"""The SDK-backed user-data stream adapter (Phase 18, plan 18-11, D-01, D-02, EXEC-05, OPS-02).

Every SDK object here is either an SDK-shaped fake from `tests/userdata_fakes.py` (bound to the
installed SDK by `tests/test_userdata_contract.py`) or a real SDK pydantic model built from a
SYNTHETIC frame. No network is touched, no real SDK client is constructed, and the SDK's
module-global stream map is isolated per test (research P6, P18). The facts the fakes mirror
come from reading the installed SDK source; the SDK's live behaviour is established by plan
18-18, not here.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from binance_common.configuration import ConfigurationWebSocketStreams
from src.adapters import binance_userdata as bud
from src.adapters.binance_userdata import (
    QueuedStreamItem,
    SdkUserDataTransport,
    UserDataAdapter,
)
from src.adapters.binance_userdata_events import (
    OrderUpdateEvent,
    StreamAnomaly,
    StreamAnomalyKind,
    to_fill_event,
)
from src.execution.fill_monitor import FillEvent
from src.ops import redaction

from tests.support.limits import test_only_stream_limits
from tests.support.userdata_frames import order_trade_update_frame
from tests.userdata_fakes import (
    TEST_ONLY_LISTEN_KEY,
    FakeUserDataWsClient,
    fresh_sdk_stream_map,
    make_order_trade_update_message,
    make_raw_dict_message,
)

TEST_ONLY_NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
TEST_ONLY_STREAM_URL = "wss://example.invalid"


def _clock() -> datetime:
    return TEST_ONLY_NOW


@pytest.fixture(autouse=True)
def sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the SDK module-global stream map per test (research P6, P18)."""
    return fresh_sdk_stream_map(monkeypatch)


@pytest.fixture(autouse=True)
def _isolated_redactor() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


class _StubListenKeys:
    """A minimal ListenKeyPort for the Task 1 slice (the SDK port is tested further down)."""

    def __init__(self, key: str = TEST_ONLY_LISTEN_KEY) -> None:
        self.key = key
        self.starts = 0
        self.keepalives = 0
        self.closes = 0

    async def start(self) -> str:
        self.starts += 1
        return self.key

    async def keepalive(self) -> None:
        self.keepalives += 1

    async def close(self) -> None:
        self.closes += 1


def _configuration() -> ConfigurationWebSocketStreams:
    return ConfigurationWebSocketStreams(stream_url=TEST_ONLY_STREAM_URL)


class _Factory:
    """Client factory that records the fresh fake clients it builds."""

    def __init__(self) -> None:
        self.built: list[FakeUserDataWsClient] = []

    def __call__(self, configuration: ConfigurationWebSocketStreams) -> FakeUserDataWsClient:
        client = FakeUserDataWsClient()
        self.built.append(client)
        return client


def _rig(
    *,
    ws: FakeUserDataWsClient | None = None,
    port: Any = None,
    queue_max: int | None = None,
) -> tuple[UserDataAdapter, SdkUserDataTransport, FakeUserDataWsClient, _Factory, Any]:
    ws = ws if ws is not None else FakeUserDataWsClient()
    factory = _Factory()
    transport = SdkUserDataTransport(_configuration(), client_factory=factory, ws_client=ws)
    limits = test_only_stream_limits()
    if queue_max is not None:
        limits = dataclasses.replace(limits, event_queue_max=queue_max)
    port = port if port is not None else _StubListenKeys()
    adapter = UserDataAdapter(transport=transport, listen_keys=port, limits=limits, clock=_clock)
    return adapter, transport, ws, factory, port


def _sdk_free(value: object, path: str = "item") -> None:
    """Fail when any attribute reachable from `value` has an SDK type."""
    module = type(value).__module__
    assert not module.startswith("binance_"), f"{path} has SDK type {type(value).__name__}"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            _sdk_free(getattr(value, item.name), f"{path}.{item.name}")
    elif isinstance(value, tuple | list):
        for index, element in enumerate(value):
            _sdk_free(element, f"{path}[{index}]")


# --------------------------------------------------------------------------- #
# Task 1: tracer.
# --------------------------------------------------------------------------- #


