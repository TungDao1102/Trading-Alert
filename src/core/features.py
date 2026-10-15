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

# --------------------------------------------------------------------------- #
# Decimal arithmetic helpers — pinned local context (D-10).
#
# Single source of truth lives in `._decimal` (review WR-16); the names
# are re-exported here so existing `from .features import ...` uses keep
# working.
# --------------------------------------------------------------------------- #
from ._decimal import _PREC, _add, _div, _mul, _q, _sub
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

# Declared bar durations per interval spell. WR-04: the gap check anchors
# on the interval-declared duration, not on inference from the first two
# bars (a leading gap is invisible to inference).
_INTERVAL_BAR_DURATIONS: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}

# EMA periods are fixed by design (Stage A tracer baseline) — they are
# named constants, not registry knobs. The ATR period is a versioned
# registry knob (CR-01); legacy sets predating it fall back to 14,
# reproducing the previously hardcoded ATR-14 exactly (WR-13).
_EMA_FAST_PERIOD = 20
_EMA_MID_PERIOD = 50
_EMA_SLOW_PERIOD = 200
_ATR_PERIOD_FALLBACK = 14


def _atr_period_from_params(parameter_set: ParameterSet) -> int:
    """Return the versioned ATR period, or 14 for legacy sets (WR-13)."""
    raw = parameter_set.params.get("atr_period", _ATR_PERIOD_FALLBACK)
    return int(raw)


def _expected_bar_duration(candles: list[Candle], interval: str) -> timedelta | None:
    """Return the interval-declared bar duration (WR-04).

    Returns None if there are fewer than two candles. Raises
    ValueError on an unknown interval — callers map it to NO_TRADE.
    """
    if len(candles) < 2:
        return None
    declared = _INTERVAL_BAR_DURATIONS.get(interval)
    if declared is None:
        raise ValueError(
            f"_expected_bar_duration: unsupported interval {interval!r}; "
            f"supported: {sorted(_INTERVAL_BAR_DURATIONS)}"
        )
    return declared


def _detect_gaps(candles: list[Candle], expected: timedelta | None) -> list[bool]:
    """Return a per-bar gap flag (True = this bar's open is later than expected).

    WR-04: the expectation anchors on each bar's PREVIOUS bar open
    (`prev.open + expected`), not on `prev.close + expected` with a
    baked-in `-1s` close-time convention. A leading gap (first two bars
    disagreeing with the declared duration) flags bar 1, invalidating
    the whole stream fail-closed. The first bar is never a gap.
    """
    if expected is None:
        return [False] * len(candles)
    flags: list[bool] = []
    for i, c in enumerate(candles):
        if i == 0:
            flags.append(False)
            continue
        prev_open = candles[i - 1].open_time_utc
        expected_open = prev_open + expected
        if c.open_time_utc > expected_open:
            flags.append(True)
        else:
            flags.append(False)
    return flags


def _ema_last(closes: list[Decimal], period: int) -> Decimal | None:
    """The EMA of the last close, or None while warming up; the value `_ema_series` ends on.

    Same SMA seed and recurrence as `_ema_series`; the caller holds the pinned `_PREC` context.
    """
    if period <= 0:
        raise ValueError(f"EMA period must be > 0, got {period}")
    n = len(closes)
    if n < period:
        return None
    seed = closes[0]
    for i in range(1, period):
        seed = seed + closes[i]
    seed = seed / Decimal(period)
    alpha = Decimal(2) / Decimal(period + 1)
    one_minus_alpha = Decimal(1) - alpha
    prev = seed
    for i in range(period, n):
        prev = alpha * closes[i] + one_minus_alpha * prev
    return prev


def _atr_last(candles: list[Candle], period: int) -> Decimal | None:
    """The Wilder ATR of the last bar, or None while warming up; the value `_atr_series` ends on.

    Same true-range rule and recurrence as `_atr_series`; the caller holds the pinned `_PREC`
    context.
    """
    if period <= 0:
        raise ValueError(f"ATR period must be > 0, got {period}")
    n = len(candles)
    if n < period + 1:
        return None
    trs: list[Decimal] = []
    prev_close: Decimal | None = None
    for c in candles:
        if prev_close is None:
            trs.append(c.high - c.low)
        else:
            hl = c.high - c.low
            hc = abs(c.high - prev_close)
            lc = abs(c.low - prev_close)
            if hl >= hc and hl >= lc:
                trs.append(hl)
            elif hc >= lc:
                trs.append(hc)
            else:
                trs.append(lc)
        prev_close = c.close
    seed = trs[0]
    for i in range(1, period):
        seed = seed + trs[i]
    seed = seed / Decimal(period)
    prev = seed
    period_less_one = Decimal(period - 1)
    divisor = Decimal(period)
    for i in range(period, n):
        prev = (period_less_one * prev + trs[i]) / divisor
    return prev


