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

import dataclasses
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import src.backtest.entry as entry_rules
import src.backtest.lifecycle as lifecycle_api
from src.backtest.lifecycle import LifecycleEvent, PlanState, advance, new_plan_state
from src.backtest.series import ListMinuteSource
from src.core.types import Candle
from src.domain.trade_plan import TradePlan

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


# --------------------------------------------------------------------------- #
# Task 3: CANDLE_CLOSE invalidation, cancel API, PENDING_AT_DATA_END (D-05, D-32..D-35)
#
# Hand oracles (strategy bars are 1h; signal bar N = 09:00-09:59, N+1 = 10:00-10:59):
#     LONG  level 98.00 (= stop): bar close 97.90 < 98.00 -> INVALIDATION_CANCEL at the bar
#           close 10:59:59.999; close 98.00 is not beyond the level -> still RESTING.
#     SHORT level 102.00: bar close 102.10 > 102.00 -> INVALIDATION_CANCEL.
#     Fill first: the 10:30 minute trades through (low 99.90) and the bar closes 97.90 ->
#           the plan FILLS and is not invalidated.
#     Expiry 13:59:59.999: the 13:00-13:59 bar closes at expiry beyond the level ->
#           INVALIDATION_CANCEL wins over EXPIRED; with no bar (a mid-bar window) -> EXPIRED.
# --------------------------------------------------------------------------- #

BAR_1_CLOSE = datetime(2026, 1, 5, 10, 59, 59, 999000, tzinfo=UTC)
EXPIRY = datetime(2026, 1, 5, 13, 59, 59, 999000, tzinfo=UTC)


def _bar(open_hour: int, close: str) -> Candle:
    """A 1h strategy bar (open_hour:00 - open_hour:59:59.999) closing at `close`."""
    return Candle(
        symbol=SYMBOL,
        interval="1h",
        open_time_utc=datetime(2026, 1, 5, open_hour, 0, tzinfo=UTC),
        close_time_utc=datetime(2026, 1, 5, open_hour, 59, 59, 999000, tzinfo=UTC),
        open=D("100.00"),
        high=D("103.00"),
        low=D("97.00"),
        close=D(close),
        volume=D("10"),
    )


def _flat_minutes(hour: int, count: int = 3) -> list[Candle]:
    """Trade minutes that never reach the LONG limit 100.00 nor the SHORT limit 100.10."""
    return [
        make_minute(SYMBOL, _at(hour, m), "100.04", "100.05", "100.01", "100.03", "trade")
        for m in range(count)
    ]


def _bar_run(
    state: PlanState,
    trade: list[Candle],
    *,
    bar: Candle | None,
    start: datetime = SIGNAL_CLOSE,
    end: datetime = BAR_1_CLOSE,
) -> tuple[PlanState, tuple[LifecycleEvent, ...]]:
    marks = _benign_marks([(c.open_time_utc.hour, c.open_time_utc.minute) for c in trade])
    source = ListMinuteSource(trade={SYMBOL: trade}, mark={SYMBOL: marks})
    return advance(state, source=source, start_exclusive=start, end_inclusive=end, bar=bar)


def _opened_long() -> PlanState:
    filled, _ = _run(
        _state("LONG"), [_trade(0, o="100.40", h="100.50", low="99.90", c="100.20")], "LONG"
    )
    assert filled.phase == "OPEN"
    return filled


def test_invalidation_level_parses_the_candle_close_rule_and_fails_closed() -> None:
    plan = make_trade_plan("LONG", stop_loss="98.00")
    assert entry_rules.invalidation_level(plan) == D("98.00")

    def with_rule(rule: object) -> TradePlan:
        text = rule if isinstance(rule, str) else json.dumps(rule)
        return dataclasses.replace(plan, invalidation_rule_json=text)

    with pytest.raises(ValueError, match="CANDLE_CLOSE"):
        entry_rules.invalidation_level(with_rule({"basis": "WICK", "level": "98.00"}))
    with pytest.raises(ValueError, match="level"):
        entry_rules.invalidation_level(with_rule({"basis": "CANDLE_CLOSE"}))
    with pytest.raises(ValueError, match="level"):
        entry_rules.invalidation_level(with_rule({"basis": "CANDLE_CLOSE", "level": 98.0}))
    with pytest.raises(ValueError, match="level"):
        entry_rules.invalidation_level(with_rule({"basis": "CANDLE_CLOSE", "level": "abc"}))
    with pytest.raises(ValueError, match="JSON"):
        entry_rules.invalidation_level(with_rule("{not json"))


