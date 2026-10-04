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
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from src.core._decimal import _sub
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

from .semantics import (
    EXIT_END_OF_DATA,
    EXIT_SL,
    EXIT_TP2,
    POSITION_MODE,
    TP1_QUANTITY_FRACTION,
)
from .series import MinuteSource

if TYPE_CHECKING:
    from .lifecycle import PlanState

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


# Label of the TP1 partial leg. It is not an exit kind (a position never ends at TP1).
LEG_TP1 = "TP1"


@dataclass(frozen=True)
class ExitLeg:
    """One exit leg resolved from a mark minute or a fallback bar.

    `kind` is `LEG_TP1` (partial), `EXIT_SL`, `EXIT_TP2` or `EXIT_END_OF_DATA` (the last two
    ones close the remainder). `price` is the booked price: the trigger for a take-profit
    (no price improvement), the adverse of trigger and mark-minute open for a stop.
    `gap_through_stop` is True only for a stop leg priced at a gapped open.
    """

    kind: str
    price: Decimal
    quantity: Decimal
    time_utc: datetime
    gap_through_stop: bool = False


def _stop_leg(*, state: PlanState, mark_minute: Candle, quantity: Decimal) -> ExitLeg:
    """Exit `quantity` at the stop: the adverse of the trigger and the minute open (D-33)."""
    trigger = state.levels.sl_trigger
    if state.direction == _LONG:
        price = min(trigger, mark_minute.open)
    else:
        price = max(trigger, mark_minute.open)
    return ExitLeg(
        kind=EXIT_SL,
        price=price,
        quantity=quantity,
        time_utc=mark_minute.close_time_utc,
        gap_through_stop=price != trigger,
    )


def _tp_legs(*, state: PlanState, mark_minute: Candle, remaining: Decimal) -> tuple[ExitLeg, ...]:
    """TP1 then TP2 legs touched by a mark minute (TP1 first when both are touched)."""
    levels = state.levels
    tp1_trigger, tp1_quantity, tp2_trigger = (
        levels.tp1_trigger,
        levels.tp1_quantity,
        levels.tp2_trigger,
    )
    if tp1_trigger is None or tp1_quantity is None or tp2_trigger is None:
        return ()  # a stop-only state: the stop is its only exit
    direction = state.direction
    tp1_touched = is_tp_touched(
        mark_minute=mark_minute, tp_trigger=tp1_trigger, direction=direction
    )
    tp2_touched = is_tp_touched(
        mark_minute=mark_minute, tp_trigger=tp2_trigger, direction=direction
    )
    at_utc = mark_minute.close_time_utc
    legs: list[ExitLeg] = []
    tp1_taken = state.tp1_quantity is not None
    if not tp1_taken and (tp1_touched or tp2_touched):
        legs.append(
            ExitLeg(kind=LEG_TP1, price=tp1_trigger, quantity=tp1_quantity, time_utc=at_utc)
        )
        remaining = _sub(remaining, tp1_quantity)
        tp1_taken = True
    if tp1_taken and tp2_touched:
        legs.append(ExitLeg(kind=EXIT_TP2, price=tp2_trigger, quantity=remaining, time_utc=at_utc))
    return tuple(legs)


def resolve_mark_minute(
    *, state: PlanState, mark_minute: Candle, is_fill_minute: bool
) -> tuple[ExitLeg, ...]:
    """Return the ordered exit legs of one mark-price minute for an OPEN position (D-12, D-33).

    The stop is decided before any take-profit (stop-first, `semantics.TIE_BREAK`): a minute
    touching the stop closes the whole remaining quantity at the stop, whatever else it
    touched. On the fill minute only the stop is eligible, because the instant of the fill
    inside the minute is unknown. Otherwise TP1 (a partial, once) and then TP2 (the
    remainder) are returned in that order; a minute touching both books TP1 then TP2 at the
    same minute close. Take-profits book their trigger price; the stop books the adverse of
    trigger and minute open and flags a gap.
    """
    remaining = state.remaining_quantity
    if remaining is None or remaining <= Decimal("0"):
        raise ValueError("resolve_mark_minute needs an OPEN position with a remaining quantity")
    if is_sl_touched(
        mark_minute=mark_minute, sl_trigger=state.levels.sl_trigger, direction=state.direction
    ):
        return (_stop_leg(state=state, mark_minute=mark_minute, quantity=remaining),)
    if is_fill_minute:
        return ()
    return _tp_legs(state=state, mark_minute=mark_minute, remaining=remaining)


