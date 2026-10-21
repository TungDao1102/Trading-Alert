"""Reconcile loop tests (Phase 20, plan 20-12, EXEC-02, D-01, D-02, D-07).

One `ReconcileLoop.tick` reads the three Binance truth snapshots, derives the local intent from
the protection coordinator's view and the unresolved intent rows, runs compare v2, classifies
every divergence and acts through exactly one owner: SAFE_MODE for everything, the sweeper for
orphans only, the coordinator for stop-related exposure, an alert for the rest.

Evidence label: executed unit tests with fakes. Nothing here touches Binance, Telegram or a
database, and nothing is a Demo observation. The loop is a library; Phase 24 composes it.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_limits import RateLimitPolicy
from src.adapters.binance_ratelimit_gate import (
    GATE_NOT_RESTORED,
    GATE_STATE_UNKNOWN,
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    GateRestriction,
    RestRateLimitGate,
)
from src.domain.enums import OrderRole
from src.execution.execution_limits import ExecutionLimitsInvalid, ExecutionLimitsNotConfigured
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.ops.rest_gate_state import FileGateStateStore
from src.reconcile.classify import POLICY_BY_KIND
from src.reconcile.loop import (
    ALERT_SINK_FAILED,
    RECONCILE_ACTION_FAILED,
    RECONCILE_READ_FAILED,
    RECONCILE_SKIPPED_GATE,
    RECONCILE_SKIPPED_RESTORE_PENDING,
    RECONCILE_TICK,
    TICK_COMPARED,
    TICK_READ_FAILED,
    TICK_SKIPPED_GATE,
    TICK_SKIPPED_OVERLAP,
    TICK_SKIPPED_RESTORE_PENDING,
    ReconcileLoop,
)
from src.reconcile.safe_mode import SafeModeController
from src.reconcile.sweeper import OrphanSweeper

from tests.support.ast_guards import float_constructor_calls, forbidden_imports, wall_clock_calls
from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.reconcile_doubles import (
    FakeGate,
    FakeIntentStore,
    FakeProtectionView,
    FakeReconcileAdapter,
    InMemorySafeModeStore,
    RecordingAlertSink,
    RecordingJournal,
    make_algo_order,
    make_intent_record,
    make_open_order,
    make_plan_protection,
    make_position,
)

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
H1 = "1" * 64
SRC_RECONCILE = Path(__file__).parent.parent / "src" / "reconcile"
NEW_MODULES = ("loop.py", "classify.py", "local_intent.py")


EXIT_CALLS: list[str] = []


@pytest.fixture(autouse=True)
def _no_loop_test_exits_safe_mode() -> Any:
    """Across every loop test: `exit_safe_mode` is never called (the operator alone exits)."""
    EXIT_CALLS.clear()
    yield
    assert EXIT_CALLS == [], "a reconcile tick called exit_safe_mode"


class SpyingSafeMode(SafeModeController):
    """The real controller; records every enter and fails the test on any exit."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.enter_calls: list[str] = []
        self.exit_calls = 0

    def enter_safe_mode(self, *, reason: str, now_utc: datetime | None = None) -> None:
        self.enter_calls.append(reason)
        super().enter_safe_mode(reason=reason, now_utc=now_utc)

    async def exit_safe_mode(self, *args: Any, **kwargs: Any) -> Any:
        self.exit_calls += 1
        EXIT_CALLS.append("exit_safe_mode")
        raise AssertionError("the reconcile loop must never exit SAFE_MODE")


class SpySweeper:
    """Wraps the real sweeper and keeps every `CompareDiff` it was asked to sweep."""

    def __init__(self, inner: OrphanSweeper) -> None:
        self.inner = inner
        self.diffs: list[Any] = []

    async def sweep(self, diff: Any, *, position_verifier: Any, now_utc: datetime) -> Any:
        self.diffs.append(diff)
        return await self.inner.sweep(diff, position_verifier=position_verifier, now_utc=now_utc)


@dataclass
class Rig:
    loop: ReconcileLoop
    adapter: FakeReconcileAdapter
    gate: Any
    safe_mode: Any
    intents: Any
    protection: FakeProtectionView
    sweeper: Any
    alerts: RecordingAlertSink
    journal: RecordingJournal
    sweeper_journal: RecordingJournal

    def event_types(self) -> list[str]:
        return [e.event_type for e in self.journal.events]


