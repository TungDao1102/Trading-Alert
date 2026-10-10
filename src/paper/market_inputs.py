"""Market inputs of the live paper loop (Phase 16, plan 16-26; D-35, Q-G folded into O-07).

What the per-bar tick needs from outside the candle stream, and where each value comes from:

- exchange constraints (tick, step, minimum quantity, minimum notional): only from the public
  `exchangeInfo`, never hard-coded (AGENTS.md exchange authority);
- the refresh cadence and the time-to-live of a constraint snapshot: only from the ratified
  runtime configuration;
- the account inputs: the initial equity and the risk rate from the ratified configuration;
- open positions and the daily loss: through the required `RiskInputsProvider` port. This module
  holds NO default implementation of the port; plan 16-31 binds it to the SHADOW ledger.

The module never reads the wall clock: every time arrives through the injected clock.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from src.adapters.binance_public import Kline as RestKline
from src.adapters.binance_public import SymbolFilters
from src.paper.vocabulary import INTERVAL_MS, SourceTag, TaggedBar

_UNIX_ORIGIN = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)

SIBLING_INTERVAL = "4h"


class PublicDataLike(Protocol):
    """The credential-free public adapter surface the loop uses (`BinancePublicMarketData`)."""

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[RestKline]: ...

    async def server_time(self) -> datetime: ...

    async def exchange_info(self) -> list[SymbolFilters]: ...


def _to_ms(moment: datetime) -> int:
    """Whole milliseconds since the Unix epoch (exact integer arithmetic)."""
    return (moment.astimezone(UTC) - _UNIX_ORIGIN) // _ONE_MS


def make_sibling_fetcher(
    public: PublicDataLike, loop: asyncio.AbstractEventLoop
) -> Callable[[str, datetime], TaggedBar | None]:
    """The synchronous `fetch_4h_bar(symbol, close)` the bar pipeline needs (plan 16-24).

    The pipeline runs in a worker thread (`asyncio.to_thread`), so the fetch hands the async REST
    call to the event loop and waits for it; the loop thread is never blocked by it. It returns
    the closed 4h bar ending exactly at `close_time_utc`, or None when the exchange has no such
    closed candle (flag-never-fabricate: nothing is invented).
    """
    step = timedelta(milliseconds=INTERVAL_MS[SIBLING_INTERVAL])

    def fetch(symbol: str, close_time_utc: datetime) -> TaggedBar | None:
        open_time = close_time_utc + _ONE_MS - step
        rows = asyncio.run_coroutine_threadsafe(
            public.klines(
                symbol,
                SIBLING_INTERVAL,
                start_ms=_to_ms(open_time),
                end_ms=_to_ms(close_time_utc),
                limit=2,
            ),
            loop,
        ).result()
        for row in rows:
            if row.open_time_utc == open_time and row.close_time_utc == close_time_utc:
                return TaggedBar(
                    symbol=symbol,
                    interval=SIBLING_INTERVAL,
                    open_time_utc=row.open_time_utc,
                    close_time_utc=row.close_time_utc,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    source=SourceTag.REST_BACKFILL,
                )
        return None

    return fetch


__all__ = ["PublicDataLike", "make_sibling_fetcher"]
