"""Pure feature engine — EMA, ATR, swing, zone (Phase 4, plan 04-01).

Per D-01/D-02/D-10: stdlib + Decimal only. No Polars/pandas/NumPy/Binance
SDK/SQLAlchemy/Pydantic. Every division runs inside a pinned
`localcontext(prec=28)`; every Decimal is built from a string. The
canonical-hash discipline (D-04) means the same input sequence must
produce the same output bytes across processes and Python versions.

Indicator conventions (RESEARCH.md §Code Examples, Pitfall 1):
  - EMA: alpha = 2 / (period + 1), SMA-seeded, first emission at
    0-based index `period - 1` (TA-Lib convention).
  - ATR: Wilder alpha = 1 / period, SMA-of-TR seeded, first emission at
    the n-th candle (0-based index `period - 1`).
  - Swing high/low: highest high / lowest low over `swing_lookback`
    trailing bars, confirmed at the close of the bar at index
    `i` (the rightmost bar in the window). No future-bar leakage.
  - Zone: cluster of swing pivots within `zone_tolerance_atr * ATR`
    half-width; the tracer slice uses a single swing-low zone for
    LONG setups (Family A Stage A baseline per trend-pullback.md §3).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, localcontext

from src.domain.registry import ParameterSet

from .types import (
    REASON_GAP_IN_SOURCE,
    REASON_WARMUP_INSUFFICIENT,
    Candle,
    FeatureFrame,
    FeatureOutput,
    _invalid,
    _ok,
)

# --------------------------------------------------------------------------- #
# Decimal arithmetic helpers — pinned local context (D-10).
# --------------------------------------------------------------------------- #

_PREC = 28


def _q(x: Decimal | int | str) -> Decimal:
    """Build a Decimal from a string/int (never from a float)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, str):
        return Decimal(x)
    raise TypeError(f"_q: unsupported type {type(x).__name__}")


def _div(a: Decimal, b: Decimal) -> Decimal:
    """Divide two Decimals under a pinned local context (D-10)."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a / b


def _mul(a: Decimal, b: Decimal) -> Decimal:
    """Multiply two Decimals under a pinned local context."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a * b


def _add(a: Decimal, b: Decimal) -> Decimal:
    """Add two Decimals under a pinned local context."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a + b


def _sub(a: Decimal, b: Decimal) -> Decimal:
    """Subtract two Decimals under a pinned local context."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a - b


# --------------------------------------------------------------------------- #
# EMA — TA-Lib convention (alpha = 2 / (n + 1), SMA-seeded).
# --------------------------------------------------------------------------- #


def ema_update(prior: Decimal, price: Decimal, alpha: Decimal) -> Decimal:
    """One EMA step: alpha * price + (1 - alpha) * prior.

    Pinned local context; never inherits ambient getcontext().prec.
    """
    with localcontext() as ctx:
        ctx.prec = _PREC
        one = _q("1")
        return _add(_mul(alpha, price), _mul(_sub(one, alpha), prior))


def _ema_series(closes: list[Decimal], period: int) -> list[FeatureOutput]:
    """Compute the EMA series for `closes` with the given `period`.

    First emission at 0-based index `period - 1` (SMA seed of the first
    `period` closes). Before that, the output is invalid with
    `WARMUP_INSUFFICIENT`.
    """
    if period <= 0:
        raise ValueError(f"EMA period must be > 0, got {period}")
    out: list[FeatureOutput] = []
    if len(closes) < period:
        # All bars before the first emission are warm-up invalid.
        return [_invalid(REASON_WARMUP_INSUFFICIENT) for _ in closes]

    # SMA seed = mean of first `period` closes.
    seed = closes[0]
    for i in range(1, period):
        seed = _add(seed, closes[i])
    seed = _div(seed, _q(period))

    alpha = _div(_q("2"), _q(period + 1))

    # First `period - 1` bars: WARMUP_INSUFFICIENT.
    for _ in range(period - 1):
        out.append(_invalid(REASON_WARMUP_INSUFFICIENT))
    # Bar at index `period - 1`: emit the SMA seed.
    out.append(_ok(seed))

    # Subsequent bars: EMA recurrence.
    prev = seed
    for i in range(period, len(closes)):
        prev = ema_update(prev, closes[i], alpha)
        out.append(_ok(prev))
    return out


# --------------------------------------------------------------------------- #
# ATR — Wilder convention (alpha = 1 / n, SMA-of-TR seeded).
# --------------------------------------------------------------------------- #


def true_range(high: Decimal, low: Decimal, prev_close: Decimal | None) -> Decimal:
    """True range: max(H - L, |H - C_prev|, |L - C_prev|).

    For the first bar (no prev_close), TR = H - L.
    """
    if prev_close is None:
        return _sub(high, low)
    hl = _sub(high, low)
    hc = abs(_sub(high, prev_close))
    lc = abs(_sub(low, prev_close))
    # max of three Decimals — use a simple comparison chain.
    if hl >= hc and hl >= lc:
        return hl
    if hc >= lc:
        return hc
    return lc