async def test_tracer_sdk_order_trade_update_becomes_queued_event_and_fill() -> None:
    adapter, _transport, ws, _factory, port = _rig()

    await adapter.start()

    assert port.starts == 1
    assert adapter.epoch == 1
    # The bare listenKey goes on the wire as the SUBSCRIBE params, on the private connection.
    assert [frame["params"] for frame in ws.subscribe_frames] == [[TEST_ONLY_LISTEN_KEY]]
    private = ws.connection_for("private")
    assert private is not None
    assert len(private.stream_callback_map[TEST_ONLY_LISTEN_KEY]) == 1

    delivered = ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_order_trade_update_message())

    assert delivered == 1
    assert adapter.queue.qsize() == 1
    item = adapter.queue.get_nowait()
    assert isinstance(item, QueuedStreamItem)
    assert item.received_at_utc == TEST_ONLY_NOW
    assert item.connection_epoch == 1
    assert isinstance(item.outcome, OrderUpdateEvent)
    fill = to_fill_event(item.outcome)
    assert isinstance(fill, FillEvent)
    assert (fill.order_id, fill.exchange_trade_id) == ("8000000001", "900000001")
    assert fill.symbol == "BTCUSDT"
    assert fill.side == "BUY"
    assert fill.position_side == "BOTH"
    assert fill.fill_quantity == Decimal("0.004")
    assert fill.fill_price == Decimal("60000.00")
    assert fill.commission == Decimal("0.09600000")
    assert fill.commission_asset == "USDT"
    _sdk_free(item)
    _sdk_free(fill)


async def test_raw_dict_fallback_takes_the_same_path_and_gives_the_same_event() -> None:
    adapter, _transport, ws, _factory, _port = _rig()
    await adapter.start()

    ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_order_trade_update_message())
    ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_raw_dict_message(order_trade_update_frame()))

    from_model = adapter.queue.get_nowait()
    from_dict = adapter.queue.get_nowait()
    assert isinstance(from_dict.outcome, OrderUpdateEvent)
    assert from_dict.outcome == from_model.outcome
    _sdk_free(from_dict)


async def test_unrecognized_message_becomes_an_anomaly_item_and_never_raises() -> None:
    adapter, _transport, ws, _factory, _port = _rig()
    await adapter.start()

    ws.emit_user_event(TEST_ONLY_LISTEN_KEY, object())

    item = adapter.queue.get_nowait()
    assert isinstance(item.outcome, StreamAnomaly)
    assert item.outcome.kind is StreamAnomalyKind.UNRECOGNIZED_ENVELOPE
    assert item.connection_epoch == 1
    _sdk_free(item)


async def test_parser_exception_becomes_a_malformed_payload_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _transport, ws, _factory, _port = _rig()
    await adapter.start()

    def broken_parser(message: object, *, observed_at_utc: datetime) -> Any:
        raise RuntimeError("parser bug")

    monkeypatch.setattr(bud, "parse_stream_message", broken_parser)
    ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_order_trade_update_message())

    item = adapter.queue.get_nowait()
    assert isinstance(item.outcome, StreamAnomaly)
    assert item.outcome.kind is StreamAnomalyKind.MALFORMED_PAYLOAD
    assert "parser bug" not in item.outcome.detail
    assert item.outcome.observed_at_utc == TEST_ONLY_NOW


async def test_connect_raises_connection_error_when_the_sdk_produced_no_connection() -> None:
    ws = FakeUserDataWsClient(produce_connection=False)
    adapter, _transport, _ws, _factory, _port = _rig(ws=ws)

    with pytest.raises(ConnectionError) as excinfo:
        await adapter.start()

    assert "wss" not in str(excinfo.value)
    assert TEST_ONLY_LISTEN_KEY not in str(excinfo.value)
    assert adapter.epoch == 0
    assert ws.subscribe_frames == []


async def test_connect_raises_connection_error_when_no_private_connection_exists() -> None:
    class _NoPrivate(FakeUserDataWsClient):
        URL_PATHS = ("market", "public")

    ws = _NoPrivate()
    adapter, _transport, _ws, _factory, _port = _rig(ws=ws)

    with pytest.raises(ConnectionError):
        await adapter.start()
    assert ws.subscribe_frames == []
    assert adapter.epoch == 0
