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


# --------------------------------------------------------------------------- #
# Task 2: all eight dimensions, pinned time bases, ordering, buckets, low-n.
# --------------------------------------------------------------------------- #

DIMENSION_ORDER = [
    "symbol",
    "month",
    "quarter",
    "session",
    "direction",
    "volatility_regime",
    "trend_range_regime",
    "strategy_version",
]


def full_outcomes() -> list[TradeOutcome]:
    return make_outcomes(load_input("low_n_slices")["full_outcomes"])


def full_section(
    outcomes: list[TradeOutcome] | None = None, base_seed: int = BASE_SEED
) -> SlicesSection:
    return build_slices(
        full_outcomes() if outcomes is None else outcomes,
        evidence=EvidenceKind.BACKTEST,
        base_seed=base_seed,
        resamples=MIN_RESAMPLES,
    )


def _ratio(pair: list[str] | None) -> Decimal | None:
    if pair is None:
        return None
    return _div(D(pair[0]), D(pair[1]))


def test_vocabulary_and_session_bands_pinned_verbatim() -> None:
    from src.analytics.slices import SESSION_BANDS, SLICE_VOCABULARY_VERSION

    assert SLICE_VOCABULARY_VERSION == "slices/1"
    assert SESSION_BANDS == (("ASIA", 0, 8), ("EUROPE", 8, 16), ("US", 16, 24))
    assert [d.value for d in SliceDimension] == DIMENSION_ORDER


def test_session_boundary_mapping_start_inclusive_end_exclusive() -> None:
    from src.analytics.slices import session_for

    from tests.phase10_helpers import parse_utc

    cases = {
        "2026-01-05T00:00:00+00:00": "ASIA",
        "2026-01-05T07:59:59+00:00": "ASIA",
        "2026-01-05T08:00:00+00:00": "EUROPE",
        "2026-01-05T15:59:59+00:00": "EUROPE",
        "2026-01-05T16:00:00+00:00": "US",
        "2026-01-05T23:59:59+00:00": "US",
    }
    for iso, band in cases.items():
        assert session_for(parse_utc(iso)) == band, iso


def test_dimensions_in_fixed_order_with_all_row_first() -> None:
    section = full_section()
    assert [t.dimension.value for t in section.tables] == DIMENSION_ORDER
    core = compute_core_metrics(
        full_outcomes(), base_seed=BASE_SEED, resamples=MIN_RESAMPLES, ordinal=0
    )
    for table in section.tables:
        assert table.all_row.key == "ALL"
        assert table.display_rows[0] is table.all_row
        assert all(row.key != "ALL" for row in table.rows)
        assert table.all_row.mean_r == core.mean_r
        assert table.all_row.n == core.n == 8


def test_all_dimension_rows_match_hand_computed_fixture() -> None:
    expected = load_expected("low_n_slices")["full"]
    section = full_section()
    want_all = expected["all"]
    for table in section.tables:
        assert table.all_row.n == want_all["n"]
        assert table.all_row.n_r_valued == want_all["n_r_valued"]
        assert table.all_row.incomplete == want_all["incomplete"]
        assert table.all_row.mean_r.value == _ratio(want_all["mean_r"])
        want = expected["dimensions"][table.dimension.value]
        assert table.slice_count == want["slice_count"] == len(table.rows)
        assert table.total_n == want["total_n"]
        assert [row.key for row in table.rows] == [r["key"] for r in want["rows"]]
        for row, want_row in zip(table.rows, want["rows"], strict=True):
            label = f"{table.dimension.value}/{row.key}"
            assert row.n == want_row["n"], label
            assert row.n_r_valued == want_row["n_r_valued"], label
            assert row.incomplete == want_row["incomplete"], label
            assert row.mean_r.value == _ratio(want_row["mean_r"]), label
            assert row.low_n is True, label  # every slice here is far below LOW_N_THRESHOLD


def test_time_bases_month_quarter_from_exit_session_from_entry() -> None:
    section = full_section()
    tables = {t.dimension.value: t for t in section.tables}
    # F3 entered 2026-03-31 but exited 2026-04-01: it belongs to April / Q2 (exit time).
    assert [r.key for r in tables["month"].rows] == ["2026-03", "2026-04", "INCOMPLETE"]
    assert tables["month"].rows[1].n == 4
    assert [r.key for r in tables["quarter"].rows] == ["2026-Q1", "2026-Q2", "INCOMPLETE"]
    # Missing basis time (no exit / no entry) is INCOMPLETE, not UNKNOWN.
    assert [r.key for r in tables["session"].rows] == ["ASIA", "EUROPE", "US", "INCOMPLETE"]
    assert tables["session"].rows[-1].n == 1  # only the no-fill outcome lacks an entry time


