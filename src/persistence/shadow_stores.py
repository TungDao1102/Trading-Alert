"""The PostgreSQL stores of the SHADOW chain (Phase 16, plan 16-31, D-04, D-16).

`PgShadowStores` composes the Phase 17 stores behind the one port the running chain uses
(`src/paper/shadow_runtime.py:ShadowRuntimeStores`, which is the `ShadowStores`, `ConfirmStores`
and `ReservationStores` ports plus three single-row readers):

- writers and single-row readers: `PgTradingEntityStore` (signal and trade plan, parents first),
  `PgApprovalStore` (PENDING rows, atomic decisions, short-id mapping, one decided approval per
  plan) and `PgJournalStore` (deterministic ids: a replay writes no new row);
- the readers none of them had: the PENDING and the APPROVE-APPROVED approvals (the restart
  sweeps) are plain selects here, and the journal of one correlation.

Mode scope (Phase 24, plan 24-08; research C-7, OQ-6; owner answer 24-01 Q8): SHADOW and DEMO
share one PostgreSQL database, and the confirm sweeps judge every APPROVED approval their store
lists. `PgShadowStores(db, confirm_mode=...)` therefore writes a durable mode marker (the journal
event `APPROVAL_MODE_RECORDED`, correlation `approval-mode:<approval_id>`) in the SAME transaction
as the PENDING approval row, and `list_approved_approvals` returns only the approvals of its mode:

- a SHADOW-scoped store also returns an approval that has no marker (every row written before
  this plan is a SHADOW row);
- a DEMO- or LIVE-scoped store returns an approval only when it carries its own marker (fail
  closed for the order-capable modes);
- `confirm_mode=None` is the unscoped store (every APPROVED approval, no marker written) kept for
  the tests that predate the scope.

No schema change: the marker is a journal row whose payload is the canonical JSON of the mode.

No in-memory fallback exists (D-04): a store that cannot be reached raises `StoreUnavailable`.
"""

from __future__ import annotations

import json
from typing import Final

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.approval.mapping import ShortIdMapping
from src.db.mappers import approval_from_row
from src.db.models import ApprovalRow, JournalEventRow
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.persistence.approvals import PgApprovalStore
from src.persistence.entities import PgTradingEntityStore
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

# The three mode labels of the confirm profiles (`src/approval/confirm_core.py`:
# `ConfirmProfile.mode_label`). Repeated here on purpose: persistence must not import the
# confirm layer, and a test pins the equality.
CONFIRM_MODES: Final[tuple[str, ...]] = ("SHADOW", "DEMO", "LIVE")

EVENT_APPROVAL_MODE_RECORDED: Final = "APPROVAL_MODE_RECORDED"
ENTITY_APPROVAL_MODE: Final = "ApprovalMode"
APPROVAL_MODE_CORRELATION_PREFIX: Final = "approval-mode:"
_MARKER_JOURNAL_PREFIX: Final = "appr-mode"
_MARKER_STEP: Final = "recorded"


def mode_marker_payload(mode: str) -> str:
    """The canonical payload of the marker of `mode` (the reader compares it as a whole)."""
    if mode not in CONFIRM_MODES:
        raise ValueError(f"confirm_mode must be one of {CONFIRM_MODES}, got {mode!r}")
    return json.dumps({"mode": mode}, sort_keys=True, separators=(",", ":"))


_PAYLOAD_TO_MODE: Final[dict[str, str]] = {mode_marker_payload(m): m for m in CONFIRM_MODES}


def mode_from_marker_payload(payload_json: str) -> str | None:
    """The mode a marker payload names, or None for a payload this code did not write."""
    return _PAYLOAD_TO_MODE.get(payload_json)


def approval_mode_correlation(approval_id: str) -> str:
    return f"{APPROVAL_MODE_CORRELATION_PREFIX}{approval_id}"


def approval_mode_event(approval: Approval, mode: str) -> JournalEvent:
    """The marker journal event of one approval: deterministic id, so a replay is a no-op."""
    correlation = approval_mode_correlation(approval.approval_id)
    return JournalEvent(
        journal_event_id=correlated_event_id(
            prefix=_MARKER_JOURNAL_PREFIX,
            correlation_id=correlation,
            event_type=EVENT_APPROVAL_MODE_RECORDED,
            entity_id=approval.approval_id,
            step=_MARKER_STEP,
        ),
        occurred_at_utc=approval.requested_at_utc,
        event_type=EVENT_APPROVAL_MODE_RECORDED,
        entity_type=ENTITY_APPROVAL_MODE,
        entity_id=approval.approval_id,
        correlation_id=correlation,
        signal_id=approval.signal_id,
        trade_plan_id=approval.trade_plan_id,
        approval_id=approval.approval_id,
        payload_json=mode_marker_payload(mode),
    )


