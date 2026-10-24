"""Phase 22 gate (plan 22-16): the structural invariants of the leverage and margin guard.

This file asserts, against the real tree and without any network or live evidence:

- the two pure modules (`src/risk/liquidation.py`, `src/risk/margin_check.py`) read no wall clock,
  build no float, hold no quote-asset literal, import nothing outside the standard library and the
  project's pure layers, and hold no numeric literal except 0, 1 (and 10000, the basis-point
  denominator, in `margin_check`): no bracket, rate or leverage value is hard-coded (criterion 2);
  the four execution modules read no wall clock and import no adapter, store, SDK or database
  client (`PHASE22_PURE_MODULES`, `PHASE22_EXECUTION_MODULES`);
- `TARGET_LEVERAGE` is 5 and `TARGET_MARGIN_TYPE` is `ISOLATED` (D035);
  `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` is True since the owner's answer of
  2026-10-24 (DECISIONS D085; two Demo samples, to be re-checked on mainnet at the Phase 26
  canary); the three margin limit keys hold the owner's numbers 300, 60000 and 1000 with the
  provenance `DECISION`, are required and no longer listed by `unset_keys()` (O-2 and O-3, D085);
  `LiquidationFailurePolicy` has exactly CLOSE_POSITION and ALERT_ONLY (O-4: the owner chose
  CLOSE_POSITION, recorded for the Phase 24 composition);
- the `RejectionReason` enum still has 21 members (amendment A3) and no Phase 22 plain code is
  one of them; every plain code is a module-level string of its module and has its row in
  GLOSSARY 9.3; the migration head is `0012_reservation_margin`; the two configuration calls are on
  the shadow order surface; the nine error codes are REJECTED_DEFINITIVE on PLACEMENT only;
- the wiring facts: `ProtectionCoordinator` accepts `liquidation_watch` (default None), the
  placement context requires `margin_guard`, and gate 5f2 sits after the position mode and before
  the hand-off record;
- two things Phase 22 built but does NOT activate, pinned so a later change is made on purpose:
  nothing in `src/` writes `required_margin` (the Phase 24 issuer calls `register_request`), and
  nothing in `src/` or `scripts/` passes `liquidation_watch` to a coordinator (Phase 24 composes
  it, so EXEC-02 and D-12 are not active before then);
- each Phase 22 requirement has its named automated tests, resolved with `ast` and never imported
  or run (`REQUIREMENT_TESTS`); the owner records name O-1 to O-4; the Demo evidence plan and the
  fixture provenance carry their labels.

A failure message names the missing path, symbol or test. Nothing here changes behavior and nothing
here claims an owner item solved, a criterion Demo-proven or a requirement complete: the owner's
Demo run of 2026-10-24 gave single samples only (`22-DEMO-RESULTS.md`, demo-observed, not mainnet),
EXEC-01 and EXEC-02 stay Pending, criteria 1 to 3 stay NOT Demo-proven through the guard, no
Phase 19 OWNER-GAPS item (O-02 to O-05) is closed, and the owner items O-1 to O-4
(`22-OWNER-DECISIONS.md`) are DECIDED by the owner's answer of 2026-10-24 (DECISIONS D085):
setting the margin keys does not open the live path (fourteen required keys stay
`NOT_CONFIGURED`, `LIVE_ORDERS_DISABLED` stays) and the Telegram control for leverage and margin
type that the owner asked for is a requirement that is NOT built.

Evidence label: executed structural tests. Nothing here touches Binance, Telegram or a database;
the Alembic head is read from the script directory and needs no connection.
"""

from __future__ import annotations

import ast
import re
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    wall_clock_calls,
)

ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = ROOT / ".planning" / "phases" / "22-leverage-margin-liquidation-guard"

# --------------------------------------------------------------------------- #
# The module inventory.
# --------------------------------------------------------------------------- #

#: New pure modules (D-06, D-13): stdlib plus project types only. No clock, no float, no SDK.
#: The value is the set of numeric literals the module may hold.
PHASE22_PURE_MODULES: dict[str, frozenset[int]] = {
    "src/risk/liquidation.py": frozenset({0, 1, 10000}),
    "src/risk/margin_check.py": frozenset({0, 1, 10000}),
}

#: New execution modules: they take injected clocks and ports and import no adapter, store or SDK.
PHASE22_EXECUTION_MODULES: tuple[str, ...] = (
    "src/execution/symbol_config_guard.py",
    "src/execution/bracket_cache.py",
    "src/execution/margin_guard.py",
    "src/execution/liquidation_watch.py",
)

PURE_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "src.adapters",
    "src.persistence",
    "src.execution",
    "src.ops",
    "src.paper",
    "sqlalchemy",
    "binance*",
    "polars",
    "pandas",
    "numpy",
    "httpx",
)
EXECUTION_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "src.adapters",
    "src.persistence",
    "binance*",
    "sqlalchemy",
)

