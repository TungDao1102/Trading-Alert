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

import pytest
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

# Addendum of 2026-10-16: the orchestrator re-read pages with WebFetch on the new URL pattern
# (the old /docs/derivatives/... paths answer a landing shell or a WAF challenge). A row whose
# Method starts with "WebFetch summary" must cite the working URL, the read date and say that
# the summary is not character-exact.
WEBFETCH_READ_DATE = "2026-10-16"
NOT_CHARACTER_EXACT = "not character-exact"
WORKING_URL_PREFIXES = (
    "https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/",
    "https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/",
)
# Pages the 2026-10-16 WebFetch read covered; their rows are READ, not UNVERIFIED.
WEBFETCH_READ_SUFFIXES = (
    "user-data-streams/Start-User-Data-Stream",
    "user-data-streams/Keepalive-User-Data-Stream",
    "user-data-streams/Event-Listen-Key-Expired",
    "trade/rest-api/Change-Position-Mode",
    "error-code",
    "general-info",
    "trade/rest-api/Query-Algo-Order",
    "change-log",
)
# Facts the 2026-10-16 read contradicts in the research baseline; each must be named as such.
BASELINE_CONTRADICTIONS = ("/private/ws/<listenKey>", "settlement_autoclose")
CONTRADICTS = "CONTRADICTS the research baseline"
# Items the research relied on that the 2026-10-16 read found absent from the pages read.
CONFIRMED_ABSENCES = ("Retry-After", "-4509")
ABSENT = "absent from the page"

# Plan 18-25: the subsection that holds the facts observed on Demo (smoke and probe). Its rows
# are the only rows of the Phase 18 section that may carry a Demo method label.
DEMO_SUBSECTION_TITLE = "Demo-observed facts"
DEMO_LABELS = ("Demo probe", "Demo smoke")
NOT_VERIFIED_ON_MAINNET = "not verified on mainnet"
NOT_MAINNET = "not mainnet"
NO_DEMO_FACTS_SENTENCE = "No Demo-observed facts were recorded:"
PHASE18_DIR = REPO_ROOT / ".planning" / "phases" / "18-user-data-stream-error-taxonomy"
EVIDENCE_DIR = PHASE18_DIR / "evidence"
DECISIONS_DIR = PHASE18_DIR / "decisions"
# The tests that read the phase's decision and evidence files skip, with a reason, when
# `/gsd-cleanup` archived the directory or `/gsd-pr-branch` left `.planning/` out (review WR-05).
requires_phase18_planning = pytest.mark.skipif(
    not PHASE18_DIR.is_dir(),
    reason="the Phase 18 planning directory is not in this checkout (archived or filtered)",
)
EVIDENCE_FILE_NAME = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9._-]*\.(?:json|txt))\b")

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
        header = cells and cells[0] in ("Source URL", "Source (evidence file)")
        if cells and (header or set(cells[0]) <= {"-", " ", ":"}):
            continue
        rows.append(cells)
    return rows


def _split_demo_subsection(body: str) -> tuple[str, str]:
    """(body before the Demo-observed subsection, the subsection body; "" when absent)."""
    match = re.search(rf"^### {re.escape(DEMO_SUBSECTION_TITLE)}[^\n]*\n", body, flags=re.MULTILINE)
    if match is None:
        return body, ""
    rest = body[match.end() :]
    nxt = re.search(r"^##", rest, flags=re.MULTILINE)
    return body[: match.start()], (rest[: nxt.start()] if nxt else rest)


def _sources_text() -> str:
    return SOURCES.read_text(encoding="utf-8")


def _phase18_rows() -> list[list[str]]:
    body = _section(_sources_text(), PHASE18_TITLE_PREFIX)
    assert body, f"missing section '## {PHASE18_TITLE_PREFIX}...' in docs/SOURCES.md"
    # The "Demo-observed facts" subsection (plan 18-25) has its own row shape and its own tests.
    rows = _rows(_split_demo_subsection(body)[0])
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


def _row_urls(cells: list[str]) -> list[str]:
    return [u.split("#", 1)[0].rstrip("/.,;") for u in HTTPS_URL.findall(cells[0])]


def test_phase18_webfetch_rows_cite_working_url_date_and_precision() -> None:
    for cells in _phase18_rows():
        method = cells[3]
        if not method.startswith("WebFetch summary"):
            continue
        urls = HTTPS_URL.findall(cells[0])
        assert any(u.startswith(WORKING_URL_PREFIXES) for u in urls), cells[0]
        assert WEBFETCH_READ_DATE in cells[2], cells[2]
        assert NOT_CHARACTER_EXACT in method, method


def test_phase18_addendum_pages_are_recorded_as_read() -> None:
    rows = _phase18_rows()
    for suffix in WEBFETCH_READ_SUFFIXES:
        matching = [c for c in rows if any(u.endswith("/" + suffix) for u in _row_urls(c))]
        assert matching, suffix
        assert all(c[3].startswith("WebFetch summary") for c in matching), suffix


