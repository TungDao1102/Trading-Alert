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

import pytest
from src.paper.coverage import (
    EvidenceGapReason,
    HostTick,
    HostTickVerdict,
    freeze_evidence_report,
)
from src.paper.evidence_bundle import load_evidence_bundle
from src.paper.freeze import DiffLogEntry, FreezeSkippedEntry, read_run_metadata

from tests.test_paper_exit_evaluator import (
    CRON as EVALUATOR_CRON,
)
from tests.test_paper_exit_evaluator import (
    EPOCH_ID,
    OTHER_EPOCH_ID,
    PARAMETER_HASH,
    THRESHOLDS,
    TrialFixture,
    _evaluate,
    _result,
    make_fixture,
)
from tests.test_paper_freeze_evidence import (
    DETECTED,
    END,
    GRACE,
    GRACE_VALUES,
    PIN,
    _at,
    _clean,
    _good,
    _report,
    _run,
)
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


# --------------------------------------------------------------------------- #
# Task 2: the verdict matrix (hourly cron 0, pin 00:10, window end 06:00, epoch a*64, hash b*64).
# --------------------------------------------------------------------------- #

E_EPOCH = "a" * 64
E_HASH = "b" * 64
E_CRON = "0 * * * *"
OTHER_TICK_ID = "fedcba9876543210fedcba9876543210"


def _host_tick(
    slot: datetime,
    *,
    witnessed: datetime,
    checked: datetime | None = None,
    outcome: str = "clean",
    meta: dict[str, str] | None = None,
    path: str | None = None,
    data: bytes | None = None,
    epoch_id: str = E_EPOCH,
    current_hash: str = E_HASH,
    tick_id: str = TICK_ID,
) -> HostTick:
    """A host tick whose bytes are the CLI's own line (written through the line classes)."""
    if data is None:
        moment = checked if checked is not None else slot + timedelta(seconds=5)
        metadata = host_metadata(tick_id, E_CRON) if meta is None else meta
        entry: DiffLogEntry | FreezeSkippedEntry
        if outcome == "SKIPPED":
            entry = FreezeSkippedEntry(moment, "allowlist empty", metadata)
        else:
            entry = DiffLogEntry(
                moment,
                epoch_id,
                E_HASH,
                current_hash if outcome == "clean" else "d" * 64,
                outcome,
                metadata,
            )
        data = (entry.to_jsonl() + "\n").encode("utf-8")
    return HostTick(path or host_path(slot, tick_id), witnessed, len(data), data)


def _host_report(runs, lines, ticks, *, grace=GRACE, pinned_hash=E_HASH, epoch_id=E_EPOCH):
    return freeze_evidence_report(
        pin_utc=PIN,
        window_end_utc=END,
        cron=E_CRON,
        lines=lines,
        runs=runs,
        grace_seconds=grace,
        detected_at_utc=DETECTED,
        host_ticks=ticks,
        pinned_epoch_id=epoch_id,
        pinned_hash=pinned_hash,
    )


def _verdicts(report) -> list[HostTickVerdict]:
    return [result.verdict for result in report.host_results]


def _status(report, slot: datetime) -> str:
    return next(r.status for r in report.slot_results if r.slot_utc == slot)


def test_a_host_tick_with_no_github_run_satisfies_its_slot() -> None:
    slot = _at(2)
    tick = _host_tick(slot, witnessed=slot + timedelta(seconds=20))
    report = _host_report([], [], [tick])
    assert _verdicts(report) == [HostTickVerdict.SATISFIED]
    result = next(r for r in report.slot_results if r.slot_utc == slot)
    assert (result.status, result.run_id, result.host_path) == ("SATISFIED", None, tick.path)
    assert slot in report.satisfied_slots
    assert all(gap.slot_utc != slot for gap in report.gaps)
    assert "Host witness ticks (16-DEC-HOST-TICK): 1 judged, 1 satisfied a slot" in report.statement


def test_lateness_comes_from_the_witness_time_only() -> None:
    slot = _at(2)
    late = _host_tick(
        slot,
        witnessed=slot + timedelta(seconds=GRACE + 1),
        checked=slot + timedelta(seconds=10),
    )
    report = _host_report([], [], [late])
    assert _verdicts(report) == [HostTickVerdict.LATE_BEYOND_GRACE]
    assert _status(report, slot) == "EVIDENCE_GAP"
    assert any(gap.slot_utc == slot for gap in report.gaps)


