"""Machine check of docs/research/GEOMETRY_AUDIT.md (Phase 15, plan 15-01, D-10, F-113).

The audit table compares each family sheet's Stage baseline with the code as it was before
Phase 15. This test fails when a required cell is missing or duplicated, a verdict is outside
the vocabulary, a non-MATCH row cites no decision, or any cell says TBD.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DOC = REPO_ROOT / "docs" / "research" / "GEOMETRY_AUDIT.md"

TABLE_HEADER = (
    "| Family | Cell | Sheet Stage baseline | Code before Phase 15 | "
    "Phase 15 resolution | Verdict | Decision |"
)
VERDICTS = frozenset({"MATCH", "FIX", "DEVIATION", "PARAMETER"})
DECISION_PATTERN = re.compile(r"D-\d\d|D054")

REQUIRED_CELLS: dict[str, tuple[str, ...]] = {
    "A": ("regime", "pullback", "level", "zone", "entry", "stop", "target"),
    "B": ("regime", "direction", "breakout", "retest", "anchoring", "entry", "stop", "target"),
    "C": ("regime", "range", "entry", "stop", "target"),
}
REQUIRED_FLAGS = tuple(f"F{n}" for n in range(1, 13))

COLUMN_COUNT = 7


def _read_doc() -> str:
    """Read the audit doc as UTF-8 with CRLF normalized to LF (working trees may be CRLF)."""
    return AUDIT_DOC.read_text(encoding="utf-8").replace("\r\n", "\n")


def _split_row(line: str) -> list[str]:
    """Split one markdown table row into stripped cells."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_rows(text: str) -> list[dict[str, str]]:
    """Return the audit rows (first cell A, B or C) of the table that follows TABLE_HEADER."""
    rows: list[dict[str, str]] = []
    in_table = False
    for line in text.split("\n"):
        if line.strip() == TABLE_HEADER:
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = _split_row(line)
        if cells[0] not in {"A", "B", "C"}:
            continue
        assert len(cells) == COLUMN_COUNT, f"row has {len(cells)} cells, expected 7: {line[:80]}"
        rows.append(
            {
                "family": cells[0],
                "cell": cells[1],
                "sheet": cells[2],
                "code": cells[3],
                "resolution": cells[4],
                "verdict": cells[5],
                "decision": cells[6],
            }
        )
    return rows


def check_rows(rows: list[dict[str, str]]) -> list[str]:
    """Return every structural problem of the parsed rows (empty list means the table is sound)."""
    problems: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["family"], row["cell"])
        seen[key] = seen.get(key, 0) + 1
    for family, cells in REQUIRED_CELLS.items():
        for cell in cells:
            count = seen.get((family, cell), 0)
            if count != 1:
                problems.append(f"missing or duplicate cell: family {family} cell {cell} x{count}")
    for row in rows:
        label = f"{row['family']}/{row['cell']}"
        if row["verdict"] not in VERDICTS:
            problems.append(f"{label}: verdict {row['verdict']!r} outside the vocabulary")
        if row["verdict"] != "MATCH" and not DECISION_PATTERN.search(row["decision"]):
            problems.append(f"{label}: non-MATCH row cites no decision")
        for name, value in row.items():
            if re.search(r"\bTBD\b", value):
                problems.append(f"{label}: column {name} contains TBD")
    return problems


def test_required_cells_cover_twenty_family_cell_pairs() -> None:
    assert sum(len(cells) for cells in REQUIRED_CELLS.values()) == 20
    assert {family: len(cells) for family, cells in REQUIRED_CELLS.items()} == {
        "A": 7,
        "B": 8,
        "C": 5,
    }


def test_audit_doc_exists_and_has_table_header() -> None:
    assert AUDIT_DOC.is_file()
    assert TABLE_HEADER in _read_doc()


def test_audit_table_is_sound() -> None:
    rows = parse_rows(_read_doc())
    assert rows, "no audit rows parsed"
    assert check_rows(rows) == []


def test_missing_required_cell_is_detected() -> None:
    text = _read_doc()
    kept = [line for line in text.split("\n") if not line.startswith("| A | level |")]
    assert len(kept) == len(text.split("\n")) - 1, "the level row was not found in the doc"
    problems = check_rows(parse_rows("\n".join(kept)))
    assert any("cell level" in p and "x0" in p for p in problems)


def test_verdict_outside_vocabulary_is_detected() -> None:
    rows = parse_rows(_read_doc())
    rows[0] = {**rows[0], "verdict": "MAYBE"}
    assert any("outside the vocabulary" in p for p in check_rows(rows))


def test_non_match_row_without_decision_is_detected() -> None:
    rows = parse_rows(_read_doc())
    index = next(i for i, r in enumerate(rows) if r["verdict"] != "MATCH")
    rows[index] = {**rows[index], "decision": "n/a"}
    assert any("cites no decision" in p for p in check_rows(rows))


