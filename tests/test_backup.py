"""Tests for the backup script + scratch-restore drill (02-05 Task 3).

D-12: PostgreSQL state (pg_dump of metadata/coverage/watermarks) AND the
self-collected OI dataset (Parquet snapshot copy), restores into a
scratch target and verifies row-count/hash equality. Drill is automated
(single command) and rehearsed in this phase; off-host copy is required
(backup must not live only on the primary host).

This module covers:
  1. Manifest hashing (sha256 of every payload file is computed and
     recorded alongside the bundle)
  2. The drill restores a backup into a scratch database and asserts
     row-count + sha256 equality, exiting non-zero on any mismatch
  3. The PowerShell entrypoint exists and forwards to the Python module
     (no logic in the wrapper; the contract is "single Python entry point
     behind a thin shell")
  4. Corrupted-copy detection: a tampered backup file makes the drill
     exit non-zero (T-02-10)

The actual `pg_dump` command and the live Docker Compose PostgreSQL
container are not exercised here (the test environment has no live PG);
the contract is exercised via a fake `pg_dump_runner` callable that
substitutes a deterministic local file for the real database dump.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from src.ops import backup as backup_mod
from src.ops.backup import (
    BackupResult,
    RestoreReport,
    run_drill,
    write_manifest,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _seed_fake_pg_dump(target: Path) -> Path:
    """Write a fake pg_dump file (sqlite snapshot) for the drill harness."""
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target)
    db.execute("CREATE TABLE IF NOT EXISTS symbol_metadata (symbol TEXT, ts TEXT)")
    db.execute("INSERT INTO symbol_metadata VALUES ('BTCUSDT', '2026-09-21')")
    db.execute("INSERT INTO symbol_metadata VALUES ('ETHUSDT', '2026-09-21')")
    db.commit()
    db.close()
    return target


def _seed_fake_parquet(target: Path) -> Path:
    """Write a tiny Parquet file for the drill."""
    target.parent.mkdir(parents=True, exist_ok=True)
    # The Parquet layout in production uses Polars; for the drill harness
    # we accept any non-empty file (the sha256 is the equality proof).
    target.write_bytes(b"PARQUET-PAYLOAD\x00\x01\x02\x03" * 64)
    return target


def _no_op_pg_dump(out_path: Path) -> Path:
    """Default fake pg_dump: write a sqlite snapshot to `out_path`."""
    return _seed_fake_pg_dump(out_path)


# --------------------------------------------------------------------------- #
# Test 1 — write_manifest records sha256 of every payload file.
# --------------------------------------------------------------------------- #


def test_write_manifest_records_sha256(tmp_path: Path) -> None:
    """The manifest is JSON {file: sha256} for every payload file."""
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    f1 = payload_dir / "pg.dump"
    f1.write_bytes(b"alpha-beta-gamma")
    f2 = payload_dir / "oi-tick.parquet"
    f2.write_bytes(b"delta-epsilon-zeta")

    manifest_path = tmp_path / "manifest.json"
    manifest = write_manifest(payload_dir, manifest_path)

    assert manifest["pg.dump"] == _sha256(f1)
    assert manifest["oi-tick.parquet"] == _sha256(f2)
    # And the JSON file on disk matches the returned dict.
    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk == manifest


# --------------------------------------------------------------------------- #
# Test 2 — backup() runs end-to-end against fake runners + writes manifest.
# --------------------------------------------------------------------------- #


def test_backup_runs_against_fake_pg_dump(tmp_path: Path) -> None:
    """Single-command backup: pg_dump fake + Parquet copy + manifest."""
    bundle_root = tmp_path / "bundle"
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _seed_fake_parquet(parquet_root / "BTCUSDT.parquet")

    result = backup_mod.backup(
        bundle_root=bundle_root,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[parquet_root],
    )

    assert isinstance(result, BackupResult)
    assert result.bundle_root == bundle_root
    assert (bundle_root / "pg.dump").exists()
    # Parquet layout: <bundle>/parquet/<source_basename>/...
    assert (bundle_root / "parquet" / parquet_root.name / "BTCUSDT.parquet").exists()
    assert (bundle_root / "manifest.json").exists()

    manifest = json.loads((bundle_root / "manifest.json").read_text(encoding="utf-8"))
    assert "pg.dump" in manifest
    assert f"parquet/{parquet_root.name}/BTCUSDT.parquet" in manifest
    # sha256 round-trip — the manifest entries match the actual file hashes.
    assert manifest["pg.dump"] == _sha256(bundle_root / "pg.dump")
    assert manifest[f"parquet/{parquet_root.name}/BTCUSDT.parquet"] == _sha256(
        bundle_root / "parquet" / parquet_root.name / "BTCUSDT.parquet"
    )


# --------------------------------------------------------------------------- #
# Test 3 — drill restores into scratch + asserts row-count + sha256 equality.
# --------------------------------------------------------------------------- #


def test_drill_restores_and_asserts_equality(tmp_path: Path) -> None:
    """Backup → scratch restore → equality check; report captures the verdict."""
    # Build a backup bundle
    bundle_root = tmp_path / "bundle"
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _seed_fake_parquet(parquet_root / "oi.parquet")

    backup_mod.backup(
        bundle_root=bundle_root,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[parquet_root],
    )

    # Restore into a scratch dir
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    pg_restore_path = scratch_root / "pg.dump"

    report = run_drill(
        bundle_root=bundle_root,
        scratch_root=scratch_root,
        pg_dump_path=pg_restore_path,
        parquet_roots=[parquet_root],
    )

    assert isinstance(report, RestoreReport)
    assert report.equal is True
    assert report.failed_files == []
    assert len(report.restored_files) >= 2  # pg.dump + at least one parquet
    assert "pg.dump" in report.restored_files
    assert f"parquet/{parquet_root.name}/oi.parquet" in report.restored_files


# --------------------------------------------------------------------------- #
# Test 4 — drill exits non-zero on a tampered backup file (T-02-10).
# --------------------------------------------------------------------------- #


def test_drill_fails_on_tampered_backup(tmp_path: Path) -> None:
    """T-02-10: silent backup corruption MUST exit non-zero on the drill."""
    bundle_root = tmp_path / "bundle"
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _seed_fake_parquet(parquet_root / "oi.parquet")
    backup_mod.backup(
        bundle_root=bundle_root,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[parquet_root],
    )

    # Tamper: rewrite the pg.dump with garbage AFTER the manifest was
    # computed. The manifest hash no longer matches the file contents.
    (bundle_root / "pg.dump").write_bytes(b"CORRUPTED-CONTENT-NOT-IN-MANIFEST")

    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    pg_restore_path = scratch_root / "pg.dump"

    report = run_drill(
        bundle_root=bundle_root,
        scratch_root=scratch_root,
        pg_dump_path=pg_restore_path,
        parquet_roots=[parquet_root],
    )

    assert report.equal is False
    assert "pg.dump" in report.failed_files
    assert any("sha256" in msg.lower() or "hash" in msg.lower() for msg in report.messages)


# --------------------------------------------------------------------------- #
# Test 5 — drill records the equality verdict as a machine-readable struct.
# --------------------------------------------------------------------------- #


def test_drill_report_is_json_serializable(tmp_path: Path) -> None:
    """The RestoreReport must serialize to JSON for the CLI / Phase-7 journal."""
    bundle_root = tmp_path / "bundle"
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _seed_fake_parquet(parquet_root / "oi.parquet")
    backup_mod.backup(
        bundle_root=bundle_root,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[parquet_root],
    )

    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    pg_restore_path = scratch_root / "pg.dump"

    report = run_drill(
        bundle_root=bundle_root,
        scratch_root=scratch_root,
        pg_dump_path=pg_restore_path,
        parquet_roots=[parquet_root],
    )

    # Must serialize to JSON without raising.
    payload = json.loads(json.dumps(report.as_dict(), default=str))
    assert payload["equal"] is True
    assert "manifest_sha256" in payload or "manifest" in payload


# --------------------------------------------------------------------------- #
# Test 6 — manifest is written with stable ordering (sorted paths).
# --------------------------------------------------------------------------- #


def test_manifest_is_sorted_for_reproducibility(tmp_path: Path) -> None:
    """The manifest path order is stable so two backups of the same data
    hash to the same manifest sha256 (audit-friendly)."""
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    # Create files in non-sorted order
    for name in ["z.parquet", "a.parquet", "m.parquet"]:
        (payload_dir / name).write_bytes(b"x" * 32)

    manifest_path = tmp_path / "manifest.json"
    manifest = write_manifest(payload_dir, manifest_path)
    keys = list(manifest.keys())
    assert keys == sorted(keys)


# --------------------------------------------------------------------------- #
# Test 7 — bundle root never lives under the parquet source root (sanity).
# --------------------------------------------------------------------------- #


def test_backup_bundle_root_outside_source_roots(tmp_path: Path) -> None:
    """The backup bundle root must not be a subdirectory of any source
    parquet root (avoids recursive copy + 'include self' loops)."""
    source = tmp_path / "source"
    source.mkdir()
    _seed_fake_parquet(source / "x.parquet")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    # Place a fake bundle under source — backup should still succeed by
    # writing OUTSIDE source (the backup function must not follow itself).
    backup_mod.backup(
        bundle_root=bundle,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[source],
    )
    assert (bundle / "parquet" / source.name / "x.parquet").exists()
    assert not (source / "bundle").exists()


# --------------------------------------------------------------------------- #
# Test 8 — multiple parquet roots merge into one bundle.
# --------------------------------------------------------------------------- #


def test_backup_supports_multiple_parquet_roots(tmp_path: Path) -> None:
    """The Parquet tree (oi + funding + candles) lives under separate
    partitions; backup must merge them into one bundle manifest."""
    oi_root = tmp_path / "oi"
    funding_root = tmp_path / "funding"
    oi_root.mkdir()
    funding_root.mkdir()
    _seed_fake_parquet(oi_root / "BTCUSDT.parquet")
    _seed_fake_parquet(funding_root / "BTCUSDT.parquet")

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    backup_mod.backup(
        bundle_root=bundle,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[oi_root, funding_root],
    )
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert f"parquet/{oi_root.name}/BTCUSDT.parquet" in manifest
    assert f"parquet/{funding_root.name}/BTCUSDT.parquet" in manifest


# --------------------------------------------------------------------------- #
# Phase 13 plan 04 (D-27, T-13-17) — the mark-kline subtree under the raw
# root is covered by the EXISTING backup + restore drill (no new mechanism).
# --------------------------------------------------------------------------- #


def test_backup_covers_mark_kline_subtree(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    mark_part = (
        raw_root
        / "dataset=mark_klines"
        / "interval=1m"
        / "symbol=BTCUSDT"
        / "date=2026-09-29"
        / "part.parquet"
    )
    _seed_fake_parquet(mark_part)
    trade_part = raw_root / "interval=1m" / "symbol=BTCUSDT" / "date=2026-09-29" / "part.parquet"
    _seed_fake_parquet(trade_part)

    bundle_root = tmp_path / "bundle"
    backup_mod.backup(
        bundle_root=bundle_root,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[raw_root],
    )

    rel = "dataset=mark_klines/interval=1m/symbol=BTCUSDT/date=2026-09-29/part.parquet"
    key = f"parquet/{raw_root.name}/{rel}"
    copied = bundle_root / "parquet" / raw_root.name / rel
    assert copied.exists()
    assert copied.read_bytes() == mark_part.read_bytes()
    manifest = json.loads((bundle_root / "manifest.json").read_text(encoding="utf-8"))
    assert key in manifest
    assert manifest[key] == _sha256(mark_part)

    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    report = run_drill(
        bundle_root=bundle_root,
        scratch_root=scratch_root,
        pg_dump_path=scratch_root / "pg.dump",
        parquet_roots=[raw_root],
    )
    assert report.equal is True
    assert report.failed_files == []
    assert key in report.restored_files


# --------------------------------------------------------------------------- #
# Test 9 — drill exits non-zero (returncode) on a tampered backup via CLI.
# --------------------------------------------------------------------------- #


def test_backup_cli_exits_nonzero_on_tampered_backup(tmp_path: Path) -> None:
    """`python -m src.ops.backup drill` exits 1 when any file's sha256 mismatches."""
    bundle_root = tmp_path / "bundle"
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _seed_fake_parquet(parquet_root / "oi.parquet")
    backup_mod.backup(
        bundle_root=bundle_root,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[parquet_root],
    )

    # Tamper with the pg.dump
    (bundle_root / "pg.dump").write_bytes(b"CORRUPTED")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.ops.backup",
            "drill",
            "--bundle-root",
            str(bundle_root),
            "--scratch-root",
            str(tmp_path / "scratch"),
            "--pg-dump-path",
            str(tmp_path / "scratch" / "pg.dump"),
            "--parquet-roots",
            str(parquet_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, f"stderr={proc.stderr!r}"
    assert "drill" in proc.stdout.lower() or "drill" in proc.stderr.lower()


# --------------------------------------------------------------------------- #
# Test 10 — CLI entry point: backup runs end-to-end and exits 0.
# --------------------------------------------------------------------------- #


def test_backup_cli_runs_backup_mode(tmp_path: Path) -> None:
    """`python -m src.ops.backup backup` writes a bundle + manifest + exits 0.

    The suite has no live PostgreSQL, so the CLI runs with the explicit
    TEST-ONLY `--sqlite-fake-pg-dump` flag. Production never passes that
    flag and goes through the real `pg_dump` runner (CR-06).
    """
    bundle_root = tmp_path / "bundle"
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _seed_fake_parquet(parquet_root / "oi.parquet")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.ops.backup",
            "backup",
            "--bundle-root",
            str(bundle_root),
            "--parquet-roots",
            str(parquet_root),
            "--pg-dump-path",
            str(bundle_root / "pg.dump"),
            "--sqlite-fake-pg-dump",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert (bundle_root / "pg.dump").exists()
    assert (bundle_root / "parquet" / parquet_root.name / "oi.parquet").exists()
    assert (bundle_root / "manifest.json").exists()


# --------------------------------------------------------------------------- #
# Test 11 — PowerShell wrapper exists and forwards to the Python module.
# --------------------------------------------------------------------------- #


def test_backup_drill_powershell_wrapper_exists() -> None:
    """The PowerShell entry point exists at scripts/backup-drill.ps1."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "backup-drill.ps1"
    assert script.exists(), f"missing {script}"
    text = script.read_text(encoding="utf-8")
    # The wrapper defers ALL logic to the Python module — no SQL /
    # dump / copy logic in the shell script.
    assert "src.ops.backup" in text
    # The wrapper invokes a python interpreter (production wires `uv run python`).
    assert "python" in text.lower() or "uv run" in text.lower()
    # No `pg_dump` invocation in the shell (logic lives in Python).
    assert "pg_dump" not in text


# --------------------------------------------------------------------------- #
# Test 12 — static guard: no float() in src/ops/backup.py (paranoia).
# --------------------------------------------------------------------------- #


def test_backup_module_has_no_float_call() -> None:
    """The backup module should never convert Decimal/bytes to float."""
    import ast

    src = Path(backup_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                pytest.fail(f"float() call at line {node.lineno}")


# --------------------------------------------------------------------------- #
# Test 13 — bundle is reproducible: re-running backup with the same
# inputs produces a manifest with identical sha256s.
# --------------------------------------------------------------------------- #


def test_backup_is_reproducible(tmp_path: Path) -> None:
    """Re-running the backup against unchanged inputs MUST produce identical
    sha256 entries — the contract is bit-exact reproducibility."""
    bundle_a = tmp_path / "bundle_a"
    bundle_b = tmp_path / "bundle_b"
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _seed_fake_parquet(parquet_root / "oi.parquet")

    backup_mod.backup(
        bundle_root=bundle_a,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[parquet_root],
    )
    backup_mod.backup(
        bundle_root=bundle_b,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[parquet_root],
    )
    manifest_a = json.loads((bundle_a / "manifest.json").read_text(encoding="utf-8"))
    manifest_b = json.loads((bundle_b / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_a == manifest_b


# --------------------------------------------------------------------------- #
# Test 14 — bundle root is created if missing.
# --------------------------------------------------------------------------- #


def test_backup_creates_bundle_root_if_missing(tmp_path: Path) -> None:
    """A non-existent bundle root is created on demand."""
    bundle = tmp_path / "deep" / "nested" / "bundle"
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _seed_fake_parquet(parquet_root / "x.parquet")

    backup_mod.backup(
        bundle_root=bundle,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[parquet_root],
    )
    assert bundle.exists()
    assert (bundle / "manifest.json").exists()


# --------------------------------------------------------------------------- #
# Test 16 — scratch-root guard refuses the live immutable store (WR-02).
# --------------------------------------------------------------------------- #


def test_drill_refuses_live_raw_store_as_scratch(tmp_path: Path) -> None:
    """`--scratch-root data/raw` (or anything overlapping it) must fail
    closed BEFORE any recursive delete — a typo must never wipe the
    live D-04 store."""
    from src.ops.backup import _assert_safe_scratch_root

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    live = backup_mod.DEFAULT_PARQUET_ROOT.resolve()
    # The store itself.
    with pytest.raises(ValueError, match="live"):
        _assert_safe_scratch_root(live, bundle)
    # Anything inside the store (partial wipe).
    with pytest.raises(ValueError, match="live"):
        _assert_safe_scratch_root(live / "data_class=oi", bundle)
    # Anything above the store (wiping an ancestor deletes the store).
    with pytest.raises(ValueError, match="live"):
        _assert_safe_scratch_root(live.parent, bundle)
    # An unrelated scratch dir still passes the guard.
    _assert_safe_scratch_root(tmp_path / "scratch", bundle)


# --------------------------------------------------------------------------- #
# Test 17 — prune garbage-collects stale bundle entries (WR-04).
# --------------------------------------------------------------------------- #


def test_prune_removes_stale_bundle_entries(tmp_path: Path) -> None:
    """Files deleted from the source are pruned from the bundle + manifest."""
    bundle = tmp_path / "bundle"
    source = tmp_path / "parquet"
    source.mkdir()
    _seed_fake_parquet(source / "keep.parquet")
    _seed_fake_parquet(source / "stale.parquet")
    backup_mod.backup(
        bundle_root=bundle,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[source],
    )
    stale_key = f"parquet/{source.name}/stale.parquet"
    assert (bundle / stale_key).exists()

    (source / "stale.parquet").unlink()
    report = backup_mod.prune_bundle(bundle_root=bundle, parquet_roots=[source])

    assert stale_key in report.pruned_files
    assert not (bundle / stale_key).exists()
    assert (bundle / f"parquet/{source.name}/keep.parquet").exists()
    assert (bundle / "pg.dump").exists()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert stale_key not in manifest
    assert "pg.dump" in manifest


def test_prune_dry_run_deletes_nothing(tmp_path: Path) -> None:
    """`dry_run=True` reports without deleting or rewriting the manifest."""
    bundle = tmp_path / "bundle"
    source = tmp_path / "parquet"
    source.mkdir()
    _seed_fake_parquet(source / "stale.parquet")
    backup_mod.backup(
        bundle_root=bundle,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[source],
    )
    (source / "stale.parquet").unlink()
    manifest_before = (bundle / "manifest.json").read_text(encoding="utf-8")

    report = backup_mod.prune_bundle(bundle_root=bundle, parquet_roots=[source], dry_run=True)

    stale_key = f"parquet/{source.name}/stale.parquet"
    assert stale_key in report.pruned_files
    assert report.dry_run is True
    assert (bundle / stale_key).exists()
    assert (bundle / "manifest.json").read_text(encoding="utf-8") == manifest_before


def test_prune_keeps_unmapped_keys(tmp_path: Path) -> None:
    """Keys that cannot be mapped to a known root are kept, never deleted."""
    bundle = tmp_path / "bundle"
    source = tmp_path / "parquet"
    source.mkdir()
    _seed_fake_parquet(source / "x.parquet")
    backup_mod.backup(
        bundle_root=bundle,
        pg_dump_runner=lambda out: _no_op_pg_dump(out),
        parquet_roots=[source],
    )
    ghost = bundle / "parquet" / "ghost" / "g.parquet"
    ghost.parent.mkdir(parents=True, exist_ok=True)
    ghost.write_bytes(b"GHOST")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parquet/ghost/g.parquet"] = _sha256(ghost)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    report = backup_mod.prune_bundle(bundle_root=bundle, parquet_roots=[source])

    assert report.pruned_files == ()
    assert ghost.exists()


# --------------------------------------------------------------------------- #
# Path safety: roots and manifest keys that escape or overlap the bundle (quick 261114-kxu).
# --------------------------------------------------------------------------- #


def _refused_backup(tmp_path: Path, make_root: Any) -> tuple[Path, Path, list[Path]]:
    """Run a backup that must be refused; returns (bundle, sentinel, pg_dump calls)."""
    bundle = tmp_path / "outer" / "bundle"
    bundle.mkdir(parents=True)
    sentinel = bundle / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    root = make_root(bundle)
    if root == bundle / "inside":
        root.mkdir()
    calls: list[Path] = []

    def runner(out: Path) -> Path:
        calls.append(out)
        return _no_op_pg_dump(out)

    with pytest.raises(ValueError):
        backup_mod.backup(bundle_root=bundle, pg_dump_runner=runner, parquet_roots=[root])
    return bundle, sentinel, calls


@pytest.mark.parametrize(
    "make_root",
    [
        pytest.param(lambda bundle: bundle / "..", id="dotdot-name"),
        pytest.param(lambda bundle: Path("."), id="dot-name"),
        pytest.param(lambda bundle: bundle, id="the-bundle-itself"),
        pytest.param(lambda bundle: bundle / "inside", id="inside-the-bundle"),
        pytest.param(lambda bundle: bundle.parent, id="contains-the-bundle"),
    ],
)
def test_backup_refuses_a_parquet_root_that_escapes_or_overlaps_the_bundle(
    tmp_path: Path, make_root: Any
) -> None:
    bundle, sentinel, calls = _refused_backup(tmp_path, make_root)

    assert calls == [], "refused before pg_dump runs"
    assert sentinel.read_text(encoding="utf-8") == "keep me", "nothing was deleted"
    assert not (bundle / "manifest.json").exists()


def test_drill_refuses_a_root_named_dotdot_before_deleting_anything(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    source = tmp_path / "parquet"
    source.mkdir()
    _seed_fake_parquet(source / "a.parquet")
    backup_mod.backup(
        bundle_root=bundle, pg_dump_runner=lambda out: _no_op_pg_dump(out), parquet_roots=[source]
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    sentinel = scratch / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError):
        run_drill(bundle_root=bundle, scratch_root=scratch, parquet_roots=[source / ".."])

    assert sentinel.read_text(encoding="utf-8") == "keep me"


def _bundle_with_outside_file(tmp_path: Path) -> tuple[Path, Path, Path]:
    bundle = tmp_path / "bundle"
    source = tmp_path / "parquet"
    source.mkdir()
    _seed_fake_parquet(source / "x.parquet")
    backup_mod.backup(
        bundle_root=bundle, pg_dump_runner=lambda out: _no_op_pg_dump(out), parquet_roots=[source]
    )
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the bundle", encoding="utf-8")
    return bundle, source, outside


@pytest.mark.parametrize(
    "key_for",
    [
        pytest.param(lambda base, outside: f"parquet/{base}/../../outside.txt", id="dotdot"),
        pytest.param(lambda base, outside: outside.as_posix(), id="absolute"),
        pytest.param(lambda base, outside: f"parquet\\{base}\\..\\..\\outside.txt", id="backslash"),
    ],
)
def test_prune_refuses_a_manifest_key_that_escapes_the_bundle(tmp_path: Path, key_for: Any) -> None:
    bundle, source, outside = _bundle_with_outside_file(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[key_for(source.name, outside)] = _sha256(outside)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    before = manifest_path.read_bytes()
    kept = bundle / f"parquet/{source.name}/x.parquet"
    (source / "x.parquet").unlink()  # a stale safe key, which a clean prune would delete

    with pytest.raises(ValueError, match="manifest keys"):
        backup_mod.prune_bundle(bundle_root=bundle, parquet_roots=[source])

    assert outside.read_text(encoding="utf-8") == "not part of the bundle"
    assert manifest_path.read_bytes() == before, "the manifest is unchanged"
    assert kept.exists(), "nothing was deleted, not even the safe stale key"


# --------------------------------------------------------------------------- #
# Test 15 — secret-free: backup code contains no literal API key pattern.
# --------------------------------------------------------------------------- #


def test_backup_module_has_no_secret_literal() -> None:
    """T-02-09: dump files are excluded from git and the backup code must
    not contain any literal credential patterns."""
    text = Path(backup_mod.__file__).read_text(encoding="utf-8")
    # Common API-key-shaped patterns. Strict enough to fail on accidental
    # leak, permissive enough to avoid false positives on test fixtures.
    for pat in ("api_key =", "API_KEY=", "AKIA", "BEGIN PRIVATE KEY"):
        assert pat not in text, f"backup code contains secret-like literal: {pat!r}"