@pytest.mark.parametrize("grace", GRACE_VALUES)
def test_no_grace_value_lets_a_late_witness_satisfy_a_slot(grace: int) -> None:
    slot = _at(2)
    on_edge = _host_tick(slot, witnessed=slot + timedelta(seconds=grace), checked=slot)
    assert _verdicts(_host_report([], [], [on_edge], grace=grace)) == [HostTickVerdict.SATISFIED]
    beyond = _host_tick(
        slot, witnessed=slot + timedelta(seconds=grace + 1), checked=slot + timedelta(seconds=1)
    )
    report = _host_report([], [], [beyond], grace=grace)
    assert HostTickVerdict.SATISFIED not in _verdicts(report)
    assert slot not in report.satisfied_slots
    assert not report.qualifying_from_pin


def test_a_line_time_outside_the_slot_to_witness_interval_is_out_of_slot() -> None:
    slot = _at(2)
    before = _host_tick(
        slot, witnessed=slot + timedelta(seconds=20), checked=slot - timedelta(seconds=1)
    )
    after = _host_tick(
        _at(3),
        witnessed=_at(3) + timedelta(seconds=20),
        checked=_at(3) + timedelta(seconds=30),
        tick_id=OTHER_TICK_ID,
    )
    fast_clock = _host_tick(
        slot + timedelta(hours=1),
        witnessed=slot + timedelta(seconds=20),
        checked=slot + timedelta(hours=1),
        tick_id="1" * 32,
    )
    for tick in (before, after, fast_clock):
        report = _host_report([], [], [tick])
        assert _verdicts(report) == [HostTickVerdict.OUT_OF_SLOT]
        assert not report.satisfied_slots


def test_a_tick_witnessed_after_the_next_slot_serves_only_that_next_slot() -> None:
    slot, nxt = _at(2), _at(3)
    stale = _host_tick(slot, witnessed=nxt + timedelta(seconds=10))
    report = _host_report([], [], [stale])
    assert _verdicts(report) == [HostTickVerdict.OUT_OF_SLOT]
    assert report.host_results[0].slot_utc == nxt
    assert slot not in report.satisfied_slots and nxt not in report.satisfied_slots
    for_next = _host_tick(nxt, witnessed=nxt + timedelta(seconds=10), tick_id=OTHER_TICK_ID)
    report = _host_report([], [], [for_next])
    assert nxt in report.satisfied_slots and slot not in report.satisfied_slots


@pytest.mark.parametrize("outcome", ["REGISTRY_DIFF", "SKIPPED"])
def test_a_non_clean_host_line_after_the_pin_breaks_the_slot_and_the_window(outcome: str) -> None:
    slot = _at(2)
    tick = _host_tick(slot, witnessed=slot + timedelta(seconds=20), outcome=outcome)
    report = _host_report([], [], [tick])
    assert _verdicts(report) == [HostTickVerdict.NON_CLEAN]
    assert _status(report, slot) == "BROKEN_BY_LINE"
    brk = next(b for b in report.breaks if b.host_path == tick.path)
    assert (brk.at_utc, brk.outcome, brk.run_id) == (tick.witnessed_at_utc, outcome, None)
    # GitHub satisfies the slot, yet the host break still ends continuity.
    runs, lines = _good([1, 2, 3, 4, 5, 6])
    report = _host_report(runs, lines, [tick])
    assert _status(report, slot) == "SATISFIED"
    assert report.satisfied_slots == report.slots
    assert not report.qualifying_from_pin


def _two_lines(slot: datetime) -> bytes:
    line = _host_tick(slot, witnessed=slot).data or b""
    return line + line


def _unreadable(case: str, slot: datetime, witnessed: datetime) -> HostTick:
    line = _host_tick(slot, witnessed=witnessed).data or b""
    if case == "two lines":
        return HostTick(host_path(slot), witnessed, len(line) * 2, line + line)
    if case == "no trailing newline":
        return _host_tick(slot, witnessed=witnessed, data=line.rstrip(b"\n"))
    if case == "no bytes":
        return HostTick(host_path(slot), witnessed, len(line), None)
    if case == "size differs":
        return HostTick(host_path(slot), witnessed, len(line) + 1, line)
    if case == "not json":
        return _host_tick(slot, witnessed=witnessed, data=b"nope\n")
    if case == "not an object":
        return _host_tick(slot, witnessed=witnessed, data=b"[1]\n")
    if case == "not utf-8":
        return _host_tick(slot, witnessed=witnessed, data=b"\xff\xfe\n")
    if case == "unknown outcome":
        return _host_tick(slot, witnessed=witnessed, data=b'{"outcome":"weird"}\n')
    return _host_tick(slot, witnessed=witnessed, path="garbage.jsonl")


