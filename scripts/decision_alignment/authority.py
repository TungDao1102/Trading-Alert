"""Authority documents gate module (Phase 11, plan 11-06; D031, D-12, D-13, F-052).

Executable checks that keep the TradingView webhook authentication wording truthful
(TradingView cannot sign requests, so no document may promise an HMAC check) and that
keep the generated ``AGENTS.md`` blocks equal to their sources (``STACK.md`` and
``PROJECT.md``), including the one canonical quantization order.

``run()`` returns ``(name, ok, detail)`` tuples AU-01..AU-06; every check is also a pure
function over text so tests can inject good and bad input.

Required phrases are matched after ``normalise`` (emphasis markers and backticks removed,
whitespace collapsed).

Stdlib only.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
AGENTS_PATH = REPO_ROOT / "AGENTS.md"
STACK_PATH = REPO_ROOT / ".planning" / "research" / "STACK.md"
PROJECT_PATH = REPO_ROOT / ".planning" / "PROJECT.md"
TRADINGVIEW_PATH = DOCS_DIR / "integration" / "TRADINGVIEW.md"
RISK_PATH = DOCS_DIR / "trading" / "RISK_MANAGEMENT.md"
PROTOCOL_PATH = DOCS_DIR / "research" / "RESEARCH_PROTOCOL.md"

Gate = tuple[str, bool, str]

HMAC_CLAIM = "HMAC-checked"

TRADINGVIEW_PHRASES = (
    "cannot sign",
    "secret path segment",
    "source-IP allow-list",
    "3 seconds",
    "INTG-02",
    "2FA",
    "F-052",
    "verify against current TradingView docs",
)

FASTAPI_ROW_PREFIX = "| FastAPI |"
QUANTIZATION_BULLET_PREFIX = "- **Quantization**"

# The four tokens of the canonical quantization order (D031), as regexes. The protocol
# spells the second and third as "minimum quantity" / "minimum notional".
QUANTIZATION_TOKENS: tuple[tuple[str, str], ...] = (
    ("stepSize", r"stepSize"),
    ("min quantity", r"min(?:imum)? quantity"),
    ("min notional", r"min(?:imum)? notional"),
    (
        "minimum_risk_utilization_after_rounding",
        r"minimum_risk_utilization_after_rounding",
    ),
)

# The pre-decision ordering that put the utilization check before the min-qty/notional
# reject (11-RESEARCH F4).
# Matches the exact historical phrase and any sentence where a realized-risk check is
# followed, inside one clause, by an arrow and a min-qty/min-quantity/min-notional step.
OLD_ORDER_PHRASE = (
    r"realized[- ]risk[^.|;]{0,40}?(?:→|->)[^.|;]{0,30}?"
    r"min(?:imum)?[- ]?(?:qty|quantity|notional)"
)


def normalise(text: str) -> str:
    """Strip ``**`` and backticks, then collapse all whitespace to single spaces."""
    return " ".join(text.replace("**", "").replace("`", "").split())


def _section(text: str, number: int) -> str:
    """Body of the ``## <number>.`` section, up to the next ``## <n>.`` heading."""
    text = text.replace("\r\n", "\n")
    match = re.search(rf"^## {number}\.[^\n]*\n", text, flags=re.MULTILINE)
    if match is None:
        return ""
    rest = text[match.end() :]
    nxt = re.search(r"^## \d+\.", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _verdict(name: str, problems: list[str]) -> Gate:
    if problems:
        return (name, False, " | ".join(problems))
    return (name, True, "ok")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- AU-01


def check_no_hmac_claim(files: dict[str, str]) -> Gate:
    """AU-01: no scanned file promises that TradingView webhooks are HMAC-checked."""
    hits = [label for label, text in sorted(files.items()) if HMAC_CLAIM in normalise(text)]
    if hits:
        return ("AU-01", False, "HMAC-checked claim in: " + ", ".join(hits))
    return ("AU-01", True, "ok")


# --------------------------------------------------------------------------- AU-02


def check_tradingview_scheme(text: str) -> Gate:
    """AU-02: TRADINGVIEW section 5 states the real (unsigned) authentication scheme."""
    haystack = normalise(_section(text, 5))
    missing = [p for p in TRADINGVIEW_PHRASES if p not in haystack]
    problems = ["missing: " + "; ".join(missing)] if missing else []
    return _verdict("AU-02", problems)


# ------------------------------------------------------------- AU-03 / AU-05 (drift)


def _prefixed_lines(text: str, prefix: str) -> list[str]:
    return [
        line.rstrip("\r")
        for line in text.replace("\r\n", "\n").split("\n")
        if line.startswith(prefix)
    ]


def check_generated_row(
    source_text: str, generated_text: str, prefix: str, name: str = "AU-03"
) -> Gate:
    """A generated block line equals its source line (byte for byte, line endings aside).

    Every line beginning with ``prefix`` is compared; both sides must contain at least one.
    """
    source = _prefixed_lines(source_text, prefix)
    generated = _prefixed_lines(generated_text, prefix)
    if not source:
        return (name, False, f"no source line starts with {prefix!r}")
    if not generated:
        return (name, False, f"no generated line starts with {prefix!r}")
    if source != generated:
        return (name, False, f"generated line differs from source for prefix {prefix!r}")
    return (name, True, "ok")


# --------------------------------------------------------------------------- AU-04


def check_quantization_order(text: str, label: str) -> Gate:
    """AU-04: stepSize, min quantity, min notional, utilization appear in this order."""
    haystack = normalise(text)
    position = 0
    for token_name, pattern in QUANTIZATION_TOKENS:
        match = re.compile(pattern).search(haystack, position)
        if match is None:
            return (
                "AU-04",
                False,
                f"{label}: {token_name!r} missing or out of order",
            )
        position = match.end()
    return ("AU-04", True, "ok")


def canonical_order_line(risk_text: str) -> str:
    """The labelled ``Canonical order (D031):`` line of RISK_MANAGEMENT section 11."""
    for line in risk_text.replace("\r\n", "\n").split("\n"):
        if normalise(line).startswith("Canonical order (D031):"):
            return line
    return ""


def protocol_quantization_block(protocol_text: str) -> str:
    """The ``### Quantization`` block of RESEARCH_PROTOCOL section 2."""
    text = protocol_text.replace("\r\n", "\n")
    match = re.search(r"^### Quantization[^\n]*\n", text, flags=re.MULTILINE)
    if match is None:
        return ""
    rest = text[match.end() :]
    nxt = re.search(r"^(?:---|##+ )", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def quantization_bullet(text: str) -> str:
    """The ``- **Quantization**`` bullet of PROJECT.md or AGENTS.md."""
    lines = _prefixed_lines(text, QUANTIZATION_BULLET_PREFIX)
    return lines[0] if lines else ""


def check_quantization_agreement(
    risk_text: str, protocol_text: str, project_text: str, agents_text: str
) -> Gate:
    """AU-04 over the four locations: RISK_MANAGEMENT, protocol, PROJECT and AGENTS."""
    regions = (
        ("RISK_MANAGEMENT section 11", canonical_order_line(risk_text)),
        ("RESEARCH_PROTOCOL section 2", protocol_quantization_block(protocol_text)),
        ("PROJECT.md", quantization_bullet(project_text)),
        ("AGENTS.md", quantization_bullet(agents_text)),
    )
    problems: list[str] = []
    for label, region in regions:
        ok, detail = check_quantization_order(region, label)[1:]
        if not ok:
            problems.append(detail)
    return _verdict("AU-04", problems)


# --------------------------------------------------------------------------- AU-06


def check_no_old_order(files: dict[str, str]) -> Gate:
    """AU-06: the pre-decision quantization ordering is gone from the instruction files."""
    pattern = re.compile(OLD_ORDER_PHRASE)
    hits = [label for label, text in sorted(files.items()) if pattern.search(normalise(text))]
    if hits:
        return ("AU-06", False, "old quantization order in: " + ", ".join(hits))
    return ("AU-06", True, "ok")


# ------------------------------------------------------------------------------ run


def _scanned_docs() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)).replace("\\", "/"): _read(path)
        for path in sorted(DOCS_DIR.rglob("*.md"))
    }


def run() -> list[Gate]:
    """Evaluate every gate against the real repository documents."""
    stack = _read(STACK_PATH)
    agents = _read(AGENTS_PATH)
    project = _read(PROJECT_PATH)
    scanned = _scanned_docs()
    scanned["AGENTS.md"] = agents
    scanned[".planning/research/STACK.md"] = stack
    scanned[".planning/PROJECT.md"] = project
    return [
        check_no_hmac_claim(scanned),
        check_tradingview_scheme(_read(TRADINGVIEW_PATH)),
        check_generated_row(stack, agents, FASTAPI_ROW_PREFIX, "AU-03"),
        check_quantization_agreement(_read(RISK_PATH), _read(PROTOCOL_PATH), project, agents),
        check_generated_row(project, agents, QUANTIZATION_BULLET_PREFIX, "AU-05"),
        check_no_old_order(
            {
                "AGENTS.md": agents,
                ".planning/PROJECT.md": project,
                ".planning/research/STACK.md": stack,
            }
        ),
    ]


if __name__ == "__main__":  # pragma: no cover
    import sys

    results = run()
    for gate_name, gate_ok, gate_detail in results:
        print(("PASS" if gate_ok else "FAIL"), gate_name, gate_detail)
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
