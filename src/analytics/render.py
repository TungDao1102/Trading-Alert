"""Offline Markdown report composition (Phase 10, plans 10-10 and 10-11, D-04).

`render_markdown` is a pure function of a `JournalDepthReport`: no clock, no locale, no
filesystem. It emits the H1, the header table and all ten sections in the fixed UI-SPEC order,
separated by a blank line, a `---` rule and a blank line; every section renders even when its
data is empty. Output is UTF-8 text with LF line endings, one trailing LF and no trailing
whitespace; the caller writes it with `newline="\\n"`.
"""

from __future__ import annotations

from src.analytics.render_common import (
    DISPLAY_TZ_NAME,
    SECTION_TITLES,
    TRUNCATION_MARKER,
    RenderError,
    join_blocks,
    md_cell,
)
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
from src.analytics.types import EvidenceKind

__all__ = [
    "REPORT_TITLE",
    "SECTION_TITLES",
    "render_markdown",
    "render_telegram_pointer",
    "report_file_stem",
]

REPORT_TITLE = "Journal Depth + Kill-Gate Report"
_STEM_DIGEST_CHARS = 12
SOAK_EVIDENCE_SENTENCE = "Soak evidence never feeds a value into trading logic (D-18)."
TEST_ONLY_EXCLUDED_LINE = "test_only records excluded: {count} (D063 item 3)"


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


def _paper_statements(report: JournalDepthReport) -> list[str]:
    """Plain-text statements about the PAPER evidence, printed under the evidence overview.

    Only data the report already carries is stated: that SHADOW soak evidence is present and
    never feeds a value into trading logic (D-18), and the number of `test_only` rehearsal rows
    that were excluded before any count (REV-03, D063 item 3). Nothing here is a metric.
    """
    paper = next(block for block in report.evidence if block.kind is EvidenceKind.PAPER)
    lines: list[list[str]] = []
    if paper.shadow_records > 0:
        lines.append([SOAK_EVIDENCE_SENTENCE])
    if paper.test_only_excluded > 0:
        lines.append([TEST_ONLY_EXCLUDED_LINE.format(count=paper.test_only_excluded)])
    return join_blocks(lines)


def render_markdown(report: JournalDepthReport, blocked_by: tuple[str, ...] = ()) -> str:
    """Render the full report: header, then sections 1-10 in the fixed order.

    `blocked_by` (D061 F) lists unresolved review items: the kill-gate verdict is then replaced
    by a NOT CONCLUDED marker in the header and in section 1; every other section is unchanged.
    """
    rendered = [
        render_section_kill_gate(report, blocked_by),
        join_blocks([render_section_evidence_overview(report), _paper_statements(report)]),
        render_section_full_report(report),
        render_section_dual_universe(report),
        render_section_approval_delay(report),
        render_section_execution_quality(report),
        render_section_mfe_mae(report),
        render_section_slices(report),
        [],  # section 9 needs the truncation count of every other section
        render_section_provenance(report),
    ]
    header = render_header(report, blocked_by)
    rendered[8] = render_section_incomplete(report, _count_truncations([header, *rendered]))
    if len(rendered) != len(SECTION_TITLES):
        raise RenderError("rendered section count does not match SECTION_TITLES")
    lines = [f"# {REPORT_TITLE}", "", *header]
    for section in rendered:
        lines.extend(["", "---", "", *section])
    text = "\n".join(lines) + "\n"
    _check_byte_rules(text)
    return text


def report_file_stem(report: JournalDepthReport) -> str:
    """`journal-depth-<YYYYMMDDTHHMMSSZ>-<digest12>` from the injected as-of and the digest."""
    moment = report.as_of_utc
    compact = (
        f"{moment.year:04d}{moment.month:02d}{moment.day:02d}"
        f"T{moment.hour:02d}{moment.minute:02d}{moment.second:02d}Z"
    )
    return f"journal-depth-{compact}-{report.digest()[:_STEM_DIGEST_CHARS]}"


def render_telegram_pointer(report: JournalDepthReport, file_name: str) -> str:
    """Plain-text pointer to a generated report. Formatter only: no send is wired to it.

    The text names the kill-gate state, a digest prefix and the file name, and says it is not a
    decision or approval. It carries no buttons, callback data or approval wording, so it can
    never act as a decision surface. The existing notify Protocol only sends inline-keyboard
    messages, so a plain-text send needs a new adapter helper, which is deferred (D-04).
    """
    return (
        f"Journal depth report ready. Kill gate: {report.kill_gate.verdict.state.value}. "
        f"Digest {report.digest()[:_STEM_DIGEST_CHARS]}. File: {md_cell(file_name)}. "
        "Open the report to read it; this message is not a decision or approval.\n"
        f"Display: {DISPLAY_TZ_NAME} (UTC internally)"
    )
