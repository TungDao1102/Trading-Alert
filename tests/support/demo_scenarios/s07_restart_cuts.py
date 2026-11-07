"""S07 restart mid-flow at three cut points (plan 25-12; EXEC-01, EXEC-03, D079, D080).

TEST_ONLY. One scenario module with a `cut` argument, shared by the CI twin (the fake composed
process) and the owner's Demo test (the real process). A crash is `env.abandon()` (no drain, the
stream stopped with the listenKey kept; a no-op on the fake, where the process is just not driven
any more) followed by `env.restart()`: a second process over the SAME stores and the SAME exchange
(25-RESEARCH Pattern 4). The cuts are deliberate in-process crashes that end flat.

* cut "c" (after the fill and the confirmed stop): the second process rehydrates the plan in the
  protection state the first one had, sends nothing to the exchange and the first reconcile tick is
  clean (a real Demo observation, no fault is injected).

Cuts "a" (before the entry answer is known) and "b" (between the fill and the stop) are added in
later tasks of the plan; `run` refuses any other name before it touches anything.

Labels: no step of cut "c" injects a trigger, so every step carries the env label (SYNTHETIC on the
fake, DEMO_OBSERVED on Demo).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from scripts import demo_rehearsal as dr
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState

from tests.support.demo_scenarios.harness import ScenarioRecorder, ensure_clean_start
from tests.support.demo_scenarios.s04_stop_rejected import (
    SCENARIO_FILL,
    drive_fill,
    record_step,
)
from tests.support.demo_scenarios.s06_replay import (
    close_and_clean,
    place_approved_entry,
    shutdown,
    start_evidence,
)

# Every adapter method that sends something to the exchange; the read-only ones are not listed.
MUTATING_METHODS: tuple[str, ...] = (
    "place_entry",
    "place_algo_protective",
    "place_market_close",
    "cancel_normal_order",
    "cancel_algo_order",
)

STEP_C_REHYDRATED = "cut_c_rehydrated_protected"
STEP_C_NOTHING_SENT = "cut_c_nothing_new_sent"
STEP_C_RECONCILE_CLEAN = "cut_c_reconcile_clean"

_PROTECTED_FAMILY = (
    ProtectionState.PROTECTED,
    ProtectionState.COMPLETE,
    ProtectionState.TP_UNAVAILABLE,
)


class _Processes:
    """The process that is running now and what a crash left behind.

    `first` is the env the scenario was given; `current` is the one a `restart()` returned (or
    `first`). A crashed process is never shut down in order (that would be a drain it did not get).
    """

    def __init__(self, first: Any) -> None:
        self.first = first
        self.current = first
        self.crashed = False

    async def crash(self) -> None:
        """The crash: no drain, the listenKey kept (`abandon`; a no-op on the fake)."""
        await self.current.abandon()
        self.crashed = True

    async def restart(self) -> Any:
        if self.current.restart is None:
            raise dr.SmokeHalt("restart_unavailable")
        self.current = await self.current.restart()
        self.crashed = False
        return self.current

    async def shutdown(self) -> None:
        """Stop the running process in order; a crashed one with no successor is left as it is."""
        if self.crashed:
            return
        await shutdown(self.current)


def mutating_counts(env: Any) -> dict[str, int]:
    """How many calls of each mutating adapter method reached the exchange edge so far.

    The fault edge records every adapter call of both processes (a restart re-binds the same
    object), whether or not a fault is armed, so the count is the same on the fake and on Demo.
    """
    return {method: len(env.faults.calls_to(method)) for method in MUTATING_METHODS}


def protection_of(env: Any, plan_hash: str) -> Any:
    return env.wiring.coordinator.protection_of(plan_hash)


# ---- the dispatcher ---------------------------------------------------------------------------- #

CutRunner = Callable[[Any, ScenarioRecorder, _Processes], Awaitable[str]]


async def run(env: Any, recorder: ScenarioRecorder, *, cut: str) -> str:
    """Run S07 at `cut` on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`.

    An unknown cut name raises `ValueError` before anything is read or recorded.
    """
    runner = _CUT_RUNNERS.get(cut)
    if runner is None:
        raise ValueError(f"unknown restart cut {cut!r}; expected one of {sorted(_CUT_RUNNERS)}")
    recorder.default_label = env.label
    recorder.details["cut"] = cut
    await ensure_clean_start(env, recorder)
    processes = _Processes(env)
    try:
        return await runner(env, recorder, processes)
    finally:
        await processes.shutdown()


# ---- cut (c): restart after the fill and the confirmed stop ------------------------------------ #


async def _cut_c(env: Any, recorder: ScenarioRecorder, processes: _Processes) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    first = await place_approved_entry(env, recorder, SCENARIO_FILL)
    await drive_fill(env, first)

    async def stop_confirmed() -> bool:
        view = protection_of(env, first.plan_hash)
        return view is not None and view.stop_confirmed_at_utc is not None

    if not await dr._wait_until(env, stop_confirmed):
        raise dr._smoke_fail(env, recorder, "stop_confirmed", "the stop was not confirmed by REST")
    stop_id = derive_algo_client_id(plan_hash=first.plan_hash, role=OrderRole.STOP_LOSS.value)
    recorder.record_ids(
        "stop_confirmed", order_ids=[], client_order_ids=[], algo_client_ids=[stop_id]
    )
    dr._smoke_record(env, recorder, "stop_confirmed", dr.STEP_PASSED, "the stop is REST-confirmed")

    async def complete() -> bool:
        view = protection_of(env, first.plan_hash)
        return view is not None and view.state in (
            ProtectionState.COMPLETE,
            ProtectionState.TP_UNAVAILABLE,
        )

    await dr._wait_until(env, complete)  # best effort: the take-profit legs follow the stop
    before = protection_of(env, first.plan_hash)
    if before is None or before.state not in _PROTECTED_FAMILY:
        state = None if before is None else before.state.value
        raise dr._smoke_fail(
            env, recorder, "stop_confirmed", f"not protected before the cut: {state}"
        )
    counts_before = mutating_counts(env)

    # ---- the crash and the second process ---------------------------------------------------- #
    await processes.crash()
    second = await processes.restart()
    await dr._bring_up(second, recorder, "restart")
    for _ in range(dr.SMOKE_REPLAY_SETTLE_TICKS):
        await second.tick()

    restored = protection_of(second, first.plan_hash)
    state_before = before.state
    if (
        restored is None
        or restored.state is not state_before
        or restored.stop_confirmed_at_utc is None
    ):
        state = None if restored is None else restored.state.value
        raise dr._smoke_fail(
            second,
            recorder,
            STEP_C_REHYDRATED,
            f"the plan was not rehydrated protected: {state} "
            f"(before the cut: {state_before.value})",
        )
    record_step(
        second,
        recorder,
        STEP_C_REHYDRATED,
        f"the second process rehydrated the plan {restored.state.value}, stop confirmed",
    )

    counts_after = mutating_counts(second)
    if counts_after != counts_before:
        raise dr._smoke_fail(
            second,
            recorder,
            STEP_C_NOTHING_SENT,
            f"the second process sent something: {counts_before} -> {counts_after}",
        )
    record_step(
        second,
        recorder,
        STEP_C_NOTHING_SENT,
        "the second process placed, cancelled and closed nothing (exchange edge counts unchanged)",
    )

    from src.live.reconcile import reconcile_tick_once

    report = await reconcile_tick_once(second.wiring.reconcile, second.clock())
    clean = report.agreement is True and not report.divergences and report.failed_source is None
    if not clean:
        raise dr._smoke_fail(
            second, recorder, STEP_C_RECONCILE_CLEAN, "the first reconcile compare was not clean"
        )
    record_step(
        second, recorder, STEP_C_RECONCILE_CLEAN, "the first reconcile agrees, no divergence"
    )
    recorder.details["cut_c"] = {
        "state_before_crash": state_before.value,
        "state_after_restart": restored.state.value,
        "stop_confirmed_after_restart": restored.stop_confirmed_at_utc is not None,
        "stop_client_algo_id": stop_id,
        "mutating_calls_before_crash": counts_before,
        "mutating_calls_after_restart": counts_after,
    }
    await close_and_clean(second, recorder, first)
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE


_CUT_RUNNERS: dict[str, CutRunner] = {"c": _cut_c}
