"""Kill-gate state evaluator tests (Phase 10, plan 10-05, D-03, D013/D030).

RED first: these tests are authored before `src/analytics/{clock,family,killgate}.py`
exist. `evaluate` is a pure function of family facts + research clock + an injected
evaluated-at instant; it never reads a wall clock and never compares a metric to a
numeric threshold (a family's PASS/FAIL is a recorded human decision).

Fixtures: `tests/fixtures/phase10/kill_*/{input,expected}.json` (ISO datetimes with a
`+00:00` suffix, 64-hex hashes, hand-authored decision references).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from src.analytics.clock import (
    ClockStart,
    add_months,
    earliest_terminal_utc,
    extra_days_after,
    whole_months_between,
)
from src.analytics.family import FamilyEvidence, FamilyStatus, KillGateInputError
from src.analytics.killgate import KillGateVerdict, evaluate
from src.domain.enums import KillGateState

from tests.phase10_helpers import load_expected, load_input, parse_utc


def build_clock(raw: dict[str, Any]) -> ClockStart:
    return ClockStart(
        start_utc=parse_utc(raw["start_utc"]),
        source=raw["source"],
        freeze_commit=raw["freeze_commit"],
        commit_author_date=raw["commit_author_date"],
    )


def build_family(raw: dict[str, Any]) -> FamilyEvidence:
    decided = raw["decided_at_utc"]
    return FamilyEvidence(
        family_id=raw["family_id"],
        sheet_sha256=raw["sheet_sha256"],
        sheet_slots_present=tuple(raw["sheet_slots_present"]),
        candidate_param_set_hashes=tuple(raw["candidate_param_set_hashes"]),
        experiment_ids=tuple(raw["experiment_ids"]),
        status=FamilyStatus(raw["status"]),
        decision_ref=raw["decision_ref"],
        decided_at_utc=None if decided is None else parse_utc(decided),
        development_experiment_ids=tuple(raw["development_experiment_ids"]),
        validation_experiment_ids=tuple(raw["validation_experiment_ids"]),
    )


def load_case(case: str) -> tuple[ClockStart, list[FamilyEvidence], datetime]:
    data = load_input(case)
    return (
        build_clock(data["clock"]),
        [build_family(f) for f in data["families"]],
        parse_utc(data["evaluated_at_utc"]),
    )


def evaluate_case(case: str) -> KillGateVerdict:
    clock, families, evaluated_at = load_case(case)
    return evaluate(families=families, clock=clock, evaluated_at_utc=evaluated_at)


def test_tracer_insufficient_edge_state() -> None:
    verdict = evaluate_case("kill_insufficient_edge")
    expected = load_expected("kill_insufficient_edge")
    assert verdict.state is KillGateState.INSUFFICIENT_EDGE
    assert verdict.state.value == expected["state"]
    assert verdict.families_tested == expected["families_tested"] == 3
    assert verdict.families_budget_met is True
    assert verdict.months_budget_met is True
    assert verdict.any_pass is False
    assert verdict.pass_count == 0
    assert verdict.sticky is False
    assert verdict.whole_months == expected["whole_months"]
    assert verdict.extra_days == expected["extra_days"]
    assert verdict.months_elapsed == Decimal(expected["months_elapsed"])
    assert verdict.earliest_terminal_utc == parse_utc(expected["earliest_terminal_utc"])
    assert verdict.cycle_start_utc == parse_utc("2026-09-19T00:00:00+00:00")
    assert list(verdict.independent_family_ids) == expected["independent_family_ids"]
    assert list(verdict.non_independent_family_ids) == expected["non_independent_family_ids"]
    assert list(verdict.decision_refs) == expected["decision_refs"]
    assert verdict.rule_ref == "D013/D030"
    assert verdict.reopened_by_decision_ref is None
    assert verdict.reopened_by_operator_id is None
    assert verdict.reopened_at_utc is None
    assert verdict.prior_terminal_count == 0
    assert [row.family_id for row in verdict.families] == sorted(
        row.family_id for row in verdict.families
    )


def test_tracer_within_budget_state() -> None:
    verdict = evaluate_case("kill_within_budget")
    expected = load_expected("kill_within_budget")
    assert verdict.state is KillGateState.WITHIN_BUDGET
    assert verdict.state.value == expected["state"]
    assert verdict.families_tested == expected["families_tested"] == 2
    assert verdict.families_budget_met is False
    assert verdict.months_budget_met is True
    assert verdict.any_pass is False
    assert list(verdict.decision_refs) == expected["decision_refs"]


def test_tracer_earliest_terminal_is_six_calendar_months_after_freeze() -> None:
    clock, _, _ = load_case("kill_insufficient_edge")
    assert earliest_terminal_utc(clock.start_utc) == parse_utc("2027-03-19T00:00:00+00:00")


def test_tracer_identical_inputs_give_identical_digests() -> None:
    first = evaluate_case("kill_insufficient_edge")
    second = evaluate_case("kill_insufficient_edge")
    assert first == second
    assert first.evidence_digest == second.evidence_digest
    assert first.digest() == second.digest()
    expected = load_expected("kill_insufficient_edge")
    assert first.evidence_digest == expected["evidence_digest"]
    assert first.digest() == expected["verdict_digest"]


# --------------------------------------------------------------------------- #
# Task 3: exact boundary, PASSING_CANDIDATE, independence-driven counting, validation.
# --------------------------------------------------------------------------- #


def evaluate_at(case: str, evaluated_at_iso: str) -> KillGateVerdict:
    clock, families, _ = load_case(case)
    return evaluate(families=families, clock=clock, evaluated_at_utc=parse_utc(evaluated_at_iso))


def test_boundary_one_second_before_six_months_is_within_budget() -> None:
    expected = load_expected("kill_clock_boundary")["before"]
    data = load_input("kill_clock_boundary")
    verdict = evaluate_at("kill_clock_boundary", data["evaluated_at_utc_before"])
    assert verdict.evaluated_at_utc == parse_utc(expected["evaluated_at_utc"])
    assert verdict.state is KillGateState.WITHIN_BUDGET
    assert verdict.state.value == expected["state"]
    assert verdict.months_budget_met is False
    assert verdict.families_budget_met is True
    assert verdict.whole_months == expected["whole_months"]
    assert verdict.extra_days == expected["extra_days"]
    assert verdict.months_elapsed == Decimal(expected["months_elapsed"])


def test_boundary_exactly_six_months_is_eligible_and_inclusive() -> None:
    expected = load_expected("kill_clock_boundary")["at"]
    verdict = evaluate_case("kill_clock_boundary")
    assert verdict.evaluated_at_utc == parse_utc(expected["evaluated_at_utc"])
    assert verdict.state is KillGateState.INSUFFICIENT_EDGE
    assert verdict.state.value == expected["state"]
    assert verdict.months_budget_met is True
    assert verdict.whole_months == expected["whole_months"]
    assert verdict.extra_days == expected["extra_days"]
    assert verdict.months_elapsed == Decimal(expected["months_elapsed"])
    assert verdict.evaluated_at_utc == verdict.earliest_terminal_utc


def test_boundary_outcomes_are_pinned_by_digest() -> None:
    expected = load_expected("kill_clock_boundary")
    data = load_input("kill_clock_boundary")
    before = evaluate_at("kill_clock_boundary", data["evaluated_at_utc_before"])
    at = evaluate_case("kill_clock_boundary")
    assert before.digest() == expected["before"]["verdict_digest"]
    assert at.digest() == expected["at"]["verdict_digest"]
    assert before.digest() != at.digest()
    assert before.evidence_digest != at.evidence_digest


def test_add_months_clamps_to_last_day_of_target_month() -> None:
    assert add_months(parse_utc("2026-01-31T00:00:00+00:00"), 1) == parse_utc(
        "2026-02-28T00:00:00+00:00"
    )
    assert add_months(parse_utc("2024-01-31T00:00:00+00:00"), 1) == parse_utc(
        "2024-02-29T00:00:00+00:00"
    )
    assert add_months(parse_utc("2026-08-31T13:45:10+00:00"), 6) == parse_utc(
        "2027-02-28T13:45:10+00:00"
    )
    assert add_months(parse_utc("2026-12-15T00:00:00+00:00"), 2) == parse_utc(
        "2027-02-15T00:00:00+00:00"
    )


def test_whole_months_and_extra_days_arithmetic() -> None:
    start = parse_utc("2026-01-31T00:00:00+00:00")
    assert whole_months_between(start, parse_utc("2026-02-27T23:59:59+00:00")) == 0
    assert whole_months_between(start, parse_utc("2026-02-28T00:00:00+00:00")) == 1
    assert whole_months_between(start, parse_utc("2025-01-01T00:00:00+00:00")) == 0
    assert extra_days_after(start, parse_utc("2026-03-10T12:00:00+00:00"), 1) == 10
    assert extra_days_after(start, parse_utc("2025-01-01T00:00:00+00:00"), 0) == 0


def test_passing_candidate_records_evidence_without_authorizing_live() -> None:
    verdict = evaluate_case("kill_passing_candidate")
    expected = load_expected("kill_passing_candidate")
    assert verdict.state is KillGateState.PASSING_CANDIDATE
    assert verdict.state.value == expected["state"]
    assert verdict.any_pass is True
    assert verdict.pass_count == expected["pass_count"] == 1
    assert list(verdict.decision_refs) == expected["decision_refs"]
    assert "DEC-2026-11-pass-breakout-retest" in verdict.decision_refs
    assert verdict.families_budget_met is True
    assert verdict.months_budget_met is True
    # Nothing in the verdict can be read as a live authorization (D-03).
    field_names = {field.name for field in dataclasses.fields(verdict)}
    assert not any("live" in n or "enable" in n or "authoriz" in n for n in field_names)


def test_three_tested_before_six_months_is_within_budget() -> None:
    verdict = evaluate_at("kill_insufficient_edge", "2027-02-01T00:00:00+00:00")
    assert verdict.families_tested == 3
    assert verdict.families_budget_met is True
    assert verdict.months_budget_met is False
    assert verdict.state is KillGateState.WITHIN_BUDGET


def test_six_months_elapsed_with_only_two_tested_is_within_budget() -> None:
    verdict = evaluate_case("kill_within_budget")
    assert verdict.months_budget_met is True
    assert verdict.families_tested == 2
    assert verdict.state is KillGateState.WITHIN_BUDGET


def test_a_pass_before_the_months_budget_is_still_passing_candidate() -> None:
    verdict = evaluate_at("kill_passing_candidate", "2026-12-01T00:00:00+00:00")
    assert verdict.months_budget_met is False
    assert verdict.state is KillGateState.PASSING_CANDIDATE


def test_non_independent_tested_family_is_not_counted() -> None:
    clock, families, evaluated_at = load_case("kill_insufficient_edge")
    clone = dataclasses.replace(
        families[2], sheet_sha256=families[1].sheet_sha256
    )  # shares a sheet hash with an earlier family
    verdict = evaluate(
        families=[families[0], families[1], clone], clock=clock, evaluated_at_utc=evaluated_at
    )
    assert verdict.families_tested == 2
    assert verdict.state is KillGateState.WITHIN_BUDGET
    assert len(verdict.non_independent_family_ids) == 1


def test_decision_before_the_cycle_start_is_not_counted() -> None:
    clock, families, evaluated_at = load_case("kill_insufficient_edge")
    stale = dataclasses.replace(families[0], decided_at_utc=parse_utc("2026-09-18T00:00:00+00:00"))
    verdict = evaluate(
        families=[stale, families[1], families[2]], clock=clock, evaluated_at_utc=evaluated_at
    )
    assert verdict.families_tested == 2
    assert verdict.state is KillGateState.WITHIN_BUDGET


def test_input_order_does_not_change_the_verdict() -> None:
    clock, families, evaluated_at = load_case("kill_insufficient_edge")
    forward = evaluate(families=families, clock=clock, evaluated_at_utc=evaluated_at)
    backward = evaluate(
        families=list(reversed(families)), clock=clock, evaluated_at_utc=evaluated_at
    )
    assert forward == backward
    assert forward.digest() == backward.digest()


def test_duplicate_family_id_is_rejected() -> None:
    clock, families, evaluated_at = load_case("kill_insufficient_edge")
    with pytest.raises(KillGateInputError):
        evaluate(families=[families[0], families[0]], clock=clock, evaluated_at_utc=evaluated_at)


def test_naive_evaluated_at_is_rejected() -> None:
    clock, families, _ = load_case("kill_insufficient_edge")
    with pytest.raises(KillGateInputError):
        evaluate(families=families, clock=clock, evaluated_at_utc=datetime(2027, 4, 1))


def test_decided_after_evaluated_at_is_rejected() -> None:
    clock, families, _ = load_case("kill_insufficient_edge")
    with pytest.raises(KillGateInputError):
        evaluate(
            families=families,
            clock=clock,
            evaluated_at_utc=parse_utc("2026-11-14T23:59:59+00:00"),
        )
