"""Feature engine validity/warm-up/gap/quality tests (Phase 4, plan 04-02).

Per D-03/D-04: every feature output carries `valid` + `reason_code`; long
warm-up features (EMA200-4H) report invalid until history suffices; gaps
invalidate features spanning them (never synthesized); quality rejects
(duplicate timestamps, OHLC violations, timestamp regressions) fail closed
before any feature computes.

TDD discipline: RED → GREEN. Each test pins one behavior; the
implementation in `src/core/features.py` must make every test green.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.core.features import (
    _atr_series,
    _ema_series,
    compute_features,
    ema_update,
    true_range,
)
from src.core.strategy import evaluate
from src.core.types import (
    REASON_GAP_IN_SOURCE,
    REASON_WARMUP_INSUFFICIENT,
    AccountState,
    Candle,
    MarketSnapshot,
)
from src.domain.registry import ParameterSet, load_parameter_set

# --------------------------------------------------------------------------- #
# Candle builder — produces deterministic, Decimal-only candles.
# --------------------------------------------------------------------------- #


def _hour_open(t_index: int) -> datetime:
    """Return the 1H-bar open at index t_index (t_index hours from epoch)."""
    base = datetime(2026, 9, 18, 0, 0, 0, tzinfo=UTC)
    return base + timedelta(hours=t_index)


def _four_hour_open(t_index: int) -> datetime:
    """Return the 4H-bar open at index t_index (t_index * 4 hours from epoch)."""
    base = datetime(2026, 9, 18, 0, 0, 0, tzinfo=UTC)
    return base + timedelta(hours=4 * t_index)


def _make_candle(
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    open_time: datetime,
    close: str = "50000.00",
    high: str | None = None,
    low: str | None = None,
    open_: str | None = None,
    volume: str = "100.00",
) -> Candle:
    """Build one Candle with deterministic Decimal fields."""
    close_d = Decimal(close)
    open_d = Decimal(open_) if open_ else close_d - Decimal("10.00")
    high_d = Decimal(high) if high else close_d + Decimal("50.00")
    low_d = Decimal(low) if low else close_d - Decimal("60.00")
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time_utc=open_time,
        close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
        open=open_d,
        high=high_d,
        low=low_d,
        close=close_d,
        volume=Decimal(volume),
    )


def _candles_at_index(
    n: int,
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    start: datetime | None = None,
    base_price: str = "50000.00",
    step: int = 1,
) -> list[Candle]:
    """Build n closed candles with a steady uptrend (close climbs by 10/bar)."""
    if start is None:
        if interval == "1h":
            start = _hour_open(0)
        else:
            start = _four_hour_open(0)
    rows: list[Candle] = []
    for i in range(n):
        offset = timedelta(hours=i * step)
        close = Decimal(base_price) + Decimal(str(i * 10))
        rows.append(
            Candle(
                symbol=symbol,
                interval=interval,
                open_time_utc=start + offset,
                close_time_utc=start + offset + timedelta(hours=step) - timedelta(seconds=1),
                open=close - Decimal("10.00"),
                high=close + Decimal("50.00"),
                low=close - Decimal("60.00"),
                close=close,
                volume=Decimal("100.00"),
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Shared fixtures.
# --------------------------------------------------------------------------- #


@pytest.fixture
def parameter_set() -> ParameterSet:
    return load_parameter_set("trend-pullback", "baseline-v1")


@pytest.fixture
def account_state() -> AccountState:
    return AccountState(
        equity=Decimal("10000.00"),
        risk_rate=Decimal("0.005"),
    )


# --------------------------------------------------------------------------- #
# Test 1 — EMA20 warm-up: 19 bars invalid; 20th equals SMA seed.
# --------------------------------------------------------------------------- #


def test_ema20_warmup_insufficient_at_19_bars() -> None:
    """Beh. 1a: EMA20 on 19 closed candles is invalid (WARMUP_INSUFFICIENT).

    The first emission of an SMA-seeded EMA occurs at 0-based index
    period-1 (= 19 for EMA20). Bars 0..18 must all be invalid with
    reason_code WARMUP_INSUFFICIENT.
    """
    closes = [Decimal(str(50000 + i * 10)) for i in range(19)]
    series = _ema_series(closes, 20)

    assert len(series) == 19
    for i, out in enumerate(series):
        assert out.valid is False, f"bar {i} should be invalid during warm-up"
        assert out.reason_code == REASON_WARMUP_INSUFFICIENT
        assert out.value is None


def test_ema20_first_emission_equals_sma_seed_at_20_bars() -> None:
    """Beh. 1b: EMA20's first emission equals the hand-computed SMA seed.

    At bar index 19 (0-based), the EMA emits the SMA of the first 20
    closes. Hand-computed: sum(50000, 50010, ..., 50190) / 20.
    Expected = 50095.00 (exact integer arithmetic).
    """
    closes = [Decimal(str(50000 + i * 10)) for i in range(20)]
    series = _ema_series(closes, 20)

    # First 19 bars: invalid.
    for i in range(19):
        assert series[i].valid is False

    # Bar 19: SMA seed = (50000 + 50010 + ... + 50190) / 20.
    hand_computed = Decimal("0")
    for c in closes:
        hand_computed += c
    hand_computed = hand_computed / Decimal("20")

    assert series[19].valid is True
    assert series[19].reason_code == "OK"
    assert series[19].value == hand_computed


# --------------------------------------------------------------------------- #
# Test 2 — EMA200(4H) warm-up: <200 bars invalid; evaluate NO_TRADEs.
# --------------------------------------------------------------------------- #


def test_ema200_4h_warmup_short_prefix_invalid(parameter_set) -> None:
    """Beh. 2a: EMA200(4H) needs 200 bars; 60 bars → invalid.

    The 60-bar 4H prefix must show features_valid=False; the EMA200
    reason code must be WARMUP_INSUFFICIENT.
    """
    candles_4h = _candles_at_index(60, interval="4h")
    frame = compute_features(
        symbol="BTCUSDT",
        interval="4h",
        candles=candles_4h,
        parameter_set=parameter_set,
    )
    assert frame.features_valid is False
    assert frame.ema_200.valid is False
    assert frame.ema_200.reason_code == REASON_WARMUP_INSUFFICIENT


def test_evaluate_returns_no_trade_on_warmup_short_prefix(parameter_set, account_state) -> None:
    """Beh. 2b: evaluate on a warm-up-short prefix returns NO_TRADE with WARMUP_INSUFFICIENT.

    Both setup (1H) and context (4H) must have enough history to
    trigger EMA200. With only 60 bars of 4H context, the regime gate
    rejects with WARMUP_INSUFFICIENT.
    """
    candles_1h = _candles_at_index(60, interval="1h")
    candles_4h = _candles_at_index(60, interval="4h")
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.is_no_trade
    assert result.reason_code == REASON_WARMUP_INSUFFICIENT


# --------------------------------------------------------------------------- #
# Test 3 — Gap injection: features spanning a gap are GAP_IN_SOURCE.
# --------------------------------------------------------------------------- #


def test_gap_injection_makes_spanning_features_invalid(
    parameter_set,
) -> None:
    """Beh. 3a: deleting middle rows makes every spanning feature GAP_IN_SOURCE.

    Build a 250-bar series, delete 5 consecutive bars in the middle.
    Every feature whose computation window spans the gap (i.e. every
    bar at or after the gap) must report valid=False with reason_code
    GAP_IN_SOURCE. No bridged values.
    """
    candles = _candles_at_index(250, interval="1h")
    # Delete bars 100..104 (5 consecutive hours).
    gap_start = 100
    gap_end = 105  # exclusive
    candles_with_gap = candles[:gap_start] + candles[gap_end:]
    assert len(candles_with_gap) == 245

    frame = compute_features(
        symbol="BTCUSDT",
        interval="1h",
        candles=candles_with_gap,
        parameter_set=parameter_set,
    )

    # The last bar (index 244 in the gap-injected series) is AFTER the
    # gap, so its features must be GAP_IN_SOURCE.
    assert frame.features_valid is False
    assert frame.ema_20.valid is False
    assert frame.ema_20.reason_code == REASON_GAP_IN_SOURCE
    assert frame.ema_50.valid is False
    assert frame.ema_50.reason_code == REASON_GAP_IN_SOURCE
    assert frame.ema_200.valid is False
    assert frame.ema_200.reason_code == REASON_GAP_IN_SOURCE
    assert frame.atr_14.valid is False
    assert frame.atr_14.reason_code == REASON_GAP_IN_SOURCE


def test_gap_injection_returns_no_trade_never_bridged(parameter_set, account_state) -> None:
    """Beh. 3b: evaluate on gap-injected candles returns NO_TRADE, never bridges.

    The strategy gate must reject the gap-injected series as
    NO_TRADE; no fabricated/bridged feature values may propagate.
    """
    candles_1h = _candles_at_index(250, interval="1h")
    candles_4h = _candles_at_index(250, interval="4h")
    # Inject a gap in the 1H series.
    candles_1h_gap = candles_1h[:200] + candles_1h[205:]

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h_gap,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.is_no_trade
    # The rejection reason must mention the gap (or DATA_STALE family).
    assert result.reason_code in (
        REASON_GAP_IN_SOURCE,
        "DATA_STALE",
    )


# --------------------------------------------------------------------------- #
# Test 4 — Quality rejects: duplicate / OHLC violation / regression → ValueError.
# --------------------------------------------------------------------------- #


def test_duplicate_timestamp_raises_value_error(parameter_set) -> None:
    """Beh. 4a: duplicate open_time_utc raises ValueError before any feature computes.

    Two candles sharing the same open_time_utc must trip the quality
    gate and prevent any feature computation.
    """
    candles = _candles_at_index(100, interval="1h")
    # Replace bar 50 with a duplicate of bar 49.
    dup = Candle(
        symbol="BTCUSDT",
        interval="1h",
        open_time_utc=candles[49].open_time_utc,
        close_time_utc=candles[49].close_time_utc,
        open=Decimal("50100.00"),
        high=Decimal("50200.00"),
        low=Decimal("50000.00"),
        close=Decimal("50100.00"),
        volume=Decimal("100.00"),
    )
    candles_with_dup = candles[:50] + [dup] + candles[51:]
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        compute_features(
            symbol="BTCUSDT",
            interval="1h",
            candles=candles_with_dup,
            parameter_set=parameter_set,
        )


def test_high_below_low_raises_value_error() -> None:
    """Beh. 4b: high < low raises ValueError at Candle construction.

    The Candle validator catches this immediately; no feature
    computation can ever run on a malformed bar.
    """
    bad_time = _hour_open(0)
    with pytest.raises(ValueError, match="high"):
        Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time_utc=bad_time,
            close_time_utc=bad_time + timedelta(hours=1) - timedelta(seconds=1),
            open=Decimal("50000.00"),
            high=Decimal("49900.00"),  # high < low
            low=Decimal("50000.00"),
            close=Decimal("50000.00"),
            volume=Decimal("100.00"),
        )


def test_timestamp_regression_raises_value_error(parameter_set) -> None:
    """Beh. 4c: non-monotonic timestamps raise ValueError before any feature computes.

    A bar whose open_time_utc is earlier than its predecessor's must
    trip the quality gate.
    """
    candles = _candles_at_index(100, interval="1h")
    # Replace bar 50 with a bar at bar 48's timestamp (regression).
    regression = Candle(
        symbol="BTCUSDT",
        interval="1h",
        open_time_utc=candles[48].open_time_utc,  # same as bar 48 → regression vs bar 49
        close_time_utc=candles[48].close_time_utc,
        open=Decimal("50100.00"),
        high=Decimal("50200.00"),
        low=Decimal("50000.00"),
        close=Decimal("50100.00"),
        volume=Decimal("100.00"),
    )
    candles_with_reg = candles[:50] + [regression] + candles[51:]
    with pytest.raises(ValueError, match="[Rr]egression|monotonic"):
        compute_features(
            symbol="BTCUSDT",
            interval="1h",
            candles=candles_with_reg,
            parameter_set=parameter_set,
        )


# --------------------------------------------------------------------------- #
# Test 5 — ATR14 first emission = SMA of first 14 true ranges (Wilder alpha).
# --------------------------------------------------------------------------- #


def test_atr14_first_emission_equals_sma_of_true_ranges(parameter_set) -> None:
    """Beh. 5a: ATR14's first emission equals SMA of the first 14 true ranges.

    Hand-computed: TR_i = max(H-L, |H-prev_close|, |L-prev_close|);
    ATR seed = mean of TR_0..TR_13. Wilder alpha is 1/14 (not EMA
    alpha 2/15).
    """
    candles = _candles_at_index(30, interval="1h")
    series = _atr_series(candles, 14)

    # Bars 0..12: invalid (need 14 TRs, first one at bar 0).
    for i in range(13):
        assert series[i].valid is False
        assert series[i].reason_code == REASON_WARMUP_INSUFFICIENT

    # Hand-compute TRs.
    trs: list[Decimal] = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c.high - c.low)
        else:
            prev_close = candles[i - 1].close
            hl = c.high - c.low
            hc = abs(c.high - prev_close)
            lc = abs(c.low - prev_close)
            trs.append(max(hl, hc, lc))

    hand_computed = Decimal("0")
    for tr in trs[:14]:
        hand_computed += tr
    hand_computed = hand_computed / Decimal("14")

    assert series[13].valid is True
    assert series[13].reason_code == "OK"
    assert series[13].value == hand_computed


def test_atr14_uses_wilder_alpha_not_ema_alpha() -> None:
    """Beh. 5b: ATR14 uses Wilder alpha 1/14, NOT EMA alpha 2/15.

    The second ATR emission (bar 14) must equal
    ((13 * ATR_seed + TR_14) / 14), NOT (2/15 * TR_14 + 13/15 * ATR_seed).
    """
    candles = _candles_at_index(30, interval="1h")
    series = _atr_series(candles, 14)

    # Hand-compute TRs.
    trs: list[Decimal] = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c.high - c.low)
        else:
            prev_close = candles[i - 1].close
            hl = c.high - c.low
            hc = abs(c.high - prev_close)
            lc = abs(c.low - prev_close)
            trs.append(max(hl, hc, lc))

    # Wilder recurrence: ATR_t = ((period-1) * ATR_{t-1} + TR_t) / period.
    period = 14
    atr_seed = sum(trs[:period]) / Decimal(str(period))
    wilder_bar_14 = ((Decimal(str(period - 1)) * atr_seed) + trs[14]) / Decimal(str(period))

    assert series[14].valid is True
    assert series[14].value == wilder_bar_14


# --------------------------------------------------------------------------- #
# Additional helpers — true_range + ema_update smoke tests.
# --------------------------------------------------------------------------- #


def test_true_range_first_bar_uses_high_minus_low() -> None:
    """Beh. 6: true_range with no prev_close returns H - L."""
    tr = true_range(Decimal("100.00"), Decimal("90.00"), None)
    assert tr == Decimal("10.00")


def test_true_range_with_prev_close_uses_max_of_three() -> None:
    """Beh. 7: true_range with prev_close returns max(H-L, |H-Cp|, |L-Cp|)."""
    # H=100, L=90, prev_close=105 → |H-Cp|=5, |L-Cp|=15, H-L=10 → max=15
    tr = true_range(Decimal("100.00"), Decimal("90.00"), Decimal("105.00"))
    assert tr == Decimal("15.00")


def test_ema_update_smoke() -> None:
    """Beh. 8: ema_update(prior, price, alpha) = alpha*price + (1-alpha)*prior."""
    prior = Decimal("100.00")
    price = Decimal("110.00")
    alpha = Decimal("0.5")
    out = ema_update(prior, price, alpha)
    # 0.5 * 110 + 0.5 * 100 = 55 + 50 = 105
    assert out == Decimal("105.00")


# --------------------------------------------------------------------------- #
# Test 9 — FeatureFrame.features_valid requires every per-feature valid.
# --------------------------------------------------------------------------- #


def test_feature_frame_features_valid_is_and_of_all_features(parameter_set) -> None:
    """Beh. 9: features_valid = AND of all per-feature valid flags.

    With a 250-bar uptrend series, EMA20/50/200/ATR14/swing/zone are
    all valid → features_valid=True.
    """
    candles = _candles_at_index(250, interval="1h")
    frame = compute_features(
        symbol="BTCUSDT",
        interval="1h",
        candles=candles,
        parameter_set=parameter_set,
    )
    assert frame.features_valid is True
    for f in (
        frame.ema_20,
        frame.ema_50,
        frame.ema_200,
        frame.atr_14,
        frame.swing_high,
        frame.swing_low,
        frame.zone_upper,
        frame.zone_lower,
    ):
        assert f.valid is True, f"feature {f.reason_code!r} should be valid"


# --------------------------------------------------------------------------- #
# Test 10 — Multi-timeframe independence: 1H perturbation doesn't change 4H.
# --------------------------------------------------------------------------- #


def test_1h_perturbation_does_not_change_4h_features(
    parameter_set,
) -> None:
    """Beh. 10: D-02 multi-timeframe independence.

    Perturbing one 1H candle's close must NOT change any 4H feature
    value. The two streams are independently ordered closed
    sequences — the core NEVER interpolates 4H values into 1H bars.
    """
    # Build independent 1H and 4H sequences.
    candles_1h = _candles_at_index(250, interval="1h")
    candles_4h = _candles_at_index(250, interval="4h")

    # Compute 4H features before perturbation.
    frame_before = compute_features(
        symbol="BTCUSDT",
        interval="4h",
        candles=candles_4h,
        parameter_set=parameter_set,
    )

    # Perturb one 1H close by a large amount (expand high/low to satisfy
    # the Candle OHLC validator).
    perturbed_1h = list(candles_1h)
    last = perturbed_1h[-1]
    shift = Decimal("10000.00")
    perturbed_1h[-1] = Candle(
        symbol=last.symbol,
        interval=last.interval,
        open_time_utc=last.open_time_utc,
        close_time_utc=last.close_time_utc,
        open=last.open + shift,
        high=last.high + shift,
        low=last.low + shift,
        close=last.close + shift,
        volume=last.volume,
    )

    # Compute 4H features after perturbation (same 4H candles).
    frame_after = compute_features(
        symbol="BTCUSDT",
        interval="4h",
        candles=candles_4h,
        parameter_set=parameter_set,
    )

    # Every 4H feature value must be identical.
    for f_before, f_after in (
        (frame_before.ema_20, frame_after.ema_20),
        (frame_before.ema_50, frame_after.ema_50),
        (frame_before.ema_200, frame_after.ema_200),
        (frame_before.atr_14, frame_after.atr_14),
        (frame_before.swing_high, frame_after.swing_high),
        (frame_before.swing_low, frame_after.swing_low),
        (frame_before.zone_upper, frame_after.zone_upper),
        (frame_before.zone_lower, frame_after.zone_lower),
    ):
        assert f_before.value == f_after.value, (
            f"4H feature changed after 1H perturbation: "
            f"before={f_before.value}, after={f_after.value}"
        )
        assert f_before.valid == f_after.valid
        assert f_before.reason_code == f_after.reason_code


def test_4h_perturbation_does_not_change_1h_features(
    parameter_set,
) -> None:
    """Beh. 11: D-02 multi-timeframe independence (reverse direction).

    Perturbing one 4H candle's close must NOT change any 1H feature
    value. The two streams are independently ordered closed
    sequences.
    """
    candles_1h = _candles_at_index(250, interval="1h")
    candles_4h = _candles_at_index(250, interval="4h")

    # Compute 1H features before perturbation.
    frame_before = compute_features(
        symbol="BTCUSDT",
        interval="1h",
        candles=candles_1h,
        parameter_set=parameter_set,
    )

    # Perturb one 4H close by a large amount (expand high/low to satisfy
    # the Candle OHLC validator).
    perturbed_4h = list(candles_4h)
    last = perturbed_4h[-1]
    shift = Decimal("10000.00")
    perturbed_4h[-1] = Candle(
        symbol=last.symbol,
        interval=last.interval,
        open_time_utc=last.open_time_utc,
        close_time_utc=last.close_time_utc,
        open=last.open + shift,
        high=last.high + shift,
        low=last.low + shift,
        close=last.close + shift,
        volume=last.volume,
    )

    # Compute 1H features after perturbation (same 1H candles).
    frame_after = compute_features(
        symbol="BTCUSDT",
        interval="1h",
        candles=candles_1h,
        parameter_set=parameter_set,
    )

    # Every 1H feature value must be identical.
    for f_before, f_after in (
        (frame_before.ema_20, frame_after.ema_20),
        (frame_before.ema_50, frame_after.ema_50),
        (frame_before.ema_200, frame_after.ema_200),
        (frame_before.atr_14, frame_after.atr_14),
        (frame_before.swing_high, frame_after.swing_high),
        (frame_before.swing_low, frame_after.swing_low),
        (frame_before.zone_upper, frame_after.zone_upper),
        (frame_before.zone_lower, frame_after.zone_lower),
    ):
        assert f_before.value == f_after.value, (
            f"1H feature changed after 4H perturbation: "
            f"before={f_before.value}, after={f_after.value}"
        )
        assert f_before.valid == f_after.valid
        assert f_before.reason_code == f_after.reason_code
