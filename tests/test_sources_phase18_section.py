"""Structure tests for the "Facts read for Phase 18" section of docs/SOURCES.md (plan 18-01).

The Phase 18 Binance documentation re-reads live in their own section because the exchange
document gate (``scripts/decision_alignment/exchange.py``) reads only the Phase 11 register.
These tests keep the new section honest (URL, read date, method label, "not verified live",
failure text for an unreadable page) and prove the Phase 11 register is byte-identical.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from scripts.decision_alignment import exchange

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES = REPO_ROOT / "docs" / "SOURCES.md"

PHASE18_TITLE_PREFIX = "Facts read for Phase 18"

# sha256 of the Phase 11 section body (LF line endings) computed before plan 18-01 edited
# docs/SOURCES.md. The gate reads this register; it must not change.
PHASE11_SECTION_SHA256 = "248baa07ce1ca934145779374ea057bfee12a7d93857a74111a82343ac3dbbd5"

BINANCE_DOCS_HOST = "developers.binance.com"
METHOD_LABELS = ("WebFetch summary", "installed SDK source", "UNVERIFIED")
NOT_VERIFIED_LIVE = "not verified live"
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
HTTPS_URL = re.compile(r"https://[^\s)>\]\"'`|]+")

REQUIRED_SUFFIXES = (
    "user-data-streams/Start-User-Data-Stream",
    "user-data-streams/Keepalive-User-Data-Stream",
    "websocket-market-streams/Important-WebSocket-Change-Notice",
    "websocket-market-streams/Connect",
    "user-data-streams/Event-Algo-Order-Update",
    "user-data-streams/Event-Order-Update",
    "user-data-streams/Event-Balance-and-Position-Update",
    "user-data-streams/Event-Listen-Key-Expired",
    "trade/rest-api/Change-Position-Mode",
    "error-code",
    "general-info",
    "trade/rest-api/Query-Algo-Order",
    "change-log",
    "websocket-market-streams/Live-Subscribing-Unsubscribing-to-streams",
)

# The nine items of the "UNVERIFIED register" in 18-RESEARCH.md; each needs a status line.
UNVERIFIED_REGISTER_ITEMS = range(1, 10)
ITEM_STATUS = re.compile(r"^- item (\d+): (now READ|still UNVERIFIED) \(\S", flags=re.MULTILINE)


def _section(text: str, title_prefix: str) -> str:
    """Body of the first ``## <title_prefix>...`` section, up to the next ``##`` heading."""
    text = text.replace("\r\n", "\n")
    match = re.search(rf"^## {re.escape(title_prefix)}[^\n]*\n", text, flags=re.MULTILINE)
    if match is None:
        return ""
    rest = text[match.end() :]
    nxt = re.search(r"^## ", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _heading(text: str, title_prefix: str) -> str:
    match = re.search(
        rf"^## ({re.escape(title_prefix)}[^\n]*)$",
        text.replace("\r\n", "\n"),
        flags=re.MULTILINE,
    )
    return match.group(1) if match else ""


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _rows(body: str) -> list[list[str]]:
    """Data rows of the section's four-column table (header and separator excluded)."""
    rows: list[list[str]] = []
    for raw in body.splitlines():
        if not raw.startswith("|"):
            continue
        cells = _cells(raw)
        if cells and (cells[0] == "Source URL" or set(cells[0]) <= {"-", " ", ":"}):
            continue
        rows.append(cells)
    return rows


def _sources_text() -> str:
    return SOURCES.read_text(encoding="utf-8")


def _phase18_rows() -> list[list[str]]:
    body = _section(_sources_text(), PHASE18_TITLE_PREFIX)
    assert body, f"missing section '## {PHASE18_TITLE_PREFIX}...' in docs/SOURCES.md"
    rows = _rows(body)
    assert rows, "the Phase 18 section has no table rows"
    return rows


def test_phase18_section_rows() -> None:
    for cells in _phase18_rows():
        assert len(cells) == 4, cells
        url_cell, _used_for, checked_on, method = cells
        urls = HTTPS_URL.findall(url_cell)
        assert any(BINANCE_DOCS_HOST in u for u in urls), url_cell
        assert ISO_DATE.search(checked_on), checked_on
        assert any(label in method for label in METHOD_LABELS), method
        assert NOT_VERIFIED_LIVE in exchange.normalise(" | ".join(cells)), url_cell


def test_phase18_section_lists_every_required_page() -> None:
    first_cells = [cells[0] for cells in _phase18_rows()]
    for suffix in REQUIRED_SUFFIXES:
        assert any(
            u.split("#", 1)[0].rstrip("/.,;").endswith(suffix)
            for cell in first_cells
            for u in HTTPS_URL.findall(cell)
        ), suffix


def test_phase18_section_unverified_rows_have_failure_text() -> None:
    for cells in _phase18_rows():
        method = cells[3]
        if not method.startswith("UNVERIFIED"):
            continue
        match = re.search(r"failure:\s*(\S.*)", method)
        assert match is not None, method
        assert match.group(1).strip(), method


def test_phase18_section_has_a_status_line_per_register_item() -> None:
    body = _section(_sources_text(), PHASE18_TITLE_PREFIX)
    found = [int(m.group(1)) for m in ITEM_STATUS.finditer(body)]
    assert sorted(found) == list(UNVERIFIED_REGISTER_ITEMS), found


def test_phase18_heading_is_not_the_phase11_heading() -> None:
    heading = _heading(_sources_text(), PHASE18_TITLE_PREFIX)
    assert heading.startswith(PHASE18_TITLE_PREFIX)
    assert not heading.startswith(exchange.SOURCES_SECTION_TITLE)


def test_phase11_section_unchanged() -> None:
    body = _section(_sources_text(), exchange.SOURCES_SECTION_TITLE)
    assert body
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == PHASE11_SECTION_SHA256


# --------------------------------------------------------------------------- Task 3

EXECUTION_SPEC = REPO_ROOT / "docs" / "trading" / "EXECUTION_SPEC.md"
BINANCE = REPO_ROOT / "docs" / "integration" / "BINANCE.md"

ALGO_STATUS_ROWS = ("NEW", "TRIGGERING", "TRIGGERED", "FINISHED", "CANCELED", "REJECTED", "EXPIRED")


def test_execution_spec_status_rows() -> None:
    # Same row match as scripts/decision_alignment/exchange.py::check_algo_status.
    section = exchange._section(EXECUTION_SPEC.read_text(encoding="utf-8"), 6)
    rows = {
        m.group(1) for m in re.finditer(r"^\|\s*`?([A-Z_]+)`?\s*\|", section, flags=re.MULTILINE)
    }
    missing = [status for status in ALGO_STATUS_ROWS if status not in rows]
    assert not missing, missing


def test_binance_doc_verify_marker_count() -> None:
    text = exchange.normalise(BINANCE.read_text(encoding="utf-8"))
    assert text.count(exchange.VERIFY_MARKER) >= exchange.VERIFY_MARKER_MINIMUM


def test_execution_spec_cites_no_unregistered_binance_url() -> None:
    name, ok, detail = exchange.check_source_register(
        EXECUTION_SPEC.read_text(encoding="utf-8"), _sources_text()
    )
    assert name == "EX-06"
    assert ok, detail
