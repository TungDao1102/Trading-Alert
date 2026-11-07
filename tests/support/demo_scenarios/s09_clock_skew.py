"""S09 clock skew: the drift guard blocks entries before anything is sent (plan 25-13; OPS-01).

TEST_ONLY. The scenario receives an env whose process clock is ALREADY skewed beyond the ratified
drift limit; the skew is never computed from a literal here (`skew_for` is twice the larger of the
two loaded limits, the same function the owner's Demo test passes to `EnvOptions(clock_offset=)`).
The real `ClockDriftGuard` of the process measures it and blocks new entries (D-14). Then a request
is approved and confirmed and must place nothing; the refusal is journaled. The scenario starts
the process with `start_tolerant` (the smoke's `_bring_up` would stop at the blocked guard before
any card, which is its own, already tested job).

Twin: `install_twin_skew` answers the server time `skew` behind the process clock, so the REAL
measurement (`measure_clock_drift`, `evaluate_clock_drift`) finds the offset, and calls the real
adapter's own `_require_entries_allowed` ahead of the fake's `place_entry` (the fake serves
`place_entry`, the real adapter never runs it on the twin). Demo: the process clock is skewed by
`EnvOptions.clock_offset` and Binance's own server time is the reference.

Research assumption A3: the SDK stamps requests from the system clock, not the injected clock, so
signed calls are expected to succeed. If Binance answers -1021 instead, the guard has a re-measure
pending (`minus_1021_seen`); the scenario records that and still asserts nothing was placed. The
exchange-side -1021 stays with the owner opt-in probe case `timestamp_outside_recv_window`.

The skew is the injected trigger (`label_for(env, injected=True)`); the guard and the refusal are
the real reaction (the env label).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from scripts import demo_rehearsal as dr
from src.adapters.binance_clock import ClockDriftGuard
from src.adapters.binance_limits import DriftLimits, load_binance_limits
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME
from src.live.runtime import BINANCE_LIMITS_RELATIVE, REPO_ROOT

from tests.support.demo_scenarios.harness import (
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
    read_account_counts,
)
from tests.support.demo_scenarios.s03_crossed_stop import placement_rows
from tests.support.demo_scenarios.s04_stop_rejected import record_injection_step, record_step
from tests.support.demo_scenarios.s06_replay import shutdown, start_evidence
from tests.support.demo_scenarios.s07_restart_cuts import start_tolerant
from tests.support.demo_scenarios.s08_stream_loss import card_and_approve, expire_plan, ticks

STEP_SKEW = "clock_skew_injected"
STEP_GUARD = "drift_guard_blocks_entries"
STEP_NOTHING_PLACED = "confirm_places_nothing"
STEP_JOURNALED = "refusal_journaled"


def skew_for(limits: DriftLimits) -> timedelta:
    """Twice the larger of the two ratified drift limits (host ahead of, or behind, Binance)."""
    return timedelta(milliseconds=2 * max(limits.ahead_limit_ms, limits.behind_limit_ms))


def loaded_drift_limits() -> DriftLimits:
    """The ratified drift limits the real process loads (for the Demo test's `clock_offset`)."""
    return load_binance_limits(REPO_ROOT / BINANCE_LIMITS_RELATIVE).drift


def install_twin_skew(env: Any) -> timedelta:
    """Twin only: skew what the real guard measures and route `place_entry` through its check."""
    if not env.synthetic:
        raise ValueError(
            "install_twin_skew is for the twin; a Demo env uses EnvOptions.clock_offset"
        )
    skew = skew_for(env.assembly.binance_limits.drift)
    inner = env.faults.inner
    real = inner._real  # the real BinanceUsdmAdapter under the composed edge

    async def server_time() -> datetime:
        return env.clock() - skew

    async def guarded_place_entry(**kwargs: Any) -> Any:
        real._require_entries_allowed()  # EntriesBlocked, exactly as the real place_entry raises it
        return await inner.place_entry(**kwargs)

    env.faults.override("server_time", server_time, times=None)
    env.faults.override("place_entry", guarded_place_entry, times=None)
    return skew


def drift_answer(guard: ClockDriftGuard, now_utc: datetime) -> dict[str, Any]:
    """What the guard says at `now_utc`: facts only (never an id, never exchange text)."""
    verdict = guard.last_verdict
    reason = guard.blocked_reason(now_utc)
    return {
        "blocked_reason": None if reason is None else reason.value,
        "offset_ms": None if verdict is None else verdict.offset_ms,
        "within_limits": None if verdict is None else verdict.within_limits,
        "measurement_failed": None if verdict is None else verdict.measurement_failed,
        "minus_1021_seen": bool(guard.remeasure_requested),
    }


def record_skew(env: Any, recorder: ScenarioRecorder, detail: str) -> None:
    """The injected trigger: DEMO_FAULT_INJECTED on Demo, never DEMO_OBSERVED."""
    record_injection_step(env, recorder, detail, name=STEP_SKEW)


def record_reaction(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A reaction of the real process: the env label."""
    record_step(env, recorder, name, detail)


def _reason_of(event_type: str, payload: dict[str, Any]) -> str | None:
    key = "reason_code" if event_type == EVENT_PLACEMENT_OUTCOME else "reason"
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _refused(event_type: str, payload: dict[str, Any]) -> bool:
    return payload.get("is_no_trade") is True if event_type == EVENT_PLACEMENT_OUTCOME else True


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S09 on an already skewed `env`; returns the outcome. A failed step raises SmokeHalt."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder)
    finally:
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder) -> str:
    start_evidence(env, recorder)
    await start_tolerant(env, recorder, "start")
    drift = env.assembly.binance_limits.drift
    facts: dict[str, Any] = recorder.details.setdefault("clock_skew", {})
    facts["skew_ms"] = int(skew_for(drift) / timedelta(milliseconds=1))
    facts["ahead_limit_ms"] = int(drift.ahead_limit_ms)
    facts["behind_limit_ms"] = int(drift.behind_limit_ms)
    record_skew(
        env,
        recorder,
        f"the process clock is skewed by {facts['skew_ms']} ms, twice the larger drift limit "
        f"({facts['ahead_limit_ms']} ms ahead, {facts['behind_limit_ms']} ms behind)",
    )

    guard = env.assembly.exchange.drift_guard
    facts.update(drift_answer(guard, env.clock()))
    if facts["blocked_reason"] is None:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_GUARD,
            f"the drift guard does not block entries despite a {facts['skew_ms']} ms skew "
            f"(offset {facts['offset_ms']} ms): the env was not skewed",
        )
    record_reaction(
        env,
        recorder,
        STEP_GUARD,
        f"the guard measured an offset of {facts['offset_ms']} ms and blocks new entries "
        f"({facts['blocked_reason']}); a -1021 pending: {facts['minus_1021_seen']}",
    )

    wiring = env.wiring
    first = await card_and_approve(env, recorder)
    await env.owner.act("confirm", short_id=first.short_id, note="")

    async def refused() -> bool:
        rows = await env.assembly.executor.read(
            placement_rows, wiring.stores.journal, wiring.stores.shadow, first.trade_plan_id
        )
        return bool(rows)

    if not await dr._wait_until(env, refused):
        raise dr._smoke_fail(env, recorder, STEP_JOURNALED, "CONFIRM left no journaled outcome")
    rows = await env.assembly.executor.read(
        placement_rows, wiring.stores.journal, wiring.stores.shadow, first.trade_plan_id
    )
    event_type, payload = rows[0]
    facts["refusal_event"] = event_type
    facts["refusal_reason"] = _reason_of(event_type, payload)
    facts["refusal_refused"] = _refused(event_type, payload)
    counts = await read_account_counts(env)
    facts["orders_after_confirm"] = counts.normal_orders
    facts["positions_after_confirm"] = counts.positions
    if counts.normal_orders or counts.algo_orders or counts.positions:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_NOTHING_PLACED,
            f"the account holds {counts.normal_orders} order(s), {counts.algo_orders} algo "
            f"order(s), {counts.positions} position(s) after the CONFIRM",
        )
    record_reaction(
        env,
        recorder,
        STEP_NOTHING_PLACED,
        "the approved and confirmed request placed nothing: no order, algo order or position",
    )
    if not facts["refusal_refused"] or not facts["refusal_reason"]:
        raise dr._smoke_fail(
            env, recorder, STEP_JOURNALED, f"the journaled row is {event_type}, not a refusal"
        )
    record_reaction(
        env,
        recorder,
        STEP_JOURNALED,
        f"the refusal is journaled ({event_type}: {facts['refusal_reason']})",
    )

    await expire_plan(env, first)
    await ticks(env)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE
