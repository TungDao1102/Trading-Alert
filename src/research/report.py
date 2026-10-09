"""Run report composition for the research runner (Phase 16, plan 16-18, D-27).

Reporting only (L-03): it composes the feasibility lines (plan 16-12) and the plateau section
over the preregistered grid, in that order. Per-point figures come from the existing backtest
report builder (`src.backtest.report.build`); this module defines no metric. It decides
nothing: no marker, no ordering by a value, no selection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from src.backtest import report as backtest_report
from src.backtest.semantics import ENTRY_FILLED, PARTIAL_FILL

from .plateau import PlateauReport, render_plateau

# The summary is a fixed set of existing report figures. The bootstrap interval is not part of
# it, so the seed and the resample count below choose no figure shown; the minimum resample
# count the builder accepts keeps the build cheap.
_SUMMARY_BOOTSTRAP_SEED = 0
_SUMMARY_RESAMPLES = 100

# The text `src/backtest/lifecycle.py` writes into `coverage_note` for a position held through a
# mark-price hole (both the skipped-span note and the bar-close fallback note start with it). A
# test pins this to the lifecycle's own note text.
MARK_HOLE_MARKER: Final = "mark_price_1m_missing"

_FILLED_ENTRY_KINDS: Final = frozenset({ENTRY_FILLED, PARTIAL_FILL})

# D052-open, O-10 (REV-09): restoring the field is a separate user decision (plan 16-41).
# tests/test_modeled_costs_none_guard.py pins every reader of the field.
COST_FIELD_LINE: Final = (
    "modeled_costs_per_unit is None on v2 filled TradeRecords (D052-open, O-10); no figure uses it"
)


def count_mark_hole_trades(trades: Sequence[Mapping[str, Any]]) -> int:
    """Filled trades whose `coverage_note` records a mark-price hole (OQ-1, report only).

    A filled trade is one with outcome OK and a filled entry; it may have closed or been closed
    by the end of the data. The count is neither classified nor used in any other figure.
    """
    count = 0
    for trade in trades:
        if trade.get("outcome_kind") != "OK" or trade.get("entry_kind") not in _FILLED_ENTRY_KINDS:
            continue
        note = trade.get("coverage_note")
        if isinstance(note, str) and MARK_HOLE_MARKER in note:
            count += 1
    return count


def mark_hole_line(count: int, parameter_set_id: str) -> str:
    """The OQ-1 line: a bare count, unclassified; the methodology is the user's decision."""
    return (
        f"trades held through mark-price holes: {count} (unclassified; methodology is a user "
        "decision before any candidate is evaluated with this metric, OQ-1, D063 item 8) "
        f"parameter_set_id={parameter_set_id}"
    )


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
    mark_hole_trade_counts: Mapping[str, int],
) -> list[str]:
    """The printed report after the record lines.

    Order: feasibility, plateau, the mark-hole count per grid point (grid order of
    `mark_hole_trade_counts`), then the cost-field limitation once.
    """
    return [
        *feasibility_lines,
        *render_plateau(plateau),
        *(mark_hole_line(count, pid) for pid, count in mark_hole_trade_counts.items()),
        COST_FIELD_LINE,
    ]


__all__ = [
    "COST_FIELD_LINE",
    "MARK_HOLE_MARKER",
    "count_mark_hole_trades",
    "mark_hole_line",
    "point_summary",
    "render_run_report",
    "summarize_trades",
]
