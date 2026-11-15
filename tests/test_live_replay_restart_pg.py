"""Replay and restart matrix on PostgreSQL across two process instances (plan 24-28; D-09, D-20).

The scenarios of `tests/test_live_replay_restart.py` on the real stores at the migration head:
the rig is `make_live_pg_rig` (the fake exchange, bot and virtual clock at the edges; the
PostgreSQL stores of `build_pg_stores` under everything else). A second process is a second engine
over the same database, so its presses are separate connections and the database's consume rule
(the ENTRY intent written ahead of `place_entry`) decides. Every test asserts the count of
`place_entry` calls on the fake as exactly 0 or exactly 1.

The two concurrent presses are dispatched with `asyncio.gather`; the store calls are synchronous,
so on one loop they interleave only at the awaits. The row-level race of two threads on two
engines is proven by `tests/test_execution_exactly_once_pg.py`.

Skips without TEST_DATABASE_URL; fails under TRADING_CI_STRICT=1 (`tests/pg_support.py`).
TEST_ONLY: the prices, the snapshot and the TTL are the rig's made-up values.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

import pytest
from src.domain.enums import ApprovalResult, ExecutionIntentStatus, OrderRole
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.protection import ProtectionState
from src.live.startup import protection_correlation

from tests.support.live_pg_rig import PgConnection, make_live_pg_rig, pg_stores_on
from tests.support.live_rig import LiveRig, forbid_real_sleep
from tests.test_live_replay_restart import (
    _approve_rows,
    _entry_intent,
    _place_entry_count,
    _press_on,
    _second_process,
)
from tests.test_live_restart_rehydrate import Restart

D = Decimal


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


class PgRestart(Restart):
    """The objects of the second process, reading the restorable entries from PostgreSQL."""

    def _reader_for(self, rig: LiveRig) -> Any:
        return rig.intents  # PgExecutionStateStore: restorable_entries and get_intent

    def _events_of(self, correlation: str) -> list[Any]:
        events: list[Any] = []
        for key in (correlation, protection_correlation(correlation)):
            events.extend(self.rig.journal.list_by_correlation(key))
        return events


async def _pg_restart(rig: LiveRig, connection: PgConnection) -> PgRestart:
    """Persist run 1's SAFE_MODE state through PostgreSQL and build the new process."""
    now = rig.clock.now()
    store = connection.store_set.safe_mode_state
    store.save(rig.safe_mode.state_snapshot(), now_utc=now)
    placement = await rig.inputs.for_plan(rig.approve_row(), rig.plan, now)
    return PgRestart(rig, placement.live_context.plan_constraint_snapshot, store)


def _second(rig: LiveRig, connection: PgConnection) -> Any:
    return _second_process(
        rig,
        stores=connection.view,
        intents=connection.store_set.execution_state,
        journal=connection.store_set.journal,
    )


# --------------------------------------------------------------------------- #
# Replays and concurrent presses.
# --------------------------------------------------------------------------- #


async def test_a_replayed_approve_keeps_one_decision_and_places_nothing(pg_db: str) -> None:
    with pg_stores_on(pg_db) as one:
        rig = await make_live_pg_rig(one)
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


async def test_a_replayed_confirm_places_exactly_one_entry_with_the_derived_client_id(
    pg_db: str,
) -> None:
    with pg_stores_on(pg_db) as one:
        rig = await make_live_pg_rig(one)
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


async def test_a_cancel_after_confirm_changes_nothing(pg_db: str) -> None:
    with pg_stores_on(pg_db) as one:
        rig = await make_live_pg_rig(one)
        handle = await rig.approve_and_confirm()
        await rig.wiring.service.drain()
        before = (rig.approve_row(), _entry_intent(rig))

        await rig.press("CXL", handle.short_id, query_id="q-cxl")
        await rig.wiring.service.drain()

        assert (rig.approve_row(), _entry_intent(rig)) == before, "state unchanged"
        assert _place_entry_count(rig) == 1, "the CANCEL never cancels or re-sends the entry"
        assert rig.fake.calls_to("cancel_normal_order") == []


async def test_a_confirm_after_cancel_places_nothing(pg_db: str) -> None:
    with pg_stores_on(pg_db) as one:
        rig = await make_live_pg_rig(one)
        handle = await rig.issue_and_send()
        assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
        await rig.clock.advance(30)
        rig.set_prices()
        assert (await rig.press("CXL", handle.short_id, query_id="q-cxl")).ok

        await rig.press("CNF", handle.short_id, query_id="q-cnf")
        await rig.wiring.service.drain()

        assert _entry_intent(rig) is None, "no entry intent was ever written"
        assert _place_entry_count(rig) == 0


async def test_two_concurrent_confirm_presses_lead_to_exactly_one_place_entry(
    pg_db: str,
) -> None:
    with pg_stores_on(pg_db) as one:
        rig = await make_live_pg_rig(one)
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


