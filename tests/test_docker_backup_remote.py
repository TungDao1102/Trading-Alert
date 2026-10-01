"""Real rclone 1.75.1 against an ``rclone serve s3`` double (13.1-08). Marker ``docker``.

MinIO no longer publishes images (research finding 1), so the pinned rclone image plays both
roles: the S3 server (``rclone serve s3``) and the client the adapter drives. The adapter's argv
runs through a docker-run runner; credentials reach the client container through the process
environment (``docker run -e NAME``), never through argv.

The containers share the default bridge and the client dials the server by container IP. A
user-defined network would be the textbook choice, but on the maintainer's Docker Desktop daemon
attaching a container to a user-defined network hangs forever (the container stays in "Created"
and cannot be removed), so the test avoids that feature; the default bridge works everywhere.

Locally a missing daemon or image skips with a reason naming it; under ``TRADING_CI_STRICT=1``
the image is pulled on demand and a missing daemon or image is a failure.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from src.ops import backup as backup_mod
from src.ops import backup_remote as remote
from src.ops.backup import main
from src.ops.backup_remote import RcloneResult, RemoteError

from tests.docker_helpers import RCLONE_IMAGE, docker, image_present, unique_name
from tests.infra_helpers import STRICT_ENV, infra_skip

pytestmark = pytest.mark.docker

S3_PORT = 9000
CRYPT = "BACKUPS3CRYPT:"
STARTUP_TRIES = 40


def _require_rclone_image() -> None:
    if image_present(RCLONE_IMAGE):
        return
    if os.environ.get(STRICT_ENV) == "1":
        docker("pull", RCLONE_IMAGE, check=False, timeout=900)
        if image_present(RCLONE_IMAGE):
            return
    infra_skip(f"rclone image {RCLONE_IMAGE} not present on the docker daemon (docker pull it)")


# --------------------------------------------------------------------------- #
# The S3 double and the docker-run rclone runner
# --------------------------------------------------------------------------- #


def _host_dirs_to_mount(argv: Sequence[str]) -> list[Path]:
    """Existing host directories that the argv's absolute local paths live under."""
    candidates: list[Path] = []
    previous = ""
    for arg in argv:
        is_filter_value = previous in {"--include", "--exclude"}
        previous = arg
        if is_filter_value or not os.path.isabs(arg):
            continue
        path = Path(arg)
        while not path.exists() and path.parent != path:
            path = path.parent
        candidates.append(path if path.is_dir() else path.parent)
    unique = sorted(set(candidates), key=lambda p: len(p.parts))
    chosen: list[Path] = []
    for directory in unique:
        if not any(directory.is_relative_to(existing) for existing in chosen):
            chosen.append(directory)
    return chosen


@dataclass
class DockerRclone:
    """An ``RcloneRunner`` that runs each call in the pinned rclone image."""

    env: Mapping[str, str]

    def __call__(self, argv: Sequence[str], extra: Mapping[str, str]) -> RcloneResult:
        mounts = _host_dirs_to_mount(argv)
        targets = {directory: f"/mnt/m{i}" for i, directory in enumerate(mounts)}
        translated: list[str] = []
        previous = ""
        for arg in argv:
            out = arg
            if previous not in {"--include", "--exclude"} and os.path.isabs(arg):
                path = Path(arg)
                for directory, target in targets.items():
                    if path == directory or path.is_relative_to(directory):
                        rel = path.relative_to(directory).as_posix()
                        out = target if rel == "." else f"{target}/{rel}"
                        break
            translated.append(out)
            previous = arg
        merged = {**self.env, **extra}
        cmd = ["run", "--rm"]
        for name in merged:
            cmd += ["-e", name]  # value comes from the docker CLI's environment, not argv
        for directory, target in targets.items():
            cmd += ["--mount", f"type=bind,source={directory},target={target}"]
        cmd += [RCLONE_IMAGE, *translated]
        proc = docker(*cmd, check=False, env=merged, timeout=300)
        return RcloneResult(proc.returncode, proc.stdout, proc.stderr)


