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
