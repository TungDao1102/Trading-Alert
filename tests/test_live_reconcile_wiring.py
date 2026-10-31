"""The reconcile composition of the live process (plan 24-20; EXEC-02, G4-029, WR-B6).

Evidence label: executed tests with in-memory stores and the Binance-semantics fake exchange. No
network, no database and nothing here is `[DEMO]`. The loop, the sweeper, the UNKNOWN-entry
resolver, the SAFE_MODE controller, the alert sink and the lot-filter source are the REAL objects
built by `src.live.reconcile.build_reconcile`; only the edges are fakes (exchange, bot, stores,
feeds). Every number is TEST_ONLY.

Task 1 (tracer): a protected position reconciles clean; an orphan protective is swept with the
injected time (a `datetime.now` that raises proves no wall-clock fallback); a divergence enters
SAFE_MODE and its alerts reach the sink; the build refusals; an overlapping tick.
Task 2: lot filters (live, stored, plan snapshot), entry good-till, risk reducer, feed skew.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.domain.enums import OrderRole
from src.execution.emergency_close import MarketEmergencyCloser
from src.execution.execution_limits import (
    ExecutionLimits,
    ExecutionLimitsInvalid,
    ExecutionLimitsNotConfigured,
)
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.pending_actions import PendingKind
from src.execution.protection import ProtectionState
from src.live.alerts import AlertBundle, build_alerts, drain_once
from src.live.reconcile import (
    ReconcileBundle,
    build_lot_filters,
    build_reconcile,
    entry_good_till_by_plan_hash,
    entry_good_till_from_store,
    make_risk_reducer,
    reconcile_tick_once,
)
from src.reconcile.feed_freshness import FeedReading, clock_skew_from_drift
from src.reconcile.loop import (
    RECONCILE_TICK,
    TICK_COMPARED,
    TICK_SKIPPED_OVERLAP,
)
from src.reconcile.safe_mode import SafeModeController

from tests.shadow_fakes import make_shadow_plan, make_shadow_signal
from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.limits import test_only_binance_limits as make_binance_limits
from tests.support.live_rig import LiveRig, forbid_real_sleep, make_live_rig
from tests.support.lot_filter_fakes import InMemoryLotFilterStore
from tests.support.pending_action_fakes import InMemoryPendingActionStore
from tests.support.protection_doubles import (
    complete_constraint_snapshot,
    lot_filters_for_tests,
    resting_entry_for_tests,
)
from tests.support.reconcile_doubles import (
    FakeGate,
    FakeIntentStore,
    FakeProtectionView,
    InMemorySafeModeStore,
    RecordingJournal,
    make_intent_record,
    make_open_order,
    make_plan_protection,
)
from tests.support.reconcile_rig import FakeFeedSource, FakeStreamSource, QueryingAdapter
from tests.support.virtual_time import yield_to_loop

D = Decimal
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
H1 = "1" * 64
SYMBOL = "BTCUSDT"
SL_ID = derive_algo_client_id(plan_hash=H1, role=OrderRole.STOP_LOSS.value)
ENTRY_ID = derive_client_order_id(plan_hash=H1, role=OrderRole.ENTRY.value)
CHAT_ID = 4242


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


# --------------------------------------------------------------------------- #
# Doubles and the composition helper.
# --------------------------------------------------------------------------- #


class MiniBot:
    """Only `send_message` exists."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, *, chat_id: int | str, text: str, reply_markup: Any = None) -> Any:
        self.sent.append(text)
        return SimpleNamespace(message_id=len(self.sent))


class NoSleep:
    async def __call__(self, seconds: float) -> None:
        return None


class StepProtection(FakeProtectionView):
    """The coordinator hooks of the doubles plus an awaitable `step` that records its calls."""

    def __init__(self, plans: Any = (), **kwargs: Any) -> None:
        super().__init__(plans, **kwargs)
        self.steps = 0
        self.order: list[str] = []

    async def step(self) -> None:
        self.steps += 1
        self.order.append("coordinator.step")


