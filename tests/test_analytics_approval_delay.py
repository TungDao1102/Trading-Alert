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
    DelayBucket,
    build_approval_delay,
    delay_bucket_for,
)
from src.analytics.lifecycle import LifecyclePath, LifecycleRecord
from src.analytics.types import AnalyticsInputError, EvidenceKind
from src.domain.enums import ApprovalResult
from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS

from tests.phase10_helpers import D, load_expected, load_input, make_lifecycle_record

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
APPROVAL_DELAY_SRC = SRC_DIR / "analytics" / "approval_delay.py"
PAPER_ATTRIBUTION_SRC = SRC_DIR / "paper" / "attribution.py"
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


# --------------------------------------------------------------------------- #
# Task 2: LIVE-only delay buckets and measured-delay calibration evidence.
# --------------------------------------------------------------------------- #

BUCKET_ORDER = (
    DelayBucket.LT_1M,
    DelayBucket.M1_TO_5,
    DelayBucket.M5_TO_30,
    DelayBucket.GE_30M,
)


def live_section() -> ApprovalDelaySection:
    return section_for("live", EvidenceKind.LIVE)


@pytest.mark.parametrize(
    ("delay", "bucket"),
    [
        ("0", DelayBucket.LT_1M),
        ("30", DelayBucket.LT_1M),
        ("59.999999", DelayBucket.LT_1M),
        ("60", DelayBucket.M1_TO_5),
        ("90", DelayBucket.M1_TO_5),
        ("299", DelayBucket.M1_TO_5),
        ("300", DelayBucket.M5_TO_30),
        ("1799", DelayBucket.M5_TO_30),
        ("1800", DelayBucket.GE_30M),
        ("86400", DelayBucket.GE_30M),
        ("-0.000001", None),
    ],
)
def test_delay_bucket_boundaries(delay: str, bucket: DelayBucket | None) -> None:
    assert delay_bucket_for(D(delay)) is bucket


def test_delay_bucket_labels_and_order_are_fixed() -> None:
    assert [b.value for b in DelayBucket] == ["<1m", "1-5m", "5-30m", ">=30m"]
    assert tuple(DelayBucket) == BUCKET_ORDER


def test_live_buckets_counts_and_fixed_order() -> None:
    expected = load_expected("approval_delay_three_reports")["live"]
    section = live_section()
    assert tuple(row.bucket for row in section.buckets) == BUCKET_ORDER
    assert [row.n for row in section.buckets] == [1, 2, 2, 1]
    for row, want in zip(section.buckets, expected["buckets"], strict=True):
        assert row.bucket.value == want["bucket"]
        assert row.n == want["n"]
        assert row.n_r_valued == want["n_r_valued"]
        assert row.mean_r.value == D(want["mean_r"])
        assert row.low_n is want["low_n"]
        assert row.incomplete == tuple((r, c) for r, c in want["incomplete"])
        assert HEX64.match(row.digest())
    assert_block(section.system, expected["system"])
    assert_block(section.user_execution, expected["user_execution"])
    assert_block(section.opportunity, expected["opportunity"])
    assert section.synthetic_lag_seconds is None
    assert section.synthetic_lag_label is None


def test_live_measured_delay_is_calibration_evidence() -> None:
    expected = load_expected("approval_delay_three_reports")["live"]["measured_delay"]
    measured = live_section().measured_delay
    assert measured is not None
    assert measured.n == expected["n"] == 6
    assert measured.median == D(expected["median"])
    assert measured.minimum == D(expected["minimum"])
    assert measured.maximum == D(expected["maximum"])
    total, count = expected["mean_sum_over_n"]
    assert measured.mean.value is not None
    assert abs(measured.mean.value - D(total) / D(count)) < D("0.000001")


def test_live_section_digest_is_pinned() -> None:
    section = live_section()
    assert section.delay_incomplete == ()
    assert HEX64.match(section.digest())
    want = load_expected("approval_delay_three_reports")["live"]["section_digest"]
    assert section.digest() == want


def test_paper_section_digest_is_repinned_after_bucket_fields() -> None:
    want = load_expected("approval_delay_three_reports")["paper"]["section_digest"]
    assert paper_section().digest() == want