def _atr_series(candles: list[Candle], period: int) -> list[FeatureOutput]:
    """Compute the ATR(period) series using Wilder's smoothing.

    First emission at 0-based index `period - 1` (SMA of the first
    `period` true ranges). Before that, the output is invalid with
    `WARMUP_INSUFFICIENT`.
    """
    if period <= 0:
        raise ValueError(f"ATR period must be > 0, got {period}")
    if len(candles) < period + 1:
        # Need at least `period` true ranges, which requires `period + 1`
        # bars (the first bar's TR is H - L with no prev_close).
        return [_invalid(REASON_WARMUP_INSUFFICIENT) for _ in candles]

    # Compute true ranges.
    trs: list[Decimal] = []
    for i, c in enumerate(candles):
        prev_close = candles[i - 1].close if i > 0 else None
        trs.append(true_range(c.high, c.low, prev_close))

    # SMA seed = mean of first `period` TRs.
    seed = trs[0]
    for i in range(1, period):
        seed = _add(seed, trs[i])
    seed = _div(seed, _q(period))

    out: list[FeatureOutput] = []
    for _ in range(period - 1):
        out.append(_invalid(REASON_WARMUP_INSUFFICIENT))
    out.append(_ok(seed))

    # Wilder recurrence: ATR_t = ((period - 1) * ATR_{t-1} + TR_t) / period
    prev = seed
    for i in range(period, len(trs)):
        prev = _div(_add(_mul(_q(period - 1), prev), trs[i]), _q(period))
        out.append(_ok(prev))
    return out


# --------------------------------------------------------------------------- #
# Swing high / low — trailing-window extrema (no future-bar leakage).
# --------------------------------------------------------------------------- #


def _swing_series(
    candles: list[Candle],
    lookback: int,
    *,
    high: bool,
) -> list[FeatureOutput]:
    """Trailing-window swing high (or low) over `lookback` bars.

    At bar index `i`, the swing is the max high (or min low) over
    `candles[i - lookback + 1 .. i]` (inclusive). The swing is
    "confirmed" at the close of bar `i` — no future-bar leakage.

    First valid emission at index `lookback - 1`.
    """
    if lookback <= 0:
        raise ValueError(f"swing lookback must be > 0, got {lookback}")
    out: list[FeatureOutput] = []
    for i in range(len(candles)):
        if i < lookback - 1:
            out.append(_invalid(REASON_WARMUP_INSUFFICIENT))
            continue
        window = candles[i - lookback + 1 : i + 1]
        if high:
            value = max(c.high for c in window)
        else:
            value = min(c.low for c in window)
        out.append(_ok(value))
    return out


# --------------------------------------------------------------------------- #
# Zone — single-swing zone with ATR half-width (Family A Stage A baseline).
# --------------------------------------------------------------------------- #


def _zone_series(
    candles: list[Candle],
    atr_series: list[FeatureOutput],
    swing_low_series: list[FeatureOutput],
    swing_high_series: list[FeatureOutput],
    zone_tolerance_atr: Decimal,
) -> tuple[list[FeatureOutput], list[FeatureOutput]]:
    """Build support/resistance zones from swing pivots with ATR half-width.

    For the tracer slice (Family A Stage A baseline per
    trend-pullback.md §3): the support zone (LONG) is centered on the
    trailing swing low with half-width = zone_tolerance_atr * ATR; the
    resistance zone (SHORT) is centered on the trailing swing high.
    Both are invalid until the underlying swing + ATR are valid.
    """
    n = len(candles)
    zone_upper: list[FeatureOutput] = []
    zone_lower: list[FeatureOutput] = []
    half_width_factor = zone_tolerance_atr
    for i in range(n):
        atr = atr_series[i]
        sl = swing_low_series[i]
        sh = swing_high_series[i]
        if not (atr.valid and sl.valid and sh.valid):
            zone_upper.append(_invalid(REASON_WARMUP_INSUFFICIENT))
            zone_lower.append(_invalid(REASON_WARMUP_INSUFFICIENT))
            continue
        assert atr.value is not None
        assert sl.value is not None
        assert sh.value is not None
        half_width = _mul(half_width_factor, atr.value)
        # Support zone (LONG entry): [swing_low - half, swing_low + half]
        # Resistance zone (SHORT entry): [swing_high - half, swing_high + half]
        zone_lower.append(_ok(_sub(sl.value, half_width)))
        zone_upper.append(_ok(_add(sh.value, half_width)))
    return zone_upper, zone_lower


# --------------------------------------------------------------------------- #
# Gap detection — flag-never-fabricate (D-04).
# --------------------------------------------------------------------------- #


def _expected_bar_duration(candles: list[Candle]) -> timedelta | None:
    """Infer the expected bar duration from the first two candles.

    Returns None if there are fewer than two candles.
    """
    if len(candles) < 2:
        return None
    return candles[1].open_time_utc - candles[0].open_time_utc


