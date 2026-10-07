"""Tests for the rclone off-host backup adapter (Phase 13.1 plan 08, D-12 / D-17).

No rclone binary and no network: every rclone call goes through an injected fake runner that
records argv. The real binary is exercised in tests/test_docker_backup_remote.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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
PARQUET_REMOTE = "BACKUPS3CRYPT:parquet"
LATER = datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC)
LATEST = datetime(2026, 10, 3, 3, 15, 0, tzinfo=UTC)
SNAP2 = "20261002T031500Z"
SNAP3 = "20261003T031500Z"
HEAD_DIFFERENT = "parquet push refused: path(s) already published with different content"
HEAD_ORPHAN = (
    "parquet push refused: remote object(s) differ from the local file(s) "
    "and no complete snapshot names them"
)
HEAD_VERIFY = "parquet verification failed"

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
        self.lists: list[tuple[str, list[str]]] = []
        self.sentinel = sentinel or RcloneResult(0, remote.SENTINEL_CONTENT, "")
        self.overrides = dict(overrides or {})

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        self.calls.append(list(argv))
        if "--files-from-raw" in argv:  # the adapter deletes the list file after the call
            listing = Path(argv[list(argv).index("--files-from-raw") + 1])
            self.lists.append((argv[0], listing.read_text(encoding="utf-8").splitlines()))
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


def _normalised(call: Sequence[str]) -> list[str]:
    """A recorded argv with the temporary ``--files-from-raw`` list file replaced by a marker."""
    out: list[str] = []
    previous = ""
    for arg in call:
        out.append("<LIST>" if previous == "--files-from-raw" else arg)
        previous = arg
    return out


def test_push_cli_runs_sentinel_then_parquet_then_snapshot_then_cryptcheck(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _make_bundle(tmp_path)
    fake = FakeRclone()
    root = str(bundle.resolve())
    parquet = str(Path(root) / "parquet")
    snap_remote = f"BACKUPS3CRYPT:snapshots/{SNAP}"

    code = main(["push", "--bundle-root", str(bundle)], rclone_runner=fake, now_utc=NOW)

    assert code == 0
    assert f"push-OK snapshot={SNAP}" in capsys.readouterr().out
    assert [_normalised(call) for call in fake.calls] == [
        ["cat", SENTINEL_ARG],
        ["lsf", "--files-only", "-R", "--max-depth", "2", "BACKUPS3CRYPT:snapshots/"],
        ["lsf", "-R", "--files-only", "BACKUPS3CRYPT:parquet/"],
        ["copy", parquet, "BACKUPS3CRYPT:parquet", "--files-from-raw", "<LIST>", "--immutable"],
        ["copyto", str(Path(root) / "pg.dump"), f"{snap_remote}/pg.dump", "--immutable"],
        ["cryptcheck", parquet, "BACKUPS3CRYPT:parquet", "--one-way"],
        ["cryptcheck", root, snap_remote, "--include", "/pg.dump"],
        [
            "copyto",
            str(Path(root) / "manifest.json"),
            f"{snap_remote}/manifest.json",
            "--immutable",
        ],
        ["cryptcheck", root, snap_remote, "--include", "/manifest.json"],
    ]
    assert fake.lists == [("copy", ["raw/oi.parquet"])]


def test_push_uploads_manifest_last_so_a_snapshot_is_never_complete_before_its_files(
    tmp_path: Path,
) -> None:
    bundle = _make_bundle(tmp_path)
    fake = FakeRclone()

    remote.push_snapshot(bundle, fake, now_utc=NOW)

    targets = [call[2] for call in fake.calls if call[0] in {"copy", "copyto"}]
    assert targets[0] == "BACKUPS3CRYPT:parquet"
    assert targets[-1].endswith("/manifest.json")
    checks = [i for i, call in enumerate(fake.calls) if call[0] == "cryptcheck"]
    manifest_put = next(
        i for i, call in enumerate(fake.calls) if call[0] == "copyto" and "manifest.json" in call[2]
    )
    assert len(checks) == 3
    assert checks[0] < checks[1] < manifest_put < checks[2]  # tree and pg.dump are checked first


def test_push_skips_parquet_copy_when_bundle_has_no_parquet(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path, with_parquet=False)
    shutil.rmtree(bundle / "parquet")  # an empty root leaves an empty directory behind
    fake = FakeRclone()

    remote.push_snapshot(bundle, fake, now_utc=NOW)

    local_parquet = str(bundle.resolve() / "parquet")
    for call in fake.calls:  # no Parquet listing, upload or check of any kind
        assert not any(arg.startswith(PARQUET_REMOTE) or arg == local_parquet for arg in call)
        assert "--files-from-raw" not in call
    assert fake.verbs().count("cryptcheck") == 2  # pg.dump and manifest only


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


def test_init_remote_treats_exit_0_with_empty_output_as_no_sentinel() -> None:
    # `rclone cat` of a missing object exits 0 with no output (the path reads as an empty dir).
    state = {"written": False}

    class Fresh(FakeRclone):
        def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
            if list(argv)[:2] == ["cat", SENTINEL_ARG]:
                self.calls.append(list(argv))
                content = remote.SENTINEL_CONTENT if state["written"] else ""
                return RcloneResult(0, content, "")
            if argv[0] == "copyto" and argv[2] == SENTINEL_ARG:
                self.calls.append(list(argv))
                state["written"] = True
                return RcloneResult(0, "", "")
            return super().__call__(argv, env)

    fake = Fresh()

    assert remote.init_sentinel(fake, raw_remote="BACKUPS3:b") is True

    assert "copyto" in fake.verbs()


def test_init_remote_exit_0_empty_still_refuses_a_non_empty_bucket() -> None:
    fake = FakeRclone(
        sentinel=RcloneResult(0, "", ""),
        overrides={"lsf": RcloneResult(0, "h3l2k5/\n", "")},
    )

    with pytest.raises(RemoteError, match="refusing --init-remote"):
        remote.init_sentinel(fake, raw_remote="BACKUPS3:b")

    assert "copyto" not in fake.verbs()


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
    """Interprets the argv the adapter emits against a directory standing in for the remote.

    ``cryptcheck`` is a hash-aware model of what the real rclone 1.75.1 was proven to do on a
    crypt remote over an S3 double, see
    ``.planning/quick/261007-onb-cr-01-replacement-d064-parquet-push-mani/261007-onb-proof-output.txt``
    (labels a1 a2 a3 b1 to b4 c1 c2 d1 d2 e1 s1 s2 and the FINDINGS block): it compares the
    SHA-256 of the bytes, never the size alone and never the modification time; a changed file, a
    file of another size and a file missing on the remote fail with exit 1 and an ``ERROR :
    <path>: ...`` line; a remote-only file fails unless ``--one-way`` is given; ``--include`` and
    ``--files-from-raw`` restrict the check to the named paths. ``copy`` honours
    ``--files-from-raw`` and ``--immutable`` (exit 6 when an existing object would change), and
    ``deletefile`` exits 4 for an object that does not exist. ``self.lists`` records the content
    of every ``--files-from-raw`` list file at call time (the adapter deletes it afterwards).
    """

    def __init__(self, store: Path) -> None:
        self.store = store
        self.calls: list[list[str]] = []
        self.lists: list[tuple[str, list[str]]] = []
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

    def _listed(self, argv: Sequence[str]) -> list[str] | None:
        """The paths of the ``--files-from-raw`` list file (read now), or None without the flag."""
        files_from = self._flag_values(argv, "--files-from-raw")
        if not files_from:
            return None
        wanted = Path(files_from[0]).read_text(encoding="utf-8").splitlines()
        self.lists.append((argv[0], list(wanted)))
        return wanted

    def _put(self, source: Path, target: Path, *, immutable: bool) -> RcloneResult:
        """Model rclone's default comparison, which ``--immutable`` makes strict."""
        if target.exists():
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

    @staticmethod
    def _files(root: Path) -> set[str]:
        if not root.is_dir():
            return set()
        return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}

    def _cryptcheck(self, argv: Sequence[str]) -> RcloneResult:
        local, remote_dir = Path(argv[1]), self._path(argv[2])
        scope: set[str] | None = None
        includes = [name.lstrip("/") for name in self._flag_values(argv, "--include")]
        if includes:
            scope = set(includes)
        listed = self._listed(argv)
        if listed is not None:
            scope = set(listed) if scope is None else scope & set(listed)
        mine, theirs = self._files(local), self._files(remote_dir)
        if scope is not None:
            mine, theirs = mine & scope, theirs & scope
        errors: list[str] = []
        for rel in sorted(mine):
            if rel not in theirs:
                errors.append(f"ERROR : {rel}: file not in Encrypted drive 'BACKUPS3CRYPT{{x}}:'")
                continue
            ours, other = (local / rel).read_bytes(), (remote_dir / rel).read_bytes()
            if len(ours) != len(other):
                errors.append(f"ERROR : {rel}: sizes differ")
            elif hashlib.sha256(ours).digest() != hashlib.sha256(other).digest():
                errors.append(f"ERROR : {rel}: hashes differ (BACKUPS3CRYPT{{x}}:) vs (local:)")
        if "--one-way" not in argv:
            errors.extend(
                f"ERROR : {rel}: file not in Local file system" for rel in sorted(theirs - mine)
            )
        if not errors:
            return RcloneResult(0, "", "")
        summary = f"NOTICE: Failed to cryptcheck: {len(errors)} differences found"
        return RcloneResult(1, "", "\n".join([*errors, summary]))

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        self.calls.append(list(argv))
        verb = argv[0]
        immutable = "--immutable" in argv
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
            if "-R" in argv:  # recursive file listing, relative to the listed directory
                files = sorted(
                    p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()
                )
                return RcloneResult(0, "".join(f"{name}\n" for name in files), "")
            dirs = sorted(d.name for d in path.iterdir() if d.is_dir())
            return RcloneResult(0, "".join(f"{name}/\n" for name in dirs), "")
        if verb == "copyto":
            return self._put(Path(argv[1]), self._path(argv[2]), immutable=immutable)
        if verb == "copy":
            source, dest = argv[1], argv[2]
            listed = self._listed(argv)
            if source.startswith(CRYPT):  # remote -> local
                src_dir = self._path(source)
                if listed is not None:
                    candidates = [src_dir / rel for rel in listed if (src_dir / rel).is_file()]
                else:
                    candidates = [p for p in src_dir.rglob("*") if p.is_file()]
                for file in candidates:
                    out = Path(dest) / file.relative_to(src_dir)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, out)  # rclone keeps the remote modtime on download
                return RcloneResult(0, "", "")
            if listed is not None:  # local -> remote, only the listed files
                uploads = [Path(source) / rel for rel in listed if (Path(source) / rel).is_file()]
            else:
                uploads = [p for p in Path(source).rglob("*") if p.is_file()]
            for file in uploads:
                target = self._path(dest) / file.relative_to(source)
                outcome = self._put(file, target, immutable=immutable)
                if outcome.returncode != 0:
                    return outcome
            return RcloneResult(0, "", "")
        if verb == "cryptcheck":
            return self._cryptcheck(argv)
        if verb == "deletefile":
            path = self._path(argv[1])
            if not path.is_file():
                return RcloneResult(4, "", f"Failed to deletefile: {argv[1]}: object not found")
            path.unlink()
            parent = path.parent
            while parent != self.store and not any(parent.iterdir()):  # S3 has no empty dirs
                parent.rmdir()
                parent = parent.parent
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


