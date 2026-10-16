"""The user-data stream supervisor: one owner of the stream lifecycle (Phase 18, plan 18-14, D-03).

The stream is only a hint; REST is the truth (D-05). The SDK owns the socket, its reconnect and
its 23-hour in-place rotation, but events in a swap window are lost and the SDK resubscribes
the key it remembers (research P8). The supervisor makes every gap visible: a rebuild, an SDK
reconnect, a re-keyed listenKey, an expiry, a keepalive failure beyond the tolerance or a queue
overflow puts the stream in UNKNOWN; events received while the state is not LIVE are held and
delivered only after a REST snapshot has succeeded, flagged `after_gap`.

One control task makes every state change. The adapter's connection callbacks, the event pump
and the timers only post commands to it and return at once, so at most one recovery runs at a
time and the order of transitions is the order of the commands. Every retry is bounded by the
ratified `StreamLimits` through tenacity with the injected sleep; an exhausted retry leaves the
state UNKNOWN, reports the failure and waits for an explicit `request_resync()` (fail closed).

Nothing in `src` imports this module for wiring (D-04: the composition is Phases 24 and 25),
and it imports nothing from `src.paper`. No wall clock is read and no number is defined here:
time comes from the injected clock and sleep, every interval, attempt count and tolerance from
`StreamLimits`, every pause or ban length from the shared `RestRateLimitGate`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

import structlog
import tenacity
from src.adapters.binance_limits import StreamLimits
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_userdata import ConnectionEvent, QueuedStreamItem
from src.adapters.binance_userdata_events import StreamOutcome
from tenacity.stop import stop_base

log = structlog.get_logger()

Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]
SnapshotProvider = Callable[[], Awaitable[object]]

# Reasons reported through `on_state_change` and `on_failure` (fixed project text).
REASON_START = "START"
REASON_SNAPSHOT = "SNAPSHOT"
REASON_SNAPSHOT_OK = "SNAPSHOT_OK"
REASON_CONNECTION_CLOSED = "CONNECTION_CLOSED"
REASON_CONNECTION_ERROR = "CONNECTION_ERROR"
REASON_SDK_RECONNECT = "SDK_RECONNECT"
REASON_STOP = "STOP"
REASON_INTERNAL_ERROR = "INTERNAL_ERROR"
CONNECT_EXHAUSTED = "CONNECT_EXHAUSTED"
REBUILD_EXHAUSTED = "REBUILD_EXHAUSTED"
SNAPSHOT_EXHAUSTED = "SNAPSHOT_EXHAUSTED"


# --------------------------------------------------------------------------- #
# Public value types.
# --------------------------------------------------------------------------- #


class StreamState(StrEnum):
    """CONNECTING, SYNCING (snapshot running), LIVE (trusted), UNKNOWN (a gap), STOPPED."""

    CONNECTING = "CONNECTING"
    SYNCING = "SYNCING"
    LIVE = "LIVE"
    UNKNOWN = "UNKNOWN"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class StreamSnapshot:
    """A REST snapshot taken after a gap; the payload is opaque to the supervisor."""

    taken_at_utc: datetime
    payload: object


@dataclass(frozen=True)
class TrustedEvent:
    """A stream outcome released to the consumer; `after_gap` marks an event held over a gap."""

    outcome: StreamOutcome
    received_at_utc: datetime
    connection_epoch: int
    after_gap: bool


@dataclass(frozen=True)
class LivenessSnapshot:
    """The liveness record: state, its start, the epoch and the latest liveness signals."""

    state: StreamState
    state_since_utc: datetime
    epoch: int
    last_event_at_utc: datetime | None
    last_ping_at_utc: datetime | None
    last_pong_at_utc: datetime | None
    last_keepalive_ok_at_utc: datetime | None
    consecutive_keepalive_failures: int


class SupervisedAdapter(Protocol):
    """The surface of `UserDataAdapter` (plan 18-11) the supervisor drives."""

    @property
    def epoch(self) -> int: ...

    @property
    def queue(self) -> asyncio.Queue[QueuedStreamItem]: ...

    @property
    def overflowed(self) -> bool: ...

    @property
    def overflow_count(self) -> int: ...

    def clear_overflow(self) -> None: ...

    def private_connection_open(self) -> bool: ...

    def set_connection_listener(
        self, listener: Callable[[ConnectionEvent], None] | None
    ) -> None: ...

    async def start(self) -> None: ...

    async def keepalive(self) -> None: ...

    async def rekey(self) -> None: ...

    async def rebuild(self) -> None: ...

    async def stop(self, *, close_listen_key: bool) -> None: ...


# --------------------------------------------------------------------------- #
# Internal commands and helpers.
# --------------------------------------------------------------------------- #


class _Step(StrEnum):
    """What a recovery has to do before the snapshot, weakest first."""

    SYNC = "SYNC"
    REBUILD = "REBUILD"
    REKEY = "REKEY"
    CONNECT = "CONNECT"


# A rekey rebuilds when the connection is gone, and a connect does everything.
_STEP_STRENGTH: tuple[_Step, ...] = (_Step.SYNC, _Step.REBUILD, _Step.REKEY, _Step.CONNECT)


def _stronger(current: _Step | None, wanted: _Step) -> _Step:
    if current is None:
        return wanted
    if _STEP_STRENGTH.index(current) >= _STEP_STRENGTH.index(wanted):
        return current
    return wanted


@dataclass(frozen=True)
class _StartCommand:
    pass


@dataclass(frozen=True)
class _ConnectionCommand:
    event: ConnectionEvent


@dataclass(frozen=True)
class _ItemCommand:
    item: QueuedStreamItem
    # The LIVE generation when the pump posted the item, None when the state was not LIVE.
    live_generation: int | None


_Command = _StartCommand | _ConnectionCommand | _ItemCommand


class _RecoveryHalted(Exception):  # noqa: N818 - an internal signal, not an error type
    """A recovery stopped: the reason is reported and the stream waits for a resync."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SnapshotDeadlineExceeded(Exception):  # noqa: N818 - name states what happened
    """One snapshot attempt did not finish within `snapshot_deadline_seconds`."""


