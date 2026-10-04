"""Tests for the rclone off-host backup adapter (Phase 13.1 plan 08, D-12 / D-17).

No rclone binary and no network: every rclone call goes through an injected fake runner that
records argv. The real binary is exercised in tests/test_docker_backup_remote.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from src.ops import backup as backup_mod
from src.ops import backup_remote as remote
from src.ops.backup import main
from src.ops.backup_remote import RcloneResult, RemoteConfigError, RemoteError

NOW = datetime(2026, 10, 1, 3, 15, 0, tzinfo=UTC)
SNAP = "20261001T031500Z"
SENTINEL_ARG = "BACKUPS3CRYPT:_sentinel/sentinel.txt"

S3_ENV = {
    "BACKUP_S3_PROVIDER": "Other",
    "BACKUP_S3_ENDPOINT": "https://s3.example.invalid",
    "BACKUP_S3_REGION": "us-east-1",
    "BACKUP_S3_BUCKET": "trading-backups",
    "BACKUP_S3_ACCESS_KEY_ID": "AccessIdValue12345",
    "BACKUP_S3_SECRET_ACCESS_KEY": "SecretKeyValue-abcdef-98765",
    "BACKUP_CRYPT_PASSWORD": "ObscuredPasswordOne-xyz",
    "BACKUP_CRYPT_PASSWORD2": "ObscuredPasswordTwo-xyz",
}
SECRET_VALUES = (
    "AccessIdValue12345",
    "SecretKeyValue-abcdef-98765",
    "ObscuredPasswordOne-xyz",
    "ObscuredPasswordTwo-xyz",
)


class FakeRclone:
    """Records argv; answers the sentinel read and lets a test override any command."""

    def __init__(
        self,
        *,
        sentinel: RcloneResult | None = None,
        overrides: Mapping[str, RcloneResult] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.sentinel = sentinel or RcloneResult(0, remote.SENTINEL_CONTENT, "")
        self.overrides = dict(overrides or {})

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        self.calls.append(list(argv))
        if list(argv)[:2] == ["cat", SENTINEL_ARG]:
            return self.sentinel
        return self.overrides.get(argv[0], RcloneResult(0, "", ""))

    def verbs(self) -> list[str]:
        return [call[0] for call in self.calls]


def _fake_dump(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"FAKE-PG-DUMP\x00" * 8)
    return out


def _make_bundle(tmp_path: Path, *, with_parquet: bool = True) -> Path:
    source = tmp_path / "raw"
    source.mkdir(exist_ok=True)
    if with_parquet:
        (source / "oi.parquet").write_bytes(b"BBB" * 100)
    bundle = tmp_path / "bundle"
    backup_mod.backup(bundle_root=bundle, pg_dump_runner=_fake_dump, parquet_roots=[source])
    return bundle


# --------------------------------------------------------------------------- #
# rclone_env
# --------------------------------------------------------------------------- #


def test_rclone_env_maps_all_eight_variables() -> None:
    mapped = remote.rclone_env(S3_ENV)

    assert mapped == {
        "RCLONE_CONFIG_BACKUPS3_TYPE": "s3",
        "RCLONE_CONFIG_BACKUPS3_PROVIDER": "Other",
        "RCLONE_CONFIG_BACKUPS3_ENDPOINT": "https://s3.example.invalid",
        "RCLONE_CONFIG_BACKUPS3_REGION": "us-east-1",
        "RCLONE_CONFIG_BACKUPS3_ACCESS_KEY_ID": "AccessIdValue12345",
        "RCLONE_CONFIG_BACKUPS3_SECRET_ACCESS_KEY": "SecretKeyValue-abcdef-98765",
        "RCLONE_CONFIG_BACKUPS3CRYPT_TYPE": "crypt",
        "RCLONE_CONFIG_BACKUPS3CRYPT_REMOTE": "BACKUPS3:trading-backups",
        "RCLONE_CONFIG_BACKUPS3CRYPT_PASSWORD": "ObscuredPasswordOne-xyz",
        "RCLONE_CONFIG_BACKUPS3CRYPT_PASSWORD2": "ObscuredPasswordTwo-xyz",
    }


def test_rclone_env_missing_variable_names_it_and_no_values() -> None:
    environ = {k: v for k, v in S3_ENV.items() if k != "BACKUP_CRYPT_PASSWORD"}

    with pytest.raises(RemoteConfigError) as excinfo:
        remote.rclone_env(environ)

    message = str(excinfo.value)
    assert "BACKUP_CRYPT_PASSWORD" in message
    for value in S3_ENV.values():
        assert value not in message


def test_rclone_env_empty_value_counts_as_missing_and_lists_every_name() -> None:
    environ = {**S3_ENV, "BACKUP_S3_BUCKET": "", "BACKUP_S3_REGION": ""}

    with pytest.raises(RemoteConfigError) as excinfo:
        remote.rclone_env(environ)

    assert "BACKUP_S3_BUCKET" in str(excinfo.value)
    assert "BACKUP_S3_REGION" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# snapshot ids
# --------------------------------------------------------------------------- #


def test_snapshot_id_round_trip_and_utc_conversion() -> None:
    assert remote.snapshot_id(NOW) == SNAP
    assert remote.parse_snapshot_id(SNAP) == NOW
    plus7 = datetime(2026, 10, 1, 10, 15, 0, tzinfo=UTC).astimezone(UTC)
    assert remote.snapshot_id(plus7) == "20261001T101500Z"


@pytest.mark.parametrize(
    "name",
    ["", "latest", "20261001", "20261001T031500", "20261301T031500Z", "20261001T256100Z", "x" * 16],
)
def test_parse_snapshot_id_rejects_malformed_names(name: str) -> None:
    assert remote.parse_snapshot_id(name) is None


def test_snapshot_id_needs_an_aware_datetime() -> None:
    with pytest.raises(ValueError, match="timezone"):
        remote.snapshot_id(datetime(2026, 10, 1, 3, 15, 0))


# --------------------------------------------------------------------------- #
# push (tracer: through the CLI)
# --------------------------------------------------------------------------- #


def test_push_cli_runs_sentinel_then_parquet_then_snapshot_then_cryptcheck(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _make_bundle(tmp_path)
    fake = FakeRclone()
    root = str(bundle.resolve())

    code = main(["push", "--bundle-root", str(bundle)], rclone_runner=fake, now_utc=NOW)

    assert code == 0
    assert f"push-OK snapshot={SNAP}" in capsys.readouterr().out
    assert fake.calls == [
        ["cat", SENTINEL_ARG],
        [
            "copy",
            str(Path(root) / "parquet"),
            "BACKUPS3CRYPT:parquet",
            "--immutable",
            "--size-only",
        ],
        [
            "copyto",
            str(Path(root) / "pg.dump"),
            f"BACKUPS3CRYPT:snapshots/{SNAP}/pg.dump",
            "--immutable",
        ],
        [
            "copyto",
            str(Path(root) / "manifest.json"),
            f"BACKUPS3CRYPT:snapshots/{SNAP}/manifest.json",
            "--immutable",
        ],
        [
            "cryptcheck",
            root,
            f"BACKUPS3CRYPT:snapshots/{SNAP}",
            "--include",
            "/pg.dump",
            "--include",
            "/manifest.json",
        ],
    ]


def test_push_uploads_manifest_last_so_a_snapshot_is_never_complete_before_its_files(
    tmp_path: Path,
) -> None:
    bundle = _make_bundle(tmp_path)
    fake = FakeRclone()

    remote.push_snapshot(bundle, fake, now_utc=NOW)

    targets = [call[2] for call in fake.calls if call[0] in {"copy", "copyto"}]
    assert targets[0] == "BACKUPS3CRYPT:parquet"
    assert targets[-1].endswith("/manifest.json")


def test_push_skips_parquet_copy_when_bundle_has_no_parquet(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path, with_parquet=False)
    shutil.rmtree(bundle / "parquet")  # an empty root leaves an empty directory behind
    fake = FakeRclone()

    remote.push_snapshot(bundle, fake, now_utc=NOW)

    assert all("BACKUPS3CRYPT:parquet" not in call for call in fake.calls)


@pytest.mark.parametrize(
    "sentinel",
    [
        RcloneResult(0, "", ""),
        RcloneResult(0, "something else\n", ""),
        RcloneResult(3, "", "directory not found"),
        RcloneResult(1, "", "boom"),
    ],
    ids=["empty", "mismatch", "exit3", "exit1"],
)
def test_push_stops_before_any_copy_when_sentinel_is_not_the_expected_value(
    tmp_path: Path, sentinel: RcloneResult, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _make_bundle(tmp_path)
    fake = FakeRclone(sentinel=sentinel)

    code = main(["push", "--bundle-root", str(bundle)], rclone_runner=fake, now_utc=NOW)

    assert code == 1
    assert fake.verbs() == ["cat"]
    assert "sentinel" in capsys.readouterr().err


@pytest.mark.parametrize("failing", ["copy", "copyto", "cryptcheck"])
@pytest.mark.parametrize("code", [1, 3])
def test_push_fails_on_nonzero_exit_of_any_step_including_exit_3(
    tmp_path: Path, failing: str, code: int, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _make_bundle(tmp_path)
    fake = FakeRclone(overrides={failing: RcloneResult(code, "", "directory not found")})

    exit_code = main(["push", "--bundle-root", str(bundle)], rclone_runner=fake, now_utc=NOW)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert f"exit {code}" in captured.err
    assert "push-OK" not in captured.out


def test_push_refuses_a_bundle_that_fails_verification_before_touching_the_remote(
    tmp_path: Path,
) -> None:
    bundle = _make_bundle(tmp_path)
    (bundle / "pg.dump").write_bytes(b"tampered")
    fake = FakeRclone()

    with pytest.raises(RemoteError, match="verification failed"):
        remote.push_snapshot(bundle, fake, now_utc=NOW)

    assert fake.calls == []


def test_push_cli_without_backup_environment_fails_naming_variables_not_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _make_bundle(tmp_path)
    for name in S3_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BACKUP_S3_SECRET_ACCESS_KEY", "")

    code = main(["push", "--bundle-root", str(bundle)], now_utc=NOW)

    assert code == 1
    err = capsys.readouterr().err
    assert "BACKUP_S3_BUCKET" in err
    assert "BACKUP_CRYPT_PASSWORD2" in err


# --------------------------------------------------------------------------- #
# --init-remote
# --------------------------------------------------------------------------- #


@pytest.fixture
def backup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in S3_ENV.items():
        monkeypatch.setenv(name, value)


def test_init_remote_writes_sentinel_only_on_an_empty_store(
    tmp_path: Path, backup_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _make_bundle(tmp_path)
    state = {"written": False}

    class Fresh(FakeRclone):
        def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
            if list(argv)[:2] == ["cat", SENTINEL_ARG]:
                self.calls.append(list(argv))
                if state["written"]:
                    return RcloneResult(0, remote.SENTINEL_CONTENT, "")
                return RcloneResult(3, "", "directory not found")
            if argv[0] == "copyto" and argv[2] == SENTINEL_ARG:
                self.calls.append(list(argv))
                assert Path(argv[1]).read_text(encoding="ascii") == remote.SENTINEL_CONTENT
                state["written"] = True
                return RcloneResult(0, "", "")
            return super().__call__(argv, env)

    fake = Fresh()

    code = main(
        ["push", "--bundle-root", str(bundle), "--init-remote"], rclone_runner=fake, now_utc=NOW
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "init-OK sentinel=written" in out
    assert f"push-OK snapshot={SNAP}" in out
    assert ["lsf", "--dirs-only", "BACKUPS3CRYPT:snapshots/"] in fake.calls
    assert ["lsf", "BACKUPS3:trading-backups"] in fake.calls
    assert ["copyto", fake.calls[3][1], SENTINEL_ARG, "--immutable"] in fake.calls


def test_init_remote_refuses_when_snapshots_listing_is_not_empty() -> None:
    fake = FakeRclone(
        sentinel=RcloneResult(3, "", "directory not found"),
        overrides={"lsf": RcloneResult(0, "20260101T000000Z/\n", "")},
    )

    with pytest.raises(RemoteError, match="already holds snapshots"):
        remote.init_sentinel(fake, raw_remote="BACKUPS3:b")

    assert "copyto" not in fake.verbs()


def test_init_remote_refuses_when_raw_bucket_is_not_empty_wrong_key_case() -> None:
    class WrongKey(FakeRclone):
        def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
            if argv[0] == "lsf" and argv[1] == "BACKUPS3:b":
                self.calls.append(list(argv))
                return RcloneResult(0, "h3l2k5/\n", "")
            return super().__call__(argv, env)

    fake = WrongKey(
        sentinel=RcloneResult(3, "", "directory not found"),
        overrides={"lsf": RcloneResult(3, "", "directory not found")},
    )

    with pytest.raises(RemoteError, match="bucket is not empty"):
        remote.init_sentinel(fake, raw_remote="BACKUPS3:b")

    assert "copyto" not in fake.verbs()


def test_init_remote_refuses_a_foreign_sentinel_and_leaves_a_valid_one_alone() -> None:
    foreign = FakeRclone(sentinel=RcloneResult(0, "other store\n", ""))
    with pytest.raises(RemoteError, match="differs"):
        remote.init_sentinel(foreign, raw_remote="BACKUPS3:b")

    valid = FakeRclone()
    assert remote.init_sentinel(valid, raw_remote="BACKUPS3:b") is False
    assert valid.verbs() == ["cat"]


def test_init_remote_refuses_on_a_hard_failure_instead_of_assuming_empty() -> None:
    fake = FakeRclone(sentinel=RcloneResult(1, "", "network down"))

    with pytest.raises(RemoteError, match="refusing --init-remote"):
        remote.init_sentinel(fake, raw_remote="BACKUPS3:b")


# --------------------------------------------------------------------------- #
# Secrets stay out of argv and error text
# --------------------------------------------------------------------------- #


def test_no_secret_value_appears_in_any_recorded_argv(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    fake = FakeRclone()

    remote.push_snapshot(bundle, fake, now_utc=NOW)

    mapped = remote.rclone_env(S3_ENV)
    secrets = [
        v for k, v in mapped.items() if k.endswith(("SECRET_ACCESS_KEY", "PASSWORD", "PASSWORD2"))
    ]
    assert secrets
    flat = "\n".join(arg for call in fake.calls for arg in call)
    for secret in (*secrets, *SECRET_VALUES):
        assert secret not in flat


def test_production_runner_puts_credentials_in_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    runner = remote.make_rclone_runner({**S3_ENV, "RCLONE_BIN": "rclone-test"})

    result = runner(["lsf", "BACKUPS3CRYPT:snapshots/"], {})

    assert result == RcloneResult(0, "ok", "")
    assert seen["cmd"] == ["rclone-test", "lsf", "BACKUPS3CRYPT:snapshots/"]
    assert seen["env"]["RCLONE_CONFIG_BACKUPS3_SECRET_ACCESS_KEY"] == "SecretKeyValue-abcdef-98765"
    assert seen["env"]["RCLONE_CONFIG_BACKUPS3CRYPT_REMOTE"] == "BACKUPS3:trading-backups"
    assert not any(value in " ".join(seen["cmd"]) for value in SECRET_VALUES)


def test_production_runner_reports_a_missing_binary_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    runner = remote.make_rclone_runner(S3_ENV)

    with pytest.raises(RemoteError, match="rclone binary not found"):
        runner(["version"], {})


def test_error_excerpt_scrubs_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in S3_ENV.items():
        monkeypatch.setenv(name, value)
    fake = FakeRclone(
        overrides={
            "copy": RcloneResult(1, "", "auth failed for SecretKeyValue-abcdef-98765 on endpoint")
        }
    )

    with pytest.raises(RemoteError) as excinfo:
        remote._call(fake, ["copy", "a", "b"])

    assert "SecretKeyValue-abcdef-98765" not in str(excinfo.value)
    assert "exit 1" in str(excinfo.value)


def test_manifest_json_written_by_backup_is_what_the_snapshot_names(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    assert set(manifest) == {"pg.dump", "parquet/raw/oi.parquet"}


# --------------------------------------------------------------------------- #
# A directory-backed fake of the crypt remote (push -> pull round trips)
# --------------------------------------------------------------------------- #

CRYPT = "BACKUPS3CRYPT:"


class StoreRclone:
    """Interprets the argv the adapter emits against a directory standing in for the remote."""

    def __init__(self, store: Path) -> None:
        self.store = store
        self.calls: list[list[str]] = []
        store.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        sentinel = self.store / "_sentinel" / "sentinel.txt"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(remote.SENTINEL_CONTENT, encoding="ascii", newline="\n")

    def _path(self, arg: str) -> Path:
        assert arg.startswith(CRYPT), arg
        return self.store / arg[len(CRYPT) :].rstrip("/")

    @staticmethod
    def _flag_values(argv: Sequence[str], flag: str) -> list[str]:
        return [argv[i + 1] for i, a in enumerate(argv) if a == flag]

    def _put(
        self, source: Path, target: Path, *, immutable: bool, size_only: bool = False
    ) -> RcloneResult:
        """Model rclone's default size+modtime comparison, which ``--immutable`` makes strict."""
        if target.exists():
            if size_only and target.stat().st_size == source.stat().st_size:
                return RcloneResult(0, "", "")
            if target.read_bytes() == source.read_bytes():
                if immutable and target.stat().st_mtime_ns != source.stat().st_mtime_ns:
                    return RcloneResult(6, "", "immutable file modified")
                return RcloneResult(0, "", "")
            if immutable:
                return RcloneResult(6, "", "immutable file modified")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        stat = source.stat()
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # rclone keeps the modtime
        return RcloneResult(0, "", "")

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        self.calls.append(list(argv))
        verb = argv[0]
        immutable = "--immutable" in argv
        size_only = "--size-only" in argv
        if verb == "cat":
            path = self._path(argv[1])
            if not path.is_file():
                return RcloneResult(3, "", "directory not found")
            return RcloneResult(0, path.read_text(encoding="ascii"), "")
        if verb == "lsf":
            target = argv[-1]
            if target.startswith("BACKUPS3:"):
                return RcloneResult(0, "", "")
            path = self._path(target)
            if not path.is_dir():
                return RcloneResult(3, "", "directory not found")
            dirs = sorted(d.name for d in path.iterdir() if d.is_dir())
            return RcloneResult(0, "".join(f"{name}/\n" for name in dirs), "")
        if verb == "copyto":
            return self._put(
                Path(argv[1]), self._path(argv[2]), immutable=immutable, size_only=size_only
            )
        if verb == "copy":
            source, dest = argv[1], argv[2]
            if source.startswith(CRYPT):  # remote -> local
                src_dir = self._path(source)
                files_from = self._flag_values(argv, "--files-from-raw")
                if files_from:
                    wanted = Path(files_from[0]).read_text(encoding="utf-8").splitlines()
                    candidates = [src_dir / rel for rel in wanted if (src_dir / rel).is_file()]
                else:
                    candidates = [p for p in src_dir.rglob("*") if p.is_file()]
                for file in candidates:
                    out = Path(dest) / file.relative_to(src_dir)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, out)  # rclone keeps the remote modtime on download
                return RcloneResult(0, "", "")
            for file in (p for p in Path(source).rglob("*") if p.is_file()):  # local -> remote
                target = self._path(dest) / file.relative_to(source)
                outcome = self._put(file, target, immutable=immutable, size_only=size_only)
                if outcome.returncode != 0:
                    return outcome
            return RcloneResult(0, "", "")
        if verb == "cryptcheck":
            local, remote_dir = Path(argv[1]), self._path(argv[2])
            names = [i.lstrip("/") for i in self._flag_values(argv, "--include")]
            for name in names:
                theirs = remote_dir / name
                if not theirs.is_file() or theirs.read_bytes() != (local / name).read_bytes():
                    return RcloneResult(1, "", "1 differences found")
            return RcloneResult(0, "", "")
        if verb == "purge":
            path = self._path(argv[1])
            if not path.is_dir():
                return RcloneResult(3, "", "directory not found")
            shutil.rmtree(path)
            return RcloneResult(0, "", "")
        raise AssertionError(f"unexpected rclone verb {verb}")

    def verbs(self) -> list[str]:
        return [call[0] for call in self.calls]


