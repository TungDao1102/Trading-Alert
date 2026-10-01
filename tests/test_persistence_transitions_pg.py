"""PgTradingEntityStore: in-transaction state machines, precision guard, DB rule parity (17-10).

Pins, against a real PostgreSQL server (each test on a generated `t17_<hex>_test` clone built
by `alembic upgrade head`):

  - DOMN-04 / D-20: every status change takes the row lock, treats an unchanged status as an
    idempotent no-op, calls `assert_transition`, and applies a conditional UPDATE. An illegal
    move raises `IllegalTransition` and writes nothing; two concurrent writers cannot both win;
  - the PostgreSQL terminal triggers of migration 0004 refuse exactly the states in
    `transitions.TERMINAL_STATES` and accept every legal move out of a non-terminal state
    (parity, so the Python tables and the database rule cannot drift);
  - D-12 / F-410: a Decimal with more than 18 fractional digits is refused with
    `PrecisionError` before PostgreSQL could round it, naming the field and never the value;
  - D-03: an order transition and its journal event commit together or not at all;
  - idempotent inserts compare the stored row (`RowConflict` on a different entity) and fills
    are idempotent on `(order_id, exchange_trade_id)`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from src.db.models import ExecutionIntentRow
from src.domain.enums import (
    ApprovalResult,
    ExecutionIntentStatus,
    OrderStatus,
    PositionStatus,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.fill import Fill
from src.domain.journal import JournalEvent
from src.domain.order import Order
from src.domain.position import Position
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.domain.transitions import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    IllegalTransition,
    TransitionKind,
)
from src.persistence.engine import make_sync_engine
from src.persistence.entities import PgTradingEntityStore
from src.persistence.errors import ParentRowMissing, PrecisionError, RowConflict
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import (
    T0,
    T1,
    expect_db_error,
    hexid,
    insert_and_commit,
    make_approval,
    make_order,
    make_plan,
    make_position,
    make_signal,
)

_RAISE = "P0001"
NOW = T0 + timedelta(minutes=7, microseconds=123456)


# --------------------------------------------------------------------------- #
# Fixtures and domain builders (the store speaks domain objects only).
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
def store(db: OperationalDatabase) -> PgTradingEntityStore:
    return PgTradingEntityStore(db)


def signal_entity(n: int = 1, **overrides: Any) -> Signal:
    values: dict[str, Any] = {
        "signal_id": hexid(n),
        "strategy_id": "trend-pullback",
        "strategy_version": "v1.0.0",
        "parameter_set_id": "baseline-v1",
        "parameter_set_hash": "b" * 64,
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "setup_type": "TREND_PULLBACK_LONG",
        "source_timeframe": "1h",
        "source_candle_close_utc": T0,
        "detected_at_utc": T0,
        "status": SignalStatus.DETECTED,
        "expires_at_utc": T1,
        "invalidated_at_utc": None,
    }
    values.update(overrides)
    return Signal(**values)


def plan_entity(n: int = 1, signal_n: int = 1, **overrides: Any) -> TradePlan:
    values: dict[str, Any] = {
        "trade_plan_id": hexid(0x1000 + n),
        "signal_id": hexid(signal_n),
        "trade_plan_version": "v1.0.0",
        "entry_model": "LIMIT_ZONE",
        "entry_min_price": Decimal("50000"),
        "entry_max_price": Decimal("50100"),
        "stop_loss_price": Decimal("49500"),
        "take_profit_json": "[]",
        "invalidation_rule_json": "{}",
        "expiry_utc": T1,
        "expected_rr_json": "{}",
        "risk_rate": Decimal("0.005"),
        "risk_budget": Decimal("4"),
        "suggested_quantity": Decimal("0.08"),
        "quantity_before_rounding": Decimal("0.08"),
        "quantity_after_rounding": Decimal("0.08"),
        "quantization_decision": "ACCEPTED",
        "plan_hash": "d" * 64,
        "status": TradePlanStatus.READY,
        "created_at_utc": T0,
    }
    values.update(overrides)
    return TradePlan(**values)


def position_entity(n: int = 1, **overrides: Any) -> Position:
    values: dict[str, Any] = {
        "position_id": hexid(0x4000 + n),
        "symbol": "BTCUSDT",
        "position_side": "BOTH",
        "mode": "ONE_WAY",
        "quantity": Decimal("0.08"),
        "entry_price": Decimal("50050"),
        "break_even_price": Decimal("50060"),
        "unrealized_pnl": Decimal("0"),
        "realized_pnl": Decimal("0"),
        "opened_at_utc": T0,
        "updated_at_utc": T0,
        "closed_at_utc": None,
        "status": PositionStatus.OPEN,
    }
    values.update(overrides)
    return Position(**values)


def order_entity(n: int = 1, plan_n: int | None = 1, **overrides: Any) -> Order:
    values: dict[str, Any] = {
        "order_id": hexid(0x5000 + n),
        "trade_plan_id": hexid(0x1000 + plan_n) if plan_n is not None else None,
        "position_id": None,
        "parent_order_id": None,
        "order_role": "ENTRY",
        "exchange": "BINANCE_USDM",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "order_type": "LIMIT",
        "time_in_force": "GTC",
        "quantity": Decimal("0.08"),
        "price": Decimal("50050"),
        "stop_price": None,
        "close_position": False,
        "reduce_only": False,
        "client_order_id": f"x-{n:032x}EN",
        "exchange_order_id": None,
        "algo_client_id": None,
        "exchange_status": "NEW",
        "local_status": OrderStatus.NEW,
        "submitted_at_utc": T0,
        "updated_at_utc": T0,
        "canceled_at_utc": None,
    }
    values.update(overrides)
    return Order(**values)


def fill_entity(n: int = 1, order_n: int = 1, **overrides: Any) -> Fill:
    values: dict[str, Any] = {
        "fill_id": hexid(0x6000 + n),
        "order_id": hexid(0x5000 + order_n),
        "exchange_trade_id": f"trade-{n}",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "fill_price": Decimal("50050"),
        "fill_quantity": Decimal("0.08"),
        "quote_quantity": Decimal("4004"),
        "commission": Decimal("0.00008"),
        "commission_asset": "USDT",
        "realized_pnl": Decimal("0"),
        "fill_time_utc": T0,
        "is_maker": False,
    }
    values.update(overrides)
    return Fill(**values)


def seed_parents(store: PgTradingEntityStore) -> None:
    """Signal 1 -> plan 1, committed (parents first)."""
    store.insert_signal(signal_entity(1))
    store.insert_trade_plan(plan_entity(1, 1))


# --------------------------------------------------------------------------- #
# Signal transitions.
# --------------------------------------------------------------------------- #


def test_signal_round_trip_and_forward_transitions(store: PgTradingEntityStore) -> None:
    sig = signal_entity(1)
    store.insert_signal(sig)
    assert store.get_signal(sig.signal_id) == sig

    notified = store.transition_signal(sig.signal_id, SignalStatus.NOTIFIED, now_utc=NOW)
    assert notified == replace(sig, status=SignalStatus.NOTIFIED)
    approved = store.transition_signal(sig.signal_id, SignalStatus.APPROVED, now_utc=NOW)
    assert approved.status is SignalStatus.APPROVED
    assert store.get_signal(sig.signal_id) == approved


def test_signal_illegal_transition_from_terminal_raises_and_leaves_row(
    store: PgTradingEntityStore,
) -> None:
    sig = signal_entity(1)
    store.insert_signal(sig)
    store.transition_signal(sig.signal_id, SignalStatus.EXPIRED, now_utc=NOW)
    before = store.get_signal(sig.signal_id)
    with pytest.raises(IllegalTransition) as caught:
        store.transition_signal(sig.signal_id, SignalStatus.APPROVED, now_utc=NOW)
    assert caught.value.kind is TransitionKind.SIGNAL
    assert (caught.value.old, caught.value.new) == ("EXPIRED", "APPROVED")
    assert store.get_signal(sig.signal_id) == before


def test_signal_same_status_is_an_idempotent_no_op(store: PgTradingEntityStore) -> None:
    sig = signal_entity(1)
    store.insert_signal(sig)
    store.transition_signal(sig.signal_id, SignalStatus.INVALIDATED, now_utc=NOW)
    stored = store.get_signal(sig.signal_id)
    later = NOW + timedelta(hours=1)
    again = store.transition_signal(sig.signal_id, SignalStatus.INVALIDATED, now_utc=later)
    assert again == stored
    assert again is not None and again.invalidated_at_utc == NOW  # not rewritten


def test_signal_invalidated_sets_invalidated_at_from_injected_clock(
    store: PgTradingEntityStore,
) -> None:
    sig = signal_entity(1)
    store.insert_signal(sig)
    out = store.transition_signal(sig.signal_id, SignalStatus.INVALIDATED, now_utc=NOW)
    assert out.invalidated_at_utc == NOW
    assert out.status is SignalStatus.INVALIDATED


def test_transition_of_unknown_row_raises_row_conflict(store: PgTradingEntityStore) -> None:
    with pytest.raises(RowConflict):
        store.transition_signal(hexid(99), SignalStatus.NOTIFIED, now_utc=NOW)
    assert store.get_signal(hexid(99)) is None


# --------------------------------------------------------------------------- #
# TradePlan, Order, Position transitions.
# --------------------------------------------------------------------------- #


def test_trade_plan_transitions_and_illegal_supersede(store: PgTradingEntityStore) -> None:
    seed_parents(store)
    plan_id = hexid(0x1001)
    assert store.transition_trade_plan(
        plan_id, TradePlanStatus.APPROVAL_PENDING, now_utc=NOW
    ).status is (TradePlanStatus.APPROVAL_PENDING)
    store.transition_trade_plan(plan_id, TradePlanStatus.APPROVED, now_utc=NOW)
    with pytest.raises(IllegalTransition):
        store.transition_trade_plan(plan_id, TradePlanStatus.SUPERSEDED, now_utc=NOW)
    stored = store.get_trade_plan(plan_id)
    assert stored is not None and stored.status is TradePlanStatus.APPROVED


def test_order_new_to_filled_then_back_is_illegal(store: PgTradingEntityStore) -> None:
    seed_parents(store)
    order = order_entity(1)
    store.insert_order(order)
    filled = store.transition_order(order.order_id, OrderStatus.FILLED, now_utc=NOW)
    assert filled.local_status is OrderStatus.FILLED
    assert filled.updated_at_utc == NOW
    assert filled.canceled_at_utc is None
    with pytest.raises(IllegalTransition):
        store.transition_order(order.order_id, OrderStatus.NEW, now_utc=NOW)
    assert store.get_order(order.order_id) == filled


def test_order_canceled_sets_canceled_at_and_updated_at(store: PgTradingEntityStore) -> None:
    seed_parents(store)
    order = order_entity(1)
    store.insert_order(order)
    out = store.transition_order(order.order_id, OrderStatus.CANCELED, now_utc=NOW)
    assert out.local_status is OrderStatus.CANCELED
    assert out.canceled_at_utc == NOW
    assert out.updated_at_utc == NOW


def test_position_open_to_closed_sets_closed_at_and_reopen_is_illegal(
    store: PgTradingEntityStore,
) -> None:
    pos = position_entity(1)
    store.insert_position(pos)
    closed = store.transition_position(pos.position_id, PositionStatus.CLOSED, now_utc=NOW)
    assert closed.status is PositionStatus.CLOSED
    assert closed.closed_at_utc == NOW
    assert closed.updated_at_utc == NOW
    with pytest.raises(IllegalTransition):
        store.transition_position(pos.position_id, PositionStatus.OPEN, now_utc=NOW)
    assert store.get_position(pos.position_id) == closed


def test_position_closing_is_not_a_closed_timestamp(store: PgTradingEntityStore) -> None:
    pos = position_entity(1)
    store.insert_position(pos)
    closing = store.transition_position(pos.position_id, PositionStatus.CLOSING, now_utc=NOW)
    assert closing.closed_at_utc is None
    assert closing.updated_at_utc == NOW


# --------------------------------------------------------------------------- #
# Row lock: two concurrent writers cannot both apply a transition.
# --------------------------------------------------------------------------- #


def test_concurrent_transitions_apply_exactly_once(pg_db: str, store: PgTradingEntityStore) -> None:
    sig = signal_entity(1, status=SignalStatus.NOTIFIED)
    store.insert_signal(sig)
    barrier = threading.Barrier(2)
    outcomes: dict[str, object] = {}

    def attempt(label: str, target: SignalStatus) -> None:
        engine = make_sync_engine(pg_db)
        try:
            local = PgTradingEntityStore(OperationalDatabase(engine))
            barrier.wait(timeout=10)
            try:
                outcomes[label] = local.transition_signal(sig.signal_id, target, now_utc=NOW)
            except IllegalTransition as exc:
                outcomes[label] = exc
        finally:
            engine.dispose()

    threads = [
        threading.Thread(target=attempt, args=("approve", SignalStatus.APPROVED)),
        threading.Thread(target=attempt, args=("skip", SignalStatus.SKIPPED_USER)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    wins = [v for v in outcomes.values() if isinstance(v, Signal)]
    losses = [v for v in outcomes.values() if isinstance(v, IllegalTransition)]
    assert len(wins) == 1 and len(losses) == 1, outcomes
    final = store.get_signal(sig.signal_id)
    assert final == wins[0]


# --------------------------------------------------------------------------- #
# Idempotent inserts, conflicts, missing parents.
# --------------------------------------------------------------------------- #


def test_insert_trade_plan_twice_is_a_no_op_and_a_different_plan_conflicts(
    store: PgTradingEntityStore,
) -> None:
    store.insert_signal(signal_entity(1))
    plan = plan_entity(1, 1)
    store.insert_trade_plan(plan)
    store.insert_trade_plan(plan)
    assert store.get_trade_plan(plan.trade_plan_id) == plan
    with pytest.raises(RowConflict):
        store.insert_trade_plan(replace(plan, stop_loss_price=Decimal("49400")))
    assert store.get_trade_plan(plan.trade_plan_id) == plan


def test_replayed_insert_after_the_entity_advanced_is_a_no_op(
    store: PgTradingEntityStore,
) -> None:
    """Lifecycle fields evolve after insertion; a replay of the initial insert is not a conflict."""
    sig = signal_entity(1)
    store.insert_signal(sig)
    notified = store.transition_signal(sig.signal_id, SignalStatus.NOTIFIED, now_utc=NOW)
    store.insert_signal(sig)
    assert store.get_signal(sig.signal_id) == notified


def test_insert_signal_with_different_content_conflicts(store: PgTradingEntityStore) -> None:
    sig = signal_entity(1)
    store.insert_signal(sig)
    with pytest.raises(RowConflict):
        store.insert_signal(replace(sig, symbol="ETHUSDT"))


def test_missing_parents_raise_parent_row_missing(store: PgTradingEntityStore) -> None:
    with pytest.raises(ParentRowMissing):
        store.insert_trade_plan(plan_entity(1, 7))
    store.insert_signal(signal_entity(1))
    with pytest.raises(ParentRowMissing):
        store.insert_order(order_entity(1, plan_n=1))  # trade plan 1 was never inserted


def test_order_unique_client_id_violation_is_a_row_conflict(store: PgTradingEntityStore) -> None:
    seed_parents(store)
    store.insert_order(order_entity(1))
    with pytest.raises(RowConflict):
        store.insert_order(order_entity(2, client_order_id=order_entity(1).client_order_id))


# --------------------------------------------------------------------------- #
# Fills.
# --------------------------------------------------------------------------- #


def test_record_fill_is_idempotent_and_conflicts_on_a_different_fill(
    store: PgTradingEntityStore,
) -> None:
    seed_parents(store)
    order = order_entity(1)
    store.insert_order(order)
    fill = fill_entity(1, 1)
    store.record_fill(fill)
    store.record_fill(fill)
    assert store.list_fills_for_order(order.order_id) == [fill]
    different = replace(fill, fill_id=hexid(0x6099), fill_quantity=Decimal("0.07"))
    with pytest.raises(RowConflict):
        store.record_fill(different)  # same (order_id, exchange_trade_id), other content
    assert store.list_fills_for_order(order.order_id) == [fill]


def test_record_fill_for_missing_order_raises_parent_row_missing(
    store: PgTradingEntityStore,
) -> None:
    with pytest.raises(ParentRowMissing):
        store.record_fill(fill_entity(1, 1))


def test_list_fills_orders_by_time_then_id(store: PgTradingEntityStore) -> None:
    seed_parents(store)
    store.insert_order(order_entity(1))
    late = fill_entity(1, 1, fill_time_utc=T0 + timedelta(minutes=2))
    early = fill_entity(2, 1, fill_time_utc=T0 + timedelta(minutes=1))
    store.record_fill(late)
    store.record_fill(early)
    assert store.list_fills_for_order(hexid(0x5001)) == [early, late]


# --------------------------------------------------------------------------- #
# Precision guard (D-12, F-410): refuse what NUMERIC(38,18) would silently round.
# --------------------------------------------------------------------------- #

NINETEEN = Decimal("0.1234567890123456789")
EIGHTEEN = Decimal("0.123456789012345678")


def _insert_plan(store: PgTradingEntityStore, **kw: Any) -> None:
    store.insert_trade_plan(plan_entity(2, 1, **kw))


def _insert_order(store: PgTradingEntityStore, **kw: Any) -> None:
    store.insert_order(order_entity(2, 1, **kw))


def _insert_position(store: PgTradingEntityStore, **kw: Any) -> None:
    store.insert_position(position_entity(1, **kw))


def _record_fill(store: PgTradingEntityStore, **kw: Any) -> None:
    store.record_fill(fill_entity(1, 1, **kw))


_PLAN_FIELDS = (
    "entry_min_price",
    "entry_max_price",
    "stop_loss_price",
    "risk_rate",
    "risk_budget",
    "suggested_quantity",
    "quantity_before_rounding",
    "quantity_after_rounding",
)
_ORDER_FIELDS = ("quantity", "price", "stop_price")
_POSITION_FIELDS = (
    "quantity",
    "entry_price",
    "break_even_price",
    "unrealized_pnl",
    "realized_pnl",
)
_FILL_FIELDS = ("fill_price", "fill_quantity", "quote_quantity", "commission", "realized_pnl")

_GUARD_CASES: list[tuple[str, str, Callable[..., None]]] = (
    [("trade_plans", f, _insert_plan) for f in _PLAN_FIELDS]
    + [("orders", f, _insert_order) for f in _ORDER_FIELDS]
    + [("positions", f, _insert_position) for f in _POSITION_FIELDS]
    + [("fills", f, _record_fill) for f in _FILL_FIELDS]
)


def _count(engine: Engine, table: str) -> int:
    with Session(engine) as session:
        return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())  # noqa: S608


@pytest.mark.parametrize(
    ("table", "field", "insert"), _GUARD_CASES, ids=[f"{t}.{f}" for t, f, _i in _GUARD_CASES]
)
def test_nineteen_fractional_digits_are_refused_before_postgres_can_round(
    engine: Engine,
    store: PgTradingEntityStore,
    table: str,
    field: str,
    insert: Callable[..., None],
) -> None:
    seed_parents(store)  # signal 1, plan 1
    store.insert_order(order_entity(1, 1))  # order 1 is the parent of the fill under test
    before = _count(engine, table)
    with pytest.raises(PrecisionError) as caught:
        insert(store, **{field: NINETEEN})
    message = str(caught.value)
    assert field in message  # names the field ...
    assert "1234567890123456789" not in message  # ... never the value
    assert _count(engine, table) == before, "no row may exist after a refused insert"


@pytest.mark.parametrize("field", _PLAN_FIELDS)
def test_eighteen_fractional_digits_are_accepted_and_round_trip_exactly(
    store: PgTradingEntityStore, field: str
) -> None:
    store.insert_signal(signal_entity(1))
    plan = plan_entity(1, 1, **{field: EIGHTEEN})
    store.insert_trade_plan(plan)
    stored = store.get_trade_plan(plan.trade_plan_id)
    assert stored == plan
    assert getattr(stored, field) == EIGHTEEN


def test_non_finite_decimal_is_a_precision_error(store: PgTradingEntityStore) -> None:
    store.insert_signal(signal_entity(1))
    with pytest.raises(PrecisionError):
        store.insert_trade_plan(plan_entity(1, 1, entry_min_price=Decimal("NaN")))


def test_integer_part_overflow_still_raises_a_database_error(
    store: PgTradingEntityStore,
) -> None:
    from sqlalchemy.exc import DataError

    store.insert_signal(signal_entity(1))
    with pytest.raises(DataError):
        store.insert_trade_plan(plan_entity(1, 1, entry_min_price=Decimal(10) ** 21))


# --------------------------------------------------------------------------- #
# D-03: an order transition and its journal event are one unit of work.
# --------------------------------------------------------------------------- #


class _Boom(Exception):
    pass


def _order_event(order_id: str, n: int = 1) -> JournalEvent:
    return JournalEvent(
        journal_event_id=hexid(0x7000 + n),
        occurred_at_utc=NOW,
        event_type="ORDER_FILLED",
        entity_type="order",
        entity_id=order_id,
        correlation_id=f"corr-{n}",
        order_id=order_id,
        payload_json="{}",
        created_at_utc=NOW,
    )


def test_order_transition_and_journal_event_commit_together(
    db: OperationalDatabase, store: PgTradingEntityStore
) -> None:
    seed_parents(store)
    order = order_entity(1)
    store.insert_order(order)
    journal = PgJournalStore(db)
    event = _order_event(order.order_id)
    with db.transaction() as tx:
        store.transition_order(order.order_id, OrderStatus.FILLED, now_utc=NOW, tx=tx)
        journal.append(tx, event)
    stored = store.get_order(order.order_id)
    assert stored is not None and stored.local_status is OrderStatus.FILLED
    assert journal.get(event.journal_event_id) == event


def test_order_transition_and_journal_event_roll_back_together(
    db: OperationalDatabase, store: PgTradingEntityStore
) -> None:
    seed_parents(store)
    order = order_entity(1)
    store.insert_order(order)
    journal = PgJournalStore(db)
    event = _order_event(order.order_id)
    with pytest.raises(_Boom), db.transaction() as tx:
        store.transition_order(order.order_id, OrderStatus.FILLED, now_utc=NOW, tx=tx)
        journal.append(tx, event)
        raise _Boom
    stored = store.get_order(order.order_id)
    assert stored == order  # unchanged
    assert journal.get(event.journal_event_id) is None


def test_illegal_transition_inside_a_unit_of_work_writes_nothing(
    db: OperationalDatabase, store: PgTradingEntityStore
) -> None:
    seed_parents(store)
    order = order_entity(1, local_status=OrderStatus.FILLED)
    store.insert_order(order)
    journal = PgJournalStore(db)
    event = _order_event(order.order_id)
    with pytest.raises(IllegalTransition), db.transaction() as tx:
        journal.append(tx, event)
        store.transition_order(order.order_id, OrderStatus.NEW, now_utc=NOW, tx=tx)
    assert journal.get(event.journal_event_id) is None


# --------------------------------------------------------------------------- #
# D-20 parity: the database terminal rule equals transitions.TERMINAL_STATES.
# --------------------------------------------------------------------------- #


def _intent(n: int, **overrides: Any) -> ExecutionIntentRow:
    values: dict[str, Any] = {
        "approval_id": hexid(0x2000 + n),
        "role": "ENTRY",
        "trade_plan_id": hexid(0x1000 + n),
        "plan_hash": "d" * 64,
        "client_order_id": f"x-{n:032x}EN",
        "algo_client_id": None,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "intended_quantity": Decimal("0.08"),
        "intended_price": Decimal("50050"),
        "intent_status": "INTENDED",
        "outcome_recorded": False,
        "intended_at_utc": T0,
        "updated_at_utc": T0,
    }
    values.update(overrides)
    return ExecutionIntentRow(**values)


def _build_row(kind: TransitionKind, n: int, status: str) -> list[object]:
    """Parent-complete rows for entity number `n` of `kind`, carrying `status`."""
    if kind is TransitionKind.SIGNAL:
        return [make_signal(n, status=status)]
    if kind is TransitionKind.POSITION:
        return [make_position(n, status=status)]
    base: list[object] = [make_signal(n), make_plan(n, n)]
    if kind is TransitionKind.TRADE_PLAN:
        return [make_signal(n), make_plan(n, n, status=status)]
    if kind is TransitionKind.ORDER:
        return [*base, make_order(n, n, local_status=status)]
    if kind is TransitionKind.APPROVAL:
        return [*base, make_approval(n, n, n, status=status, result=status)]
    return [
        *base,
        make_approval(n, n, n, status="APPROVED", result="APPROVED"),
        _intent(n, intent_status=status),
    ]


_TABLE = {
    TransitionKind.SIGNAL: ("signals", "status"),
    TransitionKind.TRADE_PLAN: ("trade_plans", "status"),
    TransitionKind.ORDER: ("orders", "local_status"),
    TransitionKind.POSITION: ("positions", "status"),
    TransitionKind.APPROVAL: ("approvals", "status"),
    TransitionKind.EXECUTION_INTENT: ("execution_intents", "intent_status"),
}
_ENUM_VALUES = {
    TransitionKind.SIGNAL: [s.value for s in SignalStatus],
    TransitionKind.TRADE_PLAN: [s.value for s in TradePlanStatus],
    TransitionKind.ORDER: [s.value for s in OrderStatus],
    TransitionKind.POSITION: [s.value for s in PositionStatus],
    TransitionKind.APPROVAL: [s.value for s in ApprovalResult],
    TransitionKind.EXECUTION_INTENT: [s.value for s in ExecutionIntentStatus],
}


def _key_column(table: str) -> str:
    return {
        "signals": "signal_id",
        "trade_plans": "trade_plan_id",
        "orders": "order_id",
        "positions": "position_id",
        "approvals": "approval_id",
        "execution_intents": "approval_id",
    }[table]


@pytest.mark.parametrize("kind", list(TransitionKind), ids=lambda k: k.value)
def test_every_enum_member_has_a_transition_table_entry(kind: TransitionKind) -> None:
    assert sorted(LEGAL_TRANSITIONS[kind]) == sorted(_ENUM_VALUES[kind])


@pytest.mark.parametrize("kind", list(TransitionKind), ids=lambda k: k.value)
def test_database_refuses_every_terminal_state_exit_and_accepts_every_legal_move(
    engine: Engine, kind: TransitionKind
) -> None:
    table, column = _TABLE[kind]
    key = _key_column(table)
    terminals = sorted(TERMINAL_STATES[kind])
    assert terminals, "every machine has at least one terminal state"

    # Seed one row per (state) for terminal-exit probing and one per (state, successor) pair.
    next_n = 1
    terminal_rows: list[tuple[str, str, int]] = []
    for state in terminals:
        for other in _ENUM_VALUES[kind]:
            if other != state:
                terminal_rows.append((state, other, next_n))
                next_n += 1
    legal_rows: list[tuple[str, str, int]] = []
    for old, successors in LEGAL_TRANSITIONS[kind].items():
        for new in sorted(successors):
            legal_rows.append((old, new, next_n))
            next_n += 1

    seed: list[object] = []
    seen_parents: set[tuple[str, int]] = set()
    for state, _other, n in terminal_rows + legal_rows:
        for row in _build_row(kind, n, state):
            ident = (type(row).__name__, n)
            if ident in seen_parents:
                continue
            seen_parents.add(ident)
            seed.append(row)
    insert_and_commit(engine, *seed)

    def row_id(n: int) -> str:
        if kind is TransitionKind.EXECUTION_INTENT or kind is TransitionKind.APPROVAL:
            return hexid(0x2000 + n)
        return {
            "signals": hexid(n),
            "trade_plans": hexid(0x1000 + n),
            "orders": hexid(0x5000 + n),
            "positions": hexid(0x4000 + n),
        }[table]

    for state, other, n in terminal_rows:
        with expect_db_error(_RAISE) as info, Session(engine) as session:
            session.execute(
                text(f"UPDATE {table} SET {column} = :v WHERE {key} = :k"),  # noqa: S608
                {"v": other, "k": row_id(n)},
            )
            session.commit()
        assert "terminal" in info.message and table in info.message, (state, other)

    for old, new, n in legal_rows:
        with Session(engine) as session:
            result = session.execute(
                text(f"UPDATE {table} SET {column} = :v WHERE {key} = :k"),  # noqa: S608
                {"v": new, "k": row_id(n)},
            )
            session.commit()
        assert result.rowcount == 1, (old, new)  # type: ignore[attr-defined]
