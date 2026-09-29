"""Family independence and evidence-validation tests (Phase 10, plan 10-05, D-03, T-10-14/15).

"Independently specified" is decided by facts (7-slot sheet, distinct sheet hash, disjoint
registered parameter-set hashes), never a free-text flag. A TESTED_PASS / TESTED_FAIL status
can only be constructed from a recorded human decision (decision_ref, decided-at, Development
and Validation experiment ids): a fabricated pass cannot reach the evaluator.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from src.analytics.family import (
    REQUIRED_SLOTS,
    FamilyEvidence,
    FamilyStatus,
    KillGateInputError,
    independent_family_ids,
    is_baseline_parameter_set_id,
)
from src.analytics.killgate import KillGateInputError as ReExportedError

from tests.phase10_helpers import parse_utc

DECIDED = parse_utc("2026-11-15T00:00:00+00:00")


def make_family(family_id: str, **overrides: Any) -> FamilyEvidence:
    """A complete, independent, TESTED_FAIL family unless overridden."""
    digit = family_id[0]
    fields: dict[str, Any] = {
        "family_id": family_id,
        "sheet_sha256": digit * 64,
        "sheet_slots_present": REQUIRED_SLOTS,
        "candidate_param_set_hashes": (digit * 63 + "1",),
        "experiment_ids": (f"exp-{family_id}-dev", f"exp-{family_id}-val"),
        "status": FamilyStatus.TESTED_FAIL,
        "decision_ref": f"DEC-2026-11-fail-{family_id}",
        "decided_at_utc": DECIDED,
        "development_experiment_ids": (f"exp-{family_id}-dev",),
        "validation_experiment_ids": (f"exp-{family_id}-val",),
    }
    fields.update(overrides)
    return FamilyEvidence(**fields)


def test_killgate_reexports_the_same_error_type() -> None:
    assert ReExportedError is KillGateInputError
    assert issubclass(KillGateInputError, ValueError)


def test_three_complete_distinct_families_are_independent() -> None:
    families = [make_family("bbb"), make_family("aaa"), make_family("ccc")]
    independent, non_independent = independent_family_ids(families)
    assert independent == ("aaa", "bbb", "ccc")
    assert non_independent == ()


def test_missing_sheet_is_non_independent() -> None:
    families = [make_family("aaa", sheet_sha256=None), make_family("bbb")]
    assert independent_family_ids(families) == (("bbb",), ("aaa",))


def test_partial_sheet_slots_are_non_independent() -> None:
    families = [make_family("aaa", sheet_slots_present=(1, 2, 3)), make_family("bbb")]
    assert independent_family_ids(families) == (("bbb",), ("aaa",))


def test_shared_sheet_hash_marks_the_later_sorted_family_non_independent() -> None:
    shared = "d" * 64
    families = [
        make_family("bbb", sheet_sha256=shared),
        make_family("aaa", sheet_sha256=shared),
    ]
    assert independent_family_ids(families) == (("aaa",), ("bbb",))


def test_shared_param_set_hash_marks_the_later_sorted_family_non_independent() -> None:
    shared = ("e" * 63 + "9",)
    families = [
        make_family("bbb", candidate_param_set_hashes=shared),
        make_family("aaa", candidate_param_set_hashes=shared),
    ]
    assert independent_family_ids(families) == (("aaa",), ("bbb",))


def test_family_without_a_parameter_set_hash_is_non_independent() -> None:
    families = [make_family("aaa", candidate_param_set_hashes=())]
    assert independent_family_ids(families) == ((), ("aaa",))


def test_independence_result_does_not_depend_on_input_order() -> None:
    shared = "d" * 64
    forward = [make_family("aaa", sheet_sha256=shared), make_family("bbb", sheet_sha256=shared)]
    assert independent_family_ids(forward) == independent_family_ids(list(reversed(forward)))


def test_duplicate_family_ids_are_rejected() -> None:
    with pytest.raises(KillGateInputError):
        independent_family_ids([make_family("aaa"), make_family("aaa")])


def test_empty_family_id_is_rejected() -> None:
    with pytest.raises(KillGateInputError):
        dataclasses.replace(make_family("aaa"), family_id="")


@pytest.mark.parametrize("bad", ["", "xyz", "A" * 64, "a" * 63, "a" * 65])
def test_non_hex64_sheet_hash_is_rejected(bad: str) -> None:
    with pytest.raises(KillGateInputError):
        make_family("aaa", sheet_sha256=bad)


def test_non_hex64_param_set_hash_is_rejected() -> None:
    with pytest.raises(KillGateInputError):
        make_family("aaa", candidate_param_set_hashes=("not-a-hash",))


@pytest.mark.parametrize("status", [FamilyStatus.TESTED_FAIL, FamilyStatus.TESTED_PASS])
@pytest.mark.parametrize("ref", [None, "", "   "])
def test_tested_status_without_decision_ref_cannot_be_constructed(
    status: FamilyStatus, ref: str | None
) -> None:
    """Fabricated pass guard: the evaluator can never see a TESTED_* without a decision."""
    with pytest.raises(KillGateInputError):
        make_family("aaa", status=status, decision_ref=ref)


def test_tested_pass_without_decided_at_is_rejected() -> None:
    with pytest.raises(KillGateInputError):
        make_family("aaa", status=FamilyStatus.TESTED_PASS, decided_at_utc=None)


def test_naive_decided_at_is_rejected() -> None:
    with pytest.raises(KillGateInputError):
        make_family("aaa", decided_at_utc=DECIDED.replace(tzinfo=None))


def test_development_and_validation_ids_are_required_and_must_be_experiments() -> None:
    with pytest.raises(KillGateInputError):
        make_family("aaa", development_experiment_ids=())
    with pytest.raises(KillGateInputError):
        make_family("aaa", validation_experiment_ids=())
    with pytest.raises(KillGateInputError):
        make_family("aaa", development_experiment_ids=("exp-other",))
    with pytest.raises(KillGateInputError):
        make_family("aaa", validation_experiment_ids=("exp-other",))


def test_not_tested_family_needs_no_decision_record() -> None:
    family = make_family(
        "aaa",
        status=FamilyStatus.NOT_TESTED,
        decision_ref=None,
        decided_at_utc=None,
        development_experiment_ids=(),
        validation_experiment_ids=(),
    )
    assert family.status is FamilyStatus.NOT_TESTED


def test_baseline_parameter_set_ids_are_excluded_from_candidates() -> None:
    assert is_baseline_parameter_set_id("baseline-no-trade-v1") is True
    assert is_baseline_parameter_set_id("baseline-simple-trend-v1") is True
    assert is_baseline_parameter_set_id("baseline-v1") is False
    assert is_baseline_parameter_set_id("baseline-v2") is False
    assert is_baseline_parameter_set_id("trend-pullback-baseline-v1") is False