#: The quote asset is a parameter of the live path, never a literal (research Pitfall 10).
QUOTE_ASSET_LITERAL = "USDT"


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _numeric_literals(path: Path) -> list[Decimal]:
    """Every int or float constant and every `Decimal("text")` argument of a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[Decimal] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool):
                continue
            if isinstance(value, int | float):
                found.append(Decimal(repr(value)))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Decimal"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.append(Decimal(node.args[0].value))
    return found


def test_phase22_module_inventory_exists() -> None:
    missing = [
        relative
        for relative in (*PHASE22_PURE_MODULES, *PHASE22_EXECUTION_MODULES)
        if not (ROOT / relative).is_file()
    ]
    assert missing == [], f"missing Phase 22 modules: {missing}"


@pytest.mark.parametrize("relative", sorted(PHASE22_PURE_MODULES))
def test_invariant_1_pure_modules_have_no_clock_no_float_no_client_and_no_quote_literal(
    relative: str,
) -> None:
    path = ROOT / relative
    assert wall_clock_calls(path) == [], f"{relative} reads a clock"
    assert float_constructor_calls(path) == [], f"{relative} builds a float"
    assert forbidden_imports(path, PURE_FORBIDDEN_IMPORTS) == [], f"{relative} imports a client"
    assert QUOTE_ASSET_LITERAL not in _string_constants(path), (
        f"{relative} holds the literal {QUOTE_ASSET_LITERAL!r}"
    )


@pytest.mark.parametrize("relative", sorted(PHASE22_PURE_MODULES))
def test_invariant_1a_pure_modules_hold_no_bracket_rate_or_leverage_number(relative: str) -> None:
    """Criterion 2: no hard-coded bracket, maintenance rate, fee rate or leverage in the logic."""
    allowed = {Decimal(number) for number in PHASE22_PURE_MODULES[relative]}
    literals = _numeric_literals(ROOT / relative)
    stray = sorted({str(value) for value in literals if value not in allowed})
    assert stray == [], f"{relative} holds numeric literals outside {sorted(allowed)}: {stray}"


@pytest.mark.parametrize("relative", sorted(PHASE22_PURE_MODULES))
def test_invariant_1b_pure_modules_are_scanned_by_the_float_guard(relative: str) -> None:
    from tests.test_domain_no_float import SCANNED_FILES

    assert relative in SCANNED_FILES, f"{relative} is not in tests/test_domain_no_float.py"


@pytest.mark.parametrize("relative", PHASE22_EXECUTION_MODULES)
def test_invariant_1c_execution_modules_read_no_clock_and_import_no_adapter_or_store(
    relative: str,
) -> None:
    path = ROOT / relative
    assert wall_clock_calls(path) == [], f"{relative} reads a clock"
    assert forbidden_imports(path, EXECUTION_FORBIDDEN_IMPORTS) == [], (
        f"{relative} imports an adapter, a store or the SDK"
    )
    assert QUOTE_ASSET_LITERAL not in _string_constants(path), (
        f"{relative} holds the literal {QUOTE_ASSET_LITERAL!r}"
    )


# --------------------------------------------------------------------------- #
# Constants: the D035 target, the evidence-gated netting switch, the failure policy.
# --------------------------------------------------------------------------- #


def test_invariant_2_the_target_is_the_d035_cap_and_isolated() -> None:
    from src.execution import symbol_config_guard

    assert symbol_config_guard.TARGET_LEVERAGE == 5, "D035 caps the leverage at 5x"
    assert symbol_config_guard.TARGET_MARGIN_TYPE == "ISOLATED", "D035 fixes ISOLATED margin"


def test_invariant_3_the_netting_constant_is_true_since_d085() -> None:
    from src.risk import margin_check

    assert margin_check.AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED is True, (
        "the owner flipped this constant on 2026-10-24 (DECISIONS D085) on two Demo samples; "
        "only an owner DECISIONS row may change it again"
    )
    decisions = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    rows = [line for line in decisions.splitlines() if line.startswith("| D085 |")]
    assert len(rows) == 1, "DECISIONS must carry exactly one D085 row"
    for needle in (
        "2026-10-24, owner answer",
        "AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED",
        "CLOSE_POSITION",
        "NOT designed and NOT built",
        "SymbolConfigGuard",
        "fourteen required keys stay `NOT_CONFIGURED`",
    ):
        assert needle in rows[0], f"D085 does not mention {needle!r}"


def test_invariant_4_the_failure_policy_has_exactly_the_two_owner_choices() -> None:
    from src.execution.liquidation_watch import LiquidationFailurePolicy

    assert {member.name for member in LiquidationFailurePolicy} == {
        "CLOSE_POSITION",
        "ALERT_ONLY",
    }, "O-4: both choices exist, neither is a default"


# --------------------------------------------------------------------------- #
# The three margin limits hold the owner's numbers since 2026-10-24 (O-2, O-3, DECISIONS D085).
# --------------------------------------------------------------------------- #

EXECUTION_LIMITS_FILE = ROOT / "config" / "execution" / "execution-limits-v1.toml"
MARGIN_LIMIT_KEYS: tuple[str, ...] = (
    "margin.liquidation_buffer_bps",
    "margin.max_bracket_age_ms",
    "margin.headroom_bps",
)
MARGIN_LIMIT_DECIDED: dict[str, int] = {
    "margin.liquidation_buffer_bps": 300,
    "margin.max_bracket_age_ms": 60000,
    "margin.headroom_bps": 1000,
}


def test_invariant_5_the_margin_limits_are_required_and_hold_the_owner_numbers() -> None:
    from src.execution.execution_limits import (
        ALERT_ONLY_LIMIT_KEYS,
        NOT_CONFIGURED_WORD,
        load_execution_limits,
    )

    document = tomllib.loads(EXECUTION_LIMITS_FILE.read_text(encoding="utf-8"))
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    unset = limits.unset_keys()
    for dotted in MARGIN_LIMIT_KEYS:
        section, key = dotted.split(".")
        assert document[section][key] == MARGIN_LIMIT_DECIDED[dotted], f"{dotted} (D085)"
        assert document["provenance"][section][key] == "DECISION", f"{dotted} provenance"
        assert dotted not in ALERT_ONLY_LIMIT_KEYS, f"{dotted} must be required, not alert-only"
        assert dotted not in unset, f"{dotted} is still listed as unset"
    # Setting them does not open the live path: other required keys stay NOT_CONFIGURED.
    assert len(unset) == 14, "fourteen required keys stay NOT_CONFIGURED (D085)"
    assert NOT_CONFIGURED_WORD in EXECUTION_LIMITS_FILE.read_text(encoding="utf-8")


def test_invariant_5b_the_phase_21_key_keeps_the_state_recorded_in_the_file() -> None:
    """The equity-age key is read from the file, not pinned to a number here (DECISIONS D084)."""
    from src.execution.execution_limits import NOT_CONFIGURED_WORD, load_execution_limits

    document = tomllib.loads(EXECUTION_LIMITS_FILE.read_text(encoding="utf-8"))
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    value = document["account"]["max_equity_age_ms"]
    assert (value == NOT_CONFIGURED_WORD) == ("account.max_equity_age_ms" in limits.unset_keys())


# --------------------------------------------------------------------------- #
# Vocabulary: the enum is untouched, every plain code has a module and a GLOSSARY row.
# --------------------------------------------------------------------------- #

#: Plain-string rejection-style codes (D-16 as amended by A3) and the module that defines each.
PHASE22_PLAIN_CODES: dict[str, str] = {
    "LIQUIDATION_TOO_CLOSE": "src/risk/liquidation.py",
    "LIQUIDATION_INPUT_UNAVAILABLE": "src/risk/liquidation.py",
    "LEVERAGE_ABOVE_BRACKET": "src/risk/liquidation.py",
    "NOTIONAL_ABOVE_MAX": "src/risk/liquidation.py",
    "MARGIN_CONFIG_UNVERIFIED": "src/execution/symbol_config_guard.py",
    "MARGIN_CONFIG_CHANGE_REFUSED": "src/execution/symbol_config_guard.py",
    "AUTO_ADD_MARGIN_ENABLED": "src/execution/symbol_config_guard.py",
    "MARGIN_MODE_UNSUPPORTED": "src/execution/margin_guard.py",
    "LIQUIDATION_UNKNOWN_AFTER_FILL": "src/execution/liquidation_watch.py",
    "LIQUIDATION_TOO_CLOSE_AFTER_FILL": "src/execution/liquidation_watch.py",
    "LIQUIDATION_PRICE_DIFFERS": "src/execution/liquidation_watch.py",
}

#: Blocked reasons of the account judgement (not rejection reasons).
PHASE22_BLOCKED_REASONS: dict[str, str] = {
    "READING_UNUSABLE": "src/risk/margin_check.py",
    "HEDGE_MODE": "src/risk/margin_check.py",
    "MULTI_ASSETS_MODE": "src/risk/margin_check.py",
}

STATUS_PREFIX = "proposed canonical, promote in Phase"
BLOCKED_STATUS = "blocked reason, not a rejection reason"


def _glossary_table_rows(heading: str, next_heading: str) -> dict[str, list[str]]:
    """First-cell code -> all cells, for the table under a `###` heading of docs/GLOSSARY.md."""
    text = (ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.index(next_heading, start)
    rows: dict[str, list[str]] = {}
    for line in text[start:end].splitlines():
        match = re.match(r"\|\s*`([A-Z0-9_]+)`\s*\|", line)
        if match is None:
            continue
        code = match.group(1)
        assert code not in rows, f"{code} appears twice under {heading!r}"
        rows[code] = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return rows


def _source_string_constants(relative: str) -> set[str]:
    """String values assigned to a module-level name in `relative` (the emitted codes)."""
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    values: set[str] = set()
    for node in tree.body:
        value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            values.add(value.value)
    return values


def test_invariant_6_the_rejection_reason_enum_still_has_21_members() -> None:
    from src.domain.enums import RejectionReason

    members = {member.value for member in RejectionReason}
    assert len(RejectionReason) == 21, "Phase 22 adds no rejection reason (amendment A3)"
    assert "INSUFFICIENT_MARGIN" in members
    assert members.isdisjoint(PHASE22_PLAIN_CODES), "a Phase 22 plain code became an enum member"
    assert members.isdisjoint(PHASE22_BLOCKED_REASONS)


def test_invariant_6b_every_plain_code_is_defined_in_its_module() -> None:
    for code, module in {**PHASE22_PLAIN_CODES, **PHASE22_BLOCKED_REASONS}.items():
        assert code in _source_string_constants(module), f"{module} no longer defines {code}"


def test_invariant_6c_glossary_93_lists_every_plain_code_once_with_its_module() -> None:
    rows = _glossary_table_rows("### 9.3 ", "### 9.4 ")
    for code, module in PHASE22_PLAIN_CODES.items():
        assert code in rows, f"GLOSSARY 9.3 lacks {code}"
        assert module in rows[code][1], f"{code}: 'Emitted in' does not name {module}"
        assert rows[code][3].startswith(STATUS_PREFIX), f"{code}: status {rows[code][3]!r}"
    for code, module in PHASE22_BLOCKED_REASONS.items():
        assert code in rows, f"GLOSSARY 9.3 lacks {code}"
        assert module in rows[code][1], f"{code}: 'Emitted in' does not name {module}"
        assert rows[code][3] == BLOCKED_STATUS, f"{code}: status {rows[code][3]!r}"


def test_invariant_6d_glossary_91_lists_exactly_the_enum() -> None:
    from src.domain.enums import RejectionReason

    text = (ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8")
    block = text[text.index("### 9.1 ") : text.index("### 9.2 ")]
    codes = re.search(r"```text\n(.*?)```", block, re.DOTALL)
    assert codes is not None
    listed = set(codes.group(1).split())
    assert listed == {member.value for member in RejectionReason}


# --------------------------------------------------------------------------- #
# Migration head, shadow surface, error taxonomy.
# --------------------------------------------------------------------------- #


def test_invariant_7_the_migration_head_is_0012_reservation_margin() -> None:
    from tests.pg_support import alembic_head_revision

    assert alembic_head_revision() == "0012_reservation_margin", (
        "plan 22-08 set the head to 0012; a later migration must update this gate on purpose"
    )


def _frozenset_strings(relative: str, name: str) -> set[str]:
    """The string members of a module-level `name = frozenset({...})` (read with ast)."""
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return {
                element.value
                for element in ast.walk(node.value)
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    raise AssertionError(f"{relative} defines no {name}")


def test_invariant_8_the_two_configuration_calls_are_on_the_shadow_order_surface() -> None:
    surface = _frozenset_strings("tests/test_paper_shadow_isolation.py", "ORDER_SURFACE")
    assert {"change_margin_type", "change_initial_leverage"} <= surface


PHASE22_ERROR_CODES: tuple[int, ...] = (
    -4046,
    -4047,
    -4048,
    -4028,
    -4161,
    -4168,
    -4209,
    -2027,
    -2028,
)


def test_invariant_9_the_nine_error_codes_are_definitive_on_placement_only() -> None:
    from src.domain.exchange_errors import (
        ERROR_CODE_TABLE,
        CallKind,
        ExchangeErrorCategory,
    )

    for code in PHASE22_ERROR_CODES:
        entry = ERROR_CODE_TABLE[code]
        by_kind = entry.categories_by_call_kind
        assert by_kind[CallKind.PLACEMENT] is ExchangeErrorCategory.REJECTED_DEFINITIVE, code
        others = [kind for kind in CallKind if kind is not CallKind.PLACEMENT]
        assert all(by_kind.get(kind) is None for kind in others), (
            f"{code} classifies on a call kind other than PLACEMENT"
        )


# --------------------------------------------------------------------------- #
# Wiring facts read with ast: the coordinator hook, the required guard, gate 5f2.
# --------------------------------------------------------------------------- #


def _class_node(relative: str, name: str) -> ast.ClassDef:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{relative} defines no class {name}")


def test_invariant_10_the_coordinator_accepts_liquidation_watch_with_default_none() -> None:
    klass = _class_node("src/execution/protection.py", "ProtectionCoordinator")
    init = next(
        node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    names = [arg.arg for arg in init.args.kwonlyargs]
    assert "liquidation_watch" in names
    default = init.args.kw_defaults[names.index("liquidation_watch")]
    assert isinstance(default, ast.Constant) and default.value is None, (
        "liquidation_watch must default to None: Phase 24 composes it (EXEC-02, D-12)"
    )


def test_invariant_11_the_live_context_requires_the_margin_guard() -> None:
    klass = _class_node("src/execution/live_context.py", "LivePlacementContext")
    field = next(
        node
        for node in klass.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "margin_guard"
    )
    assert field.value is None, "margin_guard must have no default (CR-07)"


def test_invariant_12_gate_5f2_sits_after_the_position_mode_and_before_the_hand_off_record() -> (
    None
):
    source = (ROOT / "src/execution/manager.py").read_text(encoding="utf-8")
    mode = source.index("await adapter.get_position_mode()")
    guard = source.index("live_context.margin_guard.evaluate(")
    hand_off = source.index("resting_entry = RestingEntry(")
    assert source.count("margin_guard.evaluate(") == 1
    assert mode < guard < hand_off, "gate 5f2 is out of order"


# --------------------------------------------------------------------------- #
# Built but not active: pinned so Phase 24 changes them on purpose (plan-check addenda).
# --------------------------------------------------------------------------- #


def _python_files(directory: str) -> list[Path]:
    return sorted(
        path for path in (ROOT / directory).rglob("*.py") if "__pycache__" not in path.parts
    )


def _calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def test_invariant_13_nothing_in_src_writes_required_margin() -> None:
    """Phase 22 supplies the column and the claims reader; the Phase 24 issuer writes the value.

    Until then every RESERVED or PLACED row reads as an unknown margin and a plan placed while
    another claim exists is refused UNCERTAIN_ACCOUNT_STATE. This is why the "approved but
    unplaced plans" part of criterion 3 is proven on fakes and the PostgreSQL claims reader only.
    """
    offenders: list[str] = []
    for path in _python_files("src"):
        relative = path.relative_to(ROOT).as_posix()
        for call in _calls(path):
            keywords = {keyword.arg for keyword in call.keywords}
            if _call_name(call) == "register_request":
                offenders.append(f"{relative}:{call.lineno} calls register_request")
            if "required_margin" in keywords and relative != "src/persistence/risk_reservations.py":
                offenders.append(f"{relative}:{call.lineno} passes required_margin")
    assert offenders == [], (
        f"a Phase 24 composition appeared; update this gate and 22-DEFERRED.md on purpose: "
        f"{offenders}"
    )


def test_invariant_14_nothing_passes_liquidation_watch_to_a_coordinator_yet() -> None:
    """`liquidation_watch` is built and tested, but ProtectionCoordinator defaults it to None.

    EXEC-02 and D-12 are not active until the Phase 24 composition passes a watch and a policy.
    """
    offenders: list[str] = []
    for directory in ("src", "scripts"):
        for path in _python_files(directory):
            relative = path.relative_to(ROOT).as_posix()
            for call in _calls(path):
                if any(keyword.arg == "liquidation_watch" for keyword in call.keywords):
                    offenders.append(f"{relative}:{call.lineno} passes liquidation_watch")
                if _call_name(call) == "LiquidationWatch" and (
                    relative != "src/execution/liquidation_watch.py"
                ):
                    offenders.append(f"{relative}:{call.lineno} builds a LiquidationWatch")
    assert offenders == [], (
        f"a Phase 24 composition appeared; update this gate and 22-DEFERRED.md on purpose: "
        f"{offenders}"
    )


# --------------------------------------------------------------------------- #
# Requirement -> named tests (resolved with ast, never imported).
# --------------------------------------------------------------------------- #

REQUIREMENT_TESTS: dict[str, tuple[tuple[str, str], ...]] = {
    "RISK-01": (
        # The pure available-margin predicate (criterion 3) and its goldens.
        ("tests/test_margin_check.py", "test_recorded_demo_shape_initial_margin"),
        (
            "tests/test_margin_check.py",
            "test_recorded_demo_2019_shape_is_refused_insufficient_margin",
        ),
        (
            "tests/test_margin_check.py",
            "test_passing_plan_needs_margin_fees_and_headroom_equality_passes",
        ),
        ("tests/test_margin_check.py", "test_one_unit_short_of_equality_fails"),
        ("tests/test_margin_check.py", "test_end_to_end_claims_to_verdict"),
        (
            "tests/test_margin_check.py",
            "test_netting_constant_is_true_since_the_owner_decision_d085",
        ),
        # The account judgement (criterion 4: one-way, single-asset only).
        ("tests/test_margin_check.py", "test_a_fresh_recorded_reading_is_ok"),
        (
            "tests/test_margin_check.py",
            "test_the_refusal_order_is_unusable_then_hedge_then_multi_assets",
        ),
        (
            "tests/test_margin_guard.py",
            "test_a_hedge_or_multi_asset_account_is_refused_before_anything_is_mutated",
        ),
        # The guard end to end over the recorded Demo account, and the headroom boundary.
        (
            "tests/test_margin_guard.py",
            "test_recorded_crossed_x20_account_flows_through_every_check_to_one_pass",
        ),
        (
            "tests/test_margin_guard.py",
            "test_the_headroom_boundary_equal_passes_and_one_unit_below_fails",
        ),
        # The request the manager hands the guard is exactly what is placed.
        (
            "tests/test_execution_manager.py",
            "test_gate_5f2_orders_the_position_mode_the_guard_and_the_placement",
        ),
    ),
    "RISK-02": (
        # The liquidation price from the exchange brackets (criterion 2): goldens and boundaries.
        ("tests/test_liquidation_price.py", "test_g1_long_small_quantity"),
        ("tests/test_liquidation_price.py", "test_g2_short_small_quantity"),
        (
            "tests/test_liquidation_price.py",
            "test_g3_long_uses_the_bracket_of_the_liquidation_notional_not_of_the_entry",
        ),
        ("tests/test_liquidation_price.py", "test_g4_short_uses_bracket_two"),
        ("tests/test_liquidation_price.py", "test_long_boundary_is_strict"),
        ("tests/test_liquidation_price.py", "test_short_boundary_is_strict"),
        ("tests/test_liquidation_price.py", "test_g6_matches_the_recorded_demo_liquidation_price"),
        ("tests/test_liquidation_price.py", "test_entry_notional_above_the_top_cap_is_refused"),
        ("tests/test_liquidation_price.py", "test_leverage_above_the_entry_bracket_is_refused"),
        # The bounded-age bracket cache.
        (
            "tests/test_bracket_cache.py",
            "test_recorded_demo_table_reaches_the_liquidation_verdict_through_the_real_adapter",
        ),
        (
            "tests/test_bracket_cache.py",
            "test_a_notional_coefficient_other_than_one_makes_the_set_unusable",
        ),
        # The refusal matrix of the guard.
        (
            "tests/test_margin_guard.py",
            "test_every_refusal_has_its_exact_plain_code_and_touches_nothing_later",
        ),
        ("tests/test_margin_guard.py", "test_the_first_refusal_in_the_fixed_order_wins"),
        # The claims of other plans: fakes and the PostgreSQL claims reader only (criterion 3).
        ("tests/test_margin_check.py", "test_other_claims_margin_netting"),
        (
            "tests/test_margin_check.py",
            "test_unknown_other_claims_are_uncertain_account_state_not_insufficient",
        ),
        (
            "tests/test_risk_reservation_margin_pg.py",
            "test_a_reserved_plan_with_a_margin_is_a_claim_and_a_new_store_instance_rebuilds_it",
        ),
        (
            "tests/test_risk_reservation_margin_pg.py",
            "test_a_legacy_form_request_reads_as_an_unknown_margin_never_zero",
        ),
        ("tests/test_risk_reservation_margin_pg.py", "test_a_released_plan_is_no_longer_a_claim"),
        # 22-REVIEW WR-07: the claim amount is derived from the row, never trusted as stored.
        (
            "tests/test_risk_reservations.py",
            "test_a_request_whose_required_margin_is_not_quantity_x_price_over_leverage_is_refused",
        ),
        (
            "tests/test_risk_reservation_margin_pg.py",
            "test_a_stored_margin_that_differs_from_the_derived_one_reads_as_an_unknown_claim",
        ),
    ),
    "EXEC-01": (
        # The configuration guard (criterion 1).
        (
            "tests/test_symbol_config_guard.py",
            "test_tracer_the_recorded_crossed_x20_flat_symbol_becomes_isolated_x5",
        ),
        ("tests/test_symbol_config_guard.py", "test_ensure_is_idempotent_across_runs"),
        (
            "tests/test_symbol_config_guard.py",
            "test_a_non_flat_crossed_symbol_is_refused_with_zero_posts",
        ),
        (
            "tests/test_symbol_config_guard.py",
            "test_a_post_that_answers_200_without_changing_the_state_is_unverified",
        ),
        (
            "tests/test_symbol_config_guard.py",
            "test_auto_add_margin_on_the_first_read_is_refused_before_any_post",
        ),
        # The adapter reads and the two mutating calls.
        (
            "tests/test_leverage_margin_adapter.py",
            "test_symbol_config_snapshot_reads_the_recorded_demo_crossed_x20",
        ),
        (
            "tests/test_leverage_margin_adapter.py",
            "test_leverage_brackets_snapshot_reads_the_recorded_demo_table_as_exact_decimals",
        ),
        (
            "tests/test_leverage_margin_adapter.py",
            "test_change_margin_type_sends_one_signed_call_with_the_sdk_enum",
        ),
        (
            "tests/test_leverage_margin_adapter.py",
            "test_change_initial_leverage_sends_one_signed_call",
        ),
        # Gate 5f2: a refusal consumes nothing; a pass completes the in-memory snapshot (G4-039).
        (
            "tests/test_execution_manager.py",
            "test_a_guard_refusal_returns_its_code_and_consumes_nothing",
        ),
        (
            "tests/test_execution_manager.py",
            "test_a_pass_hands_the_registry_the_snapshot_the_exchange_verified",
        ),
        (
            "tests/test_snapshot_margin_leverage.py",
            "test_the_guard_verified_values_complete_the_snapshot_and_make_it_valid_for_live",
        ),
        (
            "tests/test_snapshot_margin_leverage.py",
            "test_a_manager_placement_with_a_real_verdict_hands_protection_a_valid_snapshot",
        ),
    ),
    "EXEC-02": (
        # The post-fill liquidation judgement (built, not active before Phase 24).
        (
            "tests/test_liquidation_watch.py",
            "test_an_exchange_value_inside_the_buffer_fails_by_policy",
        ),
        (
            "tests/test_liquidation_watch.py",
            "test_the_predicate_is_strict_at_the_boundary_and_measured_from_the_fill_price",
        ),
        ("tests/test_liquidation_watch.py", "test_an_unknown_exchange_value_fails_closed"),
        (
            "tests/test_liquidation_watch.py",
            "test_the_recorded_demo_isolated_long_differs_by_the_rounded_wallet_only",
        ),
        (
            "tests/test_liquidation_watch.py",
            "test_the_policy_is_a_required_keyword_with_no_default",
        ),
        # The coordinator hook: CLOSE_REQUIRED through the existing path.
        (
            "tests/test_protection_liquidation.py",
            "test_close_verdict_enters_close_required_once_and_keeps_the_stop",
        ),
        (
            "tests/test_protection_liquidation.py",
            "test_close_verdict_with_the_real_closer_ends_flat_through_one_reduce_only_close",
        ),
        (
            "tests/test_protection_liquidation.py",
            "test_alert_only_failed_journals_and_alerts_but_never_closes",
        ),
        ("tests/test_protection_liquidation.py", "test_it_never_runs_before_the_stop_is_confirmed"),
    ),
}


def _test_function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_invariant_15_each_phase22_requirement_has_its_named_tests() -> None:
    assert set(REQUIREMENT_TESTS) == {"RISK-01", "RISK-02", "EXEC-01", "EXEC-02"}
    problems: list[str] = []
    for requirement, pairs in REQUIREMENT_TESTS.items():
        assert pairs, f"{requirement} names no test"
        for relative, name in pairs:
            path = ROOT / relative
            if not path.exists():
                problems.append(f"{requirement}: {relative} does not exist")
            elif name not in _test_function_names(path):
                problems.append(f"{requirement}: {relative} defines no test {name!r}")
    assert problems == [], f"requirement-to-test pairs missing: {problems}"


def test_invariant_15b_every_requirement_name_is_a_known_requirement() -> None:
    planning = ROOT / ".planning" / "REQUIREMENTS.md"
    if not planning.is_file():
        pytest.skip("REQUIREMENTS.md is not in this checkout (filtered)")
    text = planning.read_text(encoding="utf-8")
    for requirement in REQUIREMENT_TESTS:
        assert f"**{requirement}**" in text, requirement


# --------------------------------------------------------------------------- #
# The owner records name O-1 to O-4; the Demo evidence plan and fixtures keep their labels.
# --------------------------------------------------------------------------- #

OWNER_ITEMS: tuple[str, ...] = tuple(f"O-{number}" for number in range(1, 5))


def test_invariant_16_the_owner_decisions_and_the_deferred_register_name_o1_to_o4() -> None:
    if not PHASE_DIR.is_dir():
        pytest.skip(".planning/phases/22-* is not in this checkout (filtered)")
    problems: list[str] = []
    for name in ("22-OWNER-DECISIONS.md", "22-DEFERRED.md"):
        path = PHASE_DIR / name
        if not path.is_file():
            problems.append(f"{name} does not exist")
            continue
        text = path.read_text(encoding="utf-8")
        problems.extend(f"{name} does not name {item}" for item in OWNER_ITEMS if item not in text)
    assert problems == [], f"owner records incomplete: {problems}"


def test_invariant_17_the_owner_items_are_decided_and_no_register_overclaims() -> None:
    if not PHASE_DIR.is_dir():
        pytest.skip(".planning/phases/22-* is not in this checkout (filtered)")
    decisions = (PHASE_DIR / "22-OWNER-DECISIONS.md").read_text(encoding="utf-8")
    for item in OWNER_ITEMS:
        section = re.search(rf"^## {item}\b.*?(?=^## |\Z)", decisions, re.DOTALL | re.MULTILINE)
        assert section is not None, f"22-OWNER-DECISIONS.md has no section {item}"
        assert "Status: DECIDED" in section.group(0), f"{item} is not recorded as DECIDED"
        assert "D085" in section.group(0), f"{item} does not cite DECISIONS D085"
    assert "đòn bẩy x5, isolated, có thể config thông qua telegram" in decisions
    deferred = (PHASE_DIR / "22-DEFERRED.md").read_text(encoding="utf-8")
    assert "liquidation_watch" in deferred and "NOT active" in deferred
    assert "required_margin" in deferred and "register_request" in deferred
    assert "NOT Demo-proven" in deferred
    # The Telegram control is a new owner requirement that is recorded and NOT built.
    assert "set the leverage and the margin type from Telegram" in deferred
    assert "NOT designed and NOT built" in deferred
    assert "future phase (Phase 24 composition or a new phase)" in deferred
    assert "SymbolConfigGuard" in deferred and "two-step confirm" in deferred
    # No claim that a Phase 19 OWNER-GAPS item (O-02 to O-05) is solved or closed by this answer.
    for text in (decisions, deferred):
        lowered = text.lower()
        for claim in ("o-02 is closed", "o-03 is closed", "o-04 is closed", "o-05 is closed"):
            assert claim not in lowered, claim


def test_invariant_18_the_demo_evidence_plan_names_every_sj3_case_and_the_unproven_label() -> None:
    text = (ROOT / ".planning" / "DEMO-EVIDENCE-PLAN.md").read_text(encoding="utf-8")
    assert "not Demo-proven" in text
    sj3 = _sj3_cases()
    assert len(sj3) == 6, sj3
    missing = [case for case in sj3 if case not in text]
    assert missing == [], f"DEMO-EVIDENCE-PLAN.md lacks cases {missing}"


def _sj3_cases() -> tuple[str, ...]:
    tree = ast.parse((ROOT / "scripts" / "demo_probe.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SJ3_CASES"
            and node.value is not None
        ):
            return tuple(
                element.value
                for element in ast.walk(node.value)
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
    raise AssertionError("scripts/demo_probe.py defines no SJ3_CASES")


def test_invariant_19_the_deferred_register_names_every_sj3_case() -> None:
    if not PHASE_DIR.is_dir():
        pytest.skip(".planning/phases/22-* is not in this checkout (filtered)")
    deferred = (PHASE_DIR / "22-DEFERRED.md").read_text(encoding="utf-8")
    missing = [case for case in _sj3_cases() if case not in deferred]
    assert missing == [], f"22-DEFERRED.md lacks cases {missing}"


def test_invariant_20_the_fixture_readme_keeps_the_provenance_labels() -> None:
    text = (ROOT / "tests" / "fixtures" / "phase22" / "README.md").read_text(encoding="utf-8")
    assert "RECORDED_DEMO" in text
    assert "demo-observed, not mainnet" in text


def test_invariant_21_the_claim_amount_is_derived_and_the_placed_instant_is_the_ack() -> None:
    """22-REVIEW WR-06 and WR-07, pinned in code and not only in prose.

    The amount of a margin claim is `quantity x margin_entry_price / margin_leverage` by the one
    definition `margin_for_reservation`: the request refuses any other value and the claims reader
    derives the figure from the row. `placed_at_utc` is the instant the exchange ACKNOWLEDGED the
    entry, read after the POST answer: the netting rule of `other_claims_margin` compares it with
    the stamp of the account reading, which is taken before the reading's first request.
    """
    from src.persistence.risk_reservations import PgRiskReservationStore
    from src.risk import reservations
    from src.risk.margin_check import MarginClaim

    assert "margin_for_reservation" in reservations.__all__
    reader = (ROOT / "src" / "persistence" / "risk_reservations.py").read_text(encoding="utf-8")
    assert "margin_for_reservation(" in reader
    mark_placed_doc = PgRiskReservationStore.mark_placed.__doc__ or ""
    assert "AFTER the exchange ACKNOWLEDGED" in mark_placed_doc
    assert "never before the POST" in mark_placed_doc
    assert "ACKNOWLEDGED" in (MarginClaim.__doc__ or "")
    # The stamp of the reading is taken before its first request (account_equity.refresh).
    equity = (ROOT / "src" / "execution" / "account_equity.py").read_text(encoding="utf-8")
    assert "stamped with the injected clock BEFORE the first request" in equity
