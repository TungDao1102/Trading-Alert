"""INCOMPLETE buckets and backtest normalization (Phase 10, plan 10-01, D-02).

Missing fills, 1m coverage gaps, and fallback simulations are counted with an
explicit IncompleteReason - nothing is imputed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from src.analytics.excursion import build_excursion_section, compute_trade_excursion
from src.analytics.inputs import normalize_backtest
from src.analytics.types import (
    AnalyticsInputError,
    EvidenceKind,
    IncompleteReason,
    OutcomeContext,
)

from tests.phase10_helpers import D, load_expected, load_input, make_candles, make_trade_record


def test_missing_1m_candle_is_no_1m_coverage() -> None:
    data = load_input("incomplete_no_1m")
    expected = load_expected("incomplete_no_1m")
    outcome = normalize_backtest([make_trade_record(**data["trade"])]).outcomes[0]
    candles = make_candles(data["candles"])

    excursion = compute_trade_excursion(outcome, candles)
    assert excursion.incomplete_reason is IncompleteReason(expected["incomplete_reason"])
    for name in (
        "mfe_price",
        "mae_price",
        "mfe_r",
        "mae_r",
        "time_to_mfe_s",
        "time_to_mae_s",
        "holding_s",
        "realized_r",
    ):
        assert getattr(excursion, name) is None, name

    section = build_excursion_section(
        [outcome], {"BTCUSDT": candles}, evidence=EvidenceKind.BACKTEST, resamples=100
    )
    assert section.n_outcomes == expected["section"]["n_outcomes"]
    assert section.n_measured == expected["section"]["n_measured"] == 0
    assert section.incomplete == tuple(
        (reason, count) for reason, count in expected["section"]["incomplete"]
    )
    assert section.stat("mfe_price").mean.value is None


def test_duplicate_minute_candle_is_no_1m_coverage() -> None:
    data = load_input("complete_trade")
    outcome = normalize_backtest([make_trade_record(**data["trade"])]).outcomes[0]
    candles = make_candles(data["candles"])
    candles = [*candles, candles[1]]
    excursion = compute_trade_excursion(outcome, candles)
    assert excursion.incomplete_reason is IncompleteReason.NO_1M_COVERAGE


def test_no_fill_fallback_and_absent_risk_cases() -> None:
    data = load_input("incomplete_no_fill")
    expected = load_expected("incomplete_no_fill")
    records = [make_trade_record(**row) for row in data["trades"]]
    outcomes = normalize_backtest(records).outcomes
    candles = {"BTCUSDT": make_candles(data["candles"])}

    for outcome in outcomes:
        want = expected["trades"][outcome.trade_id]
        excursion = compute_trade_excursion(outcome, candles["BTCUSDT"])
        reason = want["incomplete_reason"]
        if reason is not None:
            assert excursion.incomplete_reason is IncompleteReason(reason)
            assert excursion.mfe_price is None
            continue
        # Absent (not zero) risk: price excursions present, R excursions None,
        # and NOT counted as a zero-risk exclusion.
        assert excursion.incomplete_reason is None
        assert excursion.mfe_price == D(want["mfe_price"])
        assert excursion.mae_price == D(want["mae_price"])
        assert excursion.mfe_r is None
        assert excursion.mae_r is None
        assert excursion.r_excluded_zero_risk is False
        assert want["r_excluded_zero_risk"] is False

    section = build_excursion_section(
        outcomes, candles, evidence=EvidenceKind.BACKTEST, resamples=100
    )
    assert section.n_outcomes == expected["section"]["n_outcomes"] == 3
    assert section.n_measured == expected["section"]["n_measured"] == 1
    assert section.n_zero_risk_excluded == expected["section"]["n_zero_risk_excluded"] == 0
    assert section.incomplete == tuple(
        (reason, count) for reason, count in expected["section"]["incomplete"]
    )


def test_reject_records_become_no_trade_records_only() -> None:
    ok = make_trade_record(trade_id="T-OK", direction="LONG")
    rejected = make_trade_record(
        trade_id="T-REJ", outcome_kind="REJECT", reason_code="RISK_BUDGET_EXCEEDED"
    )
    result = normalize_backtest([rejected, ok])
    assert [o.trade_id for o in result.outcomes] == ["T-OK"]
    assert len(result.rejects) == 1
    reject = result.rejects[0]
    assert reject.evidence is EvidenceKind.BACKTEST
    assert reject.reason_code == "RISK_BUDGET_EXCEEDED"
    assert reject.source_id == "T-REJ"


def test_contexts_propagate_onto_outcomes() -> None:
    record = make_trade_record(trade_id="T-CTX")
    context = OutcomeContext(
        intended_entry_price=Decimal("99.50"), regime="BULLISH", vol_regime="HIGH"
    )
    outcome = normalize_backtest([record], {"T-CTX": context}).outcomes[0]
    assert outcome.intended_entry_price == Decimal("99.50")
    assert outcome.regime == "BULLISH"
    assert outcome.vol_regime == "HIGH"
    bare = normalize_backtest([record]).outcomes[0]
    assert bare.intended_entry_price is None
    assert bare.regime is None


def test_invalid_direction_and_duplicate_trade_ids_fail_closed() -> None:
    with pytest.raises(AnalyticsInputError):
        normalize_backtest([make_trade_record(trade_id="T-BAD", direction="SIDEWAYS")])
    with pytest.raises(AnalyticsInputError):
        normalize_backtest(
            [make_trade_record(trade_id="T-DUP"), make_trade_record(trade_id="T-DUP")]
        )
