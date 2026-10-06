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


def window_from_closes(
    closes: Sequence[Decimal],
    *,
    half_range: Decimal = Decimal("1"),
    bearish: bool = False,
) -> tuple[list[Candle], list[Candle]]:
    """(setup_candles, context_candles) for any 1h close path with a trending 4h context.

    The last 4h bar opens six hours before the evaluated 1h bar opens, so it has closed by
    then. The context rises (BULLISH) or falls (`bearish`, BEARISH) by `half_range` per bar
    over 250 bars.
    """
    setup = constant_range_candles(closes, half_range=half_range)
    return setup, trending_context(len(setup), half_range=half_range, bearish=bearish)


def trending_context(
    setup_length: int, *, half_range: Decimal = Decimal("1"), bearish: bool = False
) -> list[Candle]:
    """250 closed 4h bars rising (BULLISH) or falling (`bearish`) by `half_range` per bar.

    The last 4h bar opens six hours before the evaluated 1h bar (index `setup_length - 1`)
    opens, so it has closed by then.
    """
    if bearish:
        context_closes = [Decimal("100") + half_range * (250 - k) for k in range(250)]
    else:
        context_closes = [Decimal("100") + half_range * k for k in range(250)]
    context_start = SETUP_START + timedelta(hours=setup_length - 1 - 6) - timedelta(hours=4) * 249
    return constant_range_candles(
        context_closes, interval="4h", start=context_start, half_range=half_range
    )


def scale_closes(closes: Sequence[Decimal], *, atr: Decimal, pivot_low: Decimal) -> list[Decimal]:
    """Affine copy of an a_long_worked-shaped path for a different price scale.

    Maps close c to `half * c + (pivot_low - 99 * half)` with `half = atr / 2`, so the bar
    range becomes `atr` and the base case pivot low 99.00 lands on `pivot_low`. Every ratio of
    the base derivation (zone, buffers, stop, RR) is preserved. Decimal only.
    """
    half = atr / 2
    offset = pivot_low - Decimal("99") * half
    return [half * close + offset for close in closes]


def family_a_long_audit_window(
    *, atr: Decimal, pivot_low: Decimal
) -> tuple[list[Candle], list[Candle]]:
    """a_long_worked shape rescaled to bar range `atr` with the pivot low at `pivot_low`."""
    closes = scale_closes(family_a_long_closes(), atr=atr, pivot_low=pivot_low)
    return window_from_closes(closes, half_range=atr / 2)


def family_a_long_audit_60000_window() -> tuple[list[Candle], list[Candle]]:
    """CONTEXT audit anchor: pivot 60,000, ATR 400 (bar range 400)."""
    return family_a_long_audit_window(atr=Decimal("400"), pivot_low=Decimal("60000"))


def family_a_long_audit_59000_window() -> tuple[list[Candle], list[Candle]]:
    """CONTEXT audit anchor 1: pivot 59,000, ATR 300 (bar range 300)."""
    return family_a_long_audit_window(atr=Decimal("300"), pivot_low=Decimal("59000"))


def family_a_short_closes() -> list[Decimal]:
    """Mirror of the a_long_worked path: close' = 200 - close (steps keep their size)."""
    return [Decimal("200") - close for close in family_a_long_closes()]


def family_a_short_window() -> tuple[list[Candle], list[Candle]]:
    """(setup_candles, context_candles) for a_short_worked (BEARISH 4h context)."""
    return window_from_closes(family_a_short_closes(), bearish=True)


