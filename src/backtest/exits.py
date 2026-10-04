"""Protective-exit rules of the causal simulator (Phase 14, plans 14-01 and 14-07).

SL and TP triggers are evaluated on mark-price 1m klines (D-10, D037) at the live-snapped
trigger levels. The levels and the TP1 quantity come from the live helper
`size_protectives_to_filled_qty` of `src/execution/placement.py`, called with
`ProtectiveTemplate(tp1_quantity_fraction=TP1_QUANTITY_FRACTION)`; nothing is re-derived
here, so the backtest cannot drift from the legs the exchange would hold (D-11, D-27):
TP1 is a reduce-only partial of half the filled quantity (floored to the step, gated by
min quantity and min notional), TP2 closes the remainder, and the stop level never moves
after TP1. The exit price of every leg is its trigger price: no price improvement.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.core.types import Candle
from src.domain.trade_plan import TradePlan
from src.execution.placement import (
    ProtectiveTemplate,
    derive_sl_trigger_price,
    quantize_price,
    size_protectives_to_filled_qty,
    sl_trigger_rounding,
)
from src.risk.types import ConstraintSnapshot

from .semantics import POSITION_MODE, TP1_QUANTITY_FRACTION

_LONG = "LONG"
_SHORT = "SHORT"


@dataclass(frozen=True)
class ProtectiveLevels:
    """The protective legs of one plan at their live-snapped trigger prices.

    The TP fields stay `None` for a state built without the TP ladder (a stop-only
    state): such a position is exited by its stop alone.
    """

    sl_trigger: Decimal
    tp1_trigger: Decimal | None = None
    tp2_trigger: Decimal | None = None
    tp1_quantity: Decimal | None = None


@dataclass(frozen=True)
class ProtectiveReject:
    """TP1 cannot be sized for the filled quantity: the plan is a NO_TRADE reject (D-27).

    `reason_code` is the live `RejectionReason` value (MIN_QTY_REJECT, NOTIONAL_REJECT or
    EXCHANGE_CONSTRAINT) returned by `size_protectives_to_filled_qty`.
    """

    reason_code: str


def take_profit_levels(plan: TradePlan) -> tuple[Decimal, Decimal]:
    """Parse `(tp1, tp2)` from the planner's `take_profit_json` (fail closed on any defect)."""
    try:
        payload = json.loads(plan.take_profit_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"take_profit_json is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("take_profit_json must be a JSON object")
    parsed: list[Decimal] = []
    for key in ("tp1", "tp2"):
        raw = payload.get(key)
        if not isinstance(raw, str):
            raise ValueError(f"take_profit_json {key} must be a decimal string, got {raw!r}")
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"take_profit_json {key} is not a decimal: {raw!r}") from exc
        if not value.is_finite() or value <= Decimal("0"):
            raise ValueError(f"take_profit_json {key} must be a positive finite price, got {raw!r}")
        parsed.append(value)
    return parsed[0], parsed[1]


def _leg_decimal(leg: dict[str, Any] | None, key: str) -> Decimal:
    value = None if leg is None else leg.get(key)
    if not isinstance(value, Decimal):
        raise ValueError(f"protective leg field {key!r} must be a Decimal, got {value!r}")
    return value


def protective_levels_for_fill(
    *,
    plan: TradePlan,
    direction: str,
    filled_quantity: Decimal,
    constraint_snapshot: ConstraintSnapshot,
) -> ProtectiveLevels | ProtectiveReject:
    """Size the live protective legs for `filled_quantity` and return their levels (D-11, D-27).

    Builds `ProtectiveTemplate(tp1_quantity_fraction=TP1_QUANTITY_FRACTION)` from the plan's
    stop and `take_profit_json`, calls `size_protectives_to_filled_qty` in `POSITION_MODE`,
    and returns the snapped trigger prices plus the TP1 quantity of the legs. When the live
    helper rejects TP1 as un-sizeable (MIN_QTY_REJECT, NOTIONAL_REJECT, EXCHANGE_CONSTRAINT)
    the reason is returned as a `ProtectiveReject` and the engine turns it into a NO_TRADE.
    """
    if direction not in (_LONG, _SHORT):
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    tp1, tp2 = take_profit_levels(plan)
    template = ProtectiveTemplate(
        stop_loss_trigger_price=derive_sl_trigger_price(stop_loss_price=plan.stop_loss_price),
        tp1_trigger_price=tp1,
        tp2_trigger_price=tp2,
        tp1_quantity_fraction=TP1_QUANTITY_FRACTION,
    )
    sizing = size_protectives_to_filled_qty(
        filled_quantity=filled_quantity,
        protective_template=template,
        constraint_snapshot=constraint_snapshot,
        position_mode=POSITION_MODE,
        candidate_position_side=direction,
    )
    if sizing.is_no_trade:
        return ProtectiveReject(reason_code=sizing.reason_code)
    return ProtectiveLevels(
        sl_trigger=_leg_decimal(sizing.sl_leg, "trigger_price"),
        tp1_trigger=_leg_decimal(sizing.tp1_leg, "trigger_price"),
        tp2_trigger=_leg_decimal(sizing.tp2_leg, "trigger_price"),
        tp1_quantity=_leg_decimal(sizing.tp1_leg, "quantity"),
    )


def sl_trigger_price(*, plan: TradePlan, direction: str, price_tick_size: Decimal) -> Decimal:
    """Return the live SL trigger price: the plan's stop snapped toward the entry."""
    if direction not in (_LONG, _SHORT):
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    return quantize_price(
        price=derive_sl_trigger_price(stop_loss_price=plan.stop_loss_price),
        price_tick_size=price_tick_size,
        direction=sl_trigger_rounding(candidate_position_side=direction),
    )


def is_sl_touched(*, mark_minute: Candle, sl_trigger: Decimal, direction: str) -> bool:
    """True when a mark-price minute reaches the stop (LONG: low, SHORT: high)."""
    if direction == _LONG:
        return mark_minute.low <= sl_trigger
    if direction == _SHORT:
        return mark_minute.high >= sl_trigger
    raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")


def is_tp_touched(*, mark_minute: Candle, tp_trigger: Decimal, direction: str) -> bool:
    """True when a mark-price minute reaches a take-profit (LONG: high, SHORT: low)."""
    if direction == _LONG:
        return mark_minute.high >= tp_trigger
    if direction == _SHORT:
        return mark_minute.low <= tp_trigger
    raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
