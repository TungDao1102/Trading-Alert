"""Offline report renderer tests: governance half (Phase 10, plan 10-10, D-04, GOV-01, JRN-01).

RED first: authored before `src/analytics/render_common.py`, `render_killgate.py` and
`render.py` exist. The renderer is a pure function of `JournalDepthReport`; every string,
format and escape rule is pinned by `10-UI-SPEC.md`. Fixture: `report_composite`
(INSUFFICIENT_EDGE verdict, LIVE evidence empty).
"""

from __future__ import annotations

import dataclasses
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from src.analytics.family import FamilyStatus
from src.analytics.gates import GATE_IDS, GATE_LABELS
from src.analytics.killgate import PriorEvaluation, ResetRecord
from src.analytics.no_trade import NoTradeCategory, NoTradeRow
from src.analytics.render import SECTION_TITLES, render_markdown
from src.analytics.render_common import (
    DISPLAY_TZ_NAME,
    MAX_CELL_CHARS,
    NO_DATA,
    TRUNCATION_MARKER,
    fmt_bps,
    fmt_display,
    fmt_estimate,
    fmt_int,
    fmt_months,
    fmt_pct,
    fmt_price,
    fmt_r,
    fmt_seconds,
    fmt_utc,
    md_cell,
    md_cell_truncated,
    md_table,
)
from src.analytics.render_killgate import STATE_SENTENCES, render_header
from src.analytics.types import AnalyticsInputError, Estimate, EvidenceKind
from src.domain.enums import KillGateState

from tests.phase10_helpers import parse_utc
from tests.test_analytics_report import build_report_inputs

CASE_AS_OF = "2027-04-01T00:00:00+00:00"


def make_report(**changes):  # type: ignore[no-untyped-def]
    """Build the composite report, optionally replacing ReportInputs fields."""
    from src.analytics.report import build_journal_depth_report

    inputs = build_report_inputs()
    if changes:
        inputs = dataclasses.replace(inputs, **changes)
    return build_journal_depth_report(inputs, base_seed=20260929, resamples=100)


def render_lines(report) -> list[str]:  # type: ignore[no-untyped-def]
    return render_markdown(report).split("\n")


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #


