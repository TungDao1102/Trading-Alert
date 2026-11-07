"""Phase 25 gate (plan 25-17): the structure of the Demo campaign, checked against the tree.

This file asserts, against the real tree and without any network, Binance, Telegram or database,
that the campaign cannot lose a scenario, a mark or an inherited item unnoticed:

- the scenario structure (D-05): every catalog scenario S01-S19 has its module with
  `async def run`, a twin test file with at least one test and a module-level `REUSES` tuple whose
  entries resolve (with `ast`) to existing functions, and a demo test file with at least one test
  and the `demo` mark at module level; S20 is observation-only and is covered by rows of
  `docs/operations/DEMO_VS_MAINNET.md`;
- the demo mark (D-03, T-25-42): re-checked on every scenario's demo file, next to the plan 25-01
  guard;
- no new `src/live` module and live placement still disabled (D-08);
- every requirement of the phase maps to named tests and every CONTEXT decision D-01 to D-14 maps to
  the plan that built it and to existing evidence (`REQUIREMENT_TESTS`, `DECISION_EVIDENCE`);
- the consolidated scenario inventory (`25-SCENARIO-INVENTORY.md`) agrees with the catalog and the
  `REUSES` tuples;
- the register of inherited items (`25-DEFERRED.md`) gives every inherited id of the ROADMAP
  Phase 25 entry a status, captures every finding of the plan summaries and every strict xfail
  twin, and claims no Demo or mainnet result without an evidence path.

Every check is a small function that takes a root, so a negative control can run it on a copy in
`tmp_path`. A failure message names the scenario id, the path, the symbol or the id.

Evidence label: executed structural tests. Nothing here claims a Demo result, a requirement
complete or a mainnet observation, and nothing changes behavior: `LIVE_ORDERS_DISABLED` stays, and
the owner decisions (R-21, R-22, the -1003 margin key) stay open in the register.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.support.demo_scenarios.catalog import SCENARIOS, Scenario
from tests.test_phase24_gate import LIVE_MODULES

ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = ROOT / ".planning" / "phases" / "25-demo-integration-test-campaign"

#: The scenario ids of the pinned catalog (plan 25-08): S01-S20.
CATALOG_IDS: tuple[str, ...] = tuple(f"S{number:02d}" for number in range(1, 21))

# --------------------------------------------------------------------------- #
# Reading a file with ast (never imported, never run).
# --------------------------------------------------------------------------- #


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _test_function_names(tree: ast.Module) -> list[str]:
    return sorted(name for name in _function_names(tree) if name.startswith("test_"))


def _has_top_level_async_run(tree: ast.Module) -> bool:
    return any(isinstance(node, ast.AsyncFunctionDef) and node.name == "run" for node in tree.body)


def _module_string_tuple(tree: ast.Module, name: str) -> list[str] | None:
    """The string entries of a module-level `name = (...)`; None if absent or not all strings."""
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        if isinstance(value, ast.Tuple | ast.List) and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts
        ):
            return [str(item.value) for item in value.elts if isinstance(item, ast.Constant)]
        return None
    return None


def _is_demo_mark(node: ast.AST) -> bool:
    """True for the attribute chain `pytest.mark.demo`."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "demo"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _has_demo_pytestmark(tree: ast.Module) -> bool:
    """A module-level `pytestmark = ...` that holds `pytest.mark.demo` (alone or in a list)."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            return any(_is_demo_mark(part) for part in ast.walk(node.value))
    return False


def _resolve_reference(root: Path, reference: str) -> str | None:
    """None when `path::function` names an existing function, else the reason it does not."""
    relative, separator, name = reference.partition("::")
    if not separator or not name:
        return f"{reference!r} is not of the form path::function"
    path = root / relative
    if not path.is_file():
        return f"{relative} does not exist"
    if name not in _function_names(_tree(path)):
        return f"{relative} defines no function {name!r}"
    return None


# --------------------------------------------------------------------------- #
# The scenario structure (D-05, T-25-41, T-25-42).
# --------------------------------------------------------------------------- #


def scenario_problems(scenario: Scenario, root: Path) -> list[str]:
    """Every way one scenario's three files fail the structure; each message names the id."""
    sid = scenario.id
    if scenario.module is None or scenario.twin_test is None or scenario.demo_test is None:
        return [f"{sid}: a non-observation scenario must name a module, a twin and a demo test"]
    problems: list[str] = []

    module = root / scenario.module
    if not module.is_file():
        problems.append(f"{sid}: module {scenario.module} does not exist")
    elif not _has_top_level_async_run(_tree(module)):
        problems.append(f"{sid}: module {scenario.module} defines no `async def run`")

    twin = root / scenario.twin_test
    if not twin.is_file():
        problems.append(f"{sid}: twin test {scenario.twin_test} does not exist")
    else:
        twin_tree = _tree(twin)
        if not _test_function_names(twin_tree):
            problems.append(f"{sid}: twin test {scenario.twin_test} has no test function")
        reuses = _module_string_tuple(twin_tree, "REUSES")
        if reuses is None:
            problems.append(
                f"{sid}: twin test {scenario.twin_test} has no module-level REUSES tuple"
            )
        elif not reuses:
            problems.append(f"{sid}: twin test {scenario.twin_test} has an empty REUSES tuple")
        else:
            for reference in reuses:
                reason = _resolve_reference(root, reference)
                if reason is not None:
                    problems.append(f"{sid}: REUSES entry {reference!r}: {reason}")

    demo = root / scenario.demo_test
    if not demo.is_file():
        problems.append(f"{sid}: demo test {scenario.demo_test} does not exist")
    else:
        demo_tree = _tree(demo)
        if not _test_function_names(demo_tree):
            problems.append(f"{sid}: demo test {scenario.demo_test} has no test function")
        if not _has_demo_pytestmark(demo_tree):
            problems.append(
                f"{sid}: demo test {scenario.demo_test} has no module-level "
                "`pytestmark = pytest.mark.demo` (it would run in CI)"
            )
    return problems


def unlisted_scenario_files(root: Path) -> list[str]:
    """Scenario-shaped files on disk that the catalog does not list (S00 is the preflight)."""
    listed = {
        path
        for scenario in SCENARIOS
        for path in (scenario.module, scenario.twin_test, scenario.demo_test)
        if path is not None
    }
    patterns = (
        "tests/support/demo_scenarios/s[0-9][0-9]_*.py",
        "tests/test_demo_twin_s[0-9][0-9]_*.py",
        "tests/demo/test_demo_s[0-9][0-9]_*.py",
    )
    found = {
        path.relative_to(root).as_posix() for pattern in patterns for path in root.glob(pattern)
    }
    return sorted(path for path in found - listed if "_s00_" not in path and "/s00_" not in path)


