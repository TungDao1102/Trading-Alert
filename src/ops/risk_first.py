"""Act first, journal afterwards: risk-reducing controls never wait for the journal (D-16, F-702).

A risk-reducing control (disable live orders, cancel a pending entry, cancel the protective
legs, the manual emergency close) must reach its effect even when the journal or its database
is down. Two helpers carry that rule:

- `record_after`: the action has already happened. Try the journal; if it fails, write the
  record to the local spill; if that fails too, raise `AuditRecordLost`.
- `act_then_record`: start the write-ahead to the spill (in a worker thread, so a crash during
  the action still leaves the evidence once the write lands), run the action beside it, then try
  the journal and remove the spill file on success. The action never waits for the spill disk
  (Phase 20 review WR-C7); only the settling of the audit record may, and only when the journal
  failed and the spill is the one remaining record. The action's result or exception is
  preserved. `AuditRecordLost` is raised only when the action succeeded and neither the journal
  nor the spill took the record.

A spill failure before the action is remembered, never raised: the action still runs. Every
message and note here names exception CLASSES only, never exception text (which may carry
request material).

The spill is supplementary evidence of what this process did; it is never a substitute for
Binance truth (D-30).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from src.domain.journal import JournalEvent
from src.ops.spill import LocalSpill, SpillToken

_NO_SPILL = "NoSpillConfigured"


class AuditRecordLost(Exception):
    """The action ran, but neither the journal nor the spill could take its audit record.

    The message names the event id and the exception class names only.
    """

    def __init__(self, *, journal_event_id: str, journal_error: str, spill_error: str) -> None:
        self.journal_event_id = journal_event_id
        self.journal_error = journal_error
        self.spill_error = spill_error
        super().__init__(
            f"audit record {journal_event_id} lost after the action ran: "
            f"journal={journal_error}, spill={spill_error}"
        )


def _try_journal(journal: Any, event: JournalEvent) -> str | None:
    """Record the event; return None on success or the exception class name on failure."""
    try:
        journal.record(event)
    except Exception as exc:
        return type(exc).__name__
    return None


def _try_spill(spill: LocalSpill | None, event: JournalEvent) -> tuple[SpillToken | None, str]:
    """Write the spill; return (token, "") on success or (None, class name) on failure."""
    if spill is None:
        return None, _NO_SPILL
    try:
        return spill.write(event), ""
    except Exception as exc:
        return None, type(exc).__name__


def _discard_quietly(spill: LocalSpill | None, token: SpillToken | None) -> None:
    """Remove a spill file after the journal accepted its record; a failure keeps the file.

    A kept file is harmless: a later replay finds the id already present and removes it.
    """
    if spill is None or token is None:
        return
    try:
        spill.discard(token)
    except Exception:
        return


def record_after(*, spill: LocalSpill | None, journal: Any, event: JournalEvent) -> None:
    """Record `event` for an action that has already happened.

    Raises:
        AuditRecordLost: the journal and the spill both failed (or no spill is configured).
    """
    journal_error = _try_journal(journal, event)
    if journal_error is None:
        return
    token, spill_error = _try_spill(spill, event)
    if token is None:
        raise AuditRecordLost(
            journal_event_id=event.journal_event_id,
            journal_error=journal_error,
            spill_error=spill_error,
        )


type _SpillOutcome = tuple[SpillToken | None, str]


def _start_spill(spill: LocalSpill | None, event: JournalEvent) -> asyncio.Future[_SpillOutcome]:
    """Start the write-ahead in a worker thread and return at once (WR-C7).

    The file write, its fsync and `replace_with_retry` (which sleeps on a Windows lock) must not
    run on the event loop in front of a risk-reducing action: a stalled disk would hold the
    action and every other coroutine. `_try_spill` never raises an `Exception`.
    """
    loop = asyncio.get_running_loop()
    if spill is None:
        done: asyncio.Future[_SpillOutcome] = loop.create_future()
        done.set_result((None, _NO_SPILL))
        return done
    return loop.run_in_executor(None, _try_spill, spill, event)


def _spill_result(future: asyncio.Future[_SpillOutcome]) -> _SpillOutcome | None:
    """The finished write-ahead's outcome, or None while it is still running."""
    if not future.done() or future.cancelled() or future.exception() is not None:
        return None
    return future.result()


def _discard_when_written(spill: LocalSpill | None, future: asyncio.Future[_SpillOutcome]) -> None:
    """The journal took the record: remove the spill file, now or when the write finishes."""
    outcome = _spill_result(future)
    if outcome is not None:
        _discard_quietly(spill, outcome[0])
        return

    def discard(finished: asyncio.Future[_SpillOutcome]) -> None:
        late = _spill_result(finished)
        if late is not None:
            _discard_quietly(spill, late[0])

    future.add_done_callback(discard)


async def act_then_record[T](
    *,
    spill: LocalSpill | None,
    journal: Any,
    event: JournalEvent,
    action: Callable[[], Awaitable[T]],
) -> T:
    """Start the spill write-ahead, run `action` beside it, then record `event` in the journal.

    Returns the action's result. If the action raises, that exception is re-raised after the
    audit attempt (a lost audit record is attached to it as a note, class names only).

    The action never waits for the spill disk (WR-C7). When the journal takes the record the
    spill file is removed as soon as its write has finished, without waiting for it. Only when
    the journal failed does the call wait for the write-ahead, because that file is then the one
    remaining record and its fate decides whether the audit record is lost.

    Raises:
        AuditRecordLost: the action succeeded but the journal and the spill both failed.
    """
    spill_future = _start_spill(spill, event)
    try:
        result = await action()
    except BaseException as exc:
        journal_error = _try_journal(journal, event)
        if journal_error is None:
            _discard_when_written(spill, spill_future)
        else:
            outcome = _spill_result(spill_future)
            if outcome is not None and outcome[0] is None:
                exc.add_note(
                    f"audit record {event.journal_event_id} lost: "
                    f"journal={journal_error}, spill={outcome[1]}"
                )
        raise
    journal_error = _try_journal(journal, event)
    if journal_error is None:
        _discard_when_written(spill, spill_future)
        return result
    token, spill_error = await spill_future
    if token is not None:
        return result  # the record waits in the spill until replay
    raise AuditRecordLost(
        journal_event_id=event.journal_event_id,
        journal_error=journal_error,
        spill_error=spill_error,
    )


__all__ = ["AuditRecordLost", "act_then_record", "record_after"]
