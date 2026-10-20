"""D064 real-S3 gate: the detection claims of the Parquet push, run against the configured remote.

D064 accepts the push design (manifest SHA-256 comparison plus a ``cryptcheck`` before the
manifest is published) only after its detection claims have been shown on a real S3 remote
through the crypt layer, multipart objects included (RUNBOOK 11, "Real-S3 gate"; D066 lists the
proof as still open). This module runs those claims as one re-runnable procedure:

* The remote is the one the backup uses, built by the same code path (``rclone_env`` of
  ``src.ops.backup_remote``), so a backend added there later is gated unchanged. The gate never
  touches the backup data: every object it writes lives under a throwaway prefix
  ``d064-gate-<UTC>-<12 hex>`` directly below the configured bucket. The prefix holds ``-`` and
  upper-case letters, which rclone's default crypt name encoding (lower-case base32) never
  produces, so it cannot collide with an encrypted name of the backup itself. The prefix must
  be empty before the gate writes anything, and it is purged in every exit path.
* Each scenario gets its own crypt root ``<prefix>/<scenario>`` with its own sentinel, so the
  scenarios cannot see each other's snapshots.
* Nothing runs without ``execute=True``: the default prints the plan and touches nothing.
* The evidence lists every claim with PASS or FAIL. No secret value is printed: rclone output
  is scrubbed, and the bucket name is replaced by ``<bucket>``.

Exit codes: 0 every claim passed, 1 a claim failed (or the run was interrupted), 2 a usage or
configuration error (nothing was touched).
"""

from __future__ import annotations

import os
import re
import secrets
import signal
import tempfile
import types
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

from src.ops.backup import MANIFEST_NAME, backup, verify_bundle
from src.ops.backup_remote import (
    CRYPT_REMOTE,
    HEAD_PARQUET_DIFFERENT,
    HEAD_PARQUET_ORPHAN,
    HEAD_PARQUET_VERIFY,
    PARQUET_DIR,
    REMOTE_NONE,
    SNAPSHOTS_DIR,
    RcloneResult,
    RcloneRunner,
    RemoteConfigError,
    RemoteError,
    force_multipart_env,
    init_sentinel,
    list_complete_snapshots,
    make_rclone_runner,
    pull_snapshot,
    push_snapshot,
    raw_bucket_remote,
    rclone_env,
    remote_mode,
)
from src.ops.redaction import scrub

PREFIX_RE = re.compile(r"d064-gate-\d{8}T\d{6}Z-[0-9a-f]{12}")
DEFAULT_MULTIPART_MIB = 12
MIN_MULTIPART_MIB = 6  # above the forced 5 MiB cutoff, so the object is at least two parts
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
_EXIT_LSF_NOT_FOUND = 3
_SOURCE = "raw"  # the Parquet root basename of every gate bundle (keys parquet/raw/...)

# (id, what the claim shows); the order is the order of the evidence.
CLAIMS: tuple[tuple[str, str], ...] = (
    ("upload-new-paths", "new Parquet paths are uploaded and the snapshot becomes complete"),
    ("skip-unchanged", "an unchanged Parquet file is skipped by the manifest SHA-256 comparison"),
    (
        "refuse-changed-same-size",
        "a published path changed locally with the same size is refused, nothing uploaded",
    ),
    (
        "refuse-changed-other-size",
        "a published path changed locally with another size is refused, nothing uploaded",
    ),
    ("upload-only-new-path", "a new path next to published ones uploads only the new path"),
    ("pull-round-trip", "the newest complete snapshot pulls back and verifies"),
    ("adopt-identical-orphan", "an object left by an interrupted push is adopted when identical"),
    ("refuse-different-orphan", "an object left by an interrupted push is refused when different"),
    (
        "detect-modified-through-crypt",
        "cryptcheck detects a remote object changed through the crypt layer after upload",
    ),
    (
        "detect-modified-at-provider",
        "cryptcheck detects a ciphertext object overwritten at the provider after upload",
    ),
    ("detect-deleted", "cryptcheck detects a remote object deleted after upload"),
    (
        "upload-then-check-failure-incomplete",
        "a check failure right after the upload leaves the snapshot incomplete",
    ),
    (
        "failed-manifest-check-removed",
        "a manifest that fails its own check is removed and the snapshot stays incomplete",
    ),
    ("multipart-upload-verified", "a multipart object through crypt uploads and verifies"),
    ("multipart-unchanged-passes", "an unchanged multipart object passes the next push"),
    ("multipart-modified-detected", "cryptcheck detects a changed multipart object"),
    ("cleanup", "the throwaway prefix is purged and lists empty afterwards"),
)
CLAIM_IDS: tuple[str, ...] = tuple(claim for claim, _ in CLAIMS)


