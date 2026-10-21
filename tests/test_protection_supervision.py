"""Stop supervision after PROTECTED, COMPLETE and TP_UNAVAILABLE (plan 20-09; D-07, D-06, D077).

Before this plan a plan past PROTECTED never read its stop again: a stop cancelled or lost while
the position stayed open was invisible. Now each step of PROTECTED, COMPLETE and TP_UNAVAILABLE
reads the stop by its deterministic id. A stop that reads ABSENT or NOT_ACTIVE is decided by the
position as in D077 (the existing ``_on_stop_lost``): confirmed exposure is CLOSE_REQUIRED (B4) and
a reduce-only MARKET close, an unreadable position is UNPROTECTED with ``stop_lost_at`` set once,
flat on two reads with the entry terminal is FLAT. A stop confirmed ACTIVE and later lost is never
re-placed.

Every test runs offline against the stateful Phase 19 fake exchange, the real
``MarketEmergencyCloser`` and virtual time. The deadlines are the TEST_ONLY values of
``tests/support/execution_limits.py``, never a ratified number. Binance's behavior for a
``closePosition`` stop when the position closes (assumption A3) is NOT observed: both outcomes
(auto-cancelled, or left as an orphan and swept) are handled and tested against the fake [DESIGN];
no [DEMO] claim.
"""

from __future__ import annotations

import json
from collections import deque
from decimal import Decimal
from typing import Any

import pytest
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import PlanProtection, ProtectionState

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal

FULL_FILL = D("0.010")
# The TEST_ONLY max_unprotected_ms of tests/support/execution_limits.py, in milliseconds.
MAX_UNPROTECTED_MS = 7777


def _view(rig: ProtectionRig) -> PlanProtection:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection


def _transitions(rig: ProtectionRig) -> list[tuple[str, str, str]]:
    out = []
    for event in rig.journal.calls:
        if event.event_type == "PROTECTION_TRANSITION":
            body = json.loads(event.payload_json)
            out.append((body["from"], body["to"], body["reason"]))
    return out


def _states(rig: ProtectionRig) -> list[str]:
    return [to for _, to, _ in _transitions(rig)]


def _stop_reads(rig: ProtectionRig) -> int:
    """How many REST queries of the STOP_LOSS leg (by its deterministic id) were made."""
    return sum(
        1
        for call in rig.fake.calls_to("query_algo_order_by_client")
        if call["kwargs"]["client_algo_id"] == rig.stop_id
    )


def _close_required_alerts(rig: ProtectionRig) -> list[str]:
    return [a.reason for a in rig.alerts.alerts if a.event == "CLOSE_REQUIRED"]


async def _to_protected(rig: ProtectionRig, quantity: Decimal = FULL_FILL) -> None:
    """The entry fills by `quantity`; two steps later the stop is confirmed and the entry ended."""
    rig.coordinator.fill_sink(rig.stream_fill(quantity))
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.UNPROTECTED
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.PROTECTED


def _script_position_read_failures(rig: ProtectionRig, count: int) -> None:
    """The next `count` position reads raise (the stop reads stay real)."""
    script = deque([True] * count)
    original = rig.fake.snapshot_positions

    async def scripted(**kwargs: Any) -> Any:
        if script and script.popleft():
            rig.fake._record_call("snapshot_positions", kwargs)
            raise RuntimeError("scripted position read failure")
        return await original(**kwargs)

    rig.fake.snapshot_positions = scripted  # type: ignore[method-assign]


