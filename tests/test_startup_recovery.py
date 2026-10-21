"""Startup recovery and the closer's pending attempt after a restart (Phase 20, plan 20-19).

``run_startup_recovery`` restores SAFE_MODE, the pending-action table, the coordinator, the
closer, the execution intents and the local spill in a fixed order, from durable sources only,
and enters SAFE_MODE whenever it cannot prove one of them. Every test runs offline against the
stateful Phase 19 fake exchange, in-memory stores, a real ``LocalSpill`` on ``tmp_path`` and
virtual time. A green test proves agreement with the fakes, not with Binance (no Demo
observation); wiring a running process is Phase 24.
"""

from __future__ import annotations

import ast
import json
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.emergency_close import (
    CODE_HISTORY_NOT_TERMINAL,
    EmergencyCloseStatus,
    MarketEmergencyCloser,
    pending_attempts_from_events,
    plan_hash_of_close_event,
)
from src.execution.order_ids import derive_close_order_id
from src.execution.protection import ProtectionCoordinator, ProtectionState
from src.execution.protection_rebuild import RestoredPlan, rebuild_plan
from src.ops.spill import LocalSpill, replay_spill
from src.persistence.errors import StoreUnavailable
from src.reconcile.safe_mode import SAFE_MODE_STATE_UNREADABLE, SafeModeController
from src.reconcile.startup import (
    STEP_CLOSER_RESTORED,
    STEP_COORDINATOR_RESTORED,
    STEP_INTENTS_RESOLVED,
    STEP_PENDING_LOADED,
    STEP_SAFE_MODE_LOADED,
    STEP_SPILL_READ,
    STEP_SPILL_REPLAYED,
    StartupReport,
    run_startup_recovery,
)

from tests.support.execution_limits import test_only_execution_limits as _test_limits
from tests.support.intent_store_fakes import SimulatedCrash
from tests.support.pending_action_fakes import (
    FailingPendingActionStore,
    InMemoryPendingActionStore,
)
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    ProtectionRig,
    RecordingSafeMode,
    lot_filters_for_tests,
    make_rig,
)
from tests.support.reconcile_doubles import InMemorySafeModeStore, RaisingJournal
from tests.support.reconcile_doubles import RecordingJournal as ConflictJournal

D = Decimal
STARTUP_SOURCE = Path("src/reconcile/startup.py")
EXPECTED_STEPS = (
    STEP_SAFE_MODE_LOADED,
    STEP_PENDING_LOADED,
    STEP_SPILL_READ,
    STEP_COORDINATOR_RESTORED,
    STEP_CLOSER_RESTORED,
    STEP_INTENTS_RESOLVED,
    STEP_SPILL_REPLAYED,
)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


class SpySafeMode(RecordingSafeMode):
    """A SAFE_MODE controller double that records any attempt to leave SAFE_MODE."""

    def __init__(self) -> None:
        super().__init__()
        self.exit_calls = 0

    async def exit_safe_mode(self, **_: Any) -> None:
        self.exit_calls += 1


class OrderedPending(InMemoryPendingActionStore):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    def list_open(self) -> Any:
        self._order.append("pending")
        return super().list_open()


class OrderedSpill(LocalSpill):
    def __init__(self, directory: Path, order: list[str]) -> None:
        super().__init__(directory)
        self._order = order

    def scan(self) -> Any:
        self._order.append("spill")
        return super().scan()


class OrderedIntents:
    """Delegates to the in-memory intent store and logs the recovery read."""

    def __init__(self, inner: Any, order: list[str]) -> None:
        self._inner = inner
        self._order = order

    def list_unresolved_intents(self) -> Any:
        self._order.append("intents")
        return self._inner.list_unresolved_intents()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@dataclass
