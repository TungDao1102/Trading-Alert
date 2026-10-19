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

This module is the tracer (branch B0, the happy path) plus REST-only fill detection and the
router wiring. The failure branches and the two deadlines are plan 19-14, the take-profit legs
plan 19-16, the manager hand-off plan 19-15, the emergency closer plan 19-12.

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
from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.domain.journal import JournalEvent, content_hash_event_id, correlated_event_id
from src.execution.constraint_snapshot import PlanConstraintSnapshot
from src.execution.execution_limits import ExecutionLimits
from src.execution.intent_store import ExecutionIntentStore
from src.execution.order_ids import derive_algo_client_id
from src.persistence.errors import IntentStateConflict, PersistenceError

POSITION_MODE_ONE_WAY = "ONE_WAY"
POSITION_MODE_HEDGE = "HEDGE"

SAFE_MODE_DB_FAILURE = "DB_FAILURE"

EVENT_PROTECTION_TRANSITION = "PROTECTION_TRANSITION"
EVENT_FILL_QUANTITY_UNKNOWN = "PROTECTION_FILL_QUANTITY_UNKNOWN"
EVENT_UNKNOWN_FILL = "PROTECTION_UNKNOWN_FILL"
EVENT_REST_FAILED = "PROTECTION_REST_FAILED"
EVENT_STOP_PLACEMENT_FAILED = "PROTECTION_STOP_PLACEMENT_FAILED"
EVENT_ENTRY_CANCEL_FAILED = "PROTECTION_ENTRY_CANCEL_FAILED"
EVENT_STEP_ERROR = "PROTECTION_STEP_ERROR"

# The order statuses that end an entry (research P5): FILLED, and the three "ended without
# (further) fills" statuses of the router (TERMINAL_NOT_FILLED_STATUSES).
TERMINAL_ENTRY_STATUSES: frozenset[str] = frozenset(
    {"FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}
)
FILLED_ENTRY_STATUSES: frozenset[str] = frozenset({"PARTIALLY_FILLED", "FILLED"})

_ZERO = Decimal("0")
_CORRELATION_PREFIX = "protection_"
_TRANSITION_ID_PREFIX = "ptr"
_NO_STATE = "NONE"

# Reasons journaled on a transition (fixed project text, never exchange text).
REASON_REGISTERED = "REGISTERED"
REASON_FIRST_FILL_STREAM = "FIRST_FILL_STREAM"
REASON_FIRST_FILL_REST = "FIRST_FILL_REST"
REASON_STOP_CONFIRMED_ENTRY_TERMINAL = "STOP_CONFIRMED_ENTRY_TERMINAL"
REASON_STOP_CONFIRMED_ENTRY_OPEN = "STOP_CONFIRMED_ENTRY_OPEN"
REASON_ENTRY_TERMINAL = "ENTRY_TERMINAL"
REASON_ENTRY_ENDED_NO_FILL = "ENTRY_ENDED_NO_FILL"


class ProtectionState(str, Enum):
    """The stable protection state names (Phase 20 reads them, research P8).

    This plan implements the transitions AWAITING_FILL -> UNPROTECTED -> PROTECTED_ENTRY_OPEN /
    PROTECTED and AWAITING_FILL -> ENTRY_ENDED_NO_FILL. The transitions into COMPLETE,
    TP_UNAVAILABLE (plan 19-16), CLOSE_REQUIRED, FLAT and CLOSE_FAILED (plan 19-14) are later.
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


# A position in one of these states is exposed without a confirmed stop (or being closed).
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


class _Tracked:
    """The mutable record of one registered plan (in-process; the exchange is the truth)."""

    def __init__(self, entry: RestingEntry) -> None:
        self.entry = entry
        self.state: ProtectionState | None = None
        self.seq = 0
        self.first_fill_at: datetime | None = None
        self.stop_confirmed_at: datetime | None = None
        self.entry_terminal_at: datetime | None = None
        self.last_reason: str | None = None
        self.entry_exchange_order_id: str | None = None
        self.stop_unknown_recorded = False

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
        )


def _attr(obj: Any, name: str) -> Any:
    """Read ``name`` from an attribute-style or dict-style object."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


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
        self._transition(tracked, ProtectionState.AWAITING_FILL, REASON_REGISTERED, self._now())

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
            if owner.state is ProtectionState.AWAITING_FILL:
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
            elif state in (ProtectionState.UNPROTECTED, ProtectionState.PROTECTED_ENTRY_OPEN):
                await self._confirm(tracked)
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

    async def _place_stop(self, tracked: _Tracked) -> None:
        """Query-first by the deterministic id, then place the closePosition stop."""
        entry = tracked.entry
        stop_id = self._stop_client_id(tracked)
        try:
            probe = await self._adapter.query_algo_order_by_client(client_algo_id=stop_id)
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
                # one is never re-placed here (the branch logic is plan 19-14).
                return
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
        except Exception as exc:  # noqa: BLE001 - ambiguous: the REST step resolves it
            self._journal_note(
                tracked,
                EVENT_STOP_PLACEMENT_FAILED,
                {"error_type": type(exc).__name__},
                self._now(),
            )

    async def _cancel_entry_remainder(self, tracked: _Tracked) -> None:
        entry = tracked.entry
        try:
            await self._adapter.cancel_normal_order(
                symbol=entry.symbol, orig_client_order_id=entry.entry_client_order_id
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
        entry = tracked.entry
        need_stop = tracked.stop_confirmed_at is None
        need_entry = tracked.entry_terminal_at is None
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
        if need_stop:
            self._apply_stop_answer(tracked, stop_result)
        if need_entry:
            self._apply_entry_answer(tracked, entry_result)
        self._settle_state(tracked)

    @staticmethod
    async def _guarded(awaitable: Any) -> Any:
        try:
            return await awaitable
        except Exception as exc:  # noqa: BLE001 - returned so the caller journals it
            return exc

    def _apply_stop_answer(self, tracked: _Tracked, answer: Any) -> None:
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
            return
        if _attr(answer, "found") is not True:
            return
        status = _optional_text(_attr(answer, "algo_status"))
        if is_protection_confirmed(status):
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
        elif not tracked.stop_unknown_recorded:
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
        """Move UNPROTECTED / PROTECTED_ENTRY_OPEN to the state the confirmed facts support."""
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
    # Transitions, journal, store and SAFE_MODE helpers.
    # ------------------------------------------------------------------ #

    def _now(self) -> datetime:
        now = self._clock()
        _require_utc(now, "clock()")
        return now

    def _transition(
        self, tracked: _Tracked, new_state: ProtectionState, reason: str, now: datetime
    ) -> None:
        entry = tracked.entry
        previous = _NO_STATE if tracked.state is None else tracked.state.value
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
    "BLOCKING_STATES",
    "EVENT_ENTRY_CANCEL_FAILED",
    "EVENT_FILL_QUANTITY_UNKNOWN",
    "EVENT_PROTECTION_TRANSITION",
    "EVENT_REST_FAILED",
    "EVENT_STEP_ERROR",
    "EVENT_STOP_PLACEMENT_FAILED",
    "EVENT_UNKNOWN_FILL",
    "FILLED_ENTRY_STATUSES",
    "POSITION_MODE_HEDGE",
    "POSITION_MODE_ONE_WAY",
    "SAFE_MODE_DB_FAILURE",
    "TERMINAL_ENTRY_STATUSES",
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
