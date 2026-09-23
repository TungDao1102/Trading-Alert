"""TradePlan frozen dataclass (Phase 3, plan 03-02).

Per D-01/D-02/D-11/D-12: frozen pure-Python dataclass with Decimal
money/qty/price fields, timezone-aware UTC datetime fields, and Enum
status fields. No `Optional` status; `Optional` is reserved for
"transition never happened" timestamps only.

The TradePlan entity carries the DATA_MODEL §2.4 field list. The
`trade_plan_id` derives from the parent signal hash via
`ids.derive_child_id` with the discriminator `trade_plan:v1`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .enums import TradePlanStatus


def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(
            f"{field_name} must be Decimal, got {type(value).__name__}"
        )


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(
            f"{field_name} must be UTC, got offset {value.utcoffset()}"
        )


@dataclass(frozen=True)
class TradePlan:
    """The executable interpretation of one signal (DATA_MODEL §2.4).

    `trade_plan_id` is the content hash from `ids.derive_child_id` with
    discriminator `trade_plan:v1` — never passed in by callers.
    `status` is explicit (D-11); NULL timestamps mean "transition never
    happened".

    Money/qty/price fields are `Decimal` (D-12). JSON-carrying fields
    are stored as strings (DATA_MODEL §5 JSON-as-TEXT rule).
    """

    trade_plan_id: str
    signal_id: str  # FK to Signal
    trade_plan_version: str
    entry_model: str  # validated non-empty string (Phase 4 may promote to Enum)
    entry_min_price: Decimal
    entry_max_price: Decimal
    stop_loss_price: Decimal
    take_profit_json: str  # JSON-as-TEXT
    invalidation_rule_json: str  # JSON-as-TEXT
    expiry_utc: datetime  # aware UTC
    expected_rr_json: str  # JSON-as-TEXT
    risk_rate: Decimal
    risk_budget: Decimal
    suggested_quantity: Decimal
    quantity_before_rounding: Decimal
    quantity_after_rounding: Decimal
    quantization_decision: str  # validated non-empty string
    plan_hash: str
    status: TradePlanStatus  # explicit — never inferred (D-11)
    created_at_utc: datetime  # aware UTC

    def __post_init__(self) -> None:
        # D-12: Decimal-only for money/qty/price fields.
        for fname in (
            "entry_min_price",
            "entry_max_price",
            "stop_loss_price",
            "risk_rate",
            "risk_budget",
            "suggested_quantity",
            "quantity_before_rounding",
            "quantity_after_rounding",
        ):
            _require_decimal(getattr(self, fname), fname)
        # D-12: UTC-aware datetimes only.
        _require_utc_aware(self.expiry_utc, "expiry_utc")
        _require_utc_aware(self.created_at_utc, "created_at_utc")
