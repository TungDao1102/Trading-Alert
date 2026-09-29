"""Pure D013/D030 kill-gate evaluator and its journal event (Phase 10, plan 10-05, D-03, D-05).

`evaluate` maps independently-specified family facts + the research clock + an INJECTED
evaluated-at instant to a `KillGateVerdict`:

- INSUFFICIENT_EDGE iff >= 3 independently specified families are TESTED under the frozen
  methodology AND >= 6 calendar months have elapsed since the research-clock start AND no
  counted family holds a recorded passing decision.
- PASSING_CANDIDATE iff some counted family holds a recorded passing decision. This only
  records that evidence exists; it never authorizes live trading.
- WITHIN_BUDGET otherwise.

The evaluator only reads. It never writes a reset, never calls the exchange, never touches
the live-enable flag, never reads a wall clock, and never compares a metric to a numeric
acceptance threshold (thresholds are TBD in the frozen protocol; a family's pass/fail is a
recorded human decision carrying a decision_ref).

The terminal outcome is recorded as an append-only KILL_GATE_EVALUATION JournalEvent with a
content-hash id (journal-first, mirroring execution enablement); identical inputs give an
identical event id and digest, and the payload is an allow-listed secret-free dict.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from src.analytics.clock import (
    REQUIRED_MONTHS,
    ClockStart,
    earliest_terminal_utc,
    extra_days_after,
    whole_months_between,
)
from src.analytics.family import (
    FamilyEvidence,
    FamilyStatus,
    KillGateInputError,
    independent_family_ids,
)
from src.domain.canonical import sha256_hex
from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent, content_hash_event_id

__all__ = [
    "KILL_GATE_CORRELATION_ID",
    "KILL_GATE_ENTITY_ID",
    "KILL_GATE_ENTITY_TYPE",
    "KILL_GATE_EVENT_TYPE",
    "QUESTION_APPROVED_EVENT_TYPE",
    "REQUIRED_FAMILIES",
    "FamilyRow",
    "JournalLike",
    "KillGateInputError",
    "KillGateVerdict",
    "PriorEvaluation",
    "ResetRecord",
    "build_kill_gate_event",
    "build_question_approved_event",
    "evaluate",
    "prior_from_event",
    "priors_from_events",
    "record_kill_gate_evaluation",
    "registration_allowed",
    "reset_from_event",
    "resets_from_events",
]

REQUIRED_FAMILIES = 3
RULE_REF = "D013/D030"
KILL_GATE_EVENT_TYPE = "KILL_GATE_EVALUATION"
KILL_GATE_ENTITY_TYPE = "KillGate"
KILL_GATE_ENTITY_ID = "KILL_GATE_D013"
KILL_GATE_CORRELATION_ID = "analytics_kill_gate"
QUESTION_APPROVED_EVENT_TYPE = "KILL_GATE_QUESTION_APPROVED"

_EVENT_ID_PREFIX = "kill_gate"
_RESET_EVENT_ID_PREFIX = "kill_gate_reset"
_DAYS_PER_MONTH = Decimal(30)
_MONTHS_QUANTUM = Decimal("0.0001")


class JournalLike(Protocol):
    """Anything that quacks like the project journal (structural, no concrete import)."""

    def record(self, event: Any) -> None: ...


@dataclass(frozen=True)
class FamilyRow:
    """One family's line in the verdict (payload-safe facts only)."""

    family_id: str
    status: str
    decision_ref: str | None
    sheet_sha256: str | None
    independent: bool
    counted: bool
    param_set_count: int
    experiment_count: int

    def as_payload(self) -> dict[str, Any]:
        """Allow-listed event fields (`counted` is evaluator-internal and not emitted)."""
        return {
            "family_id": self.family_id,
            "status": self.status,
            "decision_ref": self.decision_ref,
            "sheet_sha256": self.sheet_sha256,
            "independent": self.independent,
            "param_set_count": self.param_set_count,
            "experiment_count": self.experiment_count,
        }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


