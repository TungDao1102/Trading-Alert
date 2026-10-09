"""Live 1m trade and mark minutes for the SHADOW fill driver (Phase 16, plan 16-19, D-14).

`LiveMinuteSource` is an append-only in-memory `MinuteSource` (the protocol of
`src/backtest/series.py`) that the Phase 14 lifecycle reads exactly like a recorded series.
Every appended batch is validated with `validate_minute_series`; a minute that has not closed yet
is refused; a missing minute stays a hole (nothing is padded) and the lifecycle annotates it in
`coverage_note`; a symbol that has no series raises like `ListMinuteSource` does, so a missing
symbol can never read as "no price moves"; and a stored minute is never overwritten (an identical
re-delivery is a no-op, a different one is refused).

`LiveMinutePoller` fills the source from the public REST adapter's `klines(symbol, "1m")` and
`mark_klines(symbol, "1m")`. REST polling is the planner's implementation choice (research D9, G4):
the installed SDK has no mark-price kline stream, and REST `klines` and `markPriceKlines` are
documented with weights of 1 to 2 per call (docs/SOURCES.md, Phase 13 rows). The poll cadence
and the minute close lag are timing numbers owned by the user (O-07): both are REQUIRED keyword
inputs with no default. The poller reads no clock itself: `poll_once` takes `now_utc` and `run`
takes a clock callable, so a replay of the same inputs stores the same minutes.

Trade and mark are fetched together and only minutes that closed at or before
`now_utc - close_lag` are stored, so the returned `settled_through_utc` is a watermark up to which
BOTH series are complete: the fill driver must only be advanced to that instant, or a mark minute
that arrives late would be skipped by the next window and read as a hole.

The module imports nothing from the Binance SDK: the adapter is passed in (anything shaped like
`BinancePublicMarketData`), and its error types stay the caller's to name through
`transient_errors`.
"""

from __future__ import annotations

import asyncio
from bisect import bisect_left
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from src.adapters.binance_public import Kline, MarkKline
from src.backtest.series import MinuteSeriesError, _window, validate_minute_series
from src.core.types import Candle

