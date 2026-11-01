"""`run_admitted` (plan 24-27 task 3): start, wait for the stop, stop in order, drain and close.

The assembly is the real `build_wiring` product over fakes at the edges (see
`tests/support/live_wiring_rig.py`); the start sequence itself is replaced by a function that
completes the assembly the way step 4 does and reports an outcome, because the real sequence needs
PostgreSQL (the sequence has its own tests, tests/test_live_start_sequence.py). The stop signal is
an injected `wait_for_stop`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import src.live.startup as startup_module
from src.live import runtime
from src.live.config import LiveExitCode, live_liveness_problem, read_live_liveness
from src.live.runtime import LiveContext, run_admitted, shutdown_in_order
from src.live.startup import StartupOutcome
from src.paper import held_marker

from tests.shadow_fakes import T0
from tests.support.execution_limits import (
    TEST_ONLY_EXECUTION_LIMIT_VALUES,
    write_execution_limits_toml,
)
from tests.support.live_wiring_rig import (
    WiringHandles,
    complete_assembly,
    forbid_connections,
    make_assembly,
    make_config,
)
from tests.test_live_config_refusal import demo_env


@pytest.fixture(autouse=True)
def _no_connections(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return forbid_connections(monkeypatch)


def outcome(*, admitted: bool = True, step: str | None = None, code: str | None = None) -> Any:
    return StartupOutcome(
        admitted=admitted,
        held_step=step,
        held_code=code,
        held_message=None if admitted else "refused by the test",
        safe_mode_reasons=(),
        safe_mode_errors=(),
        in_safe_mode=False,
        started_tasks=(),
        enabled=admitted,
        enable_reason=None,
        first_install=False,
        steps=(),
        degraded_steps=(),
        recovery=None,
        reconcile=None,
    )


def context(
    tmp_path: Path, *, hold: bool = False, wait: Callable[[], None] | None = None
) -> LiveContext:
    config = make_config(tmp_path)
    return LiveContext(
        config=config,
        env={},
        clock=lambda: T0,
        started_at_utc=T0,
        initialize_gate_state=False,
        operator_id=None,
        hold_on_refusal=hold,
        wait_for_stop=wait if wait is not None else (lambda: None),
    )


def patch_sequence(
    monkeypatch: pytest.MonkeyPatch,
    handles: WiringHandles,
    *,
    result: Any,
    complete: bool = True,
) -> None:
    async def fake_sequence(_ports: Any, *, now_utc: Any) -> Any:
        if complete:
            await complete_assembly(handles)
        return result

    monkeypatch.setattr(startup_module, "run_start_sequence", fake_sequence)


# --------------------------------------------------------------------------- #
# Start and stop.
# --------------------------------------------------------------------------- #


def test_an_admitted_start_runs_until_the_stop_and_closes_the_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handles = make_assembly(tmp_path)
    patch_sequence(monkeypatch, handles, result=outcome())
    stopped: list[bool] = []

    def wait() -> None:
        stopped.append(True)

    code = run_admitted(context(tmp_path, wait=wait), assemble=lambda _ctx: handles.assembly)
    assert code == int(LiveExitCode.OK)
    assert stopped == [True]
    assert handles.assembly.executor.closed


def test_main_calls_the_runner_with_the_admitted_context_and_returns_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handles = make_assembly(tmp_path)
    patch_sequence(monkeypatch, handles, result=outcome())
    seen: list[LiveContext] = []

    def runner(ctx: LiveContext) -> int:
        seen.append(ctx)
        return run_admitted(ctx, assemble=lambda _c: handles.assembly)

    root = tmp_path / "repo"
    root.mkdir()
    limits = write_execution_limits_toml(
        tmp_path / "limits.toml", values=dict(TEST_ONLY_EXECUTION_LIMIT_VALUES)
    )
    code = runtime.main(
        ["--state-dir", str(tmp_path / "main-state")],
        environ=demo_env(),
        wait_for_stop=lambda: None,
        clock=lambda: T0,
        run_live=runner,
        repo_root=root,
        limits_path=limits,
    )
    assert code == int(LiveExitCode.OK)
    assert len(seen) == 1 and seen[0].wait_for_stop is not None


def test_a_refused_start_reports_its_step_and_code_and_closes_the_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    handles = make_assembly(tmp_path)
    patch_sequence(
        monkeypatch,
        handles,
        result=outcome(admitted=False, step="ALEMBIC", code="ALEMBIC_MISMATCH"),
        complete=False,
    )
    code = run_admitted(context(tmp_path), assemble=lambda _ctx: handles.assembly)
    err = capsys.readouterr().err
    assert code == int(LiveExitCode.STARTUP_FAILED)
    assert "held at step ALEMBIC (ALEMBIC_MISMATCH)" in err
    assert handles.assembly.executor.closed


def test_hold_on_refusal_consumes_the_held_step_and_writes_the_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handles = make_assembly(tmp_path)
    patch_sequence(
        monkeypatch,
        handles,
        result=outcome(admitted=False, step="GATE", code="GATE_STATE_MISSING"),
        complete=False,
    )
    marker_dir = make_config(tmp_path).held_marker_dir
    during: list[held_marker.HeldMarker | None] = []

    def wait() -> None:
        during.append(held_marker.read_own_marker(marker_dir))

    code = run_admitted(
        context(tmp_path, hold=True, wait=wait), assemble=lambda _ctx: handles.assembly
    )
    assert code == int(LiveExitCode.STARTUP_FAILED)
    assert len(during) == 1 and during[0] is not None, "the marker exists while held"
    assert "held at step GATE" in during[0].refusal or during[0].refusal == "STARTUP_FAILED"
    assert held_marker.read_own_marker(marker_dir) is None, "removed once the hold ends"


def test_a_broken_wiring_link_refuses_to_start_and_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    handles = make_assembly(tmp_path)

    async def sequence_with_a_dropped_link(_ports: Any, *, now_utc: Any) -> Any:
        wiring = await complete_assembly(handles)
        wiring.coordinator._restore_required = False  # the link under test
        return outcome()

    monkeypatch.setattr(startup_module, "run_start_sequence", sequence_with_a_dropped_link)
    code = run_admitted(context(tmp_path), assemble=lambda _ctx: handles.assembly)
    err = capsys.readouterr().err
    assert code == int(LiveExitCode.STARTUP_FAILED)
    assert "coordinator_restore_required" in err
    assert handles.assembly.executor.closed


def test_a_start_sequence_that_raises_fails_closed_naming_the_class_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    handles = make_assembly(tmp_path)

    async def boom(_ports: Any, *, now_utc: Any) -> Any:
        raise RuntimeError("secret-looking-detail")

    monkeypatch.setattr(startup_module, "run_start_sequence", boom)
    code = run_admitted(context(tmp_path), assemble=lambda _ctx: handles.assembly)
    err = capsys.readouterr().err
    assert code == int(LiveExitCode.STARTUP_FAILED)
    assert "RuntimeError" in err and "secret-looking-detail" not in err


def test_an_assembly_that_cannot_be_built_fails_closed_naming_the_class_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(_ctx: LiveContext) -> Any:
        raise ValueError("secret-looking-detail")

    code = run_admitted(context(tmp_path), assemble=broken)
    err = capsys.readouterr().err
    assert code == int(LiveExitCode.STARTUP_FAILED)
    assert "ValueError" in err and "secret-looking-detail" not in err


def test_without_a_database_url_the_default_assembly_refuses_naming_the_variables(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_admitted(context(tmp_path))
    assert code == int(LiveExitCode.STARTUP_FAILED)
    assert "DATABASE_URL_SYNC or DATABASE_URL is not set" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# The stop order.
# --------------------------------------------------------------------------- #


class _Recorder:
    def __init__(self, order: list[str], name: str, *, fails: bool = False) -> None:
        self._order, self._name, self._fails = order, name, fails

    async def _hit(self) -> None:
        self._order.append(self._name)
        if self._fails:
            raise RuntimeError(self._name)

    async def stop(self, **_kwargs: Any) -> None:
        await self._hit()

    async def drain(self) -> None:
        await self._hit()

    async def aclose(self) -> None:
        await self._hit()


def _fake_assembly(order: list[str], tmp_path: Path, *, failing: str | None = None) -> Any:
    def rec(name: str) -> _Recorder:
        return _Recorder(order, name, fails=name == failing)

    scheduler = SimpleNamespace(stop=lambda: order.append("scheduler.stop"))

    async def scheduler_done() -> None:
        order.append("scheduler.done")

    wiring = SimpleNamespace(
        scheduler=scheduler,
        runner=SimpleNamespace(stop=rec("bot").stop),
        stream=SimpleNamespace(
            supervisor=SimpleNamespace(stop=rec("supervisor").stop),
            fanout=SimpleNamespace(drain=rec("stream_writes").drain),
        ),
        persistence=SimpleNamespace(drain=rec("persistence").drain),
        service=SimpleNamespace(drain=rec("service").drain),
    )

    async def make_task() -> asyncio.Task[None]:
        return asyncio.ensure_future(scheduler_done())

    return SimpleNamespace(
        is_complete=True,
        wiring=wiring,
        scheduler_task=None,
        make_task=make_task,
        config=SimpleNamespace(liveness_dir=tmp_path),
        executor=SimpleNamespace(aclose=rec("executor").aclose),
    )


async def test_the_stop_order_is_scheduler_bot_supervisor_writes_service_executor(
    tmp_path: Path,
) -> None:
    order: list[str] = []
    assembly = _fake_assembly(order, tmp_path)
    assembly.scheduler_task = await assembly.make_task()
    failed = await shutdown_in_order(assembly)
    assert failed == []
    assert order == [
        "scheduler.stop",
        "scheduler.done",
        "bot",
        "supervisor",
        "stream_writes",
        "persistence",
        "service",
        "executor",
    ]


async def test_a_failing_step_is_recorded_and_the_next_steps_still_run(tmp_path: Path) -> None:
    order: list[str] = []
    assembly = _fake_assembly(order, tmp_path, failing="bot")
    failed = await shutdown_in_order(assembly)
    assert failed == ["bot"]
    assert order[-3:] == ["persistence", "service", "executor"]


async def test_a_placement_in_flight_and_a_queued_write_complete_before_the_close(
    tmp_path: Path,
) -> None:
    handles = make_assembly(tmp_path)
    wiring = await complete_assembly(handles)
    assembly = handles.assembly
    release = asyncio.Event()
    done: list[str] = []

    async def placement() -> None:
        await release.wait()
        done.append("placement")

    task = asyncio.ensure_future(placement())
    wiring.service._tasks.add(task)
    task.add_done_callback(wiring.service._tasks.discard)
    written: list[str] = []
    queued = asyncio.ensure_future(assembly.executor.write(lambda: written.append("write")))
    asyncio.get_running_loop().call_later(0.05, release.set)

    failed = await shutdown_in_order(assembly)
    await queued
    assert done == ["placement"], "the placement completed, it was never cancelled mid-send"
    assert written == ["write"], "the queued write completed"
    assert assembly.executor.closed
    assert "service" not in failed and "executor" not in failed


async def test_shutdown_of_an_assembly_that_never_completed_still_closes_the_executor(
    tmp_path: Path,
) -> None:
    handles = make_assembly(tmp_path)
    assert not handles.assembly.is_complete
    assert await shutdown_in_order(handles.assembly) == []
    assert handles.assembly.executor.closed


# --------------------------------------------------------------------------- #
# The liveness stamp.
# --------------------------------------------------------------------------- #


async def test_the_liveness_stamp_is_written_with_the_scheduler_results_and_accepted(
    tmp_path: Path,
) -> None:
    handles = make_assembly(tmp_path)
    wiring = await complete_assembly(handles)
    assembly = handles.assembly
    spec = next(s for s in wiring.specs if s.name == "liveness_stamp")
    await spec.run()
    stamp = read_live_liveness(assembly.config.liveness_dir)
    assert stamp is not None
    assert stamp.mode == "DEMO"
    assert stamp.loop_alive_utc == handles.clock.now()
    assert set(stamp.tasks) == {s.name for s in wiring.specs}
    assert all(value == "PASS" for value in stamp.tasks.values())
    bound_ms = int(timedelta(seconds=30).total_seconds() * 1000)
    assert (
        live_liveness_problem(
            assembly.config.liveness_dir, now_utc=handles.clock.now(), bound_ms=bound_ms
        )
        is None
    )
