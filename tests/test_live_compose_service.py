"""The live compose service holds visibly on a refused start (plan 24-35; D-01, D-03, O-2).

Marker: docker.
A `live` service with an EMPTY live env file has no `LIVE_RUNTIME_MODE`, so the live runtime refuses
its start. With `--hold-on-refusal` it must stay up and non-operational instead of crash-looping:
the container runs, the held marker is on the state volume, the probe (`--healthcheck`) exits
non-zero and names the refusal code, and Docker never restarted it. The project is isolated (own
name, own env files, own volumes) and is torn down with its volumes in a `finally`.

The test needs the image `trading-alert:dev` built from this checkout
(`docker compose build db-upgrade`). Nothing here holds a credential: the env file carries random
throwaway database values and the live env file is empty.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.docker_helpers import (
    APP_IMAGE,
    ComposeProject,
    compose_project,
    docker,
    require_image,
    unique_name,
    write_env_file,
)
from tests.infra_helpers import infra_skip

HOLD_TIMEOUT_S = 240
POLL_INTERVAL_S = 3
STATE_DIRECTORY = "/app/logs/live"
HELD_MARKER_PREFIX = "held-refusal-"


def _container_id(project: ComposeProject, env: dict[str, str]) -> str:
    proc = project.compose("ps", "-q", "live", profiles=("live",), env=env, check=False)
    return proc.stdout.strip()


def _wait_for_held_marker(project: ComposeProject, env: dict[str, str]) -> list[str]:
    """Poll the state directory until a held marker file appears; return the file names."""
    deadline = time.monotonic() + HOLD_TIMEOUT_S
    names: list[str] = []
    while time.monotonic() < deadline:
        proc = project.compose(
            "exec",
            "-T",
            "live",
            "ls",
            STATE_DIRECTORY,
            profiles=("live",),
            env=env,
            check=False,
            timeout=60,
        )
        if proc.returncode == 0:
            names = proc.stdout.split()
            if any(name.startswith(HELD_MARKER_PREFIX) for name in names):
                return names
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(f"no held marker appeared in {STATE_DIRECTORY} within {HOLD_TIMEOUT_S} s: {names}")


@pytest.mark.docker
def test_the_live_service_with_an_empty_env_file_holds_instead_of_crash_looping(
    tmp_path: Path,
) -> None:
    require_image(APP_IMAGE)
    probe = docker(
        "run",
        "--rm",
        "--entrypoint",
        "/app/.venv/bin/python",
        APP_IMAGE,
        "-m",
        "src.live.runtime",
        "--help",
        check=False,
        timeout=120,
    )
    if probe.returncode != 0:
        infra_skip(
            f"image {APP_IMAGE} does not carry src.live.runtime "
            "(rebuild it with: docker compose build db-upgrade)"
        )
    env_file = write_env_file(tmp_path / "project.env")
    live_env = tmp_path / "live.env"
    live_env.write_text("", encoding="utf-8", newline="\n")
    env = {"TRADING_LIVE_ENV_FILE": str(live_env)}
    with compose_project(unique_name("t2435"), env_file) as project:
        started = project.compose("up", "-d", "live", profiles=("live",), env=env, timeout=600)
        assert started.returncode == 0

        names = _wait_for_held_marker(project, env)
        assert any(name.startswith(HELD_MARKER_PREFIX) for name in names)

        # The probe is the compose healthcheck command: unhealthy, with the refusal named.
        health = project.compose(
            "exec",
            "-T",
            "live",
            "/app/.venv/bin/python",
            "-m",
            "src.live.runtime",
            "--healthcheck",
            profiles=("live",),
            env=env,
            check=False,
            timeout=120,
        )
        assert health.returncode != 0
        payload = json.loads(health.stdout.strip().splitlines()[-1])
        assert payload["healthy"] is False
        assert payload["held"] is True
        assert payload["held_refusal"], "the held marker must name the refusal code"
        assert payload["mode"] == "UNRESOLVED"
        assert payload["problem"]

        liveness = project.compose(
            "exec",
            "-T",
            "live",
            "/app/.venv/bin/python",
            "-m",
            "src.live.runtime",
            "--liveness",
            profiles=("live",),
            env=env,
            check=False,
            timeout=120,
        )
        assert liveness.returncode != 0

        # The container is still up and Docker never restarted it (no crash loop).
        container = _container_id(project, env)
        assert container
        inspected = json.loads(docker("inspect", container, timeout=60).stdout)[0]
        assert inspected["State"]["Running"] is True
        assert inspected["RestartCount"] == 0
        assert inspected["HostConfig"]["RestartPolicy"]["Name"] in ("no", "")
        assert inspected["HostConfig"]["PortBindings"] in ({}, None)

        # The refusal is visible in the container log: the code and the missing mode, no value.
        logs = project.compose("logs", "--no-log-prefix", "live", profiles=("live",), env=env)
        text = logs.stdout + logs.stderr
        assert "live runtime refused" in text
        assert "LIVE_RUNTIME_MODE" in text

        # Still holding a moment later (a crash loop would have changed the container).
        time.sleep(POLL_INTERVAL_S)
        again = json.loads(docker("inspect", container, timeout=60).stdout)[0]
        assert again["State"]["Running"] is True
        assert again["RestartCount"] == 0
        assert again["State"]["StartedAt"] == inspected["State"]["StartedAt"]
