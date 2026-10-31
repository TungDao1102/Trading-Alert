"""Text-level checks of the Dockerfile (13.1-03).

No daemon is needed: the Dockerfile is read as text. The properties pinned here are the ones a
fresh VPS depends on: every base image pinned by tag plus digest (D-05), the venv interpreter in
HEALTHCHECK and CMD (D-06, F-705), fixed UID 10001 and pre-owned mount points (research finding
4), and no runtime ``uv run``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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


# --- ops target and build context (13.1-03 task 3) ------------------------------------------

DOCKERIGNORE = REPO_ROOT / ".dockerignore"
PGDG_FINGERPRINT = "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8"
RCLONE_IMAGE = (
    "rclone/rclone:1.75.1@sha256:45401ad7410db1d67ffdb58e19059ad20b0d8e0285a60e38bbec55cc1019c7a5"
)


def _ops_stage() -> list[str]:
    logical = _logical_lines()
    start = next(i for i, ln in enumerate(logical) if re.search(r"\bAS ops$", ln, re.IGNORECASE))
    return logical[start:]


def test_rclone_stage_is_pinned_and_declared_before_runtime() -> None:
    lines = _lines()
    rclone = next(i for i, ln in enumerate(lines) if ln.startswith(f"FROM {RCLONE_IMAGE} AS "))
    runtime = next(i for i, ln in enumerate(lines) if re.search(r"\bAS runtime$", ln))
    assert rclone < runtime
    assert lines[rclone].endswith(" AS rclonebin")


def test_ops_stage_extends_runtime_and_returns_to_the_unprivileged_user() -> None:
    stage = _ops_stage()
    assert stage[0] == "FROM runtime AS ops"
    users = [ln for ln in stage if ln.startswith("USER ")]
    assert users == ["USER root", "USER 10001"]
    # The ops stage ends unprivileged and must not redefine the runtime probe or command.
    assert not any(ln.startswith(("HEALTHCHECK", "CMD", "ENTRYPOINT")) for ln in stage)


def test_ops_stage_copies_rclone_and_installs_the_toolbox() -> None:
    stage = "\n".join(_ops_stage())
    assert "COPY --from=rclonebin /usr/local/bin/rclone /usr/local/bin/rclone" in stage
    for package in ("rsync", "openssh-client", "postgresql-client-17", "gnupg", "ca-certificates"):
        assert package in stage, package
    assert "apt-get install -y --no-install-recommends" in stage
    assert "rm -rf /var/lib/apt/lists/*" in stage


def test_ops_stage_verifies_the_pgdg_key_fingerprint_during_the_build() -> None:
    stage = "\n".join(_ops_stage())
    assert "https://www.postgresql.org/media/keys/ACCC4CF8.asc" in stage
    assert "gpg --show-keys --with-colons" in stage
    assert PGDG_FINGERPRINT in stage
    assert "signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc" in stage
    # The fingerprint comparison must come before the repository is added and apt is updated.
    assert stage.index(PGDG_FINGERPRINT) < stage.index("pgdg.list")


def test_ops_stage_documents_the_floating_client_exception() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "exception to D-05" in text


def test_universe_copy_still_occurs_exactly_once() -> None:
    copy_line = "COPY docs/research/universe ./docs/research/universe"
    assert _lines().count(copy_line) == 1
    assert not any(ln.startswith("RUN useradd") for ln in _ops_stage())


def test_dockerignore_keeps_secrets_and_state_out_of_the_build_context() -> None:
    entries = [
        ln.strip()
        for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    for required in (
        ".env",
        ".env.*",
        "!.env.example",
        ".git",
        ".venv",
        "data",
        "logs",
        "backup",
        ".planning",
        ".gsd",
        ".omo",
        ".codegraph",
        "__pycache__",
        # WR-12: unanchored patterns only match at the context root, so nested bytecode
        # (src/**/__pycache__) needs the ** forms.
        "**/__pycache__",
        "**/*.py[cod]",
        "**/.pytest_cache",
        "tests",
    ):
        assert required in entries, f"{required} missing from .dockerignore"
    # The negation must come after the pattern it excepts, or it has no effect.
    assert entries.index(".env.*") < entries.index("!.env.example")
    assert any(entry.endswith("_cache") or entry.endswith("cache") for entry in entries)


def test_dockerignore_does_not_exclude_what_the_image_copies() -> None:
    entries = {
        ln.strip()
        for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    for needed in ("src", "scripts", "alembic.ini", "pyproject.toml", "uv.lock", "docs"):
        assert needed not in entries, f"{needed} is COPY'd by the Dockerfile"


# --- 16-55 Task 1: every path the runtime reads at start is in the image (B2-CR-05) ----------

# What the runtime image must carry: the registry (`REGISTRY_ROOT`, /app/params), the ratified
# runtime configuration (`PAPER_RUNTIME_CONFIG`), the collect list, the migration config, the code.
RUNTIME_READ_PATHS: tuple[str, ...] = (
    "params",
    "config/paper",
    # R-6, C-8 (plan 24-25): the live process loads its limits from the image, so the image hash
    # covers them like the paper configuration.
    "config/execution",
    "config/binance",
    "docs/research/universe",
    "alembic.ini",
    "src",
    "scripts",
)


def _logical_lines_of(text: str) -> list[str]:
    """`_logical_lines` over any Dockerfile text (the negative control edits a copy)."""
    out: list[str] = []
    current = ""
    for raw in text.splitlines():
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


def runtime_copy_sources(dockerfile_text: str) -> list[str]:
    """The build-context sources of every COPY of the runtime stage (COPY --from excluded)."""
    sources: list[str] = []
    in_runtime = False
    for line in _logical_lines_of(dockerfile_text):
        if re.match(r"^FROM\s", line, flags=re.IGNORECASE):
            in_runtime = bool(re.search(r"\bAS\s+runtime$", line, flags=re.IGNORECASE))
            continue
        if not in_runtime or not line.startswith("COPY ") or line.startswith("COPY --from="):
            continue
        tokens = [t for t in line.split()[1:] if not t.startswith("--")]
        sources.extend(t.rstrip("/").removeprefix("./") for t in tokens[:-1])
    return sources


def _dockerignore_patterns(text: str) -> list[str]:
    return [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith("!")
    ]


def dockerignore_excluder(path: str, dockerignore_text: str) -> str | None:
    """The .dockerignore pattern that excludes `path` (or one of its parents), else None."""
    import fnmatch

    parts = path.split("/")
    candidates = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    for pattern in _dockerignore_patterns(dockerignore_text):
        bare = pattern.strip("/")
        for candidate in candidates:
            if fnmatch.fnmatchcase(candidate, bare):
                return pattern
            if bare.startswith("**/") and fnmatch.fnmatchcase(
                candidate.rsplit("/", 1)[-1], bare[3:]
            ):
                return pattern
    return None


def missing_runtime_paths(dockerfile_text: str, dockerignore_text: str) -> list[str]:
    """Every runtime read path that no runtime COPY carries, or that .dockerignore excludes."""
    sources = runtime_copy_sources(dockerfile_text)
    missing: list[str] = []
    for needed in RUNTIME_READ_PATHS:
        covered = any(needed == s or needed.startswith(s + "/") for s in sources)
        excluded = dockerignore_excluder(needed, dockerignore_text)
        if not covered:
            missing.append(f"{needed} (no COPY in the runtime stage)")
        elif excluded is not None:
            missing.append(f"{needed} (excluded by .dockerignore pattern {excluded})")
    return missing


def test_the_runtime_stage_copies_every_path_the_runtime_reads_at_start() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")
    assert missing_runtime_paths(dockerfile, dockerignore) == []
    assert "COPY params ./params" in _lines()
    assert "COPY config/paper ./config/paper" in _lines()
    assert "COPY config/execution ./config/execution" in _lines()
    assert "COPY config/binance ./config/binance" in _lines()


def test_the_path_check_names_params_when_its_copy_line_is_removed(tmp_path: Path) -> None:
    """Negative control: a copy of the Dockerfile without the params COPY line fails."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    edited = "\n".join(ln for ln in text.splitlines() if ln.strip() != "COPY params ./params")
    assert edited != "\n".join(text.splitlines()), "the params COPY line must exist to remove it"
    copy = tmp_path / "Dockerfile"
    copy.write_text(edited, encoding="utf-8")
    missing = missing_runtime_paths(
        copy.read_text(encoding="utf-8"), DOCKERIGNORE.read_text(encoding="utf-8")
    )
    assert missing == ["params (no COPY in the runtime stage)"]


