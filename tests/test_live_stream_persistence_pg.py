"""Stream events to persisted orders and positions in PostgreSQL (plan 24-19, D-10, G4-043/034).

Pins, on a generated `t17_<hex>_test` clone built by `alembic upgrade head`:

  * ORDER_TRADE_UPDATE NEW (E1) then FILLED (E2) for a system entry id: one Order row, exchange
    status FILLED, event time E2; a redelivered NEW with E1 afterwards leaves FILLED (stale, a
    recorded no-op); the writes run in arrival order on the writer thread;
  * ACCOUNT_UPDATE positions (SYNTHETIC frames through a real parser and router): inserted with
    the snapshot, updated by a later event, an older one ignored, `status` untouched;
  * a move out of UNKNOWN made by a stream event journals evidence_source USER_DATA_EVENT and the
    event time (G4-034), for an Order and for a Position;
  * a client id that is not ours is not persisted; failures are journaled by class name;
  * the sink call returns before the database write completes (a blocked fake store).

Evidence label: executed tests, SYNTHETIC frames, no Binance, no Telegram. Times are TEST_ONLY.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from src.adapters.binance_userdata_events import AccountUpdateEvent, parse_stream_message
from src.db.models import JournalEventRow
from src.domain.enums import ExecutionIntentStatus, OrderRole, OrderStatus, PositionStatus
from src.domain.journal import JournalEvent
from src.domain.stream_records import UNKNOWN_EXIT_EVIDENCE
from src.execution.intent_store import IntentRecord
from src.execution.order_ids import derive_client_order_id
from src.live.stream_persistence import (
    FAIL_MISSING_FIELD,
    FAIL_NO_INTENT,
    STREAM_PERSISTENCE_FAILURE,
    StreamPersistence,
    make_account_position_writer,
    make_exchange_state_writer,
    order_id_for,
    position_id_for,
)
from src.ops.store_executor import WRITER_THREAD_PREFIX, StoreExecutor
from src.persistence.engine import make_sync_engine
from src.persistence.entities import PgTradingEntityStore
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import (
    T0,
    hexid,
    insert_and_commit,
    make_plan,
    make_position,
    make_signal,
)
from tests.support.stream_sinks import (
    FakeOrderLookup,
    RecordingJournal,
    RecordingSinks,
    make_router,
)
from tests.support.userdata_frames import account_update_frame, position_row

PLAN_HASH = "d" * 64
CLIENT_ID = derive_client_order_id(plan_hash=PLAN_HASH, role=OrderRole.ENTRY.value)
EX_ID = "8000000001"
E1 = T0 + timedelta(minutes=1)
E2 = T0 + timedelta(minutes=2)
E3 = T0 + timedelta(minutes=3)
E4 = T0 + timedelta(minutes=4)
NOW = T0 + timedelta(minutes=9, microseconds=123456)
SESSION = "test-only-stream-session-0001"
PLAN_ID = hexid(0x1000 + 1)


@dataclass(frozen=True)
class FakeUpdate:
    """Satisfies `ExchangeStateLike` (the router's update plus the event time `E`)."""

    local_order_id: str
    exchange_status: str
    exchange_order_id: str
    now_utc: datetime
    exchange_event_time_utc: datetime


def update(status: str, at: datetime, *, client_id: str = CLIENT_ID) -> FakeUpdate:
    return FakeUpdate(client_id, status, EX_ID, NOW, at)


def make_intent(**overrides: Any) -> IntentRecord:
    values: dict[str, Any] = {
        "approval_id": hexid(0x2001),
        "role": OrderRole.ENTRY.value,
        "trade_plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "client_order_id": CLIENT_ID,
        "algo_client_id": None,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "intended_quantity": Decimal("0.01"),
        "intended_price": Decimal("60000"),
        "intent_status": ExecutionIntentStatus.ACKED,
        "exchange_order_id": None,
        "exchange_status": None,
        "outcome": None,
        "intended_at_utc": T0,
        "sent_at_utc": T0 + timedelta(seconds=1),
        "resolved_at_utc": None,
        "updated_at_utc": T0,
    }
    values.update(overrides)
    return IntentRecord(**values)


class Intents:
    def __init__(self, *records: IntentRecord) -> None:
        self.records = {r.client_order_id: r for r in records if r.client_order_id}
        self.threads: list[str] = []

    def intent_for_client_id(self, client_order_id: str) -> IntentRecord | None:
        self.threads.append(threading.current_thread().name)
        return self.records.get(client_order_id)


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


@pytest.fixture
def executor() -> Iterator[StoreExecutor]:
    ex = StoreExecutor()
    try:
        yield ex
    finally:
        ex.close()


def build(
    *,
    store: PgTradingEntityStore,
    db: OperationalDatabase,
    journal: PgJournalStore,
    executor: StoreExecutor,
    intents: Intents,
) -> StreamPersistence:
    return StreamPersistence(
        executor=executor,
        store=store,
        database=db,
        intents=intents,
        journal=journal.record,
        clock=lambda: NOW,
        correlation_id=SESSION,
    )


def seed_plan(engine: Engine) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1))