class Harness:
    rig: ProtectionRig
    safe_mode: Any
    coordinator: ProtectionCoordinator
    closer: MarketEmergencyCloser
    pending: Any
    spill: LocalSpill | None
    journal: Any
    order: list[str] = field(default_factory=list)
    spill_rows_seen: list[Any] = field(default_factory=list)
    calls_before: int = 0

    def builder(self) -> Callable[[Callable[[str], Any]], Sequence[RestoredPlan]]:
        rig = self.rig

        def build(spill_rows_for: Callable[[str], Any]) -> Sequence[RestoredPlan]:
            self.order.append("builder")
            rows = spill_rows_for(rig.entry.plan_hash)
            self.spill_rows_seen.append(rows)
            events = [
                e
                for e in rig.journal.events.values()
                if e.correlation_id == f"protection_{rig.entry.plan_hash}"
            ]
            return [
                rebuild_plan(
                    entry=rig.entry,
                    transition_events=events,
                    entry_intent=rig.inner_store.get_entry(approval_id=rig.entry.approval_id),
                    stop_intent=rig.inner_store.get_intent(
                        approval_id=rig.entry.approval_id, role="STOP_LOSS"
                    ),
                    spill_rows=rows,
                )
            ]

        return build

    def close_reader(self) -> Callable[[], Mapping[str, Sequence[JournalEvent]]]:
        rig = self.rig

        def read() -> Mapping[str, Sequence[JournalEvent]]:
            self.order.append("close_reader")
            out: dict[str, list[JournalEvent]] = {}
            for event in rig.journal.events.values():
                plan = plan_hash_of_close_event(event)
                if plan is not None:
                    out.setdefault(plan, []).append(event)
            return out

        return read

    def replayer(self) -> Callable[[Any, Any], Any]:
        def replay(spill: Any, journal: Any) -> Any:
            self.order.append("replay")
            return replay_spill(spill, journal)

        return replay

    async def run(self, *, load: Callable[[], Any] | None = None) -> StartupReport:
        rig = self.rig

        def safe_mode_load() -> Any:
            self.order.append("safe_mode_load")
            return self.safe_mode if load is None else load()

        return await run_startup_recovery(
            safe_mode_load=safe_mode_load,
            pending_store=self.pending,
            coordinator=self.coordinator,
            closer=self.closer,
            restored_plans_builder=self.builder(),
            close_attempts_reader=self.close_reader(),
            intent_store=OrderedIntents(rig.inner_store, self.order),  # type: ignore[arg-type]
            probe_adapter=rig.fake,
            journal=self.journal,
            spill=self.spill,
            now_utc=rig.clock.now(),
            spill_replay=self.replayer(),
        )

    def new_adapter_calls(self) -> list[str]:
        return [c["method"] for c in self.rig.fake.calls[self.calls_before :]]


def _closer(rig: ProtectionRig, safe_mode: Any, *, journal: Any = None, spill: Any = None) -> Any:
    rig.fake.set_lot_filters("BTCUSDT", lot_filters_for_tests())
    return MarketEmergencyCloser(
        adapter=rig.fake,
        journal=rig.journal if journal is None else journal,
        safe_mode_controller=safe_mode,
        alert_sink=rig.alerts,
        clock=rig.clock,
        limits=_test_limits(),
        spill=spill,
    )


def harness(
    rig: ProtectionRig,
    tmp_path: Path,
    *,
    safe_mode: Any = None,
    pending: Any = None,
    with_spill: bool = True,
    journal: Any = None,
) -> Harness:
    order: list[str] = []
    mode = SpySafeMode() if safe_mode is None else safe_mode
    pending_store = OrderedPending(order) if pending is None else pending
    spill = OrderedSpill(tmp_path / "spill", order) if with_spill else None
    coordinator = ProtectionCoordinator(
        adapter=rig.fake,
        intent_store=rig.inner_store,  # type: ignore[arg-type]
        journal=rig.journal,
        safe_mode_controller=mode,
        alert_sink=rig.alerts,
        emergency_closer=rig.closer,
        limits=_test_limits(),
        clock=rig.clock,
        pending_actions=pending_store,
        restore_required=True,
    )
    return Harness(
        rig=rig,
        safe_mode=mode,
        coordinator=coordinator,
        closer=_closer(rig, mode, spill=spill),
        pending=pending_store,
        spill=spill,
        journal=ConflictJournal() if journal is None else journal,
        order=order,
        calls_before=len(rig.fake.calls),
    )


