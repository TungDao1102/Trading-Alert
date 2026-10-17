"""Pins for research protocol v2.6.0 (D075, D076): a plan whose TP2 is not a positive price.

Plan 16-63. The amendment makes the planner return NO_TRADE RR_TOO_LOW for a plan whose TP2 is not
above zero after storage quantization and moves `SIMULATOR_SEMANTICS_VERSION` from 2.2.0 to 2.3.0.
These tests pin the owner's adopted text byte for byte (read from the decision record
`16-DEC-V260`), the header, the two DECISIONS rows (D075 the amendment, D076 the regeneration
inventory and the disposition of the original 240 records, with the owner's supersession wording
and exactly two version numbers replaced, derived from the reviewer-text file), the DOC_STATUS
lines and the one-field Holdout marker edit.

They read the protocol text, never a typed header version except the v2.6.0 witnesses themselves.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"
DECISIONS = REPO_ROOT / "docs" / "DECISIONS.md"
DOC_STATUS = REPO_ROOT / "docs" / "DOC_STATUS.md"
MARKER = REPO_ROOT / "docs" / "research" / "holdout_consumed.json"
PHASE = REPO_ROOT / ".planning" / "phases" / "16-paper-runtime-composition"
V260_RECORD = PHASE / "decisions" / "16-DEC-V260.md"
REVIEWER_TEXT = PHASE / "decisions" / "16-DEC-FIXPLANS-reviewer-text.md"
INVENTORY = PHASE / "evidence" / "16-63-regen-inventory.md"

LANDING_DATE = "2026-10-17"
V250_LANDING_COMMIT = "c96fa0d9ef00fdad981174de9b9670544eaf7a79"
# sha256 of the five gate lines "1. **G1 ..." to "5. **G5 ..." joined by newlines, taken from the
# v2.5.0 text (HEAD before the landing): the thresholds are byte-identical in v2.6.0.
GATE_LINES_SHA256 = "96d1d5f9fd3c6a973686d4bbcfe6eefcbd7cb3743e1c68823815b615dc14c601"
# sha256 of the rows D071 to D074 of docs/DECISIONS.md before the landing: never edited.
ROW_SHA256 = {
    "D071": "658bcf015abcfd191ba2f13c46658d1ccf00371b3a0d4a03b2e1486bd7e51e88",
    "D072": "71bac69e615417f375fdfc44fae0a3263f8c7aa8b71d21cac755a5baa1bbb0b7",
    "D073": "ffa3009f65cf411d818b7213fde16413a8152dbf4accfd87749793874a5caee9",
    "D074": "71c2e552cd8d138f792c306951b0da711b70186341ee7186fff6cdd2b6b3ecbc",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _protocol() -> str:
    return _read(PROTOCOL)


def _row(decisions: str, decision_id: str) -> str:
    rows = [ln for ln in decisions.splitlines() if ln.startswith(f"| {decision_id} |")]
    assert len(rows) == 1, f"{decision_id} must appear exactly once as a row"
    return rows[0]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _adopted_text() -> str:
    """The owner's adopted v2.6.0 block of 16-DEC-V260 item R2 (label D075 already in it)."""
    lines = _read(V260_RECORD).splitlines()
    quoted = [ln for ln in lines if ln.startswith("> **v2.6.0 (semantic, D075).**")]
    assert len(quoted) == 1
    return quoted[0][2:]


def _supersession_paragraph() -> str:
    lines = _read(REVIEWER_TEXT).splitlines()
    prefix = '"The original 240 records are retained unchanged'
    quoted = [ln for ln in lines if ln.startswith(prefix)]
    assert len(quoted) == 1
    return quoted[0].strip('"')


def _derived_paragraph() -> tuple[str, str]:
    """(source paragraph, paragraph with exactly the two version numbers replaced)."""
    source = _supersession_paragraph()
    old_sim, old_protocol = "simulator_semantics_version 2.2.0", "protocol v2.5.0"
    assert source.count(old_sim) == 1 and source.count(old_protocol) == 1
    derived = source.replace(old_sim, "simulator_semantics_version 2.3.0").replace(
        old_protocol, "protocol v2.6.0"
    )
    return source, derived


# --------------------------------------------------------------------------- #
# Test 1: header, adopted text, gates, rows, DOC_STATUS, marker.
# --------------------------------------------------------------------------- #


