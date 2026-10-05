"""Tests for the Parquet -> backtest case-input builder (13-09, M4, D-17..D-22).

Every test publishes generated whole-day fixtures through the REAL immutable
publishers (`publish_batch`, `publish_mark_batch`) and the collector's tick
writers, so the builder reads exactly the layout production writes. The
module-scoped store is built once; tests that mutate a store work on a copy.
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_usdm import FundingTick, Kline, MarkKline, OiSnapshot
from src.backtest.case import CASE_INPUT_SCHEMA, parse_case_input
from src.backtest.engine import simulate
from src.backtest.semantics import FUNDING_JITTER, FUNDING_MAX_CADENCE
from src.data import case_input as ci
from src.data.collector import _write_funding_tick, _write_oi_snapshot
from src.data.coverage import DEFAULT_FUNDING_INTERVAL_MS, FUNDING_JITTER_MS, GapRange
from src.data.minute_source import ParquetMinuteSource
from src.data.store import publish_batch, publish_mark_batch
from src.risk.gating import evaluate_risk

from tests.backtest_case_helpers import DEFAULT_COST_MODEL, constraint_row, scripted_plan

SYMBOL = "BTCUSDT"
OTHER = "ETHUSDT"
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 4, tzinfo=UTC)
AS_OF = date(2026, 9, 30)

BAR_KEYS = {
    "symbol",
    "interval",
    "open_time_utc",
    "close_time_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
}

_STEP_MS = {"1m": 60_000, "1h": 3_600_000, "4h": 14_400_000}


def _price(open_ms: int) -> Decimal:
    return Decimal(100) + Decimal((open_ms // 60_000) % 97) / Decimal(100)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _kline(interval: str, open_ms: int, symbol: str = SYMBOL) -> Kline:
    step = _STEP_MS[interval]
    p = _price(open_ms)
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_from_ms(open_ms),
        close_time_utc=_from_ms(open_ms + step - 1),
        open=p,
        high=p + Decimal("0.05"),
        low=p - Decimal("0.05"),
        close=p,
        volume=Decimal("1.5"),
        quote_volume=p * Decimal("1.5"),
        trade_count=7,
    )


def _mark(open_ms: int, symbol: str = SYMBOL) -> MarkKline:
    p = _price(open_ms)
    return MarkKline(
        symbol=symbol,
        interval="1m",
        open_time_utc=_from_ms(open_ms),
        close_time_utc=_from_ms(open_ms + 59_999),
        open=p,
        high=p + Decimal("0.02"),
        low=p - Decimal("0.02"),
        close=p,
        price_tick_count=12,
    )


def _slots(start: datetime, end: datetime, interval: str) -> list[int]:
    step = _STEP_MS[interval]
    return list(range(_ms(start), _ms(end), step))


def build_store(
    raw_root: Path,
    *,
    start: datetime = START,
    end: datetime = END,
    skip_1m_hour: datetime | None = None,
    symbols: tuple[str, ...] = (SYMBOL,),
) -> None:
    """Publish whole UTC days for `symbols` through the real writers.

    `skip_1m_hour` leaves the sixty 1m trade bars of that hour unpublished (every symbol).
    """
    skipped: set[int] = set()
    if skip_1m_hour is not None:
        first = _ms(skip_1m_hour)
        skipped = set(range(first, first + 3_600_000, 60_000))
    for symbol in symbols:
        for interval in ("1h", "4h", "1m"):
            publish_batch(
                [
                    _kline(interval, ms, symbol)
                    for ms in _slots(start, end, interval)
                    if not (interval == "1m" and ms in skipped)
                ],
                interval=interval,
                symbol=symbol,
                raw_root=raw_root,
            )
        publish_mark_batch(
            [_mark(ms, symbol) for ms in _slots(start, end, "1m")],
            interval="1m",
            symbol=symbol,
            raw_root=raw_root,
        )
        for ms in range(_ms(start), _ms(end), 8 * 3_600_000):
            _write_funding_tick(
                FundingTick(
                    symbol=symbol,
                    funding_time_utc=_from_ms(ms),
                    funding_rate=Decimal("0.0001"),
                    mark_price=Decimal("100.50"),
                ),
                raw_root,
            )
        for ms in range(_ms(start), _ms(end), 300_000):
            _write_oi_snapshot(
                OiSnapshot(
                    symbol=symbol,
                    observed_at_utc=_from_ms(ms),
                    open_interest=Decimal("12345.5"),
                ),
                raw_root,
            )


@pytest.fixture(scope="module")
def base_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("case_input_store") / "raw"
    build_store(root, symbols=(SYMBOL, OTHER))
    return root


@pytest.fixture
def store(tmp_path: Path, base_store: Path) -> Path:
    """A private, mutable copy of the module store."""
    dest = tmp_path / "raw"
    shutil.copytree(base_store, dest)
    return dest


def _build(raw_root: Path, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "symbols": [SYMBOL],
        "start_utc": START,
        "end_utc": END,
        "as_of_day_utc": AS_OF,
    }
    if "symbol" in overrides:
        del kwargs["symbols"]
    kwargs.update(overrides)
    return ci.build_case_input_data(raw_root, **kwargs)


def _scenario(symbols: tuple[str, ...] = (SYMBOL,), **extra: Any) -> dict[str, Any]:
    """The caller-owned scenario keys of a v2 case (the store owns the market data)."""
    scenario: dict[str, Any] = {
        "strategy_id": "trend-pullback",
        "strategy_version": "v4.0.0",
        "parameter_set_id": "baseline-v5",
        "account_state": {"equity": "10000", "risk_rate": "0.005"},
        "cost_model": dict(DEFAULT_COST_MODEL),
        "constraint_history": [
            constraint_row(symbol, datetime(2026, 6, 1, tzinfo=UTC)) for symbol in symbols
        ],
    }
    scenario.update(extra)
    return scenario


# --------------------------------------------------------------------------- #
# Task 1 - published Parquet -> builder -> v2 case.
# --------------------------------------------------------------------------- #


def test_builder_reads_published_partitions(base_store: Path) -> None:
    data = _build(base_store)
    assert data.symbols == (SYMBOL,)
    assert len(data.strategy_bars) == 72
    assert len(data.context_bars) == 18
    opens = [b["open_time_utc"] for b in data.strategy_bars]
    assert opens == sorted(opens)
    ctx_opens = [b["open_time_utc"] for b in data.context_bars]
    assert ctx_opens == sorted(ctx_opens)
    assert len(data.funding) == 9
    assert len(data.open_interest) == 864
    # The default leaves the minute rows out: a ParquetMinuteSource serves them lazily.
    assert data.trade_bars_1m == ()
    assert data.mark_bars_1m == ()
    assert re.fullmatch(r"[0-9a-f]{64}", data.dataset_id)
    assert data.allowed_gaps == ()
    assert "intrabar_1m_map" not in ci.CaseInputData.__dataclass_fields__


def test_with_minute_rows_adds_trade_and_mark_rows(base_store: Path) -> None:
    data = _build(base_store, with_minute_rows=True)
    assert len(data.trade_bars_1m) == 4320
    assert len(data.mark_bars_1m) == 4320
    case = data.to_case_input(**_scenario())
    assert len(case["trade_bars_1m"]) == 4320
    assert len(case["mark_bars_1m"]) == 4320
    for row in case["trade_bars_1m"][:3]:
        assert set(row) == BAR_KEYS and row["interval"] == "1m"
    for row in case["mark_bars_1m"][:3]:
        assert set(row) == BAR_KEYS - {"volume"}
    parse_case_input(case)  # the closed v2 parser accepts the minute rows


def test_bar_dicts_are_string_typed(base_store: Path) -> None:
    data = _build(base_store)
    for bar in (*data.strategy_bars, *data.context_bars):
        assert set(bar) == BAR_KEYS
        assert all(isinstance(v, str) for v in bar.values())
        # ISO timestamps, tz-aware UTC.
        assert datetime.fromisoformat(bar["open_time_utc"]).utcoffset() == timedelta(0)
    # Decimal values are plain (never scientific) strings.
    first = data.strategy_bars[0]
    assert Decimal(first["open"]) == _price(_ms(START))
    assert "E" not in first["open"].upper()


def test_multi_symbol_output_carries_the_v2_keys(base_store: Path) -> None:
    data = _build(base_store, symbols=[OTHER, SYMBOL])
    assert data.symbols == (SYMBOL, OTHER)
    case = data.to_case_input(**_scenario((SYMBOL, OTHER)))

    assert case["case_input_schema"] == CASE_INPUT_SCHEMA == "backtest-case/2"
    assert case["symbols"] == [SYMBOL, OTHER]
    assert {b["symbol"] for b in case["strategy_bars"]} == {SYMBOL, OTHER}
    assert {b["symbol"] for b in case["context_bars"]} == {SYMBOL, OTHER}
    assert len(case["strategy_bars"]) == 144 and len(case["context_bars"]) == 36
    assert [r["symbol"] for r in case["funding"]].count(SYMBOL) == 9
    assert [r["symbol"] for r in case["funding"]].count(OTHER) == 9
    assert case["data_window"] == {"start_utc": START.isoformat(), "end_utc": END.isoformat()}
    assert case["dataset_id"] == data.dataset_id
    assert case["allowed_gaps"] == []
    assert "intrabar_1m_map" not in case
    assert "mark_price_bars" not in case
    assert "open_interest" not in case  # OI stays inert; the closed v2 schema has no key for it
    assert "trade_bars_1m" not in case and "mark_bars_1m" not in case

    parsed = parse_case_input(case)  # the closed v2 parser accepts the builder output
    assert parsed.symbols == (SYMBOL, OTHER)
    assert parsed.dataset_id == data.dataset_id

    # Two symbols hash a different file set than one.
    assert data.dataset_id != _build(base_store).dataset_id


def test_single_symbol_keyword_is_still_accepted(base_store: Path) -> None:
    by_keyword = _build(base_store, symbol=SYMBOL)
    assert by_keyword.symbols == (SYMBOL,)
    assert by_keyword.dataset_id == _build(base_store).dataset_id
    with pytest.raises(ci.CaseInputError):
        _build(base_store, symbol=SYMBOL, symbols=[SYMBOL])
    with pytest.raises(ci.CaseInputError):
        ci.build_case_input_data(base_store, start_utc=START, end_utc=END, as_of_day_utc=AS_OF)
    with pytest.raises(ci.CaseInputError):
        _build(base_store, symbols=[SYMBOL, SYMBOL])
    with pytest.raises(ci.CaseInputError):
        _build(base_store, symbols=[])


def test_builder_output_runs_through_the_engine_with_a_lazy_minute_source(
    base_store: Path,
) -> None:
    """Published partitions -> builder -> `engine.simulate` + ParquetMinuteSource, twice."""
    signal_close = datetime(2026, 7, 1, 9, 59, 59, 999000, tzinfo=UTC)
    outputs: list[dict[str, Any]] = []
    for _ in range(2):
        data = _build(base_store)
        scenario = _scenario(scripted_plans=[scripted_plan(SYMBOL, signal_close, "sig-e2e")])
        case = data.to_case_input(**scenario)
        source = ParquetMinuteSource(
            base_store, symbols=list(data.symbols), start_utc=START, end_utc=END, cache_days=2
        )
        outputs.append(simulate(case, risk_fn=evaluate_risk, minute_source=source))

        # Every minute partition the lazy source opened is covered by the case's dataset id.
        root = base_store.resolve()
        opened = {path.resolve().relative_to(root).as_posix() for path in source.files_read()}
        assert opened
        assert opened <= set(data.files)
        files = [base_store / rel for rel in data.files]
        assert ci.dataset_identity(base_store, files) == data.dataset_id
        assert outputs[-1]["run_summary"]["dataset_id"] == data.dataset_id

    assert outputs[0] == outputs[1]
    assert len(outputs[0]["trades"]) == 1
    assert outputs[0]["trades"][0]["signal_id"] == "sig-e2e"


def test_to_case_input_refuses_builder_key_collision(base_store: Path) -> None:
    data = _build(base_store)
    for key in ("strategy_bars", "funding", "symbols", "data_window", "dataset_id", "allowed_gaps"):
        with pytest.raises(ci.CaseInputError):
            data.to_case_input(**{**_scenario(), key: []})
    # The caller-owned scenario keys never collide with the builder keys.
    case = data.to_case_input(**_scenario(scripted_plans=[]))
    for key in ("constraint_history", "account_state", "cost_model", "scripted_plans"):
        assert key in case


# --------------------------------------------------------------------------- #
# Task 2 - fail-closed gap policy (D-19) and range refusal (D-17).
# --------------------------------------------------------------------------- #

DAY_END = datetime(2026, 7, 2, tzinfo=UTC)
GAP_HOUR = datetime(2026, 7, 1, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def gap_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One whole day whose 10:00-11:00 one-minute trade bars were never published."""
    root = tmp_path_factory.mktemp("case_input_gap") / "raw"
    build_store(root, start=START, end=DAY_END, skip_1m_hour=GAP_HOUR)
    return root


