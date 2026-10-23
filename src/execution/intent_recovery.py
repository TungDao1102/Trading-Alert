"""Restart recovery of in-flight execution intents (Phase 17-12, D-14, F-703).

A process that dies between the write-ahead steps leaves intents INTENDED or SENT whose
exchange state is unknown. On restart this module LEARNS, it never ACTS:

  1. every SENT intent is first recorded UNKNOWN (the honest state: the order may or may not
     exist); an INTENDED ENTRY (never sent: `mark_sent` commits before `place_entry`) is probed
     first, see below;
  2. every unresolved intent is probed by its deterministic client id only
     (`query_order_by_client` for the ENTRY leg, `query_algo_order_by_client` for the
     protective legs) and resolved (Phase 20, plan 20-10, D-11, Q5, research F5):

       found                                       -> ACKED (with the exchange order id)
       ENTRY, INTENDED, absent                     -> REJECTED, reason NEVER_SENT (one probe;
                                                      INTENDED -> REJECTED is a legal move)
       ENTRY, SENT or UNKNOWN, absent              -> stays UNKNOWN. Absence alone is not
                                                      evidence: `newClientOrderId` is unique only
                                                      among OPEN orders (docs/integration/
                                                      BINANCE.md 6.1). `UnknownEntryResolver`
                                                      below closes it, and only on evidence.
       protective leg, absent, intended < window,
         and its plan's ENTRY is REJECTED          -> REJECTED
       protective leg of a plan whose ENTRY is
         not REJECTED (or unreadable)              -> stays UNKNOWN for the coordinator rebuild
                                                      (F5): recovery never terminates a stop the
                                                      coordinator must re-place
       probe error, indeterminate answer, or an
       absent leg older than the window            -> stays UNKNOWN

  3. when any intent stays UNKNOWN, SAFE_MODE is entered once with reason
     `UNRESOLVED_EXECUTION_INTENT` (GLOSSARY 9.4), so no new entry is placed. Leaving
     SAFE_MODE stays with the Phase 20 reconciler (D-14); closing an intent never exits it (D-15).

Placement is structurally impossible here: the adapter parameter is the two-method
`IntentProbeAdapter` Protocol below, which has no order-placement method, and a retried
send after a restart is exactly the double entry the write-ahead rows exist to prevent
(research Pitfall 11, F-703, T-17-31).

The 3-day default window comes from Binance Query Order retention: an order that was
canceled or expired without a fill and is older than 3 days is no longer returned, so
"not found" is a definitive absence only for younger intents. It now applies only to the
protective legs of a plan whose ENTRY is REJECTED. It is a keyword argument so a documented
change in the exchange rule is a one-line edit at the call site.

A GTD expiry is not proof that an order is terminal: Phase 19 assumption A2 stays
[NOT_TESTED]. Evidence labels: Binance id visibility is [DOC], nothing here is [DEMO].

Imports: stdlib, `src.domain`, `src.execution` and the pure-Python `src.persistence.errors`
(the same typed failures the manager catches); no SQLAlchemy. The resolver is a tested
function, not wired into a live process (Phase 20 and Phase 24 own the wiring).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.domain.journal import JournalEvent, content_hash_event_id
from src.domain.stream_records import (
    EXIT_EVIDENCE_PREFIX,
    EvidenceSource,
    ExitEvidence,
    exit_evidence_event,
)
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.execution.intent_store import (
    RESOLUTION_NEVER_SENT,
    RESOLUTION_RECONCILED_ABSENT,
    ExecutionIntentStore,
    IntentRecord,
)
from src.persistence.errors import PersistenceError

# SAFE_MODE entry reasons (GLOSSARY 9.4).
UNRESOLVED_EXECUTION_INTENT = "UNRESOLVED_EXECUTION_INTENT"
_DB_FAILURE = "DB_FAILURE"

# Binance Query Order: a canceled or expired order with no fills older than 3 days is not
# returned (docs, Query Order "orders not found" rules; research Pitfall 11).
DEFAULT_LOOKUP_WINDOW = timedelta(days=3)

_ENTRY_ROLE = OrderRole.ENTRY.value

# Journal events of the UNKNOWN-entry protocol (plan 20-10, D-11). Payloads carry ids and fixed
# text only, never exchange text.
EVENT_UNKNOWN_ENTRY_PROBE = "UNKNOWN_ENTRY_PROBE"
EVENT_UNKNOWN_ENTRY_KEPT = "UNKNOWN_ENTRY_KEPT"
_INTENT_ENTITY = "EXECUTION_INTENT"
_PROBE_ID_PREFIX = "uep"
_KEPT_ID_PREFIX = "uek"
_CORRELATION_PREFIX = "unknown-entry:"

# Why an UNKNOWN entry stayed UNKNOWN in one step (fixed text).
KEPT_NOT_DUE = "NOT_DUE"
KEPT_PROBES_PENDING = "PROBES_PENDING"
KEPT_PROBE_INDETERMINATE = "PROBE_INDETERMINATE"
KEPT_GTD_GRACE_NOT_PASSED = "GTD_GRACE_NOT_PASSED"
KEPT_EXPOSURE_PRESENT = "EXPOSURE_PRESENT"
KEPT_OPEN_ORDER_PRESENT = "OPEN_ORDER_PRESENT"
KEPT_READ_INDETERMINATE = "READ_INDETERMINATE"
KEPT_READ_FAILED = "READ_FAILED"
KEPT_GTD_UNKNOWN = "GTD_UNKNOWN"
KEPT_JOURNAL_FAILED = "JOURNAL_FAILED"
KEPT_STORE_FAILED = "STORE_FAILED"

# (approval_id, role, final status): the deterministic report row.
IntentOutcome = tuple[str, str, ExecutionIntentStatus]


class IntentProbeAdapter(Protocol):
    """The two read-only lookups recovery may use; there is deliberately nothing else."""

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> Any: ...

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any: ...


class SafeModeEntry(Protocol):
    """The one `SafeModeController` method recovery needs."""

    def enter_safe_mode(self, *, reason: str, now_utc: datetime | None = None) -> None: ...


@dataclass(frozen=True)
class RecoveryReport:
    """What one recovery pass did, in the store's deterministic order."""

    resolved: tuple[IntentOutcome, ...]
    unresolved: tuple[IntentOutcome, ...]
    safe_mode_entered: bool


