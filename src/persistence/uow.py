"""Unit of work for operational PostgreSQL (Phase 17, D-03).

`OperationalDatabase.transaction()` is the only way stores write: every multi-row
change that must be atomic commits in ONE transaction, and a connection-level
failure surfaces as `StoreUnavailable` (fail closed, D-04), never as a retry.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from src.persistence.errors import StoreFailure, StoreUnavailable


class OperationalDatabase:
    """Owns an engine and hands out explicit transactions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Yield a Session inside `session.begin()`: commit on success, roll back on error.

        Connection-level `OperationalError` / `InterfaceError` become `StoreUnavailable`
        (carrying only the exception type). Constraint violations (`IntegrityError`)
        propagate unchanged for the calling store to translate. Every other database
        error (read-only transaction after a failover, a trigger `RAISE EXCEPTION`, an
        out-of-range value) becomes `StoreFailure`, so callers that fail closed on
        `PersistenceError` never see a raw driver exception (17-REVIEW WR-01). Both typed
        messages name exception types only and drop the cause (`from None`): the
        SQLAlchemy message carries the SQL text and its parameters.
        """
        try:
            with Session(self._engine, expire_on_commit=False) as session, session.begin():
                yield session
        except IntegrityError:
            raise
        except (OperationalError, InterfaceError) as exc:
            raise StoreUnavailable(
                f"PostgreSQL unavailable during transaction ({type(exc).__name__})"
            ) from None
        except DBAPIError as exc:
            driver_error = type(exc.orig).__name__ if exc.orig is not None else "unknown"
            raise StoreFailure(
                f"PostgreSQL error during transaction ({type(exc).__name__}/{driver_error})"
            ) from None

    def dispose(self) -> None:
        """Close every pooled connection."""
        self._engine.dispose()