def _pushed_store(tmp_path: Path) -> tuple[StoreRclone, Path, str]:
    bundle = _make_bundle(tmp_path)
    store = StoreRclone(tmp_path / "remote")
    store.init()
    snap = remote.push_snapshot(bundle, store, now_utc=NOW)
    return store, bundle, snap


# --------------------------------------------------------------------------- #
# pull
# --------------------------------------------------------------------------- #


def test_pull_rebuilds_the_bundle_from_one_snapshot_and_verifies_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, bundle, snap = _pushed_store(tmp_path)
    store.calls.clear()
    dest = tmp_path / "restore"

    code = main(["pull", "--dest", str(dest)], rclone_runner=store)

    assert code == 0
    assert f"pull-OK snapshot={snap}" in capsys.readouterr().out
    assert backup_mod.verify_bundle(dest) == []
    assert (dest / "pg.dump").read_bytes() == (bundle / "pg.dump").read_bytes()
    assert (dest / "parquet" / "raw" / "oi.parquet").read_bytes() == b"BBB" * 100
    assert store.calls[0] == ["cat", SENTINEL_ARG]
    assert store.calls[1] == ["lsf", "--dirs-only", "BACKUPS3CRYPT:snapshots/"]
    parquet_copy = next(c for c in store.calls if "--files-from-raw" in c)
    assert parquet_copy[:2] == ["copy", "BACKUPS3CRYPT:parquet"]


