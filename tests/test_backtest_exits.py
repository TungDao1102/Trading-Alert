"""Exit-ladder tests for the causal lifecycle driver (Phase 14, plan 14-07).

Tracer (Task 1): a filled LONG takes TP1 (half of the fill, sized by the live helper) on
bar N+2 and TP2 on bar N+4, and the record books both legs.

Hand oracle (LONG, zone 99.00-101.00 -> mid 100.00; tick 0.10, step 0.001, min qty 0.001,
min notional 5; SL 98.00, TP1 104.00, TP2 108.00; filled 0.5):

    TP1 quantity   = floor(0.5 x 0.5 to step 0.001) = 0.250 (live size_protectives_to_filled_qty)
    gross_pnl      = 0.250 x (104.00 - 100.00) + 0.250 x (108.00 - 100.00) = 1.00 + 2.00 = 3.00
    entry fee      = 100.00 x 0.5   x 0.0005 = 0.0250
    entry slippage = 100.00 x 0.5   x 0.0002 = 0.0100   (expected_slippage)
    TP1 fee        = 104.00 x 0.250 x 0.0005 = 0.0130
    TP1 slippage   = 104.00 x 0.250 x 0.0002 = 0.0052   (TP legs use expected_slippage)
    TP2 fee        = 108.00 x 0.250 x 0.0005 = 0.0135
    TP2 slippage   = 108.00 x 0.250 x 0.0002 = 0.0054
    exit_fee       = 0.0130 + 0.0135 = 0.0265
    slippage       = 0.0100 + 0.0052 + 0.0054 = 0.0206
    realized_pnl   = 3.00 - 0.0250 - 0.0265 - 0.0206 + 0 = 2.9279
    bookings       = FILL -0.0350, TP1 +0.9818, EXIT +1.9811 (sum 2.9279)
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.backtest.costs import CostModel
from src.backtest.exits import (
    ProtectiveLevels,
    ProtectiveReject,
    end_of_data_exit,
    protective_levels_for_fill,
    resolve_fallback_hour,
    resolve_mark_minute,
)
from src.backtest.lifecycle import (
    LifecycleEvent,
    PlanState,
    advance,
    finalize_at_data_end,
    new_plan_state,
)
from src.backtest.records import TradeRecord, booking_for_event, build_trade_record
from src.backtest.series import ListMinuteSource
from src.backtest.validator import validate_trade_record
from src.core.types import Candle
from src.domain.trade_plan import TradePlan
from src.risk.types import ConstraintSnapshot

from tests.backtest_plan_helpers import make_minute, make_trade_plan

SYMBOL = "BTCUSDT"
TICK = Decimal("0.10")
SIGNAL_CLOSE = datetime(2026, 1, 5, 9, 59, 59, 999000, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
SNAPSHOT = ConstraintSnapshot(
    symbol=SYMBOL,
    price_tick_size=TICK,
    quantity_step_size=Decimal("0.001"),
    min_quantity=Decimal("0.001"),
    min_notional=Decimal("5"),
    metadata_observed_at_utc=datetime(2025, 12, 1, tzinfo=UTC),
)
Ohlc = tuple[str, str, str, str]


def D(text: str) -> Decimal:  # noqa: N802 - terse fixture helper
    return Decimal(text)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 5, hour, minute, tzinfo=UTC)


def close_of(open_time: datetime) -> datetime:
    """Close time of a 1m minute built by `make_minute` (open + 59.999 s)."""
    return open_time + timedelta(seconds=59, milliseconds=999)


def cost_model() -> CostModel:
    return CostModel(
        fee_rate_entry=D("0.0005"),
        fee_rate_exit=D("0.0005"),
        funding_treatment="ADDITIVE",
        expected_slippage=D("0.0002"),
        slippage_model="FIXED_RATE",
        spread_fill_assumptions="TAKER",
        partial_fill_fraction=D("1"),
        cost_model_hash="",
        exit_slippage_rate=D("0.0010"),
    )


def minutes(
    kind: str,
    first_open: datetime,
    end_exclusive: datetime,
    price: str,
    specials: dict[datetime, Ohlc] | None = None,
    holes: set[datetime] | None = None,
) -> list[Candle]:
    """Flat 1m minutes at `price` from `first_open` (inclusive) to `end_exclusive`.

    `specials` overrides the (open, high, low, close) of single minutes; `holes` leaves
    minutes out of the series entirely (an explicit data hole, never padded).
    """
    rows: list[Candle] = []
    t = first_open
    while t < end_exclusive:
        if holes is None or t not in holes:
            o, h, low, c = (specials or {}).get(t, (price, price, price, price))
            rows.append(make_minute(SYMBOL, t, o, h, low, c, kind))
        t += MINUTE
    return rows


def strategy_bar(hour: int, *, o: str, h: str, low: str, c: str) -> Candle:
    """A 1h strategy bar opening at `hour`:00 and closing at :59:59.999."""
    opened = at(hour)
    return Candle(
        symbol=SYMBOL,
        interval="1h",
        open_time_utc=opened,
        close_time_utc=opened + HOUR - timedelta(milliseconds=1),
        open=D(o),
        high=D(h),
        low=D(low),
        close=D(c),
        volume=D("1"),
    )


def flat_bar(hour: int) -> Candle:
    return strategy_bar(hour, o="101.00", h="101.00", low="101.00", c="101.00")


def long_plan() -> TradePlan:
    return make_trade_plan(
        "LONG",
        entry_min="99.00",
        entry_max="101.00",
        stop_loss="98.00",
        tp1="104.00",
        tp2="108.00",
        signal_close_utc=SIGNAL_CLOSE,
        trade_plan_id="tp-ladder",
        signal_id="sig-ladder",
    )


def levels_for(plan: TradePlan, direction: str, filled: str = "0.5") -> ProtectiveLevels:
    result = protective_levels_for_fill(
        plan=plan, direction=direction, filled_quantity=D(filled), constraint_snapshot=SNAPSHOT
    )
    assert isinstance(result, ProtectiveLevels)
    return result


def long_state(*, plan: TradePlan | None = None) -> PlanState:
    chosen = plan if plan is not None else long_plan()
    return new_plan_state(
        plan=chosen,
        symbol=SYMBOL,
        direction="LONG",
        signal_close_utc=SIGNAL_CLOSE,
        price_tick_size=TICK,
        planned_quantity=D("0.5"),
        sized_realized_risk=D("1.50"),
        levels=levels_for(chosen, "LONG"),
    )


FILL_TRADE: Ohlc = ("100.40", "100.50", "99.90", "100.20")  # low 99.90 trades through 100.00


def long_fill_source(
    *,
    mark_specials: dict[datetime, Ohlc] | None = None,
    mark_holes: set[datetime] | None = None,
    end_exclusive: datetime | None = None,
) -> ListMinuteSource:
    """Trade minutes fill the LONG at 10:01; mark minutes are flat 101.00 unless overridden."""
    end = at(14) if end_exclusive is None else end_exclusive
    trade = minutes("trade", at(10), end, "101.00", {at(10, 1): FILL_TRADE})
    mark = minutes("mark", at(10), end, "101.00", mark_specials, mark_holes)
    return ListMinuteSource(trade={SYMBOL: trade}, mark={SYMBOL: mark})


def walk_hours(
    state: PlanState, source: ListMinuteSource, bars: list[Candle]
) -> tuple[PlanState, list[LifecycleEvent]]:
    """Advance bar by bar (previous close, this close], passing the closing bar."""
    previous = SIGNAL_CLOSE
    events: list[LifecycleEvent] = []
    current = state
    for bar in bars:
        current, new = advance(
            current,
            source=source,
            start_exclusive=previous,
            end_inclusive=bar.close_time_utc,
            bar=bar,
        )
        events.extend(new)
        previous = bar.close_time_utc
    return current, events


def record_of(state: PlanState, *, funding: str = "0") -> TradeRecord:
    return build_trade_record(
        state=state,
        strategy_version="v1",
        parameter_set_hash="b" * 64,
        cost_model=cost_model(),
        funding_amount=D(funding),
        funding_event_count=0,
        regime=None,
        constraints_extrapolated=False,
    )


TP1_TOUCH: Ohlc = ("101.00", "104.00", "101.00", "103.00")  # high exactly at TP1 104.00
TP2_TOUCH: Ohlc = ("101.00", "108.05", "101.00", "107.00")  # high through TP2 108.00
LADDER_MARKS = {at(11, 20): TP1_TOUCH, at(13, 10): TP2_TOUCH}
LADDER_BARS = [flat_bar(10), flat_bar(11), flat_bar(12), flat_bar(13)]


def ladder_run() -> tuple[PlanState, list[LifecycleEvent]]:
    return walk_hours(long_state(), long_fill_source(mark_specials=LADDER_MARKS), LADDER_BARS)


# --------------------------------------------------------------------------- #
# Task 1 (tracer): live-sized TP1, TP2, per-leg record.
# --------------------------------------------------------------------------- #


def test_levels_for_fill_use_the_live_sizing_helper_for_tp1_half() -> None:
    levels = levels_for(long_plan(), "LONG")
    assert levels.sl_trigger == D("98.00")
    assert levels.tp1_trigger == D("104.00")
    assert levels.tp2_trigger == D("108.00")
    assert levels.tp1_quantity == D("0.250")  # floor(0.5 x 0.5 to step 0.001)


def test_levels_floor_the_tp1_quantity_to_the_step() -> None:
    # 0.1575 x 0.5 = 0.07875 -> floored to 0.078 (never rounded up); 0.078 x 104.00 >= 5
    levels = levels_for(long_plan(), "LONG", filled="0.1575")
    assert levels.tp1_quantity == D("0.078")


def test_levels_snap_tp_triggers_toward_the_entry() -> None:
    long_levels = levels_for(
        make_trade_plan("LONG", tp1="104.05", tp2="108.05", signal_close_utc=SIGNAL_CLOSE),
        "LONG",
    )
    assert long_levels.tp1_trigger == D("104.00")  # LONG: down, toward the entry
    assert long_levels.tp2_trigger == D("108.00")
    short_levels = levels_for(
        make_trade_plan(
            "SHORT",
            stop_loss="102.00",
            tp1="96.05",
            tp2="92.05",
            signal_close_utc=SIGNAL_CLOSE,
        ),
        "SHORT",
    )
    assert short_levels.tp1_trigger == D("96.10")  # SHORT: up, toward the entry
    assert short_levels.tp2_trigger == D("92.10")
    assert short_levels.sl_trigger == D("102.00")


def test_unsizeable_tp1_is_a_no_trade_reject_with_the_live_reason() -> None:
    below_min_qty = protective_levels_for_fill(
        plan=long_plan(),
        direction="LONG",
        filled_quantity=D("0.001"),  # half = 0.0005 -> floors to 0
        constraint_snapshot=SNAPSHOT,
    )
    assert isinstance(below_min_qty, ProtectiveReject)
    assert below_min_qty.reason_code == "MIN_QTY_REJECT"
    below_notional = protective_levels_for_fill(
        plan=long_plan(),
        direction="LONG",
        filled_quantity=D("0.002"),  # TP1 0.001 x 104.00 = 0.104 < min notional 5
        constraint_snapshot=SNAPSHOT,
    )
    assert isinstance(below_notional, ProtectiveReject)
    assert below_notional.reason_code == "NOTIONAL_REJECT"


def test_tracer_tp1_half_on_bar_n2_then_tp2_on_bar_n4() -> None:
    source = long_fill_source(mark_specials=LADDER_MARKS)
    after_n2, events_n2 = walk_hours(long_state(), source, LADDER_BARS[:2])

    # Bar N+1 (10:00-10:59) filled at 10:01; bar N+2 (11:00-11:59) took TP1 at 11:20.
    assert after_n2.phase == "OPEN"
    assert after_n2.entry_time_utc == close_of(at(10, 1))
    assert after_n2.tp1_quantity == D("0.250")
    assert after_n2.tp1_price == D("104.00")
    assert after_n2.tp1_time_utc == close_of(at(11, 20))
    assert after_n2.remaining_quantity == D("0.250")
    assert after_n2.levels.sl_trigger == D("98.00")  # the stop does not move after TP1
    assert [e.kind for e in events_n2] == ["FILL", "TP1"]
    assert events_n2[1].quantity == D("0.250")
    assert events_n2[1].price == D("104.00")

    final, events = ladder_run()
    assert final.phase == "CLOSED"
    assert final.exit_kind == "TP2"
    assert final.exit_price == D("108.00")  # no price improvement past the trigger 108.05
    assert final.exit_time_utc == close_of(at(13, 10))
    assert final.remaining_quantity == D("0")
    assert final.gap_through_stop is False
    assert [e.kind for e in events] == ["FILL", "TP1", "EXIT"]
    assert events[2].exit_kind == "TP2"
    assert events[2].quantity == D("0.250")


def test_tracer_record_books_both_legs_with_per_leg_costs() -> None:
    final, _ = ladder_run()
    record = record_of(final)
    assert record.exit_kind == "TP2"
    assert record.quantity == D("0.5")
    assert record.tp1_quantity == D("0.250")
    assert record.tp1_price == D("104.00")
    assert record.tp1_time_utc == close_of(at(11, 20))
    assert record.gross_pnl == D("3.00")
    assert record.entry_fee == D("0.0250")
    assert record.exit_fee == D("0.0265")
    assert record.slippage_amount == D("0.0206")
    assert record.realized_pnl == D("2.9279")
    assert record.realized_risk == D("1.50")


def test_event_bookings_sum_to_the_record_realized_pnl() -> None:
    final, events = ladder_run()
    bookings = [booking_for_event(e, state=final, cost_model=cost_model()) for e in events]
    assert [b.kind for b in bookings] == ["FILL", "TP1", "EXIT"]
    assert [b.amount for b in bookings] == [D("-0.0350"), D("0.9818"), D("1.9811")]
    assert sum((b.amount for b in bookings), D("0")) == record_of(final).realized_pnl


# --------------------------------------------------------------------------- #
# Task 2: stop-first tie-break, TP1 then SL, same-minute TP1+TP2, fill minute, gaps.
#
# Hand oracles (LONG: entry 100.00, SL 98.00, TP1 104.00, TP2 108.00, filled 0.5):
#   TP1 then SL (F-102 worked example): TP1 0.250 at 104.00 (+1.00), SL 0.250 at 98.00 (-0.50)
#       gross 0.50 (the v1 simulator exited the whole 0.5 at TP1 inside the bar: +2.00)
#       exit_fee = 104.00 x 0.250 x 0.0005 + 98.00 x 0.250 x 0.0005 = 0.0130 + 0.01225 = 0.02525
#       slippage = 0.0100 + 104.00 x 0.250 x 0.0002 + 98.00 x 0.250 x 0.0010
#                = 0.0100 + 0.0052 + 0.0245 = 0.0397          (SL leg: exit_slippage_rate)
#       realized = 0.50 - 0.0250 - 0.02525 - 0.0397 = 0.41005
# --------------------------------------------------------------------------- #

FILL_CLOSE = close_of(at(10, 1))
SL_AND_TP1: Ohlc = ("101.00", "104.10", "97.95", "100.00")  # touches SL 98.00 and TP1 104.00
SL_AND_TP2: Ohlc = ("101.00", "108.05", "97.95", "100.00")  # touches SL 98.00 and TP2 108.00
TP1_AND_TP2: Ohlc = ("101.00", "108.05", "101.00", "107.00")  # touches TP1 and TP2, no SL
SL_GAP_DOWN: Ohlc = ("97.50", "97.80", "97.20", "97.60")  # opens below SL 98.00
SL_THROUGH: Ohlc = ("101.00", "101.00", "97.90", "98.50")  # opens above SL, trades through it


def fill_minute_state(mark_specials: dict[datetime, Ohlc] | None = None) -> PlanState:
    """An OPEN LONG filled at 10:01:59.999 (the window ends at the fill minute close)."""
    state, _ = advance(
        long_state(),
        source=long_fill_source(mark_specials=mark_specials),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=FILL_CLOSE,
        bar=None,
    )
    return state


def run_long(
    mark_specials: dict[datetime, Ohlc], bars: list[Candle] | None = None
) -> tuple[PlanState, list[LifecycleEvent]]:
    return walk_hours(
        long_state(), long_fill_source(mark_specials=mark_specials), bars or LADDER_BARS[:3]
    )


def short_plan() -> TradePlan:
    return make_trade_plan(
        "SHORT",
        entry_min="99.00",
        entry_max="101.00",
        stop_loss="102.00",
        tp1="96.00",
        tp2="92.00",
        signal_close_utc=SIGNAL_CLOSE,
        trade_plan_id="tp-short",
        signal_id="sig-short",
    )


def short_state() -> PlanState:
    plan = short_plan()
    return new_plan_state(
        plan=plan,
        symbol=SYMBOL,
        direction="SHORT",
        signal_close_utc=SIGNAL_CLOSE,
        price_tick_size=TICK,
        planned_quantity=D("0.5"),
        sized_realized_risk=D("1.50"),
        levels=levels_for(plan, "SHORT"),
    )


def run_short(mark_specials: dict[datetime, Ohlc]) -> tuple[PlanState, list[LifecycleEvent]]:
    """SHORT limit 100.00 fills at 10:01 (high 100.10); mark minutes flat 99.00 otherwise."""
    fill: Ohlc = ("99.80", "100.10", "99.70", "100.00")
    source = ListMinuteSource(
        trade={SYMBOL: minutes("trade", at(10), at(14), "99.00", {at(10, 1): fill})},
        mark={SYMBOL: minutes("mark", at(10), at(14), "99.00", mark_specials)},
    )
    bars = [strategy_bar(h, o="99.00", h="99.00", low="99.00", c="99.00") for h in (10, 11, 12)]
    return walk_hours(short_state(), source, bars)


def test_resolve_mark_minute_stop_wins_a_minute_that_touches_sl_and_tp1() -> None:
    state = fill_minute_state()
    minute = make_minute(SYMBOL, at(11, 20), *SL_AND_TP1, "mark")
    legs = resolve_mark_minute(state=state, mark_minute=minute, is_fill_minute=False)
    assert [(leg.kind, leg.price, leg.quantity) for leg in legs] == [("SL", D("98.00"), D("0.5"))]


def test_resolve_mark_minute_tp1_and_tp2_in_one_minute_are_ordered_tp1_then_tp2() -> None:
    state = fill_minute_state()
    minute = make_minute(SYMBOL, at(11, 20), *TP1_AND_TP2, "mark")
    legs = resolve_mark_minute(state=state, mark_minute=minute, is_fill_minute=False)
    assert [(leg.kind, leg.price, leg.quantity) for leg in legs] == [
        ("TP1", D("104.00"), D("0.250")),
        ("TP2", D("108.00"), D("0.250")),
    ]
    assert {leg.time_utc for leg in legs} == {close_of(at(11, 20))}


def test_resolve_mark_minute_on_the_fill_minute_only_the_stop_is_eligible() -> None:
    state = fill_minute_state()
    only_tp = make_minute(SYMBOL, at(10, 1), *TP1_AND_TP2, "mark")
    assert resolve_mark_minute(state=state, mark_minute=only_tp, is_fill_minute=True) == ()
    both = make_minute(SYMBOL, at(10, 1), *SL_AND_TP1, "mark")
    legs = resolve_mark_minute(state=state, mark_minute=both, is_fill_minute=True)
    assert [leg.kind for leg in legs] == ["SL"]


def test_one_minute_touching_sl_and_tp1_exits_the_whole_position_at_the_stop() -> None:
    final, events = run_long({at(11, 20): SL_AND_TP1})
    assert final.exit_kind == "SL"
    assert final.exit_price == D("98.00")
    assert final.tp1_quantity is None  # no TP1 leg was booked
    assert [e.kind for e in events] == ["FILL", "EXIT"]
    assert events[1].quantity == D("0.5")  # the whole position


def test_tp1_then_sl_keeps_the_tp1_leg_and_is_not_the_v1_whole_position_win() -> None:
    final, events = run_long({at(11, 20): TP1_TOUCH, at(12, 30): SL_AND_TP2})
    assert final.exit_kind == "SL"  # SL and TP2 in one minute: stop first
    assert final.exit_price == D("98.00")
    assert final.tp1_quantity == D("0.250")
    assert [e.kind for e in events] == ["FILL", "TP1", "EXIT"]
    assert events[2].quantity == D("0.250")  # only the remainder exits at the stop
    record = record_of(final)
    assert record.gross_pnl == D("0.50")  # +1.00 on TP1, -0.50 on the stop (v1 booked +2.00)
    assert record.exit_fee == D("0.02525")
    assert record.slippage_amount == D("0.0397")
    assert record.realized_pnl == D("0.41005")
    bookings = [booking_for_event(e, state=final, cost_model=cost_model()) for e in events]
    assert sum((b.amount for b in bookings), D("0")) == record.realized_pnl


def test_one_minute_touching_tp1_and_tp2_without_sl_books_both_at_that_minute() -> None:
    final, events = run_long({at(11, 20): TP1_AND_TP2})
    assert [e.kind for e in events] == ["FILL", "TP1", "EXIT"]
    assert events[1].time_utc == events[2].time_utc == close_of(at(11, 20))
    assert final.exit_kind == "TP2"
    assert final.tp1_time_utc == final.exit_time_utc == close_of(at(11, 20))


def test_fill_minute_that_touches_only_tp1_takes_no_profit_until_a_later_minute() -> None:
    at_fill = fill_minute_state({at(10, 1): TP1_TOUCH})
    assert at_fill.phase == "OPEN"
    assert at_fill.tp1_quantity is None  # a TP touch on the fill minute is deferred
    final, events = run_long({at(10, 1): TP1_TOUCH, at(10, 2): TP1_TOUCH}, [flat_bar(10)])
    assert [e.kind for e in events] == ["FILL", "TP1"]
    assert final.tp1_time_utc == close_of(at(10, 2))  # next minute, touched again


def test_fill_minute_that_touches_sl_and_tp1_stops_out_on_the_fill_minute() -> None:
    final, events = run_long({at(10, 1): SL_AND_TP1}, [flat_bar(10)])
    assert [e.kind for e in events] == ["FILL", "EXIT"]
    assert final.exit_kind == "SL"
    assert final.exit_time_utc == final.entry_time_utc == FILL_CLOSE


def test_stop_gap_books_the_adverse_mark_open_and_flags_it() -> None:
    final, events = run_long({at(11, 20): SL_GAP_DOWN})
    assert final.exit_kind == "SL"
    assert final.exit_price == D("97.50")  # min(trigger 98.00, mark open 97.50)
    assert final.gap_through_stop is True
    assert events[-1].price == D("97.50")
    record = record_of(final)
    assert record.gap_through_stop is True
    assert record.exit_price == D("97.50")
    assert record.gross_pnl == D("-1.25")  # (97.50 - 100.00) x 0.5


def test_a_stop_traded_through_from_above_exits_at_the_trigger_without_a_gap_flag() -> None:
    final, _ = run_long({at(11, 20): SL_THROUGH})
    assert final.exit_price == D("98.00")
    assert final.gap_through_stop is False


def test_stop_gap_after_tp1_exits_the_remainder_at_the_adverse_open() -> None:
    final, events = run_long({at(11, 20): TP1_TOUCH, at(12, 30): SL_GAP_DOWN})
    assert final.exit_price == D("97.50")
    assert final.gap_through_stop is True
    assert final.tp1_quantity == D("0.250")
    assert events[-1].quantity == D("0.250")


def test_short_tie_stop_first_and_gap_mirror() -> None:
    # SHORT: SL 102.00 is touched by a mark high, TP1 96.00 by a mark low.
    tie, _ = run_short({at(11, 20): ("99.00", "102.05", "95.95", "99.00")})
    assert tie.exit_kind == "SL"
    assert tie.exit_price == D("102.00")
    assert tie.tp1_quantity is None
    assert tie.gap_through_stop is False
    # Gap: the minute opens above the stop, the adverse price is the higher of trigger and open.
    gap, _ = run_short({at(11, 20): ("102.50", "102.80", "102.30", "102.40")})
    assert gap.exit_price == D("102.50")
    assert gap.gap_through_stop is True


def test_short_ladder_takes_tp1_then_tp2_on_mark_lows() -> None:
    final, events = run_short(
        {
            at(11, 20): ("99.00", "99.00", "96.00", "97.00"),  # low exactly at TP1 96.00
            at(11, 40): ("97.00", "97.00", "91.95", "92.50"),  # low through TP2 92.00
        }
    )
    assert [e.kind for e in events] == ["FILL", "TP1", "EXIT"]
    assert final.tp1_price == D("96.00")
    assert final.exit_kind == "TP2"
    assert final.exit_price == D("92.00")


# --------------------------------------------------------------------------- #
# Task 3: missing-minute fallback at the strategy-bar close, END_OF_DATA close.
#
# Fallback (D-12, D-33): while a position is open and the mark minutes of a strategy bar
# have a hole, minutes before the first missing one are walked normally; the rest of the
# bar resolves ONCE at the bar close from the strategy-bar range, stop-first, never mid-bar.
#
# END_OF_DATA hand oracle (LONG entry 100.00 qty 0.5, last mark close 100.40 at 11:59:59.999):
#   gross    = (100.40 - 100.00) x 0.5            = 0.20
#   exit fee = 100.40 x 0.5 x 0.0005              = 0.02510
#   exit slp = 100.40 x 0.5 x 0.0010 (exit_slippage_rate, forced market close) = 0.05020
#   slippage = 0.0100 + 0.05020                   = 0.0602
#   realized = 0.20 - 0.0250 - 0.02510 - 0.0602   = 0.0897
# TP1 then END_OF_DATA (TP1 0.250 at 104.00, remainder 0.250 closed at 100.40):
#   gross    = 1.00 + 0.250 x 0.40 = 1.10
#   exit fee = 0.0130 + 100.40 x 0.250 x 0.0005 = 0.0130 + 0.01255 = 0.02555
#   slippage = 0.0100 + 0.0052 + 100.40 x 0.250 x 0.0010 = 0.0100 + 0.0052 + 0.0251 = 0.0403
#   realized = 1.10 - 0.0250 - 0.02555 - 0.0403   = 1.00915
# --------------------------------------------------------------------------- #

HOLE_FROM_12_15 = {at(12, m) for m in range(15, 60)}  # minutes 12:00-12:14 exist, then a hole
FIRST_MISSING_12_15 = "2026-01-05T12:15:00+00:00"
BAR_12_CLOSE = at(13) - timedelta(milliseconds=1)


def run_with_hole(
    bar12: Candle,
    *,
    marks: dict[datetime, Ohlc] | None = None,
    holes: set[datetime] | None = None,
) -> tuple[PlanState, list[LifecycleEvent]]:
    source = long_fill_source(
        mark_specials=marks, mark_holes=HOLE_FROM_12_15 if holes is None else holes
    )
    return walk_hours(long_state(), source, [flat_bar(10), flat_bar(11), bar12])


def test_hole_resolves_the_rest_of_the_hour_at_the_bar_close_with_stop_first() -> None:
    bar12 = strategy_bar(12, o="101.00", h="101.50", low="97.90", c="99.00")
    final, events = run_with_hole(bar12)
    assert final.exit_kind == "SL"
    assert final.exit_price == D("98.00")
    assert final.exit_time_utc == BAR_12_CLOSE  # the bar close, never mid-bar
    assert final.fallback_applied is True
    assert final.coverage_note is not None and FIRST_MISSING_12_15 in final.coverage_note
    assert [e.kind for e in events] == ["FILL", "EXIT"]
    record = record_of(final)
    assert record.fallback_applied is True
    assert record.coverage_note == final.coverage_note


def test_hole_with_a_bar_range_that_touches_only_tp1_books_tp1_at_the_bar_close() -> None:
    bar12 = strategy_bar(12, o="101.00", h="104.50", low="100.50", c="103.00")
    final, events = run_with_hole(bar12)
    assert final.phase == "OPEN"
    assert final.tp1_time_utc == BAR_12_CLOSE
    assert final.tp1_price == D("104.00")
    assert final.remaining_quantity == D("0.250")
    assert final.fallback_applied is True
    assert [e.kind for e in events] == ["FILL", "TP1"]


def test_hole_with_a_bar_range_that_touches_tp2_books_tp1_then_tp2_at_the_bar_close() -> None:
    bar12 = strategy_bar(12, o="101.00", h="108.50", low="100.50", c="108.00")
    final, events = run_with_hole(bar12)
    assert [e.kind for e in events] == ["FILL", "TP1", "EXIT"]
    assert final.exit_kind == "TP2"
    assert final.tp1_time_utc == final.exit_time_utc == BAR_12_CLOSE


def test_minutes_before_the_hole_are_walked_and_minutes_after_it_are_not_used() -> None:
    # 12:10 (before the hole) touches TP1 on the mark series and books at its own minute.
    bar12 = strategy_bar(12, o="101.00", h="104.20", low="100.50", c="103.00")
    before, _ = run_with_hole(bar12, marks={at(12, 10): TP1_TOUCH})
    assert before.tp1_time_utc == close_of(at(12, 10))
    # 12:40 exists after the hole and would stop the position, but the rest of the hour
    # resolves from the bar range only (low 100.50 never reaches the stop).
    after, _ = run_with_hole(bar12, marks={at(12, 40): SL_THROUGH})
    assert after.phase == "OPEN"
    assert after.fallback_applied is True


def test_a_window_that_ends_mid_bar_never_resolves_a_hole() -> None:
    source = long_fill_source(mark_holes=HOLE_FROM_12_15)
    open_state, _ = walk_hours(long_state(), source, [flat_bar(10), flat_bar(11)])
    start = flat_bar(11).close_time_utc
    mid, mid_events = advance(
        open_state,
        source=source,
        start_exclusive=start,
        end_inclusive=close_of(at(12, 30)),
        bar=None,
    )
    # Nothing resolved, nothing flagged; only the settle marker advanced (12:00-12:14 walked,
    # the hole starts 12:15).
    assert mid.mark_settled_through_utc == at(12, 14)
    assert replace(mid, mark_settled_through_utc=open_state.mark_settled_through_utc) == open_state
    assert mid_events == ()
    bar12 = strategy_bar(12, o="101.00", h="101.50", low="97.90", c="99.00")
    resolved, _ = advance(
        open_state,
        source=source,
        start_exclusive=start,
        end_inclusive=bar12.close_time_utc,
        bar=bar12,
    )
    assert resolved.exit_kind == "SL"  # the hour resolves only when the bar-close window arrives
    assert resolved.exit_time_utc == BAR_12_CLOSE


def test_a_hole_in_an_earlier_mid_bar_window_is_found_at_the_bar_close() -> None:
    # WR-09: the 12:15-12:29 hole lies in a mid-bar window; the closing-bar window starts
    # after it, but the hole scan covers the whole bar, so the hour still falls back.
    holes = {at(12, m) for m in range(15, 30)}
    source = long_fill_source(mark_holes=holes)
    open_state, _ = walk_hours(long_state(), source, [flat_bar(10), flat_bar(11)])
    start = flat_bar(11).close_time_utc
    mid, _ = advance(
        open_state,
        source=source,
        start_exclusive=start,
        end_inclusive=close_of(at(12, 30)),
        bar=None,
    )
    bar12 = strategy_bar(12, o="101.00", h="101.50", low="97.90", c="99.00")
    resolved, _ = advance(
        mid,
        source=source,
        start_exclusive=close_of(at(12, 30)),
        end_inclusive=bar12.close_time_utc,
        bar=bar12,
    )
    assert resolved.fallback_applied is True
    assert (
        resolved.coverage_note is not None and "2026-01-05T12:15:00+00:00" in resolved.coverage_note
    )
    assert resolved.exit_kind == "SL"
    assert resolved.exit_time_utc == BAR_12_CLOSE


def test_a_hole_on_the_fill_minute_is_flagged_and_resolved_by_the_fallback() -> None:
    # WR-09: the fill minute (10:01) has no mark minute, so its stop check cannot run.
    source = long_fill_source(mark_holes={at(10, 1)})
    bar10 = strategy_bar(10, o="100.40", h="105.00", low="97.90", c="101.00")
    state, _ = advance(
        long_state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=bar10.close_time_utc,
        bar=bar10,
    )
    assert state.fallback_applied is True
    assert state.coverage_note is not None and "2026-01-05T10:01:00+00:00" in state.coverage_note
    assert state.exit_kind == "SL"  # the bar range reaches the stop; only the stop is eligible


def test_full_mark_coverage_never_uses_the_fallback_even_when_the_bar_range_is_wide() -> None:
    bar12 = strategy_bar(12, o="101.00", h="109.00", low="97.00", c="101.00")
    final, events = run_with_hole(bar12, holes=set())
    assert final.phase == "OPEN"  # the flat mark series never touches a level
    assert final.fallback_applied is False
    assert final.coverage_note is None
    assert [e.kind for e in events] == ["FILL"]


def test_fallback_in_the_fill_bar_resolves_only_the_stop() -> None:
    holes = {at(10, m) for m in range(30, 60)}
    wide_but_safe = strategy_bar(10, o="100.40", h="105.00", low="99.00", c="101.00")
    source = long_fill_source(mark_holes=holes)
    safe, safe_events = advance(
        long_state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=wide_but_safe.close_time_utc,
        bar=wide_but_safe,
    )
    assert safe.phase == "OPEN"  # the range reaches TP1 but the bar also holds pre-fill minutes
    assert safe.tp1_quantity is None
    assert safe.fallback_applied is True
    assert safe.coverage_note is not None and "2026-01-05T10:30:00+00:00" in safe.coverage_note
    assert [e.kind for e in safe_events] == ["FILL"]
    stopped_bar = strategy_bar(10, o="100.40", h="105.00", low="97.90", c="101.00")
    stopped, _ = advance(
        long_state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=stopped_bar.close_time_utc,
        bar=stopped_bar,
    )
    assert stopped.exit_kind == "SL"
    assert stopped.exit_time_utc == stopped_bar.close_time_utc


def test_resolve_fallback_hour_returns_stop_first_legs_and_a_coverage_note() -> None:
    state = walk_hours(long_state(), long_fill_source(), [flat_bar(10), flat_bar(11)])[0]
    bar12 = strategy_bar(12, o="101.00", h="104.50", low="97.90", c="99.00")
    resolution = resolve_fallback_hour(state=state, bar=bar12, first_missing_open_utc=at(12, 15))
    assert [(leg.kind, leg.price, leg.quantity) for leg in resolution.legs] == [
        ("SL", D("98.00"), D("0.5"))
    ]
    assert resolution.legs[0].time_utc == BAR_12_CLOSE
    assert FIRST_MISSING_12_15 in resolution.coverage_note
    assert "trade-price" in resolution.coverage_note


def test_resolve_fallback_hour_prices_a_gap_through_the_stop_at_the_bar_open() -> None:
    # WR-04: the position is already open when bar 12 opens beneath the 98.00 stop (gap down),
    # so the fallback books the open, not the trigger, and flags the gap.
    state = walk_hours(long_state(), long_fill_source(), [flat_bar(10), flat_bar(11)])[0]
    gapped = strategy_bar(12, o="96.50", h="97.00", low="95.00", c="96.00")
    resolution = resolve_fallback_hour(state=state, bar=gapped, first_missing_open_utc=at(12, 0))
    (stop,) = resolution.legs
    assert (stop.kind, stop.price, stop.gap_through_stop) == ("SL", D("96.50"), True)
    # An open above the stop (no gap) still books the trigger, unflagged.
    plain = strategy_bar(12, o="101.00", h="101.50", low="97.90", c="99.00")
    (plain_stop,) = resolve_fallback_hour(
        state=state, bar=plain, first_missing_open_utc=at(12, 0)
    ).legs
    assert (plain_stop.price, plain_stop.gap_through_stop) == (D("98.00"), False)


DATA_END = at(12)  # mid-run data end: the last mark minute at or before it opens at 11:59
EOD_MARKS: dict[datetime, Ohlc] = {at(11, 59): ("101.00", "101.00", "100.40", "100.40")}


def eod_state(mark_specials: dict[datetime, Ohlc]) -> tuple[PlanState, ListMinuteSource]:
    source = long_fill_source(mark_specials=mark_specials)
    state, _ = advance(
        long_state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=DATA_END,
        bar=None,
    )
    assert state.phase == "OPEN"
    return state, source


def test_end_of_data_closes_the_open_position_at_the_last_mark_close() -> None:
    state, source = eod_state(EOD_MARKS)
    closed, events = finalize_at_data_end(state, data_end_utc=DATA_END, source=source)
    assert closed.phase == "CLOSED"
    assert closed.exit_kind == "END_OF_DATA"
    assert closed.exit_price == D("100.40")
    assert closed.exit_time_utc == close_of(at(11, 59))
    assert closed.entry_kind == "ENTRY_FILLED"
    assert [e.kind for e in events] == ["EXIT"]
    assert events[0].exit_kind == "END_OF_DATA"
    assert events[0].quantity == D("0.5")
    record = record_of(closed)
    assert record.exit_kind == "END_OF_DATA"
    assert record.gross_pnl == D("0.20")
    assert record.exit_fee == D("0.02510")
    assert record.slippage_amount == D("0.0602")  # the exit leg uses exit_slippage_rate
    assert record.realized_pnl == D("0.0897")
    start = SIGNAL_CLOSE
    validate_trade_record(record, data_start_utc=start, data_end_utc=DATA_END)


def test_end_of_data_after_tp1_closes_only_the_remainder() -> None:
    state, source = eod_state({**EOD_MARKS, at(11, 20): TP1_TOUCH})
    closed, events = finalize_at_data_end(state, data_end_utc=DATA_END, source=source)
    assert closed.exit_kind == "END_OF_DATA"
    assert events[0].quantity == D("0.250")
    record = record_of(closed)
    assert record.tp1_quantity == D("0.250")
    assert record.gross_pnl == D("1.10")
    assert record.exit_fee == D("0.02555")
    assert record.slippage_amount == D("0.0403")
    assert record.realized_pnl == D("1.00915")


def test_end_of_data_looks_back_past_a_trailing_mark_hole() -> None:
    # The mark series stops at 10:30 while the data ends at 13:00: the close at 10:30 is used.
    holes = {at(10, 30) + MINUTE * k for k in range(1, 400)}
    source = long_fill_source(
        mark_specials={at(10, 30): ("101.00", "101.00", "100.40", "100.40")}, mark_holes=holes
    )
    state, _ = advance(
        long_state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=close_of(at(10, 30)),
        bar=None,
    )
    closed, _ = finalize_at_data_end(state, data_end_utc=at(13), source=source)
    assert closed.exit_time_utc == close_of(at(10, 30))
    assert closed.exit_price == D("100.40")


def test_end_of_data_is_never_dated_before_a_fallback_booked_tp1() -> None:
    # CR-01: a hole in the last bar books TP1 at the bar close (12:59:59.999) while the last
    # mark minute is 12:14; the forced close must not be dated before that TP1 leg.
    bar12 = strategy_bar(12, o="101.00", h="104.50", low="99.00", c="101.00")
    source = long_fill_source(mark_holes=HOLE_FROM_12_15)
    state, _ = walk_hours(long_state(), source, [flat_bar(10), flat_bar(11), bar12])
    assert state.phase == "OPEN"
    assert state.tp1_time_utc == BAR_12_CLOSE
    closed, events = finalize_at_data_end(state, data_end_utc=at(13), source=source)
    assert closed.exit_kind == "END_OF_DATA"
    assert closed.exit_time_utc == BAR_12_CLOSE
    assert events[0].time_utc == BAR_12_CLOSE
    validate_trade_record(record_of(closed), data_start_utc=SIGNAL_CLOSE, data_end_utc=at(13))


def test_end_of_data_without_a_source_or_a_mark_minute_fails_closed() -> None:
    state, source = eod_state({})
    with pytest.raises(ValueError, match="END_OF_DATA"):
        finalize_at_data_end(state, data_end_utc=DATA_END)
    empty = ListMinuteSource(trade={SYMBOL: []}, mark={SYMBOL: []})
    with pytest.raises(ValueError, match="mark"):
        end_of_data_exit(state=state, data_end_utc=DATA_END, source=empty)
    assert source is not None
