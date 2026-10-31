"""The image says which code it runs, and carries the live limits (plan 24-25, R-6, OPS-04, D-31).

Static checks read the Dockerfile and `.dockerignore` as text. The docker-marked checks build the
runtime stage with a build argument and run `python -m src.live.runtime --healthcheck` inside it,
where there is no `.git` and no git executable to ask.

The build argument is `TRADING_APP_REVISION` (40 lowercase hex). It is set from the checked-out
commit by `deploy/update.sh` and `deploy/soak-image.sh` and passed by `docker-compose.yml`
(`build.args`). It carries no secret and has no literal default.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.docker_helpers import docker
from tests.infra_helpers import infra_skip

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

REVISION_VARIABLE = "TRADING_APP_REVISION"
STAMP = "0123456789abcdef0123456789abcdef01234567"
VENV_PYTHON = "/app/.venv/bin/python"
BUILD_TIMEOUT_S = 1500


def _logical_lines() -> list[str]:
    """Dockerfile instructions with backslash continuations joined; comments dropped."""
    out: list[str] = []
    current = ""
    for raw in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not current and (not stripped or stripped.startswith("#")):
            continue
        if stripped.endswith("\\"):
            current += stripped[:-1].rstrip() + " "
            continue
        out.append((current + stripped).strip())
        current = ""
    if current:
        out.append(current.strip())
    return out


def _runtime_stage() -> list[str]:
    lines = _logical_lines()
    start = next(i for i, ln in enumerate(lines) if re.search(r"\bAS runtime$", ln, re.IGNORECASE))
    stop = next(
        (i for i, ln in enumerate(lines) if i > start and ln.upper().startswith("FROM ")),
        len(lines),
    )
    return lines[start:stop]


# --- static checks -----------------------------------------------------------------------------


def test_the_runtime_stage_declares_the_revision_argument_without_a_default() -> None:
    stage = _runtime_stage()
    assert f"ARG {REVISION_VARIABLE}" in stage, "ARG must be declared bare: no literal revision"
    assert f"ENV {REVISION_VARIABLE}=${{{REVISION_VARIABLE}}}" in stage
    # The stamp is never a literal 40-hex value anywhere in the Dockerfile.
    assert re.search(r"\b[0-9a-f]{40}\b", DOCKERFILE.read_text(encoding="utf-8")) is None


def test_the_revision_argument_follows_the_dependency_install() -> None:
    """The stamp changes on every commit, so it must not invalidate the `uv sync` layer."""
    stage = _runtime_stage()
    arg = stage.index(f"ARG {REVISION_VARIABLE}")
    sync = next(i for i, ln in enumerate(stage) if ln.startswith("RUN uv sync"))
    assert sync < arg
    user = stage.index("USER 10001")
    assert arg < user


def test_no_secret_is_passed_as_a_build_argument() -> None:
    args = [ln for ln in _logical_lines() if ln.upper().startswith("ARG ")]
    assert args == [f"ARG {REVISION_VARIABLE}"]


def test_the_runtime_stage_copies_the_limits_directories() -> None:
    stage = _runtime_stage()
    assert "COPY config/execution ./config/execution" in stage
    assert "COPY config/binance ./config/binance" in stage


def test_dockerignore_keeps_git_and_env_files_out_of_the_image() -> None:
    """C-9 premise: the stamp exists because the image has no `.git`; secrets stay out (OPS-02)."""
    entries = {
        ln.strip()
        for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    assert ".git" in entries
    assert ".env" in entries
    assert ".env.*" in entries


# --- docker-marked checks ----------------------------------------------------------------------


def _build(tag: str, *build_args: str) -> None:
    proc = docker(
        "build",
        "--target",
        "runtime",
        *build_args,
        "-t",
        tag,
        str(REPO_ROOT),
        check=False,
        timeout=BUILD_TIMEOUT_S,
    )
    if proc.returncode != 0:
        infra_skip(f"image build failed: {proc.stderr.strip()[-300:]}")


def _run(tag: str, *command: str) -> subprocess.CompletedProcess[str]:
    return docker("run", "--rm", "--network", "none", tag, *command, check=False, timeout=120)


@pytest.fixture(scope="module")
def stamped_image() -> Iterator[str]:
    tag = f"trading-alert-stamp-test:{secrets.token_hex(4)}"
    _build(tag, "--build-arg", f"{REVISION_VARIABLE}={STAMP}")
    try:
        yield tag
    finally:
        docker("image", "rm", "-f", tag, check=False, timeout=120)


@pytest.fixture(scope="module")
def unstamped_image() -> Iterator[str]:
    tag = f"trading-alert-nostamp-test:{secrets.token_hex(4)}"
    _build(tag)
    try:
        yield tag
    finally:
        docker("image", "rm", "-f", tag, check=False, timeout=120)


def _healthcheck_payload(tag: str) -> dict[str, object]:
    proc = _run(tag, VENV_PYTHON, "-m", "src.live.runtime", "--healthcheck")
    # Exit 1 is expected (the process is not running); the answer is the JSON line on stdout.
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert isinstance(payload, dict)
    return payload


@pytest.mark.docker
def test_the_stamped_image_answers_healthcheck_with_its_revision(stamped_image: str) -> None:
    payload = _healthcheck_payload(stamped_image)
    assert payload["app_revision"] == STAMP
    assert "app_revision_problem" not in payload
    assert str(payload["python_version"]).startswith("3.13")


@pytest.mark.docker
def test_the_stamped_image_carries_the_limits_files(stamped_image: str) -> None:
    for path in (
        "/app/config/execution/execution-limits-v1.toml",
        "/app/config/binance/binance-limits-v1.toml",
    ):
        proc = _run(stamped_image, "test", "-s", path)
        assert proc.returncode == 0, f"{path} is missing from the image"


@pytest.mark.docker
def test_the_image_has_neither_git_history_nor_env_files(stamped_image: str) -> None:
    proc = _run(stamped_image, "sh", "-c", "ls -A /app")
    assert proc.returncode == 0
    names = set(proc.stdout.split())
    assert ".git" not in names
    assert ".env" not in names


@pytest.mark.docker
def test_an_unstamped_image_prints_unknown_and_still_answers(unstamped_image: str) -> None:
    payload = _healthcheck_payload(unstamped_image)
    assert payload["app_revision"] == "unknown"
    assert str(payload["python_version"]).startswith("3.13")
