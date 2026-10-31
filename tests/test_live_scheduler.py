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
    TaskEvent,
    TaskResult,
    TaskSpec,
)

from tests.support import execution_limits as limits_support
from tests.support.execution_limits import TEST_ONLY_EXECUTION_LIMIT_VALUES
from tests.support.limits import test_only_binance_limits
from tests.support.virtual_time import VirtualTime


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
        value = getattr(cadences, item.name)
        assert isinstance(value, timedelta)
        assert value > timedelta(0), item.name
