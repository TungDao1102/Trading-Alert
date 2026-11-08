"""SHADOW paper ledger over the Phase 14 simulated ledger (Phase 16, plan 16-23, D-17, REV-07).

The paper loop never had a ledger (G4-010, D052 item i): every risk verdict saw an empty account.
`ShadowLedger` gives the SHADOW loop the state the backtest sizes against, so a multi-signal
history is sized against simulated positions and the simulated daily loss exactly as the engine
sizes it. It CALLS `src.backtest.ledger` (`Ledger.start`, `apply_booking`, `roll_to`,
`register_exposure`, `update_exposure`, `remove_exposure`, `open_positions_for_risk`,
`daily_loss_quote`) and the portfolio gates of `src.risk.portfolio.check_portfolio`; it copies
no rule of either, and `src/backtest` and `src/risk` are unchanged.

Equity rule (REV-07, D063 item 5): the initial equity is a required keyword input with no default
and this module holds no numeric equity literal. Paper initial equity equals the exact intended
initial live equity and is never chosen to reduce quantization rejections or to raise the trade
count; the value is set by the user in plan 16-34, never here.

Exposure timing is the user's Q-C decision (`decisions/16-DEC-Q-C.md`, `reserve-at-confirm`):
a plan reserves exposure only when a valid CONFIRM is accepted AND its SHADOW_CONFIRMED journal
write succeeded; never at signal and never at APPROVE. The accepted consequence is that SHADOW
risk verdicts can differ from the backtest while a plan waits. The reservation lasts until the
plan's own `expiry_utc` (inclusive boundary, as the confirm gate); there is no reservation TTL and
`SHADOW_CONFIRM_EXPIRED` (the 60 s confirm card TTL) is a different thing that never touches it.

Design of the CONFIRM path (design A, chosen over a tentative reserve): `ShadowReservations.check`
runs the full capacity check (plan validity, Q-B fill window, same-symbol conflict and the
cluster, aggregate and position-count gates of `check_portfolio` on the CURRENT ledger) BEFORE
`SHADOW_CONFIRMED` is journaled; `reserve` runs after the journal write succeeded. Both run
inside one serialized section (`ShadowReservations.section()`, held by `ConfirmBook.handle_confirm`
around recheck, journal and reserve), so no other CONFIRM can interleave and `reserve` repeats the
same pure check on the same state and cannot refuse. A refusal there (a foreign writer, a bug) is
journaled as `SHADOW_RESERVATION_REFUSED` and the CONFIRM is reported as not successful; it never
leaves a reservation. A failed check or a failed journal write reserves nothing.

Recovery is from the journal only (Q-J `journal-only`, no second state store). The journal events
that carry the lifecycle of one approval, all under the correlation `shadow-confirm:<approval_id>`
and joined by `plan_hash`:

- `SHADOW_CONFIRMED` (existing, written by `ConfirmBook` BEFORE the `on_confirmed` callback): the
  source of truth for a confirmed plan. Its payload carries the `reservation` facts (symbol,
  direction, sized realized risk, planned quantity, signal close, plan expiry, confirm instant and
  the Q-B eligibility start), so a crash between the journal write and the reserve still rebuilds
  the reservation.
- `SHADOW_POSITION_OPENED` (new): the plan filled; the reservation became a position.
- `SHADOW_PLAN_EXPIRED_UNFILLED` (new, reason `PLAN_EXPIRED_UNFILLED`): the plan reached its expiry
  without a fill; the reservation is released exactly once.
- `SHADOW_RESERVATION_REFUSED` (new): the reserve step refused after the CONFIRM was journaled, or
  the fill driver could not open the confirmed plan (`refuse`, plan 16-58; the reason is the
  driver reject code).

No existing event can express the end of a confirmed-but-unfilled plan, so these three are added
to the existing journal (`journal_events.event_type` is a free String(64); no migration, no table).
None is in `TERMINAL_CONFIRM_EVENTS` (they are not confirm outcomes), none is a `confirm_event` of
`attribute_shadow_outcome`, and their ids and payloads are pure functions of stable data (plan
hash, plan expiry, approval id; never a restart wall clock), so a repeated recovery writes the
same event id with the same content and the journal treats it as a replay.

Pure and deterministic: stdlib, Decimal, the Phase 14 ledger and the pure risk gates only; no
clock (every instant is an argument), no float.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol

from src.backtest.ledger import (
    Ledger,
    apply_booking,
    daily_loss_quote,
    equity_positive,
    open_positions_for_risk,
    register_exposure,
    remove_exposure,
    roll_to,
    update_exposure,
)
from src.backtest.lifecycle import (
    EVENT_EXIT,
    EVENT_FILL,
    EVENT_TP1,
    LifecycleEvent,
    PlanState,
)
from src.backtest.records import Booking
from src.backtest.semantics import NO_TRADE_CONFLICT
from src.backtest.series import MinuteSource
from src.core._decimal import _sub
from src.domain.approval import Approval
from src.domain.enums import QuantizationDecision, RejectionReason
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper.shadow_fill import (
    FundingHistory,
    ShadowFillDriver,
    eligibility_start_for,
)
from src.risk.portfolio import check_portfolio
from src.risk.realized_risk import realized_risk_for_fill
from src.risk.types import OpenPosition, SizedResult

_OK: Final = "OK"
_ZERO: Final = Decimal("0")

# Event types of the reservation lifecycle. `EVENT_SHADOW_CONFIRMED` is the existing confirm event
# of `src/paper/shadow_confirm.py`, compared by value so this module does not import the
# Telegram-facing module (a test pins the literal to its source).
EVENT_SHADOW_CONFIRMED: Final = "SHADOW_CONFIRMED"
EVENT_SHADOW_POSITION_OPENED: Final = "SHADOW_POSITION_OPENED"
EVENT_SHADOW_PLAN_EXPIRED_UNFILLED: Final = "SHADOW_PLAN_EXPIRED_UNFILLED"
EVENT_SHADOW_RESERVATION_REFUSED: Final = "SHADOW_RESERVATION_REFUSED"
RESERVATION_EVENTS: Final = (
    EVENT_SHADOW_POSITION_OPENED,
    EVENT_SHADOW_PLAN_EXPIRED_UNFILLED,
    EVENT_SHADOW_RESERVATION_REFUSED,
)

REASON_PLAN_EXPIRED_UNFILLED: Final = "PLAN_EXPIRED_UNFILLED"
REASON_RESERVATION_ENDED: Final = "RESERVATION_ENDED"

CORRELATION_PREFIX: Final = "shadow-confirm:"  # the correlation of `ConfirmBook._correlation`
_EVENT_ID_PREFIX: Final = "shadow-rsv"
_ENTITY_TYPE: Final = "ShadowReservation"
_STEP_OPENED: Final = "position_opened"
_STEP_TERMINAL: Final = "terminal"


class ReservationEndedError(RuntimeError):
    """A FILL arrived for a reservation that already ended (released, refused or expired).

    The poller must fail closed: booking a fill for an ended plan would register no exposure and
    fabricate an outcome (plan 16-58, B2-CR-02).
    """


def reservation_key(plan_hash: str, approval_id: str) -> str:
    """The stable identity of one confirmation: plan hash plus approval id (never a callback id)."""
    return f"{plan_hash}:{approval_id}"


@dataclass(frozen=True)
class RegisterResult:
    """Whether a plan could be registered, and the engine label when it could not."""

    registered: bool
    reason_code: str


class ShadowLedger:
    """The simulated account of the SHADOW loop (one instance per paper epoch).

    `initial_equity` is a required `Decimal` input: it has no default and no illustration value.
    `parameter_set_params` is the raw parameter-set mapping the Phase 14 ledger resolves its
    absolute thresholds from, and `started_at_utc` the UTC instant that opens day 1.

    Every method takes the instance lock (reentrant), so each is atomic; `lock` lets a caller hold
    it across a sequence (the CONFIRM section).
    """

    def __init__(
        self,
        *,
        initial_equity: Decimal,
        parameter_set_params: Mapping[str, Any],
        started_at_utc: datetime,
    ) -> None:
        self._ledger = Ledger.start(
            equity=initial_equity,
            parameter_set_params=dict(parameter_set_params),
            at_utc=started_at_utc,
        )
        # Quantity still carried per registered plan (the engine's `exposure_remaining`).
        self._remaining: dict[str, Decimal] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ views

    @property
    def lock(self) -> threading.RLock:
        """The single-writer lock of this ledger (reentrant)."""
        return self._lock

    @property
    def ledger(self) -> Ledger:
        """The current Phase 14 ledger value (immutable)."""
        return self._ledger

    @property
    def equity(self) -> Decimal:
        return self._ledger.equity

    @property
    def initial_equity(self) -> Decimal:
        return self._ledger.initial_equity

    def holds_symbol(self, symbol: str) -> bool:
        """True when a plan or position of `symbol` is registered (one active plan per symbol)."""
        with self._lock:
            return any(e.symbol == symbol for e in self._ledger.exposures)

    # ------------------------------------------------------------------ register

    def register(self, state: PlanState) -> RegisterResult:
        """Register a plan's sized realized risk, unless its symbol already holds one.

        One active plan or position per symbol (D-32): a second plan is refused with the
        engine's own label `CONFLICT_WITH_OPEN_POSITION` and nothing changes. This is the
        symbol-conflict path only; the CONFIRM path is `try_register`, which also runs the
        portfolio gates.
        """
        with self._lock:
            if self.holds_symbol(state.symbol):
                return RegisterResult(registered=False, reason_code=NO_TRADE_CONFLICT)
            self.restore(
                trade_plan_id=state.plan.trade_plan_id,
                symbol=state.symbol,
                direction=state.direction,
                sized_realized_risk=state.sized_realized_risk,
                planned_quantity=state.planned_quantity,
            )
            return RegisterResult(registered=True, reason_code=_OK)

    def restore(
        self,
        *,
        trade_plan_id: str,
        symbol: str,
        direction: str,
        sized_realized_risk: Decimal,
        planned_quantity: Decimal,
    ) -> None:
        """Register an exposure with no admission check (an admitted reservation, or a recovery)."""
        with self._lock:
            self._ledger = register_exposure(
                self._ledger,
                trade_plan_id=trade_plan_id,
                symbol=symbol,
                position_side=direction,
                open_risk=sized_realized_risk,
            )
            self._remaining[trade_plan_id] = planned_quantity

    def release(self, trade_plan_id: str) -> None:
        """Drop a plan's exposure (an unfilled plan that reached its expiry).

        Idempotent: an exposure the lifecycle already dropped (the plan was cancelled or expired
        inside the simulated minutes before the expiry sweep ran, plan 16-31) is not an error.
        """
        with self._lock:
            self._drop(trade_plan_id)

    def _drop(self, trade_plan_id: str) -> None:
        """Remove a plan's exposure when it is still registered (caller holds the lock)."""
        if any(e.trade_plan_id == trade_plan_id for e in self._ledger.exposures):
            self._ledger = remove_exposure(self._ledger, trade_plan_id=trade_plan_id)
        self._remaining.pop(trade_plan_id, None)

    def _view_at(self, at_utc: datetime) -> Ledger:
        """The ledger as of `at_utc`, rolled to that UTC day on a COPY (plan 16-58, B2-WR-01).

        A CONFIRM or a risk-input read is judged on the day it happens, but it must not move the
        stored ledger: bookings of the minutes still to be applied (a 23:59 exit processed after
        00:00) would then fail with "cannot roll the ledger backwards". The stored ledger moves
        only through bookings. A time inside or before the stored day judges the stored ledger
        as it is: the roll only goes forward, so a late-adopted CONFIRM instant cannot raise.
        """
        _require_utc(at_utc, "at_utc")
        day_start = at_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        if day_start <= self._ledger.day_start_utc:
            return self._ledger
        return roll_to(self._ledger, at_utc)

    def admit(
        self,
        *,
        symbol: str,
        direction: str,
        sized_realized_risk: Decimal,
        planned_quantity: Decimal,
        now_utc: datetime,
    ) -> str | None:
        """None when the candidate fits the CURRENT ledger, else the rejection reason code.

        Order: exhausted equity, the same-symbol conflict (engine label), then the unchanged
        portfolio gates of `check_portfolio` (cluster cap, aggregate cap, position count, daily
        stop) over `risk_inputs`, i.e. over open positions AND still-valid reservations. The
        constraint freshness gate was decided on the signal bar; here the snapshot is "observed
        now". Read-only: the UTC day is rolled on a copy (`_view_at`), never stored.
        """
        with self._lock:
            judged = self._view_at(now_utc)
            if not equity_positive(judged):
                return RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
            if self.holds_symbol(symbol):
                return NO_TRADE_CONFLICT
            sized = SizedResult(
                is_no_trade=False,
                quantity=planned_quantity,
                quantity_before_rounding=planned_quantity,
                quantity_after_rounding=planned_quantity,
                quantization_decision=QuantizationDecision.ACCEPTED.value,
                realized_risk=sized_realized_risk,
            )
            verdict = check_portfolio(
                sized=sized,
                candidate_symbol=symbol,
                candidate_position_side=direction,
                open_positions=open_positions_for_risk(judged),
                daily_loss_quote=daily_loss_quote(judged),
                parameter_set=judged.thresholds,
                now_utc=now_utc,
                ttl=timedelta(0),
                constraint_observed_at_utc=now_utc,
            )
            return verdict.reason_code if verdict.is_no_trade else None

    def try_register(
        self,
        *,
        trade_plan_id: str,
        symbol: str,
        direction: str,
        sized_realized_risk: Decimal,
        planned_quantity: Decimal,
        now_utc: datetime,
    ) -> RegisterResult:
        """Admit then register as one atomic step (capacity check inside the reserve path)."""
        with self._lock:
            reason = self.admit(
                symbol=symbol,
                direction=direction,
                sized_realized_risk=sized_realized_risk,
                planned_quantity=planned_quantity,
                now_utc=now_utc,
            )
            if reason is not None:
                return RegisterResult(registered=False, reason_code=reason)
            self.restore(
                trade_plan_id=trade_plan_id,
                symbol=symbol,
                direction=direction,
                sized_realized_risk=sized_realized_risk,
                planned_quantity=planned_quantity,
            )
            return RegisterResult(registered=True, reason_code=_OK)

    # ------------------------------------------------------------------ bookings and events

    def apply(self, booking: Booking) -> None:
        """Book one dated amount (non-decreasing time order, as the Phase 14 ledger requires)."""
        with self._lock:
            self._ledger = apply_booking(self._ledger, booking)

    def apply_event(self, event: LifecycleEvent, *, start_state: PlanState) -> None:
        """Keep the exposure in step with a lifecycle event, as the engine does (D-18, D035).

        `start_state` is the plan state before the event (any later state of the same plan works:
        only its invariant fields are read). A FILL of a reduced quantity re-registers the
        exposure with the risk scaled to the filled share (one exposure per plan, never two); a
        TP1 scales it to the remaining quantity; EXIT, CANCEL and PENDING release it.
        """
        plan_id = start_state.plan.trade_plan_id
        with self._lock:
            if event.kind == EVENT_FILL:
                if event.quantity is None:
                    raise ValueError("a FILL event needs a quantity")
                self._remaining[plan_id] = event.quantity
                if start_state.fill_quantity != start_state.planned_quantity:
                    scaled = realized_risk_for_fill(
                        sized_realized_risk=start_state.sized_realized_risk,
                        planned_quantity=start_state.planned_quantity,
                        filled_quantity=start_state.fill_quantity,
                    )
                    self._ledger = remove_exposure(self._ledger, trade_plan_id=plan_id)
                    self._ledger = register_exposure(
                        self._ledger,
                        trade_plan_id=plan_id,
                        symbol=start_state.symbol,
                        position_side=start_state.direction,
                        open_risk=scaled,
                    )
            elif event.kind == EVENT_TP1:
                if event.quantity is None:
                    raise ValueError("a TP1 event needs a quantity")
                remaining = _sub(self._remaining[plan_id], event.quantity)
                self._remaining[plan_id] = remaining
                self._ledger = update_exposure(
                    self._ledger,
                    trade_plan_id=plan_id,
                    filled_quantity=start_state.fill_quantity,
                    remaining_quantity=remaining,
                )
            elif event.kind == EVENT_EXIT:
                # A filled position must still carry its exposure when it exits.
                self._ledger = remove_exposure(self._ledger, trade_plan_id=plan_id)
                self._remaining.pop(plan_id, None)
            else:
                # CANCEL, PENDING: an unfilled plan no longer carries risk. The expiry sweep may
                # have released its reservation first (plan 16-31), so this is idempotent.
                self._drop(plan_id)

    # ------------------------------------------------------------------ risk inputs

    def risk_inputs(self, now_utc: datetime) -> tuple[list[OpenPosition], Decimal]:
        """`(open_positions, daily_loss_quote)` for the next risk verdict at `now_utc`.

        The positions are the full current exposure: open positions AND confirmed-but-unfilled
        reservations that are still valid (an expired or refused one has been released). Reads the
        ledger rolled to the UTC day of `now_utc`, as the engine does before it evaluates a signal
        (day PnL resets, thresholds re-resolve against the day-start equity). The roll is made on
        a copy and never stored (plan 16-58, B2-WR-01): the stored ledger moves only through
        bookings.
        """
        with self._lock:
            view = self._view_at(now_utc)
            return open_positions_for_risk(view), daily_loss_quote(view)

    def equity_and_thresholds(self, now_utc: datetime) -> tuple[Decimal, dict[str, Any]]:
        """`(equity, absolute thresholds)` the next risk verdict at `now_utc` sizes and gates with.

        What the engine reads after `roll_to(close)`: the CURRENT ledger equity for sizing
        (`ledger.equity`) and the absolute portfolio thresholds re-resolved against the UTC
        day-start equity (`ledger.thresholds`; 16-DEC-EQUITY-BASE). Both come from one `_view_at`
        under the ledger lock, so they are a consistent pair. The roll is made on a copy and
        never stored: the stored ledger moves only through bookings.
        """
        with self._lock:
            view = self._view_at(now_utc)
            return view.equity, dict(view.thresholds)


