"""Plan 16-63 Task 1: a plan whose TP2 is not a positive price is NO_TRADE RR_TOO_LOW.

Diagnosis (plan 16-61, run 2.2.0, evidence/16-61-run-output.txt): research-run-1-a01,
1000PEPEUSDT, SHORT, signal bar open 2025-10-11 05:00 UTC, VALIDATION fold 2. The planner
built a plan whose TP2 = quantize(entry_ref - 2 x (entry_ref - TP1)) was
-0.001548100000000000, and `take_profit_levels` (src/backtest/exits.py) raised. The symbol and
the time rest on the orchestrator's diagnosis; the arithmetic is proved in
`test_the_run_1_a01_numbers_give_the_negative_tp2_of_the_2_2_0_error`.

The recipe lowers every setup row (open, high, low, close) of a phase 6 fixture by a constant,
so the geometry (entry, stop, TP1) moves by that constant and the TP2 formula crosses zero.
Hand values for `intrabar_both_touched_short` (baseline-v6): entry_ref 132.2, TP1 126.8, so
TP1 lowered by 123.34 is 3.46 on an entry of 8.86 and TP2 = 8.86 - 2 x 5.40 = -1.94.

Owner decision of 2026-10-17, Option A.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.backtest.engine import simulate
from src.backtest.entry import snapped_limit_price
from src.backtest.exits import sl_trigger_price, take_profit_levels
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot, PlanResult, SetupResult
from src.domain.canonical import quantize_for_storage
from src.domain.enums import RejectionReason
from src.domain.registry import ParameterSet, load_parameter_set
from src.paper.loop import evaluate_closed_bar
from src.risk.gating import evaluate_risk

from tests.backtest_case_helpers import (
    SYMBOL,
    constraint_row,
    flat_minutes,
    make_case,
    minute_row,
    phase6_case_identity,
    phase6_cost_model,
    phase6_strategy_rows,
)
from tests.test_paper_decision_surface import _bar_context

SHORT_FIXTURE = "intrabar_both_touched_short"
LONG_FIXTURE = "intrabar_both_touched"
TICK = Decimal("0.10")

# plan_hash literals printed by the UNMODIFIED code (RED step, evidence/16-63-red-evidence.txt).
LONG_PLAN_HASH = "e461c438d12c68f6551fd013207b76450a54666ec43abae72854130891974d9f"
SHORT_PLAN_HASH = "6cdec18c121d7df8e4bd67f696084c96098d06f0e2a05cf59d5a10ea2792d843"


def _candle(row: dict[str, Any]) -> Candle:
    return Candle(
        symbol=row["symbol"],
        interval=row["interval"],
        open_time_utc=datetime.fromisoformat(row["open_time_utc"]),
        close_time_utc=datetime.fromisoformat(row["close_time_utc"]),
        open=Decimal(row["open"]),
        high=Decimal(row["high"]),
        low=Decimal(row["low"]),
        close=Decimal(row["close"]),
        volume=Decimal(row["volume"]),
    )


def _lowered(rows: list[dict[str, Any]], amount: str) -> list[dict[str, Any]]:
    """Copies of `rows` with open, high, low and close lowered by `amount` (Decimal strings)."""
    delta = Decimal(amount)
    out: list[dict[str, Any]] = []
    for row in rows:
        moved = dict(row)
        for key in ("open", "high", "low", "close"):
            moved[key] = str(Decimal(row[key]) - delta)
        out.append(moved)
    return out


def _identity(fixture: str) -> tuple[ParameterSet, str]:
    strategy_id, strategy_version, parameter_set_id = phase6_case_identity(fixture)
    return load_parameter_set(strategy_id, parameter_set_id), strategy_version


def _evaluate_and_plan(
    fixture: str, lowering: str = "0"
) -> tuple[SetupResult, PlanResult | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """evaluate then plan the fixture with its setup rows lowered (context rows unchanged)."""
    strategy_rows, context_rows = phase6_strategy_rows(fixture)
    strategy_rows = _lowered(strategy_rows, lowering)
    setup = [_candle(r) for r in strategy_rows]
    context = [_candle(r) for r in context_rows]
    parameter_set, strategy_version = _identity(fixture)
    account = AccountState(equity=Decimal("10000"), risk_rate=Decimal("0.005"))
    snapshot = MarketSnapshot(
        symbol=SYMBOL,
        setup_candles=setup,
        context_candles=[c for c in context if c.close_time_utc <= setup[-1].close_time_utc],
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account,
        strategy_version=strategy_version,
        parameter_set=parameter_set,
    )
    if result.is_no_trade or result.signal is None:
        return result, None, strategy_rows, context_rows
    planned = plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=account,
        created_at_utc=setup[-1].close_time_utc,
    )
    return result, planned, strategy_rows, context_rows


def _levels(planned: PlanResult) -> tuple[Decimal, Decimal]:
    assert planned.trade_plan is not None
    targets = json.loads(planned.trade_plan.take_profit_json)
    return Decimal(targets["tp1"]), Decimal(targets["tp2"])


def _entry_ref(planned: PlanResult) -> Decimal:
    assert planned.trade_plan is not None
    return (planned.trade_plan.entry_min_price + planned.trade_plan.entry_max_price) / 2


# --------------------------------------------------------------------------- #
# Test 1 - the lowered SHORT is NO_TRADE RR_TOO_LOW
# --------------------------------------------------------------------------- #


def test_a_short_whose_tp2_is_negative_is_no_trade_rr_too_low() -> None:
    result, planned, _, _ = _evaluate_and_plan(SHORT_FIXTURE, "123.34")
    assert result.signal is not None
    assert result.signal.direction == "SHORT"
    assert planned is not None
    assert planned.is_no_trade is True
    assert planned.trade_plan is None
    assert planned.reason_code == RejectionReason.RR_TOO_LOW.value


# --------------------------------------------------------------------------- #
# Test 2 - origin witness (arithmetic of the 2.2.0 error)
# --------------------------------------------------------------------------- #


def test_the_run_1_a01_numbers_give_the_negative_tp2_of_the_2_2_0_error() -> None:
    entry_ref = Decimal("0.0070985")
    tp1 = Decimal("0.0027752")
    tp1_leg = entry_ref - tp1
    assert tp1_leg == Decimal("0.0043233")
    assert tp1_leg > entry_ref / 2
    tp2 = quantize_for_storage(entry_ref - 2 * tp1_leg)
    assert tp2 == Decimal("-0.001548100000000000")


# --------------------------------------------------------------------------- #
# Test 3 - boundary
# --------------------------------------------------------------------------- #


def test_a_tp2_of_exactly_zero_is_no_trade() -> None:
    result, planned, _, _ = _evaluate_and_plan(SHORT_FIXTURE, "121.4")
    assert result.signal is not None
    assert planned is not None
    assert planned.is_no_trade is True
    assert planned.trade_plan is None
    assert planned.reason_code == RejectionReason.RR_TOO_LOW.value


def test_a_tp2_just_above_zero_is_still_a_plan() -> None:
    result, planned, _, _ = _evaluate_and_plan(SHORT_FIXTURE, "121.39")
    assert result.signal is not None
    assert planned is not None
    assert planned.is_no_trade is False
    assert planned.trade_plan is not None
    tp1, tp2 = _levels(planned)
    assert _entry_ref(planned) == Decimal("10.81")
    assert tp1 == Decimal("5.41")
    assert tp2 == Decimal("0.010000000000000000")
    assert tp2 > Decimal("0")
    expected_rr = json.loads(planned.trade_plan.expected_rr_json)
    assert "tp2_rr" in expected_rr


# --------------------------------------------------------------------------- #
# Test 4 - nothing else moves
# --------------------------------------------------------------------------- #


def test_the_unlowered_long_plan_is_byte_identical() -> None:
    result, planned, _, _ = _evaluate_and_plan(LONG_FIXTURE)
    assert result.signal is not None
    assert planned is not None and planned.trade_plan is not None
    assert result.signal.direction == "LONG"
    assert planned.trade_plan.plan_hash == LONG_PLAN_HASH
    _, tp2 = _levels(planned)
    assert tp2 > _entry_ref(planned)


def test_the_unlowered_short_plan_is_byte_identical() -> None:
    result, planned, _, _ = _evaluate_and_plan(SHORT_FIXTURE)
    assert result.signal is not None
    assert planned is not None and planned.trade_plan is not None
    assert result.signal.direction == "SHORT"
    assert planned.trade_plan.plan_hash == SHORT_PLAN_HASH
    tp1, tp2 = _levels(planned)
    assert (_entry_ref(planned), tp1, tp2) == (
        Decimal("132.2"),
        Decimal("126.8"),
        Decimal("121.4"),
    )


# --------------------------------------------------------------------------- #
# Test 5 - order of the checks
# --------------------------------------------------------------------------- #


def test_the_geometry_rejection_stays_first_and_once_before_tp2_and_the_rr_gate() -> None:
    import inspect

    from src.core import planner as planner_module

    source = inspect.getsource(planner_module.plan)
    geometry = source.index("_geometry_rejection(")
    tp2_computed = source.index("tp2 = quantize_for_storage(_sub(entry_ref")
    rr_gate = source.index("realized_rr = _div(tp1_leg, risk)")
    assert source.count("_geometry_rejection(") == 1
    assert geometry < tp2_computed < rr_gate


# --------------------------------------------------------------------------- #
# Test 6 - the engine
# --------------------------------------------------------------------------- #


def _engine_case(lowering: str) -> dict[str, Any]:
    """The SHORT fixture as a backtest case, setup rows lowered by `lowering`.

    The minute rows are derived from the UNLOWERED plan's limit and stop minus the lowering, so
    that, were a plan created, it would fill and stop out; the guarded case has no plan.
    """
    _, unlowered, _, _ = _evaluate_and_plan(SHORT_FIXTURE)
    assert unlowered is not None and unlowered.trade_plan is not None
    plan_0 = unlowered.trade_plan
    shift = Decimal(lowering)
    limit = snapped_limit_price(plan=plan_0, direction="SHORT", price_tick_size=TICK) - shift
    stop = sl_trigger_price(plan=plan_0, direction="SHORT", price_tick_size=TICK) - shift
    strategy_rows, context_rows = phase6_strategy_rows(SHORT_FIXTURE)
    strategy_rows = _lowered(strategy_rows, lowering)
    setup = [_candle(r) for r in strategy_rows]
    strategy_id, strategy_version, parameter_set_id = phase6_case_identity(SHORT_FIXTURE)
    start = setup[-1].close_time_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)
    trade_row = minute_row(
        SYMBOL,
        start + timedelta(minutes=10),
        str(limit),
        str(limit + TICK * 2),
        str(limit - TICK),
        str(limit),
        kind="trade",
    )
    flat = flat_minutes(SYMBOL, start, 30, str(limit), kind="mark", half_range="0.1")
    stop_row = minute_row(
        SYMBOL,
        start + timedelta(minutes=30),
        str(limit),
        str(stop + TICK),
        str(limit),
        str(limit),
        kind="mark",
    )
    return make_case(
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set_id,
        cost_overrides=phase6_cost_model(SHORT_FIXTURE),
        strategy_bars=strategy_rows,
        context_bars=context_rows,
        trade_minutes=[trade_row],
        mark_minutes=[*flat, stop_row],
        data_start=setup[0].open_time_utc,
        data_end=setup[-1].close_time_utc + timedelta(hours=3),
        funding=[
            {
                "symbol": SYMBOL,
                "funding_time_utc": when.isoformat(),
                "funding_rate": "0",
                "mark_price": "100",
            }
            for when in (
                setup[0].open_time_utc,
                setup[-1].close_time_utc - timedelta(hours=4),
                setup[-1].close_time_utc + timedelta(hours=3),
            )
        ],
    )


def test_the_engine_counts_the_guarded_plan_as_a_reject_and_does_not_raise() -> None:
    output = simulate(_engine_case("123.34"), risk_fn=evaluate_risk)

    records = output["trades"]
    assert len(records) == 1
    assert records[0]["entry_kind"] == "REJECT"
    assert records[0]["reason_code"] == RejectionReason.RR_TOO_LOW.value
    assert records[0]["entry_time_utc"] is None
    assert output["run_summary"]["no_trade_counts"]["RR_TOO_LOW"] == 1


def test_the_unlowered_engine_case_still_fills() -> None:
    output = simulate(_engine_case("0"), risk_fn=evaluate_risk)

    records = output["trades"]
    assert len(records) == 1
    assert records[0]["entry_kind"] != "REJECT"
    assert records[0]["entry_time_utc"] is not None
    assert "RR_TOO_LOW" not in output["run_summary"]["no_trade_counts"]


# --------------------------------------------------------------------------- #
# Test 7 - the paper bar chain
# --------------------------------------------------------------------------- #


def _paper_outcome(lowering: str) -> Any:
    strategy_rows, context_rows = phase6_strategy_rows(SHORT_FIXTURE)
    strategy_rows = _lowered(strategy_rows, lowering)
    setup = [_candle(r) for r in strategy_rows]
    context = [_candle(r) for r in context_rows]
    strategy_id, strategy_version, parameter_set_id = phase6_case_identity(SHORT_FIXTURE)
    case = {
        "strategy_id": strategy_id,
        "parameter_set_id": parameter_set_id,
        "strategy_version": strategy_version,
        "symbols": [SYMBOL],
        "account_state": {"equity": "10000", "risk_rate": "0.005"},
        "constraint_history": [constraint_row(SYMBOL)],
        "cost_model": phase6_cost_model(SHORT_FIXTURE),
    }
    closed = setup[-1]
    bar_context = _bar_context(case, closed.close_time_utc)
    return evaluate_closed_bar(
        bar_context,
        closed,
        setup,
        [c for c in context if c.close_time_utc <= closed.close_time_utc],
    )


def test_the_paper_bar_chain_ends_at_the_planner_for_the_guarded_plan() -> None:
    outcome = _paper_outcome("123.34")
    assert outcome.stage == "planner"
    assert outcome.reason_code == RejectionReason.RR_TOO_LOW.value
    assert outcome.trade_plan is None
    assert outcome.signal is not None


def test_the_paper_bar_chain_goes_past_the_planner_for_the_unlowered_bar() -> None:
    outcome = _paper_outcome("0")
    assert outcome.stage != "planner"
    assert outcome.trade_plan is not None


# --------------------------------------------------------------------------- #
# Test 8 - defence in depth kept
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tp2", ["-1.94", "0", "0E-18"])
def test_take_profit_levels_still_refuses_a_non_positive_tp2(tp2: str) -> None:
    _, planned, _, _ = _evaluate_and_plan(SHORT_FIXTURE)
    assert planned is not None and planned.trade_plan is not None
    tp1, _ = _levels(planned)
    broken = dataclasses.replace(
        planned.trade_plan,
        take_profit_json=json.dumps({"tp1": str(tp1), "tp2": tp2}, sort_keys=True),
    )
    with pytest.raises(ValueError, match="positive finite price"):
        take_profit_levels(broken)
