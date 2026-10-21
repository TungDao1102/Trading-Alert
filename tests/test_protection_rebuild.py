"""Rebuild of the protection state after a restart (Phase 20, plan 20-19; D-08, D-30, D077).

The rebuild reads the journaled ``PROTECTION_TRANSITION`` rows through ``replay_transitions`` (the
same guard as live), the STOP_LOSS intent row and the local spill's records of the plan, and
hands the coordinator a ``RestoredPlan``. Every test runs offline against the stateful Phase 19
fake exchange, the real ``MarketEmergencyCloser`` where a close happens, and virtual time. The
deadlines are the TEST_ONLY values of ``tests/support/execution_limits.py``; ``max_unprotected_ms``
stays NOT_CONFIGURED in the committed file. A green test proves agreement with the fake, not with
Binance (no Demo observation).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import ExecutionIntentStatus
from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.emergency_close import MarketEmergencyCloser
from src.execution.intent_recovery import resolve_unresolved_intents
from src.execution.protection import (
    EVENT_PROTECTION_TRANSITION,
    ProtectionCoordinator,
    ProtectionState,
)
from src.execution.protection_rebuild import (
    REASON_STOP_HISTORY_UNKNOWN,
    RestoredPlan,
    rebuild_plan,
)
from src.execution.protection_replay import replay_transitions

from tests.support.ast_guards import float_constructor_calls, wall_clock_calls
from tests.support.execution_limits import test_only_execution_limits as _test_limits
from tests.support.intent_store_fakes import SimulatedCrash
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    ProtectionRig,
    ScriptedEmergencyCloser,
    lot_filters_for_tests,
    make_rig,
)

D = Decimal
MAX_UNPROTECTED_MS = 7777
REBUILD_SOURCE = Path("src/execution/protection_rebuild.py")


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _correlation(plan_hash: str = TEST_ONLY_PLAN_HASH) -> str:
    return f"protection_{plan_hash}"


def _transition_events(rig: ProtectionRig) -> list[JournalEvent]:
    """The PROTECTION_TRANSITION rows the journal holds for the plan (a restart reads these)."""
    return [
        e
        for e in rig.journal.events.values()
        if e.correlation_id == _correlation() and e.event_type == EVENT_PROTECTION_TRANSITION
    ]


def _rows(rig: ProtectionRig) -> list[tuple[str, str, str]]:
    ordered = sorted(_transition_events(rig), key=lambda e: json.loads(e.payload_json)["seq"])
    out = []
    for event in ordered:
        body = json.loads(event.payload_json)
        out.append((body["from"], body["to"], body["reason"]))
    return out


def _stop_intent(rig: ProtectionRig) -> Any:
    return rig.inner_store.get_intent(approval_id=rig.entry.approval_id, role="STOP_LOSS")


def _rebuild(
    rig: ProtectionRig,
    *,
    events: list[JournalEvent] | None = None,
    spill_rows: list[JournalEvent] | None = None,
    use_spill_none: bool = False,
    stop_intent: Any = "from-store",
) -> RestoredPlan:
    return rebuild_plan(
        entry=rig.entry,
        transition_events=_transition_events(rig) if events is None else events,
        entry_intent=None,
        stop_intent=_stop_intent(rig) if stop_intent == "from-store" else stop_intent,
        spill_rows=None if use_spill_none else ([] if spill_rows is None else spill_rows),
    )


def _restart(rig: ProtectionRig, *, closer: Any = None) -> ProtectionCoordinator:
    """A new coordinator over the same fake exchange, intent store, journal and clock."""
    return ProtectionCoordinator(
        adapter=rig.fake,
        intent_store=rig.inner_store,  # type: ignore[arg-type]
        journal=rig.journal,
        safe_mode_controller=rig.safe_mode,
        alert_sink=rig.alerts,
        emergency_closer=rig.closer if closer is None else closer,
        limits=_test_limits(),
        clock=rig.clock,
        restore_required=True,
    )


def _real_closer(rig: ProtectionRig) -> MarketEmergencyCloser:
    rig.fake.set_lot_filters("BTCUSDT", lot_filters_for_tests())
    return MarketEmergencyCloser(
        adapter=rig.fake,
        journal=rig.journal,
        safe_mode_controller=rig.safe_mode,
        alert_sink=rig.alerts,
        clock=rig.clock,
        limits=_test_limits(),
    )


def _place_calls(rig: ProtectionRig) -> int:
    return len(rig.fake.calls_to("place_algo_protective"))


async def _crash_after_stop_intent_sent(rig: ProtectionRig) -> None:
    """Run 1: the first fill is seen, the STOP_LOSS intent is SENT, the process dies before the
    placement reaches the exchange. The fake is restored for run 2 (a new process)."""
    original = rig.fake.place_algo_protective

    async def crash(**kwargs: Any) -> Any:
        raise SimulatedCrash

    rig.fake.place_algo_protective = crash  # type: ignore[method-assign]
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    try:
        with pytest.raises(SimulatedCrash):
            await rig.coordinator.step()
    finally:
        rig.fake.place_algo_protective = original  # type: ignore[method-assign]


def _first_fill_time(rig: ProtectionRig) -> datetime:
    for event in _transition_events(rig):
        if json.loads(event.payload_json)["reason"].startswith("FIRST_FILL"):
            return event.occurred_at_utc
    raise AssertionError("no first-fill row")


async def _advance_ms(rig: ProtectionRig, milliseconds: int) -> None:
    await rig.clock.advance(milliseconds / 1000)


# --------------------------------------------------------------------------- #
# Task 1 (tracer): crash after the STOP_LOSS intent was SENT.
# --------------------------------------------------------------------------- #


async def test_crash_after_stop_intent_sent_restart_places_stop_once() -> None:
    rig = await make_rig(real_closer=True)
    await _crash_after_stop_intent_sent(rig)

    # Run 1 left an acknowledged-entry shaped plan without a stop: the intent is SENT, the
    # exchange never saw a placement.
    assert _stop_intent(rig).intent_status == ExecutionIntentStatus.SENT
    assert _place_calls(rig) == 0
    first_fill = _first_fill_time(rig)
    await _advance_ms(rig, 1500)

    # Run 2: a new process. Until restore() has run it blocks entries and is not complete.
    restarted = _restart(rig, closer=_real_closer(rig))
    assert restarted.blocks_new_entries() is True
    assert restarted.restore_complete is False

    restored = _rebuild(rig)
    assert restored.state is ProtectionState.UNPROTECTED
    assert restored.first_fill_at == first_fill
    assert restored.stop_confirmed_at is None
    assert restored.stop_lost_at is None
    assert restored.replay_valid is True
    assert restored.stop_history_known is True

    report = restarted.restore([restored], now_utc=rig.clock.now())
    assert restarted.restore_complete is True
    assert report.restored == (TEST_ONLY_PLAN_HASH,)
    assert report.replay_invalid == ()
    assert report.stop_history_unknown == ()
    # Restoring places nothing and never restarts the clock.
    assert _place_calls(rig) == 0
    view = restarted.protection_of(TEST_ONLY_PLAN_HASH)
    assert view is not None and view.first_fill_at_utc == first_fill

    # The ordinary step queries the stop by its deterministic id and, the fake showing it
    # absent, places it exactly once under that id at the plan's stop price.
    await restarted.step()
    calls = rig.fake.calls_to("place_algo_protective")
    assert len(calls) == 1
    assert calls[0]["kwargs"]["client_algo_id"] == rig.stop_id
    assert calls[0]["kwargs"]["trigger_price"] == rig.entry.sl_trigger_price

    # The next step reads it ACTIVE: the intent ends ACKED and the plan is PROTECTED.
    await restarted.step()
    assert _stop_intent(rig).intent_status == ExecutionIntentStatus.ACKED
    assert restarted.protection_of(TEST_ONLY_PLAN_HASH).state is ProtectionState.PROTECTED  # type: ignore[union-attr]
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    assert restarted.blocks_new_entries() is False


async def test_recovery_leaves_the_sent_stop_intent_for_the_rebuild_then_it_ends_acked() -> None:
    """F5: recovery turns SENT into UNKNOWN but never terminates a live plan's stop."""
    rig = await make_rig(real_closer=True)
    await _crash_after_stop_intent_sent(rig)
    restarted = _restart(rig, closer=_real_closer(rig))
    restarted.restore([_rebuild(rig)], now_utc=rig.clock.now())

    report = await resolve_unresolved_intents(
        store=rig.inner_store,  # type: ignore[arg-type]
        adapter=rig.fake,
        safe_mode_controller=rig.safe_mode,
        now_utc=rig.clock.now(),
    )
    assert (rig.entry.approval_id, "STOP_LOSS", ExecutionIntentStatus.UNKNOWN) in report.unresolved
    assert _stop_intent(rig).intent_status == ExecutionIntentStatus.UNKNOWN

    await restarted.step()
    await restarted.step()
    assert _stop_intent(rig).intent_status == ExecutionIntentStatus.ACKED
    assert len(rig.fake.calls_to("place_algo_protective")) == 1


