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
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.core import planner as planner_module
from src.core import strategy as strategy_module
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


def _number(text: str) -> int | Decimal | str:
    """Registry spelling: whole numbers are int, fractions are Decimal, words stay text."""
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return text
    return int(text) if "." not in text else Decimal(text)


def _parameter_set(case: dict[str, Any]) -> ParameterSet:
    """baseline-v5 of the case's family plus the case's own keys (in memory only)."""
    base = load_parameter_set(case.get("family", "trend-pullback"), "baseline-v5")
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


def test_a_long_legacy_contrast_stop_inside_the_zone_is_now_stop_too_tight() -> None:
    """Plan 15-13: the legacy contrast still signals but its plan is refused (D-06).

    The sidecar numbers document why: the legacy stop 97.60 lies above entry_min 96.80.
    """
    result, planned, expected = _run("a_long_legacy_contrast")
    assert result.signal is not None
    assert Decimal(expected["stop_loss"]) > Decimal(expected["entry_min"])
    assert planned.is_no_trade
    assert planned.trade_plan is None
    assert planned.reason_code == _STOP_TOO_TIGHT


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


def _enclosing_ifs(root: ast.AST, target: ast.AST) -> list[ast.If]:
    """Every `if` statement of `root` whose body or else-branch contains `target`."""
    return [
        node
        for node in ast.walk(root)
        if isinstance(node, ast.If) and any(target is inner for inner in ast.walk(node))
    ]


def _mentions_geometry_version(node: ast.AST) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and inner.id == "geometry_version":
            return True
        if isinstance(inner, ast.Constant) and inner.value == "geometry_version":
            return True
    return False


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


def test_geometry_rejection_call_is_not_gated_by_geometry_version() -> None:
    """T-15-22: no enclosing `if` of the single call tests geometry_version (D-06 is universal)."""
    tree = ast.parse(Path(planner_module.__file__ or "").read_text(encoding="utf-8"))
    plan_def = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "plan"
    )
    call = next(node for node in ast.walk(plan_def) if _is_geometry_rejection_call(node))
    gating = [
        node for node in _enclosing_ifs(plan_def, call) if _mentions_geometry_version(node.test)
    ]
    assert gating == []
    # No plan()-level early return keyed on geometry_version before the call either: the call
    # is reached on every path that has a quantized zone, legacy or not.
    assert not any(
        isinstance(node, ast.If)
        and _mentions_geometry_version(node.test)
        and node.lineno < call.lineno
        and any(isinstance(inner, ast.Return) for inner in ast.walk(node))
        for node in ast.walk(plan_def)
    )


# --------------------------------------------------------------------------- #
# Plan 15-13: the validator is universal. Legacy parameter sets (no geometry_version) are
# subject to D-06, D-07 and F6 as well (D-06: a plan violating the invariant is a bug).
# Plan hashes below were captured from the pre-change planner (old geometry_version gate).
# --------------------------------------------------------------------------- #

_LEGACY_B_PASSING_HASH = "4c998fb73d10cb9d24d675da6440964a7cb0fef337d26017bc3e96db3c1ea595"
_LEGACY_C_PASSING_HASH = "4b849e874dba87c6a593c01e8291ff71bad2185312c0e8df8db219875880da28"
_LEGACY_C_LOW_97_7_HASH = "523151f79fa89a10c921d3e2e3a4069f65cadfcee6204f9a51b2665c7e51ebd5"


def _legacy_b_window(*, low: str) -> tuple[list[Candle], list[Candle]]:
    """The b_long_legacy_contrast window with the evaluated bar's low replaced (high 104)."""
    setup, context = geometry_builders.family_b_long_window()
    bar = geometry_builders.with_evaluated_bar(
        setup, high=Decimal("104"), low=Decimal(low), close=Decimal("103")
    )
    return bar, context


def _legacy_c_set(**overrides: str) -> ParameterSet:
    return _case_set("c_long_legacy_contrast", **overrides)


def _legacy_c_window(*, low: str | None = None) -> tuple[list[Candle], list[Candle]]:
    """The c_long_legacy_contrast window (flat 4h); `low` replaces the evaluated bar's low."""
    setup, context = geometry_builders.range_mr_long_flat_context_window()
    if low is None:
        return setup, context
    return (
        geometry_builders.with_evaluated_bar(
            setup, high=Decimal("100"), low=Decimal(low), close=Decimal("98")
        ),
        context,
    )


