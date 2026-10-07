"""Tests for the bookkeeping gate module (Phase 11, plan 11-07).

Positive tests feed the amended real documents; negative tests feed the pre-change text
from commit 679825c (skipped when that commit is not present in a shallow clone) and
synthetic mutated copies.
"""

from __future__ import annotations

import re
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


PRE_PHASE_12_REFERENCED = {
    "NO_TRADE_REGIME", "RR_TOO_LOW", "STALE_SETUP", "INVALIDATED",
    "EXCHANGE_CONSTRAINT", "DATA_STALE", "RECONCILIATION_REQUIRED",
    "APPROVAL_EXPIRED", "MIN_QTY_REJECT", "NOTIONAL_REJECT", "UTILIZATION_REJECT",
    "CLUSTER_CAP_REJECT", "AGGREGATE_CAP_REJECT", "MAX_POSITIONS_REJECT",
    "DAILY_STOP_BLOCK", "STALE_CONSTRAINTS", "UNCERTAIN_ACCOUNT_STATE",
}  # fmt: skip
PHASE_12_CODES = {"STOP_TOO_TIGHT", "COST_TO_RISK_EXCEEDED"}


def test_referenced_codes_are_the_seventeen_plus_optional_phase_12_codes() -> None:
    referenced = bk.referenced_reason_codes()
    # Superset/subset pair: the two cost-guard codes become referenced when plan 12-06
    # lands, so this assertion needs no edit then.
    assert PRE_PHASE_12_REFERENCED <= referenced
    assert referenced <= PRE_PHASE_12_REFERENCED | PHASE_12_CODES


def test_real_glossary_split_is_20_canonical_and_5_retired() -> None:
    parsed = bk.parse_glossary_sections(_read(GLOSSARY))
    assert len(parsed["canonical"]) == 20
    assert sorted(parsed["aliases"]) == sorted(bk.RETIRED_ALIASES)
    assert len(bk.RETIRED_ALIASES) == 5
    assert len(ENUM_VALUES) == 20
    assert not hasattr(bk, "ALIASES")


def test_retired_alias_added_to_enum_values_fails_gl03() -> None:
    gates = {
        n: ok
        for n, ok, _ in bk.check_glossary(
            _read(GLOSSARY),
            ENUM_VALUES | {"RISK_LIMIT"},
            bk.referenced_reason_codes(),
            APPROVAL_VALUES,
        )
    }
    assert gates["GL-03"] is False


def test_retired_alias_pasted_into_canonical_block_fails_gl01() -> None:
    lines = _read(GLOSSARY).splitlines()
    idx = lines.index("STOP_TOO_TIGHT")
    lines.insert(idx, "QUANTIZATION_REJECT")
    assert _gl(chr(10).join(lines))["GL-01"] is False


def test_retired_table_missing_a_row_fails_gl03() -> None:
    lines = _read(GLOSSARY).splitlines(keepends=True)
    kept = [ln for ln in lines if not ln.startswith("| `MIN_NOTIONAL_REJECT`")]
    assert len(kept) == len(lines) - 1
    assert _gl("".join(kept))["GL-03"] is False


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


def test_thirteen_new_ids_are_registered_and_mapped() -> None:
    req = _read(REQUIREMENTS)
    assert len(bk.NEW_REQUIREMENTS) == 13
    assert all(isinstance(p, str) for p in bk.NEW_REQUIREMENTS.values())
    assert bk.NEW_REQUIREMENTS["OPS-06"] == "13.1"  # the Phase 13.1 insertion moved it
    for rid, phase in bk.NEW_REQUIREMENTS.items():
        # Status is not pinned: later phases flip these IDs to Complete.
        row = rf"^\| {rid} \| Phase {re.escape(phase)} \| \w+ \|"
        assert re.search(row, req, flags=re.MULTILINE)
        assert re.search(rf"^- \[[ x]\] \*\*{rid}\*\*:", req, flags=re.MULTILINE)


def test_completed_new_requirement_does_not_fail_rq01() -> None:
    req = _read(REQUIREMENTS).replace(
        "| OPS-06 | Phase 13.1 | Pending |", "| OPS-06 | Phase 13.1 | Complete |"
    )
    assert _rq(req, _read(ROADMAP))["RQ-01"] is True


def test_later_footer_date_and_consistent_counts_pass_rq02_rq05() -> None:
    req = _read(REQUIREMENTS).replace("*Last updated: 2026-09-30", "*Last updated: 2027-01-15")
    gates = _rq(req, _read(ROADMAP))
    assert gates["RQ-02"] is True
    assert gates["RQ-05"] is True


def test_older_footer_date_fails_rq05() -> None:
    req = _read(REQUIREMENTS).replace("*Last updated: 2026-09-30", "*Last updated: 2026-09-01")
    assert _rq(req, _read(ROADMAP))["RQ-05"] is False


def test_missing_planning_files_skip_rq_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bk, "REQUIREMENTS_PATH", bk.REPO_ROOT / "nope" / "REQUIREMENTS.md")
    results = bk.run_reqs()
    assert len(results) == 5
    assert all(ok and detail.startswith("SKIP") for _, ok, detail in results)


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
    req = _read(REQUIREMENTS).replace("| OPS-06 | Phase 13.1 |", "| OPS-06 | Phase 14 |")
    assert _rq(req, _read(ROADMAP))["RQ-01"] is False