def test_pull_fetches_exactly_the_parquet_files_the_manifest_names(tmp_path: Path) -> None:
    store, _bundle, _snap = _pushed_store(tmp_path)
    extra = store.store / "parquet" / "raw" / "unrelated.parquet"
    extra.write_bytes(b"not in any manifest")
    dest = tmp_path / "restore"

    remote.pull_snapshot(dest, store)

    assert not (dest / "parquet" / "raw" / "unrelated.parquet").exists()


def test_pull_fails_when_the_manifest_names_a_file_the_remote_lacks(tmp_path: Path) -> None:
    store, _bundle, _snap = _pushed_store(tmp_path)
    (store.store / "parquet" / "raw" / "oi.parquet").unlink()

    with pytest.raises(RemoteError, match="failed verification"):
        remote.pull_snapshot(tmp_path / "restore", store)


def test_pull_fails_when_a_pulled_file_was_tampered_with(tmp_path: Path) -> None:
    store, _bundle, _snap = _pushed_store(tmp_path)
    (store.store / "parquet" / "raw" / "oi.parquet").write_bytes(b"corrupt")

    with pytest.raises(RemoteError, match="failed verification"):
        remote.pull_snapshot(tmp_path / "restore", store)


def test_pull_refuses_a_non_empty_dest_before_any_remote_call(tmp_path: Path) -> None:
    store, _bundle, _snap = _pushed_store(tmp_path)
    store.calls.clear()
    dest = tmp_path / "restore"
    dest.mkdir()
    (dest / "keep.txt").write_text("precious", encoding="utf-8")

    with pytest.raises(RemoteError, match="empty directory"):
        remote.pull_snapshot(dest, store)

    assert store.calls == []
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "precious"


