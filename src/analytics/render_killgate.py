"""Governance half of the offline report: header, Kill Gate and Evidence Overview (plan 10-10).

Pure functions of a `JournalDepthReport` returning lines of Markdown. Wording, table columns
and formats follow `10-UI-SPEC.md`. INSUFFICIENT_EDGE is presented as a calm, valid terminal
outcome with the same visual weight as every other state; PASSING_CANDIDATE is explicitly
non-authorizing; no state ever enables live trading. Emphasis never encodes favorability and
no row is ordered by result. All sourced text passes `md_cell`.
"""

from __future__ import annotations

from types import MappingProxyType

from src.analytics.gates import GATE_IDS, GATE_LABELS
from src.analytics.killgate import KillGateVerdict
from src.analytics.killgate_guard import not_concluded_line
from src.analytics.no_trade import NoTradeCategory, NoTradeRow, NoTradeSection
from src.analytics.render_common import (
    DISPLAY_TZ_NAME,
    NO_DATA,
    READ_ONLY_STATEMENT,
    SECTION_TITLES,
    TIMEZONE_NOTE,
    evidence_caption,
    fmt_display,
    fmt_int,
    fmt_months,
    fmt_utc,
    join_blocks,
    md_cell,
    md_table,
)
from src.analytics.report import EVIDENCE_ORDER, FamilyGateRow, JournalDepthReport
from src.analytics.types import ANALYTICS_SCHEMA_VERSION, AnalyticsInputError, EvidenceKind
from src.domain.enums import KillGateState

__all__ = [
    "ENABLEMENT_CLOSING",
    "GENERATOR_NAME",
    "STATE_SENTENCES",
    "STICKY_NOTE",
    "render_header",
    "render_section_evidence_overview",
    "render_section_kill_gate",
]

GENERATOR_NAME = "src.analytics.cli"
# The em dash is the one non-ASCII character permitted, and only inside the banner line.
_EM_DASH = chr(0x2014)

# One fixed sentence per state (UI-SPEC Copywriting Contract). The first two carry
# placeholders filled by `_banner`; the terminal sentence is fully fixed.
STATE_SENTENCES: MappingProxyType[KillGateState, str] = MappingProxyType(
    {
        KillGateState.WITHIN_BUDGET: (
            "Research budget is not exhausted ({n} of 3 families tested, {m} of 6 months "
            "elapsed). Keep researching. Live trading stays disabled."
        ),
        KillGateState.PASSING_CANDIDATE: (
            "A family has a recorded passing decision ({decision_ref}). This records that "
            "evidence exists. It does not authorize live trading; a separate decision record "
            "is required."
        ),
        KillGateState.INSUFFICIENT_EDGE: (
            "NO_TRADE / INSUFFICIENT EDGE. Three or more independently specified families "
            "were tested under the frozen methodology, at least six months have elapsed, and "
            "none passed. This is a valid terminal outcome, not an error. Live trading stays "
            "disabled and new strategy families are not registered until a new evidence-backed "
            "question is approved by an explicit human decision record."
        ),
    }
)

STICKY_NOTE = (
    "This outcome does not clear itself. Only a recorded human decision "
    "(operator, decision reference) can reopen research."
)
BUDGET_RULE_SENTENCE = "INSUFFICIENT_EDGE requires BOTH budgets met AND no passing family (D013)."
SHARED_COMPONENT_NOTE = (
    "Families A and C share the regime detector; B reuses the 4H direction gate. "
    "Shown for transparency; independence is decided by the registry test, not this note."
)
NO_DECISION_REFS = "No recorded family decisions."
ENABLEMENT_CLOSING = "Live trading is never enabled by this report."
_OPERATOR_ENABLEMENT = (
    "Live enablement remains an explicit operator action with a passing health verdict."
)
ENABLEMENT_EFFECT: MappingProxyType[KillGateState, str] = MappingProxyType(
    {
        KillGateState.WITHIN_BUDGET: _OPERATOR_ENABLEMENT,
        KillGateState.PASSING_CANDIDATE: _OPERATOR_ENABLEMENT,
        KillGateState.INSUFFICIENT_EDGE: (
            "New strategy families are not registered and live enablement is refused until "
            "an explicit human decision record clears this state."
        ),
    }
)
LIVE_ROWS_ABSENT = (
    "No LIVE evidence rows exist yet. Backtest and paper sections are complete; "
    "live-5 sections populate when live journal rows appear."
)