class FakePlanStore:
    def __init__(self, plans: dict[str, Any]) -> None:
        self.plans = plans
        self.reads: list[str] = []

    def get_trade_plan(self, trade_plan_id: str) -> Any:
        self.reads.append(trade_plan_id)
        return self.plans.get(trade_plan_id)


class FakeSnapshotStore:
    def __init__(self, snapshots: dict[str, Any] | None = None) -> None:
        self.snapshots = snapshots or {}

    def get(self, trade_plan_id: str) -> Any:
        return self.snapshots.get(trade_plan_id)


class FilterAdapter(QueryingAdapter):
    """The reconcile read double plus the lot-filter read of the real adapter."""

    async def symbol_lot_filters(self, *, symbol: str) -> Any:
        self._enter("symbol_lot_filters")
        return lot_filters_for_tests()


@dataclass
class Parts:
    bundle: ReconcileBundle
    alerts: AlertBundle
    journal: RecordingJournal
    safe_mode: SafeModeController
    bot: MiniBot
    lot_store: InMemoryLotFilterStore
    coordinator: Any
    pending: InMemoryPendingActionStore
    feeds: FakeFeedSource

    def event_types(self) -> list[str]:
        return [e.event_type for e in self.journal.events]


def compose(
    *,
    adapter: Any,
    coordinator: Any,
    intent_store: Any,
    now: datetime = NOW,
    limits: ExecutionLimits | None = None,
    gate: Any = None,
    feeds: FakeFeedSource | None = None,
    stream: Any = None,
    pending: InMemoryPendingActionStore | None = None,
    plan_store: Any = None,
    safe_mode: Any = None,
    snapshot_store: Any = None,
    journal: RecordingJournal | None = None,
    lot_store: InMemoryLotFilterStore | None = None,
) -> Parts:
    the_limits = limits or make_test_limits()
    the_journal = journal or RecordingJournal()
    bot = MiniBot()
    alerts = build_alerts(
        journal=the_journal,
        spill=None,
        limits=the_limits,
        bot=bot,
        chat_id=CHAT_ID,
        sleep=NoSleep(),
        clock=lambda: now,
    )
    the_safe_mode = safe_mode or SafeModeController(
        adapter=adapter,
        journal=the_journal,
        state_store=InMemorySafeModeStore(),
        on_enter=alerts.safe_mode_observer,
    )
    the_store = lot_store or InMemoryLotFilterStore()
    lot_filters = build_lot_filters(
        adapter=adapter,
        store=the_store,
        snapshot_store=snapshot_store or FakeSnapshotStore(),
        limits=the_limits,
        clock=lambda: now,
    )
    the_feeds = feeds or FakeFeedSource(FeedReading({SYMBOL: now}, now))
    the_pending = pending or InMemoryPendingActionStore()
    bundle = build_reconcile(
        adapter=adapter,
        gate=gate or FakeGate(),
        safe_mode=the_safe_mode,
        intent_store=intent_store,
        coordinator=coordinator,
        closer=object(),
        alerts=alerts.sink,
        journal=the_journal,
        limits=the_limits,
        binance_limits=make_binance_limits(),
        feeds=the_feeds,
        stream=stream or FakeStreamSource(),
        lot_filters=lot_filters,
        pending_actions=the_pending,
        plan_store=plan_store or FakePlanStore({}),
    )
    return Parts(
        bundle=bundle,
        alerts=alerts,
        journal=the_journal,
        safe_mode=the_safe_mode,
        bot=bot,
        lot_store=the_store,
        coordinator=coordinator,
        pending=the_pending,
        feeds=the_feeds,
    )


async def protected_rig() -> LiveRig:
    """The tracer path of plan 24-04: CONFIRM, one entry, a fill, a REST-confirmed stop."""
    rig = await make_live_rig()
    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    rig.route(rig.trade_frame())
    await rig.wiring.coordinator.step()
    await rig.clock.advance(1)
    await rig.wiring.coordinator.step()
    protection = rig.wiring.coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.PROTECTED
    return rig


