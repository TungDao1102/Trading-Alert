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
