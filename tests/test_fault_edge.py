"""The test-only fault injection of the Demo campaign (plan 25-02, D-05, D-08).

TEST_ONLY: every object under test is a fake or an in-memory double; nothing here reaches Binance.
The tracer runs the REAL composed process (`build_wiring`) on the Binance-semantics fake and
injects one definitive stop rejection through the existing `exchange_edge` seam; the coordinator's
reaction (CLOSE_REQUIRED and a reduce-only close) is the production one. Later tests of this file
prove every mode of `FaultEdge` and `FaultPublic` on small stubs, the SDK-level faults under the
real adapter and REST gate, and the store faults.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from binance_common.errors import BadRequestError
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState
from src.live.wiring import TASK_SIGNAL_PUMP, check_wiring

from tests.support.fault_edge import FaultEdge
from tests.support.live_composed_rig import ComposedRig, make_composed_rig
from tests.support.live_rig import forbid_real_sleep


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


async def _drive_to_fill(rig: ComposedRig) -> tuple[object, str]:
    """Approve, confirm and fill one plan on the composed rig; returns (request, quantity)."""
    wiring = await rig.prepare()
    request = await rig.derive_request()
    (spec,) = [s for s in wiring.specs if s.name == TASK_SIGNAL_PUMP]
    await spec.run()
    short_id = next(iter(rig.memory.shadow.mappings))
    assert (await rig.press("APR", short_id, query_id="q-apr")).ok
    await rig.clock.advance(30)
    rig.set_prices()
    assert (await rig.press("CNF", short_id, query_id="q-cnf")).ok
    await wiring.service.drain()
    (placement,) = rig.fake.calls_to("place_entry")
    quantity = placement["kwargs"]["quantity"]
    rig.fake.fill(rig.entry_id(request), quantity=quantity)  # type: ignore[arg-type]
    routed = rig.route(rig.trade_frame(request, str(quantity)))  # type: ignore[arg-type]
    assert routed.fills == 1
    return request, str(quantity)


# --------------------------------------------------------------------------- #
# Task 1 - the tracer: an injected stop rejection reaches the real coordinator.
# --------------------------------------------------------------------------- #


async def test_a_fault_edge_keeps_the_composed_wiring_whole(tmp_path: Path) -> None:
    faults = FaultEdge()
    rig = make_composed_rig(tmp_path, faults=faults)
    wiring = await rig.prepare()
    assert check_wiring(wiring) == []
    assert wiring.exchange.adapter is faults
    assert wiring.exchange.gate is rig.assembly.exchange.gate


async def test_an_injected_stop_rejection_after_a_fill_ends_in_close_required_and_a_close(
    tmp_path: Path,
) -> None:
    faults = FaultEdge()
    rig = make_composed_rig(tmp_path, faults=faults)
    faults.raise_before_send(
        "place_algo_protective",
        BadRequestError(error_message="TEST_ONLY injected rejection", status_code=-2021),
    )
    request, quantity = await _drive_to_fill(rig)
    wiring = rig.wiring
    assert wiring is not None
    await wiring.coordinator.step()

    protection = wiring.coordinator.protection_of(request.plan.plan_hash)  # type: ignore[attr-defined]
    assert protection is not None
    assert protection.state in (ProtectionState.CLOSE_REQUIRED, ProtectionState.FLAT)
    # The rejection never reached the exchange; one reduce-only market close did.
    stop_id = derive_algo_client_id(
        plan_hash=request.plan.plan_hash,  # type: ignore[attr-defined]
        role=OrderRole.STOP_LOSS.value,
    )
    assert rig.fake.calls_to("place_algo_protective") == []
    (injected,) = faults.calls_to("place_algo_protective")
    assert injected["injected"] is True and injected["mode"] == "raise_before_send"
    assert injected["kwargs"]["client_algo_id"] == stop_id
    assert [(i.method, i.mode) for i in faults.injections] == [
        ("place_algo_protective", "raise_before_send")
    ]
    (close,) = rig.fake.calls_to("place_market_close")
    assert close["kwargs"]["side"] == "SELL"
    # The fake's market close is reduce-only by contract: it rejects an order that adds exposure.
    assert not rig.fake.positions.get("BTCUSDT"), "the close ended flat"
    assert str(close["kwargs"]["quantity"]) == quantity
    assert len(rig.fake.calls_to("place_entry")) == 1, "a placement is never re-sent"


async def test_an_injection_is_consumed_after_its_times(tmp_path: Path) -> None:
    faults = FaultEdge()
    rig = make_composed_rig(tmp_path, faults=faults)
    await rig.prepare()
    faults.raise_before_send("get_position_mode", RuntimeError("TEST_ONLY boom"), times=1)
    adapter = rig.assembly.exchange.adapter
    with pytest.raises(RuntimeError, match="TEST_ONLY boom"):
        await adapter.get_position_mode()
    await adapter.get_position_mode()  # the fault is gone: the call reaches the fake
    records = faults.calls_to("get_position_mode")
    assert [r["injected"] for r in records] == [True, False]


async def test_a_rig_without_faults_behaves_as_before(tmp_path: Path) -> None:
    rig = make_composed_rig(tmp_path)
    wiring = await rig.prepare()
    assert rig.faults is None and rig.sdk_faults is None and rig.store_faults is None
    assert wiring.exchange.adapter is rig.edge
    assert check_wiring(wiring) == []