async def place_orphan_leg(fake: BinanceSemanticsFakeAdapter) -> None:
    await fake.place_algo_protective(
        symbol=SYMBOL,
        side="SELL",
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=D("59000"),
        close_position=True,
        quantity=None,
        working_type="MARK_PRICE",
        client_algo_id=SL_ID,
        reduce_only=None,
    )


# --------------------------------------------------------------------------- #
# Task 1 (tracer).
# --------------------------------------------------------------------------- #


async def test_a_protected_position_reconciles_clean_through_the_composed_loop() -> None:
    rig = await protected_rig()
    now = rig.clock.now()
    parts = compose(
        adapter=rig.fake,
        coordinator=rig.wiring.coordinator,
        intent_store=rig.intents,
        now=now,
        feeds=FakeFeedSource(FeedReading({SYMBOL: now - timedelta(seconds=1)}, now)),
    )

    report = await reconcile_tick_once(parts.bundle, now)

    assert report.outcome == TICK_COMPARED
    assert report.agreement is True, report.divergences
    assert report.safe_mode_reasons == ()
    assert parts.safe_mode.in_safe_mode is False
    assert RECONCILE_TICK in parts.event_types()
    assert report.order[-1] == "background", "the lot-filter refresh ran last"
    assert parts.lot_store.rows[SYMBOL][1] == now, "the refresh stored the live filters"
    assert len(parts.alerts.queue) == 0, "a clean tick raises no alert"
    assert len(rig.fake.calls_to("place_entry")) == 1, "reconcile places nothing"


async def test_an_orphan_protective_is_swept_with_the_injected_time_never_the_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    await place_orphan_leg(fake)
    parts = compose(
        adapter=fake,
        coordinator=StepProtection(),
        intent_store=FakeIntentStore([make_intent_record(H1, OrderRole.STOP_LOSS.value)]),
    )

    class NoWallClock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            raise AssertionError("the wall clock was read")

    import src.reconcile.safe_mode as safe_mode_module
    import src.reconcile.sweeper as sweeper_module

    monkeypatch.setattr(sweeper_module, "datetime", NoWallClock)
    monkeypatch.setattr(safe_mode_module, "datetime", NoWallClock)

    report = await reconcile_tick_once(parts.bundle, NOW)

    assert [d.kind for d in report.divergences] == ["ORPHAN_PROTECTIVE"]
    assert report.swept == ((SYMBOL, SL_ID),)
    assert SL_ID not in fake.open_algos
    assert len(fake.calls_to("snapshot_positions")) >= 3, "one compare read and two sweep reads"
    sweep_rows = [e for e in parts.journal.events if e.entity_type != "ReconcileLoop"]
    assert sweep_rows, "the sweeper journaled its pre and post image"
    assert {e.occurred_at_utc for e in sweep_rows if e.event_type.startswith("SWEEP")} <= {NOW}
    assert parts.safe_mode.entered_reason == "ORPHAN_PROTECTIVE"


async def test_a_local_intent_the_exchange_does_not_show_enters_safe_mode_and_alerts() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    parts = compose(
        adapter=fake,
        coordinator=StepProtection(),
        intent_store=FakeIntentStore([make_intent_record(H1, OrderRole.ENTRY.value)]),
    )

    report = await reconcile_tick_once(parts.bundle, NOW)

    assert report.agreement is False
    kinds = {d.kind for d in report.divergences}
    assert "UNSYNCED_NORMAL" in kinds
    assert parts.safe_mode.in_safe_mode is True
    assert parts.safe_mode.entered_reason in kinds
    queued = {(a.event, a.reason) for a in parts.alerts.queue}
    assert ("DIVERGENCE", "UNSYNCED_NORMAL") in queued
    delivered = await drain_once(parts.alerts)
    assert (delivered.delivered, delivered.failed) == (len(queued), 0)
    assert len(parts.bot.sent) == len(queued)


