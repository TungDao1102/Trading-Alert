"""S04 stop rejected after a fill: one reduce-only close, never a second stop (plan 25-11).

TEST_ONLY. EXEC-01, OPS-01, D079 / D077 / D080. Binance Demo cannot reject a stop on demand, so the
trigger is injected at the adapter edge (`FaultEdge.raise_before_send` on `place_algo_protective`,
a `BadRequestError` carrying code -2021, nothing is sent for it) and the REACTION is the real one
(25-RESEARCH Pattern 2, D-08): the coordinator classifies the rejection as definitive (branch B5),
never resends the stop, enters CLOSE_REQUIRED, sends one reduce-only MARKET close under a derived
`xc-` client id, ends FLAT, journals the critical alerts and blocks new entries meanwhile.

Labels: the injection step is `label_for(env, injected=True)` (DEMO_FAULT_INJECTED on Demo), the
close is `label_for(env, injected=False)` (DEMO_OBSERVED on Demo, a real Demo order). On the fake
every step is SYNTHETIC.

This module also holds the helpers S03 and S18 share (the catalog names only the nine files of the
plan): `injected_rejection`, `drive_fill`, `stop_placements`, `protection_rows`, `alert_rows`,
`expire_plan_and_leave_safe_mode` and the step recorders.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from binance_common.errors import BadRequestError
from scripts import demo_rehearsal as dr
from src.domain.enums import OrderRole, TradePlanStatus
from src.execution.order_ids import derive_algo_client_id, derive_close_order_id
from src.execution.protection import ProtectionState

from tests.support.demo_scenarios.harness import (
    NOT_OBSERVED,
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
    label_for,
)
from tests.support.demo_scenarios.s06_replay import (
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)
from tests.support.virtual_time import yield_to_loop

SCENARIO_FILL = "fill"
STOP_METHOD = "place_algo_protective"
CLOSE_METHOD = "place_market_close"
REJECTION_CODE = -2021  # ORDER_WOULD_IMMEDIATELY_TRIGGER (DEMO_PROBE_DATE 2026-10-22)
BRANCH_B5 = "B5_STOP_REJECTED"

STEP_INJECT = "inject_stop_rejection"
STEP_STOP_NOT_RESENT = "stop_not_resent"
STEP_CLOSE_REQUIRED = "close_required_b5"
STEP_BLOCKED = "entries_blocked_while_close_required"
STEP_CLOSE = "reduce_only_close"
STEP_ALERTS = "alerts_journaled"
STEP_SAFE_MODE_LEFT = "safe_mode_left"
STEP_PLAN_EXPIRED = "plan_expired"

_HOLD_POLL_ROUNDS = 5000
_PROTECTION_CORRELATION_PREFIX = "protection_"
_ALERT_CORRELATION_ID = "operational_alerts"
_CLOSING_STATES = (
    ProtectionState.CLOSE_REQUIRED,
    ProtectionState.CLOSE_FAILED,
    ProtectionState.FLAT,
)


def injected_rejection(code: int = REJECTION_CODE) -> BadRequestError:
    """The definitive rejection the adapter edge raises; the text says TEST_ONLY, never read."""
    return BadRequestError(error_message="TEST_ONLY injected rejection", status_code=code)


# ---- step recorders (the label rule in one place) ---------------------------------------------- #


def _prefix(env: Any) -> str:
    return "SYNTHETIC: " if env.synthetic else ""


def record_injection_step(
    env: Any, recorder: ScenarioRecorder, detail: str, *, name: str = STEP_INJECT
) -> None:
    """An injected trigger: DEMO_FAULT_INJECTED on Demo, never DEMO_OBSERVED (T-25-25)."""
    recorder.add_labeled_step(
        name, dr.STEP_PASSED, _prefix(env) + detail, label=label_for(env, injected=True)
    )


def record_close_step(
    env: Any, recorder: ScenarioRecorder, detail: str, *, name: str = STEP_CLOSE
) -> None:
    """The reaction: the env label (a real Demo order is DEMO_OBSERVED)."""
    recorder.add_labeled_step(
        name, dr.STEP_PASSED, _prefix(env) + detail, label=label_for(env, injected=False)
    )


def record_step(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    recorder.add_labeled_step(
        name, dr.STEP_PASSED, _prefix(env) + detail, label=label_for(env, injected=False)
    )


# ---- reads through the process ----------------------------------------------------------------- #


def stop_placements(env: Any, plan_hash: str) -> list[dict[str, Any]]:
    """Every `place_algo_protective` call of the plan's STOP_LOSS id that reached the edge."""
    stop_id = derive_algo_client_id(plan_hash=plan_hash, role=OrderRole.STOP_LOSS.value)
    return [
        c
        for c in env.faults.calls_to(STOP_METHOD)
        if c.get("kwargs", {}).get("client_algo_id") == stop_id
    ]