class GateUsageError(Exception):
    """A usage or configuration error: exit 2, nothing on the remote was touched."""


class _Interrupted(Exception):
    """A simulated process death after a matching rclone call (an interrupted push)."""


@dataclass(frozen=True)
class GateRemote:
    """How the gate reaches the remote.

    ``runner_for(subpath)`` is a runner whose crypt remote is rooted at ``<bucket>/<subpath>``
    (raw remote calls work through any of them); ``raw_for(subpath)`` is the un-encrypted remote
    path of the same place. Tests inject a directory-backed fake.
    """

    runner_for: Callable[[str], RcloneRunner]
    raw_for: Callable[[str], str]


def production_remote(environ: Mapping[str, str]) -> GateRemote:
    """The configured remote, built by the backup's own environment mapping."""
    return GateRemote(
        runner_for=lambda sub: make_rclone_runner(environ, subpath=sub),
        raw_for=lambda sub: raw_bucket_remote(environ, subpath=sub),
    )


def new_prefix(now_utc: datetime, token: str | None = None) -> str:
    """``d064-gate-<YYYYMMDDTHHMMSSZ>-<12 hex>``: unique per run (time plus 48 random bits)."""
    tail = token if token is not None else secrets.token_hex(6)
    prefix = f"d064-gate-{now_utc.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}-{tail}"
    if not PREFIX_RE.fullmatch(prefix):
        raise GateUsageError("the gate prefix must look like d064-gate-<UTC>-<12 hex>")
    return prefix


@dataclass
class ClaimResult:
    claim: str
    passed: bool
    detail: str


@dataclass
class _Recorder:
    """Wraps a runner: records argv, the ``--files-from-raw`` lists, and runs hooks after calls."""

    inner: RcloneRunner
    extra: Mapping[str, str] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    lists: dict[int, list[str]] = field(default_factory=dict)
    hooks: list[tuple[Callable[[Sequence[str]], bool], Callable[[], None]]] = field(
        default_factory=list
    )

    def __call__(self, argv: Sequence[str], extra: Mapping[str, str]) -> RcloneResult:
        args = list(argv)
        if "--files-from-raw" in args:  # the adapter deletes the list file after the call
            listing = Path(args[args.index("--files-from-raw") + 1])
            self.lists[len(self.calls)] = listing.read_text(encoding="utf-8").splitlines()
        self.calls.append(args)
        result = self.inner(args, {**self.extra, **extra})
        for match, action in list(self.hooks):
            if match(args):
                self.hooks.remove((match, action))
                action()
        return result

    def parquet_uploads(self, start: int) -> list[str]:
        """Paths of every Parquet upload (``copy`` local -> crypt ``parquet``) since ``start``."""
        out: list[str] = []
        for index in range(start, len(self.calls)):
            call = self.calls[index]
            if call[0] == "copy" and call[2] == f"{CRYPT_REMOTE}:{PARQUET_DIR}":
                out.extend(self.lists.get(index, ["<whole tree>"]))
        return out

    def writes(self, start: int) -> list[list[str]]:
        mutating = {"copy", "copyto", "deletefile", "purge", "sync", "move", "moveto"}
        return [call for call in self.calls[start:] if call[0] in mutating]