async def test_two_confirm_presses_on_two_processes_place_exactly_once(pg_db: str) -> None:
    """The second connection is a second engine and execution path (its own confirm book)."""
    with pg_stores_on(pg_db) as one, pg_stores_on(pg_db) as other:
        rig = await make_live_pg_rig(one)
        handle = await rig.issue_and_send()
        assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
        await rig.clock.advance(30)
        rig.set_prices()
        second = _second(rig, other)

        await asyncio.gather(
            rig.press("CNF", handle.short_id, query_id="q-cnf-a"),
            _press_on(rig, second, "CNF", handle.short_id, query_id="q-cnf-b"),
        )
        await rig.wiring.service.drain()
        await second.service.drain()

        assert _place_entry_count(rig) == 1, "the second path has no context and consumes nothing"
        entry = other.store_set.execution_state.get_entry(approval_id=rig.approve_row().approval_id)
        assert entry is not None and entry.client_order_id == rig.entry_id, "visible to process 2"


async def test_a_redelivered_approve_after_the_plan_expired_answers_the_stored_outcome(
    pg_db: str,
) -> None:
    with pg_stores_on(pg_db) as one:
        rig = await make_live_pg_rig(one)
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
# Restarts.
# --------------------------------------------------------------------------- #


async def test_a_restart_between_approve_and_confirm_places_nothing_and_needs_a_fresh_card(
    pg_db: str,
) -> None:
    with pg_stores_on(pg_db) as one, pg_stores_on(pg_db) as other:
        rig = await make_live_pg_rig(one)
        handle = await rig.issue_and_send()
        assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
        approval_id = rig.approve_row().approval_id

        await rig.clock.advance(30)
        second = _second(rig, other)
        expired = second.confirm_flow.expire_on_restart(rig.clock.now())

        assert expired == [approval_id]
        (event,) = other.view.journal_of_type("DEMO_CONFIRM_EXPIRED")
        assert json.loads(event.payload_json)["reason"] == "RUNTIME_RESTART"
        rig.set_prices()
        old = await _press_on(rig, second, "CNF", handle.short_id, query_id="q-cnf-old")
        await second.service.drain()
        assert not old.ok, "the old card needs a fresh CONFIRM"
        assert _entry_intent(rig) is None
        assert _place_entry_count(rig) == 0

        await _press_on(rig, second, "APR", handle.short_id, query_id="q-apr-after")
        await second.service.drain()
        assert _approve_rows(rig) and _approve_rows(rig)[0].result is ApprovalResult.APPROVED
        assert _place_entry_count(rig) == 0


async def test_a_restart_after_an_ambiguous_entry_stays_unknown_and_is_never_re_sent(
    pg_db: str,
) -> None:
    with pg_stores_on(pg_db) as one, pg_stores_on(pg_db) as other:
        rig = await make_live_pg_rig(one)
        rig.fake.fail_next("place_entry", RuntimeError("timeout"))  # accepted, result lost
        handle = await rig.approve_and_confirm()
        await rig.wiring.service.drain()
        entry = _entry_intent(rig)
        assert entry is not None and entry.intent_status is ExecutionIntentStatus.UNKNOWN
        assert rig.safe_mode.in_safe_mode
        assert _place_entry_count(rig) == 1

        restart = await _pg_restart(rig, other)
        await restart.recover()
        second = _second(rig, other)
        second.confirm_flow.expire_on_restart(rig.clock.now())
        replay = await _press_on(rig, second, "CNF", handle.short_id, query_id="q-cnf-replay")
        await second.service.drain()
        await restart.coordinator.step()

        assert not replay.ok, "no context after the restart"
        after = other.store_set.execution_state.get_entry(approval_id=rig.approve_row().approval_id)
        assert after is not None and after.intent_status is ExecutionIntentStatus.UNKNOWN
        assert after.client_order_id == rig.entry_id, "the same derived id before and after"
        assert restart.safe_mode.in_safe_mode, "SAFE_MODE was read back from PostgreSQL"
        assert _place_entry_count(rig) == 1, "an UNKNOWN entry is never re-sent (D080)"


async def test_a_restart_after_an_acknowledged_entry_rebuilds_it_and_a_fill_gets_its_stop(
    pg_db: str,
) -> None:
    with pg_stores_on(pg_db) as one, pg_stores_on(pg_db) as other:
        rig = await make_live_pg_rig(one)
        handle = await rig.approve_and_confirm()
        await rig.wiring.service.drain()
        assert _place_entry_count(rig) == 1
        original = _entry_intent(rig)
        assert original is not None and original.client_order_id == rig.entry_id

        restart = await _pg_restart(rig, other)
        await restart.recover()
        second = _second(rig, other)
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
