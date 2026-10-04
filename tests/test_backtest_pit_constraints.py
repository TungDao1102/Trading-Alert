"""Point-in-time constraint selection tests (Phase 14, plan 14-05, D-17, D-30, F-305).

History for BTCUSDT used throughout (hand-built, strings only):
    2026-03-01T00:00:00Z  tick 0.10  step 0.001  min_qty 0.001  min_notional 5
    2026-06-01T00:00:00Z  tick 0.20  step 0.001  min_qty 0.001  min_notional 5
Selection rule: the latest row with observed_at <= bar close. Before the first row the
earliest row is back-extrapolated and flagged (D-30). The snapshot handed to the live
risk pipeline carries `metadata_observed_at_utc` clamped to the bar close, so the
freshness gate sees age 0 against ttl 0 and no wall clock is involved (D-17).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.backtest.constraints import (
    ConstraintHistory,
    ConstraintHistoryError,
    ConstraintRow,
    PitConstraint,
    parse_constraint_row,
    select_constraints,
)
from src.backtest.costs import guard_rates_from_params
from src.core.types import AccountState
from src.domain.registry import load_parameter_set
from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates
from src.risk.gating import evaluate_risk
from src.risk.portfolio import resolve_absolute_thresholds

from tests.backtest_plan_helpers import D, make_trade_plan

MARCH = datetime(2026, 3, 1, tzinfo=UTC)
JUNE = datetime(2026, 6, 1, tzinfo=UTC)


def _row_dict(symbol: str, observed_at: str, tick: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "price_tick_size": tick,
        "quantity_step_size": "0.001",
        "min_quantity": "0.001",
        "min_notional": "5",
        "metadata_observed_at_utc": observed_at,
    }


def _history() -> ConstraintHistory:
    rows = [
        parse_constraint_row(_row_dict("BTCUSDT", "2026-06-01T00:00:00Z", "0.20")),
        parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "0.10")),
        parse_constraint_row(_row_dict("ETHUSDT", "2026-03-01T00:00:00Z", "0.01")),
    ]
    return ConstraintHistory.from_rows(rows)


def test_bar_between_two_rows_selects_the_earlier_one() -> None:
    pit = select_constraints(
        _history(), symbol="BTCUSDT", bar_close_utc=datetime(2026, 4, 10, tzinfo=UTC)
    )
    assert isinstance(pit, PitConstraint)
    assert pit.snapshot.price_tick_size == D("0.10")
    assert pit.observed_at_utc == MARCH
    assert pit.extrapolated is False


def test_bar_close_exactly_at_a_row_time_selects_that_row() -> None:
    pit = select_constraints(_history(), symbol="BTCUSDT", bar_close_utc=JUNE)
    assert pit.snapshot.price_tick_size == D("0.20")
    assert pit.observed_at_utc == JUNE
    assert pit.extrapolated is False


def test_bar_close_one_millisecond_before_a_row_still_selects_the_previous_row() -> None:
    pit = select_constraints(
        _history(), symbol="BTCUSDT", bar_close_utc=JUNE - timedelta(milliseconds=1)
    )
    assert pit.snapshot.price_tick_size == D("0.10")


def test_bar_after_the_last_row_selects_the_last_row() -> None:
    pit = select_constraints(
        _history(), symbol="BTCUSDT", bar_close_utc=datetime(2027, 1, 1, tzinfo=UTC)
    )
    assert pit.snapshot.price_tick_size == D("0.20")
    assert pit.extrapolated is False


def test_bar_before_the_first_row_back_extrapolates_the_earliest_row_with_a_flag() -> None:
    pit = select_constraints(
        _history(), symbol="BTCUSDT", bar_close_utc=datetime(2025, 12, 31, tzinfo=UTC)
    )
    assert pit.snapshot.price_tick_size == D("0.10")
    assert pit.observed_at_utc == MARCH
    assert pit.extrapolated is True


def test_symbols_do_not_leak_into_each_other() -> None:
    pit = select_constraints(_history(), symbol="ETHUSDT", bar_close_utc=JUNE)
    assert pit.snapshot.symbol == "ETHUSDT"
    assert pit.snapshot.price_tick_size == D("0.01")


def test_input_row_order_does_not_change_the_selection() -> None:
    ordered = [
        parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "0.10")),
        parse_constraint_row(_row_dict("BTCUSDT", "2026-06-01T00:00:00Z", "0.20")),
    ]
    forward = ConstraintHistory.from_rows(ordered)
    backward = ConstraintHistory.from_rows(list(reversed(ordered)))
    bar_close = datetime(2026, 5, 1, tzinfo=UTC)
    assert select_constraints(forward, symbol="BTCUSDT", bar_close_utc=bar_close) == (
        select_constraints(backward, symbol="BTCUSDT", bar_close_utc=bar_close)
    )


def test_snapshot_is_clamped_to_the_bar_close_and_the_true_observed_at_is_returned_apart() -> None:
    bar_close = datetime(2026, 4, 10, 11, 59, 59, 999000, tzinfo=UTC)
    pit = select_constraints(_history(), symbol="BTCUSDT", bar_close_utc=bar_close)
    assert pit.snapshot.metadata_observed_at_utc == bar_close
    assert pit.observed_at_utc == MARCH


def _risk_reason(pit: PitConstraint, bar_close: datetime) -> str:
    """Run the real evaluate_risk with ttl 0 and now = bar close; return the reason code."""
    params = load_parameter_set("trend-pullback", "baseline-v5").params
    min_stop_distance_rate, max_cost_to_risk = guard_rates_from_params(params)
    plan = make_trade_plan(signal_close_utc=bar_close)
    verdict = evaluate_risk(
        trade_plan=plan,
        candidate_position_side="LONG",
        account_state=AccountState(equity=D("10000"), risk_rate=D("0.005")),
        constraint_snapshot=pit.snapshot,
        open_positions=[],
        daily_loss_quote=D("0"),
        now_utc=bar_close,
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
            str(params["minimum_risk_utilization_after_rounding"])
        ),
        parameter_set=resolve_absolute_thresholds(parameter_set=params, equity=D("10000")),
    )
    return verdict.reason_code


def test_live_freshness_gate_passes_with_ttl_zero_and_no_wall_clock() -> None:
    bar_close = datetime(2026, 4, 10, 11, 59, 59, 999000, tzinfo=UTC)
    pit = select_constraints(_history(), symbol="BTCUSDT", bar_close_utc=bar_close)
    assert _risk_reason(pit, bar_close) != "STALE_CONSTRAINTS"
    assert _risk_reason(pit, bar_close) == "OK"


def test_live_freshness_gate_passes_for_a_back_extrapolated_row() -> None:
    bar_close = datetime(2025, 12, 31, 11, 59, 59, 999000, tzinfo=UTC)
    pit = select_constraints(_history(), symbol="BTCUSDT", bar_close_utc=bar_close)
    assert pit.extrapolated is True
    assert _risk_reason(pit, bar_close) != "STALE_CONSTRAINTS"


def test_a_symbol_without_rows_raises_naming_the_symbol() -> None:
    with pytest.raises(ConstraintHistoryError, match="SOLUSDT"):
        select_constraints(_history(), symbol="SOLUSDT", bar_close_utc=JUNE)


def test_duplicate_observed_at_for_one_symbol_raises() -> None:
    rows = [
        parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "0.10")),
        parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "0.20")),
    ]
    with pytest.raises(ConstraintHistoryError, match="BTCUSDT"):
        ConstraintHistory.from_rows(rows)


def test_the_same_observed_at_for_different_symbols_is_allowed() -> None:
    history = _history()
    assert (
        select_constraints(history, symbol="BTCUSDT", bar_close_utc=MARCH).observed_at_utc == MARCH
    )
    assert (
        select_constraints(history, symbol="ETHUSDT", bar_close_utc=MARCH).observed_at_utc == MARCH
    )


def test_a_naive_bar_close_is_refused() -> None:
    with pytest.raises(ValueError, match="UTC"):
        select_constraints(_history(), symbol="BTCUSDT", bar_close_utc=datetime(2026, 4, 10))


def test_a_float_value_raises_type_error() -> None:
    bad = _row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "0.10")
    bad["price_tick_size"] = 0.1
    with pytest.raises(TypeError, match="price_tick_size"):
        parse_constraint_row(bad)


def test_an_int_or_bool_value_raises_type_error() -> None:
    for bad_value in (1, True):
        bad = _row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "0.10")
        bad["min_notional"] = bad_value
        with pytest.raises(TypeError, match="min_notional"):
            parse_constraint_row(bad)


def test_parse_accepts_decimal_strings_and_iso_utc_timestamps() -> None:
    row = parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00+00:00", "0.10"))
    assert isinstance(row, ConstraintRow)
    assert row.price_tick_size == D("0.10")
    assert row.observed_at_utc == MARCH
    z_row = parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "0.10"))
    assert z_row.observed_at_utc == MARCH


def test_parse_refuses_naive_and_non_utc_timestamps() -> None:
    with pytest.raises(ValueError, match="UTC"):
        parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00", "0.10"))
    with pytest.raises(ValueError, match="UTC"):
        parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T07:00:00+07:00", "0.10"))


def test_parse_refuses_missing_keys_non_positive_and_non_finite_values() -> None:
    missing = _row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "0.10")
    del missing["min_quantity"]
    with pytest.raises(ConstraintHistoryError, match="min_quantity"):
        parse_constraint_row(missing)
    with pytest.raises(ValueError, match="price_tick_size"):
        parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "0"))
    with pytest.raises(ValueError, match="price_tick_size"):
        parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "NaN"))
    with pytest.raises(ValueError, match="price_tick_size"):
        parse_constraint_row(_row_dict("BTCUSDT", "2026-03-01T00:00:00Z", "not-a-number"))


def test_module_holds_no_ttl_value() -> None:
    source = (
        Path(__file__).resolve().parent.parent / "src" / "backtest" / "constraints.py"
    ).read_text(encoding="utf-8")
    assert "ttl" not in source.lower()
