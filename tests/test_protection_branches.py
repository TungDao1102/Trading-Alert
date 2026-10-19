"""The failure branches of the protection coordinator (plan 19-14; D-11, D-12, D-13, D034).

One deterministic offline race test per branch of 19-NOTES.md "Fill, stop and entry remainder",
run against the stateful Phase 19 fake exchange (constructed with
`enforce_flat_stop_rejection=True`), the real `MarketEmergencyCloser` over the same fake, scripted
completion gates and virtual time. Nothing sleeps and nothing touches a network. A green test
proves agreement with the fake's labelled rules, not with mainnet: the -2021 / -4509 answers are
Demo-observed only, the -2022 / -2024 answers of a reduce-only close are a TEST CONVENTION, and
no number here is a ratified limit (the deadlines are the TEST_ONLY values of
tests/support/execution_limits.py).

Open and NOT claimed safe here: Q4 / Phase 18 src/WR-12 (a 418/429 pause refuses the stop, the
cancel and the close), A3 (whether a closePosition stop is auto-cancelled when the position
closes), A2 (a GTD expiry reported as EXPIRED and terminal).
"""

from __future__ import annotations

import json
from decimal import Decimal

from src.domain.enums import ExecutionIntentStatus
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState

from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    ProtectionRig,
    make_rig,
)

D = Decimal


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection.state


def _transition_reasons(rig: ProtectionRig) -> list[tuple[str, str, str]]:
    """The journaled (from, to, reason) triples of the plan, in recording order."""
    out = []
    for event in rig.journal.calls:
        if event.event_type == "PROTECTION_TRANSITION":
            body = json.loads(event.payload_json)
            out.append((body["from"], body["to"], body["reason"]))
    return out


# --------------------------------------------------------------------------- #
# B5 (tracer): -2021 after a fill, end to end to CLOSE_REQUIRED, the close and FLAT.
# --------------------------------------------------------------------------- #


async def test_branch_b5_definitive_stop_rejection_after_a_fill_closes_and_ends_flat() -> None:
    rig = await make_rig(real_closer=True)
    rig.fake.reject_next_algo(-2021)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()

    # The stop was rejected definitively: the intent is REJECTED and the plan must be closed.
    stop_row = rig.stop_row()
    assert stop_row is not None
    assert stop_row.intent_status is ExecutionIntentStatus.REJECTED
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    assert [(a.event, a.reason, a.plan_hash) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "B5_STOP_REJECTED", TEST_ONLY_PLAN_HASH)
    ]
    transitions = _transition_reasons(rig)
    assert transitions[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B5_STOP_REJECTED")

    # The entry remainder cancel was issued and exactly one reduce-only MARKET close went out.
    assert len(rig.fake.calls_to("cancel_normal_order")) >= 1
    closes = rig.fake.calls_to("place_market_close")
    assert len(closes) == 1
    assert closes[0]["kwargs"]["quantity"] == D("0.004")
    assert closes[0]["kwargs"]["side"] == "SELL"
    assert closes[0]["kwargs"]["position_side"] == "BOTH"
    assert rig.fake.positions["BTCUSDT"] == D("0")

    # The stop is never resent, in this step or in any later one.
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.FLAT
    assert rig.coordinator.blocks_new_entries() is False
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    assert len(rig.fake.calls_to("place_market_close")) == 1

    # After FLAT the protective legs are swept once, by deterministic id (SL, TP1, TP2).
    swept = [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("cancel_algo_order")]
    assert swept == [
        derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role=role)
        for role in ("STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2")
    ]
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]  # still only the one entry
    assert [t[:2] for t in _transition_reasons(rig)][-2:] == [
        ("UNPROTECTED", "CLOSE_REQUIRED"),
        ("CLOSE_REQUIRED", "FLAT"),
    ]
    assert len(rig.alerts.alerts) == 1


async def test_branch_b5_never_reads_exception_message_text() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src/execution/protection.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("error_message", ".message", "str(exc)", "str(answer)"):
        assert forbidden not in source, forbidden


# --------------------------------------------------------------------------- #
# Task 2: B1, B2, B3 and the two separate deadlines (D-13) on virtual time.
# --------------------------------------------------------------------------- #

# The TEST_ONLY deadlines of tests/support/execution_limits.py, in milliseconds.
MAX_UNPROTECTED_MS = 7777
ENTRY_TERMINAL_TIMEOUT_MS = 13333


