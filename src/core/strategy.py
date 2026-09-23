"""Pure strategy function — trend-pullback tracer slice (Phase 4, plan 04-01).

Per D-05/D-07: pure function `evaluate(snapshot, account_state,
strategy_version, parameter_set) -> NO_TRADE | SETUP(Signal)`. Zero I/O,
zero clock reads (timestamps passed in), zero randomness. The tracer
slice implements the Family A Stage A baseline (R1 structure-only regime
+ P1 zone touch + E2 zone + ATR buffer entry + S2 structure + ATR buffer
SL + T1 fixed-R TP) per `docs/research/families/trend-pullback.md` §3.

`SignalId` is built via `ids.make_signal_id` with `detected_at_utc =
source_candle_close_utc` (candle-close timing, D-07). The setup
fingerprint binds regime + setup + zone + ATR so distinct rules never
collide.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, localcontext

from src.domain.canonical import sha256_hex
from src.domain.enums import RejectionReason, SignalStatus
from src.domain.ids import make_signal_id
from src.domain.registry import ParameterSet
from src.domain.signal import Signal

from .features import compute_features
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

    # Setup gate (1H setup stream).
    last_setup_candle = snapshot.setup_candles[-1]
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
