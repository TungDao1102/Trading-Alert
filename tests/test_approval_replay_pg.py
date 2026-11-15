"""End-to-end APPROVE replay across a restart and after expiry on PostgreSQL (Phase 17-14).

SC3's user-visible guarantee, APRV-02 across Telegram replays and EXEC-03 across restarts:
the REAL callback dispatch (`dispatch_callback` wired to `PgApprovalStore` and
`PgJournalStore`) feeds the REAL execution path (`execute_approved_plan` with
`PgExecutionStateStore`), and a redelivered callback reaches `place_entry` zero times.

Decisions applied:
  - The short-id mapping is seeded with `PgApprovalStore.record_short_id_mapping` before the
    first callback, as the Phase 23 sender will (dispatch looks it up before any decision).
  - Parents (signal, trade plan, PENDING approval) are written through
    `PgTradingEntityStore` and `PgApprovalStore.insert_pending`, the production write paths.
  - The adapter is the Binance-semantics fake of plan 01. The entry is FILLED between
    deliveries (the exchange would accept the same client id again, F-126), so exchange-side
    dedup could not save a regression; a negative control proves the chain would show it.
  - A "restart" disposes every engine and builds a new engine, new stores and a new
    manager call on the same database (the in-process per-token lock of the replay layer
    survives inside one test process, but it is only a latency optimization, D-17).

The wiring helpers at the top are shared with `tests/test_callback_redelivery_pg.py`.
Every PostgreSQL test runs on a generated database cloned from the migrated template.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.adapters.telegram_callbacks import (
    CallbackKind,
    DispatchResult,
    ParsedCallback,
    dispatch_callback,
)
from src.approval.binding import Callback
from src.approval.mapping import ShortIdMapping, derive_short_id, make_short_id_mapping
from src.approval.tokens import token_hash_of
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalConsumptionStatus,
    ApprovalResult,
    OrderRole,
    RejectionReason,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.signal import Signal
from src.execution.manager import ExecutionOutcome
from src.execution.order_ids import derive_client_order_id
from src.persistence.approvals import PgApprovalStore
from src.persistence.engine import make_sync_engine
from src.persistence.entities import PgTradingEntityStore
from src.persistence.execution_state import PgExecutionStateStore
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.intent_store_fakes import AlwaysWinsIntentStore
from tests.support.press_identity import OWNER_PRESS
from tests.test_execution_manager import (
    _build_approval,
    _build_approved_plan,
    _build_risk_kwargs,
    _load_input,
    _parse_utc,
    _run_plan,
)

CASE = _load_input()
APPROVAL_ID: str = CASE["approval_id"]
TRADE_PLAN_ID: str = CASE["trade_plan_id"]
PLAN_HASH: str = CASE["plan_hash"]
RAW_TOKEN: str = CASE["raw_token"]
WRONG_TOKEN = "raw_token_wrong_" + "z" * 40
CHAT_ID: int = CASE["chat_id"]
SHORT_ID: str = derive_short_id(CASE["signal_id"])
NOW_UTC: datetime = _parse_utc(CASE["now_utc"])
EXPIRY_UTC: datetime = _parse_utc(CASE["expiry_utc"])
AFTER_EXPIRY_UTC: datetime = EXPIRY_UTC + timedelta(hours=1)
ENTRY_CLIENT_ID = derive_client_order_id(plan_hash=PLAN_HASH, role=OrderRole.ENTRY.value)
QUERY_ID = "cbq:1001"
OK = ExecutionOutcome(is_no_trade=False, reason_code="OK")
INVALIDATED = ExecutionOutcome(is_no_trade=True, reason_code=RejectionReason.INVALIDATED.value)


# --------------------------------------------------------------------------- #
# Wiring helpers (imported by tests/test_callback_redelivery_pg.py).
# --------------------------------------------------------------------------- #


@dataclass
class Process:
    """Everything a (re)started process builds on one database."""

    engine: Engine
    db: OperationalDatabase
    approvals: PgApprovalStore
    journal: PgJournalStore
    state: PgExecutionStateStore
    entities: PgTradingEntityStore

    def dispose(self) -> None:
        self.engine.dispose()


@contextmanager
def process_on(url: str) -> Iterator[Process]:
    """A fresh engine and fresh stores, disposed on exit (what a restart rebuilds)."""
    engine = make_sync_engine(url)
    db = OperationalDatabase(engine)
    try:
        yield Process(
            engine=engine,
            db=db,
            approvals=PgApprovalStore(db),
            journal=PgJournalStore(db),
            state=PgExecutionStateStore(db),
            entities=PgTradingEntityStore(db),
        )
    finally:
        engine.dispose()


def seed_parent_chain(proc: Process) -> None:
    """Signal, READY plan, PENDING approval and short-id mapping via the production writers."""
    created = _parse_utc(CASE["created_at_utc"])
    proc.entities.insert_signal(
        Signal(
            signal_id=CASE["signal_id"],
            strategy_id="trend-pullback",
            strategy_version=CASE["strategy_version"],
            parameter_set_id=CASE["parameter_set_id"],
            parameter_set_hash=CASE["parameter_set_hash"],
            symbol=CASE["symbol"],
            direction="LONG",
            setup_type="TREND_PULLBACK_LONG",
            source_timeframe="1h",
            source_candle_close_utc=created,
            detected_at_utc=created,
            status=SignalStatus.DETECTED,
            expires_at_utc=EXPIRY_UTC,
        )
    )
    proc.entities.insert_trade_plan(
        replace(_build_approved_plan(CASE), status=TradePlanStatus.READY)
    )
    pending = replace(
        _build_approval(CASE),
        action=ApprovalAction.APPROVE,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        acted_at_utc=None,
    )
    proc.approvals.insert_pending(pending)
    proc.approvals.record_short_id_mapping(
        make_short_id_mapping(
            signal_id=CASE["signal_id"], trade_plan_id=TRADE_PLAN_ID, created_at_utc=created
        )
    )


def binding_context() -> dict[str, Any]:
    return {
        "plan_hash": PLAN_HASH,
        "strategy_version": CASE["strategy_version"],
        "parameter_set_id": CASE["parameter_set_id"],
        "parameter_set_hash": CASE["parameter_set_hash"],
        "expiry_utc": EXPIRY_UTC,
    }


def execute_callback(raw_token: str, now_utc: datetime) -> Callback:
    """The callback payload the execution manager binds against."""
    return Callback(
        raw_token=raw_token,
        chat_id=CHAT_ID,
        plan_hash=PLAN_HASH,
        strategy_version=CASE["strategy_version"],
        parameter_set_id=CASE["parameter_set_id"],
        parameter_set_hash=CASE["parameter_set_hash"],
        callback_at_utc=now_utc,
        action=ApprovalAction.APPROVE,
    )


def dispatch(
    proc: Process,
    *,
    query_id: str,
    now_utc: datetime,
    raw_token: str = RAW_TOKEN,
    chat_id: int = CHAT_ID,
    kind: CallbackKind = CallbackKind.APPROVE,
    lookup_by_token_hash: Callable[[str], Approval | None] | None = None,
    save_atomic: Callable[[Approval, ShortIdMapping | None], None] | None = None,
) -> DispatchResult:
    """One Telegram delivery through the real dispatch wired to the PostgreSQL stores.

    `lookup_by_token_hash` and `save_atomic` default to the PostgreSQL approval store; a race
    test wraps them to hold two deliveries between the lookup and the decision.
    """
    prefix = "APR:" if kind is CallbackKind.APPROVE else "SKP:"
    return dispatch_callback(
        ParsedCallback(raw=prefix + SHORT_ID, kind=kind, short_id=SHORT_ID),
        callback_chat_id=chat_id,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=now_utc,
        raw_token=raw_token,
        correlation_id=query_id,
        journal_receipt=proc.journal.record,
        lookup_by_short_id=proc.approvals.lookup_by_short_id,
        lookup_by_token_hash=lookup_by_token_hash or proc.approvals.lookup_by_token_hash,
        save_atomic=save_atomic or proc.approvals.save_atomic,
        now_utc=now_utc,
        binding_context=binding_context(),
        **OWNER_PRESS,
    )


async def execute(
    proc: Process,
    adapter: BinanceSemanticsFakeAdapter,
    approval: Approval,
    *,
    now_utc: datetime,
    raw_token: str = RAW_TOKEN,
    intent_store: Any | None = None,
) -> ExecutionOutcome:
    """`execute_approved_plan` with the PostgreSQL intent store and journal."""
    outcome: ExecutionOutcome = await _run_plan(
        adapter,
        callback=execute_callback(raw_token, now_utc),
        approval=approval,
        now_utc=now_utc,
        risk_kwargs={**_build_risk_kwargs(CASE), "now_utc": now_utc},
        intent_store=intent_store if intent_store is not None else proc.state,
        journal=proc.journal,
    )
    return outcome


@dataclass(frozen=True)
class Delivery:
    dispatch: DispatchResult
    outcome: ExecutionOutcome | None  # None: dispatch refused, execution never ran


async def deliver(
    proc: Process,
    adapter: BinanceSemanticsFakeAdapter,
    *,
    query_id: str,
    now_utc: datetime,
    intent_store: Any | None = None,
    lookup_by_token_hash: Callable[[str], Approval | None] | None = None,
    save_atomic: Callable[[Approval, ShortIdMapping | None], None] | None = None,
) -> Delivery:
    """The full chain for one APPROVE delivery: dispatch, then execute when it resolved."""
    result = dispatch(
        proc,
        query_id=query_id,
        now_utc=now_utc,
        lookup_by_token_hash=lookup_by_token_hash,
        save_atomic=save_atomic,
    )
    if not (
        result.ok
        and result.approval is not None
        and result.approval.status is ApprovalResult.APPROVED
    ):
        return Delivery(dispatch=result, outcome=None)
    outcome = await execute(
        proc, adapter, result.approval, now_utc=now_utc, intent_store=intent_store
    )
    return Delivery(dispatch=result, outcome=outcome)


def scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def intent_rows(engine: Engine) -> list[tuple[str, str]]:
    """(role, intent_status) of every execution intent of the approval, role-ordered."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT role, intent_status FROM execution_intents "
                "WHERE approval_id = :a ORDER BY role"
            ),
            {"a": APPROVAL_ID},
        ).all()
    return [(str(role), str(status)) for role, status in rows]


