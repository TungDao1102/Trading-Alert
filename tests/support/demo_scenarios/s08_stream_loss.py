"""S08 WS disconnect and listenKey expiry (plan 25-13; EXEC-02, OPS-01, D-07).

TEST_ONLY. The scenario runs the composed process (fake in the CI twin, real Demo in the owner's
test) through `run(env, recorder, *, trigger)`. The REAL `UserDataSupervisor` of the process drives
every reaction (the state machine, the bounded reconnect, the snapshot, the sinks into health,
reconcile and SAFE_MODE); only the TRIGGER differs, supplied by the env:

* `ScriptedStreamTrigger` (the twin): the supervisor of the composed process runs over a scripted
  `SupervisedAdapter` (the websocket edge of the twin, a fake of the same seam the start sequence
  already replaces). `drop` emits the adapter's "close" connection event and keeps the stream down
  (every reconnect fails) so the gap can be examined; `release` lets the reconnect work again;
  `expire` queues a `listenKeyExpired` item the supervisor reads like any stream item.
* `DemoStreamTrigger` (the owner's Demo run): `drop` posts a "close" connection event for the
  CURRENT connection into the supervisor's own listener, so the supervisor runs its own rebuild
  (a real keepalive, a real new websocket connection, a real REST snapshot): an injected trigger
  with a real reconnection (DEMO_FAULT_INJECTED). A real listenKey expiry needs the keepalive
  suppressed for more than the 60 minute key life; it runs only with `TRADING_DEMO_SLOW=1`
  (keepalive failures injected through `SdkFaults`), otherwise that step is NOT_OBSERVED.

What the scenario records is what the code does, never a wished-for result (T-25-30): a step that
could not be produced in the env is NOT_OBSERVED / NOT_REHEARSED, and a behaviour that differs from
the plan's text ends COMPLETE_WITH_GAPS (see the findings of plan 25-13).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from collections.abc import Callable
from typing import Any, Protocol

from binance_common.errors import ServerError
from scripts import demo_rehearsal as dr
from src.adapters.binance_userdata import ConnectionEvent, QueuedStreamItem
from src.adapters.binance_userdata_events import ListenKeyExpiredEvent
from src.adapters.binance_userdata_supervisor import StreamState
from src.domain.enums import TradePlanStatus
from src.execution.protection import ProtectionState
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME, EVENT_PLACEMENT_REFUSED
from src.live.wiring import TASK_HEALTH

from tests.support.demo_scenarios.harness import (
    NOT_OBSERVED,
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

SCENARIO_FAR = "far"
SLOW_ENV = "TRADING_DEMO_SLOW"
STEP_BASELINE = "stream_live_and_health_ok"
STEP_DROP = "stream_dropped"
STEP_GAP_HEALTH = "health_refuses_while_not_live"
STEP_ENTRY_IN_GAP = "entry_refused_while_not_live"
STEP_SILENCE = "silence_leads_to_safe_mode"
STEP_NO_SELF_RESYNC = "halted_stream_waits_for_resync"
STEP_RESTORED = "stream_live_again"
STEP_CATCH_UP = "rest_reconcile_catches_up_the_gap"
STEP_SAFE_MODE_EXIT = "safe_mode_left_after_live"
STEP_EXPIRY = "listen_key_expired_restarts_the_stream"
STEP_STATES = "stream_states_seen"
STEP_EXIT_REFUSED = "safe_mode_exit_refused_while_not_live"
STEP_ENTRY_AFTER_EXIT = "entry_allowed_after_the_documented_exit"
HEALTH_STREAM_CHECKS = ("ws_connection_state", "user_data_stream_state")
SILENCE_REASONS = ("STALE_FEED", "USER_DATA_STREAM_HALTED")
KEEPALIVE_SDK_METHOD = "keepalive_user_data_stream"
KEEPALIVE_POLL_SECONDS = 30
INJECTED_TEXT = "TEST_ONLY injected keepalive failure"
_STATE_REASON_CAP = 64
_PLACEMENT_CORRELATION = "live-placement"


# ---- the trigger seam ------------------------------------------------------------------------ #


class StreamTrigger(Protocol):
    """What the env supplies: how the stream is dropped, restored and expired."""

    #: True when the trigger keeps the stream down until `release` (the twin); a Demo drop is
    #: followed by the supervisor's own recovery at once.
    holds: bool

    async def drop(self, env: Any) -> None: ...

    async def release(self, env: Any) -> None: ...

    async def expire(self, env: Any, watcher: StateWatcher | None) -> str:
        """Provoke a listenKey expiry; returns "EXPIRED" or the NOT_OBSERVED reason text."""
        ...

    def calls(self) -> dict[str, int]:
        """How often the stream edge was asked to start, keepalive, rekey, rebuild and stop."""
        ...

    def queued_items(self) -> int:
        """Stream items waiting for the supervisor (a change the stream never delivered is 0)."""
        ...

    async def change_order_during_gap(self, env: Any, first: Any) -> None:
        """Change the plan's resting entry on the exchange behind the stream's back."""
        ...


class ScriptedStreamAdapter:
    """A scripted `SupervisedAdapter`: the twin's websocket edge (TEST_ONLY, nothing is sent).

    `down=True` makes start, rekey and rebuild fail with a `ConnectionError` (a retryable
    failure, the supervisor retries within its bound and then halts); `down=False` lets them
    succeed. Every call is counted, and `emit_close` / `emit_expired` are the two triggers.
    """

    def __init__(self, clock: Callable[[], Any]) -> None:
        self._clock = clock
        self.epoch = 1
        self.queue: asyncio.Queue[QueuedStreamItem] = asyncio.Queue()
        self.overflowed = False
        self.overflow_count = 0
        self.open = True
        self.down = False
        self.counts: dict[str, int] = {
            "start": 0,
            "keepalive": 0,
            "rekey": 0,
            "rebuild": 0,
            "stop": 0,
        }
        self._listener: Callable[[ConnectionEvent], None] | None = None

    def clear_overflow(self) -> None:
        self.overflowed = False

    def private_connection_open(self) -> bool:
        return self.open

    def set_connection_listener(self, listener: Callable[[ConnectionEvent], None] | None) -> None:
        self._listener = listener

    def _connect(self, name: str) -> None:
        self.counts[name] += 1
        if self.down:
            raise ConnectionError("TEST_ONLY scripted stream is down")
        self.epoch += 1
        self.open = True

    async def start(self) -> None:
        self._connect("start")

    async def keepalive(self) -> None:
        self.counts["keepalive"] += 1

    async def rekey(self) -> None:
        self._connect("rekey")

    async def rebuild(self) -> None:
        self._connect("rebuild")

    async def stop(self, *, close_listen_key: bool) -> None:
        self.counts["stop"] += 1
        self.open = False

    def emit_close(self) -> None:
        """The socket closes: a "close" event of the CURRENT connection reaches the listener."""
        self.open = False
        if self._listener is not None:
            self._listener(ConnectionEvent(name="close", at_utc=self._clock(), epoch=self.epoch))

    def emit_expired(self) -> None:
        """A `listenKeyExpired` item of the CURRENT connection reaches the stream queue."""
        now = self._clock()
        self.queue.put_nowait(
            QueuedStreamItem(
                outcome=ListenKeyExpiredEvent(event_time_utc=now),
                received_at_utc=now,
                connection_epoch=self.epoch,
            )
        )


class ScriptedStreamTrigger:
    """The twin trigger over a `ScriptedStreamAdapter` (see the module docstring)."""

    holds = True

    def __init__(self, adapter: ScriptedStreamAdapter) -> None:
        self.adapter = adapter

    async def drop(self, env: Any) -> None:
        self.adapter.down = True
        self.adapter.emit_close()
        await env.pause(0)

    async def release(self, env: Any) -> None:
        self.adapter.down = False

    async def expire(self, env: Any, watcher: StateWatcher | None) -> str:
        self.adapter.emit_expired()
        return "EXPIRED"

    def calls(self) -> dict[str, int]:
        return dict(self.adapter.counts)

    def queued_items(self) -> int:
        return self.adapter.queue.qsize()

    async def change_order_during_gap(self, env: Any, first: Any) -> None:
        env.fake.cancel(first.entry_client_id)  # the fake's own cancel: no stream frame follows


def install_scripted_stream(env: Any) -> ScriptedStreamTrigger:
    """Twin only: start the process's REAL supervisor over a scripted adapter instead of `go_live`.

    Call before the start sequence runs. The env's `ports_transform` keeps everything else the
    twin env already replaces (alembic revisions, the scheduler); only `start_stream` changes.
    """
    adapter = ScriptedStreamAdapter(env.clock)
    inner = env.ports_transform

    async def start_stream() -> None:
        supervisor = env.assembly.wiring.stream.supervisor
        supervisor._adapter = adapter  # the websocket edge of the twin (a SupervisedAdapter)
        await supervisor.start()

    def transform(ports: Any) -> Any:
        return dataclasses.replace(inner(ports), start_stream=start_stream)

    env.ports_transform = transform
    return ScriptedStreamTrigger(adapter)


class DemoStreamTrigger:
    """The Demo trigger: the supervisor's own rebuild, and the optional slow expiry."""

    holds = False

    async def drop(self, env: Any) -> None:
        stream = env.wiring.stream
        # The event the adapter's listener posts when the SDK reports a closed socket, for the
        # CURRENT connection: the supervisor then runs its own rebuild and snapshot.
        stream.supervisor._on_connection_event(
            ConnectionEvent(name="close", at_utc=env.clock(), epoch=stream.adapter.epoch)
        )

    async def release(self, env: Any) -> None:
        return None

    def calls(self) -> dict[str, int]:
        return {}

    def queued_items(self) -> int:
        return 0

    async def change_order_during_gap(self, env: Any, first: Any) -> None:
        raise NotImplementedError("a Demo drop recovers at once; no gap is held open")

    async def expire(self, env: Any, watcher: StateWatcher | None) -> str:
        """Without `TRADING_DEMO_SLOW=1` the reason; with it, the keepalive is failed and watched.

        With the loaded limits the supervisor re-keys after `keepalive_failure_tolerance` failed
        keepalives (one, at the 30 minute interval), BEFORE the 60 minute key life ends, so the
        injected failure is expected to show `KEEPALIVE_FAILURES`, not a real expiry. What is seen
        is returned as it is: "EXPIRED" only if the supervisor reported `LISTEN_KEY_EXPIRED`.
        """
        if os.environ.get(SLOW_ENV) != "1" or watcher is None:
            return (
                "a real listenKey expiry needs the keepalive suppressed for more than 60 minutes; "
                f"it runs only when the owner sets {SLOW_ENV}=1"
            )
        stream_limits = env.assembly.binance_limits.stream
        wait_seconds = int(stream_limits.keepalive_interval_seconds) * 2
        mark = len(watcher.transitions)
        env.sdk_faults.fail_sdk(KEEPALIVE_SDK_METHOD, ServerError(INJECTED_TEXT, 503), times=None)
        try:
            waited = 0
            while waited < wait_seconds and not _reacted(watcher, mark):
                await env.pause(KEEPALIVE_POLL_SECONDS)
                waited += KEEPALIVE_POLL_SECONDS
        finally:
            env.sdk_faults.clear(KEEPALIVE_SDK_METHOD)
        reasons = [reason for _state, reason in watcher.since(mark)]
        if "LISTEN_KEY_EXPIRED" in reasons:
            return "EXPIRED"
        return (
            f"keepalives were failed for {waited} s and the supervisor reported "
            f"{reasons or 'nothing'}: a real listenKeyExpired event was not observed"
        )


