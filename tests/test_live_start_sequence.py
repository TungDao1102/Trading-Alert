"""The D-08 start sequence (plan 24-26): order, fail-closed outcomes, gate bootstrap, sentinel.

Everything is a fake or a spy except the objects the sequence is about: the real
`FileGateStateStore` and `RestRateLimitGate`, the real `SafeModeController` over an in-memory
durable store, the real `LiveEnablementController` and `enable_demo`, and the real
`run_startup_recovery`. The tracer test at the end puts the sequence over the live rig (the real
desk, confirm flow, service and manager with the Binance-semantics fake) to show that a CONFIRM
before the last step cannot place and the first `place_entry` only happens after it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_client import Environment
from src.adapters.binance_ratelimit_gate import GateRecoveryStatus, RestRateLimitGate
from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent
from src.execution.enablement import LiveEnablementController
from src.execution.protection import RestoreReport
from src.live import startup
from src.live.enablement import (
    REASON_ENABLED,
    REASON_KILL_GATE_UNEVALUATED,
    StartEnablement,
)
from src.live.startup import (
    AlembicRevisions,
    RecoveryPorts,
    StartupPorts,
    StartupRefused,
    run_start_sequence,
)
from src.ops.health import (
    ALL_CHECK_NAMES,
    HealthCheckResult,
    HealthRuntimeMode,
    HealthVerdict,
    run_health_checks,
)
from src.ops.rest_gate_state import FileGateStateStore
from src.reconcile.loop import TICK_COMPARED, TickReport
from src.reconcile.safe_mode import SafeModeController
from src.reconcile.startup import PartialRestore

from tests.shadow_fakes import T0
from tests.support.limits import test_only_rate_limit_policy
from tests.support.reconcile_doubles import FakeReconcileAdapter, InMemorySafeModeStore
from tests.support.stream_sinks import RecordingJournal

OPERATOR = "owner"
HEAD = "0015_order_event_time"


def passing_verdict(mode: HealthRuntimeMode = HealthRuntimeMode.DEMO) -> HealthVerdict:
    return run_health_checks(
        results=[
            HealthCheckResult(check_name=n, status="PASS", detail="ok", observed_at_utc=T0)
            for n in ALL_CHECK_NAMES
        ],
        mode=mode,
    )


class _Pending:
    def list_open(self) -> list[Any]:
        return []


class _Coordinator:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self._done = False

    @property
    def restore_complete(self) -> bool:
        return self._done

    def restore(self, plans: Sequence[Any], *, now_utc: datetime) -> RestoreReport:
        self._calls.append("coordinator.restore")
        self._done = True
        return RestoreReport(
            restored=(), replay_invalid=(), stop_history_unknown=(), safe_mode_reasons=()
        )


class _Closer:
    def restore_pending(self, *, plan_hash: str, attempts: Sequence[Any]) -> None:
        return None


class _Intents:
    def list_unresolved_intents(self) -> tuple[Any, ...]:
        return ()


class _SpyGateStore(FileGateStateStore):
    def __init__(self, path: Path, *, clock: Callable[[], datetime], calls: list[str]) -> None:
        super().__init__(path, clock=clock)
        self._calls = calls

    def initialize(self, *, now_utc: datetime, operator_id: str) -> Any:
        self._calls.append("gate.initialize")
        return super().initialize(now_utc=now_utc, operator_id=operator_id)


class _SpyGate:
    def __init__(self, gate: RestRateLimitGate, calls: list[str]) -> None:
        self._gate = gate
        self._calls = calls

    def restore(self) -> GateRecoveryStatus:
        self._calls.append("gate.restore")
        return self._gate.restore()


class _FailingSafeModeStore:
    def save(self, state: Mapping[str, Any], *, now_utc: datetime) -> None:
        raise OSError("TEST_ONLY store down")

    def load(self) -> Mapping[str, Any] | None:
        raise OSError("TEST_ONLY store down")


@dataclass
class Harness:
    """The ports of a healthy DEMO start over a temp directory, with every call recorded."""

    tmp: Path
    calls: list[str] = field(default_factory=list)
    rows: list[JournalEvent] = field(default_factory=list)
    controller_disabled_at_row: list[bool] = field(default_factory=list)
    safe_mode_journal: RecordingJournal = field(default_factory=RecordingJournal)
    enablement_journal: RecordingJournal = field(default_factory=RecordingJournal)
    tick: Callable[[datetime], Awaitable[TickReport]] | None = None
    safe_mode: SafeModeController | None = None
    enablement: LiveEnablementController | None = None
    overrides: dict[str, Any] = field(default_factory=dict)
    mode: Environment = Environment.DEMO
    flag: bool = False
    operator: str | None = OPERATOR

    # ---- state on disk ------------------------------------------------------------------- #

    @property
    def gate_path(self) -> Path:
        return self.tmp / "gate" / "rest-gate-state.json"

    @property
    def spill_dir(self) -> Path:
        return self.tmp / "spill"

    def install(self, *, gate: bool = True, sentinel: bool = True) -> None:
        """A previous first install: the gate state file and (or not) the spill sentinel."""
        if gate:
            FileGateStateStore(self.gate_path, clock=lambda: T0).initialize(
                now_utc=T0, operator_id=OPERATOR
            )
        if sentinel:
            startup.write_spill_sentinel(self.spill_dir, now_utc=T0)

    # ---- ports --------------------------------------------------------------------------- #

    def _spy(self, name: str, value: Any = None) -> Callable[[], Any]:
        override = self.overrides.get(name)

        def port() -> Any:
            self.calls.append(name)
            if override is not None:
                return override()
            return value

        return port

    def ports(self) -> StartupPorts:
        store = _SpyGateStore(self.gate_path, clock=lambda: T0, calls=self.calls)
        gate = RestRateLimitGate(
            policy=test_only_rate_limit_policy(), clock=lambda: T0, state_store=store
        )
        adapter = FakeReconcileAdapter()
        sm_store = InMemorySafeModeStore()

        def load_safe_mode() -> SafeModeController:
            self.calls.append("load_safe_mode")
            if "load_safe_mode" in self.overrides:
                return self.overrides["load_safe_mode"](adapter, self.safe_mode_journal)  # type: ignore[no-any-return]
            self.safe_mode = SafeModeController.load(
                adapter=adapter,  # type: ignore[arg-type]
                journal=self.safe_mode_journal,
                state_store=sm_store,
                now_utc=T0,
            )
            return self.safe_mode

        def start_enablement() -> StartEnablement:
            self.calls.append("start_enablement")
            if "start_enablement" in self.overrides:
                return self.overrides["start_enablement"]()  # type: ignore[no-any-return]
            self.enablement = LiveEnablementController(journal=self.enablement_journal)
            return StartEnablement(
                controller=self.enablement, persisted_enabled=False, persisted_problem=None
            )

        def alembic_revisions() -> AlembicRevisions:
            self.calls.append("alembic")
            if "alembic" in self.overrides:
                return self.overrides["alembic"]()  # type: ignore[no-any-return]
            return AlembicRevisions(current=HEAD, head=HEAD)

        def admitted_config() -> Mapping[str, str]:
            self.calls.append("config")
            if "config" in self.overrides:
                return self.overrides["config"]()  # type: ignore[no-any-return]
            return {"mode": self.mode.value}

        def builder(spill_rows_for: Callable[[str], Any]) -> list[Any]:
            self.calls.append("builder")
            if "builder" in self.overrides:
                return self.overrides["builder"](spill_rows_for)  # type: ignore[no-any-return]
            return []

        def close_reader() -> Mapping[str, Sequence[JournalEvent]]:
            self.calls.append("close_reader")
            return {}

        async def reconcile_tick(now: datetime) -> TickReport:
            self.calls.append("reconcile")
            if "reconcile" in self.overrides:
                return await self.overrides["reconcile"](now)  # type: ignore[no-any-return]
            return TickReport(outcome=TICK_COMPARED, now_utc=now, agreement=True)

        def expire_confirms(now: datetime) -> list[str]:
            self.calls.append("expire_confirms")
            if "expire_confirms" in self.overrides:
                return self.overrides["expire_confirms"](now)  # type: ignore[no-any-return]
            return []

        def health_verdict() -> HealthVerdict:
            self.calls.append("health")
            if "health" in self.overrides:
                return self.overrides["health"]()  # type: ignore[no-any-return]
            return passing_verdict(
                HealthRuntimeMode.DEMO if self.mode is Environment.DEMO else HealthRuntimeMode.LIVE
            )

        def kill_gate_state() -> KillGateState | None:
            self.calls.append("kill_gate")
            if "kill_gate" in self.overrides:
                return self.overrides["kill_gate"]()  # type: ignore[no-any-return]
            return KillGateState.WITHIN_BUDGET  # TEST_ONLY: the owner source is an open question

        async def record(event: JournalEvent) -> None:
            if "record" in self.overrides:
                self.overrides["record"](event)
            self.rows.append(event)
            if self.enablement is not None:
                self.controller_disabled_at_row.append(self.enablement.is_disabled)

        coordinator = _Coordinator(self.calls)
        return StartupPorts(
            mode=self.mode,
            clock=lambda: T0 + timedelta(seconds=len(self.rows)),
            record=record,
            admitted_config=admitted_config,
            gate_store=store,
            gate=_SpyGate(gate, self.calls),  # type: ignore[arg-type]
            initialize_gate_state=self.flag,
            operator_id=self.operator,
            alembic_revisions=alembic_revisions,
            load_safe_mode=load_safe_mode,
            start_enablement=start_enablement,
            load_constraint_snapshots=self._spy("snapshots"),
            spill_directory=self.spill_dir,
            measure_clock_drift=self._spy("drift"),
            refresh_exchange_info=self._spy("exchange_info"),
            recovery=RecoveryPorts(
                pending_store=_Pending(),  # type: ignore[arg-type]
                coordinator=coordinator,
                closer=_Closer(),
                restored_plans_builder=builder,
                close_attempts_reader=close_reader,
                intent_store=_Intents(),  # type: ignore[arg-type]
                probe_adapter=adapter,  # type: ignore[arg-type]
                journal=self.safe_mode_journal,
                spill=None,
            ),
            reconcile_tick=reconcile_tick,
            expire_confirms=expire_confirms,
            requeue_alerts=self._spy("requeue"),
            start_stream=self._spy("stream"),
            start_bot=self._spy("bot"),
            start_scheduler=self._spy("scheduler"),
            health_verdict=health_verdict,
            kill_gate_state=kill_gate_state,
        )

    async def run(self) -> startup.StartupOutcome:
        return await run_start_sequence(self.ports(), now_utc=T0)

    def step_rows(self) -> list[dict[str, Any]]:
        return [
            json.loads(e.payload_json) for e in self.rows if e.event_type == "LIVE_STARTUP_STEP"
        ]


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    h = Harness(tmp=tmp_path)
    h.install()
    return h


# --------------------------------------------------------------------------- #
# Task 1: the order.
# --------------------------------------------------------------------------- #

# D094 (owner, 2026-11-01), a DELIBERATE change of this pin: the user-data stream starts BEFORE the
# first reconcile tick (D-08 had it after). Plan 24-29 finding F1: with the old order the tick
# always judged a silent feed and every clean start was parked in SAFE_MODE STALE_FEED.
EXPECTED_CALLS = [
    "config",
    "gate.restore",
    "alembic",
    "load_safe_mode",
    "start_enablement",
    "snapshots",
    "drift",
    "exchange_info",
    "builder",
    "coordinator.restore",
    "close_reader",
    "stream",
    "reconcile",
    "expire_confirms",
    "requeue",
    "bot",
    "scheduler",
    "health",
    "kill_gate",
]


async def test_the_steps_run_in_the_d08_order_each_journaled_and_enable_is_last(
    harness: Harness,
) -> None:
    outcome = await harness.run()

    assert harness.calls == EXPECTED_CALLS
    assert "gate.initialize" not in harness.calls, "no flag, no initialization"
    assert outcome.admitted and not outcome.in_safe_mode and outcome.enabled
    assert outcome.enable_reason == REASON_ENABLED
    assert outcome.started_tasks == ("STREAM", "BOT", "SCHEDULER")
    assert startup.START_STEPS.index("STREAM") < startup.START_STEPS.index("RECONCILE")
    assert [r["step"] for r in harness.step_rows()] == list(startup.START_STEPS)
    assert [r["outcome"] for r in harness.step_rows()] == ["OK"] * len(startup.START_STEPS)
    assert [r["group"] for r in harness.step_rows()] == [
        startup.START_STEP_GROUP[s] for s in startup.START_STEPS
    ]
    # the enablement controller was DISABLED at every row before the ENABLE row
    assert all(harness.controller_disabled_at_row[:-1])
    assert harness.enablement is not None and not harness.enablement.is_disabled
    assert [s.name for s in outcome.steps] == list(startup.START_STEPS)


async def test_the_stream_is_up_when_the_first_reconcile_tick_judges_the_feed(
    harness: Harness,
) -> None:
    """D094 / finding F1: the tick must find the stream started, and it is started only after the
    recovery rebuilt the registry and the client-id index (no frame before the rebuild)."""
    seen: dict[str, list[str]] = {}

    async def tick(now: datetime) -> TickReport:
        seen["calls_at_tick"] = list(harness.calls)
        return TickReport(
            outcome=TICK_COMPARED, now_utc=now, agreement=True, divergences=(), failed_source=None
        )

    harness.overrides["reconcile"] = tick
    outcome = await harness.run()

    at_tick = seen["calls_at_tick"]
    assert "stream" in at_tick
    assert at_tick.index("stream") > at_tick.index("coordinator.restore")
    assert at_tick.index("stream") > at_tick.index("builder")
    assert "bot" not in at_tick and "scheduler" not in at_tick
    assert outcome.admitted and not outcome.in_safe_mode and outcome.enabled


async def test_a_stream_that_cannot_start_still_runs_the_tick_and_continues_in_safe_mode(
    harness: Harness,
) -> None:
    """D-08 fail-closed semantics survive the reorder: a failing stream start is SAFE_MODE with
    monitoring (the tick, the bot and the scheduler) still running, and nothing is enabled."""
    harness.overrides["stream"] = _raises("stream")
    outcome = await harness.run()

    assert outcome.admitted and outcome.in_safe_mode and not outcome.enabled
    assert "STREAM" in outcome.degraded_steps
    assert "reconcile" in harness.calls, "monitoring continues"
    assert outcome.started_tasks == ("BOT", "SCHEDULER")
    assert harness.safe_mode is not None
    assert harness.safe_mode.entered_reason == "STARTUP_STREAM_FAILED"


def test_start_steps_is_the_nine_groups_in_order() -> None:
    groups = [startup.START_STEP_GROUP[s] for s in startup.START_STEPS]
    assert groups == sorted(groups)
    assert set(groups) == set(range(1, 10))
    assert startup.START_STEPS[-1] == "ENABLE"
    assert len(set(startup.START_STEPS)) == len(startup.START_STEPS)


async def test_a_step_row_carries_a_name_an_outcome_and_a_code_never_a_message(
    harness: Harness,
) -> None:
    def failing() -> None:
        raise RuntimeError("postgresql://user:SECRET@host/db")

    harness.overrides["exchange_info"] = failing
    await harness.run()

    for event in harness.rows:
        assert "SECRET" not in event.payload_json
    (row,) = [r for r in harness.step_rows() if r["step"] == "EXCHANGE_INFO"]
    assert row["outcome"] == "FAILED"
    assert row["code"] == "STEP_FAILED:RuntimeError"


async def test_the_first_rows_wait_for_the_alembic_check(harness: Harness) -> None:
    """The journal table may not exist before the head check: the rows of 1 to 3 follow it."""
    seen_at_first_write: list[list[str]] = []

    def watch(event: JournalEvent) -> None:
        if not seen_at_first_write:
            seen_at_first_write.append(list(harness.calls))

    harness.overrides["record"] = watch
    await harness.run()

    assert "alembic" in seen_at_first_write[0], "no row is written before the Alembic check"
    assert [r["step"] for r in harness.step_rows()][:3] == ["CONFIG", "GATE", "ALEMBIC"]


async def test_a_held_start_writes_no_journal_row(harness: Harness) -> None:
    harness.overrides["alembic"] = lambda: AlembicRevisions(current="0001", head=HEAD)
    outcome = await harness.run()
    assert not outcome.admitted
    assert harness.rows == [], "the journal may be unmigrated: a hold goes to the log only"
    assert [s.name for s in outcome.steps] == ["CONFIG", "GATE", "ALEMBIC"]


# --------------------------------------------------------------------------- #
# Task 2: holds (groups 1 to 3 and the controllers) and the gate bootstrap.
# --------------------------------------------------------------------------- #


def _assert_nothing_started(outcome: startup.StartupOutcome, harness: Harness) -> None:
    assert not outcome.admitted
    assert outcome.started_tasks == ()
    assert not outcome.enabled
    for later in ("stream", "bot", "scheduler", "reconcile", "health", "kill_gate"):
        assert later not in harness.calls


async def test_no_gate_state_and_no_flag_holds_and_names_the_one_shot_command(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp=tmp_path)  # nothing installed: a missing file is "unknown"
    outcome = await harness.run()

    _assert_nothing_started(outcome, harness)
    assert (outcome.held_step, outcome.held_code) == ("GATE", startup.CODE_GATE_STATE_MISSING)
    assert outcome.held_message is not None
    assert "--initialize-gate-state --operator-id" in outcome.held_message
    assert "gate.initialize" not in harness.calls
    assert not harness.gate_path.exists(), "never initialized silently"
    assert "alembic" not in harness.calls


async def test_the_flag_with_an_existing_state_file_is_refused_and_the_file_is_untouched(
    harness: Harness,
) -> None:
    before = harness.gate_path.read_bytes()
    harness.flag = True
    outcome = await harness.run()

    _assert_nothing_started(outcome, harness)
    assert outcome.held_code == startup.CODE_GATE_STATE_EXISTS
    assert harness.gate_path.read_bytes() == before
    assert "gate.initialize" not in harness.calls


async def test_the_flag_with_a_corrupt_state_file_is_refused_too(harness: Harness) -> None:
    harness.gate_path.write_bytes(b"not json")
    harness.flag = True
    outcome = await harness.run()
    assert outcome.held_code == startup.CODE_GATE_STATE_EXISTS
    assert harness.gate_path.read_bytes() == b"not json"


@pytest.mark.parametrize("operator", [None, "", "   "])
async def test_the_flag_needs_an_operator_id(tmp_path: Path, operator: str | None) -> None:
    harness = Harness(tmp=tmp_path, flag=True, operator=operator)
    outcome = await harness.run()
    assert outcome.held_code == startup.CODE_OPERATOR_ID_MISSING
    assert not harness.gate_path.exists()


async def test_a_corrupt_state_without_the_flag_holds_the_gate_is_not_restored(
    harness: Harness,
) -> None:
    harness.gate_path.write_bytes(b"not json")
    outcome = await harness.run()
    _assert_nothing_started(outcome, harness)
    assert outcome.held_code == startup.CODE_GATE_NOT_RESTORED
    assert "alembic" not in harness.calls


async def test_an_alembic_mismatch_holds_and_names_both_revisions(harness: Harness) -> None:
    harness.overrides["alembic"] = lambda: AlembicRevisions(current="0014_x", head=HEAD)
    outcome = await harness.run()
    _assert_nothing_started(outcome, harness)
    assert (outcome.held_step, outcome.held_code) == ("ALEMBIC", startup.CODE_ALEMBIC_MISMATCH)
    assert outcome.held_message is not None
    assert "0014_x" in outcome.held_message and HEAD in outcome.held_message
    assert "load_safe_mode" not in harness.calls


def test_alembic_head_matches_is_exact() -> None:
    assert startup.alembic_head_matches(current=HEAD, head=HEAD)
    assert not startup.alembic_head_matches(current=None, head=HEAD)
    assert not startup.alembic_head_matches(current="0014_x", head=HEAD)


async def test_an_unreadable_alembic_revision_holds_without_the_message_text(
    harness: Harness,
) -> None:
    def down() -> AlembicRevisions:
        raise ConnectionError("postgresql://user:SECRET@host/db")

    harness.overrides["alembic"] = down
    outcome = await harness.run()
    _assert_nothing_started(outcome, harness)
    assert outcome.held_code == startup.CODE_ALEMBIC_UNREADABLE
    assert outcome.held_message is not None and "SECRET" not in outcome.held_message


async def test_a_mode_that_differs_from_the_admitted_config_holds(harness: Harness) -> None:
    harness.overrides["config"] = lambda: {"mode": "LIVE"}
    outcome = await harness.run()
    _assert_nothing_started(outcome, harness)
    assert outcome.held_step == "CONFIG"
    assert "gate.restore" not in harness.calls


async def test_a_config_step_that_raises_holds_with_the_class_name_only(harness: Harness) -> None:
    def broken() -> Mapping[str, str]:
        raise KeyError("TELEGRAM_BOT_TOKEN=SECRET")

    harness.overrides["config"] = broken
    outcome = await harness.run()
    _assert_nothing_started(outcome, harness)
    assert outcome.held_message is not None and "SECRET" not in outcome.held_message
    assert "KeyError" in outcome.held_message


async def test_a_safe_mode_port_that_raises_holds(harness: Harness) -> None:
    def boom(adapter: Any, journal: Any) -> SafeModeController:
        raise RuntimeError("no controller")

    harness.overrides["load_safe_mode"] = boom
    outcome = await harness.run()
    _assert_nothing_started(outcome, harness)
    assert outcome.held_step == "SAFE_MODE"
    assert "start_enablement" not in harness.calls


async def test_an_enabled_controller_at_start_holds(harness: Harness) -> None:
    def enabled() -> StartEnablement:
        controller = LiveEnablementController(journal=harness.enablement_journal)
        controller.enable(
            operator_id="x",
            now_utc=T0,
            health_verdict=passing_verdict(),
            kill_gate_state=KillGateState.WITHIN_BUDGET,
        )
        return StartEnablement(
            controller=controller, persisted_enabled=True, persisted_problem=None
        )

    harness.overrides["start_enablement"] = enabled
    outcome = await harness.run()
    _assert_nothing_started(outcome, harness)
    assert outcome.held_code == startup.CODE_ENABLEMENT_NOT_DISABLED


# --------------------------------------------------------------------------- #
# Task 2: the first install and the spill sentinel (20-DEFERRED row 43).
# --------------------------------------------------------------------------- #


async def test_the_first_install_initializes_the_gate_once_and_writes_the_sentinel(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp=tmp_path, flag=True)
    outcome = await harness.run()

    assert harness.calls.count("gate.initialize") == 1
    assert harness.calls.index("gate.initialize") < harness.calls.index("gate.restore")
    assert harness.gate_path.exists()
    assert startup.check_spill_sentinel(harness.spill_dir)
    assert outcome.first_install and outcome.admitted
    assert not outcome.in_safe_mode and outcome.enabled
    (gate_row,) = [r for r in harness.step_rows() if r["step"] == "GATE"]
    assert gate_row["code"] == "INITIALIZED"


async def test_a_first_install_that_holds_before_the_sentinel_step_is_recoverable(
    tmp_path: Path,
) -> None:
    """24-REVIEW WR-01: the gate state and the sentinel appear together, whatever holds next."""
    harness = Harness(tmp=tmp_path, flag=True)
    harness.overrides["alembic"] = lambda: AlembicRevisions(current="0014_x", head=HEAD)
    first = await harness.run()

    assert (first.held_step, first.held_code) == ("ALEMBIC", startup.CODE_ALEMBIC_MISMATCH)
    assert harness.gate_path.exists()
    assert startup.check_spill_sentinel(harness.spill_dir), "no gate state without a sentinel"

    # The operator fixes the migration and starts again, without --initialize-gate-state.
    del harness.overrides["alembic"]
    harness.flag = False
    second = await harness.run()
    assert second.admitted and not second.in_safe_mode and second.enabled
    assert "SPILL_SENTINEL" not in second.degraded_steps


async def test_a_refused_bootstrap_without_an_operator_id_writes_no_sentinel(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp=tmp_path, flag=True, operator=None)
    outcome = await harness.run()
    assert outcome.held_code == startup.CODE_OPERATOR_ID_MISSING
    assert not harness.gate_path.exists()
    assert not startup.check_spill_sentinel(harness.spill_dir)


async def test_a_later_start_with_the_gate_but_no_sentinel_enters_restore_inconsistent(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp=tmp_path)
    harness.install(gate=True, sentinel=False)  # the spill volume was re-created empty
    outcome = await harness.run()

    assert outcome.admitted and outcome.in_safe_mode
    assert harness.safe_mode is not None
    assert harness.safe_mode.entered_reason == "RESTORE_INCONSISTENT"
    assert "SPILL_SENTINEL" in outcome.degraded_steps
    assert not outcome.enabled and "health" not in harness.calls
    assert outcome.started_tasks == ("STREAM", "BOT", "SCHEDULER"), "monitoring keeps running"


async def test_an_unparsable_sentinel_counts_as_missing(tmp_path: Path) -> None:
    harness = Harness(tmp=tmp_path)
    harness.install(gate=True, sentinel=False)
    harness.spill_dir.mkdir()
    (harness.spill_dir / startup.SPILL_SENTINEL_NAME).write_text("{", encoding="utf-8")
    outcome = await harness.run()
    assert outcome.in_safe_mode and "SPILL_SENTINEL" in outcome.degraded_steps


def test_the_sentinel_is_ignored_by_the_spill_scan(tmp_path: Path) -> None:
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")
    startup.write_spill_sentinel(spill.directory, now_utc=T0)
    startup.write_spill_sentinel(spill.directory, now_utc=T0 + timedelta(hours=1))  # idempotent
    scan = spill.scan()
    assert scan.records == () and scan.corrupt == ()
    body = json.loads((spill.directory / startup.SPILL_SENTINEL_NAME).read_text(encoding="utf-8"))
    assert body["created_at_utc"] == T0.isoformat(), "the first install time is kept"


# --------------------------------------------------------------------------- #
# Task 2: later failures continue in SAFE_MODE, monitoring runs, enable_demo never.
# --------------------------------------------------------------------------- #


def _raises(name: str) -> Callable[[], Any]:
    def boom() -> Any:
        raise RuntimeError(f"{name} down")

    return boom


async def _tick_raises(now: datetime) -> TickReport:
    raise RuntimeError("reconcile down")


async def _tick_diverged(now: datetime) -> TickReport:
    return TickReport(outcome=TICK_COMPARED, now_utc=now, agreement=False)


async def _tick_read_failed(now: datetime) -> TickReport:
    return TickReport(outcome="READ_FAILED", now_utc=now, failed_source="positions")


async def _tick_skipped_restore(now: datetime) -> TickReport:
    return TickReport(outcome="SKIPPED_RESTORE_PENDING", now_utc=now)


def _builder_raises(spill_rows_for: Callable[[str], Any]) -> list[Any]:
    raise RuntimeError("plans unreadable")


def _builder_partial(spill_rows_for: Callable[[str], Any]) -> list[Any]:
    raise PartialRestore((), 1)


def _expire_raises(now: datetime) -> list[str]:
    raise RuntimeError("journal down")


FAILING_STEPS: list[Any] = [
    pytest.param("SNAPSHOTS", {"snapshots": _raises("snapshots")}, id="snapshots"),
    pytest.param("CLOCK_DRIFT", {"drift": _raises("drift")}, id="clock-drift"),
    pytest.param("EXCHANGE_INFO", {"exchange_info": _raises("info")}, id="exchange-info"),
    pytest.param("RECOVERY", {"builder": _builder_raises}, id="recovery-builder"),
    pytest.param("RECOVERY", {"builder": _builder_partial}, id="recovery-builder-partial"),
    pytest.param("RECONCILE", {"reconcile": _tick_raises}, id="reconcile-raises"),
    pytest.param("RECONCILE", {"reconcile": _tick_diverged}, id="reconcile-divergence"),
    pytest.param("RECONCILE", {"reconcile": _tick_read_failed}, id="reconcile-read-failed"),
    pytest.param("RECONCILE", {"reconcile": _tick_skipped_restore}, id="reconcile-skipped"),
    pytest.param("CONFIRM_EXPIRY", {"expire_confirms": _expire_raises}, id="confirm-expiry"),
    pytest.param("ALERT_REQUEUE", {"requeue": _raises("requeue")}, id="alert-requeue"),
    pytest.param("STREAM", {"stream": _raises("stream")}, id="stream"),
    pytest.param("BOT", {"bot": _raises("bot")}, id="bot"),
    pytest.param("SCHEDULER", {"scheduler": _raises("scheduler")}, id="scheduler"),
]


@pytest.mark.parametrize(("step", "overrides"), FAILING_STEPS)
async def test_a_failure_after_the_controllers_continues_in_safe_mode_and_never_enables(
    harness: Harness, step: str, overrides: dict[str, Any]
) -> None:
    harness.overrides.update(overrides)
    outcome = await harness.run()

    assert outcome.admitted, "not a hold: monitoring must run"
    assert outcome.in_safe_mode
    assert harness.safe_mode is not None and harness.safe_mode.in_safe_mode
    assert step in outcome.degraded_steps
    assert not outcome.enabled
    assert harness.enablement is not None and harness.enablement.is_disabled
    assert "health" not in harness.calls and "kill_gate" not in harness.calls
    rows = {r["step"]: r for r in harness.step_rows()}
    assert rows[step]["outcome"] == "FAILED"
    assert rows["ENABLE"]["outcome"] == "SKIPPED"
    assert rows["ENABLE"]["code"] == startup.CODE_BLOCKED_STEP_FAILED or (
        rows["ENABLE"]["code"] == startup.CODE_BLOCKED_SAFE_MODE
    )
    # monitoring: every task that did not itself fail was started, after the failure
    monitoring = {"STREAM", "BOT", "SCHEDULER"} - {step}
    assert monitoring <= set(outcome.started_tasks)


async def test_there_are_at_least_eight_parametrized_failing_steps() -> None:
    assert len(FAILING_STEPS) >= 8


async def test_a_safe_mode_store_failure_at_load_starts_in_safe_mode_with_monitoring(
    harness: Harness,
) -> None:
    def load(adapter: Any, journal: Any) -> SafeModeController:
        harness.safe_mode = SafeModeController.load(
            adapter=adapter, journal=journal, state_store=_FailingSafeModeStore(), now_utc=T0
        )
        return harness.safe_mode

    harness.overrides["load_safe_mode"] = load
    outcome = await harness.run()

    assert outcome.admitted and outcome.in_safe_mode
    assert harness.safe_mode is not None
    assert harness.safe_mode.entered_reason == "SAFE_MODE_STATE_UNREADABLE"
    assert not outcome.enabled and "health" not in harness.calls
    assert outcome.started_tasks == ("STREAM", "BOT", "SCHEDULER")


async def test_a_persisted_safe_mode_blocks_the_enable_and_keeps_its_reason(
    harness: Harness,
) -> None:
    def load(adapter: Any, journal: Any) -> SafeModeController:
        store = InMemorySafeModeStore()
        controller = SafeModeController(
            adapter=adapter,
            journal=journal,
            state_store=store,  # type: ignore[arg-type]
        )
        controller.enter_safe_mode(reason="DIVERGENCE_FROM_LAST_RUN", now_utc=T0)
        harness.safe_mode = SafeModeController.load(
            adapter=adapter, journal=journal, state_store=store, now_utc=T0
        )
        return harness.safe_mode

    harness.overrides["load_safe_mode"] = load
    outcome = await harness.run()

    assert outcome.in_safe_mode and not outcome.enabled
    assert harness.safe_mode is not None
    assert harness.safe_mode.entered_reason == "DIVERGENCE_FROM_LAST_RUN"
    rows = {r["step"]: r for r in harness.step_rows()}
    assert rows["ENABLE"]["code"] == startup.CODE_BLOCKED_SAFE_MODE


async def test_a_failing_step_does_not_overwrite_a_standing_safe_mode_reason(
    harness: Harness,
) -> None:
    harness.overrides["drift"] = _raises("drift")
    harness.overrides["exchange_info"] = _raises("info")
    outcome = await harness.run()
    assert harness.safe_mode is not None
    assert harness.safe_mode.entered_reason == "STARTUP_CLOCK_DRIFT_FAILED"
    assert outcome.safe_mode_reasons == ("STARTUP_CLOCK_DRIFT_FAILED",)


async def test_a_journal_that_cannot_be_written_blocks_the_enable_and_enters_db_failure(
    harness: Harness,
) -> None:
    written = {"n": 0}

    def flaky(event: JournalEvent) -> None:
        written["n"] += 1
        if written["n"] > 3:  # the buffered rows pass, the later ones fail
            raise OSError("TEST_ONLY journal down")

    harness.overrides["record"] = flaky
    outcome = await harness.run()
    assert outcome.in_safe_mode and not outcome.enabled
    assert harness.safe_mode is not None and harness.safe_mode.entered_reason == "DB_FAILURE"


# --------------------------------------------------------------------------- #
# Task 2: the enable step.
# --------------------------------------------------------------------------- #


async def test_live_mode_never_enables_in_process(tmp_path: Path) -> None:
    harness = Harness(tmp=tmp_path, mode=Environment.LIVE)
    harness.install()
    outcome = await harness.run()

    assert outcome.admitted and not outcome.in_safe_mode
    assert not outcome.enabled
    assert "health" not in harness.calls and "kill_gate" not in harness.calls
    rows = {r["step"]: r for r in harness.step_rows()}
    assert rows["ENABLE"]["outcome"] == "SKIPPED"
    assert rows["ENABLE"]["code"] == startup.CODE_LIVE_HUMAN_ENABLE
    assert harness.enablement is not None and harness.enablement.is_disabled


async def test_an_unevaluated_kill_gate_state_leaves_the_process_running_and_disabled(
    harness: Harness,
) -> None:
    harness.overrides["kill_gate"] = lambda: None  # nothing writes a KILL_GATE row today
    outcome = await harness.run()

    assert outcome.admitted and not outcome.in_safe_mode
    assert not outcome.enabled
    assert outcome.enable_reason == REASON_KILL_GATE_UNEVALUATED
    rows = {r["step"]: r for r in harness.step_rows()}
    assert rows["ENABLE"]["outcome"] == "REFUSED"
    assert harness.enablement is not None and harness.enablement.is_disabled
    assert outcome.started_tasks == ("STREAM", "BOT", "SCHEDULER")


async def test_a_kill_gate_source_that_raises_is_unevaluated_not_a_default(
    harness: Harness,
) -> None:
    harness.overrides["kill_gate"] = _raises("kill gate")
    outcome = await harness.run()
    assert not outcome.enabled and outcome.enable_reason == REASON_KILL_GATE_UNEVALUATED


async def test_a_health_port_that_raises_means_no_enable(harness: Harness) -> None:
    harness.overrides["health"] = _raises("health")
    outcome = await harness.run()
    assert outcome.admitted and not outcome.enabled
    assert "kill_gate" not in harness.calls
    rows = {r["step"]: r for r in harness.step_rows()}
    assert rows["HEALTH"]["code"] == startup.CODE_HEALTH_UNAVAILABLE


async def test_a_failing_health_verdict_refuses_the_enable(harness: Harness) -> None:
    results = [
        HealthCheckResult(
            check_name=n,
            status="FAIL" if n == ALL_CHECK_NAMES[0] else "PASS",
            detail="x",
            observed_at_utc=T0,
        )
        for n in ALL_CHECK_NAMES
    ]
    harness.overrides["health"] = lambda: run_health_checks(
        results=results, mode=HealthRuntimeMode.DEMO
    )
    outcome = await harness.run()
    assert not outcome.enabled and outcome.enable_reason == "HEALTH_NOT_OK"
    assert harness.enablement is not None and harness.enablement.is_disabled


def test_startup_refused_carries_a_code_and_fixed_text() -> None:
    refusal = StartupRefused("X", "fixed")
    assert (refusal.code, refusal.message) == ("X", "fixed")


# --------------------------------------------------------------------------- #
# Tracer: over the live rig, nothing is placed before the last step.
# --------------------------------------------------------------------------- #


async def test_a_confirm_before_the_last_step_places_nothing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.support.live_rig import forbid_real_sleep, make_live_rig

    forbid_real_sleep(monkeypatch)
    rig = await make_live_rig()
    rig.enablement.disable(operator_id="start", now_utc=T0)  # a start is DISABLED (T-24-66)
    placements_at_row: list[int] = []
    inner_record = harness.ports().record

    async def watch(event: JournalEvent) -> None:
        placements_at_row.append(len(rig.fake.calls_to("place_entry")))
        await inner_record(event)

    base_ports = harness.ports()
    pressed: list[bool] = []

    async def reconcile_with_press(now: datetime) -> TickReport:
        # Step 8: an operator's APPROVE and CONFIRM arrive while the sequence is still running.
        # The bot is not started, but even a press that reached the flow ends in NO_TRADE.
        await rig.approve_and_confirm()
        await rig.wiring.service.drain()
        pressed.append(True)
        return TickReport(outcome=TICK_COMPARED, now_utc=now, agreement=True)

    ports = replace(
        base_ports,
        record=watch,
        reconcile_tick=reconcile_with_press,
        start_enablement=lambda: StartEnablement(
            controller=rig.enablement, persisted_enabled=False, persisted_problem=None
        ),
    )
    outcome = await run_start_sequence(ports, now_utc=T0)

    assert pressed == [True]
    (placement,) = rig.journal.by_type("LIVE_PLACEMENT_OUTCOME")
    assert json.loads(placement.payload_json)["reason_code"] == "DISABLED", "refused, not lost"
    assert outcome.admitted and outcome.enabled
    assert rig.fake.calls_to("place_entry") == [], (
        "the CONFIRM during the sequence reached the manager while DISABLED: nothing was placed"
    )
    assert set(placements_at_row) == {0}, "no placement at any step row, ENABLE included"


async def test_the_first_entry_is_placed_only_after_the_sequence_completes(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.support.live_rig import forbid_real_sleep, make_live_rig

    forbid_real_sleep(monkeypatch)
    rig = await make_live_rig()
    rig.enablement.disable(operator_id="start", now_utc=T0)
    ports = replace(
        harness.ports(),
        start_enablement=lambda: StartEnablement(
            controller=rig.enablement, persisted_enabled=False, persisted_problem=None
        ),
    )
    outcome = await run_start_sequence(ports, now_utc=T0)
    assert outcome.enabled and outcome.steps[-1].name == "ENABLE"
    assert rig.fake.calls_to("place_entry") == []

    await rig.approve_and_confirm()
    await rig.wiring.service.drain()

    assert len(rig.fake.calls_to("place_entry")) == 1, "one entry, and only after the sequence"