def test_the_header_reads_v260_frozen_amended_on_the_landing_date() -> None:
    lines = _protocol().splitlines()
    assert "> **Protocol version:** v2.6.0" in lines
    assert "> **Status:** FROZEN" in lines
    assert "> **Frozen on:** 2026-09-19" in lines  # unchanged: the D013 clock is not restarted
    assert f"> **Amended on:** {LANDING_DATE}" in lines
    assert "> **Supersedes:** v2.5.0" in lines


def test_the_adopted_v260_text_is_present_byte_for_byte() -> None:
    block = _adopted_text()
    assert block.startswith("**v2.6.0 (semantic, D075).** ")
    lines = _protocol().splitlines()
    assert lines.count(block) == 1
    assert "NO_TRADE" in block and "RR_TOO_LOW" in block and "2.3.0" in block
    assert "không bao giờ được gộp vào cùng một phép tính" in block


def test_the_gate_sentences_g1_to_g5_are_byte_identical_to_v250() -> None:
    gates = [ln for ln in _protocol().splitlines() if re.match(r"^[1-5]\. \*\*G[1-5] ", ln)]
    assert len(gates) == 5
    assert _sha("\n".join(gates)) == GATE_LINES_SHA256


def test_d075_is_the_only_row_that_freezes_v260_and_d076_follows_it() -> None:
    decisions = _read(DECISIONS)
    lines = decisions.splitlines()
    ids = [int(m.group(1)) for ln in lines if (m := re.match(r"^\| D(\d{3}) \|", ln))]
    assert ids == list(range(1, ids[-1] + 1)), "DC-02: ids are contiguous"
    index = {
        f"D{n:03d}": next(i for i, ln in enumerate(lines) if ln.startswith(f"| D{n:03d} |"))
        for n in (73, 74, 75, 76)
    }
    assert index["D074"] == index["D073"] + 1
    assert index["D075"] == index["D074"] + 1, "D075 directly follows D074"
    assert index["D076"] == index["D075"] + 1, "D076 directly follows D075"
    assert "protocol v2.6.0 frozen" in lines[index["D075"]]
    assert sum("protocol v2.6.0 frozen" in ln for ln in lines) == 1
    assert "protocol v2.6.0 frozen" not in lines[index["D076"]]
    # D071 to D074 are not edited
    for decision_id, digest in ROW_SHA256.items():
        assert _sha(_row(decisions, decision_id)) == digest, decision_id
    for decision_id in ("D075", "D076"):
        row = _row(decisions, decision_id)
        assert len(row.split(" | ")) == 4, "four cells, no pipe inside a cell"
        assert "<" not in row.split(" | ")[1], "no placeholder in the title"


def test_d075_names_the_decision_record_the_diagnosis_and_what_is_unchanged() -> None:
    row = _row(_read(DECISIONS), "D075")
    for needle in (
        "16-DEC-V260",
        "RR_TOO_LOW",
        "2.2.0 to 2.3.0",
        "research-run-1-a01",
        "1000PEPEUSDT",
        "-0.0015481",
        "strategy_version stays v5.0.0",
        V250_LANDING_COMMIT,
        "G1 to G5",
        "Nothing is applied backwards",
        "counted under RR_TOO_LOW together with a plan refused for a real RR below the floor",
        "protocol v2.6.0 frozen",
    ):
        assert needle in row, needle


def test_d076_holds_the_owners_wording_with_exactly_two_replacements_and_the_inventory() -> None:
    row = _row(_read(DECISIONS), "D076")
    source, derived = _derived_paragraph()
    assert derived in row
    assert source not in row, "the unreplaced D074 paragraph must be absent"
    assert row.count(derived) == 1
    assert (
        "No experiment record was ever written under simulator_semantics_version 2.2.0 "
        "or protocol v2.5.0"
    ) in row
    assert (
        "(the owner's wording of D074 with only the versions 2.2.0 and v2.5.0 replaced by "
        "2.3.0 and v2.6.0, 16-DEC-V260.md)"
    ) in row
    assert "docs/research/experiments/research-run-1-v2-3-0/" in row
    assert 'simulator_semantics_version: "2.3.0"' in row
    for needle in ("VERSION_PIN", "DERIVED_DIGEST", "STORED_RECORD", "Reversibility"):
        assert needle in row, needle
    assert "only version string and trade_id differ" in row
    # the evidence file the row compiles is the committed one (LF-normalized sha256)
    digest = _sha(_read(INVENTORY).replace("\r\n", "\n"))
    assert digest in row


