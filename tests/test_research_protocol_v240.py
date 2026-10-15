"""Pins for research protocol v2.4.0 (D070): terminal settlement and the data each gate uses.

Quick 261014-nnl, plan 09. The amendment changes how the simulator treats a symbol's
declared terminal instant and states, for the first time, which data feeds G1 to G5. These
tests pin the sentences that carry the Validation-only invariant (design section 4), the
settlement counting rules and the extended end-state vocabulary. They read the protocol
text, never a typed header version, so a later amendment that keeps the sentences keeps the
tests green, and one that removes them fails loudly.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"

GATES_SENTENCE = (
    "G1, G2 and G3 (pooled Validation closed trades) and G4 use Validation only; "
    "G5 uses the Holdout only; no G1-G5 statistic is computed from Development trades "
    "or the Development equity path."
)


def _text() -> str:
    return PROTOCOL.read_text(encoding="utf-8")


def _section(heading: str, next_heading: str) -> str:
    text = _text()
    start = text.index(heading)
    return text[start : text.index(next_heading, start)]


def _section4() -> str:
    return _section("## §4 Acceptance methodology", "## §5 ")


def _gates_paragraph() -> str:
    paragraphs = [p for p in _section4().split("\n\n") if p.startswith("**Data used by the gates")]
    assert len(paragraphs) == 1
    return paragraphs[0]


def _version_tuple() -> tuple[int, int, int]:
    match = re.search(r"^> \*\*Protocol version:\*\* v(\d+)\.(\d+)\.(\d+)", _text(), re.M)
    assert match is not None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def test_the_header_is_at_least_v240_and_keeps_the_original_freeze_date() -> None:
    assert _version_tuple() >= (2, 4, 0)
    lines = _text().splitlines()
    assert "> **Status:** FROZEN" in lines
    assert "> **Frozen on:** 2026-09-19" in lines
    assert any(re.fullmatch(r"> \*\*Amended on:\*\* \d{4}-\d{2}-\d{2}", ln) for ln in lines)


def test_protocol_states_g1_to_g4_use_validation_only_and_g5_holdout_only() -> None:
    paragraph = _gates_paragraph()
    assert GATES_SENTENCE in paragraph
    assert paragraph.startswith("**Data used by the gates (v2.4.0).** G1, G2 and G3 ")
    # the sentence sits in section 4, after the gate list and before the holdout marker
    section4 = _section4()
    assert section4.index("A candidate passes only when G1-G5 all pass.") < section4.index(
        "**Data used by the gates"
    )
    assert section4.index("**Data used by the gates") < section4.index(
        "**Holdout consumed marker.**"
    )


def test_protocol_states_no_g_gate_input_uses_development() -> None:
    paragraph = _gates_paragraph()
    assert "no G1-G5 statistic is computed from Development trades" in paragraph
    assert "the Development equity path" in paragraph
    assert "it feeds none of the gates G1 to G5" in paragraph
    # the gate lines themselves name Validation or the Holdout, never Development
    for number in "12345":
        gate = [ln for ln in _section4().splitlines() if ln.startswith(f"{number}. **G{number} ")]
        assert len(gate) == 1
        assert "Development" not in gate[0]
    # the §1 selection role of Development is kept
    assert "keeps the role §1 gives it" in _gates_paragraph()


def test_protocol_does_not_claim_development_is_reporting_only() -> None:
    text = _text()
    assert not re.search(r"Development\s+feeds\s+reporting\s+only", text, re.I)
    assert not re.search(r"Development[^.\n]{0,40}\breporting only\b", text, re.I)


def test_settlement_is_counted_apart_from_closed_trades() -> None:
    section4 = _section4()
    bullets = [
        ln for ln in section4.splitlines() if ln.startswith("- Terminal settlement (v2.4.0):")
    ]
    assert len(bullets) == 1
    bullet = bullets[0]
    assert "`SETTLEMENT` exits and `SETTLEMENT_CANCEL` entries are counted apart" in bullet
    assert "a `SETTLEMENT` exit is never a closed trade" in bullet
    assert "excluded from pooled R, from the G1 and G5 counts and from every closed-trade" in bullet
    assert "a case without one does not carry the key" in bullet


def test_closed_trade_definition_is_sl_or_tp2_unchanged() -> None:
    bullet = next(
        ln for ln in _section4().splitlines() if ln.startswith("- Terminal settlement (v2.4.0):")
    )
    assert "The frozen definition of a closed trade (an exit by SL or TP2) is unchanged" in bullet
    # the data-end bullet of section 3 keeps the same exclusion rule next to the new one
    section3 = _section("## §3 Execution assumptions", "## §4 ")
    assert "excluded from pooled R and the closed-trade floor" in section3
    terminal = [
        ln for ln in section3.splitlines() if ln.startswith("- **terminal settlement (v2.4.0)**")
    ]
    assert len(terminal) == 1
    assert "excluded from pooled R and the closed-trade floor, like `END_OF_DATA`" in terminal[0]


def test_end_states_line_names_settlement_cancel_and_settlement() -> None:
    section6 = _text().split("## §6 ", 1)[1]
    lines = [ln for ln in section6.splitlines() if ln.startswith("- **simulated end states")]
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith("- **simulated end states (v2.0.0, extended in v2.4.0)**")
    assert "`PENDING_AT_DATA_END` or `SETTLEMENT_CANCEL`" in line
    assert "ends as SL, TP2, `END_OF_DATA` or `SETTLEMENT`" in line
    assert (
        "`END_OF_DATA`, `PENDING_AT_DATA_END`, `SETTLEMENT_CANCEL` and `SETTLEMENT` are reported "
        "separately and never booked as SL, TP or expiry"
    ) in line


def test_amendment_states_the_adverse_bound_is_not_a_global_worst_case() -> None:
    bullet = next(
        ln for ln in _section4().splitlines() if ln.startswith("- Settlement bound (v2.4.0):")
    )
    assert "The adverse bound is monotone for the net PnL of the settled trade" in bullet
    assert "but it is not a global worst case" in bullet
    assert "R below -1 is possible for the settled trade" in bullet
    assert (
        "no proxy for it (a flat price, the last mark close, an OHLC average, a midpoint)" in bullet
    )


def test_settlement_cannot_reach_validation_or_the_holdout_by_the_manifest_rule() -> None:
    text = _text()
    assert (
        "the manifest refuses a terminal settlement whose declared terminal is at or after the "
        "Validation start, so a settlement can reach neither Validation nor the Holdout"
    ) in text


def test_strategy_version_and_gate_thresholds_are_stated_unchanged() -> None:
    text = _text()
    assert "`strategy_version` stays `v5.0.0` for the 48 registered parameter sets" in text
    assert "(the G1 and G5 sentences word for word)" in text
    assert "no holdout entry, experiment record or kill-gate decision exists" in text
