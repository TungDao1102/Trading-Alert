"""Contract test binding the WS fakes to the installed SDK (Phase 16 D-09).

F-125 / F-607: the paper WS tests used fakes with a fictional API (`on_message`,
handle-level `reconnect` / `close`, synchronous calls) while the real SDK has an
async surface and a handle with only `on` and `unsubscribe`. These tests fail CI
whenever a fake is synchronous where the SDK is asynchronous, or exposes a handle
API the SDK does not have.

No network is touched: only the installed SDK *classes* are introspected. No SDK
client is ever constructed or connected here (research D7: the stream map in
`binance_common.websocket` is module-global and would leak between tests).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from binance_common import websocket as sdk_websocket
from binance_common.websocket import RequestStreamHandle
from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (
    DerivativesTradingUsdsFuturesWebSocketStreams as SdkClient,
)

from tests.paper_ws_fakes import FakeSdkWsClient, FakeStreamHandle

_CLIENT_COROUTINES = ("create_connection", "kline_candlestick_streams", "close_connection")
_CLIENT_SIGNATURES = ("kline_candlestick_streams", "close_connection", "on_connection")


def _params(fn: Any) -> list[str]:
    """Parameter names without `self`."""
    return [name for name in inspect.signature(fn).parameters if name != "self"]


def _public_members(cls: type) -> set[str]:
    return {name for name in dir(cls) if not name.startswith("_")}


def assert_mirrors_sdk_async_surface(client_cls: type, handle_cls: type) -> None:
    """Raise AssertionError naming the first method where a fake departs from the SDK."""
    for name in _CLIENT_COROUTINES:
        assert inspect.iscoroutinefunction(getattr(SdkClient, name)), f"SDK {name} not async"
        assert inspect.iscoroutinefunction(getattr(client_cls, name, None)), (
            f"fake client method {name} must be a coroutine function like the SDK"
        )
    for name in _CLIENT_SIGNATURES:
        assert _params(getattr(client_cls, name)) == _params(getattr(SdkClient, name)), (
            f"fake client method {name} parameter names differ from the SDK"
        )
    assert not inspect.iscoroutinefunction(SdkClient.on_connection)
    assert not inspect.iscoroutinefunction(getattr(client_cls, "on_connection", None)), (
        "fake client method on_connection must be synchronous like the SDK"
    )
    assert not inspect.iscoroutinefunction(RequestStreamHandle.on)
    assert not inspect.iscoroutinefunction(getattr(handle_cls, "on", None)), (
        "fake handle method on must be synchronous like the SDK"
    )
    assert inspect.iscoroutinefunction(RequestStreamHandle.unsubscribe)
    assert inspect.iscoroutinefunction(getattr(handle_cls, "unsubscribe", None)), (
        "fake handle method unsubscribe must be a coroutine function like the SDK"
    )
    assert _params(handle_cls.on) == _params(RequestStreamHandle.on), (  # type: ignore[attr-defined]
        "fake handle method on parameter names differ from the SDK"
    )
    assert _public_members(handle_cls) == _public_members(RequestStreamHandle), (
        "fake handle public members must equal the SDK handle's public members"
    )


def test_every_fake_mirrors_the_installed_sdk_async_surface() -> None:
    assert_mirrors_sdk_async_surface(FakeSdkWsClient, FakeStreamHandle)


def test_sdk_client_methods_are_coroutines_and_fakes_follow() -> None:
    for name in _CLIENT_COROUTINES:
        assert inspect.iscoroutinefunction(getattr(SdkClient, name)), name
        assert inspect.iscoroutinefunction(getattr(FakeSdkWsClient, name)), name


def test_fake_parameter_names_equal_the_sdk() -> None:
    for name in _CLIENT_SIGNATURES:
        assert _params(getattr(FakeSdkWsClient, name)) == _params(getattr(SdkClient, name)), name


def test_stream_handle_has_only_on_and_unsubscribe() -> None:
    assert not inspect.iscoroutinefunction(RequestStreamHandle.on)
    assert inspect.iscoroutinefunction(RequestStreamHandle.unsubscribe)
    assert not inspect.iscoroutinefunction(FakeStreamHandle.on)
    assert inspect.iscoroutinefunction(FakeStreamHandle.unsubscribe)
    assert _public_members(RequestStreamHandle) == {"on", "unsubscribe"}
    assert _public_members(FakeStreamHandle) == {"on", "unsubscribe"}


def test_negative_control_synchronous_fake_is_rejected() -> None:
    """The helper must raise for a fake that is synchronous where the SDK is async."""

    class _SyncClient:
        def create_connection(self) -> None:  # SDK: coroutine
            return None

        def kline_candlestick_streams(
            self, symbol: str | None, interval: Any, id: str | None = None
        ) -> FakeStreamHandle:
            return FakeStreamHandle("x")

        def close_connection(self, connection: Any = None, close_session: bool = True) -> None:
            return None

        def on_connection(self, event: str, callback: Any, connection: Any = None) -> None:
            return None

    with pytest.raises(AssertionError, match="create_connection"):
        assert_mirrors_sdk_async_surface(_SyncClient, FakeStreamHandle)


def test_negative_control_handle_with_fictional_api_is_rejected() -> None:
    """A handle exposing `on_message` / `reconnect` / `close` (the old fakes) is rejected."""

    class _FictionalHandle:
        def on(self, event: str, callback: Any) -> None:
            return None

        async def unsubscribe(self) -> None:
            return None

        def on_message(self, callback: Any) -> None:  # not on the real handle
            return None

        def reconnect(self) -> None:  # not on the real handle
            return None

    with pytest.raises(AssertionError, match="public members"):
        assert_mirrors_sdk_async_surface(FakeSdkWsClient, _FictionalHandle)


def test_sdk_global_stream_map_exists() -> None:
    """`PaperWsAdapter.rebuild` edits this map (research D3/D7); an SDK bump that moves it fails CI.

    Installed shape: `global_stream_connections` is a `StreamConnectionsMap` object whose
    `stream_connections_map` attribute is the dict of stream name -> connection.
    """
    holder = sdk_websocket.global_stream_connections
    assert isinstance(holder.stream_connections_map, dict)
