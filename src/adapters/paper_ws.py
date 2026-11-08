"""Binance USDⓈ-M WebSocket Streams adapter for the paper loop (Phase 7, plan 07-01).

Per D-01 + RESEARCH §Pattern 1: this is the ONLY module in the project
allowed to import the `binance-sdk-derivatives-trading-usds-futures`
WebSocket Streams surface. The paper loop subscribes via this adapter
and receives frozen `Kline` instances — SDK response models never
leak into `src/paper/`.

Dataclass conventions mirror `src/adapters/binance_usdm.py`:
  - Prices / quantities are `Decimal` (no float for exchange-sensitive
    values per ENGINEERING_PRINCIPLES).
  - Timestamps are `datetime` with `tzinfo=UTC` (D-06).
  - All fields are `frozen=True` so an immutable value flows through
    the pipeline and cannot be accidentally mutated.

Phase 16 (plan 16-01): the adapter is written on the real SDK shape. Every SDK call is
awaited, the interval is a plain string, the default configuration carries the SDK PROD
stream URL, and the stream handle is used only through `on` / `unsubscribe`. The adapter is
constructible with an injected SDK-shaped fake (`tests/paper_ws_fakes.py`, bound to the
installed SDK by `tests/test_paper_ws_contract.py`) so unit tests never touch the network.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import structlog
from binance_common import websocket as sdk_websocket
from binance_common.configuration import ConfigurationWebSocketStreams
from binance_common.constants import DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (
    DerivativesTradingUsdsFuturesWebSocketStreams,
)

log = structlog.get_logger()

# Intervals the paper runtime subscribes to. The SDK builds the stream name with
# `str()` of the interval argument, so a plain string ("1h" -> btcusdt@kline_1h) is
# required; the SDK interval Enum would yield an invalid stream name (research (b)).
ALLOWED_INTERVALS: frozenset[str] = frozenset({"1m", "1h", "4h"})

# --------------------------------------------------------------------------- #
# Frozen domain dataclass — the public contract of the adapter.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Kline:
    """One kline row from a WS kline stream, normalized to project types.

    `close_time_utc <= now_utc` is the invariant callers MUST enforce
    before accepting a kline (RESEARCH §Pitfall 1 — never include the
    forming candle). `is_closed` is the WS `x` flag carried verbatim
    so the paper loop's double gate can short-circuit forming updates
    without re-parsing the wire payload.
    """

    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int
    is_closed: bool


# --------------------------------------------------------------------------- #
# Wire-format normalization.
# --------------------------------------------------------------------------- #


def _ms_to_utc(ms: int) -> datetime:
    """Convert a millisecond Unix epoch to a tz-aware UTC datetime.

    Exact timedelta arithmetic (WR-01) — never float division.
    """
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)


def _normalize_kline_payload(
    symbol: str,
    interval: str,
    payload: dict[str, Any],
) -> Kline:
    """Map a raw WS kline payload to a frozen `Kline`.

    The wire format uses Binance field names (t/T/o/h/l/c/v/n/x/q);
    the `Kline` uses the project's canonical field names. Decimal
    prices/quantities, UTC-aware datetimes.
    """
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_ms_to_utc(int(payload["t"])),
        close_time_utc=_ms_to_utc(int(payload["T"])),
        open=Decimal(str(payload["o"])),
        high=Decimal(str(payload["h"])),
        low=Decimal(str(payload["l"])),
        close=Decimal(str(payload["c"])),
        volume=Decimal(str(payload["v"])),
        quote_volume=Decimal(str(payload.get("q", "0"))),
        trade_count=int(payload.get("n", 0)),
        is_closed=bool(payload.get("x", False)),
    )


# --------------------------------------------------------------------------- #
# SDK log bridge (research D4): the SDK reports through root `logging.*` calls.
# --------------------------------------------------------------------------- #

_SDK_PATH_MARKERS: tuple[str, ...] = ("/binance_common/", "/binance_sdk_")


class _SdkLogBridge(logging.Handler):
    """Forward WARNING+ records raised inside the Binance SDK packages to structlog.

    `WebSocketCommon.connect` swallows every exception and reports it with the root
    `logging.error(...)` function (research D4), so without a handler a failed connect
    is invisible in the structured output. Records from other libraries are ignored.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            path = record.pathname.replace("\\", "/")
            if not any(marker in path for marker in _SDK_PATH_MARKERS):
                return
            emit = log.error if record.levelno >= logging.ERROR else log.warning
            emit("paper_ws.sdk_log", sdk_level=record.levelname, message=record.getMessage())
        except Exception:
            self.handleError(record)


