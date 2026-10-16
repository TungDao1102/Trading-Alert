"""The user-data stream supervisor (Phase 18, plan 18-14, D-03, D-04, D-05, EXEC-05).

Every test runs the real `UserDataAdapter`, `SdkUserDataTransport` and `SdkListenKeyPort` over
the SDK-shaped fakes of plan 18-11 (`tests/userdata_fakes.py`), with the SDK module-global
stream map isolated per test. Time is virtual (`tests/support/virtual_time.py`): the clock and
the sleep are injected, nothing really sleeps, and a call of `asyncio.sleep` fails the test.
The listenKey port's worker thread is replaced by an inline call for these tests only, so the
event loop alone decides the order of everything (the worker thread itself is tested in
`tests/test_userdata_adapter.py`). Every limit is a TEST_ONLY value of
`tests/support/limits.py`; no ratified number appears here.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest
from binance_common.configuration import ConfigurationWebSocketStreams
from src.adapters import binance_userdata_supervisor as sup_mod
from src.adapters.binance_limits import StreamLimits
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_userdata import (
    ConnectionEvent,
    SdkListenKeyPort,
    SdkUserDataTransport,
    UserDataAdapter,
)
from src.adapters.binance_userdata_events import OrderUpdateEvent
from src.adapters.binance_userdata_supervisor import (
    StreamSnapshot,
    StreamState,
    TrustedEvent,
    UserDataSupervisor,
)
from src.ops import redaction

from tests.support.limits import test_only_rate_limit_policy, test_only_stream_limits
from tests.support.virtual_time import VirtualTime
from tests.userdata_fakes import (
    TEST_ONLY_LISTEN_KEY,
    FakeRestUserDataApi,
    FakeUserDataWsClient,
    fresh_sdk_stream_map,
    make_order_trade_update_message,
)

TEST_ONLY_STREAM_URL = "wss://example.invalid"
# Synthetic exchange order ids that tell the delivered events apart.
TEST_ONLY_ORDER_IDS = (8_000_000_101, 8_000_000_102, 8_000_000_103, 8_000_000_104)

S = StreamState


# --------------------------------------------------------------------------- #
# Fixtures: isolation, no real sleep, inline worker thread.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the SDK module-global stream map per test (research P6, P18)."""
    return fresh_sdk_stream_map(monkeypatch)


@pytest.fixture(autouse=True)
def _isolated_redactor() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Fail on any `asyncio.sleep`: every wait must go through the injected sleep."""
    calls: list[float] = []

    async def _forbidden(delay: float, result: Any = None) -> Any:
        calls.append(delay)
        raise AssertionError("asyncio.sleep called: the supervisor must use the injected sleep")

    monkeypatch.setattr(asyncio, "sleep", _forbidden)
    return calls


@pytest.fixture(autouse=True)
def _inline_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the port's SDK call inline so only the event loop orders the test."""

    async def _inline(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _inline)


# --------------------------------------------------------------------------- #
# Rig.
# --------------------------------------------------------------------------- #


class _Factory:
    """Client factory recording the fresh fake clients a rebuild creates."""

    def __init__(self, *, produce_connection: bool = True) -> None:
        self.built: list[FakeUserDataWsClient] = []
        self.produce_connection = produce_connection

    def __call__(self, configuration: ConfigurationWebSocketStreams) -> FakeUserDataWsClient:
        client = FakeUserDataWsClient(produce_connection=self.produce_connection)
        self.built.append(client)
        return client


class ScriptedSnapshots:
    """A snapshot provider: counts calls, runs an optional hook, may raise scripted errors."""

    def __init__(self) -> None:
        self.calls = 0
        self.failures: list[BaseException] = []
        self.fail_always: BaseException | None = None
        self.on_call: Callable[[int], Awaitable[None] | None] | None = None

    async def __call__(self) -> object:
        self.calls += 1
        if self.on_call is not None:
            result = self.on_call(self.calls)
            if inspect.isawaitable(result):
                await result
        if self.fail_always is not None:
            raise self.fail_always
        if self.failures:
            raise self.failures.pop(0)
        return {"snapshot": self.calls}


class Rig:
    """The real adapter stack over the fakes, a supervisor and recording sinks."""

    def __init__(
        self,
        *,
        limits: StreamLimits | None = None,
        rest: FakeRestUserDataApi | None = None,
        ws: FakeUserDataWsClient | None = None,
        factory: _Factory | None = None,
    ) -> None:
        self.vt = VirtualTime()
        self.limits = limits if limits is not None else test_only_stream_limits()
        self.gate = RestRateLimitGate(policy=test_only_rate_limit_policy(), clock=self.vt.now)
        self.rest = rest if rest is not None else FakeRestUserDataApi()
        self.ws = ws if ws is not None else FakeUserDataWsClient()
        self.factory = factory if factory is not None else _Factory()
        self.transport = SdkUserDataTransport(
            ConfigurationWebSocketStreams(stream_url=TEST_ONLY_STREAM_URL),
            client_factory=self.factory,
            ws_client=self.ws,
        )
        self.port = make_port(self.rest, self.gate)
        self.adapter = UserDataAdapter(
            transport=self.transport, listen_keys=self.port, limits=self.limits, clock=self.vt.now
        )
        self.snapshots_provider = ScriptedSnapshots()
        self.states: list[tuple[StreamState, str]] = []
        self.events: list[TrustedEvent] = []
        self.snapshots: list[tuple[StreamSnapshot, int]] = []
        self.failures: list[str] = []
        self.supervisor = UserDataSupervisor(
            adapter=self.adapter,
            limits=self.limits,
            clock=self.vt.now,
            sleep=self.vt.sleep,
            rest_gate=self.gate,
            snapshot_provider=self.snapshots_provider,
            on_state_change=lambda state, reason: self.states.append((state, reason)),
            on_event=self.events.append,
            on_snapshot=lambda snapshot, epoch: self.snapshots.append((snapshot, epoch)),
            on_failure=self.failures.append,
        )

    def client(self) -> FakeUserDataWsClient:
        """The fake client the transport currently holds (the last one built, else the first)."""
        return self.factory.built[-1] if self.factory.built else self.ws

    def emit_order(self, order_id: int) -> int:
        return self.client().emit_user_event(
            TEST_ONLY_LISTEN_KEY, make_order_trade_update_message(i=order_id)
        )

    def state_names(self) -> list[StreamState]:
        return [state for state, _ in self.states]

    def order_ids(self) -> list[tuple[str, bool]]:
        out: list[tuple[str, bool]] = []
        for event in self.events:
            assert isinstance(event.outcome, OrderUpdateEvent)
            out.append((event.outcome.exchange_order_id, event.after_gap))
        return out

    async def settle(self) -> None:
        await self.vt.settle()


