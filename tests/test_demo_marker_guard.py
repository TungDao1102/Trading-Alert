"""Guards of the owner-run Demo selection (plan 25-01, D-03, OPS-02).

TEST_ONLY: nothing here talks to Binance. Three facts are pinned:

- the collection hook skips every `demo` item unless `-m demo` is given together with
  TRADING_DEMO_RUN=1 (a plain skip, so it holds under TRADING_CI_STRICT=1 too);
- the CI command (`-m "not docker"`) collects `tests/demo` and reports it skipped;
- every test function under `tests/demo` carries the `demo` mark (AST scan, negative control).
"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO_ROOT / "tests" / "demo"
SKIP_REASON_FRAGMENT = "owner-run only"


class _StubItem:
    """The part of `pytest.Item` the hook touches: a closest-marker lookup and add_marker."""

    def __init__(self, *, demo: bool) -> None:
        self._demo = demo
        self.added: list[Any] = []

    def get_closest_marker(self, name: str) -> Any:
        return object() if (name == "demo" and self._demo) else None

    def add_marker(self, marker: Any) -> None:
        self.added.append(marker)


def _run_hook(
    markexpr: str, environ: Mapping[str, str], monkeypatch: pytest.MonkeyPatch
) -> tuple[_StubItem, _StubItem]:
    conftest = importlib.import_module("tests.conftest")
    hook = conftest.pytest_collection_modifyitems
    monkeypatch.delenv("TRADING_DEMO_RUN", raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)
    config = SimpleNamespace(getoption=lambda name: markexpr if name == "markexpr" else None)
    demo_item, plain_item = _StubItem(demo=True), _StubItem(demo=False)
    hook(config, [demo_item, plain_item])
    return demo_item, plain_item


def test_the_ci_expression_skips_a_demo_item_and_leaves_a_plain_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo_item, plain_item = _run_hook("not docker", {}, monkeypatch)
    assert plain_item.added == []
    (marker,) = demo_item.added
    assert marker.name == "skip"
    assert SKIP_REASON_FRAGMENT in marker.kwargs["reason"]


def test_the_ci_expression_skips_a_demo_item_even_with_the_run_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo_item, _ = _run_hook("not docker", {"TRADING_DEMO_RUN": "1"}, monkeypatch)
    assert len(demo_item.added) == 1


@pytest.mark.parametrize("expr", ["demo", "demo and not docker", "not docker and demo"])
def test_demo_selected_with_the_run_variable_adds_no_skip(
    expr: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo_item, plain_item = _run_hook(expr, {"TRADING_DEMO_RUN": "1"}, monkeypatch)
    assert demo_item.added == []
    assert plain_item.added == []


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes"])
def test_demo_selected_without_the_exact_run_value_is_skipped(
    value: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    environ = {} if value is None else {"TRADING_DEMO_RUN": value}
    demo_item, _ = _run_hook("demo", environ, monkeypatch)
    assert len(demo_item.added) == 1


def test_not_demo_is_skipped_even_with_the_run_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    demo_item, _ = _run_hook("not demo", {"TRADING_DEMO_RUN": "1"}, monkeypatch)
    assert len(demo_item.added) == 1


def test_an_empty_expression_skips_a_demo_item(monkeypatch: pytest.MonkeyPatch) -> None:
    demo_item, _ = _run_hook("", {"TRADING_DEMO_RUN": "1"}, monkeypatch)
    assert len(demo_item.added) == 1


def test_the_ci_command_collects_tests_demo_and_reports_it_skipped_in_strict_mode() -> None:
    """The real thing: a child pytest with CI's expression, strict mode, and no run variable."""
    env = {k: v for k, v in os.environ.items() if k != "TRADING_DEMO_RUN"}
    env["TRADING_CI_STRICT"] = "1"
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/demo",
            "-m",
            "not docker",
            "-rs",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "skipped" in out, out
    assert SKIP_REASON_FRAGMENT in out, out
    assert " passed" not in out and " failed" not in out and " error" not in out, out


# --------------------------------------------------------------------------- #
# Every test function under tests/demo carries the demo mark.
# --------------------------------------------------------------------------- #


def _is_demo_mark(node: ast.expr) -> bool:
    """`pytest.mark.demo`, also as a call (`pytest.mark.demo()`)."""
    if isinstance(node, ast.Call):
        node = node.func
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "demo"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _module_marked(tree: ast.Module) -> bool:
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets):
            continue
        value = stmt.value
        elements = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
        if any(_is_demo_mark(element) for element in elements):
            return True
    return False


def _decorated(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    return any(_is_demo_mark(decorator) for decorator in node.decorator_list)


def unmarked_demo_tests(paths: Iterable[Path]) -> list[str]:
    """`path::test_name` of every `test_*` function without the `demo` mark (never imports)."""
    unmarked: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _module_marked(tree):
            continue
        for stmt in tree.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                if stmt.name.startswith("test_") and not _decorated(stmt):
                    unmarked.append(f"{path.name}::{stmt.name}")
            elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
                if _decorated(stmt):
                    continue
                for member in stmt.body:
                    if (
                        isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
                        and member.name.startswith("test_")
                        and not _decorated(member)
                    ):
                        unmarked.append(f"{path.name}::{stmt.name}::{member.name}")
    return unmarked


def test_every_test_function_under_tests_demo_carries_the_demo_mark() -> None:
    files = sorted(DEMO_DIR.glob("test_*.py"))
    assert files, "tests/demo has no test file"
    assert unmarked_demo_tests(files) == []


def test_the_marker_scan_reports_a_seeded_unmarked_file(tmp_path: Path) -> None:
    seeded = tmp_path / "test_seeded_unmarked.py"
    seeded.write_text(
        "import pytest\n\n\ndef test_a() -> None:\n    pass\n\n\n"
        "@pytest.mark.demo\ndef test_b() -> None:\n    pass\n\n\n"
        "class TestC:\n    def test_c(self) -> None:\n        pass\n",
        encoding="utf-8",
    )
    assert unmarked_demo_tests([seeded]) == [
        "test_seeded_unmarked.py::test_a",
        "test_seeded_unmarked.py::TestC::test_c",
    ]


def test_the_marker_scan_accepts_module_level_marks_in_every_spelling(tmp_path: Path) -> None:
    for index, spelling in enumerate(
        ["pytest.mark.demo", "[pytest.mark.demo]", "(pytest.mark.docker, pytest.mark.demo)"]
    ):
        path = tmp_path / f"test_marked_{index}.py"
        path.write_text(
            f"import pytest\n\npytestmark = {spelling}\n\n\ndef test_a() -> None:\n    pass\n",
            encoding="utf-8",
        )
        assert unmarked_demo_tests([path]) == []
