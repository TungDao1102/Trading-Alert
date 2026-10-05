"""Typed run summary emitted by the v2 engine (Phase 14, plan 14-09, Task 2).

`run_summary` is the producer side of the experiment record (D-22): every protocol-mandated
run fact, as JSON-native values with sorted keys. Counts are derived from the records the
engine emitted plus its NO_TRADE counter, so a test recounts the trades to prove the
summary cannot drift from them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.backtest import engine
from src.backtest.engine import simulate
from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION
from src.core.types import SetupResult
from src.domain.enums import DailyState
from src.risk.types import PortfolioVerdict, SizedResult

from tests.backtest_case_helpers import (
    DATA_END,
    DATA_START,
    SIGNAL_CLOSE,
    SYMBOL,
    at,
    bar_row,
    fixed_risk_fn,
    flat_minutes,
    funding_row,
    make_case,
    minute_row,
    scripted_plan,
)

NEXT_CLOSE = SIGNAL_CLOSE + timedelta(hours=1)
DATASET_ID = "ab" * 32


def go_through(symbol: str, open_time: datetime) -> dict[str, str]:
    """A trade minute that trades through a 100.00 LONG limit."""
    return minute_row(symbol, open_time, "100.20", "100.30", "99.80", "100.00", kind="trade")


def gap_stop(symbol: str, open_time: datetime) -> dict[str, str]:
    """A mark minute that opens below the 98.00 LONG stop (a gap through the stop)."""
    return minute_row(symbol, open_time, "97.50", "97.60", "97.40", "97.55", kind="mark")


def dispatching_risk_fn() -> Any:
    """Reject `sig-risk`, size `sig-tp1` at 0.001 (its TP1 leg floors to zero), size the rest."""
    sizer = fixed_risk_fn("0.5", "1.50")

    def risk_fn(**kwargs: Any) -> PortfolioVerdict:
        signal_id = kwargs["trade_plan"].signal_id
        if signal_id == "sig-risk":
            return PortfolioVerdict(
                is_no_trade=True,
                sized=None,
                reason_code="CLUSTER_CAP_REJECT",
                daily_state=DailyState.NORMAL,
            )
        if signal_id == "sig-tp1":
            sized = SizedResult(
                is_no_trade=False,
                quantity=Decimal("0.001"),
                quantity_before_rounding=Decimal("0.001"),
                quantity_after_rounding=Decimal("0.001"),
                quantization_decision="ACCEPTED",
                realized_risk=Decimal("0.003"),
            )
            return PortfolioVerdict(
                is_no_trade=False, sized=sized, reason_code="OK", daily_state=DailyState.NORMAL
            )
        return sizer(**kwargs)

    return risk_fn


def reasons_case() -> dict[str, Any]:
    """BTC rests then conflicts; ETH is risk-rejected; SOL has an unsizeable TP1 leg."""
    return make_case(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        scripted=[
            scripted_plan("BTCUSDT", SIGNAL_CLOSE, "sig-1"),
            scripted_plan("BTCUSDT", NEXT_CLOSE, "sig-conflict"),
            scripted_plan("ETHUSDT", SIGNAL_CLOSE, "sig-risk"),
            scripted_plan("SOLUSDT", SIGNAL_CLOSE, "sig-tp1"),
        ],
        trade_minutes=flat_minutes("BTCUSDT", at(10, 0), 90, "105.00", kind="trade"),
        mark_minutes=flat_minutes("BTCUSDT", at(10, 0), 90, "100.00", kind="mark"),
    )


def counters_case() -> dict[str, Any]:
    """BTC held to data end, ETH resting to data end, SOL stopped out through a gap."""
    return make_case(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        scripted=[
            scripted_plan("BTCUSDT", SIGNAL_CLOSE, "sig-btc"),
            scripted_plan("ETHUSDT", SIGNAL_CLOSE, "sig-eth"),
            scripted_plan("SOLUSDT", SIGNAL_CLOSE, "sig-sol"),
        ],
        trade_minutes=[
            *flat_minutes("BTCUSDT", at(10, 0), 1, "105.00", kind="trade"),
            go_through("BTCUSDT", at(10, 1)),
            *flat_minutes("ETHUSDT", at(10, 0), 120, "105.00", kind="trade"),
            *flat_minutes("SOLUSDT", at(10, 0), 1, "105.00", kind="trade"),
            go_through("SOLUSDT", at(10, 1)),
        ],
        mark_minutes=[
            *flat_minutes("BTCUSDT", at(10, 0), 120, "100.00", kind="mark"),
            *flat_minutes("ETHUSDT", at(10, 0), 120, "100.00", kind="mark"),
            *flat_minutes("SOLUSDT", at(10, 0), 40, "100.00", kind="mark"),
            gap_stop("SOLUSDT", at(10, 40)),
        ],
        dataset_id=DATASET_ID,
    )


def test_no_trade_counts_name_each_reject_conflict_and_tp1_sizing_reason() -> None:
    output = simulate(reasons_case(), risk_fn=dispatching_risk_fn())

    counts = output["run_summary"]["no_trade_counts"]
    assert counts == {
        "CLUSTER_CAP_REJECT": 1,
        "CONFLICT_WITH_OPEN_POSITION": 1,
        "MIN_QTY_REJECT": 1,
    }
    assert list(counts) == sorted(counts)
    # The rejects are records too; the conflict is a counter only.
    assert sorted(t["reason_code"] for t in output["trades"] if t["entry_kind"] == "REJECT") == [
        "CLUSTER_CAP_REJECT",
        "MIN_QTY_REJECT",
    ]


def test_strategy_no_trade_reasons_are_counted_per_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    reasons = iter(["NO_TRADE_REGIME", "NO_TRADE_REGIME", "NO_TRADE_REGIME", "DATA_STALE"])

    def spy(**_: Any) -> SetupResult:
        return SetupResult(is_no_trade=True, reason_code=next(reasons))

    monkeypatch.setattr(engine, "evaluate", spy)
    rows = [
        bar_row(SYMBOL, DATA_START + timedelta(hours=i), "100", "101", "99", "100")
        for i in range(4)
    ]
    output = simulate(make_case(strategy_bars=rows), risk_fn=fixed_risk_fn("0.5", "1.5"))

    assert output["run_summary"]["no_trade_counts"] == {"DATA_STALE": 1, "NO_TRADE_REGIME": 3}
    assert output["run_summary"]["plan_source"] == "STRATEGY"


def test_run_facts_echo_the_protocol_constants_and_the_inputs() -> None:
    output = simulate(counters_case(), risk_fn=fixed_risk_fn("0.5", "1.50"))
    summary = output["run_summary"]

    assert summary["intrabar_tie_break"] == "STOP_FIRST"
    assert summary["timeframe"] == "1h"
    assert summary["context_timeframe"] == "4h"
    assert summary["strategy_window_bars"] == 1000
    assert summary["context_window_bars"] == 300
    assert summary["simulator_semantics_version"] == SIMULATOR_SEMANTICS_VERSION == "2.0.0"
    assert summary["plan_source"] == "SCRIPTED"
    assert summary["dataset_id"] == DATASET_ID
    assert summary["data_window"] == {
        "start_utc": DATA_START.isoformat(),
        "end_utc": DATA_END.isoformat(),
    }
    assert summary["allowed_gaps_used"] == []
    note = summary["tie_order_note"]
    assert "(time, symbol)" in note
    assert "bias" in note


def test_dataset_id_is_none_when_the_case_has_no_dataset() -> None:
    output = simulate(make_case(scripted=[], dataset_id=None), risk_fn=fixed_risk_fn("0.5", "1.50"))

    assert output["run_summary"]["dataset_id"] is None
    assert output["run_summary"]["data_window"]["start_utc"] == DATA_START.isoformat()


def test_flag_counts_equal_a_recount_of_the_emitted_records() -> None:
    output = simulate(counters_case(), risk_fn=fixed_risk_fn("0.5", "1.50"))
    summary = output["run_summary"]
    trades = output["trades"]

    assert summary["end_of_data_count"] == sum(t["exit_kind"] == "END_OF_DATA" for t in trades) == 1
    assert (
        summary["pending_at_data_end_count"]
        == sum(t["entry_kind"] == "PENDING_AT_DATA_END" for t in trades)
        == 1
    )
    assert summary["gap_through_stop_count"] == sum(t["gap_through_stop"] for t in trades) == 1
    assert summary["fallback_count"] == sum(t["fallback_applied"] for t in trades)
    assert summary["constraints_extrapolated_count"] == sum(
        t["constraints_extrapolated"] for t in trades
    )
    assert summary["touch_no_fill_total"] == sum(t["touch_no_fill_count"] for t in trades)
    for key in (
        "fallback_count",
        "constraints_extrapolated_count",
        "touch_no_fill_total",
    ):
        assert isinstance(summary[key], int)
        assert not isinstance(summary[key], bool)


def test_a_touch_without_a_fill_is_summed_into_touch_no_fill_total() -> None:
    # The first trade minute touches the 99.00-101.00 limit zone price exactly at the limit
    # without trading through it; the second trades through. The recount ties the totals.
    case = make_case(
        scripted=[scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-1")],
        trade_minutes=[
            minute_row(SYMBOL, at(10, 0), "100.60", "100.70", "100.00", "100.30", kind="trade"),
            go_through(SYMBOL, at(10, 1)),
        ],
        mark_minutes=flat_minutes(SYMBOL, at(10, 0), 60, "100.00", kind="mark"),
    )
    output = simulate(case, risk_fn=fixed_risk_fn("0.5", "1.50"))

    assert output["run_summary"]["touch_no_fill_total"] == sum(
        t["touch_no_fill_count"] for t in output["trades"]
    )
    assert output["run_summary"]["touch_no_fill_total"] >= 1


def test_allowed_gaps_used_is_echoed_with_the_gap_that_covered_the_hole() -> None:
    gap = {
        "series": "funding",
        "symbol": SYMBOL,
        "start_utc": datetime(2026, 1, 5, 0, 0, tzinfo=UTC).isoformat(),
        "end_utc": at(20, 0).isoformat(),
        "missing": 2,
    }
    case = make_case(
        scripted=[scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-1")],
        trade_minutes=[go_through(SYMBOL, at(10, 1))],
        mark_minutes=flat_minutes(SYMBOL, at(10, 0), 120, "100.00", kind="mark"),
        funding=[
            funding_row(SYMBOL, datetime(2026, 1, 5, 0, 0, tzinfo=UTC)),
            funding_row(SYMBOL, at(20, 0)),
        ],
        data_end=at(20, 0),
        allowed_gaps=[gap],
    )
    output = simulate(case, risk_fn=fixed_risk_fn("0.5", "1.50"))

    assert output["run_summary"]["allowed_gaps_used"] == [
        {
            "series": "funding",
            "symbol": SYMBOL,
            "start_utc": gap["start_utc"],
            "end_utc": gap["end_utc"],
        }
    ]


def test_acknowledged_gaps_of_other_series_are_recorded_in_the_summary() -> None:
    # WR-05: a run over data with an acknowledged missing 1m trade minute must not read as
    # gap-free; the acknowledged gap is recorded next to the funding gaps that were used.
    gap = {
        "series": "trade",
        "symbol": SYMBOL,
        "start_utc": at(10, 30).isoformat(),
        "end_utc": at(10, 30).isoformat(),
        "missing": 1,
    }
    case = make_case(
        scripted=[scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-1")],
        trade_minutes=[go_through(SYMBOL, at(10, 1))],
        mark_minutes=flat_minutes(SYMBOL, at(10, 0), 120, "100.00", kind="mark"),
        allowed_gaps=[gap],
    )
    output = simulate(case, risk_fn=fixed_risk_fn("0.5", "1.50"))

    assert output["run_summary"]["allowed_gaps_used"] == [
        {
            "series": "trade",
            "symbol": SYMBOL,
            "start_utc": gap["start_utc"],
            "end_utc": gap["end_utc"],
        }
    ]


def test_the_summary_is_json_native_sorted_and_carries_no_parameters() -> None:
    output = simulate(counters_case(), risk_fn=fixed_risk_fn("0.5", "1.50"))
    summary = output["run_summary"]

    assert list(summary) == sorted(summary)
    assert "parameters" not in summary
    assert "parameters_json" not in summary
    roundtrip = json.loads(json.dumps(summary, sort_keys=True))
    assert roundtrip == summary

    def native(value: Any) -> bool:
        if value is None or isinstance(value, (str, int, bool)):
            return not isinstance(value, float)
        if isinstance(value, list):
            return all(native(v) for v in value)
        if isinstance(value, dict):
            return all(isinstance(k, str) and native(v) for k, v in value.items())
        return False

    assert native(summary)
    assert list(summary["no_trade_counts"]) == sorted(summary["no_trade_counts"])
