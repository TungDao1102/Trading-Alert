"""Phase 15 plan 15-03: confirmed fractal pivots (D-01, D-03, D-04, T-15-05).

Candles are built from explicit lows (pivot lows) or highs (pivot highs); Decimal from
strings and ints only. The micro example is hand-derived in 15-RESEARCH.md Pattern 1.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

import pytest
from src.core.pivots import pivot_at, recent_pivots
from src.core.types import Candle

from tests.geometry_builders import SETUP_START

LOOKBACK = 20
MICRO_LOWS = (105, 104, 103, 100, 103, 104, 105)  # t = 3, L = R = 3


def _bars(lows: Sequence[int], highs: Sequence[int]) -> list[Candle]:
    candles: list[Candle] = []
    for index, (low, high) in enumerate(zip(lows, highs, strict=True)):
        open_time = SETUP_START + timedelta(hours=index)
        mid = Decimal(low + high) / 2
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=mid,
                high=Decimal(high),
                low=Decimal(low),
                close=mid,
                volume=Decimal("1"),
            )
        )
    return candles


def _from_lows(lows: Sequence[int]) -> list[Candle]:
    return _bars(lows, [low + 2 for low in lows])


def _from_highs(highs: Sequence[int]) -> list[Candle]:
    return _bars([high - 2 for high in highs], highs)


def _low(candles: Sequence[Candle], i: int, **overrides: int) -> Decimal | None:
    kwargs = {"lookback": LOOKBACK, "left": 3, "right": 3}
    kwargs.update(overrides)
    return pivot_at(candles, i, high=False, **kwargs)


def test_pivot_confirmed_exactly_at_t_plus_r() -> None:
    candles = _from_lows(MICRO_LOWS)
    assert _low(candles, 5) is None  # t + R - 1: not yet confirmed
    assert _low(candles, 6) == Decimal("100")  # t + R: confirmed


def test_pivot_high_confirmed_exactly_at_t_plus_r() -> None:
    candles = _from_highs([200 - low for low in MICRO_LOWS])  # mirror image, peak at t = 3
    assert pivot_at(candles, 5, lookback=LOOKBACK, left=3, right=3, high=True) is None
    assert pivot_at(candles, 6, lookback=LOOKBACK, left=3, right=3, high=True) == Decimal("100")


def test_evaluated_bar_is_never_the_level() -> None:
    falling = _from_lows([200 - k for k in range(40)])  # every bar a new low
    assert all(_low(falling, i) is None for i in range(len(falling)))
    rising = _from_highs([100 + k for k in range(40)])  # every bar a new high
    assert all(
        pivot_at(rising, i, lookback=LOOKBACK, left=3, right=3, high=True) is None
        for i in range(len(rising))
    )


def test_tie_rule_double_bottom_yields_exactly_one_pivot() -> None:
    # indices 0..8; equal lows at 3 and 5. Left side non-strict, right side strict, so the
    # earlier one fails (the later low is not strictly higher) and the later one qualifies.
    candles = _from_lows((9, 8, 7, 5, 6, 5, 7, 8, 9))
    found = recent_pivots(candles, 8, lookback=LOOKBACK, left=3, right=3, high=False, count=5)
    assert found == ((5, Decimal("5")),)


def test_tie_rule_flat_series_has_no_pivot_and_plateau_end_is_the_pivot() -> None:
    flat = _from_lows([50] * 30)
    assert all(_low(flat, i) is None for i in range(len(flat)))
    # a plateau followed by a strictly higher right side: the last plateau bar qualifies
    plateau = _from_lows((5, 5, 5, 5, 6, 7, 8))
    found = recent_pivots(plateau, 6, lookback=LOOKBACK, left=3, right=3, high=False, count=5)
    assert found == ((3, Decimal("5")),)


def test_lookback_bound_and_left_side_before_window() -> None:
    lows = (*MICRO_LOWS, 106, 107, 108, 109, 110, 111)  # pivot at t = 3, last index 12
    candles = _from_lows(lows)
    last = len(lows) - 1
    # window start = 12 - 10 + 1 = 3 = t: found, although t - left = 0 lies before the window
    assert _low(candles, last, lookback=10) == Decimal("100")
    # window start = 4 > t: the pivot is too old
    assert _low(candles, last, lookback=9) is None


def test_warm_up_needs_left_plus_right_plus_one_bars() -> None:
    six = _from_lows((105, 104, 103, 100, 103, 104))
    assert all(_low(six, i) is None for i in range(6))
    seven = _from_lows(MICRO_LOWS)
    assert _low(seven, 6) == Decimal("100")


def _zigzag(n: int) -> tuple[list[int], list[int]]:
    """Deterministic integer series with many pivots (no randomness)."""
    lows = [1000 + ((k * 37) % 23) * 5 - (k % 7) * 3 for k in range(n)]
    return lows, [low + 4 for low in lows]


def test_pivot_at_prefix_invariance_over_a_300_bar_series() -> None:
    lows, highs = _zigzag(300)
    candles = _bars(lows, highs)
    for i in range(len(candles)):
        for high in (False, True):
            full = pivot_at(candles, i, lookback=LOOKBACK, left=3, right=3, high=high)
            prefix = pivot_at(candles[: i + 1], i, lookback=LOOKBACK, left=3, right=3, high=high)
            assert full == prefix


def test_pivot_at_prefix_invariance_ignores_poisoned_later_candles() -> None:
    lows, highs = _zigzag(300)
    candles = _bars(lows, highs)
    for i in range(0, len(candles), 7):
        poisoned_lows = [*lows[: i + 1], *([1] * (len(lows) - i - 1))]
        poisoned_highs = [*highs[: i + 1], *([100000] * (len(highs) - i - 1))]
        poisoned = _bars(poisoned_lows, poisoned_highs)
        for high in (False, True):
            clean = pivot_at(candles, i, lookback=LOOKBACK, left=3, right=3, high=high)
            dirty = pivot_at(poisoned, i, lookback=LOOKBACK, left=3, right=3, high=high)
            assert clean == dirty


def test_recent_pivots_are_newest_first_and_capped() -> None:
    lows, highs = _zigzag(300)
    candles = _bars(lows, highs)
    i = 250
    found = recent_pivots(candles, i, lookback=LOOKBACK, left=3, right=3, high=False, count=3)
    assert 1 <= len(found) <= 3
    assert [index for index, _level in found] == sorted((index for index, _ in found), reverse=True)
    assert all(index <= i - 3 and index >= i - LOOKBACK + 1 for index, _ in found)
    assert found[0][1] == pivot_at(candles, i, lookback=LOOKBACK, left=3, right=3, high=False)
    one = recent_pivots(candles, i, lookback=LOOKBACK, left=3, right=3, high=False, count=1)
    assert one == found[:1]


def test_recent_pivots_empty_when_none_confirmed() -> None:
    candles = _from_lows((105, 104, 103, 100, 103, 104))
    assert recent_pivots(candles, 5, lookback=LOOKBACK, left=3, right=3, high=False, count=2) == ()


@pytest.mark.parametrize(
    ("kwargs", "index"),
    [
        ({"left": 0, "right": 3, "lookback": 20}, 6),
        ({"left": 3, "right": 0, "lookback": 20}, 6),
        ({"left": 3, "right": 3, "lookback": 3}, 6),
        ({"left": 3, "right": 3, "lookback": 20}, 7),
        ({"left": 3, "right": 3, "lookback": 20}, -1),
    ],
)
def test_invalid_arguments_raise_value_error(kwargs: dict[str, int], index: int) -> None:
    candles = _from_lows(MICRO_LOWS)
    with pytest.raises(ValueError):
        pivot_at(candles, index, high=False, **kwargs)
    with pytest.raises(ValueError):
        recent_pivots(candles, index, high=False, count=1, **kwargs)


def test_recent_pivots_rejects_non_positive_count() -> None:
    candles = _from_lows(MICRO_LOWS)
    with pytest.raises(ValueError):
        recent_pivots(candles, 6, lookback=LOOKBACK, left=3, right=3, high=False, count=0)