class StopPlacementGuard:
    """RISK-03 (never wider): every STOP_LOSS placement carries the plan stop and its own id.

    Wraps ``place_algo_protective`` of the fake. A violation is recorded, not raised: the
    coordinator step catches any exception of one plan, so a raise inside the adapter would hide.
    """

    def __init__(self, rig: ProtectionRig) -> None:
        self.violations: list[str] = []
        self.stop_placements = 0
        original = rig.fake.place_algo_protective

        async def checked(**kwargs: Any) -> Any:
            if kwargs.get("type") == "STOP_MARKET":
                self.stop_placements += 1
                if kwargs["client_algo_id"] != rig.stop_id:
                    self.violations.append("client_algo_id")
                if kwargs["trigger_price"] != rig.entry.sl_trigger_price:
                    self.violations.append("trigger_price")
                if kwargs["close_position"] is not True:
                    self.violations.append("close_position")
            return await original(**kwargs)

        rig.fake.place_algo_protective = checked  # type: ignore[method-assign]

    def assert_clean(self) -> None:
        assert self.violations == []


async def _checked_rig(**kwargs: Any) -> tuple[ProtectionRig, StopPlacementGuard]:
    rig = await make_rig(real_closer=True, **kwargs)
    return rig, StopPlacementGuard(rig)


async def _to_state(rig: ProtectionRig, state: ProtectionState) -> None:
    """Drive the plan to one of the three supervised states."""
    if state is ProtectionState.TP_UNAVAILABLE:
        await _to_protected(rig, D("0.001"))  # TP1 cannot be sized from 0.001 (O-03)
        await rig.coordinator.step()
    else:
        await _to_protected(rig)
        if state is ProtectionState.COMPLETE:
            await rig.coordinator.step()
    assert _view(rig).state is state


# --------------------------------------------------------------------------- #
# Task 1 (tracer): a PROTECTED plan whose stop is cancelled with exposure open.
# --------------------------------------------------------------------------- #


async def test_protected_stop_cancelled_with_exposure_closes_and_never_replaces() -> None:
    rig, guard = await _checked_rig()
    await _to_protected(rig)
    placements_before = len(rig.fake.calls_to("place_algo_protective"))
    assert placements_before == 1

    rig.fake.cancel_algo(rig.stop_id)  # the owner or an outage cancels the confirmed stop
    detected_at = rig.clock.now()
    reads_before = _stop_reads(rig)

    await rig.coordinator.step()

    assert _stop_reads(rig) - reads_before == 1, "one supervision read of the stop by its id"
    assert _transitions(rig)[-1] == ("PROTECTED", "CLOSE_REQUIRED", "B4_FILL_AFTER_STOP")
    assert _view(rig).stop_lost_at_utc == detected_at
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    assert _close_required_alerts(rig) == ["B4_FILL_AFTER_STOP"]
    assert [c["kwargs"]["quantity"] for c in rig.fake.calls_to("place_market_close")] == [FULL_FILL]
    assert rig.fake.calls_to("place_market_close")[0]["kwargs"]["side"] == "SELL"

    for _ in range(3):
        await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.FLAT
    assert len(rig.fake.calls_to("place_algo_protective")) == placements_before
    assert "PROTECTED" not in _states(rig)[_states(rig).index("CLOSE_REQUIRED") :]
    assert _close_required_alerts(rig) == ["B4_FILL_AFTER_STOP"]
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert guard.stop_placements == 1
    guard.assert_clean()


# --------------------------------------------------------------------------- #
# Task 2: the other D077 outcomes and the RISK-03 price invariant.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "state",
    [ProtectionState.PROTECTED, ProtectionState.COMPLETE, ProtectionState.TP_UNAVAILABLE],
)
async def test_a_cancelled_stop_with_exposure_is_b4_in_every_supervised_state(
    state: ProtectionState,
) -> None:
    rig, guard = await _checked_rig()
    await _to_state(rig, state)
    exposure = rig.fake.positions["BTCUSDT"]
    assert exposure != D("0")
    rig.fake.cancel_algo(rig.stop_id)

    await rig.coordinator.step()

    assert _transitions(rig)[-1] == (state.value, "CLOSE_REQUIRED", "B4_FILL_AFTER_STOP")
    assert [c["kwargs"]["quantity"] for c in rig.fake.calls_to("place_market_close")] == [exposure]
    for _ in range(3):
        await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.FLAT
    assert _close_required_alerts(rig) == ["B4_FILL_AFTER_STOP"]
    assert guard.stop_placements == 1, "a confirmed stop that was lost is never re-placed"
    guard.assert_clean()


