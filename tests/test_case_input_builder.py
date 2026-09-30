"""Tests for the Parquet -> backtest case-input builder (13-09, M4, D-17..D-22).

Every test publishes generated whole-day fixtures through the REAL immutable
publishers (`publish_batch`, `publish_mark_batch`) and the collector's tick
writers, so the builder reads exactly the layout production writes. The
module-scoped store is built once; tests that mutate a store work on a copy.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_usdm import FundingTick, Kline, MarkKline, OiSnapshot
from src.data import case_input as ci
from src.data.collector import _write_funding_tick, _write_oi_snapshot
from src.data.coverage import GapRange
from src.data.store import publish_batch, publish_mark_batch

SYMBOL = "BTCUSDT"
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 4, tzinfo=UTC)
AS_OF = date(2026, 9, 30)
FIXTURES = Path(__file__).parent / "fixtures" / "phase6"

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


def _kline(interval: str, open_ms: int) -> Kline:
    step = _STEP_MS[interval]
    p = _price(open_ms)
    return Kline(
        symbol=SYMBOL,
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


def _mark(open_ms: int) -> MarkKline:
    p = _price(open_ms)
    return MarkKline(
        symbol=SYMBOL,
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
) -> None:
    """Publish whole UTC days for BTCUSDT through the real writers.

    `skip_1m_hour` leaves the sixty 1m trade bars of that hour unpublished.
    """
    skipped: set[int] = set()
    if skip_1m_hour is not None:
        first = _ms(skip_1m_hour)
        skipped = set(range(first, first + 3_600_000, 60_000))
    for interval in ("1h", "4h", "1m"):
        publish_batch(
            [
                _kline(interval, ms)
                for ms in _slots(start, end, interval)
                if not (interval == "1m" and ms in skipped)
            ],
            interval=interval,
            symbol=SYMBOL,
            raw_root=raw_root,
        )
    publish_mark_batch(
        [_mark(ms) for ms in _slots(start, end, "1m")],
        interval="1m",
        symbol=SYMBOL,
        raw_root=raw_root,
    )
    for ms in range(_ms(start), _ms(end), 8 * 3_600_000):
        _write_funding_tick(
            FundingTick(
                symbol=SYMBOL,
                funding_time_utc=_from_ms(ms),
                funding_rate=Decimal("0.0001"),
                mark_price=Decimal("100.50"),
            ),
            raw_root,
        )
    for ms in range(_ms(start), _ms(end), 300_000):
        _write_oi_snapshot(
            OiSnapshot(
                symbol=SYMBOL,
                observed_at_utc=_from_ms(ms),
                open_interest=Decimal("12345.5"),
            ),
            raw_root,
        )


@pytest.fixture(scope="module")
def base_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("case_input_store") / "raw"
    build_store(root)
    return root


@pytest.fixture
def store(tmp_path: Path, base_store: Path) -> Path:
    """A private, mutable copy of the module store."""
    dest = tmp_path / "raw"
    shutil.copytree(base_store, dest)
    return dest


def _build(raw_root: Path, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "symbol": SYMBOL,
        "start_utc": START,
        "end_utc": END,
        "as_of_day_utc": AS_OF,
    }
    kwargs.update(overrides)
    return ci.build_case_input_data(raw_root, **kwargs)


def _scenario() -> dict[str, Any]:
    case = json.loads(
        (FIXTURES / "intrabar_both_touched" / "input.json").read_text(encoding="utf-8")
    )
    for key in ("strategy_bars", "context_bars", "intrabar_1m_map"):
        case.pop(key)
    return case


# --------------------------------------------------------------------------- #
# Task 1 - tracer: published Parquet -> builder -> simulator + assemble.
# --------------------------------------------------------------------------- #


def test_builder_reads_published_partitions(base_store: Path) -> None:
    data = _build(base_store)
    assert len(data.strategy_bars) == 72
    assert len(data.context_bars) == 18
    opens = [b["open_time_utc"] for b in data.strategy_bars]
    assert opens == sorted(opens)
    ctx_opens = [b["open_time_utc"] for b in data.context_bars]
    assert ctx_opens == sorted(ctx_opens)
    assert len(data.intrabar_1m_map) == 72
    for minutes in data.intrabar_1m_map.values():
        assert minutes is not None
        assert len(minutes) == 60
    assert len(data.mark_bars_1m) == 4320
    assert len(data.funding) == 9
    assert len(data.open_interest) == 864
    assert re.fullmatch(r"[0-9a-f]{64}", data.dataset_id)
    assert data.allowed_gaps == ()


def test_bar_dicts_are_string_typed_and_keys_match_close_time(base_store: Path) -> None:
    data = _build(base_store)
    for bar in (*data.strategy_bars, *data.context_bars):
        assert set(bar) == BAR_KEYS
        assert all(isinstance(v, str) for v in bar.values())
        # ISO timestamps, tz-aware UTC.
        assert datetime.fromisoformat(bar["open_time_utc"]).utcoffset() == timedelta(0)
    for bar, key in zip(data.strategy_bars, data.intrabar_1m_map, strict=True):
        assert key == f"BTCUSDT|{bar['close_time_utc']}"
    for minutes in data.intrabar_1m_map.values():
        assert minutes is not None
        for minute in minutes:
            assert set(minute) == BAR_KEYS
            assert minute["interval"] == "1m"
    # Decimal values are plain (never scientific) strings.
    first = data.strategy_bars[0]
    assert Decimal(first["open"]) == _price(_ms(START))
    assert "E" not in first["open"].upper()


def test_builder_output_runs_through_simulator_and_assemble(base_store: Path) -> None:
    from src.backtest.costs import build_cost_model
    from src.backtest.experiment import assemble
    from src.backtest.simulator import run

    data = _build(base_store)
    case = data.to_case_input(**_scenario())
    assert case["dataset_id"] == data.dataset_id
    assert len(case["strategy_bars"]) == 72
    result = run(case)
    assert "trades" in result

    identity = json.loads(
        (FIXTURES / "registry_identity" / "input.json").read_text(encoding="utf-8")
    )
    cost = dict(identity["cost_model"])
    cost["partial_fill_fraction"] = "0.5"
    record = assemble(
        parameter_set_id="baseline-v3",
        strategy_id=identity["strategy_id"],
        strategy_version=identity["strategy_version"],
        data_snapshot_id=data.dataset_id,
        code_version="13-09-test",
        cost_model=build_cost_model(cost),
        time_range_start_utc=data.start_utc,
        time_range_end_utc=data.end_utc,
        universe=[SYMBOL],
        run_type="CANDIDATE",
    )
    assert record.data_snapshot_id == data.dataset_id


def test_to_case_input_refuses_builder_key_collision(base_store: Path) -> None:
    data = _build(base_store)
    with pytest.raises(ci.CaseInputError):
        data.to_case_input(strategy_bars=[], **_scenario())


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
    data = _build(gap_store, end_utc=DAY_END, allow_gaps=(gap, unrelated))
    assert data.allowed_gaps == (gap,)
    close = GAP_HOUR + timedelta(hours=1) - timedelta(milliseconds=1)
    key = f"BTCUSDT|{close.isoformat()}"
    assert data.intrabar_1m_map[key] is None
    # Every other hour keeps its full 60 one-minute candles.
    others = [v for k, v in data.intrabar_1m_map.items() if k != key]
    assert others
    assert all(v is not None and len(v) == 60 for v in others)
    exported = data.to_case_input(**_scenario())["allowed_gaps"]
    assert exported == [
        {
            "series": "intrabar_1m",
            "symbol": SYMBOL,
            "interval": "1m",
            "start_utc": gap.start_utc.isoformat(),
            "end_utc": gap.end_utc.isoformat(),
            "missing": 60,
        }
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
