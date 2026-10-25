"""`act_then_record` never makes the risk-reducing action wait for the spill disk (WR-C7).

The write-ahead used to run synchronously on the event loop before `await action()`: open,
write, fsync, `replace_with_retry` (which sleeps up to 0.4 s on a Windows `PermissionError`) and
no timeout. A stalled disk or an antivirus lock therefore delayed the action and froze every
other coroutine. Now the write-ahead is started in a worker thread and runs beside the action;
the action never waits for it, and the journal result settles it afterwards.

Evidence label: executed tests with fakes only. No database, no network, no Binance.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
from datetime import UTC, datetime

import pytest
from src.domain.journal import JournalEvent
from src.ops.risk_first import AuditRecordLost, act_then_record
from src.ops.spill import SpillToken

from tests.support.reconcile_doubles import RaisingJournal, RecordingJournal

NOW_UTC = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
TOKEN = SpillToken(journal_event_id="unit_test_wa")


def _event() -> JournalEvent:
    return JournalEvent(
        journal_event_id="unit_test_wa",
        occurred_at_utc=NOW_UTC,
        event_type="UNIT_TEST_EVENT",
        entity_type="UnitTest",
        entity_id="entity-wa",
        correlation_id="unit_test_correlation",
        payload_json=json.dumps({"k": "wa"}, separators=(",", ":")),
    )


class StalledSpill:
    """A spill whose `write` blocks until the test releases it (a stalled disk)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.writer_thread: int | None = None
        self.discarded: list[SpillToken] = []
        self.written: list[str] = []
        self._fail = fail

    def write(self, event: JournalEvent) -> SpillToken:
        self.writer_thread = threading.get_ident()
        self.started.set()
        assert self.release.wait(timeout=10), "the test never released the stalled write"
        if self._fail:
            raise OSError("TEST_ONLY disk failure")
        self.written.append(event.journal_event_id)
        return SpillToken(journal_event_id=event.journal_event_id)

    def discard(self, token: SpillToken) -> None:
        self.discarded.append(token)


async def _wait_for(flag: threading.Event) -> None:
    for _ in range(500):
        if flag.is_set():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the spill write never started")


async def _wait_discarded(spill: StalledSpill) -> None:
    for _ in range(500):
        if spill.discarded:
            return
        await asyncio.sleep(0.01)


async def test_the_action_runs_and_the_call_returns_while_the_spill_write_is_stalled() -> None:
    spill = StalledSpill()
    journal = RecordingJournal()
    seen: list[str] = []

    async def action() -> str:
        # The write-ahead is already running beside the action, and it is still stalled.
        await _wait_for(spill.started)
        seen.append("action")
        assert not spill.release.is_set()
        return "closed"

    result = await asyncio.wait_for(
        act_then_record(
            spill=spill,  # type: ignore[arg-type]
            journal=journal,
            event=_event(),
            action=action,
        ),
        timeout=5,
    )

    assert result == "closed"
    assert seen == ["action"]
    assert len(journal.events) == 1  # the journal took the record; nobody waited for the disk
    assert spill.writer_thread != threading.get_ident()  # off the event loop thread
    assert spill.discarded == []  # the write has not finished yet

    spill.release.set()  # the disk comes back: the finished write is discarded, not left behind
    await _wait_discarded(spill)
    assert spill.discarded == [TOKEN]


async def test_the_event_loop_keeps_running_while_the_spill_write_is_stalled() -> None:
    spill = StalledSpill()
    ticks: list[int] = []

    async def action() -> None:
        await _wait_for(spill.started)
        for i in range(5):
            ticks.append(i)
            await asyncio.sleep(0)

    await act_then_record(
        spill=spill,  # type: ignore[arg-type]
        journal=RecordingJournal(),
        event=_event(),
        action=action,
    )
    spill.release.set()
    assert ticks == [0, 1, 2, 3, 4]


async def test_with_the_journal_down_the_record_waits_for_the_spill_and_is_kept() -> None:
    spill = StalledSpill()
    calls: list[str] = []

    async def action() -> None:
        calls.append("ran")

    task = asyncio.ensure_future(
        act_then_record(
            spill=spill,  # type: ignore[arg-type]
            journal=RaisingJournal(),
            event=_event(),
            action=action,
        )
    )
    await _wait_for(spill.started)
    await asyncio.sleep(0.05)
    assert calls == ["ran"]  # the action did not wait for the disk
    assert not task.done()  # only the settling of the audit record waits for it
    spill.release.set()
    await asyncio.wait_for(task, timeout=5)
    assert spill.written == ["unit_test_wa"]
    assert spill.discarded == []  # the journal is down: the spill file is the record


async def test_with_the_journal_down_and_the_spill_failing_the_record_is_reported_lost() -> None:
    spill = StalledSpill(fail=True)
    spill.release.set()

    async def action() -> None:
        return None

    with pytest.raises(AuditRecordLost):
        await act_then_record(
            spill=spill,  # type: ignore[arg-type]
            journal=RaisingJournal(),
            event=_event(),
            action=action,
        )


async def test_a_raising_action_is_not_held_by_a_stalled_spill() -> None:
    spill = StalledSpill()
    journal = RecordingJournal()

    async def action() -> None:
        await _wait_for(spill.started)
        raise RuntimeError("exchange said no")

    with pytest.raises(RuntimeError, match="exchange said no"):
        await asyncio.wait_for(
            act_then_record(
                spill=spill,  # type: ignore[arg-type]
                journal=journal,
                event=_event(),
                action=action,
            ),
            timeout=5,
        )

    assert len(journal.events) == 1
    spill.release.set()
    await _wait_discarded(spill)
    assert spill.discarded == [TOKEN]


async def test_a_raising_action_with_the_journal_down_waits_for_the_spill_and_keeps_it() -> None:
    spill = StalledSpill()

    async def action() -> None:
        await _wait_for(spill.started)
        raise RuntimeError("exchange said no")

    task = asyncio.ensure_future(
        act_then_record(
            spill=spill,  # type: ignore[arg-type]
            journal=RaisingJournal(),
            event=_event(),
            action=action,
        )
    )
    await _wait_for(spill.started)
    await asyncio.sleep(0.05)
    assert not task.done()  # the action has ended; only the settling of the record waits
    spill.release.set()
    with pytest.raises(RuntimeError, match="exchange said no"):
        await asyncio.wait_for(task, timeout=5)
    assert spill.written == ["unit_test_wa"]
    assert spill.discarded == []


def test_the_helper_signature_is_unchanged() -> None:
    assert list(inspect.signature(act_then_record).parameters) == [
        "spill",
        "journal",
        "event",
        "action",
    ]
