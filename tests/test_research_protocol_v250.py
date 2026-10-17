"""Pins for research protocol v2.5.0 (D073, D074): warm-up history for research windows.

Plan 16-60. The amendment changes how a research window is built (candle history loaded before
its start, indicators only) and moves `SIMULATOR_SEMANTICS_VERSION` from 2.1.0 to 2.2.0. These
tests pin the user's adopted text byte for byte (read from the decision record, with the one
label the user's decision renumbered), the header, the two DECISIONS rows (D073 the amendment,
D074 the regeneration inventory and the disposition of the original 240 records, with the owner's
supersession wording verbatim), the DOC_STATUS lines and the one-field Holdout marker edit.

They read the protocol text, never a typed header version except the v2.5.0 witnesses themselves.
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
V250_RECORD = PHASE / "decisions" / "16-DEC-V250.md"
REVIEWER_TEXT = PHASE / "decisions" / "16-DEC-FIXPLANS-reviewer-text.md"
INVENTORY = PHASE / "evidence" / "16-60-regen-inventory.md"

LANDING_DATE = "2026-10-17"
# sha256 of the five gate lines "1. **G1 ..." to "5. **G5 ..." joined by newlines, taken from the
# v2.4.0 text (HEAD before the landing): the thresholds are byte-identical in v2.5.0.
GATE_LINES_SHA256 = "96d1d5f9fd3c6a973686d4bbcfe6eefcbd7cb3743e1c68823815b615dc14c601"
# sha256 of the rows D071 and D072 (the Phase 18 row) of docs/DECISIONS.md before the landing.
D071_ROW_SHA256 = "658bcf015abcfd191ba2f13c46658d1ccf00371b3a0d4a03b2e1486bd7e51e88"
D072_ROW_SHA256 = "71bac69e615417f375fdfc44fae0a3263f8c7aa8b71d21cac755a5baa1bbb0b7"
V240_LANDING_COMMIT = "006c480d35581b045ee0d6a73b02af23028ff6da"


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
    """The user's adopted v2.5.0 block of 16-DEC-V250 item 2, with the row label D073."""
    lines = _read(V250_RECORD).splitlines()
    quoted = [ln for ln in lines if ln.startswith("> **v2.5.0 (semantic, D071).**")]
    assert len(quoted) == 1
    block = quoted[0][2:]
    assert block.count("(semantic, D071)") == 1
    return block.replace("(semantic, D071)", "(semantic, D073)")


def _supersession_paragraph() -> str:
    lines = _read(REVIEWER_TEXT).splitlines()
    prefix = '"The original 240 records are retained unchanged'
    quoted = [ln for ln in lines if ln.startswith(prefix)]
    assert len(quoted) == 1
    return quoted[0].strip('"')


# --------------------------------------------------------------------------- #
# Test 1: header, adopted text, gates, rows, DOC_STATUS, marker.
# --------------------------------------------------------------------------- #


def test_the_header_reads_v250_frozen_amended_on_the_landing_date() -> None:
    lines = _protocol().splitlines()
    assert "> **Protocol version:** v2.5.0" in lines
    assert "> **Status:** FROZEN" in lines
    assert "> **Frozen on:** 2026-09-19" in lines  # unchanged: the D013 clock is not restarted
    assert f"> **Amended on:** {LANDING_DATE}" in lines
    assert "> **Supersedes:** v2.4.0" in lines


def test_the_adopted_v250_text_is_present_byte_for_byte_except_the_row_label() -> None:
    block = _adopted_text()
    assert block.startswith("**v2.5.0 (semantic, D073).** ")
    lines = _protocol().splitlines()
    assert lines.count(block) == 1
    # the user's words that carry the decision are in the block
    assert "2024-10-03" in block and "Holdout" in block
    assert "không bao giờ được gộp vào cùng một phép tính" in block


def test_the_gate_sentences_g1_to_g5_are_byte_identical_to_v240() -> None:
    gates = [ln for ln in _protocol().splitlines() if re.match(r"^[1-5]\. \*\*G[1-5] ", ln)]
    assert len(gates) == 5
    assert _sha("\n".join(gates)) == GATE_LINES_SHA256


