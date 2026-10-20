"""Write-ahead proof on PostgreSQL: rows precede every exchange call (Phase 17-11, SC3).

D-14 / F-703: every leg is committed before its order leaves. Plan 19-15 (D-10) splits the
sequence between two owners.

The manager (`execute_approved_plan`):
  1. approval consumed + ENTRY INTENDED
  2. ENTRY SENT, then `place_entry`
  3. ENTRY ACKED / REJECTED / UNKNOWN, then the hand-off to the protection registry
  4. ENTRY outcome

The protection coordinator (`src/execution/protection.py`, after the first fill):
  5. STOP_LOSS INTENDED then SENT, then `place_algo_protective`
  6. STOP_LOSS ACKED after the REST confirmation of the stop

A crash at ANY manager step (a `BaseException` the manager never catches) leaves a readable row,
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

    def __init__(self, probe_engine: Engine, *, enforce_flat_stop_rejection: bool = False) -> None:
        super().__init__(enforce_flat_stop_rejection=enforce_flat_stop_rejection)
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


async def test_rows_are_committed_before_the_entry_call_and_no_stop_row_exists(
    pg_db: str,
) -> None:
    with _store_on(pg_db) as (engine, store), _store_on(pg_db) as (probe_engine, _unused):
        _seed_parent_chain(engine)
        adapter = _ObservingAdapter(probe_engine)

        outcome = await _run_plan(adapter, intent_store=store)

        assert outcome == ExecutionOutcome(is_no_trade=False, reason_code="OK")
        # place_entry: ENTRY already SENT, no protective row yet.
        assert adapter.seen_at_place_entry == [{"ENTRY": "SENT"}]
        # D-10: the manager places no protective order and writes no STOP_LOSS row.
        assert adapter.seen_at_place_algo == []
        assert adapter.calls_to("place_algo_protective") == []

        assert _statuses(engine) == {"ENTRY": "ACKED"}
        assert _outcome_columns(engine) == (True, False, "OK")


async def test_the_coordinator_writes_the_stop_loss_intent_ahead_of_the_stop(pg_db: str) -> None:
    """D-14 now lives in the coordinator: after the first fill the STOP_LOSS row is committed
    INTENDED then SENT BEFORE `place_algo_protective`, and ACKED only after the REST query of
    the stop answers ACTIVE. The manager hands the entry over through the real coordinator."""
    from src.execution.protection import ProtectionCoordinator, ProtectionState

    from tests.support.execution_limits import test_only_execution_limits
    from tests.support.protection_doubles import (
        RecordingAlerts,
        RecordingSafeMode,
        ScriptedEmergencyCloser,
    )
    from tests.support.stream_sinks import RecordingJournal
    from tests.support.virtual_time import VirtualTime
    from tests.test_execution_manager import _build_live_context

    with _store_on(pg_db) as (engine, store), _store_on(pg_db) as (probe_engine, _unused):
        _seed_parent_chain(engine)
        adapter = _ObservingAdapter(probe_engine, enforce_flat_stop_rejection=True)
        clock = VirtualTime()
        coordinator = ProtectionCoordinator(
            adapter=adapter,
            intent_store=store,
            journal=RecordingJournal(),
            safe_mode_controller=RecordingSafeMode(),
            alert_sink=RecordingAlerts(),
            emergency_closer=ScriptedEmergencyCloser(),
            limits=test_only_execution_limits(),
            clock=clock,
        )
        live = _build_live_context(CASE, protection_registry=coordinator)

        outcome = await _run_plan(adapter, intent_store=store, live_context=live)

        assert outcome == ExecutionOutcome(is_no_trade=False, reason_code="OK")
        assert _statuses(engine) == {"ENTRY": "ACKED"}
        before = coordinator.protection_of(PLAN_HASH)
        assert before is not None and before.state is ProtectionState.AWAITING_FILL
        assert adapter.calls_to("place_algo_protective") == []  # nothing before a fill

        adapter.fill(ENTRY_CLIENT_ID)  # the whole entry fills on the exchange
        await coordinator.step()

        # The stop went out with STOP_LOSS already SENT in the committed rows.
        assert adapter.seen_at_place_algo == [{"ENTRY": "ACKED", "STOP_LOSS": "SENT"}]
        placed = adapter.calls_to("place_algo_protective")
        assert len(placed) == 1
        assert placed[0]["kwargs"]["client_algo_id"] == SL_ALGO_ID
        assert placed[0]["kwargs"]["close_position"] is True
        # The placement step leaves the row SENT: a placement answer alone never protects (D-11).
        assert _statuses(engine) == {"ENTRY": "ACKED", "STOP_LOSS": "SENT"}
        # ACKED only after the REST query of the stop answers ACTIVE (the next step).
        await coordinator.step()
        assert adapter.calls_to("query_algo_order_by_client")
        assert _statuses(engine) == {"ENTRY": "ACKED", "STOP_LOSS": "ACKED"}
        after = coordinator.protection_of(PLAN_HASH)
        assert after is not None
        assert after.state in (ProtectionState.PROTECTED, ProtectionState.PROTECTED_ENTRY_OPEN)
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
        assert stop_loss["sent_at_utc"] == clock.now()


# --------------------------------------------------------------------------- #
# Crash injection after every write-ahead step, then restart on a fresh engine.
# --------------------------------------------------------------------------- #

# step -> (rows left behind, place_entry calls made before the crash). Plan 19-15: the manager
# writes only the ENTRY steps; the STOP_LOSS steps belong to the coordinator (test below).
_CRASH_MATRIX: list[tuple[str, dict[str, str], int]] = [
    ("consume", {"ENTRY": "INTENDED"}, 0),
    ("entry_sent", {"ENTRY": "SENT"}, 0),
    ("entry_result", {"ENTRY": "ACKED"}, 1),
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
        assert _statuses(engine2) == {"ENTRY": "ACKED"}


# --------------------------------------------------------------------------- #
# Complete run, then restart.
# --------------------------------------------------------------------------- #


async def test_restart_after_a_complete_run_returns_the_stored_outcome(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        first = await _run_plan(adapter, intent_store=store)
        assert first == ExecutionOutcome(is_no_trade=False, reason_code="OK")
        assert _statuses(engine) == {"ENTRY": "ACKED"}

    adapter.fill(ENTRY_CLIENT_ID)
    calls_before_restart = len(adapter.calls)

    with _store_on(pg_db) as (engine2, restarted_store):
        second = await _run_plan(adapter, intent_store=restarted_store)
        assert second == first
        assert len(adapter.calls) == calls_before_restart
        assert len(adapter.calls_to("place_entry")) == 1
        assert _statuses(engine2) == {"ENTRY": "ACKED"}


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