class _StopAfterVirtualDelay(stop_base):
    """Tenacity stop: the injected clock has moved `max_delay` past the cycle start."""

    def __init__(self, clock: Clock, started_at: datetime, max_delay: timedelta) -> None:
        self._clock = clock
        self._started_at = started_at
        self._max_delay = max_delay

    def __call__(self, retry_state: tenacity.RetryCallState) -> bool:
        return self._clock() - self._started_at >= self._max_delay


def _retryable(exc: BaseException) -> bool:
    """Cancellation and a halted recovery are never retried."""
    return not isinstance(exc, asyncio.CancelledError | _RecoveryHalted)


# --------------------------------------------------------------------------- #
# The supervisor.
# --------------------------------------------------------------------------- #


class UserDataSupervisor:
    """Owns connect, keepalive, rotation, rebuild and stop of one user-data stream (D-03).

    Sinks are synchronous and must only record or enqueue: `on_state_change(state, reason)`,
    `on_event(TrustedEvent)`, `on_snapshot(StreamSnapshot, epoch)` and `on_failure(reason)`.
    A failing `on_state_change`, `on_event` or `on_failure` is logged and never propagates; a
    failing `on_snapshot` fails that snapshot attempt (the snapshot was not handed on).
    """

    def __init__(
        self,
        *,
        adapter: SupervisedAdapter,
        limits: StreamLimits,
        clock: Clock,
        sleep: Sleep,
        rest_gate: RestRateLimitGate,
        snapshot_provider: SnapshotProvider,
        on_state_change: Callable[[StreamState, str], None],
        on_event: Callable[[TrustedEvent], None],
        on_snapshot: Callable[[StreamSnapshot, int], None],
        on_failure: Callable[[str], None],
    ) -> None:
        if not isinstance(limits, StreamLimits):
            raise TypeError("limits must be StreamLimits")
        if not isinstance(rest_gate, RestRateLimitGate):
            raise TypeError("rest_gate must be the process-wide RestRateLimitGate")
        self._adapter = adapter
        self._limits = limits
        self._clock = clock
        self._sleep = sleep
        self._gate = rest_gate
        self._snapshot_provider = snapshot_provider
        self._on_state_change = on_state_change
        self._on_event = on_event
        self._on_snapshot = on_snapshot
        self._on_failure = on_failure

        self._commands: asyncio.Queue[_Command] = asyncio.Queue()
        self._tasks: set[asyncio.Task[None]] = set()
        self._start_done: asyncio.Future[None] | None = None
        self._started = False
        self._stopped = False

        # Not trusted before the first snapshot.
        self._state = StreamState.UNKNOWN
        self._state_since = clock()
        # Increases on every entry into LIVE; an item posted in an older generation is late.
        self._generation = 0
        self._held: list[QueuedStreamItem] = []
        # Items posted by the pump and not yet delivered (in the command queue or held).
        self._pending_items = 0
        self._room = asyncio.Event()
        self._room.set()
        # The halt reason while waiting for request_resync; the step a resync has to run.
        self._halted: str | None = None
        self._pending_step: _Step | None = None
        self._awaiting_open = False

        self._last_event_at: datetime | None = None
        self._last_ping_at: datetime | None = None
        self._last_pong_at: datetime | None = None
        self._last_keepalive_ok_at: datetime | None = None
        self._keepalive_failures = 0

    def __repr__(self) -> str:
        return f"{type(self).__name__}(state={self._state.value}, epoch={self._adapter.epoch})"

    # -- read-only state ----------------------------------------------------- #

    @property
    def state(self) -> StreamState:
        return self._state

    def liveness(self) -> LivenessSnapshot:
        return LivenessSnapshot(
            state=self._state,
            state_since_utc=self._state_since,
            epoch=self._adapter.epoch,
            last_event_at_utc=self._last_event_at,
            last_ping_at_utc=self._last_ping_at,
            last_pong_at_utc=self._last_pong_at,
            last_keepalive_ok_at_utc=self._last_keepalive_ok_at,
            consecutive_keepalive_failures=self._keepalive_failures,
        )

    # -- lifecycle ----------------------------------------------------------- #

    async def start(self) -> None:
        """Connect and take the first snapshot; returns once LIVE or once the start halted.

        An exhausted connect raises nothing: the state is UNKNOWN and the failure reported.
        """
        if self._started:
            raise RuntimeError("UserDataSupervisor.start() called twice")
        self._started = True
        done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._start_done = done
        self._adapter.set_connection_listener(self._on_connection_event)
        self._spawn(self._control_loop())
        self._spawn(self._pump())
        self._post(_StartCommand())
        await done

    async def stop(self, *, close_listen_key: bool) -> None:
        """Cancel every task, drain the commands, stop the adapter, set STOPPED (idempotent).

        `close_listen_key` has no default: the listenKey is an account-level singleton and a
        DELETE ends the stream of every holder (research P7), so the caller decides each time.
        """
        if self._stopped:
            return
        self._stopped = True
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        while not self._commands.empty():
            self._commands.get_nowait()
        self._held.clear()
        self._pending_items = 0
        self._adapter.set_connection_listener(None)
        try:
            await self._adapter.stop(close_listen_key=close_listen_key)
        except Exception as exc:
            log.warning("userdata.supervisor.adapter_stop_failed", error_type=type(exc).__name__)
        self._set_state(StreamState.STOPPED, REASON_STOP)
        if self._start_done is not None and not self._start_done.done():
            self._start_done.set_result(None)

    # -- task bookkeeping (paper supervisor precedent, not imported) --------- #

    def _spawn(self, coroutine: Awaitable[None]) -> asyncio.Task[None]:
        task: asyncio.Task[None] = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("userdata.supervisor.task_failed", error_type=type(exc).__name__)

    def _post(self, command: _Command) -> None:
        if self._stopped:
            return
        self._commands.put_nowait(command)

    # -- producers: they only post ------------------------------------------ #

    def _on_connection_event(self, event: ConnectionEvent) -> None:
        """Adapter connection listener (event-loop thread): post and return at once."""
        self._post(_ConnectionCommand(event))

    async def _pump(self) -> None:
        """Move adapter queue items into commands; stop pulling while the hold bound is full.

        A full bound makes the adapter's own bounded queue fill and overflow, which the control
        task then handles as a gap (the overflow path), so nothing is dropped silently here.
        """
        queue = self._adapter.queue
        while True:
            item = await queue.get()
            while self._pending_items >= self._limits.event_queue_max:
                self._room.clear()
                await self._room.wait()
            self._pending_items += 1
            live = self._state is StreamState.LIVE
            self._post(_ItemCommand(item, self._generation if live else None))

    # -- the control task ---------------------------------------------------- #

    async def _control_loop(self) -> None:
        while True:
            command = await self._commands.get()
            try:
                await self._handle(command)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error(
                    "userdata.supervisor.command_failed",
                    command=type(command).__name__,
                    error_type=type(exc).__name__,
                )
                self._pending_step = _stronger(self._pending_step, _Step.SYNC)
                self._halt(REASON_INTERNAL_ERROR)

    async def _handle(self, command: _Command) -> None:
        if self._stopped:
            return
        if isinstance(command, _ItemCommand):
            self._accept_item(command)
        elif isinstance(command, _ConnectionCommand):
            await self._handle_connection(command.event)
        elif isinstance(command, _StartCommand):
            try:
                self._set_state(StreamState.CONNECTING, REASON_START)
                await self._run_recovery(_Step.CONNECT)
            finally:
                if self._start_done is not None and not self._start_done.done():
                    self._start_done.set_result(None)

    # -- events -------------------------------------------------------------- #

    def _accept_item(self, command: _ItemCommand) -> None:
        item = command.item
        self._last_event_at = item.received_at_utc
        if self._state is StreamState.LIVE:
            self._deliver(item, after_gap=command.live_generation != self._generation)
        else:
            self._held.append(item)

    def _deliver(self, item: QueuedStreamItem, *, after_gap: bool) -> None:
        self._pending_items -= 1
        if self._pending_items < self._limits.event_queue_max:
            self._room.set()
        self._call_sink(
            "on_event",
            self._on_event,
            TrustedEvent(
                outcome=item.outcome,
                received_at_utc=item.received_at_utc,
                connection_epoch=item.connection_epoch,
                after_gap=after_gap,
            ),
        )

    # -- connection events --------------------------------------------------- #

    async def _handle_connection(self, event: ConnectionEvent) -> None:
        name = event.name
        if name == "ping":
            self._last_ping_at = event.at_utc
            return
        if name == "pong":
            self._last_pong_at = event.at_utc
            return
        # An event of a connection the adapter has since replaced (its own rebuild closing
        # the old client, or the SDK's immediate "open" during a connect) is stale.
        stale = event.epoch < self._adapter.epoch
        if name == "close":
            if stale and self._adapter.private_connection_open():
                log.info("userdata.supervisor.stale_close_ignored")
                return
            await self._lose(_Step.REBUILD, REASON_CONNECTION_CLOSED)
        elif name == "error":
            # A callback error surfaces as "error" on a healthy socket (research P5).
            if self._adapter.private_connection_open():
                log.info("userdata.supervisor.error_on_open_connection_ignored")
                return
            await self._lose(_Step.REBUILD, REASON_CONNECTION_ERROR)
        elif name == "reconnect":
            if stale:
                return
            if self._halted is not None:
                self._pending_step = _stronger(self._pending_step, _Step.SYNC)
                return
            self._awaiting_open = True
            self._pending_step = _stronger(self._pending_step, _Step.SYNC)
            self._set_state(StreamState.UNKNOWN, REASON_SDK_RECONNECT)
        elif name == "open":
            if stale or not self._awaiting_open or self._halted is not None:
                return
            self._awaiting_open = False
            await self._run_recovery(_stronger(self._pending_step, _Step.SYNC))

    # -- recovery ------------------------------------------------------------ #

    async def _lose(self, step: _Step, reason: str) -> None:
        """A loss of continuity: UNKNOWN, then the recovery (or only the step, when halted)."""
        wanted = _stronger(self._pending_step, step)
        if self._halted is not None:
            self._pending_step = wanted
            log.info("userdata.supervisor.loss_while_halted", reason=reason, step=wanted.value)
            return
        self._set_state(StreamState.UNKNOWN, reason)
        await self._run_recovery(wanted)

    async def _run_recovery(self, step: _Step) -> None:
        """Run `step` (connect, rekey or rebuild) under its bound, then the snapshot."""
        self._pending_step = step
        try:
            if step is _Step.CONNECT:
                await self._bounded_reconnect(self._adapter.start, CONNECT_EXHAUSTED)
                self._after_connect()
            elif step is _Step.REBUILD:
                await self._bounded_reconnect(self._adapter.rebuild, REBUILD_EXHAUSTED)
                self._after_connect()
            self._pending_step = _Step.SYNC
            await self._sync()
            self._pending_step = None
        except _RecoveryHalted as halted:
            self._halt(halted.reason)

    def _after_connect(self) -> None:
        self._awaiting_open = False

    async def _sync(self) -> None:
        """SYNCING, a bounded snapshot, `on_snapshot`, then LIVE and the held events."""
        self._set_state(StreamState.SYNCING, REASON_SNAPSHOT)
        await self._bounded(
            self._snapshot_attempt,
            max_attempts=self._limits.snapshot_max_attempts,
            max_delay_seconds=None,
            wait_multiplier=self._limits.snapshot_wait_multiplier_seconds,
            wait_max=self._limits.snapshot_wait_max_seconds,
            exhausted=SNAPSHOT_EXHAUSTED,
        )
        self._adapter.clear_overflow()
        self._enter_live()

    async def _snapshot_attempt(self) -> None:
        """One attempt: the provider within its deadline, then `on_snapshot`.

        An event lost to an overflow while the attempt ran may postdate the snapshot, so such
        an attempt fails and the next one is taken.
        """
        losses_before = self._adapter.overflow_count
        payload = await self._snapshot_within_deadline()
        if self._adapter.overflow_count != losses_before:
            raise RuntimeError("events were lost while the snapshot was taken")
        snapshot = StreamSnapshot(taken_at_utc=self._clock(), payload=payload)
        self._on_snapshot(snapshot, self._adapter.epoch)

    async def _snapshot_within_deadline(self) -> object:
        """The provider raced against the injected sleep of `snapshot_deadline_seconds`."""
        work = asyncio.ensure_future(self._snapshot_provider())
        timer = asyncio.ensure_future(self._sleep(self._limits.snapshot_deadline_seconds))
        try:
            done, _ = await asyncio.wait((work, timer), return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (work, timer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, timer, return_exceptions=True)
        if work in done:
            return work.result()
        raise SnapshotDeadlineExceeded("snapshot attempt exceeded its deadline")

    def _enter_live(self) -> None:
        self._generation += 1
        self._halted = None
        self._set_state(StreamState.LIVE, REASON_SNAPSHOT_OK)
        held, self._held = self._held, []
        for item in held:
            self._deliver(item, after_gap=True)

    async def _bounded_reconnect(
        self, operation: Callable[[], Awaitable[None]], label: str
    ) -> None:
        limits = self._limits
        await self._bounded(
            operation,
            max_attempts=limits.reconnect_max_attempts,
            max_delay_seconds=limits.reconnect_max_delay_seconds,
            wait_multiplier=limits.reconnect_wait_multiplier_seconds,
            wait_max=limits.reconnect_wait_max_seconds,
            exhausted=label,
        )

    async def _bounded(
        self,
        operation: Callable[[], Awaitable[None]],
        *,
        max_attempts: int,
        max_delay_seconds: int | None,
        wait_multiplier: int,
        wait_max: int,
        exhausted: str,
    ) -> None:
        """Tenacity with the injected sleep; exhaustion becomes `_RecoveryHalted(exhausted)`."""
        stop: stop_base = tenacity.stop_after_attempt(max_attempts)
        if max_delay_seconds is not None:
            stop = stop | _StopAfterVirtualDelay(
                self._clock, self._clock(), timedelta(seconds=max_delay_seconds)
            )
        retrying = tenacity.AsyncRetrying(
            sleep=self._sleep,
            stop=stop,
            wait=tenacity.wait_random_exponential(multiplier=wait_multiplier, max=wait_max),
            retry=tenacity.retry_if_exception(_retryable),
            reraise=False,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    await operation()
        except tenacity.RetryError as exc:
            last = exc.last_attempt.exception()
            log.error(
                "userdata.supervisor.retry_exhausted",
                reason=exhausted,
                attempts=exc.last_attempt.attempt_number,
                error_type=type(last).__name__ if last is not None else None,
            )
            raise _RecoveryHalted(exhausted) from None

    # -- state and sinks ----------------------------------------------------- #

    def _halt(self, reason: str) -> None:
        """UNKNOWN, report once, and wait for `request_resync()`."""
        self._halted = reason
        self._set_state(StreamState.UNKNOWN, reason)
        self._call_sink("on_failure", self._on_failure, reason)

    def _set_state(self, state: StreamState, reason: str) -> None:
        if state is self._state:
            return
        self._state = state
        self._state_since = self._clock()
        log.info("userdata.supervisor.state", state=state.value, reason=reason)
        self._call_sink("on_state_change", self._on_state_change, state, reason)

    def _call_sink(self, name: str, sink: Callable[..., None], *args: object) -> None:
        try:
            sink(*args)
        except Exception as exc:
            log.error("userdata.supervisor.sink_failed", sink=name, error_type=type(exc).__name__)


__all__ = [
    "LivenessSnapshot",
    "SnapshotDeadlineExceeded",
    "StreamSnapshot",
    "StreamState",
    "SupervisedAdapter",
    "TrustedEvent",
    "UserDataSupervisor",
]
