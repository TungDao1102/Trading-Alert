"""The PostgreSQL stores of the SHADOW chain (Phase 16, plan 16-31, D-04, D-16).

`PgShadowStores` composes the Phase 17 stores behind the one port the running chain uses
(`src/paper/shadow_runtime.py:ShadowRuntimeStores`, which is the `ShadowStores`, `ConfirmStores`
and `ReservationStores` ports plus three single-row readers):

- writers and single-row readers: `PgTradingEntityStore` (signal and trade plan, parents first),
  `PgApprovalStore` (PENDING rows, atomic decisions, short-id mapping, one decided approval per
  plan) and `PgJournalStore` (deterministic ids: a replay writes no new row);
- the readers none of them had: the PENDING and the APPROVE-APPROVED approvals (the restart
  sweeps) are plain selects here, and the journal of one correlation.

No in-memory fallback exists (D-04): a store that cannot be reached raises `StoreUnavailable`.
"""

from __future__ import annotations

from sqlalchemy import select

from src.approval.mapping import ShortIdMapping
from src.db.mappers import approval_from_row
from src.db.models import ApprovalRow
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult
from src.domain.journal import JournalEvent
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.persistence.approvals import PgApprovalStore
from src.persistence.entities import PgTradingEntityStore
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase


class PgShadowStores:
    """The SHADOW chain's persistence port over the Phase 17 PostgreSQL stores."""

    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db
        self._entities = PgTradingEntityStore(db)
        self._approvals = PgApprovalStore(db)
        self._journal = PgJournalStore(db)

    # ---- writers ------------------------------------------------------------ #

    def insert_signal(self, signal: Signal) -> None:
        self._entities.insert_signal(signal)

    def insert_trade_plan(self, plan: TradePlan) -> None:
        self._entities.insert_trade_plan(plan)

    def insert_pending(self, approval: Approval) -> None:
        self._approvals.insert_pending(approval)

    def record_short_id_mapping(self, mapping: ShortIdMapping) -> None:
        self._approvals.record_short_id_mapping(mapping)

    def save_atomic(self, approval: Approval, mapping: ShortIdMapping | None) -> None:
        self._approvals.save_atomic(approval, mapping)

    def record_journal(self, event: JournalEvent) -> None:
        self._journal.record(event)

    # ---- readers ------------------------------------------------------------ #

    def lookup_by_token_hash(self, token_hash: str) -> Approval | None:
        return self._approvals.lookup_by_token_hash(token_hash)

    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None:
        return self._approvals.lookup_by_short_id(short_id)

    def get_signal(self, signal_id: str) -> Signal | None:
        return self._entities.get_signal(signal_id)

    def get_trade_plan(self, trade_plan_id: str) -> TradePlan | None:
        return self._entities.get_trade_plan(trade_plan_id)

    def get_approval(self, approval_id: str) -> Approval | None:
        return self._approvals.get(approval_id)

    def list_pending_approvals(self) -> list[Approval]:
        return self._by_status(ApprovalResult.PENDING)

    def list_approved_approvals(self) -> list[Approval]:
        return [
            a
            for a in self._by_status(ApprovalResult.APPROVED)
            if a.action is ApprovalAction.APPROVE
        ]

    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]:
        return self._journal.list_by_correlation(correlation_id)

    def _by_status(self, status: ApprovalResult) -> list[Approval]:
        with self._db.transaction() as session:
            rows = session.execute(
                select(ApprovalRow).where(ApprovalRow.status == status.value)
            ).scalars()
            return [approval_from_row(row) for row in rows]


__all__ = ["PgShadowStores"]
