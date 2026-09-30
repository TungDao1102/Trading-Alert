"""Exchange-facts documents gate module (Phase 11, plan 11-05; D031, D-13, D-14, D034, D037).

Executable checks that keep the Binance facts in the documents aligned with the dated
official sources recorded in ``docs/SOURCES.md``: the account-wide conditional-order
limit, algo-order trigger-time semantics, the WebSocket URL split, the ``workingType``
default and the symbol filters. ``run()`` returns ``(name, ok, detail)`` tuples
EX-01..EX-08; every check is also a pure function over text so tests can inject good and
bad input.

Required phrases are matched after ``normalise`` (emphasis markers and backticks removed,
whitespace collapsed). Forbidden wording is matched per normalised line.

Stdlib only.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
EXECUTION_SPEC_PATH = DOCS_DIR / "trading" / "EXECUTION_SPEC.md"
SOURCES_PATH = DOCS_DIR / "SOURCES.md"
BINANCE_PATH = DOCS_DIR / "integration" / "BINANCE.md"

Gate = tuple[str, bool, str]

CHANGE_LOG_URL = "https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log"
SOURCES_SECTION_TITLE = "Facts verified for Phase 11 (2026-09-30)"
FETCH_DATE = "2026-09-30"


def normalise(text: str) -> str:
    """Strip ``**`` and backticks, then collapse all whitespace to single spaces."""
    return " ".join(text.replace("**", "").replace("`", "").split())


def _lines(text: str) -> list[str]:
    """Normalised, non-empty lines."""
    out: list[str] = []
    for raw in text.splitlines():
        line = normalise(raw)
        if line:
            out.append(line)
    return out


def _section(text: str, number: int) -> str:
    """Body of the ``## <number>.`` section, up to the next ``## <n>.`` heading."""
    text = text.replace("\r\n", "\n")
    match = re.search(rf"^## {number}\.[^\n]*\n", text, flags=re.MULTILINE)
    if match is None:
        return ""
    rest = text[match.end() :]
    nxt = re.search(r"^## \d+\.", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _titled_section(text: str, title: str) -> str:
    """Body of the ``## <title>`` section, up to the next ``##`` heading."""
    text = text.replace("\r\n", "\n")
    match = re.search(rf"^## {re.escape(title)}[^\n]*\n", text, flags=re.MULTILINE)
    if match is None:
        return ""
    rest = text[match.end() :]
    nxt = re.search(r"^## ", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _missing(text: str, phrases: tuple[str, ...]) -> list[str]:
    haystack = normalise(text)
    return [p for p in phrases if p not in haystack]


def _forbidden_hits(text: str, patterns: tuple[str, ...]) -> list[str]:
    """Normalised lines matching any forbidden regex (case-insensitive)."""
    compiled = [re.compile(p, flags=re.IGNORECASE) for p in patterns]
    return [line for line in _lines(text) if any(c.search(line) for c in compiled)]


def _verdict(name: str, missing: list[str], forbidden: list[str]) -> Gate:
    problems: list[str] = []
    if missing:
        problems.append("missing: " + "; ".join(missing))
    if forbidden:
        problems.append("forbidden: " + "; ".join(forbidden))
    if problems:
        return (name, False, " | ".join(problems))
    return (name, True, "ok")


# --------------------------------------------------------------------------- EX-01

ALGO_LIMIT_PHRASES = (
    "200 open conditional orders",
    "across all symbols",
    "account-wide",
    "not per symbol",
    "2025-12-29",
    "MAX_NUM_ALGO_ORDERS",
    "verify against current Binance docs",
    "F-051",
)
ALGO_LIMIT_FORBIDDEN = (r"200-open-conditional-order limit per symbol",)


def check_algo_limit(text: str) -> Gate:
    """EXECUTION_SPEC section 12: the 200 conditional-order limit is account-wide (F-051)."""
    return _verdict(
        "EX-01",
        _missing(_section(text, 12), ALGO_LIMIT_PHRASES),
        _forbidden_hits(text, ALGO_LIMIT_FORBIDDEN),
    )


# --------------------------------------------------------------------------- EX-02

# Each status must be a row of the section 6.1 status table (first cell), not merely a word
# that appears somewhere in the section.
ALGO_STATUS_ROWS = ("NEW", "TRIGGERING", "FINISHED", "REJECTED", "EXPIRED")

ALGO_STATUS_PHRASES = (
    "FINISHED does not mean filled",
    "ALGO_UPDATE",
    "o.rm",
    "no margin check before",
    "verify against current Binance docs",
    "F-054",
)


def check_algo_status(text: str) -> Gate:
    """EXECUTION_SPEC section 6.1: algo-order status semantics at trigger time (F-054)."""
    section = _section(text, 6)
    rows = {
        m.group(1) for m in re.finditer(r"^\|\s*`?([A-Z_]+)`?\s*\|", section, flags=re.MULTILINE)
    }
    missing = [f"status row {r}" for r in ALGO_STATUS_ROWS if r not in rows]
    return _verdict("EX-02", missing + _missing(section, ALGO_STATUS_PHRASES), [])


# --------------------------------------------------------------------------- EX-03

NEW_ORDER_PATH = "rest-api/New-Order"
POSITION_MODE_PAGE = "rest-api/Change-Position-Mode"


def check_position_mode_citation(text: str) -> Gate:
    """EXECUTION_SPEC section 8: the position-mode sentence cites Change-Position-Mode (F-057)."""
    body = _section(text, 8)
    sentences = [ln for ln in _lines(body) if "position-mode changes" in ln]
    if not sentences:
        return ("EX-03", False, "missing: the sentence about position-mode changes")
    missing: list[str] = []
    forbidden: list[str] = []
    for sentence in sentences:
        if POSITION_MODE_PAGE not in sentence:
            missing.append(f"link to {POSITION_MODE_PAGE}")
        if NEW_ORDER_PATH in sentence:
            forbidden.append(f"position-mode sentence links to {NEW_ORDER_PATH}")
    return _verdict("EX-03", missing, forbidden)


# --------------------------------------------------------------------------- EX-04

ORPHAN_PHRASES = ("not an orphan", "F-401", "re-place", "cancel-only", "D034")


def check_orphan_reconciler(text: str) -> Gate:
    """EXECUTION_SPEC section 9: entry-paired stop is no orphan; reconciler re-places (D034)."""
    return _verdict("EX-04", _missing(_section(text, 9), ORPHAN_PHRASES), [])


# --------------------------------------------------------------------------- EX-05

CONTROLS_PHRASES = ("disable new entry orders", "explicit protect", "SAFE_MODE", "D034")
CONTROLS_FORBIDDEN = (r"disable new live orders",)


def check_emergency_controls(text: str) -> Gate:
    """EXECUTION_SPEC section 11: entry-only disable plus an explicit protect action (D034)."""
    return _verdict(
        "EX-05",
        _missing(_section(text, 11), CONTROLS_PHRASES),
        _forbidden_hits(text, CONTROLS_FORBIDDEN),
    )


# --------------------------------------------------------------------------- EX-06

EXTERNAL_URL = re.compile(r"https?://[^\s)>\]\"'`]+")
CHECKED_HOSTS = ("developers.binance.com", "tradingview.com")


def _canonical_url(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/.,;")


def cited_urls(text: str) -> set[str]:
    """Canonical developers.binance.com and tradingview.com URLs found in ``text``."""
    return {
        _canonical_url(m)
        for m in EXTERNAL_URL.findall(text)
        if any(host in m for host in CHECKED_HOSTS)
    }


def registered_urls(sources_text: str) -> tuple[set[str], list[str]]:
    """URLs in the Phase 11 register whose row carries the fetch date and a method.

    Returns the registered set and the list of rows that lack a date or a method.
    """
    body = _titled_section(sources_text, SOURCES_SECTION_TITLE)
    registered: set[str] = set()
    incomplete: list[str] = []
    for raw in body.splitlines():
        if not raw.startswith("|"):
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        urls = cited_urls(cells[0]) if cells else set()
        if not urls:
            continue
        if len(cells) < 4 or FETCH_DATE not in cells[2] or not cells[3]:
            incomplete.append(cells[0])
            continue
        registered |= urls
    return registered, incomplete


def unfetched_urls(sources_text: str) -> set[str]:
    """URLs in the Phase 11 register whose Method cell says the page was not fetched."""
    body = _titled_section(sources_text, SOURCES_SECTION_TITLE)
    out: set[str] = set()
    for raw in body.splitlines():
        if not raw.startswith("|"):
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[3].lower().startswith("not fetched"):
            out |= cited_urls(cells[0])
    return out


def _unmarked_unfetched_citations(spec_text: str, unfetched: set[str]) -> list[str]:
    """Unfetched URLs cited in a paragraph that lacks the verify marker.

    A page that was never read cannot ground a fact; the citing paragraph must say so.
    """
    bad: set[str] = set()
    for block in re.split(r"\n\s*\n", spec_text.replace("\r\n", "\n")):
        if VERIFY_MARKER in normalise(block):
            continue
        bad |= cited_urls(block) & unfetched
    return sorted(bad)


def check_source_register(spec_text: str, sources_text: str) -> Gate:
    """Every Binance/TradingView URL cited in EXECUTION_SPEC is registered with date and method.

    A URL registered as "Not fetched" is accepted only where the citing paragraph carries
    the ``verify against current Binance docs`` marker.
    """
    registered, incomplete = registered_urls(sources_text)
    unregistered = sorted(u for u in cited_urls(spec_text) if u not in registered)
    problems: list[str] = []
    unmarked = _unmarked_unfetched_citations(spec_text, unfetched_urls(sources_text))
    if unmarked:
        problems.append(
            "cites a not-fetched page without the verify marker: " + "; ".join(unmarked)
        )
    if unregistered:
        problems.append("cited but not registered: " + "; ".join(unregistered))
    if incomplete:
        problems.append("register rows without date or method: " + "; ".join(incomplete))
    if problems:
        return ("EX-06", False, " | ".join(problems))
    return ("EX-06", True, "ok")


# --------------------------------------------------------------------------- EX-06a


def check_sources(text: str) -> Gate:
    """SOURCES.md: the change-log row with fetch date and method under the Phase 11 section."""
    body = _titled_section(text, SOURCES_SECTION_TITLE)
    if not body:
        return ("EX-06a", False, f"missing section '{SOURCES_SECTION_TITLE}'")
    missing = _missing(body, (CHANGE_LOG_URL, FETCH_DATE, "WebFetch"))
    return _verdict("EX-06a", missing, [])


# --------------------------------------------------------------------------- EX-07

VERIFY_MARKER = "verify against current Binance docs"
VERIFY_MARKER_MINIMUM = 3

BINANCE_SECTION_PHRASES: dict[int, tuple[str, ...]] = {
    3: ("/public", "/market", "/private", "listenKey", "2026-04-23", "F-053"),
    5: ("/private", "listenKey"),
    6: ("MARK_PRICE", "CONTRACT_PRICE", "D037"),
    7: ("MARKET_LOT_SIZE", "PERCENT_PRICE", "unverified", "F-056"),
    9: ("EXECUTION_SPEC.md section 6.1", "account-wide"),
}


def check_binance_doc(text: str) -> Gate:
    """BINANCE.md: WebSocket split, workingType default, market filters, verify markers."""
    missing: list[str] = []
    for number, phrases in BINANCE_SECTION_PHRASES.items():
        missing.extend(f"section {number}: {p}" for p in _missing(_section(text, number), phrases))
    count = normalise(text).count(VERIFY_MARKER)
    if count < VERIFY_MARKER_MINIMUM:
        missing.append(f"'{VERIFY_MARKER}' x{VERIFY_MARKER_MINIMUM} (found {count})")
    return _verdict("EX-07", missing, [])


# --------------------------------------------------------------------------- EX-08

COIN_FUTURES_MARKER = "derivatives-trading-coin-futures"


def check_no_coin_futures_links(texts: dict[str, str]) -> Gate:
    """No document under docs/ cites a coin-futures path for a USD-M statement (F-057)."""
    offenders = sorted(name for name, body in texts.items() if COIN_FUTURES_MARKER in body)
    if offenders:
        return ("EX-08", False, "coin-futures citation in: " + "; ".join(offenders))
    return ("EX-08", True, "ok")


# --------------------------------------------------------------------------- run


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run() -> list[Gate]:
    """Evaluate every gate against the real repository documents."""
    spec = _read(EXECUTION_SPEC_PATH)
    sources = _read(SOURCES_PATH)
    return [
        check_algo_limit(spec),
        check_algo_status(spec),
        check_position_mode_citation(spec),
        check_orphan_reconciler(spec),
        check_emergency_controls(spec),
        check_source_register(spec, sources),
        check_sources(sources),
        check_binance_doc(_read(BINANCE_PATH)),
        check_no_coin_futures_links(
            {
                path.relative_to(REPO_ROOT).as_posix(): _read(path)
                for path in sorted(DOCS_DIR.rglob("*.md"))
            }
        ),
    ]


if __name__ == "__main__":  # pragma: no cover
    import sys

    results = run()
    for gate_name, gate_ok, gate_detail in results:
        print(("PASS" if gate_ok else "FAIL"), gate_name, gate_detail)
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
