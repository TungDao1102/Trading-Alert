"""S05 cancel racing a fill: the fill ends protected or closed, never orphaned (plan 25-10).

TEST_ONLY. EXEC-01, D-12/D-13. One "fill" request is approved and confirmed; once the entry is
acknowledged, the entry cancel of the expiry path (`expire_pending_entry` with the canonical
trigger `expiry_time`, the call the scheduled cancel makes after the plan expiry) races the fill.

* On the fake (`env.deliver_fill` is set) the race is deterministic: the cancel is held at the
  exchange with the fault edge's hold/release, the entry fills while it is held, then the cancel is
  released and finds the order already filled. Nothing is injected beyond the delay of a request.
* On Demo nothing is held (a delayed send would not be the natural race): the cancel is sent once
  right after the acknowledgment, and the exchange decides. The race step is DEMO_OBSERVED only if
  the entry still rested (NEW) when the cancel started and the post-cancel query showed it filled;
  otherwise NOT_OBSERVED with the order of events (T-25-25).

Either way the run must end with: a verdict of FILLED_OR_PARTIAL (the cancel answered "already
filled or absent") followed by a confirmed stop and a plan that is not CLOSE_REQUIRED, no resting
entry order and no algo order outside the plan's own legs, exactly one `place_entry`, and an account
that ends clean after the production operator close. If the cancel won instead (no fill), the entry
is CANCELED, nothing is protected because nothing filled, and the plan is expired.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from scripts import demo_rehearsal as dr
from src.domain.enums import OrderRole
from src.execution.cancel_verification import CancelVerdict
from src.execution.manager import expire_pending_entry
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState

from tests.support.demo_scenarios.harness import (
    NOT_OBSERVED,
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
    label_for,
)
from tests.support.demo_scenarios.s06_replay import (
    cancel_resting_entry,
    close_and_clean,
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)
from tests.support.virtual_time import yield_to_loop

SCENARIO_FILL = "fill"
STEP_RACE = "cancel_fill_race"
STEP_PROTECTED = "fill_protected"
STEP_NO_ORPHAN = "no_orphan_no_second_entry"

_CANCEL = "cancel_normal_order"
_HOLD_POLL_ROUNDS = 5000
_ZERO = Decimal(0)
_FILLED_VERDICT = CancelVerdict.FILLED_OR_PARTIAL


def crossed(pre_status: str | None, verdict: CancelVerdict) -> bool:
    """True when the entry rested before the cancel and the exchange then showed it filled."""
    return pre_status == "NEW" and verdict is _FILLED_VERDICT


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S05 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder)
    finally:
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    wiring = env.wiring
    adapter = env.assembly.exchange.adapter
    first = await place_approved_entry(env, recorder, SCENARIO_FILL)

    # ---- the race: the cancel of the expiry path against the fill --------------------------- #
    pre = await adapter.query_order_by_client(
        symbol=dr.SYMBOL, orig_client_order_id=first.entry_client_id
    )
    pre_status = pre.status
    scripted = env.deliver_fill is not None
    if scripted:
        env.faults.hold(_CANCEL)
    cancel = asyncio.ensure_future(
        expire_pending_entry(
            plan_hash=first.plan_hash,
            symbol=dr.SYMBOL,
            adapter=adapter,
            journal=wiring.stores.journal,
            now_utc=env.clock(),
            trigger_reason="expiry_time",
            spill=getattr(wiring, "spill", None),
        )
    )
    if scripted:
        for _ in range(_HOLD_POLL_ROUNDS):
            if env.faults.held(_CANCEL) or cancel.done():
                break
            await yield_to_loop()
        if not env.faults.held(_CANCEL):
            await _settle(cancel)
            raise dr._smoke_fail(env, recorder, STEP_RACE, "the cancel never reached the exchange")
        await env.deliver_fill(first)
        env.faults.release(_CANCEL)
    try:
        verdict = await cancel
    except Exception as exc:  # noqa: BLE001 - recorded by class name, then the scenario stops
        recorder.record_failure(STEP_RACE, exc)
        raise dr._smoke_fail(
            env, recorder, STEP_RACE, f"the entry cancel raised {type(exc).__name__}"
        ) from None
    recorder.details["cancel_race"] = {
        "pre_status": pre_status,
        "verdict": verdict.value,
        "crossed": crossed(pre_status, verdict),
        "held_at_exchange": scripted,
    }
    record_race_step(env, recorder, pre_status, verdict.value)

    if verdict is CancelVerdict.CANCELED:
        # The cancel won: nothing filled, nothing to protect. The plan is expired and the account
        # checked, by the same production path S06 uses.
        await cancel_resting_entry(env, recorder, first)
        if not await account_clean(env, recorder):
            raise dr.SmokeHalt("account_clean")
        recorder.outcome = dr.OUTCOME_COMPLETE_WITH_GAPS
        return dr.OUTCOME_COMPLETE_WITH_GAPS
    if verdict is not _FILLED_VERDICT:
        raise dr._smoke_fail(
            env, recorder, STEP_RACE, f"the post-cancel query showed {verdict.value}, not a fill"
        )

    # ---- the fill is protected; no orphan, no second entry ----------------------------------- #
    await _assert_protected(env, recorder, first)
    await close_and_clean(env, recorder, first)
    outcome = dr.OUTCOME_COMPLETE if crossed(pre_status, verdict) else dr.OUTCOME_COMPLETE_WITH_GAPS
    recorder.outcome = outcome
    return outcome


async def _settle(task: asyncio.Future[Any]) -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:  # noqa: BLE001, S110 - the scenario is already failing
        pass


def record_race_step(env: Any, recorder: ScenarioRecorder, pre_status: str, verdict: str) -> None:
    """The race step: the env label only when the fill really crossed the cancel (T-25-25)."""
    prefix = "SYNTHETIC: " if env.synthetic else ""
    events = f"the entry was {pre_status} before the cancel; the post-cancel query showed {verdict}"
    if crossed(pre_status, CancelVerdict(verdict)):
        recorder.add_labeled_step(
            STEP_RACE,
            dr.STEP_PASSED,
            prefix + "the fill crossed the cancel: " + events,
            label=label_for(env, injected=False),
        )
        return
    recorder.add_labeled_step(
        STEP_RACE,
        dr.STEP_NOT_REHEARSED,
        prefix + "the fill did not cross the cancel: " + events,
        label=label_for(env, injected=False) if env.synthetic else NOT_OBSERVED,
    )


async def _assert_protected(env: Any, recorder: ScenarioRecorder, first: Any) -> None:
    wiring = env.wiring
    adapter = env.assembly.exchange.adapter

    async def stop_confirmed() -> bool:
        view = wiring.coordinator.protection_of(first.plan_hash)
        return view is not None and view.stop_confirmed_at_utc is not None

    if not await dr._wait_until(env, stop_confirmed):
        raise dr._smoke_fail(env, recorder, STEP_PROTECTED, "the stop was not confirmed by REST")

    async def settled() -> bool:
        view = wiring.coordinator.protection_of(first.plan_hash)
        return view is not None and view.state in (
            ProtectionState.COMPLETE,
            ProtectionState.TP_UNAVAILABLE,
        )

    await dr._wait_until(env, settled)
    view = wiring.coordinator.protection_of(first.plan_hash)
    if view is None or view.state is ProtectionState.CLOSE_REQUIRED:
        state = None if view is None else view.state.value
        raise dr._smoke_fail(env, recorder, STEP_PROTECTED, f"protection state {state}")
    await dr._record_order_ids(
        env, recorder, STEP_PROTECTED, first, legs=(OrderRole.STOP_LOSS.value,)
    )
    positions = [
        p for p in await adapter.snapshot_positions(symbol=dr.SYMBOL) if p.position_amt != _ZERO
    ]
    held = sum((abs(p.position_amt) for p in positions), _ZERO)
    if held <= _ZERO or held > first.quantity:
        raise dr._smoke_fail(
            env, recorder, STEP_PROTECTED, f"position {held}, approved {first.quantity}"
        )
    dr._smoke_record(
        env,
        recorder,
        STEP_PROTECTED,
        dr.STEP_PASSED,
        f"the filled {held} of {first.quantity} has a REST-confirmed stop (state "
        f"{view.state.value}); the cancel answered already filled",
    )

    orders = await adapter.snapshot_open_normal_orders(symbol=dr.SYMBOL)
    own_legs = {
        derive_algo_client_id(plan_hash=first.plan_hash, role=role.value)
        for role in (OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT_1, OrderRole.TAKE_PROFIT_2)
    }
    algos = await adapter.snapshot_open_algo_orders(symbol=dr.SYMBOL)
    foreign = [a for a in algos if a.client_algo_id not in own_legs]
    placed = place_entry_calls(env)
    if orders or foreign or placed != 1:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_NO_ORPHAN,
            f"{len(orders)} resting order(s), {len(foreign)} foreign algo order(s), "
            f"{placed} place_entry call(s)",
        )
    dr._smoke_record(
        env,
        recorder,
        STEP_NO_ORPHAN,
        dr.STEP_PASSED,
        "no resting entry order, no algo order outside the plan's legs, one place_entry",
    )