def test_phase18_section_names_the_baseline_contradictions() -> None:
    rows = _phase18_rows()
    for fact in BASELINE_CONTRADICTIONS:
        assert any(
            fact in exchange.normalise(c[1]) and CONTRADICTS in exchange.normalise(c[1])
            for c in rows
        ), fact
    for fact in CONFIRMED_ABSENCES:
        assert any(
            fact in exchange.normalise(c[1]) and ABSENT in exchange.normalise(c[1]) for c in rows
        ), fact


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


# --------------------------------------------------------------------------- Plan 18-25


def _decision_text(name: str) -> str:
    path = DECISIONS_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _evidence_text(name: str) -> str:
    path = EVIDENCE_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _smoke_ran() -> bool:
    """The plan 18-25 rule: decided from the files, not from memory."""
    check = _evidence_text("18-smoke-check.txt")
    return (
        "option: postpone" not in _decision_text("18-DEC-O-18-03-smoke.md")
        and bool(check)
        and "smoke postponed by the user" not in check
    )


def _probe_ran() -> bool:
    check = _evidence_text("18-probe-check.txt")
    return (
        "option: postpone" not in _decision_text("18-DEC-O-18-03.md")
        and bool(check)
        and "probe postponed by the user" not in check
    )


def demo_subsection_problems(sources_text: str, *, smoke_ran: bool, probe_ran: bool) -> list[str]:
    """Every rule the "Demo-observed facts" subsection must satisfy; empty when it is fine."""
    body = _section(sources_text, PHASE18_TITLE_PREFIX)
    main_body, demo_body = _split_demo_subsection(body)
    problems: list[str] = []
    # A Demo label belongs to the subsection only: no row of the main table may carry one.
    for cells in _rows(main_body):
        if len(cells) == 4 and any(label in cells[3] for label in DEMO_LABELS):
            problems.append(f"Demo label outside the subsection: {cells[0][:80]}")
    if not demo_body.strip():
        return [*problems, "the subsection 'Demo-observed facts' is absent"]
    rows = _rows(demo_body)
    if not smoke_ran and not probe_ran:
        if rows:
            problems.append("rows although neither run happened")
        if NO_DEMO_FACTS_SENTENCE not in demo_body:
            problems.append("missing the 'No Demo-observed facts were recorded' sentence")
        return problems
    if not rows:
        problems.append("no Demo-observed rows although a run happened")
    labels_seen: set[str] = set()
    for cells in rows:
        if len(cells) != 4:
            problems.append(f"row is not four columns: {cells[:1]}")
            continue
        source, used_for, checked_on, method = cells
        label = next((lab for lab in DEMO_LABELS if method.startswith(lab)), None)
        if label is None:
            problems.append(f"method does not start with a Demo label: {method[:60]}")
            continue
        labels_seen.add(label)
        if not source.startswith(f"{label} evidence "):
            problems.append(f"source does not start with '{label} evidence ': {source[:60]}")
        names = EVIDENCE_FILE_NAME.findall(source)
        if not names:
            problems.append(f"no evidence file name in the source cell: {source[:60]}")
        for name in names:
            if not (EVIDENCE_DIR / name).exists():
                problems.append(f"evidence file does not exist: {name}")
        if label == "Demo probe" and not any(n.startswith("demo-probe-EVIDENCE-") for n in names):
            problems.append(f"a probe row must cite a demo-probe-EVIDENCE file: {source[:60]}")
        if label == "Demo smoke" and not any(
            n.startswith("user-data-smoke-EVIDENCE-") for n in names
        ):
            problems.append(f"a smoke row must cite a user-data-smoke-EVIDENCE file: {source[:60]}")
        if NOT_VERIFIED_ON_MAINNET not in method or NOT_MAINNET not in method:
            problems.append(f"method lacks 'not mainnet' / 'not verified on mainnet': {method}")
        if not ISO_DATE.search(checked_on):
            problems.append(f"no date in Checked on: {checked_on}")
        if not used_for.strip():
            problems.append("empty Used for cell")
        if HTTPS_URL.search(source):
            problems.append(f"a Demo row cites a URL as its source: {source[:60]}")
    if smoke_ran and "Demo smoke" not in labels_seen:
        problems.append("the smoke ran and no Demo smoke row exists")
    if probe_ran and "Demo probe" not in labels_seen:
        problems.append("the probe ran and no Demo probe row exists")
    if not smoke_ran and "Demo smoke" in labels_seen:
        problems.append("a Demo smoke row although the smoke was postponed")
    if not probe_ran and "Demo probe" in labels_seen:
        problems.append("a Demo probe row although the probe was postponed")
    return problems


@requires_phase18_planning
def test_run_flags_follow_the_decision_files() -> None:
    # Both runs happened on 2026-10-16 (decision files carry no postponement line).
    assert _smoke_ran()
    assert _probe_ran()


@requires_phase18_planning
def test_demo_observed_subsection_is_accepted() -> None:
    problems = demo_subsection_problems(
        _sources_text(), smoke_ran=_smoke_ran(), probe_ran=_probe_ran()
    )
    assert problems == []


