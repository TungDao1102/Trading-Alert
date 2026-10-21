"""In-memory doubles of the validated lot-filter store (Phase 20, plan 20-18, D-21, Q3).

`InMemoryLotFilterStore` follows the `LotFilterStore` Protocol of `src.execution.lot_filter_source`
(one row per symbol, a later fetch replaces an earlier one, an older fetch never replaces a newer
one). `FailingLotFilterStore` raises on every call, for the fail-closed tests. Nothing here is an
exchange value: every number a test stores through it is TEST_ONLY.
"""

from __future__ import annotations

from datetime import datetime

from src.domain.lot_filters import LotFilters
from src.execution.lot_filter_source import StoredLotFilters


class InMemoryLotFilterStore:
    """The last validated filters of each symbol, with the fetch time."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[LotFilters, datetime]] = {}
        self.upserts: list[tuple[str, datetime]] = []

    def upsert(self, filters: LotFilters, *, fetched_at_utc: datetime) -> None:
        self.upserts.append((filters.symbol, fetched_at_utc))
        current = self.rows.get(filters.symbol)
        if current is not None and current[1] > fetched_at_utc:
            return
        self.rows[filters.symbol] = (filters, fetched_at_utc)

    def get(self, symbol: str) -> StoredLotFilters | None:
        row = self.rows.get(symbol)
        if row is None:
            return None
        return StoredLotFilters(filters=row[0], fetched_at_utc=row[1], filters_stale=True)


class FailingLotFilterStore:
    """A store whose database is down: every call raises."""

    def upsert(self, filters: LotFilters, *, fetched_at_utc: datetime) -> None:
        raise ConnectionError("TEST_ONLY store down")

    def get(self, symbol: str) -> StoredLotFilters | None:
        raise ConnectionError("TEST_ONLY store down")


__all__ = ["FailingLotFilterStore", "InMemoryLotFilterStore"]
