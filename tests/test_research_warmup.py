"""Research warm-up (plan 16-60, review finding B3-CR-01, user option A of 2026-10-16).

Every research window is built from a case that holds `RESEARCH_WARMUP_SPAN` of candle history
before the window start, for the indicators only: `data_window` and the minute source stay at the
window, the engine evaluates no signal before the window start, the span never reaches the
Holdout and never starts before `development_start_utc` (so the Development window starts cold,
and the run says so in one neutral line). The span is a code constant covered by
`SIMULATOR_SEMANTICS_VERSION` (16-DEC-V250 item 1, 16-DEC-FIXPLANS.md 16-60 Q0 = accept 50 days).

All stores are synthetic and live in tmp_path; nothing touches the network or the real data root.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_usdm import FundingTick
from src.backtest import engine as engine_module
from src.backtest import semantics, simulator
from src.backtest.experiment import CodeVersion
from src.core.features import _EMA_SLOW_PERIOD
from src.data.case_input import ENGINE_SERIES, TerminalDeclaration, build_case_input_data
from src.data.collector import _write_funding_tick
from src.data.minute_source import ParquetMinuteSource
from src.data.store import publish_batch, publish_mark_batch
from src.research import run as research_run
from src.research.manifest import DatasetManifest, SplitWindow, research_splits
from src.research.run import run_research

from tests.backtest_case_helpers import constraint_row
from tests.test_case_input_builder import _from_ms, _kline, _mark, _ms, _slots
from tests.test_research_runner import FAKE_COMMIT, _authorization, _grid

REPO_ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "BTCUSDT"
STORE_START = datetime(2026, 1, 1, tzinfo=UTC)
STORE_END = datetime(2026, 3, 11, tzinfo=UTC)
# Long manifest: a 59-day Development window, so the first Validation fold has 59 days of history.
DEV_END = datetime(2026, 3, 1, tzinfo=UTC)
VAL_END = datetime(2026, 3, 9, tzinfo=UTC)
HOLD_START = VAL_END
HOLD_END = STORE_END
# Short manifest: for the Development-window and whole-run tests (small windows, fast engine).
SHORT_DEV_END = datetime(2026, 1, 5, tzinfo=UTC)
SHORT_VAL_END = datetime(2026, 1, 13, tzinfo=UTC)
SPAN = semantics.RESEARCH_WARMUP_SPAN


def _build_store(root: Path, *, start: datetime, end: datetime, symbol: str = SYMBOL) -> None:
    """Publish whole UTC days through the real writers (no open interest: the engine ignores it)."""
    for interval in ("1h", "4h", "1m"):
        publish_batch(
            [_kline(interval, ms, symbol) for ms in _slots(start, end, interval)],
            interval=interval,
            symbol=symbol,
            raw_root=root,
        )
    publish_mark_batch(
        [_mark(ms, symbol) for ms in _slots(start, end, "1m")],
        interval="1m",
        symbol=symbol,
        raw_root=root,
    )
    for ms in range(_ms(start), _ms(end), 8 * 3_600_000):
        _write_funding_tick(
            FundingTick(
                symbol=symbol,
                funding_time_utc=_from_ms(ms),
                funding_rate=Decimal("0.0001"),
                mark_price=Decimal("100.50"),
            ),
            root,
        )


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("warmup_store") / "raw"
    _build_store(root, start=STORE_START, end=STORE_END)
    return root


def _manifest(
    store: Path,
    directory: Path,
    *,
    dev_end: datetime = DEV_END,
    val_end: datetime = VAL_END,
) -> DatasetManifest:
    constraints = directory / "constraints.json"
    constraints.write_text(
        json.dumps(
            {"constraint_history": [constraint_row(SYMBOL, datetime(2025, 12, 1, tzinfo=UTC))]}
        ),
        encoding="utf-8",
    )
    dataset_id = build_case_input_data(
        store,
        symbols=[SYMBOL],
        start_utc=STORE_START,
        end_utc=val_end,
        as_of_day_utc=val_end.date(),
        series=ENGINE_SERIES,
    ).dataset_id
    return DatasetManifest(
        universe_id="research-universe-v1",
        symbols=(SYMBOL,),
        dataset_id=dataset_id,
        development_start_utc=STORE_START,
        development_end_utc=dev_end,
        validation_start_utc=dev_end,
        validation_end_utc=val_end,
        holdout_start_utc=val_end,
        holdout_end_utc=STORE_END,
        strategy_interval="1h",
        context_interval="4h",
        data_source="binance-usdm-public",
        data_source_version="test-1",
        excluded_periods=(),
        known_gaps=(),
        equity=Decimal("1000"),
        risk_rate=Decimal("0.005"),
        constraint_source=str(constraints),
        constraint_sha256=hashlib.sha256(constraints.read_bytes()).hexdigest(),
    )


@dataclass
class Seen:
    """What the engine was asked to evaluate and what the simulator and builder were handed."""

    evaluations: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    builds: list[dict[str, Any]]
    sources: list[dict[str, Any]]


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> Seen:
    spy = Seen(evaluations=[], cases=[], builds=[], sources=[])
    real_evaluate = engine_module.evaluate

    def spy_evaluate(**kwargs: Any) -> Any:
        result = real_evaluate(**kwargs)
        snapshot = kwargs["snapshot"]
        spy.evaluations.append(
            {
                "symbol": snapshot.symbol,
                "setup_bars": len(snapshot.setup_candles),
                "context_bars": len(snapshot.context_candles),
                "close": snapshot.setup_candles[-1].close_time_utc,
                "reason": result.reason_code,
            }
        )
        return result

    real_build = research_run.build_case_input_data

    def spy_build(*args: Any, **kwargs: Any) -> Any:
        data = real_build(*args, **kwargs)
        spy.builds.append({"kwargs": dict(kwargs), "files": data.files})
        return data

    real_run = simulator.run

    def spy_run(case_input: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        spy.cases.append(copy.deepcopy(case_input))
        return real_run(case_input, **kwargs)

    class SpySource(ParquetMinuteSource):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            spy.sources.append(dict(kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(engine_module, "evaluate", spy_evaluate)
    monkeypatch.setattr(research_run, "build_case_input_data", spy_build)
    monkeypatch.setattr(simulator, "run", spy_run)
    monkeypatch.setattr(research_run, "ParquetMinuteSource", SpySource)
    monkeypatch.setattr(
        research_run,
        "read_code_version",
        lambda repo_root: CodeVersion(commit=FAKE_COMMIT, dirty=False),
    )
    return spy


def _fold(manifest: DatasetManifest, index: int) -> SplitWindow:
    """Validation fold `index` (0 based) of the manifest."""
    return research_splits(manifest)[1 + index]


def _simulate(manifest: DatasetManifest, store: Path, window: SplitWindow) -> tuple[str, Any]:
    grid = _grid()
    constraints = research_run._load_constraints(manifest)
    return research_run._simulate_split(
        manifest=manifest,
        grid=grid,
        point=grid.points[0],
        window=window,
        raw_root=store,
        constraints=constraints,
    )


def _first_evaluation(seen: Seen, window: SplitWindow) -> dict[str, Any]:
    inside = [e for e in seen.evaluations if e["close"] >= window.start_utc]
    assert inside, "the engine evaluated no bar of the window"
    return inside[0]


def _warmup_count(output: dict[str, Any]) -> int:
    return int(output["run_summary"]["no_trade_counts"].get("WARMUP_INSUFFICIENT", 0))


def _trim_history_hours(monkeypatch: pytest.MonkeyPatch, window: SplitWindow, hours: int) -> None:
    """Hand the simulator only `hours` of bar history before the window (hour granularity).

    The store publishes whole days, so a history that is not a whole number of days cannot be
    published; the case the runner built is trimmed on its way into the simulator instead.
    """
    real_run = simulator.run
    cutoff = window.start_utc - timedelta(hours=hours)

    def trimmed(case_input: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        case = copy.deepcopy(case_input)
        for key in ("strategy_bars", "context_bars"):
            case[key] = [
                bar for bar in case[key] if datetime.fromisoformat(bar["open_time_utc"]) >= cutoff
            ]
        return real_run(case, **kwargs)

    monkeypatch.setattr(simulator, "run", trimmed)


# --------------------------------------------------------------------------- #
# Test 2: the constant is a derivation, not a free number.
# --------------------------------------------------------------------------- #


def test_span_is_the_whole_day_ceiling_of_the_window_fullness_depth() -> None:
    hours = max(semantics.STRATEGY_WINDOW_BARS * 1, semantics.CONTEXT_WINDOW_BARS * 4)
    assert hours == 1200
    assert timedelta(days=-(-hours // 24)) == SPAN
    assert SPAN == timedelta(days=50)
    assert SPAN.seconds == 0 and SPAN.microseconds == 0  # whole days: day-partitioned files
    assert "STRUCTURAL" in (semantics.__doc__ or "") + _constant_comment()


def _constant_comment() -> str:
    source = Path(semantics.__file__).read_text(encoding="utf-8")
    start = source.index("RESEARCH_WARMUP_SPAN")
    return source[max(0, start - 1500) : start]


# --------------------------------------------------------------------------- #
# Test 1: the case holds the history, the window stays the window.
# --------------------------------------------------------------------------- #


def test_a_fold_case_holds_the_span_of_history_before_its_start(
    store: Path, tmp_path: Path, seen: Seen
) -> None:
    manifest = _manifest(store, tmp_path)
    window = _fold(manifest, 0)
    assert window.start_utc - SPAN > manifest.development_start_utc  # not clamped here

    _dataset_id, output = _simulate(manifest, store, window)

    case = seen.cases[-1]
    warm_start = window.start_utc - SPAN
    strategy_open = min(datetime.fromisoformat(b["open_time_utc"]) for b in case["strategy_bars"])
    context_open = min(datetime.fromisoformat(b["open_time_utc"]) for b in case["context_bars"])
    assert strategy_open == warm_start
    assert context_open == warm_start
    # The data window is the research window; the minute source is the research window.
    assert case["data_window"] == {
        "start_utc": window.start_utc.isoformat(),
        "end_utc": window.end_utc.isoformat(),
    }
    assert output["run_summary"]["data_window"] == case["data_window"]
    assert seen.sources[-1]["start_utc"] == window.start_utc
    assert seen.sources[-1]["end_utc"] == window.end_utc
    assert _warmup_count(output) == 0


def test_a_cold_fold_build_still_warms_up_so_the_fix_is_what_removes_the_count(
    store: Path, tmp_path: Path, seen: Seen, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(store, tmp_path)
    window = _fold(manifest, 0)
    monkeypatch.setattr(research_run, "RESEARCH_WARMUP_SPAN", timedelta(0))
    _id, cold = _simulate(manifest, store, window)
    assert _warmup_count(cold) > 0
    assert seen.cases[-1]["data_window"]["start_utc"] == window.start_utc.isoformat()


def test_the_experiment_record_is_the_window_not_the_warmup(
    store: Path, tmp_path: Path, seen: Seen
) -> None:
    manifest = _manifest(store, tmp_path)
    window = _fold(manifest, 1)
    grid = _grid()
    record, _trades = research_run._run_split(
        manifest=manifest,
        grid=grid,
        point=grid.points[0],
        window=window,
        raw_root=store,
        constraints=research_run._load_constraints(manifest),
        code_version=CodeVersion(commit=FAKE_COMMIT, dirty=False),
    )
    assert record.time_range_start_utc == window.start_utc
    assert record.time_range_end_utc == window.end_utc
    assert record.split_start_utc == window.start_utc
    assert record.split_end_utc == window.end_utc
    assert record.split_role == "VALIDATION"


# --------------------------------------------------------------------------- #
# Test 3: window fullness boundary.
# --------------------------------------------------------------------------- #


def test_history_of_exactly_the_span_gives_full_setup_and_context_windows(
    store: Path, tmp_path: Path, seen: Seen
) -> None:
    manifest = _manifest(store, tmp_path)
    window = _fold(manifest, 0)
    _simulate(manifest, store, window)
    first = _first_evaluation(seen, window)
    assert first["setup_bars"] == semantics.STRATEGY_WINDOW_BARS
    assert first["context_bars"] == semantics.CONTEXT_WINDOW_BARS
    assert first["reason"] != "WARMUP_INSUFFICIENT"


def test_one_hour_less_history_leaves_the_context_window_one_bar_short(
    store: Path, tmp_path: Path, seen: Seen, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(store, tmp_path)
    window = _fold(manifest, 0)
    hours = int(SPAN / timedelta(hours=1))
    _trim_history_hours(monkeypatch, window, hours - 1)
    _simulate(manifest, store, window)
    first = _first_evaluation(seen, window)
    assert first["context_bars"] == semantics.CONTEXT_WINDOW_BARS - 1
    assert first["setup_bars"] == semantics.STRATEGY_WINDOW_BARS


# --------------------------------------------------------------------------- #
# Test 4: the strategy's own WARMUP_INSUFFICIENT boundary.
# --------------------------------------------------------------------------- #


def test_the_strategys_own_minimum_history_decides_warmup_insufficient(
    store: Path, tmp_path: Path, seen: Seen, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strategy needs `_EMA_SLOW_PERIOD` 4h context bars (read from src/core, not typed).

    The window-fullness span of the constant (1000 x 1h, 300 x 4h) is the stricter bound and
    the one the constant uses; this test pins the strategy's own, shorter bound at the first bar
    of the fold: exactly that many 4h bars of history is enough, one hour less is not.
    """
    manifest = _manifest(store, tmp_path)
    window = _fold(manifest, 0)
    minimum_hours = _EMA_SLOW_PERIOD * 4
    assert minimum_hours < int(SPAN / timedelta(hours=1))  # the span is the stricter bound

    with monkeypatch.context() as patch:
        _trim_history_hours(patch, window, minimum_hours)
        _simulate(manifest, store, window)
    enough = _first_evaluation(seen, window)
    assert enough["context_bars"] == _EMA_SLOW_PERIOD
    assert enough["reason"] != "WARMUP_INSUFFICIENT"

    seen.evaluations.clear()
    with monkeypatch.context() as patch:
        _trim_history_hours(patch, window, minimum_hours - 1)
        _simulate(manifest, store, window)
    short = _first_evaluation(seen, window)
    assert short["context_bars"] == _EMA_SLOW_PERIOD - 1
    assert short["reason"] == "WARMUP_INSUFFICIENT"


