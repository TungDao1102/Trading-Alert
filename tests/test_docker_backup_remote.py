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
import random
import secrets
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
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
    # WR-01: the real recursive listing reports a snapshot as complete once it has a manifest.
    assert remote.list_complete_snapshots(runner) == sorted(everything)
    half = remote.snapshot_id(datetime(2025, 1, 20, 3, 15, 0, tzinfo=UTC))
    dump_remote = f"{snap_remote}/pg.dump"
    assert runner(["copyto", dump_remote, f"{CRYPT}snapshots/{half}/pg.dump"], {}).returncode == 0
    assert half in remote.list_snapshots(runner)
    assert half not in remote.list_complete_snapshots(runner)
    assert remote.pull_snapshot(tmp_path / "skips-half", runner) == snaps[-1]
    everything = remote.list_snapshots(runner)
    keep, delete = remote.select_retained(remote.list_complete_snapshots(runner))
    assert delete  # the oldest planted days fall outside every window
    assert set(snaps) <= keep

    assert main(["retain", "--dry-run"], rclone_runner=runner) == 0
    assert remote.list_snapshots(runner) == sorted(everything)
    assert main(["retain"], rclone_runner=runner) == 0
    assert remote.list_snapshots(runner) == sorted(keep)  # the stale half push is purged too
    # The Parquet objects survived retention: pulling the newest snapshot still verifies.
    again = tmp_path / "pulled-after-retention"
    assert main(["pull", "--dest", str(again)], rclone_runner=runner) == 0