def _gap(start: datetime, minutes: int) -> Any:
    return GapRange(
        series="intrabar_1m",
        symbol=SYMBOL,
        interval="1m",
        start_utc=start,
        end_utc=start + timedelta(minutes=minutes),
        missing=minutes,
    )


def test_builder_refuses_unresolved_gap(gap_store: Path) -> None:
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build(gap_store, end_utc=DAY_END)
    assert isinstance(excinfo.value, ci.CaseInputError)
    assert list(excinfo.value.gaps) == [_gap(GAP_HOUR, 60)]


def test_allowed_gap_is_recorded_on_output(gap_store: Path) -> None:
    gap = _gap(GAP_HOUR, 60)
    unrelated = _gap(GAP_HOUR + timedelta(hours=2), 60)
    data = _build(gap_store, end_utc=DAY_END, allow_gaps=(gap, unrelated), with_minute_rows=True)
    assert data.allowed_gaps == (gap,)
    # The hole stays a hole in the minute rows: nothing is padded.
    assert len(data.trade_bars_1m) == 1440 - 60
    assert len(data.mark_bars_1m) == 1440
    exported = data.to_case_input(**_scenario())["allowed_gaps"]
    assert exported == [
        {
            "series": "intrabar_1m",
            "symbol": SYMBOL,
            "start_utc": gap.start_utc.isoformat(),
            "end_utc": gap.end_utc.isoformat(),
            "missing": 60,
        }
    ]


