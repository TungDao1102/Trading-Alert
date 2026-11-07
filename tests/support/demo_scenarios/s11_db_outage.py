"""S11 DB outage during a risk-reducing close (plan 25-14; OPS-01, R-24, D034, D016).

TEST_ONLY. A database failure never blocks a risk-reducing action: the control acts first and
journals afterwards (`src/ops/risk_first.py`), the record the journal refuses waits in the local
spill, and SAFE_MODE DB_FAILURE blocks new entries. The scenario shows it on the real process:

1. S04's trigger: the first stop placement after the fill is rejected at the adapter edge (code
   -2021, nothing is sent for it) and, at that same instant, the journal store is made unavailable
   (`StoreFaults.fail_store("journal", "record", times=None)`, a test-only proxy; the database
   itself is not stopped). Both are armed in ONE override of the stop placement, so the outage
   starts exactly when the risk-reducing action does, on the fake and on Demo alike (a Demo entry
   fills at once, so arming after the entry would race the first protection pass).
2. The reaction is the production code's: one reduce-only MARKET close under the derived `xc-` id,
   the position flat, the stop never resent, the audit rows the journal refused (`EMERGENCY_CLOSE`
   pre-send, `PROTECTIVE_CANCEL`, `OPERATIONAL_ALERT`, `SAFE_MODE_*`) in the local spill, and
   SAFE_MODE with a DB_FAILURE entry.
3. The database is back (the fault is cleared). A new request is refused (SAFE_MODE), the operator
   leaves SAFE_MODE through `/safemode_exit` (RUNBOOK 21.1a) and a new request should be placed
   again. It is NOT (finding F1, below): the step `entry_allowed_after_the_exit` is recorded as it
   was observed, never assumed.
4. The next start replays the spill into the journal (RUNBOOK 21.2): every spilled row is replayed
   once, nothing failed or conflicted, the spill is empty and each row is in the journal.

Finding F1 (recorded, not fixed here): the coordinator does not spill its own PROTECTION_TRANSITION
rows when the journal is down (RUNBOOK 21.2, 20-DEFERRED), and nothing journals them again. The plan
that ended during the outage therefore has no FLAT row in the journal, and the journal is the source
of the reservation sweep: (a) the position's risk reservation stays RESERVED in the running process,
so after the database is back and SAFE_MODE is left the next request on the cluster is refused
CLUSTER_CAP_REJECT; (b) the restart rebuilds the plan as live, the reconcile enters SAFE_MODE and
entries stay disabled in that process (ENABLE runs only at start). The scenario records (a) as the
step `entry_allowed_after_the_exit` and (b) as `restart_after_the_outage_is_clean` (both
NOT_REHEARSED, labelled as observed), leaves SAFE_MODE with the operator exit so the account and the
durable SAFE_MODE state end clean, and ends COMPLETE_WITH_GAPS.

The real PostgreSQL outage (`docker compose stop postgres`) is not part of this scenario.

Labels: the injection step is `label_for(env, injected=True)`; the close and every other reaction
carry the env label (a real Demo order is DEMO_OBSERVED). On the fake every step is SYNTHETIC.
"""

from __future__ import annotations

import json
from typing import Any

from scripts import demo_rehearsal as dr
from src.domain.enums import ExecutionIntentStatus
from src.execution.order_ids import derive_close_order_id

from tests.support.demo_scenarios.harness import (
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
    label_for,
)
from tests.support.demo_scenarios.s04_stop_rejected import (
    SCENARIO_FILL,
    STOP_METHOD,
    close_placements,
    drive_fill,
    injected_rejection,
    record_injection_step,
    record_step,
    stop_placements,
    wait_flat,
)
from tests.support.demo_scenarios.s06_replay import (
    cancel_resting_entry,
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)
from tests.support.demo_scenarios.s07_restart_cuts import start_tolerant
from tests.support.demo_scenarios.s08_stream_loss import (
    card_and_approve,
    expire_plan,
    leave_safe_mode,
    placement_decision,
    ticks,
)