def test_doc_status_index_line_and_log_line_name_v260_d075_and_d076() -> None:
    lines = _read(DOC_STATUS).splitlines()
    index = [ln for ln in lines if ln.startswith("- `research/RESEARCH_PROTOCOL.md`")]
    assert len(index) == 1
    assert "v2.6.0" in index[0] and "D075" in index[0]
    assert f"amended {LANDING_DATE}" in index[0]
    log = [ln for ln in lines if ln.startswith(f"- {LANDING_DATE} ") and "v2.6.0 semantic" in ln]
    assert len(log) == 1
    assert "D075" in log[0] and "D076" in log[0]
    assert "RESEARCH_PROTOCOL.md" in log[0]


def test_the_holdout_marker_changed_only_its_protocol_version_and_stays_empty() -> None:
    marker = json.loads(_read(MARKER))
    assert marker == {"schema": "holdout-consumed/2", "protocol_version": "v2.6.0", "entries": []}


# --------------------------------------------------------------------------- #
# Test 2: the migration paragraph, section 3, precedents and the amendment log.
# --------------------------------------------------------------------------- #


def _migration() -> str:
    text = _protocol()
    start = text.index("### Migration (v2.5.0 to v2.6.0)")
    end = text.index("**Numeric-gate status (v1.1.0).**", start)
    return text[start:end]


def test_migration_paragraph_states_supersession_nothing_of_220_and_what_does_not_change() -> None:
    paragraph = _migration()
    assert "semantic amendment" in paragraph and "D032, D043 and D075" in paragraph
    assert V250_LANDING_COMMIT in paragraph  # the v2.5.0 text in git history
    assert "RR_TOO_LOW" in paragraph and "TP2" in paragraph
    assert "`simulator_semantics_version` 2.3.0" in paragraph
    # research evidence under 2.1.0 is superseded by the rerun under 2.3.0 and never pooled
    assert "2.1.0" in paragraph and "superseded" in paragraph
    assert "never pooled" in paragraph
    # nothing was ever produced under 2.2.0
    assert "nothing was ever produced under simulator semantics 2.2.0" in paragraph
    # nothing registered moves
    assert "G1 to G5 and every threshold" in paragraph
    assert "`strategy_version` v5.0.0 and the 48 parameter-set hashes are untouched" in paragraph
    assert "Nothing is applied backwards" in paragraph


def test_section_3_holds_the_take_profit_plan_validity_subsection() -> None:
    text = _protocol()
    assert text.count("### Take-profit plan validity (v2.6.0)") == 1
    start = text.index("### Take-profit plan validity (v2.6.0)")
    end = text.index("### Timeframe hierarchy", start)
    section = text[start:end]
    assert _adopted_text() in section.splitlines()
    assert "covered by `simulator_semantics_version`" in section


def test_amendment_log_and_precedent_lists_name_v260() -> None:
    text = _protocol()
    log = [ln for ln in text.splitlines() if ln.startswith("- **v2.6.0 - ")]
    assert len(log) == 1
    assert f"- **v2.6.0 - {LANDING_DATE} - D075 (semantic).**" in log[0]
    assert "`Supersedes: v2.5.0`" in log[0]
    assert text.count("`v2.6.0` minor") == 2  # section 0 and Appendix A precedents


# --------------------------------------------------------------------------- #
# Test 4: the sheet, spec and audit lines.
# --------------------------------------------------------------------------- #


def test_the_sheets_the_spec_and_the_audit_carry_the_positivity_rule() -> None:
    families = REPO_ROOT / "docs" / "research" / "families"
    trend = _read(families / "trend-pullback.md")
    assert "TP2 must be a positive price" in trend
    assert "NO_TRADE RR_TOO_LOW (protocol v2.6.0, D075)" in trend
    for sheet in ("breakout-retest.md", "range-mr.md"):
        text = _read(families / sheet)
        assert "same TP2 positivity rule" in text and "protocol v2.6.0, D075" in text
    spec = _read(REPO_ROOT / "docs" / "backtest" / "BACKTEST_SPEC.md")
    assert "TP2 is not above zero after storage quantization is never created" in spec
    assert spec.count("RESEARCH_PROTOCOL.md` v2.6.0") == 2
    audit = _read(REPO_ROOT / "docs" / "research" / "GEOMETRY_AUDIT.md")
    assert audit.count("**Addendum (protocol v2.6.0, D075).**") == 1
    addendum_at = audit.index("**Addendum (protocol v2.6.0, D075).**")
    assert addendum_at > audit.index("| C | target |"), "the addendum sits below the table"
