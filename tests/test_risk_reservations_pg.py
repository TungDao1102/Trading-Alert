"""PgRiskReservationStore against a real PostgreSQL server (Phase 21, plan 21-12; D-16, D-17).

Each test runs on a generated `t17_<hex>_test` clone built by `alembic upgrade head`. One row of
`risk_reservations` holds the reservation of a trade plan for its whole life. `reserve_in` runs
the shared cap gate under the lock of today's `daily_risk_days` row, inside the caller's
transaction; the transitions follow `RELEASE_SOURCE_STATUSES`. Expected values are literals
derived by hand in the comments.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason
from src.persistence import risk_reservations as store_module
from src.persistence.day_risk import PgDayRiskStore
from src.persistence.engine import make_sync_engine
from src.persistence.errors import ParentRowMissing, PrecisionError, RowConflict
from src.persistence.risk_reservations import (
    PgRiskReservationStore,
    ReservationRecord,
    ReservationRefused,
)
from src.persistence.uow import OperationalDatabase
from src.risk import reservations as risk_module
from src.risk.daily_loss import DayRiskState
from src.risk.reservations import (
    RELEASE_SOURCE_STATUSES,
    CountedReservation,
    ReleaseReason,
    ReservationRequest,
    ReservationStatus,
)

from tests.support.pg_rows import (
    expect_db_error,
    hexid,
    insert_and_commit,
    make_approval,
    make_plan,
    make_signal,
)

D = Decimal
ZERO = D("0")
NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
BASE_AT = datetime(2026, 10, 23, 0, 5, tzinfo=UTC)
DAY = NOW.date()
HASH_1 = "a" * 64
HASH_2 = "b" * 64
P1 = hexid(0x1001)
P2 = hexid(0x1002)
A1 = hexid(0x2001)
A2 = hexid(0x2002)

# Registry RATES on a day-start base of 1000: cluster cap 6, aggregate cap 10, warning 5, stop 10.
RATES: dict[str, Any] = {
    "max_open_positions": 2,
    "max_aggregate_open_risk": D("0.01"),
    "cluster_cap": D("0.006"),
    "daily_loss_warning_threshold": D("0.005"),
    "daily_loss_stop_threshold": D("0.01"),
}

_LOCK_NOT_AVAILABLE = "55P03"


def request(
    *,
    plan_id: str = P1,
    plan_hash: str = HASH_1,
    symbol: str = "BTCUSDT",
    side: str = "LONG",
    quantity: str = "0.001",
    risk: str = "4",
) -> ReservationRequest:
    return ReservationRequest(
        trade_plan_id=plan_id,
        plan_hash=plan_hash,
        symbol=symbol,
        position_side=side,
        quantity=D(quantity),
        realized_risk=D(risk),
    )


def decided(approval_id: str = A1, plan_id: str = P1, *, at: datetime = NOW) -> Approval:
    """An approval decided APPROVED at `at` (the callback time)."""
    return Approval(
        approval_id=approval_id,
        trade_plan_id=plan_id,
        signal_id=hexid(1),
        action=ApprovalAction.APPROVE,
        result=ApprovalResult.APPROVED,
        status=ApprovalResult.APPROVED,
        approval_token_hash=hexid(0x3000),
        requested_at_utc=NOW,
        acted_at_utc=at,
        actor_id="operator",
        request_hash="e" * 64,
    )


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        insert_and_commit(
            eng,
            make_signal(1),
            make_plan(1, 1, plan_hash=HASH_1),
            make_plan(2, 1, plan_hash=HASH_2),
            make_approval(1, 1, 1),
            make_approval(2, 2, 1),
        )
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def db(engine: Engine) -> OperationalDatabase:
    return OperationalDatabase(engine)


@pytest.fixture
def store(db: OperationalDatabase) -> PgRiskReservationStore:
    return PgRiskReservationStore(db)


def open_today(db: OperationalDatabase, *, latched: bool = False) -> None:
    days = PgDayRiskStore(db)
    days.open_day(
        DayRiskState(utc_day=DAY, equity_at_day_start=D("1000"), base_observed_at_utc=BASE_AT)
    )
    if latched:
        days.latch_stop(utc_day=DAY, at_utc=NOW)


def reserve(
    db: OperationalDatabase,
    store: PgRiskReservationStore,
    approval: Approval,
    *,
    daily_loss: Decimal | None = ZERO,
    rates: dict[str, Any] | None = None,
    at: datetime = NOW,
) -> ReservationRecord:
    """One approval transaction: reserve_in, then commit (a refusal rolls it back)."""
    with db.transaction() as session:
        return store.reserve_in(
            session,
            approval=approval,
            now_utc=at,
            daily_loss_quote=daily_loss,
            parameter_set=RATES if rates is None else rates,
        )


def counted(plan_id: str, symbol: str, side: str, status: ReservationStatus, risk: str, h: str):
    return CountedReservation(
        trade_plan_id=plan_id,
        plan_hash=h,
        symbol=symbol,
        position_side=side,
        status=status,
        open_risk=D(risk),
    )


# --------------------------------------------------------------------------------------
# Task 1: register_request and reserve_in
# --------------------------------------------------------------------------------------
def test_a_registered_request_is_requested_and_not_counted(
    store: PgRiskReservationStore,
) -> None:
    record = store.register_request(request(), now_utc=NOW)

    assert record.status is ReservationStatus.REQUESTED
    assert record.approval_id is None
    assert record.release_reason is None
    assert record.requested_at_utc == NOW
    assert store.get(P1) == record
    assert store.list_counted() == ()


def test_reserve_in_counts_the_plan_and_a_new_store_instance_rebuilds_it(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(), now_utc=NOW)

    record = reserve(db, store, decided())

    assert record.status is ReservationStatus.RESERVED
    assert record.approval_id == A1
    assert record.reserved_at_utc == NOW
    stored = store.get(P1)
    assert stored is not None
    assert stored.status is ReservationStatus.RESERVED
    assert stored.approval_id == A1
    assert stored.reserved_at_utc == NOW
    expected = (counted(P1, "BTCUSDT", "LONG", ReservationStatus.RESERVED, "4", HASH_1),)
    assert store.list_counted() == expected
    # A restart builds a new store over the same database: nothing is kept in memory.
    assert PgRiskReservationStore(store._db).list_counted() == expected  # noqa: SLF001
    assert PgRiskReservationStore(store._db).get(P1) == stored  # noqa: SLF001


def test_reserve_in_twice_is_a_no_op(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(), now_utc=NOW)
    first = reserve(db, store, decided())

    again = reserve(db, store, decided(), at=LATER)

    assert again == first
    assert again.reserved_at_utc == NOW


def test_a_second_plan_over_the_cluster_cap_is_refused_and_stays_requested(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    # Cluster cap 6; P1 reserves 4; P2 asks 2.5 on the same direction: 4 + 2.5 = 6.5 > 6.
    open_today(db)
    store.register_request(request(), now_utc=NOW)
    store.register_request(
        request(plan_id=P2, plan_hash=HASH_2, symbol="ETHUSDT", risk="2.5"), now_utc=NOW
    )
    reserve(db, store, decided())

    with pytest.raises(ReservationRefused) as raised:
        reserve(db, store, decided(A2, P2))

    assert raised.value.reason_code is RejectionReason.CLUSTER_CAP_REJECT
    assert str(raised.value) == "CLUSTER_CAP_REJECT"
    p2 = store.get(P2)
    assert p2 is not None
    assert p2.status is ReservationStatus.REQUESTED
    assert p2.approval_id is None
    assert [row.trade_plan_id for row in store.list_counted()] == [P1]


def test_a_plan_that_fits_is_reserved_next_to_another(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    # 4 + 1.5 = 5.5 <= 6 and two positions <= 2.
    open_today(db)
    store.register_request(request(), now_utc=NOW)
    store.register_request(
        request(plan_id=P2, plan_hash=HASH_2, symbol="ETHUSDT", risk="1.5"), now_utc=NOW
    )
    reserve(db, store, decided())

    reserve(db, store, decided(A2, P2))

    assert [(r.trade_plan_id, r.open_risk) for r in store.list_counted()] == [
        (P1, D("4")),
        (P2, D("1.5")),
    ]


def test_the_caller_owns_the_transaction_a_rollback_leaves_the_plan_requested(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(), now_utc=NOW)

    class Abort(Exception):
        pass

    with pytest.raises(Abort), db.transaction() as session:
        store.reserve_in(
            session,
            approval=decided(),
            now_utc=NOW,
            daily_loss_quote=D("0"),
            parameter_set=RATES,
        )
        assert store.get(P1, tx=session).status is ReservationStatus.RESERVED  # type: ignore[union-attr]
        raise Abort

    stored = store.get(P1)
    assert stored is not None
    assert stored.status is ReservationStatus.REQUESTED
    assert store.list_counted() == ()


def test_reserve_in_holds_the_day_row_lock_until_the_caller_ends_the_transaction(
    engine: Engine, db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(), now_utc=NOW)

    with db.transaction() as session:
        store.reserve_in(
            session,
            approval=decided(),
            now_utc=NOW,
            daily_loss_quote=D("0"),
            parameter_set=RATES,
        )
        with expect_db_error(_LOCK_NOT_AVAILABLE), engine.connect() as other:
            other.execute(
                text("SELECT 1 FROM daily_risk_days WHERE utc_day = :d FOR UPDATE NOWAIT"),
                {"d": DAY},
            )
    # The caller committed: the lock is free again.
    with engine.connect() as other:
        other.execute(
            text("SELECT 1 FROM daily_risk_days WHERE utc_day = :d FOR UPDATE NOWAIT"),
            {"d": DAY},
        )


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("no_day_row", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
        ("latched", RejectionReason.DAILY_STOP_BLOCK),
        ("daily_loss_unknown", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
        ("loss_at_the_stop", RejectionReason.DAILY_STOP_BLOCK),
        ("bad_thresholds", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
        ("not_approved", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
        ("no_request_row", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
        ("already_placed", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
    ],
)
def test_reserve_in_fails_closed_and_changes_nothing(
    db: OperationalDatabase,
    store: PgRiskReservationStore,
    engine: Engine,
    case: str,
    reason: RejectionReason,
) -> None:
    approval = decided()
    daily_loss: Decimal | None = D("0")
    rates = RATES
    if case != "no_day_row":
        open_today(db, latched=case == "latched")
    if case != "no_request_row":
        store.register_request(request(), now_utc=NOW)
    if case == "daily_loss_unknown":
        daily_loss = None
    if case == "loss_at_the_stop":
        daily_loss = D("10")
    if case == "bad_thresholds":
        rates = {key: value for key, value in RATES.items() if key != "cluster_cap"}
    if case == "not_approved":
        approval = Approval(
            approval_id=A1,
            trade_plan_id=P1,
            signal_id=hexid(1),
            action=ApprovalAction.SKIP_USER,
            result=ApprovalResult.SKIPPED,
            status=ApprovalResult.SKIPPED,
            approval_token_hash=hexid(0x3000),
            requested_at_utc=NOW,
            acted_at_utc=NOW,
        )
    if case == "already_placed":
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE risk_reservations SET status = 'PLACED', approval_id = :a "
                    "WHERE trade_plan_id = :p"
                ),
                {"a": A2, "p": P1},
            )
    before = store.get(P1)

    with pytest.raises(ReservationRefused) as raised:
        reserve(db, store, approval, daily_loss=daily_loss, rates=rates)

    assert raised.value.reason_code is reason
    assert store.get(P1) == before


def test_register_request_twice_with_the_same_identity_is_a_no_op(
    store: PgRiskReservationStore,
) -> None:
    first = store.register_request(request(), now_utc=NOW)

    again = store.register_request(request(), now_utc=LATER)

    assert again == first
    assert again.requested_at_utc == NOW


@pytest.mark.parametrize(
    "other",
    [
        {"risk": "5"},
        {"quantity": "0.002"},
        {"symbol": "ETHUSDT"},
        {"side": "SHORT"},
        {"plan_hash": HASH_2},
    ],
)
def test_register_request_with_another_identity_is_a_row_conflict(
    store: PgRiskReservationStore, other: dict[str, str]
) -> None:
    store.register_request(request(), now_utc=NOW)

    with pytest.raises(RowConflict):
        store.register_request(request(**other), now_utc=NOW)

    assert store.get(P1) is not None


def test_register_request_for_an_unknown_plan_is_parent_row_missing(
    store: PgRiskReservationStore,
) -> None:
    with pytest.raises(ParentRowMissing):
        store.register_request(request(plan_id=hexid(0x1999)), now_utc=NOW)

    assert store.get(hexid(0x1999)) is None


def test_an_amount_with_19_fractional_digits_raises_precision_error_before_any_write(
    store: PgRiskReservationStore,
) -> None:
    with pytest.raises(PrecisionError):
        store.register_request(request(risk="4.0000000000000000001"), now_utc=NOW)
    with pytest.raises(PrecisionError):
        store.register_request(request(quantity="0.0000000000000000001"), now_utc=NOW)

    assert store.get(P1) is None


def test_a_naive_time_is_refused(store: PgRiskReservationStore) -> None:
    with pytest.raises(ValueError, match="UTC"):
        store.register_request(request(), now_utc=datetime(2026, 10, 23, 10, 0))  # noqa: DTZ001


def test_the_store_has_no_delete_path() -> None:
    names = {name for name in dir(PgRiskReservationStore) if not name.startswith("_")}
    assert names == {
        "get",
        "list_counted",
        "register_request",
        "reserve_in",
        "mark_placed",
        "mark_open",
        "release",
    }


# --------------------------------------------------------------------------------------
# Task 2: lifecycle transitions
# --------------------------------------------------------------------------------------
S = ReservationStatus
R = ReleaseReason

#: The plan's table, written out by hand so a change of the mapping in the risk module fails here.
EXPECTED_SOURCES: dict[ReleaseReason, frozenset[ReservationStatus]] = {
    R.APPROVAL_SKIPPED: frozenset({S.REQUESTED}),
    R.APPROVAL_EXPIRED: frozenset({S.REQUESTED}),
    R.PLAN_EXPIRED: frozenset({S.REQUESTED, S.RESERVED}),
    R.PLAN_INVALIDATED: frozenset({S.REQUESTED, S.RESERVED}),
    R.PLAN_SUPERSEDED: frozenset({S.REQUESTED, S.RESERVED}),
    R.PLACEMENT_REFUSED: frozenset({S.RESERVED}),
    R.ENTRY_REJECTED: frozenset({S.RESERVED, S.PLACED}),
    R.ENTRY_ENDED_NO_FILL: frozenset({S.PLACED}),
    R.POSITION_CLOSED: frozenset({S.OPEN}),
}


def force_status(
    engine: Engine,
    plan_id: str,
    status: ReservationStatus,
    *,
    first_reason: ReleaseReason = R.APPROVAL_EXPIRED,
) -> None:
    """Put the stored row into `status` directly (the setup of a table cell)."""
    counted_status = status in (S.RESERVED, S.PLACED, S.OPEN)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE risk_reservations SET status = :s, approval_id = :a, "
                "release_reason = :r, released_at_utc = :ra, reserved_at_utc = NULL, "
                "placed_at_utc = NULL, opened_at_utc = NULL WHERE trade_plan_id = :p"
            ),
            {
                "s": status.value,
                "a": A1 if counted_status else None,
                "r": first_reason.value if status is S.RELEASED else None,
                "ra": NOW if status is S.RELEASED else None,
                "p": plan_id,
            },
        )


def test_the_expected_table_is_the_mapping_of_the_risk_module() -> None:
    assert dict(RELEASE_SOURCE_STATUSES) == EXPECTED_SOURCES
    assert set(EXPECTED_SOURCES) == set(ReleaseReason)
    # The store reads the mapping itself, not a copy of it.
    assert store_module.RELEASE_SOURCE_STATUSES is risk_module.RELEASE_SOURCE_STATUSES
    assert "RELEASE_SOURCE_STATUSES[reason]" in inspect.getsource(PgRiskReservationStore.release)


def test_mark_placed_then_mark_open_walk_the_lifecycle(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(), now_utc=NOW)
    reserve(db, store, decided())

    placed = store.mark_placed(P1, now_utc=LATER)
    assert placed.status is S.PLACED
    assert placed.placed_at_utc == LATER
    assert store.mark_placed(P1, now_utc=datetime(2026, 10, 23, 12, 0, tzinfo=UTC)) == placed

    opened = store.mark_open(P1, now_utc=datetime(2026, 10, 23, 12, 30, tzinfo=UTC))
    assert opened.status is S.OPEN
    assert opened.opened_at_utc == datetime(2026, 10, 23, 12, 30, tzinfo=UTC)
    assert opened.placed_at_utc == LATER
    assert store.mark_open(P1, now_utc=datetime(2026, 10, 23, 13, 0, tzinfo=UTC)) == opened
    assert [row.status for row in store.list_counted()] == [S.OPEN]


@pytest.mark.parametrize("status", [S.REQUESTED, S.OPEN, S.RELEASED])
def test_mark_placed_from_any_other_status_is_a_row_conflict(
    engine: Engine, store: PgRiskReservationStore, status: ReservationStatus
) -> None:
    store.register_request(request(), now_utc=NOW)
    force_status(engine, P1, status)

    with pytest.raises(RowConflict):
        store.mark_placed(P1, now_utc=LATER)

    stored = store.get(P1)
    assert stored is not None
    assert stored.status is status


@pytest.mark.parametrize("status", [S.REQUESTED, S.RESERVED, S.RELEASED])
def test_mark_open_from_any_other_status_is_a_row_conflict(
    engine: Engine, store: PgRiskReservationStore, status: ReservationStatus
) -> None:
    store.register_request(request(), now_utc=NOW)
    force_status(engine, P1, status)

    with pytest.raises(RowConflict):
        store.mark_open(P1, now_utc=LATER)

    stored = store.get(P1)
    assert stored is not None
    assert stored.status is status


def test_mark_placed_and_mark_open_of_an_absent_plan_are_row_conflicts(
    store: PgRiskReservationStore,
) -> None:
    with pytest.raises(RowConflict):
        store.mark_placed(P1, now_utc=NOW)
    with pytest.raises(RowConflict):
        store.mark_open(P1, now_utc=NOW)
    assert store.get(P1) is None


_CELLS = [(reason, status) for reason in ReleaseReason for status in ReservationStatus]


@pytest.mark.parametrize(("reason", "status"), _CELLS, ids=lambda v: v.value)
def test_release_follows_the_transition_table_cell_by_cell(
    engine: Engine,
    store: PgRiskReservationStore,
    reason: ReleaseReason,
    status: ReservationStatus,
) -> None:
    store.register_request(request(), now_utc=NOW)
    first_reason = R.PLAN_EXPIRED if reason is R.APPROVAL_EXPIRED else R.APPROVAL_EXPIRED
    force_status(engine, P1, status, first_reason=first_reason)
    before = store.get(P1)

    if status is S.RELEASED:
        # Already RELEASED (any reason): a no-op that keeps the first stored reason and time.
        record = store.release(P1, reason=reason, now_utc=LATER)
        assert record == before
        assert record.release_reason is first_reason
        assert record.released_at_utc == NOW
    elif status in EXPECTED_SOURCES[reason]:
        record = store.release(P1, reason=reason, now_utc=LATER)
        assert record.status is S.RELEASED
        assert record.release_reason is reason
        assert record.released_at_utc == LATER
        assert store.get(P1) == record
        # A released reservation can never be counted again.
        assert store.list_counted() == ()
        with pytest.raises(RowConflict):
            store.mark_placed(P1, now_utc=LATER)
        with pytest.raises(RowConflict):
            store.mark_open(P1, now_utc=LATER)
        assert store.get(P1) == record
    else:
        with pytest.raises(RowConflict) as raised:
            store.release(P1, reason=reason, now_utc=LATER)
        assert P1 in str(raised.value)
        assert reason.value in str(raised.value)
        assert status.value in str(raised.value)
        assert store.get(P1) == before


@pytest.mark.parametrize("reason", list(ReleaseReason), ids=lambda v: v.value)
def test_release_of_an_absent_plan_is_a_row_conflict(
    store: PgRiskReservationStore, reason: ReleaseReason
) -> None:
    with pytest.raises(RowConflict):
        store.release(P1, reason=reason, now_utc=NOW)

    assert store.get(P1) is None


def test_a_second_terminal_signal_keeps_the_first_reason_and_time(
    store: PgRiskReservationStore,
) -> None:
    store.register_request(request(), now_utc=NOW)
    first = store.release(P1, reason=R.APPROVAL_EXPIRED, now_utc=NOW)

    second = store.release(P1, reason=R.PLAN_EXPIRED, now_utc=LATER)

    assert second == first
    assert second.release_reason is R.APPROVAL_EXPIRED
    assert second.released_at_utc == NOW
    assert store.get(P1) == first


def test_a_released_reservation_frees_the_caps_for_another_plan(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    # P1 holds 4 of the cluster cap 6; P2 asks 2.5 and is refused until P1 is released.
    open_today(db)
    store.register_request(request(), now_utc=NOW)
    store.register_request(
        request(plan_id=P2, plan_hash=HASH_2, symbol="ETHUSDT", risk="2.5"), now_utc=NOW
    )
    reserve(db, store, decided())
    with pytest.raises(ReservationRefused):
        reserve(db, store, decided(A2, P2))

    store.release(P1, reason=R.PLAN_EXPIRED, now_utc=LATER)
    reserve(db, store, decided(A2, P2), at=LATER)

    assert [row.trade_plan_id for row in store.list_counted()] == [P2]
