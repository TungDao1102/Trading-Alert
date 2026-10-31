"""Monotonic exchange event time on orders and positions, against PostgreSQL (24-07, D-10, G4-043).

Pins, on a generated `t17_<hex>_test` clone built by `alembic upgrade head` (migration 0015):

  - `update_order_exchange_state` with an exchange event time applies an update only when it is
    not older than the stored one; an older update changes nothing and is reported as stale, a
    newer one applies and is stored, an equal time with the same state is an idempotent no-op
    (T-24-17);
  - a call without an event time keeps today's behaviour (returns the `Order`, never stale) and
    does not erase a stored event time;
  - `update_position_snapshot` follows the same rule, never touches `status`, accepts Decimal
    values only (a float is a `TypeError`) and refuses a value NUMERIC(38,18) would round
    (`PrecisionError`), writing nothing (T-24-19);
  - the event time must be UTC-aware.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.domain.enums import OrderStatus, PositionStatus
from src.domain.order import Order
from src.domain.position import Position
from src.persistence.engine import make_sync_engine
from src.persistence.entities import PgTradingEntityStore, StateUpdate
from src.persistence.errors import PrecisionError, RowConflict
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import (
    T0,
    hexid,
    insert_and_commit,
    make_order,
    make_plan,
    make_position,
    make_signal,
)

E1 = T0 + timedelta(minutes=1)
E2 = T0 + timedelta(minutes=2)
E3 = T0 + timedelta(minutes=3)
NOW = T0 + timedelta(minutes=9, microseconds=654321)
LATER = NOW + timedelta(seconds=5)
ORDER_ID = hexid(0x5001)
POSITION_ID = hexid(0x4001)


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def store(engine: Engine) -> PgTradingEntityStore:
    return PgTradingEntityStore(OperationalDatabase(engine))


def _seed_order(engine: Engine) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1), make_order(1, 1))


def _seed_position(engine: Engine, **overrides: Any) -> None:
    insert_and_commit(engine, make_position(1, **overrides))


def _order_event_time(engine: Engine) -> datetime | None:
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT exchange_event_time_utc FROM orders WHERE order_id = :k"),
            {"k": ORDER_ID},
        ).scalar_one()
    return value  # type: ignore[no-any-return]


def _position_event_time(engine: Engine) -> datetime | None:
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT snapshot_event_time_utc FROM positions WHERE position_id = :k"),
            {"k": POSITION_ID},
        ).scalar_one()
    return value  # type: ignore[no-any-return]


def _snapshot(
    store: PgTradingEntityStore, event_time: datetime, *, now: datetime = NOW, **values: Any
) -> StateUpdate[Position]:
    args: dict[str, Any] = {
        "quantity": Decimal("0.05"),
        "entry_price": Decimal("50100"),
        "break_even_price": Decimal("50110"),
        "unrealized_pnl": Decimal("1.25"),
        "realized_pnl": Decimal("-0.5"),
    }
    args.update(values)
    return store.update_position_snapshot(
        POSITION_ID, event_time_utc=event_time, now_utc=now, **args
    )


# --------------------------------------------------------------------------- #
# Orders.
# --------------------------------------------------------------------------- #


def test_a_new_order_has_no_event_time(engine: Engine) -> None:
    _seed_order(engine)
    assert _order_event_time(engine) is None


def test_the_first_event_applies_and_stores_its_time(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_order(engine)
    out = store.update_order_exchange_state(
        ORDER_ID,
        exchange_status="PARTIALLY_FILLED",
        exchange_order_id="111",
        now_utc=NOW,
        exchange_event_time_utc=E2,
    )
    assert isinstance(out, StateUpdate)
    assert out.stale is False
    assert out.entity.exchange_status == "PARTIALLY_FILLED"
    assert out.entity.exchange_order_id == "111"
    assert out.entity.updated_at_utc == NOW
    assert _order_event_time(engine) == E2


def test_an_older_event_changes_nothing_and_is_reported_stale(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_order(engine)
    applied = store.update_order_exchange_state(
        ORDER_ID,
        exchange_status="FILLED",
        exchange_order_id="111",
        now_utc=NOW,
        exchange_event_time_utc=E2,
    )
    before = store.get_order(ORDER_ID)
    stale = store.update_order_exchange_state(
        ORDER_ID,
        exchange_status="NEW",
        exchange_order_id="111",
        now_utc=LATER,
        exchange_event_time_utc=E1,
    )
    assert stale.stale is True
    assert stale.entity == before == applied.entity
    assert store.get_order(ORDER_ID) == before
    assert before is not None and before.exchange_status == "FILLED"
    assert before.updated_at_utc == NOW
    assert _order_event_time(engine) == E2


def test_a_newer_event_applies_and_moves_the_stored_time_forward(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_order(engine)
    store.update_order_exchange_state(
        ORDER_ID, exchange_status="NEW", now_utc=NOW, exchange_event_time_utc=E2
    )
    out = store.update_order_exchange_state(
        ORDER_ID, exchange_status="PARTIALLY_FILLED", now_utc=LATER, exchange_event_time_utc=E3
    )
    assert out.stale is False
    assert out.entity.exchange_status == "PARTIALLY_FILLED"
    assert out.entity.updated_at_utc == LATER
    assert _order_event_time(engine) == E3


def test_an_equal_time_with_the_same_state_is_an_idempotent_no_op(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_order(engine)
    first = store.update_order_exchange_state(
        ORDER_ID,
        exchange_status="NEW",
        exchange_order_id="111",
        now_utc=NOW,
        exchange_event_time_utc=E2,
    )
    again = store.update_order_exchange_state(
        ORDER_ID,
        exchange_status="NEW",
        exchange_order_id="111",
        now_utc=LATER,
        exchange_event_time_utc=E2,
    )
    assert again.stale is False
    assert again.entity == first.entity
    assert again.entity.updated_at_utc == NOW  # not rewritten
    assert _order_event_time(engine) == E2


def test_an_equal_time_with_a_different_state_applies(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    """Binance can send several updates with the same `E`; equal is not stale."""
    _seed_order(engine)
    store.update_order_exchange_state(
        ORDER_ID, exchange_status="NEW", now_utc=NOW, exchange_event_time_utc=E2
    )
    out = store.update_order_exchange_state(
        ORDER_ID, exchange_status="PARTIALLY_FILLED", now_utc=LATER, exchange_event_time_utc=E2
    )
    assert out.stale is False
    assert out.entity.exchange_status == "PARTIALLY_FILLED"


def test_without_an_event_time_the_old_behaviour_holds_and_the_stored_time_is_kept(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_order(engine)
    store.update_order_exchange_state(
        ORDER_ID, exchange_status="NEW", now_utc=NOW, exchange_event_time_utc=E2
    )
    out = store.update_order_exchange_state(ORDER_ID, exchange_status="CANCELED", now_utc=LATER)
    assert isinstance(out, Order)
    assert out.exchange_status == "CANCELED"
    assert out.local_status is OrderStatus.NEW
    assert _order_event_time(engine) == E2


def test_a_different_exchange_order_id_is_still_a_conflict_with_an_event_time(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_order(engine)
    store.update_order_exchange_state(
        ORDER_ID,
        exchange_status="NEW",
        exchange_order_id="111",
        now_utc=NOW,
        exchange_event_time_utc=E1,
    )
    with pytest.raises(RowConflict):
        store.update_order_exchange_state(
            ORDER_ID,
            exchange_status="NEW",
            exchange_order_id="222",
            now_utc=LATER,
            exchange_event_time_utc=E2,
        )
    assert _order_event_time(engine) == E1


@pytest.mark.parametrize(
    "bad",
    [
        datetime(2026, 9, 19, 12, 5),
        datetime(2026, 9, 19, 12, 5, tzinfo=timezone(timedelta(hours=7))),
    ],
    ids=["naive", "offset"],
)
def test_the_order_event_time_must_be_utc_aware(
    engine: Engine, store: PgTradingEntityStore, bad: datetime
) -> None:
    _seed_order(engine)
    with pytest.raises(ValueError, match="exchange_event_time_utc"):
        store.update_order_exchange_state(
            ORDER_ID, exchange_status="NEW", now_utc=NOW, exchange_event_time_utc=bad
        )
    assert _order_event_time(engine) is None


# --------------------------------------------------------------------------- #
# Positions.
# --------------------------------------------------------------------------- #


def test_a_new_position_has_no_event_time(engine: Engine) -> None:
    _seed_position(engine)
    assert _position_event_time(engine) is None


def test_the_first_snapshot_applies_every_value_and_never_touches_status(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_position(engine)
    out = _snapshot(store, E1)
    assert out.stale is False
    pos = out.entity
    assert pos.quantity == Decimal("0.05")
    assert pos.entry_price == Decimal("50100")
    assert pos.break_even_price == Decimal("50110")
    assert pos.unrealized_pnl == Decimal("1.25")
    assert pos.realized_pnl == Decimal("-0.5")
    assert pos.updated_at_utc == NOW
    assert pos.status is PositionStatus.OPEN
    assert pos.closed_at_utc is None
    assert store.get_position(POSITION_ID) == pos
    assert _position_event_time(engine) == E1


def test_a_newer_snapshot_replaces_an_older_one_and_a_stale_one_changes_nothing(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_position(engine)
    _snapshot(store, E1, quantity=Decimal("0.05"))
    newer = _snapshot(store, E2, now=LATER, quantity=Decimal("-0.07"))
    assert newer.stale is False
    assert newer.entity.quantity == Decimal("-0.07")  # signed: a short is legal
    assert _position_event_time(engine) == E2

    stale = _snapshot(store, E1, now=LATER + timedelta(seconds=1), quantity=Decimal("0.01"))
    assert stale.stale is True
    assert stale.entity == newer.entity
    assert store.get_position(POSITION_ID) == newer.entity
    assert _position_event_time(engine) == E2


def test_an_equal_time_with_the_same_values_is_an_idempotent_no_op(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_position(engine)
    first = _snapshot(store, E1)
    again = _snapshot(store, E1, now=LATER)
    assert again.stale is False
    assert again.entity == first.entity
    assert again.entity.updated_at_utc == NOW


def test_a_snapshot_never_changes_the_status_of_a_closing_position(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_position(engine, status="CLOSING")
    out = _snapshot(store, E1)
    assert out.entity.status is PositionStatus.CLOSING


def test_a_missing_position_is_a_conflict(store: PgTradingEntityStore) -> None:
    with pytest.raises(RowConflict):
        _snapshot(store, E1)


@pytest.mark.parametrize(
    "field",
    ["quantity", "entry_price", "break_even_price", "unrealized_pnl", "realized_pnl"],
)
def test_a_float_value_is_a_type_error_and_nothing_is_written(
    engine: Engine, store: PgTradingEntityStore, field: str
) -> None:
    _seed_position(engine)
    with pytest.raises(TypeError, match=field):
        _snapshot(store, E1, **{field: 1.5})
    assert _position_event_time(engine) is None
    assert store.get_position(POSITION_ID) == Position(
        position_id=POSITION_ID,
        symbol="BTCUSDT",
        position_side="BOTH",
        mode="ONE_WAY",
        quantity=Decimal("0.08"),
        entry_price=Decimal("50050"),
        break_even_price=Decimal("50060"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        opened_at_utc=T0,
        updated_at_utc=T0,
        closed_at_utc=None,
        status=PositionStatus.OPEN,
    )


def test_a_decimal_with_more_than_18_fractional_digits_is_refused_never_rounded(
    engine: Engine, store: PgTradingEntityStore
) -> None:
    _seed_position(engine)
    too_fine = Decimal("0." + "1" * 19)
    with pytest.raises(PrecisionError, match="positions.unrealized_pnl"):
        _snapshot(store, E1, unrealized_pnl=too_fine)
    assert _position_event_time(engine) is None
    stored = store.get_position(POSITION_ID)
    assert stored is not None and stored.unrealized_pnl == Decimal("0")


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
def test_a_non_finite_decimal_is_refused(
    engine: Engine, store: PgTradingEntityStore, bad: Decimal
) -> None:
    _seed_position(engine)
    with pytest.raises(PrecisionError):
        _snapshot(store, E1, realized_pnl=bad)
    assert _position_event_time(engine) is None


@pytest.mark.parametrize(
    "bad",
    [
        datetime(2026, 9, 19, 12, 5),
        datetime(2026, 9, 19, 12, 5, tzinfo=timezone(timedelta(hours=7))),
    ],
    ids=["naive", "offset"],
)
def test_the_snapshot_event_time_must_be_utc_aware(
    engine: Engine, store: PgTradingEntityStore, bad: datetime
) -> None:
    _seed_position(engine)
    with pytest.raises(ValueError, match="event_time_utc"):
        _snapshot(store, bad)
    assert _position_event_time(engine) is None


def test_the_now_time_must_be_utc_aware(engine: Engine, store: PgTradingEntityStore) -> None:
    _seed_position(engine)
    with pytest.raises(ValueError, match="now_utc"):
        _snapshot(store, E1, now=datetime(2026, 9, 19, 13, 0))
    assert _position_event_time(engine) is None


def test_the_event_time_round_trips_in_utc(engine: Engine, store: PgTradingEntityStore) -> None:
    _seed_position(engine)
    exact = datetime(2026, 9, 19, 12, 5, 6, 789000, tzinfo=UTC)
    _snapshot(store, exact)
    assert _position_event_time(engine) == exact
