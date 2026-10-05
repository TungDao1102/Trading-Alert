"""Engine tests for the v2 event loop (Phase 14, plan 14-08).

Tracer (Task 1): one scripted LONG plan at the 09:59:59.999 close is sized by the real
`evaluate_risk` on ledger equity, rests from 10:00, fills at 10:01, is stopped out by the
mark minute 10:40 and leaves one validated record.

Hand oracle (zone 99.00-101.00 -> limit 100.00, stop 98.00, tick 0.10, step 0.001,
min qty 0.001, min notional 5, equity 10000, risk_rate 0.005, baseline-v5 costs):

    sizing entry       = 101.00 (adverse zone edge)
    costs per unit     = 101 x 0.0006 + 98 x 0.0008 = 0.1390
    risk per unit      = |101 - 98| + 0.1390 = 3.1390, allowed risk = 10000 x 0.005 = 50
    quantity           = floor(50 / 3.1390 = 15.9286..., step 0.001) = 15.928
    realized risk      = 15.928 x 3.1390 = 49.997992
    gross_pnl          = (98.00 - 100.00) x 15.928 = -31.856
    entry fee          = 100 x 15.928 x 0.0005 = 0.7964
    entry slippage     = 100 x 15.928 x 0.0001 = 0.15928
    exit fee           = 98 x 15.928 x 0.0005 = 0.780472
    exit slippage      = 98 x 15.928 x 0.0003 = 0.4682832
    realized_pnl       = -31.856 - 0.7964 - 0.780472 - (0.15928 + 0.4682832) = -34.0604352
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.case import CASE_INPUT_SCHEMA, REMOVED_V1_KEYS
from src.backtest.engine import simulate
from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION
from src.risk.gating import evaluate_risk
from src.risk.types import PortfolioVerdict

from tests.backtest_case_helpers import (
    SIGNAL_CLOSE,
    SYMBOL,
    at,
    flat_minutes,
    make_case,
    minute_close,
    minute_row,
    scripted_plan,
)

ENGINE_PATH = Path(__file__).resolve().parent.parent / "src" / "backtest" / "engine.py"


def tracer_case(**overrides: Any) -> dict[str, Any]:
    """The Task 1 case: a scripted LONG at 09:59:59.999, fill at 10:01, stop at 10:40."""
    trade = [
        # 10:00 stays above the limit - one tick; 10:01 trades through it.
        minute_row(SYMBOL, at(10, 0), "100.60", "100.70", "100.40", "100.60", kind="trade"),
        minute_row(SYMBOL, at(10, 1), "100.20", "100.30", "99.80", "100.00", kind="trade"),
    ]
    mark = [
        *flat_minutes(SYMBOL, at(10, 0), 40, "100.00", kind="mark"),
        minute_row(SYMBOL, at(10, 40), "98.50", "98.60", "97.90", "98.20", kind="mark"),
    ]
    arguments: dict[str, Any] = {
        "scripted": [scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-1")],
        "trade_minutes": trade,
        "mark_minutes": mark,
    }
    arguments.update(overrides)
    return make_case(**arguments)


def spying_risk_fn(calls: list[dict[str, Any]], verdicts: list[PortfolioVerdict]) -> Any:
    """`evaluate_risk` wrapped so a test sees every call and every verdict."""

    def risk_fn(**kwargs: Any) -> PortfolioVerdict:
        calls.append(kwargs)
        verdict = evaluate_risk(**kwargs)
        verdicts.append(verdict)
        return verdict

    return risk_fn


def test_tracer_plan_rests_fills_and_stops_out_with_real_sizing() -> None:
    calls: list[dict[str, Any]] = []
    verdicts: list[PortfolioVerdict] = []
    output = simulate(tracer_case(), risk_fn=spying_risk_fn(calls, verdicts))

    assert len(output["trades"]) == 1
    trade = output["trades"][0]
    assert trade["entry_kind"] == "ENTRY_FILLED"
    assert trade["outcome_kind"] == "OK"
    assert trade["exit_kind"] == "SL"
    assert trade["direction"] == "LONG"
    assert trade["signal_id"] == "sig-1"
    assert trade["signal_close_utc"] == SIGNAL_CLOSE.isoformat()
    # The plan is active from the first minute AFTER the signal close, and the fill is the
    # close of the deciding trade minute (10:01), never the signal bar itself.
    assert trade["entry_time_utc"] == minute_close(at(10, 1)).isoformat()
    assert datetime.fromisoformat(trade["entry_time_utc"]) > SIGNAL_CLOSE
    assert trade["exit_time_utc"] == minute_close(at(10, 40)).isoformat()
    assert Decimal(trade["entry_price"]) == Decimal("100.00")
    assert Decimal(trade["exit_price"]) == Decimal("98.00")
    assert trade["gap_through_stop"] is False
    assert Decimal(trade["quantity"]) == Decimal("15.928")
    assert Decimal(trade["planned_quantity"]) == Decimal("15.928")


def test_tracer_record_costs_follow_the_hand_oracle() -> None:
    verdicts: list[PortfolioVerdict] = []
    output = simulate(tracer_case(), risk_fn=spying_risk_fn([], verdicts))
    trade = output["trades"][0]

    assert Decimal(trade["gross_pnl"]) == Decimal("-31.856")
    assert Decimal(trade["entry_fee"]) == Decimal("0.7964")
    assert Decimal(trade["exit_fee"]) == Decimal("0.780472")
    assert Decimal(trade["slippage_amount"]) == Decimal("0.6275632")
    assert Decimal(trade["funding_amount"]) == Decimal("0")
    assert Decimal(trade["realized_pnl"]) == Decimal("-34.0604352")
    # A full fill: the R denominator is the sized realized risk itself (D-20).
    sized = verdicts[0].sized
    assert sized is not None
    assert Decimal(trade["realized_risk"]) == sized.realized_risk == Decimal("49.997992")


def test_risk_fn_receives_ledger_state_a_point_in_time_constraint_and_zero_ttl() -> None:
    calls: list[dict[str, Any]] = []
    simulate(tracer_case(), risk_fn=spying_risk_fn(calls, []))

    assert len(calls) == 1
    call = calls[0]
    assert call["now_utc"] == SIGNAL_CLOSE
    assert call["ttl"] == timedelta(0)
    assert call["open_positions"] == []
    assert call["daily_loss_quote"] == Decimal("0")
    assert call["account_state"].equity == Decimal("10000")
    assert call["account_state"].risk_rate == Decimal("0.005")
    assert call["candidate_position_side"] == "LONG"
    snapshot = call["constraint_snapshot"]
    assert snapshot.symbol == SYMBOL
    assert snapshot.price_tick_size == Decimal("0.10")
    # The freshness stamp is clamped to the bar close so the zero ttl gate sees age 0.
    assert snapshot.metadata_observed_at_utc == SIGNAL_CLOSE
    # Registry thresholds arrive as absolute quote amounts of the ledger equity (D-18).
    assert call["parameter_set"]["cluster_cap"] == Decimal("50.000")


def test_output_carries_summary_hashes_and_symbols() -> None:
    output = simulate(tracer_case(), risk_fn=evaluate_risk)

    assert output["symbols"] == [SYMBOL]
    assert output["strategy_version"] == "v4.0.0"
    assert len(output["parameter_set_hash"]) == 64
    assert len(output["cost_model_hash"]) == 64
    summary = output["run_summary"]
    assert summary["plan_source"] == "SCRIPTED"
    assert summary["simulator_semantics_version"] == SIMULATOR_SEMANTICS_VERSION == "2.0.0"
    assert summary["no_trade_counts"] == {}
    assert summary["allowed_gaps_used"] == []
    # The whole output is canonical-JSON safe.
    assert json.loads(json.dumps(output, sort_keys=True)) == output


@pytest.mark.parametrize("key", REMOVED_V1_KEYS)
def test_a_case_carrying_a_v1_key_is_refused_naming_the_key(key: str) -> None:
    case = tracer_case()
    case[key] = {} if key.endswith("_map") else "x"
    with pytest.raises(ValueError, match=key):
        simulate(case, risk_fn=evaluate_risk)


def test_removed_keys_include_the_documented_v1_set() -> None:
    assert set(REMOVED_V1_KEYS) == {
        "intrabar_1m_map",
        "constraint_snapshot",
        "open_positions",
        "daily_loss_quote",
        "now_utc",
        "ttl_seconds",
        "mark_price_bars",
    }


def test_a_case_without_the_schema_literal_is_refused() -> None:
    case = tracer_case()
    del case["case_input_schema"]
    with pytest.raises(ValueError, match="case_input_schema"):
        simulate(case, risk_fn=evaluate_risk)


def test_a_case_with_another_schema_literal_is_refused() -> None:
    case = tracer_case()
    case["case_input_schema"] = "backtest-case/1"
    with pytest.raises(ValueError, match=CASE_INPUT_SCHEMA):
        simulate(case, risk_fn=evaluate_risk)


def test_a_cost_model_without_funding_convention_is_refused() -> None:
    case = tracer_case()
    del case["cost_model"]["funding_convention"]
    with pytest.raises(ValueError, match="funding_convention"):
        simulate(case, risk_fn=evaluate_risk)


def test_a_float_anywhere_in_the_case_is_refused() -> None:
    case = tracer_case()
    case["account_state"]["equity"] = 10000.5
    with pytest.raises(TypeError, match="equity"):
        simulate(case, risk_fn=evaluate_risk)


def test_a_naive_datetime_in_the_case_is_refused() -> None:
    case = tracer_case()
    case["data_window"]["end_utc"] = "2026-01-05T12:00:00"
    with pytest.raises(ValueError, match="end_utc"):
        simulate(case, risk_fn=evaluate_risk)


def test_the_engine_never_imports_evaluate_risk() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == "evaluate_risk"
    ]
    assert imported == []