async def test_an_unreadable_local_source_enters_db_failure_and_the_safe_mode_alert_is_sent() -> (
    None
):
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    parts = compose(
        adapter=fake,
        coordinator=StepProtection(),
        intent_store=FakeIntentStore(raises=RuntimeError("db down")),
    )

    report = await reconcile_tick_once(parts.bundle, NOW)

    assert report.outcome != TICK_COMPARED
    assert parts.safe_mode.entered_reason == "DB_FAILURE"
    assert [a.event for a in parts.alerts.queue] == ["DB_FAILURE"], "the SAFE_MODE alert"
    await drain_once(parts.alerts)
    assert len(parts.bot.sent) == 1


async def test_the_build_refuses_a_controller_without_a_state_store() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    volatile = SafeModeController(adapter=fake, journal=RecordingJournal())

    with pytest.raises(ValueError, match="durable"):
        compose(
            adapter=fake,
            coordinator=StepProtection(),
            intent_store=FakeIntentStore(),
            safe_mode=volatile,
        )


async def test_the_build_refuses_a_tick_interval_not_below_max_unprotected() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    base = make_test_limits()
    limits = dataclasses.replace(base, reconcile_tick_interval_ms=base.max_unprotected_ms)

    with pytest.raises(ExecutionLimitsInvalid):
        compose(
            adapter=fake,
            coordinator=StepProtection(),
            intent_store=FakeIntentStore(),
            limits=limits,
        )


async def test_the_build_names_an_unset_limit() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    limits = make_test_limits(stale_feed_max_user_data_silence_ms=None)

    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        compose(
            adapter=fake,
            coordinator=StepProtection(),
            intent_store=FakeIntentStore(),
            limits=limits,
        )

    assert "stale_feed.max_user_data_silence_ms" in caught.value.keys


async def test_an_overlapping_tick_returns_skipped_overlap() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    parts = compose(adapter=fake, coordinator=StepProtection(), intent_store=FakeIntentStore())
    fake.hold("snapshot_open_normal_orders")

    first = asyncio.ensure_future(reconcile_tick_once(parts.bundle, NOW))
    await yield_to_loop()
    assert fake.held() == ["snapshot_open_normal_orders"]
    second = await reconcile_tick_once(parts.bundle, NOW)
    fake.release("snapshot_open_normal_orders")
    finished = await first

    assert second.outcome == TICK_SKIPPED_OVERLAP
    assert finished.outcome == TICK_COMPARED


def test_the_module_builds_the_sweeper_without_a_pinned_time() -> None:
    source = (ROOT / "src" / "live" / "reconcile.py").read_text(encoding="utf-8")
    assert "OrphanSweeper(adapter=adapter, journal=journal)" in source
    assert "now_utc=" not in source.split("OrphanSweeper(", 1)[1].split(")", 1)[0]


# --------------------------------------------------------------------------- #
# Task 2: lot filters, entry good-till, risk reducer, feed clock skew.
# --------------------------------------------------------------------------- #


async def test_lot_filters_read_live_first_then_stored_then_the_plan_snapshot() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    fake.set_lot_filters(SYMBOL, lot_filters_for_tests())
    store = InMemoryLotFilterStore()
    snapshot = complete_constraint_snapshot()
    source = build_lot_filters(
        adapter=fake,
        store=store,
        snapshot_store=FakeSnapshotStore({snapshot.trade_plan_id: snapshot}),
        limits=make_test_limits(),
        clock=lambda: NOW,
    )

    live = await source.for_emergency_close(SYMBOL, trade_plan_id=snapshot.trade_plan_id)
    assert live.filters_stale is False
    assert store.rows[SYMBOL][1] == NOW, "a good live read is stored"

    fake.fail_next("symbol_lot_filters", RuntimeError("down"))
    stored = await source.for_emergency_close(SYMBOL, trade_plan_id=snapshot.trade_plan_id)
    assert stored.filters_stale is True
    assert stored.fetched_at_utc == NOW

    store.rows.clear()
    fake.fail_next("symbol_lot_filters", RuntimeError("down"))
    from_plan = await source.for_emergency_close(SYMBOL, trade_plan_id=snapshot.trade_plan_id)
    assert from_plan.filters_stale is True
    assert from_plan.fetched_at_utc == snapshot.constraints_observed_at_utc

    fake.fail_next("symbol_lot_filters", RuntimeError("down"))
    with pytest.raises(Exception, match="unavailable"):
        await source.for_emergency_close(SYMBOL, trade_plan_id="unknown-plan")