def test_the_catalog_lists_s01_to_s20_once_and_only_s20_is_observation_only() -> None:
    assert [scenario.id for scenario in SCENARIOS] == list(CATALOG_IDS)
    assert [s.id for s in SCENARIOS if s.observation_only] == ["S20"]


@pytest.mark.parametrize(
    "scenario", [s for s in SCENARIOS if not s.observation_only], ids=lambda s: s.id
)
def test_every_catalog_scenario_has_its_module_twin_reuses_and_marked_demo_test(
    scenario: Scenario,
) -> None:
    assert scenario_problems(scenario, ROOT) == []


def test_no_scenario_file_exists_outside_the_catalog() -> None:
    assert unlisted_scenario_files(ROOT) == [], "scenario files the catalog does not list"


def test_every_demo_test_file_of_the_phase_carries_the_demo_mark() -> None:
    """The plan 25-01 guard scans test functions; this re-checks every file by name (T-25-42)."""
    files = sorted((ROOT / "tests" / "demo").glob("test_demo_s*.py"))
    assert len(files) == 20, f"expected S00 plus 19 scenario demo files, found {len(files)}"
    unmarked = [path.name for path in files if not _has_demo_pytestmark(_tree(path))]
    assert unmarked == [], f"demo files without the demo mark: {unmarked}"


# --------------------------------------------------------------------------- #
# S20 is observation-only: DEMO_VS_MAINNET.md carries its rows.
# --------------------------------------------------------------------------- #

DVM_PATH = Path("docs") / "operations" / "DEMO_VS_MAINNET.md"

#: (what the row is about, a pattern the row must match, the label it must carry or None).
OBSERVATION_ROWS: tuple[tuple[str, str, str | None], ...] = (
    ("A2 GTD entry expiry status", r"\(A2\)", None),
    ("A3 closePosition legs after the position closes", r"\(A3\)", None),
    ("B2/B3 same-id stop re-place", r"\(B2 and B3\)", None),
    ("a real 418 ban beyond 259200 s", r"418 ban .*259200", "NOT_OBSERVED"),
    ("429/418 queue order", r"queue order", "NOT_OBSERVED"),
)


def _dvm_rows(root: Path) -> list[list[str]]:
    path = root / DVM_PATH
    if not path.is_file():
        return []
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\| DVM-\d+ ", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def observation_problems(root: Path) -> list[str]:
    """S20 problems: a missing document, or an observation item without its labelled row."""
    rows = _dvm_rows(root)
    if not rows:
        return [f"S20: {DVM_PATH.as_posix()} has no DVM rows"]
    problems: list[str] = []
    for subject, pattern, label in OBSERVATION_ROWS:
        matching = [row for row in rows if re.search(pattern, " ".join(row))]
        if not matching:
            problems.append(f"S20: no DVM row names {subject}")
        elif label is not None and not any(len(row) > 2 and row[2] == label for row in matching):
            problems.append(f"S20: the DVM row for {subject} is not labelled {label}")
    return problems


def test_s20_is_covered_by_the_demo_vs_mainnet_rows() -> None:
    assert observation_problems(ROOT) == []


# --------------------------------------------------------------------------- #
# No new live module, live placement still disabled.
# --------------------------------------------------------------------------- #


def test_phase_25_added_no_src_live_module() -> None:
    found = {path.stem for path in (ROOT / "src" / "live").glob("*.py")}
    assert found == LIVE_MODULES, (
        f"src/live changed: missing {sorted(LIVE_MODULES - found)}, "
        f"new {sorted(found - LIVE_MODULES)}; Phase 25 adds none (D-08)"
    )


def test_live_placement_is_still_disabled() -> None:
    source = (ROOT / "src" / "execution" / "enablement.py").read_text(encoding="utf-8")
    assert "LIVE_ORDERS_DISABLED" in source, "enablement.py no longer names LIVE_ORDERS_DISABLED"
    from src.execution.enablement import LiveEnablementController

    class _Journal:
        def record(self, event: object) -> None:  # pragma: no cover - never reached
            raise AssertionError("a default controller must not journal")

    controller = LiveEnablementController(journal=_Journal())
    assert controller.is_disabled is True, "Phase 25 must not enable live placement"
    assert controller.guard_placement(plan_hash="0" * 64).reason_code == "DISABLED"


# --------------------------------------------------------------------------- #
# Negative controls: each rule must be able to fail, by scenario id, on a tmp copy.
# --------------------------------------------------------------------------- #

_FAKE = Scenario(
    id="S99",
    slug="fake",
    title="Fake",
    roadmap_bullet="fake",
    plan="25-99",
    requirements=("EXEC-01",),
    module="tests/support/demo_scenarios/s99_fake.py",
    twin_test="tests/test_demo_twin_s99_fake.py",
    demo_test="tests/demo/test_demo_s99_fake.py",
)

_GOOD_MODULE = "async def run(env, recorder):\n    return 'ok'\n"
_GOOD_TWIN = (
    "REUSES = ('tests/test_existing.py::test_exists',)\n\n\ndef test_the_twin():\n    pass\n"
)
_GOOD_DEMO = "import pytest\n\npytestmark = pytest.mark.demo\n\n\ndef test_the_demo():\n    pass\n"


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_tree(
    root: Path,
    *,
    module: str | None = _GOOD_MODULE,
    twin: str | None = _GOOD_TWIN,
    demo: str | None = _GOOD_DEMO,
) -> None:
    _write(root, "tests/test_existing.py", "def test_exists():\n    pass\n")
    for relative, text in (
        (_FAKE.module, module),
        (_FAKE.twin_test, twin),
        (_FAKE.demo_test, demo),
    ):
        if relative is not None and text is not None:
            _write(root, relative, text)


def test_negative_control_a_complete_scenario_has_no_problem(tmp_path: Path) -> None:
    _fake_tree(tmp_path)
    assert scenario_problems(_FAKE, tmp_path) == []


def test_negative_control_a_twin_without_reuses_fails_naming_the_scenario(tmp_path: Path) -> None:
    _fake_tree(tmp_path, twin="def test_the_twin():\n    pass\n")
    problems = scenario_problems(_FAKE, tmp_path)
    assert len(problems) == 1 and problems[0].startswith("S99:") and "REUSES" in problems[0]


