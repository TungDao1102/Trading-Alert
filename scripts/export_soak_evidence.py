"""Export one epoch of the soak trial as a verifiable evidence bundle (Phase 16, plan 16-30).

    python scripts/export_soak_evidence.py --source {pg,fixture} --epoch <epoch_id>
        --pinned <pinned_epoch.json> [--pinned ...] --diff-log <registry_diff.jsonl>
        --github-runs <runs.json> --config <paper-runtime.toml> [--workflow <yml>]
        --window-start <UTC ISO> --window-end <UTC ISO> --out <new directory>
        [--records <runtime_records.jsonl>]        (fixture source only)
        [--analytics-inputs <analytics_inputs.json>]

The output is one `soak-evidence-bundle/1` directory (layout and loader: `src/paper/
evidence_bundle.py`, plan 16-25) that `scripts/evaluate_trial_soak.py` accepts. The script is
location-agnostic: it writes a local directory and decides no durable location (checkpoint O-01
and the publishing step belong to plan 16-47).

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

Exit codes: 0 bundle written; 2 an input is unusable (named, never its content); 3 a secret-looking
value was found (file named, nothing written). No network is touched.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_trial_soak import (  # noqa: E402
    DEFAULT_WORKFLOW,
    WorkflowError,
    read_workflow_cron,
)
from src.ops.redaction import Redactor  # noqa: E402
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

SOURCE_PG = "pg"
SOURCE_FIXTURE = "fixture"
SOURCES = (SOURCE_PG, SOURCE_FIXTURE)


class InputError(Exception):
    """An input is missing or unusable. The message names a file or a key, never a value."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
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


def main(
    argv: Sequence[str] | None = None,
    *,
    state: RuntimeStatePort | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Export one epoch. `state` is a test seam for the pg source (a fake or an open port);
    `environ` defaults to the process environment (database URL, secret values to scan for)."""
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
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
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