# --------------------------------------------------------------------------- #
# Test 5: the Development window starts cold; the run says so, once.
# --------------------------------------------------------------------------- #


def test_development_window_is_clamped_at_the_dataset_start_and_starts_cold(
    store: Path, tmp_path: Path, seen: Seen
) -> None:
    manifest = _manifest(store, tmp_path, dev_end=SHORT_DEV_END, val_end=SHORT_VAL_END)
    window = research_splits(manifest)[0]
    assert window.role == "DEVELOPMENT"

    _id, output = _simulate(manifest, store, window)

    assert seen.builds[-1]["kwargs"]["start_utc"] == manifest.development_start_utc
    case = seen.cases[-1]
    first_open = min(datetime.fromisoformat(b["open_time_utc"]) for b in case["strategy_bars"])
    assert first_open == manifest.development_start_utc  # no day before the dataset start
    assert case["data_window"]["start_utc"] == manifest.development_start_utc.isoformat()
    assert _warmup_count(output) > 0  # cold: the record carries the count
    assert manifest.development_start_utc == STORE_START  # the Development start is not moved


def test_a_fold_with_less_history_than_the_span_is_clamped_at_the_dataset_start(
    store: Path, tmp_path: Path, seen: Seen
) -> None:
    manifest = _manifest(store, tmp_path, dev_end=SHORT_DEV_END, val_end=SHORT_VAL_END)
    window = _fold(manifest, 0)
    _simulate(manifest, store, window)
    assert seen.builds[-1]["kwargs"]["start_utc"] == manifest.development_start_utc


