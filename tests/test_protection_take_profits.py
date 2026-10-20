"""The coordinator's take-profit and exit steps (plan 19-16; D-18, D-19, D-20, G2-032, O-03).

From PROTECTED (entry terminal, stop confirmed by REST) the next `step()` reads the REST position
and calls `attach_protectives_to_fill`: COMPLETE when both take-profit legs are REST-confirmed,
TP_UNAVAILABLE otherwise (SAFE_MODE with the existing ENTRY_WITHOUT_PROTECTIVE reason, a critical
alert, the confirmed stop kept, no market close for that reason alone). From COMPLETE or
TP_UNAVAILABLE a step that reads a flat position goes FLAT and sweeps the plan's legs by
deterministic id. Virtual time, the stateful fake exchange and an in-memory intent store; nothing
sleeps and nothing touches a network. TEST_ONLY numbers; a green test proves agreement with the
fake, not with Binance. Tests whose names contain `tp` are selected by `-k tp`.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from typing import Any

from src.domain.enums import ExecutionIntentStatus
from src.domain.lot_filters import LotFilters
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState

from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    TEST_ONLY_SYMBOL,
    ProtectionRig,
    complete_constraint_snapshot,
    lot_filters_for_tests,
    make_rig,
    script_empty_position_reads,
)

D = Decimal
STOP_ID = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="STOP_LOSS")
TP1_ID = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_1")
TP2_ID = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_2")
HOLD = "ENTRY_WITHOUT_PROTECTIVE"


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection.state


def _placed_ids(rig: ProtectionRig) -> list[str]:
    return [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("place_algo_protective")]


def _row(rig: ProtectionRig, role: str) -> Any:
    return rig.inner_store.get_intent(approval_id=rig.entry.approval_id, role=role)


def _last_transition(rig: ProtectionRig) -> tuple[str, str, str]:
    payload = [
        json.loads(e.payload_json)
        for e in rig.journal.calls
        if e.event_type == "PROTECTION_TRANSITION"
    ][-1]
    return (payload["from"], payload["to"], payload["reason"])


FULL_FILL = D("0.010")


async def _to_protected(rig: ProtectionRig, quantity: Decimal = FULL_FILL) -> None:
    """The entry fills by `quantity`; two steps later the stop is confirmed and the entry ended."""
    rig.coordinator.fill_sink(rig.stream_fill(quantity))
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.UNPROTECTED
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED


def _coarser_live_filters() -> LotFilters:
    return dataclasses.replace(
        lot_filters_for_tests(),
        lot_min_quantity=D("0.002"),
        lot_step_size=D("0.002"),
        market_lot_min_quantity=D("0.002"),
        market_lot_step_size=D("0.002"),
    )


def _assert_tp_unavailable_and_nothing_else(rig: ProtectionRig, detail: str) -> None:
    """The TP_UNAVAILABLE routine: state, SAFE_MODE once, critical alert, stop kept, no close."""
    assert _state(rig) is ProtectionState.TP_UNAVAILABLE
    assert rig.safe_mode.entered_reasons == [HOLD]
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [("TP_UNAVAILABLE", detail)]
    assert STOP_ID in rig.fake.open_algos, "the confirmed stop must be kept"
    assert rig.fake.calls_to("cancel_algo_order") == [], "the stop must not be cancelled"
    assert rig.fake.calls_to("place_market_close") == [], "never a flatten for that reason alone"
    assert getattr(rig.closer, "calls", []) == [], "the emergency closer must not run"
    assert rig.coordinator.blocks_new_entries() is False
    notes = [e for e in rig.journal.calls if e.event_type == "PROTECTION_TP_UNAVAILABLE"]
    assert len(notes) == 1
    assert json.loads(notes[0].payload_json)["failure_detail"] == detail


# --------------------------------------------------------------------------- #
# PROTECTED -> attach -> COMPLETE.
# --------------------------------------------------------------------------- #


async def test_tp_protected_then_the_next_step_attaches_both_legs_and_completes() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    assert _placed_ids(rig) == [STOP_ID], "no take profit before the PROTECTED step"

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.COMPLETE
    assert _last_transition(rig) == ("PROTECTED", "COMPLETE", "TP_LEGS_CONFIRMED")
    assert _placed_ids(rig) == [STOP_ID, TP1_ID, TP2_ID]
    tp1 = rig.fake.calls_to("place_algo_protective")[1]["kwargs"]
    assert (tp1["quantity"], tp1["reduce_only"], tp1["close_position"]) == (D("0.005"), True, False)
    tp2 = rig.fake.calls_to("place_algo_protective")[2]["kwargs"]
    assert (tp2["quantity"], tp2["reduce_only"], tp2["close_position"]) == (None, None, True)
    for role in ("TAKE_PROFIT_1", "TAKE_PROFIT_2"):
        assert _row(rig, role).intent_status is ExecutionIntentStatus.ACKED
    assert _row(rig, "TAKE_PROFIT_1").intended_quantity == D("0.005")
    assert set(rig.fake.open_algos) == {STOP_ID, TP1_ID, TP2_ID}
    assert rig.safe_mode.entered_reasons == []
    assert rig.alerts.alerts == []
    assert rig.coordinator.blocks_new_entries() is False


async def test_tp_legs_are_placed_exactly_once_when_step_runs_again() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.COMPLETE
    log_after_complete = list(rig.log)
    calls_after_complete = len(rig.fake.calls)

    for _ in range(3):
        await rig.coordinator.step()

    assert _state(rig) is ProtectionState.COMPLETE
    assert _placed_ids(rig) == [STOP_ID, TP1_ID, TP2_ID]
    assert rig.log == log_after_complete, "a repeated step wrote or placed something"
    reads_only = {"snapshot_positions"}
    new_calls = {c["method"] for c in rig.fake.calls[calls_after_complete:]}
    assert new_calls <= reads_only
    assert rig.log.count("store.record_protective_intent:TAKE_PROFIT_1") == 1


async def test_tp_quantity_comes_from_the_rest_position_not_the_planned_entry_quantity() -> None:
    rig = await make_rig()
    await _to_protected(rig, D("0.004"))  # the remainder is cancelled; the position is 0.004

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.COMPLETE
    assert rig.fake.calls_to("place_algo_protective")[1]["kwargs"]["quantity"] == D("0.002")


async def test_tp_a_late_fill_before_the_entry_is_terminal_never_resizes_tp1() -> None:
    """G2-032: nothing is placed while the entry is open; the legs are sized once from the final
    position, and no TP1 is ever cancelled or replaced afterwards."""
    rig = await make_rig()
    rig.fake.fail_next("cancel_normal_order", TimeoutError("cancel lost"))
    rig.fake.fail_next("cancel_normal_order", TimeoutError("cancel lost again"))
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # first fill: stop placed, the entry cancel fails
    await rig.coordinator.step()  # stop confirmed, the entry is still open, the cancel fails
    assert _state(rig) is ProtectionState.PROTECTED_ENTRY_OPEN
    rig.fake.fill(rig.entry_id, quantity=D("0.003"))  # a late fill: the position is now 0.007
    await rig.coordinator.step()  # the cancel goes through, REST has not shown it yet
    assert _state(rig) is ProtectionState.PROTECTED_ENTRY_OPEN
    await rig.coordinator.step()  # the entry is CANCELED
    assert _state(rig) is ProtectionState.PROTECTED
    assert _placed_ids(rig) == [STOP_ID], "a take profit was placed while the entry was open"

    await rig.coordinator.step()  # PROTECTED -> COMPLETE

    assert _state(rig) is ProtectionState.COMPLETE
    assert _placed_ids(rig) == [STOP_ID, TP1_ID, TP2_ID]
    # floor(0.5 * 0.007) on the 0.001 grid: sized from the final position, not from 0.004.
    assert rig.fake.calls_to("place_algo_protective")[1]["kwargs"]["quantity"] == D("0.003")
    for _ in range(2):
        await rig.coordinator.step()
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert _placed_ids(rig).count(TP1_ID) == 1


# --------------------------------------------------------------------------- #
# D-20: snapshot validity before the legs.
# --------------------------------------------------------------------------- #


async def test_tp_stale_but_complete_snapshot_reads_live_filters_and_resizes() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    await rig.clock.advance(11 * 60)  # past the TEST_ONLY snapshot TTL of 600 s
    rig.fake.set_lot_filters(TEST_ONLY_SYMBOL, _coarser_live_filters())

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.COMPLETE
    assert len(rig.fake.calls_to("symbol_lot_filters")) == 1
    assert rig.fake.calls_to("place_algo_protective")[1]["kwargs"]["quantity"] == D("0.004")
    assert rig.safe_mode.entered_reasons == []


async def test_tp_fresh_snapshot_does_not_read_live_filters() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.COMPLETE
    assert rig.fake.calls_to("symbol_lot_filters") == []


async def test_tp_stale_snapshot_with_a_failing_filter_read_is_tp_unavailable() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    await rig.clock.advance(11 * 60)
    # No lot filters are set on the fake: the live read raises.

    await rig.coordinator.step()

    _assert_tp_unavailable_and_nothing_else(
        rig, "plan snapshot is stale and no live filters were read"
    )
    assert _placed_ids(rig) == [STOP_ID]
    assert _last_transition(rig) == ("PROTECTED", "TP_UNAVAILABLE", "TP_UNAVAILABLE")


async def test_tp_incomplete_snapshot_is_refused_into_tp_unavailable() -> None:
    """The recorded consequence: margin type, leverage and equity are unknown until Phases
    21-22, so with real data every TP placement ends here (stop kept, SAFE_MODE, alert)."""
    rig = await make_rig(plan_constraint_snapshot=complete_constraint_snapshot(margin_type=None))
    await _to_protected(rig)

    await rig.coordinator.step()

    _assert_tp_unavailable_and_nothing_else(
        rig, "plan snapshot is INCOMPLETE and not valid for live"
    )
    assert _placed_ids(rig) == [STOP_ID]
    assert rig.fake.calls_to("symbol_lot_filters") == []
    assert _row(rig, "TAKE_PROFIT_1") is None


# --------------------------------------------------------------------------- #
# O-03 / CR-03: un-sizeable or rejected legs keep the stop; never a normal completion.
# --------------------------------------------------------------------------- #


async def test_tp_unsizeable_tp1_is_tp_unavailable_without_a_single_tp_fallback() -> None:
    rig = await make_rig()
    await _to_protected(rig, D("0.001"))  # TP1 = 0.0005 floors to nothing: MIN_QTY_REJECT

    await rig.coordinator.step()

    _assert_tp_unavailable_and_nothing_else(rig, "TAKE_PROFIT_1 sizing: MIN_QTY_REJECT")
    assert _placed_ids(rig) == [STOP_ID], "no TP1 and no TP2 (O-03: no single-TP fallback)"
    for _ in range(2):
        await rig.coordinator.step()
    assert _state(rig) is ProtectionState.TP_UNAVAILABLE
    assert len(rig.safe_mode.entered_reasons) == 1, "TP_UNAVAILABLE must not repeat the routine"
    assert len(rig.alerts.alerts) == 1


async def test_tp_rejected_leg_is_tp_unavailable_and_keeps_the_stop() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    rig.fake.reject_next_algo(-4016, "price too far")

    await rig.coordinator.step()

    _assert_tp_unavailable_and_nothing_else(rig, "TAKE_PROFIT_1: BadRequestError")
    assert _row(rig, "TAKE_PROFIT_1").intent_status is ExecutionIntentStatus.REJECTED
    assert _placed_ids(rig) == [STOP_ID, TP1_ID]


async def test_tp_unreadable_position_waits_and_retries_on_the_next_step() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    rig.fake.fail_next("snapshot_positions", TimeoutError("positions timeout"))

    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED
    assert _placed_ids(rig) == [STOP_ID]
    assert any(e.event_type == "PROTECTION_REST_FAILED" for e in rig.journal.calls)

    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.COMPLETE


async def test_tp_position_on_the_wrong_side_is_tp_unavailable() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    rig.fake.positions[TEST_ONLY_SYMBOL] = D("-0.010")  # contradicts the LONG plan

    await rig.coordinator.step()

    _assert_tp_unavailable_and_nothing_else(rig, "position side does not match the plan")
    assert _placed_ids(rig) == [STOP_ID]


# --------------------------------------------------------------------------- #
# Exit: REST shows flat -> FLAT, and the plan's legs are swept by deterministic id.
# --------------------------------------------------------------------------- #


def _swept_ids(rig: ProtectionRig) -> list[str]:
    return [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("cancel_algo_order")]


async def test_tp_exit_by_tp2_goes_flat_and_sweeps_the_remaining_legs() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.COMPLETE
    rig.fake.trigger_stop(TP2_ID)  # a closePosition TP consumes the position

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    assert _last_transition(rig) == ("COMPLETE", "FLAT", "POSITION_CLOSED")
    assert _swept_ids(rig) == [STOP_ID, TP1_ID, TP2_ID]
    assert rig.fake.open_algos == {}
    assert rig.coordinator.blocks_new_entries() is False
    await rig.coordinator.step()
    assert _swept_ids(rig) == [STOP_ID, TP1_ID, TP2_ID], "the sweep ran again"


async def test_tp_exit_by_the_stop_goes_flat_and_sweeps_both_take_profits() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    await rig.coordinator.step()
    rig.fake.trigger_stop(STOP_ID)

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    assert _swept_ids(rig) == [STOP_ID, TP1_ID, TP2_ID]
    assert rig.fake.open_algos == {}


async def test_tp_a_partially_closed_position_keeps_the_complete_state() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    await rig.coordinator.step()
    rig.fake.trigger_stop(TP1_ID)  # TP1 takes 0.005 of the 0.010
    assert rig.fake.positions[TEST_ONLY_SYMBOL] == D("0.005")

    for _ in range(3):
        await rig.coordinator.step()

    assert _state(rig) is ProtectionState.COMPLETE
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert {STOP_ID, TP2_ID} <= set(rig.fake.open_algos)


async def test_tp_unavailable_exits_to_flat_with_a_sweep_when_the_position_closes() -> None:
    rig = await make_rig()
    await _to_protected(rig, D("0.001"))
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.TP_UNAVAILABLE
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.TP_UNAVAILABLE, "an open position keeps the state"
    assert rig.fake.calls_to("cancel_algo_order") == []
    rig.fake.trigger_stop(STOP_ID)

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    assert _last_transition(rig) == ("TP_UNAVAILABLE", "FLAT", "POSITION_CLOSED")
    assert _swept_ids(rig) == [STOP_ID, TP1_ID, TP2_ID]


async def test_tp_a_position_closed_before_the_legs_ends_flat_without_placing_them() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    rig.fake.trigger_stop(STOP_ID)  # the stop was consumed between the confirmation and the step

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    assert _last_transition(rig) == ("PROTECTED", "FLAT", "POSITION_CLOSED")
    assert _placed_ids(rig) == [STOP_ID]
    assert _swept_ids(rig) == [STOP_ID, TP1_ID, TP2_ID]


def _gap_note_count(rig: ProtectionRig) -> int:
    return sum(
        1
        for e in rig.journal.calls
        if e.event_type == "PROTECTION_REST_FAILED"
        and json.loads(e.payload_json).get("error_type") == "TransientPositionGap"
    )


async def test_tp_one_empty_position_read_in_protected_never_sweeps_the_active_stop() -> None:
    """19-REVIEW CR-03 / T-8-30: a transient empty read is not FLAT.

    PROTECTED means the stop is REST-confirmed ACTIVE and the position (0.010) is open. The old
    code went FLAT on one empty `snapshot_positions` answer and cancelled the ACTIVE stop; now a
    second, fresh read shows the position, the gap is journaled and the state is kept.
    """
    rig = await make_rig()
    await _to_protected(rig)
    script_empty_position_reads(rig.fake, [True, False])

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.PROTECTED
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert STOP_ID in rig.fake.open_algos
    assert _gap_note_count(rig) == 1
    await rig.coordinator.step()  # the next real read attaches the take profits as usual
    assert _state(rig) is ProtectionState.COMPLETE


async def test_tp_one_empty_position_read_in_complete_keeps_every_leg() -> None:
    """From COMPLETE, one empty read followed by the real position keeps all three legs."""
    rig = await make_rig()
    await _to_protected(rig)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.COMPLETE
    script_empty_position_reads(rig.fake, [True, False])

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.COMPLETE
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert {STOP_ID, TP1_ID, TP2_ID} <= set(rig.fake.open_algos)
    assert _gap_note_count(rig) == 1


async def test_tp_exit_needs_two_consecutive_zero_reads() -> None:
    """A genuine exit still goes FLAT, after exactly two zero reads in the step."""
    rig = await make_rig()
    await _to_protected(rig)
    await rig.coordinator.step()
    rig.fake.trigger_stop(TP2_ID)
    reads_before = len(rig.fake.calls_to("snapshot_positions"))

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    assert len(rig.fake.calls_to("snapshot_positions")) - reads_before == 2
    assert _gap_note_count(rig) == 0


async def test_tp_unreadable_position_in_complete_keeps_the_state() -> None:
    rig = await make_rig()
    await _to_protected(rig)
    await rig.coordinator.step()
    rig.fake.fail_next("snapshot_positions", TimeoutError("positions timeout"))

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.COMPLETE
    assert rig.fake.calls_to("cancel_algo_order") == []