def test_rebuild_plan_is_pure_no_wall_clock_no_float() -> None:
    assert wall_clock_calls(REBUILD_SOURCE) == []
    assert float_constructor_calls(REBUILD_SOURCE) == []


async def test_a_plan_with_no_rows_and_no_stop_intent_restores_awaiting_fill() -> None:
    rig = await make_rig(register=False)
    restored = rebuild_plan(
        entry=rig.entry,
        transition_events=[],
        entry_intent=None,
        stop_intent=None,
        spill_rows=[],
    )
    assert restored.state is ProtectionState.AWAITING_FILL
    assert restored.seq == 0
    assert restored.first_fill_at is None
    assert restored.stop_history_known is True
    assert restored.replay_valid is True


async def test_no_rows_but_a_stop_intent_is_an_unknown_history_dated_at_the_intent() -> None:
    rig = await make_rig()
    await _crash_after_stop_intent_sent(rig)
    intent = _stop_intent(rig)
    restored = rebuild_plan(
        entry=rig.entry,
        transition_events=[],
        entry_intent=None,
        stop_intent=intent,
        spill_rows=[],
    )
    assert restored.state is ProtectionState.UNPROTECTED
    assert restored.stop_history_known is False
    assert restored.last_reason == REASON_STOP_HISTORY_UNKNOWN
    assert restored.stop_lost_at == intent.intended_at_utc
    assert restored.first_fill_at == intent.intended_at_utc


