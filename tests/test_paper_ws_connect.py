"""Paper WS adapter on the real SDK shape (Phase 16, plan 16-01, D-08/D-09).

History: Phase 7 CR-04 pinned a fail-loud lifecycle against fakes that exposed a
fictional API (`on_message`, handle-level `reconnect` / `close`). The 2026-10-04
live probe showed the real SDK has none of those: `create_connection` and
`kline_candlestick_streams` are coroutines, the interval is a plain string in the
stream name, and `RequestStreamHandle` has only `on` and `unsubscribe` (F-125,
F-607).

Every fake used here comes from `tests/paper_ws_fakes.py`, which
`tests/test_paper_ws_contract.py` binds to the installed SDK. No network is
touched and no real SDK client is connected.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from binance_common.constants import DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
from src.adapters.paper_ws import Kline, PaperWsAdapter
from structlog.testing import capture_logs

from tests.paper_ws_fakes import (
    FakeSdkWsClient,
    FakeStreamHandle,
    fresh_sdk_stream_map,
    make_kline_model,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the SDK module-global stream map per test (research D7)."""
    return fresh_sdk_stream_map(monkeypatch)


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


# --------------------------------------------------------------------------- #
# Awaited connect and subscribe (tracer: one closed kline end to end).
# --------------------------------------------------------------------------- #


async def test_connect_awaits_create_connection_once_with_prod_stream_url() -> None:
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]

    await adapter.connect()

    assert fake.create_connection_calls == 1
    assert adapter.configuration.stream_url == DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL


def test_default_client_is_built_from_the_prod_stream_url() -> None:
    """Without an injected client the real SDK client is built, not connected."""
    adapter = PaperWsAdapter()

    # The SDK constructor appends "/stream" to a configured stream_url.
    assert adapter.configuration.stream_url is not None
    assert adapter.configuration.stream_url.startswith(
        DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
    )


async def test_subscribe_passes_lowercase_symbol_and_plain_string_interval() -> None:
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()

    await adapter.subscribe(symbol="BTCUSDT", interval="1h", on_kline=lambda _k: None)

    assert len(fake.kline_calls) == 1
    symbol, interval, _id = fake.kline_calls[0]
    assert symbol == "btcusdt"
    assert interval == "1h"
    assert type(interval) is str  # not an Enum: str(Enum) breaks the stream name


async def test_closed_kline_model_reaches_caller_as_frozen_kline() -> None:
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()
    received: list[Kline] = []
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=received.append)

    fake.handles[0]._emit(make_kline_model(is_closed=True))

    assert len(received) == 1
    kline = received[0]
    assert kline.is_closed is True
    assert kline.open == Decimal("84094.70")
    assert kline.high == Decimal("84139.20")
    assert kline.low == Decimal("83902.50")
    assert kline.close == Decimal("83909.90")
    assert kline.volume == Decimal("5844.590")
    assert kline.quote_volume == Decimal("490868445.00560")
    assert kline.trade_count == 179_437
    assert kline.open_time_utc == _EPOCH + timedelta(milliseconds=1_791_360_000_000)
    assert kline.close_time_utc == _EPOCH + timedelta(milliseconds=1_791_363_599_999)
    assert kline.open_time_utc.tzinfo is UTC
    assert kline.close_time_utc.microsecond == 999_000  # exact to the millisecond
    with pytest.raises(FrozenInstanceError):
        kline.close = Decimal("1")  # type: ignore[misc]


async def test_open_kline_is_delivered_with_is_closed_false() -> None:
    """Filtering forming candles stays in the supervisor (SC7), not the adapter."""
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()
    received: list[Kline] = []
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=received.append)

    fake.handles[0]._emit(make_kline_model(is_closed=False))

    assert len(received) == 1
    assert received[0].is_closed is False


async def test_subscribe_rejects_unsupported_interval() -> None:
    from src.adapters.paper_ws import ALLOWED_INTERVALS

    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()

    assert frozenset({"1m", "1h", "4h"}) == ALLOWED_INTERVALS
    with pytest.raises(ValueError, match="unsupported interval"):
        await adapter.subscribe(symbol="btcusdt", interval="15m", on_kline=lambda _k: None)
    assert fake.kline_calls == []


