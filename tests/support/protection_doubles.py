"""Test doubles for the fill-driven protection coordinator (plan 19-11).

Nothing here is Binance data and no value is a chosen threshold: the prices, quantities and the
snapshot TTL are TEST_ONLY numbers that only make a consistent `RestingEntry`. No production
code imports this module.

* `RecordingAlerts` records every `critical(...)` call of the `CriticalAlertSink` Protocol.
* `ScriptedEmergencyCloser` answers `close_position(...)` from a script (True means "REST shows
  the position flat") and records each call. The happy path of plan 19-11 never calls it; the
  branch tests of plan 19-14 do.
* `RecordingSafeMode` is the duck-typed SAFE_MODE controller (`enter_safe_mode`).
* `resting_entry_for_tests(**overrides)` builds one consistent BTCUSDT LONG `RestingEntry`.
* `make_rig(...)` wires a `ProtectionCoordinator` over the Phase 19 fake exchange (constructed
  with `enforce_flat_stop_rejection=True`), an in-memory intent store behind an event log,
  a recording journal and virtual time, with the entry placed on the fake and registered.
  With `real_closer=True` (plan 19-14) the coordinator gets the real `MarketEmergencyCloser`
  over the same fake (fake lot filters set, sharing the journal, SAFE_MODE and alerts) instead of
  the scripted closer, so a failure-branch test ends in a real reduce-only MARKET close.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.adapters.binance_userdata_router import FillSource, RoutedFill
from src.domain.lot_filters import LotFilters
from src.execution.constraint_snapshot import PlanConstraintSnapshot
from src.execution.emergency_close import MarketEmergencyCloser
from src.execution.execution_limits import ExecutionLimits
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.protection import ProtectionCoordinator, RestingEntry

from tests.support.execution_limits import test_only_execution_limits
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.stream_sinks import RecordingJournal
from tests.support.virtual_time import VirtualTime

TEST_ONLY_PLAN_HASH = "a1" * 32
TEST_ONLY_SYMBOL = "BTCUSDT"
TEST_ONLY_APPROVAL_ID = "approval-protection-0001"
TEST_ONLY_TRADE_PLAN_ID = "plan-protection-0001"
# TEST_ONLY snapshot TTL (the parameter set value is not read here).
TEST_ONLY_SNAPSHOT_TTL = timedelta(seconds=600)
TEST_ONLY_REGISTERED_AT = datetime(2026, 10, 16, 11, 59, 0, tzinfo=UTC)


@dataclass(frozen=True)
class RecordedAlert:
    event: str
    plan_hash: str
    symbol: str
    reason: str
    now_utc: datetime


@dataclass
class RecordingAlerts:
    """`CriticalAlertSink` that records each critical alert."""

    alerts: list[RecordedAlert] = field(default_factory=list)

    def critical(
        self, *, event: str, plan_hash: str, symbol: str, reason: str, now_utc: datetime
    ) -> None:
        self.alerts.append(
            RecordedAlert(
                event=event, plan_hash=plan_hash, symbol=symbol, reason=reason, now_utc=now_utc
            )
        )


class ScriptedEmergencyCloser:
    """`EmergencyCloser` answering from a script; an exhausted script answers False."""

    def __init__(self, results: Iterable[bool] = ()) -> None:
        self._results: deque[bool] = deque(results)
        self.calls: list[dict[str, Any]] = []

    async def close_position(self, *, entry: RestingEntry, reason: str) -> bool:
        self.calls.append({"entry": entry, "reason": reason})
        return self._results.popleft() if self._results else False


class RecordingSafeMode:
    """Duck-typed SAFE_MODE controller recording each entry reason."""

    def __init__(self) -> None:
        self.entered_reasons: list[str] = []
        self.in_safe_mode = False

    def enter_safe_mode(self, *, reason: str, now_utc: Any = None) -> None:
        self.entered_reasons.append(reason)
        self.in_safe_mode = True


def lot_filters_for_tests() -> LotFilters:
    """FAKE BTCUSDT lot filters (TEST_ONLY numbers, not exchangeInfo) for the real closer."""
    return LotFilters(
        symbol=TEST_ONLY_SYMBOL,
        price_tick_size=Decimal("0.01"),
        lot_min_quantity=Decimal("0.001"),
        lot_max_quantity=Decimal("1000"),
        lot_step_size=Decimal("0.001"),
        market_lot_min_quantity=Decimal("0.001"),
        market_lot_max_quantity=Decimal("120"),
        market_lot_step_size=Decimal("0.001"),
        min_notional=Decimal("100"),
    )


def complete_constraint_snapshot(**overrides: Any) -> PlanConstraintSnapshot:
    """A COMPLETE `PlanConstraintSnapshot` of BTCUSDT (every live input known)."""
    fields: dict[str, Any] = {
        "trade_plan_id": TEST_ONLY_TRADE_PLAN_ID,
        "symbol": TEST_ONLY_SYMBOL,
        "price_tick_size": Decimal("0.01"),
        "quantity_step_size": Decimal("0.001"),
        "min_quantity": Decimal("0.001"),
        "max_quantity": Decimal("1000"),
        "min_notional": Decimal("100"),
        "market_lot_min_quantity": Decimal("0.001"),
        "market_lot_max_quantity": Decimal("120"),
        "market_lot_step_size": Decimal("0.001"),
        "percent_price_multiplier_up": Decimal("1.05"),
        "percent_price_multiplier_down": Decimal("0.95"),
        "percent_price_multiplier_decimals": 4,
        "working_type": "MARK_PRICE",
        "margin_type": "ISOLATED",
        "leverage": 3,
        "equity_used": Decimal("1000"),
        "constraints_observed_at_utc": TEST_ONLY_REGISTERED_AT,
        "captured_at_utc": TEST_ONLY_REGISTERED_AT,
    }
    fields.update(overrides)
    return PlanConstraintSnapshot(**fields)


def resting_entry_for_tests(**overrides: Any) -> RestingEntry:
    """One consistent BTCUSDT LONG resting entry (0.010 at a TEST_ONLY level); override by field."""
    plan_hash = overrides.get("plan_hash", TEST_ONLY_PLAN_HASH)
    fields: dict[str, Any] = {
        "approval_id": TEST_ONLY_APPROVAL_ID,
        "trade_plan_id": TEST_ONLY_TRADE_PLAN_ID,
        "plan_hash": plan_hash,
        "symbol": TEST_ONLY_SYMBOL,
        "side": "LONG",
        "entry_side": "BUY",
        "exit_side": "SELL",
        "entry_client_order_id": derive_client_order_id(plan_hash=plan_hash, role="ENTRY"),
        "entry_quantity": Decimal("0.010"),
        "sl_trigger_price": Decimal("59000.00"),
        "tp1_trigger_price": Decimal("62000.00"),
        "tp2_trigger_price": Decimal("64000.00"),
        "tp1_quantity_fraction": Decimal("0.5"),
        "working_type": "MARK_PRICE",
        "position_mode": "ONE_WAY",
        "plan_constraint_snapshot": complete_constraint_snapshot(),
        "snapshot_ttl": TEST_ONLY_SNAPSHOT_TTL,
        "registered_at_utc": TEST_ONLY_REGISTERED_AT,
    }
    fields.update(overrides)
    return RestingEntry(**fields)


class LoggingStore:
    """Delegates to an `InMemoryExecutionIntentStore` and appends each call to a shared log."""

    def __init__(self, inner: InMemoryExecutionIntentStore, log: list[str]) -> None:
        self._inner = inner
        self._log = log

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            if "role" in kwargs:
                self._log.append(f"store.{name}:{kwargs['role']}")
            else:
                self._log.append(f"store.{name}")
            return target(*args, **kwargs)

        return call


@dataclass
class ProtectionRig:
    """Everything one protection test touches (see `make_rig`)."""

    fake: BinanceSemanticsFakeAdapter
    inner_store: InMemoryExecutionIntentStore
    journal: RecordingJournal
    safe_mode: RecordingSafeMode
    alerts: RecordingAlerts
    closer: ScriptedEmergencyCloser | MarketEmergencyCloser
    clock: VirtualTime
    coordinator: ProtectionCoordinator
    entry: RestingEntry
    log: list[str]

    @property
    def stop_id(self) -> str:
        return derive_algo_client_id(plan_hash=self.entry.plan_hash, role="STOP_LOSS")

    @property
    def entry_id(self) -> str:
        return self.entry.entry_client_order_id

    def stream_fill(
        self,
        quantity: Decimal,
        *,
        after_gap: bool = False,
        source: FillSource = FillSource.USER_DATA_EVENT,
    ) -> RoutedFill:
        """The exchange fills the entry by `quantity`; returns the stream view of that fill."""
        self.fake.fill(self.entry_id, quantity=quantity)
        return RoutedFill(fill=self.fake.fill_events[-1], source=source, after_gap=after_gap)

    def stop_row(self) -> Any:
        return self.inner_store.get_intent(approval_id=self.entry.approval_id, role="STOP_LOSS")

    def transitions(self) -> list[tuple[str, str]]:
        """The journaled (from, to) pairs in recording order."""
        import json

        return [
            (json.loads(e.payload_json)["from"], json.loads(e.payload_json)["to"])
            for e in self.journal.calls
            if e.event_type == "PROTECTION_TRANSITION"
        ]


async def make_rig(
    *,
    limits: ExecutionLimits | None = None,
    place_entry: bool = True,
    register: bool = True,
    real_closer: bool = False,
    **entry_overrides: Any,
) -> ProtectionRig:
    """A coordinator over the fake exchange; the entry is placed on the fake and registered."""
    clock = VirtualTime()
    fake = BinanceSemanticsFakeAdapter(now_utc=clock.now(), enforce_flat_stop_rejection=True)
    log: list[str] = []
    _log_adapter_calls(fake, log)
    inner = InMemoryExecutionIntentStore()
    journal = RecordingJournal()
    safe_mode = RecordingSafeMode()
    alerts = RecordingAlerts()
    closer: ScriptedEmergencyCloser | MarketEmergencyCloser
    if real_closer:
        fake.set_lot_filters(TEST_ONLY_SYMBOL, lot_filters_for_tests())
        closer = MarketEmergencyCloser(
            adapter=fake,
            journal=journal,
            safe_mode_controller=safe_mode,
            alert_sink=alerts,
            clock=clock,
        )
    else:
        closer = ScriptedEmergencyCloser()
    entry = resting_entry_for_tests(**entry_overrides)
    coordinator = ProtectionCoordinator(
        adapter=fake,
        intent_store=LoggingStore(inner, log),  # type: ignore[arg-type]
        journal=journal,
        safe_mode_controller=safe_mode,
        alert_sink=alerts,
        emergency_closer=closer,
        limits=limits if limits is not None else test_only_execution_limits(),
        clock=clock,
    )
    if place_entry:
        await fake.place_entry(
            symbol=entry.symbol,
            side=entry.entry_side,
            position_side="BOTH",
            time_in_force="GTC",
            quantity=entry.entry_quantity,
            price=Decimal("60000.00"),
            new_client_order_id=entry.entry_client_order_id,
        )
    if register:
        coordinator.register_resting_entry(entry)
    return ProtectionRig(
        fake=fake,
        inner_store=inner,
        journal=journal,
        safe_mode=safe_mode,
        alerts=alerts,
        closer=closer,
        clock=clock,
        coordinator=coordinator,
        entry=entry,
        log=log,
    )


def _log_adapter_calls(fake: BinanceSemanticsFakeAdapter, log: list[str]) -> None:
    """Wrap the order-changing adapter methods so the shared log shows when each one starts."""
    for name in ("place_algo_protective", "cancel_normal_order"):
        original = getattr(fake, name)

        async def wrapper(*, _name: str = name, _original: Any = original, **kwargs: Any) -> Any:
            log.append(f"adapter.{_name}")
            return await _original(**kwargs)

        setattr(fake, name, wrapper)


__all__ = [
    "LoggingStore",
    "ProtectionRig",
    "make_rig",
    "TEST_ONLY_APPROVAL_ID",
    "TEST_ONLY_PLAN_HASH",
    "TEST_ONLY_REGISTERED_AT",
    "TEST_ONLY_SNAPSHOT_TTL",
    "TEST_ONLY_SYMBOL",
    "TEST_ONLY_TRADE_PLAN_ID",
    "RecordedAlert",
    "RecordingAlerts",
    "RecordingSafeMode",
    "ScriptedEmergencyCloser",
    "complete_constraint_snapshot",
    "lot_filters_for_tests",
    "resting_entry_for_tests",
]
