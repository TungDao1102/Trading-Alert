"""Fakes for the live daily-loss service (Phase 21, plan 21-13; plan 21-16 reuses them).

* ``InMemoryDayRiskStore`` mirrors the semantics of ``PgDayRiskStore`` (plan 21-09): ``open_day``
  returns the STORED row (the first base wins), ``latch_stop`` / ``mark_warning_alerted`` set
  their time once, ``add_components`` is idempotent per key and atomic (a different amount or
  asset raises ``RowConflict`` and stores nothing of that call), and there is no delete. It adds
  failure injection: ``raise_next(method, exc)`` makes the next call of that method raise.
* ``ScriptedDayRiskReader`` stands in for the adapter's ``user_trades_in_window`` and
  ``income_in_window``: it serves rows set per symbol (and one income tuple), records every call
  with its keyword arguments, and can fail a method (``fail``) or run a hook on each call.

TEST_ONLY helpers; nothing here is a project value and no figure is a mainnet figure.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Any

from src.persistence.errors import RowConflict
from src.risk.daily_loss import (
    DayRiskState,
    LossComponent,
    base_is_inside_day,
)

_ComponentKey = tuple[date, str, str, str]


class InMemoryDayRiskStore:
    """``DayRiskStorePort`` with the semantics of ``PgDayRiskStore`` and failure injection."""

    def __init__(self) -> None:
        self._days: dict[date, DayRiskState] = {}
        self._components: dict[_ComponentKey, LossComponent] = {}
        self._raise_next: dict[str, list[BaseException]] = {}
        self.calls: list[str] = []

    def raise_next(self, method: str, exc: BaseException) -> None:
        """The next call of ``method`` raises ``exc`` (queued; one failure per call)."""
        self._raise_next.setdefault(method, []).append(exc)

    def count(self, method: str) -> int:
        return self.calls.count(method)

    def _enter(self, method: str) -> None:
        self.calls.append(method)
        queue = self._raise_next.get(method)
        if queue:
            raise queue.pop(0)

    # ------------------------------------------------------------------ reads

    def get_day(self, utc_day: date) -> DayRiskState | None:
        self._enter("get_day")
        return self._days.get(utc_day)

    def has_day(self, utc_day: date) -> bool:
        self._enter("has_day")
        return utc_day in self._days

    def list_components(self, utc_day: date) -> tuple[LossComponent, ...]:
        self._enter("list_components")
        rows = [row for key, row in self._components.items() if key[0] == utc_day]
        rows.sort(key=lambda row: (row.kind.value, row.source.value, row.source_key))
        return tuple(rows)

    # ----------------------------------------------------------------- writes

    def open_day(self, state: DayRiskState) -> DayRiskState:
        self._enter("open_day")
        return self._days.setdefault(state.utc_day, state)

    def latch_stop(self, *, utc_day: date, at_utc: datetime) -> DayRiskState:
        self._enter("latch_stop")
        return self._stamp_once("stop_latched_at_utc", utc_day, at_utc)

    def mark_warning_alerted(self, *, utc_day: date, at_utc: datetime) -> DayRiskState:
        self._enter("mark_warning_alerted")
        return self._stamp_once("warning_alerted_at_utc", utc_day, at_utc)

    def _stamp_once(self, column: str, utc_day: date, at_utc: datetime) -> DayRiskState:
        if not base_is_inside_day(utc_day=utc_day, observed_at_utc=at_utc):
            raise ValueError(f"{column} {at_utc.isoformat()} is outside UTC day {utc_day}")
        stored = self._days.get(utc_day)
        if stored is None:
            raise RowConflict(f"daily_risk_days {utc_day}: no stored state to set {column}")
        if getattr(stored, column) is None:
            stored = DayRiskState(
                utc_day=stored.utc_day,
                equity_at_day_start=stored.equity_at_day_start,
                base_observed_at_utc=stored.base_observed_at_utc,
                stop_latched_at_utc=(
                    at_utc if column == "stop_latched_at_utc" else stored.stop_latched_at_utc
                ),
                warning_alerted_at_utc=(
                    at_utc if column == "warning_alerted_at_utc" else stored.warning_alerted_at_utc
                ),
            )
            self._days[utc_day] = stored
        return stored

    def add_components(self, components: Iterable[LossComponent]) -> int:
        self._enter("add_components")
        pending: dict[_ComponentKey, LossComponent] = {}
        inserted = 0
        for component in components:
            key = (
                component.utc_day,
                component.kind.value,
                component.source.value,
                component.source_key,
            )
            stored = self._components.get(key) or pending.get(key)
            if stored is None:
                pending[key] = component
                inserted += 1
            elif stored.amount != component.amount or stored.asset != component.asset:
                raise RowConflict(f"daily_loss_components {key} already stored differently")
        self._components.update(pending)
        return inserted


class ScriptedDayRiskReader:
    """``DayRiskReadPort`` serving set rows; every call is recorded with its keyword arguments."""

    def __init__(
        self,
        *,
        trades: dict[str, tuple[Any, ...]] | None = None,
        income: tuple[Any, ...] = (),
        on_call: Callable[[str], None] | None = None,
    ) -> None:
        self.trades: dict[str, tuple[Any, ...]] = dict(trades or {})
        self.income: tuple[Any, ...] = income
        self._on_call = on_call
        self._failures: dict[str, BaseException] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def fail(self, method: str, exc: BaseException | None) -> None:
        """Make ``method`` raise ``exc`` on every call (``None`` clears the failure)."""
        if exc is None:
            self._failures.pop(method, None)
        else:
            self._failures[method] = exc

    def count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)

    def _enter(self, method: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((method, kwargs))
        if self._on_call is not None:
            self._on_call(method)
        failure = self._failures.get(method)
        if failure is not None:
            raise failure

    async def user_trades_in_window(
        self, *, symbol: str, start_utc: datetime, end_utc: datetime
    ) -> tuple[Any, ...]:
        self._enter(
            "user_trades_in_window",
            {"symbol": symbol, "start_utc": start_utc, "end_utc": end_utc},
        )
        return self.trades.get(symbol, ())

    async def income_in_window(
        self, *, income_type: str, start_utc: datetime, end_utc: datetime
    ) -> tuple[Any, ...]:
        self._enter(
            "income_in_window",
            {"income_type": income_type, "start_utc": start_utc, "end_utc": end_utc},
        )
        return self.income


__all__ = ["InMemoryDayRiskStore", "ScriptedDayRiskReader"]
