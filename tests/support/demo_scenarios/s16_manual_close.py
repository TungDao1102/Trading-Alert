"""S16 manual close outside the system (plan 25-16; G2-016, G4-035, EXEC-02, D-06).

TEST_ONLY. A system plan is filled and protected (stop and both take-profit legs). A test actor,
outside the system, then closes the whole position with a reduce-only MARKET order, exactly what
an owner closing the position in the exchange UI does. The REAL coordinator and reconcile loop of
the composed process must end flat, report no divergence, enter no SAFE_MODE, send no close of
their own and leave no orphan protective leg.

The scenario `leaves_state` (catalog flag): an actor position that was not closed or an approved
plan that was not expired would block the next run. A failed step names the way out
(`scripts/demo_clear.py`, see `LEAVES_STATE`).

The actor: its client id starts with `t25a-` (`actor_client_id`), which no system id family can
match. It calls the adapter the edge wraps (`env.faults.inner`), so the edge ledger holds only what
the system process sent (it must hold no close). The few lines of the actor are copied from S15 on
purpose; S15's private helper is not imported. Actor steps carry the env label and the detail
"test actor"; nothing is injected on Demo and nothing is modelled, so the Demo steps are
DEMO_OBSERVED.

1. A "fill" request is placed through the production path, filled, and protected: the stop is open.
2. The actor closes the whole position (reduce-only MARKET, its own client id, the position's own
   quantity). Twin only (A3, labelled SYNTHETIC): the fake ends the closePosition legs EXPIRED, as
   the 2026-10-22 Demo record says Binance did (`LEGS_EXPIRE`); `LEGS_STAY` ends nothing.
3. The coordinator records the external close (state FLAT) and the system sends no close order.
4. The reconcile reports flat: no divergence tick, no SAFE_MODE.
5. No protective leg of the symbol stays open (T-25-40). The final status of the stop and of both
   take-profit legs is read from the exchange and recorded verbatim by status code (ABSENT when the
   exchange no longer lists the id), together with how many cancels the system sent for each.
6. A new request: the closed plan's approval holds the symbol until its expiry, so the sender may
   refuse the request (the code defines that wait; what it did is recorded). The operator step
   `APPROVED -> EXPIRED` (the one `scripts/demo_clear.py` makes) ends it, a new request is placed
   and cancelled, and the account ends clean.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from scripts import demo_rehearsal as dr
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState
from src.live.approval_sender import EVENT_REQUEST_REFUSED

from tests.support.demo_scenarios.harness import (
    CLEAR_INSTRUCTION,
    SYNTHETIC,
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
    label_for,
)
from tests.support.demo_scenarios.s04_stop_rejected import (
    close_placements,
    drive_fill,
    protection_rows,
    record_step,
)
from tests.support.demo_scenarios.s06_replay import (
    cancel_resting_entry,
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)
from tests.support.demo_scenarios.s08_stream_loss import expire_plan, leave_safe_mode, ticks
from tests.support.demo_scenarios.s14_safe_mode import journal_rows

SCENARIO_FAR = "far"
SCENARIO_FILL = "fill"
ACTOR_ID_PREFIX = "t25a-"
LEGS_EXPIRE = "expire_close_position"
LEGS_STAY = "stay"
LEGS_EXCHANGE = "exchange"  # Demo: nothing is modelled, the status is read from the exchange
TWIN_LEG_STATUS = "EXPIRED"
LEG_ROLES = (
    OrderRole.STOP_LOSS.value,
    OrderRole.TAKE_PROFIT_1.value,
    OrderRole.TAKE_PROFIT_2.value,
)

STEP_PROTECTED = "system_position_protected"
STEP_ACTOR_CLOSED = "actor_closes_the_position_outside_the_system"
STEP_TWIN_LEGS = "twin_ends_close_position_legs_expired"
STEP_FLAT_RECORDED = "system_records_the_external_close"
STEP_RECONCILE_FLAT = "reconcile_reports_flat_no_divergence"
STEP_LEGS_READ = "leg_final_status_read_from_the_exchange"
STEP_NO_ORPHAN = "no_orphan_leg_remains"
STEP_NEW_REQUEST = "new_request_after_the_manual_close"
STEP_ENTRY_AFTER = "entry_placed_after_the_plan_expired"
STEP_SAFE_MODE_LEFT = "safe_mode_left_after_the_gap"

LEAVES_STATE = (
    "S16 leaves state: close any open BTCUSDT position and algo order in the Binance Demo UI "
    f"(the actor's client ids start with '{ACTOR_ID_PREFIX}'), then: {CLEAR_INSTRUCTION}"
)

_RECONCILE_CORRELATION = "reconcile_loop"
_SETTLE_TICKS = 2
_MIN_TICKS_AFTER_CLOSE = 2


# ---- the actor (a local copy of the S15 pattern) ----------------------------------------------- #


def actor_client_id(role: str, stamp: int, number: int) -> str:
    """An actor client id: `t25a-<role>-<stamp>-<n>`, at most 36 characters, never a system id."""
    client_id = f"{ACTOR_ID_PREFIX}{role}-{stamp}-{number}"
    if len(client_id) > 36:
        raise ValueError("an actor client id must be at most 36 characters")
    return client_id


def record_actor_step(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A step the test actor made: the env label (never injected), the detail says so."""
    prefix = "SYNTHETIC: " if env.synthetic else ""
    recorder.add_labeled_step(
        name,
        dr.STEP_PASSED,
        f"{prefix}test actor: {detail}",
        label=label_for(env, injected=False),
    )