@dataclass(frozen=True)
class KillGateVerdict:
    """Deterministic outcome of one kill-gate evaluation.

    The sticky/reopen fields are part of the event contract from plan 05 so the one-way
    payload key set never changes; plan 07 fills them.
    """

    state: KillGateState
    evaluated_at_utc: datetime
    cycle_start_utc: datetime
    families_tested: int
    independent_family_ids: tuple[str, ...]
    non_independent_family_ids: tuple[str, ...]
    families_budget_met: bool
    months_budget_met: bool
    whole_months: int
    extra_days: int
    months_elapsed: Decimal  # whole_months + extra_days/30, display only
    any_pass: bool
    pass_count: int
    decision_refs: tuple[str, ...]
    earliest_terminal_utc: datetime
    clock: ClockStart
    evidence_digest: str
    families: tuple[FamilyRow, ...]
    sticky: bool = False
    reopened_by_decision_ref: str | None = None
    reopened_by_operator_id: str | None = None
    reopened_at_utc: datetime | None = None
    prior_terminal_count: int = 0
    rule_ref: str = RULE_REF

    def as_payload(self) -> dict[str, Any]:
        """The exact allow-listed event payload (constant key set; nulls stay present)."""
        return {
            "rule_ref": self.rule_ref,
            "state": self.state.value,
            "evaluated_at_utc": self.evaluated_at_utc.isoformat(),
            "cycle_start_utc": self.cycle_start_utc.isoformat(),
            "families_required": REQUIRED_FAMILIES,
            "months_required": REQUIRED_MONTHS,
            "families_tested": self.families_tested,
            "families_budget_met": self.families_budget_met,
            "months_budget_met": self.months_budget_met,
            "whole_months": self.whole_months,
            "extra_days": self.extra_days,
            "any_pass": self.any_pass,
            "pass_count": self.pass_count,
            "sticky": self.sticky,
            "reopened_by_decision_ref": self.reopened_by_decision_ref,
            "reopened_by_operator_id": self.reopened_by_operator_id,
            "reopened_at_utc": _iso(self.reopened_at_utc),
            "prior_terminal_count": self.prior_terminal_count,
            "independent_family_ids": list(self.independent_family_ids),
            "non_independent_family_ids": list(self.non_independent_family_ids),
            "decision_refs": list(self.decision_refs),
            "evidence_digest": self.evidence_digest,
            "clock": self.clock.as_payload(),
            "families": [row.as_payload() for row in self.families],
        }

    def digest(self) -> str:
        """SHA-256 over the payload plus the display-only fields (byte-stable)."""
        material = self.as_payload()
        material["months_elapsed"] = str(self.months_elapsed)
        material["earliest_terminal_utc"] = self.earliest_terminal_utc.isoformat()
        return sha256_hex(material)


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise KillGateInputError(f"{name} must be a UTC-aware datetime")


@dataclass(frozen=True)
class PriorEvaluation:
    """An earlier persisted KILL_GATE_EVALUATION outcome (state + when it was evaluated)."""

    state: KillGateState
    evaluated_at_utc: datetime


@dataclass(frozen=True)
class ResetRecord:
    """An explicit human KILL_GATE_QUESTION_APPROVED record (never created by the evaluator)."""

    operator_id: str
    decision_ref: str
    occurred_at_utc: datetime


def _event_sort_key(event: JournalEvent) -> tuple[datetime, str, str, str]:
    return (event.occurred_at_utc, event.event_type, event.entity_id, event.journal_event_id)