def test_negative_control_an_empty_reuses_tuple_fails(tmp_path: Path) -> None:
    _fake_tree(tmp_path, twin="REUSES = ()\n\n\ndef test_the_twin():\n    pass\n")
    assert any("empty REUSES" in problem for problem in scenario_problems(_FAKE, tmp_path))


def test_negative_control_a_reuses_entry_naming_a_missing_function_fails(tmp_path: Path) -> None:
    twin = "REUSES = ('tests/test_existing.py::test_gone',)\n\n\ndef test_t():\n    pass\n"
    _fake_tree(tmp_path, twin=twin)
    problems = scenario_problems(_FAKE, tmp_path)
    assert len(problems) == 1
    assert problems[0].startswith("S99:") and "test_gone" in problems[0]


def test_negative_control_a_reuses_entry_naming_a_missing_file_or_no_function_fails(
    tmp_path: Path,
) -> None:
    for entry, needle in (("tests/none.py::test_x", "does not exist"), ("tests/no_sep", "form")):
        twin = f"REUSES = ({entry!r},)\n\n\ndef test_t():\n    pass\n"
        _fake_tree(tmp_path, twin=twin)
        problems = scenario_problems(_FAKE, tmp_path)
        assert len(problems) == 1 and needle in problems[0], problems


def test_negative_control_a_twin_without_a_test_function_fails(tmp_path: Path) -> None:
    _fake_tree(tmp_path, twin="REUSES = ('tests/test_existing.py::test_exists',)\n")
    assert any("no test function" in p for p in scenario_problems(_FAKE, tmp_path))


def test_negative_control_a_demo_test_without_the_mark_fails_naming_the_scenario(
    tmp_path: Path,
) -> None:
    _fake_tree(tmp_path, demo="def test_the_demo():\n    pass\n")
    problems = scenario_problems(_FAKE, tmp_path)
    assert len(problems) == 1 and problems[0].startswith("S99:") and "demo" in problems[0]


def test_negative_control_a_mark_on_one_function_only_is_not_the_module_mark(
    tmp_path: Path,
) -> None:
    demo = "import pytest\n\n\n@pytest.mark.demo\ndef test_the_demo():\n    pass\n"
    _fake_tree(tmp_path, demo=demo)
    assert any("module-level" in p for p in scenario_problems(_FAKE, tmp_path))


def test_negative_control_a_list_of_marks_that_holds_the_demo_mark_is_accepted(
    tmp_path: Path,
) -> None:
    demo = (
        "import pytest\n\npytestmark = [pytest.mark.asyncio, pytest.mark.demo]\n\n\n"
        "def test_the_demo():\n    pass\n"
    )
    _fake_tree(tmp_path, demo=demo)
    assert scenario_problems(_FAKE, tmp_path) == []


def test_negative_control_a_module_without_run_and_a_missing_demo_file_fail(
    tmp_path: Path,
) -> None:
    _fake_tree(tmp_path, module="def run(env, recorder):\n    return 'x'\n", demo=None)
    problems = scenario_problems(_FAKE, tmp_path)
    assert any("async def run" in problem for problem in problems)
    assert any("does not exist" in problem and "demo test" in problem for problem in problems)


def test_negative_control_missing_module_and_twin_files_fail_by_id(tmp_path: Path) -> None:
    _fake_tree(tmp_path, module=None, twin=None)
    problems = scenario_problems(_FAKE, tmp_path)
    assert len(problems) == 2 and all(problem.startswith("S99:") for problem in problems)


def test_negative_control_a_scenario_file_outside_the_catalog_is_found(tmp_path: Path) -> None:
    _write(tmp_path, "tests/demo/test_demo_s77_extra.py", "pass\n")
    _write(tmp_path, "tests/demo/test_demo_s00_preflight.py", "pass\n")
    assert unlisted_scenario_files(tmp_path) == ["tests/demo/test_demo_s77_extra.py"]


def test_negative_control_s20_without_its_rows_fails_naming_the_scenario(tmp_path: Path) -> None:
    assert observation_problems(tmp_path) == [f"S20: {DVM_PATH.as_posix()} has no DVM rows"]
    only_a2 = "| DVM-22 | GTD entry expiry (A2) | NOT_OBSERVED | reason | implication |\n"
    _write(tmp_path, DVM_PATH.as_posix(), only_a2)
    problems = observation_problems(tmp_path)
    assert len(problems) == len(OBSERVATION_ROWS) - 1
    assert all(problem.startswith("S20:") for problem in problems)


def test_negative_control_a_418_row_that_claims_an_observation_fails(tmp_path: Path) -> None:
    rows = "".join(
        f"| DVM-{index} | {subject} {extra} | {label} | s | i |\n"
        for index, (subject, extra, label) in enumerate(
            (
                ("(A2)", "", "NOT_OBSERVED"),
                ("(A3)", "", "DEMO_OBSERVED"),
                ("(B2 and B3)", "", "DEMO_OBSERVED"),
                ("A real HTTP 418 ban", "that lasts longer than 259200 s", "DEMO_OBSERVED"),
                ("the queue order", "", "NOT_OBSERVED"),
            ),
            start=1,
        )
    )
    _write(tmp_path, DVM_PATH.as_posix(), rows)
    problems = observation_problems(tmp_path)
    assert problems == [
        "S20: the DVM row for a real 418 ban beyond 259200 s is not labelled NOT_OBSERVED"
    ]


# --------------------------------------------------------------------------- #
# Requirement -> named tests (resolved with ast, never imported).
# --------------------------------------------------------------------------- #

