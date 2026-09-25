"""Risk pipeline orchestration (Phase 5, plan 05-01).

Per 05-PATTERNS.md: `evaluate_risk` runs the fixed-order pipeline
`size_position → quantize` and returns the final SizedResult. Portfolio
gates (cluster/aggregate/count/daily-state) arrive in plan 05-02 — this
tracer slice proves the sizing+quantization parity guarantee first.
"""

from __future__ import annotations

from decimal import Decimal

from src.core.types import AccountState
from src.domain.trade_plan import TradePlan

from .quantization import quantize
from .sizing import size_position
from .types import ConstraintSnapshot, SizedResult


def evaluate_risk(
    *,
    trade_plan: TradePlan,
    account_state: AccountState,
    constraint_snapshot: ConstraintSnapshot,
    entry_ref: Decimal,
    modeled_costs_per_unit: Decimal,
    minimum_risk_utilization_after_rounding: Decimal,
) -> SizedResult:
    """Run size_position → quantize in fixed order; return final SizedResult.

    The pipeline is the same function called in backtest/paper/live
    (D-02 parity guarantee). Portfolio gates are added in plan 05-02.
    """
    sized = size_position(
        trade_plan=trade_plan,
        account_state=account_state,
        entry_ref=entry_ref,
        modeled_costs_per_unit=modeled_costs_per_unit,
    )

    # If sizing already failed closed (e.g. zero SL distance), short-circuit.
    if sized.is_no_trade:
        return sized

    allowed_risk = account_state.equity * account_state.risk_rate
    sl_distance = abs(entry_ref - trade_plan.stop_loss_price)
    risk_per_unit = sl_distance + modeled_costs_per_unit

    return quantize(
        sized=sized,
        constraint_snapshot=constraint_snapshot,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=minimum_risk_utilization_after_rounding,
        reference_price=entry_ref,
    )


__all__ = ["evaluate_risk"]