def family_a_no_opposite_pivot_closes() -> list[Decimal]:
    """A confirmed pivot low and a touching last bar, but no confirmed pivot high in 20 bars.

    A 0.25 ramp to a 99.25 peak at bar 220 (outside the 20-bar lookback of the last bar),
    then a 0.25 fall for 26 bars to the pivot low bar 246 (close 92.75, low 91.75), then
    93.00, 93.25 and 93.00. Falling highs have higher bars on their left, so no pivot high
    qualifies. 250 bars; the evaluated bar 249 is the third right-side bar of the pivot low.
    """
    closes = [Decimal("44.25") + Decimal("0.25") * k for k in range(221)]
    closes.extend(Decimal("99.25") - Decimal("0.25") * j for j in range(1, 27))
    closes.extend(Decimal(v) for v in "93.00 93.25 93.00".split())
    return closes


def family_a_no_opposite_pivot_window() -> tuple[list[Candle], list[Candle]]:
    return window_from_closes(family_a_no_opposite_pivot_closes())


def _p9_closes(final_tail: str) -> list[Decimal]:
    """Shared p9 lead-in: 0.25 ramp to a 106 peak (bar 247), a fall to a confirmed pivot low.

    Bar 247 closes 106 (pivot high 107), bars 248..254 close 105, 104, 103, 102, 101, 100.5,
    100 (bar 254, low 99.00 = the pivot low P, confirmed at bar 257 by 100.5, 101, 101.5), and
    `final_tail` continues from bar 258.
    """
    closes = [Decimal("44.25") + Decimal("0.25") * k for k in range(248)]
    lead = "105 104 103 102 101 100.5 100 100.5 101 101.5"
    closes.extend(Decimal(v) for v in lead.split())
    closes.extend(Decimal(v) for v in final_tail.split())
    return closes


def family_a_p9_inside_tolerance_closes() -> list[Decimal]:
    """Last bar (260) closes 99.2: low 98.20 is a new low but inside 98.00-100.00 (P = 99)."""
    return _p9_closes("100.5 99.7 99.2")


def family_a_p9_beyond_tolerance_closes() -> list[Decimal]:
    """Last bar (262) closes 97: low 96.00 is 3.00 = 1.5 ATR below P = 99, outside 98.00-100.00."""
    return _p9_closes("100.5 99.5 98.5 97.5 97")


def family_a_p9_inside_tolerance_window() -> tuple[list[Candle], list[Candle]]:
    return window_from_closes(family_a_p9_inside_tolerance_closes())


def family_a_p9_beyond_tolerance_window() -> tuple[list[Candle], list[Candle]]:
    return window_from_closes(family_a_p9_beyond_tolerance_closes())


def family_a_rising_closes(count: int = 250) -> list[Decimal]:
    """Strictly rising 0.25 closes: every low exceeds all lows before it, so no pivot low."""
    return [Decimal("44.25") + Decimal("0.25") * k for k in range(count)]


def family_a_tp_loss_side_closes() -> list[Decimal]:
    """Setup closes whose newest confirmed pivot high lies BELOW the pivot low (F6).

    A 0.25 ramp up to a 104 peak (pivot high 105, confirmed by 103, 102, 101), a rise to 108,
    then a small dip whose bottom (close 107, low 106) is the confirmed pivot low. The bars
    around the dip keep making equal or higher highs, so no newer pivot high is confirmed
    when the last bar (close 107.5, low 106.5) touches the pivot zone. Bar count 258.
    """
    closes = [Decimal("44.25") + Decimal("0.25") * k for k in range(240)]
    tail = "103 102 101 102 103 104 105 106 107 108 108 107.5 107 108 108.5 109 108.5 107.5"
    closes.extend(Decimal(v) for v in tail.split())
    return closes


def family_a_tp_loss_side_window() -> tuple[list[Candle], list[Candle]]:
    """(setup_candles, context_candles) for the loss-side TP1 case (F6)."""
    return window_from_closes(family_a_tp_loss_side_closes())


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


# --------------------------------------------------------------------------- #
# Family B (breakout-retest) windows, plan 15-05. Hand derivations: DERIVATIONS.md.
# --------------------------------------------------------------------------- #

_ONE_HOUR = timedelta(hours=1)


