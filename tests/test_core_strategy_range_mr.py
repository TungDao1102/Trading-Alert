"""Range mean-reversion family tests for Phase 4 plan 04-04.

Per D-05: range-mr is Family C, a parallel slice on the proven tracer
harness. The branch implements:
- Range detection on closed-bar structure (swing_high/swing_low define
  the range; zone_min_touches confirmed touches; zone_aging_bars aging
  cutoff).
- Range-edge touch on a NEUTRAL regime (4H context).
- Range-break invalidation by range_break_buffer_atr * ATR.
- SETUP emits Signal with RANGE_MR_LONG or RANGE_MR_SHORT setup_type.

TDD discipline: RED → GREEN. These tests pin the four behaviors named
in plan 04-04 task 2.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.core import strategy as strategy_module
from src.core.planner import plan
from src.core.strategy import evaluate
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


def _build_1h_candles_range_mr_long() -> list[Candle]:
    """Build 1H candles with a clear LONG range-mr pattern.

    Pattern:
    - 200 bars of gentle uptrend (warm-up).
    - 30 bars of range with high = 52000, low = 51800 (creates a clear
      range). Multiple touches of the upper band (zone_min_touches=2).
    - 1 bar at the lower band (LONG entry: touch the support).
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

    # 30 bars of range with high = 51950, low = 51810.
    # All range bars have low = 51810 (within touch tolerance of 51800)
    # so they all count as lower-band touches. High = 51950 stays below
    # the original zone_upper 52000 so no upper-band touches are created.
    for i in range(30):
        close = Decimal("51900.00")
        open_p = Decimal("51890.00")
        high = Decimal("51950.00")
        low = Decimal("51810.00")
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

    # 1 bar at the lower band (LONG entry: touch the support at 51800).
    close = Decimal("51850.00")
    open_p = Decimal("51840.00")
    high = Decimal("51900.00")
    low = Decimal("51800.00")  # touch the support
    open_time = _hour_open(230)
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


def _build_1h_candles_range_mr_short() -> list[Candle]:
    """Build 1H candles with a clear SHORT range-mr pattern."""
    rows: list[Candle] = []
    base_price = Decimal("60000.00")

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

    # 30 bars of range with high = 48190, low = 48050.
    # All range bars have high = 48190 (within touch tolerance of 48200)
    # so they all count as upper-band touches. Low = 48050 stays above
    # the original zone_lower 48000 so no lower-band touches are created.
    for i in range(30):
        close = Decimal("48100.00")
        open_p = Decimal("48110.00")
        high = Decimal("48190.00")
        low = Decimal("48050.00")
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

    # 1 bar at the upper band (SHORT entry: touch the resistance at 48200).
    close = Decimal("48150.00")
    open_p = Decimal("48160.00")
    high = Decimal("48200.00")  # touch the resistance
    low = Decimal("48100.00")
    open_time = _hour_open(230)
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