def test_primitives_md_cell_escapes_pipe_backtick_angle_newline_and_controls() -> None:
    assert md_cell("a|b") == "a\\|b"
    assert md_cell("a`b") == "a'b"
    assert md_cell("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"
    assert md_cell("a\nb\r\nc\td") == "a b  c d"
    assert md_cell("a\x00b\x07c\x7fd") == "abcd"
    assert md_cell("plain text 123") == "plain text 123"
    assert md_cell("  padded  ") == "padded"
    assert md_cell("") == ""


def test_primitives_md_cell_backslash_cannot_defeat_the_pipe_escape() -> None:
    # A raw backslash before a pipe must not turn "\|" into an escaped backslash + bare pipe.
    assert md_cell("a\\|b") == "a\\\\\\|b"
    assert md_cell("a\\b") == "a\\\\b"


def test_primitives_md_cell_strips_unicode_format_and_line_separator_characters() -> None:
    assert md_cell("a\u202eb") == "ab"  # bidi override
    assert md_cell("a\u200bb") == "ab"  # zero-width space
    assert md_cell("a\u2028b\u2029c") == "a b c"
    assert md_cell("a\x85b") == "ab"  # C1 control


def test_primitives_md_cell_truncates_at_200_chars_with_marker() -> None:
    text = "x" * 300
    out = md_cell(text)
    assert out == "x" * MAX_CELL_CHARS + TRUNCATION_MARKER
    assert TRUNCATION_MARKER == "...[truncated]"
    assert MAX_CELL_CHARS == 200
    assert md_cell_truncated(text) is True
    assert md_cell_truncated("x" * 200) is False
    assert md_cell("x" * 200) == "x" * 200
    # Escaping never splits an escape sequence at the cut.
    pipes = "|" * 300
    assert md_cell(pipes) == "\\|" * 200 + TRUNCATION_MARKER


def test_primitives_number_formats_exponent_and_negative_zero() -> None:
    assert fmt_r(Decimal("-0.00001")) == "0.0000"
    assert fmt_r(Decimal("1E+1")) == "10.0000"
    assert fmt_r(Decimal("0.80")) == "0.8000"
    assert fmt_r(Decimal("0.00005")) == "0.0000"  # half-even tie to even
    assert fmt_r(Decimal("0.00015")) == "0.0002"
    assert fmt_r(Decimal("-1.5")) == "-1.5000"
    assert fmt_r(None) == NO_DATA == "no data"
    assert fmt_pct(Decimal("87.5")) == "87.50%"
    assert fmt_pct(Decimal("-0.001")) == "0.00%"
    assert fmt_seconds(Decimal("12.25")) == "12.2"
    assert fmt_seconds(Decimal("12.35")) == "12.4"
    assert fmt_bps(Decimal("1.005")) == "1.00"
    assert fmt_bps(Decimal("-0.001")) == "0.00"
    assert fmt_months(Decimal("6.4333")) == "6.4"
    assert fmt_months(Decimal("3")) == "3.0"
    assert fmt_price(Decimal("1E+1")) == "10"
    assert fmt_price(Decimal("0.00010")) == "0.00010"
    assert fmt_price(Decimal("-0.00")) == "0.00"
    assert fmt_price(None) == "no data"
    assert fmt_int(12) == "12"
    assert fmt_int(0) == "0"
    assert fmt_int(None) == "no data"
    with pytest.raises(AnalyticsInputError):
        fmt_r(Decimal("NaN"))
    with pytest.raises(AnalyticsInputError):
        fmt_r(1)  # type: ignore[arg-type]
    with pytest.raises(AnalyticsInputError):
        fmt_int(True)


def test_primitives_fmt_estimate_for_zero_one_and_many() -> None:
    many = Estimate(
        value=Decimal("0.8"),
        lo=Decimal("0.5"),
        hi=Decimal("1.1"),
        n=2,
        n_valued=2,
        interval_absent=False,
    )
    assert fmt_estimate(many, fmt_r) == "0.8000 [0.5000, 1.1000] n=2"
    one = Estimate(value=Decimal("0.8"), lo=None, hi=None, n=1, n_valued=1, interval_absent=True)
    assert fmt_estimate(one, fmt_r) == "0.8000 [interval absent] n=1"
    none = Estimate(value=None, lo=None, hi=None, n=0, n_valued=0, interval_absent=True)
    assert fmt_estimate(none, fmt_r) == "no data"
    partial = Estimate(
        value=Decimal("0.8"),
        lo=Decimal("0.5"),
        hi=Decimal("1.1"),
        n=3,
        n_valued=2,
        interval_absent=False,
    )
    assert fmt_estimate(partial, fmt_r) == "0.8000 [0.5000, 1.1000] n=2"


def test_primitives_utc_and_display_time() -> None:
    moment = parse_utc("2027-04-01T00:00:00+00:00")
    assert fmt_utc(moment) == "2027-04-01T00:00:00+00:00"
    assert fmt_display(moment) == "2027-04-01 07:00:00 +07:00"
    assert DISPLAY_TZ_NAME == "Asia/Ho_Chi_Minh"
    late = parse_utc("2027-04-01T20:30:59+00:00")
    assert fmt_display(late) == "2027-04-02 03:30:59 +07:00"
    with pytest.raises(AnalyticsInputError):
        fmt_utc(datetime(2027, 4, 1))
    with pytest.raises(AnalyticsInputError):
        fmt_display(datetime(2027, 4, 1))
    with pytest.raises(AnalyticsInputError):
        fmt_display(datetime(2027, 4, 1, tzinfo=timezone(timedelta(hours=7))))


def test_primitives_md_table_alignment_and_pre_escaped_cells() -> None:
    lines = md_table(["A", "B"], [":---", "---:"], [["x", "1"], ["y\\|z", "22"]])
    assert lines == [
        "| A | B |",
        "| :--- | ---: |",
        "| x | 1 |",
        "| y\\|z | 22 |",
    ]
    with pytest.raises(AnalyticsInputError):
        md_table(["A"], [":---"], [["a|b"]])  # unescaped pipe
    with pytest.raises(AnalyticsInputError):
        md_table(["A"], [":---"], [["a\nb"]])
    with pytest.raises(AnalyticsInputError):
        md_table(["A", "B"], [":---", ":---"], [["only"]])
    with pytest.raises(AnalyticsInputError):
        md_table(["A"], ["---"], [["x"]])
    with pytest.raises(AnalyticsInputError):
        md_table(["A"], [":---"], [[1]])  # type: ignore[list-item]


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #


def test_header_table_rows_in_the_exact_ui_spec_order() -> None:
    report = make_report()
    lines = render_header(report)
    assert lines == [
        "| Field | Value |",
        "| :--- | :--- |",
        f"| Report digest | sha256:{report.digest()} |",
        "| As of (UTC) | 2027-04-01T00:00:00+00:00 |",
        "| As of (display) | 2027-04-01 07:00:00 +07:00 (Asia/Ho_Chi_Minh) |",
        "| Timezone note | Stored and computed values are UTC. Display times are "
        "Asia/Ho_Chi_Minh (UTC+07:00, no DST). |",
        "| Generator | src.analytics.cli + analytics-schema/1 |",
        "| Read-only statement | This report is read-only. It never changes parameters, "
        "orders, or approvals, and it never enables live trading. |",
        "| Kill gate state | INSUFFICIENT_EDGE |",
        "| Live orders | LIVE_ORDERS_DISABLED |",
    ]


# --------------------------------------------------------------------------- #
# Banner
# --------------------------------------------------------------------------- #

INSUFFICIENT_SENTENCE = (
    "NO_TRADE / INSUFFICIENT EDGE. Three or more independently specified families were "
    "tested under the frozen methodology, at least six months have elapsed, and none "
    "passed. This is a valid terminal outcome, not an error. Live trading stays disabled "
    "and new strategy families are not registered until a new evidence-backed question is "
    "approved by an explicit human decision record."
)


def test_banner_insufficient_edge_is_calm_terminal_and_exact() -> None:
    lines = render_lines(make_report())
    banner = "> **KILL GATE STATE: INSUFFICIENT_EDGE TERMINAL** \u2014 " + INSUFFICIENT_SENTENCE
    assert banner in lines
    assert STATE_SENTENCES[KillGateState.INSUFFICIENT_EDGE] == INSUFFICIENT_SENTENCE
    assert lines.index("## 1. Kill Gate") + 2 == lines.index(banner)
    # Same visual weight as every other state: a plain bold banner, no alarm styling.
    assert "> **KILL GATE STATE: INSUFFICIENT_EDGE" in banner
    assert "ERROR" not in banner.upper().replace("NOT AN ERROR", "")


def test_banner_within_budget_and_passing_candidate_sentences_are_filled() -> None:
    early = make_report(as_of_utc=parse_utc("2026-12-19T00:00:00+00:00"))
    lines = render_lines(early)
    assert (
        "> **KILL GATE STATE: WITHIN_BUDGET** \u2014 Research budget is not exhausted "
        "(3 of 3 families tested, 3.0 of 6 months elapsed). Keep researching. "
        "Live trading stays disabled." in lines
    )
    assert not any(line.startswith("> **KILL GATE STATE: WITHIN_BUDGET TERMINAL") for line in lines)
    base = build_report_inputs()
    families = tuple(
        dataclasses.replace(
            family, status=FamilyStatus.TESTED_PASS, decision_ref="DEC-2026-11-pass-range-mr"
        )
        if family.family_id == "range-mr"
        else family
        for family in base.families
    )
    passing = make_report(families=families)
    plines = render_lines(passing)
    assert (
        "> **KILL GATE STATE: PASSING_CANDIDATE** \u2014 A family has a recorded passing "
        "decision (DEC-2026-11-pass-range-mr). This records that evidence exists. It does "
        "not authorize live trading; a separate decision record is required." in plines
    )


def test_banner_sticky_terminal_and_reset_event_lines() -> None:
    prior = PriorEvaluation(
        state=KillGateState.INSUFFICIENT_EDGE,
        evaluated_at_utc=parse_utc("2027-03-01T00:00:00+00:00"),
    )
    sticky = render_lines(make_report(prior_evaluations=(prior,)))
    note = (
        "This outcome does not clear itself. Only a recorded human decision "
        "(operator, decision reference) can reopen research."
    )
    assert note in sticky
    assert not any(line.startswith("Reopened by decision") for line in sticky)
    reset = ResetRecord(
        operator_id="op|1",
        decision_ref="DEC-2027-03-reopen",
        occurred_at_utc=parse_utc("2027-03-15T00:00:00+00:00"),
    )
    reopened = render_lines(make_report(prior_evaluations=(prior,), resets=(reset,)))
    assert note not in reopened
    assert (
        "Reopened by decision DEC-2027-03-reopen (operator op\\|1) at 2027-03-15 07:00:00 +07:00."
        in reopened
    )
    plain = render_lines(make_report())
    assert note not in plain
    assert not any(line.startswith("Reopened by decision") for line in plain)


# --------------------------------------------------------------------------- #
# Budget and clock
# --------------------------------------------------------------------------- #


def test_budget_table_rows_and_rule_sentence() -> None:
    lines = render_lines(make_report())
    start = lines.index("| Budget | Required | Actual | Status |")
    assert lines[start : start + 5] == [
        "| Budget | Required | Actual | Status |",
        "| :--- | :--- | ---: | :--- |",
        "| Independently specified families tested | 3 | 3 | MET |",
        "| Research months elapsed | 6 calendar months | 6.4 (6 calendar months + 13 days) | MET |",
        "| Any family passing acceptance | none required | 0 | informational |",
    ]
    assert lines[start + 5] == ""
    assert (
        lines[start + 6]
        == "INSUFFICIENT_EDGE requires BOTH budgets met AND no passing family (D013)."
    )
    early = render_lines(make_report(as_of_utc=parse_utc("2026-12-19T00:00:00+00:00")))
    assert (
        "| Research months elapsed | 6 calendar months | 3.0 (3 calendar months + 0 days) "
        "| NOT_MET |" in early
    )


def test_clock_provenance_table_and_earliest_note() -> None:
    lines = render_lines(make_report())
    start = lines.index("| Field | Value |", lines.index("## 1. Kill Gate"))
    assert lines[start : start + 9] == [
        "| Field | Value |",
        "| :--- | :--- |",
        "| Research clock start (UTC) | 2026-09-19T00:00:00+00:00 |",
        "| Source | docs/research/RESEARCH_PROTOCOL.md header: Frozen on |",
        "| Freeze commit | 281ccd0894ea35717cc741788b6133cfb202af82 |",
        "| Commit author date | 2026-09-19T14:08:12+07:00 |",
        "| Earliest possible INSUFFICIENT_EDGE (UTC) | 2027-03-19T00:00:00+00:00 |",
        "| Evaluated at (UTC) | 2027-04-01T00:00:00+00:00 |",
        "| Evaluated at (display) | 2027-04-01 07:00:00 +07:00 |",
    ]
    assert not any(line.startswith("Earliest possible INSUFFICIENT_EDGE:") for line in lines)
    early = render_lines(make_report(as_of_utc=parse_utc("2026-12-19T00:00:00+00:00")))
    assert "Earliest possible INSUFFICIENT_EDGE: 2027-03-19." in early


# --------------------------------------------------------------------------- #
# Tracer: whole-document byte rules
# --------------------------------------------------------------------------- #


def test_tracer_document_is_lf_only_single_trailing_lf_and_ascii_but_the_banner_dash() -> None:
    text = render_markdown(make_report())
    assert text.startswith("# Journal Depth + Kill-Gate Report\n\n| Field | Value |\n")
    assert "\r" not in text
    assert text.endswith("\n") and not text.endswith("\n\n")
    for number, line in enumerate(text.split("\n")[:-1], start=1):
        assert line == line.rstrip(), f"trailing whitespace on line {number}: {line!r}"
        for char in line:
            if ord(char) > 127:
                assert char == "\u2014", f"unexpected non-ASCII {char!r} on line {number}"
                assert line.startswith("> **KILL GATE STATE"), line
    assert "\n\n---\n\n## 1. Kill Gate\n\n> **KILL GATE STATE: " in text
    assert not text.startswith("\ufeff")
    assert render_markdown(make_report()) == text  # deterministic


# --------------------------------------------------------------------------- #
# Task 2: family matrices, NO_TRADE by category, decisions, enablement, Section 2
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "phase10"
    / "render_golden"
    / "expected_sections_0_2.md"
)
RESERVED_WORDS = (
    "winner",
    "best",
    "recommend",
    "optimize",
    "tune",
    "improve",
    "profitable",
    "edge found",
    "should",
)
_RESERVED_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in RESERVED_WORDS) + r")\w*", re.IGNORECASE
)
BACKSLASH = chr(92)