SCENARIO_FAR = "far"
STORE = "journal"
STORE_METHOD = "record"
DB_FAILURE = "DB_FAILURE"
STEP_BASELINE = "spill_baseline"
STEP_INJECT = "inject_stop_rejection_and_journal_outage"
STEP_CLOSE = "reduce_only_close_sent_during_the_outage"
STEP_SPILLED = "audit_rows_in_the_local_spill"
STEP_SAFE_MODE = "safe_mode_db_failure_entered"
STEP_ENTRY_REFUSED = "entry_refused_in_safe_mode"
STEP_EXIT = "safe_mode_left"
STEP_ENTRY_ALLOWED = "entry_allowed_after_the_exit"
STEP_REPLAYED = "spill_replayed_at_the_next_start"
STEP_RESTART_CLEAN = "restart_after_the_outage_is_clean"
STEP_SECOND_EXIT = "safe_mode_left_after_the_restart"

_SAFE_MODE_EVENTS = ("SAFE_MODE_ENTER", "SAFE_MODE_REENTER")


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


def spill_events(env: Any) -> dict[str, Any]:
    """`journal_event_id -> JournalEvent` of every record the local spill holds (a disk read)."""
    return {record.event.journal_event_id: record.event for record in env.wiring.spill.pending()}


def _present(journal: Any, ids: list[str]) -> bool:
    return all(journal.get(event_id) is not None for event_id in ids)


def _outage_with_rejection(env: Any) -> Any:
    """The stop placement stand-in: the journal goes down, then the stop is rejected (-2021).

    Nothing is sent: the inner adapter is never called. Armed once; the first stop placement after
    the fill consumes it, so the outage begins exactly when the risk-reducing action does.
    """

    async def reject(**_kwargs: Any) -> Any:
        env.store_faults.fail_store(STORE, STORE_METHOD, times=None)
        raise injected_rejection()

    return reject


def _journal_write_failures(env: Any) -> int:
    key = f"{STORE}.{STORE_METHOD}"
    return len([i for i in env.store_faults.injections if i.method == key])


async def _await_decision(env: Any, recorder: ScenarioRecorder, request: Any) -> list[Any]:
    async def decided() -> bool:
        return bool(await placement_decision(env, request))

    if not await dr._wait_until(env, decided):
        raise dr._smoke_fail(
            env, recorder, STEP_ENTRY_REFUSED, "the CONFIRM left no journaled decision"
        )
    decisions: list[Any] = await placement_decision(env, request)
    return decisions


# ---- the scenario ------------------------------------------------------------------------------ #


class _Processes:
    """The process that runs now (a restart replaces it) and whether it was stopped already."""

    def __init__(self, env: Any) -> None:
        self.env = env
        self.stopped = False

    async def stop(self) -> None:
        await shutdown(self.env)
        self.stopped = True

    async def shutdown(self) -> None:
        if not self.stopped:
            await self.stop()


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S11 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    processes = _Processes(env)
    try:
        return await _sequence(env, recorder, processes)
    finally:
        env.store_faults.clear()  # the database is back whatever happened
        env.faults.clear(STOP_METHOD)
        await processes.shutdown()


async def _sequence(env: Any, recorder: ScenarioRecorder, processes: _Processes) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    facts: dict[str, Any] = recorder.details.setdefault("db_outage", {})
    baseline = set(spill_events(env))
    facts["spill_baseline_count"] = len(baseline)
    record_reaction(
        env, recorder, STEP_BASELINE, f"the local spill holds {len(baseline)} record(s) before"
    )

    env.faults.override(STOP_METHOD, _outage_with_rejection(env), times=1)
    first = await place_approved_entry(env, recorder, SCENARIO_FILL)
    await drive_fill(env, first)
    await wait_flat(env, recorder, first, STEP_CLOSE)

    await _check_close(env, recorder, facts, first)
    spilled_ids = await _check_spill_and_safe_mode(env, recorder, facts, baseline)

    env.store_faults.clear()  # the database is back; SAFE_MODE stays until the operator exits
    await expire_plan(env, first)
    await _check_entry_refused(env, recorder, facts)
    await leave_safe_mode(env, recorder, STEP_EXIT)
    await _check_entry_allowed(env, recorder, facts)

    await processes.stop()
    return await _restart_and_replay(env, recorder, facts, processes, spilled_ids)


