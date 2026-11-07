"""S15 foreign order and doubled position (plan 25-16; EXEC-02, D-02, D-07).

TEST_ONLY. A test actor, outside the system, makes orders on the account and the REAL reconcile
loop of the composed process must see them: it journals the divergence, enters SAFE_MODE and
alerts. The scenario runs two flows in one process (flow 1, then flow 2).

The scenario `leaves_state` (catalog flag): SAFE_MODE is durable on Demo and an actor position is
real, so the run ends by cleaning up and leaving SAFE_MODE through the operator exit itself. A
failed step names the way out (`scripts/demo_clear.py`, see `LEAVES_STATE`).

The actor: client ids start with `t25a-` (`actor_client_id`), which no system id family (`x-`,
`xa-`, `xc-`) can match, so the compare reports FOREIGN_ORDER and not UNTRACKED_SYSTEM_ORDER. Its
prices and its smallest valid quantity come from the exchange filters the process loaded
(`actor_sizing`), never from a literal. It calls the adapter the edge wraps (`env.faults.inner`),
so the edge ledger keeps counting only what the system process sends, and the system is never
asked to place or cancel anything of the actor's. Actor steps carry the env label (DEMO_OBSERVED
on Demo, SYNTHETIC on the twin) and the detail "test actor"; nothing is injected, so no step is
DEMO_FAULT_INJECTED. On the twin the actor's marketable order is filled by `fake.fill`; on Demo
the exchange fills it.

Flow 1 runs first: the twin's shared `deliver_fill` helper expects the fake's ledger to hold
exactly one `place_entry` (the system's), so the actor's first order must come after it. The
order is irrelevant on Demo.

Flow 1, doubled position:
1. A system plan is filled and its stop REST-confirmed (production path); the reconcile is clean.
2. The actor adds the smallest valid position in the same direction. The next tick journals
   DOUBLED_POSITION (more than the plan's quantity), enters SAFE_MODE, alerts and tells the
   coordinator (D-07), which only re-checks. The system closes nothing, sends no second entry and
   keeps the stop.
3. `/safemode_exit` is refused (COMPARE_NOT_CLEAN).
4. The actor reduces its own part with a reduce-only close of its own quantity; a clean tick
   follows and SAFE_MODE still stands.
5. The system position is exited through its production path (`operator_close_position`), the
   account is checked clean, SAFE_MODE is left through the operator exit, and a new request is
   placed and cancelled (entries are restored).

Flow 2, foreign order (flat account):
1. The actor places one far resting BUY LIMIT with an actor id.
2. The next reconcile tick journals FOREIGN_ORDER, enters SAFE_MODE FOREIGN_ORDER and alerts. The
   kind is ALERT_ONLY for good (D-02): the system neither cancels nor sweeps the order.
3. A new request gets no card: the approval sender's symbol rule (RESTING_ENTRY_ORDER) refuses it
   before any CONFIRM exists, so nothing can be placed.
4. `/safemode_exit` is refused (COMPARE_NOT_CLEAN, journaled); SAFE_MODE stays.
5. The actor cancels its own order by its own id; a clean tick follows and SAFE_MODE still stands
   (the reconcile loop never leaves it, D-15); `/safemode_exit` plus `/confirm` leaves it.
6. A new request gets a card again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

from scripts import demo_rehearsal as dr
from src.execution.order_ids import OrderRole, derive_algo_client_id
from src.execution.placement import PRICE_ROUND_DOWN, quantize_price
from src.execution.protection import ProtectionState
from src.live.approval_sender import EVENT_REQUEST_REFUSED, SOURCE_RESTING_ENTRY

from tests.support.demo_scenarios.harness import (
    CLEAR_INSTRUCTION,
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
    label_for,
)
from tests.support.demo_scenarios.s04_stop_rejected import (
    close_placements,
    drive_fill,
    record_step,
)
from tests.support.demo_scenarios.s06_replay import (
    cancel_resting_entry,
    close_and_clean,
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)
from tests.support.demo_scenarios.s08_stream_loss import (
    card_and_approve,
    expire_plan,
    leave_safe_mode,
    ticks,
)
from tests.support.demo_scenarios.s14_safe_mode import journal_rows

SCENARIO_FAR = "far"
SCENARIO_FILL = "fill"
ACTOR_ID_PREFIX = "t25a-"
KIND_FOREIGN_ORDER = "FOREIGN_ORDER"
KIND_DOUBLED_POSITION = "DOUBLED_POSITION"
EXIT_REFUSAL = "COMPARE_NOT_CLEAN"

STEP_FOREIGN_PLACED = "actor_places_foreign_order"
STEP_FOREIGN_DETECTED = "foreign_order_detected_safe_mode_entered"
STEP_FOREIGN_UNTOUCHED = "foreign_order_left_untouched_by_the_system"
STEP_FOREIGN_NO_CARD = "new_request_gets_no_card_while_the_foreign_order_rests"
STEP_FOREIGN_EXIT_REFUSED = "safemode_exit_refused_while_the_foreign_order_rests"
STEP_FOREIGN_REMOVED = "actor_cancels_its_own_order"
STEP_FOREIGN_CLEAN = "reconcile_clean_safe_mode_stands_after_the_actor_cancel"
STEP_FOREIGN_EXIT = "foreign_flow_safe_mode_left"
STEP_FOREIGN_CARD_AGAIN = "new_request_gets_a_card_after_the_exit"
STEP_DOUBLED_BASELINE = "system_position_protected_and_reconcile_clean"
STEP_DOUBLED_PLACED = "actor_adds_a_position"
STEP_DOUBLED_DETECTED = "doubled_position_detected_safe_mode_entered"
STEP_DOUBLED_EXIT_REFUSED = "safemode_exit_refused_while_the_position_is_doubled"
STEP_DOUBLED_REDUCED = "actor_reduces_its_own_part"
STEP_DOUBLED_CLEAN = "reconcile_clean_safe_mode_stands_after_the_actor_reduce"
STEP_DOUBLED_EXIT = "doubled_flow_safe_mode_left"
STEP_ENTRY_RESTORED = "entry_restored_after_the_exit"

LEAVES_STATE = (
    "S15 leaves state: close the actor's open BTCUSDT order and position (client ids starting "
    f"'{ACTOR_ID_PREFIX}') and any system position in the Binance Demo UI, leave SAFE_MODE with "
    f"/safemode_exit and /confirm, then: {CLEAR_INSTRUCTION}"
)

_RECONCILE_CORRELATION = "reconcile_loop"
_SAFE_MODE_CORRELATION = "reconcile_safe_mode"
_ALERT_CORRELATION = "operational_alerts"
_SAFE_MODE_ENTER_EVENTS = ("SAFE_MODE_ENTER", "SAFE_MODE_REENTER")
_FAR_BAND_FRACTION = dr.FAR_BAND_FRACTION  # the injector's own fraction of the PERCENT_PRICE band
_SETTLE_TICKS = 2


# ---- the actor --------------------------------------------------------------------------------- #


def actor_client_id(role: str, stamp: int, number: int) -> str:
    """An actor client id: `t25a-<role>-<stamp>-<n>`, at most 36 characters, never a system id."""
    client_id = f"{ACTOR_ID_PREFIX}{role}-{stamp}-{number}"
    if len(client_id) > 36:
        raise ValueError("an actor client id must be at most 36 characters")
    return client_id


@dataclass(frozen=True)
class ActorSizing:
    """What the actor sends: two prices on the tick grid and the smallest valid quantity."""

    price_below: Decimal
    price_above: Decimal
    quantity: Decimal

    def facts(self) -> dict[str, str]:
        return {
            "price_below": str(self.price_below),
            "price_above": str(self.price_above),
            "quantity": str(self.quantity),
        }


def actor_sizing(filters: Any, mark_price: Decimal) -> ActorSizing:
    """Prices and the smallest valid quantity from the loaded filters (no literal).

    `price_below` and `price_above` sit half way into the PERCENT_PRICE band on each side of the
    mark (the injector's `far` and `fill` entries), rounded down to the tick. The quantity is the
    smallest multiple of the step that is at least the minimum quantity and reaches the minimum
    notional at the LOWER price, so both prices are valid.
    """
    up = filters.percent_price_multiplier_up
    down = filters.percent_price_multiplier_down
    if up is None or down is None:
        raise ValueError("the PERCENT_PRICE band is missing from the exchange filters")
    tick = filters.price_tick_size
    step = filters.quantity_step_size
    below = quantize_price(
        price=mark_price * (Decimal(1) - (Decimal(1) - down) * _FAR_BAND_FRACTION),
        price_tick_size=tick,
        direction=PRICE_ROUND_DOWN,
    )
    above = quantize_price(
        price=mark_price * (Decimal(1) + (up - Decimal(1)) * _FAR_BAND_FRACTION),
        price_tick_size=tick,
        direction=PRICE_ROUND_DOWN,
    )
    raw = max(filters.min_quantity, filters.min_notional / below)
    quantity = (raw / step).to_integral_value(rounding=ROUND_CEILING) * step
    if not Decimal(0) < below < mark_price < above or quantity * below < filters.min_notional:
        raise ValueError("the actor's prices or quantity are not valid under the filters")
    return ActorSizing(price_below=below, price_above=above, quantity=quantity)


def record_actor_step(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A step the test actor made: the env label (never injected), the detail says so."""
    prefix = "SYNTHETIC: " if env.synthetic else ""
    recorder.add_labeled_step(
        name,
        dr.STEP_PASSED,
        f"{prefix}test actor: {detail}",
        label=label_for(env, injected=False),
    )


def _actor_step(
    env: Any, recorder: ScenarioRecorder, name: str, client_id: str, detail: str
) -> None:
    """An actor step plus its client id in the evidence, so the owner can find it in the UI."""
    record_actor_step(env, recorder, name, detail)
    recorder.record_ids(name, client_order_ids=[client_id])


class _Actor:
    """The test actor: its orders go to the adapter the edge wraps, outside the system process."""

    def __init__(self, env: Any, recorder: ScenarioRecorder) -> None:
        self._env = env
        self._recorder = recorder
        self._adapter = env.faults.inner
        self._stamp = int(env.clock().timestamp())
        self._count = 0
        self._sizing: ActorSizing | None = None
        self.resting: list[str] = []
        self.facts: dict[str, Any] = recorder.details.setdefault("actor", {"actions": []})

    async def size(self) -> ActorSizing:
        if self._sizing is None:
            filters = dr.select_symbol(
                await self._env.assembly.exchange.public.exchange_info([dr.SYMBOL])
            )
            mark = (await self._adapter.get_mark_price(symbol=dr.SYMBOL)).mark_price
            self._sizing = actor_sizing(filters, mark)
            self.facts["sizing"] = {
                **self._sizing.facts(),
                "mark": str(mark),
                "min_notional": str(filters.min_notional),
                "quantity_step": str(filters.quantity_step_size),
            }
        return self._sizing

    def _next_id(self, role: str) -> str:
        self._count += 1
        return actor_client_id(role, self._stamp, self._count)

    def _log(self, role: str, client_id: str, side: str, quantity: Decimal, price: Any) -> None:
        self.facts["actions"].append(
            {
                "role": role,
                "client_id": client_id,
                "side": side,
                "quantity": str(quantity),
                "price": None if price is None else str(price),
            }
        )

    async def rest(self) -> str:
        """One far resting BUY LIMIT with an actor id."""
        sizing = await self.size()
        client_id = self._next_id("rest")
        await self._adapter.place_entry(
            symbol=dr.SYMBOL,
            side="BUY",
            position_side="BOTH",
            time_in_force="GTC",
            quantity=sizing.quantity,
            price=sizing.price_below,
            new_client_order_id=client_id,
        )
        self.resting.append(client_id)
        self._log("rest", client_id, "BUY", sizing.quantity, sizing.price_below)
        return client_id

    async def cancel(self, client_id: str) -> None:
        await self._adapter.cancel_normal_order(symbol=dr.SYMBOL, orig_client_order_id=client_id)
        if client_id in self.resting:
            self.resting.remove(client_id)
        self._log("cancel", client_id, "-", Decimal(0), None)

    async def add_position(self, side: str) -> str:
        """One marketable LIMIT of the smallest valid quantity (the twin fills it by hand)."""
        sizing = await self.size()
        price = sizing.price_above if side == "BUY" else sizing.price_below
        client_id = self._next_id("add")
        await self._adapter.place_entry(
            symbol=dr.SYMBOL,
            side=side,
            position_side="BOTH",
            time_in_force="GTC",
            quantity=sizing.quantity,
            price=price,
            new_client_order_id=client_id,
        )
        self.resting.append(client_id)
        self._log("add", client_id, side, sizing.quantity, price)
        if self._env.synthetic:
            self._env.fake.fill(client_id)
        return client_id

    async def reduce(self, side: str, quantity: Decimal) -> str:
        """A reduce-only MARKET close of the actor's own quantity."""
        client_id = self._next_id("reduce")
        await self._adapter.place_market_close(
            symbol=dr.SYMBOL,
            side=side,
            position_side="BOTH",
            quantity=quantity,
            new_client_order_id=client_id,
        )
        self._log("reduce", client_id, side, quantity, None)
        return client_id

    async def position(self) -> Decimal:
        """The signed position of the symbol (one-way: one row)."""
        rows = await self._adapter.snapshot_positions(symbol=dr.SYMBOL)
        return sum((row.position_amt for row in rows), Decimal(0))

    async def is_open(self, client_id: str) -> bool:
        orders = await self._adapter.snapshot_open_normal_orders(symbol=dr.SYMBOL)
        return any(order.client_order_id == client_id for order in orders)

    async def cleanup(self) -> None:
        """Best effort: cancel what the actor still rests, by its own ids. Never a position."""
        for client_id in list(self.resting):
            try:
                await self.cancel(client_id)
            except Exception:  # noqa: BLE001, S110 - best effort at the end of a scenario
                pass


# ---- reads ------------------------------------------------------------------------------------- #


async def _tick_payloads(env: Any, since: int) -> list[dict[str, Any]]:
    rows = await journal_rows(env, _RECONCILE_CORRELATION, "RECONCILE_TICK")
    return [json.loads(row.payload_json) for row in rows[since:]]


async def _tick_count(env: Any) -> int:
    return len(await journal_rows(env, _RECONCILE_CORRELATION, "RECONCILE_TICK"))


async def _enter_count(env: Any) -> int:
    return len(await journal_rows(env, _SAFE_MODE_CORRELATION, _SAFE_MODE_ENTER_EVENTS))


async def _enter_reasons(env: Any, since: int) -> list[str]:
    rows = await journal_rows(env, _SAFE_MODE_CORRELATION, _SAFE_MODE_ENTER_EVENTS)
    return sorted({str(json.loads(row.payload_json).get("reason")) for row in rows[since:]})


def _alert_payloads(journal: Any) -> list[dict[str, Any]]:
    rows = journal.list_by_correlation(_ALERT_CORRELATION)
    return [json.loads(r.payload_json) for r in rows if r.event_type == "OPERATIONAL_ALERT"]


async def _alerts_for(env: Any, reason: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = await env.assembly.executor.read(
        _alert_payloads, env.wiring.stores.journal
    )
    return [p for p in payloads if p.get("reason") == reason]


def _protection_state(env: Any, plan_hash: str) -> str | None:
    view = env.wiring.coordinator.protection_of(plan_hash)
    return None if view is None else str(view.state.value)


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


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S15 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    actor = _Actor(env, recorder)
    try:
        return await _sequence(env, recorder, actor)
    except dr.SmokeHalt:
        _name_the_cleanup(recorder)
        raise
    finally:
        await actor.cleanup()
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder, actor: _Actor) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    recorder.details["leaves_state"] = LEAVES_STATE
    await _doubled_flow(env, recorder, actor)
    await _foreign_flow(env, recorder, actor)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE


# ---- shared checks ----------------------------------------------------------------------------- #


async def _detect(
    env: Any,
    recorder: ScenarioRecorder,
    *,
    kind: str,
    step: str,
    ticks_before: int,
    enters_before: int,
    alert_event: str,
) -> dict[str, Any]:
    """Wait for a tick that reports `kind` with SAFE_MODE on; the facts of what the loop did."""

    async def reported() -> bool:
        payloads = await _tick_payloads(env, ticks_before)
        hit = any(p.get("counts", {}).get(kind, 0) >= 1 for p in payloads)
        return hit and bool(env.wiring.safe_mode.in_safe_mode)

    if not await dr._wait_until(env, reported):
        raise _fail(
            env,
            recorder,
            step,
            f"no reconcile tick reported {kind} with SAFE_MODE on (SAFE_MODE "
            f"{bool(env.wiring.safe_mode.in_safe_mode)})",
        )
    payloads = await _tick_payloads(env, ticks_before)
    tick = next(p for p in payloads if p.get("counts", {}).get(kind, 0) >= 1)
    alerts = await _alerts_for(env, kind)
    return {
        "counts": tick["counts"],
        "safe_mode_reasons": tick["safe_mode_reasons"],
        "enter_reasons": await _enter_reasons(env, enters_before),
        "delegated": tick["delegated"],
        "alerts": len(alerts),
        "alert_event": alert_event,
        "alert_reason": kind,
        "action_failures": tick["action_failures"],
    }


async def _exit_is_refused(
    env: Any, recorder: ScenarioRecorder, step: str, facts: dict[str, Any]
) -> None:
    """`/safemode_exit` with `/confirm` while the divergence stands: refused, journaled."""
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
        or len(rows) != before + 1
        or EXIT_REFUSAL not in refusals
    ):
        raise _fail(
            env,
            recorder,
            step,
            f"exit facts {json.dumps(facts['exit_refused'])}; expected one refusal naming "
            f"{EXIT_REFUSAL} and SAFE_MODE on",
        )
    record_step(
        env,
        recorder,
        step,
        f"/safemode_exit with /confirm was refused ({', '.join(refusals)}) and journaled; "
        "SAFE_MODE stays on",
    )


