"""Fill frozen dataclass (Phase 3, plan 03-02).

Per D-01/D-02/D-12: frozen pure-Python dataclass with Decimal
money/qty/price fields and timezone-aware UTC datetime fields. Fills
are EVENTS, not state — there is no `status` field (DATA_MODEL §2.8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(
            f"{field_name} must be Decimal, got {type(value).__name__}"
        )


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")


@dataclass(frozen=True)
class Fill:
    """One row per execution/fill event (DATA_MODEL §2.8).

    Fills are events with no status field. The unique key where
    available is `(order_id, exchange_trade_id)`.

    Money/qty/price fields are `Decimal` (D-12). `side` and
    `position_side` are validated non-empty strings (Phase 4 may
    promote to Enum).
    """

    fill_id: str
    order_id: str  # FK to Order
    exchange_trade_id: str
    symbol: str
    side: str  # BUY / SELL
    position_side: str  # LONG / SHORT / BOTH
    fill_price: Decimal
    fill_quantity: Decimal
    quote_quantity: Decimal
    commission: Decimal
    commission_asset: str
    realized_pnl: Decimal
    fill_time_utc: datetime  # aware UTC
    is_maker: bool

    def __post_init__(self) -> None:
        # D-12: Decimal-only for money/qty/price fields.
        for fname in (
            "fill_price",
            "fill_quantity",
            "quote_quantity",
            "commission",
            "realized_pnl",
        ):
            _require_decimal(getattr(self, fname), fname)
        # D-12: UTC-aware datetimes only.
        _require_utc_aware(self.fill_time_utc, "fill_time_utc")
