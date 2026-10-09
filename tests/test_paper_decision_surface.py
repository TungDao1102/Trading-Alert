"""Typed per-bar outcome and decision surface (Phase 16, plan 16-10).

Task 1 (tracer): `evaluate_closed_bar` is the per-bar body of `run_paper_tick` extracted into a
typed function (D-02). It returns the closed candle, the stage, the reason code and the Signal,
TradePlan and risk verdict objects that today's dict output drops. `run_paper_tick` projects the
same objects into exactly the dicts it returned before; the byte-identity guards live in
test_paper_start_gate.py, test_paper_parity.py, test_paper_reviewfix_pins.py,
test_paper_feed_gates.py and test_paper_closed_candle.py and are never edited here.

Task 3: `decision_surface` observes the same chain per closed bar through the shared
`src/core` and `src/risk` functions and yields one record per closed 1h bar, replayable with
tolerance zero. It never touches the Phase 14 simulator (L-02).

No network is touched. The fixture is the Phase 7 parity history (250 1h bars, one risk-passing
setup on the last bar, regime NO_TRADE on the 49 before it, 200 warm-up bars first).
"""

from __future__ import annotations

import ast
import itertools
import json
import random
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.costs import build_cost_model
from src.core.types import Candle
from src.paper.bars import BarBuffers
from src.paper.freeze import load_parameter_set_at_root, resolve_registry_root
from src.paper.loop import (
    BarContext,
    BarOutcome,
    _parse_account_state,
    _parse_candle,
    _parse_constraint_snapshot,
    evaluate_closed_bar,
    run_paper_tick,
)
from src.paper.surface import DecisionSurfaceRecord, decision_surface, surface_digest
from src.risk.portfolio import resolve_absolute_thresholds

from tests.test_paper_parity import (
    _project_paper_verdicts_full,
    _replay_paper_through_bars,
)

PARITY_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "phase7" / "parity_overlapping_history"
)

# Index of the single risk-passing bar in the parity fixture and a regime NO_TRADE bar before it.
PASSING_BAR = 249
STRATEGY_NO_TRADE_BAR = 220


def _case_input() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((PARITY_FIXTURE / "input.json").read_text())
    return loaded


def _setup_bars(case: dict[str, Any]) -> list[Candle]:
    return [_parse_candle(r) for r in case["strategy_bars"]]


def _context_bars(case: dict[str, Any]) -> list[Candle]:
    return [_parse_candle(r) for r in case["context_bars"]]


def _bar_context(case: dict[str, Any], bar_close: datetime) -> BarContext:
    """The context `run_paper_tick` derives from a case input, stamped at `bar_close` (ttl 0)."""
    parameter_set = load_parameter_set_at_root(
        case["strategy_id"], case["parameter_set_id"], resolve_registry_root()
    )
    account_state = _parse_account_state(case["account_state"])
    row = case["constraint_history"][0]
    snapshot = _parse_constraint_snapshot(
        {**row, "metadata_observed_at_utc": bar_close.isoformat()}
    )
    return BarContext(
        symbol=case["symbols"][0],
        strategy_version=case["strategy_version"],
        parameter_set=parameter_set,
        account_state=account_state,
        constraint_snapshot=snapshot,
        cost_model=build_cost_model(case["cost_model"]),
        open_positions=(),
        daily_loss_quote=Decimal("0"),
        ttl=timedelta(seconds=0),
        absolute_thresholds=resolve_absolute_thresholds(
            parameter_set=parameter_set.params, equity=account_state.equity
        ),
    )


def _evaluate(case: dict[str, Any], index: int, **context_changes: Any) -> BarOutcome:
    setup = _setup_bars(case)[: index + 1]
    closed = setup[-1]
    context = _bar_context(case, closed.close_time_utc)
    if context_changes:
        context = replace(context, **context_changes)
    context_candles = [c for c in _context_bars(case) if c.close_time_utc <= closed.close_time_utc]
    return evaluate_closed_bar(context, closed, setup, context_candles)