REQUIREMENT_TESTS: dict[str, tuple[tuple[str, str], ...]] = {
    "EXEC-01": (
        (
            "tests/test_demo_twin_s01_happy.py",
            "test_s01_runs_end_to_end_and_every_step_is_synthetic",
        ),
        (
            "tests/test_demo_twin_s02_partial_fill.py",
            "test_a_partial_fill_is_protected_after_the_first_fill_and_ends_clean",
        ),
        (
            "tests/test_demo_twin_s04_stop_rejected.py",
            "test_a_rejected_stop_after_a_fill_ends_in_one_close_and_a_clean_account",
        ),
        ("tests/test_demo_same_code_path.py", "test_execute_approved_plan_has_no_mode_argument"),
    ),
    "EXEC-02": (
        (
            "tests/test_demo_twin_s15_foreign_order.py",
            "test_a_foreign_resting_order_is_reported_enters_safe_mode_and_is_never_touched",
        ),
        (
            "tests/test_demo_twin_s16_manual_close.py",
            "test_a_manual_close_leaves_a_flat_clean_orphan_free_account",
        ),
        (
            "tests/test_demo_twin_s08_stream_loss.py",
            "test_the_rest_reconcile_finds_the_order_change_the_stream_never_delivered",
        ),
    ),
    "EXEC-03": (
        ("tests/test_demo_twin_s06_replay.py", "test_the_exchange_saw_exactly_one_place_entry"),
        (
            "tests/test_demo_twin_s07_restart_cuts.py",
            "test_cut_a_one_place_entry_across_both_processes",
        ),
        (
            "tests/test_evaluate_demo_soak.py",
            "test_two_non_refused_outcomes_for_one_plan_fail_and_name_both_journal_ids",
        ),
    ),
    "APRV-01": (
        (
            "tests/test_demo_twin_s01_happy.py",
            "test_every_card_the_run_sent_passes_the_live_text_check",
        ),
        (
            "tests/test_demo_env_factory.py",
            "test_an_approve_press_goes_through_the_runner_handler_with_the_authorized_ids",
        ),
        (
            "tests/test_demo_twin_s06_replay.py",
            "test_the_press_ids_were_distinct_and_both_reached_the_handler",
        ),
    ),
    "APRV-02": (
        (
            "tests/test_demo_twin_s06_replay.py",
            "test_the_journal_holds_one_non_refused_placement_outcome",
        ),
        (
            "tests/test_demo_env_factory.py",
            "test_a_replayed_approve_and_the_confirm_variants_press_the_right_prefix",
        ),
        (
            "tests/test_demo_twin_s06_replay.py",
            "test_a_second_place_entry_fails_the_concurrent_step",
        ),
    ),
    "OPS-01": (
        (
            "tests/test_demo_twin_s14_safe_mode.py",
            "test_an_unresolved_entry_enters_safe_mode_and_the_operator_exit_restores_entries",
        ),
        (
            "tests/test_demo_twin_s10_rate_limit.py",
            "test_an_injected_429_restricts_the_gate_refuses_the_entry_and_opens_again",
        ),
        (
            "tests/test_persistence_pool_timeout.py",
            "test_an_exhausted_pool_is_store_unavailable_with_the_type_name_only",
        ),
        (
            "tests/test_live_health_journal_volume.py",
            "test_ten_idle_ticks_journal_ten_verdicts_and_the_ten_check_rows_once",
        ),
    ),
    "OPS-02": (
        (
            "tests/test_demo_env_guard.py",
            "test_any_binance_live_name_is_refused_by_name_and_not_by_value",
        ),
        (
            "tests/test_demo_evidence_index.py",
            "test_a_secret_in_an_evidence_file_is_scrubbed_in_the_index",
        ),
        (
            "tests/test_demo_twin_s01_happy.py",
            "test_no_sentinel_secret_reaches_the_evidence_file",
        ),
    ),
}


def missing_pairs(root: Path, pairs: tuple[tuple[str, str], ...], label: str) -> list[str]:
    problems: list[str] = []
    for relative, name in pairs:
        reason = _resolve_reference(root, f"{relative}::{name}")
        if reason is not None:
            problems.append(f"{label}: {reason}")
    return problems


def test_each_phase25_requirement_has_at_least_two_named_tests() -> None:
    assert set(REQUIREMENT_TESTS) == {
        "EXEC-01",
        "EXEC-02",
        "EXEC-03",
        "APRV-01",
        "APRV-02",
        "OPS-01",
        "OPS-02",
    }
    problems: list[str] = []
    for requirement, pairs in REQUIREMENT_TESTS.items():
        assert len(set(pairs)) >= 2, f"{requirement} names fewer than two distinct tests"
        problems.extend(missing_pairs(ROOT, pairs, requirement))
    assert problems == [], f"requirement-to-test pairs missing: {problems}"


def test_every_requirement_name_is_a_known_requirement() -> None:
    planning = ROOT / ".planning" / "REQUIREMENTS.md"
    if not planning.is_file():
        pytest.skip("REQUIREMENTS.md is not in this checkout (filtered)")
    text = planning.read_text(encoding="utf-8")
    for requirement in REQUIREMENT_TESTS:
        assert f"**{requirement}**" in text, requirement


def test_every_requirement_a_catalog_scenario_names_has_named_tests() -> None:
    named = {requirement for scenario in SCENARIOS for requirement in scenario.requirements}
    assert named <= set(REQUIREMENT_TESTS), sorted(named - set(REQUIREMENT_TESTS))


def test_negative_control_a_requirement_pair_naming_a_missing_test_is_reported(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "tests/test_a.py", "def test_here():\n    pass\n")
    problems = missing_pairs(
        tmp_path, (("tests/test_a.py", "test_here"), ("tests/test_a.py", "test_gone")), "EXEC-01"
    )
    assert len(problems) == 1 and "EXEC-01" in problems[0] and "test_gone" in problems[0]
    assert missing_pairs(tmp_path, (("tests/none.py", "test_x"),), "OPS-02") == [
        "OPS-02: tests/none.py does not exist"
    ]


# --------------------------------------------------------------------------- #
# The decision table: every CONTEXT decision D-01..D-14 to its plan and its evidence.
# An evidence item is ("test", path, function) or ("doc", path, anchor text).
# --------------------------------------------------------------------------- #

Evidence = tuple[str, str, str]


def _t(path: str, name: str) -> Evidence:
    return ("test", path, name)


def _d(path: str, anchor: str) -> Evidence:
    return ("doc", path, anchor)


_PLANNING = ".planning/phases/25-demo-integration-test-campaign"
_FACTS = ".planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md"

