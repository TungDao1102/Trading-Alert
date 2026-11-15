"""PostgreSQL journal store: durable, append-only, replay-idempotent (Phase 17-08, D-10, F-412).

`PgJournalStore` is the production implementation behind every journal-first controller
(`JournalLike.record`) and the Telegram callback receipt (`JournalReceipt`). The behaviors
pinned here:

  - round trip through `journal_to_row` / `journal_from_row`;
  - a replayed event (same id, same identity fields and payload) is a no-op, even with a
    later `occurred_at_utc` (a redelivered callback carries a new delivery time);
  - the same id with anything else different raises `JournalConflict` and the stored row is
    untouched (the audit trail never silently drops a colliding different event);
  - `append(tx, event)` joins a caller-owned unit of work (commit both or neither);
  - a missing parent row is `ParentRowMissing`; an unreachable database is `StoreUnavailable`;
  - the store has no update/delete method and the database trigger refuses a bypassing writer;
  - the existing controllers write rows through the store with no signature change.

Every test runs on a generated `t17_<hex>_test` database cloned from an alembic-built
template (`tests/pg_support.py`).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from src.adapters.telegram_callbacks import (
    _build_callback_receipt,
    parse_callback_data,
)
from src.db.models import ApprovalRow, JournalEventRow
from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.enablement import LiveEnablementController
from src.persistence.engine import make_sync_engine
from src.persistence.errors import JournalConflict, ParentRowMissing, StoreUnavailable
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase
from src.reconcile.safe_mode import SafeModeController
from src.reconcile.sweeper import OrphanSweeper

from tests.support.pg_rows import T0, T1, hexid, make_approval, make_plan, make_signal

T_LATER = T0 + timedelta(seconds=7)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def db(engine: Engine) -> OperationalDatabase:
    return OperationalDatabase(engine)


@pytest.fixture
def store(db: OperationalDatabase) -> PgJournalStore:
    return PgJournalStore(db)


def _event(
    n: int = 1,
    *,
    occurred_at_utc: datetime = T0,
    payload: dict[str, Any] | None = None,
    **overrides: Any,
) -> JournalEvent:
    payload_json = json.dumps(payload if payload is not None else {"n": n}, sort_keys=True)
    values: dict[str, Any] = {
        "journal_event_id": content_hash_event_id(
            prefix="t",
            event_type="TEST_EVENT",
            entity_id=f"entity-{n}",
            occurred_at_utc=T0,
            payload_json=json.dumps({"n": n}, sort_keys=True),
        ),
        "occurred_at_utc": occurred_at_utc,
        "event_type": "TEST_EVENT",
        "entity_type": "Test",
        "entity_id": f"entity-{n}",
        "correlation_id": f"corr-{n}",
        "payload_json": payload_json,
    }
    values.update(overrides)
    return JournalEvent(**values)


def _count(engine: Engine, table: str = "journal_events") -> int:
    with Session(engine) as session:
        return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def _seed_parents(session: Session) -> None:
    session.add(make_signal(1))
    session.flush()
    session.add(make_plan(1, 1))
    session.flush()
    session.add(make_approval(1, 1, 1))
    session.flush()


# --------------------------------------------------------------------------- #
# Round trip and replay idempotency.
# --------------------------------------------------------------------------- #


def test_record_then_get_round_trips(store: PgJournalStore) -> None:
    event = _event(1, signal_id=None, payload={"k": "v", "amount": "1.50"})
    store.record(event)

    stored = store.get(event.journal_event_id)

    assert stored == event
    assert stored is not None
    assert stored.occurred_at_utc.utcoffset() == timedelta(0)


def test_get_returns_none_for_an_unknown_id(store: PgJournalStore) -> None:
    assert store.get(hexid(0xDEAD)) is None


def test_record_twice_leaves_one_row(engine: Engine, store: PgJournalStore) -> None:
    event = _event(1)

    store.record(event)
    store.record(event)

    assert _count(engine) == 1


def test_replay_with_a_later_delivery_time_is_a_noop_and_keeps_the_first(
    engine: Engine, store: PgJournalStore
) -> None:
    first = _event(1, occurred_at_utc=T0, created_at_utc=T0)
    replay = _event(1, occurred_at_utc=T_LATER, created_at_utc=T_LATER)
    assert first.journal_event_id == replay.journal_event_id

    store.record(first)
    store.record(replay)

    assert _count(engine) == 1
    stored = store.get(first.journal_event_id)
    assert stored is not None
    assert stored.occurred_at_utc == T0
    assert stored.created_at_utc == T0


def test_callback_receipts_with_different_delivery_times_produce_one_row(
    engine: Engine, store: PgJournalStore
) -> None:
    parsed = parse_callback_data("APR:" + "a" * 32)
    first = _build_callback_receipt(
        parsed=parsed, callback_chat_id=42, callback_at_utc=T0, correlation_id="cbq:777"
    )
    redelivered = _build_callback_receipt(
        parsed=parsed, callback_chat_id=42, callback_at_utc=T_LATER, correlation_id="cbq:777"
    )
    assert first.journal_event_id == redelivered.journal_event_id

    receipt = store.record  # the callback JournalReceipt is the bound method
    receipt(first)
    receipt(redelivered)

    assert _count(engine) == 1


# --------------------------------------------------------------------------- #
# Conflict detection (F-412, T-17-20, T-17-21).
# --------------------------------------------------------------------------- #


def test_same_id_with_a_different_payload_raises_and_leaves_the_row_unchanged(
    engine: Engine, store: PgJournalStore
) -> None:
    original = _event(1, payload={"secret_marker": "ORIGINAL-PAYLOAD-TEXT"})
    different = _event(
        1,
        journal_event_id=original.journal_event_id,
        payload={"secret_marker": "DIFFERENT-PAYLOAD-TEXT"},
    )
    store.record(original)

    with pytest.raises(JournalConflict) as info:
        store.record(different)

    message = str(info.value)
    assert original.journal_event_id in message
    assert "payload_json" in message
    assert "ORIGINAL-PAYLOAD-TEXT" not in message
    assert "DIFFERENT-PAYLOAD-TEXT" not in message
    assert store.get(original.journal_event_id) == original
    assert _count(engine) == 1


def test_same_id_with_a_different_entity_names_the_differing_fields(
    store: PgJournalStore,
) -> None:
    original = _event(1)
    different = _event(
        1,
        journal_event_id=original.journal_event_id,
        entity_id="another-entity",
        correlation_id="another-corr",
        payload=json.loads(original.payload_json),
    )
    store.record(original)

    with pytest.raises(JournalConflict) as info:
        store.record(different)

    message = str(info.value)
    assert "entity_id" in message
    assert "correlation_id" in message
    assert store.get(original.journal_event_id) == original


# --------------------------------------------------------------------------- #
# Unit of work.
# --------------------------------------------------------------------------- #


def test_append_commits_with_a_caller_owned_insert(
    engine: Engine, db: OperationalDatabase, store: PgJournalStore
) -> None:
    event = _event(1, signal_id=hexid(1), trade_plan_id=hexid(0x1001), approval_id=hexid(0x2001))

    with db.transaction() as tx:
        _seed_parents(tx)
        store.append(tx, event)

    assert _count(engine) == 1
    assert _count(engine, "approvals") == 1


def test_append_rolls_back_together_with_the_caller_work(
    engine: Engine, db: OperationalDatabase, store: PgJournalStore
) -> None:
    event = _event(1)

    with pytest.raises(RuntimeError, match="boom"), db.transaction() as tx:
        _seed_parents(tx)
        store.append(tx, event)
        raise RuntimeError("boom")

    assert _count(engine) == 0
    assert _count(engine, "approvals") == 0


def test_missing_parent_raises_parent_row_missing(engine: Engine, store: PgJournalStore) -> None:
    orphan_event = _event(1, approval_id=hexid(0x2999))

    with pytest.raises(ParentRowMissing):
        store.record(orphan_event)

    assert _count(engine) == 0


def test_parent_inserted_first_in_the_same_unit_of_work_succeeds(
    engine: Engine, db: OperationalDatabase, store: PgJournalStore
) -> None:
    event = _event(1, approval_id=hexid(0x2001))

    with db.transaction() as tx:
        _seed_parents(tx)
        store.append(tx, event)

    stored = store.get(event.journal_event_id)
    assert stored is not None
    assert stored.approval_id == hexid(0x2001)
    with Session(engine) as session:
        assert session.get(ApprovalRow, hexid(0x2001)) is not None


# --------------------------------------------------------------------------- #
# Reads.
# --------------------------------------------------------------------------- #


def test_list_by_correlation_orders_by_time_then_id(store: PgJournalStore) -> None:
    same_time_b = _event(2, correlation_id="shared", journal_event_id="b" * 64, occurred_at_utc=T0)
    same_time_a = _event(3, correlation_id="shared", journal_event_id="a" * 64, occurred_at_utc=T0)
    earlier = _event(
        4,
        correlation_id="shared",
        journal_event_id="f" * 64,
        occurred_at_utc=T0 - timedelta(minutes=1),
    )
    other = _event(5, correlation_id="elsewhere")
    for event in (same_time_b, other, same_time_a, earlier):
        store.record(event)

    listed = store.list_by_correlation("shared")

    assert [e.journal_event_id for e in listed] == ["f" * 64, "a" * 64, "b" * 64]
    assert store.list_by_correlation("nobody") == []


# --------------------------------------------------------------------------- #
# Append-only (D-10).
# --------------------------------------------------------------------------- #


def test_the_store_exposes_no_update_or_delete_method() -> None:
    public = {name for name in dir(PgJournalStore) if not name.startswith("_")}
    assert public == {"record", "append", "get", "list_by_correlation"}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE journal_events SET event_type = 'TAMPERED'",
        "DELETE FROM journal_events",
        "TRUNCATE journal_events CASCADE",
    ],
)
def test_a_bypassing_writer_is_refused_by_the_trigger(
    engine: Engine, store: PgJournalStore, statement: str
) -> None:
    event = _event(1)
    store.record(event)

    with pytest.raises(DBAPIError) as info, Session(engine) as session, session.begin():
        session.execute(text(statement))

    assert "append-only" in str(info.value)
    assert store.get(event.journal_event_id) == event


def test_raw_session_update_through_the_orm_is_refused(
    engine: Engine, store: PgJournalStore
) -> None:
    event = _event(1)
    store.record(event)

    with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
        row = session.get(JournalEventRow, event.journal_event_id)
        assert row is not None
        row.event_type = "TAMPERED"
        session.flush()

    assert store.get(event.journal_event_id) == event


# --------------------------------------------------------------------------- #
# Outage (D-04, Pitfall 9).
# --------------------------------------------------------------------------- #


def test_an_unreachable_database_raises_store_unavailable() -> None:
    dead = create_engine(
        "postgresql+psycopg://nobody:nopass@127.0.0.1:1/none",
        poolclass=NullPool,
        connect_args={"connect_timeout": 2},
    )
    store = PgJournalStore(OperationalDatabase(dead))
    try:
        with pytest.raises(StoreUnavailable) as info:
            store.record(_event(1))
        assert "nopass" not in str(info.value)
    finally:
        dead.dispose()


# --------------------------------------------------------------------------- #
# Controller wiring through PostgreSQL (signatures accepted unchanged).
# --------------------------------------------------------------------------- #


def _passing_health_verdict() -> Any:
    from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks

    return run_health_checks(
        results=[
            HealthCheckResult(check_name=name, status="PASS", detail="ok", observed_at_utc=T0)
            for name in ALL_CHECK_NAMES
        ]
    )


def _event_types(engine: Engine) -> list[str]:
    with Session(engine) as session:
        return list(
            session.execute(
                select(JournalEventRow.event_type).order_by(
                    JournalEventRow.occurred_at_utc, JournalEventRow.journal_event_id
                )
            ).scalars()
        )


def test_enablement_controller_writes_rows_through_the_store(
    engine: Engine, store: PgJournalStore
) -> None:
    controller = LiveEnablementController(journal=store)

    controller.enable(
        operator_id="operator-1",
        now_utc=T0,
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    controller.disable(operator_id="operator-1", now_utc=T1)

    assert _event_types(engine) == ["LIVE_ORDERS_ENABLED", "LIVE_ORDERS_DISABLED"]


def test_safe_mode_controller_writes_a_row_through_the_store(
    engine: Engine, store: PgJournalStore
) -> None:
    controller = SafeModeController(adapter=SimpleNamespace(), journal=store)  # type: ignore[arg-type]

    controller.enter_safe_mode(reason="DIVERGENCE", now_utc=T0)

    assert controller.in_safe_mode is True
    assert _event_types(engine) == ["SAFE_MODE_ENTER"]


class _SweepAdapter:
    def __init__(self) -> None:
        self.cancelled: list[tuple[str, str]] = []

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any:
        # Plan 20-11: the sweeper verifies the cancel, so the order is gone after the cancel.
        if self.cancelled:
            return SimpleNamespace(found=False, algo_status=None, update_time_utc=None)
        return SimpleNamespace(found=True, algo_status="NEW", update_time_utc=T0)

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None:
        self.cancelled.append((symbol, client_algo_id))


def test_orphan_sweeper_pre_cancel_event_is_a_row_in_the_store(
    engine: Engine, store: PgJournalStore
) -> None:
    adapter = _SweepAdapter()
    sweeper = OrphanSweeper(adapter=adapter, journal=store, now_utc=T0)
    orphan = SimpleNamespace(symbol="BTCUSDT", client_algo_id="xa-" + "1" * 31 + "SL")
    diff = SimpleNamespace(orphan_protectives=[orphan])

    outcome = asyncio.run(sweeper.sweep(diff, position_verifier=lambda **_: Decimal("0")))

    assert outcome.swept_count == 1
    assert adapter.cancelled == [("BTCUSDT", orphan.client_algo_id)]
    with Session(engine) as session:
        phases = [
            json.loads(payload)["phase"]
            for payload in session.execute(
                select(JournalEventRow.payload_json).where(
                    JournalEventRow.event_type == "ORPHAN_SWEEP"
                )
            ).scalars()
        ]
    assert sorted(phases) == ["post_cancel", "pre_cancel"]
    with Session(engine) as session:
        total = session.execute(select(func.count()).select_from(JournalEventRow)).scalar_one()
    assert total == 2