async def test_a_new_entry_never_gets_a_stored_row() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    fake.set_lot_filters(SYMBOL, lot_filters_for_tests())
    store = InMemoryLotFilterStore()
    source = build_lot_filters(
        adapter=fake,
        store=store,
        snapshot_store=FakeSnapshotStore(),
        limits=make_test_limits(),
        clock=lambda: NOW,
    )
    await source.for_entry(SYMBOL)
    fake.fail_next("symbol_lot_filters", RuntimeError("down"))

    with pytest.raises(Exception, match="unavailable"):
        await source.for_entry(SYMBOL)


async def test_an_unset_refresh_interval_refuses_the_lot_filter_build() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    limits = make_test_limits(reconcile_lot_filter_refresh_interval_ms=None)

    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        build_lot_filters(
            adapter=fake,
            store=InMemoryLotFilterStore(),
            snapshot_store=FakeSnapshotStore(),
            limits=limits,
            clock=lambda: NOW,
        )

    assert caught.value.keys == ("reconcile.lot_filter_refresh_interval_ms",)


async def test_a_closer_built_with_the_source_closes_with_the_fresh_filters() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    fake.set_lot_filters(SYMBOL, lot_filters_for_tests())
    fake.set_mark_price(SYMBOL, D("60000"), NOW)
    fake.positions[SYMBOL] = D("0.010")
    source = build_lot_filters(
        adapter=fake,
        store=InMemoryLotFilterStore(),
        snapshot_store=FakeSnapshotStore(),
        limits=make_test_limits(),
        clock=lambda: NOW,
    )
    journal = RecordingJournal()
    closer = MarketEmergencyCloser(
        adapter=fake,  # type: ignore[arg-type]
        journal=journal,
        safe_mode_controller=SafeModeController(adapter=fake, journal=journal),
        alert_sink=SimpleNamespace(critical=lambda **_: None),  # type: ignore[arg-type]
        clock=lambda: NOW,
        limits=make_test_limits(),
        lot_filters=source,
    )

    closed = await closer.close_position(entry=resting_entry_for_tests(), reason="TEST")

    assert closed is True
    assert fake.calls_to("symbol_lot_filters") != []
    assert fake.positions[SYMBOL] == D("0")


def _stored_plan() -> Any:
    return make_shadow_plan(make_shadow_signal())


def test_entry_good_till_is_the_stored_plan_expiry_floored_to_the_second() -> None:
    plan = _stored_plan()
    record = make_intent_record(H1, OrderRole.ENTRY.value)
    store = FakePlanStore({record.trade_plan_id: plan})
    good_till = entry_good_till_from_store(store)

    assert good_till(record) == plan.expiry_utc.replace(microsecond=0)
    assert good_till(make_intent_record("2" * 64, OrderRole.ENTRY.value)) is None


def test_entry_good_till_by_plan_hash_learns_the_plan_id_from_the_unresolved_entry() -> None:
    plan = _stored_plan()
    record = make_intent_record(H1, OrderRole.ENTRY.value)
    good_till = entry_good_till_by_plan_hash(
        FakePlanStore({record.trade_plan_id: plan}), FakeIntentStore([record])
    )

    assert good_till(H1) == plan.expiry_utc.replace(microsecond=0)
    assert good_till("2" * 64) is None


def test_entry_good_till_by_plan_hash_is_none_when_the_plan_is_not_stored() -> None:
    record = make_intent_record(H1, OrderRole.ENTRY.value)
    good_till = entry_good_till_by_plan_hash(FakePlanStore({}), FakeIntentStore([record]))

    assert good_till(H1) is None


