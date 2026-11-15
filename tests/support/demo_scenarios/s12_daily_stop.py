"""S12 DAILY_STOP (plan 25-15; OPS-01, D033, D-12, D-14).

TEST_ONLY. A loss beyond the daily stop cannot be produced on Demo on demand, so the loss rows are
fed through the day-risk reader edge and the real day service, store and placement path react.

Run S12 LAST in an owner session: DAILY_STOP is latched in the day store for the rest of the UTC day
(`leaves_state`), so every later CONFIRM on that Demo account is refused until 00:00 UTC. The
scenario refuses to start when the day is already latched. The injected rows also stay among the
day's loss components in the database; they are the record of the injection.

1. Baseline: the day row the process persisted (its base equity) and the stop threshold the loaded
   parameters give (`daily_loss_stop_threshold` rate times that base). Nothing here is a literal.
2. A request is approved and confirmed: a GTD LIMIT entry rests on the exchange (far from the mark).
3. Injected trigger (DEMO_FAULT_INJECTED): `user_trades_in_window` is overridden at the adapter
   edge and returns one loss fill sized 10 percent beyond the stop threshold (Decimal, computed from
   the values of step 1). The process's own `day_risk_backfill` task reads it and folds it.
4. The day service is asked to evaluate the day (`LiveDayRiskService.evaluate`, the call the
   placement path makes at every CONFIRM; no scheduled task evaluates a day whose loss is known, so
   the scenario makes the call, which is why this step is labelled as injected). The verdict is
   DAILY_STOP and the latch is persisted before it returns (D-14).
5. The resting entry: D033 and D-12 say the resting entries are cancelled, the stops kept and a
   DAILY_STOP alert sent (`enforce_daily_state`). No live composition calls it (finding F1 of plan
   25-15), so the entry stays and no alert is journaled. The step records what was observed:
   PASSED if the entry was cancelled and the alert journaled, NOT_REHEARSED otherwise.
6. The operator cancels the resting entry (the production step), a new request is approved (the
   card and the APPROVE are not blocked by DAILY_STOP, observed) and its CONFIRM is refused
   `DAILY_STOP_BLOCK` with nothing sent.

Only the loss rows and the scenario's evaluate call are injected triggers; the verdict, the latch,
the refusal and the untouched resting entry are the real process's reactions (env label).
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from scripts import demo_rehearsal as dr
from src.adapters.binance_usdm import UserTradeRow
from src.domain.enums import DailyState
from src.risk.daily_loss import DayRiskState, day_thresholds, utc_day_of, utc_day_start

from tests.support.demo_scenarios.harness import (
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
    label_for,
)
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
    placement_decision,
    ticks,
)

SCENARIO_FAR = "far"
TRADES_METHOD = "user_trades_in_window"
CANCEL_METHOD = "cancel_normal_order"
STOP_KEY = "daily_loss_stop_threshold"
DAILY_STOP_REASON = "DAILY_STOP_BLOCK"
ALERT_EVENT = "DAILY_STOP"
BEYOND_THE_STOP = Decimal("1.1")  # the injected loss, as a multiple of the stop threshold
# TEST_ONLY ids of the injected fill; far above any real Demo order or trade id of the account.
INJECTED_ORDER_ID = 9_100_000_001
INJECTED_TRADE_ID = 9_100_000_101

STEP_PRECONDITION = "precondition_day_not_latched"
STEP_BASELINE = "day_state_baseline"
STEP_INJECT = "inject_losses_beyond_the_daily_stop"
STEP_LOSS_KNOWN = "loss_known_to_the_day_service"
STEP_DAILY_STOP = "day_state_daily_stop_latched"
STEP_RESTING_ENTRY = "resting_entry_handled_at_daily_stop"
STEP_CONFIRM_REFUSED = "confirm_refused_daily_stop"

_ALERT_CORRELATION = "operational_alerts"
_ONE_SECOND = timedelta(seconds=1)


def record_inject(env: Any, recorder: ScenarioRecorder, detail: str) -> None:
    """The injected loss rows: DEMO_FAULT_INJECTED on Demo, never DEMO_OBSERVED."""
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


async def persisted_day(env: Any) -> DayRiskState | None:
    """Today's persisted day row (a read through the process's executor), or None."""
    day = utc_day_of(env.clock())
    row: DayRiskState | None = await env.assembly.executor.read(
        lambda store: store.get_day(day), env.wiring.stores.day_risk
    )
    return row


def _alert_rows(journal: Any) -> list[dict[str, Any]]:
    rows = journal.list_by_correlation(_ALERT_CORRELATION)
    payloads = [
        json.loads(row.payload_json) for row in rows if row.event_type == "OPERATIONAL_ALERT"
    ]
    return [p for p in payloads if p.get("event") == ALERT_EVENT]


async def daily_stop_alerts(env: Any) -> int:
    """How many `DAILY_STOP` operational alerts the journal holds."""
    rows: list[dict[str, Any]] = await env.assembly.executor.read(
        _alert_rows, env.wiring.stores.journal
    )
    return len(rows)


async def _entry_is_open(env: Any, client_id: str) -> bool:
    adapter = env.assembly.exchange.adapter
    orders = await adapter.snapshot_open_normal_orders(symbol=dr.SYMBOL)
    return any(order.client_order_id == client_id for order in orders)


def _loss_known(env: Any) -> Decimal | None:
    loss: Decimal | None = env.wiring.day_risk.current_daily_loss_quote(utc_day_of(env.clock()))
    return loss


# ---- the scenario ------------------------------------------------------------------------------ #


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S12 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder)
    finally:
        env.faults.clear(TRADES_METHOD)
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    facts: dict[str, Any] = recorder.details.setdefault("daily_stop", {})
    recorder.details["leaves_state"] = (
        "DAILY_STOP is latched for the rest of the UTC day; run S12 last in an owner session"
    )

    day = await _baseline(env, recorder, facts)
    first = await place_approved_entry(env, recorder, SCENARIO_FAR)
    await _inject_and_wait(env, recorder, facts, day)
    await _evaluate_the_day(env, recorder, facts)
    outcome = await _resting_entry(env, recorder, facts, first)
    await _confirm_is_refused(env, recorder, facts)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = outcome
    return outcome


async def _baseline(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> DayRiskState:
    """The persisted day row and the thresholds the loaded parameters give (no literal)."""

    async def opened() -> bool:
        return await persisted_day(env) is not None

    if not await dr._wait_until(env, opened):
        raise dr._smoke_fail(
            env, recorder, STEP_BASELINE, "the process persisted no day row for today"
        )
    row = await persisted_day(env)
    assert row is not None
    if row.stop_latched_at_utc is not None:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_PRECONDITION,
            "DAILY_STOP is already latched for this UTC day and holds until 00:00 UTC; S12 runs "
            "once per UTC day, last in an owner session",
        )
    dr._smoke_record(
        env, recorder, STEP_PRECONDITION, dr.STEP_PASSED, "the day is not latched at the start"
    )
    thresholds = day_thresholds(parameter_set=env.assembly.params, day=row)
    if thresholds is None:
        raise dr._smoke_fail(env, recorder, STEP_BASELINE, "the day thresholds are not usable")
    stop = Decimal(thresholds[STOP_KEY])
    facts.update(
        {
            "utc_day": row.utc_day.isoformat(),
            "day_base": str(row.equity_at_day_start),
            "stop_rate": str(env.assembly.params[STOP_KEY]),
            "stop_threshold": str(stop),
        }
    )
    record_reaction(
        env,
        recorder,
        STEP_BASELINE,
        f"day {row.utc_day} opened from the persisted base; the stop threshold is the loaded "
        f"rate {facts['stop_rate']} of that base",
    )
    return row


def _loss_rows(env: Any, loss: Decimal, day: Any) -> Any:
    """The reader override: one loss fill of BTCUSDT inside today's window, nothing for others."""
    fill_time = utc_day_start(day) + _ONE_SECOND

    async def trades(**kwargs: Any) -> tuple[UserTradeRow, ...]:
        if kwargs.get("symbol") != dr.SYMBOL:
            return ()
        return (
            UserTradeRow(
                symbol=dr.SYMBOL,
                order_id=INJECTED_ORDER_ID,
                trade_id=INJECTED_TRADE_ID,
                realized_pnl=-loss,
                commission=Decimal("0"),
                commission_asset="USDT",
                margin_asset="USDT",
                time_utc=fill_time,
            ),
        )

    return trades