def _spill_protection_row(rig: ProtectionRig, *, at: datetime) -> JournalEvent:
    """A protection-correlation record that only the spill holds (the journal lacks it)."""
    body = json.dumps({"state_after": "PROTECTED_ENTRY_OPEN"}, sort_keys=True)
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="pop",
            event_type="OPERATOR_PROTECT_STEPPED",
            entity_id=rig.entry.plan_hash,
            occurred_at_utc=at,
            payload_json=body,
        ),
        occurred_at_utc=at,
        event_type="OPERATOR_PROTECT_STEPPED",
        entity_type="ProtectionState",
        entity_id=rig.entry.plan_hash,
        correlation_id=_correlation(),
        payload_json=body,
    )


# --------------------------------------------------------------------------- #
# Task 2: clocks survive, lost stops stay lost, corrupt replay fails closed.
# --------------------------------------------------------------------------- #


def _view(coordinator: ProtectionCoordinator) -> Any:
    protection = coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection


def _script_failures(rig: ProtectionRig, method: str, count: int) -> None:
    for _ in range(count):
        rig.fake.fail_next(method, RuntimeError("scripted ambiguous failure"))


def _stop_queries(rig: ProtectionRig) -> int:
    return len(rig.fake.calls_to("query_algo_order_by_client"))


def _market_closes(rig: ProtectionRig) -> list[Any]:
    return rig.fake.calls_to("place_market_close")


def _states_of(rig: ProtectionRig) -> list[str]:
    return [to for _, to, _ in _rows(rig)]


