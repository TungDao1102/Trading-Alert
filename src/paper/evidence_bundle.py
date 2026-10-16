"""Soak evidence bundle layout and loader (Phase 16, plan 16-25; D-23, REV-18, T-16-59).

One bundle is one directory holding the evidence of ONE epoch. The exporter of plan 16-30 writes
it; `load_evidence_bundle` is the only reader the evaluator trusts:

    manifest.json            schema, epoch_id, window_start_utc, window_end_utc, source, files,
                             and (plan 16-59) as_of_utc
    pinned_epoch.json        the pinned `StreamEpoch` (as `write_pinned_state` writes it)
    registry_diff.jsonl      the freeze-check log lines: since plan 16-59 the DERIVED union of
                             the input artifacts (deduplicated by run identity, ordered by time);
                             the manifest `freeze_log` lists the inputs and their run ids
    github_runs.json         the exported GitHub run list (array or `workflow_runs` object)
    runtime_records.jsonl    one runtime journal record per line
    evidence_gaps.jsonl      one EVIDENCE_GAP per line (never mixed into registry_diff.jsonl)
    missing_ticks.jsonl      optional (plan 16-59): one row per scheduled tick without a usable
                             freeze line, with its run id and the run's conclusion
    freeze_artifact_<16 hex>.jsonl
                             optional, one per input artifact (plan 16-59): an original freeze-check
                             artifact kept byte for byte (<16 hex> = the start of its sha256)
    analytics_evidence.json  optional SHADOW analytics evidence

`files` maps each file name to its SHA-256. Every file is hashed and compared BEFORE it is parsed,
so a file edited after export is refused and named (fail closed). `source` is "pg" (the soak
database) or "fixture"; the proof class of the whole bundle follows from it and from nothing else.

Line shapes:

- runtime record: `{"event_type", "epoch_id", "occurred_at_utc", "symbol", "interval", "payload"}`
  (`payload` carries no float; a float is refused);
- evidence gap: `{"slot_utc", "schedule", "reason", "detected_at_utc", "run_id"}`.

`as_of_utc` (plan 16-59, B2-WR-06) is the instant the exporter judged the freeze ticks as of: a
tick is judged only when its slot plus the ratified grace is at or before it. A bundle whose
`as_of_utc` is before `window_end_utc` plus the grace is PARTIAL (an hourly export): it loads and
is published, but the trial evaluator refuses to judge it (`bundle_is_partial`). A bundle without
`as_of_utc` (written before plan 16-59) is treated as final.

Plan 16-51 adds two runtime record types to `runtime_records.jsonl`, `PAPER_REPLAY_INPUTS` (what
the risk stage read for an evaluated live bar) and `PAPER_HISTORY_BARS` (every bar the pipeline
accepted, with its acceptance sequence). The bundle schema stays `soak-evidence-bundle/1` and no
file is added: the trial evaluator rebuilds the parity replay from these lines and the registry
parameter set whose hash equals the pin. `runtime_record_line` is the one canonical writer of such
a line, for every `RuntimeEventType`.

Pure of the clock and the network: it reads the files of one directory and nothing else.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.paper.coverage import (
    EvidenceGap,
    EvidenceGapReason,
    FreezeLine,
    GithubRun,
    parse_freeze_log,
    parse_github_runs,
)
from src.paper.freeze import StreamEpoch
from src.paper.runtime_state import RuntimeRecord
from src.paper.vocabulary import RuntimeEventType

BUNDLE_SCHEMA = "soak-evidence-bundle/1"
MANIFEST_NAME = "manifest.json"
FILE_PINNED = "pinned_epoch.json"
FILE_DIFF = "registry_diff.jsonl"
FILE_RUNS = "github_runs.json"
FILE_RECORDS = "runtime_records.jsonl"
FILE_GAPS = "evidence_gaps.jsonl"
FILE_ANALYTICS = "analytics_evidence.json"
FILE_MISSING_TICKS = "missing_ticks.jsonl"
FREEZE_ARTIFACT_PREFIX = "freeze_artifact_"
FREEZE_ARTIFACT_PATTERN = re.compile(r"freeze_artifact_[0-9a-f]{16}\.jsonl")

REQUIRED_FILES: tuple[str, ...] = (FILE_PINNED, FILE_DIFF, FILE_RUNS, FILE_RECORDS, FILE_GAPS)
OPTIONAL_FILES: tuple[str, ...] = (FILE_MISSING_TICKS, FILE_ANALYTICS)
KNOWN_FILES: frozenset[str] = frozenset((*REQUIRED_FILES, *OPTIONAL_FILES))
SOURCES: tuple[str, ...] = ("pg", "fixture")


class BundleError(Exception):
    """The bundle is incomplete, edited after export or unreadable (names the file, no content)."""


@dataclass(frozen=True)
class DiffRecord:
    """The epoch and hash fields of one freeze-check line, as written (None when absent)."""

    checked_at_utc: datetime | None
    epoch_id: str | None
    pinned_hash: str | None
    current_hash: str | None
    outcome: str | None


@dataclass(frozen=True)
class MissingTick:
    """A scheduled freeze tick without a usable line (plan 16-59, correction 3).

    `run_id`, `status` and `conclusion` are those of the GitHub run assigned to the slot, or None
    when no run was found for it. The slot is an EVIDENCE_GAP whatever the artifacts say.
    """

    slot_utc: datetime
    run_id: str | None
    status: str | None
    conclusion: str | None
    reason: str


@dataclass(frozen=True)
class EvidenceBundle:
    """A verified, parsed bundle of one epoch. Everything in it is the exporter's own data."""

    path: Path
    epoch_id: str
    window_start_utc: datetime
    window_end_utc: datetime
    source: str
    pinned: StreamEpoch
    freeze_lines: tuple[FreezeLine, ...]
    diff_records: tuple[DiffRecord, ...]
    runs: tuple[GithubRun, ...]
    records: tuple[RuntimeRecord, ...]
    evidence_gaps: tuple[EvidenceGap, ...]
    analytics: Mapping[str, Any] | None
    file_sha256: Mapping[str, str]
    as_of_utc: datetime | None = None
    missing_ticks: tuple[MissingTick, ...] = ()


