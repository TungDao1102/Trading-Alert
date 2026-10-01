"""SC4 tracer: one APPROVE reaches `execute_approved_plan` twice, one entry (Phase 17-01).

F-126 / F-603: Binance's `newClientOrderId` is unique only among OPEN orders,
so once the first entry is FILLED (or CANCELED) the exchange would accept the
same deterministic id again and a replayed APPROVE would place a second entry.
The approval is therefore consumed durably in PostgreSQL by writing the ENTRY
execution intent ahead of `place_entry` (D-13, D-14, D-15).

Plan 17-12 completes the SC4 matrix below the tracer tests: the first entry still
OPEN, FILLED or CANCELED, each with and without a restart (all engines disposed, new
engine, store and manager), two concurrent calls from two threads with separate engines,
and negative controls (a store that never remembers) proving the fake would catch F-126.

Every PostgreSQL test runs on a generated `t17_<hex>_test` database cloned from
an alembic-built template (`tests/pg_support.py`).
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session
from src.db.mappers import approval_to_row, signal_to_row, trade_plan_to_row
from src.domain.enums import OrderRole, SignalStatus
from src.domain.signal import Signal
from src.execution.manager import ExecutionOutcome
from src.execution.order_ids import derive_client_order_id
from src.persistence.engine import make_sync_engine
from src.persistence.execution_state import PgExecutionStateStore
from src.persistence.uow import OperationalDatabase

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.intent_store_fakes import (
    AlwaysWinsIntentStore,
    BarrierBeforeConsume,
    InMemoryExecutionIntentStore,
)
from tests.test_execution_manager import (
    _build_approval,
    _build_approved_plan,
    _load_input,
    _parse_utc,
    _run_plan,
)

CASE = _load_input()
APPROVAL_ID: str = CASE["approval_id"]
PLAN_HASH: str = CASE["plan_hash"]
NOW_UTC: datetime = _parse_utc(CASE["now_utc"])
ENTRY_CLIENT_ID = derive_client_order_id(plan_hash=PLAN_HASH, role=OrderRole.ENTRY.value)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _seed_parent_chain(engine: Engine) -> None:
    """Signal -> TradePlan -> Approval, parents first (FK-safe, plan 02 adds the FKs)."""
    signal = Signal(
        signal_id=CASE["signal_id"],
        strategy_id="trend-pullback",
        strategy_version=CASE["strategy_version"],
        parameter_set_id=CASE["parameter_set_id"],
        parameter_set_hash=CASE["parameter_set_hash"],
        symbol=CASE["symbol"],
        direction="LONG",
        setup_type="TREND_PULLBACK_LONG",
        source_timeframe="1h",
        source_candle_close_utc=_parse_utc(CASE["created_at_utc"]),
        detected_at_utc=_parse_utc(CASE["created_at_utc"]),
        status=SignalStatus.APPROVED,
        expires_at_utc=_parse_utc(CASE["expiry_utc"]),
    )
    with Session(engine) as session, session.begin():
        session.add(signal_to_row(signal))
        session.flush()
        session.add(trade_plan_to_row(_build_approved_plan(CASE)))
        session.flush()
        session.add(approval_to_row(_build_approval(CASE)))


@contextmanager
def _store_on(url: str) -> Iterator[tuple[Engine, PgExecutionStateStore]]:
    """A fresh engine + store (what a restarted process would build)."""
    engine = make_sync_engine(url)
    try:
        yield engine, PgExecutionStateStore(OperationalDatabase(engine))
    finally:
        engine.dispose()


def _scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def _entry_row(engine: Engine) -> Any:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text("SELECT * FROM execution_intents WHERE approval_id = :a AND role = 'ENTRY'"),
                {"a": APPROVAL_ID},
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    return rows[0]


# --------------------------------------------------------------------------- #
# The fake models Binance's open-orders-only client id uniqueness.
# --------------------------------------------------------------------------- #


async def test_fake_rejects_duplicate_open_client_id_with_4116() -> None:
    adapter = BinanceSemanticsFakeAdapter()
    kwargs: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "time_in_force": "GTC",
        "quantity": CASE["suggested_quantity"],
        "price": CASE["expected_limit_price"],
        "new_client_order_id": ENTRY_CLIENT_ID,
    }
    await adapter.place_entry(**kwargs)
    with pytest.raises(RuntimeError, match="-4116"):
        await adapter.place_entry(**kwargs)


@pytest.mark.parametrize("free", ["fill", "cancel"])
async def test_fake_accepts_the_same_client_id_after_fill_or_cancel(free: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    kwargs: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "time_in_force": "GTC",
        "quantity": CASE["suggested_quantity"],
        "price": CASE["expected_limit_price"],
        "new_client_order_id": ENTRY_CLIENT_ID,
    }
    await adapter.place_entry(**kwargs)
    getattr(adapter, free)(ENTRY_CLIENT_ID)
    await adapter.place_entry(**kwargs)
    assert len(adapter.calls_to("place_entry")) == 2


async def test_fake_probe_finds_open_and_historical_orders_only() -> None:
    adapter = BinanceSemanticsFakeAdapter()
    kwargs: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "time_in_force": "GTC",
        "quantity": CASE["suggested_quantity"],
        "price": CASE["expected_limit_price"],
        "new_client_order_id": ENTRY_CLIENT_ID,
    }
    await adapter.place_entry(**kwargs)
    probe = await adapter.query_order_by_client(
        symbol="BTCUSDT", orig_client_order_id=ENTRY_CLIENT_ID
    )
    assert probe.found is True
    adapter.fill(ENTRY_CLIENT_ID)
    probe = await adapter.query_order_by_client(
        symbol="BTCUSDT", orig_client_order_id=ENTRY_CLIENT_ID
    )
    assert probe.found is True and probe.status == "FILLED"
    never_seen = await adapter.query_order_by_client(
        symbol="BTCUSDT", orig_client_order_id="x-never-seen"
    )
    assert never_seen.found is False


# --------------------------------------------------------------------------- #
# The fixture hands out migrated, disposable, generated databases.
# --------------------------------------------------------------------------- #


def test_pg_db_is_a_generated_migrated_database(pg_db: str, pg_server_url: str) -> None:
    name = make_url(pg_db).database
    assert name is not None
    assert re.fullmatch(r"t17_[0-9a-f]+_test", name)
    assert name != make_url(pg_server_url).database
    engine = make_sync_engine(pg_db)
    try:
        assert _scalar(engine, "SELECT version_num FROM alembic_version") == (
            "0004_persistence_integrity"
        )
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
# SC4: exactly one entry, across a fill between calls and across a restart.
# --------------------------------------------------------------------------- #


async def test_double_call_after_fill_places_exactly_one_entry(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    observed_during_place: list[str] = []

    with _store_on(pg_db) as (engine, store), _store_on(pg_db) as (probe_engine, _unused):
        _seed_parent_chain(engine)

        def read_intent_through_second_connection(_kwargs: dict[str, Any]) -> None:
            # Never assert inside the hook: the manager treats any exception
            # from place_entry as an ambiguous placement. Record, assert after.
            status = _scalar(
                probe_engine,
                "SELECT intent_status FROM execution_intents "
                "WHERE approval_id = :a AND role = 'ENTRY'",
                a=APPROVAL_ID,
            )
            observed_during_place.append(status)

        adapter.on_place_entry = read_intent_through_second_connection

        first = await _run_plan(adapter, intent_store=store)
        assert first == ExecutionOutcome(is_no_trade=False, reason_code="OK")
        assert len(adapter.calls_to("place_entry")) == 1
        # The write-ahead row was COMMITTED (visible to another connection) as SENT.
        assert observed_during_place == ["SENT"]

        adapter.fill(ENTRY_CLIENT_ID)  # the exchange would now accept the same id again
        calls_after_first = len(adapter.calls)

        second = await _run_plan(adapter, intent_store=store)

        assert second == first
        assert len(adapter.calls) == calls_after_first  # zero adapter calls on replay
        assert len(adapter.calls_to("place_entry")) == 1

        assert _scalar(engine, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1
        row = _entry_row(engine)
        assert row["intent_status"] == "ACKED"
        assert row["outcome_recorded"] is True
        assert row["outcome_is_no_trade"] is False
        assert row["outcome_reason_code"] == "OK"
        assert row["client_order_id"] == ENTRY_CLIENT_ID
        assert row["algo_client_id"] is None
        assert row["trade_plan_id"] == CASE["trade_plan_id"]
        assert row["plan_hash"] == PLAN_HASH

        with engine.connect() as conn:
            approval = conn.execute(
                text(
                    "SELECT consumption_status, consumed_at_utc FROM approvals "
                    "WHERE approval_id = :a"
                ),
                {"a": APPROVAL_ID},
            ).one()
        assert approval.consumption_status == "CONSUMED"
        assert approval.consumed_at_utc == NOW_UTC
        assert approval.consumed_at_utc.utcoffset() == NOW_UTC.utcoffset()


async def test_replay_after_cancel_places_exactly_one_entry(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        first = await _run_plan(adapter, intent_store=store)
        adapter.cancel(ENTRY_CLIENT_ID)
        second = await _run_plan(adapter, intent_store=store)
        assert second == first
        assert len(adapter.calls_to("place_entry")) == 1
        assert _scalar(engine, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1


async def test_restart_returns_stored_outcome_with_zero_adapter_calls(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        first = await _run_plan(adapter, intent_store=store)
    adapter.fill(ENTRY_CLIENT_ID)
    calls_before_restart = len(adapter.calls)

    # "Restart": a brand-new engine, store and manager call on the same database.
    with _store_on(pg_db) as (engine2, restarted_store):
        second = await _run_plan(adapter, intent_store=restarted_store)
        assert second == first
        assert len(adapter.calls) == calls_before_restart
        assert _scalar(engine2, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1


# --------------------------------------------------------------------------- #
# Negative control: without a durable memory the fake sees F-126.
# --------------------------------------------------------------------------- #


async def test_negative_control_never_remembering_store_places_two_entries() -> None:
    adapter = BinanceSemanticsFakeAdapter()
    store = AlwaysWinsIntentStore()

    first = await _run_plan(adapter, intent_store=store)
    adapter.fill(ENTRY_CLIENT_ID)
    second = await _run_plan(adapter, intent_store=store)

    assert first.is_no_trade is False
    assert second.is_no_trade is False
    # The old no-persistence behavior: the exchange accepted the freed id again.
    assert len(adapter.calls_to("place_entry")) == 2


async def test_in_memory_store_has_the_same_one_entry_semantics() -> None:
    adapter = BinanceSemanticsFakeAdapter()
    store = InMemoryExecutionIntentStore()
    first = await _run_plan(adapter, intent_store=store)
    adapter.fill(ENTRY_CLIENT_ID)
    second = await _run_plan(adapter, intent_store=store)
    assert second == first
    assert len(adapter.calls_to("place_entry")) == 1


# --------------------------------------------------------------------------- #
# Plan 17-12: the full SC4 matrix (D-15, D-17, D-25, D-26).
# --------------------------------------------------------------------------- #

OK = ExecutionOutcome(is_no_trade=False, reason_code="OK")
RECONCILIATION_REQUIRED = ExecutionOutcome(is_no_trade=True, reason_code="RECONCILIATION_REQUIRED")
SCENARIOS = ("open", "filled", "canceled")
BARRIER_TIMEOUT_SECONDS = 30.0


def _free_the_client_id(adapter: BinanceSemanticsFakeAdapter, scenario: str) -> None:
    """What the exchange does to the first entry between the two calls."""
    if scenario == "open":
        return  # still on the open book: the exchange itself would reject a duplicate id
    getattr(adapter, "fill" if scenario == "filled" else "cancel")(ENTRY_CLIENT_ID)


class _RejectionRecordingAdapter(BinanceSemanticsFakeAdapter):
    """Records every error the fake exchange raised for `place_entry` (e.g. -4116)."""

    def __init__(self) -> None:
        super().__init__()
        self.entry_rejections: list[str] = []

    async def place_entry(self, **kwargs: Any) -> Any:
        try:
            return await super().place_entry(**kwargs)
        except RuntimeError as exc:
            self.entry_rejections.append(str(exc))
            raise

    @property
    def accepted_entries(self) -> int:
        return len(self.calls_to("place_entry")) - len(self.entry_rejections)


@pytest.mark.parametrize("restart", [False, True], ids=["same_process", "restart"])
@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_sc4_double_call_places_exactly_one_entry(
    pg_db: str, scenario: str, restart: bool
) -> None:
    adapter = BinanceSemanticsFakeAdapter()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        first = await _run_plan(adapter, intent_store=store)
        assert first == OK
        if restart:
            engine.dispose()  # the process "exits"; every pooled connection is gone
        _free_the_client_id(adapter, scenario)
        calls_after_first = len(adapter.calls)

        second_context = _store_on(pg_db) if restart else nullcontext((engine, store))
        with second_context as (engine2, store2):
            second = await _run_plan(adapter, intent_store=store2)

            assert second == first  # the stored outcome, not a fresh decision
            assert len(adapter.calls) == calls_after_first  # zero adapter calls on the replay
            assert len(adapter.calls_to("place_entry")) == 1
            entries = _scalar(
                engine2, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'"
            )
            assert entries == 1
            assert _entry_row(engine2)["intent_status"] == "ACKED"
            consumed = _scalar(
                engine2, "SELECT count(*) FROM approvals WHERE consumption_status = 'CONSUMED'"
            )
            assert consumed == 1


# --------------------------------------------------------------------------- #
# Concurrency: two threads, separate engines, released together at the barrier.
# --------------------------------------------------------------------------- #


def _consume_args() -> dict[str, Any]:
    return {
        "approval_id": APPROVAL_ID,
        "trade_plan_id": CASE["trade_plan_id"],
        "plan_hash": PLAN_HASH,
        "client_order_id": ENTRY_CLIENT_ID,
        "symbol": CASE["symbol"],
        "side": "BUY",
        "intended_quantity": Decimal("2.415"),
        "intended_price": Decimal(str(CASE["expected_limit_price"])),
        "now_utc": NOW_UTC,
    }


@pytest.mark.parametrize("attempt", range(3))
def test_two_threads_consuming_the_same_approval_yield_one_winner_and_one_row(
    pg_db: str, attempt: int
) -> None:
    barrier = threading.Barrier(2)

    with _store_on(pg_db) as (engine, store_a), _store_on(pg_db) as (_engine_b, store_b):
        _seed_parent_chain(engine)

        def consume(store: PgExecutionStateStore) -> bool:
            barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
            return store.consume_and_record_entry_intent(**_consume_args())

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(consume, store_a), pool.submit(consume, store_b)]
            results = sorted(f.result(timeout=60) for f in futures)

        assert results == [False, True]  # exactly one winner (D-17, D-26)
        assert _scalar(engine, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1
        assert _entry_row(engine)["intent_status"] == "INTENDED"
        consumed = _scalar(
            engine, "SELECT count(*) FROM approvals WHERE consumption_status = 'CONSUMED'"
        )
        assert consumed == 1


@pytest.mark.parametrize("attempt", range(3))
def test_two_concurrent_manager_calls_place_exactly_one_entry(pg_db: str, attempt: int) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    barrier = threading.Barrier(2)

    with _store_on(pg_db) as (engine, store_a), _store_on(pg_db) as (_engine_b, store_b):
        _seed_parent_chain(engine)

        def run(store: PgExecutionStateStore) -> ExecutionOutcome:
            raced = BarrierBeforeConsume(
                store, barrier=barrier, timeout_seconds=BARRIER_TIMEOUT_SECONDS
            )
            # Its own event loop per thread: a blocking store call stalls only its thread.
            return asyncio.run(_run_plan(adapter, intent_store=raced))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, store_a), pool.submit(run, store_b)]
            outcomes = [f.result(timeout=60) for f in futures]

        assert len(adapter.calls_to("place_entry")) == 1
        assert _scalar(engine, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1
        assert OK in outcomes  # the winner completed its run
        # The loser returns the winner's recorded outcome, or fail-closed
        # RECONCILIATION_REQUIRED while the winner has not finalized yet; never a 2nd order.
        for outcome in outcomes:
            assert outcome in (OK, RECONCILIATION_REQUIRED)
        assert _entry_row(engine)["intent_status"] == "ACKED"


# --------------------------------------------------------------------------- #
# Negative controls: without a durable memory the fake sees F-126.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("scenario", ["filled", "canceled"])
async def test_negative_control_never_remembering_store_places_two_entries_after_free(
    scenario: str,
) -> None:
    adapter = _RejectionRecordingAdapter()
    store = AlwaysWinsIntentStore()

    first = await _run_plan(adapter, intent_store=store)
    _free_the_client_id(adapter, scenario)
    second = await _run_plan(adapter, intent_store=store)

    assert first.is_no_trade is False
    assert second.is_no_trade is False
    # The exchange freed the id, so it accepted the SAME client id a second time.
    assert len(adapter.calls_to("place_entry")) == 2
    assert adapter.entry_rejections == []
    assert adapter.accepted_entries == 2


async def test_negative_control_open_entry_is_rejected_with_4116_by_the_exchange() -> None:
    adapter = _RejectionRecordingAdapter()
    store = AlwaysWinsIntentStore()

    await _run_plan(adapter, intent_store=store)
    await _run_plan(adapter, intent_store=store)  # the first entry is still OPEN

    # One entry on the book; the second attempt reached the exchange and got -4116 back.
    # Only the FILLED / CANCELED scenarios show why F-126 needs the local row: the
    # exchange dedups an open id and nothing else.
    assert len(adapter.calls_to("place_entry")) == 2
    assert len(adapter.entry_rejections) == 1
    assert "-4116" in adapter.entry_rejections[0]
    assert adapter.accepted_entries == 1
    assert len(adapter.open_orders) == 1


def test_negative_control_concurrent_calls_without_a_durable_row_both_reach_the_exchange() -> None:
    adapter = _RejectionRecordingAdapter()
    barrier = threading.Barrier(2)

    def run() -> ExecutionOutcome:
        raced = BarrierBeforeConsume(
            AlwaysWinsIntentStore(), barrier=barrier, timeout_seconds=BARRIER_TIMEOUT_SECONDS
        )
        return asyncio.run(_run_plan(adapter, intent_store=raced))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run), pool.submit(run)]
        for future in futures:
            future.result(timeout=60)

    # Both workers consumed the "same" approval and both sent: the barrier harness really
    # overlaps the two calls, so the exactly-one assertions above are not vacuous.
    assert len(adapter.calls_to("place_entry")) == 2


def _reset_consumption(engine: Engine) -> None:
    """Back to 'approved, nothing consumed' so one database can host many race rounds."""
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM execution_intents WHERE approval_id = :a"), {"a": APPROVAL_ID}
        )
        conn.execute(
            text(
                "UPDATE approvals SET consumption_status = 'UNCONSUMED', consumed_at_utc = NULL "
                "WHERE approval_id = :a"
            ),
            {"a": APPROVAL_ID},
        )


def test_consume_race_never_raises_for_the_loser_over_many_rounds(pg_db: str) -> None:
    """Two writers racing on one approval: the loser gets False, never an exception.

    The loser's INSERT can reach the secondary unique index (plan, role) before it
    sees the winner on the targeted arbiter (approval, role). That unique violation
    means "lost the race to the same approval", not "a different approval holds the
    plan", so the store must answer False (D-17). Many rounds make the narrow window
    observable instead of a one-in-twenty flake.
    """
    rounds = 60
    with _store_on(pg_db) as (engine, store_a), _store_on(pg_db) as (_engine_b, store_b):
        _seed_parent_chain(engine)
        for _round in range(rounds):
            _reset_consumption(engine)
            barrier = threading.Barrier(2)

            def consume(store: PgExecutionStateStore, gate: threading.Barrier = barrier) -> bool:
                gate.wait(timeout=BARRIER_TIMEOUT_SECONDS)
                return store.consume_and_record_entry_intent(**_consume_args())

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(consume, store_a), pool.submit(consume, store_b)]
                results = sorted(f.result(timeout=60) for f in futures)

            assert results == [False, True]
            assert (
                _scalar(engine, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1
            )


def test_consume_for_a_different_approval_of_the_same_plan_is_still_a_conflict(
    pg_db: str,
) -> None:
    """Only a lost race to the SAME approval is False; another approval holding the plan raises."""
    from dataclasses import replace

    from src.domain.enums import ApprovalAction, ApprovalResult
    from src.persistence.errors import IntentStateConflict

    other = replace(
        _build_approval(CASE),
        approval_id="apprv_other_for_same_plan",
        action=ApprovalAction.SIMULATE,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash="f" * 64,
        acted_at_utc=None,
    )
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with Session(engine) as session, session.begin():
            session.add(approval_to_row(other))

        assert store.consume_and_record_entry_intent(**_consume_args()) is True
        rival = {**_consume_args(), "approval_id": other.approval_id}
        with pytest.raises(IntentStateConflict):
            store.consume_and_record_entry_intent(**rival)

        assert _scalar(engine, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1
        assert _entry_row(engine)["approval_id"] == APPROVAL_ID
