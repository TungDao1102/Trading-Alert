"""DOMN-04 / D-20: legal-transition tables, enum parity and GLOSSARY parity (plan 17-03).

Plan 20-02 adds a seventh kind, PROTECTION (T-A, D-29): its table is copied from the
``ProtectionState`` docstring of ``src/execution/protection.py``. It is not persisted (no table,
no trigger) and its GLOSSARY section 11 block waits for the owner's acceptance of the D055
closure draft (19-OWNER-GAPS section 5), so it is exempt from the GLOSSARY parity tests below.
The enum parity of its keys lives in ``tests/test_protection_transitions.py`` because the
state enum is on the execution side and ``src/domain`` never imports ``src.execution``.
"""

from __future__ import annotations

import itertools
import re
from enum import Enum
from pathlib import Path

import pytest
from src.domain.enums import (
    ApprovalConsumptionStatus,
    ApprovalResult,
    ExecutionIntentStatus,
    LiveInputsStatus,
    OrderStatus,
    PositionStatus,
    SignalStatus,
    SystemStateKey,
    TradePlanStatus,
)
from src.domain.transitions import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    IllegalTransition,
    TransitionKind,
    assert_transition,
    is_legal,
)

GLOSSARY = Path(__file__).resolve().parents[1] / "docs" / "GLOSSARY.md"

ENUM_FOR_KIND: dict[TransitionKind, type[Enum]] = {
    TransitionKind.SIGNAL: SignalStatus,
    TransitionKind.TRADE_PLAN: TradePlanStatus,
    TransitionKind.ORDER: OrderStatus,
    TransitionKind.POSITION: PositionStatus,
    TransitionKind.APPROVAL: ApprovalResult,
    TransitionKind.EXECUTION_INTENT: ExecutionIntentStatus,
}