def record_leg_status_step(
    env: Any, recorder: ScenarioRecorder, statuses: Mapping[str, str | None]
) -> None:
    """The legs' final status as the exchange answered it, verbatim by status code."""
    prefix = "SYNTHETIC: " if env.synthetic else ""
    text = ", ".join(
        f"{role}={'ABSENT' if status is None else status}" for role, status in statuses.items()
    )
    recorder.add_labeled_step(
        STEP_LEGS_READ,
        dr.STEP_PASSED,
        f"{prefix}final status of the protective legs: {text}",
        label=label_for(env, injected=False),
    )


class _Actor:
    """The test actor: its order goes to the adapter the edge wraps, outside the system process."""

    def __init__(self, env: Any, recorder: ScenarioRecorder) -> None:
        self._env = env
        self._recorder = recorder
        self._adapter = env.faults.inner
        self._stamp = int(env.clock().timestamp())
        self._count = 0
        self.facts: dict[str, Any] = recorder.details.setdefault("actor", {"actions": []})

    async def position(self) -> Decimal:
        """The signed position of the symbol (one-way: one row)."""
        rows = await self._adapter.snapshot_positions(symbol=dr.SYMBOL)
        return sum((row.position_amt for row in rows), Decimal(0))

    async def close_position(self) -> str:
        """A reduce-only MARKET close of the whole position, with the actor's own client id."""
        position = await self.position()
        side = "SELL" if position > 0 else "BUY"
        quantity = abs(position)
        self._count += 1
        client_id = actor_client_id("close", self._stamp, self._count)
        await self._adapter.place_market_close(
            symbol=dr.SYMBOL,
            side=side,
            position_side="BOTH",
            quantity=quantity,
            new_client_order_id=client_id,
        )
        self.facts["actions"].append(
            {"role": "close", "client_id": client_id, "side": side, "quantity": str(quantity)}
        )
        return client_id


def end_close_position_legs(fake: Any) -> list[str]:
    """Twin only (A3): the closePosition legs end EXPIRED, as the Demo record says Binance did.

    An explicit-quantity leg (TP1) is not covered by that record and stays open.
    """
    ended: list[str] = []
    for client_id, record in list(fake.open_algos.items()):
        if record.close_position:
            fake.open_algos.pop(client_id)
            record.status = TWIN_LEG_STATUS
            record.updated_at_utc = fake.now_utc
            fake.algo_history[client_id] = record
            ended.append(client_id)
    return ended


# ---- reads ------------------------------------------------------------------------------------- #


async def _tick_payloads(env: Any, since: int) -> list[dict[str, Any]]:
    rows = await journal_rows(env, _RECONCILE_CORRELATION, "RECONCILE_TICK")
    return [json.loads(row.payload_json) for row in rows[since:]]


async def _tick_count(env: Any) -> int:
    return len(await journal_rows(env, _RECONCILE_CORRELATION, "RECONCILE_TICK"))


async def _open_algo_ids(env: Any) -> list[str]:
    """The client algo ids of every open protective order of the symbol."""
    adapter = env.assembly.exchange.adapter
    rows = await adapter.snapshot_open_algo_orders(symbol=dr.SYMBOL)
    return [str(row.client_algo_id) for row in rows]


