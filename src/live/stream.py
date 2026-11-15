"""The user-data stream of the live process, wired to the protection coordinator (plan 24-18).

D-14 (24-NOTES item 4): the Phase 18 router is the only consumer of the user-data stream, and until
this module exists a filled entry has no stop in any real process. `build_stream` assembles, over
the exchange bundle of plan 24-12 (the listen-key port already holds the process-wide REST gate and
the stream configuration is the environment row's, so no `/private` URL is built here, D-16):

  transport (`SdkUserDataTransport`) -> `UserDataAdapter` -> `UserDataSupervisor` (shared gate,
  REST snapshot provider; keepalive, rotation and reconnect stay in the supervisor)
    -> `on_event` -> `UserDataRouter` (`order_lookup` is the live client-id index)
    -> ONE `fill_sink`: the fill fan-out below.

The stream is evidence and trigger; REST stays the truth (Phase 21 D-01). Nothing here fabricates
state: an unknown client id is the router's divergence and never reaches the coordinator.

The fill fan-out (research Pattern 5) is synchronous, never raises and never blocks the loop. In
order: `coordinator.fill_sink(routed)` (memory only), the protection wake event (the step runs at
once instead of at the next period, assumption A1), `equity.invalidate(...)` (memory only), and
`day_risk.ingest_fill(...)` scheduled on the StoreExecutor writer thread (it writes a store). A
member that raises does not skip the others; it is counted and journaled by member name and
exception class name only (never a message), the journal row itself going through the writer.
If the day-loss write cannot be scheduled or fails, the day loss is made unknown (fail closed).

`fills_fallback` (research C-5) is called inside the synchronous `route`, but a REST fill read is
async: it returns an empty sequence at once and schedules the async read as a task on the running
loop (never a nested loop, never a blocking call). The fills it reads are delivered to the same
fan-out as `REST_FALLBACK` fills. The reader itself is injected; without one nothing is scheduled
and the router's own FILL_TOTAL_MISMATCH divergence is the only trace.

`make_protection_step` is the body of the scheduler's protection task: a periodic tick is one
`coordinator.step()`; a tick that follows a fill is `WOKEN_STEP_PASSES` passes, because one pass
only places the stop and the next pass confirms it by REST (and the one after runs the post-fill
liquidation comparison of D-24), none of which should wait a whole period.

No wall clock is read and nothing sleeps: the clock and sleep are injected.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog
from binance_common.configuration import ConfigurationWebSocketStreams

from src.adapters.binance_limits import StreamLimits
from src.adapters.binance_userdata import SdkUserDataTransport, UserDataAdapter
from src.adapters.binance_userdata_events import AccountUpdateEvent
from src.adapters.binance_userdata_router import (
    AlgoRoute,
    ExchangeStateUpdate,
    FillSource,
    OrderLookup,
    OrderStatusHint,
    RoutedFill,
    StreamDivergence,
    UserDataRouter,
)
from src.adapters.binance_userdata_supervisor import (
    SnapshotProvider,
    StreamSnapshot,
    StreamState,
    TrustedEvent,
    UserDataSupervisor,
)
from src.domain.journal import JournalEvent, correlated_event_id
from src.execution.fill_monitor import FillEvent
from src.live.exchange import ExchangeBundle
from src.ops.store_executor import StoreExecutor

_log = structlog.get_logger(__name__)

# STRUCTURAL: the passes of a step that follows a fill. Pass 1 places the stop, pass 2 confirms it
# by REST, pass 3 runs the post-fill checks of the PROTECTED state (liquidation comparison, D-24).
WOKEN_STEP_PASSES = 3

INVALIDATE_FILL = "ACCOUNT_UPDATE"
INVALIDATE_GAP = "STREAM_GAP"

EVENT_FANOUT_MEMBER_FAILED = "FILL_FANOUT_MEMBER_FAILED"
EVENT_FALLBACK_READ_FAILED = "FILLS_FALLBACK_READ_FAILED"
EVENT_ROUTE_FAILED = "STREAM_ROUTE_FAILED"
_ENTITY_TYPE = "UserDataStream"
_JOURNAL_PREFIX = "live-stream"

MEMBER_COORDINATOR = "coordinator"
MEMBER_WAKE = "wake"
MEMBER_EQUITY = "equity"
MEMBER_DAY_RISK = "day_risk"
MEMBER_DAY_RISK_SCHEDULE = "day_risk_schedule"

FillsReader = Callable[[str], Awaitable[Sequence[FillEvent]]]


class FillSinkLike(Protocol):
    """The coordinator's fill sink (`ProtectionCoordinator.fill_sink`)."""

    def fill_sink(self, routed: RoutedFill) -> None: ...


