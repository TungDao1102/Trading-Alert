"""A -1008 on a new entry never refuses the protective work of the process (quick task 261020-g1a).

Binance (general-info and error-code pages, WebFetch summary read 2026-10-20): -1008 "Request
throttled by system-level protection" means the node exceeded its concurrency; it is not counted
toward rate limits and reduce-only / close-position orders are exempt. Before this task the
adapter recorded it in the process-wide REST gate as a 429, so one -1008 on an entry paused every
REST call of the process and the protection coordinator's stop and remainder cancel, and the
emergency closer's reduce-only MARKET close, were refused with a `PreSendRefusal`.

The rig: the REAL `BinanceUsdmAdapter` (over a recording fake SDK) meets the -1008 on its entry;
the coordinator and the closer run over the Phase 19 fake exchange wrapped so that every adapter
coroutine first passes the SAME real `RestRateLimitGate` (one gate per process, plan 18-14). A
real 429 recorded in that gate still refuses them (the pause is never bypassed). Nothing sleeps
and nothing touches a network.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from binance_common.errors import BadRequestError
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.domain.exchange_errors import ExchangeErrorCategory
from src.execution.emergency_close import EmergencyCloseStatus, MarketEmergencyCloser
from src.execution.protection import ProtectionState

from tests.support.execution_limits import test_only_execution_limits
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.limits import test_only_signed_call_policy
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    TEST_ONLY_SYMBOL,
    RecordingAlerts,
    RecordingSafeMode,
    lot_filters_for_tests,
    make_rig,
    resting_entry_for_tests,
)
from tests.support.stream_sinks import RecordingJournal
from tests.support.virtual_time import VirtualTime

D = Decimal


class _GatedFake:
    """The fake exchange behind the process-wide gate: each coroutine checks the gate first."""

    def __init__(self, fake: BinanceSemanticsFakeAdapter, gate: RestRateLimitGate) -> None:
        self._fake = fake
        self._gate = gate

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._fake, name)
        if not inspect.iscoroutinefunction(target):
            return target

        async def gated(*args: Any, **kwargs: Any) -> Any:
            self._gate.check()
            return await target(*args, **kwargs)

        return gated


class _ThrottlingRest:
    """Fake SDK surface: every `new_order` answers -1008 (HTTP 400) and is counted."""

    def __init__(self) -> None:
        self.new_order_calls = 0

    def new_order(self, **_: Any) -> Any:
        self.new_order_calls += 1
        raise BadRequestError("Request throttled by system-level protection.", -1008)


async def _real_adapter_meets_1008(clock: VirtualTime) -> RestRateLimitGate:
    """The shared gate, after the real adapter's single entry POST was answered -1008."""
    policy = test_only_signed_call_policy()
    gate = RestRateLimitGate(policy=policy.rate_limit, clock=clock)
    rest = _ThrottlingRest()
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        signed_call_policy=policy,
        rest_gate=gate,
    )
    with pytest.raises(BadRequestError):
        await adapter.place_entry(
            symbol=TEST_ONLY_SYMBOL,
            side="BUY",
            position_side="BOTH",
            time_in_force="GTC",
            quantity=D("0.010"),
            price=D("100.0"),
            new_client_order_id="e" * 36,
        )
    assert rest.new_order_calls == 1  # one POST; the placement is never re-sent
    return gate


# --------------------------------------------------------------------------- #
# The coordinator: stop and remainder cancel are sent after a -1008 elsewhere.
# --------------------------------------------------------------------------- #


async def test_coordinator_places_the_stop_and_cancel_after_a_1008_entry() -> None:
    rig = await make_rig()
    gate = await _real_adapter_meets_1008(rig.clock)
    assert gate.restriction() is None
    rig.coordinator._adapter = _GatedFake(rig.fake, gate)  # type: ignore[assignment]

    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()

    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    assert len(rig.fake.calls_to("cancel_normal_order")) == 1
    not_sent = [
        e for e in rig.journal.calls if "NOT_SENT" in e.event_type or "not_sent" in e.payload_json
    ]
    assert not_sent == []

    await rig.clock.advance(1)
    await rig.coordinator.step()
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.PROTECTED
    assert rig.safe_mode.entered_reasons == []


async def test_a_real_429_in_the_shared_gate_still_refuses_the_stop() -> None:
    """Control: the fix bypasses nothing. A 429 pause still refuses the stop before sending."""
    rig = await make_rig()
    gate = await _real_adapter_meets_1008(rig.clock)
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
    rig.coordinator._adapter = _GatedFake(rig.fake, gate)  # type: ignore[assignment]

    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()

    assert rig.fake.calls_to("place_algo_protective") == []
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True


# --------------------------------------------------------------------------- #
# The emergency closer: the reduce-only MARKET close is sent after a -1008 elsewhere.
# --------------------------------------------------------------------------- #


def _closer_rig(clock: VirtualTime, gate: RestRateLimitGate) -> tuple[Any, Any, Any, Any]:
    fake = BinanceSemanticsFakeAdapter(now_utc=clock.now(), enforce_flat_stop_rejection=True)
    fake._apply_position_delta(TEST_ONLY_SYMBOL, D("0.010"), D("60000"))
    fake.set_lot_filters(TEST_ONLY_SYMBOL, lot_filters_for_tests())
    safe_mode = RecordingSafeMode()
    alerts = RecordingAlerts()
    closer = MarketEmergencyCloser(
        adapter=_GatedFake(fake, gate),
        journal=RecordingJournal(),
        safe_mode_controller=safe_mode,
        alert_sink=alerts,
        clock=clock,
        limits=test_only_execution_limits(),
    )
    return fake, closer, safe_mode, alerts


async def test_emergency_closer_closes_after_a_1008_entry() -> None:
    clock = VirtualTime()
    gate = await _real_adapter_meets_1008(clock)
    fake, closer, safe_mode, alerts = _closer_rig(clock, gate)

    flat = await closer.close_position(entry=resting_entry_for_tests(), reason="TEST_ONLY")

    assert flat is True
    assert closer.last_result is not None
    assert closer.last_result.status is EmergencyCloseStatus.FLAT
    assert len(fake.calls_to("place_market_close")) == 1
    assert safe_mode.entered_reasons == []
    assert alerts.alerts == []


async def test_a_real_429_in_the_shared_gate_still_refuses_the_close() -> None:
    clock = VirtualTime()
    gate = await _real_adapter_meets_1008(clock)
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
    fake, closer, _, _ = _closer_rig(clock, gate)

    flat = await closer.close_position(entry=resting_entry_for_tests(), reason="TEST_ONLY")

    assert flat is False
    assert fake.calls_to("place_market_close") == []