@dataclass
class _Hook:
    """One fault for ``FaultStore``: fires on the first call that ``match`` accepts.

    ``forced`` results are returned INSTEAD of performing the call (one per match, the hook
    stays until they are used up); otherwise the call is performed, then ``after`` runs, then
    ``crash`` is raised or ``override`` replaces the result.
    """

    match: Callable[[Sequence[str]], bool]
    after: Callable[[], None] | None = None
    forced: list[RcloneResult] = field(default_factory=list)
    override: RcloneResult | None = None
    crash: BaseException | None = None


class FaultStore(StoreRclone):
    """``StoreRclone`` plus injected faults: corrupt or delete objects, force a result, crash."""

    def __init__(self, store: Path) -> None:
        super().__init__(store)
        self.hooks: list[_Hook] = []

    def hook(self, match: Callable[[Sequence[str]], bool], **kwargs: Any) -> _Hook:
        created = _Hook(match, **kwargs)
        self.hooks.append(created)
        return created

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        for hook in list(self.hooks):
            if not hook.match(argv):
                continue
            if hook.forced:
                self.calls.append(list(argv))
                outcome = hook.forced.pop(0)
                if not hook.forced:
                    self.hooks.remove(hook)
                return outcome
            self.hooks.remove(hook)
            real = super().__call__(argv, env)
            if hook.after is not None:
                hook.after()
            if hook.crash is not None:
                raise hook.crash
            return hook.override or real
        return super().__call__(argv, env)


