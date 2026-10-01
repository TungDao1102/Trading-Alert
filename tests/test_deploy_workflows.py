"""Text-level gate over the GitHub workflows (13.1-02, D-01/D-02/D-03/D-19).

No YAML library: the workflows are read as text (CRLF-normalised) and checked with regexes
per job block. The gate pins every action to a commit SHA, fixes the runner and the uv
version, and bans failure suppression in ci.yml so the pipeline cannot pass vacuously
(threats T-13.1-04, T-13.1-06, T-13.1-07).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"
ALL_WORKFLOWS = ("ci.yml",)
UV_VERSION = "0.12.21"
RUNNER = "ubuntu-24.04"

# Failure-suppression literals live only in this test file.
SUPPRESSION_KEY = "continue-on-error"
OR_TRUE_PATTERNS = (r"\|\|\s*true\b", r"\|\|\s*:(\s|$)", r"\bset\s+\+e\b")

USES_RE = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)(?P<rest>.*)$", re.MULTILINE)
PINNED_USES_RE = re.compile(
    r"^\s*-?\s*uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?"
    r"@[0-9a-f]{40} # v\d+\.\d+\.\d+\s*$",
    re.MULTILINE,
)
JOB_HEADER_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.MULTILINE)


def _read(name: str) -> str:
    return (WORKFLOWS_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def _jobs(text: str) -> dict[str, str]:
    """Split a workflow into {job_id: block} using the two-space job headers under `jobs:`."""
    marker = re.search(r"^jobs:\s*$", text, re.MULTILINE)
    assert marker is not None, "workflow has no jobs: section"
    body = text[marker.end() :]
    headers = list(JOB_HEADER_RE.finditer(body))
    jobs: dict[str, str] = {}
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        jobs[header.group(1)] = body[header.start() : end]
    return jobs


# --------------------------------------------------------------------------------------
# ci.yml structure
# --------------------------------------------------------------------------------------


def test_ci_declares_the_four_jobs() -> None:
    assert set(_jobs(_read("ci.yml"))) == {"test", "lint", "types", "docker"}


def test_ci_triggers_and_permissions() -> None:
    text = _read("ci.yml")
    assert re.search(r"^on:\s*$", text, re.MULTILINE)
    assert re.search(r"^  push:\s*\n    branches: \[master\]", text, re.MULTILINE)
    assert re.search(r"^  pull_request:\s*\n    branches: \[master\]", text, re.MULTILINE)
    assert "pull_request_target" not in text
    assert re.search(r"^permissions:\s*\n  contents: read\s*$", text, re.MULTILINE)
    assert re.search(r"^concurrency:", text, re.MULTILINE)
    assert "cancel-in-progress: true" in text


def test_ci_strict_mode_and_no_downloaded_python_at_top_level() -> None:
    text = _read("ci.yml")
    header = text[: re.search(r"^jobs:\s*$", text, re.MULTILINE).start()]  # type: ignore[union-attr]
    assert re.search(r'^  TRADING_CI_STRICT: "1"\s*$', header, re.MULTILINE)
    assert re.search(r"^  UV_PYTHON_DOWNLOADS: never\s*$", header, re.MULTILINE)


@pytest.mark.parametrize("job", ["test", "lint", "types", "docker"])
def test_ci_every_job_is_standard(job: str) -> None:
    block = _jobs(_read("ci.yml"))[job]
    assert f"runs-on: {RUNNER}" in block
    assert re.search(r"timeout-minutes: \d+", block)
    assert "uv sync --frozen --extra dev" in block
    assert "python-version-file: .python-version" in block
    assert f'version: "{UV_VERSION}"' in block
    assert "enable-cache: true" in block


def test_ci_test_job() -> None:
    block = _jobs(_read("ci.yml"))["test"]
    assert "fetch-depth: 0" in block
    assert 'uv run pytest -m "not docker"' in block
    image = re.search(r"^\s+image: (\S+)$", block, re.MULTILINE)
    assert image is not None
    assert image.group(1).startswith("postgres:17.11-bookworm@sha256:")
    assert re.fullmatch(r"postgres:17\.11-bookworm@sha256:[0-9a-f]{64}", image.group(1))
    assert "pg_isready" in block
    url = re.search(r"TEST_DATABASE_URL: (\S+)", block)
    assert url is not None
    assert url.group(1).endswith("/trading_test")
    assert "POSTGRES_DB: trading_test" in block


def test_ci_lint_job() -> None:
    block = _jobs(_read("ci.yml"))["lint"]
    assert "uv lock --check" in block
    assert "uv run ruff check" in block
    assert "uv run ruff format --check" in block


def test_ci_types_job() -> None:
    assert "uv run mypy src" in _jobs(_read("ci.yml"))["types"]


def test_ci_docker_job() -> None:
    block = _jobs(_read("ci.yml"))["docker"]
    assert "cp .env.example .env" in block
    assert "docker compose config -q" in block
    assert "docker compose --profile paper --profile live --profile ops config -q" in block
    assert "shellcheck --version" in block
    assert "shellcheck -x deploy/*.sh" in block
    assert "docker compose --profile ops build" in block
    assert "uv run pytest -m docker" in block


def test_ci_needs_no_secrets_and_never_pushes() -> None:
    text = _read("ci.yml")
    assert "secrets." not in text
    for banned in ("docker login", "docker push", "docker compose push", "ssh "):
        assert banned not in text


# --------------------------------------------------------------------------------------
# All workflows: pins, runner, uv version, no suppression
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_WORKFLOWS)
def test_every_uses_is_sha_pinned_with_version_comment(name: str) -> None:
    text = _read(name)
    uses = USES_RE.findall(text)
    assert uses, f"{name}: no uses: lines found"
    pinned = PINNED_USES_RE.findall(text)
    assert len(pinned) == len(uses), (
        f"{name}: every `uses:` must be owner/repo@<40-hex> # vX.Y.Z "
        f"({len(pinned)} of {len(uses)} are)"
    )


@pytest.mark.parametrize("name", ALL_WORKFLOWS)
def test_every_runner_is_the_pinned_ubuntu(name: str) -> None:
    text = _read(name)
    runners = re.findall(r"^\s+runs-on:\s*(\S+)\s*$", text, re.MULTILINE)
    assert runners, f"{name}: no runs-on found"
    assert set(runners) == {RUNNER}, f"{name}: runners {runners}"
    assert "ubuntu-latest" not in text


@pytest.mark.parametrize("name", ALL_WORKFLOWS)
def test_setup_uv_takes_the_exact_version(name: str) -> None:
    text = _read(name)
    n_setup = len(re.findall(r"astral-sh/setup-uv@", text))
    assert (
        len(re.findall(rf'^\s+version: "{re.escape(UV_VERSION)}"\s*$', text, re.MULTILINE))
        == n_setup
    )
    assert "latest" not in text.lower().replace("ubuntu-latest", "")


@pytest.mark.parametrize("name", ALL_WORKFLOWS)
def test_no_workflow_suppresses_step_failure_key(name: str) -> None:
    assert SUPPRESSION_KEY not in _read(name)


@pytest.mark.parametrize("pattern", OR_TRUE_PATTERNS)
def test_ci_has_no_or_true_idiom(pattern: str) -> None:
    assert re.search(pattern, _read("ci.yml")) is None


def test_gate_workflows_keep_their_gate_scripts() -> None:
    """Only pins/runner change in registry-gate and research-gate (D-01)."""
    registry = _read("registry-gate.yml")
    assert "scripts/verify_decision_alignment.py all" in registry
    assert "verify_parameter_set" in registry
    research = _read("research-gate.yml")
    assert "Freeze check" in research
    assert "Registry-path tripwire passed." in research


def test_paper_freeze_cache_and_upload_logic_unchanged() -> None:
    text = _read("paper_freeze_check.yml")
    assert "actions/cache/restore@" in text
    assert "actions/cache/save@" in text
    assert "actions/upload-artifact@" in text
    assert "key: paper-freeze-state" in text
    assert "if-no-files-found: warn" in text
