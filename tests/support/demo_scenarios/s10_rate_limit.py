"""S10 rate limit and 418, injected only (plan 25-14; OPS-01, D-07, D083).

TEST_ONLY. The owner decided on 2026-10-22 that a real 429 or 418 is never provoked (25-RESEARCH
Pitfall 7): an IP ban would also block the address the API key is restricted to. The answer is
INJECTED under the REAL adapter (`SdkFaults`, D-08): the armed SDK method raises BEFORE anything is
sent, the adapter classifies it and the one process-wide REST gate records it exactly as it would a
real answer. The reaction is the production code's:

* the gate records the pause (429) or the ban (418) and persists the deadline to its state file;
* the CONFIRM that follows is refused with nothing sent (its equity refresh is the signed read the
  gate refuses), a replayed CONFIRM places nothing, and the SDK is reached exactly once (the
  injected call): nothing is re-sent while the gate is restricted;
* the reconcile loop journals `RECONCILE_SKIPPED_GATE` instead of reading the account;
* when the Retry-After has passed entries are allowed again.

Variants: `"429"` (default, Demo and twin) pauses the gate for a short Retry-After that is derived
from the loaded limits (never longer than a fallback wait, so the test shows that the header wins).
`"418"` is twin only: a ban with no Retry-After takes the ratified fallback wait
(`signed_calls.rate_limit_418_no_retry_after_wait_seconds`), journals the `REST_GATE_BAN_ENTERED`
alert with the gate's own deadline, and survives a restart (the restored gate still refuses and no
entry is enabled). The Demo 418 variant is S19, which clears its false ban at once.

Twin limit (stated, not hidden): on the composed rig the order calls (`place_entry` and friends) are
served by the Binance-semantics fake, so the real adapter's own gate check on a placement is not on
the twin's path (it is covered by `tests/test_binance_ratelimit_gate.py`). The signed read that
carries the gate on the twin is the equity refresh the CONFIRM makes through the real adapter and
the real SDK stand-in. What is asserted is therefore: no `place_entry` reached the edge, no second
SDK call, a refused placement decision, the reconcile skip.

Labels: the injection step is `label_for(env, injected=True)` (DEMO_FAULT_INJECTED on Demo); every
reaction carries the env label (SYNTHETIC on the fake). A step the env could not produce is
NOT_OBSERVED, never DEMO_OBSERVED.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios.harness import ScenarioRecorder, account_clean, ensure_clean_start
from tests.support.demo_scenarios.s04_stop_rejected import record_injection_step, record_step
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
    placement_decision,
    record_gap,
    ticks,
)
from tests.support.fault_edge import rate_limit_ban_error, too_many_requests_error

VARIANT_429 = "429"
VARIANT_418 = "418"
VARIANTS = (VARIANT_429, VARIANT_418)
SCENARIO_FAR = "far"
SDK_METHOD = "account_information_v3"  # the SDK call behind the equity refresh of every CONFIRM
RETRY_AFTER_SECONDS = 10
REASON_PAUSE = "RATE_LIMIT_PAUSE_429"
REASON_BAN = "IP_BAN_418"
BAN_ALERT_EVENT = "REST_GATE_BAN_ENTERED"
SKIP_EVENT = "RECONCILE_SKIPPED_GATE"

STEP_BASELINE = "gate_open_at_start"
STEP_INJECT = "inject_rate_limit_answer"
STEP_RESTRICTED = "gate_restricted_and_persisted"
STEP_REFUSED = "confirm_refused_nothing_sent"
STEP_NOT_RESENT = "nothing_re_sent_while_restricted"
STEP_REPLAY = "replayed_confirm_places_nothing"
STEP_RECONCILE_SKIP = "reconcile_skips_while_restricted"
STEP_ALERT = "ban_alert_journaled"
STEP_NO_ALERT = "no_ban_alert_for_a_pause"
STEP_OPEN_AGAIN = "gate_open_after_the_retry_after"
STEP_ENTRY_ALLOWED = "entry_allowed_again"
STEP_RESTART = "restart_restores_the_ban"

_RECONCILE_CORRELATION = "reconcile_loop"
_ALERT_CORRELATION = "operational_alerts"
_TOLERANCE_SECONDS = 2


def policy_of(env: Any) -> Any:
    """The rate-limit policy of the loaded Binance limits (`signed_calls.rate_limit_*`)."""
    return env.assembly.binance_limits.signed.rate_limit


def retry_after_for(policy: Any) -> int:
    """The short Retry-After of the 429 variant, refused when it would not show the header win.

    A Retry-After at or above the cap is capped, and one at or above the 429 fallback proves nothing
    (the fallback would give the same pause): both are refused, never silently adjusted.
    """
    seconds = RETRY_AFTER_SECONDS
    cap = int(policy.retry_after_cap_seconds)
    fallback = int(policy.no_retry_after_wait_429_seconds)
    if seconds >= cap or seconds >= fallback:
        raise ValueError(
            f"Retry-After {seconds} s is not below the cap ({cap} s) and the fallback "
            f"({fallback} s)"
        )
    return seconds


# ---- reads ------------------------------------------------------------------------------------- #


def reconcile_gate_skips(journal: Any) -> list[dict[str, Any]]:
    """The payloads of every `RECONCILE_SKIPPED_GATE` row of the reconcile loop."""
    rows = journal.list_by_correlation(_RECONCILE_CORRELATION)
    return [json.loads(r.payload_json) for r in rows if r.event_type == SKIP_EVENT]


def ban_alerts(journal: Any) -> list[dict[str, Any]]:
    """The payloads of every `REST_GATE_BAN_ENTERED` operational alert."""
    rows = journal.list_by_correlation(_ALERT_CORRELATION)
    payloads = [json.loads(r.payload_json) for r in rows if r.event_type == "OPERATIONAL_ALERT"]
    return [p for p in payloads if p.get("event") == BAN_ALERT_EVENT]


async def read_journal(env: Any, reader: Any) -> Any:
    """Run a journal reader through the process's own executor (the store is PostgreSQL on Demo)."""
    return await env.assembly.executor.read(reader, env.wiring.stores.journal)


