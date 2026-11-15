"""S18 unprotected-position drill (G2-016): CLOSE_FAILED, alert, blocked entries (plan 25-11).

TEST_ONLY. OPS-01, D-06. The drill the RUNBOOK describes for a position that cannot be protected:
the stop is rejected (S04's trigger) AND every reduce-only close fails. Both triggers are injected
at the adapter edge (`FaultEdge.raise_before_send`, a definitive -2021 for the stop, a definitive
-2022 for the close, nothing is sent for either) and the REACTION is the real coordinator's:

* the plan holds CLOSE_FAILED, `blocks_new_entries()` is True, SAFE_MODE is on, the critical alerts
  (CLOSE_REQUIRED, PROTECTIVE_REJECTED, EMERGENCY_CLOSE_FAILED) are journaled and the close is
  retried at every coordinator step;
* the operator `/close` and `/confirm` (RUNBOOK 21.1a) are sent through the real handler with the
  authorized identity. For a plan whose close is already required the code answers
  CLOSE_ALREADY_REQUIRED and sends nothing (`ProtectionCoordinator.operator_close`): the retry
  stays the coordinator's own, so the plan's wording "the operator `/close` flattens the position"
  does not describe V1 (recorded as a finding in the SUMMARY, not hidden);
* the close fault is lifted and the coordinator's next retry sends a real reduce-only MARKET close;
  the plan ends FLAT, entries unblock, SAFE_MODE is left through `/safemode_exit`, the account ends
  clean.

Labels: every step inside the fault window is `label_for(env, injected=True)` (DEMO_FAULT_INJECTED
on Demo, because nothing real was sent); only the final close is `label_for(env, injected=False)`
(a real Demo order, DEMO_OBSERVED). The scenario leaves state if it halts (a Demo position without a
stop, SAFE_MODE on): its recorded failure step names `scripts/demo_clear.py`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from scripts import demo_rehearsal as dr
from src.execution.order_ids import derive_close_order_id
from src.execution.protection import ProtectionState

from tests.support.demo_scenarios import s04_stop_rejected as s04
from tests.support.demo_scenarios.harness import (
    CLEAR_INSTRUCTION,
    ScenarioRecorder,
    ensure_clean_start,
    label_for,
)
from tests.support.demo_scenarios.s06_replay import (
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)

CLOSE_REJECTION_CODE = -2022  # REDUCE_ONLY_REJECT (a test convention, never evidence: D055)
STEP_INJECT = "inject_stop_rejection_and_close_failures"
STEP_CLOSE_FAILED = "close_failed_blocks_entries"
STEP_ALERTS = "critical_alerts_journaled"
STEP_RETRIES = "close_retried_every_step"
STEP_OPERATOR_CLOSE = "operator_close_answered"
STEP_FLATTENED = "flattened_after_fault_cleared"
STEP_STATE_LEFT = "state_left_on_demo"
ALERT_CLOSE_FAILED = "EMERGENCY_CLOSE_FAILED"
CODE_CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
CODE_ALREADY_REQUIRED = "CLOSE_ALREADY_REQUIRED"
_OPERATOR_UPDATE_BASE = 30_000


# ---- helpers ----------------------------------------------------------------------------------- #


def record_fault_step(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A step inside the injected fault window: DEMO_FAULT_INJECTED on Demo, never observed."""
    s04.record_injection_step(env, recorder, detail, name=name)


def confirm_token(bot: Any, chat_id: int, since: int) -> str | None:
    """The one-time token of the last `/confirm <token>` line sent to `chat_id` after `since`.

    Reads the process's bot channel: `FakeBot.sent` holds objects with `chat_id` and `text`, the
    Demo env's `RecordingBot.sent` holds `(chat_id, text)` pairs. The token is never recorded.
    """
    for item in reversed(list(bot.sent)[since:]):
        target, text = (item.chat_id, item.text) if hasattr(item, "text") else (item[0], item[1])
        if target == chat_id and "/confirm " in text:
            parts = text.rsplit("/confirm ", 1)[1].split()
            if parts:
                return str(parts[0])
    return None


def bot_channel(env: Any) -> Any:
    """The object that records what the process sent to the owner chat (it has a `sent` list).

    On Demo `assembly.bot` is the env's `RecordingBot`; on the fake it is a `LiveBotProxy` bound
    to the rig's `FakeBot`.
    """
    bot = env.assembly.bot
    if hasattr(bot, "sent"):
        return bot
    bound = getattr(bot, "_bot", None)
    if bound is not None and hasattr(bound, "sent"):
        return bound
    raise RuntimeError("the process bot does not record what it sent")


def _protection(env: Any, plan_hash: str) -> Any:
    return env.wiring.coordinator.protection_of(plan_hash)


