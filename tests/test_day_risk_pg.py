"""PgDayRiskStore against a real PostgreSQL server (Phase 21, plan 21-09; D-07, D-14, F-963).

Each test runs on a generated `t17_<hex>_test` clone built by `alembic upgrade head`. The tables
`daily_risk_days` and `daily_loss_components` hold the UTC day's base, latch and loss
components. A restart inside the day (a new store instance) keeps all of it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from src.persistence.day_risk import PgDayRiskStore
from src.persistence.engine import make_sync_engine
from src.persistence.errors import PrecisionError, RowConflict, StoreUnavailable
from src.persistence.uow import OperationalDatabase
from src.risk.daily_loss import (
    ComponentKind,
    ComponentSource,
    DayRiskState,
    LossComponent,
)

from tests.support.pg_rows import expect_db_error

D = Decimal
DAY = date(2026, 10, 23)
PREVIOUS_DAY = date(2026, 10, 22)
BASE_AT = datetime(2026, 10, 23, 0, 5, tzinfo=UTC)
T1 = datetime(2026, 10, 23, 9, 30, tzinfo=UTC)
T2 = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)

#: A closed local port: connecting is refused at once, nothing is listening and no secret is used.
UNREACHABLE_URL = "postgresql+psycopg://trading@127.0.0.1:1/unreachable_test"


def make_state(
    *, utc_day: date = DAY, equity: str = "1000", base_at: datetime = BASE_AT
) -> DayRiskState:
    return DayRiskState(
        utc_day=utc_day, equity_at_day_start=D(equity), base_observed_at_utc=base_at
    )


def make_component(
    *,
    kind: ComponentKind = ComponentKind.FILL_PNL,
    source: ComponentSource = ComponentSource.USER_DATA_EVENT,
    source_key: str = "BTCUSDT:111:222",
    amount: str = "-12.5",
    asset: str = "USDT",
    event_time_utc: datetime = T1,
) -> LossComponent:
    return LossComponent(
        utc_day=event_time_utc.date(),
        kind=kind,
        source=source,
        source_key=source_key,
        amount=D(amount),
        asset=asset,
        event_time_utc=event_time_utc,
    )


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def store(engine: Engine) -> PgDayRiskStore:
    return PgDayRiskStore(OperationalDatabase(engine))


def _restarted(store: PgDayRiskStore) -> PgDayRiskStore:
    """A new store instance over the same database, as a restart would build."""
    return PgDayRiskStore(store._db)  # noqa: SLF001


# --------------------------------------------------------------------------------------
# Task 1: the day row and its base
# --------------------------------------------------------------------------------------
def test_open_day_then_get_day_round_trips_decimal_and_utc_times(store: PgDayRiskStore) -> None:
    state = make_state(equity="1000.123456789012345678")

    stored = store.open_day(state)

    assert stored == state
    assert store.get_day(DAY) == state
    got = store.get_day(DAY)
    assert got is not None
    assert got.equity_at_day_start == D("1000.123456789012345678")
    assert got.base_observed_at_utc == BASE_AT
    assert got.base_observed_at_utc.utcoffset() == timedelta(0)


def test_a_second_open_returns_the_stored_row_and_keeps_the_base(store: PgDayRiskStore) -> None:
    first = make_state(equity="1000")
    store.open_day(first)

    again = store.open_day(make_state(equity="900", base_at=T1))

    assert again.equity_at_day_start == D("1000")
    assert again.base_observed_at_utc == BASE_AT
    assert store.get_day(DAY) == first


def test_a_new_store_instance_keeps_the_same_row(store: PgDayRiskStore) -> None:
    store.open_day(make_state(equity="1000"))

    restarted = _restarted(store)

    got = restarted.get_day(DAY)
    assert got is not None
    assert got.equity_at_day_start == D("1000")
    # A restart that reads a different base still gets the stored one.
    assert restarted.open_day(make_state(equity="900")).equity_at_day_start == D("1000")


def test_has_day_and_get_day_of_an_absent_day(store: PgDayRiskStore) -> None:
    store.open_day(make_state())

    assert store.has_day(DAY) is True
    assert store.has_day(PREVIOUS_DAY) is False
    assert store.get_day(PREVIOUS_DAY) is None


def test_has_earlier_day_is_true_for_any_stored_day_before_and_false_otherwise(
    store: PgDayRiskStore,
) -> None:
    # WR-08: a gap of several days still has an earlier row; a later or equal day does not count.
    assert store.has_earlier_day(DAY) is False
    gap_day = PREVIOUS_DAY - timedelta(days=3)
    store.open_day(make_state(utc_day=gap_day, base_at=BASE_AT - timedelta(days=4)))
    assert store.has_earlier_day(DAY) is True
    assert store.has_earlier_day(gap_day) is False
    assert store.has_earlier_day(PREVIOUS_DAY - timedelta(days=4)) is False


def test_more_than_18_fractional_digits_raise_precision_error_before_any_write(
    store: PgDayRiskStore, engine: Engine
) -> None:
    with pytest.raises(PrecisionError):
        store.open_day(make_state(equity="1000.1234567890123456789"))

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM daily_risk_days")).scalar_one() == 0


def test_the_database_refuses_a_non_positive_base_that_bypasses_the_domain(
    engine: Engine,
) -> None:
    with expect_db_error("23514") as info, engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO daily_risk_days (utc_day, equity_at_day_start, base_observed_at_utc) "
                "VALUES ('2026-10-23', 0, :t)"
            ),
            {"t": BASE_AT},
        )
    assert info.constraint == "ck_daily_risk_days_equity_positive"


# --------------------------------------------------------------------------------------
# Task 2: components
# --------------------------------------------------------------------------------------
def test_add_components_is_idempotent_and_lists_in_key_order(store: PgDayRiskStore) -> None:
    c1 = make_component(kind=ComponentKind.FILL_PNL, source_key="BTCUSDT:1:1")
    c2 = make_component(kind=ComponentKind.FILL_COMMISSION, source_key="BTCUSDT:1:1", amount="-0.4")

    assert store.add_components([c2, c1]) == 2
    assert store.add_components([c1, c2]) == 0

    # Ordered by (kind, source, source_key): FILL_COMMISSION sorts before FILL_PNL.
    assert store.list_components(DAY) == (c2, c1)


def test_add_components_of_a_stored_key_with_another_amount_raises_and_stores_nothing_else(
    store: PgDayRiskStore,
) -> None:
    c1 = make_component(source_key="BTCUSDT:1:1", amount="-10")
    store.add_components([c1])
    fresh = make_component(source_key="BTCUSDT:2:2", amount="-3")
    clash = make_component(source_key="BTCUSDT:1:1", amount="-11")

    with pytest.raises(RowConflict) as excinfo:
        store.add_components([fresh, clash])

    assert "BTCUSDT:1:1" in str(excinfo.value)
    assert "-11" not in str(excinfo.value)
    assert store.list_components(DAY) == (c1,)


def test_add_components_of_a_stored_key_with_another_asset_raises(store: PgDayRiskStore) -> None:
    store.add_components([make_component(asset="USDT")])

    with pytest.raises(RowConflict):
        store.add_components([make_component(asset="BUSD")])

    (only,) = store.list_components(DAY)
    assert only.asset == "USDT"


def test_the_same_key_from_two_sources_is_two_rows(store: PgDayRiskStore) -> None:
    stream = make_component(source=ComponentSource.USER_DATA_EVENT, amount="-5")
    rest = make_component(source=ComponentSource.REST_USER_TRADES, amount="-5.5")

    assert store.add_components([stream, rest]) == 2
    assert len(store.list_components(DAY)) == 2


def test_components_of_two_days_are_listed_separately(store: PgDayRiskStore) -> None:
    today = make_component(source_key="BTCUSDT:1:1", event_time_utc=T1)
    yesterday = make_component(
        source_key="BTCUSDT:0:0", event_time_utc=datetime(2026, 10, 22, 23, 59, tzinfo=UTC)
    )

    store.add_components([today, yesterday])

    assert store.list_components(DAY) == (today,)
    assert store.list_components(PREVIOUS_DAY) == (yesterday,)


def test_a_component_amount_round_trips_exactly_and_too_many_digits_raise(
    store: PgDayRiskStore,
) -> None:
    exact = make_component(amount="-0.000000000000000001")
    store.add_components([exact])
    assert store.list_components(DAY)[0].amount == D("-0.000000000000000001")

    with pytest.raises(PrecisionError):
        store.add_components(
            [make_component(source_key="BTCUSDT:9:9", amount="-1.0000000000000000001")]
        )
    assert len(store.list_components(DAY)) == 1


def test_funding_components_round_trip(store: PgDayRiskStore) -> None:
    funding = make_component(
        kind=ComponentKind.FUNDING,
        source=ComponentSource.REST_INCOME,
        source_key="BTCUSDT:77",
        amount="-0.02",
    )

    store.add_components([funding])

    assert store.list_components(DAY) == (funding,)


# --------------------------------------------------------------------------------------
# Task 2: the one-time latch and warning stamps
# --------------------------------------------------------------------------------------
def test_latch_stop_is_set_once_and_survives_a_restart(store: PgDayRiskStore) -> None:
    store.open_day(make_state())

    first = store.latch_stop(utc_day=DAY, at_utc=T1)
    second = store.latch_stop(utc_day=DAY, at_utc=T2)

    assert first.stop_latched_at_utc == T1
    assert second.stop_latched_at_utc == T1
    got = _restarted(store).get_day(DAY)
    assert got is not None
    assert got.stop_latched_at_utc == T1
    assert got.equity_at_day_start == D("1000")


def test_mark_warning_alerted_is_set_once_and_survives_a_restart(store: PgDayRiskStore) -> None:
    store.open_day(make_state())

    first = store.mark_warning_alerted(utc_day=DAY, at_utc=T1)
    second = store.mark_warning_alerted(utc_day=DAY, at_utc=T2)

    assert first.warning_alerted_at_utc == T1
    assert second.warning_alerted_at_utc == T1
    got = _restarted(store).get_day(DAY)
    assert got is not None
    assert got.warning_alerted_at_utc == T1
    assert got.stop_latched_at_utc is None


def test_a_second_open_does_not_clear_a_latch(store: PgDayRiskStore) -> None:
    store.open_day(make_state())
    store.latch_stop(utc_day=DAY, at_utc=T1)

    again = store.open_day(make_state())

    assert again.stop_latched_at_utc == T1


def test_stamping_an_absent_day_raises_row_conflict(store: PgDayRiskStore) -> None:
    with pytest.raises(RowConflict):
        store.latch_stop(utc_day=DAY, at_utc=T1)
    with pytest.raises(RowConflict):
        store.mark_warning_alerted(utc_day=DAY, at_utc=T1)


def test_a_stamp_outside_the_day_or_naive_is_refused_and_nothing_is_written(
    store: PgDayRiskStore,
) -> None:
    store.open_day(make_state())

    with pytest.raises(ValueError, match="outside UTC day"):
        store.latch_stop(utc_day=DAY, at_utc=datetime(2026, 10, 24, 0, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="UTC-aware"):
        store.latch_stop(utc_day=DAY, at_utc=datetime(2026, 10, 23, 9, 0))

    got = store.get_day(DAY)
    assert got is not None
    assert got.stop_latched_at_utc is None


# --------------------------------------------------------------------------------------
# Task 2: the day-row lock
# --------------------------------------------------------------------------------------
def test_lock_day_of_an_absent_day_is_none(store: PgDayRiskStore) -> None:
    with store._db.transaction() as session:  # noqa: SLF001
        assert store.lock_day(session, DAY) is None


def test_lock_day_blocks_a_second_connection_until_the_first_commits(
    store: PgDayRiskStore,
) -> None:
    store.open_day(make_state())
    holder_has_lock = threading.Event()
    release_holder = threading.Event()
    waiter_got_lock = threading.Event()
    errors: list[BaseException] = []

    def holder() -> None:
        try:
            with store._db.transaction() as session:  # noqa: SLF001
                assert store.lock_day(session, DAY) is not None
                holder_has_lock.set()
                assert release_holder.wait(timeout=10)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the main thread
            errors.append(exc)

    def waiter() -> None:
        try:
            with store._db.transaction() as session:  # noqa: SLF001
                assert store.lock_day(session, DAY) is not None
                waiter_got_lock.set()
        except BaseException as exc:  # noqa: BLE001 - surfaced by the main thread
            errors.append(exc)

    holder_thread = threading.Thread(target=holder)
    waiter_thread = threading.Thread(target=waiter)
    holder_thread.start()
    assert holder_has_lock.wait(timeout=10)
    waiter_thread.start()

    # The waiter must stay blocked while the holder's transaction is open.
    assert not waiter_got_lock.wait(timeout=0.7)
    release_holder.set()
    holder_thread.join(timeout=10)
    waiter_thread.join(timeout=10)

    assert errors == []
    assert waiter_got_lock.is_set()


# --------------------------------------------------------------------------------------
# Task 2: failure and surface
# --------------------------------------------------------------------------------------
def test_an_unreachable_database_raises_store_unavailable() -> None:
    engine = create_engine(UNREACHABLE_URL, connect_args={"connect_timeout": 2})
    try:
        store = PgDayRiskStore(OperationalDatabase(engine))
        with pytest.raises(StoreUnavailable):
            store.get_day(DAY)
    finally:
        engine.dispose()


def test_the_store_has_no_delete_or_purge_method() -> None:
    names = [name for name in dir(PgDayRiskStore) if not name.startswith("__")]

    assert [n for n in names if n.lstrip("_").startswith(("delete", "purge", "remove"))] == []
    assert {
        "get_day",
        "has_day",
        "has_earlier_day",
        "open_day",
        "latch_stop",
        "mark_warning_alerted",
        "add_components",
        "list_components",
        "lock_day",
    } <= set(names)


def test_the_database_refuses_an_unknown_kind_and_an_empty_source_key(engine: Engine) -> None:
    insert = (
        "INSERT INTO daily_loss_components (utc_day, kind, source, source_key, amount, asset, "
        "event_time_utc) VALUES ('2026-10-23', :kind, 'USER_DATA_EVENT', :key, -1, 'USDT', :t)"
    )
    with expect_db_error("23514") as info, engine.begin() as conn:
        conn.execute(text(insert), {"kind": "BOGUS", "key": "k", "t": T1})
    assert info.constraint == "ck_daily_loss_components_kind"
    with expect_db_error("23514") as info, engine.begin() as conn:
        conn.execute(text(insert), {"kind": "FILL_PNL", "key": "", "t": T1})
    assert info.constraint == "ck_daily_loss_components_source_key"
