"""DEMO enablement, the D058 mark gate and the kill-gate switch-off (plan 24-22; D-27, D-28, Q5).

Evidence label: executed unit tests with fakes; the rig tests drive the real approval desk, confirm
flow, execution service and manager over the Binance-semantics fake exchange (tests/support/
live_rig.py). Nothing touches Binance, Telegram or a database. Times are TEST_ONLY.

Pinned:

* `enable_demo` is DEMO only: LIVE (and TESTNET) raise before the controller is touched;
* it enables only from a verdict judged for DEMO that is OK (a stale mark price is a FAIL, D058),
  with an evaluated kill-gate state that is not INSUFFICIENT_EDGE;
* a persisted "enabled" is never trusted: every start is DISABLED;
* the kill gate can only switch off; `src/live` calls `.enable(` only inside `enable_demo`.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_client import Environment
from src.domain.enums import KillGateState, SystemStateKey
from src.domain.journal import JournalEvent
from src.execution.enablement import LiveEnablementController
from src.live.enablement import (
    ACTION_ALREADY_DISABLED,
    ACTION_DISABLED,
    ACTION_NO_CHANGE,
    DEMO_RUNTIME_OPERATOR_ID,
    EVENT_ENABLE_REFUSED,
    EVENT_ENABLEMENT_RESET_AT_START,
    KILL_GATE_OPERATOR_ID,
    REASON_ALREADY_ENABLED,
    REASON_ENABLED,
    REASON_HEALTH_NOT_OK,
    REASON_KILL_GATE_INSUFFICIENT_EDGE,
    REASON_KILL_GATE_UNEVALUATED,
    REASON_VERDICT_NOT_FOR_DEMO,
    LiveEnableForbidden,
    enable_demo,
    kill_gate_tick_once,
    on_kill_gate_verdict,
    persist_enablement_snapshot,
    start_disabled,
)
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME
from src.ops.health import (
    ALL_CHECK_NAMES,
    CHECK_LAST_CLOSED_CANDLE_TIME,
    CHECK_MARKET_FEED_FRESHNESS,
    HealthCheckResult,
    HealthRuntimeMode,
    HealthVerdict,
    run_health_checks,
)

from tests.shadow_fakes import T0
from tests.support.live_rig import TEST_ONLY_OPERATOR, forbid_real_sleep, make_live_rig
from tests.test_kill_gate_state import evaluate_case
from tests.test_live_health import Parts

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)
SRC_LIVE = Path(__file__).resolve().parents[1] / "src" / "live"


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #


class Journal:
    """The controller's synchronous journal."""

    def __init__(self) -> None:
        self.events: list[JournalEvent] = []

    def record(self, event: Any) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.event_type for e in self.events]


class Recorder:
    """The async journal writer of the tick bodies."""

    def __init__(self) -> None:
        self.events: list[JournalEvent] = []

    async def __call__(self, event: JournalEvent) -> None:
        self.events.append(event)

    def of(self, event_type: str) -> list[JournalEvent]:
        return [e for e in self.events if e.event_type == event_type]


class StoredRecord:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state


class FakeStateStore:
    """`PgSystemStateStore` as the module uses it."""

    def __init__(self, latest: StoredRecord | None = None) -> None:
        self.stored = latest
        self.appended: list[tuple[SystemStateKey, dict[str, Any]]] = []

    def append(self, key: SystemStateKey, state: Any, *, now_utc: datetime) -> None:
        self.appended.append((key, dict(state)))

    def latest(self, key: SystemStateKey) -> StoredRecord | None:
        assert key is SystemStateKey.LIVE_ENABLEMENT
        return self.stored


