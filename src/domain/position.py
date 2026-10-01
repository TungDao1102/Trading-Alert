"""Position frozen dataclass (Phase 3, plan 03-02).

Per D-01/D-02/D-11/D-12: frozen pure-Python dataclass with Decimal
money/qty/price fields, timezone-aware UTC datetime fields, and Enum
status fields. No `Optional` status; `Optional` is reserved for
"transition never happened" timestamps only.

The Position entity carries the DATA_MODEL §2.9 field list. The
exchange remains authoritative for the live position state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .enums import PositionStatus


def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")


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


@dataclass(frozen=True)
class Position:
    """Internal representation reconciled from Binance (DATA_MODEL §2.9).

    `position_side` and `mode` are validated non-empty strings (Phase 4
    may promote to Enum). `status` is a PositionStatus enum (D-10);
    NULL `closed_at_utc` means "transition never happened" (D-11).

    Money/qty/price fields are `Decimal` (D-12).
    """

    position_id: str
    symbol: str
    position_side: str  # LONG / SHORT / BOTH
    mode: str  # ONE_WAY / HEDGE
    quantity: Decimal
    entry_price: Decimal
    break_even_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    opened_at_utc: datetime  # aware UTC
    updated_at_utc: datetime  # aware UTC
    closed_at_utc: datetime | None = None  # None = "never happened" (D-11)
    status: PositionStatus = PositionStatus.UNKNOWN  # explicit (D-11)

    def __post_init__(self) -> None:
        # Validated non-empty strings (docstring contract).
        for fname in ("position_id", "symbol", "position_side", "mode"):
            _require_non_empty(getattr(self, fname), fname)
        # D-12: Decimal-only for money/qty/price fields.
        for fname in (
            "quantity",
            "entry_price",
            "break_even_price",
            "unrealized_pnl",
            "realized_pnl",
        ):
            _require_decimal(getattr(self, fname), fname)
        # D-12: UTC-aware datetimes only.
        _require_utc_aware(self.opened_at_utc, "opened_at_utc")
        _require_utc_aware(self.updated_at_utc, "updated_at_utc")
        if self.closed_at_utc is not None:
            _require_utc_aware(self.closed_at_utc, "closed_at_utc")