def test_the_run_prints_one_neutral_cold_start_line(
    store: Path,
    tmp_path: Path,
    seen: Seen,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _manifest(store, tmp_path, dev_end=SHORT_DEV_END, val_end=SHORT_VAL_END)
    grid = _grid()
    records = run_research(
        manifest=manifest,
        grid=grid,
        authorization=_authorization(manifest, grid),
        raw_root=store,
        output_dir=tmp_path / "experiments",
        repo_root=REPO_ROOT,
    )
    assert len(records) == 5
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith("warmup ")]
    assert len(lines) == 1, out
    line = lines[0]
    assert "DEVELOPMENT" in line and "cold" in line
    assert manifest.development_start_utc.isoformat() in line
    assert str(SPAN.days) in line
    assert re.search(r"\b(pass|fail|verdict|rank|best|winner)\w*", line, re.IGNORECASE) is None


# --------------------------------------------------------------------------- #
# Test 6: no Holdout day is read; the as-of guard is unchanged.
# --------------------------------------------------------------------------- #


def test_no_day_at_or_after_the_holdout_start_is_read_for_any_window(
    store: Path, tmp_path: Path, seen: Seen
) -> None:
    manifest = _manifest(store, tmp_path)
    holdout_day = manifest.holdout_start_utc.date().isoformat()
    for window in research_splits(manifest)[1:]:  # the Development window is long and cold
        _simulate(manifest, store, window)
    assert len(seen.builds) == 4
    for build in seen.builds:
        kwargs = build["kwargs"]
        assert kwargs["as_of_day_utc"] == manifest.validation_end_utc.date()
        assert kwargs["end_utc"] <= manifest.holdout_start_utc
        dates = [m.group(1) for f in build["files"] if (m := re.search(r"date=([\d-]{10})", f))]
        assert dates and max(dates) < holdout_day, (kwargs, max(dates))
    # The warm-up of a Validation fold reads Development days, prices only.
    first = seen.builds[0]["kwargs"]
    assert first["start_utc"] == research_splits(manifest)[1].start_utc - SPAN