def make_rig(
    *,
    plans: tuple[Any, ...] = (),
    normal: tuple[Any, ...] = (),
    algo: tuple[Any, ...] = (),
    positions: tuple[Any, ...] = (),
    adapter: FakeReconcileAdapter | None = None,
    gate: Any = None,
    protection: FakeProtectionView | None = None,
    alerts: RecordingAlertSink | None = None,
    intents: Any = None,
    unknown_entries: Any = None,
    limits: Any = None,
    sweeper: Any = None,
    spy_sweeper: bool = False,
    safe_mode: Any = None,
) -> Rig:
    fake = adapter or FakeReconcileAdapter(
        normal_orders=normal, algo_orders=algo, positions=positions
    )
    safe_mode = safe_mode or SpyingSafeMode(
        adapter=fake, journal=RecordingJournal(), state_store=InMemorySafeModeStore()
    )
    sweeper_journal = RecordingJournal()
    sweeper = sweeper or OrphanSweeper(adapter=fake, journal=sweeper_journal)
    if spy_sweeper:
        sweeper = SpySweeper(sweeper)
    gate_double = gate or FakeGate()
    store = intents if intents is not None else InMemoryExecutionIntentStore()
    view = protection or FakeProtectionView(plans)
    sink = alerts or RecordingAlertSink()
    journal = RecordingJournal()
    loop = ReconcileLoop(
        adapter=fake,
        gate=gate_double,
        safe_mode=safe_mode,
        intent_store=store,
        protection=view,
        sweeper=sweeper,
        alerts=sink,
        journal=journal,
        limits=limits or make_test_limits(),
        unknown_entries=unknown_entries,
    )
    return Rig(
        loop=loop,
        adapter=fake,
        gate=gate_double,
        safe_mode=safe_mode,
        intents=store,
        protection=view,
        sweeper=sweeper,
        alerts=sink,
        journal=journal,
        sweeper_journal=sweeper_journal,
    )


def protected_btc_plan() -> Any:
    """BTCUSDT LONG 0.004, stop confirmed, entry terminal: state PROTECTED."""
    return make_plan_protection(H1, symbol="BTCUSDT", state="PROTECTED")


def matching_btc_truth() -> dict[str, tuple[Any, ...]]:
    """The exchange state that agrees with `protected_btc_plan`."""
    return {
        "algo": (
            make_algo_order(
                derive_algo_client_id(plan_hash=H1, role=OrderRole.STOP_LOSS.value), "BTCUSDT"
            ),
        ),
        "positions": (make_position("BTCUSDT", "0.004"),),
    }


FOREIGN_ID = "web_manual_1"


# --------------------------------------------------------------------------- #
# Task 1 (tracer): one tick with a foreign order.
# --------------------------------------------------------------------------- #


