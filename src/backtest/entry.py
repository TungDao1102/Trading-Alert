"""Entry rules of the causal simulator (Phase 14, plan 14-01).

The simulated limit price is the price live would actually send: the zone mid,
snapped onto the tick grid with the live rounding rule (LONG floors, SHORT ceils).
The helpers of `src/execution/placement.py` are called, never re-derived, so the
backtest cannot drift from the order the exchange sees (D-07).

A resting plan is invalidated only at a strategy-bar close: a LONG when the bar close is
below the plan's CANDLE_CLOSE level, a SHORT when it is above (D-05, D-35). The level is
the plan's own `stop_loss_price` as written by the planner.

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

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from src.core._decimal import _add, _sub
from src.core.types import Candle
from src.domain.trade_plan import TradePlan
from src.execution.placement import derive_limit_price, entry_limit_rounding, quantize_price

_LONG = "LONG"
_SHORT = "SHORT"
_CANDLE_CLOSE = "CANDLE_CLOSE"


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


def is_minute_eligible(*, minute: Candle, expiry_utc: datetime) -> bool:
    """True when a minute may still fill the plan: its close is at or before expiry (D-04, D-33).

    The comparison is `<=` against the minute's own close time, so the last eligible
    minute is the one closing exactly at `expiry_utc` and the next minute is not. Expiry
    is judged against the simulated minute, never against a fixture clock.
    """
    return minute.close_time_utc <= expiry_utc


def is_trade_through(
    *, minute: Candle, limit_price: Decimal, price_tick_size: Decimal, direction: str
) -> bool:
    """True when a trade-price minute trades through the limit by at least one tick."""
    _require_direction(direction)
    if direction == _LONG:
        return minute.low <= _sub(limit_price, price_tick_size)
    return minute.high >= _add(limit_price, price_tick_size)


def is_touch(*, minute: Candle, limit_price: Decimal, direction: str) -> bool:
    """True when a trade-price minute reaches the limit (LONG low <= limit, SHORT high >= limit).

    A touch alone never fills; whether it also traded through is `is_trade_through`.
    """
    _require_direction(direction)
    if direction == _LONG:
        return minute.low <= limit_price
    return minute.high >= limit_price


def is_touch_only(
    *, minute: Candle, limit_price: Decimal, price_tick_size: Decimal, direction: str
) -> bool:
    """True when a minute reaches the limit price but does not trade through it (D-07)."""
    if is_trade_through(
        minute=minute,
        limit_price=limit_price,
        price_tick_size=price_tick_size,
        direction=direction,
    ):
        return False
    return is_touch(minute=minute, limit_price=limit_price, direction=direction)


def invalidation_level(plan: TradePlan) -> Decimal:
    """Parse the plan's CANDLE_CLOSE invalidation level as a `Decimal` (D-35).

    Fails closed: an unparseable rule, a basis other than CANDLE_CLOSE, or a missing,
    non-string or non-numeric level raises `ValueError` rather than guessing a level.
    """
    try:
        rule = json.loads(plan.invalidation_rule_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalidation_rule_json is not valid JSON: {exc}") from exc
    if not isinstance(rule, dict):
        raise ValueError("invalidation_rule_json must be a JSON object")
    basis = rule.get("basis")
    if basis != _CANDLE_CLOSE:
        raise ValueError(f"invalidation basis must be CANDLE_CLOSE, got {basis!r}")
    raw = rule.get("level")
    if not isinstance(raw, str):
        raise ValueError(f"invalidation level must be a decimal string, got {raw!r}")
    try:
        level = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalidation level is not a decimal: {raw!r}") from exc
    if not level.is_finite():
        raise ValueError(f"invalidation level must be finite, got {raw!r}")
    return level


def is_invalidated(*, bar_close_price: Decimal, level: Decimal, direction: str) -> bool:
    """True when a strategy-bar close is strictly beyond the invalidation level (D-05, D-35)."""
    _require_direction(direction)
    if direction == _LONG:
        return bar_close_price < level
    return bar_close_price > level