DECISION_EVIDENCE: dict[str, tuple[str, tuple[Evidence, ...]]] = {
    "D-01": (
        "25-01, 25-09",
        (
            _t(
                "tests/test_demo_marker_guard.py",
                "test_the_ci_expression_skips_a_demo_item_even_with_the_run_variable",
            ),
            _d("AGENTS.md", "run by the owner only"),
        ),
    ),
    "D-02": (
        "25-02",
        (
            _t("tests/test_fault_edge.py", "test_a_fault_edge_keeps_the_composed_wiring_whole"),
            _t(
                "tests/test_demo_twin_s01_happy.py",
                "test_s01_runs_end_to_end_and_every_step_is_synthetic",
            ),
        ),
    ),
    "D-03": (
        "25-01",
        (
            _t(
                "tests/test_demo_marker_guard.py",
                "test_every_test_function_under_tests_demo_carries_the_demo_mark",
            ),
            _t(
                "tests/test_demo_env_guard.py",
                "test_any_binance_live_name_is_refused_by_name_and_not_by_value",
            ),
        ),
    ),
    "D-04": (
        "25-08, 25-09",
        (
            _t(
                "tests/test_demo_harness.py",
                "test_the_document_has_the_scenario_schema_and_the_file_stem_follows_the_mode",
            ),
            _t(
                "tests/test_demo_twin_s01_happy.py",
                "test_the_evidence_file_has_the_scenario_schema_name_and_one_kind",
            ),
        ),
    ),
    "D-05": (
        "25-08, 25-10, 25-11, 25-12, 25-13, 25-14, 25-15, 25-16",
        (
            _t("tests/test_demo_harness.py", "test_every_entry_follows_the_naming_rule"),
            _t(
                "tests/test_phase25_gate.py",
                "test_every_catalog_scenario_has_its_module_twin_reuses_and_marked_demo_test",
            ),
        ),
    ),
    "D-06": (
        "25-11, 25-13, 25-14, 25-16",
        (
            _t(
                "tests/test_demo_twin_s16_manual_close.py",
                "test_a_manual_close_leaves_a_flat_clean_orphan_free_account",
            ),
            _t(
                "tests/test_demo_twin_s17_stale_feed.py",
                "test_a_stale_mark_fails_the_feed_check_refuses_the_entry_and_enters_safe_mode",
            ),
            _t(
                "tests/test_demo_twin_s18_unprotected.py",
                "test_a_rejected_stop_and_a_failing_close_end_close_failed_then_flat",
            ),
            _t(
                "tests/test_demo_twin_s19_rest_gate_cli.py",
                "test_a_false_418_is_cleared_by_stop_status_clear_and_restart",
            ),
        ),
    ),
    "D-07": (
        "25-06",
        (
            _d("docs/operations/DEMO_VS_MAINNET.md", "| DVM-22 |"),
            _d("docs/operations/DEMO_VS_MAINNET.md", "| DVM-28 |"),
            _t("tests/test_phase25_gate.py", "test_s20_is_covered_by_the_demo_vs_mainnet_rows"),
        ),
    ),
    "D-08": (
        "25-05",
        (
            _t(
                "tests/test_demo_same_code_path.py",
                "test_src_execution_and_src_risk_reference_no_environment_demo",
            ),
            _t(
                "tests/test_demo_same_code_path.py",
                "test_src_live_demo_references_equal_the_pinned_allow_list",
            ),
        ),
    ),
    "D-09": (
        "25-07 (the registration itself: plan 25-24)",
        (
            _t(
                "tests/test_evaluate_demo_soak.py",
                "test_verify_registration_refuses_a_file_edited_after_its_hash_was_recorded",
            ),
            _t(
                "tests/test_evaluate_demo_soak.py",
                "test_an_order_before_the_registration_commit_fails",
            ),
        ),
    ),
    "D-10": (
        "25-07",
        (
            _t(
                "tests/test_evaluate_demo_soak.py",
                "test_the_report_is_create_only_sorted_lf_and_carries_the_input_hashes",
            ),
            _t(
                "tests/test_evaluate_demo_soak.py",
                "test_the_script_imports_its_event_names_and_never_retypes_them",
            ),
        ),
    ),
    "D-11": (
        "25-04",
        (
            _t(
                "tests/test_live_health_journal_volume.py",
                "test_ten_idle_ticks_journal_ten_verdicts_and_the_ten_check_rows_once",
            ),
        ),
    ),
    "D-12": (
        "25-06",
        (
            _d("docs/operations/DEMO_VS_MAINNET.md", "| DVM-01 |"),
            _d(_FACTS, "Demo cross-check"),
        ),
    ),
    "D-13": (
        "25-03, 25-04",
        (
            _t(
                "tests/test_persistence_pool_timeout.py",
                "test_an_exhausted_pool_is_store_unavailable_with_the_type_name_only",
            ),
            _t(
                "tests/test_live_health_journal_volume.py",
                "test_a_status_flip_journals_one_extra_row_for_that_check_only",
            ),
        ),
    ),
    "D-14": (
        "25-17",
        (_d(f"{_PLANNING}/25-CONTEXT.md", "**D-14 [auto]:**"),),
    ),
}


def decision_problems(root: Path, table: dict[str, tuple[str, tuple[Evidence, ...]]]) -> list[str]:
    problems: list[str] = []
    for decision, (plans, items) in sorted(table.items()):
        if not plans.strip() or not items:
            problems.append(f"{decision}: no plan or no evidence")
            continue
        for plan in re.findall(r"25-\d\d", plans):
            if not (root / _PLANNING / f"{plan}-PLAN.md").is_file():
                problems.append(f"{decision}: plan {plan} has no PLAN.md")
        for kind, relative, needle in items:
            path = root / relative
            if not path.is_file():
                problems.append(f"{decision}: {relative} does not exist")
            elif kind == "test":
                if needle not in _function_names(_tree(path)):
                    problems.append(f"{decision}: {relative} defines no test {needle!r}")
            elif needle not in path.read_text(encoding="utf-8"):
                problems.append(f"{decision}: {relative} does not contain {needle!r}")
    return problems


def test_the_decision_table_names_every_context_decision() -> None:
    expected = {f"D-{number:02d}" for number in range(1, 15)}
    assert set(DECISION_EVIDENCE) == expected, (
        f"decision table ids differ: {sorted(expected ^ set(DECISION_EVIDENCE))}"
    )
    context = (PHASE_DIR / "25-CONTEXT.md").read_text(encoding="utf-8")
    for decision in sorted(expected):
        assert re.search(rf"\*\*{decision}\b", context), f"{decision} is not a CONTEXT decision"


def test_every_decision_has_a_plan_and_existing_evidence() -> None:
    assert decision_problems(ROOT, DECISION_EVIDENCE) == []


def test_negative_control_a_decision_without_evidence_or_with_a_missing_anchor_fails(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "tests/test_a.py", "def test_here():\n    pass\n")
    _write(tmp_path, "docs/a.md", "an anchor\n")
    _write(tmp_path, f"{_PLANNING}/25-01-PLAN.md", "plan\n")
    table: dict[str, tuple[str, tuple[Evidence, ...]]] = {
        "D-01": ("25-01", (_t("tests/test_a.py", "test_here"), _d("docs/a.md", "an anchor"))),
        "D-02": ("25-01", ()),
        "D-03": ("25-02", (_t("tests/test_a.py", "test_here"),)),
        "D-04": ("25-01", (_t("tests/test_a.py", "test_gone"), _d("docs/a.md", "nothing"))),
    }
    problems = decision_problems(tmp_path, table)
    assert [problem.split(":")[0] for problem in problems] == ["D-02", "D-03", "D-04", "D-04"]


