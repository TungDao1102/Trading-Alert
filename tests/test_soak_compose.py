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


def restart_loop_problems(command: Sequence[str], probe: Sequence[str], restart: str) -> list[str]:
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


def test_refusal_codes_are_3_to_6_and_8_and_exclude_the_restartable_statuses() -> None:
    # 8 (INSTANCE_LEASE_HELD) joined the refusals with the single-instance guard (plan 16-55).
    assert REFUSAL_CODES == {3, 4, 5, 6, 8}
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


# --------------------------------------------------------------------------- #
# Task 2: the soak environment template.
# --------------------------------------------------------------------------- #

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def _template_lines() -> list[str]:
    assert SOAK_ENV_EXAMPLE.is_file(), "deploy/soak.env.example does not exist"
    return SOAK_ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()


def _template_assignments() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for line in _template_lines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        assert match is not None, f"not a NAME= line: {line[:40]!r}"
        found.append((match.group(1), match.group(2)))
    return found


def _env_example_names() -> set[str]:
    names: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = _ASSIGNMENT.match(line)
        if match:
            names.add(match.group(1))
    return names


def test_soak_template_has_names_only_and_no_binance_name() -> None:
    text = "\n".join(_template_lines())
    assert "BINANCE_" not in text
    assignments = _template_assignments()
    assert assignments, "template lists no variable"
    assert all(value == "" for _, value in assignments)
    assert not any(name.startswith("BINANCE_") for name, _ in assignments)
    names = [name for name, _ in assignments]
    assert len(names) == len(set(names)), "a name is listed twice"


def test_soak_template_lists_every_name_the_services_read_and_no_other() -> None:
    # Collector and paper read the database and runtime names (ALLOWED_ENV_NAMES); the backup
    # service reads every BACKUP_ name of .env.example; compose interpolates IMAGE_TAG.
    backup_names = {n for n in _env_example_names() if n.startswith("BACKUP_")}
    assert backup_names, ".env.example lists no BACKUP_ name"
    expected = set(ALLOWED_ENV_NAMES) | backup_names | {"IMAGE_TAG"}
    actual = {name for name, _ in _template_assignments()}
    assert expected - actual == set(), "missing from the template"
    assert actual - expected == set(), "unexpected in the template"


def test_soak_template_header_states_the_shared_env_file_and_the_refusal() -> None:
    header = "\n".join(line for line in _template_lines() if line.lstrip().startswith("#")).replace(
        "\n# ", " "
    )
    assert "x-app" in header
    assert "env_file" in header
    assert "BACKUP_" in header
    assert "WR-06" in header
    assert "Phase 24" in header
    assert "BINANCE" in header
    assert "refuses to start" in header
    assert "even" in header and "empty" in header
    assert "TRADING_ENV_FILE" in header
    assert "names only" in header.lower()


# --------------------------------------------------------------------------- #
# Task 3: the down -v guard of deploy/compose-soak.sh.
# --------------------------------------------------------------------------- #

REFUSAL_MESSAGE = "refused: down -v on the soak project"

_DOWN_VOLUMES = [
    ["down", "-v"],
    ["down", "--volumes"],
    ["down", "--remove-orphans", "-v"],
    ["--profile", "paper", "down", "--volumes"],
    ["-p", SOAK_PROJECT, "down", "-v"],
    ["--project-name", SOAK_PROJECT, "down", "--volumes"],
    ["--project-name=" + SOAK_PROJECT, "down", "-v"],
]


def _bash() -> str:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found")
    return bash


def _wrapper_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v
        for k, v in _hermetic_env().items()
        if k not in {"COMPOSE_PROJECT_NAME", "TRADING_ENV_FILE", "DRY_RUN"}
    }
    # DRY_RUN=1 always: even an unexpectedly allowed command would only be printed.
    env["DRY_RUN"] = "1"
    env.update(extra or {})
    return env


