"""PostgreSQL store of pending protective actions (Phase 20, plan 20-14, D-19, Q4).

`PgPendingActionStore` persists the explicit state of a protective action the REST gate
refused: `STOP_NOT_SENT`, `PROTECTION_ENTRY_CANCEL_NOT_SENT`, `CLOSE_NOT_SENT`. The row is the
INTENT only (no price, quantity or side), so the table survives a restart without ever
carrying a payload that could be replayed blindly.

  - `record_blocked` inserts the open row of `(plan_hash, kind)` or bumps it (`block_count`,
    `last_blocked_at_utc`, `gate_reason`, `retry_after_until_utc`) in ONE transaction. The open
    row is read `FOR UPDATE`; `uq_pending_protective_actions_open` is the arbiter of a race, and
    the loser gets `RowConflict`.
  - `resolve` and `supersede` close the open row (and only the open row); they answer None when
    nothing is open, so repeating them is harmless.
  - `list_open` returns every PENDING row ordered by `(first_blocked_at_utc, pending_id)`.

There is no delete method. An unreachable database raises `StoreUnavailable` from the unit of
work; there is no retry loop here (the coordinator's next step is the retry, F-406). Who reads
the open rows at start is plan 20-19; the order in which they are served is plan 20-21.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import PendingProtectiveActionRow
from src.execution.pending_actions import (
    PendingAction,
    PendingKind,
    PendingState,
    pending_id_for,
)
from src.persistence.errors import RowConflict
from src.persistence.uow import OperationalDatabase

_SQLSTATE_UNIQUE_VIOLATION = "23505"


def _require_utc_aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC, got offset {value.utcoffset()}")
    return value


def _require_kind(kind: object) -> PendingKind:
    if not isinstance(kind, PendingKind):
        raise ValueError(f"kind must be a PendingKind, got {type(kind).__name__}")
    return kind


def _to_action(row: PendingProtectiveActionRow) -> PendingAction:
    """The domain record of a stored row; a malformed row raises ValueError (fail closed)."""
    return PendingAction(
        pending_id=row.pending_id,
        plan_hash=row.plan_hash,
        trade_plan_id=row.trade_plan_id,
        approval_id=row.approval_id,
        symbol=row.symbol,
        kind=PendingKind(row.pending_kind),
        state=PendingState(row.state),
        gate_reason=row.gate_reason,
        first_blocked_at_utc=row.first_blocked_at_utc,
        last_blocked_at_utc=row.last_blocked_at_utc,
        block_count=row.block_count,
        retry_after_until_utc=row.retry_after_until_utc,
        resolved_at_utc=row.resolved_at_utc,
        resolution_note=row.resolution_note,
    )


class PgPendingActionStore:
    """Durable pending protective actions (see the module docstring)."""

    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db

    @contextmanager
    def _unit(self, tx: Session | None) -> Iterator[Session]:
        """Join the caller's unit of work, or open (and commit) one."""
        if tx is not None:
            yield tx
            return
        with self._db.transaction() as session:
            yield session

    def record_blocked(
        self,
        *,
        plan_hash: str,
        trade_plan_id: str,
        approval_id: str,
        symbol: str,
        kind: PendingKind,
        gate_reason: str,
        retry_after_until_utc: datetime | None,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> PendingAction:
        """Insert the open row of `(plan_hash, kind)` or bump it.

        Raises:
            ValueError: a malformed argument (naive time, unknown kind, free-text reason).
                Nothing is written.
            RowConflict: a concurrent writer opened the same row first (retry on the next
                step). When a caller-owned `tx` is passed it is aborted.
        """
        _require_utc_aware(now_utc, "now_utc")
        kind = _require_kind(kind)
        with self._unit(tx) as session:
            row = self._open_row(session, plan_hash, kind)
            if row is not None:
                bumped = PendingAction(
                    pending_id=row.pending_id,
                    plan_hash=row.plan_hash,
                    trade_plan_id=row.trade_plan_id,
                    approval_id=row.approval_id,
                    symbol=row.symbol,
                    kind=kind,
                    state=PendingState.PENDING,
                    gate_reason=gate_reason,
                    first_blocked_at_utc=row.first_blocked_at_utc,
                    last_blocked_at_utc=max(now_utc, row.last_blocked_at_utc),
                    block_count=row.block_count + 1,
                    retry_after_until_utc=retry_after_until_utc,
                    resolved_at_utc=None,
                    resolution_note=None,
                )
                row.gate_reason = bumped.gate_reason
                row.last_blocked_at_utc = bumped.last_blocked_at_utc
                row.block_count = bumped.block_count
                row.retry_after_until_utc = bumped.retry_after_until_utc
                session.flush()
                return bumped
            opened = PendingAction(
                pending_id=pending_id_for(plan_hash, kind, opened_at_utc=now_utc),
                plan_hash=plan_hash,
                trade_plan_id=trade_plan_id,
                approval_id=approval_id,
                symbol=symbol,
                kind=kind,
                state=PendingState.PENDING,
                gate_reason=gate_reason,
                first_blocked_at_utc=now_utc,
                last_blocked_at_utc=now_utc,
                block_count=1,
                retry_after_until_utc=retry_after_until_utc,
                resolved_at_utc=None,
                resolution_note=None,
            )
            session.add(
                PendingProtectiveActionRow(
                    pending_id=opened.pending_id,
                    plan_hash=opened.plan_hash,
                    trade_plan_id=opened.trade_plan_id,
                    approval_id=opened.approval_id,
                    symbol=opened.symbol,
                    pending_kind=opened.kind.value,
                    state=opened.state.value,
                    gate_reason=opened.gate_reason,
                    first_blocked_at_utc=opened.first_blocked_at_utc,
                    last_blocked_at_utc=opened.last_blocked_at_utc,
                    block_count=opened.block_count,
                    retry_after_until_utc=opened.retry_after_until_utc,
                    resolved_at_utc=None,
                    resolution_note=None,
                )
            )
            try:
                session.flush()
            except IntegrityError as exc:
                if getattr(exc.orig, "sqlstate", None) == _SQLSTATE_UNIQUE_VIOLATION:
                    raise RowConflict(
                        f"pending action {kind.value}: the open row was taken concurrently"
                    ) from exc
                raise
            return opened

    def resolve(
        self,
        *,
        plan_hash: str,
        kind: PendingKind,
        note: str,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> PendingAction | None:
        """Close the open row as RESOLVED; None when no row is open."""
        return self._close(plan_hash, kind, PendingState.RESOLVED, note, now_utc, tx)

    def supersede(
        self,
        *,
        plan_hash: str,
        kind: PendingKind,
        note: str,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> PendingAction | None:
        """Close the open row as SUPERSEDED (it is never to be sent); None when none is open."""
        return self._close(plan_hash, kind, PendingState.SUPERSEDED, note, now_utc, tx)

    def list_open(self, *, tx: Session | None = None) -> tuple[PendingAction, ...]:
        """Every PENDING row, ordered by `(first_blocked_at_utc, pending_id)`.

        Raises:
            ValueError: a stored row is malformed (fail closed, never skipped).
        """
        with self._unit(tx) as session:
            rows = session.execute(
                select(PendingProtectiveActionRow)
                .where(PendingProtectiveActionRow.state == PendingState.PENDING.value)
                .order_by(
                    PendingProtectiveActionRow.first_blocked_at_utc,
                    PendingProtectiveActionRow.pending_id,
                )
            ).scalars()
            return tuple(_to_action(row) for row in rows)

    def _close(
        self,
        plan_hash: str,
        kind: PendingKind,
        state: PendingState,
        note: str,
        now_utc: datetime,
        tx: Session | None,
    ) -> PendingAction | None:
        _require_utc_aware(now_utc, "now_utc")
        kind = _require_kind(kind)
        with self._unit(tx) as session:
            row = self._open_row(session, plan_hash, kind)
            if row is None:
                return None
            closed_at = max(now_utc, row.last_blocked_at_utc)
            closed = PendingAction(
                pending_id=row.pending_id,
                plan_hash=row.plan_hash,
                trade_plan_id=row.trade_plan_id,
                approval_id=row.approval_id,
                symbol=row.symbol,
                kind=kind,
                state=state,
                gate_reason=row.gate_reason,
                first_blocked_at_utc=row.first_blocked_at_utc,
                last_blocked_at_utc=row.last_blocked_at_utc,
                block_count=row.block_count,
                retry_after_until_utc=row.retry_after_until_utc,
                resolved_at_utc=closed_at,
                resolution_note=note,
            )
            row.state = closed.state.value
            row.resolved_at_utc = closed.resolved_at_utc
            row.resolution_note = closed.resolution_note
            session.flush()
            return closed

    @staticmethod
    def _open_row(
        session: Session, plan_hash: str, kind: PendingKind
    ) -> PendingProtectiveActionRow | None:
        return session.execute(
            select(PendingProtectiveActionRow)
            .where(
                PendingProtectiveActionRow.plan_hash == plan_hash,
                PendingProtectiveActionRow.pending_kind == kind.value,
                PendingProtectiveActionRow.state == PendingState.PENDING.value,
            )
            .with_for_update()
        ).scalar_one_or_none()


__all__ = ["PgPendingActionStore"]
