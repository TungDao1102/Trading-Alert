"""Text-level checks of the Dockerfile (13.1-03).

No daemon is needed: the Dockerfile is read as text. The properties pinned here are the ones a
fresh VPS depends on: every base image pinned by tag plus digest (D-05), the venv interpreter in
HEALTHCHECK and CMD (D-06, F-705), fixed UID 10001 and pre-owned mount points (research finding
4), and no runtime ``uv run``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"

VENV_PYTHON = "/app/.venv/bin/python"
PINNED_IMAGE = re.compile(r"^[a-z0-9][a-z0-9./_-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")


def _lines() -> list[str]:
    return DOCKERFILE.read_text(encoding="utf-8").splitlines()


def _logical_lines() -> list[str]:
    """Dockerfile instructions with backslash continuations joined; comments dropped."""
    out: list[str] = []
    current = ""
    for raw in _lines():
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


def _stage_names() -> list[str]:
    names: list[str] = []
    for line in _logical_lines():
        m = re.match(r"^FROM\s+\S+\s+AS\s+(\S+)$", line, flags=re.IGNORECASE)
        if m:
            names.append(m.group(1))
    return names


def test_no_syntax_directive() -> None:
    # A `# syntax=` directive pulls an unpinned frontend image (T-13.1-09).
    assert not any(ln.lower().lstrip().startswith("# syntax") for ln in _lines())


def test_every_from_is_a_prior_stage_or_pinned_by_digest() -> None:
    seen: list[str] = []
    froms = 0
    for line in _logical_lines():
        m = re.match(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?$", line, flags=re.IGNORECASE)
        if not m:
            continue
        froms += 1
        image, stage = m.group(1), m.group(2)
        assert image in seen or PINNED_IMAGE.match(image), f"FROM not pinned by digest: {line}"
        if stage:
            seen.append(stage)
    assert froms >= 2


def test_copy_from_names_a_stage_and_never_an_image() -> None:
    stages = set(_stage_names())
    copies = [ln for ln in _logical_lines() if re.match(r"^COPY\s+--from=", ln)]
    assert copies, "expected at least the uv binary COPY --from"
    for line in copies:
        source = re.match(r"^COPY\s+--from=(\S+)", line)
        assert source is not None
        assert source.group(1) in stages, f"COPY --from must name a stage: {line}"


@pytest.mark.parametrize(
    "image",
    [
        "python:3.13.15-slim-bookworm@sha256:"
        "2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26",
        "ghcr.io/astral-sh/uv:0.12.21@sha256:"
        "a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711",
    ],
)
def test_runtime_bases_use_the_verified_pins(image: str) -> None:
    assert any(ln.startswith(f"FROM {image}") for ln in _lines())


def test_dependencies_install_only_from_the_lockfile() -> None:
    logical = _logical_lines()
    assert "RUN uv sync --frozen --no-dev" in logical
    assert not any(ln.startswith("RUN") and "pip install" in ln for ln in logical)


def test_no_runtime_uv_run_and_no_path_python() -> None:
    for line in _logical_lines():
        if line.startswith(("CMD", "ENTRYPOINT", "HEALTHCHECK")):
            assert '"uv"' not in line, line
            assert "uv run" not in line, line


def test_healthcheck_is_exec_form_with_the_venv_interpreter() -> None:
    health = [ln for ln in _logical_lines() if ln.startswith("HEALTHCHECK")]
    assert len(health) == 1
    line = health[0]
    assert 'CMD ["/app/.venv/bin/python", "-m", "src.data.collector", "--healthcheck"]' in line, (
        line
    )
    assert "|| exit" not in line
    assert "--start-period=6m" in line
    assert "--interval=60s" in line
    assert "--timeout=15s" in line
    assert "--retries=3" in line


def test_cmd_is_exec_form_with_the_venv_interpreter() -> None:
    cmds = [ln for ln in _logical_lines() if ln.startswith("CMD")]
    assert cmds == [f'CMD ["{VENV_PYTHON}", "-m", "src.data.collector"]']


def test_uv_environment_is_pinned_to_the_app_venv() -> None:
    text = "\n".join(_logical_lines())
    assert "UV_PROJECT_ENVIRONMENT=/app/.venv" in text
    assert "UV_PYTHON_DOWNLOADS=never" in text


def test_useradd_creates_fixed_uid_and_owned_mount_points() -> None:
    useradd = [ln for ln in _logical_lines() if ln.startswith("RUN useradd --uid 10001")]
    assert len(useradd) == 1
    line = useradd[0]
    assert "--create-home appuser" in line
    for mount in ("/app/data/raw", "/app/data/backup", "/app/logs"):
        assert mount in line, f"{mount} must be created in the same RUN as useradd"
    assert "chown" in line and "10001:10001" in line and "/app" in line


def test_runtime_user_is_the_fixed_uid() -> None:
    users = [ln for ln in _logical_lines() if ln.startswith("USER ")]
    assert users, "expected a USER instruction"
    assert users[-1] == "USER 10001" or users[0] == "USER 10001"
    # The runtime stage must drop root before its HEALTHCHECK / CMD.
    logical = _logical_lines()
    runtime_start = next(i for i, ln in enumerate(logical) if re.search(r"\bAS runtime$", ln))
    tail = logical[runtime_start:]
    assert "USER 10001" in tail
    assert tail.index("USER 10001") < next(i for i, ln in enumerate(tail) if ln.startswith("CMD"))
