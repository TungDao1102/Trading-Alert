"""An entry the manager left ENTRY_STATE_UNKNOWN, tracked by the coordinator (19-REVIEW WR-05).

Owner decision (review-fix batch 1): the manager hands an ENTRY_STATE_UNKNOWN entry (Q5) to the
protection coordinator, flagged `entry_state_unknown`. The coordinator

* never sends an entry, and never reads found=False as proof that the entry does not exist;
* never forgets the record;
* protects a fill it finds with the normal fill -> stop -> cancel-remainder flow, under the
  SAFE_MODE(ENTRY_STATE_UNKNOWN) the manager already entered (SAFE_MODE blocks entries only);
* after the GTD time plus `protection.entry_unknown_grace_ms` without ever finding the entry,
  moves it to ENTRY_UNRESOLVED (one journaled note) and queries it only every Nth step.

The grace is a FAKE value from `tests/support/execution_limits.py` (the owner has not chosen it).
Everything runs on the stateful fake exchange with virtual time: no network, no sleep.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.execution.protection import (
    EVENT_ENTRY_UNRESOLVED,
    UNRESOLVED_ENTRY_POLL_EVERY_N_STEPS,
    ProtectionState,
)

from tests.support.execution_limits import TEST_ONLY_EXECUTION_LIMIT_VALUES
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    ProtectionRig,
    make_rig,
    resting_entry_for_tests,
)
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START

D = Decimal
N = UNRESOLVED_ENTRY_POLL_EVERY_N_STEPS
GRACE_MS = TEST_ONLY_EXECUTION_LIMIT_VALUES["protection.entry_unknown_grace_ms"]
# TEST_ONLY: the entry's goodTillDate, 30 minutes after the virtual start.
GOOD_TILL = TEST_ONLY_VIRTUAL_START + timedelta(minutes=30)
# Every order-changing adapter method: the coordinator must never send an ENTRY.
SENDING_METHODS = ("place_entry", "place_market_close")


async def _unknown_rig(*, exists: bool) -> ProtectionRig:
    """An ENTRY_STATE_UNKNOWN entry; `exists` says whether the exchange really booked it."""
    rig = await make_rig(
        place_entry=exists, entry_state_unknown=True, entry_good_till_utc=GOOD_TILL
    )
    # What the manager did before the hand-off (Q5): SAFE_MODE ENTRY_STATE_UNKNOWN.
    rig.safe_mode.enter_safe_mode(reason="ENTRY_STATE_UNKNOWN")
    return rig


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None, "the record must never be forgotten"
    return protection.state


def _queries(rig: ProtectionRig) -> int:
    return len(rig.fake.calls_to("query_order_by_client"))


def _sends(rig: ProtectionRig) -> dict[str, int]:
    return {method: len(rig.fake.calls_to(method)) for method in SENDING_METHODS}


def _unresolved_notes(rig: ProtectionRig) -> list[Any]:
    return [e for e in rig.journal.calls if e.event_type == EVENT_ENTRY_UNRESOLVED]


async def _advance_ms(rig: ProtectionRig, milliseconds: int) -> None:
    await rig.clock.advance(milliseconds / 1000)


async def _advance_to(rig: ProtectionRig, instant: Any) -> None:
    await _advance_ms(rig, (instant - rig.clock.now()) // timedelta(milliseconds=1))
    assert rig.clock.now() == instant


async def _book_the_entry_late(rig: ProtectionRig) -> None:
    """The exchange shows the entry after all (it was booked; the lookups only missed it)."""
    await rig.fake.place_entry(
        symbol=rig.entry.symbol,
        side=rig.entry.entry_side,
        position_side="BOTH",
        time_in_force="GTC",
        quantity=rig.entry.entry_quantity,
        price=D("60000.00"),
        new_client_order_id=rig.entry.entry_client_order_id,
    )


# --------------------------------------------------------------------------- #
# The record.
# --------------------------------------------------------------------------- #


def test_an_unknown_entry_needs_its_good_till_time_and_a_bool_flag() -> None:
    with pytest.raises(ValueError, match="entry_good_till_utc"):
        resting_entry_for_tests(entry_state_unknown=True)
    with pytest.raises(TypeError, match="entry_state_unknown"):
        resting_entry_for_tests(entry_state_unknown=1, entry_good_till_utc=GOOD_TILL)
    with pytest.raises(ValueError, match="entry_good_till_utc"):
        resting_entry_for_tests(entry_good_till_utc=GOOD_TILL.replace(tzinfo=None))
    entry = resting_entry_for_tests(entry_state_unknown=True, entry_good_till_utc=GOOD_TILL)
    assert entry.entry_state_unknown is True and entry.entry_good_till_utc == GOOD_TILL
    # An ACKED hand-off is unchanged: no flag, and the GTD time is optional.
    assert resting_entry_for_tests().entry_state_unknown is False


async def test_registration_journals_the_unknown_origin_and_blocks_nothing_new() -> None:
    rig = await _unknown_rig(exists=False)
    assert rig.transitions() == [("NONE", "AWAITING_FILL")]
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.last_reason == "REGISTERED_ENTRY_STATE_UNKNOWN"
    assert rig.coordinator.blocks_new_entries() is False


# --------------------------------------------------------------------------- #
# An entry that exists after all is protected.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["rest", "stream"])
async def test_an_unknown_entry_that_exists_gets_a_stop_after_a_fill(source: str) -> None:
    """The fill is protected by the normal flow; the entry is never sent again."""
    rig = await _unknown_rig(exists=True)
    sends_before = _sends(rig)
    await rig.coordinator.step()  # found NEW: still waiting for a fill
    assert _state(rig) is ProtectionState.AWAITING_FILL

    if source == "rest":
        rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    else:
        rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.UNPROTECTED
    stops = rig.fake.calls_to("place_algo_protective")
    assert len(stops) == 1
    assert stops[0]["kwargs"]["close_position"] is True
    assert stops[0]["kwargs"]["client_algo_id"] == rig.stop_id
    cancels = rig.fake.calls_to("cancel_normal_order")
    assert [c["kwargs"]["orig_client_order_id"] for c in cancels] == [rig.entry_id]

    await rig.clock.advance(1)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED
    assert _sends(rig) == sends_before  # nothing but the stop and the cancel was sent
    assert rig.safe_mode.entered_reasons == ["ENTRY_STATE_UNKNOWN"]


# --------------------------------------------------------------------------- #
# found=False never means "absent".
# --------------------------------------------------------------------------- #


async def test_found_false_for_a_long_time_never_forgets_and_never_resends() -> None:
    rig = await _unknown_rig(exists=False)
    # 50 steps, one every 30 s (25 minutes): before GTD + grace every step queries the entry.
    for _ in range(50):
        await rig.coordinator.step()
        await _advance_ms(rig, 30_000)
    assert rig.clock.now() < GOOD_TILL + timedelta(milliseconds=GRACE_MS)
    assert _state(rig) is ProtectionState.AWAITING_FILL
    assert _queries(rig) == 50
    # Then a whole day of steps, one a minute, far past GTD + grace.
    for _ in range(24 * 60):
        await rig.coordinator.step()
        await _advance_ms(rig, 60_000)
    assert _state(rig) is ProtectionState.ENTRY_UNRESOLVED
    assert _sends(rig) == {"place_entry": 0, "place_market_close": 0}
    assert rig.fake.calls_to("place_algo_protective") == []
    assert rig.fake.calls_to("cancel_normal_order") == []
    assert rig.inner_store.get_intent(approval_id=rig.entry.approval_id, role="STOP_LOSS") is None
    assert len(_unresolved_notes(rig)) == 1
    assert rig.coordinator.blocks_new_entries() is False
    assert rig.safe_mode.entered_reasons == ["ENTRY_STATE_UNKNOWN"]
    assert rig.safe_mode.in_safe_mode is True


# --------------------------------------------------------------------------- #
# GTD + grace: low-frequency polling, SAFE_MODE kept.
# --------------------------------------------------------------------------- #


async def test_after_gtd_plus_grace_it_polls_every_nth_step_and_keeps_safe_mode() -> None:
    rig = await _unknown_rig(exists=False)
    deadline = GOOD_TILL + timedelta(milliseconds=GRACE_MS)

    await _advance_to(rig, deadline - timedelta(milliseconds=1))
    await rig.coordinator.step()  # one millisecond short of GTD + grace: still every step
    assert _state(rig) is ProtectionState.AWAITING_FILL
    assert _unresolved_notes(rig) == []

    await _advance_ms(rig, 1)
    await rig.coordinator.step()  # reaching GTD + grace switches (the query still ran)
    assert _state(rig) is ProtectionState.ENTRY_UNRESOLVED
    assert rig.transitions() == [
        ("NONE", "AWAITING_FILL"),
        ("AWAITING_FILL", "ENTRY_UNRESOLVED"),
    ]
    (note,) = _unresolved_notes(rig)
    payload = json.loads(note.payload_json)
    assert payload["reason"] == "ENTRY_NOT_FOUND_AFTER_GTD_GRACE"
    assert payload["poll_every_n_steps"] == str(N)
    assert payload["entry_client_order_id"] == rig.entry_id
    assert _queries(rig) == 2

    # From now on the entry is queried only on every Nth step.
    seen: list[int] = []
    for _ in range(3 * N):
        await _advance_ms(rig, 60_000)
        await rig.coordinator.step()
        seen.append(_queries(rig))
    assert seen == [2 + (step + 1) // N for step in range(3 * N)]
    assert _queries(rig) == 2 + 3

    # Still tracked, one note only, SAFE_MODE kept, nothing new blocked, nothing sent.
    assert _state(rig) is ProtectionState.ENTRY_UNRESOLVED
    assert len(_unresolved_notes(rig)) == 1
    assert rig.safe_mode.entered_reasons == ["ENTRY_STATE_UNKNOWN"]
    assert rig.safe_mode.in_safe_mode is True
    assert rig.coordinator.blocks_new_entries() is False
    assert _sends(rig) == {"place_entry": 0, "place_market_close": 0}
    assert rig.fake.calls_to("place_algo_protective") == []


async def test_an_unresolved_entry_found_filled_on_the_nth_step_gets_a_stop() -> None:
    rig = await _unknown_rig(exists=False)
    await _advance_to(rig, GOOD_TILL + timedelta(milliseconds=GRACE_MS))
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.ENTRY_UNRESOLVED

    await _book_the_entry_late(rig)
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))  # REST only: no stream event
    for _ in range(N - 1):
        await rig.coordinator.step()
    assert rig.fake.calls_to("place_algo_protective") == []  # not queried yet
    await rig.coordinator.step()  # the Nth step queries and finds the fill
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    await rig.clock.advance(1)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED
    assert len(rig.fake.calls_to("place_entry")) == 1  # only the test's own late booking


async def test_a_stream_fill_of_an_unresolved_entry_is_acted_on_at_once() -> None:
    rig = await _unknown_rig(exists=False)
    await _advance_to(rig, GOOD_TILL + timedelta(milliseconds=GRACE_MS))
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.ENTRY_UNRESOLVED

    await _book_the_entry_late(rig)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # the first unresolved step: not an Nth step
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert len(rig.fake.calls_to("place_algo_protective")) == 1


async def test_an_unresolved_entry_found_open_returns_to_the_every_step_poll() -> None:
    rig = await _unknown_rig(exists=False)
    await _advance_to(rig, GOOD_TILL + timedelta(milliseconds=GRACE_MS))
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.ENTRY_UNRESOLVED

    await _book_the_entry_late(rig)  # open (NEW), not filled
    for _ in range(N):
        await rig.coordinator.step()
    assert _state(rig) is ProtectionState.AWAITING_FILL
    assert rig.transitions()[-1] == ("ENTRY_UNRESOLVED", "AWAITING_FILL")
    before = _queries(rig)
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _queries(rig) == before + 2
    # Found once, it never goes unresolved again.
    await _advance_ms(rig, 60_000)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.AWAITING_FILL


async def test_an_unresolved_entry_found_ended_without_a_fill_ends_the_plan() -> None:
    rig = await _unknown_rig(exists=False)
    await _advance_to(rig, GOOD_TILL + timedelta(milliseconds=GRACE_MS))
    await rig.coordinator.step()
    await _book_the_entry_late(rig)
    rig.fake.cancel(rig.entry_id)  # the exchange ended it with nothing executed
    for _ in range(N):
        await rig.coordinator.step()
    assert _state(rig) is ProtectionState.ENTRY_ENDED_NO_FILL
    assert rig.fake.calls_to("place_algo_protective") == []


async def test_an_acked_entry_never_becomes_unresolved() -> None:
    """Control: only an ENTRY_STATE_UNKNOWN entry switches; an ACKED one keeps every step."""
    rig = await make_rig(place_entry=False, entry_good_till_utc=GOOD_TILL)
    await _advance_to(rig, GOOD_TILL + timedelta(milliseconds=GRACE_MS) + timedelta(hours=1))
    for _ in range(N + 1):
        await rig.coordinator.step()
    assert _state(rig) is ProtectionState.AWAITING_FILL
    assert _queries(rig) == N + 1
    assert _unresolved_notes(rig) == []
