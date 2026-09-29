"""Acceptance-gate cell derivation tests (Phase 10, plan 10-07, D-03, RESEARCH P3).

RED first: authored before `src/analytics/gates.py` exists. Cells use only MET / NOT_MET /
PENDING_THRESHOLD_TBD / NOT_EVALUATED; judgement gates are always PENDING_THRESHOLD_TBD and
no cell is ever a pass by inference.
"""

from __future__ import annotations

import itertools

import pytest
from src.analytics.family import KillGateInputError
from src.analytics.gates import (
    GATE_IDS,
    GATE_LABELS,
    FamilyGateFacts,
    GateCell,
    derive_gate_cells,
    gate_cells_digest,
)
from src.analytics.killgate import registration_allowed
from src.domain.enums import KillGateState

JUDGEMENT_GATES = ("G04", "G05", "G06", "G09")
NEVER_MET_GATES = ("G01", "G02", "G04", "G05", "G06", "G09")


def _facts(
    *,
    cost: bool = False,
    repro: bool | None = None,
    uncertainty: bool = False,
    baseline: bool = False,
    tested: bool = False,
) -> FamilyGateFacts:
    return FamilyGateFacts(
        cost_model_hash_present=cost,
        reproducibility_verified=repro,
        uncertainty_report_present=uncertainty,
        baseline_compared=baseline,
        tested=tested,
    )


def test_gate_ids_and_labels_match_the_ui_spec_legend() -> None:
    assert GATE_IDS == ("G01", "G02", "G03", "G04", "G05", "G06", "G07", "G08", "G09", "G10")
    assert GATE_LABELS == {
        "G01": "Deterministic rules",
        "G02": "No material look-ahead",
        "G03": "Costs modeled",
        "G04": "Not single-symbol/session",
        "G05": "OOS consistent",
        "G06": "Tolerable drawdown",
        "G07": "Reproducible",
        "G08": "Interval uncertainty",
        "G09": "No single-point dependence",
        "G10": "Baseline-compared",
    }


def test_gate_cell_vocabulary_is_closed() -> None:
    assert {cell.value for cell in GateCell} == {
        "MET",
        "NOT_MET",
        "PENDING_THRESHOLD_TBD",
        "NOT_EVALUATED",
    }


def test_untested_family_with_no_facts_is_all_not_evaluated_or_pending() -> None:
    cells = derive_gate_cells(_facts())
    assert [gate_id for gate_id, _ in cells] == list(GATE_IDS)
    by_id = dict(cells)
    for gate_id in JUDGEMENT_GATES:
        assert by_id[gate_id] is GateCell.PENDING_THRESHOLD_TBD
    for gate_id in ("G01", "G02", "G03", "G07", "G08", "G10"):
        assert by_id[gate_id] is GateCell.NOT_EVALUATED


def test_tested_family_without_evidence_is_not_met_on_machine_derivable_gates() -> None:
    by_id = dict(derive_gate_cells(_facts(repro=False, tested=True)))
    for gate_id in ("G03", "G07", "G08", "G10"):
        assert by_id[gate_id] is GateCell.NOT_MET, gate_id
    assert by_id["G01"] is GateCell.NOT_EVALUATED
    assert by_id["G02"] is GateCell.NOT_EVALUATED


def test_machine_derivable_gates_are_met_when_their_evidence_is_present() -> None:
    by_id = dict(derive_gate_cells(_facts(cost=True, repro=True, uncertainty=True, baseline=True)))
    for gate_id in ("G03", "G07", "G08", "G10"):
        assert by_id[gate_id] is GateCell.MET, gate_id


def test_reproducibility_false_is_not_met_only_when_tested() -> None:
    assert dict(derive_gate_cells(_facts(repro=False, tested=True)))["G07"] is GateCell.NOT_MET
    assert (
        dict(derive_gate_cells(_facts(repro=False, tested=False)))["G07"] is GateCell.NOT_EVALUATED
    )
    assert dict(derive_gate_cells(_facts(repro=None, tested=True)))["G07"] is GateCell.NOT_EVALUATED


def test_exhaustive_combinations_never_yield_met_for_judgement_or_unverifiable_gates() -> None:
    combos = 0
    for cost, repro, uncertainty, baseline, tested in itertools.product(
        (True, False), (True, False, None), (True, False), (True, False), (True, False)
    ):
        combos += 1
        cells = derive_gate_cells(
            _facts(
                cost=cost, repro=repro, uncertainty=uncertainty, baseline=baseline, tested=tested
            )
        )
        by_id = dict(cells)
        assert len(cells) == 10
        assert all(isinstance(cell, GateCell) for _, cell in cells)
        for gate_id in NEVER_MET_GATES:
            assert by_id[gate_id] is not GateCell.MET, (gate_id, cost, repro, tested)
        for gate_id in JUDGEMENT_GATES:
            assert by_id[gate_id] is GateCell.PENDING_THRESHOLD_TBD
        for gate_id in ("G01", "G02"):
            assert by_id[gate_id] is GateCell.NOT_EVALUATED
    assert combos == 48


def test_derive_gate_cells_is_deterministic_and_digestible() -> None:
    facts = _facts(cost=True, repro=True, tested=True)
    first = derive_gate_cells(facts)
    second = derive_gate_cells(facts)
    assert first == second
    assert gate_cells_digest(first) == gate_cells_digest(second)
    assert gate_cells_digest(first) != gate_cells_digest(derive_gate_cells(_facts()))


def test_family_gate_facts_rejects_non_bool_fields() -> None:
    with pytest.raises(KillGateInputError):
        FamilyGateFacts(
            cost_model_hash_present="yes",  # type: ignore[arg-type]
            reproducibility_verified=None,
            uncertainty_report_present=False,
            baseline_compared=False,
            tested=False,
        )


def test_registration_allowed_is_false_only_for_insufficient_edge() -> None:
    assert registration_allowed(KillGateState.INSUFFICIENT_EDGE) is False
    assert registration_allowed(KillGateState.WITHIN_BUDGET) is True
    assert registration_allowed(KillGateState.PASSING_CANDIDATE) is True


@pytest.mark.parametrize("bad", ["INSUFFICIENT_EDGE", None, 1, "WITHIN_BUDGET"])
def test_registration_allowed_rejects_non_state_arguments(bad: object) -> None:
    with pytest.raises(TypeError):
        registration_allowed(bad)  # type: ignore[arg-type]