def close_placements(env: Any) -> list[dict[str, Any]]:
    """Every reduce-only MARKET close that reached the edge."""
    return list(env.faults.calls_to(CLOSE_METHOD))


def protection_rows(journal: Any, plan_hash: str) -> list[dict[str, Any]]:
    """The payloads of the plan's `PROTECTION_TRANSITION` rows, in recording order."""
    rows = journal.list_by_correlation(f"{_PROTECTION_CORRELATION_PREFIX}{plan_hash}")
    ordered = sorted(
        (row for row in rows if row.event_type == "PROTECTION_TRANSITION"),
        key=lambda row: json.loads(row.payload_json)["seq"],
    )
    return [json.loads(row.payload_json) for row in ordered]


def alert_rows(journal: Any, plan_hash: str) -> list[dict[str, Any]]:
    """The payloads of the `OPERATIONAL_ALERT` rows that name the plan."""
    rows = journal.list_by_correlation(_ALERT_CORRELATION_ID)
    payloads = [
        json.loads(row.payload_json) for row in rows if row.event_type == "OPERATIONAL_ALERT"
    ]
    return [payload for payload in payloads if payload.get("plan_hash") == plan_hash]


def _protection(env: Any, plan_hash: str) -> Any:
    return env.wiring.coordinator.protection_of(plan_hash)


# ---- the shared moves -------------------------------------------------------------------------- #


async def drive_fill(env: Any, first: Any) -> None:
    """The fill: scripted on the fake, the exchange's own on Demo (a marketable entry)."""
    if env.deliver_fill is not None:
        await env.deliver_fill(first)


async def _sample_window(env: Any, first: Any) -> tuple[ProtectionState, bool] | None:
    view = _protection(env, first.plan_hash)
    if view is None or view.state not in _CLOSING_STATES:
        return None
    return view.state, bool(env.wiring.coordinator.blocks_new_entries())


async def _poll_for_window(env: Any, first: Any) -> tuple[ProtectionState, bool] | None:
    """Tick until the plan is closing or flat; on the fake the close is held for one look.

    On the fake (`env.deliver_fill` is set) the reduce-only close is held at the exchange while a
    tick runs, so the window "CLOSE_REQUIRED, close in flight" is stepped deterministically. On Demo
    nothing is held (a delayed risk-reducing close would be real exposure): the plain tick loop
    samples the state between ticks and may land after FLAT.
    """
    scripted = env.deliver_fill is not None
    if scripted:
        env.faults.hold(CLOSE_METHOD)
    try:
        for _ in range(env.wait_ticks):
            sampled = await _sample_window(env, first)
            if sampled is not None:
                return sampled
            ticking = asyncio.ensure_future(env.tick())
            if scripted:
                for _ in range(_HOLD_POLL_ROUNDS):
                    if env.faults.held(CLOSE_METHOD) or ticking.done():
                        break
                    await yield_to_loop()
                if env.faults.held(CLOSE_METHOD):
                    sampled = await _sample_window(env, first)
                    env.faults.release(CLOSE_METHOD)
                    await ticking
                    return sampled
            await ticking
        return await _sample_window(env, first)
    finally:
        if env.faults.held(CLOSE_METHOD):
            env.faults.release(CLOSE_METHOD)
        env.faults.clear(CLOSE_METHOD)


