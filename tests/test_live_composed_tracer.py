"""The end-to-end tracer THROUGH `build_wiring` (plan 24-27B, Task 1 behaviours 1 to 3 of 24-27).

A Demo smoke request is injected into the process's `DemoSmokeSignalSource`; the composed signal
pump hands it to the composed approval sender, the card goes out through the (fake) bot, an APPROVE
press and a CONFIRM press go through the runner's one `on_callback` handler, the composed execution
service places exactly ONE entry through the composed producer, and a SYNTHETIC `ORDER_TRADE_UPDATE`
frame (never captured data) routed by the composed stream's router reaches the composed
coordinator, which places the stop and confirms it by REST. Every object between the edges is the
one `build_wiring` built; the edges are the in-memory stores, the Binance-semantics fake exchange,
the PTB bot and the virtual clock (tests/support/live_composed_rig.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    ExecutionIntentStatus,
    OrderRole,
    SignalStatus,
    TradePlanStatus,
)
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME
from src.live.wiring import TASK_SIGNAL_PUMP, check_wiring

from tests.support.live_composed_rig import ComposedRig, make_composed_rig
from tests.support.live_rig import forbid_real_sleep


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


async def _run_pump(rig: ComposedRig) -> None:
    assert rig.wiring is not None
    (spec,) = [s for s in rig.wiring.specs if s.name == TASK_SIGNAL_PUMP]
    await spec.run()


async def test_the_composed_wiring_has_no_broken_link_on_the_in_memory_stores(
    tmp_path: Path,
) -> None:
    rig = make_composed_rig(tmp_path)
    wiring = await rig.prepare()
    assert check_wiring(wiring) == []


async def test_confirm_places_one_entry_and_its_stream_fill_ends_in_a_protected_position(
    tmp_path: Path,
) -> None:
    rig = make_composed_rig(tmp_path)
    wiring = await rig.prepare()
    request = await rig.derive_request()

    # The pump hands the queued request to the sender: one card, the rows persisted, a reservation.
    await _run_pump(rig)
    (card,) = rig.bot.sent
    assert "Mode: DEMO" in card.text
    assert rig.memory.shadow.signals[request.signal.signal_id].status is SignalStatus.NOTIFIED
    assert rig.memory.reservations.get(request.plan.trade_plan_id) is not None
    short_id = next(iter(rig.memory.shadow.mappings))

    assert (await rig.press("APR", short_id, query_id="q-apr")).ok
    approve = next(
        a for a in rig.memory.shadow.approvals.values() if a.action is ApprovalAction.APPROVE
    )
    assert approve.status is ApprovalResult.APPROVED
    assert rig.memory.shadow.plans[request.plan.trade_plan_id].status is TradePlanStatus.APPROVED

    await rig.clock.advance(30)
    rig.set_prices()
    assert rig.fake.calls_to("place_entry") == []
    assert (await rig.press("CNF", short_id, query_id="q-cnf")).ok
    await wiring.service.drain()

    (placement,) = rig.fake.calls_to("place_entry")
    kwargs = placement["kwargs"]
    assert (kwargs["symbol"], kwargs["side"], kwargs["time_in_force"]) == ("BTCUSDT", "BUY", "GTD")
    assert kwargs["new_client_order_id"] == rig.entry_id(request)
    assert rig.fake.calls_to("place_algo_protective") == [], "no entry-time stop (D079)"
    (outcome,) = rig.memory.journal.by_type(EVENT_PLACEMENT_OUTCOME)
    assert json.loads(outcome.payload_json) == {"is_no_trade": False, "reason_code": "OK"}
    protection = wiring.coordinator.protection_of(request.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.AWAITING_FILL
    assert wiring.index.known_order(rig.entry_id(request)) is not None
    entry = rig.memory.execution_state.get_entry(approval_id=approve.approval_id)
    assert entry is not None and entry.intent_status is ExecutionIntentStatus.ACKED

    # The exchange fills the entry; the stream says so. The composed router (index lookup) feeds
    # the composed coordinator; two protection passes place the stop and confirm it by REST.
    quantity = str(placement["kwargs"]["quantity"])
    rig.fake.fill(rig.entry_id(request), quantity=placement["kwargs"]["quantity"])
    routed = rig.route(rig.trade_frame(request, quantity))
    assert routed.fills == 1
    await wiring.coordinator.step()
    await rig.clock.advance(1)
    await wiring.coordinator.step()

    protection = wiring.coordinator.protection_of(request.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.PROTECTED
    (stop,) = rig.fake.calls_to("place_algo_protective")
    assert stop["kwargs"]["close_position"] is True
    assert stop["kwargs"]["client_algo_id"] == derive_algo_client_id(
        plan_hash=request.plan.plan_hash, role=OrderRole.STOP_LOSS.value
    )
    assert len(rig.fake.calls_to("place_entry")) == 1, "a placement is never re-sent"


async def test_the_protected_entry_is_restorable_until_its_plan_ends_d093(tmp_path: Path) -> None:
    """D093 on the composed process: an ACKED entry is restored while its plan is live."""
    from src.domain.journal import JournalEvent

    rig = make_composed_rig(tmp_path)
    wiring = await rig.prepare()
    request = await rig.derive_request()
    await _run_pump(rig)
    short_id = next(iter(rig.memory.shadow.mappings))
    assert (await rig.press("APR", short_id, query_id="q-apr")).ok
    await rig.clock.advance(30)
    rig.set_prices()
    import threading

    from src.ops.store_executor import WRITER_THREAD_PREFIX

    outcome_threads: list[str] = []
    real_record = rig.memory.journal.record

    def record(event: object) -> None:
        if getattr(event, "event_type", "") == EVENT_PLACEMENT_OUTCOME:
            outcome_threads.append(threading.current_thread().name)
        real_record(event)  # type: ignore[arg-type]

    rig.memory.journal.record = record  # type: ignore[method-assign]
    assert (await rig.press("CNF", short_id, query_id="q-cnf")).ok
    await wiring.service.drain()
    # Plan 24-27B: the placement service's own journal row left the loop (the manager's
    # write-ahead intent and journal calls are NOT behind the seam: see the 24-27B summary).
    assert len(outcome_threads) == 1 and outcome_threads[0].startswith(WRITER_THREAD_PREFIX)
    intents = rig.memory.execution_state
    assert [e.plan_hash for e in intents.restorable_entries()] == [request.plan.plan_hash]

    # The coordinator journals every transition; an END (FLAT) removes the plan from the read.
    correlation = f"protection_{request.plan.plan_hash}"
    rig.memory.journal.record(
        JournalEvent(
            journal_event_id="ended-1",
            occurred_at_utc=rig.clock.now(),
            event_type="PROTECTION_TRANSITION",
            entity_type="ProtectionState",
            entity_id=request.plan.plan_hash,
            correlation_id=correlation,
            payload_json='{"seq":3,"to":"FLAT"}',
        )
    )
    assert intents.restorable_entries() == ()


async def test_the_sender_store_calls_run_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan 24-27B (D-25): desk issue, reservation, signal transition and journal leave the loop."""
    import threading

    from src.ops.store_executor import WRITER_THREAD_PREFIX

    rig = make_composed_rig(tmp_path)
    wiring = await rig.prepare()
    threads: dict[str, str] = {}
    sender = wiring.sender

    def spy(owner: object, attr: str, label: str) -> None:
        original = getattr(owner, attr)

        def wrapped(*args: object, **kwargs: object) -> object:
            threads.setdefault(label, threading.current_thread().name)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, attr, wrapped)

    spy(wiring.desk, "issue", "issue")
    spy(sender, "_register_reservation", "reservation")
    spy(sender._entities, "transition_signal", "transition")
    await rig.derive_request()
    await _run_pump(rig)
    assert set(threads) == {"issue", "reservation", "transition"}
    for name, thread in threads.items():
        assert thread.startswith(WRITER_THREAD_PREFIX), f"{name} ran on {thread}"
