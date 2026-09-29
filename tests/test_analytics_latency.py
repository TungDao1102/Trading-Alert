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

import pytest
from src.analytics.latency import Leg, build_execution_quality
from src.analytics.lifecycle import (
    LifecyclePath,
    LifecycleRecord,
    normalize_backtest_lifecycle,
    normalize_paper_lifecycle,
)
from src.analytics.types import AnalyticsInputError, EvidenceKind, TradeOutcome
from src.domain.enums import ApprovalResult
from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS
from src.paper.journal import PaperRecord

from tests.phase10_helpers import (
    D,
    load_expected,
    load_input,
    make_lifecycle_record,
    make_paper_record,
    parse_utc,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
LATENCY_SRC = Path(__file__).resolve().parent.parent / "src" / "analytics" / "latency.py"


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
    for rate, key in ((section.fill_rate, "fill_rate"), (section.expiry_rate, "expiry_rate")):
        want_rate = expected[key]
        assert rate.numerator == want_rate["numerator"]
        assert rate.denominator == want_rate["denominator"]
        assert rate.pct == D(want_rate["pct"])
    assert section.deviation.price.mean.n_valued == 0
    assert section.deviation.incomplete == tuple(
        (r, c) for r, c in expected["deviation"]["incomplete"]
    )
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


# --------------------------------------------------------------------------- #
# Task 2: fill %, expiry rate, signed entry deviation, backtest normalizer
# --------------------------------------------------------------------------- #


def _outcome(
    trade_id: str,
    *,
    entry_kind: str | None,
    direction: str = "LONG",
    intended: str | None = None,
    entry: str | None = None,
) -> TradeOutcome:
    return TradeOutcome(
        evidence=EvidenceKind.BACKTEST,
        trade_id=trade_id,
        signal_id=f"SIG-{trade_id}",
        strategy_version="v2.0.0",
        parameter_set_hash="a" * 64,
        symbol="BTCUSDT",
        direction=direction,
        entry_kind=entry_kind,
        entry_price=None if entry is None else D(entry),
        entry_time_utc=None,
        exit_kind=None,
        exit_price=None,
        exit_time_utc=None,
        quantity=None,
        realized_pnl=None,
        realized_risk=None,
        fallback_applied=False,
        intended_entry_price=None if intended is None else D(intended),
    )


def _backtest_set() -> list[TradeOutcome]:
    return [
        _outcome("T1", entry_kind="ENTRY_FILLED", intended="100", entry="100.5"),
        _outcome("T2", entry_kind="PARTIAL_FILL", direction="SHORT", intended="200", entry="199"),
        _outcome("T3", entry_kind="EXPIRED", intended="300"),
        _outcome("T4", entry_kind="TOUCH_NO_FILL", intended="400"),
    ]


def test_backtest_fill_and_expiry_rates_and_deviation() -> None:
    records = normalize_backtest_lifecycle(_backtest_set())
    section = build_execution_quality(records, evidence=EvidenceKind.BACKTEST, resamples=100)
    assert section.n_records == 4
    assert (section.fill_rate.numerator, section.fill_rate.denominator) == (2, 4)
    assert section.fill_rate.pct == Decimal("50")
    assert (section.expiry_rate.numerator, section.expiry_rate.denominator) == (1, 4)
    assert section.expiry_rate.pct == Decimal("25")
    # Deviation measured only for filled outcomes with an intended price.
    assert section.deviation.price.mean.n_valued == 2
    assert section.deviation.price.mean.value == Decimal("0.75")  # mean(0.5, 1)
    assert section.deviation.bps.mean.value == Decimal("50")  # both are 50 bps
    assert section.deviation.incomplete == (("NO_FILL_EVENT", 2),)
    # Backtest evidence has no timestamps: every leg is NOT_MEASURED for every record.
    for stat in section.legs:
        assert stat.n_measured == 0
        assert stat.incomplete == (("NOT_MEASURED_FOR_EVIDENCE", 4),)
    assert section.synthetic_lag_seconds is None


def _live_fill(source_id: str, direction: str, intended: str, actual: str) -> LifecycleRecord:
    return make_lifecycle_record(
        source_id=source_id,
        direction=direction,
        order_submitted_at_utc="2026-02-02T08:00:00+00:00",
        entry_filled=True,
        intended_entry_price=intended,
        actual_entry_price=actual,
    )


def test_deviation_sign_long_worse_when_above_short_worse_when_below() -> None:
    records = [
        _live_fill("A-LONG-BETTER", "LONG", "100", "99"),
        _live_fill("B-LONG-WORSE", "LONG", "100", "101"),
        _live_fill("C-SHORT-WORSE", "SHORT", "100", "99"),
        _live_fill("D-SHORT-BETTER", "SHORT", "100", "101"),
    ]
    section = build_execution_quality(records, evidence=EvidenceKind.LIVE, resamples=100)
    price = section.deviation.price
    # -1, +1, +1, -1 (positive = worse for the trader)
    assert price.mean.n_valued == 4
    assert price.minimum == Decimal("-1")
    assert price.maximum == Decimal("1")
    assert price.mean.value == Decimal("0")
    assert section.deviation.bps.maximum == Decimal("100")  # 1 / 100 * 10000
    assert section.deviation.bps.minimum == Decimal("-100")


def test_denominator_zero_gives_none_pct_never_zero() -> None:
    section = build_execution_quality([], evidence=EvidenceKind.LIVE, resamples=100)
    assert section.fill_rate.denominator == 0
    assert section.fill_rate.pct is None
    assert section.expiry_rate.pct is None
    assert section.deviation.price.mean.value is None


def test_paper_deviation_is_incomplete_not_measured_for_evidence() -> None:
    lifecycle = normalize_paper_lifecycle(paper_records())
    section = build_execution_quality(lifecycle, evidence=EvidenceKind.PAPER, resamples=100)
    assert section.deviation.price.mean.n_valued == 0
    assert section.deviation.incomplete == (("NOT_MEASURED_FOR_EVIDENCE", 1),)


def test_deviation_missing_intended_and_missing_fill_price_are_counted() -> None:
    records = [
        make_lifecycle_record(
            source_id="NO-INTENDED",
            order_submitted_at_utc="2026-02-02T08:00:00+00:00",
            entry_filled=True,
            actual_entry_price="100",
        ),
        make_lifecycle_record(
            source_id="NO-FILL-PRICE",
            order_submitted_at_utc="2026-02-02T08:00:00+00:00",
            entry_filled=True,
            intended_entry_price="100",
        ),
    ]
    section = build_execution_quality(records, evidence=EvidenceKind.LIVE, resamples=100)
    assert section.deviation.price.mean.n_valued == 0
    assert section.deviation.incomplete == (
        ("NO_FILL_EVENT", 1),
        ("NO_INTENDED_PRICE", 1),
    )


def test_section_digest_is_deterministic_and_input_order_independent() -> None:
    first = build_execution_quality(
        normalize_backtest_lifecycle(_backtest_set()),
        evidence=EvidenceKind.BACKTEST,
        resamples=100,
    )
    second = build_execution_quality(
        normalize_backtest_lifecycle(list(reversed(_backtest_set()))),
        evidence=EvidenceKind.BACKTEST,
        resamples=100,
    )
    assert first.digest() == second.digest()
    assert first.fill_rate.digest() != first.expiry_rate.digest()
