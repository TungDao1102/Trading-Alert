"""The paper process entrypoint: `python -m src.paper.runtime` (plan 16-22, D-01, L-05, D061 E).

Order of `main` (each step may end the process before the next one runs):

1. Configure redacted logging.
2. Trade-key refusal: any `BINANCE_*` name in the environment exits 3 (names only are printed).
3. Start gate: the approved allowlist is read through the freeze accessors only. An empty
   allowlist logs "SKIPPED (allowlist empty)" and exits 0, before any adapter, database engine
   or Telegram application is constructed, and with no fallback to any set.
4. Admission (the user's decision Q-A, `runtime-exact-hash-all`): the runtime process gate
   requires an exact-hash allowlist entry for EVERY parameter set, a fully rationalized one
   included. It runs before any candle is parsed and before `pin_stream_epoch`. A missing entry
   or a hash that differs from the registry file's hash exits 6. A match only lets the existing
   validation continue; `pin_stream_epoch` (unchanged) still judges the set afterwards.
5. The ratified runtime configuration (exit 4 when anything is absent).
6. The epoch: pinned only on the explicit operator flag `--pin-epoch` when no pinned state
   exists; every restart loads the stored epoch and never mints one (exit 5 without a pin,
   exit 6 on any mismatch).
7. RUNTIME_START, the run, RUNTIME_STOP (recorded only on a clean stop, so a crash leaves a
   START without a STOP, which the coverage code reads as a crash).

Two layers, deliberately different (see config/paper/README.md): the runtime process gate here
(exact-hash authorization for every set) and the per-call rule inside `pin_stream_epoch` (an
entry is required only for a set without rationale tables). Rationale tables never replace
runtime authorization.

Exit codes are the named table `ExitCode` in `src/paper/runtime_config.py`. With the opt-in
flag `--hold-on-refusal` (used by the compose service) a refusal does not exit: the process logs
it, stays up and returns the refusal code only after SIGTERM or SIGINT, so a restart policy can
never loop on a refusal. SKIPPED and restartable failures are never held.

The live loop (plan 16-26, `run_admitted`) composes the credential-free public adapter, the
`PaperWsAdapter`, the `PaperSupervisor`, ONE bounded asyncio queue, ONE consumer task and the
`BarPipeline`:

    SDK message -> supervisor sink -> `queue.put_nowait` -> consumer -> `BarPipeline.handle` in
    `asyncio.to_thread` -> `RuntimeStatePort`

The receive callbacks only enqueue (research P10): every database write and the whole tick run
off the event loop through the one synchronous state port, wrapped locally with
`asyncio.to_thread` (the Phase 24 item G4-040 choice between threads and an async pool stays
open). A full queue, a failed write or a pipeline error stops the loop, unsubscribes and closes the
adapter and ends the process with `ExitCode.FAIL_CLOSED_RUNTIME` WITHOUT a RUNTIME_STOP record, so
the restart reads the open RUNTIME_START as a crash. A requested stop (SIGTERM or SIGINT)
unsubscribes, closes the adapter and returns normally; `main` then records RUNTIME_STOP.

Every consumer batch writes one PAPER_TICK_STATS record: the tick time, the batch counts, the
dropped-event counts by reason (a host clock running behind drops closed bars, research P20) and
the measured duration of the `BarPipeline.handle` call (assumption A10: a tick ends well inside a
bar interval). The duration comes from the injected monotonic function and feeds no decision.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import structlog

from src.core.types import Candle
from src.ops.redaction import configure_logging
from src.paper.bars import BarBuffers
from src.paper.freeze import (
    PaperAllowlistEntry,
    StreamEpoch,
    allowlist_entries,
    find_allowlist_entry,
    load_parameter_set_at_root,
    load_pinned_state,
    pin_stream_epoch,
    resolve_registry_root,
    write_pinned_state,
)
from src.paper.loop import BarContext
from src.paper.market_inputs import (
    ConstraintProvider,
    make_context_factory,
    make_sibling_fetcher,
    measure_clock_skew,
    refresh_forever,
)
from src.paper.pipeline import BarPipeline, HeldBar, PipelineResult
from src.paper.restart import (
    RestartPlan,
    apply_restart_fence,
    downtime_gaps,
    health_record,
    restart_gap_record,
    restore_runtime,
    supervisor_cursors,
    warm_up,
)
from src.paper.runtime_config import (
    ConfigNotRatified,
    ExitCode,
    RuntimeConfig,
    load_runtime_config,
    read_env,
    refuse_trade_capable_env,
)
from src.paper.runtime_state import RuntimeRecord, RuntimeRecordConflict, RuntimeStatePort
from src.paper.supervisor import PaperSupervisor
from src.paper.vocabulary import (
    GapReason,
    GapRecord,
    HealthState,
    RuntimeEventType,
    SourceTag,
    TaggedBar,
)
from src.persistence.errors import PersistenceError

SKIPPED_EVENT = "SKIPPED (allowlist empty)"
DEFAULT_PINNED_STATE = Path("logs/paper/pinned_epoch.json")

# Capacity of the inbound bar queue. An implementation value (CONTEXT, Claude's discretion), NOT a
# ratified threshold: it only has to hold one REST backfill burst after an outage (a few hundred
# bars per pair) with room to spare. A full queue is never absorbed: the process fails closed.
QUEUE_MAXSIZE = 4096

# The two intervals the loop subscribes to: the 1h setup bars and the 4h context bars.
LOOP_INTERVALS: tuple[str, ...] = ("1h", "4h")

# Origin tag of a PAPER_GAP the supervisor reports (the pipeline writes its own gaps with
# `GAP_DETAIL_*` tags; a gap detected by both with a different payload would be a conflict).
GAP_DETAIL_SUPERVISOR = "SUPERVISOR"

log = structlog.get_logger()


@dataclass(frozen=True)
class RuntimeContext:
    """What the run (plan 16-26) receives once the process has been admitted and started."""

    epoch: StreamEpoch
    config: RuntimeConfig
    state: RuntimeStatePort
    env: Mapping[str, str]
    clock: Callable[[], datetime]
    registry_root: Path | None
    # The time of this run's own RUNTIME_START (set by `main`): markers before it are the previous
    # run, which tells a planned restart from a crash (plan 16-29).
    started_at_utc: datetime | None = None


def build_parser() -> argparse.ArgumentParser:
    """The command line of the paper process (plan 16-32 parses the compose command with it)."""
    parser = argparse.ArgumentParser(
        prog="python -m src.paper.runtime",
        description="Paper runtime: once-per-process start gate, then the paper loop.",
    )
    parser.add_argument(
        "--hold-on-refusal",
        action="store_true",
        help=(
            "On a refusal (exit codes 3 to 6) log it and stay up until SIGTERM or SIGINT "
            "instead of exiting, so a restart policy cannot loop on it."
        ),
    )
    parser.add_argument(
        "--pin-epoch",
        action="store_true",
        help=(
            "Operator command: pin the epoch of this trial when no pinned state exists. "
            "Without it a start needs an existing pinned state and reuses its epoch."
        ),
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help=(
            "Container probe: print healthy and exit with status zero only while the last "
            "processed closed bar is younger than the ratified maximum age; otherwise print "
            "unhealthy and a reason and exit with status one."
        ),
    )
    parser.add_argument(
        "--pinned-state",
        type=Path,
        default=DEFAULT_PINNED_STATE,
        help=f"Path of the pinned-state JSON file (default: {DEFAULT_PINNED_STATE.as_posix()}).",
    )
    return parser


def wait_for_stop_signal() -> None:
    """Block until SIGTERM or SIGINT arrives (the production `wait_for_stop`)."""
    stop = threading.Event()

    def _handler(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    stop.wait()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _refuse(
    code: ExitCode,
    reason: str,
    *,
    hold: bool,
    wait_for_stop: Callable[[], None],
) -> int:
    """Report a refusal on stderr and in the log; hold until stopped when asked to."""
    print(f"paper runtime refused (exit {int(code)}): {reason}", file=sys.stderr)
    structlog.get_logger().error("paper runtime refused", exit_code=int(code), reason=reason)
    if hold:
        wait_for_stop()
    return int(code)


def _admit(
    strategy_id: str, parameter_set_id: str, registry_root: Path | None
) -> tuple[PaperAllowlistEntry | None, str | None]:
    """The strict runtime gate (Q-A): an exact-hash entry for this set, rationalized or not.

    Returns (entry, None) when admitted, or (None, reason) when not. Pure admission: it reads
    the allowlist and the registry file and decides nothing else; `pin_stream_epoch` still
    runs its full validation afterwards.
    """
    try:
        entry = find_allowlist_entry(strategy_id, parameter_set_id)
    except ValueError as exc:
        return None, str(exc)
    if entry is None:
        return None, (
            f"no allowlist entry for {strategy_id}/{parameter_set_id}: the runtime gate "
            "requires an exact-hash entry for every parameter set, rationalized or not (Q-A)"
        )
    try:
        file_hash = load_parameter_set_at_root(
            strategy_id, parameter_set_id, resolve_registry_root(registry_root)
        ).parameter_set_hash
    except Exception as exc:  # fail closed on any defect of the file, naming only the type
        return None, f"{strategy_id}/{parameter_set_id}: cannot load the set ({type(exc).__name__})"
    if file_hash != entry.parameter_set_hash:
        return None, (
            f"{strategy_id}/{parameter_set_id}: the allowlist hash {entry.parameter_set_hash} "
            f"does not match the registry file's parameter_set_hash {file_hash}"
        )
    return entry, None


def _state_from_env(values: Mapping[str, str]) -> RuntimeStatePort:
    """The production state port: journal rows on PostgreSQL (Q-J), never an in-memory fallback."""
    url = values.get("DATABASE_URL_SYNC") or values.get("DATABASE_URL")
    if not url:
        raise ConfigNotRatified(["DATABASE_URL_SYNC or DATABASE_URL"])
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    # Imported here so that a SKIPPED start and every refusal never import SQLAlchemy.
    from sqlalchemy import create_engine

    from src.persistence.paper_runtime_state import PgRuntimeState
    from src.persistence.uow import OperationalDatabase

    return PgRuntimeState(OperationalDatabase(create_engine(url, future=True)))


def _epoch_record(
    event_type: RuntimeEventType,
    epoch: StreamEpoch,
    at: datetime,
    extra: Mapping[str, Any] | None = None,
) -> RuntimeRecord:
    return RuntimeRecord(
        event_type=event_type,
        epoch_id=epoch.epoch_id,
        occurred_at_utc=at,
        payload={
            "strategy_id": epoch.strategy_id,
            "parameter_set_id": epoch.parameter_set_id,
            "parameter_set_hash": epoch.parameter_set_hash,
            **(extra or {}),
        },
    )


class RuntimeFailClosed(Exception):
    """The live loop stopped because continuing could not be trusted (exit code 7, restartable).

    The message is this module's own text (a reason such as "queue is full"); the underlying
    exception of a failed write is reported by its type name only, never by its message.
    """


class HandlesBars(Protocol):
    """What the consumer needs from the pipeline (`BarPipeline`; a double in tests)."""

    def handle(self, bars: Iterable[TaggedBar], *, now_utc: datetime) -> PipelineResult: ...


@dataclass(frozen=True)
class LoopWiring:
    """Composition and test seams of `run_admitted`; production binds only `risk_inputs`.

    Every field is optional. Left at None the loop builds the production object: the
    credential-free `BinancePublicMarketData`, a real `PaperWsAdapter`, the real `BarPipeline`, the
    signal-driven stop, the monotonic clock and `asyncio.sleep`. `risk_inputs` (the required
    open-positions and daily-loss port) has no production default in src: plan 16-31 binds it.
    """

    ws_client: Any | None = None
    ws_client_factory: Callable[[Any], Any] | None = None
    public: Any | None = None
    risk_inputs: Any | None = None
    context_factory: Callable[[Candle], BarContext] | None = None
    pipeline: HandlesBars | None = None
    stop_waiter: Callable[[], Awaitable[None]] | None = None
    monotonic_ms: Callable[[], int] | None = None
    sleep: Callable[[timedelta], Awaitable[None]] | None = None
    queue_maxsize: int | None = None


def _monotonic_ms() -> int:
    """The one monotonic reading of the module (whole milliseconds); it feeds no decision."""
    return time.monotonic_ns() // 1_000_000


async def _real_sleep(delay: timedelta) -> None:
    await asyncio.sleep(delay.total_seconds())


async def _wait_for_stop_signal() -> None:
    """Return when SIGTERM or SIGINT arrives (installed on the main thread, every platform)."""
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()

    def _handler(_signum: int, _frame: object) -> None:
        loop.call_soon_threadsafe(stopped.set)

    previous = {
        signal.SIGINT: signal.signal(signal.SIGINT, _handler),
        signal.SIGTERM: signal.signal(signal.SIGTERM, _handler),
    }
    try:
        await stopped.wait()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _gap_record(epoch_id: str, gap: GapRecord) -> RuntimeRecord:
    """The PAPER_GAP record of a gap the supervisor reported (keyed on the expected close)."""
    return RuntimeRecord(
        event_type=RuntimeEventType.PAPER_GAP,
        epoch_id=epoch_id,
        occurred_at_utc=gap.detected_at_utc,
        symbol=gap.symbol,
        interval=gap.interval,
        payload={
            "expected_close_utc": gap.expected_close_utc,
            "reason": gap.reason.value,
            "source": GAP_DETAIL_SUPERVISOR,
        },
    )


def _tick_stats_record(
    *,
    epoch_id: str,
    tick_time: datetime,
    batch_seq: int,
    bars_in: int,
    result: PipelineResult,
    duration_ms: int,
    queue_depth_before: int,
) -> RuntimeRecord:
    """The PAPER_TICK_STATS record of one consumer batch (research P20 and A10).

    `duration_ms` is evidence only; nothing in the loop reads it back to decide anything.
    """
    dropped_by_reason: dict[str, int] = {}
    for dropped in result.dropped:
        key = dropped.reason.value
        dropped_by_reason[key] = dropped_by_reason.get(key, 0) + 1
    return RuntimeRecord(
        event_type=RuntimeEventType.PAPER_TICK_STATS,
        epoch_id=epoch_id,
        occurred_at_utc=tick_time,
        payload={
            "batch_seq": batch_seq,
            "bars_in": bars_in,
            "evaluated": len(result.evaluated),
            "held": len(result.held),
            "duplicates": len(result.duplicates),
            "dropped_total": len(result.dropped),
            "dropped_by_reason": dropped_by_reason,
            "duration_ms": max(0, duration_ms),
            "queue_depth_before": queue_depth_before,
        },
    )


class _LiveLoop:
    """The running composition: sinks, queue, consumer and the shutdown (see the module docstring).

    Everything here runs on the event-loop thread except the two `asyncio.to_thread` calls (the
    pipeline tick and a record write). Failures never raise into the SDK: they are stored once in
    `_failure`, the stop event is set and `run` re-raises after a clean teardown.
    """

    def __init__(
        self,
        *,
        context: RuntimeContext,
        wiring: LoopWiring,
        pipeline: HandlesBars,
        supervisor_factory: Callable[[_LiveLoop], PaperSupervisor],
        restart: RestartPlan,
        constraints: ConstraintProvider | None = None,
    ) -> None:
        self._context = context
        self._restart = restart
        # Closes at or before this instant can only be history (see `apply_restart_fence`).
        self._fence: datetime | None = None
        self._live_seen = False
        self._constraints = constraints
        self._epoch_id = context.epoch.epoch_id
        self._state = context.state
        self._clock = context.clock
        self._pipeline = pipeline
        self._queue: asyncio.Queue[TaggedBar] = asyncio.Queue(
            maxsize=wiring.queue_maxsize if wiring.queue_maxsize is not None else QUEUE_MAXSIZE
        )
        self._monotonic_ms = (
            wiring.monotonic_ms if wiring.monotonic_ms is not None else _monotonic_ms
        )
        self._sleep = wiring.sleep if wiring.sleep is not None else _real_sleep
        self._stop_waiter = (
            wiring.stop_waiter if wiring.stop_waiter is not None else _wait_for_stop_signal
        )
        self._stop = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._failure: BaseException | None = None
        self._batch_seq = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._record_tasks: set[asyncio.Task[None]] = set()
        self._supervisor = supervisor_factory(self)

    # ---- the SDK-facing callbacks: enqueue or schedule, never touch the store ------------- #

    def sinks(self) -> dict[str, Any]:
        return {
            "on_closed_bar": self._sink_closed_bar,
            "on_backfill": self._sink_backfill,
            "on_gap": self._sink_gap,
            "on_connection_event": self._sink_connection_event,
        }

    def _sink_closed_bar(self, bar: TaggedBar) -> None:
        self._enqueue(bar)

    def _sink_backfill(self, bar: TaggedBar) -> None:
        self._enqueue(bar)

    def _sink_gap(self, gap: GapRecord) -> None:
        self._spawn_record(_gap_record(self._epoch_id, gap))

    def _sink_connection_event(self, event: RuntimeEventType, at: datetime) -> None:
        self._spawn_record(
            RuntimeRecord(event_type=event, epoch_id=self._epoch_id, occurred_at_utc=at)
        )

    def _enqueue(self, bar: TaggedBar) -> None:
        if self._fence is not None:
            bar = apply_restart_fence(bar, self._fence)
        if bar.source is SourceTag.LIVE_WS and not self._live_seen:
            # The first live closed event after the warm-up ends the declared DISCONNECTED state.
            self._live_seen = True
            # Strictly after the DISCONNECTED record of this start: a health record is keyed on
            # its time, so two states in the same millisecond would be one conflicting record.
            at = max(self._clock(), self._restart.started_at_utc + timedelta(milliseconds=1))
            self._spawn_record(health_record(self._epoch_id, HealthState.HEALTHY, at))
        try:
            self._queue.put_nowait(bar)
        except asyncio.QueueFull:
            self._fail(RuntimeFailClosed("the inbound bar queue is full: a bar cannot be dropped"))
            raise

    def _spawn_record(self, record: RuntimeRecord) -> None:
        task = asyncio.get_running_loop().create_task(self._write_record(record))
        self._record_tasks.add(task)
        task.add_done_callback(self._record_tasks.discard)

    async def _write_record(self, record: RuntimeRecord) -> None:
        try:
            await asyncio.to_thread(self._state.record, record)
        except Exception as exc:
            self._fail(exc)

    # ---- failure --------------------------------------------------------------------------- #

    def _fail(self, exc: BaseException) -> None:
        if self._failure is None:
            self._failure = exc
            reason = str(exc) if isinstance(exc, RuntimeFailClosed) else type(exc).__name__
            log.error("paper runtime failing closed", reason=reason)
        self._stop.set()

    # ---- the consumer ---------------------------------------------------------------------- #

    async def _consume(self) -> None:
        try:
            while True:
                first = await self._queue.get()
                self._idle.clear()
                try:
                    await self._process_batch(first)
                finally:
                    self._idle.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    async def _process_batch(self, first: TaggedBar) -> None:
        depth_before = self._queue.qsize() + 1  # the batch itself plus what waits behind it
        bars = [first]
        while True:
            try:
                bars.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        now = self._clock()
        started = self._monotonic_ms()
        result = await asyncio.to_thread(self._pipeline.handle, bars, now_utc=now)
        finished = self._monotonic_ms()
        stats = _tick_stats_record(
            epoch_id=self._epoch_id,
            tick_time=now,
            batch_seq=self._batch_seq,
            bars_in=len(bars),
            result=result,
            duration_ms=finished - started,
            queue_depth_before=depth_before,
        )
        self._batch_seq += 1
        await asyncio.to_thread(self._state.record, stats)
        for held in result.held:
            self._schedule_resubmit(held)

    def _schedule_resubmit(self, held: HeldBar) -> None:
        task = asyncio.get_running_loop().create_task(self._resubmit(held))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _resubmit(self, held: HeldBar) -> None:
        """Hand a held 1h bar back to the consumer once its sibling deadline has passed."""
        try:
            wait = held.deadline_utc - self._clock()
            if wait > timedelta(0):
                await self._sleep(wait)
            self._enqueue(held.bar)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    # ---- run and teardown ------------------------------------------------------------------ #

    async def _restore_before_subscribing(self) -> None:
        """Record the downtime, rebuild the engine windows and seed the supervisor (plan 16-29).

        Everything here happens before the first subscription, so the first live bar meets full
        windows, a seeded cursor and a fence; a warm-up bar is history, never a record.
        """
        plan = self._restart
        records = [
            health_record(
                self._epoch_id,
                HealthState.DISCONNECTED,
                plan.started_at_utc,
                GapReason.WS_RECONNECT_WINDOW,
            ),
            *(restart_gap_record(self._epoch_id, gap) for gap in plan.gaps),
        ]
        for record in records:
            await asyncio.to_thread(self._state.record, record)
        if plan.warm.bars:
            result = await asyncio.to_thread(
                self._pipeline.handle, plan.warm.bars, now_utc=plan.snapshot_utc
            )
            if result.evaluated or result.recorded:
                raise RuntimeFailClosed("the REST warm-up evaluated or recorded a bar")
        for (symbol, interval), close in supervisor_cursors(plan.restored, plan.warm).items():
            self._supervisor.record_close(symbol, interval, close)
        self._fence = plan.snapshot_utc

    async def run(self) -> None:
        await self._restore_before_subscribing()
        try:
            await self._supervisor.start()
        except Exception as exc:
            raise RuntimeFailClosed(f"the WebSocket start failed ({type(exc).__name__})") from exc
        consumer = asyncio.create_task(self._consume())
        if self._constraints is not None:
            every = timedelta(seconds=self._context.config.timing.exchange_info_refresh_seconds)
            self._tasks.add(
                asyncio.create_task(
                    refresh_forever(self._constraints, every=every, sleep=self._sleep)
                )
            )
        stopper: asyncio.Future[None] = asyncio.ensure_future(self._stop_waiter())
        failed: asyncio.Future[Any] = asyncio.ensure_future(self._stop.wait())
        try:
            await asyncio.wait({stopper, failed}, return_when=asyncio.FIRST_COMPLETED)
            if stopper.done() and not stopper.cancelled() and stopper.exception() is not None:
                self._fail(stopper.exception() or RuntimeFailClosed("the stop waiter failed"))
        finally:
            await self._shutdown(consumer, stopper, failed)
        failure = self._failure
        if failure is None:
            return
        if isinstance(failure, (RuntimeFailClosed, PersistenceError, RuntimeRecordConflict)):
            raise failure
        raise RuntimeFailClosed(f"the loop failed ({type(failure).__name__})") from failure

    async def _shutdown(self, consumer: asyncio.Task[None], *waiters: asyncio.Future[Any]) -> None:
        """Unsubscribe and close first, let a running batch finish, then cancel the rest."""
        await self._supervisor.stop()
        await self._idle.wait()
        pending: list[asyncio.Future[Any]] = [consumer, *waiters, *self._tasks]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.gather(*self._record_tasks, return_exceptions=True)


def _resolve_public(wiring: LoopWiring) -> Any:
    """The public adapter of the wiring, or the credential-free production one."""
    if wiring.public is not None:
        return wiring.public
    from src.adapters.binance_public import BinancePublicMarketData

    return BinancePublicMarketData()


async def run_admitted(context: RuntimeContext, wiring: LoopWiring | None = None) -> None:
    """Run the live paper loop for an admitted, started process until it is told to stop.

    Returns after a requested stop (the caller then records RUNTIME_STOP). Raises
    `RuntimeFailClosed` (or the persistence errors `main` maps to the same exit code) after the
    adapter has been unsubscribed and closed, when the loop stopped itself.
    """
    from src.adapters.paper_ws import PaperWsAdapter

    live = wiring if wiring is not None else LoopWiring()
    config = context.config
    epoch = context.epoch
    loop = asyncio.get_running_loop()
    public = _resolve_public(live)

    pipeline = live.pipeline
    constraints: ConstraintProvider | None = None
    if pipeline is None:
        parameter_set = load_parameter_set_at_root(
            epoch.strategy_id, epoch.parameter_set_id, resolve_registry_root(context.registry_root)
        )
        factory = live.context_factory
        if factory is None:
            if live.risk_inputs is None:
                raise RuntimeFailClosed("the risk inputs port is not bound")
            constraints = ConstraintProvider(
                public=public, symbols=config.symbols, clock=context.clock
            )
            try:
                await constraints.refresh()
            except Exception as exc:
                raise RuntimeFailClosed(
                    f"the first exchangeInfo refresh failed ({type(exc).__name__})"
                ) from exc
            factory = make_context_factory(
                parameter_set=parameter_set,
                constraints=constraints,
                risk_inputs=live.risk_inputs,
                account=config.account,
                ttl_seconds=config.timing.constraint_snapshot_ttl_seconds,
            )
        pipeline = BarPipeline(
            epoch=epoch,
            parameter_set=parameter_set,
            context_factory=factory,
            buffers=BarBuffers(),
            state=context.state,
            sibling_4h_wait_seconds=config.timing.sibling_4h_wait_seconds,
            fetch_4h_bar=make_sibling_fetcher(public, loop),
        )

    def build_supervisor(owner: _LiveLoop) -> PaperSupervisor:
        adapter = PaperWsAdapter(ws_client=live.ws_client, client_factory=live.ws_client_factory)
        sinks = owner.sinks()
        return PaperSupervisor(
            ws_adapter=adapter,
            rest_adapter=public,
            symbols=config.symbols,
            intervals=LOOP_INTERVALS,
            on_closed_bar=sinks["on_closed_bar"],
            on_backfill=sinks["on_backfill"],
            on_gap=sinks["on_gap"],
            on_connection_event=sinks["on_connection_event"],
            clock=context.clock,
        )

    snapshot = context.clock()
    started = context.started_at_utc if context.started_at_utc is not None else snapshot
    try:
        restored = await asyncio.to_thread(
            restore_runtime, context.state, epoch.epoch_id, current_start_utc=started
        )
        warm = await warm_up(public, config.symbols, LOOP_INTERVALS, snapshot)
    except (PersistenceError, RuntimeRecordConflict):
        raise
    except Exception as exc:
        raise RuntimeFailClosed(
            f"the restart restore or the REST warm-up failed ({type(exc).__name__})"
        ) from exc
    plan = RestartPlan(
        started_at_utc=started,
        snapshot_utc=snapshot,
        restored=restored,
        warm=warm,
        gaps=downtime_gaps(
            restored, now_utc=snapshot, symbols=config.symbols, intervals=LOOP_INTERVALS
        ),
    )

    await _LiveLoop(
        context=context,
        wiring=live,
        pipeline=pipeline,
        supervisor_factory=build_supervisor,
        restart=plan,
        constraints=constraints,
    ).run()


def _healthcheck(
    *,
    env: Mapping[str, str],
    pinned_path: Path,
    state: RuntimeStatePort | None,
    registry_root: Path | None,
    now: Callable[[], datetime],
) -> int:
    """The container probe: 0 only for a running process that keeps processing closed bars.

    Liveness is not health (research P5): a process that is up but processes nothing, a held
    refusal (`--hold-on-refusal` keeps the container up after a refusal) and a stopped process all
    report unhealthy. The start gate's own refusal checks run first, so the probe exits 1 wherever
    the start would be refused. Only the NAMES of offending variables are ever printed.
    """

    def unhealthy(reason: str) -> int:
        print(f"unhealthy: {reason}")
        return 1

    trade_names = refuse_trade_capable_env(env)
    if trade_names:
        return unhealthy("trade-capable variable present: " + ", ".join(trade_names))
    if not allowlist_entries():
        return unhealthy("the allowlist admits nothing: no paper process runs")
    values = read_env(env)
    absent = [
        name for name in ("PAPER_STRATEGY_ID", "PAPER_PARAMETER_SET_ID") if not values.get(name)
    ]
    if absent:
        return unhealthy("runtime configuration not ratified: " + ", ".join(absent))
    entry, why_not = _admit(
        values["PAPER_STRATEGY_ID"], values["PAPER_PARAMETER_SET_ID"], registry_root
    )
    if entry is None:
        return unhealthy(why_not or "not admitted")
    try:
        config = load_runtime_config(values.get("PAPER_RUNTIME_CONFIG"))
    except ConfigNotRatified as exc:
        return unhealthy(str(exc))
    if not pinned_path.is_file():
        return unhealthy("no pinned epoch")
    try:
        epoch = load_pinned_state(pinned_path)
    except (OSError, ValueError, KeyError, TypeError):
        return unhealthy("the pinned state is unreadable")
    if epoch.parameter_set_hash != entry.parameter_set_hash:
        return unhealthy("the pinned state does not match the admitted allowlist entry")
    try:
        port = state if state is not None else _state_from_env(values)
        marker = port.latest_runtime_marker(epoch.epoch_id)
        closes = port.last_close_by_pair(epoch.epoch_id)
    except ConfigNotRatified as exc:
        return unhealthy(str(exc))
    except Exception as exc:  # the probe must answer, never crash, on a store problem
        return unhealthy(f"the runtime state is unreadable ({type(exc).__name__})")

    if marker is None or marker.event_type is not RuntimeEventType.RUNTIME_START:
        return unhealthy("no running process is recorded")
    max_age = timedelta(seconds=config.timing.healthcheck_max_bar_age_seconds)
    at = now()
    started = marker.occurred_at_utc
    last_bar = max(closes.values(), default=None)
    if last_bar is not None and last_bar >= started:
        if at - last_bar <= max_age:
            print("healthy")
            return 0
        return unhealthy("the last processed closed bar is older than the maximum age")
    if at - started <= max_age:
        print("healthy: waiting for the first closed bar since the start")
        return 0
    return unhealthy("no closed bar was processed within the maximum age after the start")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    wait_for_stop: Callable[[], None] | None = None,
    state: RuntimeStatePort | None = None,
    registry_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    run_loop: Callable[[RuntimeContext], None] | None = None,
    wiring: LoopWiring | None = None,
) -> int:
    """Run the paper process: start gate, admission, epoch, run; returns the exit status.

    The keyword parameters are test and composition seams; production passes none of them.
    """
    args = build_parser().parse_args(argv)
    env: Mapping[str, str] = os.environ if environ is None else environ
    configure_logging(env)
    stopper = wait_for_stop if wait_for_stop is not None else wait_for_stop_signal
    now = clock if clock is not None else _utc_now
    hold: bool = args.hold_on_refusal

    if args.healthcheck:
        return _healthcheck(
            env=env,
            pinned_path=args.pinned_state,
            state=state,
            registry_root=registry_root,
            now=now,
        )

    def refuse(code: ExitCode, reason: str) -> int:
        return _refuse(code, reason, hold=hold, wait_for_stop=stopper)

    trade_names = refuse_trade_capable_env(env)
    if trade_names:
        return refuse(
            ExitCode.TRADE_KEY_REFUSED,
            "trade-capable variable present: " + ", ".join(trade_names),
        )

    if not allowlist_entries():
        structlog.get_logger().info(SKIPPED_EVENT)
        return int(ExitCode.OK)

    values = read_env(env)
    absent = [
        name for name in ("PAPER_STRATEGY_ID", "PAPER_PARAMETER_SET_ID") if not values.get(name)
    ]
    if absent:
        return refuse(
            ExitCode.CONFIG_NOT_RATIFIED,
            "runtime configuration not ratified: " + ", ".join(absent),
        )
    strategy_id = values["PAPER_STRATEGY_ID"]
    parameter_set_id = values["PAPER_PARAMETER_SET_ID"]

    entry, why_not = _admit(strategy_id, parameter_set_id, registry_root)
    if entry is None:
        return refuse(ExitCode.ADMISSION_OR_EPOCH_MISMATCH, why_not or "not admitted")

    try:
        config = load_runtime_config(values.get("PAPER_RUNTIME_CONFIG"))
        port = state if state is not None else _state_from_env(values)
    except ConfigNotRatified as exc:
        return refuse(ExitCode.CONFIG_NOT_RATIFIED, str(exc))

    live_wiring: LoopWiring | None = None
    if run_loop is None:
        live_wiring = wiring if wiring is not None else LoopWiring()
        if (
            live_wiring.pipeline is None
            and live_wiring.context_factory is None
            and live_wiring.risk_inputs is None
        ):
            return refuse(
                ExitCode.CONFIG_NOT_RATIFIED,
                "the risk inputs port is not bound: open positions and the daily loss have no "
                "default implementation in src (plan 16-31 binds them to the SHADOW ledger)",
            )

    pinned_path: Path = args.pinned_state
    if args.pin_epoch:
        if pinned_path.exists():
            return refuse(
                ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
                "a pinned state exists: a new pin restarts the qualifying trial (REV-18), "
                "so the operator archives the old state first",
            )
        try:
            epoch = pin_stream_epoch(
                strategy_id=strategy_id,
                parameter_set_id=parameter_set_id,
                opened_at_utc=now(),
                registry_root=registry_root,
            )
        except Exception as exc:  # the per-call validation refuses in many typed ways
            return refuse(
                ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
                f"pin_stream_epoch refused ({type(exc).__name__}): {exc}",
            )
        if epoch.parameter_set_hash != entry.parameter_set_hash:
            return refuse(
                ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
                "the pinned set's hash changed between admission and the pin",
            )
        newly_pinned = True
    else:
        if not pinned_path.is_file():
            return refuse(
                ExitCode.NO_PINNED_EPOCH,
                "no pinned epoch: pinning is an operator command (O-11 iii)",
            )
        try:
            epoch = load_pinned_state(pinned_path)
        except (OSError, ValueError, KeyError, TypeError):
            return refuse(ExitCode.ADMISSION_OR_EPOCH_MISMATCH, "the pinned state is unreadable")
        if (
            epoch.strategy_id != strategy_id
            or epoch.parameter_set_id != parameter_set_id
            or epoch.parameter_set_hash != entry.parameter_set_hash
        ):
            return refuse(
                ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
                "the pinned state does not match the admitted allowlist entry",
            )
        newly_pinned = False

    context = RuntimeContext(
        epoch=epoch,
        config=config,
        state=port,
        env=values,
        clock=now,
        registry_root=registry_root,
    )
    try:
        if newly_pinned:
            # Recorded before the file is written: a failed write leaves an orphan record of an
            # epoch no run uses, while the reverse order would leave a trial with no pin record.
            port.record(_epoch_record(RuntimeEventType.EPOCH_PINNED, epoch, epoch.opened_at_utc))
            write_pinned_state(epoch, pinned_path)
        start_extra: dict[str, Any] = {}
        if run_loop is None and live_wiring is not None:
            public = _resolve_public(live_wiring)
            live_wiring = replace(live_wiring, public=public)
            try:
                skew_ms = asyncio.run(measure_clock_skew(public, now))
            except Exception as exc:
                raise RuntimeFailClosed(
                    f"the clock-skew check against Binance server time failed "
                    f"({type(exc).__name__})"
                ) from exc
            start_extra["clock_skew_ms"] = skew_ms
            structlog.get_logger().info("clock skew measured", clock_skew_ms=skew_ms)
        started_at = now()
        context = replace(context, started_at_utc=started_at)
        port.record(_epoch_record(RuntimeEventType.RUNTIME_START, epoch, started_at, start_extra))
        structlog.get_logger().info("runtime start", epoch_id=epoch.epoch_id)
        if run_loop is not None:
            run_loop(context)
        else:
            asyncio.run(run_admitted(context, live_wiring))
        port.record(_epoch_record(RuntimeEventType.RUNTIME_STOP, epoch, now()))
    except (PersistenceError, RuntimeRecordConflict, RuntimeFailClosed) as exc:
        detail = str(exc) if isinstance(exc, RuntimeFailClosed) else type(exc).__name__
        print(
            f"paper runtime failed closed (exit {int(ExitCode.FAIL_CLOSED_RUNTIME)}): {detail}",
            file=sys.stderr,
        )
        return int(ExitCode.FAIL_CLOSED_RUNTIME)
    return int(ExitCode.OK)


if __name__ == "__main__":
    raise SystemExit(main())
