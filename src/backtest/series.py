"""Lazy 1m minute-series contract for the causal simulator (Phase 14, plan 14-01).

The simulator never holds a dict of minute rows (a 24-month multi-symbol case is
about 38 GB, D-31). It reads minutes only through the `MinuteSource` protocol, one
window at a time. `ListMinuteSource` serves fixtures from in-memory candles; the
Polars-backed implementation lives in `src/data` (plan 14-10) so this package stays
Polars-free.

A hole (a missing minute) is explicit and stays absent from every window; nothing
is padded or sorted silently (D-13).

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from src.core.types import Candle

_KINDS = ("trade", "mark")


class MinuteSeriesError(ValueError):
    """A minute series or row violates the D-13 load-time contract."""


class MinuteSource(Protocol):
    """Windowed read access to continuous 1m trade-price and mark-price series.

    Both methods return the minutes of `symbol` whose `close_time_utc` lies in the
    half-open window `(start_exclusive, end_inclusive]`, ascending. Holes are simply
    absent from the result.
    """

    def trade_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]: ...

    def mark_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]: ...


def _close_time(candle: Candle) -> datetime:
    return candle.close_time_utc


def _window(
    series: Sequence[Candle], start_exclusive: datetime, end_inclusive: datetime
) -> Sequence[Candle]:
    """Select candles with close time in `(start_exclusive, end_inclusive]` (ascending input)."""
    lo = bisect_right(series, start_exclusive, key=_close_time)
    hi = bisect_right(series, end_inclusive, key=_close_time)
    return series[lo:hi]


def validate_minute_series(candles: Sequence[Candle], *, symbol: str, kind: str) -> None:
    """Fail closed unless `candles` has strictly increasing open times for `symbol`.

    Raises:
        MinuteSeriesError: a symbol mismatch, or an open time that is not strictly
            later than the previous one.
    """
    if kind not in _KINDS:
        raise MinuteSeriesError(f"kind must be one of {_KINDS}, got {kind!r}")
    previous_open: datetime | None = None
    for candle in candles:
        if candle.symbol != symbol:
            raise MinuteSeriesError(f"{kind} minute for {symbol}: symbol mismatch")
        if previous_open is not None and candle.open_time_utc <= previous_open:
            raise MinuteSeriesError(
                f"{kind} minute {candle.open_time_utc.isoformat()} for {symbol}: "
                "open times must be strictly increasing"
            )
        previous_open = candle.open_time_utc


class ListMinuteSource:
    """In-memory `MinuteSource` for fixtures and tests.

    Every series is validated at construction. Series are stored as given: never
    sorted, never padded. Asking for a symbol that has no series is a data error and
    raises, so a missing symbol can never read as "no price moves".
    """

    def __init__(
        self,
        trade: Mapping[str, Sequence[Candle]],
        mark: Mapping[str, Sequence[Candle]],
    ) -> None:
        self._trade: dict[str, tuple[Candle, ...]] = {}
        self._mark: dict[str, tuple[Candle, ...]] = {}
        for symbol in sorted(trade):
            validate_minute_series(trade[symbol], symbol=symbol, kind="trade")
            self._trade[symbol] = tuple(trade[symbol])
        for symbol in sorted(mark):
            validate_minute_series(mark[symbol], symbol=symbol, kind="mark")
            self._mark[symbol] = tuple(mark[symbol])

    def trade_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]:
        if symbol not in self._trade:
            raise MinuteSeriesError(f"no trade-price minute series for {symbol}")
        return _window(self._trade[symbol], start_exclusive, end_inclusive)

    def mark_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]:
        if symbol not in self._mark:
            raise MinuteSeriesError(f"no mark-price minute series for {symbol}")
        return _window(self._mark[symbol], start_exclusive, end_inclusive)


def parse_minute_row(row: Mapping[str, Any], *, kind: str) -> Candle:
    """Build a 1m `Candle` from a JSON-like row.

    `kind` is `"trade"` or `"mark"`. Mark rows carry no volume (the Phase 13 mark
    columns have `price_tick_count` instead), so a parsed mark candle gets
    `Decimal("0")` volume.
    """
    if kind not in _KINDS:
        raise MinuteSeriesError(f"kind must be one of {_KINDS}, got {kind!r}")
    volume = Decimal(row["volume"]) if kind == "trade" else Decimal("0")
    return Candle(
        symbol=str(row["symbol"]),
        interval=str(row["interval"]),
        open_time_utc=datetime.fromisoformat(str(row["open_time_utc"])),
        close_time_utc=datetime.fromisoformat(str(row["close_time_utc"])),
        open=Decimal(row["open"]),
        high=Decimal(row["high"]),
        low=Decimal(row["low"]),
        close=Decimal(row["close"]),
        volume=volume,
    )
