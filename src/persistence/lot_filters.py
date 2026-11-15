"""PostgreSQL store of the last validated lot filters (Phase 20, plan 20-18; Q3, D-21).

`PgLotFilterStore` keeps ONE row per symbol in `validated_lot_filters` (migration 0009): the
exchangeInfo filters `LotFilters` validated, with the time of that read.

  - `upsert` is `INSERT ... ON CONFLICT (symbol) DO UPDATE ... WHERE excluded.fetched_at_utc >=
    validated_lot_filters.fetched_at_utc`: a later (or equal) fetch replaces the row, an older
    one never does, so "last validated" is monotonic even if two readers race. The row's
    `updated_at_utc` is the fetch time of the write (the single writer is `LotFilterSource`).
  - `get` returns the row as `StoredLotFilters(filters_stale=True)`: whatever is read back from
    the store is stale by definition. A malformed row raises (`ValueError`/`TypeError` from
    `LotFilters`), and the caller treats that as "nothing stored" (fail closed).

Decimals go in and come out exactly (`NUMERIC(38, 18)`); times are UTC-aware. There is no delete
method. An unreachable database raises `StoreUnavailable` from the unit of work; there is no
retry loop here.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.db.models import ValidatedLotFiltersRow
from src.domain.lot_filters import LotFilters
from src.execution.lot_filter_source import StoredLotFilters
from src.persistence.uow import OperationalDatabase

_DECIMAL_COLUMNS = (
    "price_tick_size",
    "lot_min_quantity",
    "lot_max_quantity",
    "lot_step_size",
    "market_lot_min_quantity",
    "market_lot_max_quantity",
    "market_lot_step_size",
    "min_notional",
)


def _require_utc_aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC, got offset {value.utcoffset()}")
    return value


class PgLotFilterStore:
    """The last validated lot filters of each symbol, on PostgreSQL."""

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

    def upsert(
        self, filters: LotFilters, *, fetched_at_utc: datetime, tx: Session | None = None
    ) -> None:
        """Store `filters` as the symbol's last validated filters (newest fetch wins).

        Raises:
            ValueError: `fetched_at_utc` is not a UTC-aware datetime. Nothing is written.
        """
        fetched = _require_utc_aware(fetched_at_utc, "fetched_at_utc")
        values: dict[str, object] = {name: getattr(filters, name) for name in _DECIMAL_COLUMNS}
        values.update(symbol=filters.symbol, fetched_at_utc=fetched, updated_at_utc=fetched)
        insert = pg_insert(ValidatedLotFiltersRow).values(**values)
        update_set = {name: insert.excluded[name] for name in _DECIMAL_COLUMNS}
        update_set["fetched_at_utc"] = insert.excluded.fetched_at_utc
        update_set["updated_at_utc"] = insert.excluded.updated_at_utc
        statement = insert.on_conflict_do_update(
            index_elements=["symbol"],
            set_=update_set,
            where=ValidatedLotFiltersRow.fetched_at_utc <= insert.excluded.fetched_at_utc,
        )
        with self._unit(tx) as session:
            session.execute(statement)

    def get(self, symbol: str, *, tx: Session | None = None) -> StoredLotFilters | None:
        """The stored row of `symbol` flagged stale, or None when the symbol has none."""
        with self._unit(tx) as session:
            row = session.execute(
                select(ValidatedLotFiltersRow).where(ValidatedLotFiltersRow.symbol == symbol)
            ).scalar_one_or_none()
            if row is None:
                return None
            filters = LotFilters(
                symbol=row.symbol,
                price_tick_size=row.price_tick_size,
                lot_min_quantity=row.lot_min_quantity,
                lot_max_quantity=row.lot_max_quantity,
                lot_step_size=row.lot_step_size,
                market_lot_min_quantity=row.market_lot_min_quantity,
                market_lot_max_quantity=row.market_lot_max_quantity,
                market_lot_step_size=row.market_lot_step_size,
                min_notional=row.min_notional,
            )
            return StoredLotFilters(
                filters=filters, fetched_at_utc=row.fetched_at_utc, filters_stale=True
            )


__all__ = ["PgLotFilterStore"]
