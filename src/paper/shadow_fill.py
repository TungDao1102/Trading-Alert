"""SHADOW simulated-fill driver over the Phase 14 lifecycle (Phase 16, plan 16-19, D-14, L-02).

A SHADOW plan that the operator confirmed is filled by the SAME public functions the Phase 14
simulator uses, over live 1m trade and mark minutes. Nothing here copies a fill, exit, cost or
funding rule: the driver re-expresses only the engine's per-plan sizing SEQUENCE (fill quantity,
protective levels, `new_plan_state`) and then drives `advance`, `booking_for_event`,
`funding_events` and `build_trade_record`. It never goes through the private `_Engine`, and it
does not change `src/backtest`: when the eligibility start equals the signal close the trade
record is byte-equal to the `simulate` trade for the same minutes (the tracer test). If a
simulator change ever turns out to be needed, work stops and a new decision is recorded (L-02).

When a confirmed plan becomes fill-eligible is the user's Q-B decision, recorded 2026-10-09 as
`confirm-plus-one` (`decisions/16-DEC-Q-B.md`): the instant the system recorded on the successful
SHADOW_CONFIRMED event, floored to the minute, plus exactly one minute. `eligibility_start_for`
computes it from that recorded instant only (never from card creation, APPROVE or a wall clock),
and the result is passed to `advance` as `start_exclusive`. `advance` selects minutes by CLOSE
time in `(start_exclusive, end_inclusive]` and already clamps a start to the signal close, so no
simulator change is needed: the first eligible minute is the one OPENING at floor + 1 minute,
strictly after the confirm instant, and the minute containing the confirm is never read. The
difference from the backtest (a fill from the signal close) is the human approval delay and is
intentional.

Pure and deterministic: no clock, no I/O, no float. Every instant is an argument, so a restart
that replays the same inputs reproduces the same threshold, the same fills and the same record.

A few helpers are imported from `src.backtest.engine` by name (`_floor_to_step`, `_open_segments`,
`_EVENT_RANK`, `_RANK_FUNDING`) because the simulator offers no public form of them and copying
them would let the two drift apart; the private `_Engine` class is not used.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from src.backtest.costs import CostModel
from src.backtest.engine import _EVENT_RANK, _RANK_FUNDING, _floor_to_step, _open_segments
from src.backtest.exits import ProtectiveReject, protective_levels_for_fill
from src.backtest.funding import (
    FundingCoverageError,
    FundingGap,
    FundingRow,
    funding_events,
)
from src.backtest.lifecycle import (
    PHASE_CLOSED,
    LifecycleEvent,
    PlanState,
    advance,
    new_plan_state,
)
from src.backtest.records import (
    BOOKING_FUNDING,
    Booking,
    TradeRecord,
    booking_for_event,
    build_trade_record,
)
from src.backtest.series import MinuteSource
from src.core._decimal import _add, _mul
from src.core.types import Candle
from src.paper.loop import BarOutcome
from src.risk.types import ConstraintSnapshot

_ZERO = Decimal("0")
_MINUTE = timedelta(minutes=1)
_MIN_QTY_REJECT = "MIN_QTY_REJECT"
_RISK_PASSED = "risk_passed"
# The `ConfirmOutcome.CONFIRMED` value of `src.paper.shadow` (a str-valued enum), compared by
# value so this module does not import the Telegram-facing shadow module.
_CONFIRMED = "CONFIRMED"

STATUS_ELIGIBLE = "ELIGIBLE"
STATUS_CONFIRM_NOT_SUCCESSFUL = "CONFIRM_NOT_SUCCESSFUL"
STATUS_CONFIRM_BEFORE_SIGNAL_CLOSE = "CONFIRM_BEFORE_SIGNAL_CLOSE"
STATUS_PLAN_EXPIRED = "PLAN_EXPIRED"
STATUS_NO_MINUTE_BEFORE_EXPIRY = "NO_MINUTE_BEFORE_EXPIRY"


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


@dataclass(frozen=True)
class FillEligibility:
    """When a confirmed SHADOW plan may start filling, with every instant that explains it.

    `signal_close_utc`, `approved_at_utc` (optional: the APPROVE press), `confirmed_at_utc` (the
    instant recorded on the SHADOW_CONFIRMED event) and `eligibility_start_utc` are all kept so
    the journal can record the whole chain (`to_audit_dict`). `eligibility_start_utc` is None
    unless `status` is `ELIGIBLE`: a confirm that did not succeed, a plan that expired and a
    confirm with no readable minute left before expiry start no fill simulation.
    """

    signal_close_utc: datetime
    plan_expiry_utc: datetime
    confirmed_at_utc: datetime | None
    approved_at_utc: datetime | None
    eligibility_start_utc: datetime | None
    status: str

    @property
    def is_eligible(self) -> bool:
        return self.status == STATUS_ELIGIBLE and self.eligibility_start_utc is not None

    def to_audit_dict(self) -> dict[str, str | None]:
        """Journal-able form: ISO-8601 UTC text (None when the instant does not exist)."""

        def text(value: datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        return {
            "signal_close_utc": text(self.signal_close_utc),
            "approved_at_utc": text(self.approved_at_utc),
            "confirmed_at_utc": text(self.confirmed_at_utc),
            "eligibility_start_utc": text(self.eligibility_start_utc),
            "plan_expiry_utc": text(self.plan_expiry_utc),
            "status": self.status,
        }


def eligibility_start_for(
    *,
    signal_close_utc: datetime,
    plan_expiry_utc: datetime,
    confirm_outcome: str,
    confirmed_at_utc: datetime | None,
    approved_at_utc: datetime | None = None,
) -> FillEligibility:
    """Q-B `confirm-plus-one`: the recorded CONFIRM instant floored to the minute, plus one minute.

    `confirmed_at_utc` must be the `confirmed_at_utc` the system recorded on the successful
    SHADOW_CONFIRMED event, so a restart that reads the journal reproduces the same threshold;
    this function reads no clock. The plus-one is applied exactly once. The result is the
    `start_exclusive` for `advance`: minutes are selected by close time, so the minute opening at
    the floored confirm instant (which contains the confirm, or opens exactly at it) closes at or
    before the start and is never read, and the first minute read opens at floor + 1 minute.

    No fill simulation starts (`is_eligible` is False, start None) when the CONFIRM was not a
    success (`confirm_outcome` other than CONFIRMED, or no recorded instant), when it is dated
    before the signal close, when it is at or after the plan expiry (inclusive boundary, as the
    confirm gate), or when the computed start is not before the expiry.
    """
    _require_utc(signal_close_utc, "signal_close_utc")
    _require_utc(plan_expiry_utc, "plan_expiry_utc")
    if confirmed_at_utc is not None:
        _require_utc(confirmed_at_utc, "confirmed_at_utc")
    if approved_at_utc is not None:
        _require_utc(approved_at_utc, "approved_at_utc")

    def verdict(status: str, start: datetime | None = None) -> FillEligibility:
        return FillEligibility(
            signal_close_utc=signal_close_utc,
            plan_expiry_utc=plan_expiry_utc,
            confirmed_at_utc=confirmed_at_utc,
            approved_at_utc=approved_at_utc,
            eligibility_start_utc=start,
            status=status,
        )

    if confirm_outcome != _CONFIRMED or confirmed_at_utc is None:
        return verdict(STATUS_CONFIRM_NOT_SUCCESSFUL)
    if confirmed_at_utc < signal_close_utc:
        return verdict(STATUS_CONFIRM_BEFORE_SIGNAL_CLOSE)
    if confirmed_at_utc >= plan_expiry_utc:
        return verdict(STATUS_PLAN_EXPIRED)
    start = confirmed_at_utc.replace(second=0, microsecond=0) + _MINUTE
    if start >= plan_expiry_utc:
        return verdict(STATUS_NO_MINUTE_BEFORE_EXPIRY)
    return verdict(STATUS_ELIGIBLE, start)


@dataclass(frozen=True)
class FundingHistory:
    """The funding history a position is booked against (D-14, D-36).

    `rows` are the public funding rows (`FundingRow`, see `parse_funding_row`); the loaded range
    is the stretch of time those rows cover, which `funding_events` checks against the holding
    window and fails closed on a hole that no allowed gap covers.
    """

    rows: Sequence[FundingRow]
    loaded_start_utc: datetime
    loaded_end_utc: datetime
    allowed_gaps: Sequence[FundingGap] = ()

    def __post_init__(self) -> None:
        _require_utc(self.loaded_start_utc, "loaded_start_utc")
        _require_utc(self.loaded_end_utc, "loaded_end_utc")


@dataclass(frozen=True)
class ShadowOpenResult:
    """Whether a risk-passed outcome could rest as a simulated plan, and why not if it could not."""

    opened: bool
    reason_code: str


class ShadowFillDriver:
    """One SHADOW plan from resting entry to terminal outcome (single use, one symbol).

    Construct one driver per confirmed plan with the point-in-time constraint snapshot the plan
    was sized on, `open` it with the risk-passed bar outcome and the eligibility start, then call
    `advance_to` as closed minutes arrive. `trade_record` returns the validated record once the
    plan is terminal.
    """

    def __init__(
        self,
        *,
        cost_model: CostModel,
        constraint_snapshot: ConstraintSnapshot,
        strategy_version: str,
        parameter_set_hash: str,
        constraints_extrapolated: bool,
    ) -> None:
        self._cost_model = cost_model
        self._constraints = constraint_snapshot
        self._strategy_version = strategy_version
        self._parameter_set_hash = parameter_set_hash
        self._constraints_extrapolated = constraints_extrapolated
        self._state: PlanState | None = None
        self._regime: str | None = None
        self._eligibility_start_utc: datetime | None = None
        self._eligibility: FillEligibility | None = None
        self._advanced_to: datetime | None = None
        self._bookings: list[Booking] = []
        self._events: list[LifecycleEvent] = []
        self._funding_amount = _ZERO
        self._funding_count = 0
        self._used_funding_gaps: list[FundingGap] = []

    # ------------------------------------------------------------------ open

    def open(self, outcome: BarOutcome, *, eligibility_start_utc: datetime) -> ShadowOpenResult:
        """Rest the plan of a risk-passed bar outcome, eligible for fills after the given start.

        Re-expresses the engine's sizing sequence in order: the fill quantity is the planned
        quantity times `partial_fill_fraction`, floored to the step; a zero quantity or an
        un-sizeable TP1 rejects the plan (no simulation starts); otherwise the protective levels
        and `new_plan_state` follow. Risk was already decided on the bar (`outcome.verdict`).
        """
        if self._state is not None:
            raise RuntimeError("this driver already holds a plan; use one driver per plan")
        _require_utc(eligibility_start_utc, "eligibility_start_utc")
        plan = outcome.trade_plan
        signal = outcome.signal
        verdict = outcome.verdict
        sized = verdict.sized if verdict is not None else None
        if (
            outcome.stage != _RISK_PASSED
            or plan is None
            or signal is None
            or verdict is None
            or verdict.is_no_trade
            or sized is None
            or sized.quantity is None
        ):
            raise ValueError(
                f"a SHADOW fill needs a {_RISK_PASSED} outcome with a signal, a plan and a sized "
                f"verdict, got stage {outcome.stage!r}"
            )
        close = outcome.closed_candle.close_time_utc
        planned_quantity = sized.quantity
        fill_quantity = _floor_to_step(
            _mul(planned_quantity, self._cost_model.partial_fill_fraction),
            self._constraints.quantity_step_size,
        )
        if fill_quantity <= _ZERO:
            return ShadowOpenResult(opened=False, reason_code=_MIN_QTY_REJECT)
        levels = protective_levels_for_fill(
            plan=plan,
            direction=signal.direction,
            filled_quantity=fill_quantity,
            constraint_snapshot=self._constraints,
        )
        if isinstance(levels, ProtectiveReject):
            return ShadowOpenResult(opened=False, reason_code=levels.reason_code)
        self._state = new_plan_state(
            plan=plan,
            symbol=signal.symbol,
            direction=signal.direction,
            signal_close_utc=close,
            price_tick_size=self._constraints.price_tick_size,
            planned_quantity=planned_quantity,
            sized_realized_risk=sized.realized_risk,
            fill_quantity=fill_quantity,
            levels=levels,
        )
        self._regime = outcome.regime
        self._eligibility_start_utc = eligibility_start_utc
        self._advanced_to = close
        return ShadowOpenResult(opened=True, reason_code="OK")

    def open_confirmed(self, outcome: BarOutcome, eligibility: FillEligibility) -> ShadowOpenResult:
        """`open` with the Q-B start of a successful CONFIRM; an ineligible confirm opens nothing.

        The eligibility must belong to this bar (same signal close). The audit chain (signal
        close, APPROVE, CONFIRM, computed start) stays available as `eligibility`.
        """
        if not eligibility.is_eligible or eligibility.eligibility_start_utc is None:
            raise ValueError(
                f"the confirm is not eligible to start a fill simulation: {eligibility.status}"
            )
        if eligibility.signal_close_utc != outcome.closed_candle.close_time_utc:
            raise ValueError(
                f"the eligibility is for signal close {eligibility.signal_close_utc.isoformat()}, "
                f"not for this bar closing {outcome.closed_candle.close_time_utc.isoformat()}"
            )
        result = self.open(outcome, eligibility_start_utc=eligibility.eligibility_start_utc)
        if result.opened:
            self._eligibility = eligibility
        return result

    # ------------------------------------------------------------------ advance

    def advance_to(
        self,
        now_utc: datetime,
        source: MinuteSource,
        *,
        bar: Candle | None = None,
        funding: FundingHistory | None = None,
    ) -> tuple[Booking, ...]:
        """Advance the plan over the minutes closing in `(previous window end, now_utc]`.

        Minutes closing at or before the eligibility start are never read, so no price from
        before the operator acted can create a fill. Windows partition time: a minute is
        processed in exactly one call, and a call with `now_utc` at or before the previous
        window end does nothing (a replay is a no-op). `bar` is the strategy bar closing at
        `now_utc`, or None for a window that ends mid-bar. A position that has open time inside
        the window needs `funding`; without it the call fails closed and changes nothing.

        Returns the bookings this call added, in booking order (funding first at one instant).
        """
        state, eligibility, previous = self._opened()
        _require_utc(now_utc, "now_utc")
        if now_utc <= previous:
            return ()
        end_state, events = advance(
            state,
            source=source,
            start_exclusive=max(previous, eligibility),
            end_inclusive=now_utc,
            bar=bar,
        )
        items: list[tuple[datetime, int, Booking]] = [
            (
                event.time_utc,
                _EVENT_RANK[event.kind],
                booking_for_event(event, state=end_state, cost_model=self._cost_model),
            )
            for event in events
        ]
        funding_amount = self._funding_amount
        funding_count = self._funding_count
        used_gaps = list(self._used_funding_gaps)
        segments = _open_segments(state, events, window_start=previous, window_end=now_utc)
        if segments:
            if funding is None:
                raise FundingCoverageError(
                    f"{state.symbol} has an open position in the window ending "
                    f"{now_utc.isoformat()} but no funding history was given"
                )
            result = funding_events(
                symbol=state.symbol,
                direction=state.direction,
                segments=segments,
                rows=funding.rows,
                mark_source=source,
                allowed_gaps=funding.allowed_gaps,
                loaded_start_utc=funding.loaded_start_utc,
                loaded_end_utc=funding.loaded_end_utc,
            )
            for gap in result.used_allowed_gaps:
                if gap not in used_gaps:
                    used_gaps.append(gap)
            for payment in result.events:
                items.append(
                    (
                        payment.funding_time_utc,
                        _RANK_FUNDING,
                        Booking(
                            time_utc=payment.funding_time_utc,
                            symbol=state.symbol,
                            trade_plan_id=state.plan.trade_plan_id,
                            amount=payment.amount,
                            kind=BOOKING_FUNDING,
                        ),
                    )
                )
                funding_amount = _add(funding_amount, payment.amount)
                funding_count += 1
        added = tuple(booking for _time, _rank, booking in sorted(items, key=_item_order))
        # Commit only after every step above succeeded, so a failed window changes nothing.
        self._state = end_state
        self._advanced_to = now_utc
        self._events.extend(events)
        self._bookings.extend(added)
        self._funding_amount = funding_amount
        self._funding_count = funding_count
        self._used_funding_gaps = used_gaps
        return added

    # ------------------------------------------------------------------ results

    def trade_record(self) -> TradeRecord:
        """The validated terminal record of a CLOSED plan (raises while the plan is live)."""
        state, _eligibility, _previous = self._opened()
        return build_trade_record(
            state=state,
            strategy_version=self._strategy_version,
            parameter_set_hash=self._parameter_set_hash,
            cost_model=self._cost_model,
            funding_amount=self._funding_amount,
            funding_event_count=self._funding_count,
            regime=self._regime,
            constraints_extrapolated=self._constraints_extrapolated,
        )

    @property
    def state(self) -> PlanState:
        return self._opened()[0]

    @property
    def is_opened(self) -> bool:
        return self._state is not None

    @property
    def is_closed(self) -> bool:
        return self._state is not None and self._state.phase == PHASE_CLOSED

    @property
    def bookings(self) -> tuple[Booking, ...]:
        return tuple(self._bookings)

    @property
    def events(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self._events)

    @property
    def funding_amount(self) -> Decimal:
        return self._funding_amount

    @property
    def funding_event_count(self) -> int:
        return self._funding_count

    @property
    def used_funding_gaps(self) -> tuple[FundingGap, ...]:
        return tuple(self._used_funding_gaps)

    @property
    def eligibility_start_utc(self) -> datetime:
        return self._opened()[1]

    @property
    def eligibility(self) -> FillEligibility | None:
        """The audited eligibility the plan was opened with (None when opened with a raw start)."""
        return self._eligibility

    @property
    def advanced_to_utc(self) -> datetime:
        return self._opened()[2]

    def _opened(self) -> tuple[PlanState, datetime, datetime]:
        if self._state is None or self._eligibility_start_utc is None or self._advanced_to is None:
            raise RuntimeError("no plan is open: call open() with a risk-passed outcome first")
        return self._state, self._eligibility_start_utc, self._advanced_to


def _item_order(item: tuple[datetime, int, Booking]) -> tuple[datetime, int]:
    return item[0], item[1]


__all__ = [
    "STATUS_CONFIRM_BEFORE_SIGNAL_CLOSE",
    "STATUS_CONFIRM_NOT_SUCCESSFUL",
    "STATUS_ELIGIBLE",
    "STATUS_NO_MINUTE_BEFORE_EXPIRY",
    "STATUS_PLAN_EXPIRED",
    "FillEligibility",
    "FundingHistory",
    "ShadowFillDriver",
    "ShadowOpenResult",
    "eligibility_start_for",
]
