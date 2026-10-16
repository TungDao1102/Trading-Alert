"""`compute_features` computes the last bar only; it must equal the series-based reference.

Quick task 261015-mvq. The reference below is the previous body of `compute_features`: it builds
every feature series over the whole window with the series helpers (which stay in
`src.core.features`) and reads the last element. The production function computes only the last
bar. Both must return the same `FeatureFrame` (equality and `repr`, which feeds the paper
feature digest) or raise the same exception type with the same message.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from src.core import features as features_module
from src.core.features import (
    _EMA_FAST_PERIOD,
    _EMA_MID_PERIOD,
    _EMA_SLOW_PERIOD,
    _atr_period_from_params,
    _atr_series,
    _detect_gaps,
    _ema_series,
    _expected_bar_duration,
    _swing_series,
    _zone_series,
    compute_features,
)
from src.core.types import (
    REASON_GAP_IN_SOURCE,
    Candle,
    FeatureFrame,
    _invalid,
)
from src.domain.registry import ParameterSet, load_parameter_set

_INTERVAL_HOURS = {"1h": 1, "3h": 3, "4h": 4}

_SETS = (
    ("trend-pullback", "research-run-1-a01"),
    ("breakout-retest", "research-run-1-b01"),
    ("range-mr", "research-run-1-c01"),
    ("trend-pullback", "baseline-v6"),
)


def _reference_compute_features(
    *,
    symbol: str,
    interval: str,
    candles: list[Candle],
    parameter_set: ParameterSet,
) -> FeatureFrame:
    """The series-based body `compute_features` had before quick task 261015-mvq."""
    if not candles:
        raise ValueError("compute_features: candles must be non-empty")
    for c in candles:
        if c.symbol != symbol:
            raise ValueError(f"compute_features: candle symbol {c.symbol!r} != {symbol!r}")
        if c.interval != interval:
            raise ValueError(f"compute_features: candle interval {c.interval!r} != {interval!r}")
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
    swing_lookback = int(parameter_set.params["swing_lookback"])
    zone_tolerance_atr = parameter_set.params["zone_tolerance_atr"]
    if not isinstance(zone_tolerance_atr, Decimal):
        zone_tolerance_atr = Decimal(str(zone_tolerance_atr))

    closes = [c.close for c in candles]
    ema_20 = _ema_series(closes, _EMA_FAST_PERIOD)
    ema_50 = _ema_series(closes, _EMA_MID_PERIOD)
    ema_200 = _ema_series(closes, _EMA_SLOW_PERIOD)
    atr_14 = _atr_series(candles, _atr_period_from_params(parameter_set))
    swing_high = _swing_series(candles, swing_lookback, high=True)
    swing_low = _swing_series(candles, swing_lookback, high=False)
    zone_upper, zone_lower = _zone_series(
        candles, atr_14, swing_low, swing_high, zone_tolerance_atr
    )

    expected = _expected_bar_duration(candles, interval)
    gap_flags = _detect_gaps(candles, expected)
    if any(gap_flags):
        first_gap = gap_flags.index(True)
        for series in (
            ema_20,
            ema_50,
            ema_200,
            atr_14,
            swing_high,
            swing_low,
            zone_upper,
            zone_lower,
        ):
            for i in range(first_gap, len(series)):
                if series[i].valid:
                    series[i] = _invalid(REASON_GAP_IN_SOURCE)

    last = len(candles) - 1
    required = (
        ema_20[last],
        ema_50[last],
        ema_200[last],
        atr_14[last],
        swing_high[last],
        swing_low[last],
        zone_upper[last],
        zone_lower[last],
    )
    return FeatureFrame(
        symbol=symbol,
        interval=interval,
        bar_index=last,
        bar_close_utc=candles[last].close_time_utc,
        features_valid=all(f.valid for f in required),
        ema_20=ema_20[last],
        ema_50=ema_50[last],
        ema_200=ema_200[last],
        atr_14=atr_14[last],
        swing_high=swing_high[last],
        swing_low=swing_low[last],
        zone_upper=zone_upper[last],
        zone_lower=zone_lower[last],
    )


def _bars(
    seed: int,
    count: int,
    *,
    interval: str = "1h",
    symbol: str = "BTCUSDT",
    digits: int = 2,
    flat: bool = False,
) -> list[Candle]:
    """Seeded random-walk bars; `digits` is the number of decimals of every price."""
    rng = random.Random(seed)
    step = timedelta(hours=_INTERVAL_HOURS[interval])
    start = datetime(2024, 10, 3, tzinfo=UTC)
    quantum = Decimal(1).scaleb(-digits)
    price = Decimal("100.5")
    out: list[Candle] = []
    for i in range(count):
        if flat:
            o = h = low = c = price
        else:
            move = Decimal(rng.randint(-300, 300)) * quantum
            o = price
            c = max(quantum, o + move)
            h = max(o, c) + Decimal(rng.randint(0, 200)) * quantum
            low = max(quantum, min(o, c) - Decimal(rng.randint(0, 200)) * quantum)
            price = c
        opened = start + i * step
        out.append(
            Candle(
                symbol=symbol,
                interval=interval,
                open_time_utc=opened,
                close_time_utc=opened + step - timedelta(milliseconds=1),
                open=o,
                high=h,
                low=low,
                close=c,
                volume=Decimal("10"),
            )
        )
    return out


def _drop(bars: list[Candle], *indexes: int) -> list[Candle]:
    return [b for i, b in enumerate(bars) if i not in indexes]


def _outcome(function, **kwargs):  # type: ignore[no-untyped-def]
    try:
        return ("ok", function(**kwargs))
    except Exception as error:
        return ("raised", type(error), str(error))


def _assert_same(
    candles: list[Candle], parameter_set: ParameterSet, *, interval: str = "1h"
) -> None:
    kwargs = {
        "symbol": "BTCUSDT",
        "interval": interval,
        "candles": candles,
        "parameter_set": parameter_set,
    }
    old = _outcome(_reference_compute_features, **kwargs)
    new = _outcome(compute_features, **kwargs)
    assert old == new
    if old[0] == "ok":
        assert repr(old[1]) == repr(new[1])


@pytest.fixture(scope="module")
def parameter_sets() -> list[ParameterSet]:
    return [load_parameter_set(strategy, name) for strategy, name in _SETS]


def test_every_warmup_length_matches(parameter_sets: list[ParameterSet]) -> None:
    bars = _bars(1, 260)
    for ps in parameter_sets:
        for length in range(1, 261):
            _assert_same(bars[:length], ps)


@pytest.mark.parametrize(("interval", "window"), [("1h", 1000), ("4h", 300)])
def test_full_windows_match(parameter_sets: list[ParameterSet], interval: str, window: int) -> None:
    bars = _bars(2, window + 40, interval=interval)
    for ps in parameter_sets:
        for end in (window, window + 7, window + 40):
            _assert_same(bars[end - window : end], ps, interval=interval)


def test_gaps_match(parameter_sets: list[ParameterSet]) -> None:
    bars = _bars(3, 300)
    cases = [
        _drop(bars, 1),
        _drop(bars, 150),
        _drop(bars, 298),
        _drop(bars, 10, 200),
        _drop(bars, 1, 299),
        _drop(bars, 0),
        _drop(bars[:30], 5),
        _drop(bars[:5], 3),
    ]
    for ps in parameter_sets:
        for window in cases:
            _assert_same(window, ps)


def test_flat_and_many_digit_prices_match(parameter_sets: list[ParameterSet]) -> None:
    cases = [
        _bars(4, 260, flat=True),
        _bars(5, 260, digits=8),
        _bars(6, 260, digits=20),
        _bars(7, 260, digits=27),
    ]
    for ps in parameter_sets:
        for window in cases:
            _assert_same(window, ps)


@pytest.mark.parametrize("period", [1, 2, 3, 14, 250])
def test_atr_periods_match(parameter_sets: list[ParameterSet], period: int) -> None:
    bars = _bars(8, 300)
    base = parameter_sets[0]
    changed = ParameterSet(
        strategy_id=base.strategy_id,
        strategy_version=base.strategy_version,
        parameter_set_id=base.parameter_set_id,
        params={**base.params, "atr_period": period},
        parameter_set_hash=base.parameter_set_hash,
    )
    for length in (1, period, period + 1, period + 2, 120, 300):
        _assert_same(bars[: min(length, 300)], changed)


def test_swing_lookback_longer_than_window_matches(parameter_sets: list[ParameterSet]) -> None:
    bars = _bars(9, 50)
    base = parameter_sets[0]
    for lookback in (1, 2, 49, 50, 51, 300):
        changed = ParameterSet(
            strategy_id=base.strategy_id,
            strategy_version=base.strategy_version,
            parameter_set_id=base.parameter_set_id,
            params={**base.params, "swing_lookback": lookback},
            parameter_set_hash=base.parameter_set_hash,
        )
        _assert_same(bars, changed)


def test_invalid_inputs_raise_the_same_error(parameter_sets: list[ParameterSet]) -> None:
    ps = parameter_sets[0]
    bars = _bars(10, 30)
    _assert_same([], ps)
    _assert_same(bars, ps, interval="4h")
    _assert_same(bars, ps, interval="2h")
    _assert_same(bars + [bars[-1]], ps)
    _assert_same([bars[1], bars[0]], ps)
    other = [
        Candle(
            symbol="ETHUSDT",
            interval=b.interval,
            open_time_utc=b.open_time_utc,
            close_time_utc=b.close_time_utc,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
        )
        for b in bars
    ]
    _assert_same(other, ps)


@pytest.mark.parametrize(
    ("swing_lookback", "atr_period"),
    [(0, 14), (-1, 14), (20, 0), (20, -3), (0, 0), (-2, -2), (20, "x"), (0, "x")],
)
def test_bad_parameters_raise_the_same_error(
    parameter_sets: list[ParameterSet], swing_lookback: int, atr_period: object
) -> None:
    base = parameter_sets[0]
    changed = ParameterSet(
        strategy_id=base.strategy_id,
        strategy_version=base.strategy_version,
        parameter_set_id=base.parameter_set_id,
        params={**base.params, "swing_lookback": swing_lookback, "atr_period": atr_period},
        parameter_set_hash=base.parameter_set_hash,
    )
    for length in (1, 10, 30, 260):
        _assert_same(_bars(11, length), changed)


def test_helpers_other_callers_use_are_still_exported() -> None:
    for name in (
        "_ema_series",
        "_atr_series",
        "_swing_series",
        "_zone_series",
        "ema_update",
        "true_range",
    ):
        assert callable(getattr(features_module, name))


def test_result_does_not_depend_on_the_ambient_context_above_the_pinned_precision() -> None:
    bars = _bars(12, 260, digits=20)
    ps = load_parameter_set("trend-pullback", "research-run-1-a01")
    kwargs = {"symbol": "BTCUSDT", "interval": "1h", "candles": bars, "parameter_set": ps}
    with localcontext() as ctx:
        ctx.prec = 50
        assert repr(compute_features(**kwargs)) == repr(_reference_compute_features(**kwargs))


@pytest.mark.parametrize("length", [1, 2, 30])
@pytest.mark.parametrize(
    ("swing_lookback", "atr_period"), [(20, 14), (0, 14), (20, 0), (0, 0), (20, "x")]
)
def test_unsupported_interval_raises_after_the_parameter_checks(
    parameter_sets: list[ParameterSet],
    length: int,
    swing_lookback: int,
    atr_period: object,
) -> None:
    base = parameter_sets[0]
    changed = ParameterSet(
        strategy_id=base.strategy_id,
        strategy_version=base.strategy_version,
        parameter_set_id=base.parameter_set_id,
        params={**base.params, "swing_lookback": swing_lookback, "atr_period": atr_period},
        parameter_set_hash=base.parameter_set_hash,
    )
    _assert_same(_bars(13, length, interval="3h"), changed, interval="3h")