@pytest.mark.parametrize(
    "case",
    [
        "two lines",
        "no trailing newline",
        "no bytes",
        "size differs",
        "not json",
        "not an object",
        "not utf-8",
        "unknown outcome",
        "bad path",
    ],
)
def test_an_unreadable_witness_object_is_a_break_and_never_evidence(case: str) -> None:
    slot = _at(2)
    witnessed = slot + timedelta(seconds=20)
    tick = _unreadable(case, slot, witnessed)
    report = _host_report([], [], [tick])
    assert _verdicts(report) == [HostTickVerdict.UNREADABLE]
    assert slot not in report.satisfied_slots
    brk = next(b for b in report.breaks if b.host_path == tick.path)
    assert (brk.at_utc, brk.outcome) == (witnessed, "INVALID")
    assert not report.qualifying_from_pin


@pytest.mark.parametrize(
    "meta",
    [
        {"schedule": E_CRON, "tick_id": TICK_ID},
        {"schedule": E_CRON, "source": "github", "tick_id": TICK_ID},
        {"schedule": E_CRON, "source": "host", "tick_id": TICK_ID, "run_id": "9"},
        {"schedule": E_CRON, "source": "host", "tick_id": TICK_ID, "event_name": "schedule"},
        {"schedule": E_CRON, "source": "host", "tick_id": TICK_ID, "run_attempt": "1"},
        {"schedule": E_CRON, "source": "host", "tick_id": OTHER_TICK_ID},
    ],
)
def test_a_host_line_with_a_github_identity_or_another_tick_id_is_wrong_source(
    meta: dict[str, str],
) -> None:
    slot = _at(2)
    tick = _host_tick(slot, witnessed=slot + timedelta(seconds=20), meta=meta)
    report = _host_report([], [], [tick])
    assert _verdicts(report) == [HostTickVerdict.WRONG_SOURCE]
    assert slot not in report.satisfied_slots


def test_schedule_epoch_and_hash_must_be_the_evaluated_ones() -> None:
    slot = _at(2)
    w = slot + timedelta(seconds=20)
    wrong_cron = _host_tick(slot, witnessed=w, meta=host_metadata(TICK_ID, "34 * * * *"))
    assert _verdicts(_host_report([], [], [wrong_cron])) == [HostTickVerdict.SCHEDULE_MISMATCH]
    other_epoch = _host_tick(slot, witnessed=w, epoch_id="c" * 64)
    assert _verdicts(_host_report([], [], [other_epoch])) == [HostTickVerdict.WRONG_EPOCH_OR_HASH]
    other_hash = _host_tick(slot, witnessed=w, current_hash="c" * 64)
    assert _verdicts(_host_report([], [], [other_hash])) == [HostTickVerdict.WRONG_EPOCH_OR_HASH]
    for tick in (wrong_cron, other_epoch, other_hash):
        assert slot not in _host_report([], [], [tick]).satisfied_slots


def test_one_tick_id_in_two_objects_satisfies_nothing() -> None:
    first, second = _at(2), _at(3)
    ticks = [
        _host_tick(first, witnessed=first + timedelta(seconds=20)),
        _host_tick(second, witnessed=second + timedelta(seconds=20)),
    ]
    report = _host_report([], [], ticks)
    assert _verdicts(report) == [HostTickVerdict.DUPLICATE, HostTickVerdict.DUPLICATE]
    assert not report.satisfied_slots


def test_a_github_line_that_carries_host_fields_never_satisfies_a_slot() -> None:
    for extra in ({"source": "host"}, {"tick_id": TICK_ID}):
        runs = [_run(1002, _at(2, 0, 12))]
        clean = _clean(1002, _at(2, 0, 40))
        line = DiffLogEntry(
            clean.checked_at_utc,
            clean.epoch_id,
            clean.pinned_hash,
            clean.current_hash,
            "clean",
            {**(clean.run_metadata or {}), **extra},
        )
        report = _report(runs, [line], cron=E_CRON)
        slot_gap = next(g for g in report.gaps if g.slot_utc == _at(2))
        assert slot_gap.reason is EvidenceGapReason.INVALID_LINE
        assert _at(2) not in report.satisfied_slots


