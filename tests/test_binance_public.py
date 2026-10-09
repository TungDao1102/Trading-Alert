"""Public market-data adapter split (phase 16, plan 16-03; SC6, D-13, D040).

`BinancePublicMarketData` carries the public data surface of the exchange adapter so the SHADOW
runtime can read market data without constructing the order adapter. These tests pin that the
order adapter delegates to it with identical output, and that the public module has no order,
cancel, account or position surface and no credential source. No network is used: a fake SDK
client stands in for the REST client.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any

import src.adapters.binance_public as public_mod
import src.adapters.binance_usdm as usdm_mod
from src.adapters.binance_public import BinancePublicMarketData
from src.adapters.binance_usdm import BinanceUsdmAdapter

# Source: live GET /fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=2, 2026-10-07 (16-RESEARCH.md,
# "Real-shaped fixture rows"; prices are exchange data).
ROW0 = [
    1791360000000,
    "84094.70",
    "84139.20",
    "83902.50",
    "83909.90",
    "5844.590",
    1791363599999,
    "490868445.00560",
    179437,
    "2473.352",
    "207729461.40190",
    "0",
]
ROW1 = [
    1791363600000,
    "83909.90",
    "83965.50",
    "83603.00",
    "83749.00",
    "7821.908",
    1791367199999,
    "655296503.76730",
    125134,
    "3519.234",
    "294835835.39980",
    "0",
]


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _FakeRest:
    """Records every call so a test can assert which SDK method was reached."""

    def __init__(self, rows: list[list[Any]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def kline_candlestick_data(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("kline_candlestick_data", kwargs))
        return _FakeResponse(self._rows)


class _FakeSdk:
    def __init__(self, rest: _FakeRest) -> None:
        self.rest_api = rest


def _sdk() -> _FakeSdk:
    return _FakeSdk(_FakeRest([ROW0, ROW1]))


def test_public_klines_equal_order_adapter_klines() -> None:
    public = asyncio.run(BinancePublicMarketData(sdk_client=_sdk()).klines("BTCUSDT", "1h"))  # type: ignore[arg-type]
    order = asyncio.run(BinanceUsdmAdapter(sdk_client=_sdk()).klines("BTCUSDT", "1h"))  # type: ignore[arg-type]
    assert len(public) == 2
    assert public == order
    assert [repr(k) for k in public] == [repr(k) for k in order]


def test_kline_is_one_type_re_exported_by_the_order_adapter() -> None:
    assert usdm_mod.Kline is public_mod.Kline