def _replays_clean(rig: ProtectionRig) -> bool:
    """The whole journal (run 1 and run 2) is still one valid, contiguous history."""
    payloads = [json.loads(e.payload_json) for e in _transition_events(rig)]
    replay_transitions(payloads, plan_hash=TEST_ONLY_PLAN_HASH)
    return True


async def _to_protected_entry_open(rig: ProtectionRig, cancel_failures: int) -> None:
    """First fill 0.004, the stop confirmed ACTIVE by REST, the entry still open."""
    _script_failures(rig, "cancel_normal_order", cancel_failures)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _view(rig.coordinator).state is ProtectionState.PROTECTED_ENTRY_OPEN


async def test_restart_never_resets_stop_lost_at() -> None:
    rig = await make_rig(real_closer=True)
    await _to_protected_entry_open(rig, cancel_failures=2)
    await _advance_ms(rig, 1000)
    rig.fake.trigger_stop(rig.stop_id)
    _script_failures(rig, "snapshot_positions", 500)  # the position is never readable
    lost_at = rig.clock.now()
    await rig.coordinator.step()
    assert _view(rig.coordinator).state is ProtectionState.UNPROTECTED
    assert _view(rig.coordinator).stop_lost_at_utc == lost_at

    # The process dies and restarts 5000 ms after the loss.
    await _advance_ms(rig, 5000)
    restart_time = rig.clock.now()
    restarted = _restart(rig, closer=_real_closer(rig))
    restored = _rebuild(rig)
    assert restored.stop_lost_at == lost_at
    assert restored.stop_lost_at != restart_time
    assert restored.state is ProtectionState.UNPROTECTED
    assert restored.stop_history_known is True
    queries, placements = _stop_queries(rig), _place_calls(rig)
    restarted.restore([restored], now_utc=restart_time)
    assert _view(restarted).stop_lost_at_utc == lost_at
    assert restarted.blocks_new_entries() is True

    await restarted.step()
    assert _view(restarted).state is ProtectionState.UNPROTECTED
    await _advance_ms(rig, MAX_UNPROTECTED_MS - 5000 - 1)  # L + 7776 ms
    await restarted.step()
    assert _view(restarted).state is ProtectionState.UNPROTECTED
    assert _market_closes(rig) == []
    await _advance_ms(rig, 1)  # L + 7777 ms, not restart + 7777 ms
    await restarted.step()
    assert ("UNPROTECTED", "CLOSE_REQUIRED", "B4_STOP_LOST_UNRESOLVED") in _rows(rig)
    # The lost stop was never queried for re-placement and never placed; no guessed close.
    assert _stop_queries(rig) == queries
    assert _place_calls(rig) == placements == 1
    assert _market_closes(rig) == []
    assert _replays_clean(rig)