async def test_the_loop_alerts_a_stale_resting_entry_from_the_stored_plan_expiry() -> None:
    plan = _stored_plan()
    record = make_intent_record(H1, OrderRole.ENTRY.value)
    gtd = plan.expiry_utc.replace(microsecond=0)
    grace = make_test_limits().reconcile_entry_stale_grace_ms
    assert grace is not None
    now = gtd + timedelta(milliseconds=grace) + timedelta(seconds=1)
    adapter = FilterAdapter(normal_orders=(make_open_order(ENTRY_ID, SYMBOL),))
    awaiting = make_plan_protection(
        H1, state="AWAITING_FILL", first_fill=False, stop_confirmed=False, entry_terminal=False
    )
    parts = compose(
        adapter=adapter,
        coordinator=StepProtection((awaiting,)),
        intent_store=FakeIntentStore([record]),
        plan_store=FakePlanStore({record.trade_plan_id: plan}),
        now=now,
    )

    report = await reconcile_tick_once(parts.bundle, now)

    assert report.stale_entries == (ENTRY_ID,)
    assert [a.event for a in parts.alerts.queue] == ["STALE_ENTRY_ORDER"]
    assert parts.safe_mode.in_safe_mode is False, "alert only"


async def test_the_risk_reducer_runs_the_coordinator_step_when_a_pending_action_is_open() -> None:
    adapter = FilterAdapter()
    coordinator = StepProtection()
    pending = InMemoryPendingActionStore()
    pending.record_blocked(
        plan_hash=H1,
        trade_plan_id="plan-1",
        approval_id="approval-1",
        symbol=SYMBOL,
        kind=PendingKind.CLOSE_NOT_SENT,
        gate_reason="RATE_LIMIT_429",
        retry_after_until_utc=None,
        now_utc=NOW,
    )
    parts = compose(
        adapter=adapter,
        coordinator=coordinator,
        intent_store=FakeIntentStore(),
        pending=pending,
    )

    report = await reconcile_tick_once(parts.bundle, NOW)

    assert coordinator.steps == 1
    assert "risk_reducing" in report.order
    assert report.order.index("risk_reducing") < report.order.index("reads")
    assert "background" not in report.order, "a standing pending row skips the background phase"


async def test_without_open_pending_actions_the_reducer_is_not_awaited() -> None:
    coordinator = StepProtection()
    parts = compose(
        adapter=FilterAdapter(), coordinator=coordinator, intent_store=FakeIntentStore()
    )

    await reconcile_tick_once(parts.bundle, NOW)

    assert coordinator.steps == 0


async def test_make_risk_reducer_steps_the_coordinator_once_per_call() -> None:
    coordinator = StepProtection()
    reducer = make_risk_reducer(coordinator, object())

    await reducer()
    await reducer()

    assert coordinator.steps == 2


async def test_the_loop_carries_the_feed_clock_skew_of_the_ratified_drift() -> None:
    drift = make_binance_limits().drift
    skew = clock_skew_from_drift(drift)
    tracked = make_plan_protection(
        H1, state="AWAITING_FILL", first_fill=False, stop_confirmed=False, entry_terminal=False
    )

    async def tick_with_feed_ahead_by(ahead: timedelta) -> Any:
        parts = compose(
            adapter=FilterAdapter(normal_orders=(make_open_order(ENTRY_ID, SYMBOL),)),
            coordinator=StepProtection((tracked,)),
            intent_store=FakeIntentStore(),
            feeds=FakeFeedSource(FeedReading({SYMBOL: NOW + ahead}, NOW)),
        )
        return await reconcile_tick_once(parts.bundle, NOW)

    inside = await tick_with_feed_ahead_by(skew - timedelta(milliseconds=1))
    outside = await tick_with_feed_ahead_by(skew + timedelta(seconds=1))

    assert inside.stale_symbols == ()
    assert outside.stale_symbols == (SYMBOL,)
