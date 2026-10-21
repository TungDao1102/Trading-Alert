"""Fill-driven protection coordinator (Phase 19, plan 19-11; D-10, D-11, D-12, D-13, D-14).

The one protection model of V1 (owner-adopted direction, 19-NOTES.md "adopt kem cac diem tren"):
the entry rests on the exchange without a stop; on the FIRST fill with positive quantity (a
user-data stream fill or a REST probe, PARTIALLY_FILLED counts) this coordinator

* writes the STOP_LOSS intent INTENDED then SENT (its ``intended_at_utc`` is the durable
  "unprotected since" time, research F6), and
* starts the ``closePosition`` STOP_MARKET placement and the cancel of the entry remainder
  TOGETHER (D-12, research Pattern 2: ``asyncio.gather``; neither waits for the other, because
  the adapter cancel has its own bounded retry that would otherwise sit inside
  ``max_unprotected_ms``).

A position counts as protected only after a REST query of the stop answers class ACTIVE
(``is_protection_confirmed``, D-11, research F7): a NEW placement response, HTTP success or an
ALGO_UPDATE alone never moves the state. ``blocks_new_entries()`` is True while any registered
position is UNPROTECTED, CLOSE_REQUIRED or CLOSE_FAILED (RISK-04).

Plan 19-11 built the happy path (branch B0), the REST-only fill detection and the router
wiring. Plan 19-14 (this revision) adds the failure branches of 19-NOTES.md "Fill, stop and entry
remainder", verbatim as D-12 requires, and the two SEPARATE deadlines of D-13, both measured from
the first detected fill in whole milliseconds (``timedelta`` floor division, no float; reaching a
deadline means escalate):

* B5 ``B5_STOP_REJECTED``: a definitive stop rejection after a fill (``classify`` of the facts
  from ``adapter.error_facts``, category REJECTED_DEFINITIVE, for example -2021) is never resent;
  the intent is REJECTED and the plan goes CLOSE_REQUIRED.
* B1 ``B1_ENTRY_NOT_TERMINAL``: stop confirmed, entry still open ``entry_terminal_timeout_ms``
  after the first fill: the stop is kept (it is only swept after FLAT), no TP, CLOSE_REQUIRED with
  the knowingly-accepted reason journaled. This closes a position that has a good stop because an
  entry cancel was slow (owner note); a wide measured timeout is the mitigation.
* B2 ``B2_STOP_UNCONFIRMED`` / B3 ``B3_BOTH_AMBIGUOUS``: stop still unconfirmed
  ``max_unprotected_ms`` after the first fill (entry terminal: B2, entry still open: B3). Before
  the deadline the stop and the entry are queried by id every step, the entry cancel is re-issued
  every step, and a stop REST proved absent is re-placed under the same id (never blindly).
* B4 ``B4_FILL_AFTER_STOP``: a once-confirmed stop that is no longer ACTIVE while a position
  exists (decided by the position, never by the algo status class, research P6) is never
  re-placed; the rest is cancelled and the new exposure is closed by MARKET.
* Stop lost, exposure not proven (19-REVIEW WR-04, owner decision D077): a once-confirmed stop
  that is no longer ACTIVE while the position cannot be read, or reads flat while the entry can
  still fill, moves the plan to UNPROTECTED (blocking) and records ``stop_lost_at`` once, at the
  first detection. The stop is never read, re-placed or trusted again. Every later step decides
  by the position: exposure is B4, flat on two consecutive reads with a terminal entry is FLAT,
  anything else keeps UNPROTECTED. A failed read never stops the clock: ``max_unprotected_ms``
  measured from ``stop_lost_at`` escalates to CLOSE_REQUIRED (``B4_STOP_LOST_UNRESOLVED``), and
  the emergency closer reads the quantity itself (it never sends a guessed one).
* ``NO_POSITION_ON_STOP_BUT_EXPOSED``: -4509 on the stop reads the position; flat with a terminal
  entry ends FLAT, an open position goes CLOSE_REQUIRED.

CLOSE_REQUIRED (entered once per plan): SAFE_MODE(``CLOSE_REQUIRED``), a critical alert
``CLOSE_REQUIRED``, the branch code journaled on the transition, then
``emergency_closer.close_position``. A close that does not end flat moves the plan to
CLOSE_FAILED, which keeps blocking new entries and retries the close every step; FLAT needs the
entry terminal AND REST flat, after which the plan's protective legs are swept by deterministic id
(``cancel_untriggered_protectives``).

Open, recorded and NOT decided here: Q4 / Phase 18 src/WR-12 (a 418/429 pause refuses the stop,
the cancel and the close with a pre-send refusal; no exemption is added, every refused call is
journaled as not sent, the deadline keeps running and the escalation to CLOSE_REQUIRED /
CLOSE_FAILED with SAFE_MODE and a critical alert is attempted on time, but "never naked" is NOT
claimed for that window), A3 (whether a closePosition stop is auto-cancelled when the position
closes, probe 6) and A2 (a GTD expiry reported as EXPIRED and terminal). An exception's message
text is never read (D-21): only its class and int code through the taxonomy.

Plan 19-16 adds the take-profit step and the exit: from PROTECTED (entry terminal, stop confirmed
by REST) the next step reads the REST position and calls ``attach_protectives_to_fill``, which
sizes TP1 and TP2 from that position, writes their intents ahead and confirms them by REST; the
plan is COMPLETE when both are confirmed. A stale but COMPLETE plan snapshot gets the live
exchangeInfo filters read here (D-20); an INCOMPLETE snapshot, an un-sizeable TP1 (no single-TP
fallback, O-03) or a rejected leg is TP_UNAVAILABLE (SAFE_MODE with ENTRY_WITHOUT_PROTECTIVE, a
critical alert ``TP_UNAVAILABLE``, the confirmed stop kept, never a flatten for that reason
alone). The legs are placed once after the entry is terminal, so TP1 is never resized by a late
fill (G2-032). From COMPLETE or TP_UNAVAILABLE, a step that reads a flat REST position goes FLAT
and sweeps the plan's legs by deterministic id. The manager hand-off is plan 19-15, the emergency
closer plan 19-12. The stop of a COMPLETE or TP_UNAVAILABLE plan is not supervised any more
(recorded open item: a stop that stops being ACTIVE while the position stays open is Phase 20/24).

Every FLAT transition (which sweeps every leg, an ACTIVE stop included) needs two consecutive zero
REST position reads, the T-8-30 rule of ``src/reconcile/sweeper.py`` (19-REVIEW CR-03): a zero
read followed by a non-zero one is journaled as ``TransientPositionGap`` and the state is kept.
The emergency closer applies the same rule before it answers flat.

19-REVIEW WR-05 (owner decision): the manager also registers an entry its Q5 path left
ENTRY_STATE_UNKNOWN (``RestingEntry.entry_state_unknown``). The coordinator never sends an entry.
It polls the entry by client order id like any AWAITING_FILL entry: an answer that is not
found=True keeps it waiting (never read as proof of absence), and the record is never dropped; a
fill it finds follows the normal fill -> stop -> cancel-remainder flow, under the SAFE_MODE the
manager entered (SAFE_MODE blocks entries only, D034). If the entry was never found by its GTD time
plus the owner grace ``protection.entry_unknown_grace_ms``, the plan moves to ENTRY_UNRESOLVED
(one journaled note): it stays tracked, still blocks nothing it did not block before, and is
queried only on every ``UNRESOLVED_ENTRY_POLL_EVERY_N_STEPS``-th step until it is found (a stream
fill is acted on at once).

Design rules:

* Step-driven. There is no internal sleep and no running loop: the caller (Phase 24, research
  Q8) calls ``await step()`` on a cadence that must be compatible with ``max_unprotected_ms``;
  that cadence is a Phase 24 number and is not decided here. Time comes from the injected
  ``clock``; every adapter, store, journal, SAFE_MODE controller, alert sink and emergency
  closer is injected.
* The intent state machine is not extended (research F6): the STOP_LOSS row uses
  INTENDED -> SENT -> ACKED / UNKNOWN. The protection state is an in-process enum journaled on
  every transition (``PROTECTION_TRANSITION``); the exchange (REST) is the truth after a restart.
  Rebuilding coordinator state after a restart is Phase 20/24 (G4-029, research P8); the state
  names are stable for Phase 20.
* A store ``PersistenceError`` never prevents the stop placement: SAFE_MODE(DB_FAILURE) once,
  later store writes are skipped, protection continues (D034, research P10). A journal failure is
  handled the same way: the audit row is lost, the protection step still runs.
* ``fill_sink`` is a synchronous, non-blocking, infallible enqueue for the router's
  ``fill_sink``. Its input is read by duck typing (``.fill``, ``.after_gap``, ``.source``); this
  module imports no adapter and no SDK. A fill the sink could not read is covered by the REST
  poll of every AWAITING_FILL entry.
* Pure core rule: stdlib, Decimal, asyncio and ``src.domain`` / ``src.execution`` /
  ``src.persistence.errors`` only; no float, no wall clock, no sleep.

O-01 stays open: this module makes the D-10 flow available but does not enable live orders; LIVE
stays blocked until the owner accepts the D055 closure draft and the Demo probes are run.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

from src.domain.algo_status import is_protection_confirmed
from src.domain.enums import ExecutionIntentStatus, LiveInputsStatus, OrderRole
from src.domain.exchange_errors import (
    CallKind,
    ExchangeErrorCategory,
    PreSendRefusal,
    classify,
)
from src.domain.journal import JournalEvent, content_hash_event_id, correlated_event_id
from src.domain.transitions import PROTECTION_INITIAL_STATE, TransitionKind, is_legal
from src.execution.constraint_snapshot import PlanConstraintSnapshot, snapshot_is_valid_for_live
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.execution.intent_store import ExecutionIntentStore
from src.execution.order_ids import derive_algo_client_id
from src.persistence.errors import IntentStateConflict, PersistenceError

POSITION_MODE_ONE_WAY = "ONE_WAY"
POSITION_MODE_HEDGE = "HEDGE"

SAFE_MODE_DB_FAILURE = "DB_FAILURE"
SAFE_MODE_CLOSE_REQUIRED = "CLOSE_REQUIRED"
SAFE_MODE_ENTRY_WITHOUT_PROTECTIVE = "ENTRY_WITHOUT_PROTECTIVE"
# Plan 20-02 (D-29, T-A): a state change the PROTECTION table refuses (fail closed).
SAFE_MODE_PROTECTION_STATE_INVALID = "PROTECTION_STATE_INVALID"
ALERT_CLOSE_REQUIRED = "CLOSE_REQUIRED"
ALERT_TP_UNAVAILABLE = "TP_UNAVAILABLE"

# The branch codes of 19-NOTES.md "Fill, stop and entry remainder" (D-12): the reason journaled on
# the transition into CLOSE_REQUIRED, the reason of the critical alert and the reason handed to the
# emergency closer.
BRANCH_B1_ENTRY_NOT_TERMINAL = "B1_ENTRY_NOT_TERMINAL"
BRANCH_B2_STOP_UNCONFIRMED = "B2_STOP_UNCONFIRMED"
BRANCH_B3_BOTH_AMBIGUOUS = "B3_BOTH_AMBIGUOUS"
BRANCH_B4_FILL_AFTER_STOP = "B4_FILL_AFTER_STOP"
BRANCH_B5_STOP_REJECTED = "B5_STOP_REJECTED"
BRANCH_NO_POSITION_BUT_EXPOSED = "NO_POSITION_ON_STOP_BUT_EXPOSED"
# 19-REVIEW WR-04 (owner, D077): a lost stop whose plan did not reach a safe state (position zero
# AND entry terminal) within max_unprotected_ms of the first detection of the loss.
BRANCH_B4_STOP_LOST_UNRESOLVED = "B4_STOP_LOST_UNRESOLVED"

EVENT_PROTECTION_TRANSITION = "PROTECTION_TRANSITION"
EVENT_PROTECTION_TRANSITION_REJECTED = "PROTECTION_TRANSITION_REJECTED"
EVENT_FILL_QUANTITY_UNKNOWN = "PROTECTION_FILL_QUANTITY_UNKNOWN"
EVENT_UNKNOWN_FILL = "PROTECTION_UNKNOWN_FILL"
EVENT_REST_FAILED = "PROTECTION_REST_FAILED"
EVENT_STOP_PLACEMENT_FAILED = "PROTECTION_STOP_PLACEMENT_FAILED"
EVENT_ENTRY_CANCEL_FAILED = "PROTECTION_ENTRY_CANCEL_FAILED"
EVENT_STEP_ERROR = "PROTECTION_STEP_ERROR"
EVENT_STOP_NOT_SENT = "STOP_NOT_SENT"
EVENT_ENTRY_CANCEL_NOT_SENT = "PROTECTION_ENTRY_CANCEL_NOT_SENT"
EVENT_CLOSE_REQUIRED = "PROTECTION_CLOSE_REQUIRED"
EVENT_CLOSE_ATTEMPT_ERROR = "PROTECTION_CLOSE_ATTEMPT_ERROR"
EVENT_SWEEP_FAILED = "PROTECTION_SWEEP_FAILED"
EVENT_TP_UNAVAILABLE = "PROTECTION_TP_UNAVAILABLE"
EVENT_ENTRY_UNRESOLVED = "PROTECTION_ENTRY_UNRESOLVED"

# 19-REVIEW WR-05 (owner): an entry the manager left ENTRY_STATE_UNKNOWN (Q5) that the coordinator
# has never found by the GTD time plus `protection.entry_unknown_grace_ms` is ENTRY_UNRESOLVED and
# is queried only on every Nth step from then on (a stream fill is still acted on at once). A code
# cadence, not an owner limit: it only thins out a REST query that keeps answering "not found".
UNRESOLVED_ENTRY_POLL_EVERY_N_STEPS = 10

# The order statuses that end an entry (research P5): FILLED, and the three "ended without
# (further) fills" statuses of the router (TERMINAL_NOT_FILLED_STATUSES).
TERMINAL_ENTRY_STATUSES: frozenset[str] = frozenset(
    {"FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}
)
FILLED_ENTRY_STATUSES: frozenset[str] = frozenset({"PARTIALLY_FILLED", "FILLED"})

_ZERO = Decimal("0")
_CORRELATION_PREFIX = "protection_"
_TRANSITION_ID_PREFIX = "ptr"
_REJECTED_ID_PREFIX = "ptx"
_NO_STATE = "NONE"

# Reasons journaled on a transition (fixed project text, never exchange text).
REASON_REGISTERED = "REGISTERED"
REASON_REGISTERED_ENTRY_STATE_UNKNOWN = "REGISTERED_ENTRY_STATE_UNKNOWN"
REASON_ENTRY_UNRESOLVED = "ENTRY_NOT_FOUND_AFTER_GTD_GRACE"
REASON_ENTRY_FOUND = "ENTRY_FOUND"
REASON_FIRST_FILL_STREAM = "FIRST_FILL_STREAM"
REASON_FIRST_FILL_REST = "FIRST_FILL_REST"
REASON_STOP_CONFIRMED_ENTRY_TERMINAL = "STOP_CONFIRMED_ENTRY_TERMINAL"
REASON_STOP_CONFIRMED_ENTRY_OPEN = "STOP_CONFIRMED_ENTRY_OPEN"
REASON_ENTRY_TERMINAL = "ENTRY_TERMINAL"
REASON_ENTRY_ENDED_NO_FILL = "ENTRY_ENDED_NO_FILL"
REASON_CLOSED_ENTRY_TERMINAL = "CLOSED_ENTRY_TERMINAL"
REASON_CLOSE_FAILED = "CLOSE_FAILED"
REASON_CLOSE_NOT_SENT = "CLOSE_NOT_SENT"
REASON_CLOSED_ENTRY_OPEN = "CLOSED_ENTRY_OPEN"
REASON_STOP_CONSUMED_FLAT = "STOP_CONSUMED_FLAT"
REASON_STOP_LOST = "STOP_LOST"
REASON_NO_POSITION_ON_STOP = "NO_POSITION_ON_STOP"
REASON_TP_LEGS_CONFIRMED = "TP_LEGS_CONFIRMED"
REASON_TP_UNAVAILABLE = "TP_UNAVAILABLE"
REASON_POSITION_CLOSED = "POSITION_CLOSED"

# Fixed project text for a position that contradicts the plan (never exchange text).
DETAIL_POSITION_SIDE_MISMATCH = "position side does not match the plan"
# The journaled error type of a zero position read that a second, fresh read did not confirm
# (T-8-30 two consecutive zero reads, the rule of src/reconcile/sweeper.py; 19-REVIEW CR-03).
ERROR_TRANSIENT_POSITION_GAP = "TransientPositionGap"


class ProtectionState(str, Enum):
    """The stable protection state names (Phase 20 reads them, research P8).

    Implemented: AWAITING_FILL -> UNPROTECTED -> PROTECTED_ENTRY_OPEN / PROTECTED,
    AWAITING_FILL -> ENTRY_ENDED_NO_FILL (plan 19-11), from UNPROTECTED or
    PROTECTED_ENTRY_OPEN, CLOSE_REQUIRED <-> CLOSE_FAILED -> FLAT (plan 19-14), and PROTECTED ->
    COMPLETE / TP_UNAVAILABLE, with COMPLETE / TP_UNAVAILABLE (and PROTECTED, when REST is flat)
    -> FLAT (plan 19-16). 19-REVIEW WR-05 (owner) adds the eleventh name ENTRY_UNRESOLVED: an
    ENTRY_STATE_UNKNOWN entry never found by its GTD time plus the grace; it leaves to
    UNPROTECTED on a fill, ENTRY_ENDED_NO_FILL when found ended, or AWAITING_FILL when found open.
    19-REVIEW WR-04 (owner, D077) adds no name: a lost stop moves PROTECTED_ENTRY_OPEN back to
    UNPROTECTED (reason ``STOP_LOST``), which leaves only to CLOSE_REQUIRED or FLAT.
    """

    AWAITING_FILL = "AWAITING_FILL"
    UNPROTECTED = "UNPROTECTED"
    PROTECTED_ENTRY_OPEN = "PROTECTED_ENTRY_OPEN"
    PROTECTED = "PROTECTED"
    COMPLETE = "COMPLETE"
    TP_UNAVAILABLE = "TP_UNAVAILABLE"
    CLOSE_REQUIRED = "CLOSE_REQUIRED"
    FLAT = "FLAT"
    CLOSE_FAILED = "CLOSE_FAILED"
    ENTRY_ENDED_NO_FILL = "ENTRY_ENDED_NO_FILL"
    ENTRY_UNRESOLVED = "ENTRY_UNRESOLVED"


# A position in one of these states is exposed without a confirmed stop (or being closed).
# ENTRY_UNRESOLVED is deliberately absent: like AWAITING_FILL it holds no known exposure, and the
# SAFE_MODE(ENTRY_STATE_UNKNOWN) the manager entered already blocks new entries (19-REVIEW WR-05).
BLOCKING_STATES: frozenset[ProtectionState] = frozenset(
    {
        ProtectionState.UNPROTECTED,
        ProtectionState.CLOSE_REQUIRED,
        ProtectionState.CLOSE_FAILED,
    }
)


# --------------------------------------------------------------------------- #
# Value objects.
# --------------------------------------------------------------------------- #


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")


def _require_positive_decimal(value: object, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite() or value <= _ZERO:
        raise ValueError(f"{name} must be a finite positive Decimal")


def _require_utc(value: object, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


@dataclass(frozen=True, kw_only=True)
class RestingEntry:
    """One resting entry the manager hands over after the entry is ACKED (plan 19-15).

    Everything the protection flow needs comes from the bound plan: the coordinator invents no
    price, side or size. ``tp1_quantity_fraction`` is carried for plan 19-16 and comes from the
    caller, never from a constant in ``src/execution`` (EXEC-07 / O-02).

    19-REVIEW WR-05 (owner): the manager also hands over an entry its Q5 path left
    ENTRY_STATE_UNKNOWN, with ``entry_state_unknown=True``. Such an entry may or may not exist on
    the exchange; ``entry_good_till_utc`` (the ``goodTillDate`` the entry was sent with, required
    for it) is when the exchange ends it, from which the owner grace
    ``protection.entry_unknown_grace_ms`` is measured.
    """

    approval_id: str
    trade_plan_id: str
    plan_hash: str
    symbol: str
    side: str
    entry_side: str
    exit_side: str
    entry_client_order_id: str
    entry_quantity: Decimal
    sl_trigger_price: Decimal
    tp1_trigger_price: Decimal
    tp2_trigger_price: Decimal
    tp1_quantity_fraction: Decimal
    working_type: str
    position_mode: str
    plan_constraint_snapshot: PlanConstraintSnapshot
    snapshot_ttl: timedelta
    registered_at_utc: datetime
    entry_state_unknown: bool = False
    entry_good_till_utc: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "approval_id",
            "trade_plan_id",
            "plan_hash",
            "symbol",
            "side",
            "entry_client_order_id",
            "working_type",
            "position_mode",
        ):
            _require_text(getattr(self, name), name)
        for name in ("entry_side", "exit_side"):
            if getattr(self, name) not in ("BUY", "SELL"):
                raise ValueError(f"{name} must be BUY or SELL")
        if self.entry_side == self.exit_side:
            raise ValueError("entry_side and exit_side must be opposite")
        for name in (
            "entry_quantity",
            "sl_trigger_price",
            "tp1_trigger_price",
            "tp2_trigger_price",
            "tp1_quantity_fraction",
        ):
            _require_positive_decimal(getattr(self, name), name)
        if self.tp1_quantity_fraction >= Decimal("1"):
            raise ValueError("tp1_quantity_fraction must be below 1")
        if not isinstance(self.plan_constraint_snapshot, PlanConstraintSnapshot):
            raise TypeError("plan_constraint_snapshot must be a PlanConstraintSnapshot")
        if self.working_type != self.plan_constraint_snapshot.working_type:
            raise ValueError("working_type must equal the plan constraint snapshot working type")
        if not isinstance(self.snapshot_ttl, timedelta) or self.snapshot_ttl <= timedelta(0):
            raise ValueError("snapshot_ttl must be a positive timedelta")
        _require_utc(self.registered_at_utc, "registered_at_utc")
        if not isinstance(self.entry_state_unknown, bool):
            raise TypeError("entry_state_unknown must be a bool")
        if self.entry_good_till_utc is not None:
            _require_utc(self.entry_good_till_utc, "entry_good_till_utc")
        elif self.entry_state_unknown:
            raise ValueError("an ENTRY_STATE_UNKNOWN entry needs entry_good_till_utc")


@dataclass(frozen=True)
class PlanProtection:
    """The read-only view of one plan's protection state."""

    plan_hash: str
    symbol: str
    state: ProtectionState
    first_fill_at_utc: datetime | None
    stop_confirmed_at_utc: datetime | None
    entry_terminal_at_utc: datetime | None
    last_reason: str | None
    # 19-REVIEW WR-04: the first detection of a once-confirmed stop that is no longer ACTIVE;
    # set once and never reset (``stop_confirmed_at_utc`` keeps the earlier confirmation).
    stop_lost_at_utc: datetime | None = None


