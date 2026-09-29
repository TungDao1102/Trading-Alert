"""Closing purity and determinism guards for the analytics edge (Phase 10, plan 10-12).

The pure `src/analytics` modules are covered by the AST purity guard and the no-float scan; this
file locks the edge that surrounds them: the CLI and the two adapters are float and clock clean,
the only write construction in the phase is the guarded journal append, the CLI imports no
server, exchange, Telegram or execution code, the no-float scan lists every pure module (drift
guard), and the PowerShell wrapper is a thin, parseable delegate.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_domain_no_float import SCANNED_FILES, _find_float_calls

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYTICS_DIR = REPO_ROOT / "src" / "analytics"
CLI = REPO_ROOT / "src" / "analytics" / "cli.py"
EDGE_FILES = (
    "src/analytics/cli.py",
    "src/adapters/analytics_files.py",
    "src/adapters/analytics_store.py",
)
WRAPPER = REPO_ROOT / "scripts" / "dev" / "journal-report.ps1"
README = REPO_ROOT / "scripts" / "dev" / "README.md"
FORBIDDEN_CLI_IMPORT_ROOTS = frozenset(
    {"fastapi", "uvicorn", "telegram", "binance", "httpx", "requests"}
)
_CLOCK_ATTRS = frozenset({"now", "utcnow", "today"})
_TIME_ATTRS = frozenset({"time", "time_ns", "monotonic", "perf_counter"})
_INSERT_NAMES = frozenset({"insert", "pg_insert", "sqlite_insert", "Insert"})
_MUTATION_NAMES = frozenset({"update", "delete"})


def _tree(rel: str) -> ast.Module:
    return ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _enclosing_function(tree: ast.Module, target: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(child is target for child in ast.walk(node)):
                return node.name
    return None


# --------------------------------------------------------------------------- #
# Drift guard: the no-float scan lists every pure analytics module
# --------------------------------------------------------------------------- #


def test_no_float_scan_lists_every_pure_analytics_module() -> None:
    pure = sorted(
        f"src/analytics/{path.name}" for path in ANALYTICS_DIR.glob("*.py") if path.name != "cli.py"
    )
    assert pure, "no analytics modules found"
    missing = [rel for rel in pure if rel not in SCANNED_FILES]
    assert not missing, f"SCANNED_FILES is missing pure analytics modules: {missing}"


def test_no_float_scan_does_not_list_the_edge_cli() -> None:
    assert "src/analytics/cli.py" not in SCANNED_FILES


# --------------------------------------------------------------------------- #
# Edge modules: no float, no total_seconds, one bounded clock read
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rel", EDGE_FILES)
def test_edge_module_has_no_float_shapes(rel: str) -> None:
    found = _find_float_calls((REPO_ROOT / rel).read_text(encoding="utf-8"))
    assert found == [], f"{rel}: float shapes found: {found}"


@pytest.mark.parametrize("rel", EDGE_FILES)
def test_edge_module_never_calls_total_seconds(rel: str) -> None:
    offenders = [
        node.lineno
        for node in ast.walk(_tree(rel))
        if isinstance(node, ast.Attribute) and node.attr == "total_seconds"
    ]
    assert offenders == []


def test_cli_reads_the_wall_clock_at_most_once_inside_the_as_of_resolver() -> None:
    tree = _tree("src/analytics/cli.py")
    clock_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and (
            (node.func.attr in _CLOCK_ATTRS)
            or (
                node.func.attr in _TIME_ATTRS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "time"
            )
        )
    ]
    assert len(clock_calls) <= 1
    for call in clock_calls:
        assert _enclosing_function(tree, call) == "_resolve_as_of"


@pytest.mark.parametrize(
    "rel", ("src/adapters/analytics_files.py", "src/adapters/analytics_store.py")
)
def test_adapters_never_read_the_wall_clock(rel: str) -> None:
    offenders = [
        node.lineno
        for node in ast.walk(_tree(rel))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _CLOCK_ATTRS | _TIME_ATTRS
    ]
    assert offenders == []


# --------------------------------------------------------------------------- #
# Writes: the one guarded journal append, nothing else
# --------------------------------------------------------------------------- #


def test_the_only_insert_building_code_is_the_guarded_append_statement() -> None:
    for rel in ("src/adapters/analytics_files.py", "src/adapters/analytics_store.py"):
        tree = _tree(rel)
        builders = {
            _enclosing_function(tree, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node) in _INSERT_NAMES
        }
        allowed = {"build_append_stmt"} if rel.endswith("analytics_store.py") else set()
        assert builders <= allowed, f"{rel}: insert built outside build_append_stmt: {builders}"


def test_cli_builds_no_write_statement_of_its_own() -> None:
    tree = _tree("src/analytics/cli.py")
    statement_names = _INSERT_NAMES | _MUTATION_NAMES | {"text"}
    bare_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in statement_names
    ]
    executes = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]
    sqlalchemy_imports = [
        module for module in _imported_modules(tree) if module.split(".")[0] == "sqlalchemy"
    ]
    assert bare_calls == []
    assert executes == []
    assert sqlalchemy_imports == []


def test_cli_journal_write_goes_only_through_the_guarded_adapter_append() -> None:
    tree = _tree("src/analytics/cli.py")
    appends = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "append_kill_gate_event"
    ]
    assert len(appends) == 1
    source = CLI.read_text(encoding="utf-8")
    assert "build_question_approved_event" not in source
    assert "record_kill_gate_evaluation" not in source


# --------------------------------------------------------------------------- #
# Imports: no server, exchange, Telegram or enablement code in the CLI
# --------------------------------------------------------------------------- #


def _imported_modules(tree: ast.Module) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def test_cli_imports_no_server_exchange_telegram_or_http_client() -> None:
    offenders = [
        module
        for module in _imported_modules(_tree("src/analytics/cli.py"))
        if module.split(".")[0] in FORBIDDEN_CLI_IMPORT_ROOTS
    ]
    assert offenders == []


def test_cli_imports_no_execution_or_enablement_code() -> None:
    offenders = [
        module
        for module in _imported_modules(_tree("src/analytics/cli.py"))
        if module == "src.execution" or module.startswith(("src.execution.", "src.ops"))
    ]
    assert offenders == []


def test_cli_never_prints_or_embeds_the_database_url() -> None:
    tree = _tree("src/analytics/cli.py")
    reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "DATABASE_URL"
    ]
    assert len(reads) == 1  # read once from the environment, in _database_url
    assert _enclosing_function(tree, reads[0]) == "_database_url"


# --------------------------------------------------------------------------- #
# PowerShell wrapper
# --------------------------------------------------------------------------- #


def _wrapper_text() -> str:
    return WRAPPER.read_text(encoding="utf-8")


def test_wrapper_delegates_to_the_cli_in_the_scripts_dev_convention() -> None:
    assert WRAPPER.is_file()
    text = _wrapper_text()
    assert ". (Join-Path $PSScriptRoot '_common.ps1')" in text
    assert "Assert-Uv" in text
    assert "uv run python -m src.analytics.cli" in text
    assert re.search(r"finally\s*\{[^}]*Exit-RepoRoot", text) is not None
    assert "$LASTEXITCODE" in text
    assert re.search(r"^exit \$code\s*$", text, re.MULTILINE) is not None


def test_wrapper_declares_every_documented_parameter() -> None:
    text = _wrapper_text()
    for name in ("AsOf", "OutDir", "Universe", "Evidence", "Decisions", "RawRoot"):
        assert re.search(rf"\[string\]\${name}\b", text), name
    for name in ("Record", "NoDb"):
        assert re.search(rf"\[switch\]\${name}\b", text), name
    for flag in (
        "--as-of",
        "--out-dir",
        "--universe",
        "--evidence",
        "--decisions",
        "--raw-root",
        "--record",
        "--no-db",
    ):
        assert flag in text, flag


def test_wrapper_avoids_here_strings_and_never_echoes_secrets() -> None:
    text = _wrapper_text()
    assert "@'" not in text
    assert '@"' not in text
    assert "DATABASE_URL" not in text
    assert "Write-Host $env" not in text
    assert "-Record is the only write" in text


def test_readme_lists_the_wrapper() -> None:
    text = README.read_text(encoding="utf-8")
    assert "journal-report.ps1" in text
    assert "KILL_GATE_EVALUATION" in text


def test_wrapper_parses_with_the_powershell_language_parser() -> None:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        pytest.skip("no PowerShell executable on PATH")
    script = (
        "$errors = $null; $tokens = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        "$env:GSD_WRAPPER_PATH, [ref]$tokens, [ref]$errors); "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.Message }; exit 1 }; exit 0"
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "GSD_WRAPPER_PATH": str(WRAPPER)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
