"""`deploy/compose-rehearsal.sh`: the guarded wrapper of the `trading-rehearsal` project (16-53).

Docker is replaced by a stub on PATH that only records its arguments, so nothing here needs a
daemon, a network or a real env file. The stub answers the soak probe (`docker ps -q ...`) from
FAKE_SOAK_CONTAINERS. Every refusal must happen before any compose call, and no output ever
carries a value of the secret-looking variables the tests plant.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.infra_helpers import find_bash, infra_skip

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "deploy" / "compose-rehearsal.sh"
PROJECT = "trading-rehearsal"
SECRET = "rehearsal-secret-value-never-printed"

STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE_DOCKER_LOG"
if [[ ${1:-} == ps ]]; then
  printf '%s' "${FAKE_SOAK_CONTAINERS:-}"
  exit "${FAKE_DOCKER_PS_EXIT:-0}"
fi
exit 0
"""


def _bash() -> str:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found")
    return bash


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        stub = self.bin / "docker"
        stub.write_text(STUB, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
        self.log = tmp_path / "docker.log"
        self.env_file = tmp_path / "rehearsal.env"
        self.env_file.write_text("POSTGRES_USER=rehearsal\nPAPER_STRATEGY_ID=x\n", encoding="utf-8")

    def calls(self) -> list[str]:
        if not self.log.is_file():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def run(
        self,
        args: Sequence[str],
        extra_env: dict[str, str] | None = None,
        *,
        env_file: str | None = "default",
    ) -> subprocess.CompletedProcess[str]:
        assert WRAPPER.is_file(), "deploy/compose-rehearsal.sh does not exist"
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("BINANCE_")
            and k not in {"COMPOSE_PROJECT_NAME", "TRADING_ENV_FILE", "DRY_RUN"}
        }
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env["FAKE_DOCKER_LOG"] = self.log.as_posix()
        env["MSYS_NO_PATHCONV"] = "1"
        if env_file == "default":
            env["TRADING_ENV_FILE"] = self.env_file.as_posix()
        elif env_file is not None:
            env["TRADING_ENV_FILE"] = env_file
        env.update(extra_env or {})
        return subprocess.run(
            [_bash(), WRAPPER.as_posix(), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=REPO_ROOT,
            env=env,
        )


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def _expected(rig: Rig, *args: str) -> str:
    return f"docker compose -p {PROJECT} --env-file {rig.env_file.as_posix()} " + " ".join(args)


def test_dry_run_prints_the_project_command_and_calls_no_docker(rig: Rig) -> None:
    proc = rig.run(["--dry-run", "up", "-d", "postgres"])
    assert proc.returncode == 0, proc.stderr.strip()[:300]
    assert proc.stdout.splitlines()[-1] == "+ " + _expected(rig, "up", "-d", "postgres")
    assert rig.calls() == []


def test_the_dry_run_environment_switch_does_the_same(rig: Rig) -> None:
    proc = rig.run(["ps"], {"DRY_RUN": "1"})
    assert proc.returncode == 0, proc.stderr.strip()[:300]
    assert proc.stdout.splitlines()[-1] == "+ " + _expected(rig, "ps")
    assert rig.calls() == []


def test_a_real_run_probes_the_soak_then_forwards_exactly_the_command(rig: Rig) -> None:
    proc = rig.run(["--profile", "paper", "up", "-d", "--no-build"])
    assert proc.returncode == 0, proc.stderr.strip()[:300]
    calls = rig.calls()
    assert calls[0].startswith("ps -q --filter")
    assert "label=com.docker.compose.project=trading-soak" in calls[0]
    assert calls[1:] == [_expected(rig, "--profile", "paper", "up", "-d", "--no-build")[7:]]
    assert proc.stdout.splitlines()[0] == "+ " + _expected(
        rig, "--profile", "paper", "up", "-d", "--no-build"
    )


def test_the_project_is_pinned_even_when_the_environment_names_another(rig: Rig) -> None:
    proc = rig.run(["--dry-run", "ps"], {"COMPOSE_PROJECT_NAME": "trading-soak"})
    assert proc.returncode == 0, proc.stderr.strip()[:300]
    assert proc.stdout.splitlines()[-1] == "+ " + _expected(rig, "ps")


@pytest.mark.parametrize(
    "args",
    [
        ["-p", "trading", "ps"],
        ["--project-name", "trading-soak", "ps"],
        ["--project-name=trading", "ps"],
        ["--env-file", "other.env", "ps"],
        ["--env-file=other.env", "ps"],
    ],
    ids=lambda a: " ".join(a),
)
def test_another_project_or_env_file_flag_is_refused(rig: Rig, args: list[str]) -> None:
    proc = rig.run(args)
    assert proc.returncode == 1
    assert "refused" in proc.stderr
    assert "+ docker" not in proc.stdout
    assert rig.calls() == []


def test_the_project_name_flag_naming_the_rehearsal_is_accepted(rig: Rig) -> None:
    proc = rig.run(["--dry-run", "-p", PROJECT, "ps"])
    assert proc.returncode == 0, proc.stderr.strip()[:300]


def test_no_arguments_is_a_usage_error(rig: Rig) -> None:
    assert rig.run([]).returncode == 2
    assert rig.run(["--dry-run"]).returncode == 2
    assert rig.calls() == []


@pytest.mark.parametrize("mode", ["unset", "missing", "inside-checkout"])
def test_a_missing_or_in_checkout_env_file_is_refused(rig: Rig, mode: str) -> None:
    if mode == "unset":
        proc = rig.run(["--dry-run", "ps"], env_file=None)
    elif mode == "missing":
        proc = rig.run(["--dry-run", "ps"], env_file=(rig.env_file.parent / "nope.env").as_posix())
    else:
        inside = REPO_ROOT / "deploy" / "soak.env.example"
        assert inside.is_file()
        proc = rig.run(["--dry-run", "ps"], env_file=inside.as_posix())
    assert proc.returncode == 1
    assert "refused" in proc.stderr
    assert "+ docker" not in proc.stdout
    assert rig.calls() == []


@pytest.mark.parametrize("dry", [True, False], ids=["dry-run", "live"])
def test_a_binance_variable_in_the_environment_is_refused_by_name_only(
    rig: Rig, dry: bool
) -> None:
    args = (["--dry-run"] if dry else []) + ["ps"]
    proc = rig.run(args, {"BINANCE_API_KEY": SECRET, "BINANCE_EMPTY": ""})
    assert proc.returncode == 1
    assert "BINANCE_API_KEY" in proc.stderr and "BINANCE_EMPTY" in proc.stderr
    assert SECRET not in proc.stderr + proc.stdout
    assert "+ docker" not in proc.stdout
    assert rig.calls() == []


@pytest.mark.parametrize("dry", [True, False], ids=["dry-run", "live"])
@pytest.mark.parametrize("prefix", ["", "export ", "  "], ids=["plain", "export", "indented"])
def test_a_binance_name_in_the_env_file_is_refused_by_name_only(
    rig: Rig, dry: bool, prefix: str
) -> None:
    rig.env_file.write_text(
        f"POSTGRES_USER=rehearsal\n# BINANCE_COMMENTED=x\n{prefix}BINANCE_LIVE_API_KEY={SECRET}\n",
        encoding="utf-8",
    )
    proc = rig.run((["--dry-run"] if dry else []) + ["ps"])
    assert proc.returncode == 1
    assert "BINANCE_LIVE_API_KEY" in proc.stderr
    assert "BINANCE_COMMENTED" not in proc.stderr
    assert SECRET not in proc.stderr + proc.stdout
    assert rig.calls() == []


def test_negative_control_an_env_file_without_binance_names_is_not_refused(rig: Rig) -> None:
    rig.env_file.write_text("POSTGRES_USER=rehearsal\nBINANCEISH=1\n", encoding="utf-8")
    proc = rig.run(["--dry-run", "ps"])
    assert proc.returncode == 0, proc.stderr.strip()[:300]


def test_a_running_soak_project_refuses_the_rehearsal(rig: Rig) -> None:
    proc = rig.run(["up", "-d"], {"FAKE_SOAK_CONTAINERS": "0123456789ab\n"})
    assert proc.returncode == 1
    assert "trading-soak" in proc.stderr
    assert all(call.startswith("ps ") for call in rig.calls())
    assert "+ docker" not in proc.stdout


def test_a_failing_soak_probe_fails_closed(rig: Rig) -> None:
    proc = rig.run(["up", "-d"], {"FAKE_DOCKER_PS_EXIT": "1"})
    assert proc.returncode == 1
    assert "refused" in proc.stderr
    assert all(call.startswith("ps ") for call in rig.calls())


def test_the_dry_run_does_not_probe_the_soak(rig: Rig) -> None:
    proc = rig.run(["--dry-run", "up", "-d"], {"FAKE_SOAK_CONTAINERS": "0123456789ab\n"})
    assert proc.returncode == 0, proc.stderr.strip()[:300]
    assert rig.calls() == []
