"""Offline Markdown report composition (Phase 10, plans 10-10 and 10-11, D-04).

`render_markdown` is a pure function of a `JournalDepthReport`: no clock, no locale, no
filesystem. It emits the H1, the header table and all ten sections in the fixed UI-SPEC order,
separated by a blank line, a `---` rule and a blank line; every section renders even when its
data is empty. Output is UTF-8 text with LF line endings, one trailing LF and no trailing
whitespace; the caller writes it with `newline="\\n"`.
"""

from __future__ import annotations

from src.analytics.render_common import SECTION_TITLES, TRUNCATION_MARKER, RenderError
from src.analytics.render_killgate import (
    render_header,
    render_section_evidence_overview,
    render_section_kill_gate,
)
from src.analytics.render_metrics import (
    render_section_approval_delay,
    render_section_dual_universe,
    render_section_execution_quality,
    render_section_full_report,
    render_section_incomplete,
    render_section_mfe_mae,
    render_section_provenance,
    render_section_slices,
)
from src.analytics.report import JournalDepthReport

__all__ = ["REPORT_TITLE", "SECTION_TITLES", "render_markdown"]

REPORT_TITLE = "Journal Depth + Kill-Gate Report"


def _check_byte_rules(text: str) -> None:
    """Fail closed if the document could differ between platforms or carry stray whitespace."""
    if "\r" in text:
        raise RenderError("rendered report contains a carriage return")
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise RenderError("rendered report must end with exactly one line feed")
    for number, line in enumerate(text.split("\n")[:-1], start=1):
        if line != line.rstrip():
            raise RenderError(f"rendered report line {number} has trailing whitespace")


def _count_truncations(sections: list[list[str]]) -> int:
    """How many cells `md_cell` cut, counted from the fixed marker in the rendered lines."""
    return sum(line.count(TRUNCATION_MARKER) for section in sections for line in section)


def render_markdown(report: JournalDepthReport) -> str:
    """Render the full report: header, then sections 1-10 in the fixed order."""
    rendered = [
        render_section_kill_gate(report),
        render_section_evidence_overview(report),
        render_section_full_report(report),
        render_section_dual_universe(report),
        render_section_approval_delay(report),
        render_section_execution_quality(report),
        render_section_mfe_mae(report),
        render_section_slices(report),
        [],  # section 9 needs the truncation count of every other section
        render_section_provenance(report),
    ]
    header = render_header(report)
    rendered[8] = render_section_incomplete(report, _count_truncations([header, *rendered]))
    if len(rendered) != len(SECTION_TITLES):
        raise RenderError("rendered section count does not match SECTION_TITLES")
    lines = [f"# {REPORT_TITLE}", "", *header]
    for section in rendered:
        lines.extend(["", "---", "", *section])
    text = "\n".join(lines) + "\n"
    _check_byte_rules(text)
    return text