# --------------------------------------------------------------------------- #
# The consolidated scenario inventory: the Wave 0 coverage inventory of 25-RESEARCH.
# --------------------------------------------------------------------------- #

INVENTORY_RELATIVE = f"{_PLANNING}/25-SCENARIO-INVENTORY.md"
INVENTORY_COLUMNS: tuple[str, ...] = (
    "id",
    "title",
    "twin test",
    "demo test",
    "REUSES",
    "expected Demo labels",
    "leaves_state",
)
#: The evidence labels an inventory row may name (harness.LABELS, checked by a test below).
LABEL_WORDS: frozenset[str] = frozenset(
    {"SYNTHETIC", "DEMO_OBSERVED", "DEMO_FAULT_INJECTED", "NOT_OBSERVED"}
)


def _strip(cell: str) -> str:
    return cell.replace("`", "").strip()


def inventory_cells(root: Path) -> dict[str, list[str]]:
    path = root / INVENTORY_RELATIVE
    if not path.is_file():
        return {}
    rows: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\| S\d\d ", line):
            cells = [_strip(cell) for cell in line.strip().strip("|").split("|")]
            rows[cells[0]] = cells
    return rows


def inventory_header(root: Path) -> list[str]:
    path = root / INVENTORY_RELATIVE
    if not path.is_file():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| id "):
            return [_strip(cell) for cell in line.strip().strip("|").split("|")]
    return []


def inventory_problems(root: Path, scenarios: tuple[Scenario, ...]) -> list[str]:
    """Rows missing, unknown or drifted from the catalog and from the REUSES tuples."""
    if not (root / INVENTORY_RELATIVE).is_file():
        return [f"{INVENTORY_RELATIVE} does not exist"]
    problems: list[str] = []
    if inventory_header(root) != list(INVENTORY_COLUMNS):
        problems.append(f"inventory header is not {list(INVENTORY_COLUMNS)}")
    rows = inventory_cells(root)
    for sid in sorted(set(rows) - {scenario.id for scenario in scenarios}):
        problems.append(f"{sid}: the inventory has a row the catalog does not list")
    for scenario in scenarios:
        sid = scenario.id
        cells = rows.get(sid)
        if cells is None:
            problems.append(f"{sid}: no inventory row")
            continue
        if len(cells) != len(INVENTORY_COLUMNS):
            problems.append(
                f"{sid}: the row has {len(cells)} columns, not {len(INVENTORY_COLUMNS)}"
            )
            continue
        _, title, twin, demo, reuses, labels, leaves = cells
        if title != scenario.title:
            problems.append(f"{sid}: title {title!r} differs from the catalog {scenario.title!r}")
        if leaves != ("yes" if scenario.leaves_state else "no"):
            problems.append(f"{sid}: leaves_state {leaves!r} differs from the catalog")
        if scenario.observation_only:
            if "DVM" not in labels:
                problems.append(f"{sid}: an observation-only row must name its DVM rows")
            continue
        if twin != scenario.twin_test or demo != scenario.demo_test:
            problems.append(f"{sid}: twin or demo path differs from the catalog")
        words = set(re.findall(r"[A-Z]+(?:_[A-Z]+)+", labels))
        if not words or not words <= LABEL_WORDS:
            problems.append(f"{sid}: expected Demo labels {labels!r} are not harness labels")
        twin_path = root / (scenario.twin_test or "")
        tuple_entries = (
            _module_string_tuple(_tree(twin_path), "REUSES") if twin_path.is_file() else None
        )
        listed = [entry.strip() for entry in reuses.split(";") if entry.strip()]
        if tuple_entries is None or listed != tuple_entries:
            problems.append(f"{sid}: inventory REUSES differ from the REUSES tuple of {twin}")
    return problems


def test_the_inventory_has_one_row_per_scenario_agreeing_with_catalog_and_reuses() -> None:
    assert inventory_problems(ROOT, SCENARIOS) == []


def test_the_inventory_labels_are_the_harness_labels() -> None:
    from tests.support.demo_scenarios.harness import LABELS

    assert set(LABEL_WORDS) == set(LABELS)


def _inventory_text(rows: list[str]) -> str:
    header = "| " + " | ".join(INVENTORY_COLUMNS) + " |\n|" + "---|" * len(INVENTORY_COLUMNS) + "\n"
    return header + "".join(rows)


def _fake_row(**override: str) -> str:
    cells = {
        "id": "S99",
        "title": "Fake",
        "twin": "`tests/test_demo_twin_s99_fake.py`",
        "demo": "`tests/demo/test_demo_s99_fake.py`",
        "reuses": "`tests/test_existing.py::test_exists`",
        "labels": "DEMO_OBSERVED",
        "leaves": "no",
    }
    cells.update(override)
    return "| " + " | ".join(cells.values()) + " |\n"


def test_negative_control_an_inventory_matching_the_tree_has_no_problem(tmp_path: Path) -> None:
    _fake_tree(tmp_path)
    _write(tmp_path, INVENTORY_RELATIVE, _inventory_text([_fake_row()]))
    assert inventory_problems(tmp_path, (_FAKE,)) == []


def test_negative_control_an_inventory_that_drifted_fails_naming_the_scenario(
    tmp_path: Path,
) -> None:
    _fake_tree(tmp_path)
    drifts = {
        "reuses": "`tests/test_existing.py::test_other`",
        "labels": "DEMO_MAYBE",
        "leaves": "yes",
        "title": "Another",
        "twin": "`tests/test_demo_twin_s98_x.py`",
    }
    for column, value in drifts.items():
        _write(tmp_path, INVENTORY_RELATIVE, _inventory_text([_fake_row(**{column: value})]))
        problems = inventory_problems(tmp_path, (_FAKE,))
        assert len(problems) == 1 and problems[0].startswith("S99:"), (column, problems)


def test_negative_control_a_missing_row_an_extra_row_and_a_missing_file_fail(
    tmp_path: Path,
) -> None:
    _fake_tree(tmp_path)
    assert inventory_problems(tmp_path, (_FAKE,)) == [f"{INVENTORY_RELATIVE} does not exist"]
    _write(tmp_path, INVENTORY_RELATIVE, _inventory_text([_fake_row(id="S98")]))
    problems = inventory_problems(tmp_path, (_FAKE,))
    assert "S98: the inventory has a row the catalog does not list" in problems
    assert "S99: no inventory row" in problems


