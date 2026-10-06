"""Pure strategy function — family dispatch (Phase 4, plans 04-01 + 04-04).

Per D-05/D-07: pure function `evaluate(snapshot, account_state,
strategy_version, parameter_set) -> NO_TRADE | SETUP(Signal)`. Zero I/O,
zero clock reads (timestamps passed in), zero randomness.

Family dispatch (D-05 — tracer-first, then parallel slices):
  - `trend-pullback` (Family A, tracer): P1 zone touch on a regime-
    confirming 4H context. The Stage A baseline per
    `docs/research/families/trend-pullback.md` §3.
  - `breakout-retest` (Family B, 04-04): breakout (3 consecutive bars
    closing beyond the zone edge) followed by a retest within
    `retest_window_bars` and `retest_depth_atr` × ATR. The countdown
    starts at the breakout-bar close (retest on the breakout bar itself
    never counts) per `docs/research/families/breakout-retest.md` §5.
  - `range-mr` (Family C, 04-04): range-edge touch on a NEUTRAL regime
    with `zone_min_touches` confirmed touches and `zone_aging_bars`
    aging cutoff; range-break invalidation by `range_break_buffer_atr` ×
    ATR per `docs/research/families/range-mr.md` §2.4.

`SignalId` is built via `ids.make_signal_id` with `detected_at_utc =
source_candle_close_utc` (candle-close timing, D-07). The setup
fingerprint binds regime + setup + zone + ATR so distinct rules never
collide.

Per D-08 / Phase-1 D012: no family is declared a winner. All three
families remain hypotheses pending backtest + out-of-sample evidence.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from src.domain.canonical import sha256_hex
from src.domain.enums import RejectionReason, SignalStatus
from src.domain.ids import make_signal_id
from src.domain.registry import ParameterSet
from src.domain.signal import Signal

from ._decimal import _add, _div, _mul, _q, _sub  # noqa: F401 (re-export for compat)
from .features import _atr_series, _swing_series, compute_features
from .pivots import pivot_at
from .types import (
    AccountState,
    Candle,
    FeatureFrame,
    MarketSnapshot,
    SetupResult,
)

# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


_INTERVAL_DURATIONS: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def _interval_duration(interval: str) -> timedelta:
    """Return the canonical bar duration for an interval string."""
    duration = _INTERVAL_DURATIONS.get(interval)
    if duration is None:
        raise ValueError(
            f"_interval_duration: unsupported interval {interval!r}; "
            f"supported: {sorted(_INTERVAL_DURATIONS)}"
        )
    return duration


def _is_forming_bar(candle: Candle, prev: Candle) -> bool:
    """True iff `candle` is a forming (unclosed) bar relative to `prev`.

    Per D-02/STRAT-01: the engine must NEVER source a SETUP from an
    unclosed candle. A bar is forming when its close_time_utc is
    earlier than the expected close_time_utc derived from the previous
    bar's close_time_utc plus the bar duration. Equivalently: the
    candle's close_time_utc has not yet been reached.
    """
    duration = _interval_duration(candle.interval)
    expected_close = prev.close_time_utc + duration
    return candle.close_time_utc < expected_close


# --------------------------------------------------------------------------- #
# Regime gate — Family A R1 (structure-only) on the 4H context.
# --------------------------------------------------------------------------- #


def _resolve_regime(
    context_frame: FeatureFrame,
    last_context_close: Decimal,
) -> str:
    """Resolve the regime verdict from the 4H context frame + last close.

    BULLISH if last close > EMA50(4H); BEARISH if last close < EMA50(4H);
    NEUTRAL otherwise.

    R1 (structure-only) design note: the tracer slice uses EMA50 as the
    regime proxy (an R2-style simplification of R1 — see
    trend-pullback.md §2.1 for the full R1/R2/R3 alternatives; the
    Stage A baseline is R1, but EMA50 is a deterministic proxy that is
    byte-exact reproducible without a structure detector).
    """
    if not context_frame.features_valid:
        return "NO_TRADE"
    assert context_frame.ema_50.value is not None
    if last_context_close > context_frame.ema_50.value:
        return "BULLISH"
    if last_context_close < context_frame.ema_50.value:
        return "BEARISH"
    return "NEUTRAL"


# --------------------------------------------------------------------------- #
# Setup gate — Family A P1 (zone touch) on the 1H setup stream.
# --------------------------------------------------------------------------- #


def _detect_setup(
    setup_frame: FeatureFrame,
    last_setup_candle: Candle,
    regime: str,
    *,
    zone_tolerance_atr: Decimal,
) -> tuple[str, str, Decimal, Decimal] | None:
    """Return (direction, setup_type, zone_upper, zone_lower) or None.

    CR-06: per-side zones, not the cross-range pair. LONG keys off the
    SUPPORT zone (swing low ± tolerance) in a BULLISH regime; SHORT keys
    off the RESISTANCE zone (swing high ± tolerance) in a BEARISH
    regime — per trend-pullback.md §3. A BULLISH bar touching
    RESISTANCE is not a pullback to support and emits nothing. The
    returned zone is the touched side's zone (bound into the setup
    fingerprint), not the full support-to-resistance span.
    """
    if not setup_frame.features_valid:
        return None
    assert setup_frame.swing_low.value is not None
    assert setup_frame.swing_high.value is not None
    assert setup_frame.atr_14.value is not None
    half = _mul(zone_tolerance_atr, setup_frame.atr_14.value)
    support_lower = _sub(setup_frame.swing_low.value, half)
    support_upper = _add(setup_frame.swing_low.value, half)
    resistance_lower = _sub(setup_frame.swing_high.value, half)
    resistance_upper = _add(setup_frame.swing_high.value, half)

    if regime == "BULLISH":
        if support_lower <= last_setup_candle.low <= support_upper:
            return ("LONG", "TREND_PULLBACK_LONG", support_upper, support_lower)
    elif regime == "BEARISH":
        if resistance_lower <= last_setup_candle.high <= resistance_upper:
            return ("SHORT", "TREND_PULLBACK_SHORT", resistance_upper, resistance_lower)
    return None


# --------------------------------------------------------------------------- #
# Setup gate, geometry_version 1 — Family A zone touch on a confirmed pivot.
# --------------------------------------------------------------------------- #


def geometry_version(parameter_set: ParameterSet) -> int | None:
    """The optional registry integer `geometry_version`; None means legacy behavior (D-25)."""
    value = parameter_set.params.get("geometry_version")
    return None if value is None else int(value)


def _detect_pivot_setup(
    setup_candles: list[Candle],
    setup_frame: FeatureFrame,
    regime: str,
    parameter_set: ParameterSet,
) -> tuple[str, str, Decimal, Decimal] | None:
    """Return (direction, setup_type, zone_upper, zone_lower) or None (geometry_version 1).

    D-01/D-03: the setup level is the most recent CONFIRMED pivot (low for LONG, high for
    SHORT) inside `swing_lookback` bars. The evaluated bar is only ever a right-side
    confirmer, so a bar that makes a new N-bar low can no longer signal a pullback to
    support. No confirmed pivot returns None (never a fallback to the trailing extreme).
    The touch test itself is unchanged: the evaluated bar's low (LONG) or high (SHORT)
    lies within `pivot +/- zone_tolerance_atr * ATR`.
    """
    if not setup_frame.features_valid or regime not in ("BULLISH", "BEARISH"):
        return None
    assert setup_frame.atr_14.value is not None
    last = len(setup_candles) - 1
    last_candle = setup_candles[last]
    bullish = regime == "BULLISH"
    level = pivot_at(
        setup_candles,
        last,
        lookback=int(parameter_set.params["swing_lookback"]),
        left=int(parameter_set.params["pivot_left_bars"]),
        right=int(parameter_set.params["pivot_right_bars"]),
        high=not bullish,
    )
    if level is None:
        return None
    half = _mul(Decimal(str(parameter_set.params["zone_tolerance_atr"])), setup_frame.atr_14.value)
    zone_lower = _sub(level, half)
    zone_upper = _add(level, half)
    if bullish:
        if zone_lower <= last_candle.low <= zone_upper:
            return ("LONG", "TREND_PULLBACK_LONG", zone_upper, zone_lower)
    elif zone_lower <= last_candle.high <= zone_upper:
        return ("SHORT", "TREND_PULLBACK_SHORT", zone_upper, zone_lower)
    return None


# --------------------------------------------------------------------------- #
# Setup fingerprint — binds regime + setup + zone + ATR.
# --------------------------------------------------------------------------- #


def _setup_fingerprint(
    *,
    regime: str,
    direction: str,
    setup_type: str,
    zone_upper: Decimal,
    zone_lower: Decimal,
    atr: Decimal,
    ema_20: Decimal,
    ema_50: Decimal,
    ema_200: Decimal,
) -> str:
    """Canonical hash of the setup's parameter-influencing values.

    Per D-07: the fingerprint must bind every value that influences the
    setup so distinct rules never collide. Sorted keys, compact
    separators, Decimal-as-str (canonical.py).
    """
    return sha256_hex(
        {
            "regime": regime,
            "direction": direction,
            "setup_type": setup_type,
            "zone_upper": zone_upper,
            "zone_lower": zone_lower,
            "atr": atr,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "ema_200": ema_200,
        }
    )


# --------------------------------------------------------------------------- #
# Breakout-retest detector (Family B).
# --------------------------------------------------------------------------- #


def _detect_breakout_retest_setup(
    *,
    setup_candles: list[Candle],
    parameter_set: ParameterSet,
) -> tuple[str, str, Decimal, Decimal] | None:
    """Family B detector: breakout followed by a retest within the window.

    Per `docs/research/families/breakout-retest.md` §2.1 (B1 close
    breakout) and §2.2 (R1 touch retest):
      1. `breakout_confirmation_bars` consecutive bars close beyond the
         zone edge — the zone edge is `swing_high[swing_lookback] +
         zone_tolerance_atr * ATR` for LONG (symmetric for SHORT).
      2. The countdown starts at the breakout-bar close: a retest on
         the breakout bar itself NEVER counts (must be a later bar
         within `retest_window_bars`).
      3. The retest bar's extreme pierces into `[zone_edge −
         retest_depth_atr * ATR, zone_edge + retest_depth_atr * ATR]`.

    Self-inflation guard: the zone edge at bar `i` uses the swing and
    ATR at bar `i − breakout_confirmation_bars − 1` (one bar before the
    earliest confirmation bar). This keeps the breakout bars'
    own highs out of the trailing swing window — without this guard
    `swing_high[i]` includes bar `i`'s high and `zone_upper` becomes
    strictly greater than `close[i]`, making the detector unsatisfiable.

    Returns ``(direction, setup_type, zone_upper, zone_lower)`` or
    ``None``.
    """
    breakout_confirmation_bars = int(parameter_set.params["breakout_confirmation_bars"])
    retest_window_bars = int(parameter_set.params["retest_window_bars"])
    retest_depth_atr = Decimal(str(parameter_set.params["retest_depth_atr"]))
    zone_tolerance_atr = Decimal(str(parameter_set.params["zone_tolerance_atr"]))
    swing_lookback = int(parameter_set.params["swing_lookback"])
    atr_period = int(parameter_set.params["atr_period"])

    n = len(setup_candles)
    # WR-15: only breakout_confirmation_bars + swing_lookback of HISTORY
    # is required — the retest window extends FORWARD from the breakout
    # bar, so it must not gate how much history a valid setup needs.
    min_bars = breakout_confirmation_bars + swing_lookback
    if n < min_bars:
        return None

    swing_high_series = _swing_series(setup_candles, swing_lookback, high=True)
    swing_low_series = _swing_series(setup_candles, swing_lookback, high=False)
    atr_series = _atr_series(setup_candles, atr_period)

    # CR-04: every op routes through the pinned prec-28 helpers — no
    # localcontext(prec=50) block, no ambient-precision arithmetic.
    for i in range(n - 1, breakout_confirmation_bars - 1, -1):
        ref_bar = i - breakout_confirmation_bars
        ref_prev = ref_bar - 1
        if ref_prev < 0:
            continue
        sh_ref_out = swing_high_series[ref_prev]
        sl_ref_out = swing_low_series[ref_prev]
        atr_ref_out = atr_series[ref_prev]
        if (
            not sh_ref_out.valid
            or sh_ref_out.value is None
            or not sl_ref_out.valid
            or sl_ref_out.value is None
            or not atr_ref_out.valid
            or atr_ref_out.value is None
        ):
            continue
        # WR-12: one (zone, atr_ref) pair per candidate — the edge AND
        # the retest band derive from the reference bar's ATR, never
        # from a later bar's volatility.
        atr_ref = atr_ref_out.value
        zone_upper = _add(sh_ref_out.value, _mul(zone_tolerance_atr, atr_ref))
        zone_lower = _sub(sl_ref_out.value, _mul(zone_tolerance_atr, atr_ref))

        long_breakout = True
        for j in range(breakout_confirmation_bars):
            if setup_candles[i - j].close <= zone_upper:
                long_breakout = False
                break
        if long_breakout:
            retest_bar_idx = _find_retest_bar(
                setup_candles,
                atr_ref,
                retest_window_bars,
                retest_depth_atr,
                zone_upper,
                i + 1,
                is_long=True,
            )
            if retest_bar_idx is not None:
                return ("LONG", "BREAKOUT_RETEST_LONG", zone_upper, zone_lower)

        if not sl_ref_out.valid or sl_ref_out.value is None:
            continue
        short_breakout = True
        for j in range(breakout_confirmation_bars):
            if setup_candles[i - j].close >= zone_lower:
                short_breakout = False
                break
        if short_breakout:
            retest_bar_idx = _find_retest_bar(
                setup_candles,
                atr_ref,
                retest_window_bars,
                retest_depth_atr,
                zone_lower,
                i + 1,
                is_long=False,
            )
            if retest_bar_idx is not None:
                return (
                    "SHORT",
                    "BREAKOUT_RETEST_SHORT",
                    zone_upper,
                    zone_lower,
                )

    return None


def _find_retest_bar(
    setup_candles: list[Candle],
    atr_ref: Decimal,
    retest_window_bars: int,
    retest_depth_atr: Decimal,
    zone_edge: Decimal,
    start_idx: int,
    *,
    is_long: bool,
) -> int | None:
    """Scan forward from start_idx for a retest bar within window.

    For LONG: the bar's low must be in `[zone_edge −
    retest_depth_atr * ATR_ref, zone_edge + retest_depth_atr * ATR_ref]`.
    For SHORT: the bar's high must be in the same band. `ATR_ref` is the
    reference bar's ATR (WR-12: edge and band share one volatility).
    """
    n = len(setup_candles)
    end_idx = min(start_idx + retest_window_bars, n)
    band = _mul(retest_depth_atr, atr_ref)
    band_lo = _sub(zone_edge, band)
    band_hi = _add(zone_edge, band)
    for k in range(start_idx, end_idx):
        if is_long:
            if band_lo <= setup_candles[k].low <= band_hi:
                return k
        else:
            if band_lo <= setup_candles[k].high <= band_hi:
                return k
    return None


# --------------------------------------------------------------------------- #
# Range mean-reversion detector (Family C).
# --------------------------------------------------------------------------- #


def _detect_range_mr_setup(
    *,
    setup_candles: list[Candle],
    parameter_set: ParameterSet,
) -> tuple[str, str, Decimal, Decimal] | None:
    """Family C detector: range-edge touch on a NEUTRAL regime.

    Per `docs/research/families/range-mr.md` §2.4:
      1. The 4H context must resolve to NEUTRAL (handled by the caller —
         regime gate above rejects BULLISH/BEARISH for this family).
      2. The range is defined by `swing_high` (resistance) and
         `swing_low` (support) on the 1H setup stream.
      3. The zone is valid when `zone_min_touches` bars have touched the
         band AND the most recent touch is within `zone_aging_bars`.
      4. Range-break invalidation: a close beyond the band by
         `range_break_buffer_atr * ATR` invalidates the zone.

    Returns ``(direction, setup_type, zone_upper, zone_lower)`` or
    ``None``.
    """
    zone_min_touches = int(parameter_set.params["zone_min_touches"])
    zone_aging_bars = int(parameter_set.params["zone_aging_bars"])
    range_break_buffer_atr = Decimal(str(parameter_set.params["range_break_buffer_atr"]))
    swing_lookback = int(parameter_set.params["swing_lookback"])
    # CR-01: versioned registry knobs — KeyError (never silent defaults).
    atr_period = int(parameter_set.params["atr_period"])
    touch_tolerance_atr = Decimal(str(parameter_set.params["touch_tolerance_atr"]))

    n = len(setup_candles)
    if n < swing_lookback + zone_aging_bars + 1:
        return None

    swing_high_series = _swing_series(setup_candles, swing_lookback, high=True)
    swing_low_series = _swing_series(setup_candles, swing_lookback, high=False)
    atr_series = _atr_series(setup_candles, atr_period)

    last_idx = n - 1
    ref_idx = last_idx - 1
    sh_ref_out = swing_high_series[ref_idx]
    sl_ref_out = swing_low_series[ref_idx]
    atr_ref_out = atr_series[ref_idx]
    if (
        not sh_ref_out.valid
        or sh_ref_out.value is None
        or not sl_ref_out.valid
        or sl_ref_out.value is None
        or not atr_ref_out.valid
        or atr_ref_out.value is None
    ):
        return None

    # WR-12: one (zone, atr_ref) pair — touch band AND break buffer both
    # derive from the reference bar's ATR. CR-04: pinned prec-28 helpers
    # for every op; comparisons use precomputed bounds, never ambient `-`.
    zone_upper = sh_ref_out.value
    zone_lower = sl_ref_out.value
    atr_ref = atr_ref_out.value
    band = _mul(touch_tolerance_atr, atr_ref)
    lower_lo = _sub(zone_lower, band)
    lower_hi = _add(zone_lower, band)
    upper_lo = _sub(zone_upper, band)
    upper_hi = _add(zone_upper, band)

    # WR-02: one band convention — historical touches and the current
    # bar use the same within-band predicate. The scan covers bars
    # strictly before the reference window (bars that define the
    # reference level itself never count as confirmations of it).
    upper_touches: list[int] = []
    lower_touches: list[int] = []
    for j in range(swing_lookback, ref_idx - swing_lookback + 1):
        if upper_lo <= setup_candles[j].high <= upper_hi:
            upper_touches.append(j)
        if lower_lo <= setup_candles[j].low <= lower_hi:
            lower_touches.append(j)

    breakout_buffer = _mul(range_break_buffer_atr, atr_ref)
    break_lo = _sub(zone_lower, breakout_buffer)
    break_hi = _add(zone_upper, breakout_buffer)
    last_close = setup_candles[last_idx].close
    last_low = setup_candles[last_idx].low
    last_high = setup_candles[last_idx].high
    if last_close < break_lo:
        return None
    if last_close > break_hi:
        return None

    long_eligible = (
        lower_lo <= last_low <= lower_hi
        and len(lower_touches) >= zone_min_touches
        and lower_touches[-1] >= last_idx - zone_aging_bars
        # Dual-touch disambiguation: a wide band can place one bar
        # within BOTH edges — the setup fades the NEAR edge only, so
        # the far-edge side stays ineligible. Ties keep LONG.
        and abs(_sub(last_low, zone_lower)) <= abs(_sub(last_high, zone_upper))
    )
    short_eligible = (
        upper_lo <= last_high <= upper_hi
        and len(upper_touches) >= zone_min_touches
        and upper_touches[-1] >= last_idx - zone_aging_bars
        and abs(_sub(last_high, zone_upper)) < abs(_sub(last_low, zone_lower))
    )

    if long_eligible:
        return ("LONG", "RANGE_MR_LONG", zone_upper, zone_lower)
    if short_eligible:
        return ("SHORT", "RANGE_MR_SHORT", zone_upper, zone_lower)
    return None


# --------------------------------------------------------------------------- #
# Public entry point — evaluate.
# --------------------------------------------------------------------------- #


def evaluate(
    *,
    snapshot: MarketSnapshot,
    account_state: AccountState,
    strategy_version: str,
    parameter_set: ParameterSet,
) -> SetupResult:
    """Pure: (snapshot, account_state, strategy_version, parameter_set) -> SetupResult.

    Per D-07: zero I/O, zero clock reads, zero randomness. The strategy
    emits NO_TRADE with a canonical RejectionReason value when any
    required feature is invalid or the regime/setup gates fail.
    """
    if not snapshot.setup_candles:
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.NO_TRADE_REGIME.value,
        )
    if not snapshot.context_candles:
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.NO_TRADE_REGIME.value,
        )

    # Stream-identity gate (WR-07/WR-05): the setup stream must be
    # stamped with the snapshot's source timeframe (a 1H stream
    # mislabeled "4h" corrupts signal IDs and expiry math), and both
    # streams must use known intervals — an unknown interval is
    # DATA_STALE, never a ValueError out of the pure core.
    if snapshot.setup_candles[0].interval != snapshot.source_timeframe:
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.DATA_STALE.value,
        )
    try:
        _interval_duration(snapshot.setup_candles[0].interval)
        _interval_duration(snapshot.context_candles[0].interval)
    except ValueError:
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.DATA_STALE.value,
        )

    # Compute features on both streams.
    setup_frame = compute_features(
        symbol=snapshot.symbol,
        interval=snapshot.setup_candles[0].interval,
        candles=snapshot.setup_candles,
        parameter_set=parameter_set,
    )
    context_frame = compute_features(
        symbol=snapshot.symbol,
        interval=snapshot.context_candles[0].interval,
        candles=snapshot.context_candles,
        parameter_set=parameter_set,
    )

    # Feature gate (D-03/D-04): any required-feature-invalid on either
    # stream returns NO_TRADE naming the exact reason code. The
    # WARMUP_INSUFFICIENT / GAP_IN_SOURCE / INVALID_INPUT vocabulary
    # propagates verbatim so the boundary + determinism suites can pin
    # the reason without parsing generic regime messages.
    for frame, _label in (
        (setup_frame, "setup"),
        (context_frame, "context"),
    ):
        if frame.features_valid:
            continue
        # Pick the first invalid feature's reason for the rejection.
        for feat in (
            frame.ema_20,
            frame.ema_50,
            frame.ema_200,
            frame.atr_14,
            frame.swing_high,
            frame.swing_low,
            frame.zone_upper,
            frame.zone_lower,
        ):
            if not feat.valid:
                reason = feat.reason_code
                # Map GAP_IN_SOURCE to DATA_STALE for the strategy's
                # canonical RejectionReason vocabulary (the feature
                # layer speaks the gap vocabulary; the strategy speaks
                # the cross-module rejection vocabulary).
                if reason == "GAP_IN_SOURCE":
                    reason = RejectionReason.DATA_STALE.value
                return SetupResult(
                    is_no_trade=True,
                    reason_code=reason,
                )
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.NO_TRADE_REGIME.value,
        )

    # Regime gate (4H context) — family-specific.
    last_context_close = snapshot.context_candles[-1].close
    regime = _resolve_regime(context_frame, last_context_close)
    if regime == "NO_TRADE":
        # The context frame was invalid: no regime verdict exists, so none is named.
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.NO_TRADE_REGIME.value,
        )
    if parameter_set.strategy_id != "range-mr" and regime == "NEUTRAL":
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.NO_TRADE_REGIME.value,
            regime=regime,
        )
    # CR-07: range-mr is a NEUTRAL-regime family — fading an established
    # trend as "mean reversion" is the false-positive class the regime
    # gate exists to prevent.
    if parameter_set.strategy_id == "range-mr" and regime != "NEUTRAL":
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.NO_TRADE_REGIME.value,
            regime=regime,
        )

    # Forming-bar gate (D-02/STRAT-01): the engine must NEVER source a
    # SETUP from an unclosed candle. Both streams are gated (WR-05) —
    # a forming bar on either side means the market state is not yet
    # finalized. Single-bar streams carry no chaining evidence either
    # way, so they skip this gate and fall through to the feature gate,
    # which rejects them fail-closed with WARMUP_INSUFFICIENT.
    last_setup_candle = snapshot.setup_candles[-1]
    last_context_candle = snapshot.context_candles[-1]
    setup_forming = len(snapshot.setup_candles) >= 2 and _is_forming_bar(
        last_setup_candle, snapshot.setup_candles[-2]
    )
    context_forming = len(snapshot.context_candles) >= 2 and _is_forming_bar(
        last_context_candle, snapshot.context_candles[-2]
    )
    if setup_forming or context_forming:
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.DATA_STALE.value,
            regime=regime,
        )

    # Setup gate (1H setup stream) — family dispatch (D-05).
    if parameter_set.strategy_id == "breakout-retest":
        setup = _detect_breakout_retest_setup(
            setup_candles=snapshot.setup_candles,
            parameter_set=parameter_set,
        )
    elif parameter_set.strategy_id == "range-mr":
        setup = _detect_range_mr_setup(
            setup_candles=snapshot.setup_candles,
            parameter_set=parameter_set,
        )
    elif parameter_set.strategy_id == "trend-pullback":
        if geometry_version(parameter_set) is not None:
            setup = _detect_pivot_setup(snapshot.setup_candles, setup_frame, regime, parameter_set)
        else:
            zone_tolerance_atr = Decimal(str(parameter_set.params["zone_tolerance_atr"]))
            setup = _detect_setup(
                setup_frame,
                last_setup_candle,
                regime,
                zone_tolerance_atr=zone_tolerance_atr,
            )
    else:
        # WR-11: unknown family is NO_TRADE — never default to Family A.
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.DATA_STALE.value,
            regime=regime,
        )
    if setup is None:
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.NO_TRADE_REGIME.value,
            regime=regime,
        )
    direction, setup_type, zone_upper, zone_lower = setup

    # Build the Signal.
    assert setup_frame.atr_14.value is not None
    assert setup_frame.ema_20.value is not None
    assert setup_frame.ema_50.value is not None
    assert setup_frame.ema_200.value is not None

    fingerprint = _setup_fingerprint(
        regime=regime,
        direction=direction,
        setup_type=setup_type,
        zone_upper=zone_upper,
        zone_lower=zone_lower,
        atr=setup_frame.atr_14.value,
        ema_20=setup_frame.ema_20.value,
        ema_50=setup_frame.ema_50.value,
        ema_200=setup_frame.ema_200.value,
    )

    source_close = last_setup_candle.close_time_utc
    signal_expiry_hours = int(parameter_set.params["signal_expiry_hours"])
    expires_at = source_close + timedelta(hours=signal_expiry_hours)

    signal_id = make_signal_id(
        strategy_id=parameter_set.strategy_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set.parameter_set_id,
        symbol=snapshot.symbol,
        source_timeframe=snapshot.source_timeframe,
        source_candle_close_utc=source_close,
        setup_fingerprint=fingerprint,
    )

    signal = Signal(
        signal_id=signal_id,
        strategy_id=parameter_set.strategy_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set.parameter_set_id,
        parameter_set_hash=parameter_set.parameter_set_hash,
        symbol=snapshot.symbol,
        direction=direction,
        setup_type=setup_type,
        source_timeframe=snapshot.source_timeframe,
        source_candle_close_utc=source_close,
        detected_at_utc=source_close,  # D-07 candle-close timing
        status=SignalStatus.DETECTED,
        expires_at_utc=expires_at,
        invalidated_at_utc=None,
    )

    return SetupResult(
        is_no_trade=False,
        signal=signal,
        reason_code="OK",
        regime=regime,
    )


__all__ = ["evaluate"]
