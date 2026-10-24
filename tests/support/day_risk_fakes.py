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
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.execution.account_equity import LiveEquitySource
from src.execution.day_risk_service import LiveDayRiskService
from src.persistence.errors import RowConflict
from src.risk.daily_loss import (
    DayRiskState,
    FundingPolicy,
    LossComponent,
    base_is_inside_day,
)

from tests.support.account_fakes import (
    BALANCES,
    CONFIG,
    INFORMATION,
    ScriptedAccountReader,
    demo_account_snapshots,
)
from tests.support.execution_limits import test_only_execution_limits
from tests.support.virtual_time import VirtualTime

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

    def has_earlier_day(self, utc_day: date) -> bool:
        self._enter("has_earlier_day")
        return any(day < utc_day for day in self._days)

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
        income_by_type: dict[str, tuple[Any, ...]] | None = None,
        on_call: Callable[[str], None] | None = None,
    ) -> None:
        self.trades: dict[str, tuple[Any, ...]] = dict(trades or {})
        # ``income`` is the FUNDING_FEE answer; ``income_by_type`` serves any other income type
        # (REALIZED_PNL, COMMISSION, INSURANCE_CLEAR for the WR-09 cross-check). Unset: no rows.
        self.income: tuple[Any, ...] = income
        self.income_by_type: dict[str, tuple[Any, ...]] = dict(income_by_type or {})
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
        if income_type == "FUNDING_FEE":
            return self.income
        return self.income_by_type.get(income_type, ())


TEST_ONLY_PARAMETER_SET: dict[str, Any] = {
    "daily_loss_warning_threshold": Decimal("0.005"),
    "daily_loss_stop_threshold": Decimal("0.01"),
    "cluster_cap": Decimal("0.006"),
    "max_aggregate_open_risk": Decimal("0.01"),
    "max_open_positions": 2,
}


@dataclass
class DayRiskRig:
    """A service over the fakes and the recorded-Demo account snapshots (plan 21-16 tests)."""

    service: LiveDayRiskService
    store: InMemoryDayRiskStore
    reader: ScriptedDayRiskReader
    clock: VirtualTime


async def build_day_risk_rig(
    *,
    start: datetime,
    reader: ScriptedDayRiskReader | None = None,
    store: InMemoryDayRiskStore | None = None,
    policy: FundingPolicy = FundingPolicy.TRADES_WITH_UNVERIFIED_FUNDING,
) -> DayRiskRig:
    """One service on a virtual clock at ``start``; the day base is the recorded Demo equity."""
    clock = VirtualTime(start)
    information, balances, config = await demo_account_snapshots()
    account = ScriptedAccountReader(
        {CONFIG: [config], INFORMATION: [information], BALANCES: [balances]},
        virtual_time=clock,
        advance_seconds_per_call=0,
    )
    source = LiveEquitySource(
        adapter=account, clock=clock, limits=test_only_execution_limits(), quote_asset="USDT"
    )
    day_store = store if store is not None else InMemoryDayRiskStore()
    day_reader = reader if reader is not None else ScriptedDayRiskReader()
    service = LiveDayRiskService(
        reader=day_reader,
        store=day_store,
        equity=source,
        clock=clock,
        symbols={"BTCUSDT"},
        quote_asset="USDT",
        funding_policy=policy,
        parameter_set=TEST_ONLY_PARAMETER_SET,
    )
    return DayRiskRig(service, day_store, day_reader, clock)


__all__ = [
    "TEST_ONLY_PARAMETER_SET",
    "DayRiskRig",
    "InMemoryDayRiskStore",
    "ScriptedDayRiskReader",
    "build_day_risk_rig",
]
