"""The margin trio of a reservation and the claims reader, on PostgreSQL (Phase 22, plan 22-08).

Each test runs on a generated `t17_<hex>_test` clone built by `alembic upgrade head`. A
reservation row carries the initial margin its plan needs (`required_margin`, written at plan
issue) together with the price and the leverage it was computed at; `list_margin_claims` returns
one `MarginClaim` per RESERVED or PLACED row, rebuilt from the table on every call (D-14,
amendment A2). A row without a stored margin reads as an UNKNOWN margin (None), never zero.
Expected values are literals derived by hand in the comments.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult
from src.persistence.day_risk import PgDayRiskStore
from src.persistence.engine import make_sync_engine
from src.persistence.errors import PrecisionError, RowConflict
from src.persistence.risk_reservations import PgRiskReservationStore
from src.persistence.uow import OperationalDatabase
from src.risk.daily_loss import DayRiskState
from src.risk.margin_check import MarginClaim
from src.risk.reservations import (
    ReleaseReason,
    ReservationRequest,
    ReservationStatus,
    margin_for_reservation,
)

from tests.support.pg_rows import (
    hexid,
    insert_and_commit,
    make_approval,
    make_plan,
    make_signal,
)

D = Decimal
NOW = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 24, 11, 0, tzinfo=UTC)
BASE_AT = datetime(2026, 10, 24, 0, 5, tzinfo=UTC)
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

# 0.01 x 80000 / 5 = 160.
MARGIN_160: dict[str, Any] = {
    "required_margin": D("160"),
    "margin_entry_price": D("80000"),
    "margin_leverage": 5,
}
# 0.1 x 3000 / 10 = 30.
MARGIN_30: dict[str, Any] = {
    "required_margin": D("30"),
    "margin_entry_price": D("3000"),
    "margin_leverage": 10,
}


def request(
    *,
    plan_id: str = P1,
    plan_hash: str = HASH_1,
    symbol: str = "BTCUSDT",
    side: str = "LONG",
    quantity: str = "0.01",
    risk: str = "1",
    **margin: Any,
) -> ReservationRequest:
    return ReservationRequest(
        trade_plan_id=plan_id,
        plan_hash=plan_hash,
        symbol=symbol,
        position_side=side,
        quantity=D(quantity),
        realized_risk=D(risk),
        **margin,
    )


def decided(approval_id: str = A1, plan_id: str = P1) -> Approval:
    return Approval(
        approval_id=approval_id,
        trade_plan_id=plan_id,
        signal_id=hexid(1),
        action=ApprovalAction.APPROVE,
        result=ApprovalResult.APPROVED,
        status=ApprovalResult.APPROVED,
        approval_token_hash=hexid(0x3000),
        requested_at_utc=NOW,
        acted_at_utc=NOW,
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


def open_today(db: OperationalDatabase) -> None:
    PgDayRiskStore(db).open_day(
        DayRiskState(utc_day=DAY, equity_at_day_start=D("1000"), base_observed_at_utc=BASE_AT)
    )


def reserve(db: OperationalDatabase, store: PgRiskReservationStore, approval: Approval) -> None:
    with db.transaction() as session:
        store.reserve_in(
            session,
            approval=approval,
            now_utc=NOW,
            daily_loss_quote=D("0"),
            parameter_set=RATES,
        )


# --------------------------------------------------------------------------------------
# Task 1: the trio is stored, compared and read back as claims
# --------------------------------------------------------------------------------------
def test_a_reserved_plan_with_a_margin_is_a_claim_and_a_new_store_instance_rebuilds_it(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(**MARGIN_160), now_utc=NOW)
    reserve(db, store, decided())

    expected = (MarginClaim(P1, ReservationStatus.RESERVED, D("160"), None),)
    assert store.list_margin_claims() == expected
    # A restart builds a new store over the same database: nothing is kept in memory.
    assert PgRiskReservationStore(db).list_margin_claims() == expected


def test_a_registered_but_not_yet_reserved_plan_is_not_a_claim(
    store: PgRiskReservationStore,
) -> None:
    store.register_request(request(**MARGIN_160), now_utc=NOW)

    assert store.list_margin_claims() == ()


def test_a_legacy_form_request_reads_as_an_unknown_margin_never_zero(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(), now_utc=NOW)
    reserve(db, store, decided())

    claims = store.list_margin_claims()

    assert claims == (MarginClaim(P1, ReservationStatus.RESERVED, None, None),)
    assert claims[0].required_margin is None


def test_the_claims_are_sorted_by_symbol_side_and_plan_id(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    # BTCUSDT (P2) sorts before ETHUSDT (P1) although P1 was registered first.
    # Risk 1 + 1 = 2 <= cluster cap 6, two positions <= 2.
    open_today(db)
    store.register_request(
        request(plan_id=P1, symbol="ETHUSDT", quantity="0.1", **MARGIN_30), now_utc=NOW
    )
    store.register_request(
        request(plan_id=P2, plan_hash=HASH_2, symbol="BTCUSDT", **MARGIN_160), now_utc=NOW
    )
    reserve(db, store, decided(A1, P1))
    reserve(db, store, decided(A2, P2))

    assert store.list_margin_claims() == (
        MarginClaim(P2, ReservationStatus.RESERVED, D("160"), None),
        MarginClaim(P1, ReservationStatus.RESERVED, D("30"), None),
    )


def test_registering_the_same_trio_again_is_a_no_op(store: PgRiskReservationStore) -> None:
    first = store.register_request(request(**MARGIN_160), now_utc=NOW)

    again = store.register_request(request(**MARGIN_160), now_utc=LATER)

    assert again == first
    assert again.requested_at_utc == NOW


@pytest.mark.parametrize(
    "changed",
    [
        # Each change keeps required_margin = quantity x price / leverage (0.01 x ...), because a
        # request with another amount is refused at construction (22-REVIEW WR-07).
        {"margin_entry_price": D("80001"), "required_margin": D("160.002")},
        {"margin_leverage": 4, "required_margin": D("200")},
        {"margin_leverage": 4, "margin_entry_price": D("80001"), "required_margin": D("200.0025")},
    ],
)
def test_the_same_plan_with_another_margin_is_a_row_conflict(
    store: PgRiskReservationStore, changed: dict[str, Any]
) -> None:
    store.register_request(request(**MARGIN_160), now_utc=NOW)

    with pytest.raises(RowConflict):
        store.register_request(request(**{**MARGIN_160, **changed}), now_utc=NOW)


def test_a_request_with_an_understated_margin_is_refused_before_anything_is_written(
    store: PgRiskReservationStore,
) -> None:
    with pytest.raises(ValueError, match="required_margin must equal"):
        request(**{**MARGIN_160, "required_margin": D("0.000001")})

    assert store.get(P1) is None


def test_a_stored_margin_that_differs_from_the_derived_one_reads_as_an_unknown_claim(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    """WR-07: the reader derives quantity x price / leverage and does not trust the column."""
    from sqlalchemy import update
    from src.db.models import RiskReservationRow

    open_today(db)
    store.register_request(request(**MARGIN_160), now_utc=NOW)
    reserve(db, store, decided())
    assert store.list_margin_claims() == (
        MarginClaim(P1, ReservationStatus.RESERVED, D("160"), None),
    )

    with db.transaction() as session:
        session.execute(
            update(RiskReservationRow)
            .where(RiskReservationRow.trade_plan_id == P1)
            .values(required_margin=D("0.000001"))
        )

    (claim,) = store.list_margin_claims()
    assert claim.required_margin is None  # unknown, never the understated figure
    assert claim.status is ReservationStatus.RESERVED


def test_a_margin_on_a_stored_legacy_row_is_a_row_conflict(
    store: PgRiskReservationStore,
) -> None:
    store.register_request(request(), now_utc=NOW)

    with pytest.raises(RowConflict):
        store.register_request(request(**MARGIN_160), now_utc=NOW)


def test_dropping_the_margin_of_a_stored_row_is_a_row_conflict(
    store: PgRiskReservationStore,
) -> None:
    store.register_request(request(**MARGIN_160), now_utc=NOW)

    with pytest.raises(RowConflict):
        store.register_request(request(), now_utc=NOW)


def test_an_amount_with_more_than_eighteen_fractional_digits_writes_nothing(
    store: PgRiskReservationStore,
) -> None:
    # required_margin is always rounded UP to 18 digits by margin_for_reservation, so only the
    # entry price can carry a digit the NUMERIC(38, 18) column would round.
    too_fine = D("80000." + "0" * 18 + "1")  # 19 fractional digits, the last one is 1
    assert too_fine.as_tuple().exponent == -19
    required = margin_for_reservation(quantity=D("0.01"), price=too_fine, leverage=5)

    with pytest.raises(PrecisionError):
        store.register_request(
            request(required_margin=required, margin_entry_price=too_fine, margin_leverage=5),
            now_utc=NOW,
        )

    assert store.get(P1) is None


# --------------------------------------------------------------------------------------
# Task 2: which rows are claims, and what another connection sees
# --------------------------------------------------------------------------------------
def test_a_placed_plan_stays_a_claim_with_its_placed_time(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(**MARGIN_160), now_utc=NOW)
    reserve(db, store, decided())

    store.mark_placed(P1, now_utc=LATER)

    assert store.list_margin_claims() == (
        MarginClaim(P1, ReservationStatus.PLACED, D("160"), LATER),
    )


def test_an_open_plan_is_not_a_claim(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(**MARGIN_160), now_utc=NOW)
    reserve(db, store, decided())
    store.mark_placed(P1, now_utc=LATER)

    store.mark_open(P1, now_utc=LATER)

    assert store.list_margin_claims() == ()


def test_a_released_plan_is_no_longer_a_claim(
    db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(**MARGIN_160), now_utc=NOW)
    reserve(db, store, decided())
    assert len(store.list_margin_claims()) == 1

    store.release(P1, reason=ReleaseReason.PLACEMENT_REFUSED, now_utc=LATER)

    assert store.list_margin_claims() == ()


def test_a_claim_is_visible_to_another_connection_only_once_it_is_committed(
    pg_db: str, db: OperationalDatabase, store: PgRiskReservationStore
) -> None:
    open_today(db)
    store.register_request(request(**MARGIN_160), now_utc=NOW)
    other_engine = make_sync_engine(pg_db)
    try:
        reader = PgRiskReservationStore(OperationalDatabase(other_engine))
        with db.transaction() as session:
            store.reserve_in(
                session,
                approval=decided(),
                now_utc=NOW,
                daily_loss_quote=D("0"),
                parameter_set=RATES,
            )
            # The writer sees its own uncommitted claim; the other connection does not (READ
            # COMMITTED).
            assert len(store.list_margin_claims(tx=session)) == 1
            assert reader.list_margin_claims() == ()
        # Committed: the next reader sees the claim with its margin.
        assert reader.list_margin_claims() == (
            MarginClaim(P1, ReservationStatus.RESERVED, D("160"), None),
        )
    finally:
        other_engine.dispose()