def install_sdk_log_bridge() -> None:
    """Attach the SDK log bridge to the stdlib root logger once (idempotent)."""
    root = logging.getLogger()
    if any(isinstance(handler, _SdkLogBridge) for handler in root.handlers):
        return
    root.addHandler(_SdkLogBridge())


def _safe_url(url: str | None) -> str | None:
    """Drop userinfo and query from a URL before logging (no credentials in logs)."""
    if not url:
        return url
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _sdk_stream_map() -> dict[Any, Any]:
    """The SDK's module-global stream-name -> connection map (research D3/D7).

    Looked up through the module at call time so tests can swap it for an isolated map.
    """
    stream_map: dict[Any, Any] = sdk_websocket.global_stream_connections.stream_connections_map
    return stream_map


# --------------------------------------------------------------------------- #
# Frozen value types returned by the adapter (no SDK type inside).
# --------------------------------------------------------------------------- #

# Connection lifecycle events the runtime may observe (ping/pong are not lifecycle events).
LIFECYCLE_EVENTS: tuple[str, ...] = ("open", "reconnect", "close", "error")

ClientFactory = Callable[
    [ConfigurationWebSocketStreams], DerivativesTradingUsdsFuturesWebSocketStreams
]


@dataclass(frozen=True)
class RebuildReport:
    """What `PaperWsAdapter.rebuild` found, so a live smoke can tell the two close paths apart.

    `stale_stream_names_found` lists the adapter's own stream names that were still in the SDK
    global stream map when `rebuild` started: non-empty after an unsolicited close (the SDK's
    discard path keeps the names, research D3), empty after a user-initiated close (the SDK
    forgets them). The counts are SDK connections before and after the rebuild (D5: the SDK
    opens one socket per url path).
    """

    stale_stream_names_found: tuple[str, ...]
    connections_before: int
    connections_after: int


@dataclass(frozen=True)
class WsDiagnostics:
    """Read-only snapshot for operators and the live smoke evidence."""

    connection_count: int
    subscribed_streams: tuple[str, ...]
    stale_stream_names: tuple[str, ...]


@dataclass
class _Subscription:
    """One recorded kline subscription, kept so `rebuild` can replay it.

    `retired_handles` holds the SDK handles that `rebuild` replaced, so that a handle the caller
    received before a rebuild still names this subscription (16-43 investigation, Finding 2).
    """

    symbol: str
    interval: str
    on_kline: Callable[[Kline], None]
    stream_id: str | None
    handle: Any = None
    retired_handles: list[Any] = field(default_factory=list)

    @property
    def stream_name(self) -> str:
        return f"{self.symbol.lower()}@kline_{self.interval}"


# --------------------------------------------------------------------------- #
# Adapter — single owner of WS Streams imports.
# --------------------------------------------------------------------------- #


