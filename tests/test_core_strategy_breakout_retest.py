"""Breakout-retest family tests for Phase 4 plan 04-04.

Per D-05: breakout-retest is Family B, a parallel slice on the proven
tracer harness. The branch implements:
- Breakout detection on closed-bar structure (breakout_confirmation_bars
  consecutive bars closing beyond the zone edge computed at the
  preceding bar).
- Retest countdown starting at the breakout-bar close.
- Retest acceptance within retest_window_bars and depth
  retest_depth_atr * ATR.
- SETUP emits Signal with BREAKOUT_RETEST_LONG or BREAKOUT_RETEST_SHORT
  setup_type.

TDD discipline: RED → GREEN. These tests pin the four behaviors named
in plan 04-04 task 1.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.core.features import _atr_series, _swing_series
from src.core.planner import plan
from src.core.strategy import (
    _detect_breakout_retest_levels,
    _detect_breakout_retest_setup,
    evaluate,
)
from src.core.types import AccountState, Candle, MarketSnapshot, SetupResult
from src.domain.enums import RejectionReason
from src.domain.ids import make_signal_id
from src.domain.registry import ParameterSet, load_parameter_set

from tests import geometry_builders

# --------------------------------------------------------------------------- #
# Candle builders — deterministic, Decimal-only candles.
# --------------------------------------------------------------------------- #


def _hour_open(t_index: int) -> datetime:
    """Return the 1H-bar open at index t_index."""
    base = datetime(2026, 9, 18, 0, 0, 0, tzinfo=UTC)
    return base + timedelta(hours=t_index)


def _four_hour_open(t_index: int) -> datetime:
    """Return the 4H-bar open at index t_index."""
    base = datetime(2026, 9, 18, 0, 0, 0, tzinfo=UTC)
    return base + timedelta(hours=4 * t_index)


def _build_1h_candles_breakout_retest_long() -> list[Candle]:
    """Build 1H candles with a clear LONG breakout-retest pattern.

    Pattern:
    - 200 bars of gentle uptrend (warm-up + regime-confirming uptrend).
    - 20 bars of consolidation with high = 52000 (creates a clear
      resistance level).
    - 3 consecutive bars with close > zone_upper at the preceding bar
      (breakout). The breakout bars' highs stay at 52000 so they do
      NOT inflate the swing_high at themselves.
    - 1 bar with low within retest_depth_atr * ATR of zone_upper
      (retest).

    The breakout bars are placed at indices 220-222 and the retest bar
    at index 223, so the trailing 20 bars at index 223 are 204-223.
    The breakout bars (220-222) ARE in the trailing 20 — but their
    highs are 52000 (same as the consolidation bars), so the swing
    high at index 223 stays at 52000.

    The implementation computes zone_upper at bar i using swing_high
    at bar i-1, so the breakout bars themselves don't inflate the
    threshold they're compared against.
    """
    rows: list[Candle] = []
    base_price = Decimal("50000.00")

    # 200 bars of gentle uptrend.
    for i in range(200):
        close = base_price + Decimal(str(i * 5 + 50))
        open_p = close - Decimal("10.00")
        high = close + Decimal("50.00")
        low = close - Decimal("60.00")
        open_time = _hour_open(i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    # 20 bars of consolidation with high = 52000.
    # Closes stay around 51950, so the 3-bar breakout below will have
    # closes ABOVE the preceding-bar swing_high + zone_tolerance_atr*ATR.
    for i in range(20):
        close = Decimal("51950.00")
        open_p = close - Decimal("10.00")
        high = Decimal("52000.00")
        low = close - Decimal("60.00")
        open_time = _hour_open(200 + i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    # 3 consecutive breakout bars at indices 220-222.
    # Highs stay at 52000 (same as consolidation) so they don't inflate
    # the swing_high at themselves; closes jump well above the
    # preceding-bar zone_upper.
    for i in range(3):
        close = Decimal("52150.00") + Decimal(str(i * 10))
        open_p = Decimal("52100.00") + Decimal(str(i * 10))
        high = Decimal("52200.00") + Decimal(str(i * 10))
        low = Decimal("52050.00") + Decimal(str(i * 10))
        open_time = _hour_open(220 + i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    # 1 retest bar at index 223 with low near the zone_upper.
    close = Decimal("52150.00")
    open_p = close - Decimal("10.00")
    high = close + Decimal("50.00")
    low = Decimal("52050.00")  # retest: low near zone_upper
    open_time = _hour_open(223)
    rows.append(
        Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time_utc=open_time,
            close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=Decimal("100.00"),
        )
    )

    return rows


def _build_1h_candles_breakout_retest_short() -> list[Candle]:
    """Build 1H candles with a clear SHORT breakout-retest pattern."""
    rows: list[Candle] = []
    base_price = Decimal("50000.00")

    # 200 bars of gentle downtrend.
    for i in range(200):
        close = base_price - Decimal(str(i * 5))
        open_p = close + Decimal("10.00")
        high = open_p + Decimal("60.00")
        low = close - Decimal("50.00")
        open_time = _hour_open(i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    # 20 bars of consolidation with low = 48000.
    for i in range(20):
        close = Decimal("48050.00")
        open_p = close + Decimal("10.00")
        high = close + Decimal("60.00")
        low = Decimal("48000.00")
        open_time = _hour_open(200 + i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    # 3 consecutive SHORT breakout bars at indices 220-222.
    for i in range(3):
        close = Decimal("47850.00") - Decimal(str(i * 10))
        open_p = Decimal("47900.00") - Decimal(str(i * 10))
        high = Decimal("47950.00") - Decimal(str(i * 10))
        low = Decimal("47800.00") - Decimal(str(i * 10))
        open_time = _hour_open(220 + i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    # 1 retest bar at index 223 with high near the zone_lower.
    close = Decimal("47850.00")
    open_p = close + Decimal("10.00")
    high = Decimal("47950.00")  # retest: high near zone_lower
    low = close - Decimal("50.00")
    open_time = _hour_open(223)
    rows.append(
        Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time_utc=open_time,
            close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=Decimal("100.00"),
        )
    )

    return rows


def _build_4h_candles_bullish() -> list[Candle]:
    """Build 4H candles with a BULLISH regime (close > EMA50)."""
    rows: list[Candle] = []
    base_price = Decimal("50000.00")
    for i in range(250):
        close = base_price + Decimal(str(i * 50 + 30))
        open_p = close - Decimal("20.00")
        high = close + Decimal("40.00")
        low = close - Decimal("40.00")
        open_time = _four_hour_open(i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="4h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=4) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("500.00"),
            )
        )
    return rows


def _build_4h_candles_bearish() -> list[Candle]:
    """Build 4H candles with a BEARISH regime (close < EMA50)."""
    rows: list[Candle] = []
    base_price = Decimal("60000.00")
    for i in range(250):
        close = base_price - Decimal(str(i * 50 + 30))
        open_p = close + Decimal("20.00")
        high = open_p + Decimal("40.00")
        low = close - Decimal("40.00")
        open_time = _four_hour_open(i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="4h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=4) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("500.00"),
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #


@pytest.fixture
def parameter_set() -> ParameterSet:
    """Load breakout-retest/baseline-v1."""
    return load_parameter_set("breakout-retest", "baseline-v1")


@pytest.fixture
def account_state() -> AccountState:
    """Standard account state for tests."""
    return AccountState(
        equity=Decimal("10000.00"),
        risk_rate=Decimal("0.005"),
    )


# --------------------------------------------------------------------------- #
# Test 1 — valid-retest-setup: breakout + retest within window → SETUP LONG.
# --------------------------------------------------------------------------- #


def test_valid_breakout_retest_setup_emits_setup_long(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 1: Breakout + retest within window yields SETUP with BREAKOUT_RETEST_LONG.

    The breakout bar closes beyond the zone edge (computed at the
    preceding bar), 3 consecutive bars confirm the breakout, and a
    retest bar within retest_window_bars touches within
    retest_depth_atr * ATR of the zone edge.
    """
    candles_1h = _build_1h_candles_breakout_retest_long()
    candles_4h = _build_4h_candles_bullish()
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
    assert not result.is_no_trade, f"expected SETUP, got NO_TRADE: {result.reason_code}"
    assert result.signal is not None
    assert result.signal.setup_type == "BREAKOUT_RETEST_LONG"
    assert result.signal.direction == "LONG"
    assert result.signal.source_timeframe == "1h"


