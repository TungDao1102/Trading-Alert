"""Kill-gate state evaluator tests (Phase 10, plan 10-05, D-03, D013/D030).

RED first: these tests are authored before `src/analytics/{clock,family,killgate}.py`
exist. `evaluate` is a pure function of family facts + research clock + an injected
evaluated-at instant; it never reads a wall clock and never compares a metric to a
numeric threshold (a family's PASS/FAIL is a recorded human decision).

Fixtures: `tests/fixtures/phase10/kill_*/{input,expected}.json` (ISO datetimes with a
`+00:00` suffix, 64-hex hashes, hand-authored decision references).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from src.analytics.clock import ClockStart, earliest_terminal_utc
from src.analytics.family import FamilyEvidence, FamilyStatus
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
