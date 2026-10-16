"""Drift measurement with an injected clock and server-time source; -1021 re-measure (18-07).

Every test uses a virtual clock and a scripted server-time coroutine: nothing sleeps, reads a
real clock or touches the network. Limits are TEST_ONLY values (`tests/support/limits.py`).
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from src.adapters import binance_clock as bclock

from tests.support import limits as tl
from tests.support.ast_guards import float_constructor_calls, wall_clock_calls

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
T0 = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
HOST_MS = 1_772_600_000_000  # an arbitrary virtual host-clock origin in milliseconds


class VirtualClock:
    """A scripted host clock (`clock_ms`) and a UTC clock (`now_utc`); records every read."""

    def __init__(self, readings_ms: list[int], now: datetime = T0) -> None:
        self._readings = list(readings_ms)
        self.reads = 0
        self.now = now

    def clock_ms(self) -> int:
        self.reads += 1
        return self._readings.pop(0)

    def now_utc(self) -> datetime:
        return self.now


class ScriptedServerTime:
    """An async server-time source returning (or raising) scripted results, counting calls."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.calls = 0
        self.on_call: Callable[[], None] | None = None

    async def __call__(self) -> datetime:
        self.calls += 1
        if self.on_call is not None:
            self.on_call()
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result  # type: ignore[return-value]


def _server_at(ms: int) -> datetime:
    return EPOCH + timedelta(milliseconds=ms)


def _limits(**changes: object) -> bclock.DriftLimits:
    return dataclasses.replace(tl.test_only_drift_limits(), **changes)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# measure_clock_drift
# --------------------------------------------------------------------------- #


async def test_measurement_reads_the_clock_around_exactly_one_server_call() -> None:
    clock = VirtualClock([HOST_MS, HOST_MS + 10])
    server = ScriptedServerTime(_server_at(HOST_MS - 100))
    reads_at_call: list[int] = []
    server.on_call = lambda: reads_at_call.append(clock.reads)

    verdict = await bclock.measure_clock_drift(
        server_time=server, clock_ms=clock.clock_ms, now_utc=clock.now_utc, limits=_limits()
    )

    assert server.calls == 1
    assert clock.reads == 2
    assert reads_at_call == [1]  # one read before the call, one after
    assert verdict.measurement_failed is False
    assert verdict.offset_ms == 105  # midpoint HOST_MS + 5 minus server HOST_MS - 100
    assert verdict.uncertainty_ms == 5
    assert verdict.within_limits is True
    assert verdict.measured_at_utc == T0
    assert verdict.failure_type is None


async def test_server_datetime_converts_to_exact_milliseconds_without_float() -> None:
    # 999 microseconds past a millisecond must floor, never round through a float.
    server_moment = _server_at(HOST_MS) + timedelta(microseconds=999)
    clock = VirtualClock([HOST_MS, HOST_MS])
    verdict = await bclock.measure_clock_drift(
        server_time=ScriptedServerTime(server_moment),
        clock_ms=clock.clock_ms,
        now_utc=clock.now_utc,
        limits=_limits(),
    )
    assert verdict.offset_ms == 0


async def test_a_non_utc_aware_server_time_is_converted_by_its_offset() -> None:
    plus_two = datetime(2026, 3, 4, 7, 6, 7, tzinfo=timezone(timedelta(hours=2)))
    utc_ms = (plus_two - EPOCH) // timedelta(milliseconds=1)
    clock = VirtualClock([utc_ms + 40, utc_ms + 40])
    verdict = await bclock.measure_clock_drift(
        server_time=ScriptedServerTime(plus_two),
        clock_ms=clock.clock_ms,
        now_utc=clock.now_utc,
        limits=_limits(),
    )
    assert verdict.offset_ms == 40


async def test_an_out_of_limit_measurement_is_a_successful_verdict_outside_limits() -> None:
    clock = VirtualClock([HOST_MS, HOST_MS])
    verdict = await bclock.measure_clock_drift(
        server_time=ScriptedServerTime(_server_at(HOST_MS - tl.TEST_ONLY_AHEAD_LIMIT_MS - 1)),
        clock_ms=clock.clock_ms,
        now_utc=clock.now_utc,
        limits=_limits(),
    )
    assert verdict.measurement_failed is False
    assert verdict.within_limits is False


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("slow"),
        ConnectionError("down"),
        ValueError("missing server_time"),
        KeyError("x"),
    ],
)
async def test_a_raising_server_time_is_a_failed_verdict_naming_the_type_only(
    error: Exception,
) -> None:
    clock = VirtualClock([HOST_MS, HOST_MS])
    server = ScriptedServerTime(error)
    verdict = await bclock.measure_clock_drift(
        server_time=server, clock_ms=clock.clock_ms, now_utc=clock.now_utc, limits=_limits()
    )
    assert server.calls == 1  # no retry inside the measurement
    assert verdict.measurement_failed is True
    assert verdict.within_limits is False
    assert verdict.offset_ms is None and verdict.uncertainty_ms is None
    assert verdict.failure_type == type(error).__name__
    assert str(error.args[0]) not in (verdict.failure_type or "")
    assert verdict.measured_at_utc == T0


