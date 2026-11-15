"""The coordinator reads "cancel sent, gone from the open-algo list" as success (plan 24-34, D-34).

Demo criterion 5 recorded that for about one second after an algo cancel the by-id query still
answers NEW while the open-algo list no longer shows the order. The sweeper learned this in plan
24-21; the coordinator's FLAT sweep still read the by-id answer alone, so it called the leg
STILL_OPEN, journaled `PROTECTION_SWEEP_UNVERIFIED` and cancelled the same legs again on every
step. A leg that the open list still shows stays not cancelled, as before.

Evidence label: executed tests with the Binance-semantics fake and its `algo_cancel_query_lag`
(plan 24-21) on virtual time; no network. The lag value is a TEST_ONLY number.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import EVENT_SWEEP_UNVERIFIED, ProtectionState

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal
LAG = timedelta(seconds=1)


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection.state


async def _to_complete(rig: ProtectionRig) -> None:
    rig.coordinator.fill_sink(rig.stream_fill(D("0.010")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.COMPLETE


def _unverified(rig: ProtectionRig) -> list[Any]:
    return [e for e in rig.journal.calls if e.event_type == EVENT_SWEEP_UNVERIFIED]


def _cancels(rig: ProtectionRig) -> list[str]:
    return [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("cancel_algo_order")]


async def _flat_with_resting_legs(rig: ProtectionRig) -> None:
    """TP2 is consumed: the position is flat and the stop and TP1 still rest on the exchange."""
    await _to_complete(rig)
    rig.fake.trigger_stop(
        derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_2")
    )


async def test_a_lagging_by_id_query_after_the_cancel_is_a_success() -> None:
    rig = await make_rig()
    rig.fake.algo_cancel_query_lag = LAG
    await _flat_with_resting_legs(rig)

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    first = _cancels(rig)
    assert len(first) == 3  # one cancel per leg, nothing else
    assert _unverified(rig) == []  # no PROTECTION_SWEEP_UNVERIFIED
    # The by-id query really lagged: it still answers NEW for the cancelled stop.
    stop = await rig.fake.query_algo_order_by_client(client_algo_id=rig.stop_id)
    assert stop.found is True and stop.algo_status == "NEW"

    # The sweep is done: later steps do not cancel the gone legs again.
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _cancels(rig) == first
    assert _unverified(rig) == []
    assert rig.safe_mode.entered_reasons == []


async def test_a_leg_still_in_the_open_list_stays_not_cancelled() -> None:
    rig = await make_rig()
    rig.fake.algo_cancel_query_lag = LAG
    await _flat_with_resting_legs(rig)
    # A stuck leg: the cancel is accepted but the order keeps resting (the open list shows it).
    stop_id = rig.stop_id
    original = rig.fake.cancel_algo_order

    async def stuck(*, symbol: str, client_algo_id: str) -> Any:
        if client_algo_id == stop_id:
            rig.fake._record_call("cancel_algo_order", {"client_algo_id": client_algo_id})
            return None
        return await original(symbol=symbol, client_algo_id=client_algo_id)

    rig.fake.cancel_algo_order = stuck  # type: ignore[method-assign]

    await rig.coordinator.step()

    notes = _unverified(rig)
    assert len(notes) == 1
    legs = json.loads(notes[0].payload_json)["legs"]
    assert legs["STOP_LOSS"] == "STILL_OPEN"
    # Retried by the next step, as before the change.
    before = len(_cancels(rig))
    await rig.coordinator.step()
    assert len(_cancels(rig)) > before


async def test_an_unreadable_open_list_keeps_the_old_unverified_result() -> None:
    rig = await make_rig()
    rig.fake.algo_cancel_query_lag = LAG
    await _flat_with_resting_legs(rig)

    async def broken(**kwargs: Any) -> Any:
        raise RuntimeError("list unavailable")

    rig.fake.snapshot_open_algo_orders = broken  # type: ignore[method-assign]

    await rig.coordinator.step()

    assert len(_unverified(rig)) == 1
    assert json.loads(_unverified(rig)[0].payload_json)["legs"]["STOP_LOSS"] == "STILL_OPEN"