def test_live_returns_four_rows_even_when_buckets_are_empty() -> None:
    records, _, _ = case_inputs("live")
    only_slow = [r for r in records if r.source_id == "LIVE-6"]
    section = section_for("live", EvidenceKind.LIVE, records=only_slow)
    assert tuple(row.bucket for row in section.buckets) == BUCKET_ORDER
    assert [row.n for row in section.buckets] == [0, 0, 0, 1]
    empty = section.buckets[0]
    assert empty.n_r_valued == 0
    assert empty.mean_r.value is None
    assert empty.low_n is True
    assert empty.incomplete == ()


def test_paper_evidence_has_no_buckets_and_keeps_synthetic_label() -> None:
    records, _, _ = case_inputs("live")
    paper = [
        make_lifecycle_record(
            evidence=EvidenceKind.PAPER,
            source_id=r.source_id,
            signal_id=r.signal_id,
            path=r.path,
            approval_result=r.approval_result,
            signal_detected_at_utc=r.signal_detected_at_utc,
            approved_at_utc=r.approved_at_utc,
            synthetic_lag=True,
        )
        for r in records
    ]
    section = section_for("live", EvidenceKind.PAPER, records=paper)
    assert section.buckets == ()
    assert section.measured_delay is None
    assert section.delay_incomplete == ()
    assert section.synthetic_lag_seconds == 30
    assert section.synthetic_lag_label == SYNTHETIC_LAG_LABEL


def test_backtest_evidence_has_neither_label_nor_buckets() -> None:
    records = [
        make_lifecycle_record(
            evidence=EvidenceKind.BACKTEST,
            source_id="T-1",
            signal_id="SIG-T1",
            path=LifecyclePath.SYSTEM_ONLY,
            entry_filled=True,
        ),
        make_lifecycle_record(
            evidence=EvidenceKind.BACKTEST,
            source_id="T-2",
            signal_id=None,
            path=LifecyclePath.SYSTEM_ONLY,
            entry_filled=False,
        ),
    ]
    section = build_approval_delay(
        records,
        evidence=EvidenceKind.BACKTEST,
        realized_r_by_signal={"SIG-T1": D("1.0")},
        hypothetical_r_by_signal={},
        base_seed=SEED,
        resamples=RESAMPLES,
    )
    assert section.buckets == ()
    assert section.measured_delay is None
    assert section.synthetic_lag_seconds is None
    assert section.synthetic_lag_label is None
    assert section.system.n_signals == 2
    assert section.system.n_r_valued == 1
    assert section.system.incomplete == (("NO_FILL_EVENT", 1),)


def test_negative_and_unmatched_delays_are_counted_not_bucketed() -> None:
    negative = make_lifecycle_record(
        source_id="NEG",
        signal_id="NEG",
        path=LifecyclePath.USER_EXECUTED,
        approval_result=ApprovalResult.APPROVED,
        signal_detected_at_utc="2026-03-03T08:00:00+00:00",
        approved_at_utc="2026-03-03T07:59:00+00:00",
    )
    no_signal_time = make_lifecycle_record(
        source_id="NOSIG",
        signal_id="NOSIG",
        path=LifecyclePath.USER_EXECUTED,
        approval_result=ApprovalResult.APPROVED,
        approved_at_utc="2026-03-03T09:00:00+00:00",
    )
    section = build_approval_delay(
        [negative, no_signal_time],
        evidence=EvidenceKind.LIVE,
        realized_r_by_signal={},
        hypothetical_r_by_signal={},
        base_seed=SEED,
        resamples=RESAMPLES,
    )
    assert [row.n for row in section.buckets] == [0, 0, 0, 0]
    assert section.delay_incomplete == (("NEGATIVE_INTERVAL", 1), ("UNMATCHED_JOIN", 1))
    assert section.measured_delay is not None
    assert section.measured_delay.n == 0


def test_measured_delay_uses_approved_live_rows_only() -> None:
    section = live_section()
    assert section.measured_delay is not None
    # LIVE-7 (skipped opportunity) has no approval time and is not a delay sample.
    assert section.measured_delay.n == 6


def test_paper_constant_is_unchanged() -> None:
    assert APPROVAL_DELAY_LAG_SECONDS == 30
    text = PAPER_ATTRIBUTION_SRC.read_text(encoding="utf-8")
    assert "APPROVAL_DELAY_LAG_SECONDS: int = 30" in text
