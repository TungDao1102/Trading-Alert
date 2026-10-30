"""Description of a stored entry outcome for the redelivery reply (Phase 23, plan 23-05; D-12).

Oracle table (ExecutionIntentStatus -> PriorOutcome): ACKED -> ALREADY_EXECUTED; UNKNOWN, SENT and
INTENDED -> NEEDS_RECONCILIATION (an ambiguous result is never "rejected", Q5); REJECTED ->
REJECTED; no intent -> None. G4-032: the stored outcome is read only when a redelivered press
hit APPROVAL_EXPIRED on an APPROVED approval.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import src.execution.prior_outcome as po
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    ExecutionIntentStatus,
    RejectionReason,
)
from src.execution.intent_store import IntentRecord
from src.execution.prior_outcome import (
    PRIOR_OUTCOME_LABEL,
    PriorOutcome,
    describe_prior_outcome,
    prior_outcome_for_expired_redelivery,
)

from tests.support.ast_guards import wall_clock_calls
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore

NOW = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)
APPROVAL_ID = "appr-1"


def _approval(result: ApprovalResult) -> Approval:
    acted = None if result is ApprovalResult.PENDING else NOW
    return Approval(
        approval_id=APPROVAL_ID,
        trade_plan_id="tp-1",
        signal_id="sig-1",
        action=ApprovalAction.APPROVE,
        result=result,
        status=result,
        approval_token_hash="h" * 64,
        requested_at_utc=NOW,
        acted_at_utc=acted,
    )


def _intent(status: ExecutionIntentStatus) -> IntentRecord:
    return IntentRecord(
        approval_id=APPROVAL_ID,
        role="ENTRY",
        trade_plan_id="tp-1",
        plan_hash="p" * 64,
        client_order_id="cid",
        algo_client_id=None,
        symbol="BTCUSDT",
        side="LONG",
        intended_quantity=Decimal("0.5"),
        intended_price=Decimal("100"),
        intent_status=status,
        exchange_order_id=None,
        exchange_status=None,
        outcome=None,
        intended_at_utc=NOW,
        sent_at_utc=None,
        resolved_at_utc=None,
        updated_at_utc=NOW,
    )


EXPECTED = {
    ExecutionIntentStatus.ACKED: PriorOutcome.ALREADY_EXECUTED,
    ExecutionIntentStatus.UNKNOWN: PriorOutcome.NEEDS_RECONCILIATION,
    ExecutionIntentStatus.SENT: PriorOutcome.NEEDS_RECONCILIATION,
    ExecutionIntentStatus.INTENDED: PriorOutcome.NEEDS_RECONCILIATION,
    ExecutionIntentStatus.REJECTED: PriorOutcome.REJECTED,
}


def test_no_intent_is_none() -> None:
    assert describe_prior_outcome(None) is None


@pytest.mark.parametrize("status", list(ExecutionIntentStatus))
def test_every_status_is_mapped_explicitly(status: ExecutionIntentStatus) -> None:
    assert status in EXPECTED, f"unmapped ExecutionIntentStatus {status!r}"
    assert describe_prior_outcome(_intent(status)) is EXPECTED[status]


@pytest.mark.parametrize(
    "status",
    [ExecutionIntentStatus.UNKNOWN, ExecutionIntentStatus.SENT, ExecutionIntentStatus.INTENDED],
)
def test_ambiguous_is_never_rejected(status: ExecutionIntentStatus) -> None:
    assert describe_prior_outcome(_intent(status)) is not PriorOutcome.REJECTED


def test_labels() -> None:
    assert set(PRIOR_OUTCOME_LABEL) == set(PriorOutcome)
    assert PRIOR_OUTCOME_LABEL[PriorOutcome.ALREADY_EXECUTED] == (
        "already placed (acknowledged by the exchange; fill state is in the journal)"
    )
    assert PRIOR_OUTCOME_LABEL[PriorOutcome.NEEDS_RECONCILIATION] == "needs reconciliation"
    assert PRIOR_OUTCOME_LABEL[PriorOutcome.REJECTED] == "rejected"
    for outcome, label in PRIOR_OUTCOME_LABEL.items():
        if outcome is not PriorOutcome.REJECTED:
            assert "rejected" not in label


# --- expired redelivery ---------------------------------------------------------------------


def _store_with(status: ExecutionIntentStatus) -> InMemoryExecutionIntentStore:
    store = InMemoryExecutionIntentStore()
    store.consume_and_record_entry_intent(
        approval_id=APPROVAL_ID,
        trade_plan_id="tp-1",
        plan_hash="p" * 64,
        client_order_id="cid",
        symbol="BTCUSDT",
        side="LONG",
        intended_quantity=Decimal("0.5"),
        intended_price=Decimal("100"),
        approved_quantity=Decimal("0.5"),
        now_utc=NOW,
    )
    if status is not ExecutionIntentStatus.INTENDED:
        store.mark_sent(approval_id=APPROVAL_ID, role="ENTRY", now_utc=NOW)
    return store


def test_expired_redelivery_of_an_in_flight_entry_needs_reconciliation() -> None:
    store = _store_with(ExecutionIntentStatus.SENT)
    result = prior_outcome_for_expired_redelivery(
        reason_code=RejectionReason.APPROVAL_EXPIRED,
        stored=_approval(ApprovalResult.APPROVED),
        intent_reader=lambda approval_id: store.get_entry(approval_id=approval_id),
    )
    assert result is PriorOutcome.NEEDS_RECONCILIATION


def test_expired_redelivery_with_plain_string_reason_code() -> None:
    store = _store_with(ExecutionIntentStatus.INTENDED)
    result = prior_outcome_for_expired_redelivery(
        reason_code="APPROVAL_EXPIRED",
        stored=_approval(ApprovalResult.APPROVED),
        intent_reader=lambda approval_id: store.get_entry(approval_id=approval_id),
    )
    assert result is PriorOutcome.NEEDS_RECONCILIATION


def test_expired_redelivery_of_an_acked_entry_is_already_executed() -> None:
    record = _intent(ExecutionIntentStatus.ACKED)
    result = prior_outcome_for_expired_redelivery(
        reason_code=RejectionReason.APPROVAL_EXPIRED,
        stored=_approval(ApprovalResult.APPROVED),
        intent_reader=lambda _approval_id: record,
    )
    assert result is PriorOutcome.ALREADY_EXECUTED


def test_reader_receives_the_approval_id() -> None:
    seen: list[str] = []

    def reader(approval_id: str) -> IntentRecord | None:
        seen.append(approval_id)
        return None

    result = prior_outcome_for_expired_redelivery(
        reason_code=RejectionReason.APPROVAL_EXPIRED,
        stored=_approval(ApprovalResult.APPROVED),
        intent_reader=reader,
    )
    assert result is None
    assert seen == [APPROVAL_ID]


def _forbidden_reader(_approval_id: str) -> Any:
    raise AssertionError("the reader must not be called")


@pytest.mark.parametrize(
    "reason",
    [RejectionReason.INVALIDATED, RejectionReason.STALE_SETUP, "MARK_PRICE_UNAVAILABLE"],
)
def test_other_reasons_never_read(reason: Any) -> None:
    assert (
        prior_outcome_for_expired_redelivery(
            reason_code=reason,
            stored=_approval(ApprovalResult.APPROVED),
            intent_reader=_forbidden_reader,
        )
        is None
    )


def test_missing_stored_never_reads() -> None:
    assert (
        prior_outcome_for_expired_redelivery(
            reason_code=RejectionReason.APPROVAL_EXPIRED,
            stored=None,
            intent_reader=_forbidden_reader,
        )
        is None
    )


@pytest.mark.parametrize(
    "result", [ApprovalResult.SKIPPED, ApprovalResult.EXPIRED, ApprovalResult.PENDING]
)
def test_non_approved_never_reads(result: ApprovalResult) -> None:
    assert (
        prior_outcome_for_expired_redelivery(
            reason_code=RejectionReason.APPROVAL_EXPIRED,
            stored=_approval(result),
            intent_reader=_forbidden_reader,
        )
        is None
    )


# --- module hygiene -------------------------------------------------------------------------

_SRC = Path(po.__file__)


def test_module_is_pure() -> None:
    assert not wall_clock_calls(_SRC)
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not name.startswith(("src.execution.manager", "src.adapters", "src.persistence")), (
            name
        )
