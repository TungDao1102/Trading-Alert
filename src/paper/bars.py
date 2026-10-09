"""Pure runtime bar buffers with the engine windows (Phase 16, plan 16-10, D-02).

The paper runtime keeps closed 1h and 4h candles in memory and cuts the same windows the Phase 14
backtest engine cuts, so the decision logic sees the same inputs in both places (research
pitfalls P6 and P7):

- the setup window is the trailing `STRATEGY_WINDOW_BARS` 1h bars ending at a close;
- the context window is the trailing `CONTEXT_WINDOW_BARS` 4h bars whose close is at or before
  that close (`bisect_right`, so a 4h bar closing at the same instant is included);
- at a shared close the 4h bar is delivered before the 1h bar (`group_by_close`).

The two window constants are imported from `src.backtest.semantics` (a documented constant
import, not a copy) so a change there moves the runtime with it. Beyond that the module imports
only stdlib and the project core candle type; it does not import the paper vocabulary module.
Decimal prices ride on `Candle`; there is no float. Buffers hold at most the window plus one bar
per (symbol, interval), so memory stays bounded however long the process runs.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from src.backtest.semantics import CONTEXT_WINDOW_BARS, STRATEGY_WINDOW_BARS
from src.core.types import Candle

SETUP_INTERVAL = "1h"
CONTEXT_INTERVAL = "4h"

# At a shared close the longer interval goes first, so a 1h evaluation sees the 4h bar that
# closed at the same instant in its context (the engine's bisect_right context rule, P6).
_INTERVAL_ORDER: dict[str, int] = {CONTEXT_INTERVAL: 0, SETUP_INTERVAL: 1}


class _Closed(Protocol):
    """Anything that carries a close time and an interval (a Candle, a source-tagged bar)."""

    @property
    def close_time_utc(self) -> datetime: ...

    @property
    def interval(self) -> str: ...


def _interval_rank(interval: str) -> int:
    try:
        return _INTERVAL_ORDER[interval]
    except KeyError:
        raise ValueError(
            f"unsupported interval {interval!r}; expected one of {sorted(_INTERVAL_ORDER)}"
        ) from None


def group_by_close[T: _Closed](items: Iterable[T]) -> tuple[tuple[datetime, tuple[T, ...]], ...]:
    """Group items by close time ascending, 4h before 1h inside a group (P6).

    The order is a function of the items alone, not of their arrival order: inside a group the
    sort key is (interval rank, symbol, open time), reading `symbol` and `open_time_utc` when the
    item has them. An unknown interval raises `ValueError` (fail closed).
    """

    def key(item: T) -> tuple[datetime, int, str, datetime]:
        symbol = getattr(item, "symbol", "")
        opened: datetime = getattr(item, "open_time_utc", item.close_time_utc)
        return (item.close_time_utc, _interval_rank(item.interval), str(symbol), opened)

    groups: list[tuple[datetime, tuple[T, ...]]] = []
    for item in sorted(items, key=key):
        if groups and groups[-1][0] == item.close_time_utc:
            groups[-1] = (groups[-1][0], (*groups[-1][1], item))
        else:
            groups.append((item.close_time_utc, (item,)))
    return tuple(groups)


class _Series:
    """One (symbol, interval) buffer kept sorted by close time and bounded to `capacity`."""

    __slots__ = ("bars", "capacity", "closes", "opens")

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.bars: list[Candle] = []
        self.closes: list[datetime] = []
        self.opens: set[datetime] = set()

    def add(self, candle: Candle) -> bool:
        if candle.open_time_utc in self.opens:
            return False
        if len(self.bars) >= self.capacity and candle.close_time_utc < self.closes[0]:
            return False  # older than everything a full buffer still holds
        position = bisect_right(self.closes, candle.close_time_utc)
        self.bars.insert(position, candle)
        self.closes.insert(position, candle.close_time_utc)
        self.opens.add(candle.open_time_utc)
        while len(self.bars) > self.capacity:
            dropped = self.bars.pop(0)
            self.closes.pop(0)
            self.opens.discard(dropped.open_time_utc)
        return True

    def window(self, close: datetime, size: int) -> list[Candle]:
        high = bisect_right(self.closes, close)
        return self.bars[max(0, high - size) : high]


class BarBuffers:
    """Closed-candle buffers per (symbol, interval) cutting the engine windows (D-02, P7).

    Only the setup interval (1h) and the context interval (4h) are accepted. `add` is the single
    write path: it dedups by open time and returns False for a bar it already holds or for a bar
    older than everything a full buffer still retains. Window queries are answered for closes at
    or after the oldest retained bar, which is every close the runtime asks about (the latest).
    """

    def __init__(
        self,
        *,
        strategy_window_bars: int = STRATEGY_WINDOW_BARS,
        context_window_bars: int = CONTEXT_WINDOW_BARS,
    ) -> None:
        if strategy_window_bars < 1 or context_window_bars < 1:
            raise ValueError("window sizes must be positive")
        self._windows = {
            SETUP_INTERVAL: strategy_window_bars,
            CONTEXT_INTERVAL: context_window_bars,
        }
        self._series: dict[tuple[str, str], _Series] = {}

    def _capacity(self, interval: str) -> int:
        try:
            return self._windows[interval] + 1
        except KeyError:
            raise ValueError(
                f"unsupported interval {interval!r}; expected '{SETUP_INTERVAL}' or "
                f"'{CONTEXT_INTERVAL}'"
            ) from None

    def add(self, candle: Candle) -> bool:
        """Store a closed candle. Returns False when its open time is already held."""
        key = (candle.symbol, candle.interval)
        series = self._series.get(key)
        if series is None:
            series = _Series(self._capacity(candle.interval))
            self._series[key] = series
        return series.add(candle)

    def setup_window(self, symbol: str, close: datetime) -> list[Candle]:
        """The trailing setup (1h) bars ending at `close` (engine `_setup_window`)."""
        series = self._series.get((symbol, SETUP_INTERVAL))
        if series is None:
            return []
        return series.window(close, self._windows[SETUP_INTERVAL])

    def context_window(self, symbol: str, close: datetime) -> list[Candle]:
        """The trailing context (4h) bars closed at or before `close` (engine `_context_window`)."""
        series = self._series.get((symbol, CONTEXT_INTERVAL))
        if series is None:
            return []
        return series.window(close, self._windows[CONTEXT_INTERVAL])

    def size(self, symbol: str, interval: str) -> int:
        """How many bars are held for (symbol, interval)."""
        series = self._series.get((symbol, interval))
        return 0 if series is None else len(series.bars)


__all__ = [
    "CONTEXT_INTERVAL",
    "SETUP_INTERVAL",
    "BarBuffers",
    "group_by_close",
]
