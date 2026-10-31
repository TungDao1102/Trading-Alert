"""Plan 24-05 (D-25, G4-040): the StoreExecutor seam keeps store I/O off the event loop.

Facts pinned here (research P-2, measured on this stack):

* ordered writes complete in submission order because they share ONE worker thread;
* reads go through `asyncio.to_thread` and may run and finish in parallel;
* a cancelled awaiting caller does NOT stop its write (the side effect still happens), so a
  caller keeps every write idempotent;
* an exception of the store function reaches the awaiting caller unchanged;
* contextvars set by the caller are visible in the worker;
* `close()` drains the queued writes and later writes are refused.

The tests use real threads and `threading.Event` handshakes with one bounded wait, no sleeps.
"""

from __future__ import annotations

import asyncio
import contextvars
import threading

import pytest

from src.ops.store_executor import WRITER_THREAD_PREFIX, StoreExecutor

TEST_ONLY_WAIT_SECONDS = 5.0

_marker: contextvars.ContextVar[str] = contextvars.ContextVar("test_marker", default="unset")


class StoreBoom(Exception):
    """A store failure with a message the test compares exactly."""


async def _wait(event: threading.Event) -> None:
    """Wait for a worker-thread event without blocking the loop (bounded)."""
    assert await asyncio.to_thread(event.wait, TEST_ONLY_WAIT_SECONDS), "worker handshake timed out"


async def test_concurrent_writes_complete_in_submission_order_on_one_writer_thread() -> None:
    executor = StoreExecutor()
    first_started = threading.Event()
    release_first = threading.Event()
    done: list[str] = []
    threads: list[str] = []

    def slow_first() -> str:
        first_started.set()
        assert release_first.wait(TEST_ONLY_WAIT_SECONDS)
        done.append("first")
        threads.append(threading.current_thread().name)
        return "first"

    def fast_second() -> str:
        done.append("second")
        threads.append(threading.current_thread().name)
        return "second"

    try:
        first = asyncio.create_task(executor.write(slow_first))
        await _wait(first_started)
        second = asyncio.create_task(executor.write(fast_second))
        await asyncio.sleep(0)  # the second submission reaches the writer queue
        release_first.set()
        assert await asyncio.gather(first, second) == ["first", "second"]
    finally:
        await executor.aclose()

    assert done == ["first", "second"]
    assert len(set(threads)) == 1
    assert threads[0].startswith(WRITER_THREAD_PREFIX)
    assert threads[0] != threading.current_thread().name


async def test_concurrent_reads_run_in_parallel_off_the_writer_thread() -> None:
    executor = StoreExecutor()
    second_done = threading.Event()
    done: list[str] = []
    threads: list[str] = []

    def slow_first() -> None:
        # Would deadlock (and time out) if the reads were serialized behind each other.
        assert second_done.wait(TEST_ONLY_WAIT_SECONDS)
        done.append("first")
        threads.append(threading.current_thread().name)

    def fast_second() -> None:
        done.append("second")
        threads.append(threading.current_thread().name)
        second_done.set()

    try:
        await asyncio.gather(executor.read(slow_first), executor.read(fast_second))
    finally:
        await executor.aclose()

    assert done == ["second", "first"]
    assert all(not name.startswith(WRITER_THREAD_PREFIX) for name in threads)
    assert all(name != threading.current_thread().name for name in threads)


async def test_a_cancelled_caller_does_not_cancel_a_running_write() -> None:
    """P-2: the worker thread cannot be stopped, so the write completes; keep writes idempotent."""
    executor = StoreExecutor()
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def write() -> None:
        started.set()
        assert release.wait(TEST_ONLY_WAIT_SECONDS)
        completed.set()

    try:
        caller = asyncio.create_task(executor.write(write))
        await _wait(started)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert not completed.is_set()  # still running in the worker
        release.set()
        await _wait(completed)
    finally:
        await executor.aclose()


