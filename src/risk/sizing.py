"""Pure position-sizing function (Phase 5, plan 05-01).

Per D-01 + RISK_MANAGEMENT §§1-3: `size_position` consumes a Phase-4
TradePlan DEFERRED_TO_RISK estimate fields as inputs (never re-derived)
plus equity, risk_rate, entry_ref, and modeled_costs_per_unit, and
returns raw quantity equal to `allowed_risk / risk_per_unit`, all in
Decimal under pinned prec-28.

The function never imports the SDK, never reads a clock, never reads
the environment. The same call linked into backtest/paper/live produces
byte-identical outputs (parity fixture is the enforcement mechanism).
"""

from __future__ import annotations

from decimal import Decimal

from src.core._decimal import _add, _div, _mul, _sub
from src.core.types import AccountState
from src.domain.enums import QuantizationDecision, RejectionReason
from src.domain.trade_plan import TradePlan

from .types import SizedResult

# Reason code strings — use enum values for byte-identity with GLOSSARY §9.
_OK = "OK"
_DEFERRED = QuantizationDecision.DEFERRED_TO_RISK.value


def size_position(
    *,
    trade_plan: TradePlan,
    account_state: AccountState,
    entry_ref: Decimal,
    modeled_costs_per_unit: Decimal,
) -> SizedResult:
    """Compute raw position size per D-01 canonical formula.

    `entry_ref` is the SIZING entry chosen by the caller: since Phase 12
    (D-03) `size_and_quantize` passes the adverse zone edge (LONG
    `entry_max`, SHORT `entry_min`), not the zone mid. The formula below is
    unchanged (D-02); `modeled_costs_per_unit` is quote currency per unit,
    produced by `per_unit_round_trip_cost` for that same entry.

    `allowed_risk = equity × risk_rate`.
    `sl_distance = |entry_ref - stop_loss_price|`.
    `risk_per_unit = sl_distance + modeled_costs_per_unit`.
    `raw_quantity = allowed_risk / risk_per_unit`.

    Returns a SizedResult with `quantity_before_rounding = quantity_after_rounding
    = raw_quantity` (passthrough — quantization owns the floor in
    `quantize()`). Zero/negative `risk_per_unit` returns
    `is_no_trade=True` with `EXCHANGE_CONSTRAINT` (Pitfall 1 — never
    divide by zero).
    """
    # Inputs the caller must already have validated:
    # - `trade_plan` is a frozen TradePlan (TradePlan.__post_init__ guards)
    # - `account_state` is a frozen AccountState with equity>0 and risk_rate in (0,1]
    # We re-derive sl_distance from the plan + entry_ref so risk never trusts
    # the plan's `risk_budget` directly (D-02: plan fields are consumed as
    # inputs but risk recomputes the math from canonical inputs).
    entry_ref_d = _require_decimal(entry_ref, "entry_ref")
    costs = _require_decimal(modeled_costs_per_unit, "modeled_costs_per_unit")

    sl_distance = abs(_sub(entry_ref_d, trade_plan.stop_loss_price))
    risk_per_unit = _add(sl_distance, costs)

    # Fail-closed on degenerate geometry OR non-positive risk_per_unit
    # (Pitfall 1: zero SL distance divides by zero with or without costs;
    # negative costs are also non-positive).
    if sl_distance <= Decimal("0") or risk_per_unit <= Decimal("0"):
        return SizedResult(
            is_no_trade=True,
            quantity=None,
            quantity_before_rounding=Decimal("0"),
            quantity_after_rounding=Decimal("0"),
            quantization_decision=QuantizationDecision.REJECTED.value,
            realized_risk=Decimal("0"),
            reason_code=RejectionReason.EXCHANGE_CONSTRAINT.value,
        )

    allowed_risk = _mul(account_state.equity, account_state.risk_rate)
    raw_quantity = _div(allowed_risk, risk_per_unit)

    return SizedResult(
        is_no_trade=False,
        quantity=raw_quantity,
        quantity_before_rounding=raw_quantity,
        quantity_after_rounding=raw_quantity,
        quantization_decision=_DEFERRED,
        realized_risk=allowed_risk,
        reason_code=_OK,
    )


def _require_decimal(value: object, field_name: str) -> Decimal:
    """Reject non-Decimal values for money/qty/price inputs (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    return value


__all__ = ["size_position"]
