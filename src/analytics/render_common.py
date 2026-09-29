"""Shared formatting and escaping primitives for the offline report renderer (Phase 10, plan 10-10).

Everything here is a pure function of its arguments: no clock, no locale, no host, no path,
no float. The number formats, fixed sentences and escape rules are copied from the
`10-UI-SPEC.md` Typography, Copywriting and Determinism sections; changing any digit count or
wording changes every rendered digest and golden fixture.

Text that comes from the database, the journal or a decision record must pass `md_cell`
before it is placed in a table cell or a line of prose. `md_table` accepts only pre-escaped
text and refuses a cell that would break the table shape.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from zoneinfo import ZoneInfo

from src.analytics.types import AnalyticsInputError, Estimate, EvidenceKind, _require_utc

__all__ = [
    "DISPLAY_TZ_NAME",
    "MAX_CELL_CHARS",
    "NO_DATA",
    "READ_ONLY_STATEMENT",
    "SECTION_TITLES",
    "TIMEZONE_NOTE",
    "TRUNCATION_MARKER",
    "RenderError",
    "evidence_caption",
    "fmt_bps",
    "fmt_display",
    "fmt_estimate",
    "fmt_int",
    "fmt_months",
    "fmt_pct",
    "fmt_price",
    "fmt_r",
    "fmt_seconds",
    "fmt_utc",
    "join_blocks",
    "md_cell",
    "md_cell_truncated",
    "md_table",
]

NO_DATA = "no data"
TRUNCATION_MARKER = "...[truncated]"
MAX_CELL_CHARS = 200
DISPLAY_TZ_NAME = "Asia/Ho_Chi_Minh"

TIMEZONE_NOTE = (
    "Stored and computed values are UTC. Display times are Asia/Ho_Chi_Minh (UTC+07:00, no DST)."
)
READ_ONLY_STATEMENT = (
    "This report is read-only. It never changes parameters, orders, or approvals, "
    "and it never enables live trading."
)

# The ten fixed H2 headings, in the fixed UI-SPEC order. Sections never move or vanish.
SECTION_TITLES: tuple[str, ...] = (
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

_ALIGNMENTS = (":---", "---:")
_QUANTUM_4DP = "0.0001"
_QUANTUM_2DP = "0.01"
_QUANTUM_1DP = "0.1"
_DECIMAL_PRECISION = 28

_ESCAPES = {
    "\\": "\\\\",
    "|": "\\|",
    "`": "'",
    "<": "&lt;",
    ">": "&gt;",
}
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_SPACE_CATEGORIES = frozenset({"Zl", "Zp"})


class RenderError(ValueError):
    """A rendered document violated a byte-level rule (an internal invariant)."""


def _clean(text: str) -> str:
    """Line breaks and tabs become one space; other control/format characters are dropped."""
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if char in "\r\n\t" or category in _SPACE_CATEGORIES:
            kept.append(" ")
        elif category in _DROPPED_CATEGORIES:
            continue
        else:
            kept.append(char)
    return "".join(kept).strip(" ")


def md_cell_truncated(text: str) -> bool:
    """True when `md_cell(text)` cuts the text at the length limit."""
    return len(_clean(text)) > MAX_CELL_CHARS


def md_cell(text: str) -> str:
    """The single escape for database, journal and decision text.

    Pipes and backslashes are escaped, line breaks and tabs become one space, backticks
    become apostrophes, angle brackets become entities, control and format characters are
    dropped, and the text is cut at 200 characters with a fixed marker. The cut happens
    before escaping so an escape sequence is never split.
    """
    if not isinstance(text, str):
        raise AnalyticsInputError(f"md_cell requires str, got {type(text).__name__}")
    cleaned = _clean(text)
    truncated = len(cleaned) > MAX_CELL_CHARS
    if truncated:
        cleaned = cleaned[:MAX_CELL_CHARS]
    escaped = "".join(_ESCAPES.get(char, char) for char in cleaned)
    return escaped + TRUNCATION_MARKER if truncated else escaped


def _finite(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise AnalyticsInputError(f"{name} requires a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise AnalyticsInputError(f"{name} requires a finite Decimal, got {value}")
    return value


def _fixed(value: Decimal | None, quantum: str, name: str) -> str:
    if value is None:
        return NO_DATA
    finite = _finite(value, name)
    try:
        with localcontext() as context:
            context.prec = _DECIMAL_PRECISION
            rounded = finite.quantize(Decimal(quantum), rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise AnalyticsInputError(f"{name} cannot be formatted: {finite}") from exc
    if rounded.is_zero():
        rounded = rounded.copy_abs()
    return format(rounded, "f")


def fmt_r(value: Decimal | None) -> str:
    """R multiple, win rate as a fraction, expectancy: 4 dp, half-even, never '-0.0000'."""
    return _fixed(value, _QUANTUM_4DP, "fmt_r")


def fmt_pct(value: Decimal | None) -> str:
    """A value already expressed in percent: 2 dp plus the percent sign."""
    text = _fixed(value, _QUANTUM_2DP, "fmt_pct")
    return text if text == NO_DATA else text + "%"


def fmt_seconds(value: Decimal | None) -> str:
    """Seconds, 1 dp; the unit lives in the column header."""
    return _fixed(value, _QUANTUM_1DP, "fmt_seconds")


def fmt_bps(value: Decimal | None) -> str:
    """Basis points, 2 dp."""
    return _fixed(value, _QUANTUM_2DP, "fmt_bps")


def fmt_months(value: Decimal | None) -> str:
    """Months elapsed, 1 dp."""
    return _fixed(value, _QUANTUM_1DP, "fmt_months")


def fmt_price(value: Decimal | None) -> str:
    """Price, quantity or PnL exactly as stored: no exponent, no grouping, no negative zero."""
    if value is None:
        return NO_DATA
    finite = _finite(value, "fmt_price")
    return format(finite.copy_abs() if finite.is_zero() else finite, "f")


def fmt_int(value: int | None) -> str:
    """A plain count."""
    if value is None:
        return NO_DATA
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnalyticsInputError(f"fmt_int requires an int, got {type(value).__name__}")
    return str(value)


def fmt_estimate(estimate: Estimate, fmt: Callable[[Decimal | None], str]) -> str:
    """`<value> [<lo>, <hi>] n=<n>`; a bare number is never produced."""
    if estimate.n_valued == 0 or estimate.value is None:
        return NO_DATA
    if estimate.interval_absent or estimate.lo is None or estimate.hi is None:
        return f"{fmt(estimate.value)} [interval absent] n={estimate.n_valued}"
    return f"{fmt(estimate.value)} [{fmt(estimate.lo)}, {fmt(estimate.hi)}] n={estimate.n_valued}"


def _stamp(moment: datetime, separator: str) -> str:
    return (
        f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}{separator}"
        f"{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}"
    )


def fmt_utc(moment: datetime) -> str:
    """`YYYY-MM-DDTHH:MM:SS+00:00` from numeric fields (sub-second detail stays in the sidecar)."""
    _require_utc(moment, "moment")
    return _stamp(moment, "T") + "+00:00"


def fmt_display(moment: datetime) -> str:
    """`YYYY-MM-DD HH:MM:SS +07:00` in Asia/Ho_Chi_Minh, converted only here, at the edge."""
    _require_utc(moment, "moment")
    local = moment.astimezone(ZoneInfo(DISPLAY_TZ_NAME))
    offset = local.utcoffset()
    if offset is None:
        raise AnalyticsInputError("display timezone has no UTC offset")
    minutes = offset // timedelta(minutes=1)
    sign = "+" if minutes >= 0 else "-"
    hours, remainder = divmod(abs(minutes), 60)
    return _stamp(local, " ") + f" {sign}{hours:02d}:{remainder:02d}"


def evidence_caption(kind: EvidenceKind | None = None) -> str:
    """The italic one-line evidence caption placed above a table."""
    if kind is None:
        return "*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*"
    return f"*Evidence: {kind.value}*"


def _check_cell(cell: object) -> str:
    if not isinstance(cell, str):
        raise AnalyticsInputError(f"table cells must be str, got {type(cell).__name__}")
    if "\n" in cell or "\r" in cell:
        raise AnalyticsInputError("table cell contains a line break; pass text through md_cell")
    index = 0
    while index < len(cell):
        char = cell[index]
        if char == "\\":
            index += 2
            continue
        if char == "|":
            raise AnalyticsInputError("table cell contains an unescaped pipe; use md_cell")
        index += 1
    return cell


def md_table(
    headers: Sequence[str], aligns: Sequence[str], rows: Sequence[Sequence[str]]
) -> list[str]:
    """A GFM table as lines: header, alignment row, then one line per row.

    Alignment tokens are `:---` (text, left) or `---:` (numeric, right). Every cell must be
    pre-escaped text; each cell is padded with one space on each side of the pipes.
    """
    if len(headers) == 0 or len(headers) != len(aligns):
        raise AnalyticsInputError("headers and aligns must be non-empty and the same length")
    for align in aligns:
        if align not in _ALIGNMENTS:
            raise AnalyticsInputError(f"alignment must be one of {_ALIGNMENTS}, got {align!r}")
    lines = [_row(headers), _row(aligns)]
    for row in rows:
        if len(row) != len(headers):
            raise AnalyticsInputError(
                f"table row has {len(row)} cells, expected {len(headers)}: {list(row)!r}"
            )
        lines.append(_row(row))
    return lines


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(_check_cell(cell) for cell in cells) + " |"


def join_blocks(blocks: Sequence[Sequence[str]]) -> list[str]:
    """Join blocks of lines with exactly one blank line between them (empty blocks skipped)."""
    lines: list[str] = []
    for block in blocks:
        if not block:
            continue
        if lines:
            lines.append("")
        lines.extend(block)
    return lines
