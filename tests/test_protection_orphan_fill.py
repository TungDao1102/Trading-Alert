"""A stream fill that beats the plan's registration is not lost (first Demo run, 2026-11-01).

The exchange filled the entry 23 ms before `register_resting_entry` ran. The step journaled the
fill as unknown and dropped it, so the stop waited for the next REST pass 15 s later and the
reconcile saw an unprotected position. The coordinator now keeps a recent unowned fill and hands it
to the plan registered next on the same symbol and side. The REST pass would also place the stop,
so the tests read the REASON of the first transition: FIRST_FILL_STREAM or FIRST_FILL_REST.
"""

from __future__ import annotations

import json
from decimal import Decimal

from src.execution.protection import REASON_FIRST_FILL_REST, REASON_FIRST_FILL_STREAM

from tests.support.protection_doubles import (
    ProtectionRig,
    make_rig,
    resting_entry_for_tests,
)

D = Decimal


def _first_fill_reason(rig: ProtectionRig) -> str | None:
    for event in rig.journal.calls:
        if event.event_type != "PROTECTION_TRANSITION":
            continue
        body = json.loads(event.payload_json)
        if body["from"] == "AWAITING_FILL" and body["to"] == "UNPROTECTED":
            return str(body["reason"])
    return None


async def test_a_fill_before_the_registration_is_handled_as_a_stream_fill_on_register() -> None:
    rig = await make_rig(register=False)
    woken: list[bool] = []
    rig.coordinator.set_wake(lambda: woken.append(True))

    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # no plan owns the fill yet: it is journaled and kept
    assert rig.stop_row() is None

    rig.coordinator.register_resting_entry(rig.entry)
    assert woken == [True]

    await rig.coordinator.step()
    assert _first_fill_reason(rig) == REASON_FIRST_FILL_STREAM
    assert len(rig.fake.calls_to("place_algo_protective")) == 1


async def test_without_the_kept_fill_the_rest_pass_is_the_one_that_finds_it() -> None:
    # The control: the same exchange state, but the fill was never routed to the coordinator.
    rig = await make_rig(register=False)
    rig.stream_fill(D("0.004"))
    rig.coordinator.register_resting_entry(rig.entry)

    await rig.coordinator.step()

    assert _first_fill_reason(rig) == REASON_FIRST_FILL_REST


async def test_a_fill_older_than_the_bound_is_never_given_to_a_later_plan() -> None:
    rig = await make_rig(register=False)
    woken: list[bool] = []
    rig.coordinator.set_wake(lambda: woken.append(True))

    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.clock.advance(61)

    rig.coordinator.register_resting_entry(rig.entry)

    assert woken == []
    await rig.coordinator.step()
    assert _first_fill_reason(rig) == REASON_FIRST_FILL_REST


async def test_a_fill_for_the_other_side_is_not_given_to_the_plan() -> None:
    rig = await make_rig(register=False)
    woken: list[bool] = []
    rig.coordinator.set_wake(lambda: woken.append(True))
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()

    rig.coordinator.register_resting_entry(
        resting_entry_for_tests(entry_side="SELL", exit_side="BUY", side="SHORT")
    )

    assert woken == []
