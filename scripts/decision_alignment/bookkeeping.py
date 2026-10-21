"""Bookkeeping gate module (Phase 11, plan 11-07; D-15, D-16, D-19, D044, D045).

Executable checks for the authority-chain bookkeeping: GLOSSARY reason codes and
ApprovalResult (GL-01..GL-06; the five aliases were retired in Phase 12, so 9.2 is a
removal record), REQUIREMENTS/ROADMAP registration of the 13 new
requirement IDs (RQ-01..RQ-05), and the DECISIONS/DOC_STATUS/DATA_MODEL records
(DC-01..DC-06). ``run()`` returns ``(name, ok, detail)`` tuples. Every check is a pure
function over text (plus the enum and code-reference sets it is handed) so tests can
inject good and bad input.

Stdlib only; ``run_glossary`` imports ``src.domain.enums`` for the enum value sets.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
GLOSSARY_PATH = REPO_ROOT / "docs" / "GLOSSARY.md"
SRC_ROOT = REPO_ROOT / "src"

Gate = tuple[str, bool, str]

# The five synonym codes removed from RejectionReason in Phase 12 (D-09, D046). They are
# recorded in GLOSSARY 9.2 and must never re-enter the enum or the 9.1 canonical block.
RETIRED_ALIASES: tuple[str, ...] = (
    "QUANTIZATION_REJECT",
    "MIN_NOTIONAL_REJECT",
    "RISK_LIMIT",
    "CORRELATED_RISK_LIMIT",
    "DAILY_STOP",
)

# Plain-string codes emitted outside RejectionReason (GL-05).
STRING_CODES: tuple[str, ...] = (
    "DISABLED",
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


def parse_glossary_sections(text: str) -> dict[str, Any]:
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
    """Gates GL-01..GL-06 over GLOSSARY text and the code-derived sets.

    Since Phase 12 the alias set is empty: the 9.1 block is the whole enum and section 9.2
    is a record of the five retired names (``RETIRED_ALIASES``). GL-01 and GL-03 fail if a
    retired name re-enters the enum or the canonical block.
    """
    parsed = parse_glossary_sections(text)
    canonical = list(parsed["canonical"])
    retired_table = list(parsed["aliases"])
    plain = str(parsed["plain"])
    approval = list(parsed["approval"])
    gates: list[Gate] = []

    # GL-01 canonical block: unique tokens, none of the five retired aliases.
    dups = sorted({t for t in canonical if canonical.count(t) > 1})
    leaked = sorted(set(canonical) & set(RETIRED_ALIASES))
    problems = []
    if not canonical:
        problems.append("section 9.1 block missing or empty")
    if dups:
        problems.append("duplicate tokens: " + ", ".join(dups))
    if leaked:
        problems.append("retired aliases in canonical block: " + ", ".join(leaked))
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

    # GL-03 the 9.1 block equals the enum; no retired alias is an enum member; the 9.2
    # table documents exactly the five removed names (it declares no member).
    canonical_set = set(canonical)
    problems = []
    if canonical_set != enum_values:
        only_doc = sorted(canonical_set - enum_values)
        only_enum = sorted(enum_values - canonical_set)
        problems.append(f"9.1 block differs from enum (doc-only {only_doc}, enum-only {only_enum})")
    revived = sorted(set(RETIRED_ALIASES) & enum_values)
    if revived:
        problems.append("retired aliases in enum: " + ", ".join(revived))
    if sorted(retired_table) != sorted(RETIRED_ALIASES):
        problems.append(
            f"retired table is {sorted(retired_table)}, expected {sorted(RETIRED_ALIASES)}"
        )
    gates.append(
        (
            "GL-03",
            not problems,
            "; ".join(problems)
            or f"{len(canonical)} canonical equal enum, {len(retired_table)} retired recorded",
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
    kill = list(parsed["kill_tokens"])
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


# --------------------------------------------------------------------------- REQUIREMENTS

# The 13 requirement IDs registered by plan 11-07 (F-116 and related findings) and the
# phase that implements each. They stay Pending here; later phases complete them.
# Phases are strings so a decimal (inserted) phase can be named: OPS-06 moved from Phase 13 to
# Phase 13.1 when the roadmap inserted the deployment phase (REQUIREMENTS.md and ROADMAP.md agree).
NEW_REQUIREMENTS: dict[str, str] = {
    "RISK-03": "20",
    "RISK-04": "19",
    "EXEC-04": "17",
    "EXEC-05": "18",
    "EXEC-06": "20",
    "EXEC-07": "19",
    "DOMN-04": "17",
    "BKTS-04": "14",
    "OPS-03": "24",
    "OPS-04": "24",
    "OPS-05": "20",
    "OPS-06": "13.1",
    "GOV-02": "26",
}

MIN_REQUIREMENTS = 43
REQUIREMENTS_REGISTERED_ON = "2026-09-30"

REQUIREMENTS_PATH = REPO_ROOT / ".planning" / "REQUIREMENTS.md"
ROADMAP_PATH = REPO_ROOT / ".planning" / "ROADMAP.md"

_LIST_ITEM = re.compile(r"^- \[[ x]\] \*\*([A-Z]+-\d+)\*\*:", flags=re.MULTILINE)
_TRACE_ROW = re.compile(r"^\| ([A-Z]+-\d+) \| Phase ([\d.]+) \| (\w+) \|", flags=re.MULTILINE)


def _roadmap_requirements_line(roadmap: str, phase: str) -> str:
    """The ``**Requirements**:`` line inside the ``### Phase <phase>:`` section."""
    body = _slice(roadmap, rf"^### Phase {re.escape(phase)}:[^\n]*\n", r"^### Phase ")
    match = re.search(r"^\*\*Requirements\*\*:[^\n]*", body, flags=re.MULTILINE)
    return match.group(0) if match else ""