def test_the_path_check_names_a_dockerignore_exclusion() -> None:
    """Negative control: a .dockerignore line that excludes config/ fails the check."""
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8") + "\nconfig\n"
    missing = missing_runtime_paths(DOCKERFILE.read_text(encoding="utf-8"), dockerignore)
    assert missing == [
        "config/paper (excluded by .dockerignore pattern config)",
        "config/execution (excluded by .dockerignore pattern config)",
        "config/binance (excluded by .dockerignore pattern config)",
    ]


# --- 16-55 Task 1: the in-image load check (scripts/check_image_paths.py) -------------------

RUNTIME_CONFIG = REPO_ROOT / "config" / "paper" / "paper-runtime-v2.toml"


def _check_module() -> Any:
    import importlib

    return importlib.import_module("scripts.check_image_paths")


def _config_values() -> list[str]:
    import tomllib

    raw = tomllib.loads(RUNTIME_CONFIG.read_text(encoding="utf-8"))
    values: list[str] = []
    for section in raw.values():
        for value in section.values():
            items = value if isinstance(value, list) else [value]
            values.extend(str(item) for item in items)
    return values


def test_image_check_passes_on_the_repository_and_prints_names_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    check = _check_module()
    code = check.main(
        ["--root", str(REPO_ROOT)], environ={"PAPER_RUNTIME_CONFIG": str(RUNTIME_CONFIG)}
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    lines = captured.out.splitlines()
    assert any("trend-pullback/research-run-1-a01" in ln for ln in lines), lines
    assert any(RUNTIME_CONFIG.as_posix() in ln for ln in lines), lines
    text = captured.out + captured.err
    for value in _config_values():
        assert f"= {value}" not in text and f"={value}" not in text, value
    assert "initial_equity" not in text and "risk_rate" not in text


def test_image_check_fails_naming_the_set_when_params_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    check = _check_module()
    root = tmp_path / "app"
    (root / "config" / "paper").mkdir(parents=True)
    config = root / "config" / "paper" / RUNTIME_CONFIG.name
    config.write_bytes(RUNTIME_CONFIG.read_bytes())
    code = check.main(["--root", str(root)], environ={"PAPER_RUNTIME_CONFIG": str(config)})
    captured = capsys.readouterr()
    assert code == 1
    assert "trend-pullback/research-run-1-a01" in captured.err


@pytest.mark.parametrize("value", [None, "", "/nonexistent/paper-runtime-v2.toml"])
def test_image_check_fails_naming_the_variable_when_the_config_is_absent(
    value: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    check = _check_module()
    environ = {} if value is None else {"PAPER_RUNTIME_CONFIG": value}
    code = check.main(["--root", str(REPO_ROOT)], environ=environ)
    captured = capsys.readouterr()
    assert code == 1
    assert "PAPER_RUNTIME_CONFIG" in captured.err


def test_image_check_with_an_empty_allowlist_exits_0_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.paper.freeze as freeze

    monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", ())
    check = _check_module()
    code = check.main(
        ["--root", str(REPO_ROOT)], environ={"PAPER_RUNTIME_CONFIG": str(RUNTIME_CONFIG)}
    )
    assert code == 0
    assert "nothing is allowlisted" in capsys.readouterr().out


def test_image_check_runs_as_a_module_from_the_root() -> None:
    """The image runs `python -m scripts.check_image_paths --root /app` with /app as cwd."""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not k.startswith("BINANCE_")}
    env["PAPER_RUNTIME_CONFIG"] = str(RUNTIME_CONFIG)
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.check_image_paths", "--root", str(REPO_ROOT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
