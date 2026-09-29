"""Approval-delay impact tests (Phase 10, plan 10-06, D-02, METRICS section 3).

Task 1 tracer: three side-by-side reports (System / User execution /
Opportunity) over PAPER lifecycle records with honest INCOMPLETE accounting and
the synthetic-lag label (RESEARCH P2).
"""

from __future__ import annotations

import ast
import dataclasses
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.analytics.approval_delay import (
    SYNTHETIC_LAG_LABEL,
    ApprovalDelayBlock,
    ApprovalDelaySection,
    build_approval_delay,
)
from src.analytics.lifecycle import LifecyclePath, LifecycleRecord
from src.analytics.types import AnalyticsInputError, EvidenceKind
from src.domain.enums import ApprovalResult
from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS

from tests.phase10_helpers import D, load_expected, load_input, make_lifecycle_record

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
APPROVAL_DELAY_SRC = SRC_DIR / "analytics" / "approval_delay.py"
RESAMPLES = 100
SEED = 20260929


def build_records(rows: list[dict[str, Any]], evidence: str) -> list[LifecycleRecord]:
    """Fixture rows -> LifecycleRecords (enums parsed; ISO strings handled by the helper)."""
    records: list[LifecycleRecord] = []
    for row in rows:
        fields: dict[str, Any] = dict(row)
        fields["evidence"] = EvidenceKind(evidence)
        fields["path"] = LifecyclePath(fields["path"])
        if fields.get("approval_result") is not None:
            fields["approval_result"] = ApprovalResult(fields["approval_result"])
        records.append(make_lifecycle_record(**fields))
    return records


def case_inputs(case: str) -> tuple[list[LifecycleRecord], dict[str, Decimal], dict[str, Decimal]]:
    data = load_input("approval_delay_three_reports")[case]
    records = build_records(data["records"], data["evidence"])
    realized = {key: D(value) for key, value in data["realized_r_by_signal"].items()}
    hypothetical = {key: D(value) for key, value in data["hypothetical_r_by_signal"].items()}
    return records, realized, hypothetical


def section_for(
    case: str,
    evidence: EvidenceKind,
    *,
    records: list[LifecycleRecord] | None = None,
    hypothetical: dict[str, Decimal] | None = None,
) -> ApprovalDelaySection:
    loaded, realized, loaded_hypothetical = case_inputs(case)
    return build_approval_delay(
        loaded if records is None else records,
        evidence=evidence,
        realized_r_by_signal=realized,
        hypothetical_r_by_signal=loaded_hypothetical if hypothetical is None else hypothetical,
        base_seed=SEED,
        resamples=RESAMPLES,
    )


def paper_section() -> ApprovalDelaySection:
    return section_for("paper", EvidenceKind.PAPER)


def assert_block(block: ApprovalDelayBlock, want: dict[str, Any]) -> None:
    assert block.n_signals == want["n_signals"]
    assert block.n_r_valued == want["n_r_valued"]
    assert block.incomplete == tuple((reason, count) for reason, count in want["incomplete"])
    assert block.hypothetical_used is want["hypothetical_used"]
    if "mean_r" in want:
        assert block.mean_r.value == D(want["mean_r"])
        assert block.expectancy_r == D(want["mean_r"])
    if "win_rate" in want:
        assert block.win_rate == D(want["win_rate"])
    if "interval_absent" in want:
        assert block.mean_r.interval_absent is want["interval_absent"]


def test_tracer_three_reports_paper() -> None:
    expected = load_expected("approval_delay_three_reports")["paper"]
    section = paper_section()
    assert section.evidence is EvidenceKind.PAPER
    assert_block(section.system, expected["system"])
    assert_block(section.user_execution, expected["user_execution"])
    assert_block(section.opportunity, expected["opportunity"])
    assert (section.system.label, section.user_execution.label, section.opportunity.label) == (
        "SYSTEM",
        "USER_EXECUTION",
        "OPPORTUNITY",
    )
    # System R per record: realized else hypothetical -> (1.0, -0.5, 2.0) mean 5/6.
    assert section.system.mean_r.value is not None
    assert abs(section.system.mean_r.value - D("2.5") / D("3")) < D("0.000001")
    assert section.system.win_rate is not None
    assert abs(section.system.win_rate - D("2") / D("3")) < D("0.000001")
    assert section.opportunity.mean_r.value == D("2.0")
    assert section.synthetic_lag_seconds == expected["synthetic_lag_seconds"] == 30
    assert section.synthetic_lag_label == expected["synthetic_lag_label"]
    assert section.buckets == ()
    assert section.measured_delay is None
    assert HEX64.match(section.digest())
    assert section.digest() == expected["section_digest"]


def test_synthetic_lag_label_uses_imported_constant() -> None:
    assert SYNTHETIC_LAG_LABEL == "SYNTHETIC LAG (APPROVAL_DELAY_LAG_SECONDS=30)"
    assert SYNTHETIC_LAG_LABEL == (
        f"SYNTHETIC LAG (APPROVAL_DELAY_LAG_SECONDS={APPROVAL_DELAY_LAG_SECONDS})"
    )
    tree = ast.parse(APPROVAL_DELAY_SRC.read_text(encoding="utf-8"))
    imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            assert "APPROVAL_DELAY_LAG_SECONDS" not in names
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assert node.target.id != "APPROVAL_DELAY_LAG_SECONDS"
        if isinstance(node, ast.ImportFrom) and node.module == "src.paper.attribution":
            imported = imported or any(a.name == "APPROVAL_DELAY_LAG_SECONDS" for a in node.names)
    assert imported


def test_sections_never_compare_blocks() -> None:
    forbidden = ("delta", "diff", "rank", "best", "worst", "better", "advice", "recommend")
    names = {f.name for f in dataclasses.fields(ApprovalDelaySection)}
    names |= {f.name for f in dataclasses.fields(ApprovalDelayBlock)}
    for name in names:
        assert not any(word in name.lower() for word in forbidden), name
    section = paper_section()
    for block in (section.system, section.user_execution, section.opportunity):
        assert HEX64.match(block.digest())


def test_missing_hypothetical_is_never_imputed() -> None:
    section = section_for("paper", EvidenceKind.PAPER, hypothetical={})
    assert section.opportunity.n_r_valued == 0
    assert section.opportunity.mean_r.value is None
    assert section.opportunity.win_rate is None
    assert section.opportunity.incomplete == (("NO_HYPOTHETICAL_OUTCOME", 2),)
    assert section.opportunity.hypothetical_used is False
    assert section.system.n_r_valued == 2
    assert section.system.incomplete == (
        ("NO_HYPOTHETICAL_OUTCOME", 2),
        ("NO_PAPER_OUTCOME", 1),
    )


def test_mixed_evidence_kinds_raise() -> None:
    with pytest.raises(AnalyticsInputError):
        section_for("paper", EvidenceKind.LIVE)


def test_duplicate_signal_key_raises() -> None:
    records, _, _ = case_inputs("paper")
    with pytest.raises(AnalyticsInputError):
        section_for("paper", EvidenceKind.PAPER, records=[*records, records[0]])


def test_digest_is_independent_of_input_order() -> None:
    records, _, _ = case_inputs("paper")
    forward = section_for("paper", EvidenceKind.PAPER, records=records)
    backward = section_for("paper", EvidenceKind.PAPER, records=list(reversed(records)))
    assert forward.digest() == backward.digest()