def check_requirements(req_text: str, roadmap_text: str) -> list[Gate]:
    """Gates RQ-01..RQ-05 over REQUIREMENTS.md and ROADMAP.md text."""
    req = _norm(req_text)
    roadmap = _norm(roadmap_text)
    items = _LIST_ITEM.findall(req)
    rows = _TRACE_ROW.findall(req)
    row_ids = [r[0] for r in rows]
    gates: list[Gate] = []

    # RQ-01 each new ID: exactly one list item and one traceability row with the phase.
    problems: list[str] = []
    for rid, phase in NEW_REQUIREMENTS.items():
        if items.count(rid) != 1:
            problems.append(f"{rid} list items: {items.count(rid)}")
        matching = [r for r in rows if r[0] == rid]
        if len(matching) != 1:
            problems.append(f"{rid} trace rows: {len(matching)}")
        elif matching[0][1] != phase:
            # Status is deliberately not pinned: later phases complete these IDs.
            problems.append(f"{rid} row is Phase {matching[0][1]}, expected Phase {phase}")
    gates.append(("RQ-01", not problems, "; ".join(problems) or "13 IDs listed and mapped"))

    # RQ-02 coverage block counts are consistent with the list and table (invariants, not a
    # snapshot); the floor of 43 is the registry size after Phase 11 registered 13 IDs.
    distinct = len(set(items))
    mapped = len(set(row_ids))
    match_total = re.search(r"v1 requirements: (\d+) total", req)
    match_mapped = re.search(r"Mapped to phases: (\d+)", req)
    match_unmapped = re.search(r"Unmapped: (\d+)", req)
    got = (
        int(match_total.group(1)) if match_total else -1,
        int(match_mapped.group(1)) if match_mapped else -1,
        int(match_unmapped.group(1)) if match_unmapped else -1,
    )
    ok02 = got == (distinct, mapped, distinct - mapped) and distinct >= MIN_REQUIREMENTS
    gates.append(
        (
            "RQ-02",
            ok02,
            "ok"
            if ok02
            else f"coverage {got}, list IDs {distinct}, table IDs {mapped}, "
            f"expected ({distinct}, {mapped}, {distinct - mapped}) with at least "
            f"{MIN_REQUIREMENTS} IDs",
        )
    )

    # RQ-03 no duplicate IDs; the table has one row per list ID and nothing else.
    dup_items = sorted({i for i in items if items.count(i) > 1})
    dup_rows = sorted({i for i in row_ids if row_ids.count(i) > 1})
    problems = []
    if dup_items:
        problems.append("duplicate list IDs: " + ", ".join(dup_items))
    if dup_rows:
        problems.append("duplicate trace rows: " + ", ".join(dup_rows))
    if set(items) != set(row_ids):
        problems.append(f"list/table ID mismatch: {sorted(set(items) ^ set(row_ids))}")
    gates.append(("RQ-03", not problems, "; ".join(problems) or "one row per ID"))

    # RQ-04 ROADMAP requirement lines carry the new IDs; placeholder sentences are gone.
    problems = []
    by_phase: dict[str, list[str]] = {}
    for rid, phase in NEW_REQUIREMENTS.items():
        by_phase.setdefault(phase, []).append(rid)
    for phase, ids in sorted(by_phase.items()):
        line = _roadmap_requirements_line(roadmap, phase)
        absent = [i for i in ids if i not in line]
        if absent:
            problems.append(f"Phase {phase} Requirements line lacks {', '.join(absent)}")
    if not re.search(
        r"Thirteen new REQ-IDs.*phases 13-26", _roadmap_requirements_line(roadmap, "11")
    ):
        problems.append("Phase 11 Requirements line lacks the registration sentence")
    for stale in ("New REQ-IDs are to be added", "A new REQ-ID is to be added"):
        if stale in roadmap:
            problems.append(f"stale sentence still present: {stale}")
    if "research-universe-v1.toml" not in _slice(
        roadmap, r"^### Phase 13:[^\n]*\n", r"^### Phase "
    ):
        problems.append("Phase 13 lacks the universe freeze sentence")
    gates.append(("RQ-04", not problems, "; ".join(problems) or "ROADMAP lines updated"))

    # RQ-05 footer names an update date no earlier than the Phase 11 registration.
    footer = re.search(r"^\*Last updated: (\d{4}-\d{2}-\d{2})", req, flags=re.MULTILINE)
    ok05 = footer is not None and footer.group(1) >= REQUIREMENTS_REGISTERED_ON
    gates.append(
        (
            "RQ-05",
            ok05,
            "ok" if ok05 else f"footer date is not on or after {REQUIREMENTS_REGISTERED_ON}",
        )
    )
    return gates