def test_pull_chooses_newest_parseable_id_or_the_named_snapshot(tmp_path: Path) -> None:
    store, bundle, first = _pushed_store(tmp_path)
    later = datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC)
    second = remote.push_snapshot(bundle, store, now_utc=later)
    (store.store / "snapshots" / "zz-scratch-notes").mkdir()

    assert remote.pull_snapshot(tmp_path / "a", store) == second
    assert remote.pull_snapshot(tmp_path / "b", store, snapshot=first) == first
    with pytest.raises(RemoteError, match="not found"):
        remote.pull_snapshot(tmp_path / "c", store, snapshot="20200101T000000Z")
    with pytest.raises(RemoteError, match="valid snapshot id"):
        remote.pull_snapshot(tmp_path / "d", store, snapshot="../x")


def test_pull_with_an_empty_snapshot_listing_is_an_error(tmp_path: Path) -> None:
    store = StoreRclone(tmp_path / "remote")
    store.init()

    with pytest.raises(RemoteError, match="no snapshots"):
        remote.pull_snapshot(tmp_path / "restore", store)


def test_pull_refuses_when_the_sentinel_does_not_decrypt(tmp_path: Path) -> None:
    store = StoreRclone(tmp_path / "remote")  # never initialised: looks like a wrong key

    with pytest.raises(RemoteError, match="sentinel"):
        remote.pull_snapshot(tmp_path / "restore", store)

    assert store.verbs() == ["cat"]


