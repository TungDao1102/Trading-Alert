"""S02 partial fill: the stop follows the first fill and is sized from what filled (plan 25-10).

TEST_ONLY. EXEC-01, D055/D079 (fill-driven protection). One "fill" request is approved and
confirmed; the entry then fills in part (the twin scripts that through the `partial_fill` hook) or
in full (Binance Demo, where a partial fill cannot be forced: `scripts/demo_probe.py` lists
`partial_fill_attempt` as able to stay NOT_OBSERVED for ever). Either way the coordinator must

* place the stop (the `closePosition` STOP_MARKET) after the first fill and confirm it by REST;
* block new entries while the position has no confirmed stop (twin only: the stop placement is held
  at the exchange for one observation; on Demo nothing is delayed);
* cancel the unfilled remainder of the entry (D-12), so the position stays what filled;
* size TP1 and TP2 from the REST position, never above the filled (or approved) quantity.

The run ends flat through the production operator close, the plan expired (DOMN-04) and
`account_clean` PASSED.

Labels: the step `partial_fill` is the env label when a partial fill really happened, NOT_OBSERVED
(reason in the detail) on Demo when the entry filled in one trade, and SYNTHETIC on the fake with
no hook. A step is never DEMO_OBSERVED for an event that did not happen (T-25-25).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from scripts import demo_rehearsal as dr
from src.domain.enums import OrderRole, TradePlanStatus
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState
from src.live.wiring import TASK_PROTECTION

from tests.support.demo_scenarios.harness import (
    NOT_OBSERVED,
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
    label_for,
)
from tests.support.demo_scenarios.s06_replay import (
    place_approved_entry,
    shutdown,
    start_evidence,
)
from tests.support.virtual_time import yield_to_loop

SCENARIO_FILL = "fill"
STEP_PARTIAL_FILL = "partial_fill"
STEP_STOP_AFTER_FIRST_FILL = "stop_after_first_fill"
STEP_BLOCKS_WHILE_UNPROTECTED = "blocks_new_entries_while_unprotected"
STEP_REMAINDER_CANCELLED = "remainder_cancelled"
STEP_TP_SIZING = "tp_sized_from_position"
STEP_CLOSE = "close_cleanup"

# A twin hook: scripts ONE partial fill of the request on the exchange and on the user-data stream,
# and returns the filled quantity. Demo passes none (the exchange fills when it fills).
PartialFill = Callable[[Any], Awaitable[Decimal]]

_ZERO = Decimal(0)
_HOLD_POLL_ROUNDS = 5000


async def run(
    env: Any, recorder: ScenarioRecorder, *, partial_fill: PartialFill | None = None
) -> str:
    """Run S02 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder, partial_fill)
    finally:
        await shutdown(env)


def _protection(env: Any, first: Any) -> Any:
    return env.wiring.coordinator.protection_of(first.plan_hash)


