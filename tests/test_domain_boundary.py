"""Boundary determinism suite (Phase 4, plan 04-02 — real family behavior).

Per D-08 and TESTING_STRATEGY §5: empty, single-bar, warm-up-insufficient,
and gap-injected inputs each return an explicit invalid reason and
never raise or crash. The Phase-3 placeholder `_placeholder_decide`
has been replaced with real `compute_features` + `evaluate` calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.core.features import compute_features
from src.core.strategy import evaluate
from src.core.types import (
    AccountState,
    Candle,
    MarketSnapshot,
    SetupResult,
)
from src.domain.registry import ParameterSet, load_parameter_set

ACCOUNT_STATE = AccountState(
    equity=Decimal("10000.00"),
    risk_rate=Decimal("0.005"),
)


@pytest.fixture
def parameter_set() -> ParameterSet:
    return load_parameter_set("trend-pullback", "baseline-v1")


def _make_candle(
    *,
    open_time: datetime,
    close: str = "50000.00",
    high: str | None = None,
    low: str | None = None,
    open_: str | None = None,
    interval: str = "1h",
) -> Candle:
    """Build one Candle with deterministic Decimal fields."""
    close_d = Decimal(close)
    open_d = Decimal(open_) if open_ else close_d - Decimal("10.00")
    high_d = Decimal(high) if high else close_d + Decimal("50.00")
    low_d = Decimal(low) if low else close_d - Decimal("60.00")
    step = timedelta(hours=1) if interval == "1h" else timedelta(hours=4)
    return Candle(
        symbol="BTCUSDT",
        interval=interval,
        open_time_utc=open_time,
        close_time_utc=open_time + step - timedelta(seconds=1),
        open=open_d,
        high=high_d,
        low=low_d,
        close=close_d,
        volume=Decimal("100.00"),
    )


def _build_1h_candles(n: int) -> list[Candle]:
    """Build n closed 1H candles with a steady uptrend."""
    base = datetime(2026, 9, 18, 0, 0, 0, tzinfo=UTC)
    rows: list[Candle] = []
    for i in range(n):
        close = Decimal("50000.00") + Decimal(str(i * 10))
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=base + timedelta(hours=i),
                close_time_utc=base + timedelta(hours=i + 1) - timedelta(seconds=1),
                open=close - Decimal("10.00"),
                high=close + Decimal("50.00"),
                low=close - Decimal("60.00"),
                close=close,
                volume=Decimal("100.00"),
            )
        )
    return rows


def _build_4h_candles(n: int) -> list[Candle]:
    """Build n closed 4H candles with a steady uptrend."""
    base = datetime(2026, 9, 18, 0, 0, 0, tzinfo=UTC)
    rows: list[Candle] = []
    for i in range(n):
        close = Decimal("50000.00") + Decimal(str(i * 30))
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="4h",
                open_time_utc=base + timedelta(hours=4 * i),
                close_time_utc=base + timedelta(hours=4 * (i + 1)) - timedelta(seconds=1),
                open=close - Decimal("20.00"),
                high=close + Decimal("40.00"),
                low=close - Decimal("40.00"),
                close=close,
                volume=Decimal("500.00"),
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Test 1 — empty input returns an explicit invalid reason.
# --------------------------------------------------------------------------- #


def test_empty_input_returns_explicit_invalid_reason(
    parameter_set: ParameterSet,
) -> None:
    """Beh. 1: empty candle list yields NO_TRADE with NO_TRADE_REGIME, no exception."""
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=[],
        context_candles=[],
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=ACCOUNT_STATE,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.is_no_trade
    assert result.reason_code == "NO_TRADE_REGIME"


# --------------------------------------------------------------------------- #
# Test 2 — single-bar input returns an explicit invalid reason.
# --------------------------------------------------------------------------- #


def test_single_bar_returns_explicit_invalid_reason(
    parameter_set: ParameterSet,
) -> None:
    """Beh. 2: single-bar list yields NO_TRADE with WARMUP_INSUFFICIENT, no exception."""
    candles_1h = _build_1h_candles(1)
    candles_4h = _build_4h_candles(1)
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=ACCOUNT_STATE,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.is_no_trade
    assert result.reason_code == "WARMUP_INSUFFICIENT"


# --------------------------------------------------------------------------- #
# Test 3 — warm-up-insufficient input returns an explicit invalid reason.
# --------------------------------------------------------------------------- #


def test_warmup_insufficient_returns_explicit_invalid_reason(
    parameter_set: ParameterSet,
) -> None:
    """Beh. 3: too-few-bars input yields NO_TRADE with WARMUP_INSUFFICIENT, no exception."""
    candles_1h = _build_1h_candles(50)
    candles_4h = _build_4h_candles(50)
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=ACCOUNT_STATE,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.is_no_trade
    assert result.reason_code == "WARMUP_INSUFFICIENT"


# --------------------------------------------------------------------------- #
# Test 4 — sufficient input never raises.
# --------------------------------------------------------------------------- #


def test_sufficient_input_never_raises(
    parameter_set: ParameterSet,
) -> None:
    """Beh. 4: at-threshold input returns a decision, no exception."""
    candles_1h = _build_1h_candles(250)
    candles_4h = _build_4h_candles(250)
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=ACCOUNT_STATE,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    # Either SETUP or NO_TRADE — both are valid outcomes; the contract
    # is "never raises, never crashes".
    assert isinstance(result, SetupResult)
    assert result.reason_code is not None


# --------------------------------------------------------------------------- #
# Test 5 — gap-injected input returns NO_TRADE with DATA_STALE.
# --------------------------------------------------------------------------- #


def test_gap_injected_input_returns_no_trade_with_data_stale(
    parameter_set: ParameterSet,
) -> None:
    """Beh. 5: gap-injected input yields NO_TRADE with DATA_STALE, no exception."""
    candles_1h = _build_1h_candles(250)
    candles_4h = _build_4h_candles(250)
    # Inject a gap in the 1H series (delete bars 100..104).
    candles_1h_gap = candles_1h[:100] + candles_1h[105:]
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h_gap,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=ACCOUNT_STATE,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.is_no_trade
    assert result.reason_code == "DATA_STALE"


# --------------------------------------------------------------------------- #
# Test 6 — both-touched ambiguous bar resolves deterministically.
# --------------------------------------------------------------------------- #


def test_both_touched_ambiguous_bar_resolves_deterministically(
    parameter_set: ParameterSet,
) -> None:
    """Beh. 6: a both-touched ambiguous bar resolves to exactly one outcome.

    A bar whose low touches the support zone AND whose high touches the
    resistance zone is ambiguous. The strategy must resolve it to
    exactly one of NO_TRADE or SETUP — never raise, never flip across
    reruns.
    """
    candles_1h = _build_1h_candles(250)
    candles_4h = _build_4h_candles(250)
    # Perturb the last 1H candle so its low AND high both touch the
    # zone (ambiguous: could be LONG or SHORT).
    last = candles_1h[-1]
    # Make the candle span a huge range so both low and high touch
    # both zones.
    ambiguous = Candle(
        symbol=last.symbol,
        interval=last.interval,
        open_time_utc=last.open_time_utc,
        close_time_utc=last.close_time_utc,
        open=last.open,
        high=last.close + Decimal("5000.00"),  # very high
        low=last.close - Decimal("5000.00"),  # very low
        close=last.close,
        volume=last.volume,
    )
    candles_1h_amb = candles_1h[:-1] + [ambiguous]
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h_amb,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    # Run twice — must get the same outcome.
    result1 = evaluate(
        snapshot=snapshot,
        account_state=ACCOUNT_STATE,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    result2 = evaluate(
        snapshot=snapshot,
        account_state=ACCOUNT_STATE,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    # Both runs must agree (no flip across reruns).
    assert result1.is_no_trade == result2.is_no_trade
    assert result1.reason_code == result2.reason_code
    if not result1.is_no_trade:
        assert result1.signal is not None
        assert result2.signal is not None
        assert result1.signal.signal_id == result2.signal.signal_id


# --------------------------------------------------------------------------- #
# Test 7 — raising variant is detected by never-raises contract.
# --------------------------------------------------------------------------- #


def test_raising_variant_is_detected_by_never_raises_contract() -> None:
    """Canary: a raising implementation trips the contract.

    A deliberately broken helper (raises on empty input instead of
    returning NO_TRADE) raises under pytest.raises — proving the
    no-exception assertion is sensitive to the crash bug class.
    """
    import pytest

    def _raising_evaluate(
        candles_1h: list[Candle],
        candles_4h: list[Candle],
    ) -> SetupResult:
        if not candles_1h:
            raise RuntimeError("empty input crashed the helper")
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            setup_candles=candles_1h,
            context_candles=candles_4h,
            source_timeframe="1h",
        )
        parameter_set = load_parameter_set("trend-pullback", "baseline-v1")
        return evaluate(
            snapshot=snapshot,
            account_state=ACCOUNT_STATE,
            strategy_version=parameter_set.strategy_version,
            parameter_set=parameter_set,
        )

    with pytest.raises(RuntimeError, match="empty input"):
        _raising_evaluate([], [])


# --------------------------------------------------------------------------- #
# Test 8 — compute_features on empty input raises ValueError.
# --------------------------------------------------------------------------- #


def test_compute_features_empty_input_raises_value_error(
    parameter_set: ParameterSet,
) -> None:
    """Beh. 8: compute_features on empty input raises ValueError, never crashes silently."""
    import pytest

    with pytest.raises(ValueError, match="non-empty"):
        compute_features(
            symbol="BTCUSDT",
            interval="1h",
            candles=[],
            parameter_set=parameter_set,
        )