# --------------------------------------------------------------------------- #
# push against the directory fake: immutability and allowed verbs
# --------------------------------------------------------------------------- #


def test_second_push_does_not_change_an_existing_parquet_object(tmp_path: Path) -> None:
    store, bundle, _first = _pushed_store(tmp_path)
    parquet_remote = store.store / "parquet" / "raw" / "oi.parquet"
    before = parquet_remote.stat().st_mtime_ns

    remote.push_snapshot(bundle, store, now_utc=datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC))

    assert parquet_remote.stat().st_mtime_ns == before
    assert sorted(p.name for p in (store.store / "snapshots").iterdir()) == [
        "20261001T031500Z",
        "20261002T031500Z",
    ]


def test_push_never_issues_delete_sync_or_move_against_the_remote(tmp_path: Path) -> None:
    store, bundle, _first = _pushed_store(tmp_path)
    remote.push_snapshot(bundle, store, now_utc=datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC))

    assert set(store.verbs()) <= {"cat", "copy", "copyto", "cryptcheck"}


def test_push_after_the_staged_file_mtime_changed_is_not_an_immutable_violation(
    tmp_path: Path,
) -> None:
    """CR-01: same bytes with a new mtime (a restored host) must not fail the push."""
    store, bundle, _first = _pushed_store(tmp_path)
    staged = bundle / "parquet" / "raw" / "oi.parquet"
    later_ns = staged.stat().st_mtime_ns + 90 * 86_400 * 1_000_000_000
    os.utime(staged, ns=(later_ns, later_ns))

    snap = remote.push_snapshot(bundle, store, now_utc=datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC))

    assert snap == "20261002T031500Z"


