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

import ast
import asyncio
import dataclasses
import inspect
import random
from collections.abc import Awaitable, Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from binance_common.configuration import ConfigurationWebSocketStreams
from binance_common.errors import (
    BadRequestError,
    RateLimitBanError,
    ServerError,
    TooManyRequestsError,
    UnauthorizedError,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.listen_key_expired import (  # noqa: E501
    ListenKeyExpired as SdkListenKeyExpired,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.user_data_stream_events_response import (  # noqa: E501
    UserDataStreamEventsResponse,
)
from src.adapters import binance_userdata_supervisor as sup_mod
from src.adapters.binance_limits import StreamLimits
from src.adapters.binance_ratelimit_gate import (
    GATE_NOT_RESTORED,
    GATE_STATE_UNKNOWN,
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    GateRecoveryStatus,
    GateStateStore,
    RateLimitBanActive,
    RestRateLimitGate,
)
from src.adapters.binance_userdata import (
    ConnectionEvent,
    SdkListenKeyPort,
    SdkUserDataTransport,
    UserDataAdapter,
)
from src.adapters.binance_userdata_events import (
    ListenKeyExpiredEvent,
    OrderUpdateEvent,
    StreamAnomaly,
)
from src.adapters.binance_userdata_supervisor import (
    LivenessSnapshot,
    StreamSnapshot,
    StreamState,
    TrustedEvent,
    UserDataSupervisor,
    stream_is_stale,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from src.ops import redaction
from src.ops.rest_gate_state import FileGateStateStore

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)
from tests.support.limits import (
    TEST_ONLY_KEEPALIVE_FAILURE_TOLERANCE,
    TEST_ONLY_KEEPALIVE_INTERVAL_SECONDS,
    TEST_ONLY_MAX_LIVENESS_AGE_SECONDS,
    TEST_ONLY_PROJECT_ROTATION_INTERVAL_SECONDS,
    TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS,
    TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS,
    TEST_ONLY_RECONNECT_MAX_ATTEMPTS,
    TEST_ONLY_RECONNECT_WAIT_MAX_SECONDS,
    TEST_ONLY_RECONNECT_WAIT_MULTIPLIER_SECONDS,
    TEST_ONLY_SNAPSHOT_DEADLINE_SECONDS,
    TEST_ONLY_SNAPSHOT_MAX_ATTEMPTS,
    TEST_ONLY_SNAPSHOT_WAIT_MAX_SECONDS,
    test_only_rate_limit_policy,
    test_only_stream_limits,
)
from tests.support.userdata_frames import listen_key_expired_frame
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START, VirtualTime
from tests.userdata_fakes import (
    TEST_ONLY_LISTEN_KEY,
    TEST_ONLY_SECOND_LISTEN_KEY,
    FakeRestUserDataApi,
    FakeUserDataWsClient,
    fresh_sdk_stream_map,
    make_order_trade_update_message,
)

KEEPALIVE = TEST_ONLY_KEEPALIVE_INTERVAL_SECONDS
TOLERANCE = TEST_ONLY_KEEPALIVE_FAILURE_TOLERANCE
ROTATION = TEST_ONLY_PROJECT_ROTATION_INTERVAL_SECONDS
WAIT_429 = TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS
CAP = TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS
MAX_AGE = TEST_ONLY_MAX_LIVENESS_AGE_SECONDS
# The SDK error text planted in every SDK error (never asserted on, never decided from).
TEST_ONLY_SDK_MESSAGE = "sdk-detail-text"
_C = ExchangeErrorCategory

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
    """A snapshot provider: counts calls, runs an optional hook, may raise scripted errors.

    With a gate it behaves like another REST holder of the process: it consults the gate
    before "sending" and a refused call is not counted.
    """

    def __init__(self, gate: RestRateLimitGate | None = None) -> None:
        self.gate = gate
        self.calls = 0
        self.failures: list[BaseException] = []
        self.fail_always: BaseException | None = None
        self.on_call: Callable[[int], Awaitable[None] | None] | None = None

    async def __call__(self) -> object:
        if self.gate is not None:
            self.gate.check()
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
        gate_store: GateStateStore | None = None,
    ) -> None:
        self.vt = VirtualTime()
        self.limits = limits if limits is not None else test_only_stream_limits()
        self.gate = RestRateLimitGate(
            policy=test_only_rate_limit_policy(), clock=self.vt.now, state_store=gate_store
        )
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
        self.snapshots_provider = ScriptedSnapshots(self.gate)
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

    def emit_order(self, order_id: int, key: str = TEST_ONLY_LISTEN_KEY) -> int:
        return self.client().emit_user_event(key, make_order_trade_update_message(i=order_id))

    def state_names(self) -> list[StreamState]:
        return [state for state, _ in self.states]

    def order_ids(self) -> list[tuple[str, bool]]:
        out: list[tuple[str, bool]] = []
        for event in self.events:
            if isinstance(event.outcome, OrderUpdateEvent):
                out.append((event.outcome.exchange_order_id, event.after_gap))
        return out

    def listen_key_posts(self) -> int:
        return self.rest.calls["start_user_data_stream"]

    def keepalives(self) -> int:
        return self.rest.calls["keepalive_user_data_stream"]

    async def settle(self) -> None:
        await self.vt.settle()

    async def start_live(self) -> None:
        await self.supervisor.start()
        await self.settle()
        assert self.supervisor.state is S.LIVE

    async def stop(self) -> None:
        await self.supervisor.stop(close_listen_key=False)


def limits_with(**overrides: Any) -> StreamLimits:
    """The TEST_ONLY stream limits with some fields replaced (no rotation unless asked)."""
    base = dataclasses.replace(test_only_stream_limits(), project_rotation_interval_seconds=None)
    return dataclasses.replace(base, **overrides)


def expiry_message() -> UserDataStreamEventsResponse:
    """A listenKeyExpired frame through the SDK model (synthetic key, never a credential)."""
    return UserDataStreamEventsResponse(SdkListenKeyExpired.from_dict(listen_key_expired_frame()))


def make_port(rest: FakeRestUserDataApi, gate: RestRateLimitGate) -> SdkListenKeyPort:
    return SdkListenKeyPort(rest, rest_gate=gate)


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


def sdk_stream_map_of() -> dict[Any, Any]:
    from binance_common import websocket as sdk_websocket

    stream_map: dict[Any, Any] = sdk_websocket.global_stream_connections.stream_connections_map
    return stream_map


# --------------------------------------------------------------------------- #
# Task 2: keepalive.
# --------------------------------------------------------------------------- #


async def test_keepalive_success_records_ok_time_and_keeps_live() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    assert rig.keepalives() == 0

    await rig.vt.advance(KEEPALIVE)

    assert rig.keepalives() == 1
    liveness = rig.supervisor.liveness()
    assert liveness.last_keepalive_ok_at_utc == rig.vt.now()
    assert liveness.consecutive_keepalive_failures == 0
    assert rig.supervisor.state is S.LIVE
    assert rig.state_names() == [S.CONNECTING, S.SYNCING, S.LIVE]
    await rig.stop()


async def test_keepalive_count_equals_intervals_elapsed_over_a_long_period() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    elapsed = 0
    # Uneven steps, some shorter and some much longer than the interval.
    for step in (KEEPALIVE // 3, KEEPALIVE, 1, KEEPALIVE * 4 + 5, KEEPALIVE - 6, KEEPALIVE * 9):
        await rig.vt.advance(step)
        elapsed += step
        assert rig.keepalives() == elapsed // KEEPALIVE
    assert rig.listen_key_posts() == 1
    assert rig.snapshots_provider.calls == 1
    await rig.stop()


async def test_invalid_listen_key_on_keepalive_rekeys_and_resyncs() -> None:
    rest = FakeRestUserDataApi(listen_keys=(TEST_ONLY_LISTEN_KEY, TEST_ONLY_SECOND_LISTEN_KEY))
    rig = Rig(limits=limits_with(), rest=rest)
    await rig.start_live()
    stream_map = sdk_stream_map_of()
    assert TEST_ONLY_LISTEN_KEY in stream_map
    rest.fail_next("keepalive_user_data_stream", BadRequestError(TEST_ONLY_SDK_MESSAGE, -1125))
    held_id = TEST_ONLY_ORDER_IDS[2]

    def _emit_on_new_key(call: int) -> None:
        if call == 2:
            rig.emit_order(held_id, key=TEST_ONLY_SECOND_LISTEN_KEY)

    rig.snapshots_provider.on_call = _emit_on_new_key
    await rig.vt.advance(KEEPALIVE)

    assert rig.state_names()[3:] == [S.UNKNOWN, S.SYNCING, S.LIVE]
    assert rig.states[3][1] == "LISTEN_KEY_INVALID"
    assert rig.listen_key_posts() == 2
    # The old key name is forgotten and the NEW key is subscribed.
    assert TEST_ONLY_LISTEN_KEY not in stream_map
    assert TEST_ONLY_SECOND_LISTEN_KEY in stream_map
    assert rig.snapshots_provider.calls == 2
    assert rig.order_ids() == [(str(held_id), True)]
    assert rig.failures == []
    await rig.stop()


async def test_listen_key_expired_event_rekeys_and_resyncs() -> None:
    rest = FakeRestUserDataApi(listen_keys=(TEST_ONLY_LISTEN_KEY, TEST_ONLY_SECOND_LISTEN_KEY))
    rig = Rig(limits=limits_with(), rest=rest)
    await rig.start_live()
    stream_map = sdk_stream_map_of()

    assert rig.client().emit_user_event(TEST_ONLY_LISTEN_KEY, expiry_message()) == 1
    await rig.settle()

    # The expiry itself is delivered (every outcome type is), then the key is replaced.
    assert isinstance(rig.events[0].outcome, ListenKeyExpiredEvent)
    assert rig.events[0].after_gap is False
    assert rig.state_names()[3:] == [S.UNKNOWN, S.SYNCING, S.LIVE]
    assert rig.states[3][1] == "LISTEN_KEY_EXPIRED"
    assert rig.listen_key_posts() == 2
    assert TEST_ONLY_LISTEN_KEY not in stream_map
    assert TEST_ONLY_SECOND_LISTEN_KEY in stream_map
    assert rig.snapshots_provider.calls == 2
    await rig.stop()


async def test_transient_keepalive_failure_below_tolerance_keeps_live() -> None:
    assert TOLERANCE > 1  # the TEST_ONLY tolerance leaves room for one tolerated failure
    rig = Rig(limits=limits_with())
    await rig.start_live()
    rig.rest.fail_next("keepalive_user_data_stream", ServerError(TEST_ONLY_SDK_MESSAGE, 503))

    await rig.vt.advance(KEEPALIVE)

    assert rig.supervisor.state is S.LIVE
    assert rig.supervisor.liveness().consecutive_keepalive_failures == 1
    assert rig.listen_key_posts() == 1
    assert rig.snapshots_provider.calls == 1

    # A later success resets the counter.
    await rig.vt.advance(KEEPALIVE)
    assert rig.supervisor.liveness().consecutive_keepalive_failures == 0
    assert rig.state_names() == [S.CONNECTING, S.SYNCING, S.LIVE]
    await rig.stop()


async def test_transient_keepalive_failures_at_tolerance_go_unknown_and_rekey() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    for _ in range(TOLERANCE):
        rig.rest.fail_next("keepalive_user_data_stream", ServerError(TEST_ONLY_SDK_MESSAGE, 503))

    await rig.vt.advance(KEEPALIVE * (TOLERANCE - 1))
    assert rig.supervisor.state is S.LIVE
    await rig.vt.advance(KEEPALIVE)

    assert rig.state_names()[3:] == [S.UNKNOWN, S.SYNCING, S.LIVE]
    assert rig.states[3][1] == "KEEPALIVE_FAILURES"
    assert rig.listen_key_posts() == 2
    assert rig.snapshots_provider.calls == 2
    assert rig.supervisor.liveness().consecutive_keepalive_failures == 0
    await rig.stop()


async def test_hard_keepalive_failure_reports_category_and_never_loops() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    rig.rest.fail_next(
        "keepalive_user_data_stream", UnauthorizedError(TEST_ONLY_SDK_MESSAGE, -2015)
    )

    await rig.vt.advance(KEEPALIVE)
    assert rig.supervisor.state is S.UNKNOWN
    assert rig.failures == ["AUTH_OR_SIGNATURE"]

    await rig.vt.advance(KEEPALIVE * 5)
    assert rig.keepalives() == 1
    assert rig.listen_key_posts() == 1
    assert rig.snapshots_provider.calls == 1
    assert rig.failures == ["AUTH_OR_SIGNATURE"]
    assert rig.supervisor.state is S.UNKNOWN
    await rig.stop()


# --------------------------------------------------------------------------- #
# Task 2: the shared rate-limit gate in the supervisor (user amendment 2026-10-16).
# --------------------------------------------------------------------------- #


async def test_keepalive_429_never_triggers_immediate_rekey_or_snapshot() -> None:
    rig = Rig(limits=limits_with(keepalive_failure_tolerance=1))
    await rig.start_live()
    rig.rest.fail_next(
        "keepalive_user_data_stream", TooManyRequestsError(TEST_ONLY_SDK_MESSAGE, -1003, None)
    )

    await rig.vt.advance(KEEPALIVE)

    # The 429 paused every REST call of the process; the supervisor is waiting it out.
    restriction = rig.gate.restriction()
    assert restriction is not None and restriction.reason == RATE_LIMIT_PAUSE_429
    assert WAIT_429 in rig.vt.sleeps
    assert rig.supervisor.state is S.UNKNOWN
    assert rig.listen_key_posts() == 1
    assert rig.snapshots_provider.calls == 1

    await rig.vt.advance(WAIT_429 - 1)
    assert rig.supervisor.state is S.UNKNOWN
    assert rig.listen_key_posts() == 1
    assert rig.snapshots_provider.calls == 1
    assert S.SYNCING not in rig.state_names()[3:]

    await rig.vt.advance(1)
    assert rig.listen_key_posts() == 2
    assert rig.snapshots_provider.calls == 2
    assert rig.state_names()[3:] == [S.UNKNOWN, S.SYNCING, S.LIVE]
    await rig.stop()


async def test_keepalive_429_with_retry_after_waits_capped_value() -> None:
    rig = Rig(limits=limits_with(keepalive_failure_tolerance=1))
    await rig.start_live()
    rig.rest.fail_next(
        "keepalive_user_data_stream",
        TooManyRequestsError(TEST_ONLY_SDK_MESSAGE, -1003, CAP * 3),
    )

    await rig.vt.advance(KEEPALIVE)
    assert CAP in rig.vt.sleeps
    assert CAP * 3 not in rig.vt.sleeps

    await rig.vt.advance(CAP - 1)
    assert rig.listen_key_posts() == 1
    assert rig.supervisor.state is S.UNKNOWN
    await rig.vt.advance(1)
    assert rig.listen_key_posts() == 2
    assert rig.supervisor.state is S.LIVE
    await rig.stop()


async def test_pause_set_by_another_holder_delays_every_supervisor_rest_step() -> None:
    margin = 10
    rig = Rig(limits=limits_with())
    await rig.start_live()

    # Another holder meets a 429 shortly before the keepalive is due.
    await rig.vt.advance(KEEPALIVE - margin)
    rig.gate.record(_C.RATE_LIMITED, None)
    await rig.vt.advance(margin)
    assert rig.keepalives() == 0
    await rig.vt.advance(WAIT_429 - margin - 1)
    assert rig.keepalives() == 0
    assert rig.supervisor.state is S.LIVE
    await rig.vt.advance(1)
    assert rig.keepalives() == 1

    # A running snapshot cycle: the first attempt after a gap fails while another holder
    # pauses REST; the next attempt waits the remaining pause and consumes no attempt.
    def _pause_during_attempt(call: int) -> None:
        if call == 2:
            rig.gate.record(_C.RATE_LIMITED, None)

    rig.snapshots_provider.on_call = _pause_during_attempt
    rig.snapshots_provider.failures.append(RuntimeError("snapshot attempt failed"))
    rig.ws.simulate_unsolicited_close()
    await rig.settle()
    assert rig.snapshots_provider.calls == 2
    assert rig.supervisor.state is S.SYNCING

    await rig.vt.advance(WAIT_429 - 1)
    assert rig.snapshots_provider.calls == 2
    assert rig.supervisor.state is S.SYNCING
    await rig.vt.advance(2)
    assert rig.snapshots_provider.calls == 3
    assert rig.supervisor.state is S.LIVE
    await rig.stop()


async def test_ban_on_listen_key_call_blocks_every_holder() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    rig.rest.fail_next(
        "keepalive_user_data_stream", RateLimitBanError(TEST_ONLY_SDK_MESSAGE, -1003, None)
    )

    await rig.vt.advance(KEEPALIVE)

    restriction = rig.gate.restriction()
    assert restriction is not None and restriction.reason == IP_BAN_418
    assert rig.supervisor.state is S.UNKNOWN
    assert rig.failures == ["RATE_LIMIT_BAN_ACTIVE"]
    # Another holder of the same gate is refused without sending.
    other_holder = ScriptedSnapshots(rig.gate)
    with pytest.raises(RateLimitBanActive):
        await other_holder()
    assert other_holder.calls == 0

    await rig.vt.advance(KEEPALIVE * 4)
    assert rig.failures == ["RATE_LIMIT_BAN_ACTIVE"]
    assert rig.keepalives() == 1
    assert rig.listen_key_posts() == 1
    assert rig.snapshots_provider.calls == 1
    assert rig.supervisor.state is S.UNKNOWN
    await rig.stop()


async def test_request_resync_during_ban_sends_nothing() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    rig.rest.fail_next(
        "keepalive_user_data_stream", RateLimitBanError(TEST_ONLY_SDK_MESSAGE, -1003, None)
    )
    await rig.vt.advance(KEEPALIVE)
    calls_before = dict(rig.rest.calls)

    rig.supervisor.request_resync()
    await rig.settle()

    assert rig.failures == ["RATE_LIMIT_BAN_ACTIVE", "RATE_LIMIT_BAN_ACTIVE"]
    assert rig.rest.calls == calls_before
    assert rig.snapshots_provider.calls == 1
    assert rig.supervisor.state is S.UNKNOWN
    await rig.stop()


async def test_wait_end_does_not_restore_live() -> None:
    rig = Rig(limits=limits_with(keepalive_failure_tolerance=1))
    await rig.start_live()
    rig.rest.fail_next(
        "keepalive_user_data_stream", TooManyRequestsError(TEST_ONLY_SDK_MESSAGE, -1003, None)
    )
    rig.snapshots_provider.fail_always = RuntimeError("snapshot unavailable")
    await rig.vt.advance(KEEPALIVE)
    assert rig.supervisor.state is S.UNKNOWN
    held_id = TEST_ONLY_ORDER_IDS[3]
    rig.emit_order(held_id)
    await rig.settle()

    # The pause ends: nothing becomes LIVE by itself; the snapshot cycle runs and fails.
    await rig.vt.advance(WAIT_429)
    assert rig.gate.restriction() is None
    assert rig.supervisor.state is not S.LIVE
    await rig.vt.advance(KEEPALIVE)
    assert rig.supervisor.state is S.UNKNOWN
    assert S.LIVE not in rig.state_names()[3:]
    assert rig.failures == ["SNAPSHOT_EXHAUSTED"]
    assert rig.events == []
    await rig.stop()


# --------------------------------------------------------------------------- #
# WR-C4: a gate with no known end is not a pause; the wait is bounded by the stream limits.
# --------------------------------------------------------------------------- #


def _unknown_gate_rig(tmp_path: Path, limits: StreamLimits, *, restore: bool = True) -> Rig:
    """A rig over a gate with a store whose file is missing (loss of initialized state)."""
    store = FileGateStateStore(tmp_path / "gate.json", clock=lambda: TEST_ONLY_NOW)
    rig = Rig(limits=limits, gate_store=store)
    if restore:
        assert rig.gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    return rig


TEST_ONLY_NOW = TEST_ONLY_VIRTUAL_START


async def _start_and_advance(rig: Rig, seconds: float) -> None:
    starting = asyncio.ensure_future(rig.supervisor.start())
    await rig.vt.advance(seconds)
    await asyncio.wait_for(starting, timeout=5)  # real seconds: a spinning supervisor fails here


async def test_unknown_gate_state_halts_after_the_reconnect_attempts_and_reports_once(
    tmp_path: Path,
) -> None:
    rig = _unknown_gate_rig(tmp_path, limits_with())
    attempts = rig.limits.reconnect_max_attempts

    await _start_and_advance(rig, rig.limits.reconnect_max_delay_seconds)

    # One check per attempt, one hint-length (1 s) wait between two checks, then the halt.
    assert rig.vt.sleeps.count(1) == attempts - 1
    assert rig.failures == [GATE_STATE_UNKNOWN]
    assert rig.supervisor.state is S.UNKNOWN
    assert rig.states[-1] == (S.UNKNOWN, GATE_STATE_UNKNOWN)
    # Nothing was sent: the gate refused everything and the stream never connected.
    assert sum(rig.rest.calls.values()) == 0
    assert rig.snapshots_provider.calls == 0
    # No further retries after the halt, however long the process runs.
    sleeps = len(rig.vt.sleeps)
    await rig.vt.advance(rig.limits.reconnect_max_delay_seconds)
    assert len(rig.vt.sleeps) == sleeps
    assert rig.failures == [GATE_STATE_UNKNOWN]
    await rig.stop()


async def test_unknown_gate_state_halts_after_the_reconnect_delay_when_attempts_are_many(
    tmp_path: Path,
) -> None:
    limits = limits_with(reconnect_max_attempts=1000, reconnect_max_delay_seconds=3)
    rig = _unknown_gate_rig(tmp_path, limits)

    await _start_and_advance(rig, 3)

    # Checks at 0, 1, 2 and 3 seconds of the injected clock; the fourth sees the delay spent.
    assert rig.vt.sleeps.count(1) == 3
    assert rig.failures == [GATE_STATE_UNKNOWN]
    await rig.stop()


async def test_a_gate_that_was_never_restored_halts_the_same_way(tmp_path: Path) -> None:
    rig = _unknown_gate_rig(tmp_path, limits_with(), restore=False)
    assert rig.gate.recovery_status() is GateRecoveryStatus.NOT_RESTORED

    await _start_and_advance(rig, rig.limits.reconnect_max_delay_seconds)

    assert rig.vt.sleeps.count(1) == rig.limits.reconnect_max_attempts - 1
    assert rig.failures == [GATE_NOT_RESTORED]
    assert sum(rig.rest.calls.values()) == 0
    await rig.stop()


async def test_a_resync_on_an_unknown_gate_is_bounded_again_and_reports_again(
    tmp_path: Path,
) -> None:
    rig = _unknown_gate_rig(tmp_path, limits_with())
    await _start_and_advance(rig, rig.limits.reconnect_max_delay_seconds)
    assert rig.failures == [GATE_STATE_UNKNOWN]

    rig.supervisor.request_resync()
    await rig.vt.advance(rig.limits.reconnect_max_delay_seconds)

    assert rig.failures == [GATE_STATE_UNKNOWN, GATE_STATE_UNKNOWN]
    assert sum(rig.rest.calls.values()) == 0
    await rig.stop()


async def test_a_timed_pause_longer_than_the_reconnect_bound_is_still_waited_out() -> None:
    limits = limits_with(reconnect_max_attempts=1, reconnect_max_delay_seconds=1)
    rig = Rig(limits=limits)
    rig.gate.record(_C.RATE_LIMITED, None)

    starting = asyncio.ensure_future(rig.supervisor.start())
    await rig.vt.advance(WAIT_429 - 1)
    assert rig.failures == []
    assert rig.listen_key_posts() == 0
    await rig.vt.advance(1)
    await asyncio.wait_for(starting, timeout=5)  # real seconds: a spinning supervisor fails here
    await rig.settle()

    assert rig.failures == []
    assert rig.supervisor.state is S.LIVE
    assert rig.listen_key_posts() == 1
    await rig.stop()


# --------------------------------------------------------------------------- #
# Task 2: rotation, SDK reconnect, connection errors.
# --------------------------------------------------------------------------- #


async def test_project_rotation_interval_rebuilds_and_resyncs() -> None:
    rig = Rig(limits=limits_with(project_rotation_interval_seconds=ROTATION))
    await rig.start_live()

    await rig.vt.advance(ROTATION - 1)
    assert rig.factory.built == []
    await rig.vt.advance(1)

    assert rig.state_names()[3:] == [S.UNKNOWN, S.SYNCING, S.LIVE]
    assert rig.states[3][1] == "PROJECT_ROTATION"
    assert len(rig.factory.built) == 1
    assert rig.adapter.epoch == 2
    assert rig.snapshots_provider.calls == 2

    # The timer restarts after the rotation's own connect.
    await rig.vt.advance(ROTATION)
    assert len(rig.factory.built) == 2
    assert rig.snapshots_provider.calls == 3
    await rig.stop()


async def test_no_rotation_timer_when_none_and_sdk_reconnect_is_a_gap() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    assert rig.supervisor._rotation_task is None

    await rig.vt.advance(ROTATION * 3)
    assert rig.factory.built == []
    assert rig.snapshots_provider.calls == 1

    rig.ws.emit_connection_event("private", "reconnect")
    await rig.settle()
    assert rig.supervisor.state is S.UNKNOWN
    held_id = TEST_ONLY_ORDER_IDS[0]
    rig.emit_order(held_id)
    await rig.settle()
    assert rig.events == []

    rig.ws.emit_connection_event("private", "open")
    await rig.settle()
    assert rig.state_names()[3:] == [S.UNKNOWN, S.SYNCING, S.LIVE]
    assert rig.states[3][1] == "SDK_RECONNECT"
    assert rig.snapshots_provider.calls == 2
    assert rig.factory.built == []
    assert rig.order_ids() == [(str(held_id), True)]
    await rig.stop()


async def test_error_event_on_open_connection_is_ignored_and_on_closed_one_is_a_loss() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()

    rig.ws.emit_connection_event("private", "error", RuntimeError("callback failed"))
    await rig.settle()
    assert rig.supervisor.state is S.LIVE
    assert rig.factory.built == []

    private = rig.ws.connection_for("private")
    assert private is not None
    private.is_open = False
    rig.ws.emit_connection_event("private", "error", RuntimeError("socket failed"))
    await rig.settle()
    assert rig.state_names()[3:] == [S.UNKNOWN, S.SYNCING, S.LIVE]
    assert rig.states[3][1] == "CONNECTION_ERROR"
    assert len(rig.factory.built) == 1
    await rig.stop()


# --------------------------------------------------------------------------- #
# Task 2: liveness and staleness.
# --------------------------------------------------------------------------- #


async def test_ping_and_pong_update_the_liveness_record() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()

    await rig.vt.advance(5)
    rig.ws.emit_connection_event("private", "ping", b"payload")
    await rig.settle()
    ping_at = rig.vt.now()
    await rig.vt.advance(7)
    rig.ws.emit_connection_event("private", "pong", b"payload")
    await rig.settle()

    liveness = rig.supervisor.liveness()
    assert isinstance(liveness, LivenessSnapshot)
    assert liveness.last_ping_at_utc == ping_at
    assert liveness.last_pong_at_utc == rig.vt.now()
    assert liveness.last_event_at_utc is None
    assert liveness.state is S.LIVE
    assert liveness.epoch == 1
    assert rig.supervisor.state is S.LIVE
    await rig.stop()


async def test_quiet_account_with_regular_pings_is_not_stale() -> None:
    ping_every = MAX_AGE // 2
    rig = Rig(limits=limits_with(keepalive_interval_seconds=MAX_AGE * 100))
    await rig.start_live()
    for _ in range(40):
        await rig.vt.advance(ping_every)
        rig.ws.emit_connection_event("private", "ping")
        await rig.settle()
        liveness = rig.supervisor.liveness()
        assert not stream_is_stale(liveness, rig.vt.now(), max_liveness_age_seconds=MAX_AGE)
    assert rig.supervisor.liveness().last_event_at_utc is None
    # Without pings the same quiet stream turns stale once the age is exceeded.
    await rig.vt.advance(MAX_AGE + 1)
    assert stream_is_stale(
        rig.supervisor.liveness(), rig.vt.now(), max_liveness_age_seconds=MAX_AGE
    )
    await rig.stop()


def _liveness(**overrides: Any) -> LivenessSnapshot:
    values: dict[str, Any] = {
        "state": S.LIVE,
        "state_since_utc": VirtualTime().now(),
        "epoch": 1,
        "last_event_at_utc": None,
        "last_ping_at_utc": None,
        "last_pong_at_utc": None,
        "last_keepalive_ok_at_utc": None,
        "consecutive_keepalive_failures": 0,
    }
    values.update(overrides)
    return LivenessSnapshot(**values)


def test_stream_is_stale_is_pure_and_uses_only_liveness_signals() -> None:
    start: datetime = VirtualTime().now()
    limit = timedelta(seconds=MAX_AGE)
    live = _liveness()
    # The LIVE entry counts as a liveness signal; staleness means strictly older than the limit.
    assert not stream_is_stale(live, start + limit, max_liveness_age_seconds=MAX_AGE)
    assert stream_is_stale(
        live, start + limit + timedelta(microseconds=1), max_liveness_age_seconds=MAX_AGE
    )
    # The latest of ping, pong and keepalive counts; an event never does.
    later = start + limit
    for field in ("last_ping_at_utc", "last_pong_at_utc", "last_keepalive_ok_at_utc"):
        snapshot = _liveness(**{field: later})
        assert not stream_is_stale(snapshot, later + limit, max_liveness_age_seconds=MAX_AGE)
    with_event = _liveness(last_event_at_utc=later)
    assert stream_is_stale(with_event, later + limit + limit, max_liveness_age_seconds=MAX_AGE)
    # A ratified none computes no verdict.
    assert not stream_is_stale(live, start + limit * 1000, max_liveness_age_seconds=None)
    # Not LIVE and no liveness signal at all: stale (fail closed).
    assert stream_is_stale(_liveness(state=S.UNKNOWN), start, max_liveness_age_seconds=MAX_AGE)


# --------------------------------------------------------------------------- #
# Task 2: queue overflow and anomalies.
# --------------------------------------------------------------------------- #


async def test_queue_overflow_goes_unknown_resyncs_and_releases_only_what_was_held() -> None:
    queue_max = 2
    rig = Rig(limits=limits_with(event_queue_max=queue_max))
    await rig.start_live()

    # A burst larger than the adapter queue arrives before the pump runs.
    for order_id in TEST_ONLY_ORDER_IDS[:3]:
        rig.emit_order(order_id)
    assert rig.adapter.overflowed
    await rig.settle()

    assert rig.state_names()[3:] == [S.UNKNOWN, S.SYNCING, S.LIVE]
    assert rig.states[3][1] == "QUEUE_OVERFLOW"
    assert rig.snapshots_provider.calls == 2
    assert not rig.adapter.overflowed
    assert rig.adapter.overflow_count == 1
    assert rig.order_ids() == [(str(order_id), True) for order_id in TEST_ONLY_ORDER_IDS[:2]]
    await rig.stop()


async def test_anomaly_is_delivered_with_the_same_hold_rule() -> None:
    rig = Rig(limits=limits_with())

    def _anomaly_during_snapshot(call: int) -> None:
        rig.client().emit_user_event(TEST_ONLY_LISTEN_KEY, object())

    rig.snapshots_provider.on_call = _anomaly_during_snapshot
    await rig.start_live()
    rig.client().emit_user_event(TEST_ONLY_LISTEN_KEY, object())
    await rig.settle()

    assert [type(event.outcome) for event in rig.events] == [StreamAnomaly, StreamAnomaly]
    assert [event.after_gap for event in rig.events] == [True, False]
    await rig.stop()


# --------------------------------------------------------------------------- #
# Task 3: bounded exhaustion and the explicit resync request.
# --------------------------------------------------------------------------- #

# Long enough for every bounded cycle of the TEST_ONLY limits to run out.
EXHAUST_SECONDS = KEEPALIVE - 1


async def test_rebuild_exhaustion_is_bounded_reported_once_and_waits_for_resync() -> None:
    factory = _Factory(produce_connection=False)
    rig = Rig(limits=limits_with(), factory=factory)
    await rig.start_live()
    first_sleep = len(rig.vt.sleeps)

    rig.ws.simulate_unsolicited_close()
    await rig.vt.advance(EXHAUST_SECONDS)

    assert len(factory.built) == TEST_ONLY_RECONNECT_MAX_ATTEMPTS
    assert rig.supervisor.state is S.UNKNOWN
    assert rig.failures == ["REBUILD_EXHAUSTED"]
    waits = rig.vt.sleeps[first_sleep:]
    assert waits and max(waits) <= TEST_ONLY_RECONNECT_WAIT_MAX_SECONDS

    # Nothing more happens by itself.
    await rig.vt.advance(EXHAUST_SECONDS)
    assert len(factory.built) == TEST_ONLY_RECONNECT_MAX_ATTEMPTS
    assert rig.failures == ["REBUILD_EXHAUSTED"]
    assert rig.snapshots_provider.calls == 1

    # An explicit resync runs one more bounded cycle; once the rebuild works it reaches LIVE.
    factory.produce_connection = True
    rig.supervisor.request_resync()
    await rig.vt.advance(EXHAUST_SECONDS)
    assert len(factory.built) == TEST_ONLY_RECONNECT_MAX_ATTEMPTS + 1
    assert rig.supervisor.state is S.LIVE
    assert rig.snapshots_provider.calls == 2
    await rig.stop()


async def test_resync_during_a_ban_does_not_even_rebuild_the_socket() -> None:
    factory = _Factory(produce_connection=False)
    rig = Rig(limits=limits_with(), factory=factory)
    await rig.start_live()
    rig.ws.simulate_unsolicited_close()
    await rig.vt.advance(EXHAUST_SECONDS)
    assert rig.failures == ["REBUILD_EXHAUSTED"]
    built = len(factory.built)

    rig.gate.record(_C.IP_BANNED, None)  # another holder met a 418
    factory.produce_connection = True
    rig.supervisor.request_resync()
    await rig.vt.advance(EXHAUST_SECONDS)

    assert rig.failures == ["REBUILD_EXHAUSTED", "RATE_LIMIT_BAN_ACTIVE"]
    assert len(factory.built) == built
    assert rig.snapshots_provider.calls == 1
    assert rig.supervisor.state is S.UNKNOWN
    await rig.stop()


async def test_rebuild_retry_is_also_bounded_by_the_virtual_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Full jitter replaced by its upper bound, so the first wait is exactly the multiplier; a
    # delay bound equal to it is reached when the second attempt fails.
    monkeypatch.setattr(random, "uniform", lambda low, high: high)
    multiplier = TEST_ONLY_RECONNECT_WAIT_MULTIPLIER_SECONDS
    delay = multiplier
    factory = _Factory(produce_connection=False)
    rig = Rig(limits=limits_with(reconnect_max_delay_seconds=delay), factory=factory)
    await rig.start_live()

    rig.ws.simulate_unsolicited_close()
    await rig.vt.advance(EXHAUST_SECONDS)

    assert TEST_ONLY_RECONNECT_MAX_ATTEMPTS > 2
    assert len(factory.built) == 2
    assert rig.failures == ["REBUILD_EXHAUSTED"]
    await rig.stop()


async def test_snapshot_exhaustion_holds_events_until_a_resync_succeeds() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    rig.snapshots_provider.fail_always = RuntimeError("snapshot unavailable")
    held_id = TEST_ONLY_ORDER_IDS[1]

    rig.ws.simulate_unsolicited_close()
    await rig.settle()
    rig.emit_order(held_id)
    await rig.vt.advance(EXHAUST_SECONDS)

    assert rig.snapshots_provider.calls == 1 + TEST_ONLY_SNAPSHOT_MAX_ATTEMPTS
    assert rig.supervisor.state is S.UNKNOWN
    assert rig.failures == ["SNAPSHOT_EXHAUSTED"]
    assert rig.events == []
    await rig.vt.advance(EXHAUST_SECONDS)
    assert rig.snapshots_provider.calls == 1 + TEST_ONLY_SNAPSHOT_MAX_ATTEMPTS
    assert rig.events == []

    rig.snapshots_provider.fail_always = None
    rig.supervisor.request_resync()
    await rig.settle()
    assert rig.snapshots_provider.calls == 2 + TEST_ONLY_SNAPSHOT_MAX_ATTEMPTS
    assert rig.supervisor.state is S.LIVE
    assert rig.order_ids() == [(str(held_id), True)]
    assert rig.failures == ["SNAPSHOT_EXHAUSTED"]
    await rig.stop()


async def test_snapshot_attempt_has_a_deadline_on_virtual_time() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    never: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    async def _hang(call: int) -> None:
        if call == 2:
            await never

    rig.snapshots_provider.on_call = _hang
    rig.ws.simulate_unsolicited_close()
    await rig.settle()
    assert rig.supervisor.state is S.SYNCING
    assert TEST_ONLY_SNAPSHOT_DEADLINE_SECONDS in rig.vt.sleeps

    await rig.vt.advance(TEST_ONLY_SNAPSHOT_DEADLINE_SECONDS - 1)
    assert rig.snapshots_provider.calls == 2
    await rig.vt.advance(1 + TEST_ONLY_SNAPSHOT_WAIT_MAX_SECONDS)
    assert rig.snapshots_provider.calls == 3
    assert rig.supervisor.state is S.LIVE
    assert not never.done() or never.cancelled()
    await rig.stop()


async def test_initial_connect_exhaustion_ends_unknown_without_raising() -> None:
    rig = Rig(limits=limits_with(), ws=FakeUserDataWsClient(produce_connection=False))

    starting = asyncio.ensure_future(rig.supervisor.start())
    await rig.vt.advance(EXHAUST_SECONDS)

    assert starting.done()
    assert starting.exception() is None
    assert rig.state_names() == [S.CONNECTING, S.UNKNOWN]
    assert rig.failures == ["CONNECT_EXHAUSTED"]
    assert rig.listen_key_posts() == TEST_ONLY_RECONNECT_MAX_ATTEMPTS
    assert rig.snapshots_provider.calls == 0
    await rig.supervisor.stop(close_listen_key=False)
    assert rig.supervisor.state is S.STOPPED


async def test_resync_during_a_pause_waits_first_and_a_pause_is_not_an_attempt() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    rig.snapshots_provider.fail_always = RuntimeError("snapshot unavailable")
    rig.ws.simulate_unsolicited_close()
    await rig.vt.advance(EXHAUST_SECONDS)
    assert rig.failures == ["SNAPSHOT_EXHAUSTED"]
    calls = rig.snapshots_provider.calls

    rig.gate.record(_C.RATE_LIMITED, None)
    rig.supervisor.request_resync()
    await rig.vt.advance(WAIT_429 - 1)
    assert rig.snapshots_provider.calls == calls
    assert rig.supervisor.state is not S.LIVE

    # Another holder pauses REST again in the middle of the cycle: still no extra attempt.
    def _pause_again(call: int) -> None:
        if call == calls + 2:
            rig.gate.record(_C.RATE_LIMITED, None)

    rig.snapshots_provider.on_call = _pause_again
    await rig.vt.advance(EXHAUST_SECONDS)
    assert rig.snapshots_provider.calls == calls + TEST_ONLY_SNAPSHOT_MAX_ATTEMPTS
    assert rig.failures == ["SNAPSHOT_EXHAUSTED", "SNAPSHOT_EXHAUSTED"]
    assert rig.supervisor.state is S.UNKNOWN
    await rig.stop()


async def test_request_resync_is_ignored_while_live_and_after_stop() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    rig.supervisor.request_resync()
    await rig.settle()
    assert rig.snapshots_provider.calls == 1
    assert rig.state_names() == [S.CONNECTING, S.SYNCING, S.LIVE]

    await rig.stop()
    rig.supervisor.request_resync()
    await rig.settle()
    assert rig.supervisor.state is S.STOPPED
    assert rig.supervisor._commands.qsize() == 0


# --------------------------------------------------------------------------- #
# Task 3: stop.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("close_listen_key", [True, False])
async def test_stop_cancels_every_task_and_is_idempotent(close_listen_key: bool) -> None:
    rig = Rig(limits=limits_with(project_rotation_interval_seconds=ROTATION))
    await rig.start_live()
    # Leave work in flight: a pause makes the next keepalive wait inside the control task,
    # and a command sits in the queue.
    rig.gate.record(_C.RATE_LIMITED, None)
    await rig.vt.advance(KEEPALIVE)
    rig.supervisor.request_resync()
    assert rig.supervisor._tasks

    await rig.supervisor.stop(close_listen_key=close_listen_key)

    assert rig.supervisor.state is S.STOPPED
    assert rig.state_names()[-1] is S.STOPPED
    assert rig.supervisor._tasks == set()
    assert rig.supervisor._commands.qsize() == 0
    assert asyncio.all_tasks() == {asyncio.current_task()}
    assert rig.rest.calls["close_user_data_stream"] == (1 if close_listen_key else 0)
    states = list(rig.states)

    await rig.supervisor.stop(close_listen_key=close_listen_key)
    assert rig.states == states
    assert rig.rest.calls["close_user_data_stream"] == (1 if close_listen_key else 0)


async def test_stop_requires_the_close_listen_key_argument() -> None:
    rig = Rig(limits=limits_with())
    await rig.start_live()
    with pytest.raises(TypeError):
        await rig.supervisor.stop()  # type: ignore[call-arg]
    params = inspect.signature(UserDataSupervisor.stop).parameters
    assert params["close_listen_key"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["close_listen_key"].default is inspect.Parameter.empty
    await rig.stop()


def test_constructor_arguments_are_keyword_only_and_required() -> None:
    params = list(inspect.signature(UserDataSupervisor.__init__).parameters.values())[1:]
    assert [p.name for p in params] == [
        "adapter",
        "limits",
        "clock",
        "sleep",
        "rest_gate",
        "snapshot_provider",
        "on_state_change",
        "on_event",
        "on_snapshot",
        "on_failure",
    ]
    for param in params:
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty


# --------------------------------------------------------------------------- #
# Task 3: structural guards (D-04, no src.paper, no wall clock, no numbers).
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_PATH = REPO_ROOT / "src" / "adapters" / "binance_userdata_supervisor.py"
SUPERVISOR_MODULE = "src.adapters.binance_userdata_supervisor"


def _imports_supervisor(names: list[str]) -> bool:
    return any(
        name == SUPERVISOR_MODULE or name.startswith(SUPERVISOR_MODULE + ".") for name in names
    )


def test_no_src_module_imports_the_supervisor() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted((REPO_ROOT / "src").rglob("*.py"))
        if path != SUPERVISOR_PATH and _imports_supervisor(module_imports(path))
    ]
    assert offenders == []


def test_import_guard_negative_control(tmp_path: Path) -> None:
    wired = tmp_path / "wired.py"
    wired.write_text(
        "from src.adapters.binance_userdata_supervisor import UserDataSupervisor\n",
        encoding="utf-8",
    )
    assert _imports_supervisor(module_imports(wired))
    also = tmp_path / "also.py"
    also.write_text("import src.adapters.binance_userdata_supervisor as s\n", encoding="utf-8")
    assert _imports_supervisor(module_imports(also))


def test_supervisor_imports_nothing_from_paper() -> None:
    assert forbidden_imports(SUPERVISOR_PATH, ("src.paper",)) == []


def test_supervisor_reads_no_wall_clock_and_calls_no_float() -> None:
    assert wall_clock_calls(SUPERVISOR_PATH) == []
    assert float_constructor_calls(SUPERVISOR_PATH) == []


def _int_literals(path: Path) -> list[tuple[int, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sorted(
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is int
    )


def test_supervisor_defines_no_number_beyond_zero_and_one(tmp_path: Path) -> None:
    assert [item for item in _int_literals(SUPERVISOR_PATH) if item[1] not in (0, 1)] == []
    # Negative control: a literal interval is found.
    planted = tmp_path / "planted.py"
    planted.write_text("KEEPALIVE_INTERVAL_SECONDS = 1800\n", encoding="utf-8")
    assert _int_literals(planted) == [(1, 1800)]


async def test_a_task_that_dies_fails_closed_instead_of_staying_live() -> None:
    """Review WR-05: a crashed timer must not leave the stream LIVE with nothing running."""
    rig = Rig()
    await rig.start_live()

    async def _broken_sleep(seconds: float) -> None:
        raise RuntimeError("timer task crashed")

    # The keepalive timer looks the sleep up again after its first interval.
    rig.supervisor._sleep = _broken_sleep
    await rig.vt.advance(KEEPALIVE)
    await rig.settle()

    assert rig.supervisor.state is S.UNKNOWN
    assert rig.states[-1] == (S.UNKNOWN, sup_mod.REASON_TASK_DIED)
    assert rig.failures == [sup_mod.REASON_TASK_DIED]

    await rig.stop()


async def test_a_rebuild_proves_the_stored_listen_key_with_a_keepalive() -> None:
    """Review CR-02 (no-decision part): a rebuild must not resubscribe an unproven key."""
    rig = Rig()
    await rig.start_live()
    assert rig.keepalives() == 0

    rig.ws.simulate_unsolicited_close()
    await rig.settle()

    assert rig.supervisor.state is S.LIVE
    assert rig.keepalives() == 1
    assert rig.listen_key_posts() == 1
    await rig.stop()


async def test_a_rebuild_with_an_expired_listen_key_starts_a_new_key() -> None:
    rest = FakeRestUserDataApi(listen_keys=(TEST_ONLY_LISTEN_KEY, TEST_ONLY_SECOND_LISTEN_KEY))
    rig = Rig(rest=rest)
    await rig.start_live()
    stream_map = sdk_stream_map_of()
    rest.fail_next("keepalive_user_data_stream", BadRequestError(TEST_ONLY_SDK_MESSAGE, -1125))

    rig.ws.simulate_unsolicited_close()
    await rig.settle()

    assert rig.supervisor.state is S.LIVE
    assert rig.listen_key_posts() == 2
    assert TEST_ONLY_LISTEN_KEY not in stream_map
    assert TEST_ONLY_SECOND_LISTEN_KEY in stream_map
    assert rig.failures == []
    await rig.stop()


async def test_a_rebuild_waits_out_a_rest_pause_before_proving_the_key() -> None:
    rig = Rig()
    await rig.start_live()
    rig.gate.record(ExchangeErrorCategory.RATE_LIMITED, None)

    rig.ws.simulate_unsolicited_close()
    await rig.settle()
    assert rig.keepalives() == 0  # refused by the gate, nothing sent
    assert rig.supervisor.state is not S.LIVE

    await rig.vt.advance(WAIT_429)
    await rig.settle()
    assert rig.keepalives() == 1
    assert rig.supervisor.state is S.LIVE
    await rig.stop()
