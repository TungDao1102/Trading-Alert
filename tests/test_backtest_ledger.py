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