def make_port(rest: FakeRestUserDataApi, gate: RestRateLimitGate) -> SdkListenKeyPort:
    del gate  # the port takes the shared gate from Task 2 on
    return SdkListenKeyPort(rest)


# --------------------------------------------------------------------------- #
# Task 1: tracer.
# --------------------------------------------------------------------------- #


async def test_tracer_start_live_close_unknown_rebuild_snapshot_live_after_gap(
    real_sleep_calls: list[float],
) -> None:
    rig = Rig()
    first, live_id, during_second, after_id = TEST_ONLY_ORDER_IDS

    def _emit_during_snapshot(call: int) -> None:
        # An event that arrives while the snapshot is being taken is held.
        rig.emit_order(first if call == 1 else during_second)

    rig.snapshots_provider.on_call = _emit_during_snapshot

    await rig.supervisor.start()
    await rig.settle()

    assert rig.state_names() == [S.CONNECTING, S.SYNCING, S.LIVE]
    assert rig.supervisor.state is S.LIVE
    assert rig.snapshots_provider.calls == 1
    assert [epoch for _, epoch in rig.snapshots] == [1]
    assert rig.snapshots[0][0].payload == {"snapshot": 1}
    assert rig.order_ids() == [(str(first), True)]

    # A live event is trusted at once.
    assert rig.emit_order(live_id) == 1
    await rig.settle()
    assert rig.order_ids()[-1] == (str(live_id), False)

    # Unsolicited close: UNKNOWN, rebuild (fresh client, stale name forgotten), new snapshot.
    rig.ws.simulate_unsolicited_close()
    await rig.settle()

    assert rig.state_names() == [S.CONNECTING, S.SYNCING, S.LIVE, S.UNKNOWN, S.SYNCING, S.LIVE]
    unknown_reason = rig.states[3][1]
    assert isinstance(unknown_reason, str) and unknown_reason
    assert rig.snapshots_provider.calls == 2
    assert rig.adapter.epoch == 2
    assert [epoch for _, epoch in rig.snapshots] == [1, 2]
    assert len(rig.factory.built) == 1
    diagnostics = rig.transport.diagnostics()
    assert diagnostics.rebuild_count == 1
    assert diagnostics.stale_listen_key_names_found == 1
    # The fresh client sent the SUBSCRIBE again: the stale name had been forgotten.
    assert [frame["params"] for frame in rig.factory.built[0].subscribe_frames] == [
        [TEST_ONLY_LISTEN_KEY]
    ]
    # The event that arrived between the close and the new LIVE was held, then released.
    assert rig.order_ids()[-1] == (str(during_second), True)
    assert rig.events[-1].connection_epoch == 2

    assert rig.emit_order(after_id) == 1
    await rig.settle()
    assert rig.order_ids()[-1] == (str(after_id), False)
    assert real_sleep_calls == []

    await rig.supervisor.stop(close_listen_key=False)


async def test_connection_callback_only_posts_and_commands_run_in_order() -> None:
    rig = Rig()
    await rig.supervisor.start()
    await rig.settle()

    listener = rig.supervisor._on_connection_event
    assert not inspect.iscoroutinefunction(listener)
    first_at = rig.vt.now()
    await rig.vt.advance(1)
    second_at = rig.vt.now()

    pending_before = rig.supervisor._commands.qsize()
    result = listener(ConnectionEvent(name="ping", at_utc=first_at, epoch=rig.adapter.epoch))
    assert result is None
    listener(ConnectionEvent(name="ping", at_utc=second_at, epoch=rig.adapter.epoch))
    # Posted, not handled: the callback returned before the control task ran.
    assert rig.supervisor._commands.qsize() == pending_before + 2
    await rig.settle()
    assert rig.supervisor.liveness().last_ping_at_utc == second_at

    # Two stream events posted back to back are delivered in order.
    rig.emit_order(TEST_ONLY_ORDER_IDS[0])
    rig.emit_order(TEST_ONLY_ORDER_IDS[1])
    await rig.settle()
    assert rig.order_ids() == [
        (str(TEST_ONLY_ORDER_IDS[0]), False),
        (str(TEST_ONLY_ORDER_IDS[1]), False),
    ]

    await rig.supervisor.stop(close_listen_key=False)


def test_module_exports() -> None:
    assert {"StreamState", "StreamSnapshot", "TrustedEvent", "UserDataSupervisor"} <= set(
        sup_mod.__all__
    )