# --------------------------------------------------------------------------- #
# Task 1 - evaluate_closed_bar
# --------------------------------------------------------------------------- #


def test_risk_passed_bar_returns_signal_plan_and_sized_verdict() -> None:
    """Test 1: the objects today's dict output drops come back typed."""
    case = _case_input()
    outcome = _evaluate(case, PASSING_BAR)

    assert outcome.stage == "risk_passed"
    assert outcome.reason_code == "OK"
    assert outcome.signal is not None
    assert outcome.trade_plan is not None
    assert outcome.verdict is not None
    assert outcome.verdict.is_no_trade is False
    assert outcome.verdict.sized is not None
    assert isinstance(outcome.verdict.sized.quantity, Decimal)
    assert outcome.closed_candle == _setup_bars(case)[PASSING_BAR]
    assert outcome.regime is not None


def test_risk_passed_bar_matches_the_tick_record_ids() -> None:
    """The typed outcome and the unchanged tick dicts name the same signal and plan."""
    case = _case_input()
    outcome = _evaluate(case, PASSING_BAR)
    assert outcome.signal is not None and outcome.trade_plan is not None

    bars = case["strategy_bars"]
    bar = bars[PASSING_BAR]
    event = {
        "t": int(datetime.fromisoformat(bar["open_time_utc"]).timestamp() * 1000),
        "T": int(datetime.fromisoformat(bar["close_time_utc"]).timestamp() * 1000),
        "o": bar["open"],
        "h": bar["high"],
        "l": bar["low"],
        "c": bar["close"],
        "v": bar["volume"],
        "x": True,
    }
    tick = run_paper_tick(
        {
            "strategy_id": case["strategy_id"],
            "strategy_version": case["strategy_version"],
            "parameter_set_id": case["parameter_set_id"],
            "account_state": case["account_state"],
            "cost_model": case["cost_model"],
            "constraint_snapshot": {
                **{k: v for k, v in case["constraint_history"][0].items()},
                "metadata_observed_at_utc": bar["close_time_utc"],
            },
            "open_positions": [],
            "daily_loss_quote": "0",
            "ttl_seconds": "0",
            "symbol": case["symbols"][0],
            "warmed_up_1h": bars[:PASSING_BAR],
            "warmed_up_4h": [
                c for c in case["context_bars"] if c["close_time_utc"] <= bar["close_time_utc"]
            ],
            "feed_events": [event],
            "now_utc": bar["close_time_utc"],
        },
        allow_unrationalized=True,
    )
    (record,) = tick["no_trade_records"]
    assert record["stage"] == "risk_passed"
    assert record["signal_id"] == outcome.signal.signal_id
    assert record["trade_plan_id"] == outcome.trade_plan.trade_plan_id
    assert [s["signal_id"] for s in tick["signals"]] == [outcome.signal.signal_id]
    assert [p["trade_plan_id"] for p in tick["trade_plans"]] == [outcome.trade_plan.trade_plan_id]


def test_strategy_stage_no_trade_has_no_signal() -> None:
    """Test 2: a strategy-stage NO_TRADE keeps the strategy reason code and carries no signal."""
    case = _case_input()
    outcome = _evaluate(case, STRATEGY_NO_TRADE_BAR)

    assert outcome.stage == "strategy"
    assert outcome.reason_code == "NO_TRADE_REGIME"
    assert outcome.signal is None
    assert outcome.trade_plan is None
    assert outcome.verdict is None


def test_risk_stage_no_trade_keeps_signal_plan_and_verdict() -> None:
    """A risk-stage NO_TRADE still hands back the signal and the plan that were rejected."""
    case = _case_input()
    base = _evaluate(case, PASSING_BAR)
    assert base.stage == "risk_passed"
    closed = _setup_bars(case)[PASSING_BAR]
    context = _bar_context(case, closed.close_time_utc)
    huge = replace(context.constraint_snapshot, min_notional=Decimal("1000000000"))
    outcome = _evaluate(case, PASSING_BAR, constraint_snapshot=huge)

    assert outcome.stage == "risk"
    assert outcome.verdict is not None and outcome.verdict.is_no_trade is True
    assert outcome.reason_code == outcome.verdict.reason_code
    assert outcome.reason_code != "OK"
    assert outcome.signal is not None and outcome.trade_plan is not None