def _cancels_naming(env: Any, client_id: str) -> int:
    return len(
        [
            c
            for c in env.faults.calls_to("cancel_algo_order")
            if c.get("kwargs", {}).get("client_algo_id") == client_id
        ]
    )


def _fail(env: Any, recorder: ScenarioRecorder, step: str, text: str) -> dr.SmokeHalt:
    return dr._smoke_fail(env, recorder, step, text)


def _name_the_cleanup(recorder: ScenarioRecorder) -> None:
    """The scenario leaves state: the failed step and the details say how to clear it."""
    recorder.details["leaves_state"] = LEAVES_STATE
    for step in reversed(recorder.steps):
        if step["status"] == dr.STEP_FAILED:
            step["detail"] = f"{step['detail']} | {LEAVES_STATE}"
            return


# ---- the scenario ------------------------------------------------------------------------------ #


async def run(env: Any, recorder: ScenarioRecorder, *, legs: str = LEGS_EXPIRE) -> str:
    """Run S16 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`.

    `legs` selects the twin's model of what the exchange does with the protective legs
    (`LEGS_EXPIRE` or `LEGS_STAY`); a Demo env refuses anything else, because Demo answers for
    itself.
    """
    if legs not in (LEGS_EXPIRE, LEGS_STAY):
        raise ValueError(f"unknown leg variant {legs!r}")
    if not env.synthetic and legs != LEGS_EXPIRE:
        raise ValueError("the leg variants are twin-only: Demo ends the legs itself")
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    actor = _Actor(env, recorder)
    try:
        return await _sequence(env, recorder, actor, legs)
    except dr.SmokeHalt:
        _name_the_cleanup(recorder)
        raise
    finally:
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder, actor: _Actor, legs: str) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    facts: dict[str, Any] = recorder.details.setdefault("manual_close", {})
    facts["legs_model"] = legs if env.synthetic else LEGS_EXCHANGE
    recorder.details["leaves_state"] = LEAVES_STATE

    first = await place_approved_entry(env, recorder, SCENARIO_FILL)
    await drive_fill(env, first)
    leg_ids = {
        role: derive_algo_client_id(plan_hash=first.plan_hash, role=role) for role in LEG_ROLES
    }
    position = await _protected(env, recorder, actor, facts, first, leg_ids)

    ticks_before = await _tick_count(env)
    await _actor_closes(env, recorder, actor, facts, position, leg_ids, legs)
    await _flat_is_recorded(env, recorder, facts, first)
    outcome = await _reconcile_is_flat(env, recorder, facts, ticks_before)
    await _no_orphan(env, recorder, facts, leg_ids)
    await _new_request(env, recorder, facts, first)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = outcome
    return outcome


async def _protected(
    env: Any,
    recorder: ScenarioRecorder,
    actor: _Actor,
    facts: dict[str, Any],
    first: Any,
    leg_ids: Mapping[str, str],
) -> Any:
    async def protected() -> bool:
        view = env.wiring.coordinator.protection_of(first.plan_hash)
        return view is not None and view.state in (
            ProtectionState.COMPLETE,
            ProtectionState.TP_UNAVAILABLE,
        )

    if not await dr._wait_until(env, protected):
        raise _fail(env, recorder, STEP_PROTECTED, "the system position did not become protected")
    await ticks(env, _SETTLE_TICKS)
    position = await actor.position()
    adapter = env.assembly.exchange.adapter
    open_now = [row.client_algo_id for row in await adapter.snapshot_open_algo_orders()]
    stop_id = leg_ids[OrderRole.STOP_LOSS.value]
    facts["system_position"] = str(abs(position))
    facts["legs_open_before"] = {role: leg in open_now for role, leg in leg_ids.items()}
    if position == 0 or stop_id not in open_now:
        raise _fail(
            env,
            recorder,
            STEP_PROTECTED,
            f"position {position}, legs open {json.dumps(facts['legs_open_before'])}",
        )
    record_step(
        env,
        recorder,
        STEP_PROTECTED,
        f"the system position {abs(position)} is protected; legs open before the close: "
        f"{json.dumps(facts['legs_open_before'])}",
    )
    return position