async def test_restart_in_close_required_blocks_and_a_late_active_stop_never_downgrades() -> None:
    rig = await make_rig(closer_results=[True])
    _script_failures(rig, "cancel_normal_order", 1000)  # the entry stays open
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # the stop is placed NEW, the cancel fails
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"  # a status of an unknown class
    await rig.coordinator.step()
    await _advance_ms(rig, MAX_UNPROTECTED_MS)
    await rig.coordinator.step()  # B3: both ambiguous
    assert _view(rig.coordinator).state is ProtectionState.CLOSE_REQUIRED
    assert _rows(rig)[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B3_BOTH_AMBIGUOUS")

    restarted = _restart(rig, closer=ScriptedEmergencyCloser([True, True, True]))
    restored = _rebuild(rig)
    assert restored.state is ProtectionState.CLOSE_REQUIRED
    assert restored.close_branch == "B3_BOTH_AMBIGUOUS"
    restarted.restore([restored], now_utc=rig.clock.now())
    assert _view(restarted).state is ProtectionState.CLOSE_REQUIRED
    assert restarted.blocks_new_entries() is True

    # A late REST answer showing the stop ACTIVE does not downgrade the plan.
    rig.fake.open_algos[rig.stop_id].status = "NEW"
    await restarted.step()
    await restarted.step()
    assert _view(restarted).state is ProtectionState.CLOSE_REQUIRED
    assert restarted.blocks_new_entries() is True
    assert "PROTECTED" not in _states_of(rig)
    assert "PROTECTED_ENTRY_OPEN" not in _states_of(rig)
    assert _place_calls(rig) == 1


async def test_restart_in_close_failed_keeps_its_branch() -> None:
    rig = await make_rig()  # the scripted closer answers False: the close never ends flat
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"
    await rig.coordinator.step()
    await _advance_ms(rig, MAX_UNPROTECTED_MS)
    await rig.coordinator.step()
    assert _view(rig.coordinator).state is ProtectionState.CLOSE_FAILED
    restored = _rebuild(rig)
    assert restored.state is ProtectionState.CLOSE_FAILED
    assert restored.close_branch == "B2_STOP_UNCONFIRMED"
    restarted = _restart(rig)
    restarted.restore([restored], now_utc=rig.clock.now())
    assert restarted.blocks_new_entries() is True
    assert _view(restarted).state is ProtectionState.CLOSE_FAILED


async def test_restart_of_a_first_fill_unprotected_plan_keeps_the_first_fill_deadline() -> None:
    rig = await make_rig(real_closer=True)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # the stop is placed NEW, the entry cancel went through
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"  # never ACTIVE: never protection
    await rig.coordinator.step()
    first_fill = _first_fill_time(rig)
    assert _view(rig.coordinator).state is ProtectionState.UNPROTECTED

    await _advance_ms(rig, 3000)
    restarted = _restart(rig, closer=_real_closer(rig))
    restored = _rebuild(rig)
    assert restored.first_fill_at == first_fill
    assert restored.stop_confirmed_at is None
    assert restored.stop_history_known is True
    restarted.restore([restored], now_utc=rig.clock.now())

    await _advance_ms(rig, MAX_UNPROTECTED_MS - 3000 - 1)  # first_fill + 7776 ms
    await restarted.step()
    assert _view(restarted).state is ProtectionState.UNPROTECTED
    assert _market_closes(rig) == []
    await _advance_ms(rig, 1)  # first_fill + 7777 ms, not restart + 7777 ms
    await restarted.step()
    assert ("UNPROTECTED", "CLOSE_REQUIRED", "B2_STOP_UNCONFIRMED") in _rows(rig)
    assert _replays_clean(rig)


async def test_a_flat_plan_restores_flat_and_is_not_stepped_for_protection() -> None:
    rig = await make_rig(real_closer=True)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"
    await rig.coordinator.step()
    await _advance_ms(rig, MAX_UNPROTECTED_MS)
    await rig.coordinator.step()  # B2 and the real close
    await rig.coordinator.step()  # flat on two reads, the entry terminal: FLAT
    assert _view(rig.coordinator).state is ProtectionState.FLAT

    restarted = _restart(rig, closer=_real_closer(rig))
    restored = _rebuild(rig)
    assert restored.state is ProtectionState.FLAT
    assert restored.stop_history_known is True
    queries, placements, closes = _stop_queries(rig), _place_calls(rig), len(_market_closes(rig))
    restarted.restore([restored], now_utc=rig.clock.now())
    await restarted.step()
    assert _view(restarted).state is ProtectionState.FLAT
    # The only reads are the idempotent sweep's cancel verification of the three legs.
    assert _stop_queries(rig) <= queries + 3
    assert _place_calls(rig) == placements
    assert len(_market_closes(rig)) == closes
    assert restarted.blocks_new_entries() is False


def _journal_rows(rig: ProtectionRig) -> list[JournalEvent]:
    return sorted(_transition_events(rig), key=lambda e: json.loads(e.payload_json)["seq"])


def _with_payload(event: JournalEvent, **changes: Any) -> JournalEvent:
    body = json.loads(event.payload_json)
    body.update(changes)
    return replace(event, payload_json=json.dumps(body, sort_keys=True, separators=(",", ":")))


@pytest.mark.parametrize("corruption", ["seq_gap", "illegal_edge", "missing_evidence"])
async def test_corrupt_replay_fails_closed_unprotected_and_never_places_a_stop(
    corruption: str,
) -> None:
    rig = await make_rig(real_closer=True)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.010")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _view(rig.coordinator).state is ProtectionState.PROTECTED
    rows = _journal_rows(rig)
    assert [json.loads(e.payload_json)["seq"] for e in rows] == [1, 2, 3]
    intent_time = _stop_intent(rig).intended_at_utc
    if corruption == "seq_gap":
        corrupted = [rows[0], rows[2]]
    elif corruption == "illegal_edge":
        corrupted = [rows[0], rows[1], _with_payload(rows[2], to="AWAITING_FILL")]
    else:
        corrupted = [rows[0], rows[1], _with_payload(rows[2], evidence=None)]

    await _advance_ms(rig, 2000)
    restored = _rebuild(rig, events=corrupted)
    assert restored.replay_valid is False
    assert restored.state is ProtectionState.UNPROTECTED
    assert restored.stop_history_known is False
    assert restored.last_reason == REASON_STOP_HISTORY_UNKNOWN
    assert restored.stop_lost_at == restored.first_fill_at == intent_time  # earliest durable time

    restarted = _restart(rig, closer=_real_closer(rig))
    queries, placements = _stop_queries(rig), _place_calls(rig)
    report = restarted.restore([restored], now_utc=rig.clock.now())
    assert report.replay_invalid == (TEST_ONLY_PLAN_HASH,)
    assert report.stop_history_unknown == (TEST_ONLY_PLAN_HASH,)
    assert "PROTECTION_STATE_INVALID" in rig.safe_mode.entered_reasons
    assert restarted.blocks_new_entries() is True

    # The position (0.010) is open: the D077 rule closes it by MARKET; no stop is read or placed.
    await restarted.step()
    assert ("UNPROTECTED", "CLOSE_REQUIRED", "B4_FILL_AFTER_STOP") in _rows(rig)
    assert [c["kwargs"]["quantity"] for c in _market_closes(rig)] == [D("0.010")]
    assert _stop_queries(rig) == queries
    assert _place_calls(rig) == placements == 1


@pytest.mark.parametrize("source", ["missing_rows", "spill_only_row", "unreadable_spill"])
async def test_unknown_stop_history_never_permits_a_replacement(source: str) -> None:
    rig = await make_rig(real_closer=True)
    await _crash_after_stop_intent_sent(rig)  # exposure +0.004, intent SENT, the stop never placed
    first_fill = _first_fill_time(rig)
    intent_time = _stop_intent(rig).intended_at_utc
    assert intent_time == first_fill
    await _advance_ms(rig, 1000)
    _script_failures(rig, "snapshot_positions", 500)  # the position cannot be read

    if source == "missing_rows":
        restored = _rebuild(rig, events=[])
    elif source == "spill_only_row":
        restored = _rebuild(rig, spill_rows=[_spill_protection_row(rig, at=first_fill)])
    else:
        restored = _rebuild(rig, use_spill_none=True)
    assert restored.state is ProtectionState.UNPROTECTED
    assert restored.stop_history_known is False
    assert restored.last_reason == REASON_STOP_HISTORY_UNKNOWN
    assert restored.stop_lost_at == intent_time == restored.first_fill_at

    restarted = _restart(rig, closer=_real_closer(rig))
    queries = _stop_queries(rig)
    report = restarted.restore([restored], now_utc=rig.clock.now())
    assert report.stop_history_unknown == (TEST_ONLY_PLAN_HASH,)
    assert "RESTORE_INCONSISTENT" in rig.safe_mode.entered_reasons
    assert restarted.blocks_new_entries() is True

    # The stop is never placed or trusted; the D077 clock runs from the earliest durable time.
    await restarted.step()
    assert _view(restarted).state is ProtectionState.UNPROTECTED
    await _advance_ms(rig, MAX_UNPROTECTED_MS - 1000 - 1)  # first_fill + 7776 ms
    await restarted.step()
    assert _view(restarted).state is ProtectionState.UNPROTECTED
    await _advance_ms(rig, 1)  # first_fill + 7777 ms
    await restarted.step()
    assert _view(restarted).state in (ProtectionState.CLOSE_REQUIRED, ProtectionState.CLOSE_FAILED)
    assert ("UNPROTECTED", "CLOSE_REQUIRED", "B4_STOP_LOST_UNRESOLVED") in _rows(rig)
    assert _market_closes(rig) == []  # no MARKET close with a guessed quantity
    assert _place_calls(rig) == 0  # the placement counter stays zero
    assert _stop_queries(rig) == queries  # the stop is never queried for re-placement


async def test_unknown_stop_history_with_exposure_closes_by_position_and_places_nothing() -> None:
    rig = await make_rig(real_closer=True)
    await _crash_after_stop_intent_sent(rig)
    restored = _rebuild(rig, events=[])
    restarted = _restart(rig, closer=_real_closer(rig))
    restarted.restore([restored], now_utc=rig.clock.now())
    queries = _stop_queries(rig)

    await restarted.step()
    assert ("UNPROTECTED", "CLOSE_REQUIRED", "B4_FILL_AFTER_STOP") in _rows(rig)
    assert [c["kwargs"]["quantity"] for c in _market_closes(rig)] == [D("0.004")]
    assert [c["kwargs"]["side"] for c in _market_closes(rig)] == ["SELL"]
    assert _place_calls(rig) == 0
    assert _stop_queries(rig) == queries
    await restarted.step()
    assert _view(restarted).state is ProtectionState.FLAT
    assert _place_calls(rig) == 0


async def test_unknown_stop_history_flat_with_the_entry_open_stays_unprotected() -> None:
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "cancel_normal_order", 1000)  # the entry stays open
    await _crash_after_stop_intent_sent(rig)
    rig.fake.positions["BTCUSDT"] = D("0")  # flat, though the entry can still fill
    restored = _rebuild(rig, events=[])
    restarted = _restart(rig, closer=_real_closer(rig))
    restarted.restore([restored], now_utc=rig.clock.now())

    for _ in range(3):
        await restarted.step()
        assert _view(restarted).state is ProtectionState.UNPROTECTED
        assert restarted.blocks_new_entries() is True
    await _advance_ms(rig, MAX_UNPROTECTED_MS)
    await restarted.step()
    assert ("UNPROTECTED", "CLOSE_REQUIRED", "B4_STOP_LOST_UNRESOLVED") in _rows(rig)
    assert _market_closes(rig) == []  # flat: nothing to close, no guessed quantity
    assert _view(restarted).state is ProtectionState.CLOSE_REQUIRED
    assert _place_calls(rig) == 0


