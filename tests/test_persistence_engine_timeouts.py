"""Bounded waits on the sync persistence engine (17-REVIEW WR-02).

The store is synchronous and runs on the asyncio thread, so every wait it can block on
needs a bound: connect, lock wait, statement, pool checkout and a half-open TCP socket.
The numeric defaults live in named constants in `src.persistence.engine`; every one is
overridable by an argument.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.persistence import engine as engine_module
from src.persistence.engine import make_sync_engine
from src.persistence.errors import StoreUnavailable
from src.persistence.uow import OperationalDatabase

SECRET = "pw-not-in-messages"
# RFC 5737 TEST-NET-1: never routed, so a connect either blackholes or fails at once.
UNREACHABLE_URL = f"postgresql+psycopg://trading:{SECRET}@192.0.2.1:5432/trading"


def test_connect_args_carry_every_bound_and_the_utc_pin() -> None:
    args = engine_module.build_connect_args()

    options = str(args["options"])
    assert "-c timezone=UTC" in options
    assert f"-c lock_timeout={engine_module.DEFAULT_LOCK_TIMEOUT_MS}" in options
    assert f"-c statement_timeout={engine_module.DEFAULT_STATEMENT_TIMEOUT_MS}" in options
    assert args["connect_timeout"] == engine_module.DEFAULT_CONNECT_TIMEOUT_S
    assert args["keepalives"] == 1
    assert args["keepalives_idle"] == engine_module.DEFAULT_KEEPALIVE_IDLE_S
    assert args["keepalives_interval"] == engine_module.DEFAULT_KEEPALIVE_INTERVAL_S
    assert args["keepalives_count"] == engine_module.DEFAULT_KEEPALIVE_COUNT
    assert args["tcp_user_timeout"] == engine_module.DEFAULT_TCP_USER_TIMEOUT_MS


def test_connect_args_are_overridable_and_reject_non_positive_values() -> None:
    args = engine_module.build_connect_args(
        lock_timeout_ms=111, statement_timeout_ms=222, connect_timeout_s=7
    )
    assert "-c lock_timeout=111" in str(args["options"])
    assert "-c statement_timeout=222" in str(args["options"])
    assert args["connect_timeout"] == 7
    for bad in ({"lock_timeout_ms": 0}, {"statement_timeout_ms": -1}, {"connect_timeout_s": 0}):
        with pytest.raises(ValueError):
            engine_module.build_connect_args(**bad)  # type: ignore[arg-type]


def test_an_unreachable_host_fails_within_the_bound_without_the_password() -> None:
    started = time.monotonic()
    with pytest.raises(StoreUnavailable) as info:
        make_sync_engine(UNREACHABLE_URL, connect_timeout_s=1)
    elapsed = time.monotonic() - started

    assert elapsed < 8.0, f"connect was not bounded: {elapsed:.1f}s"
    assert SECRET not in str(info.value)


@pytest.fixture
def short_engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db, statement_timeout_ms=300, lock_timeout_ms=400, pool_timeout_s=2)
    try:
        yield eng
    finally:
        eng.dispose()


def test_session_settings_and_pool_timeout_reach_the_connection(short_engine: Engine) -> None:
    with short_engine.connect() as conn:
        assert conn.execute(text("SHOW statement_timeout")).scalar_one() == "300ms"
        assert conn.execute(text("SHOW lock_timeout")).scalar_one() == "400ms"
        assert conn.execute(text("SHOW TimeZone")).scalar_one() == "UTC"
    assert short_engine.pool.timeout() == 2  # type: ignore[attr-defined]


def test_a_slow_statement_is_cancelled_as_store_unavailable(short_engine: Engine) -> None:
    db = OperationalDatabase(short_engine)
    started = time.monotonic()
    with pytest.raises(StoreUnavailable), db.transaction() as session:
        session.execute(text("SELECT pg_sleep(5)"))
    assert time.monotonic() - started < 3.0
