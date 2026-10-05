"""v2 event-loop engine of the causal simulator (Phase 14, plan 14-08, D-01, D-17..D-19, D-32).

`simulate(case_input, *, risk_fn, minute_source=None)` replaces the per-bar v1 `run`. The
loop walks the union of the strategy-bar closes (and the scripted-plan closes) sorted by
`(time, symbol)`. At each distinct close `T` it does, in this order (D-18):

  1. advance every active plan and position over the elapsed window `(previous close, T]`
     with `lifecycle.advance` and turn the events (fills, TP1 legs, exits, cancels) and the
     funding payments of every open position into dated `Booking`s;
  2. apply those bookings to the ledger in `(time, symbol)` order; when a booking moves the
     UTC day into DAILY_STOP, every resting entry that had not filled by that instant is
     cancelled DAILY_STOP_CANCEL at that instant while open positions keep their stop
     (D-32, D033);
  3. only then evaluate the new setups of the symbols closing at `T`, in sorted symbol
     order, with the updated ledger: equity, exposures including resting entries, daily
     loss, the point-in-time constraint snapshot and `ttl = timedelta(0)` (D-17, D035).

A plan created at close N is active from bar N+1 because `advance` never reads a minute
closing at or before the signal close (D-01). There is at most one active plan or position
per symbol: a setup firing meanwhile is skipped and counted under the summary label
`CONFLICT_WITH_OPEN_POSITION`, which is not a `RejectionReason` (D-32).

`risk_fn` is the shared `evaluate_risk` (or a stand-in with its keyword signature). The engine
never imports it: `simulator.run` (plan 14-12) passes its module-global `evaluate_risk`, so a
test can monkeypatch `src.backtest.simulator.evaluate_risk`.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic and reads no clock: stdlib + Decimal + the pure `src` core only.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from heapq import heappop, heappush
from itertools import count
from typing import Any

from src.core._decimal import _add, _mul, _sub
from src.core.planner import plan as build_trade_plan
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot
from src.domain.registry import ParameterSet, load_parameter_set
from src.domain.trade_plan import TradePlan
from src.risk.realized_risk import realized_risk_for_fill
from src.risk.types import PortfolioVerdict

from .binding import assert_sizing_costs_bind_registry
from .case import FUNDING_SERIES, ParsedCase, ScriptedPlan, parse_case_input
from .constraints import PitConstraint, select_constraints
from .costs import cost_rates_from_model, guard_rates_from_params
from .exits import ProtectiveReject, protective_levels_for_fill
from .funding import FundingEvent, FundingGap, FundingRow, OpenSegment, funding_events
from .ledger import (
    Ledger,
    apply_booking,
    cancel_resting_required,
    daily_loss_quote,
    equity_positive,
    open_positions_for_risk,
    register_exposure,
    remove_exposure,
    roll_to,
    update_exposure,
)
from .lifecycle import (
    EVENT_CANCEL,
    EVENT_EXIT,
    EVENT_FILL,
    EVENT_PENDING,
    EVENT_TP1,
    PHASE_CLOSED,
    PHASE_OPEN,
    PHASE_RESTING,
    LifecycleEvent,
    PlanState,
    advance,
    cancel_plan,
    finalize_at_data_end,
    new_plan_state,
)
from .records import (
    BOOKING_CANCEL,
    BOOKING_FUNDING,
    BOOKING_PENDING,
    Booking,
    TradeRecord,
    booking_for_event,
    build_reject_record,
    build_trade_record,
)
from .semantics import (
    CONTEXT_WINDOW_BARS,
    DAILY_STOP_CANCEL,
    EXIT_END_OF_DATA,
    FUNDING_JITTER,
    FUNDING_MAX_CADENCE,
    NO_TRADE_CONFLICT,
    PLAN_SOURCE_SCRIPTED,
    PLAN_SOURCE_STRATEGY,
    SIMULATOR_SEMANTICS_VERSION,
    STRATEGY_WINDOW_BARS,
)
from .series import MinuteSource
from .validator import validate_trade_record

RiskFn = Callable[..., PortfolioVerdict]

_ZERO = Decimal("0")
_UNCERTAIN_ACCOUNT_STATE = "UNCERTAIN_ACCOUNT_STATE"
_MIN_QTY_REJECT = "MIN_QTY_REJECT"
_SOURCE_TIMEFRAME = "1h"

# Order of the items sharing one instant: funding first, then the lifecycle order of a plan.
_RANK_FUNDING = 0
_EVENT_RANK = {EVENT_FILL: 1, EVENT_TP1: 2, EVENT_EXIT: 3, EVENT_CANCEL: 4, EVENT_PENDING: 5}


@dataclass
class _Entity:
    """The one active plan or position of a symbol, with the numbers the records need."""

    state: PlanState
    advanced_to: datetime
    extrapolated: bool
    funding_amount: Decimal = _ZERO
    funding_count: int = 0
    exposure_remaining: Decimal = _ZERO


@dataclass
class _Item:
    """One thing to book inside a window: a lifecycle event or a funding payment."""

    entity: _Entity
    event: LifecycleEvent | None = None
    funding: FundingEvent | None = None


@dataclass(frozen=True)
class EngineRun:
    """A finished simulation: the output dict, every ledger booking and the final ledger."""

    output: dict[str, Any]
    bookings: tuple[Booking, ...]
    ledger: Ledger


@dataclass
class _Window:
    """Working state of one advanced window (all active entities, one closing instant)."""

    start_states: dict[str, PlanState] = field(default_factory=dict)
    end_states: dict[str, PlanState] = field(default_factory=dict)
    events: dict[str, tuple[LifecycleEvent, ...]] = field(default_factory=dict)
    dropped: set[str] = field(default_factory=set)
    heap: list[tuple[datetime, str, int, int, _Item]] = field(default_factory=list)
    sequence: count[int] = field(default_factory=count)


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Floor `value` to a whole number of `step`s (never rounds up, AGENTS quantization)."""
    return _mul(value // step, step)


def _open_segments(
    start_state: PlanState,
    events: Sequence[LifecycleEvent],
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[OpenSegment]:
    """Constant-quantity stretches a position was open inside one window (D-14, D-36).

    A position open at the window start is open from `window_start` with its remaining
    quantity; a FILL event opens it at the fill time; a TP1 event splits the stretch and
    lowers the quantity to the remainder; an EXIT closes it; a position still open at the
    end runs to `window_end`. Zero-length stretches are dropped.
    """
    segments: list[OpenSegment] = []
    cursor: datetime | None = None
    quantity: Decimal | None = None
    if start_state.phase == PHASE_OPEN and start_state.remaining_quantity is not None:
        cursor = window_start
        quantity = start_state.remaining_quantity
    for event in events:
        if event.kind == EVENT_FILL and event.quantity is not None:
            cursor, quantity = event.time_utc, event.quantity
        elif event.kind == EVENT_TP1 and event.quantity is not None:
            if cursor is not None and quantity is not None:
                if event.time_utc > cursor:
                    segments.append(OpenSegment(cursor, event.time_utc, quantity))
                cursor, quantity = event.time_utc, _sub(quantity, event.quantity)
        elif event.kind == EVENT_EXIT:
            if cursor is not None and quantity is not None and event.time_utc > cursor:
                segments.append(OpenSegment(cursor, event.time_utc, quantity))
            cursor, quantity = None, None
    if cursor is not None and quantity is not None and window_end > cursor:
        segments.append(OpenSegment(cursor, window_end, quantity))
    return segments


class _Engine:
    """One simulation run over a parsed v2 case (single use)."""

    def __init__(
        self,
        parsed: ParsedCase,
        parameter_set: ParameterSet,
        source: MinuteSource,
        risk_fn: RiskFn,
    ) -> None:
        self.parsed = parsed
        self.parameter_set = parameter_set
        self.source = source
        self.risk_fn = risk_fn
        self.cost_model = parsed.cost_model
        self.cost_rates = cost_rates_from_model(parsed.cost_model)
        self.min_stop_distance_rate, self.max_cost_to_risk = guard_rates_from_params(
            parameter_set.params
        )
        self.min_utilization = Decimal(
            str(parameter_set.params["minimum_risk_utilization_after_rounding"])
        )
        self.risk_rate = parsed.account_state.risk_rate
        self.data_start = parsed.data_start_utc
        self.data_end = parsed.data_end_utc
        self.ledger = Ledger.start(
            equity=parsed.account_state.equity,
            parameter_set_params=parameter_set.params,
            at_utc=parsed.data_start_utc,
        )
        self.active: dict[str, _Entity] = {}
        self.records: list[TradeRecord] = []
        self.bookings: list[Booking] = []
        self.no_trade_counts: dict[str, int] = {}
        self.used_gaps: list[FundingGap] = []
        self.funding_gaps = tuple(
            FundingGap(symbol=g.symbol, start_utc=g.start_utc, end_utc=g.end_utc)
            for g in parsed.allowed_gaps
            if g.series == FUNDING_SERIES
        )
        self.setup_bars: dict[str, list[Candle]] = {}
        self.setup_closes: dict[str, list[datetime]] = {}
        self.context_bars: dict[str, list[Candle]] = {}
        self.context_closes: dict[str, list[datetime]] = {}
        self.bar_at: dict[tuple[str, datetime], Candle] = {}
        self.scripted: dict[tuple[datetime, str], ScriptedPlan] = {}
        self.funding_rows: dict[str, list[FundingRow]] = {}
        self.funding_times: dict[str, list[datetime]] = {}
        self.schedule: dict[datetime, list[str]] = {}
        self._index_inputs()

    # ------------------------------------------------------------------ setup

    def _index_inputs(self) -> None:
        parsed = self.parsed
        for bar in parsed.strategy_bars:  # already sorted by (close, symbol)
            self.setup_bars.setdefault(bar.symbol, []).append(bar)
            self.setup_closes.setdefault(bar.symbol, []).append(bar.close_time_utc)
            self.bar_at[(bar.symbol, bar.close_time_utc)] = bar
            self.schedule.setdefault(bar.close_time_utc, []).append(bar.symbol)
        for bar in parsed.context_bars:
            self.context_bars.setdefault(bar.symbol, []).append(bar)
            self.context_closes.setdefault(bar.symbol, []).append(bar.close_time_utc)
        if parsed.scripted_plans is not None:
            for scripted in parsed.scripted_plans:
                self.scripted[(scripted.bar_close_utc, scripted.symbol)] = scripted
                symbols = self.schedule.setdefault(scripted.bar_close_utc, [])
                if scripted.symbol not in symbols:
                    symbols.append(scripted.symbol)
        for symbols in self.schedule.values():
            symbols.sort()
        for row in parsed.funding_rows:  # already sorted by (symbol, time)
            self.funding_rows.setdefault(row.symbol, []).append(row)
            self.funding_times.setdefault(row.symbol, []).append(row.funding_time_utc)

    # ------------------------------------------------------------------ main loop

    def run(self) -> EngineRun:
        for close in sorted(self.schedule):
            if close > self.data_end:
                break
            self._process_window(close, final=False)
            if close < self.data_start:
                continue  # warm-up close: no signal is evaluated before the data window
            self.ledger = roll_to(self.ledger, close)
            for symbol in self.schedule[close]:
                self._evaluate_signal(symbol, close)
        self._process_window(self.data_end, final=True)
        return EngineRun(output=self._output(), bookings=tuple(self.bookings), ledger=self.ledger)

    def _output(self) -> dict[str, Any]:
        ordered = sorted(
            self.records,
            key=lambda r: (r.signal_close_utc or self.data_start, r.symbol, r.trade_id),
        )
        used = sorted(set(self.used_gaps), key=lambda g: (g.symbol, g.start_utc, g.end_utc))
        scripted = self.parsed.scripted_plans is not None
        return {
            "trades": [record.to_dict() for record in ordered],
            "run_summary": {
                "no_trade_counts": dict(sorted(self.no_trade_counts.items())),
                "plan_source": PLAN_SOURCE_SCRIPTED if scripted else PLAN_SOURCE_STRATEGY,
                "allowed_gaps_used": [
                    {
                        "series": FUNDING_SERIES,
                        "symbol": gap.symbol,
                        "start_utc": gap.start_utc.isoformat(),
                        "end_utc": gap.end_utc.isoformat(),
                    }
                    for gap in used
                ],
                "simulator_semantics_version": SIMULATOR_SEMANTICS_VERSION,
            },
            "strategy_version": self.parsed.strategy_version,
            "parameter_set_hash": self.parameter_set.parameter_set_hash,
            "cost_model_hash": self.cost_model.cost_model_hash,
            "symbols": list(self.parsed.symbols),
        }

    def _count(self, label: str) -> None:
        self.no_trade_counts[label] = self.no_trade_counts.get(label, 0) + 1

    # ------------------------------------------------------------------ window

    def _process_window(self, window_end: datetime, *, final: bool) -> None:
        """Advance every active entity to `window_end`, book the events, close the finished."""
        if not self.active:
            return
        window = _Window()
        for symbol in sorted(self.active):
            entity = self.active[symbol]
            start_state = entity.state
            end_state, events = advance(
                start_state,
                source=self.source,
                start_exclusive=entity.advanced_to,
                end_inclusive=window_end,
                bar=self.bar_at.get((symbol, window_end)),
            )
            if final:
                end_state, closing = finalize_at_data_end(
                    end_state, data_end_utc=window_end, source=self.source
                )
                events = (*events, *closing)
            window.start_states[symbol] = start_state
            window.end_states[symbol] = end_state
            window.events[symbol] = events
            for event in events:
                self._push(
                    window, symbol, event.time_utc, _EVENT_RANK[event.kind], _Item(entity, event)
                )
            if start_state.phase == PHASE_OPEN:
                self._push_funding(window, symbol, entity, window_end)
        self._drain(window, window_end)
        for symbol in sorted(window.start_states):
            entity = self.active[symbol]
            entity.state = window.end_states[symbol]
            entity.advanced_to = window_end
            if entity.state.phase == PHASE_CLOSED:
                self._close_entity(symbol, entity)

    def _push(
        self, window: _Window, symbol: str, time_utc: datetime, rank: int, item: _Item
    ) -> None:
        heappush(window.heap, (time_utc, symbol, rank, next(window.sequence), item))

    def _drain(self, window: _Window, window_end: datetime) -> None:
        """Book the window's items in `(time, symbol, rank)` order, cancelling on DAILY_STOP."""
        while window.heap:
            time_utc, symbol, _rank, _seq, item = heappop(window.heap)
            if symbol in window.dropped:
                continue
            entity = item.entity
            start_state = window.start_states[symbol]
            if item.funding is not None:
                booking = Booking(
                    time_utc=item.funding.funding_time_utc,
                    symbol=symbol,
                    trade_plan_id=start_state.plan.trade_plan_id,
                    amount=item.funding.amount,
                    kind=BOOKING_FUNDING,
                )
                self._book(booking)
                entity.funding_amount = _add(entity.funding_amount, item.funding.amount)
                entity.funding_count += 1
            else:
                event = item.event
                if event is None:
                    raise ValueError("a window item needs an event or a funding payment")
                booking = booking_for_event(
                    event, state=window.end_states[symbol], cost_model=self.cost_model
                )
                if event.exit_kind == EXIT_END_OF_DATA:
                    booking = self._not_before_last_booking(booking)
                self._book(booking)
                self._update_exposure(entity, start_state, event)
                if event.kind == EVENT_FILL and start_state.phase == PHASE_RESTING:
                    self._push_funding(window, symbol, entity, window_end)
            if booking.kind not in (BOOKING_CANCEL, BOOKING_PENDING) and cancel_resting_required(
                self.ledger
            ):
                self._cancel_resting(window, booking.time_utc)

    def _not_before_last_booking(self, booking: Booking) -> Booking:
        """Date a forced END_OF_DATA close no earlier than the ledger's last booking.

        The close is priced at the last mark minute, which a trailing mark hole can place
        before bookings of other symbols already applied; the ledger needs non-decreasing
        times, and the record keeps the true exit time.
        """
        last = self.ledger.last_booking_time_utc
        if last is not None and booking.time_utc < last:
            return Booking(
                time_utc=last,
                symbol=booking.symbol,
                trade_plan_id=booking.trade_plan_id,
                amount=booking.amount,
                kind=booking.kind,
            )
        return booking

    def _book(self, booking: Booking) -> None:
        self.ledger = apply_booking(self.ledger, booking)
        self.bookings.append(booking)

    def _update_exposure(
        self, entity: _Entity, start_state: PlanState, event: LifecycleEvent
    ) -> None:
        """Keep the ledger exposure in step with the event (D-18, D035)."""
        plan_id = start_state.plan.trade_plan_id
        if event.kind == EVENT_FILL:
            if event.quantity is None:
                raise ValueError("a FILL event needs a quantity")
            entity.exposure_remaining = event.quantity
            if start_state.fill_quantity != start_state.planned_quantity:
                scaled = realized_risk_for_fill(
                    sized_realized_risk=start_state.sized_realized_risk,
                    planned_quantity=start_state.planned_quantity,
                    filled_quantity=start_state.fill_quantity,
                )
                self.ledger = remove_exposure(self.ledger, trade_plan_id=plan_id)
                self.ledger = register_exposure(
                    self.ledger,
                    trade_plan_id=plan_id,
                    symbol=start_state.symbol,
                    position_side=start_state.direction,
                    open_risk=scaled,
                )
        elif event.kind == EVENT_TP1:
            if event.quantity is None:
                raise ValueError("a TP1 event needs a quantity")
            entity.exposure_remaining = _sub(entity.exposure_remaining, event.quantity)
            self.ledger = update_exposure(
                self.ledger,
                trade_plan_id=plan_id,
                filled_quantity=start_state.fill_quantity,
                remaining_quantity=entity.exposure_remaining,
            )
        else:  # EXIT, CANCEL, PENDING: the plan no longer carries risk
            self.ledger = remove_exposure(self.ledger, trade_plan_id=plan_id)

    def _cancel_resting(self, window: _Window, at_utc: datetime) -> None:
        """DAILY_STOP: cancel every entry still resting at `at_utc`; open stops stay (D033).

        An entity that was resting when the window began is re-advanced from its saved
        start state to `at_utc` with no strategy bar (D-05): if it is still RESTING it had
        not filled by that instant and ends DAILY_STOP_CANCEL there, and the rest of its
        window is dropped. A plan that filled, expired or was invalidated by then is
        untouched.
        """
        for symbol in sorted(window.start_states):
            start_state = window.start_states[symbol]
            if symbol in window.dropped or start_state.phase != PHASE_RESTING:
                continue
            entity = self.active[symbol]
            state_at, _ = advance(
                start_state,
                source=self.source,
                start_exclusive=entity.advanced_to,
                end_inclusive=at_utc,
                bar=None,
            )
            if state_at.phase != PHASE_RESTING:
                continue
            closed, cancel_events = cancel_plan(
                state_at, entry_kind=DAILY_STOP_CANCEL, at_utc=at_utc
            )
            for event in cancel_events:
                self._book(booking_for_event(event, state=closed, cost_model=self.cost_model))
                self._update_exposure(entity, start_state, event)
            window.end_states[symbol] = closed
            window.dropped.add(symbol)

    def _close_entity(self, symbol: str, entity: _Entity) -> None:
        """Turn a CLOSED state into its validated record and free the symbol."""
        record = build_trade_record(
            state=entity.state,
            strategy_version=self.parsed.strategy_version,
            parameter_set_hash=self.parameter_set.parameter_set_hash,
            cost_model=self.cost_model,
            funding_amount=entity.funding_amount,
            funding_event_count=entity.funding_count,
            regime=None,
            constraints_extrapolated=entity.extrapolated,
        )
        validate_trade_record(record, data_start_utc=self.data_start, data_end_utc=self.data_end)
        self.records.append(record)
        del self.active[symbol]

    # ------------------------------------------------------------------ funding

    def _push_funding(
        self, window: _Window, symbol: str, entity: _Entity, window_end: datetime
    ) -> None:
        """Queue the funding payments of the position's open stretches inside this window."""
        start_state = window.start_states[symbol]
        segments = _open_segments(
            start_state,
            window.events[symbol],
            window_start=entity.advanced_to,
            window_end=window_end,
        )
        if not segments:
            return
        result = funding_events(
            symbol=symbol,
            direction=start_state.direction,
            segments=segments,
            rows=self._funding_slice(symbol, segments[0].start_utc, segments[-1].end_utc),
            mark_source=self.source,
            allowed_gaps=self.funding_gaps,
            loaded_start_utc=self.data_start,
            loaded_end_utc=self.data_end,
        )
        for gap in result.used_allowed_gaps:
            if gap not in self.used_gaps:
                self.used_gaps.append(gap)
        for payment in result.events:
            self._push(
                window,
                symbol,
                payment.funding_time_utc,
                _RANK_FUNDING,
                _Item(entity, funding=payment),
            )

    def _funding_slice(
        self, symbol: str, start_utc: datetime, end_utc: datetime
    ) -> list[FundingRow]:
        """The funding rows the coverage rule can read for a window, plus one neighbour per side.

        The coverage check looks at `[start - G, end + G]` (G = cadence + jitter) clipped to the
        loaded range, and reports a hole with the nearest real neighbouring instants; handing
        it those rows and one row beyond each edge gives the same verdict as the full history
        without re-sorting the whole series for every window.
        """
        rows = self.funding_rows.get(symbol, [])
        times = self.funding_times.get(symbol, [])
        tolerance = FUNDING_MAX_CADENCE + FUNDING_JITTER
        low = max(start_utc - tolerance, self.data_start)
        high = min(end_utc + tolerance, self.data_end)
        first = max(bisect_left(times, low) - 1, 0)
        last = min(bisect_right(times, high) + 1, len(rows))
        return rows[first:last]

    # ------------------------------------------------------------------ signals

    def _evaluate_signal(self, symbol: str, close: datetime) -> None:
        """Evaluate the setup of `symbol` closing at `close` against the updated ledger."""
        if self.parsed.scripted_plans is not None:
            self._evaluate_scripted(symbol, close)
        elif (symbol, close) in self.bar_at:
            self._evaluate_strategy(symbol, close)

    def _evaluate_scripted(self, symbol: str, close: datetime) -> None:
        scripted = self.scripted.get((close, symbol))
        if scripted is None:
            return
        if not equity_positive(self.ledger):
            self._count(_UNCERTAIN_ACCOUNT_STATE)  # exhausted equity: fail closed (AGENTS)
            return
        if symbol in self.active:
            self._count(NO_TRADE_CONFLICT)
            return
        self._size_and_register(
            symbol, close, scripted.plan, scripted.direction, scripted.signal_id
        )

    def _evaluate_strategy(self, symbol: str, close: datetime) -> None:
        if not equity_positive(self.ledger):
            self._count(_UNCERTAIN_ACCOUNT_STATE)  # exhausted equity: fail closed (AGENTS)
            return
        account = AccountState(equity=self.ledger.equity, risk_rate=self.risk_rate)
        setup = self._setup_window(symbol, close)
        snapshot = MarketSnapshot(
            symbol=symbol,
            setup_candles=setup,
            context_candles=self._context_window(symbol, close),
            source_timeframe=_SOURCE_TIMEFRAME,
        )
        result = evaluate(
            snapshot=snapshot,
            account_state=account,
            strategy_version=self.parsed.strategy_version,
            parameter_set=self.parameter_set,
        )
        signal = result.signal
        if result.is_no_trade or signal is None:
            self._count(result.reason_code)
            return
        if symbol in self.active:
            self._count(NO_TRADE_CONFLICT)
            return
        planned = build_trade_plan(
            signal=signal,
            setup_candles=setup,
            parameter_set=self.parameter_set,
            account_state=account,
            created_at_utc=close,
        )
        if planned.is_no_trade or planned.trade_plan is None:
            self._reject(
                symbol, signal.direction, signal.signal_id, None, planned.reason_code, close
            )
            return
        self._size_and_register(
            symbol, close, planned.trade_plan, signal.direction, signal.signal_id
        )

    def _setup_window(self, symbol: str, close: datetime) -> list[Candle]:
        """The trailing STRATEGY_WINDOW_BARS setup bars ending at `close` (bisect, D-31)."""
        high = bisect_right(self.setup_closes.get(symbol, []), close)
        return self.setup_bars.get(symbol, [])[max(0, high - STRATEGY_WINDOW_BARS) : high]

    def _context_window(self, symbol: str, close: datetime) -> list[Candle]:
        """The trailing CONTEXT_WINDOW_BARS context bars closed at or before `close` (D-31)."""
        high = bisect_right(self.context_closes.get(symbol, []), close)
        return self.context_bars.get(symbol, [])[max(0, high - CONTEXT_WINDOW_BARS) : high]

    def _reject(
        self,
        symbol: str,
        direction: str,
        signal_id: str | None,
        trade_plan_id: str | None,
        reason_code: str,
        close: datetime,
        *,
        modeled_costs_per_unit: Decimal | None = None,
        extrapolated: bool = False,
    ) -> None:
        self.records.append(
            build_reject_record(
                signal_id=signal_id,
                trade_plan_id=trade_plan_id,
                symbol=symbol,
                direction=direction,
                reason_code=reason_code,
                bar_close_utc=close,
                strategy_version=self.parsed.strategy_version,
                parameter_set_hash=self.parameter_set.parameter_set_hash,
                modeled_costs_per_unit=modeled_costs_per_unit,
                constraints_extrapolated=extrapolated,
            )
        )

    def _size_and_register(
        self,
        symbol: str,
        close: datetime,
        trade_plan: TradePlan,
        direction: str,
        signal_id: str,
    ) -> None:
        """Gate a plan through `risk_fn` on the ledger and, on a pass, let it rest (D-17, D-18)."""
        pit: PitConstraint = select_constraints(
            self.parsed.constraints, symbol=symbol, bar_close_utc=close
        )
        verdict = self.risk_fn(
            trade_plan=trade_plan,
            candidate_position_side=direction,
            account_state=AccountState(equity=self.ledger.equity, risk_rate=self.risk_rate),
            constraint_snapshot=pit.snapshot,
            open_positions=open_positions_for_risk(self.ledger),
            daily_loss_quote=daily_loss_quote(self.ledger),
            now_utc=close,
            ttl=timedelta(0),
            cost_rates=self.cost_rates,
            min_stop_distance_rate=self.min_stop_distance_rate,
            max_cost_to_risk=self.max_cost_to_risk,
            minimum_risk_utilization_after_rounding=self.min_utilization,
            parameter_set=self.ledger.thresholds,
        )
        plan_id = trade_plan.trade_plan_id
        sized = verdict.sized
        if verdict.is_no_trade or sized is None or sized.quantity is None:
            self._reject(
                symbol,
                direction,
                signal_id,
                plan_id,
                verdict.reason_code,
                close,
                extrapolated=pit.extrapolated,
            )
            return
        planned_quantity = sized.quantity
        step = pit.snapshot.quantity_step_size
        fill_quantity = _floor_to_step(
            _mul(planned_quantity, self.cost_model.partial_fill_fraction), step
        )
        if fill_quantity <= _ZERO:
            self._reject(
                symbol,
                direction,
                signal_id,
                plan_id,
                _MIN_QTY_REJECT,
                close,
                modeled_costs_per_unit=sized.modeled_costs_per_unit,
                extrapolated=pit.extrapolated,
            )
            return
        levels = protective_levels_for_fill(
            plan=trade_plan,
            direction=direction,
            filled_quantity=fill_quantity,
            constraint_snapshot=pit.snapshot,
        )
        if isinstance(levels, ProtectiveReject):
            self._reject(
                symbol,
                direction,
                signal_id,
                plan_id,
                levels.reason_code,
                close,
                modeled_costs_per_unit=sized.modeled_costs_per_unit,
                extrapolated=pit.extrapolated,
            )
            return
        state = new_plan_state(
            plan=trade_plan,
            symbol=symbol,
            direction=direction,
            signal_close_utc=close,
            price_tick_size=pit.snapshot.price_tick_size,
            planned_quantity=planned_quantity,
            sized_realized_risk=sized.realized_risk,
            fill_quantity=fill_quantity,
            levels=levels,
        )
        self.ledger = register_exposure(
            self.ledger,
            trade_plan_id=plan_id,
            symbol=symbol,
            position_side=direction,
            open_risk=sized.realized_risk,
        )
        self.active[symbol] = _Entity(state=state, advanced_to=close, extrapolated=pit.extrapolated)


def simulate_detailed(
    case_input: dict[str, Any],
    *,
    risk_fn: RiskFn,
    minute_source: MinuteSource | None = None,
) -> EngineRun:
    """Run the v2 engine and return the output together with the ledger bookings.

    Same contract as `simulate`; the extra `bookings` and final `ledger` let a test prove
    that funding and exits reached the ledger at their own times (D-14, D-18).
    """
    parsed = parse_case_input(case_input)
    source = minute_source if minute_source is not None else parsed.minute_source
    if source is None:
        raise ValueError(
            "no minute data: the case has no trade_bars_1m / mark_bars_1m rows and no "
            "minute_source was passed"
        )
    parameter_set = load_parameter_set(parsed.strategy_id, parsed.parameter_set_id)
    # CR-10: the case's strategy_version must match the registry's, otherwise the identity
    # would attest to a combination that was never versioned together.
    if parameter_set.strategy_version != parsed.strategy_version:
        raise ValueError(
            f"case strategy_version={parsed.strategy_version!r} != registry "
            f"strategy_version={parameter_set.strategy_version!r} for "
            f"{parsed.strategy_id}/{parsed.parameter_set_id}"
        )
    assert_sizing_costs_bind_registry(parameter_set, parsed.cost_model)
    return _Engine(parsed, parameter_set, source, risk_fn).run()


def simulate(
    case_input: dict[str, Any],
    *,
    risk_fn: RiskFn,
    minute_source: MinuteSource | None = None,
) -> dict[str, Any]:
    """Run the v2 engine on a case-input v2 dict and return the output dict.

    The output carries `trades` (`TradeRecord.to_dict()` in the deterministic order signal
    bar close, symbol, trade id), `run_summary` (`no_trade_counts`, `plan_source`,
    `allowed_gaps_used`, `simulator_semantics_version`), `strategy_version`,
    `parameter_set_hash`, `cost_model_hash` and `symbols`.
    """
    return simulate_detailed(case_input, risk_fn=risk_fn, minute_source=minute_source).output


__all__ = ["EngineRun", "RiskFn", "simulate", "simulate_detailed"]