def _parse_payload(event: JournalEvent) -> dict[str, Any] | None:
    try:
        loaded = json.loads(event.payload_json)
    except (ValueError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _parse_utc_iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed


def prior_from_event(event: JournalEvent) -> PriorEvaluation | None:
    """Parse a KILL_GATE_EVALUATION event into a prior; None when it is anything else.

    Never raises: another event type, non-JSON, a missing/unknown state or a missing/naive
    evaluated-at all yield None (untrusted-shape input, T-10-21).
    """
    if event.event_type != KILL_GATE_EVENT_TYPE:
        return None
    payload = _parse_payload(event)
    if payload is None:
        return None
    raw_state = payload.get("state")
    evaluated_at = _parse_utc_iso(payload.get("evaluated_at_utc"))
    if not isinstance(raw_state, str) or evaluated_at is None:
        return None
    try:
        state = KillGateState(raw_state)
    except ValueError:
        return None
    return PriorEvaluation(state=state, evaluated_at_utc=evaluated_at)


def reset_from_event(event: JournalEvent) -> ResetRecord | None:
    """Parse a KILL_GATE_QUESTION_APPROVED event into a reset record; None otherwise.

    Never raises. Empty strings are passed through on purpose: the evaluator is the single
    place that ignores a reset with an empty operator_id or decision_ref.
    """
    if event.event_type != QUESTION_APPROVED_EVENT_TYPE:
        return None
    payload = _parse_payload(event)
    if payload is None:
        return None
    operator_id = payload.get("operator_id")
    decision_ref = payload.get("decision_ref")
    if not isinstance(operator_id, str) or not isinstance(decision_ref, str):
        return None
    return ResetRecord(
        operator_id=operator_id,
        decision_ref=decision_ref,
        occurred_at_utc=event.occurred_at_utc,
    )


def priors_from_events(events: Iterable[JournalEvent]) -> tuple[PriorEvaluation, ...]:
    """Parse events (sorted by occurred_at_utc, event_type, entity_id, id); drop non-priors."""
    parsed = (prior_from_event(event) for event in sorted(events, key=_event_sort_key))
    return tuple(prior for prior in parsed if prior is not None)


def resets_from_events(events: Iterable[JournalEvent]) -> tuple[ResetRecord, ...]:
    """Parse events (same ordering as `priors_from_events`); drop non-reset events."""
    parsed = (reset_from_event(event) for event in sorted(events, key=_event_sort_key))
    return tuple(reset for reset in parsed if reset is not None)


def build_question_approved_event(
    operator_id: str, decision_ref: str, occurred_at_utc: datetime
) -> JournalEvent:
    """Build the human reset event (builder for tests / future operator tooling, no I/O).

    This is NOT a write path of the evaluator: the evaluator never creates a reset (D-03).
    """
    if not isinstance(operator_id, str) or operator_id.strip() == "":
        raise KillGateInputError("operator_id must be a non-empty string")
    if not isinstance(decision_ref, str) or decision_ref.strip() == "":
        raise KillGateInputError("decision_ref must be a non-empty string")
    _require_utc(occurred_at_utc, "occurred_at_utc")
    payload_json = json.dumps(
        {"decision_ref": decision_ref, "operator_id": operator_id, "rule_ref": RULE_REF},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix=_RESET_EVENT_ID_PREFIX,
            event_type=QUESTION_APPROVED_EVENT_TYPE,
            entity_id=KILL_GATE_ENTITY_ID,
            occurred_at_utc=occurred_at_utc,
            payload_json=payload_json,
        ),
        occurred_at_utc=occurred_at_utc,
        event_type=QUESTION_APPROVED_EVENT_TYPE,
        entity_type=KILL_GATE_ENTITY_TYPE,
        entity_id=KILL_GATE_ENTITY_ID,
        correlation_id=KILL_GATE_CORRELATION_ID,
        payload_json=payload_json,
    )


def registration_allowed(state: KillGateState) -> bool:
    """False only for the terminal INSUFFICIENT_EDGE state (D-03: no new family registration).

    Pure predicate; the CI tripwire (tests/test_kill_gate_registration.py) enforces it against
    the committed decision record because CI cannot read the journal.
    """
    if not isinstance(state, KillGateState):
        raise TypeError("registration_allowed requires a KillGateState")
    return state is not KillGateState.INSUFFICIENT_EDGE


def _evidence_row(family: FamilyEvidence, *, independent: bool, counted: bool) -> dict[str, Any]:
    return {
        "family_id": family.family_id,
        "status": family.status.value,
        "decision_ref": family.decision_ref,
        "decided_at_utc": _iso(family.decided_at_utc),
        "sheet_sha256": family.sheet_sha256,
        "sheet_slots_present": sorted(family.sheet_slots_present),
        "candidate_param_set_hashes": sorted(family.candidate_param_set_hashes),
        "experiment_ids": sorted(family.experiment_ids),
        "development_experiment_ids": sorted(family.development_experiment_ids),
        "validation_experiment_ids": sorted(family.validation_experiment_ids),
        "independent": independent,
        "counted": counted,
    }


