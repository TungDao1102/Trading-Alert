"""Composed journal-depth report tests (Phase 10, plan 10-08, D-01, D-04, D-05).

RED first: these tests are authored before `src/analytics/report.py` exists. The report
is one pure function of frozen inputs: three fixed EvidenceBlocks (BACKTEST, PAPER, LIVE,
never pooled), stamped with a single digest. Fixture: `tests/fixtures/phase10/report_composite`.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from src.analytics.clock import ClockStart
from src.analytics.inputs import normalize_backtest
from src.analytics.lifecycle import normalize_backtest_lifecycle, normalize_paper_lifecycle
from src.analytics.no_trade import no_trade_from_paper
from src.analytics.report import (
    EvidenceBlock,
    EvidenceInputs,
    ReportInputs,
    build_evidence_block,
    build_journal_depth_report,
)
from src.analytics.stats import r_value
from src.analytics.types import (
    ANALYTICS_SCHEMA_VERSION,
    MIN_RESAMPLES,
    AnalyticsInputError,
    EvidenceKind,
)

from tests.phase10_helpers import (
    load_expected,
    load_input,
    make_candles,
    make_outcome,
    make_paper_record,
    make_trade_record,
    parse_utc,
)

CASE = "report_composite"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def build_clock(raw: dict[str, Any]) -> ClockStart:
    return ClockStart(
        start_utc=parse_utc(raw["start_utc"]),
        source=raw["source"],
        freeze_commit=raw["freeze_commit"],
        commit_author_date=raw["commit_author_date"],
    )


def build_backtest_inputs(raw: dict[str, Any]) -> EvidenceInputs:
    trades = [make_trade_record(**trade) for trade in raw["trades"]]
    normalized = normalize_backtest(trades)
    candles_by_symbol: dict[str, list[Any]] = {}
    for candle in make_candles(raw["candles"]):
        candles_by_symbol.setdefault(candle.symbol, []).append(candle)
    realized = {
        outcome.signal_id: value
        for outcome in normalized.outcomes
        if outcome.signal_id is not None
        and (value := r_value(outcome.realized_pnl, outcome.realized_risk)) is not None
    }
    return EvidenceInputs(
        kind=EvidenceKind.BACKTEST,
        outcomes=normalized.outcomes,
        lifecycle=normalize_backtest_lifecycle(normalized.outcomes),
        no_trades=normalized.rejects,
        candles_by_symbol=candles_by_symbol,
        realized_r_by_signal=realized,
    )


def build_paper_inputs(raw: dict[str, Any]) -> EvidenceInputs:
    records = [make_paper_record(row) for row in raw["records"]]
    return EvidenceInputs(
        kind=EvidenceKind.PAPER,
        lifecycle=normalize_paper_lifecycle(records),
        no_trades=tuple(no_trade_from_paper(records)),
        paper_epoch_ids=tuple(sorted({record.epoch_id for record in records})),
    )


def build_report_inputs(case: str = CASE) -> ReportInputs:
    data = load_input(case)
    return ReportInputs(
        as_of_utc=parse_utc(data["as_of_utc"]),
        backtest=build_backtest_inputs(data["backtest"]),
        paper=build_paper_inputs(data["paper"]),
        live=EvidenceInputs(kind=EvidenceKind.LIVE),
        research_symbols=tuple(data["research_symbols"]),
        clock=build_clock(data["clock"]),
    )


def build_report(case: str = CASE, *, resamples: int = MIN_RESAMPLES, base_seed: int | None = None):  # type: ignore[no-untyped-def]
    data = load_input(case)
    return build_journal_depth_report(
        build_report_inputs(case),
        base_seed=data["base_seed"] if base_seed is None else base_seed,
        resamples=resamples,
    )


def test_tracer_composes_three_kinds_and_digest() -> None:
    report = build_report()
    expected = load_expected(CASE)
    assert report.schema_version == ANALYTICS_SCHEMA_VERSION
    assert [block.kind for block in report.evidence] == [
        EvidenceKind.BACKTEST,
        EvidenceKind.PAPER,
        EvidenceKind.LIVE,
    ]
    assert [block.kind.value for block in report.evidence] == expected["evidence_kinds"]
    backtest, paper, live = report.evidence
    assert backtest.has_data is True
    assert paper.has_data is True
    assert live.has_data is False
    assert backtest.core.n == expected["backtest_core_n"] == 2
    assert backtest.core.n_r_valued == 2
    assert str(backtest.core.mean_r.value) == expected["backtest_mean_r"]
    assert paper.core.n == 0
    assert paper.no_trade.total.all_n == expected["paper_no_trade_total"] == 2
    # LIVE renders as a valid no-data block: n 0 everywhere.
    assert live.core.n == 0
    assert live.excursion.n_outcomes == 0
    assert live.execution_quality.n_records == 0
    assert live.dual_universe.live5_empty is True
    assert live.dual_universe.live5.n == 0
    assert live.dual_universe.research.n == 0
    assert live.no_trade.total.all_n == 0
    assert report.digest() == report.digest()
    assert HEX64.match(report.digest())
    assert report.digest() == expected["report_digest"]


def test_report_carries_injected_time_seed_and_resamples() -> None:
    data = load_input(CASE)
    report = build_report()
    assert report.as_of_utc == parse_utc(data["as_of_utc"])
    assert report.base_seed == data["base_seed"]
    assert report.resamples == MIN_RESAMPLES


def test_empty_evidence_is_a_valid_no_data_block() -> None:
    block = build_evidence_block(
        EvidenceInputs(kind=EvidenceKind.LIVE),
        research_symbols=("BTCUSDT",),
        expected_universe_hash=None,
        base_seed=1,
        resamples=MIN_RESAMPLES,
    )
    assert isinstance(block, EvidenceBlock)
    assert block.kind is EvidenceKind.LIVE
    assert block.has_data is False
    assert block.core.n == 0
    assert block.core.mean_r.value is None
    assert HEX64.match(block.digest())


def test_cross_kind_elements_raise() -> None:
    paper_outcome = make_outcome(evidence="PAPER", trade_id="P-1")
    with pytest.raises(AnalyticsInputError):
        build_evidence_block(
            EvidenceInputs(kind=EvidenceKind.BACKTEST, outcomes=(paper_outcome,)),
            research_symbols=("BTCUSDT",),
            expected_universe_hash=None,
            base_seed=1,
            resamples=MIN_RESAMPLES,
        )
    live_lifecycle = build_paper_inputs(load_input(CASE)["paper"]).lifecycle
    with pytest.raises(AnalyticsInputError):
        build_evidence_block(
            EvidenceInputs(kind=EvidenceKind.LIVE, lifecycle=live_lifecycle),
            research_symbols=("BTCUSDT",),
            expected_universe_hash=None,
            base_seed=1,
            resamples=MIN_RESAMPLES,
        )
    paper_no_trades = build_paper_inputs(load_input(CASE)["paper"]).no_trades
    with pytest.raises(AnalyticsInputError):
        build_evidence_block(
            EvidenceInputs(kind=EvidenceKind.BACKTEST, no_trades=paper_no_trades),
            research_symbols=("BTCUSDT",),
            expected_universe_hash=None,
            base_seed=1,
            resamples=MIN_RESAMPLES,
        )


def test_report_inputs_reject_a_mis_slotted_evidence_kind() -> None:
    data = load_input(CASE)
    with pytest.raises(AnalyticsInputError):
        ReportInputs(
            as_of_utc=parse_utc(data["as_of_utc"]),
            backtest=EvidenceInputs(kind=EvidenceKind.PAPER),
            paper=EvidenceInputs(kind=EvidenceKind.PAPER),
            live=EvidenceInputs(kind=EvidenceKind.LIVE),
            research_symbols=(),
            clock=build_clock(data["clock"]),
        )
