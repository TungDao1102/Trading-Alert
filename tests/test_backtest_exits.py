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

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.backtest.costs import CostModel
from src.backtest.exits import (
    ProtectiveLevels,
    ProtectiveReject,
    protective_levels_for_fill,
    resolve_mark_minute,
)
from src.backtest.lifecycle import LifecycleEvent, PlanState, advance, new_plan_state
from src.backtest.records import TradeRecord, booking_for_event, build_trade_record
from src.backtest.series import ListMinuteSource
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
