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

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_DIR = ROOT / "src" / "execution"
RISK_DIR = ROOT / "src" / "risk"
LIVE_DIR = ROOT / "src" / "live"

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
