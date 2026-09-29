"""Lifecycle normalizer tests (Phase 10, plan 10-03, D-02/D-05)."""

from __future__ import annotations

import pytest
from src.analytics.latency import Leg, build_execution_quality
from src.analytics.lifecycle import (
    LifecyclePath,
    normalize_backtest_lifecycle,
    normalize_paper_lifecycle,
)
from src.analytics.types import AnalyticsInputError, EvidenceKind, TradeOutcome
from src.domain.enums import ApprovalResult

from tests.phase10_helpers import D, load_expected, load_input, make_paper_record


def _outcome(
    trade_id: str,
    *,
    entry_kind: str | None,
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
        direction="LONG",
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


def test_backtest_entry_kind_mapping() -> None:
    outcomes = [
        _outcome("A", entry_kind="ENTRY_FILLED", intended="100", entry="100"),
        _outcome("B", entry_kind="PARTIAL_FILL", intended="100", entry="100"),
        _outcome("C", entry_kind="TOUCH_NO_FILL", intended="100"),
        _outcome("D", entry_kind="EXPIRED", intended="100"),
        _outcome("E", entry_kind="INVALIDATION_CANCEL", intended="100"),
    ]
    records = normalize_backtest_lifecycle(outcomes)
    assert [rec.source_id for rec in records] == ["A", "B", "C", "D", "E"]
    assert [rec.entry_filled for rec in records] == [True, True, False, False, False]
    assert [rec.expired_without_fill for rec in records] == [False, False, False, True, False]
    for rec in records:
        assert rec.evidence is EvidenceKind.BACKTEST
        assert rec.path is LifecyclePath.SYSTEM_ONLY
        assert rec.signal_detected_at_utc is None
        assert rec.approved_at_utc is None
        assert rec.order_submitted_at_utc is None
        assert rec.fill_time_utc is None
        assert rec.intended_entry_price == D("100")
    assert records[0].actual_entry_price == D("100")
    assert records[2].actual_entry_price is None


def test_backtest_unknown_entry_kind_fails_closed() -> None:
    with pytest.raises(AnalyticsInputError):
        normalize_backtest_lifecycle([_outcome("A", entry_kind="MYSTERY")])


def test_backtest_missing_entry_kind_is_not_an_entry_order() -> None:
    (rec,) = normalize_backtest_lifecycle([_outcome("A", entry_kind=None)])
    assert rec.entry_filled is None
    assert rec.expired_without_fill is None


def test_backtest_duplicate_trade_id_fails_closed() -> None:
    outcomes = [_outcome("A", entry_kind="EXPIRED"), _outcome("A", entry_kind="EXPIRED")]
    with pytest.raises(AnalyticsInputError):
        normalize_backtest_lifecycle(outcomes)


def test_opportunity_skipped_and_expired_rows_are_retained() -> None:
    data = load_input("opportunity_skipped_expired")
    expected = load_expected("opportunity_skipped_expired")
    paper = [make_paper_record(row) for row in data["records"]]
    lifecycle = normalize_paper_lifecycle(paper)
    assert len(lifecycle) == expected["n_records"] == 2
    for rec, want in zip(lifecycle, expected["lifecycle"], strict=True):
        assert rec.signal_id == want["signal_id"]
        assert rec.path is LifecyclePath(want["path"])
        assert rec.approval_result is ApprovalResult(want["approval_result"])
        assert rec.reason_code == want["reason_code"]
        assert rec.approved_at_utc is None
        assert rec.order_submitted_at_utc is None
        assert rec.fill_time_utc is None
        assert rec.synthetic_lag is False

    section = build_execution_quality(lifecycle, evidence=EvidenceKind.PAPER, resamples=100)
    assert section.n_records == 2
    assert section.leg(Leg.SIGNAL_TO_SEEN).incomplete == tuple(
        (r, c) for r, c in expected["seen_incomplete"]
    )
    # They reach no downstream leg denominator.
    downstream = (
        Leg.DELIVERY_TO_APPROVED,
        Leg.SIGNAL_TO_APPROVED,
        Leg.APPROVED_TO_ORDER,
        Leg.ORDER_TO_FILL,
    )
    for leg in downstream:
        stat = section.leg(leg)
        assert stat.n_measured == expected["downstream_legs_n_measured"]
        assert stat.incomplete == ()
    assert section.fill_rate.denominator == expected["fill_rate"]["denominator"]
    assert section.fill_rate.pct is None
    assert section.expiry_rate.pct is None


def test_paper_duplicate_attribution_fails_closed() -> None:
    data = load_input("opportunity_skipped_expired")
    rows = [make_paper_record(row) for row in data["records"]]
    with pytest.raises(AnalyticsInputError):
        normalize_paper_lifecycle([*rows, rows[0]])
