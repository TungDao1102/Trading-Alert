"""Disposable PostgreSQL databases for the Phase 17 persistence tests (D-23, SC5).

`TEST_DATABASE_URL` names the SERVER (the maintenance connection) and is
never itself connected to for test work, altered or dropped. This module:

  1. builds ONE session-scoped template database named `t17_tmpl_<hex>_test`
     by running `alembic upgrade head` (never an ORM-metadata schema build; F-606),
  2. clones it per test with `CREATE DATABASE ... TEMPLATE ...` into a
     generated `t17_<hex>_test` database (the append-only journal added in
     plan 02 makes row cleanup impossible, so a clone per test is mandatory),
  3. drops every generated database `WITH (FORCE)` at teardown.

The only dynamic SQL in the project lives here: database names, which are
generated from `secrets.token_hex`, validated against
`^t17_(tmpl_)?[0-9a-f]+_test$` BEFORE they reach SQL, and quoted. They are
never user input.

A missing `TEST_DATABASE_URL` skips loudly locally and FAILS under
`TRADING_CI_STRICT=1` (`tests.infra_helpers.infra_skip`), so a misconfigured
CI cannot pass the PostgreSQL battery vacuously (research C9).

URLs are never printed; any text that may carry the password is redacted.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.pool import NullPool

from tests.infra_helpers import infra_skip

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"
_DISPOSABLE_NAME = re.compile(r"^t17_(tmpl_)?[0-9a-f]+_test$")
_ALEMBIC_TIMEOUT_S = 180


def require_test_database_url() -> str:
    """Return `TEST_DATABASE_URL`, or skip loudly (FAIL under TRADING_CI_STRICT=1)."""
    url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not url:
        infra_skip("TEST_DATABASE_URL is not set; PostgreSQL tests cannot run")
    return url


def assert_disposable_database_name(name: str) -> str:
    """Refuse anything that is not a generated `t17_*_test` database name."""
    if not _DISPOSABLE_NAME.fullmatch(name):
        raise ValueError(
            f"refusing database name {name!r}: only generated t17_<hex>_test "
            "(or t17_tmpl_<hex>_test) databases may be created or dropped by tests"
        )
    return name


def _admin_engine(server_url: str) -> Engine:
    """AUTOCOMMIT maintenance engine (CREATE/DROP DATABASE cannot run in a transaction)."""
    return create_engine(server_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)


def _with_database(server_url: str, database: str) -> URL:
    return make_url(server_url).set(database=database)


def database_url_for(server_url: str, database: str) -> str:
    """URL string (password included, for connecting) for `database` on the server."""
    return _with_database(server_url, database).render_as_string(hide_password=False)


def _redact(message: str, server_url: str) -> str:
    password = make_url(server_url).password
    if password:
        message = message.replace(password, "***")
    return message


def create_database(server_url: str, name: str, *, template: str | None = None) -> None:
    """CREATE a validated disposable database, optionally from a validated template."""
    assert_disposable_database_name(name)
    if template is not None:
        assert_disposable_database_name(template)
    engine = _admin_engine(server_url)
    try:
        with engine.connect() as conn:
            if template is None:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
            else:
                conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{template}"'))
    finally:
        engine.dispose()


def drop_database(server_url: str, name: str) -> None:
    """DROP a validated disposable database, terminating leftover sessions."""
    assert_disposable_database_name(name)
    engine = _admin_engine(server_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        engine.dispose()


def alembic_head_revision() -> str:
    """The single head revision of the Alembic chain, read from the script directory.

    Tests compare a migrated database against this instead of a literal revision id, so
    adding a migration never needs a test edit. Raises when the chain has several heads.
    """
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "src" / "db" / "alembic"))
    config.set_main_option("path_separator", "os")
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one Alembic head, found {sorted(heads)}")
    return heads[0]


def run_alembic(database_url: str, *args: str) -> None:
    """Run `python -m alembic <args>` against `database_url` in a subprocess.

    The child gets `DATABASE_URL` (what `src/db/alembic/env.py` reads) in its
    own environment only, mirroring `src/ops/backup.py::_prod_migrate_runner`.
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    proc = subprocess.run(  # noqa: S603 - fixed argv, interpreter from sys.executable
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=_ALEMBIC_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        detail = _redact((proc.stderr or proc.stdout)[-2000:], database_url)
        raise RuntimeError(f"alembic {' '.join(args)} failed (exit {proc.returncode}): {detail}")


@pytest.fixture(scope="session")
def pg_server_url() -> str:
    """The maintenance-connection URL of the PostgreSQL server under test."""
    return require_test_database_url()


@pytest.fixture(scope="session")
def pg_template_name(pg_server_url: str) -> Iterator[str]:
    """A session template database built ONLY by `alembic upgrade head`."""
    name = f"t17_tmpl_{secrets.token_hex(4)}_test"
    create_database(pg_server_url, name)
    try:
        run_alembic(database_url_for(pg_server_url, name), "upgrade", "head")
        yield name
    finally:
        drop_database(pg_server_url, name)


@pytest.fixture
def pg_db(pg_server_url: str, pg_template_name: str) -> Iterator[str]:
    """A fresh migrated database cloned from the template; yields its URL string."""
    name = f"t17_{secrets.token_hex(6)}_test"
    create_database(pg_server_url, name, template=pg_template_name)
    try:
        yield database_url_for(pg_server_url, name)
    finally:
        drop_database(pg_server_url, name)


@pytest.fixture
def pg_empty_db(pg_server_url: str) -> Iterator[str]:
    """An EMPTY generated database (no migrations) for migration-cycle tests."""
    name = f"t17_{secrets.token_hex(6)}_test"
    create_database(pg_server_url, name)
    try:
        yield database_url_for(pg_server_url, name)
    finally:
        drop_database(pg_server_url, name)