@dataclass
class S3Double:
    server: str
    address: str
    access_key: str
    secret_key: str

    def obscure(self, passphrase: str) -> str:
        return docker("run", "--rm", RCLONE_IMAGE, "obscure", passphrase).stdout.strip()

    def new_bucket(self) -> str:
        bucket = unique_name("bkt")
        docker("exec", self.server, "mkdir", "-p", f"/data/{bucket}")
        return bucket

    def env_for(self, bucket: str, *, passphrase: str, salt: str) -> dict[str, str]:
        return {
            "BACKUP_S3_PROVIDER": "Other",
            "BACKUP_S3_ENDPOINT": f"http://{self.address}:{S3_PORT}",
            "BACKUP_S3_REGION": "us-east-1",
            "BACKUP_S3_BUCKET": bucket,
            "BACKUP_S3_ACCESS_KEY_ID": self.access_key,
            "BACKUP_S3_SECRET_ACCESS_KEY": self.secret_key,
            "BACKUP_CRYPT_PASSWORD": self.obscure(passphrase),
            "BACKUP_CRYPT_PASSWORD2": self.obscure(salt),
        }

    def runner(self, backup_env: Mapping[str, str]) -> DockerRclone:
        return DockerRclone(remote.rclone_env(backup_env))

    def objects(self, bucket: str) -> set[str]:
        """Server-side (ciphertext) objects as ``path size mtime`` lines."""
        proc = docker(
            "exec",
            self.server,
            "sh",
            "-c",
            f"cd /data/{bucket} && find . -type f -exec stat -c '%n %s %Y' {{}} +",
            check=False,
        )
        return {line for line in proc.stdout.splitlines() if line.strip()}


def _wait_until_ready(double: S3Double) -> None:
    env = double.env_for(double.new_bucket(), passphrase="warmup-one", salt="warmup-two")
    runner = double.runner(env)
    raw = remote.raw_bucket_remote(env)
    for _ in range(STARTUP_TRIES):
        if runner(["lsf", raw], {}).returncode == 0:
            return
        time.sleep(1)
    logs = docker("logs", double.server, check=False).stderr[-400:]
    pytest.fail(f"rclone serve s3 did not become ready: {logs}")


@pytest.fixture(scope="module")
def s3_double() -> Iterator[S3Double]:
    _require_rclone_image()
    server = unique_name("t131-s3")
    access_key = secrets.token_hex(10)
    secret_key = secrets.token_hex(20)
    try:
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
        address = docker(
            "inspect",
            "--format",
            "{{.NetworkSettings.Networks.bridge.IPAddress}}",
            server,
        ).stdout.strip()
        assert address, "the server container has no bridge address"
        double = S3Double(server, address, access_key, secret_key)
        _wait_until_ready(double)
        yield double
    finally:
        docker("rm", "-f", server, check=False, timeout=60)


# --------------------------------------------------------------------------- #
# Fixtures for a bundle
# --------------------------------------------------------------------------- #

DAY1 = datetime(2026, 9, 30, 3, 15, 0, tzinfo=UTC)
DAY2 = datetime(2026, 10, 1, 3, 15, 0, tzinfo=UTC)


def _fake_dump(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"FAKE-PG-DUMP\x00" * 64)
    return out


def _make_bundle(tmp_path: Path) -> Path:
    source = tmp_path / "raw"
    (source / "interval=1m" / "symbol=BTCUSDT").mkdir(parents=True)
    (source / "interval=1m" / "symbol=BTCUSDT" / "part.parquet").write_bytes(b"AAA" * 400)
    (source / "oi.parquet").write_bytes(b"BBB" * 400)
    bundle = tmp_path / "bundle"
    backup_mod.backup(bundle_root=bundle, pg_dump_runner=_fake_dump, parquet_roots=[source])
    return bundle