# --------------------------------------------------------------------------- #
# Hardened dispatch (Phase 7 CR-04), kept on the real handle shape.
# --------------------------------------------------------------------------- #


async def test_attribute_style_model_is_coerced_not_dropped() -> None:
    """An SDK-style model with to_dict() reaches on_kline instead of vanishing."""

    class _AttrModel:
        def to_dict(self) -> dict[str, Any]:
            return {"stream": "s", "data": {"k": _kline_payload()}}

    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()
    received: list[Kline] = []
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=received.append)

    fake.handles[0]._emit(_AttrModel())

    assert len(received) == 1
    assert received[0].symbol == "btcusdt"
    assert received[0].is_closed is True


async def test_unknown_envelope_is_logged_not_dispatched() -> None:
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()
    received: list[Kline] = []
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=received.append)

    fake.handles[0]._emit({"ack": True})  # junk: no data/k/t/T keys
    fake.handles[0]._emit(42)  # non-dict, non-model

    assert received == []


async def test_malformed_payload_does_not_kill_stream() -> None:
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()
    received: list[Kline] = []
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=received.append)

    fake.handles[0]._emit({"stream": "s", "data": {"k": {"t": 1}}})  # missing keys
    fake.handles[0]._emit({"stream": "s", "data": {"k": _kline_payload()}})

    assert len(received) == 1


# --------------------------------------------------------------------------- #
# Lifecycle on the real SDK shape (Task 3): connect check, events, unsubscribe,
# close, rebuild and diagnostics.
# --------------------------------------------------------------------------- #

_OWN_STREAMS = ("btcusdt@kline_1h", "ethusdt@kline_4h")


async def _two_stream_adapter(
    first: FakeSdkWsClient, clients: list[FakeSdkWsClient]
) -> tuple[PaperWsAdapter, list[Kline], list[Kline]]:
    """Adapter on `first`, rebuilding through a factory that records the clients it builds."""

    def factory(_configuration: Any) -> Any:
        client = FakeSdkWsClient()
        clients.append(client)
        return client

    adapter = PaperWsAdapter(ws_client=first, client_factory=factory)  # type: ignore[arg-type]
    await adapter.connect()
    btc: list[Kline] = []
    eth: list[Kline] = []
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=btc.append)
    await adapter.subscribe(symbol="ethusdt", interval="4h", on_kline=eth.append)
    return adapter, btc, eth


async def test_connect_without_any_sdk_connection_raises_and_logs() -> None:
    """D4: the SDK swallows a failed connect; the adapter must not look healthy."""
    fake = FakeSdkWsClient(produce_connection=False)
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]

    with capture_logs() as logs, pytest.raises(ConnectionError):
        await adapter.connect()

    assert any(entry["event"] == "paper_ws.connect_failed" for entry in logs)


@pytest.mark.parametrize("event", ["open", "reconnect", "close", "error"])
async def test_on_connection_registers_lifecycle_events_on_the_sdk_client(event: str) -> None:
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()

    def callback(*_args: Any) -> None:
        return None

    adapter.on_connection(event, callback)

    assert fake.connection_callbacks[event] == [callback]


@pytest.mark.parametrize("event", ["ping", "pong", "message", "bogus"])
async def test_on_connection_rejects_other_events(event: str) -> None:
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()

    with pytest.raises(ValueError, match="unsupported connection event"):
        adapter.on_connection(event, lambda *_a: None)

    assert not fake.connection_callbacks


async def test_on_connection_before_connect_is_applied_after_connect() -> None:
    """The SDK drops a connection callback when no connection exists yet."""
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]

    def callback(*_args: Any) -> None:
        return None

    adapter.on_connection("reconnect", callback)
    assert fake.dropped_connection_callbacks == 0  # not forwarded while unconnected
    await adapter.connect()

    assert fake.connection_callbacks["reconnect"] == [callback]


async def test_unsubscribe_awaits_the_handle_and_close_awaits_close_connection() -> None:
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()
    handle = await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=lambda _k: None)

    await adapter.unsubscribe(handle)
    assert handle._unsubscribed == 1

    await adapter.close()
    assert fake.close_calls == 1
    assert fake.connections == []


