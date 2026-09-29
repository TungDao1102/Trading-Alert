"""Governance half of the offline report: header and the Kill Gate section (Phase 10, plan 10-10).

Pure functions of a `JournalDepthReport` returning lines of Markdown. Wording, table columns
and formats follow `10-UI-SPEC.md`. INSUFFICIENT_EDGE is presented as a calm, valid terminal
outcome with the same visual weight as every other state; PASSING_CANDIDATE is explicitly
non-authorizing; no state ever enables live trading. Emphasis never encodes favorability and
no row is ordered by result. All sourced text passes `md_cell`.
"""

from __future__ import annotations

from types import MappingProxyType

from src.analytics.killgate import KillGateVerdict
from src.analytics.render_common import (
    DISPLAY_TZ_NAME,
    NO_DATA,
    READ_ONLY_STATEMENT,
    SECTION_TITLES,
    TIMEZONE_NOTE,
    fmt_display,
    fmt_int,
    fmt_months,
    fmt_utc,
    join_blocks,
    md_cell,
    md_table,
)
from src.analytics.report import JournalDepthReport
from src.analytics.types import ANALYTICS_SCHEMA_VERSION
from src.domain.enums import KillGateState

__all__ = [
    "GENERATOR_NAME",
    "STATE_SENTENCES",
    "STICKY_NOTE",
    "render_header",
    "render_section_kill_gate",
]

GENERATOR_NAME = "src.analytics.cli"
_EM_DASH = "—"

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


def render_header(report: JournalDepthReport) -> list[str]:
    """The two-column header table, rows in the exact UI-SPEC order."""
    rows = [
        ["Report digest", f"sha256:{report.digest()}"],
        ["As of (UTC)", fmt_utc(report.as_of_utc)],
        ["As of (display)", f"{fmt_display(report.as_of_utc)} ({DISPLAY_TZ_NAME})"],
        ["Timezone note", TIMEZONE_NOTE],
        ["Generator", f"{GENERATOR_NAME} + {ANALYTICS_SCHEMA_VERSION}"],
        ["Read-only statement", READ_ONLY_STATEMENT],
        ["Kill gate state", report.kill_gate.verdict.state.value],
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


def render_section_kill_gate(report: JournalDepthReport) -> list[str]:
    """`## 1. Kill Gate`: banner, budget progress and clock provenance."""
    verdict = report.kill_gate.verdict
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
    ]
    return join_blocks(blocks)