def _reacted(watcher: StateWatcher, mark: int) -> bool:
    return any(state == StreamState.UNKNOWN.value for state, _reason in watcher.since(mark))


# ---- observation ----------------------------------------------------------------------------- #


class StateWatcher:
    """Records every (state, reason) the supervisor reports, then forwards to the real sink."""

    def __init__(self, supervisor: Any) -> None:
        self.transitions: list[tuple[str, str]] = []
        self._supervisor = supervisor
        original = supervisor._on_state_change

        def record(state: StreamState, reason: str) -> None:
            if len(self.transitions) < _STATE_REASON_CAP:
                self.transitions.append((state.value, reason))
            original(state, reason)

        supervisor._on_state_change = record

    @property
    def states(self) -> list[str]:
        return [state for state, _reason in self.transitions]

    def since(self, mark: int) -> list[tuple[str, str]]:
        return self.transitions[mark:]


# ---- steps shared by the sequences ------------------------------------------------------------ #


def record_gap(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A step this env could not produce: NOT_OBSERVED on Demo, a rehearsal gap on the twin."""
    prefix = "SYNTHETIC: " if env.synthetic else ""
    recorder.add_labeled_step(
        name,
        dr.STEP_NOT_REHEARSED,
        prefix + detail,
        label=label_for(env, injected=False) if env.synthetic else NOT_OBSERVED,
    )


def _supervisor(env: Any) -> Any:
    return env.wiring.stream.supervisor


def _stream_state(env: Any) -> StreamState:
    state: StreamState = _supervisor(env).state
    return state


async def health_verdict(env: Any, recorder: ScenarioRecorder) -> Any:
    """Run the health task once, record its facts, return the verdict."""
    specs = {spec.name: spec for spec in env.wiring.specs}
    await specs[TASK_HEALTH].run()
    verdict = env.wiring.health.latest_verdict
    recorder.record_health(verdict)
    return verdict


def failing_checks(verdict: Any) -> list[str]:
    return [r.check_name for r in verdict.results if r.status == "FAIL"]


def silence_bound_ms(env: Any) -> int | None:
    """The configured user-data silence bound of the process (the loaded limits)."""
    bound = env.assembly.config.limits.stale_feed_max_user_data_silence_ms
    return None if bound is None else int(bound)


def recovery_window_seconds(env: Any) -> int:
    """Twice the supervisor's own reconnect delay bound: how long a halted stream is watched."""
    return 2 * int(env.assembly.binance_limits.stream.reconnect_max_delay_seconds)


async def _card_and_approve(env: Any, recorder: ScenarioRecorder) -> Any:
    """Inject a `far` request, wait for the card and APPROVE it (no CONFIRM)."""
    first = await dr._inject(env, recorder, SCENARIO_FAR, "signal")
    wiring = env.wiring

    async def card_issued() -> bool:
        if wiring.demo_signal is None or wiring.demo_signal.source.pending != 0:
            return False
        row = await dr._smoke_read(env, wiring.stores.entities.get_trade_plan, first.trade_plan_id)
        return row is not None

    if not await dr._wait_until(env, card_issued):
        raise dr._smoke_fail(env, recorder, "card", "the approval card was not issued")
    await env.owner.act("approve", short_id=first.short_id, note="")

    async def approved() -> bool:
        row = await dr._smoke_read(env, wiring.stores.entities.get_trade_plan, first.trade_plan_id)
        return row is not None and row.status is TradePlanStatus.APPROVED

    if not await dr._wait_until(env, approved):
        raise dr._smoke_fail(env, recorder, "approve", "no APPROVE was seen before the timeout")
    return first


def placement_decisions(journal: Any, shadow: Any, trade_plan_id: str) -> list[dict[str, Any]]:
    """The placement decisions of the plan's approvals, oldest first.

    Two rows can end a CONFIRM without an order: `LIVE_PLACEMENT_REFUSED` (the inputs were refused
    before the manager ran, for example `UNCERTAIN_ACCOUNT_STATE`) and a refused
    `LIVE_PLACEMENT_OUTCOME` (the manager's own verdict). Each entry has `event`, `refused` and
    `reason`.
    """
    approval_ids: dict[str, None] = {}
    for approval in [*shadow.list_pending_approvals(), *shadow.list_approved_approvals()]:
        if approval.trade_plan_id == trade_plan_id:
            approval_ids[approval.approval_id] = None
    rows: list[dict[str, Any]] = []
    for approval_id in approval_ids:
        for event in journal.list_by_correlation(f"{_PLACEMENT_CORRELATION}:{approval_id}"):
            payload = json.loads(event.payload_json)
            if event.event_type == EVENT_PLACEMENT_REFUSED:
                rows.append(
                    {"event": event.event_type, "refused": True, "reason": payload["reason"]}
                )
            elif event.event_type == EVENT_PLACEMENT_OUTCOME:
                rows.append(
                    {
                        "event": event.event_type,
                        "refused": bool(payload.get("is_no_trade")),
                        "reason": payload.get("reason_code"),
                    }
                )
    return rows


async def _placement_decision(env: Any, first: Any) -> list[dict[str, Any]]:
    wiring = env.wiring
    rows: list[dict[str, Any]] = await env.assembly.executor.read(
        placement_decisions, wiring.stores.journal, wiring.stores.shadow, first.trade_plan_id
    )
    return rows


async def _expire_plan(env: Any, first: Any) -> None:
    """APPROVED -> EXPIRED (DOMN-04), so the approval no longer holds the symbol."""
    await env.assembly.executor.write(
        env.wiring.stores.entities.transition_trade_plan,
        first.trade_plan_id,
        TradePlanStatus.EXPIRED,
        now_utc=env.clock(),
    )


async def _ticks(env: Any, count: int = dr.SMOKE_REPLAY_SETTLE_TICKS) -> None:
    for _ in range(count):
        await env.tick()


async def _wait_state(env: Any, state: StreamState) -> bool:
    async def reached() -> bool:
        return _stream_state(env) is state

    return await dr._wait_until(env, reached)


def _exit_refusals(env: Any) -> list[str]:
    """The refusal names of the latest SAFE_MODE exit row check (twin: the memory journal)."""
    rig = getattr(env, "rig", None)
    if rig is None:
        return []
    refusals: list[str] = []
    for row in rig.stores.journal.by_type("SAFE_MODE_EXIT_REFUSED"):
        refusals = list(json.loads(row.payload_json).get("refusals", []))
    return refusals


async def _leave_safe_mode(env: Any, recorder: ScenarioRecorder, name: str) -> None:
    """The operator exit (RUNBOOK 21.1a) once the stream is LIVE; SAFE_MODE must be off after."""
    wiring = env.wiring
    if wiring.safe_mode.in_safe_mode:
        await env.owner.act("safemode_exit")

        async def left() -> bool:
            return not wiring.safe_mode.in_safe_mode

        if not await dr._wait_until(env, left):
            refusals = ", ".join(_exit_refusals(env)) or "unknown"
            raise dr._smoke_fail(
                env,
                recorder,
                name,
                f"SAFE_MODE was not left by /safemode_exit (refused: {refusals}); leave it by "
                "hand (RUNBOOK 21.1a) and run scripts/demo_clear.py if anything is left",
            )
    if wiring.coordinator.blocks_new_entries():
        raise dr._smoke_fail(env, recorder, name, "entries are still blocked after the exit")
    record_step(env, recorder, name, "SAFE_MODE is off (left through /safemode_exit)")


async def _restore_stream(
    env: Any, recorder: ScenarioRecorder, trigger: StreamTrigger, watcher: StateWatcher
) -> None:
    """Let the reconnect work again and ask the supervisor to resync; LIVE must follow.

    Nothing in `src` calls `request_resync()` (finding F1 of plan 25-13): after a halted recovery
    the stream stays UNKNOWN until the process restarts. The scenario asks for the resync itself,
    the stand-in for the call production does not make, and records that it did.
    """
    mark = len(watcher.transitions)
    await trigger.release(env)
    _supervisor(env).request_resync()
    if not await _wait_state(env, StreamState.LIVE):
        raise dr._smoke_fail(env, recorder, STEP_RESTORED, "the stream did not return to LIVE")
    recorder.details["resync_requested_by_scenario"] = (
        int(recorder.details.get("resync_requested_by_scenario", 0)) + 1
    )
    seen = [state for state, _reason in watcher.since(mark)]
    if StreamState.LIVE.value not in seen:
        raise dr._smoke_fail(env, recorder, STEP_RESTORED, f"states after the resync: {seen}")
    record_step(env, recorder, STEP_RESTORED, f"after the resync the stream passed through {seen}")


def _snapshot_calls(env: Any) -> int:
    return len(env.faults.calls_to("snapshot_positions"))


def _protection_state(env: Any, plan_hash: str) -> str | None:
    view = env.wiring.coordinator.protection_of(plan_hash)
    return None if view is None else str(view.state.value)


# ---- the scenario ------------------------------------------------------------------------------ #


def _default_trigger(env: Any) -> StreamTrigger:
    if env.synthetic:
        raise ValueError("a synthetic env needs the trigger of install_scripted_stream(env)")
    return DemoStreamTrigger()


async def run(
    env: Any,
    recorder: ScenarioRecorder,
    *,
    trigger: StreamTrigger | None = None,
    early_confirm: bool = False,
) -> str:
    """Run S08 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`.

    `early_confirm=True` (a holding trigger only) presses CONFIRM right after the drop, before the
    first reconcile tick can enter SAFE_MODE: what the code does in the first moments of a gap.
    """
    recorder.default_label = env.label
    chosen = trigger if trigger is not None else _default_trigger(env)
    if early_confirm and not chosen.holds:
        raise ValueError("early_confirm needs a trigger that holds the stream down")
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder, chosen, early_confirm)
    finally:
        await shutdown(env)


