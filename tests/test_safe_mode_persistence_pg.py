"""PgSafeModeStateStore over the system_state_events log (Phase 20, plan 20-06, D-14, F-127).

Pins, against a real PostgreSQL server (each test on a generated `t17_<hex>_test` clone built by
`alembic upgrade head`; no DDL change, the `system_state_events` CHECK already lists SAFE_MODE):

  - `enter_safe_mode` through a controller with a `PgSafeModeStateStore` writes a SAFE_MODE row and
    a `SYSTEM_STATE_CHANGED` journal event, and a second controller from
    `SafeModeController.load` on a fresh engine is in SAFE_MODE with the same reason and time;
  - an empty table loads as None (the default controller, SAFE_MODE off);
  - a stored state the controller cannot parse, and a database that cannot be reached, both start
    the controller IN SAFE_MODE with reason `SAFE_MODE_STATE_UNREADABLE` (fail closed).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.domain.enums import RejectionReason, SystemStateKey
from src.persistence.engine import make_sync_engine
from src.persistence.journal import PgJournalStore
from src.persistence.safe_mode_store import PgSafeModeStateStore
from src.persistence.system_state import PgSystemStateStore
from src.persistence.uow import OperationalDatabase
from src.reconcile.safe_mode import SAFE_MODE_STATE_UNREADABLE, SafeModeController

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)

#: A closed local port: connecting is refused at once, nothing is listening and no secret is used.
UNREACHABLE_URL = "postgresql+psycopg://trading@127.0.0.1:1/unreachable_test"


class _NoAdapter:
    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]:
        return []

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]:
        return []

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]:
        return []


class _MemoryJournal:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


def _clean_compare(**_kwargs: Any) -> Any:
    return SimpleNamespace(agreement=True)


def _open(
    url: str,
) -> tuple[Callable[[], None], Engine, PgJournalStore, PgSystemStateStore, PgSafeModeStateStore]:
    engine = make_sync_engine(url)
    db = OperationalDatabase(engine)
    journal = PgJournalStore(db)
    system_state = PgSystemStateStore(db, journal)
    return engine.dispose, engine, journal, system_state, PgSafeModeStateStore(system_state)


def _count(engine: Engine, sql: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql)).scalar_one())


def _controller(journal: Any, store: PgSafeModeStateStore) -> SafeModeController:
    return SafeModeController(
        adapter=_NoAdapter(), journal=journal, compare_fn=_clean_compare, state_store=store
    )


def _load(journal: Any, store: PgSafeModeStateStore, now_utc: datetime) -> SafeModeController:
    return SafeModeController.load(
        adapter=_NoAdapter(),
        journal=journal,
        state_store=store,
        now_utc=now_utc,
        compare_fn=_clean_compare,
    )


def test_enter_writes_a_safe_mode_row_and_a_second_controller_loads_it(pg_db: str) -> None:
    dispose, engine, journal, _system_state, store = _open(pg_db)
    try:
        controller = _controller(journal, store)
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

        assert _count(engine, "SELECT count(*) FROM system_state_events") == 1
        assert (
            _count(
                engine,
                "SELECT count(*) FROM system_state_events WHERE state_key = 'SAFE_MODE'",
            )
            == 1
        )
        types = {
            event.event_type
            for event in journal.list_by_correlation("reconcile_safe_mode")
            + journal.list_by_correlation("system_state:SAFE_MODE")
        }
        assert types == {"SAFE_MODE_ENTER", "SYSTEM_STATE_CHANGED"}
    finally:
        dispose()

    dispose_b, _engine_b, journal_b, _state_b, store_b = _open(pg_db)
    try:
        restored = _load(journal_b, store_b, T2)

        assert restored.in_safe_mode is True
        assert restored.entered_reason == "DB_FAILURE"
        assert restored.entered_at_utc == T0
        assert restored.is_durable is True
        verdict = restored.guard_new_entries(trade_plan=None)
        assert verdict.is_no_trade is True
        assert verdict.reason_code == RejectionReason.RECONCILIATION_REQUIRED.value
    finally:
        dispose_b()


def test_a_reentry_with_a_new_reason_is_a_new_version_and_the_latest_wins(pg_db: str) -> None:
    dispose, engine, journal, _system_state, store = _open(pg_db)
    try:
        controller = _controller(journal, store)
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)
        controller.enter_safe_mode(reason="UNSYNCED_POSITION", now_utc=T1)

        assert _count(engine, "SELECT max(state_version) FROM system_state_events") == 2
        restored = _load(journal, store, T2)

        assert restored.entered_reason == "UNSYNCED_POSITION"
        assert restored.entered_at_utc == T0
    finally:
        dispose()


def test_an_empty_table_loads_as_none_and_gives_the_default_controller(pg_db: str) -> None:
    dispose, _engine, journal, _system_state, store = _open(pg_db)
    try:
        assert store.load() is None

        controller = _load(journal, store, T0)

        assert controller.in_safe_mode is False
        assert controller.state_snapshot() == {
            "in_safe_mode": False,
            "entered_at_utc": None,
            "entered_reason": None,
        }
    finally:
        dispose()


def test_save_and_load_round_trip_the_state_mapping(pg_db: str) -> None:
    dispose, _engine, _journal, system_state, store = _open(pg_db)
    try:
        state = {
            "in_safe_mode": True,
            "entered_at_utc": T0.isoformat(),
            "entered_reason": "DB_FAILURE",
        }

        store.save(state, now_utc=T0)

        assert store.load() == state
        record = system_state.latest(SystemStateKey.SAFE_MODE)
        assert record is not None and record.version == 1
    finally:
        dispose()


def test_a_stored_state_the_controller_cannot_parse_starts_in_safe_mode_unreadable(
    pg_db: str,
) -> None:
    dispose, _engine, _journal, _system_state, store = _open(pg_db)
    try:
        # A mapping the system-state store accepts but the controller format rejects (no keys).
        store.save({"in_safe_mode": True}, now_utc=T0)
        journal = _MemoryJournal()

        controller = _load(journal, store, T2)

        assert controller.in_safe_mode is True
        assert controller.entered_reason == SAFE_MODE_STATE_UNREADABLE
        assert controller.entered_at_utc == T2
        (event,) = journal.events
        assert json.loads(event.payload_json) == {"error_type": "ValueError"}
    finally:
        dispose()


def test_an_unreachable_database_starts_the_controller_in_safe_mode_unreadable() -> None:
    engine = make_sync_engine(UNREACHABLE_URL)
    try:
        db = OperationalDatabase(engine)
        store = PgSafeModeStateStore(PgSystemStateStore(db, PgJournalStore(db)))
        journal = _MemoryJournal()

        controller = _load(journal, store, T2)

        assert controller.in_safe_mode is True
        assert controller.entered_reason == SAFE_MODE_STATE_UNREADABLE
        assert controller.entered_at_utc == T2
        assert controller.guard_new_entries(trade_plan=None).is_no_trade is True
        (event,) = journal.events
        assert json.loads(event.payload_json) == {"error_type": "StoreUnavailable"}
        assert "127.0.0.1" not in event.payload_json
    finally:
        engine.dispose()