async def _open_position(env: Any) -> bool:
    adapter = env.assembly.exchange.adapter
    rows = await adapter.snapshot_positions(symbol=dr.SYMBOL)
    return any(row.position_amt != 0 for row in rows)


def _operator_update(env: Any, n: int) -> Any:
    config = env.assembly.config
    return SimpleNamespace(
        update_id=_OPERATOR_UPDATE_BASE + n,
        effective_chat=SimpleNamespace(id=config.authorized_chat_id, type="private"),
        effective_user=SimpleNamespace(id=min(config.authorized_user_ids)),
    )


# ---- the scenario ------------------------------------------------------------------------------ #


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S18 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder)
    except dr.SmokeHalt:
        prefix = "SYNTHETIC: " if env.synthetic else ""
        recorder.add_labeled_step(
            STEP_STATE_LEFT,
            dr.STEP_FAILED,
            prefix
            + "the drill stopped before the position was flat; the account may hold a position "
            "without a stop and SAFE_MODE may be on: " + CLEAR_INSTRUCTION,
            label=label_for(env, injected=False),
        )
        raise
    finally:
        env.faults.clear(s04.CLOSE_METHOD)
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    wiring = env.wiring

    # Both triggers are armed BEFORE the fill: the first stop placement and every close fail.
    env.faults.raise_before_send(s04.STOP_METHOD, s04.injected_rejection(), times=1)
    env.faults.raise_before_send(
        s04.CLOSE_METHOD, s04.injected_rejection(CLOSE_REJECTION_CODE), times=None
    )
    first = await place_approved_entry(env, recorder, s04.SCENARIO_FILL)
    await s04.drive_fill(env, first)
    plan_hash = first.plan_hash

    # ---- CLOSE_FAILED: entries blocked, SAFE_MODE on, position open ------------------------- #
    async def close_failed() -> bool:
        view = _protection(env, plan_hash)
        return view is not None and view.state is ProtectionState.CLOSE_FAILED

    if not await dr._wait_until(env, close_failed):
        view = _protection(env, plan_hash)
        state = None if view is None else view.state.value
        raise dr._smoke_fail(env, recorder, STEP_CLOSE_FAILED, f"the plan state is {state}")
    injected_stops = [c for c in s04.stop_placements(env, plan_hash) if c.get("injected") is True]
    injected_closes = [c for c in s04.close_placements(env) if c.get("injected") is True]
    if len(injected_stops) != 1 or not injected_closes:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_INJECT,
            f"{len(injected_stops)} injected stop(s), {len(injected_closes)} injected close(s)",
        )
    record_fault_step(
        env,
        recorder,
        STEP_INJECT,
        f"the first stop placement was rejected with code {s04.REJECTION_CODE} and every "
        f"reduce-only close is rejected with code {CLOSE_REJECTION_CODE}; nothing was sent for "
        "them",
    )
    blocks = bool(wiring.coordinator.blocks_new_entries())
    in_safe_mode = bool(wiring.safe_mode.in_safe_mode)
    still_open = await _open_position(env)
    if not (blocks and in_safe_mode and still_open):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_CLOSE_FAILED,
            f"blocks_new_entries={blocks}, safe_mode={in_safe_mode}, position_open={still_open}",
        )
    record_fault_step(
        env,
        recorder,
        STEP_CLOSE_FAILED,
        "CLOSE_FAILED: new entries are blocked, SAFE_MODE is on, the position is still open",
    )

    # ---- retried at every step; still blocked; alerts journaled ------------------------------ #
    for _ in range(dr.SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()
        view = _protection(env, plan_hash)
        if view is None or view.state is not ProtectionState.CLOSE_FAILED:
            raise dr._smoke_fail(env, recorder, STEP_RETRIES, "the plan left CLOSE_FAILED early")
        if not wiring.coordinator.blocks_new_entries():
            raise dr._smoke_fail(env, recorder, STEP_RETRIES, "entries were unblocked")
    attempts = [c for c in s04.close_placements(env)]
    if len(attempts) < 2 or not all(c.get("injected") is True for c in attempts):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_RETRIES,
            f"{len(attempts)} close attempt(s), "
            f"{sum(1 for c in attempts if c.get('injected') is True)} injected",
        )
    if len(s04.stop_placements(env, plan_hash)) != 1:
        raise dr._smoke_fail(env, recorder, STEP_RETRIES, "the rejected stop was resent")
    recorder.details["close_failed"] = {
        "state": ProtectionState.CLOSE_FAILED.value,
        "blocks_new_entries": blocks,
        "safe_mode": in_safe_mode,
        "position_still_open": still_open,
        "close_attempts_while_failed": len(attempts),
    }
    record_fault_step(
        env,
        recorder,
        STEP_RETRIES,
        f"{len(attempts)} close attempts across the coordinator steps, each rejected at the edge; "
        "the plan stayed CLOSE_FAILED and blocked, the stop was never resent",
    )
    alerts = await env.assembly.executor.read(s04.alert_rows, wiring.stores.journal, plan_hash)
    pairs = {(row.get("event"), row.get("reason")) for row in alerts}
    needed = {("CLOSE_REQUIRED", s04.BRANCH_B5), ("PROTECTIVE_REJECTED", s04.BRANCH_B5)}
    if not needed <= pairs or not any(event == ALERT_CLOSE_FAILED for event, _r in pairs):
        raise dr._smoke_fail(env, recorder, STEP_ALERTS, f"alert rows {sorted(map(str, pairs))}")
    record_fault_step(
        env,
        recorder,
        STEP_ALERTS,
        "OPERATIONAL_ALERT rows CLOSE_REQUIRED, PROTECTIVE_REJECTED and EMERGENCY_CLOSE_FAILED "
        "name the plan",
    )

    # ---- the operator /close and /confirm through the real handler --------------------------- #
    await _operator_close(env, recorder, plan_hash)

    # ---- lift the close fault: the coordinator's own retry flattens the position -------------- #
    env.faults.clear(s04.CLOSE_METHOD)

    async def flat() -> bool:
        view = _protection(env, plan_hash)
        return view is not None and view.state is ProtectionState.FLAT

    if not await dr._wait_until(env, flat):
        view = _protection(env, plan_hash)
        state = None if view is None else view.state.value
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_FLATTENED,
            f"the plan did not end FLAT after the fault (state {state})",
        )
    await _assert_flattened(env, recorder, plan_hash)
    await s04.expire_plan_and_leave_safe_mode(env, recorder, first)
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE


