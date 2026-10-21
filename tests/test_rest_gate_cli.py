"""Operator commands `status` and `clear` for the persisted REST gate state (plan 20-07, Task 4).

Owner decision O-C: a false restriction must be liftable from the server without waiting.
`status` is read-only. `clear` writes a fresh valid initialized record (bootstrap-equivalent) and
keeps the old file aside; it takes effect only at the NEXT restart, through `restore()`. A
persisted ban or pause deadline that is still in the future needs `--force`. Clocks are fakes.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import src.ops.rest_gate_cli as cli_mod
import src.ops.rest_gate_state as state_mod
from src.adapters.binance_limits import RateLimitPolicy
from src.adapters.binance_ratelimit_gate import (
    GateRecoveryStatus,
    RateLimitBanActive,
    RestRateLimitGate,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from src.ops.rest_gate_cli import clear_state, main, status_report
from src.ops.rest_gate_state import FileGateStateStore, GateStateExists

from tests.support.ast_guards import module_imports
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_418,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_429,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS as CAP,
)

T0 = datetime(2026, 10, 21, 9, 0, 0, tzinfo=UTC)
REMINDER = "check once by hand before clearing"


class VirtualClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        no_retry_after_wait_418_seconds=WAIT_418,
        no_retry_after_wait_429_seconds=WAIT_429,
        retry_after_cap_seconds=CAP,
    )


def _store(tmp_path: Path, clock: VirtualClock) -> FileGateStateStore:
    return FileGateStateStore(tmp_path / "gate.json", clock=clock)


def _initialized(tmp_path: Path) -> tuple[FileGateStateStore, VirtualClock]:
    clock = VirtualClock()
    store = _store(tmp_path, clock)
    store.initialize(now_utc=clock(), operator_id="op-1")
    return store, clock


def _banned(tmp_path: Path, seconds: int) -> tuple[FileGateStateStore, VirtualClock]:
    store, clock = _initialized(tmp_path)
    gate = RestRateLimitGate(policy=_policy(), clock=clock, state_store=store)
    gate.restore()
    gate.record(ExchangeErrorCategory.IP_BANNED, seconds)
    return store, clock


def _text(result: object) -> str:
    return "\n".join(result.lines)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


def test_status_on_a_good_file_prints_the_state_and_the_reminder(tmp_path: Path) -> None:
    store, clock = _banned(tmp_path, 120)
    result = status_report(store, clock())
    text = _text(result)
    assert result.exit_code == 0
    assert str(store.path) in text
    assert "2026-10-21T09:02:00Z" in text  # ban_until_utc
    assert "op-1" in text and "2026-10-21T09:00:00Z" in text  # initialized by / at
    assert "RESTORED_DURABLE" in text
    assert REMINDER in text


def test_status_on_a_missing_file_exits_2_and_says_missing(tmp_path: Path) -> None:
    clock = VirtualClock()
    result = status_report(_store(tmp_path, clock), clock())
    text = _text(result)
    assert result.exit_code == 2
    assert "missing" in text
    assert "RESTORED_UNKNOWN_STATE" in text
    assert REMINDER in text


def test_status_on_a_corrupt_file_exits_2_and_says_corrupt(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    store.path.write_bytes(b"{broken")
    result = status_report(store, clock())
    text = _text(result)
    assert result.exit_code == 2
    assert "corrupt" in text
    assert "RESTORED_UNKNOWN_STATE" in text


def test_status_does_not_move_a_corrupt_file(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    store.path.write_bytes(b"{broken")
    status_report(store, clock())
    assert store.path.read_bytes() == b"{broken"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gate.json"]


def test_status_never_writes(tmp_path: Path) -> None:
    store, clock = _banned(tmp_path, 120)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    status_report(store, clock())
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    assert before == after
    missing = _store(tmp_path / "nowhere", clock)
    status_report(missing, clock())
    assert not (tmp_path / "nowhere").exists()


# --------------------------------------------------------------------------- #
# clear
# --------------------------------------------------------------------------- #


def test_initialize_is_still_refused_when_a_file_exists(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    clear_state(store, clock(), operator_id="op-2", reason="checked", force=False)
    before = store.path.read_bytes()
    with pytest.raises(GateStateExists):
        store.initialize(now_utc=clock(), operator_id="op-3")
    assert store.path.read_bytes() == before


def test_clear_on_a_missing_file_writes_a_fresh_initialized_record(tmp_path: Path) -> None:
    clock = VirtualClock()
    store = _store(tmp_path, clock)
    result = clear_state(store, clock(), operator_id="op-9", reason="file lost", force=False)
    assert result.exit_code == 0
    record = store.load()
    assert record is not None
    assert record.initialized_by == "op-9"
    assert record.initialized_at_utc == T0
    assert record.ban_until_utc is None and record.pause_until_utc is None
    assert "next restart" in _text(result)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gate.json"]  # nothing to keep aside


def test_clear_on_an_initialized_record_without_a_deadline(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    clock.advance(60)
    result = clear_state(store, clock(), operator_id="op-2", reason="routine", force=False)
    assert result.exit_code == 0
    record = store.load()
    assert record is not None and record.initialized_by == "op-2"
    assert record.initialized_at_utc == clock()
    assert len([p for p in tmp_path.iterdir() if ".replaced-" in p.name]) == 1


def test_clear_keeps_a_corrupt_file_aside(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    store.path.write_bytes(b"{broken")
    result = clear_state(store, clock(), operator_id="op-2", reason="corrupt", force=False)
    assert result.exit_code == 0
    aside = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
    assert len(aside) == 1 and aside[0].read_bytes() == b"{broken"
    assert store.load() is not None


def test_clear_refuses_a_future_deadline_without_force(tmp_path: Path) -> None:
    store, clock = _banned(tmp_path, 120)
    before = store.path.read_bytes()
    clock.advance(30)
    result = clear_state(store, clock(), operator_id="op-2", reason="false ban", force=False)
    assert result.exit_code == 3
    assert "2026-10-21T09:02:00Z" in _text(result)
    assert store.path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gate.json"]


def test_clear_with_force_clears_and_says_forced(tmp_path: Path) -> None:
    store, clock = _banned(tmp_path, 120)
    clock.advance(30)
    result = clear_state(store, clock(), operator_id="op-2", reason="false ban", force=True)
    assert result.exit_code == 0
    assert "forced" in _text(result)
    record = store.load()
    assert record is not None and record.ban_until_utc is None
    assert len([p for p in tmp_path.iterdir() if ".replaced-" in p.name]) == 1


def test_clear_does_not_need_force_once_the_deadline_has_passed(tmp_path: Path) -> None:
    store, clock = _banned(tmp_path, 120)
    clock.advance(121)
    result = clear_state(store, clock(), operator_id="op-2", reason="expired", force=False)
    assert result.exit_code == 0
    assert "forced" not in _text(result)


@pytest.mark.parametrize(
    ("operator_id", "reason"), [("", "why"), ("  ", "why"), ("op", ""), ("op", " ")]
)
def test_clear_refuses_an_empty_operator_id_or_reason(
    tmp_path: Path, operator_id: str, reason: str
) -> None:
    store, clock = _initialized(tmp_path)
    before = store.path.read_bytes()
    result = clear_state(store, clock(), operator_id=operator_id, reason=reason, force=True)
    assert result.exit_code == 2
    assert store.path.read_bytes() == before


def test_clear_warns_to_stop_the_process_first(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    text = _text(clear_state(store, clock(), operator_id="op-2", reason="r", force=False))
    assert "stop the trading process" in text.lower()
    assert "write its in-memory deadlines back" in text
    assert REMINDER in text


def test_clear_write_failure_leaves_the_old_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, clock = _initialized(tmp_path)
    before = store.path.read_bytes()

    def boom(tmp: Path, path: Path) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(state_mod, "replace_with_retry", boom)
    result = clear_state(store, clock(), operator_id="op-2", reason="r", force=False)
    assert result.exit_code == 4
    assert store.path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gate.json"]  # no tmp, no aside left


def test_clear_takes_effect_only_after_restart_restore(tmp_path: Path) -> None:
    store, clock = _banned(tmp_path, 3600)
    running = RestRateLimitGate(policy=_policy(), clock=clock, state_store=store)
    running.restore()
    with pytest.raises(RateLimitBanActive):
        running.check()
    result = clear_state(store, clock(), operator_id="op-2", reason="false ban", force=True)
    assert result.exit_code == 0
    with pytest.raises(RateLimitBanActive):  # the running gate is not touched
        running.check()
    assert running.restore() is GateRecoveryStatus.RESTORED_DURABLE
    with pytest.raises(RateLimitBanActive):
        running.check()

    restarted = RestRateLimitGate(policy=_policy(), clock=clock, state_store=store)
    assert restarted.restore() is GateRecoveryStatus.RESTORED_DURABLE
    assert restarted.check() is None
    assert restarted.restriction() is None


def test_clear_after_loss_unblocks_the_next_start(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    store.path.unlink()
    lost = RestRateLimitGate(policy=_policy(), clock=clock, state_store=store)
    assert lost.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    assert clear_state(store, clock(), operator_id="op-2", reason="r", force=False).exit_code == 0
    again = RestRateLimitGate(policy=_policy(), clock=clock, state_store=store)
    assert again.restore() is GateRecoveryStatus.RESTORED_DURABLE


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def test_main_status_and_clear_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "gate.json"
    assert main(["status", "--path", str(path)]) == 2
    assert "missing" in capsys.readouterr().out
    assert main(["clear", "--path", str(path), "--operator-id", "op-1", "--reason", "install"]) == 0
    assert main(["status", "--path", str(path)]) == 0
    out = capsys.readouterr().out
    assert "RESTORED_DURABLE" in out and "op-1" in out


def test_main_requires_the_path_and_the_operator_id() -> None:
    with pytest.raises(SystemExit) as info:
        main(["status"])
    assert info.value.code == 2
    with pytest.raises(SystemExit) as info:
        main(["clear", "--path", "x", "--reason", "r"])
    assert info.value.code == 2


def test_main_prints_no_environment_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BINANCE_LIVE_API_SECRET", "s3cret-value-xyz")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw-abc@host/db")
    main(["status", "--path", str(tmp_path / "gate.json")])
    out = capsys.readouterr()
    assert "s3cret-value-xyz" not in out.out + out.err
    assert "pw-abc" not in out.out + out.err


def test_cli_module_has_no_network_or_gate_mutation() -> None:
    path = Path(inspect.getfile(cli_mod))
    imports = set(module_imports(path))
    forbidden = ("binance", "requests", "aiohttp", "httpx", "socket", "urllib", "websocket")
    assert not [name for name in imports if name.split(".")[0].startswith(forbidden)]
    adapters = {name for name in imports if name.startswith("src.adapters")}
    assert adapters <= {"src.adapters.binance_ratelimit_gate"}  # the pure gate module: types only
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "RestRateLimitGate" not in imported  # no running gate can be reached from here
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"record", "restore", "check", "restriction", "request", "urlopen"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "environ" not in names | attrs and "getenv" not in names | attrs


def test_library_functions_read_no_clock() -> None:
    path = Path(inspect.getfile(cli_mod))
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name, node in functions.items():
        if name == "main":
            continue
        called = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "now" not in called, name