async def test_a_naive_server_datetime_is_a_failed_verdict() -> None:
    clock = VirtualClock([HOST_MS, HOST_MS])
    naive = datetime(2026, 3, 4, 5, 6, 7)  # noqa: DTZ001 - the naive value under test
    verdict = await bclock.measure_clock_drift(
        server_time=ScriptedServerTime(naive),
        clock_ms=clock.clock_ms,
        now_utc=clock.now_utc,
        limits=_limits(),
    )
    assert verdict.measurement_failed is True
    assert verdict.failure_type == bclock.NAIVE_SERVER_TIME


async def test_a_non_datetime_server_result_is_a_failed_verdict() -> None:
    clock = VirtualClock([HOST_MS, HOST_MS])
    verdict = await bclock.measure_clock_drift(
        server_time=ScriptedServerTime(HOST_MS),
        clock_ms=clock.clock_ms,
        now_utc=clock.now_utc,
        limits=_limits(),
    )
    assert verdict.measurement_failed is True
    assert verdict.failure_type == bclock.NOT_A_DATETIME


async def test_a_backwards_host_clock_is_a_failed_verdict() -> None:
    clock = VirtualClock([HOST_MS, HOST_MS - 1])
    verdict = await bclock.measure_clock_drift(
        server_time=ScriptedServerTime(_server_at(HOST_MS)),
        clock_ms=clock.clock_ms,
        now_utc=clock.now_utc,
        limits=_limits(),
    )
    assert verdict.measurement_failed is True
    assert verdict.within_limits is False
    assert verdict.failure_type == bclock.HOST_CLOCK_BACKWARDS


async def test_a_non_int_host_clock_reading_is_a_failed_verdict() -> None:
    clock = VirtualClock([HOST_MS, True])  # type: ignore[list-item]
    verdict = await bclock.measure_clock_drift(
        server_time=ScriptedServerTime(_server_at(HOST_MS)),
        clock_ms=clock.clock_ms,
        now_utc=clock.now_utc,
        limits=_limits(),
    )
    assert verdict.measurement_failed is True
    assert verdict.failure_type == bclock.INVALID_HOST_CLOCK_READING


async def test_cancellation_is_not_swallowed() -> None:
    import asyncio

    clock = VirtualClock([HOST_MS, HOST_MS])
    with pytest.raises(asyncio.CancelledError):
        await bclock.measure_clock_drift(
            server_time=ScriptedServerTime(asyncio.CancelledError()),
            clock_ms=clock.clock_ms,
            now_utc=clock.now_utc,
            limits=_limits(),
        )


def test_measurement_arguments_are_required_keywords() -> None:
    params = inspect.signature(bclock.measure_clock_drift).parameters
    assert list(params) == ["server_time", "clock_ms", "now_utc", "limits"]
    for param in params.values():
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty


# --------------------------------------------------------------------------- #
# Re-measure scheduling and refresh
# --------------------------------------------------------------------------- #


def _guard(**changes: object) -> bclock.ClockDriftGuard:
    return bclock.ClockDriftGuard(limits=_limits(**changes))


async def _refresh_good(guard: bclock.ClockDriftGuard, now: datetime) -> bclock.DriftVerdict:
    clock = VirtualClock([HOST_MS, HOST_MS], now=now)
    return await guard.refresh(
        server_time=ScriptedServerTime(_server_at(HOST_MS)),
        clock_ms=clock.clock_ms,
        now_utc=clock.now_utc,
    )


def test_needs_remeasure_when_no_verdict_exists() -> None:
    assert _guard().needs_remeasure(T0) is True


async def test_periodic_remeasure_after_the_interval_has_elapsed() -> None:
    guard = _guard()
    await _refresh_good(guard, T0)
    interval = timedelta(seconds=tl.TEST_ONLY_PERIODIC_REMEASURE_INTERVAL_SECONDS)
    assert guard.needs_remeasure(T0) is False
    assert guard.needs_remeasure(T0 + interval - timedelta(microseconds=1)) is False
    assert guard.needs_remeasure(T0 + interval) is True


async def test_no_periodic_remeasure_when_the_interval_is_none() -> None:
    guard = _guard(periodic_remeasure_interval_seconds=None)
    await _refresh_good(guard, T0)
    assert guard.needs_remeasure(T0 + timedelta(days=30)) is False
    # The age rule still applies: an old verdict blocks entries.
    assert guard.entries_allowed(T0 + timedelta(days=30)) is False
    assert guard.blocked_reason(T0 + timedelta(days=30)) is bclock.DriftBlockReason.STALE


