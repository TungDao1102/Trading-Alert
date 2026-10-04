"""Encrypted, provider-neutral off-host backups through rclone (Phase 13.1, D-12 / D-17).

Transport is rclone only: an ``s3`` remote (any S3-compatible store: AWS, Wasabi, B2 through its
S3 endpoint, ``rclone serve s3`` in tests) with an rclone ``crypt`` remote layered on top, so the
provider sees ciphertext (names and contents). Everything is configured from ``BACKUP_S3_*`` and
``BACKUP_CRYPT_*`` environment variables that are mapped here to ``RCLONE_CONFIG_*``; a missing
variable fails closed naming the variable, never its value. No credential ever appears in argv:
the mapped values live only in the child process environment.

Remote layout (inside the crypt remote)::

    _sentinel/sentinel.txt                       fixed content, proves the crypt key is right
    snapshots/<YYYYMMDDTHHMMSSZ>/pg.dump
    snapshots/<YYYYMMDDTHHMMSSZ>/manifest.json   lists pg.dump and every Parquet path + sha256
    parquet/<root basename>/...                  append-only: copied with ``--immutable``,
                                                 never synced, moved or deleted

Safety rules enforced here (research finding 13, Pitfalls 6 and 7):

* A wrong crypt key looks like an empty bucket to rclone (``lsf`` prints a notice and exits 0,
  sub-path operations exit 3). So every push, pull and retention run first decrypts the sentinel
  and compares it; exit code 3, an empty listing and a content mismatch are errors, never "no
  backups yet". The sentinel is only created by an explicit ``--init-remote`` on an empty bucket.
* Retention deletes only ``snapshots/<id>`` directories whose name parses as a snapshot id, only
  after the new snapshot passed ``rclone cryptcheck``, and never touches ``parquet/``.
* A pulled bundle is rebuilt from one snapshot plus exactly the Parquet files its manifest names
  and is verified (sha256 + set equality) before it is returned.

Stdlib only, plus ``src.ops.backup`` (bundle verification) and ``src.ops.redaction`` (scrubbing).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.ops.backup import (
    DEFAULT_PG_DUMP_NAME,
    MANIFEST_NAME,
    DataProbe,
    PgDumpRunner,
    PgRestoreRunner,
    _assert_safe_scratch_root,
    _is_unsafe_key,
    _read_manifest,
    _sqlalchemy_url,
    backup,
    restore_database,
    verify_bundle,
)
from src.ops.redaction import scrub

S3_REMOTE = "BACKUPS3"
CRYPT_REMOTE = "BACKUPS3CRYPT"

S3_VARIABLES: tuple[str, ...] = (
    "BACKUP_S3_PROVIDER",
    "BACKUP_S3_ENDPOINT",
    "BACKUP_S3_REGION",
    "BACKUP_S3_BUCKET",
    "BACKUP_S3_ACCESS_KEY_ID",
    "BACKUP_S3_SECRET_ACCESS_KEY",
)
CRYPT_VARIABLES: tuple[str, ...] = ("BACKUP_CRYPT_PASSWORD", "BACKUP_CRYPT_PASSWORD2")

SENTINEL_PATH = "_sentinel/sentinel.txt"
SENTINEL_CONTENT = "trading-alert backup sentinel format=1\n"

SNAPSHOTS_DIR = "snapshots"
PARQUET_DIR = "parquet"

# rclone exit codes (https://rclone.org/docs/#exit-code).
_EXIT_NOT_FOUND = frozenset({3, 4})

_SNAPSHOT_ID_FORMAT = "%Y%m%dT%H%M%SZ"
_SNAPSHOT_ID_RE = re.compile(r"\d{8}T\d{6}Z")
_RCLONE_TIMEOUT_S = 6 * 3600
_EXCERPT_CHARS = 400


class RemoteError(RuntimeError):
    """A remote operation failed or refused. Messages never carry secret values."""


class RemoteConfigError(RemoteError):
    """Backup environment variables are missing. Messages name variables, never values."""


@dataclass(frozen=True)
class RcloneResult:
    """Exit code and captured text of one rclone invocation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