async def _inject_and_wait(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], row: DayRiskState
) -> None:
    stop = Decimal(facts["stop_threshold"])
    loss = stop * BEYOND_THE_STOP
    facts["injected_loss"] = str(loss)
    facts["cancel_calls_before_the_loss"] = len(env.faults.calls_to(CANCEL_METHOD))
    env.faults.override(TRADES_METHOD, _loss_rows(env, loss, row.utc_day), times=None)
    record_inject(
        env,
        recorder,
        f"user_trades_in_window returns one loss fill of {loss} {dr.SYMBOL} (the stop threshold "
        f"{stop} times {BEYOND_THE_STOP}); the rows exist only at the adapter edge",
    )

    async def known() -> bool:
        current = _loss_known(env)
        return current is not None and current >= stop

    if not await dr._wait_until(env, known):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_LOSS_KNOWN,
            f"the day service never knew a loss of {stop} or more (known: {_loss_known(env)})",
        )
    injected_calls = [c for c in env.faults.calls_to(TRADES_METHOD) if c["injected"] is True]
    facts["loss_known"] = str(_loss_known(env))
    facts["injection_calls"] = len(injected_calls)
    if not injected_calls or Decimal(facts["loss_known"]) != loss:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_LOSS_KNOWN,
            f"{len(injected_calls)} injected read(s), known loss {facts['loss_known']}, "
            f"expected {loss}",
        )
    record_reaction(
        env,
        recorder,
        STEP_LOSS_KNOWN,
        f"the backfill read the injected fill; the day service knows a loss of "
        f"{facts['loss_known']} (stop threshold {stop})",
    )


