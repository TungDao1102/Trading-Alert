"""Plan binding tests (Phase 19, plan 19-02; D-01..D-04, research F2/F3).

What the human approved is exactly what is placed: the plan hash is re-derived
with the planner's frozen algorithm, symbol and side come from the persisted
Signal reached by plan.signal_id, and every disagreement is a named refusal.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, MarketSnapshot
from src.domain.registry import ParameterSet, load_parameter_set
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.binding import (
    BindingVerdict,
    BoundPlan,
    bind_plan,
    recompute_plan_hash,
)

from tests import geometry_builders

_PARAMETER_SET_ID = "baseline-v6"


def _parameter_set() -> ParameterSet:
    return load_parameter_set("trend-pullback", _PARAMETER_SET_ID)


def _real_plan(side: str) -> tuple[Signal, TradePlan]:
    """A real evaluate() Signal and plan() TradePlan on the hand-derived Family A window."""
    window = (
        geometry_builders.family_a_long_window()
        if side == "LONG"
        else geometry_builders.family_a_short_window()
    )
    parameter_set = _parameter_set()
    account_state = AccountState(equity=Decimal("10000.00"), risk_rate=Decimal("0.005"))
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=window[0],
        context_candles=window[1],
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None
    planned = plan(
        signal=result.signal,
        setup_candles=window[0],
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert planned.trade_plan is not None, planned.reason_code
    assert result.signal.direction == side
    return result.signal, planned.trade_plan


def _bind(signal: Signal, trade_plan: TradePlan, **overrides: str) -> BindingVerdict:
    """bind_plan with every argument consistent, then the named overrides applied."""
    kwargs: dict[str, str] = {
        "callback_plan_hash": trade_plan.plan_hash,
        "approval_request_hash": trade_plan.plan_hash,
        "approval_strategy_version": signal.strategy_version,
        "approval_parameter_set_id": signal.parameter_set_id,
        "approval_parameter_set_hash": signal.parameter_set_hash,
        "plan_snapshot_symbol": signal.symbol,
        "plan_snapshot_trade_plan_id": trade_plan.trade_plan_id,
        "caller_symbol": signal.symbol,
        "caller_side": signal.direction,
    }
    kwargs.update(overrides)
    return bind_plan(trade_plan=trade_plan, signal=signal, **kwargs)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_tracer_real_plan_binds_to_its_signal(side: str) -> None:
    signal, trade_plan = _real_plan(side)
    assert recompute_plan_hash(trade_plan) == trade_plan.plan_hash

    verdict = _bind(signal, trade_plan)

    assert verdict.ok is True
    assert verdict.reason_code == "OK"
    assert verdict.bound == BoundPlan(
        trade_plan_id=trade_plan.trade_plan_id,
        plan_hash=trade_plan.plan_hash,
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        side=side,
        entry_side="BUY" if side == "LONG" else "SELL",
        exit_side="SELL" if side == "LONG" else "BUY",
        approved_quantity=trade_plan.quantity_after_rounding,
    )
