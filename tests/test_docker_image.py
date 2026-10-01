"""Image behaviours only a daemon can prove (13.1-03). Marker ``docker``.

Locally these skip with a reason naming the daemon or the missing image; under
``TRADING_CI_STRICT=1`` (the CI ``docker`` job, after ``docker compose --profile ops build``)
a missing daemon or image is a failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.docker_helpers import (
    APP_IMAGE,
    OPS_IMAGE,
    POSTGRES_IMAGE,
    compose_project,
    docker,
    require_image,
    unique_name,
    write_env_file,
)
from tests.infra_helpers import infra_skip

HEALTH_PROBE = ["CMD", "/app/.venv/bin/python", "-m", "src.data.collector", "--healthcheck"]
MOUNT_POINTS = ("/app/data/raw", "/app/data/backup", "/app/logs")


@pytest.mark.docker
def test_fresh_named_volumes_are_writable_by_the_runtime_user() -> None:
    require_image(APP_IMAGE)
    volumes = [unique_name("t131-vol") for _ in MOUNT_POINTS]
    try:
        mounts: list[str] = []
        for volume, target in zip(volumes, MOUNT_POINTS, strict=True):
            mounts += ["-v", f"{volume}:{target}"]
        proc = docker(
            "run",
            "--rm",
            "--entrypoint",
            "sh",
            *mounts,
            APP_IMAGE,
            "-c",
            "id -u && touch /app/data/raw/x /app/data/backup/x /app/logs/x && echo writable",
        )
        assert proc.stdout.split() == ["10001", "writable"]
    finally:
        for volume in volumes:
            docker("volume", "rm", "-f", volume, check=False, timeout=60)


@pytest.mark.docker
def test_image_runs_as_the_fixed_uid_with_the_exec_form_venv_healthcheck() -> None:
    require_image(APP_IMAGE)
    config = json.loads(
        docker("image", "inspect", "--format", "{{json .Config}}", APP_IMAGE).stdout
    )
    assert config["User"] == "10001"
    assert config["Healthcheck"]["Test"] == HEALTH_PROBE
    assert config["Cmd"] == ["/app/.venv/bin/python", "-m", "src.data.collector"]
    # 6 minutes in nanoseconds: no watermark exists before the first tick (Pitfall 13).
    assert config["Healthcheck"]["StartPeriod"] == 6 * 60 * 10**9


@pytest.mark.docker
def test_ops_image_has_the_toolbox_at_the_pinned_versions() -> None:
    require_image(OPS_IMAGE)

    def run(command: str) -> str:
        proc = docker("run", "--rm", "--entrypoint", "sh", OPS_IMAGE, "-c", f"{command} 2>&1")
        return proc.stdout

    assert "pg_dump (PostgreSQL) 17." in run("pg_dump --version")
    assert "pg_restore (PostgreSQL) 17." in run("pg_restore --version")
    assert "rclone v1.75.1" in run("rclone version")
    assert "rsync" in run("rsync --version")
    assert "OpenSSH" in run("ssh -V")
    assert run("id -u").strip() == "10001"


@pytest.mark.docker
def test_db_upgrade_runs_against_a_real_postgres_and_the_probe_finds_the_venv(
    tmp_path: Path,
) -> None:
    require_image(APP_IMAGE)
    if docker("image", "inspect", POSTGRES_IMAGE, check=False, timeout=60).returncode != 0:
        pulled = docker("pull", "--quiet", POSTGRES_IMAGE, check=False, timeout=600)
        if pulled.returncode != 0:
            infra_skip(f"postgres image {POSTGRES_IMAGE} unavailable and could not be pulled")
    env_file = write_env_file(tmp_path / "env")
    with compose_project(unique_name("t131-up"), env_file) as project:
        project.compose("up", "-d", "--wait", "--no-build", "postgres", timeout=300)
        upgrade = project.compose("run", "--rm", "--no-deps", "db-upgrade", check=False)
        assert upgrade.returncode == 0, upgrade.stderr[-800:]

        # Fresh database: no watermark yet, so the probe must report unhealthy with its own
        # message, proving the interpreter and the venv packages are importable (F-705).
        probe = project.compose(
            "run",
            "--rm",
            "--no-deps",
            "collector",
            "/app/.venv/bin/python",
            "-m",
            "src.data.collector",
            "--healthcheck",
            check=False,
        )
        assert probe.returncode == 1, probe.stderr[-800:]
        assert "collector-health:" in probe.stderr
        assert "ModuleNotFoundError" not in probe.stderr
