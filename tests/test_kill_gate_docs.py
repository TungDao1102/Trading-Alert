"""Doc-parity tripwire for the D013 kill-gate reconciliation (Phase 10, plan 10-02).

D-03 declares D013 authoritative over the protocol's originally inverted OR
wording and demands the resolution be *recorded*, not silently picked. The
resolution lives in a new DECISIONS row (D030), a clarification amendment to
the frozen research protocol (v1.0.1) and the DOC_STATUS index.

These tests make that reconciliation regress-proof and re-implement the three
research-gate witnesses from ``.github/workflows/research-gate.yml`` so an
amendment can never silently break the freeze check.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISIONS = REPO_ROOT / "docs" / "DECISIONS.md"
PROTOCOL = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"
DOC_STATUS = REPO_ROOT / "docs" / "DOC_STATUS.md"
GLOSSARY = REPO_ROOT / "docs" / "GLOSSARY.md"

FREEZE_COMMIT = "281ccd0894ea35717cc741788b6133cfb202af82"

# Witness regexes copied verbatim from .github/workflows/research-gate.yml
# (grep -E semantics; Python `re` accepts these patterns unchanged).
W1_STATUS = re.compile(r"^>\s*\*\*Status:\*\*\s*FROZEN\b", re.MULTILINE)
W1_FROZEN_ON = re.compile(r"^>\s*\*\*Frozen on:\*\*\s*[0-9]{4}-[0-9]{2}-[0-9]{2}", re.MULTILINE)
W2_LISTED = re.compile(r"research/RESEARCH_PROTOCOL\.md")
W2_PENDING = re.compile(r"research/RESEARCH_PROTOCOL\.md.*(pending-freeze|DRAFT|Living research)")
W3_FREEZE_ROW = re.compile(
    r"protocol v1\.0\.0 frozen|RESEARCH_PROTOCOL.*frozen|frozen.*RESEARCH_PROTOCOL"
)

# Pre-amendment literal lines that must stay verbatim.
PINNED_PROTOCOL_LINES = (
    "> **Status:** FROZEN",
    "> **Frozen on:** 2026-09-19",
    "> **Supersedes:** none",
)
D029_ROW_PREFIX = "| D029 | Research protocol v1.0.0 frozen | Accepted |"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> list[str]:
    return _read(path).splitlines()


def _kill_gate_section(text: str) -> str:
    """Return the body of the ``### Kill gate D013`` section of the protocol."""
    start = text.index("### Kill gate D013")
    rest = text[start + len("### Kill gate D013") :]
    end = re.search(r"^(---|#{1,3} )", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).lower()


def test_d030_row_present() -> None:
    """D030 is recorded once, appended after D029, citing D013 + freeze commit."""
    lines = _lines(DECISIONS)
    d030_idx = [i for i, ln in enumerate(lines) if ln.startswith("| D030 |")]
    d029_idx = [i for i, ln in enumerate(lines) if ln.startswith("| D029 |")]
    assert len(d030_idx) == 1, "D030 must appear exactly once as a table-row start"
    assert len(d029_idx) == 1
    assert d030_idx[0] > d029_idx[0], "D030 must be appended after D029"
    row = lines[d030_idx[0]]
    for token in ("D013", "RESEARCH_PROTOCOL", "INSUFFICIENT_EDGE", FREEZE_COMMIT):
        assert token in row, f"D030 row must mention {token}"


def test_protocol_freeze_witnesses_intact() -> None:
    """The amendment leaves Status/Frozen-on/Supersedes/D029 and all witnesses intact."""
    protocol = _read(PROTOCOL)
    protocol_lines = protocol.splitlines()
    for pinned in PINNED_PROTOCOL_LINES:
        assert pinned in protocol_lines, f"pinned protocol line missing: {pinned!r}"
    assert "> **Protocol version:** v1.0.1" in protocol_lines
    # Witness 1: header FROZEN + Frozen-on date (date itself unchanged, pinned above).
    assert W1_STATUS.search(protocol)
    assert W1_FROZEN_ON.search(protocol)
    # Witness 3 + D029 row verbatim prefix.
    decisions = _read(DECISIONS)
    assert W3_FREEZE_ROW.search(decisions)
    assert any(ln.startswith(D029_ROW_PREFIX) for ln in decisions.splitlines())
    # Witness 2 is exercised in test_doc_status_line_not_pending.
    assert W2_LISTED.search(_read(DOC_STATUS))


def test_protocol_kill_gate_matches_d013() -> None:
    """The kill-gate section states the three conjunctive conditions and cites D030."""
    section = _kill_gate_section(_read(PROTOCOL))
    norm = _normalize(section)
    assert "at least three" in norm
    assert "independently specified" in norm
    assert "at least six calendar months" in norm
    assert "freeze" in norm
    assert "no family" in norm
    assert "recorded passing decision" in norm
    assert "and" in norm
    assert "D030" in section
    assert "fewer than three" not in norm, "inverted OR wording must be gone"
    # Closing sentence about NO_TRADE / forced green lights is preserved.
    assert "NO_TRADE" in section
    assert "forced green light" in norm


def test_doc_status_line_not_pending() -> None:
    """DOC_STATUS names the protocol at v1.0.1 with D030 and no pending markers."""
    lines = [ln for ln in _lines(DOC_STATUS) if W2_LISTED.search(ln)]
    assert lines, "DOC_STATUS must list research/RESEARCH_PROTOCOL.md"
    index_lines = [ln for ln in lines if ln.startswith("- `research/RESEARCH_PROTOCOL.md`")]
    assert len(index_lines) == 1
    assert "v1.0.1" in index_lines[0]
    assert "D030" in index_lines[0]
    for ln in lines:
        assert not W2_PENDING.search(ln), f"pending marker on DOC_STATUS line: {ln!r}"


def test_glossary_tokens_match_enum() -> None:
    """GLOSSARY section 8.2 lists exactly the KillGateState values (no synonyms)."""
    from src.domain.enums import KillGateState

    text = _read(GLOSSARY)
    heading = "### 8.2 Canonical KillGateState (Phase 10, D-03)"
    assert heading in text, "GLOSSARY section 8.2 missing"
    body = text[text.index(heading) + len(heading) :].split("\n## ", 1)[0]
    block = re.search(r"```text\n(.*?)```", body, re.DOTALL)
    assert block is not None, "GLOSSARY 8.2 must carry a fenced token block"
    tokens = [ln.strip() for ln in block.group(1).splitlines() if ln.strip()]
    assert len(tokens) == 3
    assert set(tokens) == {m.value for m in KillGateState}
    assert "D030" in body
