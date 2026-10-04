"""Protective-exit rules of the causal simulator (Phase 14, plan 14-01).

SL (and, from plan 14-07, TP) triggers are evaluated on mark-price 1m klines (D-10,
D037) at the live-snapped trigger levels. The SL trigger is the plan's stop snapped
with the live rounding rule (toward the entry), via the helpers of
`src/execution/placement.py`. The exit price is the trigger price: no price
improvement.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core.types import Candle
from src.domain.trade_plan import TradePlan
from src.execution.placement import derive_sl_trigger_price, quantize_price, sl_trigger_rounding
from src.risk.types import ConstraintSnapshot

_LONG = "LONG"
_SHORT = "SHORT"


@dataclass(frozen=True)
class ProtectiveLevels:
    """The protective legs of one plan at their live-snapped trigger prices.

    The TP fields stay `None` until plan 14-07 fills the TP1/TP2 ladder.
    """

    sl_trigger: Decimal
    tp1_trigger: Decimal | None = None
    tp2_trigger: Decimal | None = None
    tp1_quantity: Decimal | None = None


def sl_trigger_price(*, plan: TradePlan, direction: str, price_tick_size: Decimal) -> Decimal:
    """Return the live SL trigger price: the plan's stop snapped toward the entry."""
    if direction not in (_LONG, _SHORT):
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    return quantize_price(
        price=derive_sl_trigger_price(stop_loss_price=plan.stop_loss_price),
        price_tick_size=price_tick_size,
        direction=sl_trigger_rounding(candidate_position_side=direction),
    )


@dataclass(frozen=True)
class ProtectiveReject:
    """TP1 cannot be sized for the filled quantity: the plan is a NO_TRADE reject (D-27)."""

    reason_code: str


def protective_levels_for_fill(
    *,
    plan: TradePlan,
    direction: str,
    filled_quantity: Decimal,
    constraint_snapshot: ConstraintSnapshot,
) -> ProtectiveLevels | ProtectiveReject:
    """RED skeleton: stop only (wrong on purpose, replaced in the GREEN commit)."""
    del filled_quantity
    return ProtectiveLevels(
        sl_trigger=sl_trigger_price(
            plan=plan, direction=direction, price_tick_size=constraint_snapshot.price_tick_size
        )
    )


def is_sl_touched(*, mark_minute: Candle, sl_trigger: Decimal, direction: str) -> bool:
    """True when a mark-price minute reaches the stop (LONG: low, SHORT: high)."""
    if direction == _LONG:
        return mark_minute.low <= sl_trigger
    if direction == _SHORT:
        return mark_minute.high >= sl_trigger
    raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