async def _clean_tick_safe_mode_stands(
    env: Any, recorder: ScenarioRecorder, step: str, facts: dict[str, Any], key: str, since: int
) -> None:
    """After the actor cleaned up: a tick with no divergence, and SAFE_MODE still on (D-15)."""

    async def clean() -> bool:
        payloads = await _tick_payloads(env, since)
        return bool(payloads) and payloads[-1].get("divergence_count") == 0

    if not await dr._wait_until(env, clean):
        raise _fail(env, recorder, step, "no clean reconcile tick followed the actor's clean-up")
    payloads = await _tick_payloads(env, since)
    facts[key] = {
        "last_tick_divergences": payloads[-1]["divergence_count"],
        "in_safe_mode": bool(env.wiring.safe_mode.in_safe_mode),
    }
    if not facts[key]["in_safe_mode"]:
        raise _fail(env, recorder, step, "SAFE_MODE was left without the operator exit")
    record_step(
        env,
        recorder,
        step,
        "the reconcile tick after the clean-up reports no divergence; SAFE_MODE still stands "
        "until the operator exits",
    )


async def _operator_exit(
    env: Any, recorder: ScenarioRecorder, step: str, facts: dict[str, Any]
) -> None:
    before = len(await journal_rows(env, _SAFE_MODE_CORRELATION, "SAFE_MODE_EXIT"))
    await leave_safe_mode(env, recorder, step)
    rows = await journal_rows(env, _SAFE_MODE_CORRELATION, "SAFE_MODE_EXIT")
    operator = str(json.loads(rows[-1].payload_json).get("operator_id", "")) if rows else ""
    facts["exit"] = {
        "in_safe_mode_after": bool(env.wiring.safe_mode.in_safe_mode),
        "exit_rows": len(rows) - before,
        "exit_operator_recorded": bool(operator),
    }
    if facts["exit"]["exit_rows"] != 1 or not facts["exit"]["exit_operator_recorded"]:
        raise _fail(
            env,
            recorder,
            step,
            f"exit rows {json.dumps(facts['exit'])}; expected one with an operator",
        )


