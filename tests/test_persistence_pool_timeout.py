"""R-24 (D-13): a pool exhaustion inside `OperationalDatabase.transaction()` is a typed outage.

Since CR-01 the wait for a pooled connection is bounded, but the SQLAlchemy `TimeoutError` it
raises is not a `DBAPIError`, so no clause of `transaction()` caught it and it escaped the
execution manager as a raw exception after the approval was consumed. It must surface as
`StoreUnavailable` carrying the exception type name only (no SQL text, no cause).

SQLite stands in for PostgreSQL here: the pool is SQLAlchemy's own `QueuePool`, so the failure
is the same one. The PostgreSQL variant lives in `tests/test_persistence_uow_pg.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.pool import QueuePool
from src.persistence.errors import StoreUnavailable
from src.persistence.uow import OperationalDatabase

MARKER_SQL = "select 1 as pool_timeout_marker"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(
        f"sqlite:///{tmp_path / 'pool.db'}",
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    try:
        yield eng
    finally:
        eng.dispose()


def test_an_exhausted_pool_is_store_unavailable_with_the_type_name_only(engine: Engine) -> None:
    db = OperationalDatabase(engine)

    with engine.connect(), pytest.raises(StoreUnavailable) as info, db.transaction() as session:
        session.execute(text(MARKER_SQL))

    assert "TimeoutError" in str(info.value)
    assert "pool_timeout_marker" not in str(info.value)
    assert "select" not in str(info.value).lower()
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


def test_the_raw_pool_timeout_is_not_what_the_caller_sees(engine: Engine) -> None:
    db = OperationalDatabase(engine)

    with engine.connect():
        try:
            with db.transaction() as session:
                session.execute(text(MARKER_SQL))
        except SQLAlchemyTimeoutError:  # pragma: no cover - the regression this test guards
            pytest.fail("a raw sqlalchemy TimeoutError escaped transaction()")
        except StoreUnavailable:
            pass
        else:  # pragma: no cover
            pytest.fail("transaction() did not fail while the only connection was held")


def test_the_same_transaction_succeeds_once_the_held_connection_closes(engine: Engine) -> None:
    db = OperationalDatabase(engine)

    with engine.connect(), pytest.raises(StoreUnavailable), db.transaction() as session:
        session.execute(text(MARKER_SQL))

    with db.transaction() as session:
        assert session.execute(text("select 1")).scalar_one() == 1