# --------------------------------------------------------------------------- #
# Protocols (everything injected).
# --------------------------------------------------------------------------- #


class ProtectionRegistry(Protocol):
    """What the manager and the entry gate use of the coordinator (plans 19-13, 19-15)."""

    def blocks_new_entries(self) -> bool: ...

    def register_resting_entry(self, entry: RestingEntry) -> None: ...

    def protection_of(self, plan_hash: str) -> PlanProtection | None: ...


class CriticalAlertSink(Protocol):
    """Where a critical alert goes (Telegram UX is Phase 23)."""

    def critical(
        self, *, event: str, plan_hash: str, symbol: str, reason: str, now_utc: datetime
    ) -> None: ...


class EmergencyCloser(Protocol):
    """Closes a position by a reduce-only MARKET order (plan 19-12)."""

    async def close_position(self, *, entry: RestingEntry, reason: str) -> bool:
        """True only when REST shows the position flat."""
        ...


class ProtectionAdapter(Protocol):
    """The adapter methods the coordinator calls (the real adapter and the fake have them)."""

    async def place_algo_protective(self, **kwargs: Any) -> Any: ...

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any: ...

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> Any: ...

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> Any: ...

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> Any: ...

    async def snapshot_positions(self, *, symbol: str | None = None) -> Any: ...

    async def symbol_lot_filters(self, *, symbol: str) -> Any: ...

    def error_facts(self, exc: BaseException) -> Any: ...