# --------------------------------------------------------------------------- #
# The register of inherited items and findings: a status for every one (D-13, D-14).
# --------------------------------------------------------------------------- #

REGISTER_RELATIVE = f"{_PLANNING}/25-DEFERRED.md"
REGISTER_STATUS_WORDS: tuple[str, ...] = ("covered", "owner-open", "deferred", "superseded")

#: The inherited ids of the ROADMAP Phase 25 entry (owner registration 2026-10-07).
INHERITED_IDS: tuple[str, ...] = (
    "G2-016",
    "D055",
    "D056",
    "G2-030",
    "P20-DEMO",
    "P20-ERR1003",
    "R-21",
    "R-22",
    "R-23",
    "R-24",
    "R-25",
    "R-28",
)

#: Statuses the plan and the CONTEXT fix for good; the owner-open rows are NOT pinned here, because
#: the owner's later answers (plans 25-19 to 25-23) move them on purpose.
PINNED_STATUS: dict[str, str] = {
    "P20-ERR1003": "superseded",
    "R-23": "deferred",
    "R-24": "covered",
    "R-25": "covered",
    "R-28": "deferred",
}

FORBIDDEN_CLAIMS: tuple[str, ...] = ("mainnet-observed", "live-observed", "host-observed")


def roadmap_inherited_ids(root: Path) -> list[str]:
    text = (root / ".planning" / "ROADMAP.md").read_text(encoding="utf-8")
    start = text.index("### Phase 25: Binance Demo Integration Test Campaign")
    section = text[start:]
    section = section[: section.index("**Plans:**")]
    section = section[section.index("**Inherited items**") :]
    return re.findall(r"^- \[([A-Za-z0-9-]+)[\] /]", section, re.MULTILINE)


def register_rows(root: Path) -> dict[str, list[str]]:
    path = root / REGISTER_RELATIVE
    if not path.is_file():
        return {}
    rows: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        first = cells[0].strip("`")
        if len(cells) >= 4 and first and first != "id" and not set(first) <= {"-", ":", " "}:
            rows[first] = cells
    return rows


def status_problem(row_id: str, cells: list[str]) -> str | None:
    words = cells[2].replace("`", "").split()
    status = words[0].strip("*:;,.") if words else ""
    if status not in REGISTER_STATUS_WORDS:
        return f"{row_id}: status {cells[2][:30]!r} is none of {REGISTER_STATUS_WORDS}"
    if not cells[3]:
        return f"{row_id}: no evidence or reason in the where column"
    if status == "covered" and not re.search(r"25-\d\d|\bS\d\d\b", cells[3]):
        return f"{row_id}: a covered row must name the plan or scenario that covers it"
    return None


def register_problems(root: Path, inherited: tuple[str, ...] | list[str]) -> list[str]:
    path = root / REGISTER_RELATIVE
    if not path.is_file():
        return [f"{REGISTER_RELATIVE} does not exist"]
    rows = register_rows(root)
    problems: list[str] = []
    for item in inherited:
        if item not in rows:
            problems.append(f"{item}: no row in 25-DEFERRED.md")
    for row_id, cells in rows.items():
        problem = status_problem(row_id, cells)
        if problem:
            problems.append(problem)
    for row_id, wanted in PINNED_STATUS.items():
        if row_id in rows and not rows[row_id][2].replace("`", "").startswith(wanted):
            problems.append(f"{row_id}: the status must be {wanted!r}")
    return problems


def evidence_claim_problems(text: str) -> list[str]:
    """A forbidden claim anywhere, or a DEMO_OBSERVED line with no evidence path or DVM row."""
    problems = [f"the register claims {claim}" for claim in FORBIDDEN_CLAIMS if claim in text]
    evidence = re.compile(r"[A-Za-z0-9_./-]+\.(?:json|md|py|txt)\b|DVM-\d+")
    for number, line in enumerate(text.splitlines(), start=1):
        if "DEMO_OBSERVED" in line and not evidence.search(line):
            problems.append(f"line {number} claims DEMO_OBSERVED with no evidence path")
    return problems


def named_test_files(text: str) -> list[str]:
    return sorted(set(re.findall(r"tests/[A-Za-z0-9_/]+\.py", text)))


def test_the_roadmap_phase25_entry_lists_the_expected_inherited_ids() -> None:
    ids = roadmap_inherited_ids(ROOT)
    assert ids == list(INHERITED_IDS), f"the ROADMAP inherited ids changed: {ids}"


def test_every_inherited_item_has_a_status_in_the_register() -> None:
    assert register_problems(ROOT, roadmap_inherited_ids(ROOT)) == []


def test_the_register_names_only_existing_test_files() -> None:
    text = (ROOT / REGISTER_RELATIVE).read_text(encoding="utf-8")
    named = named_test_files(text)
    assert named, "the register names no test file"
    missing = [relative for relative in named if not (ROOT / relative).is_file()]
    assert missing == [], f"the register names test files that do not exist: {missing}"


def test_nothing_in_the_register_claims_a_mainnet_host_or_unevidenced_demo_result() -> None:
    text = (ROOT / REGISTER_RELATIVE).read_text(encoding="utf-8")
    assert "NOT_OBSERVED" in text, "the register must keep NOT_OBSERVED for owner-only items"
    assert evidence_claim_problems(text) == []


def test_decision_d14_points_at_the_register_rows_of_r23_and_r28() -> None:
    rows = register_rows(ROOT)
    for row_id in ("R-23", "R-28"):
        assert row_id in rows, f"{row_id} has no register row"
        assert "D-14" in " ".join(rows[row_id]), f"{row_id} does not cite D-14"


def test_the_owner_questions_are_recorded_open_and_never_decided_here() -> None:
    rows = register_rows(ROOT)
    for row_id in ("R-21", "R-22", "ERR1003-KEY", "OWNER-4"):
        assert row_id in rows, f"{row_id} has no register row"
    for row_id in ("R-21", "R-22"):
        status = rows[row_id][2].replace("`", "")
        assert status.startswith(("owner-open", "covered")), (row_id, status)
    if rows["R-22"][2].startswith("owner-open"):
        assert "22.5" in " ".join(rows["R-22"]), "R-22 must cite the interim stop procedure"


