"""Single-command backup + scratch-restore drill (D-12 / SECURITY_AND_OPERATIONS §9).

The backup script does two things, atomically:

  1. `pg_dump --format=custom` of the operational PostgreSQL state
     (symbol_metadata / coverage_windows / collector_watermarks /
     collector_gaps — everything in the baseline Alembic migration). The
     dump lives at `<bundle_root>/pg.dump`.
  2. A copy of the self-collected Parquet tree (OI ticks, funding ticks,
     opportunistic research OI, candles once backfilled). The copy
     lives at `<bundle_root>/parquet/...` preserving the directory layout.

After the payload is in place, the script writes a `manifest.json`
containing a sha256 for every payload file. The manifest is the
authoritative equality contract for the restore drill.

The restore drill (`run_drill`):

  1. Recreates the dump from the bundle (or copies it back into a
     scratch database — the actual `pg_restore` is left to the
     operator's environment for V1; this module ships the equality
     proof).
  2. Recopies the Parquet payload to a scratch root.
  3. Re-hashes every payload file in the scratch root and compares it
     to the manifest. Any mismatch is a hard failure — exits non-zero.

The CLI entry point is `python -m src.ops.backup [backup|drill]`. All
shell logic (PowerShell wrapper, scheduling, off-host copy) defers to
this module — no SQL / copy logic lives in the shell scripts.

Operator notes (D-12):
  - Off-host target is set via `BACKUP_TARGET` env var. The current
    proposal is a OneDrive-synced directory on the operator's host —
    the sync agent copies the bundle root off the primary host, so a
    primary-host loss does NOT destroy the backup.
  - The backup shell-out is the real `pg_dump` (`_prod_pg_dump_runner`,
    configured via `PG_DUMP_BIN` / `DATABASE_URL_SYNC`); tests pass an
    explicit sqlite fake via `--sqlite-fake-pg-dump`, never the default.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

DEFAULT_PARQUET_ROOT = Path("data") / "raw"
DEFAULT_BUNDLE_ROOT = Path("data") / "backup"
DEFAULT_PG_DUMP_NAME = "pg.dump"
MANIFEST_NAME = "manifest.json"

# Type alias for the pg_dump runner — callable taking an output path and
# returning the same path on success. Production wires this to a real
# `pg_dump --format=custom ...` invocation; tests pass a sqlite fake.
PgDumpRunner = Callable[[Path], Path]


@dataclass(frozen=True)
class BackupBundle:
    """Manifest entry — one line per payload file."""

    root: Path
    pg_dump_path: Path
    parquet_roots: tuple[Path, ...]
    manifest_path: Path
    sha256_by_relpath: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BackupResult:
    """Outcome of one `backup()` call.

    `bundle_sha256` is the sha256 of the manifest JSON itself — two
    runs against the same inputs MUST produce the same bundle_sha256
    (reproducibility invariant per D-12).
    """

    bundle_root: Path
    pg_dump_path: Path
    parquet_files: tuple[Path, ...]
    manifest_path: Path
    bundle_sha256: str


@dataclass
class RestoreReport:
    """Outcome of one `run_drill()` call.

    Mutable (not frozen) because the drill mutates `restored_files`,
    `failed_files`, `messages`, `equal`, and `manifest` as it walks the
    bundle — a dataclass with `__post_init__` reset is the cleanest fit.
    """

    bundle_root: Path
    scratch_root: Path
    restored_files: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    manifest: dict[str, str] = field(default_factory=dict)
    equal: bool = False

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _sha256_file(path: Path) -> str:
    """Compute sha256 of a file in 64KB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(payload_root: Path, manifest_path: Path) -> dict[str, str]:
    """Walk `payload_root`, compute sha256 of every file, write JSON map.

    Path keys are relative to `payload_root` (POSIX-style for portability)
    so the same payload produces the same manifest on every host. The
    manifest file itself is excluded from its own hash: on incremental
    re-runs into the same bundle root the pre-existing manifest would
    otherwise be hashed into the new manifest (self-referential entry
    whose stored hash is immediately stale).
    """
    manifest: dict[str, str] = {}
    files = sorted(
        p for p in payload_root.rglob("*") if p.is_file() and p.name != MANIFEST_NAME
    )
    for path in files:
        rel = path.relative_to(payload_root).as_posix()
        manifest[rel] = _sha256_file(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def backup(
    *,
    bundle_root: Path,
    pg_dump_runner: PgDumpRunner,
    parquet_roots: Sequence[Path] = (DEFAULT_PARQUET_ROOT,),
    pg_dump_name: str = DEFAULT_PG_DUMP_NAME,
) -> BackupResult:
    """Run the single-command backup.

    Steps:
      1. Run `pg_dump_runner` against `<bundle_root>/<pg_dump_name>`.
      2. Copy every file under each `parquet_root` into
         `<bundle_root>/parquet/<basename_of_root>/...`.
      3. Write `manifest.json` of the full payload.
      4. Compute the manifest sha256 (bundle_sha256).

    `bundle_root` is created if missing. The backup is append-only: it
    never deletes files in `bundle_root` (re-runs overwrite the same
    tree), so files deleted from a source root survive in the bundle
    until `prune_bundle()` (the `prune` subcommand) garbage-collects
    them — without pruning, a restore would resurrect deliberately
    removed data.
    """
    bundle_root.mkdir(parents=True, exist_ok=True)
    pg_dump_path = bundle_root / pg_dump_name
    pg_dump_runner(pg_dump_path)

    _blog = structlog.get_logger()
    missing_roots = [s for s in parquet_roots if not s.exists()]
    for source in missing_roots:
        # A typo'd root must never yield a silent pg.dump-only bundle.
        _blog.warning("backup.parquet_root_missing", root=str(source))
    if parquet_roots and len(missing_roots) == len(parquet_roots):
        raise FileNotFoundError(
            "refusing backup: every parquet root is missing "
            f"({[str(s) for s in parquet_roots]}) — bundle would contain "
            "only pg.dump"
        )

    for source in parquet_roots:
        if not source.exists():
            continue
        target = bundle_root / "parquet" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # Re-running an incremental backup overwrites the same tree.
            shutil.rmtree(target)
        shutil.copytree(source, target)

    manifest_path = bundle_root / MANIFEST_NAME
    write_manifest(bundle_root, manifest_path)
    bundle_sha256 = _sha256_file(manifest_path)

    parquet_files = tuple(
        p for p in (bundle_root / "parquet").rglob("*") if p.is_file()
    )
    return BackupResult(
        bundle_root=bundle_root,
        pg_dump_path=pg_dump_path,
        parquet_files=parquet_files,
        manifest_path=manifest_path,
        bundle_sha256=bundle_sha256,
    )


@dataclass(frozen=True)
class PruneReport:
    """Outcome of one `prune_bundle()` call.

    `pruned_files` are manifest relpaths whose source file no longer
    exists (deleted from the bundle unless `dry_run`). Keys that cannot
    be mapped to a known source root (`pg.dump`, unknown basenames) are
    always kept — pruning only garbage-collects what it can prove stale.
    """

    bundle_root: Path
    pruned_files: tuple[str, ...]
    dry_run: bool
    manifest_path: Path


def _remove_empty_dirs(root: Path) -> None:
    """Recursively remove empty directories under `root` (prune cleanup)."""
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir():
            _remove_empty_dirs(child)
    if not any(root.iterdir()):
        root.rmdir()


def prune_bundle(
    *,
    bundle_root: Path,
    parquet_roots: Sequence[Path] = (DEFAULT_PARQUET_ROOT,),
    dry_run: bool = False,
) -> PruneReport:
    """Reconcile the bundle against the live source roots (WR-04).

    Deletes bundle entries under `parquet/<basename>/...` whose source
    file no longer exists under the matching root, then rewrites the
    manifest so it describes the source of truth again. With
    `dry_run=True` nothing is deleted or rewritten — the report lists
    what WOULD be pruned.
    """
    manifest_path = bundle_root / MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"refusing prune: no manifest at {manifest_path}")
    manifest: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_basename = {s.name: s for s in parquet_roots}
    pruned: list[str] = []
    for key in sorted(manifest):
        if not key.startswith("parquet/"):
            continue
        parts = key.split("/", 2)
        if len(parts) != 3:
            continue
        _, base, rel = parts
        source = by_basename.get(base)
        if source is None:
            continue
        if not (source / rel).exists():
            pruned.append(key)
    if not dry_run:
        for key in pruned:
            (bundle_root / key).unlink(missing_ok=True)
        _remove_empty_dirs(bundle_root / "parquet")
        remaining = {k: v for k, v in manifest.items() if k not in set(pruned)}
        manifest_path.write_text(
            json.dumps(remaining, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return PruneReport(
        bundle_root=bundle_root,
        pruned_files=tuple(pruned),
        dry_run=dry_run,
        manifest_path=manifest_path,
    )


def _assert_safe_scratch_root(scratch_root: Path, bundle_root: Path) -> None:
    """Fail closed before any recursive delete of an operator-supplied path.

    A typo (`--scratch-root .`, `/`, `~`, the bundle root itself, or
    `data/raw`) must never wipe the working tree, the live store, or the
    backup bundle. Raises `ValueError` on any dangerous layout.
    """
    resolved = scratch_root.resolve()
    bundle = bundle_root.resolve()
    if resolved == bundle:
        raise ValueError(
            f"refusing drill: --scratch-root {scratch_root} resolves to "
            "the bundle root itself"
        )
    if resolved == Path(resolved.anchor):
        raise ValueError(
            f"refusing drill: --scratch-root {scratch_root} is a filesystem root"
        )
    for protected in (Path.home().resolve(), Path.cwd().resolve()):
        if resolved == protected:
            raise ValueError(
                f"refusing drill: --scratch-root {scratch_root} resolves to "
                f"protected directory {protected}"
            )
    if bundle.is_relative_to(resolved):
        raise ValueError(
            f"refusing drill: bundle root {bundle_root} lives inside "
            f"--scratch-root {scratch_root} — wiping scratch would destroy "
            "the backup bundle"
        )
    if resolved.is_relative_to(bundle):
        raise ValueError(
            f"refusing drill: --scratch-root {scratch_root} lives inside "
            f"the bundle root {bundle_root} — ambiguous layout, refusing"
        )
    # Never wipe the live immutable Parquet store (D-04): a
    # `--scratch-root data/raw` typo resolves differently from CWD,
    # home, and the bundle root, so none of the guards above catch it.
    # Refuse the store itself, anything inside it (partial wipe), and
    # anything above it (wiping an ancestor deletes the store too —
    # e.g. `--scratch-root data` when the bundle lives off-host).
    live_raw = DEFAULT_PARQUET_ROOT.resolve()
    if (
        resolved == live_raw
        or resolved.is_relative_to(live_raw)
        or live_raw.is_relative_to(resolved)
    ):
        raise ValueError(
            f"refusing drill: --scratch-root {scratch_root} is the live "
            f"raw store {live_raw} (or overlaps it) — wiping it would "
            "delete collected candles"
        )


def run_drill(
    *,
    bundle_root: Path,
    scratch_root: Path,
    pg_dump_path: Path | None = None,
    parquet_roots: Sequence[Path] = (DEFAULT_PARQUET_ROOT,),
) -> RestoreReport:
    """Restore the bundle into a scratch root + assert sha256 equality.

    Steps:
      1. Wipe `scratch_root` and recreate it.
      2. Copy the bundle's pg.dump into the scratch root (this is the
         restore half; production wires `pg_restore --create` against
         a scratch database, but the equality proof lives in the
         manifest hash, not in the restore path).
      3. Copy every payload file from the bundle into the scratch root
         under the same `<parquet_root_basename>/...` layout.
      4. Read the manifest, re-hash every file in the scratch root,
         compare each hash to the manifest. Any mismatch → report
         `equal=False` and the offending path in `failed_files`.

    `pg_dump_path` defaults to `<scratch_root>/pg.dump` so a caller who
    only wants the equality verdict (no separate scratch database path)
    can pass `bundle_root` + `scratch_root` and skip the pg_dump_path
    argument.
    """
    report = RestoreReport(bundle_root=bundle_root, scratch_root=scratch_root)
    # Destructive recursive delete on an operator-supplied path: validate
    # FIRST, fail closed on any dangerous layout (never wipe blindly).
    _assert_safe_scratch_root(scratch_root, bundle_root)
    if scratch_root.exists():
        shutil.rmtree(scratch_root)
    scratch_root.mkdir(parents=True, exist_ok=True)

    bundle_pg_dump = bundle_root / DEFAULT_PG_DUMP_NAME
    if not bundle_pg_dump.exists():
        report.messages.append(f"bundle pg.dump missing at {bundle_pg_dump}")
        report.failed_files.append(DEFAULT_PG_DUMP_NAME)
        return report
    restore_pg_dump = pg_dump_path or (scratch_root / DEFAULT_PG_DUMP_NAME)
    restore_pg_dump.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle_pg_dump, restore_pg_dump)

    for source in parquet_roots:
        bundle_parquet_dir = bundle_root / "parquet" / source.name
        if not bundle_parquet_dir.exists():
            continue
        target = scratch_root / "parquet" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(bundle_parquet_dir, target)

    manifest_path = bundle_root / MANIFEST_NAME
    if not manifest_path.exists():
        report.messages.append(f"manifest missing at {manifest_path}")
        report.failed_files.append(str(manifest_path))
        return report
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Recompute the drill's manifest against the scratch root. Walk the
    # bundle's pg.dump + every restored parquet file.
    candidate_files: list[Path] = []
    candidate_files.append(restore_pg_dump)
    candidate_files.extend(
        p for p in (scratch_root / "parquet").rglob("*") if p.is_file()
    )
    for path in candidate_files:
        try:
            rel = path.relative_to(scratch_root).as_posix()
        except ValueError:
            rel = path.as_posix()
            report.failed_files.append(rel)
            report.messages.append(f"{rel}: outside scratch root, not verified")
            continue
        expected = manifest.get(rel)
        if expected is None:
            report.failed_files.append(rel)
            report.messages.append(f"{rel}: not in manifest")
            continue
        actual = _sha256_file(path)
        if actual != expected:
            report.failed_files.append(rel)
            report.messages.append(
                f"{rel}: sha256 mismatch (expected {expected}, got {actual})"
            )
        else:
            report.restored_files.append(rel)

    # Full-set comparison: every manifest key must have been visited. Extra
    # bundle files, a skipped root, or a truncated restore otherwise still
    # yields equal=True. (The manifest.json entry itself is excluded — it
    # is never part of its own hash.)
    visited = set(report.restored_files) | set(report.failed_files)
    for key in sorted(manifest):
        if key == MANIFEST_NAME:
            continue
        if key not in visited:
            report.failed_files.append(key)
            report.messages.append(f"{key}: in manifest but never restored")

    report.manifest = manifest
    report.equal = not report.failed_files
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _prod_pg_dump_runner(out: Path) -> Path:
    """Production pg_dump runner — shells out to the real `pg_dump`.

    Binary from `PG_DUMP_BIN` (default `pg_dump`); database URL from
    `DATABASE_URL_SYNC` (fallback `DATABASE_URL`). Raises on any failure
    so the CLI never prints `backup-OK` without archiving real
    PostgreSQL state (D-12).
    """
    pg_bin = os.environ.get("PG_DUMP_BIN", "pg_dump")
    db_url = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "refusing backup: neither DATABASE_URL_SYNC nor DATABASE_URL "
            "is set — no PostgreSQL dump was taken, backup-OK refused"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [pg_bin, "--format=custom", "-f", str(out), db_url],
        check=True,
    )
    return out


