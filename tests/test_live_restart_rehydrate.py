"""Restart rehydrate over fakes (plan 24-26; D-09, G4-029, D080, P-4).

Run 1 is the live rig (real desk, confirm flow, service, manager, coordinator over the
Binance-semantics fake and the in-memory stores). A restart is modelled by NEW objects over the
same stores: a new `SafeModeController.load`, coordinator (`restore_required=True`), closer,
client-id index, router and confirm flow. The glue under test is `restored_plans_builder`,
`close_attempts_reader` and `rebuild_client_id_index`, driven by the real `run_startup_recovery`.
The PostgreSQL variant is plan 24-28.

TEST_ONLY: the snapshot, the TP1 fraction and the TTL are the rig's made-up values.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any

import pytest
from src.adapters.binance_userdata_events import parse_stream_message
from src.adapters.binance_userdata_supervisor import TrustedEvent
from src.adapters.telegram_callbacks import on_callback
from src.approval.confirm_core import DEMO_CONFIRM_PROFILE
from src.domain.enums import (
    ApprovalResult,
    ExecutionIntentStatus,
    OrderRole,
)
from src.domain.journal import JournalEvent
from src.execution.confirm_recheck import make_confirm_recheck, prefetched_provider
from src.execution.constraint_snapshot import PlanConstraintSnapshot
from src.execution.emergency_close import (
    _CORRELATION_PREFIX as CLOSE_PREFIX,
)
from src.execution.emergency_close import (
    EVENT_EMERGENCY_CLOSE,
    MarketEmergencyCloser,
)
from src.execution.intent_store import IntentRecord
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.pre_placement import check_remaining_validity
from src.execution.protection import ProtectionCoordinator, ProtectionState
from src.live import startup
from src.live.order_index import ClientIdIndex
from src.live.scheduled_cancel import cancel_unrestored_entries
from src.live.startup import (
    RecoveryPorts,
    close_attempts_reader,
    protection_correlation,
    rebuild_client_id_index,
    resting_entry_from_intent,
    restored_plans_builder,
)
from src.live.wiring import build_execution_path
from src.reconcile.safe_mode import SafeModeController
from src.reconcile.startup import (
    _PROTECTION_CORRELATION_PREFIX as PROTECTION_PREFIX,
)
from src.reconcile.startup import (
    PartialRestore,
    StartupReport,
    UnrestorableEntry,
    run_startup_recovery,
)

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    T0,
    USER_ID,
    make_callback_update,
)
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.live_rig import (
    TEST_ONLY_SYMBOL,
    LiveRig,
    forbid_real_sleep,
    make_live_rig,
)
from tests.support.protection_doubles import RecordingAlerts
from tests.support.reconcile_doubles import InMemorySafeModeStore
from tests.support.stream_sinks import RecordingSinks, make_router
from tests.test_live_start_sequence import Harness

D = Decimal
TEST_ONLY_TP1_FRACTION = D("0.5")
TEST_ONLY_SNAPSHOT_TTL = timedelta(seconds=3600)
SM_REASON = "TEST_ONLY_OPERATOR_DRILL"


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


# --------------------------------------------------------------------------- #
# Run 2 builder.
# --------------------------------------------------------------------------- #


class MemoryRestoreReader:
    """The `RestoreIntentReader` over the in-memory intent store (test-side private read).

    The production store has neither method yet (the PostgreSQL reads are a hand-off to plan
    24-27 or 24-28): `list_unresolved_intents` omits ACKED rows and the store has no `get_intent`.
    """

    def __init__(self, store: InMemoryExecutionIntentStore) -> None:
        self._store = store

    def restorable_entries(self) -> Sequence[IntentRecord]:
        rows = self._store._rows.values()
        wanted = {
            ExecutionIntentStatus.SENT,
            ExecutionIntentStatus.UNKNOWN,
            ExecutionIntentStatus.ACKED,
        }
        return tuple(
            sorted(
                (r for r in rows if r.role == OrderRole.ENTRY.value and r.intent_status in wanted),
                key=lambda r: (r.intended_at_utc, r.approval_id),
            )
        )

    def get_intent(self, *, approval_id: str, role: str) -> IntentRecord | None:
        return self._store.get_intent(approval_id=approval_id, role=role)


class Restart:
    """The objects of the second process over the first process' stores."""

    def __init__(
        self,
        rig: LiveRig,
        snapshot: PlanConstraintSnapshot,
        store: Any,
        *,
        on_enter: Callable[[str, datetime], None] | None = None,
    ) -> None:
        self.rig = rig
        self.snapshot = snapshot
        self.alerts = RecordingAlerts()
        self.index = ClientIdIndex()
        self.safe_mode = SafeModeController.load(
            adapter=rig.fake,  # type: ignore[arg-type]
            journal=rig.journal,
            state_store=store,
            now_utc=rig.clock.now(),
            on_enter=on_enter,
        )
        self.closer = MarketEmergencyCloser(
            adapter=rig.fake,  # type: ignore[arg-type]
            journal=rig.journal,
            safe_mode_controller=self.safe_mode,
            alert_sink=self.alerts,
            clock=rig.clock,
            limits=rig.limits,
        )
        self.coordinator = ProtectionCoordinator(
            adapter=rig.fake,  # type: ignore[arg-type]
            intent_store=rig.intents,
            journal=rig.journal,
            safe_mode_controller=self.safe_mode,
            alert_sink=self.alerts,
            emergency_closer=self.closer,
            limits=rig.limits,
            clock=rig.clock,
            restore_required=True,
        )
        self.reader = self._reader_for(rig)
        self.builder = restored_plans_builder(
            intents=self.reader,
            plan_for=rig.stores.plans.get,
            snapshot_for=lambda trade_plan_id: snapshot,
            transition_events_for=self._events_of,
            index=self.index,
            tp1_quantity_fraction=TEST_ONLY_TP1_FRACTION,
            snapshot_ttl=TEST_ONLY_SNAPSHOT_TTL,
        )
        self.reader_of_closes = close_attempts_reader(
            plan_hashes=lambda: [e.plan_hash for e in self.reader.restorable_entries()],
            events_for_correlation=self._events_of,
        )

    def _reader_for(self, rig: LiveRig) -> Any:
        """The restore reader; the PostgreSQL variant (plan 24-28) overrides it."""
        return MemoryRestoreReader(rig.intents)

    def _events_of(self, correlation: str) -> list[JournalEvent]:
        """The journal rows of a correlation id, or of a plan hash (protection rows)."""
        wanted = {correlation, protection_correlation(correlation)}
        return [e for e in self.rig.journal.events.values() if e.correlation_id in wanted]

    def recovery_ports(self) -> RecoveryPorts:
        return RecoveryPorts(
            pending_store=_NoPending(),  # type: ignore[arg-type]
            coordinator=self.coordinator,
            closer=self.closer,
            restored_plans_builder=self.builder,
            close_attempts_reader=self.reader_of_closes,
            intent_store=self.rig.intents,
            probe_adapter=self.rig.fake,  # type: ignore[arg-type]
            journal=self.rig.journal,
            spill=None,
        )

    async def recover(self) -> StartupReport:
        parts = self.recovery_ports()
        return await run_startup_recovery(
            safe_mode_load=lambda: self.safe_mode,
            pending_store=parts.pending_store,
            coordinator=parts.coordinator,
            closer=parts.closer,
            restored_plans_builder=parts.restored_plans_builder,
            close_attempts_reader=parts.close_attempts_reader,
            intent_store=parts.intent_store,
            probe_adapter=parts.probe_adapter,
            journal=parts.journal,
            spill=None,
            now_utc=self.rig.clock.now(),
        )

    def route(self, frame: dict[str, Any]) -> Any:
        sinks = RecordingSinks()
        router = make_router(
            lookup=self.index,  # type: ignore[arg-type]
            journal=self.rig.journal,
            sinks=sinks,
            clock=self.rig.clock,
            overrides={"fill_sink": self.coordinator.fill_sink},
        )
        received = self.rig.clock.now()
        return router.route(
            TrustedEvent(
                outcome=parse_stream_message(frame, observed_at_utc=received),
                received_at_utc=received,
                connection_epoch=1,
                after_gap=False,
            )
        )


