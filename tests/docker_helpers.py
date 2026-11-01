"""Shared helpers for the docker-marked tests (13.1-03).

Everything here shells out to the ``docker`` CLI. Locally a missing image is a reason to SKIP;
under ``TRADING_CI_STRICT=1`` (CI) it is a failure (``infra_skip``). The helpers never echo
environment values: credentials reach containers through an env file or the process
environment, never through argv, and the wrapper returns output only.

The images ``trading-alert:dev`` and ``trading-alert-ops:dev`` are produced by
``docker compose --profile ops build`` (the CI ``docker`` job runs that before these tests).
"""

from __future__ import annotations

import contextlib
import os
import secrets
import socket
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests.infra_helpers import infra_skip

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

APP_IMAGE = "trading-alert:dev"
OPS_IMAGE = "trading-alert-ops:dev"

# Pinned references; kept equal to the Dockerfile and docker-compose.yml (tests/test_deploy_*
# assert those files, the CI docker job exercises these).
POSTGRES_IMAGE = (
    "postgres:17.11-bookworm@sha256:"
    "639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652"
)
RCLONE_IMAGE = (
    "rclone/rclone:1.75.1@sha256:45401ad7410db1d67ffdb58e19059ad20b0d8e0285a60e38bbec55cc1019c7a5"
)

DEFAULT_TIMEOUT_S = 300


def _env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    # Git Bash on Windows would otherwise rewrite container paths such as /app/data.
    env["MSYS_NO_PATHCONV"] = "1"
    env.update(extra or {})
    return env


def docker(
    *args: str,
    check: bool = True,
    timeout: float = DEFAULT_TIMEOUT_S,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``docker <args>`` with text output. Never prints the environment."""
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
        env=_env(env),
    )


def image_present(tag: str) -> bool:
    return docker("image", "inspect", tag, check=False, timeout=60).returncode == 0


def require_image(tag: str) -> None:
    """Skip (fail in strict mode) when the image is not available on the daemon."""
    if not image_present(tag):
        infra_skip(
            f"image {tag} not found on the docker daemon "
            "(build it with: docker compose --profile ops build)"
        )


def unique_name(prefix: str) -> str:
    """A collision-free lowercase name for projects, volumes and containers."""
    return f"{prefix}-{secrets.token_hex(4)}"


def free_port() -> int:
    """An unused loopback TCP port (best effort; a race is possible but unlikely)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def write_env_file(path: Path, **values: str) -> Path:
    """Write a throwaway env file with random credentials; ``values`` override defaults."""
    merged = {
        "POSTGRES_USER": "u" + secrets.token_hex(4),
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "POSTGRES_DB": "tradingtest",
        "POSTGRES_PORT": str(free_port()),
    }
    merged.update(values)
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in merged.items()),
        encoding="utf-8",
        newline="\n",
    )
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return path


@dataclass
class ComposeProject:
    """A throwaway compose project over the repo's docker-compose.yml."""

    name: str
    env_file: Path
    extra_files: Sequence[Path] = field(default_factory=tuple)

    def compose(
        self,
        *args: str,
        profiles: Sequence[str] = (),
        check: bool = True,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [
            "compose",
            "-p",
            self.name,
            "--env-file",
            str(self.env_file),
            "-f",
            str(COMPOSE_FILE),
        ]
        for extra in self.extra_files:
            cmd += ["-f", str(extra)]
        for profile in profiles:
            cmd += ["--profile", profile]
        cmd += list(args)
        return docker(
            *cmd,
            check=check,
            timeout=timeout,
            # One file per throwaway project (plan 24-36, D-29): the paper and backup env files
            # of the compose file are the project file too, as deploy/lib.sh compose_init does.
            env={
                "TRADING_ENV_FILE": str(self.env_file),
                "TRADING_PAPER_ENV_FILE": str(self.env_file),
                "TRADING_BACKUP_ENV_FILE": str(self.env_file),
            },
        )


@contextlib.contextmanager
def compose_project(
    name: str,
    env_file: Path,
    extra_files: Sequence[Path] = (),
) -> Iterator[ComposeProject]:
    """Yield a project and ALWAYS tear it down with volumes on exit."""
    project = ComposeProject(name=name, env_file=env_file, extra_files=tuple(extra_files))
    try:
        yield project
    finally:
        project.compose(
            "--profile",
            "ops",
            "--profile",
            "paper",
            "--profile",
            "live",
            "down",
            "-v",
            "--remove-orphans",
            check=False,
            timeout=180,
        )