async def _check_close(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], first: Any
) -> None:
    plan_hash = first.plan_hash
    stops = stop_placements(env, plan_hash)
    injected = [c for c in stops if c.get("injected") is True]
    facts["stop_placements"] = len(stops)
    facts["stop_injected"] = len(injected)
    if len(stops) != 1 or len(injected) != 1:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_INJECT,
            f"{len(stops)} stop placement(s), {len(injected)} injected; expected one of each",
        )
    record_inject(
        env,
        recorder,
        "the first stop placement was rejected at the adapter edge and, at the same instant, the "
        "journal store raised StoreUnavailable until cleared; nothing was sent for the stop",
    )
    closes = close_placements(env)
    expected_id = derive_close_order_id(plan_hash=plan_hash, attempt_no=1)
    facts["close_calls"] = len(closes)
    facts["close_client_id"] = expected_id
    if len(closes) != 1 or closes[0]["kwargs"].get("new_client_order_id") != expected_id:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_CLOSE,
            f"{len(closes)} close call(s), expected one under {expected_id}",
        )
    adapter = env.assembly.exchange.adapter
    positions = [
        p for p in await adapter.snapshot_positions(symbol=dr.SYMBOL) if p.position_amt != 0
    ]
    facts["position_flat"] = not positions
    if positions or not str(expected_id).startswith("xc-"):
        raise dr._smoke_fail(env, recorder, STEP_CLOSE, "a position is still open after the close")
    recorder.record_ids(
        STEP_CLOSE, order_ids=[], client_order_ids=[expected_id], algo_client_ids=[]
    )
    record_reaction(
        env,
        recorder,
        STEP_CLOSE,
        "one reduce-only MARKET close under the derived xc- id went out while the journal was "
        "down and the position is flat; the stop was never resent",
    )


async def _check_spill_and_safe_mode(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], baseline: set[str]
) -> list[str]:
    wiring = env.wiring
    events = spill_events(env)
    new = {event_id: event for event_id, event in events.items() if event_id not in baseline}
    facts["journal_write_failures"] = _journal_write_failures(env)
    facts["spilled_count"] = len(new)
    facts["spilled_event_types"] = sorted({event.event_type for event in new.values()})
    phases = sorted(
        {
            str(json.loads(event.payload_json).get("phase"))
            for event in new.values()
            if event.event_type == "EMERGENCY_CLOSE"
        }
    )
    reasons = sorted(
        {
            str(json.loads(event.payload_json).get("reason"))
            for event in new.values()
            if event.event_type in _SAFE_MODE_EVENTS
        }
    )
    facts["emergency_close_phases_spilled"] = phases
    facts["safe_mode_reasons_spilled"] = reasons
    facts["in_safe_mode_after_the_close"] = bool(wiring.safe_mode.in_safe_mode)
    facts["safe_mode_standing_reason"] = getattr(wiring.safe_mode, "entered_reason", None)
    if (
        facts["journal_write_failures"] < 1
        or not new
        or "EMERGENCY_CLOSE" not in facts["spilled_event_types"]
        or "pre_send" not in phases
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_SPILLED,
            f"{facts['journal_write_failures']} journal write failure(s), {len(new)} new spill "
            f"record(s) of types {facts['spilled_event_types']}, close phases {phases}",
        )
    record_reaction(
        env,
        recorder,
        STEP_SPILLED,
        f"{len(new)} audit row(s) the journal refused are in the local spill "
        f"({', '.join(facts['spilled_event_types'])}); the close's pre-send record among them",
    )
    if not facts["in_safe_mode_after_the_close"] or DB_FAILURE not in reasons:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_SAFE_MODE,
            f"in SAFE_MODE {facts['in_safe_mode_after_the_close']}, spilled reasons {reasons}",
        )
    record_reaction(
        env,
        recorder,
        STEP_SAFE_MODE,
        f"SAFE_MODE was entered with a {DB_FAILURE} row (standing reason "
        f"{facts['safe_mode_standing_reason']}) and new entries are blocked",
    )
    return sorted(new)


