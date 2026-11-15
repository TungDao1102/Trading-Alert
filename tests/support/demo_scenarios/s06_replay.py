"""S06 replayed and concurrent presses: one entry, one outcome (plan 25-10; EXEC-03, APRV-02).

TEST_ONLY. The scenario runs the composed process (fake in the CI twin, real Demo in the owner's
test) through `run(env, recorder)`: one "far" request is approved, then two CONFIRM presses race
through the runner's handler (two handler calls with distinct callback query ids), then the same
APPROVE and CONFIRM are replayed. The exchange must see exactly one `place_entry` (counted at the
`FaultEdge` the env installs, which records every adapter call whether or not a fault is armed),
the journal must hold exactly one non-refused `LIVE_PLACEMENT_OUTCOME` for the plan, and the run
ends with the resting entry cancelled through the production path and `account_clean` PASSED.

No step injects a trigger, so every step carries the env label (SYNTHETIC on the fake,
DEMO_OBSERVED on Demo). The "far" request rests far below the mark and is never filled.

`place_approved_entry` (inject, card, APPROVE, CONFIRM, entry acknowledged) is shared by S02 and
S05, which differ only in what happens after the entry is acknowledged.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from scripts import demo_rehearsal as dr
from src.domain.enums import ExecutionIntentStatus, TradePlanStatus
from src.execution.manager import expire_pending_entry
from src.execution.protection import ProtectionState
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME

from tests.support.demo_scenarios.harness import ScenarioRecorder, account_clean, ensure_clean_start

SCENARIO_FAR = "far"
STEP_CONCURRENT_CONFIRM = "concurrent_confirm"
STEP_REPLAYS = "replays_place_nothing"
STEP_ONE_OUTCOME = "one_placement_outcome"
STEP_CANCEL_ENTRY = "cancel_resting_entry"
STEP_CLOSE = "close_cleanup"
_JOURNAL_CORRELATION_PREFIX = "live-placement"


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S06 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder)
    finally:
        await shutdown(env)


async def shutdown(env: Any) -> None:
    """Stop the process in order, best effort, whatever happened (the smoke's own finally)."""
    from src.live.runtime import shutdown_in_order

    try:
        await shutdown_in_order(env.assembly)
    except Exception:  # noqa: BLE001, S110 - best effort at the end of a scenario
        pass


def start_evidence(env: Any, recorder: ScenarioRecorder) -> None:
    """The evidence kind and, on the fake, the note that nothing here is Demo-observed."""
    recorder.details["evidence_kind"] = env.label
    if env.synthetic:
        recorder.add_synthetic_input(
            "SYNTHETIC run: the exchange is the Binance-semantics fake, the presses are fake and "
            "every id, price and time is a test value; nothing here is Demo-observed"
        )


async def place_approved_entry(
    env: Any,
    recorder: ScenarioRecorder,
    scenario: str,
    *,
    confirm_presses: int = 1,
) -> Any:
    """Inject `scenario`, wait for the card, APPROVE, CONFIRM and wait for the entry ACK.

    `confirm_presses > 1` issues that many CONFIRM presses concurrently (distinct query ids).
    Returns the injected request (`dr._Request`). Every failure records its step and raises
    `dr.SmokeHalt`.
    """
    first = await dr._inject(env, recorder, scenario, "signal")
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

    presses = [
        env.owner.act("confirm", short_id=first.short_id, note="") for _ in range(confirm_presses)
    ]
    await asyncio.gather(*presses)

    async def entry_acked() -> bool:
        row = await dr._smoke_read(
            env, wiring.stores.execution_state.intent_for_client_id, first.entry_client_id
        )
        return row is not None and row.intent_status is ExecutionIntentStatus.ACKED

    if not await dr._wait_until(env, entry_acked):
        raise dr._smoke_fail(env, recorder, "confirm_entry", "the entry was not acknowledged")
    await dr._record_order_ids(env, recorder, "confirm_entry", first)
    dr._smoke_record(
        env,
        recorder,
        "confirm_entry",
        dr.STEP_PASSED,
        f"one GTD LIMIT entry acknowledged after {confirm_presses} CONFIRM press(es)",
    )
    return first


def place_entry_calls(env: Any) -> int:
    """How many `place_entry` calls reached the adapter edge (the exchange POSTs of this env)."""
    return len(env.faults.calls_to("place_entry"))


async def _sequence(env: Any, recorder: ScenarioRecorder) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    wiring = env.wiring

    first = await place_approved_entry(env, recorder, SCENARIO_FAR, confirm_presses=2)
    placed = place_entry_calls(env)
    if placed != 1:
        raise dr._smoke_fail(
            env, recorder, STEP_CONCURRENT_CONFIRM, f"{placed} place_entry calls, expected 1"
        )
    dr._smoke_record(
        env,
        recorder,
        STEP_CONCURRENT_CONFIRM,
        dr.STEP_PASSED,
        "two concurrent CONFIRM presses led to exactly one place_entry",
    )

    # ---- replays of the same APPROVE and CONFIRM ------------------------------------------ #
    await env.owner.act("replay_approve", short_id=first.short_id)
    await env.owner.act("replay_confirm", short_id=first.short_id)
    for _ in range(dr.SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()
    adapter = env.assembly.exchange.adapter
    resting = await adapter.snapshot_open_normal_orders(symbol=dr.SYMBOL)
    placed = place_entry_calls(env)
    if placed != 1 or len(resting) != 1:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_REPLAYS,
            f"{placed} place_entry calls and {len(resting)} open orders after the replays",
        )
    dr._smoke_record(
        env,
        recorder,
        STEP_REPLAYS,
        dr.STEP_PASSED,
        "a replayed APPROVE and a replayed CONFIRM placed nothing; one entry rests",
    )

    # ---- exactly one non-refused placement outcome in the journal -------------------------- #
    outcomes = await env.assembly.executor.read(
        placement_outcomes, wiring.stores.journal, wiring.stores.shadow, first.trade_plan_id
    )
    refused = [o for o in outcomes if o.get("is_no_trade")]
    if len(outcomes) != 1 or refused:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_ONE_OUTCOME,
            f"{len(outcomes)} placement outcome row(s), {len(refused)} refused; expected one "
            "non-refused",
        )
    dr._smoke_record(
        env,
        recorder,
        STEP_ONE_OUTCOME,
        dr.STEP_PASSED,
        "the journal holds one non-refused LIVE_PLACEMENT_OUTCOME for the plan",
    )

    # ---- cancel the resting entry through the production path, then the account is clean --- #
    await cancel_resting_entry(env, recorder, first)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE


