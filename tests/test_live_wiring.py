"""The D-05 wiring gate (plan 24-27): every ROADMAP criterion 1 link has a production caller.

The completed wiring is built through `build_wiring` with fakes only at the edges (SDK client
factory, PTB application factory and bot, clock, sleep); the SQL engine is created and never
connected, so every store is the real PostgreSQL class. `check_wiring` returns the broken links.
Each criterion-1 link has a negative control: replacing exactly that link makes `check_wiring`
name exactly that link.
"""

from __future__ import annotations

import ast
import dataclasses
import functools
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_ratelimit_gate import RateLimitBanActive
from src.domain.exchange_errors import ExchangeErrorCategory
from src.live import wiring as wiring_module
from src.live.wiring import (
    LINK_ALERT_SINK,
    LINK_APPROVAL_SENDER,
    LINK_BOT_RUNNER,
    LINK_CALLBACK_HANDLER,
    LINK_CLOSER,
    LINK_COMMANDS,
    LINK_DEMO_SIGNAL,
    LINK_DRIFT_GUARD,
    LINK_EXECUTION_SERVICE,
    LINK_HEALTH_TASK,
    LINK_LIQUIDATION_WATCH,
    LINK_ONE_GATE,
    LINK_RECONCILE,
    LINK_RESERVATION_RELEASE,
    LINK_RESOLVER,
    LINK_RESTORE_REQUIRED,
    LINK_RISK_PRODUCER,
    LINK_SAFE_MODE,
    LINK_SCHEDULER_SPECS,
    LINK_SIGNAL_PUMP,
    LINK_SNAPSHOT_RECORDER,
    LINK_SWEEPER,
    TASK_NAMES,
    CompleteLiveWiring,
    WiringIncomplete,
    check_wiring,
)
from src.ops.alerts import JournalFirstAlertSink