def test_legacy_family_a_stop_too_tight_end_to_end() -> None:
    """A4/D-06: a baseline-v5 style Family A set still emits its legacy signal, never a plan.

    The legacy stop is swing_low - 0.2 x ATR = 97.60, inside the entry zone 96.80..99.20.
    """
    case = _load_cases()["a_long_legacy_contrast"]
    assert "geometry_version" not in case["params"]
    result, planned = _evaluate_and_plan(
        geometry_builders.family_a_long_window(), _parameter_set(case)
    )
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None and result.signal.direction == "LONG"
    assert planned is not None
    assert planned.is_no_trade
    assert planned.trade_plan is None
    assert planned.reason_code == _STOP_TOO_TIGHT


def test_legacy_family_a_registry_baseline_v5_never_plans() -> None:
    """The registered baseline-v5 itself: whenever it emits a signal, plan() refuses it."""
    parameter_set = load_parameter_set("trend-pullback", "baseline-v5")
    assert "geometry_version" not in parameter_set.params
    for window in (
        geometry_builders.family_a_long_window(),
        geometry_builders.family_a_short_window(),
    ):
        result, planned = _evaluate_and_plan(window, parameter_set)
        if planned is not None:
            assert result.signal is not None
            assert planned.trade_plan is None
            assert planned.reason_code == _STOP_TOO_TIGHT


def test_legacy_b_invalidated_when_the_signal_bar_is_through_the_stop() -> None:
    """D-07 on a legacy B plan: bar low 102.00 <= the legacy stop 102.60 (the sidecar contrast)."""
    case = _load_cases()["b_long_legacy_contrast"]
    assert "geometry_version" not in case["params"]
    window = geometry_builders.family_b_long_window()
    result, planned = _evaluate_and_plan(window, _parameter_set(case))
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None and result.signal.direction == "LONG"
    assert planned is not None
    assert planned.is_no_trade and planned.trade_plan is None
    assert planned.reason_code == _INVALIDATED
    assert window[0][-1].low == Decimal("102")


def test_legacy_b_touching_the_stop_is_invalidated_and_above_it_plans() -> None:
    """Touching counts (`low <= stop`): at low 102.50 the stop is 102.607, above the bar low."""
    parameter_set = _case_set("b_long_legacy_contrast")
    _r, through = _evaluate_and_plan(_legacy_b_window(low="102.5"), parameter_set)
    assert through is not None and through.reason_code == _INVALIDATED
    _r, above = _evaluate_and_plan(_legacy_b_window(low="102.7"), parameter_set)
    assert above is not None and not above.is_no_trade, above.reason_code


def test_legacy_c_invalidated_when_the_signal_bar_is_through_the_stop() -> None:
    """D-07 on a legacy C plan (flat 4h): crash bar low 95.00 <= stop 97.557 (zone 98 - 0.2 ATR)."""
    parameter_set = _legacy_c_set(touch_tolerance_atr="2.0")
    assert "geometry_version" not in parameter_set.params
    result, planned = _evaluate_and_plan(_legacy_c_window(low="95"), parameter_set)
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None and result.signal.direction == "LONG"
    assert planned is not None
    assert planned.is_no_trade and planned.trade_plan is None
    assert planned.reason_code == _INVALIDATED


def test_legacy_c_above_the_stop_still_plans() -> None:
    parameter_set = _legacy_c_set(touch_tolerance_atr="2.0")
    _r, above = _evaluate_and_plan(_legacy_c_window(low="97.7"), parameter_set)
    assert above is not None and not above.is_no_trade, above.reason_code
    assert above.trade_plan is not None
    assert above.trade_plan.stop_loss_price < above.trade_plan.entry_min_price


def test_legacy_plan_hash_unchanged_for_plans_that_satisfy_the_invariants() -> None:
    """D-07: a legacy B/C plan that passes keeps its exact plan_hash (pre-change literals)."""
    _r, b_plan = _evaluate_and_plan(
        _legacy_b_window(low="102.7"), _case_set("b_long_legacy_contrast")
    )
    assert b_plan is not None and b_plan.trade_plan is not None
    assert b_plan.trade_plan.plan_hash == _LEGACY_B_PASSING_HASH
    _r, c_plan = _evaluate_and_plan(_legacy_c_window(), _legacy_c_set())
    assert c_plan is not None and c_plan.trade_plan is not None
    assert c_plan.trade_plan.plan_hash == _LEGACY_C_PASSING_HASH
    _r, c_plan_2 = _evaluate_and_plan(
        _legacy_c_window(low="97.7"), _legacy_c_set(touch_tolerance_atr="2.0")
    )
    assert c_plan_2 is not None and c_plan_2.trade_plan is not None
    assert c_plan_2.trade_plan.plan_hash == _LEGACY_C_LOW_97_7_HASH


