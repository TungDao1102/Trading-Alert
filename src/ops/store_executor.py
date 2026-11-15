"""The StoreExecutor seam: synchronous store calls leave the event loop (D-25, G4-040).

The stores (PostgreSQL through SQLAlchemy, the Parquet and file stores) are synchronous. One
asyncio loop also runs the Telegram runner, the user-data stream and the protection step, so a
store call made ON that loop blocks all of them. Every on-loop store call therefore goes through
this seam:

* `write(fn, ...)` runs on ONE dedicated single-thread executor, so ordered writes complete in
  submission order (the default executor reorders concurrent calls, measured fact P-2).
* `read(fn, ...)` runs through `asyncio.to_thread`: reads may run and finish in parallel.
* The caller's `contextvars` context is copied into the worker for both.
* `close()` drains the writer (queued writes finish; none is cut off mid-flight) and a write
  submitted afterwards raises `RuntimeError`. `aclose()` does the same without blocking the loop.

There is no async database pool and no new dependency (decision D-25, owner answer Q2).

Cancellation (measured fact P-2): a worker thread cannot be stopped. When the task awaiting a
`write` is cancelled, the write is NOT cancelled: a running write finishes, and a write still
waiting in the queue still runs (the awaited future is shielded). The caller learns nothing
about the outcome, so EVERY write passed to this seam must be idempotent at the store layer
(natural key or `ON CONFLICT`), because a caller that gave up may retry. A failure of a write
whose caller was cancelled is swallowed by the seam (the caller is gone); the store function
logs its own errors.

This module lives in `src/ops`, outside `src/execution` and `src/live`, because the SHADOW
isolation closure test bans those packages (C-11). It imports the standard library only.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")

WRITER_THREAD_PREFIX = "store-writer"


def _consume_outcome[V](future: asyncio.Future[V]) -> None:
    """Mark the outcome of a write as retrieved, so an abandoned failure is not logged twice."""
    if not future.cancelled():
        future.exception()


class StoreExecutor:
    """Ordered writes on one thread, parallel reads, caller context propagated, drain on close."""

    def __init__(self) -> None:
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix=WRITER_THREAD_PREFIX)
        self._closed = False

    @property
    def closed(self) -> bool:
        """True once `close()` or `aclose()` was called; later writes raise `RuntimeError`."""
        return self._closed

    async def read(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
        """Run a store read on the default executor (parallel, any order)."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def write(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
        """Run a store write on the single writer thread, in submission order.

        Raises `RuntimeError` when the executor is closed. A cancelled caller does not cancel the
        write (see the module docstring): keep writes idempotent.
        """
        if self._closed:
            raise RuntimeError("StoreExecutor is closed: the write was not submitted")
        context = contextvars.copy_context()
        loop = asyncio.get_running_loop()
        work = loop.run_in_executor(
            self._writer, functools.partial(context.run, functools.partial(fn, *args, **kwargs))
        )
        # Shield: cancelling the awaiting task must not cancel a write that is still queued.
        work.add_done_callback(_consume_outcome)
        return await asyncio.shield(work)

    def close(self) -> None:
        """Drain the writer and stop it (blocking, idempotent). Prefer `aclose()` on the loop."""
        self._closed = True
        self._writer.shutdown(wait=True)

    async def aclose(self) -> None:
        """Like `close()`, but the wait for the drain does not block the event loop."""
        self._closed = True
        await asyncio.to_thread(self._writer.shutdown, wait=True)