# --------------------------------------------------------------------------- #
# Funding cadence (D-36, D-15): per-symbol cadence, one tolerance with the engine.
# --------------------------------------------------------------------------- #

HOUR_MS = 3_600_000
FUNDING_END = datetime(2026, 7, 26, tzinfo=UTC)


def _funding_store(root: Path, ticks: dict[str, list[datetime]]) -> None:
    for symbol, instants in ticks.items():
        for when in instants:
            _write_funding_tick(
                FundingTick(
                    symbol=symbol,
                    funding_time_utc=when,
                    funding_rate=Decimal("0.0001"),
                    mark_price=Decimal("100.50"),
                ),
                root,
            )


def _every(first: datetime, hours: int, count: int) -> list[datetime]:
    return [first + timedelta(hours=hours * i) for i in range(count)]


def test_builder_funding_tolerance_equals_the_coverage_constants() -> None:
    assert FUNDING_MAX_CADENCE == timedelta(milliseconds=DEFAULT_FUNDING_INTERVAL_MS)
    assert FUNDING_JITTER == timedelta(milliseconds=FUNDING_JITTER_MS)
    assert ci.FUNDING_TOLERANCE_MS == DEFAULT_FUNDING_INTERVAL_MS + FUNDING_JITTER_MS


def test_infer_funding_cadence_from_observed_spacing() -> None:
    eight = [i * 8 * HOUR_MS + (i % 3) * 1_000 for i in range(10)]
    four = [i * 4 * HOUR_MS - (i % 2) * 2_000 for i in range(10)]
    assert ci.infer_funding_cadence_ms(eight) == 8 * HOUR_MS
    assert ci.infer_funding_cadence_ms(four) == 4 * HOUR_MS
    # A missed instant in a 4 h series (one 8 h spacing) does not change the cadence.
    missed = [t for i, t in enumerate(four) if i != 5]
    assert ci.infer_funding_cadence_ms(missed) == 4 * HOUR_MS
    # Nothing to infer from: the default 8 h cadence.
    assert ci.infer_funding_cadence_ms([]) == 8 * HOUR_MS
    assert ci.infer_funding_cadence_ms([0]) == 8 * HOUR_MS


