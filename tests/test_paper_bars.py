"""Pure bar buffers with the engine windows (Phase 16, plan 16-10, task 2).

The runtime keeps its own incremental buffers; they must cut exactly the windows the engine cuts
(`STRATEGY_WINDOW_BARS = 1000` setup bars, `CONTEXT_WINDOW_BARS = 300` context bars, context bars
selected with `bisect_right` on the setup close) and order 4h before 1h at a shared close
(research pitfalls P6 and P7). No network, no clock.
"""

from __future__ import annotations

import ast
import itertools
import random
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.backtest.semantics import CONTEXT_WINDOW_BARS, STRATEGY_WINDOW_BARS
from src.core.types import Candle
from src.paper.bars import BarBuffers, group_by_close

SYMBOL = "BTCUSDT"
T0 = datetime(2026, 1, 1, tzinfo=UTC)
ONE_MS = timedelta(milliseconds=1)


def _bar(interval: str, index: int, symbol: str = SYMBOL) -> Candle:
    step = timedelta(hours=1) if interval == "1h" else timedelta(hours=4)
    opened = T0 + step * index
    price = Decimal(100 + index % 50)
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time_utc=opened,
        close_time_utc=opened + step - ONE_MS,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=Decimal(1),
    )


def _history(hours: int = 1500) -> tuple[list[Candle], list[Candle]]:
    setup = [_bar("1h", i) for i in range(hours)]
    context = [_bar("4h", i) for i in range(hours // 4)]
    return setup, context


def _reference_window(bars: list[Candle], close: datetime, size: int) -> list[Candle]:
    """The engine's rule (`_setup_window` / `_context_window`): bisect_right, trailing `size`."""
    closes = [b.close_time_utc for b in bars]
    high = bisect_right(closes, close)
    return bars[max(0, high - size) : high]


def _feed_in_close_order(buffers: BarBuffers, bars: list[Candle]) -> None:
    for _, group in group_by_close(bars):
        for candle in group:
            buffers.add(candle)


# --------------------------------------------------------------------------- #
# Test 1 - windows equal the engine rule
# --------------------------------------------------------------------------- #


def test_windows_use_the_engine_constants() -> None:
    assert STRATEGY_WINDOW_BARS == 1000
    assert CONTEXT_WINDOW_BARS == 300


def test_windows_equal_the_engine_rule_on_a_1500_bar_history() -> None:
    setup, context = _history(1500)
    buffers = BarBuffers()
    checked = 0
    for _, group in group_by_close([*setup, *context]):
        for candle in group:
            buffers.add(candle)
        for candle in group:
            if candle.interval != "1h":
                continue
            close = candle.close_time_utc
            assert buffers.setup_window(SYMBOL, close) == _reference_window(
                setup, close, STRATEGY_WINDOW_BARS
            )
            assert buffers.context_window(SYMBOL, close) == _reference_window(
                context, close, CONTEXT_WINDOW_BARS
            )
            checked += 1
    assert checked == 1500


def test_the_latest_windows_are_full_length_once_history_is_long_enough() -> None:
    setup, context = _history(1500)
    buffers = BarBuffers()
    _feed_in_close_order(buffers, [*setup, *context])
    last = setup[-1].close_time_utc
    assert len(buffers.setup_window(SYMBOL, last)) == STRATEGY_WINDOW_BARS
    assert len(buffers.context_window(SYMBOL, last)) == CONTEXT_WINDOW_BARS


def test_a_short_history_returns_everything_at_or_before_the_close() -> None:
    setup, context = _history(40)
    buffers = BarBuffers()
    _feed_in_close_order(buffers, [*setup, *context])
    close = setup[20].close_time_utc
    assert buffers.setup_window(SYMBOL, close) == setup[:21]
    assert buffers.context_window(SYMBOL, close) == _reference_window(context, close, 300)
    assert buffers.setup_window("ETHUSDT", close) == []


def test_symbols_do_not_mix() -> None:
    buffers = BarBuffers()
    btc = _bar("1h", 0)
    eth = _bar("1h", 0, symbol="ETHUSDT")
    assert buffers.add(btc) is True
    assert buffers.add(eth) is True
    assert buffers.setup_window(SYMBOL, btc.close_time_utc) == [btc]
    assert buffers.setup_window("ETHUSDT", eth.close_time_utc) == [eth]


def test_arrival_order_does_not_change_the_windows() -> None:
    setup, context = _history(120)
    in_order = BarBuffers()
    _feed_in_close_order(in_order, [*setup, *context])
    shuffled = BarBuffers()
    mixed = [*setup, *context]
    random.Random(7).shuffle(mixed)
    for candle in mixed:
        shuffled.add(candle)
    close = setup[-1].close_time_utc
    assert shuffled.setup_window(SYMBOL, close) == in_order.setup_window(SYMBOL, close)
    assert shuffled.context_window(SYMBOL, close) == in_order.context_window(SYMBOL, close)


# --------------------------------------------------------------------------- #
# Test 2 - dedup by open time
# --------------------------------------------------------------------------- #


def test_adding_a_stored_open_time_returns_false_and_changes_nothing() -> None:
    buffers = BarBuffers()
    first = _bar("1h", 5)
    assert buffers.add(first) is True
    before = buffers.setup_window(SYMBOL, first.close_time_utc)
    redelivered = Candle(
        symbol=first.symbol,
        interval=first.interval,
        open_time_utc=first.open_time_utc,
        close_time_utc=first.close_time_utc,
        open=Decimal(999),
        high=Decimal(1000),
        low=Decimal(998),
        close=Decimal(999),
        volume=Decimal(7),
    )
    assert buffers.add(redelivered) is False
    assert buffers.setup_window(SYMBOL, first.close_time_utc) == before == [first]
    assert buffers.size(SYMBOL, "1h") == 1


def test_a_bar_older_than_a_full_buffer_is_refused() -> None:
    setup, _ = _history(1500)
    buffers = BarBuffers()
    for candle in setup:
        buffers.add(candle)
    assert buffers.add(setup[0]) is False
    assert buffers.size(SYMBOL, "1h") <= STRATEGY_WINDOW_BARS + 1


def test_an_unsupported_interval_is_refused() -> None:
    buffers = BarBuffers()
    minute = Candle(
        symbol=SYMBOL,
        interval="1m",
        open_time_utc=T0,
        close_time_utc=T0 + timedelta(minutes=1) - ONE_MS,
        open=Decimal(1),
        high=Decimal(1),
        low=Decimal(1),
        close=Decimal(1),
        volume=Decimal(1),
    )
    with pytest.raises(ValueError, match="interval"):
        buffers.add(minute)


# --------------------------------------------------------------------------- #
# Test 3 - close-time grouping, 4h before 1h
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Item:
    close_time_utc: datetime
    interval: str
    symbol: str = SYMBOL


def test_group_by_close_orders_by_close_and_puts_4h_before_1h_for_any_permutation() -> None:
    four_hour_close = T0 + timedelta(hours=4) - ONE_MS
    items = [
        _Item(four_hour_close, "4h"),
        _Item(four_hour_close, "1h"),
        _Item(four_hour_close, "1h", symbol="ETHUSDT"),
        _Item(four_hour_close - timedelta(hours=1), "1h"),
        _Item(four_hour_close + timedelta(hours=1), "1h"),
    ]
    expected = group_by_close(items)
    assert [close for close, _ in expected] == sorted({i.close_time_utc for i in items})
    shared = dict(expected)[four_hour_close]
    assert [i.interval for i in shared] == ["4h", "1h", "1h"]
    for permutation in itertools.permutations(items):
        assert group_by_close(permutation) == expected


def test_group_by_close_refuses_an_unknown_interval() -> None:
    with pytest.raises(ValueError, match="interval"):
        group_by_close([_Item(T0, "1m")])


def test_group_by_close_of_nothing_is_empty() -> None:
    assert group_by_close([]) == ()


# --------------------------------------------------------------------------- #
# Test 4 - memory bound
# --------------------------------------------------------------------------- #


def test_buffers_never_exceed_the_window_plus_one_bar_per_interval() -> None:
    setup, context = _history(1500)
    buffers = BarBuffers()
    for _, group in group_by_close([*setup, *context]):
        for candle in group:
            buffers.add(candle)
            assert buffers.size(SYMBOL, "1h") <= STRATEGY_WINDOW_BARS + 1
            assert buffers.size(SYMBOL, "4h") <= CONTEXT_WINDOW_BARS + 1
    assert buffers.size(SYMBOL, "1h") == STRATEGY_WINDOW_BARS + 1
    assert buffers.size(SYMBOL, "4h") == CONTEXT_WINDOW_BARS + 1


# --------------------------------------------------------------------------- #
# Independence from the paper vocabulary module
# --------------------------------------------------------------------------- #


def test_bars_module_does_not_import_the_paper_vocabulary() -> None:
    source = (Path(__file__).resolve().parent.parent / "src" / "paper" / "bars.py").read_text(
        encoding="utf-8"
    )
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "src.paper.vocabulary" not in imported
    assert not any(name.startswith("src.paper") for name in imported)