async def _check_entry_refused(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    sent_before = place_entry_calls(env)
    request = await card_and_approve(env, recorder)
    await env.owner.act("confirm", short_id=request.short_id, note="")
    decisions = await _await_decision(env, recorder, request)
    facts["entry_decisions"] = decisions
    facts["entry_refusal_reason"] = decisions[-1]["reason"]
    facts["place_entry_calls_at_refusal"] = place_entry_calls(env)
    if not all(d["refused"] for d in decisions) or place_entry_calls(env) != sent_before:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_ENTRY_REFUSED,
            f"decisions {decisions}, place_entry {place_entry_calls(env)} (was {sent_before})",
        )
    record_reaction(
        env,
        recorder,
        STEP_ENTRY_REFUSED,
        f"with SAFE_MODE on, the CONFIRM was refused ({facts['entry_refusal_reason']}) and no "
        "entry was sent",
    )
    await expire_plan(env, request)


async def _counted_reservations(env: Any) -> list[str] | None:
    """The status of every counted risk reservation (what the caps read), or None if unreadable."""
    try:
        rows = await env.assembly.executor.read(
            lambda store: store.list_counted(), env.wiring.stores.reservations
        )
    except Exception:  # noqa: BLE001 - an observation only, never a precondition
        return None
    return [str(row.status.value) for row in rows]


