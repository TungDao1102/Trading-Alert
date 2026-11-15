"""The step that reaches `max_unprotected_ms` still makes its re-place attempt (plan 20-31, W2).

The accepted wording of Phase 20 success criterion 2, case (1) (owner O-A): a never-confirmed stop
that REST proves absent (by-id query AND open-algo-orders listing both read in the step) is
re-placed under the SAME client id once per step, and the step that reaches the deadline STILL makes
that one attempt before it escalates to CLOSE_REQUIRED. The code order is in
`ProtectionCoordinator._supervise_plan`: the ABSENT branch places first, the deadline check follows.

`tests/test_protection_demo_shapes.py::test_when_neither_read_ever_shows_the_stop_there_is_one_
attempt_per_step_then_b2` counts the attempts of the steps BEFORE the deadline and asserts the
B2 escalation at the deadline, but never the placement count across the deadline step. These tests
do. Fakes only (the Demo-shaped lag of plan 20-27); nothing is [DEMO] evidence.
"""

from __future__ import annotations

from src.execution.protection import ProtectionState

from tests.support.protection_doubles import ProtectionRig
from tests.test_protection_demo_shapes import (
    MAX_UNPROTECTED_MS,
    DemoLag,
    _first_fill_step,
    _places,
    _state,
    _transition_reasons,
)


def _stop_placements(rig: ProtectionRig) -> list[int]:
    """Indices (in the fake's call log) of every stop placement."""
    return [i for i, c in enumerate(rig.fake.calls) if c["method"] == "place_algo_protective"]


def _first_index(rig: ProtectionRig, method: str) -> int | None:
    for i, call in enumerate(rig.fake.calls):
        if call["method"] == method:
            return i
    return None


async def test_the_step_that_reaches_the_deadline_still_makes_its_replace_attempt() -> None:
    rig = await _first_fill_step(DemoLag(by_id_absent=99, listing_hides=99))
    await rig.coordinator.step()  # one ordinary step before the deadline
    before_deadline = _places(rig)
    assert before_deadline == 2
    assert _state(rig) is ProtectionState.UNPROTECTED

    await rig.clock.advance(MAX_UNPROTECTED_MS / 1000)
    await rig.coordinator.step()  # the step that reaches max_unprotected_ms

    assert _places(rig) == before_deadline + 1  # the attempt was made on the deadline step
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    assert _transition_reasons(rig)[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B2_STOP_UNCONFIRMED")
    for call in rig.fake.calls_to("place_algo_protective"):
        assert call["kwargs"]["client_algo_id"] == rig.stop_id  # always the same id
        assert call["kwargs"]["trigger_price"] == rig.entry.sl_trigger_price


async def test_the_deadline_attempt_comes_before_the_close_escalation() -> None:
    rig = await _first_fill_step(DemoLag(by_id_absent=99, listing_hides=99))
    await rig.clock.advance(MAX_UNPROTECTED_MS / 1000)
    attempts_before = len(_stop_placements(rig))

    await rig.coordinator.step()

    placements = _stop_placements(rig)
    assert len(placements) == attempts_before + 1
    close_at = _first_index(rig, "place_market_close")
    if close_at is not None:  # the real closer may already have acted in the same step
        assert placements[-1] < close_at
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED


async def test_a_deadline_step_with_the_stop_listed_makes_no_attempt_and_no_escalation() -> None:
    """The attempt needs REST proof of absence; the listing showing the stop is REST proof of
    presence (plan 20-27), so there is no re-place and no escalation."""
    rig = await _first_fill_step(DemoLag(by_id_absent=99, listing_hides=0))
    before = _places(rig)
    await rig.clock.advance(MAX_UNPROTECTED_MS / 1000)

    await rig.coordinator.step()

    assert _places(rig) == before
    assert _state(rig) is ProtectionState.PROTECTED
    assert rig.fake.calls_to("place_market_close") == []