def _set_env(monkeypatch: pytest.MonkeyPatch, env: Mapping[str, str]) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_push_list_pull_cryptcheck_and_retention_with_the_real_rclone(
    s3_double: S3Double, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bucket = s3_double.new_bucket()
    env = s3_double.env_for(bucket, passphrase=secrets.token_hex(8), salt=secrets.token_hex(8))
    runner = s3_double.runner(env)
    _set_env(monkeypatch, env)
    bundle = _make_bundle(tmp_path)

    # First push creates the sentinel on the empty bucket; the second adds another snapshot.
    assert (
        main(
            ["push", "--bundle-root", str(bundle), "--init-remote"],
            rclone_runner=runner,
            now_utc=DAY1,
        )
        == 0
    )
    after_first = s3_double.objects(bucket)
    assert after_first
    assert main(["push", "--bundle-root", str(bundle)], rclone_runner=runner, now_utc=DAY2) == 0
    after_second = s3_double.objects(bucket)

    # Nothing that existed (parquet objects included) was changed or removed by the second push.
    assert after_first <= after_second
    assert len(after_second) > len(after_first)
    # The provider sees ciphertext only: no plaintext name or fragment of one.
    stored_names = " ".join(after_second)
    for plain in ("snapshots", "parquet", "pg.dump", "manifest", "sentinel", "oi.parquet"):
        assert plain not in stored_names

    remote.check_sentinel(runner)
    snaps = remote.list_snapshots(runner)
    assert snaps == [remote.snapshot_id(DAY1), remote.snapshot_id(DAY2)]

    # Pull rebuilds the bundle; the adapter verified it, and it matches the source bundle.
    dest = tmp_path / "pulled"
    assert main(["pull", "--dest", str(dest)], rclone_runner=runner) == 0
    assert backup_mod.verify_bundle(dest) == []
    assert (dest / "manifest.json").read_bytes() == (bundle / "manifest.json").read_bytes()
    assert (dest / "pg.dump").read_bytes() == (bundle / "pg.dump").read_bytes()
    assert main(["pull", "--dest", str(dest)], rclone_runner=runner) == 1  # non-empty dest refused

    # cryptcheck passes on identical files and fails when a local file differs.
    snap_remote = f"{CRYPT}snapshots/{remote.snapshot_id(DAY2)}"
    check = ["cryptcheck", str(bundle), snap_remote, "--include", "/pg.dump"]
    assert runner(check, {}).returncode == 0
    (bundle / "pg.dump").write_bytes(b"changed after upload")
    assert runner(check, {}).returncode != 0

    # Retention: plant nine consecutive old days, then apply 7/4/6 for real.
    manifest_remote = f"{snap_remote}/manifest.json"
    planted = [
        remote.snapshot_id(datetime(2025, 1, day, 3, 15, 0, tzinfo=UTC)) for day in range(1, 10)
    ]
    for name in planted:
        copied = runner(["copyto", manifest_remote, f"{CRYPT}snapshots/{name}/manifest.json"], {})
        assert copied.returncode == 0
    everything = remote.list_snapshots(runner)
    assert sorted(everything) == sorted([*planted, *snaps])
    keep, delete = remote.select_retained(everything)
    assert delete  # the oldest planted days fall outside every window
    assert set(snaps) <= keep

    assert main(["retain", "--dry-run"], rclone_runner=runner) == 0
    assert remote.list_snapshots(runner) == sorted(everything)
    assert main(["retain"], rclone_runner=runner) == 0
    assert remote.list_snapshots(runner) == sorted(keep)
    # The Parquet objects survived retention: pulling the newest snapshot still verifies.
    again = tmp_path / "pulled-after-retention"
    assert main(["pull", "--dest", str(again)], rclone_runner=runner) == 0


def test_a_wrong_crypt_key_is_refused_by_every_operation(
    s3_double: S3Double, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bucket = s3_double.new_bucket()
    good = s3_double.env_for(bucket, passphrase=secrets.token_hex(8), salt=secrets.token_hex(8))
    bad = s3_double.env_for(bucket, passphrase=secrets.token_hex(8), salt=secrets.token_hex(8))
    good_runner = s3_double.runner(good)
    bad_runner = s3_double.runner(bad)
    bundle = _make_bundle(tmp_path)

    _set_env(monkeypatch, good)
    assert (
        main(
            ["push", "--bundle-root", str(bundle), "--init-remote"],
            rclone_runner=good_runner,
            now_utc=DAY1,
        )
        == 0
    )
    before = s3_double.objects(bucket)

    _set_env(monkeypatch, bad)
    with pytest.raises(RemoteError, match="sentinel"):
        remote.check_sentinel(bad_runner)
    assert main(["push", "--bundle-root", str(bundle)], rclone_runner=bad_runner, now_utc=DAY2) == 1
    assert main(["retain"], rclone_runner=bad_runner) == 1
    assert main(["pull", "--dest", str(tmp_path / "nope")], rclone_runner=bad_runner) == 1
    # --init-remote must not initialise an existing store that merely looks empty with this key.
    assert (
        main(
            ["push", "--bundle-root", str(bundle), "--init-remote"],
            rclone_runner=bad_runner,
            now_utc=DAY2,
        )
        == 1
    )
    assert s3_double.objects(bucket) == before

    _set_env(monkeypatch, good)
    remote.check_sentinel(good_runner)  # the right key still works
    assert remote.list_snapshots(good_runner) == [remote.snapshot_id(DAY1)]
