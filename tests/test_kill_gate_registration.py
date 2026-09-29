"""Registration tripwire for a recorded terminal kill-gate state (Phase 10, plan 10-07, D-03).

CI cannot read the journal, so the terminal outcome is mirrored in the committed human
decision record `docs/research/kill_gate_decisions.json`. While that record carries
`recorded_terminal` (state INSUFFICIENT_EDGE), the set of strategy-family directories under
`params/` must equal `families_at_record`: a new family directory fails this test (D-03: the
terminal outcome blocks new strategy-family registration; RESEARCH Open Question 5 option b).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from src.analytics.killgate import registration_allowed
from src.domain.enums import KillGateState

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISIONS_PATH = REPO_ROOT / "docs" / "research" / "kill_gate_decisions.json"
PARAMS_DIR = REPO_ROOT / "params"

SCHEMA_ID = "kill-gate-decisions/1"
FAMILY_KEYS = {
    "family_id",
    "status",
    "decision_ref",
    "decided_at_utc",
    "development_experiment_ids",
    "validation_experiment_ids",
}
RESET_KEYS = {"operator_id", "decision_ref", "occurred_at_utc"}
TERMINAL_KEYS = {"state", "decision_ref", "recorded_at_utc", "families_at_record"}
FORBIDDEN_KEYS = {"parameterSetId", "parameter_set_id", "parameterSetHash", "parameter_set_hash"}


def _load() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    return loaded


def _all_keys(node: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            keys |= _all_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _all_keys(item)
    return keys


def schema_violations(doc: dict[str, Any]) -> list[str]:
    """Structural checks of the decision record (empty list when valid)."""
    problems: list[str] = []
    if set(doc) != {"schema", "families", "resets", "recorded_terminal"}:
        problems.append(f"unexpected top-level keys: {sorted(doc)}")
        return problems
    if doc["schema"] != SCHEMA_ID:
        problems.append(f"schema must be {SCHEMA_ID}")
    if not isinstance(doc["families"], list):
        problems.append("families must be a list")
    else:
        for entry in doc["families"]:
            if not isinstance(entry, dict) or not FAMILY_KEYS <= set(entry):
                problems.append(f"family entry missing keys {sorted(FAMILY_KEYS)}: {entry!r}")
    if not isinstance(doc["resets"], list):
        problems.append("resets must be a list")
    else:
        for entry in doc["resets"]:
            if not isinstance(entry, dict) or not RESET_KEYS <= set(entry):
                problems.append(f"reset entry missing keys {sorted(RESET_KEYS)}: {entry!r}")
    terminal = doc["recorded_terminal"]
    if terminal is not None:
        if not isinstance(terminal, dict) or set(terminal) != TERMINAL_KEYS:
            problems.append(f"recorded_terminal must carry exactly {sorted(TERMINAL_KEYS)}")
        else:
            if terminal["state"] != "INSUFFICIENT_EDGE":
                problems.append("recorded_terminal.state must be INSUFFICIENT_EDGE")
            for name in ("decision_ref", "recorded_at_utc"):
                if not isinstance(terminal[name], str) or terminal[name].strip() == "":
                    problems.append(f"recorded_terminal.{name} must be a non-empty string")
            families = terminal["families_at_record"]
            if not isinstance(families, list) or families != sorted(families):
                problems.append("recorded_terminal.families_at_record must be a sorted list")
    return problems


def registration_violations(doc: dict[str, Any], params_dir: Path) -> list[str]:
    """D-03 tripwire: under a recorded terminal state, params/ must not gain a family."""
    terminal = doc["recorded_terminal"]
    if terminal is None:
        return []
    present = sorted(child.name for child in params_dir.iterdir() if child.is_dir())
    recorded = list(terminal["families_at_record"])
    if present == recorded:
        return []
    added = sorted(set(present) - set(recorded))
    removed = sorted(set(recorded) - set(present))
    return [
        "D-03: strategy-family registration is blocked while the kill gate records "
        f"INSUFFICIENT_EDGE (decision {terminal['decision_ref']}); "
        f"new params/ directories: {added}; missing: {removed}. "
        "Clearing the terminal state needs an explicit human decision record."
    ]


def test_decision_record_is_valid_json_with_the_documented_schema() -> None:
    doc = _load()
    assert schema_violations(doc) == []
    assert doc["schema"] == SCHEMA_ID


def test_decision_record_avoids_parameter_set_identity_keys() -> None:
    """The research-gate registry-path tripwire scans repo JSON for these key names."""
    assert not (_all_keys(_load()) & FORBIDDEN_KEYS)
    assert "parameters" not in _all_keys(_load())


def test_committed_repo_state_passes_the_registration_tripwire() -> None:
    assert registration_violations(_load(), PARAMS_DIR) == []


def test_tripwire_is_vacuous_without_a_recorded_terminal(tmp_path: Path) -> None:
    (tmp_path / "family-a").mkdir()
    doc = {"schema": SCHEMA_ID, "families": [], "resets": [], "recorded_terminal": None}
    assert schema_violations(doc) == []
    assert registration_violations(doc, tmp_path) == []


def _terminal_doc(families: list[str]) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "families": [],
        "resets": [],
        "recorded_terminal": {
            "state": "INSUFFICIENT_EDGE",
            "decision_ref": "DEC-TEST-terminal",
            "recorded_at_utc": "2027-04-01T00:00:00+00:00",
            "families_at_record": families,
        },
    }


def test_tripwire_fires_when_a_family_directory_is_added_under_a_terminal_record(
    tmp_path: Path,
) -> None:
    for name in ("alpha", "beta"):
        (tmp_path / name).mkdir()
    doc = _terminal_doc(["alpha", "beta"])
    assert schema_violations(doc) == []
    assert registration_violations(doc, tmp_path) == []
    (tmp_path / "gamma").mkdir()
    violations = registration_violations(doc, tmp_path)
    assert len(violations) == 1
    assert "D-03" in violations[0]
    assert "gamma" in violations[0]


def test_tripwire_ignores_plain_files_and_flags_a_missing_directory(tmp_path: Path) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "README.md").write_text("not a family", encoding="utf-8")
    assert registration_violations(_terminal_doc(["alpha"]), tmp_path) == []
    violations = registration_violations(_terminal_doc(["alpha", "beta"]), tmp_path)
    assert violations and "beta" in violations[0]


def test_schema_violations_reject_malformed_records() -> None:
    assert schema_violations({"schema": SCHEMA_ID})
    bad_state = _terminal_doc(["a"])
    bad_state["recorded_terminal"]["state"] = "WITHIN_BUDGET"
    assert schema_violations(bad_state)
    unsorted = _terminal_doc(["b", "a"])
    assert schema_violations(unsorted)
    empty_ref = _terminal_doc(["a"])
    empty_ref["recorded_terminal"]["decision_ref"] = ""
    assert schema_violations(empty_ref)
    missing_keys = {
        "schema": SCHEMA_ID,
        "families": [{"family_id": "x"}],
        "resets": [{"operator_id": "o"}],
        "recorded_terminal": None,
    }
    assert len(schema_violations(missing_keys)) == 2


@pytest.mark.parametrize(
    ("state", "allowed"),
    [
        (KillGateState.INSUFFICIENT_EDGE, False),
        (KillGateState.WITHIN_BUDGET, True),
        (KillGateState.PASSING_CANDIDATE, True),
    ],
)
def test_registration_allowed_is_false_only_for_insufficient_edge(
    state: KillGateState, allowed: bool
) -> None:
    assert registration_allowed(state) is allowed
