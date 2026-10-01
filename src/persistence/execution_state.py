"""PostgreSQL execution-intent store (Phase 17, D-13/D-14/D-15, EXEC-03, F-126).

`PgExecutionStateStore` satisfies `src.execution.intent_store.ExecutionIntentStore`.
Each method is ONE explicit transaction (D-03), written with SQLAlchemy Core
statements against the ORM tables:

  - consume: `INSERT ... ON CONFLICT (approval_id, role) DO NOTHING RETURNING` plus a
    conditional `UPDATE approvals` in the SAME transaction. The conflict target is
    named; an untargeted `ON CONFLICT DO NOTHING` would also swallow a uniqueness
    violation on a DIFFERENT arbiter (a second approval for the same plan, a reused
    client id), hiding a second-entry attempt, so those surface as
    `IntentStateConflict` and the transaction rolls back (no intent row survives).
  - status writes are conditional UPDATEs guarded by the allowed predecessors
    (`ALLOWED_PREDECESSORS`); a rowcount of 0 raises `IntentStateConflict`.

The correctness line is the database constraint, not Python: a lost race, a replay
and a restart all end in the same stored row (D-15, D-17). Decimals stay Decimal
and every timestamp the store writes is the caller's injected UTC `now_utc`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from src.db.models import ApprovalRow, ExecutionIntentRow
from src.domain.enums import (
    ApprovalConsumptionStatus,
    ApprovalResult,
    ExecutionIntentStatus,
    OrderRole,
)
from src.execution.intent_store import ALLOWED_PREDECESSORS, IntentRecord, RecordedOutcome
from src.persistence.errors import IntentStateConflict, ParentRowMissing
from src.persistence.uow import OperationalDatabase

_SQLSTATE_UNIQUE_VIOLATION = "23505"
_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else "unknown constraint"


def _translate_integrity(exc: IntegrityError, *, what: str) -> Exception:
    """Map an `IntegrityError` to a typed persistence error (names only, no values)."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    name = _constraint_name(exc)
    if sqlstate == _SQLSTATE_FOREIGN_KEY_VIOLATION:
        return ParentRowMissing(f"{what}: parent row missing ({name})")
    return IntentStateConflict(f"{what}: constraint violated ({name})")


def _to_record(row: ExecutionIntentRow) -> IntentRecord:
    outcome: RecordedOutcome | None = None
    if row.outcome_recorded:
        if row.outcome_is_no_trade is None or row.outcome_reason_code is None:
            raise IntentStateConflict("incoherent recorded outcome on execution intent")
        outcome = RecordedOutcome(
            is_no_trade=row.outcome_is_no_trade, reason_code=row.outcome_reason_code
        )
    return IntentRecord(
        approval_id=row.approval_id,
        role=row.role,
        trade_plan_id=row.trade_plan_id,
        plan_hash=row.plan_hash,
        client_order_id=row.client_order_id,
        algo_client_id=row.algo_client_id,
        symbol=row.symbol,
        side=row.side,
        intended_quantity=row.intended_quantity,
        intended_price=row.intended_price,
        intent_status=ExecutionIntentStatus(row.intent_status),
        exchange_order_id=row.exchange_order_id,
        exchange_status=row.exchange_status,
        outcome=outcome,
        intended_at_utc=row.intended_at_utc,
        sent_at_utc=row.sent_at_utc,
        resolved_at_utc=row.resolved_at_utc,
        updated_at_utc=row.updated_at_utc,
    )


def _predecessors(target: ExecutionIntentStatus) -> list[str]:
    allowed = ALLOWED_PREDECESSORS[target]
    if not allowed:
        raise IntentStateConflict(f"status {target.value} cannot be written after creation")
    return sorted(status.value for status in allowed)


