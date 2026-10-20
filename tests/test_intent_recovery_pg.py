"""Restart recovery against PostgreSQL and the Binance-semantics fake (Phase 17-12, D-14, F-703).

A process crashes between write-ahead steps (plan 17-11 `CrashAfter`), a NEW engine, store
and manager come up on the same database, and `resolve_unresolved_intents` turns every
in-flight intent into UNKNOWN and then resolves it only by querying the exchange by its
deterministic client id. It never places an order: the fake's `place_entry` and
`place_algo_protective` call counts are asserted on every path.

Every PostgreSQL test runs on a generated `t17_<hex>_test` database cloned from an
alembic-built template (`tests/pg_support.py`). Rows are read through a second engine so
only COMMITTED state is observed.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.execution.intent_recovery import resolve_unresolved_intents
from src.execution.manager import ExecutionOutcome
from src.execution.order_ids import derive_algo_client_id

from tests.support.fake_binance_exchange import (
    HISTORY_RETENTION,
    STATUS_NEW,
    BinanceSemanticsFakeAdapter,
    ExchangeOrderRecord,
)
from tests.support.intent_store_fakes import CrashAfter, SimulatedCrash
from tests.test_execution_exactly_once_pg import (
    APPROVAL_ID,
    CASE,
    ENTRY_CLIENT_ID,
    NOW_UTC,
    PLAN_HASH,
    _scalar,
    _seed_parent_chain,
    _store_on,
)
from tests.test_execution_manager import _run_plan
from tests.test_intent_recovery import RecordingSafeModeController

SL_ALGO_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role=OrderRole.STOP_LOSS.value)
RECONCILIATION_REQUIRED = ExecutionOutcome(is_no_trade=True, reason_code="RECONCILIATION_REQUIRED")
# Plan 19-15 (D-10): the manager writes only the ENTRY steps. The STOP_LOSS steps are written by the
# protection coordinator after the first fill, so they are crashed through `_write_stop_intent`.
ENTRY_CRASH_STEPS = ("consume", "entry_sent", "entry_result")
STOP_CRASH_STEPS = ("sl_intent", "sl_sent", "sl_result")


def _statuses(engine: Engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT role, intent_status FROM execution_intents WHERE approval_id = :a"),
            {"a": APPROVAL_ID},
        ).all()
    return {row.role: row.intent_status for row in rows}


def _row(engine: Engine, role: str) -> Any:
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT * FROM execution_intents WHERE approval_id = :a AND role = :r"),
                {"a": APPROVAL_ID, "r": role},
            )
            .mappings()
            .one()
        )


def _exchange_holds_entry(adapter: BinanceSemanticsFakeAdapter) -> str:
    """The order reached the exchange before the crash; put it on the fake without `place_entry`."""
    adapter.open_orders[ENTRY_CLIENT_ID] = ExchangeOrderRecord(
        client_id=ENTRY_CLIENT_ID,
        symbol=CASE["symbol"],
        status=STATUS_NEW,
        created_at_utc=NOW_UTC,
        exchange_id="ex-held-1",
    )
    return "ex-held-1"


def _exchange_holds_stop_loss(adapter: BinanceSemanticsFakeAdapter) -> None:
    adapter.open_algos[SL_ALGO_ID] = ExchangeOrderRecord(
        client_id=SL_ALGO_ID,
        symbol=CASE["symbol"],
        status=STATUS_NEW,
        created_at_utc=NOW_UTC,
        exchange_id="algo-held-1",
    )


def _place_counts(adapter: BinanceSemanticsFakeAdapter) -> tuple[int, int]:
    return (
        len(adapter.calls_to("place_entry")),
        len(adapter.calls_to("place_algo_protective")),
    )


# --------------------------------------------------------------------------- #
# list_unresolved_intents on PostgreSQL.
# --------------------------------------------------------------------------- #


def test_list_unresolved_intents_returns_open_legs_only(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.list_unresolved_intents() == ()

        assert store.consume_and_record_entry_intent(
            approval_id=APPROVAL_ID,
            trade_plan_id=CASE["trade_plan_id"],
            plan_hash=PLAN_HASH,
            client_order_id=ENTRY_CLIENT_ID,
            symbol=CASE["symbol"],
            side="BUY",
            intended_quantity=Decimal("2.415"),
            intended_price=Decimal(str(CASE["expected_limit_price"])),
            now_utc=NOW_UTC,
        )
        assert store.record_protective_intent(
            approval_id=APPROVAL_ID,
            role="STOP_LOSS",
            trade_plan_id=CASE["trade_plan_id"],
            plan_hash=PLAN_HASH,
            algo_client_id=SL_ALGO_ID,
            symbol=CASE["symbol"],
            side="SELL",
            intended_price=Decimal("98"),
            now_utc=NOW_UTC,
        )

        listed = store.list_unresolved_intents()
        # Same instant and approval: the role breaks the tie (ENTRY before STOP_LOSS).
        assert [(r.approval_id, r.role, r.intent_status) for r in listed] == [
            (APPROVAL_ID, "ENTRY", ExecutionIntentStatus.INTENDED),
            (APPROVAL_ID, "STOP_LOSS", ExecutionIntentStatus.INTENDED),
        ]
        assert listed[0].client_order_id == ENTRY_CLIENT_ID
        assert listed[1].algo_client_id == SL_ALGO_ID

        store.mark_sent(approval_id=APPROVAL_ID, role="ENTRY", now_utc=NOW_UTC)
        store.record_result(
            approval_id=APPROVAL_ID,
            role="ENTRY",
            status=ExecutionIntentStatus.UNKNOWN,
            exchange_order_id=None,
            exchange_status=None,
            now_utc=NOW_UTC,
        )
        assert [r.intent_status for r in store.list_unresolved_intents()] == [
            ExecutionIntentStatus.UNKNOWN,
            ExecutionIntentStatus.INTENDED,
        ]

        store.record_result(
            approval_id=APPROVAL_ID,
            role="ENTRY",
            status=ExecutionIntentStatus.ACKED,
            exchange_order_id="ex-1",
            exchange_status="NEW",
            now_utc=NOW_UTC,
        )
        store.mark_sent(approval_id=APPROVAL_ID, role="STOP_LOSS", now_utc=NOW_UTC)
        store.record_result(
            approval_id=APPROVAL_ID,
            role="STOP_LOSS",
            status=ExecutionIntentStatus.REJECTED,
            exchange_order_id=None,
            exchange_status=None,
            now_utc=NOW_UTC,
        )
        assert store.list_unresolved_intents() == ()  # ACKED and REJECTED are terminal


# --------------------------------------------------------------------------- #
# Crash, restart on a fresh engine, recovery, replay.
# --------------------------------------------------------------------------- #


async def test_crash_after_entry_sent_is_resolved_to_acked_and_never_resent(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW_UTC)
    safe_mode = RecordingSafeModeController()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with pytest.raises(SimulatedCrash):
            await _run_plan(adapter, intent_store=CrashAfter(store, step="entry_sent"))
        assert _statuses(engine) == {"ENTRY": "SENT"}
    assert _place_counts(adapter) == (0, 0)
    exchange_order_id = _exchange_holds_entry(adapter)  # the order did reach the exchange

    # Restart: a brand-new engine, store and manager on the same database.
    with _store_on(pg_db) as (engine2, restarted_store):
        report = await resolve_unresolved_intents(
            store=restarted_store,
            adapter=adapter,
            safe_mode_controller=safe_mode,
            now_utc=NOW_UTC,
        )

        assert report.resolved == ((APPROVAL_ID, "ENTRY", ExecutionIntentStatus.ACKED),)
        assert report.unresolved == ()
        assert safe_mode.entered == []
        assert _statuses(engine2) == {"ENTRY": "ACKED"}
        row = _row(engine2, "ENTRY")
        assert row["exchange_order_id"] == exchange_order_id
        assert row["exchange_status"] == STATUS_NEW
        assert row["resolved_at_utc"] == NOW_UTC
        assert _place_counts(adapter) == (0, 0)

        calls_before_replay = len(adapter.calls)
        second = await _run_plan(adapter, intent_store=restarted_store)

        # No outcome was ever recorded: still fail closed, still no adapter call.
        assert second == RECONCILIATION_REQUIRED
        assert len(adapter.calls) == calls_before_replay
        assert _place_counts(adapter) == (0, 0)
        assert _scalar(engine2, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1


async def test_crash_after_entry_sent_with_the_order_absent_is_rejected(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW_UTC)
    safe_mode = RecordingSafeModeController()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with pytest.raises(SimulatedCrash):
            await _run_plan(adapter, intent_store=CrashAfter(store, step="entry_sent"))

    with _store_on(pg_db) as (engine2, restarted_store):
        report = await resolve_unresolved_intents(
            store=restarted_store,
            adapter=adapter,
            safe_mode_controller=safe_mode,
            now_utc=NOW_UTC,
        )

        assert report.resolved == ((APPROVAL_ID, "ENTRY", ExecutionIntentStatus.REJECTED),)
        assert safe_mode.entered == []
        assert _statuses(engine2) == {"ENTRY": "REJECTED"}
        assert _place_counts(adapter) == (0, 0)

        # The approval stays consumed: a replay can never place the entry.
        second = await _run_plan(adapter, intent_store=restarted_store)
        assert second == RECONCILIATION_REQUIRED
        assert _place_counts(adapter) == (0, 0)


def _write_stop_intent(store: Any) -> None:
    """The coordinator's three write-ahead steps for the closePosition stop, in order."""
    assert store.record_protective_intent(
        approval_id=APPROVAL_ID,
        role=OrderRole.STOP_LOSS.value,
        trade_plan_id=CASE["trade_plan_id"],
        plan_hash=PLAN_HASH,
        algo_client_id=SL_ALGO_ID,
        symbol=CASE["symbol"],
        side="SELL",
        intended_price=Decimal("98"),
        now_utc=NOW_UTC,
        intended_quantity=None,
    )
    store.mark_sent(approval_id=APPROVAL_ID, role=OrderRole.STOP_LOSS.value, now_utc=NOW_UTC)
    store.record_result(
        approval_id=APPROVAL_ID,
        role=OrderRole.STOP_LOSS.value,
        status=ExecutionIntentStatus.ACKED,
        exchange_order_id="algo-held-1",
        exchange_status=STATUS_NEW,
        now_utc=NOW_UTC,
    )