class RoutedFillLike(Protocol):
    """What the router's ``RoutedFill`` offers; read by duck typing (no adapter import)."""

    @property
    def fill(self) -> Any: ...

    @property
    def after_gap(self) -> bool: ...

    @property
    def source(self) -> Any: ...


# --------------------------------------------------------------------------- #
# Internals.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _QueuedFill:
    """A stream fill reduced to the plain fields the coordinator reads."""

    order_id: str
    trade_id: str
    symbol: str
    side: str
    quantity: Decimal
    after_gap: bool
    source: str


class _PlaceOutcome(Enum):
    """How one stop placement ended (never protection: only REST ACTIVE is)."""

    PLACED = "PLACED"
    EXISTS = "EXISTS"
    REJECTED = "REJECTED"
    NO_POSITION = "NO_POSITION"
    NOT_SENT = "NOT_SENT"
    AMBIGUOUS = "AMBIGUOUS"


class _StopReading(Enum):
    """What one REST query of the stop answered."""

    ACTIVE = "ACTIVE"
    ABSENT = "ABSENT"
    NOT_ACTIVE = "NOT_ACTIVE"
    UNREADABLE = "UNREADABLE"


class _Tracked:
    """The mutable record of one registered plan (in-process; the exchange is the truth)."""

    def __init__(self, entry: RestingEntry) -> None:
        self.entry = entry
        self.state: ProtectionState | None = None
        self.seq = 0
        self.first_fill_at: datetime | None = None
        self.stop_confirmed_at: datetime | None = None
        # 19-REVIEW WR-04: set once when a confirmed stop is first seen lost, never reset.
        self.stop_lost_at: datetime | None = None
        self.entry_terminal_at: datetime | None = None
        self.last_reason: str | None = None
        self.entry_exchange_order_id: str | None = None
        self.stop_unknown_recorded = False
        self.close_branch: str | None = None
        self.sweep_done = False
        # 19-REVIEW WR-05: whether any REST query has ever answered found=True for the entry, and
        # the steps spent in ENTRY_UNRESOLVED (the low-frequency poll counter).
        self.entry_found = False
        self.unresolved_steps = 0

    def view(self) -> PlanProtection:
        assert self.state is not None
        return PlanProtection(
            plan_hash=self.entry.plan_hash,
            symbol=self.entry.symbol,
            state=self.state,
            first_fill_at_utc=self.first_fill_at,
            stop_confirmed_at_utc=self.stop_confirmed_at,
            entry_terminal_at_utc=self.entry_terminal_at,
            last_reason=self.last_reason,
            stop_lost_at_utc=self.stop_lost_at,
        )


