"""The single R-denominator function (Phase 14, plan 14-01, D-20).

One pure function computes the realized risk that every R multiple divides by:
the realized risk persisted at sizing (`SizedResult.realized_risk`, the worst-case
adverse-edge figure) scaled by `filled_quantity / planned_quantity`. Backtest
records, the analytics normalizers and the excursion code all call it, so the
two paths can never carry competing denominators.

The module imports stdlib + Decimal + `src/core/_decimal.py` only, mirroring the
Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from decimal import Decimal

from src.core._decimal import _div, _mul

_ZERO = Decimal("0")


def realized_risk_for_fill(
    *,
    sized_realized_risk: Decimal,
    planned_quantity: Decimal,
    filled_quantity: Decimal,
) -> Decimal:
    """Return `sized_realized_risk x filled_quantity / planned_quantity`.

    Raises:
        TypeError: any input is not a Decimal (floats are refused, never coerced).
        ValueError: `planned_quantity <= 0`, `filled_quantity < 0` or
            `filled_quantity > planned_quantity`.
    """
    for name, value in (
        ("sized_realized_risk", sized_realized_risk),
        ("planned_quantity", planned_quantity),
        ("filled_quantity", filled_quantity),
    ):
        if not isinstance(value, Decimal):
            raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if planned_quantity <= _ZERO:
        raise ValueError(f"planned_quantity must be > 0, got {planned_quantity}")
    if filled_quantity < _ZERO:
        raise ValueError(f"filled_quantity must be >= 0, got {filled_quantity}")
    if filled_quantity > planned_quantity:
        raise ValueError(
            f"filled_quantity {filled_quantity} must be <= planned_quantity {planned_quantity}"
        )
    return _div(_mul(sized_realized_risk, filled_quantity), planned_quantity)
