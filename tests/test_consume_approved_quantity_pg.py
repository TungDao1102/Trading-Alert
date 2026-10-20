"""The consume transaction re-checks the stored approved quantity (19-REVIEW WR-01 follow-up).

Quick task 261020-q2d, DECISIONS D078 (5). `bind_plan` compares the plan quantity with the
`Approval` object's `approved_quantity`, and that object is supplied by the caller. The consume
transaction (`PgExecutionStateStore.consume_and_record_entry_intent`) therefore reads the stored
`approvals.approved_quantity` itself, under `FOR UPDATE`, after the intent INSERT and before the
consuming UPDATE: it must be NOT NULL, equal to the quantity the manager bound and at least the
quantity about to be placed. Otherwise `ApprovedQuantityRefused` is raised inside the
transaction, the intent INSERT rolls back, the approval stays UNCONSUMED, and the manager
answers `APPROVED_QUANTITY_NOT_CONFIRMED` with no exchange call.

A replay (the ENTRY row already exists) still answers False before any quantity is read, so a
redelivered callback replays to the stored outcome exactly as before.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from src.db.mappers import approval_to_row
from src.domain.enums import ApprovalAction, ApprovalResult
from src.execution.manager import APPROVED_QUANTITY_NOT_CONFIRMED, ExecutionOutcome
from src.persistence.errors import ApprovedQuantityRefused, IntentStateConflict

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.test_execution_exactly_once_pg import (
    APPROVAL_ID,
    CASE,
    _consume_args,
    _scalar,
    _seed_parent_chain,
    _store_on,
)
from tests.test_execution_manager import _build_approval, _run_plan

# The fixture's approved quantity (the plan's quantity_after_rounding, D078).
STORED = Decimal("2.415")


def _set_stored_quantity(engine: Engine, value: Decimal | None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE approvals SET approved_quantity = :q WHERE approval_id = :a"),
            {"q": value, "a": APPROVAL_ID},
        )


def _args(**overrides: Any) -> dict[str, Any]:
    args = {**_consume_args(), "approved_quantity": STORED}
    args.update(overrides)
    return args


def _assert_nothing_consumed(engine: Engine) -> None:
    assert _scalar(engine, "SELECT count(*) FROM execution_intents") == 0
    assert (
        _scalar(
            engine,
            "SELECT consumption_status FROM approvals WHERE approval_id = :a",
            a=APPROVAL_ID,
        )
        == "UNCONSUMED"
    )


# --------------------------------------------------------------------------- #
# Store level.
# --------------------------------------------------------------------------- #


def test_the_seeded_row_stores_the_fixture_quantity(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, _store):
        _seed_parent_chain(engine)
        stored = _scalar(
            engine, "SELECT approved_quantity FROM approvals WHERE approval_id = :a", a=APPROVAL_ID
        )
        assert stored == STORED


def test_consume_wins_when_the_stored_quantity_confirms_the_order(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_args()) is True
        assert _scalar(engine, "SELECT count(*) FROM execution_intents") == 1


def test_consume_accepts_a_placed_quantity_below_the_stored_one(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert (
            store.consume_and_record_entry_intent(**_args(intended_quantity=Decimal("2.414")))
            is True
        )


def test_consume_compares_numerically_not_by_scale(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert (
            store.consume_and_record_entry_intent(
                **_args(approved_quantity=Decimal("2.415000"), intended_quantity=Decimal("2.4150"))
            )
            is True
        )


def test_consume_refuses_a_row_that_stores_no_quantity(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        _set_stored_quantity(engine, None)
        with pytest.raises(ApprovedQuantityRefused):
            store.consume_and_record_entry_intent(**_args())
        _assert_nothing_consumed(engine)


@pytest.mark.parametrize("stored", [Decimal("2.414"), Decimal("2.416"), Decimal("99")])
def test_consume_refuses_a_stored_quantity_that_differs_from_the_bound_one(
    pg_db: str, stored: Decimal
) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        _set_stored_quantity(engine, stored)
        with pytest.raises(ApprovedQuantityRefused):
            store.consume_and_record_entry_intent(**_args(intended_quantity=Decimal("2.000")))
        _assert_nothing_consumed(engine)


def test_consume_refuses_a_placed_quantity_above_the_stored_one(pg_db: str) -> None:
    """The caller's bound and the stored value agree, yet the order would exceed them."""
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with pytest.raises(ApprovedQuantityRefused):
            store.consume_and_record_entry_intent(
                **_args(intended_quantity=STORED + Decimal("1e-18"))
            )
        _assert_nothing_consumed(engine)


