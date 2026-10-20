"""Restart recovery of in-flight execution intents (Phase 17-12, D-14, F-703, Pitfall 11).

After a restart every intent left INTENDED or SENT is first recorded UNKNOWN, then
resolved ONLY by querying the exchange by its deterministic client id:

  found                                   -> ACKED
  definitively absent, younger than 3 d   -> REJECTED
  probe error / indeterminate / too old   -> stays UNKNOWN, and SAFE_MODE is entered

Recovery never places an order: the Binance-semantics fake counts `place_entry` and
`place_algo_protective` calls and every case asserts both stay at zero.

These tests use the in-memory store; the PostgreSQL proof is `test_intent_recovery_pg.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.execution.intent_recovery import RecoveryReport, resolve_unresolved_intents
from src.execution.intent_store import IntentRecord
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.persistence.errors import IntentStateConflict

from tests.support.fake_binance_exchange import (
    HISTORY_RETENTION,
    STATUS_NEW,
    BinanceSemanticsFakeAdapter,
    ExchangeOrderRecord,
)
from tests.support.intent_store_fakes import FailingIntentStore, InMemoryExecutionIntentStore

NOW = datetime(2026, 9, 19, 10, 30, tzinfo=UTC)
SYMBOL = "BTCUSDT"
PLAN_HASH = "ab" * 32

ENTRY = OrderRole.ENTRY.value
STOP_LOSS = OrderRole.STOP_LOSS.value
UNKNOWN = ExecutionIntentStatus.UNKNOWN
ACKED = ExecutionIntentStatus.ACKED
REJECTED = ExecutionIntentStatus.REJECTED
INTENDED = ExecutionIntentStatus.INTENDED
SENT = ExecutionIntentStatus.SENT


class RecordingSafeModeController:
    """Duck-typed controller recording every SAFE_MODE entry."""

    def __init__(self) -> None:
        self.entered: list[tuple[str, datetime | None]] = []

    def enter_safe_mode(self, *, reason: str, now_utc: datetime | None = None) -> None:
        self.entered.append((reason, now_utc))


def _plan_hash(index: int) -> str:
    return f"{index:02x}" * 32


def _entry_id(index: int) -> str:
    return derive_client_order_id(plan_hash=_plan_hash(index), role=ENTRY)


def _sl_id(index: int) -> str:
    return derive_algo_client_id(plan_hash=_plan_hash(index), role=STOP_LOSS)


def _seed_entry(
    store: InMemoryExecutionIntentStore,
    *,
    index: int = 1,
    status: ExecutionIntentStatus = SENT,
    at: datetime = NOW,
) -> str:
    """Write one ENTRY intent for approval `appr-<index>` up to `status`; returns its id."""
    approval_id = f"appr-{index}"
    assert store.consume_and_record_entry_intent(
        approval_id=approval_id,
        trade_plan_id=f"plan-{index}",
        plan_hash=_plan_hash(index),
        client_order_id=_entry_id(index),
        symbol=SYMBOL,
        side="BUY",
        intended_quantity=Decimal("1"),
        intended_price=Decimal("100"),
        approved_quantity=Decimal("1"),
        now_utc=at,
    )
    if status != INTENDED:
        store.mark_sent(approval_id=approval_id, role=ENTRY, now_utc=at)
    if status in (UNKNOWN, ACKED, REJECTED):
        store.record_result(
            approval_id=approval_id,
            role=ENTRY,
            status=status,
            exchange_order_id=None,
            exchange_status=None,
            now_utc=at,
        )
    return approval_id


def _seed_stop_loss(
    store: InMemoryExecutionIntentStore,
    *,
    index: int = 1,
    status: ExecutionIntentStatus = SENT,
    at: datetime = NOW,
) -> None:
    approval_id = f"appr-{index}"
    assert store.record_protective_intent(
        approval_id=approval_id,
        role=STOP_LOSS,
        trade_plan_id=f"plan-{index}",
        plan_hash=_plan_hash(index),
        algo_client_id=_sl_id(index),
        symbol=SYMBOL,
        side="SELL",
        intended_price=Decimal("98"),
        now_utc=at,
    )
    if status != INTENDED:
        store.mark_sent(approval_id=approval_id, role=STOP_LOSS, now_utc=at)
    if status in (UNKNOWN, ACKED, REJECTED):
        store.record_result(
            approval_id=approval_id,
            role=STOP_LOSS,
            status=status,
            exchange_order_id=None,
            exchange_status=None,
            now_utc=at,
        )


def _exchange_holds_entry(adapter: BinanceSemanticsFakeAdapter, index: int = 1) -> str:
    """Put the order on the fake exchange WITHOUT going through `place_entry`."""
    client_id = _entry_id(index)
    adapter.open_orders[client_id] = ExchangeOrderRecord(
        client_id=client_id,
        symbol=SYMBOL,
        status=STATUS_NEW,
        created_at_utc=NOW,
        exchange_id=f"ex-held-{index}",
    )
    return f"ex-held-{index}"


def _exchange_holds_stop_loss(adapter: BinanceSemanticsFakeAdapter, index: int = 1) -> None:
    client_id = _sl_id(index)
    adapter.open_algos[client_id] = ExchangeOrderRecord(
        client_id=client_id,
        symbol=SYMBOL,
        status=STATUS_NEW,
        created_at_utc=NOW,
        exchange_id=f"algo-held-{index}",
    )


def _no_orders_placed(adapter: BinanceSemanticsFakeAdapter) -> None:
    assert adapter.calls_to("place_entry") == []
    assert adapter.calls_to("place_algo_protective") == []


def _row(store: InMemoryExecutionIntentStore, approval_id: str, role: str) -> IntentRecord:
    row = store.get_intent(approval_id=approval_id, role=role)
    assert row is not None
    return row


# --------------------------------------------------------------------------- #
# list_unresolved_intents.
# --------------------------------------------------------------------------- #


def test_list_unresolved_returns_intended_sent_unknown_in_deterministic_order() -> None:
    store = InMemoryExecutionIntentStore()
    # Seeded out of order on purpose: ordering is intended_at_utc, approval_id, role.
    _seed_entry(store, index=3, status=INTENDED, at=NOW + timedelta(minutes=2))
    _seed_entry(store, index=2, status=SENT, at=NOW + timedelta(minutes=1))
    _seed_stop_loss(store, index=2, status=INTENDED, at=NOW + timedelta(minutes=1))
    _seed_entry(store, index=1, status=UNKNOWN, at=NOW)
    _seed_entry(store, index=4, status=ACKED, at=NOW - timedelta(minutes=1))
    _seed_entry(store, index=5, status=REJECTED, at=NOW - timedelta(minutes=2))

    listed = store.list_unresolved_intents()

    assert [(r.approval_id, r.role, r.intent_status) for r in listed] == [
        ("appr-1", ENTRY, UNKNOWN),
        ("appr-2", ENTRY, SENT),
        ("appr-2", STOP_LOSS, INTENDED),
        ("appr-3", ENTRY, INTENDED),
    ]


def test_list_unresolved_is_empty_when_every_intent_is_terminal() -> None:
    store = InMemoryExecutionIntentStore()
    _seed_entry(store, index=1, status=ACKED)
    _seed_entry(store, index=2, status=REJECTED)
    assert store.list_unresolved_intents() == ()


# --------------------------------------------------------------------------- #
# Resolution by deterministic-id query.
# --------------------------------------------------------------------------- #


async def test_entry_sent_and_found_becomes_acked_with_the_exchange_order_id() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=SENT)
    exchange_order_id = _exchange_holds_entry(adapter)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    row = _row(store, approval_id, ENTRY)
    assert row.intent_status == ACKED
    assert row.exchange_order_id == exchange_order_id
    assert row.exchange_status == STATUS_NEW
    assert report.resolved == ((approval_id, ENTRY, ACKED),)
    assert report.unresolved == ()
    assert report.safe_mode_entered is False
    assert safe_mode.entered == []
    _no_orders_placed(adapter)
    probes = adapter.calls_to("query_order_by_client")
    assert [p["kwargs"] for p in probes] == [
        {"symbol": SYMBOL, "orig_client_order_id": _entry_id(1)}
    ]


async def test_entry_intended_but_never_sent_becomes_rejected() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=INTENDED)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert _row(store, approval_id, ENTRY).intent_status == REJECTED
    assert report.resolved == ((approval_id, ENTRY, REJECTED),)
    assert safe_mode.entered == []
    _no_orders_placed(adapter)


async def test_stop_loss_sent_and_found_by_algo_id_becomes_acked() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=ACKED)
    _seed_stop_loss(store, status=SENT)
    _exchange_holds_stop_loss(adapter)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert _row(store, approval_id, STOP_LOSS).intent_status == ACKED
    assert report.resolved == ((approval_id, STOP_LOSS, ACKED),)
    assert safe_mode.entered == []
    algo_probes = adapter.calls_to("query_algo_order_by_client")
    assert [p["kwargs"] for p in algo_probes] == [{"client_algo_id": _sl_id(1)}]
    # A protective leg is never probed as a normal order.
    assert adapter.calls_to("query_order_by_client") == []
    _no_orders_placed(adapter)


async def test_probe_error_leaves_unknown_and_enters_safe_mode_once() -> None:
    store = InMemoryExecutionIntentStore()

    class RaisingProbeAdapter(BinanceSemanticsFakeAdapter):
        async def query_order_by_client(self, **kwargs: Any) -> Any:
            await super().query_order_by_client(**kwargs)
            raise RuntimeError("-1003 too many requests")

    adapter = RaisingProbeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=SENT)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    row = _row(store, approval_id, ENTRY)
    assert row.intent_status == UNKNOWN
    assert row.resolved_at_utc is None
    assert report.resolved == ()
    assert report.unresolved == ((approval_id, ENTRY, UNKNOWN),)
    assert report.safe_mode_entered is True
    assert safe_mode.entered == [("UNRESOLVED_EXECUTION_INTENT", NOW)]
    _no_orders_placed(adapter)


@pytest.mark.parametrize("found", [None, "yes", 1])
async def test_indeterminate_probe_answer_is_not_treated_as_absence(found: Any) -> None:
    store = InMemoryExecutionIntentStore()

    class IndeterminateAdapter(BinanceSemanticsFakeAdapter):
        async def query_order_by_client(self, **kwargs: Any) -> Any:
            await super().query_order_by_client(**kwargs)
            return {"found": found}

    adapter = IndeterminateAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=SENT)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert _row(store, approval_id, ENTRY).intent_status == UNKNOWN
    assert report.unresolved == ((approval_id, ENTRY, UNKNOWN),)
    assert len(safe_mode.entered) == 1
    _no_orders_placed(adapter)


async def test_absent_and_older_than_three_days_stays_unknown() -> None:
    store = InMemoryExecutionIntentStore()
    now = NOW + HISTORY_RETENTION + timedelta(hours=1)
    adapter = BinanceSemanticsFakeAdapter(now_utc=now)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=SENT, at=NOW)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=now
    )

    # The exchange no longer retains old canceled orders, so "not found" proves nothing.
    assert _row(store, approval_id, ENTRY).intent_status == UNKNOWN
    assert report.unresolved == ((approval_id, ENTRY, UNKNOWN),)
    assert safe_mode.entered == [("UNRESOLVED_EXECUTION_INTENT", now)]
    _no_orders_placed(adapter)


async def test_absent_at_exactly_three_days_stays_unknown_and_just_under_is_rejected() -> None:
    store = InMemoryExecutionIntentStore()
    safe_mode = RecordingSafeModeController()
    exactly = _seed_entry(store, index=1, status=SENT, at=NOW)
    just_under = _seed_entry(store, index=2, status=SENT, at=NOW + timedelta(seconds=1))
    now = NOW + HISTORY_RETENTION
    adapter = BinanceSemanticsFakeAdapter(now_utc=now)

    await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=now
    )

    assert _row(store, exactly, ENTRY).intent_status == UNKNOWN
    assert _row(store, just_under, ENTRY).intent_status == REJECTED


async def test_found_is_acked_even_when_older_than_three_days() -> None:
    store = InMemoryExecutionIntentStore()
    now = NOW + timedelta(days=10)
    adapter = BinanceSemanticsFakeAdapter(now_utc=now)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=SENT, at=NOW)
    _exchange_holds_entry(adapter)

    await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=now
    )

    assert _row(store, approval_id, ENTRY).intent_status == ACKED
    assert safe_mode.entered == []


async def test_lookup_window_is_a_keyword_argument() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW + timedelta(hours=2))
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=SENT, at=NOW)

    await resolve_unresolved_intents(
        store=store,
        adapter=adapter,
        safe_mode_controller=safe_mode,
        now_utc=NOW + timedelta(hours=2),
        lookup_window=timedelta(hours=1),
    )

    assert _row(store, approval_id, ENTRY).intent_status == UNKNOWN
    assert len(safe_mode.entered) == 1


async def test_safe_mode_is_entered_exactly_once_for_many_unresolved_intents() -> None:
    store = InMemoryExecutionIntentStore()

    class RaisingProbeAdapter(BinanceSemanticsFakeAdapter):
        async def query_order_by_client(self, **kwargs: Any) -> Any:
            raise RuntimeError("exchange unreachable")

        async def query_algo_order_by_client(self, **kwargs: Any) -> Any:
            raise RuntimeError("exchange unreachable")

    adapter = RaisingProbeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    _seed_entry(store, index=1, status=SENT)
    _seed_entry(store, index=2, status=INTENDED)
    _seed_entry(store, index=3, status=ACKED)
    _seed_stop_loss(store, index=3, status=SENT)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert len(report.unresolved) == 3
    assert len(safe_mode.entered) == 1
    for row in store.list_unresolved_intents():
        assert row.intent_status == UNKNOWN


async def test_resolved_and_unresolved_mix_is_reported_deterministically() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    _seed_entry(store, index=1, status=SENT, at=NOW)
    _seed_entry(store, index=2, status=SENT, at=NOW + timedelta(minutes=1))
    _seed_entry(store, index=3, status=INTENDED, at=NOW + timedelta(minutes=2))
    _exchange_holds_entry(adapter, index=1)  # found -> ACKED
    # index 2 SENT but absent and young -> REJECTED; index 3 INTENDED, absent -> REJECTED

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert report == RecoveryReport(
        resolved=(
            ("appr-1", ENTRY, ACKED),
            ("appr-2", ENTRY, REJECTED),
            ("appr-3", ENTRY, REJECTED),
        ),
        unresolved=(),
        safe_mode_entered=False,
    )
    _no_orders_placed(adapter)


async def test_terminal_intents_are_never_probed() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    _seed_entry(store, index=1, status=ACKED)
    _seed_entry(store, index=2, status=REJECTED)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert report == RecoveryReport(resolved=(), unresolved=(), safe_mode_entered=False)
    assert adapter.calls == []
    assert safe_mode.entered == []


async def test_an_intent_already_unknown_is_resolved_when_the_exchange_now_shows_it() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(store, status=UNKNOWN)
    _exchange_holds_entry(adapter)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert _row(store, approval_id, ENTRY).intent_status == ACKED
    assert report.resolved == ((approval_id, ENTRY, ACKED),)


async def test_recovery_is_repeatable_and_resolves_once_the_exchange_answers() -> None:
    store = InMemoryExecutionIntentStore()
    safe_mode = RecordingSafeModeController()
    failing = {"on": True}

    class FlakyAdapter(BinanceSemanticsFakeAdapter):
        async def query_order_by_client(self, **kwargs: Any) -> Any:
            if failing["on"]:
                raise RuntimeError("timeout")
            return await super().query_order_by_client(**kwargs)

    adapter = FlakyAdapter(now_utc=NOW)
    approval_id = _seed_entry(store, status=SENT)
    _exchange_holds_entry(adapter)

    first = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )
    assert first.unresolved == ((approval_id, ENTRY, UNKNOWN),)

    failing["on"] = False
    second = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )
    assert second.resolved == ((approval_id, ENTRY, ACKED),)
    assert second.safe_mode_entered is False
    assert len(safe_mode.entered) == 1  # only the first (failed) pass entered SAFE_MODE
    _no_orders_placed(adapter)


# --------------------------------------------------------------------------- #
# Fail closed on store problems and bad input.
# --------------------------------------------------------------------------- #


async def test_a_failing_status_write_leaves_the_intent_unresolved_and_enters_safe_mode() -> None:
    inner = InMemoryExecutionIntentStore()
    store = FailingIntentStore(
        "record_result", IntentStateConflict("boom"), inner=inner, role=ENTRY
    )
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()
    approval_id = _seed_entry(inner, status=SENT)
    _exchange_holds_entry(adapter)

    report = await resolve_unresolved_intents(
        store=store, adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
    )

    assert report.resolved == ()
    assert [(a, r) for a, r, _s in report.unresolved] == [(approval_id, ENTRY)]
    assert len(safe_mode.entered) == 1
    _no_orders_placed(adapter)


async def test_a_failing_list_enters_safe_mode_and_propagates() -> None:
    from src.persistence.errors import StoreUnavailable

    class UnreadableStore(InMemoryExecutionIntentStore):
        def list_unresolved_intents(self) -> tuple[IntentRecord, ...]:
            raise StoreUnavailable("database down")

    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    safe_mode = RecordingSafeModeController()

    with pytest.raises(StoreUnavailable):
        await resolve_unresolved_intents(
            store=UnreadableStore(), adapter=adapter, safe_mode_controller=safe_mode, now_utc=NOW
        )

    assert [reason for reason, _now in safe_mode.entered] == ["DB_FAILURE"]
    assert adapter.calls == []


async def test_naive_now_is_refused_before_any_work() -> None:
    store = InMemoryExecutionIntentStore()
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW)
    _seed_entry(store, status=SENT)

    with pytest.raises(ValueError, match="UTC"):
        await resolve_unresolved_intents(
            store=store,
            adapter=adapter,
            safe_mode_controller=RecordingSafeModeController(),
            now_utc=datetime(2026, 9, 19, 10, 30),
        )

    assert adapter.calls == []
    assert _row(store, "appr-1", ENTRY).intent_status == SENT