def _close_pre_send_event(rig: ProtectionRig, *, attempt_no: int = 1) -> JournalEvent:
    """What a closer's pre_send row looks like (written ahead to the spill)."""
    client_id = derive_close_order_id(plan_hash=rig.entry.plan_hash, attempt_no=attempt_no)
    body = json.dumps(
        {
            "phase": "pre_send",
            "plan_hash": rig.entry.plan_hash,
            "symbol": rig.entry.symbol,
            "reason": "B4_FILL_AFTER_STOP",
            "attempt_no": attempt_no,
            "client_order_id": client_id,
            "side": "SELL",
            "quantity": "0.004",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    at = rig.clock.now()
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="ecl",
            event_type="EMERGENCY_CLOSE",
            entity_id=client_id,
            occurred_at_utc=at,
            payload_json=body,
        ),
        occurred_at_utc=at,
        event_type="EMERGENCY_CLOSE",
        entity_type="Order",
        entity_id=client_id,
        correlation_id=f"emergency_close_{rig.entry.plan_hash}",
        trade_plan_id=rig.entry.trade_plan_id,
        approval_id=rig.entry.approval_id,
        payload_json=body,
    )


async def _crashed_closer_run(rig: ProtectionRig, tmp_path: Path) -> LocalSpill:
    """Run 1 of a closer: the journal is down, pre_send goes to the spill, the process dies.

    The position is open (+0.004) and the send never reaches the exchange.
    """
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    spill = LocalSpill(tmp_path / "spill")
    closer = _closer(rig, RecordingSafeMode(), journal=RaisingJournal(), spill=spill)

    async def crash(**kwargs: Any) -> Any:
        raise SimulatedCrash

    original = rig.fake.place_market_close
    rig.fake.place_market_close = crash  # type: ignore[method-assign]
    try:
        with pytest.raises(SimulatedCrash):
            await closer.close_position(entry=rig.entry, reason="B4_FILL_AFTER_STOP")
    finally:
        rig.fake.place_market_close = original  # type: ignore[method-assign]
    return spill


# --------------------------------------------------------------------------- #
# The closer: the pending attempt survives a restart.
# --------------------------------------------------------------------------- #


async def test_pending_close_attempt_survives_restart_and_its_number_is_never_reused(
    tmp_path: Path,
) -> None:
    rig = await make_rig(real_closer=True)
    spill = await _crashed_closer_run(rig, tmp_path)

    # The pre_send row exists only in the spill (the journal was down).
    records = spill.pending()
    assert [json.loads(r.event.payload_json)["phase"] for r in records] == ["pre_send"]
    attempts = pending_attempts_from_events([r.event for r in records])
    assert [(a.attempt_no, a.seen, a.quantity, a.side) for a in attempts] == [
        (1, False, D("0.004"), "SELL")
    ]

    # Run 2: a new closer adopts attempt 1 as UNKNOWN pending.
    safe_mode = RecordingSafeMode()
    closer2 = _closer(rig, safe_mode)
    closer2.restore_pending(plan_hash=rig.entry.plan_hash, attempts=attempts)
    first_id = derive_close_order_id(plan_hash=rig.entry.plan_hash, attempt_no=1)
    second_id = derive_close_order_id(plan_hash=rig.entry.plan_hash, attempt_no=2)

    # The fake shows attempt 1 as not found: nothing is sent, the failure is visible.
    assert await closer2.close_position(entry=rig.entry, reason="B4_FILL_AFTER_STOP") is False
    assert closer2.last_result is not None
    assert closer2.last_result.status is EmergencyCloseStatus.PENDING_UNKNOWN
    assert closer2.last_result.reason == CODE_HISTORY_NOT_TERMINAL
    assert rig.fake.calls_to("place_market_close") == []
    assert "EMERGENCY_CLOSE_FAILED" in safe_mode.entered_reasons

    # The late attempt 1 arrives and fills 0.001 of the 0.004: the closer reads the position
    # again and sends the rest under attempt number 2, never under 1.
    await rig.fake.place_market_close(
        symbol="BTCUSDT",
        side="SELL",
        position_side="BOTH",
        quantity=D("0.001"),
        new_client_order_id=first_id,
    )
    assert await closer2.close_position(entry=rig.entry, reason="B4_FILL_AFTER_STOP") is True
    sent = [c["kwargs"]["new_client_order_id"] for c in rig.fake.calls_to("place_market_close")]
    assert sent == [first_id, second_id]  # the first is the late arrival, the second the closer's
    assert rig.fake.positions["BTCUSDT"] == D("0")