def test_regime_tag_mapping_and_unknown_bucket_pinned_last() -> None:
    section = full_section()
    tables = {t.dimension.value: t for t in section.tables}
    trend = tables["trend_range_regime"]
    # BULLISH/BEARISH -> TREND, NEUTRAL -> RANGE, other tags verbatim, absent -> UNKNOWN.
    assert [r.key for r in trend.rows] == ["CHOP", "RANGE", "TREND", "UNKNOWN"]
    assert {r.key: r.n for r in trend.rows} == {"CHOP": 1, "RANGE": 1, "TREND": 4, "UNKNOWN": 2}
    vol = tables["volatility_regime"]
    assert [r.key for r in vol.rows] == ["HIGH", "LOW", "UNKNOWN"]


def test_ordering_ignores_results_best_slice_is_not_promoted() -> None:
    section = full_section()
    tables = {t.dimension.value: t for t in section.tables}
    version = tables["strategy_version"]
    means = {row.key: row.mean_r.value for row in version.rows}
    assert means["v2.1.0"] is not None
    assert means["v2.0.0"] is not None
    assert means["v2.1.0"] > means["v2.0.0"]
    assert version.rows[-1].key == "v2.1.0"  # best-looking slice sorts LAST by key
    symbol = tables["symbol"]
    sym_means = {row.key: row.mean_r.value for row in symbol.rows if row.mean_r.value is not None}
    assert symbol.rows[0].key == "BTCUSDT"
    assert symbol.rows[0].mean_r.value == min(sym_means.values())  # worst-looking sorts first
    best_symbol = max(sym_means, key=lambda k: sym_means[k])
    assert best_symbol == "SOLUSDT"
    assert symbol.rows[0].key != best_symbol


def test_shuffled_input_yields_identical_tables_and_digest() -> None:
    baseline = full_section()
    rng = random.Random(11)
    for _ in range(4):
        shuffled = full_outcomes()
        rng.shuffle(shuffled)
        again = full_section(shuffled)
        assert again.digest() == baseline.digest()
        for a, b in zip(again.tables, baseline.tables, strict=True):
            assert [r.key for r in a.rows] == [r.key for r in b.rows]


def test_untagged_dimension_yields_all_plus_unknown_with_full_count() -> None:
    section = build_slices(
        tracer_outcomes(),
        evidence=EvidenceKind.BACKTEST,
        base_seed=BASE_SEED,
        resamples=MIN_RESAMPLES,
    )
    tables = {t.dimension.value: t for t in section.tables}
    for name in ("volatility_regime", "trend_range_regime"):
        table = tables[name]
        assert table.all_row.key == "ALL"
        assert [row.key for row in table.rows] == ["UNKNOWN"]
        assert table.rows[0].n == table.all_row.n == 7
        assert table.slice_count == 1
    # The tracer set has entry/exit times, so only the no-fill outcome is INCOMPLETE.
    month = tables["month"]
    assert [row.key for row in month.rows] == ["2026-01", "INCOMPLETE"]
    assert month.rows[-1].n == 1


def test_low_n_slices_are_flagged_retained_and_counted() -> None:
    section = full_section()
    for table in section.tables:
        assert all(row.low_n for row in table.rows)
        assert table.slice_count == len(table.rows) > 0
    tables = {t.dimension.value: t for t in section.tables}
    # A slice with zero R-valued trades is retained with an explicit no-estimate row.
    xrp = next(row for row in tables["symbol"].rows if row.key == "XRPUSDT")
    assert xrp.n == 1
    assert xrp.n_r_valued == 0
    assert xrp.mean_r.value is None
    assert xrp.mean_r.interval_absent is True


def test_per_row_seed_is_base_seed_plus_ordinal_and_digest_tracks_seed() -> None:
    section = full_section()
    month = next(t for t in section.tables if t.dimension is SliceDimension.MONTH)
    assert month.all_row.mean_r.seed == BASE_SEED + 0
    assert month.rows[0].mean_r.seed == BASE_SEED + 1  # 2026-03, 2 R-valued
    assert month.rows[1].mean_r.seed == BASE_SEED + 2  # 2026-04, 4 R-valued
    assert full_section().digest() == section.digest()
    assert full_section(base_seed=BASE_SEED + 1).digest() != section.digest()
    assert section.session_bands == (("ASIA", 0, 8), ("EUROPE", 8, 16), ("US", 16, 24))
    assert section.vocabulary_version == "slices/1"
    assert HEX64.match(section.digest())


def test_pinned_full_section_digest() -> None:
    expected = load_expected("low_n_slices")["full"]
    assert expected["section_digest"] is not None
    assert full_section().digest() == expected["section_digest"]