async def _sequence(
    env: Any, recorder: ScenarioRecorder, trigger: StreamTrigger, early_confirm: bool
) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    watcher = StateWatcher(_supervisor(env))
    await _baseline(env, recorder)
    if not trigger.holds:
        outcome = await _demo_sequence(env, recorder, trigger, watcher)
    elif early_confirm:
        outcome = await _early_sequence(env, recorder, trigger, watcher)
    else:
        outcome = await _twin_sequence(env, recorder, trigger, watcher)
    recorder.details["stream_states"] = [[state, reason] for state, reason in watcher.transitions]
    record_step(
        env,
        recorder,
        STEP_STATES,
        "the supervisor reported "
        + ", ".join(f"{state}({reason})" for state, reason in watcher.transitions),
    )
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = outcome
    return outcome


async def _baseline(env: Any, recorder: ScenarioRecorder) -> None:
    state = _stream_state(env)
    verdict = await health_verdict(env, recorder)
    if state is not StreamState.LIVE or verdict is None or verdict.is_no_trade:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_BASELINE,
            f"stream {state.value}, health no_trade={getattr(verdict, 'is_no_trade', None)}",
        )
    record_step(env, recorder, STEP_BASELINE, "the stream is LIVE and the health verdict is OK")


async def _drop(
    env: Any, recorder: ScenarioRecorder, trigger: StreamTrigger, watcher: StateWatcher
) -> None:
    mark = len(watcher.transitions)
    await trigger.drop(env)
    await env.pause(0)
    seen = watcher.since(mark)
    if ("UNKNOWN", "CONNECTION_CLOSED") not in seen:
        raise dr._smoke_fail(env, recorder, STEP_DROP, f"the supervisor reported {seen}")
    record_injection_step(
        env,
        recorder,
        "a close event of the current connection was injected; the supervisor reported "
        "UNKNOWN (CONNECTION_CLOSED) and started its own recovery",
        name=STEP_DROP,
    )


