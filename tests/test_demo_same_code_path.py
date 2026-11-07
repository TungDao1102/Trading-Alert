"""D-08 / Phase 25 criterion 2: Demo and live share one code path; only endpoint and keys differ.

The Demo campaign proves something about live only if Demo runs the code live runs. This module
turns that into an AST check (plan 25-05), over source text and never by importing it:

  * `src/execution` and `src/risk` contain no `Environment.DEMO` (and no `.DEMO` attribute of any
    name): the placement, protection and risk path cannot branch on Demo.
  * In `src/live` the set of files that reference `Environment.DEMO` equals the pinned
    `DEMO_BRANCH_ALLOW_LIST`, each entry with a reason. A naive "no DEMO in src/live" test fails on
    day one (25-RESEARCH Pitfall 4: mode parsing, the DEMO-only enable, the /demo_signal injector
    and the DEMO kill-gate rule are deliberate); the allow-list keeps those and makes a NEW Demo
    branch a reviewed decision, by exact path.
  * The placement chain takes no mode: `execute_approved_plan` and `BinanceUsdmAdapter.place_entry`
    have no argument named `mode`, `environment` or `env`.
  * Production assembly installs no test edge: the `build_wiring` call in `default_assemble`
    passes no `exchange_edge` keyword (and no `**` expansion that could carry it), and neither
    `src/execution` nor `src/risk` imports `tests` or `scripts`.

Each rule is a function over a path or a source text with a seeded negative control, so a rule that
stops detecting its violation fails here and not silently.

Known limit: the scanner matches the literal name `Environment` (how every src module imports it
from `src.adapters.binance_client`); an `import Environment as Env` alias is not followed.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.support.ast_guards import forbidden_imports

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_DIR = ROOT / "src" / "execution"
RISK_DIR = ROOT / "src" / "risk"
LIVE_DIR = ROOT / "src" / "live"

MANAGER = ROOT / "src" / "execution" / "manager.py"
ADAPTER = ROOT / "src" / "adapters" / "binance_usdm.py"
RUNTIME = ROOT / "src" / "live" / "runtime.py"

# Each entry is a reviewed, deliberate Demo-aware module of the live process (D-08), keyed by exact
# repo-relative path. A new module that references `Environment.DEMO` must be added here with a
# reason on purpose; the set below equals today's scan of src/live.
DEMO_BRANCH_ALLOW_LIST: dict[str, str] = {
    "src/live/config.py": (
        "mode parsing: ACCEPTED_MODES maps the exact text DEMO to Environment.DEMO, and the "
        "opposite-credential rule picks the other mode's variables to refuse"
    ),
    "src/live/enablement.py": (
        "enable_demo refuses any mode that is not DEMO: the in-process enable exists only in "
        "DEMO, LIVE keeps the human step"
    ),
    "src/live/smoke_injection.py": (
        "the /demo_signal injector and its DemoSmokeSignalSource exist only in DEMO; LIVE and "
        "TESTNET never get the command"
    ),
    "src/live/startup.py": (
        "DEMO start rule: the HEALTH and ENABLE steps run in DEMO only, LIVE skips them with the "
        "human-enable code"
    ),
    "src/live/wiring.py": (
        "demo_degraded_allowed for the health producer (D056 (2)) and the LINK_DEMO_SIGNAL "
        "check that the injector exists in DEMO and nowhere else"
    ),
    "src/live/wiring_parts.py": (
        "the DEMO-only kill-gate sources rule (D092): an explicit DEMO rule, the persisted "
        "evaluated state in every other mode"
    ),
}

# Argument names that would make the placement chain mode-dependent.
MODE_ARGUMENT_NAMES = frozenset({"mode", "environment", "env"})
# The keyword that installs a test fault edge into the exchange adapter (24-xx test seam).
TEST_EDGE_KEYWORD = "exchange_edge"
SPLAT = "**"


def source_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def relative(path: Path, root: Path = ROOT) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def demo_references(
    paths: Iterable[Path],
    root: Path = ROOT,
    owners: frozenset[str] | None = frozenset({"Environment"}),
) -> list[str]:
    """`path:line` of every `<owner>.DEMO` attribute access; `owners=None` matches any Name."""
    found: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = relative(path, root)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute) and node.attr == "DEMO"):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            if owners is None or node.value.id in owners:
                found.append(f"{rel}:{node.lineno}")
    return sorted(found)


def referencing_files(references: Iterable[str]) -> set[str]:
    return {reference.rsplit(":", 1)[0] for reference in references}


def _find_function(
    tree: ast.Module, name: str, class_name: str | None = None
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    scope: ast.AST = tree
    if class_name is not None:
        classes = [
            n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name
        ]
        if not classes:
            return None
        scope = classes[0]
    for node in ast.walk(scope):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def argument_names(source: str, name: str, class_name: str | None = None) -> list[str]:
    """Every parameter name of the first function `name` (in `class_name` when given).

    Raises:
        LookupError: no such function, so a rename cannot turn the check vacuous.
    """
    function = _find_function(ast.parse(source), name, class_name)
    if function is None:
        raise LookupError(f"{class_name + '.' if class_name else ''}{name} not found")
    args = function.args
    names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def mode_arguments(source: str, name: str, class_name: str | None = None) -> list[str]:
    return [n for n in argument_names(source, name, class_name) if n in MODE_ARGUMENT_NAMES]


def build_wiring_keywords(source: str, function: str = "default_assemble") -> list[str]:
    """Keyword names of every `build_wiring(...)` call inside `function`; `**` for an expansion.

    Raises:
        LookupError: `function` or its `build_wiring` call is missing (the check would be vacuous).
    """
    found = _find_function(ast.parse(source), function)
    if found is None:
        raise LookupError(f"{function} not found")
    keywords: list[str] = []
    calls = 0
    for node in ast.walk(found):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if callee != "build_wiring":
            continue
        calls += 1
        keywords.extend(k.arg if k.arg is not None else SPLAT for k in node.keywords)
    if calls == 0:
        raise LookupError(f"{function} has no build_wiring call")
    return keywords


def test_src_execution_and_src_risk_reference_no_environment_demo() -> None:
    files = source_files(EXECUTION_DIR) + source_files(RISK_DIR)
    assert files, "src/execution and src/risk must be found"
    assert demo_references(files) == []


def test_src_execution_and_src_risk_branch_on_no_demo_attribute_of_any_name() -> None:
    # Hardening: an alias or another enum (`HealthRuntimeMode.DEMO`) is no way round the rule.
    files = source_files(EXECUTION_DIR) + source_files(RISK_DIR)
    assert demo_references(files, owners=None) == []


def test_src_live_demo_references_equal_the_pinned_allow_list() -> None:
    files = source_files(LIVE_DIR)
    assert files, "src/live must be found"
    found = referencing_files(demo_references(files))
    assert found == set(DEMO_BRANCH_ALLOW_LIST), (
        f"unlisted: {sorted(found - set(DEMO_BRANCH_ALLOW_LIST))}; "
        f"stale: {sorted(set(DEMO_BRANCH_ALLOW_LIST) - found)}"
    )


def test_the_demo_allow_list_names_only_live_modules_with_a_reason() -> None:
    assert len(DEMO_BRANCH_ALLOW_LIST) == 6
    for rel, reason in DEMO_BRANCH_ALLOW_LIST.items():
        assert rel.startswith("src/live/") and rel.endswith(".py")
        assert (ROOT / rel).is_file(), f"{rel} no longer exists"
        assert reason.strip() != ""


def test_negative_control_a_demo_branch_in_execution_is_reported(tmp_path: Path) -> None:
    (tmp_path / "src" / "execution").mkdir(parents=True)
    seeded = tmp_path / "src" / "execution" / "x.py"
    seeded.write_text(
        "from src.adapters.binance_client import Environment\n"
        "def f(mode):\n"
        "    if mode is Environment.DEMO:\n"
        "        return 1\n"
        "    return mode is Environment.LIVE\n",
        encoding="utf-8",
    )
    assert demo_references([seeded], root=tmp_path) == ["src/execution/x.py:3"]


def test_negative_control_the_any_owner_scan_finds_another_enum(tmp_path: Path) -> None:
    seeded = tmp_path / "y.py"
    seeded.write_text("def f(m):\n    return m is HealthRuntimeMode.DEMO\n", encoding="utf-8")
    assert demo_references([seeded], root=tmp_path) == []
    assert demo_references([seeded], root=tmp_path, owners=None) == ["y.py:2"]


def test_negative_control_an_unlisted_live_module_breaks_the_set_comparison(tmp_path: Path) -> None:
    live = tmp_path / "src" / "live"
    live.mkdir(parents=True)
    listed = live / "enablement.py"
    listed.write_text("if mode is Environment.DEMO:\n    pass\n", encoding="utf-8")
    unlisted = live / "new_mod.py"
    unlisted.write_text("if mode is Environment.DEMO:\n    pass\n", encoding="utf-8")
    found = referencing_files(demo_references([listed, unlisted], root=tmp_path))
    assert found == {"src/live/enablement.py", "src/live/new_mod.py"}
    assert found != set(DEMO_BRANCH_ALLOW_LIST)
    assert found - set(DEMO_BRANCH_ALLOW_LIST) == {"src/live/new_mod.py"}


def test_negative_control_the_allow_list_is_by_exact_path(tmp_path: Path) -> None:
    # The same text in a renamed file is not excused by the entry of the original name.
    live = tmp_path / "src" / "live"
    live.mkdir(parents=True)
    renamed = live / "enablement_v2.py"
    renamed.write_text("if mode is Environment.DEMO:\n    pass\n", encoding="utf-8")
    found = referencing_files(demo_references([renamed], root=tmp_path))
    assert found == {"src/live/enablement_v2.py"}
    assert not found <= set(DEMO_BRANCH_ALLOW_LIST)


def test_negative_control_a_non_attribute_demo_text_is_not_a_reference(tmp_path: Path) -> None:
    seeded = tmp_path / "z.py"
    seeded.write_text(
        '"""Environment.DEMO in a docstring"""\n# Environment.DEMO in a comment\n'
        'NAME = "Environment.DEMO"\nDEMO = 1\n',
        encoding="utf-8",
    )
    assert demo_references([seeded], root=tmp_path) == []


# ---- the placement chain takes no mode ---------------------------------------------------------


def test_execute_approved_plan_has_no_mode_argument() -> None:
    names = argument_names(MANAGER.read_text(encoding="utf-8"), "execute_approved_plan")
    assert "callback" in names and "adapter" in names  # the right function was found
    assert mode_arguments(MANAGER.read_text(encoding="utf-8"), "execute_approved_plan") == []


def test_adapter_place_entry_has_no_mode_argument() -> None:
    source = ADAPTER.read_text(encoding="utf-8")
    names = argument_names(source, "place_entry", class_name="BinanceUsdmAdapter")
    assert "symbol" in names and "quantity" in names  # the right method was found
    assert mode_arguments(source, "place_entry", class_name="BinanceUsdmAdapter") == []


@pytest.mark.parametrize("argument", sorted(MODE_ARGUMENT_NAMES))
def test_negative_control_a_mode_argument_is_found(argument: str) -> None:
    free = f"async def execute_approved_plan(*, callback, {argument}, adapter): ...\n"
    assert mode_arguments(free, "execute_approved_plan") == [argument]
    positional = f"class C:\n    def place_entry(self, symbol, {argument}=None, **kw): ...\n"
    assert mode_arguments(positional, "place_entry", class_name="C") == [argument]
    extra = f"def place_entry(self, *{argument}): ...\n"
    assert mode_arguments(extra, "place_entry") == [argument]


def test_a_missing_function_is_an_error_not_an_empty_pass() -> None:
    with pytest.raises(LookupError):
        argument_names("def other(): ...\n", "execute_approved_plan")
    with pytest.raises(LookupError):
        argument_names("class A:\n    def place_entry(self): ...\n", "place_entry", "B")


# ---- production assembly installs no test edge -------------------------------------------------


def test_default_assemble_passes_no_exchange_edge_to_build_wiring() -> None:
    keywords = build_wiring_keywords(RUNTIME.read_text(encoding="utf-8"))
    assert "config" in keywords and "sdk_factory" in keywords  # the real call was found
    assert TEST_EDGE_KEYWORD not in keywords
    assert SPLAT not in keywords


def test_negative_control_a_seeded_exchange_edge_keyword_is_found() -> None:
    seeded = (
        "def default_assemble(context):\n"
        "    from x import build_wiring\n"
        "    return build_wiring(config=1, exchange_edge=edge, sleep=2)\n"
    )
    assert build_wiring_keywords(seeded) == ["config", "exchange_edge", "sleep"]
    assert TEST_EDGE_KEYWORD in build_wiring_keywords(seeded)


def test_negative_control_a_keyword_expansion_is_found() -> None:
    seeded = "def default_assemble(context):\n    return wiring.build_wiring(config=1, **extra)\n"
    assert build_wiring_keywords(seeded) == ["config", SPLAT]


def test_negative_control_a_clean_call_and_a_vacuous_scan() -> None:
    clean = "def default_assemble(c):\n    return build_wiring(config=1)\n"
    assert TEST_EDGE_KEYWORD not in build_wiring_keywords(clean)
    # A call moved out of default_assemble, or a renamed function, cannot make the check vacuous.
    with pytest.raises(LookupError):
        build_wiring_keywords("def default_assemble(c):\n    return other(config=1)\n")
    with pytest.raises(LookupError):
        build_wiring_keywords("def assemble(c):\n    return build_wiring(config=1)\n")


@pytest.mark.parametrize(
    "path", source_files(EXECUTION_DIR) + source_files(RISK_DIR), ids=lambda p: relative(p)
)
def test_src_execution_and_src_risk_import_neither_tests_nor_scripts(path: Path) -> None:
    assert forbidden_imports(path, ("tests", "scripts")) == []


def test_negative_control_a_tests_or_scripts_import_is_found(tmp_path: Path) -> None:
    seeded = tmp_path / "seeded.py"
    seeded.write_text(
        "import tests.support.fakes\nfrom scripts import demo_rehearsal\nimport src.risk\n",
        encoding="utf-8",
    )
    assert forbidden_imports(seeded, ("tests", "scripts")) == ["tests.support.fakes", "scripts"]