async def _actor_closes(
    env: Any,
    recorder: ScenarioRecorder,
    actor: _Actor,
    facts: dict[str, Any],
    position: Any,
    leg_ids: Mapping[str, str],
    legs: str,
) -> None:
    close_id = await actor.close_position()
    quantity = abs(position)
    facts["actor"] = {
        "client_id": close_id,
        "side": "SELL" if position > 0 else "BUY",
        "quantity": str(quantity),
    }

    async def flat() -> bool:
        return await actor.position() == 0

    if not await dr._wait_until(env, flat):
        raise _fail(
            env,
            recorder,
            STEP_ACTOR_CLOSED,
            f"the position is {await actor.position()} after the actor's reduce-only close",
        )
    # Twin only, no tick in between: the exchange ends the closePosition legs as Demo did (A3).
    if env.synthetic and legs == LEGS_EXPIRE:
        ended = end_close_position_legs(env.fake)
        facts["twin_expired_legs"] = ended
        recorder.add_labeled_step(
            STEP_TWIN_LEGS,
            dr.STEP_PASSED,
            f"SYNTHETIC: the twin ended {len(ended)} closePosition leg(s) {TWIN_LEG_STATUS} to "
            "model the Demo record of 2026-10-22 (A3: both legs ended EXPIRED, none orphaned); "
            "the explicit-quantity TP1 is not covered by that record and was left open",
            label=SYNTHETIC,
        )
    record_actor_step(
        env,
        recorder,
        STEP_ACTOR_CLOSED,
        f"closed the whole position with a reduce-only MARKET {facts['actor']['side']} "
        f"{quantity} (client id {close_id}); the system was not asked to place anything",
    )
    recorder.record_ids(
        STEP_ACTOR_CLOSED, client_order_ids=[close_id], algo_client_ids=list(leg_ids.values())
    )


async def _flat_is_recorded(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], first: Any
) -> None:
    async def flat() -> bool:
        view = env.wiring.coordinator.protection_of(first.plan_hash)
        return view is not None and view.state is ProtectionState.FLAT

    if not await dr._wait_until(env, flat):
        view = env.wiring.coordinator.protection_of(first.plan_hash)
        raise _fail(
            env,
            recorder,
            STEP_FLAT_RECORDED,
            f"the plan did not end FLAT after the external close "
            f"(state {None if view is None else view.state.value})",
        )
    rows = await env.assembly.executor.read(
        protection_rows, env.wiring.stores.journal, first.plan_hash
    )
    last = rows[-1]
    facts["flat"] = {
        "protection_state": last["to"],
        "transition_reason": last["reason"],
        "evidence": last["evidence"],
        "system_close_orders": len(close_placements(env)),
    }
    if facts["flat"]["system_close_orders"] != 0:
        raise _fail(
            env,
            recorder,
            STEP_FLAT_RECORDED,
            f"the system sent {facts['flat']['system_close_orders']} close order(s) for a "
            "position that was already flat",
        )
    record_step(
        env,
        recorder,
        STEP_FLAT_RECORDED,
        f"the plan moved to {last['to']} (reason {last['reason']}, evidence {last['evidence']}); "
        "the system sent no close of its own",
    )


async def _reconcile_is_flat(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], since: int
) -> str:
    """Ticks after the close: flat, no divergence, no SAFE_MODE; a gap is recorded, never hidden."""

    async def settled() -> bool:
        payloads = await _tick_payloads(env, since)
        return len(payloads) >= _MIN_TICKS_AFTER_CLOSE and payloads[-1]["divergence_count"] == 0

    if not await dr._wait_until(env, settled):
        raise _fail(env, recorder, STEP_RECONCILE_FLAT, "the reconcile never reported a clean tick")
    payloads = await _tick_payloads(env, since)
    divergent = [p for p in payloads if p["divergence_count"]]
    kinds = sorted({kind for p in divergent for kind in p["counts"]})
    facts["reconcile"] = {
        "ticks_after_close": len(payloads),
        "divergent_ticks": len(divergent),
        "kinds": kinds,
        "safe_mode_after": bool(env.wiring.safe_mode.in_safe_mode),
    }
    if not divergent and not facts["reconcile"]["safe_mode_after"]:
        record_step(
            env,
            recorder,
            STEP_RECONCILE_FLAT,
            f"{len(payloads)} reconcile tick(s) after the close, none with a divergence, "
            "SAFE_MODE not entered",
        )
        return dr.OUTCOME_COMPLETE
    prefix = "SYNTHETIC: " if env.synthetic else ""
    recorder.add_labeled_step(
        STEP_RECONCILE_FLAT,
        dr.STEP_NOT_REHEARSED,
        f"{prefix}{len(divergent)} of {len(payloads)} tick(s) after the manual close reported a "
        f"divergence ({', '.join(kinds)}); SAFE_MODE {facts['reconcile']['safe_mode_after']}",
        label=label_for(env, injected=False),
    )
    if env.wiring.safe_mode.in_safe_mode:
        await leave_safe_mode(env, recorder, STEP_SAFE_MODE_LEFT)
    return dr.OUTCOME_COMPLETE_WITH_GAPS