def _script_failures(rig: ProtectionRig, method: str, count: int) -> None:
    """The next `count` calls of `method` raise an ambiguous error (state untouched)."""
    for _ in range(count):
        rig.fake.fail_next(method, RuntimeError("scripted ambiguous failure"))


def _place_calls(rig: ProtectionRig) -> int:
    return len(rig.fake.calls_to("place_algo_protective"))


async def _advance_ms(rig: ProtectionRig, milliseconds: int) -> None:
    await rig.clock.advance(milliseconds / 1000)


async def test_branch_b1_slow_entry_cancel_keeps_the_stop_then_closes_at_its_own_deadline() -> None:
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "cancel_normal_order", 5)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()  # stop placed, the cancel fails (entry stays PARTIALLY_FILLED)
    await rig.coordinator.step()  # REST: the stop is ACTIVE, the entry is still open
    assert _state(rig) is ProtectionState.PROTECTED_ENTRY_OPEN

    # Before entry_terminal_timeout_ms: the stop is kept, no TP is placed, no close is sent.
    await _advance_ms(rig, ENTRY_TERMINAL_TIMEOUT_MS - 1)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED_ENTRY_OPEN
    assert _place_calls(rig) == 1
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.alerts.alerts == []
    assert rig.safe_mode.entered_reasons == []

    # The deadline is reached: CLOSE_REQUIRED with the knowingly-accepted reason journaled.
    await _advance_ms(rig, 1)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    assert _transition_reasons(rig)[-1] == (
        "PROTECTED_ENTRY_OPEN",
        "CLOSE_REQUIRED",
        "B1_ENTRY_NOT_TERMINAL",
    )
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "B1_ENTRY_NOT_TERMINAL")
    ]
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    notes = rig.journal.by_type("PROTECTION_CLOSE_REQUIRED")
    assert len(notes) == 1
    assert json.loads(notes[0].payload_json)["accepted_knowingly"] == "STOP_KEPT_ENTRY_CANCEL_SLOW"
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert rig.fake.positions["BTCUSDT"] == D("0")
    # The good stop is kept open until the close returned (it is only swept after FLAT).
    assert rig.stop_id in rig.fake.open_algos
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert _place_calls(rig) == 1

    # The plan stays watched: the entry is still open, so the state is not FLAT yet.
    await rig.coordinator.step()  # the cancel fails again
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    await rig.coordinator.step()  # the cancel goes through
    assert rig.fake.history[rig.entry_id].status == "CANCELED"
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    await rig.coordinator.step()  # entry terminal and REST flat
    assert _state(rig) is ProtectionState.FLAT
    assert rig.coordinator.blocks_new_entries() is False
    # The stop is cancelled only after the close returned.
    completed = rig.fake.completed
    assert completed.index("place_market_close") < completed.index("cancel_algo_order")
    assert rig.stop_id not in rig.fake.open_algos
    assert _place_calls(rig) == 1


async def test_branch_b2_entry_terminal_stop_unconfirmed_closes_at_max_unprotected_ms() -> None:
    rig = await make_rig(real_closer=True)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # stop NEW, the entry cancel succeeded
    # The stop answers a status whose class is UNKNOWN (consumed-looking): never protection.
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"

    queries_before = len(rig.fake.calls_to("query_algo_order_by_client"))
    await rig.coordinator.step()
    assert len(rig.fake.calls_to("query_algo_order_by_client")) == queries_before + 1
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True

    await _advance_ms(rig, MAX_UNPROTECTED_MS - 1)
    await rig.coordinator.step()  # one millisecond before the deadline
    assert len(rig.fake.calls_to("query_algo_order_by_client")) == queries_before + 2
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.fake.calls_to("place_market_close") == []
    assert _place_calls(rig) == 1  # no TP, no blind second stop

    await _advance_ms(rig, 1)
    await rig.coordinator.step()  # exactly max_unprotected_ms: the deadline is reached
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    assert _transition_reasons(rig)[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B2_STOP_UNCONFIRMED")
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "B2_STOP_UNCONFIRMED")
    ]
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert rig.fake.positions["BTCUSDT"] == D("0")
    assert _place_calls(rig) == 1


async def test_branch_b2_a_stop_active_one_step_before_the_deadline_avoids_close_required() -> None:
    rig = await make_rig(real_closer=True)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.UNPROTECTED

    await _advance_ms(rig, MAX_UNPROTECTED_MS - 1)
    rig.fake.open_algos[rig.stop_id].status = "NEW"  # REST now answers ACTIVE
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED
    await _advance_ms(rig, 60_000)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED
    assert rig.alerts.alerts == []
    assert rig.fake.calls_to("place_market_close") == []