# ---- the twin sequence: the stream is held down ------------------------------------------------ #


async def _twin_sequence(
    env: Any, recorder: ScenarioRecorder, trigger: StreamTrigger, watcher: StateWatcher
) -> str:
    wiring = env.wiring
    gap: dict[str, Any] = recorder.details.setdefault("gap", {})

    # ---- drop: the stream stays down, health refuses ----------------------------------------- #
    await _drop(env, recorder, trigger, watcher)
    gap["state_after_drop"] = _stream_state(env).value
    await env.tick()
    verdict = await health_verdict(env, recorder)
    gap["health_no_trade"] = bool(verdict.is_no_trade)
    gap["health_failing"] = failing_checks(verdict)
    if not (verdict.is_no_trade and set(HEALTH_STREAM_CHECKS) <= set(gap["health_failing"])):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_GAP_HEALTH,
            f"health no_trade={verdict.is_no_trade}, failing {gap['health_failing']}",
        )
    record_step(
        env,
        recorder,
        STEP_GAP_HEALTH,
        f"while the stream is {gap['state_after_drop']} the health verdict is no-trade "
        f"({', '.join(gap['health_failing'])} FAIL)",
    )

    # ---- a CONFIRM during the gap places nothing; the silence enters SAFE_MODE ----------------- #
    first = await _card_and_approve(env, recorder)
    await env.owner.act("confirm", short_id=first.short_id, note="")
    await _ticks(env)
    placed = place_entry_calls(env)
    decisions = await _placement_decision(env, first)
    gap["place_entry_calls"] = placed
    gap["placement_refusal"] = decisions[-1]["reason"] if decisions else None
    if placed != 0 or not decisions or not decisions[-1]["refused"]:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_ENTRY_IN_GAP,
            f"{placed} place_entry call(s), placement decisions {decisions}",
        )
    record_step(
        env,
        recorder,
        STEP_ENTRY_IN_GAP,
        f"the CONFIRM pressed while the stream was {_stream_state(env).value} placed nothing "
        f"(refused: {gap['placement_refusal']})",
    )
    reason = getattr(wiring.safe_mode, "entered_reason", None)
    gap["safe_mode_reason"] = reason
    gap["silence_bound_ms"] = silence_bound_ms(env)
    if not wiring.safe_mode.in_safe_mode or reason not in SILENCE_REASONS:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_SILENCE,
            f"SAFE_MODE {wiring.safe_mode.in_safe_mode}, reason {reason}; expected one of "
            f"{SILENCE_REASONS}",
        )
    record_step(
        env,
        recorder,
        STEP_SILENCE,
        f"the silent stream (bound {gap['silence_bound_ms']} ms) entered SAFE_MODE {reason}",
    )

    # ---- the exit is refused while the stream is not LIVE (exit row 7) ------------------------ #
    await env.owner.act("safemode_exit")
    await _ticks(env, 2)
    refused = bool(wiring.safe_mode.in_safe_mode) and _stream_state(env) is not StreamState.LIVE
    gap["exit_refused_while_not_live"] = refused
    gap["exit_refusals"] = _exit_refusals(env)
    if not refused:
        raise dr._smoke_fail(
            env, recorder, STEP_EXIT_REFUSED, "SAFE_MODE was left while the stream was not LIVE"
        )
    record_step(
        env,
        recorder,
        STEP_EXIT_REFUSED,
        f"/safemode_exit was refused while the stream was not LIVE ({gap['exit_refusals']})",
    )

    # ---- a halted stream does not resync by itself (finding F1) ------------------------------- #
    mark = len(watcher.transitions)
    rebuilds_before = trigger.calls().get("rebuild", 0)
    await env.pause(recovery_window_seconds(env))
    await _ticks(env, 2)
    window = {
        "state": _stream_state(env).value,
        "new_transitions": len(watcher.transitions) - mark,
        "rebuild_calls_before": rebuilds_before,
        "rebuild_calls_after": trigger.calls().get("rebuild", 0),
    }
    gap["no_self_resync"] = window
    if window["state"] != StreamState.UNKNOWN.value or window["new_transitions"] != 0:
        raise dr._smoke_fail(
            env, recorder, STEP_NO_SELF_RESYNC, f"the halted stream moved by itself: {window}"
        )
    record_step(
        env,
        recorder,
        STEP_NO_SELF_RESYNC,
        f"{recovery_window_seconds(env)} s after the halt the stream is still UNKNOWN; nothing in "
        "src asks for a resync (finding F1)",
    )

    # ---- back to LIVE, the documented exit, then entries are allowed again -------------------- #
    await _restore_stream(env, recorder, trigger, watcher)
    await _leave_safe_mode(env, recorder, STEP_SAFE_MODE_EXIT)
    await _expire_plan(env, first)
    second = await place_approved_entry(env, recorder, SCENARIO_FAR)
    if place_entry_calls(env) != 1:
        raise dr._smoke_fail(
            env, recorder, STEP_ENTRY_AFTER_EXIT, "the entry after the exit was not placed once"
        )
    record_step(
        env,
        recorder,
        STEP_ENTRY_AFTER_EXIT,
        "after the stream was LIVE and SAFE_MODE was left, an entry was placed and acknowledged",
    )

    # ---- an order change the stream never delivered is found by the REST reconcile ------------ #
    await _catch_up(env, recorder, trigger, watcher, second)
    await _leave_safe_mode(env, recorder, STEP_SAFE_MODE_EXIT)
    await _expire_plan(env, second)

    # ---- listenKeyExpired restarts the stream and reconciles ----------------------------------- #
    return await _expiry(env, recorder, trigger, watcher)


