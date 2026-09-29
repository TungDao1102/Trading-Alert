"""KILL_GATE_EVALUATION journal-event tests (Phase 10, plan 10-05, D-03, D-05).

RED first: authored before `build_kill_gate_event` / `record_kill_gate_evaluation`
exist. The event is journal-first (mirrors execution enablement), carries a content-hash
id, and its payload is an exact allow-listed, secret-free dict whose key set is constant.
"""

from __future__ import annotations

import json
from typing import Any

from src.analytics.killgate import (
    KILL_GATE_CORRELATION_ID,
    KILL_GATE_ENTITY_ID,
    KILL_GATE_ENTITY_TYPE,
    KILL_GATE_EVENT_TYPE,
    build_kill_gate_event,
    record_kill_gate_evaluation,
)

from tests.phase10_helpers import load_expected, load_input, parse_utc
from tests.test_kill_gate_state import evaluate_at, evaluate_case

PAYLOAD_KEYS = frozenset(
    {
        "rule_ref",
        "state",
        "evaluated_at_utc",
        "cycle_start_utc",
        "families_required",
        "months_required",
        "families_tested",
        "families_budget_met",
        "months_budget_met",
        "whole_months",
        "extra_days",
        "any_pass",
        "pass_count",
        "sticky",
        "reopened_by_decision_ref",
        "reopened_by_operator_id",
        "reopened_at_utc",
        "prior_terminal_count",
        "independent_family_ids",
        "non_independent_family_ids",
        "decision_refs",
        "evidence_digest",
        "clock",
        "families",
    }
)
CLOCK_KEYS = frozenset({"start_utc", "source", "freeze_commit", "commit_author_date"})
FAMILY_KEYS = frozenset(
    {
        "family_id",
        "status",
        "decision_ref",
        "sheet_sha256",
        "independent",
        "param_set_count",
        "experiment_count",
    }
)


class FakeJournal:
    """Append-only in-memory journal (matches the `JournalLike.record` surface)."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


def test_tracer_insufficient_edge_to_journal_event() -> None:
    verdict = evaluate_case("kill_insufficient_edge")
    event = build_kill_gate_event(verdict)
    expected = load_expected("kill_insufficient_edge")

    assert KILL_GATE_EVENT_TYPE == event.event_type == "KILL_GATE_EVALUATION"
    assert KILL_GATE_ENTITY_TYPE == event.entity_type == "KillGate"
    assert KILL_GATE_ENTITY_ID == event.entity_id == "KILL_GATE_D013"
    assert KILL_GATE_CORRELATION_ID == event.correlation_id == "analytics_kill_gate"
    assert event.occurred_at_utc == verdict.evaluated_at_utc
    assert event.journal_event_id.startswith("kill_gate_")
    assert event.journal_event_id == expected["journal_event_id"]

    payload = json.loads(event.payload_json)
    assert set(payload) == PAYLOAD_KEYS
    assert payload["state"] == "INSUFFICIENT_EDGE"
    assert payload["rule_ref"] == "D013/D030"
    assert payload["families_required"] == 3
    assert payload["months_required"] == 6
    assert payload["evidence_digest"] == verdict.evidence_digest
    assert set(payload["clock"]) == CLOCK_KEYS
    assert all(set(row) == FAMILY_KEYS for row in payload["families"])
    assert [row["family_id"] for row in payload["families"]] == [
        "breakout-retest",
        "range-mr",
        "trend-pullback",
    ]
    # Null-valued keys stay present so the key set is constant across states.
    assert payload["reopened_by_decision_ref"] is None
    assert payload["sticky"] is False
    assert payload["evaluated_at_utc"] == "2027-04-01T00:00:00+00:00"
    # Compact, sorted-key JSON.
    assert event.payload_json == json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_tracer_two_builds_give_identical_event_id_and_digest() -> None:
    first = build_kill_gate_event(evaluate_case("kill_insufficient_edge"))
    second = build_kill_gate_event(evaluate_case("kill_insufficient_edge"))
    assert first.journal_event_id == second.journal_event_id
    assert first.payload_json == second.payload_json
    assert (
        json.loads(first.payload_json)["evidence_digest"]
        == json.loads(second.payload_json)["evidence_digest"]
    )


def test_tracer_record_is_journal_first_single_write() -> None:
    journal = FakeJournal()
    verdict = evaluate_case("kill_insufficient_edge")
    returned = record_kill_gate_evaluation(verdict, journal=journal)
    assert journal.events == [returned]
    assert returned == build_kill_gate_event(verdict)
    replayed = record_kill_gate_evaluation(verdict, journal=journal)
    assert replayed.journal_event_id == returned.journal_event_id
    assert len(journal.events) == 2


def test_tracer_within_budget_event_key_set_is_constant() -> None:
    event = build_kill_gate_event(evaluate_case("kill_within_budget"))
    payload = json.loads(event.payload_json)
    assert set(payload) == PAYLOAD_KEYS
    assert payload["state"] == "WITHIN_BUDGET"
    assert payload["families_tested"] == 2
    assert payload["families_budget_met"] is False
    assert event.occurred_at_utc == parse_utc("2027-04-01T00:00:00+00:00")


# --------------------------------------------------------------------------- #
# Task 3: every fixture verdict yields a constant-key, secret-free, pinned event.
# --------------------------------------------------------------------------- #

ALL_CASES = (
    "kill_within_budget",
    "kill_passing_candidate",
    "kill_insufficient_edge",
    "kill_clock_boundary",
)
FORBIDDEN_SUBSTRINGS = ("key", "secret", "token", "signature")


def test_payload_is_secret_free_for_every_fixture_verdict() -> None:
    for case in ALL_CASES:
        event = build_kill_gate_event(evaluate_case(case))
        lowered = event.payload_json.lower()
        for forbidden in FORBIDDEN_SUBSTRINGS:
            assert forbidden not in lowered, (case, forbidden)
        assert set(json.loads(event.payload_json)) == PAYLOAD_KEYS, case
        for text_field in ("traceback", "exception", "error"):
            assert text_field not in lowered, (case, text_field)


def test_passing_candidate_event_pins_digests_and_carries_the_pass_reference() -> None:
    verdict = evaluate_case("kill_passing_candidate")
    event = build_kill_gate_event(verdict)
    expected = load_expected("kill_passing_candidate")
    payload = json.loads(event.payload_json)
    assert payload["state"] == "PASSING_CANDIDATE"
    assert payload["pass_count"] == 1
    assert "DEC-2026-11-pass-breakout-retest" in payload["decision_refs"]
    assert verdict.evidence_digest == expected["evidence_digest"]
    assert verdict.digest() == expected["verdict_digest"]
    assert event.journal_event_id == expected["journal_event_id"]


def test_boundary_events_are_distinct_and_pinned() -> None:
    expected = load_expected("kill_clock_boundary")
    data = load_input("kill_clock_boundary")
    before = build_kill_gate_event(
        evaluate_at("kill_clock_boundary", data["evaluated_at_utc_before"])
    )
    at = build_kill_gate_event(evaluate_case("kill_clock_boundary"))
    assert before.journal_event_id != at.journal_event_id
    assert before.journal_event_id == expected["before"]["journal_event_id"]
    assert at.journal_event_id == expected["at"]["journal_event_id"]
    assert json.loads(before.payload_json)["state"] == "WITHIN_BUDGET"
    assert json.loads(at.payload_json)["state"] == "INSUFFICIENT_EDGE"
    assert before.occurred_at_utc == parse_utc("2027-03-18T23:59:59+00:00")
    assert at.occurred_at_utc == parse_utc("2027-03-19T00:00:00+00:00")
