"""PostgreSQL restart integration test on the Phase 17 stores (Phase 16, plan 16-29, SC1).

The behaviours are the shared `contract_*` bodies of `tests/test_paper_runtime_restart.py`, which
also run on the in-memory reference port, so the in-memory and PostgreSQL stores are held to the
same rules. One session: a pin, a stopped process with processed bars up to C, downtime, a start
with REST warm-up, and two closed live bars, all on `PgRuntimeState` (journal rows as the state,
Q-J decision).

Every test runs on a generated `t17_<hex>_test` database cloned from an alembic-built template
(`tests/pg_support.py`); without `TEST_DATABASE_URL` they skip locally and FAIL under
`TRADING_CI_STRICT=1`. No schema change in plan 16-29.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from src.db.models import JournalEventRow
from src.paper.runtime_state import InMemoryRuntimeState, RuntimeStatePort
from src.persistence.engine import make_sync_engine
from src.persistence.paper_runtime_state import PgRuntimeState
from src.persistence.uow import OperationalDatabase

from tests import test_paper_runtime_restart as restart_tests

# The fixtures of the shared module, registered here so the same rig drives the PostgreSQL runs.
live = restart_tests.live
_isolated_sdk_stream_map = restart_tests._isolated_sdk_stream_map


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def pg_state(engine: Engine) -> RuntimeStatePort:
    return PgRuntimeState(OperationalDatabase(engine))


def test_a_full_session_leaves_one_record_per_expected_close_on_postgresql(
    live: restart_tests.Live, pg_state: RuntimeStatePort
) -> None:
    restart_tests.contract_full_session_accounts_for_every_close(live, lambda: pg_state)


def test_replaying_the_whole_session_inserts_zero_rows_and_raises_no_conflict_on_postgresql(
    live: restart_tests.Live, pg_state: RuntimeStatePort, engine: Engine
) -> None:
    def journal_rows() -> int:
        with engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(JournalEventRow)).scalar_one())

    restart_tests.run_session(live, pg_state)
    rows_after_first_run = journal_rows()
    assert rows_after_first_run > 0

    restart_tests.contract_replaying_the_session_inserts_nothing(live, lambda: pg_state)

    assert journal_rows() == rows_after_first_run, "the replay inserted no journal row"


def test_record_ids_are_the_same_at_a_different_wall_clock_on_postgresql(
    live: restart_tests.Live, pg_state: RuntimeStatePort
) -> None:
    restart_tests.contract_ids_do_not_depend_on_the_wall_clock(
        live, lambda: pg_state, InMemoryRuntimeState
    )