async def test_crash_after_sl_sent_resolves_the_stop_loss_by_algo_id(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW_UTC)
    safe_mode = RecordingSafeModeController()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        outcome = await _run_plan(adapter, intent_store=store)  # the manager writes ENTRY only
        assert outcome.is_no_trade is False
        assert _statuses(engine) == {"ENTRY": "ACKED"}
        with pytest.raises(SimulatedCrash):
            _write_stop_intent(CrashAfter(store, step="sl_sent"))
        assert _statuses(engine) == {"ENTRY": "ACKED", "STOP_LOSS": "SENT"}
    placed_before = _place_counts(adapter)
    assert placed_before == (1, 0)
    _exchange_holds_stop_loss(adapter)

    with _store_on(pg_db) as (engine2, restarted_store):
        report = await resolve_unresolved_intents(
            store=restarted_store,
            adapter=adapter,
            safe_mode_controller=safe_mode,
            now_utc=NOW_UTC,
        )

        assert report.resolved == ((APPROVAL_ID, "STOP_LOSS", ExecutionIntentStatus.ACKED),)
        assert safe_mode.entered == []
        assert _statuses(engine2) == {"ENTRY": "ACKED", "STOP_LOSS": "ACKED"}
        assert _place_counts(adapter) == placed_before
        algo_probe_kwargs = [c["kwargs"] for c in adapter.calls_to("query_algo_order_by_client")]
        assert algo_probe_kwargs == [{"client_algo_id": SL_ALGO_ID}]