def test_bar_outcome_rejects_an_unknown_stage() -> None:
    case = _case_input()
    outcome = _evaluate(case, STRATEGY_NO_TRADE_BAR)
    with pytest.raises(ValueError, match="stage"):
        replace(outcome, stage="nonsense")


# --------------------------------------------------------------------------- #
# Task 3 - decision_surface
# --------------------------------------------------------------------------- #


def _per_bar_context(case: dict[str, Any]) -> Callable[[Candle], BarContext]:
    return lambda candle: _bar_context(case, candle.close_time_utc)


def _all_bars(case: dict[str, Any]) -> list[Candle]:
    return [*_setup_bars(case), *_context_bars(case)]


@pytest.fixture(scope="module")
def surface_records() -> tuple[DecisionSurfaceRecord, ...]:
    case = _case_input()
    return decision_surface(_all_bars(case), context=_per_bar_context(case))


def test_one_record_per_closed_1h_bar_and_context_records_for_4h(
    surface_records: tuple[DecisionSurfaceRecord, ...],
) -> None:
    """Test 1: record shape per bar; 4h bars are context records only."""
    case = _case_input()
    setup = _setup_bars(case)
    hourly = [r for r in surface_records if r.interval == "1h"]
    context = [r for r in surface_records if r.interval == "4h"]
    assert [r.bar_close_utc for r in hourly] == [b.close_time_utc for b in setup]
    assert len(context) == len(case["context_bars"])
    assert all(r.stage == "context" and r.reason_code == "CONTEXT_BAR" for r in context)
    assert all(r.signal_id is None and r.feature_digest is None for r in context)

    passing = hourly[PASSING_BAR]
    outcome = _evaluate(case, PASSING_BAR)
    assert outcome.signal is not None and outcome.trade_plan is not None
    assert outcome.verdict is not None and outcome.verdict.sized is not None
    assert passing.stage == "risk_passed" and passing.reason_code == "OK"
    assert passing.signal_id == outcome.signal.signal_id
    assert passing.plan_hash == outcome.trade_plan.plan_hash
    assert passing.risk_reason == outcome.verdict.reason_code
    assert passing.sized_quantity == outcome.verdict.sized.quantity
    assert passing.regime == outcome.regime
    assert isinstance(passing.feature_digest, str) and len(passing.feature_digest) == 64


def test_surface_agrees_with_the_paper_tick_on_every_1h_bar(
    surface_records: tuple[DecisionSurfaceRecord, ...],
) -> None:
    """The observer and the unchanged tick name the same stage, reason and signal per bar."""
    case = _case_input()
    ticks = _project_paper_verdicts_full(_replay_paper_through_bars(case))
    hourly = [r for r in surface_records if r.interval == "1h"]
    assert len(ticks) == len(hourly)
    for (bar_close, signal_id, reason, stage), record in zip(ticks, hourly, strict=True):
        assert record.bar_close_utc.isoformat() == bar_close
        assert (record.stage, record.reason_code, record.signal_id) == (stage, reason, signal_id)


def test_replay_and_arrival_order_give_the_same_digest(
    surface_records: tuple[DecisionSurfaceRecord, ...],
) -> None:
    """Test 2: running twice and on a shuffled arrival order is identical, tolerance zero."""
    case = _case_input()
    again = decision_surface(_all_bars(case), context=_per_bar_context(case))
    shuffled_bars = _all_bars(case)
    random.Random(16).shuffle(shuffled_bars)
    shuffled = decision_surface(shuffled_bars, context=_per_bar_context(case))
    assert again == surface_records
    assert shuffled == surface_records
    assert surface_digest(again) == surface_digest(shuffled) == surface_digest(surface_records)


