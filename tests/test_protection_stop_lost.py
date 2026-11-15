"""A once-confirmed stop that is later lost (19-REVIEW WR-04; owner decision, DECISIONS D077).

The owner's policy for a stop that was confirmed ACTIVE by REST and later reads ABSENT or
NOT_ACTIVE (decided by the position, research P6):

* confirmed positive exposure: CLOSE_REQUIRED and a MARKET close (B4); the stop is never
  re-placed;
* the position unreadable, or zero while the entry is not terminal: the plan is UNPROTECTED
  (blocking new entries) and ``stop_lost_at`` is recorded once, at the first detection, and never
  reset; a failed read neither clears the blocking state nor stops that clock;
* ``max_unprotected_ms`` from ``stop_lost_at`` without a safe state (position zero AND entry
  terminal) escalates to CLOSE_REQUIRED; with the position unreadable no MARKET close is sent
  with a guessed quantity (the closer's own rules decide);
* FLAT needs the two consecutive zero reads of CR-03.

Every test runs offline against the stateful Phase 19 fake exchange, the real
`MarketEmergencyCloser` and virtual time. The deadlines are the TEST_ONLY values of
tests/support/execution_limits.py, never a ratified number (`max_unprotected_ms` stays
NOT_CONFIGURED in the committed file). P6 (Demo probe, assumption A3) is not observed: a green
test proves agreement with the fake, not with Binance.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import pytest
from src.execution.protection import PlanProtection, ProtectionState

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal

# The TEST_ONLY deadlines of tests/support/execution_limits.py, in milliseconds.
MAX_UNPROTECTED_MS = 7777


def _view(rig: ProtectionRig) -> PlanProtection:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection


def _transition_reasons(rig: ProtectionRig) -> list[tuple[str, str, str]]:
    out = []
    for event in rig.journal.calls:
        if event.event_type == "PROTECTION_TRANSITION":
            body = json.loads(event.payload_json)
            out.append((body["from"], body["to"], body["reason"]))
    return out


def _states(rig: ProtectionRig) -> list[str]:
    return [to for _, to, _ in _transition_reasons(rig)]


def _place_calls(rig: ProtectionRig) -> int:
    return len(rig.fake.calls_to("place_algo_protective"))


def _close_required_alerts(rig: ProtectionRig) -> list[str]:
    return [a.reason for a in rig.alerts.alerts if a.event == "CLOSE_REQUIRED"]


async def _advance_ms(rig: ProtectionRig, milliseconds: int) -> None:
    await rig.clock.advance(milliseconds / 1000)


def _script_failures(rig: ProtectionRig, method: str, count: int) -> None:
    for _ in range(count):
        rig.fake.fail_next(method, RuntimeError("scripted ambiguous failure"))


def _script_position_read_failures(
    fake: BinanceSemanticsFakeAdapter, pattern: Iterable[bool]
) -> None:
    """The next `snapshot_positions` calls follow `pattern`: True raises, False is real."""
    script = deque(pattern)
    original = fake.snapshot_positions

    async def scripted(**kwargs: Any) -> Any:
        if script and script.popleft():
            fake._record_call("snapshot_positions", kwargs)
            raise RuntimeError("scripted position read failure")
        return await original(**kwargs)

    fake.snapshot_positions = scripted  # type: ignore[method-assign]


async def _to_protected_entry_open(rig: ProtectionRig, cancel_failures: int) -> None:
    """First fill 0.004, the stop confirmed ACTIVE by REST, the entry still open."""
    _script_failures(rig, "cancel_normal_order", cancel_failures)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # the stop is placed, the remainder cancel fails
    await rig.coordinator.step()  # REST: the stop is ACTIVE, the entry is still open
    assert _view(rig).state is ProtectionState.PROTECTED_ENTRY_OPEN
    assert _view(rig).stop_confirmed_at_utc is not None
    assert _place_calls(rig) == 1


async def test_wr04_stop_lost_position_unreadable_throughout_escalates_from_stop_lost_at() -> None:
    """PROTECTED_ENTRY_OPEN -> UNPROTECTED -> CLOSE_REQUIRED with the position never readable."""
    rig = await make_rig(real_closer=True)
    await _to_protected_entry_open(rig, cancel_failures=2)

    # The loss is first seen 1000 ms after the first fill, so a deadline measured from the
    # first fill would fire 1000 ms earlier than the one measured from stop_lost_at.
    await _advance_ms(rig, 1000)
    rig.fake.trigger_stop(rig.stop_id)
    _script_failures(rig, "snapshot_positions", 500)  # no position read succeeds from here on
    lost_at = rig.clock.now()
    stop_queries = len(rig.fake.calls_to("query_algo_order_by_client"))

    await rig.coordinator.step()  # REST: the stop is FINISHED; the position read fails
    assert _view(rig).state is ProtectionState.UNPROTECTED
    assert _transition_reasons(rig)[-1] == ("PROTECTED_ENTRY_OPEN", "UNPROTECTED", "STOP_LOST")
    assert rig.coordinator.blocks_new_entries() is True
    assert _view(rig).stop_lost_at_utc == lost_at
    assert rig.alerts.alerts == []
    assert rig.safe_mode.entered_reasons == []

    # Failed reads on every poll: still blocking, the clock is never reset, the lost stop is
    # never read or re-placed, and the plan never settles to PROTECTED although the entry is
    # terminal (the remainder cancel went through on the detection step).
    for _ in range(3):
        await _advance_ms(rig, 1000)
        await rig.coordinator.step()
        assert _view(rig).state is ProtectionState.UNPROTECTED
        assert rig.coordinator.blocks_new_entries() is True
        assert _view(rig).stop_lost_at_utc == lost_at
    assert _view(rig).entry_terminal_at_utc is not None
    assert len(rig.fake.calls_to("query_algo_order_by_client")) == stop_queries + 1

    await _advance_ms(rig, MAX_UNPROTECTED_MS - 3000 - 1)  # 1 ms short of the deadline
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.UNPROTECTED
    assert rig.alerts.alerts == []

    await _advance_ms(rig, 1)  # exactly max_unprotected_ms after stop_lost_at
    await rig.coordinator.step()
    assert ("UNPROTECTED", "CLOSE_REQUIRED", "B4_STOP_LOST_UNRESOLVED") in _transition_reasons(rig)
    # The closer could not read the quantity: nothing was sent, the close failed closed.
    assert _view(rig).state is ProtectionState.CLOSE_FAILED
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.fake.calls_to("place_market_close") == []
    # WR-C8: the close goes first, so the closer's own failure may enter SAFE_MODE before it.
    assert "CLOSE_REQUIRED" in rig.safe_mode.entered_reasons
    assert _close_required_alerts(rig) == ["B4_STOP_LOST_UNRESOLVED"]

    # Later steps keep reconciling: still no guessed close, still blocking, the coordinator's
    # CLOSE_REQUIRED alert stays one, and no stop is ever placed again.
    for _ in range(3):
        await _advance_ms(rig, 1000)
        await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.CLOSE_FAILED
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.fake.calls_to("place_market_close") == []
    assert _close_required_alerts(rig) == ["B4_STOP_LOST_UNRESOLVED"]
    assert _place_calls(rig) == 1
    assert "PROTECTED" not in _states(rig)


async def test_wr04_stop_lost_position_zero_entry_open_is_not_safe_and_escalates() -> None:
    """PROTECTED_ENTRY_OPEN -> UNPROTECTED -> CLOSE_REQUIRED: flat, but the entry can still fill."""
    rig = await make_rig(real_closer=True)
    await _to_protected_entry_open(rig, cancel_failures=1000)  # the entry stays open

    rig.fake.trigger_stop(rig.stop_id)  # the stop flattened the position
    assert rig.fake.positions["BTCUSDT"] == D("0")
    lost_at = rig.clock.now()
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.UNPROTECTED
    assert _transition_reasons(rig)[-1] == ("PROTECTED_ENTRY_OPEN", "UNPROTECTED", "STOP_LOST")
    assert rig.coordinator.blocks_new_entries() is True
    assert _view(rig).stop_lost_at_utc == lost_at

    await _advance_ms(rig, MAX_UNPROTECTED_MS - 1)
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.UNPROTECTED
    assert rig.alerts.alerts == []
    assert rig.fake.calls_to("place_market_close") == []

    await _advance_ms(rig, 1)
    await rig.coordinator.step()
    assert _transition_reasons(rig)[-1] == (
        "UNPROTECTED",
        "CLOSE_REQUIRED",
        "B4_STOP_LOST_UNRESOLVED",
    )
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    assert _close_required_alerts(rig) == ["B4_STOP_LOST_UNRESOLVED"]
    # Flat on two reads: nothing to close and nothing sent; the open entry keeps it blocking.
    assert rig.fake.calls_to("place_market_close") == []
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.CLOSE_REQUIRED
    assert rig.coordinator.blocks_new_entries() is True

    rig.fake.cancel(rig.entry_id)  # the entry finally ends
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.FLAT
    assert rig.coordinator.blocks_new_entries() is False
    assert _place_calls(rig) == 1
    assert _close_required_alerts(rig) == ["B4_STOP_LOST_UNRESOLVED"]


async def test_wr04_stop_lost_with_exposure_closes_at_once_and_never_places_a_stop() -> None:
    rig = await make_rig(real_closer=True)
    await _to_protected_entry_open(rig, cancel_failures=2)
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERED"  # not ACTIVE; the 0.004 is still open
    detected_at = rig.clock.now()
    placements_before = _place_calls(rig)

    await rig.coordinator.step()
    assert _transition_reasons(rig)[-1] == (
        "PROTECTED_ENTRY_OPEN",
        "CLOSE_REQUIRED",
        "B4_FILL_AFTER_STOP",
    )
    assert _view(rig).stop_lost_at_utc == detected_at
    assert [c["kwargs"]["quantity"] for c in rig.fake.calls_to("place_market_close")] == [
        D("0.004")
    ]
    for _ in range(3):
        await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.FLAT
    assert _place_calls(rig) == placements_before  # no stop placement call at all
    assert "UNPROTECTED" not in _states(rig)[2:]  # never parked: the exposure was confirmed
    assert _close_required_alerts(rig) == ["B4_FILL_AFTER_STOP"]


@pytest.mark.parametrize("how", ["canceled", "missing"])
async def test_wr04_a_canceled_or_missing_stop_is_never_replaced(how: str) -> None:
    """D077 overrides D034's automatic SL re-placement for a stop that was confirmed and is lost.

    `canceled`: REST finds the stop CANCELED (NOT_ACTIVE). `missing`: REST does not find it at
    all (ABSENT, the reading that re-places a stop that was never confirmed). Either way, with
    the position unreadable the plan is UNPROTECTED and nothing is placed; once the open 0.004
    is read it is B4 and closed by MARKET.
    """
    rig = await make_rig(real_closer=True)
    await _to_protected_entry_open(rig, cancel_failures=1000)
    if how == "canceled":
        rig.fake.cancel_algo(rig.stop_id)
    else:
        rig.fake.open_algos.pop(rig.stop_id)  # gone from the book and from the history
    _script_position_read_failures(rig.fake, [True, True, True])

    for _ in range(3):
        await rig.coordinator.step()
        assert _view(rig).state is ProtectionState.UNPROTECTED
        assert rig.coordinator.blocks_new_entries() is True
    assert _place_calls(rig) == 1

    await rig.coordinator.step()  # the position reads 0.004
    assert _transition_reasons(rig)[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B4_FILL_AFTER_STOP")
    assert [c["kwargs"]["quantity"] for c in rig.fake.calls_to("place_market_close")] == [
        D("0.004")
    ]
    assert _place_calls(rig) == 1


async def test_wr04_stop_lost_entry_terminal_unreadable_then_exposed_is_b4_not_protected() -> None:
    """The CR-03 interaction: a lost stop with a terminal entry no longer settles to PROTECTED.

    Before the fix the plan stayed PROTECTED_ENTRY_OPEN on the unreadable read, settled to
    PROTECTED on the next step (the stop was not read again) and attached take profits while the
    stop was not active.
    """
    rig = await make_rig(real_closer=True)
    await _to_protected_entry_open(rig, cancel_failures=2)
    await rig.coordinator.step()  # the remainder cancel goes through (entry read before it)
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERED"  # not ACTIVE; 0.004 still open
    _script_position_read_failures(rig.fake, [True])

    await rig.coordinator.step()  # entry terminal; the stop is lost; the position read fails
    assert _view(rig).entry_terminal_at_utc is not None
    assert _view(rig).state is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True

    await rig.coordinator.step()  # the position reads 0.004: B4 at once
    assert _transition_reasons(rig)[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B4_FILL_AFTER_STOP")
    assert [c["kwargs"]["quantity"] for c in rig.fake.calls_to("place_market_close")] == [
        D("0.004")
    ]
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.FLAT
    assert "PROTECTED" not in _states(rig)
    assert "COMPLETE" not in _states(rig)
    assert _place_calls(rig) == 1  # no take profit, no second stop


async def test_wr04_stop_lost_settles_flat_only_after_two_consecutive_zero_reads() -> None:
    rig = await make_rig(real_closer=True)
    await _to_protected_entry_open(rig, cancel_failures=2)
    await rig.coordinator.step()  # the remainder cancel goes through (entry read before it)
    rig.fake.trigger_stop(rig.stop_id)  # the stop flattened the position
    _script_position_read_failures(rig.fake, [True])

    await rig.coordinator.step()  # entry terminal; the stop is lost; the position read fails
    assert _view(rig).state is ProtectionState.UNPROTECTED

    # One zero read, then a failed confirming read: never FLAT, nothing swept.
    _script_position_read_failures(rig.fake, [False, True])
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.fake.calls_to("cancel_algo_order") == []

    reads_before = len(rig.fake.calls_to("snapshot_positions"))
    await rig.coordinator.step()  # two consecutive zero reads
    assert _transition_reasons(rig)[-1] == ("UNPROTECTED", "FLAT", "STOP_CONSUMED_FLAT")
    assert len(rig.fake.calls_to("snapshot_positions")) - reads_before == 2
    assert rig.coordinator.blocks_new_entries() is False
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.alerts.alerts == []
    assert "PROTECTED" not in _states(rig)
    assert _place_calls(rig) == 1
