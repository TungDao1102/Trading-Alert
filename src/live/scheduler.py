"""The one scheduler primitive every periodic live task runs on, and the cadences it runs at.

Plan 24-10; D-11 (one primitive, injected clock and sleep, no jitter), D-12 (every interval comes
from a loaded limit and an unset one refuses by name), D087 (the day-risk backfill stays under the
daily-loss age).

``Scheduler`` runs one asyncio task per ``TaskSpec``. A task loop is: run the task, record the
outcome, wait for the earlier of the injected sleep (the fixed interval, measured from the end of
the run) and the optional wake event, repeat. Nothing here reads a clock or calls ``asyncio.sleep``:
the clock and the sleep are injected, so tests drive it in virtual time and
``tests/test_live_ast_guards.py`` can forbid a wall-clock call in this module.

Failure isolation (T-24-24): an exception of a task is recorded and surfaced, never raised out of
its loop, and never touches the other tasks. It is recorded by exception class name only
(T-24-26): the message of an exception can carry a path or a value. ``CancelledError`` is not an
``Exception``; it propagates, so shutdown works and a cancelled task is not counted as a failure.

Journal: every outcome change of a task is passed to the injected async ``record`` function (the
StoreExecutor path in the composition root): the first run (ok or failed), a failure after an ok
run or with a different exception class, and the first success after a failure. A repeated failure
of the same class is not journaled again. A ``record`` that raises is logged by class name and the
loop goes on. The per-task ``TaskResult`` (last started, last ok, last error class, consecutive
failures) is kept in memory for the liveness stamp and the health probes.

Stall watchdog: a ``TaskSpec`` may carry ``stall_after_seconds``. While one run of that task is
still going once the bound has passed (measured with the injected sleep), the scheduler journals
ONE ``TaskEvent(kind="stall")`` for that run through the same ``record``. It observes only. The run
is never cancelled and never cut short, because a cancelled placement POST would break the rule
that a placement is never re-sent (AGENTS.md, D080); the run ends when it ends and the loop
continues as before. One event per stalled run, not one per interval. The default is None (off): a
task without a bound behaves exactly as before (same sleeps, same journal).

No number lives here as a cadence: ``LiveCadences.from_limits`` reads the loaded limits only.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from src.adapters.binance_limits import BinanceLimits
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured

_LOGGER = logging.getLogger(__name__)

# D087: the day-risk backfill must complete more often than ``account.max_daily_loss_age_ms``
# expires a known loss, or the loss turns unknown (NO_TRADE) between two runs. Running it at half
# that age leaves one full missed run of slack. This is a relationship to a ratified owner number
# (the age is 300000 ms by D087), not a cadence of its own.
DAILY_LOSS_AGE_DIVISOR = 2

TaskEventKind = Literal["first_run", "failure", "recovery", "stall"]


@dataclass(frozen=True)
class TaskSpec:
    """One named periodic task.

    ``interval`` comes from a loaded limit at build time (``LiveCadences``) and has no default.
    ``wake`` is an optional event that runs the task at once (for example the protection step
    after a fill, because a periodic-only step would add its whole period to the unprotected
    window); the scheduler clears it when it has used it. ``stall_after_seconds`` (default None,
    off) turns on the observe-only stall watchdog described in the module docstring.
    """

    name: str
    run: Callable[[], Awaitable[None]]
    interval: timedelta
    wake: asyncio.Event | None = None
    stall_after_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("TaskSpec name must not be empty")
        if self.interval <= timedelta(0):
            raise ValueError(f"TaskSpec {self.name!r} interval must be positive")
        stall = self.stall_after_seconds
        if stall is not None and not (math.isfinite(stall) and stall > 0):
            raise ValueError(f"TaskSpec {self.name!r} stall_after_seconds must be finite and > 0")


@dataclass(frozen=True)
class TaskEvent:
    """One journaled outcome change of a task (the error is a class name, never a message)."""

    task: str
    kind: TaskEventKind
    at_utc: datetime
    error_class: str | None


@dataclass(frozen=True)
class TaskResult:
    """The in-memory result of one task: the latest run instant and the latest outcome."""

    name: str
    last_started_utc: datetime | None
    last_ok_utc: datetime | None
    last_error_class: str | None
    consecutive_failures: int

    @property
    def healthy(self) -> bool:
        """False from a failed run until the next successful run (the health probe is FAIL)."""
        return self.consecutive_failures == 0


@dataclass
class _TaskState:
    started: bool = False
    last_started_utc: datetime | None = None
    last_ok_utc: datetime | None = None
    last_error_class: str | None = None
    consecutive_failures: int = 0


Record = Callable[[TaskEvent], Awaitable[None]]


class Scheduler:
    """Runs every spec on its interval until ``stop()``; see the module docstring."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]],
        record: Record,
        specs: Iterable[TaskSpec],
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._record = record
        self._specs = tuple(specs)
        if not self._specs:
            raise ValueError("a Scheduler needs at least one TaskSpec")
        names = [spec.name for spec in self._specs]
        if len(set(names)) != len(names):
            raise ValueError("duplicate TaskSpec name")
        self._state = {spec.name: _TaskState() for spec in self._specs}
        self._stop_event = asyncio.Event()
        self._running = False

    # ---- public ------------------------------------------------------------------------- #

    async def run(self) -> None:
        """Run every task loop until ``stop()``; cancelling this call cancels every loop."""
        if self._running:
            raise RuntimeError("Scheduler is already running")
        self._running = True
        loops = [asyncio.create_task(self._loop(spec)) for spec in self._specs]
        try:
            await asyncio.gather(*loops)
        finally:
            for loop_task in loops:
                loop_task.cancel()
            await asyncio.gather(*loops, return_exceptions=True)
            self._running = False

    def stop(self) -> None:
        """End every loop after its current run; ``run()`` then returns."""
        self._stop_event.set()

    def results(self) -> Mapping[str, TaskResult]:
        """A snapshot of every task's result, keyed by task name."""
        return {
            name: TaskResult(
                name=name,
                last_started_utc=state.last_started_utc,
                last_ok_utc=state.last_ok_utc,
                last_error_class=state.last_error_class,
                consecutive_failures=state.consecutive_failures,
            )
            for name, state in self._state.items()
        }

    # ---- one task loop ------------------------------------------------------------------ #

    async def _loop(self, spec: TaskSpec) -> None:
        while not self._stop_event.is_set():
            started = self._clock()
            error_class: str | None = None
            watchdog: asyncio.Task[None] | None = None
            if spec.stall_after_seconds is not None:
                watchdog = asyncio.ensure_future(self._watch_stall(spec, spec.stall_after_seconds))
            try:
                await spec.run()
            except Exception as exc:  # a task never takes the loop or the others down
                error_class = type(exc).__name__  # class name only: a message may hold a value
            finally:
                if watchdog is not None:
                    watchdog.cancel()
                    await asyncio.gather(watchdog, return_exceptions=True)
            await self._note(spec.name, started, error_class)
            await self._wait(spec)

    async def _watch_stall(self, spec: TaskSpec, bound_seconds: float) -> None:
        """Observe only: after the bound, journal one stall event for the run still going.

        This coroutine never touches the run (no cancel, no cut-off). The loop cancels it when the
        run ends; the journal write is shielded so a run that ends during the write does not lose
        the row.
        """
        await self._sleep(bound_seconds)
        _LOGGER.error(
            "scheduler task %s is still running after %s seconds", spec.name, bound_seconds
        )
        await asyncio.shield(self._record_stall(spec.name))

    async def _record_stall(self, name: str) -> None:
        try:
            await self._record(
                TaskEvent(task=name, kind="stall", at_utc=self._clock(), error_class=None)
            )
        except Exception as exc:  # the journal must not stop the task loop
            _LOGGER.warning("scheduler journal write failed for %s: %s", name, type(exc).__name__)

    async def _note(self, name: str, started: datetime, error_class: str | None) -> None:
        state = self._state[name]
        first = not state.started
        previous_error = state.last_error_class
        state.started = True
        state.last_started_utc = started
        state.last_error_class = error_class
        kind: TaskEventKind | None = None
        if error_class is None:
            state.last_ok_utc = started
            state.consecutive_failures = 0
            if first:
                kind = "first_run"
            elif previous_error is not None:
                kind = "recovery"
        else:
            state.consecutive_failures += 1
            if first:
                kind = "first_run"
            elif previous_error != error_class:
                kind = "failure"
        if kind is None:
            return
        try:
            await self._record(
                TaskEvent(task=name, kind=kind, at_utc=started, error_class=error_class)
            )
        except Exception as exc:  # the journal must not stop the task loop
            _LOGGER.warning("scheduler journal write failed for %s: %s", name, type(exc).__name__)

    async def _wait(self, spec: TaskSpec) -> None:
        """Return at the earlier of the interval, the wake event and stop."""
        waiters: list[asyncio.Task[object]] = [
            asyncio.ensure_future(self._sleep(spec.interval.total_seconds())),
            asyncio.ensure_future(self._stop_event.wait()),
        ]
        if spec.wake is not None:
            waiters.append(asyncio.ensure_future(spec.wake.wait()))
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
        if spec.wake is not None:
            spec.wake.clear()


