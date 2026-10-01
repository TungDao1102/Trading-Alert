"""Restart recovery of in-flight execution intents (Phase 17-12, D-14, F-703).

A process that dies between the write-ahead steps leaves intents INTENDED or SENT whose
exchange state is unknown. On restart this module LEARNS, it never ACTS:

  1. every INTENDED / SENT intent is first recorded UNKNOWN (the honest state: the order
     may or may not exist);
  2. every unresolved intent is probed by its deterministic client id only
     (`query_order_by_client` for the ENTRY leg, `query_algo_order_by_client` for the
     protective legs) and resolved:

       found                                       -> ACKED (with the exchange order id)
       definitively absent AND intended < window   -> REJECTED
       probe error, indeterminate answer, or an
       absent order older than the window          -> stays UNKNOWN

  3. when any intent stays UNKNOWN, SAFE_MODE is entered once with reason
     `UNRESOLVED_EXECUTION_INTENT` (GLOSSARY 9.4), so no new entry is placed. Leaving
     SAFE_MODE stays with the Phase 20 reconciler (D-14).

Placement is structurally impossible here: the adapter parameter is the two-method
`IntentProbeAdapter` Protocol below, which has no order-placement method, and a retried
send after a restart is exactly the double entry the write-ahead rows exist to prevent
(research Pitfall 11, F-703, T-17-31).

The 3-day default window comes from Binance Query Order retention: an order that was
canceled or expired without a fill and is older than 3 days is no longer returned, so
"not found" is a definitive absence only for younger intents. It is a keyword argument so
a documented change in the exchange rule is a one-line edit at the call site.

Imports: stdlib, `src.domain`, `src.execution` and the pure-Python `src.persistence.errors`
(the same typed failures the manager catches); no SQLAlchemy. The resolver is a tested
function, not wired into a live process (Phase 20 and Phase 24 own the wiring).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.execution.intent_store import ExecutionIntentStore, IntentRecord
from src.persistence.errors import PersistenceError

# SAFE_MODE entry reasons (GLOSSARY 9.4).
UNRESOLVED_EXECUTION_INTENT = "UNRESOLVED_EXECUTION_INTENT"
_DB_FAILURE = "DB_FAILURE"

# Binance Query Order: a canceled or expired order with no fills older than 3 days is not
# returned (docs, Query Order "orders not found" rules; research Pitfall 11).
DEFAULT_LOOKUP_WINDOW = timedelta(days=3)

_ENTRY_ROLE = OrderRole.ENTRY.value

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
    elif answer.found is False and now_utc - record.intended_at_utc < lookup_window:
        target = ExecutionIntentStatus.REJECTED  # definitive absence of a young intent
    else:
        # Probe failed, answer indeterminate, or the exchange no longer retains the
        # order: absence is not provable, so the intent stays UNKNOWN (T-17-33).
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
