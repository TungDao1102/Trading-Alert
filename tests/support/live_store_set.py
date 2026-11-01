"""An in-memory `LiveStoreSet` for the composed live process (plan 24-27B).

TEST_ONLY: every class here is a dict-backed double of one PostgreSQL store of
`src.live.wiring.build_pg_stores`, with the semantics the composed process relies on. The stores are
the DATABASE edge of the composition, so the tracer on `build_wiring` can run without a connection
(the real classes are proven by the `*_pg.py` suites and by the SQL-compile tests). No production
module imports this file (tests/test_no_unratified_defaults.py enforces it).

What is modelled, and what is not:

* Journal, system state (append-only, versioned), SAFE_MODE state, plan constraint snapshots,
  risk reservations (the REQUESTED -> RESERVED -> PLACED -> OPEN -> RELEASED lifecycle with the
  counted and margin-claim reads), approvals (decision, mapping and the `after_decide` hook with a
  rollback of the decision when the hook raises), entities (signals and plans share the dicts of
  the DEMO-scoped shadow store; transitions go through the DOMN-04 table; orders with the
  event-time guard), intents (the production reads `intent_for_client_id` and
  `restorable_entries` on top of the shared intent fake), pending actions, lot filters and the day
  risk store (the existing fakes).
* NOT modelled: foreign keys beyond what the shadow fake checks, row locks, the cap verdict of
  `reserve_in` (the reservation gate itself is proven by the Phase 21 suites), and positions
  (`ACCOUNT_UPDATE` is not part of the tracer; the position methods raise `NotImplementedError`
  so a use is loud).
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.approval.mapping import ShortIdMapping
from src.domain.approval import Approval
from src.domain.enums import (
    ExecutionIntentStatus,
    KillGateState,
    OrderRole,
    SignalStatus,
    SystemStateKey,
    TradePlanStatus,
)
from src.domain.journal import JournalEvent
from src.domain.order import Order
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.domain.transitions import TransitionKind, assert_transition
from src.execution.intent_store import IntentRecord
from src.live.wiring import LiveStoreSet
from src.persistence.entities import StateUpdate
from src.persistence.errors import RowConflict
from src.persistence.risk_reservations import ReservationRecord
from src.persistence.system_state import SystemStateRecord
from src.risk.margin_check import MarginClaim
from src.risk.reservations import (
    CountedReservation,
    ReleaseReason,
    ReservationRequest,
    ReservationStatus,
    margin_for_reservation,
)

from tests.shadow_fakes import InMemoryShadowStores
from tests.support.day_risk_fakes import InMemoryDayRiskStore
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.lot_filter_fakes import InMemoryLotFilterStore
from tests.support.pending_action_fakes import InMemoryPendingActionStore
from tests.support.reconcile_doubles import InMemorySafeModeStore

_RESTORABLE = frozenset(
    {
        ExecutionIntentStatus.SENT,
        ExecutionIntentStatus.UNKNOWN,
        ExecutionIntentStatus.ACKED,
    }
)


class MemorySession:
    """The unit-of-work token the Pg stores take as `tx`; the in-memory stores ignore it."""


class InMemoryDatabase:
    """`OperationalDatabase.transaction()` over nothing (the stores here are not transactional)."""

    @contextmanager
    def transaction(self) -> Iterator[MemorySession]:
        yield MemorySession()


class InMemoryJournal:
    """`PgJournalStore`: append-only, replay-idempotent, listed by correlation id."""

    def __init__(self) -> None:
        self._events: dict[str, JournalEvent] = {}
        self._lock = threading.Lock()

    def record(self, event: JournalEvent) -> None:
        with self._lock:
            stored = self._events.get(event.journal_event_id)
            if stored is None:
                self._events[event.journal_event_id] = event
            elif stored != event:
                raise RowConflict(f"journal event {event.journal_event_id}: different content")

    def append(self, tx: Any, event: JournalEvent) -> None:
        self.record(event)

    def get(self, journal_event_id: str) -> JournalEvent | None:
        with self._lock:
            return self._events.get(journal_event_id)

    def list_by_correlation(self, correlation_id: str) -> list[JournalEvent]:
        with self._lock:
            return [e for e in self._events.values() if e.correlation_id == correlation_id]

    # ---- test-side reads ------------------------------------------------------------------- #

    @property
    def events(self) -> list[JournalEvent]:
        with self._lock:
            return list(self._events.values())

    def by_type(self, event_type: str) -> list[JournalEvent]:
        return [e for e in self.events if e.event_type == event_type]


class InMemorySystemState:
    """`PgSystemStateStore`: versioned append-only states and the kill-gate read."""

    def __init__(self, journal: InMemoryJournal) -> None:
        self._journal = journal
        self._records: dict[SystemStateKey, list[SystemStateRecord]] = {}

    def append(
        self,
        key: SystemStateKey,
        state: Mapping[str, Any],
        *,
        now_utc: datetime,
        tx: Any = None,
    ) -> SystemStateRecord:
        versions = self._records.setdefault(key, [])
        record = SystemStateRecord(
            key=key,
            version=len(versions) + 1,
            state=dict(state),
            recorded_at_utc=now_utc,
            journal_event_id=f"memory-{key.value}-{len(versions) + 1}",
        )
        versions.append(record)
        return record

    def latest(self, key: SystemStateKey, *, tx: Any = None) -> SystemStateRecord | None:
        versions = self._records.get(key)
        return versions[-1] if versions else None

    def latest_kill_gate_state(self, *, tx: Any = None) -> KillGateState | None:
        record = self.latest(SystemStateKey.KILL_GATE)
        if record is None:
            return None
        return KillGateState(str(record.state["state"]))


class InMemorySnapshots:
    """`PgPlanConstraintSnapshotStore`: write-once per plan."""

    def __init__(self) -> None:
        self._rows: dict[str, Any] = {}

    def record(self, snapshot: Any, *, tx: Any = None) -> None:
        stored = self._rows.get(snapshot.trade_plan_id)
        if stored is not None and stored != snapshot:
            raise RowConflict(f"snapshot {snapshot.trade_plan_id}: a different one is stored")
        self._rows[snapshot.trade_plan_id] = snapshot

    def get(self, trade_plan_id: str, *, tx: Any = None) -> Any:
        return self._rows.get(trade_plan_id)


class InMemoryEntities:
    """`PgTradingEntityStore` over the dicts of the DEMO-scoped shadow store (one set of rows)."""

    def __init__(self, shadow: InMemoryShadowStores) -> None:
        self._shadow = shadow
        self._orders: dict[str, Order] = {}
        self._event_times: dict[str, datetime] = {}
        self._lock = threading.Lock()

    # ---- signals and plans ----------------------------------------------------------------- #

    def insert_signal(self, signal: Signal, *, tx: Any = None) -> None:
        self._shadow.insert_signal(signal)

    def get_signal(self, signal_id: str, *, tx: Any = None) -> Signal | None:
        return self._shadow.signals.get(signal_id)

    def transition_signal(
        self, signal_id: str, new_status: SignalStatus, *, now_utc: datetime, tx: Any = None
    ) -> Signal:
        signal = self._shadow.signals.get(signal_id)
        if signal is None:
            raise RowConflict(f"signal {signal_id}: does not exist")
        if signal.status is new_status:
            return signal
        assert_transition(TransitionKind.SIGNAL, signal.status, new_status)
        updated = dataclasses.replace(signal, status=new_status)
        self._shadow.signals[signal_id] = updated
        return updated

    def insert_trade_plan(self, plan: TradePlan, *, tx: Any = None) -> None:
        self._shadow.insert_trade_plan(plan)

    def get_trade_plan(self, trade_plan_id: str, *, tx: Any = None) -> TradePlan | None:
        return self._shadow.plans.get(trade_plan_id)

    def get_trade_plan_by_hash(self, plan_hash: str, *, tx: Any = None) -> TradePlan | None:
        for plan in self._shadow.plans.values():
            if plan.plan_hash == plan_hash:
                return plan
        return None

    def transition_trade_plan(
        self, trade_plan_id: str, new_status: TradePlanStatus, *, now_utc: datetime, tx: Any = None
    ) -> TradePlan:
        plan = self._shadow.plans.get(trade_plan_id)
        if plan is None:
            raise RowConflict(f"trade plan {trade_plan_id}: does not exist")
        if plan.status is new_status:
            return plan
        assert_transition(TransitionKind.TRADE_PLAN, plan.status, new_status)
        updated = dataclasses.replace(plan, status=new_status)
        self._shadow.plans[trade_plan_id] = updated
        return updated

    # ---- orders ---------------------------------------------------------------------------- #

    def insert_order(self, order: Order, *, tx: Any = None) -> None:
        with self._lock:
            self._orders.setdefault(order.order_id, order)

    def get_order(self, order_id: str, *, tx: Any = None) -> Order | None:
        with self._lock:
            return self._orders.get(order_id)

    def get_order_by_client_order_id(self, client_order_id: str, *, tx: Any = None) -> Order | None:
        with self._lock:
            return next(
                (o for o in self._orders.values() if o.client_order_id == client_order_id), None
            )

    def get_order_by_algo_client_id(self, algo_client_id: str, *, tx: Any = None) -> Order | None:
        with self._lock:
            return next(
                (o for o in self._orders.values() if o.algo_client_id == algo_client_id), None
            )

    def update_order_exchange_state(
        self,
        order_id: str,
        *,
        exchange_status: str,
        exchange_order_id: str | None = None,
        now_utc: datetime,
        exchange_event_time_utc: datetime | None = None,
        tx: Any = None,
    ) -> Any:
        with self._lock:
            order = self._orders[order_id]
            stored_event = self._event_times.get(order_id)
            if (
                exchange_event_time_utc is not None
                and stored_event is not None
                and exchange_event_time_utc < stored_event
            ):
                return StateUpdate(order, True)
            updated = dataclasses.replace(
                order,
                exchange_status=exchange_status,
                exchange_order_id=order.exchange_order_id
                if exchange_order_id is None
                else exchange_order_id,
                updated_at_utc=now_utc,
            )
            self._orders[order_id] = updated
            if exchange_event_time_utc is not None:
                self._event_times[order_id] = exchange_event_time_utc
                return StateUpdate(updated, False)
            return updated

    def transition_order(
        self, order_id: str, new_status: Any, *, now_utc: datetime, tx: Any = None, **_: Any
    ) -> Order:
        with self._lock:
            order = self._orders[order_id]
            assert_transition(TransitionKind.ORDER, order.local_status, new_status)
            updated = dataclasses.replace(order, local_status=new_status, updated_at_utc=now_utc)
            self._orders[order_id] = updated
            return updated

    # ---- positions: not modelled ------------------------------------------------------------ #

    def get_position(self, position_id: str, *, tx: Any = None) -> Any:
        raise NotImplementedError("positions are not modelled by the in-memory entity store")

    insert_position = get_position
    update_position_snapshot = get_position
    transition_position = get_position

    # ---- test-side reads --------------------------------------------------------------------- #

    @property
    def orders(self) -> dict[str, Order]:
        with self._lock:
            return dict(self._orders)


class InMemoryApprovals:
    """`PgApprovalStore.save_atomic`: the decision and the hook succeed or fail together."""

    def __init__(self, shadow: InMemoryShadowStores) -> None:
        self._shadow = shadow

    def save_atomic(
        self,
        approval: Approval,
        mapping: ShortIdMapping | None,
        *,
        after_decide: Any = None,
    ) -> None:
        before_approvals = dict(self._shadow.approvals)
        before_mappings = dict(self._shadow.mappings)
        before_signals = dict(self._shadow.signals)
        before_plans = dict(self._shadow.plans)
        try:
            self._shadow.save_atomic(approval, mapping)
            if after_decide is not None:
                after_decide(MemorySession(), approval)
        except BaseException:
            self._shadow.approvals.clear()
            self._shadow.approvals.update(before_approvals)
            self._shadow.mappings.clear()
            self._shadow.mappings.update(before_mappings)
            self._shadow.signals.clear()
            self._shadow.signals.update(before_signals)
            self._shadow.plans.clear()
            self._shadow.plans.update(before_plans)
            raise


@dataclass
class _Reservation:
    request: ReservationRequest
    status: ReservationStatus
    approval_id: str | None
    requested_at_utc: datetime
    reserved_at_utc: datetime | None = None
    placed_at_utc: datetime | None = None
    opened_at_utc: datetime | None = None
    released_at_utc: datetime | None = None
    release_reason: ReleaseReason | None = None

    def record(self) -> ReservationRecord:
        return ReservationRecord(
            trade_plan_id=self.request.trade_plan_id,
            approval_id=self.approval_id,
            status=self.status,
            release_reason=self.release_reason,
            requested_at_utc=self.requested_at_utc,
            reserved_at_utc=self.reserved_at_utc,
            placed_at_utc=self.placed_at_utc,
            opened_at_utc=self.opened_at_utc,
            released_at_utc=self.released_at_utc,
        )


class InMemoryReservations:
    """`PgRiskReservationStore`: the lifecycle and the two reads. No cap verdict (see above)."""

    def __init__(self) -> None:
        self._rows: dict[str, _Reservation] = {}
        self._lock = threading.Lock()

    def register_request(
        self, request: ReservationRequest, *, now_utc: datetime, tx: Any = None
    ) -> ReservationRecord:
        with self._lock:
            row = self._rows.get(request.trade_plan_id)
            if row is None:
                row = _Reservation(
                    request=request,
                    status=ReservationStatus.REQUESTED,
                    approval_id=None,
                    requested_at_utc=now_utc,
                )
                self._rows[request.trade_plan_id] = row
            elif row.request != request:
                raise RowConflict(f"risk_reservations {request.trade_plan_id}: other identity")
            return row.record()

    def reserve_in(
        self,
        session: Any,
        *,
        approval: Approval,
        now_utc: datetime,
        daily_loss_quote: Any,
        parameter_set: Any,
    ) -> ReservationRecord:
        with self._lock:
            row = self._rows.get(approval.trade_plan_id)
            if row is None or row.status is not ReservationStatus.REQUESTED:
                raise RowConflict(f"reservation of {approval.trade_plan_id} is not REQUESTED")
            row.status = ReservationStatus.RESERVED
            row.approval_id = approval.approval_id
            row.reserved_at_utc = now_utc
            return row.record()

    def release_requested_in(
        self,
        session: Any,
        *,
        trade_plan_id: str,
        reason: ReleaseReason,
        now_utc: datetime,
    ) -> None:
        with self._lock:
            row = self._rows.get(trade_plan_id)
            if row is not None and row.status is ReservationStatus.REQUESTED:
                row.status = ReservationStatus.RELEASED
                row.release_reason = reason
                row.released_at_utc = now_utc

    def mark_placed(
        self, trade_plan_id: str, *, now_utc: datetime, tx: Any = None
    ) -> ReservationRecord:
        with self._lock:
            row = self._rows[trade_plan_id]
            if row.status is ReservationStatus.RESERVED:
                row.status = ReservationStatus.PLACED
                row.placed_at_utc = now_utc
            return row.record()

    def get(self, trade_plan_id: str, *, tx: Any = None) -> ReservationRecord | None:
        with self._lock:
            row = self._rows.get(trade_plan_id)
            return None if row is None else row.record()

    def list_counted(self, *, tx: Any = None) -> tuple[CountedReservation, ...]:
        counted = {ReservationStatus.RESERVED, ReservationStatus.PLACED, ReservationStatus.OPEN}
        with self._lock:
            rows = [r for r in self._rows.values() if r.status in counted]
        return tuple(
            CountedReservation(
                trade_plan_id=r.request.trade_plan_id,
                plan_hash=r.request.plan_hash,
                symbol=r.request.symbol,
                position_side=r.request.position_side,
                status=r.status,
                open_risk=r.request.realized_risk,
            )
            for r in sorted(
                rows,
                key=lambda r: (r.request.symbol, r.request.position_side, r.request.trade_plan_id),
            )
        )

    def list_margin_claims(self, *, tx: Any = None) -> tuple[MarginClaim, ...]:
        claim_statuses = {ReservationStatus.RESERVED, ReservationStatus.PLACED}
        with self._lock:
            rows = [r for r in self._rows.values() if r.status in claim_statuses]
        claims: list[MarginClaim] = []
        for r in sorted(
            rows, key=lambda r: (r.request.symbol, r.request.position_side, r.request.trade_plan_id)
        ):
            request = r.request
            required: Any = None
            if request.margin_entry_price is not None and request.margin_leverage is not None:
                required = margin_for_reservation(
                    quantity=request.quantity,
                    price=request.margin_entry_price,
                    leverage=request.margin_leverage,
                )
            claims.append(
                MarginClaim(
                    trade_plan_id=request.trade_plan_id,
                    status=r.status,
                    required_margin=required,
                    placed_at_utc=r.placed_at_utc,
                )
            )
        return tuple(claims)


class LiveIntentStore(InMemoryExecutionIntentStore):
    """The shared intent fake plus the two production reads of `PgExecutionStateStore`.

    `restorable_entries` applies the D093 rule through the journal, as the SQL does: ENTRY rows in
    SENT, UNKNOWN or ACKED whose plan has no `PROTECTION_TRANSITION` row into FLAT or
    ENTRY_ENDED_NO_FILL.
    """

    def __init__(self, journal: InMemoryJournal | None = None) -> None:
        super().__init__()
        self._journal = journal

    def intent_for_client_id(self, client_order_id: str) -> IntentRecord | None:
        with self._lock:
            for row in self._rows.values():
                if client_order_id in (row.client_order_id, row.algo_client_id):
                    return row
        return None

    def _ended(self, plan_hash: str) -> bool:
        if self._journal is None:
            return False
        for event in self._journal.list_by_correlation(f"protection_{plan_hash}"):
            if event.event_type != "PROTECTION_TRANSITION":
                continue
            if any(
                f'"to":"{state}"' in event.payload_json for state in ("FLAT", "ENTRY_ENDED_NO_FILL")
            ):
                return True
        return False

    def restorable_entries(self) -> tuple[IntentRecord, ...]:
        with self._lock:
            rows = [
                r
                for r in self._rows.values()
                if r.role == OrderRole.ENTRY.value and r.intent_status in _RESTORABLE
            ]
        rows = [r for r in rows if not self._ended(r.plan_hash)]
        return tuple(sorted(rows, key=lambda r: (r.intended_at_utc, r.approval_id)))


@dataclass(frozen=True, kw_only=True)
class MemoryStoreHandles:
    """The typed doubles behind the `LiveStoreSet` (tests read them directly)."""

    db: InMemoryDatabase
    shadow: InMemoryShadowStores
    approvals: InMemoryApprovals
    entities: InMemoryEntities
    execution_state: LiveIntentStore
    journal: InMemoryJournal
    pending_actions: InMemoryPendingActionStore
    reservations: InMemoryReservations
    system_state: InMemorySystemState
    safe_mode_state: InMemorySafeModeStore
    snapshots: InMemorySnapshots
    lot_filters: InMemoryLotFilterStore
    day_risk: InMemoryDayRiskStore


def build_memory_stores() -> tuple[LiveStoreSet, MemoryStoreHandles]:
    """A `LiveStoreSet` of in-memory doubles and the typed handles to them."""
    journal = InMemoryJournal()
    shadow = InMemoryShadowStores(confirm_mode="DEMO")
    handles = MemoryStoreHandles(
        db=InMemoryDatabase(),
        shadow=shadow,
        approvals=InMemoryApprovals(shadow),
        entities=InMemoryEntities(shadow),
        execution_state=LiveIntentStore(journal),
        journal=journal,
        pending_actions=InMemoryPendingActionStore(),
        reservations=InMemoryReservations(),
        system_state=InMemorySystemState(journal),
        safe_mode_state=InMemorySafeModeStore(),
        snapshots=InMemorySnapshots(),
        lot_filters=InMemoryLotFilterStore(),
        day_risk=InMemoryDayRiskStore(),
    )
    store_set = LiveStoreSet(
        db=handles.db,  # type: ignore[arg-type]
        shadow=handles.shadow,  # type: ignore[arg-type]
        approvals=handles.approvals,  # type: ignore[arg-type]
        entities=handles.entities,  # type: ignore[arg-type]
        execution_state=handles.execution_state,  # type: ignore[arg-type]
        journal=handles.journal,  # type: ignore[arg-type]
        pending_actions=handles.pending_actions,  # type: ignore[arg-type]
        reservations=handles.reservations,  # type: ignore[arg-type]
        system_state=handles.system_state,  # type: ignore[arg-type]
        safe_mode_state=handles.safe_mode_state,  # type: ignore[arg-type]
        snapshots=handles.snapshots,  # type: ignore[arg-type]
        lot_filters=handles.lot_filters,  # type: ignore[arg-type]
        day_risk=handles.day_risk,  # type: ignore[arg-type]
    )
    return store_set, handles


__all__ = [
    "InMemoryApprovals",
    "InMemoryDatabase",
    "InMemoryEntities",
    "InMemoryJournal",
    "InMemoryReservations",
    "InMemorySnapshots",
    "InMemorySystemState",
    "LiveIntentStore",
    "MemorySession",
    "MemoryStoreHandles",
    "build_memory_stores",
]