from tests.support.live_wiring_rig import (
    WiringHandles,
    complete_assembly,
    forbid_connections,
    make_assembly,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_connections(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return forbid_connections(monkeypatch)


@pytest.fixture
def handles(tmp_path: Path) -> WiringHandles:
    return make_assembly(tmp_path)


@pytest.fixture
async def complete(handles: WiringHandles) -> CompleteLiveWiring:
    return await complete_assembly(handles)


# --------------------------------------------------------------------------- #
# The completed wiring.
# --------------------------------------------------------------------------- #


async def test_the_completed_wiring_has_no_broken_link(complete: CompleteLiveWiring) -> None:
    assert check_wiring(complete) == []


def test_the_wiring_is_not_available_before_the_safe_mode_controller_is_loaded(
    handles: WiringHandles,
) -> None:
    with pytest.raises(WiringIncomplete):
        _ = handles.assembly.wiring


async def test_the_scheduler_specs_are_exactly_the_listed_set(complete: CompleteLiveWiring) -> None:
    assert {spec.name for spec in complete.specs} == TASK_NAMES
    assert len(complete.specs) == len(TASK_NAMES)
    assert TASK_NAMES == {
        "protection_step",
        "reconcile_tick",
        "drift_remeasure",
        "mark_refresh",
        "commission_refresh",
        "day_risk_backfill",
        "confirm_ttl_sweep",
        "alert_drain",
        "health_tick",
        "liveness_stamp",
        "scheduled_cancel",
        "signal_source_pump",
        # Plan 24-37 (F4, D095): a deliberate addition to the pinned set.
        "reservation_release_sweep",
    }


async def test_the_protection_task_wakes_on_a_fill(complete: CompleteLiveWiring) -> None:
    protection = next(spec for spec in complete.specs if spec.name == "protection_step")
    assert protection.wake is complete.stream.wake


async def test_every_interval_comes_from_the_cadences(
    complete: CompleteLiveWiring, handles: WiringHandles
) -> None:
    cadences = handles.assembly.cadences
    by_name = {spec.name: spec.interval for spec in complete.specs}
    assert by_name["protection_step"] == cadences.protection_step
    assert by_name["reconcile_tick"] == cadences.reconcile_tick
    assert by_name["drift_remeasure"] == cadences.drift_remeasure
    assert by_name["day_risk_backfill"] == cadences.day_risk_backfill
    assert by_name["health_tick"] == cadences.health


async def test_one_rest_gate_for_every_holder_and_a_418_blocks_public_data(
    complete: CompleteLiveWiring,
) -> None:
    gate = complete.exchange.gate
    assert complete.exchange.adapter._rest_gate is gate
    assert complete.exchange.public._rest_gate is gate
    assert complete.exchange.listen_keys._rest_gate is gate
    assert complete.exchange.probe._rest_gate is gate
    assert complete.stream.supervisor._gate is gate
    assert complete.operator._gate is gate
    assert complete.reconcile.loop._gate is gate
    # Behaviour: a 418 recorded on the one gate blocks the public data call before the SDK.
    complete.exchange.gate_store.initialize(now_utc=complete.clock(), operator_id="test")
    complete.exchange.gate.restore()
    gate.record(ExchangeErrorCategory.IP_BANNED, 60)
    with pytest.raises(RateLimitBanActive):
        await complete.exchange.public.mark_price("BTCUSDT")


async def test_the_adapter_drift_guard_is_present_and_a_never_measured_guard_blocks(
    complete: CompleteLiveWiring,
) -> None:
    guard = complete.exchange.drift_guard
    assert complete.exchange.adapter._drift_guard is guard
    assert guard.needs_remeasure(complete.clock())


async def test_the_sink_is_the_one_journal_first_sink_everywhere(
    complete: CompleteLiveWiring,
) -> None:
    sink = complete.alerts.sink
    assert type(sink) is JournalFirstAlertSink
    assert complete.coordinator._alerts is sink
    assert complete.closer._alerts is sink
    assert complete.reconcile.loop._alerts is sink
    assert complete.producer._alert_sink is sink


async def test_the_coordinator_holds_the_closer_restore_required_and_the_watch(
    complete: CompleteLiveWiring,
) -> None:
    assert complete.coordinator._closer is complete.closer
    assert complete.coordinator._restore_required is True
    assert complete.coordinator._restored is False
    assert "CLOSE_POSITION" in repr(complete.coordinator._liquidation_watch._policy)
    assert complete.safe_mode.is_durable


async def test_the_runner_registers_the_operator_commands_and_the_demo_signal_and_polls_messages(
    complete: CompleteLiveWiring,
) -> None:
    from src.live.telegram_runner import ALLOWED_UPDATES

    # The five operator commands plus the DEMO-only owner-triggered smoke injection (24-27B).
    assert set(complete.runner._command_handlers) == {*complete.operator.handlers(), "demo_signal"}
    assert len(complete.operator.handlers()) == 5
    assert "message" in ALLOWED_UPDATES
    assert "callback_query" in ALLOWED_UPDATES


async def test_no_rest_fills_reader_is_composed_and_the_fallback_schedules_nothing(
    complete: CompleteLiveWiring,
) -> None:
    """24-27B: no production fills-by-order read exists (UserTradeRow lacks price and quantity)."""
    from src.adapters.binance_usdm import UserTradeRow

    assert complete.stream.fills_fallback("123") == ()
    assert complete.stream.fills_fallback.scheduled == 0
    assert {"price", "quantity", "side"}.isdisjoint(UserTradeRow.__dataclass_fields__)


async def test_the_resolver_on_resolved_is_the_coordinator(complete: CompleteLiveWiring) -> None:
    callback = complete.reconcile.resolver._on_resolved
    assert callback == complete.coordinator.note_entry_resolved


async def test_the_runner_flow_is_the_single_confirm_flow(complete: CompleteLiveWiring) -> None:
    assert complete.runner.flow is not None
    assert complete.runner.service is complete.service
    assert complete.service._inputs is complete.producer


async def test_a_completed_assembly_returns_the_same_wiring_twice(
    handles: WiringHandles, complete: CompleteLiveWiring
) -> None:
    again = handles.assembly.complete(safe_mode=complete.safe_mode, enablement=complete.enablement)
    assert again is complete


# --------------------------------------------------------------------------- #
# Negative controls: replacing exactly one link names exactly that link.
# --------------------------------------------------------------------------- #


class _RehearsalStyleSink:
    """A sink that is not the journal-first one (the rehearsal sink of the demo script)."""

    def alert(self, **_kwargs: Any) -> None: ...


def _replace(wiring: CompleteLiveWiring, **changes: Any) -> CompleteLiveWiring:
    return dataclasses.replace(wiring, **changes)


def _without_task(wiring: CompleteLiveWiring, name: str) -> CompleteLiveWiring:
    return _replace(wiring, specs=tuple(s for s in wiring.specs if s.name != name))


async def test_negative_control_a_missing_signal_pump_task(complete: CompleteLiveWiring) -> None:
    assert check_wiring(_without_task(complete, "signal_source_pump")) == [LINK_SIGNAL_PUMP] + [
        LINK_SCHEDULER_SPECS
    ]


async def test_negative_control_a_missing_health_task(complete: CompleteLiveWiring) -> None:
    broken = check_wiring(_without_task(complete, "health_tick"))
    assert LINK_HEALTH_TASK in broken


async def test_negative_control_a_missing_reconcile_task(complete: CompleteLiveWiring) -> None:
    broken = check_wiring(_without_task(complete, "reconcile_tick"))
    assert LINK_RECONCILE in broken


async def test_negative_control_a_missing_scheduler_task_changes_the_set(
    complete: CompleteLiveWiring,
) -> None:
    broken = check_wiring(_without_task(complete, "mark_refresh"))
    assert broken == [LINK_SCHEDULER_SPECS]


async def test_negative_control_a_rehearsal_style_sink(complete: CompleteLiveWiring) -> None:
    other = dataclasses.replace(complete.alerts, sink=_RehearsalStyleSink())  # type: ignore[arg-type]
    assert check_wiring(_replace(complete, alerts=other)) == [LINK_ALERT_SINK]


async def test_negative_control_a_coordinator_without_a_closer(
    complete: CompleteLiveWiring,
) -> None:
    class _NoCloser:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self._closer = None

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    assert check_wiring(_replace(complete, closer=_NoCloser(complete.closer))) == [LINK_CLOSER]  # type: ignore[arg-type]


async def test_negative_control_a_coordinator_that_does_not_require_a_restore(
    complete: CompleteLiveWiring,
) -> None:
    complete.coordinator._restore_required = False
    try:
        assert check_wiring(complete) == [LINK_RESTORE_REQUIRED]
    finally:
        complete.coordinator._restore_required = True


async def test_negative_control_a_coordinator_without_the_liquidation_watch(
    complete: CompleteLiveWiring,
) -> None:
    watch = complete.coordinator._liquidation_watch
    complete.coordinator._liquidation_watch = None
    try:
        assert check_wiring(complete) == [LINK_LIQUIDATION_WATCH]
    finally:
        complete.coordinator._liquidation_watch = watch


async def test_negative_control_an_adapter_without_a_drift_guard(
    complete: CompleteLiveWiring,
) -> None:
    guard = complete.exchange.adapter._drift_guard
    complete.exchange.adapter._drift_guard = None
    try:
        assert check_wiring(complete) == [LINK_DRIFT_GUARD]
    finally:
        complete.exchange.adapter._drift_guard = guard


async def test_negative_control_a_second_rest_gate(complete: CompleteLiveWiring) -> None:
    from src.adapters.binance_ratelimit_gate import RestRateLimitGate

    original = complete.exchange.public._rest_gate
    complete.exchange.public._rest_gate = RestRateLimitGate(
        policy=complete.exchange.gate._policy, clock=complete.clock
    )
    try:
        assert check_wiring(complete) == [LINK_ONE_GATE]
    finally:
        complete.exchange.public._rest_gate = original


async def test_negative_control_a_handler_other_than_on_callback(
    complete: CompleteLiveWiring,
) -> None:
    async def other_handler(*_args: Any, **_kwargs: Any) -> None: ...

    class _Runner:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.handler = functools.partial(other_handler)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    assert check_wiring(_replace(complete, runner=_Runner(complete.runner))) == [  # type: ignore[arg-type]
        LINK_BOT_RUNNER,
        LINK_CALLBACK_HANDLER,
    ]


async def test_negative_control_a_runner_with_another_service(complete: CompleteLiveWiring) -> None:
    class _Runner:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.service = object()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    broken = check_wiring(_replace(complete, runner=_Runner(complete.runner)))  # type: ignore[arg-type]
    assert LINK_EXECUTION_SERVICE in broken


async def test_negative_control_a_producer_without_the_snapshot_recorder_f3(
    complete: CompleteLiveWiring,
) -> None:
    """Plan 24-37 / F3: without the recorder no placement makes its snapshot durable and a
    restart cannot rebuild the plan, so the start must be refused naming the link."""
    recorder = complete.producer._snapshot_recorder
    assert recorder == complete.stores.snapshots.record
    complete.producer._snapshot_recorder = None
    try:
        assert check_wiring(complete) == [LINK_SNAPSHOT_RECORDER]
    finally:
        complete.producer._snapshot_recorder = recorder


async def test_negative_control_a_service_without_the_release_hook_f4(
    complete: CompleteLiveWiring,
) -> None:
    """Plan 24-37 / F4: a refused CONFIRM must reach the releaser the sweep task runs."""
    hook = complete.service._on_refused
    assert hook == complete.releaser.release_refused
    complete.service._on_refused = None
    try:
        assert check_wiring(complete) == [LINK_RESERVATION_RELEASE]
    finally:
        complete.service._on_refused = hook


async def test_negative_control_a_service_not_fed_by_the_producer(
    complete: CompleteLiveWiring,
) -> None:
    inputs = complete.service._inputs
    complete.service._inputs = object()  # type: ignore[assignment]
    try:
        assert check_wiring(complete) == [LINK_RISK_PRODUCER]
    finally:
        complete.service._inputs = inputs


async def test_negative_control_an_approval_sender_that_is_not_the_desks(
    complete: CompleteLiveWiring,
) -> None:
    class _Sender:
        _desk = object()

    assert check_wiring(_replace(complete, sender=_Sender())) == [LINK_APPROVAL_SENDER]  # type: ignore[arg-type]


async def test_negative_control_an_orphan_sweeper_that_is_not_the_loops(
    complete: CompleteLiveWiring,
) -> None:
    sweeper = complete.reconcile.loop._sweeper
    complete.reconcile.loop._sweeper = object()
    try:
        assert check_wiring(complete) == [LINK_SWEEPER]
    finally:
        complete.reconcile.loop._sweeper = sweeper


async def test_negative_control_a_resolver_not_bound_to_the_coordinator(
    complete: CompleteLiveWiring,
) -> None:
    callback = complete.reconcile.resolver._on_resolved
    complete.reconcile.resolver._on_resolved = None
    try:
        assert check_wiring(complete) == [LINK_RESOLVER]
    finally:
        complete.reconcile.resolver._on_resolved = callback


async def test_negative_control_a_non_durable_safe_mode_controller(
    handles: WiringHandles,
) -> None:
    """The reconcile loop refuses a volatile controller at build, so no such wiring exists."""
    from src.execution.enablement import LiveEnablementController
    from src.reconcile.safe_mode import SafeModeController

    assembly = handles.assembly
    volatile = SafeModeController(
        adapter=assembly.exchange.adapter,  # type: ignore[arg-type]
        journal=assembly.stores.journal,
    )
    with pytest.raises(ValueError, match="durable"):
        assembly.complete(
            safe_mode=volatile,
            enablement=LiveEnablementController(journal=assembly.stores.journal),
        )
    assert not assembly.is_complete


async def test_negative_control_the_check_names_a_controller_without_a_state_store(
    complete: CompleteLiveWiring,
) -> None:
    store = complete.safe_mode._state_store
    complete.safe_mode._state_store = None
    try:
        assert LINK_SAFE_MODE in check_wiring(complete)
    finally:
        complete.safe_mode._state_store = store


async def test_negative_control_runner_without_operator_commands(
    complete: CompleteLiveWiring,
) -> None:
    handlers = dict(complete.runner._command_handlers)
    complete.runner._command_handlers.clear()
    try:
        assert check_wiring(complete) == [LINK_COMMANDS]
    finally:
        complete.runner._command_handlers.update(handlers)


async def test_negative_control_the_demo_signal_command_is_not_registered(
    complete: CompleteLiveWiring,
) -> None:
    handler = complete.runner._command_handlers.pop("demo_signal")
    try:
        assert check_wiring(complete) == [LINK_COMMANDS]
    finally:
        complete.runner._command_handlers["demo_signal"] = handler


async def test_negative_control_the_demo_signal_feeds_another_queue(
    complete: CompleteLiveWiring,
) -> None:
    from src.live.signal_source import DemoSmokeSignalSource

    assert complete.demo_signal is not None
    original = complete.demo_signal._source
    complete.demo_signal._source = DemoSmokeSignalSource(
        run_id="other", parameter_set=complete.demo_signal._source._parameter_set
    )
    try:
        assert check_wiring(complete) == [LINK_DEMO_SIGNAL]
    finally:
        complete.demo_signal._source = original


async def test_negative_control_a_non_demo_wiring_must_not_carry_the_command(
    complete: CompleteLiveWiring,
) -> None:
    from src.adapters.binance_client import Environment

    live = dataclasses.replace(complete, mode=Environment.LIVE)
    assert LINK_DEMO_SIGNAL in check_wiring(live)


# --------------------------------------------------------------------------- #
# Construction stays inside src/live (D-04).
# --------------------------------------------------------------------------- #

CONSTRUCTED = frozenset(
    {
        "ExecutionService",
        "ProtectionCoordinator",
        "JournalFirstAlertSink",
        "RestRateLimitGate",
        "BinanceUsdmAdapter",
        "Scheduler",
    }
)
ALLOWED_OUTSIDE_LIVE = frozenset(
    {
        "src/execution/protection.py",
        "src/ops/alerts.py",
        "src/adapters/binance_ratelimit_gate.py",
        "src/adapters/binance_usdm.py",
        # Reviewed exceptions (plan 24-27 SUMMARY): the data collection tools build their own
        # public-data adapter; they are not the live process and run no order path.
        "src/data/backfill_cli.py",
        "src/data/collector.py",
        "src/data/universe_freeze.py",
    }
)


def _constructions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (
                node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            )
            if name in CONSTRUCTED:
                found.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {name}")
    return found


def test_no_module_outside_src_live_constructs_a_live_object() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("src/live/") or relative in ALLOWED_OUTSIDE_LIVE:
            continue
        offenders.extend(_constructions(path))
    assert offenders == [], f"live objects constructed outside src/live: {offenders}"


def test_the_negative_control_of_the_scan_finds_a_construction(tmp_path: Path) -> None:
    module = tmp_path / "x.py"
    module.write_text("service = ExecutionService()\n", encoding="utf-8")
    tree = ast.parse(module.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert any(getattr(c.func, "id", "") in CONSTRUCTED for c in calls)


def test_the_wiring_module_is_the_only_one_constructing_the_coordinator_in_src_live() -> None:
    sites = [
        site
        for path in sorted((ROOT / "src" / "live").rglob("*.py"))
        for site in _constructions(path)
        if "ProtectionCoordinator" in site
    ]
    assert all(site.startswith("src/live/wiring.py") for site in sites), sites
    assert wiring_module.LINK_COMMANDS == LINK_COMMANDS


# --------------------------------------------------------------------------- #
# Quick task 261114-mp1 (D111): the protection stall bound reaches only the protection TaskSpec.
# --------------------------------------------------------------------------- #


async def test_with_the_default_limits_no_task_has_a_stall_bound(
    complete: CompleteLiveWiring,
) -> None:
    assert {spec.stall_after_seconds for spec in complete.specs} == {None}


async def test_a_set_stall_bound_reaches_only_the_protection_task(
    handles: WiringHandles,
) -> None:
    import datetime as dt

    handles.assembly.cadences = dataclasses.replace(
        handles.assembly.cadences, protection_stall_after=dt.timedelta(milliseconds=5353)
    )
    complete = await complete_assembly(handles)
    bounds = {spec.name: spec.stall_after_seconds for spec in complete.specs}
    assert bounds.pop("protection_step") == 5.353
    assert set(bounds.values()) == {None}


async def test_the_shipped_stall_bound_reaches_only_the_protection_task_as_sixty_seconds(
    handles: WiringHandles,
) -> None:
    # Quick 261115-pdb (D114): the shipped file -> loader -> cadences -> the protection TaskSpec.
    from src.execution.execution_limits import load_execution_limits

    shipped = load_execution_limits(
        Path(__file__).resolve().parents[1] / "config" / "execution" / "execution-limits-v1.toml"
    )
    # Before the first complete_assembly: it caches the wiring.
    handles.assembly.cadences = dataclasses.replace(
        handles.assembly.cadences, protection_stall_after=shipped.scheduler_protection_stall_after
    )
    complete = await complete_assembly(handles)
    bounds = {spec.name: spec.stall_after_seconds for spec in complete.specs}
    assert bounds.pop("protection_step") == 60
    assert set(bounds.values()) == {None}


# --------------------------------------------------------------------------- #
# Quick task 261114-mp1 (D111): the production record path alerts a stall.
# --------------------------------------------------------------------------- #


def _stall_event(kind: str = "stall") -> Any:
    from src.live.scheduler import TaskEvent

    from tests.shadow_fakes import T0

    return TaskEvent(task="protection_step", kind=kind, at_utc=T0, error_class=None)  # type: ignore[arg-type]


async def test_a_stall_event_is_journaled_and_raises_one_task_stalled_alert(
    handles: WiringHandles,
) -> None:
    from src.live.wiring_parts import task_event_journal

    journaled: list[Any] = []

    async def record(event: Any) -> None:
        journaled.append(event)

    handles.assembly.record = record  # type: ignore[assignment]
    event = _stall_event()

    await handles.assembly._record_task(event)

    assert journaled == [task_event_journal(event)]
    queued = list(handles.assembly.alerts.sink.queue)
    assert [(a.event, a.subject, a.reason) for a in queued] == [
        ("TASK_STALLED", "protection_step", "STALL_BOUND_EXCEEDED")
    ]


async def test_a_failure_event_is_journaled_and_raises_no_alert(handles: WiringHandles) -> None:
    journaled: list[Any] = []

    async def record(event: Any) -> None:
        journaled.append(event)

    handles.assembly.record = record  # type: ignore[assignment]

    await handles.assembly._record_task(_stall_event("failure"))

    assert len(journaled) == 1
    assert list(handles.assembly.alerts.sink.queue) == []


async def test_the_stall_alert_is_still_attempted_when_the_journal_write_raises(
    handles: WiringHandles,
) -> None:
    async def record(event: Any) -> None:
        raise RuntimeError("journal down (test)")

    handles.assembly.record = record  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="journal down"):
        await handles.assembly._record_task(_stall_event())

    assert [a.event for a in handles.assembly.alerts.sink.queue] == ["TASK_STALLED"]


# --------------------------------------------------------------------------- #
# Quick task 261115-kra (D112): the production path of the scheduler duration record.
# --------------------------------------------------------------------------- #


def _duration_summary() -> Any:
    from src.live.scheduler import TaskDurationSummary

    from tests.shadow_fakes import T0

    return TaskDurationSummary(
        task="protection_step",
        at_utc=T0,
        runs=3,
        total_ms=4500,
        max_ms=2500,
        window_max_ms=2500,
        new_max=True,
        window_end=False,
    )


async def test_a_duration_summary_is_journaled_and_never_alerts(handles: WiringHandles) -> None:
    from src.live.wiring_parts import task_duration_journal

    journaled: list[Any] = []

    async def record(event: Any) -> None:
        journaled.append(event)

    handles.assembly.record = record  # type: ignore[assignment]
    summary = _duration_summary()

    await handles.assembly._record_task_duration(summary)

    assert journaled == [task_duration_journal(summary)]
    assert list(handles.assembly.alerts.sink.queue) == []


async def test_the_scheduler_carries_the_duration_recorder_and_no_window_by_default(
    handles: WiringHandles, complete: CompleteLiveWiring
) -> None:
    scheduler = complete.scheduler
    assert scheduler._record_duration == handles.assembly._record_task_duration
    assert scheduler._duration_summary_interval is None  # the default limits leave it unset


async def test_a_set_cadence_window_reaches_the_scheduler(handles: WiringHandles) -> None:
    import datetime as dt

    handles.assembly.cadences = dataclasses.replace(
        handles.assembly.cadences, duration_summary_interval=dt.timedelta(milliseconds=6262)
    )
    with_window = await complete_assembly(handles)
    assert with_window.scheduler._record_duration == handles.assembly._record_task_duration
    assert with_window.scheduler._duration_summary_interval == dt.timedelta(milliseconds=6262)
