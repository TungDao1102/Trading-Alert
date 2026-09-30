"""Tests for the protocol v1.1.0 gate module (Phase 11, plan 11-01; D032, D043).

The real-repository test proves gates PR-01..PR-10 hold today; the negative tests feed
each pure check a deliberately broken input so a regression in the protocol text, the
holdout marker or the BACKTEST_SPEC pointers cannot pass silently.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from scripts.decision_alignment import protocol as gate

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"
DECISIONS = REPO_ROOT / "docs" / "DECISIONS.md"
DOC_STATUS = REPO_ROOT / "docs" / "DOC_STATUS.md"
HOLDOUT = REPO_ROOT / "docs" / "research" / "holdout_consumed.json"
BACKTEST_SPEC = REPO_ROOT / "docs" / "backtest" / "BACKTEST_SPEC.md"

VALID_ENTRY: dict[str, Any] = {
    "lineage_id": "trend-pullback@v1",
    "candidate_sha256": "a" * 64,
    "consumed_at_utc": "2026-10-01T00:00:00Z",
    "decision_ref": "D044",
}


def _protocol() -> str:
    return PROTOCOL.read_text(encoding="utf-8")


def _doc(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema": "holdout-consumed/1",
        "protocol_version": "v1.1.0",
        "entries": copy.deepcopy(entries if entries is not None else []),
    }


def test_all_gates_pass_on_the_real_repository() -> None:
    results = gate.run()
    assert [name for name, _, _ in results] == [f"PR-{i:02d}" for i in range(1, 11)]
    failed = [(name, detail) for name, ok, detail in results if not ok]
    assert failed == []


def test_witnesses_agree_on_real_files() -> None:
    protocol = _protocol()
    decisions = DECISIONS.read_text(encoding="utf-8")
    doc_status = DOC_STATUS.read_text(encoding="utf-8")
    assert gate.check_witnesses(protocol, decisions, doc_status) == []
    stale = doc_status.replace("v1.1.0", "v1.0.1")
    assert gate.check_witnesses(protocol, decisions, stale)
    no_row = "\n".join(ln for ln in decisions.splitlines() if "protocol v1.1.0 frozen" not in ln)
    assert gate.check_witnesses(protocol, no_row, doc_status)


def test_header_missing_amended_on_fails() -> None:
    text = "\n".join(
        ln for ln in _protocol().splitlines() if not ln.startswith("> **Amended on:**")
    )
    problems = gate.check_header(text)
    assert any("Amended on" in p for p in problems)


def test_header_moved_frozen_on_fails() -> None:
    text = _protocol().replace("> **Frozen on:** 2026-09-19", "> **Frozen on:** 2026-09-30")
    assert any("Frozen on" in p for p in gate.check_header(text))


def test_d030_line_altered_fails() -> None:
    text = _protocol().replace("at least six calendar months", "at least three calendar months")
    assert gate.check_d030_rule(text)
    text = _protocol().replace(
        "- no family holds a recorded passing decision.", "- some family fails."
    )
    assert gate.check_d030_rule(text)


def test_d030_inverted_disjunction_fails() -> None:
    text = _protocol() + "\nThe gate fires with fewer than three families.\n"
    assert any("fewer than three" in p for p in gate.check_d030_rule(text))


def test_required_phrase_removed_fails() -> None:
    text = _protocol().replace("Holm-Bonferroni", "Bonferroni")
    assert any("Holm-Bonferroni" in p for p in gate.check_preregistration(text))
    text = _protocol().replace("N = 25", "N = 50")
    assert any("N = 25" in p for p in gate.check_preregistration(text))


def test_forbidden_phrase_present_fails() -> None:
    text = _protocol() + "\nThresholds remain TBD until exercised on real data.\n"
    assert any("Thresholds remain TBD" in p for p in gate.check_no_human_pass(text))


def test_human_pass_wording_fails() -> None:
    text = _protocol() + "\nA family's passing status is a recorded human decision.\n"
    assert any("recorded human decision" in p for p in gate.check_no_human_pass(text))
    stripped = _protocol().replace("may never pass a candidate that fails", "may pass anything")
    assert any("may never pass" in p for p in gate.check_no_human_pass(stripped))


def test_holdout_real_marker_is_valid() -> None:
    doc = json.loads(HOLDOUT.read_text(encoding="utf-8"))
    assert gate.check_holdout_marker(doc) == []
    assert set(doc) == {"schema", "protocol_version", "entries"}


def test_holdout_valid_entry_passes() -> None:
    assert gate.check_holdout_marker(_doc([VALID_ENTRY])) == []


def test_holdout_duplicate_candidate_fails() -> None:
    second = {**VALID_ENTRY, "lineage_id": "trend-pullback@v2"}
    problems = gate.check_holdout_marker(_doc([VALID_ENTRY, second]))
    assert any("duplicates candidate_sha256" in p for p in problems)


def test_holdout_duplicate_lineage_fails() -> None:
    second = {**VALID_ENTRY, "candidate_sha256": "b" * 64}
    problems = gate.check_holdout_marker(_doc([VALID_ENTRY, second]))
    assert any("duplicates lineage_id" in p for p in problems)


def test_holdout_unknown_key_fails() -> None:
    doc = _doc()
    doc["note"] = "extra"
    assert any("unexpected top-level keys" in p for p in gate.check_holdout_marker(doc))


def test_holdout_forbidden_key_fails() -> None:
    entry = {**VALID_ENTRY, "parameter_set_hash": "c" * 64}
    problems = gate.check_holdout_marker(_doc([entry]))
    assert any("forbidden keys" in p for p in problems)
    doc = _doc()
    doc["parameters"] = {}
    assert any("forbidden keys" in p for p in gate.check_holdout_marker(doc))


def test_holdout_entry_missing_consumed_at_fails() -> None:
    entry = {k: v for k, v in VALID_ENTRY.items() if k != "consumed_at_utc"}
    problems = gate.check_holdout_marker(_doc([entry]))
    assert any("consumed_at_utc" in p for p in problems)


def test_holdout_bad_schema_fails() -> None:
    doc = _doc()
    doc["schema"] = "holdout-consumed/2"
    assert any("schema" in p for p in gate.check_holdout_marker(doc))


def test_quantization_order_swapped_fails() -> None:
    text = _protocol()
    swapped = text.replace("`NOTIONAL_REJECT`", "@@TMP@@").replace(
        "`MIN_QTY_REJECT`", "`NOTIONAL_REJECT`"
    )
    swapped = swapped.replace("@@TMP@@", "`MIN_QTY_REJECT`")
    assert gate.check_quantization_order(text) == []
    assert gate.check_quantization_order(swapped)


def test_backtest_spec_real_file_passes() -> None:
    assert gate.check_backtest_spec(BACKTEST_SPEC.read_text(encoding="utf-8")) == []


def test_backtest_spec_still_deferring_thresholds_fails() -> None:
    text = (
        BACKTEST_SPEC.read_text(encoding="utf-8")
        + "\nExact numerical acceptance thresholds remain `TBD` until the research methodology "
        "is exercised on real data.\n"
    )
    assert any("defers" in p for p in gate.check_backtest_spec(text))


def test_universe_and_cost_alignment_citations_required() -> None:
    text = _protocol()
    assert gate.check_universe_reference(text) == []
    assert gate.check_cost_execution_alignment(text) == []
    assert gate.check_universe_reference(text.replace("D039", "D0xx"))
    assert gate.check_cost_execution_alignment(text.replace("D037", "D0xx"))


def test_candidate_sha256_is_deterministic_and_field_sensitive() -> None:
    base = gate.candidate_sha256("trend-pullback", "v1", "d" * 64)
    assert re.fullmatch(r"[0-9a-f]{64}", base)
    assert base == gate.candidate_sha256("trend-pullback", "v1", "d" * 64)
    assert base != gate.candidate_sha256("breakout-retest", "v1", "d" * 64)
    assert base != gate.candidate_sha256("trend-pullback", "v2", "d" * 64)
    assert base != gate.candidate_sha256("trend-pullback", "v1", "e" * 64)


def test_rewrapped_protocol_still_passes_phrase_checks() -> None:
    rewrapped = re.sub(r" (?=\S)", lambda m: "\n  " if m.start() % 7 == 0 else " ", _protocol())
    assert rewrapped != _protocol()
    assert gate.check_preregistration(rewrapped) == []
    assert gate.check_no_human_pass(rewrapped) == []
    assert gate.check_d030_rule(rewrapped) == []