def test_four_hour_funding_with_one_missed_instant_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    day = datetime(2026, 7, 1, tzinfo=UTC)
    four_hourly = [t for t in _every(day, 4, 6) if t != day + timedelta(hours=12)]
    _funding_store(root, {SYMBOL: _every(day, 8, 3), OTHER: four_hourly})
    data = _build(root, symbols=[SYMBOL, OTHER], end_utc=DAY_END, series=("funding",))
    assert data.allowed_gaps == ()
    assert [r["symbol"] for r in data.funding].count(OTHER) == 5
    assert [r["symbol"] for r in data.funding].count(SYMBOL) == 3


def test_a_long_funding_hole_fails_closed_unless_allowed_and_is_recorded(
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw"
    first_block = _every(datetime(2026, 7, 1, tzinfo=UTC), 8, 3)
    second_block = _every(datetime(2026, 7, 22, tzinfo=UTC), 8, 12)
    _funding_store(root, {SYMBOL: [*first_block, *second_block]})

    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build(root, end_utc=FUNDING_END, series=("funding",))
    hole = GapRange(
        series="funding",
        symbol=SYMBOL,
        interval="8h",
        start_utc=datetime(2026, 7, 2, tzinfo=UTC),
        end_utc=datetime(2026, 7, 22, tzinfo=UTC),
        missing=60,
    )
    assert list(excinfo.value.gaps) == [hole]

    data = _build(root, end_utc=FUNDING_END, series=("funding",), allow_gaps=(hole,))
    assert data.allowed_gaps == (hole,)
    case = data.to_case_input(**_scenario())
    assert case["allowed_gaps"] == [
        {
            "series": "funding",
            "symbol": SYMBOL,
            "start_utc": hole.start_utc.isoformat(),
            "end_utc": hole.end_utc.isoformat(),
            "missing": 60,
        }
    ]
    assert parse_case_input(case).allowed_gaps[0].series == "funding"


def test_a_four_hour_series_with_a_long_hole_names_its_own_cadence(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    ticks = [
        *_every(datetime(2026, 7, 1, tzinfo=UTC), 4, 6),
        *_every(datetime(2026, 7, 4, tzinfo=UTC), 4, 6),
    ]
    _funding_store(root, {SYMBOL: ticks})
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build(root, end_utc=datetime(2026, 7, 5, tzinfo=UTC), series=("funding",))
    assert [(g.interval, g.start_utc, g.end_utc) for g in excinfo.value.gaps] == [
        ("4h", datetime(2026, 7, 2, tzinfo=UTC), datetime(2026, 7, 4, tzinfo=UTC))
    ]


def test_builder_never_pads_an_empty_store(tmp_path: Path) -> None:
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build(tmp_path / "empty_raw", end_utc=DAY_END)
    assert {g.series for g in excinfo.value.gaps} >= {"trade", "mark_1m", "funding"}


def test_range_after_as_of_day_is_refused(base_store: Path) -> None:
    with pytest.raises(ci.CaseInputRangeError):
        _build(base_store, as_of_day_utc=date(2026, 7, 3))
    # Ending exactly at the start of the as-of day is allowed.
    data = _build(base_store, as_of_day_utc=date(2026, 7, 4))
    assert data.end_utc == END


def test_naive_or_non_midnight_start_is_refused(base_store: Path) -> None:
    with pytest.raises(ci.CaseInputRangeError):
        _build(base_store, start_utc=datetime(2026, 7, 1))
    with pytest.raises(ci.CaseInputRangeError):
        _build(base_store, start_utc=datetime(2026, 7, 1, 6, tzinfo=UTC))
    with pytest.raises(ci.CaseInputRangeError):
        _build(base_store, end_utc=START)


# --------------------------------------------------------------------------- #
# Task 3 - determinism of the builder and its dataset identity (D-18, D-20).
# --------------------------------------------------------------------------- #


def test_dataset_id_is_deterministic(base_store: Path) -> None:
    """Same store, same call: equal dataset_id and byte-equal canonical payloads (D-20)."""
    from src.domain.canonical import canonical_bytes, sha256_hex

    first = _build(base_store)
    second = _build(base_store)
    assert first.dataset_id == second.dataset_id
    a = first.to_case_input(**_scenario())
    b = second.to_case_input(**_scenario())
    assert canonical_bytes(a) == canonical_bytes(b)
    assert sha256_hex(a) == sha256_hex(b)


def test_dataset_id_changes_with_any_partition(store: Path) -> None:
    baseline = _build(store).dataset_id

    # One changed close price in one re-written day file (immutable: unlink + republish).
    day_file = store / "interval=1h" / f"symbol={SYMBOL}" / "date=2026-07-02" / "part.parquet"
    day_file.unlink()
    changed = [
        _kline("1h", ms)
        if ms != _ms(datetime(2026, 7, 2, 5, tzinfo=UTC))
        else Kline(
            symbol=SYMBOL,
            interval="1h",
            open_time_utc=_from_ms(ms),
            close_time_utc=_from_ms(ms + 3_600_000 - 1),
            open=_price(ms),
            high=_price(ms) + Decimal("0.05"),
            low=_price(ms) - Decimal("0.05"),
            close=_price(ms) + Decimal("0.01"),
            volume=Decimal("1.5"),
            quote_volume=Decimal("150"),
            trade_count=7,
        )
        for ms in _slots(datetime(2026, 7, 2, tzinfo=UTC), datetime(2026, 7, 3, tzinfo=UTC), "1h")
    ]
    publish_batch(changed, interval="1h", symbol=SYMBOL, raw_root=store)
    after_rewrite = _build(store).dataset_id
    assert after_rewrite != baseline

    # One OI tick file removed (10 minute spacing is still inside the gap bound).
    oi_dir = store / "data_class=oi" / f"symbol={SYMBOL}" / "date=2026-07-02"
    sorted(oi_dir.glob("tick-*.parquet"))[100].unlink()
    after_remove = _build(store).dataset_id
    assert after_remove not in (baseline, after_rewrite)


def test_dataset_identity_ignores_file_order(base_store: Path) -> None:
    data = _build(base_store)
    files = [base_store / rel for rel in data.files]
    assert ci.dataset_identity(base_store, files) == data.dataset_id
    assert ci.dataset_identity(base_store, list(reversed(files))) == data.dataset_id


def test_dataset_identity_paths_are_posix_relative(base_store: Path) -> None:
    """The hashed payload holds forward-slash paths relative to raw_root, nothing else."""
    import hashlib

    from src.domain.canonical import sha256_hex

    data = _build(base_store)
    assert data.files == tuple(sorted(data.files))
    for rel in data.files:
        assert "\\" not in rel
        assert ":" not in rel
        assert not rel.startswith("/")
    payload = {
        "files": [
            {
                "path": rel,
                "sha256": hashlib.sha256((base_store / rel).read_bytes()).hexdigest(),
            }
            for rel in data.files
        ]
    }
    assert sha256_hex(payload) == data.dataset_id


def test_case_input_module_has_no_clock_or_float() -> None:
    import ast

    tree = ast.parse(Path(ci.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                pytest.fail(f"float() call at line {node.lineno}")
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and (
                (base.id == "datetime" and node.attr in {"now", "utcnow", "today"})
                or (base.id == "date" and node.attr == "today")
                or (base.id == "time" and node.attr in {"time", "time_ns"})
            ):
                pytest.fail(f"wall-clock reference {base.id}.{node.attr} at line {node.lineno}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            module = getattr(node, "module", None)
            assert "time" not in names and module != "time"


def test_builder_rejects_unsafe_symbol_or_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _no_fs(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("filesystem touched before argument validation")

    monkeypatch.setattr(ci, "_kline_files", _no_fs)
    monkeypatch.setattr(ci, "_tick_files", _no_fs)
    root = tmp_path / "raw"
    with pytest.raises(ci.CaseInputError):
        _build(root, symbol="../BTCUSDT")
    with pytest.raises(ci.CaseInputError):
        _build(root, symbol="btcusdt")
    with pytest.raises(ci.CaseInputError):
        _build(root, strategy_interval="2h")
    with pytest.raises(ci.CaseInputError):
        _build(root, context_interval="../4h")
    with pytest.raises(ci.CaseInputError):
        _build(root, series=("trade", "bogus"))
