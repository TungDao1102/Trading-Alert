"""Execution-quality latency engine tests (Phase 10, plan 10-03, D-02).

Task 1 tracer: paper PaperRecord rows flow normalize_paper_lifecycle ->
build_execution_quality and yield the six fixed-order latency legs with honest
INCOMPLETE accounting and the synthetic-lag label (RESEARCH P1, P2).
"""

from __future__ import annotations

import ast
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.analytics.latency import Leg, build_execution_quality
from src.analytics.lifecycle import LifecyclePath, LifecycleRecord, normalize_paper_lifecycle
from src.analytics.types import AnalyticsInputError, EvidenceKind
from src.domain.enums import ApprovalResult
from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS, AttributionKind
from src.paper.journal import PaperRecord

from tests.phase10_helpers import D, load_expected, load_input, parse_utc

HEX64 = re.compile(r"^[0-9a-f]{64}$")
LATENCY_SRC = Path(__file__).resolve().parent.parent / "src" / "analytics" / "latency.py"


def make_paper_record(row: dict[str, Any]) -> PaperRecord:
    fields = dict(row)
    fields["attribution"] = AttributionKind(fields["attribution"])
    for name in (
        "signal_detected_at_utc",
        "approval_acted_at_utc",
        "order_submitted_at_utc",
        "fill_time_utc",
    ):
        raw = fields[name]
        fields[name] = None if raw is None else parse_utc(raw)
    return PaperRecord(**fields)


def paper_records() -> list[PaperRecord]:
    return [make_paper_record(row) for row in load_input("paper_lifecycle")["records"]]


def test_tracer_paper_lifecycle_to_section() -> None:
    expected = load_expected("paper_lifecycle")
    lifecycle = normalize_paper_lifecycle(paper_records())
    assert len(lifecycle) == expected["n_records"] == 2
    assert [rec.signal_id for rec in lifecycle] == ["SIG-A", "SIG-B"]
    for rec, want in zip(lifecycle, expected["lifecycle"], strict=True):
        assert rec.evidence is EvidenceKind.PAPER
        assert rec.path is LifecyclePath(want["path"])
        assert rec.approval_result is ApprovalResult(want["approval_result"])
        assert rec.synthetic_lag is want["synthetic_lag"]
        assert rec.reason_code == want["reason_code"]
        assert rec.delivery_requested_at_utc is None

    section = build_execution_quality(lifecycle, evidence=EvidenceKind.PAPER, resamples=100)
    assert section.evidence is EvidenceKind.PAPER
    assert section.n_records == 2
    assert tuple(stat.leg for stat in section.legs) == tuple(Leg)
    for stat, want in zip(section.legs, expected["legs"], strict=True):
        assert stat.leg is Leg(want["leg"])
        assert stat.n_measured == want["n_measured"], want["leg"]
        assert stat.incomplete == tuple((r, c) for r, c in want["incomplete"]), want["leg"]
        assert stat.unit == "s"
        if want["mean"] is None:
            assert stat.mean.value is None
        else:
            assert stat.mean.value == D(want["mean"]), want["leg"]
    assert section.synthetic_lag_seconds == expected["synthetic_lag_seconds"] == 30
    assert HEX64.match(section.digest())
    assert section.digest() == expected["section_digest"]


def test_leg_enum_order_matches_ui_spec_e1() -> None:
    assert [leg.value for leg in Leg] == [
        "SIGNAL_TO_SEEN",
        "SIGNAL_TO_DELIVERY",
        "DELIVERY_TO_APPROVED",
        "SIGNAL_TO_APPROVED",
        "APPROVED_TO_ORDER",
        "ORDER_TO_FILL",
    ]


def test_mixed_evidence_kinds_raise() -> None:
    lifecycle = normalize_paper_lifecycle(paper_records())
    live = LifecycleRecord(
        evidence=EvidenceKind.LIVE,
        source_id="SIG-Z",
        signal_id="SIG-Z",
        symbol="BTCUSDT",
        strategy_version="v2.0.0",
        direction=None,
        path=LifecyclePath.SYSTEM_ONLY,
        approval_result=None,
        signal_detected_at_utc=parse_utc("2026-02-02T10:00:00+00:00"),
        delivery_requested_at_utc=None,
        approved_at_utc=None,
        order_submitted_at_utc=None,
        fill_time_utc=None,
        intended_entry_price=None,
        actual_entry_price=None,
        entry_filled=None,
        expired_without_fill=None,
        reason_code="",
        synthetic_lag=False,
        epoch_id=None,
    )
    with pytest.raises(AnalyticsInputError):
        build_execution_quality([*lifecycle, live], evidence=EvidenceKind.PAPER, resamples=100)


def test_synthetic_lag_only_for_paper_and_not_redefined() -> None:
    assert APPROVAL_DELAY_LAG_SECONDS == 30
    tree = ast.parse(LATENCY_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            assert "APPROVAL_DELAY_LAG_SECONDS" not in names
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assert node.target.id != "APPROVAL_DELAY_LAG_SECONDS"
    section = build_execution_quality([], evidence=EvidenceKind.LIVE, resamples=100)
    assert section.synthetic_lag_seconds is None


def test_missing_timestamp_is_never_imputed_as_zero() -> None:
    lifecycle = normalize_paper_lifecycle(paper_records())
    section = build_execution_quality(lifecycle, evidence=EvidenceKind.PAPER, resamples=100)
    seen = section.legs[0]
    assert seen.n_measured == 0
    assert seen.mean.value is None
    assert seen.median is None
    assert seen.p90 is None
    assert seen.mean.value != Decimal(0)