def find_reserved(text: str) -> list[str]:
    """Reserved words (case-insensitive, at a word start) found in `text`."""
    return [match.group(0) for match in _RESERVED_PATTERN.finditer(text)]


def table_after(lines: list[str], heading: str) -> list[str]:
    """The pipe-table lines that follow `heading` (first table only)."""
    start = lines.index(heading) + 1
    while not lines[start].startswith("|"):
        start += 1
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return lines[start:end]


def unescaped_pipes(line: str) -> int:
    count = 0
    index = 0
    while index < len(line):
        if line[index] == BACKSLASH:
            index += 2
            continue
        if line[index] == "|":
            count += 1
        index += 1
    return count


def with_range_mr_passing():  # type: ignore[no-untyped-def]
    base = build_report_inputs()
    families = tuple(
        dataclasses.replace(
            family, status=FamilyStatus.TESTED_PASS, decision_ref="DEC-2026-11-pass-range-mr"
        )
        if family.family_id == "range-mr"
        else family
        for family in base.families
    )
    return make_report(families=families)


def test_k2a_family_matrix_columns_rows_and_shared_component_note() -> None:
    lines = render_lines(make_report())
    table = table_after(lines, "### 1.3 Family acceptance")
    assert table == [
        "| Family | Independent | Sheet hash (12) | Param sets | Experiments | Status "
        "| Decision ref | Universe |",
        "| :--- | :--- | :--- | ---: | ---: | :--- | :--- | :--- |",
        "| trend-pullback | YES | a1a1a1a1a1a1 | 2 | 2 | TESTED_FAIL "
        "| DEC-2026-11-fail-trend-pullback | Live-5 n=2 / Research n=2 |",
        "| breakout-retest | YES | a2a2a2a2a2a2 | 1 | 2 | TESTED_FAIL "
        "| DEC-2026-11-fail-breakout-retest | no data |",
        "| range-mr | YES | a3a3a3a3a3a3 | 1 | 2 | TESTED_FAIL "
        "| DEC-2026-11-fail-range-mr | no data |",
    ]
    note = (
        "Families A and C share the regime detector; B reuses the 4H direction gate. "
        "Shown for transparency; independence is decided by the registry test, not this note."
    )
    end = lines.index(table[-1]) + 1
    assert lines[end] == "" and lines[end + 1] == note


