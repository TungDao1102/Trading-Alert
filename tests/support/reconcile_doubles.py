"""Journal doubles for the risk-first / spill tests (Phase 20, plan 20-08).

Three duck-typed journals with the one surface every controller uses, `record(event)`:

- `RaisingJournal`: every `record` call raises (a database outage that never ends).
- `RecordingJournal`: keeps events by id with the real journal's replay rule: the same id with
  the same identity fields is a no-op, the same id with different fields raises
  `JournalConflict`. `get(id)` mirrors `PgJournalStore.get`.
- `FlakyJournal`: fails the first `fail_times` calls, then behaves like `RecordingJournal`.

None of them touches a database or the network.

Plan 20-12 adds the doubles of the reconcile loop: `RecordingAlertSink`, `FakeGate`,
`FakeProtectionView`, `FakeReconcileAdapter`, `InMemorySafeModeStore`, `FakeIntentStore` and five row builders
(`make_position`, `make_open_order`, `make_algo_order`, `make_plan_protection`,
`make_intent_record`). The adapter
double raises on any method whose name starts with `place_` or `new_` and records the attempt,
so a loop that tried to place an order would fail the test by construction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.adapters.binance_usdm import (
    AlgoOrderProbe,
    OpenAlgoOrderSnapshot,
    OpenOrderSnapshot,
    PositionSnapshot,
)
from src.domain.journal import JournalEvent
from src.persistence.errors import JournalConflict, StoreUnavailable

# Same identity fields the real journal compares on a replay (src/persistence/journal.py).
_IDENTITY_FIELDS: tuple[str, ...] = (
    "event_type",
    "entity_type",
    "entity_id",
    "correlation_id",
    "signal_id",
    "trade_plan_id",
    "approval_id",
    "order_id",
    "position_id",
    "payload_json",
)


class RaisingJournal:
    """A journal whose `record` always raises `StoreUnavailable`."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self._exc = exc
        self.attempts = 0

    def record(self, event: JournalEvent) -> None:
        self.attempts += 1
        raise self._exc or StoreUnavailable("PostgreSQL unavailable during transaction")


class RecordingJournal:
    """An in-memory journal with the real replay rule (identical no-op, different conflict)."""

    def __init__(self) -> None:
        self.events: list[JournalEvent] = []
        self.attempts = 0
        self._by_id: dict[str, JournalEvent] = {}

    def record(self, event: JournalEvent) -> None:
        self.attempts += 1
        existing = self._by_id.get(event.journal_event_id)
        if existing is None:
            self._by_id[event.journal_event_id] = event
            self.events.append(event)
            return
        differing = [n for n in _IDENTITY_FIELDS if getattr(existing, n) != getattr(event, n)]
        if differing:
            raise JournalConflict(
                f"journal event {event.journal_event_id} already exists with different "
                f"fields: {', '.join(differing)}"
            )

    def get(self, journal_event_id: str) -> JournalEvent | None:
        return self._by_id.get(journal_event_id)

    def preload(self, event: JournalEvent) -> None:
        """Put an event in the journal without counting an attempt (test setup)."""
        self._by_id[event.journal_event_id] = event
        self.events.append(event)


class FlakyJournal(RecordingJournal):
    """Fails the first `fail_times` `record` calls with `StoreUnavailable`, then records."""

    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self._remaining_failures = fail_times

    def record(self, event: JournalEvent) -> None:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            self.attempts += 1
            raise StoreUnavailable("PostgreSQL unavailable during transaction")
        super().record(event)


# --------------------------------------------------------------------------- #
# Plan 20-12: doubles of the reconcile loop.
# --------------------------------------------------------------------------- #

_T0 = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class AlertCall:
    """One call of `ReconcileAlertSink.alert`, keywords kept verbatim."""

    event: str
    subject: str
    reason: str
    now_utc: datetime
    plan_hash: str | None
    symbol: str | None


class RecordingAlertSink:
    """Keeps every alert; `fail_with` makes every call raise after it is counted."""

    def __init__(self, *, fail_with: BaseException | None = None) -> None:
        self.alerts: list[AlertCall] = []
        self.attempts = 0
        self._fail_with = fail_with

    def alert(
        self,
        *,
        event: str,
        subject: str,
        reason: str,
        now_utc: datetime,
        plan_hash: str | None = None,
        symbol: str | None = None,
    ) -> None:
        self.attempts += 1
        if self._fail_with is not None:
            raise self._fail_with
        self.alerts.append(
            AlertCall(
                event=event,
                subject=subject,
                reason=reason,
                now_utc=now_utc,
                plan_hash=plan_hash,
                symbol=symbol,
            )
        )


class FakeGate:
    """A REST gate whose `restriction()` returns what the test set (None = no restriction)."""

    def __init__(self, restriction: Any = None, *, raises: BaseException | None = None) -> None:
        self.current = restriction
        self.raises = raises
        self.calls = 0

    def restriction(self) -> Any:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.current


