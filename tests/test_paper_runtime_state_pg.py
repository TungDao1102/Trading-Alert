"""PostgreSQL runtime state: journal rows as state, restart restore (Phase 16, plan 16-16, Q-J).

Q-J decision "journal-only" (user, 2026-10-09): every runtime record is a journal event written
through `PgJournalStore.record` with entity type "PaperRuntime"; restore reads bounded queries
over `journal_events` by event type and the correlation prefix `paper:<epoch>:`. No migration,
no new table.

The behaviours are the shared `contract_*` bodies of `tests/test_paper_runtime_state.py`, so the
in-memory and PostgreSQL ports are held to the same rules. Every test runs on a generated
`t17_<hex>_test` database cloned from an alembic-built template (`tests/pg_support.py`); without
`TEST_DATABASE_URL` they skip locally and FAIL under `TRADING_CI_STRICT=1`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from src.db.models import JournalEventRow
from src.paper.runtime_state import (
    ENTITY_TYPE,
    RuntimeRecordConflict,
    RuntimeStatePort,
    runtime_correlation_id,
    runtime_event_id,
)
from src.paper.vocabulary import RuntimeEventType
from src.persistence.engine import make_sync_engine
from src.persistence.journal import PgJournalStore
from src.persistence.paper_runtime_state import PgRuntimeState
from src.persistence.uow import OperationalDatabase

from tests.test_paper_runtime_state import (
    CONTRACTS,
    EPOCH,
    OTHER_EPOCH,
    T0,
    PortFactory,
    bar,
    bar_close,
    marker,
    simulated_session,
)


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


def journal_row_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(JournalEventRow)).scalar_one())


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.__name__)
def test_pg_state_meets_the_same_contract_as_the_in_memory_state(
    contract: Callable[[PortFactory], None], db: OperationalDatabase
) -> None:
    contract(lambda: PgRuntimeState(db))


def test_replaying_a_full_session_inserts_zero_rows_and_raises_nothing(
    db: OperationalDatabase, engine: Engine
) -> None:
    state = PgRuntimeState(db)
    session = simulated_session()
    for record in session:
        state.record(record)
    assert journal_row_count(engine) == len(session)
    for record in session:
        state.record(record)
    assert journal_row_count(engine) == len(session)


def test_a_restart_restores_the_closes_and_the_marker_from_the_database(
    db: OperationalDatabase,
) -> None:
    first_process = PgRuntimeState(db)
    for record in simulated_session():
        first_process.record(record)

    second_process = PgRuntimeState(db)  # a new instance on the same database
    assert second_process.last_close_by_pair(EPOCH) == {
        ("BTCUSDT", "1h"): bar_close(2),
        ("ETHUSDT", "1h"): bar_close(1),
    }
    last = second_process.latest_runtime_marker(EPOCH)
    assert last is not None
    assert last.event_type is RuntimeEventType.RUNTIME_STOP
    assert last.occurred_at_utc == T0 + timedelta(hours=4)
    assert second_process.records(EPOCH) == first_process.records(EPOCH)
    # The restarted process keeps writing without a duplicate or a conflict.
    second_process.record(bar(3))
    assert second_process.last_close_by_pair(EPOCH)[("BTCUSDT", "1h")] == bar_close(3)


def test_every_record_is_a_journal_event_written_through_the_journal_store(
    db: OperationalDatabase,
) -> None:
    state = PgRuntimeState(db)
    record = bar(7)
    state.record(record)
    event = PgJournalStore(db).get(runtime_event_id(record))
    assert event is not None
    assert event.entity_type == ENTITY_TYPE == "PaperRuntime"
    assert event.event_type == "PAPER_BAR_PROCESSED"
    assert event.entity_id == "BTCUSDT:1h"
    assert event.correlation_id == runtime_correlation_id(record)
    assert event.correlation_id.startswith(f"paper:{EPOCH}:")
    assert event.occurred_at_utc == bar_close(7)
    assert event.payload_json == record.payload_json
    assert event.created_at_utc is None  # no wall clock anywhere in the record


def test_a_conflict_is_the_port_error_not_the_journal_error(db: OperationalDatabase) -> None:
    state = PgRuntimeState(db)
    state.record(bar(1))
    with pytest.raises(RuntimeRecordConflict) as excinfo:
        state.record(bar(1, source="REST_BACKFILL"))
    assert "LIVE_WS" not in str(excinfo.value)  # payload contents stay out of the message
    assert state.records(EPOCH)[0].payload["source"] == "LIVE_WS"


def test_epochs_are_isolated_and_a_wildcard_in_an_epoch_id_matches_only_itself(
    db: OperationalDatabase,
) -> None:
    state = PgRuntimeState(db)
    wild, plain, other = "e_1", "eX1", "e%"
    for epoch in (wild, plain, other, OTHER_EPOCH):
        state.record(bar(0, epoch_id=epoch))
        state.record(marker(RuntimeEventType.RUNTIME_START, T0, epoch_id=epoch))
    for epoch in (wild, plain, other, OTHER_EPOCH):
        assert [r.epoch_id for r in state.records(epoch)] == [epoch, epoch]
        assert set(state.last_close_by_pair(epoch)) == {("BTCUSDT", "1h")}
        latest = state.latest_runtime_marker(epoch)
        assert latest is not None
        assert latest.epoch_id == epoch
    assert state.records(EPOCH) == []
    assert state.last_close_by_pair(EPOCH) == {}
    assert state.latest_runtime_marker(EPOCH) is None


def test_restore_reads_only_the_latest_close_per_pair_whatever_the_history(
    db: OperationalDatabase,
) -> None:
    state = PgRuntimeState(db)
    for hour in range(48):
        state.record(bar(hour))
        state.record(bar(hour, symbol="ETHUSDT", interval="4h"))
    assert state.last_close_by_pair(EPOCH) == {
        ("BTCUSDT", "1h"): bar_close(47),
        ("ETHUSDT", "4h"): bar_close(47),
    }
    assert len(state.records(EPOCH, {RuntimeEventType.PAPER_BAR_PROCESSED})) == 96


def test_a_start_and_a_stop_at_the_same_instant_resolve_to_the_start(
    db: OperationalDatabase,
) -> None:
    state = PgRuntimeState(db)
    state.record(marker(RuntimeEventType.RUNTIME_START, T0))
    state.record(marker(RuntimeEventType.RUNTIME_STOP, T0))
    latest = state.latest_runtime_marker(EPOCH)
    assert latest is not None
    assert latest.event_type is RuntimeEventType.RUNTIME_START


def test_the_pg_state_conforms_to_the_port(db: OperationalDatabase) -> None:
    port: RuntimeStatePort = PgRuntimeState(db)
    assert isinstance(port.records(EPOCH), (list, tuple))


def test_other_journal_rows_with_a_paper_prefix_are_not_runtime_records(
    db: OperationalDatabase,
) -> None:
    from src.domain.journal import JournalEvent

    journal = PgJournalStore(db)
    journal.record(
        JournalEvent(
            journal_event_id="paper_foreign_row",
            occurred_at_utc=T0,
            event_type="PAPER_BAR_PROCESSED",
            entity_type="PaperRecord",
            entity_id="BTCUSDT:1h",
            correlation_id=f"paper:{EPOCH}:BTCUSDT:1h:1",
            payload_json="{}",
        )
    )
    state = PgRuntimeState(db)
    assert state.records(EPOCH) == []
    assert state.last_close_by_pair(EPOCH) == {}
