"""`PgExecutionStateStore.restorable_entries` against PostgreSQL (plan 24-27B, DECISIONS D093).

ENTRY rows in SENT, UNKNOWN and ACKED are restorable only while their plan has not ended: a
`PROTECTION_TRANSITION` journal row into FLAT or ENTRY_ENDED_NO_FILL ends it. No age number.

NOT RUN on the machine that wrote it (no PostgreSQL, TEST_DATABASE_URL forbidden to the author);
the orchestrator runs the `_pg` suite. The SQL itself is compiled for the PostgreSQL dialect by
tests/test_live_wiring_parts.py.
"""

from __future__ import annotations

import json
from decimal import Decimal

from src.domain.enums import ExecutionIntentStatus
from src.domain.journal import JournalEvent, correlated_event_id
from src.execution.protection import EVENT_PROTECTION_TRANSITION
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

from tests.test_execution_exactly_once_pg import (
    APPROVAL_ID,
    CASE,
    ENTRY_CLIENT_ID,
    NOW_UTC,
    PLAN_HASH,
    _seed_parent_chain,
    _store_on,
)


def _transition(db: OperationalDatabase, new_state: str, seq: int) -> None:
    payload = json.dumps(
        {"from": "X", "reason": "TEST_ONLY", "seq": seq, "to": new_state},
        sort_keys=True,
        separators=(",", ":"),
    )
    correlation = f"protection_{PLAN_HASH}"
    PgJournalStore(db).record(
        JournalEvent(
            journal_event_id=correlated_event_id(
                prefix="pnt",
                correlation_id=correlation,
                event_type=EVENT_PROTECTION_TRANSITION,
                entity_id=PLAN_HASH,
                step=f"{seq}:{new_state}",
            ),
            occurred_at_utc=NOW_UTC,
            event_type=EVENT_PROTECTION_TRANSITION,
            entity_type="ProtectionState",
            entity_id=PLAN_HASH,
            correlation_id=correlation,
            payload_json=payload,
        )
    )


def _acked_entry(store: object) -> None:
    assert store.consume_and_record_entry_intent(  # type: ignore[attr-defined]
        approval_id=APPROVAL_ID,
        trade_plan_id=CASE["trade_plan_id"],
        plan_hash=PLAN_HASH,
        client_order_id=ENTRY_CLIENT_ID,
        symbol=CASE["symbol"],
        side="BUY",
        intended_quantity=Decimal("2.415"),
        intended_price=Decimal(str(CASE["expected_limit_price"])),
        approved_quantity=Decimal("2.415"),
        now_utc=NOW_UTC,
    )
    store.mark_sent(approval_id=APPROVAL_ID, role="ENTRY", now_utc=NOW_UTC)  # type: ignore[attr-defined]
    store.record_result(  # type: ignore[attr-defined]
        approval_id=APPROVAL_ID,
        role="ENTRY",
        status=ExecutionIntentStatus.ACKED,
        exchange_order_id="ex-1",
        exchange_status="NEW",
        now_utc=NOW_UTC,
    )


def test_an_acked_entry_is_restorable_until_its_plan_ends(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        _acked_entry(store)
        db = OperationalDatabase(engine)
        assert [r.approval_id for r in store.restorable_entries()] == [APPROVAL_ID]

        _transition(db, "UNPROTECTED", 1)
        _transition(db, "PROTECTED", 2)
        assert [r.approval_id for r in store.restorable_entries()] == [APPROVAL_ID], (
            "a protected plan has not ended"
        )

        _transition(db, "FLAT", 3)
        assert store.restorable_entries() == ()


def test_an_entry_that_ended_without_a_fill_is_not_restorable(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        _acked_entry(store)
        _transition(OperationalDatabase(engine), "ENTRY_ENDED_NO_FILL", 1)
        assert store.restorable_entries() == ()


def test_another_plans_end_does_not_hide_this_entry(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        _acked_entry(store)
        other = f"protection_{'0' * 64}"
        PgJournalStore(OperationalDatabase(engine)).record(
            JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix="pnt",
                    correlation_id=other,
                    event_type=EVENT_PROTECTION_TRANSITION,
                    entity_id="0" * 64,
                    step="1:FLAT",
                ),
                occurred_at_utc=NOW_UTC,
                event_type=EVENT_PROTECTION_TRANSITION,
                entity_type="ProtectionState",
                entity_id="0" * 64,
                correlation_id=other,
                payload_json='{"to":"FLAT"}',
            )
        )
        assert [r.approval_id for r in store.restorable_entries()] == [APPROVAL_ID]
