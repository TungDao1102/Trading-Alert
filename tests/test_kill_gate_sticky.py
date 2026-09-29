"""Sticky INSUFFICIENT_EDGE, human reset and replay-idempotence tests (Phase 10, plan 10-07, D-03).

RED first: authored before the sticky/reset extension of `src/analytics/killgate.py`.
The terminal outcome never auto-clears: only a separate explicit
KILL_GATE_QUESTION_APPROVED human event (non-empty operator_id and decision_ref) that occurs
after the latest prior terminal evaluation reopens research. The evaluator only reads it.

Fixtures: `tests/fixtures/phase10/{kill_sticky_reset,idempotent_replay}/`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest
from src.analytics.family import FamilyEvidence, KillGateInputError
from src.analytics.killgate import (
    QUESTION_APPROVED_EVENT_TYPE,
    KillGateVerdict,
    PriorEvaluation,
    ResetRecord,
    build_kill_gate_event,
    build_question_approved_event,
    evaluate,
    prior_from_event,
    reset_from_event,
)
from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent

from tests.phase10_helpers import load_expected, load_input, parse_utc
from tests.test_kill_gate_event import PAYLOAD_KEYS
from tests.test_kill_gate_state import build_clock, build_family, load_case

STICKY_CASE = "kill_sticky_reset"
REPLAY_CASE = "idempotent_replay"


def _sticky_inputs() -> tuple[Any, dict[str, FamilyEvidence], dict[str, Any]]:
    data = load_input(STICKY_CASE)
    families = {raw["family_id"]: build_family(raw) for raw in data["families"]}
    return build_clock(data["clock"]), families, data


def _reset_event(raw: dict[str, str]) -> JournalEvent:
    return build_question_approved_event(
        raw["operator_id"], raw["decision_ref"], parse_utc(raw["occurred_at_utc"])
    )


def _run_sequence() -> list[tuple[KillGateVerdict, JournalEvent]]:
    """Replay the three-step fixture, feeding each persisted event back as a prior."""
    clock, families, data = _sticky_inputs()
    priors: list[PriorEvaluation] = []
    resets: list[ResetRecord] = []
    outcomes: list[tuple[KillGateVerdict, JournalEvent]] = []
    for step in data["steps"]:
        if step["reset"] is not None:
            parsed_reset = reset_from_event(_reset_event(step["reset"]))
            assert parsed_reset is not None
            resets.append(parsed_reset)
        verdict = evaluate(
            families=[families[fid] for fid in step["family_ids"]],
            clock=clock,
            evaluated_at_utc=parse_utc(step["evaluated_at_utc"]),
            prior_evaluations=tuple(priors),
            resets=tuple(resets),
        )
        event = build_kill_gate_event(verdict)
        parsed_prior = prior_from_event(event)
        assert parsed_prior is not None
        priors.append(parsed_prior)
        outcomes.append((verdict, event))
    return outcomes


def test_tracer_sticky_sequence_terminal_then_sticky_then_reopened() -> None:
    expected_steps = load_expected(STICKY_CASE)["steps"]
    outcomes = _run_sequence()
    assert len(outcomes) == len(expected_steps) == 3
    for (verdict, event), expected in zip(outcomes, expected_steps, strict=True):
        label = expected["name"]
        assert verdict.state.value == expected["state"], label
        assert verdict.sticky is expected["sticky"], label
        assert verdict.prior_terminal_count == expected["prior_terminal_count"], label
        assert verdict.families_tested == expected["families_tested"], label
        assert verdict.any_pass is expected["any_pass"], label
        assert verdict.cycle_start_utc == parse_utc(expected["cycle_start_utc"]), label
        assert verdict.earliest_terminal_utc == parse_utc(expected["earliest_terminal_utc"]), label
        assert verdict.reopened_by_decision_ref == expected["reopened_by_decision_ref"], label
        assert verdict.reopened_by_operator_id == expected["reopened_by_operator_id"], label
        reopened_at = expected["reopened_at_utc"]
        assert verdict.reopened_at_utc == (None if reopened_at is None else parse_utc(reopened_at))
        assert set(json.loads(event.payload_json)) == PAYLOAD_KEYS, label


def test_tracer_new_evidence_never_clears_the_terminal_outcome() -> None:
    _, sticky_event = _run_sequence()[1]
    verdict = _run_sequence()[1][0]
    assert verdict.state is KillGateState.INSUFFICIENT_EDGE
    assert verdict.sticky is True
    assert verdict.any_pass is True  # the passing family is reported but never clears
    assert json.loads(sticky_event.payload_json)["sticky"] is True


def test_tracer_reset_restarts_the_research_budget_at_the_reset_time() -> None:
    verdict = _run_sequence()[2][0]
    assert verdict.state is KillGateState.WITHIN_BUDGET
    assert verdict.cycle_start_utc == parse_utc("2027-06-01T00:00:00+00:00")
    assert verdict.families_tested == 0
    assert verdict.months_budget_met is False
    assert verdict.reopened_by_decision_ref == "DEC-2027-06-new-question"
    assert verdict.reopened_by_operator_id == "operator_alpha"


def test_sticky_sequence_digests_are_pinned() -> None:
    expected_steps = load_expected(STICKY_CASE)["steps"]
    for (verdict, event), expected in zip(_run_sequence(), expected_steps, strict=True):
        assert verdict.digest() == expected["verdict_digest"], expected["name"]
        assert verdict.evidence_digest == expected["evidence_digest"], expected["name"]
        assert event.journal_event_id == expected["journal_event_id"], expected["name"]


def test_sticky_ignored_reset_cases_stay_sticky() -> None:
    clock, families, data = _sticky_inputs()
    base = [families[fid] for fid in ("trend-pullback", "breakout-retest", "range-mr")]
    terminal = evaluate(
        families=base, clock=clock, evaluated_at_utc=parse_utc("2027-04-01T00:00:00+00:00")
    )
    prior = prior_from_event(build_kill_gate_event(terminal))
    assert prior is not None
    assert len(data["ignored_reset_cases"]) == 4
    for case in data["ignored_reset_cases"]:
        parsed = reset_from_event(_reset_event_unchecked(case["reset"]))
        assert parsed is not None, case["name"]
        verdict = evaluate(
            families=base,
            clock=clock,
            evaluated_at_utc=parse_utc(case["evaluated_at_utc"]),
            prior_evaluations=(prior,),
            resets=(parsed,),
        )
        assert verdict.state is KillGateState.INSUFFICIENT_EDGE, case["name"]
        assert verdict.sticky is True, case["name"]
        assert verdict.reopened_by_decision_ref is None, case["name"]
        assert verdict.reopened_by_operator_id is None, case["name"]
        assert verdict.cycle_start_utc == clock.start_utc, case["name"]


def _reset_event_unchecked(raw: dict[str, str]) -> JournalEvent:
    """Hand-build a reset event (bypasses the builder's empty-field rejection)."""
    payload = {
        "decision_ref": raw["decision_ref"],
        "operator_id": raw["operator_id"],
        "rule_ref": "D013/D030",
    }
    return JournalEvent(
        journal_event_id="kill_gate_reset_hand_built_" + raw["decision_ref"],
        occurred_at_utc=parse_utc(raw["occurred_at_utc"]),
        event_type=QUESTION_APPROVED_EVENT_TYPE,
        entity_type="KillGate",
        entity_id="KILL_GATE_D013",
        correlation_id="analytics_kill_gate",
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


def test_sticky_prior_at_the_same_instant_is_ignored() -> None:
    clock, families, _ = _sticky_inputs()
    base = [families[fid] for fid in ("trend-pullback", "breakout-retest", "range-mr")]
    instant = parse_utc("2027-04-01T00:00:00+00:00")
    fresh = evaluate(families=base, clock=clock, evaluated_at_utc=instant)
    own_event_prior = prior_from_event(build_kill_gate_event(fresh))
    assert own_event_prior is not None
    replayed = evaluate(
        families=base,
        clock=clock,
        evaluated_at_utc=instant,
        prior_evaluations=(own_event_prior,),
    )
    assert replayed.sticky is False
    assert replayed.prior_terminal_count == 0
    assert replayed == fresh


def test_sticky_reset_needs_a_terminal_strictly_before_it() -> None:
    clock, families, _ = _sticky_inputs()
    base = [families[fid] for fid in ("trend-pullback", "breakout-retest", "range-mr")]
    prior = PriorEvaluation(
        state=KillGateState.INSUFFICIENT_EDGE,
        evaluated_at_utc=parse_utc("2027-04-01T00:00:00+00:00"),
    )
    same_instant_reset = ResetRecord(
        operator_id="operator_alpha",
        decision_ref="DEC-2027-04-same-instant",
        occurred_at_utc=parse_utc("2027-04-01T00:00:00+00:00"),
    )
    verdict = evaluate(
        families=base,
        clock=clock,
        evaluated_at_utc=parse_utc("2027-05-01T00:00:00+00:00"),
        prior_evaluations=(prior,),
        resets=(same_instant_reset,),
    )
    assert verdict.sticky is True


def test_sticky_reset_before_a_later_terminal_does_not_clear_that_terminal() -> None:
    clock, families, _ = _sticky_inputs()
    base = [families[fid] for fid in ("trend-pullback", "breakout-retest", "range-mr")]
    first = PriorEvaluation(
        state=KillGateState.INSUFFICIENT_EDGE,
        evaluated_at_utc=parse_utc("2027-04-01T00:00:00+00:00"),
    )
    second = PriorEvaluation(
        state=KillGateState.INSUFFICIENT_EDGE,
        evaluated_at_utc=parse_utc("2027-08-01T00:00:00+00:00"),
    )
    old_reset = ResetRecord(
        operator_id="operator_alpha",
        decision_ref="DEC-2027-06-old",
        occurred_at_utc=parse_utc("2027-06-01T00:00:00+00:00"),
    )
    verdict = evaluate(
        families=base,
        clock=clock,
        evaluated_at_utc=parse_utc("2027-09-01T00:00:00+00:00"),
        prior_evaluations=(first, second),
        resets=(old_reset,),
    )
    assert verdict.sticky is True
    assert verdict.state is KillGateState.INSUFFICIENT_EDGE
    assert verdict.prior_terminal_count == 2


def test_replay_identical_inputs_give_identical_digest_and_event_id() -> None:
    clock, families, evaluated_at = load_case("kill_insufficient_edge")
    first = evaluate(families=families, clock=clock, evaluated_at_utc=evaluated_at)
    second = evaluate(families=families, clock=clock, evaluated_at_utc=evaluated_at)
    assert first.digest() == second.digest()
    assert build_kill_gate_event(first).journal_event_id == (
        build_kill_gate_event(second).journal_event_id
    )
    expected = load_expected(REPLAY_CASE)
    replay_input = load_input(REPLAY_CASE)
    assert replay_input["source_case"] == "kill_insufficient_edge"
    assert parse_utc(replay_input["evaluated_at_utc"]) == evaluated_at
    assert first.state.value == expected["state"]
    assert first.sticky is expected["sticky"]
    assert first.prior_terminal_count == expected["prior_terminal_count"]
    assert first.digest() == expected["verdict_digest"]
    assert build_kill_gate_event(first).journal_event_id == expected["journal_event_id"]


def test_replay_own_persisted_event_at_the_same_instant_gives_the_same_event_id() -> None:
    clock, families, evaluated_at = load_case("kill_insufficient_edge")
    first = evaluate(families=families, clock=clock, evaluated_at_utc=evaluated_at)
    first_event = build_kill_gate_event(first)
    persisted_prior = prior_from_event(first_event)
    assert persisted_prior is not None
    again = evaluate(
        families=families,
        clock=clock,
        evaluated_at_utc=evaluated_at,
        prior_evaluations=(persisted_prior,),
    )
    again_event = build_kill_gate_event(again)
    assert again_event.journal_event_id == first_event.journal_event_id
    assert again_event.payload_json == first_event.payload_json
    assert again.digest() == first.digest()
    assert again.evidence_digest == first.evidence_digest


def test_replay_prior_and_reset_order_does_not_change_the_result() -> None:
    clock, families, _ = _sticky_inputs()
    base = [families[fid] for fid in ("trend-pullback", "breakout-retest", "range-mr")]
    early = PriorEvaluation(
        state=KillGateState.INSUFFICIENT_EDGE,
        evaluated_at_utc=parse_utc("2027-04-01T00:00:00+00:00"),
    )
    late = PriorEvaluation(
        state=KillGateState.INSUFFICIENT_EDGE,
        evaluated_at_utc=parse_utc("2027-05-01T00:00:00+00:00"),
    )
    reset_a = ResetRecord("op_a", "DEC-a", parse_utc("2027-06-01T00:00:00+00:00"))
    reset_b = ResetRecord("op_b", "DEC-b", parse_utc("2027-06-03T00:00:00+00:00"))
    when = parse_utc("2027-06-10T00:00:00+00:00")
    forward = evaluate(
        families=base,
        clock=clock,
        evaluated_at_utc=when,
        prior_evaluations=(early, late),
        resets=(reset_a, reset_b),
    )
    backward = evaluate(
        families=base,
        clock=clock,
        evaluated_at_utc=when,
        prior_evaluations=(late, early),
        resets=(reset_b, reset_a),
    )
    assert forward == backward
    assert forward.digest() == backward.digest()
    assert forward.reopened_by_decision_ref == "DEC-b"
    assert forward.cycle_start_utc == parse_utc("2027-06-03T00:00:00+00:00")


def test_prior_from_event_parses_only_kill_gate_evaluations() -> None:
    clock, families, evaluated_at = load_case("kill_insufficient_edge")
    event = build_kill_gate_event(
        evaluate(families=families, clock=clock, evaluated_at_utc=evaluated_at)
    )
    prior = prior_from_event(event)
    assert prior == PriorEvaluation(
        state=KillGateState.INSUFFICIENT_EDGE, evaluated_at_utc=evaluated_at
    )
    reset_event = build_question_approved_event(
        "operator_alpha", "DEC-x", parse_utc("2027-06-01T00:00:00+00:00")
    )
    assert prior_from_event(reset_event) is None
    assert reset_from_event(event) is None


def _event_with(payload_json: str, event_type: str = "KILL_GATE_EVALUATION") -> JournalEvent:
    return JournalEvent(
        journal_event_id="evt-1",
        occurred_at_utc=parse_utc("2027-04-01T00:00:00+00:00"),
        event_type=event_type,
        entity_type="KillGate",
        entity_id="KILL_GATE_D013",
        correlation_id="analytics_kill_gate",
        payload_json=payload_json,
    )


@pytest.mark.parametrize(
    "payload_json",
    [
        "",
        "[]",
        "{}",
        '{"state": "NOPE", "evaluated_at_utc": "2027-04-01T00:00:00+00:00"}',
        '{"state": "INSUFFICIENT_EDGE"}',
        '{"state": "INSUFFICIENT_EDGE", "evaluated_at_utc": "garbage"}',
        '{"state": "INSUFFICIENT_EDGE", "evaluated_at_utc": "2027-04-01T00:00:00"}',
        '{"state": 7, "evaluated_at_utc": "2027-04-01T00:00:00+00:00"}',
        '{"state": "INSUFFICIENT_EDGE", "evaluated_at_utc": 5}',
    ],
)
def test_prior_from_event_returns_none_for_malformed_payloads(payload_json: str) -> None:
    assert prior_from_event(_event_with(payload_json)) is None


@pytest.mark.parametrize(
    "payload_json",
    ["", "[]", "{}", '{"operator_id": 3, "decision_ref": "d"}', '{"operator_id": "o"}'],
)
def test_reset_from_event_returns_none_for_malformed_payloads(payload_json: str) -> None:
    assert reset_from_event(_event_with(payload_json, QUESTION_APPROVED_EVENT_TYPE)) is None


def test_build_question_approved_event_shape() -> None:
    occurred = parse_utc("2027-06-01T00:00:00+00:00")
    event = build_question_approved_event("operator_alpha", "DEC-2027-06-new-question", occurred)
    assert event.event_type == QUESTION_APPROVED_EVENT_TYPE == "KILL_GATE_QUESTION_APPROVED"
    assert event.entity_type == "KillGate"
    assert event.entity_id == "KILL_GATE_D013"
    assert event.correlation_id == "analytics_kill_gate"
    assert event.occurred_at_utc == occurred
    assert event.journal_event_id.startswith("kill_gate_reset_")
    assert json.loads(event.payload_json) == {
        "decision_ref": "DEC-2027-06-new-question",
        "operator_id": "operator_alpha",
        "rule_ref": "D013/D030",
    }
    assert event.payload_json == json.dumps(
        json.loads(event.payload_json), sort_keys=True, separators=(",", ":")
    )
    twin = build_question_approved_event("operator_alpha", "DEC-2027-06-new-question", occurred)
    assert twin.journal_event_id == event.journal_event_id
    parsed = reset_from_event(event)
    assert parsed == ResetRecord(
        operator_id="operator_alpha",
        decision_ref="DEC-2027-06-new-question",
        occurred_at_utc=occurred,
    )


@pytest.mark.parametrize(("operator_id", "decision_ref"), [("", "DEC-1"), ("op", ""), (" ", "d")])
def test_build_question_approved_event_rejects_empty_fields(
    operator_id: str, decision_ref: str
) -> None:
    with pytest.raises(KillGateInputError):
        build_question_approved_event(
            operator_id, decision_ref, parse_utc("2027-06-01T00:00:00+00:00")
        )


def test_build_question_approved_event_rejects_naive_time() -> None:
    with pytest.raises(KillGateInputError):
        build_question_approved_event("op", "DEC-1", datetime(2027, 6, 1))


def test_evaluate_rejects_naive_prior_or_reset_times() -> None:
    clock, families, evaluated_at = load_case("kill_insufficient_edge")
    with pytest.raises(KillGateInputError):
        evaluate(
            families=families,
            clock=clock,
            evaluated_at_utc=evaluated_at,
            prior_evaluations=(
                PriorEvaluation(
                    state=KillGateState.INSUFFICIENT_EDGE, evaluated_at_utc=datetime(2027, 1, 1)
                ),
            ),
        )
    with pytest.raises(KillGateInputError):
        evaluate(
            families=families,
            clock=clock,
            evaluated_at_utc=evaluated_at,
            resets=(ResetRecord("op", "DEC-1", datetime(2027, 1, 1)),),
        )


def test_sticky_payload_key_set_matches_the_plan_05_allow_list() -> None:
    for verdict, event in _run_sequence():
        assert set(json.loads(event.payload_json)) == PAYLOAD_KEYS
        assert set(verdict.as_payload()) == PAYLOAD_KEYS