def test_tbd_in_any_cell_is_detected() -> None:
    rows = parse_rows(_read_doc())
    rows[0] = {**rows[0], "resolution": "value is TBD"}
    assert any("contains TBD" in p for p in check_rows(rows))


def test_arithmetic_section_carries_the_acceptance_anchors() -> None:
    text = _read_doc()
    assert "## Arithmetic" in text
    assert "59,680" in text
    assert "no plan with SL inside the zone" in text


def test_flags_table_lists_each_research_flag_exactly_once() -> None:
    text = _read_doc()
    assert "## Research flags and their disposition" in text
    flag_rows = [_split_row(line) for line in text.splitlines() if re.match(r"\| F\d+ \|", line)]
    assert sorted(row[0] for row in flag_rows) == sorted(REQUIRED_FLAGS)
    for row in flag_rows:
        assert len(row) == 4, f"flag row {row[0]} must have Flag, Finding, Disposition, Plan"
        assert re.fullmatch(r"15-\d\d(, 15-\d\d)*", row[3]), f"{row[0]}: plan cell {row[3]!r}"
        assert "TBD" not in re.split(r"\W+", " ".join(row))


def test_leakage_verdicts_heading_and_d23_supersession_present() -> None:
    text = _read_doc()
    assert "## Leakage verdicts (D-13)" in text
    assert "superseded by D-23" in text


def test_universal_invariants_section_lists_reasons_and_order() -> None:
    text = _read_doc()
    assert "## Universal planner invariants" in text
    for token in ("D-06", "D-07", "D-08", "F6", "STOP_TOO_TIGHT", "INVALIDATED", "RR_TOO_LOW"):
        assert token in text


# --------------------------------------------------------------------------- #
# Family sheets (plan 15-14, D-12, F-113, T-15-24)
# --------------------------------------------------------------------------- #

SHEETS_ROOT = REPO_ROOT / "docs" / "research" / "families"
SHEET_FAMILIES = ("trend-pullback", "breakout-retest", "range-mr")
IMPLEMENTED_AS = "Implemented as (Phase 15, D054)"
BASELINE_LINE = re.compile(r"^- Stage [ABC] baseline implemented: (?P<value>.+)$", re.MULTILINE)
VARIANTS_LINE = re.compile(
    r"^- (?P<names>[^\n]*variants implemented): (?P<value>.+)$", re.MULTILINE
)


