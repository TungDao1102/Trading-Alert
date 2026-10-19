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

The listenKey is a credential (research P3, threat T-18-28). It is registered with the
redactor the moment it is received (`SdkListenKeyPort.start`, a keepalive response carrying a
key) and again, idempotently, as the first statement of every transport entry point that
takes a key (`connect`, `rebuild`, `resubscribe`), before any log line or SDK call that could
carry a URL: the documented path form `/private/ws/<listenKey>` (docs/SOURCES.md, "Facts read
for Phase 18", user-data-streams `#connect` row, a WebFetch summary of 2026-10-16, not verified
live) puts the key in a URL path segment that the redactor's `listenKey=` shape rule does not
match. No exception, event, repr, anomaly or log line of this module carries the key.

The listenKey REST calls make exactly one SDK call each and are never retried here: a 429 or a
418 is reported (`ListenKeyTransient` or `ListenKeyFailure` with the category and the
Retry-After seconds) per the user's record `decisions/18-DEC-O-18-01.md` and its amendment of
2026-10-16. The port holds the process-wide REST rate-limit gate of plan 18-10 (plan 18-14):
`SdkListenKeyPort._rest_call` refuses before sending while a ban or a pause is active and
records a 418 or a 429 in the gate.

No wall clock is read: every timestamp comes from the injected clock. No number is defined
here: the queue bound comes from the ratified `StreamLimits`.
"""

from __future__ import annotations

import asyncio
import copy
import functools
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import structlog
from binance_common import websocket as sdk_websocket
from binance_common.configuration import ConfigurationWebSocketStreams
from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (
    DerivativesTradingUsdsFuturesWebSocketStreams,
)
from src.adapters.binance_errors import error_facts_from_exception
from src.adapters.binance_limits import StreamLimits
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_userdata_events import (
    StreamAnomalyKind,
    StreamOutcome,
    make_stream_anomaly,
    parse_stream_message,
    unwrap_message,
)
from src.domain.exchange_errors import CallKind, ExchangeErrorCategory, classify
from src.ops.redaction import register_runtime_secret, scrub

log = structlog.get_logger()

# The url path of the SDK connection that carries the user-data stream (research F1 item 5).
PRIVATE_URL_PATH = "private"

# The SDK connection events observed on the private connection
# (`binance_common.constants.SUPPORTED_CONNECTION_EVENTS`, pinned by the contract test).
CONNECTION_EVENTS: tuple[str, ...] = ("open", "reconnect", "close", "error", "ping", "pong")

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
    object or a plain dict); the connection sink receives a connection event name (one of
    `CONNECTION_EVENTS`), which the adapter turns into a `ConnectionEvent`. Both sinks run on
    the event-loop thread and must only record or enqueue. Every method that takes a listenKey
    registers it with the redactor as its first statement.
    """

    async def connect(self, listen_key: str) -> None: ...

    async def resubscribe(self, listen_key: str) -> None: ...

    async def close(self) -> None: ...

    async def rebuild(self, listen_key: str) -> None: ...

    def set_message_sink(self, sink: MessageSink) -> None: ...

    def set_connection_sink(self, sink: ConnectionSink) -> None: ...

    def private_connection_open(self) -> bool: ...

    def diagnostics(self) -> object: ...


class _UserDataStreamRestApi(Protocol):
    """The three synchronous listenKey methods of the SDK REST API (no parameter)."""

    def start_user_data_stream(self) -> Any: ...

    def keepalive_user_data_stream(self) -> Any: ...

    def close_user_data_stream(self) -> Any: ...


# --------------------------------------------------------------------------- #
# listenKey errors (no SDK text, no key, no URL).
# --------------------------------------------------------------------------- #


class ListenKeyError(Exception):
    """A failed listenKey call: the category and the Retry-After seconds, nothing else.

    The message names the category only; the SDK exception is neither the cause nor the
    context, so its text (which may carry a URL) never reaches a traceback.
    """

    def __init__(self, category: ExchangeErrorCategory, retry_after_seconds: int | None) -> None:
        super().__init__(f"listenKey call failed: {category.value}")
        self.category = category
        self.retry_after_seconds = retry_after_seconds


