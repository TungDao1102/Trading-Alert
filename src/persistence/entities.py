"""PostgreSQL repositories for Signal, TradePlan, Order, Fill and Position (Phase 17, plan 10).

`PgTradingEntityStore` gives the five remaining domain entities (Approval and JournalEvent have
their own stores) a durable home and gives every mapper pair in `src/db/mappers.py` a
production caller (D-02, D-21, DOMN-01, SC1). Two rules are enforced HERE, so no caller can
bypass them:

State machines (DOMN-04, D-20, T-17-26). Every status change runs in ONE transaction:

  1. `SELECT ... FOR UPDATE` locks the row, so a concurrent writer waits and then sees the
     committed status instead of racing it;
  2. an unchanged status is an idempotent no-op returning the stored entity
     (`assert_transition` raises on equal states by design, plan 03);
  3. `src.domain.transitions.assert_transition` validates the move; `IllegalTransition`
     propagates and nothing is written;
  4. a conditional `UPDATE ... WHERE <status column> = old` applies the move together with its
     timestamp side effects, all taken from the injected `now_utc` (never a wall clock):
     Signal INVALIDATED sets `invalidated_at_utc`; Order CANCELED sets `canceled_at_utc`;
     Position CLOSED sets `closed_at_utc`; Order and Position moves set `updated_at_utc`.
     `rowcount` must be 1, otherwise `RowConflict`.

The PostgreSQL terminal-status triggers of migration 0004 are the second line of defence
against a writer that bypasses this class; `tests/test_persistence_transitions_pg.py` proves
they match `transitions.TERMINAL_STATES`.

Precision (D-12, F-410, T-17-27). Before any write, every Decimal bound for a NUMERIC column
must equal `quantize_for_storage(value)`, else `PrecisionError` naming the table and field (never
the value). PostgreSQL would otherwise round a 19th fractional digit silently and the stored
`plan_hash` inputs would no longer reproduce.

Inserts are idempotent: `INSERT ... ON CONFLICT (primary key) DO NOTHING`, and when nothing was
inserted the stored row is re-read and compared. Fields that legitimately evolve after insertion
(status and its timestamps; for an Order the exchange identifiers and exchange status; for a
Position the quantities and PnL) are excluded from that comparison, so replaying the original
insert after the entity advanced is a no-op, while a different entity under the same id raises
`RowConflict` (the approvals store follows the same rule). A foreign key violation is
`ParentRowMissing`; a unique violation on another arbiter (for example `client_order_id`) is
`RowConflict`. Fills are compared in full and are idempotent on `(order_id, exchange_trade_id)`
as well as on `fill_id`, because Phase 18's stream will redeliver them.

Every method takes an optional keyword `tx` (a Session from `OperationalDatabase.transaction()`).
When absent the method opens its own transaction; when present the work joins the caller's unit
of work, so an order transition and its journal event commit together or not at all (D-03).
A failed statement inside a caller-owned transaction leaves it aborted; the caller propagates the
exception and the unit of work rolls back as a whole. An unreachable database raises
`StoreUnavailable` from the unit of work; there is no retry loop (F-406).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.mappers import (
    fill_from_row,
    fill_to_row,
    order_from_row,
    order_to_row,
    position_from_row,
    position_to_row,
    signal_from_row,
    signal_to_row,
    trade_plan_from_row,
    trade_plan_to_row,
)
from src.db.models import FillRow, OrderRow, PositionRow, SignalRow, TradePlanRow
from src.domain.canonical import STORAGE_DECIMAL_PLACES, quantize_for_storage
from src.domain.enums import (
    OrderStatus,
    PositionStatus,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.fill import Fill
from src.domain.order import Order
from src.domain.position import Position
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.domain.transitions import TransitionKind, assert_transition
from src.persistence.errors import (
    ParentRowMissing,
    PersistenceError,
    PrecisionError,
    RowConflict,
)
from src.persistence.uow import OperationalDatabase

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
_SQLSTATE_UNIQUE_VIOLATION = "23505"


@dataclass(frozen=True)
class _Spec[E, R]:
    """How one entity maps to its table and which columns are fixed after insertion."""

    label: str
    model: type[R]
    id_column: str
    to_row: Callable[[E], R]
    from_row: Callable[[R], E]
    # Columns that evolve after insertion; excluded from the idempotent-insert comparison.
    evolving: frozenset[str]


_SIGNAL = _Spec(
    label="signal",
    model=SignalRow,
    id_column="signal_id",
    to_row=signal_to_row,
    from_row=signal_from_row,
    evolving=frozenset({"status", "invalidated_at_utc"}),
)
_TRADE_PLAN = _Spec(
    label="trade plan",
    model=TradePlanRow,
    id_column="trade_plan_id",
    to_row=trade_plan_to_row,
    from_row=trade_plan_from_row,
    evolving=frozenset({"status"}),
)
_ORDER = _Spec(
    label="order",
    model=OrderRow,
    id_column="order_id",
    to_row=order_to_row,
    from_row=order_from_row,
    evolving=frozenset(
        {
            "local_status",
            "exchange_status",
            "exchange_order_id",
            "updated_at_utc",
            "canceled_at_utc",
        }
    ),
)
_POSITION = _Spec(
    label="position",
    model=PositionRow,
    id_column="position_id",
    to_row=position_to_row,
    from_row=position_from_row,
    evolving=frozenset(
        {
            "quantity",
            "entry_price",
            "break_even_price",
            "unrealized_pnl",
            "realized_pnl",
            "updated_at_utc",
            "closed_at_utc",
            "status",
        }
    ),
)


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else "unknown constraint"


def _translate_integrity(
    exc: IntegrityError, label: str, entity_id: str
) -> PersistenceError | None:
    """Map a foreign key or unique violation to a typed error; None means re-raise as is."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    name = _constraint_name(exc)
    if sqlstate == _SQLSTATE_FOREIGN_KEY_VIOLATION:
        return ParentRowMissing(f"{label} {entity_id}: parent row missing ({name})")
    if sqlstate == _SQLSTATE_UNIQUE_VIOLATION:
        return RowConflict(f"{label} {entity_id}: unique constraint violated ({name})")
    return None


