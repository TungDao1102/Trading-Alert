"""Algo-order status classification tests (Phase 18, plan 18-06).

CONTEXT D-07 and G2-028: every `ALGO_UPDATE` status `X` has exactly one
class (ACTIVE, TERMINAL_OK, TERMINAL_FAILED or UNKNOWN); an unseen value
is UNKNOWN and never ACTIVE. Only ACTIVE confirms protection, and the
attach path of `src/execution/manager.py` asks `is_protection_confirmed`
instead of the removed one-element allow-list.

The classes of TRIGGERING, TRIGGERED, FINISHED and CANCELED are the
owner's recorded decision (`decisions/18-DEC-O-18-01.md`, 2026-10-16).
`test_algo_status_table_matches_decision_record` parses that record, and
`test_algo_status_table_as_recorded_2026_10_16` pins the same table
literally, so a change of the record or of the table fails both tests
until a new record and a reviewed table change land together.
"""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from typing import Any

import pytest
from src.domain.algo_status import (
    ALGO_STATUS_TABLE,
    ALGO_STATUS_VOCABULARY,
    AlgoStatusClass,
    AlgoStatusEntry,
    classify_algo_status,
    is_protection_confirmed,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DECISION_RECORD = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "18-user-data-stream-error-taxonomy"
    / "decisions"
    / "18-DEC-O-18-01.md"
)
MANAGER_PATH = REPO_ROOT / "src" / "execution" / "manager.py"

# The documented defaults for the statuses the record does not classify
# (record text: "NEW is ACTIVE, REJECTED and EXPIRED are TERMINAL_FAILED").
_DOCUMENTED_DEFAULTS: dict[str, AlgoStatusClass] = {
    "NEW": AlgoStatusClass.ACTIVE,
    "REJECTED": AlgoStatusClass.TERMINAL_FAILED,
    "EXPIRED": AlgoStatusClass.TERMINAL_FAILED,
}

# The six statuses that must never be ACTIVE (EXECUTION_SPEC 6.1, D055
# invariant 2: a status that is no longer a resting stop is not protection).
_NEVER_ACTIVE = ("TRIGGERING", "TRIGGERED", "FINISHED", "CANCELED", "REJECTED", "EXPIRED")

_UNSEEN_VALUES: tuple[object, ...] = (
    None,
    "",
    "new",
    " NEW",
    "NEW ",
    7,
    b"NEW",
    "SOMETHING_ELSE",
)

_SEVEN = tuple(sorted(ALGO_STATUS_VOCABULARY))


def _record_classes() -> dict[str, str]:
    """Parse the `class <STATUS>: <CLASS>` lines of the decision record."""
    text = DECISION_RECORD.read_text(encoding="utf-8")
    pattern = re.compile(r"^class ([A-Z_]+): ([A-Z_]+)\s*$", flags=re.MULTILINE)
    classes: dict[str, str] = {}
    for status, klass in pattern.findall(text):
        assert status not in classes, f"status {status} is classified twice in the record"
        classes[status] = klass
    return classes


# --------------------------------------------------------------------------- #
# The table itself.
# --------------------------------------------------------------------------- #


def test_table_keys_equal_the_vocabulary() -> None:
    assert frozenset(ALGO_STATUS_TABLE) == ALGO_STATUS_VOCABULARY
    assert len(ALGO_STATUS_TABLE) == 7


def test_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        ALGO_STATUS_TABLE["NEW"] = ALGO_STATUS_TABLE["CANCELED"]  # type: ignore[index]


@pytest.mark.parametrize("status", _SEVEN)
def test_each_entry_is_complete_and_frozen(status: str) -> None:
    entry = ALGO_STATUS_TABLE[status]
    assert isinstance(entry, AlgoStatusEntry)
    assert entry.status == status
    assert isinstance(entry.klass, AlgoStatusClass)
    assert entry.meaning.strip() != ""
    assert entry.source_note.strip() != ""
    with pytest.raises(AttributeError):
        entry.klass = AlgoStatusClass.ACTIVE  # type: ignore[misc]


def test_class_vocabulary_is_the_four_d07_classes() -> None:
    assert [c.value for c in AlgoStatusClass] == [
        "ACTIVE",
        "TERMINAL_OK",
        "TERMINAL_FAILED",
        "UNKNOWN",
    ]


@pytest.mark.parametrize("status", _SEVEN)
def test_classify_returns_the_table_class_for_every_status(status: str) -> None:
    assert classify_algo_status(status) is ALGO_STATUS_TABLE[status].klass


@pytest.mark.parametrize("value", _UNSEEN_VALUES, ids=repr)
def test_unseen_empty_none_non_string_and_wrong_case_are_unknown(value: object) -> None:
    assert classify_algo_status(value) is AlgoStatusClass.UNKNOWN
    assert is_protection_confirmed(value) is False


@pytest.mark.parametrize("value", (*_SEVEN, *_UNSEEN_VALUES), ids=repr)
def test_protection_confirmed_if_and_only_if_active(value: object) -> None:
    assert is_protection_confirmed(value) is (classify_algo_status(value) is AlgoStatusClass.ACTIVE)


# --------------------------------------------------------------------------- #
# The table equals the owner's record (T-18-17).
# --------------------------------------------------------------------------- #


