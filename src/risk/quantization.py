"""Pure quantization function (Phase 5, plan 05-01).

Per D-02 + RISK_MANAGEMENT §11: `quantize` floors raw quantity via exact
Decimal floor-division by `quantity_step_size`, then applies the
min-quantity reject, notional reject, and 60% realized-risk /
allowed-risk utilization gate in fixed order — first failure wins.

The function never rounds up to meet minimums (§11 rule 1). The
utilization gate uses `realized_risk / allowed_risk` (NOT
`rounded / raw_quantity`) — the parity fixture pins a nonzero-cost
case that distinguishes the two metrics (Pitfall 2).
"""

from __future__ import annotations

from decimal import Decimal

from src.core._decimal import _div, _mul
from src.domain.enums import QuantizationDecision, RejectionReason

from .types import ConstraintSnapshot, SizedResult

_OK = "OK"


def quantize(
    *,
    sized: SizedResult,
    constraint_snapshot: ConstraintSnapshot,
    allowed_risk: Decimal,
    risk_per_unit: Decimal,
    minimum_risk_utilization_after_rounding: Decimal,
    reference_price: Decimal,
) -> SizedResult:
    """Floor raw quantity and apply the §11 gate order.

    Gate order (first failure wins):
      1. `rounded < min_quantity` → `MIN_QTY_REJECT`
      2. `rounded × reference_price < min_notional` → `NOTIONAL_REJECT`
      3. `realized_risk / allowed_risk < minimum_risk_utilization_after_rounding`
         → `UTILIZATION_REJECT`

    On accept: returns SizedResult with `quantity = rounded`,
    `quantization_decision = ACCEPTED`, `realized_risk = rounded × risk_per_unit`.
    On reject: returns SizedResult with `is_no_trade = True`,
    `quantity = None`, `quantization_decision = REJECTED`, and the
    matching D-05 reason code.

    Defensive fail-closed: zero/negative `quantity_step_size`,
    `min_quantity`, `min_notional`, or `reference_price` returns
    `EXCHANGE_CONSTRAINT` (Pitfall 1 — never divide by zero).
    """
    raw_quantity = sized.quantity_before_rounding

    # Defensive: zero/negative step_size or reference_price → fail closed.
    if constraint_snapshot.quantity_step_size <= Decimal("0"):
        return _reject(
            sized=sized,
            rounded=raw_quantity,
            realized_risk=Decimal("0"),
            reason_code=RejectionReason.EXCHANGE_CONSTRAINT.value,
        )
    if reference_price <= Decimal("0"):
        return _reject(
            sized=sized,
            rounded=raw_quantity,
            realized_risk=Decimal("0"),
            reason_code=RejectionReason.EXCHANGE_CONSTRAINT.value,
        )

    # Exact Decimal floor-division (Pitfall 2 mitigation: never round up).
    steps = raw_quantity // constraint_snapshot.quantity_step_size
    rounded = steps * constraint_snapshot.quantity_step_size

    # Gate 1: min-quantity reject.
    if rounded < constraint_snapshot.min_quantity:
        return _reject(
            sized=sized,
            rounded=rounded,
            realized_risk=_mul(rounded, risk_per_unit),
            reason_code=RejectionReason.MIN_QTY_REJECT.value,
        )

    # Gate 2: notional reject (zone-mid entry_ref per locked D-02 decision).
    notional = _mul(rounded, reference_price)
    if notional < constraint_snapshot.min_notional:
        return _reject(
            sized=sized,
            rounded=rounded,
            realized_risk=_mul(rounded, risk_per_unit),
            reason_code=RejectionReason.NOTIONAL_REJECT.value,
        )

    # Gate 3: utilization reject (realized_risk / allowed_risk, NOT
    # rounded / raw_quantity — Pitfall 2 distinguishing case).
    realized_risk = _mul(rounded, risk_per_unit)
    if allowed_risk > Decimal("0"):
        utilization = _div(realized_risk, allowed_risk)
    else:
        # Defensive: zero allowed_risk → fail closed.
        return _reject(
            sized=sized,
            rounded=rounded,
            realized_risk=realized_risk,
            reason_code=RejectionReason.UNCERTAIN_ACCOUNT_STATE.value,
        )
    if utilization < minimum_risk_utilization_after_rounding:
        return _reject(
            sized=sized,
            rounded=rounded,
            realized_risk=realized_risk,
            reason_code=RejectionReason.UTILIZATION_REJECT.value,
        )

    # All gates passed → ACCEPTED.
    return SizedResult(
        is_no_trade=False,
        quantity=rounded,
        quantity_before_rounding=sized.quantity_before_rounding,
        quantity_after_rounding=rounded,
        quantization_decision=QuantizationDecision.ACCEPTED.value,
        realized_risk=realized_risk,
        reason_code=_OK,
    )


def _reject(
    *,
    sized: SizedResult,
    rounded: Decimal,
    realized_risk: Decimal,
    reason_code: str,
) -> SizedResult:
    """Build a SizedResult with is_no_trade=True and the given reason code."""
    return SizedResult(
        is_no_trade=True,
        quantity=None,
        quantity_before_rounding=sized.quantity_before_rounding,
        quantity_after_rounding=rounded,
        quantization_decision=QuantizationDecision.REJECTED.value,
        realized_risk=realized_risk,
        reason_code=reason_code,
    )


__all__ = ["quantize"]