async def _catch_up(
    env: Any,
    recorder: ScenarioRecorder,
    trigger: StreamTrigger,
    watcher: StateWatcher,
    first: Any,
) -> None:
    snapshots_before = _snapshot_calls(env)
    await _drop(env, recorder, trigger, watcher)
    await trigger.change_order_during_gap(env, first)
    await _ticks(env, 2 * dr.SMOKE_REPLAY_SETTLE_TICKS)
    facts: dict[str, Any] = recorder.details.setdefault("catch_up", {})
    facts["stream_items_queued"] = trigger.queued_items()
    facts["protection_state_in_gap"] = _protection_state(env, first.plan_hash)
    await _restore_stream(env, recorder, trigger, watcher)
    await _ticks(env)
    facts["protection_state"] = _protection_state(env, first.plan_hash)
    facts["snapshot_calls_before"] = snapshots_before
    facts["snapshot_calls_after"] = _snapshot_calls(env)
    caught = (
        facts["stream_items_queued"] == 0
        and facts["protection_state"] == ProtectionState.ENTRY_ENDED_NO_FILL.value
        and facts["snapshot_calls_after"] > facts["snapshot_calls_before"]
    )
    if not caught:
        raise dr._smoke_fail(
            env, recorder, STEP_CATCH_UP, f"the reconcile did not catch up: {facts}"
        )
    record_step(
        env,
        recorder,
        STEP_CATCH_UP,
        "the entry was cancelled on the exchange while the stream was down and no frame was "
        f"delivered; the REST reconcile moved the plan to {facts['protection_state']}",
    )