async def observe_close_window(
    env: Any, recorder: ScenarioRecorder, first: Any, *, step: str = STEP_CLOSE_REQUIRED
) -> ProtectionState:
    """Record the first closing state seen (B5 expected) and whether entries were blocked.

    While the plan is CLOSE_REQUIRED the coordinator must block new entries; that window is stepped
    on the fake and best effort on Demo (T-25-25): a plan seen already FLAT leaves the blocked step
    NOT_OBSERVED instead of PASSED.
    """
    sampled = await _poll_for_window(env, first)
    if sampled is None:
        raise dr._smoke_fail(env, recorder, step, "the plan never reached CLOSE_REQUIRED or FLAT")
    state, blocks = sampled
    observed = state is ProtectionState.CLOSE_REQUIRED
    recorder.details["close_required_window"] = {
        "observed": observed,
        "state": state.value,
        "blocks_new_entries": blocks,
    }
    if state is ProtectionState.CLOSE_FAILED:
        raise dr._smoke_fail(env, recorder, step, "the close did not end flat (CLOSE_FAILED)")
    if observed:
        if blocks is not True:
            raise dr._smoke_fail(
                env, recorder, STEP_BLOCKED, "new entries were not blocked in CLOSE_REQUIRED"
            )
        record_step(
            env,
            recorder,
            STEP_BLOCKED,
            "blocks_new_entries() was True while the plan was CLOSE_REQUIRED",
        )
    else:
        recorder.add_labeled_step(
            STEP_BLOCKED,
            dr.STEP_NOT_REHEARSED,
            _prefix(env) + "the poll found the plan already FLAT; the window was not stepped",
            label=label_for(env, injected=False) if env.synthetic else NOT_OBSERVED,
        )
    return state


async def wait_flat(env: Any, recorder: ScenarioRecorder, first: Any, step: str) -> None:
    async def flat() -> bool:
        view = _protection(env, first.plan_hash)
        return view is not None and view.state is ProtectionState.FLAT

    if not await dr._wait_until(env, flat):
        view = _protection(env, first.plan_hash)
        state = None if view is None else view.state.value
        raise dr._smoke_fail(env, recorder, step, f"the plan did not end FLAT (state {state})")


async def assert_b5_reaction(env: Any, recorder: ScenarioRecorder, first: Any) -> None:
    """The reaction every definitive stop rejection shares (S04, S03 ii): the checks, recorded."""
    wiring = env.wiring
    plan_hash = first.plan_hash
    for _ in range(dr.SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()
    # --- never resent ---
    stops = stop_placements(env, plan_hash)
    if len(stops) != 1:
        raise dr._smoke_fail(
            env, recorder, STEP_STOP_NOT_RESENT, f"{len(stops)} stop placements, expected 1"
        )
    stop_id = derive_algo_client_id(plan_hash=plan_hash, role=OrderRole.STOP_LOSS.value)
    intent = await dr._smoke_read(env, wiring.stores.execution_state.intent_for_client_id, stop_id)
    intent_status = None if intent is None else intent.intent_status.value
    if intent_status != "REJECTED":
        raise dr._smoke_fail(
            env, recorder, STEP_STOP_NOT_RESENT, f"stop intent status {intent_status}"
        )
    record_step(
        env,
        recorder,
        STEP_STOP_NOT_RESENT,
        "one stop placement reached the edge and its intent is REJECTED; it was never resent",
    )
    # --- B5 and the journal ---
    rows = await env.assembly.executor.read(protection_rows, wiring.stores.journal, plan_hash)
    triples = [(row["from"], row["to"], row["reason"]) for row in rows]
    if ("UNPROTECTED", "CLOSE_REQUIRED", BRANCH_B5) not in triples:
        raise dr._smoke_fail(
            env, recorder, STEP_CLOSE_REQUIRED, f"no B5 CLOSE_REQUIRED transition in {triples}"
        )
    record_step(
        env,
        recorder,
        STEP_CLOSE_REQUIRED,
        "UNPROTECTED -> CLOSE_REQUIRED with reason B5_STOP_REJECTED is journaled",
    )
    # --- exactly one reduce-only close under an xc- id ---
    closes = close_placements(env)
    expected_id = derive_close_order_id(plan_hash=plan_hash, attempt_no=1)
    if len(closes) != 1 or closes[0]["kwargs"].get("new_client_order_id") != expected_id:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_CLOSE,
            f"{len(closes)} close call(s), expected one under {expected_id}",
        )
    close = closes[0]["kwargs"]
    if close.get("position_side") != "BOTH" or not str(expected_id).startswith("xc-"):
        raise dr._smoke_fail(env, recorder, STEP_CLOSE, "the close is not a one-way reduce-only")
    adapter = env.assembly.exchange.adapter
    positions = [
        p for p in await adapter.snapshot_positions(symbol=dr.SYMBOL) if p.position_amt != 0
    ]
    if positions:
        raise dr._smoke_fail(env, recorder, STEP_CLOSE, "a position is still open after the close")
    recorder.record_ids(
        STEP_CLOSE, order_ids=[], client_order_ids=[expected_id], algo_client_ids=[]
    )
    record_close_step(
        env,
        recorder,
        "one reduce-only MARKET close under the derived xc- client id; the position is flat",
    )
    # --- the alerts ---
    alerts = await env.assembly.executor.read(alert_rows, wiring.stores.journal, plan_hash)
    pairs = {(row.get("event"), row.get("reason")) for row in alerts}
    needed = {("CLOSE_REQUIRED", BRANCH_B5), ("PROTECTIVE_REJECTED", BRANCH_B5)}
    if not needed <= pairs:
        raise dr._smoke_fail(env, recorder, STEP_ALERTS, f"alert rows {sorted(map(str, pairs))}")
    record_step(
        env,
        recorder,
        STEP_ALERTS,
        "OPERATIONAL_ALERT rows CLOSE_REQUIRED and PROTECTIVE_REJECTED name the plan",
    )
    # --- no second entry ---
    placed = place_entry_calls(env)
    if placed != 1:
        raise dr._smoke_fail(env, recorder, STEP_CLOSE, f"{placed} place_entry calls, expected 1")


