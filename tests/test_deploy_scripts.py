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
        [shellcheck, "-x", "-P", "SCRIPTDIR", script.as_posix()],
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


# --- 16-55 Task 1: deploy/soak-image.sh runs the in-image load check before it records ------

IN_IMAGE_CONFIG = "/app/config/paper/paper-runtime-v1.toml"
FAKE_IMAGE_ID = "sha256:" + "ab" * 32

# A docker stub: records each call, answers `image inspect` with a fixed id and exits from
# `run` with FAKE_DOCKER_RUN_STATUS (the in-image check), everything else with 0.
DOCKER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE_DOCKER_LOG"
case ${1:-} in
  image) printf '%s\\n' "$FAKE_IMAGE_ID" ;;
  run) exit "${FAKE_DOCKER_RUN_STATUS:-0}" ;;
esac
exit 0
"""


class _SoakImageRig:
    """A clean throwaway checkout holding the soak recipe scripts, plus a stub docker on PATH."""

    def __init__(self, tmp_path: Path) -> None:
        self.repo = tmp_path / "checkout"
        (self.repo / "deploy").mkdir(parents=True)
        for name in ("soak-image.sh", "lib.sh", "compose-soak.sh"):
            (self.repo / "deploy" / name).write_bytes((DEPLOY_DIR / name).read_bytes())
        for args in (
            ("init", "-q"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "test"),
            ("config", "core.autocrlf", "false"),
            ("add", "-A"),
            ("commit", "-q", "-m", "init"),
        ):
            subprocess.run(
                ["git", *args], cwd=self.repo, check=True, capture_output=True, timeout=60
            )
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        stub = self.bin / "docker"
        stub.write_text(DOCKER_STUB, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
        self.log = tmp_path / "docker.log"
        self.state = tmp_path / "state"

    def commit(self) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.is_file() else []

    def run(self, *args: str, run_status: int = 0) -> subprocess.CompletedProcess[str]:
        bash = find_bash()
        if bash is None:
            infra_skip("bash not found")
        import os

        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"DRY_RUN", "IMAGE_TAG", "COMPOSE_PROJECT_NAME", "TRADING_ENV_FILE"}
        }
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env["FAKE_DOCKER_LOG"] = self.log.as_posix()
        env["FAKE_IMAGE_ID"] = FAKE_IMAGE_ID
        env["FAKE_DOCKER_RUN_STATUS"] = str(run_status)
        env["TRADING_DEPLOY_STATE_DIR"] = self.state.as_posix()
        env["MSYS_NO_PATHCONV"] = "1"
        return subprocess.run(
            [bash, (self.repo / "deploy" / "soak-image.sh").as_posix(), *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=env,
        )


def _image_check_call(commit: str) -> str:
    return (
        f"run --rm --network none --env PAPER_RUNTIME_CONFIG={IN_IMAGE_CONFIG} "
        f"--entrypoint /app/.venv/bin/python trading-alert:{commit} "
        "-m scripts.check_image_paths --root /app"
    )


def test_soak_image_runs_the_in_image_check_after_the_build_and_before_the_record(
    tmp_path: Path,
) -> None:
    rig = _SoakImageRig(tmp_path)
    commit = rig.commit()
    proc = rig.run()
    assert proc.returncode == 0, proc.stderr.strip()[-500:]
    calls = rig.calls()
    build = next(i for i, c in enumerate(calls) if c.startswith("compose ") and " build" in c)
    check = calls.index(_image_check_call(commit))
    assert build < check, calls
    assert (rig.state / "soak-image.env").is_file()
    assert "--network none" in calls[check]


def test_soak_image_writes_no_record_when_the_in_image_check_fails(tmp_path: Path) -> None:
    rig = _SoakImageRig(tmp_path)
    commit = rig.commit()
    proc = rig.run(run_status=1)
    assert proc.returncode != 0
    assert _image_check_call(commit) in rig.calls()
    assert not (rig.state / "soak-image.env").exists()
    assert not (rig.state / "soak-image.history").exists()
    assert "in-image check" in proc.stderr


def test_soak_image_dry_run_prints_the_check_and_runs_no_docker(tmp_path: Path) -> None:
    rig = _SoakImageRig(tmp_path)
    commit = rig.commit()
    proc = rig.run("--dry-run")
    assert proc.returncode == 0, proc.stderr.strip()[-500:]
    assert f"+ docker {_image_check_call(commit)}" in proc.stdout.splitlines()
    assert rig.calls() == []
    assert not rig.state.exists()


def test_soak_env_template_names_the_in_image_config_path_without_a_value() -> None:
    lines = (DEPLOY_DIR / "soak.env.example").read_text(encoding="utf-8").splitlines()
    comments = [ln for ln in lines if ln.startswith("#")]
    assert any(IN_IMAGE_CONFIG in ln for ln in comments), "no comment names the in-image path"
    assignments = [ln for ln in lines if ln and not ln.startswith("#")]
    assert "PAPER_RUNTIME_CONFIG=" in assignments
    assert all(ln.endswith("=") for ln in assignments), "the template stays names-only"
