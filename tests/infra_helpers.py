"""Shared helpers for tests that depend on external infrastructure (13.1-01).

Locally, a missing docker daemon or bash is a reason to SKIP a test. In CI it must never
be: ``TRADING_CI_STRICT=1`` turns every such skip into a failure, so a CI run cannot pass
vacuously by skipping the infrastructure-bound tests (threat T-13.1-03).

Stdlib and pytest only. Every subprocess call sets ``MSYS_NO_PATHCONV=1`` so Git-for-Windows
bash does not rewrite container paths such as ``/work`` into Windows paths.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import pytest

STRICT_ENV = "TRADING_CI_STRICT"

_WSL_LAUNCHER_PARTS = ("system32", "windowsapps")

_DOCKER_INFO_TIMEOUT_S = 20
_COMPOSE_VERSION_TIMEOUT_S = 20

# One probe per pytest session: `docker info` can take seconds when the daemon is down.
_docker_cache: tuple[bool, str] | None = None


def _strict() -> bool:
    return os.environ.get(STRICT_ENV) == "1"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    return env


def infra_skip(reason: str) -> NoReturn:
    """Skip the current test, or FAIL it when ``TRADING_CI_STRICT=1``."""
    if _strict():
        pytest.fail(
            f"{reason} ({STRICT_ENV}=1: missing infrastructure is a failure)",
            pytrace=False,
        )
    pytest.skip(reason)


def find_bash() -> str | None:
    """Locate a usable bash, or None.

    On Windows the ``bash.exe`` in System32 and the Store alias in
    ``Microsoft\\WindowsApps`` are WSL launchers, which cannot run the repo's shell
    scripts; both are rejected, and Git-for-Windows bash is preferred over any other.
    """
    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        candidate = program_files / "Git" / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("bash")
    if found and not (
        sys.platform == "win32" and any(p in found.lower() for p in _WSL_LAUNCHER_PARTS)
    ):
        return found
    return None


def _reset_docker_cache() -> None:
    global _docker_cache
    _docker_cache = None


def docker_daemon_reachable() -> tuple[bool, str]:
    """Return ``(reachable, detail)``; the probe result is cached for the session."""
    global _docker_cache
    if _docker_cache is not None:
        return _docker_cache
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=_DOCKER_INFO_TIMEOUT_S,
            check=False,
            env=_env(),
        )
    except FileNotFoundError:
        result = (False, "docker CLI not found on PATH")
    except subprocess.TimeoutExpired:
        result = (False, f"docker info timed out after {_DOCKER_INFO_TIMEOUT_S}s")
    except OSError as exc:
        result = (False, f"docker could not be started: {exc}")
    else:
        if proc.returncode == 0 and proc.stdout.strip():
            result = (True, proc.stdout.strip())
        else:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            result = (False, detail[0] if detail else f"docker info exited {proc.returncode}")
    _docker_cache = result
    return result


def compose_cli_available() -> tuple[bool, str]:
    """Return ``(available, detail)`` for the compose plugin; needs no daemon."""
    try:
        proc = subprocess.run(
            ["docker", "compose", "version", "--short"],
            capture_output=True,
            text=True,
            timeout=_COMPOSE_VERSION_TIMEOUT_S,
            check=False,
            env=_env(),
        )
    except FileNotFoundError:
        return (False, "docker CLI not found on PATH")
    except subprocess.TimeoutExpired:
        return (False, f"docker compose version timed out after {_COMPOSE_VERSION_TIMEOUT_S}s")
    except OSError as exc:
        return (False, f"docker could not be started: {exc}")
    if proc.returncode == 0 and proc.stdout.strip():
        return (True, proc.stdout.strip())
    detail = (proc.stderr or proc.stdout).strip().splitlines()
    return (False, detail[0] if detail else f"docker compose exited {proc.returncode}")


def require_tool(name: str) -> str:
    """Return the path of ``name`` on PATH, or ``infra_skip`` (fail in strict mode)."""
    found = shutil.which(name)
    if found is None:
        infra_skip(f"required tool not found on PATH: {name}")
    return found
