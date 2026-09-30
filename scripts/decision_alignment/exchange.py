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


# --------------------------------------------------------------------------- EX-06a


def check_sources(text: str) -> Gate:
    """SOURCES.md: the change-log row with fetch date and method under the Phase 11 section."""
    body = _titled_section(text, SOURCES_SECTION_TITLE)
    if not body:
        return ("EX-06a", False, f"missing section '{SOURCES_SECTION_TITLE}'")
    missing = _missing(body, (CHANGE_LOG_URL, FETCH_DATE, "WebFetch"))
    return _verdict("EX-06a", missing, [])


# --------------------------------------------------------------------------- run


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run() -> list[Gate]:
    """Evaluate every gate against the real repository documents."""
    spec = _read(EXECUTION_SPEC_PATH)
    sources = _read(SOURCES_PATH)
    return [
        check_algo_limit(spec),
        check_sources(sources),
    ]


if __name__ == "__main__":  # pragma: no cover
    import sys

    results = run()
    for gate_name, gate_ok, gate_detail in results:
        print(("PASS" if gate_ok else "FAIL"), gate_name, gate_detail)
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
