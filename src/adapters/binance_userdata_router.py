"""The user-data event router: trusted stream events to project outcomes (Phase 18, plan 18-15).

The stream is a hint and REST is the authority (D-05). The router takes the events the
supervisor of plan 18-14 releases (`TrustedEvent`: LIVE, or held over a gap and released after
a REST snapshot) and hands each outcome to an injected sink: a `FillEvent` for the idempotent
`fold_fills`, an order status hint with `USER_DATA_EVENT` evidence, an algo-status hint with its
ratified class, an account delta, a journaled stream anomaly and a divergence record for the
reconciler (D-05 to D-08). It never decides state: an unknown, malformed or surprising event is
evidence for the reconciler, not input to a guess.

Imports: the standard library, `src.adapters.binance_userdata_events`,
`src.execution.fill_monitor.FillEvent` and `src.domain.*` only; nothing from `src.persistence`
or `src.paper` and no SDK. The process wiring (persistence sinks, the reconciler) is Phases 20
and 24 (D-04). No wall clock is read: event times come from the events and the injected clock.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from src.adapters.binance_userdata_events import (
    AccountUpdateEvent,
    AlgoUpdateEvent,
    OrderUpdateEvent,
    StreamOutcome,
    to_fill_event,
)
from src.domain.algo_status import AlgoStatusClass
from src.domain.enums import OrderRole, OrderStatus
from src.domain.journal import JournalEvent
from src.domain.stream_records import ExitEvidence
from src.execution.fill_monitor import FillEvent

Clock = Callable[[], datetime]

# Kinds of outcome a `RouteResult` reports.
KIND_ORDER_UPDATE = "ORDER_UPDATE"


# --------------------------------------------------------------------------- #
# Injected collaborators.
# --------------------------------------------------------------------------- #


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, kw_only=True)
class KnownOrder:
    """An order (or algo order) the project placed, as the lookup knows it."""

    local_order_id: str
    client_id: str
    symbol: str
    role: OrderRole
    local_status: OrderStatus

    def __post_init__(self) -> None:
        for name in ("local_order_id", "client_id", "symbol"):
            _require_text(getattr(self, name), name)
        if not isinstance(self.role, OrderRole):
            raise TypeError(f"role must be OrderRole, got {type(self.role).__name__}")
        if not isinstance(self.local_status, OrderStatus):
            raise TypeError(
                f"local_status must be OrderStatus, got {type(self.local_status).__name__}"
            )


class OrderLookup(Protocol):
    """Read-only lookup of the project's own orders by client order id or client algo id."""

    def known_order(self, client_order_id: str) -> KnownOrder | None: ...

    def known_algo(self, client_algo_id: str) -> KnownOrder | None: ...


class JournalRecorder(Protocol):
    """The append-only journal surface (`record`); a failure propagates (fail closed)."""

    def record(self, event: JournalEvent) -> None: ...


class TrustedItem(Protocol):
    """What the router reads of the supervisor's `TrustedEvent` (structural, no import)."""

    @property
    def outcome(self) -> StreamOutcome: ...

    @property
    def received_at_utc(self) -> datetime: ...

    @property
    def after_gap(self) -> bool: ...


# --------------------------------------------------------------------------- #
# Outcome records handed to the sinks.
# --------------------------------------------------------------------------- #


class FillSource(str, Enum):
    """Where a routed fill came from: a stream TRADE or the REST fills fallback."""

    USER_DATA_EVENT = "USER_DATA_EVENT"
    REST_FALLBACK = "REST_FALLBACK"


@dataclass(frozen=True, kw_only=True)
class RoutedFill:
    """A `FillEvent` for `fold_fills`, with its source and the gap flag of its event."""

    fill: FillEvent
    source: FillSource
    after_gap: bool


@dataclass(frozen=True, kw_only=True)
class ExchangeStateUpdate:
    """The exchange view of a known order (for `update_order_exchange_state`, Phase 20 wiring)."""

    local_order_id: str
    exchange_status: str
    exchange_order_id: str
    now_utc: datetime