class _Crash(Exception):
    """A simulated process death between two rclone calls (never caught by the adapter)."""


def _call_with(verb: str, *elements: str) -> Callable[[Sequence[str]], bool]:
    """Match a call of ``verb`` whose argv contains every one of ``elements`` exactly."""

    def match(argv: Sequence[str]) -> bool:
        return argv[0] == verb and all(element in argv for element in elements)

    return match


def _corrupt(store: StoreRclone, rel: str) -> None:
    """Change a remote object out of band: same size, different bytes, same modification time."""
    path = store.store / rel
    stat = path.stat()
    path.write_bytes(bytes(byte ^ 0x01 for byte in path.read_bytes()))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))


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
    store.calls.clear()

    remote.push_snapshot(bundle, store, now_utc=datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC))

    assert parquet_remote.stat().st_mtime_ns == before
    assert "copy" not in store.verbs()  # the known path is skipped, not offered to rclone
    assert sorted(p.name for p in (store.store / "snapshots").iterdir()) == [
        "20261001T031500Z",
        "20261002T031500Z",
    ]


def test_push_never_issues_delete_sync_or_move_against_the_remote(tmp_path: Path) -> None:
    store, bundle, _first = _pushed_store(tmp_path)
    remote.push_snapshot(bundle, store, now_utc=datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC))

    assert set(store.verbs()) <= {"cat", "copy", "copyto", "cryptcheck", "lsf"}


def test_push_after_the_staged_file_mtime_changed_is_not_an_immutable_violation(
    tmp_path: Path,
) -> None:
    """CR-01: same bytes with a new mtime (a restored host) must not fail the push."""
    store, bundle, _first = _pushed_store(tmp_path)
    staged = bundle / "parquet" / "raw" / "oi.parquet"
    later_ns = staged.stat().st_mtime_ns + 90 * 86_400 * 1_000_000_000
    os.utime(staged, ns=(later_ns, later_ns))
    store.calls.clear()

    snap = remote.push_snapshot(bundle, store, now_utc=datetime(2026, 10, 2, 3, 15, 0, tzinfo=UTC))

    assert snap == "20261002T031500Z"
    assert "copy" not in store.verbs()


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


def test_pull_skips_a_half_pushed_newest_snapshot_for_the_newest_complete_one(
    tmp_path: Path,
) -> None:
    """WR-01: a snapshot whose manifest never arrived is not 'the newest'."""
    store, bundle, first = _pushed_store(tmp_path)
    half = store.store / "snapshots" / "20261005T031500Z"
    half.mkdir()
    (half / "pg.dump").write_bytes((bundle / "pg.dump").read_bytes())  # manifest never uploaded

    assert remote.pull_snapshot(tmp_path / "a", store) == first
    with pytest.raises(RemoteError, match="incomplete"):
        remote.pull_snapshot(tmp_path / "b", store, snapshot="20261005T031500Z")


def test_retention_keeps_the_complete_snapshot_over_a_half_pushed_one_of_the_same_day(
    tmp_path: Path,
) -> None:
    """WR-01: the incomplete later snapshot of a day must not displace the good one."""
    store, bundle, first = _pushed_store(tmp_path)  # 2026-10-01 03:15, complete
    half = store.store / "snapshots" / "20261001T230000Z"  # same day, later, no manifest
    half.mkdir()
    (half / "pg.dump").write_bytes((bundle / "pg.dump").read_bytes())

    report = remote.apply_retention(store, dry_run=False)

    assert first in report.kept
    assert (store.store / "snapshots" / first / "manifest.json").is_file()
    assert report.deleted == ()  # the half push is newer than every complete one: left alone
    assert half.is_dir()


def test_retention_purges_an_incomplete_snapshot_older_than_a_complete_one(
    tmp_path: Path,
) -> None:
    store, bundle, first = _pushed_store(tmp_path)
    garbage = store.store / "snapshots" / "20260901T031500Z"
    garbage.mkdir()
    (garbage / "pg.dump").write_bytes((bundle / "pg.dump").read_bytes())

    report = remote.apply_retention(store, dry_run=False)

    assert report.deleted == ("20260901T031500Z",)
    assert not garbage.exists()
    assert (store.store / "snapshots" / first / "manifest.json").is_file()


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
    last = {
        verb: max(i for i, v in enumerate(verbs) if v == verb) for verb in ("lsf", "cryptcheck")
    }
    assert last["cryptcheck"] < last["lsf"]  # retention lists only after the last cryptcheck
    first_write = min(i for i, v in enumerate(verbs) if v in {"copy", "copyto"})
    assert verbs.index("lsf") < first_write  # the push reads the remote before it writes
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
    failing = store.verbs().index("cryptcheck")
    assert all(call[0] not in {"lsf", "purge"} for call in store.calls[failing:])
    assert list((store.store / "snapshots").rglob("manifest.json")) == []
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


