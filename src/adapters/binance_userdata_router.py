"""The user-data event router: trusted stream events to project outcomes (Phase 18, plan 18-15).

The stream is a hint and REST is the authority (D-05). The router takes the events the
supervisor of plan 18-14 releases (`TrustedEvent`: LIVE, or held over a gap and released after
a REST snapshot) and hands each outcome to an injected sink (D-05 to D-08):

- a TRADE of a known order: a `RoutedFill` (the `FillEvent` of `to_fill_event`) for the
  idempotent `fold_fills`, keyed `(exchange order id, trade id)`;
- every update of a known order: an `ExchangeStateUpdate` and an `OrderStatusHint` carrying
  `ExitEvidence(source=USER_DATA_EVENT)`; the router changes no state itself;
- the accumulated-quantity check (`FillTotalsTracker`): a TRADE whose accumulated quantity `z`
  is the largest seen for its order and differs from the sum of the unique last-filled
  quantities is a FILL_TOTAL_MISMATCH anomaly, a divergence and one call of the REST fills
  fallback (real trade ids, so the fold key space stays one, research P13);
- an ALGO_UPDATE: de-duplicated per lifecycle update (below), then an `AlgoRoute` with the
  ratified class of its status (D-07), a STREAM_ALGO_TERMINAL_FAILED divergence for a known
  order whose class is TERMINAL_FAILED, and the reject reason `rm` journaled as a scrubbed,
  length-capped ALGO_STATUS_DIAGNOSTIC that decides nothing (P23);
- an ACCOUNT_UPDATE: the event unchanged to the account sink (deltas only, nothing computed);
  an ACCOUNT_CONFIG_UPDATE: an ACCOUNT_CONFIG_HINT journal record; listenKeyExpired and the
  ignored events: counters only;
- every surprise (an unknown client order id or algo id, a forced-close order, an amendment, a
  liquidation, a malformed or unknown-status frame): a STREAM_ANOMALY journal record with a
  deterministic id per (session, kind, payload hash) and a `StreamDivergence` for the
  reconciler. Nothing is silently dropped or coerced, and nothing is fabricated.

ALGO_UPDATE de-duplication. The Binance change log entry of 2026-08-21 (docs/SOURCES.md "Facts
read for Phase 18"; a WebFetch summary, not verified live) says an ALGO_UPDATE of a trailing
stop may arrive twice, first with `ia` false and then with `ia` true. The router keys every
ALGO_UPDATE by (client algo id, algo id, algo status, actual order id, executed quantity,
reject reason), leaving out `is_activated` and the event and transaction times. The first event
of a key is routed; a later event with the same key in the same router instance (one stream
session) is counted in `RouteResult.duplicate_algo_updates` and routed nowhere. A different
status for the same algo id is a different key and is never suppressed. The seen keys are not
persisted: a frame replayed in a new session is handled by the journal's deterministic ids.

Failures. A sink that raises does not stop routing: the exception TYPE (never its message) is
journaled as a ROUTER_SINK_FAILURE record and the next sink runs. A failing journal is
re-raised (fail closed: losing the audit record must not be silent); the router then forgets
nothing it would need on redelivery (journal ids, the ALGO_UPDATE key and the reported
accumulated value are remembered only after the journal accepted the record).

Imports: the standard library, `src.adapters.binance_userdata_events`,
`src.execution.fill_monitor.FillEvent`, `src.domain.*` and `src.ops.redaction.scrub` only;
nothing from `src.persistence` or `src.paper` and no SDK. The process wiring (persistence
sinks, the reconciler, the mapping of `StreamDivergence` onto the reconciler's divergence
vocabulary) is Phases 20 and 24 (D-04). No wall clock is read: event times come from the events
and the injected clock.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol

from src.adapters.binance_userdata_events import (
    ACCOUNT_CONFIG_UPDATE_EVENT,
    ACCOUNT_UPDATE_EVENT,
    ALGO_UPDATE_EVENT,
    LISTEN_KEY_EXPIRED_EVENT,
    ORDER_TRADE_UPDATE_EVENT,
    AccountConfigUpdateEvent,
    AccountUpdateEvent,
    AlgoUpdateEvent,
    IgnoredEvent,
    ListenKeyExpiredEvent,
    OrderUpdateEvent,
    StreamAnomaly,
    StreamAnomalyKind,
    StreamOutcome,
    canonical_payload_sha256,
    to_fill_event,
)
from src.domain.algo_status import AlgoStatusClass, classify_algo_status
from src.domain.enums import OrderRole, OrderStatus
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.stream_records import (
    USER_DATA_STREAM,
    EvidenceSource,
    ExitEvidence,
    stream_anomaly_event,
)
from src.execution.fill_monitor import FillEvent
from src.ops.redaction import scrub

Clock = Callable[[], datetime]

# Journal event types written by the router (beside STREAM_ANOMALY of src.domain.stream_records).
ALGO_STATUS_DIAGNOSTIC = "ALGO_STATUS_DIAGNOSTIC"
ACCOUNT_CONFIG_HINT = "ACCOUNT_CONFIG_HINT"
# The anomaly kind of a sink that raised (a router record, not a StreamAnomalyKind).
ROUTER_SINK_FAILURE = "ROUTER_SINK_FAILURE"

ALGO_DIAGNOSTIC_PREFIX = "ad"
ACCOUNT_CONFIG_PREFIX = "ac"
REJECT_REASON_JOURNAL_MAX_CHARS = 200
# journal_events.correlation_id is VARCHAR(128).
SESSION_ID_MAX_CHARS = 128

# Kinds of outcome a `RouteResult` reports.
KIND_ORDER_UPDATE = "ORDER_UPDATE"
KIND_ALGO_UPDATE = "ALGO_UPDATE"
KIND_ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
KIND_ACCOUNT_CONFIG_UPDATE = "ACCOUNT_CONFIG_UPDATE"
KIND_LISTEN_KEY_EXPIRED = "LISTEN_KEY_EXPIRED"
KIND_IGNORED = "IGNORED"
KIND_STREAM_ANOMALY = "STREAM_ANOMALY"
KIND_UNRECOGNIZED = "UNRECOGNIZED"

_EXECUTION_TYPE_TRADE = "TRADE"
# Order statuses that end an order without (further) fills.
TERMINAL_NOT_FILLED_STATUSES: frozenset[str] = frozenset(
    {"CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}
)

_EVENT_NAMES: dict[type, str] = {
    OrderUpdateEvent: ORDER_TRADE_UPDATE_EVENT,
    AlgoUpdateEvent: ALGO_UPDATE_EVENT,
    AccountUpdateEvent: ACCOUNT_UPDATE_EVENT,
    AccountConfigUpdateEvent: ACCOUNT_CONFIG_UPDATE_EVENT,
    ListenKeyExpiredEvent: LISTEN_KEY_EXPIRED_EVENT,
}


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
    # A sink raised: the event it was handed (a fill, a status hint, an algo update) was not
    # taken over, so the reconciler must look at the order or algo order it names.
    SINK_FAILURE = "SINK_FAILURE"


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
    fallback_calls: int = 0
    fallback_fills: int = 0
    exchange_states: int = 0
    status_hints: int = 0
    algo_routes: int = 0
    account_events: int = 0
    config_hints: int = 0
    diagnostics: int = 0
    anomalies: int = 0
    divergences: int = 0
    duplicate_algo_updates: int = 0
    listen_key_expired: int = 0
    ignored: int = 0
    sink_failures: int = 0


@dataclass
class _Tally:
    """Mutable counters of one `route` call, frozen into a `RouteResult` at the end."""

    fills: int = 0
    fallback_calls: int = 0
    fallback_fills: int = 0
    exchange_states: int = 0
    status_hints: int = 0
    algo_routes: int = 0
    account_events: int = 0
    config_hints: int = 0
    diagnostics: int = 0
    anomalies: int = 0
    divergences: int = 0
    duplicate_algo_updates: int = 0
    listen_key_expired: int = 0
    ignored: int = 0
    sink_failures: int = 0

    def result(self, *, handled: bool, kind: str) -> RouteResult:
        counts = {f.name: getattr(self, f.name) for f in fields(self)}
        return RouteResult(handled=handled, kind=kind, **counts)


# --------------------------------------------------------------------------- #
# Accumulated-quantity integrity check.
# --------------------------------------------------------------------------- #


class FillTotalsTracker:
    """Per exchange order id: unique trade ids with their last-filled quantity, largest `z` seen.

    `observe` records a TRADE and returns the accumulated value to report when that event's
    accumulated quantity is at least the largest seen for its order and differs from the sum of
    the unique last-filled quantities; an older event (accumulated below the largest seen) is
    never checked, so reordering never raises a false mismatch. A value already reported
    (`mark_reported`) is not returned again, so the fallback runs at most once per (order,
    accumulated value). Trades supplied by the REST fallback are added with `record_trade`.
    """

    def __init__(self) -> None:
        self._trades: dict[str, dict[str, Decimal]] = {}
        self._largest: dict[str, Decimal] = {}
        self._reported: set[tuple[str, Decimal]] = set()

    def record_trade(self, order_id: str, trade_id: str, quantity: Decimal) -> None:
        """Remember one unique trade (the first quantity seen for a trade id is kept)."""
        self._trades.setdefault(order_id, {}).setdefault(trade_id, quantity)

    def observe(self, event: OrderUpdateEvent) -> Decimal | None:
        if event.execution_type != _EXECUTION_TYPE_TRADE:
            return None
        trade_id = event.trade_id
        last = event.last_filled_quantity
        accumulated = event.accumulated_filled_quantity
        if trade_id is None or last is None or accumulated is None:
            return None
        order_id = event.exchange_order_id
        self.record_trade(order_id, trade_id, last)
        largest = self._largest.get(order_id)
        if largest is not None and accumulated < largest:
            return None
        self._largest[order_id] = accumulated
        if self.unique_total(order_id) == accumulated:
            return None
        if (order_id, accumulated) in self._reported:
            return None
        return accumulated

    def mark_reported(self, order_id: str, accumulated: Decimal) -> None:
        self._reported.add((order_id, accumulated))

    def unique_total(self, order_id: str) -> Decimal:
        return sum(self._trades.get(order_id, {}).values(), Decimal("0"))

    def largest_accumulated(self, order_id: str) -> Decimal | None:
        return self._largest.get(order_id)


# --------------------------------------------------------------------------- #
# Deterministic fingerprints and payloads.
# --------------------------------------------------------------------------- #


def _plain(value: object) -> object:
    """A JSON-ready, deterministic form of an event value (text for Decimal and datetime)."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple | list):
        return [_plain(entry) for entry in value]
    if value is None or isinstance(value, str | int | bool):
        return value
    return {"__type__": type(value).__name__}


