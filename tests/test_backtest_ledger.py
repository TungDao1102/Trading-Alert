"""Simulated ledger tests (Phase 14, plan 14-05, D-18, D-32, F-305).

The tracer proves the whole chain on hand arithmetic: a stopped-out trade is booked
as two dated amounts, the ledger reaches DAILY_STOP, and the UNCHANGED risk pipeline
(`evaluate_risk`) then blocks the next candidate with DAILY_STOP_BLOCK.

Hand values (baseline-v5 rates, initial equity 10000):
    daily_loss_stop_threshold    0.01  x 10000 = 100
    daily_loss_warning_threshold 0.005 x 10000 = 50
    cluster_cap                  0.005 x 10000 = 50
    max_aggregate_open_risk      0.01  x 10000 = 100
    bookings: -2.50 (entry fee + slippage) and -98.00 (SL leg net)
    equity    = 10000 - 2.50 - 98.00 = 9899.50
    day loss  = 2.50 + 98.00 = 100.50 >= 100 -> DAILY_STOP
Day 2 (Task 2): a day-1 loss of 120 leaves equity 9880 and the day-2 thresholds
    0.01 x 9880 = 98.80 stop and 0.005 x 9880 = 49.40 warning.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.backtest import ledger as ledger_mod
from src.backtest.costs import guard_rates_from_params
from src.backtest.ledger import (
    Ledger,
    apply_booking,
    cancel_resting_required,
    daily_loss_quote,
    daily_state,
)
from src.backtest.records import BOOKING_EXIT, BOOKING_FILL, Booking
from src.core.types import AccountState
from src.domain.enums import DailyState
from src.domain.registry import load_parameter_set
from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates
from src.risk.gating import evaluate_risk
from src.risk.types import ConstraintSnapshot, OpenPosition, PortfolioVerdict

from tests.backtest_plan_helpers import D, make_trade_plan

PARAMS = load_parameter_set("trend-pullback", "baseline-v5").params
START = datetime(2026, 1, 5, 9, 59, 59, 999000, tzinfo=UTC)
FILL_TIME = datetime(2026, 1, 5, 10, 1, 59, 999000, tzinfo=UTC)
EXIT_TIME = datetime(2026, 1, 5, 10, 40, 59, 999000, tzinfo=UTC)
NEXT_SIGNAL = datetime(2026, 1, 5, 11, 59, 59, 999000, tzinfo=UTC)


def _booking(time_utc: datetime, amount: str, kind: str = BOOKING_FILL) -> Booking:
    return Booking(
        time_utc=time_utc,
        symbol="BTCUSDT",
        trade_plan_id="tp-1",
        amount=D(amount),
        kind=kind,
    )


def _fresh_ledger() -> Ledger:
    return Ledger.start(equity=D("10000"), parameter_set_params=PARAMS, at_utc=START)


def _stopped_out_ledger() -> Ledger:
    ledger = apply_booking(_fresh_ledger(), _booking(FILL_TIME, "-2.50"))
    return apply_booking(ledger, _booking(EXIT_TIME, "-98.00", BOOKING_EXIT))


def _risk_verdict(
    ledger: Ledger, open_positions: list[OpenPosition] | None = None
) -> PortfolioVerdict:
    """Run the real evaluate_risk for a fresh LONG candidate at the next signal close."""
    plan = make_trade_plan(trade_plan_id="tp-2", signal_id="sig-2", signal_close_utc=NEXT_SIGNAL)
    snapshot = ConstraintSnapshot(
        symbol="BTCUSDT",
        price_tick_size=D("0.10"),
        quantity_step_size=D("0.001"),
        min_quantity=D("0.001"),
        min_notional=D("5"),
        metadata_observed_at_utc=NEXT_SIGNAL,
    )
    min_stop_distance_rate, max_cost_to_risk = guard_rates_from_params(PARAMS)
    return evaluate_risk(
        trade_plan=plan,
        candidate_position_side="LONG",
        account_state=AccountState(equity=ledger.equity, risk_rate=D("0.005")),
        constraint_snapshot=snapshot,
        open_positions=[] if open_positions is None else open_positions,
        daily_loss_quote=daily_loss_quote(ledger),
        now_utc=NEXT_SIGNAL,
        ttl=timedelta(0),
        cost_rates=CostRates(
            fee_rate_entry=D("0.0005"),
            entry_slippage_rate=D("0.0001"),
            fee_rate_exit=D("0.0005"),
            exit_slippage_rate=D("0.0003"),
            fee_source=FEE_SOURCE_PARAMETER,
        ),
        min_stop_distance_rate=min_stop_distance_rate,
        max_cost_to_risk=max_cost_to_risk,
        minimum_risk_utilization_after_rounding=Decimal(
            str(PARAMS["minimum_risk_utilization_after_rounding"])
        ),
        parameter_set=ledger.thresholds,
    )


# --------------------------------------------------------------------------- #
# Tracer: bookings -> DAILY_STOP -> evaluate_risk blocks the next signal.
# --------------------------------------------------------------------------- #


def test_fresh_ledger_resolves_thresholds_against_initial_equity() -> None:
    ledger = _fresh_ledger()
    assert ledger.equity == D("10000")
    assert ledger.initial_equity == D("10000")
    assert ledger.thresholds["daily_loss_stop_threshold"] == D("100")
    assert ledger.thresholds["daily_loss_warning_threshold"] == D("50")
    assert daily_loss_quote(ledger) == D("0")
    assert daily_state(ledger) is DailyState.NORMAL
    assert cancel_resting_required(ledger) is False


def test_stopped_out_trade_reaches_daily_stop() -> None:
    ledger = _stopped_out_ledger()
    assert ledger.equity == D("9899.50")
    assert daily_loss_quote(ledger) == D("100.50")
    assert daily_state(ledger) is DailyState.DAILY_STOP
    assert cancel_resting_required(ledger) is True


def test_first_booking_alone_is_still_normal() -> None:
    ledger = apply_booking(_fresh_ledger(), _booking(FILL_TIME, "-2.50"))
    assert ledger.equity == D("9997.50")
    assert daily_loss_quote(ledger) == D("2.50")
    assert daily_state(ledger) is DailyState.NORMAL
    assert cancel_resting_required(ledger) is False


def test_evaluate_risk_blocks_next_signal_with_daily_stop_block() -> None:
    verdict = _risk_verdict(_stopped_out_ledger())
    assert verdict.is_no_trade
    assert verdict.reason_code == "DAILY_STOP_BLOCK"
    assert verdict.daily_state is DailyState.DAILY_STOP


def test_evaluate_risk_is_not_blocked_by_the_daily_state_before_the_second_booking() -> None:
    ledger = apply_booking(_fresh_ledger(), _booking(FILL_TIME, "-2.50"))
    verdict = _risk_verdict(ledger)
    assert verdict.reason_code != "DAILY_STOP_BLOCK"
    assert not verdict.is_no_trade
    assert verdict.daily_state is DailyState.NORMAL


def test_profit_is_not_a_loss_and_lifts_equity() -> None:
    ledger = apply_booking(_fresh_ledger(), _booking(EXIT_TIME, "10.00", BOOKING_EXIT))
    assert ledger.equity == D("10010.00")
    assert daily_loss_quote(ledger) == D("0")
    assert daily_state(ledger) is DailyState.NORMAL


def test_apply_booking_returns_a_new_ledger_and_leaves_the_old_one_untouched() -> None:
    before = _fresh_ledger()
    after = apply_booking(before, _booking(FILL_TIME, "-2.50"))
    assert before.equity == D("10000")
    assert after.equity == D("9997.50")
    assert after is not before
    with pytest.raises(AttributeError):
        before.equity = D("1")  # type: ignore[misc]


def test_a_booking_earlier_than_the_last_one_is_refused() -> None:
    ledger = apply_booking(_fresh_ledger(), _booking(EXIT_TIME, "-98.00", BOOKING_EXIT))
    with pytest.raises(ValueError, match="non-decreasing"):
        apply_booking(ledger, _booking(FILL_TIME, "-2.50"))


def test_same_instant_bookings_are_allowed() -> None:
    ledger = apply_booking(_fresh_ledger(), _booking(EXIT_TIME, "-1.00", BOOKING_EXIT))
    ledger = apply_booking(ledger, _booking(EXIT_TIME, "-2.00", BOOKING_EXIT))
    assert ledger.equity == D("9997.00")


def test_a_non_decimal_amount_is_refused() -> None:
    bad = Booking(
        time_utc=FILL_TIME,
        symbol="BTCUSDT",
        trade_plan_id="tp-1",
        amount="-2.50",  # type: ignore[arg-type]
        kind=BOOKING_FILL,
    )
    with pytest.raises(TypeError):
        apply_booking(_fresh_ledger(), bad)


# --------------------------------------------------------------------------- #
# Task 2: UTC day roll, exposure projection, exhausted equity.
# --------------------------------------------------------------------------- #

DAY1_LOSS_TIME = datetime(2026, 1, 5, 15, 0, 0, tzinfo=UTC)
DAY2_START = datetime(2026, 1, 6, 0, 0, 0, tzinfo=UTC)


def _day1_loss_ledger() -> Ledger:
    """Loss of 120 on day 1 -> equity 9880, DAILY_STOP (120 >= 100)."""
    return apply_booking(_fresh_ledger(), _booking(DAY1_LOSS_TIME, "-120.00", BOOKING_EXIT))


def test_day1_loss_of_120_is_daily_stop() -> None:
    ledger = _day1_loss_ledger()
    assert ledger.equity == D("9880.00")
    assert daily_state(ledger) is DailyState.DAILY_STOP


def test_roll_to_next_utc_day_resets_the_day_and_reresolves_thresholds() -> None:
    rolled = ledger_mod.roll_to(_day1_loss_ledger(), DAY2_START)
    assert rolled.day_pnl == D("0")
    assert rolled.equity_at_day_start == D("9880.00")
    assert rolled.equity == D("9880.00")
    assert rolled.thresholds["daily_loss_stop_threshold"] == D("98.80")
    assert rolled.thresholds["daily_loss_warning_threshold"] == D("49.40")
    assert daily_loss_quote(rolled) == D("0")
    assert daily_state(rolled) is DailyState.NORMAL
    assert cancel_resting_required(rolled) is False


def test_roll_to_within_the_same_day_changes_nothing() -> None:
    ledger = _day1_loss_ledger()
    later = datetime(2026, 1, 5, 23, 59, 59, 999000, tzinfo=UTC)
    assert ledger_mod.roll_to(ledger, later) == ledger


def test_roll_to_an_earlier_day_is_refused() -> None:
    rolled = ledger_mod.roll_to(_day1_loss_ledger(), DAY2_START)
    with pytest.raises(ValueError, match="backwards"):
        ledger_mod.roll_to(rolled, datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC))


def test_a_booking_exactly_at_midnight_belongs_to_the_new_day() -> None:
    ledger = apply_booking(_day1_loss_ledger(), _booking(DAY2_START, "-10.00", BOOKING_EXIT))
    assert ledger.day_pnl == D("-10.00")
    assert ledger.equity_at_day_start == D("9880.00")
    assert ledger.equity == D("9870.00")
    assert daily_loss_quote(ledger) == D("10.00")
    assert ledger.thresholds["daily_loss_stop_threshold"] == D("98.80")


def test_a_booking_just_before_midnight_stays_on_the_old_day() -> None:
    just_before = DAY2_START - timedelta(milliseconds=1)
    ledger = apply_booking(_day1_loss_ledger(), _booking(just_before, "-10.00", BOOKING_EXIT))
    assert ledger.equity_at_day_start == D("10000")
    assert daily_loss_quote(ledger) == D("130.00")


def test_thresholds_are_reresolved_only_at_a_day_roll_not_per_booking() -> None:
    ledger = apply_booking(_fresh_ledger(), _booking(FILL_TIME, "-30.00", BOOKING_EXIT))
    assert ledger.equity == D("9970.00")
    assert ledger.thresholds["daily_loss_stop_threshold"] == D("100")


def test_resting_exposure_projects_open_risk_with_zero_daily_pnl() -> None:
    ledger = ledger_mod.register_exposure(
        _fresh_ledger(),
        trade_plan_id="tp-1",
        symbol="BTCUSDT",
        position_side="LONG",
        open_risk=D("50"),
    )
    assert ledger_mod.open_positions_for_risk(ledger) == [
        OpenPosition(
            symbol="BTCUSDT",
            position_side="LONG",
            open_risk=D("50"),
            daily_pnl_contribution=D("0"),
        )
    ]


def test_update_exposure_after_tp1_scales_open_risk_by_remaining_over_filled() -> None:
    ledger = ledger_mod.register_exposure(
        _fresh_ledger(),
        trade_plan_id="tp-1",
        symbol="BTCUSDT",
        position_side="LONG",
        open_risk=D("50"),
    )
    ledger = ledger_mod.update_exposure(
        ledger,
        trade_plan_id="tp-1",
        filled_quantity=D("0.5"),
        remaining_quantity=D("0.25"),
    )
    (position,) = ledger_mod.open_positions_for_risk(ledger)
    assert position.open_risk == D("25")


def test_remove_exposure_drops_the_projection() -> None:
    ledger = ledger_mod.register_exposure(
        _fresh_ledger(),
        trade_plan_id="tp-1",
        symbol="BTCUSDT",
        position_side="LONG",
        open_risk=D("50"),
    )
    ledger = ledger_mod.remove_exposure(ledger, trade_plan_id="tp-1")
    assert ledger_mod.open_positions_for_risk(ledger) == []


def test_projections_are_sorted_by_symbol_then_side_regardless_of_registration_order() -> None:
    ledger = _fresh_ledger()
    for plan_id, symbol, side in (
        ("tp-c", "ETHUSDT", "SHORT"),
        ("tp-a", "ETHUSDT", "LONG"),
        ("tp-b", "BTCUSDT", "SHORT"),
    ):
        ledger = ledger_mod.register_exposure(
            ledger,
            trade_plan_id=plan_id,
            symbol=symbol,
            position_side=side,
            open_risk=D("10"),
        )
    keys = [(p.symbol, p.position_side) for p in ledger_mod.open_positions_for_risk(ledger)]
    assert keys == [("BTCUSDT", "SHORT"), ("ETHUSDT", "LONG"), ("ETHUSDT", "SHORT")]


def test_duplicate_registration_and_unknown_updates_fail_loudly() -> None:
    ledger = ledger_mod.register_exposure(
        _fresh_ledger(),
        trade_plan_id="tp-1",
        symbol="BTCUSDT",
        position_side="LONG",
        open_risk=D("50"),
    )
    with pytest.raises(ValueError, match="already registered"):
        ledger_mod.register_exposure(
            ledger,
            trade_plan_id="tp-1",
            symbol="BTCUSDT",
            position_side="LONG",
            open_risk=D("50"),
        )
    with pytest.raises(ValueError, match="unknown"):
        ledger_mod.update_exposure(
            ledger,
            trade_plan_id="tp-9",
            filled_quantity=D("0.5"),
            remaining_quantity=D("0.25"),
        )
    with pytest.raises(ValueError, match="unknown"):
        ledger_mod.remove_exposure(ledger, trade_plan_id="tp-9")


def test_resting_exposure_counts_toward_the_portfolio_gates_in_evaluate_risk() -> None:
    """A resting 50 of risk plus the candidate exceeds the 50 cluster cap (D-18, D035)."""
    ledger = ledger_mod.register_exposure(
        _fresh_ledger(),
        trade_plan_id="tp-1",
        symbol="BTCUSDT",
        position_side="LONG",
        open_risk=D("50"),
    )
    verdict = _risk_verdict(ledger, ledger_mod.open_positions_for_risk(ledger))
    assert verdict.is_no_trade
    assert verdict.reason_code == "CLUSTER_CAP_REJECT"


def test_equity_positive_is_false_at_zero_or_negative_equity() -> None:
    assert ledger_mod.equity_positive(_fresh_ledger()) is True
    broke = apply_booking(_fresh_ledger(), _booking(FILL_TIME, "-10000.00", BOOKING_EXIT))
    assert broke.equity == D("0.00")
    assert ledger_mod.equity_positive(broke) is False
    below = apply_booking(broke, _booking(EXIT_TIME, "-5.00", BOOKING_EXIT))
    assert below.equity == D("-5.00")
    assert ledger_mod.equity_positive(below) is False


def test_roll_to_with_exhausted_equity_fails_closed_to_daily_stop() -> None:
    broke = apply_booking(_fresh_ledger(), _booking(FILL_TIME, "-10000.00", BOOKING_EXIT))
    rolled = ledger_mod.roll_to(broke, DAY2_START)
    assert ledger_mod.equity_positive(rolled) is False
    assert daily_state(rolled) is DailyState.DAILY_STOP
    assert cancel_resting_required(rolled) is True


def test_start_refuses_non_positive_equity() -> None:
    with pytest.raises(ValueError):
        Ledger.start(equity=D("0"), parameter_set_params=PARAMS, at_utc=START)