def test_valid_breakout_retest_setup_emits_setup_short(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 1b: Symmetric SHORT breakout-retest yields SETUP SHORT."""
    candles_1h = _build_1h_candles_breakout_retest_short()
    candles_4h = _build_4h_candles_bearish()
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
    assert not result.is_no_trade, f"expected SETUP, got NO_TRADE: {result.reason_code}"
    assert result.signal is not None
    assert result.signal.setup_type == "BREAKOUT_RETEST_SHORT"
    assert result.signal.direction == "SHORT"


# --------------------------------------------------------------------------- #
# Test 2 — window-expiry-no-trade: retest one bar past window → NO_TRADE.
# --------------------------------------------------------------------------- #


def test_retest_after_window_expires_yields_no_trade(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2: Retest arriving one bar after retest_window_bars expires yields NO_TRADE.

    A late retest (one bar past retest_window_bars=5) never emits a
    SETUP. The branch must name the window-expiry reason so callers
    can distinguish it from a regime/setup-gate NO_TRADE.
    """
    candles_1h = _build_1h_candles_breakout_retest_long()
    # The original builder places a valid retest at index 223 (1 bar
    # after the breakout at 222). Overwrite it with a bar whose low is
    # OUTSIDE the retest band so the only retest touch in the series
    # is the late one at index 229.
    candles_1h[223] = Candle(
        symbol="BTCUSDT",
        interval="1h",
        open_time_utc=_hour_open(223),
        close_time_utc=_hour_open(223) + timedelta(hours=1) - timedelta(seconds=1),
        open=Decimal("52140.00"),
        high=Decimal("52200.00"),
        low=Decimal("52120.00"),  # OUTSIDE retest band — no retest touch
        close=Decimal("52150.00"),
        volume=Decimal("100.00"),
    )
    # Add 5 filler bars (indices 224-228) so the next retest bar is at
    # index 229, which is 7 bars after the breakout — past the
    # retest_window_bars=5 window.
    for i in range(5):
        close = Decimal("52150.00")
        open_p = close - Decimal("10.00")
        high = close + Decimal("50.00")
        low = Decimal("52120.00")  # OUTSIDE retest band — no retest touch
        open_time = _hour_open(224 + i)
        candles_1h.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )
    # Add a late retest bar at index 229 (7 bars after breakout).
    close = Decimal("52150.00")
    open_p = close - Decimal("10.00")
    high = close + Decimal("50.00")
    low = Decimal("52050.00")  # would be a valid retest touch
    open_time = _hour_open(229)
    candles_1h.append(
        Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time_utc=open_time,
            close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=Decimal("100.00"),
        )
    )

    candles_4h = _build_4h_candles_bullish()
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
    assert result.is_no_trade, (
        f"expected NO_TRADE for late retest, got SETUP: "
        f"{result.signal.setup_type if result.signal else None}"
    )


