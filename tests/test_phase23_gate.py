"""Phase 23 gate (plan 23-13): the structural invariants of the Telegram approval hardening.

This file asserts, against the real tree and without any network or live evidence:

- the second, independent gate (D-01, D-02): `authorized_user_ids` is a required keyword-only
  parameter without a default on `on_callback` and `build_application`, the variable
  `TELEGRAM_AUTHORIZED_USER_IDS` is an allowed environment name and is named in both env examples;
  `build_application` registers an error handler (D-08);
- the vocabulary (D-15 as amended by orchestrator resolution 7): `RejectionReason` still has 21
  members and GLOSSARY 9.1 equals it; every plain code Phase 23 added is defined in its module and
  has its row in GLOSSARY 9.3 (the deliberate amendment of D-15's wording is stated there);
- purity (D-09, D-13, D-17): the new pure modules read no wall clock and build no float; the
  confirm core imports nothing order-capable, Telegram-facing or from `src.paper`; the desk and
  the flow import no `src.execution.manager`, no Binance adapter and never name
  `execute_approved_plan` (the only seam to placement is the injected `on_confirmed`);
- messages (D-14): no generated DEMO/LIVE/SIMULATE golden carries `Asia/Ho_Chi_Minh` or a
  `Display:` line, while the SHADOW time pair still carries it;
- the migration head is `0014_decided_excl_expired` (D-16, the owner's O-2 answer (a));
- live placement is still disabled (`LiveEnablementController` default);
- each Phase 23 requirement has its named automated tests, resolved with `ast` and never imported
  or run (`REQUIREMENT_TESTS`).

A failure message names the missing path, symbol or test. Nothing here changes behavior and nothing
here claims an owner item solved, a live behavior verified or a requirement complete: APRV-01 and
APRV-02 stay Complete (Phase 8) with Phase 23 hardening at library level, PAPER-02 stays Pending
(Phase 16 closes it), and nothing of this phase is composed into a running process (Phase 24).

Evidence label: executed structural tests. Nothing here touches Binance, Telegram or a database;
the Alembic head is read from the script directory and needs no connection.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    wall_clock_calls,
)

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
# The module inventory.
# --------------------------------------------------------------------------- #

#: Pure modules of Phase 23: injected clocks and ports, no wall clock, no float constructor.
PHASE23_PURE_MODULES: tuple[str, ...] = (
    "src/approval/confirm_core.py",
    "src/risk/money_at_stake.py",
    "src/ops/alert_wording.py",
    "src/execution/confirm_recheck.py",
    "src/execution/prior_outcome.py",
)

#: The confirm core must be usable by SHADOW, DEMO and LIVE alike: it imports none of these.
CONFIRM_CORE_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "src.execution",
    "src.paper",
    "src.adapters",
    "telegram",
    "binance*",
)

#: The desk and the flow reach placement only through the injected `on_confirmed` (D-17).
PLACEMENT_FORBIDDEN_NAMES: tuple[str, ...] = (
    "src.execution.manager",
    "src.adapters.binance_usdm",
)

PHASE23_LIBRARY_MODULES: tuple[str, ...] = (
    "src/approval/reason_codes.py",
    "src/approval/confirm_core.py",
    "src/risk/money_at_stake.py",
    "src/ops/alert_wording.py",
    "src/execution/confirm_recheck.py",
    "src/execution/prior_outcome.py",
    "src/execution/approval_desk.py",
    "src/execution/confirm_flow.py",
    "src/adapters/telegram_callbacks.py",
    "src/adapters/telegram_notify.py",
    "src/db/alembic/versions/0013_approval_money.py",
    "src/db/alembic/versions/0014_decided_excl_expired.py",
    "scripts/gen_phase23_fixtures.py",
)


def test_phase23_module_inventory_exists() -> None:
    missing = [relative for relative in PHASE23_LIBRARY_MODULES if not (ROOT / relative).is_file()]
    assert missing == [], f"missing Phase 23 modules: {missing}"


@pytest.mark.parametrize("relative", PHASE23_PURE_MODULES)
def test_invariant_1_pure_modules_read_no_clock_and_build_no_float(relative: str) -> None:
    path = ROOT / relative
    assert wall_clock_calls(path) == [], f"{relative} reads a wall clock"
    assert float_constructor_calls(path) == [], f"{relative} builds a float"


def test_invariant_1b_the_confirm_core_imports_nothing_order_capable_or_telegram_facing() -> None:
    path = ROOT / "src/approval/confirm_core.py"
    assert forbidden_imports(path, CONFIRM_CORE_FORBIDDEN_IMPORTS) == [], (
        "src/approval/confirm_core.py imports an execution, paper, adapter or Telegram module"
    )


def _imported_dotted_names(path: Path) -> set[str]:
    """Every module name and every `module.member` an import statement brings in."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _identifiers(path: Path) -> set[str]:
    """Every name, attribute and imported alias identifier of a module (docstrings excluded)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.name.rsplit(".", 1)[-1])
    return found


@pytest.mark.parametrize(
    "relative", ("src/execution/approval_desk.py", "src/execution/confirm_flow.py")
)
def test_invariant_1c_the_desk_and_the_flow_reach_placement_only_through_on_confirmed(
    relative: str,
) -> None:
    path = ROOT / relative
    imported = _imported_dotted_names(path)
    offenders = sorted(
        name
        for name in imported
        for banned in PLACEMENT_FORBIDDEN_NAMES
        if name == banned or name.startswith(banned + ".")
    )
    assert offenders == [], f"{relative} imports {offenders}"
    assert "execute_approved_plan" not in _identifiers(path), (
        f"{relative} names execute_approved_plan: the only seam is the injected on_confirmed"
    )


def test_invariant_1d_the_money_module_is_scanned_by_the_domain_float_guard() -> None:
    from tests.test_domain_no_float import SCANNED_FILES

    assert "src/risk/money_at_stake.py" in SCANNED_FILES, (
        "src/risk/money_at_stake.py is not in tests/test_domain_no_float.py"
    )


def test_invariant_2_live_placement_is_still_disabled() -> None:
    from src.execution.enablement import LiveEnablementController

    class _Journal:
        def record(self, event: object) -> None:  # pragma: no cover - never reached
            raise AssertionError("a default controller must not journal")

    controller = LiveEnablementController(journal=_Journal())
    assert controller.is_disabled is True, "Phase 23 must not enable live placement"
    verdict = controller.guard_placement(plan_hash="0" * 64)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "DISABLED"


# --------------------------------------------------------------------------- #
# The second gate: a required keyword-only allow-list, its variable, the error handler.
# --------------------------------------------------------------------------- #

CALLBACKS = "src/adapters/telegram_callbacks.py"


def _function_node(relative: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{relative} defines no function {name}")


@pytest.mark.parametrize("name", ("on_callback", "build_application"))
def test_invariant_3_authorized_user_ids_is_required_and_keyword_only(name: str) -> None:
    function = _function_node(CALLBACKS, name)
    keyword_only = [arg.arg for arg in function.args.kwonlyargs]
    assert "authorized_user_ids" in keyword_only, f"{name}: authorized_user_ids is not keyword-only"
    assert "authorized_user_ids" not in [arg.arg for arg in function.args.args], name
    default = function.args.kw_defaults[keyword_only.index("authorized_user_ids")]
    assert default is None, f"{name}: authorized_user_ids has a default (D-02: never allow-all)"


def test_invariant_3b_the_allow_list_variable_is_allowed_and_named_in_both_env_examples() -> None:
    from src.paper.runtime_config import ALLOWED_ENV_NAMES

    assert "TELEGRAM_AUTHORIZED_USER_IDS" in ALLOWED_ENV_NAMES
    for relative in (".env.example", "deploy/soak.env.example"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "TELEGRAM_AUTHORIZED_USER_IDS" in text, f"{relative} does not name the variable"


def test_invariant_4_build_application_registers_an_error_handler() -> None:
    function = _function_node(CALLBACKS, "build_application")
    registered = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_error_handler"
    ]
    assert registered, "build_application no longer calls add_error_handler (D-08)"


# --------------------------------------------------------------------------- #
# Vocabulary: the enum is untouched, every plain code has a module and a GLOSSARY row.
# --------------------------------------------------------------------------- #

#: code -> (module that defines it, kind of status its GLOSSARY 9.3 row carries).
#: "refusal" rows read "proposed canonical, promote in Phase 24"; the others name their own kind.
PHASE23_PLAIN_CODES: dict[str, tuple[str, str]] = {
    "USER_ID_UNAVAILABLE": ("src/approval/reason_codes.py", "refusal"),
    "CHAT_NOT_PRIVATE": ("src/approval/reason_codes.py", "refusal"),
    "USER_NOT_AUTHORIZED": ("src/approval/reason_codes.py", "refusal"),
    "APPROVAL_STORE_FAILURE": ("src/approval/reason_codes.py", "refusal"),
    "ALREADY_DECIDED": ("src/approval/reason_codes.py", "outcome"),
    "CALLBACK_HANDLER_ERROR": ("src/approval/reason_codes.py", "refusal"),
    "CONFIRM_INPUTS_UNAVAILABLE": ("src/execution/confirm_recheck.py", "refusal"),
    "CONFIRM_INPUTS_MISMATCH": ("src/execution/confirm_recheck.py", "refusal"),
    "MONEY_AT_STAKE_MISSING": ("src/risk/money_at_stake.py", "refusal"),
    "USER_MISMATCH": ("src/approval/confirm_core.py", "refusal"),
    "CHAT_MISMATCH": ("src/approval/confirm_core.py", "refusal"),
    "NO_CONFIRM_CONTEXT": ("src/approval/confirm_core.py", "refusal"),
    "RECHECK_ERROR": ("src/approval/confirm_core.py", "refusal"),
    "CONFIRM_TTL_ELAPSED": ("src/approval/confirm_core.py", "confirm"),
    "CARD_DELIVERY_FAILED": ("src/approval/confirm_core.py", "confirm"),
    "RUNTIME_RESTART": ("src/approval/confirm_core.py", "confirm"),
    "CONFIRM_ALREADY_EXPIRED": ("src/approval/confirm_core.py", "confirm"),
    "VALIDITY_RULE_ERROR": ("src/execution/confirm_flow.py", "card"),
    "LEFT_PENDING_SIBLING_DECIDED": ("src/paper/shadow.py", "outcome"),
}

STATUS_PREFIX = "proposed canonical, promote in Phase"
STATUS_BY_KIND: dict[str, str] = {
    "outcome": "outcome label",
    "confirm": "confirm journal reason, not a rejection reason",
    "card": "confirmation card text, not a rejection reason",
}


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


def _string_constants_anywhere(relative: str) -> set[str]:
    """Every string constant of a module, wherever it sits (the emitted codes)."""
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_invariant_5_the_rejection_reason_enum_still_has_21_members() -> None:
    from src.domain.enums import RejectionReason

    members = {member.value for member in RejectionReason}
    assert len(RejectionReason) == 21, "Phase 23 adds no rejection reason (resolution 7)"
    assert members.isdisjoint(PHASE23_PLAIN_CODES), "a Phase 23 plain code became an enum member"


def test_invariant_5b_every_phase23_edge_code_is_listed_and_defined() -> None:
    from src.approval.reason_codes import PHASE23_EDGE_CODES
    from src.execution.confirm_recheck import (
        CONFIRM_INPUTS_MISMATCH,
        CONFIRM_INPUTS_UNAVAILABLE,
    )
    from src.risk.money_at_stake import MONEY_AT_STAKE_MISSING

    for code in (
        *PHASE23_EDGE_CODES,
        CONFIRM_INPUTS_UNAVAILABLE,
        CONFIRM_INPUTS_MISMATCH,
        MONEY_AT_STAKE_MISSING,
    ):
        assert code in PHASE23_PLAIN_CODES, f"{code} is not pinned by this gate"


def test_invariant_5c_the_confirm_core_reason_codes_are_all_pinned() -> None:
    from src.approval import confirm_core

    reasons = {
        value
        for name, value in vars(confirm_core).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    assert reasons, "confirm_core defines no REASON_ code"
    missing = sorted(reasons - set(PHASE23_PLAIN_CODES))
    assert missing == [], f"confirm_core defines reason codes this gate does not pin: {missing}"


def test_invariant_5d_every_plain_code_is_defined_in_its_module() -> None:
    for code, (module, _kind) in PHASE23_PLAIN_CODES.items():
        assert code in _string_constants_anywhere(module), f"{module} no longer defines {code}"


def test_invariant_5e_glossary_93_lists_every_plain_code_once_with_its_module() -> None:
    rows = _glossary_table_rows("### 9.3 ", "### 9.4 ")
    for code, (module, kind) in PHASE23_PLAIN_CODES.items():
        assert code in rows, f"GLOSSARY 9.3 lacks {code}"
        assert module in rows[code][1], f"{code}: 'Emitted in' does not name {module}"
        assert rows[code][2], f"{code}: empty meaning"
        status = rows[code][3]
        if kind == "refusal":
            assert status.startswith(STATUS_PREFIX), f"{code}: status {status!r}"
        else:
            assert status.startswith(STATUS_BY_KIND[kind]), f"{code}: status {status!r}"


def test_invariant_5f_glossary_93_states_the_resolution_7_amendment() -> None:
    text = (ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8")
    start = text.index("### 9.3 ")
    introduction = text[start : text.index("| Code | Emitted in", start)]
    assert "Phase 23" in introduction and "RejectionReason" in introduction
    assert "21 members" in introduction


def test_invariant_5g_glossary_91_lists_exactly_the_enum() -> None:
    from src.domain.enums import RejectionReason

    text = (ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8")
    block = text[text.index("### 9.1 ") : text.index("### 9.2 ")]
    codes = re.search(r"```text\n(.*?)```", block, re.DOTALL)
    assert codes is not None
    listed = set(codes.group(1).split())
    assert listed == {member.value for member in RejectionReason}


# --------------------------------------------------------------------------- #
# Migration head (D-16, the owner's O-2 answer (a) of 2026-10-26).
# --------------------------------------------------------------------------- #


def test_invariant_6_the_migration_head_is_0014_decided_excl_expired() -> None:
    from tests.pg_support import alembic_head_revision

    assert alembic_head_revision() == "0014_decided_excl_expired", (
        "plan 23-08 moved the head to 0014 (owner answer a); a later migration must update this "
        "gate on purpose"
    )


# --------------------------------------------------------------------------- #
# Message texts (D-14): UTC with a suffix in DEMO/LIVE/SIMULATE, the pair stays in SHADOW.
# --------------------------------------------------------------------------- #


def _load_generator() -> ModuleType:
    path = ROOT / "scripts" / "gen_phase23_fixtures.py"
    spec = importlib.util.spec_from_file_location("gen_phase23_fixtures_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_invariant_7_generated_messages_carry_no_display_zone_note() -> None:
    rendered = _load_generator().render_all()
    messages = {key: text for key, text in rendered.items() if key.startswith("messages/")}
    for expected in (
        "messages/approve_base.txt",
        "messages/approve_request_demo.txt",
        "messages/approve_request_live.txt",
        "messages/simulate.txt",
        "messages/confirm_card_demo.txt",
    ):
        assert expected in messages, f"the generator no longer renders {expected}"
    for key, text in messages.items():
        assert "Asia/Ho_Chi_Minh" not in text, f"{key} names Asia/Ho_Chi_Minh"
        assert "Display:" not in text, f"{key} carries a Display line"
        assert " UTC" in text, f"{key} shows no explicit UTC suffix"


def test_invariant_7b_the_shadow_time_pair_still_carries_both_zones() -> None:
    from src.paper.shadow import format_time_pair

    text = format_time_pair(datetime(2026, 10, 9, 3, 0, 0, tzinfo=UTC))
    assert "UTC (" in text and "Asia/Ho_Chi_Minh" in text


# --------------------------------------------------------------------------- #
# Requirement -> named tests (resolved with ast, never imported).
# --------------------------------------------------------------------------- #

REQUIREMENT_TESTS: dict[str, tuple[tuple[str, str], ...]] = {
    "APRV-01": (
        # The money block is built once, recomputed independently and refused when incomplete.
        ("tests/test_money_at_stake.py", "test_long_plan_money_is_recomputed_independently"),
        ("tests/test_money_at_stake.py", "test_short_plan_money_is_recomputed_independently"),
        ("tests/test_money_at_stake.py", "test_refuses_without_equity"),
        (
            "tests/test_approval_desk.py",
            "test_issue_refuses_missing_or_mismatching_money_before_any_write",
        ),
        # Plain-word operator alerts.
        (
            "tests/test_alert_wording.py",
            "test_b2_close_required_is_the_header_plus_four_plain_lines",
        ),
        # The card shows the stored amounts and the stored entry outcome.
        (
            "tests/test_confirm_flow.py",
            "test_the_confirmed_card_shows_the_stored_entry_outcome",
        ),
    ),
    "APRV-02": (
        # The user and private-chat gate.
        (
            "tests/test_telegram_authorization.py",
            "test_a_stranger_is_refused_before_any_lookup_and_journaled_with_only_his_id",
        ),
        (
            "tests/test_telegram_authorization.py",
            "test_a_group_with_the_authorized_chat_id_is_refused_before_any_lookup",
        ),
        (
            "tests/test_telegram_authorization.py",
            "test_an_allowed_press_is_decided_with_the_presser_as_actor_and_replay_keeps_it",
        ),
        # The decided message is final and a stale tap is answered from stored state.
        (
            "tests/test_telegram_decided_message.py",
            "test_tracer_a_skip_press_finalizes_the_message_with_an_empty_keyboard",
        ),
        (
            "tests/test_telegram_decided_message.py",
            "test_a_fresh_approve_is_not_already_decided_and_a_replay_is",
        ),
        (
            "tests/test_approval_desk.py",
            "test_three_skip_taps_give_one_transition_and_one_final_edit",
        ),
        # Handler errors are journaled and answered neutrally.
        (
            "tests/test_telegram_error_handler.py",
            "test_a_handler_exception_is_journaled_and_answered_neutrally",
        ),
        # The two-step confirm: only a valid CONFIRM by the approving user reaches on_confirmed.
        (
            "tests/test_confirm_flow.py",
            "test_confirm_by_the_approving_user_reaches_on_confirmed_once_and_finalizes",
        ),
        (
            "tests/test_confirm_flow.py",
            "test_a_confirm_by_a_user_who_is_not_listed_never_reaches_the_confirm_core",
        ),
        (
            "tests/test_confirm_flow.py",
            "test_a_confirm_after_the_ttl_is_refused_and_the_card_becomes_final",
        ),
        ("tests/test_confirm_recheck.py", "test_second_confirm_finds_no_snapshot"),
        ("tests/test_confirm_core.py", "test_a_valid_confirm_in_the_core_reaches_the_hook_once"),
    ),
    "PAPER-02": (
        # The decider and the money block survive a new store instance.
        (
            "tests/test_persistence_approvals_pg.py",
            "test_tracer_decided_actor_and_money_survive_a_new_store_instance",
        ),
        # G4-042 (the owner's O-2 answer (a)): both siblings of an undecided plan expire.
        (
            "tests/test_persistence_approvals_pg.py",
            "test_both_pending_siblings_of_an_undecided_plan_can_be_expired_at_restart",
        ),
        (
            "tests/test_persistence_approvals_pg.py",
            "test_a_decided_plans_sibling_is_never_expired",
        ),
        # P16R-02: every CONFIRM adopted in one sweep reaches on_confirmed.
        (
            "tests/test_confirm_core.py",
            "test_two_adoptions_in_one_sweep_reach_the_hook_once_each_in_order",
        ),
    ),
}


def _test_function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_invariant_8_each_phase23_requirement_has_its_named_tests() -> None:
    assert set(REQUIREMENT_TESTS) == {"APRV-01", "APRV-02", "PAPER-02"}
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


def test_invariant_8b_every_requirement_name_is_a_known_requirement() -> None:
    planning = ROOT / ".planning" / "REQUIREMENTS.md"
    if not planning.is_file():
        pytest.skip("REQUIREMENTS.md is not in this checkout (filtered)")
    text = planning.read_text(encoding="utf-8")
    for requirement in REQUIREMENT_TESTS:
        assert f"**{requirement}**" in text, requirement