async def inline_write(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


def results_with(
    *, status_of: dict[str, str] | None = None, degraded: tuple[str, ...] = ()
) -> list[HealthCheckResult]:
    status_of = status_of or {}
    return [
        HealthCheckResult(
            check_name=name,
            status=status_of.get(name, "DEGRADED" if name in degraded else "PASS"),
            detail="x",
            observed_at_utc=NOW,
        )
        for name in ALL_CHECK_NAMES
    ]


def demo_verdict() -> HealthVerdict:
    return run_health_checks(
        results=results_with(degraded=(CHECK_LAST_CLOSED_CANDLE_TIME,)),
        mode=HealthRuntimeMode.DEMO,
        demo_degraded_allowed=True,
    )


def new_controller() -> tuple[LiveEnablementController, Journal]:
    journal = Journal()
    return LiveEnablementController(journal=journal), journal


# --------------------------------------------------------------------------- #
# enable_demo - the rules.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", [Environment.LIVE, Environment.TESTNET])
async def test_enable_demo_raises_before_touching_the_controller_outside_demo(
    mode: Environment,
) -> None:
    controller, journal = new_controller()
    recorder = Recorder()
    with pytest.raises(LiveEnableForbidden):
        await enable_demo(
            mode=mode,
            controller=controller,
            health_verdict=demo_verdict(),
            kill_gate_state=KillGateState.WITHIN_BUDGET,
            now_utc=NOW,
            record=recorder,
        )
    assert controller.is_disabled
    assert journal.events == [] and recorder.events == []


async def test_a_healthy_demo_start_enables_with_the_fixed_operator_and_persists() -> None:
    controller, journal = new_controller()
    store = FakeStateStore()
    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=controller,
        health_verdict=demo_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
        now_utc=NOW,
        record=Recorder(),
        persist=lambda: persist_enablement_snapshot(
            controller, state_store=store, write=inline_write, now_utc=NOW
        ),
    )
    assert outcome.enabled and outcome.reason == REASON_ENABLED and outcome.persisted
    assert controller.is_disabled is False
    assert controller.operator_id == DEMO_RUNTIME_OPERATOR_ID
    assert journal.types() == ["LIVE_ORDERS_ENABLED"]
    assert json.loads(journal.events[0].payload_json)["operator_id"] == DEMO_RUNTIME_OPERATOR_ID
    ((key, snapshot),) = store.appended
    assert key is SystemStateKey.LIVE_ENABLEMENT
    assert snapshot == {
        "disabled": False,
        "enabled_at_utc": NOW.isoformat(),
        "operator_id": DEMO_RUNTIME_OPERATOR_ID,
    }


async def test_a_stale_mark_price_refuses_the_enable_and_names_the_check() -> None:
    parts = Parts()
    parts.mark("BTCUSDT", age_seconds=300)  # D058: stale mark price
    producer = parts.producer()
    verdict = producer.verdict(producer.produce(now_utc=NOW))
    controller, journal = new_controller()
    recorder = Recorder()
    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=controller,
        health_verdict=verdict,
        kill_gate_state=KillGateState.WITHIN_BUDGET,
        now_utc=NOW,
        record=recorder,
    )
    assert outcome.enabled is False
    assert outcome.reason == REASON_HEALTH_NOT_OK
    assert outcome.failing == (CHECK_MARKET_FEED_FRESHNESS,)
    assert controller.is_disabled
    assert journal.events == [], "the controller wrote nothing"
    (event,) = recorder.of(EVENT_ENABLE_REFUSED)
    document = json.loads(event.payload_json)
    assert document["failing"] == [CHECK_MARKET_FEED_FRESHNESS]
    assert document["reason"] == REASON_HEALTH_NOT_OK
    assert document["mode"] == "DEMO"


async def test_a_missing_mark_price_also_refuses_the_enable() -> None:
    parts = Parts()
    producer = parts.producer(symbols=("BTCUSDT", "SOLUSDT"))
    verdict = producer.verdict(producer.produce(now_utc=NOW))
    controller, _ = new_controller()
    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=controller,
        health_verdict=verdict,
        kill_gate_state=KillGateState.WITHIN_BUDGET,
        now_utc=NOW,
        record=Recorder(),
    )
    assert outcome.enabled is False and CHECK_MARKET_FEED_FRESHNESS in outcome.failing


async def test_a_degraded_verdict_without_the_flag_names_the_degraded_check() -> None:
    verdict = run_health_checks(
        results=results_with(degraded=(CHECK_LAST_CLOSED_CANDLE_TIME,)),
        mode=HealthRuntimeMode.DEMO,
    )
    controller, _ = new_controller()
    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=controller,
        health_verdict=verdict,
        kill_gate_state=KillGateState.WITHIN_BUDGET,
        now_utc=NOW,
        record=Recorder(),
    )
    assert outcome.enabled is False
    assert outcome.failing == (CHECK_LAST_CLOSED_CANDLE_TIME,)