async def _expiry(
    env: Any, recorder: ScenarioRecorder, trigger: StreamTrigger, watcher: StateWatcher
) -> str:
    """The expiry step; returns COMPLETE if it was observed, COMPLETE_WITH_GAPS otherwise."""
    mark = len(watcher.transitions)
    snapshots_before = _snapshot_calls(env)
    rekeys_before = trigger.calls().get("rekey", 0)
    answer = await trigger.expire(env, watcher)
    if answer != "EXPIRED":
        record_gap(env, recorder, STEP_EXPIRY, answer)
        return dr.OUTCOME_COMPLETE_WITH_GAPS
    await env.pause(0)
    if not await _wait_state(env, StreamState.LIVE):
        raise dr._smoke_fail(env, recorder, STEP_EXPIRY, "the stream did not return to LIVE")
    await _ticks(env)
    seen = [[state, reason] for state, reason in watcher.since(mark)]
    facts: dict[str, Any] = recorder.details.setdefault("expiry", {})
    facts["transitions"] = seen
    facts["rekey_calls"] = trigger.calls().get("rekey", 0) - rekeys_before
    facts["live_entries"] = sum(1 for state, _reason in seen if state == StreamState.LIVE.value)
    facts["snapshot_calls_before"] = snapshots_before
    facts["snapshot_calls_after"] = _snapshot_calls(env)
    facts["safe_mode"] = bool(env.wiring.safe_mode.in_safe_mode)
    first_reason = seen[0] if seen else None
    if (
        first_reason != ["UNKNOWN", "LISTEN_KEY_EXPIRED"]
        or facts["live_entries"] != 1
        or facts["safe_mode"]
        or facts["snapshot_calls_after"] <= facts["snapshot_calls_before"]
    ):
        raise dr._smoke_fail(env, recorder, STEP_EXPIRY, f"after the expiry: {facts}")
    record_injection_step(
        env,
        recorder,
        f"listenKeyExpired was reported; the supervisor restarted the stream ({seen}) and the "
        "after-gap REST snapshot ran; no second LIVE entry, SAFE_MODE stayed off",
        name=STEP_EXPIRY,
    )
    return dr.OUTCOME_COMPLETE