async def _operator_close(env: Any, recorder: ScenarioRecorder, plan_hash: str) -> None:
    operator = env.wiring.operator
    chat_id = env.assembly.config.authorized_chat_id
    bot = bot_channel(env)
    since = len(bot.sent)
    before = len(s04.close_placements(env))
    state_before = _protection(env, plan_hash).state.value
    args = SimpleNamespace(args=[dr.SYMBOL])
    ask = await operator.close(_operator_update(env, 1), args)
    token = confirm_token(bot, chat_id, since)
    if ask.code != CODE_CONFIRM_REQUIRED or token is None:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_OPERATOR_CLOSE,
            f"/close answered {ask.code}, token {'sent' if token else 'not sent'}",
        )
    done = await operator.confirm(_operator_update(env, 2), SimpleNamespace(args=[token]))
    after = len(s04.close_placements(env))
    recorder.details["operator_close"] = {
        "ask_code": ask.code,
        "confirm_code": done.code,
        "plan_state": state_before,
        "close_calls_before": before,
        "close_calls_after": after,
    }
    if done.code != CODE_ALREADY_REQUIRED:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_OPERATOR_CLOSE,
            f"/confirm answered {done.code}, not {CODE_ALREADY_REQUIRED}",
        )
    if env.synthetic and after != before:
        raise dr._smoke_fail(
            env, recorder, STEP_OPERATOR_CLOSE, "the operator command itself sent a close"
        )
    record_fault_step(
        env,
        recorder,
        STEP_OPERATOR_CLOSE,
        f"/close asked for a token ({ask.code}); /confirm was answered {done.code} while the plan "
        f"was {state_before}: the retry stays the coordinator's own",
    )


async def _assert_flattened(env: Any, recorder: ScenarioRecorder, plan_hash: str) -> None:
    sent = [c for c in s04.close_placements(env) if c.get("injected") is not True]
    if len(sent) != 1:
        raise dr._smoke_fail(
            env, recorder, STEP_FLATTENED, f"{len(sent)} close(s) reached the exchange, expected 1"
        )
    close_id = str(sent[0]["kwargs"].get("new_client_order_id"))
    if not close_id.startswith("xc-"):
        raise dr._smoke_fail(env, recorder, STEP_FLATTENED, "the close has no xc- client id")
    if await _open_position(env):
        raise dr._smoke_fail(env, recorder, STEP_FLATTENED, "a position is still open")
    if env.wiring.coordinator.blocks_new_entries():
        raise dr._smoke_fail(env, recorder, STEP_FLATTENED, "entries are still blocked after FLAT")
    if place_entry_calls(env) != 1:
        raise dr._smoke_fail(env, recorder, STEP_FLATTENED, "an entry was placed meanwhile")
    recorder.details["final_close_is_attempt_one"] = close_id == derive_close_order_id(
        plan_hash=plan_hash, attempt_no=1
    )
    recorder.record_ids(
        STEP_FLATTENED, order_ids=[], client_order_ids=[close_id], algo_client_ids=[]
    )
    s04.record_close_step(
        env,
        recorder,
        "the fault was lifted and the coordinator's retry sent one reduce-only MARKET close under "
        "an xc- client id; the position is flat and entries are unblocked",
        name=STEP_FLATTENED,
    )