def _guard_precision(table: str, column: str, value: Decimal) -> None:
    """Refuse a Decimal that NUMERIC(38,18) would silently round (D-12, F-410)."""
    try:
        quantized = quantize_for_storage(value)
    except ValueError:
        raise PrecisionError(f"{table}.{column}: not a finite storable decimal") from None
    if quantized != value:
        raise PrecisionError(
            f"{table}.{column}: more than {STORAGE_DECIMAL_PLACES} fractional digits"
        )


def _row_values(row: object, model: type[Any]) -> dict[str, Any]:
    """Column values of a mapped row, after the precision guard on every NUMERIC column."""
    table = model.__table__
    values: dict[str, Any] = {}
    for column in table.columns:
        value = getattr(row, column.key)
        if isinstance(column.type, Numeric) and isinstance(value, Decimal):
            _guard_precision(table.name, column.key, value)
        values[column.key] = value
    return values


def _fetch[E, R](session: Session, spec: _Spec[E, R], entity_id: str) -> R | None:
    """Read the stored row, bypassing the identity map (another transaction may have written)."""
    id_attr = getattr(spec.model, spec.id_column)
    stmt: Any = (
        select(spec.model).where(id_attr == entity_id).execution_options(populate_existing=True)
    )
    row: R | None = session.execute(stmt).scalar_one_or_none()
    return row


