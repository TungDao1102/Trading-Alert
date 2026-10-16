"""Binance USD-M user-data stream adapter over the official SDK (Phase 18, plan 18-11, D-01, D-02).

This is the only module that imports the Binance SDK user-data surface for the stream: the
REST listenKey calls (`start_user_data_stream`, `keepalive_user_data_stream`,
`close_user_data_stream`) and event delivery through
`DerivativesTradingUsdsFuturesWebSocketStreams.user_data(listenKey)` on the `/private`
connection (research F1). SDK types stay inside: the raw stream callback hands the SDK object
to the SDK-free parser of `src/adapters/binance_userdata_events.py` and only the typed event,
or a `StreamAnomaly`, leaves on a bounded queue. Nothing here imports `src.paper` (D-03), and
the composition into a running process is Phase 24 (D-04).

The adapter makes no liveness claim (threat T-18-29): whether the SDK's SUBSCRIBE with a bare
listenKey is accepted and events arrive in the envelope the SDK routes is settled by the live
smoke (plan 18-18); plan 18-19 is the gated direct fallback. The supervisor of plan 18-14
drives the primitives exposed here.

No wall clock is read: every timestamp comes from the injected clock. No number is defined
here: the queue bound comes from the ratified `StreamLimits`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import structlog
from binance_common import websocket as sdk_websocket
from binance_common.configuration import ConfigurationWebSocketStreams
from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (
    DerivativesTradingUsdsFuturesWebSocketStreams,
)
from src.adapters.binance_limits import StreamLimits
from src.adapters.binance_userdata_events import (
    StreamAnomalyKind,
    StreamOutcome,
    make_stream_anomaly,
    parse_stream_message,
    unwrap_message,
)

log = structlog.get_logger()

# The url path of the SDK connection that carries the user-data stream (research F1 item 5).
PRIVATE_URL_PATH = "private"

MessageSink = Callable[[object], None]
ConnectionSink = Callable[[str], None]
Clock = Callable[[], datetime]
ClientFactory = Callable[
    [ConfigurationWebSocketStreams], DerivativesTradingUsdsFuturesWebSocketStreams
]


def _sdk_stream_map() -> dict[Any, Any]:
    """The SDK's module-global stream-name -> connection map (research P6).

    Looked up through the module attribute at call time so tests can swap it.
    """
    stream_map: dict[Any, Any] = sdk_websocket.global_stream_connections.stream_connections_map
    return stream_map


# --------------------------------------------------------------------------- #
# Project-owned interfaces (D-01).
# --------------------------------------------------------------------------- #


class ListenKeyPort(Protocol):
    """The listenKey lifecycle: start (returns the key), keepalive, close."""

    async def start(self) -> str: ...

    async def keepalive(self) -> None: ...

    async def close(self) -> None: ...


class UserDataTransport(Protocol):
    """A connection that delivers the user-data stream of one listenKey.

    The message sink receives whatever the transport's stream callback receives (an SDK
    object or a plain dict); the connection sink receives a connection event name. Both
    sinks run on the event-loop thread and must only record or enqueue.
    """

    async def connect(self, listen_key: str) -> None: ...

    async def close(self) -> None: ...

    async def rebuild(self, listen_key: str) -> None: ...

    def set_message_sink(self, sink: MessageSink) -> None: ...

    def set_connection_sink(self, sink: ConnectionSink) -> None: ...

    def private_connection_open(self) -> bool: ...

    def diagnostics(self) -> object: ...


# --------------------------------------------------------------------------- #
# Value types (no SDK type inside).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class QueuedStreamItem:
    """One parsed stream message: the outcome, when it was received, and on which connection.

    `connection_epoch` is the adapter epoch at receipt; it increases on every successful
    connect, rebuild and rekey, so a consumer can tell events of a replaced connection apart.
    """

    outcome: StreamOutcome
    received_at_utc: datetime
    connection_epoch: int


@dataclass(frozen=True)
class TransportDiagnostics:
    """Read-only snapshot of the SDK transport (no listenKey, no SDK object).

    `stale_listen_key_names_found` counts the transport's own listenKey names that were still
    in the SDK stream map when the last rebuild started (a name is a credential, so only the
    count is reported).
    """

    connection_count: int
    private_connection_open: bool
    subscribed: bool
    rebuild_count: int
    stale_listen_key_names_found: int


# --------------------------------------------------------------------------- #
# SDK transport.
# --------------------------------------------------------------------------- #


class SdkUserDataTransport:
    """The user-data stream over `DerivativesTradingUsdsFuturesWebSocketStreams.user_data`.

    Follows `src/adapters/paper_ws.py`: every SDK call is awaited; `create_connection`
    swallows connect errors (research D4), so the connection list is checked and a
    `ConnectionError` naming no URL is raised when no `/private` connection exists. The
    configuration is built by the caller from the environment row and is never defaulted
    here. Tests inject an SDK-shaped fake client and factory.
    """

    def __init__(
        self,
        configuration: ConfigurationWebSocketStreams,
        client_factory: ClientFactory | None = None,
        ws_client: DerivativesTradingUsdsFuturesWebSocketStreams | None = None,
    ) -> None:
        self._configuration = configuration
        self._client_factory: ClientFactory = (
            client_factory
            if client_factory is not None
            else DerivativesTradingUsdsFuturesWebSocketStreams
        )
        self._ws: DerivativesTradingUsdsFuturesWebSocketStreams = (
            ws_client if ws_client is not None else self._client_factory(configuration)
        )
        self._message_sink: MessageSink | None = None
        self._connection_sink: ConnectionSink | None = None
        # Kept only to forget its name in the SDK stream map; never logged.
        self._listen_key: str | None = None
        self._rebuild_count = 0
        self._stale_found = 0

    def __repr__(self) -> str:
        return f"{type(self).__name__}(connections={len(self._ws.connections)})"

    # -- sinks --------------------------------------------------------------- #

    def set_message_sink(self, sink: MessageSink) -> None:
        self._message_sink = sink

    def set_connection_sink(self, sink: ConnectionSink) -> None:
        self._connection_sink = sink

    def _dispatch_message(self, message: object) -> None:
        sink = self._message_sink
        if sink is None:
            return
        try:
            sink(message)
        except Exception as exc:  # never raise into the SDK receive loop (research P5)
            log.error("userdata.message_sink_failed", error_type=type(exc).__name__)

    # -- connection ---------------------------------------------------------- #

    def _private_connections(self) -> list[Any]:
        return [c for c in self._ws.connections if c.url_path == PRIVATE_URL_PATH]

    def private_connection_open(self) -> bool:
        """True when the current client holds an open `/private` connection."""
        return any(
            getattr(connection, "is_open", False) is True
            for connection in self._private_connections()
        )

    async def connect(self, listen_key: str) -> None:
        """Open the SDK connections, then SUBSCRIBE the bare listenKey on `/private`."""
        await self._ws.create_connection()  # type: ignore[no-untyped-call]  # SDK is untyped
        if not self._private_connections():
            log.error(
                "userdata.connect_failed",
                client_type=type(self._ws).__name__,
                connection_count=len(self._ws.connections),
            )
            raise ConnectionError("Binance WS create_connection produced no private connection")
        handle = await self._ws.user_data(listen_key)
        handle.on("message", self._dispatch_message)
        self._listen_key = listen_key

    async def close(self) -> None:
        """User-initiated close: every SDK connection closes and the SDK forgets its streams."""
        await self._ws.close_connection()
        self._forget_own_name()
        self._listen_key = None

    def _forget_own_name(self) -> None:
        """Remove exactly this transport's listenKey name from the SDK stream map."""
        if self._listen_key is not None:
            _sdk_stream_map().pop(self._listen_key, None)

    async def rebuild(self, listen_key: str) -> None:
        raise NotImplementedError

    def diagnostics(self) -> TransportDiagnostics:
        return TransportDiagnostics(
            connection_count=len(self._ws.connections),
            private_connection_open=self.private_connection_open(),
            subscribed=self._listen_key is not None,
            rebuild_count=self._rebuild_count,
            stale_listen_key_names_found=self._stale_found,
        )


