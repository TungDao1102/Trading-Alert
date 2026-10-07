"""Doc-parity tripwire for the D013 kill-gate reconciliation (Phase 10, plan 10-02).

D-03 declares D013 authoritative over the protocol's originally inverted OR
wording and demands the resolution be *recorded*, not silently picked. The
resolution lives in a new DECISIONS row (D030), a clarification amendment to
the frozen research protocol (v1.0.1, since superseded by the v1.1.0 semantic
amendment D043 and then by the v2.0.0 simulator-semantics amendment D052) and the
DOC_STATUS index.

These tests make that reconciliation regress-proof and re-implement the three
research-gate witnesses from ``.github/workflows/research-gate.yml`` so an
amendment can never silently break the freeze check. The witnesses are
version-bound: the header ``Protocol version`` must equal the DECISIONS
``protocol vX.Y.Z frozen`` row and the DOC_STATUS index line. The version is read from the
header, never typed here, so a later amendment cannot leave a stale literal behind (D-28).
"""

from __future__ import annotations

import re
import tomllib
from decimal import Decimal
from pathlib import Path

from src.domain.registry import load_parameter_set

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISIONS = REPO_ROOT / "docs" / "DECISIONS.md"
PROTOCOL = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"
DOC_STATUS = REPO_ROOT / "docs" / "DOC_STATUS.md"
GLOSSARY = REPO_ROOT / "docs" / "GLOSSARY.md"

FREEZE_COMMIT = "281ccd0894ea35717cc741788b6133cfb202af82"