async def test_pre_send_is_written_ahead_to_the_spill_and_removed_after_the_journal(
    tmp_path: Path,
) -> None:
    rig = await make_rig(real_closer=True)
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    spill = LocalSpill(tmp_path / "spill")
    seen_during_send: list[int] = []
    original = rig.fake.place_market_close

    async def observe(**kwargs: Any) -> Any:
        seen_during_send.append(len(spill.pending()))
        return await original(**kwargs)

    rig.fake.place_market_close = observe  # type: ignore[method-assign]
    closer = _closer(rig, RecordingSafeMode(), spill=spill)
    assert await closer.close_position(entry=rig.entry, reason="B4_FILL_AFTER_STOP") is True
    # With a healthy journal the spill file is removed once the journal took the row, so the
    # write-ahead record exists only while the journal write is the open question.
    assert spill.pending() == ()
    assert seen_during_send == [0]
    assert any(
        json.loads(e.payload_json).get("phase") == "pre_send"
        for e in rig.journal.events.values()
        if e.event_type == "EMERGENCY_CLOSE"
    )


def test_pending_attempts_are_read_from_phases_not_from_notes() -> None:
    plan = "a1" * 32

    def event(phase: str, attempt: int, second: int, **extra: Any) -> JournalEvent:
        from datetime import UTC, datetime

        at = datetime(2026, 10, 16, 12, 0, second, tzinfo=UTC)
        body = json.dumps(
            {
                "phase": phase,
                "attempt_no": attempt,
                "client_order_id": f"xc-{attempt}",
                "plan_hash": plan,
                **extra,
            },
            sort_keys=True,
        )
        return JournalEvent(
            journal_event_id=f"e{attempt}{phase}{second}",
            occurred_at_utc=at,
            event_type="EMERGENCY_CLOSE",
            entity_type="Order",
            entity_id=f"xc-{attempt}",
            correlation_id=f"emergency_close_{plan}",
            payload_json=body,
        )

    note = JournalEvent(
        journal_event_id="note1",
        occurred_at_utc=event("pre_send", 1, 1).occurred_at_utc,
        event_type="EMERGENCY_CLOSE",
        entity_type="EmergencyClose",
        entity_id=plan,
        correlation_id=f"emergency_close_{plan}",
        payload_json=json.dumps({"phase": "failed", "plan_hash": plan}),
    )
    events = [
        event("pre_send", 1, 1, side="SELL", quantity="0.004"),
        event("filled", 1, 2),  # attempt 1 ended
        event("pre_send", 2, 3, side="SELL", quantity="0.002"),
        event("post_send", 2, 4),  # acknowledged, not terminal
        event("pre_send", 3, 5, side="SELL", quantity="0.001"),
        event("rejected", 3, 6),  # ended
        event("pre_send", 4, 7, side="BUY", quantity="0.001"),
        event("ambiguous", 4, 8),
        note,
    ]
    found = pending_attempts_from_events(events)
    assert [(a.attempt_no, a.seen) for a in found] == [(2, True), (4, False)]
    with pytest.raises(ValueError):
        pending_attempts_from_events(
            [
                JournalEvent(
                    journal_event_id="bad",
                    occurred_at_utc=events[0].occurred_at_utc,
                    event_type="EMERGENCY_CLOSE",
                    entity_type="Order",
                    entity_id="x",
                    correlation_id=f"emergency_close_{plan}",
                    payload_json=json.dumps({"attempt_no": "one", "phase": "pre_send"}),
                )
            ]
        )


