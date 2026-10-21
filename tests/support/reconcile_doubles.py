"""Journal doubles for the risk-first / spill tests (Phase 20, plan 20-08).

Three duck-typed journals with the one surface every controller uses, `record(event)`:

- `RaisingJournal`: every `record` call raises (a database outage that never ends).
- `RecordingJournal`: keeps events by id with the real journal's replay rule: the same id with
  the same identity fields is a no-op, the same id with different fields raises
  `JournalConflict`. `get(id)` mirrors `PgJournalStore.get`.
- `FlakyJournal`: fails the first `fail_times` calls, then behaves like `RecordingJournal`.

None of them touches a database or the network.
"""

from __future__ import annotations

from src.domain.journal import JournalEvent
from src.persistence.errors import JournalConflict, StoreUnavailable

# Same identity fields the real journal compares on a replay (src/persistence/journal.py).
_IDENTITY_FIELDS: tuple[str, ...] = (
    "event_type",
    "entity_type",
    "entity_id",
    "correlation_id",
    "signal_id",
    "trade_plan_id",
    "approval_id",
    "order_id",
    "position_id",
    "payload_json",
)


class RaisingJournal:
    """A journal whose `record` always raises `StoreUnavailable`."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self._exc = exc
        self.attempts = 0

    def record(self, event: JournalEvent) -> None:
        self.attempts += 1
        raise self._exc or StoreUnavailable("PostgreSQL unavailable during transaction")


class RecordingJournal:
    """An in-memory journal with the real replay rule (identical no-op, different conflict)."""

    def __init__(self) -> None:
        self.events: list[JournalEvent] = []
        self.attempts = 0
        self._by_id: dict[str, JournalEvent] = {}

    def record(self, event: JournalEvent) -> None:
        self.attempts += 1
        existing = self._by_id.get(event.journal_event_id)
        if existing is None:
            self._by_id[event.journal_event_id] = event
            self.events.append(event)
            return
        differing = [n for n in _IDENTITY_FIELDS if getattr(existing, n) != getattr(event, n)]
        if differing:
            raise JournalConflict(
                f"journal event {event.journal_event_id} already exists with different "
                f"fields: {', '.join(differing)}"
            )

    def get(self, journal_event_id: str) -> JournalEvent | None:
        return self._by_id.get(journal_event_id)

    def preload(self, event: JournalEvent) -> None:
        """Put an event in the journal without counting an attempt (test setup)."""
        self._by_id[event.journal_event_id] = event
        self.events.append(event)


class FlakyJournal(RecordingJournal):
    """Fails the first `fail_times` `record` calls with `StoreUnavailable`, then records."""

    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self._remaining_failures = fail_times

    def record(self, event: JournalEvent) -> None:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            self.attempts += 1
            raise StoreUnavailable("PostgreSQL unavailable during transaction")
        super().record(event)


__all__ = ["RaisingJournal", "RecordingJournal", "FlakyJournal"]
