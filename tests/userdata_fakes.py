"""SDK-shaped fakes for the user-data stream adapter tests (Phase 18, plan 18-11, D-01, D-02).

Every fake mirrors the installed `binance-sdk-derivatives-trading-usds-futures` 17.4.0 /
`binance-common` 4.4.0 surface the adapter uses, and `tests/test_userdata_contract.py` binds
them to the installed SDK (coroutine-ness, parameter names, handle members). The structure
follows `tests/paper_ws_fakes.py` (Phase 16); its classes are not imported here, only
`fresh_sdk_stream_map` is reused.

No network is touched and no real SDK client is constructed here.

Messages are built from the SDK's own pydantic models around the synthetic frames of
`tests/support/userdata_frames.py` (SYNTHETIC, never captured Binance data): the real callback
payload is a `UserDataStreamEventsResponse` holding either a parsed model or, on the SDK's
raw-dict fallback (research P4), a plain dict.
"""

from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from binance_common import websocket as sdk_websocket
from binance_common.models import ApiResponse
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    KeepaliveUserDataStreamResponse,
    StartUserDataStreamResponse,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.order_trade_update import (  # noqa: E501
    OrderTradeUpdate,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.user_data_stream_events_response import (  # noqa: E501
    UserDataStreamEventsResponse,
)

from tests.paper_ws_fakes import fresh_sdk_stream_map
from tests.support.userdata_frames import order_trade_update_frame

# Mirrors binance_common.constants.SUPPORTED_CONNECTION_EVENTS (pinned by the contract test).
SUPPORTED_CONNECTION_EVENTS: frozenset[str] = frozenset(
    {"open", "ping", "pong", "reconnect", "close", "error"}
)

# A synthetic, obviously fake listenKey of 64 alphanumeric characters (the documented key
# length). It is NOT a credential and was never issued by Binance.
TEST_ONLY_LISTEN_KEY = ("TestOnlyListenKeyNotACredential" + "A1b2C3d4" * 5)[:64]
TEST_ONLY_SECOND_LISTEN_KEY = ("TestOnlySecondListenKeyNotACredential" + "Z9y8X7w6" * 5)[:64]


def _sdk_stream_map() -> dict[Any, Any]:
    stream_map: dict[Any, Any] = sdk_websocket.global_stream_connections.stream_connections_map
    return stream_map


# --------------------------------------------------------------------------- #
# Messages built from the SDK models.
# --------------------------------------------------------------------------- #


def make_order_trade_update_message(**overrides: Any) -> UserDataStreamEventsResponse:
    """A real SDK `UserDataStreamEventsResponse` around a real `OrderTradeUpdate` model.

    Keyword overrides replace keys of the synthetic frame's `o` object (see
    `order_trade_update_frame`); the frame is validated by the SDK model, never handed over
    as a plain dict.
    """
    model = OrderTradeUpdate.from_dict(order_trade_update_frame(**overrides))
    return UserDataStreamEventsResponse(model)


def make_raw_dict_message(frame: dict[str, Any]) -> UserDataStreamEventsResponse:
    """The SDK's raw-dict fallback: the wrapper holding a plain dict (`_wrap_raw_payload`)."""
    return UserDataStreamEventsResponse.model_construct(actual_instance=frame)


# --------------------------------------------------------------------------- #
# WebSocket Streams fakes.
# --------------------------------------------------------------------------- #


def _invoke_connection_callback(callback: Callable[..., None], *args: Any) -> None:
    """Call `callback` with as many positional arguments as it accepts (SDK behaviour).

    Mirrors `WebSocketCommon._invoke_connection_callback`: ping and pong pass the payload,
    error passes the error, and the argument list is trimmed to the callback's signature.
    """
    if args:
        try:
            parameters = list(inspect.signature(callback).parameters.values())
        except (TypeError, ValueError):
            parameters = None
        if parameters is not None:
            accepted = 0
            for parameter in parameters:
                if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
                    accepted = len(args)
                    break
                if parameter.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                ):
                    accepted += 1
            args = args[:accepted]
    try:
        callback(*args)
    except Exception as exc:  # the SDK isolates callback failures and logs them
        logging.error(f"Error in connection callback: {type(exc).__name__}")


class FakeConnection:
    """Stand-in for `binance_common.websocket.WebSocketConnection` (identity and maps only)."""

    def __init__(self, connection_id: int, url_path: str) -> None:
        self.id = connection_id
        self.url_path = url_path
        self.is_open = True
        self.stream_callback_map: dict[str, list[Callable[[Any], None]]] = {}
        self.connection_callback_map: defaultdict[str, list[Callable[..., None]]] = defaultdict(
            list
        )