# --------------------------------------------------------------------------- #
# CR-01 replacement (D064): manifest SHA-256 comparison, cryptcheck before the manifest
# --------------------------------------------------------------------------- #

FILES: dict[str, bytes] = {"interval=1m/a.parquet": b"A" * 50, "interval=1m/b.parquet": b"B" * 60}
NEW_FILE = {"interval=1m/c.parquet": b"C" * 70}
A_PATH = "raw/interval=1m/a.parquet"
H1, H2, H3 = "1" * 64, "2" * 64, "3" * 64


def _bundle(tmp_path: Path, name: str, files: Mapping[str, bytes]) -> Path:
    """A bundle whose source root is named ``raw``, so the Parquet keys are ``parquet/raw/...``."""
    source = tmp_path / name / "raw"
    source.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        target = source / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    bundle = tmp_path / f"{name}-bundle"
    backup_mod.backup(bundle_root=bundle, pg_dump_runner=_fake_dump, parquet_roots=[source])
    return bundle


def _fresh(tmp_path: Path, cls: type[StoreRclone] = StoreRclone) -> Any:
    store = cls(tmp_path / "remote")
    store.init()
    return store


def _remote_parquet(store: StoreRclone) -> dict[str, tuple[bytes, int]]:
    root = store.store / "parquet"
    if not root.is_dir():
        return {}
    return {
        p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def _writes(store: StoreRclone, start: int = 0) -> list[list[str]]:
    mutating = {"copy", "copyto", "deletefile", "delete", "purge", "sync", "move", "moveto"}
    return [call for call in store.calls[start:] if call[0] in mutating]


def _manifest_object(snap: str) -> str:
    return f"snapshots/{snap}/manifest.json"


class _ManifestRunner:
    """Answers ``cat`` of snapshot manifests from a mapping of snapshot id to a result."""

    def __init__(self, manifests: Mapping[str, RcloneResult]) -> None:
        self.manifests = dict(manifests)
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        self.calls.append(list(argv))
        assert argv[0] == "cat", argv
        snap = argv[1].split("/")[1]
        return self.manifests[snap]


def _json_result(payload: object) -> RcloneResult:
    return RcloneResult(0, json.dumps(payload), "")


# -- pure logic ------------------------------------------------------------------------------ #


def test_classify_same_hash_is_skipped() -> None:
    plan = remote.classify_parquet_paths({"raw/a": H1}, {"raw/a": frozenset({H1})}, {"raw/a"})

    assert plan == remote.ParquetPushPlan(skip=("raw/a",), upload=(), adopt=(), conflicts=())


@pytest.mark.parametrize("present", [True, False])
def test_classify_known_with_a_different_hash_is_a_hard_failure_whatever_the_size(
    present: bool,
) -> None:
    plan = remote.classify_parquet_paths(
        {"raw/a": H2}, {"raw/a": frozenset({H1})}, {"raw/a"} if present else set()
    )

    assert plan.conflicts == (("raw/a", "different content"),)
    assert plan.skip == plan.upload == plan.adopt == ()


def test_classify_new_path_absent_from_the_remote_is_uploaded() -> None:
    plan = remote.classify_parquet_paths({"raw/b": H1, "raw/a": H2}, {}, set())

    assert plan.upload == ("raw/a", "raw/b")
    assert plan.skip == plan.adopt == plan.conflicts == ()


def test_classify_new_path_present_on_the_remote_is_an_adoption_candidate() -> None:
    plan = remote.classify_parquet_paths({"raw/a": H1}, {}, {"raw/a", "raw/other"})

    assert plan.adopt == ("raw/a",)
    assert plan.skip == plan.upload == plan.conflicts == ()


def test_classify_paths_two_manifests_disagree_about_is_a_hard_failure() -> None:
    known = {"raw/a": frozenset({H1, H2})}

    for local_hash in (H1, H2, H3):
        plan = remote.classify_parquet_paths({"raw/a": local_hash}, known, {"raw/a"})
        assert plan.conflicts == (("raw/a", "manifests disagree"),)
        assert plan.skip == plan.upload == plan.adopt == ()


def test_local_parquet_hashes_keeps_only_parquet_keys_without_the_prefix() -> None:
    manifest = {"pg.dump": H1, "parquet/raw/a": H2, "parquet/raw/x=1/b": H3}

    assert remote.local_parquet_hashes(manifest) == {"raw/a": H2, "raw/x=1/b": H3}


@pytest.mark.parametrize("name", ["raw/a\nb", "raw/a\rb"])
def test_local_parquet_hashes_refuses_a_path_with_a_line_break(name: str) -> None:
    with pytest.raises(RemoteError, match="line break"):
        remote.local_parquet_hashes({f"parquet/{name}": H1})


def test_known_parquet_hashes_is_the_union_of_every_complete_manifest_and_ignores_pg_dump() -> None:
    runner = _ManifestRunner(
        {
            "20260101T000000Z": _json_result(
                {"pg.dump": H3, "parquet/raw/a": H1, "parquet/raw/b": H2}
            ),
            "20260102T000000Z": _json_result(
                {"pg.dump": H1, "parquet/raw/b": H2, "parquet/raw/c": H3}
            ),
            "20260103T000000Z": _json_result({"pg.dump": H2, "parquet/raw/a": H3}),
        }
    )

    known = remote.known_parquet_hashes(runner, sorted(runner.manifests))

    assert known == {
        "raw/a": frozenset({H1, H3}),
        "raw/b": frozenset({H2}),
        "raw/c": frozenset({H3}),
    }
    assert [call[1] for call in runner.calls] == [
        f"BACKUPS3CRYPT:snapshots/{snap}/manifest.json" for snap in sorted(runner.manifests)
    ]


@pytest.mark.parametrize(
    "result",
    [
        RcloneResult(1, "", "boom"),
        RcloneResult(3, "", "directory not found"),
        RcloneResult(0, "not json at all", ""),
        RcloneResult(0, json.dumps(["parquet/raw/a"]), ""),
        RcloneResult(0, json.dumps({"parquet/raw/a": 7}), ""),
        RcloneResult(0, json.dumps({"parquet/../escape": H1}), ""),
        RcloneResult(0, json.dumps({"/absolute": H1}), ""),
    ],
    ids=["exit1", "exit3", "not-json", "list", "non-str-value", "dotdot-key", "absolute-key"],
)
def test_known_parquet_hashes_refuses_an_unreadable_manifest(result: RcloneResult) -> None:
    runner = _ManifestRunner({"20260101T000000Z": result})

    with pytest.raises(
        RemoteError, match="unreadable manifest of complete snapshot 20260101T000000Z"
    ):
        remote.known_parquet_hashes(runner, ["20260101T000000Z"])


def test_a_remote_manifest_body_never_appears_in_the_error_text() -> None:
    runner = _ManifestRunner({"20260101T000000Z": RcloneResult(0, "SECRET-BODY-xyz {", "")})

    with pytest.raises(RemoteError) as excinfo:
        remote.known_parquet_hashes(runner, ["20260101T000000Z"])

    assert "SECRET-BODY-xyz" not in str(excinfo.value)


def test_remote_parquet_paths_reads_the_recursive_listing_and_treats_not_found_as_empty() -> None:
    listing = FakeRclone(overrides={"lsf": RcloneResult(0, "raw/a\nraw/x=1/b\n", "")})
    missing = FakeRclone(overrides={"lsf": RcloneResult(3, "", "directory not found")})
    broken = FakeRclone(overrides={"lsf": RcloneResult(1, "", "boom")})

    assert remote.remote_parquet_paths(listing) == frozenset({"raw/a", "raw/x=1/b"})
    assert listing.calls == [["lsf", "-R", "--files-only", "BACKUPS3CRYPT:parquet/"]]
    assert remote.remote_parquet_paths(missing) == frozenset()
    with pytest.raises(RemoteError, match="exit 1"):
        remote.remote_parquet_paths(broken)


# -- Cases A to I against the directory fake ---------------------------------------------------- #


@pytest.mark.parametrize("new_mtime", [False, True], ids=["same-mtime", "new-mtime"])
def test_case_a_same_path_same_size_same_content_is_skipped_without_any_upload(
    tmp_path: Path, new_mtime: bool
) -> None:
    store = _fresh(tmp_path)
    remote.push_snapshot(_bundle(tmp_path, "one", FILES), store, now_utc=NOW)
    again = _bundle(tmp_path, "two", FILES)
    if new_mtime:  # a host restored months later: same bytes, other modification times
        for staged in (again / "parquet").rglob("*.parquet"):
            later_ns = staged.stat().st_mtime_ns + 90 * 86_400 * 1_000_000_000
            os.utime(staged, ns=(later_ns, later_ns))
    before = _remote_parquet(store)
    store.calls.clear()
    store.lists.clear()

    snap = remote.push_snapshot(again, store, now_utc=LATER)

    assert snap == SNAP2
    assert "copy" not in store.verbs()  # no Parquet upload of any kind
    assert store.lists == []  # nothing to adopt, nothing to upload
    assert _remote_parquet(store) == before  # bytes and modification times untouched


@pytest.mark.parametrize(
    "changed",
    [
        {"interval=1m/a.parquet": b"X" * 50, "interval=1m/b.parquet": b"B" * 60},
        {"interval=1m/a.parquet": b"A" * 50, "interval=1m/b.parquet": b"B" * 61},
    ],
    ids=["case-b-same-size", "case-c-different-size"],
)
def test_case_b_and_c_a_known_path_with_different_content_fails_hard_without_overwrite(
    tmp_path: Path, changed: Mapping[str, bytes]
) -> None:
    store = _fresh(tmp_path)
    remote.push_snapshot(_bundle(tmp_path, "one", FILES), store, now_utc=NOW)
    before = _remote_parquet(store)
    snapshots_before = sorted(p.name for p in (store.store / "snapshots").iterdir())
    store.calls.clear()

    with pytest.raises(RemoteError) as excinfo:
        remote.push_snapshot(_bundle(tmp_path, "two", changed), store, now_utc=LATER)

    text = str(excinfo.value)
    assert text.startswith(HEAD_DIFFERENT)
    assert "raw/interval=1m/" in text
    assert _remote_parquet(store) == before
    assert sorted(p.name for p in (store.store / "snapshots").iterdir()) == snapshots_before
    assert _writes(store) == []  # nothing was uploaded, nothing was removed


def test_case_b_names_at_most_five_paths_and_counts_the_rest(tmp_path: Path) -> None:
    many = {f"interval=1m/f{i}.parquet": f"{i}".encode() * 10 for i in range(8)}
    store = _fresh(tmp_path)
    remote.push_snapshot(_bundle(tmp_path, "one", many), store, now_utc=NOW)
    changed = {rel: data.upper() + b"!" for rel, data in many.items()}

    with pytest.raises(RemoteError) as excinfo:
        remote.push_snapshot(_bundle(tmp_path, "two", changed), store, now_utc=LATER)

    text = str(excinfo.value)
    assert text.count("raw/interval=1m/f") == 5
    assert "and 3 more" in text
    assert "raw/interval=1m/f0.parquet" in text  # the first path in sorted order


def test_case_d_a_new_path_is_uploaded_and_nothing_else_changes(tmp_path: Path) -> None:
    store = _fresh(tmp_path)
    remote.push_snapshot(_bundle(tmp_path, "one", FILES), store, now_utc=NOW)
    before = _remote_parquet(store)
    store.calls.clear()
    store.lists.clear()

    remote.push_snapshot(_bundle(tmp_path, "two", {**FILES, **NEW_FILE}), store, now_utc=LATER)

    assert store.lists == [("copy", ["raw/interval=1m/c.parquet"])]
    after = _remote_parquet(store)
    assert {rel: after[rel] for rel in before} == before  # earlier objects identical
    assert set(after) - set(before) == {"raw/interval=1m/c.parquet"}
    assert (store.store / _manifest_object(SNAP2)).is_file()


def test_case_e_orphan_identical_is_adopted_without_upload(tmp_path: Path) -> None:
    store = _fresh(tmp_path)
    remote.push_snapshot(_bundle(tmp_path, "one", FILES), store, now_utc=NOW)
    bundle = _bundle(tmp_path, "two", {**FILES, **NEW_FILE})
    orphan = store.store / "parquet" / "raw" / "interval=1m" / "c.parquet"
    orphan.write_bytes(NEW_FILE["interval=1m/c.parquet"])  # left by a push that died
    before = _remote_parquet(store)
    store.calls.clear()
    store.lists.clear()

    snap = remote.push_snapshot(bundle, store, now_utc=LATER)

    assert snap == SNAP2
    assert "copy" not in store.verbs()  # adopted, not uploaded again
    assert store.lists == [("cryptcheck", ["raw/interval=1m/c.parquet"])]
    assert _remote_parquet(store) == before
    assert (store.store / _manifest_object(SNAP2)).is_file()


def test_case_e_orphan_different_fails_hard_and_stays_untouched(tmp_path: Path) -> None:
    store = _fresh(tmp_path)
    remote.push_snapshot(_bundle(tmp_path, "one", FILES), store, now_utc=NOW)
    bundle = _bundle(tmp_path, "two", {**FILES, **NEW_FILE})
    orphan = store.store / "parquet" / "raw" / "interval=1m" / "c.parquet"
    orphan.write_bytes(b"Z" * 70)  # same size, other content
    before = _remote_parquet(store)
    store.calls.clear()

    with pytest.raises(RemoteError) as excinfo:
        remote.push_snapshot(bundle, store, now_utc=LATER)

    text = str(excinfo.value)
    assert text.startswith(HEAD_ORPHAN)
    assert "raw/interval=1m/c.parquet" in text
    assert _remote_parquet(store) == before
    assert _writes(store) == []
    assert not (store.store / "snapshots" / SNAP2).exists()


def test_case_e_interrupted_push_does_not_block_the_next_push(tmp_path: Path) -> None:
    store = _fresh(tmp_path, FaultStore)
    remote.push_snapshot(_bundle(tmp_path, "one", FILES), store, now_utc=NOW)
    bundle = _bundle(tmp_path, "two", {**FILES, **NEW_FILE})
    store.hook(_call_with("copy", "--files-from-raw"), crash=_Crash("killed after the upload"))

    with pytest.raises(_Crash):
        remote.push_snapshot(bundle, store, now_utc=LATER)

    orphan = store.store / "parquet" / "raw" / "interval=1m" / "c.parquet"
    assert orphan.is_file()  # the Parquet file went up, nothing else did
    assert not (store.store / "snapshots" / SNAP2).exists()
    assert remote.list_complete_snapshots(store) == [SNAP]
    before = _remote_parquet(store)
    store.calls.clear()

    assert remote.push_snapshot(bundle, store, now_utc=LATEST) == SNAP3

    assert "copy" not in store.verbs()
    assert _remote_parquet(store) == before
    assert remote.list_complete_snapshots(store) == [SNAP, SNAP3]


@pytest.mark.parametrize("target", ["parquet", "pg.dump"])
def test_case_f_upload_followed_by_cryptcheck_failure_leaves_the_snapshot_incomplete(
    tmp_path: Path, target: str
) -> None:
    store = _fresh(tmp_path, FaultStore)
    bundle = _bundle(tmp_path, "one", FILES)
    if target == "parquet":
        store.hook(
            _call_with("copy", "--files-from-raw"),
            after=lambda: _corrupt(store, f"parquet/{A_PATH}"),
        )
    else:
        store.hook(
            lambda argv: argv[0] == "copyto" and argv[2].endswith("/pg.dump"),
            after=lambda: _corrupt(store, f"snapshots/{SNAP}/pg.dump"),
        )

    with pytest.raises(RemoteError) as excinfo:
        remote.push_snapshot(bundle, store, now_utc=NOW)

    assert "exit 1" in str(excinfo.value)
    if target == "parquet":
        assert str(excinfo.value).startswith(HEAD_VERIFY)
    assert not (store.store / _manifest_object(SNAP)).exists()
    failing = max(
        i for i, c in enumerate(store.calls) if c[0] == "cryptcheck"
    )  # the push stops there
    assert not any(c[0] in {"copyto", "lsf", "purge"} for c in store.calls[failing + 1 :])
    assert all("manifest.json" not in " ".join(c) for c in store.calls[failing:])
    assert remote.list_complete_snapshots(store) == []


def test_case_g_remote_object_modified_after_upload_is_detected(tmp_path: Path) -> None:
    store, bundle, first = _pushed_store(tmp_path)
    _corrupt(store, "parquet/raw/oi.parquet")  # same size, same modification time
    store.calls.clear()

    with pytest.raises(RemoteError) as excinfo:
        remote.push_snapshot(bundle, store, now_utc=LATER)

    text = str(excinfo.value)
    assert text.startswith(HEAD_VERIFY)
    assert "exit 1" in text
    assert "raw/oi.parquet" in text
    assert "copy" not in store.verbs()  # no auto-heal: the object is not uploaded over
    assert not (store.store / _manifest_object(SNAP2)).exists()
    assert remote.list_complete_snapshots(store) == [first]


def test_case_h_remote_object_deleted_after_upload_is_detected(tmp_path: Path) -> None:
    store, bundle, first = _pushed_store(tmp_path)
    (store.store / "parquet" / "raw" / "oi.parquet").unlink()
    store.calls.clear()

    with pytest.raises(RemoteError) as excinfo:
        remote.push_snapshot(bundle, store, now_utc=LATER)

    text = str(excinfo.value)
    assert text.startswith(HEAD_VERIFY)
    assert "raw/oi.parquet" in text
    assert "copy" not in store.verbs()
    assert not (store.store / _manifest_object(SNAP2)).exists()
    assert remote.list_complete_snapshots(store) == [first]


def _corrupting_manifest_push(tmp_path: Path) -> tuple[FaultStore, Path, bytes]:
    store = _fresh(tmp_path, FaultStore)
    remote.push_snapshot(_bundle(tmp_path, "one", FILES), store, now_utc=NOW)
    sibling = (store.store / _manifest_object(SNAP)).read_bytes()
    bundle = _bundle(tmp_path, "two", {**FILES, **NEW_FILE})
    store.hook(
        lambda argv: argv[0] == "copyto" and argv[2].endswith(f"{SNAP2}/manifest.json"),
        after=lambda: _corrupt(store, _manifest_object(SNAP2)),
    )
    store.calls.clear()
    return store, bundle, sibling


def test_case_i_failed_manifest_check_removes_the_manifest_and_the_snapshot_stays_incomplete(
    tmp_path: Path,
) -> None:
    store, bundle, sibling = _corrupting_manifest_push(tmp_path)

    with pytest.raises(RemoteError) as excinfo:
        remote.push_snapshot(bundle, store, now_utc=LATER)

    assert str(excinfo.value).startswith(
        f"manifest verification failed: snapshot {SNAP2} left incomplete"
    )
    assert "exit 1" in str(excinfo.value)  # the original cryptcheck error is carried along
    assert [c for c in store.calls if c[0] == "deletefile"] == [
        ["deletefile", f"BACKUPS3CRYPT:{_manifest_object(SNAP2)}"]
    ]
    assert not (store.store / _manifest_object(SNAP2)).exists()
    assert (store.store / "snapshots" / SNAP2 / "pg.dump").is_file()
    assert remote.list_complete_snapshots(store) == [SNAP]  # never complete, sibling untouched
    assert (store.store / _manifest_object(SNAP)).read_bytes() == sibling


def test_case_i_manifest_upload_failure_also_removes_the_manifest(tmp_path: Path) -> None:
    store = _fresh(tmp_path, FaultStore)
    bundle = _bundle(tmp_path, "one", FILES)
    store.hook(
        lambda argv: argv[0] == "copyto" and argv[2].endswith("/manifest.json"),
        override=RcloneResult(1, "", "connection reset after the object was written"),
    )

    with pytest.raises(RemoteError, match=f"snapshot {SNAP} left incomplete") as excinfo:
        remote.push_snapshot(bundle, store, now_utc=NOW)

    assert "exit 1" in str(excinfo.value)
    assert not (store.store / _manifest_object(SNAP)).exists()
    assert remote.list_complete_snapshots(store) == []


def test_case_i_an_interrupt_during_manifest_publication_still_removes_the_manifest(
    tmp_path: Path,
) -> None:
    store = _fresh(tmp_path, FaultStore)
    bundle = _bundle(tmp_path, "one", FILES)
    store.hook(
        lambda argv: argv[0] == "copyto" and argv[2].endswith("/manifest.json"),
        crash=KeyboardInterrupt(),
    )

    with pytest.raises(KeyboardInterrupt):
        remote.push_snapshot(bundle, store, now_utc=NOW)

    assert not (store.store / _manifest_object(SNAP)).exists()
    assert remote.list_complete_snapshots(store) == []


@pytest.mark.parametrize("failures", [1, 2])
def test_case_i_one_failed_removal_is_retried_and_two_are_reported_with_the_manual_path(
    tmp_path: Path, failures: int
) -> None:
    store, bundle, _sibling = _corrupting_manifest_push(tmp_path)
    store.hook(
        _call_with("deletefile"),
        forced=[RcloneResult(1, "", "Failed to deletefile: boom")] * failures,
    )

    with pytest.raises(RemoteError) as excinfo:
        remote.push_snapshot(bundle, store, now_utc=LATER)

    text = str(excinfo.value)
    assert len([c for c in store.calls if c[0] == "deletefile"]) == 2
    manifest_path = (store.store / _manifest_object(SNAP2)).exists()
    if failures == 1:
        assert text.startswith(f"manifest verification failed: snapshot {SNAP2} left incomplete")
        assert not manifest_path
    else:
        assert text.startswith(
            f"manifest verification failed AND the manifest of snapshot {SNAP2} "
            "could not be removed"
        )
        assert f"snapshots/{SNAP2}/manifest.json" in text
        assert manifest_path  # still there: the operator removes it by hand


def test_deletefile_is_only_ever_issued_for_the_new_snapshot_manifest(tmp_path: Path) -> None:
    store, bundle, sibling = _corrupting_manifest_push(tmp_path)
    store.hook(_call_with("deletefile"), forced=[RcloneResult(1, "", "boom")])

    with pytest.raises(RemoteError):
        remote.push_snapshot(bundle, store, now_utc=LATER)

    deletes = [c for c in store.calls if c[0] == "deletefile"]
    assert deletes and all(
        c == ["deletefile", f"BACKUPS3CRYPT:{_manifest_object(SNAP2)}"] for c in deletes
    )
    assert (store.store / _manifest_object(SNAP)).read_bytes() == sibling


# -- guards ------------------------------------------------------------------------------------ #


def test_snapshot_id_collision_is_refused_before_any_write(tmp_path: Path) -> None:
    store, bundle, first = _pushed_store(tmp_path)
    manifest_before = (store.store / _manifest_object(first)).read_bytes()
    before = _remote_parquet(store)
    store.calls.clear()

    with pytest.raises(RemoteError, match=f"snapshot id {first} already exists on the remote"):
        remote.push_snapshot(bundle, store, now_utc=NOW)

    assert _writes(store) == []
    assert "cryptcheck" not in store.verbs()
    assert (store.store / _manifest_object(first)).read_bytes() == manifest_before
    assert _remote_parquet(store) == before


@pytest.mark.parametrize(
    ("failing", "pattern"),
    [
        ("complete-listing", r"rclone lsf failed \(exit 1\)"),
        ("parquet-listing", r"rclone lsf failed \(exit 1\)"),
        ("manifest-cat", "unreadable manifest of complete snapshot"),
    ],
    ids=["complete-listing", "parquet-listing", "manifest-cat"],
)
def test_lsf_and_cat_failures_fail_closed(tmp_path: Path, failing: str, pattern: str) -> None:
    store = _fresh(tmp_path, FaultStore)
    remote.push_snapshot(_bundle(tmp_path, "one", FILES), store, now_utc=NOW)
    bundle = _bundle(tmp_path, "two", {**FILES, **NEW_FILE})
    matchers: dict[str, Callable[[Sequence[str]], bool]] = {
        "complete-listing": lambda argv: (
            argv[0] == "lsf" and argv[-1] == "BACKUPS3CRYPT:snapshots/"
        ),
        "parquet-listing": lambda argv: argv[0] == "lsf" and argv[-1] == "BACKUPS3CRYPT:parquet/",
        "manifest-cat": lambda argv: argv[0] == "cat" and argv[1].endswith("/manifest.json"),
    }
    store.hook(matchers[failing], forced=[RcloneResult(1, "", "boom")])
    before = _remote_parquet(store)
    store.calls.clear()

    with pytest.raises(RemoteError, match=pattern):
        remote.push_snapshot(bundle, store, now_utc=LATER)

    assert _writes(store) == []
    assert _remote_parquet(store) == before


def test_push_stops_after_the_sentinel_when_it_does_not_match(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    fake = FakeRclone(sentinel=RcloneResult(0, "another store\n", ""))

    with pytest.raises(RemoteError, match="sentinel"):
        remote.push_snapshot(bundle, fake, now_utc=NOW)

    assert fake.calls == [["cat", SENTINEL_ARG]]  # no listing, no manifest read, no upload


def test_manifest_schema_and_bundle_sha256_are_unchanged_by_the_push(tmp_path: Path) -> None:
    source = tmp_path / "src" / "raw"
    source.mkdir(parents=True)
    (source / "a.parquet").write_bytes(b"A" * 40)
    first = backup_mod.backup(
        bundle_root=tmp_path / "bundle", pg_dump_runner=_fake_dump, parquet_roots=[source]
    )
    manifest_bytes = first.manifest_path.read_bytes()
    store = _fresh(tmp_path)

    remote.push_snapshot(tmp_path / "bundle", store, now_utc=NOW)
    remote.push_snapshot(tmp_path / "bundle", store, now_utc=LATER)

    assert first.manifest_path.read_bytes() == manifest_bytes  # the push never rewrites it
    manifest = json.loads(manifest_bytes)
    assert set(manifest) == {"pg.dump", "parquet/raw/a.parquet"}
    assert all(isinstance(k, str) and re.fullmatch(r"[0-9a-f]{64}", v) for k, v in manifest.items())
    second = backup_mod.backup(
        bundle_root=tmp_path / "bundle", pg_dump_runner=_fake_dump, parquet_roots=[source]
    )
    assert second.bundle_sha256 == first.bundle_sha256
    assert (store.store / _manifest_object(SNAP)).read_bytes() == manifest_bytes


def test_no_call_uses_rclone_size_or_checksum_options_and_uploads_stay_immutable(
    tmp_path: Path,
) -> None:
    store = _fresh(tmp_path)
    remote.push_snapshot(_bundle(tmp_path, "one", FILES), store, now_utc=NOW)
    remote.push_snapshot(_bundle(tmp_path, "two", {**FILES, **NEW_FILE}), store, now_utc=LATER)
    remote.push_snapshot(_bundle(tmp_path, "three", {**FILES, **NEW_FILE}), store, now_utc=LATEST)

    forbidden = {"--size-only", "--checksum", "-c", "--ignore-size", "--ignore-times", "--update"}
    assert store.calls
    for call in store.calls:
        assert not forbidden & set(call), call
        if call[0] in {"copy", "copyto"} and not call[1].startswith(CRYPT):
            assert "--immutable" in call, call


def test_a_failing_tree_check_names_the_path_even_when_the_excerpt_is_cut(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    stderr = "\n".join(
        [
            'ERROR : raw/oi.parquet: hashes differ (BACKUPS3CRYPT{x}:parquet) "a" vs (local:) "b"',
            *["NOTICE: Encrypted drive 'BACKUPS3CRYPT{x}:parquet': 0 matching files"] * 20,
            "NOTICE: Failed to cryptcheck: 1 differences found",
        ]
    )
    fake = FakeRclone(overrides={"cryptcheck": RcloneResult(1, "", stderr)})

    with pytest.raises(RemoteError) as excinfo:
        remote.push_snapshot(bundle, fake, now_utc=NOW)

    text = str(excinfo.value)
    assert text.startswith(HEAD_VERIFY)
    assert "raw/oi.parquet" in text
    assert "exit 1" in text
    assert len(text) < 1000  # bounded