class PaperWsAdapter:
    """Project-owned wrapper around `DerivativesTradingUsdsFuturesWebSocketStreams`.

    Every SDK call is awaited (`create_connection` and `kline_candlestick_streams` are
    coroutines). The real `RequestStreamHandle` exposes only `on` and `unsubscribe`, so the
    adapter has no handle-level reconnect or close. The SDK owns reconnection (23 h rotation,
    serverShutdown reconnect, research D2); the adapter only reports connection events
    through `on_connection`, and offers `rebuild` for the one case the SDK does not recover
    from: an unsolicited close (research D3).

    Tests inject a fake `ws_client` and a `client_factory` (see `tests/paper_ws_fakes.py`,
    which `tests/test_paper_ws_contract.py` binds to the installed SDK) so unit tests never
    touch the network.

    The adapter normalizes SDK response models to frozen `Kline` instances; SDK types never
    leave this module. It never touches an order or account endpoint.
    """

    def __init__(
        self,
        ws_client: DerivativesTradingUsdsFuturesWebSocketStreams | None = None,
        configuration: ConfigurationWebSocketStreams | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._configuration: ConfigurationWebSocketStreams = (
            configuration
            if configuration is not None
            else ConfigurationWebSocketStreams(
                stream_url=DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
            )
        )
        self._client_factory: ClientFactory = (
            client_factory
            if client_factory is not None
            else DerivativesTradingUsdsFuturesWebSocketStreams
        )
        if ws_client is not None:
            self._ws: DerivativesTradingUsdsFuturesWebSocketStreams = ws_client
        else:
            self._ws = self._client_factory(self._configuration)
        self._subscriptions: list[_Subscription] = []
        self._connection_callbacks: list[tuple[str, Callable[..., None]]] = []
        self.last_rebuild: RebuildReport | None = None

    @property
    def configuration(self) -> ConfigurationWebSocketStreams:
        """The SDK configuration this adapter builds its client from."""
        return self._configuration

    # -- connection ---------------------------------------------------------- #

    async def connect(self) -> None:
        """Open the SDK connections and fail loudly when none was produced.

        `WebSocketCommon.connect` swallows every exception and returns None (research D4), so
        `create_connection` never raises on a failed connect: the connection list is checked
        instead, and `ConnectionError` is raised so a dead stream is never silent.
        """
        install_sdk_log_bridge()
        await self._ws.create_connection()  # type: ignore[no-untyped-call]  # SDK is untyped
        if not self._ws.connections:
            log.error(
                "paper_ws.connect_failed",
                client_type=type(self._ws).__name__,
                stream_url=_safe_url(self._configuration.stream_url),
            )
            raise ConnectionError("Binance WS create_connection produced no connection")
        # The SDK registers a connection callback only on existing connections and copies it
        # to replacement connections, so (re-)apply the recorded callbacks after a connect.
        for event, callback in self._connection_callbacks:
            self._ws.on_connection(event, callback)

    def on_connection(self, event: str, callback: Callable[..., None]) -> None:
        """Observe an SDK connection event (open, reconnect, close or error).

        The callback runs on the event-loop thread (research D6): it must only record or
        enqueue, never block or do I/O. Recorded so it is re-applied after `connect` and
        `rebuild`.
        """
        if event not in LIFECYCLE_EVENTS:
            raise ValueError(
                f"unsupported connection event {event!r}; supported: {list(LIFECYCLE_EVENTS)}"
            )
        if (event, callback) not in self._connection_callbacks:
            self._connection_callbacks.append((event, callback))
        if self._ws.connections:
            self._ws.on_connection(event, callback)

    async def close(self) -> None:
        """User-initiated shutdown: close every SDK connection and forget the subscriptions."""
        await self._ws.close_connection()
        self._subscriptions.clear()

    # -- subscriptions ------------------------------------------------------- #

    async def subscribe(
        self,
        *,
        symbol: str,
        interval: str,
        on_kline: Callable[[Kline], None],
        stream_id: str | None = None,
    ) -> Any:
        """Subscribe to a kline stream and dispatch each event to `on_kline`.

        `symbol` is the Binance symbol (e.g. "btcusdt"); the SDK stream name is lowercase.
        `interval` is one of `ALLOWED_INTERVALS` ("1m", "1h", "4h").
        `on_kline` receives a frozen `Kline` per event (forming candles included; filtering
        stays in the supervisor).
        `stream_id` is an optional unique request ID.

        Returns the underlying SDK stream handle; pass it to `unsubscribe`. The handle stays
        valid across `rebuild`: `unsubscribe` resolves it to the subscription's current SDK
        handle (16-43 investigation, Finding 2).
        """
        if interval not in ALLOWED_INTERVALS:
            raise ValueError(
                f"unsupported interval {interval!r}; supported: {sorted(ALLOWED_INTERVALS)}"
            )
        sub = _Subscription(
            symbol=symbol, interval=interval, on_kline=on_kline, stream_id=stream_id
        )
        await self._open_stream(sub)
        self._subscriptions.append(sub)
        return sub.handle

    def _subscription_of(self, handle: Any) -> _Subscription | None:
        """The subscription whose current or retired SDK handle is this object (identity)."""
        for sub in self._subscriptions:
            if sub.handle is handle or any(old is handle for old in sub.retired_handles):
                return sub
        return None

    async def unsubscribe(self, handle: Any) -> None:
        """Unsubscribe one stream (awaits the SDK handle) and stop replaying it on rebuild.

        `handle` is what `subscribe` returned. After a `rebuild` that handle belongs to the
        closed client, so it is resolved to the subscription's CURRENT SDK handle and that one
        is unsubscribed (16-43 investigation, Finding 2). A handle the adapter never returned is
        awaited as given and no subscription is dropped. If the SDK call raises, the
        subscription stays, so a later rebuild still replays it.
        """
        sub = self._subscription_of(handle)
        if sub is None:
            await handle.unsubscribe()
            return
        await sub.handle.unsubscribe()
        self._subscriptions = [other for other in self._subscriptions if other is not sub]

    async def _open_stream(self, sub: _Subscription) -> None:
        symbol = sub.symbol
        interval = sub.interval
        on_kline = sub.on_kline
        # The SDK types `interval` as its Enum but builds the stream name with str(); the
        # plain string is what produces `btcusdt@kline_1h` (research (b)).
        handle = await self._ws.kline_candlestick_streams(
            symbol=symbol.lower(),
            interval=cast(Any, interval),
            id=sub.stream_id,
        )

        def _on_message(message: Any) -> None:
            # Hardened dispatch (CR-04): one malformed payload must
            # never propagate into the SDK dispatch thread and kill
            # the stream, and unknown envelopes must be logged, never
            # silently dropped.
            try:
                payload = _extract_kline_payload(message)
            except Exception as exc:
                log.warning(
                    "paper_ws.extract_failed",
                    error=repr(exc),
                    message_type=type(message).__name__,
                )
                return
            if payload is None:
                log.warning(
                    "paper_ws.unknown_envelope",
                    message_type=type(message).__name__,
                )
                return
            try:
                kline = _normalize_kline_payload(symbol, interval, payload)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning(
                    "paper_ws.normalize_failed",
                    error=repr(exc),
                )
                return
            on_kline(kline)

        handle.on("message", _on_message)
        if sub.handle is not None:
            sub.retired_handles.append(sub.handle)
        sub.handle = handle

    # -- recovery and diagnostics -------------------------------------------- #

    def _own_stream_names(self) -> tuple[str, ...]:
        return tuple(sub.stream_name for sub in self._subscriptions)

    def _forget_own_streams(self) -> None:
        """Remove this adapter's own stream names from the SDK global stream map.

        After an unsolicited close the SDK's `_discard_connection` does not forget the dead
        connection's streams (research D3), and `WebSocketStreamBase.subscribe` skips every
        stream still in the map, so a plain re-subscribe would send nothing. The map is
        module-global and shared by all clients (research D7), so only the exact names this
        adapter subscribed are removed; foreign entries are never touched.

        UNVERIFIED LIVE until plan 16-21: this behaviour is derived from reading
        `binance_common` 4.4.0, not from a forced disconnect against Binance.
        """
        stream_map = _sdk_stream_map()
        for name in self._own_stream_names():
            stream_map.pop(name, None)

    async def rebuild(self) -> None:
        """Recover from an unsolicited close: fresh client, reconnect, replay subscriptions.

        Records a `RebuildReport` (`last_rebuild`) BEFORE touching the SDK stream map so a live
        smoke can prove which close path it exercised. The supervisor ignores the result.
        """
        own_names = self._own_stream_names()
        stream_map = _sdk_stream_map()
        stale_found = tuple(name for name in own_names if name in stream_map)
        connections_before = len(self._ws.connections)

        try:
            # Release the remaining sockets and the aiohttp session of the dead client.
            await self._ws.close_connection()
        except Exception as exc:
            log.warning("paper_ws.rebuild_old_close_failed", error=repr(exc))
        self._forget_own_streams()

        self._ws = self._client_factory(self._configuration)
        await self.connect()
        for sub in self._subscriptions:
            await self._open_stream(sub)

        self.last_rebuild = RebuildReport(
            stale_stream_names_found=stale_found,
            connections_before=connections_before,
            connections_after=len(self._ws.connections),
        )
        log.info(
            "paper_ws.rebuilt",
            stale_stream_names_found=list(stale_found),
            connections_before=connections_before,
            connections_after=self.last_rebuild.connections_after,
        )

    def sdk_connections(self) -> tuple[Any, ...]:
        """Read-only snapshot of the SDK connection objects of the current client.

        Used by the public-data live smoke (plan 16-17) to drop the transport beneath the SDK
        connections; nothing in the paper runtime uses it. The objects are SDK internals and
        must not leave operator tooling.
        """
        return tuple(self._ws.connections)

    def diagnostics(self) -> WsDiagnostics:
        """Read-only snapshot: SDK connection count, own streams, own streams left stale.

        A stale name is one of the adapter's own streams still mapped in the SDK global map to
        a connection that is no longer open.
        """
        stream_map = _sdk_stream_map()
        live = list(self._ws.connections)
        stale: list[str] = []
        for name in self._own_stream_names():
            mapped = stream_map.get(name)
            if mapped is not None and not any(mapped is connection for connection in live):
                stale.append(name)
        return WsDiagnostics(
            connection_count=len(live),
            subscribed_streams=self._own_stream_names(),
            stale_stream_names=tuple(stale),
        )


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _as_dict(value: Any) -> dict[str, Any] | None:
    """Coerce an SDK model to a plain dict, or None if impossible.

    The SDK may deliver response objects with attributes instead of
    raw dicts (CR-04) — support `dict` passthrough, `to_dict()` /
    `model_dump()` carriers, and `__dict__` attribute bags.
    """
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
        except Exception:
            return None
        return result if isinstance(result, dict) else None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            result = model_dump()
        except Exception:
            return None
        return result if isinstance(result, dict) else None
    bag = getattr(value, "__dict__", None)
    if isinstance(bag, dict) and bag:
        return dict(bag)
    return None


def _extract_kline_payload(message: Any) -> dict[str, Any] | None:
    """Extract the kline payload from a WS message.

    The SDK wraps kline events in a `{stream, data}` envelope; the
    `data` field carries the kline payload. This helper unwraps the
    envelope and returns the kline dict, or None if the message is
    not a kline event. Attribute-style SDK models are coerced via
    `_as_dict` so they are never silently dropped (CR-04). Bare
    kline-shaped dicts (wire fields, no envelope) are accepted; any
    other shape returns None and the caller logs the envelope type.
    """
    envelope = _as_dict(message)
    if envelope is None:
        return None
    if "data" in envelope:
        data_dict = _as_dict(envelope["data"])
        if data_dict is None:
            return None
        return _as_dict(data_dict.get("k"))
    if "k" in envelope:
        return _as_dict(envelope["k"])
    if "t" in envelope and "T" in envelope:
        return envelope
    return None


__all__ = [
    "ALLOWED_INTERVALS",
    "LIFECYCLE_EVENTS",
    "Kline",
    "PaperWsAdapter",
    "RebuildReport",
    "WsDiagnostics",
    "install_sdk_log_bridge",
]
