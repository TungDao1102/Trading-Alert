"""The SHADOW chain in the running process on the real PostgreSQL stores (plan 16-31).

`PgShadowStores` is the production persistence of the chain: the Phase 17 entity, approval and
journal stores plus the two sweep readers and the three single-row readers the running process
needs. These tests run the same session as `tests/test_paper_shadow_runtime.py` on a generated
database cloned from the alembic-built template (`tests/pg_support.py`): alert, APPROVE, CONFIRM,
fill, stop, and a restart that rebuilds the open position from the journal alone.

Without `TEST_DATABASE_URL` the tests skip locally and fail under `TRADING_CI_STRICT=1`. No network,
no real Telegram.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.domain.enums import ApprovalAction
from src.paper.shadow_confirm import EVENT_SHADOW_CONFIRM_ISSUED, EVENT_SHADOW_CONFIRMED
from src.paper.shadow_ledger import (
    EVENT_SHADOW_POSITION_OPENED,
    EVENT_SHADOW_RESERVATION_REFUSED,
)
from src.paper.shadow_runtime import (
    EVENT_SHADOW_PLAN_CONTEXT,
    EVENT_SHADOW_POSITION_CLOSED,
)
from src.persistence.engine import make_sync_engine
from src.persistence.shadow_stores import PgShadowStores
from src.persistence.uow import OperationalDatabase

from tests.test_paper_shadow_runtime import (
    ETH,
    MINUTE,
    Rig,
    _refusal_code,
    _two_confirms_one_unsizable,
    _uninterrupted,
    after_minutes,
    poll_at,
)


@contextmanager
def pg_stores(url: str) -> Iterator[tuple[Engine, PgShadowStores]]:
    engine = make_sync_engine(url)
    try:
        yield engine, PgShadowStores(OperationalDatabase(engine))
    finally:
        engine.dispose()


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


def approve_row_id(engine: Engine) -> str:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT approval_id FROM approvals WHERE action = :a AND status = 'APPROVED'"),
            {"a": ApprovalAction.APPROVE.value},
        ).all()
    assert len(rows) == 1, "exactly one decided APPROVE row"
    return str(rows[0][0])


async def test_the_chain_runs_end_to_end_on_postgresql(pg_db: str) -> None:
    reference = await _uninterrupted([after_minutes(5)])
    with pg_stores(pg_db) as (engine, stores):
        rig = Rig(stores=cast(Any, stores))
        await rig.approve_and_confirm()
        await poll_at(rig, after_minutes(5))

        correlation = f"shadow-confirm:{approve_row_id(engine)}"
        assert journal_types(engine, correlation) == [
            EVENT_SHADOW_CONFIRM_ISSUED,
            EVENT_SHADOW_CONFIRMED,
            EVENT_SHADOW_POSITION_OPENED,
            EVENT_SHADOW_POSITION_CLOSED,
        ]
        with engine.connect() as conn:
            contexts = conn.execute(
                text("SELECT payload_json FROM journal_events WHERE event_type = :t"),
                {"t": EVENT_SHADOW_PLAN_CONTEXT},
            ).all()
        assert len(contexts) == 1
        assert json.loads(str(contexts[0][0]))["regime"] == "TREND"
        assert rig.ledger.ledger == reference.ledger.ledger


async def test_a_restart_on_postgresql_rebuilds_the_open_position(pg_db: str) -> None:
    reference = await _uninterrupted([after_minutes(5), after_minutes(6)])
    with pg_stores(pg_db) as (_engine, stores):
        first = Rig(stores=cast(Any, stores))
        await first.approve_and_confirm()
        await poll_at(first, after_minutes(3))  # filled and open
        public, bot = first.public, first.bot

    with pg_stores(pg_db) as (engine, stores):
        restarted = Rig(
            stores=cast(Any, stores),
            public=public,
            bot=bot,
            now=after_minutes(3) + MINUTE,
        )
        await restarted.coordinator.start()
        await poll_at(restarted, after_minutes(5))
        await poll_at(restarted, after_minutes(6))

        correlation = f"shadow-confirm:{approve_row_id(engine)}"
        types = journal_types(engine, correlation)
        assert types.count(EVENT_SHADOW_POSITION_OPENED) == 1
        assert types.count(EVENT_SHADOW_POSITION_CLOSED) == 1
        assert restarted.ledger.ledger == reference.ledger.ledger


def refused_rows(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT payload_json, approval_id, trade_plan_id FROM journal_events "
                "WHERE event_type = :t ORDER BY journal_event_id"
            ),
            {"t": EVENT_SHADOW_RESERVATION_REFUSED},
        ).all()
    return [
        {"payload": json.loads(str(r[0])), "approval_id": r[1], "trade_plan_id": r[2]} for r in rows
    ]


async def test_a_reservation_that_cannot_open_is_refused_once_on_postgresql(pg_db: str) -> None:
    code = _refusal_code()
    with pg_stores(pg_db) as (engine, stores):
        rig = await _two_confirms_one_unsizable(drive=False, stores=cast(Any, stores))
        first = rig.restart(now=rig.now + MINUTE)
        await first.coordinator.restore()  # must not raise
        (row,) = refused_rows(engine)
        assert row["payload"]["reason"] == code
        assert row["approval_id"] is not None and row["trade_plan_id"] is not None
        assert [p.symbol for p in first.coordinator.open_positions()] == [ETH]

        second = first.restart(now=first.now + MINUTE)
        await second.coordinator.restore()
        await poll_at(second, after_minutes(3))
        assert len(refused_rows(engine)) == 1, "a second restore writes nothing new"