def test_demo_observed_subsection_sits_inside_the_phase18_section_and_carries_a_date() -> None:
    body = _section(_sources_text(), PHASE18_TITLE_PREFIX)
    main_body, demo_body = _split_demo_subsection(body)
    assert demo_body.strip()
    assert "Source URL" in main_body
    heading = re.search(rf"^### {DEMO_SUBSECTION_TITLE}[^\n]*$", body, flags=re.MULTILINE)
    assert heading is not None
    assert ISO_DATE.search(heading.group(0)), heading.group(0)


def test_demo_label_in_a_main_row_is_rejected_negative_control() -> None:
    text = _sources_text().replace("\r\n", "\n")
    marker = "WebFetch summary of the working URL, not character-exact; not verified live."
    assert marker in text
    mutated = text.replace(marker, "Demo probe (not mainnet), " + marker, 1)
    assert mutated != text
    problems = demo_subsection_problems(mutated, smoke_ran=True, probe_ran=True)
    assert any("Demo label outside the subsection" in p for p in problems), problems


def test_demo_row_without_the_mainnet_caveat_is_rejected_negative_control() -> None:
    text = _sources_text().replace("\r\n", "\n")
    row_method = "Demo smoke (not mainnet), REAL_SMOKE evidence, not verified on mainnet"
    assert row_method in text
    mutated = text.replace(row_method, "Demo smoke (not mainnet), REAL_SMOKE evidence, verified", 1)
    assert mutated != text
    problems = demo_subsection_problems(mutated, smoke_ran=True, probe_ran=True)
    assert any("not verified on mainnet" in p for p in problems), problems


def test_demo_row_with_an_unknown_evidence_file_is_rejected_negative_control() -> None:
    text = _sources_text().replace("\r\n", "\n")
    name = "demo-probe-EVIDENCE-20261016T142134Z.json"
    assert name in text
    mutated = text.replace(name, "demo-probe-EVIDENCE-19990101T000000Z.json", 1)
    problems = demo_subsection_problems(mutated, smoke_ran=True, probe_ran=True)
    assert any("evidence file does not exist" in p for p in problems), problems


def test_demo_row_without_an_evidence_file_name_is_rejected_negative_control() -> None:
    text = _sources_text().replace("\r\n", "\n")
    name = "user-data-smoke-EVIDENCE-20261016T140446Z.json"
    assert name in text
    mutated = text.replace(name, "the smoke", 1)
    problems = demo_subsection_problems(mutated, smoke_ran=True, probe_ran=True)
    assert any("must cite a user-data-smoke-EVIDENCE file" in p for p in problems), problems


def test_missing_subsection_is_rejected_negative_control() -> None:
    text = _sources_text().replace("\r\n", "\n")
    mutated = text.replace(f"### {DEMO_SUBSECTION_TITLE}", "### Something else", 1)
    problems = demo_subsection_problems(mutated, smoke_ran=True, probe_ran=True)
    assert any("absent" in p for p in problems), problems


def _with_demo_body(demo_body: str) -> str:
    text = _sources_text().replace("\r\n", "\n")
    body = _section(text, PHASE18_TITLE_PREFIX)
    main_body, old_demo = _split_demo_subsection(body)
    assert old_demo
    heading = re.search(rf"^### {DEMO_SUBSECTION_TITLE}[^\n]*\n", body, flags=re.MULTILINE)
    assert heading is not None
    return text.replace(body, main_body + heading.group(0) + demo_body, 1)


def test_postponed_shape_is_accepted_and_invented_rows_are_rejected() -> None:
    sentence = (
        f"{NO_DEMO_FACTS_SENTENCE} smoke postponed by the user; probe postponed by the user.\n\n"
    )
    shaped = _with_demo_body(sentence)
    assert demo_subsection_problems(shaped, smoke_ran=False, probe_ran=False) == []
    # The same text is wrong when a run did happen (no rows although a run happened).
    assert demo_subsection_problems(shaped, smoke_ran=True, probe_ran=True)
    # Rows kept although both runs are declared postponed are rejected.
    assert demo_subsection_problems(_sources_text(), smoke_ran=False, probe_ran=False)


def test_a_postponed_smoke_leaves_no_smoke_row() -> None:
    problems = demo_subsection_problems(_sources_text(), smoke_ran=False, probe_ran=True)
    assert any("Demo smoke row although the smoke was postponed" in p for p in problems), problems


def test_phase17_live_reread_paragraph_points_at_the_probe_answer() -> None:
    text = _sources_text().replace("\r\n", "\n")
    start = text.index("### Live re-read of the Phase 17 facts")
    end = text.index("\n## ", start)
    section = text[start:end]
    assert "Still NOT verified live" in section
    tail = section.split("Still NOT verified live", 1)[1]
    assert "Phase 18" in tail and "Demo" in tail and "not mainnet" in tail
    assert "-4116" in tail