@pytest.mark.parametrize("step", ENTRY_CRASH_STEPS)
async def test_recovery_after_a_crash_at_any_step_never_places_an_order(
    pg_db: str, step: str
) -> None:
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW_UTC)
    safe_mode = RecordingSafeModeController()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with pytest.raises(SimulatedCrash):
            await _run_plan(adapter, intent_store=CrashAfter(store, step=step))
    placed_before = _place_counts(adapter)

    with _store_on(pg_db) as (engine2, restarted_store):
        await resolve_unresolved_intents(
            store=restarted_store,
            adapter=adapter,
            safe_mode_controller=safe_mode,
            now_utc=NOW_UTC,
        )
        assert _place_counts(adapter) == placed_before
        # Whatever the exchange answered, nothing is left half-open without SAFE_MODE.
        assert restarted_store.list_unresolved_intents() == () or len(safe_mode.entered) == 1

        await _run_plan(adapter, intent_store=restarted_store)
        assert _place_counts(adapter) == placed_before
        assert _scalar(engine2, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1


@pytest.mark.parametrize("step", STOP_CRASH_STEPS)
async def test_recovery_after_a_crash_in_the_stop_write_ahead_never_places_an_order(
    pg_db: str, step: str
) -> None:
    adapter = BinanceSemanticsFakeAdapter(now_utc=NOW_UTC)
    safe_mode = RecordingSafeModeController()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert (await _run_plan(adapter, intent_store=store)).is_no_trade is False
        with pytest.raises(SimulatedCrash):
            _write_stop_intent(CrashAfter(store, step=step))
    placed_before = _place_counts(adapter)

    with _store_on(pg_db) as (engine2, restarted_store):
        await resolve_unresolved_intents(
            store=restarted_store,
            adapter=adapter,
            safe_mode_controller=safe_mode,
            now_utc=NOW_UTC,
        )
        assert _place_counts(adapter) == placed_before
        # The stop is resolved only by the algo-id query, or the gap stays visible with SAFE_MODE.
        assert restarted_store.list_unresolved_intents() == () or len(safe_mode.entered) == 1

        await _run_plan(adapter, intent_store=restarted_store)  # the stored outcome, no new order
        assert _place_counts(adapter) == placed_before
        assert _scalar(engine2, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1


# --------------------------------------------------------------------------- #
# Unresolved intents fail closed and stay visible.
# --------------------------------------------------------------------------- #


async def test_probe_error_persists_unknown_and_enters_safe_mode_once(pg_db: str) -> None:
    class UnreachableAdapter(BinanceSemanticsFakeAdapter):
        async def query_order_by_client(self, **kwargs: Any) -> Any:
            raise RuntimeError("exchange unreachable")

    adapter = UnreachableAdapter(now_utc=NOW_UTC)
    safe_mode = RecordingSafeModeController()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with pytest.raises(SimulatedCrash):
            await _run_plan(adapter, intent_store=CrashAfter(store, step="entry_sent"))

    with _store_on(pg_db) as (engine2, restarted_store):
        report = await resolve_unresolved_intents(
            store=restarted_store,
            adapter=adapter,
            safe_mode_controller=safe_mode,
            now_utc=NOW_UTC,
        )

        assert report.unresolved == ((APPROVAL_ID, "ENTRY", ExecutionIntentStatus.UNKNOWN),)
        assert report.safe_mode_entered is True
        assert safe_mode.entered == [("UNRESOLVED_EXECUTION_INTENT", NOW_UTC)]
        row = _row(engine2, "ENTRY")
        assert row["intent_status"] == "UNKNOWN"
        assert row["resolved_at_utc"] is None
        assert _place_counts(adapter) == (0, 0)
        # Phase 20 reads the same rows through the store.
        listed = restarted_store.list_unresolved_intents()
        assert [(r.approval_id, r.role, r.intent_status) for r in listed] == [
            (APPROVAL_ID, "ENTRY", ExecutionIntentStatus.UNKNOWN)
        ]


async def test_absent_and_older_than_three_days_stays_unknown_on_postgres(pg_db: str) -> None:
    now = NOW_UTC + HISTORY_RETENTION + timedelta(hours=1)
    adapter = BinanceSemanticsFakeAdapter(now_utc=now)
    safe_mode = RecordingSafeModeController()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with pytest.raises(SimulatedCrash):
            await _run_plan(adapter, intent_store=CrashAfter(store, step="entry_sent"))

    with _store_on(pg_db) as (engine2, restarted_store):
        report = await resolve_unresolved_intents(
            store=restarted_store,
            adapter=adapter,
            safe_mode_controller=safe_mode,
            now_utc=now,
        )

        assert report.unresolved == ((APPROVAL_ID, "ENTRY", ExecutionIntentStatus.UNKNOWN),)
        assert safe_mode.entered == [("UNRESOLVED_EXECUTION_INTENT", now)]
        assert _statuses(engine2) == {"ENTRY": "UNKNOWN"}
        assert _place_counts(adapter) == (0, 0)


async def test_unknown_intent_is_resolved_by_a_later_recovery_pass(pg_db: str) -> None:
    class FlakyAdapter(BinanceSemanticsFakeAdapter):
        reachable = False

        async def query_order_by_client(self, **kwargs: Any) -> Any:
            if not self.reachable:
                raise RuntimeError("exchange unreachable")
            return await super().query_order_by_client(**kwargs)

    adapter = FlakyAdapter(now_utc=NOW_UTC)
    safe_mode = RecordingSafeModeController()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with pytest.raises(SimulatedCrash):
            await _run_plan(adapter, intent_store=CrashAfter(store, step="entry_sent"))
    _exchange_holds_entry(adapter)

    with _store_on(pg_db) as (_engine2, restarted_store):
        first = await resolve_unresolved_intents(
            store=restarted_store,
            adapter=adapter,
            safe_mode_controller=safe_mode,
            now_utc=NOW_UTC,
        )
        assert first.safe_mode_entered is True

    adapter.reachable = True
    with _store_on(pg_db) as (engine3, third_store):
        second = await resolve_unresolved_intents(
            store=third_store,
            adapter=adapter,
            safe_mode_controller=safe_mode,
            now_utc=NOW_UTC,
        )
        assert second.resolved == ((APPROVAL_ID, "ENTRY", ExecutionIntentStatus.ACKED),)
        assert _statuses(engine3) == {"ENTRY": "ACKED"}
        assert _place_counts(adapter) == (0, 0)
