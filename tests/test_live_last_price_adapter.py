"""Live last price read through the real adapter over a fake SDK (quick task 261020-l4p).

ROADMAP Phase 19 criterion 2 names the mark AND the last price; 19-REVIEW WR-06 built only the
mark. `GET /fapi/v1/ticker/price` ("Symbol Price Ticker", weight 1 with a symbol) via the SDK
`symbol_price_ticker` method: its single-symbol answer is `{symbol, price, time}` (the SDK model
`SymbolPriceTickerResponse1`), the no-symbol answer a list. Every Optional field is validated: a
missing, malformed, non-finite or non-positive value raises instead of becoming a plausible
default (flag never fabricate). Mirrors `tests/test_live_mark_price_adapter.py`. No network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from src.adapters.binance_public import BinancePublicMarketData, LastPriceReading
from src.adapters.binance_ratelimit_gate import (
    RateLimitBanActive,
    RateLimitPauseActive,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.adapters.binance_usdm import LastPriceReading as ExportedLastPriceReading
from src.domain.exchange_errors import ExchangeErrorCategory

from tests.support.limits import test_only_signed_call_policy

_TIME_MS = 1_789_900_000_123


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _FakeRest:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []
        self.mark_calls: list[dict[str, Any]] = []

    def symbol_price_ticker(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self.payload)

    def mark_price(self, **kwargs: Any) -> _FakeResponse:  # must never be used for the last price
        self.mark_calls.append(kwargs)
        raise AssertionError("the last price is not the mark price")


def _single(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {"symbol": "BTCUSDT", "price": "101.40", "time": _TIME_MS}
    fields.update(overrides)
    return SimpleNamespace(actual_instance=SimpleNamespace(**fields))


def _adapter(
    payload: Any, *, gate: RestRateLimitGate | None = None
) -> tuple[BinanceUsdmAdapter, _FakeRest]:
    rest = _FakeRest(payload)
    sdk = SimpleNamespace(rest_api=rest)
    return BinanceUsdmAdapter(sdk_client=sdk, rest_gate=gate), rest  # type: ignore[arg-type]


def test_exported_from_adapter_module() -> None:
    assert ExportedLastPriceReading is LastPriceReading


def test_reading_is_frozen() -> None:
    reading = LastPriceReading(
        symbol="BTCUSDT",
        last_price=Decimal("1"),
        exchange_time_utc=datetime(2026, 9, 20, tzinfo=UTC),
    )
    with pytest.raises(AttributeError):
        reading.last_price = Decimal("2")  # type: ignore[misc]


@pytest.mark.asyncio
async def test_get_last_price_returns_validated_reading() -> None:
    adapter, rest = _adapter(_single())
    reading = await adapter.get_last_price(symbol="BTCUSDT")
    assert reading == LastPriceReading(
        symbol="BTCUSDT",
        last_price=Decimal("101.40"),
        exchange_time_utc=datetime(2026, 9, 20, 10, 26, 40, 123000, tzinfo=UTC),
    )
    assert isinstance(reading.last_price, Decimal)
    assert reading.exchange_time_utc.tzinfo is not None
    # One call, for one symbol (weight 1), never the all-symbols form; never the mark endpoint.
    assert rest.calls == [{"symbol": "BTCUSDT"}]
    assert rest.mark_calls == []


@pytest.mark.asyncio
async def test_public_reader_returns_the_same_reading() -> None:
    rest = _FakeRest(_single())
    reader = BinancePublicMarketData(sdk_client=SimpleNamespace(rest_api=rest))  # type: ignore[arg-type]
    reading = await reader.last_price("BTCUSDT")
    assert reading.last_price == Decimal("101.40")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        SimpleNamespace(actual_instance=None),
        SimpleNamespace(actual_instance=[SimpleNamespace(symbol="BTCUSDT", price="1", time=1)]),
        _single(price=None),
        _single(price=""),
        _single(price="   "),
        _single(price="abc"),
        _single(price="NaN"),
        _single(price="Infinity"),
        _single(price="0"),
        _single(price="-1.5"),
        _single(price=101.4),
        _single(time=None),
        _single(time=True),
        _single(time="1789900000123"),
        _single(symbol=None),
        _single(symbol="ETHUSDT"),
    ],
    ids=[
        "empty-response",
        "no-actual-instance",
        "list-instead-of-one-symbol",
        "price-missing",
        "price-empty",
        "price-blank",
        "price-not-decimal",
        "price-nan",
        "price-infinite",
        "price-zero",
        "price-negative",
        "price-float-not-string",
        "time-missing",
        "time-bool",
        "time-string",
        "symbol-missing",
        "other-symbol",
    ],
)
async def test_malformed_response_raises(payload: Any) -> None:
    adapter, _ = _adapter(payload)
    with pytest.raises(ValueError, match="BTCUSDT"):
        await adapter.get_last_price(symbol="BTCUSDT")


@pytest.mark.asyncio
async def test_error_message_carries_no_payload() -> None:
    adapter, _ = _adapter(_single(price="SECRET-VALUE-xyz"))
    with pytest.raises(ValueError) as excinfo:
        await adapter.get_last_price(symbol="BTCUSDT")
    assert "SECRET-VALUE-xyz" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_sdk_exception_propagates_unchanged_and_is_not_retried() -> None:
    class _Boom(Exception):
        pass

    class _FailingRest(_FakeRest):
        def symbol_price_ticker(self, **kwargs: Any) -> _FakeResponse:
            self.calls.append(kwargs)
            raise _Boom("transport")

    rest = _FailingRest(None)
    adapter = BinanceUsdmAdapter(sdk_client=SimpleNamespace(rest_api=rest))  # type: ignore[arg-type]
    with pytest.raises(_Boom):
        await adapter.get_last_price(symbol="BTCUSDT")
    assert len(rest.calls) == 1


def _gate() -> RestRateLimitGate:
    policy = test_only_signed_call_policy()
    return RestRateLimitGate(
        policy=policy.rate_limit, clock=lambda: datetime(2026, 10, 16, tzinfo=UTC)
    )


@pytest.mark.asyncio
async def test_gate_pause_refuses_before_the_sdk_is_reached() -> None:
    gate = _gate()
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
    adapter, rest = _adapter(_single(), gate=gate)
    with pytest.raises(RateLimitPauseActive):
        await adapter.get_last_price(symbol="BTCUSDT")
    assert rest.calls == []


@pytest.mark.asyncio
async def test_gate_ban_refuses_before_the_sdk_is_reached() -> None:
    gate = _gate()
    gate.record(ExchangeErrorCategory.IP_BANNED, None)
    adapter, rest = _adapter(_single(), gate=gate)
    with pytest.raises(RateLimitBanActive):
        await adapter.get_last_price(symbol="BTCUSDT")
    assert rest.calls == []
