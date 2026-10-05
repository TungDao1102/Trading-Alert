"""Lazy Parquet-backed 1m `MinuteSource` for the causal simulator (Phase 14, plan 14-10).

`src/backtest` reads 1m trade and mark prices only through the `MinuteSource` protocol
(`src/backtest/series.py`) and stays Polars-free (D-26). A 24-month multi-symbol case as
a dict of rows is about 38 GB (D-31), so this module serves the same protocol straight from
the published per-day partitions:

    <raw_root>/interval=1m/symbol=<S>/date=<D>/part.parquet                      trade prices
    <raw_root>/dataset=mark_klines/interval=1m/symbol=<S>/date=<D>/part.parquet  mark prices

Rules (D-13, D-31):

- Lazy by UTC day. A window `(start_exclusive, end_inclusive]` opens only the day files
  its closes can fall in (a minute closes in the UTC day it opens in), parsed days sit in a
  small per-(series, symbol) LRU of `cache_days` entries, so memory is bounded by
  `symbols x 2 x cache_days` days of candles.
- Validated on first touch. Each loaded day goes through `validate_minute_series`
  (strictly increasing, minute-aligned, no duplicate or overlapping minute, symbol and
  interval match) and every row must belong to the partition's own UTC day. Nothing is
  sorted or padded: a missing minute stays a hole, a day with no file is an empty hole.
- Identity (Phase 13 D-18). `files_read()` lists, in first-opened order, every partition
  the source actually opened. Feed it to `dataset_identity` together with the other files a
  run used, so the dataset id covers the minute partitions too. Re-reads after an LRU
  eviction do not grow the list.
- Path safety (T-14-19). Symbols must match `^[A-Z0-9]+USDT$` before any path is built and
  every path is confined under `raw_root`.

Polars is allowed here (src/data); nothing in this module reads a clock.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
from src.backtest.series import MinuteSeriesError, parse_minute_row, validate_minute_series
from src.core.types import Candle
from src.data.store import MARK_DATASET_DIR, partition_file, read_partitions

SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")

_MICROSECOND = timedelta(microseconds=1)
_KINDS = ("trade", "mark")
_MINUTE_INTERVAL = "1m"
_TRADE_COLUMNS: tuple[str, ...] = (
    "symbol",
    "interval",
    "open_time_utc",
    "close_time_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
_MARK_COLUMNS: tuple[str, ...] = (
    "symbol",
    "interval",
    "open_time_utc",
    "close_time_utc",
    "open",
    "high",
    "low",
    "close",
)


def _close_time(candle: Candle) -> datetime:
    return candle.close_time_utc


def _require_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MinuteSeriesError(f"{name} must be a UTC-aware datetime")
    if value.utcoffset() != timedelta(0):
        raise MinuteSeriesError(f"{name} must be UTC, got offset {value.utcoffset()}")
    return value


class ParquetMinuteSource:
    """`MinuteSource` over the published 1m trade and mark day partitions.

    Args:
        raw_root: the immutable store root (trade partitions directly under it, mark
            partitions under `dataset=mark_klines`).
        symbols: the symbols this source may serve; each must match `^[A-Z0-9]+USDT$`.
        start_utc, end_utc: the readable range `[start_utc, end_utc)`; days outside it are
            never opened and read as empty.
        cache_days: parsed days kept per (series, symbol); at least 1.
    """

    def __init__(
        self,
        raw_root: Path,
        *,
        symbols: Sequence[str],
        start_utc: datetime,
        end_utc: datetime,
        cache_days: int = 4,
    ) -> None:
        if isinstance(cache_days, bool) or not isinstance(cache_days, int) or cache_days < 1:
            raise ValueError(f"cache_days must be an integer >= 1, got {cache_days!r}")
        for symbol in symbols:
            if not isinstance(symbol, str) or not SYMBOL_RE.fullmatch(symbol):
                raise MinuteSeriesError(f"symbol {symbol!r} does not match ^[A-Z0-9]+USDT$")
        start = _require_utc(start_utc, "start_utc")
        end = _require_utc(end_utc, "end_utc")
        if end <= start:
            raise MinuteSeriesError("end_utc must be after start_utc")
        self._raw_root = Path(raw_root)
        self._symbols = frozenset(symbols)
        self._first_day: date = start.astimezone(UTC).date()
        self._last_day: date = (end - _MICROSECOND).astimezone(UTC).date()
        self._cache_days = cache_days
        self._cache: dict[tuple[str, str], OrderedDict[date, tuple[Candle, ...]]] = {}
        self._files: dict[Path, None] = {}
        self._loads = 0

    # ------------------------------------------------------------------ #
    # MinuteSource protocol.
    # ------------------------------------------------------------------ #

    def trade_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]:
        return self._window("trade", symbol, start_exclusive, end_inclusive)

    def mark_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]:
        return self._window("mark", symbol, start_exclusive, end_inclusive)

    # ------------------------------------------------------------------ #
    # Identity and diagnostics.
    # ------------------------------------------------------------------ #

    def files_read(self) -> tuple[Path, ...]:
        """Every partition file opened so far, in first-opened order (D-18 identity input)."""
        return tuple(self._files)

    @property
    def loads(self) -> int:
        """How many day files were read from disk (a cache hit does not count)."""
        return self._loads

    # ------------------------------------------------------------------ #
    # Internals.
    # ------------------------------------------------------------------ #

    def _window(
        self, kind: str, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> tuple[Candle, ...]:
        if not isinstance(symbol, str) or not SYMBOL_RE.fullmatch(symbol):
            raise MinuteSeriesError(f"symbol {symbol!r} does not match ^[A-Z0-9]+USDT$")
        if symbol not in self._symbols:
            raise MinuteSeriesError(f"no {kind}-price minute series for {symbol}")
        start = _require_utc(start_exclusive, "start_exclusive")
        end = _require_utc(end_inclusive, "end_inclusive")
        if end <= start:
            return ()
        # A minute closes in the UTC day it opens in, so the closes in (start, end] lie in
        # the days from the first instant after `start` to `end`, clipped to the range.
        first = max((start + _MICROSECOND).astimezone(UTC).date(), self._first_day)
        last = min(end.astimezone(UTC).date(), self._last_day)
        out: list[Candle] = []
        day = first
        while day <= last:
            candles = self._day(kind, symbol, day)
            lo = bisect_right(candles, start, key=_close_time)
            hi = bisect_right(candles, end, key=_close_time)
            out.extend(candles[lo:hi])
            day += timedelta(days=1)
        return tuple(out)

    def _day(self, kind: str, symbol: str, day: date) -> tuple[Candle, ...]:
        lru = self._cache.setdefault((kind, symbol), OrderedDict())
        cached = lru.get(day)
        if cached is not None:
            lru.move_to_end(day)
            return cached
        candles = self._load_day(kind, symbol, day)
        lru[day] = candles
        while len(lru) > self._cache_days:
            lru.popitem(last=False)
        return candles

    def _path(self, kind: str, symbol: str, day: date) -> Path:
        root = self._raw_root / MARK_DATASET_DIR if kind == "mark" else self._raw_root
        path = partition_file(root, _MINUTE_INTERVAL, symbol, day)
        try:
            path.resolve().relative_to(self._raw_root.resolve())
        except ValueError as exc:
            raise MinuteSeriesError(f"{path} is not under raw root {self._raw_root}") from exc
        return path

    def _load_day(self, kind: str, symbol: str, day: date) -> tuple[Candle, ...]:
        path = self._path(kind, symbol, day)
        if not path.is_file():
            return ()  # an unpublished day is a hole: absent, never padded
        self._files.setdefault(path, None)
        self._loads += 1
        columns = _MARK_COLUMNS if kind == "mark" else _TRADE_COLUMNS
        try:
            frame = read_partitions([path], columns, pin_price_scale=True)
        except pl.exceptions.PolarsError as exc:
            raise MinuteSeriesError(f"cannot read {kind} partition {path}: {exc}") from exc
        candles = tuple(parse_minute_row(row, kind=kind) for row in frame.iter_rows(named=True))
        validate_minute_series(candles, symbol=symbol, kind=kind)
        for candle in candles:
            if candle.open_time_utc.astimezone(UTC).date() != day:
                raise MinuteSeriesError(
                    f"{kind} minute {candle.open_time_utc.isoformat()} for {symbol} does not "
                    f"belong to its partition day {day.isoformat()} ({path})"
                )
        return candles


__all__ = ["SYMBOL_RE", "ParquetMinuteSource"]