@dataclass(frozen=True, kw_only=True)
class OrderStatusHint:
    """A status hint for a known order with its user-data evidence (never a state change)."""

    known: KnownOrder
    execution_type: str
    exchange_status: str
    exchange_order_id: str
    terminal_not_filled: bool
    evidence: ExitEvidence
    after_gap: bool


@dataclass(frozen=True, kw_only=True)
class AlgoRoute:
    """An ALGO_UPDATE of a known algo order with the ratified class of its status (D-07)."""

    known: KnownOrder
    event: AlgoUpdateEvent
    status_class: AlgoStatusClass
    after_gap: bool


class StreamDivergenceKind(str, Enum):
    """The router's own divergence vocabulary; Phase 20 maps it onto the reconciler's."""

    STREAM_ANOMALY = "STREAM_ANOMALY"
    STREAM_FILL_TOTAL_MISMATCH = "STREAM_FILL_TOTAL_MISMATCH"
    UNKNOWN_STREAM_ORDER = "UNKNOWN_STREAM_ORDER"
    UNKNOWN_STREAM_ALGO = "UNKNOWN_STREAM_ALGO"
    STREAM_ALGO_TERMINAL_FAILED = "STREAM_ALGO_TERMINAL_FAILED"


@dataclass(frozen=True, kw_only=True)
class StreamDivergence:
    """A stream observation the reconciler must look at (fixed project text, no payload)."""

    kind: StreamDivergenceKind
    symbol: str | None
    client_order_id: str | None
    client_algo_id: str | None
    reason: str
    anomaly_kind: str | None
    payload_sha256: str | None
    after_gap: bool


@dataclass(frozen=True, kw_only=True)
class RouteResult:
    """What one `route` call did (counts only; frozen)."""

    handled: bool
    kind: str
    fills: int = 0


# --------------------------------------------------------------------------- #
# The router.
# --------------------------------------------------------------------------- #


class UserDataRouter:
    """Routes each trusted stream outcome to its sink; never fabricates state (D-05)."""

    def __init__(
        self,
        *,
        order_lookup: OrderLookup,
        journal: JournalRecorder,
        session_id: str,
        clock: Clock,
        fill_sink: Callable[[RoutedFill], None],
        status_hint_sink: Callable[[OrderStatusHint], None],
        exchange_state_sink: Callable[[ExchangeStateUpdate], None],
        algo_sink: Callable[[AlgoRoute], None],
        account_sink: Callable[[AccountUpdateEvent], None],
        divergence_sink: Callable[[StreamDivergence], None],
        fills_fallback: Callable[[str], Sequence[FillEvent]],
    ) -> None:
        _require_text(session_id, "session_id")
        self._lookup = order_lookup
        self._journal = journal
        self._session_id = session_id
        self._clock = clock
        self._fill_sink = fill_sink
        self._status_hint_sink = status_hint_sink
        self._exchange_state_sink = exchange_state_sink
        self._algo_sink = algo_sink
        self._account_sink = account_sink
        self._divergence_sink = divergence_sink
        self._fills_fallback = fills_fallback

    def route(self, item: TrustedItem) -> RouteResult:
        outcome = item.outcome
        if isinstance(outcome, OrderUpdateEvent):
            known = self._lookup.known_order(outcome.client_order_id)
            if known is not None:
                fill = to_fill_event(outcome)
                if fill is not None:
                    self._fill_sink(
                        RoutedFill(
                            fill=fill,
                            source=FillSource.USER_DATA_EVENT,
                            after_gap=item.after_gap,
                        )
                    )
                    return RouteResult(handled=True, kind=KIND_ORDER_UPDATE, fills=1)
        return RouteResult(handled=False, kind=type(outcome).__name__)


__all__ = [
    "AlgoRoute",
    "ExchangeStateUpdate",
    "FillSource",
    "JournalRecorder",
    "KnownOrder",
    "OrderLookup",
    "OrderStatusHint",
    "RouteResult",
    "RoutedFill",
    "StreamDivergence",
    "StreamDivergenceKind",
    "TrustedItem",
    "UserDataRouter",
]
