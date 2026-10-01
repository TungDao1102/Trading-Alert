"""PgSystemStateStore: append-only system state written through the journal (17-13, D-22, D-03).

Pins, against a real PostgreSQL server (each test on a generated `t17_<hex>_test` clone built by
`alembic upgrade head`):

  - `append` creates version 1, then 2, ... per key, each with ONE journal event written in the
    same transaction; `latest` returns the highest version with its state and recorded time;
  - a failing journal append leaves no state row (and no journal row): the audit trail and the
    current state cannot diverge;
  - two concurrent appends for one key: one wins, the other is `RowConflict` (the unique
    `(state_key, state_version)` index is the arbiter) and versions stay contiguous;
  - `latest_kill_gate_state` returns a `KillGateState` or None and fails closed on a stored value
    outside the enum; malformed input never reaches the database;
  - the append-only trigger refuses an UPDATE or DELETE that bypasses the store.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from src.domain.enums import KillGateState, SystemStateKey
from src.domain.journal import JournalEvent
from src.persistence.engine import make_sync_engine
from src.persistence.errors import JournalConflict, RowConflict
from src.persistence.journal import PgJournalStore
from src.persistence.system_state import PgSystemStateStore, SystemStateRecord
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import T0, expect_db_error

SAFE_ON = {
    "in_safe_mode": True,
    "entered_at_utc": "2026-09-19T12:00:00+00:00",
    "entered_reason": "DB_FAILURE",
}
SAFE_OFF = {"in_safe_mode": False, "entered_at_utc": None, "entered_reason": None}
BARRIER_TIMEOUT_SECONDS = 30


@contextmanager
def _stores_on(
    url: str, *, journal_wrapper: Any = None
) -> Iterator[tuple[Engine, PgSystemStateStore]]:
    engine = make_sync_engine(url)
    try:
        db = OperationalDatabase(engine)
        journal: Any = PgJournalStore(db)
        if journal_wrapper is not None:
            journal = journal_wrapper(journal)
        yield engine, PgSystemStateStore(db, journal)
    finally:
        engine.dispose()


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
def journal(db: OperationalDatabase) -> PgJournalStore:
    return PgJournalStore(db)


@pytest.fixture
def store(db: OperationalDatabase, journal: PgJournalStore) -> PgSystemStateStore:
    return PgSystemStateStore(db, journal)


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


# --------------------------------------------------------------------------- #
# append / latest
# --------------------------------------------------------------------------- #


def test_latest_of_a_key_never_written_is_none(store: PgSystemStateStore) -> None:
    assert store.latest(SystemStateKey.SAFE_MODE) is None
    assert store.latest_kill_gate_state() is None


def test_append_creates_contiguous_versions_and_latest_returns_the_highest(
    store: PgSystemStateStore, engine: Engine
) -> None:
    first = store.append(SystemStateKey.SAFE_MODE, SAFE_ON, now_utc=T0)
    second = store.append(SystemStateKey.SAFE_MODE, SAFE_OFF, now_utc=T0 + timedelta(minutes=5))

    assert (first.version, second.version) == (1, 2)
    latest = store.latest(SystemStateKey.SAFE_MODE)
    assert latest == second
    assert isinstance(latest, SystemStateRecord)
    assert dict(latest.state) == SAFE_OFF
    assert latest.recorded_at_utc == T0 + timedelta(minutes=5)
    assert latest.key is SystemStateKey.SAFE_MODE
    assert _count(engine, "system_state_events") == 2
    assert _count(engine, "journal_events") == 2


def test_each_key_has_its_own_version_counter(store: PgSystemStateStore) -> None:
    store.append(SystemStateKey.SAFE_MODE, SAFE_ON, now_utc=T0)
    enable = {"disabled": False, "enabled_at_utc": "2026-09-19T12:00:00+00:00", "operator_id": "op"}
    record = store.append(SystemStateKey.LIVE_ENABLEMENT, enable, now_utc=T0)

    assert record.version == 1
    assert dict(record.state) == enable
    latest_safe = store.latest(SystemStateKey.SAFE_MODE)
    assert latest_safe is not None
    assert latest_safe.version == 1


def test_append_writes_one_journal_event_linked_from_the_state_row(
    store: PgSystemStateStore, journal: PgJournalStore, engine: Engine
) -> None:
    record = store.append(SystemStateKey.SAFE_MODE, SAFE_ON, now_utc=T0)

    event = journal.get(record.journal_event_id)
    assert event is not None
    assert event.event_type == "SYSTEM_STATE_CHANGED"
    assert event.entity_type == "SystemState"
    assert event.entity_id == "SAFE_MODE"
    assert event.correlation_id == "system_state:SAFE_MODE"
    assert event.occurred_at_utc == T0
    payload = json.loads(event.payload_json)
    assert payload["state_key"] == "SAFE_MODE"
    assert payload["state_version"] == 1
    assert payload["state"] == SAFE_ON
    assert journal.list_by_correlation("system_state:SAFE_MODE") == [event]
    with engine.connect() as conn:
        linked = conn.execute(text("SELECT journal_event_id FROM system_state_events")).scalar_one()
    assert linked == record.journal_event_id


def test_the_stored_state_is_canonical_json_without_floats(
    store: PgSystemStateStore, engine: Engine
) -> None:
    store.append(SystemStateKey.SAFE_MODE, SAFE_ON, now_utc=T0)
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT state_json FROM system_state_events")).scalar_one()
    assert raw == json.dumps(SAFE_ON, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# Same-transaction guarantee
# --------------------------------------------------------------------------- #


class _FailingJournal:
    """A journal whose append raises before writing anything."""

    def append(self, tx: Session, event: JournalEvent) -> None:
        raise JournalConflict("injected journal failure")


class _WritesThenFailsJournal:
    """A journal that writes the event and then raises (a failure after the journal insert)."""

    def __init__(self, inner: PgJournalStore) -> None:
        self._inner = inner

    def append(self, tx: Session, event: JournalEvent) -> None:
        self._inner.append(tx, event)
        raise JournalConflict("injected failure after the journal insert")


def test_a_journal_failure_leaves_no_state_row(db: OperationalDatabase, engine: Engine) -> None:
    store = PgSystemStateStore(db, _FailingJournal())  # type: ignore[arg-type]

    with pytest.raises(JournalConflict):
        store.append(SystemStateKey.SAFE_MODE, SAFE_ON, now_utc=T0)

    assert _count(engine, "system_state_events") == 0
    assert store.latest(SystemStateKey.SAFE_MODE) is None


def test_a_failure_after_the_journal_insert_rolls_back_both_rows(
    db: OperationalDatabase, journal: PgJournalStore, engine: Engine
) -> None:
    store = PgSystemStateStore(db, _WritesThenFailsJournal(journal))  # type: ignore[arg-type]

    with pytest.raises(JournalConflict):
        store.append(SystemStateKey.SAFE_MODE, SAFE_ON, now_utc=T0)

    assert _count(engine, "system_state_events") == 0
    assert _count(engine, "journal_events") == 0


def test_append_joins_the_callers_unit_of_work(
    db: OperationalDatabase, store: PgSystemStateStore, engine: Engine
) -> None:
    class Abort(Exception):
        pass

    with pytest.raises(Abort), db.transaction() as tx:
        store.append(SystemStateKey.SAFE_MODE, SAFE_ON, now_utc=T0, tx=tx)
        # Visible inside the unit of work, gone after the rollback.
        assert store.latest(SystemStateKey.SAFE_MODE, tx=tx) is not None
        raise Abort

    assert _count(engine, "system_state_events") == 0
    assert _count(engine, "journal_events") == 0


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #


class _BarrierJournal:
    """Waits at a barrier inside append, i.e. after the next version was already computed."""

    def __init__(self, inner: PgJournalStore, barrier: threading.Barrier) -> None:
        self._inner = inner
        self._barrier = barrier

    def append(self, tx: Session, event: JournalEvent) -> None:
        self._barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
        self._inner.append(tx, event)


@pytest.mark.parametrize("attempt", range(3))
def test_two_concurrent_appends_for_one_key_yield_one_winner_and_a_row_conflict(
    pg_db: str, attempt: int
) -> None:
    barrier = threading.Barrier(2)

    def wrap(inner: PgJournalStore) -> _BarrierJournal:
        return _BarrierJournal(inner, barrier)

    with (
        _stores_on(pg_db, journal_wrapper=wrap) as (engine, store_a),
        _stores_on(pg_db, journal_wrapper=wrap) as (_engine_b, store_b),
    ):

        def append(store: PgSystemStateStore, reason: str) -> str:
            state = {"in_safe_mode": True, "entered_at_utc": None, "entered_reason": reason}
            try:
                store.append(SystemStateKey.SAFE_MODE, state, now_utc=T0)
            except RowConflict:
                return "conflict"
            return "ok"

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(append, store_a, "A"), pool.submit(append, store_b, "B")]
            results = sorted(f.result(timeout=60) for f in futures)

        assert results == ["conflict", "ok"]
        with engine.connect() as conn:
            versions = (
                conn.execute(text("SELECT state_version FROM system_state_events ORDER BY 1"))
                .scalars()
                .all()
            )
        assert versions == [1]
        # The loser's journal row rolled back with it (no audit event for a state that never was).
        assert _count(engine, "journal_events") == 1

        # The caller re-reads and retries: the next version is contiguous.
        # (A plain store: the barriered journal of the two racers would wait for a peer.)
        plain_db = OperationalDatabase(engine)
        retried = PgSystemStateStore(plain_db, PgJournalStore(plain_db)).append(
            SystemStateKey.SAFE_MODE, SAFE_OFF, now_utc=T0
        )
        assert retried.version == 2


# --------------------------------------------------------------------------- #
# Kill-gate typed reader
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("state", list(KillGateState))
def test_latest_kill_gate_state_returns_the_enum(
    store: PgSystemStateStore, state: KillGateState
) -> None:
    store.append(SystemStateKey.KILL_GATE, {"kill_gate_state": state.value}, now_utc=T0)
    assert store.latest_kill_gate_state() is state


def test_latest_kill_gate_state_follows_the_highest_version(store: PgSystemStateStore) -> None:
    store.append(
        SystemStateKey.KILL_GATE,
        {"kill_gate_state": KillGateState.WITHIN_BUDGET.value},
        now_utc=T0,
    )
    store.append(
        SystemStateKey.KILL_GATE,
        {"kill_gate_state": KillGateState.INSUFFICIENT_EDGE.value},
        now_utc=T0 + timedelta(seconds=1),
    )
    assert store.latest_kill_gate_state() is KillGateState.INSUFFICIENT_EDGE


@pytest.mark.parametrize(
    "state",
    [
        {"kill_gate_state": "NOT_A_STATE"},
        {"kill_gate_state": None},
        {"something_else": "WITHIN_BUDGET"},
        {},
    ],
)
def test_latest_kill_gate_state_fails_closed_on_a_stored_value_outside_the_enum(
    store: PgSystemStateStore, state: Mapping[str, str | bool | None]
) -> None:
    store.append(SystemStateKey.KILL_GATE, state, now_utc=T0)
    with pytest.raises(ValueError):
        store.latest_kill_gate_state()


# --------------------------------------------------------------------------- #
# Input validation and append-only enforcement
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "state",
    [
        {"x": 1.5},
        {"x": 1},
        {"x": {"nested": True}},
        {"x": ["a"]},
        {1: "a"},
    ],
)
def test_non_scalar_or_float_state_values_are_refused_before_the_database(
    store: PgSystemStateStore, engine: Engine, state: Any
) -> None:
    with pytest.raises(ValueError):
        store.append(SystemStateKey.SAFE_MODE, state, now_utc=T0)
    assert _count(engine, "journal_events") == 0


def test_a_plain_string_key_or_a_naive_time_is_refused(
    store: PgSystemStateStore, engine: Engine
) -> None:
    with pytest.raises(ValueError):
        store.append("SAFE_MODE", SAFE_ON, now_utc=T0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        store.append(SystemStateKey.SAFE_MODE, SAFE_ON, now_utc=T0.replace(tzinfo=None))
    assert _count(engine, "journal_events") == 0


def test_the_store_has_no_update_or_delete_method() -> None:
    names = {name for name in dir(PgSystemStateStore) if not name.startswith("_")}
    assert not {n for n in names if n.startswith(("update", "delete", "remove"))}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE system_state_events SET state_json = '{}'",
        "DELETE FROM system_state_events",
    ],
)
def test_the_append_only_trigger_refuses_a_bypassing_writer(
    store: PgSystemStateStore, engine: Engine, statement: str
) -> None:
    record = store.append(SystemStateKey.SAFE_MODE, SAFE_ON, now_utc=T0)

    with expect_db_error(), engine.begin() as conn:
        conn.execute(text(statement))

    assert store.latest(SystemStateKey.SAFE_MODE) == record
