"""Description of a stored entry outcome for the operator reply (Phase 23, plan 23-05; D-12).

`check_binding_full` answers APPROVAL_EXPIRED once the plan expired, before it looks at the
execution state, so a redelivered APPROVE of an already executed plan would say "expired"
(inherited item G4-032). The reply layer asks `prior_outcome_for_expired_redelivery` first: when
the press hit APPROVAL_EXPIRED on an approval that is APPROVED, the stored ENTRY intent says what
really happened.

An ambiguous result is never described as rejected (Q5): UNKNOWN, SENT and INTENDED mean an order
may be live on the exchange, so they map to NEEDS_RECONCILIATION. Every `ExecutionIntentStatus`
member is mapped explicitly; a new member fails the mapping (exhaustive, no default branch).

Pure over its inputs: the intent reader is injected (`Callable[[str], IntentRecord | None]`
taking the approval id; Phase 24 binds `store.get_entry(approval_id=...)`). No store, adapter or
clock import, no logging.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from src.domain.approval import Approval
from src.domain.enums import ApprovalResult, ExecutionIntentStatus, RejectionReason
from src.execution.intent_store import IntentRecord


class PriorOutcome(str, Enum):
    """What a stored entry intent says happened to an approval."""

    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
    REJECTED = "REJECTED"


PRIOR_OUTCOME_LABEL: dict[PriorOutcome, str] = {
    PriorOutcome.ALREADY_EXECUTED: "already executed",
    PriorOutcome.NEEDS_RECONCILIATION: "needs reconciliation",
    PriorOutcome.REJECTED: "rejected",
}

_BY_STATUS: dict[ExecutionIntentStatus, PriorOutcome] = {
    ExecutionIntentStatus.ACKED: PriorOutcome.ALREADY_EXECUTED,
    ExecutionIntentStatus.UNKNOWN: PriorOutcome.NEEDS_RECONCILIATION,
    ExecutionIntentStatus.SENT: PriorOutcome.NEEDS_RECONCILIATION,
    ExecutionIntentStatus.INTENDED: PriorOutcome.NEEDS_RECONCILIATION,
    ExecutionIntentStatus.REJECTED: PriorOutcome.REJECTED,
}


def describe_prior_outcome(intent: IntentRecord | None) -> PriorOutcome | None:
    """Map a stored entry intent to its description; None without an intent.

    Raises `KeyError` for an `ExecutionIntentStatus` member without an explicit mapping
    (fail closed: a new status must be classified before it can be described).
    """
    if intent is None:
        return None
    return _BY_STATUS[intent.intent_status]


def prior_outcome_for_expired_redelivery(
    *,
    reason_code: RejectionReason | str,
    stored: Approval | None,
    intent_reader: Callable[[str], IntentRecord | None],
) -> PriorOutcome | None:
    """The stored outcome, read only for an APPROVAL_EXPIRED press on an APPROVED approval.

    Any other reason, a missing approval, or an approval that is SKIPPED, EXPIRED or PENDING
    returns None and never calls the reader (G4-032).
    """
    if reason_code != RejectionReason.APPROVAL_EXPIRED.value:
        return None
    if stored is None or stored.status is not ApprovalResult.APPROVED:
        return None
    return describe_prior_outcome(intent_reader(stored.approval_id))
