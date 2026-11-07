"""The test-only fault injection of the Demo campaign (plan 25-02, D-05, D-08).

TEST_ONLY: every object under test is a fake or an in-memory double; nothing here reaches Binance.
The tracer runs the REAL composed process (`build_wiring`) on the Binance-semantics fake and
injects one definitive stop rejection through the existing `exchange_edge` seam; the coordinator's
reaction (CLOSE_REQUIRED and a reduce-only close) is the production one. Later tests of this file
prove every mode of `FaultEdge` and `FaultPublic` on small stubs, the SDK-level faults under the
real adapter and REST gate, and the store faults.
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_common.errors import BadRequestError
from src.adapters.binance_public import MarkPriceReading
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState
from src.live.wiring import TASK_SIGNAL_PUMP, check_wiring

from tests.support.ast_guards import float_constructor_calls, wall_clock_calls
from tests.support.fault_edge import (
    MODE_DROP_RESPONSE,
    MODE_HOLD,
    MODE_MOVED_MARK,
    MODE_MUTATE_PAYLOAD,
    MODE_OVERRIDE,
    MODE_RAISE_BEFORE_SEND,
    MODE_STALE_MARK,
    FaultEdge,
)
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


# --------------------------------------------------------------------------- #
# Task 2 - the remaining adapter and public-reader modes, on small stubs.
# --------------------------------------------------------------------------- #

D = Decimal
_REAL_SLEEP = asyncio.sleep  # captured before forbid_real_sleep: only ever sleep(0), a loop yield
T_MARK = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


class StubAdapter:
    """A stand-in signed adapter: records the kwargs it receives."""

    def __init__(self) -> None:
        self._rest_gate = object()
        self.received: list[tuple[str, dict[str, Any]]] = []

    async def place_entry(self, **kwargs: Any) -> str:
        self.received.append(("place_entry", dict(kwargs)))
        return "ACK"

    async def snapshot_positions(self, **kwargs: Any) -> str:
        self.received.append(("snapshot_positions", dict(kwargs)))
        return "REAL_POSITIONS"

    @staticmethod
    def error_facts(exc: BaseException) -> str:
        return f"facts:{type(exc).__name__}"


class StubPublic:
    def __init__(self) -> None:
        self._rest_gate = object()

    async def mark_price(self, symbol: str) -> MarkPriceReading:
        return MarkPriceReading(symbol=symbol, mark_price=D("50000"), exchange_time_utc=T_MARK)

    async def exchange_info(self, symbols: Any = None) -> list[str]:
        return ["INFO"]


@dataclass(frozen=True)
class StubBundle:
    adapter: Any
    public: Any
    gate: Any


def _installed() -> tuple[FaultEdge, StubAdapter, StubPublic, StubBundle]:
    faults = FaultEdge()
    adapter, public = StubAdapter(), StubPublic()
    gate = object()
    bundle = faults.install(StubBundle(adapter=adapter, public=public, gate=gate))
    assert bundle.gate is gate, "the gate is never replaced"
    assert bundle.adapter is faults and bundle.public is faults.public
    return faults, adapter, public, bundle


async def test_install_forwards_attributes_and_sync_methods_unchanged() -> None:
    faults, adapter, public, bundle = _installed()
    assert bundle.adapter._rest_gate is adapter._rest_gate
    assert bundle.public._rest_gate is public._rest_gate
    assert faults.error_facts(ValueError()) == "facts:ValueError"
    assert faults.calls_to("error_facts") == [], "a synchronous method is not recorded"
    assert await bundle.public.exchange_info() == ["INFO"]


async def test_mutate_payload_gives_the_inner_call_the_mutated_kwargs_and_keeps_both() -> None:
    faults, adapter, _, _ = _installed()
    faults.mutate_payload("place_entry", lambda kw: {**kw, "quantity": D("0.5")}, times=1)
    assert await faults.place_entry(symbol="BTCUSDT", quantity=D("1")) == "ACK"
    assert adapter.received == [("place_entry", {"symbol": "BTCUSDT", "quantity": D("0.5")})]
    (record,) = faults.calls_to("place_entry")
    assert record["kwargs"] == {"symbol": "BTCUSDT", "quantity": D("1")}
    assert record["mutated_kwargs"] == {"symbol": "BTCUSDT", "quantity": D("0.5")}
    assert (record["injected"], record["mode"]) == (True, MODE_MUTATE_PAYLOAD)
    # consumed: the next call is untouched
    await faults.place_entry(symbol="BTCUSDT", quantity=D("1"))
    assert adapter.received[-1][1]["quantity"] == D("1")
    assert faults.calls_to("place_entry")[-1]["injected"] is False


async def test_drop_response_after_send_runs_the_inner_call_once_then_raises() -> None:
    faults, adapter, _, _ = _installed()
    faults.drop_response_after_send("place_entry", TimeoutError("TEST_ONLY lost ACK"))
    with pytest.raises(TimeoutError, match="lost ACK"):
        await faults.place_entry(symbol="BTCUSDT")
    assert len(adapter.received) == 1, "the order reached the inner object exactly once"
    (record,) = faults.calls_to("place_entry")
    assert (record["injected"], record["mode"]) == (True, MODE_DROP_RESPONSE)
    assert await faults.place_entry(symbol="BTCUSDT") == "ACK"  # consumed
    assert len(adapter.received) == 2


async def test_hold_blocks_the_next_call_until_release_without_sleeping(
    real_sleep_calls: list[float],
) -> None:
    faults, adapter, _, _ = _installed()
    faults.hold("place_entry")
    task = asyncio.ensure_future(faults.place_entry(symbol="BTCUSDT"))
    for _ in range(5):
        if faults.held("place_entry"):
            break
        await _REAL_SLEEP(0)
    assert faults.held("place_entry") is True
    assert adapter.received == [], "the held call has not reached the inner object"
    assert not task.done()
    faults.release("place_entry")
    assert await task == "ACK"
    assert faults.held("place_entry") is False
    assert len(adapter.received) == 1
    assert real_sleep_calls == []
    (record,) = faults.calls_to("place_entry")
    assert (record["injected"], record["mode"]) == (True, MODE_HOLD)


async def test_release_before_the_call_arrives_and_release_with_nothing_held() -> None:
    faults, adapter, _, _ = _installed()
    with pytest.raises(ValueError, match="nothing is held"):
        faults.release("place_entry")
    faults.hold("place_entry")
    faults.release("place_entry")  # pre-release the pending hold
    assert await faults.place_entry(symbol="BTCUSDT") == "ACK"
    assert len(adapter.received) == 1


async def test_override_returns_the_scripted_answer_without_calling_inner_until_cleared() -> None:
    faults, adapter, _, _ = _installed()

    async def rows(**kwargs: Any) -> str:
        return f"LOSS_ROW:{kwargs['symbol']}"

    faults.override("snapshot_positions", rows)  # times=None: until clear
    assert await faults.snapshot_positions(symbol="BTCUSDT") == "LOSS_ROW:BTCUSDT"
    assert await faults.snapshot_positions(symbol="ETHUSDT") == "LOSS_ROW:ETHUSDT"
    assert adapter.received == []
    assert [r["mode"] for r in faults.calls_to("snapshot_positions")] == [MODE_OVERRIDE] * 2
    faults.clear("snapshot_positions")
    assert await faults.snapshot_positions(symbol="BTCUSDT") == "REAL_POSITIONS"


async def test_two_faults_on_one_method_are_consumed_in_registration_order() -> None:
    faults, adapter, _, _ = _installed()
    faults.raise_before_send("place_entry", RuntimeError("first"))
    faults.drop_response_after_send("place_entry", RuntimeError("second"))
    with pytest.raises(RuntimeError, match="first"):
        await faults.place_entry(symbol="A")
    with pytest.raises(RuntimeError, match="second"):
        await faults.place_entry(symbol="B")
    assert [s for _, kw in adapter.received for s in kw.values()] == ["B"]
    assert [(i.mode, i.sequence) for i in faults.injections] == [
        (MODE_RAISE_BEFORE_SEND, 1),
        (MODE_DROP_RESPONSE, 2),
    ]
    assert await faults.place_entry(symbol="C") == "ACK"


async def test_stale_mark_moves_the_observation_time_back_for_one_symbol_only() -> None:
    faults, _, _, bundle = _installed()
    faults.public.stale_mark("BTCUSDT", timedelta(seconds=90))
    stale = await bundle.public.mark_price("BTCUSDT")
    assert stale.exchange_time_utc == T_MARK - timedelta(seconds=90)
    assert stale.exchange_time_utc.tzinfo is not None
    assert stale.mark_price == D("50000") and isinstance(stale.mark_price, Decimal)
    other = await bundle.public.mark_price("ETHUSDT")
    assert other.exchange_time_utc == T_MARK
    (injected,) = [r for r in faults.calls_to("mark_price") if r["injected"]]
    assert injected["mode"] == MODE_STALE_MARK and injected["kwargs"] == {"symbol": "BTCUSDT"}
    faults.public.clear_marks()
    assert (await bundle.public.mark_price("BTCUSDT")).exchange_time_utc == T_MARK


async def test_moved_mark_returns_the_given_decimal_price_and_refuses_a_float() -> None:
    faults, _, _, bundle = _installed()
    faults.moved_mark("BTCUSDT", D("49000.5"), times=1)
    moved = await bundle.public.mark_price("BTCUSDT")
    assert moved.mark_price == D("49000.5") and moved.exchange_time_utc == T_MARK
    assert (await bundle.public.mark_price("BTCUSDT")).mark_price == D("50000"), "consumed"
    with pytest.raises(TypeError):
        faults.public.moved_mark("BTCUSDT", 49000.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="age"):
        faults.public.stale_mark("BTCUSDT", timedelta(seconds=-1))
    assert [i.mode for i in faults.injections] == [MODE_MOVED_MARK]


def test_the_module_reads_no_clock_no_float_and_awaits_no_sleep() -> None:
    path = Path(__file__).parent / "support" / "fault_edge.py"
    assert wall_clock_calls(path) == []
    assert float_constructor_calls(path) == []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    awaited = {
        ast.unparse(node.value.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
    }
    assert "asyncio.sleep" not in awaited