@pytest.mark.parametrize(
    "verdict",
    [
        run_health_checks(results=results_with()),  # legacy call: no mode
        run_health_checks(results=results_with(), mode=HealthRuntimeMode.LIVE),
    ],
    ids=["legacy_no_mode", "live_verdict"],
)
async def test_a_verdict_not_judged_for_demo_is_refused_even_when_ok(
    verdict: HealthVerdict,
) -> None:
    assert verdict.is_no_trade is False
    controller, _ = new_controller()
    recorder = Recorder()
    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=controller,
        health_verdict=verdict,
        kill_gate_state=KillGateState.WITHIN_BUDGET,
        now_utc=NOW,
        record=recorder,
    )
    assert outcome.enabled is False and outcome.reason == REASON_VERDICT_NOT_FOR_DEMO
    assert controller.is_disabled
    assert len(recorder.of(EVENT_ENABLE_REFUSED)) == 1


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (None, REASON_KILL_GATE_UNEVALUATED),
        (KillGateState.INSUFFICIENT_EDGE, REASON_KILL_GATE_INSUFFICIENT_EDGE),
    ],
)
async def test_an_unevaluated_or_terminal_kill_gate_refuses_the_enable(
    state: KillGateState | None, reason: str
) -> None:
    controller, _ = new_controller()
    recorder = Recorder()
    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=controller,
        health_verdict=demo_verdict(),
        kill_gate_state=state,
        now_utc=NOW,
        record=recorder,
    )
    assert outcome.enabled is False and outcome.reason == reason
    assert controller.is_disabled
    assert len(recorder.of(EVENT_ENABLE_REFUSED)) == 1


@pytest.mark.parametrize("state", [KillGateState.WITHIN_BUDGET, KillGateState.PASSING_CANDIDATE])
async def test_the_non_terminal_kill_gate_states_allow_the_enable(state: KillGateState) -> None:
    controller, _ = new_controller()
    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=controller,
        health_verdict=demo_verdict(),
        kill_gate_state=state,
        now_utc=NOW,
        record=Recorder(),
    )
    assert outcome.enabled is True and controller.is_disabled is False


async def test_a_second_enable_changes_nothing() -> None:
    controller, journal = new_controller()
    kwargs: dict[str, Any] = {
        "mode": Environment.DEMO,
        "controller": controller,
        "health_verdict": demo_verdict(),
        "kill_gate_state": KillGateState.WITHIN_BUDGET,
        "now_utc": NOW,
        "record": Recorder(),
    }
    await enable_demo(**kwargs)
    again = await enable_demo(**kwargs)
    assert again.reason == REASON_ALREADY_ENABLED
    assert journal.types() == ["LIVE_ORDERS_ENABLED"]


async def test_a_failed_snapshot_write_does_not_undo_the_enable() -> None:
    controller, _ = new_controller()

    async def broken() -> None:
        raise OSError("db down")

    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=controller,
        health_verdict=demo_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
        now_utc=NOW,
        record=Recorder(),
        persist=broken,
    )
    assert outcome.enabled is True and outcome.persisted is False
    assert controller.is_disabled is False


# --------------------------------------------------------------------------- #
# A restart never trusts a stored "enabled".
# --------------------------------------------------------------------------- #

ENABLED_SNAPSHOT = {
    "disabled": False,
    "enabled_at_utc": "2026-10-30T09:00:00+00:00",
    "operator_id": DEMO_RUNTIME_OPERATOR_ID,
}


async def read_inline(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


async def test_a_restart_with_a_stored_enabled_snapshot_starts_disabled_and_resets_it() -> None:
    store = FakeStateStore(StoredRecord(dict(ENABLED_SNAPSHOT)))
    recorder = Recorder()
    started = await start_disabled(
        journal=Journal(),
        state_store=store,
        read=read_inline,
        write=inline_write,
        record=recorder,
        now_utc=NOW,
    )
    assert started.controller.is_disabled is True
    assert started.persisted_enabled is True
    (reset,) = recorder.of(EVENT_ENABLEMENT_RESET_AT_START)
    assert json.loads(reset.payload_json) == {"persisted_enabled": True, "problem": None}
    ((key, snapshot),) = store.appended
    assert key is SystemStateKey.LIVE_ENABLEMENT
    assert snapshot == {"disabled": True, "enabled_at_utc": None, "operator_id": None}


async def test_only_a_fresh_enable_demo_after_the_start_enables_it() -> None:
    store = FakeStateStore(StoredRecord(dict(ENABLED_SNAPSHOT)))
    started = await start_disabled(
        journal=Journal(),
        state_store=store,
        read=read_inline,
        write=inline_write,
        record=Recorder(),
        now_utc=NOW,
    )
    assert started.controller.guard_placement(plan_hash="h").is_no_trade is True
    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=started.controller,
        health_verdict=demo_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
        now_utc=NOW,
        record=Recorder(),
    )
    assert outcome.enabled is True
    assert started.controller.guard_placement(plan_hash="h").is_no_trade is False


