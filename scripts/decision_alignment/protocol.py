"""Protocol gate module (Phase 11, plan 11-01; D032, D043; amended to v2.0.0 by D052).

Executable checks that keep the frozen research protocol, the DECISIONS row, the
DOC_STATUS index, the holdout consumed marker and the BACKTEST_SPEC pointers
consistent. ``run()`` returns ``(name, ok, detail)`` tuples PR-01..PR-10; every
check is also a pure function over text (or a parsed JSON document) so tests can
inject bad input.

Stdlib plus ``src.domain.canonical.sha256_hex`` only.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.domain.canonical import sha256_hex

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"
DECISIONS_PATH = REPO_ROOT / "docs" / "DECISIONS.md"
DOC_STATUS_PATH = REPO_ROOT / "docs" / "DOC_STATUS.md"
HOLDOUT_PATH = REPO_ROOT / "docs" / "research" / "holdout_consumed.json"
BACKTEST_SPEC_PATH = REPO_ROOT / "docs" / "backtest" / "BACKTEST_SPEC.md"

FROZEN_ON = "2026-09-19"
UNIVERSE_MANIFEST = "docs/research/universe/research-universe-v1.toml"

# D030 kill-gate firing rule, copied verbatim from commit 679825c (protocol v1.0.1).
# Compared after whitespace collapsing only (markup is kept), so a re-wrap is tolerated
# but any changed word is not.
D030_LINES: tuple[str, ...] = (
    "The kill gate fires only when **all three** conditions hold:",
    "- at least three **independently specified** candidate families have been tested under "
    "the frozen methodology (backtest + out-of-sample evidence), **and**",
    "- at least six calendar months have elapsed since the protocol freeze date "
    "(the header `Frozen on` date, taken at 00:00Z), **and**",
    "- no family holds a recorded passing decision.",
    '"Independently specified" means a distinct `strategy_id`, a 7-slot family sheet, a '
    "distinct sheet content hash and distinct registered parameter-set hashes (baselines "
    "excluded). Until all three hold the state is WITHIN_BUDGET (keep researching) or "
    "PASSING_CANDIDATE (a family holds a recorded passing decision; this does not authorize "
    "live).",
    "This wording conforms the section to D013 and is recorded as D030 (protocol v1.0.1, "
    "clarification only; see the Amendment log).",
    "When the kill gate fires, the project stops adding complexity, keeps live execution "
    "disabled, classifies the artifact as research/journal infrastructure, and continues to "
    "log NO_TRADE outcomes. NO_TRADE is a valid outcome of the kill gate; a forced green "
    "light is not.",
)

REQUIRED_PREREGISTRATION_PHRASES: tuple[str, ...] = (
    "Pre-registered thresholds (v1.1.0)",
    "first 40% of the dataset by time",
    "four consecutive equal-length walk-forward test folds",
    "the last 20% of the dataset by time",
    "at least 100 closed trades pooled across the four Validation folds",
    "at least 30 closed trades in each Validation fold",
    "lower bound of the 95% block-bootstrap interval",
    "20% of research equity",
    "N = 25",
    "Holm-Bonferroni",
    "alpha = 0.05",
    "about 14%",
    "A candidate passes only when G1-G5 all pass",
    "holdout_consumed.json",
    "candidate_sha256",
)

FORBIDDEN_PHRASES: tuple[str, ...] = (
    "recorded human decision",
    "Thresholds remain TBD",
    "remain TBD",
    "is TBD until exercised on real data",
    "TBD until Validation",
    "fewer than three",
)

HUMAN_ROLE_PHRASES: tuple[str, ...] = (
    "may reject a candidate that passes",
    "may never pass a candidate that fails",
)

FORBIDDEN_HOLDOUT_KEYS = frozenset(
    {"parameterSetId", "parameter_set_id", "parameterSetHash", "parameter_set_hash", "parameters"}
)
HOLDOUT_TOP_KEYS = frozenset({"schema", "protocol_version", "entries"})
HOLDOUT_ENTRY_KEYS = frozenset(
    {"lineage_id", "candidate_sha256", "consumed_at_utc", "decision_ref"}
)
HOLDOUT_SCHEMA = "holdout-consumed/1"

QUANTIZATION_ORDER: tuple[str, ...] = (
    "stepSize",
    "MIN_QTY_REJECT",
    "NOTIONAL_REJECT",
    "UTILIZATION_REJECT",
)

_HEADER_LINE = re.compile(r"^>\s*\*\*(?P<key>[^:*]+):\*\*\s*(?P<value>.*?)\s*$", re.MULTILINE)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def candidate_sha256(strategy_id: str, strategy_version: str, parameter_set_hash: str) -> str:
    """Deterministic candidate-spec hash used as the holdout consumed-marker key."""
    return sha256_hex(
        {
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "parameter_set_hash": parameter_set_hash,
        }
    )


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _norm(text: str) -> str:
    """Whitespace-collapsed text with ``**`` and backticks stripped (phrase matching)."""
    return _collapse(text.replace("**", "").replace("`", ""))


def _header(protocol: str) -> dict[str, str]:
    return {m.group("key").strip(): m.group("value") for m in _HEADER_LINE.finditer(protocol)}


def _between(text: str, start: str, end: str | None) -> str:
    begin = text.find(start)
    if begin < 0:
        return ""
    rest = text[begin:]
    if end is None:
        return rest
    stop = rest.find(end, len(start))
    return rest if stop < 0 else rest[:stop]


def _header_version(protocol: str) -> str | None:
    value = _header(protocol).get("Protocol version", "")
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)", value)
    return match.group(1) if match else None


def check_header(protocol: str) -> list[str]:
    """PR-02: Frozen on is unchanged; Amended on and a Supersedes version are present."""
    header = _header(protocol)
    problems: list[str] = []
    if header.get("Status") != "FROZEN":
        problems.append("header Status is not FROZEN")
    if header.get("Frozen on") != FROZEN_ON:
        problems.append(f"header Frozen on is not {FROZEN_ON} (kill-gate clock start, D030)")
    amended = header.get("Amended on", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", amended):
        problems.append("header carries no Amended on date")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", header.get("Supersedes", "")):
        problems.append("header Supersedes does not name a vX.Y.Z protocol version")
    if _header_version(protocol) is None:
        problems.append("header carries no Protocol version vX.Y.Z")
    return problems


def check_witnesses(protocol: str, decisions: str, doc_status: str) -> list[str]:
    """PR-01: header version = DECISIONS ``protocol vV frozen`` row = DOC_STATUS index line."""
    version = _header_version(protocol)
    if version is None:
        return ["header carries no Protocol version vX.Y.Z"]
    problems: list[str] = []
    row = re.compile(rf"^\| D\d+ \| .*protocol v{re.escape(version)} frozen", re.MULTILINE)
    if not row.search(decisions):
        problems.append(f"DECISIONS has no 'protocol v{version} frozen' row")
    index_lines = [
        ln for ln in doc_status.splitlines() if ln.startswith("- `research/RESEARCH_PROTOCOL.md`")
    ]
    if len(index_lines) != 1:
        problems.append("DOC_STATUS must carry exactly one protocol index line")
    elif f"v{version}" not in index_lines[0]:
        problems.append(f"DOC_STATUS protocol index line does not name v{version}")
    return problems


def check_d030_rule(protocol: str) -> list[str]:
    """PR-03: the D030 firing rule is verbatim and the inverted disjunction is absent."""
    collapsed = _collapse(protocol)
    problems = [
        f"D030 line altered or missing: {line[:60]!r}"
        for line in D030_LINES
        if _collapse(line) not in collapsed
    ]
    if "fewer than three" in _norm(protocol).lower():
        problems.append("inverted disjunction wording ('fewer than three') is present")
    return problems


def check_preregistration(protocol: str) -> list[str]:
    """PR-04: every pre-registration phrase is present."""
    norm = _norm(protocol)
    return [
        f"missing pre-registration phrase: {phrase!r}"
        for phrase in REQUIRED_PREREGISTRATION_PHRASES
        if phrase not in norm
    ]


def check_no_human_pass(protocol: str) -> list[str]:
    """PR-05: no wording lets a human pass a failing candidate; the two role phrases exist."""
    norm = _norm(protocol)
    problems = [f"forbidden phrase present: {p!r}" for p in FORBIDDEN_PHRASES if p in norm]
    problems += [f"missing human-role phrase: {p!r}" for p in HUMAN_ROLE_PHRASES if p not in norm]
    return problems


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys |= _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= _all_keys(child)
    return keys


def _parse_utc(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def check_holdout_marker(doc: Any) -> list[str]:
    """PR-06: the consumed marker is well-formed, append-only-shaped and duplicate free."""
    if not isinstance(doc, dict):
        return ["holdout marker is not a JSON object"]
    problems: list[str] = []
    keys = set(doc)
    if keys != HOLDOUT_TOP_KEYS:
        problems.append(f"unexpected top-level keys: {sorted(keys ^ HOLDOUT_TOP_KEYS)}")
    forbidden = sorted(_all_keys(doc) & FORBIDDEN_HOLDOUT_KEYS)
    if forbidden:
        problems.append(f"forbidden keys present (research-gate tripwire): {forbidden}")
    if doc.get("schema") != HOLDOUT_SCHEMA:
        problems.append(f"schema is not {HOLDOUT_SCHEMA!r}")
    version = doc.get("protocol_version")
    if not isinstance(version, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        problems.append("protocol_version is not vX.Y.Z")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        problems.append("entries is not a list")
        return problems
    seen_lineage: set[str] = set()
    seen_candidate: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"entry {index} is not an object")
            continue
        if set(entry) != HOLDOUT_ENTRY_KEYS:
            problems.append(f"entry {index} keys differ: {sorted(set(entry) ^ HOLDOUT_ENTRY_KEYS)}")
        lineage = entry.get("lineage_id")
        candidate = entry.get("candidate_sha256")
        if not isinstance(lineage, str) or not lineage:
            problems.append(f"entry {index} lineage_id is empty")
        elif lineage in seen_lineage:
            problems.append(f"entry {index} duplicates lineage_id {lineage!r}")
        else:
            seen_lineage.add(lineage)
        if not isinstance(candidate, str) or not _HEX64.match(candidate):
            problems.append(f"entry {index} candidate_sha256 is not 64 lowercase hex")
        elif candidate in seen_candidate:
            problems.append(f"entry {index} duplicates candidate_sha256")
        else:
            seen_candidate.add(candidate)
        if not _parse_utc(entry.get("consumed_at_utc")):
            problems.append(f"entry {index} consumed_at_utc is not an ISO UTC timestamp")
        decision_ref = entry.get("decision_ref")
        if not isinstance(decision_ref, str) or not decision_ref:
            problems.append(f"entry {index} decision_ref is empty")
    return problems


def _section2(protocol: str) -> str:
    return _between(protocol, "## §2", "## §3")


def check_quantization_order(protocol: str) -> list[str]:
    """PR-07: section 2 lists stepSize, min quantity, min notional, utilization in that order."""
    quant = _between(_section2(protocol), "### Quantization", "\n---")
    if not quant:
        return ["section 2 has no Quantization subsection"]
    positions = [quant.find(token) for token in QUANTIZATION_ORDER]
    missing = [t for t, p in zip(QUANTIZATION_ORDER, positions, strict=True) if p < 0]
    if missing:
        return [f"quantization subsection is missing: {missing}"]
    if positions != sorted(positions):
        return [f"quantization order is not {' > '.join(QUANTIZATION_ORDER)}"]
    return []


def check_backtest_spec(text: str, protocol: str | None = None) -> list[str]:
    """PR-08: BACKTEST_SPEC points at the header protocol version and does not defer thresholds.

    The pointer version is read from the protocol header (``protocol`` text, default: the real
    file), never typed here, so an amendment cannot leave a stale literal behind (D-28).
    """
    norm = _norm(text)
    problems: list[str] = []
    version = _header_version(_read(PROTOCOL_PATH) if protocol is None else protocol)
    if version is None:
        problems.append("protocol header carries no Protocol version vX.Y.Z")
    elif "RESEARCH_PROTOCOL.md" not in norm or f"v{version}" not in norm:
        problems.append(f"BACKTEST_SPEC does not point to protocol v{version}")
    if re.search(r"thresholds\s+remain\s+TBD", norm):
        problems.append("BACKTEST_SPEC still defers numeric thresholds")
    if UNIVERSE_MANIFEST not in norm or "D039" not in norm:
        problems.append("BACKTEST_SPEC does not point the research universe at the D039 manifest")
    return problems


def check_universe_reference(protocol: str) -> list[str]:
    """PR-09: section 1 references the research-universe manifest and D039."""
    section = _norm(_between(protocol, "## §1", "## §2"))
    problems: list[str] = []
    if UNIVERSE_MANIFEST not in section:
        problems.append(f"section 1 does not reference {UNIVERSE_MANIFEST}")
    if "D039" not in section:
        problems.append("section 1 does not cite D039")
    return problems


def check_cost_execution_alignment(protocol: str) -> list[str]:
    """PR-10: sections 2-3 cite D036 (taker entry), D037 (mark price), D038 (fill fraction)."""
    section = _between(protocol, "## §2", "## §4")
    return [f"sections 2-3 do not cite {d}" for d in ("D036", "D037", "D038") if d not in section]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _result(name: str, problems: list[str]) -> tuple[str, bool, str]:
    return (name, not problems, "ok" if not problems else "; ".join(problems))


def run() -> list[tuple[str, bool, str]]:
    """Evaluate gates PR-01..PR-10 against the real repository files."""
    protocol = _read(PROTOCOL_PATH)
    decisions = _read(DECISIONS_PATH)
    doc_status = _read(DOC_STATUS_PATH)
    try:
        holdout_problems = check_holdout_marker(json.loads(_read(HOLDOUT_PATH)))
    except (OSError, ValueError) as exc:
        holdout_problems = [f"holdout marker unreadable: {exc}"]
    try:
        spec_problems = check_backtest_spec(_read(BACKTEST_SPEC_PATH), protocol)
    except OSError as exc:
        spec_problems = [f"BACKTEST_SPEC unreadable: {exc}"]
    return [
        _result("PR-01", check_witnesses(protocol, decisions, doc_status)),
        _result("PR-02", check_header(protocol)),
        _result("PR-03", check_d030_rule(protocol)),
        _result("PR-04", check_preregistration(protocol)),
        _result("PR-05", check_no_human_pass(protocol)),
        _result("PR-06", holdout_problems),
        _result("PR-07", check_quantization_order(protocol)),
        _result("PR-08", spec_problems),
        _result("PR-09", check_universe_reference(protocol)),
        _result("PR-10", check_cost_execution_alignment(protocol)),
    ]


if __name__ == "__main__":
    import sys

    results = run()
    for name, ok, detail in results:
        print(f"{name} {'ok' if ok else 'FAIL'} {detail}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
