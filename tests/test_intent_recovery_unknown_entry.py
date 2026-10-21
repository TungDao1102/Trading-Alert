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
from pathlib import Path

import pytest
from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.domain.stream_records import UNKNOWN_EXIT_EVIDENCE
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from src.execution.intent_recovery import (
    EVENT_UNKNOWN_ENTRY_PROBE,
    UnknownEntryResolver,
)
from src.execution.intent_store import RESOLUTION_RECONCILED_ABSENT, IntentRecord

from tests.support.execution_limits import TEST_ONLY_EXECUTION_LIMIT_VALUES
from tests.support.execution_limits import test_only_execution_limits as make_limits
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.reconcile_doubles import RecordingJournal
from tests.test_intent_recovery import (
    NOW,
    SYMBOL,
    _entry_id,
    _row,
    _seed_entry,
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
