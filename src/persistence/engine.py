"""Synchronous engine factory for operational PostgreSQL (Phase 17, D-01/D-04, F-406).

Every connection is pinned to `TimeZone=UTC` at the libpq level (psycopg returns
`timestamptz` in the session TimeZone and the domain constructors reject non-UTC
offsets, so a drifting session would not shift values, it would break every
read), uses `pool_pre_ping`, and bounds lock waits with `lock_timeout`.

Fail closed (D-04, T-17-04): an unreachable database raises `StoreUnavailable`;
there is no in-memory fallback. The message names only the exception type and the
URL rendered with `hide_password=True` (T-17-03).
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import InterfaceError, OperationalError

from src.persistence.errors import SessionTimeZoneNotUtc, StoreUnavailable

DEFAULT_LOCK_TIMEOUT_MS = 5000
_PSYCOPG_SCHEME = "postgresql+psycopg"


def _normalize_url(database_url: str) -> str:
    """Select the psycopg 3 driver; refuse any other (psycopg2 is not a dependency)."""
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", f"{_PSYCOPG_SCHEME}://", 1)
    if not database_url.startswith(f"{_PSYCOPG_SCHEME}://"):
        raise ValueError(
            f"refusing engine: expected a {_PSYCOPG_SCHEME}:// URL "
            "(no other driver is supported for operational state)"
        )
    return database_url


def assert_session_utc(connection: Connection) -> None:
    """Raise `SessionTimeZoneNotUtc` unless the session reports TimeZone UTC."""
    zone = connection.execute(text("SHOW TimeZone")).scalar_one()
    if zone != "UTC":
        raise SessionTimeZoneNotUtc(f"session TimeZone is {zone!r}, expected 'UTC'")


def make_sync_engine(
    database_url: str, *, lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS
) -> Engine:
    """Build a sync engine with UTC pinned, verified once, failing closed.

    Raises:
        ValueError: the URL does not select the psycopg driver.
        StoreUnavailable: the database cannot be reached.
        SessionTimeZoneNotUtc: the probe connection is not on UTC.
    """
    if lock_timeout_ms <= 0:
        raise ValueError("lock_timeout_ms must be positive")
    url = make_url(_normalize_url(database_url))
    safe_url = url.render_as_string(hide_password=True)
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"options": f"-c timezone=UTC -c lock_timeout={int(lock_timeout_ms)}"},
    )
    try:
        with engine.connect() as probe:
            assert_session_utc(probe)
    except (OperationalError, InterfaceError) as exc:
        engine.dispose()
        raise StoreUnavailable(
            f"cannot reach PostgreSQL at {safe_url} ({type(exc).__name__})"
        ) from None
    except SessionTimeZoneNotUtc:
        engine.dispose()
        raise
    return engine
