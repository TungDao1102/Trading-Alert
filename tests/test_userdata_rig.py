"""Offline end-to-end rig of the user-data stream (Phase 18, plan 18-15 Task 1, EXEC-05, D-06).

The phase tracer: an SDK-shaped ORDER_TRADE_UPDATE (a real SDK `OrderTradeUpdate` model inside
the real `UserDataStreamEventsResponse`, built from SYNTHETIC frames, never captured Binance
data) goes through the real `UserDataAdapter` over the SDK-shaped fakes of plan 18-11, the
supervisor of plan 18-14 (LIVE only after a snapshot) and the router of plan 18-15, and ends as
a `FillEvent` that `fold_fills` turns into a `FoldedPositionView`. The stream is a hint; the
REST snapshot is the baseline (the flat `CurrentPositionView` stands for it here).

Time is virtual (`tests/support/virtual_time.py`), the listenKey port's worker thread is an
inline call, and a call of `asyncio.sleep` fails the test. Passing these tests is not evidence
of how live Binance frames behave.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_common.configuration import ConfigurationWebSocketStreams
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_userdata import SdkListenKeyPort, SdkUserDataTransport, UserDataAdapter
from src.adapters.binance_userdata_events import OrderUpdateEvent, parse_stream_message
from src.adapters.binance_userdata_router import (
    FillSource,
    KnownOrder,
    RouteResult,
    UserDataRouter,
)
from src.adapters.binance_userdata_supervisor import (
    StreamSnapshot,
    StreamState,
    TrustedEvent,
    UserDataSupervisor,
)
from src.domain.enums import OrderRole, OrderStatus
from src.execution.fill_monitor import CurrentPositionView, FoldedPositionView, fold_fills
from src.ops import redaction

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)
from tests.support.limits import test_only_rate_limit_policy, test_only_stream_limits
from tests.support.stream_sinks import (
    FakeOrderLookup,
    RecordingJournal,
    RecordingSinks,
    make_router,
)
from tests.support.userdata_frames import FRAME_LABEL
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START, VirtualTime
from tests.userdata_fakes import (
    TEST_ONLY_LISTEN_KEY,
    FakeRestUserDataApi,
    FakeUserDataWsClient,
    fresh_sdk_stream_map,
    make_order_trade_update_message,
)

ROUTER_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "adapters" / "binance_userdata_router.py"
)
TEST_ONLY_STREAM_URL = "wss://example.invalid"
# The client order id of the synthetic frame builder's default ORDER_TRADE_UPDATE.
TEST_ONLY_CLIENT_ID = "synthetic-entry-0001"
TEST_ONLY_EXCHANGE_ORDER_ID = 8_000_000_201
ENTRY = KnownOrder(
    local_order_id="test-only-local-order-0001",
    client_id=TEST_ONLY_CLIENT_ID,
    symbol="BTCUSDT",
    role=OrderRole.ENTRY,
    local_status=OrderStatus.NEW,
)
FLAT = CurrentPositionView(symbol="BTCUSDT", position_side="BOTH", position_amt=Decimal("0"))
# The REST snapshot the provider returns: fixed, opaque to the supervisor and the router.
FIXED_SNAPSHOT = StreamSnapshot(
    taken_at_utc=TEST_ONLY_VIRTUAL_START, payload={"positions": [], "label": "TEST_ONLY"}
)

# Two TRADE frames of one order (synthetic): 0.004 then 0.003, accumulated 0.004 and 0.007.
FIRST_TRADE: dict[str, Any] = {
    "i": TEST_ONLY_EXCHANGE_ORDER_ID,
    "t": 901,
    "l": "0.004",
    "z": "0.004",
}
SECOND_TRADE: dict[str, Any] = {
    "i": TEST_ONLY_EXCHANGE_ORDER_ID,
    "t": 902,
    "l": "0.003",
    "z": "0.007",
}


def test_frames_are_labelled_synthetic() -> None:
    assert FRAME_LABEL == "SYNTHETIC_FROM_SDK_MODEL"


# --------------------------------------------------------------------------- #
# Fixtures: isolation, no real sleep, inline worker thread.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> Any:
    return fresh_sdk_stream_map(monkeypatch)


@pytest.fixture(autouse=True)
def _isolated_redactor() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    calls: list[float] = []

    async def _forbidden(delay: float, result: Any = None) -> Any:
        calls.append(delay)
        raise AssertionError("asyncio.sleep called: the rig must use the injected sleep")

    monkeypatch.setattr(asyncio, "sleep", _forbidden)
    return calls


@pytest.fixture(autouse=True)
def _inline_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inline(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _inline)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def trusted(outcome: Any, *, after_gap: bool = False) -> TrustedEvent:
    return TrustedEvent(
        outcome=outcome,
        received_at_utc=TEST_ONLY_VIRTUAL_START,
        connection_epoch=1,
        after_gap=after_gap,
    )


def parsed(**order_overrides: Any) -> OrderUpdateEvent:
    outcome = parse_stream_message(
        make_order_trade_update_message(**order_overrides), observed_at_utc=TEST_ONLY_VIRTUAL_START
    )
    assert isinstance(outcome, OrderUpdateEvent)
    return outcome


def fold(sinks: RecordingSinks) -> FoldedPositionView:
    return fold_fills(fill_events=sinks.fill_events(), current_position_view=FLAT)


class _Factory:
    def __init__(self) -> None:
        self.built: list[FakeUserDataWsClient] = []

    def __call__(self, configuration: ConfigurationWebSocketStreams) -> FakeUserDataWsClient:
        client = FakeUserDataWsClient()
        self.built.append(client)
        return client


class StreamRig:
    """Real adapter + supervisor over the fakes, `on_event` bound to the router."""

    def __init__(self) -> None:
        self.vt = VirtualTime()
        self.gate = RestRateLimitGate(policy=test_only_rate_limit_policy(), clock=self.vt.now)
        self.rest = FakeRestUserDataApi()
        self.ws = FakeUserDataWsClient()
        self.factory = _Factory()
        self.transport = SdkUserDataTransport(
            ConfigurationWebSocketStreams(stream_url=TEST_ONLY_STREAM_URL),
            client_factory=self.factory,
            ws_client=self.ws,
        )
        limits = test_only_stream_limits()
        self.adapter = UserDataAdapter(
            transport=self.transport,
            listen_keys=SdkListenKeyPort(self.rest, rest_gate=self.gate),
            limits=limits,
            clock=self.vt.now,
        )
        self.sinks = RecordingSinks()
        self.journal = RecordingJournal()
        self.router = make_router(
            lookup=FakeOrderLookup.of(orders=[ENTRY]),
            journal=self.journal,
            sinks=self.sinks,
            clock=self.vt.now,
        )
        self.results: list[RouteResult] = []
        self.delivered: list[TrustedEvent] = []
        self.snapshot_calls = 0
        self.on_snapshot_call: Callable[[int], None] | None = None
        self.states: list[StreamState] = []
        self.supervisor = UserDataSupervisor(
            adapter=self.adapter,
            limits=limits,
            clock=self.vt.now,
            sleep=self.vt.sleep,
            rest_gate=self.gate,
            snapshot_provider=self._snapshot,
            on_state_change=lambda state, reason: self.states.append(state),
            on_event=self._on_event,
            on_snapshot=lambda snapshot, epoch: None,
            on_failure=lambda reason: None,
        )

    async def _snapshot(self) -> object:
        self.gate.check()
        self.snapshot_calls += 1
        if self.on_snapshot_call is not None:
            self.on_snapshot_call(self.snapshot_calls)
        return FIXED_SNAPSHOT

    def _on_event(self, event: TrustedEvent) -> None:
        self.delivered.append(event)
        self.results.append(self.router.route(event))

    def client(self) -> FakeUserDataWsClient:
        return self.factory.built[-1] if self.factory.built else self.ws

    def emit_trade(self, overrides: dict[str, Any]) -> int:
        return self.client().emit_user_event(
            TEST_ONLY_LISTEN_KEY, make_order_trade_update_message(**overrides)
        )

    async def start_live(self) -> None:
        await self.supervisor.start()
        await self.vt.settle()
        assert self.supervisor.state is StreamState.LIVE


# --------------------------------------------------------------------------- #
# Tracer: router only.
# --------------------------------------------------------------------------- #


def test_tracer_trade_frame_becomes_one_fill_and_an_idempotent_folded_view() -> None:
    sinks = RecordingSinks()
    router = make_router(
        lookup=FakeOrderLookup.of(orders=[ENTRY]),
        journal=RecordingJournal(),
        sinks=sinks,
        clock=lambda: TEST_ONLY_VIRTUAL_START,
    )
    event = parsed(**FIRST_TRADE)

    result = router.route(trusted(event))

    assert isinstance(router, UserDataRouter)
    assert result.handled is True
    assert result.fills == 1
    assert len(sinks.fills) == 1
    routed = sinks.fills[0]
    assert routed.source is FillSource.USER_DATA_EVENT
    assert routed.after_gap is False
    assert routed.fill.order_id == str(TEST_ONLY_EXCHANGE_ORDER_ID)
    assert routed.fill.exchange_trade_id == "901"

    view = fold(sinks)
    assert view.position_amt == Decimal("0.004")
    assert view.filled_quantity == Decimal("0.004")
    assert view.fill_count == 1

    # The same frame routed again: the fold keys on (order id, trade id), the view is unchanged.
    router.route(trusted(event))
    assert fold(sinks) == view


# --------------------------------------------------------------------------- #
# Rig: adapter + supervisor + router + fold.
# --------------------------------------------------------------------------- #


async def test_rig_live_trade_reaches_the_fill_sink_once_not_after_gap(
    real_sleep_calls: list[float],
) -> None:
    rig = StreamRig()
    await rig.start_live()
    assert rig.snapshot_calls == 1

    assert rig.emit_trade(FIRST_TRADE) == 1
    await rig.vt.settle()

    assert [routed.after_gap for routed in rig.sinks.fills] == [False]
    assert rig.sinks.fills[0].fill.exchange_trade_id == "901"
    assert rig.results[-1].handled is True
    view = fold(rig.sinks)
    assert view.position_amt == Decimal("0.004")
    assert view.fill_count == 1
    assert real_sleep_calls == []

    await rig.supervisor.stop(close_listen_key=False)


async def test_rig_trade_during_a_gap_is_released_after_the_snapshot_flagged_after_gap(
    real_sleep_calls: list[float],
) -> None:
    rig = StreamRig()
    fills_seen_during_snapshot: list[int] = []

    def _emit_during_second_snapshot(call: int) -> None:
        if call == 2:
            # UNKNOWN after the unsolicited close: the frame is held, nothing is routed yet.
            assert rig.emit_trade(SECOND_TRADE) == 1
            fills_seen_during_snapshot.append(len(rig.sinks.fills))

    rig.on_snapshot_call = _emit_during_second_snapshot
    await rig.start_live()
    assert rig.emit_trade(FIRST_TRADE) == 1
    await rig.vt.settle()
    assert len(rig.sinks.fills) == 1

    rig.ws.simulate_unsolicited_close()
    await rig.vt.settle()

    assert rig.supervisor.state is StreamState.LIVE
    assert StreamState.UNKNOWN in rig.states
    assert rig.snapshot_calls == 2
    # Held during the snapshot, released after it.
    assert fills_seen_during_snapshot == [1]
    assert [routed.after_gap for routed in rig.sinks.fills] == [False, True]
    assert [routed.fill.exchange_trade_id for routed in rig.sinks.fills] == ["901", "902"]

    # The folded view equals the view of the same fills routed in a plain order.
    plain_sinks = RecordingSinks()
    plain_router = make_router(
        lookup=FakeOrderLookup.of(orders=[ENTRY]),
        journal=RecordingJournal(),
        sinks=plain_sinks,
        clock=lambda: TEST_ONLY_VIRTUAL_START,
    )
    plain_router.route(trusted(parsed(**FIRST_TRADE)))
    plain_router.route(trusted(parsed(**SECOND_TRADE)))
    rig_view = fold(rig.sinks)
    assert rig_view == fold(plain_sinks)
    assert rig_view.position_amt == Decimal("0.007")
    assert rig_view.fill_count == 2
    assert rig.sinks.fallback_calls == []
    assert real_sleep_calls == []

    await rig.supervisor.stop(close_listen_key=False)


# --------------------------------------------------------------------------- #
# Structural guards (AST, plan 18-03 helpers).
# --------------------------------------------------------------------------- #


def test_router_module_imports_no_persistence_paper_or_sdk() -> None:
    assert forbidden_imports(ROUTER_PATH, ["src.persistence", "src.paper", "binance*"]) == []
    imports = module_imports(ROUTER_PATH)
    assert "src.execution.fill_monitor" in imports
    assert "src.adapters.binance_userdata_events" in imports
    # Only the stdlib, the event module, the fill monitor, src.domain and the redactor.
    project = [name for name in imports if name.startswith("src.")]
    assert all(
        name in {"src.adapters.binance_userdata_events", "src.execution.fill_monitor"}
        or name.startswith("src.domain.")
        or name == "src.ops.redaction"
        for name in project
    ), project


def test_router_module_reads_no_wall_clock_and_builds_no_float() -> None:
    assert wall_clock_calls(ROUTER_PATH) == []
    assert float_constructor_calls(ROUTER_PATH) == []