_TESTED_STATUSES = frozenset({"TESTED_FAIL", "TESTED_PASS"})
_MISSING = "MISSING"
_NO_TRADE_LABELS: MappingProxyType[NoTradeCategory, str] = MappingProxyType(
    {
        NoTradeCategory.REGIME_FILTER: "regime filter",
        NoTradeCategory.RR_FLOOR: "RR floor",
        NoTradeCategory.OPEN_POSITION_CONFLICT: "open-position conflict",
        NoTradeCategory.DATA_UNAVAILABILITY: "data unavailability",
        NoTradeCategory.KILL_GATE_TRIP: "kill-gate trip",
        NoTradeCategory.UNMAPPED: "UNMAPPED",
    }
)


def render_header(report: JournalDepthReport, blocked_by: tuple[str, ...] = ()) -> list[str]:
    """The two-column header table, rows in the exact UI-SPEC order.

    With `blocked_by` (D061 F) the kill-gate state row carries the NOT CONCLUDED text instead of
    the evaluated state.
    """
    state_cell = (
        not_concluded_line(blocked_by) if blocked_by else report.kill_gate.verdict.state.value
    )
    rows = [
        ["Report digest", f"sha256:{report.digest()}"],
        ["As of (UTC)", fmt_utc(report.as_of_utc)],
        ["As of (display)", f"{fmt_display(report.as_of_utc)} ({DISPLAY_TZ_NAME})"],
        ["Timezone note", TIMEZONE_NOTE],
        ["Generator", f"{GENERATOR_NAME} + {ANALYTICS_SCHEMA_VERSION}"],
        ["Read-only statement", READ_ONLY_STATEMENT],
        ["Kill gate state", state_cell],
        ["Live orders", md_cell(report.live_posture)],
    ]
    return md_table(["Field", "Value"], [":---", ":---"], rows)


def _passing_decision_refs(verdict: KillGateVerdict) -> str:
    refs = sorted(
        md_cell(row.decision_ref)
        for row in verdict.families
        if row.counted and row.status == "TESTED_PASS" and row.decision_ref is not None
    )
    return ", ".join(refs) if refs else NO_DATA


def _banner(verdict: KillGateVerdict) -> str:
    state = verdict.state
    sentence = STATE_SENTENCES[state].format(
        n=fmt_int(verdict.families_tested),
        m=fmt_months(verdict.months_elapsed),
        decision_ref=_passing_decision_refs(verdict),
    )
    label = state.value
    if state is KillGateState.INSUFFICIENT_EDGE:
        label += " TERMINAL"
    return f"> **KILL GATE STATE: {label}** {_EM_DASH} {sentence}"


def _met(flag: bool) -> str:
    return "MET" if flag else "NOT_MET"


def _budget_table(verdict: KillGateVerdict) -> list[str]:
    months = (
        f"{fmt_months(verdict.months_elapsed)} "
        f"({fmt_int(verdict.whole_months)} calendar months + {fmt_int(verdict.extra_days)} days)"
    )
    rows = [
        [
            "Independently specified families tested",
            "3",
            fmt_int(verdict.families_tested),
            _met(verdict.families_budget_met),
        ],
        ["Research months elapsed", "6 calendar months", months, _met(verdict.months_budget_met)],
        [
            "Any family passing acceptance",
            "none required",
            fmt_int(verdict.pass_count),
            "informational",
        ],
    ]
    return md_table(
        ["Budget", "Required", "Actual", "Status"], [":---", ":---", "---:", ":---"], rows
    )


def _clock_table(verdict: KillGateVerdict) -> list[str]:
    clock = verdict.clock
    rows = [
        ["Research clock start (UTC)", fmt_utc(verdict.cycle_start_utc)],
        ["Source", md_cell(clock.source)],
        ["Freeze commit", md_cell(clock.freeze_commit)],
        ["Commit author date", md_cell(clock.commit_author_date)],
        ["Earliest possible INSUFFICIENT_EDGE (UTC)", fmt_utc(verdict.earliest_terminal_utc)],
        ["Evaluated at (UTC)", fmt_utc(verdict.evaluated_at_utc)],
        ["Evaluated at (display)", fmt_display(verdict.evaluated_at_utc)],
    ]
    return md_table(["Field", "Value"], [":---", ":---"], rows)


def _earliest_note(verdict: KillGateVerdict) -> list[str]:
    if verdict.months_budget_met:
        return []
    date = fmt_utc(verdict.earliest_terminal_utc)[:10]
    return [f"Earliest possible INSUFFICIENT_EDGE: {date}."]


