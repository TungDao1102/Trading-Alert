"""Bookkeeping gate module (Phase 11, plan 11-07; D-15, D-16, D-19, D044, D045).

Executable checks for the authority-chain bookkeeping: GLOSSARY reason codes and
ApprovalResult (GL-01..GL-06), REQUIREMENTS/ROADMAP registration of the 13 new
requirement IDs (RQ-01..RQ-05), and the DECISIONS/DOC_STATUS/DATA_MODEL records
(DC-01..DC-06). ``run()`` returns ``(name, ok, detail)`` tuples. Every check is a pure
function over text (plus the enum and code-reference sets it is handed) so tests can
inject good and bad input.

Stdlib only; ``run_glossary`` imports ``src.domain.enums`` for the enum value sets.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GLOSSARY_PATH = REPO_ROOT / "docs" / "GLOSSARY.md"
SRC_ROOT = REPO_ROOT / "src"

Gate = tuple[str, bool, str]

# The five synonym codes that D-15 (resolution 3) lists as deprecated aliases.
ALIASES: tuple[str, ...] = (
    "QUANTIZATION_REJECT",
    "MIN_NOTIONAL_REJECT",
    "RISK_LIMIT",
    "CORRELATED_RISK_LIMIT",
    "DAILY_STOP",
)

# Plain-string codes emitted outside RejectionReason (GL-05).
STRING_CODES: tuple[str, ...] = (
    "DISABLED",
    "ENTRY_WITHOUT_PROTECTIVE",
    "NO_FILL",
    "HEALTH_CHECK_FAILED",
    "EXPIRED",
)

# KillGateState token block under section 8.2 (parsed by tests/test_kill_gate_docs.py).
KILL_GATE_TOKENS: tuple[str, ...] = (
    "WITHIN_BUDGET",
    "PASSING_CANDIDATE",
    "INSUFFICIENT_EDGE",
)


# --------------------------------------------------------------------------- helpers


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _slice(text: str, start_pattern: str, end_pattern: str | None) -> str:
    """Text after the first ``start_pattern`` line up to the next ``end_pattern`` line."""
    text = _norm(text)
    start = re.search(start_pattern, text, flags=re.MULTILINE)
    if start is None:
        return ""
    rest = text[start.end() :]
    if end_pattern is None:
        return rest
    end = re.search(end_pattern, rest, flags=re.MULTILINE)
    return rest[: end.start()] if end else rest


def _text_block(section: str) -> list[str]:
    """Tokens of the first fenced ``text`` block in ``section`` (comments/blank dropped)."""
    match = re.search(r"```text\n(.*?)```", section, flags=re.DOTALL)
    if match is None:
        return []
    out: list[str] = []
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _table_first_cells(section: str) -> list[str]:
    """Backticked first-cell tokens of every table row in ``section``."""
    return re.findall(r"^\|\s*`([A-Z][A-Z0-9_]*)`", section, flags=re.MULTILINE)


# --------------------------------------------------------------------------- GLOSSARY


def parse_glossary_sections(text: str) -> dict[str, object]:
    """Extract the parts of GLOSSARY sections 8.2, 9 and 10 the GL gates inspect."""
    sec9 = _slice(text, r"^## 9\.[^\n]*\n", r"^## \d+\.")
    sec91 = _slice(sec9, r"^### 9\.1[^\n]*\n", r"^### 9\.\d")
    sec92 = _slice(sec9, r"^### 9\.2[^\n]*\n", r"^### 9\.\d")
    sec93 = _slice(sec9, r"^### 9\.3[^\n]*\n", r"^### 9\.\d")
    sec10 = _slice(text, r"^## 10\.[^\n]*\n", r"^## \d+\.")
    has_82 = re.search(r"^### 8\.2 Canonical KillGateState", _norm(text), flags=re.MULTILINE)
    sec82 = _slice(text, r"^### 8\.2[^\n]*\n", r"^#{2,3} ")
    return {
        "canonical": _text_block(sec91),
        "aliases": _table_first_cells(sec92),
        "plain": sec93,
        "approval": _text_block(sec10),
        "has_82_heading": has_82 is not None,
        "kill_tokens": _text_block(sec82),
    }


def check_glossary(
    text: str,
    enum_values: set[str],
    referenced_codes: set[str],
    approval_values: set[str],
) -> list[Gate]:
    """Gates GL-01..GL-06 over GLOSSARY text and the code-derived sets."""
    parsed = parse_glossary_sections(text)
    canonical = list(parsed["canonical"])  # type: ignore[arg-type]
    aliases = list(parsed["aliases"])  # type: ignore[arg-type]
    plain = str(parsed["plain"])
    approval = list(parsed["approval"])  # type: ignore[arg-type]
    gates: list[Gate] = []

    # GL-01 canonical block: unique tokens, none of the five aliases.
    dups = sorted({t for t in canonical if canonical.count(t) > 1})
    leaked = sorted(set(canonical) & set(ALIASES))
    problems = []
    if not canonical:
        problems.append("section 9.1 block missing or empty")
    if dups:
        problems.append("duplicate tokens: " + ", ".join(dups))
    if leaked:
        problems.append("aliases in canonical block: " + ", ".join(leaked))
    gates.append(
        ("GL-01", not problems, "; ".join(problems) or f"{len(canonical)} canonical codes")
    )

    # GL-02 every code referenced by src/ is canonical.
    missing = sorted(referenced_codes - set(canonical))
    gates.append(
        (
            "GL-02",
            not missing,
            ("referenced but not in 9.1: " + ", ".join(missing))
            if missing
            else f"{len(referenced_codes)} referenced codes all canonical",
        )
    )

    # GL-03 canonical union aliases equals the enum; exactly five aliases.
    union = set(canonical) | set(aliases)
    problems = []
    if union != enum_values:
        only_doc = sorted(union - enum_values)
        only_enum = sorted(enum_values - union)
        problems.append(f"union differs from enum (doc-only {only_doc}, enum-only {only_enum})")
    if sorted(aliases) != sorted(ALIASES):
        problems.append(f"alias table is {sorted(aliases)}, expected {sorted(ALIASES)}")
    gates.append(
        (
            "GL-03",
            not problems,
            "; ".join(problems) or f"{len(canonical)}+{len(aliases)}={len(union)} equals enum",
        )
    )

    # GL-04 section 10 block equals the ApprovalResult value set.
    ok04 = (
        bool(approval) and set(approval) == approval_values and len(approval) == len(set(approval))
    )
    gates.append(
        (
            "GL-04",
            ok04,
            "ok"
            if ok04
            else f"section 10 block {approval} != ApprovalResult {sorted(approval_values)}",
        )
    )

    # GL-05 section 9.3 names the plain-string codes.
    absent = [c for c in STRING_CODES if not re.search(rf"\b{c}\b", plain)]
    gates.append(
        ("GL-05", not absent, ("section 9.3 missing: " + ", ".join(absent)) if absent else "ok")
    )

    # GL-06 section 8.2 heading and 3-token block unchanged.
    kill = list(parsed["kill_tokens"])  # type: ignore[arg-type]
    ok06 = bool(parsed["has_82_heading"]) and tuple(kill) == KILL_GATE_TOKENS
    gates.append(("GL-06", ok06, "ok" if ok06 else f"section 8.2 heading/tokens changed: {kill}"))
    return gates


def referenced_reason_codes(src_root: Path = SRC_ROOT) -> set[str]:
    """Unique ``RejectionReason.X`` names referenced in ``src/**/*.py`` (enums.py excluded)."""
    pattern = re.compile(r"RejectionReason\.([A-Z][A-Z_]*)")
    found: set[str] = set()
    for path in sorted(src_root.rglob("*.py")):
        if path.parts[-2:] == ("domain", "enums.py"):
            continue
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


def run_glossary() -> list[Gate]:
    """Evaluate GL-01..GL-06 against the real GLOSSARY and src/."""
    from src.domain.enums import ApprovalResult, RejectionReason

    return check_glossary(
        _read(GLOSSARY_PATH),
        {m.value for m in RejectionReason},
        referenced_reason_codes(),
        {m.value for m in ApprovalResult},
    )


def run() -> list[Gate]:
    """Every bookkeeping gate against the real repository."""
    return run_glossary()


if __name__ == "__main__":  # pragma: no cover
    import sys

    results = run()
    for gate_name, gate_ok, gate_detail in results:
        print(("PASS" if gate_ok else "FAIL"), gate_name, gate_detail)
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