# ---- flow A: a foreign resting order ----------------------------------------------------------- #


async def _foreign_flow(env: Any, recorder: ScenarioRecorder, actor: _Actor) -> None:
    facts: dict[str, Any] = recorder.details.setdefault("foreign_order", {})
    sent_before = place_entry_calls(env)
    ticks_before = await _tick_count(env)
    enters_before = await _enter_count(env)

    client_id = await actor.rest()
    facts["client_id"] = client_id
    sizing = await actor.size()
    if place_entry_calls(env) != sent_before:
        raise _fail(env, recorder, STEP_FOREIGN_PLACED, "the actor's order passed the system edge")
    _actor_step(
        env,
        recorder,
        STEP_FOREIGN_PLACED,
        client_id,
        f"placed one far resting BUY LIMIT {sizing.quantity} at {sizing.price_below} with "
        f"client id {client_id}; the system process was not asked to place anything",
    )

    facts["detected"] = await _detect(
        env,
        recorder,
        kind=KIND_FOREIGN_ORDER,
        step=STEP_FOREIGN_DETECTED,
        ticks_before=ticks_before,
        enters_before=enters_before,
        alert_event="FOREIGN_ORDER",
    )
    if KIND_FOREIGN_ORDER not in facts["detected"]["enter_reasons"]:
        raise _fail(
            env,
            recorder,
            STEP_FOREIGN_DETECTED,
            f"SAFE_MODE was entered for {facts['detected']['enter_reasons']}, not "
            f"{KIND_FOREIGN_ORDER}",
        )
    record_step(
        env,
        recorder,
        STEP_FOREIGN_DETECTED,
        f"the reconcile tick journaled {KIND_FOREIGN_ORDER}, entered SAFE_MODE "
        f"({', '.join(facts['detected']['enter_reasons'])}) and sent "
        f"{facts['detected']['alerts']} alert(s)",
    )

    await ticks(env, _SETTLE_TICKS)
    still_open = await actor.is_open(client_id)
    named = [
        c
        for c in env.faults.calls_to("cancel_normal_order")
        if c.get("kwargs", {}).get("orig_client_order_id") == client_id
    ]
    facts["left_untouched"] = {
        "still_open_after_ticks": still_open,
        "system_cancel_calls_naming_it": len(named),
    }
    if not still_open or named:
        raise _fail(
            env,
            recorder,
            STEP_FOREIGN_UNTOUCHED,
            f"the foreign order is {'open' if still_open else 'gone'} and the system sent "
            f"{len(named)} cancel call(s) for it; it must never touch what it did not make",
        )
    record_step(
        env,
        recorder,
        STEP_FOREIGN_UNTOUCHED,
        "after further ticks the foreign order still rests and the system sent no cancel for it "
        "(ALERT_ONLY, D-02)",
    )

    await _no_card(env, recorder, facts, sent_before)
    await _exit_is_refused(env, recorder, STEP_FOREIGN_EXIT_REFUSED, facts)

    since = await _tick_count(env)
    await actor.cancel(client_id)
    if await actor.is_open(client_id):
        raise _fail(env, recorder, STEP_FOREIGN_REMOVED, "the actor's order is still open")
    _actor_step(
        env,
        recorder,
        STEP_FOREIGN_REMOVED,
        client_id,
        f"cancelled its own order {client_id} by that id; the system was not asked to cancel",
    )
    await _clean_tick_safe_mode_stands(
        env, recorder, STEP_FOREIGN_CLEAN, facts, "after_actor_cancel", since
    )
    await _operator_exit(env, recorder, STEP_FOREIGN_EXIT, facts)

    request = await card_and_approve(env, recorder)
    facts["card_after_exit"] = {"issued": True}
    record_step(
        env,
        recorder,
        STEP_FOREIGN_CARD_AGAIN,
        "after the actor's order is gone and SAFE_MODE is left, a new request gets its card and "
        "its APPROVE",
    )
    await expire_plan(env, request)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")


