"""Constant-range candle builders for hand-derivable geometry windows (Phase 15).

Every bar built here has `high - low = 2 * half_range` and `open` equal to the previous
close, and the builders refuse closes that differ by more than `half_range`. The true range
of every bar is then exactly `2 * half_range`, so ATR(14) equals the bar range exactly and a
case can be derived by hand (tests/fixtures/phase15/DERIVATIONS.md). Decimal from strings
only.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.core.types import Candle

_DURATIONS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
SETUP_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def constant_range_candles(
    closes: Sequence[Decimal],
    *,
    interval: str = "1h",
    start: datetime = SETUP_START,
    symbol: str = "BTCUSDT",
    half_range: Decimal = Decimal("1"),
) -> list[Candle]:
    """Closed candles with high = close + half_range and low = close - half_range."""
    duration = _DURATIONS[interval]
    candles: list[Candle] = []
    previous = closes[0]
    for index, close in enumerate(closes):
        if abs(close - previous) > half_range:
            raise ValueError(f"close step at bar {index} exceeds half_range {half_range}")
        open_time = start + duration * index
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                open_time_utc=open_time,
                close_time_utc=open_time + duration - timedelta(seconds=1),
                open=previous,
                high=close + half_range,
                low=close - half_range,
                close=close,
                volume=Decimal("1"),
            )
        )
        previous = close
    return candles


def family_a_long_closes() -> list[Decimal]:
    """Setup closes of the a_long_worked window (250 bars; evaluated bar 249)."""
    closes = [Decimal("44.25") + Decimal("0.25") * k for k in range(236)]
    closes.extend(
        Decimal(v) for v in "102 101 100 101 102 103 104 105 104 103 102 101 100 99".split()
    )
    return closes


def rising_context(count: int = 250) -> list[Decimal]:
    """4h closes rising 1.00 per bar (BULLISH regime)."""
    return [Decimal("100") + Decimal(k) for k in range(count)]


def family_a_long_window() -> tuple[list[Candle], list[Candle]]:
    """(setup_candles, context_candles) for the a_long_worked case.

    The last 4h bar opens 244 hours after the setup start, so it closes before the evaluated
    1h bar does.
    """
    setup = constant_range_candles(family_a_long_closes())
    context_closes = rising_context()
    context_start = (
        SETUP_START + timedelta(hours=244) - timedelta(hours=4) * (len(context_closes) - 1)
    )
    context = constant_range_candles(context_closes, interval="4h", start=context_start)
    return setup, context