def test_the_refusal_is_an_intent_state_conflict_for_every_other_caller(pg_db: str) -> None:
    """A caller that only knows `IntentStateConflict` still fails closed."""
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        _set_stored_quantity(engine, None)
        with pytest.raises(IntentStateConflict):
            store.consume_and_record_entry_intent(**_args())


def test_a_row_that_is_not_approved_keeps_the_plain_conflict(pg_db: str) -> None:
    """The existing state checks come first; only an APPROVED, unconsumed row is judged on size."""
    # A terminal approval status cannot move back (DB trigger), so a second, PENDING approval of
    # the same plan, storing no quantity, is the row that is not approved.
    pending = replace(
        _build_approval(CASE),
        approval_id="apprv_pending_same_plan",
        action=ApprovalAction.SIMULATE,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash="f" * 64,
        acted_at_utc=None,
        approved_quantity=None,
    )
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with Session(engine) as session, session.begin():
            session.add(approval_to_row(pending))
        with pytest.raises(IntentStateConflict) as caught:
            store.consume_and_record_entry_intent(**_args(approval_id=pending.approval_id))
        assert not isinstance(caught.value, ApprovedQuantityRefused)
        _assert_nothing_consumed(engine)


def test_a_replay_answers_false_before_any_quantity_is_read(pg_db: str) -> None:
    """At-least-once delivery: the second call replays, whatever the row stores now."""
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_args()) is True
        _set_stored_quantity(engine, None)
        assert store.consume_and_record_entry_intent(**_args()) is False
        assert (
            store.consume_and_record_entry_intent(**_args(approved_quantity=Decimal("99"))) is False
        )
        assert _scalar(engine, "SELECT count(*) FROM execution_intents") == 1


def test_a_refused_consume_can_be_retried_once_the_row_confirms(pg_db: str) -> None:
    """The refusal rolled everything back: no half-written intent blocks a later valid consume."""
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        _set_stored_quantity(engine, Decimal("2.000"))
        with pytest.raises(ApprovedQuantityRefused):
            store.consume_and_record_entry_intent(**_args())
        _set_stored_quantity(engine, STORED)
        assert store.consume_and_record_entry_intent(**_args()) is True


# --------------------------------------------------------------------------- #
# Manager level: the caller-supplied Approval says 2.415, the database does not.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("stored", [None, Decimal("2.000"), Decimal("2.416")])
async def test_manager_refuses_when_the_database_does_not_confirm_the_quantity(
    pg_db: str, stored: Decimal | None
) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        _set_stored_quantity(engine, stored)
        outcome = await _run_plan(adapter, intent_store=store)
        assert outcome == ExecutionOutcome(
            is_no_trade=True, reason_code=APPROVED_QUANTITY_NOT_CONFIRMED
        )
        assert adapter.calls_to("place_entry") == []
        assert adapter.calls_to("place_algo_protective") == []
        _assert_nothing_consumed(engine)


async def test_manager_places_once_when_the_database_confirms_the_quantity(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        outcome = await _run_plan(adapter, intent_store=store)
        assert outcome == ExecutionOutcome(is_no_trade=False, reason_code="OK")
        assert len(adapter.calls_to("place_entry")) == 1


async def test_manager_replay_is_unchanged_by_the_quantity_check(pg_db: str) -> None:
    """A consumed approval replays to its stored outcome with zero adapter calls (D-15)."""
    adapter = BinanceSemanticsFakeAdapter()
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        first = await _run_plan(adapter, intent_store=store)
        calls_after_first = len(adapter.calls)
        _set_stored_quantity(engine, None)
        second = await _run_plan(adapter, intent_store=store)
        assert second == first
        assert len(adapter.calls) == calls_after_first