@dataclass(frozen=True)
class _Probe:
    """Interpreted answer of one probe: found / absent / cannot tell."""

    found: bool | None
    exchange_order_id: str | None = None
    exchange_status: str | None = None


_CANNOT_TELL = _Probe(found=None)


def _read(obj: Any, name: str) -> Any:
    """Read `name` from a dataclass-style object or a dict-style payload."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC-aware datetime")


async def _probe(adapter: IntentProbeAdapter, record: IntentRecord) -> _Probe:
    """Query the exchange by the intent's deterministic id. Never raises, never places."""
    try:
        if record.role == _ENTRY_ROLE:
            if record.client_order_id is None:
                return _CANNOT_TELL
            answer = await adapter.query_order_by_client(
                symbol=record.symbol, orig_client_order_id=record.client_order_id
            )
            status_field = "status"
            order_id = _text_or_none(_read(answer, "order_id"))
        else:
            if record.algo_client_id is None:
                return _CANNOT_TELL
            answer = await adapter.query_algo_order_by_client(client_algo_id=record.algo_client_id)
            status_field = "algo_status"
            order_id = None  # the algo probe carries no exchange order id
    except Exception:  # noqa: BLE001 - a failed probe means "cannot tell", never "absent"
        return _CANNOT_TELL
    found = _read(answer, "found")
    # Only a literal True / False is an answer; anything else is indeterminate.
    if found is True:
        return _Probe(
            found=True,
            exchange_order_id=order_id,
            exchange_status=_text_or_none(_read(answer, status_field)),
        )
    if found is False:
        return _Probe(found=False)
    return _CANNOT_TELL


