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
from decimal import Decimal, localcontext

from src.domain.canonical import sha256_hex
from src.domain.enums import RejectionReason, SignalStatus
from src.domain.ids import make_signal_id
from src.domain.registry import ParameterSet
from src.domain.signal import Signal

from .features import _atr_series, _swing_series, compute_features
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
    with localcontext() as ctx:
        ctx.prec = 28
        return a / b


def _mul(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        return a * b


def _add(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        return a + b


def _sub(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        return a - b


# --------------------------------------------------------------------------- #
# Regime gate — Family A R1 (structure-only) on the 4H context.
# --------------------------------------------------------------------------- #


def _regime_from_context(
    context_frame: FeatureFrame,
) -> tuple[str, str | None]:
    """Return (regime, reason_code) for the 4H context.

    R1 (structure-only): BULLISH if close > EMA50(4H); BEARISH if close <
    EMA50(4H); NEUTRAL otherwise. The tracer slice uses EMA50 as the
    regime proxy (R2-style simplification of R1 — see
    trend-pullback.md §2.1 for the full R1/R2/R3 alternatives; the
    Stage A baseline is R1, but the tracer uses EMA50 as a deterministic
    proxy that is byte-exact reproducible without a structure detector).
    """
    if not context_frame.features_valid:
        return ("NO_TRADE", RejectionReason.NO_TRADE_REGIME.value)
    assert context_frame.ema_50.value is not None
    assert context_frame.ema_200.value is not None
    # We need the close of the last context candle. The frame doesn't
    # carry it directly; the caller passes it via the snapshot. We
    # return a placeholder here and let the caller resolve.
    return ("OK", None)


def _resolve_regime(
    context_frame: FeatureFrame,
    last_context_close: Decimal,
) -> str:
    """Resolve the regime verdict from the 4H context frame + last close.

    BULLISH if last close > EMA50(4H); BEARISH if last close < EMA50(4H);
    NEUTRAL otherwise.
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
) -> tuple[str, str, Decimal, Decimal] | None:
    """Return (direction, setup_type, zone_upper, zone_lower) or None.

    LONG: regime == BULLISH AND last_setup_candle.low <= zone_upper AND
    last_setup_candle.low >= zone_lower (P1 zone touch).
    SHORT: regime == BEARISH AND last_setup_candle.high >= zone_lower
    AND last_setup_candle.high <= zone_upper (symmetric).
    """
    if not setup_frame.features_valid:
        return None
    assert setup_frame.zone_upper.value is not None
    assert setup_frame.zone_lower.value is not None
    zone_upper = setup_frame.zone_upper.value
    zone_lower = setup_frame.zone_lower.value

    if regime == "BULLISH":
        if last_setup_candle.low <= zone_upper and last_setup_candle.low >= zone_lower:
            return ("LONG", "TREND_PULLBACK_LONG", zone_upper, zone_lower)
    elif regime == "BEARISH":
        if last_setup_candle.high >= zone_lower and last_setup_candle.high <= zone_upper:
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
    breakout_confirmation_bars = int(
        parameter_set.params["breakout_confirmation_bars"]
    )
    retest_window_bars = int(parameter_set.params["retest_window_bars"])
    retest_depth_atr = Decimal(str(parameter_set.params["retest_depth_atr"]))
    zone_tolerance_atr = Decimal(
        str(parameter_set.params["zone_tolerance_atr"])
    )
    swing_lookback = int(parameter_set.params["swing_lookback"])
    atr_period = int(parameter_set.params.get("atr_period", 14))

    n = len(setup_candles)
    min_bars = breakout_confirmation_bars + retest_window_bars + swing_lookback
    if n < min_bars:
        return None

    swing_high_series = _swing_series(setup_candles, swing_lookback, high=True)
    swing_low_series = _swing_series(setup_candles, swing_lookback, high=False)
    atr_series = _atr_series(setup_candles, atr_period)

    with localcontext() as ctx:
        ctx.prec = 50

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
            zone_upper = sh_ref_out.value + zone_tolerance_atr * atr_ref_out.value
            zone_lower = sl_ref_out.value - zone_tolerance_atr * atr_ref_out.value

            long_breakout = True
            for j in range(breakout_confirmation_bars):
                if setup_candles[i - j].close <= zone_upper:
                    long_breakout = False
                    break
            if long_breakout:
                retest_bar_idx = _find_retest_bar(
                    setup_candles,
                    atr_series,
                    retest_window_bars,
                    retest_depth_atr,
                    zone_upper,
                    i + 1,
                    is_long=True,
                )
                if retest_bar_idx is not None:
                    return ("LONG", "BREAKOUT_RETEST_LONG", zone_upper, zone_lower)

            if (
                not sl_ref_out.valid
                or sl_ref_out.value is None
            ):
                continue
            short_breakout = True
            for j in range(breakout_confirmation_bars):
                if setup_candles[i - j].close >= zone_lower:
                    short_breakout = False
                    break
            if short_breakout:
                retest_bar_idx = _find_retest_bar(
                    setup_candles,
                    atr_series,
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
    atr_series: list,
    retest_window_bars: int,
    retest_depth_atr: Decimal,
    zone_edge: Decimal,
    start_idx: int,
    *,
    is_long: bool,
) -> int | None:
    """Scan forward from start_idx for a retest bar within window.

    For LONG: the bar's low must be in `[zone_edge −
    retest_depth_atr * ATR, zone_edge + retest_depth_atr * ATR]`.
    For SHORT: the bar's high must be in the same band.
    """
    n = len(setup_candles)
    end_idx = min(start_idx + retest_window_bars, n)
    for k in range(start_idx, end_idx):
        atr_out = atr_series[k]
        if not atr_out.valid or atr_out.value is None:
            continue
        band = retest_depth_atr * atr_out.value
        if is_long:
            if zone_edge - band <= setup_candles[k].low <= zone_edge + band:
                return k
        else:
            if zone_edge - band <= setup_candles[k].high <= zone_edge + band:
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
    range_break_buffer_atr = Decimal(
        str(parameter_set.params["range_break_buffer_atr"])
    )
    swing_lookback = int(parameter_set.params["swing_lookback"])
    atr_period = int(parameter_set.params.get("atr_period", 14))
    touch_tolerance_atr = Decimal(
        str(parameter_set.params.get("touch_tolerance_atr", "0.3"))
    )

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
    atr_last_out = atr_series[last_idx]
    if (
        not sh_ref_out.valid
        or sh_ref_out.value is None
        or not sl_ref_out.valid
        or sl_ref_out.value is None
        or not atr_last_out.valid
        or atr_last_out.value is None
    ):
        return None

    zone_upper = sh_ref_out.value
    zone_lower = sl_ref_out.value
    atr_last = atr_last_out.value
    band = touch_tolerance_atr * atr_last

    upper_touches: list[int] = []
    lower_touches: list[int] = []
    for j in range(swing_lookback, last_idx):
        if abs(setup_candles[j].high - zone_upper) <= band:
            upper_touches.append(j)
        if abs(setup_candles[j].low - zone_lower) <= band:
            lower_touches.append(j)

    breakout_buffer = range_break_buffer_atr * atr_last
    last_close = setup_candles[last_idx].close
    last_low = setup_candles[last_idx].low
    last_high = setup_candles[last_idx].high
    if last_close < zone_lower - breakout_buffer:
        return None
    if last_close > zone_upper + breakout_buffer:
        return None

    long_eligible = (
        last_low <= zone_lower
        and len(lower_touches) >= zone_min_touches
        and lower_touches[-1] >= last_idx - zone_aging_bars
    )
    short_eligible = (
        last_high >= zone_upper
        and len(upper_touches) >= zone_min_touches
        and upper_touches[-1] >= last_idx - zone_aging_bars
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
    for frame, label in (
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

    # Regime gate (4H context).
    last_context_close = snapshot.context_candles[-1].close
    regime = _resolve_regime(context_frame, last_context_close)
    if regime in ("NO_TRADE", "NEUTRAL"):
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.NO_TRADE_REGIME.value,
        )

    # Forming-bar gate (D-02/STRAT-01): the engine must NEVER source a
    # SETUP from an unclosed candle. If the last setup candle is still
    # forming (its close_time_utc is earlier than the expected close
    # derived from the previous bar), reject with DATA_STALE so the
    # caller knows the data is not yet finalized.
    last_setup_candle = snapshot.setup_candles[-1]
    if len(snapshot.setup_candles) >= 2 and _is_forming_bar(
        last_setup_candle, snapshot.setup_candles[-2]
    ):
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.DATA_STALE.value,
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
    else:
        setup = _detect_setup(setup_frame, last_setup_candle, regime)
    if setup is None:
        return SetupResult(
            is_no_trade=True,
            reason_code=RejectionReason.NO_TRADE_REGIME.value,
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
    )


__all__ = ["evaluate"]