# --------------------------------------------------------------------------- #
# Reservation lifecycle (Q-C reserve-at-confirm).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReservationBasis:
    """What the risk verdict of the signal bar decided: the sized risk and the planned quantity."""

    sized_realized_risk: Decimal
    planned_quantity: Decimal


BasisFn = Callable[[Signal, TradePlan], ReservationBasis | None]


@dataclass(frozen=True)
class Reservation:
    """One confirmed plan's reservation, exactly as journaled on SHADOW_CONFIRMED."""

    approval_id: str
    short_id: str
    trade_plan_id: str
    signal_id: str
    plan_hash: str
    symbol: str
    direction: str
    sized_realized_risk: Decimal
    planned_quantity: Decimal
    signal_close_utc: datetime
    plan_expiry_utc: datetime
    confirmed_at_utc: datetime
    eligibility_start_utc: datetime

    @property
    def key(self) -> str:
        return reservation_key(self.plan_hash, self.approval_id)

    def to_payload(self) -> dict[str, str]:
        return {
            "approval_id": self.approval_id,
            "short_id": self.short_id,
            "trade_plan_id": self.trade_plan_id,
            "signal_id": self.signal_id,
            "plan_hash": self.plan_hash,
            "symbol": self.symbol,
            "direction": self.direction,
            "sized_realized_risk": str(self.sized_realized_risk),
            "planned_quantity": str(self.planned_quantity),
            "signal_close_utc": self.signal_close_utc.isoformat(),
            "plan_expiry_utc": self.plan_expiry_utc.isoformat(),
            "confirmed_at_utc": self.confirmed_at_utc.isoformat(),
            "eligibility_start_utc": self.eligibility_start_utc.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Reservation:
        """Parse a journaled reservation (raises `ValueError` on a missing or malformed field)."""
        try:
            return cls(
                approval_id=str(payload["approval_id"]),
                short_id=str(payload["short_id"]),
                trade_plan_id=str(payload["trade_plan_id"]),
                signal_id=str(payload["signal_id"]),
                plan_hash=str(payload["plan_hash"]),
                symbol=str(payload["symbol"]),
                direction=str(payload["direction"]),
                sized_realized_risk=Decimal(str(payload["sized_realized_risk"])),
                planned_quantity=Decimal(str(payload["planned_quantity"])),
                signal_close_utc=datetime.fromisoformat(str(payload["signal_close_utc"])),
                plan_expiry_utc=datetime.fromisoformat(str(payload["plan_expiry_utc"])),
                confirmed_at_utc=datetime.fromisoformat(str(payload["confirmed_at_utc"])),
                eligibility_start_utc=datetime.fromisoformat(str(payload["eligibility_start_utc"])),
            )
        except (KeyError, ArithmeticError, TypeError) as exc:
            raise ValueError(f"malformed reservation payload: {exc!r}") from exc


@dataclass(frozen=True)
class ReserveResult:
    """What `reserve` did. `duplicate` is True when the same confirmation was already held."""

    reserved: bool
    reason_code: str
    duplicate: bool = False


@dataclass(frozen=True)
class PositionRecord:
    """A journaled SHADOW_POSITION_OPENED joined with its reservation (input of the replay)."""

    reservation: Reservation
    fill_quantity: Decimal
    opened_at_utc: datetime


DriverFn = Callable[[PositionRecord], ShadowFillDriver]
FundingFn = Callable[[Reservation], FundingHistory | None]


@dataclass(frozen=True)
class RebuildReport:
    """What `rebuild_from_records` restored and what it left alone (approval ids, sorted)."""

    restored_reservations: tuple[str, ...]
    restored_positions: tuple[str, ...]
    still_open_positions: tuple[str, ...]
    expired_unfilled: tuple[str, ...]
    already_ended: tuple[str, ...]
    conflicts: tuple[str, ...]
    coverage_notes: tuple[tuple[str, str], ...]


class ReservationStores(Protocol):
    """What the reservation layer needs from persistence: the journal writer and the readers."""

    def record_journal(self, event: JournalEvent) -> None: ...
    def list_approved_approvals(self) -> list[Approval]: ...
    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]: ...


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _payload_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _journal_event(
    *,
    event_type: str,
    approval_id: str,
    signal_id: str,
    trade_plan_id: str,
    occurred_at_utc: datetime,
    step: str,
    payload: Mapping[str, Any],
) -> JournalEvent:
    """A reservation-lifecycle event: deterministic id and payload (never a restart clock)."""
    correlation = f"{CORRELATION_PREFIX}{approval_id}"
    return JournalEvent(
        journal_event_id=correlated_event_id(
            prefix=_EVENT_ID_PREFIX,
            correlation_id=correlation,
            event_type=event_type,
            entity_id=approval_id,
            step=step,
        ),
        occurred_at_utc=occurred_at_utc,
        event_type=event_type,
        entity_type=_ENTITY_TYPE,
        entity_id=approval_id,
        correlation_id=correlation,
        signal_id=signal_id,
        trade_plan_id=trade_plan_id,
        approval_id=approval_id,
        payload_json=_payload_text(payload),
    )


