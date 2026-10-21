"""The reconciliation result contract against PostgreSQL (Phase 20, plan 20-03, T-B).

Runs the shared `IntentResultContract` (tests/test_intent_result_contract.py) against
`PgExecutionStateStore` on a generated `t17_<hex>_test` database cloned from an alembic-built
template (`tests/pg_support.py`, `alembic upgrade head`; never `create_all`). Rows are read back
through the same engine after each store call has committed, so only COMMITTED state is observed.

On top of the shared contract this module pins what only the database can prove: the named CHECK
`ck_execution_intents_resolution_reason` and the 0007 column in the catalog.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from src.db.models import ExecutionIntentRow
from src.domain.enums import ExecutionIntentStatus
from src.execution.intent_store import (
    RESOLUTION_NEVER_SENT,
    RESOLUTION_RECONCILED_ABSENT,
    IntentRecord,
)
from src.persistence.execution_state import _to_record

from tests.test_execution_exactly_once_pg import (
    APPROVAL_ID,
    _consume_args,
    _scalar,
    _seed_parent_chain,
    _store_on,
)
from tests.test_intent_result_contract import (
    T3,
    ContractHarness,
    IntentResultContract,
    default_protective_args,
    drive_entry,
    finalize,
)

_CHECK_VIOLATION = "23514"
_CHECK_NAME = "ck_execution_intents_resolution_reason"


def _protective_args() -> dict[str, Any]:
    args = default_protective_args(APPROVAL_ID)
    # The FK chain of the seeded fixture: the same trade plan as the ENTRY args.
    args["trade_plan_id"] = _consume_args()["trade_plan_id"]
    args["plan_hash"] = _consume_args()["plan_hash"]
    return args


class TestPgIntentResultContract(IntentResultContract):
    @pytest.fixture
    def harness(self, pg_db: str) -> Iterator[ContractHarness]:
        with _store_on(pg_db) as (engine, store):
            _seed_parent_chain(engine)

            def read(role: str) -> IntentRecord | None:
                with Session(engine) as session:
                    row = session.execute(
                        select(ExecutionIntentRow).where(
                            ExecutionIntentRow.approval_id == APPROVAL_ID,
                            ExecutionIntentRow.role == role,
                        )
                    ).scalar_one_or_none()
                    return None if row is None else _to_record(row)

            yield ContractHarness(
                store=store,
                approval_id=APPROVAL_ID,
                entry_args=_consume_args(),
                protective_args=_protective_args(),
                read=read,
            )


# --------------------------------------------------------------------------------------------
# Database-only proofs.
# --------------------------------------------------------------------------------------------


def test_a_reconciled_absence_is_read_back_through_a_second_engine(pg_db: str) -> None:
    """The tracer: UNKNOWN ENTRY -> RECONCILED_ABSENT, read back with its reason."""
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        harness = ContractHarness(
            store=store,
            approval_id=APPROVAL_ID,
            entry_args=_consume_args(),
            protective_args=_protective_args(),
            read=lambda role: None,
        )
        drive_entry(harness, ExecutionIntentStatus.UNKNOWN)
        finalize(harness, RESOLUTION_RECONCILED_ABSENT)
    with _store_on(pg_db) as (_engine2, store2):
        row = store2.get_entry(approval_id=APPROVAL_ID)
    assert row is not None
    assert row.intent_status is ExecutionIntentStatus.REJECTED
    assert row.resolution_reason_code == RESOLUTION_RECONCILED_ABSENT
    assert row.exchange_status is None
    assert row.exchange_order_id is None
    assert row.resolved_at_utc == T3


def test_the_column_is_nullable_varchar_32(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, _store):
        column = engine.connect().execute(
            text(
                "SELECT data_type, character_maximum_length, is_nullable "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'execution_intents' AND column_name = 'resolution_reason_code'"
            )
        )
        assert tuple(column.one()) == ("character varying", 32, "YES")


def _write_reason_directly(engine: Engine, *, status: str, reason: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE execution_intents SET intent_status = :s, resolution_reason_code = :r "
                "WHERE approval_id = :a AND role = 'ENTRY'"
            ),
            {"s": status, "r": reason, "a": APPROVAL_ID},
        )


@pytest.mark.parametrize("status", ["INTENDED", "SENT", "ACKED", "UNKNOWN"])
def test_the_check_refuses_a_reason_on_any_status_but_rejected(pg_db: str, status: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_args()) is True
        with pytest.raises(IntegrityError) as raised:
            _write_reason_directly(engine, status=status, reason=RESOLUTION_RECONCILED_ABSENT)
        orig: Any = raised.value.orig
        assert orig.sqlstate == _CHECK_VIOLATION
        assert orig.diag.constraint_name == _CHECK_NAME


def test_the_check_refuses_a_reason_outside_the_closed_set(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_args()) is True
        with pytest.raises(IntegrityError) as raised:
            _write_reason_directly(engine, status="REJECTED", reason="ABSENT_BY_GUESS")
        orig: Any = raised.value.orig
        assert orig.sqlstate == _CHECK_VIOLATION
        assert orig.diag.constraint_name == _CHECK_NAME


@pytest.mark.parametrize("reason", [RESOLUTION_RECONCILED_ABSENT, RESOLUTION_NEVER_SENT])
def test_the_check_accepts_both_codes_on_a_rejected_row(pg_db: str, reason: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_args()) is True
        _write_reason_directly(engine, status="REJECTED", reason=reason)
        stored = _scalar(
            engine,
            "SELECT resolution_reason_code FROM execution_intents WHERE approval_id = :a",
            a=APPROVAL_ID,
        )
    assert stored == reason


def test_a_rejected_row_without_a_reason_stays_valid(pg_db: str) -> None:
    """A Binance rejection (record_result) is a REJECTED row with a NULL reason."""
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        harness = ContractHarness(
            store=store,
            approval_id=APPROVAL_ID,
            entry_args=_consume_args(),
            protective_args=_protective_args(),
            read=lambda role: None,
        )
        drive_entry(harness, ExecutionIntentStatus.REJECTED)
        stored = _scalar(
            engine,
            "SELECT resolution_reason_code FROM execution_intents WHERE approval_id = :a",
            a=APPROVAL_ID,
        )
    assert stored is None


def test_the_terminal_trigger_still_blocks_moving_a_closed_row(pg_db: str) -> None:
    """REJECTED stays terminal in the database (0004): the closing cannot be undone by SQL."""
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        harness = ContractHarness(
            store=store,
            approval_id=APPROVAL_ID,
            entry_args=_consume_args(),
            protective_args=_protective_args(),
            read=lambda role: None,
        )
        drive_entry(harness, ExecutionIntentStatus.UNKNOWN)
        finalize(harness, RESOLUTION_RECONCILED_ABSENT)
        with pytest.raises(DBAPIError) as raised:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE execution_intents SET intent_status = 'UNKNOWN', "
                        "resolution_reason_code = NULL "
                        "WHERE approval_id = :a AND role = 'ENTRY'"
                    ),
                    {"a": APPROVAL_ID},
                )
        assert "terminal" in str(raised.value)