def test_is_invalidated_is_strictly_beyond_the_level_on_each_side() -> None:
    level = D("98.00")
    assert (
        entry_rules.is_invalidated(bar_close_price=D("97.90"), level=level, direction="LONG")
        is True
    )
    assert (
        entry_rules.is_invalidated(bar_close_price=D("98.00"), level=level, direction="LONG")
        is False
    )
    assert (
        entry_rules.is_invalidated(bar_close_price=D("99.00"), level=level, direction="LONG")
        is False
    )
    high = D("102.00")
    assert (
        entry_rules.is_invalidated(bar_close_price=D("102.10"), level=high, direction="SHORT")
        is True
    )
    assert (
        entry_rules.is_invalidated(bar_close_price=D("102.00"), level=high, direction="SHORT")
        is False
    )
    assert (
        entry_rules.is_invalidated(bar_close_price=D("101.00"), level=high, direction="SHORT")
        is False
    )


def test_long_bar_closing_below_the_level_without_a_fill_is_invalidation_cancel() -> None:
    state, events = _bar_run(_state("LONG"), _flat_minutes(10), bar=_bar(10, "97.90"))
    assert state.phase == "CLOSED"
    assert state.entry_kind == "INVALIDATION_CANCEL"
    assert state.entry_time_utc is None
    assert state.resolved_at_utc == BAR_1_CLOSE
    assert [e.kind for e in events] == ["CANCEL"]
    assert events[0].time_utc == BAR_1_CLOSE
    assert events[0].entry_kind == "INVALIDATION_CANCEL"


def test_bar_closing_exactly_at_the_level_does_not_invalidate() -> None:
    state, events = _bar_run(_state("LONG"), _flat_minutes(10), bar=_bar(10, "98.00"))
    assert state.phase == "RESTING"
    assert events == ()


def test_short_bar_closing_above_the_level_is_invalidation_cancel() -> None:
    state, events = _bar_run(_state("SHORT"), _flat_minutes(10), bar=_bar(10, "102.10"))
    assert state.entry_kind == "INVALIDATION_CANCEL"
    assert state.resolved_at_utc == BAR_1_CLOSE
    assert [e.kind for e in events] == ["CANCEL"]


def test_fill_is_evaluated_first_so_a_filling_bar_is_never_invalidated() -> None:
    minutes = [
        *_flat_minutes(10, 30),
        make_minute(SYMBOL, _at(10, 30), "100.40", "100.50", "99.90", "100.20", "trade"),
    ]
    # The mark series covers the whole bar: a hole after the fill would (since plan 14-07)
    # resolve the rest of the bar at the bar close, which is not what this test is about.
    marks = _benign_marks([(10, m) for m in range(60)])
    source = ListMinuteSource(trade={SYMBOL: minutes}, mark={SYMBOL: marks})
    state, events = advance(
        _state("LONG"),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=BAR_1_CLOSE,
        bar=_bar(10, "97.90"),
    )
    assert state.phase == "OPEN"
    assert state.entry_kind == "ENTRY_FILLED"
    assert state.entry_time_utc == datetime(2026, 1, 5, 10, 30, 59, 999000, tzinfo=UTC)
    assert [e.kind for e in events] == ["FILL"]


def test_invalidation_wins_over_expiry_at_the_same_instant() -> None:
    start = datetime(2026, 1, 5, 12, 59, 59, 999000, tzinfo=UTC)
    minutes = _flat_minutes(13)
    invalidated, invalidated_events = _bar_run(
        _state("LONG"), minutes, bar=_bar(13, "97.90"), start=start, end=EXPIRY
    )
    assert invalidated.entry_kind == "INVALIDATION_CANCEL"
    assert invalidated.resolved_at_utc == EXPIRY
    assert [e.entry_kind for e in invalidated_events] == ["INVALIDATION_CANCEL"]

    # The same window without a strategy bar (mid-bar view) never invalidates: it expires.
    expired, expired_events = _bar_run(_state("LONG"), minutes, bar=None, start=start, end=EXPIRY)
    assert expired.entry_kind == "EXPIRED"
    assert [e.entry_kind for e in expired_events] == ["EXPIRED"]