def test_k2a_missing_unknown_and_empty_cells() -> None:
    report = make_report()
    kill_gate = report.kill_gate
    broken = dataclasses.replace(
        kill_gate.families[0], decision_ref=None, sheet_sha256=None, independent=False
    )
    untested = dataclasses.replace(
        kill_gate.families[1], status="NOT_TESTED", decision_ref=None, independent=False
    )
    patched = dataclasses.replace(
        report,
        kill_gate=dataclasses.replace(
            kill_gate, families=(broken, untested, *kill_gate.families[2:])
        ),
    )
    table = table_after(render_lines(patched), "### 1.3 Family acceptance")
    assert table[2].startswith(
        "| trend-pullback | UNKNOWN | MISSING | 2 | 2 | TESTED_FAIL | MISSING |"
    )
    assert table[3].startswith("| breakout-retest | NO | a2a2a2a2a2a2 | 1 | 2 | NOT_TESTED | - |")


def test_k2b_gate_matrix_has_eleven_columns_and_only_the_four_cell_tokens() -> None:
    lines = render_lines(make_report())
    table = table_after(lines, "### 1.4 Family gate matrix")
    assert table[0] == "| Family | " + " | ".join(GATE_IDS) + " |"
    assert len(GATE_IDS) == 10
    allowed = {"MET", "NOT_MET", "PENDING_THRESHOLD_TBD", "NOT_EVALUATED"}
    assert len(table) == 2 + 3
    for row in table[2:]:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 11
        gates = dict(zip(GATE_IDS, cells[1:], strict=True))
        assert set(gates.values()) <= allowed
        for gate_id in ("G04", "G05", "G06", "G09"):
            assert gates[gate_id] == "PENDING_THRESHOLD_TBD"
        assert gates["G01"] == gates["G02"] == "NOT_EVALUATED"
    legend = ", ".join(f"{gate_id} {GATE_LABELS[gate_id]}" for gate_id in GATE_IDS)
    assert legend.startswith("G01 Deterministic rules, G02 No material look-ahead,")
    assert legend.endswith("G09 No single-point dependence, G10 Baseline-compared")
    assert lines[lines.index(table[-1]) + 2] == legend