# ---- the early-confirm variant (twin) ---------------------------------------------------------- #


async def _early_sequence(
    env: Any, recorder: ScenarioRecorder, trigger: StreamTrigger, watcher: StateWatcher
) -> str:
    """CONFIRM right after the drop, before any reconcile tick: SAFE_MODE is not on yet."""
    wiring = env.wiring
    first = await _card_and_approve(env, recorder)
    await _drop(env, recorder, trigger, watcher)
    verdict = await health_verdict(env, recorder)
    await env.owner.act("confirm", short_id=first.short_id, note="")
    placed = place_entry_calls(env)
    decisions = await _placement_decision(env, first)
    facts: dict[str, Any] = recorder.details.setdefault("early_confirm", {})
    facts["health_no_trade_at_confirm"] = bool(verdict.is_no_trade)
    facts["place_entry_calls"] = placed
    facts["safe_mode_at_confirm"] = bool(wiring.safe_mode.in_safe_mode)
    facts["placement_refusal"] = decisions[-1]["reason"] if decisions else None
    if placed != 0 or not decisions or not decisions[-1]["refused"]:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_ENTRY_IN_GAP,
            f"{placed} place_entry call(s), placement decisions {decisions}",
        )
    record_step(
        env,
        recorder,
        STEP_ENTRY_IN_GAP,
        f"the CONFIRM pressed right after the drop, before SAFE_MODE (on: "
        f"{facts['safe_mode_at_confirm']}), placed nothing (refused: {facts['placement_refusal']})",
    )
    await _expire_plan(env, first)
    await _restore_stream(env, recorder, trigger, watcher)
    await _leave_safe_mode(env, recorder, STEP_SAFE_MODE_EXIT)
    return dr.OUTCOME_COMPLETE


