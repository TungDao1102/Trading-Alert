"""Soak deployment configuration of the paper runtime (plan 16-32, D-01, D-32).

Three groups of checks, none of which touches a Docker daemon or the network:

- the `paper` service of `docker-compose.yml` runs `python -m src.paper.runtime` with its real
  probe, a restart policy that cannot loop on a refusal, and the logs volume (static text checks,
  because the repository carries no YAML library, plus one `docker compose config` check that
  needs only the compose CLI and is skipped through the infra helpers when it is absent);
- `deploy/soak.env.example` lists variable names only and never a `BINANCE_` name;
- `deploy/compose-soak.sh` refuses `down -v` on the soak project however the project is named,
  and no script or runbook command line runs an unguarded `down -v` against it.

The resolved compose config holds secrets, so no assertion message ever prints it.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from src.paper.runtime import build_parser
from src.paper.runtime_config import ALLOWED_ENV_NAMES, REFUSAL_CODES, ExitCode
from tests.infra_helpers import compose_cli_available, find_bash, infra_skip
from tests.test_deploy_compose import _hermetic_env, _write_project

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DEPLOY_DIR = REPO_ROOT / "deploy"
RUNBOOK = REPO_ROOT / "docs" / "operations" / "RUNBOOK.md"
SOAK_ENV_EXAMPLE = DEPLOY_DIR / "soak.env.example"
SOAK_WRAPPER = DEPLOY_DIR / "compose-soak.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

PYTHON = "/app/.venv/bin/python"
PAPER_COMMAND = [PYTHON, "-m", "src.paper.runtime", "--hold-on-refusal"]
PAPER_PROBE = ["CMD", PYTHON, "-m", "src.paper.runtime", "--healthcheck"]
SOAK_PROJECT = "trading-soak"


# --------------------------------------------------------------------------- #
# Static reading of docker-compose.yml (no YAML library in the project).
# --------------------------------------------------------------------------- #


def _service_block(name: str) -> str:
    """The text of one service: from its two-space `name:` line to the next service or section."""
    lines = COMPOSE_FILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line == f"  {name}:")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line and not line.startswith(" ") and not line.startswith("#"):
            end = i
            break
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            end = i
            break
    return "\n".join(lines[start:end])


def _comment_block_before(name: str) -> str:
    """The contiguous `#` comment lines directly above a service."""
    lines = COMPOSE_FILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line == f"  {name}:")
    collected: list[str] = []
    for line in reversed(lines[:start]):
        if not line.strip().startswith("#"):
            break
        collected.append(line.strip())
    return "\n".join(reversed(collected))


def _flow_list(block: str, key_pattern: str) -> list[str]:
    """A one-line JSON-style flow list such as `command: ["a", "b"]` (single-line only)."""
    match = re.search(rf"^\s*{key_pattern}:\s*(\[.*\])\s*$", block, flags=re.MULTILINE)
    assert match is not None, f"no one-line list for {key_pattern!r}"
    parsed = json.loads(match.group(1))
    assert isinstance(parsed, list)
    return [str(item) for item in parsed]


def _scalar(block: str, key: str) -> str:
    match = re.search(rf"^    {key}:\s*(.+?)\s*$", block, flags=re.MULTILINE)
    assert match is not None, f"no {key!r} key"
    return match.group(1).strip("\"'")


def _health_scalar(block: str, key: str) -> str:
    match = re.search(rf"^      {key}:\s*(\S+)\s*$", block, flags=re.MULTILINE)
    assert match is not None, f"no healthcheck {key!r}"
    return match.group(1)


def restart_loop_problems(
    command: Sequence[str], probe: Sequence[str], restart: str
) -> list[str]:
    """Why a service definition could loop on a configuration refusal (empty means it cannot).

    The runtime exits with 3 to 6 on a refusal; `on-failure` restarts every non-zero exit, so the
    command must carry `--hold-on-refusal` (the process then stays up and unhealthy instead).
    """
    problems: list[str] = []
    if "--hold-on-refusal" not in command:
        problems.append("command lacks --hold-on-refusal")
    if "--hold-on-refusal" in probe:
        problems.append("healthcheck must not carry --hold-on-refusal")
    if "--healthcheck" not in probe:
        problems.append("healthcheck lacks --healthcheck")
    if restart != "on-failure":
        problems.append(f"restart policy is {restart!r}, expected 'on-failure'")
    return problems


def _runtime_args(command: Sequence[str]) -> list[str]:
    assert list(command[:3]) == [PYTHON, "-m", "src.paper.runtime"]
    return list(command[3:])


# --------------------------------------------------------------------------- #
# Task 1: the paper service.
# --------------------------------------------------------------------------- #


def test_paper_service_runs_the_runtime_with_its_probe() -> None:
    block = _service_block("paper")
    assert _flow_list(block, "command") == PAPER_COMMAND
    assert _flow_list(block, "test") == PAPER_PROBE
    assert _scalar(block, "restart") == "on-failure"
    assert _flow_list(block, "profiles") == ["paper"]
    assert "disable: true" not in block
    assert "SystemExit" not in block


def test_paper_service_uses_the_logs_volume_and_waits_for_the_migration() -> None:
    block = _service_block("paper")
    assert re.search(r"^\s+- logs:/app/logs\s*$", block, flags=re.MULTILINE)
    volume_lines = re.findall(r"^\s+- (\S+:\S+)\s*$", block, flags=re.MULTILINE)
    assert volume_lines == ["logs:/app/logs"]
    assert not any(line.startswith((".", "/", "~")) for line in volume_lines)
    assert re.search(
        r"db-upgrade:\s*\n\s+condition: service_completed_successfully", block, flags=re.MULTILINE
    )
    assert "environment: *database-env" in block
    assert "<<: *app" in block
    assert not re.search(r"^\s+ports:", block, flags=re.MULTILINE)


def test_paper_probe_timing_copies_the_collector() -> None:
    paper = _service_block("paper")
    collector = _service_block("collector")
    for key in ("interval", "timeout", "start_period", "retries"):
        assert _health_scalar(paper, key) == _health_scalar(collector, key), key


def test_paper_command_arguments_parse_with_the_runtime_parser() -> None:
    parser = build_parser()
    held = parser.parse_args(_runtime_args(PAPER_COMMAND))
    assert held.hold_on_refusal is True
    assert held.healthcheck is False
    probe = parser.parse_args(_runtime_args(PAPER_PROBE[1:]))
    assert probe.healthcheck is True
    assert probe.hold_on_refusal is False


def test_compose_paper_service_cannot_restart_loop_on_a_refusal() -> None:
    block = _service_block("paper")
    problems = restart_loop_problems(
        _flow_list(block, "command"), _flow_list(block, "test")[1:], _scalar(block, "restart")
    )
    assert problems == []


def test_restart_loop_guard_catches_a_service_without_the_hold_flag() -> None:
    seeded_command = [PYTHON, "-m", "src.paper.runtime"]
    problems = restart_loop_problems(seeded_command, PAPER_PROBE[1:], "on-failure")
    assert problems == ["command lacks --hold-on-refusal"]
    assert restart_loop_problems(PAPER_COMMAND, PAPER_PROBE[1:], "unless-stopped") != []


def test_refusal_codes_are_3_to_6_and_exclude_the_restartable_statuses() -> None:
    assert REFUSAL_CODES == {3, 4, 5, 6}
    assert 1 not in REFUSAL_CODES
    assert int(ExitCode.FAIL_CLOSED_RUNTIME) == 7
    assert 7 not in REFUSAL_CODES


def test_compose_comment_names_every_refusal_code() -> None:
    comment = _comment_block_before("paper")
    for code in sorted(REFUSAL_CODES):
        assert re.search(rf"(?<!\d){code}(?!\d)", comment), f"refusal code {code} not named"
    for words in ("trade-capable", "not ratified", "pinned epoch", "mismatch"):
        assert words in comment, words
    assert "--hold-on-refusal" in comment
    assert "WR-06" in comment


def _soak_config(tmp_path: Path) -> dict[str, Any]:
    available, detail = compose_cli_available()
    if not available:
        infra_skip(f"docker compose CLI unavailable: {detail}")
    project = _write_project(tmp_path)
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(project),
            "-f",
            str(project / "docker-compose.yml"),
            "-p",
            SOAK_PROJECT,
            "--profile",
            "paper",
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=_hermetic_env(),
    )
    # stderr can echo interpolation errors but never the resolved config.
    assert proc.returncode == 0, f"compose config failed: {proc.stderr.strip()[:400]}"
    parsed = json.loads(proc.stdout)
    assert isinstance(parsed, dict)
    return parsed


def test_soak_project_renders_with_its_own_volume_names(tmp_path: Path) -> None:
    config = _soak_config(tmp_path)
    assert config["name"] == SOAK_PROJECT
    volumes = config["volumes"]
    assert volumes, "no volumes rendered"
    for key, volume in volumes.items():
        assert volume["name"] == f"{SOAK_PROJECT}_{key}", key
    assert "pgdata" in volumes
    paper = config["services"]["paper"]
    assert paper["command"] == PAPER_COMMAND
    assert paper["healthcheck"]["test"] == PAPER_PROBE
    assert paper["restart"] == "on-failure"
    assert not paper.get("ports")
