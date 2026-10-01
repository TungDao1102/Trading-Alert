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
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

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
class LibpqTarget:
    """A libpq-safe connection target: no password in the URL, password in the env.

    ``env`` carries only ``PGPASSWORD`` (when the source URL had a password) and is
    excluded from ``repr`` so a logged target never shows the secret.
    """

    url_without_password: str
    env: dict[str, str] = field(default_factory=dict, repr=False)


# pg_restore and `alembic upgrade head` seams, typed like PgDumpRunner so tests inject fakes.
PgRestoreRunner = Callable[[Path, LibpqTarget], None]
MigrateRunner = Callable[[str], None]
# Returns the names of tables (other than alembic_version) that hold rows.
DataProbe = Callable[[str], list[str]]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


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
    files = sorted(p for p in payload_root.rglob("*") if p.is_file() and p.name != MANIFEST_NAME)
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

    parquet_files = tuple(p for p in (bundle_root / "parquet").rglob("*") if p.is_file())
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
            f"refusing drill: --scratch-root {scratch_root} resolves to the bundle root itself"
        )
    if resolved == Path(resolved.anchor):
        raise ValueError(f"refusing drill: --scratch-root {scratch_root} is a filesystem root")
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
    candidate_files.extend(p for p in (scratch_root / "parquet").rglob("*") if p.is_file())
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
            report.messages.append(f"{rel}: sha256 mismatch (expected {expected}, got {actual})")
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
# Verify and restore (Phase 13.1, D-13)
# --------------------------------------------------------------------------- #