def test_algo_status_table_matches_decision_record() -> None:
    recorded = _record_classes()
    assert set(recorded) <= ALGO_STATUS_VOCABULARY, f"unknown status in record: {recorded}"
    allowed = {c.value for c in AlgoStatusClass}
    for status, klass in recorded.items():
        assert klass in allowed, f"record class {klass!r} for {status} is not a D-07 class"
    for status in _NEVER_ACTIVE:
        assert recorded.get(status) != "ACTIVE", (
            f"the record classifies {status} as ACTIVE: stop rule of plan 18-06"
        )
    for status in _SEVEN:
        expected = recorded.get(status, _DOCUMENTED_DEFAULTS.get(status))
        assert expected is not None, f"{status} has neither a record line nor a default"
        assert classify_algo_status(status).value == expected, status


def test_algo_status_table_as_recorded_2026_10_16() -> None:
    table = {status: entry.klass.value for status, entry in ALGO_STATUS_TABLE.items()}
    assert table == {
        "NEW": "ACTIVE",
        "TRIGGERING": "UNKNOWN",
        "TRIGGERED": "UNKNOWN",
        "FINISHED": "UNKNOWN",
        "CANCELED": "UNKNOWN",
        "REJECTED": "TERMINAL_FAILED",
        "EXPIRED": "TERMINAL_FAILED",
    }
    assert {s for s in _SEVEN if is_protection_confirmed(s)} == {"NEW"}
    assert all(e.klass is not AlgoStatusClass.TERMINAL_OK for e in ALGO_STATUS_TABLE.values())


# --------------------------------------------------------------------------- #
# Manager wiring: attach confirmation and existing-leg adoption.
# --------------------------------------------------------------------------- #

_PLAN_HASH = "194547b9a1659419ecfa4a736a3dece35ba6eb8515e559561f2d23cc130d8e1c"


class _LegAdapter:
    """Probe and placement fake for `_place_protective_leg`."""

    def __init__(self, *, existing: object = None, found: bool, placed: object = None) -> None:
        self._existing = existing
        self._found = found
        self._placed = placed
        self.place_calls = 0

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any:
        return {"found": self._found, "algo_status": self._existing}

    async def place_algo_protective(self, **kwargs: Any) -> Any:
        self.place_calls += 1
        return {"algo_status": self._placed}


def _leg(adapter: _LegAdapter) -> tuple[bool, str | None]:
    from src.execution.manager import _place_protective_leg

    return asyncio.run(
        _place_protective_leg(
            adapter=adapter,  # type: ignore[arg-type]
            symbol="BTCUSDT",
            plan_hash=_PLAN_HASH,
            role="STOP_LOSS",
            leg={},
        )
    )


@pytest.mark.parametrize("status", (*_SEVEN, *_UNSEEN_VALUES), ids=repr)
def test_placement_response_confirms_only_protection_confirmed_status(status: object) -> None:
    adapter = _LegAdapter(found=False, placed=status)
    confirmed, detail = _leg(adapter)
    assert adapter.place_calls == 1
    assert confirmed is is_protection_confirmed(status)
    assert detail is None


@pytest.mark.parametrize("status", (*_SEVEN, *_UNSEEN_VALUES), ids=repr)
def test_existing_leg_adopted_only_when_protection_confirmed(status: object) -> None:
    adapter = _LegAdapter(existing=status, found=True)
    confirmed, detail = _leg(adapter)
    assert adapter.place_calls == 0, "an existing leg is never re-placed"
    if is_protection_confirmed(status):
        assert (confirmed, detail) == (True, None)
    else:
        assert (confirmed, detail) == (False, f"STOP_LOSS: existing leg status {status!r}")


@pytest.mark.parametrize("status", (*_SEVEN, *_UNSEEN_VALUES), ids=repr)
def test_attach_behavior_unchanged_from_new_only_allow_list(status: object) -> None:
    """With the recorded table, confirmation equals the removed `{"NEW"}` allow-list."""
    from src.execution.manager import _is_leg_confirmed

    old_allow_list = status == "NEW"
    assert _is_leg_confirmed({"algo_status": status}) is old_allow_list
    placed, _ = _leg(_LegAdapter(found=False, placed=status))
    assert placed is old_allow_list
    adopted, _ = _leg(_LegAdapter(existing=status, found=True))
    assert adopted is old_allow_list


def test_manager_imports_is_protection_confirmed_from_the_domain_module() -> None:
    tree = ast.parse(MANAGER_PATH.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "src.domain.algo_status"
        for alias in node.names
    }
    assert "is_protection_confirmed" in imported
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "is_protection_confirmed"
    ]
    assert len(calls) >= 2, "attach confirmation and adoption must both use the table"


def test_removed_allow_list_constant_is_gone_and_imported_nowhere() -> None:
    name = "_ACTIVE_ALGO_STATUSES"
    manager_tree = ast.parse(MANAGER_PATH.read_text(encoding="utf-8"))
    assigned = {
        target.id
        for node in manager_tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    }
    assert name not in assigned
    for root in ("src", "scripts", "tests"):
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert name not in {a.name for a in node.names}, path
                if isinstance(node, ast.Attribute):
                    assert node.attr != name, path
