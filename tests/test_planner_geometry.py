"""Phase 15 plan 15-03: corrected Family A geometry through evaluate and plan.

Expected values are read from the hand-derived sidecar
tests/fixtures/phase15/geometry_cases.json (derivations in DERIVATIONS.md), never from the
code under test. Parameter values are test-local: an in-memory ParameterSet built from
trend-pullback/baseline-v5 plus the case's own keys. Nothing under params/ is touched.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.core import planner as planner_module
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot, PlanResult, SetupResult
from src.domain.canonical import quantize_for_storage
from src.domain.enums import RejectionReason
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


def _evaluate_and_plan(
    window: tuple[list[Candle], list[Candle]], parameter_set: ParameterSet
) -> tuple[SetupResult, PlanResult | None]:
    """evaluate then plan; the plan is None when evaluate itself returns NO_TRADE."""
    setup, context = window
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
    if result.is_no_trade:
        return result, None
    assert result.signal is not None
    planned = plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=account,
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )
    return result, planned


def _run(case_name: str) -> tuple[SetupResult, PlanResult, dict[str, Any]]:
    case = _load_cases()[case_name]
    builder = getattr(geometry_builders, case["builder"])
    result, planned = _evaluate_and_plan(builder(), _parameter_set(case))
    assert not result.is_no_trade, result.reason_code
    assert planned is not None
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


# --------------------------------------------------------------------------- #
# Plan 15-04: the shared structural validator (D-06, D-07, D-08, F6, D-26).
# --------------------------------------------------------------------------- #

_STOP_TOO_TIGHT = RejectionReason.STOP_TOO_TIGHT.value
_INVALIDATED = RejectionReason.INVALIDATED.value
_RR_TOO_LOW = RejectionReason.RR_TOO_LOW.value


def _case_set(name: str, **overrides: str) -> ParameterSet:
    """The sidecar case's parameter set with test-local overrides (in memory only)."""
    case = json.loads(json.dumps(_load_cases()[name]))
    case["params"].update(overrides)
    return _parameter_set(case)


def _reject(**overrides: Any) -> str | None:
    """Direct call of the validator with a valid hand-derived LONG baseline.

    Baseline = the a_long_worked numbers: zone 97.80-100.20, entry_ref 99.00, stop 97.40,
    TP1 106.00, ATR 2.00, signal bar low 98.00 and high 100.00.
    """
    values: dict[str, Any] = {
        "direction": "LONG",
        "entry_min": Decimal("97.80"),
        "entry_max": Decimal("100.20"),
        "entry_ref": Decimal("99.00"),
        "stop_loss": Decimal("97.40"),
        "take_profit_1": Decimal("106.00"),
        "atr": Decimal("2.00"),
        "signal_low": Decimal("98.00"),
        "signal_high": Decimal("100.00"),
        "min_stop_atr": None,
    }
    values.update(overrides)
    result = planner_module._geometry_rejection(**values)
    assert result is None or isinstance(result, str)
    return result


def _short(**overrides: Any) -> str | None:
    """Mirror baseline: zone 97.80-100.20, stop 100.60, TP1 92.00, signal bar high 99.50."""
    values: dict[str, Any] = {
        "direction": "SHORT",
        "stop_loss": Decimal("100.60"),
        "take_profit_1": Decimal("92.00"),
        "signal_low": Decimal("98.50"),
        "signal_high": Decimal("99.50"),
    }
    values.update(overrides)
    return _reject(**values)


def _plan_reason(planned: PlanResult | None) -> str:
    assert planned is not None
    return planned.reason_code


def test_validator_accepts_the_hand_derived_baselines() -> None:
    assert _reject() is None
    assert _short() is None


def test_stop_inside_zone_long_is_stop_too_tight() -> None:
    assert _reject(stop_loss=Decimal("97.80")) == _STOP_TOO_TIGHT  # equal to entry_min
    assert _reject(stop_loss=Decimal("98.00")) == _STOP_TOO_TIGHT  # inside the zone
    assert _reject(stop_loss=Decimal("99.00")) == _STOP_TOO_TIGHT  # at entry_ref


