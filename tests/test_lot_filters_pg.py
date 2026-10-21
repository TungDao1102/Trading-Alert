"""PgLotFilterStore against a real PostgreSQL server (Phase 20, plan 20-18, Q3, D-21).

Each test runs on a generated `t17_<hex>_test` clone built by `alembic upgrade head`. The table
`validated_lot_filters` holds one row per symbol: the last validated exchangeInfo filters and
their fetch time. A stored row is only ever used by the emergency close, flagged stale.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.domain.lot_filters import LotFilters
from src.persistence.engine import make_sync_engine
from src.persistence.lot_filters import PgLotFilterStore
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import T0, expect_db_error

D = Decimal
_CHECK_VIOLATION = "23514"


def make_filters(symbol: str = "BTCUSDT", **overrides: str) -> LotFilters:
    values = {
        "price_tick_size": "0.10",
        "lot_min_quantity": "0.001",
        "lot_max_quantity": "1000.000000000000000001",
        "lot_step_size": "0.001",
        "market_lot_min_quantity": "0.001",
        "market_lot_max_quantity": "120.5",
        "market_lot_step_size": "0.001",
        "min_notional": "100",
    }
    values.update(overrides)
    return LotFilters(symbol=symbol, **{k: D(v) for k, v in values.items()})


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def store(engine: Engine) -> PgLotFilterStore:
    return PgLotFilterStore(OperationalDatabase(engine))


def test_upsert_then_get_round_trips_every_decimal_exactly(store: PgLotFilterStore) -> None:
    filters = make_filters()

    store.upsert(filters, fetched_at_utc=T0)
    # A NEW store instance reads it back, as a restart would.
    got = PgLotFilterStore(store._db).get("BTCUSDT")  # noqa: SLF001

    assert got is not None
    assert got.filters == filters
    assert got.filters.lot_max_quantity == D("1000.000000000000000001")
    assert got.fetched_at_utc == T0
    assert got.filters_stale is True


def test_get_of_an_unknown_symbol_is_none(store: PgLotFilterStore) -> None:
    assert store.get("ETHUSDT") is None


def test_a_later_fetch_replaces_the_row_and_keeps_one_row_per_symbol(
    store: PgLotFilterStore, engine: Engine
) -> None:
    store.upsert(make_filters(), fetched_at_utc=T0)
    later = make_filters(market_lot_max_quantity="90")
    store.upsert(later, fetched_at_utc=T0 + timedelta(hours=1))
    store.upsert(make_filters("ETHUSDT"), fetched_at_utc=T0)

    got = store.get("BTCUSDT")
    assert got is not None
    assert got.filters == later
    assert got.fetched_at_utc == T0 + timedelta(hours=1)
    with engine.connect() as conn:
        symbols = (
            conn.execute(text("SELECT symbol FROM validated_lot_filters ORDER BY symbol"))
            .scalars()
            .all()
        )
    assert symbols == ["BTCUSDT", "ETHUSDT"]


def test_an_older_fetch_never_replaces_a_newer_row(store: PgLotFilterStore) -> None:
    newer = make_filters(market_lot_max_quantity="90")
    store.upsert(newer, fetched_at_utc=T0 + timedelta(hours=1))

    store.upsert(make_filters(), fetched_at_utc=T0)

    got = store.get("BTCUSDT")
    assert got is not None
    assert got.filters == newer
    assert got.fetched_at_utc == T0 + timedelta(hours=1)


def test_a_naive_fetch_time_is_refused_and_nothing_is_written(store: PgLotFilterStore) -> None:
    with pytest.raises(ValueError, match="UTC-aware"):
        store.upsert(make_filters(), fetched_at_utc=T0.replace(tzinfo=None))
    assert store.get("BTCUSDT") is None


@pytest.mark.parametrize(
    "column",
    [
        "price_tick_size",
        "lot_min_quantity",
        "lot_max_quantity",
        "lot_step_size",
        "market_lot_min_quantity",
        "market_lot_max_quantity",
        "market_lot_step_size",
        "min_notional",
    ],
)
def test_postgresql_refuses_a_non_positive_value_that_bypasses_the_domain(
    store: PgLotFilterStore, engine: Engine, column: str
) -> None:
    store.upsert(make_filters(), fetched_at_utc=T0)
    with expect_db_error(_CHECK_VIOLATION), engine.begin() as conn:
        conn.execute(text(f"UPDATE validated_lot_filters SET {column} = 0"))


def test_postgresql_refuses_an_updated_time_before_the_fetch_time(
    store: PgLotFilterStore, engine: Engine
) -> None:
    store.upsert(make_filters(), fetched_at_utc=T0)
    with expect_db_error(_CHECK_VIOLATION), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE validated_lot_filters SET updated_at_utc = fetched_at_utc - interval '1 s'"
            )
        )
