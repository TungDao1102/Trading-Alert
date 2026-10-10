"""Requirement closure rule (Phase 16, plan 16-25, SC9, D061 item J).

PAPER-01 is closable only when SC1, SC2 and SC7 each hold REAL evidence, PAPER-02 only when SC3 and
SC5 do, and PAPER-03 stays Pending (Phase 26). Fixture, fake and code-level evidence never closes
either requirement, and a proof class comes from where the evidence came from, never from a flag.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from src.paper import exit_criteria as exit_module
from src.paper.exit_criteria import (
    PAPER_03_STATUS,
    REQUIREMENT_CRITERIA,
    SC5_CODE_ONLY_SUBCLAIMS,
    ClosureVerdict,
    EvidenceItem,
    ProofClass,
    bundle_evidence_item,
    closure_verdict,
    code_evidence_item,
    rehearsal_evidence_item,
    smoke_evidence_item,
)

from tests.test_paper_exit_evaluator import _evaluate, _write_and_load, make_fixture

SHA = "a" * 64


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _real_soak_item(tmp_path: Path, name: str = "soak") -> EvidenceItem:
    fixture = make_fixture(source="pg")
    bundle = _write_and_load(fixture, tmp_path / name)
    return bundle_evidence_item(bundle, _evaluate(bundle))


def _smoke(tmp_path: Path, criterion: str, proof_class: str, name: str) -> EvidenceItem:
    return smoke_evidence_item(
        criterion, _write(tmp_path / f"{name}.json", {"proof_class": proof_class})
    )


def _rehearsal(tmp_path: Path, criterion: str, proof_class: str, name: str) -> EvidenceItem:
    return rehearsal_evidence_item(
        criterion, _write(tmp_path / f"{name}.json", {"proof_class": proof_class})
    )


def _code(tmp_path: Path, criterion: str, name: str) -> EvidenceItem:
    path = tmp_path / f"test_{name}.py"
    path.write_text("def test_it() -> None: ...\n", encoding="utf-8")
    return code_evidence_item(criterion, path)


def _status(verdict: ClosureVerdict, requirement: str) -> str:
    return next(r.status for r in verdict.requirements if r.requirement == requirement)


def _missing(verdict: ClosureVerdict) -> str:
    return "\n".join(text for r in verdict.requirements for c in r.criteria for text in c.missing)


# --------------------------------------------------------------------------- #
# Test 1: real proof per criterion.
# --------------------------------------------------------------------------- #


def test_the_requirement_map_cites_sc9_and_d061_item_j() -> None:
    assert REQUIREMENT_CRITERIA == {"PAPER-01": ("SC1", "SC2", "SC7"), "PAPER-02": ("SC3", "SC5")}
    source = Path(inspect.getsourcefile(exit_module) or "").read_text(encoding="utf-8")
    assert "ROADMAP SC9" in source and "D061 item J" in source


def test_paper_01_is_closable_with_real_soak_real_smoke_and_the_code_contract(
    tmp_path: Path,
) -> None:
    items = [
        _real_soak_item(tmp_path),
        _smoke(tmp_path, "SC7", "REAL_SMOKE", "live7"),
        _smoke(tmp_path, "SC2", "REAL_SMOKE", "live2"),
        _code(tmp_path, "SC2", "ws_contract"),
    ]
    verdict = closure_verdict(items)
    assert _status(verdict, "PAPER-01") == "CLOSABLE"
    assert _status(verdict, "PAPER-02") == "NOT CLOSABLE"


@pytest.mark.parametrize("drop", ["SC1", "SC7", "SC2-smoke", "SC2-code"])
def test_paper_01_needs_every_criterion_real(tmp_path: Path, drop: str) -> None:
    items = {
        "SC1": _real_soak_item(tmp_path),
        "SC7": _smoke(tmp_path, "SC7", "REAL_SMOKE", "live7"),
        "SC2-smoke": _smoke(tmp_path, "SC2", "REAL_SMOKE", "live2"),
        "SC2-code": _code(tmp_path, "SC2", "ws_contract"),
    }
    del items[drop]
    verdict = closure_verdict(list(items.values()))
    assert _status(verdict, "PAPER-01") == "NOT CLOSABLE"
    assert "SC" in _missing(verdict)


def test_paper_02_is_closable_with_a_real_rehearsal_or_a_real_soak_per_criterion(
    tmp_path: Path,
) -> None:
    items = [
        _rehearsal(tmp_path, "SC3", "REAL_REHEARSAL", "r3"),
        _rehearsal(tmp_path, "SC5", "REAL_REHEARSAL", "r5"),
        _code(tmp_path, "SC3", "fill_golden"),
    ]
    assert _status(closure_verdict(items), "PAPER-02") == "CLOSABLE"

    soak = _real_soak_item(tmp_path)
    as_soak = EvidenceItem(criterion="SC5", proof_class=soak.proof_class, path="p", sha256=SHA)
    verdict = closure_verdict([items[0], as_soak])
    assert _status(verdict, "PAPER-02") == "CLOSABLE"


def test_code_items_are_listed_as_supporting_and_never_sufficient(tmp_path: Path) -> None:
    items = [_code(tmp_path, "SC3", "fill_golden"), _code(tmp_path, "SC5", "shadow_pg")]
    verdict = closure_verdict(items)
    assert _status(verdict, "PAPER-02") == "NOT CLOSABLE"
    sc3 = next(c for r in verdict.requirements for c in r.criteria if c.criterion == "SC3")
    assert [i.proof_class for i in sc3.supporting_items] == [ProofClass.CODE]
    assert sc3.real_items == ()
    assert "REAL_REHEARSAL or REAL_SOAK item for SC3" in _missing(verdict)


# --------------------------------------------------------------------------- #
# Test 2: negative control for SC9.
# --------------------------------------------------------------------------- #


def test_a_complete_set_of_fake_and_code_evidence_closes_nothing(tmp_path: Path) -> None:
    fixture = make_fixture(source="fixture")
    bundle = _write_and_load(fixture, tmp_path / "fixture-bundle")
    items = [
        bundle_evidence_item(bundle, _evaluate(bundle)),
        _smoke(tmp_path, "SC7", "FAKE", "dry7"),
        _smoke(tmp_path, "SC2", "FAKE", "dry2"),
        _code(tmp_path, "SC2", "ws_contract"),
        _rehearsal(tmp_path, "SC3", "FAKE", "dry3"),
        _rehearsal(tmp_path, "SC5", "FAKE", "dry5"),
        _code(tmp_path, "SC3", "fill_golden"),
        _code(tmp_path, "SC5", "shadow_pg"),
    ]
    assert all(i.proof_class in (ProofClass.FAKE, ProofClass.CODE) for i in items)

    verdict = closure_verdict(items)
    assert _status(verdict, "PAPER-01") == "NOT CLOSABLE"
    assert _status(verdict, "PAPER-02") == "NOT CLOSABLE"
    missing = _missing(verdict)
    for named in (
        "REAL_SOAK item for SC1",
        "REAL_SMOKE item for SC2",
        "REAL_SMOKE item for SC7",
        "REAL_REHEARSAL or REAL_SOAK item for SC3",
        "REAL_REHEARSAL or REAL_SOAK item for SC5",
    ):
        assert named in missing, named
    assert "NOT CLOSABLE" in verdict.render()


def test_a_failed_trial_evaluation_cannot_become_evidence(tmp_path: Path) -> None:
    fixture = make_fixture(source="pg")
    fixture.diff_lines[10]["outcome"] = "REGISTRY_DIFF"
    bundle = _write_and_load(fixture, tmp_path / "failing")
    evaluation = _evaluate(bundle)
    assert not evaluation.passed
    with pytest.raises(ValueError, match="failed"):
        bundle_evidence_item(bundle, evaluation)


# --------------------------------------------------------------------------- #
# Test 3: sub-claims a rehearsal cannot exercise are disclosed.
# --------------------------------------------------------------------------- #


def test_sc5_subclaims_are_disclosed_as_code_and_pg_proof_only(tmp_path: Path) -> None:
    assert SC5_CODE_ONLY_SUBCLAIMS == ("SKIP journaling", "CANCEL journaling", "expiry journaling")
    items = [
        _rehearsal(tmp_path, "SC3", "REAL_REHEARSAL", "r3"),
        _rehearsal(tmp_path, "SC5", "REAL_REHEARSAL", "r5"),
    ]
    verdict = closure_verdict(items)
    assert _status(verdict, "PAPER-02") == "CLOSABLE"
    text = "\n".join(verdict.disclosures)
    for subclaim in SC5_CODE_ONLY_SUBCLAIMS:
        assert f"{subclaim}: CODE and PG proof only, disclosed" in text
    assert "O-11 (v)" in text
    assert verdict.disclosures == closure_verdict([]).disclosures


# --------------------------------------------------------------------------- #
# Test 4: PAPER-03.
# --------------------------------------------------------------------------- #


def test_paper_03_is_never_closable_here(tmp_path: Path) -> None:
    everything_real = [
        _real_soak_item(tmp_path),
        _smoke(tmp_path, "SC7", "REAL_SMOKE", "live7"),
        _smoke(tmp_path, "SC2", "REAL_SMOKE", "live2"),
        _code(tmp_path, "SC2", "ws_contract"),
        _rehearsal(tmp_path, "SC3", "REAL_REHEARSAL", "r3"),
        _rehearsal(tmp_path, "SC5", "REAL_REHEARSAL", "r5"),
    ]
    verdict = closure_verdict(everything_real)
    assert PAPER_03_STATUS == "Pending, Phase 26"
    assert _status(verdict, "PAPER-03") == "Pending, Phase 26"
    assert all(r.closable for r in verdict.requirements if r.requirement != "PAPER-03")
    paper_03 = next(r for r in verdict.requirements if r.requirement == "PAPER-03")
    assert paper_03.closable is False and paper_03.criteria == ()
    assert closure_verdict([]).requirements[-1].status == "Pending, Phase 26"


# --------------------------------------------------------------------------- #
# Test 5: the proof class comes from the source, never from a flag.
# --------------------------------------------------------------------------- #


def test_a_bundle_proof_class_follows_its_manifest_source_only(tmp_path: Path) -> None:
    fake = _write_and_load(make_fixture(source="fixture"), tmp_path / "f")
    real = _write_and_load(make_fixture(source="pg"), tmp_path / "p")
    assert bundle_evidence_item(fake, _evaluate(fake)).proof_class is ProofClass.FAKE
    assert bundle_evidence_item(real, _evaluate(real)).proof_class is ProofClass.REAL_SOAK
    for factory in (
        bundle_evidence_item,
        smoke_evidence_item,
        rehearsal_evidence_item,
        code_evidence_item,
    ):
        assert "proof_class" not in inspect.signature(factory).parameters, factory.__name__


def test_a_smoke_file_proof_class_is_read_from_its_field_and_validated(tmp_path: Path) -> None:
    assert _smoke(tmp_path, "SC7", "FAKE", "dry").proof_class is ProofClass.FAKE
    assert _smoke(tmp_path, "SC7", "REAL_SMOKE", "live").proof_class is ProofClass.REAL_SMOKE
    for claimed in ("REAL_SOAK", "REAL_REHEARSAL", "CODE", "fake", "", None):
        bad = _write(tmp_path / "bad.json", {"proof_class": claimed})
        with pytest.raises(ValueError, match="proof_class"):
            smoke_evidence_item("SC7", bad)
    no_field = _write(tmp_path / "none.json", {"other": 1})
    with pytest.raises(ValueError, match="proof_class"):
        smoke_evidence_item("SC7", no_field)


def test_a_rehearsal_file_proof_class_is_read_from_its_field_and_validated(
    tmp_path: Path,
) -> None:
    assert _rehearsal(tmp_path, "SC3", "FAKE", "dry").proof_class is ProofClass.FAKE
    assert (
        _rehearsal(tmp_path, "SC3", "REAL_REHEARSAL", "live").proof_class
        is ProofClass.REAL_REHEARSAL
    )
    for claimed in ("REAL_SOAK", "REAL_SMOKE", "CODE"):
        bad = _write(tmp_path / "bad.json", {"proof_class": claimed})
        with pytest.raises(ValueError, match="proof_class"):
            rehearsal_evidence_item("SC3", bad)


def test_items_are_checked_when_they_are_built(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="criterion"):
        EvidenceItem(criterion="SC4", proof_class=ProofClass.CODE, path="p", sha256=SHA)
    with pytest.raises(ValueError, match="sha256"):
        EvidenceItem(criterion="SC3", proof_class=ProofClass.CODE, path="p", sha256="short")
    with pytest.raises(ValueError, match="criterion"):
        smoke_evidence_item("SC3", _write(tmp_path / "s.json", {"proof_class": "REAL_SMOKE"}))
    with pytest.raises(ValueError, match="criterion"):
        rehearsal_evidence_item("SC7", _write(tmp_path / "r.json", {"proof_class": "FAKE"}))
    outside = tmp_path / "notes.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="test"):
        code_evidence_item("SC3", outside)


def test_an_item_carries_the_sha256_of_its_file(tmp_path: Path) -> None:
    path = _write(tmp_path / "s.json", {"proof_class": "REAL_SMOKE"})
    item = smoke_evidence_item("SC7", path)
    assert item.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert item.path == str(path)


def test_the_closure_verdict_is_deterministic_and_order_independent(tmp_path: Path) -> None:
    items = [
        _smoke(tmp_path, "SC7", "REAL_SMOKE", "live7"),
        _code(tmp_path, "SC2", "ws_contract"),
        _rehearsal(tmp_path, "SC3", "REAL_REHEARSAL", "r3"),
    ]
    assert closure_verdict(items) == closure_verdict(list(reversed(items)))
    assert closure_verdict(items).render() == closure_verdict(list(reversed(items))).render()
