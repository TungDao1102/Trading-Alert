"""A REST-gate refusal at any read of the emergency closer is a NOT_SENT close (plan 20-27, WR-A2).

20-REVIEW WR-A2: `RestRateLimitGate.check()` takes no category, so while a 418 ban or a 429 pause
is active EVERY signed call raises a `PreSendRefusal`, the position read of the closer included.
That read is the first gated call of `close_position`. The generic `except Exception` there used
to turn the refusal into `POSITION_READ_FAILED` (SAFE_MODE `EMERGENCY_CLOSE_FAILED`), so the
durable `CLOSE_NOT_SENT` pending row of plan 20-14 and the not-sent alert existed only if the gate
flipped between the read and the POST.

Every refusal below is a real gate refusal class (`RateLimitPauseActive`, `RateLimitBanActive`,
`GateNotRestored`), classified by exception TYPE only. Fakes only: the Phase 19 fake exchange,
the in-memory pending store and virtual time. Nothing here is [DEMO].
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from src.adapters.binance_ratelimit_gate import (
    GateNotRestored,
    RateLimitBanActive,
    RateLimitPauseActive,
)
from src.domain.exchange_errors import PreSendRefusal
from src.execution.pending_actions import PendingKind, PendingState
from src.execution.protection import ProtectionState

from tests.support.pending_action_fakes import InMemoryPendingActionStore
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    TEST_ONLY_SYMBOL,
    ProtectionRig,
    make_rig,
)

D = Decimal
ENTRY_PRICE = D("60000")


async def _closer_rig(store: InMemoryPendingActionStore | None = None) -> ProtectionRig:
    """The real closer over the fake exchange holding a long position of 0.004 (no coordinator)."""
    rig = await make_rig(real_closer=True, pending_actions=store, place_entry=False, register=False)
    rig.fake._apply_position_delta(TEST_ONLY_SYMBOL, D("0.004"), ENTRY_PRICE)  # noqa: SLF001
    return rig


async def _close(rig: ProtectionRig) -> bool:
    return await rig.closer.close_position(entry=rig.entry, reason="CLOSE_REQUIRED")


def _assert_not_sent(rig: ProtectionRig, store: InMemoryPendingActionStore) -> None:
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "NOT_SENT"
    assert rig.closer.last_result.reason == "PRE_SEND_REFUSED"
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("EMERGENCY_CLOSE_NOT_SENT", "PRE_SEND_REFUSED")
    ]
    # A refusal is not a failure of the close: no EMERGENCY_CLOSE_FAILED SAFE_MODE from it.
    assert rig.safe_mode.entered_reasons == []
    rows = store.rows_of(PendingKind.CLOSE_NOT_SENT)
    assert len(rows) == 1
    assert rows[0].state is PendingState.PENDING
    assert rows[0].plan_hash == TEST_ONLY_PLAN_HASH
    assert rows[0].block_count == 1
    # Nothing was sent.
    assert rig.fake.calls_to("place_market_close") == []


@pytest.mark.parametrize(
    "refusal",
    [RateLimitPauseActive(60), RateLimitBanActive(900), GateNotRestored("GATE_NOT_RESTORED", 1)],
    ids=["pause_429", "ban_418", "gate_not_restored"],
)
async def test_a_gate_that_refuses_the_position_read_is_a_not_sent_close(
    refusal: PreSendRefusal,
) -> None:
    store = InMemoryPendingActionStore()
    rig = await _closer_rig(store)
    rig.fake.fail_next("snapshot_positions", refusal)

    closed = await _close(rig)

    assert closed is False
    _assert_not_sent(rig, store)
    row = store.rows_of(PendingKind.CLOSE_NOT_SENT)[0]
    assert row.gate_reason == getattr(refusal, "reason", None)
    assert rig.fake.positions[TEST_ONLY_SYMBOL] == D("0.004")  # no claim of safety


async def test_the_not_sent_row_is_resolved_when_a_later_call_gets_through() -> None:
    store = InMemoryPendingActionStore()
    rig = await _closer_rig(store)
    rig.fake.fail_next("snapshot_positions", RateLimitPauseActive(60))
    assert await _close(rig) is False

    closed = await _close(rig)  # the gate is open again

    assert closed is True
    assert rig.fake.positions[TEST_ONLY_SYMBOL] == D("0")
    row = store.rows_of(PendingKind.CLOSE_NOT_SENT)[0]
    assert row.state is PendingState.RESOLVED


async def test_a_gate_that_refuses_the_lot_filter_read_is_a_not_sent_close() -> None:
    store = InMemoryPendingActionStore()
    rig = await _closer_rig(store)
    rig.fake.fail_next("symbol_lot_filters", RateLimitPauseActive(60))

    closed = await _close(rig)

    assert closed is False
    _assert_not_sent(rig, store)


async def test_a_gate_that_refuses_the_attempt_discovery_is_a_not_sent_close() -> None:
    store = InMemoryPendingActionStore()
    rig = await _closer_rig(store)
    rig.fake.fail_next("query_order_by_client", RateLimitPauseActive(60))

    closed = await _close(rig)

    assert closed is False
    _assert_not_sent(rig, store)


async def test_a_gate_that_refuses_the_position_reread_after_a_part_is_a_not_sent_close() -> None:
    store = InMemoryPendingActionStore()
    rig = await _closer_rig(store)
    original = rig.fake.snapshot_positions
    calls = {"n": 0}

    async def refuse_the_second_read(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RateLimitPauseActive(60)
        return await original(**kwargs)

    rig.fake.snapshot_positions = refuse_the_second_read  # type: ignore[method-assign]

    closed = await _close(rig)

    assert closed is False
    assert len(rig.fake.calls_to("place_market_close")) == 1  # the part before the refusal
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "NOT_SENT"
    assert rig.closer.last_result.parts_sent == 1
    assert rig.safe_mode.entered_reasons == []
    assert len(store.rows_of(PendingKind.CLOSE_NOT_SENT)) == 1


async def test_a_non_refusal_failure_of_the_position_read_is_still_a_failed_close() -> None:
    """Only the exception TYPE decides: any other failure keeps its POSITION_READ_FAILED path."""
    store = InMemoryPendingActionStore()
    rig = await _closer_rig(store)
    # A message that talks about a rate-limit pause but is not a PreSendRefusal.
    rig.fake.fail_next("snapshot_positions", RuntimeError("rate limit pause active, nothing sent"))

    closed = await _close(rig)

    assert closed is False
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "CLOSE_FAILED"
    assert rig.closer.last_result.reason == "POSITION_READ_FAILED"
    assert rig.safe_mode.entered_reasons == ["EMERGENCY_CLOSE_FAILED"]
    assert store.rows_of(PendingKind.CLOSE_NOT_SENT) == ()


async def test_a_refusal_with_a_message_the_classifier_never_reads() -> None:
    class SilentRefusal(PreSendRefusal):
        """A refusal subclass that carries no reason attribute and an unhelpful message."""

    store = InMemoryPendingActionStore()
    rig = await _closer_rig(store)
    rig.fake.fail_next("snapshot_positions", SilentRefusal("x"))

    assert await _close(rig) is False

    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "NOT_SENT"
    assert len(store.rows_of(PendingKind.CLOSE_NOT_SENT)) == 1


# --------------------------------------------------------------------------- #
# Through the coordinator: CLOSE_REQUIRED, then a gate that refuses the closer's first read.
# --------------------------------------------------------------------------- #


async def test_the_coordinator_reports_close_not_sent_when_the_gate_refuses_first() -> None:
    store = InMemoryPendingActionStore()
    rig = await make_rig(real_closer=True, pending_actions=store)
    rig.fake.reject_next_algo(-2021)  # a definitive stop rejection: CLOSE_REQUIRED at once
    rig.fake.fail_next("snapshot_positions", RateLimitPauseActive(60))
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()

    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.CLOSE_FAILED
    assert protection.last_reason == "CLOSE_NOT_SENT"
    rows = store.rows_of(PendingKind.CLOSE_NOT_SENT)
    assert len(rows) == 1 and rows[0].state is PendingState.PENDING
    assert ("EMERGENCY_CLOSE_NOT_SENT", "PRE_SEND_REFUSED") in [
        (a.event, a.reason) for a in rig.alerts.alerts
    ]
    assert rig.fake.positions[TEST_ONLY_SYMBOL] == D("0.004")
    assert rig.coordinator.blocks_new_entries() is True

    await rig.coordinator.step()  # the gate is open: the close goes out and the plan ends FLAT

    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None and protection.state is ProtectionState.FLAT
    assert store.rows_of(PendingKind.CLOSE_NOT_SENT)[0].state is PendingState.RESOLVED