def _swing_last(candles: list[Candle], lookback: int) -> tuple[Decimal | None, Decimal | None]:
    """The trailing swing (high, low) at the last bar, or (None, None) while warming up."""
    if lookback <= 0:
        raise ValueError(f"swing lookback must be > 0, got {lookback}")
    last = len(candles) - 1
    if last < lookback - 1:
        return None, None
    window = candles[last - lookback + 1 : last + 1]
    return max(c.high for c in window), min(c.low for c in window)


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
            raise ValueError(f"compute_features: candle symbol {c.symbol!r} != {symbol!r}")
        if c.interval != interval:
            raise ValueError(f"compute_features: candle interval {c.interval!r} != {interval!r}")

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
    last = len(candles) - 1

    # Only the last bar's features are read by every caller, so only they are computed. The
    # recurrences run over the whole window (the seed is the window's first bars) and every
    # operation rounds at `_PREC`, exactly as the series helpers do; the helpers stay for the
    # other callers. The order of the checks below is the order of the series helpers.
    with localcontext() as ctx:
        ctx.prec = _PREC
        ema_20 = _ema_last(closes, _EMA_FAST_PERIOD)
        ema_50 = _ema_last(closes, _EMA_MID_PERIOD)
        ema_200 = _ema_last(closes, _EMA_SLOW_PERIOD)
        atr_14 = _atr_last(candles, _atr_period_from_params(parameter_set))
        swing_high, swing_low = _swing_last(candles, swing_lookback)
        if atr_14 is not None and swing_high is not None and swing_low is not None:
            half_width = zone_tolerance_atr * atr_14
            zone_lower: Decimal | None = swing_low - half_width
            zone_upper: Decimal | None = swing_high + half_width
        else:
            zone_lower = zone_upper = None

    # Gap detection — a feature at or after the first gap is GAP_IN_SOURCE. The last bar is
    # never before the first gap, so a valid last-bar feature becomes GAP_IN_SOURCE and a
    # warm-up one keeps its warm-up reason.
    expected = _expected_bar_duration(candles, interval)
    has_gap = any(_detect_gaps(candles, expected))

    def last_bar(value: Decimal | None) -> FeatureOutput:
        if value is None:
            return _invalid(REASON_WARMUP_INSUFFICIENT)
        if has_gap:
            return _invalid(REASON_GAP_IN_SOURCE)
        return _ok(value)

    f_ema_20 = last_bar(ema_20)
    f_ema_50 = last_bar(ema_50)
    f_ema_200 = last_bar(ema_200)
    f_atr_14 = last_bar(atr_14)
    f_swing_high = last_bar(swing_high)
    f_swing_low = last_bar(swing_low)
    f_zone_upper = last_bar(zone_upper)
    f_zone_lower = last_bar(zone_lower)

    # Whole-bar validity = AND of all required features at the last bar.
    required = (
        f_ema_20,
        f_ema_50,
        f_ema_200,
        f_atr_14,
        f_swing_high,
        f_swing_low,
        f_zone_upper,
        f_zone_lower,
    )
    features_valid = all(f.valid for f in required)

    return FeatureFrame(
        symbol=symbol,
        interval=interval,
        bar_index=last,
        bar_close_utc=candles[last].close_time_utc,
        features_valid=features_valid,
        ema_20=f_ema_20,
        ema_50=f_ema_50,
        ema_200=f_ema_200,
        atr_14=f_atr_14,
        swing_high=f_swing_high,
        swing_low=f_swing_low,
        zone_upper=f_zone_upper,
        zone_lower=f_zone_lower,
    )


__all__ = [
    "compute_features",
    "ema_update",
    "true_range",
]
