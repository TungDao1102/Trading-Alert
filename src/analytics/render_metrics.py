"""Metric half of the offline report: Sections 3 and 4 (Phase 10, plan 10-11, D-02, D-04, D-05).

Pure functions of a `JournalDepthReport` returning lines of Markdown; wording, columns and
formats follow `10-UI-SPEC.md`. The unsliced Full Report (Section 3) and the dual-universe
view (Section 4) render every evidence kind in its own table (BACKTEST, PAPER, LIVE, never
pooled) from ONE shared M-1 row builder, so the two sections cannot disagree. A point
estimate is always `<value> [<lo>, <hi>] n=<n>`, `<value> [interval absent] n=<n>` or
`no data`; a missing measurement says `no data`, never blank or zero. Rows are ordered by
fixed labels, never by result, and nothing is emphasised by favorability.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.analytics.core_metrics import CoreMetrics
from src.analytics.render_common import (
    NO_DATA,
    SECTION_TITLES,
    evidence_caption,
    fmt_estimate,
    fmt_int,
    fmt_r,
    join_blocks,
    md_cell,
    md_table,
)
from src.analytics.report import EVIDENCE_ORDER, EvidenceBlock, JournalDepthReport
from src.analytics.types import LOW_N_THRESHOLD, AnalyticsInputError, EvidenceKind

__all__ = [
    "DESCRIPTIVE_NOTE",
    "EMPTY_LIVE5_NOTE",
    "EMPTY_RESEARCH_NOTE",
    "INTERVAL_ABSENT_NOTE",
    "LOW_N_LEGEND",
    "LOW_N_TOKEN",
    "M1_ROW_LABELS",
    "WEAK_UNIVERSE_LINE",
    "render_section_dual_universe",
    "render_section_full_report",
]

LOW_N_TOKEN = "LOW_N"
DESCRIPTIVE_NOTE = (
    "All figures are descriptive and carry uncertainty. "
    "Nothing here changes parameters or ranks strategy families."
)
LOW_N_LEGEND = (
    f"{LOW_N_TOKEN}: n < {LOW_N_THRESHOLD}. Flag only; not an acceptance threshold. "
    "The row is not hidden."
)
INTERVAL_ABSENT_NOTE = "interval absent (fewer than 2 R-valued trades)"
EMPTY_LIVE5_NOTE = "Live-5 slice has no rows for this evidence kind. Nothing is imputed or hidden."
EMPTY_RESEARCH_NOTE = (
    "Research slice has no rows for this evidence kind. Nothing is imputed or hidden."
)
WEAK_UNIVERSE_LINE = (
    "Weak live-5 universe: research-universe results alone do not support acceptance "
    "(BACKTEST_SPEC section 10.1)."
)

# The ten fixed M-1 row labels, in the fixed UI-SPEC order.
M1_ROW_LABELS: tuple[str, ...] = (
    "Trades (n)",
    "R-valued trades",
    "Zero-risk excluded",
    "INCOMPLETE",
    "Mean R",
    "Median R",
    "Win rate",
    "Expectancy (R)",
    "Max drawdown (R)",
    "Loss streak (max)",
)
_FIRST_R_BASED_ROW = 4


@dataclass(frozen=True)
class _MetricRow:
    """One M-1 row: label, rendered value, the sample behind it, low-n flag and note."""

    label: str
    value: str
    n: int
    low_n: bool
    note: str


def _zero_risk_sentence(count: int) -> list[str]:
    if count <= 0:
        return []
    return [
        f"Zero-risk excluded: {fmt_int(count)}. These trades have no defined R and are "
        "counted here, not dropped."
    ]


def _empty_kind_sentence(kind: EvidenceKind) -> str:
    return (
        f"No {kind.value} rows exist for this evidence kind. Nothing is imputed, hidden, or pooled."
    )


def _m1_rows(core: CoreMetrics) -> list[_MetricRow]:
    """The shared M-1 row builder used by Sections 3 and 4 (identical numbers, D-02)."""
    n_valued = core.n_r_valued
    mean_note = INTERVAL_ABSENT_NOTE if core.mean_r.interval_absent else ""
    rows = [
        _MetricRow("Trades (n)", fmt_int(core.n), core.n, False, ""),
        _MetricRow("R-valued trades", fmt_int(n_valued), n_valued, False, ""),
        _MetricRow("Zero-risk excluded", fmt_int(core.zero_risk_excluded), n_valued, False, ""),
        _MetricRow("INCOMPLETE", fmt_int(core.incomplete), n_valued, False, ""),
        _MetricRow(
            "Mean R", fmt_estimate(core.mean_r, fmt_r), core.mean_r.n_valued, core.low_n, mean_note
        ),
        _MetricRow("Median R", fmt_r(core.median_r), n_valued, core.low_n, ""),
        _MetricRow("Win rate", fmt_r(core.win_rate), n_valued, core.low_n, ""),
        _MetricRow("Expectancy (R)", fmt_r(core.expectancy_r), n_valued, core.low_n, ""),
        _MetricRow("Max drawdown (R)", fmt_r(core.max_drawdown_r), n_valued, core.low_n, ""),
        _MetricRow("Loss streak (max)", fmt_int(core.loss_streak_max), n_valued, core.low_n, ""),
    ]
    if tuple(row.label for row in rows) != M1_ROW_LABELS:
        raise AnalyticsInputError("M-1 rows drifted from the fixed label order")
    return rows


def _block_for(report: JournalDepthReport, kind: EvidenceKind) -> EvidenceBlock:
    for block in report.evidence:
        if block.kind is kind:
            return block
    raise AnalyticsInputError(f"report has no {kind.value} evidence block")


def _full_report_table(core: CoreMetrics) -> list[str]:
    rows = [
        [row.label, row.value, fmt_int(row.n), LOW_N_TOKEN if row.low_n else "", row.note]
        for row in _m1_rows(core)
    ]
    return md_table(
        ["Metric", "Value", "n", "Low-n", "Note"], [":---", ":---", "---:", ":---", ":---"], rows
    )


def render_section_full_report(report: JournalDepthReport) -> list[str]:
    """`## 3. Full Report (unsliced)`: one M-1 block per evidence kind, never pooled."""
    blocks: list[list[str]] = [[f"## {SECTION_TITLES[2]}"], [DESCRIPTIVE_NOTE]]
    for index, kind in enumerate(EVIDENCE_ORDER, start=1):
        block = _block_for(report, kind)
        blocks.extend(
            [
                [f"### 3.{index} {kind.value}"],
                [evidence_caption(kind)],
                _full_report_table(block.core),
                _zero_risk_sentence(block.core.zero_risk_excluded),
                [LOW_N_LEGEND],
                [] if block.has_data else [_empty_kind_sentence(kind)],
            ]
        )
    return join_blocks(blocks)


def _side_cells(core: CoreMetrics, row: _MetricRow, index: int) -> tuple[str, str, bool]:
    """Value, n and low-n flag for one universe side; an empty slice is `no data` and 0."""
    if core.n == 0:
        return NO_DATA, fmt_int(0), index >= _FIRST_R_BASED_ROW
    return row.value, fmt_int(row.n), row.low_n


def _dual_table(block: EvidenceBlock) -> list[str]:
    view = block.dual_universe
    live5_rows = _m1_rows(view.live5)
    research_rows = _m1_rows(view.research)
    rows: list[list[str]] = []
    for index, label in enumerate(M1_ROW_LABELS):
        live5_value, live5_n, live5_low = _side_cells(view.live5, live5_rows[index], index)
        research_value, research_n, research_low = _side_cells(
            view.research, research_rows[index], index
        )
        rows.append(
            [
                label,
                live5_value,
                live5_n,
                research_value,
                research_n,
                f"{LOW_N_TOKEN if live5_low else '-'} / {LOW_N_TOKEN if research_low else '-'}",
            ]
        )
    return md_table(
        [
            "Metric",
            "Live-5 value",
            "Live-5 n",
            "Research value",
            "Research n",
            "Low-n (Live-5 / Research)",
        ],
        [":---", ":---", "---:", ":---", "---:", ":---"],
        rows,
    )


def _universe_lines(report: JournalDepthReport) -> list[list[str]]:
    view = _block_for(report, EvidenceKind.BACKTEST).dual_universe
    live5 = ", ".join(md_cell(symbol) for symbol in view.live5_symbols)
    research = ", ".join(md_cell(symbol) for symbol in view.research_symbols) or NO_DATA
    universe_hash = view.universe_hash[:12] if view.research_symbols else NO_DATA
    return [
        [f"Live-5: {live5}"],
        [
            f"Research universe: {research} "
            f"(universe hash {universe_hash}; {md_cell(view.universe_status)})"
        ],
    ]


def render_section_dual_universe(report: JournalDepthReport) -> list[str]:
    """`## 4. Dual Universe: Live-5 vs Research`: U-1 tables side by side per evidence kind."""
    blocks: list[list[str]] = [[f"## {SECTION_TITLES[3]}"], *_universe_lines(report)]
    for index, kind in enumerate(EVIDENCE_ORDER, start=1):
        block = _block_for(report, kind)
        view = block.dual_universe
        blocks.extend(
            [
                [f"### 4.{index} {kind.value}"],
                [evidence_caption(kind)],
                _dual_table(block),
                [EMPTY_LIVE5_NOTE] if view.live5.n == 0 else [],
                [EMPTY_RESEARCH_NOTE] if view.research.n == 0 else [],
                [WEAK_UNIVERSE_LINE] if view.weak_live_universe_rejection else [],
                [LOW_N_LEGEND],
            ]
        )
    return join_blocks(blocks)
