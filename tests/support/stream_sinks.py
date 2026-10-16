"""Recording sinks, a recording journal and a dict-backed order lookup for the router (plan 18-15).

The user-data router hands every outcome to injected plain callables, so its tests need no
database. `RecordingSinks` keeps one list per sink and can make a named sink raise;
`RecordingJournal` mirrors the append-only journal contract (`PgJournalStore`): a second record
with the same id and identical content is a no-op, the same id with different content raises;
`FakeOrderLookup` answers `known_order` / `known_algo` from dicts. Nothing here is Binance data.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.adapters.binance_userdata_events import AccountUpdateEvent
from src.adapters.binance_userdata_router import (
    AlgoRoute,
    ExchangeStateUpdate,
    KnownOrder,
    OrderStatusHint,
    RoutedFill,
    StreamDivergence,
    UserDataRouter,
)
from src.domain.journal import JournalEvent
from src.execution.fill_monitor import FillEvent

TEST_ONLY_SESSION_ID = "test-only-stream-session-0001"

# The sink names a test may make fail (the keyword names of the router constructor).
SINK_NAMES: tuple[str, ...] = (
    "fill_sink",
    "status_hint_sink",
    "exchange_state_sink",
    "algo_sink",
    "account_sink",
    "divergence_sink",
    "fills_fallback",
)


class InjectedSinkFailure(RuntimeError):
    """Raised by a sink a test asked to fail."""


class InjectedJournalFailure(RuntimeError):
    """Raised by the recording journal when a test asked it to fail."""


class JournalReplayConflict(RuntimeError):
    """The same journal id recorded with different content (PgJournalStore's JournalConflict)."""


@dataclass
class RecordingSinks:
    """One list per router sink; `failing` names sinks that raise instead of recording."""

    fills: list[RoutedFill] = field(default_factory=list)
    status_hints: list[OrderStatusHint] = field(default_factory=list)
    exchange_states: list[ExchangeStateUpdate] = field(default_factory=list)
    algo_routes: list[AlgoRoute] = field(default_factory=list)
    account_events: list[AccountUpdateEvent] = field(default_factory=list)
    divergences: list[StreamDivergence] = field(default_factory=list)
    fallback_calls: list[str] = field(default_factory=list)
    # What the REST fills fallback returns per exchange order id (real trade ids).
    fallback_fills: dict[str, list[FillEvent]] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)

    def _check(self, name: str) -> None:
        if name in self.failing:
            raise InjectedSinkFailure(f"TEST_ONLY failure of {name}")

    def fill_sink(self, routed: RoutedFill) -> None:
        self._check("fill_sink")
        self.fills.append(routed)

    def status_hint_sink(self, hint: OrderStatusHint) -> None:
        self._check("status_hint_sink")
        self.status_hints.append(hint)

    def exchange_state_sink(self, update: ExchangeStateUpdate) -> None:
        self._check("exchange_state_sink")
        self.exchange_states.append(update)

    def algo_sink(self, route: AlgoRoute) -> None:
        self._check("algo_sink")
        self.algo_routes.append(route)

    def account_sink(self, event: AccountUpdateEvent) -> None:
        self._check("account_sink")
        self.account_events.append(event)

    def divergence_sink(self, divergence: StreamDivergence) -> None:
        self._check("divergence_sink")
        self.divergences.append(divergence)

    def fills_fallback(self, order_id: str) -> list[FillEvent]:
        self._check("fills_fallback")
        self.fallback_calls.append(order_id)
        return list(self.fallback_fills.get(order_id, []))

    def as_kwargs(self) -> dict[str, Callable[..., Any]]:
        return {name: getattr(self, name) for name in SINK_NAMES}

    def fill_events(self) -> list[FillEvent]:
        return [routed.fill for routed in self.fills]


@dataclass
class RecordingJournal:
    """`record(event)` with the append-only, replay-idempotent contract of the real journal."""

    events: dict[str, JournalEvent] = field(default_factory=dict)
    calls: list[JournalEvent] = field(default_factory=list)
    fail: bool = False

    def record(self, event: JournalEvent) -> None:
        self.calls.append(event)
        if self.fail:
            raise InjectedJournalFailure("TEST_ONLY journal failure")
        existing = self.events.get(event.journal_event_id)
        if existing is None:
            self.events[event.journal_event_id] = event
            return
        if _identity(existing) != _identity(event):
            raise JournalReplayConflict(
                f"journal event {event.journal_event_id} recorded with different content"
            )

    def by_type(self, event_type: str) -> list[JournalEvent]:
        return [event for event in self.events.values() if event.event_type == event_type]


def _identity(event: JournalEvent) -> tuple[object, ...]:
    return (
        event.event_type,
        event.entity_type,
        event.entity_id,
        event.correlation_id,
        event.signal_id,
        event.trade_plan_id,
        event.approval_id,
        event.order_id,
        event.position_id,
        event.payload_json,
    )


@dataclass
class FakeOrderLookup:
    """Dict-backed `OrderLookup`: client order id and client algo id to `KnownOrder`."""

    orders: dict[str, KnownOrder] = field(default_factory=dict)
    algos: dict[str, KnownOrder] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        *,
        orders: Iterable[KnownOrder] = (),
        algos: Iterable[KnownOrder] = (),
    ) -> FakeOrderLookup:
        return cls(
            orders={known.client_id: known for known in orders},
            algos={known.client_id: known for known in algos},
        )

    def known_order(self, client_order_id: str) -> KnownOrder | None:
        return self.orders.get(client_order_id)

    def known_algo(self, client_algo_id: str) -> KnownOrder | None:
        return self.algos.get(client_algo_id)


def make_router(
    *,
    lookup: FakeOrderLookup,
    journal: RecordingJournal,
    sinks: RecordingSinks,
    clock: Callable[[], datetime],
    session_id: str = TEST_ONLY_SESSION_ID,
    overrides: Mapping[str, Callable[..., Any]] | None = None,
) -> UserDataRouter:
    """A router over the recording fakes (`overrides` replaces named sinks)."""
    kwargs = sinks.as_kwargs()
    kwargs.update(overrides or {})
    return UserDataRouter(
        order_lookup=lookup,
        journal=journal,
        session_id=session_id,
        clock=clock,
        **kwargs,
    )


__all__ = [
    "SINK_NAMES",
    "TEST_ONLY_SESSION_ID",
    "FakeOrderLookup",
    "JournalReplayConflict",
    "RecordingJournal",
    "RecordingSinks",
    "InjectedJournalFailure",
    "InjectedSinkFailure",
    "make_router",
]