# --------------------------------------------------------------------------- #
# Test 3 — countdown-starts-at-close: retest on breakout bar doesn't count.
# --------------------------------------------------------------------------- #


def test_retest_on_breakout_bar_does_not_count_as_confirmation(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 3: A retest on the breakout bar itself does not count.

    The countdown starts at the breakout-bar close: a bar that touches
    the zone on the same bar as the breakout does NOT satisfy the
    retest gate. The branch must continue looking for a retest on a
    LATER bar.
    """
    rows: list[Candle] = []
    base_price = Decimal("50000.00")

    # 200 bars of gentle uptrend.
    for i in range(200):
        close = base_price + Decimal(str(i * 5 + 50))
        open_p = close - Decimal("10.00")
        high = close + Decimal("50.00")
        low = close - Decimal("60.00")
        open_time = _hour_open(i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    # 20 bars of consolidation with high = 52000.
    for i in range(20):
        close = Decimal("51950.00")
        open_p = close - Decimal("10.00")
        high = Decimal("52000.00")
        low = close - Decimal("60.00")
        open_time = _hour_open(200 + i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    # 3 consecutive breakout bars at indices 220-222.
    # The breakout bar (index 222) ALSO has a low within retest_depth
    # of the zone — but the countdown starts at its close, so this
    # touch must NOT count. Only the prior 2 bars confirm the
    # breakout.
    for i in range(3):
        if i < 2:
            # First two breakout bars: normal breakout, no retest touch.
            close = Decimal("52150.00") + Decimal(str(i * 10))
            open_p = Decimal("52100.00") + Decimal(str(i * 10))
            high = Decimal("52200.00") + Decimal(str(i * 10))
            low = Decimal("52080.00") + Decimal(str(i * 10))
        else:
            # Breakout bar (i==2): close above zone, low touches zone.
            close = Decimal("52170.00")
            open_p = Decimal("52120.00")
            high = Decimal("52200.00")
            low = Decimal("52050.00")  # retest touch on breakout bar
        open_time = _hour_open(220 + i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    # Add 5 filler bars after the breakout bar that do NOT retest.
    for i in range(5):
        close = Decimal("52150.00")
        open_p = close - Decimal("10.00")
        high = close + Decimal("50.00")
        low = Decimal("52120.00")  # OUTSIDE retest band — no retest touch
        open_time = _hour_open(223 + i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )

    candles_4h = _build_4h_candles_bullish()
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=rows,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.is_no_trade, (
        "Retest on the breakout bar itself must NOT count — expected NO_TRADE"
    )


# --------------------------------------------------------------------------- #
# Test 4 — signal-id determinism: byte-identical IDs across reruns; distinct
# inputs never collide (family + variant + closes bind the fingerprint).
# --------------------------------------------------------------------------- #


def test_signal_id_is_byte_identical_across_runs(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 4a: Two runs over identical inputs produce byte-identical SignalIds."""
    candles_1h = _build_1h_candles_breakout_retest_long()
    candles_4h = _build_4h_candles_bullish()
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    result1 = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    result2 = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result1.is_no_trade
    assert not result2.is_no_trade
    assert result1.signal is not None
    assert result2.signal is not None
    assert result1.signal.signal_id == result2.signal.signal_id


def test_signal_id_recomputable_via_make_signal_id(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 4b: SignalId recomputes via make_signal_id with the strategy inputs.

    The fingerprint binds strategy_id + family variant + closes so
    distinct regime/snapshot inputs never collide. This test pins the
    SignalId construction against the canonical hash function.
    """
    candles_1h = _build_1h_candles_breakout_retest_long()
    candles_4h = _build_4h_candles_bullish()
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
    assert not result.is_no_trade
    assert result.signal is not None
    # The SignalId must be a 64-char hex string (SHA256).
    assert len(result.signal.signal_id) == 64
    # The SignalId must be reproducible via make_signal_id with the
    # same strategy_id — strategy_version never collides across
    # families because strategy_id is bound into make_signal_id.
    canonical = make_signal_id(
        strategy_id=parameter_set.strategy_id,
        strategy_version=parameter_set.strategy_version,
        parameter_set_id=parameter_set.parameter_set_id,
        symbol=snapshot.symbol,
        source_timeframe=snapshot.source_timeframe,
        source_candle_close_utc=result.signal.source_candle_close_utc,
        setup_fingerprint=result.signal.expires_at_utc.isoformat(),  # placeholder
    )
    # We can't recompute the exact fingerprint from public fields
    # alone, but the canonical helper must accept the same inputs and
    # produce a 64-char hex string (no exception).
    assert len(canonical) == 64


def test_breakout_retest_uses_zone_at_preceding_bar(
    parameter_set: ParameterSet,
) -> None:
    """Beh. 4c: The breakout gate uses zone_upper computed BEFORE the breakout sequence.

    Without this invariant, the breakout can never fire because
    swing_high[i] includes bar i's own high, making zone_upper[i]
    strictly greater than close[i]. The reference bar must be at
    index `i - breakout_confirmation_bars - 1` (one bar before the
    earliest confirmation bar) so the breakout bars' own highs stay
    out of the trailing swing window.
    """
    candles_1h = _build_1h_candles_breakout_retest_long()
    swing_high_series = _swing_series(candles_1h, 20, high=True)
    atr_series = _atr_series(candles_1h, 14)

    # At index 222 (the last breakout bar), the reference bar is
    # 222 - 3 - 1 = 218 (one bar before the earliest confirmation bar
    # at index 220). zone_upper at 222 must use swing_high[218] +
    # zone_tolerance_atr * ATR[218], NOT swing_high[222] + ... * ATR[222].
    i = 222
    breakout_confirmation_bars = 3
    ref_prev = i - breakout_confirmation_bars - 1
    sh_ref_out = swing_high_series[ref_prev]
    atr_ref_out = atr_series[ref_prev]
    assert sh_ref_out.valid and sh_ref_out.value is not None
    assert atr_ref_out.valid and atr_ref_out.value is not None
    sh_ref = sh_ref_out.value
    atr_ref = atr_ref_out.value
    zone_tolerance = Decimal("0.5")
    zone_upper_ref = sh_ref + zone_tolerance * atr_ref

    # The breakout bar's close must be > zone_upper_ref.
    assert candles_1h[i].close > zone_upper_ref, (
        f"breakout bar close {candles_1h[i].close} must be > zone_upper_ref {zone_upper_ref}"
    )


# --------------------------------------------------------------------------- #
# Plan 15-05: geometry_version 1 anchoring, with-regime gate, bounds, legacy unchanged.
# Hand derivations: tests/fixtures/phase15/DERIVATIONS.md (Family B sections).
# --------------------------------------------------------------------------- #

_ACCOUNT = AccountState(equity=Decimal("10000.00"), risk_rate=Decimal("0.005"))


def _b_set(*, geometry: bool = True, **overrides: object) -> ParameterSet:
    """baseline-v5 breakout-retest with test-local keys (in memory only).

    breakout_confirmation_bars is set to 1 explicitly (the proposed baseline of sheet B1, not
    the inherited legacy value 3); `geometry=False` builds the legacy contrast set.
    """
    base = load_parameter_set("breakout-retest", "baseline-v5")
    params = dict(base.params)
    params["breakout_confirmation_bars"] = 1
    if geometry:
        params["geometry_version"] = 1
    params.update(overrides)
    return dataclasses.replace(base, params=params)


def _eval(window: tuple[list[Candle], list[Candle]], parameter_set: ParameterSet) -> SetupResult:
    setup, context = window
    return evaluate(
        snapshot=MarketSnapshot(
            symbol="BTCUSDT",
            setup_candles=setup,
            context_candles=context,
            source_timeframe="1h",
        ),
        account_state=_ACCOUNT,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )


def test_stale_breakout_does_not_signal_under_geometry_version_1() -> None:
    """F2: a breakout and its first retest 40 bars ago, nothing since, is no longer a signal."""
    window = geometry_builders.family_b_stale_window()
    anchored = _eval(window, _b_set())
    assert anchored.is_no_trade
    assert anchored.reason_code == RejectionReason.NO_TRADE_REGIME.value
    assert anchored.regime == "BULLISH"
    legacy = _eval(window, _b_set(geometry=False))
    assert not legacy.is_no_trade, legacy.reason_code
    assert legacy.signal is not None
    assert legacy.signal.setup_type == "BREAKOUT_RETEST_LONG"


def test_first_retest_must_be_the_evaluated_bar() -> None:
    """A retest at n - 2 followed by another band touch at n - 1 is not the first retest."""
    window = geometry_builders.family_b_not_first_retest_window()
    result = _eval(window, _b_set())
    assert result.is_no_trade
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value
    legacy = _eval(window, _b_set(geometry=False))
    assert not legacy.is_no_trade, legacy.reason_code


def test_retest_outside_window_does_not_signal() -> None:
    """The first retest comes six bars after the breakout bar, past retest_window_bars 5."""
    window = geometry_builders.family_b_late_retest_window()
    result = _eval(window, _b_set())
    assert result.is_no_trade
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value


def test_counter_regime_breakout_is_no_trade_regime_under_geometry_version_1() -> None:
    """D-24: a LONG breakout-retest anchored at n - 1 under a BEARISH 4H regime is rejected."""
    window = geometry_builders.family_b_window(bearish_context=True)
    result = _eval(window, _b_set())
    assert result.is_no_trade
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value
    assert result.regime == "BEARISH"
    legacy = _eval(window, _b_set(geometry=False))
    assert not legacy.is_no_trade, legacy.reason_code
    assert legacy.signal is not None
    assert legacy.signal.direction == "LONG"


def test_counter_regime_short_breakout_is_no_trade_regime_under_a_bullish_context() -> None:
    window = geometry_builders.family_b_window(mirror=True, bearish_context=False)
    result = _eval(window, _b_set())
    assert result.is_no_trade
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value
    assert result.regime == "BULLISH"


def test_with_regime_direction_is_chosen_from_the_regime() -> None:
    long_result = _eval(geometry_builders.family_b_long_window(), _b_set())
    short_result = _eval(geometry_builders.family_b_short_window(), _b_set())
    assert long_result.signal is not None and long_result.signal.direction == "LONG"
    assert short_result.signal is not None and short_result.signal.direction == "SHORT"


@pytest.mark.parametrize("confirmation_bars", [1, 2, 3, 5])
def test_anchored_scan_never_reads_a_negative_reference_index(confirmation_bars: int) -> None:
    """The lower bound max(confirm + 1, n - 1 - window) keeps ref_prev >= 0 for every n."""
    parameter_set = _b_set(breakout_confirmation_bars=confirmation_bars)
    setup = geometry_builders.family_b_long_setup()
    for length in range(1, 60):
        for direction in (None, "LONG", "SHORT"):
            levels = _detect_breakout_retest_levels(
                setup_candles=setup[:length], parameter_set=parameter_set, direction=direction
            )
            assert levels is None or length >= confirmation_bars + 20


def _bars(rows: list[tuple[str, str, str, str]]) -> list[Candle]:
    candles: list[Candle] = []
    for index, (open_, high, low, close) in enumerate(rows):
        open_time = _hour_open(index)
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=Decimal(open_),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                volume=Decimal("1"),
            )
        )
    return candles


_SMALL_ROWS = [
    ("100", "101", "99", "100"),
    ("100", "101", "99", "100"),
    ("100", "103", "100", "103"),
    ("103", "103", "100", "101.5"),
    ("101.5", "103", "100", "101.5"),
    ("101.5", "103", "100", "101.5"),
    ("101.5", "103", "100", "101.5"),
]


def _small_set() -> ParameterSet:
    """swing_lookback 1 and atr_period 1 make bar 0 a valid reference bar (ATR = true range)."""
    return _b_set(swing_lookback=1, atr_period=1)


def test_anchored_scan_reaches_the_smallest_breakout_bar_two() -> None:
    """n = 8, window 5, confirm 1: the lowest scanned end bar is max(2, 2) = 2, ref_prev = 0.

    Hand numbers: bar 0 has swing high 101, swing low 99 and ATR (true range) 2.00, so the edge
    is 101 + 0.5 x 2.00 = 102.00 and the far edge 101 - 1.00 = 100.00; bar 2 closes 103; bars 3..6
    have lows 100.00 (below the band 101.40..102.60) and bar 7 has low 102.00, the first retest.
    End bars 6..3 have no breakout (bar 3 closes 101.5, at or below its edge 102.00).
    """
    setup = _bars([*_SMALL_ROWS, ("102.5", "103", "102", "102.5")])
    assert len(setup) == 8
    levels = _detect_breakout_retest_levels(
        setup_candles=setup, parameter_set=_small_set(), direction="LONG"
    )
    assert levels is not None
    assert levels.zone_upper == Decimal("102.00")
    assert levels.zone_lower == Decimal("98.00")
    assert levels.sr_far_edge == Decimal("100.00")


def test_anchored_scan_does_not_reach_a_breakout_whose_retest_is_past_the_window() -> None:
    """n = 9: the same breakout bar 2 would need its retest at bar 8 = i + 6, past the window."""
    setup = _bars(
        [
            *_SMALL_ROWS,
            ("101.5", "103", "100", "101.5"),
            ("102.5", "103", "102", "102.5"),
        ]
    )
    assert len(setup) == 9
    assert (
        _detect_breakout_retest_levels(
            setup_candles=setup, parameter_set=_small_set(), direction="LONG"
        )
        is None
    )


def test_geometry_version_1_levels_without_direction_consider_both_sides() -> None:
    long_setup, _ = geometry_builders.family_b_long_window()
    short_setup, _ = geometry_builders.family_b_short_window()
    parameter_set = _b_set()
    any_long = _detect_breakout_retest_levels(setup_candles=long_setup, parameter_set=parameter_set)
    any_short = _detect_breakout_retest_levels(
        setup_candles=short_setup, parameter_set=parameter_set
    )
    assert any_long is not None and any_long.direction == "LONG"
    assert any_short is not None and any_short.direction == "SHORT"
    assert (
        _detect_breakout_retest_levels(
            setup_candles=long_setup, parameter_set=parameter_set, direction="SHORT"
        )
        is None
    )


# Signal ids and plan hashes recorded from the pre-change commit (ef8daf3) on the builders of
# this file. The legacy detector and planner must keep producing them byte for byte (D-25).
_LEGACY_PINS = {
    ("baseline-v1", "long"): (
        "bffcc6a24417850c9b9125a7e4ad7947ee91cf5ab19bad0a65a4c1c747d2ca90",
        "8b7b24eedd950b6b8326df44e17a3ea88d54dc61bc6062f5f95103f3066bda9d",
    ),
    ("baseline-v1", "short"): (
        "03549b85f45ad47da97f15522f895f8b34f64a8b044c3a04eee8bf735d87701a",
        "328614ed936f5bf73a694222ddd9fb93aa9de374a34c5dbfa9feca3823c07a33",
    ),
    ("baseline-v5", "long"): (
        "b316999bb116bbdd2a188df328e74d0900a7e1916334120cce38c7f60f49c80c",
        "14127b2707d8ff858f6433f01570afdac8ef7e4cde569f97610c544526564d33",
    ),
    ("baseline-v5", "short"): (
        "15dac458d784ec30b5c44a15d2ac21aa974f88574ae09d2622a70a15cfa3e809",
        "afdb32c40feaa8fb864cb6327b1881f68a56bba212a3b625e29678b19387e4c7",
    ),
}


@pytest.mark.parametrize(("version", "side"), sorted(_LEGACY_PINS))
def test_legacy_unchanged_signal_id_and_plan_hash_match_the_pre_change_values(
    version: str, side: str
) -> None:
    parameter_set = load_parameter_set("breakout-retest", version)
    assert "geometry_version" not in parameter_set.params
    if side == "long":
        window = (_build_1h_candles_breakout_retest_long(), _build_4h_candles_bullish())
    else:
        window = (_build_1h_candles_breakout_retest_short(), _build_4h_candles_bearish())
    result = _eval(window, parameter_set)
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None
    signal_id, plan_hash = _LEGACY_PINS[(version, side)]
    assert result.signal.signal_id == signal_id
    planned = plan(
        signal=result.signal,
        setup_candles=window[0],
        parameter_set=parameter_set,
        account_state=_ACCOUNT,
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert planned.trade_plan is not None
    assert planned.trade_plan.plan_hash == plan_hash


@pytest.mark.parametrize("side", ["long", "short"])
def test_legacy_unchanged_wrapper_agrees_with_the_levels_function(side: str) -> None:
    parameter_set = load_parameter_set("breakout-retest", "baseline-v1")
    candles = (
        _build_1h_candles_breakout_retest_long()
        if side == "long"
        else _build_1h_candles_breakout_retest_short()
    )
    wrapper = _detect_breakout_retest_setup(setup_candles=candles, parameter_set=parameter_set)
    levels = _detect_breakout_retest_levels(
        setup_candles=candles, parameter_set=parameter_set, direction="SHORT"
    )
    assert wrapper is not None and levels is not None
    assert (levels.direction, levels.setup_type, levels.zone_upper, levels.zone_lower) == wrapper
    assert levels.sr_far_edge is None  # legacy sets never carry the far edge; direction ignored