async def _sequence(env: Any, recorder: ScenarioRecorder, partial_fill: PartialFill | None) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    wiring = env.wiring
    first = await place_approved_entry(env, recorder, SCENARIO_FILL)
    approved_quantity = first.quantity
    adapter = env.assembly.exchange.adapter
    stop_id = derive_algo_client_id(plan_hash=first.plan_hash, role=OrderRole.STOP_LOSS.value)

    # ---- the first fill: scripted on the fake, the exchange's own on Demo -------------------- #
    if partial_fill is not None:
        # The stop placement is held at the exchange for one look, so the window between "the stop
        # was sent" and "REST confirmed it" can be observed; it is released right after.
        env.faults.hold("place_algo_protective")
        scripted = await partial_fill(first)
        recorder.details["scripted_partial_quantity"] = dr._jsonable(scripted)
        specs = {spec.name: spec for spec in wiring.specs}
        protection_pass = asyncio.ensure_future(specs[TASK_PROTECTION].run())
        for _ in range(_HOLD_POLL_ROUNDS):
            if env.faults.held("place_algo_protective") or protection_pass.done():
                break
            await yield_to_loop()
        try:
            await _blocks_while_unconfirmed(env, recorder, first)
        finally:
            if env.faults.held("place_algo_protective"):
                env.faults.release("place_algo_protective")
            await protection_pass
    else:
        if env.deliver_fill is not None:
            await env.deliver_fill(first)
        _record_not_observable_window(env, recorder)

    async def filled() -> bool:
        view = _protection(env, first)
        return view is not None and view.state not in (
            ProtectionState.AWAITING_FILL,
            ProtectionState.ENTRY_ENDED_NO_FILL,
        )

    if not await dr._wait_until(env, filled):
        raise dr._smoke_fail(env, recorder, "stream_fill", "no fill reached the coordinator")
    first_probe = await adapter.query_order_by_client(
        symbol=dr.SYMBOL, orig_client_order_id=first.entry_client_id
    )
    executed = first_probe.executed_quantity
    partial_seen = executed is not None and _ZERO < executed < approved_quantity
    _record_partial_step(env, recorder, partial_seen, executed, approved_quantity)

    async def stop_confirmed() -> bool:
        view = _protection(env, first)
        return view is not None and view.stop_confirmed_at_utc is not None

    if not await dr._wait_until(env, stop_confirmed):
        raise dr._smoke_fail(
            env, recorder, STEP_STOP_AFTER_FIRST_FILL, "the stop was not confirmed by REST"
        )
    stop_calls = [
        c for c in env.faults.calls_to("place_algo_protective") if _is(c, "client_algo_id", stop_id)
    ]
    await dr._record_order_ids(
        env, recorder, "stop_confirmed", first, legs=(OrderRole.STOP_LOSS.value,)
    )
    if len(stop_calls) != 1:
        raise dr._smoke_fail(
            env, recorder, STEP_STOP_AFTER_FIRST_FILL, f"{len(stop_calls)} stop placements"
        )
    dr._smoke_record(
        env,
        recorder,
        STEP_STOP_AFTER_FIRST_FILL,
        dr.STEP_PASSED,
        "one stop placed after the first fill and confirmed by REST",
    )

    # ---- the remainder is cancelled, the legs are sized from the position -------------------- #
    async def complete() -> bool:
        view = _protection(env, first)
        return view is not None and view.state in (
            ProtectionState.COMPLETE,
            ProtectionState.TP_UNAVAILABLE,
        )

    await dr._wait_until(env, complete)
    final_probe = await adapter.query_order_by_client(
        symbol=dr.SYMBOL, orig_client_order_id=first.entry_client_id
    )
    if final_probe.status not in ("CANCELED", "FILLED"):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_REMAINDER_CANCELLED,
            f"the entry is still {final_probe.status} after protection",
        )
    dr._smoke_record(
        env,
        recorder,
        STEP_REMAINDER_CANCELLED,
        dr.STEP_PASSED,
        f"the entry ended {final_probe.status}, executed quantity {final_probe.executed_quantity}",
    )
    positions = [
        p for p in await adapter.snapshot_positions(symbol=dr.SYMBOL) if p.position_amt != _ZERO
    ]
    held_quantity = sum((abs(p.position_amt) for p in positions), _ZERO)
    if held_quantity <= _ZERO or held_quantity > approved_quantity:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_TP_SIZING,
            f"position {held_quantity} against the approved quantity {approved_quantity}",
        )
    view = _protection(env, first)
    gaps = 0
    if view is not None and view.state is ProtectionState.COMPLETE:
        legs = _tp_legs(env, first)
        if legs is None or legs[0] >= held_quantity or not legs[1]:
            raise dr._smoke_fail(
                env,
                recorder,
                STEP_TP_SIZING,
                f"take-profit legs {legs} against the position {held_quantity}",
            )
        dr._smoke_record(
            env,
            recorder,
            STEP_TP_SIZING,
            dr.STEP_PASSED,
            f"TP1 {legs[0]} sized from the position {held_quantity} (approved "
            f"{approved_quantity}); TP2 closes the rest",
        )
    else:
        gaps += 1
        dr._smoke_record(
            env,
            recorder,
            STEP_TP_SIZING,
            dr.STEP_NOT_REHEARSED,
            "take-profit legs not placed: "
            + str(None if view is None else (view.state.value, view.last_reason)),
        )
    if not partial_seen or partial_fill is None:
        gaps += 1

    # ---- close, expire the plan, the account is clean ------------------------------------- #
    from src.execution.manager import operator_close_position

    closed = await operator_close_position(
        coordinator=wiring.coordinator, plan_hash=first.plan_hash, operator_id=dr.OPERATOR_ID
    )
    if not closed.accepted:
        raise dr._smoke_fail(env, recorder, STEP_CLOSE, f"close refused: {closed.code}")

    async def flat() -> bool:
        view = _protection(env, first)
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
    outcome = dr.OUTCOME_COMPLETE_WITH_GAPS if gaps else dr.OUTCOME_COMPLETE
    recorder.outcome = outcome
    return outcome


