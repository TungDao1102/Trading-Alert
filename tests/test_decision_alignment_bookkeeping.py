"""Tests for the bookkeeping gate module (Phase 11, plan 11-07).

Positive tests feed the amended real documents; negative tests feed the pre-change text
from commit 679825c (skipped when that commit is not present in a shallow clone) and
synthetic mutated copies.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.decision_alignment import bookkeeping as bk
from src.domain.enums import ApprovalResult, RejectionReason

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "679825cf3bf75ccf0cccbe10cda7b9d23d9c58b2"

GLOSSARY = "docs/GLOSSARY.md"


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _old(rel: str) -> str:
    """Pre-change text of a document from the baseline commit."""
    proc = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:{rel}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"baseline commit {BASELINE_COMMIT} unavailable")
    return proc.stdout


# --------------------------------------------------------------------------- Task 1

ENUM_VALUES = {m.value for m in RejectionReason}
APPROVAL_VALUES = {m.value for m in ApprovalResult}


def _gl(text: str, *, referenced: set[str] | None = None) -> dict[str, bool]:
    refs = bk.referenced_reason_codes() if referenced is None else referenced
    return {n: ok for n, ok, _ in bk.check_glossary(text, ENUM_VALUES, refs, APPROVAL_VALUES)}


def test_glossary_gates_pass_on_real_repo() -> None:
    results = bk.run_glossary()
    assert [n for n, _, _ in results] == [f"GL-0{i}" for i in range(1, 7)]
    assert all(ok for _, ok, _ in results), [g for g in results if not g[1]]


def test_referenced_codes_are_the_seventeen_expected() -> None:
    assert bk.referenced_reason_codes() == {
        "NO_TRADE_REGIME", "RR_TOO_LOW", "STALE_SETUP", "INVALIDATED",
        "EXCHANGE_CONSTRAINT", "DATA_STALE", "RECONCILIATION_REQUIRED",
        "APPROVAL_EXPIRED", "MIN_QTY_REJECT", "NOTIONAL_REJECT", "UTILIZATION_REJECT",
        "CLUSTER_CAP_REJECT", "AGGREGATE_CAP_REJECT", "MAX_POSITIONS_REJECT",
        "DAILY_STOP_BLOCK", "STALE_CONSTRAINTS", "UNCERTAIN_ACCOUNT_STATE",
    }  # fmt: skip


def test_real_glossary_split_is_18_plus_5_equals_23() -> None:
    parsed = bk.parse_glossary_sections(_read(GLOSSARY))
    assert len(parsed["canonical"]) == 18
    assert len(parsed["aliases"]) == 5
    assert len(ENUM_VALUES) == 23


def test_pre_change_glossary_fails_gl01_gl03_gl04() -> None:
    gates = _gl(_old(GLOSSARY))
    assert gates["GL-01"] is False  # aliases sit in the canonical block
    assert gates["GL-03"] is False
    assert gates["GL-04"] is False  # section 10 absent


def test_duplicate_canonical_code_fails_gl01() -> None:
    text = _read(GLOSSARY).replace("RR_TOO_LOW\n", "RR_TOO_LOW\nRR_TOO_LOW\n", 1)
    # CRLF working tree: fall back to the CRLF spelling when LF did not match.
    if text == _read(GLOSSARY):
        text = _read(GLOSSARY).replace("RR_TOO_LOW\r\n", "RR_TOO_LOW\r\nRR_TOO_LOW\r\n", 1)
    assert _gl(text)["GL-01"] is False


def test_missing_referenced_code_fails_gl02() -> None:
    assert _gl(_read(GLOSSARY), referenced={"NOT_A_CODE"})["GL-02"] is False


def test_union_differing_from_enum_fails_gl03() -> None:
    text = _read(GLOSSARY)
    gates = {
        n: ok
        for n, ok, _ in bk.check_glossary(
            text, ENUM_VALUES | {"EXTRA_CODE"}, bk.referenced_reason_codes(), APPROVAL_VALUES
        )
    }
    assert gates["GL-03"] is False


def test_approval_mismatch_fails_gl04() -> None:
    gates = {
        n: ok
        for n, ok, _ in bk.check_glossary(
            _read(GLOSSARY), ENUM_VALUES, bk.referenced_reason_codes(), APPROVAL_VALUES | {"X"}
        )
    }
    assert gates["GL-04"] is False


def test_missing_string_code_fails_gl05() -> None:
    text = _read(GLOSSARY).replace("HEALTH_CHECK_FAILED", "REDACTED_CODE")
    assert _gl(text)["GL-05"] is False


def test_missing_82_heading_fails_gl06() -> None:
    text = _read(GLOSSARY).replace("### 8.2 Canonical KillGateState", "### 8.2 Something else")
    assert _gl(text)["GL-06"] is False


# --------------------------------------------------------------------------- Task 2

REQUIREMENTS = ".planning/REQUIREMENTS.md"
ROADMAP = ".planning/ROADMAP.md"


def _rq(req: str, roadmap: str) -> dict[str, bool]:
    return {n: ok for n, ok, _ in bk.check_requirements(req, roadmap)}


def test_requirement_gates_pass_on_real_repo() -> None:
    results = bk.run_reqs()
    assert [n for n, _, _ in results] == [f"RQ-0{i}" for i in range(1, 6)]
    assert all(ok for _, ok, _ in results), [g for g in results if not g[1]]


def test_thirteen_new_ids_are_registered_and_all_pending() -> None:
    req = _read(REQUIREMENTS)
    assert len(bk.NEW_REQUIREMENTS) == 13
    for rid, phase in bk.NEW_REQUIREMENTS.items():
        assert f"| {rid} | Phase {phase} | Pending |" in req
        assert f"- [ ] **{rid}**:" in req


def test_pre_change_documents_fail_rq01_rq02_rq04_rq05() -> None:
    gates = _rq(_old(REQUIREMENTS), _old(ROADMAP))
    assert gates["RQ-01"] is False
    assert gates["RQ-02"] is False
    assert gates["RQ-04"] is False
    assert gates["RQ-05"] is False


def test_dropped_traceability_row_fails_rq01_and_rq03() -> None:
    req = _read(REQUIREMENTS)
    kept = [ln for ln in req.splitlines(keepends=True) if not ln.startswith("| GOV-02 |")]
    gates = _rq("".join(kept), _read(ROADMAP))
    assert gates["RQ-01"] is False
    assert gates["RQ-03"] is False


def test_wrong_phase_fails_rq01() -> None:
    req = _read(REQUIREMENTS).replace("| OPS-06 | Phase 13 |", "| OPS-06 | Phase 14 |")
    assert _rq(req, _read(ROADMAP))["RQ-01"] is False


def test_stale_coverage_count_fails_rq02() -> None:
    req = _read(REQUIREMENTS).replace("43 total", "30 total")
    assert _rq(req, _read(ROADMAP))["RQ-02"] is False


def test_duplicate_list_item_fails_rq03() -> None:
    req = _read(REQUIREMENTS)
    line = next(ln for ln in req.splitlines(keepends=True) if ln.startswith("- [ ] **RISK-04**"))
    assert _rq(req + line, _read(ROADMAP))["RQ-03"] is False


def test_roadmap_missing_new_id_fails_rq04() -> None:
    roadmap = _read(ROADMAP).replace("EXEC-05", "EXEC-0X")
    assert _rq(_read(REQUIREMENTS), roadmap)["RQ-04"] is False


def test_stale_roadmap_sentence_fails_rq04() -> None:
    roadmap = _read(ROADMAP) + "\nA new REQ-ID is to be added for something.\n"
    assert _rq(_read(REQUIREMENTS), roadmap)["RQ-04"] is False


def test_no_new_requirement_is_marked_complete() -> None:
    req = _read(REQUIREMENTS)
    for rid in bk.NEW_REQUIREMENTS:
        assert f"- [x] **{rid}**" not in req
        assert f"| {rid} |" in req and f"| {rid} | Phase" in req
        assert not any(ln.startswith(f"| {rid} |") and "Complete" in ln for ln in req.splitlines())


# --------------------------------------------------------------------------- Task 3

DECISIONS = "docs/DECISIONS.md"
DOC_STATUS = "docs/DOC_STATUS.md"
DATA_MODEL = "docs/data/DATA_MODEL.md"
SEC_OPS = "docs/operations/SECURITY_AND_OPERATIONS.md"


def _dc(
    decisions: str | None = None,
    doc_status: str | None = None,
    data_model: str | None = None,
    sec_ops: str | None = None,
) -> dict[str, bool]:
    gates = bk.check_decisions(
        _read(DECISIONS) if decisions is None else decisions,
        _read(DOC_STATUS) if doc_status is None else doc_status,
        _read(DATA_MODEL) if data_model is None else data_model,
        _read(SEC_OPS) if sec_ops is None else sec_ops,
    )
    return {n: ok for n, ok, _ in gates}


def _drop_row(text: str, decision_id: str) -> str:
    return "".join(
        ln for ln in text.splitlines(keepends=True) if not ln.startswith(f"| {decision_id} |")
    )


def test_decision_gates_pass_on_real_repo() -> None:
    results = bk.run_decisions()
    assert [n for n, _, _ in results] == [f"DC-0{i}" for i in range(1, 7)]
    assert all(ok for _, ok, _ in results), [g for g in results if not g[1]]


def test_run_returns_seventeen_passing_gates() -> None:
    results = bk.run()
    assert len(results) == 17
    assert all(ok for _, ok, _ in results), [g for g in results if not g[1]]


def test_pre_change_decisions_fail_dc01_and_dc02() -> None:
    gates = _dc(decisions=_old(DECISIONS))
    assert gates["DC-01"] is False  # blank line inside the table
    assert gates["DC-02"] is False  # ends at D042


def test_missing_d044_or_d045_fails_dc02_and_dc04() -> None:
    for decision_id in ("D044", "D045"):
        gates = _dc(decisions=_drop_row(_read(DECISIONS), decision_id))
        assert gates["DC-02"] is False
        assert gates["DC-04"] is False


def test_d044_missing_owner_phase_fails_dc04() -> None:
    text = _read(DECISIONS)
    row = next(ln for ln in text.splitlines() if ln.startswith("| D044 |"))
    assert _dc(decisions=text.replace(row, row.replace("Phase 22", "Phase XX")))["DC-04"] is False


def test_d045_missing_token_fails_dc04() -> None:
    text = _read(DECISIONS)
    row = next(ln for ln in text.splitlines() if ln.startswith("| D045 |"))
    assert _dc(decisions=text.replace(row, row.replace("F-128", "F-XXX")))["DC-04"] is False


def test_blank_line_inside_table_fails_dc01() -> None:
    text = _read(DECISIONS)
    marker = next(ln for ln in text.splitlines(keepends=True) if ln.startswith("| D020 |"))
    assert _dc(decisions=text.replace(marker, "\n" + marker))["DC-01"] is False


def test_d043_row_without_witness_phrase_fails_dc03() -> None:
    text = _read(DECISIONS).replace("protocol v1.1.0 frozen", "protocol frozen")
    assert _dc(decisions=text)["DC-03"] is False


def test_data_model_without_notes_fails_dc05() -> None:
    assert _dc(data_model=_old(DATA_MODEL))["DC-05"] is False


def test_doc_status_without_d044_line_fails_dc05() -> None:
    assert _dc(doc_status=_old(DOC_STATUS))["DC-05"] is False


def test_sec_ops_without_d045_reference_fails_dc06() -> None:
    assert _dc(sec_ops=_read(SEC_OPS).replace("D045", "DXXX"))["DC-06"] is False


def test_d044_owner_phases_exist_in_roadmap() -> None:
    roadmap = _read(ROADMAP)
    for phase in bk.D044_OWNER_PHASES:
        number = phase.split()[1]
        assert f"### {phase}:" in roadmap, f"{phase} missing from ROADMAP.md"
        assert number.isdigit()
