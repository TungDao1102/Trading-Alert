"""Clearing rules and replay of the protection transition history (plan 20-02; T-A, D077, D-08).

Pure module: standard library and ``src.domain`` only. No clock, no I/O, no float, no import of
``src.execution.protection`` (the coordinator imports this module, so the guard that runs live and
the replay that validates a journaled history share one definition and cannot drift).

This module holds the rules that sit on top of the PROTECTION table of
``src.domain.transitions`` (which edges exist):

* ``UNPROTECTED`` -> ``PROTECTED_ENTRY_OPEN`` / ``PROTECTED`` clears only with the evidence
  ``REST_STOP_CONFIRMED`` and only for a first-fill ``UNPROTECTED``: a stop-lost ``UNPROTECTED``
  (D077) leaves only to ``CLOSE_REQUIRED`` or ``FLAT``, never back to a protected state.
* A move to ``FLAT`` from ``UNPROTECTED``, ``PROTECTED_ENTRY_OPEN``, ``CLOSE_REQUIRED`` or
  ``CLOSE_FAILED`` clears only with the evidence ``REST_FLAT_TWO_READS_ENTRY_TERMINAL`` (two
  independent fresh zero position reads and a terminal entry, D-06, D-09).
* ``CLOSE_REQUIRED`` and ``CLOSE_FAILED`` never reach a protected state: that is absent from the
  table, so no evidence can open it (the exception O-H, a return to protected exposure, is not
  built; the default is NO).

``replay_transitions`` validates the journaled ``PROTECTION_TRANSITION`` payloads of ONE plan
through the same table and the same ``clearing_violation`` (D-08, replay part). It returns the
last state or raises ``ProtectionReplayInvalid`` with a fixed reason code; it never returns a
partial state and never silently drops a row. The rebuild after a restart (plan 20-19) is the
caller and decides what an invalid history means (fail closed, SAFE_MODE); this plan adds no
production caller.

A row with a clearing edge and no ``evidence`` key (a row written before plan 20-02) is invalid:
the history cannot show what cleared the blocking state, so it fails closed. Rows that clear
nothing do not need the key.

Limit of the claim (D-29): the journal rows carry no exchange event time. The replay detects only
what ordering (``seq``) and deduplication evidence it has; it is not general stale-event
detection, which is deferred to Phase 24.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.domain.transitions import (
    LEGAL_TRANSITIONS,
    PROTECTION_INITIAL_STATE,
    TransitionKind,
    is_legal,
)

# The evidence recorded in the PROTECTION_TRANSITION payload key ``evidence`` when a move clears a
# blocking state (T-A). Fixed project text, never exchange text.
EVIDENCE_REST_STOP_CONFIRMED = "REST_STOP_CONFIRMED"
EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL = "REST_FLAT_TWO_READS_ENTRY_TERMINAL"
CLEARING_EVIDENCE: frozenset[str] = frozenset(
    {EVIDENCE_REST_STOP_CONFIRMED, EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL}
)

# The reason journaled when a confirmed stop is first seen lost (D077): the replay uses it to know
# that an UNPROTECTED plan is a stop-lost one.
REASON_STOP_LOST = "STOP_LOST"
# Plan 20-09 (D-07): the reason of the same loss detected after PROTECTED, COMPLETE or
# TP_UNAVAILABLE (stop supervision); it also marks the history as stop-lost.
REASON_STOP_LOST_AFTER_PROTECTED = "STOP_LOST_AFTER_PROTECTED"
_STOP_LOST_REASONS: frozenset[str] = frozenset({REASON_STOP_LOST, REASON_STOP_LOST_AFTER_PROTECTED})

# Fixed reason codes of a refused move (the guard) and of an invalid history (the replay).
REJECT_ILLEGAL_EDGE = "ILLEGAL_EDGE"
REJECT_EVIDENCE_MISSING = "EVIDENCE_MISSING"
REJECT_STOP_LOST_CLEARED = "STOP_LOST_CLEARED"
REPLAY_EMPTY_HISTORY = "EMPTY_HISTORY"
REPLAY_MALFORMED_ROW = "MALFORMED_ROW"
REPLAY_PLAN_MISMATCH = "PLAN_MISMATCH"
REPLAY_DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
REPLAY_SEQ_GAP = "SEQ_GAP"
REPLAY_BAD_START = "BAD_START"
REPLAY_CHAIN_BROKEN = "CHAIN_BROKEN"

_NO_STATE = "NONE"
_STATE_UNPROTECTED = "UNPROTECTED"
_STATE_FLAT = "FLAT"
_PROTECTED_TARGETS: frozenset[str] = frozenset({"PROTECTED_ENTRY_OPEN", "PROTECTED"})
_FLAT_NEEDS_EVIDENCE_FROM: frozenset[str] = frozenset(
    {"UNPROTECTED", "PROTECTED_ENTRY_OPEN", "CLOSE_REQUIRED", "CLOSE_FAILED"}
)
_STATES: frozenset[str] = frozenset(LEGAL_TRANSITIONS[TransitionKind.PROTECTION])


def clearing_violation(
    previous: str, new: str, evidence: str | None, *, stop_lost: bool
) -> str | None:
    """The reason code when the move ``previous -> new`` breaks a clearing rule, else None.

    The caller has already checked the edge against the PROTECTION table. ``stop_lost`` is True
    for a plan whose confirmed stop was seen lost (``stop_lost_at`` set live; a ``STOP_LOST``
    reason earlier in the history on replay).
    """
    if previous == _STATE_UNPROTECTED and new in _PROTECTED_TARGETS:
        if stop_lost:
            return REJECT_STOP_LOST_CLEARED
        if evidence != EVIDENCE_REST_STOP_CONFIRMED:
            return REJECT_EVIDENCE_MISSING
        return None
    if (
        new == _STATE_FLAT
        and previous in _FLAT_NEEDS_EVIDENCE_FROM
        and evidence != EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL
    ):
        return REJECT_EVIDENCE_MISSING
    return None


class ProtectionReplayInvalid(ValueError):
    """A journaled protection history that cannot be trusted (fail closed, D-08).

    ``reason`` is a fixed code; the message is that code only, never row text.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ReplayedProtection:
    """The state a valid history ends in (``rows`` is the number of distinct rows validated)."""

    plan_hash: str
    state: str
    seq: int
    last_reason: str
    rows: int