def _is(call: dict[str, Any], key: str, value: str) -> bool:
    return call.get("kwargs", {}).get(key) == value


def _tp_legs(env: Any, first: Any) -> tuple[Decimal, bool] | None:
    """TP1's explicit quantity and whether TP2 is a closePosition leg (None: a leg is missing)."""
    ids = {
        role: derive_algo_client_id(plan_hash=first.plan_hash, role=role)
        for role in (OrderRole.TAKE_PROFIT_1.value, OrderRole.TAKE_PROFIT_2.value)
    }
    calls = {
        role: [
            c
            for c in env.faults.calls_to("place_algo_protective")
            if c["kwargs"]["client_algo_id"] == algo_id
        ]
        for role, algo_id in ids.items()
    }
    tp1, tp2 = calls[OrderRole.TAKE_PROFIT_1.value], calls[OrderRole.TAKE_PROFIT_2.value]
    if len(tp1) != 1 or len(tp2) != 1 or tp1[0]["kwargs"]["quantity"] is None:
        return None
    return Decimal(str(tp1[0]["kwargs"]["quantity"])), bool(tp2[0]["kwargs"]["close_position"])


def _record_partial_step(
    env: Any,
    recorder: ScenarioRecorder,
    partial_seen: bool,
    executed: Decimal | None,
    approved: Decimal,
) -> None:
    """The label says what happened: the env label for a real partial fill, else NOT_OBSERVED."""
    if partial_seen:
        recorder.add_labeled_step(
            STEP_PARTIAL_FILL,
            dr.STEP_PASSED,
            ("SYNTHETIC: " if env.synthetic else "")
            + f"the entry was filled in part when the coordinator saw it: {executed} of {approved}",
            label=label_for(env, injected=False),
        )
        return
    reason = (
        f"the entry filled in one observation (executed {executed} of {approved}); a partial "
        "fill cannot be forced on Demo, so it was not observed"
    )
    recorder.add_labeled_step(
        STEP_PARTIAL_FILL,
        dr.STEP_NOT_REHEARSED,
        ("SYNTHETIC: " if env.synthetic else "") + reason,
        label=label_for(env, injected=False) if env.synthetic else NOT_OBSERVED,
    )


async def _blocks_while_unconfirmed(env: Any, recorder: ScenarioRecorder, first: Any) -> None:
    """After the stop was sent and before REST confirmed it, no new entry may open (RISK-04)."""
    view = _protection(env, first)
    if not env.faults.held("place_algo_protective") or view is None:
        raise dr._smoke_fail(
            env, recorder, STEP_BLOCKS_WHILE_UNPROTECTED, "the coordinator never sent the stop"
        )
    if view.stop_confirmed_at_utc is not None:
        raise dr._smoke_fail(
            env, recorder, STEP_BLOCKS_WHILE_UNPROTECTED, "the stop was confirmed while in flight"
        )
    if (
        view.state is not ProtectionState.UNPROTECTED
        or not env.wiring.coordinator.blocks_new_entries()
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_BLOCKS_WHILE_UNPROTECTED,
            f"state {view.state.value}: new entries were not blocked while the stop is unconfirmed",
        )
    dr._smoke_record(
        env,
        recorder,
        STEP_BLOCKS_WHILE_UNPROTECTED,
        dr.STEP_PASSED,
        f"stop in flight, not confirmed (state {view.state.value}): blocks_new_entries() is True",
    )


def _record_not_observable_window(env: Any, recorder: ScenarioRecorder) -> None:
    """On Demo the scheduler runs by its own cadence, so the unconfirmed window is not stepped."""
    recorder.add_labeled_step(
        STEP_BLOCKS_WHILE_UNPROTECTED,
        dr.STEP_NOT_REHEARSED,
        ("SYNTHETIC: " if env.synthetic else "")
        + "the window between the stop and its REST confirmation is not stepped here; the twin "
        "asserts it",
        label=label_for(env, injected=False) if env.synthetic else NOT_OBSERVED,
    )