# --------------------------------------------------------------------------- #
# run_startup_recovery.
# --------------------------------------------------------------------------- #


async def test_all_sources_healthy_runs_the_fixed_order_and_changes_nothing_else(
    tmp_path: Path,
) -> None:
    rig = await make_rig(real_closer=True)
    h = harness(rig, tmp_path)
    h.safe_mode.enter_safe_mode(reason="SOME_EARLIER_REASON")  # the process was in SAFE_MODE

    report = await h.run()

    assert report.steps == EXPECTED_STEPS
    assert report.failed_steps == ()
    assert h.order == [
        "safe_mode_load",
        "pending",
        "spill",
        "builder",
        "close_reader",
        "intents",
        "replay",
        "spill",  # replay_spill scans the directory again, after everything else
    ]
    assert report.restore_complete is True
    assert h.coordinator.restore_complete is True
    assert report.plans_restored == 1
    assert report.pending_open == 0
    assert report.safe_mode_reasons == ()
    # SAFE_MODE is unchanged and startup never tried to leave it.
    assert report.in_safe_mode is True
    assert h.safe_mode.entered_reasons == ["SOME_EARLIER_REASON"]
    assert h.safe_mode.exit_calls == 0
    # Binance is read through the probes only: no placement, cancel or close call.
    assert not [m for m in h.new_adapter_calls() if m.startswith(("place_", "cancel_", "new_"))]
    view = h.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert view is not None and view.state is ProtectionState.AWAITING_FILL


async def test_safe_mode_store_unreadable_starts_in_safe_mode_and_recovery_continues(
    tmp_path: Path,
) -> None:
    rig = await make_rig(real_closer=True)

    class UnreadableStore(InMemorySafeModeStore):
        def load(self) -> Any:
            raise StoreUnavailable("safe mode store is down (test)")

    controller = SafeModeController.load(
        adapter=rig.fake,
        journal=ConflictJournal(),
        state_store=UnreadableStore(),
        now_utc=rig.clock.now(),
    )
    assert controller.entered_reason == SAFE_MODE_STATE_UNREADABLE
    h = harness(rig, tmp_path, safe_mode=controller)

    report = await h.run()

    assert report.steps == EXPECTED_STEPS
    assert report.in_safe_mode is True
    assert controller.entered_reason == SAFE_MODE_STATE_UNREADABLE  # still the start reason
    assert report.restore_complete is True


async def test_pending_action_store_unreadable_enters_db_failure_and_the_coordinator_still_restores(
    tmp_path: Path,
) -> None:
    rig = await make_rig(real_closer=True)
    h = harness(rig, tmp_path, pending=FailingPendingActionStore())

    report = await h.run()

    assert STEP_PENDING_LOADED in report.failed_steps
    assert STEP_PENDING_LOADED not in report.steps
    assert report.pending_open is None
    assert "DB_FAILURE" in h.safe_mode.entered_reasons
    assert STEP_COORDINATOR_RESTORED in report.steps
    assert report.restore_complete is True
    # The unreadable pending table blocks entries (the coordinator reads the same store).
    assert h.coordinator.blocks_new_entries() is True


async def test_open_pending_actions_are_counted_and_block_entries(tmp_path: Path) -> None:
    from src.execution.pending_actions import PendingKind

    rig = await make_rig(real_closer=True)
    pending = InMemoryPendingActionStore()
    pending.record_blocked(
        plan_hash=rig.entry.plan_hash,
        trade_plan_id=rig.entry.trade_plan_id,
        approval_id=rig.entry.approval_id,
        symbol=rig.entry.symbol,
        kind=PendingKind.STOP_NOT_SENT,
        gate_reason="RATE_LIMIT_PAUSE_429",
        retry_after_until_utc=None,
        now_utc=rig.clock.now(),
    )
    h = harness(rig, tmp_path, pending=pending)
    report = await h.run()
    assert report.pending_open == 1
    assert h.coordinator.blocks_new_entries() is True


