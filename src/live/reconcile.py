"""The reconcile composition of the live process (plan 24-20; EXEC-02, G4-029, WR-B6, row 41).

Phase 20 built `ReconcileLoop`, `OrphanSweeper`, `UnknownEntryResolver` and `LotFilterSource` and
tested each with fakes; nothing in `src` constructed them. `build_reconcile` does, once:

- the loop gets the DURABLE `SafeModeController` (the loop itself refuses a non-durable one), the
  protection coordinator (its `protections()`, `notify_divergence` and `restore_complete`), the
  `OrphanSweeper`, the `UnknownEntryResolver`, the alert sink, the feed and stream-divergence
  sources (plan 24-19 binds the real ones; they are typed by the reconcile Protocols), the lot
  filter source, the pending-action store, a `risk_reducer`, the stale-entry `entry_good_till`
  and `feed_clock_skew=clock_skew_from_drift(binance_limits.drift)` (20-DEFERRED WR-B6);
- the sweeper is built without a `now_utc`: the loop passes the tick time on every sweep, so the
  sweeper's wall-clock fallback is never reached (T-24-59). The loop also passes its own
  position verifier (two fresh adapter reads, a non-Decimal row raises), so no second verifier is
  written here. This module reads no clock;
- `build_lot_filters` binds `LotFilterSource` to the stored validated filters and the persisted
  plan snapshot (`snapshot_for`), for `MarketEmergencyCloser(lot_filters=...)` (D081 Q3). Plan
  24-27 builds the closer and the coordinator with it; this module only receives them.

The tick is the scheduler task body `reconcile_tick_once(bundle, now_utc)`; an overlapping call
returns `TICK_SKIPPED_OVERLAP` from the loop's own lock.

Known limits (recorded for 24-DEFERRED, nothing built here because each needs an owner number or
a file outside this plan):

- the stored-fallback maximum age of a lot-filter row is an owner number; `LotFilterSource` has
  none and this module adds none;
- WR-B7: the loop's lot-filter refresh runs inside the tick lock without a timeout; a timeout is
  a new owner number;
- the loop calls its sync stores (`list_unresolved_intents`, `list_open`) directly on the event
  loop; moving them behind `StoreExecutor` is a change to `src/reconcile/loop.py`;
- `entry_good_till_by_plan_hash` learns the trade plan id of a plan hash from the unresolved
  intents it has seen in this process; an entry acknowledged before a restart has no known plan
  id, its stale-entry check is skipped and said so once per order (a hash lookup on the plan
  store needs `src/persistence/entities.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from src.adapters.binance_limits import BinanceLimits
from src.domain.enums import OrderRole
from src.domain.trade_plan import TradePlan
from src.execution.constraint_snapshot import PlanConstraintSnapshot
from src.execution.execution_limits import ExecutionLimits
from src.execution.intent_recovery import UnknownEntryResolver
from src.execution.intent_store import ExecutionIntentStore, IntentRecord
from src.execution.lot_filter_source import (
    LotFilterAdapter,
    LotFilterSource,
    LotFilterStore,
)
from src.execution.pre_placement import good_till_date_ms
from src.reconcile.feed_freshness import clock_skew_from_drift
from src.reconcile.loop import (
    FeedSource,
    GateRestrictionSource,
    JournalSink,
    OpenPendingSource,
    ProtectionView,
    ReconcileAdapter,
    ReconcileAlertSink,
    ReconcileLoop,
    RiskReducer,
    StreamDivergenceSource,
    TickReport,
)
from src.reconcile.safe_mode import SafeModeController
from src.reconcile.sweeper import OrphanSweeper

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ENTRY_ROLE = OrderRole.ENTRY.value


class LiveReconcileAdapter(ReconcileAdapter, LotFilterAdapter, Protocol):
    """What the reconcile composition asks of the signed adapter (the real one has all of it).

    Beyond the loop's reads it needs the sweeper's algo probe and cancel, the resolver's order
    probe and the lot-filter read; they are exercised through one object so the process holds one
    adapter (and so one REST gate).
    """

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> Any: ...


class SteppingProtection(ProtectionView, Protocol):
    """The coordinator as the risk reducer uses it: the reconcile hooks plus its `step`."""

    async def step(self) -> None: ...


class PlanStore(Protocol):
    """`PgTradingEntityStore.get_trade_plan`: the stored plan, whose expiry sets the GTD."""

    def get_trade_plan(self, trade_plan_id: str) -> TradePlan | None: ...


class PlanSnapshotStore(Protocol):
    """`PgPlanConstraintSnapshotStore.get`: the persisted constraint snapshot of a plan."""

    def get(self, trade_plan_id: str) -> PlanConstraintSnapshot | None: ...


@dataclass(frozen=True, kw_only=True)
class ReconcileBundle:
    """The reconcile objects of the live process (every field required)."""

    loop: ReconcileLoop
    sweeper: OrphanSweeper
    resolver: UnknownEntryResolver
    lot_filters: LotFilterSource


# --------------------------------------------------------------------------- #
# Glue: position verifier, risk reducer, entry good-till, lot filters.
# --------------------------------------------------------------------------- #


def make_risk_reducer(coordinator: SteppingProtection, closer: object | None = None) -> RiskReducer:
    """The loop's `risk_reducer`: one coordinator step (D-20, Q4).

    A refused stop, entry cancel or emergency close is retried by the coordinator's own step: the
    closer is only ever called from the coordinator (`close_position`), so stepping the
    coordinator IS the closer's pending-action retry, in the order the coordinator already keeps
    (close first). `closer` is accepted so the composition names both parts; it is not stepped on
    its own because `MarketEmergencyCloser` has no step. The reducer sends nothing itself and its
    calls still pass the REST gate.
    """
    del closer  # documented above: the closer retries inside the coordinator's step

    async def reduce_risk() -> None:
        await coordinator.step()

    return reduce_risk


def _gtd_of(plan: TradePlan) -> datetime:
    """The `goodTillDate` the entry was sent with: the expiry floored to a whole second."""
    return _EPOCH + timedelta(milliseconds=good_till_date_ms(plan.expiry_utc))


def entry_good_till_from_store(plan_store: PlanStore) -> Callable[[IntentRecord], datetime | None]:
    """`UnknownEntryResolver.entry_good_till`: the stored plan's GTD for an intent row.

    None for an unknown plan (the resolver then keeps the intent UNKNOWN, fail closed).
    """

    def good_till(record: IntentRecord) -> datetime | None:
        plan = plan_store.get_trade_plan(record.trade_plan_id)
        return None if plan is None else _gtd_of(plan)

    return good_till


def entry_good_till_by_plan_hash(
    plan_store: PlanStore, intent_store: ExecutionIntentStore
) -> Callable[[str], datetime | None]:
    """`ReconcileLoop.entry_good_till`: the GTD of the entry of a plan hash (plan 20-28).

    The loop knows only the plan hash. The trade plan id is learned from the unresolved ENTRY
    intents (see the module docstring for the limit); an unknown hash answers None, which the loop
    reads as "unknown, skip and say so".
    """
    known: dict[str, str] = {}

    def good_till(plan_hash: str) -> datetime | None:
        if plan_hash not in known:
            for record in intent_store.list_unresolved_intents():
                if record.role == _ENTRY_ROLE:
                    known.setdefault(record.plan_hash, record.trade_plan_id)
        trade_plan_id = known.get(plan_hash)
        if trade_plan_id is None:
            return None
        plan = plan_store.get_trade_plan(trade_plan_id)
        return None if plan is None else _gtd_of(plan)

    return good_till


def build_lot_filters(
    *,
    adapter: LotFilterAdapter,
    store: LotFilterStore,
    snapshot_store: PlanSnapshotStore,
    limits: ExecutionLimits,
    clock: Callable[[], datetime],
) -> LotFilterSource:
    """The lot-filter source of the emergency closer (D081 Q3) and of the loop's refresh.

    Live read first, then the last validated stored row, then the plan snapshot
    (`snapshot_for=snapshot_store.get`); the last two are flagged stale. A new entry never uses a
    stored row (`for_entry` is live only).

    Raises:
        ExecutionLimitsNotConfigured: `reconcile.lot_filter_refresh_interval_ms` is unset.
    """
    return LotFilterSource(
        adapter=adapter,
        store=store,
        limits=limits,
        clock=clock,
        snapshot_for=snapshot_store.get,
    )


# --------------------------------------------------------------------------- #
# Composition.
# --------------------------------------------------------------------------- #


def build_reconcile(
    *,
    adapter: LiveReconcileAdapter,
    gate: GateRestrictionSource,
    safe_mode: SafeModeController,
    intent_store: ExecutionIntentStore,
    coordinator: SteppingProtection,
    closer: object,
    alerts: ReconcileAlertSink,
    journal: JournalSink,
    limits: ExecutionLimits,
    binance_limits: BinanceLimits,
    feeds: FeedSource,
    stream: StreamDivergenceSource,
    lot_filters: LotFilterSource,
    pending_actions: OpenPendingSource,
    plan_store: PlanStore,
    on_entry_resolved: Callable[[str, str], None] | None = None,
) -> ReconcileBundle:
    """Build the sweeper, the UNKNOWN-entry resolver and the reconcile loop over one adapter.

    `on_entry_resolved(plan_hash, resolution)` is the resolver's `on_resolved` (plan 24-34): the
    composition binds it to `ProtectionCoordinator.note_entry_resolved`.

    Raises (all at build, nothing is started):
        ValueError: `safe_mode` is not durable (no state store).
        ExecutionLimitsNotConfigured: a required limit is unset (names the key).
        ExecutionLimitsInvalid: the tick interval is not strictly below
            `protection.max_unprotected_ms`.
    """
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    resolver = UnknownEntryResolver(
        store=intent_store,
        adapter=adapter,
        journal=journal,
        safe_mode_controller=safe_mode,
        limits=limits,
        entry_good_till=entry_good_till_from_store(plan_store),
        on_resolved=on_entry_resolved,
    )
    loop = ReconcileLoop(
        adapter=adapter,
        gate=gate,
        safe_mode=safe_mode,
        intent_store=intent_store,
        protection=coordinator,
        sweeper=sweeper,
        alerts=alerts,
        journal=journal,
        limits=limits,
        unknown_entries=resolver,
        feeds=feeds,
        stream=stream,
        lot_filters=lot_filters,
        pending_actions=pending_actions,
        risk_reducer=make_risk_reducer(coordinator, closer),
        entry_good_till=entry_good_till_by_plan_hash(plan_store, intent_store),
        feed_clock_skew=clock_skew_from_drift(binance_limits.drift),
    )
    return ReconcileBundle(loop=loop, sweeper=sweeper, resolver=resolver, lot_filters=lot_filters)


async def reconcile_tick_once(bundle: ReconcileBundle, now_utc: datetime) -> TickReport:
    """One reconcile tick (the scheduler task body); `now_utc` is the injected process time."""
    return await bundle.loop.tick(now_utc=now_utc)


__all__ = [
    "LiveReconcileAdapter",
    "PlanSnapshotStore",
    "PlanStore",
    "ReconcileBundle",
    "SteppingProtection",
    "build_lot_filters",
    "build_reconcile",
    "entry_good_till_by_plan_hash",
    "entry_good_till_from_store",
    "make_risk_reducer",
    "reconcile_tick_once",
]