def bar_after(
    previous: Candle,
    *,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    open_: Decimal | None = None,
) -> Candle:
    """The 1h bar following `previous`; `open_` defaults to the previous close."""
    open_time = previous.open_time_utc + _ONE_HOUR
    return Candle(
        symbol=previous.symbol,
        interval=previous.interval,
        open_time_utc=open_time,
        close_time_utc=open_time + _ONE_HOUR - timedelta(seconds=1),
        open=previous.close if open_ is None else open_,
        high=high,
        low=low,
        close=close,
        volume=Decimal("1"),
    )


def range_bar_after(previous: Candle, close: Decimal) -> Candle:
    """A constant-range bar (high = close + 1, low = close - 1) following `previous`."""
    return bar_after(previous, high=close + Decimal("1"), low=close - Decimal("1"), close=close)


def family_b_long_setup(
    *,
    first_breakout: int = 246,
    plateau: int = 2,
    tail: Sequence[Decimal] = (),
) -> list[Candle]:
    """Flat range, one breakout run, a plateau away from the band, then the retest bar.

    Bars 0..first_breakout-2 alternate close 99 / 100 and end on 100 (range 2.00, so
    ATR = 2.00 exactly; swing high 101, swing low 98 over any 20 of them). Bar
    first_breakout-1 closes 101 (its high 102 is outside the swing window of the reference
    bar first_breakout-2 and inside the window of first_breakout-1). Bar first_breakout is
    the breakout bar (open 101, low 101, high 103, close 103, true range 2.00). Then
    `plateau` constant-range bars close 104 (low 103, above the retest band), then the retest
    bar closes 103 (low 102.00), then the `tail` closes (each within 1.00 of the previous).
    True range is 2.00 for every bar, so ATR = 2.00 everywhere.
    """
    flat = [
        Decimal("100") if (first_breakout - 2 - k) % 2 == 0 else Decimal("99")
        for k in range(first_breakout - 1)
    ]
    candles = constant_range_candles([*flat, Decimal("101")])
    candles.append(
        bar_after(candles[-1], high=Decimal("103"), low=Decimal("101"), close=Decimal("103"))
    )
    for close in [*([Decimal("104")] * plateau), Decimal("103"), *tail]:
        candles.append(range_bar_after(candles[-1], close))
    return candles


def mirror_candles(candles: Sequence[Candle], *, pivot: Decimal = Decimal("200")) -> list[Candle]:
    """Reflect every price p to pivot - p (highs and lows swap); times are unchanged."""
    return [
        Candle(
            symbol=c.symbol,
            interval=c.interval,
            open_time_utc=c.open_time_utc,
            close_time_utc=c.close_time_utc,
            open=pivot - c.open,
            high=pivot - c.low,
            low=pivot - c.high,
            close=pivot - c.close,
            volume=c.volume,
        )
        for c in candles
    ]


def family_b_window(
    *,
    mirror: bool = False,
    bearish_context: bool | None = None,
    first_breakout: int = 246,
    plateau: int = 2,
    tail: Sequence[Decimal] = (),
) -> tuple[list[Candle], list[Candle]]:
    """(setup, context) for a Family B case; `mirror` reflects the setup to a SHORT shape.

    The 4h context follows the mirror flag (BEARISH when mirrored) unless `bearish_context`
    overrides it, which builds the counter-regime windows.
    """
    setup = family_b_long_setup(first_breakout=first_breakout, plateau=plateau, tail=tail)
    if mirror:
        setup = mirror_candles(setup)
    bearish = mirror if bearish_context is None else bearish_context
    return setup, trending_context(len(setup), bearish=bearish)


def family_b_long_window() -> tuple[list[Candle], list[Candle]]:
    """b_long_worked: breakout bar 246, retest and evaluated bar 249, BULLISH."""
    return family_b_window()


def family_b_short_window() -> tuple[list[Candle], list[Candle]]:
    """b_short_worked: the mirror (p -> 200 - p) of b_long_worked, BEARISH."""
    return family_b_window(mirror=True)