def test_a_bar_closing_after_expiry_cannot_invalidate_an_already_expired_plan() -> None:
    start = datetime(2026, 1, 5, 12, 59, 59, 999000, tzinfo=UTC)
    end = datetime(2026, 1, 5, 14, 59, 59, 999000, tzinfo=UTC)
    state, events = _bar_run(
        _state("LONG"), _flat_minutes(13), bar=_bar(14, "97.90"), start=start, end=end
    )
    assert state.entry_kind == "EXPIRED"
    assert state.resolved_at_utc == EXPIRY
    assert [e.kind for e in events] == ["CANCEL"]


def test_a_window_that_ends_mid_bar_never_invalidates() -> None:
    # Minutes sit just under the SHORT limit and above the LONG stop, bar is None: nothing ends.
    quiet = [make_minute(SYMBOL, _at(10, 0), "100.05", "100.05", "100.01", "100.03", "trade")]
    state, events = _bar_run(_state("SHORT"), quiet, bar=None)
    assert state.phase == "RESTING"
    assert events == ()
    # A LONG whose minutes sit far below the level fills (trade-through); it is never cancelled.
    crash = [make_minute(SYMBOL, _at(10, 0), "97.00", "97.50", "96.00", "96.50", "trade")]
    long_state, long_events = _bar_run(_state("LONG"), crash, bar=None)
    assert long_state.entry_kind == "ENTRY_FILLED"
    assert [e.kind for e in long_events] == ["FILL"]


def test_a_bar_that_does_not_close_at_the_window_end_is_refused() -> None:
    with pytest.raises(ValueError, match="bar"):
        _bar_run(_state("LONG"), _flat_minutes(10), bar=_bar(9, "97.90"))


def test_cancel_plan_ends_a_resting_plan_at_the_given_instant() -> None:
    at = datetime(2026, 1, 5, 10, 15, 30, tzinfo=UTC)
    state, events = lifecycle_api.cancel_plan(
        _state("LONG"), entry_kind="DAILY_STOP_CANCEL", at_utc=at
    )
    assert state.phase == "CLOSED"
    assert state.entry_kind == "DAILY_STOP_CANCEL"
    assert state.resolved_at_utc == at
    assert state.entry_time_utc is None
    assert [e.kind for e in events] == ["CANCEL"]
    assert events[0].time_utc == at
    assert events[0].entry_kind == "DAILY_STOP_CANCEL"


def test_cancel_plan_refuses_an_open_position_a_fill_kind_and_a_naive_instant() -> None:
    at = datetime(2026, 1, 5, 11, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="OPEN"):
        lifecycle_api.cancel_plan(_opened_long(), entry_kind="DAILY_STOP_CANCEL", at_utc=at)
    with pytest.raises(ValueError, match="entry_kind"):
        lifecycle_api.cancel_plan(_state("LONG"), entry_kind="ENTRY_FILLED", at_utc=at)
    with pytest.raises(ValueError, match="UTC"):
        lifecycle_api.cancel_plan(
            _state("LONG"), entry_kind="DAILY_STOP_CANCEL", at_utc=datetime(2026, 1, 5, 11)
        )


def test_a_plan_still_resting_at_data_end_is_pending_not_expired() -> None:
    data_end = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC)  # before expiry 13:59:59.999
    resting, _ = _bar_run(_state("LONG"), _flat_minutes(10), bar=None, end=data_end)
    assert resting.phase == "RESTING"
    final, events = lifecycle_api.finalize_at_data_end(resting, data_end_utc=data_end)
    assert final.phase == "CLOSED"
    assert final.entry_kind == "PENDING_AT_DATA_END"
    assert final.entry_kind != "EXPIRED"
    assert final.resolved_at_utc == data_end
    assert [e.kind for e in events] == ["PENDING"]
    assert events[0].time_utc == data_end
    assert events[0].entry_kind == "PENDING_AT_DATA_END"


def test_finalize_at_data_end_refuses_an_open_position_without_a_minute_source() -> None:
    with pytest.raises(ValueError, match="END_OF_DATA"):
        lifecycle_api.finalize_at_data_end(_opened_long(), data_end_utc=WINDOW_END)


def test_finalize_at_data_end_leaves_a_terminal_plan_untouched() -> None:
    start = datetime(2026, 1, 5, 12, 59, 59, 999000, tzinfo=UTC)
    expired, _ = _bar_run(_state("LONG"), _flat_minutes(13), bar=None, start=start, end=EXPIRY)
    assert expired.entry_kind == "EXPIRED"
    final, events = lifecycle_api.finalize_at_data_end(expired, data_end_utc=EXPIRY)
    assert final == expired
    assert events == ()
