"""`OperationalDatabase.transaction()` error mapping against real PostgreSQL (17-REVIEW WR-01).

Every database error that is not a constraint violation must surface as a typed
`PersistenceError` (so the execution manager fails closed instead of crashing between the
entry acknowledgement and the stop loss), with a message that names exception types only.
`IntegrityError` keeps propagating raw because the stores translate it themselves.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from src.domain.journal import JournalEvent, content_hash_event_id
from src.persistence.engine import make_sync_engine
from src.persistence.errors import PersistenceError, StoreFailure
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import T0

SECRET_PARAMETER = "987654321"


def _event() -> JournalEvent:
    payload_json = '{"n":1}'
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="t",
            event_type="TEST_EVENT",
            entity_id="entity-1",
            occurred_at_utc=T0,
            payload_json=payload_json,
        ),
        occurred_at_utc=T0,
        event_type="TEST_EVENT",
        entity_type="Test",
        entity_id="entity-1",
        correlation_id="corr-1",
        payload_json=payload_json,
    )


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def db(engine: Engine) -> OperationalDatabase:
    return OperationalDatabase(engine)


def test_a_read_only_transaction_write_becomes_store_failure(db: OperationalDatabase) -> None:
    """A write against a read-only session (replica after a failover) is a typed failure."""
    with pytest.raises(StoreFailure) as info, db.transaction() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("CREATE TABLE uow_probe (a integer)"))

    assert isinstance(info.value, PersistenceError)
    assert "InternalError" in str(info.value)
    assert "ReadOnlySqlTransaction" in str(info.value)
    assert "uow_probe" not in str(info.value)


def test_a_trigger_raise_exception_becomes_store_failure(db: OperationalDatabase) -> None:
    """The append-only trigger's RAISE EXCEPTION (ProgrammingError) is a typed failure."""
    PgJournalStore(db).record(_event())

    with pytest.raises(StoreFailure) as info, db.transaction() as session:
        session.execute(text("UPDATE journal_events SET event_type = 'TAMPERED'"))

    assert "ProgrammingError" in str(info.value)
    assert "TAMPERED" not in str(info.value)
    assert "append-only" not in str(info.value)  # the trigger text is not echoed


def test_an_out_of_range_value_becomes_store_failure_without_parameters(
    db: OperationalDatabase,
) -> None:
    with pytest.raises(StoreFailure) as info, db.transaction() as session:
        session.execute(text("SELECT CAST(:v AS numeric(3, 0))"), {"v": SECRET_PARAMETER})

    assert "DataError" in str(info.value)
    assert SECRET_PARAMETER not in str(info.value)
    assert "SELECT" not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


def test_an_integrity_violation_still_propagates_raw_for_the_stores(
    db: OperationalDatabase,
) -> None:
    with pytest.raises(IntegrityError), db.transaction() as session:
        session.execute(text("CREATE TEMP TABLE uow_dup (a integer PRIMARY KEY)"))
        session.execute(text("INSERT INTO uow_dup VALUES (1)"))
        session.execute(text("INSERT INTO uow_dup VALUES (1)"))


def test_the_database_stays_usable_after_a_mapped_failure(db: OperationalDatabase) -> None:
    with pytest.raises(StoreFailure), db.transaction() as session:
        session.execute(text("SELECT CAST(:v AS numeric(3, 0))"), {"v": SECRET_PARAMETER})

    with db.transaction() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
