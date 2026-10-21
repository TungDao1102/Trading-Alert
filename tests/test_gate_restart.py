"""REST gate restart recovery (plan 20-07, T-D, owner decision O-C = option-a1-with-commands).

The gate keeps its two end times in memory; a restart forgets them. With a `GateStateStore` the
gate persists them and a restart restores them through `restore()`. Until `restore()` ran, an
empty gate is NOT proof that REST may be dispatched, so `check()` refuses with `GateNotRestored`.
A first installation is proven only by the explicit `FileGateStateStore.initialize(...)`; a state
file that is missing or does not parse is LOSS or CORRUPTION of initialized state and blocks every
REST call with no known end (option a1) until an operator acts. Clocks are fakes.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import src.adapters.binance_ratelimit_gate as gate_mod
from src.adapters.binance_limits import RateLimitPolicy
from src.adapters.binance_ratelimit_gate import (
    GATE_NOT_RESTORED,
    GateNotRestored,
    GateRecoveryStatus,
    GateRestriction,
    RateLimitBanActive,
    RestGateRefusal,
    RestRateLimitGate,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from src.ops.rest_gate_state import FileGateStateStore, GateStateExists

from tests.support.ast_guards import forbidden_imports, wall_clock_calls
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_418,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_429,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS as CAP,
)

_C = ExchangeErrorCategory
T0 = datetime(2026, 10, 21, 9, 0, 0, tzinfo=UTC)


class VirtualClock:
    """A UTC clock that only moves when the test says so."""

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


def _gate(store: FileGateStateStore, clock: VirtualClock) -> RestRateLimitGate:
    return RestRateLimitGate(policy=_policy(), clock=clock, state_store=store)


def _initialized(tmp_path: Path) -> tuple[FileGateStateStore, VirtualClock]:
    clock = VirtualClock()
    store = _store(tmp_path, clock)
    store.initialize(now_utc=clock(), operator_id="op-1")
    return store, clock


# --------------------------------------------------------------------------- #
# Tracer: a 418 ban known before the restart is enforced after it.
# --------------------------------------------------------------------------- #


def test_restart_with_active_418_ban_still_refuses(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)

    first = _gate(store, clock)
    assert first.restore() is GateRecoveryStatus.RESTORED_DURABLE
    first.check()  # a bootstrapped fresh install is not locked
    clock.advance(10)
    ban_start = clock()
    first.record(_C.IP_BANNED, 120)
    saved = store.load()
    assert saved is not None
    assert saved.ban_until_utc == ban_start + timedelta(seconds=120)

    # New process: same file, an empty gate that has not restored yet.
    clock.advance(30)
    second = _gate(store, clock)
    assert second.recovery_status() is GateRecoveryStatus.NOT_RESTORED
    for _ in range(2):
        with pytest.raises(GateNotRestored) as info:
            second.check()
        assert info.value.reason == GATE_NOT_RESTORED
    assert second.restore() is GateRecoveryStatus.RESTORED_DURABLE

    with pytest.raises(RateLimitBanActive):
        second.check()
    restriction = second.restriction()
    assert restriction is not None
    assert restriction.until_utc == ban_start + timedelta(seconds=120)

    clock.advance(91)  # ban start + 121 s
    assert second.check() is None
    assert second.restriction() is None


def test_unrestored_gate_refuses_with_a_restriction_that_has_no_end(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    gate = _gate(store, clock)
    restriction = gate.restriction()
    assert restriction == GateRestriction(
        reason=GATE_NOT_RESTORED, until_utc=None, remaining_seconds=1
    )
    assert gate.remaining_seconds() == 1
    with pytest.raises(GateNotRestored) as info:
        gate.check()
    assert isinstance(info.value, RestGateRefusal)  # plan 20-14 keeps a refused action PENDING
    assert info.value.retry_after_seconds == 1


def test_first_time_initialization_is_not_locked(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    record = store.load()
    assert record is not None
    assert record.initialized_at_utc == T0
    assert record.initialized_by == "op-1"
    assert record.ban_until_utc is None
    assert record.pause_until_utc is None
    gate = _gate(store, clock)
    assert gate.restore() is GateRecoveryStatus.RESTORED_DURABLE
    assert gate.check() is None
    assert gate.restriction() is None
    assert gate.remaining_seconds() == 0


def test_initialize_is_refused_when_a_state_file_exists_and_leaves_it_untouched(
    tmp_path: Path,
) -> None:
    store, clock = _initialized(tmp_path)
    path = tmp_path / "gate.json"
    before = path.read_bytes()
    with pytest.raises(GateStateExists):
        store.initialize(now_utc=clock(), operator_id="op-2")
    assert path.read_bytes() == before
    path.write_bytes(b"not json")  # a corrupt file also counts as an existing state file
    with pytest.raises(GateStateExists):
        store.initialize(now_utc=clock(), operator_id="op-2")
    assert path.read_bytes() == b"not json"


def test_initialize_requires_an_operator_id_and_an_aware_time(tmp_path: Path) -> None:
    clock = VirtualClock()
    store = _store(tmp_path, clock)
    with pytest.raises(ValueError):
        store.initialize(now_utc=clock(), operator_id="  ")
    with pytest.raises(ValueError):
        store.initialize(now_utc=datetime(2026, 10, 21), operator_id="op-1")
    assert not (tmp_path / "gate.json").exists()


def test_a_gate_without_a_recovery_source_is_unchanged_and_legacy() -> None:
    clock = VirtualClock()
    gate = RestRateLimitGate(policy=_policy(), clock=clock)
    assert gate.recovery_status() is GateRecoveryStatus.LEGACY_IN_MEMORY
    assert gate.check() is None
    gate.record(_C.IP_BANNED, None)
    with pytest.raises(RateLimitBanActive):
        gate.check()
    assert gate.recovery_status() is GateRecoveryStatus.LEGACY_IN_MEMORY


def test_gate_module_stays_pure_and_does_no_file_io() -> None:
    path = Path(inspect.getfile(gate_mod))
    assert forbidden_imports(path, ("os", "io", "pathlib", "json", "shutil", "tempfile")) == []
    assert wall_clock_calls(path) == []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "open" not in calls
