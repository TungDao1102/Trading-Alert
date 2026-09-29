"""Offline Markdown report composition (Phase 10, plan 10-10, D-04).

`render_markdown` is a pure function of a `JournalDepthReport`: no clock, no locale, no
filesystem. It emits the H1, the header table and the sections in the fixed UI-SPEC order,
separated by a blank line, a `---` rule and a blank line. Output is UTF-8 text with LF line
endings, one trailing LF and no trailing whitespace; the caller writes it with `newline="\\n"`.
"""

from __future__ import annotations

from src.analytics.render_common import SECTION_TITLES, RenderError
from src.analytics.render_killgate import (
    render_header,
    render_section_evidence_overview,
    render_section_kill_gate,
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


def render_markdown(report: JournalDepthReport) -> str:
    """Render the report; sections 3-10 slot in here as their renderers land."""
    lines = [f"# {REPORT_TITLE}", "", *render_header(report)]
    sections = (
        render_section_kill_gate(report),
        render_section_evidence_overview(report),
    )
    for section in sections:
        lines.extend(["", "---", "", *section])
    text = "\n".join(lines) + "\n"
    _check_byte_rules(text)
    return text
