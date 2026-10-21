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

from src.adapters.binance_ratelimit_gate import RestGateRefusal
from src.domain.enums import ExecutionIntentStatus
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState

from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    ProtectionRig,
    make_rig,
    script_empty_position_reads,
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
        ("CLOSE_REQUIRED", "B5_STOP_REJECTED", TEST_ONLY_PLAN_HASH),
        ("PROTECTIVE_REJECTED", "B5_STOP_REJECTED", TEST_ONLY_PLAN_HASH),
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
    assert len(rig.alerts.alerts) == 2  # CLOSE_REQUIRED and PROTECTIVE_REJECTED, once per plan


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
    # Plan 19-16: the step after PROTECTED attaches the take profits (COMPLETE); what this test
    # pins is that the confirmed stop, however late, never reaches CLOSE_REQUIRED.
    assert _state(rig) is ProtectionState.COMPLETE
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


# --------------------------------------------------------------------------- #
# Task 3: B4 (RISK-04), -4509, rate-limit refusals (Q4, open) and CLOSE_FAILED retries.
# --------------------------------------------------------------------------- #

PAUSE_REASON = "RATE_LIMIT_PAUSE_429"


def _refusal() -> RestGateRefusal:
    return RestGateRefusal(PAUSE_REASON, 60)


def _script_refusals(rig: ProtectionRig, method: str, count: int) -> None:
    for _ in range(count):
        rig.fake.fail_next(method, _refusal())


async def test_branch_b4_risk04_fill_after_the_stop_triggered_closes_and_never_replaces() -> None:
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "cancel_normal_order", 2)  # the entry stays open for two steps
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED_ENTRY_OPEN

    # The stop triggers and flattens the position; then the still-open entry fills again.
    rig.fake.trigger_stop(rig.stop_id)
    assert rig.fake.positions["BTCUSDT"] == D("0")
    rig.fake.fill(rig.entry_id, quantity=D("0.002"))
    assert rig.fake.positions["BTCUSDT"] == D("0.002")
    cancels_before = len(rig.fake.calls_to("cancel_normal_order"))

    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    assert _transition_reasons(rig)[-1] == (
        "PROTECTED_ENTRY_OPEN",
        "CLOSE_REQUIRED",
        "B4_FILL_AFTER_STOP",
    )
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "B4_FILL_AFTER_STOP")
    ]
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    # The stop is NOT re-placed, the remainder cancel is issued again, the new exposure closed.
    assert _place_calls(rig) == 1
    assert len(rig.fake.calls_to("cancel_normal_order")) == cancels_before + 1
    closes = rig.fake.calls_to("place_market_close")
    assert [c["kwargs"]["quantity"] for c in closes] == [D("0.002")]
    assert closes[0]["kwargs"]["side"] == "SELL"
    assert rig.fake.positions["BTCUSDT"] == D("0")

    await rig.coordinator.step()  # the entry is terminal and the position flat
    assert _state(rig) is ProtectionState.FLAT
    assert _place_calls(rig) == 1  # the plan never carried on
    assert len(rig.fake.calls_to("place_market_close")) == 1


async def test_branch_b4_is_decided_by_position_not_by_the_algo_status_class() -> None:
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "cancel_normal_order", 2)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    # The stop is still reported by REST in a consumed-looking status while a position exists.
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERED"
    await rig.coordinator.step()
    assert _transition_reasons(rig)[-1][2] == "B4_FILL_AFTER_STOP"
    assert _place_calls(rig) == 1


async def test_branch_stop_consumed_with_a_flat_position_and_terminal_entry_ends_flat() -> None:
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "cancel_normal_order", 2)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    rig.fake.trigger_stop(rig.stop_id)  # the stop did its job; no new fill
    await rig.coordinator.step()  # the cancel goes through; REST: stop FINISHED, flat
    # 19-REVIEW WR-04 (owner, D077): flat while the entry was still open (read before the cancel)
    # is not a safe state; the lost stop makes the plan UNPROTECTED (blocking), never re-placed.
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert _transition_reasons(rig)[-1] == ("PROTECTED_ENTRY_OPEN", "UNPROTECTED", "STOP_LOST")
    assert rig.coordinator.blocks_new_entries() is True
    await rig.coordinator.step()  # entry terminal, flat
    assert _state(rig) is ProtectionState.FLAT
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.alerts.alerts == []
    assert _place_calls(rig) == 1