def test_k3_no_trade_tables_fixed_row_order_and_no_data_columns() -> None:
    lines = render_lines(make_report())
    headings = [
        "### 1.5 NO_TRADE by reason category (BACKTEST)",
        "### 1.6 NO_TRADE by reason category (PAPER)",
        "### 1.7 NO_TRADE by reason category (LIVE)",
    ]
    for heading, kind in zip(headings, ("BACKTEST", "PAPER", "LIVE"), strict=True):
        assert heading in lines
        assert lines[lines.index(heading) + 2] == f"*Evidence: {kind}*"
    labels = [
        "regime filter",
        "RR floor",
        "open-position conflict",
        "data unavailability",
        "kill-gate trip",
        "UNMAPPED",
        "**Total**",
    ]
    paper = table_after(lines, headings[1])
    assert paper[0] == "| Reason category | Live-5 n | Research n | All n |"
    assert paper[1] == "| :--- | ---: | ---: | ---: |"
    assert [row.split("|")[1].strip() for row in paper[2:]] == labels
    assert paper[-1] == "| **Total** | 2 | 2 | 2 |"
    for row in paper[2:]:
        assert "no data" not in row
    # BACKTEST and LIVE have no NO_TRADE rows: every cell of every empty column is no data.
    for heading in (headings[0], headings[2]):
        table = table_after(lines, heading)
        assert [row.split("|")[1].strip() for row in table[2:]] == labels
        for row in table[2:]:
            assert row.endswith("| no data | no data | no data |")


def test_k3_empty_live5_column_renders_no_data_while_other_columns_show_counts() -> None:
    report = make_report()
    kill_gate = report.kill_gate
    paper = kill_gate.no_trade[1]
    rows = tuple(
        NoTradeRow(category=row.category, live5_n=0, research_n=row.research_n, all_n=row.all_n)
        for row in paper.rows
    )
    total = NoTradeRow(
        category=None,
        live5_n=0,
        research_n=paper.total.research_n,
        all_n=paper.total.all_n,
    )
    new_paper = dataclasses.replace(paper, rows=rows, total=total)
    patched = dataclasses.replace(
        report,
        kill_gate=dataclasses.replace(
            kill_gate, no_trade=(kill_gate.no_trade[0], new_paper, kill_gate.no_trade[2])
        ),
    )
    table = table_after(render_lines(patched), "### 1.6 NO_TRADE by reason category (PAPER)")
    body = table[2:]
    assert len(body) == 7
    assert any(row.startswith("| UNMAPPED |") for row in body)
    assert body[-1] == "| **Total** | no data | 2 | 2 |"
    for row in body:
        assert row.split("|")[2].strip() == "no data"
    assert NoTradeCategory.UNMAPPED.value == "UNMAPPED"


def test_decision_references_bullets_and_empty_sentence() -> None:
    lines = render_lines(make_report())
    start = lines.index("### 1.8 Decision references")
    assert lines[start + 2 : start + 5] == [
        "- DEC-2026-11-fail-breakout-retest",
        "- DEC-2026-11-fail-range-mr",
        "- DEC-2026-11-fail-trend-pullback",
    ]
    base = build_report_inputs()
    untested = tuple(
        dataclasses.replace(
            family,
            status=FamilyStatus.NOT_TESTED,
            decision_ref=None,
            decided_at_utc=None,
            development_experiment_ids=(),
            validation_experiment_ids=(),
        )
        for family in base.families
    )
    empty = render_lines(make_report(families=untested))
    at = empty.index("### 1.8 Decision references")
    assert empty[at + 2] == "No recorded family decisions."


def test_enablement_effect_sentence_per_state_and_the_fixed_closing_line() -> None:
    closing = "Live trading is never enabled by this report."
    operator_sentence = (
        "Live enablement remains an explicit operator action with a passing health verdict."
    )
    lines = render_lines(make_report())
    at = lines.index("### 1.9 Enablement effect")
    assert lines[at + 2] == (
        "New strategy families are not registered and live enablement is refused until an "
        "explicit human decision record clears this state."
    )
    assert lines[at + 3 : at + 5] == ["", closing]
    early = render_lines(make_report(as_of_utc=parse_utc("2026-12-19T00:00:00+00:00")))
    at = early.index("### 1.9 Enablement effect")
    assert early[at + 2] == operator_sentence
    assert early[at + 4] == closing
    passing = render_lines(with_range_mr_passing())
    at = passing.index("### 1.9 Enablement effect")
    assert passing[at + 2] == operator_sentence
    assert passing[at + 4] == closing