@pytest.mark.parametrize("how", ["stop_left_as_orphan", "stop_auto_cancelled"])
async def test_complete_tp2_triggered_flat_on_two_reads_ends_flat_without_a_close(how: str) -> None:
    """A3 / G4-035 both ways: the exchange auto-cancels the closePosition stop, or leaves it.

    Binance behavior is NOT observed (probe 6); the fake offers both outcomes.
    """
    rig, guard = await _checked_rig()
    await _to_state(rig, ProtectionState.COMPLETE)
    tp2 = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_2")
    rig.fake.trigger_stop(tp2)  # a closePosition take profit consumed the whole position
    if how == "stop_auto_cancelled":
        rig.fake.open_algos.pop(rig.stop_id)  # gone from the book and from the history (ABSENT)
    assert rig.fake.positions["BTCUSDT"] == D("0")

    await rig.coordinator.step()

    assert _view(rig).state is ProtectionState.FLAT
    assert _transitions(rig)[-1] == ("COMPLETE", "FLAT", "POSITION_CLOSED")
    flat = [
        json.loads(e.payload_json)
        for e in rig.journal.calls
        if e.event_type == "PROTECTION_TRANSITION"
    ][-1]
    assert flat["evidence"] == "REST_FLAT_TWO_READS_ENTRY_TERMINAL"
    assert rig.fake.open_algos == {}, "the sweep ran: no leg is left on the book"
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.alerts.alerts == []
    assert rig.safe_mode.entered_reasons == []
    assert rig.coordinator.blocks_new_entries() is False
    guard.assert_clean()
    assert guard.stop_placements == 1


async def test_tp_unavailable_stop_not_active_position_unreadable_escalates_from_stop_lost_at() -> (
    None
):
    rig, guard = await _checked_rig()
    await _to_state(rig, ProtectionState.TP_UNAVAILABLE)
    rig.fake.cancel_algo(rig.stop_id)  # NOT_ACTIVE on the next read
    _script_position_read_failures(rig, 500)  # no position read succeeds from here on
    lost_at = rig.clock.now()

    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.UNPROTECTED
    assert _transitions(rig)[-1] == (
        "TP_UNAVAILABLE",
        "UNPROTECTED",
        "STOP_LOST_AFTER_PROTECTED",
    )
    assert _view(rig).stop_lost_at_utc == lost_at
    assert rig.coordinator.blocks_new_entries() is True

    # stop_lost_at is set once and never moves; the lost stop is not read again.
    stop_reads = _stop_reads(rig)
    for _ in range(3):
        await rig.clock.advance(1.0)
        await rig.coordinator.step()
        assert _view(rig).state is ProtectionState.UNPROTECTED
        assert _view(rig).stop_lost_at_utc == lost_at
    assert _stop_reads(rig) == stop_reads
    assert _close_required_alerts(rig) == []

    await rig.clock.advance((MAX_UNPROTECTED_MS - 3000 - 1) / 1000)  # 1 ms short
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.UNPROTECTED
    assert _close_required_alerts(rig) == []

    await rig.clock.advance(0.001)  # exactly max_unprotected_ms after stop_lost_at
    await rig.coordinator.step()
    assert ("UNPROTECTED", "CLOSE_REQUIRED", "B4_STOP_LOST_UNRESOLVED") in _transitions(rig)
    assert _close_required_alerts(rig) == ["B4_STOP_LOST_UNRESOLVED"]
    # The closer could not read the quantity: nothing is sent with a guessed one.
    assert rig.fake.calls_to("place_market_close") == []
    assert _view(rig).state is ProtectionState.CLOSE_FAILED
    assert guard.stop_placements == 1
    guard.assert_clean()


