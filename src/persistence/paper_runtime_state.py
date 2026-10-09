"""PostgreSQL runtime state for the paper runtime (Phase 16, plan 16-16, Q-J "journal-only").

User decision Q-J (16-DEC-Q-J.md, 2026-10-09): durable runtime state lives in the existing
`journal_events` table, with no second persistence mechanism, no migration and no change to
`system_state_events`. Every `RuntimeRecord` is one journal event written through
`PgJournalStore.record` (entity type "PaperRuntime", deterministic id from
`src.paper.runtime_state.runtime_event_id`), so:

  - replaying a record is the journal's own idempotent no-op (`ON CONFLICT DO NOTHING`), and
    the same id with different content is a `JournalConflict`, surfaced here as the port's
    `RuntimeRecordConflict` (the message names field names only, never payload contents);
  - the journal is append-only: this class has no update and no delete.

Restore reads are bounded queries over `journal_events`, always restricted to entity type
"PaperRuntime", the correlation prefix `paper:<epoch>:` (the epoch is matched literally, with
LIKE wildcards escaped) and the wanted event types. `last_close_by_pair` is answered by the
database with one row per pair (`DISTINCT ON`), so restore cost does not grow with the history
of processed bars, and `latest_runtime_marker` reads at most two rows. The correlation index is
a plain btree, so the prefix filter is a scan of the journal table filtered by event type, not
an index range read; that is acceptable for the soak journal and adding an index would be the
schema change Q-J ruled out.

The port is synchronous; the runtime wraps it in `asyncio.to_thread` (phase 24 item G4-040 is
still open). An unreachable database raises `StoreUnavailable` (fail closed), never an
in-memory fallback.

This module is deliberately NOT re-exported from `src/paper/__init__.py`, which promises that
the paper package imports no SQLAlchemy.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.sql.elements import ColumnElement

from src.db.models import JournalEventRow
from src.domain.journal import JournalEvent
from src.paper.runtime_state import (
    ENTITY_TYPE,
    RUNTIME_ENTITY_ID,
    RuntimeRecord,
    RuntimeRecordConflict,
    latest_marker,
    record_sort_key,
    runtime_correlation_id,
    runtime_correlation_prefix,
    runtime_entity_id,
    runtime_event_id,
)
from src.paper.vocabulary import RuntimeEventType
from src.persistence.errors import JournalConflict
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

_MARKER_TYPES = (RuntimeEventType.RUNTIME_START.value, RuntimeEventType.RUNTIME_STOP.value)


def _epoch_scope(epoch_id: str) -> ColumnElement[bool]:
    """Rows of one epoch's runtime records: entity type plus the literal correlation prefix."""
    prefix = runtime_correlation_prefix(epoch_id)
    return (JournalEventRow.entity_type == ENTITY_TYPE) & JournalEventRow.correlation_id.startswith(
        prefix, autoescape=True
    )


def _record_from_row(row: JournalEventRow) -> RuntimeRecord:
    """Rebuild a `RuntimeRecord`; the epoch is the second part of the correlation id."""
    parts = row.correlation_id.split(":")
    if len(parts) < 3 or parts[0] != "paper":
        raise ValueError(f"journal event {row.journal_event_id}: not a runtime correlation id")
    symbol: str | None = None
    interval: str | None = None
    if row.entity_id != RUNTIME_ENTITY_ID:
        symbol, interval = row.entity_id.split(":", 1)
    payload = json.loads(row.payload_json) if row.payload_json else {}
    return RuntimeRecord(
        event_type=RuntimeEventType(row.event_type),
        epoch_id=parts[1],
        occurred_at_utc=row.occurred_at_utc,
        symbol=symbol,
        interval=interval,
        payload=payload,
    )


class PgRuntimeState:
    """`RuntimeStatePort` on PostgreSQL, with journal events as the state (Q-J journal-only)."""

    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db
        self._journal = PgJournalStore(db)

    def record(self, record: RuntimeRecord) -> None:
        """Write one record as a journal event; a replay is a no-op, other content conflicts."""
        event = JournalEvent(
            journal_event_id=runtime_event_id(record),
            occurred_at_utc=record.occurred_at_utc,
            event_type=record.event_type.value,
            entity_type=ENTITY_TYPE,
            entity_id=runtime_entity_id(record),
            correlation_id=runtime_correlation_id(record),
            payload_json=record.payload_json,
        )
        try:
            self._journal.record(event)
        except JournalConflict as exc:
            raise RuntimeRecordConflict(str(exc)) from exc

    def last_close_by_pair(self, epoch_id: str) -> Mapping[tuple[str, str], datetime]:
        """The latest processed close per pair: one database row per pair."""
        statement = (
            select(JournalEventRow.entity_id, JournalEventRow.occurred_at_utc)
            .where(
                _epoch_scope(epoch_id),
                JournalEventRow.event_type == RuntimeEventType.PAPER_BAR_PROCESSED.value,
            )
            .distinct(JournalEventRow.entity_id)
            .order_by(JournalEventRow.entity_id, JournalEventRow.occurred_at_utc.desc())
        )
        with self._db.transaction() as tx:
            rows = tx.execute(statement).all()
        out: dict[tuple[str, str], datetime] = {}
        for entity_id, occurred_at in rows:
            if entity_id == RUNTIME_ENTITY_ID or ":" not in entity_id:
                continue
            symbol, interval = entity_id.split(":", 1)
            out[(symbol, interval)] = occurred_at
        return out

    def latest_runtime_marker(self, epoch_id: str) -> RuntimeRecord | None:
        """The last RUNTIME_START or RUNTIME_STOP of the epoch (at most two rows are read)."""
        statement = (
            select(JournalEventRow)
            .where(_epoch_scope(epoch_id), JournalEventRow.event_type.in_(_MARKER_TYPES))
            .order_by(JournalEventRow.occurred_at_utc.desc(), JournalEventRow.journal_event_id)
            .limit(2)
        )
        with self._db.transaction() as tx:
            records = [_record_from_row(row) for row in tx.execute(statement).scalars()]
        return latest_marker(records)

    def records(
        self, epoch_id: str, event_types: Collection[RuntimeEventType] | None = None
    ) -> Sequence[RuntimeRecord]:
        """The epoch's records, optionally of the given types, in the port's total order."""
        statement = select(JournalEventRow).where(_epoch_scope(epoch_id))
        if event_types is not None:
            statement = statement.where(
                JournalEventRow.event_type.in_(sorted(t.value for t in event_types))
            )
        with self._db.transaction() as tx:
            records = [_record_from_row(row) for row in tx.execute(statement).scalars()]
        return sorted(records, key=record_sort_key)


__all__ = ["PgRuntimeState"]
