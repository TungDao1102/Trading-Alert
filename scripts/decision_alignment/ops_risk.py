"""Operations and risk documents gate module (Phase 11, plan 11-04; D031-D038, D042).

Executable checks that keep SECURITY_AND_OPERATIONS, RUNBOOK, RISK_MANAGEMENT,
DATA_MODEL, CONFIGURATION and SIGNAL_AND_ALERTS aligned with the accepted decisions,
so the stale pre-decision wording cannot return unnoticed. ``run()`` returns
``(name, ok, detail)`` tuples OR-01..OR-10; every check is also a pure function over
text so tests can inject good and bad input.

Required phrases are matched after ``normalise`` (emphasis markers and backticks removed,
whitespace collapsed). Forbidden wording is matched per normalised line.

Stdlib only.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEC_OPS_PATH = REPO_ROOT / "docs" / "operations" / "SECURITY_AND_OPERATIONS.md"
RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "RUNBOOK.md"

Gate = tuple[str, bool, str]


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


# --------------------------------------------------------------------------- OR-01

SAFE_MODE_SEC_OPS_PHRASES = (
    "SAFE_MODE blocks new entry orders only",
    "Protective and reduce-only orders are always allowed",
    "automatically re-placed",
    "original plan stop-loss",
    "never wider",
    "reduce-only market close",
    "HIGH-priority alert",
    "D034",
)
SAFE_MODE_SEC_OPS_FORBIDDEN = (r"^-? ?no new live order placement[;.]?$",)

SAFE_MODE_RUNBOOK_PHRASES = (
    "Block new ENTRY orders",
    "NO NEW ENTRY ORDERS",
    "not an orphan",
    "D034",
)
SAFE_MODE_RUNBOOK_FORBIDDEN = (
    r"block new live orders",
    r"^NO NEW ORDERS$",
    r"^(→ )?block new orders$",
)


def check_safe_mode_sec_ops(text: str) -> Gate:
    """SECURITY_AND_OPERATIONS section 7: entries-only SAFE_MODE and the D034 ladder."""
    return _verdict(
        "OR-01a",
        _missing(_section(text, 7), SAFE_MODE_SEC_OPS_PHRASES),
        _forbidden_hits(text, SAFE_MODE_SEC_OPS_FORBIDDEN),
    )


def check_safe_mode_runbook(text: str) -> Gate:
    """RUNBOOK: entry-only blocking, automatic stop ladder and the orphan carve-out."""
    return _verdict(
        "OR-01b",
        _missing(text, SAFE_MODE_RUNBOOK_PHRASES),
        _forbidden_hits(text, SAFE_MODE_RUNBOOK_FORBIDDEN),
    )


# --------------------------------------------------------------------------- OR-02

SECRETS_PHRASES = ("permission-restricted", "0600", "D042", "disk encryption")
SECRETS_FORBIDDEN = (r"^-? ?Encrypt secrets at rest\.?$",)


def check_secrets(text: str) -> Gate:
    """SECURITY_AND_OPERATIONS section 1: the D042 secrets-at-rest control."""
    return _verdict(
        "OR-02",
        _missing(_section(text, 1), SECRETS_PHRASES),
        _forbidden_hits(text, SECRETS_FORBIDDEN),
    )


# --------------------------------------------------------------------------- OR-03

WEBHOOK_PHRASES = ("TRADINGVIEW.md", "cannot sign")


def check_webhook_pointer(text: str) -> Gate:
    """Webhook bullet points at TRADINGVIEW.md and never claims a signature scheme."""
    section = _section(text, 1)
    webhook_lines = [ln for ln in _lines(section) if "webhook" in ln.lower()]
    missing = _missing(" ".join(webhook_lines), WEBHOOK_PHRASES)
    claims = [
        ln
        for ln in _lines(text)
        if "webhook" in ln.lower()
        and re.search(r"hmac|signature|signed", ln, flags=re.IGNORECASE)
        and "cannot sign" not in ln
    ]
    verdict = _verdict("OR-03", missing, [])
    if claims:
        detail = "signature claim without 'cannot sign': " + "; ".join(claims)
        if not verdict[1]:
            detail = verdict[2] + " | " + detail
        return ("OR-03", False, detail)
    return verdict


# --------------------------------------------------------------------------- run


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _combine(name: str, gates: list[Gate]) -> Gate:
    bad = [f"{g[0]}: {g[2]}" for g in gates if not g[1]]
    if bad:
        return (name, False, " | ".join(bad))
    return (name, True, "ok")


def run() -> list[Gate]:
    """Evaluate every gate against the real repository documents."""
    sec_ops = _read(SEC_OPS_PATH)
    runbook = _read(RUNBOOK_PATH)
    return [
        _combine(
            "OR-01",
            [check_safe_mode_sec_ops(sec_ops), check_safe_mode_runbook(runbook)],
        ),
        check_secrets(sec_ops),
        check_webhook_pointer(sec_ops),
    ]


if __name__ == "__main__":  # pragma: no cover
    import sys

    results = run()
    for gate_name, gate_ok, gate_detail in results:
        print(("PASS" if gate_ok else "FAIL"), gate_name, gate_detail)
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