# --------------------------------------------------------------------------- #
# Cadences (D-12).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class LiveCadences:
    """The interval of every periodic live task, derived from loaded limits only.

    The protection step, the reconcile tick, the confirm-TTL sweep, the alert drain, the health
    checks, the liveness stamp and the scheduled-cancel check all run at
    ``reconcile.tick_interval_ms``; the protection step additionally wakes on a fill. The drift
    re-measure runs at the ratified ``drift.periodic_remeasure_interval_seconds``. The day-risk
    backfill runs at ``account.max_daily_loss_age_ms`` divided by ``DAILY_LOSS_AGE_DIVISOR``
    (D087). The lot-filter refresh runs at ``reconcile.lot_filter_refresh_interval_ms``.
    ``protection_stall_after`` is the alert-only bound of one protection run
    (``scheduler.protection_stall_after_ms``, D111): None while the key is NOT_CONFIGURED, which
    keeps the stall watchdog off. It is the only cadence field with a default, and the default is
    not a number.
    """

    protection_step: timedelta
    reconcile_tick: timedelta
    confirm_ttl_sweep: timedelta
    alert_drain: timedelta
    health: timedelta
    liveness_stamp: timedelta
    scheduled_cancel_check: timedelta
    drift_remeasure: timedelta
    day_risk_backfill: timedelta
    lot_filter_refresh: timedelta
    protection_stall_after: timedelta | None = None

    @property
    def protection_stall_after_seconds(self) -> float | None:
        """The stall bound in seconds for ``TaskSpec.stall_after_seconds``; None = watchdog off."""
        bound = self.protection_stall_after
        return None if bound is None else bound.total_seconds()

    @classmethod
    def from_limits(
        cls,
        execution_limits: ExecutionLimits,
        binance_limits: BinanceLimits,
        *,
        daily_loss_age_divisor: int = DAILY_LOSS_AGE_DIVISOR,
    ) -> LiveCadences:
        """Derive every cadence from the loaded limits.

        Raises:
            ExecutionLimitsNotConfigured: naming every key it needs that is unset (never a value).
            ValueError: ``daily_loss_age_divisor`` is below 2, so the backfill would not run
                strictly more often than the daily-loss age expires.
        """
        if daily_loss_age_divisor < DAILY_LOSS_AGE_DIVISOR:
            raise ValueError("daily_loss_age_divisor must be at least 2 (D087)")
        tick_ms = execution_limits.reconcile_tick_interval_ms
        lot_ms = execution_limits.reconcile_lot_filter_refresh_interval_ms
        loss_age_ms = execution_limits.account_max_daily_loss_age_ms
        drift_seconds = binance_limits.drift.periodic_remeasure_interval_seconds
        unset = tuple(
            key
            for key, value in (
                ("reconcile.tick_interval_ms", tick_ms),
                ("reconcile.lot_filter_refresh_interval_ms", lot_ms),
                ("account.max_daily_loss_age_ms", loss_age_ms),
                ("drift.periodic_remeasure_interval_seconds", drift_seconds),
            )
            if value is None
        )
        if (
            unset
            or tick_ms is None
            or lot_ms is None
            or loss_age_ms is None
            or drift_seconds is None
        ):
            raise ExecutionLimitsNotConfigured(unset)
        tick = timedelta(milliseconds=tick_ms)
        return cls(
            protection_step=tick,
            reconcile_tick=tick,
            confirm_ttl_sweep=tick,
            alert_drain=tick,
            health=tick,
            liveness_stamp=tick,
            scheduled_cancel_check=tick,
            drift_remeasure=timedelta(seconds=drift_seconds),
            day_risk_backfill=timedelta(milliseconds=loss_age_ms) / daily_loss_age_divisor,
            lot_filter_refresh=timedelta(milliseconds=lot_ms),
            # Alert-only: an unset key is not refused, it leaves the watchdog off.
            protection_stall_after=execution_limits.scheduler_protection_stall_after,
        )


__all__ = [
    "DAILY_LOSS_AGE_DIVISOR",
    "LiveCadences",
    "Record",
    "Scheduler",
    "TaskEvent",
    "TaskEventKind",
    "TaskResult",
    "TaskSpec",
]
