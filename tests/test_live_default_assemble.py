"""`default_assemble` builds the live engine with `make_sync_engine` (24-REVIEW CR-01).

The placement and protection paths call the stores synchronously on the event loop and rely on the
bounded connect, lock, statement and pool waits and the verified UTC pin of
`src.persistence.engine.make_sync_engine`. A bare `create_engine` drops all of them, so the engine
is pinned here by a call spy and by an AST guard. No connection is opened.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from src.live import runtime
from src.live.runtime import DatabaseUrlMissing, LiveContext, default_assemble

from tests.shadow_fakes import T0
from tests.support.live_wiring_rig import forbid_connections, make_config

URL = "postgresql://user:secret@db.invalid:5432/trading"
RUNTIME_SOURCE = Path(runtime.__file__)


@pytest.fixture(autouse=True)
def _no_connections(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return forbid_connections(monkeypatch)


def _context(tmp_path: Path, env: dict[str, str]) -> LiveContext:
    return LiveContext(
        config=make_config(tmp_path),
        env=env,
        clock=lambda: T0,
        started_at_utc=T0,
        initialize_gate_state=False,
        operator_id=None,
    )


def test_default_assemble_hands_build_wiring_the_bounded_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine_sentinel = object()
    engine_calls: list[str] = []
    wiring_kwargs: dict[str, Any] = {}

    def spy_make_sync_engine(database_url: str, **_kwargs: Any) -> object:
        engine_calls.append(database_url)
        return engine_sentinel

    def spy_build_wiring(**kwargs: Any) -> str:
        wiring_kwargs.update(kwargs)
        return "assembly"

    monkeypatch.setattr("src.persistence.engine.make_sync_engine", spy_make_sync_engine)
    monkeypatch.setattr("src.live.wiring.build_wiring", spy_build_wiring)

    assert default_assemble(_context(tmp_path, {"DATABASE_URL": URL})) == "assembly"

    assert engine_calls == [URL]
    assert wiring_kwargs["engine"] is engine_sentinel


def test_default_assemble_prefers_the_sync_url_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def spy_make_sync_engine(database_url: str, **_kwargs: Any) -> object:
        seen.append(database_url)
        return object()

    monkeypatch.setattr("src.persistence.engine.make_sync_engine", spy_make_sync_engine)
    monkeypatch.setattr("src.live.wiring.build_wiring", lambda **_kwargs: "assembly")

    env = {"DATABASE_URL_SYNC": URL, "DATABASE_URL": "postgresql://other.invalid/other"}
    default_assemble(_context(tmp_path, env))
    assert seen == [URL]


def test_default_assemble_without_a_database_url_builds_no_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("no engine may be built without a database URL")

    monkeypatch.setattr("src.persistence.engine.make_sync_engine", refuse)
    with pytest.raises(DatabaseUrlMissing):
        default_assemble(_context(tmp_path, {}))


def test_the_live_runtime_never_builds_an_unbounded_engine() -> None:
    """The bounded factory cannot be dropped again: no `create_engine` in the live runtime."""
    tree = ast.parse(RUNTIME_SOURCE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name)
    assert "create_engine" not in names
    assert "make_sync_engine" in names
