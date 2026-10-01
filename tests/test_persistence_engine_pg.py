"""UTC session pinning on both engines and the fail-closed unreachable server (D-04, F-406).

The domain constructors reject non-UTC offsets, so a session whose TimeZone drifted
(here: the database default is `Asia/Ho_Chi_Minh`) would break every read. Both the sync
persistence engine and the existing async engine (`src.db.models.make_engine`) must pin
`timezone=UTC` regardless of the database default.

psycopg async cannot run on the Windows Proactor loop, so the async check runs inside
`asyncio.run(..., loop_factory=asyncio.SelectorEventLoop)` (Phase 10 precedent).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool
from src.db.models import dispose_engine, make_engine
from src.persistence.engine import assert_session_utc, make_sync_engine
from src.persistence.errors import SessionTimeZoneNotUtc, StoreUnavailable

from tests.pg_support import assert_disposable_database_name, require_test_database_url

NON_UTC_ZONE = "Asia/Ho_Chi_Minh"


@pytest.fixture
def non_utc_db(pg_db: str) -> str:
    """A migrated disposable database whose DEFAULT session TimeZone is not UTC."""
    name = make_url(pg_db).database
    assert name is not None
    assert_disposable_database_name(name)
    admin = create_engine(pg_db, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as conn:
            conn.execute(text(f"ALTER DATABASE \"{name}\" SET timezone = '{NON_UTC_ZONE}'"))
    finally:
        admin.dispose()
    return pg_db


@pytest.fixture
def plain_engine(non_utc_db: str) -> Iterator[Engine]:
    eng = create_engine(non_utc_db, poolclass=NullPool)
    try:
        yield eng
    finally:
        eng.dispose()


def test_plain_engine_inherits_the_non_utc_database_default(plain_engine: Engine) -> None:
    """Control: without the pin the session really is on the other zone."""
    with plain_engine.connect() as conn:
        assert conn.execute(text("SHOW TimeZone")).scalar_one() == NON_UTC_ZONE
        with pytest.raises(SessionTimeZoneNotUtc):
            assert_session_utc(conn)


def test_sync_engine_sessions_are_utc_despite_the_database_default(non_utc_db: str) -> None:
    engine = make_sync_engine(non_utc_db)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SHOW TimeZone")).scalar_one() == "UTC"
            assert_session_utc(conn)
    finally:
        engine.dispose()


def test_timestamptz_reads_back_with_zero_offset(non_utc_db: str) -> None:
    written = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    engine = make_sync_engine(non_utc_db)
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TEMP TABLE tz_probe (at TIMESTAMPTZ NOT NULL)"))
            conn.execute(text("INSERT INTO tz_probe (at) VALUES (:at)"), {"at": written})
            read_back = conn.execute(text("SELECT at FROM tz_probe")).scalar_one()
    finally:
        engine.dispose()
    assert read_back == written
    assert read_back.utcoffset() == timedelta(0)

    # control: the same read through an unpinned session carries the other zone's offset
    plain = create_engine(non_utc_db, poolclass=NullPool)
    try:
        with plain.connect() as conn:
            conn.execute(text("CREATE TEMP TABLE tz_probe (at TIMESTAMPTZ NOT NULL)"))
            conn.execute(text("INSERT INTO tz_probe (at) VALUES (:at)"), {"at": written})
            shifted = conn.execute(text("SELECT at FROM tz_probe")).scalar_one()
    finally:
        plain.dispose()
    assert shifted == written
    assert shifted.utcoffset() == timedelta(hours=7)


def test_async_engine_sessions_are_utc_despite_the_database_default(non_utc_db: str) -> None:
    async def probe() -> tuple[str, timedelta | None]:
        engine = make_engine(non_utc_db)
        try:
            async with engine.connect() as conn:
                zone = (await conn.execute(text("SHOW TimeZone"))).scalar_one()
                stamp = (
                    await conn.execute(text("SELECT TIMESTAMPTZ '2026-09-19 12:00:00+00'"))
                ).scalar_one()
            return str(zone), stamp.utcoffset()
        finally:
            await dispose_engine(non_utc_db)

    zone, offset = asyncio.run(probe(), loop_factory=asyncio.SelectorEventLoop)
    assert zone == "UTC"
    assert offset == timedelta(0)


def test_unreachable_server_fails_closed_without_leaking_the_password() -> None:
    server = make_url(require_test_database_url())
    password = server.password or "synthetic-pw-5f3c9a"
    unreachable = server.set(host="127.0.0.1", port=1, password=password)
    url = unreachable.render_as_string(hide_password=False)
    with pytest.raises(StoreUnavailable) as info:
        make_sync_engine(url)
    assert password not in str(info.value)
    assert password not in repr(info.value)
    assert "OperationalError" in str(info.value)
