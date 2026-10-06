"""Phase 15 plan 15-04 Task 3: strategy-level Family A pivot detection through evaluate.

Windows come from tests/geometry_builders.py; the expected numbers are the hand-derived ones
in tests/fixtures/phase15/DERIVATIONS.md (sections a_long_no_opposite_pivot and p9_regression).
Parameter values are test-local: an in-memory ParameterSet built from trend-pullback
baseline-v5 plus the a_long_worked sidecar keys. Nothing under params/ is touched.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from src.core.features import compute_features
from src.core.pivots import pivot_at
from src.core.planner import plan
from src.core.strategy import _detect_setup, evaluate
from src.core.types import (
    REASON_WARMUP_INSUFFICIENT,
    AccountState,
    Candle,
    MarketSnapshot,
    PlanResult,
    SetupResult,
)
from src.domain.enums import RejectionReason
from src.domain.registry import ParameterSet, load_parameter_set

from tests import geometry_builders

_CASES_PATH = Path(__file__).parent / "fixtures" / "phase15" / "geometry_cases.json"
_ACCOUNT = AccountState(equity=Decimal("10000"), risk_rate=Decimal("0.005"))


def _number(text: str) -> int | Decimal:
    return int(text) if "." not in text else Decimal(text)


def _pivot_set() -> ParameterSet:
    """baseline-v5 plus the a_long_worked keys (geometry_version 1, 3/3 pivots)."""
    case = json.loads(_CASES_PATH.read_text(encoding="utf-8"))["cases"]["a_long_worked"]
    base = load_parameter_set("trend-pullback", "baseline-v5")
    params = dict(base.params)
    for key, text in case["params"].items():
        params[key] = _number(text)
    return dataclasses.replace(base, params=params)


def _legacy_set() -> ParameterSet:
    """The same values without geometry_version and the pivot keys (legacy path)."""
    pivot = _pivot_set()
    params = {
        key: value
        for key, value in pivot.params.items()
        if key not in {"geometry_version", "pivot_left_bars", "pivot_right_bars"}
    }
    return dataclasses.replace(pivot, params=params)


def _evaluate(
    setup: list[Candle], context: list[Candle], parameter_set: ParameterSet
) -> SetupResult:
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


def _plan(result: SetupResult, setup: list[Candle], parameter_set: ParameterSet) -> PlanResult:
    assert result.signal is not None
    return plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=_ACCOUNT,
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )


def test_no_confirmed_pivot_is_no_trade_regime_not_warmup() -> None:
    """D-03 / Pitfall 2: strictly rising lows for the whole window give no pivot low at all."""
    setup, context = geometry_builders.window_from_closes(
        geometry_builders.family_a_rising_closes(250)
    )
    result = _evaluate(setup, context, _pivot_set())
    assert result.is_no_trade
    assert result.signal is None
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value
    assert result.reason_code != REASON_WARMUP_INSUFFICIENT
    assert result.regime == "BULLISH"


def test_no_confirmed_pivot_never_falls_back_to_the_trailing_extreme() -> None:
    """The legacy path signals on the very same rising window's trailing 20-bar low; the
    pivot path must not, whatever the evaluated bar's low is."""
    setup, context = geometry_builders.window_from_closes(
        geometry_builders.family_a_rising_closes(250)
    )
    last = setup[-1]
    swing_low = min(candle.low for candle in setup[-20:])
    assert swing_low < last.low  # the trailing extreme sits 19 bars back, far below the bar
    assert pivot_at(setup, len(setup) - 1, lookback=20, left=3, right=3, high=False) is None
    assert _evaluate(setup, context, _pivot_set()).is_no_trade


def test_pivot_confirmation_timing_through_evaluate() -> None:
    """The pivot low at bar 246 is confirmed at bar 249 (t + R): a window cut one bar earlier
    has no setup from it, the full window (evaluated bar touching the zone) signals."""
    setup, context = geometry_builders.family_a_no_opposite_pivot_window()
    assert len(setup) == 250
    parameter_set = _pivot_set()

    early = _evaluate(setup[:-1], context, parameter_set)  # last bar 248 = t + 2
    assert early.is_no_trade
    assert early.reason_code == RejectionReason.NO_TRADE_REGIME.value
    assert setup[-2].low == Decimal("92.25")  # inside 90.75-92.75: it WOULD touch the zone

    confirmed = _evaluate(setup, context, parameter_set)  # last bar 249 = t + 3
    assert not confirmed.is_no_trade, confirmed.reason_code
    assert confirmed.signal is not None
    assert confirmed.signal.direction == "LONG"
    assert setup[-1].low == Decimal("92.00")  # inside the zone 90.75-92.75 around P = 91.75