async def test_spill_directory_missing_is_allowed_and_enters_no_safe_mode(tmp_path: Path) -> None:
    rig = await make_rig(real_closer=True)
    h = harness(rig, tmp_path)
    assert h.spill is not None
    shutil.rmtree(h.spill.directory)  # the directory is gone: nothing is pending

    report = await h.run()

    assert report.steps == EXPECTED_STEPS
    assert report.safe_mode_reasons == ()
    assert h.safe_mode.entered_reasons == []
    assert report.spill_records == 0

    no_spill = harness(await make_rig(real_closer=True), tmp_path / "other", with_spill=False)
    report = await no_spill.run()
    assert report.steps == EXPECTED_STEPS
    assert report.safe_mode_reasons == ()


async def test_spill_file_corrupt_enters_restore_inconsistent_keeps_the_file_and_continues(
    tmp_path: Path,
) -> None:
    rig = await make_rig(real_closer=True)
    h = harness(rig, tmp_path)
    assert h.spill is not None
    bad = h.spill.directory / "deadbeef.json"
    bad.write_text("{this is not json", encoding="utf-8")

    report = await h.run()

    assert "RESTORE_INCONSISTENT" in h.safe_mode.entered_reasons
    assert STEP_SPILL_READ in report.failed_steps
    assert report.spill_corrupt == (("deadbeef", "INVALID_JSON"),)
    assert bad.exists()  # the evidence is kept
    # The plans were rebuilt with an unreadable spill (None): their stop history is unknown.
    assert h.spill_rows_seen == [None]
    assert STEP_INTENTS_RESOLVED in report.steps  # recovery continued
    assert h.safe_mode.exit_calls == 0


async def test_spill_record_conflicting_with_the_journal_enters_restore_inconsistent(
    tmp_path: Path,
) -> None:
    rig = await make_rig(real_closer=True)
    journal = ConflictJournal()
    h = harness(rig, tmp_path, journal=journal)
    assert h.spill is not None
    spilled = _close_pre_send_event(rig)
    h.spill.write(spilled)
    from dataclasses import replace

    journal.preload(replace(spilled, payload_json=spilled.payload_json.replace("0.004", "0.005")))

    report = await h.run()

    assert "RESTORE_INCONSISTENT" in h.safe_mode.entered_reasons
    assert STEP_SPILL_REPLAYED in report.failed_steps
    assert report.spill_replay.conflicts == (spilled.journal_event_id,)
    assert (h.spill.directory / f"{spilled.journal_event_id}.json").exists()  # file kept
    assert STEP_INTENTS_RESOLVED in report.steps


async def test_spill_close_attempt_that_binance_does_not_show_stays_unknown_pending(
    tmp_path: Path,
) -> None:
    rig = await make_rig(real_closer=True)
    await _crashed_closer_run(rig, tmp_path)  # writes tmp_path / "spill", which the harness reads
    h2 = harness(rig, tmp_path)
    assert h2.spill is not None and len(h2.spill.pending()) == 1

    report = await h2.run()

    assert report.close_attempts_adopted == ((rig.entry.plan_hash, 1),)
    assert STEP_CLOSER_RESTORED in report.steps
    # Binance shows no such order: the attempt stays UNKNOWN pending, nothing is sent and no new
    # attempt number is issued.
    assert await h2.closer.close_position(entry=rig.entry, reason="B4_FILL_AFTER_STOP") is False
    assert h2.closer.last_result is not None
    assert h2.closer.last_result.status is EmergencyCloseStatus.PENDING_UNKNOWN
    assert rig.fake.calls_to("place_market_close") == []
    assert "EMERGENCY_CLOSE_FAILED" in h2.safe_mode.entered_reasons
    assert h2.safe_mode.exit_calls == 0


async def test_close_attempts_from_the_journal_are_adopted_too(tmp_path: Path) -> None:
    rig = await make_rig(real_closer=True)
    rig.journal.record(_close_pre_send_event(rig))
    h = harness(rig, tmp_path)
    report = await h.run()
    assert report.close_attempts_adopted == ((rig.entry.plan_hash, 1),)