class FakeUserStreamHandle:
    """Mirrors `binance_common.websocket.RequestStreamHandle`.

    Public members are exactly `on` (sync, only the event "message") and `unsubscribe`
    (async). Recorded state is underscore-prefixed so it stays off the mirrored surface.
    """

    def __init__(self, client: FakeUserDataWsClient, stream: str) -> None:
        self._client = client
        self._stream = stream
        self._unsubscribed = 0

    def on(self, event: str, callback: Callable[[Any], None]) -> None:
        if event != "message":
            raise ValueError(f"Unsupported stream event: {event}")
        self._client.on(event, callback, self._stream)

    async def unsubscribe(self) -> None:
        self._unsubscribed += 1
        await self._client._unsubscribe_stream(self._stream)


class FakeUserDataWsClient:
    """Mirrors `DerivativesTradingUsdsFuturesWebSocketStreams` (the surface the adapter uses).

    Behaviour copied from the installed SDK source (research F1 items 4 and 5, P6):

    - `create_connection` opens one connection per url path (market, public, private);
      `produce_connection=False` models the SDK swallowing a failed connect (D4). An optional
      `on_create_connection` hook runs first (a test uses it to log the way the SDK reports a
      swallowed connect failure).
    - `user_data(listenKey)` maps the bare listenKey to the private connection in the
      module-global stream map and records the SUBSCRIBE frame only for a name not already
      mapped (`WebSocketStreamBase.subscribe` filters mapped names).
    - `on(event, callback, stream)` appends the callback to the connection the stream is
      mapped to (`WebSocketStreamBase.on`).
    - `close_connection()` is the user-initiated close: connections leave `connections` and
      their stream names are forgotten (`_close_one` + `_forget_connection_streams`).
    - `on_connection(event, callback, connection=None)` registers on the given connection, or
      on every connection when None; an exact duplicate is ignored; with no connection the
      registration is dropped (the SDK warns).
    - `simulate_unsolicited_close()` mirrors `_emit_close_event` + `_discard_connection`: the
      close callbacks fire, the connection leaves `connections`, the stream names STAY mapped.
    """

    URL_PATHS = ("market", "public", "private")

    def __init__(
        self,
        *,
        produce_connection: bool = True,
        on_create_connection: Callable[[], None] | None = None,
    ) -> None:
        self.produce_connection = produce_connection
        self.on_create_connection = on_create_connection
        self.connections: list[Any] = []
        self.create_connection_calls = 0
        self.close_calls = 0
        self.close_should_raise: BaseException | None = None
        self.subscribe_frames: list[dict[str, Any]] = []
        self.unsubscribed_streams: list[str] = []
        self.handles: list[FakeUserStreamHandle] = []
        self.dropped_connection_callbacks = 0
        self._next_connection_id = 1

    # -- mirrored SDK surface ------------------------------------------------ #

    async def create_connection(self) -> None:
        self.create_connection_calls += 1
        if self.on_create_connection is not None:
            self.on_create_connection()
        if not self.produce_connection:
            return
        for url_path in self.URL_PATHS:
            self.connections.append(FakeConnection(self._next_connection_id, url_path))
            self._next_connection_id += 1

    async def user_data(self, listenKey: str) -> FakeUserStreamHandle:  # noqa: N803 - SDK name
        if not self.connections:
            raise ValueError("No WebSocket connections available.")
        stream_map = _sdk_stream_map()
        private = [c for c in self.connections if c.url_path == "private"]
        if listenKey not in stream_map and private:
            connection = private[0]
            self.subscribe_frames.append(
                {"method": "SUBSCRIBE", "params": [listenKey], "id": len(self.subscribe_frames)}
            )
            stream_map[listenKey] = connection
            connection.stream_callback_map[listenKey] = []
        handle = FakeUserStreamHandle(self, listenKey)
        self.handles.append(handle)
        return handle

    def on(self, event: str, callback: Callable[[Any], None], stream: str) -> None:
        if event != "message":
            raise ValueError(f"Unsupported event: {event}")
        connection = _sdk_stream_map().get(stream)
        if connection is not None:
            connection.stream_callback_map.setdefault(stream, []).append(callback)

    async def close_connection(self, connection: Any = None, close_session: bool = True) -> None:
        self.close_calls += 1
        if self.close_should_raise is not None:
            raise self.close_should_raise
        closing = list(self.connections) if connection is None else [connection]
        stream_map = _sdk_stream_map()
        for closed in closing:
            closed.is_open = False
            if closed in self.connections:
                self.connections.remove(closed)
            for stream in [name for name, mapped in stream_map.items() if mapped is closed]:
                stream_map.pop(stream, None)

    def on_connection(
        self,
        event: str,
        callback: Callable[..., None],
        connection: Any = None,
    ) -> None:
        if event not in SUPPORTED_CONNECTION_EVENTS:
            raise ValueError(f"Unsupported connection event: {event}")
        targets = list(self.connections) if connection is None else [connection]
        if not targets:
            self.dropped_connection_callbacks += 1
            return
        for target in targets:
            registered = target.connection_callback_map[event]
            if callback not in registered:
                registered.append(callback)

    # -- test helpers (not part of the mirrored SDK surface) ----------------- #

    async def _unsubscribe_stream(self, stream: str) -> None:
        stream_map = _sdk_stream_map()
        connection = stream_map.pop(stream, None)
        if connection is not None:
            connection.stream_callback_map.pop(stream, None)
            self.unsubscribed_streams.append(stream)

    def connection_for(self, url_path: str) -> FakeConnection | None:
        for connection in self.connections:
            if connection.url_path == url_path:
                found: FakeConnection = connection
                return found
        return None

    def emit_user_event(self, stream: str, message: Any) -> int:
        """Deliver `message` the way the SDK receive loop routes a `stream` envelope.

        Returns the number of callbacks invoked (0 when the stream is not mapped to an open
        connection of this client, which is what the SDK would do: the message would reach
        only its INFO log).
        """
        connection = _sdk_stream_map().get(stream)
        if connection is None or connection not in self.connections or not connection.is_open:
            return 0
        callbacks = list(connection.stream_callback_map.get(stream, []))
        for callback in callbacks:
            callback(message)
        return len(callbacks)

    def emit_connection_event(self, url_path: str, event: str, *args: Any) -> None:
        """Emit a connection event on the connection of `url_path` with the SDK's arguments."""
        connection = self.connection_for(url_path)
        if connection is None:
            return
        for callback in list(connection.connection_callback_map.get(event, [])):
            _invoke_connection_callback(callback, *args)

    def registered_events(self, url_path: str) -> dict[str, int]:
        """How many callbacks are registered per event on the connection of `url_path`."""
        connection = self.connection_for(url_path)
        if connection is None:
            return {}
        return {
            event: len(callbacks)
            for event, callbacks in connection.connection_callback_map.items()
            if callbacks
        }

    def simulate_unsolicited_close(self, url_path: str = "private") -> None:
        """Mirror the SDK's unsolicited CLOSE: emit close, discard, keep the stream names."""
        connection = self.connection_for(url_path)
        if connection is None:
            return
        connection.is_open = False
        for callback in list(connection.connection_callback_map.get("close", [])):
            _invoke_connection_callback(callback)
        self.connections.remove(connection)


