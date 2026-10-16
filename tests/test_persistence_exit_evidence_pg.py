"""Evidence-gated UNKNOWN exits on PostgreSQL (plan 18-08, G4-034, D051 item i, D-08).

Pins, against a real PostgreSQL server (each test on a generated `t17_<hex>_test` clone):

  - an Order leaves UNKNOWN only with an `ExitEvidence`; the UNKNOWN_EXIT_EVIDENCE journal
    event is appended in the SAME transaction as the status change, so both commit or neither;
  - missing evidence or a store without a journal raises `EvidenceRequired` and writes nothing;
  - evidence on a transition that does not start in UNKNOWN is a ValueError (never ignored);
  - a replay of the same exit is an idempotent no-op (no second journal row).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from src.db.models import JournalEventRow
from src.domain.enums import OrderStatus
from src.domain.journal import JournalEvent
from src.domain.stream_records import (
    UNKNOWN_EXIT_EVIDENCE,
    EvidenceSource,
    ExitEvidence,
    exit_evidence_event,
)
from src.persistence.engine import make_sync_engine
from src.persistence.entities import PgTradingEntityStore
from src.persistence.errors import EvidenceRequired, JournalConflict
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import (
    T0,
    hexid,
    insert_and_commit,
    make_order,
    make_plan,
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