def _lock[E, R](session: Session, spec: _Spec[E, R], entity_id: str) -> R:
    """`SELECT ... FOR UPDATE` the row; a missing row is a conflict (never created implicitly)."""
    id_attr = getattr(spec.model, spec.id_column)
    stmt: Any = (
        select(spec.model)
        .where(id_attr == entity_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row: R | None = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise RowConflict(f"{spec.label} {entity_id}: row does not exist")
    return row


def _insert[E, R](session: Session, spec: _Spec[E, R], entity: E, entity_id: str) -> None:
    """Idempotent insert with re-read comparison (see module docstring)."""
    values = _row_values(spec.to_row(entity), spec.model)
    id_attr = getattr(spec.model, spec.id_column)
    stmt: Any = (
        pg_insert(spec.model)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[spec.id_column])
        .returning(id_attr)
    )
    try:
        inserted = session.execute(stmt).first()
    except IntegrityError as exc:
        translated = _translate_integrity(exc, spec.label, entity_id)
        if translated is None:
            raise
        raise translated from exc
    if inserted is not None:
        return
    existing = _fetch(session, spec, entity_id)
    if existing is None:
        # Not reachable while the primary key holds; never guess (fail closed).
        raise RowConflict(f"{spec.label} {entity_id}: conflicting row not visible")
    differing = [
        name
        for name in values
        if name not in spec.evolving and getattr(existing, name) != values[name]
    ]
    if differing:
        raise RowConflict(
            f"{spec.label} {entity_id} already exists with different fields: {', '.join(differing)}"
        )


def _apply[E, R](
    session: Session,
    spec: _Spec[E, R],
    entity_id: str,
    status_column: str,
    old_status: str,
    changes: dict[str, Any],
) -> E:
    """Conditional UPDATE `WHERE <status column> = old`; exactly one row must change."""
    id_attr = getattr(spec.model, spec.id_column)
    status_attr = getattr(spec.model, status_column)
    stmt: Any = (
        update(spec.model).where(id_attr == entity_id, status_attr == old_status).values(**changes)
    )
    result: Any = session.execute(stmt)
    if result.rowcount != 1:
        raise RowConflict(f"{spec.label} {entity_id}: transition not applied")
    current = _fetch(session, spec, entity_id)
    if current is None:
        raise RowConflict(f"{spec.label} {entity_id}: row vanished during transition")
    return spec.from_row(current)


class PgTradingEntityStore:
    """Signal, TradePlan, Order, Fill and Position persistence with DOMN-04 enforcement."""

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

    # ------------------------------------------------------------------ signals

    def insert_signal(self, signal: Signal, *, tx: Session | None = None) -> None:
        """Insert a signal; replaying it is a no-op, a different signal is `RowConflict`."""
        with self._unit(tx) as session:
            _insert(session, _SIGNAL, signal, signal.signal_id)

    def get_signal(self, signal_id: str, *, tx: Session | None = None) -> Signal | None:
        with self._unit(tx) as session:
            row = _fetch(session, _SIGNAL, signal_id)
            return None if row is None else _SIGNAL.from_row(row)

    def transition_signal(
        self,
        signal_id: str,
        new_status: SignalStatus,
        *,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> Signal:
        """Move a signal along the DOMN-04 table inside one locked transaction.

        Raises:
            IllegalTransition: the move is not in the table; nothing is written.
            RowConflict: the signal does not exist.
        """
        with self._unit(tx) as session:
            row = _lock(session, _SIGNAL, signal_id)
            old_status = SignalStatus(row.status)
            if old_status is new_status:
                return _SIGNAL.from_row(row)
            assert_transition(TransitionKind.SIGNAL, old_status, new_status)
            changes: dict[str, Any] = {"status": new_status.value}
            if new_status is SignalStatus.INVALIDATED:
                changes["invalidated_at_utc"] = now_utc
            return _apply(session, _SIGNAL, signal_id, "status", old_status.value, changes)

    # -------------------------------------------------------------- trade plans

    def insert_trade_plan(self, plan: TradePlan, *, tx: Session | None = None) -> None:
        """Insert a plan after the precision guard; the signal must exist (`ParentRowMissing`)."""
        with self._unit(tx) as session:
            _insert(session, _TRADE_PLAN, plan, plan.trade_plan_id)

    def get_trade_plan(self, trade_plan_id: str, *, tx: Session | None = None) -> TradePlan | None:
        with self._unit(tx) as session:
            row = _fetch(session, _TRADE_PLAN, trade_plan_id)
            return None if row is None else _TRADE_PLAN.from_row(row)

    def transition_trade_plan(
        self,
        trade_plan_id: str,
        new_status: TradePlanStatus,
        *,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> TradePlan:
        """Move a trade plan along the DOMN-04 table (no timestamp side effect)."""
        del now_utc  # plans carry no transition timestamp; kept for a uniform signature
        with self._unit(tx) as session:
            row = _lock(session, _TRADE_PLAN, trade_plan_id)
            old_status = TradePlanStatus(row.status)
            if old_status is new_status:
                return _TRADE_PLAN.from_row(row)
            assert_transition(TransitionKind.TRADE_PLAN, old_status, new_status)
            return _apply(
                session,
                _TRADE_PLAN,
                trade_plan_id,
                "status",
                old_status.value,
                {"status": new_status.value},
            )

    # ------------------------------------------------------------------- orders

    def insert_order(self, order: Order, *, tx: Session | None = None) -> None:
        """Insert an order; its plan, position and parent order must exist already."""
        with self._unit(tx) as session:
            _insert(session, _ORDER, order, order.order_id)

    def get_order(self, order_id: str, *, tx: Session | None = None) -> Order | None:
        with self._unit(tx) as session:
            row = _fetch(session, _ORDER, order_id)
            return None if row is None else _ORDER.from_row(row)

    def transition_order(
        self,
        order_id: str,
        new_status: OrderStatus,
        *,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> Order:
        """Move an order along the DOMN-04 table; CANCELED also sets `canceled_at_utc`."""
        with self._unit(tx) as session:
            row = _lock(session, _ORDER, order_id)
            old_status = OrderStatus(row.local_status)
            if old_status is new_status:
                return _ORDER.from_row(row)
            assert_transition(TransitionKind.ORDER, old_status, new_status)
            changes: dict[str, Any] = {
                "local_status": new_status.value,
                "updated_at_utc": now_utc,
            }
            if new_status is OrderStatus.CANCELED:
                changes["canceled_at_utc"] = now_utc
            return _apply(session, _ORDER, order_id, "local_status", old_status.value, changes)

    # -------------------------------------------------------------------- fills

    def record_fill(self, fill: Fill, *, tx: Session | None = None) -> None:
        """Ingest a fill idempotently on `fill_id` and `(order_id, exchange_trade_id)`.

        Raises:
            RowConflict: a DIFFERENT fill already holds this id or this (order, trade) pair.
            ParentRowMissing: the order does not exist.
            PrecisionError: a Decimal has more than 18 fractional digits.
        """
        values = _row_values(fill_to_row(fill), FillRow)
        with self._unit(tx) as session:
            stmt: Any = (
                pg_insert(FillRow)
                .values(**values)
                .on_conflict_do_nothing()
                .returning(FillRow.fill_id)
            )
            try:
                inserted = session.execute(stmt).first()
            except IntegrityError as exc:
                translated = _translate_integrity(exc, "fill", fill.fill_id)
                if translated is None:
                    raise
                raise translated from exc
            if inserted is not None:
                return
            clash: Any = (
                select(FillRow)
                .where(
                    or_(
                        FillRow.fill_id == fill.fill_id,
                        and_(
                            FillRow.order_id == fill.order_id,
                            FillRow.exchange_trade_id == fill.exchange_trade_id,
                        ),
                    )
                )
                .execution_options(populate_existing=True)
            )
            rows = list(session.execute(clash).scalars())
            if len(rows) != 1:
                # Two different stored fills each clash on one arbiter, or none is visible.
                raise RowConflict(f"fill {fill.fill_id}: conflicts with a different stored fill")
            existing = rows[0]
            differing = [name for name in values if getattr(existing, name) != values[name]]
            if differing:
                raise RowConflict(
                    f"fill {fill.fill_id} already exists with different fields: "
                    f"{', '.join(differing)}"
                )

    def list_fills_for_order(self, order_id: str, *, tx: Session | None = None) -> list[Fill]:
        """Fills of one order ordered by `fill_time_utc` then `fill_id`."""
        with self._unit(tx) as session:
            stmt: Any = (
                select(FillRow)
                .where(FillRow.order_id == order_id)
                .order_by(FillRow.fill_time_utc, FillRow.fill_id)
                .execution_options(populate_existing=True)
            )
            return [fill_from_row(row) for row in session.execute(stmt).scalars()]

    # ---------------------------------------------------------------- positions

    def insert_position(self, position: Position, *, tx: Session | None = None) -> None:
        """Insert a position; replaying it is a no-op even after it was updated."""
        with self._unit(tx) as session:
            _insert(session, _POSITION, position, position.position_id)

    def get_position(self, position_id: str, *, tx: Session | None = None) -> Position | None:
        with self._unit(tx) as session:
            row = _fetch(session, _POSITION, position_id)
            return None if row is None else _POSITION.from_row(row)

    def transition_position(
        self,
        position_id: str,
        new_status: PositionStatus,
        *,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> Position:
        """Move a position along the DOMN-04 table; CLOSED also sets `closed_at_utc`."""
        with self._unit(tx) as session:
            row = _lock(session, _POSITION, position_id)
            old_status = PositionStatus(row.status)
            if old_status is new_status:
                return _POSITION.from_row(row)
            assert_transition(TransitionKind.POSITION, old_status, new_status)
            changes: dict[str, Any] = {"status": new_status.value, "updated_at_utc": now_utc}
            if new_status is PositionStatus.CLOSED:
                changes["closed_at_utc"] = now_utc
            return _apply(session, _POSITION, position_id, "status", old_status.value, changes)


__all__ = ["PgTradingEntityStore"]
