"""PostgreSQL journal store (Phase 17, D-01/D-02/D-03/D-10, F-202, F-412, SC1).

`PgJournalStore` is the production implementation of the project journal:

  - `record(event)` commits ONE event in its own transaction. Its signature is exactly
    what every journal-first controller (`LiveEnablementController`, `SafeModeController`,
    `OrphanSweeper`, the health probes, the kill-gate recorder) and the Telegram callback
    receipt (`JournalReceipt`) already call, so none of them changes.
  - `append(tx, event)` writes inside a caller-owned unit of work, so a journal event and
    the row it describes commit together or not at all (D-03). Parents must be inserted
    first in the same unit of work (D-07); a missing parent is `ParentRowMissing`.
  - `get` / `list_by_correlation` read back through `journal_from_row`.

Replay is idempotent by id (D-10): `INSERT ... ON CONFLICT (journal_event_id) DO NOTHING`.
When nothing was inserted the stored row is re-read and compared on the identity fields
and the payload; `occurred_at_utc` and `created_at_utc` are excluded because a redelivered
callback carries a new delivery time with the same deterministic id and payload. A
different event under an existing id raises `JournalConflict` instead of being silently
dropped (F-412, T-17-20); the message names the id and the differing FIELD NAMES only,
never payload contents (T-17-21).

There is deliberately no update or delete method: the journal is append-only, and the
`trg_journal_events_append_only` trigger refuses a writer that bypasses this class.

A failed `append` inside a caller's unit of work leaves that transaction aborted (the
database rolled the failed statement back); the caller propagates the exception and the
unit of work rolls back as a whole.

An unreachable database raises `StoreUnavailable` (from the unit of work), a distinct
exception callers translate to NO_TRADE / SAFE_MODE (D-04, Pitfall 9). There is no retry
loop here (F-406).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.mappers import journal_from_row, journal_to_row
from src.db.models import JournalEventRow
from src.domain.journal import JournalEvent
from src.persistence.errors import JournalConflict, ParentRowMissing
from src.persistence.uow import OperationalDatabase

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"

# Fields compared when an id already exists. `occurred_at_utc` and `created_at_utc`
# are intentionally absent (a redelivery has a new delivery time, same identity).
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


def _row_values(event: JournalEvent) -> dict[str, Any]:
    """Column values of the mapped row (the mapper is the only domain -> row path)."""
    row = journal_to_row(event)
    return {column.key: getattr(row, column.key) for column in JournalEventRow.__table__.columns}


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else "unknown constraint"


class PgJournalStore:
    """Durable, append-only, replay-idempotent journal on PostgreSQL."""

    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db

    def record(self, event: JournalEvent) -> None:
        """Commit one event in its own transaction (the `JournalLike.record` surface)."""
        with self._db.transaction() as tx:
            self.append(tx, event)

    def append(self, tx: Session, event: JournalEvent) -> None:
        """Write one event inside the caller's unit of work.

        Raises:
            JournalConflict: the id exists with a different identity field or payload.
            ParentRowMissing: a referenced signal, plan, approval, order or position row
                does not exist yet (insert parents first in the same unit of work).
        """
        values = _row_values(event)
        try:
            inserted = tx.execute(
                pg_insert(JournalEventRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["journal_event_id"])
                .returning(JournalEventRow.journal_event_id)
            ).first()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                raise ParentRowMissing(
                    f"journal event {event.journal_event_id}: parent row missing "
                    f"({_constraint_name(exc)})"
                ) from exc
            raise
        if inserted is not None:
            return
        self._verify_replay(tx, event, values)

    def get(self, journal_event_id: str) -> JournalEvent | None:
        """Return the stored event, or None when the id is unknown."""
        with self._db.transaction() as tx:
            row = tx.execute(
                select(JournalEventRow).where(JournalEventRow.journal_event_id == journal_event_id)
            ).scalar_one_or_none()
            return None if row is None else journal_from_row(row)

    def list_by_correlation(self, correlation_id: str) -> list[JournalEvent]:
        """Events of one correlation ordered by `occurred_at_utc` then id."""
        with self._db.transaction() as tx:
            rows = tx.execute(
                select(JournalEventRow)
                .where(JournalEventRow.correlation_id == correlation_id)
                .order_by(JournalEventRow.occurred_at_utc, JournalEventRow.journal_event_id)
            ).scalars()
            return [journal_from_row(row) for row in rows]

    @staticmethod
    def _verify_replay(tx: Session, event: JournalEvent, values: dict[str, Any]) -> None:
        """The id already exists: it must be the same event, otherwise fail loudly."""
        existing = tx.execute(
            select(JournalEventRow).where(
                JournalEventRow.journal_event_id == event.journal_event_id
            )
        ).scalar_one_or_none()
        if existing is None:
            # Not reachable while the append-only trigger holds; never guess (fail closed).
            raise JournalConflict(
                f"journal event {event.journal_event_id}: conflicting row not visible"
            )
        differing = [name for name in _IDENTITY_FIELDS if getattr(existing, name) != values[name]]
        if differing:
            raise JournalConflict(
                f"journal event {event.journal_event_id} already exists with different "
                f"fields: {', '.join(differing)}"
            )


if TYPE_CHECKING:
    # mypy-only conformance: fails the type check if any journal surface drifts (D-02).
    # No new Protocol is invented; each consumer's own `JournalLike` is the contract.
    from src.adapters.telegram_callbacks import JournalReceipt
    from src.analytics.killgate import JournalLike as KillGateJournalLike
    from src.execution.enablement import JournalLike as EnablementJournalLike
    from src.ops.health import JournalLike as HealthJournalLike
    from src.reconcile.safe_mode import JournalLike as SafeModeJournalLike
    from src.reconcile.sweeper import JournalLike as SweeperJournalLike

    def _conforms(
        store: PgJournalStore,
    ) -> tuple[
        EnablementJournalLike,
        SafeModeJournalLike,
        SweeperJournalLike,
        HealthJournalLike,
        KillGateJournalLike,
        JournalReceipt,
    ]:
        return store, store, store, store, store, store.record


__all__ = ["PgJournalStore"]