def test_a_host_format_line_in_the_github_log_satisfies_no_slot() -> None:
    slot = _at(2)
    host_line = DiffLogEntry(
        slot + timedelta(seconds=5),
        E_EPOCH,
        E_HASH,
        E_HASH,
        "clean",
        host_metadata(TICK_ID, E_CRON),
    )
    report = _report([], [host_line], cron=E_CRON)
    assert slot not in report.satisfied_slots
    assert any(g.slot_utc == slot for g in report.gaps)


def test_a_host_tick_witnessed_at_or_before_the_pin_is_not_judged() -> None:
    before = _host_tick(_at(0), witnessed=PIN - timedelta(minutes=5), outcome="REGISTRY_DIFF")
    at_pin = _host_tick(_at(0), witnessed=PIN, outcome="SKIPPED", tick_id=OTHER_TICK_ID)
    report = _host_report([], [], [before, at_pin])
    assert report.host_results == ()
    assert report.breaks == ()


def test_host_ticks_need_the_pin_identity() -> None:
    tick = _host_tick(_at(2), witnessed=_at(2, 0, 20))
    kwargs: dict[str, Any] = {
        "pin_utc": PIN,
        "window_end_utc": END,
        "cron": E_CRON,
        "lines": [],
        "runs": [],
        "grace_seconds": GRACE,
        "detected_at_utc": DETECTED,
        "host_ticks": [tick],
    }
    with pytest.raises(ValueError, match="pinned_hash"):
        freeze_evidence_report(**kwargs, pinned_epoch_id=E_EPOCH)
    with pytest.raises(ValueError, match="pinned_epoch_id"):
        freeze_evidence_report(**kwargs, pinned_hash=E_HASH)


def test_the_statement_says_so_when_host_ticks_complete_the_slots() -> None:
    runs, lines = _good([1, 2, 3, 4, 5])
    slot = _at(6)
    tick = _host_tick(slot, witnessed=slot + timedelta(seconds=20))
    report = _host_report(runs, lines, [tick])
    assert report.qualifying_from_pin
    assert "a CLEAN line of a schedule run or of a witnessed host tick" in report.statement
    plain = _host_report(runs, lines, [])
    assert "Host witness" not in plain.statement and "host tick" not in plain.statement


# --------------------------------------------------------------------------- #
# Through evaluate_trial: host lines in the single-epoch and hash criteria.
# --------------------------------------------------------------------------- #


def _evaluated_gap_bundle(tmp_path: Path, **line_kwargs: Any):
    fixture, slot = _gap_fixture()
    data = host_line_bytes(slot + timedelta(seconds=40), **line_kwargs)
    objects = [(host_path(slot), data, slot + timedelta(seconds=55))]
    return _evaluate(load_evidence_bundle(write_host_bundle(fixture, tmp_path / "b", objects)))


def test_host_lines_are_read_by_the_single_epoch_and_hash_criteria(tmp_path: Path) -> None:
    baseline = _evaluated_gap_bundle(tmp_path / "ok")
    assert _result(baseline, "single epoch").passed
    assert _result(baseline, "pinned hash unchanged").passed
    other_epoch = _evaluated_gap_bundle(tmp_path / "epoch", epoch_id=OTHER_EPOCH_ID)
    assert not _result(other_epoch, "single epoch").passed
    other_hash = _evaluated_gap_bundle(tmp_path / "hash", current_hash="a" * 64)
    assert not _result(other_hash, "pinned hash unchanged").passed


def test_freeze_continuity_gains_one_host_line_only_when_host_results_exist(
    tmp_path: Path,
) -> None:
    with_host = _result(_evaluated_gap_bundle(tmp_path / "host"), "freeze continuity")
    host_lines = [line for line in with_host.evidence if line.startswith("host witness ticks")]
    assert len(host_lines) == 1 and "SATISFIED 1" in host_lines[0]
    plain_bundle = load_evidence_bundle(make_fixture().write(tmp_path / "p"))
    plain = _result(_evaluate(plain_bundle), "freeze continuity")
    assert not any(line.startswith("host witness ticks") for line in plain.evidence)