def test_backup_and_push_after_a_restore_succeeds(tmp_path: Path) -> None:
    """CR-01 end to end: backup, push, pull, restore, backup again, push again."""
    source = tmp_path / "raw"
    source.mkdir()
    (source / "oi.parquet").write_bytes(b"BBB" * 100)
    old_ns = 1_700_000_000 * 1_000_000_000
    os.utime(source / "oi.parquet", ns=(old_ns, old_ns))
    bundle = tmp_path / "bundle"
    backup_mod.backup(bundle_root=bundle, pg_dump_runner=_fake_dump, parquet_roots=[source])
    store = StoreRclone(tmp_path / "remote")
    store.init()
    remote.push_snapshot(bundle, store, now_utc=NOW)

    pulled = tmp_path / "pulled"
    remote.pull_snapshot(pulled, store)
    restored_root = tmp_path / "restored"
    restored = restored_root / "raw"  # same root name as the source: same remote object paths
    backup_mod.restore_bundle(
        pulled,
        parquet_target=restored,
        database_url=None,
        force=False,
        skip_db=True,
        pg_restore_runner=lambda _dump, _target: None,
        migrate_runner=lambda _url: None,
    )
    bundle2 = tmp_path / "bundle2"
    backup_mod.backup(bundle_root=bundle2, pg_dump_runner=_fake_dump, parquet_roots=[restored])

    snap = remote.push_snapshot(bundle2, store, now_utc=datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC))

    assert snap == "20261002T031500Z"


