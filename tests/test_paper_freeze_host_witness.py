"""Host witness ticks: a second freeze tick source (quick task 261114-12e; 16-DEC-HOST-TICK).

A host tick satisfies a slot only through its witness object: the S3 provider's server time of a
create-only object decides lateness, never a time written in the line. These tests start from the
line bytes the freeze CLI writes (`DiffLogEntry.to_jsonl()`) and follow them through bundle schema
/2 into `evaluate_trial`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.paper.coverage import HostTick, freeze_evidence_report
from src.paper.evidence_bundle import load_evidence_bundle
from src.paper.freeze import DiffLogEntry, read_run_metadata

from tests.test_paper_exit_evaluator import (
    CRON as EVALUATOR_CRON,
)
from tests.test_paper_exit_evaluator import (
    EPOCH_ID,
    PARAMETER_HASH,
    THRESHOLDS,
    TrialFixture,
    _evaluate,
    _result,
    make_fixture,
)
from tests.test_paper_freeze_evidence import DETECTED, END, GRACE, PIN, _good, _report
from tests.test_paper_freeze_workflow_pin_source import record

TICK_ID = "0123456789abcdef0123456789abcdef"
HOST_SCHEDULE = "17 * * * *"
GRACE_1800 = THRESHOLDS.freeze_tick_grace_seconds


# --------------------------------------------------------------------------- #
# Helpers: the CLI's own line bytes, a /2 bundle writer.
# --------------------------------------------------------------------------- #


def _slot_text(slot: datetime) -> str:
    return slot.astimezone(UTC).strftime("%Y%m%dT%H%MZ")


def host_path(slot: datetime, tick_id: str = TICK_ID) -> str:
    return f"{_slot_text(slot)}-{tick_id}.jsonl"


def host_metadata(tick_id: str = TICK_ID, schedule: str = HOST_SCHEDULE) -> dict[str, str]:
    return (
        read_run_metadata(
            {
                "PAPER_TICK_SOURCE": "host",
                "PAPER_TICK_ID": tick_id,
                "PAPER_EVENT_SCHEDULE": schedule,
            }
        )
        or {}
    )


def host_line_bytes(
    checked: datetime,
    *,
    epoch_id: str = EPOCH_ID,
    pinned_hash: str = PARAMETER_HASH,
    current_hash: str = PARAMETER_HASH,
    meta: dict[str, str] | None = None,
) -> bytes:
    entry = DiffLogEntry(
        checked_at_utc=checked,
        epoch_id=epoch_id,
        pinned_hash=pinned_hash,
        current_hash=current_hash,
        outcome="clean",
        run_metadata=host_metadata() if meta is None else meta,
    )
    return (entry.to_jsonl() + "\n").encode("utf-8")


def _canonical(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _lsjson_time(moment: datetime) -> str:
    """An rclone ModTime: nanosecond fraction and `Z` (the loader truncates to microseconds)."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") + ".000000123Z"


def write_host_bundle(
    fixture: TrialFixture, directory: Path, objects: list[tuple[str, bytes, datetime]]
) -> Path:
    """Write `fixture` as a bundle, then upgrade it to schema /2 with the given witness objects.

    `objects` are (path, bytes, server ModTime). The listing has the lsjson shape; the ticks file
    has one canonical row per object, sorted by path.
    """
    fixture.write(directory)
    ordered = sorted(objects, key=lambda item: item[0])
    listing = json.dumps(
        [
            {
                "Path": path,
                "Name": path,
                "Size": len(data),
                "ModTime": _lsjson_time(modtime),
                "IsDir": False,
            }
            for path, data, modtime in ordered
        ]
    ).encode("utf-8")
    rows = "".join(
        _canonical(
            {
                "path": path,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "text": data.decode("utf-8"),
            }
        )
        + "\n"
        for path, data, _ in ordered
    ).encode("utf-8")
    (directory / "host_witness_listing.json").write_bytes(listing)
    (directory / "host_ticks.jsonl").write_bytes(rows)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    manifest["schema"] = "soak-evidence-bundle/2"
    manifest["files"]["host_witness_listing.json"] = hashlib.sha256(listing).hexdigest()
    manifest["files"]["host_ticks.jsonl"] = hashlib.sha256(rows).hexdigest()
    manifest["host_witness"] = {
        "listing_file": "host_witness_listing.json",
        "ticks_file": "host_ticks.jsonl",
        "object_count": len(ordered),
        "listing": "rclone lsjson --use-server-modtime <witness prefix>/<epoch_id>/",
        "rule": "16-DEC-HOST-TICK: lateness is the provider-stamped server time of the object",
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
    )
    return directory


