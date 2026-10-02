"""Two-environment cutover proof: ``deploy/migrate.sh`` between two Compose projects (13.1-09).

Marker ``docker``. Two projects are created from the repository's real ``docker-compose.yml``
(distinct project names, volumes and PostgreSQL ports, one checkout) plus a test-only override
that replaces the collector with a deterministic fake (the real one would call Binance). A
key-only sshd+rsync sidecar built from ``tests/fixtures/cutover`` stands in for the OLD host: it
mounts the old project's named volumes read-only and sits on the NEW project's network, so the
migration script pulls over real ssh with strict host key checking (D-15, D-20, D-21).

Assertions are computed independently of ``src/ops/cutover.py`` (plain ``sha256sum`` over the
raw volumes, ``psql`` over the watermark tables) and then compared with what the script reports:

* every old Parquet path exists on the new side with the same sha256 (the only additions are the
  two new ticks),
* every old watermark row exists on the new side and has not regressed,
* the reported OI gap is the engineered 45 minutes and the script exits 0,
* the same report with ``--max-gap-minutes 30`` exits 3.

Locally the test skips with a reason naming the docker daemon, a missing ``trading-alert`` image
or the sidecar build; under ``TRADING_CI_STRICT=1`` (the CI ``docker`` job, after
``docker compose --profile ops build``) each of those is a failure.

User-defined networks are required here: Compose attaches every service to one and the sidecar
joins it by name. (On a Docker Desktop daemon where attaching containers to user-defined networks
hangs, as seen while building plan 08, this test cannot run; it is designed for the CI daemon.)
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.docker_helpers import (
    APP_IMAGE,
    COMPOSE_FILE,
    OPS_IMAGE,
    ComposeProject,
    compose_project,
    docker,
    require_image,
    unique_name,
    write_env_file,
)
from tests.infra_helpers import docker_daemon_reachable, find_bash, infra_skip

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "cutover"
OVERRIDE = FIXTURES / "compose.cutover.yml"
MIGRATE = REPO_ROOT / "deploy" / "migrate.sh"
SIDECAR_IMAGE = "t131-sshd:cutover"

SYMBOLS = ("BTCUSDT", "ETHUSDT")
SEED_START = "2026-09-01T10:00:00Z"
SEED_COUNT = 13  # ticks 10:00 .. 11:00
TICK_AT = "2026-09-01T11:45:00Z"  # first tick on the new host: a 45 minute hole after 11:00
WINDOW_END = "2026-09-01T11:46:00Z"
ENGINEERED_GAP_MINUTES = 45
CUT = "/app/data/backup/cutover"


@dataclass
class Outcome:
    migrate: subprocess.CompletedProcess[str]
    migrate_output: str
    old_files: dict[str, str]
    new_files: dict[str, str]
    old_watermarks: dict[str, int]
    new_watermarks: dict[str, int]
    report: dict[str, Any]
    strict_report: subprocess.CompletedProcess[str]


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


def _run(
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


def _volume_hashes(volume: str) -> dict[str, str]:
    """sha256 of every Parquet file in a raw volume, computed with plain coreutils."""
    script = "cd /data && find . -name '*.parquet' -print0 | sort -z | xargs -0 sha256sum"
    out = docker(
        "run",
        "--rm",
        "--entrypoint",
        "sh",
        "-v",
        f"{volume}:/data:ro",
        OPS_IMAGE,
        "-c",
        script,
    ).stdout
    hashes: dict[str, str] = {}
    for line in out.splitlines():
        digest, _, path = line.partition("  ")
        hashes[path.removeprefix("./")] = digest
    return hashes


def _watermarks(
    project: ComposeProject, env: dict[str, str], secrets_: list[str]
) -> dict[str, int]:
    sql = (
        "SELECT symbol, data_class, extract(epoch from last_tick_utc)::bigint "
        "FROM collector_watermarks ORDER BY 1, 2"
    )
    out = _run(
        project,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        env["POSTGRES_USER"],
        "-d",
        env["POSTGRES_DB"],
        "-At",
        "-F",
        "|",
        "-c",
        sql,
        secrets_=secrets_,
    )
    rows: dict[str, int] = {}
    for line in out.splitlines():
        symbol, data_class, epoch = line.split("|")
        rows[f"{symbol}|{data_class}"] = int(epoch)
    return rows


def _compose_prefix(name: str, env_file: Path) -> str:
    return (
        f"env TRADING_ENV_FILE={env_file.as_posix()} docker compose -p {name} "
        f"--env-file {env_file.as_posix()} -f {COMPOSE_FILE.as_posix()} "
        f"-f {OVERRIDE.as_posix()} --profile ops"
    )


def _build_sidecar_image() -> None:
    proc = docker(
        "build",
        "-t",
        SIDECAR_IMAGE,
        "-f",
        str(FIXTURES / "Dockerfile.sshd"),
        str(FIXTURES),
        check=False,
        timeout=900,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])
        infra_skip(f"sidecar image build failed ({SIDECAR_IMAGE}):\n{tail}")


def _wait_for_sshd(network: str, sidecar: str, keys: str) -> None:
    """Scan the sidecar's host key into the key volume's known_hosts (also proves sshd is up)."""
    script = (
        f"ssh-keyscan -t ed25519 {sidecar} > /keys/known_hosts 2>/dev/null; "
        "test -s /keys/known_hosts"
    )
    for _ in range(40):
        proc = docker(
            "run",
            "--rm",
            "--user",
            "0:0",
            "--network",
            network,
            "-v",
            f"{keys}:/keys",
            "--entrypoint",
            "sh",
            OPS_IMAGE,
            "-c",
            script,
            check=False,
            timeout=60,
        )
        if proc.returncode == 0:
            return
        time.sleep(1)
    logs = docker("logs", sidecar, check=False).stderr[-1500:]
    raise AssertionError(f"sshd in {sidecar} never answered ssh-keyscan:\n{logs}")


@pytest.fixture(scope="module")
def outcome(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Outcome]:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found; the cutover test needs Git Bash or Linux bash")
    reachable, detail = docker_daemon_reachable()
    if not reachable:
        infra_skip(f"docker daemon not reachable: {detail}")
    require_image(APP_IMAGE)
    require_image(OPS_IMAGE)
    _build_sidecar_image()

    work = tmp_path_factory.mktemp("cutover")
    old_name, new_name = unique_name("t131-old"), unique_name("t131-new")
    keys, sidecar = unique_name("t131-keys"), unique_name("t131-sidecar")
    old_env_file = write_env_file(work / "old.env")
    new_env_file = write_env_file(work / "new.env")
    old_env, new_env = _read_env(old_env_file), _read_env(new_env_file)
    assert old_env["POSTGRES_PORT"] != new_env["POSTGRES_PORT"]
    secrets_ = [old_env["POSTGRES_PASSWORD"], new_env["POSTGRES_PASSWORD"]]
    new_network = f"{new_name}_default"

    with contextlib.ExitStack() as stack:
        old = stack.enter_context(compose_project(old_name, old_env_file, [OVERRIDE]))
        new = stack.enter_context(compose_project(new_name, new_env_file, [OVERRIDE]))
        stack.callback(docker, "volume", "rm", "-f", keys, check=False, timeout=60)
        stack.callback(docker, "rm", "-f", sidecar, check=False, timeout=120)

        # Old side: schema, then 13 deterministic ticks per symbol. Its collector never runs.
        _run(old, "run", "--rm", "-T", "db-upgrade", secrets_=secrets_)
        _run(
            old,
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "ops",
            "/app/.venv/bin/python",
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
        # New side: only PostgreSQL (restore-db needs an empty database).
        _run(new, "up", "-d", "--wait", "--wait-timeout", "180", "postgres", secrets_=secrets_)

        # Dedicated ssh key and known_hosts in a throwaway volume, never in an image.
        docker("volume", "create", keys)
        docker(
            "run",
            "--rm",
            "--user",
            "0:0",
            "-v",
            f"{keys}:/keys",
            "--entrypoint",
            "sh",
            OPS_IMAGE,
            "-c",
            "ssh-keygen -q -t ed25519 -N '' -f /keys/id_ed25519 && chmod 600 /keys/id_ed25519 "
            "&& chmod 644 /keys/id_ed25519.pub",
        )
        docker(
            "run",
            "-d",
            "--name",
            sidecar,
            "--network",
            new_network,
            "-v",
            f"{old_name}_rawdata:/data/raw:ro",
            "-v",
            f"{old_name}_backupdata:/data/backup:ro",
            "-v",
            f"{keys}:/keys:ro",
            SIDECAR_IMAGE,
        )
        _wait_for_sshd(new_network, sidecar, keys)

        old_files = _volume_hashes(f"{old_name}_rawdata")
        old_watermarks = _watermarks(old, old_env, secrets_)

        env = dict(os.environ)
        env.update(
            {
                "MSYS_NO_PATHCONV": "1",
                "MIGRATE_OLD_COMPOSE": _compose_prefix(old_name, old_env_file),
                "MIGRATE_NEW_COMPOSE": _compose_prefix(new_name, new_env_file),
                "MIGRATE_RSYNC_SOURCE": f"rsync@{sidecar}",
                "MIGRATE_RSYNC_PATH": "rsync",
                "MIGRATE_REPORT_WINDOW_END": WINDOW_END,
                "MIGRATE_POLL_SECONDS": "2",
                "FAKE_TICK_AT": TICK_AT,
            }
        )
        common = ["--key-source", keys]
        migrate = subprocess.run(
            [bash, MIGRATE.as_posix(), *common, "--wait-seconds", "180", "old.invalid", "local"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=1500,
        )
        migrate_output = _scrub(migrate.stdout + "\n" + migrate.stderr, secrets_)

        # Every migrate.sh run rewrites report.json, including the strict --report-only run
        # below, so the real run's report must be read before that one starts.
        report: dict[str, Any] = {}
        if migrate.returncode == 0:
            report_args = ("run", "--rm", "-T", "--no-deps", "ops", "cat", f"{CUT}/report.json")
            report = json.loads(_run(new, *report_args, secrets_=secrets_))

        strict = subprocess.run(
            [
                bash,
                MIGRATE.as_posix(),
                "--report-only",
                "--max-gap-minutes",
                "30",
                *common,
                "old.invalid",
                "local",
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=600,
        )

        new_files: dict[str, str] = {}
        new_watermarks: dict[str, int] = {}
        if migrate.returncode == 0:
            new_files = _volume_hashes(f"{new_name}_rawdata")
            new_watermarks = _watermarks(new, new_env, secrets_)
        yield Outcome(
            migrate=migrate,
            migrate_output=migrate_output,
            old_files=old_files,
            new_files=new_files,
            old_watermarks=old_watermarks,
            new_watermarks=new_watermarks,
            report=report,
            strict_report=strict,
        )


def test_migrate_script_exits_zero_and_leaves_the_old_host_running(outcome: Outcome) -> None:
    assert outcome.migrate.returncode == 0, outcome.migrate_output
    assert "NOT been shut down" in outcome.migrate_output
    for number in range(1, 11):
        assert f"== step {number}/10" in outcome.migrate_output


def test_every_old_parquet_file_is_on_the_new_side_with_the_same_sha256(outcome: Outcome) -> None:
    assert len(outcome.old_files) == SEED_COUNT * len(SYMBOLS), "seeding went wrong"
    lost = sorted(set(outcome.old_files) - set(outcome.new_files))
    changed = sorted(
        path
        for path, digest in outcome.old_files.items()
        if path in outcome.new_files and outcome.new_files[path] != digest
    )
    assert not lost and not changed, f"lost={lost} changed={changed}\n{outcome.migrate_output}"
    added = sorted(set(outcome.new_files) - set(outcome.old_files))
    assert len(added) == len(SYMBOLS), added
    assert all("tick-20260901T114500Z.parquet" in path for path in added), added


def test_every_old_watermark_row_survives_and_none_regressed(outcome: Outcome) -> None:
    assert set(outcome.old_watermarks) == {f"{s}|oi" for s in SYMBOLS}
    for key, old_epoch in outcome.old_watermarks.items():
        assert key in outcome.new_watermarks, f"watermark row lost: {key}"
        assert outcome.new_watermarks[key] >= old_epoch, f"watermark regressed: {key}"
    # The new collector resumed from the restored watermark and advanced it.
    assert all(
        outcome.new_watermarks[key] > outcome.old_watermarks[key] for key in outcome.old_watermarks
    )


def test_the_reported_oi_gap_is_the_engineered_forty_five_minutes(outcome: Outcome) -> None:
    assert outcome.report["exit_code"] == 0
    gaps = outcome.report["oi_gaps"]
    assert isinstance(gaps, list)
    by_symbol = {g["symbol"]: g["max_gap_minutes"] for g in gaps}
    assert by_symbol == {s: ENGINEERED_GAP_MINUTES for s in SYMBOLS}
    assert outcome.report["files"]["missing"] == []
    assert outcome.report["watermarks"]["lost"] == []


def test_the_same_report_with_a_thirty_minute_threshold_exits_three(outcome: Outcome) -> None:
    out = outcome.strict_report.stdout + outcome.strict_report.stderr
    assert outcome.strict_report.returncode == 3, out
    assert "NOT been shut down" in out