def test_stop_inside_zone_short_is_stop_too_tight() -> None:
    assert _short(stop_loss=Decimal("100.20")) == _STOP_TOO_TIGHT  # equal to entry_max
    assert _short(stop_loss=Decimal("100.00")) == _STOP_TOO_TIGHT
    assert _short(stop_loss=Decimal("99.00")) == _STOP_TOO_TIGHT


def test_stop_inside_zone_boundary_is_one_storage_quantum_on_quantized_values() -> None:
    quantum = Decimal("1E-18")
    entry_min = quantize_for_storage(Decimal("97.8"))
    entry_max = quantize_for_storage(Decimal("100.2"))
    zone = {"entry_min": entry_min, "entry_max": entry_max}
    just_outside = quantize_for_storage(entry_min - quantum)
    assert just_outside < entry_min
    assert _reject(**zone, stop_loss=just_outside) is None
    assert _reject(**zone, stop_loss=entry_min) == _STOP_TOO_TIGHT
    short_outside = quantize_for_storage(entry_max + quantum)
    assert short_outside > entry_max
    assert _short(**zone, stop_loss=short_outside, signal_high=Decimal("99")) is None
    assert _short(**zone, stop_loss=entry_max) == _STOP_TOO_TIGHT


def test_invalidated_long_when_signal_low_reaches_the_stop() -> None:
    assert _reject(signal_low=Decimal("97.40")) == _INVALIDATED  # boundary counts as through
    assert _reject(signal_low=Decimal("97.00")) == _INVALIDATED
    assert _reject(signal_low=Decimal("97.41")) is None


def test_invalidated_short_when_signal_high_reaches_the_stop() -> None:
    assert _short(signal_high=Decimal("100.60")) == _INVALIDATED
    assert _short(signal_high=Decimal("101.00")) == _INVALIDATED
    assert _short(signal_high=Decimal("100.59")) is None


def test_invalidated_is_unreachable_for_family_a_by_the_d05_arithmetic() -> None:
    """F4: the signal bar low is >= zone_lower, the stop is zone_lower - entry_buffer - sl_buffer.

    a_long_worked: zone_lower 98.00, entry_buffer 0.20, sl_buffer 0.40, stop 97.40, so the
    lowest low that can signal (98.00) is 0.60 above the stop. D-07 stays as defense in depth.
    """
    _result, planned, expected = _run("a_long_worked")
    assert planned.trade_plan is not None
    zone_lower = Decimal(expected["zone_lower"])
    stop = planned.trade_plan.stop_loss_price
    assert zone_lower - stop == Decimal("0.60") == Decimal("0.20") + Decimal("0.40")
    assert _reject(signal_low=zone_lower, stop_loss=stop) is None


def test_min_stop_atr_enforces_the_stop_distance_from_entry_ref() -> None:
    # |99.00 - 97.40| = 1.60 = 0.8 ATR with ATR 2.00
    assert _reject(min_stop_atr=Decimal("0.8")) is None  # equality passes
    assert _reject(min_stop_atr=Decimal("0.81")) == _STOP_TOO_TIGHT
    assert _reject(min_stop_atr=Decimal("1.0")) == _STOP_TOO_TIGHT
    assert _reject(min_stop_atr=None) is None


def test_min_stop_atr_through_plan() -> None:
    window = geometry_builders.family_a_long_window()
    _result, tight = _evaluate_and_plan(window, _case_set("a_long_worked", min_stop_atr="1.0"))
    assert tight is not None and tight.trade_plan is None
    assert tight.reason_code == _STOP_TOO_TIGHT
    _result, equal = _evaluate_and_plan(window, _case_set("a_long_worked", min_stop_atr="0.8"))
    assert equal is not None and not equal.is_no_trade, equal.reason_code
    assert equal.trade_plan is not None
    assert equal.trade_plan.stop_loss_price == Decimal("97.40")


def test_stop_inside_zone_through_plan_with_zero_stop_buffer() -> None:
    window = geometry_builders.family_a_long_window()
    result, planned = _evaluate_and_plan(window, _case_set("a_long_worked", sl_buffer_atr="0"))
    assert not result.is_no_trade
    assert planned is not None
    assert planned.is_no_trade
    assert planned.trade_plan is None
    assert planned.reason_code == _STOP_TOO_TIGHT


def test_tp_loss_side_long_is_rr_too_low() -> None:
    assert _reject(take_profit_1=Decimal("99.00")) == _RR_TOO_LOW  # equal to entry_ref
    assert _reject(take_profit_1=Decimal("98.50")) == _RR_TOO_LOW
    assert _reject(take_profit_1=Decimal("99.01")) is None