def test_strategy_stage_no_trade_and_signal_less_bars_have_records(
    surface_records: tuple[DecisionSurfaceRecord, ...],
) -> None:
    """Test 3 (G2-008): the bars the trade-level parity test cannot see are still observed."""
    hourly = [r for r in surface_records if r.interval == "1h"]
    no_trade = [r for r in hourly if r.stage == "strategy"]
    assert len(no_trade) == 49
    assert {r.reason_code for r in no_trade} == {"NO_TRADE_REGIME"}
    assert all(r.signal_id is None and r.plan_hash is None for r in no_trade)
    assert all(r.risk_reason is None and r.sized_quantity is None for r in no_trade)
    assert all(isinstance(r.feature_digest, str) for r in no_trade)
    warmup = [r for r in hourly if r.stage == "feed_gate"]
    assert len(warmup) == 200
    assert {r.reason_code for r in warmup} == {"WARMUP_INSUFFICIENT"}


def test_surface_digest_changes_when_any_record_changes(
    surface_records: tuple[DecisionSurfaceRecord, ...],
) -> None:
    changed = list(surface_records)
    index = next(i for i, r in enumerate(changed) if r.stage == "strategy")
    changed[index] = replace(changed[index], reason_code="NO_TRADE_OTHER")
    assert surface_digest(changed) != surface_digest(surface_records)
    assert surface_digest(()) == surface_digest(())


def test_window_drift_changes_a_feature_digest(
    surface_records: tuple[DecisionSurfaceRecord, ...],
) -> None:
    """Test 4: the default windows are BarBuffers' engine windows; other windows are detected."""
    case = _case_input()
    explicit = decision_surface(
        _all_bars(case), context=_per_bar_context(case), buffers_factory=BarBuffers
    )
    assert explicit == surface_records

    narrow = decision_surface(
        _all_bars(case),
        context=_per_bar_context(case),
        buffers_factory=lambda: BarBuffers(strategy_window_bars=220, context_window_bars=300),
    )
    assert len(narrow) == len(surface_records)
    differing = [
        (a, b)
        for a, b in zip(surface_records, narrow, strict=True)
        if a.feature_digest != b.feature_digest
    ]
    assert differing, "a narrower setup window must change at least one feature digest"
    assert surface_digest(narrow) != surface_digest(surface_records)


def test_a_conflicting_duplicate_bar_fails_closed() -> None:
    case = _case_input()
    bars = _all_bars(case)
    clash = replace(bars[3], close=bars[3].close + 1)
    with pytest.raises(ValueError, match="conflicting"):
        decision_surface([*bars, clash], context=_per_bar_context(case))


def test_an_identical_duplicate_bar_is_reported_not_evaluated() -> None:
    case = _case_input()
    bars = _setup_bars(case)[:210]
    records = decision_surface([*bars, bars[205]], context=_per_bar_context(case))
    duplicates = [r for r in records if r.reason_code == "DUPLICATE_BAR"]
    assert len(duplicates) == 1
    assert duplicates[0].bar_close_utc == bars[205].close_time_utc


def test_surface_module_never_imports_the_simulator() -> None:
    """L-02: the observer is non-semantic; it must not import the engine, simulator or lifecycle."""
    source = (Path(__file__).resolve().parent.parent / "src" / "paper" / "surface.py").read_text(
        encoding="utf-8"
    )
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    forbidden = {"src.backtest.engine", "src.backtest.simulator", "src.backtest.lifecycle"}
    assert not imported & forbidden
    assert "src.paper.loop" in imported
    assert "src.core.features" in imported
    assert "src.paper.bars" in imported


def test_permutations_of_a_small_bar_set_give_one_digest() -> None:
    case = _case_input()
    bars = [*_setup_bars(case)[:3], *_context_bars(case)[:2]]
    digests = {
        surface_digest(decision_surface(list(p), context=_per_bar_context(case)))
        for p in itertools.permutations(bars)
    }
    assert len(digests) == 1
