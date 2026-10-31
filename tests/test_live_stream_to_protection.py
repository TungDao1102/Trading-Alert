"""The user-data stream feeds the protection coordinator in the composed process (plan 24-18).

Every frame here is SYNTHETIC (built from the SDK models around `tests/support/userdata_frames.py`,
never captured Binance data) and is delivered at the TRANSPORT edge: `FakeUserDataWsClient` emits
it on the private stream, so it travels the real `SdkUserDataTransport`, `UserDataAdapter`,
`UserDataSupervisor`, `UserDataRouter` and the fill fan-out of `src/live/stream.py`, then the real
`ProtectionCoordinator` over the Binance-semantics fake exchange. Time is virtual, a call of
`asyncio.sleep` fails the test and the listen-key worker thread is an inline call. The only real
threads are the StoreExecutor writer (the day-loss writes) which the tests hold with events.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from binance_common.configuration import ConfigurationWebSocketStreams
from src.adapters.binance_client import ApiCredentials, Environment
from src.adapters.binance_userdata_router import FillSource, KnownOrder, RoutedFill
from src.adapters.binance_userdata_supervisor import StreamSnapshot, StreamState
from src.domain.enums import OrderRole, OrderStatus
from src.domain.exchange_errors import ExchangeErrorCategory
from src.execution.fill_monitor import FillEvent
from src.execution.liquidation_watch import LiquidationWatch
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import BRANCH_B6_LIQUIDATION_TOO_CLOSE, ProtectionState
from src.live.exchange import ExchangeBundle, build_exchange
from src.live.risk_inputs import build_liquidation_watch
from src.live.scheduler import Scheduler, TaskEvent, TaskSpec
from src.live.stream import (
    EVENT_FALLBACK_READ_FAILED,
    EVENT_FANOUT_MEMBER_FAILED,
    EVENT_ROUTE_FAILED,
    WOKEN_STEP_PASSES,
    StreamBundle,
    StreamSinks,
    build_stream,
    make_protection_step,
)
from src.ops.store_executor import WRITER_THREAD_PREFIX, StoreExecutor
from src.risk.liquidation import Bracket

from tests.support.execution_limits import test_only_execution_limits as execution_limits_for_tests
from tests.support.limits import test_only_binance_limits as binance_limits_for_tests
from tests.support.live_rig import TEST_ONLY_STREAM_ORDER_ID, forbid_real_sleep, make_live_rig
from tests.support.phase22_fixtures import demo_brackets
from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, make_rig
from tests.support.stream_sinks import FakeOrderLookup, RecordingJournal, RecordingSinks
from tests.support.userdata_frames import FRAME_LABEL
from tests.support.virtual_time import VirtualTime
from tests.userdata_fakes import (
    TEST_ONLY_LISTEN_KEY,
    FakeRestUserDataApi,
    FakeUserDataWsClient,
    fresh_sdk_stream_map,
    make_order_trade_update_message,
)

D = Decimal
TEST_ONLY_SESSION = "live-stream-test-0001"
# TEST_ONLY: the protection period, far beyond everything a test advances.
TEST_ONLY_PERIOD = timedelta(hours=1)
# PROTECTED, then the take profits are attached: all three follow a REST-confirmed stop.
CONFIRMED_STATES = frozenset(
    {ProtectionState.PROTECTED, ProtectionState.COMPLETE, ProtectionState.TP_UNAVAILABLE}
)


def test_frames_are_labelled_synthetic() -> None:
    assert FRAME_LABEL == "SYNTHETIC_FROM_SDK_MODEL"


@pytest.fixture(autouse=True)
def sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> Any:
    return fresh_sdk_stream_map(monkeypatch)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


@pytest.fixture(autouse=True)
def _inline_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inline(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _inline)


# --------------------------------------------------------------------------- #
# Spies and the harness.
# --------------------------------------------------------------------------- #


class EquitySpy:
    def __init__(self) -> None:
        self.reasons: list[str] = []
        self.fail = False

    def invalidate(self, *, reason: str) -> None:
        self.reasons.append(reason)
        if self.fail:
            raise ValueError("TEST_ONLY equity failure")


class DayRiskSpy:
    """Records `ingest_fill` with the thread it ran on; can be held by an event."""

    def __init__(self) -> None:
        self.fills: list[Any] = []
        self.threads: list[str] = []
        self.invalidations: list[str] = []
        self.entered = threading.Event()
        self.release: threading.Event | None = None
        self.timed_out = False
        self.fail_on_ingest = False

    def ingest_fill(self, fill: Any) -> None:
        self.entered.set()
        if self.release is not None and not self.release.wait(timeout=5.0):
            self.timed_out = True
        self.threads.append(threading.current_thread().name)
        if self.fail_on_ingest:
            raise OSError("TEST_ONLY writer failure")
        self.fills.append(fill)

    def invalidate(self, *, reason: str) -> None:
        self.invalidations.append(reason)


class CoordinatorSpy:
    def __init__(self) -> None:
        self.received: list[RoutedFill] = []
        self.fail = False

    def fill_sink(self, routed: RoutedFill) -> None:
        self.received.append(routed)
        if self.fail:
            raise RuntimeError("TEST_ONLY coordinator failure")


def _sinks(recording: RecordingSinks) -> StreamSinks:
    return StreamSinks(
        status_hint_sink=recording.status_hint_sink,
        exchange_state_sink=recording.exchange_state_sink,
        algo_sink=recording.algo_sink,
        account_sink=recording.account_sink,
        divergence_sink=recording.divergence_sink,
    )


def _exchange(tmp_path: Path, clock: VirtualTime, rest: FakeRestUserDataApi) -> ExchangeBundle:
    def factory(**kwargs: Any) -> Any:
        return SimpleNamespace(
            environment=kwargs["environment"],
            surfaces=kwargs["surfaces"],
            client=SimpleNamespace(rest_api=rest),
        )

    bundle = build_exchange(
        mode=Environment.DEMO,
        credentials=ApiCredentials(api_key="k", api_secret="s"),
        binance_limits=binance_limits_for_tests(),
        execution_limits=execution_limits_for_tests(),
        clock=clock,
        sleep=clock.sleep,
        gate_state_path=tmp_path / "gate-state.json",
        on_gate_alert=lambda alert: None,
        sdk_factory=factory,
    )
    bundle.gate_store.initialize(now_utc=clock.now(), operator_id="test")
    bundle.gate.restore()
    return bundle


@dataclass
class Harness:
    clock: VirtualTime
    exchange: ExchangeBundle
    rest: FakeRestUserDataApi
    built: list[FakeUserDataWsClient]
    stream: StreamBundle
    executor: StoreExecutor
    equity: EquitySpy
    day_risk: DayRiskSpy
    sinks: RecordingSinks
    journal: Any
    reasons: list[str] = field(default_factory=list)
    states: list[StreamState] = field(default_factory=list)

    @property
    def ws(self) -> FakeUserDataWsClient:
        """The latest fake SDK client (a rebuild after a gap builds a new one)."""
        return self.built[-1]

    def emit(self, client_id: str, *, trade_id: int = 901, quantity: str = "0.004") -> int:
        message = make_order_trade_update_message(
            c=client_id, i=TEST_ONLY_STREAM_ORDER_ID, t=trade_id, l=quantity, z=quantity
        )
        return self.ws.emit_user_event(TEST_ONLY_LISTEN_KEY, message)

    async def start_live(self) -> None:
        await self.stream.supervisor.start()
        await self.clock.settle()
        assert self.stream.supervisor.state is StreamState.LIVE

    async def flush(self) -> None:
        """Let the loop turn, then wait for every writer-thread job queued so far."""
        await self.clock.settle()
        await self.stream.fanout.drain()
        await self.executor.write(lambda: None)
        await self.clock.settle()

    async def close(self) -> None:
        await self.stream.supervisor.stop(close_listen_key=False)
        await self.stream.fanout.drain()
        await self.executor.aclose()


def make_harness(
    tmp_path: Path,
    *,
    clock: VirtualTime,
    journal: Any,
    coordinator: Any,
    index: Any,
    fills_reader: Any = None,
    rest: FakeRestUserDataApi | None = None,
) -> Harness:
    rest = rest or FakeRestUserDataApi()
    exchange = _exchange(tmp_path, clock, rest)
    built: list[FakeUserDataWsClient] = [FakeUserDataWsClient()]

    def ws_factory(configuration: ConfigurationWebSocketStreams) -> FakeUserDataWsClient:
        built.append(FakeUserDataWsClient())
        return built[-1]

    equity = EquitySpy()
    day_risk = DayRiskSpy()
    sinks = RecordingSinks()
    executor = StoreExecutor()
    reasons: list[str] = []
    states: list[StreamState] = []

    async def snapshot() -> object:
        exchange.gate.check()
        return StreamSnapshot(taken_at_utc=clock.now(), payload={"label": "TEST_ONLY"})

    stream = build_stream(
        exchange=exchange,
        stream_limits=binance_limits_for_tests().stream,
        clock=clock,
        sleep=clock.sleep,
        journal=journal,
        index=index,
        coordinator=coordinator,
        equity=equity,
        day_risk=day_risk,
        executor=executor,
        snapshot_provider=snapshot,
        sinks=_sinks(sinks),
        session_id=TEST_ONLY_SESSION,
        fills_reader=fills_reader,
        on_state_change=lambda state, reason: states.append(state),
        on_failure=reasons.append,
        stream_configuration=ConfigurationWebSocketStreams(stream_url="wss://example.invalid"),
        ws_client_factory=ws_factory,
        ws_client=built[0],
    )
    return Harness(
        clock=clock,
        exchange=exchange,
        rest=rest,
        built=built,
        stream=stream,
        executor=executor,
        equity=equity,
        day_risk=day_risk,
        sinks=sinks,
        journal=journal,
        reasons=reasons,
        states=states,
    )


def _protection_scheduler(
    clock: VirtualTime, stream: StreamBundle, coordinator: Any
) -> tuple[Scheduler, list[TaskEvent]]:
    events: list[TaskEvent] = []

    async def record(event: TaskEvent) -> None:
        events.append(event)

    scheduler = Scheduler(
        clock=clock,
        sleep=clock.sleep,
        record=record,
        specs=[
            TaskSpec(
                name="protection_step",
                run=make_protection_step(coordinator, stream.fanout),
                interval=TEST_ONLY_PERIOD,
                wake=stream.wake,
            )
        ],
    )
    return scheduler, events


# --------------------------------------------------------------------------- #
# Tracer: a frame at the transport edge ends in a REST-confirmed stop.
# --------------------------------------------------------------------------- #


async def test_a_fill_frame_at_the_transport_edge_ends_in_a_rest_confirmed_stop(
    tmp_path: Path,
) -> None:
    rig = await make_live_rig()
    coordinator = rig.wiring.coordinator
    h = make_harness(
        tmp_path,
        clock=rig.clock,
        journal=rig.journal,
        coordinator=coordinator,
        index=rig.wiring.index,
    )
    await h.start_live()
    placed_at: list[Any] = []
    original = rig.fake.place_algo_protective

    async def spy(**kwargs: Any) -> Any:
        placed_at.append(rig.clock.now())
        return await original(**kwargs)

    rig.fake.place_algo_protective = spy  # type: ignore[method-assign]
    scheduler, _ = _protection_scheduler(rig.clock, h.stream, coordinator)
    runner = asyncio.create_task(scheduler.run())
    await rig.clock.settle()
    first_tick = rig.clock.now() + TEST_ONLY_PERIOD

    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    assert len(rig.fake.calls_to("place_entry")) == 1
    assert rig.fake.calls_to("place_algo_protective") == []

    # The exchange fills part of the entry; only the stream tells the process. Nobody steps.
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    assert h.emit(rig.entry_id) == 1
    await h.flush()

    protection = coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None
    assert protection.state in CONFIRMED_STATES, "the stop was confirmed by REST"
    assert coordinator.blocks_new_entries() is False
    stop_id = derive_algo_client_id(plan_hash=rig.plan.plan_hash, role=OrderRole.STOP_LOSS.value)
    stops = [
        call
        for call in rig.fake.calls_to("place_algo_protective")
        if call["kwargs"]["client_algo_id"] == stop_id
    ]
    assert len(stops) == 1, "exactly one stop (the take profits are other algo orders)"
    assert stops[0]["kwargs"]["close_position"] is True
    assert len(rig.fake.calls_to("place_entry")) == 1, "a placement is never re-sent"
    assert placed_at and placed_at[0] < first_tick, "the stop did not wait for the periodic tick"
    assert h.sinks.divergences == []
    assert rig.journal.by_type(EVENT_FANOUT_MEMBER_FAILED) == []

    scheduler.stop()
    h.stream.wake.set()
    await rig.clock.advance(TEST_ONLY_PERIOD.total_seconds())
    await runner
    await h.close()


async def test_an_unknown_client_id_is_a_divergence_and_never_a_coordinator_input(
    tmp_path: Path,
) -> None:
    rig = await make_live_rig()
    h = make_harness(
        tmp_path,
        clock=rig.clock,
        journal=rig.journal,
        coordinator=rig.wiring.coordinator,
        index=rig.wiring.index,
    )
    await h.start_live()

    assert h.emit("x-foreign-client-id-0001") == 1
    await h.flush()

    assert len(h.sinks.divergences) == 1
    assert h.stream.fanout.fills_seen == 0
    assert not h.stream.wake.is_set()
    assert rig.wiring.coordinator.fill_sink_failures == 0
    assert rig.fake.calls_to("place_algo_protective") == []
    assert h.day_risk.fills == []
    await h.close()


async def test_a_gate_restriction_delays_the_listen_key_call_and_never_bypasses_it(
    tmp_path: Path,
) -> None:
    clock = VirtualTime()
    h = make_harness(
        tmp_path,
        clock=clock,
        journal=RecordingJournal(),
        coordinator=CoordinatorSpy(),
        index=FakeOrderLookup(),
    )
    h.exchange.gate.record(ExchangeErrorCategory.IP_BANNED, None)  # another holder met a 418

    await h.stream.supervisor.start()
    await clock.settle()

    assert h.rest.calls["start_user_data_stream"] == 0
    assert h.stream.supervisor.state is not StreamState.LIVE
    assert h.reasons == ["RATE_LIMIT_BAN_ACTIVE"]
    await h.close()


async def test_a_gap_makes_the_equity_and_the_day_loss_unknown(tmp_path: Path) -> None:
    clock = VirtualTime()
    h = make_harness(
        tmp_path,
        clock=clock,
        journal=RecordingJournal(),
        coordinator=CoordinatorSpy(),
        index=FakeOrderLookup(),
    )
    await h.start_live()
    h.equity.reasons.clear()
    h.day_risk.invalidations.clear()

    h.ws.simulate_unsolicited_close()
    await clock.settle()

    assert StreamState.UNKNOWN in h.states
    assert h.stream.supervisor.state is StreamState.LIVE
    assert h.equity.reasons == ["STREAM_GAP"]
    assert h.day_risk.invalidations == ["STREAM_GAP"]
    await h.close()


async def test_a_router_failure_is_journaled_and_never_escapes_into_the_supervisor(
    tmp_path: Path,
) -> None:
    clock = VirtualTime()
    journal = RecordingJournal()
    entry = KnownOrder(
        local_order_id="test-only-local-order-0001",
        client_id="synthetic-entry-0001",
        symbol="BTCUSDT",
        role=OrderRole.ENTRY,
        local_status=OrderStatus.NEW,
    )
    h = make_harness(
        tmp_path,
        clock=clock,
        journal=journal,
        coordinator=CoordinatorSpy(),
        index=FakeOrderLookup.of(orders=[entry]),
    )
    await h.start_live()

    def boom(item: Any) -> Any:
        raise RuntimeError("TEST_ONLY route failure with a secret-looking message")

    h.stream.router.route = boom  # type: ignore[method-assign]
    assert h.emit("synthetic-entry-0001") == 1
    await h.flush()

    assert h.stream.supervisor.state is StreamState.LIVE
    (row,) = journal.by_type(EVENT_ROUTE_FAILED)
    assert json.loads(row.payload_json) == {"error_class": "RuntimeError", "member": "router"}
    assert "secret" not in row.payload_json
    await h.close()


# --------------------------------------------------------------------------- #
# The liquidation watch runs from this path (D-24 activation).
# --------------------------------------------------------------------------- #


class _Brackets:
    async def get(self, *, symbol: str) -> Any:
        brackets: list[Bracket] = demo_brackets()
        return SimpleNamespace(brackets=brackets)


class _FeeRates:
    async def entry_fee_rate(self, *, symbol: str) -> Decimal | None:
        return D("0.0004")


def _watch() -> LiquidationWatch:
    return build_liquidation_watch(
        brackets=_Brackets(), fee_rates=_FeeRates(), limits=execution_limits_for_tests()
    )


async def test_the_post_fill_liquidation_check_runs_from_the_stream_path(
    tmp_path: Path,
) -> None:
    rig = await make_rig(liquidation_watch=_watch(), real_closer=True)
    original = rig.fake.snapshot_positions

    async def with_price(**kwargs: Any) -> Any:
        rows = await original(**kwargs)
        # TEST_ONLY: a liquidation price at the stop, which fails the comparison.
        return [replace(row, liquidation_price=rig.entry.sl_trigger_price) for row in rows]

    rig.fake.snapshot_positions = with_price  # type: ignore[method-assign]
    known = KnownOrder(
        local_order_id="test-only-local-order-0001",
        client_id=rig.entry_id,
        symbol=rig.entry.symbol,
        role=OrderRole.ENTRY,
        local_status=OrderStatus.NEW,
    )
    h = make_harness(
        tmp_path,
        clock=rig.clock,
        journal=rig.journal,
        coordinator=rig.coordinator,
        index=FakeOrderLookup.of(orders=[known]),
    )
    await h.start_live()
    scheduler, _ = _protection_scheduler(rig.clock, h.stream, rig.coordinator)
    runner = asyncio.create_task(scheduler.run())
    await rig.clock.settle()

    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    assert h.emit(rig.entry_id) == 1
    await h.flush()

    assert ("PROTECTED", "CLOSE_REQUIRED") in rig.transitions()
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", BRANCH_B6_LIQUIDATION_TOO_CLOSE)
    ]
    assert rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH) is not None
    scheduler.stop()
    h.stream.wake.set()
    await rig.clock.advance(TEST_ONLY_PERIOD.total_seconds())
    await runner
    await h.close()


# --------------------------------------------------------------------------- #
# The protection step body.
# --------------------------------------------------------------------------- #


async def test_the_step_body_runs_one_pass_per_tick_and_more_only_after_a_fill() -> None:
    class Counting:
        def __init__(self) -> None:
            self.steps = 0

        async def step(self) -> None:
            self.steps += 1

    counting = Counting()
    fanout = _unit_fanout(CoordinatorSpy(), EquitySpy(), DayRiskSpy(), RecordingJournal())[0]
    run = make_protection_step(counting, fanout)

    await run()
    await run()
    assert counting.steps == 2
    fanout(_routed("1", "1"))
    await run()
    assert counting.steps == 2 + WOKEN_STEP_PASSES
    await run()
    assert counting.steps == 3 + WOKEN_STEP_PASSES
    await fanout.drain()


# --------------------------------------------------------------------------- #
# The fan-out: never raises, never blocks, every member reacts.
# --------------------------------------------------------------------------- #


def _fill_event(order_id: str, trade_id: str) -> FillEvent:
    return FillEvent(
        order_id=order_id,
        exchange_trade_id=trade_id,
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        fill_price=D("50000"),
        fill_quantity=D("0.004"),
        fill_time_utc=VirtualTime().now(),
    )


def _routed(
    order_id: str,
    trade_id: str,
    *,
    after_gap: bool = False,
    source: FillSource = FillSource.USER_DATA_EVENT,
) -> RoutedFill:
    return RoutedFill(fill=_fill_event(order_id, trade_id), source=source, after_gap=after_gap)


def _unit_fanout(
    coordinator: Any, equity: Any, day_risk: Any, journal: Any, reader: Any = None
) -> tuple[Any, Any, StoreExecutor, asyncio.Event]:
    from src.live.stream import make_fill_fanout, make_fills_fallback

    clock = VirtualTime()
    executor = StoreExecutor()
    wake = asyncio.Event()
    fanout = make_fill_fanout(
        coordinator=coordinator,
        wake=wake,
        equity=equity,
        day_risk=day_risk,
        executor=executor,
        journal=journal,
        clock=clock,
        session_id=TEST_ONLY_SESSION,
    )
    fallback = make_fills_fallback(
        fanout=fanout,
        reader=reader,
        journal=journal,
        executor=executor,
        clock=clock,
        session_id=TEST_ONLY_SESSION,
    )
    return fanout, fallback, executor, wake


async def test_one_fill_reaches_the_coordinator_the_wake_the_equity_and_the_writer() -> None:
    coordinator, equity, day_risk = CoordinatorSpy(), EquitySpy(), DayRiskSpy()
    fanout, _, executor, wake = _unit_fanout(coordinator, equity, day_risk, RecordingJournal())

    fanout(_routed("10", "1"))
    await fanout.drain()

    assert len(coordinator.received) == 1
    assert wake.is_set()
    assert equity.reasons == ["ACCOUNT_UPDATE"]
    assert len(day_risk.fills) == 1
    assert day_risk.threads == [f"{WRITER_THREAD_PREFIX}_0"]
    await executor.aclose()


async def test_a_fill_after_a_gap_invalidates_the_equity_with_the_gap_reason() -> None:
    equity = EquitySpy()
    fanout, _, executor, _ = _unit_fanout(
        CoordinatorSpy(), equity, DayRiskSpy(), RecordingJournal()
    )
    fanout(_routed("10", "1", after_gap=True))
    await fanout.drain()
    assert equity.reasons == ["STREAM_GAP"]
    await executor.aclose()


async def test_a_failing_equity_member_skips_nobody_and_is_journaled_by_class() -> None:
    coordinator, equity, day_risk, journal = (
        CoordinatorSpy(),
        EquitySpy(),
        DayRiskSpy(),
        RecordingJournal(),
    )
    equity.fail = True
    fanout, _, executor, wake = _unit_fanout(coordinator, equity, day_risk, journal)

    fanout(_routed("10", "1"))
    await fanout.drain()

    assert len(coordinator.received) == 1 and wake.is_set() and len(day_risk.fills) == 1
    (row,) = journal.by_type(EVENT_FANOUT_MEMBER_FAILED)
    assert json.loads(row.payload_json) == {"error_class": "ValueError", "member": "equity"}
    assert fanout.member_failures == {"equity": 1}
    await executor.aclose()


async def test_a_failing_coordinator_member_still_wakes_and_updates_the_rest() -> None:
    coordinator, equity, day_risk, journal = (
        CoordinatorSpy(),
        EquitySpy(),
        DayRiskSpy(),
        RecordingJournal(),
    )
    coordinator.fail = True
    fanout, _, executor, wake = _unit_fanout(coordinator, equity, day_risk, journal)

    fanout(_routed("10", "1"))
    await fanout.drain()

    assert wake.is_set() and equity.reasons and len(day_risk.fills) == 1
    (row,) = journal.by_type(EVENT_FANOUT_MEMBER_FAILED)
    assert json.loads(row.payload_json)["member"] == "coordinator"
    await executor.aclose()


async def test_the_fan_out_returns_while_the_writer_is_blocked() -> None:
    coordinator, equity, day_risk = CoordinatorSpy(), EquitySpy(), DayRiskSpy()
    day_risk.release = threading.Event()
    fanout, _, executor, wake = _unit_fanout(coordinator, equity, day_risk, RecordingJournal())

    fanout(_routed("10", "1"))  # would deadlock here if the write ran inline

    assert len(coordinator.received) == 1 and wake.is_set() and equity.reasons
    entered = await asyncio.get_running_loop().run_in_executor(None, day_risk.entered.wait, 5.0)
    assert entered
    assert day_risk.fills == [], "the write is still held on the writer thread"
    fanout(_routed("10", "2"))  # a second fill is accepted while the first write is held
    assert len(coordinator.received) == 2
    day_risk.release.set()
    await fanout.drain()
    assert len(day_risk.fills) == 2 and day_risk.timed_out is False
    await executor.aclose()


async def test_a_failed_day_loss_write_makes_the_loss_unknown() -> None:
    day_risk, journal = DayRiskSpy(), RecordingJournal()
    day_risk.fail_on_ingest = True
    fanout, _, executor, _ = _unit_fanout(CoordinatorSpy(), EquitySpy(), day_risk, journal)

    fanout(_routed("10", "1"))
    await fanout.drain()

    assert day_risk.invalidations == ["ACCOUNT_UPDATE"]
    (row,) = journal.by_type(EVENT_FANOUT_MEMBER_FAILED)
    assert json.loads(row.payload_json) == {"error_class": "OSError", "member": "day_risk"}
    await executor.aclose()


def test_with_no_running_loop_the_day_loss_is_made_unknown_not_skipped() -> None:
    coordinator, equity, day_risk = CoordinatorSpy(), EquitySpy(), DayRiskSpy()
    fanout, _, executor, wake = _unit_fanout(coordinator, equity, day_risk, RecordingJournal())

    fanout(_routed("10", "1"))

    assert len(coordinator.received) == 1 and wake.is_set()
    assert day_risk.fills == [] and day_risk.invalidations == ["ACCOUNT_UPDATE"]
    executor.close()


# --------------------------------------------------------------------------- #
# fills_fallback: empty at once, the async read scheduled afterwards.
# --------------------------------------------------------------------------- #


class ReaderSpy:
    def __init__(self, fills: Sequence[FillEvent] = ()) -> None:
        self.calls: list[str] = []
        self.fills = list(fills)
        self.fail = False
        self.gate = asyncio.Event()

    async def __call__(self, order_id: str) -> Sequence[FillEvent]:
        self.calls.append(order_id)
        await self.gate.wait()
        if self.fail:
            raise ConnectionError("TEST_ONLY read failure")
        return self.fills


async def test_fills_fallback_returns_empty_at_once_and_reads_afterwards() -> None:
    reader = ReaderSpy([_fill_event("10", "7")])
    coordinator, day_risk = CoordinatorSpy(), DayRiskSpy()
    fanout, fallback, executor, _ = _unit_fanout(
        coordinator, EquitySpy(), day_risk, RecordingJournal(), reader
    )

    assert fallback("10") == ()
    assert reader.calls == [], "nothing was read inside the synchronous call"
    assert fallback("10") == (), "a second request for the same order is not scheduled again"
    await VirtualTime().settle(5)
    assert reader.calls == ["10"]
    assert coordinator.received == []
    reader.gate.set()
    await fanout.drain()

    assert reader.calls == ["10"]
    (routed,) = coordinator.received
    assert routed.source is FillSource.REST_FALLBACK and routed.after_gap is False
    assert len(day_risk.fills) == 1
    await executor.aclose()


async def test_a_failing_fallback_read_is_journaled_by_class_only() -> None:
    reader, journal = ReaderSpy(), RecordingJournal()
    reader.fail = True
    reader.gate.set()
    fanout, fallback, executor, _ = _unit_fanout(
        CoordinatorSpy(), EquitySpy(), DayRiskSpy(), journal, reader
    )

    assert fallback("10") == ()
    await fanout.drain()

    (row,) = journal.by_type(EVENT_FALLBACK_READ_FAILED)
    assert json.loads(row.payload_json) == {
        "error_class": "ConnectionError",
        "member": "fills_fallback",
    }
    assert "TEST_ONLY" not in row.payload_json
    assert fallback("10") == (), "after a failure the order can be requested again"
    await fanout.drain()
    await executor.aclose()


def test_fills_fallback_without_a_reader_or_a_loop_schedules_nothing() -> None:
    reader = ReaderSpy()
    _, fallback, executor, _ = _unit_fanout(
        CoordinatorSpy(), EquitySpy(), DayRiskSpy(), RecordingJournal(), reader
    )
    assert fallback("10") == ()  # no running loop: nothing scheduled, nothing raised
    assert fallback.scheduled == 0
    _, no_reader, executor2, _ = _unit_fanout(
        CoordinatorSpy(), EquitySpy(), DayRiskSpy(), RecordingJournal(), None
    )
    assert no_reader("10") == ()
    executor.close()
    executor2.close()