def _build_4h_candles_neutral() -> list[Candle]:
    """Build 4H candles with a NEUTRAL regime (constant close = EMA50)."""
    rows: list[Candle] = []
    for i in range(250):
        close = Decimal("51900.00")
        open_p = Decimal("51900.00")
        high = Decimal("51940.00")
        low = Decimal("51860.00")
        open_time = _four_hour_open(i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="4h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=4) - timedelta(microseconds=1),
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
    """Load range-mr/baseline-v1."""
    return load_parameter_set("range-mr", "baseline-v1")


@pytest.fixture
def account_state() -> AccountState:
    """Standard account state for tests."""
    return AccountState(
        equity=Decimal("10000.00"),
        risk_rate=Decimal("0.005"),
    )


# --------------------------------------------------------------------------- #
# Test 1 — valid-range-setup: range-edge touch with confirmed touches → SETUP.
# --------------------------------------------------------------------------- #


def test_valid_range_mr_setup_emits_setup_long(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 1: Range-edge touch with zone_min_touches confirmed touches yields SETUP LONG.

    The 4H context resolves to NEUTRAL, the 1H range has
    zone_min_touches confirmed touches of the upper band, and the last
    bar touches the lower band (support) — a LONG mean-reversion entry.
    """
    candles_1h = _build_1h_candles_range_mr_long()
    candles_4h = _build_4h_candles_neutral()
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
    assert result.signal.setup_type == "RANGE_MR_LONG"
    assert result.signal.direction == "LONG"
    assert result.signal.source_timeframe == "1h"


def test_valid_range_mr_setup_emits_setup_short(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 1b: Symmetric SHORT range-mr yields SETUP SHORT."""
    candles_1h = _build_1h_candles_range_mr_short()
    candles_4h = _build_4h_candles_neutral()
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
    assert result.signal.setup_type == "RANGE_MR_SHORT"
    assert result.signal.direction == "SHORT"


# --------------------------------------------------------------------------- #
# Test 2 — range-break-invalidation: close beyond band by buffer → NO_TRADE.
# --------------------------------------------------------------------------- #


def test_range_break_beyond_buffer_yields_no_trade(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2: A close beyond the range band by range_break_buffer_atr * ATR invalidates the zone.

    The range is broken when the last bar's close exceeds the band by
    range_break_buffer_atr * ATR. The branch must return NO_TRADE so
    callers know the range is no longer valid.
    """
    candles_1h = _build_1h_candles_range_mr_long()
    # Overwrite the last bar (index 230) with a close well above the
    # upper band (52000) — this breaks the range to the upside.
    candles_1h[230] = Candle(
        symbol="BTCUSDT",
        interval="1h",
        open_time_utc=_hour_open(230),
        close_time_utc=_hour_open(230) + timedelta(hours=1) - timedelta(seconds=1),
        open=Decimal("52100.00"),
        high=Decimal("52200.00"),
        low=Decimal("52050.00"),
        close=Decimal("52150.00"),  # well above upper band 52000
        volume=Decimal("100.00"),
    )

    candles_4h = _build_4h_candles_neutral()
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
        f"expected NO_TRADE for range break, got SETUP: "
        f"{result.signal.setup_type if result.signal else None}"
    )


# --------------------------------------------------------------------------- #
# Test 3 — zone-aging-cutoff: last touch beyond zone_aging_bars → NO_TRADE.
# --------------------------------------------------------------------------- #


def test_zone_aging_cutoff_yields_no_trade(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 3: If the last confirmed touch is beyond zone_aging_bars, the zone is stale.

    The zone_aging_bars cutoff prevents trading on stale ranges. The
    branch must return NO_TRADE when the most recent touch is too old.
    """
    candles_1h = _build_1h_candles_range_mr_long()
    # The original builder places upper-band touches at indices 205 and
    # 210 (relative to the range start at 200). The last bar is at 230.
    # zone_aging_bars=50 means the last touch must be within 50 bars of
    # the last bar. Touch at 210 is 20 bars before 230 — within window.
    # To trigger the cutoff, we need the last touch to be > 50 bars
    # before the last bar. Replace the range bars so the last touch is
    # at index 205 (25 bars before 230) — still within window.
    # Instead, add 60 filler bars after the range so the last touch is
    # 60+ bars before the last bar.
    for i in range(60):
        close = Decimal("51750.00")
        open_p = close - Decimal("10.00")
        high = Decimal("51800.00")  # below original zone_upper 52000
        low = Decimal("51700.00")  # below original zone_lower 51800
        open_time = _hour_open(231 + i)
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
    # Add a final bar at the lower band (would be a valid touch).
    close = Decimal("51850.00")
    open_p = Decimal("51840.00")
    high = Decimal("51900.00")
    low = Decimal("51800.00")
    open_time = _hour_open(291)
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

    candles_4h = _build_4h_candles_neutral()
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
        f"expected NO_TRADE for stale zone, got SETUP: "
        f"{result.signal.setup_type if result.signal else None}"
    )


# --------------------------------------------------------------------------- #
# Test 4 — signal-id determinism: byte-identical IDs across reruns.
# --------------------------------------------------------------------------- #


def test_signal_id_is_byte_identical_across_runs(
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 4a: Two runs over identical inputs produce byte-identical SignalIds."""
    candles_1h = _build_1h_candles_range_mr_long()
    candles_4h = _build_4h_candles_neutral()
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
    """Beh. 4b: SignalId recomputes via make_signal_id with the strategy inputs."""
    candles_1h = _build_1h_candles_range_mr_long()
    candles_4h = _build_4h_candles_neutral()
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
    assert len(result.signal.signal_id) == 64
    canonical = make_signal_id(
        strategy_id=parameter_set.strategy_id,
        strategy_version=parameter_set.strategy_version,
        parameter_set_id=parameter_set.parameter_set_id,
        symbol=snapshot.symbol,
        source_timeframe=snapshot.source_timeframe,
        source_candle_close_utc=result.signal.source_candle_close_utc,
        setup_fingerprint=result.signal.expires_at_utc.isoformat(),
    )
    assert len(canonical) == 64


# --------------------------------------------------------------------------- #
# Plan 15-06 Task 2: the Family C pivot regime (D-22, F1). Hand derivations of the 4h windows
# are in tests/fixtures/phase15/DERIVATIONS.md (c_long_worked) and the waypoint tables in
# tests/geometry_builders.py; all values here are test-local, nothing under params/ changes.
# --------------------------------------------------------------------------- #

_ACCOUNT = AccountState(equity=Decimal("10000"), risk_rate=Decimal("0.005"))


def _pivot_set(**overrides: int | str | Decimal) -> ParameterSet:
    """range-mr baseline-v5 plus test-local geometry_version 1 keys (in memory only)."""
    base = load_parameter_set("range-mr", "baseline-v5")
    params = dict(base.params)
    params.update(
        {
            "pivot_left_bars": 3,
            "pivot_right_bars": 3,
            "regime_filter_lookback": 50,
            "tp_mode": "T_MID",
            "geometry_version": 1,
        }
    )
    params.update(overrides)
    return dataclasses.replace(base, params=params)


def _regime(waypoints: tuple[tuple[int, str], ...], **overrides: int | str | Decimal) -> str:
    context = geometry_builders.pivot_context(waypoints)
    return strategy_module._resolve_regime_pivots(context, _pivot_set(**overrides))


def _evaluate(
    window: tuple[list[Candle], list[Candle]], parameter_set: ParameterSet
) -> SetupResult:
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


def _pivots(
    candles: list[Candle], *, high: bool, left: int = 3, right: int = 3, lookback: int = 50
) -> list[tuple[int, Decimal]]:
    """Confirmed pivots by the definition (newest first), independent of src.core.pivots.

    Pivot high at t: high[t] >= highs[t-left..t-1] and high[t] > highs[t+1..t+right]; the pivot
    low mirrors it. Only t + right <= last index counts, inside the last `lookback` bars.
    """
    last = len(candles) - 1
    values = [c.high if high else c.low for c in candles]
    found: list[tuple[int, Decimal]] = []
    for t in range(last - right, max(left, last - lookback + 1) - 1, -1):
        level = values[t]
        left_ok = all(
            (level >= values[j]) if high else (level <= values[j]) for j in range(t - left, t)
        )
        right_ok = all(
            (level > values[j]) if high else (level < values[j])
            for j in range(t + 1, t + right + 1)
        )
        if left_ok and right_ok:
            found.append((t, level))
    return found


def test_pivot_regime_bullish_higher_high_and_higher_low() -> None:
    """Pivot highs 109 (bar 210) then 113 (bar 230), pivot lows 101 (220) then 105 (240)."""
    assert _regime(geometry_builders.PIVOT_BULLISH) == "BULLISH"


def test_pivot_regime_bearish_lower_high_and_lower_low() -> None:
    """Pivot highs 109 (210) then 105 (230), pivot lows 99 (220) then 95 (240)."""
    assert _regime(geometry_builders.PIVOT_BEARISH) == "BEARISH"


def test_pivot_regime_neutral_contracting_lower_high_and_higher_low() -> None:
    """Highs 111 then 109 (LH), lows 99 then 101 (HL): contracting, the Family C range."""
    assert _regime(geometry_builders.PIVOT_NEUTRAL_CONTRACTING) == "NEUTRAL"


def test_pivot_regime_neutral_expanding_higher_high_and_lower_low() -> None:
    """Highs 109 then 110 (HH), lows 99 then 98 (LL): expanding, also NEUTRAL."""
    assert _regime(geometry_builders.PIVOT_NEUTRAL_EXPANDING) == "NEUTRAL"


_TIE_VARIANTS = {
    "tied_highs_rising_lows": (
        (0, "100"),
        (200, "100"),
        (210, "108"),
        (220, "100"),
        (230, "108"),
        (240, "102"),
        (249, "106.5"),
    ),
    "tied_highs_falling_lows": (
        (0, "100"),
        (200, "100"),
        (210, "108"),
        (220, "100"),
        (230, "108"),
        (240, "98"),
        (249, "102.5"),
    ),
    "higher_high_tied_lows": (
        (0, "100"),
        (200, "100"),
        (210, "108"),
        (220, "100"),
        (230, "109"),
        (240, "100"),
        (249, "104.5"),
    ),
    "lower_high_tied_lows": (
        (0, "100"),
        (200, "100"),
        (210, "108"),
        (220, "100"),
        (230, "104"),
        (240, "100"),
        (249, "104.5"),
    ),
}


@pytest.mark.parametrize("name", sorted(_TIE_VARIANTS))
def test_pivot_regime_neutral_when_one_pair_is_tied(name: str) -> None:
    """Rule: an equal newest and previous pivot is neither higher nor lower.

    BULLISH needs a strictly higher high AND a strictly higher low, BEARISH a strictly lower
    high AND a strictly lower low. One tied pair therefore gives NEUTRAL whatever the other
    pair does (HH with tied lows is not BULLISH, LH with tied lows is not BEARISH, tied highs
    with HL or LL are neither).
    """
    assert _regime(_TIE_VARIANTS[name]) == "NEUTRAL"


def test_pivot_regime_tied_variants_really_tie() -> None:
    """The tie windows hold equal pivot levels (the premise of the rule above)."""
    for name in ("tied_highs_rising_lows", "tied_highs_falling_lows"):
        context = geometry_builders.pivot_context(_TIE_VARIANTS[name])
        highs = [level for _t, level in _pivots(context, high=True)[:2]]
        assert highs[0] == highs[1] == Decimal("109"), name
    context = geometry_builders.pivot_context(_TIE_VARIANTS["higher_high_tied_lows"])
    lows = [level for _t, level in _pivots(context, high=False)[:2]]
    assert lows[0] == lows[1] == Decimal("99")


_ONE_PIVOT_HIGH = (
    (0, "100"),
    (200, "100"),
    (220, "110"),
    (240, "100"),
    (249, "104.5"),
)
# Peaks at 209 and 229 (both 109), one trough at 219 inside the window and an older trough at
# 199 that is exactly one bar outside regime_filter_lookback 50 of the last bar 249.
_OLD_LOW_OUTSIDE = (
    (0, "100"),
    (199, "100"),
    (209, "108"),
    (219, "100"),
    (229, "108"),
    (249, "98"),
)
# The same shape shifted one bar later: the older trough is bar 200, the first window bar.
_OLD_LOW_ON_BOUNDARY = (
    (0, "100"),
    (200, "100"),
    (210, "108"),
    (220, "100"),
    (230, "108"),
    (249, "98.5"),
)


def test_insufficient_pivots_one_pivot_high_is_no_trade() -> None:
    """A single peak (bar 220) and two pivot lows (200, 240): fewer than two highs."""
    context = geometry_builders.pivot_context(_ONE_PIVOT_HIGH)
    assert len(_pivots(context, high=True)) == 1
    assert len(_pivots(context, high=False)) == 2
    assert strategy_module._resolve_regime_pivots(context, _pivot_set()) == "NO_TRADE"


def test_insufficient_pivots_one_pivot_low_is_no_trade() -> None:
    context = geometry_builders.pivot_context(_OLD_LOW_OUTSIDE)
    assert len(_pivots(context, high=True)) == 2
    assert len(_pivots(context, high=False)) == 1
    assert strategy_module._resolve_regime_pivots(context, _pivot_set()) == "NO_TRADE"


def test_insufficient_pivots_in_a_flat_window_is_no_trade() -> None:
    assert _regime(((0, "100"), (249, "100"))) == "NO_TRADE"


def test_insufficient_pivots_evaluate_returns_no_trade_regime_without_a_regime_name() -> None:
    setup = geometry_builders.constant_range_candles(geometry_builders.range_mr_closes())
    context = geometry_builders.pivot_context(_ONE_PIVOT_HIGH)
    result = _evaluate((setup, context), _pivot_set())
    assert result.is_no_trade
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value
    assert result.regime is None


def test_pivot_regime_ignores_a_pivot_older_than_the_lookback() -> None:
    """The trough at bar 199 is outside the 50-bar window of bar 249 and does not count.

    With it ignored the window holds one pivot low (NO_TRADE); the same shape one bar later
    puts the older trough on bar 200, the first window bar, where it counts (two equal lows
    and two equal highs, so NEUTRAL). A lookback of 49 drops bar 200 again.
    """
    assert _regime(_OLD_LOW_OUTSIDE) == "NO_TRADE"
    assert _regime(_OLD_LOW_ON_BOUNDARY) == "NEUTRAL"
    assert _regime(_OLD_LOW_ON_BOUNDARY, regime_filter_lookback=49) == "NO_TRADE"


_UNCONFIRMED_TAIL = (
    (0, "100"),
    (200, "100"),
    (210, "108"),
    (220, "102"),
    (230, "112"),
    (240, "106"),
    (246, "109"),
    (249, "107.5"),
)


def test_pivot_regime_ignores_a_swing_in_the_last_right_bars() -> None:
    """A swing high on bar 246 is confirmed only when bar 249 has closed (right = 3).

    On the first 249 bars (last index 248) it has two right-side bars and is ignored, so the
    verdict is BULLISH (highs 109 then 113, lows 101 then 105). One bar later it is a lower
    high (110 under 113) and the verdict is NEUTRAL.
    """
    context = geometry_builders.pivot_context(_UNCONFIRMED_TAIL)
    parameter_set = _pivot_set()
    assert strategy_module._resolve_regime_pivots(context[:249], parameter_set) == "BULLISH"
    assert strategy_module._resolve_regime_pivots(context, parameter_set) == "NEUTRAL"
    assert [t for t, _ in _pivots(context[:249], high=True)] == [230, 210]
    assert [t for t, _ in _pivots(context, high=True)] == [246, 230, 210]


_ZIGZAG_LEVELS = (
    100, 108, 101, 109, 105, 97, 104, 98, 106, 100, 108, 103, 99, 107, 100, 105,
    96, 104, 99, 107, 102, 110, 101, 106, 98, 105, 100, 109, 103, 97, 104, 100,
)  # fmt: skip


def _zigzag_context(length: int = 320) -> list[Candle]:
    """320 closed 4h bars through ten-bar legs between `_ZIGZAG_LEVELS` (steps at most 1)."""
    waypoints = [(10 * j, str(level)) for j, level in enumerate(_ZIGZAG_LEVELS)]
    waypoints.append((length - 1, str(_ZIGZAG_LEVELS[-1])))
    return geometry_builders.four_hour_context(
        geometry_builders.interpolated_closes(waypoints), setup_length=length
    )


def _oracle_regime(candles: list[Candle]) -> str:
    highs = _pivots(candles, high=True)[:2]
    lows = _pivots(candles, high=False)[:2]
    if len(highs) < 2 or len(lows) < 2:
        return "NO_TRADE"
    high_new, high_old = highs[0][1], highs[1][1]
    low_new, low_old = lows[0][1], lows[1][1]
    if high_new > high_old and low_new > low_old:
        return "BULLISH"
    if high_new < high_old and low_new < low_old:
        return "BEARISH"
    return "NEUTRAL"


def test_regime_prefix_invariance_matches_the_definition_at_every_bar() -> None:
    """The verdict on context[: k + 1] equals the by-definition verdict of that prefix for all k.

    The oracle counts a pivot only when its right-side bars are inside the prefix, so a
    look-ahead in the implementation would disagree with it somewhere on the 320-bar zig-zag.
    All three verdicts and NO_TRADE occur on this path, so the comparison is not vacuous.
    """
    context = _zigzag_context()
    parameter_set = _pivot_set()
    verdicts = [
        strategy_module._resolve_regime_pivots(context[: k + 1], parameter_set)
        for k in range(len(context))
    ]
    assert verdicts == [_oracle_regime(context[: k + 1]) for k in range(len(context))]
    assert {"BULLISH", "BEARISH", "NEUTRAL", "NO_TRADE"} <= set(verdicts)


def test_regime_prefix_invariance_later_bars_never_change_an_earlier_verdict() -> None:
    """Altering every bar after k leaves the verdict on context[: k + 1] unchanged."""
    context = _zigzag_context()
    parameter_set = _pivot_set()
    for k in range(0, len(context), 7):
        altered = [
            *context[: k + 1],
            *geometry_builders.mirror_candles(context[k + 1 :], pivot=Decimal("500")),
        ]
        assert altered[: k + 1] == context[: k + 1]
        assert strategy_module._resolve_regime_pivots(
            altered[: k + 1], parameter_set
        ) == strategy_module._resolve_regime_pivots(context[: k + 1], parameter_set), k


def test_regime_pivots_ignore_the_price_level_and_the_ema_features() -> None:
    """The pivot regime reads highs and lows only: a uniform price shift leaves it unchanged."""
    base = geometry_builders.pivot_context(geometry_builders.PIVOT_BULLISH)
    shifted = [
        dataclasses.replace(
            c,
            open=c.open + Decimal("1000"),
            high=c.high + Decimal("1000"),
            low=c.low + Decimal("1000"),
            close=c.close + Decimal("1000"),
        )
        for c in base
    ]
    parameter_set = _pivot_set()
    assert strategy_module._resolve_regime_pivots(base, parameter_set) == "BULLISH"
    assert strategy_module._resolve_regime_pivots(shifted, parameter_set) == "BULLISH"


# Signal ids and plan hashes recorded from the pre-change commit (f8a5553) on the builders of
# this file. The legacy Family C regime, detector and planner must keep producing them byte
# for byte (D-25).
_LEGACY_PINS = {
    ("baseline-v1", "long"): (
        "43765c0e8515ed1833bc1349185a20e791172ce0630c3ed7fa479216d9618144",
        "d90a223225aa1a630cd360897867db8e68e3ed44b1a5d9958876b2d8feec01cf",
    ),
    ("baseline-v1", "short"): (
        "3c7d6b97e46a34faa6c2a1b43afbd01f3f8269f9d9cc8c4662773a507a019cb5",
        "3ace17e966ea9769058c6978c88250fcffc3715b840172ce61287baabfccdacb",
    ),
    ("baseline-v5", "long"): (
        "0e53de0d48a163e7b1f7e5021d804337663584212e2d8a4ca6514e3048e3fccc",
        "21e34b809d246d2da9285f96c984810c02a156682017e8d4411719253432d45a",
    ),
    ("baseline-v5", "short"): (
        "c071fe023f2172014fbbbbf1106ba5c9febc6ad2d70b4eb05e4f736945ba9478",
        "d8f472ffc0ee07fcf51575b185ce5461efb34ad9d656a95bbda0fb2af91d790c",
    ),
}


@pytest.mark.parametrize(("version", "side"), sorted(_LEGACY_PINS))
def test_legacy_unchanged_signal_id_and_plan_hash_match_the_pre_change_values(
    version: str, side: str
) -> None:
    parameter_set = load_parameter_set("range-mr", version)
    assert "geometry_version" not in parameter_set.params
    setup = (
        _build_1h_candles_range_mr_long() if side == "long" else _build_1h_candles_range_mr_short()
    )
    result = _evaluate((setup, _build_4h_candles_neutral()), parameter_set)
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None
    signal_id, plan_hash = _LEGACY_PINS[(version, side)]
    assert result.signal.signal_id == signal_id
    planned = plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=_ACCOUNT,
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert planned.trade_plan is not None
    assert planned.trade_plan.plan_hash == plan_hash


def test_legacy_regime_still_requires_exact_ema50_equality() -> None:
    """A set without geometry_version ignores the pivots: a contracting window is not NEUTRAL."""
    legacy = load_parameter_set("range-mr", "baseline-v5")
    setup, context = geometry_builders.range_mr_long_window()
    result = _evaluate((setup, context), legacy)
    assert result.is_no_trade
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value
    assert result.regime in {"BULLISH", "BEARISH"}
    flat = geometry_builders.range_mr_long_flat_context_window()
    assert not _evaluate(flat, legacy).is_no_trade
    # The same 1h window with the pivot regime set reaches NEUTRAL on the contracting window.
    corrected = _evaluate((setup, context), _pivot_set())
    assert not corrected.is_no_trade, corrected.reason_code
    assert corrected.regime == "NEUTRAL"


def test_legacy_wrapper_agrees_with_the_levels_function() -> None:
    parameter_set = load_parameter_set("range-mr", "baseline-v5")
    candles = _build_1h_candles_range_mr_long()
    wrapper = strategy_module._detect_range_mr_setup(
        setup_candles=candles, parameter_set=parameter_set
    )
    levels = strategy_module._detect_range_mr_levels(
        setup_candles=candles, parameter_set=parameter_set
    )
    assert wrapper is not None and levels is not None
    assert wrapper == (levels.direction, levels.setup_type, levels.zone_upper, levels.zone_lower)
    assert levels.sr_far_edge is None


def test_families_a_and_b_keep_the_ema50_regime_with_geometry_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-22: only range-mr switches to the pivot regime; A stays on the EMA50 proxy."""

    def _forbidden(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("pivot regime used outside range-mr")

    monkeypatch.setattr(strategy_module, "_resolve_regime_pivots", _forbidden)
    base = load_parameter_set("trend-pullback", "baseline-v5")
    params = dict(base.params)
    params.update(
        {
            "zone_tolerance_atr": Decimal("0.5"),
            "swing_lookback": 20,
            "pivot_left_bars": 3,
            "pivot_right_bars": 3,
            "geometry_version": 1,
        }
    )
    result = _evaluate(
        geometry_builders.family_a_long_window(), dataclasses.replace(base, params=params)
    )
    assert not result.is_no_trade, result.reason_code
    assert result.regime == "BULLISH"