async def test_a_malformed_close_row_enters_restore_inconsistent(tmp_path: Path) -> None:
    rig = await make_rig(real_closer=True)
    good = _close_pre_send_event(rig)
    from dataclasses import replace

    rig.journal.record(
        replace(
            good,
            journal_event_id="ecl_bad_row",
            payload_json=json.dumps({"phase": "pre_send", "attempt_no": "one"}),
        )
    )
    h = harness(rig, tmp_path)
    report = await h.run()
    assert "RESTORE_INCONSISTENT" in h.safe_mode.entered_reasons
    assert STEP_CLOSER_RESTORED in report.failed_steps
    assert report.close_attempts_adopted == ()


async def test_ambiguous_recovery_enters_safe_mode_and_the_coordinator_places_the_stop_once(
    tmp_path: Path,
) -> None:
    """A crash after the STOP_LOSS intent was SENT, end to end through startup (F5 order)."""
    rig = await make_rig(real_closer=True)
    original = rig.fake.place_algo_protective

    async def crash(**kwargs: Any) -> Any:
        raise SimulatedCrash

    rig.fake.place_algo_protective = crash  # type: ignore[method-assign]
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    with pytest.raises(SimulatedCrash):
        await rig.coordinator.step()
    rig.fake.place_algo_protective = original  # type: ignore[method-assign]
    await rig.clock.advance(1.5)

    h = harness(rig, tmp_path)
    report = await h.run()

    assert h.order.index("builder") < h.order.index("intents")  # rebuild first (F5)
    assert report.intents is not None and report.intents.safe_mode_entered is True
    assert "UNRESOLVED_EXECUTION_INTENT" in h.safe_mode.entered_reasons
    # The recovery left the live plan's STOP_LOSS intent UNKNOWN; the coordinator places once.
    assert h.coordinator.protection_of(TEST_ONLY_PLAN_HASH).state is ProtectionState.UNPROTECTED  # type: ignore[union-attr]
    await h.coordinator.step()
    await h.coordinator.step()
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    stop_intent = rig.inner_store.get_intent(approval_id=rig.entry.approval_id, role="STOP_LOSS")
    assert stop_intent is not None and stop_intent.intent_status.value == "ACKED"
    assert h.safe_mode.exit_calls == 0


async def test_a_restore_that_is_refused_is_reported_and_the_coordinator_keeps_blocking(
    tmp_path: Path,
) -> None:
    rig = await make_rig(real_closer=True)
    h = harness(rig, tmp_path)

    def broken_builder(spill_rows_for: Callable[[str], Any]) -> Sequence[RestoredPlan]:
        raise StoreUnavailable("journal is down (test)")

    report = await run_startup_recovery(
        safe_mode_load=lambda: h.safe_mode,
        pending_store=h.pending,
        coordinator=h.coordinator,
        closer=h.closer,
        restored_plans_builder=broken_builder,
        close_attempts_reader=h.close_reader(),
        intent_store=rig.inner_store,  # type: ignore[arg-type]
        probe_adapter=rig.fake,
        journal=h.journal,
        spill=h.spill,
        now_utc=rig.clock.now(),
    )

    assert STEP_COORDINATOR_RESTORED in report.failed_steps
    assert "DB_FAILURE" in h.safe_mode.entered_reasons
    assert report.restore_complete is False  # the plans are unknown: nothing claims "no plans"
    assert h.coordinator.blocks_new_entries() is True


# --------------------------------------------------------------------------- #
# Static guards.
# --------------------------------------------------------------------------- #


def test_startup_imports_no_persistence_module_and_never_leaves_safe_mode_or_places() -> None:
    source = STARTUP_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("src.persistence"), node.module
        elif isinstance(node, ast.Import):
            assert not any(alias.name.startswith("src.persistence") for alias in node.names)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "exit_safe_mode" not in called
    assert not {name for name in called if name.startswith(("place_", "cancel_", "new_"))}
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "now"]


def test_startup_report_is_a_frozen_value() -> None:
    assert StartupReport.__dataclass_params__.frozen is True  # type: ignore[attr-defined]
