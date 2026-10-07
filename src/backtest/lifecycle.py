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

Plan 14-01 built the tracer slice (resting entry, one-tick trade-through fill, mark-price
stop); plan 14-02 added simulated-minute expiry, CANDLE_CLOSE invalidation, `cancel_plan`
and the resting half of `finalize_at_data_end`. The TP1/TP2 ladder, stop gaps and the
OPEN-state END_OF_DATA close land in plan 14-07.

Plan 14-17 adds the mark-hole annotation: while a position is open, a gap of more than one
minute between consecutive walked mark minutes is recorded in `PlanState.coverage_note`
(annotation only: nothing is resolved, repriced or counted, and `fallback_applied` is
untouched). The internal marker `mark_settled_through_utc` tracks how far mark coverage is
settled and is never copied into a record.

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

from .entry import (
    invalidation_level,
    is_invalidated,
    is_minute_eligible,
    is_touch_only,
    is_trade_through,
    snapped_limit_price,
)
from .exits import (
    LEG_TP1,
    ExitLeg,
    ProtectiveLevels,
    end_of_data_exit,
    resolve_fallback_hour,
    resolve_mark_minute,
    sl_trigger_price,
)
from .semantics import (
    DAILY_STOP_CANCEL,
    ENTRY_FILLED,
    EXIT_KINDS,
    EXPIRED,
    INVALIDATION_CANCEL,
    PARTIAL_FILL,
    PENDING_AT_DATA_END,
)
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
    # Open time of the last mark minute whose coverage is settled for an OPEN position
    # (walked, resolved by a bar fallback, or the minute before the fill). Internal: never
    # copied into a record (plan 14-17).
    mark_settled_through_utc: datetime | None = None

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
    levels: ProtectiveLevels | None = None,
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
        levels=levels
        if levels is not None
        else ProtectiveLevels(
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
        mark_settled_through_utc=minute.open_time_utc - _MINUTE,
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


def _apply_leg(state: PlanState, leg: ExitLeg) -> tuple[PlanState, LifecycleEvent]:
    """Apply one exit leg: TP1 reduces the position, every other kind closes the remainder.

    A TP1 leg lowers `remaining_quantity` and records `tp1_quantity`, `tp1_price` and
    `tp1_time_utc` while the stop level stays unchanged (D-11). SL, TP2 and END_OF_DATA legs
    close the plan at the leg price and time; a gapped stop sets `gap_through_stop`.
    """
    remaining = state.remaining_quantity
    if state.phase != PHASE_OPEN or remaining is None:
        raise ValueError(f"cannot apply a {leg.kind} leg to a {state.phase} plan")
    if leg.quantity <= _ZERO or leg.quantity > remaining:
        raise ValueError(f"{leg.kind} leg quantity {leg.quantity} must be in (0, {remaining}]")
    if leg.kind == LEG_TP1:
        reduced = replace(
            state,
            remaining_quantity=remaining - leg.quantity,
            tp1_quantity=leg.quantity,
            tp1_price=leg.price,
            tp1_time_utc=leg.time_utc,
        )
        event = LifecycleEvent(
            kind=EVENT_TP1,
            symbol=state.symbol,
            trade_plan_id=state.plan.trade_plan_id,
            time_utc=leg.time_utc,
            price=leg.price,
            quantity=leg.quantity,
            entry_kind=state.entry_kind,
        )
        return reduced, event
    if leg.kind not in EXIT_KINDS:
        raise ValueError(f"unknown exit leg kind {leg.kind!r}")
    if leg.quantity != remaining:
        raise ValueError(f"{leg.kind} must close the whole remaining quantity {remaining}")
    closed = replace(
        state,
        phase=PHASE_CLOSED,
        remaining_quantity=_ZERO,
        exit_kind=leg.kind,
        exit_price=leg.price,
        exit_time_utc=leg.time_utc,
        resolved_at_utc=leg.time_utc,
        gap_through_stop=state.gap_through_stop or leg.gap_through_stop,
    )
    event = LifecycleEvent(
        kind=EVENT_EXIT,
        symbol=state.symbol,
        trade_plan_id=state.plan.trade_plan_id,
        time_utc=leg.time_utc,
        price=leg.price,
        quantity=leg.quantity,
        entry_kind=state.entry_kind,
        exit_kind=leg.kind,
    )
    return closed, event


def _apply_legs(
    state: PlanState, legs: tuple[ExitLeg, ...], events: list[LifecycleEvent]
) -> PlanState:
    """Apply `legs` in order, appending their events; stops once the plan is closed."""
    current = state
    for leg in legs:
        current, event = _apply_leg(current, leg)
        events.append(event)
        if current.phase == PHASE_CLOSED:
            break
    return current


def _close_resting(
    state: PlanState, *, entry_kind: str, at_utc: datetime
) -> tuple[PlanState, LifecycleEvent]:
    """End a resting plan without a fill: CLOSED with `entry_kind` and a CANCEL event."""
    closed = replace(state, phase=PHASE_CLOSED, entry_kind=entry_kind, resolved_at_utc=at_utc)
    event = LifecycleEvent(
        kind=EVENT_CANCEL,
        symbol=state.symbol,
        trade_plan_id=state.plan.trade_plan_id,
        time_utc=at_utc,
        price=None,
        quantity=None,
        entry_kind=entry_kind,
    )
    return closed, event


_MINUTE = timedelta(seconds=60)


def _grid_floor(value: datetime) -> datetime:
    """Whole-minute instant at or before `value` (the open of the minute containing it)."""
    return value.replace(second=0, microsecond=0)


def _first_missing_mark_open(
    state: PlanState, *, mark: tuple[Candle, ...], bar: Candle
) -> datetime | None:
    """Open time of the first mark minute absent from `bar` while the position is open.

    `mark` holds every mark minute of the whole bar (not just the advanced window), and
    the expected minutes run from the later of the bar open and the fill minute itself to
    the last minute of the bar. A hole in an earlier mid-bar window of the same bar, or on
    the fill minute, is therefore found when the closing-bar window arrives (WR-09). Only
    a window that ends at the closing bar can name a hole: a mid-bar window never resolves
    anything (D-33).
    """
    entry_time = state.entry_time_utc
    if entry_time is None:
        return None
    first = max(_grid_floor(entry_time), bar.open_time_utc)
    last = (bar.close_time_utc - timedelta(milliseconds=1)).replace(second=0, microsecond=0)
    present = {minute.open_time_utc for minute in mark}
    expected = first
    while expected <= last:
        if expected not in present:
            return expected
        expected += _MINUTE
    return None


def _skipped_span(
    settled: datetime | None, next_open: datetime
) -> tuple[datetime, datetime] | None:
    """First and last whole mark minute missing between `settled` and `next_open`, if any."""
    if settled is None or next_open - settled <= _MINUTE:
        return None
    return settled + _MINUTE, next_open - _MINUTE


def _skipped_note(span: tuple[datetime, datetime]) -> str:
    """Coverage note for minutes with no mark price outside any bar-close fallback (14-17)."""
    first, last = span
    return (
        f"mark_price_1m_missing_from_{first.isoformat()}_to_{last.isoformat()}; "
        "stop and targets not evaluated minute by minute for the missing minutes"
    )


def _join_notes(existing: str | None, extra: list[str]) -> str | None:
    """Join an existing coverage note and new notes with ' | '; None when both are empty."""
    parts = ([existing] if existing else []) + extra
    return " | ".join(parts) if parts else None


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
    `end_inclusive` (anything else raises), or `None` when the window ends mid-bar (a
    cancellation instant), in which case invalidation is never evaluated (D-05).

    RESTING: minutes closing after `plan.expiry_utc` are skipped (D-04, D-33). The first
    eligible trade minute that trades through the limit fills the plan; a minute that
    only reaches the limit increments `touch_no_fill_count`. On the fill minute only the
    stop is checked, on the mark minute with the same open time (D-33). Without a fill,
    a strategy bar closing at `end_inclusive` beyond the CANDLE_CLOSE level cancels the
    plan INVALIDATION_CANCEL (D-05, D-35); otherwise a window reaching `expiry_utc` ends
    it EXPIRED at `expiry_utc`. Precedence: fill, then invalidation, then expiry.
    OPEN: mark minutes opening at or after the entry time are walked through
    `resolve_mark_minute` (stop first, TP1 partial, TP2). When `bar` closes the window and
    the bar has a hole in its mark minutes, the walk stops at the hole and the rest of the bar
    resolves once at the bar close through `resolve_fallback_hour` (D-12, D-33). A hole
    outside a closing-bar fallback (for example an hour in which the symbol has no strategy
    bar) is only annotated in `coverage_note`; nothing is resolved or repriced (plan 14-17).
    """
    if state.phase == PHASE_CLOSED:
        return state, ()
    start = max(start_exclusive, state.signal_close_utc)
    if end_inclusive <= start:
        return state, ()
    if bar is not None and bar.close_time_utc != end_inclusive:
        raise ValueError(
            f"bar closing {bar.close_time_utc.isoformat()} must close at the window end "
            f"{end_inclusive.isoformat()}; pass bar=None for a window that ends mid-bar"
        )

    events: list[LifecycleEvent] = []
    current = state
    mark = tuple(source.mark_minutes(state.symbol, start, end_inclusive))

    if current.phase == PHASE_RESTING:
        expiry_utc = current.plan.expiry_utc
        for minute in source.trade_minutes(state.symbol, start, end_inclusive):
            if not is_minute_eligible(minute=minute, expiry_utc=expiry_utc):
                continue
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
                    current = _apply_legs(
                        current,
                        resolve_mark_minute(
                            state=current, mark_minute=fill_mark, is_fill_minute=True
                        ),
                        events,
                    )
                    if current.phase == PHASE_OPEN:
                        current = replace(current, mark_settled_through_utc=fill_mark.open_time_utc)
                    break
                break
            if is_touch_only(
                minute=minute,
                limit_price=current.limit_price,
                price_tick_size=current.price_tick_size,
                direction=current.direction,
            ):
                current = replace(current, touch_no_fill_count=current.touch_no_fill_count + 1)
        if (
            current.phase == PHASE_RESTING
            and bar is not None
            and end_inclusive <= expiry_utc
            and is_invalidated(
                bar_close_price=bar.close,
                level=invalidation_level(current.plan),
                direction=current.direction,
            )
        ):
            # Fill first (above), invalidation second, expiry last: a bar closing exactly at
            # expiry_utc that is beyond the level is INVALIDATION_CANCEL, not EXPIRED (D-35).
            current, cancel_event = _close_resting(
                current, entry_kind=INVALIDATION_CANCEL, at_utc=end_inclusive
            )
            events.append(cancel_event)
        if current.phase == PHASE_RESTING and end_inclusive >= expiry_utc:
            current, expire_event = _close_resting(current, entry_kind=EXPIRED, at_utc=expiry_utc)
            events.append(expire_event)

    if current.phase == PHASE_OPEN and current.entry_time_utc is not None:
        first_missing = (
            None
            if bar is None
            else _first_missing_mark_open(
                current,
                mark=tuple(source.mark_minutes(state.symbol, bar.open_time_utc, end_inclusive)),
                bar=bar,
            )
        )
        settled = current.mark_settled_through_utc
        new_notes: list[str] = []
        for mark_minute in mark:
            if mark_minute.open_time_utc < current.entry_time_utc:
                continue
            if first_missing is not None and mark_minute.open_time_utc >= first_missing:
                break  # the rest of the bar resolves at the bar close, not minute by minute
            span = _skipped_span(settled, mark_minute.open_time_utc)
            if span is not None:
                new_notes.append(_skipped_note(span))
            settled = mark_minute.open_time_utc
            current = _apply_legs(
                current,
                resolve_mark_minute(state=current, mark_minute=mark_minute, is_fill_minute=False),
                events,
            )
            if current.phase == PHASE_CLOSED:
                break
        if new_notes or settled != current.mark_settled_through_utc:
            current = replace(
                current,
                mark_settled_through_utc=settled,
                coverage_note=_join_notes(current.coverage_note, new_notes),
            )
        if current.phase == PHASE_OPEN and bar is not None and first_missing is not None:
            resolution = resolve_fallback_hour(
                state=current, bar=bar, first_missing_open_utc=first_missing
            )
            note = resolution.coverage_note
            if current.coverage_note is not None:
                note = f"{current.coverage_note} | {note}"
            current = replace(current, fallback_applied=True, coverage_note=note)
            current = _apply_legs(current, resolution.legs, events)

    return current, tuple(events)


_CANCEL_KINDS = frozenset({EXPIRED, INVALIDATION_CANCEL, DAILY_STOP_CANCEL})


def cancel_plan(
    state: PlanState, *, entry_kind: str, at_utc: datetime
) -> tuple[PlanState, tuple[LifecycleEvent, ...]]:
    """Cancel a RESTING plan at an arbitrary instant (D-32, D033 DAILY_STOP_CANCEL).

    Returns the CLOSED state with `entry_kind` and a CANCEL event at `at_utc`. An OPEN
    position is never cancelled here: D033 keeps the stop of an open position, so asking
    to cancel one raises `ValueError`, as does a CLOSED state or a non-cancel `entry_kind`.
    """
    if entry_kind not in _CANCEL_KINDS:
        raise ValueError(f"entry_kind must be one of {sorted(_CANCEL_KINDS)}, got {entry_kind!r}")
    _require_utc(at_utc, "at_utc")
    if state.phase == PHASE_OPEN:
        raise ValueError("cannot cancel an OPEN position: its stop stays active (D033)")
    if state.phase != PHASE_RESTING:
        raise ValueError(f"cannot cancel a plan in phase {state.phase}")
    closed, event = _close_resting(state, entry_kind=entry_kind, at_utc=at_utc)
    return closed, (event,)


def finalize_at_data_end(
    state: PlanState, *, data_end_utc: datetime, source: MinuteSource | None = None
) -> tuple[PlanState, tuple[LifecycleEvent, ...]]:
    """Resolve a plan when the data ends (D-06, D-34).

    A RESTING plan becomes PENDING_AT_DATA_END (never EXPIRED) with a PENDING event at
    `data_end_utc`. A CLOSED plan is returned unchanged. An OPEN position (already advanced
    through the data) is closed at the last mark close at or before `data_end_utc` with
    exit kind END_OF_DATA (a flagged exit, never SL or TP); that needs the minute `source`,
    and without one it raises `ValueError` so no open position can silently pass through.
    """
    _require_utc(data_end_utc, "data_end_utc")
    if state.phase == PHASE_CLOSED:
        return state, ()
    if state.phase == PHASE_OPEN:
        if source is None:
            raise ValueError(
                "an OPEN position at data end needs the minute source for its END_OF_DATA close"
            )
        leg = end_of_data_exit(state=state, data_end_utc=data_end_utc, source=source)
        closed, exit_event = _apply_leg(state, leg)
        return closed, (exit_event,)
    pending = replace(
        state,
        phase=PHASE_CLOSED,
        entry_kind=PENDING_AT_DATA_END,
        resolved_at_utc=data_end_utc,
    )
    event = LifecycleEvent(
        kind=EVENT_PENDING,
        symbol=state.symbol,
        trade_plan_id=state.plan.trade_plan_id,
        time_utc=data_end_utc,
        price=None,
        quantity=None,
        entry_kind=PENDING_AT_DATA_END,
    )
    return pending, (event,)