def placement_outcomes(journal: Any, shadow: Any, trade_plan_id: str) -> list[dict[str, Any]]:
    """The payloads of every `LIVE_PLACEMENT_OUTCOME` row of the plan's approvals."""
    approval_ids: dict[str, None] = {}
    for approval in [*shadow.list_pending_approvals(), *shadow.list_approved_approvals()]:
        if approval.trade_plan_id == trade_plan_id:
            approval_ids[approval.approval_id] = None
    rows: list[dict[str, Any]] = []
    for approval_id in approval_ids:
        correlation = f"{_JOURNAL_CORRELATION_PREFIX}:{approval_id}"
        for event in journal.list_by_correlation(correlation):
            if event.event_type == EVENT_PLACEMENT_OUTCOME:
                rows.append(json.loads(event.payload_json))
    return rows


async def cancel_resting_entry(env: Any, recorder: ScenarioRecorder, first: Any) -> None:
    """Cancel the plan's resting entry with `expire_pending_entry` and close its APPROVED plan.

    The same two production steps the smoke drill and `scripts/demo_clear.py` use: the entry is
    cancelled by its deterministic client id (verified by a query afterwards), and the plan moves
    APPROVED -> EXPIRED (DOMN-04), so its approval no longer holds the symbol. Never a blanket
    cancel of the account.
    """
    wiring = env.wiring
    verdict = await expire_pending_entry(
        plan_hash=first.plan_hash,
        symbol=dr.SYMBOL,
        adapter=env.assembly.exchange.adapter,
        journal=wiring.stores.journal,
        now_utc=env.clock(),
        trigger_reason="operator_close",
        spill=getattr(wiring, "spill", None),
    )
    await env.assembly.executor.write(
        wiring.stores.entities.transition_trade_plan,
        first.trade_plan_id,
        TradePlanStatus.EXPIRED,
        now_utc=env.clock(),
    )
    for _ in range(dr.SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()
    view = wiring.coordinator.protection_of(first.plan_hash)
    state = None if view is None else view.state
    if verdict.value != "CANCELED" or state is not ProtectionState.ENTRY_ENDED_NO_FILL:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_CANCEL_ENTRY,
            f"cancel verdict {verdict.value}, protection state {None if state is None else state}",
        )
    dr._smoke_record(
        env,
        recorder,
        STEP_CANCEL_ENTRY,
        dr.STEP_PASSED,
        "the resting entry was cancelled by its client id and the plan expired",
    )


async def close_and_clean(env: Any, recorder: ScenarioRecorder, first: Any) -> None:
    """Close the plan's position with the production operator close, expire the plan, check clean.

    `operator_close_position` sends the reduce-only MARKET close and the coordinator sweeps the
    plan's legs by their deterministic ids (never a blanket cancel); the APPROVED plan then moves
    to EXPIRED (DOMN-04) so its approval no longer holds the symbol; `account_clean` PASSED or
    `dr.SmokeHalt`.
    """
    from src.execution.manager import operator_close_position

    wiring = env.wiring
    closed = await operator_close_position(
        coordinator=wiring.coordinator, plan_hash=first.plan_hash, operator_id=dr.OPERATOR_ID
    )
    if not closed.accepted:
        raise dr._smoke_fail(env, recorder, STEP_CLOSE, f"close refused: {closed.code}")

    async def flat() -> bool:
        view = wiring.coordinator.protection_of(first.plan_hash)
        return view is not None and view.state is ProtectionState.FLAT

    if not await dr._wait_until(env, flat):
        raise dr._smoke_fail(env, recorder, STEP_CLOSE, "the plan did not end FLAT")
    dr._smoke_record(env, recorder, STEP_CLOSE, dr.STEP_PASSED, "closed by the operator close")
    await env.assembly.executor.write(
        wiring.stores.entities.transition_trade_plan,
        first.trade_plan_id,
        TradePlanStatus.EXPIRED,
        now_utc=env.clock(),
    )
    for _ in range(dr.SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
