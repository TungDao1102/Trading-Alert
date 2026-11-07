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