def test_p9_regression_new_low_beyond_tolerance_does_not_signal() -> None:
    """P = 99.00, ATR 2.00, tolerance 1.00. The last bar low is 96.00 = P - 1.5 ATR: no signal,
    while the legacy trailing swing low (which includes that bar) still signals."""
    setup, context = geometry_builders.family_a_p9_beyond_tolerance_window()
    assert setup[-1].low == Decimal("96.00")
    assert pivot_at(setup, len(setup) - 1, lookback=20, left=3, right=3, high=False) == Decimal(
        "99.00"
    )

    result = _evaluate(setup, context, _pivot_set())
    assert result.is_no_trade
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value
    assert result.regime == "BULLISH"

    legacy = _evaluate(setup, context, _legacy_set())
    assert not legacy.is_no_trade, legacy.reason_code  # the defect this phase removes


def test_p9_new_low_inside_tolerance_signals_and_the_stop_is_below_the_bar_low() -> None:
    """The last bar low is 98.20 = P - 0.4 ATR: a new low, but inside 98.00-100.00, so it still
    signals (F4 nuance) and the plan's stop 97.40 lies below that bar's low."""
    setup, context = geometry_builders.family_a_p9_inside_tolerance_window()
    assert setup[-1].low == Decimal("98.20")
    parameter_set = _pivot_set()

    result = _evaluate(setup, context, parameter_set)
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None
    assert result.signal.direction == "LONG"

    planned = _plan(result, setup, parameter_set)
    assert not planned.is_no_trade, planned.reason_code
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.stop_loss_price == Decimal("97.40")
    assert trade_plan.stop_loss_price < setup[-1].low
    assert trade_plan.entry_min_price == Decimal("97.80")
    assert trade_plan.entry_max_price == Decimal("100.20")
    targets = json.loads(trade_plan.take_profit_json)
    assert Decimal(targets["tp1"]) == Decimal("102.50")
    assert Decimal(targets["tp2"]) == Decimal("106.00")


def test_warmup_is_distinct_from_no_pivot() -> None:
    """Fewer bars than the feature warm-up is WARMUP_INSUFFICIENT; enough bars with no pivot is
    NO_TRADE_REGIME; fewer than left + right + 1 bars never yield a pivot."""
    parameter_set = _pivot_set()
    closes = geometry_builders.family_a_rising_closes(250)

    short_setup, short_context = geometry_builders.window_from_closes(closes[:199])
    warm = _evaluate(short_setup, short_context, parameter_set)
    assert warm.is_no_trade
    assert warm.reason_code == REASON_WARMUP_INSUFFICIENT

    enough_setup, enough_context = geometry_builders.window_from_closes(closes[:200])
    enough = _evaluate(enough_setup, enough_context, parameter_set)
    assert enough.is_no_trade
    assert enough.reason_code == RejectionReason.NO_TRADE_REGIME.value

    tiny = geometry_builders.constant_range_candles(
        [Decimal("100"), Decimal("99"), Decimal("98"), Decimal("97"), Decimal("98"), Decimal("99")]
    )
    assert len(tiny) == 3 + 3  # fewer than left + right + 1 = 7 bars
    for index in range(len(tiny)):
        for high in (False, True):
            assert pivot_at(tiny, index, lookback=20, left=3, right=3, high=high) is None


def test_legacy_path_is_unchanged_for_sets_without_geometry_version() -> None:
    """A geometry_version-free set keeps the legacy dispatch: evaluate agrees with the legacy
    `_detect_setup` on the trailing 20-bar swing low, on the p9 windows and a_long_worked."""
    legacy_set = _legacy_set()
    assert "geometry_version" not in legacy_set.params
    for builder in (
        geometry_builders.family_a_p9_beyond_tolerance_window,
        geometry_builders.family_a_p9_inside_tolerance_window,
        geometry_builders.family_a_long_window,
    ):
        setup, context = builder()
        frame = compute_features(
            symbol="BTCUSDT", interval="1h", candles=setup, parameter_set=legacy_set
        )
        expected = _detect_setup(frame, setup[-1], "BULLISH", zone_tolerance_atr=Decimal("0.5"))
        assert expected is not None, builder.__name__  # the trailing extreme contains the bar
        result = _evaluate(setup, context, legacy_set)
        assert not result.is_no_trade, (builder.__name__, result.reason_code)
        assert result.signal is not None
        assert (result.signal.direction, result.signal.setup_type) == expected[:2]