# argv WITHOUT the binary, extra environment for the child -> result. Tests inject fakes.
RcloneRunner = Callable[[Sequence[str], Mapping[str, str]], RcloneResult]


# --------------------------------------------------------------------------- #
# Environment mapping and the production runner
# --------------------------------------------------------------------------- #


def rclone_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Map ``BACKUP_S3_*`` / ``BACKUP_CRYPT_*`` to the ``RCLONE_CONFIG_*`` form.

    ``BACKUP_CRYPT_PASSWORD`` and ``BACKUP_CRYPT_PASSWORD2`` must already be ``rclone obscure``
    output (rclone refuses a raw passphrase). Raises ``RemoteConfigError`` listing every missing
    or empty variable by name.
    """
    missing = [name for name in (*S3_VARIABLES, *CRYPT_VARIABLES) if not environ.get(name, "")]
    if missing:
        raise RemoteConfigError(
            "backup configuration is incomplete; set: " + ", ".join(sorted(missing))
        )
    s3 = f"RCLONE_CONFIG_{S3_REMOTE}_"
    crypt = f"RCLONE_CONFIG_{CRYPT_REMOTE}_"
    return {
        f"{s3}TYPE": "s3",
        f"{s3}PROVIDER": environ["BACKUP_S3_PROVIDER"],
        f"{s3}ENDPOINT": environ["BACKUP_S3_ENDPOINT"],
        f"{s3}REGION": environ["BACKUP_S3_REGION"],
        f"{s3}ACCESS_KEY_ID": environ["BACKUP_S3_ACCESS_KEY_ID"],
        f"{s3}SECRET_ACCESS_KEY": environ["BACKUP_S3_SECRET_ACCESS_KEY"],
        f"{crypt}TYPE": "crypt",
        f"{crypt}REMOTE": f"{S3_REMOTE}:{environ['BACKUP_S3_BUCKET']}",
        f"{crypt}PASSWORD": environ["BACKUP_CRYPT_PASSWORD"],
        f"{crypt}PASSWORD2": environ["BACKUP_CRYPT_PASSWORD2"],
    }


def raw_bucket_remote(environ: Mapping[str, str]) -> str:
    """The un-encrypted ``BACKUPS3:<bucket>`` remote (ciphertext names), for emptiness checks."""
    return rclone_env(environ)[f"RCLONE_CONFIG_{CRYPT_REMOTE}_REMOTE"]


def make_rclone_runner(environ: Mapping[str, str] | None = None) -> RcloneRunner:
    """Production runner: ``rclone`` (``RCLONE_BIN`` overrides) with the mapped env.

    The configuration is validated now, so a missing variable fails before any work starts.
    Credentials travel only in the child environment, never in argv.
    """
    source = os.environ if environ is None else environ
    mapped = rclone_env(source)
    binary = source.get("RCLONE_BIN") or "rclone"

    def run(argv: Sequence[str], extra: Mapping[str, str]) -> RcloneResult:
        try:
            proc = subprocess.run(
                [binary, *argv],
                env={**os.environ, **mapped, **extra},
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_RCLONE_TIMEOUT_S,
                check=False,
            )
        except FileNotFoundError:
            raise RemoteError(f"rclone binary not found ({binary!r}); install rclone") from None
        except subprocess.TimeoutExpired:
            raise RemoteError(f"rclone {argv[0]} timed out") from None
        return RcloneResult(proc.returncode, proc.stdout, proc.stderr)

    return run


def _excerpt(text: str) -> str:
    """One scrubbed, bounded line of rclone output for an error message."""
    flat = " ".join(scrub(text).split())
    return flat[-_EXCERPT_CHARS:]


def _call(
    runner: RcloneRunner, argv: Sequence[str], *, ok: frozenset[int] = frozenset({0})
) -> RcloneResult:
    """Run rclone; any exit code outside ``ok`` (3 included) raises with a scrubbed excerpt."""
    result = runner(list(argv), {})
    if result.returncode not in ok:
        raise RemoteError(
            f"rclone {argv[0]} failed (exit {result.returncode}): {_excerpt(result.stderr)}"
        )
    return result


# --------------------------------------------------------------------------- #
# Snapshot ids
# --------------------------------------------------------------------------- #


def snapshot_id(now_utc: datetime) -> str:
    """``YYYYMMDDTHHMMSSZ`` for an aware datetime (converted to UTC)."""
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("snapshot_id needs a timezone-aware datetime")
    return now_utc.astimezone(UTC).strftime(_SNAPSHOT_ID_FORMAT)


def parse_snapshot_id(name: str) -> datetime | None:
    """UTC datetime for a well-formed snapshot id, else ``None`` (never raises)."""
    if not _SNAPSHOT_ID_RE.fullmatch(name):
        return None
    try:
        return datetime.strptime(name, _SNAPSHOT_ID_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Sentinel
# --------------------------------------------------------------------------- #


def _crypt(path: str) -> str:
    return f"{CRYPT_REMOTE}:{path}"


def _sentinel_matches(stdout: str) -> bool:
    return stdout.replace("\r\n", "\n") == SENTINEL_CONTENT


def check_sentinel(runner: RcloneRunner) -> None:
    """Decrypt the sentinel and compare it; any failure is an error, never "no backups yet"."""
    result = runner(["cat", _crypt(SENTINEL_PATH)], {})
    if result.returncode != 0:
        raise RemoteError(
            f"backup sentinel unreadable (rclone exit {result.returncode}): wrong crypt key, "
            "wrong bucket, or the remote was never initialised "
            f"(first push uses --init-remote on an empty bucket); {_excerpt(result.stderr)}"
        )
    if not result.stdout.strip():
        raise RemoteError(
            "backup sentinel is missing or empty: the remote was never initialised "
            "(first push uses --init-remote on an empty bucket) or the crypt key is wrong"
        )
    if not _sentinel_matches(result.stdout):
        raise RemoteError(
            "backup sentinel content differs from the expected value: wrong crypt key or a "
            "foreign store; refusing to continue"
        )


def init_sentinel(runner: RcloneRunner, *, raw_remote: str) -> bool:
    """Create the sentinel on a genuinely empty remote; return True when it was written.

    A valid existing sentinel is left alone (returns False). The sentinel is only written when
    its read failed with "not found", the decrypted snapshot listing is empty AND the raw bucket
    listing (ciphertext names) is empty. The last check matters: with a wrong key an existing
    store also reads as "not found" and "empty", and initialising it would mix two keys.
    """
    result = runner(["cat", _crypt(SENTINEL_PATH)], {})
    # `rclone cat` on an object that does not exist exits 0 with no output: when the HEAD finds
    # nothing, rclone treats the path as an (empty) directory. No valid sentinel is empty, so
    # that outcome means "not found", the same as exit 3/4; the listing checks below still
    # guard against an existing store read with a wrong key.
    absent = result.returncode in _EXIT_NOT_FOUND or (
        result.returncode == 0 and not result.stdout.strip()
    )
    if result.returncode == 0 and not absent:
        if _sentinel_matches(result.stdout):
            return False
        raise RemoteError("refusing --init-remote: a sentinel exists but its content differs")
    if not absent:
        raise RemoteError(
            f"refusing --init-remote: sentinel read failed (rclone exit {result.returncode}): "
            f"{_excerpt(result.stderr)}"
        )
    snapshots = runner(["lsf", "--dirs-only", _crypt(f"{SNAPSHOTS_DIR}/")], {})
    if snapshots.returncode not in {0, *_EXIT_NOT_FOUND} or (
        snapshots.returncode == 0 and snapshots.stdout.strip()
    ):
        raise RemoteError("refusing --init-remote: the remote already holds snapshots")
    raw = runner(["lsf", raw_remote], {})
    if raw.returncode not in {0, *_EXIT_NOT_FOUND} or (raw.returncode == 0 and raw.stdout.strip()):
        raise RemoteError(
            "refusing --init-remote: the bucket is not empty (an existing store with a "
            "different crypt key looks exactly like this)"
        )
    with tempfile.TemporaryDirectory(prefix="backup-sentinel-") as scratch:
        local = Path(scratch) / "sentinel.txt"
        local.write_bytes(SENTINEL_CONTENT.encode("ascii"))
        _call(runner, ["copyto", str(local), _crypt(SENTINEL_PATH), "--immutable"])
    check_sentinel(runner)
    return True


# --------------------------------------------------------------------------- #
# Push
# --------------------------------------------------------------------------- #


def _snapshot_filters() -> list[str]:
    return [
        arg for name in (DEFAULT_PG_DUMP_NAME, MANIFEST_NAME) for arg in ("--include", f"/{name}")
    ]


def push_snapshot(bundle_root: Path, runner: RcloneRunner, *, now_utc: datetime) -> str:
    """Verify the bundle, push Parquet then the snapshot, cryptcheck it, return the snapshot id.

    Order is crash-safe: the sentinel is checked first, the append-only Parquet files go up
    next (``--immutable``: an existing remote file is never changed), then ``pg.dump`` and
    finally ``manifest.json``, so a snapshot only looks complete once everything it names is
    already on the remote. ``rclone cryptcheck`` then compares the snapshot against the local
    files; retention must not run before this returns.
    """
    problems = verify_bundle(bundle_root)
    if problems:
        raise RemoteError(
            f"refusing push: bundle verification failed ({len(problems)} problem(s)): "
            + "; ".join(problems[:5])
        )
    check_sentinel(runner)
    root = bundle_root.resolve()
    snap = snapshot_id(now_utc)
    snap_remote = _crypt(f"{SNAPSHOTS_DIR}/{snap}")
    if (root / PARQUET_DIR).is_dir():
        # --size-only: an object already on the remote is skipped on size, not modtime. A file
        # restored onto a new host has the same bytes (the manifest sha256 proves it) but not
        # necessarily the same mtime; --immutable alone would fail that as "file modified".
        # A same-named file of a different size is still an error.
        _call(
            runner,
            ["copy", str(root / PARQUET_DIR), _crypt(PARQUET_DIR), "--immutable", "--size-only"],
        )
    for name in (DEFAULT_PG_DUMP_NAME, MANIFEST_NAME):
        _call(runner, ["copyto", str(root / name), f"{snap_remote}/{name}", "--immutable"])
    _call(runner, ["cryptcheck", str(root), snap_remote, *_snapshot_filters()])
    return snap


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #


def list_snapshots(runner: RcloneRunner) -> list[str]:
    """Snapshot directory names (as listed, unparsed), sorted. Empty list when none exist.

    Callers must have passed ``check_sentinel`` first: only then is an empty result a true
    "no snapshots" rather than a wrong key.
    """
    result = _call(
        runner,
        ["lsf", "--dirs-only", _crypt(f"{SNAPSHOTS_DIR}/")],
        ok=frozenset({0, *_EXIT_NOT_FOUND}),
    )
    if result.returncode != 0:
        return []
    return sorted(line.strip().rstrip("/") for line in result.stdout.splitlines() if line.strip())


def list_complete_snapshots(runner: RcloneRunner) -> list[str]:
    """Snapshot ids whose ``manifest.json`` is on the remote, sorted.

    ``push_snapshot`` uploads the manifest last, so a directory without one is a push that
    died half way. One recursive listing answers it for every snapshot at once. Same caller
    contract as ``list_snapshots`` (sentinel first).
    """
    result = _call(
        runner,
        ["lsf", "--files-only", "-R", "--max-depth", "2", _crypt(f"{SNAPSHOTS_DIR}/")],
        ok=frozenset({0, *_EXIT_NOT_FOUND}),
    )
    if result.returncode != 0:
        return []
    complete: set[str] = set()
    for line in result.stdout.splitlines():
        snap, sep, name = line.strip().partition("/")
        if sep and name == MANIFEST_NAME and snap:
            complete.add(snap)
    return sorted(complete)


# --------------------------------------------------------------------------- #
# Pull
# --------------------------------------------------------------------------- #


def pull_snapshot(dest: Path, runner: RcloneRunner, *, snapshot: str | None = None) -> str:
    """Rebuild a verified bundle in ``dest`` from one snapshot; return the snapshot id.

    ``dest`` must not exist or be empty. The snapshot directory (``pg.dump`` + ``manifest.json``)
    is copied, then exactly the Parquet files its manifest names are fetched from the
    append-only ``parquet/`` tree (``--files-from-raw``, so nothing else is transferred), and the
    result is checked with ``verify_bundle``. A manifest that names a file the remote lacks,
    or any hash mismatch, fails here, before the caller can use the bundle.
    """
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise RemoteError(f"refusing pull: --dest {dest} must be an empty directory or not exist")
    check_sentinel(runner)
    names = list_snapshots(runner)
    if not names:
        raise RemoteError("no snapshots found on the remote; nothing to pull")
    complete = set(list_complete_snapshots(runner))
    if snapshot is None:
        parseable = [n for n in names if parse_snapshot_id(n) is not None]
        if not parseable:
            raise RemoteError("the remote holds no snapshot with a valid id")
        # A half-pushed snapshot (no manifest yet) is never "the newest": fall back to the
        # newest complete one instead of failing the restore on it.
        usable = [n for n in parseable if n in complete]
        if not usable:
            raise RemoteError("the remote holds no complete snapshot (none has a manifest.json)")
        chosen = max(usable)  # ids sort chronologically
    else:
        if parse_snapshot_id(snapshot) is None:
            raise RemoteError("--snapshot is not a valid snapshot id (YYYYMMDDTHHMMSSZ)")
        if snapshot not in names:
            raise RemoteError(f"snapshot {snapshot} not found on the remote")
        if snapshot not in complete:
            raise RemoteError(f"snapshot {snapshot} is incomplete on the remote (no manifest.json)")
        chosen = snapshot
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    _call(runner, ["copy", _crypt(f"{SNAPSHOTS_DIR}/{chosen}"), str(root)])
    manifest, problem = _read_manifest(root)
    if manifest is None:
        raise RemoteError(f"snapshot {chosen} is unusable: {problem}")
    parquet_prefix = f"{PARQUET_DIR}/"
    wanted: list[str] = []
    for key in sorted(manifest):
        if _is_unsafe_key(key):
            raise RemoteError(f"snapshot {chosen} is unusable: unsafe path in its manifest")
        if key.startswith(parquet_prefix):
            wanted.append(key[len(parquet_prefix) :])
    if wanted:
        with tempfile.TemporaryDirectory(prefix="backup-files-from-") as scratch:
            listing = Path(scratch) / "files-from.txt"
            listing.write_bytes(("\n".join(wanted) + "\n").encode("utf-8"))
            _call(
                runner,
                [
                    "copy",
                    _crypt(PARQUET_DIR),
                    str(root / PARQUET_DIR),
                    "--files-from-raw",
                    str(listing),
                ],
            )
    problems = verify_bundle(root)
    if problems:
        raise RemoteError(
            f"pulled bundle failed verification ({len(problems)} problem(s)): "
            + "; ".join(problems[:5])
        )
    return chosen


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #


def select_retained(
    names: Iterable[str],
    *,
    keep_daily: int = 7,
    keep_weekly: int = 4,
    keep_monthly: int = 6,
) -> tuple[frozenset[str], frozenset[str]]:
    """Return ``(keep, delete)`` for snapshot names under the 7/4/6 policy (D-12, D-17).

    For each granularity (UTC day, ISO year-week, calendar month) the newest snapshot of every
    period is a candidate and the newest N periods *that have a snapshot* are kept. Counting
    periods that exist, not periods before "now", means a silent backup outage can never age
    out the last good snapshots. The newest snapshot overall is always kept. Names that do not
    parse as ``YYYYMMDDTHHMMSSZ`` are in neither set, so they are never deleted. No clock is
    read: the result depends only on the names.
    """
    parsed: dict[str, datetime] = {}
    for name in names:
        stamp = parse_snapshot_id(name)
        if stamp is not None:
            parsed[name] = stamp
    if not parsed:
        return frozenset(), frozenset()
    ordered = sorted(parsed, key=lambda n: parsed[n])  # ascending; ids sort chronologically
    keep: set[str] = {ordered[-1]}
    granularities: tuple[tuple[Callable[[datetime], tuple[int, ...]], int], ...] = (
        (lambda d: (d.year, d.month, d.day), keep_daily),
        (lambda d: tuple(d.isocalendar())[:2], keep_weekly),
        (lambda d: (d.year, d.month), keep_monthly),
    )
    for period_of, count in granularities:
        newest_per_period: dict[tuple[int, ...], str] = {}
        for name in ordered:
            newest_per_period[period_of(parsed[name])] = name  # later overwrites earlier
        periods = sorted(newest_per_period)
        recent = periods[max(0, len(periods) - count) :] if count > 0 else []
        keep.update(newest_per_period[period] for period in recent)
    delete = frozenset(parsed) - keep
    return frozenset(keep), delete


@dataclass(frozen=True)
class RetentionReport:
    """What ``apply_retention`` kept and deleted (or would delete with ``dry_run``)."""

    kept: tuple[str, ...]
    deleted: tuple[str, ...]
    dry_run: bool


def apply_retention(runner: RcloneRunner, *, dry_run: bool) -> RetentionReport:
    """Delete snapshots outside the retention policy; only ever ``snapshots/<id>``.

    Order: sentinel check, listing, then ``rclone purge`` for each name in the delete set. An
    empty listing raises (after a passing sentinel it still means something is wrong, and an
    outage must never look like "nothing to do"). ``parquet/`` is never listed or touched.
    Callers run this only after the new snapshot passed ``cryptcheck``.

    Only complete snapshots (a ``manifest.json`` is present) count toward the 7/4/6 windows, so
    a half-pushed snapshot can never displace a good one. An incomplete directory older than the
    newest complete snapshot is garbage and is purged; a newer one may be a push in progress
    and is left alone.
    """
    check_sentinel(runner)
    names = list_snapshots(runner)
    if not names:
        raise RemoteError("no snapshots found on the remote; refusing to apply retention")
    complete = list_complete_snapshots(runner)
    keep, delete = select_retained(complete)
    complete_stamps = [stamp for n in complete if (stamp := parse_snapshot_id(n)) is not None]
    if complete_stamps:
        newest_complete = max(complete_stamps)
        complete_set = set(complete)
        stale_incomplete = {
            n
            for n in names
            if n not in complete_set
            and (stamp := parse_snapshot_id(n)) is not None
            and stamp < newest_complete
        }
        delete = frozenset(delete | stale_incomplete)
    ordered_delete = tuple(sorted(delete))
    if not dry_run:
        for name in ordered_delete:
            if parse_snapshot_id(name) is None:  # defence in depth; select_retained guarantees it
                raise RemoteError("refusing to purge a name that is not a snapshot id")
            result = runner(["purge", _crypt(f"{SNAPSHOTS_DIR}/{name}")], {})
            if result.returncode != 0:
                raise RemoteError(
                    f"rclone purge failed (exit {result.returncode}) for snapshot {name}: "
                    f"{_excerpt(result.stderr)}"
                )
    return RetentionReport(kept=tuple(sorted(keep)), deleted=ordered_delete, dry_run=dry_run)


# --------------------------------------------------------------------------- #
# CLI handlers (src.ops.backup dispatches here)
# --------------------------------------------------------------------------- #


def cli_push(
    bundle_root: Path,
    *,
    init_remote: bool,
    runner: RcloneRunner | None,
    now_utc: datetime | None,
) -> int:
    """``push``: optional ``--init-remote``, then verify, upload and cryptcheck one snapshot."""
    run = runner or make_rclone_runner(os.environ)
    if init_remote:
        written = init_sentinel(run, raw_remote=raw_bucket_remote(os.environ))
        print(f"init-OK sentinel={'written' if written else 'present'}")
    snap = push_snapshot(bundle_root, run, now_utc=now_utc or datetime.now(UTC))
    print(f"push-OK snapshot={snap}")
    return 0


def cli_retain(*, dry_run: bool, runner: RcloneRunner | None) -> int:
    """``retain``: apply the 7/4/6 policy to the remote snapshots."""
    run = runner or make_rclone_runner(os.environ)
    report = apply_retention(run, dry_run=dry_run)
    verb = "would delete" if report.dry_run else "deleted"
    print(
        f"retain-OK dry_run={report.dry_run} kept={len(report.kept)} {verb}={len(report.deleted)}"
    )
    for name in report.deleted:
        print(f"  {name}")
    return 0


def cli_pull(dest: Path, *, snapshot: str | None, runner: RcloneRunner | None) -> int:
    """``pull``: rebuild a verified bundle from the newest (or a named) snapshot."""
    run = runner or make_rclone_runner(os.environ)
    chosen = pull_snapshot(dest, run, snapshot=snapshot)
    print(f"pull-OK snapshot={chosen} dest={dest}")
    return 0


def cli_scheduled(
    bundle_root: Path,
    parquet_roots: Sequence[Path],
    *,
    runner: RcloneRunner | None,
    pg_dump_runner: PgDumpRunner,
    now_utc: datetime | None,
) -> int:
    """``scheduled``: backup -> verify -> push (+ cryptcheck) -> retention.

    Retention only runs after ``push_snapshot`` returned, i.e. after the new snapshot's
    ``cryptcheck`` passed; any earlier failure raises and exits non-zero without deleting.
    The rclone configuration is validated before ``pg_dump`` runs.
    """
    run = runner or make_rclone_runner(os.environ)
    backup(
        bundle_root=bundle_root,
        pg_dump_runner=pg_dump_runner,
        parquet_roots=tuple(parquet_roots),
    )
    problems = verify_bundle(bundle_root)
    if problems:
        raise RemoteError(
            f"staging bundle failed verification ({len(problems)} problem(s)): "
            + "; ".join(problems[:5])
        )
    snap = push_snapshot(bundle_root, run, now_utc=now_utc or datetime.now(UTC))
    report = apply_retention(run, dry_run=False)
    print(f"scheduled-OK snapshot={snap} kept={len(report.kept)} deleted={len(report.deleted)}")
    return 0


# --------------------------------------------------------------------------- #
# drill-remote: backup -> push -> pull -> verify -> pg_restore into a scratch database
# --------------------------------------------------------------------------- #

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MAX_IDENTIFIER = 63  # PostgreSQL truncates longer identifiers silently
WATERMARK_TABLE = "collector_watermarks"


@dataclass(frozen=True)
class DrillDatabaseOps:
    """Database operations of the drill, injectable so tests need no PostgreSQL."""

    create_database: Callable[[str, str], None]  # (source database URL, new database name)
    drop_database: Callable[[str, str], None]  # (source database URL, database name)
    count_watermarks: Callable[[str], int]  # (database URL) -> row count


def scratch_database_name(source_name: str | None, now_utc: datetime) -> str:
    """``<db>_drill_<YYYYMMDDHHMMSS>``, validated against a strict identifier pattern."""
    if not source_name or not _IDENTIFIER_RE.fullmatch(source_name):
        raise RemoteError("refusing drill: the source database name is not a plain identifier")
    name = f"{source_name}_drill_{now_utc.astimezone(UTC).strftime('%Y%m%d%H%M%S')}"
    if len(name) > _MAX_IDENTIFIER:
        raise RemoteError("refusing drill: the scratch database name would exceed 63 characters")
    return name


def _admin_engine(database_url: str) -> Any:
    from sqlalchemy import create_engine

    url = _sqlalchemy_url(database_url).set(database="postgres")
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _prod_create_database(database_url: str, name: str) -> None:
    from sqlalchemy import text

    if not _IDENTIFIER_RE.fullmatch(name):
        raise RemoteError("refusing to create a database with a non-identifier name")
    engine = _admin_engine(database_url)
    try:
        with engine.connect() as conn:
            quoted = engine.dialect.identifier_preparer.quote(name)
            conn.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        engine.dispose()


def _prod_drop_database(database_url: str, name: str) -> None:
    from sqlalchemy import text

    if not _IDENTIFIER_RE.fullmatch(name):
        raise RemoteError("refusing to drop a database with a non-identifier name")
    engine = _admin_engine(database_url)
    try:
        with engine.connect() as conn:
            quoted = engine.dialect.identifier_preparer.quote(name)
            conn.execute(text(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"))
    finally:
        engine.dispose()


def _prod_count_watermarks(database_url: str) -> int:
    from sqlalchemy import create_engine, text

    engine = create_engine(_sqlalchemy_url(database_url))
    try:
        with engine.connect() as conn:
            return int(conn.execute(text(f"SELECT count(*) FROM {WATERMARK_TABLE}")).scalar_one())
    finally:
        engine.dispose()


PROD_DRILL_OPS = DrillDatabaseOps(
    create_database=_prod_create_database,
    drop_database=_prod_drop_database,
    count_watermarks=_prod_count_watermarks,
)


def cli_drill_remote(
    bundle_root: Path,
    scratch_root: Path,
    parquet_roots: Sequence[Path],
    *,
    database_url: str | None,
    runner: RcloneRunner | None,
    pg_dump_runner: PgDumpRunner,
    pg_restore_runner: PgRestoreRunner,
    data_probe: DataProbe | None,
    ops: DrillDatabaseOps | None,
    now_utc: datetime | None,
) -> int:
    """``drill-remote``: prove the newest off-host backup restores into a scratch database.

    backup -> push -> pull into ``scratch_root`` -> verify -> create ``<db>_drill_<ts>`` ->
    pg_restore -> compare ``collector_watermarks`` row counts with the source -> drop the
    scratch database (always, in a ``finally``). Exit 0 only when the counts are equal.
    """
    if not database_url:
        print("drill-REFUSED: DATABASE_URL_SYNC / DATABASE_URL is not set", file=sys.stderr)
        return 1
    database_ops = ops or PROD_DRILL_OPS
    run = runner or make_rclone_runner(os.environ)
    now = now_utc or datetime.now(UTC)
    scratch_name = scratch_database_name(_sqlalchemy_url(database_url).database, now)
    _assert_safe_scratch_root(scratch_root, bundle_root)

    backup(
        bundle_root=bundle_root,
        pg_dump_runner=pg_dump_runner,
        parquet_roots=tuple(parquet_roots),
    )
    snap = push_snapshot(bundle_root, run, now_utc=now)
    pulled = pull_snapshot(scratch_root, run, snapshot=snap)  # verifies the pulled bundle

    scratch_url = _sqlalchemy_url(database_url).set(database=scratch_name)
    scratch_url_text = scratch_url.render_as_string(hide_password=False)
    created = False
    failed = False
    source_rows = scratch_rows = -1
    try:
        database_ops.create_database(database_url, scratch_name)
        created = True
        restore_database(
            scratch_root / DEFAULT_PG_DUMP_NAME,
            database_url=scratch_url_text,
            force=False,
            pg_restore_runner=pg_restore_runner,
            migrate_runner=None,
            data_probe=data_probe,
        )
        source_rows = database_ops.count_watermarks(database_url)
        scratch_rows = database_ops.count_watermarks(scratch_url_text)
    except BaseException:
        failed = True
        raise
    finally:
        if created:
            try:
                database_ops.drop_database(database_url, scratch_name)
            except Exception as drop_exc:
                if not failed:
                    raise
                print(
                    f"warning: could not drop scratch database: {_excerpt(str(drop_exc))}",
                    file=sys.stderr,
                )
    if source_rows != scratch_rows:
        print(
            f"drill-remote-FAILED snapshot={pulled} {WATERMARK_TABLE} rows "
            f"source={source_rows} restored={scratch_rows}",
            file=sys.stderr,
        )
        return 1
    print(
        f"drill-remote-OK snapshot={pulled} {WATERMARK_TABLE}_rows={scratch_rows} "
        f"scratch_db={scratch_name} scratch_root={scratch_root}"
    )
    return 0