async def _evaluate_the_day(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    verdict = await env.wiring.day_risk.evaluate(now_utc=env.clock(), exposure=True)
    row = await persisted_day(env)
    latched = row is not None and row.stop_latched_at_utc is not None
    state = None if verdict.state is None else verdict.state.value
    facts["verdict"] = {
        "state": state,
        "reason_code": verdict.reason_code,
        "latched_in_the_store": latched,
        "evaluated_by": "scenario",
    }
    if verdict.state is not DailyState.DAILY_STOP or not latched:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_DAILY_STOP,
            f"verdict {state} ({verdict.reason_code}), latched in the store {latched}",
        )
    recorder.add_labeled_step(
        STEP_DAILY_STOP,
        dr.STEP_PASSED,
        ("SYNTHETIC: " if env.synthetic else "")
        + f"the day service evaluated the day (called by the scenario, the call the placement "
        f"makes at every CONFIRM): {state}, latched in the day store; loss "
        f"{facts['loss_known']} against the stop threshold {facts['stop_threshold']}",
        label=label_for(env, injected=True),
    )


async def _resting_entry(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], first: Any
) -> str:
    await ticks(env, 3)  # the processes get time to act on the latched day
    still_open = await _entry_is_open(env, first.entry_client_id)
    view = env.wiring.coordinator.protection_of(first.plan_hash)
    cancels = len(env.faults.calls_to(CANCEL_METHOD)) - facts["cancel_calls_before_the_loss"]
    alerts = await daily_stop_alerts(env)
    facts["resting_entry"] = {
        "entry_still_open": still_open,
        "cancel_calls_after_the_stop": cancels,
        "protection_state": None if view is None else view.state.value,
        "daily_stop_alerts": alerts,
    }
    if still_open or alerts != 1:
        _record_gap_with_env_label(
            env,
            recorder,
            STEP_RESTING_ENTRY,
            f"after the latch the resting entry is {'still open' if still_open else 'gone'} "
            f"({cancels} cancel call(s)) and {alerts} DAILY_STOP alert(s) are journaled: nothing "
            "in the live composition calls enforce_daily_state (finding F1)",
        )
        outcome = dr.OUTCOME_COMPLETE_WITH_GAPS
    else:
        record_reaction(
            env,
            recorder,
            STEP_RESTING_ENTRY,
            "the resting entry was cancelled at DAILY_STOP and the alert journaled",
        )
        outcome = dr.OUTCOME_COMPLETE
    if still_open:
        await cancel_resting_entry(env, recorder, first)  # the operator's production step
    else:
        await expire_plan(env, first)
    return outcome


async def _confirm_is_refused(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    sent_before = place_entry_calls(env)
    request = await card_and_approve(env, recorder)
    await env.owner.act("confirm", short_id=request.short_id, note="")

    async def decided() -> bool:
        return bool(await placement_decision(env, request))

    if not await dr._wait_until(env, decided):
        raise dr._smoke_fail(
            env, recorder, STEP_CONFIRM_REFUSED, "the CONFIRM left no journaled decision"
        )
    decisions = await placement_decision(env, request)
    facts["confirm"] = {
        "approve_and_card_not_blocked": True,
        "decisions": decisions,
        "place_entry_calls_before": sent_before,
        "place_entry_calls_after": place_entry_calls(env),
    }
    if (
        not decisions
        or not all(d["refused"] for d in decisions)
        or decisions[-1]["reason"] != DAILY_STOP_REASON
        or place_entry_calls(env) != sent_before
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_CONFIRM_REFUSED,
            f"decisions {decisions}, place_entry {place_entry_calls(env)} (was {sent_before}); "
            f"expected a refusal {DAILY_STOP_REASON} with nothing sent",
        )
    record_reaction(
        env,
        recorder,
        STEP_CONFIRM_REFUSED,
        f"the CONFIRM of a new request was refused {DAILY_STOP_REASON} and no entry was sent",
    )
    await expire_plan(env, request)