async def test_rebuild_after_unsolicited_close_resubscribes_own_streams_only(
    sdk_stream_map: Any,
) -> None:
    first = FakeSdkWsClient()
    clients: list[FakeSdkWsClient] = []
    adapter, btc, eth = await _two_stream_adapter(first, clients)
    foreign = object()
    sdk_stream_map.stream_connections_map["foo@kline_1m"] = foreign
    old_handles = list(first.handles)
    assert [len(h._callbacks) for h in old_handles] == [1, 1]

    first.simulate_unsolicited_close()
    # The SDK keeps the dead connection's stream names (D3): a plain re-subscribe sends nothing.
    assert set(_OWN_STREAMS) <= set(sdk_stream_map.stream_connections_map)

    await adapter.rebuild()

    assert len(clients) == 1
    new = clients[0]
    assert new.create_connection_calls == 1
    assert new.subscribe_frames == list(_OWN_STREAMS)  # SUBSCRIBE really sent for both
    assert [(s, i) for s, i, _ in new.kline_calls] == [("btcusdt", "1h"), ("ethusdt", "4h")]
    assert sdk_stream_map.stream_connections_map["foo@kline_1m"] is foreign  # foreign untouched
    # P3 duplicate-callback guard: one callback per new handle, none added to the old handles.
    assert [len(h._callbacks) for h in new.handles] == [1, 1]
    assert [len(h._callbacks) for h in old_handles] == [1, 1]
    assert first.close_calls == 1  # the dead client was released best-effort
    # The same caller callbacks keep working through the new handles.
    new.handles[0]._emit(make_kline_model(is_closed=True))
    new.handles[1]._emit(make_kline_model(symbol="ETHUSDT", interval="4h", is_closed=True))
    assert len(btc) == 1
    assert len(eth) == 1


async def test_rebuild_reapplies_connection_callbacks_on_the_new_client() -> None:
    first = FakeSdkWsClient()
    clients: list[FakeSdkWsClient] = []
    adapter, _btc, _eth = await _two_stream_adapter(first, clients)

    def callback(*_args: Any) -> None:
        return None

    adapter.on_connection("close", callback)
    first.simulate_unsolicited_close()
    await adapter.rebuild()

    assert clients[0].connection_callbacks["close"] == [callback]


async def test_rebuild_does_not_resubscribe_an_unsubscribed_stream() -> None:
    first = FakeSdkWsClient()
    clients: list[FakeSdkWsClient] = []
    adapter, _btc, _eth = await _two_stream_adapter(first, clients)
    await adapter.unsubscribe(first.handles[0])

    first.simulate_unsolicited_close()
    await adapter.rebuild()

    assert clients[0].subscribe_frames == ["ethusdt@kline_4h"]


async def test_a_handle_from_before_a_rebuild_unsubscribes_the_current_stream() -> None:
    """16-43 Finding 2: the handle `subscribe` returned stays valid across a rebuild."""
    first = FakeSdkWsClient()
    clients: list[FakeSdkWsClient] = []
    adapter, _btc, _eth = await _two_stream_adapter(first, clients)
    btc_old = first.handles[0]

    first.simulate_unsolicited_close()
    await adapter.rebuild()
    await adapter.unsubscribe(btc_old)

    assert clients[0].handles[0]._unsubscribed == 1
    assert btc_old._unsubscribed == 0
    assert adapter.diagnostics().subscribed_streams == ("ethusdt@kline_4h",)

    clients[0].simulate_unsolicited_close()
    await adapter.rebuild()
    assert clients[1].subscribe_frames == ["ethusdt@kline_4h"]


async def test_an_unknown_handle_is_still_awaited_and_changes_nothing() -> None:
    first = FakeSdkWsClient()
    clients: list[FakeSdkWsClient] = []
    adapter, _btc, _eth = await _two_stream_adapter(first, clients)
    stranger = FakeStreamHandle("x@kline_1h")

    await adapter.unsubscribe(stranger)

    assert stranger._unsubscribed == 1
    assert adapter.diagnostics().subscribed_streams == _OWN_STREAMS
    assert [h._unsubscribed for h in first.handles] == [0, 0]