def _gap_notes(rig: ProtectionRig) -> list[dict[str, str]]:
    """The journaled transient-position-gap notes (19-REVIEW CR-03)."""
    notes = []
    for event in rig.journal.calls:
        if event.event_type == "PROTECTION_REST_FAILED":
            body = json.loads(event.payload_json)
            if body.get("error_type") == "TransientPositionGap":
                notes.append(body)
    return notes


async def test_branch_stop_lost_one_empty_position_read_never_sweeps_an_open_position() -> None:
    """19-REVIEW CR-03 / T-8-30: one zero read followed by a non-zero one must not go FLAT.

    The stop reads NOT_ACTIVE, the entry is terminal and the position (0.004) is still open, but
    the first REST position answer is a transient empty list. The pre-CR-03 code went FLAT on
    that one read and swept every leg; the second, fresh read shows the position and the gap is
    journaled. 19-REVIEW WR-04 (owner, D077) decides what follows: the plan is UNPROTECTED
    (blocking), never settles to PROTECTED and never gets take profits (the pre-WR-04 code did
    both on the next step), and the next read of the open position is B4: CLOSE_REQUIRED, one
    MARKET close, no stop placement. The legs are swept only after the close made it flat.
    """
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "cancel_normal_order", 2)  # the entry stays open for two steps
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    await rig.coordinator.step()  # the remainder cancel goes through (entry read before it)
    assert _state(rig) is ProtectionState.PROTECTED_ENTRY_OPEN
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERED"  # the stop no longer looks ACTIVE
    assert rig.fake.positions["BTCUSDT"] == D("0.004")
    script_empty_position_reads(rig.fake, [True, False])

    await rig.coordinator.step()  # entry terminal; position read empty, then 0.004
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert rig.stop_id in rig.fake.open_algos
    assert len(_gap_notes(rig)) == 1
    assert "FLAT" not in [to for _, to, _ in _transition_reasons(rig)]

    await rig.coordinator.step()  # the real read shows 0.004: B4, closed by MARKET
    assert _transition_reasons(rig)[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B4_FILL_AFTER_STOP")
    assert [c["kwargs"]["quantity"] for c in rig.fake.calls_to("place_market_close")] == [
        D("0.004")
    ]
    assert rig.fake.positions["BTCUSDT"] == D("0")
    await rig.coordinator.step()  # entry terminal and flat: FLAT, then the sweep
    assert _state(rig) is ProtectionState.FLAT
    states = [to for _, to, _ in _transition_reasons(rig)]
    assert "PROTECTED" not in states and "COMPLETE" not in states
    assert _place_calls(rig) == 1  # no stop re-placed, no take profit placed
    completed = rig.fake.completed
    assert completed.index("place_market_close") < completed.index("cancel_algo_order")


async def test_branch_stop_consumed_flat_reads_the_position_twice_before_flat() -> None:
    """The genuine flat case still ends FLAT, on two consecutive zero reads."""
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "cancel_normal_order", 2)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    rig.fake.trigger_stop(rig.stop_id)
    await rig.coordinator.step()
    reads_before = len(rig.fake.calls_to("snapshot_positions"))
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.FLAT
    assert len(rig.fake.calls_to("snapshot_positions")) - reads_before == 2
    assert _gap_notes(rig) == []


async def test_branch_no_position_4509_one_empty_position_read_keeps_the_plan_unprotected() -> None:
    """19-REVIEW CR-03: -4509, a terminal entry and ONE empty position read are not FLAT.

    The entry filled completely (0.010, terminal) and the position is open; the stop answers
    -4509 and the first position read is a transient empty list. The old code went FLAT and
    swept the legs, leaving the open position with no stop. Now the second read shows the
    position, the plan stays UNPROTECTED (blocking) and the next step re-places the stop.
    """
    rig = await make_rig(real_closer=True)
    rig.fake.reject_next_algo(-4509)
    script_empty_position_reads(rig.fake, [True, False])
    rig.coordinator.fill_sink(rig.stream_fill(D("0.010")))

    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert len(_gap_notes(rig)) == 1
    assert rig.fake.positions["BTCUSDT"] == D("0.010")

    await rig.coordinator.step()  # REST: the stop is absent by id, so it is placed again
    assert _place_calls(rig) == 2
    assert rig.fake.calls_to("place_market_close") == []


