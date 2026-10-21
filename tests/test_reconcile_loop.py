"""Reconcile loop tests (Phase 20, plan 20-12, EXEC-02, D-01, D-02, D-07).

One `ReconcileLoop.tick` reads the three Binance truth snapshots, derives the local intent from
the protection coordinator's view and the unresolved intent rows, runs compare v2, classifies
every divergence and acts through exactly one owner: SAFE_MODE for everything, the sweeper for
orphans only, the coordinator for stop-related exposure, an alert for the rest.

Evidence label: executed unit tests with fakes. Nothing here touches Binance, Telegram or a
database, and nothing is a Demo observation. The loop is a library; Phase 24 composes it.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.reconcile import compare as compare_module
from src.reconcile.classify import POLICY_BY_KIND
from src.reconcile.loop import (
    ALERT_SINK_FAILED,
    RECONCILE_TICK,
    TICK_COMPARED,
    TICK_SKIPPED_OVERLAP,
    ReconcileLoop,
)
from src.reconcile.safe_mode import SafeModeController
from src.reconcile.sweeper import OrphanSweeper

from tests.support.ast_guards import float_constructor_calls, forbidden_imports, wall_clock_calls
from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.reconcile_doubles import (
    FakeGate,
    FakeProtectionView,
    FakeReconcileAdapter,
    InMemorySafeModeStore,
    RecordingAlertSink,
    RecordingJournal,
    make_algo_order,
    make_open_order,
    make_plan_protection,
    make_position,
)

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
H1 = "1" * 64
SRC_RECONCILE = Path(__file__).parent.parent / "src" / "reconcile"
NEW_MODULES = ("loop.py", "classify.py", "local_intent.py")


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
        raise AssertionError("the reconcile loop must never exit SAFE_MODE")


@dataclass
class Rig:
    loop: ReconcileLoop
    adapter: FakeReconcileAdapter
    gate: FakeGate
    safe_mode: SpyingSafeMode
    intents: InMemoryExecutionIntentStore
    protection: FakeProtectionView
    sweeper: OrphanSweeper
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
    gate: FakeGate | None = None,
    protection: FakeProtectionView | None = None,
    alerts: RecordingAlertSink | None = None,
    intents: Any = None,
    unknown_entries: Any = None,
    limits: Any = None,
) -> Rig:
    fake = adapter or FakeReconcileAdapter(
        normal_orders=normal, algo_orders=algo, positions=positions
    )
    safe_mode = SpyingSafeMode(
        adapter=fake, journal=RecordingJournal(), state_store=InMemorySafeModeStore()
    )
    sweeper_journal = RecordingJournal()
    sweeper = OrphanSweeper(adapter=fake, journal=sweeper_journal)
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
    assert set(POLICY_BY_KIND) == compare_module._DIVERGENCE_KINDS


@pytest.mark.parametrize("module", NEW_MODULES)
def test_new_modules_are_pure(module: str) -> None:
    path = SRC_RECONCILE / module
    assert (
        forbidden_imports(path, ["src.adapters", "binance_sdk", "sqlalchemy", "src.persistence"])
        == []
    )
    assert wall_clock_calls(path) == []
    assert float_constructor_calls(path) == []
