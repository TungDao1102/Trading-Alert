"""Rebuild of one plan's protection state after a restart (Phase 20, plan 20-19; D-08, D-30, D077).

Pure module: standard library, ``src.domain``, ``src.execution.protection_replay`` and the
``RestingEntry`` / ``ProtectionState`` types of ``src.execution.protection``. No clock, no I/O, no
float, no adapter call. The caller (Phase 24 wiring, plan 20-19 ``run_startup_recovery``) reads
the durable sources and passes them in; this module only decides what they prove.

What a rebuild may and may not do (D-08, G4-029 logic):

* The journaled ``PROTECTION_TRANSITION`` rows are validated by ``replay_transitions``, the same
  guard the live coordinator uses. The journal alone is NOT the source of truth: it is read
  together with the STOP_LOSS intent row and the local spill, and Binance verifies the result on
  the first ordinary step.
* No clock restarts. ``stop_lost_at`` is the ``occurred_at_utc`` of the first ``STOP_LOST*``
  transition, ``first_fill_at`` the first ``FIRST_FILL_*`` transition (else the STOP_LOSS intent's
  ``intended_at_utc``). Nothing is read from a clock here; when no durable time exists the plan's
  own ``registered_at_utc`` is used.
* A stop is never re-placed on a guess (D077, T-20-69). The coordinator may place a stop again,
  under the same deterministic id, only for a stop that was NEVER confirmed. "Never confirmed" is
  an established fact only when the journal proves it: the replay is valid, the rows are
  contiguous from seq 1 (``replay_transitions`` enforces both), no row carries the evidence
  ``REST_STOP_CONFIRMED``, the spill was readable and holds no protection-correlation record the
  journal lacks, and the STOP_LOSS intent row agrees with the rows (see ``_intent_contradicts``).
  Anything else is an UNKNOWN stop history: the plan is restored ``UNPROTECTED`` with
  ``stop_history_known`` False, reason ``STOP_HISTORY_UNKNOWN`` and ``stop_lost_at`` set to the
  earliest durable time of the plan, so the coordinator's existing stop-lost handling (D077)
  applies: the stop is never read, placed or trusted, every step decides by the position, and
  ``max_unprotected_ms`` escalates from that time.
* A corrupt or invalid replay fails closed the same way (``replay_valid`` False): nothing is
  silently discarded.
* A plan whose durable data shows it already past the point where a stop matters
  (``CLOSE_REQUIRED``, ``CLOSE_FAILED``, ``FLAT``, ``ENTRY_ENDED_NO_FILL``) keeps that state even
  when its stop history is unknown; a blocking state is never downgraded.

Known limit (recorded, not hidden): the coordinator does not spill its ``PROTECTION_TRANSITION``
rows when the journal is down (only operator audit rows and pending-action intents reach the
spill), so a transition row lost to a journal outage is detected only through the STOP_LOSS
intent row and the spill records checked here, not through the spill alone.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.domain.enums import ExecutionIntentStatus
from src.domain.journal import JournalEvent
from src.execution.intent_store import IntentRecord
from src.execution.protection import (
    EVENT_PROTECTION_TRANSITION,
    REASON_CLOSED_ENTRY_TERMINAL,
    REASON_ENTRY_ENDED_NO_FILL,
    REASON_ENTRY_TERMINAL,
    REASON_FIRST_FILL_REST,
    REASON_FIRST_FILL_STREAM,
    REASON_STOP_CONFIRMED_ENTRY_TERMINAL,
    ProtectionState,
    RestingEntry,
)
from src.execution.protection_replay import (
    EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL,
    EVIDENCE_REST_STOP_CONFIRMED,
    REASON_STOP_LOST,
    REASON_STOP_LOST_AFTER_PROTECTED,
    ProtectionReplayInvalid,
    replay_transitions,
)

# The reason a plan is restored with when its stop history cannot be established.
REASON_STOP_HISTORY_UNKNOWN = "STOP_HISTORY_UNKNOWN"

_FIRST_FILL_REASONS: frozenset[str] = frozenset({REASON_FIRST_FILL_STREAM, REASON_FIRST_FILL_REST})
_STOP_LOST_REASONS: frozenset[str] = frozenset({REASON_STOP_LOST, REASON_STOP_LOST_AFTER_PROTECTED})
_ENTRY_TERMINAL_REASONS: frozenset[str] = frozenset(
    {
        REASON_ENTRY_TERMINAL,
        REASON_CLOSED_ENTRY_TERMINAL,
        REASON_STOP_CONFIRMED_ENTRY_TERMINAL,
        REASON_ENTRY_ENDED_NO_FILL,
    }
)
# States a rebuild never re-labels, whatever the stop history says (every other state, where a
# stop matters, is restored UNPROTECTED when its history is unknown).
_KEPT_STATES: frozenset[ProtectionState] = frozenset(
    {
        ProtectionState.CLOSE_REQUIRED,
        ProtectionState.CLOSE_FAILED,
        ProtectionState.FLAT,
        ProtectionState.ENTRY_ENDED_NO_FILL,
    }
)
_PRE_FILL_STATES: frozenset[ProtectionState] = frozenset(
    {ProtectionState.AWAITING_FILL, ProtectionState.ENTRY_UNRESOLVED}
)


@dataclass(frozen=True)
class RestoredPlan:
    """What the coordinator installs for one plan after a restart (see the module docstring).

    ``replay_valid`` is False when the journaled rows failed ``replay_transitions``;
    ``stop_history_known`` is True only when "the stop was never confirmed" (or "was confirmed
    and when") is an established fact. A plan with an unknown history is ``UNPROTECTED`` with
    ``stop_lost_at`` set (a plan kept in a blocking state keeps it).
    """

    entry: RestingEntry
    state: ProtectionState
    seq: int
    first_fill_at: datetime | None
    stop_confirmed_at: datetime | None
    stop_lost_at: datetime | None
    entry_terminal_at: datetime | None
    close_branch: str | None
    last_reason: str | None
    replay_valid: bool
    stop_history_known: bool


@dataclass(frozen=True)
class _Row:
    seq: int
    previous: str
    new: str
    reason: str
    evidence: str | None
    at: datetime


def _payload(event: JournalEvent) -> dict[str, Any] | None:
    try:
        body = json.loads(event.payload_json)
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    return {**body, "plan_hash": event.entity_id}


def _rows_of(payloads: Sequence[Mapping[str, Any]], events: Sequence[JournalEvent]) -> list[_Row]:
    """The distinct rows by seq, ordered; only called for a history that replayed valid."""
    by_seq: dict[int, _Row] = {}
    for body, event in zip(payloads, events, strict=True):
        seq = int(body["seq"])
        if seq in by_seq:
            continue
        evidence = body.get("evidence")
        by_seq[seq] = _Row(
            seq=seq,
            previous=str(body["from"]),
            new=str(body["to"]),
            reason=str(body["reason"]),
            evidence=evidence if isinstance(evidence, str) else None,
            at=event.occurred_at_utc,
        )
    return [by_seq[seq] for seq in sorted(by_seq)]


def _spill_is_consistent(
    spill_rows: Sequence[JournalEvent] | None, journal_events: Sequence[JournalEvent]
) -> bool:
    """True only for a readable spill that holds no record of the plan the journal lacks."""
    if spill_rows is None:
        return False
    known = {event.journal_event_id for event in journal_events}
    return all(row.journal_event_id in known for row in spill_rows)


def _intent_contradicts(
    stop_intent: IntentRecord | None, rows: Sequence[_Row], state: ProtectionState
) -> bool:
    """True when the STOP_LOSS intent row shows something the journal rows do not.

    * An intent exists but no row ever left the pre-fill states: the first-fill row is missing.
    * The intent is ACKED but no row carries ``REST_STOP_CONFIRMED``: a confirmation (and what
      followed it) may be missing, so "never confirmed" is not established.
    * The intent is REJECTED (a definitive refusal, B5) but the journal does not end in a close
      state: the CLOSE_REQUIRED row is missing.
    """
    if stop_intent is None:
        return False
    if not any(row.reason in _FIRST_FILL_REASONS for row in rows):
        return True
    confirmed = any(row.evidence == EVIDENCE_REST_STOP_CONFIRMED for row in rows)
    if stop_intent.intent_status == ExecutionIntentStatus.ACKED and not confirmed:
        return True
    return stop_intent.intent_status == ExecutionIntentStatus.REJECTED and state not in (
        ProtectionState.CLOSE_REQUIRED,
        ProtectionState.CLOSE_FAILED,
        ProtectionState.FLAT,
    )


def _first(rows: Sequence[_Row], predicate: Callable[[_Row], bool]) -> _Row | None:
    for row in rows:
        if predicate(row):
            return row
    return None


def _earliest_durable_time(
    entry: RestingEntry,
    stop_intent: IntentRecord | None,
    rows: Sequence[_Row],
    all_event_times: Sequence[datetime],
) -> datetime:
    """The earliest time at which the plan was provably exposed or unprotected (no clock read).

    The first first-fill row and the STOP_LOSS intent's ``intended_at_utc`` are the "unprotected
    since" moments; when neither exists, the earliest journaled transition of the plan; when the
    journal holds nothing, the plan's own ``registered_at_utc``.
    """
    candidates: list[datetime] = []
    first_fill = _first(rows, lambda row: row.reason in _FIRST_FILL_REASONS)
    if first_fill is not None:
        candidates.append(first_fill.at)
    if stop_intent is not None:
        candidates.append(stop_intent.intended_at_utc)
    if candidates:
        return min(candidates)
    if all_event_times:
        return min(all_event_times)
    return entry.registered_at_utc


def _validate_inputs(
    entry: RestingEntry,
    entry_intent: IntentRecord | None,
    stop_intent: IntentRecord | None,
) -> None:
    if not isinstance(entry, RestingEntry):
        raise TypeError("entry must be a RestingEntry")
    for intent in (entry_intent, stop_intent):
        if intent is not None and (
            intent.approval_id != entry.approval_id or intent.plan_hash != entry.plan_hash
        ):
            raise ValueError("an intent row does not belong to the plan being rebuilt")


def _unknown_plan(
    entry: RestingEntry,
    *,
    at: datetime,
    seq: int,
    stop_confirmed_at: datetime | None,
    entry_terminal_at: datetime | None,
    replay_valid: bool,
) -> RestoredPlan:
    """UNPROTECTED under the D077 rules: clocks at the earliest durable time, no stop trusted."""
    return RestoredPlan(
        entry=entry,
        state=ProtectionState.UNPROTECTED,
        seq=seq,
        first_fill_at=at,
        stop_confirmed_at=stop_confirmed_at,
        stop_lost_at=at,
        entry_terminal_at=entry_terminal_at,
        close_branch=None,
        last_reason=REASON_STOP_HISTORY_UNKNOWN,
        replay_valid=replay_valid,
        stop_history_known=False,
    )


def _best_effort_seq(payloads: Sequence[Mapping[str, Any]]) -> int:
    seqs = [
        body["seq"]
        for body in payloads
        if isinstance(body.get("seq"), int) and not isinstance(body.get("seq"), bool)
    ]
    return max(seqs) if seqs else 0


def rebuild_plan(
    *,
    entry: RestingEntry,
    transition_events: Sequence[JournalEvent],
    entry_intent: IntentRecord | None,
    stop_intent: IntentRecord | None,
    spill_rows: Sequence[JournalEvent] | None,
) -> RestoredPlan:
    """Rebuild one plan's coordinator state from its durable sources.

    ``transition_events`` are the journal events of the plan's correlation
    ``protection_<plan_hash>`` (``PgJournalStore.list_by_correlation``); events of other types are
    ignored. ``entry_intent`` and ``stop_intent`` are the plan's ENTRY and STOP_LOSS intent rows
    (None when absent). ``spill_rows`` are the local spill's records of that same correlation, or
    None when the spill could not be read or holds a corrupt entry (the stop history is then
    unknown).

    Raises:
        TypeError: ``entry`` is not a ``RestingEntry``.
        ValueError: an intent row belongs to another plan (a caller bug, not a history fault).
    """
    _validate_inputs(entry, entry_intent, stop_intent)
    plan_hash = entry.plan_hash
    events = [e for e in transition_events if e.event_type == EVENT_PROTECTION_TRANSITION]
    event_times = [e.occurred_at_utc for e in events]
    all_journal_events = list(transition_events)

    if not events:
        if stop_intent is None:
            # Nothing was ever placed: the plan waits for its fill and the first-fill path
            # (query-first) does the rest.
            return RestoredPlan(
                entry=entry,
                state=ProtectionState.AWAITING_FILL,
                seq=0,
                first_fill_at=None,
                stop_confirmed_at=None,
                stop_lost_at=None,
                entry_terminal_at=None,
                close_branch=None,
                last_reason=None,
                replay_valid=True,
                stop_history_known=True,
            )
        # A STOP_LOSS intent exists but the journal holds no row: the history is unknown.
        return _unknown_plan(
            entry,
            at=_earliest_durable_time(entry, stop_intent, [], event_times),
            seq=0,
            stop_confirmed_at=None,
            entry_terminal_at=None,
            replay_valid=True,
        )

    payloads: list[dict[str, Any]] = []
    parsed_all = True
    for event in events:
        body = _payload(event)
        if body is None:
            parsed_all = False
        else:
            payloads.append(body)

    replayed = None
    if parsed_all:
        try:
            replayed = replay_transitions(payloads, plan_hash=plan_hash)
        except ProtectionReplayInvalid:
            replayed = None

    if replayed is None:
        # A corrupt or invalid history: fail closed, nothing silently discarded.
        return _unknown_plan(
            entry,
            at=_earliest_durable_time(entry, stop_intent, [], event_times),
            seq=_best_effort_seq(payloads),
            stop_confirmed_at=None,
            entry_terminal_at=None,
            replay_valid=False,
        )

    rows = _rows_of(payloads, events)
    state = ProtectionState(replayed.state)
    first_fill = _first(rows, lambda row: row.reason in _FIRST_FILL_REASONS)
    confirmed = _first(rows, lambda row: row.evidence == EVIDENCE_REST_STOP_CONFIRMED)
    lost = _first(rows, lambda row: row.reason in _STOP_LOST_REASONS and row.new == "UNPROTECTED")
    terminal = _first(
        rows,
        lambda row: (
            row.new in ("PROTECTED", "ENTRY_ENDED_NO_FILL")
            or row.reason in _ENTRY_TERMINAL_REASONS
            or row.evidence == EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL
        ),
    )
    close_row = _first(rows, lambda row: row.new == "CLOSE_REQUIRED")
    stop_confirmed_at = None if confirmed is None else confirmed.at
    entry_terminal_at = None if terminal is None else terminal.at

    known = _spill_is_consistent(spill_rows, all_journal_events) and not _intent_contradicts(
        stop_intent, rows, state
    )
    if known or state in _KEPT_STATES or (state in _PRE_FILL_STATES and stop_intent is None):
        first_fill_at = None if first_fill is None else first_fill.at
        if first_fill_at is None and stop_intent is not None and state not in _PRE_FILL_STATES:
            first_fill_at = stop_intent.intended_at_utc
        if first_fill_at is None and state is ProtectionState.UNPROTECTED:
            first_fill_at = rows[-1].at
        return RestoredPlan(
            entry=entry,
            state=state,
            seq=replayed.seq,
            first_fill_at=first_fill_at,
            stop_confirmed_at=stop_confirmed_at,
            stop_lost_at=None if lost is None else lost.at,
            entry_terminal_at=entry_terminal_at,
            close_branch=None if close_row is None else close_row.reason,
            last_reason=replayed.last_reason,
            replay_valid=True,
            stop_history_known=known,
        )
    # An unknown history for a plan in which a stop matters: UNPROTECTED under the D077 rules.
    return _unknown_plan(
        entry,
        at=_earliest_durable_time(entry, stop_intent, rows, event_times),
        seq=replayed.seq,
        stop_confirmed_at=stop_confirmed_at,
        entry_terminal_at=entry_terminal_at,
        replay_valid=True,
    )


__all__ = [
    "REASON_STOP_HISTORY_UNKNOWN",
    "RestoredPlan",
    "rebuild_plan",
]
