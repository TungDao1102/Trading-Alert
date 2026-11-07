"""Replay and restart matrix over the composed fakes (plan 24-28; D-09, D-20, EXEC-03, OPS-03).

ROADMAP criterion 3 on the composed process: a replayed APPROVE, CONFIRM or CANCEL answers from
the stored decision and changes nothing; two concurrent CONFIRM presses lead to exactly one
`place_entry`; a restart at any point of the approval flow never re-sends an order (D080). Every
test asserts the count of `place_entry` calls on the Binance-semantics fake as exactly 0 or
exactly 1. The PostgreSQL variant is `tests/test_live_replay_restart_pg.py`.

Run 1 is the live rig (`make_live_rig`). A restart is NEW objects over the same stores and the
same fake exchange: `_second_process` builds a second execution path (a fresh confirm book and a
fresh service) and, for the entry-state scenarios, reuses `Restart` of the 24-26 rehydrate module.

TEST_ONLY: the prices, the snapshot and the TTL are the rig's made-up values.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from functools import partial
from typing import Any, cast

import pytest
from src.adapters.telegram_callbacks import DispatchResult, on_callback
from src.approval.confirm_core import DEMO_CONFIRM_PROFILE
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    ExecutionIntentStatus,
    OrderRole,
)
from src.execution.confirm_recheck import make_confirm_recheck, prefetched_provider
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.pre_placement import check_remaining_validity
from src.execution.protection import ProtectionState
from src.live.wiring import LiveWiring, build_execution_path

from tests.shadow_fakes import AUTHORIZED_USER_IDS, CHAT_ID, USER_ID, make_callback_update
from tests.support.live_rig import LiveRig, forbid_real_sleep, make_live_rig
from tests.support.protection_doubles import RecordingAlerts
from tests.test_live_restart_rehydrate import _restart

D = Decimal


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _place_entry_count(rig: LiveRig) -> int:
    return len(rig.fake.calls_to("place_entry"))


def _entry_intent(rig: LiveRig) -> Any:
    return rig.intents.get_entry(approval_id=rig.approve_row().approval_id)


def _approve_rows(rig: LiveRig) -> list[Any]:
    return [a for a in rig.stores.approvals.values() if a.action is ApprovalAction.APPROVE]


async def _press_on(
    rig: LiveRig, wiring: LiveWiring, prefix: str, short_id: str, *, query_id: str
) -> DispatchResult:
    """One authorized press through `on_callback` against a given execution path."""
    update = make_callback_update(
        data=f"{prefix}:{short_id}",
        chat_id=CHAT_ID,
        query_id=query_id,
        message_chat_id=CHAT_ID,
        from_user_id=USER_ID,
        message_id=1,
        chat_type="private",
    )
    return await on_callback(
        update,
        cast(Any, None),
        **wiring.confirm_flow.callback_kwargs(
            authorized_chat_id=CHAT_ID,
            authorized_user_ids=AUTHORIZED_USER_IDS,
            error_journal=rig.stores.record_journal,
        ),
    )


def _second_process(rig: LiveRig) -> LiveWiring:
    """A new execution path over the first process' stores, intents, fake and SAFE_MODE state.

    A fresh confirm flow means a fresh confirm book: the raw tokens and the messages of run 1 are
    gone, as after a real restart.
    """
    return build_execution_path(
        loop=rig.wiring.service._loop,
        clock=rig.clock,
        adapter=rig.fake,  # type: ignore[arg-type]
        stores=rig.stores,
        intent_store=rig.intents,
        journal=rig.journal,
        safe_mode_controller=rig.safe_mode,
        enablement=rig.enablement,
        alert_sink=RecordingAlerts(),
        limits=rig.limits,
        inputs=rig.inputs,
        profile=DEMO_CONFIRM_PROFILE,
        authorized_chat_id=CHAT_ID,
        bot=rig.bot,
        sleep=rig.sleep,
        mark_price=lambda symbol: D("50050"),
        validity_rule=partial(
            check_remaining_validity,
            min_remaining_validity_seconds=rig.limits.min_remaining_validity_seconds,
            gtd_clock_margin=timedelta(seconds=2),
        ),
        recheck=make_confirm_recheck(prefetched_provider(rig.holder)),
        prefetch=None,
        token_for=lambda approval_id: None,
    )


# --------------------------------------------------------------------------- #
# Task 1: replays and concurrent presses on the composed fakes.
# --------------------------------------------------------------------------- #


async def test_a_replayed_approve_keeps_one_decision_and_places_nothing() -> None:
    rig = await make_live_rig()
    handle = await rig.issue_and_send()
    assert (await rig.press("APR", handle.short_id, query_id="q-apr-1")).ok
    first = rig.approve_row()
    sent_after_first = len(rig.bot.sent)

    await rig.press("APR", handle.short_id, query_id="q-apr-2")
    await rig.press("APR", handle.short_id, query_id="q-apr-1")
    await rig.wiring.service.drain()

    assert _approve_rows(rig) == [first], "one APPROVED decision, unchanged"
    assert first.result is ApprovalResult.APPROVED
    assert len(rig.bot.sent) == sent_after_first, "no second confirm card"
    assert _place_entry_count(rig) == 0, "APPROVE alone never places"


async def test_a_replayed_confirm_places_exactly_one_entry_with_the_derived_client_id() -> None:
    rig = await make_live_rig()
    handle = await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    assert _place_entry_count(rig) == 1

    await rig.press("CNF", handle.short_id, query_id="q-cnf-2")
    await rig.press("CNF", handle.short_id, query_id="q-cnf")  # same callback id again
    await rig.wiring.service.drain()

    assert _place_entry_count(rig) == 1, "the stored decision answers; nothing is re-sent"
    (call,) = rig.fake.calls_to("place_entry")
    assert call["kwargs"]["new_client_order_id"] == derive_client_order_id(
        plan_hash=rig.plan.plan_hash, role=OrderRole.ENTRY.value
    )
    entry = _entry_intent(rig)
    assert entry is not None and entry.client_order_id == rig.entry_id


async def test_a_cancel_after_confirm_changes_nothing() -> None:
    rig = await make_live_rig()
    handle = await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    before = (rig.approve_row(), _entry_intent(rig))

    await rig.press("CXL", handle.short_id, query_id="q-cxl")
    await rig.wiring.service.drain()

    assert (rig.approve_row(), _entry_intent(rig)) == before, "state unchanged"
    assert _place_entry_count(rig) == 1, "the CANCEL never cancels or re-sends the entry"
    assert rig.fake.calls_to("cancel_normal_order") == []


async def test_a_confirm_after_cancel_places_nothing() -> None:
    rig = await make_live_rig()
    handle = await rig.issue_and_send()
    assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
    await rig.clock.advance(30)
    rig.set_prices()
    cancelled = await rig.press("CXL", handle.short_id, query_id="q-cxl")
    assert cancelled.ok

    await rig.press("CNF", handle.short_id, query_id="q-cnf")
    await rig.wiring.service.drain()

    assert _entry_intent(rig) is None, "no entry intent was ever written"
    assert _place_entry_count(rig) == 0


async def test_two_concurrent_confirm_presses_lead_to_exactly_one_place_entry() -> None:
    rig = await make_live_rig()
    handle = await rig.issue_and_send()
    assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
    await rig.clock.advance(30)
    rig.set_prices()

    results = await asyncio.gather(
        rig.press("CNF", handle.short_id, query_id="q-cnf-a"),
        rig.press("CNF", handle.short_id, query_id="q-cnf-b"),
    )
    await rig.wiring.service.drain()

    assert len(results) == 2
    assert _place_entry_count(rig) == 1, "the consume rule lets one press win"
    entry = _entry_intent(rig)
    assert entry is not None and entry.client_order_id == rig.entry_id


async def test_two_confirm_presses_on_two_process_paths_place_exactly_once() -> None:
    """The second connection is a second execution path over the same stores (own book)."""
    rig = await make_live_rig()
    handle = await rig.issue_and_send()
    assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
    await rig.clock.advance(30)
    rig.set_prices()
    second = _second_process(rig)

    await asyncio.gather(
        rig.press("CNF", handle.short_id, query_id="q-cnf-a"),
        _press_on(rig, second, "CNF", handle.short_id, query_id="q-cnf-b"),
    )
    await rig.wiring.service.drain()
    await second.service.drain()

    assert _place_entry_count(rig) == 1, "the second path has no context and consumes nothing"


async def test_a_redelivered_approve_after_the_plan_expired_answers_the_stored_outcome() -> None:
    """G4-032: a late redelivery of APPROVE does not decide again and does not place."""
    rig = await make_live_rig()
    handle = await rig.issue_and_send()
    assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
    decided = rig.approve_row()
    await rig.clock.advance(int((rig.plan.expiry_utc - rig.clock.now()).total_seconds()) + 60)
    rig.set_prices()

    await rig.press("APR", handle.short_id, query_id="q-apr-late")
    await rig.wiring.service.drain()

    assert rig.approve_row() == decided, "the stored decision is unchanged"
    assert _place_entry_count(rig) == 0


# --------------------------------------------------------------------------- #
# Task 2: restarts.
# --------------------------------------------------------------------------- #


async def test_a_restart_between_approve_and_confirm_needs_a_fresh_confirm() -> None:
    rig = await make_live_rig()
    handle = await rig.issue_and_send()
    assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
    approval_id = rig.approve_row().approval_id

    await rig.clock.advance(30)
    second = _second_process(rig)
    expired = second.confirm_flow.expire_on_restart(rig.clock.now())

    assert expired == [approval_id]
    (event,) = rig.stores.journal_of_type("DEMO_CONFIRM_EXPIRED")
    assert json.loads(event.payload_json)["reason"] == "RUNTIME_RESTART"
    rig.set_prices()
    old = await _press_on(rig, second, "CNF", handle.short_id, query_id="q-cnf-old")
    # The first process' own book is gone with it: its press must not place either.
    await second.service.drain()
    assert not old.ok, "the old card needs a fresh CONFIRM"
    assert _entry_intent(rig) is None
    assert _place_entry_count(rig) == 0

    # A replayed APPROVE after the restart changes nothing.
    await _press_on(rig, second, "APR", handle.short_id, query_id="q-apr-after")
    await second.service.drain()
    assert _approve_rows(rig) and _approve_rows(rig)[0].result is ApprovalResult.APPROVED
    assert _place_entry_count(rig) == 0


async def test_a_restart_after_an_ambiguous_entry_stays_unknown_and_is_never_re_sent() -> None:
    rig = await make_live_rig()
    rig.fake.fail_next("place_entry", RuntimeError("timeout"))  # accepted, result lost
    handle = await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    entry = _entry_intent(rig)
    assert entry is not None and entry.intent_status is ExecutionIntentStatus.UNKNOWN
    assert rig.safe_mode.in_safe_mode
    assert _place_entry_count(rig) == 1

    restart = await _restart(rig, crash_in_safe_mode=None)
    await restart.recover()
    second = _second_process(rig)
    second.confirm_flow.expire_on_restart(rig.clock.now())
    replay = await _press_on(rig, second, "CNF", handle.short_id, query_id="q-cnf-replay")
    await second.service.drain()
    await restart.coordinator.step()

    assert not replay.ok, "no context after the restart"
    after = _entry_intent(rig)
    assert after is not None and after.intent_status is ExecutionIntentStatus.UNKNOWN
    assert after.client_order_id == rig.entry_id, "the same derived id before and after"
    assert restart.safe_mode.in_safe_mode
    assert _place_entry_count(rig) == 1, "an UNKNOWN entry is never re-sent (D080)"


async def test_a_restart_after_an_acknowledged_entry_rebuilds_it_and_a_fill_gets_its_stop() -> None:
    rig = await make_live_rig()
    handle = await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    assert _place_entry_count(rig) == 1
    original = _entry_intent(rig)
    assert original is not None and original.client_order_id == rig.entry_id

    restart = await _restart(rig, crash_in_safe_mode=None)
    await restart.recover()
    second = _second_process(rig)
    second.confirm_flow.expire_on_restart(rig.clock.now())
    replay = await _press_on(rig, second, "CNF", handle.short_id, query_id="q-cnf-replay")
    await second.service.drain()
    assert not replay.ok
    assert _place_entry_count(rig) == 1, "a replayed callback after the restart changes nothing"

    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    assert restart.route(rig.trade_frame()).fills == 1
    await restart.coordinator.step()
    await rig.clock.advance(1)
    await restart.coordinator.step()

    view = restart.coordinator.protection_of(rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.PROTECTED
    (stop,) = rig.fake.calls_to("place_algo_protective")
    assert stop["kwargs"]["client_algo_id"] == derive_algo_client_id(
        plan_hash=rig.plan.plan_hash, role=OrderRole.STOP_LOSS.value
    )
    after = _entry_intent(rig)
    assert after is not None and after.client_order_id == original.client_order_id
    assert _place_entry_count(rig) == 1, "total place_entry calls across both processes = 1"
