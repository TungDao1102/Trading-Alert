"""S07 restart mid-flow at three cut points (plan 25-12; EXEC-01, EXEC-03, D079, D080).

TEST_ONLY. One scenario module with a `cut` argument, shared by the CI twin (the fake composed
process) and the owner's Demo test (the real process). A crash is `env.abandon()` (no drain, the
stream stopped with the listenKey kept; a no-op on the fake, where the process is just not driven
any more) followed by `env.restart()`: a second process over the SAME stores and the SAME exchange
(25-RESEARCH Pattern 4). The cuts are deliberate in-process crashes that end flat.

* cut "c" (after the fill and the confirmed stop): the second process rehydrates the plan in the
  protection state the first one had, sends nothing to the exchange and the first reconcile tick is
  clean (a real Demo observation, no fault is injected).

* cut "a" (before the entry answer is known, D080): the entry POST reaches the exchange but its
  answer is lost (`drop_response_after_send`) and the process's own probe by client id fails
  (`raise_before_send` on `query_order_by_client`), so the process leaves the entry UNKNOWN with
  SAFE_MODE ENTRY_STATE_UNKNOWN and crashes. The second process's start recovery probes once by the
  deterministic client id: found means ACKED and tracked. Across both processes exactly one
  `place_entry` exists. `probe_error=True` (twin only) makes that recovery probe fail too: the
  entry stays UNKNOWN with SAFE_MODE, still nothing is re-sent.

Cut "b" (between the fill and the stop) is added in a later task of the plan; `run` refuses any
other name before it touches anything.

Labels: the lost answer and the failed probe are injected triggers (DEMO_FAULT_INJECTED on Demo,
`label_for(env, injected=True)`); what the processes then do is the real reaction and carries the
env label (SYNTHETIC on the fake, DEMO_OBSERVED on Demo). Cut "c" injects nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from binance_common.errors import BadRequestError
from scripts import demo_rehearsal as dr
from src.domain.enums import ExecutionIntentStatus, OrderRole, TradePlanStatus
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState

from tests.support.demo_scenarios.harness import (
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
)
from tests.support.demo_scenarios.s04_stop_rejected import (
    SCENARIO_FILL,
    STEP_SAFE_MODE_LEFT,
    drive_fill,
    record_injection_step,
    record_step,
)
from tests.support.demo_scenarios.s06_replay import (
    SCENARIO_FAR,
    cancel_resting_entry,
    close_and_clean,
    place_approved_entry,
    place_entry_calls,
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

STEP_A_LOST_ANSWER = "cut_a_lost_answer"
STEP_A_ENTRY_UNKNOWN = "cut_a_entry_unknown"
STEP_A_RECOVERY = "cut_a_recovery_probe"
STEP_A_ONE_ENTRY = "cut_a_one_place_entry"

# "Send status unknown": the exchange may have taken the order (taxonomy STATUS_UNKNOWN).
LOST_ANSWER_CODE = -1007
ENTRY_METHOD = "place_entry"
PROBE_METHOD = "query_order_by_client"

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

CutRunner = Callable[[Any, ScenarioRecorder, _Processes, bool], Awaitable[str]]


async def run(env: Any, recorder: ScenarioRecorder, *, cut: str, probe_error: bool = False) -> str:
    """Run S07 at `cut` on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`.

    An unknown cut name raises `ValueError` before anything is read or recorded. `probe_error`
    (cut "a" on the twin only) makes the second process's recovery probe fail as well.
    """
    runner = _CUT_RUNNERS.get(cut)
    if runner is None:
        raise ValueError(f"unknown restart cut {cut!r}; expected one of {sorted(_CUT_RUNNERS)}")
    if probe_error and (cut != "a" or not env.synthetic):
        raise ValueError("probe_error is a twin-only option of cut 'a' (the recovery probe fails)")
    recorder.default_label = env.label
    recorder.details["cut"] = cut
    await ensure_clean_start(env, recorder)
    processes = _Processes(env)
    try:
        return await runner(env, recorder, processes, probe_error)
    finally:
        await processes.shutdown()


# ---- cut (c): restart after the fill and the confirmed stop ------------------------------------ #


async def _cut_c(
    env: Any, recorder: ScenarioRecorder, processes: _Processes, probe_error: bool
) -> str:
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


# ---- cut (a): the entry answer is lost and the process crashes (D080) -------------------------- #


def lost_answer() -> BadRequestError:
    """A timeout-shaped answer ("send status unknown"); the text says TEST_ONLY, never read."""
    return BadRequestError(
        error_message="TEST_ONLY injected lost answer", status_code=LOST_ANSWER_CODE
    )


def record_lost_answer(env: Any, recorder: ScenarioRecorder, detail: str) -> None:
    """The lost answer and the failed probe are injected triggers (T-25-25)."""
    record_injection_step(env, recorder, detail, name=STEP_A_LOST_ANSWER)


def record_recovery(env: Any, recorder: ScenarioRecorder, detail: str) -> None:
    """What the second process's recovery did: the real reaction, the env label."""
    record_step(env, recorder, STEP_A_RECOVERY, detail)


async def start_tolerant(env: Any, recorder: ScenarioRecorder, label: str) -> Any:
    """Run the start sequence of `env`'s process and record it, tolerating SAFE_MODE.

    `dr._bring_up` insists on an enabled process; a restart that inherited SAFE_MODE is admitted
    but not enabled, which is exactly the state this cut shows. The record has the shape
    `_bring_up` writes. A refused admission and a failed recovery step still stop the scenario.
    """
    from src.live.startup import run_start_sequence
    from src.live.wiring import check_wiring

    ports = env.ports_transform(
        env.assembly.startup_ports(
            initialize_gate_state=env.initialize_gate_state, operator_id=dr.OPERATOR_ID
        )
    )
    outcome = await run_start_sequence(ports, now_utc=env.clock())
    recovery = outcome.recovery
    steps = ", ".join(f"{s.name}={s.outcome}" for s in outcome.steps)
    recorder.details.setdefault("start_sequences", []).append(
        {
            "label": label,
            "admitted": outcome.admitted,
            "steps": steps,
            "safe_mode_reasons": list(outcome.safe_mode_reasons),
            "recovery_failed_steps": [] if recovery is None else list(recovery.failed_steps),
            "recovery_safe_mode_reasons": []
            if recovery is None
            else list(recovery.safe_mode_reasons),
            "plans_restored": None if recovery is None else recovery.plans_restored,
        }
    )
    if not outcome.admitted:
        raise dr._smoke_fail(
            env, recorder, label, f"held at {outcome.held_step} ({outcome.held_code})"
        )
    if recovery is None or recovery.failed_steps:
        failed = "no recovery report" if recovery is None else ", ".join(recovery.failed_steps)
        raise dr._smoke_fail(env, recorder, label, f"recovery failed at {failed}")
    broken = check_wiring(env.assembly.wiring)
    if broken:
        raise dr._smoke_fail(env, recorder, "wiring_check", f"broken links: {', '.join(broken)}")
    mode = "in SAFE_MODE" if outcome.in_safe_mode else "not in SAFE_MODE"
    enabled = "entries enabled" if outcome.enabled else "entries not enabled"
    dr._smoke_record(env, recorder, label, dr.STEP_PASSED, f"admitted, {mode}, {enabled}")
    return outcome


async def _intent_status_value(env: Any, client_id: str) -> str | None:
    read = env.wiring.stores.execution_state.intent_for_client_id
    row = await dr._smoke_read(env, read, client_id)
    return None if row is None else str(row.intent_status.value)


async def _first_process_to_unknown(env: Any, recorder: ScenarioRecorder) -> Any:
    """Inject, card, APPROVE, CONFIRM; the entry ends UNKNOWN (never ACKED). Returns the request."""
    first = await dr._inject(env, recorder, SCENARIO_FAR, "signal")
    wiring = env.wiring

    async def card_issued() -> bool:
        if wiring.demo_signal is None or wiring.demo_signal.source.pending != 0:
            return False
        row = await dr._smoke_read(env, wiring.stores.entities.get_trade_plan, first.trade_plan_id)
        return row is not None

    if not await dr._wait_until(env, card_issued):
        raise dr._smoke_fail(env, recorder, "card", "the approval card was not issued")
    dr._smoke_record(env, recorder, "card", dr.STEP_PASSED, "the composed pump sent the card")
    await env.owner.act("approve", short_id=first.short_id, note="")

    async def approved() -> bool:
        row = await dr._smoke_read(env, wiring.stores.entities.get_trade_plan, first.trade_plan_id)
        return row is not None and row.status is TradePlanStatus.APPROVED

    if not await dr._wait_until(env, approved):
        raise dr._smoke_fail(env, recorder, "approve", "no APPROVE was seen before the timeout")
    dr._smoke_record(env, recorder, "approve", dr.STEP_PASSED, "the plan is APPROVED")
    await env.owner.act("confirm", short_id=first.short_id, note="")

    async def unknown() -> bool:
        status = await _intent_status_value(env, first.entry_client_id)
        return status == ExecutionIntentStatus.UNKNOWN.value

    if not await dr._wait_until(env, unknown):
        status = await _intent_status_value(env, first.entry_client_id)
        raise dr._smoke_fail(
            env, recorder, STEP_A_ENTRY_UNKNOWN, f"the entry intent is {status}, expected UNKNOWN"
        )
    return first


async def _cut_a(
    env: Any, recorder: ScenarioRecorder, processes: _Processes, probe_error: bool
) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    facts: dict[str, Any] = {"branch": "probe_error" if probe_error else "found"}
    recorder.details["cut_a"] = facts

    # The entry's answer is lost after the POST reached the exchange; the process's own probe by
    # client id then fails too (both are consumed by the first placement of the plan).
    env.faults.drop_response_after_send(ENTRY_METHOD, lost_answer(), times=1)
    env.faults.raise_before_send(PROBE_METHOD, lost_answer(), times=1)
    first = await _first_process_to_unknown(env, recorder)
    entry_id = first.entry_client_id

    posts = env.faults.calls_to(ENTRY_METHOD)
    probes = env.faults.calls_to(PROBE_METHOD)
    if (
        len(posts) != 1
        or posts[0]["injected"] is not True
        or len(probes) != 1
        or probes[0]["injected"] is not True
        or probes[0]["kwargs"].get("orig_client_order_id") != entry_id
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_A_LOST_ANSWER,
            f"{len(posts)} place_entry call(s) and {len(probes)} probe call(s) at the edge; "
            "expected one dropped POST and one failed probe by the entry's client id",
        )
    record_lost_answer(
        env,
        recorder,
        "the entry POST reached the exchange and its answer was dropped; the process's own "
        "probe by client id failed",
    )
    reason = getattr(env.wiring.safe_mode, "entered_reason", None)
    if not env.wiring.safe_mode.in_safe_mode or reason != "ENTRY_STATE_UNKNOWN":
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_A_ENTRY_UNKNOWN,
            f"SAFE_MODE is {env.wiring.safe_mode.in_safe_mode} with reason {reason}",
        )
    record_step(
        env,
        recorder,
        STEP_A_ENTRY_UNKNOWN,
        "the entry intent is UNKNOWN and SAFE_MODE ENTRY_STATE_UNKNOWN is on (D080); "
        "nothing is re-sent",
    )
    facts.update(
        {
            "intent_after_lost_answer": "UNKNOWN",
            "safe_mode_reason_first_process": reason,
            "probe_calls_first_process": len(probes),
        }
    )
    counts_before = mutating_counts(env)

    # ---- the crash and the second process ---------------------------------------------------- #
    await processes.crash()
    second = await processes.restart()
    if probe_error:
        second.faults.raise_before_send(PROBE_METHOD, lost_answer(), times=1)
    probes_before = len(second.faults.calls_to(PROBE_METHOD))
    outcome = await start_tolerant(second, recorder, "restart")
    probes_in_start = second.faults.calls_to(PROBE_METHOD)[probes_before:]
    report = outcome.recovery.intents
    resolved = [[role, status.value] for _, role, status in report.resolved]
    unresolved = [[role, status.value] for _, role, status in report.unresolved]
    facts.update(
        {
            "restart_in_safe_mode": bool(outcome.in_safe_mode),
            "restart_entries_enabled": bool(outcome.enabled),
            "recovery_resolved": resolved,
            "recovery_unresolved": unresolved,
            "recovery_safe_mode_entered": bool(report.safe_mode_entered),
            "recovery_probe_calls": len(probes_in_start),
        }
    )
    wiring = second.wiring
    if not (outcome.in_safe_mode and not outcome.enabled):
        raise dr._smoke_fail(
            second,
            recorder,
            STEP_A_RECOVERY,
            "the second process did not start blocked by SAFE_MODE",
        )
    if probe_error:
        first_probe = probes_in_start[0] if probes_in_start else None
        if (
            first_probe is None
            or first_probe["injected"] is not True
            or resolved
            or unresolved != [["ENTRY", "UNKNOWN"]]
            or not report.safe_mode_entered
        ):
            raise dr._smoke_fail(
                second,
                recorder,
                STEP_A_RECOVERY,
                f"the failed recovery probe did not leave the entry UNKNOWN: resolved {resolved}, "
                f"unresolved {unresolved}",
            )
        record_recovery(
            second,
            recorder,
            "the recovery probe failed: the entry stays UNKNOWN and SAFE_MODE stays on; "
            "nothing is re-sent",
        )
    else:
        probe = probes_in_start[0] if len(probes_in_start) == 1 else None
        if (
            probe is None
            or probe["kwargs"].get("orig_client_order_id") != entry_id
            or resolved != [["ENTRY", "ACKED"]]
            or unresolved
        ):
            raise dr._smoke_fail(
                second,
                recorder,
                STEP_A_RECOVERY,
                f"{len(probes_in_start)} probe call(s) in the start sequence, resolved {resolved}, "
                f"unresolved {unresolved}; expected one probe by the entry's client id and ACKED",
            )
        record_recovery(
            second,
            recorder,
            "the start recovery probed once by the entry's client id, found the order and "
            "recorded it ACKED",
        )
    facts["intent_after_restart"] = await _intent_status_value(second, entry_id)
    facts["safe_mode_reason_after_restart"] = getattr(wiring.safe_mode, "entered_reason", None)
    view = wiring.coordinator.protection_of(first.plan_hash)
    facts["plan_tracked_after_restart"] = view is not None
    facts["plan_state_after_restart"] = None if view is None else view.state.value
    if view is None:
        raise dr._smoke_fail(
            second, recorder, STEP_A_RECOVERY, "the restored plan is not tracked by the coordinator"
        )

    # ---- one entry across both processes ----------------------------------------------------- #
    for _ in range(dr.SMOKE_REPLAY_SETTLE_TICKS):
        await second.tick()
    placed = place_entry_calls(second)
    on_exchange = None if second.placements is None else second.placements()
    counts_after = mutating_counts(second)
    sent_after = {m: counts_after[m] - counts_before[m] for m in MUTATING_METHODS}
    if placed != 1 or on_exchange not in (None, 1) or any(sent_after.values()):
        raise dr._smoke_fail(
            second,
            recorder,
            STEP_A_ONE_ENTRY,
            f"{placed} place_entry call(s) at the edge, {on_exchange} at the exchange, "
            f"sent by the second process: {sent_after}",
        )
    record_step(
        second,
        recorder,
        STEP_A_ONE_ENTRY,
        "exactly one place_entry across both processes and nothing sent by the second one",
    )

    # ---- resolve it the documented way: cancel the entry, then the owner leaves SAFE_MODE ----- #
    await cancel_resting_entry(second, recorder, first)
    if wiring.safe_mode.in_safe_mode:
        await second.owner.act("safemode_exit")

        async def left() -> bool:
            return not wiring.safe_mode.in_safe_mode

        if not await dr._wait_until(second, left):
            raise dr._smoke_fail(
                second,
                recorder,
                STEP_SAFE_MODE_LEFT,
                "SAFE_MODE was not left by /safemode_exit; read its refusal rows, then leave it "
                "by hand (RUNBOOK 21.1a) and run scripts/demo_clear.py if anything is left",
            )
    facts["safe_mode_after_exit"] = bool(wiring.safe_mode.in_safe_mode)
    record_step(
        second, recorder, STEP_SAFE_MODE_LEFT, "SAFE_MODE is off (left through /safemode_exit)"
    )
    if not await account_clean(second, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE


_CUT_RUNNERS: dict[str, CutRunner] = {"a": _cut_a, "c": _cut_c}