def test_a_changed_parquet_file_makes_the_immutable_copy_fail(tmp_path: Path) -> None:
    store, bundle, _first = _pushed_store(tmp_path)
    (store.store / "parquet" / "raw" / "oi.parquet").write_bytes(b"different")

    with pytest.raises(RemoteError, match="exit 6"):
        remote.push_snapshot(bundle, store, now_utc=datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC))


# --------------------------------------------------------------------------- #
# scheduled
# --------------------------------------------------------------------------- #


def test_scheduled_runs_backup_verify_push_then_retention_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    (source / "oi.parquet").write_bytes(b"AAA" * 50)
    store = StoreRclone(tmp_path / "remote")
    store.init()
    events: list[str] = []

    def dump(out: Path) -> Path:
        events.append(f"pg_dump(rclone_calls={len(store.calls)})")
        return _fake_dump(out)

    real_verify = remote.verify_bundle

    def spy_verify(root: Path) -> list[str]:
        events.append(f"verify(rclone_calls={len(store.calls)})")
        return real_verify(root)

    monkeypatch.setattr(remote, "verify_bundle", spy_verify)

    code = main(
        ["scheduled", "--bundle-root", str(tmp_path / "bundle"), "--parquet-roots", str(source)],
        pg_dump_runner=dump,
        rclone_runner=store,
        now_utc=NOW,
    )

    assert code == 0
    assert events[0] == "pg_dump(rclone_calls=0)"  # pg_dump first, nothing on the remote yet
    assert events[1] == "verify(rclone_calls=0)"
    verbs = store.verbs()
    assert verbs.index("cryptcheck") < verbs.index("lsf")  # retention lists only after cryptcheck
    assert f"scheduled-OK snapshot={SNAP}" in capsys.readouterr().out


def test_scheduled_stops_before_retention_when_cryptcheck_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    (source / "oi.parquet").write_bytes(b"AAA" * 50)

    class BadCheck(StoreRclone):
        def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
            if argv[0] == "cryptcheck":
                self.calls.append(list(argv))
                return RcloneResult(1, "", "2 differences found")
            return super().__call__(argv, env)

    store = BadCheck(tmp_path / "remote")
    store.init()

    code = main(
        ["scheduled", "--bundle-root", str(tmp_path / "bundle"), "--parquet-roots", str(source)],
        pg_dump_runner=_fake_dump,
        rclone_runner=store,
        now_utc=NOW,
    )

    assert code == 1
    assert "purge" not in store.verbs()
    assert "lsf" not in store.verbs()
    assert "cryptcheck" in capsys.readouterr().err


def test_scheduled_default_bundle_root_is_data_backup_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "t.parquet").write_bytes(b"x" * 20)
    store = StoreRclone(tmp_path / "remote")
    store.init()

    code = main(["scheduled"], pg_dump_runner=_fake_dump, rclone_runner=store, now_utc=NOW)

    assert code == 0
    assert (tmp_path / "data" / "backup" / "bundle" / "manifest.json").is_file()


def test_legacy_subcommand_defaults_stay_at_data_backup() -> None:
    assert backup_mod.DEFAULT_BUNDLE_ROOT == Path("data") / "backup"
    assert backup_mod.DEFAULT_STAGING_BUNDLE_ROOT == Path("data") / "backup" / "bundle"


# --------------------------------------------------------------------------- #
# drill-remote
# --------------------------------------------------------------------------- #

DRILL_URL = "postgresql+psycopg://trading:placeholder-pw@db:5432/trading"
SCRATCH_DB = "trading_drill_20261001031500"


