"""Soak evidence bundle layout and loader (Phase 16, plan 16-25; D-23, REV-18, T-16-59).

One bundle is one directory holding the evidence of ONE epoch. The exporter of plan 16-30 writes
it; `load_evidence_bundle` is the only reader the evaluator trusts:

    manifest.json            schema, epoch_id, window_start_utc, window_end_utc, source, files
    pinned_epoch.json        the pinned `StreamEpoch` (as `write_pinned_state` writes it)
    registry_diff.jsonl      the freeze-check log lines (copied whole, never edited)
    github_runs.json         the exported GitHub run list (array or `workflow_runs` object)
    runtime_records.jsonl    one runtime journal record per line
    evidence_gaps.jsonl      one EVIDENCE_GAP per line (never mixed into registry_diff.jsonl)
    analytics_evidence.json  optional SHADOW analytics evidence

`files` maps each file name to its SHA-256. Every file is hashed and compared BEFORE it is parsed,
so a file edited after export is refused and named (fail closed). `source` is "pg" (the soak
database) or "fixture"; the proof class of the whole bundle follows from it and from nothing else.

Line shapes:

- runtime record: `{"event_type", "epoch_id", "occurred_at_utc", "symbol", "interval", "payload"}`
  (`payload` carries no float; a float is refused);
- evidence gap: `{"slot_utc", "schedule", "reason", "detected_at_utc", "run_id"}`.

Pure of the clock and the network: it reads the files of one directory and nothing else.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
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

REQUIRED_FILES: tuple[str, ...] = (FILE_PINNED, FILE_DIFF, FILE_RUNS, FILE_RECORDS, FILE_GAPS)
OPTIONAL_FILES: tuple[str, ...] = (FILE_ANALYTICS,)
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
        if name not in KNOWN_FILES:
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
    )


__all__ = [
    "BUNDLE_SCHEMA",
    "FILE_ANALYTICS",
    "FILE_DIFF",
    "FILE_GAPS",
    "FILE_PINNED",
    "FILE_RECORDS",
    "FILE_RUNS",
    "KNOWN_FILES",
    "MANIFEST_NAME",
    "OPTIONAL_FILES",
    "REQUIRED_FILES",
    "SOURCES",
    "BundleError",
    "DiffRecord",
    "EvidenceBundle",
    "load_evidence_bundle",
    "sha256_of",
]