def run_reqs() -> list[Gate]:
    """Evaluate RQ-01..RQ-05 against the real REQUIREMENTS.md and ROADMAP.md."""
    missing = [p.name for p in (REQUIREMENTS_PATH, ROADMAP_PATH) if not p.is_file()]
    if missing:
        # .planning/ is archived by milestone completion and filtered out of PR branches.
        detail = f"SKIP: {', '.join(missing)} not present"
        return [(f"RQ-0{n}", True, detail) for n in range(1, 6)]
    return check_requirements(_read(REQUIREMENTS_PATH), _read(ROADMAP_PATH))


# --------------------------------------------------------------------------- DECISIONS

DECISIONS_PATH = REPO_ROOT / "docs" / "DECISIONS.md"
DOC_STATUS_PATH = REPO_ROOT / "docs" / "DOC_STATUS.md"
DATA_MODEL_PATH = REPO_ROOT / "docs" / "data" / "DATA_MODEL.md"
SEC_OPS_PATH = REPO_ROOT / "docs" / "operations" / "SECURITY_AND_OPERATIONS.md"
PROTOCOL_PATH = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"

# Decisions must run contiguously from D001 to at least this ID; later decisions append.
MIN_LAST_DECISION = 48

# Owner phases named by the D044 follow-up list (DC-04).
D044_OWNER_PHASES: tuple[str, ...] = (
    "Phase 12",
    "Phase 13",
    "Phase 14",
    "Phase 17",
    "Phase 18",
    "Phase 20",
    "Phase 22",
    "Phase 24",
    "Phase 26",
)
D044_TOKENS: tuple[str, ...] = (
    "D031",
    "D039",
    "baseline-v4",
    "research-universe-v1.toml",
    *D044_OWNER_PHASES,
)
D045_TOKENS: tuple[str, ...] = (
    "trades",
    "feature_snapshots",
    "experiment_runs",
    "application-level",
    "F-128",
    "OPS-02",
)

# DATA_MODEL sections that carry a "not built in V1" note (DC-05).
DATA_MODEL_NOTED: tuple[tuple[str, str], ...] = (
    ("2.2", "feature_snapshots"),
    ("2.6", "trades"),
    ("2.12", "experiment_runs"),
)

_DECISION_ROW = re.compile(r"^\| (D\d{3}) \|", flags=re.MULTILINE)


def _decision_row(decisions: str, decision_id: str) -> str:
    match = re.search(rf"^\| {decision_id} \|[^\n]*", _norm(decisions), flags=re.MULTILINE)
    return match.group(0) if match else ""


