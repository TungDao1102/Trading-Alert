"""Robustness slice tests (Phase 10, plan 10-04, D-02, JRN-01).

Task 1 tracer: the core metric block and the SYMBOL slice table with the
unsliced ALL row first, low-n rows retained, and favorability-blind ordering.
"""

from __future__ import annotations

import random
import re
from decimal import Decimal

import pytest
from src.analytics.core_metrics import CoreMetrics, compute_core_metrics
from src.analytics.slices import (
    SliceDimension,
    SliceRow,
    SlicesSection,
    build_slices,
)
from src.analytics.types import (
    LOW_N_THRESHOLD,
    MIN_RESAMPLES,
    AnalyticsInputError,
    EvidenceKind,
    TradeOutcome,
)
from src.core._decimal import _div

from tests.phase10_helpers import D, load_expected, load_input, make_outcomes

HEX64 = re.compile(r"^[0-9a-f]{64}$")
BASE_SEED = 20260929


def tracer_outcomes() -> list[TradeOutcome]:
    return make_outcomes(load_input("low_n_slices")["tracer_outcomes"])


def test_tracer_core_metrics_and_symbol_slice() -> None:
    expected = load_expected("low_n_slices")["tracer"]
    outcomes = tracer_outcomes()
    core = compute_core_metrics(outcomes, base_seed=BASE_SEED, resamples=MIN_RESAMPLES, ordinal=0)
    want = expected["all"]
    assert isinstance(core, CoreMetrics)
    assert core.n == want["n"] == 7
    assert core.n_r_valued == want["n_r_valued"] == 6
    assert core.zero_risk_excluded == want["zero_risk_excluded"] == 0
    assert core.incomplete == want["incomplete"] == 1
    assert core.mean_r.value == _div(
        D(want["mean_r_numerator"]), Decimal(want["mean_r_denominator"])
    )
    assert core.mean_r.interval_absent is want["interval_absent"] is False
    assert core.mean_r.n_valued == 6
    assert core.win_rate == _div(
        Decimal(want["win_rate_numerator"]), Decimal(want["win_rate_denominator"])
    )
    assert core.expectancy_r == core.mean_r.value
    assert core.max_drawdown_r == D(want["max_drawdown_r"])
    assert core.loss_streak_max == want["loss_streak_max"] == 1
    assert core.low_n is want["low_n"] is True
    assert 6 < LOW_N_THRESHOLD

    section = build_slices(
        outcomes, evidence=EvidenceKind.BACKTEST, base_seed=BASE_SEED, resamples=MIN_RESAMPLES
    )
    assert isinstance(section, SlicesSection)
    table = section.tables[0]
    assert table.dimension is SliceDimension.SYMBOL
    sym = expected["symbol_table"]
    assert table.slice_count == sym["slice_count"] == 3
    assert table.total_n == sym["total_n"] == 7
    assert [row.key for row in table.rows] == [r["key"] for r in sym["rows"]]
    for row, want_row in zip(table.rows, sym["rows"], strict=True):
        assert row.n == want_row["n"], row.key
        assert row.n_r_valued == want_row["n_r_valued"], row.key
        assert row.low_n is want_row["low_n"], row.key
    assert HEX64.match(section.digest())
    assert table.digest() == sym["digest"]


def test_tracer_all_row_equals_core_metrics_field_by_field() -> None:
    outcomes = tracer_outcomes()
    core = compute_core_metrics(outcomes, base_seed=BASE_SEED, resamples=MIN_RESAMPLES, ordinal=0)
    section = build_slices(
        outcomes, evidence=EvidenceKind.BACKTEST, base_seed=BASE_SEED, resamples=MIN_RESAMPLES
    )
    all_row = section.tables[0].all_row
    assert isinstance(all_row, SliceRow)
    assert all_row.key == "ALL"
    assert all_row.n == core.n
    assert all_row.n_r_valued == core.n_r_valued
    assert all_row.zero_risk_excluded == core.zero_risk_excluded
    assert all_row.incomplete == core.incomplete
    assert all_row.mean_r == core.mean_r
    assert all_row.win_rate == core.win_rate
    assert all_row.expectancy_r == core.expectancy_r
    assert all_row.low_n is core.low_n


def test_tracer_symbol_rows_ascending_regardless_of_input_order() -> None:
    outcomes = tracer_outcomes()
    baseline = build_slices(
        outcomes, evidence=EvidenceKind.BACKTEST, base_seed=BASE_SEED, resamples=MIN_RESAMPLES
    )
    assert [row.key for row in baseline.tables[0].rows] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    rng = random.Random(7)
    for _ in range(3):
        shuffled = list(outcomes)
        rng.shuffle(shuffled)
        again = build_slices(
            shuffled, evidence=EvidenceKind.BACKTEST, base_seed=BASE_SEED, resamples=MIN_RESAMPLES
        )
        assert [row.key for row in again.tables[0].rows] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        assert again.digest() == baseline.digest()


def test_tracer_empty_input_stays_labelled_and_mixed_evidence_raises() -> None:
    empty = build_slices(
        [], evidence=EvidenceKind.PAPER, base_seed=BASE_SEED, resamples=MIN_RESAMPLES
    )
    assert empty.evidence is EvidenceKind.PAPER
    table = empty.tables[0]
    assert table.all_row.n == 0
    assert table.all_row.mean_r.value is None
    assert table.rows == ()
    assert table.slice_count == 0
    assert table.total_n == 0
    with pytest.raises(AnalyticsInputError):
        build_slices(
            tracer_outcomes(),
            evidence=EvidenceKind.LIVE,
            base_seed=BASE_SEED,
            resamples=MIN_RESAMPLES,
        )
