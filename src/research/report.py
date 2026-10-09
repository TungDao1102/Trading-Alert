"""Run report composition for the research runner (Phase 16, plan 16-18, D-27).

Reporting only (L-03): it composes the feasibility lines (plan 16-12) and the plateau section
over the preregistered grid, in that order. Per-point figures come from the existing backtest
report builder (`src.backtest.report.build`); this module defines no metric. It decides
nothing: no marker, no ordering by a value, no selection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from src.backtest import report as backtest_report

from .plateau import PlateauReport, render_plateau

# The summary is a fixed set of existing report figures. The bootstrap interval is not part of
# it, so the seed and the resample count below choose no figure shown; the minimum resample
# count the builder accepts keeps the build cheap.
_SUMMARY_BOOTSTRAP_SEED = 0
_SUMMARY_RESAMPLES = 100


def point_summary(report: backtest_report.UncertaintyReport) -> dict[str, object]:
    """The figures of one grid point, read unchanged from an existing report."""
    r = report.r_distribution
    return {
        "closed_trades": report.counts.trade_count,
        "end_of_data_trades": report.counts.end_of_data_count,
        "mean_r": r.mean,
        "median_r": r.median,
        "std_r": r.std,
        "wins": r.win_count,
        "losses": r.loss_count,
        "observed_max_drawdown_r": report.drawdown_distribution.observed_max_drawdown,
    }


def summarize_trades(
    *,
    experiment_record: Any,
    trade_records: Sequence[Mapping[str, Any]],
    built_at_utc: datetime,
) -> dict[str, object]:
    """Build the existing backtest report over `trade_records` and take its point summary."""
    report = backtest_report.build(
        experiment_record=experiment_record,
        trade_records=trade_records,
        bootstrap_seed=_SUMMARY_BOOTSTRAP_SEED,
        built_at_utc=built_at_utc,
        resamples=_SUMMARY_RESAMPLES,
    )
    return point_summary(report)


def render_run_report(
    *,
    feasibility_lines: Sequence[str],
    plateau: PlateauReport,
) -> list[str]:
    """The printed report after the record lines: feasibility first, then the plateau."""
    return [*feasibility_lines, *render_plateau(plateau)]


__all__ = ["point_summary", "render_run_report", "summarize_trades"]