def order_row(engine: Engine) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT exchange_status, local_status, exchange_event_time_utc, "
                    "exchange_order_id, quantity FROM orders WHERE client_order_id = :c"
                ),
                {"c": CLIENT_ID},
            )
            .mappings()
            .first()
        )
    return None if row is None else dict(row)


def position_state(engine: Engine, symbol: str = "BTCUSDT") -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT quantity, entry_price, break_even_price, unrealized_pnl, status, "
                    "snapshot_event_time_utc FROM positions WHERE position_id = :p"
                ),
                {"p": position_id_for(symbol, "BOTH")},
            )
            .mappings()
            .first()
        )
    return None if row is None else dict(row)


def journal_rows(engine: Engine, event_type: str) -> list[JournalEventRow]:
    with Session(engine) as session:
        return list(
            session.execute(
                select(JournalEventRow).where(JournalEventRow.event_type == event_type)
            ).scalars()
        )


def account_event(
    *, event_ms: int, **row_overrides: Any
) -> AccountUpdateEvent:  # a SYNTHETIC frame through the real parser
    frame = account_update_frame(event_overrides={"E": event_ms}, P=[position_row(**row_overrides)])
    outcome = parse_stream_message(frame, observed_at_utc=NOW)
    assert isinstance(outcome, AccountUpdateEvent)
    return outcome


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


# --------------------------------------------------------------------------- #
# Orders.
# --------------------------------------------------------------------------- #


