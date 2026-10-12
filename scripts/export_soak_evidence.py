"""Export one epoch of the soak trial as a verifiable evidence bundle (Phase 16, plan 16-30).

    python scripts/export_soak_evidence.py --source {pg,fixture} --epoch <epoch_id>
        --pinned <pinned_epoch.json> [--pinned ...] --diff-log <registry_diff.jsonl>
        --github-runs <runs.json> --config <paper-runtime.toml> [--workflow <yml>]
        --window-start <UTC ISO> --window-end <UTC ISO> --out <new directory>
        [--records <runtime_records.jsonl>]        (fixture source only)
        [--analytics-inputs <analytics_inputs.json>]

The output is one `soak-evidence-bundle/1` directory (layout and loader: `src/paper/
evidence_bundle.py`, plan 16-25) that `scripts/evaluate_trial_soak.py` accepts. The script is
location-agnostic until `--publish`: it writes a local directory, and the optional publishing
step (plan 16-47) copies it to the one durable location the user recorded at O-01.

Publishing (decision `16-DEC-O-01`, option a: an S3 evidence prefix OUTSIDE the backup crypt
remote, versioning enabled, no Object Lock, written by the exporter on the operator's schedule):

    python scripts/export_soak_evidence.py ... --out <new dir> --publish <remote:bucket/prefix>
    python scripts/export_soak_evidence.py publish --bundle <dir> --destination <remote:bkt/prefix>

- The destination is an rclone remote spec chosen by the operator at run time; the repository
  holds no default and no new configuration name. The credential of that remote lives in the
  operator's rclone configuration or environment, never in argv: a destination that carries a
  credential, the backup remotes (`BACKUPS3`, `BACKUPS3CRYPT`), a local path or a drive letter
  is a usage error before anything is exported or uploaded.
- Objects go to `<destination>/<epoch_id>/<file>`: every file first, `manifest.json` last. An
  epoch prefix that already holds a manifest is never published over; an object that already
  exists is left alone only when its bytes are identical (an interrupted earlier publish) and
  is never replaced. Each upload uses rclone `--immutable`.
- After the upload every published object is read back and checked against the manifest sha256;
  a mismatch or an unreadable object exits 4 and names the file (never its content).
- No digest file for the Git repository is written: that belongs to options b and e, which are
  not recorded.

What it does, and what it never does:

- One bundle is ONE epoch. The runtime records are those of `--epoch` only (every
  `RuntimeEventType`, `PAPER_REPLAY_INPUTS` and `PAPER_HISTORY_BARS` included: the port is asked
  with no event-type filter). The freeze lines (`registry_diff.jsonl`) and the GitHub run list are
  copied whole, byte for byte, whatever the epoch: nothing of another epoch is dropped, edited or
  filtered, so exporting an earlier epoch after a new pin gives a complete bundle for that epoch
  next to the new one (REV-18, earlier evidence is auxiliary and stays readable).
- `pinned_epoch.json` is the `--pinned` file whose epoch_id is `--epoch` (pass the current file and
  the archived ones; exactly one must match), copied byte for byte.
- EVIDENCE_GAP records come from `freeze_evidence_report` (the cron string is read from the
  freeze workflow file, the grace from the ratified configuration, `detected_at_utc` is the window
  end, exactly as the evaluator calls it) and go to `evidence_gaps.jsonl`. They are never written
  into `registry_diff.jsonl` (REV-02).
- The proof class follows the source and nothing else: `--source fixture` reads `--records` and
  writes manifest source "fixture"; `--source pg` reads the runtime state port (the soak
  PostgreSQL through `DATABASE_URL_SYNC` / `DATABASE_URL`, the allowed names of
  `src/paper/runtime_config.py`) and writes manifest source "pg". A records file cannot back a pg
  bundle and a state port cannot back a fixture bundle.
- Every file is scanned with the `src/ops/redaction` scrubber before the manifest is written; a
  finding aborts the export, removes the partial bundle and names the file, never the value. The
  files are staged in a sibling directory, the manifest is written last, and the finished
  directory is moved into place, so no half-written bundle appears under `--out`. An existing
  `--out` is never overwritten.
- The optional analytics file (`analytics-evidence/2`) is built by `export_shadow_evidence` from
  `--analytics-inputs` (SHADOW rows of this epoch, the backtest part and the research universe).
  `test_only` rows keep their flag; the analytics normalizer excludes and counts them (REV-03).
  Building the SHADOW rows from the journal is not part of this script (see the plan summary).

Exit codes: 0 bundle written (and published and verified when asked); 2 an input or the
destination is unusable (named, never its content); 3 a secret-looking value was found (file
named, nothing written); 4 the publish or its verification failed (the local bundle is kept).
Without `--publish` no network is touched.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_trial_soak import (  # noqa: E402
    DEFAULT_WORKFLOW,
    WorkflowError,
    read_workflow_cron,
)
from src.ops.redaction import Redactor, scrub  # noqa: E402
from src.paper.attribution import ShadowOutcome  # noqa: E402
from src.paper.coverage import (  # noqa: E402
    EvidenceGap,
    freeze_evidence_report,
    parse_freeze_log,
    parse_github_runs,
)
from src.paper.evidence_bundle import (  # noqa: E402
    BUNDLE_SCHEMA,
    FILE_ANALYTICS,
    FILE_DIFF,
    FILE_GAPS,
    FILE_PINNED,
    FILE_RECORDS,
    FILE_RUNS,
    MANIFEST_NAME,
    BundleError,
    load_evidence_bundle,
    runtime_record_line,
    sha256_of,
)
from src.paper.evidence_export import (  # noqa: E402
    ShadowRow,
    evidence_file_bytes,
    export_shadow_evidence,
)
from src.paper.freeze import StreamEpoch, load_pinned_state  # noqa: E402
from src.paper.runtime_config import (  # noqa: E402
    ConfigNotRatified,
    load_runtime_config,
    read_env,
)
from src.paper.runtime_state import (  # noqa: E402
    RuntimeRecord,
    RuntimeStatePort,
    record_sort_key,
)
from src.paper.vocabulary import RuntimeEventType  # noqa: E402

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_SECRET = 3
EXIT_PUBLISH = 4

SOURCE_PG = "pg"
SOURCE_FIXTURE = "fixture"
SOURCES = (SOURCE_PG, SOURCE_FIXTURE)


class InputError(Exception):
    """An input is missing or unusable. The message names a file or a key, never a value."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0], allow_abbrev=False
    )
    parser.add_argument("--source", required=True, choices=SOURCES, help="runtime record source")
    parser.add_argument("--epoch", required=True, help="the epoch_id of the bundle")
    parser.add_argument(
        "--pinned",
        required=True,
        action="append",
        type=Path,
        help="pinned_epoch.json (repeat for archived pins); the one of --epoch is exported",
    )
    parser.add_argument("--diff-log", required=True, type=Path, help="registry_diff.jsonl")
    parser.add_argument("--github-runs", required=True, type=Path, help="GitHub run list file")
    parser.add_argument("--config", required=True, help="ratified runtime configuration (TOML)")
    parser.add_argument(
        "--workflow",
        type=Path,
        default=DEFAULT_WORKFLOW,
        help="freeze workflow file holding the schedule cron",
    )
    parser.add_argument("--window-start", required=True, help="UTC ISO-8601 window start")
    parser.add_argument("--window-end", required=True, help="UTC ISO-8601 window end")
    parser.add_argument("--out", required=True, type=Path, help="new bundle directory")
    parser.add_argument("--records", type=Path, help="runtime records file (fixture source only)")
    parser.add_argument(
        "--analytics-inputs", type=Path, help="SHADOW rows, backtest part and research universe"
    )
    parser.add_argument(
        "--publish",
        metavar="REMOTE:BUCKET/PREFIX",
        help="after the export, publish the bundle to this evidence remote and verify it (O-01 a)",
    )
    return parser