# --- every finding of the plan summaries ------------------------------------ #


def summary_finding_ids(root: Path) -> list[str]:
    """`25-NN-Fk` for every `**Fk (` finding label in a plan SUMMARY of the phase."""
    found: list[str] = []
    for path in sorted((root / _PLANNING).glob("25-[0-9][0-9]-SUMMARY.md")):
        plan = path.name[:5]
        for label in re.findall(r"^\*\*F(\d+) \(", path.read_text(encoding="utf-8"), re.MULTILINE):
            found.append(f"{plan}-F{label}")
    return found


def finding_problems(root: Path) -> list[str]:
    rows = register_rows(root)
    labelled = summary_finding_ids(root)
    problems = [
        f"{item}: a SUMMARY finding with no register row" for item in labelled if item not in rows
    ]
    for row_id, cells in rows.items():
        if re.fullmatch(r"25-\d\d-F\d+", row_id):
            if row_id not in labelled:
                problems.append(f"{row_id}: a register finding row that no SUMMARY labels")
            if not cells[2].replace("`", "").startswith("owner-open"):
                problems.append(f"{row_id}: a finding is owner-open until the owner decides")
    return problems


def test_the_summaries_label_the_expected_findings() -> None:
    labelled = summary_finding_ids(ROOT)
    assert len(labelled) == len(set(labelled)), "a finding label is used twice in one SUMMARY"
    assert len(labelled) >= 20, f"only {len(labelled)} findings were parsed from the SUMMARYs"


def test_every_summary_finding_is_captured_in_the_register_as_owner_open() -> None:
    assert finding_problems(ROOT) == []


# --- every strict xfail twin ------------------------------------------------- #


def xfail_twin_tests(root: Path) -> list[str]:
    names: list[str] = []
    for path in sorted(root.glob("tests/test_demo_twin_s*.py")):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(
                "xfail" in ast.dump(decorator) for decorator in node.decorator_list
            ):
                names.append(f"{path.name}::{node.name}")
    return names


def xfail_problems(root: Path) -> list[str]:
    path = root / REGISTER_RELATIVE
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return [
        f"{entry}: a strict xfail twin test the register does not name"
        for entry in xfail_twin_tests(root)
        if entry.split("::")[1] not in text
    ]


def test_every_xfail_twin_test_is_named_in_the_register() -> None:
    assert len(xfail_twin_tests(ROOT)) >= 3, (
        "the strict xfail twins of 25-12, 25-14, 25-15 vanished"
    )
    assert xfail_problems(ROOT) == []


# --- negative controls -------------------------------------------------------- #

_REGISTER_HEAD = "| id | item | status | where |\n|---|---|---|---|\n"


def _register_text(rows: list[str]) -> str:
    return _REGISTER_HEAD + "".join(f"{row}\n" for row in rows)


def test_negative_control_an_inherited_id_without_a_row_or_a_status_fails(tmp_path: Path) -> None:
    rows = [
        "| G2-016 | drills | covered | S16, plan 25-16 |",
        "| D055 | model | maybe | somewhere |",
        "| D056 | health | owner-open |  |",
        "| R-24 | pool | covered | nothing named |",
        "| R-23 | async | covered | D-14, 25-17 |",
    ]
    _write(tmp_path, REGISTER_RELATIVE, _register_text(rows))
    problems = register_problems(tmp_path, ["G2-016", "D055", "D056", "R-24", "R-23", "R-99"])
    joined = " | ".join(problems)
    assert "R-99: no row" in joined
    assert "D055: status" in joined
    assert "D056: no evidence" in joined
    assert "R-24: a covered row must name" in joined
    assert "R-23: the status must be 'deferred'" in joined
    assert not any(problem.startswith("G2-016") for problem in problems)


def test_negative_control_a_missing_register_file_fails(tmp_path: Path) -> None:
    assert register_problems(tmp_path, ["R-21"]) == [f"{REGISTER_RELATIVE} does not exist"]


def test_negative_control_a_mainnet_claim_or_an_unevidenced_demo_claim_fails() -> None:
    assert evidence_claim_problems("A row that says mainnet-observed.") == [
        "the register claims mainnet-observed"
    ]
    assert evidence_claim_problems("| X | item | covered | DEMO_OBSERVED, trust me |") == [
        "line 1 claims DEMO_OBSERVED with no evidence path"
    ]
    assert evidence_claim_problems("| X | item | covered | DEMO_OBSERVED, DVM-21 |") == []
    assert (
        evidence_claim_problems("DEMO_OBSERVED in evidence/09-DEMO-REHEARSAL-EVIDENCE-x.json") == []
    )


def test_negative_control_a_finding_without_a_row_and_a_row_without_a_finding_fail(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        f"{_PLANNING}/25-11-SUMMARY.md",
        "## Findings\n\n**F1 (design observation): something.**\n\n**F2 (observation): more.**\n",
    )
    rows = ["| 25-11-F1 | x | owner-open | y |", "| 25-12-F1 | x | owner-open | y |"]
    _write(tmp_path, REGISTER_RELATIVE, _register_text(rows))
    problems = finding_problems(tmp_path)
    assert "25-11-F2: a SUMMARY finding with no register row" in problems
    assert "25-12-F1: a register finding row that no SUMMARY labels" in problems
    rows = ["| 25-11-F1 | x | deferred | y |", "| 25-11-F2 | x | owner-open | y |"]
    _write(tmp_path, REGISTER_RELATIVE, _register_text(rows))
    assert finding_problems(tmp_path) == [
        "25-11-F1: a finding is owner-open until the owner decides"
    ]


def test_negative_control_a_strict_xfail_twin_the_register_does_not_name_fails(
    tmp_path: Path,
) -> None:
    twin = (
        "import pytest\n\n\n@pytest.mark.xfail(strict=True, reason='gap')\n"
        "async def test_a_gap_is_closed():\n    pass\n\n\ndef test_plain():\n    pass\n"
    )
    _write(tmp_path, "tests/test_demo_twin_s98_gap.py", twin)
    assert xfail_twin_tests(tmp_path) == ["test_demo_twin_s98_gap.py::test_a_gap_is_closed"]
    assert xfail_problems(tmp_path) == [
        "test_demo_twin_s98_gap.py::test_a_gap_is_closed: a strict xfail twin test "
        "the register does not name"
    ]
    _write(tmp_path, REGISTER_RELATIVE, "| 25-98-F1 | test_a_gap_is_closed | owner-open | y |\n")
    assert xfail_problems(tmp_path) == []
