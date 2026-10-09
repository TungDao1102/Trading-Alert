"""Binance USD-M public market data (no orders, no account, no credentials).

Public market data only; constructs no order adapter and holds no credentials (SC6, D-13,
D040). The SHADOW runtime imports this module instead of `src.adapters.binance_usdm`, so a
process that must never place an order never loads the order adapter (phase 16, plan 16-03).

This module is, with `src/adapters/binance_usdm.py`, one of the project modules allowed to
import the `binance-sdk-derivatives-trading-usds-futures` package. SDK response models never
leave it: callers receive the frozen dataclasses below.

Dataclass conventions (unchanged from the order adapter this surface was split from):
  - Prices and quantities are `Decimal` (no float for exchange-sensitive values).
  - Timestamps are `datetime` with `tzinfo=UTC` (D-06).
  - Every dataclass is `frozen=True`.

When no `sdk_client` is passed, the SDK REST client is built from an explicit configuration
with no API key and no API secret. Nothing here reads the process environment. The public
endpoints are unsigned, so a signed request cannot originate from this class.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from binance_common.configuration import ConfigurationRestAPI
from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures

# --------------------------------------------------------------------------- #
# Frozen domain dataclasses — the public contract of this adapter.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Kline:
    """One kline row, normalized to project types.

    `close_time_utc <= now_utc` is the invariant callers MUST enforce before
    accepting a kline (RESEARCH §Pitfall 1 — never include the forming candle).
    """

    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int


# --------------------------------------------------------------------------- #
# Helper conversions.
# --------------------------------------------------------------------------- #


def _ms_to_utc(ms: int) -> datetime:
    """Convert a millisecond Unix epoch to a tz-aware UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _row_to_kline(symbol: str, interval: str, row: Sequence[Any]) -> Kline:
    """Map one raw kline list (12-field tuple) to a `Kline`.

    Per Binance docs the order is:
        0  open_time                int ms
        1  open                     str Decimal
        2  high                     str Decimal
        3  low                      str Decimal
        4  close                    str Decimal
        5  volume                   str Decimal
        6  close_time               int ms
        7  quote_asset_volume       str Decimal
        8  number_of_trades         int
        9  taker_buy_base_volume    str Decimal
        10 taker_buy_quote_volume   str Decimal
        11 ignore                   str
    """
    if len(row) < 9:
        raise ValueError(f"kline row too short ({len(row)} cols): {row!r}")
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_ms_to_utc(int(row[0])),
        close_time_utc=_ms_to_utc(int(row[6])),
        open=Decimal(str(row[1])),
        high=Decimal(str(row[2])),
        low=Decimal(str(row[3])),
        close=Decimal(str(row[4])),
        volume=Decimal(str(row[5])),
        quote_volume=Decimal(str(row[7])),
        trade_count=int(row[8]),
    )


# --------------------------------------------------------------------------- #
# Adapter — public market data only.
# --------------------------------------------------------------------------- #


def _credential_free_client() -> DerivativesTradingUsdsFutures:
    """SDK client whose REST configuration carries no API key and no API secret."""
    return DerivativesTradingUsdsFutures(
        config_rest_api=ConfigurationRestAPI(api_key=None, api_secret=None)
    )


class BinancePublicMarketData:
    """Public Binance USD-M market data behind project-owned types.

    Tests inject a fake `sdk_client` (any object exposing `rest_api.kline_candlestick_data`
    etc.) so unit tests never touch the network. The order adapter passes its own client in,
    so one client serves both surfaces there; the SHADOW runtime passes nothing and gets a
    credential-free client.
    """

    def __init__(self, sdk_client: DerivativesTradingUsdsFutures | None = None) -> None:
        self._sdk: DerivativesTradingUsdsFutures = (
            sdk_client if sdk_client is not None else _credential_free_client()
        )

    # ----- klines ---------------------------------------------------------- #

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        """Fetch one page of klines. Always returns the raw list shape
        (a list of 12-field lists) projected to `Kline` instances.

        `start_ms` / `end_ms` are inclusive open-time bounds per Binance
        docs (verified at implementation time against installed SDK).

        The underlying SDK call is synchronous (returns `ApiResponse`
        directly); we run it in a worker thread so the async paginator
        can interleave multiple pages across symbols without blocking.
        """
        response = await asyncio.to_thread(
            self._sdk.rest_api.kline_candlestick_data,
            symbol=symbol,
            interval=interval,  # type: ignore[arg-type]
            start_time=start_ms,
            end_time=end_ms,
            limit=limit,
        )
        # `data()` is a list[list[Any]] — see exchange_info_sample pattern.
        raw = response.data()
        return [_row_to_kline(symbol, interval, row) for row in raw]