def _publish_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_soak_evidence.py publish",
        description="publish an existing bundle to the O-01 evidence remote and verify it",
        allow_abbrev=False,
    )
    parser.add_argument("--bundle", required=True, type=Path, help="an exported bundle directory")
    parser.add_argument(
        "--destination", required=True, metavar="REMOTE:BUCKET/PREFIX", help="the evidence remote"
    )
    return parser


# --------------------------------------------------------------------------- #
# Inputs.
# --------------------------------------------------------------------------- #


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise InputError(f"{label} cannot be read") from None


def _decode(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError(f"{label} is not UTF-8 text") from None


def _parse_window(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise InputError(f"{label} is not an ISO-8601 time") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError(f"{label} must be UTC-aware")
    return parsed.astimezone(UTC)


def _select_pinned(paths: Sequence[Path], epoch_id: str) -> tuple[bytes, StreamEpoch]:
    """The bytes and the parsed pin of the one `--pinned` file that belongs to `epoch_id`."""
    matches: list[tuple[Path, StreamEpoch]] = []
    for path in paths:
        try:
            epoch = load_pinned_state(path)
        except (OSError, ValueError, KeyError, TypeError):
            raise InputError(f"{path.name} is not a pinned epoch file") from None
        if epoch.epoch_id == epoch_id:
            matches.append((path, epoch))
    if not matches:
        raise InputError("no --pinned file belongs to --epoch")
    if len(matches) > 1:
        raise InputError("more than one --pinned file belongs to --epoch")
    path, epoch = matches[0]
    return _read_bytes(path, path.name), epoch


def _record_from_row(row: Mapping[str, Any]) -> RuntimeRecord:
    occurred = datetime.fromisoformat(row["occurred_at_utc"])
    payload = row.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    return RuntimeRecord(
        event_type=RuntimeEventType(row["event_type"]),
        epoch_id=row["epoch_id"],
        occurred_at_utc=occurred,
        symbol=row.get("symbol"),
        interval=row.get("interval"),
        payload=payload,
    )


def _fixture_records(path: Path, epoch_id: str) -> list[RuntimeRecord]:
    """The records of `epoch_id` in a runtime records file (the 16-25 line shape)."""
    text = _decode(_read_bytes(path, path.name), path.name)
    records: list[RuntimeRecord] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.strip() == "":
            continue
        try:
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError("not a JSON object")
            if row.get("epoch_id") != epoch_id:
                continue
            records.append(_record_from_row(row))
        except (ValueError, KeyError, TypeError):
            raise InputError(f"{path.name} line {number} is not a runtime record") from None
    return sorted(records, key=record_sort_key)


def _pg_state(environ: Mapping[str, str]) -> RuntimeStatePort:
    """The soak PostgreSQL state port, from the allowed environment names only."""
    values = read_env(environ)
    url = values.get("DATABASE_URL_SYNC") or values.get("DATABASE_URL")
    if not url:
        raise InputError("DATABASE_URL_SYNC or DATABASE_URL is not set")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    # Imported here so that the fixture source never imports SQLAlchemy.
    from src.persistence.engine import make_sync_engine
    from src.persistence.paper_runtime_state import PgRuntimeState
    from src.persistence.uow import OperationalDatabase

    try:
        return PgRuntimeState(OperationalDatabase(make_sync_engine(url)))
    except Exception as exc:  # the message may carry the URL: report the type name only
        raise InputError(f"the soak database cannot be opened ({type(exc).__name__})") from None


def _pg_records(state: RuntimeStatePort, epoch_id: str) -> list[RuntimeRecord]:
    try:
        # No event-type filter: every RuntimeEventType of the epoch is exported.
        return list(state.records(epoch_id))
    except Exception as exc:  # the message may carry SQL text or the URL: type name only
        raise InputError(f"the runtime records cannot be read ({type(exc).__name__})") from None


def _shadow_row(raw: Mapping[str, Any]) -> ShadowRow:
    return ShadowRow(
        epoch_id=raw["epoch_id"],
        signal=raw["signal"],
        trade_plan=raw["trade_plan"],
        shadow_outcome=ShadowOutcome(**raw["shadow_outcome"]),
        approval=raw.get("approval"),
        order=raw.get("order"),
        fill=raw.get("fill"),
        confirm=raw.get("confirm"),
        test_only=raw.get("test_only", False),
    )


def _analytics_bytes(path: Path, epoch_id: str) -> bytes:
    """The `analytics-evidence/2` file of the SHADOW rows of `epoch_id`."""
    text = _decode(_read_bytes(path, path.name), path.name)
    try:
        document = json.loads(text)
        rows = [_shadow_row(raw) for raw in document["rows"] if raw["epoch_id"] == epoch_id]
        evidence = export_shadow_evidence(
            rows,
            research_universe=document["research_universe"],
            backtest_entries=document["backtest"],
        )
    except (ValueError, KeyError, TypeError):
        raise InputError(f"{path.name} is not a valid analytics inputs file") from None
    return evidence_file_bytes(evidence)


# --------------------------------------------------------------------------- #
# Output.
# --------------------------------------------------------------------------- #


def _jsonl(lines: Sequence[str]) -> bytes:
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def _gap_line(gap: EvidenceGap) -> str:
    row = {
        "slot_utc": gap.slot_utc.astimezone(UTC).isoformat(),
        "schedule": gap.schedule,
        "reason": gap.reason.value,
        "detected_at_utc": gap.detected_at_utc.astimezone(UTC).isoformat(),
        "run_id": gap.run_id,
    }
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _scan(files: Mapping[str, bytes], environ: Mapping[str, str]) -> list[str]:
    """Names of the files in which the redaction scrubber finds something to remove."""
    redactor = Redactor.from_environ(environ)
    flagged: list[str] = []
    for name, data in files.items():
        text = data.decode("utf-8", errors="replace")
        if redactor.scrub(text) != text:
            flagged.append(name)
    return flagged


def _write_bundle(out: Path, files: Mapping[str, bytes], manifest: Mapping[str, Any]) -> None:
    """Stage every file, write the manifest last, then move the directory into place."""
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.", suffix=".staging", dir=out.parent))
    try:
        for name, data in files.items():
            (staging / name).write_bytes(data)
        (staging / MANIFEST_NAME).write_bytes(
            (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
        )
        os.replace(staging, out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _build(
    args: argparse.Namespace, state: RuntimeStatePort | None, environ: Mapping[str, str]
) -> tuple[dict[str, bytes], dict[str, Any], int, int]:
    """The bundle files and the manifest (without writing anything)."""
    start = _parse_window(args.window_start, "--window-start")
    end = _parse_window(args.window_end, "--window-end")
    if end <= start:
        raise InputError("--window-end must be after --window-start")
    if args.out.exists():
        raise InputError(f"{args.out.name} already exists; a bundle is never overwritten")

    records_file: Path | None = args.records
    if args.source == SOURCE_FIXTURE:
        if state is not None:
            raise InputError("a runtime state port cannot back a fixture bundle")
        if records_file is None:
            raise InputError("--source fixture needs --records")
    else:
        if records_file is not None:
            raise InputError("a records file cannot back a pg bundle")

    pinned_bytes, pinned = _select_pinned(args.pinned, args.epoch)
    diff_bytes = _read_bytes(args.diff_log, args.diff_log.name)
    runs_bytes = _read_bytes(args.github_runs, args.github_runs.name)
    try:
        config = load_runtime_config(args.config)
        cron = read_workflow_cron(args.workflow)
    except (ConfigNotRatified, WorkflowError):
        raise InputError("the ratified configuration or the freeze workflow is unusable") from None

    if args.source == SOURCE_FIXTURE:
        assert records_file is not None  # checked above
        records = _fixture_records(records_file, args.epoch)
    else:
        records = _pg_records(state if state is not None else _pg_state(environ), args.epoch)
    if not records:
        raise InputError("no runtime record belongs to --epoch")

    try:
        report = freeze_evidence_report(
            pin_utc=pinned.opened_at_utc,
            window_end_utc=end,
            cron=cron,
            lines=parse_freeze_log(_decode(diff_bytes, args.diff_log.name)),
            runs=parse_github_runs(_decode(runs_bytes, args.github_runs.name)),
            grace_seconds=config.health.freeze_tick_grace_seconds,
            detected_at_utc=end,
        )
    except (ValueError, KeyError, TypeError):
        raise InputError("the freeze evidence cannot be reconciled with the run list") from None

    files: dict[str, bytes] = {
        FILE_PINNED: pinned_bytes,
        FILE_DIFF: diff_bytes,
        FILE_RUNS: runs_bytes,
        FILE_RECORDS: _jsonl([runtime_record_line(r) for r in records]),
        FILE_GAPS: _jsonl([_gap_line(g) for g in report.gaps]),
    }
    if args.analytics_inputs is not None:
        files[FILE_ANALYTICS] = _analytics_bytes(args.analytics_inputs, args.epoch)
    manifest: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "epoch_id": args.epoch,
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "source": args.source,
        "files": {},
    }
    return files, manifest, len(records), len(report.gaps)


# --------------------------------------------------------------------------- #
# Publishing to the recorded durable location (decision 16-DEC-O-01, option a).
# --------------------------------------------------------------------------- #

# The remotes of the backup crypt chain (`src/ops/backup_remote.py`): evidence never goes there.
_BACKUP_REMOTES = frozenset({"backups3", "backups3crypt"})
_DESTINATION_RE = re.compile(r":?[A-Za-z0-9_][A-Za-z0-9_.,=\-]+:[^\s:?*\"'<>|\\][^\s?*\"'<>|\\]*")
_CREDENTIAL_WORDS = re.compile(
    r"secret|passw|token|access[_-]?key|key[_-]?id|session|credential", re.I
)
_EPOCH_KEY = re.compile(r"[A-Za-z0-9._-]{1,128}")
_RCLONE_TIMEOUT_S = 900
_EXCERPT_CHARS = 300


class PublishError(Exception):
    """An upload or its verification failed. The message names a file, never its content."""


class Uploader(Protocol):
    """The object store behind `--publish`. Keys are `<epoch_id>/<file name>`."""

    def listing(self, prefix: str) -> frozenset[str]:
        """File names directly under `prefix` (empty when the prefix does not exist)."""

    def put(self, key: str, data: bytes) -> None:
        """Store one object; never replaces an existing one."""

    def get(self, key: str) -> bytes:
        """Read one object back."""


# argv without the binary, optional standard input -> (exit code, stdout, stderr).
RcloneCall = Callable[[Sequence[str], bytes | None], tuple[int, bytes, bytes]]


def _run_rclone(argv: Sequence[str], stdin: bytes | None) -> tuple[int, bytes, bytes]:
    binary = os.environ.get("RCLONE_BIN") or "rclone"
    try:
        proc = subprocess.run(
            [binary, *argv],
            input=stdin,
            capture_output=True,
            timeout=_RCLONE_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        raise PublishError("the rclone binary was not found; install rclone") from None
    except subprocess.TimeoutExpired:
        raise PublishError(f"rclone {argv[0]} timed out") from None
    return proc.returncode, proc.stdout, proc.stderr


def _excerpt(stderr: bytes) -> str:
    flat = " ".join(scrub(stderr.decode("utf-8", errors="replace")).split())
    return flat[-_EXCERPT_CHARS:]


class RcloneUploader:
    """`Uploader` over the rclone CLI. Credentials are the operator's rclone configuration or
    environment for the remote; none is passed in argv and none has a default here."""

    def __init__(self, destination: str, *, runner: RcloneCall | None = None) -> None:
        self._base = destination.rstrip("/")
        self._run = runner if runner is not None else _run_rclone

    def _target(self, key: str) -> str:
        return f"{self._base}/{key}"

    def listing(self, prefix: str) -> frozenset[str]:
        code, out, err = self._run(["lsf", "--files-only", self._target(prefix)], None)
        if code == 3:  # rclone: directory not found, i.e. nothing published under this prefix
            return frozenset()
        if code != 0:
            raise PublishError(f"listing {prefix} failed (exit {code}): {_excerpt(err)}")
        return frozenset(line for line in out.decode("utf-8").splitlines() if line)

    def put(self, key: str, data: bytes) -> None:
        code, _, err = self._run(["rcat", "--immutable", self._target(key)], data)
        if code != 0:
            raise PublishError(
                f"{key.rsplit('/', 1)[-1]} upload failed (exit {code}): {_excerpt(err)}"
            )

    def get(self, key: str) -> bytes:
        code, out, _ = self._run(["cat", self._target(key)], None)
        if code != 0:
            raise PublishError(f"{key.rsplit('/', 1)[-1]} cannot be read back (exit {code})")
        return out


def validate_destination(destination: str) -> str:
    """The destination when it is a plain remote and prefix; otherwise `InputError`.

    Refused: a local path or drive letter, an empty prefix, whitespace, a backup chain remote,
    and anything that looks like a credential (argv is visible to every local user)."""
    if _DESTINATION_RE.fullmatch(destination) is None:
        raise InputError("--publish must be <remote>:<bucket>/<prefix> with no spaces")
    if _CREDENTIAL_WORDS.search(destination):
        raise InputError("--publish must not carry a credential; configure it in rclone")
    remote = (
        destination.split(":", 2)[1]
        if destination.startswith(":")
        else destination.split(":", 1)[0]
    )
    if remote.split(",", 1)[0].lower() in _BACKUP_REMOTES:
        raise InputError("--publish must not name the backup crypt remote")
    return destination


def publish_bundle(directory: Path, uploader: Uploader) -> tuple[str, int]:
    """Upload a verified bundle (files first, manifest last) and check the published copy.

    Returns (epoch_id, object count). Raises `PublishError` naming the file on any failure."""
    manifest_bytes = _read_bytes(directory / MANIFEST_NAME, MANIFEST_NAME)
    try:
        manifest = json.loads(manifest_bytes)
        epoch_id = manifest["epoch_id"]
        digests: dict[str, str] = dict(manifest["files"])
    except (ValueError, KeyError, TypeError):
        raise InputError(f"{MANIFEST_NAME} is not a bundle manifest") from None
    if not isinstance(epoch_id, str) or _EPOCH_KEY.fullmatch(epoch_id) is None:
        raise InputError("the manifest epoch_id is not usable as a storage key")
    local = {name: _read_bytes(directory / name, name) for name in sorted(digests)}

    present = uploader.listing(epoch_id)
    if MANIFEST_NAME in present:
        raise PublishError(f"epoch {epoch_id[:12]} is already published; it is never replaced")
    for name, data in local.items():
        key = f"{epoch_id}/{name}"
        if name in present:
            if uploader.get(key) != data:
                raise PublishError(f"{name} already exists with different content; not replaced")
            continue
        uploader.put(key, data)
    uploader.put(f"{epoch_id}/{MANIFEST_NAME}", manifest_bytes)

    for name in local:
        got = uploader.get(f"{epoch_id}/{name}")
        if sha256_of(got) != digests[name]:
            raise PublishError(f"{name} does not match the manifest sha256 after publish")
    if uploader.get(f"{epoch_id}/{MANIFEST_NAME}") != manifest_bytes:
        raise PublishError(f"{MANIFEST_NAME} does not match the local manifest after publish")
    return epoch_id, len(local) + 1


def _publish(
    directory: Path, destination: str, uploader: Uploader | None, environ: Mapping[str, str]
) -> int:
    """Publish and report; maps failures to exit codes without printing a secret value."""
    redactor = Redactor.from_environ(environ)
    try:
        epoch_id, count = publish_bundle(
            directory, uploader if uploader is not None else RcloneUploader(destination)
        )
    except PublishError as exc:
        print(f"cannot publish: {redactor.scrub(str(exc))}", file=sys.stderr)
        return EXIT_PUBLISH
    except InputError as exc:
        print(f"cannot publish: {redactor.scrub(str(exc))}", file=sys.stderr)
        return EXIT_INPUT
    print(f"published and verified: {count} object(s) under {epoch_id[:12]}... of {destination}")
    return EXIT_OK


def _main_publish(
    argv: Sequence[str], uploader: Uploader | None, environ: Mapping[str, str]
) -> int:
    args = _publish_parser().parse_args(argv)
    try:
        destination = validate_destination(args.destination)
        load_evidence_bundle(args.bundle)
        files = {
            path.name: path.read_bytes() for path in sorted(args.bundle.iterdir()) if path.is_file()
        }
    except InputError as exc:
        print(f"cannot publish: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except (BundleError, OSError) as exc:
        print(f"cannot publish: the bundle is not usable ({type(exc).__name__})", file=sys.stderr)
        return EXIT_INPUT
    flagged = _scan(files, environ)
    if flagged:
        print(
            "refusing to publish: secret-looking content in " + ", ".join(flagged),
            file=sys.stderr,
        )
        return EXIT_SECRET
    return _publish(args.bundle, destination, uploader, environ)


def main(
    argv: Sequence[str] | None = None,
    *,
    state: RuntimeStatePort | None = None,
    environ: Mapping[str, str] | None = None,
    uploader: Uploader | None = None,
) -> int:
    """Export one epoch. `state` is a test seam for the pg source (a fake or an open port);
    `environ` defaults to the process environment (database URL, secret values to scan for);
    `uploader` is a test seam for `--publish` (default: rclone)."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    if arguments[:1] == ["publish"]:
        return _main_publish(arguments[1:], uploader, env)
    args = _parser().parse_args(arguments)
    destination: str | None = None
    if args.publish is not None:
        try:
            destination = validate_destination(args.publish)
        except InputError as exc:
            print(f"cannot export: {exc}", file=sys.stderr)
            return EXIT_INPUT
    try:
        files, manifest, record_count, gap_count = _build(args, state, env)
    except InputError as exc:
        print(f"cannot export: {exc}", file=sys.stderr)
        return EXIT_INPUT
    flagged = _scan(files, env)
    if flagged:
        print(
            "refusing to write the bundle: secret-looking content in " + ", ".join(flagged),
            file=sys.stderr,
        )
        return EXIT_SECRET
    manifest["files"] = {name: sha256_of(data) for name, data in sorted(files.items())}
    try:
        _write_bundle(args.out, files, manifest)
    except OSError:
        print("cannot export: the bundle directory cannot be written", file=sys.stderr)
        return EXIT_INPUT
    print(
        f"bundle written: {args.out.name} (source {args.source}, {record_count} runtime "
        f"record(s), {gap_count} evidence gap(s))"
    )
    if destination is not None:
        return _publish(args.out, destination, uploader, env)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
