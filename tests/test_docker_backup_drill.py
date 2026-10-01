"""Backup, drill and restore onto an empty host with real containers (13.1-10). Marker ``docker``.

Two Compose projects are created from the repository's real ``docker-compose.yml`` (distinct
project names, volumes and PostgreSQL ports, one checkout) and an ``rclone serve s3`` container
plays the object store. The shell wrappers under test run exactly as an operator runs them, with
``COMPOSE_PROJECT_NAME`` and ``TRADING_ENV_FILE`` selecting the project:

* source project: schema plus deterministic Parquet ticks and watermark rows (the fake collector
  of plan 09, seed mode), then ``deploy/backup.sh --init-remote``, ``deploy/backup.sh`` and
  ``deploy/backup-drill.sh`` must each exit 0 (D-12, D-13);
* second, empty project with the same ``BACKUP_*`` values and its own PostgreSQL password:
  ``deploy/restore.sh --no-start`` must exit 0 and reproduce the source's Parquet fingerprint and
  watermark rows exactly (success criterion 6);
* a second ``deploy/restore.sh`` on the now non-empty project, without ``--force``, must be refused
  with a non-zero exit.

The S3 double runs on the default bridge and is connected to each project's network under its
container name, so the ops containers of both projects reach it by DNS. Locally the test skips
with a reason naming the docker daemon or the missing ``trading-alert:dev``,
``trading-alert-ops:dev`` or rclone image; under ``TRADING_CI_STRICT=1`` (the CI ``docker`` job,
after ``docker compose --profile ops build``) each of those is a failure. Nothing here prints an
env file; failure messages are scrubbed of the generated secrets.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.docker_helpers import (
    APP_IMAGE,
    OPS_IMAGE,
    RCLONE_IMAGE,
    ComposeProject,
    compose_project,
    docker,
    image_present,
    require_image,
    unique_name,
    write_env_file,
)
from tests.infra_helpers import STRICT_ENV, docker_daemon_reachable, find_bash, infra_skip

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "cutover"
OVERRIDE = FIXTURES / "compose.cutover.yml"
DEPLOY = REPO_ROOT / "deploy"

PY = "/app/.venv/bin/python"
S3_PORT = 9000
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SEED_START = "2026-09-01T10:00:00Z"
SEED_COUNT = 13
WRAPPER_TIMEOUT_S = 1200


@dataclass
class Run:
    """The outcome of one wrapper run (output already scrubbed of generated secrets)."""

    returncode: int
    output: str


@dataclass
class Outcome:
    init_remote: Run
    scheduled: Run
    drill: Run
    restore: Run
    second_restore: Run
    source_fingerprint: dict[str, str]
    restored_fingerprint: dict[str, str]
    source_watermarks: dict[str, str]
    restored_watermarks: dict[str, str]


def _scrub(text: str, secrets_: list[str]) -> str:
    for secret in secrets_:
        if secret:
            text = text.replace(secret, "***")
    return text


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    return values


def _require_rclone_image() -> None:
    if image_present(RCLONE_IMAGE):
        return
    if os.environ.get(STRICT_ENV) == "1":
        docker("pull", RCLONE_IMAGE, check=False, timeout=900)
        if image_present(RCLONE_IMAGE):
            return
    infra_skip(f"rclone image {RCLONE_IMAGE} not present on the docker daemon (docker pull it)")


def _compose(
    project: ComposeProject,
    *args: str,
    secrets_: list[str],
    profiles: tuple[str, ...] = ("ops",),
    timeout: float = 300,
) -> str:
    """Run a compose command; on failure raise with scrubbed output."""
    proc = project.compose(*args, profiles=profiles, check=False, timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError(
            f"compose {' '.join(args[:6])} failed ({proc.returncode}):\n"
            + _scrub(proc.stdout + proc.stderr, secrets_)
        )
    return proc.stdout


def _start_s3_double(access_key: str, secret_key: str) -> str:
    """Start ``rclone serve s3`` and return the container name (also its DNS name)."""
    server = unique_name("t131-s3")
    docker(
        "run",
        "-d",
        "--name",
        server,
        "--entrypoint",
        "sh",
        RCLONE_IMAGE,
        "-c",
        "mkdir -p /data && exec rclone serve s3 /data "
        f"--addr :{S3_PORT} --auth-key {access_key},{secret_key}",
    )
    # busybox nc answers once the listener is up; if the image lacks nc, give the server a moment
    # (the first wrapper call fails loudly when the store is not reachable).
    for _ in range(30):
        probe = docker("exec", server, "nc", "-z", "127.0.0.1", str(S3_PORT), check=False)
        if probe.returncode == 0:
            return server
        if probe.returncode in (126, 127):
            time.sleep(5)
            return server
        time.sleep(1)
    logs = docker("logs", server, check=False).stderr[-400:]
    raise AssertionError(f"rclone serve s3 did not become ready: {logs}")


def _obscure(passphrase: str) -> str:
    return docker("run", "--rm", RCLONE_IMAGE, "obscure", passphrase).stdout.strip()


def _wrapper(
    bash: str,
    script: str,
    *args: str,
    project: str,
    env_file: Path,
    secrets_: list[str],
) -> Run:
    env = dict(os.environ)
    env.update(
        {
            "MSYS_NO_PATHCONV": "1",
            "COMPOSE_PROJECT_NAME": project,
            "TRADING_ENV_FILE": env_file.as_posix(),
        }
    )
    proc = subprocess.run(
        [bash, (DEPLOY / script).as_posix(), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=WRAPPER_TIMEOUT_S,
    )
    return Run(proc.returncode, _scrub(proc.stdout + "\n" + proc.stderr, secrets_))


def _ops_json(project: ComposeProject, name: str, *cmd: str, secrets_: list[str]) -> dict[str, str]:
    """Run a cutover snapshot command in the project's ops service and return its JSON file."""
    path = f"/app/data/backup/{name}.json"
    _compose(
        project,
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "ops",
        PY,
        "-m",
        "src.ops.cutover",
        *cmd,
        "--out",
        path,
        secrets_=secrets_,
    )
    out = _compose(project, "run", "--rm", "-T", "--no-deps", "ops", "cat", path, secrets_=secrets_)
    loaded = json.loads(out)
    assert isinstance(loaded, dict)
    return {str(k): str(v) for k, v in loaded.items()}


