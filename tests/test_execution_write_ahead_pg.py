"""Write-ahead proof on PostgreSQL: rows precede every exchange call (Phase 17-11, SC3).

D-14 / F-703: every leg is committed before its order leaves.

  1. approval consumed + ENTRY INTENDED
  2. ENTRY SENT, then `place_entry`
  3. ENTRY ACKED / REJECTED / UNKNOWN
  4. STOP_LOSS INTENDED then SENT, then `place_algo_protective`
  5. SL outcome and ENTRY outcome

A crash at ANY step (a `BaseException` the manager never catches) leaves a readable row,
and a restarted manager on a fresh engine returns the stored outcome or
RECONCILIATION_REQUIRED and never sends a second entry (D-26, T-17-28).

Every PostgreSQL test runs on a generated `t17_<hex>_test` database cloned from an
alembic-built template (`tests/pg_support.py`). Rows are always read through a second
engine so only COMMITTED state is observed.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.execution.manager import ExecutionOutcome
from src.execution.order_ids import derive_algo_client_id
from src.persistence.errors import IntentStateConflict

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
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

SL_ALGO_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role=OrderRole.STOP_LOSS.value)


def _statuses(engine: Engine) -> dict[str, str]:
    """`role -> intent_status` of every stored intent row of the approval."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT role, intent_status FROM execution_intents WHERE approval_id = :a"),
            {"a": APPROVAL_ID},
        ).all()
    return {row.role: row.intent_status for row in rows}


def _outcome_columns(engine: Engine) -> tuple[bool, bool | None, str | None]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT outcome_recorded, outcome_is_no_trade, outcome_reason_code "
                "FROM execution_intents WHERE approval_id = :a AND role = 'ENTRY'"
            ),
            {"a": APPROVAL_ID},
        ).one()
    return (row.outcome_recorded, row.outcome_is_no_trade, row.outcome_reason_code)


class _ObservingAdapter(BinanceSemanticsFakeAdapter):
    """Records the committed row state, read through a second connection, at each order call.

    Never asserts inside a hook: the manager treats any exception raised by an adapter call
    as an ambiguous or failed placement. Observations are asserted by the test afterwards.
    """

    def __init__(self, probe_engine: Engine) -> None:
        super().__init__()
        self._probe_engine = probe_engine
        self.seen_at_place_entry: list[dict[str, str]] = []
        self.seen_at_place_algo: list[dict[str, str]] = []

    async def place_entry(self, **kwargs: Any) -> Any:
        self.seen_at_place_entry.append(_statuses(self._probe_engine))
        return await super().place_entry(**kwargs)

    async def place_algo_protective(self, **kwargs: Any) -> Any:
        self.seen_at_place_algo.append(_statuses(self._probe_engine))
        return await super().place_algo_protective(**kwargs)


# --------------------------------------------------------------------------- #
# Row state at each adapter call.
# --------------------------------------------------------------------------- #


async def test_rows_are_committed_before_each_order_call(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store), _store_on(pg_db) as (probe_engine, _unused):
        _seed_parent_chain(engine)
        adapter = _ObservingAdapter(probe_engine)

        outcome = await _run_plan(adapter, intent_store=store)

        assert outcome == ExecutionOutcome(is_no_trade=False, reason_code="OK")
        # place_entry: ENTRY already SENT, no protective row yet.
        assert adapter.seen_at_place_entry == [{"ENTRY": "SENT"}]
        # place_algo_protective: ENTRY ACKED and STOP_LOSS already SENT.
        assert adapter.seen_at_place_algo == [{"ENTRY": "ACKED", "STOP_LOSS": "SENT"}]

        assert _statuses(engine) == {"ENTRY": "ACKED", "STOP_LOSS": "ACKED"}
        assert _outcome_columns(engine) == (True, False, "OK")
        with engine.connect() as conn:
            stop_loss = (
                conn.execute(
                    text(
                        "SELECT * FROM execution_intents "
                        "WHERE approval_id = :a AND role = 'STOP_LOSS'"
                    ),
                    {"a": APPROVAL_ID},
                )
                .mappings()
                .one()
            )
        assert stop_loss["algo_client_id"] == SL_ALGO_ID
        assert stop_loss["client_order_id"] is None
        assert stop_loss["intended_quantity"] is None
        assert stop_loss["side"] == "SELL"
        assert stop_loss["plan_hash"] == PLAN_HASH
        assert stop_loss["trade_plan_id"] == CASE["trade_plan_id"]
        assert stop_loss["outcome_recorded"] is False
        assert stop_loss["sent_at_utc"] == NOW_UTC


# --------------------------------------------------------------------------- #
# Crash injection after every write-ahead step, then restart on a fresh engine.
# --------------------------------------------------------------------------- #

# step -> (rows left behind, place_entry calls made before the crash)
_CRASH_MATRIX: list[tuple[str, dict[str, str], int]] = [
    ("consume", {"ENTRY": "INTENDED"}, 0),
    ("entry_sent", {"ENTRY": "SENT"}, 0),
    ("entry_result", {"ENTRY": "ACKED"}, 1),
    ("sl_intent", {"ENTRY": "ACKED", "STOP_LOSS": "INTENDED"}, 1),
    ("sl_sent", {"ENTRY": "ACKED", "STOP_LOSS": "SENT"}, 1),
    ("sl_result", {"ENTRY": "ACKED", "STOP_LOSS": "ACKED"}, 1),
]


