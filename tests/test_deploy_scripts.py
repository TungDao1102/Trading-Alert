"""Hygiene gate over every shell script and file shipped under ``deploy/`` (13.1-05, D-27).

The gate globs ``deploy/*.sh`` so scripts added by later plans are covered without editing
this file. Linux-bound files must be LF-only (a CR in a shebang line or a heredoc breaks the
script on the host, threat T-13.1-25), every script must declare strict mode, parse under
``bash -n`` and, where shellcheck is installed (CI), pass ``shellcheck -x``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.infra_helpers import find_bash, infra_skip, require_tool

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
CUTOVER_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "cutover"

SCRIPTS = sorted(DEPLOY_DIR.glob("*.sh"))
SCRIPT_IDS = [path.name for path in SCRIPTS]


def _lf_only_files() -> list[Path]:
    files = [p for p in DEPLOY_DIR.rglob("*") if p.is_file()] if DEPLOY_DIR.is_dir() else []
    if CUTOVER_FIXTURES.is_dir():
        files += [p for p in CUTOVER_FIXTURES.rglob("*") if p.is_file()]
    return sorted(files)


LF_FILES = _lf_only_files()


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_deploy_directory_has_scripts() -> None:
    names = {path.name for path in SCRIPTS}
    assert {"lib.sh", "bootstrap.sh"} <= names


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_script_header_and_strict_mode(script: Path) -> None:
    lines = script.read_text(encoding="utf-8").split("\n")
    assert lines[0] == "#!/usr/bin/env bash", f"{script.name}: line 1 must be the env-bash shebang"
    assert "set -Eeuo pipefail" in lines[:15], f"{script.name}: strict mode must be near the top"


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_script_parses_under_bash_n(script: Path) -> None:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found")
    proc = subprocess.run(
        [bash, "-n", script.as_posix()],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"bash -n {script.name}: {proc.stderr}"


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_script_passes_shellcheck(script: Path) -> None:
    shellcheck = require_tool("shellcheck")
    proc = subprocess.run(
        [shellcheck, "-x", script.as_posix()],
        capture_output=True,
        text=True,
        check=False,
        cwd=DEPLOY_DIR,
    )
    assert proc.returncode == 0, f"shellcheck {script.name}:\n{proc.stdout}{proc.stderr}"


@pytest.mark.parametrize(
    "path", LF_FILES, ids=[p.relative_to(REPO_ROOT).as_posix() for p in LF_FILES]
)
def test_linux_bound_files_have_no_carriage_return(path: Path) -> None:
    assert b"\r" not in path.read_bytes(), f"{path.relative_to(REPO_ROOT)} contains a CR"


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_gitattributes_forces_lf_for_deploy_files(script: Path) -> None:
    if not (REPO_ROOT / ".git").exists():
        infra_skip("not a git checkout")
    rel = script.relative_to(REPO_ROOT).as_posix()
    proc = _git("check-attr", "eol", "--", rel)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"{rel}: eol: lf"


def test_gitattributes_covers_cutover_fixtures_and_keeps_render_golden() -> None:
    text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    rules = {line.strip() for line in text.splitlines() if line.strip()}
    assert "tests/fixtures/phase10/render_golden/* -text" in rules
    for rule in (
        "deploy/** text eol=lf",
        "*.sh text eol=lf",
        "*.service text eol=lf",
        "*.timer text eol=lf",
        "Dockerfile text eol=lf",
        ".dockerignore text eol=lf",
        "docker-compose.yml text eol=lf",
        "*.yml text eol=lf",
        ".python-version text eol=lf",
        ".env.example text eol=lf",
        "tests/fixtures/cutover/** text eol=lf",
    ):
        assert rule in rules, f".gitattributes is missing: {rule}"


def test_tracked_deploy_scripts_are_executable_in_the_index() -> None:
    """core.fileMode is false on Windows, so the executable bit lives only in the index."""
    if not (REPO_ROOT / ".git").exists():
        infra_skip("not a git checkout")
    proc = _git("ls-files", "-s", "--", "deploy")
    assert proc.returncode == 0, proc.stderr
    bad = []
    for line in proc.stdout.splitlines():
        meta, _, name = line.partition("\t")
        if name.endswith(".sh") and not meta.startswith("100755"):
            bad.append(f"{name} ({meta.split()[0]})")
    assert not bad, f"tracked scripts must be mode 100755 (git update-index --chmod=+x): {bad}"