class _NoPending:
    def list_open(self) -> list[Any]:
        return []


async def _restart(
    rig: LiveRig,
    *,
    crash_in_safe_mode: str | None = SM_REASON,
    on_enter: Callable[[str, datetime], None] | None = None,
) -> Restart:
    """Persist run 1's SAFE_MODE state (the controller saves it) and build the new process."""
    now = rig.clock.now()
    if crash_in_safe_mode is not None:
        rig.safe_mode.enter_safe_mode(reason=crash_in_safe_mode, now_utc=now)
    store = InMemorySafeModeStore()
    store.save(rig.safe_mode.state_snapshot(), now_utc=now)
    approval = rig.approve_row()
    placement = await rig.inputs.for_plan(approval, rig.plan, now)
    snapshot = placement.live_context.plan_constraint_snapshot
    return Restart(rig, snapshot, store, on_enter=on_enter)


async def _run_one_resting_entry() -> LiveRig:
    rig = await make_live_rig()
    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    assert len(rig.fake.calls_to("place_entry")) == 1
    return rig


# --------------------------------------------------------------------------- #
# SAFE_MODE, resting entries, the registry and the index.
# --------------------------------------------------------------------------- #


async def test_a_restart_rebuilds_safe_mode_the_resting_entry_and_its_index_entry() -> None:
    rig = await _run_one_resting_entry()
    original = rig.wiring.coordinator._tracked[rig.plan.plan_hash].entry  # run 1's record
    restart = await _restart(rig)

    assert restart.safe_mode.in_safe_mode
    assert restart.safe_mode.entered_reason == SM_REASON, "loaded from the store, not defaulted"
    assert not restart.coordinator.restore_complete
    assert restart.coordinator.blocks_new_entries(), "no entry opens before the rebuild"

    report = await restart.recover()

    assert report.failed_steps == () and report.plans_restored == 1
    assert restart.coordinator.restore_complete
    view = restart.coordinator.protection_of(rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.AWAITING_FILL
    rebuilt = restart.coordinator._tracked[rig.plan.plan_hash].entry
    for name in (
        "approval_id",
        "trade_plan_id",
        "plan_hash",
        "symbol",
        "side",
        "entry_side",
        "exit_side",
        "entry_client_order_id",
        "entry_quantity",
        "sl_trigger_price",
        "tp1_trigger_price",
        "tp2_trigger_price",
        "tp1_quantity_fraction",
        "working_type",
        "position_mode",
        "snapshot_ttl",
        "entry_state_unknown",
        "entry_good_till_utc",
    ):
        assert getattr(rebuilt, name) == getattr(original, name), name
    known = restart.index.known_order(rig.entry_id)
    assert known is not None and known.symbol == TEST_ONLY_SYMBOL
    assert len(rig.fake.calls_to("place_entry")) == 1, "a placement is never re-sent"
    assert rig.fake.calls_to("place_algo_protective") == []


async def test_a_fill_for_the_rebuilt_entry_reaches_the_coordinator_as_a_known_order() -> None:
    rig = await _run_one_resting_entry()
    restart = await _restart(rig)
    await restart.recover()

    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    routed = restart.route(rig.trade_frame())

    assert routed.fills == 1
    assert [e for e in rig.journal.calls if "UNKNOWN" in e.event_type] == [], (
        "known order, not UNKNOWN_STREAM_ORDER"
    )
    await restart.coordinator.step()
    await rig.clock.advance(1)
    await restart.coordinator.step()
    view = restart.coordinator.protection_of(rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.PROTECTED
    (stop,) = rig.fake.calls_to("place_algo_protective")
    assert stop["kwargs"]["client_algo_id"] == derive_algo_client_id(
        plan_hash=rig.plan.plan_hash, role=OrderRole.STOP_LOSS.value
    )
    assert len(rig.fake.calls_to("place_entry")) == 1


async def test_a_protected_plan_comes_back_protected_and_its_stop_is_not_placed_again() -> None:
    rig = await _run_one_resting_entry()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    rig.route(rig.trade_frame())
    await rig.wiring.coordinator.step()
    await rig.clock.advance(1)
    await rig.wiring.coordinator.step()
    protection = rig.wiring.coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.PROTECTED
    stops_before = len(rig.fake.calls_to("place_algo_protective"))

    restart = await _restart(rig)
    report = await restart.recover()

    assert report.plans_restored == 1
    view = restart.coordinator.protection_of(rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.PROTECTED
    assert view.stop_confirmed_at_utc is not None, "no clock restarted"
    stop_id = derive_algo_client_id(plan_hash=rig.plan.plan_hash, role=OrderRole.STOP_LOSS.value)
    assert restart.index.known_algo(stop_id) is not None, "the protective id is known again"
    await restart.coordinator.step()
    assert len(rig.fake.calls_to("place_algo_protective")) == stops_before, "no re-placed stop"
    assert len(rig.fake.calls_to("place_entry")) == 1


# --------------------------------------------------------------------------- #
# UNKNOWN entries (D080).
# --------------------------------------------------------------------------- #


async def test_an_entry_sent_with_an_unknown_result_stays_unknown_with_safe_mode() -> None:
    rig = await make_live_rig()
    rig.fake.fail_next("place_entry", RuntimeError("timeout"))  # ambiguous; the probe finds nothing
    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    entry = rig.intents.get_entry(approval_id=rig.approve_row().approval_id)
    assert entry is not None and entry.intent_status is ExecutionIntentStatus.UNKNOWN
    assert rig.safe_mode.in_safe_mode and rig.safe_mode.entered_reason == "ENTRY_STATE_UNKNOWN"

    restart = await _restart(rig, crash_in_safe_mode=None)
    report = await restart.recover()

    assert restart.safe_mode.in_safe_mode
    assert restart.safe_mode.entered_reason in {
        "ENTRY_STATE_UNKNOWN",
        "UNRESOLVED_EXECUTION_INTENT",  # recovery re-asserts it while the intent is unresolved
    }
    after = rig.intents.get_entry(approval_id=rig.approve_row().approval_id)
    assert after is not None
    assert after.intent_status is ExecutionIntentStatus.UNKNOWN, (
        "a probe 'not found' never closes it as REJECTED (D080)"
    )
    assert after.resolution_reason_code is None
    assert report.intents is not None
    view = restart.coordinator.protection_of(rig.plan.plan_hash)
    assert view is not None, "the entry is tracked as a possible live order"
    assert restart.coordinator._tracked[rig.plan.plan_hash].entry.entry_state_unknown
    assert len(rig.fake.calls_to("place_entry")) == 1, "never re-sent"
    assert restart.index.known_order(rig.entry_id) is not None


# --------------------------------------------------------------------------- #
# Confirms.
# --------------------------------------------------------------------------- #


async def test_outstanding_confirms_expire_with_runtime_restart_and_a_press_places_nothing() -> (
    None
):
    rig = await make_live_rig()
    handle = await rig.issue_and_send()
    assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
    assert rig.approve_row().result is ApprovalResult.APPROVED, "an APPROVED, unconfirmed plan"

    # Run 2: a fresh confirm flow (a fresh book) over the same stores.
    wiring2 = build_execution_path(
        loop=rig.wiring.service._loop,
        clock=rig.clock,
        adapter=rig.fake,  # type: ignore[arg-type]
        stores=rig.stores,
        intent_store=rig.intents,
        journal=rig.journal,
        safe_mode_controller=rig.safe_mode,
        enablement=rig.enablement,
        alert_sink=RecordingAlerts(),
        limits=rig.limits,
        inputs=rig.inputs,
        profile=DEMO_CONFIRM_PROFILE,
        authorized_chat_id=CHAT_ID,
        bot=rig.bot,
        sleep=rig.sleep,
        mark_price=lambda symbol: D("50050"),
        validity_rule=partial(
            check_remaining_validity,
            min_remaining_validity_seconds=rig.limits.min_remaining_validity_seconds,
            gtd_clock_margin=timedelta(seconds=2),
        ),
        recheck=make_confirm_recheck(prefetched_provider(rig.holder)),
        prefetch=None,
        token_for=lambda approval_id: None,
    )
    await rig.clock.advance(30)
    expired = wiring2.confirm_flow.expire_on_restart(rig.clock.now())

    assert expired == [rig.approve_row().approval_id]
    (event,) = rig.stores.journal_of_type("DEMO_CONFIRM_EXPIRED")
    assert json.loads(event.payload_json)["reason"] == "RUNTIME_RESTART"
    assert rig.approve_row().result is ApprovalResult.APPROVED, "still approved until its expiry"
    assert wiring2.confirm_flow.expire_on_restart(rig.clock.now()) == [], "idempotent"

    update = make_callback_update(
        data=f"CNF:{handle.short_id}",
        chat_id=CHAT_ID,
        query_id="q-cnf-after-restart",
        message_chat_id=CHAT_ID,
        from_user_id=USER_ID,
        message_id=1,
        chat_type="private",
    )
    result = await on_callback(
        update,
        None,  # type: ignore[arg-type]
        **wiring2.confirm_flow.callback_kwargs(
            authorized_chat_id=CHAT_ID,
            authorized_user_ids=AUTHORIZED_USER_IDS,
            error_journal=rig.stores.record_journal,
        ),
    )
    assert not result.ok, "an old card needs a fresh CONFIRM"
    await wiring2.service.drain()
    assert rig.fake.calls_to("place_entry") == []


# --------------------------------------------------------------------------- #
# Through the sequence: everything is rebuilt before the stream and the bot start.
# --------------------------------------------------------------------------- #


async def test_the_sequence_rebuilds_registry_and_index_before_the_stream_and_the_bot(
    tmp_path: Any,
) -> None:
    rig = await _run_one_resting_entry()
    restart = await _restart(rig)
    harness = Harness(tmp=tmp_path)
    harness.install()
    seen: list[tuple[str, bool, bool]] = []

    def at(name: str) -> Callable[[], None]:
        def check() -> None:
            seen.append(
                (
                    name,
                    restart.index.known_order(rig.entry_id) is not None,
                    restart.coordinator.restore_complete,
                )
            )

        return check

    ports = dataclasses.replace(
        harness.ports(),
        load_safe_mode=lambda: restart.safe_mode,
        recovery=restart.recovery_ports(),
        start_stream=at("stream"),
        start_bot=at("bot"),
        start_scheduler=at("scheduler"),
    )
    outcome = await startup.run_start_sequence(ports, now_utc=T0)

    assert outcome.admitted and outcome.recovery is not None
    assert outcome.recovery.plans_restored == 1
    assert seen == [("stream", True, True), ("bot", True, True), ("scheduler", True, True)]
    assert outcome.in_safe_mode and not outcome.enabled, "the persisted SAFE_MODE blocks the enable"
    assert restart.safe_mode.entered_reason == SM_REASON


# --------------------------------------------------------------------------- #
# The glue on its own.
# --------------------------------------------------------------------------- #


def test_the_correlation_helpers_match_their_producers() -> None:
    assert startup.CLOSE_CORRELATION_PREFIX == CLOSE_PREFIX
    assert startup.PROTECTION_CORRELATION_PREFIX == PROTECTION_PREFIX
    assert protection_correlation("h") == f"{PROTECTION_PREFIX}h"
    assert startup.close_correlation("h") == f"{CLOSE_PREFIX}h"


def _close_event(plan_hash: str, correlation: str, n: int) -> JournalEvent:
    return JournalEvent(
        journal_event_id=f"close_{n}",
        occurred_at_utc=T0,
        event_type=EVENT_EMERGENCY_CLOSE,
        entity_type="Plan",
        entity_id=plan_hash,
        correlation_id=correlation,
        payload_json="{}",
    )


def test_close_attempts_reader_groups_by_plan_and_drops_foreign_correlations() -> None:
    mine = _close_event("p1", f"{CLOSE_PREFIX}p1", 1)
    foreign = _close_event("p2", f"{CLOSE_PREFIX}p2", 2)
    rows = {f"{CLOSE_PREFIX}p1": [mine, foreign], f"{CLOSE_PREFIX}p2": []}
    reader = close_attempts_reader(
        plan_hashes=lambda: ["p1", "p2"], events_for_correlation=lambda c: rows.get(c, [])
    )
    assert dict(reader()) == {"p1": [mine]}


async def test_a_restorable_entry_without_its_plan_or_snapshot_is_isolated() -> None:
    rig = await _run_one_resting_entry()
    restart = await _restart(rig, crash_in_safe_mode=None)
    builder = restored_plans_builder(
        intents=restart.reader,
        plan_for=lambda trade_plan_id: None,
        snapshot_for=lambda trade_plan_id: restart.snapshot,
        transition_events_for=restart._events_of,
        index=ClientIdIndex(),
        tp1_quantity_fraction=TEST_ONLY_TP1_FRACTION,
        snapshot_ttl=TEST_ONLY_SNAPSHOT_TTL,
    )
    with pytest.raises(PartialRestore) as raised:
        builder(lambda plan_hash: ())
    assert raised.value.plans == () and raised.value.unrestorable == 1

    restart.builder = builder
    report = await restart.recover()
    assert "COORDINATOR_RESTORED" in report.failed_steps
    assert "RESTORE_INCONSISTENT" in report.safe_mode_reasons
    assert "DB_FAILURE" not in report.safe_mode_reasons
    assert report.plans_restored == 0 and report.plans_unrestorable == 1
    assert restart.safe_mode.in_safe_mode
    assert restart.coordinator.restore_complete, "the (empty) restore ran"
    assert restart.safe_mode.guard_new_entries(None).is_no_trade, "SAFE_MODE blocks new entries"


class _TwoRowReader:
    """The real restore reader plus one extra (corrupt) restorable ENTRY row of its own."""

    def __init__(self, inner: Any, extra: IntentRecord) -> None:
        self._inner = inner
        self._extra = extra

    def restorable_entries(self) -> Sequence[IntentRecord]:
        return (*self._inner.restorable_entries(), self._extra)

    def get_intent(self, *, approval_id: str, role: str) -> IntentRecord | None:
        return self._inner.get_intent(approval_id=approval_id, role=role)


def _extra_row(real: IntentRecord, **overrides: Any) -> IntentRecord:
    """A second restorable ENTRY row: distinct approval id, a later intended time."""
    fields: dict[str, Any] = {
        "approval_id": "TEST_ONLY_second_approval",
        "trade_plan_id": "TEST_ONLY_second_plan",
        "intended_at_utc": real.intended_at_utc + timedelta(seconds=5),
        **overrides,
    }
    return dataclasses.replace(real, **fields)


async def _two_rows_one_corrupt(
    *, plan_for_extra_is_none: bool, on_enter: Callable[[str, datetime], None] | None = None
) -> tuple[LiveRig, Restart, Callable[[Any], Sequence[Any]], ClientIdIndex]:
    rig = await _run_one_resting_entry()
    restart = await _restart(rig, crash_in_safe_mode=None, on_enter=on_enter)
    real = rig.intents.get_entry(approval_id=rig.approve_row().approval_id)
    assert real is not None
    if plan_for_extra_is_none:
        extra = _extra_row(real)  # its trade_plan_id has no persisted plan
        corrupt_plan_id = extra.trade_plan_id
    else:  # the healthy plan, but a client id that plan does not derive: the rebuild refuses it
        extra = _extra_row(real, trade_plan_id=real.trade_plan_id, client_order_id="not-the-id")
        corrupt_plan_id = "TEST_ONLY_no_such_plan"
    index = ClientIdIndex()

    def plan_for(trade_plan_id: str) -> Any:
        return None if trade_plan_id == corrupt_plan_id else rig.stores.plans.get(trade_plan_id)

    builder = restored_plans_builder(
        intents=_TwoRowReader(restart.reader, extra),
        plan_for=plan_for,
        snapshot_for=lambda trade_plan_id: restart.snapshot,
        transition_events_for=restart._events_of,
        index=index,
        tp1_quantity_fraction=TEST_ONLY_TP1_FRACTION,
        snapshot_ttl=TEST_ONLY_SNAPSHOT_TTL,
    )
    restart.builder = builder
    return rig, restart, builder, index


@pytest.mark.parametrize("plan_for_extra_is_none", [True, False], ids=["no-plan", "row-refused"])
async def test_one_corrupt_row_does_not_stop_the_healthy_plan_from_being_restored(
    plan_for_extra_is_none: bool,
) -> None:
    entered: list[str] = []
    rig, restart, builder, index = await _two_rows_one_corrupt(
        plan_for_extra_is_none=plan_for_extra_is_none,
        on_enter=lambda reason, now_utc: entered.append(reason),
    )
    with pytest.raises(PartialRestore) as raised:
        builder(lambda plan_hash: ())
    assert [p.entry.plan_hash for p in raised.value.plans] == [rig.plan.plan_hash]
    assert raised.value.unrestorable == 1

    report = await restart.recover()

    assert restart.coordinator.protection_of(rig.plan.plan_hash) is not None
    assert index.known_order(rig.entry_id) is not None, "the healthy client ids are indexed"
    assert report.plans_restored == 1 and report.plans_unrestorable == 1
    assert "COORDINATOR_RESTORED" in report.failed_steps
    assert "RESTORE_INCONSISTENT" in report.safe_mode_reasons
    assert restart.safe_mode.in_safe_mode
    assert "RESTORE_INCONSISTENT" in entered, "the alert hook saw the entry"
    assert restart.coordinator.restore_complete
    assert restart.safe_mode.guard_new_entries(None).is_no_trade, "SAFE_MODE blocks new entries"


async def test_a_store_outage_while_building_still_fails_the_whole_build() -> None:
    rig = await _run_one_resting_entry()
    restart = await _restart(rig, crash_in_safe_mode=None)

    def outage(correlation: str) -> list[JournalEvent]:
        raise OSError("journal is down (test)")

    builder = restored_plans_builder(
        intents=restart.reader,
        plan_for=rig.stores.plans.get,
        snapshot_for=lambda trade_plan_id: restart.snapshot,
        transition_events_for=outage,
        index=ClientIdIndex(),
        tp1_quantity_fraction=TEST_ONLY_TP1_FRACTION,
        snapshot_ttl=TEST_ONLY_SNAPSHOT_TTL,
    )
    with pytest.raises(OSError):
        builder(lambda plan_hash: ())

    restart.builder = builder
    report = await restart.recover()
    assert "COORDINATOR_RESTORED" in report.failed_steps
    assert "DB_FAILURE" in report.safe_mode_reasons
    assert report.plans_unrestorable == 0
    assert not restart.coordinator.restore_complete, "entries stay blocked"
    assert restart.coordinator.blocks_new_entries()


async def test_an_entry_that_was_never_sent_is_not_restored() -> None:
    rig = await _run_one_resting_entry()
    entry = rig.intents.get_entry(approval_id=rig.approve_row().approval_id)
    assert entry is not None
    never_sent = dataclasses.replace(entry, intent_status=ExecutionIntentStatus.INTENDED)
    snapshot = (
        await rig.inputs.for_plan(rig.approve_row(), rig.plan, rig.clock.now())
    ).live_context
    with pytest.raises(ValueError, match="never sent"):
        resting_entry_from_intent(
            entry=never_sent,
            plan=rig.plan,
            snapshot=snapshot.plan_constraint_snapshot,
            tp1_quantity_fraction=TEST_ONLY_TP1_FRACTION,
            snapshot_ttl=TEST_ONLY_SNAPSHOT_TTL,
        )


async def test_a_row_with_a_foreign_client_id_is_refused() -> None:
    rig = await _run_one_resting_entry()
    entry = rig.intents.get_entry(approval_id=rig.approve_row().approval_id)
    assert entry is not None
    snapshot = (
        await rig.inputs.for_plan(rig.approve_row(), rig.plan, rig.clock.now())
    ).live_context
    with pytest.raises(ValueError, match="deterministic client id"):
        resting_entry_from_intent(
            entry=dataclasses.replace(entry, client_order_id="not-the-derived-id"),
            plan=rig.plan,
            snapshot=snapshot.plan_constraint_snapshot,
            tp1_quantity_fraction=TEST_ONLY_TP1_FRACTION,
            snapshot_ttl=TEST_ONLY_SNAPSHOT_TTL,
        )


async def test_rebuild_client_id_index_registers_entry_and_protective_ids_once() -> None:
    rig = await _run_one_resting_entry()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    rig.route(rig.trade_frame())
    await rig.wiring.coordinator.step()
    restart = await _restart(rig)
    plans = restart.builder(lambda plan_hash: ())
    again = ClientIdIndex()
    first = rebuild_client_id_index(again, plans, restart.reader)
    second = rebuild_client_id_index(again, plans, restart.reader)
    assert first == second >= 2, "entry id and at least the stop id; idempotent"
    assert again.known_order(rig.entry_id) is not None


def test_the_restart_module_has_no_clock_and_no_placement() -> None:
    from pathlib import Path

    source = Path("src/live/startup.py").read_text(encoding="utf-8")
    for forbidden in ("place_entry", "place_algo_protective", "place_market_close", "create_all"):
        assert forbidden not in source
    assert "datetime.now" not in source and "time.time" not in source


# --------------------------------------------------------------------------- #
# Quick 261114-mp1 (D110): the resting entry of an unrestorable plan is cancelled once.
# --------------------------------------------------------------------------- #

# A plan hash whose first 32 hex characters differ from the rig's plan (the entry client id is
# `x-<plan_hash[:32]><role_code>`), so its deterministic entry id is another order.
TEST_ONLY_HASH_B = "b" * 64
TEST_ONLY_SYMBOL_B = "ETHUSDT"


def _entry_id_of(plan_hash: str) -> str:
    return derive_client_order_id(plan_hash=plan_hash, role=OrderRole.ENTRY.value)


async def _partial_restart_with_resting_b(
    *, partial_fill: Decimal | None = None, on_enter: Callable[[str, datetime], None] | None = None
) -> tuple[LiveRig, Restart, str]:
    """Plan A rests and is restorable; plan B rests on the exchange but cannot be rebuilt.

    B's row is a second restorable ENTRY row with a distinct plan hash whose trade plan id has no
    persisted plan. The fake exchange holds B's entry under its deterministic client id.
    """
    rig = await _run_one_resting_entry()
    restart = await _restart(rig, crash_in_safe_mode=None, on_enter=on_enter)
    real = rig.intents.get_entry(approval_id=rig.approve_row().approval_id)
    assert real is not None
    b_id = _entry_id_of(TEST_ONLY_HASH_B)
    extra = _extra_row(
        real, plan_hash=TEST_ONLY_HASH_B, symbol=TEST_ONLY_SYMBOL_B, client_order_id=b_id
    )
    placed = dict(rig.fake.calls_to("place_entry")[0]["kwargs"])
    placed.update(symbol=TEST_ONLY_SYMBOL_B, new_client_order_id=b_id)
    await rig.fake.place_entry(**placed)
    if partial_fill is not None:
        rig.fake.fill(b_id, quantity=partial_fill)
    restart.builder = restored_plans_builder(
        intents=_TwoRowReader(restart.reader, extra),
        plan_for=lambda trade_plan_id: (
            None if trade_plan_id == extra.trade_plan_id else rig.stores.plans.get(trade_plan_id)
        ),
        snapshot_for=lambda trade_plan_id: restart.snapshot,
        transition_events_for=restart._events_of,
        index=restart.index,
        tp1_quantity_fraction=TEST_ONLY_TP1_FRACTION,
        snapshot_ttl=TEST_ONLY_SNAPSHOT_TTL,
    )
    return rig, restart, b_id


def _unrestored_port(rig: LiveRig, restart: Restart) -> Callable[[Any, datetime], Any]:
    async def port(entries: Any, now_utc: datetime) -> Any:
        return await cancel_unrestored_entries(
            entries=entries,
            adapter=rig.fake,  # type: ignore[arg-type]
            journal=rig.journal,
            spill=None,
            alerts=restart.alerts,
            now_utc=now_utc,
        )

    return port


async def test_the_partial_restore_carries_the_unrestorable_entry_with_its_shared_hash_flag() -> (
    None
):
    rig, restart, builder, _ = await _two_rows_one_corrupt(plan_for_extra_is_none=True)
    with pytest.raises(PartialRestore) as raised:
        builder(lambda plan_hash: ())
    (entry,) = raised.value.entries
    assert isinstance(entry, UnrestorableEntry)
    assert entry.trade_plan_id == "TEST_ONLY_second_plan"
    assert entry.approval_id == "TEST_ONLY_second_approval"
    assert entry.plan_hash == rig.plan.plan_hash and entry.symbol == TEST_ONLY_SYMBOL
    assert entry.fault_class == "RestoreSourceMissing"
    assert entry.plan_hash_rebuilt is True, "the healthy plan has this plan hash"

    report = await restart.recover()
    assert report.unrestorable_entries == (entry,)


async def test_a_distinct_hash_unrestorable_entry_is_not_flagged_as_rebuilt() -> None:
    rig, restart, b_id = await _partial_restart_with_resting_b()
    with pytest.raises(PartialRestore) as raised:
        restart.builder(lambda plan_hash: ())
    (entry,) = raised.value.entries
    assert entry.plan_hash == TEST_ONLY_HASH_B and entry.symbol == TEST_ONLY_SYMBOL_B
    assert entry.plan_hash_rebuilt is False
    assert [p.entry.plan_hash for p in raised.value.plans] == [rig.plan.plan_hash]


async def test_a_full_restore_and_a_store_outage_leave_no_unrestorable_entries() -> None:
    rig = await _run_one_resting_entry()
    restart = await _restart(rig, crash_in_safe_mode=None)
    assert (await restart.recover()).unrestorable_entries == ()

    def outage(correlation: str) -> list[JournalEvent]:
        raise OSError("journal is down (test)")

    other = await _restart(rig, crash_in_safe_mode=None)
    other.builder = restored_plans_builder(
        intents=other.reader,
        plan_for=rig.stores.plans.get,
        snapshot_for=lambda trade_plan_id: other.snapshot,
        transition_events_for=outage,
        index=ClientIdIndex(),
        tp1_quantity_fraction=TEST_ONLY_TP1_FRACTION,
        snapshot_ttl=TEST_ONLY_SNAPSHOT_TTL,
    )
    assert (await other.recover()).unrestorable_entries == ()


async def test_the_start_sequence_cancels_the_unrestored_plans_entry_once_and_keeps_the_rest(
    tmp_path: Any,
) -> None:
    rig, restart, b_id = await _partial_restart_with_resting_b()
    harness = Harness(tmp=tmp_path)
    harness.install()
    placements_before = {
        name: len(rig.fake.calls_to(name))
        for name in ("place_entry", "place_algo_protective", "place_market_close")
    }
    cancels_before = len(rig.fake.calls_to("cancel_normal_order"))
    ports = dataclasses.replace(
        harness.ports(),
        load_safe_mode=lambda: restart.safe_mode,
        recovery=dataclasses.replace(
            restart.recovery_ports(), unrestored_entries=_unrestored_port(rig, restart)
        ),
    )

    outcome = await startup.run_start_sequence(ports, now_utc=T0)

    assert outcome.admitted and outcome.recovery is not None
    assert outcome.recovery.plans_restored == 1 and outcome.recovery.plans_unrestorable == 1
    new_cancels = rig.fake.calls_to("cancel_normal_order")[cancels_before:]
    assert [c["kwargs"] for c in new_cancels] == [
        {"symbol": TEST_ONLY_SYMBOL_B, "orig_client_order_id": b_id}
    ]
    assert b_id not in rig.fake.open_orders, "the unwatched resting entry is gone"
    assert rig.entry_id in rig.fake.open_orders, "the healthy plan's entry stays open"
    protection = restart.coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.AWAITING_FILL
    for name, before in placements_before.items():
        assert len(rig.fake.calls_to(name)) == before, f"{name} was called during the start"
    assert outcome.in_safe_mode and restart.safe_mode.entered_reason == "RESTORE_INCONSISTENT"
    assert "RECOVERY" in outcome.degraded_steps
    assert restart.alerts.alerts == [], "a clean cancel of a flat symbol raises no alert"
    triggers = {
        json.loads(row.payload_json)["trigger_reason"]
        for row in rig.journal.by_type("ENTRY_EXPIRY")
        if row.entity_id == b_id
    }
    assert triggers == {"protection_handoff_failed"}


async def test_a_position_on_the_unrestored_plans_symbol_is_alerted_and_never_closed(
    tmp_path: Any,
) -> None:
    rig, restart, b_id = await _partial_restart_with_resting_b(partial_fill=D("0.03"))
    position_before = dict(rig.fake.positions)
    assert position_before.get(TEST_ONLY_SYMBOL_B) == D("0.03")
    harness = Harness(tmp=tmp_path)
    harness.install()
    cancels_before = len(rig.fake.calls_to("cancel_normal_order"))
    ports = dataclasses.replace(
        harness.ports(),
        load_safe_mode=lambda: restart.safe_mode,
        recovery=dataclasses.replace(
            restart.recovery_ports(), unrestored_entries=_unrestored_port(rig, restart)
        ),
    )

    outcome = await startup.run_start_sequence(ports, now_utc=T0)

    assert outcome.admitted
    assert len(rig.fake.calls_to("cancel_normal_order")) == cancels_before + 1, "the remainder"
    assert b_id not in rig.fake.open_orders
    (alert,) = restart.alerts.alerts
    assert alert.event == "DIVERGENCE" and alert.reason == "UNRESTORED_PLAN_POSITION"
    assert alert.symbol == TEST_ONLY_SYMBOL_B and alert.plan_hash == TEST_ONLY_HASH_B
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.fake.positions == position_before, "nothing was closed"
    assert outcome.in_safe_mode and "RECOVERY" in outcome.degraded_steps


async def test_a_start_without_the_port_behaves_as_before(tmp_path: Any) -> None:
    rig, restart, b_id = await _partial_restart_with_resting_b()
    harness = Harness(tmp=tmp_path)
    harness.install()
    cancels_before = len(rig.fake.calls_to("cancel_normal_order"))
    ports = dataclasses.replace(
        harness.ports(),
        load_safe_mode=lambda: restart.safe_mode,
        recovery=restart.recovery_ports(),
    )
    assert ports.recovery.unrestored_entries is None

    outcome = await startup.run_start_sequence(ports, now_utc=T0)

    assert outcome.admitted and "RECOVERY" in outcome.degraded_steps
    assert len(rig.fake.calls_to("cancel_normal_order")) == cancels_before
    assert b_id in rig.fake.open_orders