async def test_branch_b3_both_ambiguous_requeries_and_recancels_then_closes_at_the_deadline() -> (
    None
):
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "place_algo_protective", 10)
    _script_failures(rig, "cancel_normal_order", 10)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()  # stop placement and cancel both fail
    stop_queries = len(rig.fake.calls_to("query_algo_order_by_client"))
    entry_queries = len(rig.fake.calls_to("query_order_by_client"))
    cancels = len(rig.fake.calls_to("cancel_normal_order"))
    await rig.coordinator.step()
    # Each step: both are queried by id (REST is the truth) and the cancel is re-issued.
    assert len(rig.fake.calls_to("query_algo_order_by_client")) == stop_queries + 1
    assert len(rig.fake.calls_to("query_order_by_client")) == entry_queries + 1
    assert len(rig.fake.calls_to("cancel_normal_order")) == cancels + 1
    assert _state(rig) is ProtectionState.UNPROTECTED

    await _advance_ms(rig, MAX_UNPROTECTED_MS - 1)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.fake.calls_to("place_market_close") == []
    await _advance_ms(rig, 1)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    assert _transition_reasons(rig)[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B3_BOTH_AMBIGUOUS")
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "B3_BOTH_AMBIGUOUS")
    ]
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert rig.fake.positions["BTCUSDT"] == D("0")
    # No stop is placed after CLOSE_REQUIRED, however many steps follow.
    placements_at_close = _place_calls(rig)
    for _ in range(3):
        await rig.coordinator.step()
    assert _place_calls(rig) == placements_at_close


async def test_branch_ambiguous_stop_is_replaced_only_after_a_definitive_absence_probe() -> None:
    rig = await make_rig()
    rig.fake.fail_next("place_algo_protective", RuntimeError("scripted ambiguous failure"))
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()  # probe: absent; placement: ambiguous failure
    assert _state(rig) is ProtectionState.UNPROTECTED
    await rig.coordinator.step()  # REST: absent (definitive) -> the same id is placed again
    await rig.coordinator.step()  # REST: ACTIVE
    assert _state(rig) is ProtectionState.PROTECTED

    sequence = [
        (c["method"], c["kwargs"].get("client_algo_id"))
        for c in rig.fake.calls
        if c["method"] in ("place_algo_protective", "query_algo_order_by_client")
    ]
    stop_id = rig.stop_id
    assert sequence == [
        ("query_algo_order_by_client", stop_id),
        ("place_algo_protective", stop_id),
        ("query_algo_order_by_client", stop_id),
        ("place_algo_protective", stop_id),
        ("query_algo_order_by_client", stop_id),
    ]


async def test_branch_deadlines_are_separate_the_entry_timeout_never_extends_the_unprotected() -> (
    None
):
    # max_unprotected 5000 ms, entry timeout 2000 ms: an unconfirmed stop with an open entry is
    # escalated by the unprotected deadline (5000), not delayed to, nor cut short by, the other.
    limits = limits_with(max_unprotected_ms=5000, entry_terminal_timeout_ms=2000)
    rig = await make_rig(real_closer=True, limits=limits)
    _script_failures(rig, "place_algo_protective", 20)
    _script_failures(rig, "cancel_normal_order", 20)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await _advance_ms(rig, 4999)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.UNPROTECTED  # the 2000 ms timeout is not B1 here
    await _advance_ms(rig, 1)
    await rig.coordinator.step()
    assert _transition_reasons(rig)[-1][2] == "B3_BOTH_AMBIGUOUS"


async def test_branch_a_small_unprotected_limit_does_not_cut_the_entry_timeout_short() -> None:
    # The stop is confirmed: max_unprotected_ms (1000) is satisfied and plays no further role;
    # only entry_terminal_timeout_ms (13333) can escalate an open entry (B1).
    limits = limits_with(max_unprotected_ms=1000)
    rig = await make_rig(real_closer=True, limits=limits)
    _script_failures(rig, "cancel_normal_order", 20)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED_ENTRY_OPEN
    await _advance_ms(rig, ENTRY_TERMINAL_TIMEOUT_MS - 1)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED_ENTRY_OPEN
    await _advance_ms(rig, 1)
    await rig.coordinator.step()
    assert _transition_reasons(rig)[-1][2] == "B1_ENTRY_NOT_TERMINAL"
