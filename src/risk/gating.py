"""Risk pipeline orchestration (Phase 5, plans 05-01 + 05-02).

Per 05-PATTERNS.md: `evaluate_risk` runs the fixed-order pipeline
`size_position → quantize → check_portfolio` and returns the final
PortfolioVerdict. The same function is called in backtest/paper/live
(D-02 parity guarantee).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.core._decimal import _add, _div, _mul, _sub
from src.core.types import AccountState
from src.domain.enums import Direction
from src.domain.trade_plan import TradePlan

from .portfolio import check_portfolio
from .quantization import quantize
from .sizing import size_position
from .types import ConstraintSnapshot, OpenPosition, PortfolioVerdict


def evaluate_risk(
    *,
    trade_plan: TradePlan,
    candidate_position_side: str,
    account_state: AccountState,
    constraint_snapshot: ConstraintSnapshot,
    open_positions: Sequence[OpenPosition],
    daily_loss_quote: Decimal | None,
    now_utc: datetime,
    ttl: timedelta,
    modeled_costs_per_unit: Decimal,
    minimum_risk_utilization_after_rounding: Decimal,
    parameter_set: dict[str, Any],
) -> PortfolioVerdict:
    """Run size_position → quantize → check_portfolio in fixed order.

    The pipeline is the same function called in backtest/paper/live
    (D-02 parity guarantee). The first NO_TRADE short-circuits with its
    reason code preserved.

    `candidate_position_side` is required (no default) and must be a
    `Direction` value (LONG/SHORT). The cluster gate only sums open
    positions matching the candidate side, so guessing the side would
    mis-cluster SHORT plans and wrongfully PASS them — an unknown side
    raises instead of evaluating (fail closed).

    `parameter_set` carries the portfolio thresholds (cluster_cap,
    max_aggregate_open_risk, max_open_positions, daily_loss_*_threshold)
    as ABSOLUTE quote amounts — callers holding raw registry rates
    convert first via `resolve_absolute_thresholds`. This keeps the
    gate math simple and the parity fixture byte-exact.
    """
    if candidate_position_side not in {d.value for d in Direction}:
        raise ValueError(
            "candidate_position_side must be a Direction value "
            f"(LONG/SHORT), got {candidate_position_side!r} — refusing to evaluate"
        )
    # Zone-mid entry_ref = (entry_min + entry_max) / 2 (D-02 locked,
    # pinned prec-28 so ambient context mutations cannot change the value).
    entry_ref = _div(
        _add(trade_plan.entry_min_price, trade_plan.entry_max_price),
        Decimal("2"),
    )

    sized = size_position(
        trade_plan=trade_plan,
        account_state=account_state,
        entry_ref=entry_ref,
        modeled_costs_per_unit=modeled_costs_per_unit,
    )

    # If sizing already failed closed (e.g. zero SL distance), short-circuit.
    if sized.is_no_trade:
        return check_portfolio(
            sized=sized,
            candidate_symbol=constraint_snapshot.symbol,
            candidate_position_side=candidate_position_side,
            open_positions=open_positions,
            daily_loss_quote=daily_loss_quote,
            parameter_set=parameter_set,
            now_utc=now_utc,
            ttl=ttl,
            positions_reconciled=True,
            constraint_observed_at_utc=constraint_snapshot.metadata_observed_at_utc,
        )

    allowed_risk = _mul(account_state.equity, account_state.risk_rate)
    sl_distance = abs(_sub(entry_ref, trade_plan.stop_loss_price))
    risk_per_unit = _add(sl_distance, modeled_costs_per_unit)

    quantized = quantize(
        sized=sized,
        constraint_snapshot=constraint_snapshot,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=minimum_risk_utilization_after_rounding,
        reference_price=entry_ref,
    )

    return check_portfolio(
        sized=quantized,
        candidate_symbol=constraint_snapshot.symbol,
        candidate_position_side=candidate_position_side,
        open_positions=open_positions,
        daily_loss_quote=daily_loss_quote,
        parameter_set=parameter_set,
        now_utc=now_utc,
        ttl=ttl,
        positions_reconciled=True,
        constraint_observed_at_utc=constraint_snapshot.metadata_observed_at_utc,
    )


__all__ = ["evaluate_risk"]
