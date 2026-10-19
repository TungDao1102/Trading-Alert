"""The Phase 18 stream drives Phase 19 protection end to end, offline (plan 19-11 Task 3).

A SYNTHETIC ORDER_TRADE_UPDATE frame (tests/support/userdata_frames.py, never captured Binance
data) is parsed, routed by the real `UserDataRouter` whose `fill_sink` is the coordinator's, and
the coordinator places the closePosition stop over the stateful fake exchange. Time is virtual
and a call of `asyncio.sleep` fails the test; nothing touches a network. Passing proves
agreement with the fake's labelled rules, not with live Binance frames.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_userdata_events import parse_stream_message
from src.adapters.binance_userdata_router import FillSource, KnownOrder, RoutedFill, UserDataRouter
from src.adapters.binance_userdata_supervisor import TrustedEvent
from src.domain.enums import OrderRole, OrderStatus
from src.execution.protection import ProtectionState

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    ProtectionRig,
    make_rig,
)
from tests.support.stream_sinks import (
    FakeOrderLookup,
    RecordingJournal,
    RecordingSinks,
    make_router,
)
from tests.support.userdata_frames import order_trade_update_frame

D = Decimal
PROTECTION_PATH = Path(__file__).resolve().parents[1] / "src" / "execution" / "protection.py"
TEST_ONLY_STREAM_ORDER_ID = 8_000_000_501


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    calls: list[float] = []

    async def _forbidden(delay: float, result: Any = None) -> Any:
        calls.append(delay)
        raise AssertionError("asyncio.sleep called: the rig must use the injected clock")

    monkeypatch.setattr(asyncio, "sleep", _forbidden)
    return calls


def _router_for(rig: ProtectionRig) -> tuple[UserDataRouter, RecordingSinks]:
    sinks = RecordingSinks()
    known = KnownOrder(
        local_order_id="test-only-local-order-0001",
        client_id=rig.entry_id,
        symbol=rig.entry.symbol,
        role=OrderRole.ENTRY,
        local_status=OrderStatus.NEW,
    )
    router = make_router(
        lookup=FakeOrderLookup.of(orders=[known]),
        journal=RecordingJournal(),
        sinks=sinks,
        clock=rig.clock,
        overrides={"fill_sink": rig.coordinator.fill_sink},
    )
    return router, sinks


def _trade_frame(rig: ProtectionRig, **overrides: Any) -> dict[str, Any]:
    return order_trade_update_frame(
        c=rig.entry_id,
        i=TEST_ONLY_STREAM_ORDER_ID,
        t=901,
        l="0.004",
        z="0.004",
        **overrides,
    )


def _route(router: UserDataRouter, rig: ProtectionRig, frame: dict[str, Any], *, after_gap: bool):
    received = rig.clock.now()
    outcome = parse_stream_message(frame, observed_at_utc=received)
    return router.route(
        TrustedEvent(
            outcome=outcome, received_at_utc=received, connection_epoch=1, after_gap=after_gap
        )
    )


@pytest.mark.parametrize("after_gap", [False, True])
async def test_a_routed_trade_frame_drives_the_stop_and_rest_confirmation(after_gap: bool) -> None:
    rig = await make_rig()
    router, sinks = _router_for(rig)
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))  # the exchange side of the same trade

    result = _route(router, rig, _trade_frame(rig), after_gap=after_gap)
    assert result.fills == 1  # the router handed the fill to the coordinator's sink

    await rig.coordinator.step()
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True
    placements = rig.fake.calls_to("place_algo_protective")
    assert len(placements) == 1
    assert placements[0]["kwargs"]["close_position"] is True
    assert placements[0]["kwargs"]["quantity"] is None
    assert len(rig.fake.calls_to("cancel_normal_order")) == 1

    await rig.coordinator.step()
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.PROTECTED
    assert rig.coordinator.blocks_new_entries() is False
    assert sinks.fills == []  # the recording sink was replaced by the coordinator's


async def test_a_rest_fallback_fill_is_accepted_as_first_fill_evidence() -> None:
    rig = await make_rig()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    fill = rig.fake.fill_events[-1]
    rig.coordinator.fill_sink(
        RoutedFill(fill=fill, source=FillSource.REST_FALLBACK, after_gap=True)
    )

    await rig.coordinator.step()

    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.UNPROTECTED
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    assert protection.last_reason == "FIRST_FILL_STREAM"


async def test_a_stream_fill_and_a_rest_only_fill_give_the_same_protection() -> None:
    stream = await make_rig()
    router, _ = _router_for(stream)
    stream.fake.fill(stream.entry_id, quantity=D("0.004"))
    _route(router, stream, _trade_frame(stream), after_gap=False)
    await stream.coordinator.step()
    await stream.coordinator.step()

    rest = await make_rig()
    rest.fake.fill(rest.entry_id, quantity=D("0.004"))
    await rest.coordinator.step()
    await rest.coordinator.step()

    for rig in (stream, rest):
        protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
        assert protection is not None
        assert protection.state is ProtectionState.PROTECTED
    assert [c["kwargs"] for c in stream.fake.calls_to("place_algo_protective")] == [
        c["kwargs"] for c in rest.fake.calls_to("place_algo_protective")
    ]


# --------------------------------------------------------------------------- #
# Purity guard (the module is on the Phase 19 pure list, plan 19-17).
# --------------------------------------------------------------------------- #

_STDLIB_ALLOWED = {
    "__future__",
    "asyncio",
    "collections",
    "collections.abc",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "json",
    "typing",
}


def test_protection_module_is_pure() -> None:
    for name in module_imports(PROTECTION_PATH):
        assert (
            name in _STDLIB_ALLOWED
            or name.startswith("src.domain")
            or name.startswith("src.execution.")
            or name == "src.persistence.errors"
        ), name
    assert not forbidden_imports(
        PROTECTION_PATH,
        ["binance*", "sqlalchemy", "pydantic", "polars", "pandas", "numpy", "src.adapters"],
    )
    assert float_constructor_calls(PROTECTION_PATH) == []
    assert wall_clock_calls(PROTECTION_PATH) == []
    assert "asyncio.sleep" not in PROTECTION_PATH.read_text(encoding="utf-8")
