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

from collections.abc import Callable
from typing import Any

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


class FakeStreamHandle:
    """Mirrors `binance_common.websocket.RequestStreamHandle`.

    Public members are exactly `on` (sync) and `unsubscribe` (async); `emit` and
    the recorded state are underscore-free test helpers kept off the public
    surface by living in `_`-prefixed names, so `public members == {on, unsubscribe}`.
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
    """Mirrors `DerivativesTradingUsdsFuturesWebSocketStreams` (async surface only)."""

    def __init__(self) -> None:
        self.connections: list[Any] = []
        self.create_connection_calls = 0
        self.kline_calls: list[tuple[str, Any, Any]] = []
        self.handles: list[FakeStreamHandle] = []

    async def create_connection(self) -> None:
        self.create_connection_calls += 1
        self.connections.append(object())

    async def kline_candlestick_streams(
        self,
        symbol: str | None,
        interval: Any,
        id: str | None = None,  # noqa: A002 - mirrors the SDK parameter name
    ) -> FakeStreamHandle:
        self.kline_calls.append((str(symbol), interval, id))
        handle = FakeStreamHandle(f"{symbol}@kline_{interval}")
        self.handles.append(handle)
        return handle

    async def close_connection(self, connection: Any = None, close_session: bool = True) -> None:
        self.connections.clear()

    def on_connection(
        self,
        event: str,
        callback: Callable[..., None],
        connection: Any = None,
    ) -> None:
        if event not in SUPPORTED_CONNECTION_EVENTS:
            raise ValueError(f"Unsupported connection event: {event}")