def _read_sheet(family: str) -> str:
    """Read one family sheet as UTF-8 with CRLF normalized to LF."""
    return (SHEETS_ROOT / f"{family}.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def check_sheet(text: str) -> list[str]:
    """Return every structural problem of one family sheet (empty list means the sheet is sound)."""
    problems: list[str] = []
    status = next((line for line in text.split("\n") if line.startswith("> Status:")), "")
    if "HYPOTHESIS" not in status or "**NOT FROZEN**" not in status:
        problems.append(f"Status line is not 'HYPOTHESIS ... NOT FROZEN': {status!r}")
    if not re.search(rf"^###? .*{re.escape(IMPLEMENTED_AS)}", text, re.MULTILINE):
        problems.append(f"no heading carries {IMPLEMENTED_AS!r}")
    baseline = BASELINE_LINE.search(text)
    if baseline is None:
        problems.append("no 'Stage X baseline implemented' acceptance line")
    else:
        value = baseline.group("value")
        for token in ("AS RECORDED", "baseline-v6", "D054"):
            if token not in value:
                problems.append(f"baseline implemented line lacks {token!r}: {value!r}")
    variants = VARIANTS_LINE.search(text)
    if variants is None:
        problems.append("no variants-implemented acceptance line")
    elif not variants.group("value").endswith("`NO`"):
        problems.append(f"variants line no longer ends in `NO`: {variants.group('value')!r}")
    return problems


def test_sheet_check_covers_all_three_families() -> None:
    assert SHEET_FAMILIES == ("trend-pullback", "breakout-retest", "range-mr")


def test_family_sheets_record_the_implemented_geometry_and_stay_not_frozen() -> None:
    for family in SHEET_FAMILIES:
        assert check_sheet(_read_sheet(family)) == [], family


def test_sheet_check_detects_a_frozen_status_a_missing_record_and_a_flipped_variants_line() -> None:
    text = _read_sheet("trend-pullback")
    frozen = text.replace("**NOT FROZEN**", "**FROZEN**", 1)
    assert any("NOT FROZEN" in p for p in check_sheet(frozen))
    missing = text.replace(IMPLEMENTED_AS, "Implementation note")
    assert any(IMPLEMENTED_AS in p for p in check_sheet(missing))
    no_baseline = BASELINE_LINE.sub("- Stage A baseline implemented: `NO`", text)
    assert any("baseline implemented line lacks" in p for p in check_sheet(no_baseline))
    flipped = VARIANTS_LINE.sub(lambda m: f"- {m.group('names')}: `YES`", text)
    assert any("no longer ends in `NO`" in p for p in check_sheet(flipped))


def test_glossary_states_the_planner_meanings_without_touching_the_enum_block() -> None:
    text = (REPO_ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "Phase 15 planner meanings (D054, D-27)" in text
    assert "min_stop_atr" in text
    block = re.search(r"### 9\.1 Canonical codes\n\n```text\n(.*?)```", text, re.DOTALL)
    assert block is not None
    assert len(block.group(1).split()) == 21  # plan 20-05 added ENTRY_WITHOUT_PROTECTIVE


def test_configuration_documents_the_phase15_keys_and_current_sets() -> None:
    path = REPO_ROOT / "docs" / "configuration" / "CONFIGURATION.md"
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "Phase 15 geometry keys (D054)" in text
    for key in (
        "pivot_left_bars",
        "pivot_right_bars",
        "geometry_version",
        "tp_mode",
        "min_stop_atr",
    ):
        assert f"| `{key}` |" in text, key
    for set_id in ("baseline-v6", "baseline-no-trade-v4", "baseline-simple-trend-v4", "v5.0.0"):
        assert set_id in text, set_id


# --------------------------------------------------------------------------- #
# Final audit (plan 15-15, D-14, D-20, F8, T-15-25)
# --------------------------------------------------------------------------- #

READINESS_HEADING = "## Re-run readiness (criterion 4)"
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
SRC_CORE = REPO_ROOT / "src" / "core"

# The function that implements each FIX row (the plan 15-15 list).
FIX_FUNCTIONS: dict[tuple[str, str], tuple[str, ...]] = {
    ("A", "level"): ("pivot_at", "_detect_pivot_setup"),
    ("A", "stop"): ("_pivot_geometry", "_geometry_rejection"),
    ("B", "direction"): ("_detect_breakout_retest_levels",),
    ("B", "anchoring"): ("_detect_breakout_retest_levels", "_find_retest_bar"),
    ("B", "stop"): ("_breakout_retest_geometry",),
    ("C", "regime"): ("_resolve_regime_pivots",),
    ("C", "stop"): ("_range_mr_geometry",),
    ("C", "target"): ("_range_mr_geometry",),
}


def _src_core_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(SRC_CORE.glob("*.py")))


def _readiness_section(text: str) -> str:
    """The readiness section body: from its heading up to the next level-2 heading."""
    start = text.index(READINESS_HEADING)
    rest = text[start + len(READINESS_HEADING) :]
    match = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: match.start()] if match else rest


def test_no_parameter_verdict_remains_and_ratified_breakout_is_a_match() -> None:
    rows = parse_rows(_read_doc())
    assert [f"{r['family']}/{r['cell']}" for r in rows if r["verdict"] == "PARAMETER"] == []
    breakout = next(r for r in rows if (r["family"], r["cell"]) == ("B", "breakout"))
    assert breakout["verdict"] == "MATCH"
    assert "`breakout_confirmation_bars` = 1" in breakout["resolution"]


def test_every_deviation_row_cites_d054() -> None:
    rows = parse_rows(_read_doc())
    deviations = [r for r in rows if r["verdict"] == "DEVIATION"]
    assert len(deviations) == 7
    assert [f"{r['family']}/{r['cell']}" for r in deviations if "D054" not in r["decision"]] == []


def test_every_fix_row_names_an_existing_implementing_function() -> None:
    rows = parse_rows(_read_doc())
    fixes = {(r["family"], r["cell"]): r for r in rows if r["verdict"] == "FIX"}
    assert set(fixes) == set(FIX_FUNCTIONS)
    source = _src_core_text()
    for key, names in FIX_FUNCTIONS.items():
        resolution = fixes[key]["resolution"]
        for name in names:
            assert f"`{name}`" in resolution, f"{key}: resolution does not name {name}"
            assert re.search(rf"^def {name}\(", source, re.MULTILINE), f"{name} is not defined"


def test_readiness_section_has_a_digest_row_per_family_with_zero_violations() -> None:
    text = _read_doc()
    assert text.count(READINESS_HEADING) == 1
    section = _readiness_section(text)
    for family in SHEET_FAMILIES:
        rows = [ln for ln in section.split("\n") if ln.startswith(f"| {family} |")]
        assert any(HEX64.search(ln) and "invariant_violations 0" in ln for ln in rows), family
    for token in (
        "digests_match=true",
        "RESEARCH_PROTOCOL",
        "no amendment",
        "research-universe-v1",
    ):
        assert token.lower() in section.lower(), token
    assert "PLACEHOLDER" in section