def test_evidence_overview_rows_caption_and_live_sentence() -> None:
    report = make_report()
    lines = render_lines(report)
    assert lines[lines.index("## 2. Evidence Overview") + 2] == (
        "*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*"
    )
    table = table_after(lines, "## 2. Evidence Overview")
    assert table == [
        "| Evidence | Has data | Outcomes (n) | Lifecycle records | NO_TRADE rows | INCOMPLETE |",
        "| :--- | :--- | ---: | ---: | ---: | ---: |",
        "| BACKTEST | YES | 2 | 2 | 0 | 15 |",
        "| PAPER | YES | 0 | 2 | 2 | 10 |",
        "| LIVE | NO | 0 | 0 | 0 | 0 |",
    ]
    sentence = (
        "No LIVE evidence rows exist yet. Backtest and paper sections are complete; "
        "live-5 sections populate when live journal rows appear."
    )
    assert lines[lines.index(table[-1]) + 2] == sentence
    for kind, expected in ((EvidenceKind.BACKTEST, 15), (EvidenceKind.PAPER, 10)):
        total = sum(e.count for e in report.incomplete_ledger if e.evidence is kind)
        assert total == expected


def test_sections_are_composed_in_the_fixed_order_with_the_h2_spacing_rule() -> None:
    assert SECTION_TITLES == (
        "1. Kill Gate",
        "2. Evidence Overview",
        "3. Full Report (unsliced)",
        "4. Dual Universe: Live-5 vs Research",
        "5. Approval-Delay Impact",
        "6. Execution Quality",
        "7. MFE / MAE",
        "8. Robustness Slices",
        "9. Incomplete and Excluded Inputs",
        "10. Provenance",
    )
    lines = render_lines(make_report())
    h2 = [line for line in lines if line.startswith("## ")]
    assert len(h2) >= 2
    assert h2 == [f"## {title}" for title in SECTION_TITLES[: len(h2)]]
    for heading in h2:
        at = lines.index(heading)
        assert lines[at - 3 : at] == ["", "---", ""]
        assert lines[at + 1] == ""


HOSTILE_ID = "fam|`<b>x</b>`\nrow" + "y" * 300
HOSTILE_REF = "DEC|`<script>alert(1)</script>`\r\nnext" + chr(7)


def test_hostile_strings_cannot_break_tables_or_inject_markup() -> None:
    base = build_report_inputs()
    families = (
        dataclasses.replace(base.families[0], family_id=HOSTILE_ID, decision_ref=HOSTILE_REF),
        *base.families[1:],
    )
    report = make_report(families=families, family_gate_facts={})
    text = render_markdown(report)
    assert "<b>" not in text and "<script>" not in text
    assert "`" not in text
    assert chr(7) not in text
    assert "...[truncated]" in text
    lines = text.split("\n")
    header_pipes: dict[int, int] = {}
    block_start = 0
    for number, line in enumerate(lines):
        if line.startswith("|"):
            if number == 0 or not lines[number - 1].startswith("|"):
                block_start = number
                header_pipes[block_start] = unescaped_pipes(line)
            assert unescaped_pipes(line) == header_pipes[block_start], line
    assert any("&lt;b&gt;" in line for line in lines), "hostile id must render, escaped"
    assert any(line.startswith("- DEC" + BACKSLASH + "|") for line in lines)


def test_reserved_vocabulary_scan_finds_none_and_detects_an_injected_word() -> None:
    assert find_reserved("This is the BEST result") == ["BEST"]
    assert find_reserved("Recommended and optimized to improve; should tune") != []
    assert find_reserved("an edge found here") != []
    assert find_reserved("Baseline-compared INSUFFICIENT_EDGE not an error") == []
    early = make_report(as_of_utc=parse_utc("2026-12-19T00:00:00+00:00"))
    for report in (make_report(), early, with_range_mr_passing()):
        text = render_markdown(report)
        assert find_reserved(text) == []
        assert find_reserved(text + "\nThe best family") != []
    for sentence in STATE_SENTENCES.values():
        assert find_reserved(sentence) == []


def test_render_sources_contain_no_advisory_wording() -> None:
    for name in ("render_killgate.py", "render_common.py", "render.py"):
        source = (REPO_ROOT / "src" / "analytics" / name).read_text(encoding="utf-8")
        assert find_reserved(source) == [], name


def test_output_carries_no_ambient_state() -> None:
    text = render_markdown(make_report())
    host = socket.gethostname()
    assert len(host) < 4 or host.lower() not in text.lower()
    assert os.getcwd() not in text
    assert str(REPO_ROOT) not in text
    assert "C:" + BACKSLASH not in text and "/Users/" not in text


def test_golden_sections_0_2_is_a_byte_exact_prefix_of_the_full_document() -> None:
    expected = GOLDEN_PATH.read_bytes()
    document = render_markdown(make_report()).encode("utf-8")
    assert document.startswith(expected[:-1])
    separator = b"\n\n---\n\n## 3. Full Report (unsliced)\n"
    assert document[len(expected) - 1 :].startswith(separator)
    assert b"\r" not in expected
    assert expected.endswith(b"\n") and not expected.endswith(b"\n\n")
    assert not expected.startswith(bytes([0xEF, 0xBB, 0xBF]))


# --------------------------------------------------------------------------- #
# Plan 10-11 Task 1 (tracer): Sections 3 (full report) and 4 (dual universe)
# --------------------------------------------------------------------------- #