def sha256_of(data: bytes) -> str:
    """Lowercase hex SHA-256 of the bytes."""
    return hashlib.sha256(data).hexdigest()


def _refuse_float(text: str) -> None:
    raise ValueError(f"a number with a fraction ({text}) is not allowed; use text or an integer")


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO-8601 time")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} is not an ISO-8601 time") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be UTC-aware")
    return parsed.astimezone(UTC)


def _json_rows(name: str, data: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, raw in enumerate(data.decode("utf-8").splitlines(), start=1):
        if raw.strip() == "":
            continue
        try:
            row = json.loads(raw, parse_float=_refuse_float)
        except ValueError as exc:
            raise BundleError(f"{name} line {number}: {exc}") from None
        if not isinstance(row, dict):
            raise BundleError(f"{name} line {number}: not a JSON object")
        rows.append(row)
    return rows


def _parse_manifest(directory: Path) -> dict[str, Any]:
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BundleError(f"{MANIFEST_NAME} is missing from {directory.name}")
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except ValueError:
        raise BundleError(f"{MANIFEST_NAME} is not valid JSON") from None
    if not isinstance(manifest, dict):
        raise BundleError(f"{MANIFEST_NAME} is not a JSON object")
    if manifest.get("schema") != BUNDLE_SCHEMA:
        raise BundleError(f"{MANIFEST_NAME} schema must be {BUNDLE_SCHEMA!r}")
    if manifest.get("source") not in SOURCES:
        raise BundleError(f"{MANIFEST_NAME} source must be one of {list(SOURCES)}")
    return manifest


def _verified_files(directory: Path, manifest: Mapping[str, Any]) -> dict[str, bytes]:
    """Read every listed file once and compare its SHA-256 with the manifest before any parse."""
    listed = manifest.get("files")
    if not isinstance(listed, dict):
        raise BundleError(f"{MANIFEST_NAME} files must map file names to SHA-256 values")
    for name in listed:
        if name not in KNOWN_FILES and FREEZE_ARTIFACT_PATTERN.fullmatch(name) is None:
            raise BundleError(f"{MANIFEST_NAME} lists {name!r}, which is not a bundle file name")
    for name in REQUIRED_FILES:
        if name not in listed:
            raise BundleError(f"{MANIFEST_NAME} does not list the required file {name}")
    contents: dict[str, bytes] = {}
    for name, expected in listed.items():
        target = directory / name
        if not target.is_file():
            raise BundleError(f"{name} is listed in the manifest but missing from the bundle")
        data = target.read_bytes()
        if not isinstance(expected, str) or sha256_of(data) != expected:
            raise BundleError(f"{name} does not match the manifest sha256 (edited after export)")
        contents[name] = data
    return contents


def _parse_pinned(data: bytes) -> StreamEpoch:
    try:
        raw = json.loads(data)
        return StreamEpoch(
            epoch_id=raw["epoch_id"],
            strategy_id=raw["strategy_id"],
            parameter_set_id=raw["parameter_set_id"],
            parameter_set_hash=raw["parameter_set_hash"],
            opened_at_utc=_parse_utc(raw["opened_at_utc"], "opened_at_utc"),
            evidence_claim_open=bool(raw.get("evidence_claim_open", True)),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise BundleError(f"{FILE_PINNED} is not a pinned epoch: {exc}") from None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _parse_diff_records(data: bytes) -> tuple[DiffRecord, ...]:
    records: list[DiffRecord] = []
    for row in _json_rows(FILE_DIFF, data):
        try:
            checked = _parse_utc(row.get("checked_at_utc"), "checked_at_utc")
        except ValueError:
            checked = None
        records.append(
            DiffRecord(
                checked_at_utc=checked,
                epoch_id=_optional_text(row.get("epoch_id")),
                pinned_hash=_optional_text(row.get("pinned_hash")),
                current_hash=_optional_text(row.get("current_hash")),
                outcome=_optional_text(row.get("outcome")),
            )
        )
    return tuple(records)


def runtime_record_line(record: RuntimeRecord) -> str:
    """The `runtime_records.jsonl` line of one record: canonical JSON, no trailing newline.

    The payload is taken from the record's own canonical payload text, so the bytes round-trip:
    a line read back with `load_evidence_bundle` gives a record with the same
    `runtime_event_id` and `payload_json` (the exporter of plan 16-30 writes every record with it).
    """
    row = {
        "event_type": record.event_type.value,
        "epoch_id": record.epoch_id,
        "occurred_at_utc": record.occurred_at_utc.astimezone(UTC).isoformat(),
        "symbol": record.symbol,
        "interval": record.interval,
        "payload": json.loads(record.payload_json),
    }
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _parse_records(data: bytes) -> tuple[RuntimeRecord, ...]:
    records: list[RuntimeRecord] = []
    for number, row in enumerate(_json_rows(FILE_RECORDS, data), start=1):
        try:
            payload = row.get("payload", {})
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            records.append(
                RuntimeRecord(
                    event_type=RuntimeEventType(row["event_type"]),
                    epoch_id=row["epoch_id"],
                    occurred_at_utc=_parse_utc(row["occurred_at_utc"], "occurred_at_utc"),
                    symbol=row.get("symbol"),
                    interval=row.get("interval"),
                    payload=payload,
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise BundleError(f"{FILE_RECORDS} line {number}: {exc}") from None
    return tuple(records)


def _parse_gaps(data: bytes) -> tuple[EvidenceGap, ...]:
    gaps: list[EvidenceGap] = []
    for number, row in enumerate(_json_rows(FILE_GAPS, data), start=1):
        try:
            run_id = row.get("run_id")
            gaps.append(
                EvidenceGap(
                    slot_utc=_parse_utc(row["slot_utc"], "slot_utc"),
                    schedule=str(row["schedule"]),
                    reason=EvidenceGapReason(row["reason"]),
                    detected_at_utc=_parse_utc(row["detected_at_utc"], "detected_at_utc"),
                    run_id=None if run_id is None else str(run_id),
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise BundleError(f"{FILE_GAPS} line {number}: {exc}") from None
    return tuple(gaps)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _parse_missing_ticks(data: bytes) -> tuple[MissingTick, ...]:
    ticks: list[MissingTick] = []
    for number, row in enumerate(_json_rows(FILE_MISSING_TICKS, data), start=1):
        try:
            ticks.append(
                MissingTick(
                    slot_utc=_parse_utc(row["slot_utc"], "slot_utc"),
                    run_id=_optional_str(row.get("run_id")),
                    status=_optional_str(row.get("status")),
                    conclusion=_optional_str(row.get("conclusion")),
                    reason=str(row["reason"]),
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise BundleError(f"{FILE_MISSING_TICKS} line {number}: {exc}") from None
    return tuple(ticks)


def _parse_runs(data: bytes) -> tuple[GithubRun, ...]:
    try:
        return parse_github_runs(data.decode("utf-8"))
    except (ValueError, KeyError, TypeError) as exc:
        raise BundleError(f"{FILE_RUNS} is not a run list: {exc}") from None


def _parse_analytics(data: bytes) -> Mapping[str, Any]:
    try:
        parsed = json.loads(data)
    except ValueError:
        raise BundleError(f"{FILE_ANALYTICS} is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise BundleError(f"{FILE_ANALYTICS} is not a JSON object")
    return parsed


def load_evidence_bundle(path: Path | str) -> EvidenceBundle:
    """Verify every file against the manifest SHA-256, then parse the bundle.

    Raises:
        BundleError: a file is missing, listed under a foreign name, edited after export or
            unparseable; the message names the file (never its content).
    """
    directory = Path(path)
    if not directory.is_dir():
        raise BundleError(f"{directory.name} is not a bundle directory")
    manifest = _parse_manifest(directory)
    contents = _verified_files(directory, manifest)
    try:
        epoch_id = manifest["epoch_id"]
        start = _parse_utc(manifest["window_start_utc"], "window_start_utc")
        end = _parse_utc(manifest["window_end_utc"], "window_end_utc")
    except (KeyError, ValueError) as exc:
        raise BundleError(f"{MANIFEST_NAME}: {exc}") from None
    if not isinstance(epoch_id, str) or epoch_id == "":
        raise BundleError(f"{MANIFEST_NAME} epoch_id must be a non-empty string")
    if end <= start:
        raise BundleError(f"{MANIFEST_NAME} window_end_utc must be after window_start_utc")
    as_of: datetime | None = None
    if "as_of_utc" in manifest:
        try:
            as_of = _parse_utc(manifest["as_of_utc"], "as_of_utc")
        except ValueError as exc:
            raise BundleError(f"{MANIFEST_NAME}: {exc}") from None
    analytics = _parse_analytics(contents[FILE_ANALYTICS]) if FILE_ANALYTICS in contents else None
    return EvidenceBundle(
        path=directory,
        epoch_id=epoch_id,
        window_start_utc=start,
        window_end_utc=end,
        source=str(manifest["source"]),
        pinned=_parse_pinned(contents[FILE_PINNED]),
        freeze_lines=parse_freeze_log(contents[FILE_DIFF].decode("utf-8")),
        diff_records=_parse_diff_records(contents[FILE_DIFF]),
        runs=_parse_runs(contents[FILE_RUNS]),
        records=_parse_records(contents[FILE_RECORDS]),
        evidence_gaps=_parse_gaps(contents[FILE_GAPS]),
        analytics=analytics,
        file_sha256={name: sha256_of(data) for name, data in sorted(contents.items())},
        as_of_utc=as_of,
        missing_ticks=(
            _parse_missing_ticks(contents[FILE_MISSING_TICKS])
            if FILE_MISSING_TICKS in contents
            else ()
        ),
    )


def bundle_is_partial(bundle: EvidenceBundle, grace_seconds: int) -> bool:
    """True when the bundle was exported before the trial could be judged (an hourly export).

    The bundle is final once `as_of_utc` is at or after the window end plus the ratified
    freeze-tick grace. A bundle without `as_of_utc` was written before plan 16-59: final.
    """
    if bundle.as_of_utc is None:
        return False
    return bundle.as_of_utc < bundle.window_end_utc + timedelta(seconds=grace_seconds)


__all__ = [
    "BUNDLE_SCHEMA",
    "FILE_ANALYTICS",
    "FILE_DIFF",
    "FILE_GAPS",
    "FILE_MISSING_TICKS",
    "FILE_PINNED",
    "FILE_RECORDS",
    "FILE_RUNS",
    "FREEZE_ARTIFACT_PATTERN",
    "FREEZE_ARTIFACT_PREFIX",
    "KNOWN_FILES",
    "MANIFEST_NAME",
    "OPTIONAL_FILES",
    "REQUIRED_FILES",
    "SOURCES",
    "BundleError",
    "DiffRecord",
    "EvidenceBundle",
    "MissingTick",
    "bundle_is_partial",
    "load_evidence_bundle",
    "runtime_record_line",
    "sha256_of",
]
