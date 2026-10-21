"""Pending protective actions: the durable record of a gate-refused stop, entry cancel or close.

Phase 20, plan 20-14 (D-19, Q4 owner decision 2026-10-20, D-16, D-18). Every test runs against
the Phase 19 fake exchange, the in-memory pending store (same semantics as the PostgreSQL
store), a real `LocalSpill` in a temporary directory and virtual time. Nothing sleeps, nothing
touches a network, and no number here is a ratified limit (the deadlines are the TEST_ONLY
values of tests/support/execution_limits.py).

What these tests do NOT claim: that a position always has a stop under every rate-limit
condition. While the exchange forbids sending, the plan stays in its blocking state; the pending
row is only a durable record of the intent. The 429/418 semantics are [DOC], not [DEMO].
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.adapters.binance_ratelimit_gate import RateLimitPauseActive
from src.execution.pending_actions import (
    PendingAction,
    PendingKind,
    PendingState,
    pending_id_for,
)
from src.execution.protection import ProtectionState
from src.ops.spill import LocalSpill

from tests.support.pending_action_fakes import InMemoryPendingActionStore
from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal
T0 = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)
PAUSE_REASON = "RATE_LIMIT_PAUSE_429"


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection.state


async def _advance_ms(rig: ProtectionRig, milliseconds: int) -> None:
    await rig.clock.advance(milliseconds / 1000)


# --------------------------------------------------------------------------- #
# Task 1 (tracer): a gate-refused stop leaves a durable, payload-free STOP_NOT_SENT row.
# --------------------------------------------------------------------------- #


async def test_gate_refused_stop_leaves_one_pending_row_and_one_spill_record(
    tmp_path: Path,
) -> None:
    store = InMemoryPendingActionStore()
    spill = LocalSpill(tmp_path / "spill")
    rig = await make_rig(pending_actions=store, spill=spill)
    rig.fake.fail_next("place_algo_protective", RateLimitPauseActive(30))
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()

    rows = store.all_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.kind is PendingKind.STOP_NOT_SENT
    assert row.state is PendingState.PENDING
    assert row.gate_reason == PAUSE_REASON
    assert row.block_count == 1
    assert row.plan_hash == TEST_ONLY_PLAN_HASH
    assert row.retry_after_until_utc == rig.clock.now() + timedelta(seconds=30)
    assert row.first_blocked_at_utc == row.last_blocked_at_utc == rig.clock.now()

    # The intent was written ahead to the local spill, with no price, quantity or side.
    spilled = spill.pending()
    assert len(spilled) == 1
    body = json.loads(spilled[0].event.payload_json)
    assert body["pending_kind"] == "STOP_NOT_SENT"
    assert body["gate_reason"] == PAUSE_REASON
    assert not {"price", "quantity", "side", "trigger_price"} & set(body)

    # The existing journal row is still written, and the plan stays blocking.
    assert len(rig.journal.by_type("STOP_NOT_SENT")) == 1
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.safe_mode.entered_reasons == []


async def test_a_second_refused_step_bumps_the_same_row_and_spills_once(tmp_path: Path) -> None:
    store = InMemoryPendingActionStore()
    spill = LocalSpill(tmp_path / "spill")
    rig = await make_rig(pending_actions=store, spill=spill)
    rig.fake.fail_next("place_algo_protective", RateLimitPauseActive(30))
    rig.fake.fail_next("place_algo_protective", RateLimitPauseActive(20))
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    first = store.all_rows()[0]

    await _advance_ms(rig, 1000)
    await rig.coordinator.step()

    rows = store.all_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.pending_id == first.pending_id
    assert row.state is PendingState.PENDING
    assert row.block_count == 2
    assert row.first_blocked_at_utc == first.first_blocked_at_utc
    assert row.last_blocked_at_utc == first.last_blocked_at_utc + timedelta(seconds=1)
    assert row.retry_after_until_utc == rig.clock.now() + timedelta(seconds=20)
    # One spill record per episode, not one per refused step.
    assert len(spill.pending()) == 1


def test_a_pending_action_has_no_price_quantity_or_side_field() -> None:
    names = {f.name for f in dataclasses.fields(PendingAction)}
    assert not {"price", "quantity", "side", "trigger_price", "payload"} & names
    assert names == {
        "pending_id",
        "plan_hash",
        "trade_plan_id",
        "approval_id",
        "symbol",
        "kind",
        "state",
        "gate_reason",
        "first_blocked_at_utc",
        "last_blocked_at_utc",
        "block_count",
        "retry_after_until_utc",
        "resolved_at_utc",
        "resolution_note",
    }


def test_the_pending_id_is_deterministic_per_plan_kind_and_episode() -> None:
    one = pending_id_for("a" * 64, PendingKind.STOP_NOT_SENT, opened_at_utc=T0)
    assert one == pending_id_for("a" * 64, PendingKind.STOP_NOT_SENT, opened_at_utc=T0)
    assert one != pending_id_for("a" * 64, PendingKind.CLOSE_NOT_SENT, opened_at_utc=T0)
    assert one != pending_id_for("b" * 64, PendingKind.STOP_NOT_SENT, opened_at_utc=T0)
    assert one != pending_id_for(
        "a" * 64, PendingKind.STOP_NOT_SENT, opened_at_utc=T0 + timedelta(seconds=1)
    )
    assert len(one) <= 128


def _record(store: InMemoryPendingActionStore, kind: PendingKind, now: datetime) -> PendingAction:
    return store.record_blocked(
        plan_hash="c" * 64,
        trade_plan_id="plan-1",
        approval_id="approval-1",
        symbol="BTCUSDT",
        kind=kind,
        gate_reason=PAUSE_REASON,
        retry_after_until_utc=None,
        now_utc=now,
    )


def test_resolve_and_supersede_touch_only_the_open_row_of_that_kind() -> None:
    store = InMemoryPendingActionStore()
    stop = _record(store, PendingKind.STOP_NOT_SENT, T0)
    _record(store, PendingKind.CLOSE_NOT_SENT, T0)

    done = store.supersede(
        plan_hash="c" * 64,
        kind=PendingKind.STOP_NOT_SENT,
        note="CLOSE_REQUIRED_BY_POLICY",
        now_utc=T0 + timedelta(seconds=5),
    )

    assert done is not None
    assert done.pending_id == stop.pending_id
    assert done.state is PendingState.SUPERSEDED
    assert done.resolution_note == "CLOSE_REQUIRED_BY_POLICY"
    assert [r.kind for r in store.list_open()] == [PendingKind.CLOSE_NOT_SENT]
    # Nothing open any more for that kind: a second call is a no-op.
    assert (
        store.resolve(plan_hash="c" * 64, kind=PendingKind.STOP_NOT_SENT, note="X", now_utc=T0)
        is None
    )


def test_a_pending_action_refuses_a_malformed_value() -> None:
    good = _record(InMemoryPendingActionStore(), PendingKind.STOP_NOT_SENT, T0)
    with pytest.raises(ValueError):
        dataclasses.replace(good, first_blocked_at_utc=datetime(2026, 10, 21, 12, 0, 0))
    with pytest.raises(ValueError):
        dataclasses.replace(good, block_count=0)
    with pytest.raises(ValueError):
        dataclasses.replace(good, gate_reason="has a space")
    with pytest.raises(ValueError):
        dataclasses.replace(good, state=PendingState.RESOLVED)  # no resolved_at / note
