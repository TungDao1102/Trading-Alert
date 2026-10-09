"""Three-way attribution vocabulary for paper records (Phase 7, plan 07-03).

Per D-03: every paper record carries an attribution field that splits
the outcome into one of three canonical kinds:

  - `system`: the engine emitted the record (signal, plan, NO_TRADE).
  - `user-executed-sim`: a SIMULATE fill leg with the approval-delay
    lag applied to the simulated `acted_at_utc`. This is the
    "what would have happened if the user had approved" leg.
  - `opportunity`: a skipped or expired plan retained with a reason
    code. Per D-03 (never-dropped rule), these rows are never
    dropped to flatter the record — absence of evidence is itself
    evidence.

The `str, Enum` mixin keeps ORM/JSON `.value` storage trivial while
preserving Enum identity for mypy checks. The values are byte-exact
and must not be renamed — Phase-10 analytics reads them.

FLAGGED ASSUMPTION (PAPER-02 unclassified): the approval-delay lag
constant `APPROVAL_DELAY_LAG_SECONDS` is a fixed documented value
modeling the user-executed-sim leg. It is calibrated against measured
Telegram latency in Phase 10, never blocking Phase 7. The constant
lives here (not in journal.py) because it is part of the attribution
vocabulary, not the assembly contract.

Phase 16 (plan 16-35, D-15, SC3): the constant is now ONLY the documented
default for a record with no human action (the paper simulator's own
SIMULATE approval leg). Wherever a human acted in the SHADOW chain, the
approval delay is the measured `acted_at_utc - requested_at_utc` of the
approval row, with the confirm timestamps, and `assemble_paper_record`
never replaces it by signal + the constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AttributionKind(str, Enum):
    """Canonical three-way attribution for paper records (D-03).

    Values are byte-exact: `system`, `user-executed-sim`, `opportunity`.
    No synonyms, no invented names — an unknown value is a load-time
    error. Phase-10 analytics reads these values directly.
    """

    SYSTEM = "system"
    USER_EXECUTED_SIM = "user-executed-sim"
    OPPORTUNITY = "opportunity"


# Approval-delay lag constant (FLAGGED ASSUMPTION, PAPER-02 unclassified). Since plan 16-35
# it is only the default for records with no human action (D-15).
# Models the user-executed-sim leg: the simulated approval `acted_at_utc`
# equals `signal.detected_at_utc + APPROVAL_DELAY_LAG_SECONDS`. Calibrated
# against measured Telegram latency in Phase 10, never blocking Phase 7.
# The value is a documented constant — not an env var — so a mid-soak
# change is a code change, not a config drift.
APPROVAL_DELAY_LAG_SECONDS: int = 30


# --------------------------------------------------------------------------- #
# SHADOW outcome attribution (plan 16-35, D-15, PAPER-02, REV-12).
#
# Pure mapping from the journaled approval and confirm outcomes of one plan to the three-way
# attribution and its reason. The reason strings are existing vocabulary only: approval actions
# (GLOSSARY section 4), RejectionReason values (APPROVAL_EXPIRED) and the confirm journal event
# types and reasons of plan 16-11 (src/paper/shadow_confirm.py). They are repeated here as
# literals so this module keeps importing only the standard library; a test pins every literal
# to its source module.
# --------------------------------------------------------------------------- #

EVENT_CONFIRMED = "SHADOW_CONFIRMED"
EVENT_CONFIRM_CANCELLED = "SHADOW_CONFIRM_CANCELLED"
EVENT_CONFIRM_EXPIRED = "SHADOW_CONFIRM_EXPIRED"
# Reason journaled on SHADOW_CONFIRM_EXPIRED when the 60 s window simply ran out. The attribution
# reason for that case is the event type itself, as the plan states; every other expiry reason
# (CARD_DELIVERY_FAILED, RUNTIME_RESTART, USER_ID_UNAVAILABLE, a RejectionReason value at CONFIRM)
# is carried through unchanged.
REASON_CONFIRM_TTL_ELAPSED = "CONFIRM_TTL_ELAPSED"
# The reason code of a plan nobody touched that reached its expiry: the existing PAPER-02 rule of
# `assemble_paper_record` Case 3 (07-CONTEXT D-03: "skipped/expired plans retained with reason
# codes - never dropped").
REASON_UNTOUCHED_EXPIRED = "EXPIRED"

_SKIP_ACTIONS = frozenset({"SKIP_USER", "SKIP_BUSY", "CANCEL"})


@dataclass(frozen=True)
class ShadowOutcome:
    """What the journal says happened to one SHADOW plan (all fields are journaled facts).

    - `approval_action`: the human decision on the approval row (APPROVE, SKIP_USER, SKIP_BUSY,
      CANCEL) or None when nobody touched the plan.
    - `approval_rejection_reason`: the canonical rejection reason when the press was refused
      (for example APPROVAL_EXPIRED for an APPROVE after the plan expiry, REV-12).
    - `confirm_event` / `confirm_reason`: the terminal confirm journal event type and its reason.
    - `plan_expired`: True when the plan reached its expiry (only meaningful for an untouched
      plan).
    """

    approval_action: str | None = None
    approval_rejection_reason: str | None = None
    confirm_event: str | None = None
    confirm_reason: str | None = None
    plan_expired: bool = False


def attribute_shadow_outcome(outcome: ShadowOutcome) -> tuple[AttributionKind, str]:
    """Map a SHADOW plan outcome to its attribution and reason (D-15).

    - APPROVE then CONFIRM: `user-executed-sim`, empty reason.
    - SKIP_USER / SKIP_BUSY / CANCEL on the approval, a confirm CANCEL
      (SHADOW_CONFIRM_CANCELLED), a confirm that ran out (SHADOW_CONFIRM_EXPIRED, or the journaled
      CARD_DELIVERY_FAILED / RUNTIME_RESTART / USER_ID_UNAVAILABLE / gate reason) and a refused
      press (APPROVAL_EXPIRED): `opportunity` with that reason. An approved plan that was not
      confirmed is never `user-executed-sim`.
    - A plan nobody touched: `opportunity` with EXPIRED once it expired, else `system` (only the
      engine emission exists), the PAPER-02 rule of `assemble_paper_record`.

    Anything not decidable yet (APPROVE without a terminal confirm event, a non-terminal event, an
    unknown action) raises: attribution is only produced for terminal outcomes.
    """
    action = outcome.approval_action
    if outcome.approval_rejection_reason is not None:
        if outcome.confirm_event is not None:
            raise ValueError("a refused press cannot carry a confirm event")
        return AttributionKind.OPPORTUNITY, outcome.approval_rejection_reason
    if action is None:
        if outcome.confirm_event is not None:
            raise ValueError("a confirm event needs an APPROVE on the approval")
        if outcome.plan_expired:
            return AttributionKind.OPPORTUNITY, REASON_UNTOUCHED_EXPIRED
        return AttributionKind.SYSTEM, ""
    if action in _SKIP_ACTIONS:
        if outcome.confirm_event is not None:
            raise ValueError(f"a {action} approval cannot carry a confirm event")
        return AttributionKind.OPPORTUNITY, action
    if action != "APPROVE":
        raise ValueError(f"unknown approval action for attribution: {action!r}")
    event = outcome.confirm_event
    if event is None:
        raise ValueError("an APPROVE without a terminal confirm event is not decided yet")
    if event == EVENT_CONFIRMED:
        return AttributionKind.USER_EXECUTED_SIM, ""
    if event == EVENT_CONFIRM_CANCELLED:
        return AttributionKind.OPPORTUNITY, EVENT_CONFIRM_CANCELLED
    if event == EVENT_CONFIRM_EXPIRED:
        if outcome.confirm_reason in (None, "", REASON_CONFIRM_TTL_ELAPSED):
            return AttributionKind.OPPORTUNITY, EVENT_CONFIRM_EXPIRED
        return AttributionKind.OPPORTUNITY, outcome.confirm_reason
    raise ValueError(f"not a terminal confirm event: {event!r}")


__all__ = [
    "AttributionKind",
    "APPROVAL_DELAY_LAG_SECONDS",
    "EVENT_CONFIRMED",
    "EVENT_CONFIRM_CANCELLED",
    "EVENT_CONFIRM_EXPIRED",
    "REASON_CONFIRM_TTL_ELAPSED",
    "REASON_UNTOUCHED_EXPIRED",
    "ShadowOutcome",
    "attribute_shadow_outcome",
]
