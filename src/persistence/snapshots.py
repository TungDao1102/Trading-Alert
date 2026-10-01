"""PostgreSQL store for the per-plan exchange constraint snapshot (Phase 17-13, EXEC-04, D-18/D-19).

`PgPlanConstraintSnapshotStore` persists the exact constraints used to size a trade plan
(`src.execution.constraint_snapshot.PlanConstraintSnapshot`) as canonical JSON plus its sha256.

  - `record` is write-once evidence: `INSERT ... ON CONFLICT (trade_plan_id) DO NOTHING`, then the
    stored row is compared with the snapshot (sha256 and canonical JSON). Replaying the same
    snapshot is a no-op; a different snapshot for the same plan is `RowConflict`. The append-only
    trigger of migration 0004 refuses any UPDATE or DELETE that bypasses this class, and a missing
    trade plan is `ParentRowMissing`.
  - `get` parses the stored JSON, recomputes its digest and checks the denormalized columns
    against it. A digest or column mismatch is `RowConflict` (fail closed, T-17-35): corrupted or
    tampered evidence is never returned as data.
  - `is_valid_for_live` delegates to `snapshot_is_valid_for_live`. A missing plan, an INCOMPLETE
    snapshot (margin type, leverage and equity stay UNKNOWN until Phases 21-22), a stale or
    future-dated capture, and any row that fails verification are all False (D-19).

The digest is plan EVIDENCE only; it is never an input to `plan_hash` (D-18). There is no update
or delete method. An unreachable database raises `StoreUnavailable` from the unit of work.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import PlanConstraintSnapshotRow
from src.execution.constraint_snapshot import (
    UNKNOWN,
    PlanConstraintSnapshot,
    canonical_json,
    parse_snapshot_json,
    snapshot_is_valid_for_live,
    snapshot_sha256,
)
from src.persistence.errors import ParentRowMissing, RowConflict
from src.persistence.uow import OperationalDatabase

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else "unknown constraint"


def _row_values(snapshot: PlanConstraintSnapshot) -> dict[str, object]:
    """Column values of the stored row: scalars as text, unknown values as `UNKNOWN`."""
    return {
        "trade_plan_id": snapshot.trade_plan_id,
        "symbol": snapshot.symbol,
        "working_type": snapshot.working_type,
        "margin_type": UNKNOWN if snapshot.margin_type is None else snapshot.margin_type,
        "leverage": UNKNOWN if snapshot.leverage is None else str(snapshot.leverage),
        "equity_used": UNKNOWN if snapshot.equity_used is None else str(snapshot.equity_used),
        "live_inputs_status": snapshot.live_inputs_status.value,
        "constraints_observed_at_utc": snapshot.constraints_observed_at_utc,
        "captured_at_utc": snapshot.captured_at_utc,
        "snapshot_json": canonical_json(snapshot),
        "snapshot_sha256": snapshot_sha256(snapshot),
    }


def _fetch(session: Session, trade_plan_id: str) -> PlanConstraintSnapshotRow | None:
    return session.execute(
        select(PlanConstraintSnapshotRow).where(
            PlanConstraintSnapshotRow.trade_plan_id == trade_plan_id
        )
    ).scalar_one_or_none()


def _verified_snapshot(row: PlanConstraintSnapshotRow) -> PlanConstraintSnapshot:
    """Parse a stored row and prove its digest and denormalized columns match its JSON."""
    plan_id = row.trade_plan_id
    snapshot = parse_snapshot_json(row.snapshot_json)  # ValueError on a malformed document
    if snapshot_sha256(snapshot) != row.snapshot_sha256:
        raise RowConflict(f"plan constraint snapshot {plan_id}: stored sha256 does not match")
    expected = _row_values(snapshot)
    stored = {name: getattr(row, name) for name in expected}
    differing = [name for name in expected if stored[name] != expected[name]]
    if differing:
        raise RowConflict(
            f"plan constraint snapshot {plan_id}: stored columns differ from the JSON "
            f"({', '.join(differing)})"
        )
    return snapshot


class PgPlanConstraintSnapshotStore:
    """Write-once, hash-verified per-plan constraint snapshots on PostgreSQL."""

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

    def record(self, snapshot: PlanConstraintSnapshot, *, tx: Session | None = None) -> None:
        """Store the snapshot once. Replay is a no-op; a different snapshot is `RowConflict`.

        Raises:
            ParentRowMissing: the trade plan row does not exist (insert it first).
            RowConflict: a different snapshot is already stored for this plan.
        """
        values = _row_values(snapshot)
        plan_id = snapshot.trade_plan_id
        with self._unit(tx) as session:
            try:
                inserted = session.execute(
                    pg_insert(PlanConstraintSnapshotRow)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["trade_plan_id"])
                    .returning(PlanConstraintSnapshotRow.trade_plan_id)
                ).first()
            except IntegrityError as exc:
                if getattr(exc.orig, "sqlstate", None) == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                    raise ParentRowMissing(
                        f"plan constraint snapshot {plan_id}: trade plan row missing "
                        f"({_constraint_name(exc)})"
                    ) from exc
                raise
            if inserted is not None:
                return
            existing = _fetch(session, plan_id)
            if (
                existing is None
                or existing.snapshot_sha256 != values["snapshot_sha256"]
                or existing.snapshot_json != values["snapshot_json"]
            ):
                raise RowConflict(
                    f"plan constraint snapshot {plan_id}: a different snapshot is already stored"
                )

    def get(
        self, trade_plan_id: str, *, tx: Session | None = None
    ) -> PlanConstraintSnapshot | None:
        """Return the verified snapshot, or None when the plan has none.

        Raises:
            RowConflict: the stored digest or a denormalized column does not match the JSON.
            ValueError: the stored JSON is not a valid snapshot document.
        """
        with self._unit(tx) as session:
            row = _fetch(session, trade_plan_id)
            return None if row is None else _verified_snapshot(row)

    def is_valid_for_live(
        self,
        trade_plan_id: str,
        *,
        now_utc: datetime,
        ttl: timedelta,
        tx: Session | None = None,
    ) -> bool:
        """True only for a stored, verified, COMPLETE and fresh snapshot (D-19).

        A missing plan, an INCOMPLETE snapshot, a stale or future-dated capture and a row that
        fails verification are all False (fail closed).
        """
        try:
            snapshot = self.get(trade_plan_id, tx=tx)
        except (RowConflict, ValueError):
            return False
        if snapshot is None:
            return False
        return snapshot_is_valid_for_live(snapshot, now_utc=now_utc, ttl=ttl)


__all__ = ["PgPlanConstraintSnapshotStore"]