class PgExecutionStateStore:
    """Durable approval consumption and write-ahead execution intents."""

    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db

    def get_entry(self, *, approval_id: str) -> IntentRecord | None:
        with self._db.transaction() as session:
            row = session.execute(
                select(ExecutionIntentRow).where(
                    ExecutionIntentRow.approval_id == approval_id,
                    ExecutionIntentRow.role == OrderRole.ENTRY.value,
                )
            ).scalar_one_or_none()
            return None if row is None else _to_record(row)

    def consume_and_record_entry_intent(
        self,
        *,
        approval_id: str,
        trade_plan_id: str,
        plan_hash: str,
        client_order_id: str,
        symbol: str,
        side: str,
        intended_quantity: Decimal,
        intended_price: Decimal,
        now_utc: datetime,
    ) -> bool:
        """Insert the ENTRY intent and consume the approval in one transaction.

        Returns True for the winner and False when the (approval_id, ENTRY) row already
        exists (replay or lost race). Raises `IntentStateConflict` when the approval row
        cannot be consumed (missing, not APPROVED, already consumed) or another unique
        arbiter is violated, and `ParentRowMissing` when a parent row is absent.
        """
        values: dict[str, Any] = {
            "approval_id": approval_id,
            "role": OrderRole.ENTRY.value,
            "trade_plan_id": trade_plan_id,
            "plan_hash": plan_hash,
            "client_order_id": client_order_id,
            "algo_client_id": None,
            "symbol": symbol,
            "side": side,
            "intended_quantity": intended_quantity,
            "intended_price": intended_price,
            "intent_status": ExecutionIntentStatus.INTENDED.value,
            "outcome_recorded": False,
            "intended_at_utc": now_utc,
            "updated_at_utc": now_utc,
        }
        try:
            with self._db.transaction() as session:
                inserted = session.execute(
                    pg_insert(ExecutionIntentRow)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["approval_id", "role"])
                    .returning(ExecutionIntentRow.approval_id)
                ).first()
                if inserted is None:
                    return False
                stamped = session.execute(
                    update(ApprovalRow)
                    .where(
                        ApprovalRow.approval_id == approval_id,
                        ApprovalRow.consumption_status
                        == ApprovalConsumptionStatus.UNCONSUMED.value,
                        ApprovalRow.status == ApprovalResult.APPROVED.value,
                    )
                    .values(
                        consumption_status=ApprovalConsumptionStatus.CONSUMED.value,
                        consumed_at_utc=now_utc,
                    )
                )
                if stamped.rowcount != 1:  # type: ignore[attr-defined]
                    # Raised inside the transaction: the intent insert rolls back too.
                    raise IntentStateConflict(
                        "approval cannot be consumed (missing, not APPROVED or already consumed)"
                    )
                return True
        except IntegrityError as exc:
            raise _translate_integrity(exc, what="consume approval") from exc

    def mark_sent(self, *, approval_id: str, role: str, now_utc: datetime) -> None:
        self._advance(
            approval_id=approval_id,
            role=role,
            target=ExecutionIntentStatus.SENT,
            values={"sent_at_utc": now_utc},
            now_utc=now_utc,
        )

    def record_result(
        self,
        *,
        approval_id: str,
        role: str,
        status: ExecutionIntentStatus,
        exchange_order_id: str | None,
        exchange_status: str | None,
        now_utc: datetime,
    ) -> None:
        resolved = None if status == ExecutionIntentStatus.UNKNOWN else now_utc
        self._advance(
            approval_id=approval_id,
            role=role,
            target=status,
            values={
                "exchange_order_id": exchange_order_id,
                "exchange_status": exchange_status,
                "resolved_at_utc": resolved,
            },
            now_utc=now_utc,
        )

    def finalize_entry_outcome(
        self,
        *,
        approval_id: str,
        is_no_trade: bool,
        reason_code: str,
        now_utc: datetime,
    ) -> None:
        """Persist the exact `ExecutionOutcome` fields on the ENTRY row (once)."""
        try:
            with self._db.transaction() as session:
                result = session.execute(
                    update(ExecutionIntentRow)
                    .where(
                        ExecutionIntentRow.approval_id == approval_id,
                        ExecutionIntentRow.role == OrderRole.ENTRY.value,
                        ExecutionIntentRow.outcome_recorded.is_(False),
                    )
                    .values(
                        outcome_recorded=True,
                        outcome_is_no_trade=is_no_trade,
                        outcome_reason_code=reason_code,
                        updated_at_utc=now_utc,
                    )
                )
                if result.rowcount != 1:  # type: ignore[attr-defined]
                    raise IntentStateConflict(
                        "entry outcome not recorded (missing row or outcome already recorded)"
                    )
        except IntegrityError as exc:
            raise _translate_integrity(exc, what="finalize entry outcome") from exc

    # ------------------------------------------------------------------ #

    def _advance(
        self,
        *,
        approval_id: str,
        role: str,
        target: ExecutionIntentStatus,
        values: dict[str, Any],
        now_utc: datetime,
    ) -> None:
        """Conditional UPDATE: only an allowed predecessor status may move to `target`."""
        predecessors = _predecessors(target)
        try:
            with self._db.transaction() as session:
                result = session.execute(
                    update(ExecutionIntentRow)
                    .where(
                        ExecutionIntentRow.approval_id == approval_id,
                        ExecutionIntentRow.role == role,
                        ExecutionIntentRow.intent_status.in_(predecessors),
                    )
                    .values(intent_status=target.value, updated_at_utc=now_utc, **values)
                )
                if result.rowcount != 1:  # type: ignore[attr-defined]
                    raise IntentStateConflict(
                        f"illegal intent transition to {target.value} for role {role} "
                        "(missing row or disallowed predecessor status)"
                    )
        except IntegrityError as exc:
            raise _translate_integrity(exc, what=f"record {target.value}") from exc
