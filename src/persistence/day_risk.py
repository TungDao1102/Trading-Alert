"""PostgreSQL store of the UTC day's risk state (Phase 21, plan 21-09; D-07, D-14, F-963).

`PgDayRiskStore` keeps two tables (migration 0010):

  - `daily_risk_days`: ONE row per UTC day with the day-start equity base, when it was read,
    and the one-time DAILY_STOP latch and WARNING alert marks.
  - `daily_loss_components`: one row per (utc_day, kind, source, source_key), the signed loss
    components Binance reported (`src.risk.daily_loss.LossComponent`).

Rules this store keeps:

  - `open_day` never moves a stored base: it inserts the day if absent, then returns the STORED
    row. A second open (another process, a restart, a retry) returns the first row unchanged,
    so a restart inside the UTC day keeps the day and its base (D-07).
  - `latch_stop` and `mark_warning_alerted` set their time once. A second call, a later time or a
    restart never clears or moves it (D-14). On an absent day they raise `RowConflict`.
  - `add_components` is idempotent per key. The same key with another amount or asset raises
    `RowConflict` (the message names the key, never the amount) and stores nothing from that
    call (one transaction): fail closed, no silent replacement.
  - `lock_day` selects the day row `FOR UPDATE` inside the caller's transaction; the approval
    transaction serialises on it (plan 21-12).
  - There is NO delete or purge method: retention is owner-open O-1 and no number is invented.
  - An unreachable database raises `StoreUnavailable` from the unit of work; there is no retry
    loop here.

The domain types (`DayRiskState`, `LossComponent`) are the ones of `src/risk/daily_loss.py`;
nothing is redefined here. Decimals go in and come out exactly (`NUMERIC(38, 18)`); an amount
with more than 18 fractional digits raises `PrecisionError` before any write. `created_at_utc`
and `recorded_at_utc` are set by the database clock (`now()`); this module reads no clock.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.db.models import DailyLossComponentRow, DailyRiskDayRow
from src.domain.canonical import quantize_for_storage
from src.persistence.errors import PrecisionError, RowConflict
from src.persistence.uow import OperationalDatabase
from src.risk.daily_loss import (
    ComponentKind,
    ComponentSource,
    DayRiskState,
    LossComponent,
    base_is_inside_day,
)


def _require_exact_storage(value: Decimal, name: str) -> None:
    """Refuse a Decimal that NUMERIC(38,18) would round (F-410): never store a changed value."""
    if quantize_for_storage(value) != value:
        raise PrecisionError(f"{name}: more than 18 fractional digits")


def _state_from_row(row: DailyRiskDayRow) -> DayRiskState:
    return DayRiskState(
        utc_day=row.utc_day,
        equity_at_day_start=row.equity_at_day_start,
        base_observed_at_utc=row.base_observed_at_utc,
        stop_latched_at_utc=row.stop_latched_at_utc,
        warning_alerted_at_utc=row.warning_alerted_at_utc,
    )


def _component_from_row(row: DailyLossComponentRow) -> LossComponent:
    return LossComponent(
        utc_day=row.utc_day,
        kind=ComponentKind(row.kind),
        source=ComponentSource(row.source),
        source_key=row.source_key,
        amount=row.amount,
        asset=row.asset,
        event_time_utc=row.event_time_utc,
    )


def _key_text(component: LossComponent) -> str:
    return (
        f"{component.utc_day.isoformat()}/{component.kind.value}/"
        f"{component.source.value}/{component.source_key}"
    )


class PgDayRiskStore:
    """The UTC day's risk state and loss components, on PostgreSQL."""

    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db

    @contextmanager
    def _unit(self, tx: Session | None) -> Iterator[Session]:
        """Join the caller's unit of work, or open (and commit) one."""
        if tx is not None:
            yield tx
            return
        with self._db.transaction() as session:
            yield session

    # ------------------------------------------------------------------ reads

    def get_day(self, utc_day: date, *, tx: Session | None = None) -> DayRiskState | None:
        """The stored state of `utc_day`, or None when the day was never opened."""
        with self._unit(tx) as session:
            row = session.get(DailyRiskDayRow, utc_day, populate_existing=True)
            return None if row is None else _state_from_row(row)

    def has_day(self, utc_day: date, *, tx: Session | None = None) -> bool:
        """True when `utc_day` has a stored state."""
        with self._unit(tx) as session:
            return session.get(DailyRiskDayRow, utc_day, populate_existing=True) is not None

    def list_components(
        self, utc_day: date, *, tx: Session | None = None
    ) -> tuple[LossComponent, ...]:
        """The stored components of `utc_day`, ordered by (kind, source, source_key)."""
        with self._unit(tx) as session:
            rows = session.scalars(
                select(DailyLossComponentRow)
                .where(DailyLossComponentRow.utc_day == utc_day)
                .order_by(
                    DailyLossComponentRow.kind,
                    DailyLossComponentRow.source,
                    DailyLossComponentRow.source_key,
                )
            ).all()
            return tuple(_component_from_row(row) for row in rows)

    def lock_day(self, session: Session, utc_day: date) -> DailyRiskDayRow | None:
        """Select the day row `FOR UPDATE` inside the caller's transaction; None when absent.

        A second transaction asking for the same day blocks until the first commits or rolls
        back. The caller owns `session`; this method never commits.
        """
        return session.execute(
            select(DailyRiskDayRow).where(DailyRiskDayRow.utc_day == utc_day).with_for_update()
        ).scalar_one_or_none()

    # ----------------------------------------------------------------- writes

    def open_day(self, state: DayRiskState, *, tx: Session | None = None) -> DayRiskState:
        """Insert the day if absent, then return the STORED state.

        A second open of the same day never moves the base: the first stored row wins and is
        returned unchanged. The caller compares the result with `state` when it cares.

        Raises:
            PrecisionError: `equity_at_day_start` has more than 18 fractional digits. Nothing
                is written.
        """
        _require_exact_storage(state.equity_at_day_start, "daily_risk_days.equity_at_day_start")
        with self._unit(tx) as session:
            session.execute(
                pg_insert(DailyRiskDayRow)
                .values(
                    utc_day=state.utc_day,
                    equity_at_day_start=state.equity_at_day_start,
                    base_observed_at_utc=state.base_observed_at_utc,
                    stop_latched_at_utc=state.stop_latched_at_utc,
                    warning_alerted_at_utc=state.warning_alerted_at_utc,
                )
                .on_conflict_do_nothing(index_elements=["utc_day"])
            )
            row = session.get(DailyRiskDayRow, state.utc_day, populate_existing=True)
            if row is None:
                # Not reachable while the primary key holds; never guess (fail closed).
                raise RowConflict(f"daily_risk_days {state.utc_day}: stored row not visible")
            return _state_from_row(row)

    def latch_stop(
        self, *, utc_day: date, at_utc: datetime, tx: Session | None = None
    ) -> DayRiskState:
        """Set the DAILY_STOP latch time once; a stored latch is returned unchanged (D-14).

        Raises:
            RowConflict: the day has no stored state.
            ValueError: `at_utc` is not UTC-aware or lies outside the UTC day.
        """
        return self._stamp_once(column="stop_latched_at_utc", utc_day=utc_day, at_utc=at_utc, tx=tx)

    def mark_warning_alerted(
        self, *, utc_day: date, at_utc: datetime, tx: Session | None = None
    ) -> DayRiskState:
        """Set the WARNING alert time once; a stored mark is returned unchanged.

        Raises:
            RowConflict: the day has no stored state.
            ValueError: `at_utc` is not UTC-aware or lies outside the UTC day.
        """
        return self._stamp_once(
            column="warning_alerted_at_utc", utc_day=utc_day, at_utc=at_utc, tx=tx
        )

    def _stamp_once(
        self, *, column: str, utc_day: date, at_utc: datetime, tx: Session | None
    ) -> DayRiskState:
        if not base_is_inside_day(utc_day=utc_day, observed_at_utc=at_utc):
            raise ValueError(f"{column} {at_utc.isoformat()} is outside UTC day {utc_day}")
        with self._unit(tx) as session:
            session.execute(
                update(DailyRiskDayRow)
                .where(
                    DailyRiskDayRow.utc_day == utc_day,
                    getattr(DailyRiskDayRow, column).is_(None),
                )
                .values({column: at_utc})
            )
            row = session.get(DailyRiskDayRow, utc_day, populate_existing=True)
            if row is None:
                raise RowConflict(f"daily_risk_days {utc_day}: no stored state to set {column}")
            return _state_from_row(row)

    def add_components(
        self, components: Sequence[LossComponent], *, tx: Session | None = None
    ) -> int:
        """Store the components; a repeated key is a no-op. Returns the number inserted.

        All of the call is one transaction: when any key already holds another amount or asset,
        `RowConflict` is raised and nothing of this call is stored.

        Raises:
            PrecisionError: an amount has more than 18 fractional digits. Nothing is written.
            RowConflict: a stored key has a different amount or asset.
        """
        for component in components:
            _require_exact_storage(component.amount, "daily_loss_components.amount")
        inserted = 0
        with self._unit(tx) as session:
            for component in components:
                added = session.execute(
                    pg_insert(DailyLossComponentRow)
                    .values(
                        utc_day=component.utc_day,
                        kind=component.kind.value,
                        source=component.source.value,
                        source_key=component.source_key,
                        amount=component.amount,
                        asset=component.asset,
                        event_time_utc=component.event_time_utc,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["utc_day", "kind", "source", "source_key"]
                    )
                    .returning(DailyLossComponentRow.source_key)
                ).first()
                if added is not None:
                    inserted += 1
                    continue
                stored = session.get(
                    DailyLossComponentRow,
                    (
                        component.utc_day,
                        component.kind.value,
                        component.source.value,
                        component.source_key,
                    ),
                    populate_existing=True,
                )
                if stored is None:
                    # Not reachable while the primary key holds; never guess (fail closed).
                    raise RowConflict(
                        f"daily_loss_components {_key_text(component)}: stored row not visible"
                    )
                if stored.amount != component.amount or stored.asset != component.asset:
                    raise RowConflict(
                        f"daily_loss_components {_key_text(component)} already stored with a "
                        "different amount or asset"
                    )
        return inserted


__all__ = ["PgDayRiskStore"]