def _record(
    store: ExecutionIntentStore,
    record: IntentRecord,
    status: ExecutionIntentStatus,
    *,
    exchange_order_id: str | None,
    exchange_status: str | None,
    now_utc: datetime,
) -> bool:
    """One status write; False means the store failed and the status did NOT change."""
    try:
        store.record_result(
            approval_id=record.approval_id,
            role=record.role,
            status=status,
            exchange_order_id=exchange_order_id,
            exchange_status=exchange_status,
            now_utc=now_utc,
        )
    except PersistenceError:
        return False
    return True


def _protective_leg_may_be_rejected(
    store: ExecutionIntentStore,
    record: IntentRecord,
    *,
    now_utc: datetime,
    lookup_window: timedelta,
) -> bool:
    """True only for a young protective leg whose plan's ENTRY is REJECTED (research F5).

    The ENTRY intent of a live plan is not REJECTED, and then the coordinator rebuilds the stop:
    recovery must never terminate it. An unreadable ENTRY row counts as "not REJECTED".
    """
    if record.role == _ENTRY_ROLE:
        return False
    if now_utc - record.intended_at_utc >= lookup_window:
        return False
    try:
        entry = store.get_entry(approval_id=record.approval_id)
    except PersistenceError:
        return False
    return entry is not None and entry.intent_status == ExecutionIntentStatus.REJECTED


async def _resolve_intended_entry(
    *,
    store: ExecutionIntentStore,
    adapter: IntentProbeAdapter,
    record: IntentRecord,
    now_utc: datetime,
) -> ExecutionIntentStatus:
    """An INTENDED ENTRY was never sent (T-C): one probe, then NEVER_SENT / ACKED / UNKNOWN."""
    answer = await _probe(adapter, record)
    if answer.found is False:
        try:
            store.finalize_reconciled_resolution(
                approval_id=record.approval_id,
                role=record.role,
                reason_code=RESOLUTION_NEVER_SENT,
                now_utc=now_utc,
            )
        except PersistenceError:
            return record.intent_status
        return ExecutionIntentStatus.REJECTED
    if not _record(
        store,
        record,
        ExecutionIntentStatus.UNKNOWN,
        exchange_order_id=None,
        exchange_status=None,
        now_utc=now_utc,
    ):
        return record.intent_status
    if answer.found is True and _record(
        store,
        record,
        ExecutionIntentStatus.ACKED,
        exchange_order_id=answer.exchange_order_id,
        exchange_status=answer.exchange_status,
        now_utc=now_utc,
    ):
        return ExecutionIntentStatus.ACKED
    return ExecutionIntentStatus.UNKNOWN


async def _resolve_one(
    *,
    store: ExecutionIntentStore,
    adapter: IntentProbeAdapter,
    record: IntentRecord,
    now_utc: datetime,
    lookup_window: timedelta,
) -> ExecutionIntentStatus:
    """Resolve one intent; returns its status as stored afterwards."""
    status = record.intent_status
    if record.role == _ENTRY_ROLE and status == ExecutionIntentStatus.INTENDED:
        return await _resolve_intended_entry(
            store=store, adapter=adapter, record=record, now_utc=now_utc
        )
    if status in (ExecutionIntentStatus.INTENDED, ExecutionIntentStatus.SENT):
        # The process died with this leg in flight: the honest state is UNKNOWN.
        if not _record(
            store,
            record,
            ExecutionIntentStatus.UNKNOWN,
            exchange_order_id=None,
            exchange_status=None,
            now_utc=now_utc,
        ):
            return status
        status = ExecutionIntentStatus.UNKNOWN

    answer = await _probe(adapter, record)
    if answer.found is True:
        target = ExecutionIntentStatus.ACKED
    elif answer.found is False and _protective_leg_may_be_rejected(
        store, record, now_utc=now_utc, lookup_window=lookup_window
    ):
        target = ExecutionIntentStatus.REJECTED  # a leg of a plan whose ENTRY was rejected
    else:
        # Probe failed, answer indeterminate, an ENTRY that is merely not found (D-11, Q5), a
        # leg of a live plan (F5), or an order the exchange no longer retains: absence is not
        # provable, so the intent stays UNKNOWN (T-17-33).
        return status

    if _record(
        store,
        record,
        target,
        exchange_order_id=answer.exchange_order_id,
        exchange_status=answer.exchange_status,
        now_utc=now_utc,
    ):
        return target
    return status


