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
from datetime import UTC, datetime
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
    """Build a typed ExperimentRecord through the shared factory (plan 14-15).

    The report module only needs the experiment_id field for the digest; the factory
    supplies every typed field, and the id keeps its Phase 6 placeholder value.
    """
    from tests.backtest_case_helpers import make_experiment_record

    return make_experiment_record(
        experiment_id="0" * 64,
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
    built_at_utc: datetime | None = None,
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
        built_at_utc=built_at_utc if built_at_utc is not None else _FIXED_BUILT_AT_UTC,
    )


_FIXED_BUILT_AT_UTC = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)


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
        assert hasattr(report, section), f"report missing required section: {section}"
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
    assert hasattr(dual, "research_universe"), "dual_universe must expose research_universe slice"
    assert hasattr(dual, "live5_universe"), "dual_universe must expose live5_universe slice"
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
    assert report.expectancy_interval is None, "empty list must yield absent expectancy_interval"
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

    Per D-04: zero-R trades (e.g. a breakeven stop) are reported
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

    # trade_004 has realized_pnl == realized_risk (0/0.20) → R = 0. Only closed trades
    # (exit SL or TP2) are in the pool: the END_OF_DATA trade_011 and the plan outcomes are not.
    closed = [t for t in case_input["trades"] if t["exit_kind"] in ("SL", "TP2")]
    expected_zero_r = 1
    expected_wins = sum(
        1
        for t in closed
        if t["realized_risk"] not in (None, "0", "0.0")
        and Decimal(str(t["realized_pnl"])) / Decimal(str(t["realized_risk"])) > 0
    )
    expected_losses = sum(
        1
        for t in closed
        if t["realized_risk"] not in (None, "0", "0.0")
        and Decimal(str(t["realized_pnl"])) / Decimal(str(t["realized_risk"])) < 0
    )

    assert report.r_distribution.zero_r_count == expected_zero_r, (
        f"zero_r_count must equal {expected_zero_r}, got {report.r_distribution.zero_r_count}"
    )
    assert report.r_distribution.win_count == expected_wins, (
        f"win_count must equal {expected_wins}, got {report.r_distribution.win_count}"
    )
    assert report.r_distribution.loss_count == expected_losses, (
        f"loss_count must equal {expected_losses}, got {report.r_distribution.loss_count}"
    )
    # win_count + loss_count + zero_r_count must equal trade_count.
    assert (
        report.r_distribution.win_count
        + report.r_distribution.loss_count
        + report.r_distribution.zero_r_count
    ) == report.counts.trade_count, "win + loss + zero_r must equal trade_count"


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
    assert report_a.expectancy_interval.digest() != report_b.expectancy_interval.digest(), (
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


# --------------------------------------------------------------------------- #
# Nyquist gap-fill (review-fix iteration 1): CR-08, CR-12, WR-05/06/10.
# Distinct synthetic trades/seeds — never the pinned report_slices digest.
# --------------------------------------------------------------------------- #

_GAP_SEED = 777


def _gap_trade(trade_id: str, pnl: str, risk: str, **overrides: object) -> dict:
    """Build one synthetic trade dict shaped for report.build()."""
    trade: dict = {
        "trade_id": trade_id,
        "signal_id": "sig-gap",
        "trade_plan_id": "plan-gap",
        "strategy_version": "v2.0.0",
        "parameter_set_hash": "1" * 64,
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_kind": "ENTRY_FILLED",
        "entry_price": "100.00",
        "entry_time_utc": "2026-01-15T10:00:00+00:00",
        "quantity": "0.1",
        "exit_kind": "TP2",
        "exit_price": "101.00",
        "exit_time_utc": "2026-01-15T11:00:00+00:00",
        "realized_pnl": pnl,
        "realized_risk": risk,
        "gross_pnl": pnl,
        "entry_fee": "0.001",
        "exit_fee": "0.001",
        "funding_amount": "0",
        "slippage_amount": "0.0001",
        "modeled_costs_per_unit": "0.0008",
        "coverage_note": None,
        "fallback_applied": False,
        "outcome_kind": "OK",
        "reason_code": "OK",
        "regime": "TREND_UP",
        "parameter_region": "region_a",
    }
    trade.update(overrides)
    return trade


def _gap_trades_four() -> list:
    """Four synthetic trades with R = 5, -2, 3, 0 (distinct seed domain)."""
    return [
        _gap_trade("gap-t1", "0.50", "0.10"),
        _gap_trade("gap-t2", "-0.20", "0.10"),
        _gap_trade("gap-t3", "0.30", "0.10"),
        _gap_trade("gap-t4", "0", "0.20"),
    ]


def test_cr08_build_requires_explicit_built_at_utc() -> None:
    """CR-08: build() requires explicit built_at_utc (missing/None/naive fail)."""
    from src.backtest.report import build

    record = _make_experiment_record()
    trades = _gap_trades_four()[:2]

    with pytest.raises(TypeError):
        build(  # type: ignore[call-arg]
            experiment_record=record,
            trade_records=trades,
            bootstrap_seed=_GAP_SEED,
        )
    with pytest.raises(AttributeError):  # None has no .tzinfo
        build(
            experiment_record=record,
            trade_records=trades,
            bootstrap_seed=_GAP_SEED,
            built_at_utc=None,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        build(
            experiment_record=record,
            trade_records=trades,
            bootstrap_seed=_GAP_SEED,
            built_at_utc=datetime(2026, 9, 26, 12, 0, 0),
        )


def test_cr12_build_rejects_zero_resamples_and_invalid_probable() -> None:
    """CR-12: resamples=0 / invalid probable fail closed (no bogus [0,0])."""
    from src.backtest.report import ReportBuildError

    record = _make_experiment_record()
    trades = _gap_trades_four()

    for bad_resamples in (0, 50, True, "100"):
        with pytest.raises(ReportBuildError):
            _build_report(
                experiment_record=record,
                trade_records=trades,
                bootstrap_seed=_GAP_SEED,
                resamples=bad_resamples,  # type: ignore[arg-type]
            )
    for bad_probable in (
        Decimal("0"),
        Decimal("-0.1"),
        Decimal("1.5"),
        0.1,
    ):
        with pytest.raises(ReportBuildError):
            _build_report(
                experiment_record=record,
                trade_records=trades,
                bootstrap_seed=_GAP_SEED,
                resamples=100,
                probable=bad_probable,  # type: ignore[arg-type]
            )
    valid = _build_report(
        experiment_record=record,
        trade_records=trades,
        bootstrap_seed=_GAP_SEED,
        resamples=100,
    )
    assert valid.expectancy_interval is not None, (
        "minimum valid resamples=100 must yield an interval"
    )


def test_wr05_non_extreme_coverage_percent_is_exact() -> None:
    """WR-05: 2/3 coverage reports the exact quotient, never truncated 66."""
    from src.core._decimal import _div, _q

    record = _make_experiment_record()
    trades = [
        _gap_trade("gap-c1", "0.50", "0.10"),
        _gap_trade("gap-c2", "0.30", "0.10"),
        _gap_trade(
            "gap-c3",
            "-0.20",
            "0.10",
            fallback_applied=True,
            coverage_note="1m_intrabar_missing",
        ),
    ]
    report = _build_report(
        experiment_record=record,
        trade_records=trades,
        bootstrap_seed=_GAP_SEED,
        resamples=100,
    )
    assert report.intrabar_coverage.percent != Decimal("66"), (
        f"integer-truncated 66 must never appear, got {report.intrabar_coverage.percent}"
    )
    assert report.intrabar_coverage.percent == _div(_q(200), _q(3)), (
        f"2/3 coverage must be exact, got {report.intrabar_coverage.percent}"
    )


def test_wr06_bootstrap_and_drawdown_use_decoupled_rng_streams() -> None:
    """WR-06: drawdown resamples run on seed+1, decoupled from bootstrap means."""
    from src.backtest.report import (
        _quantile,
        _resample_drawdowns,
        _stationary_block_bootstrap_means,
    )

    record = _make_experiment_record()
    trades = _gap_trades_four()
    report = _build_report(
        experiment_record=record,
        trade_records=trades,
        bootstrap_seed=_GAP_SEED,
        resamples=100,
    )
    r_values = [Decimal("5"), Decimal("-2"), Decimal("3"), Decimal("0")]

    means = _stationary_block_bootstrap_means(
        r_values, seed=_GAP_SEED, n_resamples=100, p=Decimal("0.1")
    )
    assert report.expectancy_interval is not None
    assert report.expectancy_interval.lower == _quantile(means, Decimal("0.025")), (
        "expectancy bootstrap must run on the recorded seed"
    )

    drawdowns_plus_one = _resample_drawdowns(
        r_values, seed=_GAP_SEED + 1, n_resamples=100, p=Decimal("0.1")
    )
    assert report.drawdown_distribution.resampled_p50_max_drawdown == _quantile(
        drawdowns_plus_one, Decimal("0.50")
    ), "drawdown stage must run on seed+1, not the shared seed stream"

    drawdowns_same_seed = _resample_drawdowns(
        r_values, seed=_GAP_SEED, n_resamples=100, p=Decimal("0.1")
    )
    assert drawdowns_same_seed != drawdowns_plus_one, (
        "test premise: seeds 777/778 must diverge on this data"
    )


def test_wr10_risk_zero_trades_counted_and_surfaced_in_note() -> None:
    """WR-10: risk-zero trades are counted and surfaced in the data note."""
    record = _make_experiment_record()
    trades = [
        _gap_trade("gap-z1", "0.50", "0.10"),
        _gap_trade("gap-z2", "0.00", "0"),
    ]
    report = _build_report(
        experiment_record=record,
        trade_records=trades,
        bootstrap_seed=_GAP_SEED,
        resamples=100,
    )
    assert report.counts.trade_count == 2
    counted = (
        report.r_distribution.win_count
        + report.r_distribution.loss_count
        + report.r_distribution.zero_r_count
    )
    assert counted == 1, "only the risk-bearing trade enters the R distribution"
    assert report.insufficient_data_note is not None
    assert "1 trade(s) excluded from the R distribution" in (report.insufficient_data_note), (
        f"risk-zero exclusion must be surfaced, got {report.insufficient_data_note!r}"
    )
    assert "realized_risk=0" in report.insufficient_data_note


# --------------------------------------------------------------------------- #
# Plan 14-11 (D-34, D-37, D-21): only closed filled trades are trades.
# --------------------------------------------------------------------------- #


def _end_of_data_trade(trade_id: str, pnl: str, risk: str, **overrides: object) -> dict:
    """A position still open when the data ended: force-closed, never a real exit."""
    return _gap_trade(trade_id, pnl, risk, exit_kind="END_OF_DATA", **overrides)


def _plan_outcome(trade_id: str, entry_kind: str, **overrides: object) -> dict:
    """A plan that never filled: no entry, no exit, no PnL."""
    trade = _gap_trade(
        trade_id,
        "0",
        "0",
        entry_kind=entry_kind,
        entry_price=None,
        entry_time_utc=None,
        quantity=None,
        exit_kind=None,
        exit_price=None,
        exit_time_utc=None,
        realized_pnl=None,
        realized_risk=None,
        gross_pnl=None,
        regime=None,
    )
    trade.update(overrides)
    return trade


def _mixed_outcomes() -> list:
    """3 SL, 2 TP2, 1 END_OF_DATA, 2 EXPIRED, 1 INVALIDATION_CANCEL, 1 REJECT."""
    return [
        _gap_trade("m-sl1", "-0.10", "0.10", exit_kind="SL"),
        _gap_trade("m-sl2", "-0.10", "0.10", exit_kind="SL"),
        _gap_trade("m-sl3", "-0.10", "0.10", exit_kind="SL"),
        _gap_trade("m-tp1", "0.20", "0.10", exit_kind="TP2"),
        _gap_trade("m-tp2", "0.30", "0.10", exit_kind="TP2"),
        _end_of_data_trade("m-eod", "9.00", "0.10"),
        _plan_outcome("m-exp1", "EXPIRED"),
        _plan_outcome("m-exp2", "EXPIRED"),
        _plan_outcome("m-inv", "INVALIDATION_CANCEL"),
        _plan_outcome("m-rej", "REJECT", outcome_kind="REJECT", reason_code="CLUSTER_CAP_REJECT"),
    ]


def _mixed_report() -> object:
    return _build_report(
        experiment_record=_make_experiment_record(),
        trade_records=_mixed_outcomes(),
        bootstrap_seed=_GAP_SEED,
        resamples=100,
    )


def test_trade_count_and_r_distribution_cover_only_closed_filled_trades() -> None:
    report = _mixed_report()

    assert report.counts.trade_count == 5
    r = report.r_distribution
    assert (r.win_count, r.loss_count, r.zero_r_count) == (2, 3, 0)
    # The END_OF_DATA trade (R = 90) is not in the pool.
    assert r.max == Decimal("3")
    assert r.min == Decimal("-1")
    assert report.baselines.candidate_trade_count == 5
    assert sum(report.counts.counts_by_symbol.values()) == 5
    assert sum(report.counts.counts_by_regime.values()) == 5


def test_end_of_data_count_is_separate_and_plan_outcome_counts_are_by_entry_kind() -> None:
    counts = _mixed_report().counts

    assert counts.end_of_data_count == 1
    assert counts.plan_outcome_counts == {
        "EXPIRED": 2,
        "INVALIDATION_CANCEL": 1,
        "REJECT": 1,
    }
    assert list(counts.plan_outcome_counts) == sorted(counts.plan_outcome_counts)


def test_non_fills_alone_leave_the_trade_floor_at_zero() -> None:
    plans = [_plan_outcome(f"p-{i}", "EXPIRED") for i in range(40)]
    report = _build_report(
        experiment_record=_make_experiment_record(),
        trade_records=plans,
        bootstrap_seed=_GAP_SEED,
        resamples=100,
    )

    assert report.counts.trade_count == 0
    assert report.counts.plan_outcome_counts == {"EXPIRED": 40}
    assert report.expectancy_interval is None


def test_end_of_data_trades_never_enter_the_stability_or_dual_universe_slices() -> None:
    trades = [
        _gap_trade("s-1", "0.20", "0.10", exit_kind="TP2"),
        _gap_trade("s-2", "-0.10", "0.10", exit_kind="SL"),
        _end_of_data_trade("s-eod", "5.00", "0.10"),
    ]
    report = _build_report(
        experiment_record=_make_experiment_record(),
        trade_records=trades,
        bootstrap_seed=_GAP_SEED,
        resamples=100,
        universe_tags={"BTCUSDT": ["research_universe", "live5_universe"]},
    )

    assert sum(s.trade_count for s in report.stability.slices) == 2
    assert report.dual_universe.research_universe.trade_count == 2
    assert report.dual_universe.live5_universe.trade_count == 2


def test_regime_slice_is_keyed_by_the_record_regime_and_unknown_only_when_none() -> None:
    trades = [
        _gap_trade("r-1", "0.20", "0.10", exit_kind="TP2", regime="BULLISH"),
        _gap_trade("r-2", "-0.10", "0.10", exit_kind="SL", regime="BULLISH"),
        _gap_trade("r-3", "-0.10", "0.10", exit_kind="SL", regime="BEARISH"),
        _gap_trade("r-4", "0.30", "0.10", exit_kind="TP2", regime=None),
    ]
    report = _build_report(
        experiment_record=_make_experiment_record(),
        trade_records=trades,
        bootstrap_seed=_GAP_SEED,
        resamples=100,
    )

    assert report.counts.counts_by_regime == {"BEARISH": 1, "BULLISH": 2, "UNKNOWN": 1}


def test_plateau_section_is_a_fixed_not_computed_structure_for_any_input() -> None:
    from src.backtest.report import PlateauSection

    regions = [
        _gap_trade("g-a", "0.20", "0.10", exit_kind="TP2", parameter_region="region_a"),
        _gap_trade("g-b", "-0.10", "0.10", exit_kind="SL", parameter_region="region_b"),
        _gap_trade("g-c", "0.30", "0.10", exit_kind="TP2", parameter_region="region_c"),
    ]
    inputs = [[], regions, _mixed_outcomes(), _gap_trades_four()]
    plateaus = [
        _build_report(
            experiment_record=_make_experiment_record(),
            trade_records=trades,
            bootstrap_seed=_GAP_SEED,
            resamples=100,
        ).plateau
        for trades in inputs
    ]

    for plateau in plateaus:
        assert isinstance(plateau, PlateauSection)
        assert plateau.status == "NOT_COMPUTED"
        assert plateau.note == "not computed (BKTS-03 pending)"
        assert not hasattr(plateau, "regions")
        assert not hasattr(plateau, "isolated_optimum_warnings")
    assert len({plateau.digest() for plateau in plateaus}) == 1


def test_intrabar_coverage_counts_fallback_over_closed_and_end_of_data_trades() -> None:
    trades = [
        _gap_trade("i-1", "0.20", "0.10", exit_kind="TP2"),
        _gap_trade("i-2", "-0.10", "0.10", exit_kind="SL", fallback_applied=True),
        _end_of_data_trade("i-3", "0.10", "0.10", fallback_applied=True),
        _end_of_data_trade("i-4", "0.10", "0.10"),
        _plan_outcome("i-5", "EXPIRED"),
    ]
    report = _build_report(
        experiment_record=_make_experiment_record(),
        trade_records=trades,
        bootstrap_seed=_GAP_SEED,
        resamples=100,
    )

    coverage = report.intrabar_coverage
    assert coverage.closed_trades == 2
    assert coverage.end_of_data_trades == 2
    assert coverage.total_trades == 4
    assert coverage.fallback_count == 2
    assert coverage.percent == Decimal("50")


def test_a_filled_record_with_a_v1_exit_kind_is_refused() -> None:
    from src.backtest.report import ReportBuildError

    for bad_exit in ("TP1", "EOD", None, "MYSTERY"):
        with pytest.raises(ReportBuildError):
            _build_report(
                experiment_record=_make_experiment_record(),
                trade_records=[_gap_trade("v-1", "0.20", "0.10", exit_kind=bad_exit)],
                bootstrap_seed=_GAP_SEED,
                resamples=100,
            )


def test_the_mixed_report_is_deterministic_and_input_order_independent() -> None:
    forward = _mixed_report()
    reverse = _build_report(
        experiment_record=_make_experiment_record(),
        trade_records=list(reversed(_mixed_outcomes())),
        bootstrap_seed=_GAP_SEED,
        resamples=100,
    )

    assert forward.digest() == _mixed_report().digest()
    assert forward.counts.digest() == reverse.counts.digest()


def test_the_golden_fixture_counts_closed_trades_end_of_data_and_plan_outcomes_apart() -> None:
    case_input = _load_input(REPORT_SLICES_DIR)
    report = _build_report(
        experiment_record=_make_experiment_record(),
        trade_records=case_input["trades"],
        bootstrap_seed=case_input["bootstrap_seed"],
        resamples=case_input["resamples"],
        probable=Decimal(case_input["probable"]),
        universe_tags=case_input["universe_tags"],
    )

    assert len(case_input["trades"]) == 15
    assert report.counts.trade_count == 10
    assert report.counts.end_of_data_count == 1
    assert report.counts.plan_outcome_counts == {
        "EXPIRED": 2,
        "INVALIDATION_CANCEL": 1,
        "REJECT": 1,
    }
    assert report.plateau.status == "NOT_COMPUTED"
