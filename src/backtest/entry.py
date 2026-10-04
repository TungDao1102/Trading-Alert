"""Entry rules of the causal simulator (Phase 14, plan 14-01).

The simulated limit price is the price live would actually send: the zone mid,
snapped onto the tick grid with the live rounding rule (LONG floors, SHORT ceils).
The helpers of `src/execution/placement.py` are called, never re-derived, so the
backtest cannot drift from the order the exchange sees (D-07).

A LONG fills only when a trade-price 1m low is at or below `limit - tick`; a SHORT
only when a 1m high is at or above `limit + tick` (trade-through of at least one
tick). A minute that merely reaches the limit is a touch with no fill. The fill
price is the limit (no price improvement) and the fill time is the close of the
deciding minute (D-08).

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from decimal import Decimal

from src.core._decimal import _add, _sub
from src.core.types import Candle
from src.domain.trade_plan import TradePlan
from src.execution.placement import derive_limit_price, entry_limit_rounding, quantize_price

_LONG = "LONG"
_SHORT = "SHORT"


def _require_direction(direction: str) -> None:
    if direction not in (_LONG, _SHORT):
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")


def snapped_limit_price(*, plan: TradePlan, direction: str, price_tick_size: Decimal) -> Decimal:
    """Return the live limit price: zone mid snapped to the tick grid (D-07)."""
    _require_direction(direction)
    mid = derive_limit_price(
        entry_min_price=plan.entry_min_price, entry_max_price=plan.entry_max_price
    )
    return quantize_price(
        price=mid,
        price_tick_size=price_tick_size,
        direction=entry_limit_rounding(candidate_position_side=direction),
    )


def is_trade_through(
    *, minute: Candle, limit_price: Decimal, price_tick_size: Decimal, direction: str
) -> bool:
    """True when a trade-price minute trades through the limit by at least one tick."""
    _require_direction(direction)
    if direction == _LONG:
        return minute.low <= _sub(limit_price, price_tick_size)
    return minute.high >= _add(limit_price, price_tick_size)


def is_touch_only(
    *, minute: Candle, limit_price: Decimal, price_tick_size: Decimal, direction: str
) -> bool:
    """True when a minute reaches the limit price but does not trade through it."""
    _require_direction(direction)
    if is_trade_through(
        minute=minute,
        limit_price=limit_price,
        price_tick_size=price_tick_size,
        direction=direction,
    ):
        return False
    if direction == _LONG:
        return minute.low <= limit_price
    return minute.high >= limit_price
