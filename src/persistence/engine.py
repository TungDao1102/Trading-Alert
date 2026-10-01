"""Synchronous engine factory for operational PostgreSQL (Phase 17, D-01/D-04, F-406).

Every connection is pinned to `TimeZone=UTC` at the libpq level (psycopg returns
`timestamptz` in the session TimeZone and the domain constructors reject non-UTC
offsets, so a drifting session would not shift values, it would break every
read), uses `pool_pre_ping`, and bounds every wait the single asyncio thread can
block on (17-REVIEW WR-02):

  - connecting: libpq `connect_timeout` (`DEFAULT_CONNECT_TIMEOUT_S`);
  - a lock wait: `lock_timeout` (`DEFAULT_LOCK_TIMEOUT_MS`);
  - a running statement: `statement_timeout` (`DEFAULT_STATEMENT_TIMEOUT_MS`);
  - waiting for a pooled connection: `pool_timeout` (`DEFAULT_POOL_TIMEOUT_S`);
  - a half-open or blackholed TCP connection: keepalives plus `tcp_user_timeout`
    (`DEFAULT_KEEPALIVE_*`, `DEFAULT_TCP_USER_TIMEOUT_MS`; the latter is honoured on
    Linux and ignored elsewhere).

A timeout surfaces as a connection-level error and therefore as `StoreUnavailable`
(a statement timeout is a `QueryCanceled`, an `OperationalError`).

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
# Store calls are short indexed queries; 10 s is well above any healthy statement and
# well below the OS TCP timeout, so a stuck query cannot hold the event loop for minutes.
DEFAULT_STATEMENT_TIMEOUT_MS = 10_000
# libpq connect timeout in whole seconds (a blackholed host fails after this, not after ~minutes).
DEFAULT_CONNECT_TIMEOUT_S = 3
# SQLAlchemy QueuePool wait for a free connection (library default is 30 s).
DEFAULT_POOL_TIMEOUT_S = 5
# TCP keepalive: probe after 30 s idle, every 10 s, drop after 3 misses (~60 s worst case).
DEFAULT_KEEPALIVE_IDLE_S = 30
DEFAULT_KEEPALIVE_INTERVAL_S = 10
DEFAULT_KEEPALIVE_COUNT = 3
# Unacknowledged-data bound (Linux TCP_USER_TIMEOUT; libpq ignores it where unsupported).
DEFAULT_TCP_USER_TIMEOUT_MS = 15_000
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


def build_connect_args(
    *,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    connect_timeout_s: int = DEFAULT_CONNECT_TIMEOUT_S,
) -> dict[str, str | int]:
    """The psycopg connect arguments: UTC pin, bounded waits and TCP keepalives."""
    for name, value in (
        ("lock_timeout_ms", lock_timeout_ms),
        ("statement_timeout_ms", statement_timeout_ms),
        ("connect_timeout_s", connect_timeout_s),
    ):
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    return {
        "options": (
            f"-c timezone=UTC -c lock_timeout={int(lock_timeout_ms)} "
            f"-c statement_timeout={int(statement_timeout_ms)}"
        ),
        "connect_timeout": int(connect_timeout_s),
        "keepalives": 1,
        "keepalives_idle": DEFAULT_KEEPALIVE_IDLE_S,
        "keepalives_interval": DEFAULT_KEEPALIVE_INTERVAL_S,
        "keepalives_count": DEFAULT_KEEPALIVE_COUNT,
        "tcp_user_timeout": DEFAULT_TCP_USER_TIMEOUT_MS,
    }


def make_sync_engine(
    database_url: str,
    *,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    connect_timeout_s: int = DEFAULT_CONNECT_TIMEOUT_S,
    pool_timeout_s: int = DEFAULT_POOL_TIMEOUT_S,
) -> Engine:
    """Build a sync engine with UTC pinned, verified once, failing closed.

    Raises:
        ValueError: the URL does not select the psycopg driver.
        StoreUnavailable: the database cannot be reached.
        SessionTimeZoneNotUtc: the probe connection is not on UTC.
    """
    if pool_timeout_s <= 0:
        raise ValueError("pool_timeout_s must be positive")
    connect_args = build_connect_args(
        lock_timeout_ms=lock_timeout_ms,
        statement_timeout_ms=statement_timeout_ms,
        connect_timeout_s=connect_timeout_s,
    )
    url = make_url(_normalize_url(database_url))
    safe_url = url.render_as_string(hide_password=True)
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=pool_timeout_s,
        connect_args=connect_args,
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
