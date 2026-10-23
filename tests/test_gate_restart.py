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
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import src.adapters.binance_ratelimit_gate as gate_mod
from src.adapters.binance_limits import RateLimitPolicy
from src.adapters.binance_ratelimit_gate import (
    GATE_NOT_RESTORED,
    GATE_STATE_UNKNOWN,
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    GateNotRestored,
    GateRecoveryStatus,
    GateRestriction,
    GateStateCorrupt,
    GateStateRecord,
    RateLimitBanActive,
    RateLimitPauseActive,
    RestGateRefusal,
    RestRateLimitGate,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from src.ops.rest_gate_state import (
    FileGateStateStore,
    GateStateExists,
    decode_record,
)

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


# --------------------------------------------------------------------------- #
# Task 3: pause, expiry, loss and corruption of initialized state, persistence failures.
# --------------------------------------------------------------------------- #

RECOVERY_REQUIRED = "REST_GATE_RECOVERY_REQUIRED"


class _Alerts:
    def __init__(self) -> None:
        self.events: list[str] = []

    def __call__(self, event: str) -> None:
        self.events.append(event)


def _gate_with_alerts(
    store: FileGateStateStore, clock: VirtualClock
) -> tuple[RestRateLimitGate, _Alerts]:
    alerts = _Alerts()
    gate = RestRateLimitGate(policy=_policy(), clock=clock, state_store=store, on_alert=alerts)
    return gate, alerts


def test_restart_with_active_429_pause_is_enforced_until_its_end(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    first = _gate(store, clock)
    first.restore()
    pause_start = clock()
    first.record(_C.RATE_LIMITED, 50)

    clock.advance(20)
    second = _gate(store, clock)
    second.restore()
    with pytest.raises(RateLimitPauseActive):
        second.check()
    restriction = second.restriction()
    assert restriction is not None
    assert restriction.reason == RATE_LIMIT_PAUSE_429
    assert restriction.until_utc == pause_start + timedelta(seconds=50)
    clock.advance(30)
    assert second.check() is None


def test_restart_with_an_expired_restriction_opens_and_is_restored(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    first = _gate(store, clock)
    first.restore()
    first.record(_C.IP_BANNED, 60)
    clock.advance(500)
    second = _gate(store, clock)
    assert second.restore() is GateRecoveryStatus.RESTORED_DURABLE
    assert second.check() is None
    assert second.restriction() is None
    assert second.recovery_status() is GateRecoveryStatus.RESTORED_DURABLE


def test_restart_with_a_ban_and_a_pause_keeps_the_ban_as_the_reason(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    first = _gate(store, clock)
    first.restore()
    first.record(_C.IP_BANNED, 40)
    first.record(_C.RATE_LIMITED, 90)
    second = _gate(store, clock)
    second.restore()
    restriction = second.restriction()
    assert restriction is not None
    assert restriction.reason == IP_BAN_418
    assert restriction.until_utc == T0 + timedelta(seconds=90)


def test_missing_file_without_bootstrap_is_not_a_fresh_install(tmp_path: Path) -> None:
    clock = VirtualClock()
    store = _store(tmp_path, clock)  # initialize() never ran
    gate, alerts = _gate_with_alerts(store, clock)
    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    assert gate.recovery_status() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    restriction = gate.restriction()
    assert restriction == GateRestriction(
        reason=GATE_STATE_UNKNOWN, until_utc=None, remaining_seconds=1
    )
    with pytest.raises(GateNotRestored) as info:
        gate.check()
    assert info.value.reason == GATE_STATE_UNKNOWN
    assert alerts.events == [RECOVERY_REQUIRED]
    assert not (tmp_path / "gate.json").exists()  # restore() never writes a fresh install


def test_loss_after_initialization_blocks_with_no_end_until_the_operator_acts(
    tmp_path: Path,
) -> None:
    store, clock = _initialized(tmp_path)
    (tmp_path / "gate.json").unlink()

    for days in (0, 1, 4):  # every restart re-detects the loss; no timer ever ends the block
        clock.advance(days * 86400)
        gate, alerts = _gate_with_alerts(store, clock)
        assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
        with pytest.raises(GateNotRestored):
            gate.check()
        restriction = gate.restriction()
        assert restriction is not None
        assert restriction.until_utc is None
        assert alerts.events == [RECOVERY_REQUIRED]

    store.initialize(now_utc=clock(), operator_id="op-2")  # the operator, after checking
    recovered = _gate(store, clock)
    assert recovered.restore() is GateRecoveryStatus.RESTORED_DURABLE
    assert recovered.check() is None


_STAMP = '"recorded_at_utc":"2026-10-21T09:00:00Z","initialized_at_utc":"2026-10-21T09:00:00Z"'


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"",
        b"[]",
        (
            '{"schema_version":2,"ban_until_utc":null,"pause_until_utc":null,'
            + _STAMP
            + ',"initialized_by":"op-1"}'
        ).encode(),
        (
            '{"schema_version":1,"ban_until_utc":"2026-10-21T09:05:00",'
            '"pause_until_utc":null,' + _STAMP + ',"initialized_by":"op-1"}'
        ).encode(),
        (
            '{"schema_version":1,"ban_until_utc":null,"pause_until_utc":null,'
            + _STAMP
            + ',"initialized_by":"op-1","extra":1}'
        ).encode(),
        (
            b'{"schema_version":1,"ban_until_utc":null,"pause_until_utc":null,'
            b'"recorded_at_utc":"2026-10-21T09:00:00Z","initialized_at_utc":null,'
            b'"initialized_by":"op-1"}'
        ),
        b"\xff\xfe\x00",
    ],
)
def test_corruption_after_initialization_keeps_the_file_and_blocks(
    tmp_path: Path, content: bytes
) -> None:
    store, clock = _initialized(tmp_path)
    (tmp_path / "gate.json").write_bytes(content)
    gate, alerts = _gate_with_alerts(store, clock)
    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    with pytest.raises(GateNotRestored) as info:
        gate.check()
    assert info.value.reason == GATE_STATE_UNKNOWN
    assert alerts.events == [RECOVERY_REQUIRED]
    aside = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
    assert [p.name for p in aside] == ["gate.json.corrupt-20261021T090000Z"]
    assert aside[0].read_bytes() == content  # kept, never deleted or rewritten
    assert not (tmp_path / "gate.json").exists()
    # The next start sees a missing file: still loss, never a fresh install.
    again, _ = _gate_with_alerts(store, clock)
    assert again.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE


def _overflow_record() -> bytes:
    """A syntactically valid record whose timestamp overflows `astimezone(UTC)` (WR-C1)."""
    return (
        b'{"schema_version":1,"ban_until_utc":null,"pause_until_utc":null,'
        b'"recorded_at_utc":"9999-12-31T23:59:59-05:00",'
        b'"initialized_at_utc":"2026-10-21T09:00:00Z","initialized_by":"op-1"}'
    )


def _nested_record() -> bytes:
    """JSON nested far deeper than the parser's recursion limit (WR-C1)."""
    return b"[" * 200_000


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(_overflow_record(), id="year-9999-negative-offset"),
        pytest.param(_nested_record(), id="deeply-nested-json"),
    ],
)
def test_overflow_and_recursion_are_corruption_not_crashes(tmp_path: Path, content: bytes) -> None:
    """WR-C1: `OverflowError` / `RecursionError` from the parser read as a corrupt record."""
    with pytest.raises(GateStateCorrupt):
        decode_record(content)
    store, clock = _initialized(tmp_path)
    path = tmp_path / "gate.json"
    path.write_bytes(content)
    inspection = store.inspect()
    assert inspection.exists and inspection.corrupt and inspection.record is None
    assert path.exists()  # inspect never moves the file

    gate, alerts = _gate_with_alerts(store, clock)
    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    with pytest.raises(GateNotRestored) as info:
        gate.check()
    assert info.value.reason == GATE_STATE_UNKNOWN
    assert alerts.events == [RECOVERY_REQUIRED]
    aside = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
    assert [p.name for p in aside] == ["gate.json.corrupt-20261021T090000Z"]
    assert aside[0].read_bytes() == content  # kept, never deleted
    assert not path.exists()