async def test_a_lost_stop_that_reads_active_again_does_not_restore_protected() -> None:
    rig, guard = await _checked_rig()
    await _to_state(rig, ProtectionState.COMPLETE)
    rig.fake.cancel_algo(rig.stop_id)
    _script_position_read_failures(rig, 500)
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.UNPROTECTED
    states_at_loss = len(_states(rig))

    # The exchange now answers the stop ACTIVE again (a late or stale answer).
    record = rig.fake.algo_history.pop(rig.stop_id)
    record.status = "NEW"
    rig.fake.open_algos[rig.stop_id] = record

    for _ in range(3):
        await rig.coordinator.step()
        assert _view(rig).state is ProtectionState.UNPROTECTED
        assert rig.coordinator.blocks_new_entries() is True
    assert _states(rig).count("PROTECTED") == 1, "only the original PROTECTED, never a second"
    assert len(_states(rig)) == states_at_loss, "no transition after the loss"
    assert guard.stop_placements == 1
    guard.assert_clean()


async def test_every_stop_placement_carries_the_plan_stop_price_and_the_deterministic_id() -> None:
    """RISK-03: the one remaining automatic re-placement (never confirmed, proven absent)."""
    rig, guard = await _checked_rig()
    rig.fake.fail_next("place_algo_protective", RuntimeError("scripted ambiguous failure"))
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()  # the placement fails ambiguously
    await rig.coordinator.step()  # REST proves the stop absent: the same id is placed again
    await rig.coordinator.step()  # REST: ACTIVE
    assert _view(rig).state is ProtectionState.PROTECTED
    assert guard.stop_placements == 2
    placed = rig.fake.calls_to("place_algo_protective")
    assert [c["kwargs"]["client_algo_id"] for c in placed] == [rig.stop_id, rig.stop_id]
    assert [c["kwargs"]["trigger_price"] for c in placed] == [rig.entry.sl_trigger_price] * 2

    rig.fake.cancel_algo(rig.stop_id)  # confirmed, then lost: no third placement
    for _ in range(4):
        await rig.coordinator.step()
    assert guard.stop_placements == 2
    guard.assert_clean()


async def test_a_guard_violation_would_be_seen() -> None:
    """The guard itself: a stop placement with another price is recorded as a violation."""
    rig, guard = await _checked_rig()
    rig.fake.positions["BTCUSDT"] = D("0.010")  # closePosition needs an open position (-4509)
    await rig.fake.place_algo_protective(
        symbol="BTCUSDT",
        side="SELL",
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=rig.entry.sl_trigger_price - D("1"),
        close_position=True,
        quantity=None,
        working_type="MARK_PRICE",
        client_algo_id=rig.stop_id,
    )
    assert guard.violations == ["trigger_price"]


@pytest.mark.parametrize("state", [ProtectionState.PROTECTED, ProtectionState.COMPLETE])
async def test_an_unreadable_stop_answer_keeps_the_state_and_the_next_step_reads_again(
    state: ProtectionState,
) -> None:
    rig, guard = await _checked_rig()
    await _to_state(rig, state)
    if state is ProtectionState.COMPLETE:
        rig.fake.trigger_stop(
            derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_2")
        )  # flat: the exit would be taken at once if the stop could be read
    rig.fake.fail_next("query_algo_order_by_client", RuntimeError("scripted stop read failure"))
    transitions_before = list(_transitions(rig))
    placements_before = len(rig.fake.calls_to("place_algo_protective"))

    await rig.coordinator.step()

    assert _view(rig).state is state
    assert _transitions(rig) == transitions_before
    assert len(rig.fake.calls_to("place_algo_protective")) == placements_before
    failures = [
        json.loads(e.payload_json)
        for e in rig.journal.calls
        if e.event_type == "PROTECTION_REST_FAILED"
    ]
    assert failures[-1]["call"] == "query_algo_order_by_client"
    assert failures[-1]["error_type"] == "RuntimeError"
    assert all("scripted" not in e.payload_json for e in rig.journal.calls)

    await rig.coordinator.step()  # the next step reads the stop again and carries on
    assert _view(rig).state is not state
    assert _stop_reads(rig) >= 2
    guard.assert_clean()
