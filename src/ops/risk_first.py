"""Act first, journal afterwards: risk-reducing controls never wait for the journal (D-16, F-702).

A risk-reducing control (disable live orders, cancel a pending entry, cancel the protective
legs, the manual emergency close) must reach its effect even when the journal or its database
is down. Two helpers carry that rule:

- `record_after`: the action has already happened. Try the journal; if it fails, write the
  record to the local spill; if that fails too, raise `AuditRecordLost`.
- `act_then_record`: write the record to the spill first (write-ahead, so a crash during the
  action still leaves the evidence), run the action, then try the journal and remove the
  spill file on success. The action's result or exception is preserved. `AuditRecordLost` is
  raised only when the action succeeded and neither the journal nor the spill took the record.

A spill failure before the action is remembered, never raised: the action still runs. Every
message and note here names exception CLASSES only, never exception text (which may carry
request material).

The spill is supplementary evidence of what this process did; it is never a substitute for
Binance truth (D-30).
"""

from __future__ import annotations

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


async def act_then_record[T](
    *,
    spill: LocalSpill | None,
    journal: Any,
    event: JournalEvent,
    action: Callable[[], Awaitable[T]],
) -> T:
    """Write ahead to the spill, run `action`, then record `event` in the journal.

    Returns the action's result. If the action raises, that exception is re-raised after the
    audit attempt (a lost audit record is attached to it as a note, class names only).

    Raises:
        AuditRecordLost: the action succeeded but the journal and the spill both failed.
    """
    token, spill_error = _try_spill(spill, event)
    try:
        result = await action()
    except BaseException as exc:
        journal_error = _try_journal(journal, event)
        if journal_error is None:
            _discard_quietly(spill, token)
        elif token is None:
            exc.add_note(
                f"audit record {event.journal_event_id} lost: "
                f"journal={journal_error}, spill={spill_error}"
            )
        raise
    journal_error = _try_journal(journal, event)
    if journal_error is None:
        _discard_quietly(spill, token)
        return result
    if token is not None:
        return result  # the record waits in the spill until replay
    raise AuditRecordLost(
        journal_event_id=event.journal_event_id,
        journal_error=journal_error,
        spill_error=spill_error,
    )


__all__ = ["AuditRecordLost", "act_then_record", "record_after"]