def _attr(obj: Any, name: str) -> Any:
    """Read ``name`` from an attribute-style or dict-style object."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _refusal_reason(exc: BaseException) -> str:
    """The project-fixed reason of a pre-send refusal (its type name when it carries none)."""
    reason = getattr(exc, "reason", None)
    return reason if isinstance(reason, str) and reason != "" else type(exc).__name__


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


class ProtectionCoordinator:
    """Step-driven, fill-driven protection of resting entries (see the module docstring).

    Every argument is keyword-only and injected. The constructor refuses to build while any
    execution limit is NOT_CONFIGURED (D-13): ``limits.require_live_ready()`` runs before
    anything else.
    """

    def __init__(
        self,
        *,
        adapter: ProtectionAdapter,
        intent_store: ExecutionIntentStore,
        journal: Any,
        safe_mode_controller: Any,
        alert_sink: CriticalAlertSink,
        emergency_closer: EmergencyCloser,
        limits: ExecutionLimits,
        clock: Callable[[], datetime],
    ) -> None:
        limits.require_live_ready()
        max_unprotected_ms = limits.max_unprotected_ms
        entry_terminal_timeout_ms = limits.entry_terminal_timeout_ms
        entry_unknown_grace_ms = limits.entry_unknown_grace_ms
        if (
            max_unprotected_ms is None
            or entry_terminal_timeout_ms is None
            or entry_unknown_grace_ms is None
        ):
            raise ExecutionLimitsNotConfigured(
                ("max_unprotected_ms", "entry_terminal_timeout_ms", "entry_unknown_grace_ms")
            )
        self._max_unprotected_ms = max_unprotected_ms
        self._entry_terminal_timeout_ms = entry_terminal_timeout_ms
        self._entry_unknown_grace = timedelta(milliseconds=entry_unknown_grace_ms)
        self._adapter = adapter
        self._store = intent_store
        self._journal = journal
        self._safe_mode = safe_mode_controller
        self._alerts = alert_sink
        self._closer = emergency_closer
        self._limits = limits
        self._clock = clock
        self._tracked: dict[str, _Tracked] = {}
        self._fills: deque[_QueuedFill] = deque()
        self._step_lock = asyncio.Lock()
        self._store_failed = False
        self._db_failure_reported = False
        self._unknown_fills_journaled: set[tuple[str, str]] = set()
        self.fill_sink_failures = 0

    # ------------------------------------------------------------------ #
    # Registry surface.
    # ------------------------------------------------------------------ #

    def register_resting_entry(self, entry: RestingEntry) -> None:
        """Track a resting entry; the plan starts in AWAITING_FILL.

        An ``entry_state_unknown`` entry (19-REVIEW WR-05) is tracked the same way: the
        coordinator never sends an entry, waits while REST does not answer found=True (never
        reading found=False as absence), protects a fill it finds, and never forgets the record.

        Raises:
            ValueError: Hedge mode (D-14 fail closed, Hedge is unverified and not enabled in
                V1), an unknown position mode, or a plan hash that is already registered.
        """
        if not isinstance(entry, RestingEntry):
            raise TypeError("entry must be a RestingEntry")
        if entry.position_mode == POSITION_MODE_HEDGE:
            raise ValueError(
                "HEDGE position mode is not supported (D-14): refusing to register the entry"
            )
        if entry.position_mode != POSITION_MODE_ONE_WAY:
            raise ValueError(f"unknown position mode {entry.position_mode!r}")
        if entry.plan_hash in self._tracked:
            raise ValueError(f"plan {entry.plan_hash} is already registered")
        tracked = _Tracked(entry)
        self._tracked[entry.plan_hash] = tracked
        if entry.entry_state_unknown:
            reason = REASON_REGISTERED_ENTRY_STATE_UNKNOWN
        else:
            reason = REASON_REGISTERED
        self._transition(tracked, ProtectionState.AWAITING_FILL, reason, self._now())

    def blocks_new_entries(self) -> bool:
        """True while any registered position is UNPROTECTED, CLOSE_REQUIRED or CLOSE_FAILED."""
        return any(t.state in BLOCKING_STATES for t in self._tracked.values())

    def protection_of(self, plan_hash: str) -> PlanProtection | None:
        tracked = self._tracked.get(plan_hash)
        return None if tracked is None else tracked.view()

    # ------------------------------------------------------------------ #
    # The router's fill sink: synchronous, non-blocking, infallible.
    # ------------------------------------------------------------------ #

    def fill_sink(self, routed: RoutedFillLike) -> None:
        """Enqueue a routed fill for the next ``step``. Never raises, never blocks.

        A fill the sink cannot read is counted in ``fill_sink_failures``; the REST poll of every
        AWAITING_FILL entry still finds the fill (T-19-26).
        """
        try:
            fill = routed.fill
            quantity = fill.fill_quantity
            if not isinstance(quantity, Decimal) or not quantity > _ZERO:
                return
            self._fills.append(
                _QueuedFill(
                    order_id=str(fill.order_id),
                    trade_id=str(fill.exchange_trade_id),
                    symbol=str(fill.symbol),
                    side=str(fill.side),
                    quantity=quantity,
                    after_gap=bool(routed.after_gap),
                    source=str(getattr(routed.source, "value", routed.source)),
                )
            )
        except Exception:  # noqa: BLE001 - the sink must never raise into the router
            self.fill_sink_failures += 1

    # ------------------------------------------------------------------ #
    # The step.
    # ------------------------------------------------------------------ #

    async def step(self) -> None:
        """One pass over every registered plan (deterministic order, plans run concurrently).

        Queued stream fills are routed first (synchronously); then each plan advances by at most
        one phase: AWAITING_FILL -> first fill handling, UNPROTECTED / PROTECTED_ENTRY_OPEN ->
        REST confirmation. Per-plan work never raises out of ``step``.
        """
        async with self._step_lock:
            evidence = self._route_queued_fills()
            plans = sorted(
                self._tracked.values(),
                key=lambda t: (t.entry.registered_at_utc, t.entry.plan_hash),
            )
            results = await asyncio.gather(
                *(self._step_plan(t, evidence.get(t.entry.plan_hash)) for t in plans),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, Exception):
                    raise result

    def _route_queued_fills(self) -> dict[str, _QueuedFill]:
        """Attribute every queued fill to a plan; return the first-fill evidence per plan."""
        evidence: dict[str, _QueuedFill] = {}
        while self._fills:
            fill = self._fills.popleft()
            owner = self._owner_of(fill)
            if owner is None:
                self._journal_unknown_fill(fill)
                continue
            if owner.state in (ProtectionState.AWAITING_FILL, ProtectionState.ENTRY_UNRESOLVED):
                evidence.setdefault(owner.entry.plan_hash, fill)
            # A fill for a plan that is past AWAITING_FILL is a duplicate or a later fill: it
            # never places a second stop (the late-fill branch is plan 19-14).
        return evidence

    def _owner_of(self, fill: _QueuedFill) -> _Tracked | None:
        for tracked in self._tracked.values():
            if tracked.entry_exchange_order_id == fill.order_id:
                return tracked
        candidates = [
            t
            for t in self._tracked.values()
            if t.entry_exchange_order_id is None
            and t.entry.symbol == fill.symbol
            and t.entry.entry_side == fill.side
        ]
        if len(candidates) == 1:
            candidates[0].entry_exchange_order_id = fill.order_id
            return candidates[0]
        return None

    async def _step_plan(self, tracked: _Tracked, evidence: _QueuedFill | None) -> None:
        try:
            state = tracked.state
            if state is ProtectionState.AWAITING_FILL:
                if evidence is not None:
                    await self._on_first_fill(tracked, REASON_FIRST_FILL_STREAM)
                else:
                    await self._poll_entry(tracked)
                    self._mark_unknown_entry_unresolved(tracked)
            elif state is ProtectionState.ENTRY_UNRESOLVED:
                if evidence is not None:
                    await self._on_first_fill(tracked, REASON_FIRST_FILL_STREAM)
                else:
                    await self._poll_unresolved_entry(tracked)
            elif state in (ProtectionState.UNPROTECTED, ProtectionState.PROTECTED_ENTRY_OPEN):
                await self._confirm(tracked)
            elif state is ProtectionState.PROTECTED:
                await self._attach_take_profits(tracked)
            elif state in (ProtectionState.COMPLETE, ProtectionState.TP_UNAVAILABLE):
                await self._watch_exit(tracked)
            elif state in (ProtectionState.CLOSE_REQUIRED, ProtectionState.CLOSE_FAILED):
                await self._close_flow(tracked)
            elif state is ProtectionState.FLAT and not tracked.sweep_done:
                await self._sweep(tracked)
        except Exception as exc:  # noqa: BLE001 - one plan's failure must not stop the others
            self._journal_note(
                tracked,
                EVENT_STEP_ERROR,
                {"error_type": type(exc).__name__, "state": str(tracked.state)},
                self._now(),
            )

    # ------------------------------------------------------------------ #
    # First fill: intent, then the stop and the cancel together (D-10, D-12).
    # ------------------------------------------------------------------ #

    async def _on_first_fill(self, tracked: _Tracked, reason: str) -> None:
        now = self._now()
        tracked.first_fill_at = now
        self._transition(tracked, ProtectionState.UNPROTECTED, reason, now)
        self._write_stop_intent(tracked, now)
        results = await asyncio.gather(
            self._place_stop(tracked),
            self._cancel_entry_remainder(tracked),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, Exception):
                raise result
        placed = results[0]
        if isinstance(placed, _PlaceOutcome):
            await self._on_place_outcome(tracked, placed)

    async def _on_place_outcome(self, tracked: _Tracked, outcome: _PlaceOutcome) -> None:
        """React to how a stop placement ended (the stop itself is confirmed only by REST)."""
        if outcome is _PlaceOutcome.REJECTED:
            # B5 (D-12): a definitive rejection after a fill is never resent.
            entry = tracked.entry
            role = OrderRole.STOP_LOSS.value
            self._store_write(
                lambda: self._store.record_result(
                    approval_id=entry.approval_id,
                    role=role,
                    status=ExecutionIntentStatus.REJECTED,
                    exchange_order_id=None,
                    exchange_status=None,
                    now_utc=self._now(),
                )
            )
            await self._enter_close_required(tracked, BRANCH_B5_STOP_REJECTED)
        elif outcome is _PlaceOutcome.NO_POSITION:
            await self._on_no_position_on_stop(tracked)

    async def _on_no_position_on_stop(self, tracked: _Tracked) -> None:
        """-4509 on the stop: the exchange says there is no position; the position is read.

        Flat with a terminal entry ends the plan (nothing to close, the legs are swept) only when
        a second, fresh REST read is flat too (T-8-30, 19-REVIEW CR-03). Open is contradictory
        and fails closed into CLOSE_REQUIRED. Flat with an open entry, a second read that is not
        flat, or an unreadable position keeps the plan UNPROTECTED and watched: the entry cancel
        is re-issued every step and the deadline decides.
        """
        exposed = await self._position_is_open(tracked)
        if exposed is True:
            await self._enter_close_required(tracked, BRANCH_NO_POSITION_BUT_EXPOSED)
        elif exposed is False:
            entry = tracked.entry
            answer = await self._guarded(
                self._adapter.query_order_by_client(
                    symbol=entry.symbol, orig_client_order_id=entry.entry_client_order_id
                )
            )
            self._apply_entry_answer(tracked, answer)
            if tracked.entry_terminal_at is not None and await self._second_read_is_flat(tracked):
                self._transition(
                    tracked, ProtectionState.FLAT, REASON_NO_POSITION_ON_STOP, self._now()
                )
                await self._sweep(tracked)

    async def _poll_entry(self, tracked: _Tracked) -> None:
        """REST poll of an AWAITING_FILL entry: the fill source when no stream event arrived.

        A missed stream event must not leave a fill without a stop (T-19-26). Fail closed:
        PARTIALLY_FILLED / FILLED is a first fill even when the executed quantity is missing
        or zero (closePosition needs no quantity); an ended entry whose executed quantity is
        unknown is settled by the position read.
        """
        entry = tracked.entry
        answer = await self._guarded(
            self._adapter.query_order_by_client(
                symbol=entry.symbol, orig_client_order_id=entry.entry_client_order_id
            )
        )
        if isinstance(answer, BaseException):
            if not isinstance(answer, Exception):
                raise answer
            self._journal_note(
                tracked,
                EVENT_REST_FAILED,
                {"call": "query_order_by_client", "error_type": type(answer).__name__},
                self._now(),
            )
            return
        if _attr(answer, "found") is not True:
            # Not found is never proof of absence (Q5): keep waiting, keep the record.
            return
        tracked.entry_found = True
        order_id = _optional_text(_attr(answer, "order_id"))
        if order_id is not None:
            tracked.entry_exchange_order_id = order_id
        status = _optional_text(_attr(answer, "status"))
        executed = _attr(answer, "executed_quantity")
        if not isinstance(executed, Decimal):
            executed = None
        if executed is not None and executed > _ZERO:
            await self._on_first_fill(tracked, REASON_FIRST_FILL_REST)
        elif status in FILLED_ENTRY_STATUSES:
            self._note_quantity_unknown(tracked, status)
            await self._on_first_fill(tracked, REASON_FIRST_FILL_REST)
        elif status in TERMINAL_ENTRY_STATUSES:
            if executed is None:
                exposed = await self._position_is_open(tracked)
                if exposed is None:
                    return
                if exposed:
                    self._note_quantity_unknown(tracked, status)
                    await self._on_first_fill(tracked, REASON_FIRST_FILL_REST)
                    return
            now = self._now()
            tracked.entry_terminal_at = now
            self._transition(
                tracked, ProtectionState.ENTRY_ENDED_NO_FILL, REASON_ENTRY_ENDED_NO_FILL, now
            )

    def _mark_unknown_entry_unresolved(self, tracked: _Tracked) -> None:
        """ENTRY_STATE_UNKNOWN entry never found by GTD + grace: ENTRY_UNRESOLVED (19-REVIEW WR-05).

        Only an entry the manager left ENTRY_STATE_UNKNOWN qualifies, only while it is still
        AWAITING_FILL and only if no REST query ever answered found=True. Reaching the GTD time
        plus ``protection.entry_unknown_grace_ms`` (injected clock) switches it to the
        low-frequency poll. The record is kept, nothing is sent and nothing new is blocked; the
        manager's SAFE_MODE(ENTRY_STATE_UNKNOWN) stays in force (this module never leaves
        SAFE_MODE). One note is journaled on the switch.
        """
        entry = tracked.entry
        good_till = entry.entry_good_till_utc
        if (
            not entry.entry_state_unknown
            or good_till is None
            or tracked.entry_found
            or tracked.state is not ProtectionState.AWAITING_FILL
        ):
            return
        now = self._now()
        if now < good_till + self._entry_unknown_grace:
            return
        tracked.unresolved_steps = 0
        self._transition(tracked, ProtectionState.ENTRY_UNRESOLVED, REASON_ENTRY_UNRESOLVED, now)
        self._journal_note(
            tracked,
            EVENT_ENTRY_UNRESOLVED,
            {
                "entry_client_order_id": entry.entry_client_order_id,
                "entry_good_till_utc": good_till.isoformat(),
                "poll_every_n_steps": str(UNRESOLVED_ENTRY_POLL_EVERY_N_STEPS),
                "reason": REASON_ENTRY_UNRESOLVED,
            },
            now,
        )

    async def _poll_unresolved_entry(self, tracked: _Tracked) -> None:
        """ENTRY_UNRESOLVED: the REST query runs only on every Nth step (19-REVIEW WR-05).

        A found entry follows the normal flow: a fill is protected (UNPROTECTED, then the stop),
        an ended entry is ENTRY_ENDED_NO_FILL, and an entry found still open goes back to
        AWAITING_FILL and the every-step poll. Not found keeps the record unresolved.
        """
        tracked.unresolved_steps += 1
        if tracked.unresolved_steps % UNRESOLVED_ENTRY_POLL_EVERY_N_STEPS != 0:
            return
        await self._poll_entry(tracked)
        if tracked.state is ProtectionState.ENTRY_UNRESOLVED and tracked.entry_found:
            self._transition(
                tracked, ProtectionState.AWAITING_FILL, REASON_ENTRY_FOUND, self._now()
            )

    def _note_quantity_unknown(self, tracked: _Tracked, status: str | None) -> None:
        self._journal_note(
            tracked,
            EVENT_FILL_QUANTITY_UNKNOWN,
            {"status": "NONE" if status is None else status},
            self._now(),
        )

    async def _position_is_open(self, tracked: _Tracked) -> bool | None:
        """True when REST shows a non-zero position of the symbol; None when it cannot be read."""
        answer = await self._guarded(self._adapter.snapshot_positions(symbol=tracked.entry.symbol))
        if isinstance(answer, BaseException):
            if not isinstance(answer, Exception):
                raise answer
            self._journal_note(
                tracked,
                EVENT_REST_FAILED,
                {"call": "snapshot_positions", "error_type": type(answer).__name__},
                self._now(),
            )
            return None
        for row in answer:
            amount = _attr(row, "position_amt")
            if _attr(row, "symbol") == tracked.entry.symbol and (
                not isinstance(amount, Decimal) or amount != _ZERO
            ):
                return True
        return False

    def _stop_client_id(self, tracked: _Tracked) -> str:
        return derive_algo_client_id(
            plan_hash=tracked.entry.plan_hash, role=OrderRole.STOP_LOSS.value
        )

    def _write_stop_intent(self, tracked: _Tracked, now: datetime) -> None:
        """INTENDED then SENT, committed before the placement runs (F-703, D-14 step 4)."""
        entry = tracked.entry
        role = OrderRole.STOP_LOSS.value

        def intend() -> None:
            self._store.record_protective_intent(
                approval_id=entry.approval_id,
                role=role,
                trade_plan_id=entry.trade_plan_id,
                plan_hash=entry.plan_hash,
                algo_client_id=self._stop_client_id(tracked),
                symbol=entry.symbol,
                side=entry.exit_side,
                intended_price=entry.sl_trigger_price,
                now_utc=now,
                intended_quantity=None,  # closePosition leg: no quantity (D-10)
            )

        def mark_sent() -> None:
            try:
                self._store.mark_sent(approval_id=entry.approval_id, role=role, now_utc=now)
            except IntentStateConflict:
                # The row is already past SENT (an earlier attempt): not a store failure.
                return

        if self._store_write(intend):
            self._store_write(mark_sent)

    async def _place_stop(self, tracked: _Tracked, *, probe_first: bool = True) -> _PlaceOutcome:
        """Query-first by the deterministic id, then place the closePosition stop.

        Returns how the placement ended; the outcome is never protection (only a REST answer of
        ACTIVE is). The exception is read through ``error_facts`` + ``classify`` (D-21), never
        through its message text.
        """
        entry = tracked.entry
        stop_id = self._stop_client_id(tracked)
        try:
            if probe_first:
                probe = await self._adapter.query_algo_order_by_client(client_algo_id=stop_id)
            else:
                probe = None  # the caller just read a definitive absence by this id
        except Exception as exc:  # noqa: BLE001 - existence unknown: protect anyway (see below)
            # The exchange rejects a second open algo order with the same client id, so placing
            # after a failed probe cannot create a duplicate open stop; not placing would leave
            # a filled position unprotected.
            self._journal_note(
                tracked,
                EVENT_REST_FAILED,
                {"call": "query_algo_order_by_client", "error_type": type(exc).__name__},
                self._now(),
            )
        else:
            if _attr(probe, "found") is True:
                # An existing ACTIVE stop is adopted (confirmed by the REST step); a non-active
                # one is never re-placed here.
                return _PlaceOutcome.EXISTS
        try:
            await self._adapter.place_algo_protective(
                symbol=entry.symbol,
                side=entry.exit_side,
                algo_type="CONDITIONAL",
                type="STOP_MARKET",
                position_side="BOTH",
                trigger_price=entry.sl_trigger_price,
                close_position=True,
                quantity=None,
                working_type=entry.working_type,
                client_algo_id=stop_id,
            )
        except PreSendRefusal as exc:
            # Nothing reached the exchange (rate-limit gate, policy missing). The intent stays
            # SENT (REJECTED is terminal and would forbid the retry), no SAFE_MODE comes from the
            # refusal itself (D-21), and the deadline keeps running: Q4 is owner-open, so nothing
            # here claims the position is safe during a 418/429 window.
            self._journal_note(
                tracked,
                EVENT_STOP_NOT_SENT,
                {"error_type": type(exc).__name__, "reason": _refusal_reason(exc)},
                self._now(),
            )
            return _PlaceOutcome.NOT_SENT
        except Exception as exc:  # noqa: BLE001 - classified below; ambiguity is probed by REST
            category = self._classify_placement(exc)
            self._journal_note(
                tracked,
                EVENT_STOP_PLACEMENT_FAILED,
                {
                    "category": "UNCLASSIFIED" if category is None else category.value,
                    "error_type": type(exc).__name__,
                },
                self._now(),
            )
            if category is ExchangeErrorCategory.REJECTED_DEFINITIVE:
                return _PlaceOutcome.REJECTED
            if category is ExchangeErrorCategory.PRECONDITION_NO_POSITION:
                return _PlaceOutcome.NO_POSITION
            return _PlaceOutcome.AMBIGUOUS
        return _PlaceOutcome.PLACED

    def _classify_placement(self, exc: Exception) -> ExchangeErrorCategory | None:
        """The taxonomy category of a placement failure (D-21), from class and code facts only."""
        try:
            return classify(self._adapter.error_facts(exc), CallKind.PLACEMENT)
        except Exception:  # noqa: BLE001 - an unclassifiable failure is ambiguous
            return None

    async def _cancel_entry_remainder(self, tracked: _Tracked) -> None:
        entry = tracked.entry
        try:
            await self._adapter.cancel_normal_order(
                symbol=entry.symbol, orig_client_order_id=entry.entry_client_order_id
            )
        except PreSendRefusal as exc:
            self._journal_note(
                tracked,
                EVENT_ENTRY_CANCEL_NOT_SENT,
                {"error_type": type(exc).__name__, "reason": _refusal_reason(exc)},
                self._now(),
            )
        except Exception as exc:  # noqa: BLE001 - the REST step reads the entry status
            self._journal_note(
                tracked,
                EVENT_ENTRY_CANCEL_FAILED,
                {"error_type": type(exc).__name__},
                self._now(),
            )

    # ------------------------------------------------------------------ #
    # REST confirmation (D-11): the stop is protection only when REST answers ACTIVE.
    # ------------------------------------------------------------------ #

    async def _confirm(self, tracked: _Tracked) -> None:
        """One supervision step of UNPROTECTED / PROTECTED_ENTRY_OPEN (REST is the truth).

        Reads the stop (until it is confirmed, and while the entry is open afterwards, so a stop
        that stopped being ACTIVE is seen: B4) and the entry (until terminal) by deterministic id,
        re-issues the entry cancel while the entry is not terminal, re-places a stop that REST
        proved absent before it was ever confirmed, and then applies the two separate deadlines
        of D-13.

        19-REVIEW WR-04 (owner, D077): a stop that was confirmed and then lost (``stop_lost_at``)
        is never read, re-placed or trusted again. Every step decides by the position
        (``_on_stop_lost``), and the one unprotected-deadline branch that covers a stop that was
        never confirmed covers it too, measured from ``stop_lost_at``. Such a plan never settles
        back to PROTECTED_ENTRY_OPEN or PROTECTED.
        """
        entry = tracked.entry
        already_lost = tracked.stop_lost_at is not None
        need_entry = tracked.entry_terminal_at is None
        need_stop = not already_lost and (tracked.stop_confirmed_at is None or need_entry)
        stop_result: Any = None
        entry_result: Any = None
        if need_stop and need_entry:
            stop_result, entry_result = await asyncio.gather(
                self._adapter.query_algo_order_by_client(
                    client_algo_id=self._stop_client_id(tracked)
                ),
                self._adapter.query_order_by_client(
                    symbol=entry.symbol, orig_client_order_id=entry.entry_client_order_id
                ),
                return_exceptions=True,
            )
        elif need_stop:
            stop_result = await self._guarded(
                self._adapter.query_algo_order_by_client(
                    client_algo_id=self._stop_client_id(tracked)
                )
            )
        elif need_entry:
            entry_result = await self._guarded(
                self._adapter.query_order_by_client(
                    symbol=entry.symbol, orig_client_order_id=entry.entry_client_order_id
                )
            )
        was_confirmed = tracked.stop_confirmed_at is not None
        reading = self._apply_stop_answer(tracked, stop_result) if need_stop else None
        if need_entry:
            self._apply_entry_answer(tracked, entry_result)
        if tracked.entry_terminal_at is None:
            # The entry remainder is cancelled again on every step until REST says it is
            # terminal (a failed or ambiguous cancel is never taken as done).
            await self._cancel_entry_remainder(tracked)

        # The stop is lost when it was seen lost before, or when a stop confirmed on an earlier
        # step reads ABSENT or NOT_ACTIVE now (triggered, consumed or cancelled).
        stop_lost = already_lost or (
            was_confirmed and reading in (_StopReading.ABSENT, _StopReading.NOT_ACTIVE)
        )
        if stop_lost:
            # Decided by the position on every step; never re-placed (19-REVIEW WR-04).
            await self._on_stop_lost(tracked)
            if tracked.state is not ProtectionState.UNPROTECTED:
                return
        elif was_confirmed:
            if self._entry_deadline_reached(tracked):
                await self._enter_close_required(tracked, BRANCH_B1_ENTRY_NOT_TERMINAL)
                return
        elif reading is _StopReading.ABSENT:
            # A stop never confirmed and absent by id: the same id may be placed again, never
            # blindly. A lost stop never reaches this branch.
            outcome = await self._place_stop(tracked, probe_first=False)
            await self._on_place_outcome(tracked, outcome)
            if tracked.state is not ProtectionState.UNPROTECTED:
                return
        if stop_lost or tracked.stop_confirmed_at is None:
            # The stop is not protection (never confirmed: B2 / B3; lost: WR-04). One deadline
            # branch covers both; a lost stop never settles back to a protected state.
            if self._unprotected_deadline_reached(tracked):
                await self._enter_close_required(tracked, self._unprotected_branch(tracked))
                return
            if stop_lost:
                return
        self._settle_state(tracked)

    def _elapsed_ms(self, since: datetime | None) -> int:
        """Whole milliseconds since ``since`` (integer arithmetic only)."""
        assert since is not None
        return (self._now() - since) // timedelta(milliseconds=1)

    def _unprotected_deadline_reached(self, tracked: _Tracked) -> bool:
        """max_unprotected_ms (D-13), reached means escalate.

        Measured from the first fill; for a lost stop from ``stop_lost_at``, the first detection
        of the loss (19-REVIEW WR-04). Neither is ever reset, so a failed read never stops it.
        """
        since = tracked.first_fill_at if tracked.stop_lost_at is None else tracked.stop_lost_at
        return self._elapsed_ms(since) >= self._max_unprotected_ms

    def _unprotected_branch(self, tracked: _Tracked) -> str:
        """The branch code of a reached unprotected deadline."""
        if tracked.stop_lost_at is not None:
            return BRANCH_B4_STOP_LOST_UNRESOLVED
        if tracked.entry_terminal_at is not None:
            return BRANCH_B2_STOP_UNCONFIRMED
        return BRANCH_B3_BOTH_AMBIGUOUS

    def _entry_deadline_reached(self, tracked: _Tracked) -> bool:
        """entry_terminal_timeout_ms (D-13): its own clock, never added to the other."""
        return (
            tracked.entry_terminal_at is None
            and self._elapsed_ms(tracked.first_fill_at) >= self._entry_terminal_timeout_ms
        )

    async def _on_stop_lost(self, tracked: _Tracked) -> None:
        """A once-confirmed stop is not ACTIVE any more: decide by the position (research P6).

        19-REVIEW WR-04 (owner decision, D077). Runs on the step that first sees the loss and on
        every later step of the plan; the stop is never re-placed and never read again.

        * ``stop_lost_at`` is recorded once, at the first detection, and never reset: a failed
          position read neither clears the blocking state nor stops this clock.
        * Exposure without a stop is B4 (a fill after the stop triggered or was consumed):
          CLOSE_REQUIRED, the remainder is cancelled, the exposure is closed by MARKET (the
          closer reads the quantity itself and never sends a guessed one) and the plan never
          carries on.
        * A flat position with a terminal entry ends the plan, once a second, fresh REST read is
          flat too (T-8-30, 19-REVIEW CR-03).
        * Anything else is not a safe state: the position unreadable, flat while the entry can
          still fill, or a zero read the second read did not confirm. The plan is UNPROTECTED
          (blocking new entries) until one of the above happens or the unprotected deadline,
          measured from ``stop_lost_at``, escalates it.
        """
        if tracked.stop_lost_at is None:
            tracked.stop_lost_at = self._now()
        exposed = await self._position_is_open(tracked)
        if exposed is True:
            await self._enter_close_required(tracked, BRANCH_B4_FILL_AFTER_STOP)
            return
        if (
            exposed is False
            and tracked.entry_terminal_at is not None
            and await self._second_read_is_flat(tracked)
        ):
            self._transition(tracked, ProtectionState.FLAT, REASON_STOP_CONSUMED_FLAT, self._now())
            await self._sweep(tracked)
            return
        if tracked.state is not ProtectionState.UNPROTECTED:
            self._transition(tracked, ProtectionState.UNPROTECTED, REASON_STOP_LOST, self._now())

    @staticmethod
    async def _guarded(awaitable: Any) -> Any:
        try:
            return await awaitable
        except Exception as exc:  # noqa: BLE001 - returned so the caller journals it
            return exc

    def _apply_stop_answer(self, tracked: _Tracked, answer: Any) -> _StopReading:
        entry = tracked.entry
        role = OrderRole.STOP_LOSS.value
        if isinstance(answer, BaseException):
            if not isinstance(answer, Exception):
                raise answer
            self._journal_note(
                tracked,
                EVENT_REST_FAILED,
                {"call": "query_algo_order_by_client", "error_type": type(answer).__name__},
                self._now(),
            )
            return _StopReading.UNREADABLE
        found = _attr(answer, "found")
        if found is False:
            return _StopReading.ABSENT
        if found is not True:
            return _StopReading.UNREADABLE
        status = _optional_text(_attr(answer, "algo_status"))
        if is_protection_confirmed(status):
            if tracked.stop_confirmed_at is not None:
                return _StopReading.ACTIVE
            tracked.stop_confirmed_at = self._now()
            self._store_write(
                lambda: self._store.record_result(
                    approval_id=entry.approval_id,
                    role=role,
                    status=ExecutionIntentStatus.ACKED,
                    exchange_order_id=None,
                    exchange_status=status,
                    now_utc=self._now(),
                )
            )
            return _StopReading.ACTIVE
        if tracked.stop_confirmed_at is None and not tracked.stop_unknown_recorded:
            tracked.stop_unknown_recorded = True
            self._store_write(
                lambda: self._store.record_result(
                    approval_id=entry.approval_id,
                    role=role,
                    status=ExecutionIntentStatus.UNKNOWN,
                    exchange_order_id=None,
                    exchange_status=status,
                    now_utc=self._now(),
                )
            )
        return _StopReading.NOT_ACTIVE

    def _apply_entry_answer(self, tracked: _Tracked, answer: Any) -> None:
        if isinstance(answer, BaseException):
            if not isinstance(answer, Exception):
                raise answer
            self._journal_note(
                tracked,
                EVENT_REST_FAILED,
                {"call": "query_order_by_client", "error_type": type(answer).__name__},
                self._now(),
            )
            return
        if _attr(answer, "found") is not True:
            return
        order_id = _optional_text(_attr(answer, "order_id"))
        if order_id is not None:
            tracked.entry_exchange_order_id = order_id
        status = _optional_text(_attr(answer, "status"))
        if status in TERMINAL_ENTRY_STATUSES:
            tracked.entry_terminal_at = self._now()

    def _settle_state(self, tracked: _Tracked) -> None:
        """Move UNPROTECTED / PROTECTED_ENTRY_OPEN to the state the confirmed facts support.

        A lost stop is never protection again (19-REVIEW WR-04 and the CR-03 interaction): its
        earlier confirmation does not count, so such a plan is never settled here.
        """
        if tracked.stop_lost_at is not None:
            return
        stop_confirmed = tracked.stop_confirmed_at is not None
        entry_terminal = tracked.entry_terminal_at is not None
        now = self._now()
        if stop_confirmed and entry_terminal:
            reason = (
                REASON_ENTRY_TERMINAL
                if tracked.state is ProtectionState.PROTECTED_ENTRY_OPEN
                else REASON_STOP_CONFIRMED_ENTRY_TERMINAL
            )
            self._transition(tracked, ProtectionState.PROTECTED, reason, now)
        elif stop_confirmed and tracked.state is ProtectionState.UNPROTECTED:
            self._transition(
                tracked,
                ProtectionState.PROTECTED_ENTRY_OPEN,
                REASON_STOP_CONFIRMED_ENTRY_OPEN,
                now,
            )

    # ------------------------------------------------------------------ #
    # Take profits and the exit (plan 19-16; D-18, D-19, D-20, G2-032, O-03).
    # ------------------------------------------------------------------ #

    async def _position_amount(self, tracked: _Tracked) -> Decimal | None:
        """The signed REST position quantity of the symbol; None when it cannot be read."""
        symbol = tracked.entry.symbol
        answer = await self._guarded(self._adapter.snapshot_positions(symbol=symbol))
        if isinstance(answer, BaseException):
            if not isinstance(answer, Exception):
                raise answer
            self._journal_note(
                tracked,
                EVENT_REST_FAILED,
                {"call": "snapshot_positions", "error_type": type(answer).__name__},
                self._now(),
            )
            return None
        total = _ZERO
        for row in answer:
            if _attr(row, "symbol") != symbol:
                continue
            amount = _attr(row, "position_amt")
            if not isinstance(amount, Decimal) or not amount.is_finite():
                self._journal_note(
                    tracked,
                    EVENT_REST_FAILED,
                    {"call": "snapshot_positions", "error_type": "UnreadablePositionAmount"},
                    self._now(),
                )
                return None
            total += amount
        return total

    async def _second_read_is_flat(self, tracked: _Tracked) -> bool:
        """T-8-30 (19-REVIEW CR-03): a zero position read is confirmed by a second, fresh read.

        Called only after a first read showed the position flat, and before any FLAT transition
        (which sweeps every protective leg, an ACTIVE stop included). True only when this read
        is exactly zero too. A non-zero second read is a transient position gap: it is journaled
        and the caller keeps its state, so the next step reads again. An unreadable read is
        journaled by ``_position_amount`` and is never flat. One empty REST answer can therefore
        never cancel the protection of an open position.
        """
        amount = await self._position_amount(tracked)
        if amount is None:
            return False
        if amount != _ZERO:
            self._journal_note(
                tracked,
                EVENT_REST_FAILED,
                {"call": "snapshot_positions", "error_type": ERROR_TRANSIENT_POSITION_GAP},
                self._now(),
            )
            return False
        return True

    async def _attach_take_profits(self, tracked: _Tracked) -> None:
        """PROTECTED -> COMPLETE or TP_UNAVAILABLE (exactly once per plan).

        The entry is terminal and the stop confirmed, so the final position is settled (G2-032:
        no later resize path exists). The REST position is read; a flat one ends the plan, an
        unreadable one waits for the next step. A snapshot that is stale but COMPLETE gets the
        live exchangeInfo filters read here (D-20); an INCOMPLETE one is refused by attach.
        ``attach_protectives_to_fill`` enters SAFE_MODE for every refusal it reports, so this
        method adds a SAFE_MODE entry only for its own refusal (a contradicting side).
        """
        # Imported here: ``manager`` imports ``live_context``, which imports this module.
        from src.execution.manager import attach_protectives_to_fill

        entry = tracked.entry
        amount = await self._position_amount(tracked)
        if amount is None:
            return
        if amount == _ZERO:
            # T-8-30 (19-REVIEW CR-03): one zero read never sweeps the confirmed stop.
            if await self._second_read_is_flat(tracked):
                self._transition(tracked, ProtectionState.FLAT, REASON_POSITION_CLOSED, self._now())
                await self._sweep(tracked)
            return
        if (amount > _ZERO) != (entry.side == "LONG"):
            await self._enter_tp_unavailable(
                tracked,
                reason_code="POSITION_SIDE_MISMATCH",
                detail=DETAIL_POSITION_SIDE_MISMATCH,
                safe_mode_entered=False,
            )
            return
        now = self._now()
        snapshot = entry.plan_constraint_snapshot
        live_filters: Any = None
        if (
            not snapshot_is_valid_for_live(snapshot, now_utc=now, ttl=entry.snapshot_ttl)
            and snapshot.live_inputs_status is LiveInputsStatus.COMPLETE
        ):
            read = await self._guarded(self._adapter.symbol_lot_filters(symbol=entry.symbol))
            if isinstance(read, BaseException):
                if not isinstance(read, Exception):
                    raise read
                # Attach refuses a stale snapshot without live filters (fail closed).
                self._journal_note(
                    tracked,
                    EVENT_REST_FAILED,
                    {"call": "symbol_lot_filters", "error_type": type(read).__name__},
                    now,
                )
            else:
                live_filters = read
        outcome = await attach_protectives_to_fill(
            entry=entry,
            position_quantity=abs(amount),
            live_lot_filters=live_filters,
            adapter=self._adapter,  # type: ignore[arg-type]
            intent_store=self._store,
            now_utc=now,
            safe_mode_controller=self._safe_mode,
        )
        if not outcome.is_no_trade:
            self._transition(tracked, ProtectionState.COMPLETE, REASON_TP_LEGS_CONFIRMED, now)
        elif outcome.reason_code != "NO_FILL":
            await self._enter_tp_unavailable(
                tracked,
                reason_code=outcome.reason_code,
                detail=outcome.failure_detail or outcome.reason_code,
                safe_mode_entered=True,
            )

    async def _enter_tp_unavailable(
        self, tracked: _Tracked, *, reason_code: str, detail: str, safe_mode_entered: bool
    ) -> None:
        """The CR-03 routine: the take profits are not in place but the stop is (once per plan).

        The confirmed stop is kept (never cancelled here), nothing is closed for this reason
        alone (O-03: no automatic flatten, no single-TP fallback), the plan is never a normal
        completion, and ``blocks_new_entries()`` stays False (SAFE_MODE blocks entries through
        its own gate). SAFE_MODE with ENTRY_WITHOUT_PROTECTIVE, the journal note and the
        critical alert are all attempted; one failing never skips the others.
        """
        entry = tracked.entry
        now = self._now()
        self._transition(tracked, ProtectionState.TP_UNAVAILABLE, REASON_TP_UNAVAILABLE, now)
        self._journal_note(
            tracked,
            EVENT_TP_UNAVAILABLE,
            {"failure_detail": detail, "reason_code": reason_code},
            now,
        )
        if not safe_mode_entered:
            try:
                self._safe_mode.enter_safe_mode(
                    reason=SAFE_MODE_ENTRY_WITHOUT_PROTECTIVE, now_utc=now
                )
            except Exception:  # noqa: BLE001, S110 - the alert still goes out
                pass
        try:
            self._alerts.critical(
                event=ALERT_TP_UNAVAILABLE,
                plan_hash=entry.plan_hash,
                symbol=entry.symbol,
                reason=detail,
                now_utc=now,
            )
        except Exception:  # noqa: BLE001, S110 - SAFE_MODE and the journal row already exist
            pass

    async def _watch_exit(self, tracked: _Tracked) -> None:
        """COMPLETE / TP_UNAVAILABLE: a flat REST position ends the plan (FLAT) and is swept.

        The stop, TP1 or TP2 closed the position (whichever fired); the plan's remaining legs are
        cancelled by deterministic id whatever the exchange auto-cancelled (A3). An open or
        unreadable position keeps the state, and so does a zero read that a second, fresh read
        does not confirm (T-8-30, 19-REVIEW CR-03).
        """
        amount = await self._position_amount(tracked)
        if amount is None or amount != _ZERO:
            return
        if not await self._second_read_is_flat(tracked):
            return
        self._transition(tracked, ProtectionState.FLAT, REASON_POSITION_CLOSED, self._now())
        await self._sweep(tracked)

    # ------------------------------------------------------------------ #
    # CLOSE_REQUIRED, the emergency close, FLAT and the orphan sweep (D-12, D034).
    # ------------------------------------------------------------------ #

    async def _enter_close_required(self, tracked: _Tracked, branch: str) -> None:
        """Once per plan: SAFE_MODE, critical alert, journaled reason, then the emergency close.

        The stop is never cancelled here (a stop that is still open is kept until the position is
        flat) and never resent. The entry remainder cancel is issued by the caller's step (the
        first-fill gather or the supervision step) and re-issued every later step.
        """
        entry = tracked.entry
        now = self._now()
        tracked.close_branch = branch
        self._transition(tracked, ProtectionState.CLOSE_REQUIRED, branch, now)
        if branch == BRANCH_B1_ENTRY_NOT_TERMINAL:
            # Accepted knowingly (owner note): a position with a good stop is closed because an
            # entry cancel was slow; the reason is journaled.
            self._journal_note(
                tracked,
                EVENT_CLOSE_REQUIRED,
                {"accepted_knowingly": "STOP_KEPT_ENTRY_CANCEL_SLOW", "branch": branch},
                now,
            )
        try:
            self._safe_mode.enter_safe_mode(reason=SAFE_MODE_CLOSE_REQUIRED, now_utc=now)
        except Exception:  # noqa: BLE001, S110 - the alert and the close still go out
            pass
        try:
            self._alerts.critical(
                event=ALERT_CLOSE_REQUIRED,
                plan_hash=entry.plan_hash,
                symbol=entry.symbol,
                reason=branch,
                now_utc=now,
            )
        except Exception:  # noqa: BLE001, S110 - SAFE_MODE and the journal row already exist
            pass
        await self._attempt_close(tracked, branch)

    async def _attempt_close(self, tracked: _Tracked, reason: str) -> bool:
        """One emergency close attempt; True only when REST shows the position flat."""
        try:
            closed = await self._closer.close_position(entry=tracked.entry, reason=reason)
        except Exception as exc:  # noqa: BLE001 - a failed close attempt never declares safety
            self._journal_note(
                tracked, EVENT_CLOSE_ATTEMPT_ERROR, {"error_type": type(exc).__name__}, self._now()
            )
            closed = False
        if closed:
            return True
        if tracked.state is not ProtectionState.CLOSE_FAILED:
            self._transition(
                tracked, ProtectionState.CLOSE_FAILED, self._close_failure(), self._now()
            )
        return False

    def _close_failure(self) -> str:
        """Fixed reason text of a close that did not end flat (read from the closer, if offered)."""
        result = getattr(self._closer, "last_result", None)
        status = getattr(result, "status", None)
        if str(getattr(status, "value", status)) == "NOT_SENT":
            return REASON_CLOSE_NOT_SENT
        return REASON_CLOSE_FAILED

    async def _close_flow(self, tracked: _Tracked) -> None:
        """Every step of CLOSE_REQUIRED / CLOSE_FAILED: watch the entry, close until flat.

        The entry is read first (and its remainder cancelled again while it is not terminal);
        FLAT needs the entry terminal as read BEFORE the close and REST flat after it, so a
        late fill of a still-open entry is closed on a later step and never missed.
        """
        entry = tracked.entry
        if tracked.entry_terminal_at is None:
            answer = await self._guarded(
                self._adapter.query_order_by_client(
                    symbol=entry.symbol, orig_client_order_id=entry.entry_client_order_id
                )
            )
            self._apply_entry_answer(tracked, answer)
            if tracked.entry_terminal_at is None:
                await self._cancel_entry_remainder(tracked)
        entry_terminal = tracked.entry_terminal_at is not None
        closed = await self._attempt_close(tracked, tracked.close_branch or REASON_CLOSE_FAILED)
        if not closed:
            return
        if entry_terminal:
            self._transition(
                tracked, ProtectionState.FLAT, REASON_CLOSED_ENTRY_TERMINAL, self._now()
            )
            await self._sweep(tracked)
        elif tracked.state is ProtectionState.CLOSE_FAILED:
            # Flat now, but the entry is still open and may fill again: keep watching.
            self._transition(
                tracked, ProtectionState.CLOSE_REQUIRED, REASON_CLOSED_ENTRY_OPEN, self._now()
            )

    async def _sweep(self, tracked: _Tracked) -> None:
        """Cancel the plan's protective legs by deterministic id once the position is flat."""
        # Imported here: ``manager`` imports ``live_context``, which imports this module.
        from src.execution.manager import cancel_untriggered_protectives

        entry = tracked.entry
        try:
            await cancel_untriggered_protectives(
                plan_hash=entry.plan_hash,
                symbol=entry.symbol,
                adapter=self._adapter,  # type: ignore[arg-type]
                journal=self._journal,
                now_utc=self._now(),
            )
        except Exception as exc:  # noqa: BLE001 - retried by the next step; the legs are journaled
            self._journal_note(
                tracked, EVENT_SWEEP_FAILED, {"error_type": type(exc).__name__}, self._now()
            )
            return
        tracked.sweep_done = True

    # ------------------------------------------------------------------ #
    # Transitions, journal, store and SAFE_MODE helpers.
    # ------------------------------------------------------------------ #

    def _now(self) -> datetime:
        now = self._clock()
        _require_utc(now, "clock()")
        return now

    def _transition(
        self, tracked: _Tracked, new_state: ProtectionState, reason: str, now: datetime
    ) -> bool:
        """The one place a protection state changes (D-29, T-A). True when ``new_state`` holds.

        An equal-state request is an idempotent no-op decided before the guard: no ``seq`` bump,
        no journal row. Any other move must be an edge of the PROTECTION table of
        ``src.domain.transitions`` (a plan that has no state yet may only enter
        ``PROTECTION_INITIAL_STATE``). A refused move changes nothing (``state``, ``seq`` and
        ``last_reason`` stay), journals one ``PROTECTION_TRANSITION_REJECTED`` row and enters
        SAFE_MODE with ``PROTECTION_STATE_INVALID``; it returns False. Callers keep their own
        fail-closed handling and may ignore the result.
        """
        if tracked.state is new_state:
            return True
        entry = tracked.entry
        previous = _NO_STATE if tracked.state is None else tracked.state.value
        if not self._edge_is_legal(tracked, new_state):
            self._reject_transition(tracked, previous, new_state, reason, now)
            return False
        tracked.seq += 1
        tracked.state = new_state
        tracked.last_reason = reason
        payload = json.dumps(
            {
                "approval_id": entry.approval_id,
                "from": previous,
                "reason": reason,
                "seq": tracked.seq,
                "symbol": entry.symbol,
                "to": new_state.value,
                "trade_plan_id": entry.trade_plan_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self._record_journal(
            JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix=_TRANSITION_ID_PREFIX,
                    correlation_id=f"{_CORRELATION_PREFIX}{entry.plan_hash}",
                    event_type=EVENT_PROTECTION_TRANSITION,
                    entity_id=entry.plan_hash,
                    step=f"{tracked.seq}:{previous}->{new_state.value}",
                ),
                occurred_at_utc=now,
                event_type=EVENT_PROTECTION_TRANSITION,
                entity_type="ProtectionState",
                entity_id=entry.plan_hash,
                correlation_id=f"{_CORRELATION_PREFIX}{entry.plan_hash}",
                payload_json=payload,
            ),
            now,
        )
        return True

    @staticmethod
    def _edge_is_legal(tracked: _Tracked, new_state: ProtectionState) -> bool:
        """The PROTECTION table decides (a missing state may only enter the initial state)."""
        if tracked.state is None:
            return new_state.value == PROTECTION_INITIAL_STATE
        return is_legal(TransitionKind.PROTECTION, tracked.state, new_state)

    def _reject_transition(
        self,
        tracked: _Tracked,
        previous: str,
        new_state: ProtectionState,
        reason: str,
        now: datetime,
    ) -> None:
        """Journal a refused move (state and seq untouched) and enter SAFE_MODE (fail closed)."""
        entry = tracked.entry
        body = json.dumps(
            {
                "approval_id": entry.approval_id,
                "from": previous,
                "reason": reason,
                "seq": tracked.seq,
                "symbol": entry.symbol,
                "to": new_state.value,
                "trade_plan_id": entry.trade_plan_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self._record_journal(
            JournalEvent(
                journal_event_id=content_hash_event_id(
                    prefix=_REJECTED_ID_PREFIX,
                    event_type=EVENT_PROTECTION_TRANSITION_REJECTED,
                    entity_id=entry.plan_hash,
                    occurred_at_utc=now,
                    payload_json=body,
                ),
                occurred_at_utc=now,
                event_type=EVENT_PROTECTION_TRANSITION_REJECTED,
                entity_type="ProtectionState",
                entity_id=entry.plan_hash,
                correlation_id=f"{_CORRELATION_PREFIX}{entry.plan_hash}",
                payload_json=body,
            ),
            now,
        )
        try:
            self._safe_mode.enter_safe_mode(reason=SAFE_MODE_PROTECTION_STATE_INVALID, now_utc=now)
        except Exception:  # noqa: BLE001, S110 - the refusal and its journal row already exist
            pass

    def _journal_note(
        self, tracked: _Tracked, event_type: str, payload: dict[str, str], now: datetime
    ) -> None:
        """Journal one diagnostic event (fixed text and exception TYPE names only)."""
        entry = tracked.entry
        body = json.dumps(
            {**payload, "symbol": entry.symbol, "trade_plan_id": entry.trade_plan_id},
            sort_keys=True,
            separators=(",", ":"),
        )
        self._record_journal(
            JournalEvent(
                journal_event_id=content_hash_event_id(
                    prefix="pnt",
                    event_type=event_type,
                    entity_id=entry.plan_hash,
                    occurred_at_utc=now,
                    payload_json=body,
                ),
                occurred_at_utc=now,
                event_type=event_type,
                entity_type="ProtectionState",
                entity_id=entry.plan_hash,
                correlation_id=f"{_CORRELATION_PREFIX}{entry.plan_hash}",
                payload_json=body,
            ),
            now,
        )

    def _journal_unknown_fill(self, fill: _QueuedFill) -> None:
        key = (fill.order_id, fill.trade_id)
        if key in self._unknown_fills_journaled:
            return
        self._unknown_fills_journaled.add(key)
        now = self._now()
        body = json.dumps(
            {
                "after_gap": fill.after_gap,
                "order_id": fill.order_id,
                "source": fill.source,
                "symbol": fill.symbol,
                "trade_id": fill.trade_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self._record_journal(
            JournalEvent(
                journal_event_id=content_hash_event_id(
                    prefix="pnt",
                    event_type=EVENT_UNKNOWN_FILL,
                    entity_id=fill.order_id,
                    occurred_at_utc=now,
                    payload_json=body,
                ),
                occurred_at_utc=now,
                event_type=EVENT_UNKNOWN_FILL,
                entity_type="Order",
                entity_id=fill.order_id,
                correlation_id="protection_unknown_fill",
                payload_json=body,
            ),
            now,
        )

    def _record_journal(self, event: JournalEvent, now: datetime) -> None:
        """Journal an event; a failing journal loses only the audit row (D034)."""
        try:
            self._journal.record(event)
        except Exception:  # noqa: BLE001 - protection outranks the audit row
            self._enter_safe_mode_once(SAFE_MODE_DB_FAILURE, now)

    def _store_write(self, write: Callable[[], object]) -> bool:
        """Run one intent-store write; False means the store failed (SAFE_MODE once, then skip)."""
        if self._store_failed:
            return False
        try:
            write()
        except PersistenceError:
            self._store_failed = True
            self._enter_safe_mode_once(SAFE_MODE_DB_FAILURE, self._now())
            return False
        return True

    def _enter_safe_mode_once(self, reason: str, now: datetime) -> None:
        if self._db_failure_reported:
            return
        self._db_failure_reported = True
        try:
            self._safe_mode.enter_safe_mode(reason=reason, now_utc=now)
        except Exception:  # noqa: BLE001, S110 - the flag is set first; only its audit row is lost
            pass


__all__ = [
    "ALERT_CLOSE_REQUIRED",
    "ALERT_TP_UNAVAILABLE",
    "BLOCKING_STATES",
    "BRANCH_B1_ENTRY_NOT_TERMINAL",
    "BRANCH_B2_STOP_UNCONFIRMED",
    "BRANCH_B3_BOTH_AMBIGUOUS",
    "BRANCH_B4_FILL_AFTER_STOP",
    "BRANCH_B4_STOP_LOST_UNRESOLVED",
    "BRANCH_B5_STOP_REJECTED",
    "BRANCH_NO_POSITION_BUT_EXPOSED",
    "ERROR_TRANSIENT_POSITION_GAP",
    "EVENT_CLOSE_ATTEMPT_ERROR",
    "EVENT_CLOSE_REQUIRED",
    "EVENT_ENTRY_CANCEL_FAILED",
    "EVENT_ENTRY_CANCEL_NOT_SENT",
    "EVENT_ENTRY_UNRESOLVED",
    "EVENT_FILL_QUANTITY_UNKNOWN",
    "EVENT_PROTECTION_TRANSITION",
    "EVENT_PROTECTION_TRANSITION_REJECTED",
    "EVENT_REST_FAILED",
    "EVENT_STEP_ERROR",
    "EVENT_STOP_NOT_SENT",
    "EVENT_STOP_PLACEMENT_FAILED",
    "EVENT_SWEEP_FAILED",
    "EVENT_TP_UNAVAILABLE",
    "EVENT_UNKNOWN_FILL",
    "FILLED_ENTRY_STATUSES",
    "POSITION_MODE_HEDGE",
    "POSITION_MODE_ONE_WAY",
    "SAFE_MODE_CLOSE_REQUIRED",
    "SAFE_MODE_DB_FAILURE",
    "SAFE_MODE_ENTRY_WITHOUT_PROTECTIVE",
    "SAFE_MODE_PROTECTION_STATE_INVALID",
    "TERMINAL_ENTRY_STATUSES",
    "UNRESOLVED_ENTRY_POLL_EVERY_N_STEPS",
    "CriticalAlertSink",
    "EmergencyCloser",
    "PlanProtection",
    "ProtectionAdapter",
    "ProtectionCoordinator",
    "ProtectionRegistry",
    "ProtectionState",
    "RestingEntry",
    "RoutedFillLike",
]