def check_decisions(
    decisions: str,
    doc_status: str,
    data_model: str,
    sec_ops: str,
    protocol: str | None = None,
) -> list[Gate]:
    """Gates DC-01..DC-06 over DECISIONS, DOC_STATUS, DATA_MODEL and SECURITY_AND_OPERATIONS.

    ``protocol`` is the research protocol text (default: the real file); DC-03 reads the header
    version from it so the freeze-row witness is never a typed literal (D-28).
    """
    text = _norm(decisions)
    lines = text.split("\n")
    gates: list[Gate] = []

    # DC-01 contiguous table: header row through the last decision row, all pipe lines.
    header = next((i for i, ln in enumerate(lines) if ln.startswith("| ID |")), None)
    last = max((i for i, ln in enumerate(lines) if _DECISION_ROW.match(ln)), default=None)
    if header is None or last is None:
        gates.append(("DC-01", False, "table header or rows not found"))
    else:
        bad = [i + 1 for i in range(header, last + 1) if not lines[i].startswith("|")]
        gates.append(
            (
                "DC-01",
                not bad,
                f"non-table lines inside the table at {bad}" if bad else "contiguous",
            )
        )

    # DC-02 IDs are D001.. contiguous, unique, in order, and reach at least D048.
    ids = _DECISION_ROW.findall(text)
    contiguous = [f"D{n:03d}" for n in range(1, len(ids) + 1)]
    ok02 = ids == contiguous and len(ids) >= MIN_LAST_DECISION
    gates.append(
        (
            "DC-02",
            ok02,
            "ok"
            if ok02
            else f"IDs end at {ids[-1] if ids else 'none'}, count {len(ids)}, "
            f"expected contiguous D001..D{MIN_LAST_DECISION:03d} or later",
        )
    )

    # DC-03 the historic D043 witness row and the row for the current header version.
    protocol_text = _read(PROTOCOL_PATH) if protocol is None else protocol
    version = re.search(
        r"^>\s*\*\*Protocol version:\*\*\s*(v\d+\.\d+\.\d+)\s*$", protocol_text, re.MULTILINE
    )
    problems03: list[str] = []
    if "protocol v1.1.0 frozen" not in _decision_row(decisions, "D043"):
        problems03.append("D043 lacks 'protocol v1.1.0 frozen'")
    if version is None:
        problems03.append("protocol header carries no Protocol version vX.Y.Z")
    elif not re.search(
        rf"^\| D\d{{3}} \|[^\n]*protocol {re.escape(version.group(1))} frozen",
        text,
        flags=re.MULTILINE,
    ):
        problems03.append(f"DECISIONS has no row with 'protocol {version.group(1)} frozen'")
    gates.append(("DC-03", not problems03, "; ".join(problems03) or "ok"))

    # DC-04 D044 and D045 content.
    d044 = _decision_row(decisions, "D044")
    d045 = _decision_row(decisions, "D045")
    problems: list[str] = []
    if not d044:
        problems.append("D044 row missing")
    else:
        problems += [f"D044 lacks {t}" for t in D044_TOKENS if t not in d044]
    if not d045:
        problems.append("D045 row missing")
    else:
        problems += [f"D045 lacks {t}" for t in D045_TOKENS if t not in d045]
    gates.append(("DC-04", not problems, "; ".join(problems) or "D044 and D045 complete"))

    # DC-05 DOC_STATUS change-log line and the three DATA_MODEL notes.
    problems = []
    status_lines = [
        ln for ln in _norm(doc_status).split("\n") if ln.startswith("- 2026-09-30") and "D044" in ln
    ]
    if not status_lines:
        problems.append("DOC_STATUS has no 2026-09-30 line mentioning D044")
    model = _norm(data_model)
    for number, name in DATA_MODEL_NOTED:
        body = _slice(model, rf"^### {re.escape(number)} `{name}`[^\n]*\n", r"^#{2,3} ")
        first = next((ln for ln in body.split("\n") if ln.strip()), "")
        if not first.startswith("**V1 status: not built (D045).**"):
            problems.append(f"DATA_MODEL {number} {name} lacks the V1 status note")
    gates.append(("DC-05", not problems, "; ".join(problems) or "log line and notes present"))

    # DC-06 SECURITY_AND_OPERATIONS cites D045 and the row exists.
    ok06 = "D045" in sec_ops and bool(d045)
    gates.append(("DC-06", ok06, "ok" if ok06 else "SECURITY_AND_OPERATIONS/D045 reference broken"))
    return gates


def run_decisions() -> list[Gate]:
    """Evaluate DC-01..DC-06 against the real documents."""
    return check_decisions(
        _read(DECISIONS_PATH),
        _read(DOC_STATUS_PATH),
        _read(DATA_MODEL_PATH),
        _read(SEC_OPS_PATH),
    )


def run() -> list[Gate]:
    """Every bookkeeping gate against the real repository."""
    return run_glossary() + run_reqs() + run_decisions()


if __name__ == "__main__":  # pragma: no cover
    import sys

    results = run()
    for gate_name, gate_ok, gate_detail in results:
        print(("PASS" if gate_ok else "FAIL"), gate_name, gate_detail)
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
