"""PostgreSQL approval store (Phase 17, D-01/D-02/D-03/D-06/D-17/D-26, APRV-02, F-404, SC1).

`PgApprovalStore` is the durable implementation of the approval callables the Telegram
callback layer already depends on, with no signature change:

  - `lookup_by_token_hash(token_hash)`  -> `LookupByTokenHash` (replay layer, receiver)
  - `save(approval)`                    -> `SaveApproval`
  - `save_atomic(approval, mapping)`    -> `SaveAtomic` (decision + mapping, ONE transaction)
  - `lookup_by_short_id(short_id)`      -> `LookupByShortId`

plus the writers the sender and tests need: `insert_pending`, `record_short_id_mapping`, `get`.

Correctness comes from PostgreSQL, never from Python (D-17, D-26). A decision is a conditional
`UPDATE approvals ... WHERE approval_id = :id AND status = 'PENDING'` inside a SAVEPOINT:

  - 0 rows updated: someone else decided this approval first (a replay, a lost cross-process
    race). The stored row is returned inside `ApprovalAlreadyDecided`, which
    `src.approval.replay.resolve_callback` resolves to replay-to-existing or INVALIDATED.
  - `uq_approvals_one_decided_per_plan` violated: a DIFFERENT approval of the same plan (the SKIP
    row when APPROVE won, or the reverse) was already decided. The savepoint rolls back, the
    decided row is read back and returned inside `ApprovalAlreadyDecided`; the losing row stays
    PENDING. The index also refuses a bypassing raw-SQL writer (Pitfall 13).

The short-id mapping is insert-then-verify (research C16): `ON CONFLICT (short_id) DO NOTHING`
followed by a re-read that compares the stored `(signal_id, trade_plan_id)`. A short id bound to
a different plan raises `ShortIdRebindingRefused`; inside `save_atomic` that rolls the decision
back as a whole (migration 0003: re-plans fail closed instead of silently rebinding).

`approved_quantity` (D078, 19-REVIEW WR-01) is part of the request identity and is written once
with the PENDING row: `insert_pending` refuses a value with more than 18 fractional digits
(`PrecisionError`, never rounded, because NUMERIC(38,18) would round it, possibly upward). A
decision updates only `result`, `status` and `acted_at_utc`, so it never rewrites the stored
quantity.

This store never consumes an approval; consumption belongs to the execution-state transaction
(`PgExecutionStateStore.consume_and_record_entry_intent`). The raw approval token is never
stored, logged or put in an error message (only `approval_token_hash`; T-17-25). An unreachable
database raises `StoreUnavailable` from the unit of work; there is no retry loop (F-406).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.approval.mapping import ShortIdMapping
from src.approval.replay import ApprovalAlreadyDecided
from src.db.mappers import (
    approval_from_row,
    approval_to_row,
    short_id_mapping_to_row,
)
from src.db.models import ApprovalRow, ShortIdMappingRow
from src.domain.approval import Approval
from src.domain.canonical import quantize_for_storage
from src.domain.enums import ApprovalResult
from src.persistence.errors import (
    ParentRowMissing,
    PrecisionError,
    RowConflict,
    ShortIdRebindingRefused,
)
from src.persistence.uow import OperationalDatabase

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
_SQLSTATE_UNIQUE_VIOLATION = "23505"
_ONE_DECIDED_PER_PLAN = "uq_approvals_one_decided_per_plan"
_TOKEN_HASH_UNIQUE = "uq_approvals_token_hash"
_MAPPING_PAIR_UNIQUE = "uq_short_id_mapping_signal_trade_plan"

# Fields that identify an approval request. The decision, the consumption state and the
# Telegram message id evolve after insertion, so a repeated `insert_pending` is compared on
# the identity of the request only.
_IDENTITY_FIELDS: tuple[str, ...] = (
    "trade_plan_id",
    "signal_id",
    "action",
    "approval_token_hash",
    "requested_at_utc",
    "request_hash",
    "approved_quantity",
)


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else "unknown constraint"


def _approval_values(approval: Approval) -> dict[str, Any]:
    """Column values of the mapped row (the mapper is the only domain -> row path)."""
    row = approval_to_row(approval)
    return {column.key: getattr(row, column.key) for column in ApprovalRow.__table__.columns}


class PgApprovalStore:
    """Durable approvals with DB-enforced single decision and race-safe replay."""

    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db

    # ------------------------------------------------------------------ reads

    def lookup_by_token_hash(self, token_hash: str) -> Approval | None:
        """Return the approval bound to `token_hash`, or None (a wrong token)."""
        with self._db.transaction() as session:
            row = session.execute(
                select(ApprovalRow).where(ApprovalRow.approval_token_hash == token_hash)
            ).scalar_one_or_none()
            return None if row is None else approval_from_row(row)

    def get(self, approval_id: str) -> Approval | None:
        """Return the stored approval, or None when the id is unknown."""
        with self._db.transaction() as session:
            row = session.get(ApprovalRow, approval_id)
            return None if row is None else approval_from_row(row)

    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None:
        """Return `(signal_id, trade_plan_id)` for a short id, or None when unknown."""
        with self._db.transaction() as session:
            row = session.get(ShortIdMappingRow, short_id)
            return None if row is None else (row.signal_id, row.trade_plan_id)

    # ----------------------------------------------------------------- writes

    def insert_pending(self, approval: Approval) -> None:
        """Insert a PENDING approval; replaying the same request is a no-op.

        Raises:
            ValueError: the approval is not PENDING (decisions go through `save_atomic`).
            PrecisionError: `approved_quantity` has more than 18 fractional digits (D078).
            RowConflict: the approval id exists with a different request, or the token hash is
                already bound to a different approval.
            ParentRowMissing: the signal or trade plan row does not exist yet.
        """
        if approval.status != ApprovalResult.PENDING:
            raise ValueError("insert_pending requires a PENDING approval")
        quantity = approval.approved_quantity
        if quantity is not None and quantize_for_storage(quantity) != quantity:
            # NUMERIC(38,18) would round it, possibly above the issued quantity: refuse (D078).
            raise PrecisionError("approvals.approved_quantity: more than 18 fractional digits")
        values = _approval_values(approval)
        with self._db.transaction() as session:
            try:
                inserted = session.execute(
                    pg_insert(ApprovalRow)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["approval_id"])
                    .returning(ApprovalRow.approval_id)
                ).first()
            except IntegrityError as exc:
                sqlstate = getattr(exc.orig, "sqlstate", None)
                name = _constraint_name(exc)
                if sqlstate == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                    raise ParentRowMissing(
                        f"approval {approval.approval_id}: parent row missing ({name})"
                    ) from exc
                raise RowConflict(
                    f"approval {approval.approval_id}: constraint violated ({name})"
                ) from exc
            if inserted is not None:
                return
            existing = session.get(ApprovalRow, approval.approval_id)
            if existing is None:
                # Not reachable while the primary key holds; never guess (fail closed).
                raise RowConflict(f"approval {approval.approval_id}: conflicting row not visible")
            differing = [
                name for name in _IDENTITY_FIELDS if getattr(existing, name) != values[name]
            ]
            if differing:
                raise RowConflict(
                    f"approval {approval.approval_id} already exists with different "
                    f"fields: {', '.join(differing)}"
                )

    def record_short_id_mapping(
        self, mapping: ShortIdMapping, *, tx: Session | None = None
    ) -> None:
        """Insert the short-id mapping, or verify the stored pair is identical.

        Raises:
            ShortIdRebindingRefused: the short id (or the same signal/plan pair) is already
                bound to something different. Never silently rebinds (research C16).
        """
        if tx is not None:
            self._record_mapping(tx, mapping)
            return
        with self._db.transaction() as session:
            self._record_mapping(session, mapping)

    def save(self, approval: Approval) -> None:
        """`SaveApproval`: persist a decision without a mapping."""
        self.save_atomic(approval, None)

    def save_atomic(
        self,
        approval: Approval,
        mapping: ShortIdMapping | None,
        *,
        after_decide: Callable[[Session, Approval], None] | None = None,
    ) -> None:
        """Decide a PENDING approval and record its short-id mapping in ONE transaction.

        `after_decide(session, approval)` (Phase 21, plan 21-15; D-16, D-17) is optional and
        None by default, so every existing caller (paper SHADOW) behaves as before. When given,
        it runs inside the SAME transaction right after the decision is applied and before the
        mapping insert; any exception it raises rolls the decision back as a whole, so the
        approval stays PENDING. It is not called when the decision itself is refused
        (`ApprovalAlreadyDecided`, `RowConflict`). The hook must not commit or roll back.

        Raises:
            ApprovalAlreadyDecided: the approval (or another approval of the same plan) was
                already decided; `existing` is the stored decided row. Nothing is written.
            ShortIdRebindingRefused: the mapping would rebind a short id; the decision rolls back.
            RowConflict: the approval row does not exist.
            ValueError: `approval` is still PENDING.
        """
        if approval.status == ApprovalResult.PENDING:
            raise ValueError("save_atomic requires a decided approval")
        with self._db.transaction() as session:
            self._decide(session, approval)
            if after_decide is not None:
                after_decide(session, approval)
            if mapping is not None:
                self._record_mapping(session, mapping)

    # --------------------------------------------------------------- internals

    @staticmethod
    def _decide(session: Session, approval: Approval) -> None:
        try:
            with session.begin_nested():
                updated = session.execute(
                    update(ApprovalRow)
                    .where(
                        ApprovalRow.approval_id == approval.approval_id,
                        ApprovalRow.status == ApprovalResult.PENDING.value,
                    )
                    .values(
                        result=approval.result.value,
                        status=approval.status.value,
                        acted_at_utc=approval.acted_at_utc,
                    )
                )
        except IntegrityError as exc:
            name = _constraint_name(exc)
            if name != _ONE_DECIDED_PER_PLAN:
                raise RowConflict(
                    f"approval {approval.approval_id}: constraint violated ({name})"
                ) from exc
            decided = session.execute(
                select(ApprovalRow).where(
                    ApprovalRow.trade_plan_id == approval.trade_plan_id,
                    ApprovalRow.status != ApprovalResult.PENDING.value,
                )
            ).scalar_one_or_none()
            if decided is None:
                raise RowConflict(
                    f"approval {approval.approval_id}: decided row for the plan not visible"
                ) from exc
            raise ApprovalAlreadyDecided(approval_from_row(decided)) from exc
        if updated.rowcount == 1:  # type: ignore[attr-defined]
            return
        current = session.get(ApprovalRow, approval.approval_id)
        if current is None:
            raise RowConflict(f"approval {approval.approval_id}: row does not exist")
        if current.status == ApprovalResult.PENDING.value:
            # A conditional update on a PENDING row cannot match zero rows; never guess.
            raise RowConflict(f"approval {approval.approval_id}: decision not applied")
        raise ApprovalAlreadyDecided(approval_from_row(current))

    @staticmethod
    def _record_mapping(session: Session, mapping: ShortIdMapping) -> None:
        values = {
            column.key: getattr(short_id_mapping_to_row(mapping), column.key)
            for column in ShortIdMappingRow.__table__.columns
        }
        try:
            inserted = session.execute(
                pg_insert(ShortIdMappingRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["short_id"])
                .returning(ShortIdMappingRow.short_id)
            ).first()
        except IntegrityError as exc:
            name = _constraint_name(exc)
            if name == _MAPPING_PAIR_UNIQUE:
                raise ShortIdRebindingRefused(
                    f"short id {mapping.short_id}: signal and plan already bound to another "
                    "short id"
                ) from exc
            if getattr(exc.orig, "sqlstate", None) == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                raise ParentRowMissing(
                    f"short id {mapping.short_id}: parent row missing ({name})"
                ) from exc
            raise RowConflict(f"short id {mapping.short_id}: constraint violated ({name})") from exc
        if inserted is not None:
            return
        existing = session.get(ShortIdMappingRow, mapping.short_id)
        if existing is None:
            # Not reachable while the primary key holds; never guess (fail closed).
            raise RowConflict(f"short id {mapping.short_id}: conflicting row not visible")
        if (existing.signal_id, existing.trade_plan_id) != (
            mapping.signal_id,
            mapping.trade_plan_id,
        ):
            raise ShortIdRebindingRefused(
                f"short id {mapping.short_id} is already bound to a different signal or plan"
            )


if TYPE_CHECKING:
    # mypy-only conformance: fails the type check if any callback surface drifts (D-02).
    from src.adapters.telegram_callbacks import LookupByShortId, SaveAtomic
    from src.approval.replay import LookupByTokenHash, SaveApproval

    def _conforms(
        store: PgApprovalStore,
    ) -> tuple[LookupByTokenHash, SaveApproval, SaveAtomic, LookupByShortId]:
        return (
            store.lookup_by_token_hash,
            store.save,
            store.save_atomic,
            store.lookup_by_short_id,
        )


__all__ = ["PgApprovalStore"]
