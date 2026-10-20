"""Exchange lot filters for one symbol (Phase 19, plan 19-04, D-16, D-19).

`LotFilters` carries the exchangeInfo LOT_SIZE, MARKET_LOT_SIZE, tick and MIN_NOTIONAL
values that the emergency close and the TP legs need. The values come from live
exchangeInfo or from the per-plan constraint snapshot; none is ever defaulted. A missing
or invalid value is an error naming the field, so the caller cannot size an order from a
guess.

Stdlib and Decimal only (the pure domain boundary).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_MAX_SYMBOL_LEN = 32


def _require_positive_decimal(value: object, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {value}")
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")


@dataclass(frozen=True, kw_only=True)
class LotFilters:
    """LOT_SIZE and MARKET_LOT_SIZE (min, max, step), tick size and min notional.

    A quantity is valid under a filter when `min <= q <= max` and `(q - min)` is a whole
    multiple of `step` (Binance common definition, research B8). A MARKET exit must be
    valid under both filters.
    """

    symbol: str
    price_tick_size: Decimal
    lot_min_quantity: Decimal
    lot_max_quantity: Decimal
    lot_step_size: Decimal
    market_lot_min_quantity: Decimal
    market_lot_max_quantity: Decimal
    market_lot_step_size: Decimal
    min_notional: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str):
            raise TypeError(f"symbol must be str, got {type(self.symbol).__name__}")
        if self.symbol == "" or len(self.symbol) > _MAX_SYMBOL_LEN:
            raise ValueError(f"symbol must be 1..{_MAX_SYMBOL_LEN} characters")
        for name in (
            "price_tick_size",
            "lot_min_quantity",
            "lot_max_quantity",
            "lot_step_size",
            "market_lot_min_quantity",
            "market_lot_max_quantity",
            "market_lot_step_size",
            "min_notional",
        ):
            _require_positive_decimal(getattr(self, name), name)
        if self.lot_min_quantity > self.lot_max_quantity:
            raise ValueError("lot_min_quantity must be <= lot_max_quantity")
        if self.market_lot_min_quantity > self.market_lot_max_quantity:
            raise ValueError("market_lot_min_quantity must be <= market_lot_max_quantity")
