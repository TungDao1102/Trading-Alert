"""S17 stale feed drill (G2-016, D058): a stale mark fails closed and the reaction is journaled.

TEST_ONLY. OPS-01, D-06. A mark reading older than the configured mark-price age is injected at the
two readers the live process uses (D-08, the trigger only; the reaction is the production code's):

* the PUBLIC reader (`FaultEdge.stale_mark`): its readings feed the health check
  `market_feed_freshness` and the reconcile loop's feed check;
* the signed adapter's `get_mark_price` (`FaultEdge.override`): the pre-placement mark gate reads
  that one (the price check of the CONFIRM), not the public reader.

Two phases, because the two checks need different states:

A. Before any plan is active: the health check FAILs and the CONFIRM is refused at the
   pre-placement mark gate (fail closed, nothing sent). The reconcile feed check judges only the
   symbols of active plans, so no SAFE_MODE yet.
B. With a resting entry (an active plan): a stale public reading makes the next reconcile tick enter
   SAFE_MODE STALE_FEED and journal a STALE_DATA alert for the symbol. A fresh reading never leaves
   SAFE_MODE by itself (D-15); the operator exit (`/safemode_exit`, RUNBOOK 21.1a) does, and entries
   are allowed again.

The stale age is derived from the loaded limits (twice the larger of the two configured ages),
never a literal. The injection steps are `label_for(env, injected=True)`; every other step carries
the env label.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from typing import Any

from scripts import demo_rehearsal as dr
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME

from tests.support.demo_scenarios.harness import ScenarioRecorder, account_clean, ensure_clean_start
from tests.support.demo_scenarios.s03_crossed_stop import placement_rows
from tests.support.demo_scenarios.s04_stop_rejected import record_injection_step, record_step
from tests.support.demo_scenarios.s06_replay import (
    cancel_resting_entry,
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)
from tests.support.demo_scenarios.s08_stream_loss import (
    card_and_approve,
    expire_plan,
    failing_checks,
    health_verdict,
    leave_safe_mode,
    ticks,
)

SCENARIO_FAR = "far"
FEED_CHECK = "market_feed_freshness"
SAFE_MODE_REASON = "STALE_FEED"
ALERT_EVENT = "STALE_DATA"
ALERT_REASON = "MARK_PRICE_STALE"
STEP_BASELINE = "feed_fresh_and_health_ok"
STEP_INJECT = "inject_stale_marks"
STEP_FEED_CHECK = "market_feed_check_fails"
STEP_REFUSED = "confirm_refused_on_a_stale_mark"
STEP_SAFE_MODE = "stale_feed_enters_safe_mode"
STEP_ALERT = "stale_data_alert_journaled"
STEP_FRESH = "fault_cleared_feed_fresh_safe_mode_stays"
STEP_EXIT = "safe_mode_left"
STEP_ENTRIES_ALLOWED = "entries_allowed_again"
_ALERT_CORRELATION = "operational_alerts"
_JOURNAL_CORRELATION_PREFIX = "live-placement"
_STALE_SETTLE_TICKS = 3


def stale_age(limits: Any) -> timedelta:
    """Twice the larger configured mark-price age (feed check and pre-placement), from `limits`.

    An unset bound is refused, never defaulted: a drill against an unknown bound proves nothing.
    """
    bounds = (
        ("stale_feed.max_mark_price_age_ms", limits.stale_feed_max_mark_price_age_ms),
        ("pre_placement.max_mark_price_age_ms", limits.max_mark_price_age_ms),
    )
    for key, value in bounds:
        if value is None:
            raise ValueError(f"{key} is not configured")
    return timedelta(milliseconds=2 * max(int(value) for _key, value in bounds))


def record_inject(env: Any, recorder: ScenarioRecorder, detail: str) -> None:
    """The injected trigger: DEMO_FAULT_INJECTED on Demo, never DEMO_OBSERVED."""
    record_injection_step(env, recorder, detail, name=STEP_INJECT)


def record_reaction(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A reaction of the real process: the env label."""
    record_step(env, recorder, name, detail)


