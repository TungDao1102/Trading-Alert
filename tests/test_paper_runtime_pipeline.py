"""Per-closed-bar pipeline of the paper runtime (Phase 16, plan 16-24).

Task 1 (tracer): a closed LIVE_WS 1h bar after REST warm-up is evaluated once and recorded as one
replayable PAPER_BAR_PROCESSED heartbeat; warm-up bars never evaluate; a duplicate delivery writes
nothing; a warm-up reject is recorded and not evaluated; a bar closing after the injected tick
time (host clock behind) is reported as dropped FUTURE_CLOSE and neither evaluated nor recorded.

No network is touched. The fixture is the Phase 7 parity history (250 1h bars, one risk-passing
setup on the last bar, 250 4h context bars), the same one the decision-surface tests use.
"""

from __future__ import annotations

import ast
import itertools
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.core.types import Candle
from src.domain.registry import ParameterSet
from src.paper import pipeline as pipeline_module
from src.paper.bars import BarBuffers
from src.paper.freeze import StreamEpoch, load_parameter_set_at_root, resolve_registry_root
from src.paper.loop import BarOutcome
from src.paper.pipeline import BarPipeline, DroppedBar, HeldBar, PipelineResult
from src.paper.runtime_state import (
    InMemoryRuntimeState,
    RuntimeRecord,
    record_sort_key,
    runtime_event_id,
)
from src.paper.surface import decision_surface
from src.paper.vocabulary import DropReason, GapReason, RuntimeEventType, SourceTag, TaggedBar

from tests.test_paper_decision_surface import (
    PASSING_BAR,
    _all_bars,
    _bar_context,
    _case_input,
    _context_bars,
    _per_bar_context,
    _setup_bars,
)

PIPELINE_SOURCE = Path(__file__).resolve().parent.parent / "src" / "paper" / "pipeline.py"
ONE_MS = timedelta(milliseconds=1)
EPOCH_ID = "a" * 64


def _tagged(candle: Candle, source: SourceTag) -> TaggedBar:
    return TaggedBar(
        symbol=candle.symbol,
        interval=candle.interval,
        open_time_utc=candle.open_time_utc,
        close_time_utc=candle.close_time_utc,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        source=source,
    )


def _parameter_set(case: dict[str, Any]) -> ParameterSet:
    return load_parameter_set_at_root(
        case["strategy_id"], case["parameter_set_id"], resolve_registry_root()
    )


def _epoch(case: dict[str, Any], parameter_set: ParameterSet, opened: Candle) -> StreamEpoch:
    return StreamEpoch(
        epoch_id=EPOCH_ID,
        strategy_id=case["strategy_id"],
        parameter_set_id=case["parameter_set_id"],
        parameter_set_hash=parameter_set.parameter_set_hash,
        opened_at_utc=opened.close_time_utc,
    )


class Fixture:
    """A pipeline over the parity fixture with its pieces exposed to the tests."""

    def __init__(
        self,
        *,
        warmup_1h: int | None = None,
        fetch: Callable[[str, datetime], TaggedBar | None] | None = None,
    ) -> None:
        self.fetch_calls: list[tuple[str, datetime]] = []
        self._fetch = fetch
        self.case = _case_input()
        self.setup = _setup_bars(self.case)
        self.context = _context_bars(self.case)
        self.parameter_set = _parameter_set(self.case)
        self.state = InMemoryRuntimeState()
        self.buffers = BarBuffers()
        self.pipeline = BarPipeline(
            epoch=_epoch(self.case, self.parameter_set, self.setup[-1]),
            parameter_set=self.parameter_set,
            context_factory=lambda candle: _bar_context(self.case, candle.close_time_utc),
            buffers=self.buffers,
            state=self.state,
            sibling_4h_wait_seconds=30,
            fetch_4h_bar=self._fetch_4h_bar,
        )
        self.last_1h = self.setup[PASSING_BAR]
        # The warm-up history: every 1h bar before the passing one, and every 4h bar.
        history_1h = self.setup[:PASSING_BAR] if warmup_1h is None else self.setup[:warmup_1h]
        self.warmup = [
            *(_tagged(c, SourceTag.REST_WARMUP) for c in history_1h),
            *(_tagged(c, SourceTag.REST_WARMUP) for c in self.context),
        ]
        self.now = self.last_1h.close_time_utc + timedelta(seconds=2)

    def _fetch_4h_bar(self, symbol: str, close: datetime) -> TaggedBar | None:
        self.fetch_calls.append((symbol, close))
        return None if self._fetch is None else self._fetch(symbol, close)

    def warm_up(self) -> PipelineResult:
        return self.pipeline.handle(self.warmup, now_utc=self.now)

    def live(self, candle: Candle | None = None) -> TaggedBar:
        return _tagged(candle or self.last_1h, SourceTag.LIVE_WS)

    def warm(self, n_1h: int, n_4h: int | None = None) -> PipelineResult:
        """REST warm-up of the first `n_1h` 1h bars and the first `n_4h` 4h bars (default all)."""
        n_4h = len(self.context) if n_4h is None else n_4h
        bars = [
            *(_tagged(c, SourceTag.REST_WARMUP) for c in self.setup[:n_1h]),
            *(_tagged(c, SourceTag.REST_WARMUP) for c in self.context[:n_4h]),
        ]
        return self.pipeline.handle(bars, now_utc=self.now)

    def gap_records(self) -> list[RuntimeRecord]:
        return list(self.state.records(EPOCH_ID, {RuntimeEventType.PAPER_GAP}))

    def bar_records(self) -> list[RuntimeRecord]:
        return list(self.state.records(EPOCH_ID, {RuntimeEventType.PAPER_BAR_PROCESSED}))


