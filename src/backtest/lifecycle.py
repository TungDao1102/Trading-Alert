"""Pure plan/position lifecycle driver (Phase 14, plan 14-01, D-01).

A plan created at the close of strategy bar N is active only from bar N+1: no trade
or mark minute whose close is at or before the signal close is ever examined for a
fill or an exit (F-120). `advance` walks a window of 1m minutes read through the
lazy `MinuteSource` protocol and returns the next immutable `PlanState` plus the
`LifecycleEvent`s that happened inside the window.

`advance` is pure and window-parameterized: no clock, no I/O, no float. The engine
may re-advance a saved state over a shorter or later window; the same input gives
the same output. Minutes are examined in order; entry detection uses trade-price
minutes and stop detection uses mark-price minutes (D-08, D-10). On the fill minute
only the stop can trigger (D-33).

This plan (14-01) is the tracer slice: resting entry, one-tick trade-through fill,
mark-price stop. Expiry, invalidation and cancellation land in plan 14-02, the
TP1/TP2 ladder, stop gaps and END_OF_DATA in plan 14-07.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from src.core.types import Candle
from src.domain.trade_plan import TradePlan

from .entry import is_touch_only, is_trade_through, snapped_limit_price
from .exits import ProtectiveLevels, is_sl_touched, sl_trigger_price
from .semantics import ENTRY_FILLED, EXIT_SL, PARTIAL_FILL
from .series import MinuteSource

PHASE_RESTING = "RESTING"
PHASE_OPEN = "OPEN"
PHASE_CLOSED = "CLOSED"
_PHASES = frozenset({PHASE_RESTING, PHASE_OPEN, PHASE_CLOSED})

EVENT_FILL = "FILL"
EVENT_TP1 = "TP1"
EVENT_EXIT = "EXIT"
EVENT_CANCEL = "CANCEL"
EVENT_PENDING = "PENDING"
EVENT_KINDS = frozenset({EVENT_FILL, EVENT_TP1, EVENT_EXIT, EVENT_CANCEL, EVENT_PENDING})

_ZERO = Decimal("0")
_DIRECTIONS = frozenset({"LONG", "SHORT"})


@dataclass(frozen=True)
class PlanState:
    """Immutable state of one plan from resting entry to terminal outcome."""

    symbol: str
    direction: str
    plan: TradePlan
    signal_close_utc: datetime
    limit_price: Decimal
    price_tick_size: Decimal
    planned_quantity: Decimal
    fill_quantity: Decimal
    sized_realized_risk: Decimal
    levels: ProtectiveLevels
    phase: str = PHASE_RESTING
    entry_price: Decimal | None = None
    entry_time_utc: datetime | None = None
    remaining_quantity: Decimal | None = None
    tp1_quantity: Decimal | None = None
    tp1_price: Decimal | None = None
    tp1_time_utc: datetime | None = None
    touch_no_fill_count: int = 0
    gap_through_stop: bool = False
    fallback_applied: bool = False
    coverage_note: str | None = None
    entry_kind: str | None = None
    exit_kind: str | None = None
    exit_price: Decimal | None = None
    exit_time_utc: datetime | None = None
    resolved_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        if self.direction not in _DIRECTIONS:
            raise ValueError(f"direction must be LONG or SHORT, got {self.direction!r}")
        if self.phase not in _PHASES:
            raise ValueError(f"phase must be one of {sorted(_PHASES)}, got {self.phase!r}")


@dataclass(frozen=True)
class LifecycleEvent:
    """One thing that happened to a plan inside an advanced window."""

    kind: str
    symbol: str
    trade_plan_id: str
    time_utc: datetime
    price: Decimal | None
    quantity: Decimal | None
    entry_kind: str | None = None
    exit_kind: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"event kind must be one of {sorted(EVENT_KINDS)}, got {self.kind!r}")


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def new_plan_state(
    *,
    plan: TradePlan,
    symbol: str,
    direction: str,
    signal_close_utc: datetime,
    price_tick_size: Decimal,
    planned_quantity: Decimal,
    sized_realized_risk: Decimal,
    fill_quantity: Decimal | None = None,
) -> PlanState:
    """Build the RESTING state of a plan created at `signal_close_utc`.

    The limit and the SL trigger are the live-snapped prices (D-07, D-10). The filled
    quantity defaults to the planned quantity (canonical `partial_fill_fraction` 1.0,
    D-09); a smaller `fill_quantity` models a partial fill.
    """
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    _require_utc(signal_close_utc, "signal_close_utc")
    if planned_quantity <= _ZERO:
        raise ValueError(f"planned_quantity must be > 0, got {planned_quantity}")
    fill = planned_quantity if fill_quantity is None else fill_quantity
    if fill <= _ZERO or fill > planned_quantity:
        raise ValueError(
            f"fill_quantity {fill} must be in (0, planned_quantity {planned_quantity}]"
        )
    if sized_realized_risk < _ZERO:
        raise ValueError(f"sized_realized_risk must be >= 0, got {sized_realized_risk}")
    return PlanState(
        symbol=symbol,
        direction=direction,
        plan=plan,
        signal_close_utc=signal_close_utc,
        limit_price=snapped_limit_price(
            plan=plan, direction=direction, price_tick_size=price_tick_size
        ),
        price_tick_size=price_tick_size,
        planned_quantity=planned_quantity,
        fill_quantity=fill,
        sized_realized_risk=sized_realized_risk,
        levels=ProtectiveLevels(
            sl_trigger=sl_trigger_price(
                plan=plan, direction=direction, price_tick_size=price_tick_size
            )
        ),
    )


def _fill(state: PlanState, minute: Candle) -> tuple[PlanState, LifecycleEvent]:
    """Fill at the limit at the close of the deciding trade minute (D-07, D-08)."""
    entry_kind = ENTRY_FILLED if state.fill_quantity == state.planned_quantity else PARTIAL_FILL
    filled = replace(
        state,
        phase=PHASE_OPEN,
        entry_price=state.limit_price,
        entry_time_utc=minute.close_time_utc,
        remaining_quantity=state.fill_quantity,
        entry_kind=entry_kind,
    )
    event = LifecycleEvent(
        kind=EVENT_FILL,
        symbol=state.symbol,
        trade_plan_id=state.plan.trade_plan_id,
        time_utc=minute.close_time_utc,
        price=state.limit_price,
        quantity=state.fill_quantity,
        entry_kind=entry_kind,
    )
    return filled, event


def _stop_out(state: PlanState, minute: Candle) -> tuple[PlanState, LifecycleEvent]:
    """Exit the whole remaining position at the stop trigger (no price improvement)."""
    exit_quantity = state.remaining_quantity
    closed = replace(
        state,
        phase=PHASE_CLOSED,
        remaining_quantity=_ZERO,
        exit_kind=EXIT_SL,
        exit_price=state.levels.sl_trigger,
        exit_time_utc=minute.close_time_utc,
        resolved_at_utc=minute.close_time_utc,
    )
    event = LifecycleEvent(
        kind=EVENT_EXIT,
        symbol=state.symbol,
        trade_plan_id=state.plan.trade_plan_id,
        time_utc=minute.close_time_utc,
        price=state.levels.sl_trigger,
        quantity=exit_quantity,
        entry_kind=state.entry_kind,
        exit_kind=EXIT_SL,
    )
    return closed, event


def advance(
    state: PlanState,
    *,
    source: MinuteSource,
    start_exclusive: datetime,
    end_inclusive: datetime,
    bar: Candle | None,
) -> tuple[PlanState, tuple[LifecycleEvent, ...]]:
    """Advance one plan over the minutes closing in `(start_exclusive, end_inclusive]`.

    `start_exclusive` is clamped to at least `state.signal_close_utc`, so the signal
    bar's own minutes can never be read. `bar` is the strategy bar closing at
    `end_inclusive`, or `None` when the window ends mid-bar (a cancellation instant);
    it is reserved for the closed-candle invalidation rule of plan 14-02.

    RESTING: the first trade minute that trades through the limit fills the plan; a
    minute that only reaches the limit increments `touch_no_fill_count`. On the fill
    minute only the stop is checked, on the mark minute with the same open time (D-33).
    OPEN: mark minutes opening at or after the entry time are walked and the first stop
    touch exits at the trigger price.
    """
    del bar  # reserved for plan 14-02 (CANDLE_CLOSE invalidation)
    if state.phase == PHASE_CLOSED:
        return state, ()
    start = max(start_exclusive, state.signal_close_utc)
    if end_inclusive <= start:
        return state, ()

    events: list[LifecycleEvent] = []
    current = state
    mark = tuple(source.mark_minutes(state.symbol, start, end_inclusive))

    if current.phase == PHASE_RESTING:
        for minute in source.trade_minutes(state.symbol, start, end_inclusive):
            if is_trade_through(
                minute=minute,
                limit_price=current.limit_price,
                price_tick_size=current.price_tick_size,
                direction=current.direction,
            ):
                current, fill_event = _fill(current, minute)
                events.append(fill_event)
                for fill_mark in mark:
                    if fill_mark.open_time_utc != minute.open_time_utc:
                        continue
                    if is_sl_touched(
                        mark_minute=fill_mark,
                        sl_trigger=current.levels.sl_trigger,
                        direction=current.direction,
                    ):
                        current, exit_event = _stop_out(current, fill_mark)
                        events.append(exit_event)
                    break
                break
            if is_touch_only(
                minute=minute,
                limit_price=current.limit_price,
                price_tick_size=current.price_tick_size,
                direction=current.direction,
            ):
                current = replace(current, touch_no_fill_count=current.touch_no_fill_count + 1)

    if current.phase == PHASE_OPEN and current.entry_time_utc is not None:
        for mark_minute in mark:
            if mark_minute.open_time_utc < current.entry_time_utc:
                continue
            if is_sl_touched(
                mark_minute=mark_minute,
                sl_trigger=current.levels.sl_trigger,
                direction=current.direction,
            ):
                current, exit_event = _stop_out(current, mark_minute)
                events.append(exit_event)
                break

    return current, tuple(events)
