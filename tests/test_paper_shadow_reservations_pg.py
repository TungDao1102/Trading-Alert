"""SHADOW reservations on the real Phase 17 PostgreSQL journal (Phase 16, plan 16-23).

The recovery events must be replay-idempotent on `PgJournalStore.append`: the same
`journal_event_id` with identical identity fields and payload is a no-op, a different payload
raises `JournalConflict`, and a missing parent row raises `ParentRowMissing`. These tests run the
reservation lifecycle across process restarts on a generated database cloned from the alembic
template (`tests/pg_support.py`). Without `TEST_DATABASE_URL` they skip locally and fail under
`TRADING_CI_STRICT=1`. No network, no real Telegram.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.db.models import JournalEventRow
from src.domain.journal import JournalEvent
from src.paper.shadow import ConfirmOutcome
from src.paper.shadow_confirm import EVENT_SHADOW_CONFIRMED
from src.paper.shadow_ledger import (
    EVENT_SHADOW_PLAN_EXPIRED_UNFILLED,
    ReservationBasis,
    ShadowLedger,
    ShadowReservations,
)
from src.persistence.errors import JournalConflict, ParentRowMissing

from tests.shadow_fakes import CHAT_ID, T0, USER_ID
from tests.test_paper_shadow_confirm import T_PRESS, Harness
from tests.test_paper_shadow_pg import approved_id, count, journal_types, process_on
from tests.test_paper_shadow_reservations import EQUITY, PARAMS, QTY, START

PLAN_EXPIRY = T0 + timedelta(hours=4)


def _reservations(stores: Any, risk: str = "10") -> tuple[ShadowLedger, ShadowReservations]:
    ledger = ShadowLedger(initial_equity=EQUITY, parameter_set_params=PARAMS, started_at_utc=START)
    basis = ReservationBasis(Decimal(risk), QTY)
    return ledger, ShadowReservations(ledger, stores, basis_for=lambda signal, plan: basis)


async def test_confirm_reserves_and_a_restart_rebuilds_from_the_pg_journal(pg_db: str) -> None:
    with process_on(pg_db) as first:
        _ledger, reservations = _reservations(first.stores)
        h = Harness(stores=first.stores, reservations=reservations)
        short_id = await h.approve()
        result = h.confirm.handle_confirm(
            short_id=short_id,
            chat_id=CHAT_ID,
            authorized_chat_id=CHAT_ID,
            from_user_id=USER_ID,
            now_utc=T_PRESS + timedelta(seconds=12),
            correlation_id="cb-1",
        )
        assert result.outcome is ConfirmOutcome.CONFIRMED
        approval_id = approved_id(first.engine)
        assert len(reservations.pending_reservations()) == 1

    with process_on(pg_db) as second:
        ledger2, restarted = _reservations(second.stores)
        report = restarted.rebuild_from_records(
            restarted.load_records(), None, now_utc=T_PRESS + timedelta(hours=1)
        )
        assert report.restored_reservations == (approval_id,)
        positions, _loss = ledger2.risk_inputs(T_PRESS + timedelta(hours=1))
        assert [(p.symbol, p.open_risk) for p in positions] == [("BTCUSDT", Decimal("10"))]


async def test_expiry_while_offline_is_recorded_once_across_two_restarts(pg_db: str) -> None:
    with process_on(pg_db) as first:
        _ledger, reservations = _reservations(first.stores)
        h = Harness(stores=first.stores, reservations=reservations)
        short_id = await h.approve()
        h.confirm.handle_confirm(
            short_id=short_id,
            chat_id=CHAT_ID,
            authorized_chat_id=CHAT_ID,
            from_user_id=USER_ID,
            now_utc=T_PRESS + timedelta(seconds=12),
            correlation_id="cb-1",
        )
        approval_id = approved_id(first.engine)
        correlation = f"shadow-confirm:{approval_id}"

    for restart_clock in (PLAN_EXPIRY + timedelta(minutes=3), PLAN_EXPIRY + timedelta(days=20)):
        with process_on(pg_db) as proc:
            ledger, restarted = _reservations(proc.stores)
            report = restarted.rebuild_from_records(
                restarted.load_records(), None, now_utc=restart_clock
            )
            assert report.restored_reservations == ()
            positions, _loss = ledger.risk_inputs(restart_clock)
            assert positions == []
            types = journal_types(proc.engine, correlation)
            assert types.count(EVENT_SHADOW_PLAN_EXPIRED_UNFILLED) == 1
            assert types.count(EVENT_SHADOW_CONFIRMED) == 1


async def test_pg_journal_rules_for_the_release_event(pg_db: str) -> None:
    with process_on(pg_db) as proc:
        _ledger, reservations = _reservations(proc.stores)
        h = Harness(stores=proc.stores, reservations=reservations)
        short_id = await h.approve()
        h.confirm.handle_confirm(
            short_id=short_id,
            chat_id=CHAT_ID,
            authorized_chat_id=CHAT_ID,
            from_user_id=USER_ID,
            now_utc=T_PRESS + timedelta(seconds=12),
            correlation_id="cb-1",
        )
        assert reservations.release_expired(PLAN_EXPIRY) != []
        correlation = f"shadow-confirm:{approved_id(proc.engine)}"
        (released,) = [
            e
            for e in proc.stores.journal_for_correlation(correlation)
            if e.event_type == EVENT_SHADOW_PLAN_EXPIRED_UNFILLED
        ]
        rows = count(proc.engine, JournalEventRow)

        # The same id with the same payload (a re-run recovery): an idempotent no-op.
        proc.stores.record_journal(released)
        assert count(proc.engine, JournalEventRow) == rows

        # The same id with a different payload: a conflict, never a silent overwrite.
        body = json.loads(released.payload_json)
        body["plan_expiry_utc"] = (PLAN_EXPIRY + timedelta(hours=1)).isoformat()
        changed = JournalEvent(
            journal_event_id=released.journal_event_id,
            occurred_at_utc=released.occurred_at_utc,
            event_type=released.event_type,
            entity_type=released.entity_type,
            entity_id=released.entity_id,
            correlation_id=released.correlation_id,
            signal_id=released.signal_id,
            trade_plan_id=released.trade_plan_id,
            approval_id=released.approval_id,
            payload_json=json.dumps(body, sort_keys=True, separators=(",", ":")),
        )
        with pytest.raises(JournalConflict):
            proc.stores.record_journal(changed)

        # A parent row that does not exist: refused.
        orphan = JournalEvent(
            journal_event_id="shadow-rsv_" + "e" * 64,
            occurred_at_utc=PLAN_EXPIRY,
            event_type=EVENT_SHADOW_PLAN_EXPIRED_UNFILLED,
            entity_type="ShadowReservation",
            entity_id="missing",
            correlation_id="shadow-confirm:missing",
            trade_plan_id="f" * 64,
            payload_json="{}",
        )
        with pytest.raises(ParentRowMissing):
            proc.stores.record_journal(orphan)