@pytest.mark.parametrize("family", ["b", "c"])
def test_legacy_tp1_on_the_loss_side_is_rr_too_low_through_plan(
    family: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6 on legacy B/C: plan() routes the legacy plan through the validator unconditionally.

    The legacy geometry cannot produce a loss-side TP1 on its own windows, so the spy feeds the
    real validator a loss-side TP1 and counts the call: it must happen exactly once.
    """
    real = planner_module._geometry_rejection
    seen: list[dict[str, Any]] = []

    def spy(**kwargs: Any) -> str | None:
        seen.append(kwargs)
        kwargs = {**kwargs, "take_profit_1": kwargs["entry_ref"] - Decimal("1")}
        return real(**kwargs)

    monkeypatch.setattr(planner_module, "_geometry_rejection", spy)
    if family == "b":
        window, parameter_set = _legacy_b_window(low="102.7"), _case_set("b_long_legacy_contrast")
    else:
        window, parameter_set = _legacy_c_window(), _legacy_c_set()
    assert "geometry_version" not in parameter_set.params
    _r, planned = _evaluate_and_plan(window, parameter_set)
    assert len(seen) == 1
    assert planned is not None and planned.trade_plan is None
    assert planned.reason_code == _RR_TOO_LOW


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
        if case["family"] != "trend-pullback":
            continue  # Family B has its own test below
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


# --------------------------------------------------------------------------- #
# Plan 15-05: Family B (breakout-retest) under geometry_version 1.
# --------------------------------------------------------------------------- #


def _expected_rr(trade_plan: Any) -> Decimal:
    return Decimal(json.loads(trade_plan.expected_rr_json)["tp1_rr"])


def test_b_long_worked_sets_breakout_confirmation_bars_explicitly() -> None:
    """D-18: the proposed baseline 1 (sheet B1) is test-local, never inherited from v5 (3)."""
    case = _load_cases()["b_long_worked"]
    assert case["params"]["breakout_confirmation_bars"] == "1"
    assert _parameter_set(case).params["breakout_confirmation_bars"] == 1
    inherited = load_parameter_set("breakout-retest", "baseline-v5")
    assert inherited.params["breakout_confirmation_bars"] == 3  # the legacy implementation value


def test_b_long_worked_plan_has_the_s3_stop_beyond_the_narrow_sr_zone() -> None:
    result, planned, expected = _run("b_long_worked")
    assert result.signal is not None
    assert result.signal.direction == expected["direction"]
    assert result.signal.setup_type == expected["setup_type"]
    _assert_plan_matches(planned, expected)
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.entry_min_price == Decimal("101.80")
    assert trade_plan.entry_max_price == Decimal("102.20")
    assert trade_plan.stop_loss_price == Decimal("99.60")
    assert trade_plan.stop_loss_price < trade_plan.entry_min_price
    assert _expected_rr(trade_plan) == Decimal(expected["tp1_rr"])


def test_b_long_worked_levels_carry_the_far_edge_of_the_sr_zone() -> None:
    case = _load_cases()["b_long_worked"]
    setup, _context = getattr(geometry_builders, case["builder"])()
    levels = strategy_module._detect_breakout_retest_levels(
        setup_candles=setup, parameter_set=_parameter_set(case), direction="LONG"
    )
    assert levels is not None
    expected = case["expected"]
    assert levels.direction == "LONG"
    assert levels.setup_type == "BREAKOUT_RETEST_LONG"
    assert levels.zone_upper == Decimal(expected["zone_upper"])
    assert levels.zone_lower == Decimal(expected["zone_lower"])
    assert levels.sr_far_edge == Decimal(expected["sr_far_edge"])


def test_b_long_legacy_contrast_signal_bar_through_the_code_stop_is_now_invalidated() -> None:
    """Plan 15-13: the legacy code stop edge - sl_buffer = 102.60 (103.00 - 0.2 x 2.00) lies at or
    above the signal bar's low 102.00, so D-07 refuses the plan; the signal is unchanged."""
    result, planned, expected = _run("b_long_legacy_contrast")
    assert result.signal is not None
    assert Decimal(expected["stop_loss"]) == Decimal("102.60")
    assert geometry_builders.family_b_long_window()[0][-1].low == Decimal("102")
    assert Decimal(expected["stop_loss"]) >= Decimal("102")
    assert planned.is_no_trade
    assert planned.trade_plan is None
    assert planned.reason_code == _INVALIDATED
    corrected, _plan, _ = _run("b_long_worked")
    assert corrected.signal is not None
    assert corrected.signal.signal_id != result.signal.signal_id


def test_b_short_worked_plan_has_the_s3_stop_above_the_whole_zone() -> None:
    result, planned, expected = _run("b_short_worked")
    assert result.signal is not None
    assert result.signal.direction == "SHORT"
    assert result.signal.setup_type == "BREAKOUT_RETEST_SHORT"
    assert result.regime == "BEARISH"
    _assert_plan_matches(planned, expected)
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.entry_min_price == Decimal("97.80")
    assert trade_plan.entry_max_price == Decimal("98.20")
    assert trade_plan.stop_loss_price == Decimal("100.40")
    assert trade_plan.stop_loss_price > trade_plan.entry_max_price
    assert _expected_rr(trade_plan) == Decimal(expected["tp1_rr"])
    case = _load_cases()["b_short_worked"]
    assert case["params"]["breakout_confirmation_bars"] == "1"
    setup, _context = geometry_builders.family_b_short_window()
    levels = strategy_module._detect_breakout_retest_levels(
        setup_candles=setup, parameter_set=_parameter_set(case), direction="SHORT"
    )
    assert levels is not None
    assert levels.zone_upper == Decimal(expected["zone_upper"])
    assert levels.zone_lower == Decimal(expected["zone_lower"])
    assert levels.sr_far_edge == Decimal(expected["sr_far_edge"])


def test_b_long_legacy_confirm3_is_labelled_and_uses_the_legacy_value() -> None:
    case = _load_cases()["b_long_legacy_confirm3"]
    assert case["note"] == "legacy value, not the baseline to be ratified"
    assert _parameter_set(case).params["breakout_confirmation_bars"] == 3
    text = (_CASES_PATH.parent / "DERIVATIONS.md").read_text(encoding="utf-8")
    section = text.split("## b_long_legacy_confirm3", 1)[1].split("\n## ", 1)[0]
    assert "legacy value, not the baseline to be ratified" in section


def test_b_long_legacy_confirm3_reference_bar_is_four_bars_before_the_end_bar() -> None:
    """ref_prev = i - 4 = 243: bar 244 (high 102) stays out of the swing window, edge 102.00."""
    result, planned, expected = _run("b_long_legacy_confirm3")
    assert result.signal is not None
    assert result.signal.direction == "LONG"
    _assert_plan_matches(planned, expected)
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.stop_loss_price == Decimal("99.60")
    assert trade_plan.stop_loss_price < trade_plan.entry_min_price
    assert _expected_rr(trade_plan) == Decimal(expected["tp1_rr"])


def test_b_long_legacy_confirm3_needs_all_three_closes_above_the_edge() -> None:
    case = _load_cases()["b_long_legacy_confirm3"]
    result, _planned = _evaluate_and_plan(
        geometry_builders.family_b_confirm3_one_close_window(), _parameter_set(case)
    )
    assert result.is_no_trade
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value


def test_b_main_worked_cases_state_confirmation_bars_one_and_the_legacy_case_three() -> None:
    cases = _load_cases()
    for name in ("b_long_worked", "b_short_worked"):
        assert cases[name]["params"]["breakout_confirmation_bars"] == "1", name
    assert cases["b_long_legacy_confirm3"]["params"]["breakout_confirmation_bars"] == "3"


@pytest.mark.parametrize("name", ["b_long_worked", "b_short_worked", "b_long_legacy_confirm3"])
def test_b_cases_are_deterministic(name: str) -> None:
    first = _run(name)
    second = _run(name)
    assert first[0].signal == second[0].signal
    assert first[1].trade_plan == second[1].trade_plan


def test_every_corrected_family_b_plan_has_its_stop_outside_the_zone() -> None:
    checked = 0
    for name, case in _load_cases().items():
        expected = case["expected"]
        if case["family"] != "breakout-retest" or "geometry_version" not in case["params"]:
            continue
        _result, planned, _ = _run(name)
        trade_plan = planned.trade_plan
        assert trade_plan is not None, name
        if expected["direction"] == "LONG":
            assert trade_plan.stop_loss_price < trade_plan.entry_min_price, name
        else:
            assert trade_plan.stop_loss_price > trade_plan.entry_max_price, name
        checked += 1
    assert checked == 3  # b_long_worked, b_short_worked, b_long_legacy_confirm3


def test_b_d07_signal_bar_through_the_stop_is_invalidated() -> None:
    """D-07 on B: retest_depth_atr 2.0 lets a crash bar (low 98.50) be the first retest.

    DERIVATIONS.md b_long_invalidated: bars 247 and 248 have lows 108 (above the band
    98.00..106.00), bar 249 has low 98.50. ATR_last = 2.853498542274052478134110787, so the
    stop is 100 - 0.2 x ATR_last = 99.42930029154518950437317784, above the bar low.
    """
    parameter_set = _case_set("b_long_worked", retest_depth_atr="2.0")
    window = geometry_builders.family_b_crash_window()
    result, planned = _evaluate_and_plan(window, parameter_set)
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None and result.signal.direction == "LONG"
    assert planned is not None
    assert planned.is_no_trade
    assert planned.trade_plan is None
    assert planned.reason_code == _INVALIDATED
    setup, _context = window
    atr_last = Decimal("2.853498542274052478134110787")
    stop = strategy_module._detect_breakout_retest_levels(
        setup_candles=setup, parameter_set=parameter_set, direction="LONG"
    )
    assert stop is not None and stop.sr_far_edge == Decimal("100.0")
    expected_stop = Decimal("100.0") - Decimal("0.2") * atr_last
    assert expected_stop == Decimal("99.42930029154518950437317784")
    assert setup[-1].low == Decimal("98.50") < expected_stop


def test_b_d08_min_stop_atr_rejects_the_narrow_zone_stop() -> None:
    """D-08 on B: risk from entry_ref is 2 x 0.5 x 2.00 + 0.2 x 2.00 = 2.40 = 1.2 ATR."""
    window = geometry_builders.family_b_long_window()
    _result, tight = _evaluate_and_plan(window, _case_set("b_long_worked", min_stop_atr="2.0"))
    assert tight is not None and tight.trade_plan is None
    assert tight.reason_code == _STOP_TOO_TIGHT
    _result, just_over = _evaluate_and_plan(window, _case_set("b_long_worked", min_stop_atr="1.21"))
    assert just_over is not None and just_over.reason_code == _STOP_TOO_TIGHT
    _result, equal = _evaluate_and_plan(window, _case_set("b_long_worked", min_stop_atr="1.2"))
    assert equal is not None and not equal.is_no_trade, equal.reason_code
    assert equal.trade_plan is not None
    assert equal.trade_plan.stop_loss_price == Decimal("99.60")


def test_b_d06_stop_inside_the_entry_zone_is_stop_too_tight() -> None:
    """D-06 on B: zone_tolerance_atr 0 puts the far edge at the edge, and a 0.05 stop buffer
    below the 0.1 entry buffer leaves the stop at 101.90, inside the entry zone 101.80..102.20."""
    window = geometry_builders.family_b_long_window()
    parameter_set = _case_set("b_long_worked", zone_tolerance_atr="0", sl_buffer_atr="0.05")
    result, planned = _evaluate_and_plan(window, parameter_set)
    assert not result.is_no_trade, result.reason_code
    assert planned is not None
    assert planned.is_no_trade
    assert planned.trade_plan is None
    assert planned.reason_code == _STOP_TOO_TIGHT


def test_b_validator_causes_are_distinct_but_share_the_reason() -> None:
    """Two different STOP_TOO_TIGHT causes (D-06 inside the zone, D-08 ATR floor) on B."""
    window = geometry_builders.family_b_long_window()
    _r1, inside = _evaluate_and_plan(
        window, _case_set("b_long_worked", zone_tolerance_atr="0", sl_buffer_atr="0.05")
    )
    _r2, floor = _evaluate_and_plan(window, _case_set("b_long_worked", min_stop_atr="2.0"))
    assert _plan_reason(inside) == _plan_reason(floor) == _STOP_TOO_TIGHT
    # The same window passes with neither override, so each cause is the only blocker.
    _r3, clean = _evaluate_and_plan(window, _case_set("b_long_worked"))
    assert clean is not None and not clean.is_no_trade


def test_derivations_file_has_a_section_for_every_plan_15_05_case() -> None:
    text = (_CASES_PATH.parent / "DERIVATIONS.md").read_text(encoding="utf-8")
    for heading in (
        "## b_long_worked",
        "## b_long_legacy_contrast",
        "## b_short_worked",
        "## b_long_legacy_confirm3",
        "## Family B anchoring windows",
        "## Family B leakage and validator cases",
    ):
        assert heading in text, heading
    for name in ("b_long_worked", "b_short_worked"):
        section = text.split(f"## {name}", 1)[1].split("\n## ", 1)[0]
        assert "breakout_confirmation_bars = 1" in section, name


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


# --------------------------------------------------------------------------- #
# Plan 15-06: Family C (range-mr) under geometry_version 1.
# --------------------------------------------------------------------------- #


def test_c_long_worked_plan_has_the_s3_stop_beyond_the_narrow_sr_zone() -> None:
    result, planned, expected = _run("c_long_worked")
    assert result.signal is not None
    assert result.signal.direction == expected["direction"]
    assert result.signal.setup_type == expected["setup_type"]
    assert result.regime == expected["regime"] == "NEUTRAL"
    _assert_plan_matches(planned, expected)
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.entry_min_price == Decimal("97.80")
    assert trade_plan.entry_max_price == Decimal("98.20")
    assert trade_plan.stop_loss_price == Decimal("96.60")
    assert trade_plan.stop_loss_price < trade_plan.entry_min_price
    targets = json.loads(trade_plan.take_profit_json)
    midpoint = (Decimal(expected["zone_upper"]) + Decimal(expected["zone_lower"])) / 2
    assert Decimal(targets["tp1"]) == midpoint == Decimal("102")
    assert _expected_rr(trade_plan) == Decimal(expected["tp1_rr"])


def test_c_long_worked_levels_carry_the_far_edge_of_the_sr_zone() -> None:
    case = _load_cases()["c_long_worked"]
    setup, _context = getattr(geometry_builders, case["builder"])()
    levels = strategy_module._detect_range_mr_levels(
        setup_candles=setup, parameter_set=_parameter_set(case)
    )
    assert levels is not None
    expected = case["expected"]
    assert levels.direction == "LONG"
    assert levels.setup_type == "RANGE_MR_LONG"
    assert levels.zone_upper == Decimal(expected["zone_upper"])
    assert levels.zone_lower == Decimal(expected["zone_lower"])
    assert levels.sr_far_edge == Decimal(expected["sr_far_edge"])


def test_c_long_legacy_contrast_keeps_the_code_stop_and_the_opposite_boundary() -> None:
    case = _load_cases()["c_long_legacy_contrast"]
    assert "geometry_version" not in case["params"]
    result, planned, expected = _run("c_long_legacy_contrast")
    assert result.signal is not None
    assert result.regime == "NEUTRAL"
    _assert_plan_matches(planned, expected)
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.stop_loss_price == Decimal("97.60")  # zone_lower - 0.2 x ATR_last
    legacy_tp1 = Decimal(json.loads(trade_plan.take_profit_json)["tp1"])
    assert legacy_tp1 == Decimal("106.00")  # zone_upper
    levels = strategy_module._detect_range_mr_levels(
        setup_candles=geometry_builders.range_mr_long_window()[0],
        parameter_set=_parameter_set(case),
    )
    assert levels is not None and levels.sr_far_edge is None


def test_c_legacy_regime_still_needs_exact_ema50_equality() -> None:
    """D-25: without geometry_version the pivot (contracting) 4h window is not NEUTRAL."""
    case = _load_cases()["c_long_legacy_contrast"]
    result, planned = _evaluate_and_plan(
        geometry_builders.range_mr_long_window(), _parameter_set(case)
    )
    assert planned is None
    assert result.is_no_trade
    assert result.reason_code == RejectionReason.NO_TRADE_REGIME.value
    assert result.regime in {"BULLISH", "BEARISH"}


# --------------------------------------------------------------------------- #
# Plan 15-06 Task 3: Family C SHORT, T_OPPOSITE, the T-mid RR gate and the validator on C.
# --------------------------------------------------------------------------- #

_C_WORKED = ["c_short_worked", "c_long_t_opposite"]


@pytest.mark.parametrize("name", _C_WORKED)
def test_family_c_worked_case_matches_the_hand_derived_sidecar(name: str) -> None:
    result, planned, expected = _run(name)
    assert result.signal is not None
    assert result.signal.direction == expected["direction"]
    assert result.signal.setup_type == expected["setup_type"]
    assert result.regime == expected["regime"] == "NEUTRAL"
    _assert_plan_matches(planned, expected)
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert _expected_rr(trade_plan) == Decimal(expected["tp1_rr"])


def test_c_short_worked_stop_is_above_the_whole_zone_and_tp1_is_the_midpoint() -> None:
    _result, planned, expected = _run("c_short_worked")
    trade_plan = planned.trade_plan
    assert trade_plan is not None
    assert trade_plan.entry_min_price == Decimal("101.80")
    assert trade_plan.entry_max_price == Decimal("102.20")
    assert trade_plan.stop_loss_price == Decimal("103.40")
    assert trade_plan.stop_loss_price > trade_plan.entry_max_price
    targets = json.loads(trade_plan.take_profit_json)
    midpoint = (Decimal(expected["zone_upper"]) + Decimal(expected["zone_lower"])) / 2
    assert Decimal(targets["tp1"]) == midpoint == Decimal("98")
    case = _load_cases()["c_short_worked"]
    setup, _context = geometry_builders.range_mr_short_window()
    levels = strategy_module._detect_range_mr_levels(
        setup_candles=setup, parameter_set=_parameter_set(case)
    )
    assert levels is not None
    assert levels.direction == "SHORT"
    assert levels.zone_upper == Decimal(expected["zone_upper"])
    assert levels.zone_lower == Decimal(expected["zone_lower"])
    assert levels.sr_far_edge == Decimal(expected["sr_far_edge"])


def test_t_opposite_keeps_the_opposite_boundary_and_the_larger_rr() -> None:
    """Same window and stop as c_long_worked; only tp_mode changes (D-10)."""
    _result, opposite, expected = _run("c_long_t_opposite")
    _result_mid, mid, expected_mid = _run("c_long_worked")
    assert opposite.trade_plan is not None and mid.trade_plan is not None
    assert opposite.trade_plan.stop_loss_price == mid.trade_plan.stop_loss_price
    opposite_tp1 = Decimal(json.loads(opposite.trade_plan.take_profit_json)["tp1"])
    assert opposite_tp1 == Decimal(expected["zone_upper"]) == Decimal("106")
    assert _expected_rr(opposite.trade_plan) == Decimal("5.714285714285714285714285714")
    assert _expected_rr(opposite.trade_plan) > _expected_rr(mid.trade_plan)
    assert Decimal(expected_mid["tp1"]) < opposite_tp1


def test_t_mid_on_a_narrow_range_is_rr_too_low_and_t_opposite_keeps_the_plan() -> None:
    """D-10 counting case: the midpoint leg 2.00 is under 2 x risk 1.40 = 2.80."""
    window = geometry_builders.range_mr_narrow_window()
    _result, mid = _evaluate_and_plan(window, _case_set("c_long_worked"))
    assert mid is not None
    assert mid.is_no_trade and mid.trade_plan is None
    assert mid.reason_code == _RR_TOO_LOW
    result, opposite = _evaluate_and_plan(window, _case_set("c_long_worked", tp_mode="T_OPPOSITE"))
    assert result.regime == "NEUTRAL"
    assert opposite is not None and not opposite.is_no_trade, opposite.reason_code
    assert opposite.trade_plan is not None
    assert opposite.trade_plan.stop_loss_price == Decimal("96.60")
    targets = json.loads(opposite.trade_plan.take_profit_json)
    assert Decimal(targets["tp1"]) == Decimal("102")
    assert Decimal(targets["tp2"]) == Decimal("106")
    assert _expected_rr(opposite.trade_plan) == Decimal("2.857142857142857142857142857")
    setup, _context = window
    midpoint_leg = (Decimal("102") + Decimal("98")) / 2 - Decimal("98")
    assert midpoint_leg < Decimal("2") * (Decimal("98") - Decimal("96.6"))
    assert setup[-1].low == Decimal("98")


def test_t_mid_gate_boundary_follows_minimum_rr() -> None:
    """The narrow midpoint RR is 1.428571...: minimum_rr 1.4 admits it, 1.43 rejects it."""
    window = geometry_builders.range_mr_narrow_window()
    _r, admitted = _evaluate_and_plan(window, _case_set("c_long_worked", minimum_rr="1.4"))
    assert admitted is not None and not admitted.is_no_trade, admitted.reason_code
    _r, rejected = _evaluate_and_plan(window, _case_set("c_long_worked", minimum_rr="1.43"))
    assert rejected is not None and rejected.reason_code == _RR_TOO_LOW


def test_c_d07_signal_bar_through_the_stop_is_invalidated() -> None:
    """D-07 on C: touch_tolerance_atr 2.0 lets a crash bar (low 95.00) be the touch bar.

    DERIVATIONS.md: ATR_last = 2.214285714285714285714285714, so the stop is 97.00 - 0.2 x
    ATR_last = 96.55714285714285714285714286, above the bar low.
    """
    parameter_set = _case_set("c_long_worked", touch_tolerance_atr="2.0")
    window = geometry_builders.range_mr_crash_window()
    result, planned = _evaluate_and_plan(window, parameter_set)
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None and result.signal.direction == "LONG"
    assert planned is not None
    assert planned.is_no_trade and planned.trade_plan is None
    assert planned.reason_code == _INVALIDATED
    setup, _context = window
    levels = strategy_module._detect_range_mr_levels(
        setup_candles=setup, parameter_set=parameter_set
    )
    assert levels is not None and levels.sr_far_edge == Decimal("97.0")
    atr_last = (Decimal("13") * Decimal("2") + Decimal("5")) / Decimal("14")
    assert atr_last == Decimal("2.214285714285714285714285714")
    expected_stop = Decimal("97.0") - Decimal("0.2") * atr_last
    assert expected_stop == Decimal("96.55714285714285714285714286")
    assert setup[-1].low == Decimal("95") < expected_stop


def test_c_d08_min_stop_atr_rejects_a_stop_closer_than_the_floor() -> None:
    """D-08 on C: the risk 1.40 is 0.7 ATR; the floor 1.0 ATR (2.00) rejects it."""
    window = geometry_builders.range_mr_long_window()
    _r, tight = _evaluate_and_plan(window, _case_set("c_long_worked", min_stop_atr="1.0"))
    assert tight is not None and tight.trade_plan is None
    assert tight.reason_code == _STOP_TOO_TIGHT
    _r, just_over = _evaluate_and_plan(window, _case_set("c_long_worked", min_stop_atr="0.71"))
    assert just_over is not None and just_over.reason_code == _STOP_TOO_TIGHT
    _r, equal = _evaluate_and_plan(window, _case_set("c_long_worked", min_stop_atr="0.7"))
    assert equal is not None and not equal.is_no_trade, equal.reason_code
    assert equal.trade_plan is not None
    assert equal.trade_plan.stop_loss_price == Decimal("96.60")


def test_c_d06_stop_inside_the_entry_zone_is_stop_too_tight() -> None:
    """D-06 on C: zone_tolerance_atr 0 puts the far edge at the edge; a 0.05 stop buffer
    below the 0.1 entry buffer leaves the stop at 97.90, inside the zone 97.80..98.20."""
    window = geometry_builders.range_mr_long_window()
    parameter_set = _case_set("c_long_worked", zone_tolerance_atr="0", sl_buffer_atr="0.05")
    result, planned = _evaluate_and_plan(window, parameter_set)
    assert not result.is_no_trade, result.reason_code
    assert planned is not None
    assert planned.is_no_trade and planned.trade_plan is None
    assert planned.reason_code == _STOP_TOO_TIGHT


def test_c_validator_causes_are_distinct_but_share_the_reason() -> None:
    """Two STOP_TOO_TIGHT causes on C (D-06 inside the zone, D-08 ATR floor)."""
    window = geometry_builders.range_mr_long_window()
    _r1, inside = _evaluate_and_plan(
        window, _case_set("c_long_worked", zone_tolerance_atr="0", sl_buffer_atr="0.05")
    )
    _r2, floor = _evaluate_and_plan(window, _case_set("c_long_worked", min_stop_atr="1.0"))
    assert _plan_reason(inside) == _plan_reason(floor) == _STOP_TOO_TIGHT
    _r3, clean = _evaluate_and_plan(window, _case_set("c_long_worked"))
    assert clean is not None and not clean.is_no_trade


def test_every_corrected_family_c_plan_has_its_stop_outside_the_zone() -> None:
    checked = 0
    for name, case in _load_cases().items():
        expected = case["expected"]
        if case["family"] != "range-mr" or "geometry_version" not in case["params"]:
            continue
        _result, planned, _ = _run(name)
        trade_plan = planned.trade_plan
        assert trade_plan is not None, name
        if expected["direction"] == "LONG":
            assert trade_plan.stop_loss_price < trade_plan.entry_min_price, name
        else:
            assert trade_plan.stop_loss_price > trade_plan.entry_max_price, name
        checked += 1
    assert checked == 3  # c_long_worked, c_short_worked, c_long_t_opposite


@pytest.mark.parametrize(
    "name", ["c_long_worked", "c_short_worked", "c_long_t_opposite", "c_long_legacy_contrast"]
)
def test_c_cases_are_deterministic(name: str) -> None:
    first = _run(name)
    second = _run(name)
    assert first[0].signal == second[0].signal
    assert first[1].trade_plan == second[1].trade_plan


def test_c_tp_mode_outside_the_registry_values_is_a_configuration_error() -> None:
    parameter_set = _case_set("c_long_worked", tp_mode="T_THIRD")
    with pytest.raises(ValueError, match="tp_mode"):
        _evaluate_and_plan(geometry_builders.range_mr_long_window(), parameter_set)


def test_c_vanished_setup_at_plan_time_is_stale_setup() -> None:
    """A signal from the worked window planned on candles where the touch has gone."""
    case = _load_cases()["c_long_worked"]
    parameter_set = _parameter_set(case)
    setup, context = geometry_builders.range_mr_long_window()
    result, _planned = _evaluate_and_plan((setup, context), parameter_set)
    assert result.signal is not None
    moved = geometry_builders.with_evaluated_bar(
        setup, high=Decimal("104"), low=Decimal("100"), close=Decimal("103.5")
    )
    planned = plan(
        signal=result.signal,
        setup_candles=moved,
        parameter_set=parameter_set,
        account_state=AccountState(equity=Decimal("10000"), risk_rate=Decimal("0.005")),
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert planned.is_no_trade
    assert planned.reason_code == RejectionReason.STALE_SETUP.value


def test_derivations_file_has_a_section_for_every_plan_15_06_case() -> None:
    text = (_CASES_PATH.parent / "DERIVATIONS.md").read_text(encoding="utf-8")
    for heading in (
        "## c_long_worked",
        "## c_long_legacy_contrast",
        "## c_short_worked",
        "## c_long_t_opposite",
        "## Family C narrow range and validator cases",
    ):
        assert heading in text, heading
    section = text.split("## c_long_worked", 1)[1].split("\n## ", 1)[0]
    assert "NEUTRAL" in section and "pivot" in section.lower()