def _reopened_line(verdict: KillGateVerdict) -> list[str]:
    if (
        verdict.reopened_by_decision_ref is None
        or verdict.reopened_by_operator_id is None
        or verdict.reopened_at_utc is None
    ):
        return []
    return [
        f"Reopened by decision {md_cell(verdict.reopened_by_decision_ref)} "
        f"(operator {md_cell(verdict.reopened_by_operator_id)}) "
        f"at {fmt_display(verdict.reopened_at_utc)}."
    ]


def _independent_cell(row: FamilyGateRow) -> str:
    if row.independent:
        return "YES"
    return "UNKNOWN" if row.sheet_sha256 is None else "NO"


def _decision_cell(row: FamilyGateRow) -> str:
    cell = "" if row.decision_ref is None else md_cell(row.decision_ref)
    if cell:
        return cell
    return _MISSING if row.status in _TESTED_STATUSES else "-"


def _universe_cell(row: FamilyGateRow) -> str:
    if row.live5_n == 0 and row.research_n == 0:
        return NO_DATA
    return f"Live-5 n={fmt_int(row.live5_n)} / Research n={fmt_int(row.research_n)}"


def _family_table(families: tuple[FamilyGateRow, ...]) -> list[str]:
    headers = [
        "Family",
        "Independent",
        "Sheet hash (12)",
        "Param sets",
        "Experiments",
        "Status",
        "Decision ref",
        "Universe",
    ]
    aligns = [":---", ":---", ":---", "---:", "---:", ":---", ":---", ":---"]
    rows = [
        [
            md_cell(row.family_id),
            _independent_cell(row),
            _MISSING if row.sheet_sha256 is None else md_cell(row.sheet_sha256[:12]),
            fmt_int(row.param_set_count),
            fmt_int(row.experiment_count),
            md_cell(row.status),
            _decision_cell(row),
            _universe_cell(row),
        ]
        for row in families
    ]
    return md_table(headers, aligns, rows)


def _gate_matrix(families: tuple[FamilyGateRow, ...]) -> list[str]:
    headers = ["Family", *GATE_IDS]
    aligns = [":---"] * len(headers)
    rows: list[list[str]] = []
    for row in families:
        cells = dict(row.cells)
        gate_cells = [
            cells[gate_id].value if gate_id in cells else "NOT_EVALUATED" for gate_id in GATE_IDS
        ]
        rows.append([md_cell(row.family_id), *gate_cells])
    return md_table(headers, aligns, rows)


def _gate_legend() -> str:
    return ", ".join(f"{gate_id} {GATE_LABELS[gate_id]}" for gate_id in GATE_IDS)


def _count_cell(value: int, column_empty: bool) -> str:
    return NO_DATA if column_empty else fmt_int(value)


def _no_trade_table(section: NoTradeSection) -> list[str]:
    by_category = {row.category: row for row in section.rows}
    live_empty = section.total.live5_n == 0
    research_empty = section.total.research_n == 0
    all_empty = section.total.all_n == 0

    def line(label: str, row: NoTradeRow) -> list[str]:
        return [
            label,
            _count_cell(row.live5_n, live_empty),
            _count_cell(row.research_n, research_empty),
            _count_cell(row.all_n, all_empty),
        ]

    rows: list[list[str]] = []
    for category in NoTradeCategory:
        row = by_category.get(category)
        if row is None:
            raise AnalyticsInputError(f"NO_TRADE section has no row for {category.value}")
        rows.append(line(_NO_TRADE_LABELS[category], row))
    rows.append(line("**Total**", section.total))
    return md_table(
        ["Reason category", "Live-5 n", "Research n", "All n"],
        [":---", "---:", "---:", "---:"],
        rows,
    )


def _decision_reference_lines(refs: tuple[str, ...]) -> list[str]:
    if not refs:
        return [NO_DECISION_REFS]
    return [f"- {md_cell(ref) or _MISSING}" for ref in sorted(set(refs))]


WITHHELD_EXPLANATION = (
    "No kill-gate conclusion is shown on real evidence while the listed review items are "
    "unresolved. The verdict, budget, clock and family matrices are withheld; the NO_TRADE "
    "counts and decision references below and sections 2 to 10 are unaffected."
)


