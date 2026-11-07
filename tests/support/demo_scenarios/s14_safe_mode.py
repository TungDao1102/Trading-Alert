"""S14 SAFE_MODE entry and operator exit (plan 25-15; OPS-01, D080, D-15, RUNBOOK 21.1a).

TEST_ONLY. An entry whose state cannot be resolved puts the process in SAFE_MODE, the process keeps
monitoring, and only the operator's two steps (`/safemode_exit`, then `/confirm <token>`) leave it,
and only once the cause is gone. The scenario shows it on the real composed process:

1. The entry POST reaches the exchange but its answer is lost (`drop_response_after_send`) and
   the probe by client id fails (`raise_before_send` on `query_order_by_client`, until cleared).
   Both are injected triggers (DEMO_FAULT_INJECTED on Demo, `label_for(env, injected=True)`). The
   intent stays UNKNOWN and SAFE_MODE ENTRY_STATE_UNKNOWN is entered (D080); nothing is re-sent.
2. While SAFE_MODE stands the reconcile and the health ticks keep running: at least two further
   `RECONCILE_TICK` and `HEALTH_VERDICT` rows are journaled and the resolver's probes keep failing.
3. A second request is refused before it gets a card: the approval sender refuses a symbol with an
   unresolved entry intent, an active plan or a resting entry (one plan per symbol), the first
   fail-closed layer. It is recorded as observed, not as the SAFE_MODE guard.
4. `/safemode_exit` plus `/confirm` is refused (`UNKNOWN_INTENT_PRESENT`, a `SAFE_MODE_EXIT_REFUSED`
   row), and SAFE_MODE stays.
5. The probe works again (the fault is cleared). The reconcile resolver finds the order by its
   client id and records the intent ACKED; closing an intent never exits SAFE_MODE (D-15), so it
   stands.
6. The operator cancels the resting entry by its client id (the documented resolution), a new
   request is approved and its CONFIRM is refused (`RECONCILIATION_REQUIRED`): this is the SAFE_MODE
   guard itself, nothing is sent.
7. `/safemode_exit` plus `/confirm <token>` is accepted (one `SAFE_MODE_EXIT` row with the operator
   id), a new request is placed and cancelled, and the account ends clean.

The exit steps are the real reaction and carry the env label; the lost answer and the failed probe
are the only injected steps. SAFE_MODE is durable on Demo, so the exit is part of the run.
"""

from __future__ import annotations

import json
from typing import Any

from scripts import demo_rehearsal as dr
from src.domain.enums import ExecutionIntentStatus
from src.live.approval_sender import EVENT_REQUEST_REFUSED

from tests.support.demo_scenarios.harness import (
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
    label_for,
)
from tests.support.demo_scenarios.s04_stop_rejected import record_injection_step, record_step
from tests.support.demo_scenarios.s06_replay import (
    cancel_resting_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)
from tests.support.demo_scenarios.s07_restart_cuts import ENTRY_METHOD, PROBE_METHOD, lost_answer
from tests.support.demo_scenarios.s08_stream_loss import (
    card_and_approve,
    expire_plan,
    health_verdict,
    leave_safe_mode,
    placement_decision,
)

SCENARIO_FAR = "far"
UNKNOWN_REASON = "ENTRY_STATE_UNKNOWN"
UNKNOWN_INTENT_REFUSAL = "UNKNOWN_INTENT_PRESENT"

STEP_INJECT = "inject_lost_answer_and_failing_probe"
STEP_UNKNOWN = "entry_unknown_safe_mode_entered"
STEP_MONITORING = "monitoring_continues_in_safe_mode"
STEP_SECOND_REQUEST = "second_request_refused_while_unknown"
STEP_EXIT_REFUSED = "safemode_exit_refused_while_unknown"
STEP_RECONCILED = "entry_reconciled_by_the_probe"
STEP_CONFIRM_REFUSED = "confirm_refused_in_safe_mode"
STEP_EXIT = "safe_mode_left"
STEP_ENTRY_ALLOWED = "entry_allowed_after_the_exit"