@pytest.mark.parametrize(
    "stored",
    [None, StoredRecord({"disabled": True, "enabled_at_utc": None, "operator_id": None})],
    ids=["never_stored", "stored_disabled"],
)
async def test_a_disabled_or_missing_snapshot_writes_nothing_at_start(
    stored: StoredRecord | None,
) -> None:
    store = FakeStateStore(stored)
    recorder = Recorder()
    started = await start_disabled(
        journal=Journal(),
        state_store=store,
        read=read_inline,
        write=inline_write,
        record=recorder,
        now_utc=NOW,
    )
    assert started.controller.is_disabled and not started.persisted_enabled
    assert recorder.events == [] and store.appended == []


async def test_a_malformed_snapshot_starts_disabled_and_is_reported_without_its_value() -> None:
    store = FakeStateStore(StoredRecord({"disabled": "no", "secret_like": "abc123"}))
    recorder = Recorder()
    started = await start_disabled(
        journal=Journal(),
        state_store=store,
        read=read_inline,
        write=inline_write,
        record=recorder,
        now_utc=NOW,
    )
    assert started.controller.is_disabled
    assert started.persisted_problem == "STORED_ENABLEMENT_STATE_MALFORMED"
    (reset,) = recorder.of(EVENT_ENABLEMENT_RESET_AT_START)
    assert "abc123" not in reset.payload_json
    assert len(store.appended) == 1