def test_push_after_a_restore_with_new_mtimes_succeeds_with_the_real_rclone(
    s3_double: S3Double, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-01: same bytes, different mtime (a restored host) is not an immutable violation."""
    bucket = s3_double.new_bucket()
    env = s3_double.env_for(bucket, passphrase=secrets.token_hex(8), salt=secrets.token_hex(8))
    runner = s3_double.runner(env)
    _set_env(monkeypatch, env)
    bundle = _make_bundle(tmp_path)
    assert (
        main(
            ["push", "--bundle-root", str(bundle), "--init-remote"],
            rclone_runner=runner,
            now_utc=DAY1,
        )
        == 0
    )

    pulled = tmp_path / "pulled"
    assert main(["pull", "--dest", str(pulled)], rclone_runner=runner) == 0
    restored = tmp_path / "restored" / "raw"
    backup_mod.restore_bundle(
        pulled,
        parquet_target=restored,
        database_url=None,
        force=False,
        skip_db=True,
        pg_restore_runner=lambda _dump, _target: None,
        migrate_runner=lambda _url: None,
    )
    for staged in restored.rglob("*.parquet"):  # a host restored months later
        later_ns = staged.stat().st_mtime_ns + 90 * 86_400 * 1_000_000_000
        os.utime(staged, ns=(later_ns, later_ns))
    bundle2 = tmp_path / "bundle2"
    backup_mod.backup(bundle_root=bundle2, pg_dump_runner=_fake_dump, parquet_roots=[restored])

    assert main(["push", "--bundle-root", str(bundle2)], rclone_runner=runner, now_utc=DAY2) == 0


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


# --------------------------------------------------------------------------- #
# CR-01 replacement (D064): manifest SHA-256 comparison, cryptcheck before the manifest
#
# Real rclone 1.75.1 through the adapter. What each test asserts was observed first in
# .planning/quick/261007-onb-cr-01-replacement-d064-parquet-push-mani/261007-onb-proof-output.txt
# (cryptcheck detects a same-size change, an out-of-band overwrite and a deletion; a removed
# manifest object leaves the snapshot incomplete). Double only, not a real S3 provider (D064).
# --------------------------------------------------------------------------- #

DAY3 = datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC)
DAY4 = datetime(2026, 10, 3, 3, 15, 0, tzinfo=UTC)
ORIG_NS = 1_700_000_000 * 1_000_000_000
NINETY_DAYS_NS = 90 * 86_400 * 1_000_000_000
CRYPT_OVERHEAD = 48  # bytes added to a plaintext of up to 64 KiB (proof FINDINGS, o3)
PARQUET_FILES = {"interval=1m/a.parquet": b"A" * 1200, "interval=1m/b.parquet": b"B" * 1300}
NEW_PARQUET_FILE = {"interval=1m/c.parquet": b"C" * 1400}
A_REMOTE = f"{CRYPT}parquet/raw/interval=1m/a.parquet"
B_REMOTE = f"{CRYPT}parquet/raw/interval=1m/b.parquet"
C_REMOTE = f"{CRYPT}parquet/raw/interval=1m/c.parquet"
HEAD_DIFFERENT = "parquet push refused: path(s) already published with different content"
HEAD_ORPHAN = (
    "parquet push refused: remote object(s) differ from the local file(s) "
    "and no complete snapshot names them"
)


class _Crash(Exception):
    """A simulated process death between two rclone calls."""


@dataclass
class _CallLog:
    """A runner wrapper that records argv and can run an action after a matching call."""

    inner: remote.RcloneRunner
    calls: list[list[str]] = field(default_factory=list)
    hooks: list[tuple[Callable[[Sequence[str]], bool], Callable[[], None]]] = field(
        default_factory=list
    )

    def __call__(self, argv: Sequence[str], extra: Mapping[str, str]) -> RcloneResult:
        result = self.inner(argv, extra)
        self.calls.append(list(argv))
        for hook in list(self.hooks):
            if hook[0](argv):
                self.hooks.remove(hook)
                hook[1]()
        return result

    def after(self, match: Callable[[Sequence[str]], bool], action: Callable[[], None]) -> None:
        self.hooks.append((match, action))


def _is_parquet_upload(argv: Sequence[str]) -> bool:
    return argv[0] == "copy" and not argv[1].startswith(CRYPT) and "--files-from-raw" in argv


def _is_manifest_upload(argv: Sequence[str]) -> bool:
    return argv[0] == "copyto" and argv[2].endswith("/manifest.json")


def _bundle_from(
    tmp_path: Path, name: str, files: Mapping[str, bytes], mtime_ns: int | None = None
) -> Path:
    """A bundle whose source root is named ``raw`` (remote paths ``parquet/raw/...``)."""
    source = tmp_path / name / "raw"
    for rel, data in files.items():
        target = source / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    bundle = tmp_path / f"{name}-bundle"
    backup_mod.backup(bundle_root=bundle, pg_dump_runner=_fake_dump, parquet_roots=[source])
    if mtime_ns is not None:  # touching the staged files does not change the manifest
        for staged in (bundle / "parquet").rglob("*.parquet"):
            os.utime(staged, ns=(mtime_ns, mtime_ns))
    return bundle


def _ciphertext_objects(s3: S3Double, bucket: str) -> dict[str, int]:
    """Server-side object path to size."""
    out: dict[str, int] = {}
    for line in s3.objects(bucket):
        path, size, _ = line.rsplit(" ", 2)
        out[path.removeprefix("./")] = int(size)
    return out


def _ciphertext_object(
    s3: S3Double, bucket: str, plain_size: int, exclude: Collection[str] = ()
) -> tuple[str, int]:
    """The one server object holding ``plain_size`` plaintext bytes (constant crypt overhead)."""
    wanted = plain_size + CRYPT_OVERHEAD
    found = [
        (path, size)
        for path, size in _ciphertext_objects(s3, bucket).items()
        if size == wanted and path not in exclude
    ]
    assert len(found) == 1, f"expected one object of {wanted} bytes, found {found}"
    return found[0]


def _corrupt_object(
    s3: S3Double, env: Mapping[str, str], path: str, size: int, scratch: Path
) -> None:
    """Overwrite a server object through the raw S3 remote with same-length random bytes."""
    garbage = scratch / "garbage.bin"
    garbage.write_bytes(random.Random(7).randbytes(size))
    done = s3.runner(env)(["copyto", str(garbage), f"{remote.raw_bucket_remote(env)}/{path}"], {})
    assert done.returncode == 0, done.stderr


@dataclass
class _Remote:
    """A fresh bucket with its crypt environment, the docker runner and the first push done."""

    s3: S3Double
    bucket: str
    env: Mapping[str, str]
    runner: DockerRclone

    def push(self, bundle: Path, when: datetime, runner: remote.RcloneRunner | None = None) -> int:
        return main(
            ["push", "--bundle-root", str(bundle)],
            rclone_runner=runner or self.runner,
            now_utc=when,
        )

    def complete(self) -> list[str]:
        return remote.list_complete_snapshots(self.runner)


def _new_remote(
    s3: S3Double, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: Mapping[str, bytes]
) -> tuple[_Remote, Path]:
    """Initialise a bucket and push ``first`` as the DAY1 snapshot (original mtimes)."""
    bucket = s3.new_bucket()
    env = s3.env_for(bucket, passphrase=secrets.token_hex(8), salt=secrets.token_hex(8))
    runner = s3.runner(env)
    _set_env(monkeypatch, env)
    bundle = _bundle_from(tmp_path, "one", first, ORIG_NS)
    code = main(
        ["push", "--bundle-root", str(bundle), "--init-remote"], rclone_runner=runner, now_utc=DAY1
    )
    assert code == 0
    return _Remote(s3, bucket, env, runner), bundle


def test_known_path_with_same_content_is_skipped_even_with_new_mtimes(
    s3_double: S3Double, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rem, _first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    before = s3_double.objects(rem.bucket)
    again = _bundle_from(tmp_path, "two", PARQUET_FILES, ORIG_NS + NINETY_DAYS_NS)
    log = _CallLog(rem.runner)

    assert rem.push(again, DAY2, log) == 0

    assert not any(_is_parquet_upload(call) for call in log.calls)
    after = s3_double.objects(rem.bucket)
    assert before <= after  # nothing that existed was changed or removed
    assert len(after - before) == 2  # exactly pg.dump and manifest.json of the new snapshot
    assert rem.complete() == [remote.snapshot_id(DAY1), remote.snapshot_id(DAY2)]


@pytest.mark.parametrize("new_mtime", [False, True], ids=["original-mtime", "new-mtime"])
def test_same_path_same_size_different_content_fails_hard_without_overwrite(
    s3_double: S3Double,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    new_mtime: bool,
) -> None:
    rem, _first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    before = s3_double.objects(rem.bucket)
    changed = {**PARQUET_FILES, "interval=1m/a.parquet": b"X" * 1200}
    bundle = _bundle_from(tmp_path, "two", changed, ORIG_NS + (NINETY_DAYS_NS if new_mtime else 0))
    capsys.readouterr()

    assert rem.push(bundle, DAY2) == 1

    err = capsys.readouterr().err
    assert HEAD_DIFFERENT in err
    assert "raw/interval=1m/a.parquet" in err
    assert rem.runner(["cat", A_REMOTE], {}).stdout == "A" * 1200  # the remote file is unchanged
    assert remote.list_snapshots(rem.runner) == [remote.snapshot_id(DAY1)]
    assert s3_double.objects(rem.bucket) == before


def test_same_path_different_size_fails_hard_without_overwrite(
    s3_double: S3Double,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rem, _first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    before = s3_double.objects(rem.bucket)
    changed = {**PARQUET_FILES, "interval=1m/b.parquet": b"B" * 1301}
    bundle = _bundle_from(tmp_path, "two", changed, ORIG_NS)
    capsys.readouterr()

    assert rem.push(bundle, DAY2) == 1

    err = capsys.readouterr().err
    assert HEAD_DIFFERENT in err
    assert "raw/interval=1m/b.parquet" in err
    assert rem.runner(["cat", B_REMOTE], {}).stdout == "B" * 1300
    assert remote.list_snapshots(rem.runner) == [remote.snapshot_id(DAY1)]
    assert s3_double.objects(rem.bucket) == before


def test_a_new_path_uploads_and_nothing_else_changes(
    s3_double: S3Double, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rem, _first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    before = s3_double.objects(rem.bucket)
    bundle = _bundle_from(tmp_path, "two", {**PARQUET_FILES, **NEW_PARQUET_FILE}, ORIG_NS)
    log = _CallLog(rem.runner)

    assert rem.push(bundle, DAY2, log) == 0

    uploads = [call for call in log.calls if _is_parquet_upload(call)]
    assert len(uploads) == 1
    after = s3_double.objects(rem.bucket)
    assert before <= after  # earlier objects identical, mtimes included
    assert len(after - before) == 3  # the new Parquet object, pg.dump and manifest.json
    assert rem.runner(["cat", C_REMOTE], {}).stdout == "C" * 1400


def test_an_orphan_identical_to_the_local_file_is_adopted_after_an_interrupted_push(
    s3_double: S3Double, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rem, _first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    before = s3_double.objects(rem.bucket)
    bundle = _bundle_from(tmp_path, "two", {**PARQUET_FILES, **NEW_PARQUET_FILE}, ORIG_NS)
    dying = _CallLog(rem.runner)

    def die() -> None:
        raise _Crash("killed right after the Parquet upload")

    dying.after(_is_parquet_upload, die)
    with pytest.raises(_Crash):
        remote.push_snapshot(bundle, dying, now_utc=DAY2)
    orphan = s3_double.objects(rem.bucket) - before
    assert len(orphan) == 1  # the Parquet object went up, nothing else did
    assert rem.complete() == [remote.snapshot_id(DAY1)]
    log = _CallLog(rem.runner)

    assert rem.push(bundle, DAY3, log) == 0

    assert orphan <= s3_double.objects(rem.bucket)  # the orphan line is identical: not re-uploaded
    assert not any(_is_parquet_upload(call) for call in log.calls)
    assert any(call[0] == "cryptcheck" and "--files-from-raw" in call for call in log.calls)
    assert rem.complete() == [remote.snapshot_id(DAY1), remote.snapshot_id(DAY3)]


def test_an_orphan_different_from_the_local_file_fails_hard_and_stays_untouched(
    s3_double: S3Double,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rem, _first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    other = tmp_path / "other.bin"
    other.write_bytes(b"Z" * 1400)  # same size as the local c.parquet, other content
    assert rem.runner(["copyto", str(other), C_REMOTE], {}).returncode == 0
    before = s3_double.objects(rem.bucket)
    bundle = _bundle_from(tmp_path, "two", {**PARQUET_FILES, **NEW_PARQUET_FILE}, ORIG_NS)
    capsys.readouterr()

    assert rem.push(bundle, DAY2) == 1

    err = capsys.readouterr().err
    assert HEAD_ORPHAN in err
    assert "raw/interval=1m/c.parquet" in err
    assert s3_double.objects(rem.bucket) == before
    assert rem.runner(["cat", C_REMOTE], {}).stdout == "Z" * 1400
    assert remote.list_snapshots(rem.runner) == [remote.snapshot_id(DAY1)]


def test_upload_followed_by_cryptcheck_failure_leaves_the_snapshot_incomplete(
    s3_double: S3Double, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rem, _first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    known = set(_ciphertext_objects(s3_double, rem.bucket))
    bundle = _bundle_from(tmp_path, "two", {**PARQUET_FILES, **NEW_PARQUET_FILE}, ORIG_NS)
    log = _CallLog(rem.runner)

    def corrupt_new_object() -> None:
        path, size = _ciphertext_object(s3_double, rem.bucket, 1400, exclude=known)
        _corrupt_object(s3_double, rem.env, path, size, tmp_path)

    log.after(_is_parquet_upload, corrupt_new_object)

    assert rem.push(bundle, DAY2, log) == 1

    assert rem.complete() == [remote.snapshot_id(DAY1)]
    assert not any(_is_manifest_upload(call) for call in log.calls)  # no manifest was published


def test_a_remote_object_modified_after_upload_is_detected(
    s3_double: S3Double,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rem, first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    path, size = _ciphertext_object(s3_double, rem.bucket, 1200)
    _corrupt_object(s3_double, rem.env, path, size, tmp_path)
    capsys.readouterr()

    assert rem.push(first, DAY2) == 1

    err = capsys.readouterr().err
    assert "parquet verification failed" in err
    assert "raw/interval=1m/a.parquet" in err
    assert rem.complete() == [remote.snapshot_id(DAY1)]


def test_a_remote_object_deleted_after_upload_is_detected(
    s3_double: S3Double,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rem, first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    assert rem.runner(["deletefile", B_REMOTE], {}).returncode == 0
    capsys.readouterr()

    assert rem.push(first, DAY2) == 1

    err = capsys.readouterr().err
    assert "parquet verification failed" in err
    assert "raw/interval=1m/b.parquet" in err
    assert rem.complete() == [remote.snapshot_id(DAY1)]


def test_a_manifest_that_fails_its_check_is_removed_and_the_snapshot_stays_incomplete(
    s3_double: S3Double, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rem, _first = _new_remote(s3_double, tmp_path, monkeypatch, PARQUET_FILES)
    known = set(_ciphertext_objects(s3_double, rem.bucket))
    bundle = _bundle_from(tmp_path, "two", {**PARQUET_FILES, **NEW_PARQUET_FILE}, ORIG_NS)
    manifest_size = (bundle / "manifest.json").stat().st_size
    log = _CallLog(rem.runner)

    def corrupt_manifest() -> None:
        path, size = _ciphertext_object(s3_double, rem.bucket, manifest_size, exclude=known)
        _corrupt_object(s3_double, rem.env, path, size, tmp_path)

    log.after(_is_manifest_upload, corrupt_manifest)
    id1, id2 = remote.snapshot_id(DAY1), remote.snapshot_id(DAY2)

    assert rem.push(bundle, DAY2, log) == 1

    deletes = [call for call in log.calls if call[0] == "deletefile"]
    assert deletes == [["deletefile", f"{CRYPT}snapshots/{id2}/manifest.json"]]
    assert rem.complete() == [id1]  # the new snapshot never looks complete
    listing = rem.runner(["lsf", "-R", "--files-only", f"{CRYPT}snapshots/{id2}/"], {})
    assert listing.stdout.split() == ["pg.dump"]  # only its manifest was removed
    assert remote.pull_snapshot(tmp_path / "pulled", rem.runner) == id1