async def _check_entry_allowed(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    """A new request after the exit: placed (PASSED) or refused (NOT_REHEARSED, finding F1 a)."""
    sent_before = place_entry_calls(env)
    # The sweep releases the reservation of the refused (expired) request first; what remains
    # counted before the new request is the closed plan's own row.
    await ticks(env, 3)
    facts["counted_reservations_after_the_exit"] = await _counted_reservations(env)
    request = await card_and_approve(env, recorder)
    await env.owner.act("confirm", short_id=request.short_id, note="")
    decisions = await _await_decision(env, recorder, request)
    placed = not any(d["refused"] for d in decisions)
    facts["entry_after_exit_placed"] = placed
    facts["entry_after_exit_decisions"] = decisions
    facts["entry_after_exit_refusal_reason"] = None if placed else decisions[-1]["reason"]
    if not placed:
        if place_entry_calls(env) != sent_before:
            raise dr._smoke_fail(
                env, recorder, STEP_ENTRY_ALLOWED, "a refused request still sent an entry"
            )
        _record_gap_with_env_label(
            env,
            recorder,
            STEP_ENTRY_ALLOWED,
            f"after the DB returned and SAFE_MODE was left the request was refused "
            f"({facts['entry_after_exit_refusal_reason']}); the closed plan's reservation is still "
            f"counted {facts['counted_reservations_after_the_exit']} (finding F1 a)",
        )
        await expire_plan(env, request)
        return

    async def acked() -> bool:
        row = await dr._smoke_read(
            env, env.wiring.stores.execution_state.intent_for_client_id, request.entry_client_id
        )
        return row is not None and row.intent_status is ExecutionIntentStatus.ACKED

    if not await dr._wait_until(env, acked):
        raise dr._smoke_fail(env, recorder, STEP_ENTRY_ALLOWED, "the entry was not acknowledged")
    facts["place_entry_calls_after_the_exit"] = place_entry_calls(env) - sent_before
    record_reaction(
        env, recorder, STEP_ENTRY_ALLOWED, "after the operator exit a new request is placed again"
    )
    await cancel_resting_entry(env, recorder, request)


async def _restart_and_replay(
    env: Any,
    recorder: ScenarioRecorder,
    facts: dict[str, Any],
    processes: _Processes,
    spilled_ids: list[str],
) -> str:
    if env.restart is None:
        raise dr._smoke_fail(env, recorder, STEP_REPLAYED, "no restart is available")
    second = await env.restart()
    processes.env = second
    processes.stopped = False
    outcome = await start_tolerant(second, recorder, "restart")
    report = getattr(outcome.recovery, "spill_replay", None)
    replayed = [] if report is None else list(report.replayed)
    failed = [] if report is None else [list(item) for item in report.failed]
    conflicts = [] if report is None else list(report.conflicts)
    corrupt = [] if report is None else [list(item) for item in report.corrupt]
    pending_after = len(spill_events(second))
    in_journal = await second.assembly.executor.read(
        _present, second.wiring.stores.journal, replayed
    )
    facts["replay"] = {
        "replayed": len(replayed),
        "replayed_ids": replayed,
        "already_present": 0 if report is None else len(report.already_present),
        "failed": failed,
        "conflicts": conflicts,
        "corrupt": corrupt,
        "spill_pending_after": pending_after,
        "all_in_the_journal_once": bool(in_journal) and len(set(replayed)) == len(replayed),
        "covers_the_outage_rows": set(spilled_ids) <= set(replayed),
    }
    if (
        report is None
        or failed
        or conflicts
        or corrupt
        or pending_after != 0
        or not facts["replay"]["all_in_the_journal_once"]
        or not facts["replay"]["covers_the_outage_rows"]
    ):
        raise dr._smoke_fail(
            env, recorder, STEP_REPLAYED, f"spill replay: {json.dumps(facts['replay'])[:300]}"
        )
    record_reaction(
        env,
        recorder,
        STEP_REPLAYED,
        f"the next start replayed {len(replayed)} spilled row(s) into the journal, each once; the "
        "spill is empty",
    )
    facts["spilled_count_at_replay"] = len(spilled_ids)

    restart = {
        "admitted": bool(outcome.admitted),
        "in_safe_mode": bool(outcome.in_safe_mode),
        "enabled": bool(outcome.enabled),
        "start_safe_mode_reasons": list(outcome.safe_mode_reasons),
        "plans_restored": None if outcome.recovery is None else outcome.recovery.plans_restored,
    }
    facts["restart"] = restart
    gaps = dr.OUTCOME_COMPLETE_WITH_GAPS
    clean = restart["admitted"] and not restart["in_safe_mode"] and restart["enabled"]
    if clean:
        record_reaction(
            env, recorder, STEP_RESTART_CLEAN, "the start after the outage is clean and enabled"
        )
        outcome_name = dr.OUTCOME_COMPLETE if facts["entry_after_exit_placed"] else gaps
    else:
        await ticks(second, 3)
        restart["standing_reason"] = getattr(second.wiring.safe_mode, "entered_reason", None)
        _record_gap_with_env_label(
            env,
            recorder,
            STEP_RESTART_CLEAN,
            "the start after the outage is in SAFE_MODE with entries not enabled: the plan that "
            "ended during the outage has no PROTECTION_TRANSITION end row (finding F1)",
        )
        await leave_safe_mode(second, recorder, STEP_SECOND_EXIT)
        outcome_name = dr.OUTCOME_COMPLETE_WITH_GAPS
    await ticks(second, 2)
    facts["counted_reservations_after_the_restart"] = await _counted_reservations(second)
    if not await account_clean(second, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = outcome_name
    return outcome_name