def _sqlite_fake_pg_dump_runner(out: Path) -> Path:
    """TEST-ONLY fake — write a sqlite snapshot instead of a real dump.

    Used exclusively by the test suite (via the `--sqlite-fake-pg-dump`
    CLI flag) so tests run without a live PostgreSQL server. NEVER the
    default: production always goes through `_prod_pg_dump_runner`.
    """
    import sqlite3

    out.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(out)
    db.execute("CREATE TABLE IF NOT EXISTS _probe (x INTEGER)")
    db.commit()
    db.close()
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.ops.backup",
        description="Single-command backup + scratch-restore drill (D-12).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    backup_p = sub.add_parser("backup", help="Run the backup (pg_dump + parquet copy).")
    backup_p.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    backup_p.add_argument(
        "--parquet-roots",
        type=Path,
        nargs="+",
        default=[DEFAULT_PARQUET_ROOT],
    )
    backup_p.add_argument(
        "--pg-dump-path",
        type=Path,
        default=None,
        help="Override the pg_dump output path (default: <bundle-root>/pg.dump).",
    )
    backup_p.add_argument(
        "--sqlite-fake-pg-dump",
        action="store_true",
        help="TEST ONLY: write a sqlite snapshot instead of running pg_dump. "
        "Never use in production — the default is the real pg_dump runner.",
    )

    drill_p = sub.add_parser("drill", help="Restore into a scratch root + assert equality.")
    drill_p.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    drill_p.add_argument("--scratch-root", type=Path, required=True)
    drill_p.add_argument("--pg-dump-path", type=Path, required=True)
    drill_p.add_argument(
        "--parquet-roots",
        type=Path,
        nargs="+",
        default=[DEFAULT_PARQUET_ROOT],
    )

    prune_p = sub.add_parser(
        "prune",
        help="Garbage-collect bundle entries whose source file no longer exists.",
    )
    prune_p.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    prune_p.add_argument(
        "--parquet-roots",
        type=Path,
        nargs="+",
        default=[DEFAULT_PARQUET_ROOT],
    )
    prune_p.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be pruned without deleting or rewriting.",
    )

    args = parser.parse_args(argv)

    if args.cmd == "backup":
        runner = (
            _sqlite_fake_pg_dump_runner
            if args.sqlite_fake_pg_dump
            else _prod_pg_dump_runner
        )
        result = backup(
            bundle_root=args.bundle_root,
            pg_dump_runner=runner,
            parquet_roots=tuple(args.parquet_roots),
            pg_dump_name=(
                args.pg_dump_path.name
                if args.pg_dump_path is not None
                else DEFAULT_PG_DUMP_NAME
            ),
        )
        print(f"backup-OK bundle_root={args.bundle_root}")
        print(f"  pg_dump_path={result.pg_dump_path}")
        print(f"  parquet_files={len(result.parquet_files)}")
        print(f"  bundle_sha256={result.bundle_sha256}")
        return 0

    if args.cmd == "drill":
        report = run_drill(
            bundle_root=args.bundle_root,
            scratch_root=args.scratch_root,
            pg_dump_path=args.pg_dump_path,
            parquet_roots=tuple(args.parquet_roots),
        )
        if report.equal:
            restored_count = len(report.restored_files)
            print(f"drill-OK scratch_root={args.scratch_root} restored={restored_count}")
            return 0
        print(f"drill-FAILED scratch_root={args.scratch_root}", file=sys.stderr)
        for msg in report.messages:
            print(f"  {msg}", file=sys.stderr)
        return 1

    if args.cmd == "prune":
        prune_report = prune_bundle(
            bundle_root=args.bundle_root,
            parquet_roots=tuple(args.parquet_roots),
            dry_run=args.dry_run,
        )
        verb = "would prune" if prune_report.dry_run else "pruned"
        print(
            f"prune-OK bundle_root={args.bundle_root} "
            f"{verb}={len(prune_report.pruned_files)}"
        )
        for key in prune_report.pruned_files:
            print(f"  {key}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
