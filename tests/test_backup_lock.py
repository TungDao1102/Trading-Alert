"""Backup runs are mutually exclusive per bundle root (13.1 review WR-04).

The scheduled timer, ``deploy/update.sh``, the restore drill and manual runs all stage into the
same bundle directory; an overlapping run must fail fast with a clear message instead of
corrupting the other run's verify-then-push window.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from src.ops import backup as backup_mod
from src.ops.backup import BACKUP_LOCK_NAME, BackupBusy, backup_lock, main
from src.ops.backup_remote import RcloneResult


def _fake_dump(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"FAKE-PG-DUMP\x00" * 8)
    return out


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        self.calls.append(list(argv))
        return RcloneResult(0, "", "")


def test_a_second_lock_on_the_same_bundle_root_is_refused_until_the_first_ends(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "backup" / "bundle"

    with backup_lock(bundle):
        with pytest.raises(BackupBusy, match="already running"):
            with backup_lock(bundle):
                pytest.fail("the second holder must not enter")
        assert (bundle.parent / BACKUP_LOCK_NAME).is_file()

    with backup_lock(bundle):  # released on exit, so the next run proceeds
        pass


def test_different_bundle_roots_do_not_block_each_other(tmp_path: Path) -> None:
    with backup_lock(tmp_path / "a" / "bundle"), backup_lock(tmp_path / "b" / "bundle"):
        pass


def test_backup_cli_exits_non_zero_while_another_run_holds_the_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = tmp_path / "backup" / "bundle"
    source = tmp_path / "raw"
    source.mkdir()
    (source / "oi.parquet").write_bytes(b"BBB" * 10)

    with backup_lock(bundle):
        code = main(
            [
                "backup",
                "--bundle-root",
                str(bundle),
                "--parquet-roots",
                str(source),
            ],
            pg_dump_runner=_fake_dump,
        )

    assert code == 1
    assert "already running" in capsys.readouterr().err
    assert not bundle.exists(), "a refused run must not touch the staging bundle"


@pytest.mark.parametrize("cmd", ["scheduled", "push", "drill-remote"])
def test_remote_commands_refuse_before_any_rclone_call_while_locked(
    tmp_path: Path, cmd: str, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = tmp_path / "backup" / "bundle"
    rclone = _Recorder()
    extra = ["--scratch-root", str(tmp_path / "scratch")] if cmd == "drill-remote" else []

    with backup_lock(bundle):
        code = main(
            [cmd, "--bundle-root", str(bundle), *extra],
            rclone_runner=rclone,
            pg_dump_runner=_fake_dump,
        )

    assert code == 1
    assert "already running" in capsys.readouterr().err
    assert rclone.calls == []


def test_the_lock_file_is_never_part_of_a_manifest_or_a_verification(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    source = tmp_path / "raw"
    source.mkdir()
    (source / "oi.parquet").write_bytes(b"BBB" * 10)
    (root).mkdir()
    (root / BACKUP_LOCK_NAME).write_bytes(b"")  # a legacy root that contains its own lock file

    backup_mod.backup(bundle_root=root, pg_dump_runner=_fake_dump, parquet_roots=[source])

    manifest = (root / "manifest.json").read_text(encoding="utf-8")
    assert BACKUP_LOCK_NAME not in manifest
    assert backup_mod.verify_bundle(root) == []