async def test_flag_driven_remeasure_and_refresh_clears_the_flag() -> None:
    guard = _guard(periodic_remeasure_interval_seconds=None)
    await _refresh_good(guard, T0)
    guard.request_remeasure()
    assert guard.remeasure_requested is True
    assert guard.needs_remeasure(T0) is True
    verdict = await _refresh_good(guard, T0 + timedelta(seconds=1))
    assert guard.remeasure_requested is False
    assert guard.needs_remeasure(T0 + timedelta(seconds=1)) is False
    assert guard.last_verdict == verdict
    assert guard.entries_allowed(T0 + timedelta(seconds=1)) is True


async def test_refresh_records_a_failed_verdict_and_entries_stay_blocked() -> None:
    guard = _guard()
    await _refresh_good(guard, T0)
    clock = VirtualClock([HOST_MS, HOST_MS], now=T0 + timedelta(seconds=2))
    server = ScriptedServerTime(TimeoutError("slow"))
    verdict = await guard.refresh(
        server_time=server, clock_ms=clock.clock_ms, now_utc=clock.now_utc
    )
    assert server.calls == 1
    assert verdict.measurement_failed is True
    assert guard.last_verdict is verdict
    assert guard.entries_allowed(T0 + timedelta(seconds=2)) is False
    assert guard.blocked_reason(T0 + timedelta(seconds=2)) is (
        bclock.DriftBlockReason.MEASUREMENT_FAILED
    )


async def test_a_request_during_the_measurement_survives_the_refresh() -> None:
    guard = _guard(periodic_remeasure_interval_seconds=None)
    guard.request_remeasure()
    clock = VirtualClock([HOST_MS, HOST_MS])
    server = ScriptedServerTime(_server_at(HOST_MS))
    server.on_call = guard.note_clock_skew_error  # a -1021 arrives while measuring
    await guard.refresh(server_time=server, clock_ms=clock.clock_ms, now_utc=clock.now_utc)
    assert guard.remeasure_requested is True
    assert guard.needs_remeasure(T0) is True


# --------------------------------------------------------------------------- #
# -1021: only a re-measure request
# --------------------------------------------------------------------------- #


def test_note_clock_skew_error_only_requests_a_remeasure() -> None:
    guard = _guard()
    calls: list[str] = []
    original = guard.request_remeasure

    def spy() -> None:
        calls.append("request_remeasure")
        original()

    guard.request_remeasure = spy  # type: ignore[method-assign]
    result = guard.note_clock_skew_error()
    assert result is None
    assert calls == ["request_remeasure"]
    assert guard.last_verdict is None  # nothing measured, nothing recorded


def test_note_clock_skew_error_is_synchronous_and_takes_no_io_argument() -> None:
    method = bclock.ClockDriftGuard.note_clock_skew_error
    assert not inspect.iscoroutinefunction(method)
    assert list(inspect.signature(method).parameters) == ["self"]


async def test_a_minus_1021_never_re_enables_entries_by_itself() -> None:
    guard = _guard()
    guard.note_clock_skew_error()
    assert guard.entries_allowed(T0) is False
    assert guard.blocked_reason(T0) is bclock.DriftBlockReason.NEVER_MEASURED

    clock = VirtualClock([HOST_MS, HOST_MS])
    await guard.refresh(
        server_time=ScriptedServerTime(_server_at(HOST_MS - tl.TEST_ONLY_AHEAD_LIMIT_MS - 1)),
        clock_ms=clock.clock_ms,
        now_utc=clock.now_utc,
    )
    guard.note_clock_skew_error()
    assert guard.entries_allowed(T0) is False
    assert guard.blocked_reason(T0) is bclock.DriftBlockReason.OUT_OF_LIMITS

    await _refresh_good(guard, T0 + timedelta(seconds=1))
    assert guard.entries_allowed(T0 + timedelta(seconds=1)) is True


async def test_a_minus_1021_after_a_good_verdict_blocks_until_a_fresh_measurement() -> None:
    guard = _guard()
    await _refresh_good(guard, T0)
    assert guard.entries_allowed(T0) is True
    guard.note_clock_skew_error()
    # Binance contradicted the last verdict: it no longer counts as fresh.
    assert guard.entries_allowed(T0) is False
    assert guard.blocked_reason(T0) is bclock.DriftBlockReason.STALE
    await _refresh_good(guard, T0 + timedelta(seconds=1))
    assert guard.entries_allowed(T0 + timedelta(seconds=1)) is True


# --------------------------------------------------------------------------- #
# Source guard
# --------------------------------------------------------------------------- #


def test_the_clock_module_reads_no_clock_and_builds_no_float() -> None:
    module = inspect.getsourcefile(bclock)
    assert module is not None
    assert float_constructor_calls(module) == []
    assert wall_clock_calls(module) == []
    source = open(module, encoding="utf-8").read()  # noqa: PTH123, SIM115 - read-only check
    assert ".timestamp(" not in source
    assert "asyncio.sleep" not in source