def decided_approvals(engine: Engine) -> list[tuple[str, str]]:
    """(status, consumption_status) of every decided approval row of the plan."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT status, consumption_status FROM approvals "
                "WHERE trade_plan_id = :p AND status <> 'PENDING'"
            ),
            {"p": TRADE_PLAN_ID},
        ).all()
    return [(str(status), str(consumption)) for status, consumption in rows]


# --------------------------------------------------------------------------- #
# Delivery 1, restart, delivery 2 (replay), delivery 3 (after expiry).
# --------------------------------------------------------------------------- #


async def test_replayed_approve_after_restart_reaches_place_entry_zero_times(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()

    with process_on(pg_db) as first_process:
        seed_parent_chain(first_process)
        first = await deliver(first_process, adapter, query_id=QUERY_ID, now_utc=NOW_UTC)

        assert first.dispatch.ok is True
        assert first.dispatch.approval is not None
        assert first.dispatch.approval.status is ApprovalResult.APPROVED
        assert first.outcome == OK
        assert len(adapter.calls_to("place_entry")) == 1

        adapter.fill(ENTRY_CLIENT_ID)  # the exchange would now accept the same id again
        first_process.dispose()  # restart: every pooled connection of the process is gone

    calls_after_first = len(adapter.calls)

    with process_on(pg_db) as restarted:
        second = await deliver(restarted, adapter, query_id=QUERY_ID, now_utc=NOW_UTC)

        # Replay-to-existing: the stored approval comes back, and so does the stored outcome.
        assert second.dispatch.ok is True
        assert second.dispatch.approval is not None
        assert first.dispatch.approval is not None
        # Same decision; the only difference is the consumption stamped between deliveries.
        assert second.dispatch.approval == replace(
            first.dispatch.approval,
            consumption_status=ApprovalConsumptionStatus.CONSUMED,
            consumed_at_utc=NOW_UTC,
        )
        assert second.outcome == OK
        assert len(adapter.calls) == calls_after_first  # zero adapter calls of any kind
        assert len(adapter.calls_to("place_entry")) == 1

        assert intent_rows(restarted.engine) == [("ENTRY", "ACKED")]
        assert decided_approvals(restarted.engine) == [("APPROVED", "CONSUMED")]
        assert scalar(restarted.engine, "SELECT count(*) FROM approvals") == 1


async def test_redelivery_after_expiry_still_returns_the_stored_outcome(pg_db: str) -> None:
    adapter = BinanceSemanticsFakeAdapter()

    with process_on(pg_db) as first_process:
        seed_parent_chain(first_process)
        first = await deliver(first_process, adapter, query_id=QUERY_ID, now_utc=NOW_UTC)
        assert first.outcome == OK
        adapter.fill(ENTRY_CLIENT_ID)
        first_process.dispose()
    calls_after_first = len(adapter.calls)

    with process_on(pg_db) as restarted:
        # The callback layer fails closed once the plan expired (it never executes anything).
        late = dispatch(restarted, query_id=QUERY_ID, now_utc=AFTER_EXPIRY_UTC)
        assert late.ok is False
        assert late.reason_code is RejectionReason.APPROVAL_EXPIRED

        # The execution manager, handed the stored approval with the same identity, returns
        # the stored outcome without placing: the lookup precedes the expiry gate (Open Q2).
        stored = restarted.approvals.lookup_by_token_hash(token_hash_of(RAW_TOKEN))
        assert stored is not None
        assert stored.status is ApprovalResult.APPROVED
        outcome = await execute(restarted, adapter, stored, now_utc=AFTER_EXPIRY_UTC)

        assert outcome == OK
        assert len(adapter.calls) == calls_after_first
        assert len(adapter.calls_to("place_entry")) == 1
        assert intent_rows(restarted.engine) == [("ENTRY", "ACKED")]


async def test_expiry_does_not_unlock_a_plan_that_was_never_executed(pg_db: str) -> None:
    """The stored-outcome lookup only helps a consumed approval: a fresh one still expires."""
    adapter = BinanceSemanticsFakeAdapter()

    with process_on(pg_db) as proc:
        seed_parent_chain(proc)
        decided = replace(
            _build_approval(CASE),
            action=ApprovalAction.APPROVE,
            result=ApprovalResult.APPROVED,
            status=ApprovalResult.APPROVED,
            acted_at_utc=NOW_UTC,
        )
        proc.approvals.save_atomic(decided, None)  # approved but never executed
        outcome = await execute(proc, adapter, decided, now_utc=AFTER_EXPIRY_UTC)

        assert outcome == ExecutionOutcome(
            is_no_trade=True, reason_code=RejectionReason.APPROVAL_EXPIRED.value
        )
        assert adapter.calls == []
        assert intent_rows(proc.engine) == []
        assert decided_approvals(proc.engine) == [("APPROVED", "UNCONSUMED")]


# --------------------------------------------------------------------------- #
# A wrong token never reaches the stored outcome.
# --------------------------------------------------------------------------- #


async def test_wrong_token_for_the_same_short_id_is_invalidated_and_sees_no_outcome(
    pg_db: str,
) -> None:
    adapter = BinanceSemanticsFakeAdapter()

    with process_on(pg_db) as proc:
        seed_parent_chain(proc)
        first = await deliver(proc, adapter, query_id=QUERY_ID, now_utc=NOW_UTC)
        assert first.outcome == OK
        assert first.dispatch.approval is not None
        calls_after_first = len(adapter.calls)

        # Dispatch: the token hash is unknown, so the short id alone decides nothing.
        forged = dispatch(proc, query_id="cbq:1002", now_utc=NOW_UTC, raw_token=WRONG_TOKEN)
        assert forged.ok is False
        assert forged.approval is None
        assert forged.reason_code is RejectionReason.INVALIDATED

        # Execution: handed the stored approval with a wrong token, the identity gate runs
        # before the stored-outcome lookup, so the stored outcome stays hidden (D-16).
        outcome = await execute(
            proc, adapter, first.dispatch.approval, now_utc=NOW_UTC, raw_token=WRONG_TOKEN
        )
        assert outcome == INVALIDATED
        assert outcome != OK
        assert len(adapter.calls) == calls_after_first

        # The stored row is untouched by both attempts.
        assert intent_rows(proc.engine) == [("ENTRY", "ACKED")]
        assert decided_approvals(proc.engine) == [("APPROVED", "CONSUMED")]


# --------------------------------------------------------------------------- #
# Negative control: without the durable row the same chain places a second entry.
# --------------------------------------------------------------------------- #


async def test_negative_control_a_store_that_never_remembers_places_two_entries(
    pg_db: str,
) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    forgetful = AlwaysWinsIntentStore()

    with process_on(pg_db) as proc:
        seed_parent_chain(proc)
        first = await deliver(
            proc, adapter, query_id=QUERY_ID, now_utc=NOW_UTC, intent_store=forgetful
        )
        adapter.fill(ENTRY_CLIENT_ID)
        # 19-REVIEW WR-02: the manager reads the live position before it places; flatten the
        # filled position so that only the durable intent row can stop the second entry.
        for symbol, amount in list(adapter.positions.items()):
            if amount != Decimal("0"):
                adapter._apply_position_delta(symbol, -amount, Decimal("0"))
        second = await deliver(
            proc, adapter, query_id=QUERY_ID, now_utc=NOW_UTC, intent_store=forgetful
        )

        assert first.outcome is not None and first.outcome.is_no_trade is False
        assert second.outcome is not None and second.outcome.is_no_trade is False
        # The exchange freed the id, so it accepted a second entry: the assertions above on
        # the PostgreSQL store (one place_entry) are not vacuous.
        assert len(adapter.calls_to("place_entry")) == 2
        assert intent_rows(proc.engine) == []  # the forgetful store wrote no durable row