def test_tp_loss_side_short_is_rr_too_low() -> None:
    assert _short(take_profit_1=Decimal("99.00")) == _RR_TOO_LOW
    assert _short(take_profit_1=Decimal("100.00")) == _RR_TOO_LOW
    assert _short(take_profit_1=Decimal("98.99")) is None


def test_tp_loss_side_through_plan_even_with_a_tiny_minimum_rr() -> None:
    """F6: confirmed pivot high 105.00 sits below entry_ref 106.00; abs() used to pass it.

    Hand numbers (DERIVATIONS.md tp_loss_side): pivot low 106.00, zone 105.00-107.00, entry
    104.80-107.20, entry_ref 106.00, stop 104.40, newest confirmed pivot high 105.00.
    """
    window = geometry_builders.family_a_tp_loss_side_window()
    result, planned = _evaluate_and_plan(window, _case_set("a_long_worked", minimum_rr="0.1"))
    assert not result.is_no_trade, result.reason_code
    assert planned is not None
    assert planned.is_no_trade
    assert planned.trade_plan is None
    assert planned.reason_code == _RR_TOO_LOW


def test_order_stop_inside_zone_wins_over_loss_side_tp() -> None:
    both = _reject(stop_loss=Decimal("98.00"), take_profit_1=Decimal("98.00"))
    assert both == _STOP_TOO_TIGHT
    only_rr = _reject(take_profit_1=Decimal("98.00"))
    assert only_rr == _RR_TOO_LOW


def test_order_invalidated_wins_over_min_stop_and_tp_side() -> None:
    both = _reject(
        signal_low=Decimal("97.40"), min_stop_atr=Decimal("5"), take_profit_1=Decimal("98.00")
    )
    assert both == _INVALIDATED
    assert _reject(min_stop_atr=Decimal("5"), take_profit_1=Decimal("98.00")) == _STOP_TOO_TIGHT
    assert _reject(take_profit_1=Decimal("98.00")) == _RR_TOO_LOW


def test_order_through_plan_stop_inside_zone_wins_over_rr() -> None:
    window = geometry_builders.family_a_tp_loss_side_window()
    _result, planned = _evaluate_and_plan(
        window, _case_set("a_long_worked", minimum_rr="0.1", sl_buffer_atr="0")
    )
    assert _plan_reason(planned) == _STOP_TOO_TIGHT


def _is_geometry_rejection_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_geometry_rejection"
    )


def test_plan_holds_exactly_one_geometry_rejection_call() -> None:
    """D-06: the invariants live in one function with one call site, inside plan()."""
    tree = ast.parse(Path(planner_module.__file__ or "").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if _is_geometry_rejection_call(node)]
    assert len(calls) == 1
    plan_def = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "plan"
    )
    inside_plan = [node for node in ast.walk(plan_def) if _is_geometry_rejection_call(node)]
    assert len(inside_plan) == 1
    assert calls[0] is inside_plan[0]


def test_legacy_set_is_not_subject_to_the_validator() -> None:
    """No geometry_version: the legacy stop inside the zone still plans (until plan 15-13)."""
    _result, planned, expected = _run("a_long_legacy_contrast")
    assert planned.trade_plan is not None
    assert planned.trade_plan.stop_loss_price == Decimal(expected["stop_loss"])


# --------------------------------------------------------------------------- #
# Plan 15-04 Task 2: Family A SHORT, audit anchors, missing pivot, determinism.
# --------------------------------------------------------------------------- #

_WORKED_CASES = ["a_short_worked", "a_long_audit_60000", "a_long_audit_59000"]


@pytest.mark.parametrize("name", _WORKED_CASES)
def test_family_a_worked_case_matches_the_hand_derived_sidecar(name: str) -> None:
    result, planned, expected = _run(name)
    assert result.signal is not None
    assert result.signal.direction == expected["direction"]
    assert result.signal.setup_type == expected["setup_type"]
    _assert_plan_matches(planned, expected)


