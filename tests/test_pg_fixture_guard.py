"""Guards for the disposable-database fixtures and the strict-skip policy (Phase 17-01, SC5).

The PostgreSQL battery must (a) never touch anything but generated `t17_*_test`
databases, and (b) never pass vacuously in CI: a missing `TEST_DATABASE_URL` skips
loudly on a laptop and FAILS under `TRADING_CI_STRICT=1` (research C9, F-606).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests import pg_support
from tests.infra_helpers import STRICT_ENV
from tests.pg_support import (
    assert_disposable_database_name,
    require_test_database_url,
)

# --------------------------------------------------------------------------- #
# Name guard (pure; needs no server).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["t17_ab12_test", "t17_tmpl_ab12_test", "t17_0123456789ab_test"])
def test_generated_names_are_accepted(name: str) -> None:
    assert assert_disposable_database_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "trading",
        "trading_test",
        "postgres",
        "template1",
        "t17_ab12",
        "x_t17_ab12_test",
        "t17_AB12_test",
        "t17_xyz_test",
        "t17__test",
        'T17_ab12_test"; DROP DATABASE trading; --',
        't17_ab12_test"',
        "t17_ab12_test; DROP DATABASE trading",
        "",
    ],
)
def test_other_names_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match="refusing database name"):
        assert_disposable_database_name(name)


def test_create_and_drop_refuse_a_real_database_name_before_any_connection() -> None:
    # Validation happens before the engine is built, so no server is needed.
    with pytest.raises(ValueError):
        pg_support.create_database("postgresql+psycopg://u:p@localhost/postgres", "trading")
    with pytest.raises(ValueError):
        pg_support.drop_database("postgresql+psycopg://u:p@localhost/postgres", "trading_test")
    with pytest.raises(ValueError):
        pg_support.create_database(
            "postgresql+psycopg://u:p@localhost/postgres", "t17_ab12_test", template="trading"
        )


# --------------------------------------------------------------------------- #
# Strict-skip policy (the helper is called directly with a patched environment).
# --------------------------------------------------------------------------- #


def test_missing_url_skips_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(pg_support.TEST_DATABASE_URL_ENV, raising=False)
    monkeypatch.delenv(STRICT_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception, match="TEST_DATABASE_URL is not set"):
        require_test_database_url()


def test_missing_url_fails_under_trading_ci_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(pg_support.TEST_DATABASE_URL_ENV, raising=False)
    monkeypatch.setenv("TRADING_CI_STRICT", "1")
    with pytest.raises(pytest.fail.Exception, match="TEST_DATABASE_URL is not set"):
        require_test_database_url()


def test_present_url_is_returned_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(pg_support.TEST_DATABASE_URL_ENV, "postgresql+psycopg://u:p@h/postgres")
    monkeypatch.setenv("TRADING_CI_STRICT", "1")
    assert require_test_database_url() == "postgresql+psycopg://u:p@h/postgres"


# --------------------------------------------------------------------------- #
# Canary: CI can never pass the PostgreSQL battery vacuously.
# --------------------------------------------------------------------------- #


def test_canary_server_answers_when_database_url_is_required() -> None:
    """With TRADING_CI_STRICT=1 this FAILS unless TEST_DATABASE_URL is set AND answers.

    Without strict mode and without a URL it skips loudly instead.
    """
    url = require_test_database_url()
    if os.environ.get("TRADING_CI_STRICT") == "1":
        assert os.environ.get(pg_support.TEST_DATABASE_URL_ENV), "strict mode needs the URL"
    engine = pg_support._admin_engine(url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
# The fixtures themselves.
# --------------------------------------------------------------------------- #


def _database_exists(server_url: str, name: str) -> bool:
    engine = pg_support._admin_engine(server_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            ).first()
            return row is not None
    finally:
        engine.dispose()


def test_pg_db_name_is_generated_and_differs_from_the_server_url_database(
    pg_db: str, pg_server_url: str
) -> None:
    name = make_url(pg_db).database
    assert name is not None
    assert_disposable_database_name(name)
    assert name != make_url(pg_server_url).database
    assert _database_exists(pg_server_url, name)


def test_pg_db_is_dropped_at_teardown(pg_server_url: str, pg_template_name: str) -> None:
    """Drive the fixture generator by hand so teardown is observable inside a test."""
    fixture_fn: Any = pg_support.pg_db.__wrapped__  # type: ignore[attr-defined]
    generator = fixture_fn(pg_server_url, pg_template_name)
    url = next(generator)
    name = make_url(url).database
    assert name is not None
    assert _database_exists(pg_server_url, name)
    with pytest.raises(StopIteration):
        next(generator)
    assert not _database_exists(pg_server_url, name)


def test_pg_empty_db_has_no_tables_and_is_dropped_at_teardown(pg_server_url: str) -> None:
    fixture_fn: Any = pg_support.pg_empty_db.__wrapped__  # type: ignore[attr-defined]
    generator = fixture_fn(pg_server_url)
    url = next(generator)
    name = make_url(url).database
    assert name is not None
    assert_disposable_database_name(name)
    probe = pg_support._admin_engine(url)
    try:
        with probe.connect() as conn:
            tables = conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            ).scalar_one()
        assert tables == 0
    finally:
        probe.dispose()
    with pytest.raises(StopIteration):
        next(generator)
    assert not _database_exists(pg_server_url, name)


def test_template_schema_comes_from_alembic_only(pg_db: str) -> None:
    engine = pg_support._admin_engine(pg_db)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            has_intents = conn.execute(
                text("SELECT to_regclass('public.execution_intents')")
            ).scalar_one()
        assert version == "0004_persistence_integrity"
        assert has_intents == "execution_intents"
    finally:
        engine.dispose()