class ListenKeyInvalid(ListenKeyError):  # noqa: N818 - public name fixed by plan 18-11
    """INVALID_LISTEN_KEY: the key is gone; the supervisor starts a NEW key (rekey)."""


class ListenKeyTransient(ListenKeyError):  # noqa: N818 - public name fixed by plan 18-11
    """RATE_LIMITED or STATUS_UNKNOWN.

    A report for the supervisor's failure count, not a retry permission: a 429 is never
    retried and pauses every REST call of the process through the shared gate wired by plan
    18-14 (user amendment of 2026-10-16); `retry_after_seconds` is carried so the gate can be
    set from it.
    """


class ListenKeyFailure(ListenKeyError):  # noqa: N818 - public name fixed by plan 18-11
    """IP_BANNED, AUTH_OR_SIGNATURE, an unknown answer or a response without a key."""


_TRANSIENT_CATEGORIES: frozenset[ExchangeErrorCategory] = frozenset(
    {ExchangeErrorCategory.RATE_LIMITED, ExchangeErrorCategory.STATUS_UNKNOWN}
)


# The categories the shared REST gate records: a 418 bans, a 429 pauses every REST call of
# the process (user record 18-DEC-O-18-01.md and its amendment of 2026-10-16).
_GATE_CATEGORIES: frozenset[ExchangeErrorCategory] = frozenset(
    {ExchangeErrorCategory.IP_BANNED, ExchangeErrorCategory.RATE_LIMITED}
)


def _translate(category: ExchangeErrorCategory, retry_after_seconds: int | None) -> ListenKeyError:
    """The listenKey exception of a category classified with `CallKind.LISTEN_KEY`."""
    if category is ExchangeErrorCategory.INVALID_LISTEN_KEY:
        return ListenKeyInvalid(category, retry_after_seconds)
    if category in _TRANSIENT_CATEGORIES:
        return ListenKeyTransient(category, retry_after_seconds)
    return ListenKeyFailure(category, retry_after_seconds)


def _listen_key_of(response: object) -> str | None:
    """The `listen_key` (alias `listenKey`) of an SDK `ApiResponse`, or None."""
    try:
        data = response.data()  # type: ignore[attr-defined]
    except Exception:
        return None
    key = getattr(data, "listen_key", None)
    if isinstance(key, str) and key != "":
        return key
    return None


