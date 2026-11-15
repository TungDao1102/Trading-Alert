"""UNKNOWN ENTRY recovery by evidence (Phase 20, plan 20-10, T-C, D-11, D-12, Q5).

An ENTRY intent that went UNKNOWN after an ambiguous send is closed only by the full protocol of
`UnknownEntryResolver`: `reconcile.entry_unknown_probe_count` consecutive clean `found=False`
probes by client order id (spaced by `reconcile.entry_unknown_probe_interval_ms`), the GTD time plus
`protection.entry_unknown_grace_ms` passed, and a fresh positions read and a fresh open-orders read
for the symbol that show no exposure and no open order, every step journaled with the evidence
source REST_RECONCILE. The terminal status is REJECTED with the reason RECONCILED_ABSENT through
`finalize_reconciled_resolution`. Any other outcome keeps the intent UNKNOWN (and SAFE_MODE).

Fakes only: no Binance call. The limits are the TEST_ONLY values of plan 20-01 (count 3, interval
2345 ms, grace 9191 ms); they are not the owner's choice (O-G). Evidence labels: executed tests with
fakes; Binance id visibility is [DOC]; Phase 19 assumption A2 (a GTD expiry is terminal) stays
[NOT_TESTED]; nothing here is [DEMO].
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.domain.journal import JournalEvent
from src.domain.stream_records import UNKNOWN_EXIT_EVIDENCE
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from src.execution.intent_recovery import (
    EVENT_UNKNOWN_ENTRY_KEPT,
    EVENT_UNKNOWN_ENTRY_PROBE,
    UnknownEntryResolver,
    resolve_unresolved_intents,
)
from src.execution.intent_store import (
    RESOLUTION_NEVER_SENT,
    RESOLUTION_RECONCILED_ABSENT,
    IntentRecord,
)
from src.persistence.errors import IntentStateConflict, StoreUnavailable

from tests.support.execution_limits import TEST_ONLY_EXECUTION_LIMIT_VALUES
from tests.support.execution_limits import test_only_execution_limits as make_limits
from tests.support.fake_binance_exchange import (
    STATUS_NEW,
    BinanceSemanticsFakeAdapter,
    ExchangeOrderRecord,
)
from tests.support.intent_store_fakes import FailingIntentStore, InMemoryExecutionIntentStore
from tests.support.reconcile_doubles import RecordingJournal
from tests.test_intent_recovery import (
    NOW,
    SYMBOL,
    RecordingSafeModeController,
    _entry_id,
    _exchange_holds_entry,
    _exchange_holds_stop_loss,
    _no_orders_placed,
    _row,
    _seed_entry,
    _seed_stop_loss,
)

ENTRY = OrderRole.ENTRY.value
UNKNOWN = ExecutionIntentStatus.UNKNOWN
REJECTED = ExecutionIntentStatus.REJECTED

PROBE_COUNT = TEST_ONLY_EXECUTION_LIMIT_VALUES["reconcile.entry_unknown_probe_count"]
INTERVAL = timedelta(
    milliseconds=TEST_ONLY_EXECUTION_LIMIT_VALUES["reconcile.entry_unknown_probe_interval_ms"]
)
GRACE = timedelta(
    milliseconds=TEST_ONLY_EXECUTION_LIMIT_VALUES["protection.entry_unknown_grace_ms"]
)
GOOD_TILL = NOW + timedelta(hours=1)
AFTER_GRACE = GOOD_TILL + GRACE + INTERVAL

# The only adapter methods the resolver may call: the two probes' ENTRY half and the two reads.
ALLOWED_ADAPTER_CALLS = {
    "query_order_by_client",
    "snapshot_positions",
    "snapshot_open_normal_orders",
}


class SafeModeSpy:
    """Records every SAFE_MODE entry and every exit attempt (closing an intent must not exit)."""

    def __init__(self) -> None:
        self.entered: list[str] = []
        self.exit_attempts = 0

    def enter_safe_mode(self, *, reason: str, now_utc: datetime | None = None) -> None:
        self.entered.append(reason)

    def exit_safe_mode(self, **_kwargs: object) -> None:
        self.exit_attempts += 1


def _good_till(_record: IntentRecord) -> datetime | None:
    return GOOD_TILL


def _make(
    *,
    store: InMemoryExecutionIntentStore | None = None,
    adapter: BinanceSemanticsFakeAdapter | None = None,
    journal: RecordingJournal | None = None,
    safe_mode: SafeModeSpy | None = None,
) -> tuple[
    UnknownEntryResolver,
    InMemoryExecutionIntentStore,
    BinanceSemanticsFakeAdapter,
    RecordingJournal,
    SafeModeSpy,
]:
    store = store if store is not None else InMemoryExecutionIntentStore()
    adapter = adapter if adapter is not None else BinanceSemanticsFakeAdapter(now_utc=NOW)
    journal = journal if journal is not None else RecordingJournal()
    safe_mode = safe_mode if safe_mode is not None else SafeModeSpy()
    resolver = UnknownEntryResolver(
        store=store,
        adapter=adapter,
        journal=journal,
        safe_mode_controller=safe_mode,
        limits=make_limits(),
        entry_good_till=_good_till,
    )
    return resolver, store, adapter, journal, safe_mode


def _events(journal: RecordingJournal, event_type: str) -> list[dict[str, str]]:
    return [json.loads(e.payload_json) for e in journal.events if e.event_type == event_type]


async def test_full_protocol_closes_with_reconciled_absent() -> None:
    resolver, store, adapter, journal, safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)

    # Three clean probes spaced by the interval, but GTD + grace has not passed: no close, and the
    # exchange reads that prove flatness are not even made yet.
    for step in range(PROBE_COUNT):
        report = await resolver.step(now_utc=NOW + step * INTERVAL)
        assert report.closed == ()
        assert _row(store, approval_id, ENTRY).intent_status == UNKNOWN
    assert adapter.calls_to("snapshot_positions") == []
    assert adapter.calls_to("snapshot_open_normal_orders") == []
    assert len(_events(journal, EVENT_UNKNOWN_ENTRY_PROBE)) == PROBE_COUNT
    assert _events(journal, UNKNOWN_EXIT_EVIDENCE) == []

    # GTD + grace has passed and the next spaced probe is clean: the protocol closes the intent.
    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.closed == (approval_id,)
    row = _row(store, approval_id, ENTRY)
    assert row.intent_status == REJECTED
    assert row.resolution_reason_code == RESOLUTION_RECONCILED_ABSENT
    assert row.exchange_status is None
    assert row.exchange_order_id is None

    probes = _events(journal, EVENT_UNKNOWN_ENTRY_PROBE)
    assert [p["probe_no"] for p in probes] == [str(n) for n in range(1, PROBE_COUNT + 2)]
    assert {p["evidence_source"] for p in probes} == {"REST_RECONCILE"}
    assert {p["approval_id"] for p in probes} == {approval_id}
    evidence_rows = [e for e in journal.events if e.event_type == UNKNOWN_EXIT_EVIDENCE]
    assert len(evidence_rows) == 1
    assert evidence_rows[0].entity_type == "EXECUTION_INTENT"
    assert evidence_rows[0].entity_id == approval_id
    payload = json.loads(evidence_rows[0].payload_json)
    assert payload["evidence_source"] == "REST_RECONCILE"
    assert payload["from_status"] == "UNKNOWN"
    assert payload["to_status"] == "REJECTED"
    assert payload["reference"] == _entry_id(1)

    # Only the probe and the two reads were used; nothing was placed, cancelled or exited.
    assert {c["method"] for c in adapter.calls} <= ALLOWED_ADAPTER_CALLS
    assert adapter.calls_to("snapshot_positions")[-1]["kwargs"] == {"symbol": SYMBOL}
    assert adapter.calls_to("snapshot_open_normal_orders")[-1]["kwargs"] == {"symbol": SYMBOL}
    assert safe_mode.exit_attempts == 0


def test_recovery_module_has_no_place_or_cancel_call() -> None:
    source = Path("src/execution/intent_recovery.py").read_text(encoding="utf-8")
    called = {
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {name for name in called if name.startswith(("place_", "cancel_"))} == set()


def test_the_resolver_refuses_unset_limits() -> None:
    for field in (
        "reconcile_entry_unknown_probe_count",
        "reconcile_entry_unknown_probe_interval_ms",
        "entry_unknown_grace_ms",
    ):
        with pytest.raises(ExecutionLimitsNotConfigured):
            UnknownEntryResolver(
                store=InMemoryExecutionIntentStore(),
                adapter=BinanceSemanticsFakeAdapter(now_utc=NOW),
                journal=RecordingJournal(),
                safe_mode_controller=SafeModeSpy(),
                limits=make_limits(**{field: None}),
                entry_good_till=_good_till,
            )


# --------------------------------------------------------------------------- #
# Task 3: every failure keeps UNKNOWN (D-11).
# --------------------------------------------------------------------------- #


class SelectiveRaisingJournal(RecordingJournal):
    """Raises `StoreUnavailable` for the listed event types, records everything else."""

    def __init__(self, *event_types: str) -> None:
        super().__init__()
        self._raise_on = set(event_types)

    def record(self, event: JournalEvent) -> None:
        if event.event_type in self._raise_on:
            self.attempts += 1
            raise StoreUnavailable("journal unavailable")
        super().record(event)


async def _prime(resolver: UnknownEntryResolver, probes: int) -> None:
    """`probes` clean probes, spaced by the interval, all before GTD + grace."""
    for index in range(probes):
        report = await resolver.step(now_utc=NOW + index * INTERVAL)
        assert report.closed == ()


def _status(store: InMemoryExecutionIntentStore, approval_id: str) -> ExecutionIntentStatus:
    return _row(store, approval_id, ENTRY).intent_status


async def _still_unknown_and_count_reset(
    resolver: UnknownEntryResolver, store: InMemoryExecutionIntentStore, approval_id: str
) -> None:
    """After a failure the count restarts: the next due step after GTD + grace cannot close."""
    assert _status(store, approval_id) == UNKNOWN
    later = await resolver.step(now_utc=AFTER_GRACE + INTERVAL)
    assert later.closed == ()
    assert _status(store, approval_id) == UNKNOWN


async def test_a_probe_error_keeps_unknown_and_resets_the_count() -> None:
    resolver, store, adapter, _journal, safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)
    await _prime(resolver, PROBE_COUNT - 1)
    adapter.fail_next("query_order_by_client", RuntimeError("-1003 too many requests"))

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.closed == ()
    assert report.kept == ((approval_id, "PROBE_INDETERMINATE"),)
    assert safe_mode.entered[-1] == "UNRESOLVED_EXECUTION_INTENT"
    await _still_unknown_and_count_reset(resolver, store, approval_id)


async def test_an_indeterminate_probe_answer_keeps_unknown_and_resets_the_count() -> None:
    class IndeterminateAdapter(BinanceSemanticsFakeAdapter):
        async def query_order_by_client(self, **kwargs: Any) -> Any:
            await super().query_order_by_client(**kwargs)
            return {"found": "maybe"}

    resolver, store, _adapter, _journal, _safe_mode = _make(
        adapter=IndeterminateAdapter(now_utc=NOW)
    )
    approval_id = _seed_entry(store, status=UNKNOWN)

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.kept == ((approval_id, "PROBE_INDETERMINATE"),)
    await _still_unknown_and_count_reset(resolver, store, approval_id)


async def test_fewer_clean_probes_than_the_count_never_close() -> None:
    resolver, store, adapter, _journal, _safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)

    for index in range(PROBE_COUNT - 1):
        report = await resolver.step(now_utc=AFTER_GRACE + index * INTERVAL)
        assert report.closed == ()
        assert _status(store, approval_id) == UNKNOWN
    # The count-th clean probe, with GTD + grace long passed, closes it.
    last = await resolver.step(now_utc=AFTER_GRACE + (PROBE_COUNT - 1) * INTERVAL)
    assert last.closed == (approval_id,)
    assert len(adapter.calls_to("query_order_by_client")) == PROBE_COUNT


@pytest.mark.parametrize(("offset_ms", "closes"), [(-1, False), (0, True)])
async def test_the_gtd_plus_grace_boundary_is_inclusive(offset_ms: int, closes: bool) -> None:
    resolver, store, _adapter, _journal, _safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)
    await _prime(resolver, PROBE_COUNT - 1)

    report = await resolver.step(now_utc=GOOD_TILL + GRACE + timedelta(milliseconds=offset_ms))

    assert (report.closed == (approval_id,)) is closes
    assert _status(store, approval_id) == (REJECTED if closes else UNKNOWN)


async def test_a_probe_before_the_interval_has_passed_is_not_made() -> None:
    resolver, store, adapter, _journal, _safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)

    await resolver.step(now_utc=NOW)
    report = await resolver.step(now_utc=NOW + INTERVAL - timedelta(milliseconds=1))

    assert report.kept == ((approval_id, "NOT_DUE"),)
    assert len(adapter.calls_to("query_order_by_client")) == 1


async def test_without_a_gtd_time_nothing_is_closed() -> None:
    resolver, store, _adapter, _journal, _safe_mode = _make()
    resolver._entry_good_till = lambda _record: None  # type: ignore[assignment]
    approval_id = _seed_entry(store, status=UNKNOWN)

    for index in range(PROBE_COUNT + 2):
        report = await resolver.step(now_utc=AFTER_GRACE + index * INTERVAL)
        assert report.closed == ()
    assert _status(store, approval_id) == UNKNOWN
    assert report.kept == ((approval_id, "GTD_UNKNOWN"),)


async def test_a_failing_gtd_lookup_keeps_unknown() -> None:
    def broken(_record: IntentRecord) -> datetime | None:
        raise RuntimeError("no plan")

    resolver, store, _adapter, _journal, _safe_mode = _make()
    resolver._entry_good_till = broken  # type: ignore[assignment]
    approval_id = _seed_entry(store, status=UNKNOWN)
    await _prime(resolver, PROBE_COUNT - 1)

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.kept == ((approval_id, "GTD_UNKNOWN"),)
    assert _status(store, approval_id) == UNKNOWN


@pytest.mark.parametrize("method", ["snapshot_positions", "snapshot_open_normal_orders"])
async def test_a_failed_read_keeps_unknown_and_resets_the_count(method: str) -> None:
    resolver, store, adapter, _journal, _safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)
    await _prime(resolver, PROBE_COUNT - 1)
    adapter.fail_next(method, RuntimeError("-1003 too many requests"))

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.closed == ()
    assert report.kept == ((approval_id, "READ_FAILED"),)
    await _still_unknown_and_count_reset(resolver, store, approval_id)


async def test_a_non_zero_position_keeps_unknown() -> None:
    resolver, store, adapter, journal, _safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)
    adapter.positions[SYMBOL] = Decimal("0.001")
    await _prime(resolver, PROBE_COUNT - 1)

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.kept == ((approval_id, "EXPOSURE_PRESENT"),)
    assert _events(journal, EVENT_UNKNOWN_ENTRY_KEPT)[-1]["reason"] == "EXPOSURE_PRESENT"
    await _still_unknown_and_count_reset(resolver, store, approval_id)


async def test_an_open_order_on_the_symbol_keeps_unknown() -> None:
    resolver, store, adapter, _journal, _safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)
    adapter.open_orders["x-other"] = ExchangeOrderRecord(
        client_id="x-other",
        symbol=SYMBOL,
        status=STATUS_NEW,
        created_at_utc=NOW,
        exchange_id="ex-other",
    )
    await _prime(resolver, PROBE_COUNT - 1)

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.kept == ((approval_id, "OPEN_ORDER_PRESENT"),)
    await _still_unknown_and_count_reset(resolver, store, approval_id)


async def test_a_conflicting_read_keeps_unknown() -> None:
    """The probe says not found, the open-orders read shows the very order: conflict, no close."""

    class DeniesTheOrderAdapter(BinanceSemanticsFakeAdapter):
        async def query_order_by_client(self, **kwargs: Any) -> Any:
            await super().query_order_by_client(**kwargs)
            return {"found": False}

    adapter = DeniesTheOrderAdapter(now_utc=NOW)
    _exchange_holds_entry(adapter)
    resolver, store, _adapter, _journal, _safe_mode = _make(adapter=adapter)
    approval_id = _seed_entry(store, status=UNKNOWN)
    await _prime(resolver, PROBE_COUNT - 1)

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.kept == ((approval_id, "OPEN_ORDER_PRESENT"),)
    assert _status(store, approval_id) == UNKNOWN


@pytest.mark.parametrize("bad", ["not a list", None, [{"symbol": None}]])
async def test_an_unreadable_snapshot_answer_keeps_unknown(bad: Any) -> None:
    class BadSnapshotAdapter(BinanceSemanticsFakeAdapter):
        async def snapshot_positions(self, **kwargs: Any) -> Any:
            return bad

    resolver, store, _adapter, _journal, _safe_mode = _make(adapter=BadSnapshotAdapter(now_utc=NOW))
    approval_id = _seed_entry(store, status=UNKNOWN)
    await _prime(resolver, PROBE_COUNT - 1)

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.kept == ((approval_id, "READ_INDETERMINATE"),)
    assert _status(store, approval_id) == UNKNOWN


async def test_a_failing_evidence_journal_write_finalizes_nothing() -> None:
    journal = SelectiveRaisingJournal(UNKNOWN_EXIT_EVIDENCE)
    resolver, store, _adapter, _journal, _safe_mode = _make(journal=journal)
    approval_id = _seed_entry(store, status=UNKNOWN)
    await _prime(resolver, PROBE_COUNT - 1)

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.closed == ()
    assert report.kept == ((approval_id, "JOURNAL_FAILED"),)
    assert _row(store, approval_id, ENTRY).resolution_reason_code is None
    await _still_unknown_and_count_reset(resolver, store, approval_id)


async def test_a_failing_probe_journal_write_keeps_unknown_without_the_reads() -> None:
    journal = SelectiveRaisingJournal(EVENT_UNKNOWN_ENTRY_PROBE)
    resolver, store, adapter, _journal, _safe_mode = _make(journal=journal)
    approval_id = _seed_entry(store, status=UNKNOWN)

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.kept == ((approval_id, "JOURNAL_FAILED"),)
    assert adapter.calls_to("snapshot_positions") == []
    assert _status(store, approval_id) == UNKNOWN


async def test_a_failing_finalization_leaves_the_intent_unknown() -> None:
    inner = InMemoryExecutionIntentStore()
    failing = FailingIntentStore(
        "finalize_reconciled_resolution", IntentStateConflict("boom"), inner=inner
    )
    resolver, _store, _adapter, _journal, safe_mode = _make(store=failing)  # type: ignore[arg-type]
    approval_id = _seed_entry(inner, status=UNKNOWN)
    await _prime(resolver, PROBE_COUNT - 1)

    report = await resolver.step(now_utc=AFTER_GRACE)

    assert report.closed == ()
    assert report.kept == ((approval_id, "STORE_FAILED"),)
    assert failing.failures_raised == 1
    assert _status(inner, approval_id) == UNKNOWN
    assert safe_mode.entered[-1] == "UNRESOLVED_EXECUTION_INTENT"


async def test_a_found_order_becomes_acked_with_journaled_evidence() -> None:
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    exchange_order_id = _exchange_holds_entry(adapter)
    resolver, store, _adapter, journal, safe_mode = _make(adapter=adapter)
    approval_id = _seed_entry(store, status=UNKNOWN)

    report = await resolver.step(now_utc=NOW)

    assert report.acked == (approval_id,)
    row = _row(store, approval_id, ENTRY)
    assert row.intent_status == ExecutionIntentStatus.ACKED
    assert row.exchange_order_id == exchange_order_id
    evidence_rows = [json.loads(e.payload_json) for e in journal.events]
    assert [r["to_status"] for r in evidence_rows] == ["ACKED"]
    assert evidence_rows[0]["evidence_source"] == "REST_RECONCILE"
    assert safe_mode.entered == [] and safe_mode.exit_attempts == 0


async def test_a_restart_starts_the_count_again_at_zero() -> None:
    first, store, adapter, journal, safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)
    await _prime(first, PROBE_COUNT - 1)
    restarted = UnknownEntryResolver(
        store=store,
        adapter=adapter,
        journal=journal,
        safe_mode_controller=safe_mode,
        limits=make_limits(),
        entry_good_till=_good_till,
    )

    report = await restarted.step(now_utc=AFTER_GRACE)

    assert report.closed == ()
    assert _status(store, approval_id) == UNKNOWN


async def test_an_unreadable_store_enters_db_failure_and_propagates() -> None:
    inner = InMemoryExecutionIntentStore()
    failing = FailingIntentStore("list_unresolved_intents", StoreUnavailable("down"), inner=inner)
    resolver, _store, adapter, _journal, safe_mode = _make(store=failing)  # type: ignore[arg-type]

    with pytest.raises(StoreUnavailable):
        await resolver.step(now_utc=NOW)

    assert safe_mode.entered == ["DB_FAILURE"]
    assert adapter.calls == []


async def test_a_naive_now_is_refused_before_any_work() -> None:
    resolver, store, adapter, _journal, _safe_mode = _make()
    _seed_entry(store, status=UNKNOWN)

    with pytest.raises(ValueError, match="UTC"):
        await resolver.step(now_utc=datetime(2026, 9, 19, 10, 30))

    assert adapter.calls == []


async def test_only_unknown_entries_are_touched() -> None:
    resolver, store, adapter, _journal, _safe_mode = _make()
    _seed_entry(store, index=1, status=ExecutionIntentStatus.SENT)
    _seed_entry(store, index=2, status=ExecutionIntentStatus.ACKED)
    _seed_entry(store, index=3, status=REJECTED)

    report = await resolver.step(now_utc=NOW)

    assert report == type(report)(closed=(), acked=(), kept=(), safe_mode_entered=False)
    assert adapter.calls == []


# --------------------------------------------------------------------------- #
# resolve_unresolved_intents: no absence-alone conclusion for an entry (D-11, Q5, F5).
# --------------------------------------------------------------------------- #


async def test_a_sent_entry_absent_and_young_stays_unknown() -> None:
    """Q5 / D-11: the 3-day rule no longer turns an absent SENT entry into REJECTED."""
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW + timedelta(hours=1))
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=ExecutionIntentStatus.SENT, at=NOW)

    report = await resolve_unresolved_intents(
        store=store,
        adapter=adapter,
        safe_mode_controller=safe_mode,
        now_utc=NOW + timedelta(hours=1),
    )

    assert _status(store, approval_id) == UNKNOWN
    assert report.unresolved == ((approval_id, ENTRY, UNKNOWN),)
    assert report.safe_mode_entered is True
    assert [reason for reason, _now in safe_mode.entered] == ["UNRESOLVED_EXECUTION_INTENT"]
    _no_orders_placed(adapter)


async def test_an_unknown_entry_absent_and_young_stays_unknown() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=UNKNOWN)

    await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert _status(store, approval_id) == UNKNOWN


async def test_an_intended_entry_absent_is_rejected_as_never_sent() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=ExecutionIntentStatus.INTENDED)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    row = _row(store, approval_id, ENTRY)
    assert row.intent_status == REJECTED
    assert row.resolution_reason_code == RESOLUTION_NEVER_SENT
    assert row.exchange_status is None
    assert report.resolved == ((approval_id, ENTRY, REJECTED),)
    assert safe_mode.entered == []
    assert len(adapter.calls_to("query_order_by_client")) == 1  # exactly one probe
    _no_orders_placed(adapter)


async def test_an_intended_entry_found_becomes_acked() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=ExecutionIntentStatus.INTENDED)
    exchange_order_id = _exchange_holds_entry(adapter)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    row = _row(store, approval_id, ENTRY)
    assert row.intent_status == ExecutionIntentStatus.ACKED
    assert row.exchange_order_id == exchange_order_id
    assert row.resolution_reason_code is None
    assert report.resolved == ((approval_id, ENTRY, ExecutionIntentStatus.ACKED),)
    _no_orders_placed(adapter)


async def test_an_intended_entry_whose_probe_errors_becomes_unknown() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    adapter.fail_next("query_order_by_client", RuntimeError("timeout"))
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=ExecutionIntentStatus.INTENDED)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert _status(store, approval_id) == UNKNOWN
    assert report.unresolved == ((approval_id, ENTRY, UNKNOWN),)
    assert len(safe_mode.entered) == 1


async def test_an_intended_entry_whose_finalization_fails_stays_unresolved() -> None:
    inner = InMemoryExecutionIntentStore()
    failing = FailingIntentStore(
        "finalize_reconciled_resolution", IntentStateConflict("boom"), inner=inner
    )
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(inner, status=ExecutionIntentStatus.INTENDED)

    report = await resolve_unresolved_intents(
        store=failing, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert report.resolved == ()
    assert [(a, r) for a, r, _s in report.unresolved] == [(approval_id, ENTRY)]
    assert _row(inner, approval_id, ENTRY).intent_status != REJECTED
    assert len(safe_mode.entered) == 1


async def test_f5_a_young_absent_stop_loss_of_a_live_entry_is_never_rejected() -> None:
    """Research F5: the coordinator rebuilds the stop of a plan whose ENTRY is not REJECTED."""
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=ExecutionIntentStatus.ACKED)
    _seed_stop_loss(store, status=ExecutionIntentStatus.SENT)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    leg = _row(store, approval_id, OrderRole.STOP_LOSS.value)
    assert leg.intent_status == UNKNOWN
    assert report.unresolved == ((approval_id, OrderRole.STOP_LOSS.value, UNKNOWN),)
    assert len(safe_mode.entered) == 1
    _no_orders_placed(adapter)


async def test_f5_a_young_absent_stop_loss_of_an_unknown_entry_stays_unknown() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    approval_id = _seed_entry(store, status=UNKNOWN)
    _seed_stop_loss(store, status=ExecutionIntentStatus.SENT)

    await resolve_unresolved_intents(
        store=store,
        adapter=adapter,
        safe_mode_controller=RecordingSafeModeController(),
        now_utc=NOW,
    )

    assert _row(store, approval_id, OrderRole.STOP_LOSS.value).intent_status == UNKNOWN


async def test_f5_the_stop_loss_of_a_rejected_entry_keeps_the_existing_young_absent_rule() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=REJECTED)
    _seed_stop_loss(store, status=ExecutionIntentStatus.SENT)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert _row(store, approval_id, OrderRole.STOP_LOSS.value).intent_status == REJECTED
    assert report.resolved == ((approval_id, OrderRole.STOP_LOSS.value, REJECTED),)
    assert safe_mode.entered == []


async def test_f5_a_stop_loss_whose_entry_cannot_be_read_is_not_rejected() -> None:
    inner = InMemoryExecutionIntentStore()
    failing = FailingIntentStore("get_entry", StoreUnavailable("down"), inner=inner)
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(inner, status=REJECTED)
    _seed_stop_loss(inner, status=ExecutionIntentStatus.SENT)

    await resolve_unresolved_intents(
        store=failing, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert _row(inner, approval_id, OrderRole.STOP_LOSS.value).intent_status == UNKNOWN


async def test_f5_a_found_stop_loss_is_acked_whatever_the_entry_status() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    approval_id = _seed_entry(store, status=UNKNOWN)
    _seed_stop_loss(store, status=ExecutionIntentStatus.SENT)
    _exchange_holds_stop_loss(adapter)

    await resolve_unresolved_intents(
        store=store,
        adapter=adapter,
        safe_mode_controller=RecordingSafeModeController(),
        now_utc=NOW,
    )

    leg = _row(store, approval_id, OrderRole.STOP_LOSS.value)
    assert leg.intent_status == ExecutionIntentStatus.ACKED


# --------------------------------------------------------------------------- #
# 20-REVIEW WR-A1 (plan 20-27): a retry after a failed finalize write must not collide with the
# evidence row of the first attempt. `RecordingJournal` applies the real replay rule (the same
# journal id with a different identity field is a JournalConflict), as PgJournalStore does.
# --------------------------------------------------------------------------- #


class _FailsOnce(InMemoryExecutionIntentStore):
    """The named store method raises `StoreUnavailable` on its first call, then works."""

    def __init__(self, method_name: str) -> None:
        super().__init__()
        self._method_name = method_name
        self.failed = 0

    def _maybe_fail(self, name: str) -> None:
        if name == self._method_name and self.failed == 0:
            self.failed += 1
            raise StoreUnavailable("store blip")

    def finalize_reconciled_resolution(self, **kwargs: Any) -> None:
        self._maybe_fail("finalize_reconciled_resolution")
        super().finalize_reconciled_resolution(**kwargs)

    def record_result(self, **kwargs: Any) -> Any:
        if kwargs.get("status") == ExecutionIntentStatus.ACKED:
            self._maybe_fail("record_result")
        return super().record_result(**kwargs)


async def test_a_retry_after_a_failed_finalize_write_closes_without_a_journal_conflict() -> None:
    store = _FailsOnce("finalize_reconciled_resolution")
    resolver, _store, _adapter, journal, _safe_mode = _make(store=store)
    approval_id = _seed_entry(store, status=UNKNOWN)
    await _prime(resolver, PROBE_COUNT - 1)

    first = await resolver.step(now_utc=AFTER_GRACE)  # evidence row written, finalize fails
    assert first.kept == ((approval_id, "STORE_FAILED"),)
    assert [e.event_type for e in journal.events].count(UNKNOWN_EXIT_EVIDENCE) == 1
    assert _status(store, approval_id) == UNKNOWN

    # The count restarts after a failure: PROBE_COUNT clean probes, then the closing step, each
    # at its own (later) clock value. The evidence row of the closing step carries a new
    # observation time; its journal identity must not collide with the first attempt's row.
    later = AFTER_GRACE + INTERVAL
    report = None
    for step_no in range(PROBE_COUNT):
        report = await resolver.step(now_utc=later + step_no * INTERVAL)

    assert report is not None
    assert report.kept == ()
    assert report.closed == (approval_id,)
    row = _row(store, approval_id, ENTRY)
    assert row.intent_status == REJECTED
    assert row.resolution_reason_code == RESOLUTION_RECONCILED_ABSENT
    evidence = [e for e in journal.events if e.event_type == UNKNOWN_EXIT_EVIDENCE]
    assert len(evidence) == 2  # one row per observation; append-only, nothing is overwritten
    assert len({e.journal_event_id for e in evidence}) == 2
    for row_event in evidence:
        payload = json.loads(row_event.payload_json)
        assert payload["evidence_source"] == "REST_RECONCILE"
        assert payload["from_status"] == "UNKNOWN"
        assert payload["to_status"] == "REJECTED"
        assert payload["reference"] == _entry_id(1)
        assert "observed_at_utc" in payload
        assert row_event.entity_id == approval_id
        assert row_event.correlation_id == f"unknown-entry:{approval_id}"


async def test_a_retry_after_a_failed_ack_write_acks_without_a_journal_conflict() -> None:
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    exchange_order_id = _exchange_holds_entry(adapter)
    store = _FailsOnce("record_result")
    resolver, _store, _adapter, journal, _safe_mode = _make(store=store, adapter=adapter)
    approval_id = _seed_entry(store, status=UNKNOWN)

    first = await resolver.step(now_utc=NOW)  # evidence row written, the ACKED write fails
    assert first.kept == ((approval_id, "STORE_FAILED"),)
    assert _status(store, approval_id) == UNKNOWN

    second = await resolver.step(now_utc=NOW + INTERVAL)

    assert second.acked == (approval_id,)
    assert second.kept == ()
    row = _row(store, approval_id, ENTRY)
    assert row.intent_status == ExecutionIntentStatus.ACKED
    assert row.exchange_order_id == exchange_order_id
    assert [e.event_type for e in journal.events].count(UNKNOWN_EXIT_EVIDENCE) == 2


async def test_the_same_observation_replayed_is_one_evidence_row() -> None:
    """A byte-identical evidence event (same observation time) is the same journal id: a replay."""
    resolver, store, _adapter, journal, _safe_mode = _make()
    approval_id = _seed_entry(store, status=UNKNOWN)
    record = store.get_entry(approval_id=approval_id)
    assert record is not None

    first = resolver._exit_event(record, "REJECTED", AFTER_GRACE)  # noqa: SLF001
    second = resolver._exit_event(record, "REJECTED", AFTER_GRACE)  # noqa: SLF001
    journal.record(first)
    journal.record(second)

    assert first.journal_event_id == second.journal_event_id
    assert len(journal.events) == 1
