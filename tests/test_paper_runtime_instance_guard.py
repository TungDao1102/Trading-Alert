"""Plan 16-55 Task 3: one paper runtime per epoch, and `--pin-epoch` pins and exits.

B1-WR-07 (review batch 1): nothing kept two runtimes from running the same epoch at once, and
`--pin-epoch` went on into the live loop. The owner's decisions (16-DEC-FIXPLANS.md, 16-55):

- the single-instance guard is mandatory and is never weakened or bypassed (Q3);
- `--pin-epoch` pins, writes the pinned state and exits 0 without RUNTIME_START (Q3 = A,
  decisions/16-DEC-PIN-COMMAND.md).

The guard is an instance lease of the state port (a PostgreSQL session advisory lock in
production, `tests/test_paper_runtime_state_pg.py`), taken after admission, the configuration and
the port, before the pin branch and before any record. The in-memory port models one database:
two `main` calls that share it are two processes on one database.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from src.paper import held_marker, runtime
from src.paper.runtime_config import REFUSAL_CODES, ExitCode
from src.paper.runtime_state import (
    INSTANCE_LEASE_SCOPE,
    InMemoryRuntimeState,
    RuntimeRecord,
    instance_lease_key,
)
from src.paper.vocabulary import RuntimeEventType

from tests.test_paper_runtime_admission import _Rig
from tests.test_paper_runtime_loop import PAST_OPEN, Live, wait_until
from tests.test_rationale import write_rationalized_set


class CountingState(InMemoryRuntimeState):
    """The in-memory port that also counts every record write and every lease request."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[RuntimeEventType] = []
        self.lease_requests: list[str] = []

    def record(self, record: RuntimeRecord) -> None:
        self.writes.append(record.event_type)
        super().record(record)

    def acquire_instance_lease(self, scope: str) -> Any:
        self.lease_requests.append(scope)
        return super().acquire_instance_lease(scope)


@pytest.fixture(autouse=True)
def _start_from_an_empty_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.paper.freeze as freeze

    monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", ())


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Rig]:
    import src.domain.registry as domain_registry

    rig = _Rig(tmp_path, monkeypatch)
    rig.state = CountingState()
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    rig.authorize()
    yield rig


def _state(rig: _Rig) -> CountingState:
    assert isinstance(rig.state, CountingState)
    return rig.state


def _starts(rig: _Rig) -> int:
    return rig.types().count(RuntimeEventType.RUNTIME_START)


# ---- the lease key ---------------------------------------------------------------------- #


def test_the_lease_key_is_a_stable_non_negative_64_bit_value() -> None:
    key = instance_lease_key(INSTANCE_LEASE_SCOPE)
    assert key == instance_lease_key(INSTANCE_LEASE_SCOPE)
    assert 0 <= key < 2**63
    assert key != instance_lease_key("another-scope")


def test_instance_held_is_a_refusal_code_with_the_next_free_integer() -> None:
    assert int(ExitCode.INSTANCE_LEASE_HELD) == 8
    assert int(ExitCode.INSTANCE_LEASE_HELD) in REFUSAL_CODES


# ---- re-check of B1-WR-07 and Test 1: the second runtime on an epoch is refused --------- #


def test_a_second_runtime_on_the_running_epoch_is_refused_before_any_record(rig: _Rig) -> None:
    """Re-check of B1-WR-07: before the guard both runs reached RUNTIME_START.

    The first runtime's loop starts a second `main` on the same database and epoch. The second
    must be refused with the instance-held code before EPOCH_PINNED, RUNTIME_START or any record.
    """
    assert rig.run("--pin-epoch") == 0
    state = _state(rig)
    inner: list[int] = []
    writes_before_second: list[int] = []

    def first_loop(_context: Any) -> None:
        writes_before_second.append(len(state.writes))
        inner.append(rig.run(run_loop=lambda _c: pytest.fail("the second loop must not run")))
        assert len(state.writes) == writes_before_second[0], "the refused start wrote a record"

    assert rig.run(run_loop=first_loop) == 0
    assert inner == [int(ExitCode.INSTANCE_LEASE_HELD)]
    assert _starts(rig) == 1, "only the first runtime may reach RUNTIME_START"
    assert rig.types().count(RuntimeEventType.RUNTIME_STOP) == 1


