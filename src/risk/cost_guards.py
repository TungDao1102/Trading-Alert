"""Cost guards for the shared risk step (Phase 12, plan 12-06, D-07).

Two guards run between sizing and quantization: STOP_TOO_TIGHT (the stop is
so close to the entry that fees and slippage dominate the stop distance) and
COST_TO_RISK_EXCEEDED (the modeled round-trip cost is too large a share of the
per-unit risk). Both thresholds are required, Decimal-only and range checked,
so a caller cannot disable a guard by passing 0, None or a float (T-12-15).

Purity (Phase 5 D-05): stdlib and Decimal only; no float arithmetic.
"""

from __future__ import annotations

from decimal import Decimal

from src.domain.enums import RejectionReason


def _require_decimal(value: object, field_name: str) -> Decimal:
    """Reject non-Decimal values (bool, int, float, str and None included)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    return value


def validate_guard_rates(
    *,
    min_stop_distance_rate: Decimal,
    max_cost_to_risk: Decimal,
) -> None:
    """Validate the two guard thresholds; raise instead of silently disabling a guard.

    Args:
        min_stop_distance_rate: minimum stop distance as a fraction of the
            sizing entry price; must be a Decimal in the open interval (0, 1).
        max_cost_to_risk: maximum modeled cost divided by per-unit risk; must
            be a Decimal in (0, 1].

    Raises:
        TypeError: a threshold is not a Decimal (float, str, int, bool, None).
        ValueError: a threshold is outside its range (NaN and infinity included).
    """
    min_stop = _require_decimal(min_stop_distance_rate, "min_stop_distance_rate")
    max_ratio = _require_decimal(max_cost_to_risk, "max_cost_to_risk")
    if not (Decimal("0") < min_stop < Decimal("1")):
        raise ValueError(
            f"min_stop_distance_rate must be in the open interval (0, 1), got {min_stop}"
        )
    if not (Decimal("0") < max_ratio <= Decimal("1")):
        raise ValueError(f"max_cost_to_risk must be in (0, 1], got {max_ratio}")


def check_cost_guards(
    *,
    stop_distance_rate: Decimal,
    cost_to_risk_ratio: Decimal,
    min_stop_distance_rate: Decimal,
    max_cost_to_risk: Decimal,
) -> str | None:
    """Return the first violated guard's reason code, or None when both pass.

    Order is fixed: the stop check comes first. Boundaries:

    * `STOP_TOO_TIGHT` when `stop_distance_rate` is STRICTLY BELOW
      `min_stop_distance_rate` (equality passes).
    * `COST_TO_RISK_EXCEEDED` when `cost_to_risk_ratio` is STRICTLY ABOVE
      `max_cost_to_risk` (equality passes).

    `cost_to_risk_ratio` is the modeled round-trip cost divided by the
    per-unit risk (`stop distance + cost`), not by the stop distance.
    """
    if stop_distance_rate < min_stop_distance_rate:
        return RejectionReason.STOP_TOO_TIGHT.value
    if cost_to_risk_ratio > max_cost_to_risk:
        return RejectionReason.COST_TO_RISK_EXCEEDED.value
    return None


__all__ = ["check_cost_guards", "validate_guard_rates"]