async def _no_orphan(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], leg_ids: Mapping[str, str]
) -> None:
    async def none_open() -> bool:
        return not await _open_algo_ids(env)

    if not await dr._wait_until(env, none_open):
        left = await _open_algo_ids(env)
        facts["open_algo_orders_after"] = len(left)
        raise _fail(
            env,
            recorder,
            STEP_NO_ORPHAN,
            f"{len(left)} protective leg(s) still open after the manual close and the reconcile "
            "(an orphan, T-25-40)",
        )
    facts["open_algo_orders_after"] = 0
    adapter = env.assembly.exchange.adapter
    statuses: dict[str, str | None] = {}
    facts["legs"] = {}
    for role, client_id in leg_ids.items():
        probe = await adapter.query_algo_order_by_client(client_algo_id=client_id)
        status = str(probe.algo_status) if probe.found else None
        statuses[role] = status
        facts["legs"][role] = {
            "client_algo_id": client_id,
            "final_status": status,
            "system_cancel_calls": _cancels_naming(env, client_id),
        }
    record_leg_status_step(env, recorder, statuses)
    record_step(
        env,
        recorder,
        STEP_NO_ORPHAN,
        "no protective leg of the symbol is open after the manual close; the system sent "
        + ", ".join(
            f"{facts['legs'][r]['system_cancel_calls']} cancel(s) for {r}" for r in statuses
        ),
    )


async def _new_request(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], first: Any
) -> None:
    """A new request after the manual close: what the code does is recorded, then the plan ends."""
    wiring = env.wiring
    request = await dr._inject(env, recorder, SCENARIO_FAR, "request_after_manual_close")
    correlation = f"demo-request:{request.signal_id}"

    async def answered() -> bool:
        if await journal_rows(env, correlation, EVENT_REQUEST_REFUSED):
            return True
        if wiring.demo_signal is None or wiring.demo_signal.source.pending != 0:
            return False
        row = await dr._smoke_read(
            env, wiring.stores.entities.get_trade_plan, request.trade_plan_id
        )
        return row is not None

    if not await dr._wait_until(env, answered):
        raise _fail(
            env, recorder, STEP_NEW_REQUEST, "the new request was neither refused nor given a card"
        )
    refused_rows = await journal_rows(env, correlation, EVENT_REQUEST_REFUSED)
    if refused_rows:
        payload = json.loads(refused_rows[0].payload_json)
        facts["new_request"] = {
            "refused": True,
            "reason": payload.get("reason"),
            "sources": list(payload.get("sources", [])),
        }
        detail = (
            f"the new request was refused {payload.get('reason')} (sources "
            f"{', '.join(facts['new_request']['sources'])}): the closed plan's approval holds the "
            "symbol until its expiry, which the code defines; the operator step expires it"
        )
    else:
        facts["new_request"] = {"refused": False, "reason": None, "sources": []}
        detail = "the new request got its card at once: the closed plan did not hold the symbol"
        await expire_plan(env, request)
    record_step(env, recorder, STEP_NEW_REQUEST, detail)
    await expire_plan(env, first)

    before = place_entry_calls(env)
    later = await place_approved_entry(env, recorder, SCENARIO_FAR)
    placed = place_entry_calls(env) == before + 1
    await cancel_resting_entry(env, recorder, later)
    facts["entry_after"] = {"placed": placed, "cancelled": True}
    if not placed:
        raise _fail(env, recorder, STEP_ENTRY_AFTER, "the new request sent no entry")
    record_step(
        env,
        recorder,
        STEP_ENTRY_AFTER,
        "after the first plan expired a new request was placed, then cancelled by its client id",
    )