async def test_an_unreachable_store_refuses_the_start() -> None:
    async def failing_read(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        raise OSError("db down")

    with pytest.raises(OSError):
        await start_disabled(
            journal=Journal(),
            state_store=FakeStateStore(),
            read=failing_read,
            write=inline_write,
            record=Recorder(),
            now_utc=NOW,
        )


# --------------------------------------------------------------------------- #
# Through the live rig: the manager's gate 2.
# --------------------------------------------------------------------------- #


async def test_before_enable_demo_a_confirm_ends_in_no_trade_disabled_with_no_placement() -> None:
    rig = await make_live_rig()
    rig.enablement.disable(operator_id=TEST_ONLY_OPERATOR, now_utc=T0)
    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    assert rig.fake.calls_to("place_entry") == []
    (outcome,) = rig.journal.by_type(EVENT_PLACEMENT_OUTCOME)
    assert json.loads(outcome.payload_json) == {"is_no_trade": True, "reason_code": "DISABLED"}


async def test_after_enable_demo_the_same_confirm_places_exactly_one_entry() -> None:
    rig = await make_live_rig()
    rig.enablement.disable(operator_id=TEST_ONLY_OPERATOR, now_utc=T0)
    outcome = await enable_demo(
        mode=Environment.DEMO,
        controller=rig.enablement,
        health_verdict=demo_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
        now_utc=T0,
        record=Recorder(),
    )
    assert outcome.enabled
    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    assert len(rig.fake.calls_to("place_entry")) == 1


async def test_a_kill_gate_switch_off_stops_later_entries_in_the_rig() -> None:
    rig = await make_live_rig()  # enabled by the rig
    result = await on_kill_gate_verdict(
        controller=rig.enablement, state=KillGateState.INSUFFICIENT_EDGE, now_utc=T0
    )
    assert result.action == ACTION_DISABLED
    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    assert rig.fake.calls_to("place_entry") == []
    (outcome,) = rig.journal.by_type(EVENT_PLACEMENT_OUTCOME)
    assert json.loads(outcome.payload_json)["reason_code"] == "DISABLED"


# --------------------------------------------------------------------------- #
# The kill gate: only toward disabled.
# --------------------------------------------------------------------------- #


async def enabled_controller() -> tuple[LiveEnablementController, Journal]:
    controller, journal = new_controller()
    await enable_demo(
        mode=Environment.DEMO,
        controller=controller,
        health_verdict=demo_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
        now_utc=NOW,
        record=Recorder(),
    )
    return controller, journal


async def test_insufficient_edge_while_enabled_disables_once_and_is_journaled() -> None:
    controller, journal = await enabled_controller()
    persisted: list[int] = []

    async def persist() -> None:
        persisted.append(1)

    first = await on_kill_gate_verdict(
        controller=controller,
        state=KillGateState.INSUFFICIENT_EDGE,
        now_utc=NOW,
        persist=persist,
    )
    second = await on_kill_gate_verdict(
        controller=controller,
        state=KillGateState.INSUFFICIENT_EDGE,
        now_utc=NOW,
        persist=persist,
    )
    assert (first.action, second.action) == (ACTION_DISABLED, ACTION_ALREADY_DISABLED)
    assert journal.types() == ["LIVE_ORDERS_ENABLED", "LIVE_ORDERS_DISABLED"]
    assert json.loads(journal.events[1].payload_json)["operator_id"] == KILL_GATE_OPERATOR_ID
    assert controller.guard_placement(plan_hash="h").reason_code == "DISABLED"
    assert persisted == [1]


@pytest.mark.parametrize(
    "state", [None, KillGateState.WITHIN_BUDGET, KillGateState.PASSING_CANDIDATE]
)
async def test_any_other_verdict_calls_neither_enable_nor_disable(
    state: KillGateState | None,
) -> None:
    controller, journal = await enabled_controller()
    before = list(journal.events)
    result = await on_kill_gate_verdict(controller=controller, state=state, now_utc=NOW)
    assert result.action == ACTION_NO_CHANGE
    assert journal.events == before
    assert controller.is_disabled is False

    disabled, disabled_journal = new_controller()
    await on_kill_gate_verdict(controller=disabled, state=state, now_utc=NOW)
    assert disabled.is_disabled is True, "a kill-gate event never enables"
    assert disabled_journal.events == []


async def test_the_tick_body_reads_the_source_and_acts_toward_off_only() -> None:
    controller, _ = await enabled_controller()
    states = iter([KillGateState.PASSING_CANDIDATE, KillGateState.INSUFFICIENT_EDGE])

    async def source() -> KillGateState | None:
        return next(states)

    first = await kill_gate_tick_once(controller=controller, source=source, now_utc=NOW)
    assert first.action == ACTION_NO_CHANGE and controller.is_disabled is False
    second = await kill_gate_tick_once(controller=controller, source=source, now_utc=NOW)
    assert second.action == ACTION_DISABLED and controller.is_disabled is True


async def test_a_real_kill_gate_verdict_drives_the_switch_off() -> None:
    controller, _ = await enabled_controller()
    verdict = evaluate_case("kill_insufficient_edge")
    result = await on_kill_gate_verdict(controller=controller, state=verdict.state, now_utc=NOW)
    assert result.action == ACTION_DISABLED
    again = evaluate_case("kill_within_budget")
    nothing = await on_kill_gate_verdict(controller=controller, state=again.state, now_utc=NOW)
    assert nothing.action == ACTION_NO_CHANGE
    assert controller.is_disabled is True, "an easier verdict later does not re-enable"


# --------------------------------------------------------------------------- #
# AST: `.enable(` is called only inside `enable_demo` (T-24-67).
# --------------------------------------------------------------------------- #


def enable_call_sites(source: str) -> list[str]:
    """The enclosing function names of every `.enable(` call (module level is `<module>`)."""
    found: list[str] = []

    def walk(node: ast.AST, enclosing: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = (
                child.name
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                else enclosing
            )
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "enable"
            ):
                found.append(enclosing)
            walk(child, name)

    walk(ast.parse(source), "<module>")
    return found


def test_src_live_calls_enable_only_inside_enable_demo() -> None:
    sites = {
        path.name: enable_call_sites(path.read_text(encoding="utf-8"))
        for path in sorted(SRC_LIVE.glob("*.py"))
    }
    assert {name: calls for name, calls in sites.items() if calls} == {
        "enablement.py": ["enable_demo"]
    }


def test_negative_control_an_enable_call_elsewhere_is_found() -> None:
    assert enable_call_sites("def other(c):\n    c.enable(operator_id='x')\n") == ["other"]
    assert enable_call_sites("c.enable()\n") == ["<module>"]


def test_the_live_modules_never_construct_a_live_enable_path() -> None:
    """No `LIVE` branch of `enable_demo`: it refuses first and only DEMO reaches the controller."""
    source = (SRC_LIVE / "enablement.py").read_text(encoding="utf-8")
    assert "Environment.LIVE" not in source
    assert "KillGateState.WITHIN_BUDGET" not in source, "no default kill-gate state (24-01 Q5)"