class FakeProtectionView:
    """The coordinator's reconcile hooks: `protections()`, `notify_divergence`, `restore_complete`.

    `known` is the set of plan hashes `notify_divergence` answers True for; by default every
    plan handed to the constructor. `notified` records `(plan_hash, kind)` in call order.
    """

    def __init__(
        self,
        plans: Iterable[Any] = (),
        *,
        restore_complete: bool = True,
        known: Iterable[str] | None = None,
        protections_raises: BaseException | None = None,
        notify_raises: BaseException | None = None,
    ) -> None:
        self._plans = tuple(plans)
        self.restore_complete = restore_complete
        self._known = (
            frozenset(p.plan_hash for p in self._plans) if known is None else frozenset(known)
        )
        self._protections_raises = protections_raises
        self._notify_raises = notify_raises
        self.notified: list[tuple[str, str]] = []
        self.protections_calls = 0

    def protections(self) -> tuple[Any, ...]:
        self.protections_calls += 1
        if self._protections_raises is not None:
            raise self._protections_raises
        return self._plans

    def notify_divergence(self, plan_hash: str, kind: str) -> bool:
        self.notified.append((plan_hash, kind))
        if self._notify_raises is not None:
            raise self._notify_raises
        return plan_hash in self._known


class InMemorySafeModeStore:
    """A `SafeModeStateStore` that keeps every saved state (so `is_durable` is True)."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def save(self, state: Mapping[str, Any], *, now_utc: datetime) -> None:
        self.saved.append(dict(state))

    def load(self) -> Mapping[str, Any] | None:
        return self.saved[-1] if self.saved else None


class FakeReconcileAdapter:
    """The three snapshots, the algo probe and the cancels a reconcile tick may use.

    Every call is recorded in `calls` by method name. `fail` maps a method name to the exception
    it raises. A method whose name starts with `place_` or `new_` is not defined: reaching it
    records the attempt in `forbidden_calls` and raises AssertionError (the reconciler places
    nothing). `cancel_normal_order` is recorded too: a tick must never cancel a normal order.
    `pause` (an asyncio.Event) holds the first read until the test sets it (overlap tests).
    """

    def __init__(
        self,
        *,
        normal_orders: Iterable[Any] = (),
        algo_orders: Iterable[Any] = (),
        positions: Iterable[Any] = (),
        fail: Mapping[str, BaseException] | None = None,
        pause: asyncio.Event | None = None,
    ) -> None:
        self.pause = pause
        self._normal = list(normal_orders)
        self._algo = list(algo_orders)
        self._positions = list(positions)
        self.fail: dict[str, BaseException] = dict(fail or {})
        self.calls: list[str] = []
        self.cancelled_algo: list[tuple[str, str]] = []
        self.cancelled_normal: list[tuple[str, str]] = []
        self.forbidden_calls: list[str] = []

    def count(self, name: str) -> int:
        return self.calls.count(name)

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        exc = self.fail.get(name)
        if exc is not None:
            raise exc

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]:
        self._enter("snapshot_open_normal_orders")
        if self.pause is not None:
            await self.pause.wait()
        return [o for o in self._normal if symbol is None or o.symbol == symbol]

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]:
        self._enter("snapshot_open_algo_orders")
        return [o for o in self._algo if symbol is None or o.symbol == symbol]

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]:
        self._enter("snapshot_positions")
        return [p for p in self._positions if symbol is None or p.symbol == symbol]

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> AlgoOrderProbe:
        self._enter("query_algo_order_by_client")
        for order in self._algo:
            if order.client_algo_id == client_algo_id:
                return AlgoOrderProbe(
                    client_algo_id=client_algo_id,
                    found=True,
                    algo_status=order.algo_status,
                    update_time_utc=order.update_time_utc,
                )
        return AlgoOrderProbe(
            client_algo_id=client_algo_id, found=False, algo_status=None, update_time_utc=None
        )

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None:
        self._enter("cancel_algo_order")
        self.cancelled_algo.append((symbol, client_algo_id))
        self._algo = [
            o for o in self._algo if not (o.symbol == symbol and o.client_algo_id == client_algo_id)
        ]

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> None:
        self._enter("cancel_normal_order")
        self.cancelled_normal.append((symbol, orig_client_order_id))

    def __getattr__(self, name: str) -> Any:
        if name.startswith(("place_", "new_")):

            async def _forbidden(*_args: Any, **_kwargs: Any) -> None:
                self.forbidden_calls.append(name)
                raise AssertionError(f"the reconciler must never call {name}")

            return _forbidden
        raise AttributeError(name)


class FakeIntentStore:
    """`list_unresolved_intents()` over fixed rows; `raises` makes the read fail."""

    def __init__(self, rows: Iterable[Any] = (), *, raises: BaseException | None = None) -> None:
        self.rows = tuple(rows)
        self.raises = raises
        self.calls = 0

    def list_unresolved_intents(self) -> tuple[Any, ...]:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.rows


def make_intent_record(
    plan_hash: str,
    role: str,
    *,
    status: str = "SENT",
    symbol: str = "BTCUSDT",
) -> Any:
    """An unresolved `IntentRecord` row whose ids are the deterministic ones of the plan."""
    from src.domain.enums import ExecutionIntentStatus, OrderRole
    from src.execution.intent_store import IntentRecord
    from src.execution.order_ids import derive_algo_client_id, derive_client_order_id

    is_entry = role == OrderRole.ENTRY.value
    return IntentRecord(
        approval_id=f"approval-{plan_hash[:8]}",
        role=role,
        trade_plan_id=f"trade-plan-{plan_hash[:8]}",
        plan_hash=plan_hash,
        client_order_id=derive_client_order_id(plan_hash=plan_hash, role=role)
        if is_entry
        else None,
        algo_client_id=None if is_entry else derive_algo_client_id(plan_hash=plan_hash, role=role),
        symbol=symbol,
        side="BUY" if is_entry else "SELL",
        intended_quantity=Decimal("0.004"),
        intended_price=Decimal("100"),
        intent_status=ExecutionIntentStatus(status),
        exchange_order_id=None,
        exchange_status=None,
        outcome=None,
        intended_at_utc=_T0,
        sent_at_utc=None if status == "INTENDED" else _T0,
        resolved_at_utc=None,
        updated_at_utc=_T0,
    )


def make_position(
    symbol: str, amount: str | Decimal, *, position_side: str = "BOTH"
) -> PositionSnapshot:
    """A One-way exchange position row (`position_side` BOTH) with a signed amount."""
    return PositionSnapshot(
        symbol=symbol,
        position_side=position_side,
        position_amt=Decimal(amount),
        entry_price=Decimal("100"),
        break_even_price=Decimal("100"),
        mark_price=Decimal("100"),
        unrealized_profit=Decimal("0"),
        liquidation_price=None,
        notional=None,
        margin_asset="USDT",
        update_time_utc=_T0,
    )


def make_open_order(
    client_order_id: str,
    symbol: str,
    *,
    side: str = "BUY",
    quantity: str | Decimal = "0.004",
    status: str = "NEW",
) -> OpenOrderSnapshot:
    """A resting LIMIT order row."""
    return OpenOrderSnapshot(
        symbol=symbol,
        client_order_id=client_order_id,
        exchange_order_id="1",
        side=side,
        position_side="BOTH",
        order_type="LIMIT",
        time_in_force="GTD",
        status=status,
        quantity=Decimal(quantity),
        price=Decimal("100"),
        stop_price=None,
        reduce_only=False,
        close_position=False,
        working_type=None,
        price_protect=None,
        update_time_utc=_T0,
    )


def make_algo_order(
    client_algo_id: str,
    symbol: str,
    *,
    algo_status: str = "NEW",
    side: str = "SELL",
) -> OpenAlgoOrderSnapshot:
    """A resting conditional (STOP_MARKET) row; `NEW` is the ACTIVE class."""
    return OpenAlgoOrderSnapshot(
        symbol=symbol,
        client_algo_id=client_algo_id,
        algo_id="1",
        algo_type="CONDITIONAL",
        order_type="STOP_MARKET",
        side=side,
        position_side="BOTH",
        time_in_force="GTE_GTC",
        algo_status=algo_status,
        quantity=Decimal("0.004"),
        trigger_price=Decimal("90"),
        price=None,
        trigger_time_utc=None,
        working_type="MARK_PRICE",
        close_position=True,
        reduce_only=False,
        update_time_utc=_T0,
    )


def make_plan_protection(
    plan_hash: str,
    *,
    symbol: str = "BTCUSDT",
    state: str = "PROTECTED",
    side: str = "LONG",
    quantity: str | Decimal = "0.004",
    first_fill: bool = True,
    stop_confirmed: bool = True,
    entry_terminal: bool = True,
    stop_lost: bool = False,
) -> Any:
    """A `PlanProtection` view row; the flags set the matching timestamps to fixed values."""
    from src.domain.enums import OrderRole
    from src.execution.order_ids import derive_client_order_id
    from src.execution.protection import PlanProtection, ProtectionState

    return PlanProtection(
        plan_hash=plan_hash,
        symbol=symbol,
        state=ProtectionState(state),
        first_fill_at_utc=_T0 if first_fill else None,
        stop_confirmed_at_utc=_T0 + timedelta(seconds=1) if stop_confirmed else None,
        entry_terminal_at_utc=_T0 + timedelta(seconds=2) if entry_terminal else None,
        last_reason=None,
        stop_lost_at_utc=_T0 + timedelta(seconds=3) if stop_lost else None,
        approval_id=f"approval-{plan_hash[:8]}",
        side=side,
        entry_quantity=Decimal(quantity),
        entry_client_order_id=derive_client_order_id(
            plan_hash=plan_hash, role=OrderRole.ENTRY.value
        ),
    )


__all__ = [
    "AlertCall",
    "FakeGate",
    "FakeIntentStore",
    "FakeProtectionView",
    "FakeReconcileAdapter",
    "FlakyJournal",
    "InMemorySafeModeStore",
    "RaisingJournal",
    "RecordingAlertSink",
    "RecordingJournal",
    "make_algo_order",
    "make_intent_record",
    "make_open_order",
    "make_plan_protection",
    "make_position",
]