# --------------------------------------------------------------------------- #
# Adapter.
# --------------------------------------------------------------------------- #


class UserDataAdapter:
    """Typed events of the user-data stream on a bounded queue, plus lifecycle primitives.

    The raw SDK callback only enqueues and never raises (research P5, threat T-18-30): an
    unrecognised message becomes a `StreamAnomaly` item, an exception inside the parser a
    MALFORMED_PAYLOAD anomaly item.
    """

    def __init__(
        self,
        *,
        transport: UserDataTransport,
        listen_keys: ListenKeyPort,
        limits: StreamLimits,
        clock: Clock,
    ) -> None:
        if not isinstance(limits, StreamLimits):
            raise TypeError("limits must be StreamLimits")
        self._transport = transport
        self._listen_keys = listen_keys
        self._limits = limits
        self._clock = clock
        self._queue: asyncio.Queue[QueuedStreamItem] = asyncio.Queue(maxsize=limits.event_queue_max)
        self._epoch = 0
        self._listen_key: str | None = None
        self._overflowed = False
        self._overflow_count = 0
        transport.set_message_sink(self._on_raw_message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(epoch={self._epoch}, queued={self._queue.qsize()})"

    # -- read-only state ----------------------------------------------------- #

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def queue(self) -> asyncio.Queue[QueuedStreamItem]:
        return self._queue

    # -- lifecycle ----------------------------------------------------------- #

    async def start(self) -> None:
        """Obtain a listenKey from the port, connect the transport; the epoch increases."""
        key = await self._listen_keys.start()
        await self._transport.connect(key)
        self._listen_key = key
        self._epoch += 1

    # -- raw callback -------------------------------------------------------- #

    def _parse(self, message: object, received_at: datetime) -> StreamOutcome:
        try:
            return parse_stream_message(message, observed_at_utc=received_at)
        except Exception as exc:
            try:
                event_name, payload = unwrap_message(message)
            except Exception:
                event_name, payload = None, None
            return make_stream_anomaly(
                StreamAnomalyKind.MALFORMED_PAYLOAD,
                event_name=event_name,
                field=None,
                detail=f"parser raised {type(exc).__name__}",
                payload=payload,
                observed_at_utc=received_at,
            )

    def _on_raw_message(self, message: object) -> None:
        """The SDK stream callback: parse and enqueue, never raise (research P5)."""
        try:
            received_at = self._clock()
            item = QueuedStreamItem(
                outcome=self._parse(message, received_at),
                received_at_utc=received_at,
                connection_epoch=self._epoch,
            )
            self._enqueue(item)
        except Exception as exc:
            log.error("userdata.raw_callback_failed", error_type=type(exc).__name__)

    def _enqueue(self, item: QueuedStreamItem) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._overflow_count += 1
            if not self._overflowed:
                log.warning("userdata.queue_overflow", queue_max=self._limits.event_queue_max)
            self._overflowed = True


__all__ = [
    "PRIVATE_URL_PATH",
    "ListenKeyPort",
    "QueuedStreamItem",
    "SdkUserDataTransport",
    "TransportDiagnostics",
    "UserDataAdapter",
    "UserDataTransport",
]
