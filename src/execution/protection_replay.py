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
"""

from __future__ import annotations

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

# Fixed reason codes of a refused move (the guard) and of an invalid history (the replay).
REJECT_ILLEGAL_EDGE = "ILLEGAL_EDGE"
REJECT_EVIDENCE_MISSING = "EVIDENCE_MISSING"
REJECT_STOP_LOST_CLEARED = "STOP_LOST_CLEARED"

_STATE_UNPROTECTED = "UNPROTECTED"
_STATE_FLAT = "FLAT"
_PROTECTED_TARGETS: frozenset[str] = frozenset({"PROTECTED_ENTRY_OPEN", "PROTECTED"})
_FLAT_NEEDS_EVIDENCE_FROM: frozenset[str] = frozenset(
    {"UNPROTECTED", "PROTECTED_ENTRY_OPEN", "CLOSE_REQUIRED", "CLOSE_FAILED"}
)


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


__all__ = [
    "CLEARING_EVIDENCE",
    "EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL",
    "EVIDENCE_REST_STOP_CONFIRMED",
    "REASON_STOP_LOST",
    "REJECT_EVIDENCE_MISSING",
    "REJECT_ILLEGAL_EDGE",
    "REJECT_STOP_LOST_CLEARED",
    "clearing_violation",
]