def _connect(network: str, server: str) -> None:
    docker("network", "connect", network, server, timeout=120)


@pytest.fixture(scope="module")
def outcome(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Outcome]:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found; the drill test needs Git Bash or Linux bash")
    reachable, detail = docker_daemon_reachable()
    if not reachable:
        infra_skip(f"docker daemon not reachable: {detail}")
    require_image(APP_IMAGE)
    require_image(OPS_IMAGE)
    _require_rclone_image()

    work = tmp_path_factory.mktemp("drill")
    src_name, dst_name = unique_name("t131-src"), unique_name("t131-dst")
    access_key, secret_key = secrets.token_hex(10), secrets.token_hex(20)
    passphrase, salt = secrets.token_hex(12), secrets.token_hex(12)
    bucket = unique_name("bkt")

    with contextlib.ExitStack() as stack:
        server = _start_s3_double(access_key, secret_key)
        stack.callback(docker, "rm", "-f", server, check=False, timeout=120)
        docker("exec", server, "mkdir", "-p", f"/data/{bucket}")

        backup_env = {
            "BACKUP_S3_PROVIDER": "Other",
            "BACKUP_S3_ENDPOINT": f"http://{server}:{S3_PORT}",
            "BACKUP_S3_REGION": "us-east-1",
            "BACKUP_S3_BUCKET": bucket,
            "BACKUP_S3_ACCESS_KEY_ID": access_key,
            "BACKUP_S3_SECRET_ACCESS_KEY": secret_key,
            "BACKUP_CRYPT_PASSWORD": _obscure(passphrase),
            "BACKUP_CRYPT_PASSWORD2": _obscure(salt),
        }
        src_env_file = write_env_file(work / "src.env", **backup_env)
        dst_env_file = write_env_file(work / "dst.env", **backup_env)
        src_env, dst_env = _read_env(src_env_file), _read_env(dst_env_file)
        assert src_env["POSTGRES_PASSWORD"] != dst_env["POSTGRES_PASSWORD"]
        assert src_env["POSTGRES_PORT"] != dst_env["POSTGRES_PORT"]
        secrets_ = [
            src_env["POSTGRES_PASSWORD"],
            dst_env["POSTGRES_PASSWORD"],
            access_key,
            secret_key,
            passphrase,
            salt,
            backup_env["BACKUP_CRYPT_PASSWORD"],
            backup_env["BACKUP_CRYPT_PASSWORD2"],
        ]

        source = stack.enter_context(compose_project(src_name, src_env_file, [OVERRIDE]))
        target = stack.enter_context(compose_project(dst_name, dst_env_file, []))
        # Compose cannot remove a network that still has the S3 double attached.
        for network in (f"{src_name}_default", f"{dst_name}_default"):
            stack.callback(docker, "network", "disconnect", "-f", network, server, check=False)

        # Source: schema, then deterministic Parquet ticks and the matching watermark rows.
        _compose(
            source, "up", "-d", "--wait", "--wait-timeout", "180", "postgres", secrets_=secrets_
        )
        _compose(source, "run", "--rm", "-T", "db-upgrade", secrets_=secrets_)
        _compose(
            source,
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "ops",
            PY,
            "/fixture/fake_collector.py",
            "seed",
            "--symbols",
            *SYMBOLS,
            "--start",
            SEED_START,
            "--count",
            str(SEED_COUNT),
            secrets_=secrets_,
        )
        _connect(f"{src_name}_default", server)

        # Target host: only PostgreSQL exists before restore.sh runs (empty database, no Parquet).
        _compose(
            target, "up", "-d", "--wait", "--wait-timeout", "180", "postgres", secrets_=secrets_
        )
        _connect(f"{dst_name}_default", server)

        def wrapper(script: str, *args: str, name: str, env_file: Path) -> Run:
            return _wrapper(bash, script, *args, project=name, env_file=env_file, secrets_=secrets_)

        init_remote = wrapper("backup.sh", "--init-remote", name=src_name, env_file=src_env_file)
        scheduled = wrapper("backup.sh", name=src_name, env_file=src_env_file)
        drill = wrapper("backup-drill.sh", name=src_name, env_file=src_env_file)
        restore = wrapper("restore.sh", "--no-start", name=dst_name, env_file=dst_env_file)
        second = wrapper("restore.sh", "--no-start", name=dst_name, env_file=dst_env_file)

        source_fp = _ops_json(
            source, "t131-fp", "fingerprint", "--raw-root", "/app/data/raw", secrets_=secrets_
        )
        restored_fp = _ops_json(
            target, "t131-fp", "fingerprint", "--raw-root", "/app/data/raw", secrets_=secrets_
        )
        source_wm = _ops_json(source, "t131-wm", "watermarks", secrets_=secrets_)
        restored_wm = _ops_json(target, "t131-wm", "watermarks", secrets_=secrets_)

        yield Outcome(
            init_remote=init_remote,
            scheduled=scheduled,
            drill=drill,
            restore=restore,
            second_restore=second,
            source_fingerprint=source_fp,
            restored_fingerprint=restored_fp,
            source_watermarks=source_wm,
            restored_watermarks=restored_wm,
        )


def test_init_remote_scheduled_backup_and_drill_all_exit_zero(outcome: Outcome) -> None:
    assert outcome.init_remote.returncode == 0, outcome.init_remote.output
    assert outcome.scheduled.returncode == 0, outcome.scheduled.output
    assert outcome.drill.returncode == 0, outcome.drill.output


def test_restore_onto_an_empty_host_exits_zero(outcome: Outcome) -> None:
    assert outcome.restore.returncode == 0, outcome.restore.output


def test_restored_parquet_fingerprint_equals_the_source(outcome: Outcome) -> None:
    assert len(outcome.source_fingerprint) == SEED_COUNT * len(SYMBOLS), "seeding went wrong"
    assert outcome.restored_fingerprint == outcome.source_fingerprint


def test_restored_watermark_rows_equal_the_source(outcome: Outcome) -> None:
    assert set(outcome.source_watermarks) == {f"{symbol}|oi" for symbol in SYMBOLS}
    assert outcome.restored_watermarks == outcome.source_watermarks


def test_a_second_restore_onto_the_non_empty_host_is_refused(outcome: Outcome) -> None:
    assert outcome.second_restore.returncode != 0, outcome.second_restore.output