def test_adapter_has_no_reconnect_or_schedule_reconnect() -> None:
    """The SDK owns reconnection; the handle has no such operations (D1)."""
    adapter = PaperWsAdapter(ws_client=FakeSdkWsClient())  # type: ignore[arg-type]

    assert not hasattr(adapter, "reconnect")
    assert not hasattr(adapter, "schedule_reconnect")


async def test_unsolicited_and_user_initiated_close_paths_are_distinguishable() -> None:
    """Test 6: the live smoke reads `last_rebuild` to know which path it exercised."""
    first = FakeSdkWsClient()
    clients: list[FakeSdkWsClient] = []
    adapter, _btc, _eth = await _two_stream_adapter(first, clients)
    assert adapter.last_rebuild is None

    first.simulate_unsolicited_close()
    await adapter.rebuild()
    unsolicited = adapter.last_rebuild
    assert unsolicited is not None
    assert unsolicited.stale_stream_names_found == _OWN_STREAMS
    assert unsolicited.connections_before == 2  # public + private survived the market drop
    assert unsolicited.connections_after == 3

    second = clients[0]
    await second.close_connection()  # user-initiated: the SDK forgets the streams
    await adapter.rebuild()
    user_initiated = adapter.last_rebuild
    assert user_initiated is not None
    assert user_initiated.stale_stream_names_found == ()
    assert user_initiated.connections_before == 0
    assert user_initiated.connections_after == 3
    assert len(clients) == 2
    assert clients[1].subscribe_frames == list(_OWN_STREAMS)


async def test_diagnostics_reports_connections_and_stale_streams() -> None:
    first = FakeSdkWsClient()

    def factory(_configuration: Any) -> Any:
        return FakeSdkWsClient()

    adapter = PaperWsAdapter(ws_client=first, client_factory=factory)  # type: ignore[arg-type]
    before = adapter.diagnostics()
    assert before.connection_count == 0
    assert before.subscribed_streams == ()
    assert before.stale_stream_names == ()

    await adapter.connect()
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=lambda _k: None)
    await adapter.subscribe(symbol="ethusdt", interval="4h", on_kline=lambda _k: None)
    connected = adapter.diagnostics()
    assert connected.connection_count == len(first.connections) == 3
    assert connected.subscribed_streams == _OWN_STREAMS
    assert connected.stale_stream_names == ()

    first.simulate_unsolicited_close()
    dropped = adapter.diagnostics()
    assert dropped.connection_count == 2
    assert dropped.stale_stream_names == _OWN_STREAMS  # mapped to a connection that is gone

    # Frozen value holding only plain types (no SDK type leaks out).
    with pytest.raises(FrozenInstanceError):
        dropped.connection_count = 9  # type: ignore[misc]
    assert type(dropped.connection_count) is int
    assert all(
        type(name) is str for name in dropped.subscribed_streams + dropped.stale_stream_names
    )


def test_sdk_log_bridge_forwards_sdk_errors_to_structlog() -> None:
    """D4: the SDK reports through root `logging.error`; the bridge makes it structured output."""
    import logging

    from src.adapters.paper_ws import install_sdk_log_bridge

    install_sdk_log_bridge()
    install_sdk_log_bridge()  # idempotent
    root = logging.getLogger()
    record = logging.LogRecord(
        name="root",
        level=logging.ERROR,
        pathname="C:/x/site-packages/binance_common/websocket.py",
        lineno=194,
        msg="WebSocket failed to connect: boom",
        args=(),
        exc_info=None,
    )
    foreign = logging.LogRecord(
        name="root",
        level=logging.ERROR,
        pathname="C:/x/site-packages/other/lib.py",
        lineno=1,
        msg="unrelated",
        args=(),
        exc_info=None,
    )

    with capture_logs() as logs:
        root.handle(record)
        root.handle(foreign)

    sdk_logs = [entry for entry in logs if entry["event"] == "paper_ws.sdk_log"]
    assert len(sdk_logs) == 1
    assert "boom" in sdk_logs[0]["message"]
