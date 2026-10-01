"""Tests for the rclone off-host backup adapter (Phase 13.1 plan 08, D-12 / D-17).

No rclone binary and no network: every rclone call goes through an injected fake runner that
records argv. The real binary is exercised in tests/test_docker_backup_remote.py.
"""

from __future__ import annotations

import json
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
        ["copy", str(Path(root) / "parquet"), "BACKUPS3CRYPT:parquet", "--immutable"],
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
