"""Risk pipeline orchestration (Phase 5, plans 05-01 + 05-02; Phase 12, plan 12-06).

`size_and_quantize` is the shared sizing step and `evaluate_risk` is
`size_and_quantize` followed by `check_portfolio`. The same functions are
called in backtest/paper/live (D-02 parity guarantee), so parity fixtures and
the live path run identical math.

Phase 12 changes the contract (D-02, D-03):

* The cost per unit is computed HERE from a `CostRates` object and the plan
  prices (`per_unit_round_trip_cost`); a caller-supplied pre-computed cost no
  longer exists, so the caller and the pipeline can never disagree on the
  entry price.
* Sizing uses the ADVERSE edge of the entry zone (LONG `entry_max`, SHORT
  `entry_min`) for both the entry price and the stop distance. The Phase 5
  D-02 zone-mid rule is superseded as the risk-sizing entry: with the edge,
  the loss at the stop for a fill anywhere in the zone is at most
  `allowed_risk`. The zone mid REMAINS the quantizer's min-notional reference
  price, because it is the price the order is actually placed at.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.core._decimal import _add, _div, _mul, _sub
from src.core.types import AccountState
from src.domain.enums import Direction
from src.domain.trade_plan import TradePlan

from .cost_guards import validate_guard_rates
from .cost_rates import CostRates, per_unit_round_trip_cost
from .portfolio import check_portfolio
from .quantization import quantize
from .sizing import size_position
from .types import ConstraintSnapshot, OpenPosition, PortfolioVerdict, SizedResult


def size_and_quantize(
    *,
    trade_plan: TradePlan,
    candidate_position_side: str,
    account_state: AccountState,
    constraint_snapshot: ConstraintSnapshot,
    cost_rates: CostRates,
    min_stop_distance_rate: Decimal,
    max_cost_to_risk: Decimal,
    minimum_risk_utilization_after_rounding: Decimal,
) -> SizedResult:
    """Size at the adverse zone edge, then quantize; record the cost trail.

    Fixed order: `size_position`, `quantize`. The returned SizedResult carries
    the modeled cost per unit, the sizing entry price, the stop distance rate,
    the cost-to-risk ratio, the fee rates used and their source (D-12), for
    accepted and quantize-rejected plans alike. A `risk.cost_rates` structlog
    event records the same values once per call that reaches the ratio
    computation.

    `min_stop_distance_rate` and `max_cost_to_risk` are required, validated
    Decimals (no defaults) so a caller cannot disable the cost guards.

    Raises:
        ValueError: `candidate_position_side` is not LONG/SHORT, or a guard
            rate is out of range.
        TypeError: `cost_rates` is not a CostRates, or a guard rate is not a
            Decimal.
    """
    if candidate_position_side not in {d.value for d in Direction}:
        raise ValueError(
            "candidate_position_side must be a Direction value "
            f"(LONG/SHORT), got {candidate_position_side!r} — refusing to evaluate"
        )
    if not isinstance(cost_rates, CostRates):
        raise TypeError(f"cost_rates must be CostRates, got {type(cost_rates).__name__}")
    validate_guard_rates(
        min_stop_distance_rate=min_stop_distance_rate,
        max_cost_to_risk=max_cost_to_risk,
    )

    # Adverse edge of the zone: the fill that maximizes the loss at the stop.
    if candidate_position_side == Direction.LONG.value:
        sizing_entry = trade_plan.entry_max_price
    else:
        sizing_entry = trade_plan.entry_min_price
    # Zone mid stays the notional reference (the price the order is placed at).
    zone_mid = _div(
        _add(trade_plan.entry_min_price, trade_plan.entry_max_price),
        Decimal("2"),
    )

    costs = per_unit_round_trip_cost(
        side=candidate_position_side,
        entry_price=sizing_entry,
        stop_price=trade_plan.stop_loss_price,
        rates=cost_rates,
    )

    sized = size_position(
        trade_plan=trade_plan,
        account_state=account_state,
        entry_ref=sizing_entry,
        modeled_costs_per_unit=costs,
    )
    # Sizing failed closed (e.g. zero SL distance): nothing to record.
    if sized.is_no_trade:
        return sized

    allowed_risk = _mul(account_state.equity, account_state.risk_rate)
    sl_distance = abs(_sub(sizing_entry, trade_plan.stop_loss_price))
    risk_per_unit = _add(sl_distance, costs)
    stop_distance_rate = _div(sl_distance, sizing_entry)
    cost_to_risk_ratio = _div(costs, risk_per_unit)

    _emit_cost_rates_lineage(
        cost_rates=cost_rates,
        costs=costs,
        sizing_entry=sizing_entry,
        stop_distance_rate=stop_distance_rate,
        cost_to_risk_ratio=cost_to_risk_ratio,
    )

    quantized = quantize(
        sized=sized,
        constraint_snapshot=constraint_snapshot,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=minimum_risk_utilization_after_rounding,
        reference_price=zone_mid,
    )
    return dataclasses.replace(
        quantized,
        modeled_costs_per_unit=costs,
        sizing_entry_price=sizing_entry,
        stop_distance_rate=stop_distance_rate,
        cost_to_risk_ratio=cost_to_risk_ratio,
        fee_rate_entry=cost_rates.fee_rate_entry,
        fee_rate_exit=cost_rates.fee_rate_exit,
        fee_source=cost_rates.fee_source,
    )


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
    cost_rates: CostRates,
    min_stop_distance_rate: Decimal,
    max_cost_to_risk: Decimal,
    minimum_risk_utilization_after_rounding: Decimal,
    parameter_set: dict[str, Any],
) -> PortfolioVerdict:
    """Run `size_and_quantize` then `check_portfolio` in fixed order.

    The pipeline is the same function called in backtest/paper/live
    (D-02 parity guarantee). The first NO_TRADE short-circuits with its
    reason code preserved (`check_portfolio` passes an upstream no-trade
    through unchanged).

    `candidate_position_side` is required (no default) and must be a
    `Direction` value (LONG/SHORT). The cluster gate only sums open
    positions matching the candidate side, so guessing the side would
    mis-cluster SHORT plans and wrongfully PASS them — an unknown side
    raises instead of evaluating (fail closed).

    Cost model (Phase 12): `cost_rates` replaces the removed
    `modeled_costs_per_unit` keyword; the cost per unit is computed inside
    `size_and_quantize` from the sizing entry it chooses. Sizing uses the
    adverse zone edge (D-03), which supersedes the Phase 5 D-02 zone-mid rule
    for risk sizing; the zone mid remains the min-notional reference.

    `parameter_set` carries the portfolio thresholds ONLY (cluster_cap,
    max_aggregate_open_risk, max_open_positions, daily_loss_*_threshold) as
    ABSOLUTE quote amounts — callers holding raw registry rates convert first
    via `resolve_absolute_thresholds`. The cost guard thresholds are the
    required `min_stop_distance_rate` and `max_cost_to_risk` keywords.

    Non-positive equity never reaches this function: `AccountState`
    construction raises `ValueError` for `equity <= 0` (fail closed, no
    order path). Callers that must report the condition downstream map
    the exception to an `UNCERTAIN_ACCOUNT_STATE` envelope.
    """
    sized = size_and_quantize(
        trade_plan=trade_plan,
        candidate_position_side=candidate_position_side,
        account_state=account_state,
        constraint_snapshot=constraint_snapshot,
        cost_rates=cost_rates,
        min_stop_distance_rate=min_stop_distance_rate,
        max_cost_to_risk=max_cost_to_risk,
        minimum_risk_utilization_after_rounding=minimum_risk_utilization_after_rounding,
    )
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


def _emit_cost_rates_lineage(
    *,
    cost_rates: CostRates,
    costs: Decimal,
    sizing_entry: Decimal,
    stop_distance_rate: Decimal,
    cost_to_risk_ratio: Decimal,
) -> None:
    """Emit the `risk.cost_rates` decision-lineage event (D-12).

    Local structlog import preserves the module-level purity contract
    (same pattern as `quantization._emit_lineage`).
    """
    import structlog

    structlog.get_logger().info(
        "risk.cost_rates",
        fee_rate_entry=str(cost_rates.fee_rate_entry),
        fee_rate_exit=str(cost_rates.fee_rate_exit),
        fee_source=cost_rates.fee_source,
        modeled_costs_per_unit=str(costs),
        sizing_entry_price=str(sizing_entry),
        stop_distance_rate=str(stop_distance_rate),
        cost_to_risk_ratio=str(cost_to_risk_ratio),
    )


__all__ = ["evaluate_risk", "size_and_quantize"]