@dataclass(frozen=True)
class _Row:
    seq: int
    previous: str
    new: str
    reason: str
    evidence: str | None
    identity: tuple[str, str, str]


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or value == "":
        raise ProtectionReplayInvalid(REPLAY_MALFORMED_ROW)
    return value


def _parse(raw: object, plan_hash: str) -> _Row:
    if not isinstance(raw, Mapping):
        raise ProtectionReplayInvalid(REPLAY_MALFORMED_ROW)
    seq = raw.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise ProtectionReplayInvalid(REPLAY_MALFORMED_ROW)
    previous = _text(raw, "from")
    new = _text(raw, "to")
    reason = _text(raw, "reason")
    if new not in _STATES or (previous != _NO_STATE and previous not in _STATES):
        raise ProtectionReplayInvalid(REPLAY_MALFORMED_ROW)
    evidence = raw.get("evidence")
    if evidence is not None and not isinstance(evidence, str):
        raise ProtectionReplayInvalid(REPLAY_MALFORMED_ROW)
    identity = (_text(raw, "approval_id"), _text(raw, "trade_plan_id"), _text(raw, "symbol"))
    if "plan_hash" in raw:
        tagged = raw["plan_hash"]
        if not isinstance(tagged, str):
            raise ProtectionReplayInvalid(REPLAY_MALFORMED_ROW)
        if tagged != plan_hash:
            raise ProtectionReplayInvalid(REPLAY_PLAN_MISMATCH)
    return _Row(seq, previous, new, reason, evidence, identity)