# --------------------------------------------------------------------------- #
# Test 7: nothing is evaluated before the window; identity covers the days read.
# --------------------------------------------------------------------------- #


def test_no_signal_is_evaluated_before_the_window_and_the_dataset_id_covers_the_days_read(
    store: Path, tmp_path: Path, seen: Seen
) -> None:
    manifest = _manifest(store, tmp_path)
    window = _fold(manifest, 2)
    dataset_id, output = _simulate(manifest, store, window)

    assert seen.evaluations
    assert all(e["close"] >= window.start_utc for e in seen.evaluations)
    assert all(
        datetime.fromisoformat(t["signal_close_utc"]) >= window.start_utc
        for t in output["trades"]
        if t.get("signal_close_utc")
    )

    def build(start: datetime) -> str:
        return build_case_input_data(
            store,
            symbols=[SYMBOL],
            start_utc=start,
            end_utc=window.end_utc,
            as_of_day_utc=manifest.validation_end_utc.date(),
            series=ENGINE_SERIES,
        ).dataset_id

    assert dataset_id == build(window.start_utc - SPAN)
    assert dataset_id != build(window.start_utc)
    assert output["run_summary"]["dataset_id"] == dataset_id


def test_the_manifest_store_check_and_hash_do_not_move(store: Path, tmp_path: Path) -> None:
    manifest = _manifest(store, tmp_path)
    before = research_run.manifest_hash(manifest)
    research_run._check_manifest_against_store(manifest, store)  # whole range, as before
    assert research_run.manifest_hash(manifest) == before
    other = _manifest(store, tmp_path, dev_end=SHORT_DEV_END, val_end=SHORT_VAL_END)
    assert research_run.manifest_hash(other) != before


