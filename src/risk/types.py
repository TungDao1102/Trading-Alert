"""Pure-risk frozen dataclasses (Phase 5, plan 05-01).

Per D-05/D-12: frozen pure-Python dataclasses with Decimal money/qty/
price fields and timezone-aware UTC datetime fields. Construction-time
guards mirror the Phase-4 domain pattern (`src/core/types.py`,
`src/domain/trade_plan.py`).

These types are the value objects flowing between the sizing, quantize,
and gating services. All three live in this package and share the same
purity contract (stdlib + Decimal + `src/core/_decimal.py` only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


def _require_non_empty(value: str, field_name: str) -> None:
    """Reject empty strings for validated non-empty fields."""
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")


def _require_positive(value: Decimal, field_name: str) -> None:
    """Reject non-positive Decimals (D-04 fail-closed)."""
    if value <= Decimal("0"):
        raise ValueError(f"{field_name} must be > 0, got {value}")


# --------------------------------------------------------------------------- #
# ConstraintSnapshot — frozen adapter-edge mirror of SymbolFilters fields
# actually consumed by the risk pipeline (D-05 adapter-boundary isolation).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConstraintSnapshot:
    """ExchangeInfo-derived constraints consumed by risk math.

    Mirrors the fields the pure risk pipeline reads from the adapter's
    SymbolFilters — never imports the SDK. `metadata_observed_at_utc`
    drives the TTL freshness gate (D-04); step/min/notional drive
    quantization (D-02).
    """

    symbol: str
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    metadata_observed_at_utc: datetime

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        for fname in (
            "price_tick_size",
            "quantity_step_size",
            "min_quantity",
            "min_notional",
        ):
            _require_decimal(getattr(self, fname), fname)
        _require_positive(self.price_tick_size, "price_tick_size")
        _require_positive(self.quantity_step_size, "quantity_step_size")
        _require_positive(self.min_quantity, "min_quantity")
        _require_positive(self.min_notional, "min_notional")
        _require_utc_aware(self.metadata_observed_at_utc, "metadata_observed_at_utc")


# --------------------------------------------------------------------------- #
# SizedResult — discriminated ACCEPTED-or-REJECT envelope emitted by sizing
# + quantization. Mirrors the PlanResult discipline from src/core/types.py.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SizedResult:
    """Sized (or rejected) plan fields emitted by the risk pipeline.

    `is_no_trade=True` carries a canonical RejectionReason value in
    `reason_code`; `quantity` is None in that case (never a stale value
    riding along on a reject — WR-09 mirror for risk output).
    `quantity_before_rounding` and `quantity_after_rounding` are always
    populated; `realized_risk` is the canonical "actual dollars at risk
    after rounding" value used by the utilization gate and logged per
    RISK_MANAGEMENT §11 rule 5.
    """

    is_no_trade: bool
    quantity: Decimal | None
    quantity_before_rounding: Decimal
    quantity_after_rounding: Decimal
    quantization_decision: str
    realized_risk: Decimal
    reason_code: str = "OK"

    def __post_init__(self) -> None:
        _require_non_empty(self.quantization_decision, "quantization_decision")
        _require_non_empty(self.reason_code, "reason_code")
        for fname in (
            "quantity_before_rounding",
            "quantity_after_rounding",
            "realized_risk",
        ):
            _require_decimal(getattr(self, fname), fname)
        if self.is_no_trade:
            if self.quantity is not None:
                raise ValueError("SizedResult: is_no_trade=True requires quantity=None")
        else:
            if self.quantity is None:
                raise ValueError("SizedResult: is_no_trade=False requires quantity to be Decimal")
            _require_decimal(self.quantity, "quantity")
            if self.quantity <= Decimal("0"):
                raise ValueError(f"SizedResult: quantity {self.quantity} must be > 0 when sized")


__all__ = [
    "ConstraintSnapshot",
    "SizedResult",
]
