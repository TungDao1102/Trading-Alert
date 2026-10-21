"""Pending protective actions: the durable INTENT of an action the REST gate refused (D-19, Q4).

Phase 20, plan 20-14. When the REST gate refuses a protective stop, an entry-remainder cancel
or an emergency close (HTTP 418 ban, 429 pause, a gate that is not restored), nothing reaches
the exchange. Until now that was a journal row and the coordinator's in-memory retry; after a
restart the intent was gone. A ``PendingAction`` is the explicit, durable record of "this action
was not sent".

What a pending action is NOT (D-19, threat T-20-34):

* It is **not a payload**. It has no price, quantity or side. When sending is allowed again the
  coordinator's ordinary step reads the CURRENT exchange state and decides from the plan; an old
  request is never replayed blindly.
* It is **not a bypass**. The gate is not asked for an exemption (D-18); a refusal is recorded,
  not worked around.
* It is **not protection**. While the exchange forbids sending, the position has no stop that
  this record could place; the plan stays in its blocking state and nothing here claims that a
  position always has a stop under every rate-limit condition.

A row is open (``PENDING``) until it is ``RESOLVED`` (the action got through, or it became moot
because the exchange state settled) or ``SUPERSEDED`` (policy now requires a close, so a queued
stop is never sent: ``CLOSE_REQUIRED_BY_POLICY``). There is at most one open row per
``(plan_hash, kind)``; a re-block of the same action bumps the open row (``block_count``).

The restart LOAD of open rows is plan 20-19; the queue ORDER once the gate opens is plan 20-21
(D-20).

Purity: stdlib and ``src.domain`` only; no clock is read (``now_utc`` is always passed in), no
float, no SDK, no network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from src.domain.journal import JournalEvent, content_hash_event_id

# The journal event type of the spilled intent (a spill record is replayed into the journal).
EVENT_PENDING_ACTION_BLOCKED = "PENDING_PROTECTIVE_ACTION_BLOCKED"
ENTITY_TYPE_PENDING_ACTION = "PendingProtectiveAction"

# Fixed project text for the resolution notes (never exchange text).
NOTE_STOP_CONFIRMED_ACTIVE = "STOP_CONFIRMED_ACTIVE"
NOTE_ENTRY_CANCEL_ACCEPTED = "ENTRY_CANCEL_ACCEPTED"
NOTE_ENTRY_TERMINAL = "ENTRY_TERMINAL"
NOTE_CLOSE_SENT_AFTER_GATE = "CLOSE_SENT_AFTER_GATE"
NOTE_CLOSE_CONFIRMED_FLAT = "CLOSE_CONFIRMED_FLAT"
NOTE_PLAN_FLAT = "PLAN_FLAT"
NOTE_CLOSE_REQUIRED_BY_POLICY = "CLOSE_REQUIRED_BY_POLICY"
NOTE_CLOSE_FAILED_BY_POLICY = "CLOSE_FAILED_BY_POLICY"

#: What a gate reason or a note may look like: fixed upper-case project text, at most 64 characters.
_TEXT_PATTERN = re.compile(r"[A-Za-z0-9_]{1,64}")
UNSPECIFIED_REFUSAL = "UNSPECIFIED_REFUSAL"
_ID_PREFIX = "ppa"


class PendingKind(StrEnum):
    """Which refused action a pending row stands for (the three states of D-19)."""

    STOP_NOT_SENT = "STOP_NOT_SENT"
    PROTECTION_ENTRY_CANCEL_NOT_SENT = "PROTECTION_ENTRY_CANCEL_NOT_SENT"
    CLOSE_NOT_SENT = "CLOSE_NOT_SENT"


class PendingState(StrEnum):
    """Lifecycle of a pending row: open, then exactly one of the two terminal states."""

    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"


def gate_reason_text(raw: object) -> str:
    """The refusal reason as safe project text, or ``UNSPECIFIED_REFUSAL``.

    A gate reason is a fixed constant (``IP_BAN_418``, ``RATE_LIMIT_PAUSE_429``,
    ``GATE_NOT_RESTORED``, ...) or an exception class name. Anything else (empty, too long,
    punctuation) is replaced, so no free text can reach the table.
    """
    if isinstance(raw, str) and _TEXT_PATTERN.fullmatch(raw) is not None:
        return raw
    return UNSPECIFIED_REFUSAL


def pending_id_for(plan_hash: str, kind: PendingKind, *, opened_at_utc: datetime) -> str:
    """Deterministic id of one pending episode: a content hash of plan, kind and opening time.

    The opening time makes a re-block after a resolution a NEW row (the primary key never
    collides with the closed one), while the same episode always maps to the same id.
    """
    if not isinstance(kind, PendingKind):
        raise ValueError(f"kind must be a PendingKind, got {type(kind).__name__}")
    return content_hash_event_id(
        prefix=_ID_PREFIX,
        event_type=kind.value,
        entity_id=plan_hash,
        occurred_at_utc=opened_at_utc,
        payload_json="{}",
    )


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")


def _require_utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be UTC-aware, got a naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC, got offset {value.utcoffset()}")
    return value


@dataclass(frozen=True)
class PendingAction:
    """One refused protective action (intent only: no price, quantity or side field exists)."""

    pending_id: str
    plan_hash: str
    trade_plan_id: str
    approval_id: str
    symbol: str
    kind: PendingKind
    state: PendingState
    gate_reason: str
    first_blocked_at_utc: datetime
    last_blocked_at_utc: datetime
    block_count: int
    retry_after_until_utc: datetime | None
    resolved_at_utc: datetime | None
    resolution_note: str | None

    def __post_init__(self) -> None:
        for name in ("pending_id", "plan_hash", "trade_plan_id", "approval_id", "symbol"):
            _require_text(getattr(self, name), name)
        if not isinstance(self.kind, PendingKind):
            raise ValueError(f"kind must be a PendingKind, got {type(self.kind).__name__}")
        if not isinstance(self.state, PendingState):
            raise ValueError(f"state must be a PendingState, got {type(self.state).__name__}")
        if not isinstance(self.gate_reason, str) or not _TEXT_PATTERN.fullmatch(self.gate_reason):
            raise ValueError("gate_reason must be fixed project text (letters, digits, underscore)")
        first = _require_utc(self.first_blocked_at_utc, "first_blocked_at_utc")
        last = _require_utc(self.last_blocked_at_utc, "last_blocked_at_utc")
        if last < first:
            raise ValueError("last_blocked_at_utc must not be earlier than first_blocked_at_utc")
        if (
            isinstance(self.block_count, bool)
            or not isinstance(self.block_count, int)
            or self.block_count < 1
        ):
            raise ValueError("block_count must be an int >= 1")
        if self.retry_after_until_utc is not None:
            _require_utc(self.retry_after_until_utc, "retry_after_until_utc")
        if self.state is PendingState.PENDING:
            if self.resolved_at_utc is not None or self.resolution_note is not None:
                raise ValueError("an open pending action has no resolution time or note")
        else:
            if self.resolved_at_utc is None or self.resolution_note is None:
                raise ValueError("a closed pending action needs a resolution time and a note")
            _require_utc(self.resolved_at_utc, "resolved_at_utc")
            if not _TEXT_PATTERN.fullmatch(self.resolution_note):
                raise ValueError("resolution_note must be fixed project text")


class PendingActionStore(Protocol):
    """The durable store of pending protective actions (PostgreSQL in production)."""

    def record_blocked(
        self,
        *,
        plan_hash: str,
        trade_plan_id: str,
        approval_id: str,
        symbol: str,
        kind: PendingKind,
        gate_reason: str,
        retry_after_until_utc: datetime | None,
        now_utc: datetime,
    ) -> PendingAction:
        """Insert the open row of ``(plan_hash, kind)`` or bump it (count, last time, reason)."""
        ...

    def resolve(
        self, *, plan_hash: str, kind: PendingKind, note: str, now_utc: datetime
    ) -> PendingAction | None:
        """Close the open row as RESOLVED; None when no row is open."""
        ...

    def supersede(
        self, *, plan_hash: str, kind: PendingKind, note: str, now_utc: datetime
    ) -> PendingAction | None:
        """Close the open row as SUPERSEDED (never to be sent); None when no row is open."""
        ...

    def list_open(self) -> tuple[PendingAction, ...]:
        """Every PENDING row, ordered by ``(first_blocked_at_utc, pending_id)``."""
        ...


class IntentSpill(Protocol):
    """The one method of ``src.ops.spill.LocalSpill`` this module's callers use.

    Declared here so ``src.execution`` does not import ``src.ops`` (the dependency runs the
    other way); ``LocalSpill`` satisfies it structurally.
    """

    def write(self, event: JournalEvent) -> object: ...


def intent_event(
    *,
    plan_hash: str,
    trade_plan_id: str,
    approval_id: str,
    symbol: str,
    kind: PendingKind,
    gate_reason: str,
    now_utc: datetime,
) -> JournalEvent:
    """The journal-shaped record of a refused action's intent, for the local spill (D-16).

    The payload names the kind and the gate reason only: no price, quantity or side.
    """
    body = json.dumps(
        {
            "gate_reason": gate_reason,
            "pending_kind": kind.value,
            "symbol": symbol,
            "trade_plan_id": trade_plan_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix=_ID_PREFIX,
            event_type=EVENT_PENDING_ACTION_BLOCKED,
            entity_id=plan_hash,
            occurred_at_utc=now_utc,
            payload_json=body,
        ),
        occurred_at_utc=now_utc,
        event_type=EVENT_PENDING_ACTION_BLOCKED,
        entity_type=ENTITY_TYPE_PENDING_ACTION,
        entity_id=plan_hash,
        correlation_id=f"pending_action_{plan_hash}",
        trade_plan_id=trade_plan_id,
        approval_id=approval_id,
        payload_json=body,
    )


class BlockedRecorder:
    """Spill first, then record: the shared write path of the coordinator and the closer.

    ``record`` writes the intent to the local spill (once per open episode of a
    ``(plan_hash, kind)``, so a long ban does not create a file per step), then asks the store
    to insert or bump the open row. A spill failure is swallowed (the store row is the durable
    record, the spill is the fallback). It returns False when the STORE failed, so the caller
    can enter SAFE_MODE DB_FAILURE once and carry on: a store outage never blocks the
    protective flow (D-16, T-20-35). With neither store nor spill attached it does nothing.
    """

    def __init__(self, store: PendingActionStore | None, spill: IntentSpill | None) -> None:
        self._store = store
        self._spill = spill
        self._spilled: set[tuple[str, PendingKind]] = set()

    @property
    def active(self) -> bool:
        return self._store is not None or self._spill is not None

    def record(
        self,
        *,
        plan_hash: str,
        trade_plan_id: str,
        approval_id: str,
        symbol: str,
        kind: PendingKind,
        gate_reason: str,
        retry_after_until_utc: datetime | None,
        now_utc: datetime,
    ) -> bool:
        key = (plan_hash, kind)
        if self._spill is not None and key not in self._spilled:
            try:
                self._spill.write(
                    intent_event(
                        plan_hash=plan_hash,
                        trade_plan_id=trade_plan_id,
                        approval_id=approval_id,
                        symbol=symbol,
                        kind=kind,
                        gate_reason=gate_reason,
                        now_utc=now_utc,
                    )
                )
                self._spilled.add(key)
            except Exception:  # noqa: BLE001, S110 - the store row below is the durable record
                pass
        if self._store is None:
            return True
        try:
            self._store.record_blocked(
                plan_hash=plan_hash,
                trade_plan_id=trade_plan_id,
                approval_id=approval_id,
                symbol=symbol,
                kind=kind,
                gate_reason=gate_reason,
                retry_after_until_utc=retry_after_until_utc,
                now_utc=now_utc,
            )
        except Exception:  # noqa: BLE001 - any store failure is fail-closed, never a skipped step
            return False
        return True

    def forget(self, plan_hash: str, kind: PendingKind) -> None:
        """The episode ended: the next block of this action spills again."""
        self._spilled.discard((plan_hash, kind))


def retry_after_until(now_utc: datetime, retry_after_seconds: object) -> datetime | None:
    """``now + retry_after`` for a non-negative whole number of seconds, else None."""
    if (
        isinstance(retry_after_seconds, int)
        and not isinstance(retry_after_seconds, bool)
        and retry_after_seconds >= 0
    ):
        return now_utc + timedelta(seconds=retry_after_seconds)
    return None


__all__ = [
    "ENTITY_TYPE_PENDING_ACTION",
    "EVENT_PENDING_ACTION_BLOCKED",
    "NOTE_CLOSE_CONFIRMED_FLAT",
    "NOTE_CLOSE_FAILED_BY_POLICY",
    "NOTE_CLOSE_REQUIRED_BY_POLICY",
    "NOTE_CLOSE_SENT_AFTER_GATE",
    "NOTE_ENTRY_CANCEL_ACCEPTED",
    "NOTE_ENTRY_TERMINAL",
    "NOTE_PLAN_FLAT",
    "NOTE_STOP_CONFIRMED_ACTIVE",
    "UNSPECIFIED_REFUSAL",
    "BlockedRecorder",
    "IntentSpill",
    "PendingAction",
    "PendingActionStore",
    "PendingKind",
    "PendingState",
    "gate_reason_text",
    "intent_event",
    "pending_id_for",
    "retry_after_until",
]
