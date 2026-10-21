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
from datetime import datetime, timedelta
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

from tests.support.ast_guards import float_constructor_calls, wall_clock_calls
from tests.support.execution_limits import test_only_execution_limits
from tests.support.intent_store_fakes import SimulatedCrash
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    ProtectionRig,
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
        limits=test_only_execution_limits(),
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
        limits=test_only_execution_limits(),
    )


def _place_calls(rig: ProtectionRig) -> int:
    return len(rig.fake.calls_to("place_algo_protective"))


def _crash_on_stop_placement(rig: ProtectionRig) -> None:
    """The next stop placement dies before anything reaches the exchange."""

    async def crash(**kwargs: Any) -> Any:
        raise SimulatedCrash

    rig.fake.place_algo_protective = crash  # type: ignore[method-assign]


async def _crash_after_stop_intent_sent(rig: ProtectionRig) -> None:
    _crash_on_stop_placement(rig)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    with pytest.raises(SimulatedCrash):
        await rig.coordinator.step()


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
    assert calls[0]["client_algo_id"] == rig.stop_id
    assert calls[0]["trigger_price"] == rig.entry.sl_trigger_price

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