# ---- the Demo sequence: the supervisor's own rebuild ------------------------------------------ #


async def _demo_sequence(
    env: Any, recorder: ScenarioRecorder, trigger: StreamTrigger, watcher: StateWatcher
) -> str:
    first = await place_approved_entry(env, recorder, SCENARIO_FAR)
    snapshots_before = _snapshot_calls(env)
    mark = len(watcher.transitions)
    await trigger.drop(env)
    record_injection_step(
        env,
        recorder,
        "a close event of the current connection was injected; the supervisor runs its own rebuild",
        name=STEP_DROP,
    )

    async def recovered() -> bool:
        seen = [state for state, _reason in watcher.since(mark)]
        return StreamState.UNKNOWN.value in seen and _stream_state(env) is StreamState.LIVE

    if not await dr._wait_until(env, recovered):
        raise dr._smoke_fail(
            env, recorder, STEP_RESTORED, f"the supervisor reported {watcher.since(mark)}"
        )
    seen = [[state, reason] for state, reason in watcher.since(mark)]
    record_step(env, recorder, STEP_RESTORED, f"the supervisor rebuilt the stream: {seen}")
    await _ticks(env)
    snapshots_after = _snapshot_calls(env)
    state = _protection_state(env, first.plan_hash)
    recorder.details["catch_up"] = {
        "snapshot_calls_before": snapshots_before,
        "snapshot_calls_after": snapshots_after,
        "protection_state": state,
    }
    if snapshots_after <= snapshots_before:
        raise dr._smoke_fail(env, recorder, STEP_CATCH_UP, "no REST snapshot ran after the gap")
    record_step(
        env,
        recorder,
        STEP_CATCH_UP,
        "the after-gap REST snapshot and the reconcile ran; the resting entry is unchanged "
        f"(plan state {state})",
    )
    why = (
        "the supervisor rebuilt the stream within seconds, so no gap was held open; this is "
        "rehearsed on the twin"
    )
    for name in (STEP_GAP_HEALTH, STEP_ENTRY_IN_GAP, STEP_SILENCE, STEP_NO_SELF_RESYNC):
        record_gap(env, recorder, name, why)
    outcome = await _expiry(env, recorder, trigger, watcher)
    await cancel_resting_entry(env, recorder, first)
    # The gap steps above are never produced on Demo: the outcome says so whatever `outcome` is.
    del outcome
    return dr.OUTCOME_COMPLETE_WITH_GAPS
