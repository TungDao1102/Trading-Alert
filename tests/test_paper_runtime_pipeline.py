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
from datetime import timedelta
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
from src.paper.pipeline import BarPipeline, DroppedBar, PipelineResult
from src.paper.runtime_state import (
    InMemoryRuntimeState,
    RuntimeRecord,
    runtime_event_id,
)
from src.paper.surface import decision_surface
from src.paper.vocabulary import DropReason, RuntimeEventType, SourceTag, TaggedBar

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

    def __init__(self, *, warmup_1h: int | None = None) -> None:
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
        )
        self.last_1h = self.setup[PASSING_BAR]
        # The warm-up history: every 1h bar before the passing one, and every 4h bar.
        history_1h = self.setup[:PASSING_BAR] if warmup_1h is None else self.setup[:warmup_1h]
        self.warmup = [
            *(_tagged(c, SourceTag.REST_WARMUP) for c in history_1h),
            *(_tagged(c, SourceTag.REST_WARMUP) for c in self.context),
        ]
        self.now = self.last_1h.close_time_utc + timedelta(seconds=2)

    def warm_up(self) -> PipelineResult:
        return self.pipeline.handle(self.warmup, now_utc=self.now)

    def live(self, candle: Candle | None = None) -> TaggedBar:
        return _tagged(candle or self.last_1h, SourceTag.LIVE_WS)

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
