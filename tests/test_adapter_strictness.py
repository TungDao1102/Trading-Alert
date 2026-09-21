"""Strictness tests for the Binance USDM adapter (WR-03).

D-09 flag-never-fabricate: a missing exchangeInfo filter field or a
malformed open-interest-statistics row must raise loudly — never become
a plausible zero / empty string / silently dropped row.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    ExchangeInformationResponse,
    ExchangeInformationResponseSymbolsInner,
    ExchangeInformationResponseSymbolsInnerFiltersInner,
)
from src.adapters.binance_usdm import BinanceUsdmAdapter


def _price_filter(tick_size: str | None) -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="PRICE_FILTER",
        tick_size=tick_size,
    )


def _lot_filter() -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="LOT_SIZE",
        step_size="0.001",
        min_qty="0.001",
        max_qty="1000",
    )


def _notional_filter() -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="MIN_NOTIONAL",
        notional="5",
    )


def _symbol(
    filters: list[Any],
    *,
    symbol: str | None = "BTCUSDT",
) -> Any:
    return ExchangeInformationResponseSymbolsInner(
        symbol=symbol,
        contract_type="PERPETUAL",
        status="TRADING",
        base_asset="BTC",
        quote_asset="USDT",
        margin_asset="USDT",
        filters=filters,
    )


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _FakeRest:
    def __init__(self, info: Any = None, oi_rows: Any = None) -> None:
        self._info = info
        self._oi_rows = oi_rows or []

    def exchange_information(self) -> _FakeResponse:
        return _FakeResponse(self._info)

    def open_interest_statistics(
        self,
        *,
        symbol: str,
        period: str,
        limit: int,
    ) -> _FakeResponse:
        return _FakeResponse(self._oi_rows)


class _FakeSdk:
    def __init__(self, rest: _FakeRest) -> None:
        self.rest_api = rest


def _adapter_with_info(symbols: list[Any]) -> BinanceUsdmAdapter:
    info = ExchangeInformationResponse(symbols=symbols)
    return BinanceUsdmAdapter(sdk_client=_FakeSdk(_FakeRest(info=info)))  # type: ignore[arg-type]


def test_exchange_info_raises_on_missing_tick_size() -> None:
    """A PRICE_FILTER without tick_size must raise, not persist zero."""
    adapter = _adapter_with_info(
        [_symbol([_price_filter(None), _lot_filter(), _notional_filter()])]
    )
    with pytest.raises(ValueError, match="missing numeric field"):
        asyncio.run(adapter.exchange_info())


def test_exchange_info_raises_on_missing_symbol_identity() -> None:
    """A symbol record without a symbol must join the drift failure."""
    adapter = _adapter_with_info(
        [
            _symbol(
                [_price_filter("0.01"), _lot_filter(), _notional_filter()],
                symbol=None,
            )
        ]
    )
    with pytest.raises(ValueError, match="drift"):
        asyncio.run(adapter.exchange_info())


def test_exchange_info_accepts_complete_record() -> None:
    """A complete record still projects to SymbolFilters (no false raise)."""
    adapter = _adapter_with_info(
        [_symbol([_price_filter("0.01"), _lot_filter(), _notional_filter()])]
    )
    out = asyncio.run(adapter.exchange_info())
    assert len(out) == 1
    assert out[0].symbol == "BTCUSDT"
    assert str(out[0].price_tick_size) == "0.01"


class _OiRow:
    def __init__(
        self,
        symbol: str | None,
        timestamp: int | None,
        total: str | None,
    ) -> None:
        self.symbol = symbol
        self.timestamp = timestamp
        self.sum_open_interest = total


def test_oi_statistics_raises_on_malformed_row() -> None:
    """A harvest row missing timestamp/measurement raises, never drops."""
    rest = _FakeRest(oi_rows=[_OiRow("BTCUSDT", None, "123.4")])
    adapter = BinanceUsdmAdapter(sdk_client=_FakeSdk(rest))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="missing fields"):
        asyncio.run(
            adapter.open_interest_statistics(symbol="BTCUSDT", period="5m")
        )


def test_oi_statistics_accepts_complete_rows() -> None:
    """Complete harvest rows still project with the research source tag."""
    rest = _FakeRest(oi_rows=[_OiRow("BTCUSDT", 1_700_000_000_000, "123.4")])
    adapter = BinanceUsdmAdapter(sdk_client=_FakeSdk(rest))  # type: ignore[arg-type]
    out = asyncio.run(adapter.open_interest_statistics(symbol="BTCUSDT", period="5m"))
    assert len(out) == 1
    assert out[0].source == "research"