_RECONCILE_CORRELATION = "reconcile_loop"
_SAFE_MODE_CORRELATION = "reconcile_safe_mode"
_HEALTH_CORRELATION = "execution_health"
_SAFE_MODE_ENTER_EVENTS = ("SAFE_MODE_ENTER", "SAFE_MODE_REENTER")
_MONITORED_TICKS = 2


def record_inject(env: Any, recorder: ScenarioRecorder, detail: str) -> None:
    """The injected trigger: DEMO_FAULT_INJECTED on Demo, never DEMO_OBSERVED."""
    record_injection_step(env, recorder, detail, name=STEP_INJECT)


def record_reaction(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A reaction of the real process: the env label."""
    record_step(env, recorder, name, detail)


def _record_gap_with_env_label(
    env: Any, recorder: ScenarioRecorder, name: str, detail: str
) -> None:
    """An observed result that is not the expected one: NOT_REHEARSED, labelled as observed."""
    prefix = "SYNTHETIC: " if env.synthetic else ""
    recorder.add_labeled_step(
        name, dr.STEP_NOT_REHEARSED, prefix + detail, label=label_for(env, injected=False)
    )


# ---- reads ------------------------------------------------------------------------------------- #


def _rows_of(journal: Any, correlation_id: str) -> list[Any]:
    return list(journal.list_by_correlation(correlation_id))


async def journal_rows(
    env: Any, correlation_id: str, event_type: str | tuple[str, ...]
) -> list[Any]:
    """The journal rows of one correlation and event type(s), through the process's executor."""
    wanted = (event_type,) if isinstance(event_type, str) else event_type
    rows = await env.assembly.executor.read(_rows_of, env.wiring.stores.journal, correlation_id)
    return [row for row in rows if row.event_type in wanted]


async def intent_status(env: Any, client_id: str) -> str | None:
    read = env.wiring.stores.execution_state.intent_for_client_id
    row = await dr._smoke_read(env, read, client_id)
    return None if row is None else str(row.intent_status.value)


def probe_calls(env: Any) -> list[dict[str, Any]]:
    return list(env.faults.calls_to(PROBE_METHOD))


def probe_interval_seconds(env: Any) -> int:
    """The configured spacing of the resolver's probes (the loaded limits), rounded up."""
    interval_ms = env.assembly.config.limits.reconcile_entry_unknown_probe_interval_ms
    return int(-(-int(interval_ms) // 1000))


async def _enter_reasons(env: Any) -> list[str]:
    rows = await journal_rows(env, _SAFE_MODE_CORRELATION, _SAFE_MODE_ENTER_EVENTS)
    return sorted({str(json.loads(row.payload_json).get("reason")) for row in rows})


async def _await_decision(env: Any, recorder: ScenarioRecorder, request: Any, step: str) -> Any:
    async def decided() -> bool:
        return bool(await placement_decision(env, request))

    if not await dr._wait_until(env, decided):
        raise dr._smoke_fail(env, recorder, step, "the CONFIRM left no journaled decision")
    return await placement_decision(env, request)


# ---- the scenario ------------------------------------------------------------------------------ #


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S14 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder)
    finally:
        env.faults.clear(ENTRY_METHOD)
        env.faults.clear(PROBE_METHOD)  # the probe works again whatever happened
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    facts: dict[str, Any] = recorder.details.setdefault("safe_mode_drill", {})

    first = await _make_the_entry_unknown(env, recorder, facts)
    await _monitoring_continues(env, recorder, facts)
    await _second_request_is_refused(env, recorder, facts)
    await _exit_is_refused(env, recorder, facts)
    await _reconcile_resolves(env, recorder, facts, first)
    await cancel_resting_entry(env, recorder, first)
    await _confirm_is_refused(env, recorder, facts)
    await _exit_is_accepted(env, recorder, facts)
    outcome = await _entry_is_allowed(env, recorder, facts)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = outcome
    return outcome


async def _make_the_entry_unknown(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]
) -> Any:
    # The POST reaches the exchange and its answer is lost; the process's own probe then fails, and
    # keeps failing (the resolver of the reconcile tick probes through the same edge) until cleared.
    env.faults.drop_response_after_send(ENTRY_METHOD, lost_answer(), times=1)
    env.faults.raise_before_send(PROBE_METHOD, lost_answer(), times=None)
    first = await card_and_approve(env, recorder)
    await env.owner.act("confirm", short_id=first.short_id, note="")

    async def unknown() -> bool:
        return (
            await intent_status(env, first.entry_client_id) == ExecutionIntentStatus.UNKNOWN.value
        )

    if not await dr._wait_until(env, unknown):
        status = await intent_status(env, first.entry_client_id)
        raise dr._smoke_fail(
            env, recorder, STEP_UNKNOWN, f"the entry intent is {status}, expected UNKNOWN"
        )
    posts = env.faults.calls_to(ENTRY_METHOD)
    probes = probe_calls(env)
    first_probe = probes[0] if probes else None
    facts["dropped_posts"] = len([c for c in posts if c["injected"] is True])
    facts["first_probe_injected"] = bool(first_probe and first_probe["injected"] is True)
    if (
        len(posts) != 1
        or facts["dropped_posts"] != 1
        or first_probe is None
        or first_probe["injected"] is not True
        or first_probe["kwargs"].get("orig_client_order_id") != first.entry_client_id
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_INJECT,
            f"{len(posts)} place_entry call(s) and {len(probes)} probe call(s) at the edge; "
            "expected one dropped POST and a failed probe by the entry's client id",
        )
    record_inject(
        env,
        recorder,
        "the entry POST reached the exchange and its answer was dropped; the probe by client id "
        "fails until cleared",
    )
    reasons = await _enter_reasons(env)
    standing = getattr(env.wiring.safe_mode, "entered_reason", None)
    facts.update(
        {
            "intent_after_lost_answer": "UNKNOWN",
            "safe_mode_reason_at_entry": standing,
            "safe_mode_enter_reasons": reasons,
            "place_entry_calls_while_unknown": place_entry_calls(env),
        }
    )
    if not env.wiring.safe_mode.in_safe_mode or UNKNOWN_REASON not in reasons:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_UNKNOWN,
            f"in SAFE_MODE {env.wiring.safe_mode.in_safe_mode}, journaled reasons {reasons}",
        )
    record_reaction(
        env,
        recorder,
        STEP_UNKNOWN,
        f"the entry intent is UNKNOWN and SAFE_MODE {UNKNOWN_REASON} is on (D080); nothing is "
        "re-sent",
    )
    return first