def family_b_confirm3_window() -> tuple[list[Candle], list[Candle]]:
    """b_long_legacy_confirm3: closes 103, 104, 104 on bars 245..247 (three clear the edge)."""
    return family_b_window(first_breakout=245, plateau=3)


def family_b_confirm3_one_close_window() -> tuple[list[Candle], list[Candle]]:
    """Same stretch as confirm3 but only bar 247 clears the edge 102.00.

    Bars 0..243 alternate as in family_b_long_setup (bar 243 closes 100), bar 244 closes 101,
    bar 245 closes 101, bar 246 closes 102 (equal to the edge, not above it), bar 247 is a
    custom bar (open 102, low 102, high 104, close 104, true range 2.00), bar 248 closes 104
    and the evaluated bar 249 closes 103.
    """
    flat = [Decimal("100") if (243 - k) % 2 == 0 else Decimal("99") for k in range(244)]
    candles = constant_range_candles([*flat, Decimal("101"), Decimal("101"), Decimal("102")])
    candles.append(
        bar_after(candles[-1], high=Decimal("104"), low=Decimal("102"), close=Decimal("104"))
    )
    candles.append(range_bar_after(candles[-1], Decimal("104")))
    candles.append(range_bar_after(candles[-1], Decimal("103")))
    return candles, trending_context(len(candles))


def family_b_stale_window() -> tuple[list[Candle], list[Candle]]:
    """A breakout and its first retest 40 bars before the evaluated bar, nothing since.

    The b_long_worked pattern shifted so the breakout bar is 206 and the retest bar 209;
    bars 210..249 close 104 (low 103, high 105).
    """
    return family_b_window(first_breakout=206, tail=[Decimal("104")] * 40)


def family_b_not_first_retest_window() -> tuple[list[Candle], list[Candle]]:
    """Breakout bar 246, a retest at 248 (n - 2) and another band touch at 249 (n - 1)."""
    return family_b_window(plateau=1, tail=[Decimal("103")])


def family_b_late_retest_window() -> tuple[list[Candle], list[Candle]]:
    """Breakout bar 246, five bars at 104, the first retest at 252 (six bars after 246)."""
    return family_b_window(plateau=5)


def family_b_crash_window() -> tuple[list[Candle], list[Candle]]:
    """b_long_worked up to the breakout bar 246, then a gap away and a crash on bar 249.

    Bar 247: open 108, low 108, high 109, close 109. Bar 248: open 109, low 108, high 110,
    close 109. Evaluated bar 249: open 109, high 109, low 98.50, close 100. With
    retest_depth_atr 2.0 the band around the edge 102.00 is 98.00..106.00, so bars 247 and
    248 (lows 108) are outside it and bar 249 (low 98.50) is the first retest.
    """
    candles = family_b_long_setup()[:247]
    candles.append(
        bar_after(
            candles[-1],
            high=Decimal("109"),
            low=Decimal("108"),
            close=Decimal("109"),
            open_=Decimal("108"),
        )
    )
    candles.append(
        bar_after(candles[-1], high=Decimal("110"), low=Decimal("108"), close=Decimal("109"))
    )
    candles.append(
        bar_after(candles[-1], high=Decimal("109"), low=Decimal("98.50"), close=Decimal("100"))
    )
    return candles, trending_context(len(candles))


def with_evaluated_bar(
    setup: Sequence[Candle], *, high: Decimal, low: Decimal, close: Decimal
) -> list[Candle]:
    """`setup` with its last bar replaced (same open and times); used by the leakage proofs."""
    last = setup[-1]
    replaced = Candle(
        symbol=last.symbol,
        interval=last.interval,
        open_time_utc=last.open_time_utc,
        close_time_utc=last.close_time_utc,
        open=last.open,
        high=high,
        low=low,
        close=close,
        volume=last.volume,
    )
    return [*setup[:-1], replaced]