KIND_TRADE = "trade"
KIND_MARK = "mark"
_KINDS = (KIND_TRADE, KIND_MARK)
_MINUTE = timedelta(minutes=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_INTERVAL = "1m"
_PAGE_LIMIT = 1500  # Binance maximum for klines and markPriceKlines
_MAX_PAGES = 20
_ZERO = Decimal("0")


class LiveMinutePollError(RuntimeError):
    """A poll could not finish (fail closed): the feed is further behind than the page budget."""


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _open_time(candle: Candle) -> datetime:
    return candle.open_time_utc


class LiveMinuteSource:
    """Append-only, validated, in-memory 1m trade and mark series per symbol."""

    def __init__(self) -> None:
        self._series: dict[str, dict[str, list[Candle]]] = {}

    def append(
        self,
        symbol: str,
        kind: str,
        candles: Sequence[Candle],
        *,
        closed_through_utc: datetime,
    ) -> int:
        """Append closed minutes of `symbol`; returns how many NEW minutes were stored.

        `closed_through_utc` is the latest instant the caller knows to be closed; a candle whose
        close time is after it is a forming minute and the whole batch is refused. The batch is
        validated with `validate_minute_series` on its own and joined to the stored tail, so a
        duplicate, decreasing, overlapping or misaligned minute is refused. Minutes at or before
        the stored tail are accepted only as an exact replay of what is stored. Nothing is stored
        when anything is refused.
        """
        if kind not in _KINDS:
            raise MinuteSeriesError(f"kind must be one of {_KINDS}, got {kind!r}")
        _require_utc(closed_through_utc, "closed_through_utc")
        batch = list(candles)
        if not batch:
            return 0
        validate_minute_series(batch, symbol=symbol, kind=kind)
        for candle in batch:
            if candle.close_time_utc > closed_through_utc:
                raise MinuteSeriesError(
                    f"{kind} minute {candle.open_time_utc.isoformat()} for {symbol} is still "
                    f"forming (closes {candle.close_time_utc.isoformat()}, closed through "
                    f"{closed_through_utc.isoformat()})"
                )
        stored = self._series.get(symbol, {}).get(kind, [])
        fresh: list[Candle] = []
        for candle in batch:
            index = bisect_left(stored, candle.open_time_utc, key=_open_time)
            if index < len(stored) and stored[index].open_time_utc == candle.open_time_utc:
                if stored[index] != candle:
                    raise MinuteSeriesError(
                        f"{kind} minute {candle.open_time_utc.isoformat()} for {symbol} differs "
                        "from the stored minute (a stored minute is never overwritten)"
                    )
                continue
            if stored and candle.open_time_utc < stored[-1].open_time_utc:
                raise MinuteSeriesError(
                    f"{kind} minute {candle.open_time_utc.isoformat()} for {symbol} is before "
                    f"the stored tail {stored[-1].open_time_utc.isoformat()} and not stored"
                )
            fresh.append(candle)
        if fresh:
            validate_minute_series([*stored[-1:], *fresh], symbol=symbol, kind=kind)
            self._series.setdefault(symbol, {}).setdefault(kind, []).extend(fresh)
        return len(fresh)

    def last_open_utc(self, symbol: str, kind: str) -> datetime | None:
        """Open time of the newest stored minute of this series, or None when empty."""
        series = self._series.get(symbol, {}).get(kind)
        return series[-1].open_time_utc if series else None

    def trade_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]:
        return _window(self._require(symbol, KIND_TRADE), start_exclusive, end_inclusive)

    def mark_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]:
        return _window(self._require(symbol, KIND_MARK), start_exclusive, end_inclusive)

    def _require(self, symbol: str, kind: str) -> list[Candle]:
        series = self._series.get(symbol, {}).get(kind)
        if not series:
            raise MinuteSeriesError(f"no {kind}-price minute series for {symbol}")
        return series


class PublicMinuteFeed(Protocol):
    """The two public-adapter calls the poller needs (`BinancePublicMarketData` satisfies it)."""

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]: ...

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]: ...


@dataclass(frozen=True)
class PollResult:
    """What one poll stored. Both series are complete through `settled_through_utc`."""

    symbol: str
    settled_through_utc: datetime
    trade_minutes_added: int
    mark_minutes_added: int


def _to_ms(value: datetime) -> int:
    """Whole milliseconds since the Unix epoch, in integer arithmetic (no float)."""
    return (value - _EPOCH) // timedelta(milliseconds=1)


def _floor_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _trade_candle(row: Kline) -> Candle:
    return Candle(
        symbol=row.symbol,
        interval=row.interval,
        open_time_utc=row.open_time_utc,
        close_time_utc=row.close_time_utc,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
    )


def _mark_candle(row: MarkKline) -> Candle:
    return Candle(
        symbol=row.symbol,
        interval=row.interval,
        open_time_utc=row.open_time_utc,
        close_time_utc=row.close_time_utc,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=_ZERO,
    )