class SdkListenKeyPort:
    """`ListenKeyPort` over the SDK REST API (`POST`, `PUT`, `DELETE /fapi/v1/listenKey`).

    The SDK methods are synchronous (`requests`), so each runs in a worker thread. All three
    go through `_rest_call`, the port's only SDK call site.

    `rest_gate` is required: the one process-wide `RestRateLimitGate` of plan 18-10, the same
    instance every other REST holder of the process uses (plan 18-14).
    """

    def __init__(self, rest_api: _UserDataStreamRestApi, *, rest_gate: RestRateLimitGate) -> None:
        if not isinstance(rest_gate, RestRateLimitGate):
            raise TypeError("rest_gate must be the process-wide RestRateLimitGate")
        self._rest_api = rest_api
        self._rest_gate = rest_gate

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    async def _rest_call(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        """Make exactly one SDK call in a worker thread; never retry, never sleep.

        The shared gate is checked first: while a ban or a pause is active the gate's
        `RateLimitBanActive` or `RateLimitPauseActive` propagates unchanged and nothing is
        sent. A failure is classified with `CallKind.LISTEN_KEY`; a 418 (IP_BANNED) or a 429
        (RATE_LIMITED) is recorded in the gate, which bans or pauses every REST call of the
        process. The SDK exception is dropped before the translated one is raised, so neither
        its text nor its traceback travels on.
        """
        self._rest_gate.check()
        try:
            result = await asyncio.to_thread(method, **kwargs)
        except Exception as exc:
            facts = error_facts_from_exception(exc)
            category = classify(facts, CallKind.LISTEN_KEY)
        else:
            return result
        if category in _GATE_CATEGORIES:
            self._rest_gate.record(category, facts.retry_after_seconds)
        raise _translate(category, facts.retry_after_seconds)

    async def start(self) -> str:
        """`POST /fapi/v1/listenKey`: the key, registered with the redactor before return."""
        response = await self._rest_call(self._rest_api.start_user_data_stream)
        key = _listen_key_of(response)
        if key is None:
            raise ListenKeyFailure(ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR, None)
        register_runtime_secret(key)
        return key

    async def keepalive(self) -> None:
        """`PUT /fapi/v1/listenKey`; a key carried by the response is registered at once."""
        response = await self._rest_call(self._rest_api.keepalive_user_data_stream)
        key = _listen_key_of(response)
        if key is not None:
            register_runtime_secret(key)

    async def close(self) -> None:
        """`DELETE /fapi/v1/listenKey`: ends the account's stream (research P7)."""
        await self._rest_call(self._rest_api.close_user_data_stream)


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
class ConnectionEvent:
    """One SDK connection event of the private connection (payloads are never kept).

    `epoch` is the adapter epoch when the event arrived; an event emitted while a connect,
    rebuild or rekey is still running carries the epoch from before that operation.
    """

    name: str
    at_utc: datetime
    epoch: int


@dataclass(frozen=True)
class TransportDiagnostics:
    """Read-only snapshot of the SDK transport (no listenKey, no SDK object).

    `stale_listen_key_names_found` counts the transport's own listenKey names that were still
    in the SDK stream map when the last rebuild started (non-zero after an unsolicited close,
    research P6). A name is a credential, so only the count is reported.
    """

    connection_count: int
    private_connection_open: bool
    subscribed: bool
    rebuild_count: int
    stale_listen_key_names_found: int


# --------------------------------------------------------------------------- #
# SDK log noise guard and log bridge (research P3, D4; threat T-18-28).
# --------------------------------------------------------------------------- #

_SDK_PATH_MARKERS: tuple[str, ...] = ("/binance_common/", "/binance_sdk_")

# INFO lines of the SDK that carry account data or the listenKey: the receive loop's
# unrouted-message line, the subscribe line (the stream names are listenKeys) and the
# send line (the SUBSCRIBE params are listenKeys).
_NOISY_SDK_PREFIXES: tuple[str, ...] = (
    "Received message:",
    "Subscribing to streams on WebSocket",
    "Sending message to WebSocket",
)


def _is_sdk_record(record: logging.LogRecord) -> bool:
    path = record.pathname.replace("\\", "/")
    return any(marker in path for marker in _SDK_PATH_MARKERS)


class SdkNoiseGuard(logging.Filter):
    """Reject the SDK's account-data and key-bearing INFO lines (below WARNING only).

    Attached to the root logger, because the SDK logs through module-level `logging.info`
    calls. Records from other libraries are untouched. An SDK record at WARNING or above is
    kept, but its text is scrubbed in place (the SDK's ERROR lines carry the stream name, i.e.
    the listenKey), so it is redacted for every handler, not only for those that carry a
    redacting filter.
    """

    def __init__(self) -> None:
        super().__init__()
        self.suppressed_count = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if not _is_sdk_record(record):
            return True
        if record.levelno >= logging.WARNING:
            try:
                record.msg = scrub(record.getMessage())
            except Exception:
                record.msg = "unreadable SDK log record"
            record.args = None
            return True
        try:
            message = record.getMessage()
        except Exception:
            # An SDK INFO line that cannot be read may still carry account data: drop it.
            self.suppressed_count += 1
            return False
        if message.startswith(_NOISY_SDK_PREFIXES):
            self.suppressed_count += 1
            return False
        return True


def install_sdk_noise_guard() -> SdkNoiseGuard:
    """Attach one `SdkNoiseGuard` to the root logger (idempotent); return the installed guard."""
    root = logging.getLogger()
    for existing in root.filters:
        if isinstance(existing, SdkNoiseGuard):
            return existing
    guard = SdkNoiseGuard()
    root.addFilter(guard)
    return guard


class _UserDataSdkLogBridge(logging.Handler):
    """Forward WARNING+ records raised inside the Binance SDK packages to structlog.

    The SDK swallows connect errors and reports them only through root `logging.error`
    (research D4, P3). The message is scrubbed here and again by the structlog
    `redact_processor`, so a line carrying a registered listenKey appears redacted.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not _is_sdk_record(record):
                return
            message = scrub(record.getMessage())
            emit = log.error if record.levelno >= logging.ERROR else log.warning
            emit("userdata.sdk_log", sdk_level=record.levelname, message=message)
        except Exception:
            self.handleError(record)


def install_sdk_log_bridge() -> None:
    """Attach the user-data SDK log bridge to the stdlib root logger once (idempotent)."""
    root = logging.getLogger()
    if any(isinstance(handler, _UserDataSdkLogBridge) for handler in root.handlers):
        return
    root.addHandler(_UserDataSdkLogBridge())


# --------------------------------------------------------------------------- #
# Raw-frame tap (research F6 "Capturing raw frames").
# --------------------------------------------------------------------------- #


# The module global of `binance_common.websocket` the receive loop calls for every user-data
# payload (imported there from `binance_common.utils`; pinned by the contract test). Looked
# up by name because the SDK does not re-export it.
_PARSE_USER_EVENT = "parse_user_event"


@contextmanager
def capture_raw_user_events(sink: Callable[[object], None]) -> Iterator[None]:
    """Wrap the module-level `parse_user_event` of `binance_common.websocket` while active.

    The sink receives a deep copy of every payload the SDK is about to parse into a model
    (the model drops unknown fields, research P4); the original function still runs and its
    result is returned unchanged. A failing sink is logged by type name and never stops the
    parse. The wrapper is removed on exit, also after an exception. For probe and smoke
    fixtures only: a payload is account data and must not be logged.
    """
    original = getattr(sdk_websocket, _PARSE_USER_EVENT)

    def tapped(payload: Any, response_model_cls: Any) -> Any:
        try:
            sink(copy.deepcopy(payload))
        except Exception as exc:
            log.warning("userdata.raw_tap_sink_failed", error_type=type(exc).__name__)
        return original(payload, response_model_cls)

    setattr(sdk_websocket, _PARSE_USER_EVENT, tapped)
    try:
        yield
    finally:
        setattr(sdk_websocket, _PARSE_USER_EVENT, original)


# --------------------------------------------------------------------------- #
# SDK transport.
# --------------------------------------------------------------------------- #


class SdkUserDataTransport:
    """The user-data stream over `DerivativesTradingUsdsFuturesWebSocketStreams.user_data`.

    Follows `src/adapters/paper_ws.py`: every SDK call is awaited; `create_connection`
    swallows connect errors (research D4), so the connection list is checked and a
    `ConnectionError` naming no URL is raised when no `/private` connection exists. The
    configuration is built by the caller from the environment row and is never defaulted
    here. Connection callbacks are registered on the `/private` connection only. Tests inject
    an SDK-shaped fake client and factory.
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
        # Built once so the SDK's duplicate check recognises a re-registration.
        self._connection_callbacks: dict[str, Callable[[], None]] = {
            name: functools.partial(self._emit_connection, name) for name in CONNECTION_EVENTS
        }
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

    def _emit_connection(self, name: str) -> None:
        """SDK connection callback: forward the event name only (payloads are dropped)."""
        sink = self._connection_sink
        if sink is None:
            return
        try:
            sink(name)
        except Exception as exc:  # the SDK would log the text and swallow it; do it here
            log.error("userdata.connection_sink_failed", error_type=type(exc).__name__)

    # -- connection ---------------------------------------------------------- #

    def _private_connections(self) -> list[Any]:
        return [c for c in self._ws.connections if c.url_path == PRIVATE_URL_PATH]

    def private_connection_open(self) -> bool:
        """True when the current client holds an open `/private` connection."""
        return any(
            getattr(connection, "is_open", False) is True
            for connection in self._private_connections()
        )

    def _apply_connection_callbacks(self) -> None:
        """(Re-)register the connection callbacks on the private connection only."""
        for connection in self._private_connections():
            for name, callback in self._connection_callbacks.items():
                self._ws.on_connection(name, callback, connection)

    async def _subscribe(self, listen_key: str) -> None:
        handle = await self._ws.user_data(listen_key)
        handle.on("message", self._dispatch_message)
        self._listen_key = listen_key

    async def connect(self, listen_key: str) -> None:
        """Open the SDK connections, then SUBSCRIBE the bare listenKey on `/private`."""
        register_runtime_secret(listen_key)
        install_sdk_log_bridge()
        install_sdk_noise_guard()
        if self._ws.connections:
            # A failed earlier attempt left connections on this client (connect raised after
            # `create_connection`): release them and start on a fresh client, so connections
            # and callbacks never accumulate across the supervisor's retries.
            try:
                await self._ws.close_connection()
            except Exception as exc:
                log.warning("userdata.connect_old_close_failed", error_type=type(exc).__name__)
            self._forget_own_name()
            self._listen_key = None
            self._ws = self._client_factory(self._configuration)
        await self._ws.create_connection()  # type: ignore[no-untyped-call]  # SDK is untyped
        if not self._private_connections():
            log.error(
                "userdata.connect_failed",
                client_type=type(self._ws).__name__,
                connection_count=len(self._ws.connections),
            )
            raise ConnectionError("Binance WS create_connection produced no private connection")
        await self._subscribe(listen_key)
        self._apply_connection_callbacks()

    async def resubscribe(self, listen_key: str) -> None:
        """Subscribe a (new) listenKey on the existing private connection.

        The old name is forgotten first, so the SDK's `subscribe` (which skips mapped names)
        sends the SUBSCRIBE and its `_resubscribe_global_streams` never re-sends the old key
        on a later reconnect (research P6, P8). Raises `ConnectionError` when no private
        connection is open; the caller rebuilds instead.
        """
        register_runtime_secret(listen_key)
        if not self.private_connection_open():
            raise ConnectionError("no open private connection to subscribe on")
        self._forget_own_name()
        self._listen_key = None
        await self._subscribe(listen_key)

    async def close(self) -> None:
        """User-initiated close: every SDK connection closes and the SDK forgets its streams."""
        await self._ws.close_connection()
        self._forget_own_name()
        self._listen_key = None

    def _forget_own_name(self) -> None:
        """Remove exactly this transport's listenKey name from the SDK stream map.

        The map is module-global and shared by every client (research P6): foreign entries are
        never touched.
        """
        if self._listen_key is not None:
            _sdk_stream_map().pop(self._listen_key, None)

    async def rebuild(self, listen_key: str) -> None:
        """Recover from an unsolicited close: close the old client, forget the old name,
        create a fresh client, connect and subscribe `listen_key`.

        UNVERIFIED LIVE until plan 18-18: the stale-name behaviour is read from
        `binance_common` 4.4.0, not observed against Binance.
        """
        register_runtime_secret(listen_key)
        old_key = self._listen_key
        stale_found = 1 if old_key is not None and old_key in _sdk_stream_map() else 0
        try:
            # Release the remaining sockets and the aiohttp session of the old client.
            await self._ws.close_connection()
        except Exception as exc:
            log.warning("userdata.rebuild_old_close_failed", error_type=type(exc).__name__)
        self._forget_own_name()
        self._listen_key = None
        self._ws = self._client_factory(self._configuration)
        await self.connect(listen_key)
        self._rebuild_count += 1
        self._stale_found = stale_found
        log.info(
            "userdata.rebuilt",
            stale_listen_key_names_found=stale_found,
            connection_count=len(self._ws.connections),
        )

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
    MALFORMED_PAYLOAD anomaly item, and a full queue sets `overflowed` and counts the loss.
    The supervisor (plan 18-14) drives `start`, `keepalive`, `rekey`, `rebuild` and `stop`.
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
        # The current key, needed for rebuild and for the port's close; never logged.
        self._listen_key: str | None = None
        self._stopped = False
        self._overflowed = False
        self._overflow_count = 0
        self._connection_listener: Callable[[ConnectionEvent], None] | None = None
        transport.set_message_sink(self._on_raw_message)
        transport.set_connection_sink(self._on_connection_event)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(epoch={self._epoch}, queued={self._queue.qsize()})"

    # -- read-only state ----------------------------------------------------- #

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def queue(self) -> asyncio.Queue[QueuedStreamItem]:
        return self._queue

    @property
    def overflowed(self) -> bool:
        return self._overflowed

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    def clear_overflow(self) -> None:
        """Reset the overflow flag (the loss count stays)."""
        self._overflowed = False

    def private_connection_open(self) -> bool:
        return self._transport.private_connection_open()

    def set_connection_listener(self, listener: Callable[[ConnectionEvent], None] | None) -> None:
        """Receive every `ConnectionEvent` of the private connection (event-loop thread)."""
        self._connection_listener = listener

    # -- lifecycle ----------------------------------------------------------- #

    async def start(self) -> None:
        """Obtain a listenKey from the port, connect the transport; the epoch increases."""
        key = await self._listen_keys.start()
        # Held before the connect: if the connect fails, `stop(close_listen_key=True)` can
        # still DELETE the key that exists, and a retry's `rebuild` has it.
        self._listen_key = key
        await self._transport.connect(key)
        self._stopped = False
        self._epoch += 1

    async def keepalive(self) -> None:
        """The port's keepalive; a listenKey error propagates unchanged."""
        await self._listen_keys.keepalive()

    async def rekey(self) -> None:
        """Start a NEW listenKey and move the subscription to it; the epoch increases.

        The new key is subscribed on the existing private connection (the old name is
        forgotten first), or the transport is rebuilt when that connection is gone.
        """
        key = await self._listen_keys.start()
        if self._transport.private_connection_open():
            await self._transport.resubscribe(key)
        else:
            await self._transport.rebuild(key)
        self._listen_key = key
        self._epoch += 1

    async def rebuild(self) -> None:
        """The transport rebuild with the current key; the epoch increases.

        The stored key is proven first with a keepalive: after an outage or a suspend longer
        than the key's lifetime the SUBSCRIBE of an expired key would succeed at the socket
        level and deliver nothing. An invalid key (INVALID_LISTEN_KEY) is replaced by a NEW
        key, as `rekey` does; any other listenKey error propagates and the rebuild is not
        done (fail closed).
        """
        key = self._listen_key
        if key is None:
            raise RuntimeError("the adapter has no listenKey: call start() first")
        try:
            await self._listen_keys.keepalive()
        except ListenKeyInvalid:
            key = await self._listen_keys.start()
        await self._transport.rebuild(key)
        self._listen_key = key
        self._epoch += 1

    async def stop(self, *, close_listen_key: bool) -> None:
        """Close the transport; close the listenKey only when asked (idempotent).

        `close_listen_key` has no default: a DELETE ends the stream of every holder of the
        account's single key (research P7), so the caller decides each time.
        """
        if self._stopped:
            return
        key = self._listen_key
        try:
            await self._transport.close()
        finally:
            # The DELETE is attempted even when the transport close raised, and the adapter
            # is marked stopped only after the close succeeded, so a failed stop can be re-run.
            if close_listen_key and key is not None:
                await self._listen_keys.close()
        self._listen_key = None
        self._stopped = True

    # -- callbacks (event-loop thread, inside the SDK) ----------------------- #

    def _on_connection_event(self, name: str) -> None:
        try:
            listener = self._connection_listener
            if listener is None:
                return
            listener(ConnectionEvent(name=name, at_utc=self._clock(), epoch=self._epoch))
        except Exception as exc:
            log.error("userdata.connection_listener_failed", error_type=type(exc).__name__)

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
    "CONNECTION_EVENTS",
    "PRIVATE_URL_PATH",
    "ConnectionEvent",
    "ListenKeyError",
    "ListenKeyFailure",
    "ListenKeyInvalid",
    "ListenKeyPort",
    "ListenKeyTransient",
    "QueuedStreamItem",
    "SdkListenKeyPort",
    "SdkNoiseGuard",
    "SdkUserDataTransport",
    "TransportDiagnostics",
    "UserDataAdapter",
    "UserDataTransport",
    "capture_raw_user_events",
    "install_sdk_log_bridge",
    "install_sdk_noise_guard",
]