async def test_restore_refuses_a_second_call_a_repeated_plan_and_a_naive_time() -> None:
    rig = await make_rig(register=False, place_entry=False)
    restored = rebuild_plan(
        entry=rig.entry, transition_events=[], entry_intent=None, stop_intent=None, spill_rows=[]
    )
    restarted = _restart(rig)
    with pytest.raises(ValueError):
        restarted.restore([restored], now_utc=datetime(2026, 10, 16, 12, 0, 0))
    with pytest.raises(ValueError):
        restarted.restore([restored, restored], now_utc=rig.clock.now())
    assert restarted.restore_complete is False
    restarted.restore([restored], now_utc=rig.clock.now())
    assert restarted.restore_complete is True
    # The journal never recorded the plan: restore wrote the seq-1 registration row it lacks.
    assert _rows(rig) == [("NONE", "AWAITING_FILL", "REGISTERED_AFTER_RESTORE")]
    with pytest.raises(RuntimeError):
        restarted.restore([], now_utc=rig.clock.now())


async def test_unknown_stop_history_plan_kept_in_a_close_state_is_not_downgraded() -> None:
    rig = await make_rig()
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"
    await rig.coordinator.step()
    await _advance_ms(rig, MAX_UNPROTECTED_MS)
    await rig.coordinator.step()
    assert _view(rig.coordinator).state is ProtectionState.CLOSE_FAILED
    restored = _rebuild(rig, use_spill_none=True)  # the spill is unreadable
    assert restored.state is ProtectionState.CLOSE_FAILED  # never relabelled UNPROTECTED
    assert restored.stop_history_known is False
    assert restored.close_branch == "B2_STOP_UNCONFIRMED"