async def _monitoring_continues(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]
) -> None:
    ticks_before = len(await journal_rows(env, _RECONCILE_CORRELATION, "RECONCILE_TICK"))
    health_before = len(await journal_rows(env, _HEALTH_CORRELATION, "HEALTH_VERDICT"))
    failed_probes_before = len([c for c in probe_calls(env) if c["injected"] is True])
    for _ in range(_MONITORED_TICKS):
        # A verdict row's id hashes its time, so the clock must move between two health ticks.
        await env.tick()
        await health_verdict(env, recorder)

    async def monitored() -> bool:
        ticks = len(await journal_rows(env, _RECONCILE_CORRELATION, "RECONCILE_TICK"))
        return ticks >= ticks_before + _MONITORED_TICKS

    if not await dr._wait_until(env, monitored):
        raise dr._smoke_fail(
            env, recorder, STEP_MONITORING, "the reconcile tick journaled no new row in SAFE_MODE"
        )
    ticks_after = len(await journal_rows(env, _RECONCILE_CORRELATION, "RECONCILE_TICK"))
    health_after = len(await journal_rows(env, _HEALTH_CORRELATION, "HEALTH_VERDICT"))
    failed_probes = [c for c in probe_calls(env) if c["injected"] is True]
    facts["monitoring"] = {
        "in_safe_mode_throughout": bool(env.wiring.safe_mode.in_safe_mode),
        "reconcile_ticks_journaled": ticks_after - ticks_before,
        "health_verdicts_journaled": health_after - health_before,
        "probes_failed_after_the_first": len(failed_probes) - 1,
        "failed_probes_before": failed_probes_before,
    }
    if (
        not facts["monitoring"]["in_safe_mode_throughout"]
        or facts["monitoring"]["health_verdicts_journaled"] < _MONITORED_TICKS
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_MONITORING,
            f"monitoring facts {json.dumps(facts['monitoring'])}",
        )
    record_reaction(
        env,
        recorder,
        STEP_MONITORING,
        f"in SAFE_MODE the reconcile journaled {facts['monitoring']['reconcile_ticks_journaled']} "
        f"tick(s) and the health task {facts['monitoring']['health_verdicts_journaled']} "
        "verdict(s); the resolver's probes keep failing",
    )