def test_two_corrupt_files_in_one_second_get_distinct_aside_names(tmp_path: Path) -> None:
    store, _ = _initialized(tmp_path)
    for _attempt in range(2):
        (tmp_path / "gate.json").write_bytes(b"bad")
        with pytest.raises(GateStateCorrupt):
            store.load()
    names = sorted(p.name for p in tmp_path.iterdir() if ".corrupt-" in p.name)
    assert len(names) == 2


def test_an_unreadable_store_fails_closed_and_alerts() -> None:
    class Broken:
        def load(self) -> GateStateRecord | None:
            raise OSError("denied")

        def save(self, record: GateStateRecord) -> None:
            raise AssertionError("an unknown state must never be saved")

    clock = VirtualClock()
    alerts = _Alerts()
    gate = RestRateLimitGate(policy=_policy(), clock=clock, state_store=Broken(), on_alert=alerts)
    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    with pytest.raises(GateNotRestored):
        gate.check()
    assert alerts.events == [RECOVERY_REQUIRED]


def test_unknown_end_restriction_never_parks_a_sleeping_consumer_for_the_quarantine_wait(
    tmp_path: Path,
) -> None:
    clock = VirtualClock()
    gate = _gate(_store(tmp_path, clock), clock)
    before = gate.restriction()  # NOT_RESTORED
    assert before is not None and before.remaining_seconds == 1
    gate.restore()  # loss: no file
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.remaining_seconds == 1
    assert restriction.remaining_seconds != WAIT_418
    assert gate.remaining_seconds() == 1
    with pytest.raises(GateNotRestored) as info:
        gate.check()
    assert info.value.retry_after_seconds == 1


