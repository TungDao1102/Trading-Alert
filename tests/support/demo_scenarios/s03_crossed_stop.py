"""S03 price crossed the stop: refused before placement, answered -2021 after a fill (plan 25-11).

TEST_ONLY. EXEC-01, D-05, research assumption A2. Two variants run on one process:

(i) Before placement. The mark the pre-placement check reads is `adapter.get_mark_price` (not the
    public reader), so it is answered through `FaultEdge.override`: the real reading with its price
    moved past the stop, armed AFTER the request is derived (the injector reads the same mark) and
    cleared afterwards. The real check refuses at CONFIRM (MARK_PRICE_CROSSED_STOP), nothing is
    sent, the refusal is journaled, and once the plan expires nothing holds the symbol. Because the
    refusal is driven by an injected mark, that step is DEMO_FAULT_INJECTED on Demo, never observed.
(ii) After a fill. The stop request is answered by the exchange with -2021 "would immediately
    trigger". On Demo the stop payload is sent mirrored to the wrong side of the mark and the
    exchange's own answer is recorded by code and exception class name only (DEMO_OBSERVED only if
    it really rejected with -2021; any other answer is NOT_OBSERVED with the code recorded). The
    fake does not model the trigger rule, so there the answer is injected (SYNTHETIC). The reaction
    is S04's: one stop call, B5, one reduce-only close, flat
    (`s04_stop_rejected.assert_b5_reaction`).

Plan 25-11 asked for a `mutate_payload` fault that records the answer; `FaultEdge.mutate_payload`
cannot see the exchange's reply, so the override sends the mutated payload itself and records what
comes back (the override and the mutation are both recorded in the fault ledger).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from scripts import demo_rehearsal as dr
from src.approval.confirm_core import DEMO_CONFIRM_PROFILE
from src.domain.enums import TradePlanStatus
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME, EVENT_PLACEMENT_REFUSED

from tests.support.demo_scenarios import s04_stop_rejected as s04
from tests.support.demo_scenarios.harness import (
    NOT_OBSERVED,
    ScenarioRecorder,
    ensure_clean_start,
    label_for,
    read_account_counts,
)
from tests.support.demo_scenarios.s06_replay import (
    close_and_clean,
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)

STEP_MARK_INJECT = "inject_crossed_mark"
STEP_REFUSED = "refused_at_confirm"
STEP_NOTHING_SENT = "nothing_sent"
STEP_PLAN_RELEASED = "plan_released"
STEP_WRONG_SIDE_INJECT = "inject_wrong_side_stop"
STEP_ANSWER = "stop_answer"

ANSWER_REJECTED = "REJECTED"
ANSWER_ACCEPTED = "ACCEPTED"
ANSWER_ERROR = "ERROR"
SOURCE_INJECTED = "injected"
SOURCE_EXCHANGE = "exchange"
EXPECTED_CODE = s04.REJECTION_CODE
REFUSAL_REASON = "MARK_PRICE_CROSSED_STOP"
EVENT_CONFIRM_REFUSED = DEMO_CONFIRM_PROFILE.event_expired
_JOURNAL_CORRELATION_PREFIX = "live-placement"
_BEYOND = Decimal("0.01")  # the crossed mark is 1% beyond the stop
_TWO = Decimal(2)

# What sends the (mutated) stop payload: `async (env, kwargs) -> placement result`. The default
# mirrors the trigger to the wrong side; the twin swaps it to test the "exchange accepted" branch.
StopSender = Callable[[Any, dict[str, Any]], Awaitable[Any]]


# ---- pure helpers ------------------------------------------------------------------------------ #


def crossed_mark(*, direction: str, stop: Decimal) -> Decimal:
    """A mark price 1% beyond the stop trigger: below it for a LONG, above it for a SHORT."""
    if direction == "LONG":
        return stop * (Decimal(1) - _BEYOND)
    if direction == "SHORT":
        return stop * (Decimal(1) + _BEYOND)
    raise ValueError("direction must be LONG or SHORT")


def wrong_side_trigger(*, side: str, stop: Decimal, mark: Decimal) -> Decimal:
    """The stop trigger mirrored around the mark, on the stop's own decimal precision.

    A SELL stop sits below the mark (its mirror above it), a BUY stop above the mark (its mirror
    below it): the exchange then sees a trigger that would fire immediately. The stop's exponent is
    kept so the price stays on the tick grid for the Demo symbols' tick sizes (0.1 for BTCUSDT).
    """
    if side not in ("SELL", "BUY"):
        raise ValueError("side must be SELL or BUY")
    exponent = stop.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("the stop must be a finite Decimal")
    mirrored = (_TWO * mark - stop).quantize(Decimal(1).scaleb(exponent))
    if mirrored <= 0:
        raise ValueError("the mirrored trigger would not be positive")
    return mirrored


def _protective(side: str, stop: Decimal, mark: Decimal) -> bool:
    """True while the stop is on its protective side of the mark (SELL below, BUY above)."""
    return stop < mark if side == "SELL" else stop > mark


# ---- step recorders ---------------------------------------------------------------------------- #


def record_mark_injection(env: Any, recorder: ScenarioRecorder, detail: str) -> None:
    s04.record_injection_step(env, recorder, detail, name=STEP_MARK_INJECT)


def record_refusal(env: Any, recorder: ScenarioRecorder, reason: str, event_type: str) -> None:
    """The refusal verdict of the real check, driven by an injected mark: FAULT_INJECTED on Demo."""
    s04.record_injection_step(
        env,
        recorder,
        f"the real pre-placement check refused CONFIRM with {reason} ({event_type}) on the "
        "injected mark",
        name=STEP_REFUSED,
    )


def record_answer(env: Any, recorder: ScenarioRecorder, answer: dict[str, Any]) -> None:
    """The exchange's answer to the wrong-side stop: code and class name only (never the text).

    PASSED (the env label) only for a rejection with the expected code -2021; every other answer is
    recorded but is NOT_REHEARSED, and NOT_OBSERVED on Demo (assumption A2).
    """
    recorder.details["stop_answer"] = dict(answer)
    code = answer.get("code")
    text = f"answer {answer['answer']}, code {code}, class {answer.get('exception_class')}"
    prefix = "SYNTHETIC: " if env.synthetic else ""
    if answer["answer"] == ANSWER_REJECTED and code == EXPECTED_CODE:
        recorder.add_labeled_step(
            STEP_ANSWER,
            dr.STEP_PASSED,
            prefix + f"the wrong-side stop was rejected: {text}",
            label=label_for(env, injected=False),
        )
        return
    recorder.add_labeled_step(
        STEP_ANSWER,
        dr.STEP_NOT_REHEARSED,
        prefix + f"the expected rejection {EXPECTED_CODE} was not seen: {text}",
        label=label_for(env, injected=False) if env.synthetic else NOT_OBSERVED,
    )


# ---- reads and the stop sender ----------------------------------------------------------------- #


def placement_rows(
    journal: Any, shadow: Any, trade_plan_id: str
) -> list[tuple[str, dict[str, Any]]]:
    """(event type, payload) of the plan's refusals: at the CONFIRM recheck and at placement.

    The CONFIRM recheck (the approval core) journals `DEMO_CONFIRM_EXPIRED` with
    `rejected_at_confirm` into the shadow journal; the placement service journals
    `LIVE_PLACEMENT_REFUSED` / `LIVE_PLACEMENT_OUTCOME` into the live journal.
    """
    approval_ids: dict[str, None] = {}
    for approval in [*shadow.list_pending_approvals(), *shadow.list_approved_approvals()]:
        if approval.trade_plan_id == trade_plan_id:
            approval_ids[approval.approval_id] = None
    rows: list[tuple[str, dict[str, Any]]] = []
    for approval_id in approval_ids:
        for event in shadow.journal_for_correlation(DEMO_CONFIRM_PROFILE.correlation(approval_id)):
            payload = json.loads(event.payload_json)
            if event.event_type == EVENT_CONFIRM_REFUSED and payload.get("rejected_at_confirm"):
                rows.append((event.event_type, payload))
        for event in journal.list_by_correlation(f"{_JOURNAL_CORRELATION_PREFIX}:{approval_id}"):
            if event.event_type in (EVENT_PLACEMENT_REFUSED, EVENT_PLACEMENT_OUTCOME):
                rows.append((event.event_type, json.loads(event.payload_json)))
    return rows


def _reason_of(event_type: str, payload: dict[str, Any]) -> str | None:
    key = "reason_code" if event_type == EVENT_PLACEMENT_OUTCOME else "reason"
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _is_refusal(event_type: str, payload: dict[str, Any]) -> bool:
    if event_type == EVENT_PLACEMENT_OUTCOME:
        return payload.get("is_no_trade") is True
    return True


async def send_wrong_side(env: Any, kwargs: dict[str, Any]) -> Any:
    """Send the stop to the real exchange with its trigger mirrored to the wrong side of the mark.

    A stop that is already past the mark (a fast market) is sent unchanged: the exchange then
    answers for itself.
    """
    inner = env.faults.inner
    mark = (await inner.get_mark_price(symbol=kwargs["symbol"])).mark_price
    stop, side = kwargs["trigger_price"], kwargs["side"]
    mutated = dict(kwargs)
    if _protective(side, stop, mark):
        mutated["trigger_price"] = wrong_side_trigger(side=side, stop=stop, mark=mark)
    return await inner.place_algo_protective(**mutated)


def _answer_of(env: Any, exc: BaseException, source: str) -> dict[str, Any]:
    facts = env.faults.error_facts(exc)
    code = getattr(facts, "code", None)
    return {
        "answer": ANSWER_REJECTED if code is not None else ANSWER_ERROR,
        "code": code,
        "exception_class": type(exc).__name__,
        "source": source,
    }


# ---- the scenario ------------------------------------------------------------------------------ #


async def run(
    env: Any, recorder: ScenarioRecorder, *, stop_sender: StopSender | None = None
) -> str:
    """Run S03 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`.

    `stop_sender` replaces what sends the stop of variant (ii) (twin tests only); by default the
    fake answers with an injected -2021 and Demo gets the mirrored payload.
    """
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder, stop_sender)
    finally:
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder, stop_sender: StopSender | None) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    await _variant_crossed_mark(env, recorder)
    return await _variant_wrong_side_stop(env, recorder, stop_sender)


async def _variant_crossed_mark(env: Any, recorder: ScenarioRecorder) -> None:
    wiring = env.wiring
    first = await dr._inject(env, recorder, s04.SCENARIO_FILL, "signal")

    async def card_issued() -> bool:
        if wiring.demo_signal is None or wiring.demo_signal.source.pending != 0:
            return False
        row = await dr._smoke_read(env, wiring.stores.entities.get_trade_plan, first.trade_plan_id)
        return row is not None

    if not await dr._wait_until(env, card_issued):
        raise dr._smoke_fail(env, recorder, "card", "the approval card was not issued")
    dr._smoke_record(env, recorder, "card", dr.STEP_PASSED, "the composed pump sent the card")
    await env.owner.act("approve", short_id=first.short_id, note="")

    plan = await dr._smoke_read(env, wiring.stores.entities.get_trade_plan, first.trade_plan_id)
    signal = await dr._smoke_read(env, wiring.stores.shadow.get_signal, first.signal_id)
    if plan is None or signal is None:
        raise dr._smoke_fail(env, recorder, STEP_MARK_INJECT, "the plan or signal was not stored")
    crossed = crossed_mark(direction=signal.direction, stop=plan.stop_loss_price)

    async def moved_mark(**kwargs: Any) -> Any:
        reading = await env.faults.inner.get_mark_price(**kwargs)
        return dataclasses.replace(reading, mark_price=crossed)

    # Armed after the request was derived: the injector read the real mark through the same call.
    env.faults.override("get_mark_price", moved_mark, times=None)
    try:
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
    marks = [c for c in env.faults.calls_to("get_mark_price") if c.get("injected") is True]
    if not marks:
        raise dr._smoke_fail(env, recorder, STEP_MARK_INJECT, "no mark reading was moved")
    record_mark_injection(
        env,
        recorder,
        f"{len(marks)} mark reading(s) moved 1% past the stop at the adapter edge before CONFIRM",
    )

    rows = await env.assembly.executor.read(
        placement_rows, wiring.stores.journal, wiring.stores.shadow, first.trade_plan_id
    )
    event_type, payload = rows[0]
    reason = _reason_of(event_type, payload)
    refused_row = _is_refusal(event_type, payload)
    sent = place_entry_calls(env)
    recorder.details["crossed_mark"] = {
        "event_type": event_type,
        "reason_code": reason,
        "place_entry_calls_after_confirm": sent,
    }
    if not refused_row or reason != REFUSAL_REASON:
        raise dr._smoke_fail(
            env, recorder, STEP_REFUSED, f"the journaled outcome is {event_type} / {reason}"
        )
    record_refusal(env, recorder, reason, event_type)

    adapter = env.assembly.exchange.adapter
    orders = await adapter.snapshot_open_normal_orders(symbol=dr.SYMBOL)
    algos = await adapter.snapshot_open_algo_orders(symbol=dr.SYMBOL)
    positions = [
        p for p in await adapter.snapshot_positions(symbol=dr.SYMBOL) if p.position_amt != 0
    ]
    if sent != 0 or orders or algos or positions:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_NOTHING_SENT,
            f"{sent} place_entry call(s), {len(orders)} order(s), {len(algos)} algo order(s), "
            f"{len(positions)} position(s) after the refusal",
        )
    s04.record_step(
        env, recorder, STEP_NOTHING_SENT, "no entry was sent and the account holds nothing"
    )

    # The refused plan stays APPROVED until it expires; the official transition frees the symbol
    # (the step `scripts/demo_clear.py` makes), then nothing holds it.
    await env.assembly.executor.write(
        wiring.stores.entities.transition_trade_plan,
        first.trade_plan_id,
        TradePlanStatus.EXPIRED,
        now_utc=env.clock(),
    )
    for _ in range(dr.SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()
    counts = await read_account_counts(env)
    if not counts.clean:
        raise dr._smoke_fail(
            env, recorder, STEP_PLAN_RELEASED, f"the symbol is still held ({counts.text()})"
        )
    s04.record_step(
        env,
        recorder,
        STEP_PLAN_RELEASED,
        "after the plan expired no approval, order or position holds the symbol",
    )


async def _variant_wrong_side_stop(
    env: Any, recorder: ScenarioRecorder, stop_sender: StopSender | None
) -> str:
    answers: list[dict[str, Any]] = []
    injected_answer = env.synthetic and stop_sender is None

    async def answer_stop(**kwargs: Any) -> Any:
        try:
            if injected_answer:
                raise s04.injected_rejection()
            result = await (stop_sender or send_wrong_side)(env, dict(kwargs))
        except Exception as exc:  # noqa: BLE001 - recorded by code and class name, then re-raised
            answers.append(
                _answer_of(env, exc, SOURCE_INJECTED if injected_answer else SOURCE_EXCHANGE)
            )
            raise
        answers.append({"answer": ANSWER_ACCEPTED, "code": None, "source": SOURCE_EXCHANGE})
        return result

    env.faults.override(s04.STOP_METHOD, answer_stop, times=1)
    first = await place_approved_entry(env, recorder, s04.SCENARIO_FILL)
    await s04.drive_fill(env, first)

    def accepted() -> bool:
        return bool(answers) and answers[0]["answer"] == ANSWER_ACCEPTED

    state = await s04.observe_close_window(env, recorder, first, stop_if=accepted)
    if not answers:
        raise dr._smoke_fail(env, recorder, STEP_WRONG_SIDE_INJECT, "no stop placement was seen")
    s04.record_injection_step(
        env,
        recorder,
        "the stop request was answered through the adapter edge: "
        + (
            "an injected -2021 (the fake has no trigger rule)"
            if injected_answer
            else "its payload was sent mirrored to the wrong side of the mark"
        ),
        name=STEP_WRONG_SIDE_INJECT,
    )
    record_answer(env, recorder, answers[0])
    if state is None:
        return await _accepted_cleanup(env, recorder, first)
    await s04.wait_flat(env, recorder, first, s04.STEP_CLOSE)
    await s04.assert_b5_reaction(env, recorder, first)
    await s04.expire_plan_and_leave_safe_mode(env, recorder, first)
    complete = (
        answers[0]["answer"] == ANSWER_REJECTED
        and answers[0]["code"] == EXPECTED_CODE
        and recorder.details["close_required_window"]["observed"]
    )
    outcome = dr.OUTCOME_COMPLETE if complete else dr.OUTCOME_COMPLETE_WITH_GAPS
    recorder.outcome = outcome
    return outcome


async def _accepted_cleanup(env: Any, recorder: ScenarioRecorder, first: Any) -> str:
    """The exchange accepted the stop (assumption A2 failed): finish by the production close."""
    from src.execution.protection import ProtectionState

    async def settled() -> bool:
        view = env.wiring.coordinator.protection_of(first.plan_hash)
        return view is not None and (
            view.stop_confirmed_at_utc is not None or view.state is ProtectionState.FLAT
        )

    await dr._wait_until(env, settled)
    view = env.wiring.coordinator.protection_of(first.plan_hash)
    if view is not None and view.state is not ProtectionState.FLAT:
        await close_and_clean(env, recorder, first)
    else:
        await s04.expire_plan_and_leave_safe_mode(env, recorder, first)
    recorder.outcome = dr.OUTCOME_COMPLETE_WITH_GAPS
    return dr.OUTCOME_COMPLETE_WITH_GAPS