async def test_order_events_persist_in_order_and_a_late_event_changes_nothing(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    seed_plan(engine)
    intents = Intents(make_intent())
    persistence = build(store=store, db=db, journal=journal, executor=executor, intents=intents)
    sink = make_exchange_state_writer(persistence)

    sink(update("NEW", E1))
    sink(update("FILLED", E2))
    await persistence.drain()

    row = order_row(engine)
    assert row is not None
    assert (row["exchange_status"], row["exchange_event_time_utc"]) == ("FILLED", E2)
    assert row["exchange_order_id"] == EX_ID
    assert row["quantity"] == Decimal("0.01")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar_one() == 1
    assert intents.threads and all(n.startswith(WRITER_THREAD_PREFIX) for n in intents.threads)

    sink(update("NEW", E1))  # redelivered, older
    await persistence.drain()

    row = order_row(engine)
    assert row is not None
    assert (row["exchange_status"], row["exchange_event_time_utc"]) == ("FILLED", E2)
    assert persistence.stats.orders_stale == 1
    assert persistence.stats.orders_inserted == 1
    assert persistence.stats.failures == 0


async def test_a_stream_event_moves_an_unknown_order_out_with_its_evidence_source(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    seed_plan(engine)
    intents = Intents(make_intent(intent_status=ExecutionIntentStatus.UNKNOWN))
    persistence = build(store=store, db=db, journal=journal, executor=executor, intents=intents)

    persistence.exchange_state_sink(update("FILLED", E2))
    await persistence.drain()

    row = order_row(engine)
    assert row is not None and row["local_status"] == OrderStatus.FILLED.value
    events = journal_rows(engine, UNKNOWN_EXIT_EVIDENCE)
    assert len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert payload["evidence_source"] == "USER_DATA_EVENT"
    assert payload["observed_at_utc"] == E2.isoformat()
    assert (payload["from_status"], payload["to_status"]) == ("UNKNOWN", "FILLED")
    assert events[0].order_id == order_id_for(CLIENT_ID)
    assert persistence.stats.unknown_exits == 1


async def test_a_stale_event_does_not_move_an_unknown_order_and_journals_nothing(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    seed_plan(engine)
    persistence = build(
        store=store,
        db=db,
        journal=journal,
        executor=executor,
        intents=Intents(make_intent(intent_status=ExecutionIntentStatus.UNKNOWN)),
    )
    # an unknown status moves nothing, but records the exchange state at E2 ...
    persistence.exchange_state_sink(update("SOMETHING_NEW", E2))
    await persistence.drain()
    row = order_row(engine)
    assert row is not None and row["local_status"] == OrderStatus.UNKNOWN.value
    # ... and an older event is then a no-op with no evidence
    persistence.exchange_state_sink(update("FILLED", E1))
    await persistence.drain()
    row = order_row(engine)
    assert row is not None
    assert row["local_status"] == OrderStatus.UNKNOWN.value
    assert row["exchange_status"] == "SOMETHING_NEW"
    assert journal_rows(engine, UNKNOWN_EXIT_EVIDENCE) == []


async def test_a_client_id_that_is_not_ours_is_not_persisted(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    seed_plan(engine)
    persistence = build(
        store=store, db=db, journal=journal, executor=executor, intents=Intents(make_intent())
    )
    persistence.exchange_state_sink(update("NEW", E1, client_id="web_manual_77"))
    await persistence.drain()
    assert persistence.stats.foreign == 1
    assert persistence.pending == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar_one() == 0


async def test_no_intent_is_journaled_and_nothing_is_invented(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    seed_plan(engine)
    persistence = build(store=store, db=db, journal=journal, executor=executor, intents=Intents())
    persistence.exchange_state_sink(update("NEW", E1))
    await persistence.drain()
    assert order_row(engine) is None
    events = journal_rows(engine, STREAM_PERSISTENCE_FAILURE)
    assert [json.loads(e.payload_json)["reason"] for e in events] == [FAIL_NO_INTENT]


async def test_a_store_failure_is_journaled_by_class_name_only(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    # no trade plan row: the order insert hits the foreign key
    persistence = build(
        store=store, db=db, journal=journal, executor=executor, intents=Intents(make_intent())
    )
    persistence.exchange_state_sink(update("NEW", E1))
    await persistence.drain()
    assert order_row(engine) is None
    events = journal_rows(engine, STREAM_PERSISTENCE_FAILURE)
    assert len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert set(payload) == {"entity_type", "event_time_utc", "reason"}
    assert payload["reason"].isidentifier()
    assert persistence.stats.failures == 1


# --------------------------------------------------------------------------- #
# Positions.
# --------------------------------------------------------------------------- #


async def test_account_updates_insert_then_update_a_position_and_ignore_an_older_one(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    persistence = build(store=store, db=db, journal=journal, executor=executor, intents=Intents())
    sinks = RecordingSinks()
    router = make_router(
        lookup=FakeOrderLookup(),
        journal=RecordingJournal(),
        sinks=sinks,
        clock=lambda: NOW,
        overrides={"account_sink": make_account_position_writer(persistence)},
    )

    class Item:
        def __init__(self, outcome: AccountUpdateEvent) -> None:
            self.outcome = outcome
            self.received_at_utc = NOW
            self.after_gap = False

    router.route(Item(account_event(event_ms=ms(E3), pa="0.010", up="1.5")))
    await persistence.drain()
    state = position_state(engine)
    assert state is not None
    assert state["quantity"] == Decimal("0.010")
    assert state["status"] == PositionStatus.OPEN.value
    assert state["snapshot_event_time_utc"] == E3
    assert state["break_even_price"] == Decimal("60024.00")

    router.route(Item(account_event(event_ms=ms(E4), pa="0.020", up="2.5")))
    await persistence.drain()
    state = position_state(engine)
    assert state is not None
    assert (state["quantity"], state["unrealized_pnl"]) == (Decimal("0.020"), Decimal("2.5"))
    assert state["snapshot_event_time_utc"] == E4

    router.route(Item(account_event(event_ms=ms(E3), pa="0.099", up="9")))
    await persistence.drain()
    state = position_state(engine)
    assert state is not None
    assert state["quantity"] == Decimal("0.020")
    assert state["status"] == PositionStatus.OPEN.value
    assert persistence.stats.positions_stale == 1
    assert persistence.stats.positions_inserted == 1
    assert persistence.stats.failures == 0


async def test_a_position_in_unknown_leaves_it_with_user_data_evidence(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    insert_and_commit(
        engine,
        make_position(
            1,
            position_id=position_id_for("BTCUSDT", "BOTH"),
            status="UNKNOWN",
            quantity=Decimal("0"),
        ),
    )
    persistence = build(store=store, db=db, journal=journal, executor=executor, intents=Intents())
    persistence.account_sink(account_event(event_ms=ms(E3), pa="0.010"))
    await persistence.drain()
    state = position_state(engine)
    assert state is not None and state["status"] == PositionStatus.OPEN.value
    events = journal_rows(engine, UNKNOWN_EXIT_EVIDENCE)
    assert len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert payload["evidence_source"] == "USER_DATA_EVENT"
    assert payload["observed_at_utc"] == E3.isoformat()


async def test_missing_breakeven_is_never_invented_and_a_flat_unseen_position_is_skipped(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    persistence = build(store=store, db=db, journal=journal, executor=executor, intents=Intents())
    persistence.account_sink(account_event(event_ms=ms(E3), pa="0"))
    persistence.account_sink(account_event(event_ms=ms(E3), pa="0.010", bep=None))
    await persistence.drain()
    assert position_state(engine) is None
    assert persistence.stats.positions_flat_skipped == 1
    events = journal_rows(engine, STREAM_PERSISTENCE_FAILURE)
    assert [json.loads(e.payload_json)["reason"] for e in events] == [FAIL_MISSING_FIELD]


async def test_an_existing_position_keeps_stored_values_the_event_omits(
    engine: Engine,
    db: OperationalDatabase,
    store: PgTradingEntityStore,
    journal: PgJournalStore,
    executor: StoreExecutor,
) -> None:
    insert_and_commit(
        engine,
        make_position(
            1,
            position_id=position_id_for("BTCUSDT", "BOTH"),
            break_even_price=Decimal("777"),
            realized_pnl=Decimal("-3"),
        ),
    )
    persistence = build(store=store, db=db, journal=journal, executor=executor, intents=Intents())
    persistence.account_sink(account_event(event_ms=ms(E3), pa="0.030", bep=None, cr=None))
    await persistence.drain()
    state = position_state(engine)
    assert state is not None
    assert (state["quantity"], state["break_even_price"]) == (Decimal("0.030"), Decimal("777"))
    with engine.connect() as conn:
        realized = conn.execute(
            text("SELECT realized_pnl FROM positions WHERE position_id = :p"),
            {"p": position_id_for("BTCUSDT", "BOTH")},
        ).scalar_one()
    assert realized == Decimal("-3")


# --------------------------------------------------------------------------- #
# The sinks never block the loop.
# --------------------------------------------------------------------------- #


class _BlockedStore:
    """A store whose first read waits for an Event: the write cannot finish until released."""

    def __init__(self, gate: threading.Event) -> None:
        self.gate = gate
        self.entered = threading.Event()
        self.thread: str | None = None

    def get_order_by_client_order_id(self, client_id: str, *, tx: Any = None) -> None:
        self.thread = threading.current_thread().name
        self.entered.set()
        assert self.gate.wait(timeout=10)
        return None


class _FakeDb:
    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield None


async def test_the_sink_returns_before_the_database_write_completes() -> None:
    import asyncio

    gate = threading.Event()
    fake_store = _BlockedStore(gate)
    failures: list[JournalEvent] = []
    executor = StoreExecutor()
    try:
        persistence = StreamPersistence(
            executor=executor,
            store=fake_store,  # type: ignore[arg-type]
            database=_FakeDb(),  # type: ignore[arg-type]
            intents=Intents(),
            journal=failures.append,
            clock=lambda: NOW,
            correlation_id=SESSION,
        )
        persistence.exchange_state_sink(update("NEW", E1))
        assert persistence.pending == 1  # returned at once, the write has not completed
        for _ in range(200):
            if fake_store.entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert fake_store.entered.is_set()
        assert fake_store.thread is not None and fake_store.thread.startswith(WRITER_THREAD_PREFIX)
        assert persistence.pending == 1  # still blocked in the store, the loop is free
        gate.set()
        await persistence.drain()
        assert persistence.pending == 0
        assert [json.loads(e.payload_json)["reason"] for e in failures] == [FAIL_NO_INTENT]
    finally:
        gate.set()
        executor.close()
