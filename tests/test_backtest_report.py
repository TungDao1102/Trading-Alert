"""Tests for the Phase 6 uncertainty-first backtest report (plan 06-03).

Per D-04 + BACKTEST_SPEC §10 + METRICS §§1–2: every report carries trade
counts overall and by symbol/quarter/regime/version, mean/median/std of
R, bootstrap expectancy interval (block bootstrap with recorded seed),
drawdown distribution under resampling, stability across time and
symbols, parameter-plateau analysis, baseline comparison
(no-trade + simple-trend), dual-universe slices (research vs live-5),
and intrabar-coverage note. No single headline number is ever accepted.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/backtest/report.py` is implemented.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

PHASE6_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase6"
REPORT_SLICES_DIR = PHASE6_FIXTURES_DIR / "report_slices"


# --------------------------------------------------------------------------- #
# Helpers — load fixture + build a minimal ExperimentRecord for build().
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _make_experiment_record() -> object:
    """Build a minimal ExperimentRecord with 64-hex identity fields.

    The report module only needs the experiment_id field for the digest;
    the other fields are populated so __post_init__ passes.
    """
    from src.backtest.experiment import ExperimentRecord

    # Deterministic 64-hex placeholders.
    return ExperimentRecord(
        experiment_id="0" * 64,
        strategy_version="v2.0.0",
        parameter_set_id="baseline-v2",
        parameter_set_hash="0" * 64,
        data_snapshot_id="0" * 64,
        code_version="06-03-red",
        cost_model_hash="0" * 64,
        time_range_start_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_range_end_utc=datetime(2026, 5, 1, tzinfo=timezone.utc),
        universe_hash="0" * 64,
        run_type="CANDIDATE",
        result_summary_json="{}",
        notes="Phase 6 plan 06-03 report_slices fixture (RED phase).",
    )


def _build_report(
    *,
    experiment_record: object,
    trade_records: Sequence[Mapping[str, object]],
    bootstrap_seed: int,
    resamples: int = 10000,
    probable: Decimal = Decimal("0.1"),
    universe_tags: Mapping[str, Sequence[str]] | None = None,
    baseline_summaries: object | None = None,
) -> object:
    """Call the report builder — fails RED because the module does not exist."""
    from src.backtest.report import build

    return build(
        experiment_record=experiment_record,
        trade_records=trade_records,
        bootstrap_seed=bootstrap_seed,
        resamples=resamples,
        probable=probable,
        universe_tags=universe_tags,
        baseline_summaries=baseline_summaries,
    )


# --------------------------------------------------------------------------- #
# Test 1 — pinned-digest equality: build over golden list → canonical digest.
# --------------------------------------------------------------------------- #


def test_build_returns_report_with_pinned_digest() -> None:
    """Beh. 1: build over the golden trade list returns an
    UncertaintyReport whose canonical digest matches the pinned
    EXPECTED_REPORT_DIGEST.

    Per D-04: every report carries the nine mandatory sections plus the
    pinned digest. Any undeclared semantic change fails here.
    """
    from src.backtest.report import UncertaintyReport

    case_input = _load_input(REPORT_SLICES_DIR)
    expected = _load_expected(REPORT_SLICES_DIR)

    record = _make_experiment_record()
    report = _build_report(
        experiment_record=record,
        trade_records=case_input["trades"],
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )

    assert isinstance(report, UncertaintyReport), (
        f"build() must return UncertaintyReport, got {type(report).__name__}"
    )
    # The pinned digest placeholder becomes a real 64-hex value at GREEN.
    assert expected["EXPECTED_REPORT_DIGEST"] != "PLACEHOLDER_FILLED_AT_GREEN", (
        "expected.json EXPECTED_REPORT_DIGEST must be filled at GREEN"
    )
    assert report.digest() == expected["EXPECTED_REPORT_DIGEST"], (
        f"report digest must match pinned EXPECTED_REPORT_DIGEST: "
        f"{report.digest()} != {expected['EXPECTED_REPORT_DIGEST']}"
    )


# --------------------------------------------------------------------------- #
# Test 2 — seed-stable rebuild: same seed → identical digest.
# --------------------------------------------------------------------------- #


def test_build_seed_stable_rebuild_returns_identical_digest() -> None:
    """Beh. 2: rebuilding the report with the same seed returns an
    identical digest (D-04 reproducibility tripwire).

    Per D-04: the bootstrap seed is recorded on the report; rebuilds
    with the same seed are digest-stable. Unseeded RNG use fails here.
    """
    case_input = _load_input(REPORT_SLICES_DIR)
    record = _make_experiment_record()

    report_a = _build_report(
        experiment_record=record,
        trade_records=case_input["trades"],
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )
    report_b = _build_report(
        experiment_record=record,
        trade_records=case_input["trades"],
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )

    assert report_a.digest() == report_b.digest(), (
        f"same-seed rebuilds must produce identical digest: "
        f"{report_a.digest()} != {report_b.digest()}"
    )


# --------------------------------------------------------------------------- #
# Test 3 — nine-section presence: all sections are populated.
# --------------------------------------------------------------------------- #


def test_build_includes_all_nine_sections() -> None:
    """Beh. 3: build returns an UncertaintyReport with all nine mandatory
    sections: counts/slices, R distribution, bootstrap interval, drawdown
    distribution, stability, plateau, baselines, dual-universe, and
    intrabar coverage (D-04).

    Per D-04: missing-section reports fail the acceptance gate. The
    golden test asserts every section is present and non-empty.
    """
    case_input = _load_input(REPORT_SLICES_DIR)
    record = _make_experiment_record()
    report = _build_report(
        experiment_record=record,
        trade_records=case_input["trades"],
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )

    # The nine mandatory sections.
    required_sections = [
        "counts",
        "r_distribution",
        "expectancy_interval",
        "drawdown_distribution",
        "stability",
        "plateau",
        "baselines",
        "dual_universe",
        "intrabar_coverage",
    ]
    for section in required_sections:
        assert hasattr(report, section), (
            f"report missing required section: {section}"
        )
        value = getattr(report, section)
        assert value is not None, f"report.{section} must not be None"


# --------------------------------------------------------------------------- #
# Test 4 — intrabar-coverage percentages: 100% for both-touched, 0% for fallback.
# --------------------------------------------------------------------------- #


def test_intrabar_coverage_exact_percentages() -> None:
    """Beh. 4: intrabar_coverage reports the exact percentage of
    fallback_applied=False trades (100% for the both-touched fixture
    subset, 0% for the fallback subset).

    Per D-01 + Phase-2 D-09: 1m-missing trades are flagged on the trade
    record with fallback_applied=True; the report must aggregate the
    coverage honestly.
    """
    case_input = _load_input(REPORT_SLICES_DIR)
    record = _make_experiment_record()

    # Both-touched subset (exclude the trade_002 fallback).
    both_touched = [t for t in case_input["trades"] if not t["fallback_applied"]]
    report_both = _build_report(
        experiment_record=record,
        trade_records=both_touched,
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )
    assert Decimal(str(report_both.intrabar_coverage.percent)) == Decimal("100"), (
        f"both-touched subset must report 100% intrabar coverage, "
        f"got {report_both.intrabar_coverage.percent}"
    )

    # Fallback-only subset (only trade_002).
    fallback_only = [t for t in case_input["trades"] if t["fallback_applied"]]
    report_fallback = _build_report(
        experiment_record=record,
        trade_records=fallback_only,
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )
    assert Decimal(str(report_fallback.intrabar_coverage.percent)) == Decimal("0"), (
        f"fallback-only subset must report 0% intrabar coverage, "
        f"got {report_fallback.intrabar_coverage.percent}"
    )


# --------------------------------------------------------------------------- #
# Test 5 — dual-universe presence: research_universe + live5_universe slices.
# --------------------------------------------------------------------------- #


def test_dual_universe_includes_research_and_live5() -> None:
    """Beh. 5: dual_universe contains both research_universe and
    live5_universe slices (BACKTEST_SPEC §10.1).

    Per BACKTEST_SPEC §10.1: a strategy is not accepted solely because
    the broader universe rescues a weak live universe. The report must
    show both universes side by side.
    """
    case_input = _load_input(REPORT_SLICES_DIR)
    record = _make_experiment_record()
    report = _build_report(
        experiment_record=record,
        trade_records=case_input["trades"],
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )

    dual = report.dual_universe
    assert hasattr(dual, "research_universe"), (
        "dual_universe must expose research_universe slice"
    )
    assert hasattr(dual, "live5_universe"), (
        "dual_universe must expose live5_universe slice"
    )
    # Research universe includes every symbol; live-5 includes only the 5 live ones.
    research_symbols = set(dual.research_universe.symbols)
    live5_symbols = set(dual.live5_universe.symbols)
    assert "BTCUSDT" in research_symbols and "BTCUSDT" in live5_symbols, (
        "BTCUSDT must appear in both research_universe and live5_universe"
    )
    assert "DOTUSDT" in research_symbols and "DOTUSDT" not in live5_symbols, (
        "DOTUSDT must appear in research_universe but NOT live5_universe"
    )


# --------------------------------------------------------------------------- #
# Test 6 — empty list returns valid report without interval.
# --------------------------------------------------------------------------- #


def test_build_with_empty_list_returns_valid_report() -> None:
    """Beh. 6: empty trade list yields a valid UncertaintyReport with
    the bootstrap interval absent plus an insufficient-data note.

    Per D-04: a report with zero trades is still a valid report — never
    an error. The interval is absent and a note is attached.
    """
    case_input = _load_input(REPORT_SLICES_DIR)
    record = _make_experiment_record()
    report = _build_report(
        experiment_record=record,
        trade_records=[],
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )

    assert report.counts.trade_count == 0, (
        f"empty list must report 0 trade count, got {report.counts.trade_count}"
    )
    assert report.expectancy_interval is None, (
        "empty list must yield absent expectancy_interval"
    )
    assert report.insufficient_data_note is not None, (
        "empty list must yield a non-None insufficient_data_note"
    )


# --------------------------------------------------------------------------- #
# Test 7 — single trade returns valid report without interval.
# --------------------------------------------------------------------------- #


def test_build_with_single_trade_returns_valid_report_without_interval() -> None:
    """Beh. 7: a single trade yields a valid UncertaintyReport without
    the bootstrap interval (one observation is below the minimum
    threshold).

    Per D-04: fewer than two trades yields a valid report with the
    bootstrap interval absent plus an explicit insufficient-data note.
    """
    case_input = _load_input(REPORT_SLICES_DIR)
    record = _make_experiment_record()
    single_trade = case_input["trades"][:1]
    report = _build_report(
        experiment_record=record,
        trade_records=single_trade,
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )

    assert report.counts.trade_count == 1, (
        f"single trade must report 1 trade count, got {report.counts.trade_count}"
    )
    assert report.expectancy_interval is None, (
        "single-trade report must have absent expectancy_interval"
    )
    assert report.insufficient_data_note is not None, (
        "single-trade report must yield a non-None insufficient_data_note"
    )


# --------------------------------------------------------------------------- #
# Test 8 — zero-R trades counted as neither wins nor losses.
# --------------------------------------------------------------------------- #


def test_zero_r_counted_as_neither_wins_nor_losses() -> None:
    """Beh. 8: trades with R exactly zero are counted in the
    distribution as neither wins nor losses.

    Per D-04: zero-R trades (e.g. EOD exit at entry) are reported
    separately from wins and losses; the win_count + loss_count must
    equal the trade_count minus the zero-R count.
    """
    case_input = _load_input(REPORT_SLICES_DIR)
    record = _make_experiment_record()
    report = _build_report(
        experiment_record=record,
        trade_records=case_input["trades"],
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )

    # trade_004 has realized_pnl == realized_risk (0/0.20) → R = 0.
    expected_zero_r = 1
    expected_wins = sum(
        1
        for t in case_input["trades"]
        if t["realized_risk"] not in (None, "0", "0.0")
        and Decimal(str(t["realized_pnl"])) / Decimal(str(t["realized_risk"])) > 0
    )
    expected_losses = sum(
        1
        for t in case_input["trades"]
        if t["realized_risk"] not in (None, "0", "0.0")
        and Decimal(str(t["realized_pnl"])) / Decimal(str(t["realized_risk"])) < 0
    )

    assert report.r_distribution.zero_r_count == expected_zero_r, (
        f"zero_r_count must equal {expected_zero_r}, "
        f"got {report.r_distribution.zero_r_count}"
    )
    assert report.r_distribution.win_count == expected_wins, (
        f"win_count must equal {expected_wins}, "
        f"got {report.r_distribution.win_count}"
    )
    assert report.r_distribution.loss_count == expected_losses, (
        f"loss_count must equal {expected_losses}, "
        f"got {report.r_distribution.loss_count}"
    )
    # win_count + loss_count + zero_r_count must equal trade_count.
    assert (
        report.r_distribution.win_count
        + report.r_distribution.loss_count
        + report.r_distribution.zero_r_count
    ) == report.counts.trade_count, (
        "win + loss + zero_r must equal trade_count"
    )


# --------------------------------------------------------------------------- #
# Test 9 — bootstrap interval uses seeded random.Random (T-06-06 tripwire).
# --------------------------------------------------------------------------- #


def test_bootstrap_uses_recorded_seed() -> None:
    """Beh. 9: the bootstrap interval is computed from a single seeded
    `random.Random(experiment_seed)` instance; unseeded RNG use fails
    here.

    Per D-04 + T-06-06: the seed is recorded on the report and rebuilds
    are digest-compared. Different seeds must produce different
    intervals.
    """
    case_input = _load_input(REPORT_SLICES_DIR)
    record = _make_experiment_record()

    report_a = _build_report(
        experiment_record=record,
        trade_records=case_input["trades"],
        bootstrap_seed=42,
        universe_tags=case_input["universe_tags"],
    )
    report_b = _build_report(
        experiment_record=record,
        trade_records=case_input["trades"],
        bootstrap_seed=999,
        universe_tags=case_input["universe_tags"],
    )

    # Different seeds must produce different intervals (the seed gates RNG).
    assert report_a.bootstrap_seed == 42
    assert report_b.bootstrap_seed == 999
    assert report_a.expectancy_interval is not None
    assert report_b.expectancy_interval is not None
    assert (
        report_a.expectancy_interval.digest()
        != report_b.expectancy_interval.digest()
    ), (
        "different bootstrap seeds must yield different interval digests"
    )


# --------------------------------------------------------------------------- #
# Test 10 — quarter is derived deterministically from exit_time_utc.
# --------------------------------------------------------------------------- #


def test_quarter_is_derived_deterministically_from_exit_time() -> None:
    """Beh. 10: the quarter key in counts_by_quarter is derived from
    `exit_time_utc` deterministically (e.g. 2026-Q1 from January–March).

    Per D-04: counts must slice by quarter, so the derivation must be
    stable across reruns.
    """
    case_input = _load_input(REPORT_SLICES_DIR)
    record = _make_experiment_record()
    report = _build_report(
        experiment_record=record,
        trade_records=case_input["trades"],
        bootstrap_seed=case_input["bootstrap_seed"],
        universe_tags=case_input["universe_tags"],
    )

    # The fixture spans 2026-Q1 (Jan–Mar) and 2026-Q2 (Apr–Jun).
    quarters = sorted(report.counts.counts_by_quarter.keys())
    assert quarters == ["2026-Q1", "2026-Q2"], (
        f"quarter derivation must yield [2026-Q1, 2026-Q2], got {quarters}"
    )
