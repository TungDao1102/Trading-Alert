"""The protection transition guard (plan 20-02; T-A, D-29, D077).

``ProtectionCoordinator._transition`` consults the PROTECTION table of
``src/domain/transitions.py`` (built from the ``ProtectionState`` docstring) and never assigns a
state the table does not allow. Every test runs offline against the stateful Phase 19 fake
exchange, the real ``MarketEmergencyCloser`` where a close is needed, and virtual time.

Evidence label: executed unit tests with fakes. Nothing here is a Binance Demo observation (no
[DEMO] claim), and general stale-event detection is NOT claimed: Phase 20 has no exchange
event-time column, so the guard detects only what ordering and deduplication evidence it has
(D-29, the rest is deferred to Phase 24).
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import src.execution.protection_replay as replay
from src.domain.transitions import LEGAL_TRANSITIONS, TransitionKind, is_legal
from src.execution.protection import ProtectionState

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal

EVENT_TRANSITION = "PROTECTION_TRANSITION"
EVENT_REJECTED = "PROTECTION_TRANSITION_REJECTED"
SAFE_MODE_INVALID = "PROTECTION_STATE_INVALID"


def _tracked(rig: ProtectionRig) -> Any:
    return rig.coordinator._tracked[TEST_ONLY_PLAN_HASH]  # noqa: SLF001 - the guard under test


def _rows(rig: ProtectionRig, event_type: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in rig.journal.calls if e.event_type == event_type]


# --------------------------------------------------------------------------- #
# Tracer: the table and the guard, end to end through the real coordinator.
# --------------------------------------------------------------------------- #


def test_the_protection_table_keys_are_exactly_the_protection_state_names() -> None:
    from src.domain.transitions import PROTECTION_INITIAL_STATE

    assert set(LEGAL_TRANSITIONS[TransitionKind.PROTECTION]) == {s.value for s in ProtectionState}
    assert PROTECTION_INITIAL_STATE == ProtectionState.AWAITING_FILL.value


def test_the_table_allows_close_required_only_to_close_failed_or_flat() -> None:
    assert is_legal(TransitionKind.PROTECTION, "CLOSE_REQUIRED", "PROTECTED") is False
    assert is_legal(TransitionKind.PROTECTION, "CLOSE_REQUIRED", "CLOSE_FAILED") is True
    assert LEGAL_TRANSITIONS[TransitionKind.PROTECTION]["CLOSE_REQUIRED"] == {
        "CLOSE_FAILED",
        "FLAT",
    }


def test_an_operator_close_may_enter_close_required_from_every_state_with_a_position() -> None:
    """Plan 20-17 (D-26): the OPERATOR_CLOSE edges. A finished plan has none."""
    for state in (
        "AWAITING_FILL",
        "ENTRY_UNRESOLVED",
        "UNPROTECTED",
        "PROTECTED_ENTRY_OPEN",
        "PROTECTED",
        "COMPLETE",
        "TP_UNAVAILABLE",
    ):
        assert is_legal(TransitionKind.PROTECTION, state, "CLOSE_REQUIRED") is True, state
    for state in ("FLAT", "ENTRY_ENDED_NO_FILL"):
        assert is_legal(TransitionKind.PROTECTION, state, "CLOSE_REQUIRED") is False, state


async def test_close_required_never_downgrades_to_protected() -> None:
    rig = await make_rig(real_closer=True)
    rig.fake.reject_next_algo(-2021)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # B5: the stop is rejected definitively, CLOSE_REQUIRED
    tracked = _tracked(rig)
    assert tracked.state is ProtectionState.CLOSE_REQUIRED
    seq_before = tracked.seq
    reason_before = tracked.last_reason
    transitions_before = len(_rows(rig, EVENT_TRANSITION))
    assert _rows(rig, EVENT_REJECTED) == []

    accepted = rig.coordinator._transition(  # noqa: SLF001 - the guard under test
        tracked, ProtectionState.PROTECTED, "LATE_STOP_CONFIRMED", rig.clock.now()
    )

    assert accepted is False
    assert tracked.state is ProtectionState.CLOSE_REQUIRED
    assert tracked.seq == seq_before
    assert tracked.last_reason == reason_before
    assert len(_rows(rig, EVENT_TRANSITION)) == transitions_before
    rejected = _rows(rig, EVENT_REJECTED)
    assert len(rejected) == 1
    assert rejected[0]["from"] == "CLOSE_REQUIRED"
    assert rejected[0]["to"] == "PROTECTED"
    assert rejected[0]["seq"] == seq_before
    assert rejected[0]["reason"] == "LATE_STOP_CONFIRMED"
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED", SAFE_MODE_INVALID]
    assert rig.coordinator.blocks_new_entries() is True


# --------------------------------------------------------------------------- #
# Task 2: clearing rules with evidence (D077, D-06, D-09), stale and duplicate events.
# --------------------------------------------------------------------------- #

# The evidence names are pinned as literals here, independent of the implementation (T-A).
EVIDENCE_STOP = "REST_STOP_CONFIRMED"
EVIDENCE_FLAT = "REST_FLAT_TWO_READS_ENTRY_TERMINAL"

# The TEST_ONLY deadline of tests/support/execution_limits.py, in milliseconds.
ENTRY_TERMINAL_TIMEOUT_MS = 13333


def _fill(rig: ProtectionRig, quantity: str = "0.004") -> Any:
    """The exchange fills the entry; the stream view of the fill is queued and returned."""
    routed = rig.stream_fill(D(quantity))
    rig.coordinator.fill_sink(routed)
    return routed


def _script_failures(rig: ProtectionRig, method: str, count: int) -> None:
    for _ in range(count):
        rig.fake.fail_next(method, RuntimeError("scripted ambiguous failure"))


async def _unprotected_after_first_fill(rig: ProtectionRig) -> Any:
    """First fill 0.004: the stop is placed, REST has not confirmed it yet (UNPROTECTED)."""
    rig.first_fill_event = _fill(rig)  # type: ignore[attr-defined]
    await rig.coordinator.step()
    tracked = _tracked(rig)
    assert tracked.state is ProtectionState.UNPROTECTED
    return tracked


async def _protected_entry_open(rig: ProtectionRig) -> Any:
    """First fill, the stop confirmed ACTIVE by REST, the entry still open."""
    _script_failures(rig, "cancel_normal_order", 2)
    _fill(rig)
    await rig.coordinator.step()
    await rig.coordinator.step()
    tracked = _tracked(rig)
    assert tracked.state is ProtectionState.PROTECTED_ENTRY_OPEN
    return tracked


async def _close_required(rig: ProtectionRig) -> Any:
    rig.fake.reject_next_algo(-2021)
    _fill(rig)
    await rig.coordinator.step()
    tracked = _tracked(rig)
    assert tracked.state is ProtectionState.CLOSE_REQUIRED
    return tracked


async def _close_failed(rig: ProtectionRig) -> Any:
    rig.fake.reject_next_algo(-2021)
    _fill(rig)
    await rig.coordinator.step()
    tracked = _tracked(rig)
    assert tracked.state is ProtectionState.CLOSE_FAILED
    return tracked


def _assert_refused(tracked: Any, *, before_state: ProtectionState, before_seq: int) -> None:
    assert tracked.state is before_state
    assert tracked.seq == before_seq


def _rejections(rig: ProtectionRig) -> list[str]:
    return [str(row["rejection"]) for row in _rows(rig, EVENT_REJECTED)]


async def test_unprotected_first_fill_clears_only_with_rest_stop_evidence() -> None:
    for bad_evidence in (None, EVIDENCE_FLAT, "ANYTHING"):
        rig = await make_rig(real_closer=True)
        tracked = await _unprotected_after_first_fill(rig)
        seq = tracked.seq
        accepted = rig.coordinator._transition(  # noqa: SLF001
            tracked,
            ProtectionState.PROTECTED_ENTRY_OPEN,
            "X",
            rig.clock.now(),
            evidence=bad_evidence,
        )
        assert accepted is False, bad_evidence
        _assert_refused(tracked, before_state=ProtectionState.UNPROTECTED, before_seq=seq)
        assert _rejections(rig) == ["EVIDENCE_MISSING"]
        assert SAFE_MODE_INVALID in rig.safe_mode.entered_reasons

    rig = await make_rig(real_closer=True)
    tracked = await _unprotected_after_first_fill(rig)
    accepted = rig.coordinator._transition(  # noqa: SLF001
        tracked,
        ProtectionState.PROTECTED_ENTRY_OPEN,
        "X",
        rig.clock.now(),
        evidence=EVIDENCE_STOP,
    )
    assert accepted is True
    assert tracked.state is ProtectionState.PROTECTED_ENTRY_OPEN
    assert _rows(rig, EVENT_TRANSITION)[-1]["evidence"] == EVIDENCE_STOP
    assert _rows(rig, EVENT_REJECTED) == []


async def test_stop_lost_unprotected_cannot_clear_to_protected_even_with_stop_evidence() -> None:
    for target in (ProtectionState.PROTECTED_ENTRY_OPEN, ProtectionState.PROTECTED):
        rig = await make_rig(real_closer=True)
        await _protected_entry_open(rig)
        rig.fake.trigger_stop(rig.stop_id)
        _script_failures(rig, "snapshot_positions", 500)  # the position is never readable
        await rig.coordinator.step()
        tracked = _tracked(rig)
        assert tracked.state is ProtectionState.UNPROTECTED
        assert tracked.stop_lost_at is not None
        seq = tracked.seq

        accepted = rig.coordinator._transition(  # noqa: SLF001
            tracked, target, "STOP_READS_ACTIVE_AGAIN", rig.clock.now(), evidence=EVIDENCE_STOP
        )

        assert accepted is False, target
        _assert_refused(tracked, before_state=ProtectionState.UNPROTECTED, before_seq=seq)
        assert _rejections(rig) == ["STOP_LOST_CLEARED"]
        assert rig.coordinator.blocks_new_entries() is True


async def test_flat_from_a_blocking_state_needs_the_flat_evidence() -> None:
    builders: dict[ProtectionState, tuple[dict[str, Any], Any]] = {
        ProtectionState.UNPROTECTED: ({"real_closer": True}, _unprotected_after_first_fill),
        ProtectionState.CLOSE_REQUIRED: ({"real_closer": True}, _close_required),
        ProtectionState.CLOSE_FAILED: ({"closer_results": [False]}, _close_failed),
    }
    for start, (rig_args, drive) in builders.items():
        for bad_evidence in (None, EVIDENCE_STOP):
            rig = await make_rig(**rig_args)
            tracked = await drive(rig)
            seq = tracked.seq
            accepted = rig.coordinator._transition(  # noqa: SLF001
                tracked, ProtectionState.FLAT, "X", rig.clock.now(), evidence=bad_evidence
            )
            assert accepted is False, (start, bad_evidence)
            _assert_refused(tracked, before_state=start, before_seq=seq)
            assert _rejections(rig) == ["EVIDENCE_MISSING"], (start, bad_evidence)
            assert rig.coordinator.blocks_new_entries() is True

        rig = await make_rig(**rig_args)
        tracked = await drive(rig)
        accepted = rig.coordinator._transition(  # noqa: SLF001
            tracked, ProtectionState.FLAT, "X", rig.clock.now(), evidence=EVIDENCE_FLAT
        )
        assert accepted is True, start
        assert tracked.state is ProtectionState.FLAT
        assert _rows(rig, EVENT_TRANSITION)[-1]["evidence"] == EVIDENCE_FLAT


async def test_every_flat_transition_of_a_real_run_carries_the_flat_evidence() -> None:
    # B5 -> CLOSE_REQUIRED -> close -> FLAT (CLOSED_ENTRY_TERMINAL).
    rig = await make_rig(real_closer=True)
    await _close_required(rig)
    await rig.coordinator.step()
    assert _tracked(rig).state is ProtectionState.FLAT
    flat_rows = [r for r in _rows(rig, EVENT_TRANSITION) if r["to"] == "FLAT"]
    assert [r["reason"] for r in flat_rows] == ["CLOSED_ENTRY_TERMINAL"]
    assert [r["evidence"] for r in flat_rows] == [EVIDENCE_FLAT]
    # Every row has the evidence key; a move that clears nothing carries null.
    assert all("evidence" in r for r in _rows(rig, EVENT_TRANSITION))
    assert _rows(rig, EVENT_TRANSITION)[0]["evidence"] is None


async def test_a_lost_stop_that_ends_flat_from_protected_entry_open_is_a_legal_edge() -> None:
    """Audit finding: the module docstring ends a lost stop FLAT on two zero reads (STOP_CONSUMED).

    When the entry turns terminal on the same step, the plan goes PROTECTED_ENTRY_OPEN -> FLAT
    without parking in UNPROTECTED; the ProtectionState docstring and the table now say so.
    """
    rig = await make_rig(real_closer=True)
    await _protected_entry_open(rig)
    await rig.coordinator.step()  # the remainder cancel goes through (entry read before it)
    rig.fake.trigger_stop(rig.stop_id)  # the stop flattened the position

    await rig.coordinator.step()  # entry terminal, stop lost, two zero reads

    assert _tracked(rig).state is ProtectionState.FLAT
    last = _rows(rig, EVENT_TRANSITION)[-1]
    assert (last["from"], last["to"], last["reason"]) == (
        "PROTECTED_ENTRY_OPEN",
        "FLAT",
        "STOP_CONSUMED_FLAT",
    )
    assert last["evidence"] == EVIDENCE_FLAT
    assert _rows(rig, EVENT_REJECTED) == []
    assert rig.safe_mode.entered_reasons == []


async def test_stale_active_stop_after_close_required_never_downgrades() -> None:
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "cancel_normal_order", 5)
    first_fill = _fill(rig)
    await rig.coordinator.step()
    await rig.coordinator.step()  # the stop is confirmed ACTIVE, the entry is still open
    await rig.clock.advance(ENTRY_TERMINAL_TIMEOUT_MS / 1000)
    await rig.coordinator.step()  # B1: CLOSE_REQUIRED while the good stop is still on the book
    tracked = _tracked(rig)
    assert tracked.state is ProtectionState.CLOSE_REQUIRED
    assert tracked.stop_confirmed_at is not None
    assert rig.stop_id in rig.fake.open_algos
    seq = tracked.seq

    # A late REST answer reads the stop ACTIVE again and the entry terminal: the settle path of
    # the supervision step is asked to move the plan to PROTECTED. It is refused.
    tracked.entry_terminal_at = rig.clock.now()
    rig.coordinator._settle_state(tracked)  # noqa: SLF001
    assert tracked.state is ProtectionState.CLOSE_REQUIRED
    assert tracked.seq == seq
    assert [r["to"] for r in _rows(rig, EVENT_REJECTED)] == ["PROTECTED"]

    # A queued duplicate fill is ignored; the plan only ever goes to CLOSE_* / FLAT from here.
    rig.coordinator.fill_sink(first_fill)
    for _ in range(3):
        await rig.coordinator.step()
    after = [r["to"] for r in _rows(rig, EVENT_TRANSITION) if r["seq"] > seq]
    assert after, "the plan must have moved on (CLOSE_* / FLAT)"
    assert set(after) <= {"CLOSE_REQUIRED", "CLOSE_FAILED", "FLAT"}
    assert len(rig.fake.calls_to("place_algo_protective")) == 1


async def test_a_duplicate_fill_after_unprotected_is_a_no_op() -> None:
    rig = await make_rig(real_closer=True)
    await _unprotected_after_first_fill(rig)
    rig.coordinator.fill_sink(rig.first_fill_event)  # type: ignore[attr-defined]  # a repeat
    await rig.coordinator.step()
    first_fill_rows = [
        r
        for r in _rows(rig, EVENT_TRANSITION)
        if (r["from"], r["to"]) == ("AWAITING_FILL", "UNPROTECTED")
    ]
    assert len(first_fill_rows) == 1
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    assert _rows(rig, EVENT_REJECTED) == []


async def test_a_repeated_request_for_the_current_state_writes_nothing() -> None:
    rig = await make_rig(real_closer=True)
    tracked = await _unprotected_after_first_fill(rig)
    seq = tracked.seq
    reason = tracked.last_reason
    rows = len(rig.journal.calls)

    accepted = rig.coordinator._transition(  # noqa: SLF001
        tracked, ProtectionState.UNPROTECTED, "AGAIN", rig.clock.now()
    )

    assert accepted is True
    assert tracked.seq == seq
    assert tracked.last_reason == reason
    assert len(rig.journal.calls) == rows
    assert rig.safe_mode.entered_reasons == []


# --------------------------------------------------------------------------- #
# AST guards: one assignment point, evidence passed where the code holds it.
# --------------------------------------------------------------------------- #

_PROTECTION_SOURCE = Path(__file__).resolve().parents[1] / "src" / "execution" / "protection.py"


def _parsed() -> ast.Module:
    return ast.parse(_PROTECTION_SOURCE.read_text(encoding="utf-8"))


def _state_assignments() -> list[tuple[str, str, int]]:
    """(class, function, line) of every assignment whose target is an attribute named ``state``."""
    found: list[tuple[str, str, int]] = []
    for cls in (n for n in ast.walk(_parsed()) if isinstance(n, ast.ClassDef)):
        for func in (
            n for n in ast.walk(cls) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        ):
            for node in ast.walk(func):
                targets: list[ast.expr] = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                elif isinstance(node, ast.AnnAssign | ast.AugAssign):
                    targets = [node.target]
                for target in targets:
                    if isinstance(target, ast.Attribute) and target.attr == "state":
                        found.append((cls.name, func.name, node.lineno))
    return found


def test_no_code_path_assigns_state_outside_transition() -> None:
    allowed = {("_Tracked", "__init__"), ("ProtectionCoordinator", "_transition")}
    assignments = _state_assignments()
    assert assignments, "the AST walk must see the two known assignments"
    assert {(c, f) for c, f, _ in assignments} <= allowed, assignments
    tree = _parsed()
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert {"setattr", "__setattr__"}.isdisjoint(names)


def _transition_calls() -> list[ast.Call]:
    return [
        node
        for node in ast.walk(_parsed())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_transition"
    ]


def _target_state(call: ast.Call) -> str:
    node = call.args[1]
    assert isinstance(node, ast.Attribute)
    return node.attr


def test_every_move_to_flat_and_every_settle_move_passes_its_evidence() -> None:
    calls = _transition_calls()
    flat = [c for c in calls if _target_state(c) == "FLAT"]
    settle = [c for c in calls if _target_state(c) in {"PROTECTED", "PROTECTED_ENTRY_OPEN"}]
    assert len(flat) >= 5 and len(settle) >= 2, (len(flat), len(settle))
    for call in flat:
        assert [k.arg for k in call.keywords] == ["evidence"], call.lineno
        value = call.keywords[0].value
        assert isinstance(value, ast.Name), call.lineno
        assert value.id == "EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL", call.lineno
    for call in settle:
        value = call.keywords[0].value if call.keywords else None
        assert isinstance(value, ast.Name), call.lineno
        assert value.id == "EVIDENCE_REST_STOP_CONFIRMED", call.lineno


def test_the_evidence_names_are_the_pinned_literals() -> None:
    from src.execution.protection import (
        EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL,
        EVIDENCE_REST_STOP_CONFIRMED,
    )

    assert EVIDENCE_REST_STOP_CONFIRMED == EVIDENCE_STOP
    assert EVIDENCE_REST_FLAT_TWO_READS_ENTRY_TERMINAL == EVIDENCE_FLAT


# --------------------------------------------------------------------------- #
# Task 3: replay_transitions - a valid history passes the same guard, a corrupt one fails closed.
# --------------------------------------------------------------------------- #


HAPPY_CHAIN = [
    ("NONE", "AWAITING_FILL"),
    ("AWAITING_FILL", "UNPROTECTED"),
    ("UNPROTECTED", "PROTECTED_ENTRY_OPEN"),
    ("PROTECTED_ENTRY_OPEN", "PROTECTED"),
    ("PROTECTED", "FLAT"),
]


async def _valid_history() -> list[dict[str, Any]]:
    """The journaled payloads of a real run: registered, filled, protected, stopped out, flat."""
    rig = await make_rig(real_closer=True)
    await _protected_entry_open(rig)
    await rig.coordinator.step()  # the remainder cancel goes through
    await rig.coordinator.step()  # entry terminal, stop ACTIVE: PROTECTED
    assert _tracked(rig).state is ProtectionState.PROTECTED
    rig.fake.trigger_stop(rig.stop_id)  # the stop closed the position
    await rig.coordinator.step()  # PROTECTED: two zero reads, FLAT
    assert _tracked(rig).state is ProtectionState.FLAT
    rows = _rows(rig, EVENT_TRANSITION)
    assert [(r["from"], r["to"]) for r in rows] == HAPPY_CHAIN
    return rows


def _invalid(rows: list[dict[str, Any]], code: str) -> None:
    with pytest.raises(replay.ProtectionReplayInvalid) as caught:
        replay.replay_transitions(rows, plan_hash=TEST_ONLY_PLAN_HASH)
    assert caught.value.reason == code
    assert isinstance(caught.value, ValueError)
    # The error carries a fixed code only, never row text.
    assert str(caught.value) == code
    assert "BTCUSDT" not in str(caught.value)


async def test_a_real_run_replays_to_its_last_state() -> None:
    rows = await _valid_history()

    result = replay.replay_transitions(rows, plan_hash=TEST_ONLY_PLAN_HASH)

    assert result.plan_hash == TEST_ONLY_PLAN_HASH
    assert result.state == "FLAT"
    assert result.seq == rows[-1]["seq"] == len(rows)
    assert result.last_reason == rows[-1]["reason"] == "POSITION_CLOSED"
    assert result.rows == len(rows)
    with pytest.raises(AttributeError):  # frozen
        result.state = "PROTECTED"  # type: ignore[misc]


async def test_rows_out_of_order_are_sorted_and_an_identical_duplicate_counts_once() -> None:
    rows = await _valid_history()
    expected = replay.replay_transitions(rows, plan_hash=TEST_ONLY_PLAN_HASH)

    shuffled = [rows[3], rows[0], rows[4], rows[2], rows[1], dict(rows[2])]

    assert replay.replay_transitions(shuffled, plan_hash=TEST_ONLY_PLAN_HASH) == expected


async def test_the_same_seq_with_a_different_payload_fails_closed() -> None:
    rows = await _valid_history()
    conflicting = {**rows[2], "reason": "SOMETHING_ELSE"}

    _invalid([*rows, conflicting], "DUPLICATE_CONFLICT")


async def test_a_seq_gap_fails_closed() -> None:
    rows = await _valid_history()

    _invalid([r for r in rows if r["seq"] != 3], "SEQ_GAP")  # a hole in the middle
    _invalid(rows[1:], "SEQ_GAP")  # the history does not start at seq 1
    _invalid(rows[:-1] + [{**rows[-1], "seq": rows[-1]["seq"] + 1}], "SEQ_GAP")


async def test_a_first_row_that_is_not_the_registration_fails_closed() -> None:
    rows = await _valid_history()
    wrong_to = [{**rows[0], "to": "UNPROTECTED"}, *rows[1:]]
    wrong_from = [{**rows[0], "from": "AWAITING_FILL"}, *rows[1:]]

    _invalid(wrong_to, "BAD_START")
    _invalid(wrong_from, "BAD_START")


async def test_a_broken_from_to_chain_fails_closed() -> None:
    rows = await _valid_history()
    broken = [rows[0], rows[1], {**rows[2], "from": "PROTECTED"}, *rows[3:]]

    _invalid(broken, "CHAIN_BROKEN")


async def test_an_edge_outside_the_table_fails_closed() -> None:
    rows = await _valid_history()
    illegal = [rows[0], {**rows[1], "to": "PROTECTED"}]  # AWAITING_FILL -> PROTECTED
    equal_state = [rows[0], {**rows[1], "to": "AWAITING_FILL"}]  # never journaled by the guard

    _invalid(illegal, "ILLEGAL_EDGE")
    _invalid(equal_state, "ILLEGAL_EDGE")


async def test_a_close_required_history_that_returns_to_protected_fails_closed() -> None:
    rows = await _valid_history()
    base = {k: rows[1][k] for k in ("approval_id", "symbol", "trade_plan_id")}
    chain = [
        {**base, "seq": 1, "from": "NONE", "to": "AWAITING_FILL", "reason": "REGISTERED"},
        {**base, "seq": 2, "from": "AWAITING_FILL", "to": "UNPROTECTED", "reason": "X"},
        {**base, "seq": 3, "from": "UNPROTECTED", "to": "CLOSE_REQUIRED", "reason": "B2"},
        {**base, "seq": 4, "from": "CLOSE_REQUIRED", "to": "PROTECTED", "reason": "LATE"},
    ]

    _invalid(chain, "ILLEGAL_EDGE")


async def test_a_clearing_edge_without_the_allowed_evidence_fails_closed() -> None:
    rows = await _valid_history()
    for index, edge in ((2, "UNPROTECTED->PROTECTED_ENTRY_OPEN"), (4, "PROTECTED->FLAT")):
        assert f"{rows[index]['from']}->{rows[index]['to']}" == edge
    stop_row = rows[2]  # UNPROTECTED -> PROTECTED_ENTRY_OPEN, evidence REST_STOP_CONFIRMED
    assert stop_row["evidence"] == EVIDENCE_STOP

    for bad in (None, "ANYTHING", EVIDENCE_FLAT):
        _invalid([*rows[:2], {**stop_row, "evidence": bad}, *rows[3:]], "EVIDENCE_MISSING")
    without_key = {k: v for k, v in stop_row.items() if k != "evidence"}  # a pre-20-02 row
    _invalid([*rows[:2], without_key, *rows[3:]], "EVIDENCE_MISSING")

    close_flat = [
        rows[0],
        rows[1],
        {**rows[1], "seq": 3, "from": "UNPROTECTED", "to": "CLOSE_REQUIRED", "reason": "B2"},
        {**rows[1], "seq": 4, "from": "CLOSE_REQUIRED", "to": "FLAT", "reason": "X"},
    ]
    _invalid(close_flat, "EVIDENCE_MISSING")  # the evidence is null
    with_evidence = [*close_flat[:3], {**close_flat[3], "evidence": EVIDENCE_FLAT}]
    assert replay.replay_transitions(with_evidence, plan_hash=TEST_ONLY_PLAN_HASH).state == "FLAT"


async def test_a_stop_lost_history_that_clears_back_to_protected_fails_closed() -> None:
    rows = await _valid_history()
    base = {k: rows[1][k] for k in ("approval_id", "symbol", "trade_plan_id")}
    chain = [
        {**base, "seq": 1, "from": "NONE", "to": "AWAITING_FILL", "reason": "REGISTERED"},
        {**base, "seq": 2, "from": "AWAITING_FILL", "to": "UNPROTECTED", "reason": "X"},
        {
            **base,
            "seq": 3,
            "from": "UNPROTECTED",
            "to": "PROTECTED_ENTRY_OPEN",
            "reason": "STOP_CONFIRMED_ENTRY_OPEN",
            "evidence": EVIDENCE_STOP,
        },
        {
            **base,
            "seq": 4,
            "from": "PROTECTED_ENTRY_OPEN",
            "to": "UNPROTECTED",
            "reason": "STOP_LOST",
        },
        {
            **base,
            "seq": 5,
            "from": "UNPROTECTED",
            "to": "PROTECTED_ENTRY_OPEN",
            "reason": "STOP_CONFIRMED_ENTRY_OPEN",
            "evidence": EVIDENCE_STOP,
        },
    ]

    _invalid(chain, "STOP_LOST_CLEARED")
    assert (
        replay.replay_transitions(chain[:4], plan_hash=TEST_ONLY_PLAN_HASH).state == "UNPROTECTED"
    )


async def test_a_malformed_row_fails_closed() -> None:
    rows = await _valid_history()
    for key in ("from", "to", "reason", "seq", "approval_id", "trade_plan_id", "symbol"):
        missing = {k: v for k, v in rows[1].items() if k != key}
        _invalid([rows[0], missing, *rows[2:]], "MALFORMED_ROW")
    for bad_seq in ("2", 2.0, True, None, 0, -1):
        _invalid([rows[0], {**rows[1], "seq": bad_seq}, *rows[2:]], "MALFORMED_ROW")
    for key in ("from", "to", "reason"):
        _invalid([rows[0], {**rows[1], key: 7}, *rows[2:]], "MALFORMED_ROW")
        _invalid([rows[0], {**rows[1], key: ""}, *rows[2:]], "MALFORMED_ROW")
    _invalid([rows[0], {**rows[1], "to": "NOT_A_STATE"}, *rows[2:]], "MALFORMED_ROW")
    _invalid([rows[0], {**rows[1], "from": "NOT_A_STATE"}, *rows[2:]], "MALFORMED_ROW")
    _invalid([rows[0], {**rows[1], "evidence": 5}, *rows[2:]], "MALFORMED_ROW")
    _invalid([rows[0], "not a mapping", *rows[2:]], "MALFORMED_ROW")  # type: ignore[list-item]
    _invalid([], "EMPTY_HISTORY")


async def test_rows_of_two_plans_fail_closed() -> None:
    rows = await _valid_history()

    _invalid([*rows[:2], {**rows[2], "plan_hash": "b2" * 32}, *rows[3:]], "PLAN_MISMATCH")
    _invalid([*rows[:2], {**rows[2], "approval_id": "approval-other"}, *rows[3:]], "PLAN_MISMATCH")
    _invalid([*rows[:2], {**rows[2], "symbol": "ETHUSDT"}, *rows[3:]], "PLAN_MISMATCH")
    tagged = [{**r, "plan_hash": TEST_ONLY_PLAN_HASH} for r in rows]
    assert replay.replay_transitions(tagged, plan_hash=TEST_ONLY_PLAN_HASH).state == "FLAT"


async def test_the_live_guard_and_the_replay_share_one_clearing_rule() -> None:
    assert replay.CLEARING_EVIDENCE == {EVIDENCE_STOP, EVIDENCE_FLAT}
    assert replay.clearing_violation("UNPROTECTED", "PROTECTED", None, stop_lost=False) == (
        "EVIDENCE_MISSING"
    )
    assert replay.clearing_violation("UNPROTECTED", "PROTECTED", EVIDENCE_STOP, stop_lost=True) == (
        "STOP_LOST_CLEARED"
    )
    assert replay.clearing_violation("CLOSE_FAILED", "FLAT", EVIDENCE_FLAT, stop_lost=False) is None
    assert replay.clearing_violation("AWAITING_FILL", "UNPROTECTED", None, stop_lost=False) is None


def test_protection_replay_is_a_pure_module() -> None:
    from tests.support.ast_guards import (
        float_constructor_calls,
        forbidden_imports,
        wall_clock_calls,
    )

    path = Path(__file__).resolve().parents[1] / "src" / "execution" / "protection_replay.py"
    forbidden = (
        "asyncio",
        "binance*",
        "httpx",
        "numpy",
        "pandas",
        "polars",
        "pydantic",
        "requests",
        "sqlalchemy",
        "src.adapters",
        "src.db",
        "src.execution.manager",
        "src.execution.protection",
        "src.persistence",
    )
    assert forbidden_imports(path, forbidden) == []
    assert float_constructor_calls(path) == []
    assert wall_clock_calls(path) == []


async def test_a_refused_flat_move_never_sweeps_the_protective_legs() -> None:
    """A rejected FLAT must not cancel the stop (fail closed): the sweep follows an accepted move.

    No production path reaches this today (every FLAT call site holds a legal edge and its
    evidence); the guard is for the edges plans 20-09 and 20-17 add. The state is forced to a
    state with no edge to FLAT only to prove the order.
    """
    rig = await make_rig(real_closer=True)
    tracked = _tracked(rig)
    assert tracked.state is ProtectionState.AWAITING_FILL  # AWAITING_FILL -> FLAT is not an edge
    await rig.coordinator.step()  # the entry is open and unfilled: nothing happens
    cancels_before = len(rig.fake.calls_to("cancel_algo_order"))

    await rig.coordinator._watch_exit(tracked)  # noqa: SLF001 - zero position, two zero reads

    assert tracked.state is ProtectionState.AWAITING_FILL
    assert [r["to"] for r in _rows(rig, EVENT_REJECTED)] == ["FLAT"]
    assert SAFE_MODE_INVALID in rig.safe_mode.entered_reasons
    assert len(rig.fake.calls_to("cancel_algo_order")) == cancels_before
    assert tracked.sweep_done is False
