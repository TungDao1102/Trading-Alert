"""PostgreSQL store of the durable risk reservations (Phase 21, plan 21-12; D-16, D-17, F-407).

`PgRiskReservationStore` keeps one table (migration 0011), `risk_reservations`: ONE row per
trade plan for its whole life.

    REQUESTED  issued, not counted        (register_request, at plan issue)
    RESERVED   approved, counted          (reserve_in, inside the approval transaction)
    PLACED     entry consumed and sent    (mark_placed, Phase 24 caller)
    OPEN       filled                     (mark_open, Phase 24 caller)
    RELEASED   terminal, not counted      (release, one reason per terminal plan state)

Rules this store keeps:

  - `reserve_in` runs inside the CALLER's transaction. It locks today's `daily_risk_days` row
    `FOR UPDATE` (the one lock every approval serialises on), reads the counted rows, judges the
    plan's stored realized risk with `reservation_verdict` (the shared `check_portfolio`) and
    turns the REQUESTED row into RESERVED, or raises `ReservationRefused` and changes nothing.
    It never commits or rolls back and swallows no exception. Plan 21-15 composes it into the
    approval transaction.
  - `release` follows `RELEASE_SOURCE_STATUSES` exactly: a permitted source status becomes
    RELEASED with the reason and time; an already RELEASED row is a no-op that keeps its FIRST
    stored reason (two terminal signals can race, for example the approval expiry and the plan
    expiry of a PENDING plan); any other source status and an absent plan raise `RowConflict`.
  - `mark_placed` (RESERVED -> PLACED) and `mark_open` (PLACED -> OPEN) are no-ops on repeat and
    `RowConflict` otherwise, so a RELEASED row can never be counted again.
  - Every counted reservation is read from the table: a new store instance over the same
    database returns the same rows; nothing is kept in memory.
  - There is NO delete path. Messages name the plan, the reason and the status, never an amount.

The pure types and the gate are the ones of `src/risk/reservations.py`; nothing is redefined
here. Decimals go in and come out exactly (`NUMERIC(38, 18)`); an amount with more than 18
fractional digits raises `PrecisionError` before any write. This module reads no clock: every
time is passed in.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.approval.binding import ApprovalRejected
from src.db.models import RiskReservationRow
from src.domain.approval import Approval
from src.domain.canonical import quantize_for_storage
from src.domain.enums import ApprovalResult, RejectionReason
from src.persistence.day_risk import PgDayRiskStore
from src.persistence.errors import ParentRowMissing, PrecisionError, RowConflict
from src.persistence.uow import OperationalDatabase
from src.risk.daily_loss import DayRiskState, day_thresholds, utc_day_of
from src.risk.reservations import (
    COUNTED_STATUSES,
    RELEASE_SOURCE_STATUSES,
    CountedReservation,
    ReleaseReason,
    ReservationRequest,
    ReservationStatus,
    reservation_verdict,
)

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"

_S = ReservationStatus


class ReservationRefused(ApprovalRejected):
    """The approval cannot reserve its risk: the shared cap gate said NO_TRADE (D-16, D-17).

    `reason_code` is the `RejectionReason` the gate gave (a cap, DAILY_STOP_BLOCK or
    UNCERTAIN_ACCOUNT_STATE), so the approval transaction surfaces it through the callback
    dispatch unchanged. The message is the reason value only: no amount, no account figure.
    """

    def __init__(self, reason_code: RejectionReason) -> None:
        super().__init__(reason_code, reason_code.value)


@dataclass(frozen=True)
class ReservationRecord:
    """One stored reservation row (the lifecycle fields; the sized amounts stay in the row)."""

    trade_plan_id: str
    approval_id: str | None
    status: ReservationStatus
    release_reason: ReleaseReason | None
    requested_at_utc: datetime
    reserved_at_utc: datetime | None
    placed_at_utc: datetime | None
    opened_at_utc: datetime | None
    released_at_utc: datetime | None


def _to_record(row: RiskReservationRow) -> ReservationRecord:
    return ReservationRecord(
        trade_plan_id=row.trade_plan_id,
        approval_id=row.approval_id,
        status=ReservationStatus(row.status),
        release_reason=None if row.release_reason is None else ReleaseReason(row.release_reason),
        requested_at_utc=row.requested_at_utc,
        reserved_at_utc=row.reserved_at_utc,
        placed_at_utc=row.placed_at_utc,
        opened_at_utc=row.opened_at_utc,
        released_at_utc=row.released_at_utc,
    )


def _require_exact_storage(value: Decimal, name: str) -> None:
    """Refuse a Decimal that NUMERIC(38,18) would round (F-410): never store a changed value."""
    if quantize_for_storage(value) != value:
        raise PrecisionError(f"{name}: more than 18 fractional digits")


def _require_utc(at_utc: datetime, name: str) -> None:
    if (
        not isinstance(at_utc, datetime)
        or at_utc.tzinfo is None
        or at_utc.utcoffset() != timedelta(0)
    ):
        raise ValueError(f"{name} must be a UTC-aware datetime")


def _request_from_row(row: RiskReservationRow) -> ReservationRequest:
    return ReservationRequest(
        trade_plan_id=row.trade_plan_id,
        plan_hash=row.plan_hash,
        symbol=row.symbol,
        position_side=row.position_side,
        quantity=row.quantity,
        realized_risk=row.realized_risk,
    )


def _counted_from_row(row: RiskReservationRow) -> CountedReservation:
    return CountedReservation(
        trade_plan_id=row.trade_plan_id,
        plan_hash=row.plan_hash,
        symbol=row.symbol,
        position_side=row.position_side,
        status=ReservationStatus(row.status),
        open_risk=row.realized_risk,
    )


def _counted_rows(session: Session) -> tuple[CountedReservation, ...]:
    rows = session.scalars(
        select(RiskReservationRow)
        .where(RiskReservationRow.status.in_([s.value for s in COUNTED_STATUSES]))
        .order_by(
            RiskReservationRow.symbol,
            RiskReservationRow.position_side,
            RiskReservationRow.trade_plan_id,
        )
    ).all()
    return tuple(_counted_from_row(row) for row in rows)


class PgRiskReservationStore:
    """The durable risk reservation of each trade plan, on PostgreSQL."""

    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db
        self._day_store = PgDayRiskStore(db)

    @contextmanager
    def _unit(self, tx: Session | None) -> Iterator[Session]:
        """Join the caller's unit of work, or open (and commit) one."""
        if tx is not None:
            yield tx
            return
        with self._db.transaction() as session:
            yield session

    # ------------------------------------------------------------------ reads

    def get(self, trade_plan_id: str, *, tx: Session | None = None) -> ReservationRecord | None:
        """The stored reservation of `trade_plan_id`, or None when none was registered."""
        with self._unit(tx) as session:
            row = session.get(RiskReservationRow, trade_plan_id, populate_existing=True)
            return None if row is None else _to_record(row)

    def list_counted(self, *, tx: Session | None = None) -> tuple[CountedReservation, ...]:
        """Every RESERVED, PLACED and OPEN row, sorted by (symbol, position_side, plan id).

        Rebuilt from the table on every call; the reserved risk is the sized realized risk.
        """
        with self._unit(tx) as session:
            return _counted_rows(session)

    # ----------------------------------------------------------------- writes

    def register_request(
        self, request: ReservationRequest, *, now_utc: datetime, tx: Session | None = None
    ) -> ReservationRecord:
        """Store the plan's risk as a REQUESTED row (not counted), once.

        A repeat with the same identity (plan hash, symbol, side, quantity, realized risk) is a
        no-op that returns the stored record.

        Raises:
            PrecisionError: an amount has more than 18 fractional digits. Nothing is written.
            RowConflict: the plan already holds a reservation with another identity.
            ParentRowMissing: the trade plan does not exist.
        """
        _require_utc(now_utc, "now_utc")
        _require_exact_storage(request.quantity, "risk_reservations.quantity")
        _require_exact_storage(request.realized_risk, "risk_reservations.realized_risk")
        try:
            with self._unit(tx) as session:
                session.execute(
                    pg_insert(RiskReservationRow)
                    .values(
                        trade_plan_id=request.trade_plan_id,
                        approval_id=None,
                        plan_hash=request.plan_hash,
                        symbol=request.symbol,
                        position_side=request.position_side,
                        quantity=request.quantity,
                        realized_risk=request.realized_risk,
                        status=_S.REQUESTED.value,
                        release_reason=None,
                        requested_at_utc=now_utc,
                        updated_at_utc=now_utc,
                    )
                    .on_conflict_do_nothing(index_elements=["trade_plan_id"])
                )
                row = session.get(RiskReservationRow, request.trade_plan_id, populate_existing=True)
                if row is None:
                    # Not reachable while the primary key holds; never guess (fail closed).
                    raise RowConflict(
                        f"risk_reservations {request.trade_plan_id}: stored row not visible"
                    )
                if (
                    row.plan_hash != request.plan_hash
                    or row.symbol != request.symbol
                    or row.position_side != request.position_side
                    or row.quantity != request.quantity
                    or row.realized_risk != request.realized_risk
                ):
                    raise RowConflict(
                        f"risk_reservations {request.trade_plan_id} already registered with "
                        "a different identity"
                    )
                return _to_record(row)
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                raise ParentRowMissing(
                    f"risk_reservations {request.trade_plan_id}: trade plan missing"
                ) from exc
            raise

    def reserve_in(
        self,
        session: Session,
        *,
        approval: Approval,
        now_utc: datetime,
        daily_loss_quote: Decimal | None,
        parameter_set: dict[str, Any],
    ) -> ReservationRecord:
        """Turn the plan's REQUESTED row into RESERVED inside the caller's transaction.

        Order (every step fails closed): lock today's `daily_risk_days` row `FOR UPDATE`; lock
        the plan's reservation row; read the counted rows; resolve the thresholds from the
        STORED day base; judge the stored realized risk with `reservation_verdict`; only a
        passing verdict updates the row. `parameter_set` holds the registry RATES. Never
        commits or rolls back; the caller owns `session`.

        A RESERVED row of the same approval is returned unchanged (idempotent replay).

        Raises:
            ReservationRefused: the gate said NO_TRADE (a cap, DAILY_STOP_BLOCK) or the day
                state, the row, the approval or the thresholds are missing or unusable
                (UNCERTAIN_ACCOUNT_STATE). Nothing is changed.
        """
        _require_utc(now_utc, "now_utc")
        uncertain = RejectionReason.UNCERTAIN_ACCOUNT_STATE
        if approval.status != ApprovalResult.APPROVED:
            raise ReservationRefused(uncertain)
        day_row = self._day_store.lock_day(session, utc_day_of(now_utc))
        if day_row is None:
            raise ReservationRefused(uncertain)
        row = session.execute(
            select(RiskReservationRow)
            .where(RiskReservationRow.trade_plan_id == approval.trade_plan_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise ReservationRefused(uncertain)
        if row.status == _S.RESERVED.value and row.approval_id == approval.approval_id:
            return _to_record(row)
        if row.status != _S.REQUESTED.value:
            raise ReservationRefused(uncertain)
        thresholds = day_thresholds(
            parameter_set=parameter_set,
            day=DayRiskState(
                utc_day=day_row.utc_day,
                equity_at_day_start=day_row.equity_at_day_start,
                base_observed_at_utc=day_row.base_observed_at_utc,
                stop_latched_at_utc=day_row.stop_latched_at_utc,
                warning_alerted_at_utc=day_row.warning_alerted_at_utc,
            ),
        )
        if thresholds is None:
            raise ReservationRefused(uncertain)
        verdict = reservation_verdict(
            request=_request_from_row(row),
            counted=_counted_rows(session),
            daily_loss_quote=daily_loss_quote,
            stop_latched=day_row.stop_latched_at_utc is not None,
            thresholds=thresholds,
            now_utc=now_utc,
        )
        if verdict.is_no_trade:
            try:
                reason = RejectionReason(verdict.reason_code)
            except ValueError:
                reason = uncertain
            raise ReservationRefused(reason)
        row.status = _S.RESERVED.value
        row.approval_id = approval.approval_id
        row.reserved_at_utc = now_utc
        row.updated_at_utc = now_utc
        session.flush()
        return _to_record(row)

    def mark_placed(
        self, trade_plan_id: str, *, now_utc: datetime, tx: Session | None = None
    ) -> ReservationRecord:
        """RESERVED -> PLACED; a repeat is a no-op, any other status is a `RowConflict`."""
        return self._advance(
            trade_plan_id,
            now_utc=now_utc,
            tx=tx,
            source=_S.RESERVED,
            target=_S.PLACED,
            time_column="placed_at_utc",
        )

    def mark_open(
        self, trade_plan_id: str, *, now_utc: datetime, tx: Session | None = None
    ) -> ReservationRecord:
        """PLACED -> OPEN; a repeat is a no-op, any other status is a `RowConflict`."""
        return self._advance(
            trade_plan_id,
            now_utc=now_utc,
            tx=tx,
            source=_S.PLACED,
            target=_S.OPEN,
            time_column="opened_at_utc",
        )

    def _advance(
        self,
        trade_plan_id: str,
        *,
        now_utc: datetime,
        tx: Session | None,
        source: ReservationStatus,
        target: ReservationStatus,
        time_column: str,
    ) -> ReservationRecord:
        _require_utc(now_utc, "now_utc")
        with self._unit(tx) as session:
            row = self._locked(session, trade_plan_id)
            if row.status == target.value:
                return _to_record(row)
            if row.status != source.value:
                raise RowConflict(
                    f"risk_reservations {trade_plan_id}: cannot become {target.value} "
                    f"from {row.status}"
                )
            row.status = target.value
            setattr(row, time_column, now_utc)
            row.updated_at_utc = now_utc
            session.flush()
            return _to_record(row)

    def release(
        self,
        trade_plan_id: str,
        *,
        reason: ReleaseReason,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> ReservationRecord:
        """Release the reservation for `reason`, following `RELEASE_SOURCE_STATUSES` exactly.

        A permitted source status becomes RELEASED with the reason and time. An already RELEASED
        row is returned unchanged: two terminal signals can race (for example the approval
        expiry and the plan expiry of a PENDING plan), the first durable reason wins, and a
        RELEASED row cannot be counted again because `mark_placed` and `mark_open` refuse it.

        Raises:
            RowConflict: the plan has no reservation, or its status is not a permitted source
                of `reason` (a PLACED or OPEN row is never released by a plan-status reason).
        """
        _require_utc(now_utc, "now_utc")
        with self._unit(tx) as session:
            row = self._locked(session, trade_plan_id)
            if row.status == _S.RELEASED.value:
                return _to_record(row)
            if ReservationStatus(row.status) not in RELEASE_SOURCE_STATUSES[reason]:
                raise RowConflict(
                    f"risk_reservations {trade_plan_id}: {reason.value} cannot release "
                    f"a {row.status} reservation"
                )
            row.status = _S.RELEASED.value
            row.release_reason = reason.value
            row.released_at_utc = now_utc
            row.updated_at_utc = now_utc
            session.flush()
            return _to_record(row)

    @staticmethod
    def _locked(session: Session, trade_plan_id: str) -> RiskReservationRow:
        row = session.execute(
            select(RiskReservationRow)
            .where(RiskReservationRow.trade_plan_id == trade_plan_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise RowConflict(f"risk_reservations {trade_plan_id}: no reservation stored")
        return row


__all__ = ["PgRiskReservationStore", "ReservationRecord", "ReservationRefused"]