def validate_confirm_mode(confirm_mode: str | None) -> str | None:
    """`confirm_mode` itself, or ValueError unless None or one of the three mode labels."""
    if confirm_mode is not None and confirm_mode not in CONFIRM_MODES:
        raise ValueError(
            f"confirm_mode must be None or one of {CONFIRM_MODES}, got {confirm_mode!r}"
        )
    return confirm_mode


def mode_includes(confirm_mode: str | None, recorded_mode: str | None) -> bool:
    """Whether a store scoped to `confirm_mode` lists an approval marked `recorded_mode`.

    `recorded_mode` is None for an approval without a marker; a marker this code cannot read is
    never passed here (the reader skips it).
    """
    if confirm_mode is None:
        return True
    if confirm_mode == "SHADOW":
        return recorded_mode in (None, "SHADOW")
    return recorded_mode == confirm_mode


class PgShadowStores:
    """The SHADOW chain's persistence port over the Phase 17 PostgreSQL stores."""

    def __init__(self, db: OperationalDatabase, *, confirm_mode: str | None = None) -> None:
        self._db = db
        self._confirm_mode = validate_confirm_mode(confirm_mode)
        self._entities = PgTradingEntityStore(db)
        self._approvals = PgApprovalStore(db)
        self._journal = PgJournalStore(db)

    @property
    def confirm_mode(self) -> str | None:
        return self._confirm_mode

    # ---- writers ------------------------------------------------------------ #

    def insert_signal(self, signal: Signal) -> None:
        self._entities.insert_signal(signal)

    def insert_trade_plan(self, plan: TradePlan) -> None:
        self._entities.insert_trade_plan(plan)

    def insert_pending(self, approval: Approval) -> None:
        mode = self._confirm_mode
        if mode is None:
            self._approvals.insert_pending(approval)
            return

        def write_marker(tx: Session, inserted: Approval) -> None:
            self._journal.append(tx, approval_mode_event(inserted, mode))

        self._approvals.insert_pending(approval, after_insert=write_marker)

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
        """APPROVE-action APPROVED approvals of this store's mode (see the module docstring)."""
        with self._db.transaction() as session:
            rows = session.execute(
                select(ApprovalRow, JournalEventRow.payload_json)
                .outerjoin(
                    JournalEventRow,
                    and_(
                        JournalEventRow.approval_id == ApprovalRow.approval_id,
                        JournalEventRow.event_type == EVENT_APPROVAL_MODE_RECORDED,
                    ),
                )
                .where(ApprovalRow.status == ApprovalResult.APPROVED.value)
            ).all()
            approvals: list[Approval] = []
            for row, marker_payload in rows:
                recorded = (
                    None if marker_payload is None else mode_from_marker_payload(marker_payload)
                )
                if marker_payload is not None and recorded is None:
                    continue  # a marker this code did not write: never list it (fail closed)
                if not mode_includes(self._confirm_mode, recorded):
                    continue
                approval = approval_from_row(row)
                if approval.action is ApprovalAction.APPROVE:
                    approvals.append(approval)
            return approvals

    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]:
        return self._journal.list_by_correlation(correlation_id)

    def _by_status(self, status: ApprovalResult) -> list[Approval]:
        with self._db.transaction() as session:
            rows = session.execute(
                select(ApprovalRow).where(ApprovalRow.status == status.value)
            ).scalars()
            return [approval_from_row(row) for row in rows]


__all__ = [
    "APPROVAL_MODE_CORRELATION_PREFIX",
    "CONFIRM_MODES",
    "ENTITY_APPROVAL_MODE",
    "EVENT_APPROVAL_MODE_RECORDED",
    "PgShadowStores",
    "approval_mode_correlation",
    "approval_mode_event",
    "mode_from_marker_payload",
    "mode_includes",
    "mode_marker_payload",
    "validate_confirm_mode",
]