async def _second_request_is_refused(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]
) -> None:
    request = await dr._inject(env, recorder, SCENARIO_FAR, "second_signal")
    correlation = f"demo-request:{request.signal_id}"

    async def refused() -> bool:
        return bool(await journal_rows(env, correlation, EVENT_REQUEST_REFUSED))

    if not await dr._wait_until(env, refused):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_SECOND_REQUEST,
            "the second request was not refused: a card may be open for BTCUSDT while an entry is "
            "unresolved",
        )
    (row, *_rest) = await journal_rows(env, correlation, EVENT_REQUEST_REFUSED)
    payload = json.loads(row.payload_json)
    facts["second_request"] = {
        "refused": True,
        "reason": payload.get("reason"),
        "sources": list(payload.get("sources", [])),
    }
    record_reaction(
        env,
        recorder,
        STEP_SECOND_REQUEST,
        f"a second request got no card: refused {payload.get('reason')} by the sender's symbol "
        f"rule (sources {', '.join(facts['second_request']['sources'])})",
    )


async def _exit_is_refused(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    before = len(await journal_rows(env, _SAFE_MODE_CORRELATION, "SAFE_MODE_EXIT_REFUSED"))
    await env.owner.act("safemode_exit")
    rows = await journal_rows(env, _SAFE_MODE_CORRELATION, "SAFE_MODE_EXIT_REFUSED")
    refusals: list[str] = []
    if rows:
        refusals = [str(r) for r in json.loads(rows[-1].payload_json).get("refusals", [])]
    facts["exit_refused"] = {
        "still_in_safe_mode": bool(env.wiring.safe_mode.in_safe_mode),
        "refusals": refusals,
        "refused_rows_added": len(rows) - before,
    }
    if (
        not facts["exit_refused"]["still_in_safe_mode"]
        or len(rows) <= before
        or UNKNOWN_INTENT_REFUSAL not in refusals
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_EXIT_REFUSED,
            f"exit facts {json.dumps(facts['exit_refused'])}; expected a refusal naming "
            f"{UNKNOWN_INTENT_REFUSAL}",
        )
    record_reaction(
        env,
        recorder,
        STEP_EXIT_REFUSED,
        f"/safemode_exit with /confirm was refused ({', '.join(refusals)}) and journaled; "
        "SAFE_MODE stays on",
    )


async def _reconcile_resolves(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], first: Any
) -> None:
    probes_before = len(probe_calls(env))
    env.faults.clear(PROBE_METHOD)  # the probe works again
    await env.pause(probe_interval_seconds(env) + 1)  # the resolver probes at its own spacing

    async def acked() -> bool:
        return await intent_status(env, first.entry_client_id) == ExecutionIntentStatus.ACKED.value

    if not await dr._wait_until(env, acked):
        status = await intent_status(env, first.entry_client_id)
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_RECONCILED,
            f"after the probe worked again the entry intent is {status}, expected ACKED",
        )
    after = probe_calls(env)[probes_before:]
    facts["reconciled"] = {
        "intent_after": "ACKED",
        "unknown_probe_calls_after_clear": len(after),
        "last_probe_injected": bool(after[-1]["injected"]) if after else None,
        "in_safe_mode_after_resolution": bool(env.wiring.safe_mode.in_safe_mode),
        "standing_reason_after_resolution": getattr(env.wiring.safe_mode, "entered_reason", None),
    }
    await dr._record_order_ids(env, recorder, STEP_RECONCILED, first)
    if not facts["reconciled"]["in_safe_mode_after_resolution"] or not after:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_RECONCILED,
            f"reconcile facts {json.dumps(facts['reconciled'])}; closing an intent must not exit "
            "SAFE_MODE (D-15)",
        )
    record_reaction(
        env,
        recorder,
        STEP_RECONCILED,
        "the reconcile resolver probed again by the client id, found the order and recorded the "
        "intent ACKED; SAFE_MODE stays on (only the operator leaves it)",
    )


