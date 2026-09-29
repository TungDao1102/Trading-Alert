"""Protocol-header clock-start parser tests (Phase 10, plan 10-07, D-03, T-10-23).

RED first: authored before `parse_frozen_on` / `clock_start_from_protocol` exist. The clock
start is parsed from the frozen protocol header with the exact regex the research-gate CI
uses (taken as 00:00Z of the Frozen-on date), and freeze-commit provenance rides along.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from src.analytics.clock import (
    FROZEN_ON_PATTERN,
    PROTOCOL_FREEZE_COMMIT,
    PROTOCOL_FREEZE_COMMIT_AUTHOR_DATE,
    ClockStart,
    clock_start_from_protocol,
    earliest_terminal_utc,
    parse_frozen_on,
)
from src.analytics.family import KillGateInputError

from tests.phase10_helpers import load_expected, load_input, parse_utc

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "research-gate.yml"
CASE = "clock_start_provenance"
DATE_TEXT = "[0-9]{4}-[0-9]{2}-[0-9]{2}"


def _ci_frozen_on_regex() -> str:
    """Extract the Frozen-on grep -E regex from the research-gate workflow."""
    for line in WORKFLOW_PATH.read_text(encoding="utf-8").splitlines():
        if "Frozen on" in line and "grep -E" in line:
            match = re.search(r'grep -E "(?P<regex>[^"]+)"', line)
            assert match is not None, line
            return match.group("regex")
    raise AssertionError("Frozen-on grep not found in research-gate.yml")


def test_frozen_on_pattern_is_the_research_gate_regex_with_a_date_capture_group() -> None:
    ci_regex = _ci_frozen_on_regex()
    assert DATE_TEXT in ci_regex
    assert FROZEN_ON_PATTERN.pattern == ci_regex.replace(DATE_TEXT, f"({DATE_TEXT})")
    assert FROZEN_ON_PATTERN.flags & re.MULTILINE
    assert FROZEN_ON_PATTERN.groups == 1


def test_frozen_on_pattern_and_ci_regex_match_the_same_header_line() -> None:
    header = "> **Frozen on:** 2026-09-19"
    assert re.search(_ci_frozen_on_regex(), header) is not None
    match = FROZEN_ON_PATTERN.search(header)
    assert match is not None
    assert match.group(1) == "2026-09-19"
    for non_header in ("Frozen on: 2026-09-19", "> **Frozen on:** soon", "> **Status:** FROZEN"):
        assert re.search(_ci_frozen_on_regex(), non_header) is None
        assert FROZEN_ON_PATTERN.search(non_header) is None


def test_parse_frozen_on_returns_midnight_utc_of_the_frozen_on_date() -> None:
    data = load_input(CASE)
    assert parse_frozen_on(data["protocol_header"]) == parse_utc("2026-09-19T00:00:00+00:00")


def test_parse_frozen_on_rejects_text_without_the_line() -> None:
    with pytest.raises(KillGateInputError):
        parse_frozen_on("# Research Protocol\n\n> **Status:** FROZEN\n")


def test_parse_frozen_on_rejects_an_impossible_date() -> None:
    with pytest.raises(KillGateInputError):
        parse_frozen_on("> **Frozen on:** 2026-02-30\n")


def test_clock_start_provenance_fixture_is_pinned() -> None:
    data = load_input(CASE)
    expected = load_expected(CASE)
    clock = clock_start_from_protocol(
        data["protocol_header"],
        freeze_commit=data["freeze_commit"],
        commit_author_date=data["commit_author_date"],
    )
    assert isinstance(clock, ClockStart)
    assert clock.start_utc == parse_utc(expected["start_utc"])
    assert clock.source == expected["source"]
    assert clock.freeze_commit == expected["freeze_commit"]
    assert clock.commit_author_date == expected["commit_author_date"]
    assert earliest_terminal_utc(clock.start_utc) == parse_utc(expected["earliest_terminal_utc"])
    assert clock.as_payload()["freeze_commit"] == expected["freeze_commit"]
    assert clock.digest() == expected["clock_digest"]


def test_freeze_commit_constants_hold_the_verified_provenance() -> None:
    assert PROTOCOL_FREEZE_COMMIT == "281ccd0894ea35717cc741788b6133cfb202af82"
    assert PROTOCOL_FREEZE_COMMIT_AUTHOR_DATE == "2026-09-19T14:08:12+07:00"
    clock = clock_start_from_protocol("> **Frozen on:** 2026-09-19\n")
    assert clock.freeze_commit == PROTOCOL_FREEZE_COMMIT
    assert clock.commit_author_date == PROTOCOL_FREEZE_COMMIT_AUTHOR_DATE


def test_real_protocol_file_gives_the_expected_clock_start() -> None:
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    clock = clock_start_from_protocol(text)
    assert clock.start_utc == parse_utc("2026-09-19T00:00:00+00:00")
    assert earliest_terminal_utc(clock.start_utc) == parse_utc("2027-03-19T00:00:00+00:00")
    assert clock.source == "docs/research/RESEARCH_PROTOCOL.md header: Frozen on"


def test_clock_start_matches_the_committed_fixture_clock() -> None:
    """The evaluator fixtures' hand-authored clock equals the parsed real clock."""
    fixture_clock = load_input("kill_insufficient_edge")["clock"]
    clock = clock_start_from_protocol(PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert clock.as_payload() == {
        "start_utc": parse_utc(fixture_clock["start_utc"]).isoformat(),
        "source": fixture_clock["source"],
        "freeze_commit": fixture_clock["freeze_commit"],
        "commit_author_date": fixture_clock["commit_author_date"],
    }
