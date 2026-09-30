"""Tests for the Phase 11 dispatcher scripts/verify_decision_alignment.py (plan 11-08).

The dispatcher is the single read-only command (D-17) that runs every gate
module under ``scripts/decision_alignment`` and prints one PASS or FAIL line
per gate. These tests cover mode routing, output format, exit codes, the
minimum-gate-count guard and the read-only property.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import verify_decision_alignment as vda

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "verify_decision_alignment.py"

MODES = ["protocol", "params", "universe", "docs", "glossary", "reqs", "decisions"]


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _gates(prefix: str, count: int, *, failing: int | None = None) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    for i in range(count):
        ok = failing != i
        out.append((f"{prefix}-{i:02d}", ok, "ok" if ok else "broken"))
    return out


def _fake_modules(**overrides: Any) -> dict[str, Any]:
    """Build injectable fake gate modules that satisfy every minimum count."""
    mins = vda.EXPECTED_MIN
    mods: dict[str, Any] = {
        "protocol": SimpleNamespace(run=lambda: _gates("P", mins["protocol"])),
        "params": SimpleNamespace(run=lambda: _gates("PA", mins["params"])),
        "universe": SimpleNamespace(run=lambda: _gates("U", mins["universe"])),
        "ops_risk": SimpleNamespace(run=lambda: _gates("OR", mins["ops_risk"])),
        "exchange": SimpleNamespace(run=lambda: _gates("EX", mins["exchange"])),
        "authority": SimpleNamespace(run=lambda: _gates("AU", mins["authority"])),
        "bookkeeping": SimpleNamespace(
            run_glossary=lambda: _gates("GL", mins["glossary"]),
            run_reqs=lambda: _gates("RQ", mins["reqs"]),
            run_decisions=lambda: _gates("DC", mins["decisions"]),
        ),
    }
    mods.update(overrides)
    return mods


# ---------------------------------------------------------------------------
# Real-repository subprocess runs
# ---------------------------------------------------------------------------


def test_all_mode_passes_on_real_repository() -> None:
    proc = _run_script("all")
    lines = proc.stdout.splitlines()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert lines[-1] == "ALL_PASS all"
    assert sum(1 for line in lines if line.startswith("PASS ")) >= 55
    assert not any(line.startswith("FAIL") for line in lines)


@pytest.mark.parametrize("mode", MODES)
def test_each_mode_passes_on_real_repository(mode: str) -> None:
    proc = _run_script(mode)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[-1] == f"ALL_PASS {mode}"


def test_unknown_mode_exits_2() -> None:
    proc = _run_script("nonsense")
    assert proc.returncode == 2
    assert "usage" in proc.stderr.lower()


def test_missing_mode_exits_2() -> None:
    proc = _run_script()
    assert proc.returncode == 2
    assert "usage" in proc.stderr.lower()


def test_run_is_read_only() -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")

    def status_digest() -> str:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return hashlib.sha256(out.encode("utf-8")).hexdigest()

    before = status_digest()
    proc = _run_script("all")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert status_digest() == before


# ---------------------------------------------------------------------------
# In-process tests with injected fake modules
# ---------------------------------------------------------------------------


def test_all_pass_with_fakes(capsys: pytest.CaptureFixture[str]) -> None:
    rc = vda.main(["all"], modules=_fake_modules())
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert out[-1] == "ALL_PASS all"
    assert all(line.startswith("PASS ") for line in out[:-1])
    assert len(out) - 1 == sum(vda.EXPECTED_MIN.values())


def test_failing_gate_reports_fail_line_and_exit_1(capsys: pytest.CaptureFixture[str]) -> None:
    mods = _fake_modules(
        protocol=SimpleNamespace(run=lambda: _gates("P", vda.EXPECTED_MIN["protocol"], failing=2))
    )
    rc = vda.main(["protocol"], modules=mods)
    out = capsys.readouterr().out.splitlines()
    assert rc == 1
    assert "FAIL P-02 :: broken" in out
    assert out[-1] == "FAILED 1 gate(s)"


def test_too_few_gates_adds_gate_count_fail(capsys: pytest.CaptureFixture[str]) -> None:
    mods = _fake_modules(universe=SimpleNamespace(run=lambda: []))
    rc = vda.main(["universe"], modules=mods)
    out = capsys.readouterr().out.splitlines()
    assert rc == 1
    assert any(line.startswith("FAIL universe-gate-count") for line in out)
    assert out[-1] == "FAILED 1 gate(s)"


def test_raising_module_reports_type_name_only(capsys: pytest.CaptureFixture[str]) -> None:
    def boom() -> list[tuple[str, bool, str]]:
        raise ValueError("SECRET-MESSAGE-do-not-print")

    mods = _fake_modules(params=SimpleNamespace(run=boom))
    rc = vda.main(["params"], modules=mods)
    captured = capsys.readouterr()
    assert rc == 1
    assert "FAIL params-error :: ValueError" in captured.out.splitlines()
    assert "SECRET-MESSAGE" not in captured.out
    assert "SECRET-MESSAGE" not in captured.err
    assert captured.out.splitlines()[-1] == "FAILED 1 gate(s)"


def test_docs_mode_routes_three_modules(capsys: pytest.CaptureFixture[str]) -> None:
    rc = vda.main(["docs"], modules=_fake_modules())
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    names = [line.split(" ", 1)[1] for line in out[:-1]]
    mins = vda.EXPECTED_MIN
    assert len(names) == mins["ops_risk"] + mins["exchange"] + mins["authority"]
    assert names[0].startswith("OR-")
    assert names[-1].startswith("AU-")
    assert out[-1] == "ALL_PASS docs"


def test_output_order_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    vda.main(["all"], modules=_fake_modules())
    first = capsys.readouterr().out
    vda.main(["all"], modules=_fake_modules())
    second = capsys.readouterr().out
    assert first == second
    prefixes = [line.split(" ", 1)[1].split("-", 1)[0] for line in first.splitlines()[:-1]]
    order: list[str] = []
    for p in prefixes:
        if not order or order[-1] != p:
            order.append(p)
    assert order == ["P", "PA", "U", "OR", "EX", "AU", "GL", "RQ", "DC"]


def test_unknown_mode_in_process(capsys: pytest.CaptureFixture[str]) -> None:
    assert vda.main(["bogus"], modules=_fake_modules()) == 2
    assert vda.main([], modules=_fake_modules()) == 2
    capsys.readouterr()


def test_missing_module_key_is_reported_not_raised(capsys: pytest.CaptureFixture[str]) -> None:
    mods = _fake_modules()
    del mods["authority"]
    rc = vda.main(["docs"], modules=mods)
    out = capsys.readouterr().out.splitlines()
    assert rc == 1
    assert any(line.startswith("FAIL authority-error") for line in out)


# ---------------------------------------------------------------------------
# CI wiring (static)
# ---------------------------------------------------------------------------

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "registry-gate.yml"

WORKFLOW_TEST_TARGETS = [
    "tests/test_registry_gate.py",
    "tests/test_registry.py",
    "tests/test_kill_gate_docs.py",
    "tests/test_kill_gate_clock.py",
    "tests/test_research_gate_negative.py",
    "tests/test_decision_alignment*.py",
]


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_workflow_runs_verify_script() -> None:
    text = _workflow_text()
    assert "- name: Decision alignment gates" in text
    assert "uv run python scripts/verify_decision_alignment.py all" in text
    step = text.split("- name: Decision alignment gates", 1)[1].split("\n      - name:", 1)[0]
    assert "set -eu" in step


def test_workflow_negative_tests_list_is_extended() -> None:
    text = _workflow_text()
    negative = text.split("- name: Registry negative tests", 1)[1]
    for target in WORKFLOW_TEST_TARGETS:
        assert target in negative, target


def test_workflow_steps_stay_well_formed() -> None:
    text = _workflow_text()
    steps_block = text.split("    steps:\n", 1)[1]
    step_lines = [line for line in steps_block.splitlines() if line.startswith("      - ")]
    assert step_lines, "no steps found"
    assert all(line.startswith("      - name:") for line in step_lines)
    names = [line.split("name:", 1)[1].strip() for line in step_lines]
    verify_idx = next(i for i, n in enumerate(names) if n.startswith("Decision alignment gates"))
    rehash_idx = next(i for i, n in enumerate(names) if n.startswith("Re-hash registry"))
    negative_idx = next(i for i, n in enumerate(names) if n.startswith("Registry negative tests"))
    assert rehash_idx < verify_idx < negative_idx


def test_workflow_test_targets_exist() -> None:
    for target in WORKFLOW_TEST_TARGETS:
        if "*" in target:
            assert list(REPO_ROOT.glob(target)), target
        else:
            assert (REPO_ROOT / target).is_file(), target