async def test_foreign_order_tick_enters_safe_mode_alerts_and_cancels_nothing() -> None:
    truth = matching_btc_truth()
    rig = make_rig(
        plans=(protected_btc_plan(),),
        normal=(make_open_order(FOREIGN_ID, "ETHUSDT"),),
        algo=truth["algo"],
        positions=truth["positions"],
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert [d.kind for d in report.divergences] == ["FOREIGN_ORDER"]
    assert rig.safe_mode.in_safe_mode is True
    assert rig.safe_mode.entered_reason == "FOREIGN_ORDER"
    assert [(a.event, a.subject, a.reason) for a in rig.alerts.alerts] == [
        ("FOREIGN_ORDER", "ETHUSDT", "FOREIGN_ORDER")
    ]
    assert rig.adapter.cancelled_normal == []
    assert rig.adapter.cancelled_algo == []
    assert rig.protection.notified == []
    assert rig.sweeper_journal.events == []
    for name in (
        "snapshot_open_normal_orders",
        "snapshot_open_algo_orders",
        "snapshot_positions",
    ):
        assert rig.adapter.count(name) == 1, name


async def test_clean_tick_agrees_without_safe_mode_or_alert() -> None:
    truth = matching_btc_truth()
    rig = make_rig(plans=(protected_btc_plan(),), algo=truth["algo"], positions=truth["positions"])

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert report.agreement is True
    assert report.divergences == ()
    assert rig.safe_mode.enter_calls == []
    assert rig.safe_mode.in_safe_mode is False
    assert rig.alerts.alerts == []
    assert rig.event_types() == [RECONCILE_TICK]


async def test_a_tick_calls_no_placement_or_cancel_of_a_normal_order() -> None:
    truth = matching_btc_truth()
    rig = make_rig(
        plans=(protected_btc_plan(),),
        normal=(make_open_order(FOREIGN_ID, "ETHUSDT"),),
        algo=truth["algo"],
        positions=truth["positions"],
    )

    await rig.loop.tick(now_utc=NOW)

    assert rig.adapter.forbidden_calls == []
    assert set(rig.adapter.calls) <= {
        "snapshot_open_normal_orders",
        "snapshot_open_algo_orders",
        "snapshot_positions",
    }


async def test_the_tick_journal_row_counts_divergences_per_kind() -> None:
    truth = matching_btc_truth()
    rig = make_rig(
        plans=(protected_btc_plan(),),
        normal=(
            make_open_order(FOREIGN_ID, "ETHUSDT"),
            make_open_order("web_manual_2", "SOLUSDT"),
        ),
        algo=truth["algo"],
        positions=truth["positions"],
    )

    await rig.loop.tick(now_utc=NOW)

    assert rig.event_types() == [RECONCILE_TICK]
    payload = json.loads(rig.journal.events[0].payload_json)
    assert payload["outcome"] == TICK_COMPARED
    assert payload["divergence_count"] == 2
    assert payload["counts"] == {"FOREIGN_ORDER": 2}
    assert payload["safe_mode_reasons"] == ["FOREIGN_ORDER"]


async def test_a_raising_alert_sink_is_journaled_by_type_name_and_the_tick_completes() -> None:
    truth = matching_btc_truth()
    secret = "token=hunter2-do-not-journal"
    sink = RecordingAlertSink(fail_with=RuntimeError(secret))
    rig = make_rig(
        plans=(protected_btc_plan(),),
        normal=(make_open_order(FOREIGN_ID, "ETHUSDT"),),
        algo=truth["algo"],
        positions=truth["positions"],
        alerts=sink,
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert rig.safe_mode.in_safe_mode is True
    assert sink.attempts == 1
    assert rig.event_types() == [ALERT_SINK_FAILED, RECONCILE_TICK]
    failed = json.loads(rig.journal.events[0].payload_json)
    assert failed["error_type"] == "RuntimeError"
    assert all(secret not in e.payload_json for e in rig.journal.events)


async def test_an_overlapping_tick_is_skipped_while_one_is_running() -> None:
    pause = asyncio.Event()
    adapter = FakeReconcileAdapter(pause=pause)
    rig = make_rig(adapter=adapter)

    first = asyncio.create_task(rig.loop.tick(now_utc=NOW))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    second = await rig.loop.tick(now_utc=NOW)

    assert second.outcome == TICK_SKIPPED_OVERLAP
    assert adapter.count("snapshot_open_normal_orders") == 1
    pause.set()
    finished = await first
    assert finished.outcome == TICK_COMPARED


def test_policy_table_covers_every_divergence_kind() -> None:
    assert set(POLICY_BY_KIND) == importlib.import_module("src.reconcile.compare")._DIVERGENCE_KINDS


@pytest.mark.parametrize("module", NEW_MODULES)
def test_new_modules_are_pure(module: str) -> None:
    path = SRC_RECONCILE / module
    assert (
        forbidden_imports(path, ["src.adapters", "binance_sdk", "sqlalchemy", "src.persistence"])
        == []
    )
    assert wall_clock_calls(path) == []
    assert float_constructor_calls(path) == []


# --------------------------------------------------------------------------- #
# Task 2: sweep, delegation, gate skip, failed reads and constructor refusals.
# --------------------------------------------------------------------------- #

SL_ID = derive_algo_client_id(plan_hash=H1, role=OrderRole.STOP_LOSS.value)
ENTRY_ID = derive_client_order_id(plan_hash=H1, role=OrderRole.ENTRY.value)
H2 = "2" * 64


class RecordingStepper:
    """Stands in for `UnknownEntryResolver`: records the time and what had been read by then."""

    def __init__(
        self, adapter: FakeReconcileAdapter | None = None, *, raises: bool = False
    ) -> None:
        self.times: list[datetime] = []
        self.calls_seen: list[int] = []
        self._adapter = adapter
        self._raises = raises

    async def step(self, *, now_utc: datetime) -> Any:
        self.times.append(now_utc)
        self.calls_seen.append(0 if self._adapter is None else len(self._adapter.calls))
        if self._raises:
            raise RuntimeError("password=hunter2")
        return "unknown-report"


async def test_orphan_protective_is_swept_once_with_safe_mode_and_an_alert() -> None:
    rig = make_rig(
        intents=FakeIntentStore([make_intent_record(H1, OrderRole.STOP_LOSS.value)]),
        algo=(make_algo_order(SL_ID, "BTCUSDT"),),
        spy_sweeper=True,
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert [d.kind for d in report.divergences] == ["ORPHAN_PROTECTIVE"]
    assert rig.safe_mode.entered_reason == "ORPHAN_PROTECTIVE"
    assert len(rig.sweeper.diffs) == 1
    assert [o.client_algo_id for o in rig.sweeper.diffs[0].orphan_protectives] == [SL_ID]
    assert rig.adapter.cancelled_algo == [("BTCUSDT", SL_ID)]
    assert report.swept == (("BTCUSDT", SL_ID),)
    assert [(a.event, a.subject, a.reason) for a in rig.alerts.alerts] == [
        ("DIVERGENCE", "BTCUSDT", "ORPHAN_PROTECTIVE")
    ]
    assert rig.adapter.forbidden_calls == []


async def test_a_resting_entrys_stop_is_never_passed_to_the_sweeper() -> None:
    plan = make_plan_protection(
        H1, state="AWAITING_FILL", first_fill=False, stop_confirmed=False, entry_terminal=False
    )
    rig = make_rig(
        plans=(plan,),
        intents=FakeIntentStore([make_intent_record(H1, OrderRole.STOP_LOSS.value)]),
        normal=(make_open_order(ENTRY_ID, "BTCUSDT"),),
        algo=(make_algo_order(SL_ID, "BTCUSDT"),),
        spy_sweeper=True,
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.agreement is True
    assert rig.sweeper.diffs == []
    assert rig.adapter.cancelled_algo == []


async def test_an_exchange_entry_resting_for_an_untracked_plan_keeps_its_stop_off_the_sweeper() -> (
    None
):
    rig = make_rig(
        intents=FakeIntentStore([make_intent_record(H1, OrderRole.STOP_LOSS.value)]),
        normal=(make_open_order(ENTRY_ID, "BTCUSDT"),),
        algo=(make_algo_order(SL_ID, "BTCUSDT"),),
        spy_sweeper=True,
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert [d.kind for d in report.divergences] == ["UNTRACKED_SYSTEM_ORDER"]
    assert rig.sweeper.diffs == []
    assert rig.adapter.cancelled_algo == []
    assert rig.adapter.cancelled_normal == []
    assert [a.event for a in rig.alerts.alerts] == ["UNKNOWN_ORDER"]


async def test_position_without_stop_is_delegated_once_and_alerted_as_unprotected() -> None:
    rig = make_rig(plans=(protected_btc_plan(),), positions=(make_position("BTCUSDT", "0.004"),))

    report = await rig.loop.tick(now_utc=NOW)

    assert sorted(d.kind for d in report.divergences) == ["POSITION_WITHOUT_STOP", "UNSYNCED_ALGO"]
    assert rig.protection.notified == [(H1, "POSITION_WITHOUT_STOP")]
    assert report.delegated == ((H1, "POSITION_WITHOUT_STOP"),)
    by_reason = {a.reason: a for a in rig.alerts.alerts}
    assert by_reason["POSITION_WITHOUT_STOP"].event == "UNPROTECTED_POSITION"
    assert by_reason["POSITION_WITHOUT_STOP"].plan_hash == H1
    assert by_reason["UNSYNCED_ALGO"].event == "DIVERGENCE"
    assert rig.adapter.cancelled_algo == []
    assert rig.adapter.forbidden_calls == []


async def test_safe_mode_ends_on_the_most_urgent_reason_of_the_tick() -> None:
    rig = make_rig(plans=(protected_btc_plan(),), positions=(make_position("BTCUSDT", "0.004"),))

    await rig.loop.tick(now_utc=NOW)

    assert rig.safe_mode.enter_calls == ["UNSYNCED_ALGO", "POSITION_WITHOUT_STOP"]
    assert rig.safe_mode.entered_reason == "POSITION_WITHOUT_STOP"


async def test_position_without_stop_for_an_untracked_plan_still_alerts() -> None:
    plan = protected_btc_plan()
    rig = make_rig(
        protection=FakeProtectionView((plan,), known=()),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert rig.protection.notified == [(H1, "POSITION_WITHOUT_STOP")]
    assert report.delegated == ()
    assert ("BTCUSDT", "POSITION_WITHOUT_STOP") in report.undelegated
    assert "UNPROTECTED_POSITION" in [a.event for a in rig.alerts.alerts]


async def test_exposure_with_no_tracked_plan_is_alerted_and_delegated_to_nobody() -> None:
    rig = make_rig(positions=(make_position("BTCUSDT", "0.004"),))

    report = await rig.loop.tick(now_utc=NOW)

    assert sorted(d.kind for d in report.divergences) == [
        "POSITION_WITHOUT_STOP",
        "UNSYNCED_POSITION",
    ]
    assert rig.protection.notified == []
    alert = next(a for a in rig.alerts.alerts if a.reason == "POSITION_WITHOUT_STOP")
    assert (alert.event, alert.plan_hash, alert.subject) == (
        "UNPROTECTED_POSITION",
        None,
        "BTCUSDT",
    )


async def test_two_candidate_plans_on_one_symbol_are_never_guessed() -> None:
    second = make_plan_protection(H2, symbol="BTCUSDT", state="PROTECTED")
    rig = make_rig(
        plans=(protected_btc_plan(), second), positions=(make_position("BTCUSDT", "0.004"),)
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert "AMBIGUOUS_POSITION_OWNER" in [d.kind for d in report.divergences]
    assert rig.protection.notified == []
    assert ("BTCUSDT", "POSITION_WITHOUT_STOP") in report.undelegated
    assert "UNPROTECTED_POSITION" in [a.event for a in rig.alerts.alerts]


@pytest.mark.parametrize(
    ("amount", "kind"),
    [("0.008", "DOUBLED_POSITION"), ("-0.004", "SIGN_FLIPPED_POSITION")],
)
async def test_bound_violations_use_the_plan_fields_and_go_to_the_coordinator(
    amount: str, kind: str
) -> None:
    truth = matching_btc_truth()
    rig = make_rig(
        plans=(protected_btc_plan(),),
        algo=truth["algo"],
        positions=(make_position("BTCUSDT", amount),),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert [d.kind for d in report.divergences] == [kind]
    assert rig.protection.notified == [(H1, kind)]
    assert rig.safe_mode.entered_reason == kind
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [("DIVERGENCE", kind)]


async def test_several_foreign_orders_enter_safe_mode_once_and_alert_each() -> None:
    truth = matching_btc_truth()
    rig = make_rig(
        plans=(protected_btc_plan(),),
        normal=(make_open_order("web_1", "ETHUSDT"), make_open_order("web_2", "SOLUSDT")),
        algo=truth["algo"],
        positions=truth["positions"],
    )

    await rig.loop.tick(now_utc=NOW)

    assert rig.safe_mode.enter_calls == ["FOREIGN_ORDER"]
    assert [a.subject for a in rig.alerts.alerts] == ["ETHUSDT", "SOLUSDT"]
    assert rig.adapter.cancelled_normal == []


@pytest.mark.parametrize(
    "reason", [IP_BAN_418, RATE_LIMIT_PAUSE_429, GATE_NOT_RESTORED, GATE_STATE_UNKNOWN]
)
async def test_a_gate_restriction_means_no_rest_read_and_a_journal_row(reason: str) -> None:
    adapter = FakeReconcileAdapter()
    stepper = RecordingStepper(adapter)
    restriction = GateRestriction(reason=reason, until_utc=None, remaining_seconds=1)
    rig = make_rig(adapter=adapter, gate=FakeGate(restriction), unknown_entries=stepper)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_SKIPPED_GATE
    assert report.gate_reason == reason
    assert adapter.calls == []
    assert stepper.times == []
    assert rig.protection.protections_calls == 0
    assert rig.event_types() == [RECONCILE_SKIPPED_GATE]
    assert json.loads(rig.journal.events[0].payload_json)["reason"] == reason
    assert rig.safe_mode.enter_calls == []
    assert rig.safe_mode.in_safe_mode is False
    assert rig.alerts.alerts == []


async def test_a_real_gate_that_is_not_restored_blocks_every_read_until_restored(
    tmp_path: Path,
) -> None:
    def clock() -> datetime:
        return NOW

    store = FileGateStateStore(tmp_path / "gate.json", clock=clock)
    store.initialize(now_utc=NOW, operator_id="op-1")
    gate = RestRateLimitGate(
        policy=RateLimitPolicy(
            no_retry_after_wait_418_seconds=259200,
            no_retry_after_wait_429_seconds=120,
            retry_after_cap_seconds=600,
        ),
        clock=clock,
        state_store=store,
    )
    truth = matching_btc_truth()
    rig = make_rig(
        plans=(protected_btc_plan(),), gate=gate, algo=truth["algo"], positions=truth["positions"]
    )

    blocked = await rig.loop.tick(now_utc=NOW)
    gate.restore()
    compared = await rig.loop.tick(now_utc=NOW)

    assert (blocked.outcome, blocked.gate_reason) == (TICK_SKIPPED_GATE, GATE_NOT_RESTORED)
    assert compared.outcome == TICK_COMPARED
    assert compared.agreement is True
    assert rig.adapter.count("snapshot_positions") == 1


async def test_a_gate_that_raises_fails_closed_without_any_read() -> None:
    adapter = FakeReconcileAdapter()
    rig = make_rig(adapter=adapter, gate=FakeGate(raises=RuntimeError("token=abc")))

    report = await rig.loop.tick(now_utc=NOW)

    assert (report.outcome, report.failed_source) == (TICK_READ_FAILED, "gate")
    assert adapter.calls == []
    assert rig.safe_mode.enter_calls == ["API_DEGRADATION"]


async def test_restore_pending_means_no_read_and_no_unknown_step() -> None:
    adapter = FakeReconcileAdapter()
    stepper = RecordingStepper(adapter)
    rig = make_rig(
        adapter=adapter,
        protection=FakeProtectionView((protected_btc_plan(),), restore_complete=False),
        unknown_entries=stepper,
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_SKIPPED_RESTORE_PENDING
    assert adapter.calls == []
    assert stepper.times == []
    assert rig.protection.protections_calls == 0
    assert rig.event_types() == [RECONCILE_SKIPPED_RESTORE_PENDING]
    assert rig.safe_mode.enter_calls == []


_READS = (
    ("snapshot_open_normal_orders", "open_normal_orders", ("snapshot_open_algo_orders",)),
    ("snapshot_open_algo_orders", "open_algo_orders", ("snapshot_positions",)),
    ("snapshot_positions", "positions", ()),
)


@pytest.mark.parametrize(("method", "source", "never_reached"), _READS)
async def test_a_failed_truth_read_enters_api_degradation_and_compares_nothing(
    method: str, source: str, never_reached: tuple[str, ...]
) -> None:
    secret = "api-key=abc123-do-not-journal"
    adapter = FakeReconcileAdapter(
        normal_orders=(make_open_order(FOREIGN_ID, "ETHUSDT"),),
        algo_orders=(make_algo_order(SL_ID, "BTCUSDT"),),
        fail={method: RuntimeError(secret)},
    )
    rig = make_rig(adapter=adapter, spy_sweeper=True)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_READ_FAILED
    assert report.failed_source == source
    assert report.agreement is None
    assert report.divergences == ()
    assert rig.safe_mode.enter_calls == ["API_DEGRADATION"]
    assert rig.event_types() == [RECONCILE_READ_FAILED]
    assert json.loads(rig.journal.events[0].payload_json) == {
        "error_type": "RuntimeError",
        "source": source,
    }
    assert all(secret not in e.payload_json for e in rig.journal.events)
    assert rig.alerts.alerts == []
    assert rig.sweeper.diffs == []
    assert all(adapter.count(name) == 0 for name in never_reached)
    assert rig.protection.protections_calls == 0


async def test_a_snapshot_that_is_not_a_list_is_a_failed_read() -> None:
    adapter = FakeReconcileAdapter()

    async def nothing(*, symbol: str | None = None) -> None:
        return None

    adapter.snapshot_positions = nothing  # type: ignore[method-assign,assignment]
    rig = make_rig(adapter=adapter)

    report = await rig.loop.tick(now_utc=NOW)

    assert (report.outcome, report.failed_source) == (TICK_READ_FAILED, "positions")
    assert rig.safe_mode.enter_calls == ["API_DEGRADATION"]


class _NoneProtections(FakeProtectionView):
    def protections(self) -> Any:
        self.protections_calls += 1
        return None


@pytest.mark.parametrize("failure", ["store", "protections", "none"])
async def test_a_failed_local_read_enters_db_failure_and_compares_nothing(failure: str) -> None:
    secret = "dsn=postgres://user:hunter2@host"
    store = FakeIntentStore(raises=RuntimeError(secret) if failure == "store" else None)
    if failure == "protections":
        view: FakeProtectionView = FakeProtectionView(protections_raises=RuntimeError(secret))
    elif failure == "none":
        view = _NoneProtections()
    else:
        view = FakeProtectionView()
    rig = make_rig(protection=view, intents=store, normal=(make_open_order(FOREIGN_ID, "ETHUSDT"),))

    report = await rig.loop.tick(now_utc=NOW)

    assert (report.outcome, report.failed_source) == (TICK_READ_FAILED, "local_intent")
    assert rig.safe_mode.enter_calls == ["DB_FAILURE"]
    assert report.divergences == ()
    assert rig.alerts.alerts == []
    assert rig.event_types() == [RECONCILE_READ_FAILED]
    assert all(secret not in e.payload_json for e in rig.journal.events)


async def test_a_compare_error_is_never_agreement() -> None:
    bad = dataclasses.replace(make_position("BTCUSDT", "0.004"), position_amt=0.004)
    rig = make_rig(positions=(bad,))

    report = await rig.loop.tick(now_utc=NOW)

    assert (report.outcome, report.failed_source) == (TICK_READ_FAILED, "compare")
    assert report.agreement is None
    assert rig.safe_mode.enter_calls == ["API_DEGRADATION"]
    assert rig.alerts.alerts == []


async def test_an_unknown_protection_state_is_a_failed_local_read() -> None:
    odd = dataclasses.replace(protected_btc_plan(), state="NOT_A_STATE")
    rig = make_rig(plans=(odd,))

    report = await rig.loop.tick(now_utc=NOW)

    assert (report.outcome, report.failed_source) == (TICK_READ_FAILED, "local_intent")
    assert rig.safe_mode.enter_calls == ["DB_FAILURE"]


async def test_a_failing_safe_mode_save_is_journaled_and_entries_stay_blocked() -> None:
    class FailingStore(InMemorySafeModeStore):
        def save(self, state: Any, *, now_utc: datetime) -> None:
            raise RuntimeError("connection string leaked")

    adapter = FakeReconcileAdapter(normal_orders=(make_open_order(FOREIGN_ID, "ETHUSDT"),))
    controller = SpyingSafeMode(
        adapter=adapter, journal=RecordingJournal(), state_store=FailingStore()
    )
    rig = make_rig(adapter=adapter, safe_mode=controller)

    report = await rig.loop.tick(now_utc=NOW)

    assert controller.in_safe_mode is True
    assert report.action_failures == ("safe_mode_enter",)
    assert len(rig.alerts.alerts) == 1
    failed = [e for e in rig.journal.events if e.event_type == RECONCILE_ACTION_FAILED]
    assert json.loads(failed[0].payload_json)["error_type"] == "RuntimeError"
    assert "connection string" not in failed[0].payload_json


async def test_a_raising_notice_is_journaled_and_the_alert_still_goes_out() -> None:
    rig = make_rig(
        protection=FakeProtectionView((protected_btc_plan(),), notify_raises=RuntimeError("boom")),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert "notify_divergence" in report.action_failures
    assert report.delegated == ()
    assert "UNPROTECTED_POSITION" in [a.event for a in rig.alerts.alerts]


async def test_a_raising_sweeper_is_journaled_and_safe_mode_stays() -> None:
    class RaisingSweeper:
        async def sweep(self, diff: Any, *, position_verifier: Any, now_utc: datetime) -> Any:
            raise RuntimeError("cancel endpoint down")

    rig = make_rig(
        intents=FakeIntentStore([make_intent_record(H1, OrderRole.STOP_LOSS.value)]),
        algo=(make_algo_order(SL_ID, "BTCUSDT"),),
        sweeper=RaisingSweeper(),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.action_failures == ("sweep",)
    assert report.swept == ()
    assert rig.safe_mode.entered_reason == "ORPHAN_PROTECTIVE"
    assert [a.event for a in rig.alerts.alerts] == ["DIVERGENCE"]


async def test_the_unknown_entry_step_runs_once_before_any_read() -> None:
    truth = matching_btc_truth()
    adapter = FakeReconcileAdapter(algo_orders=truth["algo"], positions=truth["positions"])
    stepper = RecordingStepper(adapter)
    rig = make_rig(adapter=adapter, plans=(protected_btc_plan(),), unknown_entries=stepper)

    report = await rig.loop.tick(now_utc=NOW)

    assert stepper.times == [NOW]
    assert stepper.calls_seen == [0]
    assert report.unknown_entries == "unknown-report"
    assert report.agreement is True


async def test_a_raising_unknown_entry_step_enters_safe_mode_and_the_tick_goes_on() -> None:
    truth = matching_btc_truth()
    adapter = FakeReconcileAdapter(algo_orders=truth["algo"], positions=truth["positions"])
    stepper = RecordingStepper(adapter, raises=True)
    rig = make_rig(adapter=adapter, plans=(protected_btc_plan(),), unknown_entries=stepper)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.action_failures == ("unknown_entry_step",)
    assert rig.safe_mode.enter_calls == ["API_DEGRADATION"]
    assert report.outcome == TICK_COMPARED
    assert adapter.count("snapshot_positions") == 1
    assert all("hunter2" not in e.payload_json for e in rig.journal.events)


async def test_a_naive_now_is_refused() -> None:
    rig = make_rig()
    with pytest.raises(ValueError):
        await rig.loop.tick(now_utc=datetime(2026, 9, 19, 0, 0))


# --------------------------------------------------------------------------- #
# Constructor refusals.
# --------------------------------------------------------------------------- #


def test_constructor_refuses_a_non_durable_safe_mode_controller() -> None:
    adapter = FakeReconcileAdapter()
    volatile = SafeModeController(adapter=adapter, journal=RecordingJournal())
    assert volatile.is_durable is False
    with pytest.raises(ValueError, match="durable"):
        make_rig(adapter=adapter, safe_mode=volatile)


@pytest.mark.parametrize(
    "field", ["reconcile_tick_interval_ms", "alerts_dedupe_window_ms", "max_unprotected_ms"]
)
def test_constructor_refuses_any_unset_limit(field: str) -> None:
    with pytest.raises(ExecutionLimitsNotConfigured):
        make_rig(limits=make_test_limits(**{field: None}))


@pytest.mark.parametrize("tick_ms", [7777, 7778, 100000])
def test_constructor_refuses_a_tick_not_below_max_unprotected(tick_ms: int) -> None:
    with pytest.raises(ExecutionLimitsInvalid):
        make_rig(limits=make_test_limits(reconcile_tick_interval_ms=tick_ms))


def test_the_tick_interval_is_the_configured_cadence() -> None:
    assert make_rig().loop.tick_interval_ms == 1234
    wider = make_rig(limits=make_test_limits(reconcile_tick_interval_ms=7776))
    assert wider.loop.tick_interval_ms == 7776


# --------------------------------------------------------------------------- #
# Static guards (T-20-28).
# --------------------------------------------------------------------------- #

_FORBIDDEN_CALL_PREFIXES = (
    "place_",
    "new_",
    "cancel",
    "finalize",
    "record_result",
    "record_fill",
    "insert",
    "update",
    "mark_",
    "exit_safe_mode",
    "close_",
)

_FORBIDDEN_IMPORT_PREFIXES = (
    "src.execution.intent_store",
    "src.execution.intent_recovery",
    "src.execution.protection",
    "src.execution.emergency_close",
    "src.execution.manager",
)


@pytest.mark.parametrize("module", NEW_MODULES)
def test_the_loop_modules_call_no_placement_cancel_exit_or_row_writer(module: str) -> None:
    tree = ast.parse((SRC_RECONCILE / module).read_text(encoding="utf-8"))
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)
    offenders = sorted(n for n in called if n.startswith(_FORBIDDEN_CALL_PREFIXES))
    assert offenders == []


@pytest.mark.parametrize("module", NEW_MODULES)
def test_the_loop_imports_no_store_closer_or_coordinator_module(module: str) -> None:
    path = SRC_RECONCILE / module
    assert forbidden_imports(path, _FORBIDDEN_IMPORT_PREFIXES) == []