def test_roadmap_requirements_line_matches_decimal_phase_literally() -> None:
    roadmap = _read(ROADMAP)
    assert "OPS-06" in bk._roadmap_requirements_line(roadmap, "13.1")
    assert "OPS-06" not in bk._roadmap_requirements_line(roadmap, "13")
    # The dot is a literal: "13.1" must not match a phase heading such as "13x1".
    stub = "### Phase 13x1: X\n**Requirements**: A-01\n"
    assert bk._roadmap_requirements_line(stub, "13.1") == ""


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


# --------------------------------------------------------------------------- Task 3

DECISIONS = "docs/DECISIONS.md"
DOC_STATUS = "docs/DOC_STATUS.md"
DATA_MODEL = "docs/data/DATA_MODEL.md"
SEC_OPS = "docs/operations/SECURITY_AND_OPERATIONS.md"
PROTOCOL = "docs/research/RESEARCH_PROTOCOL.md"


def _dc(
    decisions: str | None = None,
    doc_status: str | None = None,
    data_model: str | None = None,
    sec_ops: str | None = None,
    protocol: str | None = None,
) -> dict[str, bool]:
    gates = bk.check_decisions(
        _read(DECISIONS) if decisions is None else decisions,
        _read(DOC_STATUS) if doc_status is None else doc_status,
        _read(DATA_MODEL) if data_model is None else data_model,
        _read(SEC_OPS) if sec_ops is None else sec_ops,
        protocol=_read(PROTOCOL) if protocol is None else protocol,
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


def test_appended_later_decision_keeps_dc02_green() -> None:
    real = _read(DECISIONS)
    next_id = f"D{len(bk._DECISION_ROW.findall(real)) + 1:03d}"
    text = real.rstrip("\n") + f"\n| {next_id} | Later decision | Accepted | x | y |\n"
    assert _dc(decisions=text)["DC-02"] is True


D046_WITNESS_TOKENS = (
    "STOP_TOO_TIGHT",
    "COST_TO_RISK_EXCEEDED",
    "adverse edge",
    "supersedes",
    "exit_slippage_rate",
    "ACCOUNT_MAX",
    "UNCERTAIN_ACCOUNT_STATE",
    "0.79",
    "ratification",
    "one-way",
    "F-028",
    "Phase 14",
    "Phase 24",
)


def test_d046_row_carries_witness_tokens() -> None:
    row = bk._decision_row(_read(DECISIONS), "D046")
    assert row, "D046 row missing"
    assert [t for t in D046_WITNESS_TOKENS if t not in row] == []


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


def _header_version() -> str:
    match = re.search(r"^> \*\*Protocol version:\*\* (v\d+\.\d+\.\d+)", _read(PROTOCOL), re.M)
    assert match is not None
    return match.group(1)


def test_current_header_version_row_is_required_by_dc03() -> None:
    """DC-03 also binds the row of the header version (v2.1.0, D060), not only the D043 row."""
    version = _header_version()
    text = _read(DECISIONS)
    assert f"protocol {version} frozen" in bk._decision_row(text, "D060")
    assert (
        _dc(decisions=text.replace(f"protocol {version} frozen", "protocol frozen"))["DC-03"]
        is False
    )
    # a header that names a version with no freeze row at all fails closed
    bumped = _read(PROTOCOL).replace(
        f"**Protocol version:** {version}", "**Protocol version:** v9.9.9"
    )
    assert _dc(protocol=bumped)["DC-03"] is False
    # a header without a version line fails closed too
    no_version = "\n".join(
        ln for ln in _read(PROTOCOL).splitlines() if not ln.startswith("> **Protocol version:**")
    )
    assert _dc(protocol=no_version)["DC-03"] is False


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


def test_real_table_reaches_d053() -> None:
    ids = bk._DECISION_ROW.findall(_read(DECISIONS))
    assert len(ids) >= 53
    assert ids[50:53] == ["D051", "D052", "D053"]


def test_real_table_reaches_d054() -> None:
    ids = bk._DECISION_ROW.findall(_read(DECISIONS))
    assert len(ids) >= 54
    assert ids[50:54] == ["D051", "D052", "D053", "D054"]


def test_real_table_reaches_d048() -> None:
    ids = bk._DECISION_ROW.findall(_read(DECISIONS))
    assert bk.MIN_LAST_DECISION == 48
    assert len(ids) >= 48
    assert ids[45:48] == ["D046", "D047", "D048"]


def test_d047_and_d048_rows_carry_witness_tokens() -> None:
    text = _read(DECISIONS)
    d047 = bk._decision_row(text, "D047")
    d048 = bk._decision_row(text, "D048")
    assert [t for t in ("canonical", "parameter_set_hash", "1.0") if t not in d047] == []
    assert [
        t
        for t in (
            "parity_overlapping_history",
            "DERIVATIONS",
            "gen_phase6_fixtures",
            "parameter_set_hash",
            "placement_sequences",
        )
        if t not in d048
    ] == []