def _fingerprint(outcome: object) -> str:
    """sha256 of the canonical JSON of the outcome's type and fields (same event, same hash)."""
    return canonical_payload_sha256({"type": type(outcome).__name__, "fields": _plain(outcome)})


def _text_attr(outcome: object, name: str) -> str | None:
    """A non-empty text attribute of an outcome (an order or algo identity), else None."""
    value = getattr(outcome, name, None)
    return value if isinstance(value, str) and value != "" else None


def _payload(values: dict[str, str | None]) -> str:
    return json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _event_name(outcome: object) -> str | None:
    if isinstance(outcome, StreamAnomaly):
        return outcome.event_name
    if isinstance(outcome, IgnoredEvent):
        return outcome.event_name
    return _EVENT_NAMES.get(type(outcome))


def _algo_lifecycle_key(
    event: AlgoUpdateEvent,
) -> tuple[str, str, str, str | None, Decimal | None, str | None]:
    """The lifecycle key of an ALGO_UPDATE: `is_activated` and the times are left out."""
    return (
        event.client_algo_id,
        event.algo_id,
        event.algo_status,
        event.actual_order_id,
        event.executed_quantity,
        event.reject_reason,
    )


# --------------------------------------------------------------------------- #
# The router.
# --------------------------------------------------------------------------- #


