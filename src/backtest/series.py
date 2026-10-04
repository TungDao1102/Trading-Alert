"""Lazy 1m minute-series contract for the causal simulator (Phase 14, plan 14-01).

The simulator never holds a dict of minute rows (a 24-month multi-symbol case is
about 38 GB, D-31). It reads minutes only through the `MinuteSource` protocol, one
window at a time. `ListMinuteSource` serves fixtures from in-memory candles; the
Polars-backed implementation lives in `src/data` (plan 14-10) so this package stays
Polars-free.

Minute series are validated on load (D-13): strictly increasing, minute-aligned
open times, no duplicate or overlapping minutes. A hole (a missing minute) is
explicit and stays absent from every window; nothing is padded or sorted silently.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from src.core.types import Candle

_MINUTE = timedelta(seconds=60)
_KINDS = ("trade", "mark")
_MINUTE_INTERVAL = "1m"


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
    """Fail closed unless `candles` is a valid 1m series for `symbol` (D-13).

    Per candle: symbol and interval match, and the close time lies strictly inside
    `(open, open + 60 s)`. Per pair: the next open time is strictly later than the
    previous one (no duplicate, no decreasing order) and not earlier than previous open
    + 60 s (no overlap). Every open time is aligned to a whole minute. A gap between
    consecutive opens is a legal, explicit hole.

    Raises:
        MinuteSeriesError: any violation, naming the offending open time.
    """
    if kind not in _KINDS:
        raise MinuteSeriesError(f"kind must be one of {_KINDS}, got {kind!r}")
    previous_open: datetime | None = None
    for candle in candles:
        opened = candle.open_time_utc
        where = f"{kind} minute {opened.isoformat()} for {symbol}"
        if candle.symbol != symbol:
            raise MinuteSeriesError(f"{where}: symbol mismatch, got {candle.symbol!r}")
        if candle.interval != _MINUTE_INTERVAL:
            raise MinuteSeriesError(f"{where}: interval must be '1m', got {candle.interval!r}")
        if not (opened < candle.close_time_utc < opened + _MINUTE):
            raise MinuteSeriesError(
                f"{where}: close time {candle.close_time_utc.isoformat()} must lie strictly "
                "inside (open, open + 60 s)"
            )
        if previous_open is not None:
            if opened == previous_open:
                raise MinuteSeriesError(f"{where}: duplicate open time")
            if opened < previous_open:
                raise MinuteSeriesError(
                    f"{where}: open time decreases (previous {previous_open.isoformat()})"
                )
            if opened < previous_open + _MINUTE:
                raise MinuteSeriesError(
                    f"{where}: overlaps the previous minute {previous_open.isoformat()}"
                )
        if opened.second != 0 or opened.microsecond != 0:
            raise MinuteSeriesError(f"{where}: open time is not aligned to a whole minute")
        previous_open = opened


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


def _parse_money(value: object, field_name: str) -> Decimal:
    """Coerce a money field to Decimal; floats and bools are refused, never coerced."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool | float):
        raise TypeError(f"{field_name} must be Decimal/str/int, got {type(value).__name__}")
    if isinstance(value, int | str):
        return Decimal(value)
    raise TypeError(f"{field_name} must be Decimal/str/int, got {type(value).__name__}")


def _parse_time(value: object, field_name: str) -> datetime:
    """Parse an ISO string or datetime into a UTC-aware datetime (naive refused)."""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError(f"{field_name} must be an ISO str or datetime, got {type(value).__name__}")
    if parsed.tzinfo is None:
        raise MinuteSeriesError(f"{field_name} must be UTC-aware, got naive datetime")
    if parsed.utcoffset() != timedelta(0):
        raise MinuteSeriesError(f"{field_name} must be UTC, got offset {parsed.utcoffset()}")
    return parsed


def parse_minute_row(row: Mapping[str, Any], *, kind: str) -> Candle:
    """Build a 1m `Candle` from a JSON-like row (D-13).

    `kind` is `"trade"` or `"mark"`. Trade rows carry `volume`; mark rows do not (the
    Phase 13 mark columns have `price_tick_count` instead), so a parsed mark candle
    gets `Decimal("0")` volume and a trade row without volume is refused.

    Raises:
        TypeError: a money field is a float/bool or a time field has the wrong type.
        MinuteSeriesError: naive or non-UTC time, missing column, or an unknown kind.
    """
    if kind not in _KINDS:
        raise MinuteSeriesError(f"kind must be one of {_KINDS}, got {kind!r}")
    required = ["symbol", "interval", "open_time_utc", "close_time_utc"]
    required.extend(["open", "high", "low", "close"])
    if kind == "trade":
        required.append("volume")
    missing = [name for name in required if name not in row]
    if missing:
        raise MinuteSeriesError(f"{kind} minute row is missing columns {missing}")
    volume = _parse_money(row["volume"], "volume") if kind == "trade" else Decimal("0")
    return Candle(
        symbol=str(row["symbol"]),
        interval=str(row["interval"]),
        open_time_utc=_parse_time(row["open_time_utc"], "open_time_utc"),
        close_time_utc=_parse_time(row["close_time_utc"], "close_time_utc"),
        open=_parse_money(row["open"], "open"),
        high=_parse_money(row["high"], "high"),
        low=_parse_money(row["low"], "low"),
        close=_parse_money(row["close"], "close"),
        volume=volume,
    )