def test_a_short_worked_stop_is_above_the_whole_zone() -> None:
    _result, planned, _expected = _run("a_short_worked")
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.entry_min_price == Decimal("99.80")
    assert trade_plan.entry_max_price == Decimal("102.20")
    assert trade_plan.stop_loss_price == Decimal("102.60")
    assert trade_plan.stop_loss_price > trade_plan.entry_max_price
    targets = json.loads(trade_plan.take_profit_json)
    assert Decimal(targets["tp1"]) == Decimal("94.00")
    assert Decimal(targets["tp2"]) == Decimal("87.00")


def test_a_long_audit_60000_has_no_stop_inside_the_zone() -> None:
    """F5: S = 60,000 and ATR = 400 give a corrected plan, never one with the SL in the zone."""
    _result, planned, _expected = _run("a_long_audit_60000")
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.stop_loss_price == Decimal("59680")
    zone = (Decimal("59760"), Decimal("60240"))
    assert not zone[0] <= trade_plan.stop_loss_price <= zone[1]
    assert trade_plan.stop_loss_price < zone[0]


def test_a_long_audit_59000_stop_is_below_entry_min() -> None:
    """CONTEXT anchor: 59,000 / ATR 300 gives SL 58,760 below 58,820 (old SL 58,940 was inside)."""
    _result, planned, _expected = _run("a_long_audit_59000")
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.entry_min_price == Decimal("58820")
    assert trade_plan.stop_loss_price == Decimal("58760")
    assert trade_plan.stop_loss_price < trade_plan.entry_min_price


def test_every_corrected_family_a_plan_has_its_stop_outside_the_zone() -> None:
    checked = 0
    for name, case in _load_cases().items():
        expected = case["expected"]
        if "geometry_version" not in case["params"] or expected.get("reason_code") != "OK":
            continue  # the legacy contrast case keeps the stop inside the zone on purpose
        _result, planned, _ = _run(name)
        trade_plan = planned.trade_plan
        assert trade_plan is not None, name
        if expected["direction"] == "LONG":
            assert trade_plan.stop_loss_price < trade_plan.entry_min_price, name
        else:
            assert trade_plan.stop_loss_price > trade_plan.entry_max_price, name
        checked += 1
    assert checked == 4  # a_long_worked, a_short_worked and the two audit anchors


def test_missing_opposite_pivot_at_plan_time_is_stale_setup() -> None:
    """D-09: a confirmed pivot low and a touching bar, but no pivot high to use as TP1."""
    case = _load_cases()["a_long_no_opposite_pivot"]
    window = geometry_builders.family_a_no_opposite_pivot_window()
    result, planned = _evaluate_and_plan(window, _parameter_set(case))
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None
    assert result.signal.direction == case["expected"]["direction"]
    assert planned is not None
    assert planned.is_no_trade
    assert planned.trade_plan is None
    assert planned.reason_code == case["expected"]["plan_reason_code"]


@pytest.mark.parametrize("name", ["a_long_worked", *_WORKED_CASES])
def test_signal_id_and_plan_hash_are_deterministic(name: str) -> None:
    first = _run(name)
    second = _run(name)
    assert first[0].signal is not None and second[0].signal is not None
    assert first[0].signal.signal_id == second[0].signal.signal_id
    assert first[1].trade_plan is not None and second[1].trade_plan is not None
    assert first[1].trade_plan.plan_hash == second[1].trade_plan.plan_hash


def test_evaluate_is_unchanged_when_the_last_bar_is_rebuilt_from_the_prefix() -> None:
    """No later candle exists to poison; rebuilding window[:-1] + [same last bar] is a no-op."""
    case = _load_cases()["a_long_worked"]
    parameter_set = _parameter_set(case)
    setup, context = geometry_builders.family_a_long_window()
    original, _plan = _evaluate_and_plan((setup, context), parameter_set)
    rebuilt = setup[:-1] + [dataclasses.replace(setup[-1])]
    again, _plan = _evaluate_and_plan((rebuilt, context), parameter_set)
    assert original == again
    assert original.signal is not None


def test_derivations_file_has_a_section_for_every_plan_15_04_case() -> None:
    text = (_CASES_PATH.parent / "DERIVATIONS.md").read_text(encoding="utf-8")
    for heading in (
        "## tp_loss_side",
        "## a_short_worked",
        "## a_long_audit_60000",
        "## a_long_audit_59000",
        "## a_long_no_opposite_pivot",
    ):
        assert heading in text, heading