def test_the_refused_second_runtime_holds_with_the_flag(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0
    inner: list[int] = []

    def first_loop(_context: Any) -> None:
        inner.append(rig.run("--hold-on-refusal", run_loop=lambda _c: pytest.fail("must not run")))

    stops_before = rig.stops
    assert rig.run(run_loop=first_loop) == 0
    assert inner == [int(ExitCode.INSTANCE_LEASE_HELD)]
    assert rig.stops == stops_before + 1, "the refused second runtime held until stopped"


def test_a_pin_is_refused_while_another_process_holds_the_lease(rig: _Rig) -> None:
    held = rig.state.acquire_instance_lease(INSTANCE_LEASE_SCOPE)
    assert held is not None
    try:
        assert rig.run("--pin-epoch") == ExitCode.INSTANCE_LEASE_HELD
    finally:
        held.release()
    assert not rig.pinned_path.exists(), "a refused pin writes no pinned state"
    assert _state(rig).writes == [], "a refused pin writes no record"


def test_the_pin_takes_the_lease(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0
    assert _state(rig).lease_requests == [INSTANCE_LEASE_SCOPE]


# ---- Test 2: the lease is released on every way out -------------------------------------- #


def _lease_is_free(state: InMemoryRuntimeState) -> bool:
    lease = state.acquire_instance_lease(INSTANCE_LEASE_SCOPE)
    if lease is None:
        return False
    lease.release()
    return True


def test_the_lease_is_released_after_a_clean_stop(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0
    assert _lease_is_free(rig.state)
    seen: list[bool] = []
    assert rig.run(run_loop=lambda _c: seen.append(_lease_is_free(rig.state))) == 0
    assert seen == [False], "the running process holds the lease"
    assert _lease_is_free(rig.state)


def test_the_lease_is_released_after_a_fail_closed_exit(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0

    def failing(_context: Any) -> None:
        raise runtime.RuntimeFailClosed("simulated")

    assert rig.run(run_loop=failing) == ExitCode.FAIL_CLOSED_RUNTIME
    assert _lease_is_free(rig.state)


def test_the_lease_is_released_after_an_uncaught_exception(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0

    def crashing(_context: Any) -> None:
        raise RuntimeError("loop crashed")

    with pytest.raises(RuntimeError):
        rig.run(run_loop=crashing)
    assert _lease_is_free(rig.state)


def test_a_held_refusal_releases_the_lease_before_it_holds(rig: _Rig) -> None:
    """A held process owns nothing: the one-shot pin must be able to run beside it."""
    free_while_held: list[bool] = []
    rig_stopper: Callable[[], None]

    def wait_for_stop() -> None:
        free_while_held.append(_lease_is_free(rig.state))

    rig_stopper = wait_for_stop
    code = runtime.main(
        ["--hold-on-refusal", "--pinned-state", str(rig.pinned_path)],
        environ=rig.environ(),
        wait_for_stop=rig_stopper,
        state=rig.state,
        registry_root=rig.root,
        clock=rig.clock,
        run_loop=lambda _c: pytest.fail("must not run"),
    )
    assert code == ExitCode.NO_PINNED_EPOCH
    assert free_while_held == [True]


# ---- Test 3: --pin-epoch pins and exits (16-DEC-PIN-COMMAND) ---------------------------- #


def test_pin_epoch_pins_and_exits_without_the_loop(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.adapters import binance_public, paper_ws

    def trip(label: str) -> Any:
        def _tripped(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(f"{label} must not be constructed by the pin")

        return _tripped

    monkeypatch.setattr(paper_ws.PaperWsAdapter, "__init__", trip("PaperWsAdapter"))
    monkeypatch.setattr(
        binance_public.BinancePublicMarketData, "__init__", trip("BinancePublicMarketData")
    )
    skews: list[int] = []

    async def no_skew(*_args: object) -> int:
        skews.append(1)
        return 0

    monkeypatch.setattr(runtime, "measure_clock_skew", no_skew)
    writes: list[int] = []
    real_write = runtime.write_pinned_state

    def counting_write(epoch: Any, path: Path) -> None:
        writes.append(1)
        real_write(epoch, path)

    monkeypatch.setattr(runtime, "write_pinned_state", counting_write)

    code = runtime.main(
        ["--pin-epoch", "--pinned-state", str(rig.pinned_path)],
        environ=rig.environ(),
        wait_for_stop=lambda: pytest.fail("the pin never holds"),
        state=rig.state,
        registry_root=rig.root,
        clock=rig.clock,
    )

    assert code == 0
    assert writes == [1]
    assert skews == [], "the pin measures no clock skew"
    assert rig.types() == [RuntimeEventType.EPOCH_PINNED]
    assert _state(rig).writes == [RuntimeEventType.EPOCH_PINNED]


def test_a_start_after_the_pin_runs_the_loop(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0
    assert rig.types() == [RuntimeEventType.EPOCH_PINNED]
    ran: list[str] = []
    assert rig.run(run_loop=lambda context: ran.append(context.epoch.epoch_id)) == 0
    assert ran == [rig.pinned().epoch_id]
    assert rig.types() == [
        RuntimeEventType.EPOCH_PINNED,
        RuntimeEventType.RUNTIME_START,
        RuntimeEventType.RUNTIME_STOP,
    ]


def test_pin_epoch_with_hold_on_refusal_is_a_usage_error(
    rig: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    code = rig.run("--pin-epoch", "--hold-on-refusal")
    assert code == ExitCode.USAGE == 2
    assert "--pin-epoch" in capsys.readouterr().err
    assert rig.stops == 0
    assert not rig.pinned_path.exists()
    assert _state(rig).writes == []
    assert _state(rig).lease_requests == [], "a usage error takes no lease"


# ---- Test 7: losing the lease fails the loop closed ------------------------------------- #


def test_a_lost_lease_fails_the_run_closed_without_a_stop_record(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0

    def losing(context: Any) -> None:
        rig.state.lose_instance_lease(INSTANCE_LEASE_SCOPE)
        runtime.verify_instance_lease(context.lease)

    assert rig.run(run_loop=losing) == ExitCode.FAIL_CLOSED_RUNTIME
    assert rig.types().count(RuntimeEventType.RUNTIME_STOP) == 0
    assert _lease_is_free(rig.state), "the next instance can take the lease"


def test_an_unverifiable_lease_counts_as_lost() -> None:
    class Broken:
        def is_held(self) -> bool:
            raise OSError("connection reset")

        def release(self) -> None:
            return None

    with pytest.raises(runtime.RuntimeFailClosed, match="instance lease"):
        runtime.verify_instance_lease(Broken())


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Live]:
    import src.domain.registry as domain_registry

    from tests.paper_ws_fakes import fresh_sdk_stream_map

    fresh_sdk_stream_map(monkeypatch)
    rig = _Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    yield Live(rig)


def test_the_live_loop_checks_the_lease_at_every_consumer_batch(live: Live) -> None:
    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.state.lose_instance_lease(INSTANCE_LEASE_SCOPE)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await asyncio.sleep(5)

    code = live.start(script)

    assert code == ExitCode.FAIL_CLOSED_RUNTIME
    assert live.records(RuntimeEventType.PAPER_BAR_PROCESSED) == []
    assert live.records(RuntimeEventType.RUNTIME_STOP) == []
    assert len(live.records(RuntimeEventType.RUNTIME_START)) == 1


def test_the_live_loop_checks_the_lease_at_every_constraint_refresh_step(live: Live) -> None:
    """The existing refresh loop is a periodic step: a lost lease there fails the loop closed."""
    sleeps: list[float] = []

    async def fast_sleep(delay: Any) -> None:
        sleeps.append(delay.total_seconds())
        await asyncio.sleep(0)

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.state.lose_instance_lease(INSTANCE_LEASE_SCOPE)
        await asyncio.sleep(5)

    code = live.start(script, sleep=fast_sleep, context_factory=None)

    assert code == ExitCode.FAIL_CLOSED_RUNTIME
    assert live.records(RuntimeEventType.RUNTIME_STOP) == []
    assert sleeps, "the refresh loop ran at least one step"


def test_the_marker_module_is_not_used_by_the_pin(rig: _Rig, tmp_path: Path) -> None:
    """The one-shot pin never holds, so it never writes a held marker."""
    assert rig.run("--pin-epoch") == 0
    assert held_marker.read_own_marker(rig.pinned_path.parent) is None
