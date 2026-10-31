"""Scheduled cancel of an unfilled entry past its plan expiry (plan 24-21; D-13, 20-DEFERRED).

Demo kept a GTD entry NEW 840 s past its goodTillDate, and `expire_pending_entry` had no scheduled
caller, so an entry could fill hours after its plan expired. `cancel_expired_entries_once` is the
scheduler task body (cadence: the reconcile tick, `LiveCadences.scheduled_cancel_check`).

For every plan the coordinator still holds in AWAITING_FILL:

  1. the stored plan expiry is read through the plan store port; before it nothing else happens
     (no REST call). A missing or unreadable expiry cancels nothing and is journaled;
  2. a FRESH REST read of the entry by its deterministic client id. Only a resting entry (status
     NEW) with an executed quantity of exactly zero is cancelled. A partial or full fill, an
     unknown executed quantity, an entry the exchange does not find and a status outside the known
     set are left to the protection coordinator and journaled (it owns every exposure);
  3. the one cancel is `expire_pending_entry` with the canonical trigger `expiry_time`; it acts
     first, verifies by a query afterwards and journals its own pre and post images.

Never touched: the protective legs. The module names no leg-cancel and no placement call. There is
no retry and no loop around the cancel: a failed cancel is journaled by exception class and the
next scheduled run looks again. Nothing here raises for an exchange or store failure (a
`BaseException` still propagates); only the exception CLASS NAME is ever kept, because an SDK error
text can carry a signed URL and the journal is append-only.

The clock is injected (`now_utc`); no wall clock is read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

import structlog

from src.domain.enums import OrderRole
from src.domain.journal import JournalEvent, correlated_event_id
from src.execution.cancel_verification import CancelVerdict
from src.execution.manager import ExecutionAdapter, expire_pending_entry
from src.execution.order_ids import derive_client_order_id
from src.execution.protection import PlanProtection, ProtectionState

log = structlog.get_logger(__name__)

EVENT_SCHEDULED_CANCEL = "LIVE_SCHEDULED_CANCEL"
TRIGGER_EXPIRY_TIME = "expiry_time"

OUTCOME_CANCELED = "canceled"
OUTCOME_CANCEL_UNVERIFIED = "cancel_unverified"
OUTCOME_CANCEL_FAILED = "cancel_failed"
OUTCOME_LEFT_TO_COORDINATOR = "left_to_coordinator"
OUTCOME_READ_FAILED = "read_failed"
OUTCOME_EXPIRY_UNKNOWN = "expiry_unknown"
OUTCOME_NOT_RESTING = "not_resting"

REASON_EXECUTED = "executed"
REASON_QUANTITY_UNKNOWN = "quantity_unknown"
REASON_NOT_FOUND = "not_found"
REASON_STATUS_UNEXPECTED = "status_unexpected"
REASON_NO_EXPIRY = "no_expiry"

_JOURNAL_PREFIX = "live-scheduled-cancel"
_ENTITY_TYPE = "LiveScheduledCancel"
_RESTING_STATUS = "NEW"
_ENDED_WITHOUT_FILL: frozenset[str] = frozenset(
    {"CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"}
)
_ZERO = Decimal("0")


class CoordinatorView(Protocol):
    """What the task reads of the protection coordinator: its plans."""

    def protections(self) -> tuple[PlanProtection, ...]: ...


class PlanStore(Protocol):
    """The stored plan expiry by plan hash (the composition root wraps its store in an executor)."""

    async def expiry_utc_for(self, plan_hash: str) -> datetime | None: ...


class JournalWriter(Protocol):
    """The append-only journal surface (`record`)."""

    def record(self, event: JournalEvent) -> None: ...


@dataclass(frozen=True, kw_only=True)
class ScheduledCancelResult:
    """What one examined plan came to. `detail` is a reason code or an exception class name."""

    plan_hash: str
    symbol: str
    outcome: str
    detail: str | None = None
    verdict: CancelVerdict | None = None


def _require_utc(value: object, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


async def cancel_expired_entries_once(
    *,
    coordinator: CoordinatorView,
    plan_store: PlanStore,
    adapter: ExecutionAdapter,
    journal: JournalWriter,
    spill: Any,
    now_utc: datetime,
) -> tuple[ScheduledCancelResult, ...]:
    """Run the scheduled check once; returns one result per plan examined after its expiry."""
    _require_utc(now_utc, "now_utc")
    results: list[ScheduledCancelResult] = []
    for protection in coordinator.protections():
        if protection.state is not ProtectionState.AWAITING_FILL:
            continue
        result = await _check_plan(
            protection,
            plan_store=plan_store,
            adapter=adapter,
            journal=journal,
            spill=spill,
            now_utc=now_utc,
        )
        if result is not None:
            results.append(result)
    return tuple(results)


async def _check_plan(
    protection: PlanProtection,
    *,
    plan_store: PlanStore,
    adapter: ExecutionAdapter,
    journal: JournalWriter,
    spill: Any,
    now_utc: datetime,
) -> ScheduledCancelResult | None:
    plan_hash, symbol = protection.plan_hash, protection.symbol
    entry_id = derive_client_order_id(plan_hash=plan_hash, role=OrderRole.ENTRY.value)

    def result(
        outcome: str, detail: str | None = None, verdict: CancelVerdict | None = None
    ) -> ScheduledCancelResult:
        return ScheduledCancelResult(
            plan_hash=plan_hash, symbol=symbol, outcome=outcome, detail=detail, verdict=verdict
        )

    try:
        expiry = await plan_store.expiry_utc_for(plan_hash)
    except Exception as exc:  # noqa: BLE001 - a store failure cancels nothing; class name only
        _journal(
            journal, protection, now_utc, OUTCOME_EXPIRY_UNKNOWN, error_class=type(exc).__name__
        )
        return result(OUTCOME_EXPIRY_UNKNOWN, type(exc).__name__)
    if expiry is None:
        _journal(journal, protection, now_utc, OUTCOME_EXPIRY_UNKNOWN, reason=REASON_NO_EXPIRY)
        return result(OUTCOME_EXPIRY_UNKNOWN, REASON_NO_EXPIRY)
    if now_utc < expiry:
        return None

    try:
        probe = await adapter.query_order_by_client(symbol=symbol, orig_client_order_id=entry_id)
    except Exception as exc:  # noqa: BLE001 - an unreadable order is never cancelled blind
        _journal(journal, protection, now_utc, OUTCOME_READ_FAILED, error_class=type(exc).__name__)
        return result(OUTCOME_READ_FAILED, type(exc).__name__)

    left = _left_reason(probe)
    if left == OUTCOME_NOT_RESTING:
        return result(OUTCOME_NOT_RESTING)
    if left is not None:
        _journal(journal, protection, now_utc, OUTCOME_LEFT_TO_COORDINATOR, reason=left)
        return result(OUTCOME_LEFT_TO_COORDINATOR, left)

    try:
        verdict = await expire_pending_entry(
            plan_hash=plan_hash,
            symbol=symbol,
            adapter=adapter,
            journal=journal,
            now_utc=now_utc,
            trigger_reason=TRIGGER_EXPIRY_TIME,
            spill=spill,
        )
    except Exception as exc:  # noqa: BLE001 - recorded by class; the next run looks again
        _journal(
            journal, protection, now_utc, OUTCOME_CANCEL_FAILED, error_class=type(exc).__name__
        )
        return result(OUTCOME_CANCEL_FAILED, type(exc).__name__)
    if verdict is CancelVerdict.CANCELED:
        return result(OUTCOME_CANCELED, verdict=verdict)
    # The manager already journaled `cancel_unverified` with the verdict; a filled entry
    # (FILLED_OR_PARTIAL) is the coordinator's exposure.
    return result(OUTCOME_CANCEL_UNVERIFIED, verdict.value, verdict)


def _left_reason(probe: Any) -> str | None:
    """None when the entry rests with zero executed quantity; else why it is not cancelled.

    Returns `OUTCOME_NOT_RESTING` for an entry that already ended with no fill (nothing to do and
    nothing to journal: the coordinator journals its own transition).
    """
    if getattr(probe, "found", None) is not True:
        return REASON_NOT_FOUND
    executed = getattr(probe, "executed_quantity", None)
    status = _text(getattr(probe, "status", None))
    if isinstance(executed, Decimal) and executed > _ZERO:
        return REASON_EXECUTED
    if status in ("PARTIALLY_FILLED", "FILLED"):
        return REASON_EXECUTED
    if not isinstance(executed, Decimal):
        return REASON_QUANTITY_UNKNOWN
    if status in _ENDED_WITHOUT_FILL:
        return OUTCOME_NOT_RESTING
    if status != _RESTING_STATUS:
        return REASON_STATUS_UNEXPECTED
    return None


def _journal(
    journal: JournalWriter,
    protection: PlanProtection,
    now_utc: datetime,
    outcome: str,
    *,
    reason: str | None = None,
    error_class: str | None = None,
) -> None:
    """Append one row; the id is fixed per plan, outcome and detail (a repeat is a no-op)."""
    payload: dict[str, str] = {"outcome": outcome, "symbol": protection.symbol}
    if reason is not None:
        payload["reason"] = reason
    if error_class is not None:
        payload["error_class"] = error_class
    correlation = f"{_JOURNAL_PREFIX}:{protection.plan_hash}"
    try:
        journal.record(
            JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix=_JOURNAL_PREFIX,
                    correlation_id=correlation,
                    event_type=EVENT_SCHEDULED_CANCEL,
                    entity_id=protection.plan_hash,
                    step=f"{outcome}:{reason or error_class or '-'}",
                ),
                occurred_at_utc=now_utc,
                event_type=EVENT_SCHEDULED_CANCEL,
                entity_type=_ENTITY_TYPE,
                entity_id=protection.plan_hash,
                correlation_id=correlation,
                payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            )
        )
    except Exception as exc:  # noqa: BLE001 - an audit row must not stop the task
        log.warning("live.scheduled_cancel.journal_failed", error_class=type(exc).__name__)


__all__ = [
    "EVENT_SCHEDULED_CANCEL",
    "OUTCOME_CANCELED",
    "OUTCOME_CANCEL_FAILED",
    "OUTCOME_CANCEL_UNVERIFIED",
    "OUTCOME_EXPIRY_UNKNOWN",
    "OUTCOME_LEFT_TO_COORDINATOR",
    "OUTCOME_NOT_RESTING",
    "OUTCOME_READ_FAILED",
    "CoordinatorView",
    "PlanStore",
    "ScheduledCancelResult",
    "cancel_expired_entries_once",
]
