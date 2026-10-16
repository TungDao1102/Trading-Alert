"""Virtual time for supervisor tests: an injected clock and sleep that never really sleep.

`VirtualTime.now()` is an aware UTC datetime that moves only through `advance()`. `sleep(seconds)`
records the requested duration in `sleeps` and suspends the caller until `advance()` moves
virtual time to or past its deadline. `advance()` wakes the due sleepers in deadline order and
yields to the event loop after each wake so the woken tasks run (and may register new sleeps,
which are woken in the same call when they fall due before the target). Nothing here calls
`asyncio.sleep`: a yield to the loop is a future completed by `loop.call_soon`.

The start time is TEST_ONLY and not a value of the project.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from datetime import UTC, datetime, timedelta

TEST_ONLY_VIRTUAL_START = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)

# How many loop iterations a settle yields; generous so a chain of task hand-offs completes.
SETTLE_ROUNDS = 200


async def yield_to_loop() -> None:
    """Give every ready callback of the running loop one turn (no `asyncio.sleep`)."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[None] = loop.create_future()
    loop.call_soon(future.set_result, None)
    await future


class VirtualTime:
    """An injected clock and sleep with `advance()`; see the module docstring."""

    def __init__(self, start: datetime = TEST_ONLY_VIRTUAL_START) -> None:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        self._now = start
        self.sleeps: list[float] = []
        self._sleepers: list[tuple[datetime, int, asyncio.Future[None]]] = []
        self._sequence = itertools.count()

    def now(self) -> datetime:
        return self._now

    def __call__(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if seconds <= 0:
            await yield_to_loop()
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        deadline = self._now + timedelta(seconds=seconds)
        heapq.heappush(self._sleepers, (deadline, next(self._sequence), future))
        await future

    def pending_sleepers(self) -> int:
        """How many sleeps are still waiting (cancelled ones excluded)."""
        return sum(1 for _, _, future in self._sleepers if not future.done())

    async def settle(self, rounds: int = SETTLE_ROUNDS) -> None:
        for _ in range(rounds):
            await yield_to_loop()

    async def advance(self, seconds: float) -> None:
        """Move virtual time forward by `seconds`, waking due sleepers in deadline order."""
        target = self._now + timedelta(seconds=seconds)
        await self.settle()
        while self._sleepers and self._sleepers[0][0] <= target:
            deadline, _, future = heapq.heappop(self._sleepers)
            if future.done():
                continue
            if deadline > self._now:
                self._now = deadline
            future.set_result(None)
            await self.settle()
        self._now = target
        await self.settle()


__all__ = ["SETTLE_ROUNDS", "TEST_ONLY_VIRTUAL_START", "VirtualTime", "yield_to_loop"]