def _text(nbytes: int) -> bytes:
    """``nbytes`` of random lower-case hex text (readable back with ``rclone cat``)."""
    return os.urandom((nbytes + 1) // 2).hex()[:nbytes].encode("ascii")


def _fake_dump(out: Path) -> Path:
    """The gate does not need the database: a fixed small file stands in for ``pg.dump``."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"d064 gate stand-in for pg.dump\n" * 32)
    return out


class _Work:
    """Local bundles below one scratch directory; every bundle's Parquet root is ``raw``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.count = 0

    def bundle(self, files: Mapping[str, bytes]) -> Path:
        self.count += 1
        source = self.root / f"src{self.count}" / _SOURCE
        source.mkdir(parents=True)
        for rel, data in files.items():
            target = source / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        bundle_root = self.root / f"bundle{self.count}"
        backup(bundle_root=bundle_root, pg_dump_runner=_fake_dump, parquet_roots=[source])
        return bundle_root

    def scratch(self, name: str) -> Path:
        self.count += 1
        return self.root / f"{name}{self.count}"

    def file(self, data: bytes) -> Path:
        self.count += 1
        path = self.root / f"blob{self.count}.bin"
        path.write_bytes(data)
        return path


def _crypt(path: str) -> str:
    return f"{CRYPT_REMOTE}:{path}"


def _parquet_object(rel: str) -> str:
    return _crypt(f"{PARQUET_DIR}/{_SOURCE}/{rel}")


def _harness(runner: RcloneRunner, argv: Sequence[str]) -> None:
    """A gate-side call (a tamper step), never a product call: any failure is a harness error."""
    result = runner(list(argv), {})
    if result.returncode != 0:
        raise RemoteError(
            f"gate harness step rclone {argv[0]} failed (exit {result.returncode}): "
            f"{' '.join(scrub(result.stderr).split())[-300:]}"
        )


def _overwrite_through_crypt(runner: RcloneRunner, work: _Work, rel: str, size: int) -> None:
    """Replace a remote object through the crypt layer with other text of the same size."""
    _harness(
        runner, ["copyto", str(work.file(_text(size))), _parquet_object(rel), "--ignore-times"]
    )
    readback = runner(["cat", _parquet_object(rel)], {})
    if readback.returncode != 0:
        raise RemoteError(f"gate harness: the changed object {rel} cannot be read back")


def _push_error(
    bundle_root: Path, runner: RcloneRunner, now_utc: datetime
) -> tuple[str | None, str]:
    """``(None, snapshot id)`` when the push passed, ``(message, snapshot id)`` when it raised."""
    snap = now_utc.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    try:
        return None, push_snapshot(bundle_root, runner, now_utc=now_utc)
    except RemoteError as exc:
        return str(exc), snap


def _head(message: str | None) -> str:
    if message is None:
        return "push passed"
    return " ".join(scrub(message).split())[:160]


class _Gate:
    """The scenarios. Every claim records its own result; a scenario that breaks marks the
    claims it did not reach as FAIL with the reason."""

    def __init__(self, remote: GateRemote, prefix: str, work: _Work, *, multipart_bytes: int):
        self.remote = remote
        self.prefix = prefix
        self.work = work
        self.multipart_bytes = multipart_bytes
        self.results: dict[str, ClaimResult] = {}
        self.clock = datetime(2000, 1, 1, tzinfo=UTC)

    # -- helpers ---------------------------------------------------------------------------

    def tick(self) -> datetime:
        self.clock += timedelta(seconds=1)
        return self.clock

    def record(self, claim: str, passed: bool, detail: str) -> None:
        self.results[claim] = ClaimResult(claim, passed, detail)

    def scenario(self, name: str, extra: Mapping[str, str] | None = None) -> _Recorder:
        sub = f"{self.prefix}/{name}"
        runner = _Recorder(self.remote.runner_for(sub), extra=dict(extra or {}))
        if not init_sentinel(runner, raw_remote=self.remote.raw_for(sub)):
            raise RemoteError(f"scenario {name}: its crypt root already held a sentinel")
        return runner

    def complete(self, runner: RcloneRunner, snap: str) -> bool:
        return snap in list_complete_snapshots(runner)

    def run(self, name: str, claims: Sequence[str], body: Callable[[], None]) -> None:
        try:
            body()
        except _Interrupted:
            raise
        except (RemoteError, OSError, ValueError) as exc:
            reason = f"scenario {name} stopped: {_head(str(exc))}"
            for claim in claims:
                if claim not in self.results:
                    self.record(claim, False, reason)

    # -- scenarios -------------------------------------------------------------------------

    def manifest_scenario(self) -> None:
        run = self.scenario("s1-manifest")
        files = {
            "date=2026-01-01/a.parquet": _text(48 * 1024),
            "date=2026-01-02/b.parquet": _text(40 * 1024),
        }
        first = self.work.bundle(files)
        mark = len(run.calls)
        error, snap = _push_error(first, run, self.tick())
        uploaded = sorted(run.parquet_uploads(mark))
        expected = sorted(f"{_SOURCE}/{rel}" for rel in files)
        self.record(
            "upload-new-paths",
            error is None and uploaded == expected and self.complete(run, snap),
            f"{_head(error)}; uploaded {len(uploaded)} of {len(expected)} new paths",
        )
        mark = len(run.calls)
        error, snap = _push_error(first, run, self.tick())
        again = run.parquet_uploads(mark)
        self.record(
            "skip-unchanged",
            error is None and again == [] and self.complete(run, snap),
            f"{_head(error)}; Parquet uploads in the second push: {len(again)}",
        )
        for claim, size in (
            ("refuse-changed-same-size", 48 * 1024),
            ("refuse-changed-other-size", 47 * 1024),
        ):
            changed = self.work.bundle({**files, "date=2026-01-01/a.parquet": _text(size)})
            mark = len(run.calls)
            error, snap = _push_error(changed, run, self.tick())
            writes = run.writes(mark)
            self.record(
                claim,
                error is not None
                and error.startswith(HEAD_PARQUET_DIFFERENT)
                and writes == []
                and not self.complete(run, snap),
                f"{_head(error)}; remote writes: {len(writes)}",
            )
        grown = self.work.bundle({**files, "date=2026-01-03/c.parquet": _text(30 * 1024)})
        mark = len(run.calls)
        error, snap = _push_error(grown, run, self.tick())
        uploaded = run.parquet_uploads(mark)
        self.record(
            "upload-only-new-path",
            error is None
            and uploaded == [f"{_SOURCE}/date=2026-01-03/c.parquet"]
            and self.complete(run, snap),
            f"{_head(error)}; uploaded {len(uploaded)} path(s)",
        )
        dest = self.work.scratch("pull")
        pulled = pull_snapshot(dest, run)
        problems = verify_bundle(dest)
        self.record(
            "pull-round-trip",
            pulled == snap and problems == [],
            f"pulled the newest complete snapshot: {pulled == snap}; problems: {len(problems)}",
        )

    def orphan_scenario(self) -> None:
        run = self.scenario("s2-orphan")
        files = {"date=2026-02-01/a.parquet": _text(20 * 1024)}
        bundle_root = self.work.bundle(files)
        self._interrupted_push(run, bundle_root)
        mark = len(run.calls)
        error, snap = _push_error(bundle_root, run, self.tick())
        uploads = run.parquet_uploads(mark)
        adopted = any(
            call[0] == "cryptcheck" and "--files-from-raw" in call for call in run.calls[mark:]
        )
        self.record(
            "adopt-identical-orphan",
            error is None and uploads == [] and adopted and self.complete(run, snap),
            f"{_head(error)}; uploads: {len(uploads)}; adoption check ran: {adopted}",
        )
        rel = "date=2026-02-02/g.parquet"
        self._interrupted_push(run, self.work.bundle({**files, rel: _text(24 * 1024)}))
        other = self.work.bundle({**files, rel: _text(24 * 1024)})
        mark = len(run.calls)
        error, snap = _push_error(other, run, self.tick())
        self.record(
            "refuse-different-orphan",
            error is not None
            and error.startswith(HEAD_PARQUET_ORPHAN)
            and run.parquet_uploads(mark) == []
            and not self.complete(run, snap),
            _head(error),
        )

    def _interrupted_push(self, run: _Recorder, bundle_root: Path) -> None:
        """A push that dies right after its Parquet upload (before ``pg.dump`` and the manifest)."""

        def is_upload(argv: Sequence[str]) -> bool:
            return argv[0] == "copy" and argv[2] == _crypt(PARQUET_DIR)

        def die() -> None:
            raise _Interrupted

        run.hooks.append((is_upload, die))
        try:
            push_snapshot(bundle_root, run, now_utc=self.tick())
        except _Interrupted:
            return
        raise RemoteError("gate harness: the interrupted push did not upload anything")

    def _published(self, name: str, files: Mapping[str, bytes]) -> tuple[_Recorder, Path]:
        run = self.scenario(name)
        bundle_root = self.work.bundle(files)
        error, snap = _push_error(bundle_root, run, self.tick())
        if error is not None or not self.complete(run, snap):
            raise RemoteError(f"the first push of scenario {name} failed: {_head(error)}")
        return run, bundle_root

    def _expect_verify_failure(self, claim: str, run: _Recorder, bundle_root: Path) -> None:
        error, snap = _push_error(bundle_root, run, self.tick())
        self.record(
            claim,
            error is not None
            and error.startswith(HEAD_PARQUET_VERIFY)
            and not self.complete(run, snap),
            _head(error),
        )

    def modified_through_crypt_scenario(self) -> None:
        files = {"date=2026-03-01/a.parquet": _text(16 * 1024)}
        run, bundle_root = self._published("s3-crypt-modify", files)
        _overwrite_through_crypt(run, self.work, "date=2026-03-01/a.parquet", 16 * 1024)
        self._expect_verify_failure("detect-modified-through-crypt", run, bundle_root)

    def modified_at_provider_scenario(self) -> None:
        big = "date=2026-04-01/big.parquet"
        files = {big: _text(256 * 1024), "date=2026-04-02/small.parquet": _text(8 * 1024)}
        run, bundle_root = self._published("s4-provider-modify", files)
        raw = self.remote.raw_for(f"{self.prefix}/s4-provider-modify")
        listing = run(["lsf", "-R", "--files-only", "--format", "ps", "--separator", ";", raw], {})
        if listing.returncode != 0:
            raise RemoteError(f"gate harness: raw listing failed (exit {listing.returncode})")
        sized: list[tuple[int, str]] = []
        for line in listing.stdout.splitlines():
            name, sep, length = line.rpartition(";")
            if sep and length.strip().isdigit():
                sized.append((int(length), name))
        sized.sort(reverse=True)
        if len(sized) < 2 or sized[0][0] <= 2 * sized[1][0]:
            raise RemoteError("gate harness: the largest ciphertext object is not unambiguous")
        largest, target = sized[0]
        _harness(
            run,
            [
                "copyto",
                str(self.work.file(os.urandom(largest))),
                f"{raw}/{target}",
                "--ignore-times",
            ],
        )
        self._expect_verify_failure("detect-modified-at-provider", run, bundle_root)

    def deleted_scenario(self) -> None:
        rel = "date=2026-05-01/a.parquet"
        run, bundle_root = self._published("s5-delete", {rel: _text(12 * 1024)})
        _harness(run, ["deletefile", _parquet_object(rel)])
        self._expect_verify_failure("detect-deleted", run, bundle_root)

    def in_push_scenario(self) -> None:
        run = self.scenario("s6-in-push")
        rel = "date=2026-06-01/a.parquet"
        bundle_root = self.work.bundle({rel: _text(10 * 1024)})

        def is_upload(argv: Sequence[str]) -> bool:
            return argv[0] == "copy" and argv[2] == _crypt(PARQUET_DIR)

        run.hooks.append(
            (is_upload, lambda: _overwrite_through_crypt(run.inner, self.work, rel, 10 * 1024))
        )
        self._expect_verify_failure("upload-then-check-failure-incomplete", run, bundle_root)

    def manifest_check_scenario(self) -> None:
        run = self.scenario("s7-manifest")
        bundle_root = self.work.bundle({"date=2026-07-01/a.parquet": _text(10 * 1024)})
        size = (bundle_root / MANIFEST_NAME).stat().st_size

        def is_manifest_upload(argv: Sequence[str]) -> bool:
            return (
                argv[0] == "copyto"
                and argv[2].startswith(_crypt(f"{SNAPSHOTS_DIR}/"))
                and argv[2].endswith(f"/{MANIFEST_NAME}")
            )

        def corrupt_manifest() -> None:
            target = next(c[2] for c in reversed(run.calls) if is_manifest_upload(c))
            _harness(
                run.inner, ["copyto", str(self.work.file(_text(size))), target, "--ignore-times"]
            )

        run.hooks.append((is_manifest_upload, corrupt_manifest))
        error, snap = _push_error(bundle_root, run, self.tick())
        removed = any(call[0] == "deletefile" for call in run.calls)
        self.record(
            "failed-manifest-check-removed",
            error is not None
            and error.startswith(f"manifest verification failed: snapshot {snap} left incomplete")
            and removed
            and not self.complete(run, snap),
            f"{_head(error)}; manifest removal issued: {removed}",
        )

    def multipart_scenario(self, extra: Mapping[str, str]) -> None:
        run = self.scenario("s8-multipart", extra)
        rel = "date=2026-08-01/m.parquet"
        files = {rel: _text(self.multipart_bytes), "date=2026-08-02/s.parquet": _text(4 * 1024)}
        bundle_root = self.work.bundle(files)
        error, snap = _push_error(bundle_root, run, self.tick())
        self.record(
            "multipart-upload-verified",
            error is None and self.complete(run, snap),
            f"{_head(error)}; {self.multipart_bytes} bytes",
        )
        error, snap = _push_error(bundle_root, run, self.tick())
        self.record(
            "multipart-unchanged-passes",
            error is None and self.complete(run, snap),
            _head(error),
        )
        _overwrite_through_crypt(run, self.work, rel, self.multipart_bytes)
        self._expect_verify_failure("multipart-modified-detected", run, bundle_root)


@dataclass(frozen=True)
class GateOutcome:
    lines: tuple[str, ...]
    exit_code: int


def _redact(text: str, bucket: str) -> str:
    text = scrub(text)
    return text.replace(bucket, "<bucket>") if bucket else text


@contextmanager
def _sigterm_as_interrupt() -> Iterator[None]:
    """SIGTERM (docker stop, systemd) becomes KeyboardInterrupt so the cleanup still runs."""

    def handler(signum: int, frame: types.FrameType | None) -> None:
        raise KeyboardInterrupt

    try:
        previous = signal.signal(signal.SIGTERM, handler)
    except ValueError:  # not the main thread (a test runner): nothing to install
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _precheck_empty(remote: GateRemote, prefix: str) -> None:
    """The prefix must not exist yet: a listing that is not "not found" or empty refuses."""
    raw = remote.raw_for(prefix)
    result = remote.runner_for(prefix)(["lsf", "-R", "--files-only", raw], {})
    if result.returncode == _EXIT_LSF_NOT_FOUND or (
        result.returncode == 0 and not result.stdout.strip()
    ):
        return
    if result.returncode == 0:
        raise GateUsageError(
            f"refusing: the prefix {prefix} already holds objects; the gate only runs on a new, "
            "empty throwaway prefix"
        )
    raise GateUsageError(
        f"refusing: the prefix {prefix} could not be listed (rclone exit {result.returncode}); "
        "nothing was written"
    )


def _cleanup(remote: GateRemote, prefix: str) -> ClaimResult:
    if not PREFIX_RE.fullmatch(prefix):  # defence in depth: never purge anything else
        return ClaimResult("cleanup", False, "refused to purge a path that is not a gate prefix")
    raw = remote.raw_for(prefix)
    if not raw.endswith(f"/{prefix}"):
        return ClaimResult("cleanup", False, "refused to purge: unexpected raw remote path")
    runner = remote.runner_for(prefix)
    purged = runner(["purge", raw], {})
    after = runner(["lsf", "-R", "--files-only", raw], {})
    empty = after.returncode == _EXIT_LSF_NOT_FOUND or (
        after.returncode == 0 and not after.stdout.strip()
    )
    detail = f"purge exit {purged.returncode}; listing afterwards exit {after.returncode}"
    if not empty:
        detail += f"; remove the prefix {prefix} below the bucket by hand"
    return ClaimResult("cleanup", empty, detail)


def plan_lines(prefix: str, multipart_bytes: int) -> list[str]:
    lines = [
        f"prefix: {prefix} (throwaway, below the configured bucket; purged at the end)",
        f"multipart arm: {multipart_bytes} bytes with upload_cutoff and chunk_size forced to 5 MiB",
    ]
    lines.extend(f"CLAIM {claim}: PLANNED - {text}" for claim, text in CLAIMS)
    return lines


def run_gate(
    *,
    environ: Mapping[str, str],
    execute: bool,
    prefix: str | None,
    multipart_bytes: int,
    remote: GateRemote | None = None,
    now_utc: datetime | None = None,
    rclone_version: Callable[[], str] | None = None,
) -> GateOutcome:
    """Validate the configuration, then print the plan (default) or run every claim."""
    now = now_utc or datetime.now(UTC)
    if remote_mode(environ) == REMOTE_NONE:
        raise GateUsageError(
            "BACKUP_REMOTE=none (local-only mode): there is no remote to gate; configure the "
            "remote (RUNBOOK 11.1) first"
        )
    rclone_env(environ)  # every missing variable is named here, before anything else
    bucket = environ.get("BACKUP_S3_BUCKET", "")
    if prefix is None:
        prefix = new_prefix(now)
    elif not PREFIX_RE.fullmatch(prefix):
        raise GateUsageError(
            "--prefix must look like d064-gate-<YYYYMMDDTHHMMSSZ>-<12 hex> (a throwaway prefix)"
        )
    header = [
        "D064 REAL-S3 GATE",
        f"started_utc: {now.astimezone(UTC).isoformat()}",
        f"remote: BACKUP_REMOTE={environ.get('BACKUP_REMOTE', '') or 's3'} "
        f"provider={environ.get('BACKUP_S3_PROVIDER', '')} "
        f"region={environ.get('BACKUP_S3_REGION', '')} bucket=<bucket>",
    ]
    if not execute:
        lines = [*header, "mode: DRY RUN (nothing was touched; add --execute to run)"]
        lines.extend(plan_lines(prefix, multipart_bytes))
        return GateOutcome(tuple(_redact(line, bucket) for line in lines), EXIT_OK)

    gate_remote = remote or production_remote(environ)
    _precheck_empty(gate_remote, prefix)
    lines = [*header, "mode: EXECUTE"]
    if rclone_version is not None:
        lines.append(f"rclone: {rclone_version()}")
    lines.extend(plan_lines(prefix, multipart_bytes)[:2])
    results: dict[str, ClaimResult] = {}
    interrupted = False
    with tempfile.TemporaryDirectory(prefix="d064-gate-") as scratch, _sigterm_as_interrupt():
        gate = _Gate(gate_remote, prefix, _Work(Path(scratch)), multipart_bytes=multipart_bytes)
        try:
            gate.run("s1", CLAIM_IDS[0:6], gate.manifest_scenario)
            gate.run("s2", CLAIM_IDS[6:8], gate.orphan_scenario)
            gate.run("s3", ("detect-modified-through-crypt",), gate.modified_through_crypt_scenario)
            gate.run("s4", ("detect-modified-at-provider",), gate.modified_at_provider_scenario)
            gate.run("s5", ("detect-deleted",), gate.deleted_scenario)
            gate.run("s6", ("upload-then-check-failure-incomplete",), gate.in_push_scenario)
            gate.run("s7", ("failed-manifest-check-removed",), gate.manifest_check_scenario)
            gate.run(
                "s8",
                CLAIM_IDS[13:16],
                lambda: gate.multipart_scenario(force_multipart_env(environ)),
            )
        except (KeyboardInterrupt, _Interrupted):
            interrupted = True
        finally:
            results.update(gate.results)
            results["cleanup"] = _cleanup(gate_remote, prefix)
    for claim, text in CLAIMS:
        result = results.get(claim) or ClaimResult(claim, False, "not reached")
        verdict = "PASS" if result.passed else "FAIL"
        lines.append(f"CLAIM {claim}: {verdict} - {text} ({result.detail})")
    passed = not interrupted and all(
        results.get(c, ClaimResult(c, False, "")).passed for c in CLAIM_IDS
    )
    if interrupted:
        lines.append("INTERRUPTED: the run was stopped before every claim was checked")
    lines.append(f"finished_utc: {datetime.now(UTC).isoformat()}")
    lines.append(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return GateOutcome(
        tuple(_redact(line, bucket) for line in lines), EXIT_OK if passed else EXIT_FAIL
    )


def _production_rclone_version(environ: Mapping[str, str]) -> Callable[[], str]:
    def version() -> str:
        result = make_rclone_runner(environ)(["version"], {})
        first = result.stdout.splitlines()[0] if result.stdout.strip() else ""
        return first or f"unknown (rclone version exit {result.returncode})"

    return version


def cli_real_s3_gate(
    *,
    execute: bool,
    prefix: str | None,
    evidence: Path | None,
    multipart_mib: int,
    remote: GateRemote | None,
    now_utc: datetime | None,
    out: TextIO,
    err: TextIO,
    environ: Mapping[str, str] | None = None,
) -> int:
    """``real-s3-gate``: the evidence goes to stdout (and to ``evidence`` when given)."""
    env = os.environ if environ is None else environ
    try:
        if multipart_mib < MIN_MULTIPART_MIB:
            raise GateUsageError(f"--multipart-mib must be at least {MIN_MULTIPART_MIB}")
        if evidence is not None and evidence.exists():
            raise GateUsageError(f"refusing: the evidence file {evidence} already exists")
        outcome = run_gate(
            environ=env,
            execute=execute,
            prefix=prefix,
            multipart_bytes=multipart_mib * 1024 * 1024,
            remote=remote,
            now_utc=now_utc,
            rclone_version=None if remote is not None else _production_rclone_version(env),
        )
    except (GateUsageError, RemoteConfigError) as exc:
        print(f"real-s3-gate refused (exit {EXIT_USAGE}): {scrub(str(exc))}", file=err)
        return EXIT_USAGE
    text = "\n".join(outcome.lines) + "\n"
    out.write(text)
    if evidence is not None and execute:
        evidence.parent.mkdir(parents=True, exist_ok=True)
        with evidence.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    return outcome.exit_code