# --------------------------------------------------------------------------- #
# Test 8: a terminal declaration inside a fold's warm-up (not inside its window).
# --------------------------------------------------------------------------- #


def test_a_terminal_instant_inside_the_warmup_builds_without_a_settlement_row(
    tmp_path: Path,
) -> None:
    from tests import test_research_known_gap_reason as kg
    from tests import test_research_terminal_settlement_integration as ts
    from tests.test_case_input_builder import build_store

    root = tmp_path / "raw"
    build_store(root, start=kg.STORE_START, end=kg.VAL_END, symbols=(kg.LONG,))
    kg._publish_terminal_symbol(root, kg.TERM, kg.STORE_START, kg.CUT)
    observed = kg.STORE_START - timedelta(days=30)
    constraints = tmp_path / "constraints.json"
    constraints.write_text(
        json.dumps(
            {
                "constraint_history": [
                    constraint_row(kg.LONG, observed),
                    constraint_row(kg.TERM, observed),
                ]
            }
        ),
        encoding="utf-8",
    )
    declaration = TerminalDeclaration(
        symbol=kg.TERM, reason=kg.REASON, terminal_at_utc=kg.CUT, source_url=kg.SOURCE_URL
    )
    dataset_id = build_case_input_data(
        root,
        symbols=[kg.LONG, kg.TERM],
        start_utc=kg.STORE_START,
        end_utc=kg.VAL_END,
        as_of_day_utc=kg.VAL_END.date(),
        series=ENGINE_SERIES,
        terminal_declarations=(declaration,),
    ).dataset_id
    world = ts.World(
        store=root,
        constraint_source=str(constraints),
        constraint_sha256=hashlib.sha256(constraints.read_bytes()).hexdigest(),
        dataset_id=dataset_id,
        declaration=declaration,
    )
    captured = ts._run(world, tmp_path, "run", ts.LOWER_BASE)

    folds = research_splits(captured.manifest)[1:]
    assert kg.CUT < folds[0].start_utc  # T lies in Development, i.e. in the fold's warm-up
    for window, case, output in zip(folds, captured.cases[1:], captured.outputs[1:], strict=True):
        assert "terminal_settlements" not in case
        assert case["data_window"]["start_utc"] == window.start_utc.isoformat()
        assert "settlement_count" not in output["run_summary"]
        assert all(t["exit_kind"] != "SETTLEMENT" for t in output["trades"])
    # The terminal symbol's bars before T reached the first fold as history.
    first_case = captured.cases[1]
    term_bars = [b for b in first_case["strategy_bars"] if b["symbol"] == kg.TERM]
    assert term_bars
    assert min(datetime.fromisoformat(b["open_time_utc"]) for b in term_bars) == kg.STORE_START


# --------------------------------------------------------------------------- #
# The case-input keyword that keeps the window at the window.
# --------------------------------------------------------------------------- #


def test_to_case_input_window_start_keyword_is_validated(store: Path) -> None:
    from src.data.case_input import CaseInputError

    start = STORE_START
    end = STORE_START + timedelta(days=3)
    data = build_case_input_data(
        store,
        symbols=[SYMBOL],
        start_utc=start,
        end_utc=end,
        as_of_day_utc=VAL_END.date(),
        series=ENGINE_SERIES,
    )
    scenario: dict[str, Any] = {"strategy_id": "trend-pullback"}
    default = data.to_case_input(**scenario)
    assert default["data_window"]["start_utc"] == start.isoformat()  # unchanged default
    later = start + timedelta(days=1)
    moved = data.to_case_input(data_window_start_utc=later, **scenario)
    assert moved["data_window"] == {"start_utc": later.isoformat(), "end_utc": end.isoformat()}
    assert moved["strategy_bars"] == default["strategy_bars"]  # the bars are the built range
    for bad in (start - timedelta(days=1), end, datetime(2026, 1, 2), end + timedelta(days=1)):
        with pytest.raises(CaseInputError):
            data.to_case_input(data_window_start_utc=bad, **scenario)