class UserDataRouter:
    """Routes each trusted stream outcome to its sink; never fabricates state (D-05).

    Every constructor argument is keyword-only and required. Sinks are plain callables that
    record or enqueue. `fills_fallback(exchange_order_id)` returns the REST fills of an order
    (real trade ids). One router instance serves one stream session (`session_id`).
    """

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
        if len(session_id) > SESSION_ID_MAX_CHARS:
            raise ValueError(f"session_id must be at most {SESSION_ID_MAX_CHARS} characters")
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
        self._totals = FillTotalsTracker()
        self._seen_algo_keys: set[tuple[str, str, str, str | None, Decimal | None, str | None]] = (
            set()
        )
        # Journal ids this router already wrote: a duplicate is not re-sent, because the
        # append-only journal rejects the same id with a different observation time.
        self._journaled: set[str] = set()
        # `after_gap` of the item being routed, for the divergence of a failing sink.
        self._after_gap = False

    def __repr__(self) -> str:
        return f"{type(self).__name__}(session_id={self._session_id!r})"

    @property
    def session_id(self) -> str:
        return self._session_id

    # -- dispatch ------------------------------------------------------------ #

    def route(self, item: TrustedItem) -> RouteResult:
        """Hand one trusted outcome to its sinks; never raises except for a failing journal."""
        outcome: object = item.outcome
        tally = _Tally()
        self._after_gap = item.after_gap
        if isinstance(outcome, OrderUpdateEvent):
            self._route_order(outcome, item, tally)
            return tally.result(handled=True, kind=KIND_ORDER_UPDATE)
        if isinstance(outcome, AlgoUpdateEvent):
            self._route_algo(outcome, item, tally)
            return tally.result(handled=True, kind=KIND_ALGO_UPDATE)
        if isinstance(outcome, AccountUpdateEvent):
            if self._call_sink("account_sink", self._account_sink, outcome, outcome, tally):
                tally.account_events += 1
            return tally.result(handled=True, kind=KIND_ACCOUNT_UPDATE)
        if isinstance(outcome, AccountConfigUpdateEvent):
            self._journal_config_hint(outcome, item, tally)
            return tally.result(handled=True, kind=KIND_ACCOUNT_CONFIG_UPDATE)
        if isinstance(outcome, ListenKeyExpiredEvent):
            tally.listen_key_expired += 1
            return tally.result(handled=True, kind=KIND_LISTEN_KEY_EXPIRED)
        if isinstance(outcome, IgnoredEvent):
            tally.ignored += 1
            return tally.result(handled=True, kind=KIND_IGNORED)
        if isinstance(outcome, StreamAnomaly):
            self._route_anomaly(outcome, item, tally)
            return tally.result(handled=True, kind=KIND_STREAM_ANOMALY)
        # Not a stream outcome at all: a wiring defect, recorded and surfaced, never raised.
        self._surface_anomaly(
            kind=StreamAnomalyKind.UNRECOGNIZED_ENVELOPE.value,
            event_name=None,
            field=None,
            detail=f"router received an object of type {type(outcome).__name__}",
            payload_sha256=canonical_payload_sha256({"type": type(outcome).__name__}),
            observed_at_utc=item.received_at_utc,
            divergence_kind=StreamDivergenceKind.STREAM_ANOMALY,
            symbol=None,
            client_order_id=None,
            client_algo_id=None,
            reason="the router received an object that is not a stream outcome",
            after_gap=item.after_gap,
            outcome=outcome,
            tally=tally,
        )
        return tally.result(handled=False, kind=KIND_UNRECOGNIZED)

    # -- order updates ------------------------------------------------------- #

    def _route_order(self, event: OrderUpdateEvent, item: TrustedItem, tally: _Tally) -> None:
        known = self._lookup.known_order(event.client_order_id)
        if known is None:
            self._surface_anomaly(
                kind=StreamAnomalyKind.UNKNOWN_ORDER.value,
                event_name=ORDER_TRADE_UPDATE_EVENT,
                field="o.c",
                detail="field o.c is not a client order id of a project order",
                payload_sha256=_fingerprint(event),
                observed_at_utc=item.received_at_utc,
                divergence_kind=StreamDivergenceKind.UNKNOWN_STREAM_ORDER,
                symbol=event.symbol,
                client_order_id=event.client_order_id,
                client_algo_id=None,
                reason="an order update for a client order id the project does not know",
                after_gap=item.after_gap,
                outcome=event,
                tally=tally,
            )
            return

        update = ExchangeStateUpdate(
            local_order_id=known.local_order_id,
            exchange_status=event.order_status,
            exchange_order_id=event.exchange_order_id,
            now_utc=self._clock(),
        )
        if self._call_sink("exchange_state_sink", self._exchange_state_sink, update, event, tally):
            tally.exchange_states += 1

        trade_ref = event.trade_id or "none"
        evidence = ExitEvidence(
            source=EvidenceSource.USER_DATA_EVENT,
            observed_at_utc=item.received_at_utc,
            reference=f"{event.execution_type}:{event.exchange_order_id}:{trade_ref}",
            correlation_id=self._session_id,
        )
        hint = OrderStatusHint(
            known=known,
            execution_type=event.execution_type,
            exchange_status=event.order_status,
            exchange_order_id=event.exchange_order_id,
            terminal_not_filled=event.order_status in TERMINAL_NOT_FILLED_STATUSES,
            evidence=evidence,
            after_gap=item.after_gap,
        )
        if self._call_sink("status_hint_sink", self._status_hint_sink, hint, event, tally):
            tally.status_hints += 1

        fill = to_fill_event(event)
        if fill is not None:
            routed = RoutedFill(
                fill=fill, source=FillSource.USER_DATA_EVENT, after_gap=item.after_gap
            )
            if self._call_sink("fill_sink", self._fill_sink, routed, event, tally):
                tally.fills += 1

        accumulated = self._totals.observe(event)
        if accumulated is not None:
            self._handle_fill_total_mismatch(event, known, accumulated, item, tally)

    def _handle_fill_total_mismatch(
        self,
        event: OrderUpdateEvent,
        known: KnownOrder,
        accumulated: Decimal,
        item: TrustedItem,
        tally: _Tally,
    ) -> None:
        order_id = event.exchange_order_id
        self._surface_anomaly(
            kind=StreamAnomalyKind.FILL_TOTAL_MISMATCH.value,
            event_name=ORDER_TRADE_UPDATE_EVENT,
            field="o.z",
            detail=(
                "field o.z differs from the sum of the unique last filled quantities of the order"
            ),
            payload_sha256=canonical_payload_sha256(
                {
                    "check": StreamAnomalyKind.FILL_TOTAL_MISMATCH.value,
                    "exchange_order_id": order_id,
                    "accumulated_filled_quantity": str(accumulated),
                }
            ),
            observed_at_utc=item.received_at_utc,
            divergence_kind=StreamDivergenceKind.STREAM_FILL_TOTAL_MISMATCH,
            symbol=event.symbol,
            client_order_id=known.client_id,
            client_algo_id=None,
            reason="the accumulated filled quantity disagrees with the unique stream fills",
            after_gap=item.after_gap,
            outcome=event,
            tally=tally,
        )
        # Remembered only after the journal accepted the record (a failing journal re-raises).
        self._totals.mark_reported(order_id, accumulated)

        tally.fallback_calls += 1
        try:
            fills = list(self._fills_fallback(order_id))
            if not all(isinstance(fill, FillEvent) for fill in fills):
                raise TypeError("the fills fallback returned an object that is not a FillEvent")
        except Exception as exc:
            self._record_sink_failure("fills_fallback", exc, event, tally)
            return
        for fill in fills:
            if fill.order_id == order_id:
                self._totals.record_trade(order_id, fill.exchange_trade_id, fill.fill_quantity)
            routed = RoutedFill(
                fill=fill, source=FillSource.REST_FALLBACK, after_gap=item.after_gap
            )
            if self._call_sink("fill_sink", self._fill_sink, routed, event, tally):
                tally.fallback_fills += 1

    # -- algo updates -------------------------------------------------------- #

    def _route_algo(self, event: AlgoUpdateEvent, item: TrustedItem, tally: _Tally) -> None:
        key = _algo_lifecycle_key(event)
        if key in self._seen_algo_keys:
            tally.duplicate_algo_updates += 1
            return
        status_class = classify_algo_status(event.algo_status)
        known = self._lookup.known_algo(event.client_algo_id)

        if event.reject_reason is not None:
            self._journal_algo_diagnostic(event, status_class, item, tally)

        if known is None:
            self._surface_anomaly(
                kind=StreamAnomalyKind.UNKNOWN_ORDER.value,
                event_name=ALGO_UPDATE_EVENT,
                field="o.caid",
                detail="field o.caid is not a client algo id of a project algo order",
                payload_sha256=canonical_payload_sha256(
                    {"check": "UNKNOWN_ALGO", "lifecycle_key": _plain(list(key))}
                ),
                observed_at_utc=item.received_at_utc,
                divergence_kind=StreamDivergenceKind.UNKNOWN_STREAM_ALGO,
                symbol=event.symbol,
                client_order_id=None,
                client_algo_id=event.client_algo_id,
                reason="an algo update for a client algo id the project does not know",
                after_gap=item.after_gap,
                outcome=event,
                tally=tally,
            )
        else:
            route = AlgoRoute(
                known=known, event=event, status_class=status_class, after_gap=item.after_gap
            )
            algo_sink_ok = self._call_sink("algo_sink", self._algo_sink, route, event, tally)
            if algo_sink_ok:
                tally.algo_routes += 1
            if status_class is AlgoStatusClass.TERMINAL_FAILED:
                self._emit_divergence(
                    StreamDivergence(
                        kind=StreamDivergenceKind.STREAM_ALGO_TERMINAL_FAILED,
                        symbol=event.symbol,
                        client_order_id=None,
                        client_algo_id=event.client_algo_id,
                        reason="a project algo order reports a TERMINAL_FAILED status",
                        anomaly_kind=None,
                        payload_sha256=None,
                        after_gap=item.after_gap,
                    ),
                    event,
                    tally,
                )
        # Remembered only after every journal write of this update succeeded and the algo sink
        # took the update over: a redelivery of an update the sink lost is routed again.
        if known is None or algo_sink_ok:
            self._seen_algo_keys.add(key)

    def _journal_algo_diagnostic(
        self,
        event: AlgoUpdateEvent,
        status_class: AlgoStatusClass,
        item: TrustedItem,
        tally: _Tally,
    ) -> None:
        reason = event.reject_reason or ""
        reason_hash = hashlib.sha256(reason.encode("utf-8")).hexdigest()
        entity_id = f"algo:{event.algo_id}"
        record = JournalEvent(
            journal_event_id=correlated_event_id(
                prefix=ALGO_DIAGNOSTIC_PREFIX,
                correlation_id=self._session_id,
                event_type=ALGO_STATUS_DIAGNOSTIC,
                entity_id=entity_id,
                step=f"{event.algo_status}:{reason_hash}",
            ),
            occurred_at_utc=item.received_at_utc,
            event_type=ALGO_STATUS_DIAGNOSTIC,
            entity_type=USER_DATA_STREAM,
            entity_id=entity_id,
            correlation_id=self._session_id,
            payload_json=_payload(
                {
                    "algo_id": event.algo_id,
                    "algo_status": event.algo_status,
                    "client_algo_id": event.client_algo_id,
                    "reject_reason": scrub(reason)[:REJECT_REASON_JOURNAL_MAX_CHARS],
                    "status_class": status_class.value,
                    "symbol": event.symbol,
                }
            ),
            created_at_utc=item.received_at_utc,
        )
        self._record(record)
        tally.diagnostics += 1

    # -- account configuration ----------------------------------------------- #

    def _journal_config_hint(
        self, event: AccountConfigUpdateEvent, item: TrustedItem, tally: _Tally
    ) -> None:
        entity_id = (
            f"account_config:{event.symbol}"
            if event.symbol is not None
            else "account_config:multi_assets"
        )
        multi_assets = None if event.multi_assets is None else str(event.multi_assets).lower()
        record = JournalEvent(
            journal_event_id=correlated_event_id(
                prefix=ACCOUNT_CONFIG_PREFIX,
                correlation_id=self._session_id,
                event_type=ACCOUNT_CONFIG_HINT,
                entity_id=entity_id,
                step=_fingerprint(event),
            ),
            occurred_at_utc=item.received_at_utc,
            event_type=ACCOUNT_CONFIG_HINT,
            entity_type=USER_DATA_STREAM,
            entity_id=entity_id,
            correlation_id=self._session_id,
            payload_json=_payload(
                {
                    "event_time_utc": event.event_time_utc.isoformat(),
                    "leverage": None if event.leverage is None else str(event.leverage),
                    "multi_assets": multi_assets,
                    "symbol": event.symbol,
                }
            ),
            created_at_utc=item.received_at_utc,
        )
        self._record(record)
        tally.config_hints += 1

    # -- anomalies and divergences ------------------------------------------- #

    def _route_anomaly(self, anomaly: StreamAnomaly, item: TrustedItem, tally: _Tally) -> None:
        self._surface_anomaly(
            kind=anomaly.kind.value,
            event_name=anomaly.event_name,
            field=anomaly.field,
            detail=anomaly.detail,
            payload_sha256=anomaly.payload_sha256,
            observed_at_utc=anomaly.observed_at_utc,
            divergence_kind=StreamDivergenceKind.STREAM_ANOMALY,
            symbol=None,
            client_order_id=None,
            client_algo_id=None,
            reason=f"stream anomaly {anomaly.kind.value}",
            after_gap=item.after_gap,
            outcome=anomaly,
            tally=tally,
        )

    def _surface_anomaly(
        self,
        *,
        kind: str,
        event_name: str | None,
        field: str | None,
        detail: str,
        payload_sha256: str,
        observed_at_utc: datetime,
        divergence_kind: StreamDivergenceKind,
        symbol: str | None,
        client_order_id: str | None,
        client_algo_id: str | None,
        reason: str,
        after_gap: bool,
        outcome: object,
        tally: _Tally,
    ) -> None:
        """Journal one anomaly (deterministic id per session and payload hash), then surface it."""
        self._record(
            stream_anomaly_event(
                kind=kind,
                event_name=event_name,
                field=field,
                detail=detail,
                payload_sha256=payload_sha256,
                observed_at_utc=observed_at_utc,
                session_id=self._session_id,
            )
        )
        tally.anomalies += 1
        self._emit_divergence(
            StreamDivergence(
                kind=divergence_kind,
                symbol=symbol,
                client_order_id=client_order_id,
                client_algo_id=client_algo_id,
                reason=reason,
                anomaly_kind=kind,
                payload_sha256=payload_sha256,
                after_gap=after_gap,
            ),
            outcome,
            tally,
        )

    def _emit_divergence(
        self, divergence: StreamDivergence, outcome: object, tally: _Tally
    ) -> None:
        if self._call_sink("divergence_sink", self._divergence_sink, divergence, outcome, tally):
            tally.divergences += 1

    # -- sinks and the journal ----------------------------------------------- #

    def _call_sink[ArgT](
        self,
        name: str,
        sink: Callable[[ArgT], None],
        argument: ArgT,
        outcome: object,
        tally: _Tally,
    ) -> bool:
        """Call one sink; a raising sink is journaled by exception type and routing continues."""
        try:
            sink(argument)
        except Exception as exc:
            self._record_sink_failure(name, exc, outcome, tally)
            return False
        return True

    def _record_sink_failure(
        self, name: str, exc: Exception, outcome: object, tally: _Tally
    ) -> None:
        tally.sink_failures += 1
        exception_type = type(exc).__name__
        payload_sha256 = canonical_payload_sha256(
            {
                "sink": name,
                "exception_type": exception_type,
                "outcome": _fingerprint(outcome),
            }
        )
        self._record(
            stream_anomaly_event(
                kind=ROUTER_SINK_FAILURE,
                event_name=_event_name(outcome),
                field=name,
                detail=f"sink {name} raised {exception_type}"[:200],
                payload_sha256=payload_sha256,
                observed_at_utc=self._clock(),
                session_id=self._session_id,
            )
        )
        if name == "divergence_sink":
            return  # nothing left to surface the failure to; the journal row is the trace
        # The journal row is deduplicated by its fingerprint and nobody reads it live, so the
        # loss is also surfaced as a divergence the reconciler sees (fail closed).
        self._emit_divergence(
            StreamDivergence(
                kind=StreamDivergenceKind.SINK_FAILURE,
                symbol=_text_attr(outcome, "symbol"),
                client_order_id=_text_attr(outcome, "client_order_id"),
                client_algo_id=_text_attr(outcome, "client_algo_id"),
                reason=f"sink {name} raised; the event it was handed was not taken over",
                anomaly_kind=ROUTER_SINK_FAILURE,
                payload_sha256=payload_sha256,
                after_gap=self._after_gap,
            ),
            outcome,
            tally,
        )

    def _record(self, event: JournalEvent) -> None:
        """Write one journal record once per router; a journal failure propagates."""
        if event.journal_event_id in self._journaled:
            return
        self._journal.record(event)
        self._journaled.add(event.journal_event_id)


__all__ = [
    "ACCOUNT_CONFIG_HINT",
    "ALGO_STATUS_DIAGNOSTIC",
    "ROUTER_SINK_FAILURE",
    "TERMINAL_NOT_FILLED_STATUSES",
    "AlgoRoute",
    "ExchangeStateUpdate",
    "FillSource",
    "FillTotalsTracker",
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