async def test_branch_no_position_4509_flat_and_entry_terminal_ends_flat_without_a_close() -> None:
    rig = await make_rig(real_closer=True)
    routed = rig.stream_fill(D("0.004"))
    # Another mechanism closed the position before the stop was placed (probe 6 style).
    await rig.fake.place_market_close(
        symbol="BTCUSDT",
        side="SELL",
        position_side="BOTH",
        quantity=D("0.004"),
        new_client_order_id="manual-close-0001",
    )
    rig.coordinator.fill_sink(routed)

    await rig.coordinator.step()  # the stop placement answers -4509 (no position)
    assert _state(rig) is ProtectionState.FLAT
    assert _transition_reasons(rig)[-1] == ("UNPROTECTED", "FLAT", "NO_POSITION_ON_STOP")
    assert rig.coordinator.blocks_new_entries() is False
    closes = rig.fake.calls_to("place_market_close")
    assert [c["kwargs"]["new_client_order_id"] for c in closes] == ["manual-close-0001"]
    assert _place_calls(rig) == 1  # the -4509 stop is not resent
    assert rig.alerts.alerts == []
    assert len(rig.fake.calls_to("cancel_algo_order")) == 3  # the plan's legs are swept


async def test_branch_no_position_4509_but_the_position_is_open_goes_close_required() -> None:
    rig = await make_rig(real_closer=True)
    rig.fake.reject_next_algo(-4509)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    assert _transition_reasons(rig)[-1] == (
        "UNPROTECTED",
        "CLOSE_REQUIRED",
        "NO_POSITION_ON_STOP_BUT_EXPOSED",
    )
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "NO_POSITION_ON_STOP_BUT_EXPOSED")
    ]
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert rig.fake.positions["BTCUSDT"] == D("0")
    assert _place_calls(rig) == 1


async def test_branch_no_position_4509_flat_with_an_open_entry_keeps_watching() -> None:
    rig = await make_rig(real_closer=True)
    _script_failures(rig, "cancel_normal_order", 3)
    routed = rig.stream_fill(D("0.004"))
    await rig.fake.place_market_close(
        symbol="BTCUSDT",
        side="SELL",
        position_side="BOTH",
        quantity=D("0.004"),
        new_client_order_id="manual-close-0001",
    )
    rig.coordinator.fill_sink(routed)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.UNPROTECTED  # flat, but the entry is not terminal
    assert [c for c in rig.fake.calls_to("place_market_close") if "xc-" in str(c)] == []
    assert rig.alerts.alerts == []


async def test_branch_q4_refused_stop_is_journaled_not_sent_and_the_deadline_still_escalates() -> (
    None
):
    rig = await make_rig(real_closer=True)
    _script_refusals(rig, "place_algo_protective", 10)
    _script_refusals(rig, "place_market_close", 1)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()
    not_sent = rig.journal.by_type("STOP_NOT_SENT")
    assert len(not_sent) == 1
    body = json.loads(not_sent[0].payload_json)
    assert body["reason"] == PAUSE_REASON
    assert body["error_type"] == "RestGateRefusal"
    # Nothing reached the exchange: the intent stays SENT (REJECTED is terminal and would forbid
    # the retry), no SAFE_MODE is entered by the refusal itself, nothing claims safety.
    stop_row = rig.stop_row()
    assert stop_row is not None
    assert stop_row.intent_status is ExecutionIntentStatus.SENT
    assert rig.safe_mode.entered_reasons == []
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True

    # The next step tries again, by querying the id first.
    await _advance_ms(rig, 1)  # (the journal keys events by content and time)
    await rig.coordinator.step()
    assert len(rig.journal.by_type("STOP_NOT_SENT")) == 2
    methods = [
        c["method"]
        for c in rig.fake.calls
        if c["method"] in ("place_algo_protective", "query_algo_order_by_client")
    ]
    assert methods == [
        "query_algo_order_by_client",
        "place_algo_protective",
        "query_algo_order_by_client",
        "place_algo_protective",
    ]

    # The deadline keeps running; escalation happens on time and the close is refused too.
    await _advance_ms(rig, MAX_UNPROTECTED_MS - 3)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.UNPROTECTED
    await _advance_ms(rig, 2)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.CLOSE_FAILED
    assert [t[1:] for t in _transition_reasons(rig)[-2:]] == [
        ("CLOSE_REQUIRED", "B2_STOP_UNCONFIRMED"),
        ("CLOSE_FAILED", "CLOSE_NOT_SENT"),
    ]
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    assert [a.event for a in rig.alerts.alerts] == ["CLOSE_REQUIRED", "EMERGENCY_CLOSE_NOT_SENT"]
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.fake.positions["BTCUSDT"] == D("0.004")  # nothing claims the position is safe

    # The pause ends: the next step closes and the plan ends FLAT.
    await rig.coordinator.step()
    assert rig.fake.positions["BTCUSDT"] == D("0")
    assert _state(rig) is ProtectionState.FLAT
    assert rig.coordinator.blocks_new_entries() is False


