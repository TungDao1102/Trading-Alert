"""Evidence-gated UNKNOWN exits on PostgreSQL (plan 18-08, G4-034, D051 item i, D-08).

Pins, against a real PostgreSQL server (each test on a generated `t17_<hex>_test` clone):

  - an Order leaves UNKNOWN only with an `ExitEvidence`; the UNKNOWN_EXIT_EVIDENCE journal
    event is appended in the SAME transaction as the status change, so both commit or neither;
  - missing evidence or a store without a journal raises `EvidenceRequired` and writes nothing;
  - evidence on a transition that does not start in UNKNOWN is a ValueError (never ignored);
  - a replay of the same exit is an idempotent no-op (no second journal row);
  - the same rule for a Position (G4-034);
  - `update_order_exchange_state` writes `exchange_status` / `exchange_order_id` (also on a
    terminal order, whose `local_status` the migration 0004 trigger still protects), refuses a
    different exchange id, and is idempotent; the client-id and algo-client-id lookups (G4-043);
  - the module map of `src/persistence/__init__.py` names every module of the package.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from src.db.models import JournalEventRow
from src.domain.enums import OrderStatus, PositionStatus
from src.domain.journal import JournalEvent
from src.domain.stream_records import (
    UNKNOWN_EXIT_EVIDENCE,
    EvidenceSource,
    ExitEvidence,
    exit_evidence_event,
)
from src.domain.transitions import IllegalTransition
from src.persistence.engine import make_sync_engine
from src.persistence.entities import PgTradingEntityStore
from src.persistence.errors import EvidenceRequired, JournalConflict, RowConflict
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import (
    T0,
    expect_db_error,
    hexid,
    insert_and_commit,
    make_order,
    make_plan,
    make_position,
    make_signal,
)

NOW = T0 + timedelta(minutes=9, microseconds=654321)
OBSERVED = T0 + timedelta(minutes=9)
ORDER_ID = hexid(0x5001)


# --------------------------------------------------------------------------- #
# Fixtures and helpers.
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
def journal(db: OperationalDatabase) -> PgJournalStore:
    return PgJournalStore(db)


@pytest.fixture
def store(db: OperationalDatabase, journal: PgJournalStore) -> PgTradingEntityStore:
    return PgTradingEntityStore(db, journal=journal)


def seed_order(engine: Engine, n: int = 1, **overrides: object) -> str:
    """Signal n -> plan n -> order n committed; returns the order id."""
    insert_and_commit(engine, make_signal(n), make_plan(n, n), make_order(n, n, **overrides))
    return hexid(0x5000 + n)


def user_data_evidence(**overrides: object) -> ExitEvidence:
    values: dict[str, object] = {
        "source": EvidenceSource.USER_DATA_EVENT,
        "observed_at_utc": OBSERVED,
        "reference": "ORDER_TRADE_UPDATE:E=1726747740000:i=8389765",
        "correlation_id": "uds-session-1",
    }
    values.update(overrides)
    return ExitEvidence(**values)  # type: ignore[arg-type]


def journal_rows(engine: Engine, *, order_id: str | None = None) -> list[JournalEventRow]:
    with Session(engine) as session:
        stmt = select(JournalEventRow).order_by(JournalEventRow.journal_event_id)
        if order_id is not None:
            stmt = stmt.where(JournalEventRow.order_id == order_id)
        return list(session.execute(stmt).scalars())


# --------------------------------------------------------------------------- #
# Order: UNKNOWN exit with evidence (tracer).
# --------------------------------------------------------------------------- #


def test_order_unknown_to_filled_with_user_data_evidence_journals_one_row(
    engine: Engine, store: PgTradingEntityStore, journal: PgJournalStore
) -> None:
    order_id = seed_order(engine, local_status="UNKNOWN")
    ev = user_data_evidence()

    out = store.transition_order(order_id, OrderStatus.FILLED, now_utc=NOW, evidence=ev)

    assert out.local_status is OrderStatus.FILLED
    assert out.updated_at_utc == NOW
    rows = journal_rows(engine, order_id=order_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == UNKNOWN_EXIT_EVIDENCE
    assert row.entity_type == "ORDER"
    assert row.order_id == order_id
    expected = exit_evidence_event(
        entity_type="ORDER",
        entity_id=order_id,
        from_status="UNKNOWN",
        to_status="FILLED",
        evidence=ev,
        now_utc=NOW,
        order_id=order_id,
    )
    assert journal.get(expected.journal_event_id) == expected


def test_replaying_the_same_exit_is_an_idempotent_no_op(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    order_id = seed_order(engine, local_status="UNKNOWN")
    ev = user_data_evidence()
    first = store.transition_order(order_id, OrderStatus.FILLED, now_utc=NOW, evidence=ev)
    again = store.transition_order(order_id, OrderStatus.FILLED, now_utc=NOW, evidence=ev)
    assert again == first
    assert len(journal_rows(engine, order_id=order_id)) == 1


def test_rest_reconcile_evidence_is_recorded_as_its_source(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    order_id = seed_order(engine, local_status="UNKNOWN")
    ev = user_data_evidence(
        source=EvidenceSource.REST_RECONCILE, reference="GET:/fapi/v1/order:orderId=8389765"
    )
    store.transition_order(order_id, OrderStatus.CANCELED, now_utc=NOW, evidence=ev)
    (row,) = journal_rows(engine, order_id=order_id)
    assert '"evidence_source":"REST_RECONCILE"' in row.payload_json
    assert '"to_status":"CANCELED"' in row.payload_json


# --------------------------------------------------------------------------- #
# Order: the gate refuses and writes nothing.
# --------------------------------------------------------------------------- #


def test_unknown_exit_without_evidence_raises_and_writes_nothing(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    order_id = seed_order(engine, local_status="UNKNOWN")
    with pytest.raises(EvidenceRequired):
        store.transition_order(order_id, OrderStatus.FILLED, now_utc=NOW)
    stored = store.get_order(order_id)
    assert stored is not None and stored.local_status is OrderStatus.UNKNOWN
    assert journal_rows(engine) == []


def test_unknown_exit_with_evidence_but_no_journal_raises_and_writes_nothing(
    engine: Engine, db: OperationalDatabase
) -> None:
    order_id = seed_order(engine, local_status="UNKNOWN")
    bare = PgTradingEntityStore(db)
    with pytest.raises(EvidenceRequired):
        bare.transition_order(
            order_id, OrderStatus.FILLED, now_utc=NOW, evidence=user_data_evidence()
        )
    stored = bare.get_order(order_id)
    assert stored is not None and stored.local_status is OrderStatus.UNKNOWN
    assert journal_rows(engine) == []


def test_forced_journal_conflict_rolls_the_status_change_back(
    engine: Engine, store: PgTradingEntityStore, journal: PgJournalStore
) -> None:
    order_id = seed_order(engine, local_status="UNKNOWN")
    ev = user_data_evidence()
    expected = exit_evidence_event(
        entity_type="ORDER",
        entity_id=order_id,
        from_status="UNKNOWN",
        to_status="FILLED",
        evidence=ev,
        now_utc=NOW,
        order_id=order_id,
    )
    # A DIFFERENT event already holds the deterministic id.
    journal.record(
        JournalEvent(
            journal_event_id=expected.journal_event_id,
            occurred_at_utc=NOW,
            event_type="SOMETHING_ELSE",
            entity_type="ORDER",
            entity_id=order_id,
            correlation_id="uds-session-1",
            order_id=order_id,
            payload_json="{}",
        )
    )
    with pytest.raises(JournalConflict):
        store.transition_order(order_id, OrderStatus.FILLED, now_utc=NOW, evidence=ev)
    stored = store.get_order(order_id)
    assert stored is not None and stored.local_status is OrderStatus.UNKNOWN
    assert len(journal_rows(engine, order_id=order_id)) == 1  # only the pre-existing row


def test_journal_conflict_inside_a_caller_unit_of_work_rolls_back_as_a_whole(
    engine: Engine, db: OperationalDatabase, store: PgTradingEntityStore, journal: PgJournalStore
) -> None:
    order_id = seed_order(engine, local_status="UNKNOWN")
    ev = user_data_evidence()
    clash = exit_evidence_event(
        entity_type="ORDER",
        entity_id=order_id,
        from_status="UNKNOWN",
        to_status="FILLED",
        evidence=user_data_evidence(reference="ORDER_TRADE_UPDATE:E=1:i=2"),
        now_utc=NOW,
        order_id=order_id,
    )
    with pytest.raises(JournalConflict), db.transaction() as tx:
        journal.append(tx, clash)
        store.transition_order(order_id, OrderStatus.FILLED, now_utc=NOW, evidence=ev, tx=tx)
    stored = store.get_order(order_id)
    assert stored is not None and stored.local_status is OrderStatus.UNKNOWN
    assert journal_rows(engine) == []


def test_evidence_on_a_transition_not_starting_in_unknown_is_a_value_error(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    order_id = seed_order(engine, local_status="NEW")
    with pytest.raises(ValueError):
        store.transition_order(
            order_id, OrderStatus.FILLED, now_utc=NOW, evidence=user_data_evidence()
        )
    stored = store.get_order(order_id)
    assert stored is not None and stored.local_status is OrderStatus.NEW
    assert journal_rows(engine) == []


def test_transitions_not_starting_in_unknown_behave_as_before(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    order_id = seed_order(engine, local_status="NEW")
    out = store.transition_order(order_id, OrderStatus.UNKNOWN, now_utc=NOW)
    assert out.local_status is OrderStatus.UNKNOWN
    assert journal_rows(engine) == []


# --------------------------------------------------------------------------- #
# Position: the same evidence gate.
# --------------------------------------------------------------------------- #

POSITION_ID = hexid(0x4001)


def test_position_unknown_to_closed_with_evidence_journals_one_position_row(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    insert_and_commit(engine, make_position(1, status="UNKNOWN"))
    ev = user_data_evidence(reference="ACCOUNT_UPDATE:E=1726747740000:P=BTCUSDT")
    out = store.transition_position(POSITION_ID, PositionStatus.CLOSED, now_utc=NOW, evidence=ev)
    assert out.status is PositionStatus.CLOSED
    assert out.closed_at_utc == NOW
    (row,) = journal_rows(engine)
    assert row.event_type == UNKNOWN_EXIT_EVIDENCE
    assert row.entity_type == "POSITION"
    assert row.entity_id == POSITION_ID
    assert row.position_id == POSITION_ID
    assert row.order_id is None
    again = store.transition_position(POSITION_ID, PositionStatus.CLOSED, now_utc=NOW, evidence=ev)
    assert again == out
    assert len(journal_rows(engine)) == 1


def test_position_unknown_exit_without_evidence_or_journal_writes_nothing(
    engine: Engine, db: OperationalDatabase, store: PgTradingEntityStore
) -> None:
    insert_and_commit(engine, make_position(1, status="UNKNOWN"))
    with pytest.raises(EvidenceRequired):
        store.transition_position(POSITION_ID, PositionStatus.OPEN, now_utc=NOW)
    with pytest.raises(EvidenceRequired):
        PgTradingEntityStore(db).transition_position(
            POSITION_ID, PositionStatus.OPEN, now_utc=NOW, evidence=user_data_evidence()
        )
    stored = store.get_position(POSITION_ID)
    assert stored is not None and stored.status is PositionStatus.UNKNOWN
    assert journal_rows(engine) == []


def test_position_evidence_on_a_move_not_starting_in_unknown_is_a_value_error(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    insert_and_commit(engine, make_position(1, status="OPEN"))
    with pytest.raises(ValueError):
        store.transition_position(
            POSITION_ID, PositionStatus.CLOSED, now_utc=NOW, evidence=user_data_evidence()
        )
    stored = store.get_position(POSITION_ID)
    assert stored is not None and stored.status is PositionStatus.OPEN
    assert journal_rows(engine) == []


# --------------------------------------------------------------------------- #
# Order exchange state (G4-043): the stream's first writer of exchange fields.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("terminal", ["FILLED", "CANCELED", "EXPIRED", "REJECTED"])
def test_exchange_state_is_writable_on_a_terminal_order_and_local_status_is_untouched(
    engine: Engine, store: PgTradingEntityStore, terminal: str
) -> None:
    order_id = seed_order(engine, local_status=terminal, exchange_status="NEW")
    out = store.update_order_exchange_state(
        order_id, exchange_status=terminal, exchange_order_id="8389765", now_utc=NOW
    )
    assert out.local_status is OrderStatus(terminal)
    assert out.exchange_status == terminal
    assert out.exchange_order_id == "8389765"
    assert out.updated_at_utc == NOW
    assert store.get_order(order_id) == out
    assert journal_rows(engine) == []


@pytest.mark.parametrize("terminal", ["FILLED", "CANCELED"])
def test_local_status_out_of_a_terminal_order_is_still_refused(
    engine: Engine, store: PgTradingEntityStore, terminal: str
) -> None:
    order_id = seed_order(engine, local_status=terminal)
    store.update_order_exchange_state(order_id, exchange_status="EXPIRED", now_utc=NOW)
    with pytest.raises(IllegalTransition):
        store.transition_order(order_id, OrderStatus.NEW, now_utc=NOW)
    # A writer that bypasses the store meets the terminal trigger of migration 0004.
    with expect_db_error("P0001") as info, Session(engine) as session:
        session.execute(
            text("UPDATE orders SET local_status = 'NEW' WHERE order_id = :k"), {"k": order_id}
        )
        session.commit()
    assert "terminal" in info.message
    stored = store.get_order(order_id)
    assert stored is not None and stored.local_status is OrderStatus(terminal)


def test_exchange_order_id_is_set_once_and_none_keeps_the_stored_one(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    order_id = seed_order(engine)
    store.update_order_exchange_state(
        order_id, exchange_status="NEW", exchange_order_id="111", now_utc=NOW
    )
    later = NOW + timedelta(seconds=3)
    out = store.update_order_exchange_state(
        order_id, exchange_status="PARTIALLY_FILLED", exchange_order_id=None, now_utc=later
    )
    assert out.exchange_order_id == "111"
    assert out.exchange_status == "PARTIALLY_FILLED"
    assert out.updated_at_utc == later


def test_a_different_exchange_order_id_is_a_row_conflict(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    order_id = seed_order(engine, exchange_order_id="111")
    before = store.get_order(order_id)
    with pytest.raises(RowConflict):
        store.update_order_exchange_state(
            order_id, exchange_status="FILLED", exchange_order_id="222", now_utc=NOW
        )
    assert store.get_order(order_id) == before


def test_unchanged_exchange_state_is_an_idempotent_no_op(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    order_id = seed_order(engine, exchange_status="NEW", exchange_order_id="111")
    before = store.get_order(order_id)
    out = store.update_order_exchange_state(
        order_id, exchange_status="NEW", exchange_order_id="111", now_utc=NOW
    )
    assert out == before
    assert out.updated_at_utc == T0  # not rewritten


@pytest.mark.parametrize("status", ["", "S" * 33])
def test_exchange_status_must_be_non_empty_and_fit_its_column(
    engine: Engine, store: PgTradingEntityStore, status: str
) -> None:
    order_id = seed_order(engine)
    with pytest.raises(ValueError):
        store.update_order_exchange_state(order_id, exchange_status=status, now_utc=NOW)


def test_exchange_state_of_a_missing_order_is_a_row_conflict(store: PgTradingEntityStore) -> None:
    with pytest.raises(RowConflict):
        store.update_order_exchange_state(hexid(0x5999), exchange_status="NEW", now_utc=NOW)


def test_exchange_state_joins_the_callers_unit_of_work(
    engine: Engine, db: OperationalDatabase, store: PgTradingEntityStore
) -> None:
    order_id = seed_order(engine)
    with pytest.raises(RuntimeError), db.transaction() as tx:
        store.update_order_exchange_state(
            order_id, exchange_status="FILLED", exchange_order_id="111", now_utc=NOW, tx=tx
        )
        raise RuntimeError("caller aborts")
    stored = store.get_order(order_id)
    assert stored is not None
    assert (stored.exchange_status, stored.exchange_order_id) == ("NEW", None)


# --------------------------------------------------------------------------- #
# Lookups by client order id and algo client id (the stream router's keys).
# --------------------------------------------------------------------------- #


def test_lookup_by_client_order_id(engine: Engine, store: PgTradingEntityStore) -> None:
    order_id = seed_order(engine)
    client_id = make_order(1).client_order_id
    assert client_id is not None
    found = store.get_order_by_client_order_id(client_id)
    assert found is not None and found.order_id == order_id
    assert store.get_order_by_client_order_id("x-unknown") is None


def test_lookup_by_algo_client_id(engine: Engine, store: PgTradingEntityStore) -> None:
    order_id = seed_order(
        engine, client_order_id=None, algo_client_id="algo-0001SL", order_role="STOP"
    )
    found = store.get_order_by_algo_client_id("algo-0001SL")
    assert found is not None and found.order_id == order_id
    assert store.get_order_by_algo_client_id("algo-unknown") is None
    assert store.get_order_by_client_order_id("algo-0001SL") is None


def test_lookups_join_the_callers_unit_of_work(
    engine: Engine, db: OperationalDatabase, store: PgTradingEntityStore
) -> None:
    seed_order(engine, n=1)
    with db.transaction() as tx:
        tx.add_all([make_signal(2), make_plan(2, 2)])
        tx.flush()
        tx.add(make_order(2, 2, algo_client_id="algo-0002TP"))
        tx.flush()
        # Visible inside the caller's transaction before it commits.
        inside = store.get_order_by_algo_client_id("algo-0002TP", tx=tx)
        by_client = store.get_order_by_client_order_id(f"x-{2:032x}EN", tx=tx)
        assert inside is not None and inside.order_id == hexid(0x5002)
        assert by_client == inside


@pytest.mark.parametrize("bad", ["", None])
def test_lookups_refuse_an_empty_key(store: PgTradingEntityStore, bad: object) -> None:
    with pytest.raises(ValueError):
        store.get_order_by_client_order_id(bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        store.get_order_by_algo_client_id(bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The persistence package's module map names every module (Phase 17 review info item).
# --------------------------------------------------------------------------- #


def test_persistence_module_map_lists_every_module() -> None:
    import src.persistence as package

    package_dir = Path(package.__file__).resolve().parent
    on_disk = {p.stem for p in package_dir.glob("*.py") if p.stem != "__init__"}
    doc = package.__doc__ or ""
    mapped = set(re.findall(r"^\s+- `(\w+)`", doc, flags=re.MULTILINE))
    assert mapped == on_disk