def _gap_fixture() -> tuple[TrialFixture, datetime]:
    """The all-pass fixture without run 100 and its line (as the missing-tick evaluator test)."""
    fixture = make_fixture()
    missing_run = fixture.runs.pop(100)
    fixture.diff_lines = [
        line
        for line in fixture.diff_lines
        if line["run_metadata"]["run_id"] != str(missing_run["id"])
    ]
    created = datetime.fromisoformat(missing_run["created_at"])
    slot = created.replace(minute=17, second=0, microsecond=0)
    assert created - slot == timedelta(seconds=20)
    return fixture, slot


# --------------------------------------------------------------------------- #
# (a) the owner record, (b) the CLI metadata names
# --------------------------------------------------------------------------- #


def test_the_host_tick_record_is_the_owners_s3_witness_answer() -> None:
    values = record("16-DEC-HOST-TICK.md")
    assert values["option"] == "s3-witness"
    assert values["decided by"] == "user"
    assert values["date"] == "2026-11-14"
    assert values["amends"].startswith("16-DEC-O-01.md")
    text = (
        Path(__file__).resolve().parent.parent
        / ".planning/phases/16-paper-runtime-composition/decisions/16-DEC-HOST-TICK.md"
    ).read_text(encoding="utf-8")
    assert "> s3-witness đi" in text.splitlines()
    assert "> Chấp nhận, quyền tối thiểu" in text.splitlines()


def test_the_cli_metadata_reads_the_host_tick_names() -> None:
    environ = {
        "PAPER_TICK_SOURCE": "host",
        "PAPER_TICK_ID": TICK_ID,
        "PAPER_EVENT_SCHEDULE": HOST_SCHEDULE,
    }
    assert read_run_metadata(environ) == {
        "source": "host",
        "tick_id": TICK_ID,
        "schedule": HOST_SCHEDULE,
    }
    entry = DiffLogEntry(
        checked_at_utc=PIN,
        epoch_id=EPOCH_ID,
        pinned_hash=PARAMETER_HASH,
        current_hash=PARAMETER_HASH,
        outcome="clean",
        run_metadata=read_run_metadata(environ),
    )
    assert json.loads(entry.to_jsonl())["run_metadata"] == {
        "schedule": HOST_SCHEDULE,
        "source": "host",
        "tick_id": TICK_ID,
    }
    github_only = read_run_metadata({"GITHUB_RUN_ID": "7", "GITHUB_EVENT_NAME": "schedule"})
    assert github_only == {"run_id": "7", "event_name": "schedule"}


# --------------------------------------------------------------------------- #
# (c) the tracer: CLI line bytes -> bundle /2 -> evaluate_trial
# --------------------------------------------------------------------------- #


def _tracer_freeze_passed(tmp_path: Path, witness_offset: timedelta) -> bool:
    fixture, slot = _gap_fixture()
    data = host_line_bytes(slot + timedelta(seconds=40))
    directory = write_host_bundle(
        fixture, tmp_path / "bundle", [(host_path(slot), data, slot + witness_offset)]
    )
    bundle = load_evidence_bundle(directory)
    assert len(bundle.host_ticks) == 1
    assert isinstance(bundle.host_ticks[0], HostTick)
    return bool(_result(_evaluate(bundle), "freeze continuity").passed)


def test_tracer_a_witnessed_host_tick_fills_a_github_gap_in_the_evaluated_trial(
    tmp_path: Path,
) -> None:
    assert EVALUATOR_CRON == HOST_SCHEDULE
    assert _tracer_freeze_passed(tmp_path / "on-time", timedelta(seconds=55))
    # Control: the same bundle witnessed one second beyond the grace fails continuity.
    assert not _tracer_freeze_passed(tmp_path / "late", timedelta(seconds=GRACE_1800 + 1))


# --------------------------------------------------------------------------- #
# (d) without host ticks the report is exactly the GitHub-only report
# --------------------------------------------------------------------------- #


def test_without_host_ticks_the_report_is_exactly_the_github_only_report() -> None:
    runs, lines = _good([1, 2, 4])
    plain = _report(runs, lines)
    with_pin = freeze_evidence_report(
        pin_utc=PIN,
        window_end_utc=END,
        cron="0 * * * *",
        lines=lines,
        runs=runs,
        grace_seconds=GRACE,
        detected_at_utc=DETECTED,
        host_ticks=(),
        pinned_epoch_id="a" * 64,
        pinned_hash="b" * 64,
    )
    assert with_pin == plain
    assert with_pin.statement == plain.statement
    assert with_pin.host_results == ()
