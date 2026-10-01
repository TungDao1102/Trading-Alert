"""Tests for bundle verification and restore (Phase 13.1 plan 06, D-12 / D-13).

No PostgreSQL is needed: the pg_restore and migrate steps are injected fake
runners, and the database emptiness probe is a seam. The real pg_restore path
runs in the docker drill test of plan 10.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from src.ops import backup as backup_mod
from src.ops.backup import LibpqTarget, main, restore_bundle, verify_bundle

DB_URL = "postgresql+psycopg://trading:placeholder-pw@db:5432/trading"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_dump(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"FAKE-PG-DUMP\x00" * 8)
    return out


def _make_bundle(tmp_path: Path) -> tuple[Path, Path]:
    """Backup of a two-file Parquet root; returns (bundle_root, source_root)."""
    source = tmp_path / "raw"
    (source / "interval=1m" / "symbol=BTCUSDT").mkdir(parents=True)
    (source / "interval=1m" / "symbol=BTCUSDT" / "part.parquet").write_bytes(b"AAA" * 100)
    (source / "oi.parquet").write_bytes(b"BBB" * 100)
    bundle = tmp_path / "bundle"
    backup_mod.backup(bundle_root=bundle, pg_dump_runner=_fake_dump, parquet_roots=[source])
    return bundle, source


class _Recorder:
    """Fake pg_restore and migrate runners that note what the target looked like."""

    def __init__(self, target: Path) -> None:
        self.target = target
        self.calls: list[str] = []
        self.files_at_pg_restore: list[str] | None = None
        self.hashes_at_migrate: dict[str, str] | None = None
        self.dump_seen: Path | None = None
        self.libpq_seen: LibpqTarget | None = None

    def _listing(self) -> list[str]:
        if not self.target.exists():
            return []
        return sorted(
            p.relative_to(self.target).as_posix() for p in self.target.rglob("*") if p.is_file()
        )

    def pg_restore(self, dump: Path, target: LibpqTarget) -> None:
        self.calls.append("pg_restore")
        self.files_at_pg_restore = self._listing()
        self.dump_seen = dump
        self.libpq_seen = target

    def migrate(self, url: str) -> None:
        self.calls.append("migrate")
        self.hashes_at_migrate = {rel: _sha(self.target / rel) for rel in self._listing()}


def _no_data(_url: str) -> list[str]:
    return []


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #


def test_verify_clean_bundle_is_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle, _ = _make_bundle(tmp_path)
    assert verify_bundle(bundle) == []
    assert main(["verify", "--bundle-root", str(bundle)]) == 0
    assert "verify-OK" in capsys.readouterr().out


def test_verify_flags_changed_byte(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle, source = _make_bundle(tmp_path)
    target = bundle / "parquet" / source.name / "oi.parquet"
    data = bytearray(target.read_bytes())
    data[0] ^= 0xFF
    target.write_bytes(bytes(data))

    assert main(["verify", "--bundle-root", str(bundle)]) == 1
    err = capsys.readouterr().err.splitlines()
    problem_lines = [line for line in err if f"parquet/{source.name}/oi.parquet" in line]
    assert len(problem_lines) == 1
    assert "sha256" in problem_lines[0]


def test_verify_flags_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle, source = _make_bundle(tmp_path)
    (bundle / "parquet" / source.name / "oi.parquet").unlink()

    assert main(["verify", "--bundle-root", str(bundle)]) == 1
    err = capsys.readouterr().err
    assert f"parquet/{source.name}/oi.parquet" in err
    assert "missing" in err


def test_verify_flags_extra_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle, source = _make_bundle(tmp_path)
    (bundle / "parquet" / source.name / "stowaway.parquet").write_bytes(b"x")

    assert main(["verify", "--bundle-root", str(bundle)]) == 1
    err = capsys.readouterr().err
    assert f"parquet/{source.name}/stowaway.parquet" in err
    assert "not in manifest" in err


def test_verify_without_manifest_is_a_problem(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    problems = verify_bundle(bundle)
    assert len(problems) == 1
    assert "manifest.json" in problems[0]


def test_verify_rejects_path_traversal_keys(tmp_path: Path) -> None:
    bundle, _ = _make_bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parquet/raw/../../escape.parquet"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    problems = verify_bundle(bundle)
    assert any("unsafe" in p and "escape.parquet" in p for p in problems)


# --------------------------------------------------------------------------- #
# restore
# --------------------------------------------------------------------------- #


def _restore_argv(bundle: Path, target: Path, *extra: str) -> list[str]:
    return ["restore", "--bundle-root", str(bundle), "--parquet-target", str(target), *extra]


def test_restore_refuses_tampered_bundle_before_anything_happens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    bundle, source = _make_bundle(tmp_path)
    (bundle / "parquet" / source.name / "oi.parquet").write_bytes(b"TAMPERED")
    target = tmp_path / "restored"
    rec = _Recorder(target)

    rc = main(
        _restore_argv(bundle, target),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )

    assert rc != 0
    assert rec.calls == []
    assert not target.exists() or not any(target.iterdir())
    assert "oi.parquet" in capsys.readouterr().err


def test_restore_runs_pg_restore_then_copy_then_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    bundle, source = _make_bundle(tmp_path)
    target = tmp_path / "restored"
    rec = _Recorder(target)

    rc = main(
        _restore_argv(bundle, target),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )

    assert rc == 0
    assert rec.calls == ["pg_restore", "migrate"]
    # pg_restore ran while the Parquet target was still empty; migrate ran after the copy.
    assert rec.files_at_pg_restore == []
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    prefix = f"parquet/{source.name}/"
    expected = {k[len(prefix) :]: v for k, v in manifest.items() if k.startswith(prefix)}
    assert expected  # sanity
    assert rec.hashes_at_migrate == expected
    assert rec.dump_seen == bundle / "pg.dump"
    assert not [p for p in target.rglob("*.tmp")]


def test_restore_refuses_non_empty_target_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    bundle, _ = _make_bundle(tmp_path)
    target = tmp_path / "restored"
    target.mkdir()
    (target / "something.txt").write_text("keep me", encoding="utf-8")
    rec = _Recorder(target)

    rc = main(
        _restore_argv(bundle, target),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )

    assert rc != 0
    assert rec.calls == []
    assert (target / "something.txt").read_text(encoding="utf-8") == "keep me"


def test_restore_force_skips_identical_and_aborts_on_different_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    bundle, source = _make_bundle(tmp_path)
    prefix = bundle / "parquet" / source.name

    # Identical pre-existing file: skipped, restore succeeds.
    same_target = tmp_path / "same"
    same_target.mkdir()
    (same_target / "oi.parquet").write_bytes((prefix / "oi.parquet").read_bytes())
    rec = _Recorder(same_target)
    rc = main(
        _restore_argv(bundle, same_target, "--force"),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )
    assert rc == 0
    assert rec.calls == ["pg_restore", "migrate"]

    # Differing pre-existing file: restore aborts before pg_restore, file untouched.
    diff_target = tmp_path / "diff"
    diff_target.mkdir()
    (diff_target / "oi.parquet").write_bytes(b"DIFFERENT")
    rec2 = _Recorder(diff_target)
    rc2 = main(
        _restore_argv(bundle, diff_target, "--force"),
        pg_restore_runner=rec2.pg_restore,
        migrate_runner=rec2.migrate,
        data_probe=_no_data,
    )
    assert rc2 != 0
    assert rec2.calls == []
    assert (diff_target / "oi.parquet").read_bytes() == b"DIFFERENT"


def test_restore_skip_db_copies_parquet_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    bundle, _ = _make_bundle(tmp_path)
    target = tmp_path / "restored"
    rec = _Recorder(target)

    rc = main(
        _restore_argv(bundle, target, "--skip-db"),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )

    assert rc == 0
    assert rec.calls == []
    assert (target / "oi.parquet").exists()
    assert (target / "interval=1m" / "symbol=BTCUSDT" / "part.parquet").exists()


def test_restore_bundle_api_returns_counts(tmp_path: Path) -> None:
    bundle, _ = _make_bundle(tmp_path)
    target = tmp_path / "restored"
    rec = _Recorder(target)
    report = restore_bundle(
        bundle,
        parquet_target=target,
        database_url=DB_URL,
        force=False,
        skip_db=False,
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )
    assert report.copied == 2
    assert report.skipped == 0
    assert report.database_restored is True