async def expire_plan_and_leave_safe_mode(env: Any, recorder: ScenarioRecorder, first: Any) -> None:
    """Expire the APPROVED plan, leave SAFE_MODE by the operator commands, check the account clean.

    The plan moves APPROVED -> EXPIRED (the transition `scripts/demo_clear.py` makes), so its
    approval no longer holds the symbol. B5 entered SAFE_MODE `CLOSE_REQUIRED`, which is durable on
    Demo (PostgreSQL): it is left through `/safemode_exit` and `/confirm <token>` (RUNBOOK 21.1a),
    the same path the owner would take, so the next scenario starts clean.
    """
    wiring = env.wiring
    await env.assembly.executor.write(
        wiring.stores.entities.transition_trade_plan,
        first.trade_plan_id,
        TradePlanStatus.EXPIRED,
        now_utc=env.clock(),
    )
    for _ in range(dr.SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()
    if wiring.safe_mode.in_safe_mode:
        await env.owner.act("safemode_exit")

        async def left() -> bool:
            return not wiring.safe_mode.in_safe_mode

        if not await dr._wait_until(env, left):
            raise dr._smoke_fail(
                env,
                recorder,
                STEP_SAFE_MODE_LEFT,
                "SAFE_MODE was not left by /safemode_exit; read its refusal rows, then leave it "
                "by hand (RUNBOOK 21.1a) and run scripts/demo_clear.py if anything is left",
            )
    record_step(
        env, recorder, STEP_SAFE_MODE_LEFT, "SAFE_MODE is off (left through /safemode_exit)"
    )
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")


# ---- the scenario ------------------------------------------------------------------------------ #


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S04 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder)
    finally:
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")

    # The rejection is armed BEFORE the fill; the first stop placement consumes it.
    env.faults.raise_before_send(STOP_METHOD, injected_rejection(), times=1)
    first = await place_approved_entry(env, recorder, SCENARIO_FILL)
    await drive_fill(env, first)

    state = await observe_close_window(env, recorder, first)
    injected = [c for c in stop_placements(env, first.plan_hash) if c.get("injected") is True]
    if len(injected) != 1:
        raise dr._smoke_fail(
            env, recorder, STEP_INJECT, f"{len(injected)} injected stop placements, expected 1"
        )
    record_injection_step(
        env,
        recorder,
        f"the first stop placement was rejected at the adapter edge with code {REJECTION_CODE}; "
        "nothing was sent to the exchange for it",
    )
    recorder.details["first_closing_state"] = state.value
    await wait_flat(env, recorder, first, STEP_CLOSE)
    await assert_b5_reaction(env, recorder, first)
    await expire_plan_and_leave_safe_mode(env, recorder, first)

    window = recorder.details["close_required_window"]
    outcome = dr.OUTCOME_COMPLETE if window["observed"] else dr.OUTCOME_COMPLETE_WITH_GAPS
    recorder.outcome = outcome
    return outcome