class FakeDrillOps:
    def __init__(self, *, source_rows: int = 3, scratch_rows: int = 3) -> None:
        self.events: list[str] = []
        self.source_rows = source_rows
        self.scratch_rows = scratch_rows
        self.fail_on_count = False

    def create_database(self, url: str, name: str) -> None:
        self.events.append(f"create:{name}")

    def drop_database(self, url: str, name: str) -> None:
        self.events.append(f"drop:{name}")

    def count_watermarks(self, url: str) -> int:
        self.events.append(f"count:{url.rsplit('/', 1)[-1]}")
        if self.fail_on_count:
            raise RuntimeError("count exploded")
        return self.scratch_rows if SCRATCH_DB in url else self.source_rows

    def as_ops(self) -> remote.DrillDatabaseOps:
        return remote.DrillDatabaseOps(
            create_database=self.create_database,
            drop_database=self.drop_database,
            count_watermarks=self.count_watermarks,
        )


def _drill(
    tmp_path: Path, ops: FakeDrillOps, monkeypatch: pytest.MonkeyPatch, restored: list[Any]
) -> tuple[int, StoreRclone]:
    source = tmp_path / "raw"
    source.mkdir(exist_ok=True)
    (source / "oi.parquet").write_bytes(b"AAA" * 50)
    store = StoreRclone(tmp_path / "remote")
    store.init()
    monkeypatch.setenv("DATABASE_URL_SYNC", DRILL_URL)

    def fake_restore(dump: Path, target: backup_mod.LibpqTarget) -> None:
        restored.append((dump, target.url_without_password, dict(target.env)))

    code = main(
        [
            "drill-remote",
            "--bundle-root",
            str(tmp_path / "bundle"),
            "--scratch-root",
            str(tmp_path / "drill"),
            "--parquet-roots",
            str(source),
        ],
        pg_dump_runner=_fake_dump,
        pg_restore_runner=fake_restore,
        data_probe=lambda url: [],
        rclone_runner=store,
        now_utc=NOW,
        drill_ops=ops.as_ops(),
    )
    return code, store


def test_drill_remote_restores_into_a_scratch_database_and_drops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ops = FakeDrillOps()
    restored: list[Any] = []

    code, store = _drill(tmp_path, ops, monkeypatch, restored)

    assert code == 0
    assert f"drill-remote-OK snapshot={SNAP}" in capsys.readouterr().out
    assert ops.events[0] == f"create:{SCRATCH_DB}"
    assert ops.events[-1] == f"drop:{SCRATCH_DB}"
    assert ops.events.count(f"count:{SCRATCH_DB}") == 1
    dump, url, env = restored[0]
    assert dump == tmp_path / "drill" / "pg.dump"
    assert url == f"postgresql://trading@db:5432/{SCRATCH_DB}"
    assert env == {"PGPASSWORD": "placeholder-pw"}
    assert backup_mod.verify_bundle(tmp_path / "drill") == []
    verbs = store.verbs()
    assert verbs.index("cryptcheck") < verbs.index("copy", verbs.index("cryptcheck"))


def test_drill_remote_fails_on_unequal_watermark_counts_and_still_drops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ops = FakeDrillOps(source_rows=3, scratch_rows=2)

    code, _store = _drill(tmp_path, ops, monkeypatch, [])

    assert code == 1
    assert f"drop:{SCRATCH_DB}" in ops.events
    assert "source=3 restored=2" in capsys.readouterr().err


def test_drill_remote_drops_the_scratch_database_when_a_step_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ops = FakeDrillOps()
    ops.fail_on_count = True

    code, _store = _drill(tmp_path, ops, monkeypatch, [])

    assert code == 1
    assert ops.events[-1] == f"drop:{SCRATCH_DB}"
    assert "count exploded" in capsys.readouterr().err


def test_drill_remote_refuses_without_a_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    code = main(
        ["drill-remote", "--scratch-root", str(tmp_path / "drill")],
        rclone_runner=StoreRclone(tmp_path / "remote"),
        now_utc=NOW,
    )

    assert code == 1
    assert "DATABASE_URL" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["bad-name", "1abc", "has space", "x;drop", ""])
def test_scratch_database_name_rejects_non_identifiers(name: str) -> None:
    with pytest.raises(RemoteError):
        remote.scratch_database_name(name, NOW)


def test_scratch_database_name_rejects_names_over_63_characters() -> None:
    with pytest.raises(RemoteError, match="63"):
        remote.scratch_database_name("a" * 50, NOW)
    assert remote.scratch_database_name("trading", NOW) == SCRATCH_DB