def evaluate(
    *,
    families: Iterable[FamilyEvidence],
    clock: ClockStart,
    evaluated_at_utc: datetime,
    prior_evaluations: Iterable[PriorEvaluation] = (),
    resets: Iterable[ResetRecord] = (),
) -> KillGateVerdict:
    """Evaluate D013/D030 from recorded facts; pure, deterministic, read-only.

    Sticky terminal (D-03): a prior evaluation that recorded INSUFFICIENT_EDGE stays the
    verdict regardless of new evidence until a separate explicit human reset event occurs
    after it. Only priors strictly earlier than `evaluated_at_utc` count, so replaying an
    evaluation at the same instant yields the same state, digest and event id. The
    evaluator only reads `prior_evaluations` and `resets`; it never writes or infers a reset.

    A reset is valid only with a non-empty operator_id and decision_ref, an occurrence not
    later than `evaluated_at_utc`, and an occurrence strictly after some prior terminal.

    FLAGGED PLANNER DECISION (needs user review): D013 does not specify what happens to the
    research budget after a reset. Here the cycle restarts: the cycle clock starts at the
    latest applicable reset time (never earlier than the protocol freeze), only family
    decisions dated on or after it count, and the reopening decision reference, operator and
    time are recorded in every later verdict.
    """
    _require_utc(evaluated_at_utc, "evaluated_at_utc")
    priors = tuple(prior_evaluations)
    reset_records = tuple(resets)
    for prior in priors:
        _require_utc(prior.evaluated_at_utc, "prior evaluated_at_utc")
    for reset in reset_records:
        _require_utc(reset.occurred_at_utc, "reset occurred_at_utc")
    qualifying_terminals = sorted(
        prior.evaluated_at_utc
        for prior in priors
        if prior.state is KillGateState.INSUFFICIENT_EDGE
        and prior.evaluated_at_utc < evaluated_at_utc
    )
    applicable_resets = sorted(
        (
            reset
            for reset in reset_records
            if reset.operator_id.strip() != ""
            and reset.decision_ref.strip() != ""
            and reset.occurred_at_utc <= evaluated_at_utc
            and any(terminal < reset.occurred_at_utc for terminal in qualifying_terminals)
        ),
        key=lambda reset: (reset.occurred_at_utc, reset.decision_ref, reset.operator_id),
    )
    last_terminal = qualifying_terminals[-1] if qualifying_terminals else None
    latest_reset = applicable_resets[-1] if applicable_resets else None
    sticky = last_terminal is not None and not any(
        reset.occurred_at_utc > last_terminal for reset in applicable_resets
    )
    ordered = sorted(families, key=lambda family: family.family_id)
    if len({family.family_id for family in ordered}) != len(ordered):
        raise KillGateInputError("family_id values must be unique")
    for family in ordered:
        if family.decided_at_utc is not None and family.decided_at_utc > evaluated_at_utc:
            raise KillGateInputError(
                f"decided_at_utc of family {family.family_id} is later than evaluated_at_utc"
            )

    cycle_start = clock.start_utc
    if latest_reset is not None and latest_reset.occurred_at_utc > cycle_start:
        cycle_start = latest_reset.occurred_at_utc
    independent, non_independent = independent_family_ids(ordered)
    independent_set = set(independent)

    def counts(family: FamilyEvidence) -> bool:
        return (
            family.family_id in independent_set
            and family.status is not FamilyStatus.NOT_TESTED
            and family.decided_at_utc is not None
            and family.decided_at_utc >= cycle_start
        )

    counted = [family for family in ordered if counts(family)]
    families_tested = len(counted)
    pass_count = sum(1 for family in counted if family.status is FamilyStatus.TESTED_PASS)
    any_pass = pass_count > 0
    families_budget_met = families_tested >= REQUIRED_FAMILIES
    earliest = earliest_terminal_utc(cycle_start)
    months_budget_met = evaluated_at_utc >= earliest
    whole_months = whole_months_between(cycle_start, evaluated_at_utc)
    extra_days = extra_days_after(cycle_start, evaluated_at_utc, whole_months)
    months_elapsed = (Decimal(whole_months) + Decimal(extra_days) / _DAYS_PER_MONTH).quantize(
        _MONTHS_QUANTUM
    )

    if sticky:
        state = KillGateState.INSUFFICIENT_EDGE
    elif any_pass:
        state = KillGateState.PASSING_CANDIDATE
    elif families_budget_met and months_budget_met:
        state = KillGateState.INSUFFICIENT_EDGE
    else:
        state = KillGateState.WITHIN_BUDGET

    counted_ids = {family.family_id for family in counted}
    evidence_material: dict[str, Any] = {
        "families": [
            _evidence_row(
                family,
                independent=family.family_id in independent_set,
                counted=family.family_id in counted_ids,
            )
            for family in ordered
        ],
        "clock": clock.as_payload(),
        "cycle_start_utc": cycle_start.isoformat(),
        "evaluated_at_utc": evaluated_at_utc.isoformat(),
    }
    # Sticky inputs join the evidence digest only when present, so evaluations without
    # priors/resets keep the byte-identical plan-05 digests.
    if qualifying_terminals:
        evidence_material["prior_terminals_utc"] = [t.isoformat() for t in qualifying_terminals]
    if applicable_resets:
        evidence_material["applicable_resets"] = [
            {
                "operator_id": reset.operator_id,
                "decision_ref": reset.decision_ref,
                "occurred_at_utc": reset.occurred_at_utc.isoformat(),
            }
            for reset in applicable_resets
        ]
    evidence_digest = sha256_hex(evidence_material)
    rows = tuple(
        FamilyRow(
            family_id=family.family_id,
            status=family.status.value,
            decision_ref=family.decision_ref,
            sheet_sha256=family.sheet_sha256,
            independent=family.family_id in independent_set,
            counted=family.family_id in counted_ids,
            param_set_count=len(set(family.candidate_param_set_hashes)),
            experiment_count=len(set(family.experiment_ids)),
        )
        for family in ordered
    )
    decision_refs = tuple(
        sorted({family.decision_ref for family in counted if family.decision_ref is not None})
    )
    return KillGateVerdict(
        state=state,
        evaluated_at_utc=evaluated_at_utc,
        cycle_start_utc=cycle_start,
        families_tested=families_tested,
        independent_family_ids=independent,
        non_independent_family_ids=non_independent,
        families_budget_met=families_budget_met,
        months_budget_met=months_budget_met,
        whole_months=whole_months,
        extra_days=extra_days,
        months_elapsed=months_elapsed,
        any_pass=any_pass,
        pass_count=pass_count,
        decision_refs=decision_refs,
        earliest_terminal_utc=earliest,
        clock=clock,
        evidence_digest=evidence_digest,
        families=rows,
        sticky=sticky,
        reopened_by_decision_ref=None if latest_reset is None else latest_reset.decision_ref,
        reopened_by_operator_id=None if latest_reset is None else latest_reset.operator_id,
        reopened_at_utc=None if latest_reset is None else latest_reset.occurred_at_utc,
        prior_terminal_count=len(qualifying_terminals),
    )


def build_kill_gate_event(verdict: KillGateVerdict) -> JournalEvent:
    """Build the KILL_GATE_EVALUATION JournalEvent (content-hash id; no I/O)."""
    payload_json = json.dumps(
        verdict.as_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix=_EVENT_ID_PREFIX,
            event_type=KILL_GATE_EVENT_TYPE,
            entity_id=KILL_GATE_ENTITY_ID,
            occurred_at_utc=verdict.evaluated_at_utc,
            payload_json=payload_json,
        ),
        occurred_at_utc=verdict.evaluated_at_utc,
        event_type=KILL_GATE_EVENT_TYPE,
        entity_type=KILL_GATE_ENTITY_TYPE,
        entity_id=KILL_GATE_ENTITY_ID,
        correlation_id=KILL_GATE_CORRELATION_ID,
        payload_json=payload_json,
    )


def record_kill_gate_evaluation(verdict: KillGateVerdict, *, journal: JournalLike) -> JournalEvent:
    """Journal-first: build the event, write it exactly once, return it."""
    event = build_kill_gate_event(verdict)
    journal.record(event)
    return event
