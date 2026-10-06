"""Phase 15 plan 15-03: corrected Family A geometry through evaluate and plan.

Expected values are read from the hand-derived sidecar
tests/fixtures/phase15/geometry_cases.json (derivations in DERIVATIONS.md), never from the
code under test. Parameter values are test-local: an in-memory ParameterSet built from
trend-pullback/baseline-v5 plus the case's own keys. Nothing under params/ is touched.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, MarketSnapshot, PlanResult, SetupResult
from src.domain.registry import ParameterSet, load_parameter_set

from tests import geometry_builders

_CASES_PATH = Path(__file__).parent / "fixtures" / "phase15" / "geometry_cases.json"
_FORBIDDEN_KEYS = {"parameters", "parameters_json", "parameter_set_id"}


def _load_cases() -> dict[str, Any]:
    cases = json.loads(_CASES_PATH.read_text(encoding="utf-8"))["cases"]
    assert isinstance(cases, dict)
    return cases


def _number(text: str) -> int | Decimal:
    """Registry spelling: whole numbers are int, fractions are Decimal."""
    return int(text) if "." not in text else Decimal(text)


def _parameter_set(case: dict[str, Any]) -> ParameterSet:
    base = load_parameter_set("trend-pullback", "baseline-v5")
    params = dict(base.params)
    for key, text in case["params"].items():
        params[key] = _number(text)
    return dataclasses.replace(base, params=params)


def _run(case_name: str) -> tuple[SetupResult, PlanResult, dict[str, Any]]:
    case = _load_cases()[case_name]
    builder = getattr(geometry_builders, case["builder"])
    setup, context = builder()
    parameter_set = _parameter_set(case)
    account = AccountState(equity=Decimal("10000"), risk_rate=Decimal("0.005"))
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup,
        context_candles=context,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None
    planned = plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=account,
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )
    return result, planned, case["expected"]


def _walk_keys(node: object) -> list[str]:
    keys: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(key)
            keys.extend(_walk_keys(value))
    elif isinstance(node, list):
        for value in node:
            keys.extend(_walk_keys(value))
    return keys


def test_sidecar_has_no_research_gate_tripwire_keys() -> None:
    parsed = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    assert not _FORBIDDEN_KEYS & set(_walk_keys(parsed))


def test_sidecar_states_its_independence() -> None:
    text = (_CASES_PATH.parent / "DERIVATIONS.md").read_text(encoding="utf-8")
    assert "never from the output of the code under test" in text
    assert "## a_long_worked" in text


def _assert_plan_matches(planned: PlanResult, expected: dict[str, Any]) -> None:
    assert not planned.is_no_trade, planned.reason_code
    assert planned.reason_code == expected["reason_code"]
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    targets = json.loads(trade_plan.take_profit_json)
    assert trade_plan.entry_min_price == Decimal(expected["entry_min"])
    assert trade_plan.entry_max_price == Decimal(expected["entry_max"])
    assert trade_plan.stop_loss_price == Decimal(expected["stop_loss"])
    assert Decimal(targets["tp1"]) == Decimal(expected["tp1"])
    assert Decimal(targets["tp2"]) == Decimal(expected["tp2"])
    entry_ref = (trade_plan.entry_min_price + trade_plan.entry_max_price) / 2
    assert entry_ref == Decimal(expected["entry_ref"])


def test_a_long_worked_plan_has_stop_beyond_the_whole_entry_zone() -> None:
    result, planned, expected = _run("a_long_worked")
    assert result.signal is not None
    assert result.signal.direction == expected["direction"]
    assert result.signal.setup_type == expected["setup_type"]
    _assert_plan_matches(planned, expected)
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.stop_loss_price < trade_plan.entry_min_price
    assert trade_plan.entry_min_price == Decimal("97.80")
    assert trade_plan.entry_max_price == Decimal("100.20")
    assert trade_plan.stop_loss_price == Decimal("97.40")


def test_a_long_legacy_contrast_keeps_the_stop_inside_the_zone() -> None:
    _result, planned, expected = _run("a_long_legacy_contrast")
    _assert_plan_matches(planned, expected)
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.stop_loss_price > trade_plan.entry_min_price


def test_geometry_version_changes_the_signal_identity() -> None:
    corrected, _plan_a, _ = _run("a_long_worked")
    legacy, _plan_b, _ = _run("a_long_legacy_contrast")
    assert corrected.signal is not None and legacy.signal is not None
    assert corrected.signal.signal_id != legacy.signal.signal_id


@pytest.mark.parametrize("name", ["a_long_worked", "a_long_legacy_contrast"])
def test_cases_are_reproducible(name: str) -> None:
    first = _run(name)
    second = _run(name)
    assert first[0].signal == second[0].signal
    assert first[1].trade_plan == second[1].trade_plan
