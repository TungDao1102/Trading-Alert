"""Per-leg cost booking tests for the record builder (Phase 14, plan 14-07, Task 3).

The simulated ledger bookings (`booking_for_event`) and the trade record
(`build_trade_record`) cost the same legs, so for every exit kind

    sum(bookings of FILL, TP1, EXIT events) + funding_amount == record.realized_pnl

exactly (Decimal, no rounding). The hand oracles for the individual legs live in
`tests/test_backtest_exits.py` (tracer, TP1-then-SL, END_OF_DATA, TP1-then-END_OF_DATA);
this module pins the reconciliation across SL, TP2, END_OF_DATA, TP1-then-SL and
TP1-then-END_OF_DATA, the slippage rate per leg kind, and the refusals:

    END_OF_DATA exit slippage = 100.40 x 0.5 x exit_slippage_rate
        rate 0.0010 -> 0.05020, rate 0.0020 -> 0.10040 (difference 0.05020)
    TP2 exit slippage uses expected_slippage and ignores exit_slippage_rate
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

import pytest
import src.backtest.records as records_api
from src.backtest.costs import CostModel
from src.backtest.lifecycle import (
    LifecycleEvent,
    PlanState,
    advance,
    cancel_plan,
    finalize_at_data_end,
)
from src.backtest.records import booking_for_event, build_trade_record

from tests.test_backtest_exits import (
    DATA_END,
    EOD_MARKS,
    SIGNAL_CLOSE,
    SL_AND_TP2,
    SL_THROUGH,
    TP1_TOUCH,
    D,
    Ohlc,
    at,
    cost_model,
    ladder_run,
    long_fill_source,
    long_state,
    record_of,
    run_long,
)

Case = Callable[[], tuple[PlanState, list[LifecycleEvent]]]


def _end_of_data_case(
    marks: dict[datetime, Ohlc],
) -> tuple[PlanState, list[LifecycleEvent]]:
    source = long_fill_source(mark_specials=marks)
    state, events = advance(
        long_state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=DATA_END,
        bar=None,
    )
    closed, more = finalize_at_data_end(state, data_end_utc=DATA_END, source=source)
    return closed, [*events, *more]


def _case_sl() -> tuple[PlanState, list[LifecycleEvent]]:
    return run_long({at(11, 20): SL_THROUGH})


def _case_tp2() -> tuple[PlanState, list[LifecycleEvent]]:
    return ladder_run()


def _case_end_of_data() -> tuple[PlanState, list[LifecycleEvent]]:
    return _end_of_data_case(EOD_MARKS)


def _case_tp1_then_sl() -> tuple[PlanState, list[LifecycleEvent]]:
    return run_long({at(11, 20): TP1_TOUCH, at(12, 30): SL_AND_TP2})


def _case_tp1_then_end_of_data() -> tuple[PlanState, list[LifecycleEvent]]:
    return _end_of_data_case({**EOD_MARKS, at(11, 20): TP1_TOUCH})


CASES: dict[str, Case] = {
    "SL": _case_sl,
    "TP2": _case_tp2,
    "END_OF_DATA": _case_end_of_data,
    "TP1-then-SL": _case_tp1_then_sl,
    "TP1-then-END_OF_DATA": _case_tp1_then_end_of_data,
}


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("funding", ["0", "0.0052", "-0.0031"])
def test_bookings_sum_to_realized_pnl_for_every_exit_kind(name: str, funding: str) -> None:
    state, events = CASES[name]()
    record = record_of(state, funding=funding)
    bookings = [booking_for_event(e, state=state, cost_model=cost_model()) for e in events]
    assert sum((b.amount for b in bookings), D("0")) + D(funding) == record.realized_pnl


def test_end_of_data_leg_uses_exit_slippage_rate_and_tp2_uses_expected_slippage() -> None:
    def model(exit_rate: str) -> CostModel:
        return dataclasses.replace(
            cost_model(), exit_slippage_rate=D(exit_rate), cost_model_hash=""
        )

    eod_state, _ = _end_of_data_case(EOD_MARKS)
    low = build_trade_record(
        state=eod_state,
        strategy_version="v1",
        parameter_set_hash="b" * 64,
        cost_model=model("0.0010"),
        funding_amount=D("0"),
        funding_event_count=0,
        regime=None,
        constraints_extrapolated=False,
    )
    high = build_trade_record(
        state=eod_state,
        strategy_version="v1",
        parameter_set_hash="b" * 64,
        cost_model=model("0.0020"),
        funding_amount=D("0"),
        funding_event_count=0,
        regime=None,
        constraints_extrapolated=False,
    )
    assert low.slippage_amount == D("0.0602")  # 0.0100 entry + 0.05020 exit
    assert high.slippage_amount == D("0.1104")  # 0.0100 entry + 0.10040 exit

    tp2_state, _ = ladder_run()
    tp2_low = build_trade_record(
        state=tp2_state,
        strategy_version="v1",
        parameter_set_hash="b" * 64,
        cost_model=model("0.0010"),
        funding_amount=D("0"),
        funding_event_count=0,
        regime=None,
        constraints_extrapolated=False,
    )
    tp2_high = build_trade_record(
        state=tp2_state,
        strategy_version="v1",
        parameter_set_hash="b" * 64,
        cost_model=model("0.0020"),
        funding_amount=D("0"),
        funding_event_count=0,
        regime=None,
        constraints_extrapolated=False,
    )
    assert tp2_low.slippage_amount == tp2_high.slippage_amount == D("0.0206")


@pytest.mark.parametrize("name", ["SL", "END_OF_DATA", "TP1-then-SL"])
def test_a_legacy_cost_model_without_exit_slippage_rate_is_refused(name: str) -> None:
    state, _ = CASES[name]()
    legacy = dataclasses.replace(cost_model(), exit_slippage_rate=None, cost_model_hash="")
    with pytest.raises(ValueError, match="exit_slippage_rate"):
        build_trade_record(
            state=state,
            strategy_version="v1",
            parameter_set_hash="b" * 64,
            cost_model=legacy,
            funding_amount=D("0"),
            funding_event_count=0,
            regime=None,
            constraints_extrapolated=False,
        )


@pytest.mark.parametrize("bad_kind", ["EOD", "TP1", "TP3", "STOP"])
def test_build_trade_record_refuses_an_exit_kind_outside_sl_tp2_end_of_data(
    bad_kind: str,
) -> None:
    state, _ = _case_sl()
    with pytest.raises(ValueError, match="exit_kind"):
        record_of(dataclasses.replace(state, exit_kind=bad_kind))


def test_cancel_and_pending_events_book_a_zero_amount_at_their_own_time() -> None:
    resting = long_state()
    cancelled, cancel_events = cancel_plan(
        resting, entry_kind="DAILY_STOP_CANCEL", at_utc=at(10, 30)
    )
    cancel_booking = booking_for_event(cancel_events[0], state=cancelled, cost_model=cost_model())
    assert cancel_booking.amount == D("0")
    assert cancel_booking.kind == records_api.BOOKING_CANCEL
    assert cancel_booking.time_utc == at(10, 30)

    pending, pending_events = finalize_at_data_end(resting, data_end_utc=at(12))
    pending_booking = booking_for_event(pending_events[0], state=pending, cost_model=cost_model())
    assert pending_booking.amount == Decimal("0")
    assert pending_booking.kind == records_api.BOOKING_PENDING
    assert pending_booking.trade_plan_id == resting.plan.trade_plan_id
