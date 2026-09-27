"""Paper WS adapter connect/lifecycle fail-loud pins (Phase 7 REVIEW CR-04).

Per CR-04 (fix commit 5f4723f): PaperWsAdapter previously had no connect
path, silently dropped non-dict messages, and reconnect/close were silent
no-ops behind hasattr guards (fail-open: the supervisor recorded a
successful reconnect that never happened).

These tests pin the unit-testable seams of that fix using injected fakes
— no network is touched. The live-SDK subscribe-against-connection smoke
remains manual-only (pre-soak WS leg BLOCKED).
"""

from __future__ import annotations

from typing import Any

import pytest


def _kline_payload(*, t: int = 1_000, T: int = 2_000) -> dict[str, Any]:
    return {
        "t": t,
        "T": T,
        "o": "100.00",
        "h": "100.10",
        "l": "99.95",
        "c": "100.05",
        "v": "1.0",
        "n": 10,
        "x": True,
        "q": "100.0",
    }


class _HandleWithOnMessage:
    def __init__(self) -> None:
        self.callback: Any = None

    def on_message(self, cb: Any) -> None:
        self.callback = cb


class _FakeWsClient:
    """Fake streams client exposing kline_candlestick_streams + connect entry."""

    def __init__(self, *, handle: Any = None, connect_result: Any = "connected") -> None:
        self._handle = handle or _HandleWithOnMessage()
        self._connect_result = connect_result
        self.kline_calls: list[tuple[str, Any]] = []
        self.connect_calls = 0

    def kline_candlestick_streams(
        self, *, symbol: str, interval: Any, id: Any = None
    ) -> Any:
        self.kline_calls.append((symbol, interval))
        return self._handle

    def create_connection(self) -> Any:
        self.connect_calls += 1
        return self._connect_result


class _DeadWsClient:
    """Client exposing no connection entrypoint at all."""

    def kline_candlestick_streams(
        self, *, symbol: str, interval: Any, id: Any = None
    ) -> Any:
        return object()


class _DeadHandle:
    """Handle with no reconnect/close/schedule_reconnect/on_message."""


# --------------------------------------------------------------------------- #
# connect() delegates to the SDK entrypoint; raises loudly without one.
# --------------------------------------------------------------------------- #


def test_connect_delegates_to_create_connection() -> None:
    """connect() opens the WS connection via the SDK entrypoint."""
    from src.adapters.paper_ws import PaperWsAdapter

    adapter = PaperWsAdapter(ws_client=_FakeWsClient())  # type: ignore[arg-type]
    result = adapter.connect()
    assert result == "connected"
    assert adapter._ws.connect_calls == 1


def test_connect_raises_loudly_without_entrypoint() -> None:
    """connect() on a client with no entrypoint raises, never silently OK."""
    from src.adapters.paper_ws import PaperWsAdapter

    adapter = PaperWsAdapter(ws_client=_DeadWsClient())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="no connection entrypoint"):
        adapter.connect()


# --------------------------------------------------------------------------- #
# reconnect/close/schedule_reconnect fail loud on unsupported handles.
# --------------------------------------------------------------------------- #


def test_reconnect_raises_on_handle_without_reconnect() -> None:
    """reconnect() on a handle without reconnect raises (no fake success)."""
    from src.adapters.paper_ws import PaperWsAdapter

    adapter = PaperWsAdapter(ws_client=_FakeWsClient())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="no reconnect"):
        adapter.reconnect(_DeadHandle())


def test_close_raises_on_handle_without_close() -> None:
    """close() on a handle without close raises (no fake success)."""
    from src.adapters.paper_ws import PaperWsAdapter

    adapter = PaperWsAdapter(ws_client=_FakeWsClient())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="no close"):
        adapter.close(_DeadHandle())


def test_schedule_reconnect_raises_on_handle_without_method() -> None:
    """schedule_reconnect() on an unsupported handle raises loudly."""
    from src.adapters.paper_ws import PaperWsAdapter

    adapter = PaperWsAdapter(ws_client=_FakeWsClient())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="no schedule_reconnect"):
        adapter.schedule_reconnect(_DeadHandle())


def test_subscribe_raises_when_handle_has_no_dispatch() -> None:
    """subscribe() with a dispatch-less handle raises, never a dead stream."""

    class _NoDispatchClient:
        def kline_candlestick_streams(
            self, *, symbol: str, interval: Any, id: Any = None
        ) -> Any:
            return object()

    from src.adapters.paper_ws import PaperWsAdapter

    adapter = PaperWsAdapter(ws_client=_NoDispatchClient())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="no on_message"):
        adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=lambda _k: None)


# --------------------------------------------------------------------------- #
# Attribute-style SDK models are coerced, never silently dropped.
# --------------------------------------------------------------------------- #


def test_attribute_style_model_is_coerced_not_dropped() -> None:
    """An SDK model with to_dict() reaches on_kline instead of vanishing."""

    class _AttrModel:
        def to_dict(self) -> dict[str, Any]:
            return {"stream": "s", "data": {"k": _kline_payload()}}

    from src.adapters.paper_ws import PaperWsAdapter

    received: list[Any] = []
    adapter = PaperWsAdapter(ws_client=_FakeWsClient())  # type: ignore[arg-type]
    adapter.subscribe(
        symbol="btcusdt", interval="1h", on_kline=received.append
    )
    handle = adapter._ws._handle
    assert handle.callback is not None
    handle.callback(_AttrModel())
    assert len(received) == 1
    assert received[0].symbol == "btcusdt"
    assert received[0].is_closed is True


def test_unknown_envelope_is_logged_not_dispatched() -> None:
    """A junk message dispatches nothing (caller logs unknown_envelope)."""
    from src.adapters.paper_ws import PaperWsAdapter

    received: list[Any] = []
    adapter = PaperWsAdapter(ws_client=_FakeWsClient())  # type: ignore[arg-type]
    adapter.subscribe(
        symbol="btcusdt", interval="1h", on_kline=received.append
    )
    handle = adapter._ws._handle
    handle.callback({"ack": True})  # junk: no data/k/t/T keys
    handle.callback(42)  # non-dict, non-model
    assert received == []


def test_malformed_payload_does_not_kill_stream() -> None:
    """A KeyError-shaped payload is contained; the next good one flows."""
    from src.adapters.paper_ws import PaperWsAdapter

    received: list[Any] = []
    adapter = PaperWsAdapter(ws_client=_FakeWsClient())  # type: ignore[arg-type]
    adapter.subscribe(
        symbol="btcusdt", interval="1h", on_kline=received.append
    )
    handle = adapter._ws._handle
    handle.callback({"stream": "s", "data": {"k": {"t": 1}}})  # missing keys
    handle.callback({"stream": "s", "data": {"k": _kline_payload()}})
    assert len(received) == 1
