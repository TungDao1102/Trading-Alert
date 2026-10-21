"""The reconciliation result contract of the execution-intent stores (Phase 20, plan 20-03, T-B).

`record_result` carries the EXCHANGE response (status, order id, Binance's own status string).
A reconciliation conclusion has its own API, `finalize_reconciled_resolution`, and its own column,
`execution_intents.resolution_reason_code` (migration 0007). This module holds ONE contract
(`IntentResultContract`) that every store must satisfy; `IntentResultContract` is not collected
itself, a subclass supplies the `harness` fixture:

  - `TestInMemoryIntentResultContract` (added by plan 20-03 task 2, same file),
  - `tests/test_intent_result_contract_pg.py` runs the same tests against `PgExecutionStateStore`.

What the contract pins (D-11, T-B):

  - RECONCILED_ABSENT is written only by UNKNOWN -> REJECTED, NEVER_SENT only by
    INTENDED -> REJECTED; any other source status, or an unknown reason code, refuses and writes
    nothing;
  - the application reason never lands in `exchange_status` (Binance's field);
  - a row closed by `record_result(REJECTED)` has NO reason, a row closed by the reconciliation
    API carries its code, so a definitive Binance rejection and a reconciled absence cannot be
    confused.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.execution.intent_store import (
    RESOLUTION_NEVER_SENT,
    RESOLUTION_REASON_CODES,
    RESOLUTION_RECONCILED_ABSENT,
    ExecutionIntentStore,
    IntentRecord,
)
from src.persistence.errors import IntentStateConflict

T0 = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)
T3 = T0 + timedelta(minutes=3)

ENTRY = OrderRole.ENTRY.value
STOP_LOSS = OrderRole.STOP_LOSS.value

_NEVER_WRITTEN_BY_ANYONE = "ABSENT_BY_GUESS"


@dataclass(frozen=True)
class ContractHarness:
    """One store plus what the contract needs to seed and read it back."""

    store: ExecutionIntentStore
    approval_id: str
    entry_args: dict[str, Any]
    protective_args: dict[str, Any]
    read: Callable[[str], IntentRecord | None]
    """role -> the stored row of `approval_id` (any role), or None."""


def default_entry_args(approval_id: str) -> dict[str, Any]:
    return {
        "approval_id": approval_id,
        "trade_plan_id": "plan-contract-1",
        "plan_hash": "a" * 64,
        "client_order_id": "x-contract-entry-1",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "intended_quantity": Decimal("0.08"),
        "intended_price": Decimal("50050"),
        "approved_quantity": Decimal("0.08"),
        "now_utc": T0,
    }


def default_protective_args(approval_id: str) -> dict[str, Any]:
    return {
        "approval_id": approval_id,
        "role": STOP_LOSS,
        "trade_plan_id": "plan-contract-1",
        "plan_hash": "a" * 64,
        "algo_client_id": "x-contract-stop-1",
        "symbol": "BTCUSDT",
        "side": "SELL",
        "intended_price": Decimal("49500"),
        "now_utc": T0,
    }


def drive_entry(harness: ContractHarness, target: ExecutionIntentStatus) -> None:
    """Bring the ENTRY row of the harness to `target` through legal moves only."""
    store = harness.store
    assert store.consume_and_record_entry_intent(**harness.entry_args) is True
    if target == ExecutionIntentStatus.INTENDED:
        return
    store.mark_sent(approval_id=harness.approval_id, role=ENTRY, now_utc=T1)
    if target == ExecutionIntentStatus.SENT:
        return
    if target == ExecutionIntentStatus.UNKNOWN:
        store.record_result(
            approval_id=harness.approval_id,
            role=ENTRY,
            status=ExecutionIntentStatus.UNKNOWN,
            exchange_order_id=None,
            exchange_status=None,
            now_utc=T2,
        )
    elif target == ExecutionIntentStatus.ACKED:
        store.record_result(
            approval_id=harness.approval_id,
            role=ENTRY,
            status=ExecutionIntentStatus.ACKED,
            exchange_order_id="4711",
            exchange_status="NEW",
            now_utc=T2,
        )
    elif target == ExecutionIntentStatus.REJECTED:
        store.record_result(
            approval_id=harness.approval_id,
            role=ENTRY,
            status=ExecutionIntentStatus.REJECTED,
            exchange_order_id=None,
            exchange_status="REJECTED",
            now_utc=T2,
        )
    else:  # pragma: no cover - the contract never asks for another target
        raise AssertionError(target)


def finalize(harness: ContractHarness, reason_code: str, *, role: str = ENTRY) -> None:
    harness.store.finalize_reconciled_resolution(
        approval_id=harness.approval_id, role=role, reason_code=reason_code, now_utc=T3
    )


def _entry(harness: ContractHarness) -> IntentRecord:
    row = harness.read(ENTRY)
    assert row is not None
    return row


class IntentResultContract:
    """The shared store contract. Not collected (no `Test` prefix); a subclass gives `harness`."""

    @pytest.fixture
    def harness(self) -> Iterator[ContractHarness]:
        raise NotImplementedError

    # -- the two accepted moves -------------------------------------------------------------

    def test_unknown_entry_is_finalized_reconciled_absent(self, harness: ContractHarness) -> None:
        drive_entry(harness, ExecutionIntentStatus.UNKNOWN)
        finalize(harness, RESOLUTION_RECONCILED_ABSENT)
        row = _entry(harness)
        assert row.intent_status is ExecutionIntentStatus.REJECTED
        assert row.resolution_reason_code == RESOLUTION_RECONCILED_ABSENT
        assert row.exchange_status is None
        assert row.exchange_order_id is None
        assert row.resolved_at_utc == T3
        assert row.updated_at_utc == T3
        assert row.outcome is None  # the manager's outcome_* columns are not touched

    def test_intended_entry_is_finalized_never_sent(self, harness: ContractHarness) -> None:
        drive_entry(harness, ExecutionIntentStatus.INTENDED)
        finalize(harness, RESOLUTION_NEVER_SENT)
        row = _entry(harness)
        assert row.intent_status is ExecutionIntentStatus.REJECTED
        assert row.resolution_reason_code == RESOLUTION_NEVER_SENT
        assert row.exchange_status is None
        assert row.exchange_order_id is None
        assert row.sent_at_utc is None
        assert row.resolved_at_utc == T3

    def test_a_protective_leg_never_sent_is_finalized_too(self, harness: ContractHarness) -> None:
        drive_entry(harness, ExecutionIntentStatus.ACKED)
        assert harness.store.record_protective_intent(**harness.protective_args) is True
        finalize(harness, RESOLUTION_NEVER_SENT, role=STOP_LOSS)
        leg = harness.read(STOP_LOSS)
        assert leg is not None
        assert leg.intent_status is ExecutionIntentStatus.REJECTED
        assert leg.resolution_reason_code == RESOLUTION_NEVER_SENT
        assert _entry(harness).intent_status is ExecutionIntentStatus.ACKED

    # -- the two closings cannot be confused ----------------------------------------------

    def test_an_exchange_rejection_has_no_resolution_reason(self, harness: ContractHarness) -> None:
        drive_entry(harness, ExecutionIntentStatus.REJECTED)
        row = _entry(harness)
        assert row.intent_status is ExecutionIntentStatus.REJECTED
        assert row.exchange_status == "REJECTED"
        assert row.resolution_reason_code is None

    def test_a_reconciled_row_never_carries_the_reason_in_exchange_status(
        self, harness: ContractHarness
    ) -> None:
        drive_entry(harness, ExecutionIntentStatus.UNKNOWN)
        finalize(harness, RESOLUTION_RECONCILED_ABSENT)
        row = _entry(harness)
        assert row.exchange_status not in RESOLUTION_REASON_CODES
        assert row.exchange_status is None

    def test_the_two_closings_of_one_status_are_distinguishable(
        self, harness: ContractHarness
    ) -> None:
        drive_entry(harness, ExecutionIntentStatus.UNKNOWN)
        finalize(harness, RESOLUTION_RECONCILED_ABSENT)
        reconciled = _entry(harness)
        assert reconciled.intent_status is ExecutionIntentStatus.REJECTED
        assert reconciled.resolution_reason_code is not None

    def test_record_result_keeps_its_meaning_on_a_reconciled_row(
        self, harness: ContractHarness
    ) -> None:
        """A repeat of the same exchange status is still the idempotent no-op it always was."""
        drive_entry(harness, ExecutionIntentStatus.UNKNOWN)
        finalize(harness, RESOLUTION_RECONCILED_ABSENT)
        harness.store.record_result(
            approval_id=harness.approval_id,
            role=ENTRY,
            status=ExecutionIntentStatus.REJECTED,
            exchange_order_id=None,
            exchange_status="REJECTED",
            now_utc=T3 + timedelta(minutes=1),
        )
        row = _entry(harness)
        assert row.resolution_reason_code == RESOLUTION_RECONCILED_ABSENT
        assert row.exchange_status is None

    # -- refusals: wrong source status, nothing written -----------------------------------

    @pytest.mark.parametrize(
        "source",
        [
            ExecutionIntentStatus.INTENDED,
            ExecutionIntentStatus.SENT,
            ExecutionIntentStatus.ACKED,
            ExecutionIntentStatus.REJECTED,
        ],
    )
    def test_reconciled_absent_is_refused_unless_the_row_is_unknown(
        self, harness: ContractHarness, source: ExecutionIntentStatus
    ) -> None:
        drive_entry(harness, source)
        before = _entry(harness)
        with pytest.raises(IntentStateConflict):
            finalize(harness, RESOLUTION_RECONCILED_ABSENT)
        assert _entry(harness) == before

    @pytest.mark.parametrize(
        "source",
        [
            ExecutionIntentStatus.SENT,
            ExecutionIntentStatus.UNKNOWN,
            ExecutionIntentStatus.ACKED,
            ExecutionIntentStatus.REJECTED,
        ],
    )
    def test_never_sent_is_refused_unless_the_row_is_intended(
        self, harness: ContractHarness, source: ExecutionIntentStatus
    ) -> None:
        drive_entry(harness, source)
        before = _entry(harness)
        with pytest.raises(IntentStateConflict):
            finalize(harness, RESOLUTION_NEVER_SENT)
        assert _entry(harness) == before

    def test_a_missing_row_is_refused(self, harness: ContractHarness) -> None:
        with pytest.raises(IntentStateConflict):
            finalize(harness, RESOLUTION_NEVER_SENT)
        assert harness.read(ENTRY) is None

    @pytest.mark.parametrize(
        "code", [_NEVER_WRITTEN_BY_ANYONE, "", "reconciled_absent", "REJECTED", "UNKNOWN"]
    )
    def test_an_unknown_reason_code_is_refused_before_any_write(
        self, harness: ContractHarness, code: str
    ) -> None:
        drive_entry(harness, ExecutionIntentStatus.UNKNOWN)
        before = _entry(harness)
        with pytest.raises(ValueError):
            finalize(harness, code)
        assert _entry(harness) == before

    # -- repeats ---------------------------------------------------------------------------

    def test_an_identical_repeat_is_a_no_op(self, harness: ContractHarness) -> None:
        drive_entry(harness, ExecutionIntentStatus.UNKNOWN)
        finalize(harness, RESOLUTION_RECONCILED_ABSENT)
        first = _entry(harness)
        harness.store.finalize_reconciled_resolution(
            approval_id=harness.approval_id,
            role=ENTRY,
            reason_code=RESOLUTION_RECONCILED_ABSENT,
            now_utc=T3 + timedelta(hours=1),
        )
        assert _entry(harness) == first

    def test_a_repeat_with_the_other_code_is_refused(self, harness: ContractHarness) -> None:
        drive_entry(harness, ExecutionIntentStatus.UNKNOWN)
        finalize(harness, RESOLUTION_RECONCILED_ABSENT)
        first = _entry(harness)
        with pytest.raises(IntentStateConflict):
            finalize(harness, RESOLUTION_NEVER_SENT)
        assert _entry(harness) == first

    # -- the closed set ----------------------------------------------------------------------

    def test_the_reason_set_is_exactly_the_two_codes(self, harness: ContractHarness) -> None:
        assert frozenset({"RECONCILED_ABSENT", "NEVER_SENT"}) == RESOLUTION_REASON_CODES
        assert RESOLUTION_RECONCILED_ABSENT == "RECONCILED_ABSENT"
        assert RESOLUTION_NEVER_SENT == "NEVER_SENT"
