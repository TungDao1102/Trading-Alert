"""Live mark price read through the real adapter over a fake SDK (plan 19-05, D-06).

`GET /fapi/v1/premiumIndex` via the SDK `mark_price` method. Every Optional field of the
response is validated: a missing, malformed, non-finite or non-positive value raises instead of
becoming a plausible default (flag never fabricate). No network, no real sleep.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from src.adapters.binance_public import BinancePublicMarketData, MarkPriceReading
from src.adapters.binance_ratelimit_gate import RateLimitPauseActive, RestRateLimitGate
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.adapters.binance_usdm import MarkPriceReading as ExportedMarkPriceReading
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

    def mark_price(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self.payload)


def _single(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {"symbol": "BTCUSDT", "mark_price": "101.50", "time": _TIME_MS}
    fields.update(overrides)
    return SimpleNamespace(actual_instance=SimpleNamespace(**fields))


def _adapter(
    payload: Any, *, gate: RestRateLimitGate | None = None
) -> tuple[BinanceUsdmAdapter, _FakeRest]:
    rest = _FakeRest(payload)
    sdk = SimpleNamespace(rest_api=rest)
    return BinanceUsdmAdapter(sdk_client=sdk, rest_gate=gate), rest  # type: ignore[arg-type]


def test_exported_from_adapter_module() -> None:
    assert ExportedMarkPriceReading is MarkPriceReading


@pytest.mark.asyncio
async def test_get_mark_price_returns_validated_reading() -> None:
    adapter, rest = _adapter(_single())
    reading = await adapter.get_mark_price(symbol="BTCUSDT")
    assert reading == MarkPriceReading(
        symbol="BTCUSDT",
        mark_price=Decimal("101.50"),
        exchange_time_utc=datetime(2026, 9, 20, 10, 26, 40, 123000, tzinfo=UTC),
    )
    assert isinstance(reading.mark_price, Decimal)
    assert reading.exchange_time_utc.tzinfo is not None
    assert rest.calls == [{"symbol": "BTCUSDT"}]


@pytest.mark.asyncio
async def test_public_reader_returns_the_same_reading() -> None:
    rest = _FakeRest(_single())
    reader = BinancePublicMarketData(sdk_client=SimpleNamespace(rest_api=rest))  # type: ignore[arg-type]
    reading = await reader.mark_price("BTCUSDT")
    assert reading.mark_price == Decimal("101.50")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        SimpleNamespace(actual_instance=None),
        SimpleNamespace(actual_instance=[SimpleNamespace(symbol="BTCUSDT")]),
        _single(mark_price=None),
        _single(mark_price=""),
        _single(mark_price="abc"),
        _single(mark_price="NaN"),
        _single(mark_price="Infinity"),
        _single(mark_price="0"),
        _single(mark_price="-1.5"),
        _single(time=None),
        _single(symbol=None),
        _single(symbol="ETHUSDT"),
    ],
    ids=[
        "empty-response",
        "no-actual-instance",
        "list-instead-of-one-symbol",
        "mark-price-missing",
        "mark-price-empty",
        "mark-price-not-decimal",
        "mark-price-nan",
        "mark-price-infinite",
        "mark-price-zero",
        "mark-price-negative",
        "time-missing",
        "symbol-missing",
        "other-symbol",
    ],
)
async def test_malformed_response_raises(payload: Any) -> None:
    adapter, _ = _adapter(payload)
    with pytest.raises(ValueError, match="BTCUSDT|premiumIndex|mark"):
        await adapter.get_mark_price(symbol="BTCUSDT")


@pytest.mark.asyncio
async def test_error_message_carries_no_payload() -> None:
    adapter, _ = _adapter(_single(mark_price="SECRET-VALUE-xyz"))
    with pytest.raises(ValueError) as excinfo:
        await adapter.get_mark_price(symbol="BTCUSDT")
    assert "SECRET-VALUE-xyz" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_gate_pause_refuses_before_the_sdk_is_reached() -> None:
    policy = test_only_signed_call_policy()
    gate = RestRateLimitGate(
        policy=policy.rate_limit, clock=lambda: datetime(2026, 10, 16, tzinfo=UTC)
    )
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
    adapter, rest = _adapter(_single(), gate=gate)
    with pytest.raises(RateLimitPauseActive):
        await adapter.get_mark_price(symbol="BTCUSDT")
    assert rest.calls == []