# --------------------------------------------------------------------------- #
# REST user-data stream API fake.
# --------------------------------------------------------------------------- #


class FakeRestUserDataApi:
    """Mirrors the three synchronous listenKey methods of the SDK REST API.

    `start_user_data_stream`, `keepalive_user_data_stream` and `close_user_data_stream` take
    no argument (the SDK signatures) and return an `ApiResponse` whose `data()` is the SDK
    response model with `listen_key` (alias `listenKey`). `fail_next(name, exc)` scripts one
    raised SDK error for the next call of `name`; `calls[name]` counts every call, including
    the failing ones.
    """

    METHODS = ("start_user_data_stream", "keepalive_user_data_stream", "close_user_data_stream")

    def __init__(
        self,
        *,
        listen_keys: tuple[str, ...] = (TEST_ONLY_LISTEN_KEY,),
        keepalive_listen_key: str | None = None,
        start_returns_no_key: bool = False,
    ) -> None:
        self._listen_keys = list(listen_keys)
        self._keepalive_listen_key = keepalive_listen_key
        self._start_returns_no_key = start_returns_no_key
        self.calls: dict[str, int] = dict.fromkeys(self.METHODS, 0)
        self._failures: dict[str, list[BaseException]] = {name: [] for name in self.METHODS}

    def fail_next(self, name: str, exc: BaseException) -> None:
        if name not in self.METHODS:
            raise ValueError(f"unknown method {name}")
        self._failures[name].append(exc)

    def _enter(self, name: str) -> None:
        self.calls[name] += 1
        if self._failures[name]:
            raise self._failures[name].pop(0)

    def start_user_data_stream(self) -> ApiResponse[StartUserDataStreamResponse]:
        self._enter("start_user_data_stream")
        if self._start_returns_no_key:
            model = StartUserDataStreamResponse()
        else:
            key = self._listen_keys.pop(0) if len(self._listen_keys) > 1 else self._listen_keys[0]
            model = StartUserDataStreamResponse(listenKey=key)
        return ApiResponse(data_function=lambda: model, status=200, headers={})

    def keepalive_user_data_stream(self) -> ApiResponse[KeepaliveUserDataStreamResponse]:
        self._enter("keepalive_user_data_stream")
        if self._keepalive_listen_key is None:
            model = KeepaliveUserDataStreamResponse()
        else:
            model = KeepaliveUserDataStreamResponse(listenKey=self._keepalive_listen_key)
        return ApiResponse(data_function=lambda: model, status=200, headers={})

    def close_user_data_stream(self) -> ApiResponse[None]:
        self._enter("close_user_data_stream")
        return ApiResponse(data_function=lambda: None, status=200, headers={})


__all__ = [
    "SUPPORTED_CONNECTION_EVENTS",
    "TEST_ONLY_LISTEN_KEY",
    "TEST_ONLY_SECOND_LISTEN_KEY",
    "FakeConnection",
    "FakeRestUserDataApi",
    "FakeUserDataWsClient",
    "FakeUserStreamHandle",
    "fresh_sdk_stream_map",
    "make_order_trade_update_message",
    "make_raw_dict_message",
]
