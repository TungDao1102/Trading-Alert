"""Phase 19 gate (plan 19-17): the inventory and the structural invariants in one place.

This file asserts, against the real tree and without any network or live evidence:

- every module, test, support file, config, migration and planning document the Phase 19 plans
  promise exists (`PHASE19_ARTIFACTS`);
- every public symbol a later phase imports is importable (`PHASE19_SYMBOLS`);
- the new pure modules are free of SDK, float and wall-clock use (`PHASE19_PURE_MODULES`);
- the frozen Phase 18 / Phase 9 / backtest pieces and the pinned enums are unchanged, and
  `execute_approved_plan` places no protective order (the coordinator does);
- each of APRV-01, APRV-02, EXEC-01, EXEC-02, RISK-04 and EXEC-07 has its named automated tests
  (`REQUIREMENT_TESTS`, resolved with `ast`, never imported or run);
- the GLOSSARY lists every new plain-string reason code and SAFE_MODE reason;
- the owner-gap register names every open owner item and the hand-off notes exist.

A failure message names the exact missing path, symbol or test, so the Phase 20 planner can run
this file first. Nothing here changes behavior and nothing here claims an owner item is solved.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

from tests import test_binance_limits_ratified_file as ratified_file_tests
from tests import test_phase18_gate as phase18_gate
from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)

ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = ROOT / ".planning" / "phases" / "19-execution-plan-binding-price-check"

# --------------------------------------------------------------------------- #
# The inventory.
# --------------------------------------------------------------------------- #

PHASE19_ARTIFACTS: tuple[str, ...] = (
    # Pure and execution source (plans 19-01 to 19-16).
    "src/domain/lot_filters.py",
    "src/execution/execution_limits.py",
    "src/execution/binding.py",
    "src/execution/pre_placement.py",
    "src/execution/lot_split.py",
    "src/execution/tp_sizing.py",
    "src/execution/protection.py",
    "src/execution/emergency_close.py",
    "src/execution/live_context.py",
    # Migration 0005 (19-06).
    "src/db/alembic/versions/0005_live_sized_risk.py",
    # Configuration (19-01).
    "config/execution/execution-limits-v1.toml",
    "config/execution/README.md",
    # Test support.
    "tests/support/execution_limits.py",
    "tests/support/protection_doubles.py",
    # Tests, one per plan deliverable.
    "tests/test_execution_limits.py",
    "tests/test_execution_binding.py",
    "tests/test_pre_placement.py",
    "tests/test_market_lot_split.py",
    "tests/test_live_mark_price_adapter.py",
    "tests/test_binance_entry_gtd.py",
    "tests/test_realized_risk_persistence_pg.py",
    "tests/test_tp_sizing.py",
    "tests/test_binance_market_close_adapter.py",
    "tests/test_fake_exchange_v2.py",
    "tests/test_protection_coordinator.py",
    "tests/test_protection_router_rig.py",
    "tests/test_emergency_market_close.py",
    "tests/test_protection_branches.py",
    "tests/test_protection_take_profits.py",
    # Planning documents the plans and the hand-off promise.
    ".planning/phases/19-execution-plan-binding-price-check/19-CONTEXT.md",
    ".planning/phases/19-execution-plan-binding-price-check/19-NOTES.md",
    ".planning/phases/19-execution-plan-binding-price-check/19-RESEARCH.md",
    ".planning/phases/19-execution-plan-binding-price-check/19-DEC-D055-DRAFT.md",
    ".planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md",
)

# The planning files below are only required while the phase directory is in the checkout:
# `/gsd-cleanup` archives it and `/gsd-pr-branch` leaves `.planning/` out. The code, config and
# test inventory stays a hard requirement.
requires_phase19_planning = pytest.mark.skipif(
    not PHASE_DIR.is_dir(),
    reason="the Phase 19 planning directory is not in this checkout (archived or filtered)",
)


def test_phase19_artifacts_exist() -> None:
    planning_present = PHASE_DIR.is_dir()
    missing = [
        path
        for path in PHASE19_ARTIFACTS
        if not (ROOT / path).exists() and (planning_present or not path.startswith(".planning/"))
    ]
    assert missing == [], f"missing Phase 19 artifacts: {missing}"
    assert len(set(PHASE19_ARTIFACTS)) == len(PHASE19_ARTIFACTS)


# --------------------------------------------------------------------------- #
# Public symbols.
# --------------------------------------------------------------------------- #

PHASE19_SYMBOLS: dict[str, tuple[str, ...]] = {
    "src.execution.execution_limits": (
        "EXECUTION_LIMIT_KEYS",
        "NOT_CONFIGURED_WORD",
        "ExecutionLimits",
        "ExecutionLimitsFileMissing",
        "ExecutionLimitsInvalid",
        "ExecutionLimitsNotConfigured",
        "load_execution_limits",
        "parse_execution_limits",
    ),
    "src.execution.binding": (
        "BindingVerdict",
        "BoundPlan",
        "GEOMETRY_INVALID_AFTER_SNAP",
        "PLAN_SIDE_MISMATCH",
        "PLAN_SIGNAL_MISMATCH",
        "PLAN_SYMBOL_MISMATCH",
        "PROTECTIVE_WORKING_TYPE",
        "QUANTITY_ABOVE_APPROVED",
        "WORKING_TYPE_NOT_MARK_PRICE",
        "bind_plan",
        "check_quantity_bound",
        "check_snapped_geometry",
        "check_working_type",
        "recompute_plan_hash",
        "take_profit_levels",
    ),
    "src.execution.pre_placement": (
        "GTD_MIN_AHEAD_SECONDS",
        "HEDGE_MODE_UNSUPPORTED",
        "INVALIDATION_INPUT_UNAVAILABLE",
        "LIMITS_NOT_CONFIGURED",
        "MARK_PRICE_CROSSED_STOP",
        "MARK_PRICE_OUTSIDE_ZONE",
        "MARK_PRICE_UNAVAILABLE",
        "PLAN_INVALIDATED_BEFORE_PLACEMENT",
        "PLAN_STATUS_INVALID",
        "PrePlacementInputs",
        "SYMBOL_HAS_OPEN_ORDER",
        "SYMBOL_HAS_POSITION",
        "SYMBOL_STATE_UNAVAILABLE",
        "UNPROTECTED_POSITION_EXISTS",
        "VALIDITY_TOO_SHORT",
        "bar_close_invalidates",
        "check_invalidation",
        "check_mark_price",
        "check_plan_status",
        "check_position_mode",
        "check_remaining_validity",
        "check_symbol_free",
        "evaluate_pre_placement",
        "good_till_date_ms",
        "plan_invalidation_level",
    ),
    "src.domain.lot_filters": ("LotFilters",),
    "src.execution.lot_split": (
        "CloseSplit",
        "is_valid_market_part",
        "lot_filters_from_plan_snapshot",
        "next_close_part",
        "plan_close_parts",
        "quantize_to_lot",
    ),
    "src.execution.tp_sizing": ("TakeProfitSizing", "size_take_profits"),
    "src.execution.protection": (
        "ALERT_CLOSE_REQUIRED",
        "ALERT_TP_UNAVAILABLE",
        "BLOCKING_STATES",
        "CriticalAlertSink",
        "EmergencyCloser",
        "PlanProtection",
        "ProtectionAdapter",
        "ProtectionCoordinator",
        "ProtectionRegistry",
        "ProtectionState",
        "RestingEntry",
        "SAFE_MODE_CLOSE_REQUIRED",
        "SAFE_MODE_DB_FAILURE",
        "SAFE_MODE_ENTRY_WITHOUT_PROTECTIVE",
        "TERMINAL_ENTRY_STATUSES",
    ),
    "src.execution.emergency_close": (
        "ALERT_EMERGENCY_CLOSE_FAILED",
        "ALERT_EMERGENCY_CLOSE_NOT_SENT",
        "CloseAdapter",
        "EmergencyCloseResult",
        "EmergencyCloseStatus",
        "MarketEmergencyCloser",
        "SAFE_MODE_EMERGENCY_CLOSE_FAILED",
        "discover_next_attempt_no",
    ),
    "src.execution.live_context": ("LivePlacementContext",),
    "src.execution.order_ids": ("ROLE_CODES", "derive_close_order_id"),
    "src.adapters.binance_usdm": ("BinanceUsdmAdapter", "MarketCloseResult"),
}

# Methods Phase 19 added to the Binance adapter (plans 19-05 and 19-08).
PHASE19_ADAPTER_METHODS: tuple[str, ...] = (
    "get_mark_price",
    "symbol_lot_filters",
    "place_market_close",
)


def test_phase19_public_symbols_importable() -> None:
    problems: list[str] = []
    for module_name, names in PHASE19_SYMBOLS.items():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - the gate reports any import failure by name
            problems.append(f"{module_name}: import failed ({type(exc).__name__})")
            continue
        problems.extend(
            f"{module_name}.{name}: missing" for name in names if not hasattr(module, name)
        )
    assert problems == [], f"Phase 19 public symbols not importable: {problems}"


def test_phase19_adapter_methods_exist() -> None:
    from src.adapters.binance_usdm import BinanceUsdmAdapter

    missing = [name for name in PHASE19_ADAPTER_METHODS if not hasattr(BinanceUsdmAdapter, name)]
    assert missing == [], f"BinanceUsdmAdapter lacks {missing}"


# --------------------------------------------------------------------------- #
# Requirement to test.
# --------------------------------------------------------------------------- #

# requirement id -> (test file, test function name prefix) pairs.
REQUIREMENT_TESTS: dict[str, tuple[tuple[str, str], ...]] = {
    "APRV-01": (
        ("tests/test_execution_binding.py", "test_tracer_real_plan_binds_to_its_signal"),
        ("tests/test_execution_binding.py", "test_mutated_hashed_field_without_new_hash"),
        ("tests/test_execution_binding.py", "test_symbol_mismatch"),
    ),
    "APRV-02": (
        ("tests/test_execution_binding.py", "test_callback_or_approval_hash_that_differs"),
        (
            "tests/test_approval_replay_pg.py",
            "test_replayed_approve_after_restart_reaches_place_entry_zero_times",
        ),
        (
            "tests/test_callback_redelivery_pg.py",
            "test_two_concurrent_deliveries_of_the_same_approve_place_exactly_one_entry",
        ),
        ("tests/test_execution_manager.py", "test_q5_place_entry_is_sent_once_for_every_error"),
    ),
    "EXEC-01": (
        ("tests/test_execution_limits.py", "test_require_live_ready_refuses_naming_the_four"),
        ("tests/test_pre_placement.py", "test_evaluate_valid_case_passes"),
        ("tests/test_market_lot_split.py", "test_lot_filters_accepts_a_consistent_set"),
        ("tests/test_tp_sizing.py", "test_tracer_one_way_long_tp1_and_tp2_legs"),
        ("tests/test_binance_entry_gtd.py", "test_gtd_forwards_good_till_date_in_one_sdk_call"),
        ("tests/test_binance_market_close_adapter.py", "test_one_way_close_sends_one_market"),
        ("tests/test_protection_coordinator.py", "test_first_stream_fill_starts_the_stop"),
        ("tests/test_protection_router_rig.py", "test_a_routed_trade_frame_drives_the_stop"),
        ("tests/test_emergency_market_close.py", "test_tracer_one_part_closes_the_position"),
        ("tests/test_protection_take_profits.py", "test_tp_protected_then_the_next_step"),
        ("tests/test_fake_exchange_v2.py", "test_tracer_partial_fill_probe_position"),
    ),
    "EXEC-02": (
        ("tests/test_realized_risk_persistence_pg.py", "test_consume_stores_sized_risk"),
        ("tests/test_execution_write_ahead_pg.py", "test_crash_after_each_step_leaves_a_row"),
        (
            "tests/test_execution_write_ahead_pg.py",
            "test_the_coordinator_writes_the_stop_loss_intent_ahead_of_the_stop",
        ),
        (
            "tests/test_protection_branches.py",
            "test_branch_b5_definitive_stop_rejection_after_a_fill",
        ),
        ("tests/test_protection_branches.py", "test_branch_b3_both_ambiguous"),
        ("tests/test_execution_manager.py", "test_an_unknown_exchange_error_absent_by_the_probe"),
    ),
    "RISK-04": (
        ("tests/test_pre_placement.py", "test_check_symbol_free_verdicts"),
        ("tests/test_pre_placement.py", "test_check_mark_price_position"),
        ("tests/test_execution_binding.py", "test_check_quantity_bound"),
        ("tests/test_protection_branches.py", "test_branch_b2_entry_terminal_stop_unconfirmed"),
    ),
    "EXEC-07": (
        ("tests/test_tp_sizing.py", "test_tp1_fraction_constant_and_template_shape"),
        ("tests/test_tp_sizing.py", "test_tp_sizing_defines_no_fraction_constant"),
        ("tests/test_tp_sizing.py", "test_no_single_tp_fallback_exists"),
    ),
}


def _test_function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_phase19_requirement_tests_exist() -> None:
    problems: list[str] = []
    for requirement, pairs in REQUIREMENT_TESTS.items():
        assert pairs, f"{requirement} names no test"
        for relative, prefix in pairs:
            path = ROOT / relative
            if not path.exists():
                problems.append(f"{requirement}: {relative} does not exist")
            elif not any(name.startswith(prefix) for name in _test_function_names(path)):
                problems.append(f"{requirement}: {relative} defines no test starting {prefix!r}")
    assert problems == [], f"requirement-to-test pairs missing: {problems}"
    assert set(REQUIREMENT_TESTS) == {
        "APRV-01",
        "APRV-02",
        "EXEC-01",
        "EXEC-02",
        "RISK-04",
        "EXEC-07",
    }


# --------------------------------------------------------------------------- #
# Structural invariants.
# --------------------------------------------------------------------------- #

PHASE19_PURE_MODULES: tuple[str, ...] = (
    "src/execution/binding.py",
    "src/execution/pre_placement.py",
    "src/execution/lot_split.py",
    "src/execution/tp_sizing.py",
    "src/execution/protection.py",
    "src/execution/emergency_close.py",
    "src/execution/execution_limits.py",
    "src/execution/live_context.py",
    "src/domain/lot_filters.py",
)
PURE_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "binance*",
    "requests",
    "aiohttp",
    "sqlalchemy",
    "pydantic",
    "polars",
    "src.adapters",
    "src.backtest",
)
MANAGER_PATH = ROOT / "src" / "execution" / "manager.py"
EXECUTION_LIMITS_FILE = ROOT / "config" / "execution" / "execution-limits-v1.toml"


@pytest.mark.parametrize("relative", PHASE19_PURE_MODULES)
def test_invariant_1_pure_modules_have_no_sdk_float_or_clock(relative: str) -> None:
    path = ROOT / relative
    assert forbidden_imports(path, PURE_FORBIDDEN_IMPORTS) == []
    assert float_constructor_calls(path) == []
    assert wall_clock_calls(path) == []


def test_invariant_2_pinned_enums_and_role_codes_are_unchanged() -> None:
    from src.domain.enums import ExecutionIntentStatus, OrderRole, RejectionReason
    from src.execution.order_ids import ROLE_CODES

    # The new reason codes are plain strings documented in GLOSSARY 9.3, not enum members
    # (research F10): the enum keeps its 20 members.
    assert len(RejectionReason) == 20
    assert {member.name for member in OrderRole} == {
        "ENTRY",
        "STOP_LOSS",
        "TAKE_PROFIT_1",
        "TAKE_PROFIT_2",
    }
    assert {member.name for member in ExecutionIntentStatus} == {
        "INTENDED",
        "SENT",
        "ACKED",
        "REJECTED",
        "UNKNOWN",
    }
    assert ROLE_CODES == {
        "ENTRY": "EN",
        "STOP_LOSS": "SL",
        "TAKE_PROFIT_1": "T1",
        "TAKE_PROFIT_2": "T2",
    }


def _function_node(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in {path}")


def test_invariant_3_execute_approved_plan_places_no_protective_order() -> None:
    node = _function_node(MANAGER_PATH, "execute_approved_plan")
    attribute_calls = {
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }
    name_calls = {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert "place_algo_protective" not in attribute_calls, "the coordinator places the stop"
    assert "_place_protective_leg" not in name_calls, "the coordinator places the stop"


def test_invariant_4_the_execution_limits_file_has_no_placeholder_and_no_invented_number() -> None:
    from src.execution.execution_limits import (
        EXECUTION_LIMIT_KEYS,
        NOT_CONFIGURED_WORD,
        load_execution_limits,
    )

    assert load_execution_limits(EXECUTION_LIMITS_FILE) is not None
    document = tomllib.loads(EXECUTION_LIMITS_FILE.read_text(encoding="utf-8"))
    problems: list[str] = []
    for section, keys in EXECUTION_LIMIT_KEYS.items():
        for key in keys:
            value = document[section][key]
            label = document["provenance"][section][key]
            if label == "PLACEHOLDER":
                problems.append(f"{section}.{key}: provenance PLACEHOLDER")
            elif value == NOT_CONFIGURED_WORD:
                if label != NOT_CONFIGURED_WORD:
                    problems.append(f"{section}.{key}: unset value with label {label!r}")
            elif label != "DECISION":
                problems.append(f"{section}.{key}: a set value needs provenance DECISION")
    assert problems == [], f"execution limits file: {problems}"


def test_invariant_5_the_ratified_binance_limits_file_is_unchanged() -> None:
    ratified_file_tests.test_decisions_row_pins_the_limits_file_hash()
    ratified_file_tests.test_the_real_loader_accepts_the_ratified_file_with_the_record_values()


def test_invariant_6_the_frozen_protective_sizing_is_unchanged() -> None:
    import dataclasses

    from src.backtest.semantics import TP1_QUANTITY_FRACTION
    from src.execution.placement import (
        ProtectiveTemplate,
        build_sl_leg,
        quantize_protective_qty,
        size_protectives_to_filled_qty,
    )

    assert Decimal("0.5") == TP1_QUANTITY_FRACTION
    assert [field.name for field in dataclasses.fields(ProtectiveTemplate)] == [
        "stop_loss_trigger_price",
        "tp1_trigger_price",
        "tp2_trigger_price",
        "tp1_quantity_fraction",
    ]
    assert list(inspect.signature(size_protectives_to_filled_qty).parameters) == [
        "filled_quantity",
        "protective_template",
        "constraint_snapshot",
        "position_mode",
        "candidate_position_side",
    ]
    assert list(inspect.signature(quantize_protective_qty).parameters) == [
        "raw_quantity",
        "constraint_snapshot",
        "reference_price",
    ]
    assert list(inspect.signature(build_sl_leg).parameters) == [
        "protective_template",
        "position_mode",
        "candidate_position_side",
        "price_tick_size",
    ]


def test_invariant_7_no_execution_module_imports_the_backtest() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "src" / "execution").rglob("*.py"))
        if any(
            name == "src.backtest" or name.startswith("src.backtest.")
            for name in module_imports(path)
        )
    ]
    assert offenders == [], (
        "backtest parity is pinned in tests only, never imported by src.execution"
    )


def test_invariant_8_d055_stays_open_and_the_phase18_gate_is_green() -> None:
    phase18_gate.test_invariant_8_d055_stays_open()
    phase18_gate.test_invariant_7_the_decisions_row_pins_the_limits_file()
    lines = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines()
    d055 = [line for line in lines if line.startswith("| D055 |")]
    assert len(d055) == 1 and "OPEN" in d055[0]


def test_invariant_9_every_requirement_name_is_a_known_requirement() -> None:
    text = (ROOT / ".planning" / "REQUIREMENTS.md").read_text(encoding="utf-8")
    for requirement in REQUIREMENT_TESTS:
        assert f"**{requirement}**" in text, requirement