class StepLike(Protocol):
    """The coordinator surface the protection step body needs."""

    async def step(self) -> None: ...


class EquityLike(Protocol):
    """`LiveEquitySource.invalidate`."""

    def invalidate(self, *, reason: str) -> None: ...


class DayRiskLike(Protocol):
    """`LiveDayRiskService.ingest_fill` and `invalidate`."""

    def ingest_fill(self, fill: Any) -> None: ...

    def invalidate(self, *, reason: str) -> None: ...


class JournalLike(Protocol):
    def record(self, event: JournalEvent) -> None: ...


@dataclass(frozen=True, kw_only=True)
class StreamSinks:
    """The router sinks other than the fill sink (persistence and feeds, plan 24-19)."""

    status_hint_sink: Callable[[OrderStatusHint], None]
    exchange_state_sink: Callable[[ExchangeStateUpdate], None]
    algo_sink: Callable[[AlgoRoute], None]
    account_sink: Callable[[AccountUpdateEvent], None]
    divergence_sink: Callable[[StreamDivergence], None]


class _TaskSet:
    """Fire-and-forget tasks on the running loop, kept alive until they finish."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, coro: Coroutine[Any, Any, None]) -> bool:
        """Schedule `coro`; False (and the coroutine closed) when no loop is running."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return False
        task = loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    @property
    def pending(self) -> int:
        return len(self._tasks)

    async def drain(self) -> None:
        """Wait until every scheduled task (and any it scheduled meanwhile) has finished."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


class _FailureJournal:
    """Journal rows about the stream's own failures: by name and class only, via the writer."""

    def __init__(
        self,
        *,
        journal: JournalLike,
        executor: StoreExecutor,
        clock: Callable[[], Any],
        session_id: str,
        tasks: _TaskSet,
    ) -> None:
        self._journal = journal
        self._executor = executor
        self._clock = clock
        self._session_id = session_id
        self._tasks = tasks

    def note(self, event_type: str, *, entity_id: str, step: str, error: BaseException) -> None:
        """Record `error`'s class name; never raises and never blocks."""
        try:
            correlation = f"{_JOURNAL_PREFIX}:{self._session_id}"
            event = JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix=_JOURNAL_PREFIX,
                    correlation_id=correlation,
                    event_type=event_type,
                    entity_id=entity_id,
                    step=step,
                ),
                occurred_at_utc=self._clock(),
                event_type=event_type,
                entity_type=_ENTITY_TYPE,
                entity_id=entity_id,
                correlation_id=correlation,
                payload_json=json.dumps(
                    {"member": entity_id, "error_class": type(error).__name__},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            _log.warning(event_type.lower(), member=entity_id, error=type(error).__name__)
            self._tasks.spawn(self._write(event))
        except Exception as exc:  # noqa: BLE001 - an audit row must not break the stream
            _log.warning("live_stream_journal_failed", error=type(exc).__name__)

    async def _write(self, event: JournalEvent) -> None:
        try:
            await self._executor.write(self._journal.record, event)
        except Exception as exc:  # noqa: BLE001 - the writer may be closed at shutdown
            _log.warning("live_stream_journal_write_failed", error=type(exc).__name__)


class FillFanout:
    """The router's single `fill_sink`: coordinator, wake, equity, day loss. See the module doc."""

    def __init__(
        self,
        *,
        coordinator: FillSinkLike,
        wake: asyncio.Event,
        equity: EquityLike,
        day_risk: DayRiskLike,
        executor: StoreExecutor,
        failures: _FailureJournal,
        tasks: _TaskSet,
    ) -> None:
        self._coordinator = coordinator
        self._wake = wake
        self._equity = equity
        self._day_risk = day_risk
        self._executor = executor
        self._failures = failures
        self._tasks = tasks
        self.fills_seen = 0
        self.member_failures: dict[str, int] = {}

    @property
    def tasks(self) -> _TaskSet:
        """The one task set of the stream, so one drain covers the fan-out and the fallback."""
        return self._tasks

    @property
    def failure_journal(self) -> _FailureJournal:
        return self._failures

    def __call__(self, routed: RoutedFill) -> None:
        """Hand one routed fill to every member; never raises, never blocks."""
        self.fills_seen += 1
        step = _fill_key(routed)
        self._member(MEMBER_COORDINATOR, step, lambda: self._coordinator.fill_sink(routed))
        self._member(MEMBER_WAKE, step, self._wake.set)
        reason = INVALIDATE_GAP if routed.after_gap else INVALIDATE_FILL
        self._member(MEMBER_EQUITY, step, lambda: self._equity.invalidate(reason=reason))
        scheduled = False
        try:
            scheduled = self._tasks.spawn(self._ingest(routed, step))
        except Exception as exc:  # noqa: BLE001
            self._fail(MEMBER_DAY_RISK_SCHEDULE, step, exc)
        if not scheduled:
            self._day_loss_unknown()

    def _member(self, name: str, step: str, call: Callable[[], object]) -> None:
        try:
            call()
        except Exception as exc:  # noqa: BLE001 - one member must not skip the others
            self._fail(name, step, exc)

    def _fail(self, name: str, step: str, exc: BaseException) -> None:
        self.member_failures[name] = self.member_failures.get(name, 0) + 1
        self._failures.note(EVENT_FANOUT_MEMBER_FAILED, entity_id=name, step=step, error=exc)

    def _day_loss_unknown(self) -> None:
        """Fail closed: a fill that was not added to the day loss makes the loss unknown."""
        try:
            self._day_risk.invalidate(reason=INVALIDATE_FILL)
        except Exception as exc:  # noqa: BLE001
            _log.warning("live_stream_day_risk_invalidate_failed", error=type(exc).__name__)

    async def _ingest(self, routed: RoutedFill, step: str) -> None:
        try:
            await self._executor.write(self._day_risk.ingest_fill, routed.fill)
        except Exception as exc:  # noqa: BLE001
            self._fail(MEMBER_DAY_RISK, step, exc)
            self._day_loss_unknown()

    async def drain(self) -> None:
        """Wait for the scheduled day-loss writes and journal rows (shutdown and tests)."""
        await self._tasks.drain()


class FillsFallback:
    """The router's `fills_fallback`: returns `()` at once, reads the fills afterwards."""

    def __init__(
        self,
        *,
        reader: FillsReader | None,
        deliver: Callable[[RoutedFill], None],
        failures: _FailureJournal,
        tasks: _TaskSet,
    ) -> None:
        self._reader = reader
        self._deliver = deliver
        self._failures = failures
        self._tasks = tasks
        self._in_flight: set[str] = set()
        self.scheduled = 0

    def __call__(self, exchange_order_id: str) -> Sequence[FillEvent]:
        reader = self._reader
        if reader is None or exchange_order_id in self._in_flight:
            return ()
        self._in_flight.add(exchange_order_id)
        if self._tasks.spawn(self._read(reader, exchange_order_id)):
            self.scheduled += 1
        else:
            self._in_flight.discard(exchange_order_id)
        return ()

    async def _read(self, reader: FillsReader, exchange_order_id: str) -> None:
        try:
            fills = list(await reader(exchange_order_id))
            for fill in fills:
                self._deliver(
                    RoutedFill(fill=fill, source=FillSource.REST_FALLBACK, after_gap=False)
                )
        except Exception as exc:  # noqa: BLE001 - the read is evidence, never a crash
            self._failures.note(
                EVENT_FALLBACK_READ_FAILED,
                entity_id="fills_fallback",
                step=exchange_order_id,
                error=exc,
            )
        finally:
            self._in_flight.discard(exchange_order_id)


def _fill_key(routed: RoutedFill) -> str:
    fill = routed.fill
    return f"{fill.order_id}:{fill.exchange_trade_id}:{routed.source.value}"


def make_fill_fanout(
    *,
    coordinator: FillSinkLike,
    wake: asyncio.Event,
    equity: EquityLike,
    day_risk: DayRiskLike,
    executor: StoreExecutor,
    journal: JournalLike,
    clock: Callable[[], Any],
    session_id: str,
) -> FillFanout:
    """The fill fan-out over its members (see the module docstring)."""
    tasks = _TaskSet()
    failures = _FailureJournal(
        journal=journal, executor=executor, clock=clock, session_id=session_id, tasks=tasks
    )
    return FillFanout(
        coordinator=coordinator,
        wake=wake,
        equity=equity,
        day_risk=day_risk,
        executor=executor,
        failures=failures,
        tasks=tasks,
    )


def make_fills_fallback(
    *,
    fanout: FillFanout,
    reader: FillsReader | None,
    journal: JournalLike,
    executor: StoreExecutor,
    clock: Callable[[], Any],
    session_id: str,
) -> FillsFallback:
    """The non-blocking `fills_fallback`; its fills are delivered to `fanout`."""
    tasks = fanout.tasks
    failures = fanout.failure_journal
    return FillsFallback(reader=reader, deliver=fanout, failures=failures, tasks=tasks)


def make_protection_step(
    coordinator: StepLike, fanout: FillFanout
) -> Callable[[], Awaitable[None]]:
    """The scheduler body of the protection task (one pass per tick, more after a fill)."""
    seen = 0

    async def run() -> None:
        nonlocal seen
        now_seen = fanout.fills_seen
        woken = now_seen != seen
        seen = now_seen
        await coordinator.step()
        if woken:
            for _ in range(WOKEN_STEP_PASSES - 1):
                await coordinator.step()

    return run


@dataclass(frozen=True, kw_only=True)
class StreamBundle:
    """The stream objects of the live process (every field required)."""

    supervisor: UserDataSupervisor
    router: UserDataRouter
    adapter: UserDataAdapter
    wake: asyncio.Event
    fanout: FillFanout
    fills_fallback: FillsFallback
    failures: list[str] = field(default_factory=list)


def build_stream(
    *,
    exchange: ExchangeBundle,
    stream_limits: StreamLimits,
    clock: Callable[[], Any],
    sleep: Callable[[float], Awaitable[None]],
    journal: JournalLike,
    index: OrderLookup,
    coordinator: FillSinkLike,
    equity: EquityLike,
    day_risk: DayRiskLike,
    executor: StoreExecutor,
    snapshot_provider: SnapshotProvider,
    sinks: StreamSinks,
    session_id: str,
    fills_reader: FillsReader | None = None,
    on_state_change: Callable[[StreamState, str], None] | None = None,
    on_snapshot: Callable[[StreamSnapshot, int], None] | None = None,
    on_failure: Callable[[str], None] | None = None,
    stream_configuration: ConfigurationWebSocketStreams | None = None,
    ws_client_factory: Any = None,
    ws_client: Any = None,
) -> StreamBundle:
    """Assemble transport, adapter, supervisor, router and the fill fan-out (D-14).

    Makes no network call and starts nothing: the start sequence awaits `supervisor.start()`.
    `stream_configuration`, `ws_client_factory` and `ws_client` exist for tests; by default the
    transport uses the exchange bundle's environment-row configuration and the SDK client.
    """
    wake = asyncio.Event()
    fanout = make_fill_fanout(
        coordinator=coordinator,
        wake=wake,
        equity=equity,
        day_risk=day_risk,
        executor=executor,
        journal=journal,
        clock=clock,
        session_id=session_id,
    )
    fallback = make_fills_fallback(
        fanout=fanout,
        reader=fills_reader,
        journal=journal,
        executor=executor,
        clock=clock,
        session_id=session_id,
    )
    router = UserDataRouter(
        order_lookup=index,
        journal=journal,
        session_id=session_id,
        clock=clock,
        fill_sink=fanout,
        status_hint_sink=sinks.status_hint_sink,
        exchange_state_sink=sinks.exchange_state_sink,
        algo_sink=sinks.algo_sink,
        account_sink=sinks.account_sink,
        divergence_sink=sinks.divergence_sink,
        fills_fallback=fallback,
    )
    transport = SdkUserDataTransport(
        stream_configuration if stream_configuration is not None else exchange.stream_configuration,
        client_factory=ws_client_factory,
        ws_client=ws_client,
    )
    adapter = UserDataAdapter(
        transport=transport,
        listen_keys=exchange.listen_keys,
        limits=stream_limits,
        clock=clock,
    )
    reasons: list[str] = []
    failures = fanout.failure_journal

    def route_event(event: TrustedEvent) -> None:
        try:
            router.route(event)
        except Exception as exc:  # noqa: BLE001 - never into the supervisor loop
            failures.note(
                EVENT_ROUTE_FAILED, entity_id="router", step=str(event.connection_epoch), error=exc
            )

    def state_changed(state: StreamState, reason: str) -> None:
        if state is StreamState.UNKNOWN:  # a gap: the equity and the day loss are untrustworthy
            gap_calls: list[tuple[str, Callable[[], None]]] = [
                (MEMBER_EQUITY, lambda: equity.invalidate(reason=INVALIDATE_GAP)),
                (MEMBER_DAY_RISK, lambda: day_risk.invalidate(reason=INVALIDATE_GAP)),
            ]
            for name, call in gap_calls:
                try:
                    call()
                except Exception as exc:  # noqa: BLE001
                    failures.note(
                        EVENT_FANOUT_MEMBER_FAILED, entity_id=name, step=f"gap:{reason}", error=exc
                    )
        if on_state_change is not None:
            on_state_change(state, reason)

    def snapshot_taken(snapshot: StreamSnapshot, epoch: int) -> None:
        if on_snapshot is not None:
            on_snapshot(snapshot, epoch)

    def failed(reason: str) -> None:
        reasons.append(reason)
        _log.warning("live_stream_failure", reason=reason)
        if on_failure is not None:
            on_failure(reason)

    supervisor = UserDataSupervisor(
        adapter=adapter,
        limits=stream_limits,
        clock=clock,
        sleep=sleep,
        rest_gate=exchange.gate,
        snapshot_provider=snapshot_provider,
        on_state_change=state_changed,
        on_event=route_event,
        on_snapshot=snapshot_taken,
        on_failure=failed,
    )
    return StreamBundle(
        supervisor=supervisor,
        router=router,
        adapter=adapter,
        wake=wake,
        fanout=fanout,
        fills_fallback=fallback,
        failures=reasons,
    )


__all__ = [
    "EVENT_FALLBACK_READ_FAILED",
    "EVENT_FANOUT_MEMBER_FAILED",
    "EVENT_ROUTE_FAILED",
    "INVALIDATE_FILL",
    "INVALIDATE_GAP",
    "WOKEN_STEP_PASSES",
    "FillFanout",
    "FillsFallback",
    "StreamBundle",
    "StreamSinks",
    "build_stream",
    "make_fill_fanout",
    "make_fills_fallback",
    "make_protection_step",
]
