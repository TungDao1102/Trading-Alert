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
BASELINE_COMMIT = "679825c"

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
    assert len(parsed["canonical"]) == 18  # type: ignore[arg-type]
    assert len(parsed["aliases"]) == 5  # type: ignore[arg-type]
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