def _stale_pre_placement_mark(env: Any, age: timedelta) -> Any:
    async def stale(**kwargs: Any) -> Any:
        reading = await env.faults.inner.get_mark_price(**kwargs)
        return dataclasses.replace(reading, exchange_time_utc=reading.exchange_time_utc - age)

    return stale


def stale_alerts(journal: Any) -> list[list[str]]:
    """`[event, reason]` of every STALE_DATA operational alert of the journal."""
    pairs: list[list[str]] = []
    for row in journal.list_by_correlation(_ALERT_CORRELATION):
        if row.event_type != "OPERATIONAL_ALERT":
            continue
        payload = json.loads(row.payload_json)
        if payload.get("event") == ALERT_EVENT:
            pairs.append([str(payload.get("event")), str(payload.get("reason"))])
    return pairs


def _refusal_reason(event_type: str, payload: dict[str, Any]) -> str | None:
    key = "reason_code" if event_type == EVENT_PLACEMENT_OUTCOME else "reason"
    value = payload.get(key)
    return value if isinstance(value, str) else None


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S17 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder)
    finally:
        env.faults.clear("get_mark_price")
        env.faults.public.clear_marks(dr.SYMBOL)
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    limits = env.assembly.config.limits
    age = stale_age(limits)
    facts: dict[str, Any] = recorder.details.setdefault("stale", {})
    facts["stale_age_ms"] = int(age / timedelta(milliseconds=1))
    facts["feed_bound_ms"] = int(limits.stale_feed_max_mark_price_age_ms)
    facts["pre_placement_bound_ms"] = int(limits.max_mark_price_age_ms)

    verdict = await health_verdict(env, recorder)
    if verdict is None or verdict.is_no_trade or FEED_CHECK in failing_checks(verdict):
        raise dr._smoke_fail(env, recorder, STEP_BASELINE, "the feed or the health was not fresh")
    record_reaction(env, recorder, STEP_BASELINE, "marks are fresh and the health verdict is OK")

    await _phase_a_refusal(env, recorder, age, facts)
    await _phase_b_safe_mode(env, recorder, age, facts)
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE


async def _phase_a_refusal(
    env: Any, recorder: ScenarioRecorder, age: timedelta, facts: dict[str, Any]
) -> None:
    wiring = env.wiring
    first = await card_and_approve(env, recorder)
    # Armed after the request was derived: the injector reads the real mark through these readers.
    env.faults.stale_mark(dr.SYMBOL, age, times=None)
    env.faults.override("get_mark_price", _stale_pre_placement_mark(env, age), times=None)
    record_inject(
        env,
        recorder,
        f"mark readings are served {facts['stale_age_ms']} ms old at the public reader and at "
        "the pre-placement reader; nothing is sent to the exchange for it",
    )
    try:
        await ticks(env, _STALE_SETTLE_TICKS)
        verdict = await health_verdict(env, recorder)
        facts["health_failing"] = failing_checks(verdict)
        if FEED_CHECK not in facts["health_failing"]:
            raise dr._smoke_fail(
                env,
                recorder,
                STEP_FEED_CHECK,
                f"{FEED_CHECK} did not FAIL (failing: {facts['health_failing']})",
            )
        record_reaction(
            env,
            recorder,
            STEP_FEED_CHECK,
            f"{FEED_CHECK} FAILs while the newest mark is older than {facts['feed_bound_ms']} ms",
        )
        await env.owner.act("confirm", short_id=first.short_id, note="")

        async def refused() -> bool:
            rows = await env.assembly.executor.read(
                placement_rows, wiring.stores.journal, wiring.stores.shadow, first.trade_plan_id
            )
            return bool(rows)

        if not await dr._wait_until(env, refused):
            raise dr._smoke_fail(env, recorder, STEP_REFUSED, "CONFIRM left no journaled outcome")
    finally:
        env.faults.clear("get_mark_price")
        env.faults.public.clear_marks(dr.SYMBOL)
    rows = await env.assembly.executor.read(
        placement_rows, wiring.stores.journal, wiring.stores.shadow, first.trade_plan_id
    )
    event_type, payload = rows[0]
    sent = place_entry_calls(env)
    facts["refusal_event"] = event_type
    facts["refusal_reason"] = _refusal_reason(event_type, payload)
    facts["place_entry_calls_at_refusal"] = sent
    if sent != 0 or not facts["refusal_reason"]:
        raise dr._smoke_fail(
            env, recorder, STEP_REFUSED, f"{sent} place_entry call(s), refusal {event_type}"
        )
    record_reaction(
        env,
        recorder,
        STEP_REFUSED,
        f"the CONFIRM was refused ({event_type}: {facts['refusal_reason']}), nothing was sent",
    )
    await expire_plan(env, first)
    await ticks(env, _STALE_SETTLE_TICKS)