@pytest.mark.parametrize(("step", "expected_rows", "entry_calls"), _CRASH_MATRIX)
async def test_crash_after_each_step_leaves_a_row_and_restart_never_resends(
    pg_db: str, step: str, expected_rows: dict[str, str], entry_calls: int
) -> None:
    adapter = BinanceSemanticsFakeAdapter()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with pytest.raises(SimulatedCrash):
            await _run_plan(adapter, intent_store=CrashAfter(store, step=step))
        assert len(adapter.calls_to("place_entry")) == entry_calls
        # The row is committed and readable through a different connection.
        with _store_on(pg_db) as (probe_engine, _unused):
            assert _statuses(probe_engine) == expected_rows

    calls_before_restart = len(adapter.calls)

    # "Restart": a brand-new engine, store and manager call on the same database.
    with _store_on(pg_db) as (engine2, restarted_store):
        second = await _run_plan(adapter, intent_store=restarted_store)

        # No outcome was recorded, so the restart cannot tell what exists on the exchange.
        assert second == ExecutionOutcome(is_no_trade=True, reason_code="RECONCILIATION_REQUIRED")
        assert len(adapter.calls) == calls_before_restart  # zero adapter calls on restart
        assert len(adapter.calls_to("place_entry")) <= 1
        assert _statuses(engine2) == expected_rows  # the restart changed nothing
        assert _scalar(engine2, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1


async def test_crash_after_finalize_restarts_to_the_stored_outcome(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        with pytest.raises(SimulatedCrash):
            await _run_plan(adapter, intent_store=CrashAfter(store, step="finalize"))
        assert _outcome_columns(engine) == (True, False, "OK")

    adapter.fill(ENTRY_CLIENT_ID)  # the exchange would now accept the same id again
    calls_before_restart = len(adapter.calls)

    with _store_on(pg_db) as (engine2, restarted_store):
        second = await _run_plan(adapter, intent_store=restarted_store)
        assert second == ExecutionOutcome(is_no_trade=False, reason_code="OK")
        assert len(adapter.calls) == calls_before_restart
        assert len(adapter.calls_to("place_entry")) == 1
        assert _statuses(engine2) == {"ENTRY": "ACKED", "STOP_LOSS": "ACKED"}


# --------------------------------------------------------------------------- #
# Complete run, then restart.
# --------------------------------------------------------------------------- #


async def test_restart_after_a_complete_run_returns_the_stored_outcome(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        first = await _run_plan(adapter, intent_store=store)
        assert first == ExecutionOutcome(is_no_trade=False, reason_code="OK")
        assert _statuses(engine) == {"ENTRY": "ACKED", "STOP_LOSS": "ACKED"}

    adapter.fill(ENTRY_CLIENT_ID)
    calls_before_restart = len(adapter.calls)

    with _store_on(pg_db) as (engine2, restarted_store):
        second = await _run_plan(adapter, intent_store=restarted_store)
        assert second == first
        assert len(adapter.calls) == calls_before_restart
        assert len(adapter.calls_to("place_entry")) == 1
        assert _statuses(engine2) == {"ENTRY": "ACKED", "STOP_LOSS": "ACKED"}


# --------------------------------------------------------------------------- #
# Store-level guarantees the manager relies on (D-20).
# --------------------------------------------------------------------------- #


def test_protective_intent_insert_is_idempotent_and_transitions_are_enforced(pg_db: str) -> None:
    from decimal import Decimal

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        store.consume_and_record_entry_intent(
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
        leg: dict[str, Any] = {
            "approval_id": APPROVAL_ID,
            "role": "STOP_LOSS",
            "trade_plan_id": CASE["trade_plan_id"],
            "plan_hash": PLAN_HASH,
            "algo_client_id": SL_ALGO_ID,
            "symbol": CASE["symbol"],
            "side": "SELL",
            "intended_price": Decimal("98"),
            "now_utc": NOW_UTC,
        }
        assert store.record_protective_intent(**leg) is True
        assert store.record_protective_intent(**leg) is False  # same (approval, role): no new row

        store.mark_sent(approval_id=APPROVAL_ID, role="STOP_LOSS", now_utc=NOW_UTC)
        store.mark_sent(approval_id=APPROVAL_ID, role="STOP_LOSS", now_utc=NOW_UTC)  # no-op
        store.record_result(
            approval_id=APPROVAL_ID,
            role="STOP_LOSS",
            status=ExecutionIntentStatus.ACKED,
            exchange_order_id="algo-1",
            exchange_status="NEW",
            now_utc=NOW_UTC,
        )
        # ACKED is terminal: nothing moves it again (src.domain.transitions, D-20).
        with pytest.raises(IntentStateConflict):
            store.record_result(
                approval_id=APPROVAL_ID,
                role="STOP_LOSS",
                status=ExecutionIntentStatus.REJECTED,
                exchange_order_id=None,
                exchange_status=None,
                now_utc=NOW_UTC,
            )
        with pytest.raises(IntentStateConflict):
            store.mark_sent(approval_id=APPROVAL_ID, role="TAKE_PROFIT_1", now_utc=NOW_UTC)
        assert _statuses(engine) == {"ENTRY": "INTENDED", "STOP_LOSS": "ACKED"}
