"""Confirmed fractal pivots on closed candles (Phase 15, plan 15-03).

Per docs/research/families/trend-pullback.md section 5 rows 1-3 and CONTEXT D-01/D-04: a pivot
low (high) at bar `t` is the lowest low (highest high) over `[t - left, t + right]`, and it is
known only once bar `t + right` has closed. The evaluated bar `i` can therefore only ever be a
right-side confirmer of an older pivot, never the pivot itself.

Tie rule (RESEARCH Assumption A1), pivot low at `t`:
  - `low[t] <= low[j]` for `j` in `[t - left, t - 1]`   (non-strict on the left)
  - `low[t] <  low[j]` for `j` in `[t + 1, t + right]`  (strict on the right)
The pivot high mirrors this with `>=` and `>`. Two equal lows in one window therefore yield
exactly one pivot, the left one.

Pure and prefix-invariant (D-04): the value at index `i` reads `candles[0..i]` only. Decimal
only, no wall clock, no randomness. Callers decide what a missing pivot means; this module
never falls back to a trailing extreme (D-03).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from .types import Candle


def _level(candle: Candle, high: bool) -> Decimal:
    return candle.high if high else candle.low


def _is_pivot(candles: Sequence[Candle], t: int, *, left: int, right: int, high: bool) -> bool:
    """True iff bar `t` is a pivot under the tie rule (needs `t - left >= 0`, `t + right` known)."""
    level = _level(candles[t], high)
    for j in range(t - left, t):
        other = _level(candles[j], high)
        if (level < other) if high else (level > other):
            return False
    for j in range(t + 1, t + right + 1):
        other = _level(candles[j], high)
        if (level <= other) if high else (level >= other):
            return False
    return True


def pivot_at(
    candles: Sequence[Candle],
    i: int,
    *,
    lookback: int,
    left: int,
    right: int,
    high: bool,
) -> Decimal | None:
    """Level of the most recent pivot confirmed at or before bar `i`, or None.

    `None` covers both "no pivot inside the lookback" and "fewer than left + right + 1 bars"
    (D-03). The result depends only on `candles[0..i]` (D-04).
    """
    first = max(left, i - lookback + 1)
    for t in range(i - right, first - 1, -1):
        if _is_pivot(candles, t, left=left, right=right, high=high):
            return _level(candles[t], high)
    return None


__all__ = ["pivot_at"]