# The tables copied from the plan objective (research draft, verbatim). Independent of the
# implementation so a typo in either place fails the cross-check.
EXPECTED: dict[TransitionKind, dict[str, set[str]]] = {
    TransitionKind.SIGNAL: {
        "DETECTED": {"NOTIFIED", "SKIPPED_BUSY", "EXPIRED", "INVALIDATED"},
        "NOTIFIED": {
            "VIEWED",
            "APPROVED",
            "SKIPPED_USER",
            "SKIPPED_BUSY",
            "EXPIRED",
            "INVALIDATED",
        },
        "VIEWED": {"APPROVED", "SKIPPED_USER", "SKIPPED_BUSY", "EXPIRED", "INVALIDATED"},
        "APPROVED": set(),
        "SKIPPED_USER": set(),
        "SKIPPED_BUSY": set(),
        "EXPIRED": set(),
        "INVALIDATED": set(),
    },
    TransitionKind.TRADE_PLAN: {
        "READY": {"APPROVAL_PENDING", "EXPIRED", "INVALIDATED", "SUPERSEDED"},
        "APPROVAL_PENDING": {"APPROVED", "EXPIRED", "INVALIDATED", "SUPERSEDED"},
        "APPROVED": {"EXPIRED", "INVALIDATED"},
        "EXPIRED": set(),
        "INVALIDATED": set(),
        "SUPERSEDED": set(),
    },
    TransitionKind.ORDER: {
        "PLANNED": {"SUBMITTING", "CANCELED"},
        "SUBMITTING": {"NEW", "REJECTED", "UNKNOWN", "CANCELED"},
        "NEW": {"PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "REJECTED", "UNKNOWN"},
        "PARTIALLY_FILLED": {"FILLED", "CANCELED", "EXPIRED", "UNKNOWN"},
        "UNKNOWN": {"NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "REJECTED"},
        "FILLED": set(),
        "CANCELED": set(),
        "EXPIRED": set(),
        "REJECTED": set(),
    },
    TransitionKind.POSITION: {
        "OPEN": {"CLOSING", "CLOSED", "LIQUIDATION_REPORTED", "UNKNOWN"},
        "CLOSING": {"CLOSED", "OPEN", "UNKNOWN"},
        "LIQUIDATION_REPORTED": {"CLOSED", "UNKNOWN"},
        "UNKNOWN": {"OPEN", "CLOSING", "CLOSED", "LIQUIDATION_REPORTED"},
        "CLOSED": set(),
    },
    TransitionKind.APPROVAL: {
        "PENDING": {"APPROVED", "SKIPPED", "EXPIRED"},
        "APPROVED": set(),
        "SKIPPED": set(),
        "EXPIRED": set(),
    },
    TransitionKind.EXECUTION_INTENT: {
        "INTENDED": {"SENT", "UNKNOWN", "REJECTED"},
        "SENT": {"ACKED", "REJECTED", "UNKNOWN"},
        "UNKNOWN": {"ACKED", "REJECTED"},
        "ACKED": set(),
        "REJECTED": set(),
    },
    # Copied from the ProtectionState docstring (src/execution/protection.py), not from the table.
    TransitionKind.PROTECTION: {
        "AWAITING_FILL": {"UNPROTECTED", "ENTRY_ENDED_NO_FILL", "ENTRY_UNRESOLVED"},
        "ENTRY_UNRESOLVED": {"UNPROTECTED", "ENTRY_ENDED_NO_FILL", "AWAITING_FILL"},
        "UNPROTECTED": {"PROTECTED_ENTRY_OPEN", "PROTECTED", "CLOSE_REQUIRED", "FLAT"},
        "PROTECTED_ENTRY_OPEN": {"PROTECTED", "UNPROTECTED", "CLOSE_REQUIRED"},
        "PROTECTED": {"COMPLETE", "TP_UNAVAILABLE", "FLAT"},
        "COMPLETE": {"FLAT"},
        "TP_UNAVAILABLE": {"FLAT"},
        "CLOSE_REQUIRED": {"CLOSE_FAILED", "FLAT"},
        "CLOSE_FAILED": {"CLOSE_REQUIRED", "FLAT"},
        "FLAT": set(),
        "ENTRY_ENDED_NO_FILL": set(),
    },
}

EXPECTED_TERMINAL: dict[TransitionKind, set[str]] = {
    TransitionKind.SIGNAL: {"APPROVED", "SKIPPED_USER", "SKIPPED_BUSY", "EXPIRED", "INVALIDATED"},
    TransitionKind.TRADE_PLAN: {"EXPIRED", "INVALIDATED", "SUPERSEDED"},
    TransitionKind.ORDER: {"FILLED", "CANCELED", "EXPIRED", "REJECTED"},
    TransitionKind.POSITION: {"CLOSED"},
    TransitionKind.APPROVAL: {"APPROVED", "SKIPPED", "EXPIRED"},
    TransitionKind.EXECUTION_INTENT: {"ACKED", "REJECTED"},
    TransitionKind.PROTECTION: {"FLAT", "ENTRY_ENDED_NO_FILL"},
}

KINDS = list(TransitionKind)

# The kinds whose states are an enum of ``src.domain.enums`` (ENUM_FOR_KIND). PROTECTION is keyed
# by the ProtectionState values, an execution-side enum pinned by test_protection_transitions.py.
ENUM_KINDS = [kind for kind in KINDS if kind in ENUM_FOR_KIND]

# Kinds without a GLOSSARY section 11 block yet: 19-OWNER-GAPS section 5 says the ProtectionState
# block waits for the owner's acceptance of the D055 closure draft (O-01).
GLOSSARY_DEFERRED_KINDS = {TransitionKind.PROTECTION}
GLOSSARY_KINDS = [kind for kind in KINDS if kind not in GLOSSARY_DEFERRED_KINDS]


def _values(enum_cls: type[Enum]) -> set[str]:
    return {str(m.value) for m in enum_cls}


# --------------------------------------------------------------------------- tables


def _states_of(kind: TransitionKind) -> set[str]:
    """The state names of a machine: its enum values, or the table keys of PROTECTION."""
    if kind in ENUM_FOR_KIND:
        return _values(ENUM_FOR_KIND[kind])
    return set(EXPECTED[kind])


def test_seven_kinds_are_defined() -> None:
    assert set(ENUM_KINDS) | {TransitionKind.PROTECTION} == set(KINDS)
    assert len(KINDS) == 7
    assert set(LEGAL_TRANSITIONS) == set(KINDS)


@pytest.mark.parametrize("kind", ENUM_KINDS)
def test_every_enum_member_has_a_table_entry(kind: TransitionKind) -> None:
    """A new enum value cannot ship without a transition decision (D-20)."""
    assert set(LEGAL_TRANSITIONS[kind]) == _values(ENUM_FOR_KIND[kind])


@pytest.mark.parametrize("kind", KINDS)
def test_successors_are_members_of_the_machine(kind: TransitionKind) -> None:
    members = _states_of(kind)
    for old, successors in LEGAL_TRANSITIONS[kind].items():
        assert successors <= members, f"{kind} {old} -> {successors - members}"


@pytest.mark.parametrize("kind", KINDS)
def test_tables_match_the_plan_objective(kind: TransitionKind) -> None:
    actual = {old: set(new) for old, new in LEGAL_TRANSITIONS[kind].items()}
    assert actual == EXPECTED[kind]


@pytest.mark.parametrize("kind", KINDS)
def test_terminal_states_are_states_without_successors(kind: TransitionKind) -> None:
    derived = {old for old, new in LEGAL_TRANSITIONS[kind].items() if not new}
    assert set(TERMINAL_STATES[kind]) == derived
    assert set(TERMINAL_STATES[kind]) == EXPECTED_TERMINAL[kind]


def test_tables_are_read_only() -> None:
    with pytest.raises(TypeError):
        LEGAL_TRANSITIONS[TransitionKind.ORDER] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        LEGAL_TRANSITIONS[TransitionKind.ORDER]["FILLED"] = frozenset({"NEW"})  # type: ignore[index]


# --------------------------------------------------------------------------- assert_transition


def test_illegal_signal_expired_to_approved() -> None:
    with pytest.raises(IllegalTransition) as info:
        assert_transition(TransitionKind.SIGNAL, "EXPIRED", "APPROVED")
    assert info.value.kind is TransitionKind.SIGNAL
    assert info.value.old == "EXPIRED"
    assert info.value.new == "APPROVED"
    assert isinstance(info.value, ValueError)
    message = str(info.value)
    assert "SIGNAL" in message.upper() and "EXPIRED" in message and "APPROVED" in message


def test_illegal_order_filled_to_new() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(TransitionKind.ORDER, "FILLED", "NEW")


def test_illegal_position_closed_to_open() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(TransitionKind.POSITION, "CLOSED", "OPEN")


def test_unchanged_state_is_not_a_transition() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(TransitionKind.ORDER, "NEW", "NEW")
    assert is_legal(TransitionKind.ORDER, "NEW", "NEW") is False


def test_legal_transition_returns_none() -> None:
    assert assert_transition(TransitionKind.ORDER, "SUBMITTING", "NEW") is None


def test_enum_members_and_strings_are_both_accepted() -> None:
    assert assert_transition(TransitionKind.ORDER, OrderStatus.SUBMITTING, OrderStatus.NEW) is None
    assert assert_transition(TransitionKind.ORDER, OrderStatus.SUBMITTING, "NEW") is None
    assert assert_transition(TransitionKind.ORDER, "SUBMITTING", OrderStatus.NEW) is None
    with pytest.raises(IllegalTransition) as info:
        assert_transition(TransitionKind.ORDER, OrderStatus.FILLED, OrderStatus.NEW)
    assert info.value.old == "FILLED" and info.value.new == "NEW"


def test_unknown_states_raise() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(TransitionKind.ORDER, "BOGUS", "NEW")
    with pytest.raises(IllegalTransition):
        assert_transition(TransitionKind.ORDER, "NEW", "BOGUS")
    assert is_legal(TransitionKind.ORDER, "BOGUS", "NEW") is False


@pytest.mark.parametrize("kind", KINDS)
def test_exhaustive_cross_product(kind: TransitionKind) -> None:
    states = sorted(_states_of(kind))
    for old, new in itertools.product(states, states):
        legal = new in EXPECTED[kind][old]
        assert is_legal(kind, old, new) is legal, (kind, old, new)
        if legal:
            assert_transition(kind, old, new)
        else:
            with pytest.raises(IllegalTransition) as info:
                assert_transition(kind, old, new)
            assert (info.value.kind, info.value.old, info.value.new) == (kind, old, new)


# --------------------------------------------------------------------------- GLOSSARY parsing

_SUBSECTION = re.compile(r"^### (\d+)\.(\d+) ([^\n]*)\n", re.MULTILINE)
_TEXT_BLOCK = re.compile(r"```text\n(.*?)```", re.DOTALL)


def _glossary_section(number: int) -> str:
    text = GLOSSARY.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(rf"^## {number}\.[^\n]*\n", text, flags=re.MULTILINE)
    assert match is not None, f"GLOSSARY section {number} is missing"
    rest = text[match.end() :]
    nxt = re.search(r"^## \d+\.", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _subsections(section: str, number: int) -> dict[str, str]:
    """Map the heading title of each ``### N.M Title`` subsection to its body."""
    matches = [m for m in _SUBSECTION.finditer(section) if int(m.group(1)) == number]
    out: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        out[f"{match.group(1)}.{match.group(2)} {match.group(3).strip()}"] = section[
            match.end() : end
        ]
    return out


def _first_block_lines(body: str) -> list[str]:
    match = _TEXT_BLOCK.search(body)
    assert match is not None, "no ```text block in subsection"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def _parse_transition_block(lines: list[str]) -> dict[str, set[str]]:
    table: dict[str, set[str]] = {}
    for line in lines:
        head, arrow, tail = line.partition("->")
        assert arrow, f"not a 'FROM -> TO' line: {line!r}"
        old = head.strip()
        assert old not in table, f"duplicate row for {old}"
        tail = tail.strip()
        table[old] = set() if tail == "(terminal)" else {token.strip() for token in tail.split(",")}
    return table


SECTION_11_TITLES: dict[TransitionKind, str] = {
    TransitionKind.SIGNAL: "11.1 Signal transitions",
    TransitionKind.TRADE_PLAN: "11.2 TradePlan transitions",
    TransitionKind.ORDER: "11.3 Order transitions",
    TransitionKind.POSITION: "11.4 Position transitions",
    TransitionKind.APPROVAL: "11.5 Approval transitions",
    TransitionKind.EXECUTION_INTENT: "11.6 ExecutionIntent transitions",
}


def test_glossary_section_11_has_the_six_subsections() -> None:
    subsections = _subsections(_glossary_section(11), 11)
    assert list(subsections) == [SECTION_11_TITLES[kind] for kind in GLOSSARY_KINDS]


@pytest.mark.parametrize("kind", GLOSSARY_KINDS)
def test_glossary_section_11_matches_the_python_tables(kind: TransitionKind) -> None:
    subsections = _subsections(_glossary_section(11), 11)
    parsed = _parse_transition_block(_first_block_lines(subsections[SECTION_11_TITLES[kind]]))
    actual = {old: set(new) for old, new in LEGAL_TRANSITIONS[kind].items()}
    assert parsed == actual


def test_glossary_section_11_records_the_auto_mode_default_status() -> None:
    text = _glossary_section(11)
    assert "auto-mode default" in text
    assert "D051" in text


# --------------------------------------------------------------------------- section 12

SECTION_12: dict[str, type[Enum]] = {
    "12.1 ExecutionIntentStatus": ExecutionIntentStatus,
    "12.2 ApprovalConsumptionStatus": ApprovalConsumptionStatus,
    "12.3 LiveInputsStatus": LiveInputsStatus,
    "12.4 SystemStateKey": SystemStateKey,
}


def test_glossary_section_12_has_the_four_subsections() -> None:
    subsections = _subsections(_glossary_section(12), 12)
    assert list(subsections) == list(SECTION_12)


@pytest.mark.parametrize("title", list(SECTION_12))
def test_glossary_section_12_block_equals_the_enum(title: str) -> None:
    subsections = _subsections(_glossary_section(12), 12)
    lines = _first_block_lines(subsections[title])
    assert len(lines) == len(set(lines)), "duplicate tokens in block"
    assert set(lines) == _values(SECTION_12[title])
