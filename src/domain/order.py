"""Order frozen dataclass (Phase 3, plan 03-02).

Per D-01/D-02/D-11/D-12: frozen pure-Python dataclass with Decimal
money/qty/price fields, timezone-aware UTC datetime fields, and Enum
status fields. No `Optional` status; `Optional` is reserved for
"transition never happened" timestamps only.

The Order entity carries the DATA_MODEL §2.7 field list. Three
independent identifier fields (client_order_id, exchange_order_id,
algo_client_id) are required because Binance may use different
identifiers for normal and algo orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .enums import OrderStatus


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
class Order:
    """One row per exchange order intent/submission (DATA_MODEL §2.7).

    `order_role`, `side`, `position_side`, `order_type`, `time_in_force`
    are validated non-empty strings (Phase 4 may promote to Enum).
    `local_status` is an OrderStatus enum (D-10); `exchange_status` is
    a raw string (Binance may add new statuses without warning).

    `client_order_id`, `exchange_order_id`, and `algo_client_id` are
    independently nullable: Binance may use different identifiers for
    normal and algo orders.
    """

    order_id: str
    trade_plan_id: str | None  # FK to TradePlan (nullable)
    position_id: str | None  # FK to Position (nullable)
    parent_order_id: str | None  # FK to parent Order (nullable)
    order_role: str  # ENTRY / STOP / TP / CANCEL_REPLACE / OTHER
    exchange: str
    symbol: str
    side: str  # BUY / SELL
    position_side: str  # LONG / SHORT / BOTH
    order_type: str  # MARKET / LIMIT / STOP / TAKE_PROFIT / ...
    time_in_force: str  # GTC / IOC / FOK / GTX
    quantity: Decimal
    price: Decimal | None
    stop_price: Decimal | None
    close_position: bool
    reduce_only: bool
    client_order_id: str | None
    exchange_order_id: str | None
    algo_client_id: str | None
    exchange_status: str  # raw string from Binance
    local_status: OrderStatus  # explicit — never inferred (D-11)
    submitted_at_utc: datetime  # aware UTC
    updated_at_utc: datetime  # aware UTC
    canceled_at_utc: datetime | None = None  # None = "never happened" (D-11)

    def __post_init__(self) -> None:
        # D-12: Decimal-only for money/qty/price fields.
        _require_decimal(self.quantity, "quantity")
        if self.price is not None:
            _require_decimal(self.price, "price")
        if self.stop_price is not None:
            _require_decimal(self.stop_price, "stop_price")
        # D-12: UTC-aware datetimes only.
        _require_utc_aware(self.submitted_at_utc, "submitted_at_utc")
        _require_utc_aware(self.updated_at_utc, "updated_at_utc")
        if self.canceled_at_utc is not None:
            _require_utc_aware(self.canceled_at_utc, "canceled_at_utc")