async def resolve_unresolved_intents(
    *,
    store: ExecutionIntentStore,
    adapter: IntentProbeAdapter,
    safe_mode_controller: SafeModeEntry,
    now_utc: datetime,
    lookup_window: timedelta = DEFAULT_LOOKUP_WINDOW,
) -> RecoveryReport:
    """Resolve every in-flight intent by query; fail closed into SAFE_MODE when one stays open.

    `now_utc` is the caller's injected UTC clock (no wall-clock read, D-26). An unreadable
    store enters SAFE_MODE(DB_FAILURE) and re-raises: "nothing to resolve" must never be
    confused with "could not look".
    """
    _require_utc(now_utc, "now_utc")
    if lookup_window <= timedelta(0):
        raise ValueError("lookup_window must be positive")

    try:
        records = tuple(store.list_unresolved_intents())
    except PersistenceError:
        safe_mode_controller.enter_safe_mode(reason=_DB_FAILURE, now_utc=now_utc)
        raise

    resolved: list[IntentOutcome] = []
    unresolved: list[IntentOutcome] = []
    for record in sorted(records, key=lambda r: (r.intended_at_utc, r.approval_id, r.role)):
        final = await _resolve_one(
            store=store,
            adapter=adapter,
            record=record,
            now_utc=now_utc,
            lookup_window=lookup_window,
        )
        outcome: IntentOutcome = (record.approval_id, record.role, final)
        if final in (ExecutionIntentStatus.ACKED, ExecutionIntentStatus.REJECTED):
            resolved.append(outcome)
        else:
            unresolved.append(outcome)

    safe_mode_entered = bool(unresolved)
    if safe_mode_entered:
        safe_mode_controller.enter_safe_mode(reason=UNRESOLVED_EXECUTION_INTENT, now_utc=now_utc)
    return RecoveryReport(
        resolved=tuple(resolved),
        unresolved=tuple(unresolved),
        safe_mode_entered=safe_mode_entered,
    )


# --------------------------------------------------------------------------- #
# The UNKNOWN ENTRY protocol (plan 20-10, T-C, D-11, D-12, Q5).
# --------------------------------------------------------------------------- #


class ReconcileReadAdapter(Protocol):
    """The two read-only snapshots the UNKNOWN-entry protocol adds to the two probes."""

    async def snapshot_positions(self, *, symbol: str) -> Any: ...

    async def snapshot_open_normal_orders(self, *, symbol: str) -> Any: ...


class UnknownEntryAdapter(IntentProbeAdapter, ReconcileReadAdapter, Protocol):
    """Probes and reads; deliberately no placement and no cancel method."""


class JournalSink(Protocol):
    """The one journal method the protocol needs."""

    def record(self, event: JournalEvent) -> None: ...


@dataclass(frozen=True)
class UnknownEntryReport:
    """What one `UnknownEntryResolver.step` did, in the store's deterministic order.

    `closed`: approval ids finalized REJECTED / RECONCILED_ABSENT. `acked`: approval ids whose
    order the exchange showed. `kept`: (approval id, fixed reason) of every ENTRY intent that is
    still UNKNOWN. `safe_mode_entered`: UNRESOLVED_EXECUTION_INTENT was entered this step.
    """

    closed: tuple[str, ...]
    acked: tuple[str, ...]
    kept: tuple[tuple[str, str], ...]
    safe_mode_entered: bool


@dataclass
class _ProbeState:
    """In-memory progress of one UNKNOWN entry; a restart starts again at zero (conservative)."""

    clean: int = 0
    last_probe_at: datetime | None = None


_CLOSED = "closed"
_ACKED = "acked"
_KEPT = "kept"


def _sorted_text(values: dict[str, str]) -> str:
    return json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _has_exposure(rows: Any, symbol: str) -> str | None:
    """None when `rows` prove no non-zero position for `symbol`, else the fixed keep reason."""
    if not isinstance(rows, (list, tuple)):
        return KEPT_READ_INDETERMINATE
    for row in rows:
        row_symbol = _read(row, "symbol")
        if not isinstance(row_symbol, str) or row_symbol == "":
            return KEPT_READ_INDETERMINATE
        if row_symbol != symbol:
            continue
        amount = _read(row, "position_amt")
        if not isinstance(amount, Decimal) or amount.is_nan():
            return KEPT_READ_INDETERMINATE
        if amount != 0:
            return KEPT_EXPOSURE_PRESENT
    return None


