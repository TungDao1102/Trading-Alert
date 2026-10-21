"""Where lot filters come from, and who may use stale ones (Phase 20, plan 20-18; Q3, D-21).

Owner decision Q3 (2026-10-20, option b): when exchangeInfo cannot be read during an emergency
close, the closer MAY size its parts from the last validated MARKET_LOT_SIZE filters of that
symbol, flagged stale with their fetch time. A NEW ENTRY NEVER MAY. With no valid stored filters
nothing is guessed: the close fails closed (``LotFiltersUnavailable``; the closer reports
``LOT_FILTERS_UNAVAILABLE``, SAFE_MODE and the critical alert stay).

``LotFilterSource`` is the one object that knows the difference:

* ``for_entry(symbol)`` reads the exchange live and returns ``LotFilters``. It NEVER returns a
  stored row, whatever the store holds and whatever the live read does: a failed read raises.
* ``for_emergency_close(symbol)`` is called ONLY from ``src/execution/emergency_close.py`` (an AST
  test pins it). It reads live first and stores the result as the symbol's last validated
  filters. When the live read fails it returns, in this order, the stored row, then (tier 2) the
  filters of the plan's persisted ``PlanConstraintSnapshot`` when every market-lot field and the
  maximum quantity are present; both are flagged ``filters_stale=True`` with their time. Nothing
  else is ever returned: no default, no invented value.
* ``refresh_if_due(symbol, now_utc=...)`` keeps the stored row fresh on the configured cadence
  (``reconcile.lot_filter_refresh_interval_ms``); the reconcile tick that calls it is plan 20-21.

A live read that succeeds is stored best-effort: a failing store must never turn a good live
read into a failed close, so a write error is only remembered (``last_store_error_type``).
A failing store READ is "no stored filters" (fail closed to the next tier). The REST gate is not
bypassed anywhere: a read refused by a 429/418 pause is a failed read like any other, and the
close that follows is gated by the adapter exactly as before (D-18).

Purity: stdlib, ``src.domain`` and ``src.execution``; no SDK, no ``src.persistence``, no float, no
sleep, and no clock other than the injected one. An exception's message is never read: only its
type name is kept.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from src.domain.lot_filters import LotFilters
from src.execution.constraint_snapshot import PlanConstraintSnapshot
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.execution.lot_split import lot_filters_from_plan_snapshot

_REFRESH_KEY = "reconcile.lot_filter_refresh_interval_ms"
_ONE_MS = timedelta(milliseconds=1)
_INVALID_FILTERS = "InvalidFilters"


class LotFiltersUnavailable(Exception):  # noqa: N818 - a state of the world, not a bug
    """No valid lot filters exist for this use: nothing is guessed (fail closed).

    ``error_type`` is the type name of the failed live read (or ``InvalidFilters`` when the
    adapter answered something that is not ``LotFilters``); never a message.
    """

    def __init__(self, error_type: str | None = None) -> None:
        self.error_type = error_type
        super().__init__("lot filters unavailable")


def _require_utc_aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC-aware")
    return value


@dataclass(frozen=True, kw_only=True)
class StoredLotFilters:
    """Filters with the time the exchange (or the plan snapshot) last vouched for them.

    ``filters_stale`` is False only for a live read made just now; every record read back from
    the store or the plan snapshot is stale by definition.
    """

    filters: LotFilters
    fetched_at_utc: datetime
    filters_stale: bool

    def __post_init__(self) -> None:
        if not isinstance(self.filters, LotFilters):
            raise TypeError("filters must be LotFilters")
        _require_utc_aware(self.fetched_at_utc, "fetched_at_utc")
        if not isinstance(self.filters_stale, bool):
            raise TypeError("filters_stale must be a bool")


class LotFilterStore(Protocol):
    """The last validated filters of each symbol (one row per symbol).

    ``upsert`` keeps the newest fetch: an older ``fetched_at_utc`` never replaces a newer row.
    ``get`` returns the row flagged ``filters_stale=True``, or None when the symbol has none.
    """

    def upsert(self, filters: LotFilters, *, fetched_at_utc: datetime) -> None: ...

    def get(self, symbol: str) -> StoredLotFilters | None: ...


class LotFilterAdapter(Protocol):
    """The one adapter method the source calls."""

    async def symbol_lot_filters(self, *, symbol: str) -> Any: ...


SnapshotFor = Callable[[str], PlanConstraintSnapshot | None]


class LotFilterSource:
    """Live lot filters for entries; live-then-stale lot filters for the emergency close."""

    def __init__(
        self,
        *,
        adapter: LotFilterAdapter,
        store: LotFilterStore,
        limits: ExecutionLimits,
        clock: Callable[[], datetime],
        snapshot_for: SnapshotFor | None = None,
    ) -> None:
        interval_ms = limits.reconcile_lot_filter_refresh_interval_ms
        if interval_ms is None:
            raise ExecutionLimitsNotConfigured((_REFRESH_KEY,))
        self._refresh_interval = interval_ms * _ONE_MS
        self._adapter = adapter
        self._store = store
        self._clock = clock
        self._snapshot_for = snapshot_for
        self.last_store_error_type: str | None = None

    # ------------------------------------------------------------------ #
    # Live read, shared by every path.
    # ------------------------------------------------------------------ #

    async def _read_live(self, symbol: str) -> LotFilters:
        try:
            result = await self._adapter.symbol_lot_filters(symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - any failed read is "no live filters"
            raise LotFiltersUnavailable(type(exc).__name__) from exc
        if not isinstance(result, LotFilters) or result.symbol != symbol:
            raise LotFiltersUnavailable(_INVALID_FILTERS)
        return result

    def _remember(self, filters: LotFilters, fetched_at_utc: datetime) -> bool:
        """Store a validated live read; a store failure is remembered, never raised."""
        try:
            self._store.upsert(filters, fetched_at_utc=fetched_at_utc)
        except Exception as exc:  # noqa: BLE001 - the live read is still good
            self.last_store_error_type = type(exc).__name__
            return False
        self.last_store_error_type = None
        return True

    # ------------------------------------------------------------------ #
    # The two uses.
    # ------------------------------------------------------------------ #

    async def for_entry(self, symbol: str) -> LotFilters:
        """Live filters for a new entry. Never a stored row; a failed read raises."""
        filters = await self._read_live(symbol)
        self._remember(filters, self._clock())
        return filters

    async def for_emergency_close(
        self, symbol: str, *, trade_plan_id: str | None = None
    ) -> StoredLotFilters:
        """Filters for the emergency close only (Q3, D-21); see the module docstring.

        Order: the live read; the stored last validated filters; the persisted plan snapshot of
        ``trade_plan_id`` (tier 2); else ``LotFiltersUnavailable`` (nothing is guessed).
        """
        try:
            filters = await self._read_live(symbol)
        except LotFiltersUnavailable as live_failure:
            fallback = self._stored(symbol) or self._from_plan_snapshot(symbol, trade_plan_id)
            if fallback is not None:
                return fallback
            raise live_failure
        fetched_at = self._clock()
        self._remember(filters, fetched_at)
        return StoredLotFilters(filters=filters, fetched_at_utc=fetched_at, filters_stale=False)

    def _stored(self, symbol: str) -> StoredLotFilters | None:
        try:
            row = self._store.get(symbol)
        except Exception as exc:  # noqa: BLE001 - an unreadable store is "nothing stored"
            self.last_store_error_type = type(exc).__name__
            return None
        if row is None or row.filters.symbol != symbol:
            return None
        return StoredLotFilters(
            filters=row.filters, fetched_at_utc=row.fetched_at_utc, filters_stale=True
        )

    def _from_plan_snapshot(
        self, symbol: str, trade_plan_id: str | None
    ) -> StoredLotFilters | None:
        """Tier 2: the plan's persisted snapshot, only when it holds every value the close needs.

        ``lot_filters_from_plan_snapshot`` answers None unless the maximum quantity and all three
        MARKET_LOT_SIZE values are present; a snapshot of another symbol, a failing lookup and an
        invalid value are all "nothing" (fail closed).
        """
        if self._snapshot_for is None or trade_plan_id is None:
            return None
        try:
            snapshot = self._snapshot_for(trade_plan_id)
            if snapshot is None or snapshot.symbol != symbol:
                return None
            filters = lot_filters_from_plan_snapshot(snapshot)
        except Exception as exc:  # noqa: BLE001 - an unreadable or invalid snapshot is nothing
            self.last_store_error_type = type(exc).__name__
            return None
        if filters is None:
            return None
        return StoredLotFilters(
            filters=filters, fetched_at_utc=snapshot.constraints_observed_at_utc, filters_stale=True
        )


__all__ = [
    "LotFilterAdapter",
    "LotFilterSource",
    "LotFilterStore",
    "LotFiltersUnavailable",
    "SnapshotFor",
    "StoredLotFilters",
]
