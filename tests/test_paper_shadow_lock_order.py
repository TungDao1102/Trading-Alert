"""Lock order of the SHADOW chain (Phase 16, plan 16-58, B2-CR-01, T-16-149).

A CONFIRM press ran inside the ledger section and its `on_confirmed` hook took the coordinator
lock, while the poll worker held the coordinator lock and then took the ledger lock. Run at the
same time they waited for each other forever and froze the event loop (the press runs on it).
The rule now: the coordinator lock is never held while the ledger lock is waited for, and the
CONFIRM section never calls back into the coordinator under the ledger lock.

The tests use real threads and instrumented locks. Every instrumented lock gives up after a
bounded wait and records a `deadlock` entry, so a regression is a failing assertion within a few
seconds and never a hung test run.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from types import TracebackType
from typing import Any

from src.domain.journal import JournalEvent
from src.paper.shadow_confirm import EVENT_SHADOW_CONFIRMED
from src.paper.shadow_ledger import EVENT_SHADOW_POSITION_OPENED

from tests.shadow_fakes import CHAT_ID, USER_ID
from tests.test_paper_shadow_runtime import (
    LAG_SECONDS,
    T_APPROVE,
    T_CONFIRM,
    Rig,
    RuntimeStores,
    exposures,
    poll_at,
)

WAIT_SECONDS = 3.0  # an instrumented lock that waits longer than this is a deadlock


@dataclass
class LockLog:
    """What the instrumented locks saw: acquisition edges, deadlocks and the thread hook."""

    edges: set[tuple[str, str]] = field(default_factory=set)
    deadlocks: list[str] = field(default_factory=list)
    on_attempt: Callable[[str], None] | None = None
    _held: threading.local = field(default_factory=threading.local)

    def held(self) -> list[str]:
        stack: list[str] | None = getattr(self._held, "stack", None)
        if stack is None:
            stack = []
            self._held.stack = stack
        return stack


class TrackedLock:
    """A reentrant lock that records `held -> acquired` edges and bounds every wait."""

    def __init__(self, name: str, log: LockLog) -> None:
        self._name = name
        self._log = log
        self._inner = threading.RLock()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        held = self._log.held()
        if self._log.on_attempt is not None:
            self._log.on_attempt(self._name)
        for other in held:
            if other != self._name:
                self._log.edges.add((other, self._name))
        if not self._inner.acquire(timeout=WAIT_SECONDS):
            self._log.deadlocks.append(f"{threading.current_thread().name} waits for {self._name}")
            raise TimeoutError(f"deadlock: waited {WAIT_SECONDS}s for the {self._name} lock")
        held.append(self._name)
        return True

    def release(self) -> None:
        held = self._log.held()
        held.pop()
        self._inner.release()

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def instrument(rig: Rig, log: LockLog) -> None:
    """Swap the coordinator lock and the ledger lock of a rig for tracked ones."""
    rig.coordinator._lock = TrackedLock("coordinator", log)  # type: ignore[assignment]
    rig.ledger._lock = TrackedLock("ledger", log)  # type: ignore[assignment]


class BlockingStores(RuntimeStores):
    """Blocks inside the CONFIRM section (the SHADOW_CONFIRMED append) until released."""

    def __init__(self) -> None:
        super().__init__()
        self.in_section = threading.Event()
        self.release = threading.Event()
        self.armed = False

    def record_journal(self, event: JournalEvent) -> None:
        if self.armed and event.event_type == EVENT_SHADOW_CONFIRMED:
            self.in_section.set()
            self.release.wait(WAIT_SECONDS + 2)
        super().record_journal(event)


async def _approve(rig: Rig) -> str:
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")
    await rig.tap(f"APR:{short}", f"q-apr-{short[:6]}", at=T_APPROVE)
    return short


def _press_confirm(rig: Rig, short: str, errors: list[BaseException]) -> None:
    try:
        rig.coordinator.confirm_book.handle_confirm(
            short_id=short,
            chat_id=CHAT_ID,
            authorized_chat_id=CHAT_ID,
            from_user_id=USER_ID,
            now_utc=T_CONFIRM,
            correlation_id="cb-lock-order",
        )
    except BaseException as exc:  # noqa: BLE001 - the test reports it
        errors.append(exc)


def _poll_step(rig: Rig, errors: list[BaseException]) -> None:
    try:
        rig.now = T_CONFIRM + timedelta(seconds=1)
        asyncio.run(rig.coordinator.poll_once())
    except BaseException as exc:  # noqa: BLE001 - the test reports it
        errors.append(exc)


async def test_a_confirm_and_a_poll_step_at_the_same_time_always_finish() -> None:
    stores = BlockingStores()
    rig = Rig(stores=stores)
    log = LockLog()
    instrument(rig, log)
    built: list[str] = []
    original_build = rig.coordinator._build_position

    def counting_build(reservation: Any) -> Any:
        built.append(reservation.key)
        return original_build(reservation)

    rig.coordinator._build_position = counting_build  # type: ignore[method-assign]
    short = await _approve(rig)

    press_errors: list[BaseException] = []
    poll_errors: list[BaseException] = []
    press = threading.Thread(
        target=_press_confirm, args=(rig, short, press_errors), daemon=True, name="press"
    )
    poll = threading.Thread(target=_poll_step, args=(rig, poll_errors), daemon=True, name="poll")
    poll_waits_for_ledger = threading.Event()

    def watch(name: str) -> None:
        # The poll step (its worker thread is not the press thread) reached for the ledger lock.
        if name == "ledger" and threading.current_thread() is not press:
            poll_waits_for_ledger.set()

    log.on_attempt = watch
    stores.armed = True
    press.start()
    assert stores.in_section.wait(WAIT_SECONDS), "the press never reached the CONFIRM section"
    poll.start()
    # Hold the press inside the ledger section until the poll step is waiting on the ledger lock
    # (in the old code it holds the coordinator lock by then).
    assert poll_waits_for_ledger.wait(WAIT_SECONDS), "the poll step never reached the ledger"
    stores.release.set()

    press.join(WAIT_SECONDS * 3)
    poll.join(WAIT_SECONDS * 3)
    assert log.deadlocks == [], f"lock-order inversion: {log.deadlocks}"
    assert not press.is_alive() and not poll.is_alive(), "a thread is stuck"
    assert press_errors == [] and poll_errors == []
    assert len(stores.journal_of_type(EVENT_SHADOW_CONFIRMED)) == 1
    assert len(exposures(rig)) == 1, "the reservation exists"
    (view,) = rig.coordinator.open_positions()
    assert view.symbol == "BTCUSDT"
    assert built == [view.key], "the driver is built exactly once"


async def test_the_coordinator_lock_is_never_held_while_the_ledger_lock_is_taken() -> None:
    rig = Rig()
    log = LockLog()
    instrument(rig, log)
    short = await _approve(rig)
    await rig.tap(f"CNF:{short}", "q-cnf-order", at=T_CONFIRM)
    # Fill, exit and the expiry sweeps all cross the two locks in a poll step.
    await poll_at(rig, T_CONFIRM + timedelta(minutes=3, seconds=LAG_SECONDS + 1))
    await poll_at(rig, T_CONFIRM + timedelta(minutes=7, seconds=LAG_SECONDS + 1))
    assert rig.journal(EVENT_SHADOW_POSITION_OPENED), "the scenario filled the plan"

    assert ("coordinator", "ledger") not in log.edges, "coordinator lock held while waiting"
    assert ("ledger", "coordinator") not in log.edges, "the ledger section called back"
    assert log.deadlocks == []


async def test_a_restore_never_takes_the_coordinator_lock_inside_the_ledger_section() -> None:
    first = Rig()
    short = await _approve(first)
    await first.tap(f"CNF:{short}", "q-cnf-restore", at=T_CONFIRM)
    await poll_at(first, T_CONFIRM + timedelta(minutes=3, seconds=LAG_SECONDS + 1))
    assert first.journal(EVENT_SHADOW_POSITION_OPENED)

    second = first.restart(now=T_CONFIRM + timedelta(minutes=4, seconds=LAG_SECONDS + 1))
    log = LockLog()
    instrument(second, log)
    await second.coordinator.restore()

    assert ("ledger", "coordinator") not in log.edges
    assert ("coordinator", "ledger") not in log.edges
    assert log.deadlocks == []
    assert len(second.coordinator.open_positions()) == 1, "the filled plan got its driver back"


async def test_a_successful_confirm_gets_its_driver_without_waiting_for_a_poll() -> None:
    rig = Rig()
    short = await _approve(rig)
    assert rig.coordinator.open_positions() == ()
    await rig.tap(f"CNF:{short}", "q-cnf-idle", at=T_CONFIRM)
    (view,) = rig.coordinator.open_positions()
    assert view.filled is False and view.closed is False