def test_d073_is_the_only_row_that_freezes_v250_and_d074_follows_the_phase_18_row() -> None:
    decisions = _read(DECISIONS)
    lines = decisions.splitlines()
    ids = [int(m.group(1)) for ln in lines if (m := re.match(r"^\| D(\d{3}) \|", ln))]
    assert ids == list(range(1, ids[-1] + 1)), "DC-02: ids are contiguous"
    index = {
        f"D{n:03d}": next(i for i, ln in enumerate(lines) if ln.startswith(f"| D{n:03d} |"))
        for n in (71, 72, 73, 74)
    }
    assert index["D072"] == index["D071"] + 1
    assert index["D073"] == index["D072"] + 1, "D073 directly follows the Phase 18 row D072"
    assert index["D074"] == index["D073"] + 1, "D074 directly follows D073"
    assert "protocol v2.5.0 frozen" in lines[index["D073"]]
    assert sum("protocol v2.5.0 frozen" in ln for ln in lines) == 1
    assert "protocol v2.5.0 frozen" not in lines[index["D074"]]
    # D071 and the Phase 18 row are not edited
    assert _sha(_row(decisions, "D071")) == D071_ROW_SHA256
    assert _sha(_row(decisions, "D072")) == D072_ROW_SHA256
    assert _row(decisions, "D072").startswith("| D072 | Phase 18 client configuration")
    for decision_id in ("D073", "D074"):
        row = _row(decisions, decision_id)
        assert len(row.split(" | ")) == 4, "four cells, no pipe inside a cell"
        assert "<" not in row.split(" | ")[1], "no placeholder in the title"


def test_d073_names_the_decision_records_the_constant_and_what_is_unchanged() -> None:
    row = _row(_read(DECISIONS), "D073")
    for needle in (
        "16-DEC-V250",
        "16-DEC-FIXPLANS",
        "16-DEC-V250-span",
        "B3-CR-01",
        "RESEARCH_WARMUP_SPAN",
        "50 days",
        "2.1.0 to 2.2.0",
        "starts cold",
        "2024-10-03",
        V240_LANDING_COMMIT,
        "G1 to G5",
        "Nothing is applied backwards",
        "reviewer text says D072",
    ):
        assert needle in row, needle


def test_d074_holds_the_owners_supersession_wording_verbatim_and_the_inventory() -> None:
    row = _row(_read(DECISIONS), "D074")
    assert _supersession_paragraph() in row
    assert "reviewer text says D073; recorded as D074" in row
    assert "VERSION_PIN" in row and "DERIVED_DIGEST" in row and "STORED_RECORD" in row
    assert "only version string and trade_id differ" in row
    assert "docs/research/experiments/research-run-1-v2-2-0/" in row
    assert 'simulator_semantics_version: "2.2.0"' in row
    # the evidence file the row compiles is the committed one (LF-normalized sha256)
    digest = _sha(_read(INVENTORY).replace("\r\n", "\n"))
    assert digest in row


def test_doc_status_index_line_and_log_line_name_v250_d073_and_d074() -> None:
    lines = _read(DOC_STATUS).splitlines()
    index = [ln for ln in lines if ln.startswith("- `research/RESEARCH_PROTOCOL.md`")]
    assert len(index) == 1
    assert "v2.5.0" in index[0] and "D073" in index[0]
    assert f"amended {LANDING_DATE}" in index[0]
    log = [ln for ln in lines if ln.startswith(f"- {LANDING_DATE} ") and "v2.5.0" in ln]
    assert len(log) == 1
    assert "D073" in log[0] and "D074" in log[0]
    assert "RESEARCH_PROTOCOL.md" in log[0]


def test_the_holdout_marker_changed_only_its_protocol_version_and_stays_empty() -> None:
    marker = json.loads(_read(MARKER))
    assert marker == {"schema": "holdout-consumed/2", "protocol_version": "v2.5.0", "entries": []}


# --------------------------------------------------------------------------- #
# Test 2: the migration paragraph and the amendment log.
# --------------------------------------------------------------------------- #


def _migration() -> str:
    text = _protocol()
    start = text.index("### Migration (v2.4.0 to v2.5.0)")
    end = text.index("**Numeric-gate status (v1.1.0).**", start)
    return text[start:end]


def test_migration_paragraph_states_supersession_cold_start_and_what_does_not_change() -> None:
    paragraph = _migration()
    assert "semantic amendment" in paragraph and "D073" in paragraph and "D074" in paragraph
    assert V240_LANDING_COMMIT in paragraph  # the v2.4.0 text in git history
    assert "`RESEARCH_WARMUP_SPAN`" in paragraph and "50 days" in paragraph
    assert "simulator_semantics_version` 2.2.0" in paragraph
    # research evidence under 2.1.0 (cold windows) is superseded and never pooled
    assert "2.1.0" in paragraph and "superseded" in paragraph
    assert "never pooled" in paragraph
    # the Development window starts cold because the data begins 2024-10-03
    assert "Development window starts cold" in paragraph
    assert "2024-10-03" in paragraph
    # nothing registered moves
    assert "G1 to G5 and every threshold" in paragraph
    assert "`strategy_version` v5.0.0" in paragraph
    assert "grid" in paragraph


def test_amendment_log_and_precedent_lists_name_v250() -> None:
    text = _protocol()
    log = [ln for ln in text.splitlines() if ln.startswith("- **v2.5.0 - ")]
    assert len(log) == 1
    assert f"- **v2.5.0 - {LANDING_DATE} - D073 (semantic).**" in log[0]
    assert "`Supersedes: v2.4.0`" in log[0]
    assert text.count("`v2.5.0` minor") == 2  # section 0 and Appendix A precedents