def gate_of(env: Any) -> Any:
    return env.wiring.exchange.gate


def persisted_record(env: Any) -> Any:
    """The gate state record as the file holds it (read only; nothing is written)."""
    return env.assembly.exchange.gate_store.inspect().record


def sdk_calls(env: Any) -> int:
    """How many calls of the equity SDK method passed the gate and reached the SDK proxy."""
    return len(env.sdk_faults.calls_to(SDK_METHOD))


def _seconds(delta: timedelta) -> int:
    return int(delta / timedelta(seconds=1))


def record_inject(env: Any, recorder: ScenarioRecorder, detail: str) -> None:
    """The injected answer: DEMO_FAULT_INJECTED on Demo, never DEMO_OBSERVED."""
    record_injection_step(env, recorder, detail, name=STEP_INJECT)


def record_reaction(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A reaction of the real process: the env label."""
    record_step(env, recorder, name, detail)


async def await_refusal(env: Any, recorder: ScenarioRecorder, first: Any) -> list[dict[str, Any]]:
    """Wait for the placement decision of the plan's approval; a CONFIRM must end refused."""

    async def decided() -> bool:
        return bool(await placement_decision(env, first))

    if not await dr._wait_until(env, decided):
        raise dr._smoke_fail(env, recorder, STEP_REFUSED, "the CONFIRM left no journaled decision")
    return await placement_decision(env, first)


# ---- the scenario ------------------------------------------------------------------------------ #


async def run(env: Any, recorder: ScenarioRecorder, *, variant: str = VARIANT_429) -> str:
    """Run S10 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`.

    `variant="418"` is refused on a non-synthetic env: a ban is not run on Demo here (S19 runs the
    Demo 418 variant and clears it at once). An unknown variant raises before anything is recorded.
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {list(VARIANTS)}")
    if variant == VARIANT_418 and not env.synthetic:
        raise ValueError(
            "the 418 variant is twin only: on Demo S19 runs the 418 variant and clears it at once"
        )
    recorder.default_label = env.label
    recorder.details["variant"] = variant
    await ensure_clean_start(env, recorder)
    processes = _Current(env)
    try:
        return await _sequence(env, recorder, variant, processes)
    finally:
        env.sdk_faults.clear(SDK_METHOD)
        await processes.shutdown()


class _Current:
    """The process that runs now (a restart replaces it) and whether it was already stopped."""

    def __init__(self, env: Any) -> None:
        self.env = env
        self.stopped = False

    async def stop(self) -> None:
        await shutdown(self.env)
        self.stopped = True

    async def shutdown(self) -> None:
        if not self.stopped:
            await self.stop()


async def _sequence(env: Any, recorder: ScenarioRecorder, variant: str, processes: _Current) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    facts: dict[str, Any] = recorder.details.setdefault("rate_limit", {})
    policy = policy_of(env)
    gate = gate_of(env)
    if variant == VARIANT_429:
        retry_after: int | None = retry_after_for(policy)
        facts["retry_after_seconds"] = retry_after
        error: BaseException = too_many_requests_error(retry_after=retry_after)
        reason = REASON_PAUSE
    else:
        retry_after = None
        facts["fallback_418_seconds"] = int(policy.no_retry_after_wait_418_seconds)
        error = rate_limit_ban_error()
        reason = REASON_BAN
    facts["expected_reason"] = reason

    if gate.restriction() is not None:
        raise dr._smoke_fail(env, recorder, STEP_BASELINE, "the gate was restricted at the start")
    record_reaction(env, recorder, STEP_BASELINE, "the REST gate holds no restriction at the start")

    first = await card_and_approve(env, recorder)
    seen = sdk_calls(env)
    armed_at = env.clock()
    env.sdk_faults.fail_sdk(SDK_METHOD, error, times=1)
    record_inject(
        env,
        recorder,
        f"an HTTP {variant} answer is raised under the real adapter for the next {SDK_METHOD} "
        "call; nothing is sent to the exchange for it",
    )
    await env.owner.act("confirm", short_id=first.short_id, note="")
    decisions = await await_refusal(env, recorder, first)
    await _check_restriction(env, recorder, facts, reason, retry_after, armed_at)
    await _check_refusal(env, recorder, facts, decisions)
    await _check_nothing_resent(env, recorder, facts, first, seen)
    await _check_reconcile_skip(env, recorder, facts)
    _check_alerts(env, recorder, facts, variant, await read_journal(env, ban_alerts))
    await expire_plan(env, first)

    if variant == VARIANT_418:
        return await _restart_with_the_ban(env, recorder, facts, processes)
    return await _after_the_pause(env, recorder, facts)


async def _check_restriction(
    env: Any,
    recorder: ScenarioRecorder,
    facts: dict[str, Any],
    reason: str,
    retry_after: int | None,
    armed_at: datetime,
) -> None:
    gate = gate_of(env)
    restriction = gate.restriction()
    record = persisted_record(env)
    facts["restriction_seen_active"] = restriction is not None
    if restriction is not None:
        facts["restriction_reason"] = restriction.reason
        facts["restriction_until_utc"] = (
            None if restriction.until_utc is None else (restriction.until_utc.isoformat())
        )
    deadline = None
    if record is not None:
        deadline = record.pause_until_utc if reason == REASON_PAUSE else record.ban_until_utc
    facts["persisted_deadline_utc"] = None if deadline is None else deadline.isoformat()
    facts["persisted_other_deadline_is_none"] = record is not None and (
        record.ban_until_utc is None if reason == REASON_PAUSE else record.pause_until_utc is None
    )
    if deadline is None or deadline < armed_at:
        raise dr._smoke_fail(
            env, recorder, STEP_RESTRICTED, f"no {reason} deadline persisted after the injection"
        )
    wait = _seconds(deadline - record.recorded_at_utc)
    facts["persisted_wait_seconds"] = wait
    expected = retry_after if retry_after is not None else None
    if expected is None:
        expected = int(policy_of(env).no_retry_after_wait_418_seconds)
    if abs(wait - expected) > _TOLERANCE_SECONDS:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_RESTRICTED,
            f"the persisted wait is {wait} s, expected {expected} s",
        )
    if env.synthetic and (restriction is None or restriction.reason != reason):
        raise dr._smoke_fail(env, recorder, STEP_RESTRICTED, f"the gate does not report {reason}")
    if restriction is not None and restriction.reason != reason:
        raise dr._smoke_fail(
            env, recorder, STEP_RESTRICTED, f"the gate reports {restriction.reason}"
        )
    record_reaction(
        env,
        recorder,
        STEP_RESTRICTED,
        f"the gate recorded {reason} and persisted its deadline ({wait} s after the record)",
    )


async def _check_refusal(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], decisions: list[dict[str, Any]]
) -> None:
    sent = place_entry_calls(env)
    facts["decisions"] = decisions
    facts["place_entry_calls_at_refusal"] = sent
    refused = bool(decisions) and all(d["refused"] for d in decisions)
    facts["refusal_reason"] = decisions[-1]["reason"] if decisions else None
    if sent != 0 or not refused:
        raise dr._smoke_fail(
            env, recorder, STEP_REFUSED, f"{sent} place_entry call(s), decisions {decisions}"
        )
    record_reaction(
        env,
        recorder,
        STEP_REFUSED,
        f"the CONFIRM was refused ({facts['refusal_reason']}) and no entry was sent",
    )


async def _check_nothing_resent(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], first: Any, seen: int
) -> None:
    """The SDK was reached once (the injected call); a replayed CONFIRM sends and reads nothing.

    The count is only valid while the gate refuses, so the restriction is read before and after it
    and the window counts only when both readings are restricted.
    """
    gate = gate_of(env)
    injected = [c for c in env.sdk_faults.calls_to(SDK_METHOD) if c.get("injected") is True]
    facts["sdk_injected_calls"] = len(injected)
    facts["sdk_injections"] = len(env.sdk_faults.injections)
    if len(injected) != 1 or len(env.sdk_faults.injections) != 1:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_NOT_RESENT,
            f"{len(injected)} injected SDK call(s), {len(env.sdk_faults.injections)} injection(s)",
        )
    before = gate.restriction()
    await env.owner.act("replay_confirm", short_id=first.short_id)
    count = sdk_calls(env) - seen
    after = gate.restriction()
    window_valid = before is not None and after is not None
    facts["sdk_calls_since_arming"] = count
    facts["replay_window_restricted"] = window_valid
    facts["place_entry_calls_after_replay"] = place_entry_calls(env)
    if place_entry_calls(env) != 0:
        raise dr._smoke_fail(env, recorder, STEP_REPLAY, "a replayed CONFIRM sent an entry")
    record_reaction(
        env, recorder, STEP_REPLAY, "a replayed CONFIRM during the restriction placed nothing"
    )
    if env.synthetic and not window_valid:
        raise dr._smoke_fail(env, recorder, STEP_NOT_RESENT, "the twin's gate was not restricted")
    if window_valid and count != 1:
        raise dr._smoke_fail(
            env, recorder, STEP_NOT_RESENT, f"{count} SDK call(s) since arming, expected 1"
        )
    if window_valid:
        record_reaction(
            env,
            recorder,
            STEP_NOT_RESENT,
            "the SDK was reached once (the injected call); the gate refused every other read",
        )
    else:
        record_gap(
            env,
            recorder,
            STEP_NOT_RESENT,
            "the restriction ended before the window could be read; the injected call count "
            "(exactly one) is recorded, the 'nothing in between' window is not",
        )


async def _check_reconcile_skip(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]
) -> None:
    """A reconcile tick while the gate is restricted journals the skip (twin: stepped by hand)."""
    gate = gate_of(env)

    async def skipped() -> bool:
        if await read_journal(env, reconcile_gate_skips):
            return True
        return gate.restriction() is None  # the restriction ended: stop waiting

    await ticks(env, 1)
    await dr._wait_until(env, skipped)
    rows = await read_journal(env, reconcile_gate_skips)
    facts["reconcile_gate_skips"] = len(rows)
    facts["reconcile_skip_reasons"] = sorted({str(r.get("reason")) for r in rows})
    if rows:
        record_reaction(
            env,
            recorder,
            STEP_RECONCILE_SKIP,
            f"the reconcile loop journaled {SKIP_EVENT} ({facts['reconcile_skip_reasons']})",
        )
    elif env.synthetic:
        raise dr._smoke_fail(env, recorder, STEP_RECONCILE_SKIP, "no reconcile skip was journaled")
    else:
        record_gap(
            env,
            recorder,
            STEP_RECONCILE_SKIP,
            "no reconcile tick ran inside the restriction window of the injected pause",
        )


def _check_alerts(
    env: Any,
    recorder: ScenarioRecorder,
    facts: dict[str, Any],
    variant: str,
    alerts: list[dict[str, Any]],
) -> None:
    facts["ban_alerts"] = alerts
    if variant == VARIANT_418:
        if (
            len(alerts) != 1
            or alerts[0].get("reason") != REASON_BAN
            or not alerts[0].get("until_utc")
        ):
            raise dr._smoke_fail(env, recorder, STEP_ALERT, f"ban alerts journaled: {alerts}")
        record_reaction(
            env,
            recorder,
            STEP_ALERT,
            f"one OPERATIONAL_ALERT {BAN_ALERT_EVENT} ({REASON_BAN}) carries the gate's deadline",
        )
        return
    if alerts:
        raise dr._smoke_fail(env, recorder, STEP_NO_ALERT, f"a pause raised a ban alert: {alerts}")
    record_reaction(
        env, recorder, STEP_NO_ALERT, "a 429 pause raises no ban alert (only a 418 does)"
    )


async def _after_the_pause(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> str:
    gate = gate_of(env)

    async def open_now() -> bool:
        return gate.restriction() is None

    if not await dr._wait_until(env, open_now):
        raise dr._smoke_fail(env, recorder, STEP_OPEN_AGAIN, "the gate did not open again")
    record_reaction(
        env, recorder, STEP_OPEN_AGAIN, "after the Retry-After the gate refuses nothing any more"
    )
    second = await place_approved_entry(env, recorder, SCENARIO_FAR)
    facts["place_entry_calls_after_the_pause"] = place_entry_calls(env)
    if place_entry_calls(env) != 1:
        raise dr._smoke_fail(
            env, recorder, STEP_ENTRY_ALLOWED, f"{place_entry_calls(env)} place_entry calls"
        )
    record_reaction(
        env, recorder, STEP_ENTRY_ALLOWED, "a new request is placed once the pause has passed"
    )
    await cancel_resting_entry(env, recorder, second)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE


async def _restart_with_the_ban(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], processes: _Current
) -> str:
    """Twin only: stop in order, start a second process; the persisted ban is restored."""
    before = gate_of(env).restriction()
    if before is None or env.restart is None:
        raise dr._smoke_fail(env, recorder, STEP_RESTART, "no ban to carry over or no restart")
    await processes.stop()
    second = await env.restart()
    processes.env = second
    processes.stopped = False
    outcome = await start_tolerant(second, recorder, "restart")
    restored = gate_of(second).restriction()
    facts["restart"] = {
        "admitted": bool(outcome.admitted),
        "in_safe_mode": bool(outcome.in_safe_mode),
        "enabled": bool(outcome.enabled),
        "restored_reason": None if restored is None else restored.reason,
        "restored_until_utc": None
        if restored is None or restored.until_utc is None
        else (restored.until_utc.isoformat()),
        "expected_until_utc": facts.get("restriction_until_utc"),
    }
    if (
        restored is None
        or restored.reason != REASON_BAN
        or facts["restart"]["restored_until_utc"] != facts["restart"]["expected_until_utc"]
        or outcome.enabled
    ):
        raise dr._smoke_fail(
            env, recorder, STEP_RESTART, f"the restart did not carry the ban: {facts['restart']}"
        )
    record_reaction(
        env,
        recorder,
        STEP_RESTART,
        "the second process restored the same ban deadline from the state file and did not "
        "enable entries",
    )
    await ticks(second, 2)
    if place_entry_calls(second) != 0:
        raise dr._smoke_fail(env, recorder, STEP_RESTART, "an entry was sent under the ban")
    if not await account_clean(second, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE
