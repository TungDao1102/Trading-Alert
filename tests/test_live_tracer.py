"""The Phase 24 tracer: CONFIRM, one place_entry, a fill frame, a REST-confirmed stop (24-04).

Everything is real except the edges: the Binance-semantics fake exchange, the PTB bot, the clock
and the TEST_ONLY margin guard (tests/support/live_rig.py builds it through the one composition
module, src/live/wiring.py). An authorized APPROVE press then a CONFIRM press go through
`on_callback`; the sync `on_confirmed` hook of the confirm core reaches `ExecutionService`, which
schedules ONE `execute_approved_plan` on the event loop; the fake records exactly one `place_entry`
(a GTD LIMIT with no entry-time stop, D079). A SYNTHETIC ORDER_TRADE_UPDATE frame (never captured
Binance data) is routed by the real `UserDataRouter` whose `OrderLookup` is the live client-id
index and whose fill sink is the coordinator's; the coordinator places the stop and confirms it by
REST with no manual call in between. Time is virtual and `asyncio.sleep` fails the test.
"""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from typing import Any

import pytest
from src.approval.confirm_core import DEMO_CONFIRM_PROFILE
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    ExecutionIntentStatus,
    OrderRole,
)
from src.execution.approval_desk import ApprovalDesk
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState
from src.live.execution_service import (
    EVENT_PLACEMENT_OUTCOME,
    EVENT_PLACEMENT_REFUSED,
    EVENT_PLACEMENT_TASK_FAILED,
    REFUSAL_TOKEN_UNAVAILABLE,
)

from tests.shadow_fakes import T0, InMemoryShadowStores
from tests.support.live_rig import forbid_real_sleep, make_live_rig

D = Decimal


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


# --------------------------------------------------------------------------- #
# The tracer.
# --------------------------------------------------------------------------- #


async def test_confirm_places_one_entry_and_its_fill_ends_in_a_rest_confirmed_stop() -> None:
    rig = await make_live_rig()
    service = rig.wiring.service
    coordinator = rig.wiring.coordinator
    seen_in_hook: dict[str, Any] = {}

    def at_place_entry(kwargs: dict[str, Any]) -> None:
        # P-4: the id is in the index and the ENTRY intent row is written before the send.
        client_id = kwargs["new_client_order_id"]
        seen_in_hook["index"] = rig.wiring.index.known_order(client_id)
        seen_in_hook["intent"] = rig.intents.get_entry(approval_id=rig.approve_row().approval_id)

    rig.fake.on_place_entry = at_place_entry

    handle = await rig.approve_and_confirm()
    assert service.outstanding == 1, "the hook only scheduled the placement"
    assert rig.fake.calls_to("place_entry") == [], "nothing is placed before the loop runs"
    await service.drain()

    (placement,) = rig.fake.calls_to("place_entry")
    kwargs = placement["kwargs"]
    assert (kwargs["symbol"], kwargs["side"], kwargs["time_in_force"]) == (
        "BTCUSDT",
        "BUY",
        "GTD",
    )
    assert kwargs["new_client_order_id"] == rig.entry_id
    assert rig.fake.calls_to("place_algo_protective") == [], "no entry-time stop (D079)"
    assert rig.fake.open_algos == {}
    known = seen_in_hook["index"]
    assert known is not None and known.client_id == rig.entry_id
    assert seen_in_hook["intent"] is not None
    (outcome,) = rig.journal.by_type(EVENT_PLACEMENT_OUTCOME)
    assert json.loads(outcome.payload_json) == {"is_no_trade": False, "reason_code": "OK"}
    protection = coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.AWAITING_FILL

    # The exchange fills part of the entry and the stream says so; nobody calls the coordinator
    # with the fill. The two steps are the coordinator runner's cadence (place the stop, then
    # confirm it by REST), the same as tests/test_protection_router_rig.py.
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    routed = rig.route(rig.trade_frame())
    assert routed.fills == 1
    assert rig.sinks.fills == [], "the coordinator's sink replaced the recording one"
    assert [e for e in rig.journal.calls if "UNKNOWN" in e.event_type] == [], (
        "the index knew the entry id"
    )

    await coordinator.step()
    await rig.clock.advance(1)
    await coordinator.step()

    protection = coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.PROTECTED
    (stop,) = rig.fake.calls_to("place_algo_protective")
    assert stop["kwargs"]["close_position"] is True
    assert stop["kwargs"]["client_algo_id"] == derive_algo_client_id(
        plan_hash=rig.plan.plan_hash, role=OrderRole.STOP_LOSS.value
    )
    assert len(rig.fake.calls_to("place_entry")) == 1, "a placement is never re-sent"
    entry = rig.intents.get_entry(approval_id=handle.approve_id)
    assert entry is not None and entry.intent_status is ExecutionIntentStatus.ACKED


# --------------------------------------------------------------------------- #
# The hook, the token accessor, the failure paths.
# --------------------------------------------------------------------------- #


async def test_on_confirmed_returns_none_at_once_and_never_awaits() -> None:
    rig = await make_live_rig()
    service = rig.wiring.service
    handle = await rig.issue_and_send()
    await rig.press("APR", handle.short_id, query_id="q-apr")
    approval = rig.approve_row()
    assert approval.result is ApprovalResult.APPROVED

    result = service.on_confirmed(approval, rig.plan, rig.clock.now())

    assert result is None
    assert rig.inputs.calls == 0, "the hook did not run the placement inline"
    assert service.outstanding == 1
    await service.drain()
    assert service.outstanding == 0


async def test_on_confirmed_from_a_worker_thread_schedules_through_the_loop() -> None:
    rig = await make_live_rig()
    service = rig.wiring.service
    handle = await rig.issue_and_send()
    await rig.press("APR", handle.short_id, query_id="q-apr")
    approval = rig.approve_row()
    scheduled_on_main: list[bool] = []
    original = service._schedule

    def spy(*args: Any) -> None:
        scheduled_on_main.append(threading.current_thread() is threading.main_thread())
        original(*args)

    service._schedule = spy  # type: ignore[method-assign]

    worker = threading.Thread(
        target=service.on_confirmed, args=(approval, rig.plan, rig.clock.now())
    )
    worker.start()
    worker.join()
    assert scheduled_on_main == [], "nothing ran on the worker thread itself"
    await rig.clock.settle()  # the loop picks the scheduled call up
    assert scheduled_on_main == [True], "the schedule ran on the loop thread"
    await service.drain()
    assert rig.inputs.calls == 1


async def test_a_placement_task_that_raises_is_journaled_by_class_name_only() -> None:
    rig = await make_live_rig()
    service = rig.wiring.service
    handle = await rig.issue_and_send()
    await rig.press("APR", handle.short_id, query_id="q-apr")
    approval = rig.approve_row()

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("secret-detail-do-not-journal")

    rig.inputs.for_plan = boom

    service.on_confirmed(approval, rig.plan, rig.clock.now())  # the caller is unaffected
    await service.drain()

    (failed,) = rig.journal.by_type(EVENT_PLACEMENT_TASK_FAILED)
    assert json.loads(failed.payload_json) == {"error_class": "RuntimeError"}
    assert "secret-detail" not in failed.payload_json
    assert rig.fake.calls_to("place_entry") == []


def test_approve_token_for_an_unknown_id_is_none() -> None:
    desk = ApprovalDesk(
        InMemoryShadowStores(),
        profile=DEMO_CONFIRM_PROFILE,
        clock=lambda: T0,
        intent_reader=lambda approval_id: None,
    )
    assert desk.approve_token_for("apv-unknown") is None


async def test_approve_token_for_gives_the_issued_token_and_not_the_skip_one() -> None:
    rig = await make_live_rig()
    desk = rig.wiring.desk
    handle = await rig.issue_and_send()
    token = desk.approve_token_for(handle.approve_id)
    assert token is not None and token != ""
    context = desk.resolve(handle.short_id)
    assert context is not None and context["raw_token"] == token
    skip_id = next(
        a.approval_id for a in rig.stores.approvals.values() if a.action is ApprovalAction.SKIP_USER
    )
    assert desk.approve_token_for(skip_id) is None


async def test_without_a_token_the_service_journals_a_refusal_and_calls_nothing() -> None:
    rig = await make_live_rig(token_for=lambda approval_id: None)  # a restart: the token is gone
    handle = await rig.approve_and_confirm()
    await rig.wiring.service.drain()

    (refusal,) = rig.journal.by_type(EVENT_PLACEMENT_REFUSED)
    assert json.loads(refusal.payload_json) == {"reason": REFUSAL_TOKEN_UNAVAILABLE}
    assert rig.inputs.calls == 0
    assert rig.fake.calls == []
    assert rig.intents.get_entry(approval_id=handle.approve_id) is None
