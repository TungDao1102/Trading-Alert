"""The SHADOW APPROVE then CONFIRM chain on the real Phase 17 PostgreSQL stores (plan 16-11).

D-16 and D-04: persistence of the SHADOW approval front half and of the D041 confirm step goes
through `PgApprovalStore`, `PgTradingEntityStore` and `PgJournalStore` behind the `ShadowStores`
and `ConfirmStores` ports, with parents written first, one decided approval per plan
(`uq_approvals_one_decided_per_plan`) and deterministic journal ids so that replaying a callback
writes no new row and raises no `JournalConflict`.

Every test runs on a generated database cloned from the alembic-built template
(`tests/pg_support.py`). Without `TEST_DATABASE_URL` the tests skip locally and fail under
`TRADING_CI_STRICT=1`. No network, no real Telegram.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from src.approval.mapping import ShortIdMapping
from src.db.mappers import approval_from_row
from src.db.models import ApprovalRow, JournalEventRow, SignalRow, TradePlanRow
from src.domain.approval import Approval
from src.domain.enums import ApprovalResult
from src.domain.journal import JournalEvent
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper.shadow_confirm import (
    EVENT_SHADOW_CONFIRM_EXPIRED,
    EVENT_SHADOW_CONFIRM_ISSUED,
    EVENT_SHADOW_CONFIRM_REJECTED,
    EVENT_SHADOW_CONFIRMED,
    ConfirmBook,
    assert_no_stranded_approvals,
)
from src.persistence.approvals import PgApprovalStore
from src.persistence.engine import make_sync_engine
from src.persistence.entities import PgTradingEntityStore
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase
from telegram import error as tg_error

from tests.test_paper_shadow_confirm import T_PRESS, Harness


class PgShadowStores:
    """The `ShadowStores` and `ConfirmStores` ports over the Phase 17 PostgreSQL stores.

    The PG approval store has no list readers yet (plan 16-31 adds them to the runtime
    composition), so the two sweep inputs are read here with plain selects.
    """

    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db
        self._entities = PgTradingEntityStore(db)
        self._approvals = PgApprovalStore(db)
        self._journal = PgJournalStore(db)

    def insert_signal(self, signal: Signal) -> None:
        self._entities.insert_signal(signal)

    def insert_trade_plan(self, plan: TradePlan) -> None:
        self._entities.insert_trade_plan(plan)

    def insert_pending(self, approval: Approval) -> None:
        self._approvals.insert_pending(approval)

    def record_short_id_mapping(self, mapping: ShortIdMapping) -> None:
        self._approvals.record_short_id_mapping(mapping)

    def save_atomic(self, approval: Approval, mapping: ShortIdMapping | None) -> None:
        self._approvals.save_atomic(approval, mapping)

    def lookup_by_token_hash(self, token_hash: str) -> Approval | None:
        return self._approvals.lookup_by_token_hash(token_hash)

    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None:
        return self._approvals.lookup_by_short_id(short_id)

    def record_journal(self, event: JournalEvent) -> None:
        self._journal.record(event)

    def list_pending_approvals(self) -> list[Approval]:
        return self._by_status(ApprovalResult.PENDING)

    def list_approved_approvals(self) -> list[Approval]:
        return [a for a in self._by_status(ApprovalResult.APPROVED) if a.action.value == "APPROVE"]

    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]:
        return self._journal.list_by_correlation(correlation_id)

    def _by_status(self, status: ApprovalResult) -> list[Approval]:
        with self._db.transaction() as session:
            rows = session.execute(
                select(ApprovalRow).where(ApprovalRow.status == status.value)
            ).scalars()
            return [approval_from_row(row) for row in rows]


@dataclass
class Process:
    """What a (re)started process builds on one database."""

    engine: Engine
    stores: PgShadowStores


@contextmanager
def process_on(url: str) -> Iterator[Process]:
    engine = make_sync_engine(url)
    try:
        yield Process(engine=engine, stores=PgShadowStores(OperationalDatabase(engine)))
    finally:
        engine.dispose()


def count(engine: Engine, model: Any) -> int:
    with engine.connect() as conn:
        value = conn.execute(select(func.count()).select_from(model)).scalar_one()
    return int(value)


def journal_types(engine: Engine, correlation_id: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT event_type FROM journal_events WHERE correlation_id = :c "
                "ORDER BY occurred_at_utc, journal_event_id"
            ),
            {"c": correlation_id},
        ).all()
    return [row[0] for row in rows]


def approved_id(engine: Engine) -> str:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT approval_id FROM approvals WHERE status = 'APPROVED'")
        ).all()
    assert len(rows) == 1, "exactly one decided approval for the plan"
    return str(rows[0][0])


# --------------------------------------------------------------------------- #
# Test 1: the chain writes parents first, one decided approval, and the confirm rows.
# --------------------------------------------------------------------------- #


async def test_alert_approve_confirm_writes_parents_one_decision_and_the_confirm_rows(
    pg_db: str,
) -> None:
    with process_on(pg_db) as proc:
        h = Harness(stores=proc.stores)
        short_id = await h.approve()
        h.now = T_PRESS + timedelta(seconds=12)

        await h.tap(f"CNF:{short_id}", "q-cnf")

        assert count(proc.engine, SignalRow) == 1
        assert count(proc.engine, TradePlanRow) == 1
        with proc.engine.connect() as conn:
            rows = conn.execute(text("SELECT action, status FROM approvals ORDER BY action")).all()
        # Two rows per plan: APPROVE (decided) and SKIP_USER (never decided).
        assert [tuple(r) for r in rows] == [("APPROVE", "APPROVED"), ("SKIP_USER", "PENDING")]
        correlation = f"shadow-confirm:{approved_id(proc.engine)}"
        assert journal_types(proc.engine, correlation) == [
            EVENT_SHADOW_CONFIRM_ISSUED,
            EVENT_SHADOW_CONFIRMED,
        ]
        confirmed = [
            e
            for e in proc.stores.journal_for_correlation(correlation)
            if e.event_type == EVENT_SHADOW_CONFIRMED
        ]
        body = json.loads(confirmed[0].payload_json)
        assert body["confirm_requested_at_utc"] == T_PRESS.isoformat()
        assert body["confirmed_at_utc"] == (T_PRESS + timedelta(seconds=12)).isoformat()
        assert len(h.confirmed) == 1


# --------------------------------------------------------------------------- #
# Test 2: replaying every callback writes no new rows and raises no JournalConflict.
# --------------------------------------------------------------------------- #


async def test_replaying_every_callback_writes_no_new_row(pg_db: str) -> None:
    with process_on(pg_db) as proc:
        h = Harness(stores=proc.stores)
        await h.alert()
        apr, _ = h.alert_buttons()
        short_id = apr.removeprefix("APR:")
        await h.tap(apr, "q-apr")
        h.now = T_PRESS + timedelta(seconds=12)
        await h.tap(f"CNF:{short_id}", "q-cnf")
        before = (
            count(proc.engine, JournalEventRow),
            count(proc.engine, ApprovalRow),
            len(h.confirmed),
        )

        # The same Telegram callback queries delivered a second time (at-least-once).
        await h.tap(apr, "q-apr")
        await h.tap(f"CNF:{short_id}", "q-cnf")
        await h.tap(f"CNF:{short_id}", "q-cnf-again")  # a fresh press: replays the outcome

        after = (
            count(proc.engine, JournalEventRow),
            count(proc.engine, ApprovalRow),
            len(h.confirmed),
        )
        assert after == before
        assert len(h.confirmed) == 1, "never a second position"


# --------------------------------------------------------------------------- #
# Test 3: a restart loses the raw confirm token; a later CONFIRM is rejected.
# --------------------------------------------------------------------------- #


async def test_confirm_after_a_restart_is_rejected_and_the_expiry_row_exists(pg_db: str) -> None:
    with process_on(pg_db) as first:
        h = Harness(stores=first.stores)
        short_id = await h.approve()
        approval_id = approved_id(first.engine)

    with process_on(pg_db) as second:
        restart_at = T_PRESS + timedelta(seconds=20)
        fresh = ConfirmBook(second.stores, clock=lambda: restart_at)
        expired = fresh.expire_on_restart(restart_at)
        assert expired == [approval_id]
        assert fresh.expire_on_restart(restart_at) == []  # idempotent

        h2 = Harness(stores=second.stores)
        h2.now = restart_at
        result = await h2.tap(f"CNF:{short_id}", "q-after-restart")

        assert result.ok is False
        assert h2.confirmed == []
        types = journal_types(second.engine, f"shadow-confirm:{approval_id}")
        assert types == [EVENT_SHADOW_CONFIRM_ISSUED, EVENT_SHADOW_CONFIRM_EXPIRED]
        expiry = [
            e
            for e in second.stores.journal_for_correlation(f"shadow-confirm:{approval_id}")
            if e.event_type == EVENT_SHADOW_CONFIRM_EXPIRED
        ]
        assert json.loads(expiry[0].payload_json)["reason"] == "RUNTIME_RESTART"
        # The refused press is journaled too, linked to the plan through the short-id mapping.
        with second.engine.connect() as conn:
            rejected = conn.execute(
                text("SELECT signal_id, trade_plan_id FROM journal_events WHERE event_type = :t"),
                {"t": EVENT_SHADOW_CONFIRM_REJECTED},
            ).all()
        assert len(rejected) == 1 and rejected[0][0] is not None and rejected[0][1] is not None
        # A decided approval is never reverted.
        assert approved_id(second.engine) == approval_id


# --------------------------------------------------------------------------- #
# Task 4, test 7: a CARD_DELIVERY_FAILED expiry replays on PostgreSQL and strands nothing.
# --------------------------------------------------------------------------- #


async def test_a_card_delivery_failed_expiry_replays_without_a_new_row(pg_db: str) -> None:
    with process_on(pg_db) as proc:
        h = Harness(stores=proc.stores)
        await h.alert()
        h.bot.queue_error(tg_error.BadRequest("Message to edit not found"))
        h.bot.queue_error(tg_error.NetworkError("down"))
        apr, _ = h.alert_buttons()
        await h.tap(apr, "q-apr")
        approval_id = approved_id(proc.engine)
        correlation = f"shadow-confirm:{approval_id}"
        assert journal_types(proc.engine, correlation) == [EVENT_SHADOW_CONFIRM_EXPIRED]
        expired = proc.stores.journal_for_correlation(correlation)[0]
        assert json.loads(expired.payload_json)["reason"] == "CARD_DELIVERY_FAILED"
        rows_before = count(proc.engine, JournalEventRow)

        # The same event written a second time (a redelivered callback, a re-run sweep).
        proc.stores.record_journal(expired)
        ConfirmBook(proc.stores, clock=lambda: T_PRESS).expire_on_restart(T_PRESS)

        assert count(proc.engine, JournalEventRow) == rows_before
        assert_no_stranded_approvals(proc.stores, T_PRESS + timedelta(minutes=5))
        assert approved_id(proc.engine) == approval_id