class RestoreRefused(RuntimeError):
    """A restore step refused bad or dangerous input. Messages name paths and counts only."""

    def __init__(self, message: str, problems: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.problems = list(problems)


@dataclass(frozen=True)
class RestoreBundleReport:
    """Outcome of one ``restore_bundle()`` call."""

    copied: int
    skipped: int
    database_restored: bool


def libpq_target(database_url: str) -> LibpqTarget:
    """Split a SQLAlchemy-style URL into a libpq URL and a password-bearing env.

    ``postgresql+psycopg://u:p%40ss@h:5432/db`` becomes
    ``postgresql://u@h:5432/db`` plus ``{"PGPASSWORD": "p@ss"}``. libpq rejects the
    ``+driver`` suffix and echoes the whole URL (password included) in its error,
    so neither may reach argv. A ``password`` query parameter is moved as well.
    """
    parts = urlsplit(database_url)
    scheme = parts.scheme.partition("+")[0].lower()
    if scheme not in ("postgresql", "postgres"):
        raise ValueError(f"unsupported database URL scheme {parts.scheme!r}")
    userinfo, _, hostport = parts.netloc.rpartition("@")
    username, _, raw_password = userinfo.partition(":")
    env: dict[str, str] = {}
    if raw_password:
        env["PGPASSWORD"] = unquote(raw_password)
    query = parts.query
    pairs = parse_qsl(query, keep_blank_values=True)
    if any(key == "password" for key, _ in pairs):
        for key, value in pairs:
            if key == "password" and "PGPASSWORD" not in env:
                env["PGPASSWORD"] = value
        query = urlencode([(k, v) for k, v in pairs if k != "password"])
    netloc = f"{username}@{hostport}" if username else hostport
    url = urlunsplit(("postgresql", netloc, parts.path, query, parts.fragment))
    return LibpqTarget(url_without_password=url, env=env)


def _is_unsafe_key(key: str) -> bool:
    """True for a manifest key that could escape the bundle or target root."""
    if not key or key.startswith("/") or "\\" in key or _WINDOWS_DRIVE.match(key):
        return True
    return any(segment in ("", ".", "..") for segment in key.split("/"))


def _read_manifest(bundle_root: Path) -> tuple[dict[str, str] | None, str | None]:
    """Return (manifest, None) or (None, problem line)."""
    manifest_path = bundle_root / MANIFEST_NAME
    if not manifest_path.is_file():
        return None, f"{MANIFEST_NAME}: missing"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, f"{MANIFEST_NAME}: unreadable or not valid JSON"
    if not isinstance(raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
    ):
        return None, f"{MANIFEST_NAME}: not a mapping of relative path to sha256"
    return raw, None


def verify_bundle(bundle_root: Path) -> list[str]:
    """Hash every bundle file against the manifest; return the problems found.

    An empty list means the bundle is valid. Checks: the manifest exists and is a
    path-to-sha256 mapping, no key escapes the bundle, every key names a file whose
    sha256 matches, and no file on disk (other than the root manifest itself) is
    missing from the manifest (set equality). One problem line per offending path.
    """
    manifest, problem = _read_manifest(bundle_root)
    if manifest is None:
        return [problem or f"{MANIFEST_NAME}: unreadable"]
    problems: list[str] = []
    for key in sorted(manifest):
        if _is_unsafe_key(key):
            problems.append(f"{key}: unsafe path in manifest")
            continue
        path = bundle_root / key
        if not path.is_file():
            problems.append(f"{key}: missing from bundle")
            continue
        try:
            actual = _sha256_file(path)
        except OSError:
            problems.append(f"{key}: unreadable")
            continue
        if actual != manifest[key]:
            problems.append(f"{key}: sha256 mismatch")
    on_disk = {
        p.relative_to(bundle_root).as_posix()
        for p in bundle_root.rglob("*")
        if p.is_file() and p != bundle_root / MANIFEST_NAME
    }
    for rel in sorted(on_disk - set(manifest)):
        problems.append(f"{rel}: in bundle but not in manifest")
    return problems


def _sqlalchemy_url(database_url: str) -> Any:
    """SQLAlchemy URL object; a bare ``postgresql://`` gets the psycopg 3 driver."""
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")
    return url


def _tables_with_rows(database_url: str) -> list[str]:
    """Names of tables (except alembic_version) that hold at least one row."""
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(_sqlalchemy_url(database_url))
    try:
        with engine.connect() as conn:
            quote = engine.dialect.identifier_preparer.quote
            filled: list[str] = []
            for name in sorted(inspect(conn).get_table_names()):
                if name == "alembic_version":
                    continue
                if conn.execute(text(f"SELECT 1 FROM {quote(name)} LIMIT 1")).first() is not None:
                    filled.append(name)
            return filled
    finally:
        engine.dispose()


def restore_database(
    dump_path: Path,
    *,
    database_url: str,
    force: bool,
    pg_restore_runner: PgRestoreRunner,
    migrate_runner: MigrateRunner | None = None,
    expect_sha256: str | None = None,
    data_probe: DataProbe | None = None,
) -> None:
    """Restore ``dump_path`` into the database, refusing a non-empty database.

    Order: dump exists, optional sha256 pin matches, URL is libpq-valid, database
    is empty (or ``force``), ``pg_restore``, then ``migrate_runner`` when given.
    ``restore_bundle`` passes ``migrate_runner=None`` because it migrates only after
    the Parquet copy.
    """
    if not dump_path.is_file():
        raise RestoreRefused(f"refusing restore: dump not found at {dump_path}")
    if expect_sha256 is not None and _sha256_file(dump_path) != expect_sha256.strip().lower():
        raise RestoreRefused(f"refusing restore: sha256 of {dump_path.name} differs from expected")
    target = libpq_target(database_url)
    filled = (data_probe or _tables_with_rows)(database_url)
    if filled and not force:
        raise RestoreRefused(
            f"refusing restore: database is not empty ({len(filled)} table(s) with rows: "
            f"{', '.join(filled)}); pass --force to overwrite"
        )
    pg_restore_runner(dump_path, target)
    if migrate_runner is not None:
        migrate_runner(database_url)


def _plan_parquet_copy(manifest: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Map target-relative path -> (bundle key, sha256) for every Parquet entry."""
    planned: dict[str, tuple[str, str]] = {}
    for key in sorted(manifest):
        if not key.startswith("parquet/"):
            continue
        parts = key.split("/", 2)
        if len(parts) != 3:
            raise RestoreRefused(f"{key}: cannot map this manifest entry into the Parquet target")
        rel = parts[2]
        prior = planned.get(rel)
        if prior is not None and prior[1] != manifest[key]:
            raise RestoreRefused(f"{rel}: two bundle roots hold different content for this path")
        planned[rel] = (key, manifest[key])
    return planned


def _copy_into_target(src: Path, dest: Path, expected_sha256: str) -> None:
    """Copy via a temp name plus os.replace; never overwrites an existing file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(src, tmp)
        if _sha256_file(tmp) != expected_sha256:
            raise RestoreRefused(f"{dest.name}: copied content does not match the manifest")
        if dest.exists():
            raise FileExistsError(f"refusing to overwrite existing {dest}")
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def restore_bundle(
    bundle_root: Path,
    *,
    parquet_target: Path,
    database_url: str | None,
    force: bool,
    skip_db: bool,
    pg_restore_runner: PgRestoreRunner,
    migrate_runner: MigrateRunner,
    data_probe: DataProbe | None = None,
) -> RestoreBundleReport:
    """Verified, refusing restore: verify -> checks -> pg_restore -> Parquet copy -> migrate.

    Nothing destructive happens before ``verify_bundle`` passes and every target
    check (Parquet target empty or ``force``, no existing file with different
    content, database empty or ``force``) has passed. An existing Parquet file with
    identical content is skipped; one with different content aborts the restore
    (raw files are immutable, D-04). ``skip_db`` restores Parquet only.
    """
    problems = verify_bundle(bundle_root)
    if problems:
        raise RestoreRefused(
            f"refusing restore: bundle verification failed ({len(problems)} problem(s))",
            problems,
        )
    manifest, _ = _read_manifest(bundle_root)
    assert manifest is not None  # verify_bundle succeeded, so the manifest is valid

    resolved_target = parquet_target.resolve()
    resolved_bundle = bundle_root.resolve()
    if resolved_target == resolved_bundle or resolved_bundle.is_relative_to(resolved_target):
        raise RestoreRefused(
            f"refusing restore: --parquet-target {parquet_target} contains the bundle"
        )
    if resolved_target.is_relative_to(resolved_bundle):
        raise RestoreRefused(
            f"refusing restore: --parquet-target {parquet_target} is inside the bundle"
        )

    planned = _plan_parquet_copy(manifest)
    dump_path = bundle_root / DEFAULT_PG_DUMP_NAME
    if not skip_db:
        if not database_url:
            raise RestoreRefused(
                "refusing restore: DATABASE_URL_SYNC / DATABASE_URL is not set (use --skip-db "
                "for a Parquet-only restore)"
            )
        if DEFAULT_PG_DUMP_NAME not in manifest:
            raise RestoreRefused(f"refusing restore: {DEFAULT_PG_DUMP_NAME} is not in the bundle")
        libpq_target(database_url)  # reject an unsupported scheme before anything runs

    if parquet_target.exists():
        if not parquet_target.is_dir():
            raise RestoreRefused(f"refusing restore: {parquet_target} is not a directory")
        if not force and any(parquet_target.iterdir()):
            raise RestoreRefused(
                f"refusing restore: Parquet target {parquet_target} is not empty; pass --force"
            )
    to_copy: list[tuple[str, Path, str]] = []
    skipped = 0
    for rel, (key, sha) in sorted(planned.items()):
        dest = parquet_target / rel
        if dest.exists() or dest.is_symlink():
            if not dest.is_file() or _sha256_file(dest) != sha:
                raise RestoreRefused(
                    f"{rel}: already exists in the target with different content "
                    "(raw files are immutable and never overwritten)"
                )
            skipped += 1
        else:
            to_copy.append((key, dest, sha))

    if not skip_db:
        assert database_url is not None
        restore_database(
            dump_path,
            database_url=database_url,
            force=force,
            pg_restore_runner=pg_restore_runner,
            migrate_runner=None,
            data_probe=data_probe,
        )
    for key, dest, sha in to_copy:
        _copy_into_target(bundle_root / key, dest, sha)
    if not skip_db:
        assert database_url is not None
        migrate_runner(database_url)
    return RestoreBundleReport(copied=len(to_copy), skipped=skipped, database_restored=not skip_db)


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


def _prod_pg_restore_runner(dump: Path, target: LibpqTarget) -> None:
    """Production pg_restore runner (``PG_RESTORE_BIN`` overrides the binary).

    The password travels only in ``PGPASSWORD``; argv holds the password-free URL.
    """
    pg_bin = os.environ.get("PG_RESTORE_BIN", "pg_restore")
    subprocess.run(
        [
            pg_bin,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "--dbname",
            target.url_without_password,
            str(dump),
        ],
        check=True,
        env={**os.environ, **target.env},
    )


def _prod_migrate_runner(database_url: str) -> None:
    """Run ``alembic upgrade head`` at the project root with DATABASE_URL in the child env."""
    url = _sqlalchemy_url(database_url).render_as_string(hide_password=False)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=_PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": url},
    )


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


def _database_url_from_env() -> str | None:
    return os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL") or None


def main(
    argv: Sequence[str] | None = None,
    *,
    pg_restore_runner: PgRestoreRunner | None = None,
    migrate_runner: MigrateRunner | None = None,
    data_probe: DataProbe | None = None,
) -> int:
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

    verify_p = sub.add_parser(
        "verify", help="Hash every bundle file against the manifest (set equality)."
    )
    verify_p.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)

    restore_p = sub.add_parser(
        "restore",
        help="Verify, then pg_restore, copy Parquet, alembic upgrade head. Refuses bad input.",
    )
    restore_p.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    restore_p.add_argument("--parquet-target", type=Path, required=True)
    restore_p.add_argument(
        "--force",
        action="store_true",
        help="Allow a non-empty Parquet target or database (files are never overwritten).",
    )
    restore_p.add_argument("--skip-db", action="store_true", help="Restore the Parquet files only.")

    args = parser.parse_args(argv)

    if args.cmd == "verify":
        verify_problems = verify_bundle(args.bundle_root)
        if verify_problems:
            print(f"verify-FAILED bundle_root={args.bundle_root}", file=sys.stderr)
            for line in verify_problems:
                print(f"  {line}", file=sys.stderr)
            return 1
        print(f"verify-OK bundle_root={args.bundle_root}")
        return 0

    if args.cmd == "restore":
        try:
            restored = restore_bundle(
                args.bundle_root,
                parquet_target=args.parquet_target,
                database_url=_database_url_from_env(),
                force=args.force,
                skip_db=args.skip_db,
                pg_restore_runner=pg_restore_runner or _prod_pg_restore_runner,
                migrate_runner=migrate_runner or _prod_migrate_runner,
                data_probe=data_probe,
            )
        except RestoreRefused as exc:
            print(f"restore-REFUSED: {exc}", file=sys.stderr)
            for line in exc.problems:
                print(f"  {line}", file=sys.stderr)
            return 1
        print(
            f"restore-OK parquet_target={args.parquet_target} copied={restored.copied} "
            f"skipped={restored.skipped} database_restored={restored.database_restored}"
        )
        return 0

    if args.cmd == "backup":
        runner = _sqlite_fake_pg_dump_runner if args.sqlite_fake_pg_dump else _prod_pg_dump_runner
        result = backup(
            bundle_root=args.bundle_root,
            pg_dump_runner=runner,
            parquet_roots=tuple(args.parquet_roots),
            pg_dump_name=(
                args.pg_dump_path.name if args.pg_dump_path is not None else DEFAULT_PG_DUMP_NAME
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
        print(f"prune-OK bundle_root={args.bundle_root} {verb}={len(prune_report.pruned_files)}")
        for key in prune_report.pruned_files:
            print(f"  {key}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
