"""Typed per-bar outcome and decision surface (Phase 16, plan 16-10).

Task 1 (tracer): `evaluate_closed_bar` is the per-bar body of `run_paper_tick` extracted into a
typed function (D-02). It returns the closed candle, the stage, the reason code and the Signal,
TradePlan and risk verdict objects that today's dict output drops. `run_paper_tick` projects the
same objects into exactly the dicts it returned before; the byte-identity guards live in
test_paper_start_gate.py, test_paper_parity.py, test_paper_reviewfix_pins.py,
test_paper_feed_gates.py and test_paper_closed_candle.py and are never edited here.

No network is touched. The fixture is the Phase 7 parity history (250 1h bars, one risk-passing
setup on the last bar, regime NO_TRADE on the 49 before it, 200 warm-up bars first).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.costs import build_cost_model
from src.core.types import Candle
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
from src.risk.portfolio import resolve_absolute_thresholds

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
