"""SDK-shaped fakes for the paper WebSocket tests (Phase 16, plan 16-01, D-09).

Every fake here mirrors the installed `binance-sdk-derivatives-trading-usds-futures`
17.4.0 / `binance-common` 4.4.0 async surface, verified by
`tests/test_paper_ws_contract.py` (coroutine-ness, parameter names, handle
members). The earlier fakes exposed a fictional API (`on_message`, handle-level
`reconnect` / `close`) that the real `RequestStreamHandle` does not have, so CI
passed while the real SDK did nothing (F-125, F-607).

No network is touched and no real SDK client is constructed here.

Kline events are built from the SDK's own pydantic models, never hand-written
dicts (research D8): the real callback payload is a `KlineCandlestickStreamsResponse`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from binance_common import websocket as sdk_websocket
from binance_common.websocket import StreamConnectionsMap
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models import (
    KlineCandlestickStreamsResponse,
    KlineCandlestickStreamsResponseK,
)

# Mirrors binance_common.constants.SUPPORTED_CONNECTION_EVENTS (research constants table).
SUPPORTED_CONNECTION_EVENTS: frozenset[str] = frozenset(
    {"open", "ping", "pong", "reconnect", "close", "error"}
)


def make_kline_model(
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    open_time_ms: int = 1_791_360_000_000,
    close_time_ms: int = 1_791_363_599_999,
    open_: str = "84094.70",
    high: str = "84139.20",
    low: str = "83902.50",
    close: str = "83909.90",
    volume: str = "5844.590",
    quote_volume: str = "490868445.00560",
    trade_count: int = 179_437,
    is_closed: bool = True,
    event_time_ms: int | None = None,
) -> KlineCandlestickStreamsResponse:
    """Build a real SDK `KlineCandlestickStreamsResponse` (never a plain dict)."""
    return KlineCandlestickStreamsResponse(
        e="kline",
        E=close_time_ms + 1 if event_time_ms is None else event_time_ms,
        s=symbol,
        k=KlineCandlestickStreamsResponseK(
            t=open_time_ms,
            T=close_time_ms,
            s=symbol,
            i=interval,
            o=open_,
            c=close,
            h=high,
            l=low,
            v=volume,
            n=trade_count,
            x=is_closed,
            q=quote_volume,
        ),
    )


def fresh_sdk_stream_map(monkeypatch: Any) -> StreamConnectionsMap:
    """Replace the SDK's module-global stream map with an empty one for one test (research D7).

    `binance_common.websocket.global_stream_connections` is shared by every client in the
    process, so any behavioural test must isolate it. `monkeypatch` restores the original on
    teardown. Both the fakes and `PaperWsAdapter` read the attribute at call time.
    """
    replacement = StreamConnectionsMap()
    monkeypatch.setattr(sdk_websocket, "global_stream_connections", replacement)
    return replacement


def _sdk_stream_map() -> dict[Any, Any]:
    stream_map: dict[Any, Any] = sdk_websocket.global_stream_connections.stream_connections_map
    return stream_map


class FakeConnection:
    """Stand-in for `binance_common.websocket.WebSocketConnection` (identity only)."""

    def __init__(self, connection_id: int, url_path: str) -> None:
        self.id = connection_id
        self.url_path = url_path


class FakeStreamHandle:
    """Mirrors `binance_common.websocket.RequestStreamHandle`.

    Public members are exactly `on` (sync) and `unsubscribe` (async). Recorded state and the
    `_emit` helper are underscore-prefixed so they stay off the mirrored public surface.
    """

    def __init__(self, stream: str) -> None:
        self._stream = stream
        self._callbacks: list[Callable[[Any], None]] = []
        self._unsubscribed = 0

    def on(self, event: str, callback: Callable[[Any], None]) -> None:
        if event != "message":
            raise ValueError(f"Unsupported stream event: {event}")
        self._callbacks.append(callback)

    async def unsubscribe(self) -> None:
        self._unsubscribed += 1

    # -- test helpers (underscore: not part of the mirrored public surface) --

    def _emit(self, message: Any) -> None:
        for callback in list(self._callbacks):
            callback(message)


class FakeSdkWsClient:
    """Mirrors `DerivativesTradingUsdsFuturesWebSocketStreams` (async surface only).

    Behaviour copied from the installed SDK source (research D3, D4, D5, D7):

    - `create_connection` opens one connection per url path (market, public, private).
      `produce_connection=False` models the SDK swallowing a failed connect (D4).
    - `kline_candlestick_streams` maps the stream to the market connection in the module-global
      stream map and sends SUBSCRIBE only for streams not already mapped (D3).
    - `simulate_unsolicited_close()` mirrors `_discard_connection`: the dead connection leaves
      `connections`, "close" connection callbacks fire, the stream names STAY in the map.
    - `close_connection()` mirrors the user-initiated `_close_one`: connections leave
      `connections` and their stream names are forgotten.
    - `on_connection` registers only when connections exist (the SDK warns and drops otherwise)
      and ignores an exact duplicate registration.
    """

    URL_PATHS = ("market", "public", "private")

    def __init__(self, *, produce_connection: bool = True) -> None:
        self.produce_connection = produce_connection
        self.connections: list[Any] = []
        self.create_connection_calls = 0
        self.close_calls = 0
        self.kline_calls: list[tuple[str, Any, Any]] = []
        self.subscribe_frames: list[str] = []
        self.handles: list[FakeStreamHandle] = []
        self.connection_callbacks: dict[str, list[Callable[..., None]]] = defaultdict(list)
        self.dropped_connection_callbacks = 0
        self._next_connection_id = 1

    async def create_connection(self) -> None:
        self.create_connection_calls += 1
        if not self.produce_connection:
            return
        for url_path in self.URL_PATHS:
            self.connections.append(FakeConnection(self._next_connection_id, url_path))
            self._next_connection_id += 1

    async def kline_candlestick_streams(
        self,
        symbol: str | None,
        interval: Any,
        id: str | None = None,  # noqa: A002 - mirrors the SDK parameter name
    ) -> FakeStreamHandle:
        self.kline_calls.append((str(symbol), interval, id))
        stream = f"{symbol}@kline_{interval}"
        market = [c for c in self.connections if c.url_path == "market"]
        if not market:
            raise ValueError("No WebSocket connections available.")
        stream_map = _sdk_stream_map()
        if stream not in stream_map:
            stream_map[stream] = market[0]
            self.subscribe_frames.append(stream)
        handle = FakeStreamHandle(stream)
        self.handles.append(handle)
        return handle

    async def close_connection(self, connection: Any = None, close_session: bool = True) -> None:
        self.close_calls += 1
        closing = list(self.connections) if connection is None else [connection]
        stream_map = _sdk_stream_map()
        for closed in closing:
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
        if not self.connections:
            self.dropped_connection_callbacks += 1
            return
        if callback not in self.connection_callbacks[event]:
            self.connection_callbacks[event].append(callback)

    # -- test helpers (not part of the mirrored SDK surface) --

    def simulate_unsolicited_close(self) -> None:
        """Mirror the SDK's unsolicited CLOSE: emit close, discard, keep the stream names."""
        market = [c for c in self.connections if c.url_path == "market"]
        for dead in market:
            for callback in list(self.connection_callbacks["close"]):
                callback()
            self.connections.remove(dead)