async def _no_card(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], sent_before: int
) -> None:
    """A new request while the foreign order rests: refused by the sender's symbol rule."""
    request = await dr._inject(env, recorder, SCENARIO_FAR, "request_while_foreign_order_rests")
    correlation = f"demo-request:{request.signal_id}"

    async def refused() -> bool:
        return bool(await journal_rows(env, correlation, EVENT_REQUEST_REFUSED))

    if not await dr._wait_until(env, refused):
        raise _fail(
            env,
            recorder,
            STEP_FOREIGN_NO_CARD,
            "the request was not refused: a card may be open while a foreign order rests",
        )
    (row, *_rest) = await journal_rows(env, correlation, EVENT_REQUEST_REFUSED)
    payload = json.loads(row.payload_json)
    facts["no_card"] = {
        "refused": True,
        "reason": payload.get("reason"),
        "sources": list(payload.get("sources", [])),
        "place_entry_calls_before": place_entry_calls(env) - sent_before,
        "place_entry_calls_after": place_entry_calls(env) - sent_before,
    }
    if SOURCE_RESTING_ENTRY not in facts["no_card"]["sources"] or place_entry_calls(env) != (
        sent_before
    ):
        raise _fail(
            env,
            recorder,
            STEP_FOREIGN_NO_CARD,
            f"refusal facts {json.dumps(facts['no_card'])}; expected {SOURCE_RESTING_ENTRY} and "
            "no entry sent",
        )
    record_step(
        env,
        recorder,
        STEP_FOREIGN_NO_CARD,
        f"a new request got no card: refused {payload.get('reason')} by the sender's symbol rule "
        f"(sources {', '.join(facts['no_card']['sources'])}), so no CONFIRM exists and nothing "
        "can be placed",
    )


