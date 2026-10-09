"""Freeze-tick continuity evidence (Phase 16, plan 16-15; D-21, D-22, REV-02, REV-18).

The reconciler builds the expected hourly slot grid from the epoch pin to the window end and
looks every slot up in the freeze-check lines plus the exported GitHub run list. A missing,
late, failed or manual tick is an EvidenceGap, never CLEAN, never interpolated; the qualifying
trial then restarts with a new epoch pin.
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from src.paper import coverage as coverage_module
from src.paper.coverage import (
    EvidenceGapReason,
    FreezeLine,
    GithubRun,
    coverage_report,
    expected_slots,
    freeze_evidence_report,
    parse_freeze_log,
    parse_github_runs,
)
from src.paper.freeze import DiffLogEntry, FreezeSkippedEntry

PIN = datetime(2026, 11, 1, 0, 10, tzinfo=UTC)
END = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
CRON = "0 * * * *"
GRACE = 300
DETECTED = datetime(2026, 11, 2, tzinfo=UTC)
RESTART_SENTENCE = "qualifying trial restarts with a new epoch pin (D065 item 4)"


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, 1, hour, minute, second, tzinfo=UTC)


def _run(
    run_id: int,
    created: datetime,
    *,
    event: str = "schedule",
    conclusion: str | None = "success",
    attempt: int = 1,
) -> GithubRun:
    return GithubRun(
        run_id=str(run_id),
        event=event,
        status="completed",
        conclusion=conclusion,
        created_at_utc=created,
        run_started_at_utc=created + timedelta(seconds=3),
        run_attempt=attempt,
        head_sha="c" * 40,
    )


def _meta(run_id: int, *, schedule: str = CRON, event: str = "schedule", attempt: str = "1"):
    return {
        "run_id": str(run_id),
        "run_attempt": attempt,
        "event_name": event,
        "schedule": schedule,
        "commit": "c" * 40,
    }


def _clean(run_id: int, checked: datetime, **meta_kwargs: str) -> DiffLogEntry:
    return DiffLogEntry(
        checked_at_utc=checked,
        epoch_id="a" * 64,
        pinned_hash="b" * 64,
        current_hash="b" * 64,
        outcome="clean",
        run_metadata=_meta(run_id, **meta_kwargs),
    )


def _diff(run_id: int, checked: datetime) -> DiffLogEntry:
    return DiffLogEntry(
        checked_at_utc=checked,
        epoch_id="a" * 64,
        pinned_hash="b" * 64,
        current_hash="d" * 64,
        outcome="REGISTRY_DIFF",
        run_metadata=_meta(run_id),
    )


def _skipped(checked: datetime, run_id: int | None = None) -> FreezeSkippedEntry:
    return FreezeSkippedEntry(
        checked_at_utc=checked,
        reason="allowlist empty",
        run_metadata=None if run_id is None else _meta(run_id),
    )


def _good(hours: list[int]) -> tuple[list[GithubRun], list[DiffLogEntry]]:
    """One schedule run and one CLEAN line per hourly slot (run id = 1000 + hour)."""
    runs = [_run(1000 + h, _at(h, 0, 12)) for h in hours]
    lines = [_clean(1000 + h, _at(h, 0, 40)) for h in hours]
    return runs, lines


def _report(runs, lines, *, pin=PIN, end=END, cron=CRON, grace=GRACE):
    return freeze_evidence_report(
        pin_utc=pin,
        window_end_utc=end,
        cron=cron,
        lines=lines,
        runs=runs,
        grace_seconds=grace,
        detected_at_utc=DETECTED,
    )


# --------------------------------------------------------------------------- #
# expected_slots
# --------------------------------------------------------------------------- #


def test_expected_slots_follow_the_hourly_cron_after_the_pin_up_to_the_end() -> None:
    assert expected_slots(PIN, END, "0 * * * *") == tuple(_at(h) for h in range(1, 7))


def test_the_slot_grid_follows_the_minute_of_the_cron() -> None:
    """Test 7: a cron minute chosen at checkpoint Q-Q changes the grid and nothing else."""
    assert expected_slots(PIN, END, "23 * * * *") == tuple(_at(h, 23) for h in range(0, 6))
    assert expected_slots(_at(0, 30), END, "23 * * * *") == tuple(_at(h, 23) for h in range(1, 6))


def test_a_slot_at_the_pin_instant_is_not_after_the_pin() -> None:
    assert expected_slots(_at(1), _at(3), "0 * * * *") == (_at(2), _at(3))


@pytest.mark.parametrize(
    "bad",
    [
        "*/5 * * * *",
        "0 3 * * *",
        "60 * * * *",
        "0 * * * 1",
        "0,30 * * * *",
        "00 * * * *",
        "0 * * *",
        "",
        "@hourly",
    ],
)
def test_a_cron_that_is_not_the_hourly_form_is_refused(bad: str) -> None:
    """Test 5: fail closed rather than misread a schedule."""
    with pytest.raises(ValueError, match="hourly"):
        expected_slots(PIN, END, bad)
    with pytest.raises(ValueError, match="hourly"):
        _report([], [], cron=bad)


def test_expected_slots_refuse_naive_times() -> None:
    with pytest.raises(ValueError, match="UTC"):
        expected_slots(datetime(2026, 11, 1), END, CRON)  # noqa: DTZ001


# --------------------------------------------------------------------------- #
# freeze_evidence_report
# --------------------------------------------------------------------------- #


def test_every_slot_with_a_clean_scheduled_line_is_one_qualifying_segment() -> None:
    """Test 1."""
    runs, lines = _good([1, 2, 3, 4, 5, 6])
    report = _report(runs, lines)

    assert report.slots == tuple(_at(h) for h in range(1, 7))
    assert report.satisfied_slots == report.slots
    assert report.gaps == ()
    assert report.breaks == ()
    assert report.qualifying_from_pin is True
    assert len(report.segments) == 1
    segment = report.segments[0]
    assert (segment.start_utc, segment.end_utc, segment.slot_count) == (PIN, _at(6), 6)
    assert RESTART_SENTENCE not in report.statement


def test_a_slot_with_no_run_and_no_line_is_an_evidence_gap_never_clean() -> None:
    """Test 2."""
    runs, lines = _good([1, 2, 4, 5, 6])
    report = _report(runs, lines)

    assert [(g.slot_utc, g.reason) for g in report.gaps] == [
        (_at(3), EvidenceGapReason.NO_RUN_FOUND)
    ]
    assert report.gaps[0].schedule == CRON
    assert report.gaps[0].detected_at_utc == DETECTED
    assert report.gaps[0].run_id is None
    assert _at(3) not in report.satisfied_slots
    assert [(s.start_utc, s.end_utc, s.slot_count) for s in report.segments] == [
        (PIN, _at(2), 2),
        (_at(4), _at(6), 3),
    ]
    assert report.qualifying_from_pin is False
    assert RESTART_SENTENCE in report.statement


def test_a_failed_run_without_a_line_a_late_run_and_a_manual_run_are_not_clean() -> None:
    """Test 3."""
    # 02:00: the run failed before writing its line.
    failed = _run(2002, _at(2, 0, 10), conclusion="failure")
    # 03:00: created beyond the grace (301 s).
    late = _run(2003, _at(3, 0) + timedelta(seconds=GRACE + 1))
    late_line = _clean(2003, _at(3, 6, 30))
    # 04:00: only a manual workflow_dispatch run, with a CLEAN line.
    manual = _run(2004, _at(4, 0, 5), event="workflow_dispatch")
    manual_line = _clean(2004, _at(4, 0, 30), event="workflow_dispatch", schedule="")
    runs, lines = _good([1, 5, 6])
    report = _report([*runs, failed, late, manual], [*lines, late_line, manual_line])

    reasons = {g.slot_utc: g.reason for g in report.gaps}
    assert reasons == {
        _at(2): EvidenceGapReason.RUN_WITHOUT_LINE,
        _at(3): EvidenceGapReason.RUN_LATE_BEYOND_GRACE,
        _at(4): EvidenceGapReason.NO_RUN_FOUND,
    }
    gap_runs = {g.slot_utc: g.run_id for g in report.gaps}
    assert gap_runs[_at(2)] == "2002"
    assert gap_runs[_at(3)] == "2003"
    assert gap_runs[_at(4)] is None
    assert report.satisfied_slots == (_at(1), _at(5), _at(6))
    assert report.qualifying_from_pin is False


def test_a_registry_diff_line_ends_the_segment() -> None:
    """Test 4: REGISTRY_DIFF after the pin breaks continuity."""
    runs, lines = _good([1, 2, 4, 5, 6])
    runs.append(_run(1003, _at(3, 0, 12)))
    lines.append(_diff(1003, _at(3, 0, 40)))
    report = _report(runs, lines)

    assert [b.outcome for b in report.breaks] == ["REGISTRY_DIFF"]
    assert report.gaps == ()
    assert _at(3) not in report.satisfied_slots
    assert [s.slot_count for s in report.segments] == [2, 3]
    assert report.qualifying_from_pin is False
    assert RESTART_SENTENCE in report.statement


def test_a_skipped_line_after_the_pin_ends_the_segment_but_one_before_it_is_ignored() -> None:
    """Test 4: SKIPPED after the pin fails the window; SKIPPED before the pin does not count."""
    runs, lines = _good([1, 2, 3, 4, 5, 6])
    before = _skipped(_at(0, 5))
    after = _skipped(_at(3, 30))

    clean_with_early_skip = _report(runs, [before, *lines])
    assert clean_with_early_skip.qualifying_from_pin is True
    assert clean_with_early_skip.breaks == ()

    broken = _report(runs, [before, *lines, after])
    assert [(b.outcome, b.at_utc) for b in broken.breaks] == [("SKIPPED", _at(3, 30))]
    assert [s.slot_count for s in broken.segments] == [3, 3]
    assert broken.qualifying_from_pin is False


def test_an_unparsable_line_cannot_be_placed_and_fails_closed() -> None:
    runs, lines = _good([1, 2, 3, 4, 5, 6])
    parsed = parse_freeze_log("this is not json\n")
    assert parsed[0].outcome == "INVALID"
    report = _report(runs, [*parsed, *lines])
    assert report.unplaced_line_count == 1
    assert report.qualifying_from_pin is False


def test_a_line_whose_schedule_differs_from_the_evaluated_cron_is_a_mismatch_gap() -> None:
    """Test 8: a cron edit between the pin and the end is detected, never tolerated."""
    runs, lines = _good([1, 2, 4, 5, 6])
    runs.append(_run(1003, _at(3, 0, 12)))
    lines.append(_clean(1003, _at(3, 0, 40), schedule="30 * * * *"))
    report = _report(runs, lines)

    assert [(g.slot_utc, g.reason, g.run_id) for g in report.gaps] == [
        (_at(3), EvidenceGapReason.SCHEDULE_MISMATCH, "1003")
    ]
    assert _at(3) not in report.satisfied_slots
    assert report.qualifying_from_pin is False


def test_evaluating_the_old_cron_against_new_cron_lines_finds_no_clean_slot() -> None:
    """Test 8: lines of cron "0 * * * *" never satisfy slots of cron "23 * * * *"."""
    runs, lines = _good([1, 2, 3, 4, 5, 6])
    report = _report(runs, lines, cron="23 * * * *")
    assert report.satisfied_slots == ()
    assert report.qualifying_from_pin is False
    assert all(g.schedule == "23 * * * *" for g in report.gaps)


def test_a_line_that_names_a_missing_run_cannot_satisfy_a_slot() -> None:
    """The run list is the proof a scheduled run existed; a line alone is not enough."""
    runs, lines = _good([1, 2, 4, 5, 6])
    lines.append(_clean(7777, _at(3, 0, 40)))
    report = _report(runs, lines)
    assert [(g.slot_utc, g.reason) for g in report.gaps] == [
        (_at(3), EvidenceGapReason.NO_RUN_FOUND)
    ]


def test_a_clean_line_without_run_metadata_cannot_satisfy_a_slot() -> None:
    runs, lines = _good([1, 2, 4, 5, 6])
    runs.append(_run(1003, _at(3, 0, 12)))
    lines.append(
        DiffLogEntry(
            checked_at_utc=_at(3, 0, 40),
            epoch_id="a" * 64,
            pinned_hash="b" * 64,
            current_hash="b" * 64,
            outcome="clean",
        )
    )
    report = _report(runs, lines)
    assert [(g.slot_utc, g.reason) for g in report.gaps] == [
        (_at(3), EvidenceGapReason.RUN_WITHOUT_LINE)
    ]


def test_a_rerun_line_does_not_fill_a_missed_tick() -> None:
    """A re-run is run later; its line is not the tick evidence of the slot."""
    runs, lines = _good([1, 2, 4, 5, 6])
    runs.append(_run(1003, _at(3, 0, 12), attempt=2))
    lines.append(_clean(1003, _at(3, 50), attempt="2"))
    report = _report(runs, lines)
    assert [(g.slot_utc, g.reason) for g in report.gaps] == [
        (_at(3), EvidenceGapReason.INVALID_LINE)
    ]


def test_inputs_are_not_mutated() -> None:
    runs, lines = _good([1, 2, 4, 5, 6])
    snapshot = (list(runs), list(lines))
    _report(runs, lines)
    assert (runs, lines) == snapshot


def test_the_function_returns_records_and_never_writes_a_file() -> None:
    """Test 5: the module has no file-writing call; it never edits registry_diff.jsonl."""
    source = Path(inspect.getsourcefile(coverage_module) or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {"write_text", "write_bytes", "open", "touch", "unlink", "rename", "replace_file"}
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)
    assert called.isdisjoint(banned), called & banned
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "src.paper.freeze"
        for alias in node.names
    }
    assert "_append_diff_entry" not in imported


def test_freeze_integrity_and_runtime_health_are_two_separate_reports() -> None:
    """Test 6: no shared evidence input, no field of one report in the other (REV-02)."""
    freeze_params = set(inspect.signature(freeze_evidence_report).parameters)
    health_params = set(inspect.signature(coverage_report).parameters)
    shared = freeze_params & health_params
    assert shared <= {"window_end_utc"}, shared

    runs, lines = _good([1, 2, 3, 4, 5, 6])
    freeze = _report(runs, lines)
    health = coverage_report(
        window_start_utc=PIN,
        window_end_utc=END,
        intervals=[],
        continuous_uncovered_ceiling_seconds=3600,
    )
    freeze_fields = set(freeze.__dataclass_fields__)
    health_fields = set(health.__dataclass_fields__)
    assert freeze_fields & health_fields <= {"window_end_utc"}
    # A clean freeze report does not make anything covered and vice versa.
    assert freeze.qualifying_from_pin is True
    assert health.coverage_pass is False


def test_every_gap_and_break_is_reported_together_with_the_restart_rule() -> None:
    runs, lines = _good([1, 2, 5, 6])
    report = _report(runs, lines)
    assert [g.slot_utc for g in report.gaps] == [_at(3), _at(4)]
    assert "2 EVIDENCE_GAP" in report.statement
    assert "never interpolated" in report.statement


def test_no_slots_in_the_window_is_not_qualifying() -> None:
    report = _report([], [], pin=_at(0, 10), end=_at(0, 50))
    assert report.slots == ()
    assert report.qualifying_from_pin is False


def test_a_short_window_still_needs_its_slot() -> None:
    runs, lines = _good([1])
    report = _report(runs, lines, pin=_at(0, 10), end=_at(1, 30))
    assert report.slots == (_at(1),)
    assert report.qualifying_from_pin is True


# --------------------------------------------------------------------------- #
# Parsing helpers.
# --------------------------------------------------------------------------- #


def test_parse_freeze_log_reads_clean_diff_and_skipped_lines_with_run_metadata() -> None:
    entries = [
        _clean(1001, _at(1, 0, 40)),
        _diff(1002, _at(2, 0, 40)),
        _skipped(_at(0, 5), run_id=999),
        _skipped(_at(0, 6)),
    ]
    text = "\n".join(entry.to_jsonl() for entry in entries) + "\n\n"
    parsed = parse_freeze_log(text)
    assert [(p.outcome, p.checked_at_utc) for p in parsed] == [
        ("clean", _at(1, 0, 40)),
        ("REGISTRY_DIFF", _at(2, 0, 40)),
        ("SKIPPED", _at(0, 5)),
        ("SKIPPED", _at(0, 6)),
    ]
    assert parsed[0].run_metadata == _meta(1001)
    assert parsed[3].run_metadata is None
    # Typed entries and parsed lines are interchangeable inputs.
    runs, lines = _good([1, 2, 3, 4, 5, 6])
    text = "\n".join(entry.to_jsonl() for entry in lines)
    assert _report(runs, parse_freeze_log(text)).qualifying_from_pin is True


def test_parse_freeze_log_marks_bad_lines_invalid_and_keeps_what_it_can() -> None:
    dated_bad = json.dumps(
        {
            "checked_at_utc": _at(3, 0, 40).isoformat(),
            "outcome": "weird",
            "run_metadata": _meta(1003),
        }
    )
    parsed = parse_freeze_log("not json\n[1, 2]\n" + dated_bad + "\n")
    assert [p.outcome for p in parsed] == ["INVALID", "INVALID", "INVALID"]
    assert parsed[0].checked_at_utc is None
    assert parsed[2].checked_at_utc == _at(3, 0, 40)
    assert parsed[2].run_metadata == _meta(1003)


def test_a_dated_invalid_line_of_a_slot_run_is_an_invalid_line_gap() -> None:
    runs, lines = _good([1, 2, 4, 5, 6])
    runs.append(_run(1003, _at(3, 0, 12)))
    bad = FreezeLine(
        checked_at_utc=_at(3, 0, 40),
        outcome="INVALID",
        run_metadata=_meta(1003),
        detail="outcome not recognised",
    )
    report = _report(runs, [*lines, bad])
    assert [(g.slot_utc, g.reason) for g in report.gaps] == [
        (_at(3), EvidenceGapReason.INVALID_LINE)
    ]


def test_parse_github_runs_reads_the_rest_run_list() -> None:
    payload = {
        "total_count": 2,
        "workflow_runs": [
            {
                "id": 1001,
                "event": "schedule",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-11-01T01:00:12Z",
                "run_started_at": "2026-11-01T01:00:15Z",
                "run_attempt": 1,
                "head_sha": "c" * 40,
            },
            {
                "id": 1002,
                "event": "workflow_dispatch",
                "status": "in_progress",
                "conclusion": None,
                "created_at": "2026-11-01T02:00:12Z",
                "run_started_at": None,
                "run_attempt": 1,
                "head_sha": "c" * 40,
            },
        ],
    }
    for text in (json.dumps(payload), json.dumps(payload["workflow_runs"])):
        parsed = parse_github_runs(text)
        assert [(r.run_id, r.event, r.conclusion) for r in parsed] == [
            ("1001", "schedule", "success"),
            ("1002", "workflow_dispatch", None),
        ]
        assert parsed[0].created_at_utc == _at(1, 0, 12)
        assert parsed[1].run_started_at_utc is None
    with pytest.raises(ValueError, match="runs"):
        parse_github_runs(json.dumps({"nope": []}))


# --------------------------------------------------------------------------- #
# Task 4: grace semantics (never CLEAN) and earlier-epoch evidence kept as auxiliary.
# --------------------------------------------------------------------------- #

GRACE_VALUES = (0, 1, 60, 300, 1800, 3599)


def _hand_assigned_clean_slots(runs: list[GithubRun], lines: list[DiffLogEntry]) -> set[datetime]:
    """Slots that have a CLEAN schedule-run line assigned (computed by hand, hourly cron 0)."""
    clean_ids = {
        entry.run_metadata["run_id"]
        for entry in lines
        if entry.outcome == "clean"
        and entry.run_metadata is not None
        and entry.run_metadata.get("schedule") == CRON
    }
    return {
        run.created_at_utc.replace(minute=0, second=0, microsecond=0)
        for run in runs
        if run.event == "schedule" and run.run_id in clean_ids
    }


def test_no_grace_value_turns_a_slot_without_a_clean_line_into_clean() -> None:
    """Test 1 (REV-02, REV-18): the grace only separates a late valid run from a missing one."""
    runs, lines = _good([1, 2, 4, 5, 6])  # slot 03:00 has no run and no line
    # Slot 04:00 also gets a late extra run, 10 minutes after the slot, with a CLEAN line.
    runs = [r for r in runs if r.run_id != "1004"]
    lines = [entry for entry in lines if entry.run_metadata["run_id"] != "1004"]
    runs.append(_run(1004, _at(4, 10)))
    lines.append(_clean(1004, _at(4, 10, 40)))

    eligible = _hand_assigned_clean_slots(runs, lines)
    satisfied_by_grace: dict[int, set[datetime]] = {}
    for grace in GRACE_VALUES:
        report = _report(runs, lines, grace=grace)
        reasons = {g.slot_utc: g.reason for g in report.gaps}
        assert reasons[_at(3)] is EvidenceGapReason.NO_RUN_FOUND, grace
        assert set(report.satisfied_slots) <= eligible, grace
        assert _at(3) not in report.satisfied_slots, grace
        satisfied_by_grace[grace] = set(report.satisfied_slots)
        # The late run at 04:10 is late-but-valid (600 s) or beyond the grace; nothing else moves.
        if grace >= 600:
            assert _at(4) in report.satisfied_slots
        else:
            assert reasons[_at(4)] is EvidenceGapReason.RUN_LATE_BEYOND_GRACE
    # The grace only decides whether an existing late run counts: the runs created 12 s after
    # their slot are valid from 12 s on, the run created 600 s after slot 04:00 from 600 s on.
    for grace, current in satisfied_by_grace.items():
        expected: set[datetime] = set()
        if grace >= 12:
            expected |= {_at(1), _at(2), _at(5), _at(6)}
        if grace >= 600:
            expected.add(_at(4))
        assert current == expected, grace


@pytest.mark.parametrize("grace", [3600, 3601, 7200])
def test_a_grace_at_or_above_the_slot_interval_is_refused(grace: int) -> None:
    """Test 2: one run could stand for two slots."""
    runs, lines = _good([1, 2, 3, 4, 5, 6])
    with pytest.raises(ValueError, match="one run could stand for two slots"):
        _report(runs, lines, grace=grace)


def test_a_negative_or_non_integer_grace_is_refused() -> None:
    for bad in (-1, 1.5, True, "300"):
        with pytest.raises(ValueError, match="grace_seconds"):
            _report([], [], grace=bad)  # type: ignore[arg-type]


def test_each_run_serves_at_most_its_own_slot_even_with_the_widest_grace() -> None:
    """Test 2: a CLEAN run created almost one interval late satisfies only that slot."""
    # Slot 02:00 is served by a run created at 02:59:59 (3599 s late); nothing exists for 03:00.
    late = _run(2002, _at(2, 59, 59))
    late_line = _clean(2002, _at(3, 0, 30))
    runs, lines = _good([1, 4, 5, 6])
    report = _report([*runs, late], [*lines, late_line], grace=3599)

    assert _at(2) in report.satisfied_slots
    assert _at(3) not in report.satisfied_slots
    assert [(g.slot_utc, g.reason) for g in report.gaps] == [
        (_at(3), EvidenceGapReason.NO_RUN_FOUND)
    ]


def test_a_lone_run_created_after_the_next_slot_does_not_satisfy_the_earlier_slot() -> None:
    """The run created for slot S+1 belongs to S+1, so S stays a gap."""
    only_late = _run(2003, _at(4, 0, 5))  # belongs to 04:00 whatever its line says
    line = _clean(2003, _at(4, 0, 30))
    runs, lines = _good([1, 2, 5, 6])
    report = _report([*runs, only_late], [*lines, line], grace=3599)
    reasons = {g.slot_utc: g.reason for g in report.gaps}
    assert reasons == {_at(3): EvidenceGapReason.NO_RUN_FOUND}
    assert _at(4) in report.satisfied_slots


def test_a_manual_run_never_satisfies_a_slot_whatever_its_time() -> None:
    runs, lines = _good([1, 2, 4, 5, 6])
    runs.append(_run(3003, _at(3, 0, 1), event="workflow_dispatch"))
    lines.append(_clean(3003, _at(3, 0, 20), event="workflow_dispatch", schedule=""))
    for grace in GRACE_VALUES:
        report = _report(runs, lines, grace=grace)
        assert _at(3) not in report.satisfied_slots
        assert any(g.slot_utc == _at(3) for g in report.gaps)


def test_earlier_epoch_evidence_is_auxiliary_and_reproducible_with_its_own_pin() -> None:
    """Test 3 (REV-18): evidence before the new pin never completes the new trial."""
    # Epoch E1: pin P1 00:10, window to 06:00, slot 03:00 missing -> EvidenceGap -> new pin.
    e1_runs, e1_lines = _good([1, 2, 4, 5, 6])
    # Epoch E2: new pin P2 07:10, window to 12:00, every slot present.
    p2 = _at(7, 10)
    end2 = _at(12, 0)
    e2_runs, e2_lines = _good([8, 9, 10, 11, 12])
    both_runs = [*e1_runs, *e2_runs]
    both_lines = [*e1_lines, *e2_lines]
    runs_snapshot, lines_snapshot = list(both_runs), list(both_lines)

    new_trial = _report(both_runs, both_lines, pin=p2, end=end2)
    assert new_trial.qualifying_from_pin is True
    assert new_trial.gaps == ()
    assert new_trial.satisfied_slots == tuple(_at(h) for h in range(8, 13))
    aux = new_trial.auxiliary
    assert aux.run_count == 5 and aux.line_count == 5
    assert aux.runs == tuple(e1_runs) and aux.lines == tuple(e1_lines)
    assert all(a is b for a, b in zip(aux.runs, e1_runs, strict=True))
    assert aux.first_utc == _at(1, 0, 12)
    assert aux.last_utc == _at(6, 0, 40)
    assert "earlier epoch evidence is auxiliary" in new_trial.statement
    assert "cannot complete the freeze criterion of the new trial" in new_trial.statement

    # Earlier-epoch evidence alone never satisfies a slot of the new window.
    only_old = _report(e1_runs, e1_lines, pin=p2, end=end2)
    assert only_old.satisfied_slots == ()
    assert {g.reason for g in only_old.gaps} == {EvidenceGapReason.NO_RUN_FOUND}
    assert only_old.qualifying_from_pin is False

    # With the old pin the same inputs reproduce E1's EvidenceGap exactly.
    old_trial = _report(both_runs, both_lines, pin=PIN, end=END)
    only_e1 = _report(e1_runs, e1_lines, pin=PIN, end=END)
    assert old_trial.gaps == only_e1.gaps
    assert [(g.slot_utc, g.reason) for g in old_trial.gaps] == [
        (_at(3), EvidenceGapReason.NO_RUN_FOUND)
    ]
    assert (both_runs, both_lines) == (runs_snapshot, lines_snapshot)


def test_a_report_without_earlier_evidence_has_an_empty_auxiliary_field() -> None:
    runs, lines = _good([1, 2, 3, 4, 5, 6])
    report = _report(runs, lines)
    assert report.auxiliary.run_count == 0 and report.auxiliary.line_count == 0
    assert report.auxiliary.first_utc is None and report.auxiliary.last_utc is None
    assert "auxiliary" not in report.statement


def test_a_skipped_line_before_the_pin_is_auxiliary_evidence() -> None:
    runs, lines = _good([1, 2, 3, 4, 5, 6])
    report = _report(runs, [_skipped(_at(0, 5)), *lines])
    assert report.auxiliary.line_count == 1
    assert report.qualifying_from_pin is True
