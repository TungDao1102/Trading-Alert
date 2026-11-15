"""`clear` leaves a durable audit line next to the state file (Phase 20 review WR-C10).

The free-text `--reason` and the `forced` flag used to reach only a `structlog` call (the CLI never
configures structlog), so a `--force` that overrode a real future ban left no durable reason. Now
`clear_state` appends one fsynced JSON line to `<state file>.clear-audit.jsonl` BEFORE it changes
anything (operator id, reason, forced flag, the overridden deadlines, the previous state, the time)
and a closing line (`cleared` or `failed`) after. If the audit line cannot be written, the clear
is refused and nothing is changed. A refused clear (future deadline without `--force`, empty
operator id or reason) writes nothing: it changed nothing.

Evidence label: executed tests in a temporary directory with a virtual clock; no network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import src.ops.rest_gate_state as state_mod
from src.adapters.binance_limits import RateLimitPolicy
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.domain.exchange_errors import ExchangeErrorCategory
from src.ops.rest_gate_cli import clear_state
from src.ops.rest_gate_state import FileGateStateStore

from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_418,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_429,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS as CAP,
)

T0 = datetime(2026, 10, 25, 9, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _initialized(tmp_path: Path) -> tuple[FileGateStateStore, _Clock]:
    clock = _Clock()
    store = FileGateStateStore(tmp_path / "gate.json", clock=clock)
    store.initialize(now_utc=clock(), operator_id="op-1")
    return store, clock


def _banned(tmp_path: Path, seconds: int) -> tuple[FileGateStateStore, _Clock]:
    store, clock = _initialized(tmp_path)
    policy = RateLimitPolicy(
        no_retry_after_wait_418_seconds=WAIT_418,
        no_retry_after_wait_429_seconds=WAIT_429,
        retry_after_cap_seconds=CAP,
    )
    gate = RestRateLimitGate(policy=policy, clock=clock, state_store=store)
    gate.restore()
    gate.record(ExchangeErrorCategory.IP_BANNED, seconds)
    return store, clock


def _audit(store: FileGateStateStore) -> list[dict[str, Any]]:
    path = store.path.with_name(f"{store.path.name}.clear-audit.jsonl")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_forced_clear_over_a_real_ban_records_who_why_and_what_was_overridden(
    tmp_path: Path,
) -> None:
    store, clock = _banned(tmp_path, 120)
    clock.now = T0 + timedelta(seconds=30)

    result = clear_state(store, clock(), operator_id="op-2", reason="checked by hand", force=True)

    assert result.exit_code == 0
    requested, cleared = _audit(store)
    assert requested["outcome"] == "requested"
    assert requested["operator_id"] == "op-2"
    assert requested["reason"] == "checked by hand"
    assert requested["forced"] is True
    assert requested["now_utc"] == "2026-10-25T09:00:30Z"
    assert len(requested["overridden"]) == 1
    assert requested["overridden"][0].startswith("ban_until_utc 2026-10-25T09:02:00Z")
    assert requested["previous"] == "valid"
    assert cleared["outcome"] == "cleared"
    assert cleared["operator_id"] == "op-2"


def test_an_unforced_clear_is_recorded_too_and_audit_lines_append(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)

    assert clear_state(store, clock(), operator_id="op-2", reason="r1", force=False).exit_code == 0
    assert clear_state(store, clock(), operator_id="op-3", reason="r2", force=False).exit_code == 0

    lines = _audit(store)
    assert [(line["outcome"], line["operator_id"], line["reason"]) for line in lines] == [
        ("requested", "op-2", "r1"),
        ("cleared", "op-2", "r1"),
        ("requested", "op-3", "r2"),
        ("cleared", "op-3", "r2"),
    ]
    assert all(line["forced"] is False and line["overridden"] == [] for line in lines)


def test_a_refused_clear_writes_no_audit_line(tmp_path: Path) -> None:
    store, clock = _banned(tmp_path, 120)

    assert clear_state(store, clock(), operator_id="op-2", reason="r", force=False).exit_code == 3
    assert clear_state(store, clock(), operator_id="", reason="r", force=True).exit_code == 2
    assert clear_state(store, clock(), operator_id="op", reason=" ", force=True).exit_code == 2

    assert _audit(store) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gate.json"]


def test_when_the_audit_line_cannot_be_written_the_clear_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, clock = _banned(tmp_path, 120)
    before = store.path.read_bytes()

    def boom(*_a: Any, **_k: Any) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(state_mod.FileGateStateStore, "append_clear_audit", boom)

    result = clear_state(store, clock(), operator_id="op-2", reason="r", force=True)

    assert result.exit_code == 4
    assert "audit" in " ".join(result.lines)
    assert store.path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gate.json"]


def test_a_failed_state_write_leaves_a_requested_and_a_failed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, clock = _initialized(tmp_path)

    def boom(tmp: Path, path: Path) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(state_mod, "replace_with_retry", boom)

    result = clear_state(store, clock(), operator_id="op-2", reason="r", force=False)

    assert result.exit_code == 4
    assert [line["outcome"] for line in _audit(store)] == ["requested", "failed"]