class LiveMinutePoller:
    """Poll the public adapter for closed 1m trade and mark minutes into a `LiveMinuteSource`."""

    def __init__(
        self,
        *,
        feed: PublicMinuteFeed,
        source: LiveMinuteSource,
        poll_interval_seconds: int,
        close_lag_seconds: int,
        transient_errors: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError),
        page_limit: int = _PAGE_LIMIT,
        max_pages: int = _MAX_PAGES,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError(f"poll_interval_seconds must be positive, got {poll_interval_seconds}")
        if close_lag_seconds <= 0:
            raise ValueError(f"close_lag_seconds must be positive, got {close_lag_seconds}")
        if page_limit <= 0 or max_pages <= 0:
            raise ValueError("page_limit and max_pages must be positive")
        self._feed = feed
        self._source = source
        self._poll_interval_seconds = poll_interval_seconds
        self._close_lag = timedelta(seconds=close_lag_seconds)
        self._transient_errors = transient_errors
        self._page_limit = page_limit
        self._max_pages = max_pages

    @property
    def poll_interval_seconds(self) -> int:
        return self._poll_interval_seconds

    @property
    def close_lag_seconds(self) -> int:
        return self._close_lag // timedelta(seconds=1)

    async def poll_once(self, symbol: str, *, now_utc: datetime, since_utc: datetime) -> PollResult:
        """Fetch and store the minutes of `symbol` closed at or before `now_utc - close_lag`.

        A series with no stored minute starts at `since_utc` floored to the minute; otherwise
        right after its newest stored minute. Both kinds are fetched before either is stored, so
        a failed fetch leaves the source as it was. Each fetch is retried at most once on a
        transient error; any other error, and a second transient error, propagates.
        """
        _require_utc(now_utc, "now_utc")
        _require_utc(since_utc, "since_utc")
        horizon = now_utc - self._close_lag
        trade = await self._fetch(symbol, KIND_TRADE, since_utc, horizon)
        mark = await self._fetch(symbol, KIND_MARK, since_utc, horizon)
        trade_added = self._source.append(symbol, KIND_TRADE, trade, closed_through_utc=horizon)
        mark_added = self._source.append(symbol, KIND_MARK, mark, closed_through_utc=horizon)
        return PollResult(
            symbol=symbol,
            settled_through_utc=horizon,
            trade_minutes_added=trade_added,
            mark_minutes_added=mark_added,
        )

    async def run(
        self,
        symbol: str,
        *,
        since_utc: datetime,
        clock: Callable[[], datetime],
        stop: asyncio.Event,
        on_settled: Callable[[PollResult], Awaitable[None]],
    ) -> None:
        """Poll every `poll_interval_seconds` until `stop` is set, reporting each result.

        `clock` supplies `now_utc` (the runtime passes its injected clock); a poll error ends
        the loop by propagating, so the caller can fail closed.
        """
        while not stop.is_set():
            result = await self.poll_once(symbol, now_utc=clock(), since_utc=since_utc)
            await on_settled(result)
            if stop.is_set():
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue

    async def _fetch(
        self, symbol: str, kind: str, since_utc: datetime, horizon: datetime
    ) -> list[Candle]:
        last = self._source.last_open_utc(symbol, kind)
        cursor = _floor_minute(since_utc) if last is None else last + _MINUTE
        collected: list[Candle] = []
        for _page in range(self._max_pages):
            rows = await self._page(symbol, kind, cursor, horizon)
            collected.extend(
                row
                for row in (
                    _trade_candle(r) if isinstance(r, Kline) else _mark_candle(r) for r in rows
                )
                if row.close_time_utc <= horizon and row.open_time_utc >= cursor
            )
            if len(rows) < self._page_limit:
                return collected
            cursor = rows[-1].open_time_utc + _MINUTE
        raise LiveMinutePollError(
            f"{kind} minutes of {symbol} are more than {self._max_pages} pages behind "
            f"{horizon.isoformat()}"
        )

    async def _page(
        self, symbol: str, kind: str, cursor: datetime, horizon: datetime
    ) -> Sequence[Kline | MarkKline]:
        start_ms, end_ms = _to_ms(cursor), _to_ms(horizon)

        async def call() -> Sequence[Kline | MarkKline]:
            if kind == KIND_TRADE:
                return await self._feed.klines(
                    symbol, _INTERVAL, start_ms=start_ms, end_ms=end_ms, limit=self._page_limit
                )
            return await self._feed.mark_klines(
                symbol, _INTERVAL, start_ms=start_ms, end_ms=end_ms, limit=self._page_limit
            )

        try:
            return await call()
        except self._transient_errors:
            return await call()  # exactly one retry; a second failure propagates


__all__ = [
    "KIND_MARK",
    "KIND_TRADE",
    "LiveMinutePollError",
    "LiveMinutePoller",
    "LiveMinuteSource",
    "PollResult",
    "PublicMinuteFeed",
]