async def _confirm_is_refused(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    sent_before = place_entry_calls(env)
    request = await card_and_approve(env, recorder)
    await env.owner.act("confirm", short_id=request.short_id, note="")
    decisions = await _await_decision(env, recorder, request, STEP_CONFIRM_REFUSED)
    facts["confirm_in_safe_mode"] = {
        "decisions": decisions,
        "place_entry_calls_before": sent_before,
        "place_entry_calls_after": place_entry_calls(env),
    }
    if (
        not env.wiring.safe_mode.in_safe_mode
        or not all(d["refused"] for d in decisions)
        or place_entry_calls(env) != sent_before
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_CONFIRM_REFUSED,
            f"decisions {decisions}, place_entry {place_entry_calls(env)} (was {sent_before})",
        )
    record_reaction(
        env,
        recorder,
        STEP_CONFIRM_REFUSED,
        f"with SAFE_MODE on, the CONFIRM was refused ({decisions[-1]['reason']}) and no entry was "
        "sent",
    )
    await expire_plan(env, request)


async def _exit_is_accepted(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    before = len(await journal_rows(env, _SAFE_MODE_CORRELATION, "SAFE_MODE_EXIT"))
    await leave_safe_mode(env, recorder, STEP_EXIT)
    rows = await journal_rows(env, _SAFE_MODE_CORRELATION, "SAFE_MODE_EXIT")
    operator = str(json.loads(rows[-1].payload_json).get("operator_id", "")) if rows else ""
    facts["exit"] = {
        "in_safe_mode_after": bool(env.wiring.safe_mode.in_safe_mode),
        "exit_rows": len(rows) - before,
        "exit_operator_recorded": bool(operator),
    }
    if facts["exit"]["exit_rows"] != 1 or not facts["exit"]["exit_operator_recorded"]:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_EXIT,
            f"exit rows {json.dumps(facts['exit'])}; expected one with an operator",
        )


async def _entry_is_allowed(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> str:
    """A new request after the exit: placed (PASSED) or refused (NOT_REHEARSED, never assumed)."""
    sent_before = place_entry_calls(env)
    request = await card_and_approve(env, recorder)
    await env.owner.act("confirm", short_id=request.short_id, note="")

    async def acked() -> bool:
        status = await intent_status(env, request.entry_client_id)
        return status == ExecutionIntentStatus.ACKED.value

    placed = await dr._wait_until(env, acked)
    decisions = await placement_decision(env, request)
    facts["entry_after_exit"] = {
        "placed": placed,
        "decisions": decisions,
        "place_entry_calls": place_entry_calls(env) - sent_before,
    }
    if not placed:
        if place_entry_calls(env) != sent_before:
            raise dr._smoke_fail(
                env, recorder, STEP_ENTRY_ALLOWED, "an unacknowledged request still sent an entry"
            )
        reason = decisions[-1]["reason"] if decisions else None
        _record_gap_with_env_label(
            env,
            recorder,
            STEP_ENTRY_ALLOWED,
            f"after SAFE_MODE was left the request was refused ({reason}) instead of placed",
        )
        await expire_plan(env, request)
        return dr.OUTCOME_COMPLETE_WITH_GAPS
    record_reaction(
        env, recorder, STEP_ENTRY_ALLOWED, "after the operator exit a new request is placed again"
    )
    await cancel_resting_entry(env, recorder, request)
    return dr.OUTCOME_COMPLETE
