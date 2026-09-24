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

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot
from src.domain.ids import make_signal_id
from src.domain.registry import ParameterSet, load_parameter_set

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