async def test_a_cancelled_caller_does_not_drop_a_queued_write() -> None:
    """A write still waiting in the writer queue survives its caller's cancellation too."""
    executor = StoreExecutor()
    first_started = threading.Event()
    release_first = threading.Event()
    queued_ran = threading.Event()

    def blocker() -> None:
        first_started.set()
        assert release_first.wait(TEST_ONLY_WAIT_SECONDS)

    try:
        first = asyncio.create_task(executor.write(blocker))
        await _wait(first_started)
        queued = asyncio.create_task(executor.write(queued_ran.set))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        release_first.set()
        await first
        await _wait(queued_ran)
    finally:
        await executor.aclose()


async def test_a_store_exception_reaches_the_caller_unchanged_and_the_writer_survives() -> None:
    executor = StoreExecutor()

    def failing() -> None:
        raise StoreBoom("journal write refused: 23505")

    def failing_read() -> None:
        raise StoreBoom("read refused")

    try:
        with pytest.raises(StoreBoom) as write_error:
            await executor.write(failing)
        assert str(write_error.value) == "journal write refused: 23505"
        with pytest.raises(StoreBoom) as read_error:
            await executor.read(failing_read)
        assert str(read_error.value) == "read refused"
        assert await executor.write(lambda: "still works") == "still works"
    finally:
        await executor.aclose()


async def test_a_cancelled_caller_whose_write_fails_leaves_no_unretrieved_exception(
    recwarn: pytest.WarningsRecorder,
) -> None:
    executor = StoreExecutor()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def failing() -> None:
        started.set()
        assert release.wait(TEST_ONLY_WAIT_SECONDS)
        try:
            raise StoreBoom("late failure")
        finally:
            finished.set()

    caller = asyncio.create_task(executor.write(failing))
    await _wait(started)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    release.set()
    await _wait(finished)
    await executor.aclose()
    await asyncio.sleep(0)
    assert not [w for w in recwarn if "never retrieved" in str(w.message)]


async def test_the_caller_context_is_visible_in_read_and_write() -> None:
    executor = StoreExecutor()
    token = _marker.set("caller-value")
    try:
        assert await executor.write(_marker.get) == "caller-value"
        assert await executor.read(_marker.get) == "caller-value"
    finally:
        _marker.reset(token)
        await executor.aclose()


async def test_arguments_and_keyword_arguments_reach_the_function() -> None:
    executor = StoreExecutor()

    def combine(a: int, b: int, *, scale: int) -> int:
        return (a + b) * scale

    try:
        assert await executor.write(combine, 1, 2, scale=3) == 9
        assert await executor.read(combine, 1, 2, scale=4) == 12
    finally:
        await executor.aclose()


async def test_close_drains_the_queued_writes_and_refuses_later_ones() -> None:
    executor = StoreExecutor()
    started = threading.Event()
    release = threading.Event()
    done: list[str] = []

    def first() -> None:
        started.set()
        assert release.wait(TEST_ONLY_WAIT_SECONDS)
        done.append("first")

    def second() -> None:
        done.append("second")

    first_task = asyncio.create_task(executor.write(first))
    await _wait(started)
    second_task = asyncio.create_task(executor.write(second))
    await asyncio.sleep(0)
    closer = asyncio.create_task(executor.aclose())
    await asyncio.sleep(0)
    assert not closer.done()  # the writer is still draining
    release.set()
    await asyncio.gather(first_task, second_task, closer)
    assert done == ["first", "second"]

    with pytest.raises(RuntimeError, match="closed"):
        await executor.write(lambda: None)
    assert await executor.read(lambda: "reads are not the writer") == "reads are not the writer"


async def test_close_is_idempotent() -> None:
    executor = StoreExecutor()
    assert await executor.write(lambda: 1) == 1
    executor.close()
    executor.close()
    await executor.aclose()


async def test_aclose_does_not_block_the_event_loop_while_the_writer_drains() -> None:
    executor = StoreExecutor()
    started = threading.Event()
    release = threading.Event()
    writer = asyncio.create_task(executor.write(lambda: (started.set(), release.wait(5.0))))
    await _wait(started)
    closer = asyncio.create_task(executor.aclose())
    ticks = 0
    while not closer.done() and ticks < 3:
        await asyncio.sleep(0)  # the loop keeps turning although the writer is busy
        ticks += 1
    assert ticks == 3
    release.set()
    await asyncio.gather(writer, closer)
