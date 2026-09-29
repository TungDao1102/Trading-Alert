"""Metric half of the offline report: Sections 3-10 (Phase 10, plan 10-11, D-02, D-04, D-05).

Pure functions of a `JournalDepthReport` returning lines of Markdown; wording, columns and
formats follow `10-UI-SPEC.md`. Every evidence kind renders in its own table or row group
(BACKTEST, PAPER, LIVE, never pooled). Sections 3 and 4 share ONE M-1 row builder so the two
cannot disagree. A point estimate is always `<value> [<lo>, <hi>] n=<n>`,
`<value> [interval absent] n=<n>` or `no data`; a missing measurement says `no data` or
`INCOMPLETE (<reason>)`, never blank or zero. A dash marks a statistic that is structurally
undefined (a rate has no median), which is distinct from an INCOMPLETE measurement. Rows are
ordered by fixed labels or stable keys, never by result, and nothing is emphasised by
favorability. Paper approval timing carries the SYNTHETIC LAG label and never enters the
LIVE-only delay-bucket table.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from src.analytics.approval_delay import ApprovalDelayBlock, DelayBucketRow
from src.analytics.core_metrics import CoreMetrics
from src.analytics.excursion import EXCURSION_WINDOW_CONVENTION, ExcursionSection
from src.analytics.latency import ExecutionQualitySection, Leg, RateStat
from src.analytics.render_common import (
    NO_DATA,
    SECTION_TITLES,
    evidence_caption,
    fmt_bps,
    fmt_estimate,
    fmt_int,
    fmt_pct,
    fmt_price,
    fmt_r,
    fmt_seconds,
    join_blocks,
    md_cell,
    md_table,
)
from src.analytics.report import (
    EVIDENCE_ORDER,
    EvidenceBlock,
    IncompleteEntry,
    JournalDepthReport,
)
from src.analytics.slices import ALL_KEY, SliceDimension, SliceRow, SliceTable
from src.analytics.stats import is_low_n
from src.analytics.types import (
    LOW_N_THRESHOLD,
    AnalyticsInputError,
    DistStat,
    Estimate,
    EvidenceKind,
    IncompleteReason,
)

__all__ = [
    "DELAY_CLOSING_SENTENCE",
    "DESCRIPTIVE_NOTE",
    "E1_ROW_LABELS",
    "EMPTY_LIVE5_NOTE",
    "EMPTY_RESEARCH_NOTE",
    "EXCURSION_DESCRIPTIVE_NOTE",
    "INTERVAL_ABSENT_NOTE",
    "LOW_N_LEGEND",
    "LOW_N_TOKEN",
    "M1_ROW_LABELS",
    "NO_ITEMS_SENTENCE",
    "SEEN_SENTENCE",
    "SLICE_NOTE",
    "WEAK_UNIVERSE_LINE",
    "X1_ROW_LABELS",
    "render_section_approval_delay",
    "render_section_dual_universe",
    "render_section_execution_quality",
    "render_section_full_report",
    "render_section_incomplete",
    "render_section_mfe_mae",
    "render_section_provenance",
    "render_section_slices",
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


# --------------------------------------------------------------------------- #
# Sections 5-10 (plan 10-11, Task 2)
# --------------------------------------------------------------------------- #

SLICE_NOTE = (
    "Every slice table starts with the unsliced ALL row. "
    "Slices are ordered by key, never by result."
)
DELAY_CLOSING_SENTENCE = "Differences between columns describe selection and timing effects only."
SEEN_SENTENCE = (
    "INCOMPLETE (NO_SEEN_TIMESTAMP): no read-receipt is journaled. "
    "Only delivery-request time is available as a proxy."
)
EXCURSION_DESCRIPTIVE_NOTE = (
    "These distributions are descriptive. They imply no change to take-profit, "
    "stop-loss, entry, or holding rules."
)
NO_ITEMS_SENTENCE = "No incomplete or excluded inputs."

# Fixed E-1 and X-1 row labels, in the fixed UI-SPEC order.
E1_ROW_LABELS: tuple[str, ...] = (
    "Signal created -> seen",
    "Signal created -> delivery requested (proxy)",
    "Delivery requested -> approved",
    "Signal created -> approved",
    "Approved -> order placed",
    "Order placed -> filled (wait-to-fill)",
    "Fill %",
    "Expiry without fill rate",
    "Entry deviation (price, signed; positive = worse)",
    "Entry deviation (bps of intended)",
)
X1_ROW_LABELS: tuple[str, ...] = (
    "MFE (price)",
    "MAE (price)",
    "MFE (R)",
    "MAE (R)",
    "Time to MFE",
    "Time to MAE",
    "Holding duration",
)

_NOT_APPLICABLE = "-"
_INCOMPLETE = "INCOMPLETE"
_HASH_PREFIX_CHARS = 12
_HEX_HASH = re.compile(r"^[0-9a-f]{40,64}$")

FormatFn = Callable[[Decimal | None], str]


def _reason_list(incomplete: tuple[tuple[str, int], ...]) -> str:
    """Reason codes joined by '; ' in sorted order (fixed vocabulary, escaped anyway)."""
    return "; ".join(md_cell(reason) for reason, _ in sorted(incomplete))


def _incomplete_total(incomplete: tuple[tuple[str, int], ...]) -> int:
    return sum(count for _, count in incomplete)


def _incomplete_text(reasons: str) -> str:
    return f"{_INCOMPLETE} ({reasons})"


def _short(text: str) -> str:
    """Full hashes shown as their first 12 hex characters; other text passes md_cell."""
    if _HEX_HASH.match(text):
        return text[:_HASH_PREFIX_CHARS]
    return md_cell(text)


def _low_n(flag: bool) -> str:
    return LOW_N_TOKEN if flag else ""


# ---- Section 5: approval-delay impact ------------------------------------- #


def _delay_r_cell(block: ApprovalDelayBlock, value: str) -> str:
    """`value`, or an INCOMPLETE text when the block holds no R-valued signal."""
    if block.n_r_valued > 0 or not block.incomplete:
        return value
    reasons = [reason for reason, _ in block.incomplete]
    if IncompleteReason.NO_HYPOTHETICAL_OUTCOME.value in reasons:
        return "INCOMPLETE (no hypothetical outcome)"
    return _incomplete_text(_reason_list(block.incomplete))


def _delay_incomplete_cell(block: ApprovalDelayBlock) -> str:
    total = _incomplete_total(block.incomplete)
    if total == 0:
        return fmt_int(0)
    detail = "; ".join(
        f"{md_cell(reason)}: {fmt_int(count)}" for reason, count in sorted(block.incomplete)
    )
    return f"{fmt_int(total)} ({detail})"


def _delay_table(blocks: tuple[ApprovalDelayBlock, ...]) -> list[str]:
    rows = [
        ["Signals (n)", *(fmt_int(block.n_signals) for block in blocks)],
        ["Mean R", *(_delay_r_cell(b, fmt_estimate(b.mean_r, fmt_r)) for b in blocks)],
        ["Expectancy (R)", *(_delay_r_cell(b, fmt_r(b.expectancy_r)) for b in blocks)],
        ["Win rate", *(_delay_r_cell(b, fmt_r(b.win_rate)) for b in blocks)],
        ["INCOMPLETE", *(_delay_incomplete_cell(block) for block in blocks)],
    ]
    return md_table(
        [
            "Metric",
            "System (all valid signals)",
            "User execution (approved only)",
            "Opportunity (skipped/expired)",
        ],
        [":---", ":---", ":---", ":---"],
        rows,
    )


def _bucket_table(rows: tuple[DelayBucketRow, ...]) -> list[str]:
    lines = [
        [
            row.bucket.value,
            fmt_int(row.n),
            fmt_estimate(row.mean_r, fmt_r),
            _low_n(row.low_n),
        ]
        for row in rows
    ]
    return md_table(
        ["Signal-to-approve bucket", "n", "Mean R", "Low-n"],
        [":---", "---:", ":---", ":---"],
        lines,
    )


def _measured_delay_line(measured: DistStat | None) -> str:
    prefix = "Measured signal-to-approve distribution:"
    if measured is None or measured.mean.n_valued == 0:
        return f"{prefix} {NO_DATA}"
    return (
        f"{prefix} n={fmt_int(measured.mean.n_valued)}; "
        f"mean {fmt_estimate(measured.mean, fmt_seconds)}; "
        f"median {fmt_seconds(measured.median)} s; p90 {fmt_seconds(measured.p90)} s"
    )


def render_section_approval_delay(report: JournalDepthReport) -> list[str]:
    """`## 5. Approval-Delay Impact`: three reports side by side; buckets for LIVE only."""
    blocks: list[list[str]] = [[f"## {SECTION_TITLES[4]}"]]
    for index, kind in enumerate(EVIDENCE_ORDER, start=1):
        section = _block_for(report, kind).approval_delay
        parts: list[list[str]] = [
            [f"### 5.{index} {kind.value}"],
            [evidence_caption(kind)],
            [] if section.synthetic_lag_label is None else [md_cell(section.synthetic_lag_label)],
            _delay_table((section.system, section.user_execution, section.opportunity)),
        ]
        if kind is EvidenceKind.LIVE:
            parts.extend(
                [_bucket_table(section.buckets), [_measured_delay_line(section.measured_delay)]]
            )
        blocks.extend(parts)
    blocks.append([DELAY_CLOSING_SENTENCE])
    return join_blocks(blocks)


# ---- Section 6: execution quality ----------------------------------------- #


def _measure_row(
    label: str,
    n_measured: int,
    incomplete: tuple[tuple[str, int], ...],
    mean: Estimate,
    median: Decimal | None,
    p90: Decimal | None,
    fmt: FormatFn,
    unit: str,
    forced_reason: str | None = None,
) -> list[str]:
    """One measurement row: INCOMPLETE with its reasons instead of a number when unmeasured."""
    if n_measured == 0 and forced_reason is not None:
        cells = [_incomplete_text(forced_reason), _INCOMPLETE, _INCOMPLETE]
    elif n_measured == 0 and incomplete:
        cells = [_incomplete_text(_reason_list(incomplete)), _INCOMPLETE, _INCOMPLETE]
    elif n_measured == 0:
        cells = [NO_DATA, NO_DATA, NO_DATA]
    else:
        cells = [fmt_estimate(mean, fmt), fmt(median), fmt(p90)]
    return [
        label,
        fmt_int(n_measured),
        fmt_int(_incomplete_total(incomplete)),
        *cells,
        unit,
    ]


def _rate_row(label: str, rate: RateStat) -> list[str]:
    return [
        label,
        fmt_int(rate.denominator),
        _NOT_APPLICABLE,
        fmt_pct(rate.pct),
        _NOT_APPLICABLE,
        _NOT_APPLICABLE,
        "%",
    ]


def _execution_rows(section: ExecutionQualitySection) -> list[list[str]]:
    rows: list[list[str]] = []
    for label, leg in zip(E1_ROW_LABELS[:6], Leg, strict=True):
        stat = section.leg(leg)
        forced = "NO_SEEN_TIMESTAMP" if leg is Leg.SIGNAL_TO_SEEN else None
        rows.append(
            _measure_row(
                label,
                stat.n_measured,
                stat.incomplete,
                stat.mean,
                stat.median,
                stat.p90,
                fmt_seconds,
                md_cell(stat.unit),
                forced,
            )
        )
    rows.append(_rate_row(E1_ROW_LABELS[6], section.fill_rate))
    rows.append(_rate_row(E1_ROW_LABELS[7], section.expiry_rate))
    deviation = section.deviation
    for label, dist, fmt, unit in (
        (E1_ROW_LABELS[8], deviation.price, fmt_price, "price"),
        (E1_ROW_LABELS[9], deviation.bps, fmt_bps, "bps"),
    ):
        rows.append(
            _measure_row(
                label,
                dist.mean.n_valued,
                deviation.incomplete,
                dist.mean,
                dist.median,
                dist.p90,
                fmt,
                unit,
            )
        )
    return rows


def render_section_execution_quality(report: JournalDepthReport) -> list[str]:
    """`## 6. Execution Quality`: latency legs, rates and entry deviation per evidence kind."""
    blocks: list[list[str]] = [[f"## {SECTION_TITLES[5]}"]]
    for index, kind in enumerate(EVIDENCE_ORDER, start=1):
        block = _block_for(report, kind)
        section = block.execution_quality
        label = block.approval_delay.synthetic_lag_label
        table = md_table(
            ["Leg / metric", "n measured", "n INCOMPLETE", "Mean", "Median", "p90", "Unit"],
            [":---", "---:", "---:", ":---", ":---", ":---", ":---"],
            _execution_rows(section),
        )
        blocks.extend(
            [
                [f"### 6.{index} {kind.value}"],
                [evidence_caption(kind)],
                [md_cell(label)]
                if label is not None and section.synthetic_lag_seconds is not None
                else [],
                table,
                [SEEN_SENTENCE] if index == 1 else [],
            ]
        )
    return join_blocks(blocks)


# ---- Section 7: MFE / MAE -------------------------------------------------- #


def _x1_row(
    label: str,
    stat: DistStat,
    incomplete: tuple[tuple[str, int], ...],
    fmt: FormatFn,
    unit: str,
    first_cell: str | None = None,
) -> list[str]:
    n = stat.mean.n_valued
    if n == 0 and incomplete:
        cells = [_incomplete_text(_reason_list(incomplete)), _INCOMPLETE, _INCOMPLETE]
    elif n == 0:
        cells = [NO_DATA, NO_DATA, NO_DATA]
    else:
        cells = [fmt_estimate(stat.mean, fmt), fmt(stat.median), fmt(stat.p90)]
    return [
        label if first_cell is None else first_cell,
        fmt_int(n),
        *cells,
        unit,
        _low_n(is_low_n(n)),
    ]


_X1_ALIGNS = [":---", "---:", ":---", ":---", ":---", ":---", ":---"]


def _excursion_tables(section: ExcursionSection) -> list[list[str]]:
    measures: tuple[tuple[str, str, FormatFn, str], ...] = (
        (X1_ROW_LABELS[0], "mfe_price", fmt_price, "price"),
        (X1_ROW_LABELS[1], "mae_price", fmt_price, "price"),
        (X1_ROW_LABELS[2], "mfe_r", fmt_r, "R"),
        (X1_ROW_LABELS[3], "mae_r", fmt_r, "R"),
        (X1_ROW_LABELS[4], "time_to_mfe", fmt_seconds, "s"),
        (X1_ROW_LABELS[5], "time_to_mae", fmt_seconds, "s"),
        (X1_ROW_LABELS[6], "holding", fmt_seconds, "s"),
    )
    main = md_table(
        ["Measure", "n", "Mean", "Median", "p90", "Unit", "Low-n"],
        _X1_ALIGNS,
        [
            _x1_row(label, section.stat(name), section.incomplete, fmt, unit)
            for label, name, fmt, unit in measures
        ],
    )
    diagnostics: tuple[tuple[str, DistStat, FormatFn, str], ...] = (
        ("MFE (R) of stop-loss exits", section.mfe_r_of_sl_exits, fmt_r, "R"),
        ("MAE (R) of take-profit exits", section.mae_r_of_tp_exits, fmt_r, "R"),
        ("MFE (R) vs realized R (give-back)", section.give_back, fmt_r, "R"),
        ("Holding duration distribution", section.stat("holding"), fmt_seconds, "s"),
    )
    tables = [main]
    for heading, stat, fmt, unit in diagnostics:
        tables.append(
            md_table(
                [heading, "n", "Mean", "Median", "p90", "Unit", "Low-n"],
                _X1_ALIGNS,
                [_x1_row(heading, stat, (), fmt, unit, first_cell="Distribution")],
            )
        )
    return tables


def render_section_mfe_mae(report: JournalDepthReport) -> list[str]:
    """`## 7. MFE / MAE`: excursion measures and the METRICS section 6 descriptive tables."""
    blocks: list[list[str]] = [[f"## {SECTION_TITLES[6]}"]]
    for index, kind in enumerate(EVIDENCE_ORDER, start=1):
        blocks.extend(
            [[f"### 7.{index} {kind.value}"], [evidence_caption(kind)]]
            + _excursion_tables(_block_for(report, kind).excursion)
        )
    blocks.extend([[EXCURSION_WINDOW_CONVENTION], [EXCURSION_DESCRIPTIVE_NOTE], [LOW_N_LEGEND]])
    return join_blocks(blocks)


# ---- Section 8: robustness slices ------------------------------------------ #

_SLICE_TITLES: dict[SliceDimension, str] = {
    SliceDimension.SYMBOL: "Symbol",
    SliceDimension.MONTH: "Month",
    SliceDimension.QUARTER: "Quarter",
    SliceDimension.SESSION: "Session",
    SliceDimension.DIRECTION: "Direction (long/short)",
    SliceDimension.VOLATILITY_REGIME: "Volatility regime",
    SliceDimension.TREND_RANGE_REGIME: "Trend/range regime",
    SliceDimension.STRATEGY_VERSION: "Strategy version",
}
_VOLATILITY_NOTE = "Volatility regime is UNKNOWN until a derivation lands."


def _slice_table(block: EvidenceBlock, dimension: SliceDimension) -> SliceTable:
    for table in block.slices.tables:
        if table.dimension is dimension:
            return table
    raise AnalyticsInputError(f"{block.kind.value} slices have no {dimension.value} table")


def _slice_line(row: SliceRow, kind: EvidenceKind) -> list[str]:
    key = "ALL (unsliced)" if row.key == ALL_KEY else md_cell(row.key)
    return [
        key,
        fmt_int(row.n),
        fmt_int(row.n_r_valued),
        fmt_estimate(row.mean_r, fmt_r),
        fmt_r(row.win_rate),
        fmt_r(row.expectancy_r),
        _low_n(row.low_n),
        kind.value,
    ]


def _session_note(report: JournalDepthReport) -> str:
    bands = ", ".join(
        f"{md_cell(label)} {start:02d}-{end:02d}"
        for label, start, end in report.provenance.session_bands
    )
    return f"Session bands (UTC hour of entry time): {bands}"


def render_section_slices(report: JournalDepthReport) -> list[str]:
    """`## 8. Robustness Slices`: one table per dimension, ALL row first in every kind group."""
    blocks: list[list[str]] = [[f"## {SECTION_TITLES[7]}"], [SLICE_NOTE]]
    for index, dimension in enumerate(SliceDimension, start=1):
        tables = [
            (kind, _slice_table(_block_for(report, kind), dimension)) for kind in EVIDENCE_ORDER
        ]
        counts = "; ".join(
            f"{kind.value} {fmt_int(table.slice_count)} slices, n={fmt_int(table.total_n)}"
            for kind, table in tables
        )
        rows = [_slice_line(row, kind) for kind, table in tables for row in table.display_rows]
        note: list[str] = []
        if dimension is SliceDimension.SESSION:
            note = [_session_note(report)]
        elif dimension is SliceDimension.VOLATILITY_REGIME:
            note = [_VOLATILITY_NOTE]
        blocks.extend(
            [
                [f"### 8.{index} {_SLICE_TITLES[dimension]}"],
                [f"({counts})"],
                [evidence_caption()],
                note,
                md_table(
                    [
                        "Slice key",
                        "n",
                        "R-valued n",
                        "Mean R [interval]",
                        "Win rate",
                        "Expectancy (R)",
                        "Low-n",
                        "Evidence",
                    ],
                    [":---", "---:", "---:", ":---", "---:", "---:", ":---", ":---"],
                    rows,
                ),
            ]
        )
    blocks.append([LOW_N_LEGEND])
    return join_blocks(blocks)


# ---- Section 9: incomplete and excluded inputs ----------------------------- #


def _ledger_rows(entries: tuple[IncompleteEntry, ...]) -> list[list[str]]:
    return [
        [
            entry.evidence.value,
            md_cell(entry.input_name),
            md_cell(entry.reason),
            fmt_int(entry.count),
        ]
        for entry in entries
    ]


def render_section_incomplete(report: JournalDepthReport, truncations: int) -> list[str]:
    """`## 9. Incomplete and Excluded Inputs`: the ledger in order, counted and never dropped."""
    entries = report.incomplete_ledger
    rows = _ledger_rows(entries)
    if truncations > 0:
        rows.append([_NOT_APPLICABLE, "render", "TEXT_TRUNCATED", fmt_int(truncations)])
    unmatched = sum(
        entry.count for entry in entries if entry.reason == IncompleteReason.UNMATCHED_JOIN.value
    )
    rejected = [
        f"{md_cell(entry.input_name)}: {fmt_int(entry.count)} rows rejected "
        f"({IncompleteReason.MALFORMED_ROW.value}). "
        "The report was produced without them. Fix the input and regenerate."
        for entry in entries
        if entry.reason == IncompleteReason.MALFORMED_ROW.value
    ]
    blocks: list[list[str]] = [[f"## {SECTION_TITLES[8]}"]]
    if rows:
        blocks.append(
            md_table(
                ["Evidence", "Input", "Reason", "Count"],
                [":---", ":---", ":---", "---:"],
                rows,
            )
        )
    else:
        blocks.append([NO_ITEMS_SENTENCE])
    if unmatched > 0:
        blocks.append(
            [
                f"Unmatched: {fmt_int(unmatched)} rows could not be joined to a signal or "
                "order. They are counted, not dropped."
            ]
        )
    blocks.extend([line] for line in rejected)
    return join_blocks(blocks)


# ---- Section 10: provenance ------------------------------------------------- #


def _joined(values: tuple[str, ...]) -> str:
    return ", ".join(md_cell(value) for value in values) or NO_DATA


def _joined_hashes(values: tuple[str, ...]) -> str:
    return ", ".join(_short(value) for value in values) or NO_DATA


def render_section_provenance(report: JournalDepthReport) -> list[str]:
    """`## 10. Provenance`: the P-1 fields in the fixed order; hashes as 12-hex prefixes."""
    provenance = report.provenance
    universe = _block_for(report, EvidenceKind.BACKTEST).dual_universe
    universe_cell = (
        f"{provenance.research_universe_hash[:_HASH_PREFIX_CHARS]} "
        f"({md_cell(provenance.research_universe_status)})"
        if universe.research_symbols
        else NO_DATA
    )
    experiment_rows = [
        [
            f"experiment identity ({experiment.evidence.value})",
            "; ".join(
                (
                    f"experiment_id={_short(experiment.experiment_id)}",
                    f"strategy_version={md_cell(experiment.strategy_version)}",
                    f"parameter_set_id={md_cell(experiment.parameter_set_id)}",
                    f"parameter_set_hash={_short(experiment.parameter_set_hash)}",
                    f"data_snapshot_id={_short(experiment.data_snapshot_id)}",
                    f"code_version={_short(experiment.code_version)}",
                    f"cost_model_hash={_short(experiment.cost_model_hash)}",
                )
            ),
        ]
        for experiment in provenance.experiments
    ] or [["experiment identity", NO_DATA]]
    bands = ", ".join(
        f"{md_cell(label)} {start:02d}-{end:02d}" for label, start, end in provenance.session_bands
    )
    rows: list[list[str]] = [
        ["strategyVersion", _joined(provenance.strategy_versions)],
        ["parameterSetId", _joined(provenance.parameter_set_ids)],
        ["parameterSetHash", _joined_hashes(provenance.parameter_set_hashes)],
        *experiment_rows,
        ["universe hash", universe_cell],
        [
            "dataset/version identifiers",
            f"snapshots: {_joined_hashes(provenance.data_snapshot_ids)}; "
            f"schema: {md_cell(provenance.schema_version)}",
        ],
        ["epoch_id (paper)", _joined(provenance.paper_epoch_ids)],
        ["APPROVAL_DELAY_LAG_SECONDS", fmt_int(provenance.approval_delay_lag_seconds)],
        ["LOW_N_THRESHOLD", fmt_int(provenance.low_n_threshold)],
        ["resamples", fmt_int(provenance.resamples)],
        ["base_seed", fmt_int(provenance.base_seed)],
        ["slice vocabulary version", md_cell(provenance.slice_vocabulary_version)],
        ["session bands", bands],
        ["evidence kinds present", _joined(provenance.evidence_kinds_present)],
    ]
    return join_blocks(
        [
            [f"## {SECTION_TITLES[9]}"],
            md_table(["Field", "Value"], [":---", ":---"], rows),
        ]
    )
