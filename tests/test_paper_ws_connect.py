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

from tests.paper_ws_fakes import FakeSdkWsClient, make_kline_model

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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