def _render_withheld_kill_gate(
    report: JournalDepthReport, blocked_by: tuple[str, ...]
) -> list[str]:
    """`## 1. Kill Gate` without a conclusion: marker, NO_TRADE counts, decision references."""
    kill_gate = report.kill_gate
    no_trade_sections = sorted(
        kill_gate.no_trade, key=lambda item: EVIDENCE_ORDER.index(item.evidence)
    )
    blocks: list[list[str]] = [
        [f"## {SECTION_TITLES[0]}"],
        [f"> **KILL GATE: {not_concluded_line(blocked_by)}** {_EM_DASH} {WITHHELD_EXPLANATION}"],
    ]
    index = 1
    for section in no_trade_sections:
        blocks.extend(
            [
                [f"### 1.{index} NO_TRADE by reason category ({section.evidence.value})"],
                [evidence_caption(section.evidence)],
                _no_trade_table(section),
            ]
        )
        index += 1
    blocks.extend(
        [
            [f"### 1.{index} Decision references"],
            _decision_reference_lines(kill_gate.decision_refs),
            [ENABLEMENT_CLOSING],
        ]
    )
    return join_blocks(blocks)


def render_section_kill_gate(
    report: JournalDepthReport, blocked_by: tuple[str, ...] = ()
) -> list[str]:
    """`## 1. Kill Gate`: banner, budget, clock, family matrices, NO_TRADE, decisions, effect.

    With `blocked_by` (D061 F) the conclusion is withheld and replaced by a NOT CONCLUDED block.
    """
    if blocked_by:
        return _render_withheld_kill_gate(report, blocked_by)
    kill_gate = report.kill_gate
    verdict = kill_gate.verdict
    no_trade_sections = sorted(
        kill_gate.no_trade, key=lambda item: EVIDENCE_ORDER.index(item.evidence)
    )
    blocks: list[list[str]] = [
        [f"## {SECTION_TITLES[0]}"],
        [_banner(verdict)],
        [STICKY_NOTE] if verdict.sticky else [],
        _reopened_line(verdict),
        ["### 1.1 Budget progress"],
        _budget_table(verdict),
        [BUDGET_RULE_SENTENCE],
        ["### 1.2 Clock provenance"],
        _clock_table(verdict),
        _earliest_note(verdict),
        ["### 1.3 Family acceptance"],
        _family_table(kill_gate.families),
        [SHARED_COMPONENT_NOTE],
        ["### 1.4 Family gate matrix"],
        _gate_matrix(kill_gate.families),
        [_gate_legend()],
    ]
    index = 5
    for section in no_trade_sections:
        blocks.extend(
            [
                [f"### 1.{index} NO_TRADE by reason category ({section.evidence.value})"],
                [evidence_caption(section.evidence)],
                _no_trade_table(section),
            ]
        )
        index += 1
    blocks.extend(
        [
            [f"### 1.{index} Decision references"],
            _decision_reference_lines(kill_gate.decision_refs),
            [f"### 1.{index + 1} Enablement effect"],
            [ENABLEMENT_EFFECT[verdict.state]],
            [ENABLEMENT_CLOSING],
        ]
    )
    return join_blocks(blocks)


def render_section_evidence_overview(report: JournalDepthReport) -> list[str]:
    """`## 2. Evidence Overview`: one row per evidence kind, never pooled."""
    blocks_by_kind = {block.kind: block for block in report.evidence}
    incomplete_totals: dict[EvidenceKind, int] = {kind: 0 for kind in EVIDENCE_ORDER}
    for entry in report.incomplete_ledger:
        incomplete_totals[entry.evidence] += entry.count
    rows: list[list[str]] = []
    for kind in EVIDENCE_ORDER:
        block = blocks_by_kind.get(kind)
        if block is None:
            raise AnalyticsInputError(f"report has no {kind.value} evidence block")
        rows.append(
            [
                kind.value,
                "YES" if block.has_data else "NO",
                fmt_int(block.core.n),
                fmt_int(block.execution_quality.n_records),
                fmt_int(block.no_trade.total.all_n),
                fmt_int(incomplete_totals[kind]),
            ]
        )
    table = md_table(
        [
            "Evidence",
            "Has data",
            "Outcomes (n)",
            "Lifecycle records",
            "NO_TRADE rows",
            "INCOMPLETE",
        ],
        [":---", ":---", "---:", "---:", "---:", "---:"],
        rows,
    )
    live_block = blocks_by_kind[EvidenceKind.LIVE]
    return join_blocks(
        [
            [f"## {SECTION_TITLES[1]}"],
            [evidence_caption()],
            table,
            [] if live_block.has_data else [LIVE_ROWS_ABSENT],
        ]
    )