def _has_open_order(rows: Any, symbol: str) -> str | None:
    """None when `rows` prove no open normal order for `symbol`, else the fixed keep reason."""
    if not isinstance(rows, (list, tuple)):
        return KEPT_READ_INDETERMINATE
    for row in rows:
        row_symbol = _read(row, "symbol")
        if not isinstance(row_symbol, str) or row_symbol == "":
            return KEPT_READ_INDETERMINATE
        if row_symbol == symbol:
            return KEPT_OPEN_ORDER_PRESENT
    return None


class UnknownEntryResolver:
    """Closes an UNKNOWN ENTRY intent only on repeated, fresh, journaled Binance evidence (D-11).

    All of these must hold in one `step`, otherwise the intent stays UNKNOWN and SAFE_MODE stays:

      * `reconcile.entry_unknown_probe_count` consecutive clean `found=False` probes by client
        order id, each at least `reconcile.entry_unknown_probe_interval_ms` after the previous;
      * `entry_good_till(record) + protection.entry_unknown_grace_ms` has passed;
      * a positions read and an open-orders read for the symbol, made in this step, both succeed
        and show no non-zero position and no open order;
      * every probe and the closing evidence are journaled with the source REST_RECONCILE before
        the finalization.

    It then becomes REJECTED with `resolution_reason_code` RECONCILED_ABSENT through
    `finalize_reconciled_resolution` (never the code of a Binance rejection). Closing an intent
    never exits SAFE_MODE (D-15) and nothing is re-sent (Q5): the adapter has no placement method.
    A GTD expiry is not proof that the order is terminal; Phase 19 assumption A2 stays
    [NOT_TESTED].
    """

    def __init__(
        self,
        *,
        store: ExecutionIntentStore,
        adapter: UnknownEntryAdapter,
        journal: JournalSink,
        safe_mode_controller: SafeModeEntry,
        limits: ExecutionLimits,
        entry_good_till: Callable[[IntentRecord], datetime | None],
    ) -> None:
        count = limits.reconcile_entry_unknown_probe_count
        interval_ms = limits.reconcile_entry_unknown_probe_interval_ms
        grace_ms = limits.entry_unknown_grace_ms
        if count is None or interval_ms is None or grace_ms is None:
            wanted = (
                "reconcile.entry_unknown_probe_count",
                "reconcile.entry_unknown_probe_interval_ms",
                "protection.entry_unknown_grace_ms",
            )
            unset = set(limits.unset_keys())
            raise ExecutionLimitsNotConfigured(tuple(key for key in wanted if key in unset))
        self._store = store
        self._adapter = adapter
        self._journal = journal
        self._safe_mode = safe_mode_controller
        self._count = count
        self._interval = timedelta(milliseconds=interval_ms)
        self._grace = timedelta(milliseconds=grace_ms)
        self._entry_good_till = entry_good_till
        self._state: dict[str, _ProbeState] = {}

    async def step(self, *, now_utc: datetime) -> UnknownEntryReport:
        """One pass over every UNKNOWN ENTRY intent; `now_utc` is the caller's injected clock."""
        _require_utc(now_utc, "now_utc")
        try:
            records = tuple(self._store.list_unresolved_intents())
        except PersistenceError:
            self._safe_mode.enter_safe_mode(reason=_DB_FAILURE, now_utc=now_utc)
            raise

        candidates = sorted(
            (
                r
                for r in records
                if r.role == _ENTRY_ROLE and r.intent_status == ExecutionIntentStatus.UNKNOWN
            ),
            key=lambda r: (r.intended_at_utc, r.approval_id),
        )
        live = {r.approval_id for r in candidates}
        for approval_id in [a for a in self._state if a not in live]:
            del self._state[approval_id]

        closed: list[str] = []
        acked: list[str] = []
        kept: list[tuple[str, str]] = []
        for record in candidates:
            kind, reason = await self._step_one(record, now_utc)
            if kind == _CLOSED:
                closed.append(record.approval_id)
            elif kind == _ACKED:
                acked.append(record.approval_id)
            else:
                kept.append((record.approval_id, reason))

        safe_mode_entered = bool(kept)
        if safe_mode_entered:
            self._safe_mode.enter_safe_mode(reason=UNRESOLVED_EXECUTION_INTENT, now_utc=now_utc)
        return UnknownEntryReport(
            closed=tuple(closed),
            acked=tuple(acked),
            kept=tuple(kept),
            safe_mode_entered=safe_mode_entered,
        )

    async def _step_one(self, record: IntentRecord, now_utc: datetime) -> tuple[str, str]:
        state = self._state.setdefault(record.approval_id, _ProbeState())
        if state.last_probe_at is not None and now_utc - state.last_probe_at < self._interval:
            return _KEPT, KEPT_NOT_DUE
        state.last_probe_at = now_utc

        answer = await _probe(self._adapter, record)  # never raises
        if answer.found is None:
            return self._keep(record, state, KEPT_PROBE_INDETERMINATE, now_utc)
        if answer.found is True:
            return self._ack(record, answer, state, now_utc)

        state.clean += 1
        if not self._journal_ok(lambda: self._probe_event(record, state.clean, now_utc)):
            state.clean = 0
            return _KEPT, KEPT_JOURNAL_FAILED
        if state.clean < self._count:
            return _KEPT, KEPT_PROBES_PENDING
        good_till = self._good_till(record)
        if good_till is None:
            return _KEPT, KEPT_GTD_UNKNOWN
        if now_utc < good_till + self._grace:
            return _KEPT, KEPT_GTD_GRACE_NOT_PASSED

        # Fresh reads in this step: exposure and resting orders for the symbol. A failed read is
        # never "flat": the count restarts and the intent stays UNKNOWN.
        try:
            positions = await self._adapter.snapshot_positions(symbol=record.symbol)
            orders = await self._adapter.snapshot_open_normal_orders(symbol=record.symbol)
        except Exception:  # noqa: BLE001 - an unreadable exchange state is never evidence
            return self._keep(record, state, KEPT_READ_FAILED, now_utc)
        blocked = _has_exposure(positions, record.symbol) or _has_open_order(orders, record.symbol)
        if blocked is not None:
            return self._keep(record, state, blocked, now_utc)

        # The evidence row precedes the finalization: no row, no close (T-20-23).
        if not self._journal_ok(lambda: self._exit_event(record, "REJECTED", now_utc)):
            state.clean = 0
            return _KEPT, KEPT_JOURNAL_FAILED
        try:
            self._store.finalize_reconciled_resolution(
                approval_id=record.approval_id,
                role=record.role,
                reason_code=RESOLUTION_RECONCILED_ABSENT,
                now_utc=now_utc,
            )
        except PersistenceError:
            state.clean = 0
            return _KEPT, KEPT_STORE_FAILED
        del self._state[record.approval_id]
        return _CLOSED, RESOLUTION_RECONCILED_ABSENT

    def _good_till(self, record: IntentRecord) -> datetime | None:
        """The entry's GTD time, or None when it is missing, naive or not UTC (fail closed)."""
        try:
            value = self._entry_good_till(record)
        except Exception:  # noqa: BLE001 - an unknown GTD time keeps the intent UNKNOWN
            return None
        if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
            return None
        return value

    def _keep(
        self, record: IntentRecord, state: _ProbeState, reason: str, now_utc: datetime
    ) -> tuple[str, str]:
        """Keep the intent UNKNOWN: the count restarts and the reason is journaled (best effort)."""
        state.clean = 0
        self._journal_ok(lambda: self._kept_event(record, reason, now_utc))
        return _KEPT, reason

    def _journal_ok(self, build: Callable[[], JournalEvent]) -> bool:
        """Record one journal event; False when it could not be built or written."""
        try:
            self._journal.record(build())
        except Exception:  # noqa: BLE001 - a row that is not journaled is not evidence
            return False
        return True

    def _ack(
        self, record: IntentRecord, answer: _Probe, state: _ProbeState, now_utc: datetime
    ) -> tuple[str, str]:
        if not self._journal_ok(lambda: self._exit_event(record, "ACKED", now_utc)):
            state.clean = 0
            return _KEPT, KEPT_JOURNAL_FAILED
        if not _record(
            self._store,
            record,
            ExecutionIntentStatus.ACKED,
            exchange_order_id=answer.exchange_order_id,
            exchange_status=answer.exchange_status,
            now_utc=now_utc,
        ):
            state.clean = 0
            return _KEPT, KEPT_STORE_FAILED
        self._state.pop(record.approval_id, None)
        return _ACKED, "ACKED"

    @staticmethod
    def _correlation(record: IntentRecord) -> str:
        return f"{_CORRELATION_PREFIX}{record.approval_id}"

    def _probe_event(self, record: IntentRecord, probe_no: int, now_utc: datetime) -> JournalEvent:
        body = _sorted_text(
            {
                "approval_id": record.approval_id,
                "evidence_source": EvidenceSource.REST_RECONCILE.value,
                "probe_no": str(probe_no),
                "result": "NOT_FOUND",
                "role": record.role,
            }
        )
        return JournalEvent(
            journal_event_id=content_hash_event_id(
                prefix=_PROBE_ID_PREFIX,
                event_type=EVENT_UNKNOWN_ENTRY_PROBE,
                entity_id=record.approval_id,
                occurred_at_utc=now_utc,
                payload_json=body,
            ),
            occurred_at_utc=now_utc,
            event_type=EVENT_UNKNOWN_ENTRY_PROBE,
            entity_type=_INTENT_ENTITY,
            entity_id=record.approval_id,
            correlation_id=self._correlation(record),
            approval_id=record.approval_id,
            payload_json=body,
            created_at_utc=now_utc,
        )

    def _kept_event(self, record: IntentRecord, reason: str, now_utc: datetime) -> JournalEvent:
        body = _sorted_text(
            {"approval_id": record.approval_id, "reason": reason, "role": record.role}
        )
        return JournalEvent(
            journal_event_id=content_hash_event_id(
                prefix=_KEPT_ID_PREFIX,
                event_type=EVENT_UNKNOWN_ENTRY_KEPT,
                entity_id=record.approval_id,
                occurred_at_utc=now_utc,
                payload_json=body,
            ),
            occurred_at_utc=now_utc,
            event_type=EVENT_UNKNOWN_ENTRY_KEPT,
            entity_type=_INTENT_ENTITY,
            entity_id=record.approval_id,
            correlation_id=self._correlation(record),
            approval_id=record.approval_id,
            payload_json=body,
            created_at_utc=now_utc,
        )

    def _exit_event(self, record: IntentRecord, to_status: str, now_utc: datetime) -> JournalEvent:
        reference = record.client_order_id
        if reference is None:  # unreachable: a probe needs the id
            raise ValueError("an UNKNOWN entry without a client order id cannot be closed")
        event = exit_evidence_event(
            entity_type=_INTENT_ENTITY,
            entity_id=record.approval_id,
            from_status="UNKNOWN",
            to_status=to_status,
            evidence=ExitEvidence(
                source=EvidenceSource.REST_RECONCILE,
                observed_at_utc=now_utc,
                reference=reference,
                correlation_id=self._correlation(record),
            ),
            now_utc=now_utc,
        )
        # 20-REVIEW WR-A1: `exit_evidence_event` keys the row on (correlation, type, entity,
        # transition) only, while the observation time sits in `payload_json`, which the journal
        # treats as identity. A retry after a failed finalize write (or a crash between the two
        # writes) therefore rebuilt the same id with a new time and raised JournalConflict on
        # every later step, so the entry could never leave UNKNOWN. Each observation is its own
        # append-only row: the id is a content hash over the observation, and the same
        # observation replayed is still one row.
        return replace(
            event,
            journal_event_id=content_hash_event_id(
                prefix=EXIT_EVIDENCE_PREFIX,
                event_type=event.event_type,
                entity_id=event.entity_id,
                occurred_at_utc=now_utc,
                payload_json=event.payload_json,
            ),
        )