# ---- flow B: a doubled position ---------------------------------------------------------------- #


async def _doubled_flow(env: Any, recorder: ScenarioRecorder, actor: _Actor) -> None:
    facts: dict[str, Any] = recorder.details.setdefault("doubled_position", {})
    first = await place_approved_entry(env, recorder, SCENARIO_FILL)
    await drive_fill(env, first)

    async def protected() -> bool:
        view = env.wiring.coordinator.protection_of(first.plan_hash)
        return view is not None and view.state in (
            ProtectionState.COMPLETE,
            ProtectionState.TP_UNAVAILABLE,
        )

    if not await dr._wait_until(env, protected):
        raise _fail(
            env,
            recorder,
            STEP_DOUBLED_BASELINE,
            f"the system position did not reach a protected state "
            f"({_protection_state(env, first.plan_hash)})",
        )
    await ticks(env, _SETTLE_TICKS)
    system_position = await actor.position()
    last = (await _tick_payloads(env, 0))[-1]
    facts["system_position"] = str(system_position)
    facts["baseline"] = {
        "protection_state": _protection_state(env, first.plan_hash),
        "last_tick_divergences": last["divergence_count"],
        "in_safe_mode": bool(env.wiring.safe_mode.in_safe_mode),
    }
    if (
        system_position == 0
        or facts["baseline"]["last_tick_divergences"] != 0
        or facts["baseline"]["in_safe_mode"]
    ):
        raise _fail(
            env,
            recorder,
            STEP_DOUBLED_BASELINE,
            f"baseline {json.dumps(facts['baseline'])}, position {system_position}",
        )
    record_step(
        env,
        recorder,
        STEP_DOUBLED_BASELINE,
        f"the system position {system_position} is protected "
        f"({facts['baseline']['protection_state']}) and the reconcile reports no divergence",
    )

    side = "BUY" if system_position > 0 else "SELL"
    sizing = await actor.size()
    sent_before = place_entry_calls(env)
    ticks_before = await _tick_count(env)
    enters_before = await _enter_count(env)
    client_id = await actor.add_position(side)
    total = system_position + (sizing.quantity if side == "BUY" else -sizing.quantity)

    async def doubled() -> bool:
        return await actor.position() == total

    if not await dr._wait_until(env, doubled):
        raise _fail(
            env,
            recorder,
            STEP_DOUBLED_PLACED,
            f"the position is {await actor.position()}, expected {total}",
        )
    actor.resting.remove(client_id)
    facts["actor_quantity"] = str(sizing.quantity)
    facts["total_position"] = str(abs(total))
    facts["system_position"] = str(abs(system_position))
    _actor_step(
        env,
        recorder,
        STEP_DOUBLED_PLACED,
        client_id,
        f"added {side} {sizing.quantity} (client id {client_id}) on top of the system position "
        f"{abs(system_position)}; the position is now {abs(total)}",
    )

    facts["detected"] = await _detect(
        env,
        recorder,
        kind=KIND_DOUBLED_POSITION,
        step=STEP_DOUBLED_DETECTED,
        ticks_before=ticks_before,
        enters_before=enters_before,
        alert_event="DIVERGENCE",
    )
    stop_id = derive_algo_client_id(plan_hash=first.plan_hash, role=OrderRole.STOP_LOSS.value)
    algos = await env.assembly.exchange.adapter.snapshot_open_algo_orders(symbol=dr.SYMBOL)
    facts["detected"].update(
        {
            "system_close_orders": len(close_placements(env)),
            "place_entry_calls_unchanged": place_entry_calls(env) == sent_before,
            "stop_still_open": any(a.client_algo_id == stop_id for a in algos),
            "protection_state_after": _protection_state(env, first.plan_hash),
        }
    )
    detected = facts["detected"]
    if (
        KIND_DOUBLED_POSITION not in detected["enter_reasons"]
        or detected["system_close_orders"] != 0
        or not detected["place_entry_calls_unchanged"]
        or not detected["stop_still_open"]
    ):
        raise _fail(
            env,
            recorder,
            STEP_DOUBLED_DETECTED,
            f"detection facts {json.dumps(detected, default=str)}",
        )
    record_step(
        env,
        recorder,
        STEP_DOUBLED_DETECTED,
        f"the reconcile tick journaled {KIND_DOUBLED_POSITION}, entered SAFE_MODE "
        f"({', '.join(detected['enter_reasons'])}) and alerted; the coordinator was told "
        f"({detected['delegated']}) and the system closed nothing, sent no entry and kept the stop",
    )

    await _exit_is_refused(env, recorder, STEP_DOUBLED_EXIT_REFUSED, facts)

    since = await _tick_count(env)
    side_out = "SELL" if side == "BUY" else "BUY"
    reduce_id = await actor.reduce(side_out, sizing.quantity)

    async def reduced() -> bool:
        return await actor.position() == system_position

    if not await dr._wait_until(env, reduced):
        raise _fail(
            env,
            recorder,
            STEP_DOUBLED_REDUCED,
            f"the position is {await actor.position()}, expected {system_position}",
        )
    _actor_step(
        env,
        recorder,
        STEP_DOUBLED_REDUCED,
        reduce_id,
        f"reduced its own part with a reduce-only MARKET close {sizing.quantity} (client id "
        f"{reduce_id}); the position is back to the system's {abs(system_position)}",
    )
    await _clean_tick_safe_mode_stands(
        env, recorder, STEP_DOUBLED_CLEAN, facts, "after_reduce", since
    )

    await close_and_clean(env, recorder, first)  # the system's production exit, then clean
    await _operator_exit(env, recorder, STEP_DOUBLED_EXIT, facts)

    restored_before = place_entry_calls(env)
    request = await place_approved_entry(env, recorder, SCENARIO_FAR)
    placed = place_entry_calls(env) == restored_before + 1
    await cancel_resting_entry(env, recorder, request)
    facts["entry_restored"] = {"placed": placed, "cancelled": True}
    if not placed:
        raise _fail(env, recorder, STEP_ENTRY_RESTORED, "the new request sent no entry")
    record_step(
        env,
        recorder,
        STEP_ENTRY_RESTORED,
        "after the operator exit a new request was placed again, then cancelled by its client id",
    )