def test_restore_is_one_shot_and_a_running_gate_is_never_cleared(tmp_path: Path) -> None:
    clock = VirtualClock()
    store = _store(tmp_path, clock)
    gate = _gate(store, clock)
    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    store.initialize(now_utc=clock(), operator_id="op-1")
    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE  # same process
    with pytest.raises(GateNotRestored):
        gate.check()
    assert _gate(store, clock).restore() is GateRecoveryStatus.RESTORED_DURABLE  # next start


def test_an_unknown_state_is_never_overwritten_by_a_late_record(tmp_path: Path) -> None:
    clock = VirtualClock()
    store = _store(tmp_path, clock)
    gate = _gate(store, clock)
    gate.restore()
    gate.record(_C.IP_BANNED, 100)  # a late classified answer
    assert not (tmp_path / "gate.json").exists()  # no valid-looking file may reopen the gate
    with pytest.raises(GateNotRestored):
        gate.check()


def test_a_record_before_restore_is_merged_and_saved_afterwards(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    gate = _gate(store, clock)
    gate.record(_C.IP_BANNED, 100)
    saved = store.load()
    assert saved is not None and saved.ban_until_utc is None  # nothing saved before restore
    gate.restore()
    saved = store.load()
    assert saved is not None
    assert saved.ban_until_utc == T0 + timedelta(seconds=100)
    with pytest.raises(RateLimitBanActive):
        gate.check()


class _FlakyStore:
    """Wraps a real store; `save` raises while `fail` is set."""

    def __init__(self, inner: FileGateStateStore) -> None:
        self.inner = inner
        self.fail = False

    def load(self) -> GateStateRecord | None:
        return self.inner.load()

    def save(self, record: GateStateRecord) -> None:
        if self.fail:
            raise OSError("disk full")
        self.inner.save(record)


def test_state_persistence_failure_keeps_restriction(tmp_path: Path) -> None:
    inner, clock = _initialized(tmp_path)
    flaky = _FlakyStore(inner)
    gate = RestRateLimitGate(policy=_policy(), clock=clock, state_store=flaky)
    assert gate.restore() is GateRecoveryStatus.RESTORED_DURABLE
    flaky.fail = True
    decision = gate.record(_C.IP_BANNED, 100)  # must not raise into the REST caller
    assert decision.wait_seconds == 100
    with pytest.raises(RateLimitBanActive):
        gate.check()
    assert gate.recovery_status() is GateRecoveryStatus.PERSISTENCE_FAILED
    flaky.fail = False
    gate.record(_C.RATE_LIMITED, 10)  # a later save succeeds and carries both deadlines
    assert gate.recovery_status() is GateRecoveryStatus.RESTORED_DURABLE
    saved = inner.load()
    assert saved is not None and saved.ban_until_utc == T0 + timedelta(seconds=100)


class _CountingStore(_FlakyStore):
    def __init__(self, inner: FileGateStateStore) -> None:
        super().__init__(inner)
        self.saves = 0

    def save(self, record: GateStateRecord) -> None:
        self.saves += 1
        super().save(record)


def test_a_failed_save_is_retried_by_the_next_check(tmp_path: Path) -> None:
    """WR-C2: the file must not stay without the deadline after a transient save failure."""
    inner, clock = _initialized(tmp_path)
    store = _CountingStore(inner)
    gate = RestRateLimitGate(policy=_policy(), clock=clock, state_store=store)
    assert gate.restore() is GateRecoveryStatus.RESTORED_DURABLE
    store.fail = True
    gate.record(_C.IP_BANNED, 100)
    assert gate.recovery_status() is GateRecoveryStatus.PERSISTENCE_FAILED
    saved = inner.load()
    assert saved is not None and saved.ban_until_utc is None  # the file is stale

    # Still failing: each check() tries again and the status stays PERSISTENCE_FAILED.
    before = store.saves
    with pytest.raises(RateLimitBanActive):
        gate.check()
    assert store.saves == before + 1
    assert gate.recovery_status() is GateRecoveryStatus.PERSISTENCE_FAILED

    # The disk recovers: the next check() writes the deadline without any new 418.
    store.fail = False
    clock.advance(10)
    with pytest.raises(RateLimitBanActive):
        gate.check()
    assert gate.recovery_status() is GateRecoveryStatus.RESTORED_DURABLE
    saved = inner.load()
    assert saved is not None and saved.ban_until_utc == T0 + timedelta(seconds=100)

    # A restart now restores the ban from the file.
    second = RestRateLimitGate(policy=_policy(), clock=clock, state_store=inner)
    assert second.restore() is GateRecoveryStatus.RESTORED_DURABLE
    with pytest.raises(RateLimitBanActive):
        second.check()


def test_a_failed_save_is_retried_by_a_record_that_changes_nothing(tmp_path: Path) -> None:
    inner, clock = _initialized(tmp_path)
    store = _CountingStore(inner)
    gate = RestRateLimitGate(policy=_policy(), clock=clock, state_store=store)
    gate.restore()
    store.fail = True
    gate.record(_C.IP_BANNED, 100)
    assert gate.recovery_status() is GateRecoveryStatus.PERSISTENCE_FAILED
    store.fail = False
    gate.record(_C.IP_BANNED, 10)  # shorter: the end time does not move
    assert gate.recovery_status() is GateRecoveryStatus.RESTORED_DURABLE
    saved = inner.load()
    assert saved is not None and saved.ban_until_utc == T0 + timedelta(seconds=100)


def test_a_gate_that_never_failed_a_save_does_not_save_on_check(tmp_path: Path) -> None:
    inner, clock = _initialized(tmp_path)
    store = _CountingStore(inner)
    gate = RestRateLimitGate(policy=_policy(), clock=clock, state_store=store)
    gate.restore()
    gate.record(_C.IP_BANNED, 100)
    saves = store.saves
    for _ in range(3):
        with pytest.raises(RateLimitBanActive):
            gate.check()
        gate.restriction()
    assert store.saves == saves


def test_the_state_file_directory_is_fsynced_after_the_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-C9: the order is temp fsync, replace, directory fsync."""
    import src.ops.rest_gate_state as state_mod

    events: list[str] = []
    real_replace = state_mod.replace_with_retry

    def replace(src: Path, dst: Path) -> None:
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(state_mod, "replace_with_retry", replace)
    monkeypatch.setattr(
        state_mod, "_fsync_directory", lambda directory: events.append(f"dir:{directory.name}")
    )
    store, _ = _initialized(tmp_path)  # the bootstrap links the file; it still syncs the directory
    assert events == [f"dir:{tmp_path.name}"]
    record = store.load()
    assert record is not None
    store.save(record)
    assert events[1:] == ["replace", f"dir:{tmp_path.name}"]


def test_fsync_directory_opens_syncs_and_closes_the_directory_on_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    import src.ops.rest_gate_state as state_mod

    calls: list[tuple[str, object]] = []

    def fake_open(path: object, flags: int) -> int:
        calls.append(("open", Path(str(path))))
        return 7

    fake_os = types.SimpleNamespace(
        name="posix",
        O_RDONLY=0,
        open=fake_open,
        fsync=lambda fd: calls.append(("fsync", fd)),
        close=lambda fd: calls.append(("close", fd)),
    )
    monkeypatch.setattr(state_mod, "os", fake_os)
    state_mod._fsync_directory(tmp_path)
    assert calls == [("open", tmp_path), ("fsync", 7), ("close", 7)]

    calls.clear()
    fake_os.name = "nt"  # a no-op where directories cannot be opened (Windows)
    state_mod._fsync_directory(tmp_path)
    assert calls == []

    fake_os.name = "posix"

    def denied(path: object, flags: int) -> int:
        raise OSError("denied")

    fake_os.open = denied
    state_mod._fsync_directory(tmp_path)  # best effort: never raises


def test_initialize_creates_the_file_exclusively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-C9: a bootstrap that lost the check-then-write race must not overwrite the winner."""
    clock = VirtualClock()
    store = _store(tmp_path, clock)
    winner = store.initialize(now_utc=clock(), operator_id="op-1")
    path = tmp_path / "gate.json"
    before = path.read_bytes()
    real_exists = Path.exists

    def stale_exists(self: Path) -> bool:  # the loser's exists() ran before the winner wrote
        return False if self == path else real_exists(self)

    monkeypatch.setattr(Path, "exists", stale_exists)
    with pytest.raises(GateStateExists):
        store.initialize(now_utc=clock(), operator_id="op-2")
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert store.load() == winner
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_an_alert_hook_that_raises_does_not_open_the_gate(tmp_path: Path) -> None:
    clock = VirtualClock()

    def boom(event: str) -> None:
        raise RuntimeError("alert sink down")

    gate = RestRateLimitGate(
        policy=_policy(), clock=clock, state_store=_store(tmp_path, clock), on_alert=boom
    )
    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    with pytest.raises(GateNotRestored):
        gate.check()


def test_no_bypass_for_reduce_only(tmp_path: Path) -> None:
    signature = inspect.signature(RestRateLimitGate.check)
    assert list(signature.parameters) == ["self"]
    public = {n for n in dir(RestRateLimitGate) if not n.startswith("_")}
    assert public == {
        "check",
        "record",
        "restriction",
        "remaining_seconds",
        "policy",
        "restore",
        "recovery_status",
    }
    # A closed gate refuses whoever asks: there is nothing to pass that could exempt a request.
    clock = VirtualClock()
    gate = _gate(_store(tmp_path, clock), clock)
    gate.restore()
    with pytest.raises(GateNotRestored):
        gate.check()
    with pytest.raises(TypeError):
        gate.check(reduce_only=True)  # type: ignore[call-arg]


def test_refusals_carry_no_url_key_or_path(tmp_path: Path) -> None:
    clock = VirtualClock()
    store = _store(tmp_path, clock)
    messages: list[str] = []
    gate = _gate(store, clock)
    for _attempt in range(2):  # NOT_RESTORED, then GATE_STATE_UNKNOWN
        with pytest.raises(GateNotRestored) as info:
            gate.check()
        messages.append(str(info.value))
        gate.restore()
    for text in messages:
        for forbidden in ("http", "://", "fapi", "binance", "key", "secret", "?", "gate.json"):
            assert forbidden not in text.lower(), (forbidden, text)
        assert str(tmp_path) not in text


def test_restore_without_a_store_is_legacy_and_changes_nothing() -> None:
    clock = VirtualClock()
    gate = RestRateLimitGate(policy=_policy(), clock=clock)
    assert gate.restore() is GateRecoveryStatus.LEGACY_IN_MEMORY
    assert gate.check() is None


def test_state_file_is_canonical_json_schema_version_1(tmp_path: Path) -> None:
    store, clock = _initialized(tmp_path)
    gate = _gate(store, clock)
    gate.restore()
    gate.record(_C.IP_BANNED, 120)
    text = (tmp_path / "gate.json").read_text(encoding="ascii")
    payload = json.loads(text)
    assert list(payload) == sorted(payload)
    assert payload["schema_version"] == 1
    assert payload["ban_until_utc"] == "2026-10-21T09:02:00Z"
    assert payload["pause_until_utc"] is None
    assert payload["initialized_by"] == "op-1"
    assert text.endswith("\n")
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
