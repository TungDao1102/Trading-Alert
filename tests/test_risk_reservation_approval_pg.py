"""The approval transaction reserves risk atomically (Phase 21, plan 21-15; D-16, D-17, F-407).

`make_reserving_save_atomic` decides the approval, then reserves the plan's risk under the lock
of today's `daily_risk_days` row, in ONE PostgreSQL transaction. Every test runs on a generated
`t17_<hex>_test` clone built by `alembic upgrade head`. Expected values are literals derived by
hand in the comments.

Cap arithmetic (day-start base 1000, registry RATES of `RATES`): cluster cap 6, aggregate cap
10, warning 5, stop 10. BNBUSDT is outside the cluster symbols, so two 5.5 plans meet the
aggregate cap alone: 5.5 + 5.5 = 11 > 10, while 5.5 <= 6 and 5.5 <= 10 each.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from src.adapters.telegram_callbacks import SaveAtomic
from src.approval.binding import ApprovalRejected, Callback
from src.approval.replay import ApprovalAlreadyDecided, resolve_callback
from src.approval.tokens import token_hash_of
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason
from src.persistence.approvals import PgApprovalStore
from src.persistence.day_risk import PgDayRiskStore
from src.persistence.engine import make_sync_engine
from src.persistence.errors import PersistenceError, StoreUnavailable
from src.persistence.risk_reservations import (
    APPROVAL_SERIALISATION_LOCK_KEY,
    PgRiskReservationStore,
    ReservationRefused,
    make_reserving_save_atomic,
)
from src.persistence.uow import OperationalDatabase
from src.risk.daily_loss import DayRiskState
from src.risk.reservations import ReleaseReason, ReservationRequest, ReservationStatus

from tests.support.pg_rows import (
    hexid,
    insert_and_commit,
    make_approval,
    make_plan,
    make_signal,
)

D = Decimal
ZERO = D("0")
NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
ACTED = datetime(2026, 10, 23, 10, 30, tzinfo=UTC)
BASE_AT = datetime(2026, 10, 23, 0, 5, tzinfo=UTC)
DAY = NOW.date()
HASH_1 = "a" * 64
HASH_2 = "b" * 64
P1 = hexid(0x1001)
P2 = hexid(0x1002)
A1 = hexid(0x2001)
A2 = hexid(0x2002)
A3 = hexid(0x2003)

RATES: dict[str, Any] = {
    "max_open_positions": 2,
    "max_aggregate_open_risk": D("0.01"),
    "cluster_cap": D("0.006"),
    "daily_loss_warning_threshold": D("0.005"),
    "daily_loss_stop_threshold": D("0.01"),
}


def _request(
    plan_id: str = P1,
    plan_hash: str = HASH_1,
    symbol: str = "BTCUSDT",
    side: str = "LONG",
    risk: str = "4",
) -> ReservationRequest:
    return ReservationRequest(
        trade_plan_id=plan_id,
        plan_hash=plan_hash,
        symbol=symbol,
        position_side=side,
        quantity=D("0.001"),
        realized_risk=D(risk),
    )


def _decision(
    approval_id: str = A1,
    plan_id: str = P1,
    *,
    action: ApprovalAction = ApprovalAction.APPROVE,
    status: ApprovalResult = ApprovalResult.APPROVED,
    token: int = 0x3001,
    acted_at: datetime = ACTED,
) -> Approval:
    return Approval(
        approval_id=approval_id,
        trade_plan_id=plan_id,
        signal_id=hexid(1),
        action=action,
        result=status,
        status=status,
        approval_token_hash=hexid(token),
        requested_at_utc=NOW,
        acted_at_utc=acted_at,
        actor_id="operator",
        request_hash="e" * 64,
    )


def _skip(approval_id: str = A1, plan_id: str = P1, *, action: ApprovalAction) -> Approval:
    return _decision(approval_id, plan_id, action=action, status=ApprovalResult.SKIPPED)


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
            make_approval(3, 1, 1),
        )
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def db(engine: Engine) -> OperationalDatabase:
    return OperationalDatabase(engine)


@pytest.fixture
def reservations(db: OperationalDatabase) -> PgRiskReservationStore:
    return PgRiskReservationStore(db)


@pytest.fixture
def approvals(db: OperationalDatabase) -> PgApprovalStore:
    return PgApprovalStore(db)


def _open_today(db: OperationalDatabase, *, latched: bool = False) -> None:
    days = PgDayRiskStore(db)
    days.open_day(
        DayRiskState(utc_day=DAY, equity_at_day_start=D("1000"), base_observed_at_utc=BASE_AT)
    )
    if latched:
        days.latch_stop(utc_day=DAY, at_utc=NOW)


def _composed(
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
    *,
    rates: dict[str, Any] | None = None,
    loss: Decimal | None = ZERO,
) -> SaveAtomic:
    return make_reserving_save_atomic(
        approvals=approvals,
        reservations=reservations,
        parameter_set=RATES if rates is None else rates,
        daily_loss_quote=lambda _day: loss,
    )


def _approval_status(engine: Engine, approval_id: str) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT status FROM approvals WHERE approval_id = :a"), {"a": approval_id}
            ).scalar_one()
        )


# --------------------------------------------------------------------------------------
# Task 1: the tracer
# --------------------------------------------------------------------------------------
def test_approve_decides_the_approval_and_reserves_the_risk_in_one_transaction(
    engine: Engine,
    db: OperationalDatabase,
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
) -> None:
    _open_today(db)
    reservations.register_request(_request(), now_utc=NOW)

    _composed(approvals, reservations)(_decision(), None)

    assert _approval_status(engine, A1) == "APPROVED"
    record = reservations.get(P1)
    assert record is not None
    assert record.status is ReservationStatus.RESERVED
    assert record.approval_id == A1
    assert record.reserved_at_utc == ACTED


def test_save_atomic_without_a_hook_behaves_as_before(
    engine: Engine, approvals: PgApprovalStore, reservations: PgRiskReservationStore
) -> None:
    reservations.register_request(_request(), now_utc=NOW)

    approvals.save_atomic(_decision(), None)

    assert _approval_status(engine, A1) == "APPROVED"
    record = reservations.get(P1)
    assert record is not None
    assert record.status is ReservationStatus.REQUESTED


def test_a_hook_that_raises_rolls_the_decision_back(
    engine: Engine, approvals: PgApprovalStore
) -> None:
    class Boom(Exception):
        pass

    def hook(_session: Any, _approval: Approval) -> None:
        raise Boom

    with pytest.raises(Boom):
        approvals.save_atomic(_decision(), None, after_decide=hook)

    assert _approval_status(engine, A1) == "PENDING"


# --------------------------------------------------------------------------------------
# Task 2: the two-connection race
# --------------------------------------------------------------------------------------
class _PausingStore(PgRiskReservationStore):
    """Holds the day-row lock after `reserve_in` until the other connection is waiting on it."""

    def __init__(
        self,
        db: OperationalDatabase,
        monitor: Engine,
        locked: threading.Event,
        second_started: threading.Event,
    ) -> None:
        super().__init__(db)
        self._monitor = monitor
        self._locked = locked
        self._second_started = second_started
        self.second_was_blocked = False

    def reserve_in(self, session: Any, **kwargs: Any) -> Any:
        record = super().reserve_in(session, **kwargs)
        self._locked.set()
        assert self._second_started.wait(timeout=30)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not self.second_was_blocked:
            with self._monitor.connect() as conn:
                waiting = conn.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                        "AND (query ILIKE '%daily_risk_days%' "
                        "OR query ILIKE '%pg_advisory_xact_lock%')"
                    )
                ).scalar_one()
            self.second_was_blocked = waiting >= 1
            if not self.second_was_blocked:
                time.sleep(0.05)
        return record


def _race(
    pg_db: str,
    engine: Engine,
    db: OperationalDatabase,
    *,
    second_acted_at: datetime,
) -> tuple[dict[str, object], list[_PausingStore], PgRiskReservationStore]:
    """Two approvals of 5.5 each against the 10 aggregate cap, the first holding its lock."""
    seed = PgRiskReservationStore(db)
    seed.register_request(
        _request(P1, HASH_1, symbol="BNBUSDT", side="LONG", risk="5.5"), now_utc=NOW
    )
    seed.register_request(
        _request(P2, HASH_2, symbol="BNBUSDT", side="SHORT", risk="5.5"), now_utc=NOW
    )
    locked = threading.Event()
    second_started = threading.Event()
    outcomes: dict[str, object] = {}
    pausing: list[_PausingStore] = []

    def first() -> None:
        eng = make_sync_engine(pg_db)
        try:
            thread_db = OperationalDatabase(eng)
            store = _PausingStore(thread_db, engine, locked, second_started)
            pausing.append(store)
            _composed_for(thread_db, store)(_decision(A1, P1), None)
            outcomes["first"] = "approved"
        except Exception as exc:  # reported through the assertions below
            outcomes["first"] = exc
        finally:
            eng.dispose()

    def second() -> None:
        eng = make_sync_engine(pg_db)
        try:
            assert locked.wait(timeout=30)
            thread_db = OperationalDatabase(eng)
            store = PgRiskReservationStore(thread_db)
            second_started.set()
            _composed_for(thread_db, store)(
                _decision(A2, P2, token=0x3002, acted_at=second_acted_at),
                None,
            )
            outcomes["second"] = "approved"
        except Exception as exc:  # reported through the assertions below
            outcomes["second"] = exc
        finally:
            eng.dispose()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)
    return outcomes, pausing, seed


def test_two_concurrent_approvals_that_only_one_fits_cannot_both_pass(
    pg_db: str, engine: Engine, db: OperationalDatabase
) -> None:
    _open_today(db)
    outcomes, pausing, seed = _race(pg_db, engine, db, second_acted_at=ACTED)

    assert outcomes["first"] == "approved"
    refused = outcomes["second"]
    assert isinstance(refused, ReservationRefused)
    assert refused.reason_code is RejectionReason.AGGREGATE_CAP_REJECT
    assert pausing[0].second_was_blocked is True
    assert _approval_status(engine, A1) == "APPROVED"
    assert _approval_status(engine, A2) == "PENDING"
    p1 = seed.get(P1)
    p2 = seed.get(P2)
    assert p1 is not None
    assert p2 is not None
    assert (p1.status, p1.approval_id) == (ReservationStatus.RESERVED, A1)
    assert (p2.status, p2.approval_id) == (ReservationStatus.REQUESTED, None)


def _composed_for(thread_db: OperationalDatabase, store: PgRiskReservationStore) -> SaveAtomic:
    return _composed(PgApprovalStore(thread_db), store)


# --------------------------------------------------------------------------------------
# Refusals roll the decision back
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("no_day_row", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
        ("no_request_row", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
        ("loss_unknown", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
        ("latched", RejectionReason.DAILY_STOP_BLOCK),
        ("missing_rate", RejectionReason.UNCERTAIN_ACCOUNT_STATE),
    ],
)
def test_every_refusal_leaves_the_approval_pending_and_the_request_untouched(
    engine: Engine,
    db: OperationalDatabase,
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
    case: str,
    reason: RejectionReason,
) -> None:
    rates = RATES
    loss: Decimal | None = ZERO
    if case != "no_day_row":
        _open_today(db, latched=case == "latched")
    if case != "no_request_row":
        reservations.register_request(_request(), now_utc=NOW)
    if case == "loss_unknown":
        loss = None
    if case == "missing_rate":
        rates = {key: value for key, value in RATES.items() if key != "cluster_cap"}
    before = reservations.get(P1)

    with pytest.raises(ReservationRefused) as raised:
        _composed(approvals, reservations, rates=rates, loss=loss)(_decision(), None)

    assert raised.value.reason_code is reason
    assert isinstance(raised.value, ApprovalRejected)
    assert _approval_status(engine, A1) == "PENDING"
    assert reservations.get(P1) == before
    if before is not None:
        assert before.status is ReservationStatus.REQUESTED


def test_a_failing_daily_loss_quote_approves_nothing(
    engine: Engine,
    db: OperationalDatabase,
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
) -> None:
    _open_today(db)
    reservations.register_request(_request(), now_utc=NOW)

    def unavailable(_day: object) -> Decimal | None:
        raise StoreUnavailable("PostgreSQL unavailable during transaction (OperationalError)")

    save = make_reserving_save_atomic(
        approvals=approvals,
        reservations=reservations,
        parameter_set=RATES,
        daily_loss_quote=unavailable,
    )

    with pytest.raises(PersistenceError):
        save(_decision(), None)

    assert _approval_status(engine, A1) == "PENDING"
    record = reservations.get(P1)
    assert record is not None
    assert record.status is ReservationStatus.REQUESTED


def test_an_unreachable_database_approves_nothing(
    pg_db: str,
    engine: Engine,
    db: OperationalDatabase,
    reservations: PgRiskReservationStore,
) -> None:
    _open_today(db)
    reservations.register_request(_request(), now_utc=NOW)
    # An engine whose pool points at a closed port: every transaction fails to connect.
    dead_url = make_url(pg_db).set(port=1, drivername="postgresql+psycopg")
    dead_engine = create_engine(dead_url, connect_args={"connect_timeout": 2})
    try:
        dead_db = OperationalDatabase(dead_engine)
        save = make_reserving_save_atomic(
            approvals=PgApprovalStore(dead_db),
            reservations=PgRiskReservationStore(dead_db),
            parameter_set=RATES,
            daily_loss_quote=lambda _day: ZERO,
        )
        with pytest.raises(PersistenceError):
            save(_decision(), None)
    finally:
        dead_engine.dispose()

    assert _approval_status(engine, A1) == "PENDING"
    record = reservations.get(P1)
    assert record is not None
    assert record.status is ReservationStatus.REQUESTED


# --------------------------------------------------------------------------------------
# SKIP / CANCEL / EXPIRE release the request in the same transaction
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("action", "status", "reason", "expected_status"),
    [
        (
            ApprovalAction.SKIP_USER,
            ApprovalResult.SKIPPED,
            ReleaseReason.APPROVAL_SKIPPED,
            "SKIPPED",
        ),
        (
            ApprovalAction.SKIP_BUSY,
            ApprovalResult.SKIPPED,
            ReleaseReason.APPROVAL_SKIPPED,
            "SKIPPED",
        ),
        (
            ApprovalAction.CANCEL,
            ApprovalResult.SKIPPED,
            ReleaseReason.APPROVAL_SKIPPED,
            "SKIPPED",
        ),
        (
            ApprovalAction.APPROVE,
            ApprovalResult.EXPIRED,
            ReleaseReason.APPROVAL_EXPIRED,
            "EXPIRED",
        ),
    ],
)
def test_a_skip_cancel_or_expire_releases_the_request_with_the_decision(
    engine: Engine,
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
    action: ApprovalAction,
    status: ApprovalResult,
    reason: ReleaseReason,
    expected_status: str,
) -> None:
    reservations.register_request(_request(), now_utc=NOW)

    _composed(approvals, reservations)(_decision(action=action, status=status), None)

    assert _approval_status(engine, A1) == expected_status
    record = reservations.get(P1)
    assert record is not None
    assert record.status is ReservationStatus.RELEASED
    assert record.release_reason is reason
    assert record.released_at_utc == ACTED
    assert reservations.list_counted() == ()


def test_a_skip_after_the_plan_is_reserved_leaves_the_reservation_alone(
    engine: Engine,
    db: OperationalDatabase,
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
) -> None:
    _open_today(db)
    reservations.register_request(_request(), now_utc=NOW)
    save = _composed(approvals, reservations)
    save(_decision(), None)

    with pytest.raises(ApprovalAlreadyDecided):
        save(_skip(A3, P1, action=ApprovalAction.SKIP_USER), None)

    record = reservations.get(P1)
    assert record is not None
    assert (record.status, record.approval_id) == (ReservationStatus.RESERVED, A1)
    assert _approval_status(engine, A3) == "PENDING"


def test_a_skip_for_a_plan_already_released_by_plan_expiry_keeps_the_first_reason(
    engine: Engine, approvals: PgApprovalStore, reservations: PgRiskReservationStore
) -> None:
    reservations.register_request(_request(), now_utc=NOW)
    reservations.release(P1, reason=ReleaseReason.PLAN_EXPIRED, now_utc=NOW)

    _composed(approvals, reservations)(_skip(action=ApprovalAction.SKIP_USER), None)

    assert _approval_status(engine, A1) == "SKIPPED"
    record = reservations.get(P1)
    assert record is not None
    assert record.status is ReservationStatus.RELEASED
    assert record.release_reason is ReleaseReason.PLAN_EXPIRED
    assert record.released_at_utc == NOW


def test_the_same_approve_decision_twice_raises_and_keeps_the_reservation(
    db: OperationalDatabase,
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
) -> None:
    _open_today(db)
    reservations.register_request(_request(), now_utc=NOW)
    save = _composed(approvals, reservations)
    save(_decision(), None)

    with pytest.raises(ApprovalAlreadyDecided):
        save(_decision(), None)

    record = reservations.get(P1)
    assert record is not None
    assert (record.status, record.approval_id) == (ReservationStatus.RESERVED, A1)


def test_release_requested_in_refuses_a_reason_that_does_not_release_requested(
    db: OperationalDatabase, reservations: PgRiskReservationStore
) -> None:
    reservations.register_request(_request(), now_utc=NOW)

    with pytest.raises(ValueError, match="PLAN_EXPIRED"), db.transaction() as session:
        reservations.release_requested_in(
            session, trade_plan_id=P1, reason=ReleaseReason.PLAN_EXPIRED, now_utc=ACTED
        )

    record = reservations.get(P1)
    assert record is not None
    assert record.status is ReservationStatus.REQUESTED


def test_release_requested_in_is_a_no_op_for_a_plan_without_a_request(
    db: OperationalDatabase, reservations: PgRiskReservationStore
) -> None:
    with db.transaction() as session:
        reservations.release_requested_in(
            session, trade_plan_id=P2, reason=ReleaseReason.APPROVAL_SKIPPED, now_utc=ACTED
        )

    assert reservations.get(P2) is None


# --------------------------------------------------------------------------------------
# The refusal reaches the callback layer
# --------------------------------------------------------------------------------------
def test_resolve_callback_propagates_the_cap_refusal_and_the_approval_stays_pending(
    engine: Engine,
    db: OperationalDatabase,
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
) -> None:
    _open_today(db)
    reservations.register_request(
        _request(P1, HASH_1, symbol="BNBUSDT", side="LONG", risk="5.5"), now_utc=NOW
    )
    reservations.register_request(
        _request(P2, HASH_2, symbol="BNBUSDT", side="SHORT", risk="5.5"), now_utc=NOW
    )
    raw_token = "raw_token_" + "q" * 40
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE approvals SET approval_token_hash = :t, request_hash = :h "
                "WHERE approval_id = :a"
            ),
            {"t": token_hash_of(raw_token), "h": HASH_2, "a": A2},
        )
    save = _composed(approvals, reservations)
    save(_decision(A1, P1), None)
    callback = Callback(
        raw_token=raw_token,
        chat_id=77,
        plan_hash=HASH_2,
        strategy_version="sv",
        parameter_set_id="ps",
        parameter_set_hash="c" * 64,
        callback_at_utc=ACTED,
        action=ApprovalAction.APPROVE,
    )

    with pytest.raises(ApprovalRejected) as raised:
        resolve_callback(
            callback,
            approvals.lookup_by_token_hash,
            lambda approval: save(approval, None),
            authorized_chat_id=77,
            expiry_utc=ACTED + timedelta(hours=1),
            approval_strategy_version="sv",
            approval_parameter_set_id="ps",
            approval_parameter_set_hash="c" * 64,
            now_utc=ACTED,
        )

    assert raised.value.reason_code is RejectionReason.AGGREGATE_CAP_REJECT
    assert _approval_status(engine, A2) == "PENDING"


def test_two_approvals_acted_on_either_side_of_midnight_still_serialise(
    pg_db: str, engine: Engine, db: OperationalDatabase
) -> None:
    # WR-02: the day-row lock is one lock PER UTC day, so approvals decided at 23:59:59.9 and
    # 00:00:00.1 took different locks and both read the same counted rows. The advisory lock
    # taken before the day-row lock is day-independent: the second approval must wait for the
    # first and then see its reservation (5.5 + 5.5 = 11 > the aggregate cap 10).
    next_day = datetime(2026, 10, 24, 0, 0, 0, 100000, tzinfo=UTC)
    _open_today(db)
    PgDayRiskStore(db).open_day(
        DayRiskState(
            utc_day=next_day.date(),
            equity_at_day_start=D("1000"),
            base_observed_at_utc=next_day,
        )
    )
    outcomes, pausing, seed = _race(pg_db, engine, db, second_acted_at=next_day)
    assert outcomes["first"] == "approved"
    refused = outcomes["second"]
    assert isinstance(refused, ReservationRefused)
    assert refused.reason_code is RejectionReason.AGGREGATE_CAP_REJECT
    assert pausing[0].second_was_blocked is True
    p2 = seed.get(P2)
    assert p2 is not None
    assert (p2.status, p2.approval_id) == (ReservationStatus.REQUESTED, None)
    assert _approval_status(engine, A2) == "PENDING"


def test_the_approval_serialisation_lock_key_is_the_documented_stable_63_bit_key() -> None:
    digest = hashlib.sha256(b"trading-alert:risk_reservations:approval-serialisation").digest()
    assert APPROVAL_SERIALISATION_LOCK_KEY == int.from_bytes(digest[:8], "big") & (2**63 - 1)
    assert 0 < APPROVAL_SERIALISATION_LOCK_KEY < 2**63


# --------------------------------------------------------------------------------------
# G4-042 (plan 23-08, D-16): EXPIRED rows sit outside uq_approvals_one_decided_per_plan
# --------------------------------------------------------------------------------------
def _expire(approval_id: str, *, acted_at: datetime, token: int) -> Approval:
    return _decision(
        approval_id,
        action=ApprovalAction.SKIP_USER,
        status=ApprovalResult.EXPIRED,
        token=token,
        acted_at=acted_at,
    )


def test_expiring_the_sibling_of_an_approved_plan_keeps_its_reservation(
    engine: Engine,
    db: OperationalDatabase,
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
) -> None:
    """T-23-24: the store refuses the EXPIRED decision before the reserving hook can release."""
    _open_today(db)
    reservations.register_request(_request(), now_utc=NOW)
    save = _composed(approvals, reservations)
    save(_decision(), None)

    with pytest.raises(ApprovalAlreadyDecided) as refused:
        save(_expire(A3, acted_at=ACTED + timedelta(minutes=1), token=0x3003), None)

    assert refused.value.existing.approval_id == A1
    record = reservations.get(P1)
    assert record is not None
    assert (record.status, record.approval_id) == (ReservationStatus.RESERVED, A1)
    assert record.release_reason is None
    assert _approval_status(engine, A3) == "PENDING"


def test_both_expiries_of_an_undecided_plan_release_its_request_once(
    engine: Engine, approvals: PgApprovalStore, reservations: PgRiskReservationStore
) -> None:
    reservations.register_request(_request(), now_utc=NOW)
    save = _composed(approvals, reservations)
    later = ACTED + timedelta(minutes=1)

    save(_decision(A1, status=ApprovalResult.EXPIRED), None)
    save(_expire(A3, acted_at=later, token=0x3003), None)

    assert _approval_status(engine, A1) == "EXPIRED"
    assert _approval_status(engine, A3) == "EXPIRED"
    record = reservations.get(P1)
    assert record is not None
    assert record.status is ReservationStatus.RELEASED
    assert record.release_reason is ReleaseReason.APPROVAL_EXPIRED
    # The second release matched no REQUESTED row: it is a no-op, the first timestamp stays.
    assert record.released_at_utc == ACTED
    assert reservations.list_counted() == ()