def _detect_gaps(
    candles: list[Candle], expected: timedelta | None
) -> list[bool]:
    """Return a per-bar gap flag (True = this bar's open is later than expected).

    A gap means the previous bar's close_time_utc + expected < this bar's
    open_time_utc (a missing bar in between). The first bar is never a gap.
    """
    if expected is None:
        return [False] * len(candles)
    flags: list[bool] = []
    for i, c in enumerate(candles):
        if i == 0:
            flags.append(False)
            continue
        prev_close = candles[i - 1].close_time_utc
        expected_open = prev_close + expected
        if c.open_time_utc > expected_open:
            flags.append(True)
        else:
            flags.append(False)
    return flags


# --------------------------------------------------------------------------- #
# Public entry point — compute_features.
# --------------------------------------------------------------------------- #


def compute_features(
    *,
    symbol: str,
    interval: str,
    candles: list[Candle],
    parameter_set: ParameterSet,
) -> FeatureFrame:
    """Compute the whole-bar feature frame for the last bar in `candles`.

    Returns a `FeatureFrame` describing the LAST bar (index
    `len(candles) - 1`). The strategy gate reads `features_valid` and
    the per-feature `valid` flags; per-feature `reason_code` carries
    the warm-up / gap / invalid-input reason.

    Per D-02: input is closed-candle sequences only. Per D-04: gaps
    invalidate features spanning the gap. Per D-10: every division
    runs under a pinned local context.
    """
    if not candles:
        raise ValueError("compute_features: candles must be non-empty")

    # Validate input shape.
    for c in candles:
        if c.symbol != symbol:
            raise ValueError(
                f"compute_features: candle symbol {c.symbol!r} != {symbol!r}"
            )
        if c.interval != interval:
            raise ValueError(
                f"compute_features: candle interval {c.interval!r} != {interval!r}"
            )

    # Quality gate (D-04 fail-closed): duplicate timestamps and
    # non-monotonic open_time_utc both raise ValueError naming the
    # offending bar index BEFORE any feature computes.
    # Candle.__post_init__ already validates OHLC, naive datetimes,
    # and Decimal typing per-bar; these checks cross bar boundaries.
    for i in range(1, len(candles)):
        prev_open = candles[i - 1].open_time_utc
        cur_open = candles[i].open_time_utc
        if cur_open == prev_open:
            raise ValueError(
                f"compute_features: duplicate open_time_utc={cur_open.isoformat()} "
                f"at bar index {i} (also at bar {i - 1}); "
                "rejected before any feature computed"
            )
        if cur_open < prev_open:
            raise ValueError(
                f"compute_features: timestamp regression at bar index {i}: "
                f"open_time_utc={cur_open.isoformat()} < "
                f"prev open_time_utc={prev_open.isoformat()}; "
                "non-monotonic timestamps rejected before any feature computed"
            )

    # Pull parameters (Decimal-or-int per registry contract).
    swing_lookback = int(parameter_set.params["swing_lookback"])
    zone_tolerance_atr = parameter_set.params["zone_tolerance_atr"]
    if not isinstance(zone_tolerance_atr, Decimal):
        zone_tolerance_atr = Decimal(str(zone_tolerance_atr))

    closes = [c.close for c in candles]

    ema_20 = _ema_series(closes, 20)
    ema_50 = _ema_series(closes, 50)
    ema_200 = _ema_series(closes, 200)
    atr_14 = _atr_series(candles, 14)
    swing_high = _swing_series(candles, swing_lookback, high=True)
    swing_low = _swing_series(candles, swing_lookback, high=False)
    zone_upper, zone_lower = _zone_series(
        candles, atr_14, swing_low, swing_high, zone_tolerance_atr
    )

    # Gap detection — invalidate features spanning a gap.
    expected = _expected_bar_duration(candles)
    gap_flags = _detect_gaps(candles, expected)
    if any(gap_flags):
        # Mark every feature at and after the first gap as GAP_IN_SOURCE.
        first_gap = gap_flags.index(True)
        for series in (
            ema_20,
            ema_50,
            ema_200,
            atr_14,
            swing_high,
            swing_low,
            zone_upper,
            zone_lower,
        ):
            for i in range(first_gap, len(series)):
                if series[i].valid:
                    series[i] = _invalid(REASON_GAP_IN_SOURCE)

    last = len(candles) - 1
    last_close_utc = candles[last].close_time_utc

    # Whole-bar validity = AND of all required features at the last bar.
    required = (
        ema_20[last],
        ema_50[last],
        ema_200[last],
        atr_14[last],
        swing_high[last],
        swing_low[last],
        zone_upper[last],
        zone_lower[last],
    )
    features_valid = all(f.valid for f in required)

    return FeatureFrame(
        symbol=symbol,
        interval=interval,
        bar_index=last,
        bar_close_utc=last_close_utc,
        features_valid=features_valid,
        ema_20=ema_20[last],
        ema_50=ema_50[last],
        ema_200=ema_200[last],
        atr_14=atr_14[last],
        swing_high=swing_high[last],
        swing_low=swing_low[last],
        zone_upper=zone_upper[last],
        zone_lower=zone_lower[last],
    )


__all__ = [
    "compute_features",
    "ema_update",
    "true_range",
]