def _payload_of(event: JournalEvent) -> dict[str, Any]:
    if event.payload_json == "":
        return {}
    loaded = json.loads(event.payload_json)
    return loaded if isinstance(loaded, dict) else {}


class ShadowReservations:
    """The reservation lifecycle of confirmed SHADOW plans over a `ShadowLedger` and the journal.

    One instance per paper epoch, used by the single in-process writer. `basis_for` returns the
    sizing facts of the signal bar for a plan (None fails closed).
    """

    def __init__(
        self,
        ledger: ShadowLedger,
        stores: ReservationStores,
        *,
        basis_for: BasisFn,
    ) -> None:
        self._ledger = ledger
        self._stores = stores
        self._basis_for = basis_for
        self._held: dict[str, Reservation] = {}
        self._filled: dict[str, Reservation] = {}
        self._ended: set[str] = set()
        self._seen_events: dict[str, int] = {}
        self._seen_bookings: dict[str, int] = {}

    # ---- views ---------------------------------------------------------- #

    @property
    def ledger(self) -> ShadowLedger:
        return self._ledger

    def section(self) -> AbstractContextManager[Any]:
        """The serialized section: hold it around recheck, journal write and reserve."""
        return self._ledger.lock

    def pending_reservations(self) -> tuple[Reservation, ...]:
        """Confirmed, unfilled and still valid reservations, in key order."""
        with self._ledger.lock:
            return tuple(self._held[k] for k in sorted(self._held))

    def positions(self) -> tuple[Reservation, ...]:
        """Reservations that became positions, in key order."""
        with self._ledger.lock:
            return tuple(self._filled[k] for k in sorted(self._filled))

    def active(self) -> tuple[Reservation, ...]:
        """The pending reservations then the positions, read in ONE ledger-lock acquisition.

        The coordinator takes this snapshot BEFORE it takes its own lock and builds the missing
        fill drivers from it (plan 16-58, B2-CR-01): the ledger lock is never waited for while
        the coordinator lock is held.
        """
        with self._ledger.lock:
            return (
                *(self._held[k] for k in sorted(self._held)),
                *(self._filled[k] for k in sorted(self._filled)),
            )

    # ---- the CONFIRM path ------------------------------------------------ #

    def _prepare(
        self,
        *,
        signal: Signal,
        plan: TradePlan,
        approval_id: str,
        short_id: str,
        confirmed_at_utc: datetime,
    ) -> Reservation | str:
        """The reservation of a CONFIRM at `confirmed_at_utc`, or the rejection reason code."""
        _require_utc(confirmed_at_utc, "confirmed_at_utc")
        basis = self._basis_for(signal, plan)
        if basis is None:
            return RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
        eligibility = eligibility_start_for(
            signal_close_utc=signal.source_candle_close_utc,
            plan_expiry_utc=plan.expiry_utc,
            confirm_outcome="CONFIRMED",
            confirmed_at_utc=confirmed_at_utc,
        )
        if not eligibility.is_eligible or eligibility.eligibility_start_utc is None:
            # Expired, or no readable minute left before expiry (Q-B): no useless reservation.
            return RejectionReason.APPROVAL_EXPIRED.value
        return Reservation(
            approval_id=approval_id,
            short_id=short_id,
            trade_plan_id=plan.trade_plan_id,
            signal_id=signal.signal_id,
            plan_hash=plan.plan_hash,
            symbol=signal.symbol,
            direction=signal.direction,
            sized_realized_risk=basis.sized_realized_risk,
            planned_quantity=basis.planned_quantity,
            signal_close_utc=signal.source_candle_close_utc,
            plan_expiry_utc=plan.expiry_utc,
            confirmed_at_utc=confirmed_at_utc,
            eligibility_start_utc=eligibility.eligibility_start_utc,
        )

    def check(self, signal: Signal, plan: TradePlan, now_utc: datetime) -> str | None:
        """The CONFIRM-time recheck: None when the plan may reserve now, else the reason code.

        Plan validity and the Q-B fill window, then the capacity gates on the CURRENT ledger.
        Fails closed: any error is reported as a rejection, never as a pass.
        """
        with self._ledger.lock:
            try:
                for held in (*self._held.values(), *self._filled.values()):
                    if held.plan_hash == plan.plan_hash:
                        return NO_TRADE_CONFLICT  # this plan is already confirmed
                prepared = self._prepare(
                    signal=signal,
                    plan=plan,
                    approval_id="check",
                    short_id="check",
                    confirmed_at_utc=now_utc,
                )
                if isinstance(prepared, str):
                    return prepared
                return self._ledger.admit(
                    symbol=prepared.symbol,
                    direction=prepared.direction,
                    sized_realized_risk=prepared.sized_realized_risk,
                    planned_quantity=prepared.planned_quantity,
                    now_utc=now_utc,
                )
            except Exception:  # noqa: BLE001 - fail closed: a broken recheck rejects
                return RejectionReason.UNCERTAIN_ACCOUNT_STATE.value

    def confirm_payload(
        self,
        *,
        approval: Approval,
        signal: Signal,
        plan: TradePlan,
        short_id: str,
        confirmed_at_utc: datetime,
    ) -> dict[str, Any]:
        """The `reservation` facts merged into the SHADOW_CONFIRMED payload (journal = truth)."""
        prepared = self._prepare(
            signal=signal,
            plan=plan,
            approval_id=approval.approval_id,
            short_id=short_id,
            confirmed_at_utc=confirmed_at_utc,
        )
        if isinstance(prepared, str):
            raise ValueError(f"no reservation can be journaled: {prepared}")
        return {"reservation": prepared.to_payload()}

    def reserve(
        self,
        *,
        approval: Approval,
        signal: Signal,
        plan: TradePlan,
        short_id: str,
        confirmed_at_utc: datetime,
    ) -> ReserveResult:
        """Reserve the exposure of a CONFIRM whose SHADOW_CONFIRMED write already succeeded.

        Idempotent on `plan_hash:approval_id`: the same confirmation twice reserves once. The
        capacity check is repeated here, inside the reserve path, on the same state as `check`
        (the section is serialized), so it cannot refuse in the normal flow; if it does anyway
        (or errors) nothing is reserved and SHADOW_RESERVATION_REFUSED is journaled.
        """
        with self._ledger.lock:
            key = reservation_key(plan.plan_hash, approval.approval_id)
            if key in self._held or key in self._filled:
                return ReserveResult(reserved=True, reason_code=_OK, duplicate=True)
            if key in self._ended:
                return ReserveResult(reserved=False, reason_code=REASON_RESERVATION_ENDED)
            reason: str | None
            prepared: Reservation | None = None
            try:
                outcome = self._prepare(
                    signal=signal,
                    plan=plan,
                    approval_id=approval.approval_id,
                    short_id=short_id,
                    confirmed_at_utc=confirmed_at_utc,
                )
                if isinstance(outcome, str):
                    reason = outcome
                else:
                    prepared = outcome
                    reason = self._ledger.admit(
                        symbol=outcome.symbol,
                        direction=outcome.direction,
                        sized_realized_risk=outcome.sized_realized_risk,
                        planned_quantity=outcome.planned_quantity,
                        now_utc=confirmed_at_utc,
                    )
            except Exception:  # noqa: BLE001 - fail closed: reserve nothing
                reason = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
            if reason is not None or prepared is None:
                refusal = reason or RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
                self._stores.record_journal(
                    _journal_event(
                        event_type=EVENT_SHADOW_RESERVATION_REFUSED,
                        approval_id=approval.approval_id,
                        signal_id=signal.signal_id,
                        trade_plan_id=plan.trade_plan_id,
                        occurred_at_utc=confirmed_at_utc,
                        step=_STEP_TERMINAL,
                        payload={
                            "approval_id": approval.approval_id,
                            "short_id": short_id,
                            "plan_hash": plan.plan_hash,
                            "reason": refusal,
                        },
                    )
                )
                self._ended.add(key)
                return ReserveResult(reserved=False, reason_code=refusal)
            self._ledger.restore(
                trade_plan_id=prepared.trade_plan_id,
                symbol=prepared.symbol,
                direction=prepared.direction,
                sized_realized_risk=prepared.sized_realized_risk,
                planned_quantity=prepared.planned_quantity,
            )
            self._held[key] = prepared
            return ReserveResult(reserved=True, reason_code=_OK)

    # ---- release at expiry ------------------------------------------------ #

    def _expired_event(self, reservation: Reservation) -> JournalEvent:
        # Deterministic: the occurred time is the plan expiry, never the sweep or restart clock.
        return _journal_event(
            event_type=EVENT_SHADOW_PLAN_EXPIRED_UNFILLED,
            approval_id=reservation.approval_id,
            signal_id=reservation.signal_id,
            trade_plan_id=reservation.trade_plan_id,
            occurred_at_utc=reservation.plan_expiry_utc,
            step=_STEP_TERMINAL,
            payload={
                "approval_id": reservation.approval_id,
                "plan_hash": reservation.plan_hash,
                "reason": REASON_PLAN_EXPIRED_UNFILLED,
                "plan_expiry_utc": reservation.plan_expiry_utc.isoformat(),
            },
        )

    def refuse(self, key: str, reason_code: str) -> bool:
        """Release a pending reservation that cannot rest as a simulated plan (plan 16-58).

        The fill driver refused to open it (a TP1 leg below the minimum quantity or notional, for
        example): journal SHADOW_RESERVATION_REFUSED with the reject code first, then free the
        exposure. The event id is deterministic and its time is the CONFIRM instant, never a sweep
        or restart clock, so a repeated recovery writes nothing new. Returns False when the key
        is unknown or already ended; a reservation that already became a position is an integrity
        error (`ValueError`): its SHADOW_POSITION_OPENED cannot be undone.
        """
        with self._ledger.lock:
            if key in self._ended:
                return False
            if key in self._filled:
                raise ValueError(f"reservation {key!r} already opened as a position")
            reservation = self._held.get(key)
            if reservation is None:
                return False
            self._stores.record_journal(
                _journal_event(
                    event_type=EVENT_SHADOW_RESERVATION_REFUSED,
                    approval_id=reservation.approval_id,
                    signal_id=reservation.signal_id,
                    trade_plan_id=reservation.trade_plan_id,
                    occurred_at_utc=reservation.confirmed_at_utc,
                    step=_STEP_TERMINAL,
                    payload={
                        "approval_id": reservation.approval_id,
                        "short_id": reservation.short_id,
                        "plan_hash": reservation.plan_hash,
                        "reason": reason_code,
                    },
                )
            )
            self._ledger.release(reservation.trade_plan_id)
            del self._held[key]
            self._ended.add(key)
            return True

    def release_expired(self, now_utc: datetime) -> list[str]:
        """Release every unfilled reservation whose plan reached its expiry, exactly once.

        `now_utc` is the DATA horizon the fill drivers have processed (the wall clock minus the
        minute close lag), never the raw wall clock: a fill in the last minutes before the expiry
        is only booked once its minute is settled, and releasing earlier would journal a false
        SHADOW_PLAN_EXPIRED_UNFILLED (plan 16-58, B2-CR-02).

        Journals SHADOW_PLAN_EXPIRED_UNFILLED first, then frees the exposure (a failed write
        changes nothing and is retried by the next sweep). The CONFIRM history stays for audit
        and the plan never becomes fill-eligible again. Returns the approval ids released.
        """
        _require_utc(now_utc, "now_utc")
        released: list[str] = []
        with self._ledger.lock:
            for key in sorted(self._held):
                reservation = self._held[key]
                if now_utc < reservation.plan_expiry_utc:  # inclusive boundary, as the confirm gate
                    continue
                self._stores.record_journal(self._expired_event(reservation))
                self._ledger.release(reservation.trade_plan_id)
                del self._held[key]
                self._ended.add(key)
                released.append(reservation.approval_id)
        return sorted(released)

    # ---- fill: reservation becomes the position --------------------------- #

    def record_position_opened(
        self, *, key: str, fill_quantity: Decimal, opened_at_utc: datetime
    ) -> bool:
        """Journal SHADOW_POSITION_OPENED and turn the reservation into a position.

        The exposure entry is the same one (one per plan, never counted twice). Idempotent: an
        already-opened key returns False and writes nothing. Journal first, then the state.
        """
        _require_utc(opened_at_utc, "opened_at_utc")
        with self._ledger.lock:
            if key in self._filled:
                return False
            reservation = self._held.get(key)
            if reservation is None:
                raise ValueError(f"no pending reservation {key!r} to open a position from")
            self._stores.record_journal(
                _journal_event(
                    event_type=EVENT_SHADOW_POSITION_OPENED,
                    approval_id=reservation.approval_id,
                    signal_id=reservation.signal_id,
                    trade_plan_id=reservation.trade_plan_id,
                    occurred_at_utc=opened_at_utc,
                    step=_STEP_OPENED,
                    payload={
                        **reservation.to_payload(),
                        "fill_quantity": str(fill_quantity),
                        "opened_at_utc": opened_at_utc.isoformat(),
                    },
                )
            )
            del self._held[key]
            self._filled[key] = reservation
            return True

    def _apply_new_events(self, key: str, driver: ShadowFillDriver) -> None:
        """Apply the lifecycle events of `driver` not yet applied (caller holds the lock)."""
        events = driver.events
        for index in range(self._seen_events.get(key, 0), len(events)):
            event = events[index]
            if event.kind == EVENT_FILL and key in self._ended:
                raise ReservationEndedError(
                    f"a FILL arrived for the ended reservation {key!r}: the plan was released "
                    "before its fill was processed, so no position or exposure can be booked"
                )
            if event.kind == EVENT_FILL and key in self._held:
                if event.quantity is None:
                    raise ValueError("a FILL event needs a quantity")
                self.record_position_opened(
                    key=key, fill_quantity=event.quantity, opened_at_utc=event.time_utc
                )
            self._ledger.apply_event(event, start_state=driver.state)
            self._seen_events[key] = index + 1

    def sync(self, key: str, driver: ShadowFillDriver) -> None:
        """Apply what `driver` produced since the last call: events to exposure, bookings to equity.

        A FILL event of a still-pending reservation first journals SHADOW_POSITION_OPENED, so the
        fill driver (plan 16-31) only needs this one call after each `advance_to`. Idempotent:
        already-applied events and bookings are skipped.
        """
        with self._ledger.lock:
            self._apply_new_events(key, driver)
            bookings = driver.bookings
            for index in range(self._seen_bookings.get(key, 0), len(bookings)):
                self._ledger.apply(bookings[index])
                self._seen_bookings[key] = index + 1

    def sync_many(self, drivers: Mapping[str, ShadowFillDriver]) -> None:
        """`sync` for several plans at once, with the new bookings applied in time order.

        The Phase 14 ledger needs non-decreasing booking times, and one window can hold bookings
        of several plans (one exits at 10:04 while another fills at 10:03). Events are applied
        per plan in key order; the bookings of all plans are then applied sorted by time, symbol,
        plan, index and key, exactly as `rebuild_from_records` does (plan 16-31).
        """
        with self._ledger.lock:
            pending: list[tuple[datetime, str, str, int, str, Booking]] = []
            for key in sorted(drivers):
                driver = drivers[key]
                self._apply_new_events(key, driver)
                bookings = driver.bookings
                for index in range(self._seen_bookings.get(key, 0), len(bookings)):
                    booking = bookings[index]
                    pending.append(
                        (
                            booking.time_utc,
                            booking.symbol,
                            booking.trade_plan_id,
                            index,
                            key,
                            booking,
                        )
                    )
            for _time, _symbol, _plan, _index, _key, booking in sorted(
                pending, key=lambda item: item[:5]
            ):
                self._ledger.apply(booking)
            for key, driver in drivers.items():
                self._seen_bookings[key] = max(
                    self._seen_bookings.get(key, 0), len(driver.bookings)
                )

    # ---- recovery from the journal ---------------------------------------- #

    def load_records(self) -> list[JournalEvent]:
        """The journal events of every approved approval (the input of `rebuild_from_records`)."""
        records: list[JournalEvent] = []
        for approval in sorted(self._stores.list_approved_approvals(), key=lambda a: a.approval_id):
            records.extend(
                self._stores.journal_for_correlation(f"{CORRELATION_PREFIX}{approval.approval_id}")
            )
        return records

    def rebuild_from_records(
        self,
        records: Iterable[JournalEvent],
        minute_source: MinuteSource | None,
        *,
        now_utc: datetime,
        driver_for: DriverFn | None = None,
        funding_for: FundingFn | None = None,
    ) -> RebuildReport:
        """Rebuild reservations and positions from journal events alone (Q-J, no second store).

        SHADOW_CONFIRMED is the source of truth; the other lifecycle events are joined to it by
        approval id and `plan_hash` (a mismatch is reported as a conflict and restores nothing).
        Per confirmed plan:

        - a SHADOW_POSITION_OPENED exists: the plan is a position. `driver_for` returns its opened
          fill driver; it is advanced over `minute_source` to `now_utc` (a hole is annotated in
          `coverage_note` exactly as the lifecycle does and reported, never filled), its events
          rebuild the exposure and its bookings the equity, in time order;
        - a terminal SHADOW_PLAN_EXPIRED_UNFILLED or SHADOW_RESERVATION_REFUSED exists: nothing;
        - none, and the plan expired (also while the process was offline): not restored, the
          release is recorded with the deterministic event, no late fill;
        - none, and the plan is still valid: the reservation is restored (this covers a crash
          between the SHADOW_CONFIRMED write and the reserve).

        Replaying the same records twice, or onto a rebuilt instance, creates nothing twice.
        Positions need `driver_for` (loud `ValueError` otherwise: a recovery that cannot replay
        must not guess).
        """
        _require_utc(now_utc, "now_utc")
        unique: dict[str, JournalEvent] = {}
        for event in records:
            unique.setdefault(event.journal_event_id, event)
        by_approval: dict[str, list[JournalEvent]] = defaultdict(list)
        for event in unique.values():
            if event.correlation_id.startswith(CORRELATION_PREFIX):
                by_approval[event.correlation_id.removeprefix(CORRELATION_PREFIX)].append(event)

        restored_res: list[str] = []
        restored_pos: list[str] = []
        expired: list[str] = []
        ended: list[str] = []
        conflicts: list[str] = []
        to_replay: list[PositionRecord] = []
        with self._ledger.lock:
            for approval_id in sorted(by_approval):
                group = by_approval[approval_id]
                confirmed = [e for e in group if e.event_type == EVENT_SHADOW_CONFIRMED]
                if not confirmed:
                    continue
                raw = _payload_of(confirmed[0]).get("reservation")
                if not isinstance(raw, dict):
                    continue  # a confirm journaled without a reservation (nothing to restore)
                reservation = Reservation.from_payload(raw)
                key = reservation.key
                joined = [
                    e
                    for e in group
                    if e.event_type in RESERVATION_EVENTS
                    and _payload_of(e).get("plan_hash") == reservation.plan_hash
                ]
                stray = [
                    e
                    for e in group
                    if e.event_type in RESERVATION_EVENTS
                    and _payload_of(e).get("plan_hash") != reservation.plan_hash
                ]
                if stray:
                    conflicts.append(approval_id)
                    continue
                if key in self._held or key in self._filled or key in self._ended:
                    ended.append(approval_id)
                    continue
                opened = [e for e in joined if e.event_type == EVENT_SHADOW_POSITION_OPENED]
                terminal = [
                    e
                    for e in joined
                    if e.event_type
                    in (EVENT_SHADOW_PLAN_EXPIRED_UNFILLED, EVENT_SHADOW_RESERVATION_REFUSED)
                ]
                if opened:
                    body = _payload_of(opened[0])
                    to_replay.append(
                        PositionRecord(
                            reservation=reservation,
                            fill_quantity=Decimal(str(body["fill_quantity"])),
                            opened_at_utc=datetime.fromisoformat(str(body["opened_at_utc"])),
                        )
                    )
                elif terminal:
                    self._ended.add(key)
                    ended.append(approval_id)
                elif now_utc >= reservation.plan_expiry_utc:
                    # Expired unfilled (maybe while offline): record the release, restore none.
                    self._stores.record_journal(self._expired_event(reservation))
                    self._ended.add(key)
                    expired.append(approval_id)
                else:
                    self._ledger.restore(
                        trade_plan_id=reservation.trade_plan_id,
                        symbol=reservation.symbol,
                        direction=reservation.direction,
                        sized_realized_risk=reservation.sized_realized_risk,
                        planned_quantity=reservation.planned_quantity,
                    )
                    self._held[key] = reservation
                    restored_res.append(approval_id)

            still_open, notes = self._replay_positions(
                to_replay, minute_source, now_utc, driver_for, funding_for
            )
            restored_pos = [p.reservation.approval_id for p in to_replay]
        return RebuildReport(
            restored_reservations=tuple(sorted(restored_res)),
            restored_positions=tuple(sorted(restored_pos)),
            still_open_positions=tuple(sorted(still_open)),
            expired_unfilled=tuple(sorted(expired)),
            already_ended=tuple(sorted(ended)),
            conflicts=tuple(sorted(conflicts)),
            coverage_notes=tuple(sorted(notes)),
        )

    def _replay_positions(
        self,
        positions: Sequence[PositionRecord],
        minute_source: MinuteSource | None,
        now_utc: datetime,
        driver_for: DriverFn | None,
        funding_for: FundingFn | None,
    ) -> tuple[list[str], list[tuple[str, str]]]:
        if not positions:
            return [], []
        if driver_for is None or minute_source is None:
            raise ValueError("open positions need driver_for and a minute source to be rebuilt")
        ordered = sorted(
            positions, key=lambda p: (p.reservation.confirmed_at_utc, p.reservation.key)
        )
        drivers: list[tuple[PositionRecord, ShadowFillDriver]] = []
        for record in ordered:
            driver = driver_for(record)
            funding = None if funding_for is None else funding_for(record.reservation)
            driver.advance_to(now_utc, minute_source, funding=funding)
            drivers.append((record, driver))
        still_open: list[str] = []
        notes: list[tuple[str, str]] = []
        merged: list[tuple[datetime, str, str, int, str, Booking]] = []
        for record, driver in drivers:
            reservation = record.reservation
            key = reservation.key
            self._ledger.restore(
                trade_plan_id=reservation.trade_plan_id,
                symbol=reservation.symbol,
                direction=reservation.direction,
                sized_realized_risk=reservation.sized_realized_risk,
                planned_quantity=reservation.planned_quantity,
            )
            self._filled[key] = reservation
            for event in driver.events:
                self._ledger.apply_event(event, start_state=driver.state)
            self._seen_events[key] = len(driver.events)
            self._seen_bookings[key] = len(driver.bookings)
            for index, booking in enumerate(driver.bookings):
                merged.append(
                    (booking.time_utc, booking.symbol, booking.trade_plan_id, index, key, booking)
                )
            if not driver.is_closed:
                still_open.append(reservation.approval_id)
            note = driver.state.coverage_note
            if note:
                notes.append((reservation.approval_id, note))
        # The Phase 14 ledger needs non-decreasing booking times across plans.
        for _time, _symbol, _plan, _index, _key, booking in sorted(
            merged, key=lambda item: item[:5]
        ):
            self._ledger.apply(booking)
        return still_open, notes


__all__ = [
    "EVENT_SHADOW_PLAN_EXPIRED_UNFILLED",
    "EVENT_SHADOW_POSITION_OPENED",
    "EVENT_SHADOW_RESERVATION_REFUSED",
    "RESERVATION_EVENTS",
    "PositionRecord",
    "RebuildReport",
    "RegisterResult",
    "Reservation",
    "ReservationEndedError",
    "ReservationBasis",
    "ReservationStores",
    "ReserveResult",
    "ShadowLedger",
    "ShadowReservations",
    "reservation_key",
]
