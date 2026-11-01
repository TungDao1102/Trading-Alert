"""An UNKNOWN entry closed RECONCILED_ABSENT reaches the coordinator at once (plan 24-34, D-35).

20-DEFERRED ("Coordinator notification of a RECONCILED_ABSENT entry"): when `UnknownEntryResolver`
closed an UNKNOWN entry as REJECTED the protection coordinator was not told, so the plan stayed
tracked as AWAITING_FILL until its own step. The resolver now takes an optional `on_resolved`
callback; the live composition binds it to `ProtectionCoordinator.note_entry_resolved`.

G4-034 (D051 item (i)): every resolver exit from UNKNOWN journals its evidence source (a REST
probe), the probe count and the injected time. D080 is unchanged: fewer probes than configured, or
one probe error, closes nothing.

Fakes only: the Binance-semantics fake exchange, the in-memory intent store, virtual time. The
limits are the TEST_ONLY values of plan 20-01. Nothing here is [DEMO].
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from src.domain.enums import ExecutionIntentStatus
from src.domain.stream_records import UNKNOWN_EXIT_EVIDENCE
from src.execution.intent_recovery import (
    EVENT_UNKNOWN_ENTRY_PROBE,
    UnknownEntryResolver,
)
from src.execution.intent_store import RESOLUTION_RECONCILED_ABSENT, IntentRecord
from src.execution.protection import (
    EVENT_ENTRY_RECONCILED_ABSENT,
    ProtectionState,
)

from tests.support.execution_limits import TEST_ONLY_EXECUTION_LIMIT_VALUES
from tests.support.execution_limits import test_only_execution_limits as make_limits
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.protection_doubles import (
    TEST_ONLY_APPROVAL_ID,
    TEST_ONLY_PLAN_HASH,
    TEST_ONLY_SYMBOL,
    TEST_ONLY_TRADE_PLAN_ID,
    ProtectionRig,
    make_rig,
)
from tests.support.reconcile_doubles import RecordingJournal
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START

D = Decimal
UNKNOWN = ExecutionIntentStatus.UNKNOWN
REJECTED = ExecutionIntentStatus.REJECTED

PROBE_COUNT = TEST_ONLY_EXECUTION_LIMIT_VALUES["reconcile.entry_unknown_probe_count"]
INTERVAL = timedelta(
    milliseconds=TEST_ONLY_EXECUTION_LIMIT_VALUES["reconcile.entry_unknown_probe_interval_ms"]
)
GRACE = timedelta(
    milliseconds=TEST_ONLY_EXECUTION_LIMIT_VALUES["protection.entry_unknown_grace_ms"]
)
GOOD_TILL = TEST_ONLY_VIRTUAL_START + timedelta(minutes=30)
AFTER_GRACE = GOOD_TILL + GRACE + INTERVAL


class _SafeMode:
    def __init__(self) -> None:
        self.entered: list[str] = []

    def enter_safe_mode(self, *, reason: str, now_utc: object = None) -> None:
        self.entered.append(reason)


def _good_till(_record: IntentRecord) -> object:
    return GOOD_TILL


class _Bound:
    """A resolver, its store/journal and a rig whose coordinator tracks the same plan."""

    def __init__(
        self,
        rig: ProtectionRig,
        store: InMemoryExecutionIntentStore,
        journal: RecordingJournal,
        resolver: UnknownEntryResolver,
        callbacks: list[tuple[str, str]],
    ) -> None:
        self.rig = rig
        self.store = store
        self.journal = journal
        self.resolver = resolver
        self.callbacks = callbacks

    def intent(self) -> IntentRecord:
        row = self.store.get_intent(approval_id=TEST_ONLY_APPROVAL_ID, role="ENTRY")
        assert row is not None
        return row

    def state(self) -> ProtectionState:
        protection = self.rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
        assert protection is not None
        return protection.state


async def _bound(*, bind_callback: bool, exists: bool = False) -> _Bound:
    """An ENTRY_STATE_UNKNOWN plan: UNKNOWN in the store and AWAITING_FILL in the coordinator."""
    rig = await make_rig(
        place_entry=exists, entry_state_unknown=True, entry_good_till_utc=GOOD_TILL
    )
    store = InMemoryExecutionIntentStore()
    now = rig.clock.now()
    assert store.consume_and_record_entry_intent(
        approval_id=TEST_ONLY_APPROVAL_ID,
        trade_plan_id=TEST_ONLY_TRADE_PLAN_ID,
        plan_hash=TEST_ONLY_PLAN_HASH,
        client_order_id=rig.entry_id,
        symbol=TEST_ONLY_SYMBOL,
        side="BUY",
        intended_quantity=D("0.010"),
        intended_price=D("60000.00"),
        approved_quantity=D("0.010"),
        now_utc=now,
    )
    store.mark_sent(approval_id=TEST_ONLY_APPROVAL_ID, role="ENTRY", now_utc=now)
    store.record_result(
        approval_id=TEST_ONLY_APPROVAL_ID,
        role="ENTRY",
        status=UNKNOWN,
        exchange_order_id=None,
        exchange_status=None,
        now_utc=now,
    )
    journal = RecordingJournal()
    callbacks: list[tuple[str, str]] = []

    def on_resolved(plan_hash: str, resolution: str) -> None:
        callbacks.append((plan_hash, resolution))
        rig.coordinator.note_entry_resolved(plan_hash, resolution)

    resolver = UnknownEntryResolver(
        store=store,
        adapter=rig.fake,
        journal=journal,
        safe_mode_controller=_SafeMode(),
        limits=make_limits(),
        entry_good_till=_good_till,  # type: ignore[arg-type]
        on_resolved=on_resolved if bind_callback else None,
    )
    return _Bound(rig, store, journal, resolver, callbacks)


async def _run_probes(bound: _Bound) -> None:
    """The configured probes, all absent, before GTD + grace: nothing may close."""
    start = bound.rig.clock.now()
    for step in range(PROBE_COUNT):
        report = await bound.resolver.step(now_utc=start + step * INTERVAL)
        assert report.closed == ()


async def test_reconciled_absent_reaches_the_coordinator_at_once() -> None:
    bound = await _bound(bind_callback=True)
    assert bound.state() is ProtectionState.AWAITING_FILL
    await _run_probes(bound)
    assert bound.callbacks == []
    assert bound.state() is ProtectionState.AWAITING_FILL

    report = await bound.resolver.step(now_utc=AFTER_GRACE)

    # Same call: no coordinator step ran in between.
    assert report.closed == (TEST_ONLY_APPROVAL_ID,)
    assert bound.intent().intent_status == REJECTED
    assert bound.intent().resolution_reason_code == RESOLUTION_RECONCILED_ABSENT
    assert bound.callbacks == [(TEST_ONLY_PLAN_HASH, RESOLUTION_RECONCILED_ABSENT)]
    assert bound.state() is ProtectionState.ENTRY_ENDED_NO_FILL
    assert bound.rig.coordinator.blocks_new_entries() is False
    # The coordinator journaled why (a note), after its ordinary transition row.
    notes = [e for e in bound.rig.journal.calls if e.event_type == EVENT_ENTRY_RECONCILED_ABSENT]
    assert len(notes) == 1
    assert json.loads(notes[0].payload_json)["resolution"] == RESOLUTION_RECONCILED_ABSENT
    assert bound.rig.transitions()[-1] == ("AWAITING_FILL", "ENTRY_ENDED_NO_FILL")
    # Nothing was sent by either side.
    assert bound.rig.fake.calls_to("place_entry") == []
    assert bound.rig.fake.calls_to("place_algo_protective") == []
    assert bound.rig.fake.calls_to("cancel_normal_order") == []


async def test_the_coordinator_drops_an_entry_unresolved_plan_too() -> None:
    bound = await _bound(bind_callback=True)
    # Far past GTD + grace the coordinator itself moved the plan to ENTRY_UNRESOLVED.
    await bound.rig.clock.advance((GOOD_TILL - bound.rig.clock.now()).total_seconds() + 3600)
    await bound.rig.coordinator.step()
    assert bound.state() is ProtectionState.ENTRY_UNRESOLVED
    await _run_probes_after(bound)

    assert bound.state() is ProtectionState.ENTRY_ENDED_NO_FILL


async def _run_probes_after(bound: _Bound) -> None:
    start = AFTER_GRACE
    for step in range(PROBE_COUNT):
        await bound.resolver.step(now_utc=start + step * INTERVAL)


async def test_without_the_callback_the_behaviour_is_unchanged() -> None:
    bound = await _bound(bind_callback=False)
    await _run_probes(bound)

    report = await bound.resolver.step(now_utc=AFTER_GRACE)

    assert report.closed == (TEST_ONLY_APPROVAL_ID,)
    assert bound.intent().intent_status == REJECTED
    assert bound.callbacks == []
    assert bound.state() is ProtectionState.AWAITING_FILL  # waits for its own step, as before
    assert [
        e for e in bound.rig.journal.calls if e.event_type == EVENT_ENTRY_RECONCILED_ABSENT
    ] == []


async def test_fewer_probes_than_configured_close_nothing_and_notify_nobody() -> None:
    bound = await _bound(bind_callback=True)
    start = bound.rig.clock.now()
    for step in range(PROBE_COUNT - 2):
        await bound.resolver.step(now_utc=start + step * INTERVAL)
    # GTD + grace has passed, but this is probe PROBE_COUNT - 1: one short of the configured count.
    report = await bound.resolver.step(now_utc=AFTER_GRACE)
    assert report.closed == ()
    assert bound.callbacks == []
    assert bound.intent().intent_status == UNKNOWN
    assert bound.state() is ProtectionState.AWAITING_FILL


async def test_one_probe_error_restarts_the_count_and_closes_nothing() -> None:
    bound = await _bound(bind_callback=True)
    start = bound.rig.clock.now()
    await bound.resolver.step(now_utc=start)
    original = bound.rig.fake.query_order_by_client

    async def failing(**kwargs: object) -> object:
        raise RuntimeError("network")

    bound.rig.fake.query_order_by_client = failing  # type: ignore[method-assign]
    await bound.resolver.step(now_utc=start + INTERVAL)
    bound.rig.fake.query_order_by_client = original  # type: ignore[method-assign]

    # Past GTD + grace, but only the probes since the error count: PROBE_COUNT - 1 clean ones.
    for step in range(PROBE_COUNT - 1):
        report = await bound.resolver.step(now_utc=AFTER_GRACE + step * INTERVAL)
        assert report.closed == ()
    assert bound.callbacks == []
    assert bound.intent().intent_status == UNKNOWN
    assert bound.state() is ProtectionState.AWAITING_FILL


async def test_a_failing_callback_never_undoes_the_close() -> None:
    bound = await _bound(bind_callback=False)

    def boom(plan_hash: str, resolution: str) -> None:
        raise RuntimeError("coordinator gone")

    bound.resolver._on_resolved = boom  # noqa: SLF001
    await _run_probes(bound)

    report = await bound.resolver.step(now_utc=AFTER_GRACE)

    assert report.closed == (TEST_ONLY_APPROVAL_ID,)
    assert bound.intent().intent_status == REJECTED


async def test_a_plan_past_awaiting_fill_is_not_touched_by_the_notification() -> None:
    bound = await _bound(bind_callback=True, exists=True)
    bound.rig.coordinator.fill_sink(bound.rig.stream_fill(D("0.004")))
    await bound.rig.coordinator.step()
    assert bound.state() is ProtectionState.UNPROTECTED

    changed = bound.rig.coordinator.note_entry_resolved(
        TEST_ONLY_PLAN_HASH, RESOLUTION_RECONCILED_ABSENT
    )

    assert changed is False
    assert bound.state() is ProtectionState.UNPROTECTED
    # Unknown plan and unknown resolution are refused, nothing raises.
    assert (
        bound.rig.coordinator.note_entry_resolved("ff" * 32, RESOLUTION_RECONCILED_ABSENT) is False
    )
    assert bound.rig.coordinator.note_entry_resolved(TEST_ONLY_PLAN_HASH, "SOMETHING_ELSE") is False


async def test_every_exit_from_unknown_journals_source_probe_count_and_time() -> None:
    bound = await _bound(bind_callback=True)
    await _run_probes(bound)

    await bound.resolver.step(now_utc=AFTER_GRACE)

    rows = [e for e in bound.journal.events if e.event_type == UNKNOWN_EXIT_EVIDENCE]
    assert len(rows) == 1
    payload = json.loads(rows[0].payload_json)
    assert payload["evidence_source"] == "REST_RECONCILE"
    assert payload["probe_count"] == str(PROBE_COUNT + 1)
    assert payload["observed_at_utc"] == AFTER_GRACE.isoformat()
    assert payload["to_status"] == "REJECTED"
    probes = [e for e in bound.journal.events if e.event_type == EVENT_UNKNOWN_ENTRY_PROBE]
    assert len(probes) == PROBE_COUNT + 1


async def test_the_acked_exit_carries_its_evidence_too() -> None:
    bound = await _bound(bind_callback=True, exists=True)
    start = bound.rig.clock.now()

    report = await bound.resolver.step(now_utc=start)

    assert report.acked == (TEST_ONLY_APPROVAL_ID,)
    rows = [e for e in bound.journal.events if e.event_type == UNKNOWN_EXIT_EVIDENCE]
    assert len(rows) == 1
    payload = json.loads(rows[0].payload_json)
    assert payload["evidence_source"] == "REST_RECONCILE"
    assert payload["probe_count"] == "1"
    assert payload["observed_at_utc"] == start.isoformat()
    assert payload["to_status"] == "ACKED"
    assert bound.callbacks == []  # only a RECONCILED_ABSENT close is announced