FREEZE_VERSION_LINE = re.compile(
    r"^>\s*\*\*Protocol version:\*\*\s*(v[0-9]+\.[0-9]+\.[0-9]+)\s*$", re.MULTILINE
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> list[str]:
    return _read(path).splitlines()


def _header_version() -> str:
    """The protocol version exactly as the header states it (``vX.Y.Z``)."""
    match = FREEZE_VERSION_LINE.search(_read(PROTOCOL))
    assert match is not None, "protocol header carries no 'Protocol version: vX.Y.Z' line"
    return match.group(1)


# Witness regexes copied verbatim from .github/workflows/research-gate.yml
# (grep -E semantics; Python `re` accepts these patterns unchanged). The version-bound
# witnesses (the freeze row and the index line) are built from the header version.
W1_STATUS = re.compile(r"^>\s*\*\*Status:\*\*\s*FROZEN\b", re.MULTILINE)
W1_FROZEN_ON = re.compile(r"^>\s*\*\*Frozen on:\*\*\s*[0-9]{4}-[0-9]{2}-[0-9]{2}", re.MULTILINE)
W2_LISTED = re.compile(r"research/RESEARCH_PROTOCOL\.md")
W2_PENDING = re.compile(r"research/RESEARCH_PROTOCOL\.md.*(pending-freeze|DRAFT|Living research)")


def _w3_freeze_row() -> re.Pattern[str]:
    return re.compile(rf"protocol {re.escape(_header_version())} frozen")


def _w2_index_line() -> re.Pattern[str]:
    return re.compile(rf"^- `research/RESEARCH_PROTOCOL\.md`.*{re.escape(_header_version())}")


# Header lines that must stay verbatim. Frozen-on is the kill-gate clock start (D030) and
# never moves; Amended-on records the latest amendment without matching the clock pattern.
PINNED_PROTOCOL_LINES = (
    "> **Status:** FROZEN",
    "> **Frozen on:** 2026-09-19",
)
EXPECTED_SUPERSEDES = "v1.1.0"
D043_ROW_PREFIX = "| D043 | Research protocol v1.1.0 frozen | Accepted"
D029_ROW_PREFIX = "| D029 | Research protocol v1.0.0 frozen | Accepted |"


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
    """The amendment keeps Status/Frozen-on, adds Amended-on/Supersedes and keeps D029."""
    protocol = _read(PROTOCOL)
    protocol_lines = protocol.splitlines()
    for pinned in PINNED_PROTOCOL_LINES:
        assert pinned in protocol_lines, f"pinned protocol line missing: {pinned!r}"
    assert f"> **Protocol version:** {_header_version()}" in protocol_lines
    assert f"> **Supersedes:** {EXPECTED_SUPERSEDES}" in protocol_lines
    amended = [ln for ln in protocol_lines if ln.startswith("> **Amended on:** ")]
    assert len(amended) == 1
    assert re.fullmatch(r"> \*\*Amended on:\*\* \d{4}-\d{2}-\d{2}", amended[0])
    # Witness 1: header FROZEN + Frozen-on date (date itself unchanged, pinned above).
    assert W1_STATUS.search(protocol)
    assert W1_FROZEN_ON.search(protocol)
    # Witness 3 + D029 row verbatim prefix.
    decisions = _read(DECISIONS)
    assert _w3_freeze_row().search(decisions)
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


def test_d043_row_present() -> None:
    """D043 is recorded once, appended after D042, citing D032/D030 and the clock rule."""
    lines = _lines(DECISIONS)
    d043_idx = [i for i, ln in enumerate(lines) if ln.startswith(D043_ROW_PREFIX)]
    d042_idx = [i for i, ln in enumerate(lines) if ln.startswith("| D042 |")]
    assert len(d043_idx) == 1, "D043 must appear exactly once as a table-row start"
    assert len(d042_idx) == 1
    assert d043_idx[0] > d042_idx[0], "D043 must be appended after D042"
    row = lines[d043_idx[0]]
    for token in (
        "D032",
        "D030",
        "Frozen on",
        "Amended on",
        "Holm",
        "holdout_consumed.json",
        "protocol v1.1.0 frozen",
    ):
        assert token in row, f"D043 row must mention {token}"
    assert re.search(r"protocol v1\.1\.0 frozen", row)


def test_d052_row_present() -> None:
    """D052 is recorded once, directly after D051, and voids the earlier backtest evidence."""
    lines = _lines(DECISIONS)
    d052_idx = [i for i, ln in enumerate(lines) if ln.startswith("| D052 |")]
    d051_idx = [i for i, ln in enumerate(lines) if ln.startswith("| D051 |")]
    assert len(d052_idx) == 1, "D052 must appear exactly once as a table-row start"
    assert len(d051_idx) == 1
    assert d052_idx[0] == d051_idx[0] + 1, "D052 must directly follow D051"
    row = lines[d052_idx[0]]
    assert "protocol v2.0.0 frozen" in row
    assert "bar N+1" in row
    assert "void" in row


def test_header_version_is_the_d052_amendment() -> None:
    """The header version equals the freeze row of the latest amendment (D052 is v2.0.0)."""
    assert _header_version() == "v2.0.0"


def test_doc_status_line_not_pending() -> None:
    """DOC_STATUS names the protocol at the header version with D030, D043, D052, no pending."""
    lines = [ln for ln in _lines(DOC_STATUS) if W2_LISTED.search(ln)]
    assert lines, "DOC_STATUS must list research/RESEARCH_PROTOCOL.md"
    index_lines = [ln for ln in lines if ln.startswith("- `research/RESEARCH_PROTOCOL.md`")]
    assert len(index_lines) == 1
    assert _w2_index_line().search(index_lines[0])
    assert _header_version() in index_lines[0]
    assert "D030" in index_lines[0]
    assert "D043" in index_lines[0]
    assert "D052" in index_lines[0]
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


def test_d053_inventory_row_present() -> None:
    """D053 lists what moved in Phase 14, once, directly after D052 (D048 style)."""
    lines = _lines(DECISIONS)
    d053_idx = [i for i, ln in enumerate(lines) if ln.startswith("| D053 |")]
    d052_idx = [i for i, ln in enumerate(lines) if ln.startswith("| D052 |")]
    assert len(d053_idx) == 1, "D053 must appear exactly once as a table-row start"
    assert len(d052_idx) == 1
    assert d053_idx[0] == d052_idx[0] + 1, "D053 must directly follow D052"
    row = lines[d053_idx[0]]
    for token in (
        "regeneration inventory",
        "MOVED:",
        "NOT MOVED",
        "funding_convention",
        "6d6c4e237ed0b56996ed344f4449b09a59c253a8d148af60e3aba1c8436f1caa",
        "3063dc390cecf6d7a19c2bbb338629990db366fd881f5383151ccb0bcd07a0d4",
        "analytics-evidence/2",
        "backtest-case/2",
        "ebd9e1014da67eeba942199a67699b3ac79f5fb8c64ef86b7218f003733a19c7",
        "74bbcc50fb94ee1f24a41f72668f3a9c32df7889355c521b146e56b518f4a2ec",
        "REGRESSION_SNAPSHOTS.md",
    ):
        assert token in row, f"D053 row must mention {token}"


def test_d054_geometry_row_present() -> None:
    """D054 records Phase 15 once, directly after D053 (D048 style, T-15-26)."""
    lines = _lines(DECISIONS)
    d054_idx = [i for i, ln in enumerate(lines) if ln.startswith("| D054 |")]
    d053_idx = [i for i, ln in enumerate(lines) if ln.startswith("| D053 |")]
    assert len(d054_idx) == 1, "D054 must appear exactly once as a table-row start"
    assert len(d053_idx) == 1
    assert d054_idx[0] == d053_idx[0] + 1, "D054 must directly follow D053"
    row = lines[d054_idx[0]]
    for token in (
        "baseline-v6",
        "baseline-no-trade-v4",
        "baseline-simple-trend-v4",
        "geometry_version",
        "STOP_TOO_TIGHT",
        "INVALIDATED",
        "no amendment",
        "The observed guard-survival figures",
        "not optimized",
        "D-25",
        "B1",
        "Regeneration inventory",
        "NOT MOVED",
        "_plan_geometry_is_valid",
        "far half of the entry zone",
        "TEST_DATABASE_URL",
        "2c4f1528b00f1b1e48c76040bbd6cc218a25eec21c521d8b68da86ee4811360f",
        "289d47ac5a77fd67d0551e0cb004e29562755b9455e7f9161567e7957746174d",
        "c9023e476e762fc56c993f3e920133d84a8d5700ec20805e9e85135148324100",
        "98e541eec72b3771f73adaae6f039d2de2a2ef9bcb66baa4d3507d3fe32bac9c",
        "27f4c18b92b44c28387299edb69be32977e3ab48004c1b0301fbbcc2e0d08c5f",
    ):
        assert token in row, f"D054 row must mention {token}"
    assert "ratified only through the 15-08 checkpoint" in row


def test_d054_v4_overrides_are_comparison_reference_points() -> None:
    """D054 labels the three -v4 override values as comparison reference points (G-15-10).

    The user answered on 2026-10-07 (15-UAT.md test 10) that the values are comparison
    reference points, to be written down clearly. The sentence must stay tied to the two
    hash-locked set files it describes: values, basis DECISION, ref D054, pinned hashes.
    """
    row = next(ln for ln in _lines(DECISIONS) if ln.startswith("| D054 |"))
    for token in (
        "comparison reference points",
        "comparison reference points for the RESEARCH_PROTOCOL Baselines comparison",
        "not evidence-backed parameters",
        "15-UAT.md test 10",
        "RESEARCH_PROTOCOL Baselines comparison",
        "hash-locked",
        "new parameter_set_hash",
        "baseline-no-trade-v4 minimum_rr 100",
        "baseline-simple-trend-v4 zone_tolerance_atr 1.0 and minimum_rr 0.5",
    ):
        assert token in row, f"D054 row must mention {token!r}"
    assert row.count("|") == 5, "D054 must stay one row with no pipe inside a cell"

    no_trade = load_parameter_set("trend-pullback", "baseline-no-trade-v4")
    simple = load_parameter_set("trend-pullback", "baseline-simple-trend-v4")
    assert Decimal(str(no_trade.params["minimum_rr"])) == Decimal("100")
    assert Decimal(str(simple.params["zone_tolerance_atr"])) == Decimal("1.0")
    assert Decimal(str(simple.params["minimum_rr"])) == Decimal("0.5")
    assert no_trade.parameter_set_hash == (
        "98e541eec72b3771f73adaae6f039d2de2a2ef9bcb66baa4d3507d3fe32bac9c"
    )
    assert simple.parameter_set_hash == (
        "27f4c18b92b44c28387299edb69be32977e3ab48004c1b0301fbbcc2e0d08c5f"
    )
    assert no_trade.parameter_set_hash in row
    assert simple.parameter_set_hash in row

    params_dir = REPO_ROOT / "params" / "trend-pullback"
    no_trade_doc = tomllib.loads(
        (params_dir / "baseline-no-trade-v4.toml").read_bytes().decode("utf-8")
    )
    simple_doc = tomllib.loads(
        (params_dir / "baseline-simple-trend-v4.toml").read_bytes().decode("utf-8")
    )
    for table in (
        no_trade_doc["rationale"]["minimum_rr"],
        simple_doc["rationale"]["zone_tolerance_atr"],
        simple_doc["rationale"]["minimum_rr"],
    ):
        assert table["basis"] == "DECISION"
        assert "D054" in table["text"]