M1_LABELS = (
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
KINDS = ("BACKTEST", "PAPER", "LIVE")
LOW_N_LEGEND_TEXT = "LOW_N: n < 30. Flag only; not an acceptance threshold. The row is not hidden."
ESTIMATE_SHAPE = re.compile(
    r"^(?:no data|-?\d+\.\d{4} \[(?:-?\d+\.\d{4}, -?\d+\.\d{4}|interval absent)\] n=\d+)$"
)
FULL_TITLE = "3. Full Report (unsliced)"
DUAL_TITLE = "4. Dual Universe: Live-5 vs Research"


def section_lines(text: str, title: str) -> list[str]:
    """The lines of one H2 section (heading through the line before the next H2)."""
    lines = text.split("\n")
    start = lines.index(f"## {title}")
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def split_cells(line: str) -> list[str]:
    assert line.startswith("| ") and line.endswith(" |"), line
    return line[2:-2].split(" | ")


def data_rows(table: list[str]) -> list[list[str]]:
    return [split_cells(line) for line in table[2:]]


def with_backtest_outcomes(outcomes):  # type: ignore[no-untyped-def]
    base = build_report_inputs()
    return make_report(backtest=dataclasses.replace(base.backtest, outcomes=tuple(outcomes)))


def base_outcomes():  # type: ignore[no-untyped-def]
    return list(build_report_inputs().backtest.outcomes)


def m1_rows(text: str, title: str, heading: str) -> dict[str, list[str]]:
    rows = data_rows(table_after(section_lines(text, title), heading))
    return {row[0]: row for row in rows}


def test_section3_heading_note_and_per_kind_headings_and_captions() -> None:
    text = render_markdown(make_report())
    lines = section_lines(text, FULL_TITLE)
    assert lines[0] == "## 3. Full Report (unsliced)"
    assert lines[2] == (
        "All figures are descriptive and carry uncertainty. "
        "Nothing here changes parameters or ranks strategy families."
    )
    headings = [line for line in lines if line.startswith("### ")]
    assert headings == [f"### 3.{index} {kind}" for index, kind in enumerate(KINDS, start=1)]
    for index, kind in enumerate(KINDS, start=1):
        at = lines.index(f"### 3.{index} {kind}")
        assert lines[at + 2] == f"*Evidence: {kind}*"
    header = "| Metric | Value | n | Low-n | Note |"
    assert lines.count(header) == 3
    assert lines[lines.index(header) + 1] == "| :--- | :--- | ---: | :--- | :--- |"


def test_section3_full_report_m1_row_labels_in_exact_order_for_every_kind() -> None:
    lines = section_lines(render_markdown(make_report()), FULL_TITLE)
    for index, kind in enumerate(KINDS, start=1):
        rows = data_rows(table_after(lines, f"### 3.{index} {kind}"))
        assert [row[0] for row in rows] == list(M1_LABELS)
        assert all(len(row) == 5 for row in rows)


def test_section3_backtest_values_match_core_metrics_and_low_n_flags() -> None:
    report = make_report()
    rows = m1_rows(render_markdown(report), FULL_TITLE, "### 3.1 BACKTEST")
    assert rows["Trades (n)"] == ["Trades (n)", "2", "2", "", ""]
    assert rows["R-valued trades"][1:3] == ["2", "2"]
    assert rows["Zero-risk excluded"][1] == "0"
    assert rows["INCOMPLETE"][1] == "0"
    assert rows["Mean R"][1] == "0.8000 [0.8000, 0.8000] n=2"
    assert rows["Mean R"][2] == "2"
    assert rows["Median R"][1] == "0.8000"
    assert rows["Win rate"][1] == "1.0000"
    assert rows["Expectancy (R)"][1] == "0.8000"
    assert rows["Max drawdown (R)"][1] == "0.0000"
    assert rows["Loss streak (max)"][1] == "0"
    assert report.evidence[0].core.low_n is True
    for label in ("Mean R", "Median R", "Win rate", "Expectancy (R)", "Max drawdown (R)"):
        assert rows[label][3] == "LOW_N"
    for label in ("Trades (n)", "R-valued trades", "Zero-risk excluded", "INCOMPLETE"):
        assert rows[label][3] == ""


def test_section3_estimate_cell_shapes_for_n0_n1_and_n2() -> None:
    outcomes = base_outcomes()
    two = render_markdown(with_backtest_outcomes(outcomes))
    one = render_markdown(with_backtest_outcomes(outcomes[:1]))
    zero = render_markdown(with_backtest_outcomes([]))
    heading = "### 3.1 BACKTEST"
    assert m1_rows(two, FULL_TITLE, heading)["Mean R"][1] == "0.8000 [0.8000, 0.8000] n=2"
    assert m1_rows(two, FULL_TITLE, heading)["Mean R"][4] == ""
    assert m1_rows(one, FULL_TITLE, heading)["Mean R"][1] == "0.8000 [interval absent] n=1"
    assert (
        m1_rows(one, FULL_TITLE, heading)["Mean R"][4]
        == "interval absent (fewer than 2 R-valued trades)"
    )
    assert m1_rows(zero, FULL_TITLE, heading)["Mean R"][1] == "no data"
    for text in (two, one, zero):
        assert ESTIMATE_SHAPE.match(m1_rows(text, FULL_TITLE, heading)["Mean R"][1])


def test_section3_zero_risk_sentence_low_n_legend_and_empty_kind_sentence() -> None:
    outcomes = base_outcomes()
    zero_risk = dataclasses.replace(outcomes[1], realized_risk=Decimal("0"))
    text = render_markdown(with_backtest_outcomes([outcomes[0], zero_risk]))
    lines = section_lines(text, FULL_TITLE)
    rows = m1_rows(text, FULL_TITLE, "### 3.1 BACKTEST")
    assert rows["Zero-risk excluded"][1] == "1"
    assert rows["Trades (n)"][1] == "2"
    assert rows["R-valued trades"][1] == "1"
    sentence = (
        "Zero-risk excluded: 1. These trades have no defined R and are counted here, not dropped."
    )
    assert lines.count(sentence) == 1
    normal = section_lines(render_markdown(make_report()), FULL_TITLE)
    assert not any(line.startswith("Zero-risk excluded:") for line in normal)
    assert LOW_N_LEGEND_TEXT in normal
    live = "No LIVE rows exist for this evidence kind. Nothing is imputed, hidden, or pooled."
    assert live in normal
    assert live.replace("LIVE", "BACKTEST") not in normal


def test_section4_dual_universe_symbol_lines_and_columns() -> None:
    report = make_report()
    lines = section_lines(render_markdown(report), DUAL_TITLE)
    assert lines[0] == "## 4. Dual Universe: Live-5 vs Research"
    assert "Live-5: BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT" in lines
    view = report.evidence[0].dual_universe
    assert (
        "Research universe: ADAUSDT, BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT "
        f"(universe hash {view.universe_hash[:12]}; VERIFIED)"
    ) in lines
    headings = [line for line in lines if line.startswith("### ")]
    assert headings == [f"### 4.{index} {kind}" for index, kind in enumerate(KINDS, start=1)]
    header = (
        "| Metric | Live-5 value | Live-5 n | Research value | Research n "
        "| Low-n (Live-5 / Research) |"
    )
    assert lines.count(header) == 3
    for index, kind in enumerate(KINDS, start=1):
        at = lines.index(f"### 4.{index} {kind}")
        assert lines[at + 2] == f"*Evidence: {kind}*"
        rows = data_rows(table_after(lines, f"### 4.{index} {kind}"))
        assert [row[0] for row in rows] == list(M1_LABELS)


def test_section4_backtest_values_equal_section3_for_the_same_metric_block() -> None:
    text = render_markdown(make_report())
    full = m1_rows(text, FULL_TITLE, "### 3.1 BACKTEST")
    dual = m1_rows(text, DUAL_TITLE, "### 4.1 BACKTEST")
    # Both universes hold the same two trades in the composite fixture.
    for label in M1_LABELS:
        assert dual[label][1] == dual[label][3]
        assert dual[label][2] == dual[label][4]
    for label in ("Mean R", "Median R", "Win rate", "Expectancy (R)", "Max drawdown (R)"):
        assert dual[label][1] == full[label][1]
        assert dual[label][5] == "LOW_N / LOW_N"
    assert dual["Trades (n)"][5] == "- / -"
    assert dual["Trades (n)"][1] == full["Trades (n)"][1] == "2"


def test_section4_empty_live5_cells_note_and_zero_n() -> None:
    lines = section_lines(render_markdown(make_report()), DUAL_TITLE)
    note = "Live-5 slice has no rows for this evidence kind. Nothing is imputed or hidden."
    assert lines.count(note) == 2  # PAPER and LIVE only; BACKTEST has live-5 rows
    for index, kind in ((2, "PAPER"), (3, "LIVE")):
        for row in data_rows(table_after(lines, f"### 4.{index} {kind}")):
            assert row[1] == "no data" and row[2] == "0", row
            assert row[3] == "no data" and row[4] == "0", row
    backtest = lines.index("### 4.1 BACKTEST")
    assert note not in lines[backtest : lines.index("### 4.2 PAPER")]


def test_section4_weak_live_universe_line_only_when_flagged() -> None:
    outcomes = base_outcomes()
    losing = dataclasses.replace(outcomes[0], realized_pnl=Decimal("-8.00"))
    ada_1 = dataclasses.replace(outcomes[1], trade_id="T-ADA-1", symbol="ADAUSDT")
    ada_2 = dataclasses.replace(outcomes[1], trade_id="T-ADA-2", symbol="ADAUSDT")
    report = with_backtest_outcomes([losing, ada_1, ada_2])
    assert report.evidence[0].dual_universe.weak_live_universe_rejection is True
    weak = (
        "Weak live-5 universe: research-universe results alone do not support acceptance "
        "(BACKTEST_SPEC section 10.1)."
    )
    lines = section_lines(render_markdown(report), DUAL_TITLE)
    assert lines.count(weak) == 1
    plain = section_lines(render_markdown(make_report()), DUAL_TITLE)
    assert weak not in plain


def test_tracer_sections_3_and_4() -> None:
    text = render_markdown(make_report())
    order = [text.index(f"## {title}") for title in SECTION_TITLES[:4]]
    assert order == sorted(order)
    assert text.index("## 3. Full Report (unsliced)") > text.index("## 2. Evidence Overview")
    # No bare estimate: every Mean R cell in sections 3 and 4 has the estimate shape.
    body_lines = section_lines(text, FULL_TITLE) + section_lines(text, DUAL_TITLE)
    mean_lines = [line for line in body_lines if line.startswith("| Mean R |")]
    assert len(mean_lines) == 6
    for line in mean_lines:
        cells = split_cells(line)
        value_cells = [cells[1]] if len(cells) == 5 else [cells[1], cells[3]]
        for cell in value_cells:
            assert ESTIMATE_SHAPE.match(cell), line
    assert find_reserved("\n".join(body_lines)) == []
    assert render_markdown(make_report()) == text