def _run_wrapper(
    args: Sequence[str], extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    assert SOAK_WRAPPER.is_file(), "deploy/compose-soak.sh does not exist"
    return subprocess.run(
        [_bash(), SOAK_WRAPPER.as_posix(), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=REPO_ROOT,
        env=_wrapper_env(extra_env),
    )


def _run_predicate(args: Sequence[str]) -> int:
    """Exit status of the guard predicate for `args` (0 = the arguments remove volumes)."""
    assert SOAK_WRAPPER.is_file(), "deploy/compose-soak.sh does not exist"
    proc = subprocess.run(
        [
            _bash(),
            "-c",
            'source "$1"; shift; soak_args_remove_volumes "$@"',
            "soak",
            SOAK_WRAPPER.as_posix(),
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=REPO_ROOT,
        env=_wrapper_env(),
    )
    assert proc.returncode in (0, 1), f"predicate failed to run: {proc.stderr.strip()[:200]}"
    return proc.returncode


@pytest.mark.parametrize("args", _DOWN_VOLUMES, ids=[" ".join(a) for a in _DOWN_VOLUMES])
def test_wrapper_refuses_down_with_volumes(args: list[str]) -> None:
    proc = _run_wrapper(args)
    assert proc.returncode != 0
    assert REFUSAL_MESSAGE in proc.stderr
    assert "+ docker" not in proc.stdout, "a refused command must not be announced as run"


def test_wrapper_refuses_down_with_volumes_when_the_project_comes_from_the_environment() -> None:
    proc = _run_wrapper(["down", "-v"], {"COMPOSE_PROJECT_NAME": SOAK_PROJECT})
    assert proc.returncode != 0
    assert REFUSAL_MESSAGE in proc.stderr
    proc = _run_wrapper(["down", "--volumes"], {"COMPOSE_PROJECT_NAME": SOAK_PROJECT})
    assert proc.returncode != 0
    assert REFUSAL_MESSAGE in proc.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["down"],
        ["ps"],
        ["up", "-d"],
        ["--profile", "paper", "up", "-d", "paper"],
        ["logs", "paper"],
    ],
    ids=lambda a: " ".join(a),
)
def test_wrapper_forwards_every_other_command_to_the_soak_project(args: list[str]) -> None:
    proc = _run_wrapper(args)
    assert proc.returncode == 0, proc.stderr.strip()[:300]
    first = proc.stdout.splitlines()[0]
    assert first == "+ docker compose -p trading-soak " + " ".join(args)


def test_wrapper_refuses_another_project_name() -> None:
    for args in (["-p", "trading", "ps"], ["--project-name", "trading", "ps"]):
        proc = _run_wrapper(args)
        assert proc.returncode != 0
        assert SOAK_PROJECT in proc.stderr
        assert "+ docker" not in proc.stdout


def test_wrapper_pins_the_project_even_when_the_environment_names_another() -> None:
    proc = _run_wrapper(["ps"], {"COMPOSE_PROJECT_NAME": "trading"})
    assert proc.returncode == 0, proc.stderr.strip()[:300]
    assert proc.stdout.splitlines()[0] == "+ docker compose -p trading-soak ps"


def test_guard_predicate_negative_control() -> None:
    assert _run_predicate(["down", "-v"]) == 0
    assert _run_predicate(["down", "--volumes"]) == 0
    assert _run_predicate(["down"]) == 1
    assert _run_predicate(["up", "-d"]) == 1
    assert _run_predicate(["down", "--remove-orphans"]) == 1


_COMPOSE_DOWN_VOLUMES = re.compile(
    r"\bdocker(?:\s+|-)compose\b.*\bdown\b(?=.*(?:\s-[A-Za-z]*v[A-Za-z]*(?:\s|$)|\s--volumes\b))"
)


def unguarded_down_volumes(lines: Sequence[str]) -> list[str]:
    """Command lines that run `docker compose ... down` with volume removal.

    A call through `deploy/compose-soak.sh` never matches (the wrapper refuses it), comment
    lines and the wrapper's own `die` message are prose, not invocations.
    """
    found: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("#", "die ", "printf ")):
            continue
        if _COMPOSE_DOWN_VOLUMES.search(stripped):
            found.append(stripped)
    return found


def fenced_code_lines(markdown: str) -> list[str]:
    """The lines inside fenced code blocks of a markdown text (prose is excluded)."""
    inside = False
    collected: list[str] = []
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            collected.append(line)
    return collected


def test_scan_negative_control_finds_seeded_unguarded_commands() -> None:
    seeded = [
        "docker compose -p trading-soak down -v",
        "COMPOSE_PROJECT_NAME=trading-soak docker compose down --volumes",
        "docker compose --profile paper down --remove-orphans -v",
        "docker-compose -p trading-soak down -v",
    ]
    assert unguarded_down_volumes(seeded) == seeded
    harmless = [
        "docker compose -p trading-soak down",
        "deploy/compose-soak.sh down",
        "deploy/compose-soak.sh down -v",
        "# docker compose down -v is never run on the soak project",
        "docker compose up -d --remove-orphans",
    ]
    assert unguarded_down_volumes(harmless) == []
    markdown = "Never run docker compose down -v here.\n\n```bash\ndocker compose down -v\n```\n"
    assert unguarded_down_volumes(fenced_code_lines(markdown)) == ["docker compose down -v"]
    assert unguarded_down_volumes(fenced_code_lines("Never run docker compose down -v.")) == []


def test_runbook_and_deploy_scripts_hold_no_unguarded_down_with_volumes() -> None:
    assert SOAK_WRAPPER.is_file(), "deploy/compose-soak.sh does not exist"
    found: dict[str, list[str]] = {}
    runbook = unguarded_down_volumes(fenced_code_lines(RUNBOOK.read_text(encoding="utf-8")))
    if runbook:
        found[RUNBOOK.name] = runbook
    for script in sorted(DEPLOY_DIR.glob("*.sh")):
        hits = unguarded_down_volumes(script.read_text(encoding="utf-8").splitlines())
        if hits:
            found[script.name] = hits
    assert found == {}