async def test_branch_q4_refused_entry_cancel_is_journaled_not_sent() -> None:
    rig = await make_rig()
    _script_refusals(rig, "cancel_normal_order", 1)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    not_sent = rig.journal.by_type("PROTECTION_ENTRY_CANCEL_NOT_SENT")
    assert len(not_sent) == 1
    assert json.loads(not_sent[0].payload_json)["reason"] == PAUSE_REASON
    assert rig.journal.by_type("PROTECTION_ENTRY_CANCEL_FAILED") == []
    await rig.coordinator.step()  # the cancel is issued again and goes through
    assert rig.fake.history[rig.entry_id].status == "CANCELED"


async def test_branch_close_failed_keeps_blocking_and_retries_every_step_until_flat() -> None:
    rig = await make_rig(closer_results=[False, False, True])
    rig.fake.reject_next_algo(-2021)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.CLOSE_FAILED
    assert rig.coordinator.blocks_new_entries() is True
    assert len(rig.closer.calls) == 1  # type: ignore[attr-defined]
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.CLOSE_FAILED
    assert rig.coordinator.blocks_new_entries() is True
    assert len(rig.closer.calls) == 2  # type: ignore[attr-defined]
    await rig.coordinator.step()  # REST shows flat and the entry is terminal
    assert len(rig.closer.calls) == 3  # type: ignore[attr-defined]
    assert _state(rig) is ProtectionState.FLAT
    assert rig.coordinator.blocks_new_entries() is False
    assert {c["reason"] for c in rig.closer.calls} == {"B5_STOP_REJECTED"}  # type: ignore[attr-defined]
    # Straight from CLOSE_FAILED to FLAT (no spurious hop through CLOSE_REQUIRED).
    assert [t[:2] for t in _transition_reasons(rig)[-2:]] == [
        ("CLOSE_REQUIRED", "CLOSE_FAILED"),
        ("CLOSE_FAILED", "FLAT"),
    ]
    await rig.coordinator.step()
    assert len(rig.closer.calls) == 3  # type: ignore[attr-defined]  # FLAT: no more closes


async def test_branch_every_transition_writes_one_deterministic_journal_record() -> None:
    async def run() -> tuple[list[str], int]:
        rig = await make_rig(real_closer=True)
        rig.fake.reject_next_algo(-2021)
        rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
        for _ in range(3):
            await rig.coordinator.step()
        ids = [
            e.journal_event_id for e in rig.journal.calls if e.event_type == "PROTECTION_TRANSITION"
        ]
        # Steps with no change write no transition record.
        for _ in range(3):
            await rig.coordinator.step()
        after = [e for e in rig.journal.calls if e.event_type == "PROTECTION_TRANSITION"]
        return ids, len(after)

    first_ids, first_count = await run()
    second_ids, second_count = await run()
    assert first_ids == second_ids  # deterministic ids: the same scenario, the same records
    assert len(set(first_ids)) == len(first_ids) == first_count == second_count
    # NONE->AWAITING_FILL, AWAITING_FILL->UNPROTECTED, ->CLOSE_REQUIRED, ->FLAT
    assert first_count == 4