@pytest.fixture
def spy_evaluations(monkeypatch: pytest.MonkeyPatch) -> list[Candle]:
    """Record every candle that reaches evaluate_closed_bar through the pipeline module."""
    seen: list[Candle] = []
    real = pipeline_module.evaluate_closed_bar

    def spy(*args: Any, **kwargs: Any) -> BarOutcome:
        seen.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "evaluate_closed_bar", spy)
    return seen


# --------------------------------------------------------------------------- #
# Test 1 - a live bar after warm-up is evaluated once and recorded.
# --------------------------------------------------------------------------- #


def test_live_bar_after_warmup_is_evaluated_once_and_recorded(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    warm = fx.warm_up()
    assert warm.evaluated == () and warm.recorded == ()

    result = fx.pipeline.handle([fx.live()], now_utc=fx.now)

    assert spy_evaluations == [fx.last_1h]
    assert len(result.evaluated) == 1
    assert result.evaluated[0].stage == "risk_passed"
    assert len(result.recorded) == 1 and result.duplicates == () and result.dropped == ()

    [record] = fx.bar_records()
    assert record is result.recorded[0]
    close = fx.last_1h.close_time_utc
    assert record.occurred_at_utc == close
    assert record.epoch_id == EPOCH_ID and record.symbol == "BTCUSDT" and record.interval == "1h"
    expected_id = runtime_event_id(
        RuntimeRecord.bar_processed(
            epoch_id=EPOCH_ID, symbol="BTCUSDT", interval="1h", close_time_utc=close
        )
    )
    assert runtime_event_id(record) == expected_id

    payload = record.payload
    assert payload["source"] == "LIVE_WS"
    assert payload["tick_time_utc"] == fx.now.isoformat()
    assert payload["stage"] == "risk_passed" and payload["reason_code"] == "OK"
    assert payload["plan_hash"] == result.evaluated[0].trade_plan.plan_hash  # type: ignore[union-attr]
    bar = payload["bar"]
    assert bar["close"] == str(fx.last_1h.close) and bar["interval"] == "1h"
    assert bar["open_time_utc"] == fx.last_1h.open_time_utc.isoformat()
    assert bar["close_time_utc"] == close.isoformat()
    assert Decimal(bar["volume"]) == fx.last_1h.volume

    # The surface carried in the heartbeat is exactly what the offline replay observes.
    case = fx.case
    replayed = decision_surface(_all_bars(case), context=_per_bar_context(case))
    [expected] = [r for r in replayed if r.interval == "1h" and r.bar_close_utc == close]
    assert dict(payload["surface"]) == expected.to_dict()


# --------------------------------------------------------------------------- #
# Test 2 - warm-up bars and forming bars never reach evaluate_closed_bar.
# --------------------------------------------------------------------------- #


def test_warmup_bars_only_extend_history_and_a_forming_bar_never_evaluates(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    result = fx.warm_up()

    assert spy_evaluations == []
    assert result.evaluated == () and result.recorded == () and result.dropped == ()
    assert fx.bar_records() == []
    assert fx.buffers.size("BTCUSDT", "1h") == PASSING_BAR
    assert fx.buffers.size("BTCUSDT", "4h") == len(fx.context)

    # A bar whose close lies an hour after the tick time is still forming.
    forming = fx.live()
    early = fx.last_1h.close_time_utc - timedelta(hours=1)
    outcome = fx.pipeline.handle([forming], now_utc=early)
    assert spy_evaluations == []
    assert outcome.evaluated == () and outcome.recorded == ()
    assert fx.bar_records() == []
    assert fx.buffers.size("BTCUSDT", "1h") == PASSING_BAR  # a forming bar is not history either


# --------------------------------------------------------------------------- #
# Test 3 - a duplicate delivery writes nothing and evaluates nothing.
# --------------------------------------------------------------------------- #


def test_a_duplicate_live_bar_is_reported_and_writes_nothing(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    fx.warm_up()
    first = fx.pipeline.handle([fx.live()], now_utc=fx.now)
    second = fx.pipeline.handle([fx.live()], now_utc=fx.now)

    assert len(first.recorded) == 1
    assert second.recorded == () and second.evaluated == ()
    assert second.duplicates == (fx.live(),)
    assert len(spy_evaluations) == 1
    assert len(fx.bar_records()) == 1

    # The same open time with different content is not a duplicate: fail closed.
    changed = Candle(
        symbol=fx.last_1h.symbol,
        interval=fx.last_1h.interval,
        open_time_utc=fx.last_1h.open_time_utc,
        close_time_utc=fx.last_1h.close_time_utc,
        open=fx.last_1h.open,
        high=fx.last_1h.high + Decimal("1"),
        low=fx.last_1h.low,
        close=fx.last_1h.close,
        volume=fx.last_1h.volume,
    )
    with pytest.raises(ValueError, match="conflicting duplicate bar"):
        fx.pipeline.handle([fx.live(changed)], now_utc=fx.now)
    assert len(fx.bar_records()) == 1


# --------------------------------------------------------------------------- #
# Test 4 - warm-up reject is recorded, not evaluated; purity of the module.
# --------------------------------------------------------------------------- #


def test_a_live_bar_below_the_warmup_minimum_is_recorded_and_not_evaluated(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture(warmup_1h=100)
    fx.warm_up()
    result = fx.pipeline.handle([fx.live()], now_utc=fx.now)

    assert spy_evaluations == [] and result.evaluated == ()
    [record] = fx.bar_records()
    assert record.payload["stage"] == "feed_gate"
    assert record.payload["reason_code"] == "WARMUP_INSUFFICIENT"
    assert record.payload["plan_hash"] is None
    assert record.payload["source"] == "LIVE_WS"


def test_a_stale_live_bar_is_recorded_as_data_stale_and_not_evaluated(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    fx.warm_up()
    late = fx.last_1h.close_time_utc + timedelta(seconds=61)
    fx.pipeline.handle([fx.live()], now_utc=late)

    assert spy_evaluations == []
    [record] = fx.bar_records()
    assert record.payload["stage"] == "feed_gate" and record.payload["reason_code"] == "DATA_STALE"


def test_a_live_4h_bar_extends_context_and_is_recorded_without_evaluation(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    held_back = fx.context[-1]
    fx.warmup = [
        b
        for b in fx.warmup
        if not (b.interval == "4h" and b.open_time_utc >= held_back.open_time_utc)
    ]
    fx.warm_up()
    before = fx.buffers.size("BTCUSDT", "4h")
    result = fx.pipeline.handle([_tagged(held_back, SourceTag.LIVE_WS)], now_utc=fx.now)

    assert spy_evaluations == [] and result.evaluated == ()
    assert fx.buffers.size("BTCUSDT", "4h") == before + 1
    [record] = fx.bar_records()
    assert record.interval == "4h"
    assert record.payload["stage"] == "context" and record.payload["reason_code"] == "CONTEXT_BAR"


def test_pipeline_module_imports_no_engine_execution_or_adapters() -> None:
    tree = ast.parse(PIPELINE_SOURCE.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    forbidden = ("src.backtest.engine", "src.execution", "src.adapters")
    offenders = [m for m in modules if m == "src.backtest.engine" or m.startswith(forbidden)]
    assert offenders == []
    assert "float" not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def test_pipeline_refuses_a_parameter_set_that_is_not_the_pinned_one() -> None:
    fx = Fixture()
    bad_epoch = StreamEpoch(
        epoch_id=EPOCH_ID,
        strategy_id=fx.case["strategy_id"],
        parameter_set_id=fx.case["parameter_set_id"],
        parameter_set_hash="f" * 64,
        opened_at_utc=fx.last_1h.close_time_utc,
    )
    with pytest.raises(ValueError, match="parameter_set_hash"):
        BarPipeline(
            epoch=bad_epoch,
            parameter_set=fx.parameter_set,
            context_factory=lambda candle: _bar_context(fx.case, candle.close_time_utc),
            buffers=BarBuffers(),
            state=InMemoryRuntimeState(),
            sibling_4h_wait_seconds=30,
            fetch_4h_bar=lambda symbol, close: None,
        )


# --------------------------------------------------------------------------- #
# Test 5 - clock skew (research P20): a future close is reported, not evaluated.
# --------------------------------------------------------------------------- #


def test_a_bar_closing_after_the_tick_time_is_reported_as_future_close(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    fx.warm_up()
    close = fx.last_1h.close_time_utc

    skewed_now = close - timedelta(milliseconds=3500)
    result = fx.pipeline.handle([fx.live()], now_utc=skewed_now)

    assert spy_evaluations == [] and result.evaluated == () and result.recorded == ()
    assert fx.bar_records() == []
    assert result.dropped == (
        DroppedBar(
            symbol="BTCUSDT",
            interval="1h",
            close_time_utc=close,
            reason=DropReason.FUTURE_CLOSE,
            delta_ms=3500,
        ),
    )

    # With the tick time at the close the same bar is evaluated normally; the skewed delivery
    # left no trace (it was not recorded and not added to history).
    fine = fx.pipeline.handle([fx.live()], now_utc=close)
    assert fine.dropped == () and len(fine.evaluated) == 1
    assert len(fx.bar_records()) == 1


# --------------------------------------------------------------------------- #
# Task 3 - Q-D (history-only), continuity, 4h sibling hold, arrival-order independence.
# --------------------------------------------------------------------------- #


def _later_1h(fx: Fixture, hours_after: int) -> Candle:
    """A synthetic 1h bar `hours_after` hours after the fixture's last bar."""
    delta = timedelta(hours=hours_after)
    base = fx.last_1h
    return replace(
        base, open_time_utc=base.open_time_utc + delta, close_time_utc=base.close_time_utc + delta
    )


def _gap_view(records: list[RuntimeRecord]) -> list[tuple[str, str, str, str]]:
    return sorted(
        (
            str(r.symbol),
            str(r.interval),
            str(r.payload["expected_close_utc"]),
            str(r.payload["reason"]),
        )
        for r in records
    )


WindowCall = tuple[Candle, list[Candle], list[Candle]]


@pytest.fixture
def spy_windows(monkeypatch: pytest.MonkeyPatch) -> list[WindowCall]:
    """Every (candle, setup window, context window) that reaches evaluate_closed_bar."""
    seen: list[WindowCall] = []
    real = pipeline_module.evaluate_closed_bar

    def spy(*args: Any, **kwargs: Any) -> BarOutcome:
        seen.append((args[1], list(args[2]), list(args[3])))
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "evaluate_closed_bar", spy)
    return seen


def test_backfill_only_batch_extends_history_and_records_one_gap_per_close(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    fx.warm(247)
    backfilled = fx.setup[247:249]
    result = fx.pipeline.handle(
        [_tagged(c, SourceTag.REST_BACKFILL) for c in backfilled], now_utc=fx.now
    )

    assert spy_evaluations == []
    assert result.evaluated == () and fx.bar_records() == []
    assert fx.buffers.size("BTCUSDT", "1h") == 249  # history grew in time order
    assert _gap_view(fx.gap_records()) == [
        ("BTCUSDT", "1h", c.close_time_utc.isoformat(), "WS_RECONNECT_WINDOW") for c in backfilled
    ]
    assert [g.reason for g in result.gaps] == [GapReason.WS_RECONNECT_WINDOW] * 2
    assert sorted(result.recorded, key=record_sort_key) == fx.gap_records()
    # Only gap evidence and the replay history are written: nothing says the feed was healthy
    # because the backfill worked.
    assert {r.event_type for r in fx.state.records(EPOCH_ID)} == {
        RuntimeEventType.PAPER_GAP,
        RuntimeEventType.PAPER_HISTORY_BARS,
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_batch_decides_per_bar(reverse: bool, spy_evaluations: list[Candle]) -> None:
    fx = Fixture()
    fx.warm(247)
    batch = [
        _tagged(fx.setup[247], SourceTag.REST_BACKFILL),
        _tagged(fx.setup[248], SourceTag.REST_BACKFILL),
        _tagged(fx.setup[249], SourceTag.LIVE_WS),
    ]
    if reverse:
        batch.reverse()
    result = fx.pipeline.handle(batch, now_utc=fx.now)

    assert spy_evaluations == [fx.last_1h]  # the live bar is evaluated, the backfilled ones are not
    assert [o.closed_candle for o in result.evaluated] == [fx.last_1h]
    assert len(fx.gap_records()) == 2
    [processed] = fx.bar_records()
    assert processed.occurred_at_utc == fx.last_1h.close_time_utc
    assert processed.payload["source"] == "LIVE_WS"


@pytest.mark.parametrize("live_first", [False, True])
def test_a_live_copy_wins_over_a_backfill_copy_of_the_same_bar(
    live_first: bool, spy_evaluations: list[Candle]
) -> None:
    fx = Fixture()
    fx.warm(249)
    batch = [_tagged(fx.last_1h, SourceTag.REST_BACKFILL), fx.live()]
    if live_first:
        batch.reverse()
    result = fx.pipeline.handle(batch, now_utc=fx.now)

    assert spy_evaluations == [fx.last_1h] and len(result.evaluated) == 1
    assert fx.gap_records() == []
    assert [d.source for d in result.duplicates] == [SourceTag.REST_BACKFILL]


def test_duplicate_backfill_bars_create_no_record_and_no_state_change(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    fx.warm(247)
    bar = _tagged(fx.setup[247], SourceTag.REST_BACKFILL)
    first = fx.pipeline.handle([bar, bar], now_utc=fx.now)
    assert len(first.gaps) == 1 and first.duplicates == (bar,)

    before = list(fx.state.records(EPOCH_ID))
    size = fx.buffers.size("BTCUSDT", "1h")
    second = fx.pipeline.handle([bar], now_utc=fx.now)
    in_history = fx.pipeline.handle(
        [_tagged(fx.setup[10], SourceTag.REST_BACKFILL)], now_utc=fx.now
    )

    assert second.duplicates == (bar,) and second.recorded == () and second.gaps == ()
    assert in_history.recorded == () and in_history.gaps == ()
    assert list(fx.state.records(EPOCH_ID)) == before
    assert fx.buffers.size("BTCUSDT", "1h") == size
    assert spy_evaluations == []


def test_backfilled_history_feeds_the_next_live_bar_like_a_replay(
    spy_windows: list[WindowCall],
) -> None:
    fx = Fixture()
    fx.warm(247)
    fx.pipeline.handle(
        [_tagged(c, SourceTag.REST_BACKFILL) for c in fx.setup[247:249]], now_utc=fx.now
    )
    result = fx.pipeline.handle([fx.live()], now_utc=fx.now)

    assert len(result.evaluated) == 1
    [(candle, setup_window, context_window)] = spy_windows
    assert candle == fx.last_1h
    assert setup_window == fx.setup  # backfilled bars sit in time order inside the window
    assert context_window == fx.context
    replayed = decision_surface(_all_bars(fx.case), context=_per_bar_context(fx.case))
    [expected] = [
        r for r in replayed if r.interval == "1h" and r.bar_close_utc == candle.close_time_utc
    ]
    [record] = fx.bar_records()
    assert dict(record.payload["surface"]) == expected.to_dict()


def test_live_bars_after_a_successful_reconnect_are_processed_normally(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    fx.warm(247)
    fx.pipeline.handle([_tagged(fx.setup[247], SourceTag.REST_BACKFILL)], now_utc=fx.now)
    fx.pipeline.handle([fx.live(fx.setup[248])], now_utc=fx.setup[248].close_time_utc)
    fx.pipeline.handle([fx.live()], now_utc=fx.now)
    following = _later_1h(fx, 1)
    result = fx.pipeline.handle(
        [fx.live(following)], now_utc=following.close_time_utc + timedelta(seconds=2)
    )

    assert spy_evaluations == [fx.setup[248], fx.last_1h, following]
    assert len(result.evaluated) == 1
    assert len(fx.bar_records()) == 3 and len(fx.gap_records()) == 1


def test_an_unreconciled_hole_fails_closed_until_history_is_filled(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    fx.warm(247)  # bars 247 and 248 never arrive: the backfill could not recover them
    result = fx.pipeline.handle([fx.live()], now_utc=fx.now)

    assert spy_evaluations == [] and result.evaluated == ()
    [record] = fx.bar_records()
    assert record.payload["stage"] == "feed_gate"
    assert record.payload["reason_code"] == "HISTORY_DISCONTINUITY"
    assert record.payload["plan_hash"] is None

    # Filling the hole through REST warm-up validates the history again; evaluation resumes.
    fx.pipeline.handle(
        [_tagged(c, SourceTag.REST_WARMUP) for c in fx.setup[247:249]], now_utc=fx.now
    )
    following = _later_1h(fx, 1)
    resumed = fx.pipeline.handle(
        [fx.live(following)], now_utc=following.close_time_utc + timedelta(seconds=2)
    )
    assert spy_evaluations == [following] and len(resumed.evaluated) == 1


def test_a_missing_4h_bar_away_from_a_shared_close_fails_closed(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    fx.warm(249, len(fx.context) - 2)  # the two latest 4h bars are missing
    result = fx.pipeline.handle([fx.live()], now_utc=fx.now)

    assert spy_evaluations == [] and result.evaluated == () and result.held == ()
    [record] = fx.bar_records()
    assert record.payload["reason_code"] == "HISTORY_DISCONTINUITY"


def test_a_conflicting_backfill_bar_fails_closed_and_writes_nothing() -> None:
    fx = Fixture()
    fx.warm(248)
    before = list(fx.state.records(EPOCH_ID))
    original = fx.setup[247]
    changed = replace(original, high=original.high + Decimal("1"))
    with pytest.raises(ValueError, match="conflicting duplicate bar"):
        fx.pipeline.handle([_tagged(changed, SourceTag.REST_BACKFILL)], now_utc=fx.now)
    assert list(fx.state.records(EPOCH_ID)) == before


def test_no_age_or_freshness_exception_exists_for_backfill_bars() -> None:
    src = Path(__file__).resolve().parent.parent / "src"
    offenders = [
        str(path)
        for path in src.rglob("*.py")
        if "backfill_eval_max_age_seconds" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# ---- 4h sibling hold ------------------------------------------------------ #


def _without_last_4h(fx: Fixture) -> TaggedBar:
    """Drop the shared-close 4h bar from the warm-up list and return it."""
    last = fx.context[-1]
    fx.warmup = [
        b for b in fx.warmup if not (b.interval == "4h" and b.open_time_utc == last.open_time_utc)
    ]
    return _tagged(last, SourceTag.LIVE_WS)


def test_a_1h_bar_waits_for_its_4h_sibling_and_is_evaluated_after_it(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    sibling = _without_last_4h(fx)
    fx.warm_up()
    live = fx.live()

    held = fx.pipeline.handle([live], now_utc=fx.now)
    deadline = fx.last_1h.close_time_utc + timedelta(seconds=30)
    assert held.held == (HeldBar(bar=live, deadline_utc=deadline),)
    assert held.evaluated == () and held.recorded == () and fx.fetch_calls == []
    assert fx.buffers.size("BTCUSDT", "1h") == PASSING_BAR  # a held bar changes no state

    fx.pipeline.handle([sibling], now_utc=fx.now)
    done = fx.pipeline.handle([live], now_utc=fx.now)
    assert spy_evaluations == [fx.last_1h] and len(done.evaluated) == 1 and done.held == ()
    assert fx.fetch_calls == []


@pytest.mark.parametrize("sibling_first", [True, False])
def test_a_sibling_in_the_same_batch_is_evaluated_whatever_the_arrival_order(
    sibling_first: bool, spy_evaluations: list[Candle]
) -> None:
    fx = Fixture()
    sibling = _without_last_4h(fx)
    fx.warm_up()
    batch = [sibling, fx.live()]
    if not sibling_first:
        batch.reverse()
    result = fx.pipeline.handle(batch, now_utc=fx.now)
    assert spy_evaluations == [fx.last_1h] and result.held == ()


def test_at_the_deadline_the_sibling_is_fetched_once_and_a_missing_one_is_a_gap(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture()
    _without_last_4h(fx)
    fx.warm_up()
    close = fx.last_1h.close_time_utc
    result = fx.pipeline.handle([fx.live()], now_utc=close + timedelta(seconds=30))

    assert fx.fetch_calls == [("BTCUSDT", close)]
    assert spy_evaluations == [] and result.evaluated == () and result.held == ()
    assert _gap_view(fx.gap_records()) == [
        ("BTCUSDT", "4h", close.isoformat(), "EXCHANGE_NO_CANDLE")
    ]
    [record] = fx.bar_records()
    assert record.interval == "1h" and record.payload["reason_code"] == "SIBLING_4H_MISSING"
    assert record.payload["stage"] == "feed_gate"


def test_a_fetched_sibling_is_context_only_and_unblocks_the_1h_bar(
    spy_evaluations: list[Candle],
) -> None:
    fx = Fixture(fetch=lambda symbol, close: _tagged(fx.context[-1], SourceTag.REST_BACKFILL))
    _without_last_4h(fx)
    fx.warm_up()
    close = fx.last_1h.close_time_utc
    result = fx.pipeline.handle([fx.live()], now_utc=close + timedelta(seconds=30))

    assert len(fx.fetch_calls) == 1
    assert spy_evaluations == [fx.last_1h] and len(result.evaluated) == 1
    assert _gap_view(fx.gap_records()) == [
        ("BTCUSDT", "4h", close.isoformat(), "WS_RECONNECT_WINDOW")
    ]
    assert [r.interval for r in fx.bar_records()] == ["1h"]  # the 4h bar is never evaluated


def test_a_fetched_bar_that_is_not_the_requested_sibling_is_refused() -> None:
    fx = Fixture(fetch=lambda symbol, close: _tagged(fx.context[-2], SourceTag.REST_BACKFILL))
    _without_last_4h(fx)
    fx.warm_up()
    with pytest.raises(ValueError, match="fetch_4h_bar"):
        fx.pipeline.handle([fx.live()], now_utc=fx.last_1h.close_time_utc + timedelta(seconds=30))


def test_sibling_wait_and_fetch_are_required_inputs_with_no_default() -> None:
    fx = Fixture()
    common: dict[str, Any] = {
        "epoch": _epoch(fx.case, fx.parameter_set, fx.last_1h),
        "parameter_set": fx.parameter_set,
        "context_factory": lambda candle: _bar_context(fx.case, candle.close_time_utc),
        "buffers": BarBuffers(),
        "state": InMemoryRuntimeState(),
    }
    with pytest.raises(TypeError):
        BarPipeline(**common, fetch_4h_bar=lambda symbol, close: None)
    with pytest.raises(TypeError):
        BarPipeline(**common, sibling_4h_wait_seconds=30)

    tree = ast.parse(PIPELINE_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.arguments):
            names = [a.arg for a in (*node.args, *node.kwonlyargs)]
            defaults = [*node.defaults, *node.kw_defaults]
            padded = [None] * (len(names) - len(defaults)) + defaults
            for name, default in zip(names, padded, strict=True):
                if name in {"sibling_4h_wait_seconds", "fetch_4h_bar"}:
                    assert default is None, f"{name} must have no default"
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "sibling_4h_wait_seconds":
                    assert not isinstance(node.value, ast.Constant)


# ---- arrival-order independence ------------------------------------------ #


def test_every_arrival_order_of_one_group_gives_byte_identical_records() -> None:
    def run(order: tuple[int, ...]) -> tuple[list[str], list[Candle], int]:
        fx = Fixture()
        fx.warm(248, len(fx.context) - 1)
        group = [
            _tagged(fx.context[-1], SourceTag.LIVE_WS),
            fx.live(),
            fx.live(),  # a duplicate delivery
            _tagged(fx.setup[248], SourceTag.REST_WARMUP),
        ]
        result = fx.pipeline.handle([group[i] for i in order], now_utc=fx.now)
        records = sorted(fx.state.records(EPOCH_ID), key=record_sort_key)
        return (
            [f"{runtime_event_id(r)}|{r.payload_json}" for r in records],
            [o.closed_candle for o in result.evaluated],
            len(result.duplicates),
        )

    baseline = run((0, 1, 2, 3))
    # the 4h context record, the 1h heartbeat, the replay inputs and two history-bar records
    assert len(baseline[0]) == 5
    assert len(baseline[1]) == 1 and baseline[2] == 1
    for order in itertools.permutations(range(4)):
        assert run(order) == baseline
