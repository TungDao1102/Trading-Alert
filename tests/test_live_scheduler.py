"""The live scheduler primitive and the cadence derivation (plan 24-10; D-11, D-12, D087).

Every test runs in virtual time (`tests/support/virtual_time.py`): the injected sleep never
really sleeps and a real `asyncio.sleep` fails the test. The cadences are TEST_ONLY numbers
(`tests/support/execution_limits.py`), not the owner's.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import fields
from datetime import timedelta
from typing import Any

import pytest
from src.execution.execution_limits import (
    EXECUTION_LIMIT_FIELDS,
    ExecutionLimitsNotConfigured,
)
from src.live.scheduler import (
    DAILY_LOSS_AGE_DIVISOR,
    LiveCadences,
    Scheduler,
    TaskDurationSummary,
    TaskEvent,
    TaskResult,
    TaskSpec,
)

from tests.support import execution_limits as limits_support
from tests.support.execution_limits import TEST_ONLY_EXECUTION_LIMIT_VALUES
from tests.support.limits import test_only_binance_limits
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START, VirtualTime


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    calls: list[float] = []

    async def _forbidden(delay: float, result: Any = None) -> Any:
        calls.append(delay)
        raise AssertionError("asyncio.sleep called: the scheduler must use the injected sleep")

    monkeypatch.setattr(asyncio, "sleep", _forbidden)
    return calls


class Journal:
    """An injected async journal writer that keeps what it was given."""

    def __init__(self) -> None:
        self.events: list[TaskEvent] = []

    async def __call__(self, event: TaskEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[tuple[str, str]]:
        return [(event.task, event.kind) for event in self.events]


def _scheduler(
    time: VirtualTime,
    specs: list[TaskSpec],
    record: Callable[[TaskEvent], Awaitable[None]],
) -> Scheduler:
    return Scheduler(clock=time.now, sleep=time.sleep, record=record, specs=specs)


async def _counter_run(counts: dict[str, int], name: str) -> None:
    counts[name] += 1


# --------------------------------------------------------------------------- #
# Task 1: cadence, failure isolation, wake, stop, journal.
# --------------------------------------------------------------------------- #


async def test_two_tasks_run_on_their_own_cadence_in_virtual_time(
    real_sleep_calls: list[float],
) -> None:
    time = VirtualTime()
    counts = {"a": 0, "b": 0}

    async def run_a() -> None:
        await _counter_run(counts, "a")

    async def run_b() -> None:
        await _counter_run(counts, "b")

    journal = Journal()
    scheduler = _scheduler(
        time,
        [
            TaskSpec("a", run_a, timedelta(seconds=15)),
            TaskSpec("b", run_b, timedelta(seconds=60)),
        ],
        journal,
    )
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(120)
    scheduler.stop()
    await time.advance(0)
    await asyncio.wait_for(runner, timeout=None)

    # t=0, 15, ..., 120 is 9 runs of A; t=0, 60, 120 is 3 of B.
    assert counts == {"a": 9, "b": 3}
    assert real_sleep_calls == []
    assert sorted(set(time.sleeps)) == [15.0, 60.0]
    assert journal.kinds() == [("a", "first_run"), ("b", "first_run")]


async def test_a_failing_task_does_not_stop_the_other_and_recovers() -> None:
    time = VirtualTime()
    counts = {"a": 0, "b": 0}

    async def run_a() -> None:
        counts["a"] += 1
        if counts["a"] == 2:
            raise RuntimeError("secret detail that must not be journaled")

    async def run_b() -> None:
        counts["b"] += 1

    journal = Journal()
    scheduler = _scheduler(
        time,
        [
            TaskSpec("a", run_a, timedelta(seconds=15)),
            TaskSpec("b", run_b, timedelta(seconds=60)),
        ],
        journal,
    )
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    assert scheduler.results()["a"].consecutive_failures == 0

    await time.advance(15)  # A's second run raises
    failed = scheduler.results()["a"]
    assert failed.last_error_class == "RuntimeError"
    assert failed.consecutive_failures == 1
    assert failed.healthy is False

    await time.advance(15)  # A's third run succeeds
    recovered = scheduler.results()["a"]
    assert recovered.last_error_class is None
    assert recovered.consecutive_failures == 0
    assert recovered.healthy is True
    assert recovered.last_ok_utc == time.now()

    await time.advance(45)  # B ran again at t=60 despite A's failure
    assert counts["b"] == 2
    scheduler.stop()
    await time.advance(0)
    await runner

    assert journal.kinds() == [
        ("a", "first_run"),
        ("b", "first_run"),
        ("a", "failure"),
        ("a", "recovery"),
    ]
    failure = journal.events[2]
    assert failure.error_class == "RuntimeError"
    assert "secret" not in repr(journal.events)


async def test_a_repeated_failure_of_the_same_class_is_journaled_once() -> None:
    time = VirtualTime()

    async def always_fails() -> None:
        raise ValueError("x")

    journal = Journal()
    scheduler = _scheduler(time, [TaskSpec("a", always_fails, timedelta(seconds=10))], journal)
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(35)
    result = scheduler.results()["a"]
    assert result.consecutive_failures == 4
    assert result.last_ok_utc is None
    scheduler.stop()
    await time.advance(0)
    await runner
    # The first run failed: one first_run event carrying the class, then nothing more.
    assert journal.kinds() == [("a", "first_run")]
    assert journal.events[0].error_class == "ValueError"


async def test_a_changed_failure_class_is_a_new_outcome() -> None:
    time = VirtualTime()
    runs = 0

    async def run() -> None:
        nonlocal runs
        runs += 1
        raise ValueError("x") if runs < 3 else KeyError("y")

    journal = Journal()
    scheduler = _scheduler(time, [TaskSpec("a", run, timedelta(seconds=10))], journal)
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(25)
    scheduler.stop()
    await time.advance(0)
    await runner
    assert [(e.kind, e.error_class) for e in journal.events] == [
        ("first_run", "ValueError"),
        ("failure", "KeyError"),
    ]


async def test_a_wake_event_runs_the_task_at_once_and_restarts_the_period() -> None:
    time = VirtualTime()
    wake = asyncio.Event()
    run_times: list[float] = []
    start = time.now()

    async def run_a() -> None:
        run_times.append((time.now() - start).total_seconds())

    scheduler = _scheduler(
        time, [TaskSpec("a", run_a, timedelta(seconds=15), wake=wake)], Journal()
    )
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(5)
    wake.set()
    await time.settle()
    assert run_times == [0.0, 5.0]
    assert wake.is_set() is False  # cleared after use
    await time.advance(14)  # t=19: the next periodic run is 15 s after the woken run (t=20)
    assert run_times == [0.0, 5.0]
    await time.advance(1)  # t=20
    assert run_times == [0.0, 5.0, 20.0]
    scheduler.stop()
    await time.advance(0)
    await runner


async def test_a_wake_set_during_a_run_triggers_another_run_without_waiting() -> None:
    time = VirtualTime()
    wake = asyncio.Event()
    count = 0

    async def run_a() -> None:
        nonlocal count
        count += 1
        if count == 1:
            wake.set()  # a fill arrives while the step is running

    scheduler = _scheduler(
        time, [TaskSpec("a", run_a, timedelta(seconds=15), wake=wake)], Journal()
    )
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    assert count == 2
    scheduler.stop()
    await time.advance(0)
    await runner


async def test_stop_ends_every_loop_and_run_returns() -> None:
    time = VirtualTime()
    wake = asyncio.Event()

    async def noop() -> None:
        return None

    scheduler = _scheduler(
        time,
        [
            TaskSpec("a", noop, timedelta(seconds=15), wake=wake),
            TaskSpec("b", noop, timedelta(seconds=60)),
        ],
        Journal(),
    )
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    assert runner.done() is False
    scheduler.stop()
    await time.settle()
    assert runner.done() is True
    await runner
    assert time.pending_sleepers() == 0


# --------------------------------------------------------------------------- #
# The observe-only stall watchdog (quick 261114-kxu): journal once per stalled run, never cancel.
# --------------------------------------------------------------------------- #


def _stall_spec(
    run: Callable[[], Awaitable[None]], *, stall: float | None = 30, interval: float = 15
) -> TaskSpec:
    return TaskSpec("a", run, timedelta(seconds=interval), stall_after_seconds=stall)


def _other_pending_tasks() -> list[asyncio.Task[Any]]:
    current = asyncio.current_task()
    return [t for t in asyncio.all_tasks() if t is not current and not t.done()]


async def test_a_stalled_run_is_journaled_once_and_never_cancelled() -> None:
    time = VirtualTime()
    release = asyncio.Event()
    cancelled: list[bool] = []

    async def run_a() -> None:
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    journal = Journal()
    scheduler = _scheduler(time, [_stall_spec(run_a)], journal)
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(31)

    assert journal.kinds() == [("a", "stall")]
    assert journal.events[0].at_utc == TEST_ONLY_VIRTUAL_START + timedelta(seconds=30)
    assert journal.events[0].error_class is None

    await time.advance(120)
    assert journal.kinds() == [("a", "stall")], "one event per stalled run, not one per interval"

    release.set()
    await time.settle()
    assert journal.kinds() == [("a", "stall"), ("a", "first_run")]
    assert cancelled == [], "the run was never cancelled"
    scheduler.stop()
    await time.advance(15)
    await runner
    assert _other_pending_tasks() == []


async def test_the_next_stalled_run_is_journaled_again() -> None:
    time = VirtualTime()
    gates = [asyncio.Event(), asyncio.Event()]
    started = {"n": 0}

    async def run_a() -> None:
        gate = gates[min(started["n"], 1)]
        started["n"] += 1
        await gate.wait()

    journal = Journal()
    scheduler = _scheduler(time, [_stall_spec(run_a)], journal)
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(31)
    gates[0].set()
    await time.settle()
    await time.advance(15 + 31)  # the next run starts after the interval and stalls again

    assert journal.kinds() == [("a", "stall"), ("a", "first_run"), ("a", "stall")]
    gates[1].set()
    scheduler.stop()
    await time.advance(15)
    await runner
    assert _other_pending_tasks() == []


async def test_a_run_that_ends_before_the_bound_leaves_no_event_and_no_watchdog() -> None:
    time = VirtualTime()
    counts = {"a": 0}

    async def run_a() -> None:
        counts["a"] += 1

    journal = Journal()
    scheduler = _scheduler(time, [_stall_spec(run_a)], journal)
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(100)
    scheduler.stop()
    await time.advance(15)
    await runner

    assert counts["a"] >= 6
    assert journal.kinds() == [("a", "first_run")]
    assert time.pending_sleepers() == 0
    assert _other_pending_tasks() == []


async def test_cancelling_the_scheduler_cancels_a_stalled_run_as_before_and_the_watchdog() -> None:
    time = VirtualTime()
    never = asyncio.Event()
    cancelled: list[bool] = []

    async def run_a() -> None:
        try:
            await never.wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    scheduler = _scheduler(time, [_stall_spec(run_a)], Journal())
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(10)  # stalled-to-be: the watchdog is sleeping
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner
    await time.settle()

    assert cancelled == [True]
    assert time.pending_sleepers() == 0
    assert _other_pending_tasks() == []


async def test_a_journal_that_raises_on_the_stall_event_does_not_stop_the_loop() -> None:
    time = VirtualTime()
    release = asyncio.Event()
    seen: list[str] = []

    async def record(event: TaskEvent) -> None:
        seen.append(event.kind)
        if event.kind == "stall":
            raise RuntimeError("journal down")

    async def run_a() -> None:
        await release.wait()

    scheduler = _scheduler(time, [_stall_spec(run_a)], record)
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(31)
    assert seen == ["stall"]

    release.set()
    await time.settle()
    assert seen == ["stall", "first_run"], "the loop went on"
    scheduler.stop()
    await time.advance(15)
    await runner


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_a_stall_bound_must_be_finite_and_positive(bad: float) -> None:
    async def noop() -> None:
        return None

    with pytest.raises(ValueError, match="'a'"):
        TaskSpec("a", noop, timedelta(seconds=15), stall_after_seconds=bad)


async def test_a_cancelled_error_inside_a_task_propagates_and_is_not_a_failure() -> None:
    time = VirtualTime()

    async def cancels() -> None:
        raise asyncio.CancelledError

    scheduler = _scheduler(time, [TaskSpec("a", cancels, timedelta(seconds=15))], Journal())
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert scheduler.results()["a"].last_error_class is None
    assert scheduler.results()["a"].consecutive_failures == 0


async def test_cancelling_run_cancels_the_task_loops() -> None:
    time = VirtualTime()

    async def noop() -> None:
        return None

    scheduler = _scheduler(time, [TaskSpec("a", noop, timedelta(seconds=15))], Journal())
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert time.pending_sleepers() == 0


async def test_a_journal_writer_that_raises_does_not_stop_the_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    time = VirtualTime()
    count = 0

    async def run_a() -> None:
        nonlocal count
        count += 1

    async def broken(event: TaskEvent) -> None:
        raise OSError("disk path /secret/where")

    scheduler = _scheduler(time, [TaskSpec("a", run_a, timedelta(seconds=15))], broken)
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    with caplog.at_level("WARNING"):
        await time.advance(30)
    assert count == 3
    scheduler.stop()
    await time.advance(0)
    await runner
    assert "/secret/where" not in caplog.text


async def test_results_carry_the_latest_run_instant_of_every_task() -> None:
    time = VirtualTime()
    start = time.now()

    async def noop() -> None:
        return None

    scheduler = _scheduler(
        time,
        [
            TaskSpec("a", noop, timedelta(seconds=15)),
            TaskSpec("b", noop, timedelta(seconds=60)),
        ],
        Journal(),
    )
    assert scheduler.results()["a"].last_started_utc is None
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(30)
    results = scheduler.results()
    assert results["a"].last_started_utc == start + timedelta(seconds=30)
    assert results["b"].last_started_utc == start
    assert isinstance(results["a"], TaskResult)
    scheduler.stop()
    await time.advance(0)
    await runner


async def test_spec_validation() -> None:
    async def noop() -> None:
        return None

    with pytest.raises(ValueError, match="interval"):
        TaskSpec("a", noop, timedelta(0))
    with pytest.raises(ValueError, match="interval"):
        TaskSpec("a", noop, timedelta(seconds=-1))
    with pytest.raises(ValueError, match="name"):
        TaskSpec("", noop, timedelta(seconds=1))
    time = VirtualTime()
    twice = [TaskSpec("a", noop, timedelta(seconds=1)), TaskSpec("a", noop, timedelta(seconds=2))]
    with pytest.raises(ValueError, match="duplicate"):
        _scheduler(time, twice, Journal())
    with pytest.raises(ValueError, match="at least one"):
        _scheduler(time, [], Journal())


async def test_run_twice_is_refused() -> None:
    time = VirtualTime()

    async def noop() -> None:
        return None

    scheduler = _scheduler(time, [TaskSpec("a", noop, timedelta(seconds=15))], Journal())
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    with pytest.raises(RuntimeError, match="already running"):
        await scheduler.run()
    scheduler.stop()
    await time.advance(0)
    await runner


# --------------------------------------------------------------------------- #
# Task 2: LiveCadences.from_limits.
# --------------------------------------------------------------------------- #

TICK = timedelta(milliseconds=TEST_ONLY_EXECUTION_LIMIT_VALUES["reconcile.tick_interval_ms"])


def test_every_tick_driven_cadence_equals_the_reconcile_tick() -> None:
    cadences = LiveCadences.from_limits(
        limits_support.test_only_execution_limits(), test_only_binance_limits()
    )
    assert cadences.protection_step == TICK
    assert cadences.reconcile_tick == TICK
    assert cadences.confirm_ttl_sweep == TICK
    assert cadences.alert_drain == TICK
    assert cadences.health == TICK
    assert cadences.liveness_stamp == TICK
    assert cadences.scheduled_cancel_check == TICK


def test_drift_remeasure_comes_from_the_ratified_file() -> None:
    binance = test_only_binance_limits()
    cadences = LiveCadences.from_limits(limits_support.test_only_execution_limits(), binance)
    seconds = binance.drift.periodic_remeasure_interval_seconds
    assert seconds is not None
    assert cadences.drift_remeasure == timedelta(seconds=seconds)


def test_day_risk_backfill_is_half_of_the_daily_loss_age_and_strictly_below_it() -> None:
    limits = limits_support.test_only_execution_limits()
    cadences = LiveCadences.from_limits(limits, test_only_binance_limits())
    age = timedelta(milliseconds=TEST_ONLY_EXECUTION_LIMIT_VALUES["account.max_daily_loss_age_ms"])
    assert DAILY_LOSS_AGE_DIVISOR == 2
    assert cadences.day_risk_backfill == age / 2
    assert cadences.day_risk_backfill < age


def test_lot_filter_refresh_equals_its_key() -> None:
    cadences = LiveCadences.from_limits(
        limits_support.test_only_execution_limits(), test_only_binance_limits()
    )
    expected = timedelta(
        milliseconds=TEST_ONLY_EXECUTION_LIMIT_VALUES["reconcile.lot_filter_refresh_interval_ms"]
    )
    assert cadences.lot_filter_refresh == expected


def test_an_unset_tick_refuses_naming_the_key() -> None:
    limits = limits_support.test_only_execution_limits(
        **{EXECUTION_LIMIT_FIELDS["reconcile.tick_interval_ms"]: None}
    )
    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        LiveCadences.from_limits(limits, test_only_binance_limits())
    assert caught.value.keys == ("reconcile.tick_interval_ms",)


def test_every_unset_key_is_named_together() -> None:
    limits = limits_support.test_only_execution_limits(
        **{
            EXECUTION_LIMIT_FIELDS["reconcile.tick_interval_ms"]: None,
            EXECUTION_LIMIT_FIELDS["reconcile.lot_filter_refresh_interval_ms"]: None,
            EXECUTION_LIMIT_FIELDS["account.max_daily_loss_age_ms"]: None,
        }
    )
    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        LiveCadences.from_limits(limits, test_only_binance_limits())
    assert set(caught.value.keys) == {
        "reconcile.tick_interval_ms",
        "reconcile.lot_filter_refresh_interval_ms",
        "account.max_daily_loss_age_ms",
    }


def test_an_unset_drift_interval_refuses_naming_the_key() -> None:
    binance = test_only_binance_limits()
    drift = type(binance.drift)(
        ahead_limit_ms=binance.drift.ahead_limit_ms,
        behind_limit_ms=binance.drift.behind_limit_ms,
        include_measurement_uncertainty=binance.drift.include_measurement_uncertainty,
        max_measurement_age_seconds=binance.drift.max_measurement_age_seconds,
        periodic_remeasure_interval_seconds=None,
    )
    binance = type(binance)(
        client=binance.client, signed=binance.signed, drift=drift, stream=binance.stream
    )
    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        LiveCadences.from_limits(limits_support.test_only_execution_limits(), binance)
    assert caught.value.keys == ("drift.periodic_remeasure_interval_seconds",)


def test_a_divisor_below_two_is_refused() -> None:
    for bad in (0, 1, -2):
        with pytest.raises(ValueError, match="divisor"):
            LiveCadences.from_limits(
                limits_support.test_only_execution_limits(),
                test_only_binance_limits(),
                daily_loss_age_divisor=bad,
            )


def test_every_cadence_is_a_positive_timedelta() -> None:
    cadences = LiveCadences.from_limits(
        limits_support.test_only_execution_limits(), test_only_binance_limits()
    )
    for item in fields(cadences):
        if item.name in ("protection_stall_after", "duration_summary_interval"):
            # alert-only (D111) and optional (D112): None while NOT_CONFIGURED, covered by
            # their own tests
            continue
        value = getattr(cadences, item.name)
        assert isinstance(value, timedelta)
        assert value > timedelta(0), item.name


# --------------------------------------------------------------------------- #
# Quick task 261114-mp1 (D111): the protection stall bound comes from an alert-only limit key.
# --------------------------------------------------------------------------- #


def test_an_unset_stall_bound_keeps_the_watchdog_off_and_never_refuses() -> None:
    limits = limits_support.test_only_execution_limits()
    assert limits.scheduler_protection_stall_after_ms is None
    cadences = LiveCadences.from_limits(limits, test_only_binance_limits())
    assert cadences.protection_stall_after is None
    assert cadences.protection_stall_after_seconds is None


def test_a_set_stall_bound_is_carried_as_a_timedelta_and_in_seconds() -> None:
    limits = limits_support.test_only_execution_limits(scheduler_protection_stall_after_ms=5353)
    cadences = LiveCadences.from_limits(limits, test_only_binance_limits())
    assert cadences.protection_stall_after == timedelta(milliseconds=5353)
    assert cadences.protection_stall_after_seconds == 5.353


def test_the_stall_key_is_never_named_by_the_unset_refusal() -> None:
    limits = limits_support.test_only_execution_limits(
        **{EXECUTION_LIMIT_FIELDS["reconcile.tick_interval_ms"]: None}
    )
    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        LiveCadences.from_limits(limits, test_only_binance_limits())
    assert caught.value.keys == ("reconcile.tick_interval_ms",)


# --------------------------------------------------------------------------- #
# Quick task 261115-kra (D112): the bounded per-run duration record.
# --------------------------------------------------------------------------- #


class DurationJournal:
    """An injected async duration writer that keeps what it was given."""

    def __init__(self) -> None:
        self.summaries: list[TaskDurationSummary] = []

    async def __call__(self, summary: TaskDurationSummary) -> None:
        self.summaries.append(summary)


def _timed_run(
    time: VirtualTime, durations: list[float], *, fail_at: int | None = None
) -> Callable[[], Awaitable[None]]:
    """A task whose n-th run takes durations[n] virtual seconds (the last one repeats)."""
    calls = {"n": 0}

    async def run() -> None:
        index = min(calls["n"], len(durations) - 1)
        calls["n"] += 1
        await time.sleep(durations[index])
        if fail_at is not None and calls["n"] == fail_at:
            raise ValueError("secret detail that must not be journaled")

    return run


def _duration_scheduler(
    time: VirtualTime,
    run: Callable[[], Awaitable[None]],
    *,
    record: Callable[[TaskEvent], Awaitable[None]] | None = None,
    record_duration: Callable[[TaskDurationSummary], Awaitable[None]] | None = None,
    window: timedelta | None = None,
    interval: float = 15,
) -> Scheduler:
    return Scheduler(
        clock=time.now,
        sleep=time.sleep,
        record=record or Journal(),
        specs=[TaskSpec("a", run, timedelta(seconds=interval))],
        record_duration=record_duration,
        duration_summary_interval=window,
    )


async def _run_for(scheduler: Scheduler, time: VirtualTime, seconds: float) -> None:
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(seconds)
    scheduler.stop()
    await time.advance(0)
    await asyncio.wait_for(runner, timeout=None)


async def test_the_first_run_writes_one_summary_in_whole_integer_milliseconds() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    scheduler = _duration_scheduler(time, _timed_run(time, [2.5]), record_duration=durations)
    await _run_for(scheduler, time, 3)

    assert len(durations.summaries) == 1
    summary = durations.summaries[0]
    assert summary.task == "a"
    assert (summary.runs, summary.total_ms, summary.max_ms, summary.window_max_ms) == (
        1,
        2500,
        2500,
        2500,
    )
    assert summary.new_max is True and summary.window_end is False
    assert summary.at_utc == TEST_ONLY_VIRTUAL_START + timedelta(seconds=2.5)
    for number in (summary.runs, summary.total_ms, summary.max_ms, summary.window_max_ms):
        assert type(number) is int
    assert type(summary.new_max) is bool and type(summary.window_end) is bool


async def test_the_duration_is_floored_to_whole_milliseconds() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    scheduler = _duration_scheduler(time, _timed_run(time, [2.5009]), record_duration=durations)
    await _run_for(scheduler, time, 3)
    assert [s.max_ms for s in durations.summaries] == [2500]


async def test_without_a_window_only_a_strictly_greater_run_writes_a_row() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    scheduler = _duration_scheduler(
        time, _timed_run(time, [1.0, 0.5, 1.5, 1.5]), record_duration=durations
    )
    # Runs start at 0, 16, 31.5 and 48 and end at 1, 16.5, 33 and 49.5.
    await _run_for(scheduler, time, 60)

    assert [(s.runs, s.new_max) for s in durations.summaries] == [(1, True), (3, True)]
    second = durations.summaries[1]
    assert (second.total_ms, second.max_ms, second.window_max_ms) == (3000, 1500, 1500)
    assert second.window_end is False


async def test_twenty_equal_runs_without_a_window_write_exactly_one_row() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    scheduler = _duration_scheduler(time, _timed_run(time, [1.0]), record_duration=durations)
    await _run_for(scheduler, time, 20 * 16 + 1)

    assert scheduler.results()["a"].last_ok_utc is not None
    assert len(durations.summaries) == 1
    assert durations.summaries[0].runs == 1


async def test_a_window_writes_one_row_per_window_and_restarts_the_window_maximum() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    scheduler = _duration_scheduler(
        time,
        _timed_run(time, [10.0, 1.0]),
        record_duration=durations,
        window=timedelta(seconds=60),
    )
    # Run 1 is 0..10 (the maximum). Later runs of 1 s start at 25, 41, 57, 73 (ends 26, 42, 58, 74),
    # then 89, 105, 121, 137 (ends 90, 106, 122, 138).
    await _run_for(scheduler, time, 140)

    rows = [(s.runs, s.new_max, s.window_end, s.window_max_ms) for s in durations.summaries]
    assert rows == [(1, True, False, 10000), (5, False, True, 10000), (9, False, True, 1000)]
    first_window, second_window = durations.summaries[1], durations.summaries[2]
    assert first_window.at_utc == TEST_ONLY_VIRTUAL_START + timedelta(seconds=74)
    assert second_window.at_utc == TEST_ONLY_VIRTUAL_START + timedelta(seconds=138)
    assert second_window.window_max_ms < second_window.max_ms
    assert (second_window.max_ms, second_window.total_ms) == (10000, 18000)


async def test_a_run_that_closes_the_window_and_sets_a_maximum_writes_one_row_with_both() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    scheduler = _duration_scheduler(
        time,
        _timed_run(time, [1.0, 1.0, 1.0, 1.0, 3.0]),
        record_duration=durations,
        window=timedelta(seconds=60),
    )
    # Runs start at 0, 16, 32, 48 (1 s each) and 64 (3 s, ends 67): 67 - 0 >= 60 and 3000 > 1000.
    await _run_for(scheduler, time, 70)

    rows = [(s.runs, s.new_max, s.window_end) for s in durations.summaries]
    assert rows == [(1, True, False), (5, True, True)]
    assert durations.summaries[1].window_max_ms == 3000


async def test_a_task_whose_only_run_never_ends_writes_no_summary() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    release = asyncio.Event()

    async def never_ends() -> None:
        await release.wait()

    scheduler = _duration_scheduler(time, never_ends, record_duration=durations)
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(120)
    assert durations.summaries == []
    release.set()
    await time.settle()
    scheduler.stop()
    await time.advance(0)
    await asyncio.wait_for(runner, timeout=None)
    assert len(durations.summaries) == 1


async def test_a_scheduler_built_without_the_writer_calls_nothing_new() -> None:
    time = VirtualTime()
    journal = Journal()
    scheduler = _duration_scheduler(
        time, _timed_run(time, [1.0]), record=journal, window=timedelta(seconds=30)
    )
    await _run_for(scheduler, time, 40)
    assert journal.kinds() == [("a", "first_run")]
    assert scheduler.results()["a"].healthy


async def test_a_failed_run_is_timed() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    journal = Journal()
    scheduler = _duration_scheduler(
        time,
        _timed_run(time, [1.0], fail_at=1),
        record=journal,
        record_duration=durations,
    )
    await _run_for(scheduler, time, 5)

    assert journal.kinds() == [("a", "first_run")]
    assert journal.events[0].error_class == "ValueError"
    assert len(durations.summaries) == 1
    assert (durations.summaries[0].runs, durations.summaries[0].max_ms) == (1, 1000)


async def test_a_run_cancelled_with_the_scheduler_writes_no_summary() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    scheduler = _duration_scheduler(time, _timed_run(time, [100.0]), record_duration=durations)
    runner = asyncio.create_task(scheduler.run())
    await time.settle()
    await time.advance(10)
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner
    await time.settle()
    assert durations.summaries == []


async def test_a_duration_writer_that_raises_is_logged_by_class_name_and_the_loop_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    time = VirtualTime()
    journal = Journal()
    calls: list[TaskDurationSummary] = []

    async def failing(summary: TaskDurationSummary) -> None:
        calls.append(summary)
        raise RuntimeError("secret writer detail")

    scheduler = _duration_scheduler(
        time, _timed_run(time, [1.0, 2.0]), record=journal, record_duration=failing
    )
    with caplog.at_level("WARNING"):
        await _run_for(scheduler, time, 20)

    assert journal.kinds() == [("a", "first_run")]
    assert len(calls) == 2
    # The counts are updated before the write: the failed first write loses that row only.
    assert (calls[1].runs, calls[1].total_ms, calls[1].max_ms) == (2, 3000, 2000)
    text = caplog.text
    assert "RuntimeError" in text
    assert "secret writer detail" not in text


async def _drive(*, with_record: bool) -> tuple[Any, ...]:
    time = VirtualTime()
    journal = Journal()
    durations = DurationJournal() if with_record else None
    scheduler = _duration_scheduler(
        time,
        _timed_run(time, [1.0, 2.0, 0.5, 3.0], fail_at=3),
        record=journal,
        record_duration=durations,
        window=timedelta(seconds=30) if with_record else None,
    )
    await _run_for(scheduler, time, 100)
    return (list(time.sleeps), journal.kinds(), dict(scheduler.results()))


async def test_the_duration_record_does_not_change_the_sleeps_the_events_or_the_results() -> None:
    with_record = await _drive(with_record=True)
    without_record = await _drive(with_record=False)
    assert with_record == without_record


async def test_a_clock_that_steps_back_records_zero_milliseconds_never_a_negative_number() -> None:
    time = VirtualTime()
    durations = DurationJournal()
    readings = iter([TEST_ONLY_VIRTUAL_START, TEST_ONLY_VIRTUAL_START - timedelta(seconds=5)])

    def scripted_clock() -> Any:
        return next(readings, TEST_ONLY_VIRTUAL_START)

    async def run() -> None:
        return None

    scheduler = Scheduler(
        clock=scripted_clock,
        sleep=time.sleep,
        record=Journal(),
        specs=[TaskSpec("a", run, timedelta(seconds=15))],
        record_duration=durations,
    )
    await _run_for(scheduler, time, 1)

    assert len(durations.summaries) == 1
    summary = durations.summaries[0]
    assert (summary.total_ms, summary.max_ms, summary.window_max_ms) == (0, 0, 0)
    assert summary.new_max is True


@pytest.mark.parametrize("bad", [timedelta(0), timedelta(seconds=-1)])
def test_a_non_positive_summary_interval_is_refused(bad: timedelta) -> None:
    time = VirtualTime()

    async def run() -> None:
        return None

    with pytest.raises(ValueError, match="duration_summary_interval"):
        Scheduler(
            clock=time.now,
            sleep=time.sleep,
            record=Journal(),
            specs=[TaskSpec("a", run, timedelta(seconds=15))],
            duration_summary_interval=bad,
        )


def test_an_unset_summary_interval_leaves_the_cadence_none_and_never_refuses() -> None:
    limits = limits_support.test_only_execution_limits()
    assert limits.scheduler_duration_summary_interval_ms is None
    cadences = LiveCadences.from_limits(limits, test_only_binance_limits())
    assert cadences.duration_summary_interval is None


def test_a_set_summary_interval_is_carried_as_a_timedelta() -> None:
    limits = limits_support.test_only_execution_limits(scheduler_duration_summary_interval_ms=6262)
    cadences = LiveCadences.from_limits(limits, test_only_binance_limits())
    assert cadences.duration_summary_interval == timedelta(milliseconds=6262)


def test_an_unset_tick_still_refuses_naming_only_the_tick_with_the_summary_key_set() -> None:
    limits = limits_support.test_only_execution_limits(
        scheduler_duration_summary_interval_ms=6262,
        **{EXECUTION_LIMIT_FIELDS["reconcile.tick_interval_ms"]: None},
    )
    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        LiveCadences.from_limits(limits, test_only_binance_limits())
    assert caught.value.keys == ("reconcile.tick_interval_ms",)