async def _phase_b_safe_mode(
    env: Any, recorder: ScenarioRecorder, age: timedelta, facts: dict[str, Any]
) -> None:
    wiring = env.wiring
    second = await place_approved_entry(env, recorder, SCENARIO_FAR)
    env.faults.stale_mark(dr.SYMBOL, age, times=None)
    try:

        async def in_safe_mode() -> bool:
            return bool(wiring.safe_mode.in_safe_mode)

        if not await dr._wait_until(env, in_safe_mode):
            raise dr._smoke_fail(
                env,
                recorder,
                STEP_SAFE_MODE,
                "a stale feed with an active plan did not enter SAFE_MODE",
            )
        reason = getattr(wiring.safe_mode, "entered_reason", None)
        facts["safe_mode_reason"] = reason
        if reason != SAFE_MODE_REASON:
            raise dr._smoke_fail(
                env,
                recorder,
                STEP_SAFE_MODE,
                f"SAFE_MODE reason {reason}, expected {SAFE_MODE_REASON}",
            )
        record_reaction(
            env,
            recorder,
            STEP_SAFE_MODE,
            f"with a resting entry the stale feed entered SAFE_MODE {reason}",
        )
        facts["alerts"] = stale_alerts(wiring.stores.journal)
        if [ALERT_EVENT, ALERT_REASON] not in facts["alerts"]:
            raise dr._smoke_fail(
                env, recorder, STEP_ALERT, f"STALE_DATA alerts journaled: {facts['alerts']}"
            )
        record_reaction(
            env,
            recorder,
            STEP_ALERT,
            f"an OPERATIONAL_ALERT {ALERT_EVENT} ({ALERT_REASON}) names the stale symbol",
        )
    finally:
        env.faults.public.clear_marks(dr.SYMBOL)

    # ---- the fault is cleared: a fresh reading never leaves SAFE_MODE by itself --------------- #
    await ticks(env, _STALE_SETTLE_TICKS)
    verdict = await health_verdict(env, recorder)
    facts["health_failing_after_fresh"] = failing_checks(verdict)
    facts["safe_mode_after_fresh"] = bool(wiring.safe_mode.in_safe_mode)
    if facts["health_failing_after_fresh"] or not facts["safe_mode_after_fresh"]:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_FRESH,
            f"failing {facts['health_failing_after_fresh']}, "
            f"SAFE_MODE {facts['safe_mode_after_fresh']}",
        )
    record_reaction(
        env,
        recorder,
        STEP_FRESH,
        "after the fault the feed check passes again; SAFE_MODE stays on until the operator exit",
    )
    await leave_safe_mode(env, recorder, STEP_EXIT)
    verdict = await health_verdict(env, recorder)
    if verdict.is_no_trade or wiring.coordinator.blocks_new_entries():
        raise dr._smoke_fail(
            env, recorder, STEP_ENTRIES_ALLOWED, "entries are still blocked after the exit"
        )
    record_reaction(
        env,
        recorder,
        STEP_ENTRIES_ALLOWED,
        "after the documented exit the health verdict is OK and entries are not blocked",
    )
    await cancel_resting_entry(env, recorder, second)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
