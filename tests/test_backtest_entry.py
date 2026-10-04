"""Entry rule tests for the causal lifecycle driver (Phase 14, plan 14-02, Task 2).

Hand oracles (zone 99.50-100.60 -> mid 100.05; tick 0.10; D-07, D-08):

    LONG : live rounding floors the limit -> 100.00; fills only on a trade low <= 99.90.
           low 99.95 does not fill (and touches, 99.95 <= 100.00); low 99.90 fills.
    SHORT: live rounding ceils the limit  -> 100.10; fills only on a trade high >= 100.20.
           high 100.15 does not fill; high 100.10 only touches; high 100.20 fills.
    Gap through: the fill price is the limit, never the better open (no price improvement).
    Tick sensitivity: mid 100.30 with tick 0.10 gives limit 100.30 (fill needs low <= 100.20),
           with tick 0.50 it gives limit 100.00 (fill needs low <= 99.50).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.backtest.lifecycle import LifecycleEvent, PlanState, advance, new_plan_state
from src.backtest.series import ListMinuteSource
from src.core.types import Candle

from tests.backtest_plan_helpers import make_minute, make_trade_plan

SYMBOL = "BTCUSDT"
SIGNAL_CLOSE = datetime(2026, 1, 5, 9, 59, 59, 999000, tzinfo=UTC)
WINDOW_END = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC)  # well before expiry 13:59:59.999
TICK = Decimal("0.10")


def D(text: str) -> Decimal:  # noqa: N802 - terse fixture helper
    return Decimal(text)


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 1, 5, hour, minute, tzinfo=UTC)


def _trade(minute: int, *, o: str, h: str, low: str, c: str, hour: int = 10) -> Candle:
    return make_minute(SYMBOL, _at(hour, minute), o, h, low, c, "trade")


def _benign_marks(minutes: list[tuple[int, int]]) -> list[Candle]:
    """Mark minutes (99.00-101.00) far from both stops (LONG 98.00, SHORT 102.00)."""
    return [
        make_minute(SYMBOL, _at(h, m), "100.00", "101.00", "99.00", "100.00", "mark")
        for h, m in minutes
    ]


def _state(
    direction: str, *, tick: Decimal = TICK, mid_zone: tuple[str, str] | None = None
) -> PlanState:
    stop = "98.00" if direction == "LONG" else "102.00"
    zone = mid_zone if mid_zone is not None else ("99.50", "100.60")
    plan = make_trade_plan(
        direction,
        entry_min=zone[0],
        entry_max=zone[1],
        stop_loss=stop,
        signal_close_utc=SIGNAL_CLOSE,
    )
    return new_plan_state(
        plan=plan,
        symbol=SYMBOL,
        direction=direction,
        signal_close_utc=SIGNAL_CLOSE,
        price_tick_size=tick,
        planned_quantity=D("0.5"),
        sized_realized_risk=D("1.50"),
    )


def _run(
    state: PlanState, trade: list[Candle], direction: str
) -> tuple[PlanState, tuple[LifecycleEvent, ...]]:
    marks = _benign_marks([(c.open_time_utc.hour, c.open_time_utc.minute) for c in trade])
    source = ListMinuteSource(trade={SYMBOL: trade}, mark={SYMBOL: marks})
    return advance(
        state,
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )


def test_long_limit_floors_and_fills_only_on_a_one_tick_trade_through() -> None:
    state = _state("LONG")
    assert state.limit_price == D("100.00")  # mid 100.05 floored (BUY) to the 0.10 grid

    # low 99.95: reaches the limit (touch) but is not <= 99.90 -> no fill.
    near, near_events = _run(
        state, [_trade(0, o="100.40", h="100.50", low="99.95", c="100.20")], "LONG"
    )
    assert near.phase == "RESTING"
    assert near.touch_no_fill_count == 1
    assert near_events == ()

    # low 99.90: exactly one tick through -> fills at the limit at the minute close.
    filled, events = _run(
        state, [_trade(0, o="100.40", h="100.50", low="99.90", c="100.20")], "LONG"
    )
    assert filled.entry_price == D("100.00")
    assert filled.entry_time_utc == datetime(2026, 1, 5, 10, 0, 59, 999000, tzinfo=UTC)
    assert [e.kind for e in events] == ["FILL"]
    assert events[0].price == D("100.00")


def test_short_limit_ceils_and_fills_only_on_a_one_tick_trade_through() -> None:
    state = _state("SHORT")
    assert state.limit_price == D("100.10")  # mid 100.05 ceiled (SELL) to the 0.10 grid

    below, below_events = _run(
        state, [_trade(0, o="99.80", h="100.15", low="99.70", c="100.00")], "SHORT"
    )
    assert below.phase == "RESTING"
    assert below.touch_no_fill_count == 1  # 100.15 >= 100.10 touches, but < 100.20
    assert below_events == ()

    exact_touch, _ = _run(
        state, [_trade(0, o="99.80", h="100.10", low="99.70", c="100.00")], "SHORT"
    )
    assert exact_touch.phase == "RESTING"
    assert exact_touch.touch_no_fill_count == 1  # high 100.10 only touches the limit

    filled, events = _run(
        state, [_trade(0, o="99.80", h="100.20", low="99.70", c="100.00")], "SHORT"
    )
    assert filled.entry_price == D("100.10")
    assert filled.entry_time_utc == datetime(2026, 1, 5, 10, 0, 59, 999000, tzinfo=UTC)
    assert [e.kind for e in events] == ["FILL"]


def test_gap_through_the_long_limit_fills_at_the_limit_with_no_price_improvement() -> None:
    gap = _trade(0, o="97.00", h="97.40", low="96.50", c="97.00")
    filled, events = _run(_state("LONG"), [gap], "LONG")
    assert filled.entry_price == D("100.00")  # never the better open 97.00
    assert events[0].price == D("100.00")


def test_gap_through_the_short_limit_fills_at_the_limit_with_no_price_improvement() -> None:
    gap = _trade(0, o="103.00", h="104.00", low="102.80", c="103.50")
    filled, events = _run(_state("SHORT"), [gap], "SHORT")
    assert filled.entry_price == D("100.10")  # never the better open 103.00
    assert events[0].price == D("100.10")


def test_touching_minutes_are_counted_and_never_create_records_or_events() -> None:
    state = _state("LONG")
    minutes = [
        _trade(0, o="100.50", h="100.80", low="100.00", c="100.40"),
        _trade(1, o="100.40", h="100.60", low="99.95", c="100.30"),
        _trade(2, o="100.30", h="100.50", low="99.99", c="100.20"),
        _trade(3, o="100.20", h="100.50", low="99.90", c="100.30"),
    ]
    resting, none_events = _run(state, minutes[:3], "LONG")
    assert resting.phase == "RESTING"
    assert resting.touch_no_fill_count == 3
    assert none_events == ()

    filled, events = _run(state, minutes, "LONG")
    assert filled.touch_no_fill_count == 3
    assert [e.kind for e in events] == ["FILL"]  # the three touches produced no event


def test_a_hole_at_the_trade_through_minute_never_fills_and_is_not_padded() -> None:
    state = _state("LONG")
    # 10:03 would have traded through but is absent from the series (a hole).
    held, held_events = _run(
        state,
        [
            _trade(2, o="100.50", h="100.80", low="100.00", c="100.40"),
            _trade(4, o="100.50", h="100.80", low="100.30", c="100.60"),
        ],
        "LONG",
    )
    assert held.phase == "RESTING"
    assert held.entry_price is None
    assert held.touch_no_fill_count == 1
    assert held_events == ()

    # The next present minute is evaluated normally and fills.
    filled, events = _run(
        state,
        [
            _trade(2, o="100.50", h="100.80", low="100.00", c="100.40"),
            _trade(4, o="100.50", h="100.80", low="99.80", c="100.20"),
        ],
        "LONG",
    )
    assert filled.entry_time_utc == datetime(2026, 1, 5, 10, 4, 59, 999000, tzinfo=UTC)
    assert [e.kind for e in events] == ["FILL"]


def test_trade_minutes_inside_the_signal_bar_never_fill() -> None:
    signal_bar_minute = make_minute(
        SYMBOL,
        datetime(2026, 1, 5, 9, 59, tzinfo=UTC),
        "95.00",
        "100.00",
        "50.00",
        "95.00",
        "trade",
    )
    after = _trade(0, o="100.50", h="100.80", low="100.30", c="100.40")
    source = ListMinuteSource(
        trade={SYMBOL: [signal_bar_minute, after]},
        mark={SYMBOL: _benign_marks([(10, 0)])},
    )
    state, events = advance(
        _state("LONG"),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    assert state.phase == "RESTING"
    assert state.touch_no_fill_count == 0
    assert events == ()


def test_the_tick_comes_from_the_plan_state_not_a_module_constant() -> None:
    zone = ("100.20", "100.40")  # mid 100.30
    minute = [_trade(0, o="100.40", h="100.50", low="100.20", c="100.30")]
    fine = _state("LONG", tick=D("0.10"), mid_zone=zone)
    coarse = _state("LONG", tick=D("0.50"), mid_zone=zone)
    assert fine.limit_price == D("100.30")
    assert coarse.limit_price == D("100.00")  # 100.30 floored onto the 0.50 grid

    fine_result, _ = _run(fine, minute, "LONG")
    coarse_result, _ = _run(coarse, minute, "LONG")
    assert fine_result.phase == "OPEN"  # low 100.20 <= 100.30 - 0.10
    assert fine_result.entry_price == D("100.30")
    assert coarse_result.phase == "RESTING"  # low 100.20 > 100.00 - 0.50 and > 100.00
    assert coarse_result.touch_no_fill_count == 0


def test_touches_after_expiry_are_not_counted() -> None:
    late_touch = _trade(0, o="100.50", h="100.80", low="100.00", c="100.40", hour=14)
    early_touch = _trade(0, o="100.50", h="100.80", low="100.00", c="100.40", hour=11)
    source = ListMinuteSource(
        trade={SYMBOL: [early_touch, late_touch]},
        mark={SYMBOL: _benign_marks([(11, 0), (14, 0)])},
    )
    state, _ = advance(
        _state("LONG"),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=datetime(2026, 1, 5, 16, 0, tzinfo=UTC),
        bar=None,
    )
    assert state.entry_kind == "EXPIRED"
    assert state.touch_no_fill_count == 1  # only the 11:00 touch, not the 14:00 one


def test_is_touch_and_is_trade_through_are_side_specific() -> None:
    from src.backtest.entry import is_touch, is_trade_through

    limit = D("100.00")
    long_low_95 = _trade(0, o="100.40", h="100.50", low="99.95", c="100.20")
    long_low_90 = _trade(0, o="100.40", h="100.50", low="99.90", c="100.20")
    long_far = _trade(0, o="100.40", h="100.50", low="100.01", c="100.20")
    assert is_touch(minute=long_low_95, limit_price=limit, direction="LONG") is True
    assert is_touch(minute=long_far, limit_price=limit, direction="LONG") is False
    assert (
        is_trade_through(
            minute=long_low_95, limit_price=limit, price_tick_size=TICK, direction="LONG"
        )
        is False
    )
    assert (
        is_trade_through(
            minute=long_low_90, limit_price=limit, price_tick_size=TICK, direction="LONG"
        )
        is True
    )

    short_limit = D("100.10")
    short_high_10 = _trade(0, o="99.80", h="100.10", low="99.70", c="100.00")
    short_high_20 = _trade(0, o="99.80", h="100.20", low="99.70", c="100.00")
    short_far = _trade(0, o="99.80", h="100.09", low="99.70", c="100.00")
    assert is_touch(minute=short_high_10, limit_price=short_limit, direction="SHORT") is True
    assert is_touch(minute=short_far, limit_price=short_limit, direction="SHORT") is False
    assert (
        is_trade_through(
            minute=short_high_10, limit_price=short_limit, price_tick_size=TICK, direction="SHORT"
        )
        is False
    )
    assert (
        is_trade_through(
            minute=short_high_20, limit_price=short_limit, price_tick_size=TICK, direction="SHORT"
        )
        is True
    )
