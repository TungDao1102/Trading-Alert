"""SC4 tracer: one APPROVE reaches `execute_approved_plan` twice, one entry (Phase 17-01).

F-126 / F-603: Binance's `newClientOrderId` is unique only among OPEN orders,
so once the first entry is FILLED (or CANCELED) the exchange would accept the
same deterministic id again and a replayed APPROVE would place a second entry.
The approval is therefore consumed durably in PostgreSQL by writing the ENTRY
execution intent ahead of `place_entry` (D-13, D-14, D-15).

Every PostgreSQL test runs on a generated `t17_<hex>_test` database cloned from
an alembic-built template (`tests/pg_support.py`).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
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
from tests.support.intent_store_fakes import AlwaysWinsIntentStore, InMemoryExecutionIntentStore
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