def replay_transitions(
    rows: Sequence[Mapping[str, object]], *, plan_hash: str
) -> ReplayedProtection:
    """Validate the ``PROTECTION_TRANSITION`` payloads of one plan; return the state they end in.

    ``rows`` are the decoded payload mappings (keys ``seq``, ``from``, ``to``, ``reason``,
    ``evidence``, ``approval_id``, ``trade_plan_id``, ``symbol``); a caller that read them from the
    journal may add the optional key ``plan_hash`` (the event's entity id), which must equal
    ``plan_hash``. Rows are sorted by ``seq``; two rows with the same ``seq`` and the same payload
    count once, with a different payload they raise ``DUPLICATE_CONFLICT``. The history must start
    at ``seq`` 1 with ``NONE -> AWAITING_FILL``, have no gap, chain (each ``from`` is the previous
    ``to``), use only edges of the PROTECTION table and satisfy ``clearing_violation``.

    Raises:
        ProtectionReplayInvalid: with a fixed reason code, for any violation. Nothing is returned
            for a partly valid history.
        TypeError: ``plan_hash`` is not a non-empty string (a caller bug, not a history fault).
    """
    if not isinstance(plan_hash, str) or plan_hash == "":
        raise TypeError("plan_hash must be a non-empty string")
    if len(rows) == 0:
        raise ProtectionReplayInvalid(REPLAY_EMPTY_HISTORY)
    parsed = [_parse(raw, plan_hash) for raw in rows]
    if len({row.identity for row in parsed}) != 1:
        raise ProtectionReplayInvalid(REPLAY_PLAN_MISMATCH)

    by_seq: dict[int, tuple[Mapping[str, object], _Row]] = {}
    for raw, row in zip(rows, parsed, strict=True):
        known = by_seq.get(row.seq)
        if known is None:
            by_seq[row.seq] = (raw, row)
        elif dict(known[0]) != dict(raw):
            raise ProtectionReplayInvalid(REPLAY_DUPLICATE_CONFLICT)
    ordered = [by_seq[seq][1] for seq in sorted(by_seq)]
    for expected, row in enumerate(ordered, start=1):
        if row.seq != expected:
            raise ProtectionReplayInvalid(REPLAY_SEQ_GAP)

    first = ordered[0]
    if (first.previous, first.new) != (_NO_STATE, PROTECTION_INITIAL_STATE):
        raise ProtectionReplayInvalid(REPLAY_BAD_START)
    current = first.new
    stop_lost = False
    for row in ordered[1:]:
        if row.previous != current:
            raise ProtectionReplayInvalid(REPLAY_CHAIN_BROKEN)
        if not is_legal(TransitionKind.PROTECTION, row.previous, row.new):
            raise ProtectionReplayInvalid(REJECT_ILLEGAL_EDGE)
        violation = clearing_violation(row.previous, row.new, row.evidence, stop_lost=stop_lost)
        if violation is not None:
            raise ProtectionReplayInvalid(violation)
        if row.reason in _STOP_LOST_REASONS and row.new == _STATE_UNPROTECTED:
            stop_lost = True
        current = row.new

    last = ordered[-1]
    return ReplayedProtection(
        plan_hash=plan_hash,
        state=current,
        seq=last.seq,
        last_reason=last.reason,
        rows=len(ordered),
    )


__all__ = [
    "CLEARING_EVIDENCE",
    "EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL",
    "EVIDENCE_REST_STOP_CONFIRMED",
    "REASON_STOP_LOST",
    "REASON_STOP_LOST_AFTER_PROTECTED",
    "REJECT_EVIDENCE_MISSING",
    "REJECT_ILLEGAL_EDGE",
    "REJECT_STOP_LOST_CLEARED",
    "ProtectionReplayInvalid",
    "ReplayedProtection",
    "clearing_violation",
    "replay_transitions",
]