@dataclass(frozen=True)
class FallbackResolution:
    """The legs a strategy-bar-close fallback resolves, plus the coverage note to record."""

    legs: tuple[ExitLeg, ...]
    coverage_note: str


def resolve_fallback_hour(
    *, state: PlanState, bar: Candle, first_missing_open_utc: datetime
) -> FallbackResolution:
    """Resolve the rest of a strategy bar with missing mark minutes at the bar close (D-12, D-33).

    Used only when the mark series has a hole inside `bar` while a position is open: the
    minutes before `first_missing_open_utc` were walked normally and everything from the
    hole to the bar close resolves ONCE, at `bar.close_time_utc` (never mid-bar), from the
    trade-price range of the strategy bar and stop-first. A bar range touching the stop
    closes the whole remaining position at the stop trigger; otherwise TP1 and TP2 are
    resolved exactly as for a mark minute. When the position was filled inside this bar, the
    range also covers minutes before the fill, so only the stop may be resolved (the
    take-profit is deferred to the next bar, the fallback analogue of the fill-minute rule).
    Returns the legs (possibly none) and the coverage note naming the first missing minute.
    """
    remaining = state.remaining_quantity
    if remaining is None or remaining <= Decimal("0"):
        raise ValueError("resolve_fallback_hour needs an OPEN position with a remaining quantity")
    note = (
        f"mark_price_1m_missing_from_{first_missing_open_utc.isoformat()}; "
        f"resolved_at_strategy_bar_close_{bar.close_time_utc.isoformat()} "
        "from the trade-price bar range, stop first"
    )
    trigger = state.levels.sl_trigger
    if is_sl_touched(mark_minute=bar, sl_trigger=trigger, direction=state.direction):
        stop = ExitLeg(kind=EXIT_SL, price=trigger, quantity=remaining, time_utc=bar.close_time_utc)
        return FallbackResolution(legs=(stop,), coverage_note=note)
    entry_time = state.entry_time_utc
    if entry_time is not None and entry_time >= bar.open_time_utc:
        return FallbackResolution(legs=(), coverage_note=note)
    return FallbackResolution(
        legs=_tp_legs(state=state, mark_minute=bar, remaining=remaining), coverage_note=note
    )


def end_of_data_exit(*, state: PlanState, data_end_utc: datetime, source: MinuteSource) -> ExitLeg:
    """Close the remaining quantity at the last mark close at or before `data_end_utc` (D-06, D-34).

    The position is carried until SL, TP2 or data end; one still open when the data ends is
    closed here at the close of the last mark-price minute inside `[entry minute, data end]`,
    as an `END_OF_DATA` leg (a forced market close, so the record uses `exit_slippage_rate`),
    never booked as SL or TP. The mark series is read backward in doubling look-back windows
    (starting at one hour) so a long holding period is never loaded whole. Raises
    `ValueError` when no mark minute exists, because the close cannot be priced (fail closed).
    """
    remaining = state.remaining_quantity
    entry_time = state.entry_time_utc
    if remaining is None or entry_time is None or remaining <= Decimal("0"):
        raise ValueError("end_of_data_exit needs an OPEN position with a remaining quantity")
    floor_start = entry_time - timedelta(microseconds=1)  # includes the fill minute itself
    lookback = timedelta(hours=1)
    while True:
        window_start = max(floor_start, data_end_utc - lookback)
        minutes = source.mark_minutes(state.symbol, window_start, data_end_utc)
        if minutes:
            last = minutes[-1]
            return ExitLeg(
                kind=EXIT_END_OF_DATA,
                price=last.close,
                quantity=remaining,
                time_utc=last.close_time_utc,
            )
        if window_start == floor_start:
            raise ValueError(
                f"no mark-price minute for {state.symbol} between the entry "
                f"{entry_time.isoformat()} and the data end {data_end_utc.isoformat()}: "
                "cannot price the END_OF_DATA close"
            )
        lookback = lookback * 2


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
