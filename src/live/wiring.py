"""The live composition root (D-04, D-05): the one place live objects are built.

Two layers live here.

**The execution path** (plan 24-04): `LiveWiring` and `build_execution_path` build the path from a
CONFIRM to a protected position for the tests that exercise it in isolation:

  desk -> confirm flow -> `ExecutionService.on_confirmed` -> `execute_approved_plan`
  user-data frame -> router -> `ProtectionCoordinator.fill_sink` (the router's lookup is `index`)

**The complete process** (plan 24-27): `build_wiring(...)` returns a `LiveAssembly`. Its stores,
executor, alerts, exchange, caches and observers exist at once; the objects that need the durable
SAFE_MODE controller and the DISABLED enablement controller (closer, coordinator, producer,
service, stream, reconcile, runner, sender, scheduler) are built by `complete(...)`, which the
start sequence reaches at step 4 and which returns the immutable `CompleteLiveWiring`. The startup
ports built by `startup_ports(...)` reach those objects lazily, because they are built before
step 4. `check_wiring(...)` lists the broken links; `run_admitted` refuses to start when it is not
empty, and `tests/test_live_wiring.py` pins every link with a negative control.

No module outside `src/live` constructs an adapter, gate, coordinator, sink, scheduler or the
execution service (AST scan in the wiring test). This module never reads the wall clock: the
clock, sleep, SDK factory, application factory, bot and engine are injected by the caller.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from src.adapters.binance_client import Environment
from src.adapters.binance_limits import BinanceLimits
from src.adapters.telegram_callbacks import on_callback
from src.adapters.telegram_notify import TelegramTextBot
from src.approval.confirm_core import (
    DEMO_CONFIRM_PROFILE,
    ConfirmProfile,
    ConfirmStores,
    MarkPriceFn,
    RecheckFn,
)
from src.backtest.semantics import TP1_QUANTITY_FRACTION
from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent
from src.domain.registry import ParameterSet
from src.execution.account_equity import LiveEquitySource
from src.execution.approval_desk import ApprovalDesk, DeskStores
from src.execution.bracket_cache import BracketCache
from src.execution.confirm_flow import ConfirmFlow, PrefetchFn, ValidityRule, make_confirm_flow
from src.execution.confirm_recheck import (
    PrefetchedConfirmInputs,
    make_confirm_recheck,
    prefetched_provider,
)
from src.execution.day_risk_service import LiveDayRiskService
from src.execution.emergency_close import MarketEmergencyCloser
from src.execution.execution_limits import ExecutionLimits
from src.execution.intent_store import ExecutionIntentStore
from src.execution.manager import ExecutionAdapter
from src.execution.pre_placement import check_remaining_validity
from src.execution.protection import CriticalAlertSink, ProtectionCoordinator
from src.execution.symbol_config_guard import TARGET_LEVERAGE, SymbolConfigGuard
from src.live.alerts import AlertBundle, build_alerts, drain_once, requeue_at_start
from src.live.approval_sender import (
    ApprovalRequestSender,
    DemoDeskStores,
    make_demo_save_atomic,
    make_open_demo_approvals_reader,
)
from src.live.commission import CommissionCache
from src.live.config import LiveConfig, write_live_liveness
from src.live.enablement import (
    StartEnablement,
    kill_gate_tick_once,
    persist_enablement_snapshot,
    start_disabled,
)
from src.live.exchange import ExchangeBundle, build_exchange, remeasure_drift
from src.live.execution_service import ExecutionService, JournalWriter, PlacementInputsSource
from src.live.feeds import LiveFeedSource, MarkBook, StreamDivergenceQueue, refresh_marks
from src.live.health import (
    DbWriteTracker,
    LiveHealthProducer,
    LiveHealthThresholds,
    ReconcileObserver,
    RestErrorCounter,
    TelegramDeliveryObserver,
    health_tick_once,
)
from src.live.operator import OperatorCommands
from src.live.order_index import ClientIdIndex
from src.live.reconcile import (
    ReconcileBundle,
    build_lot_filters,
    build_reconcile,
    reconcile_tick_once,
)
from src.live.reservation_release import ReservationReleaser
from src.live.risk_inputs import (
    LiveRiskInputProducer,
    PositionModeUnavailable,
    backfill_day_risk,
    build_liquidation_watch,
    confirm_inputs_from_readings,
    make_cost_rates_for,
    read_pre_placement_inputs,
)
from src.live.scheduled_cancel import cancel_expired_entries_once, cancel_unrestored_entries
from src.live.scheduler import LiveCadences, Scheduler, TaskSpec
from src.live.signal_source import DemoSmokeSignalSource, SignalSource, build_request_money
from src.live.smoke_injection import (
    COMMAND_DEMO_SIGNAL,
    DemoSignalCommand,
    build_demo_signal_command,
)
from src.live.startup import (
    RecoveryPorts,
    StartupPorts,
    close_attempts_reader,
    protection_correlation,
    restored_plans_builder,
)
from src.live.stream import StreamBundle, StreamSinks, build_stream, make_protection_step
from src.live.stream_persistence import StreamPersistence
from src.live.telegram_runner import LiveTelegramRunner
from src.live.wiring_parts import (
    AdapterPositionsReader,
    ExecutorPlanStore,
    ExecutorReservations,
    KillGateSources,
    LateBound,
    SignalContextBook,
    alembic_revisions_reader,
    alert_task_stall,
    make_kill_gate_sources,
    make_reservation_registrar,
    task_duration_journal,
    task_event_journal,
)
from src.ops.alerts import JournalFirstAlertSink
from src.ops.spill import LocalSpill
from src.ops.store_executor import StoreExecutor
from src.persistence.approvals import PgApprovalStore
from src.persistence.day_risk import PgDayRiskStore
from src.persistence.entities import PgTradingEntityStore
from src.persistence.execution_state import PgExecutionStateStore
from src.persistence.journal import PgJournalStore
from src.persistence.lot_filters import PgLotFilterStore
from src.persistence.pending_actions import PgPendingActionStore
from src.persistence.risk_reservations import PgRiskReservationStore
from src.persistence.safe_mode_store import PgSafeModeStateStore
from src.persistence.shadow_stores import PgShadowStores
from src.persistence.snapshots import PgPlanConstraintSnapshotStore
from src.persistence.system_state import PgSystemStateStore
from src.persistence.uow import OperationalDatabase
from src.reconcile.safe_mode import SafeModeController
from src.reconcile.startup import UnrestorableEntry
from src.risk.daily_loss import FundingPolicy

SleepFn = Callable[[float], Awaitable[None]]

# D091 (docs/DECISIONS.md): the two live-health bounds that have no limits-file key. "3 failed REST
# calls in the last 10" is the rate 3/10; the check fails when the rate of a health window is
# STRICTLY above it (`check_rest_error_rate`). The latest database write may be at most 60 s old.
REST_MAX_ERROR_RATE = Decimal("0.3")
DB_WRITE_MAX_AGE = timedelta(seconds=60)

# Binance USDⓈ-M perpetuals of the live-5 universe are quoted in USDT (the symbol names say so).
QUOTE_ASSET = "USDT"

STARTUP_PROBE_TEMPLATE = "live runtime {mode}: startup check"

# The scheduler task names (plan 24-27 must_haves): exactly this set.
TASK_PROTECTION = "protection_step"
TASK_RECONCILE = "reconcile_tick"
TASK_DRIFT = "drift_remeasure"
TASK_MARKS = "mark_refresh"
TASK_COMMISSION = "commission_refresh"
TASK_DAY_RISK = "day_risk_backfill"
TASK_CONFIRM_SWEEP = "confirm_ttl_sweep"
TASK_ALERT_DRAIN = "alert_drain"
TASK_HEALTH = "health_tick"
TASK_LIVENESS = "liveness_stamp"
TASK_SCHEDULED_CANCEL = "scheduled_cancel"
TASK_SIGNAL_PUMP = "signal_source_pump"
TASK_RESERVATION_SWEEP = "reservation_release_sweep"
TASK_NAMES = frozenset(
    {
        TASK_PROTECTION,
        TASK_RECONCILE,
        TASK_DRIFT,
        TASK_MARKS,
        TASK_COMMISSION,
        TASK_DAY_RISK,
        TASK_CONFIRM_SWEEP,
        TASK_ALERT_DRAIN,
        TASK_HEALTH,
        TASK_LIVENESS,
        TASK_SCHEDULED_CANCEL,
        TASK_SIGNAL_PUMP,
        TASK_RESERVATION_SWEEP,
    }
)

# The links `check_wiring` names (ROADMAP criterion 1 and D-06, D-07, D-15).
LINK_APPROVAL_SENDER = "approval_request_sender"
LINK_SIGNAL_PUMP = "signal_source_pump_task"
LINK_BOT_RUNNER = "telegram_bot_runner"
LINK_CALLBACK_HANDLER = "telegram_callback_handler_is_on_callback"
LINK_EXECUTION_SERVICE = "execution_service_is_the_confirm_target"
LINK_RISK_PRODUCER = "risk_input_producer_feeds_the_service"
LINK_RECONCILE = "reconcile_loop"
LINK_SWEEPER = "orphan_sweeper"
LINK_RESOLVER = "unknown_entry_resolver_bound_to_the_coordinator"
LINK_HEALTH_TASK = "health_scheduler_task"
LINK_KILL_GATE_TASK = "kill_gate_event_task"
LINK_ONE_GATE = "one_rest_gate"
LINK_DRIFT_GUARD = "adapter_drift_guard"
LINK_ALERT_SINK = "journal_first_alert_sink"
LINK_CLOSER = "coordinator_market_emergency_closer"
LINK_RESTORE_REQUIRED = "coordinator_restore_required"
LINK_LIQUIDATION_WATCH = "coordinator_liquidation_watch"
LINK_SAFE_MODE = "durable_safe_mode_controller"
LINK_SCHEDULER_SPECS = "scheduler_task_set"
LINK_COMMANDS = "operator_commands_registered"
LINK_DEMO_SIGNAL = "demo_signal_command_demo_only"
LINK_SNAPSHOT_RECORDER = "plan_snapshot_recorder_in_the_write_ahead_path"
LINK_RESERVATION_RELEASE = "reservation_release_on_refusal_and_expiry"


class LiveStores(DeskStores, ConfirmStores, Protocol):
    """The store surface the desk and the confirm flow share (one object serves both)."""


@dataclass(frozen=True, kw_only=True)
class LiveWiring:
    """The execution path of the live process (every field required)."""

    service: ExecutionService
    index: ClientIdIndex
    coordinator: ProtectionCoordinator
    closer: MarketEmergencyCloser
    desk: ApprovalDesk
    confirm_flow: ConfirmFlow


def build_execution_path(
    *,
    loop: asyncio.AbstractEventLoop,
    clock: Callable[[], datetime],
    adapter: ExecutionAdapter,
    stores: LiveStores,
    intent_store: ExecutionIntentStore,
    journal: JournalWriter,
    safe_mode_controller: Any,
    enablement: Any,
    alert_sink: CriticalAlertSink,
    limits: ExecutionLimits,
    inputs: PlacementInputsSource,
    profile: ConfirmProfile,
    authorized_chat_id: int,
    bot: TelegramTextBot,
    sleep: SleepFn,
    mark_price: MarkPriceFn | None,
    validity_rule: ValidityRule,
    recheck: RecheckFn,
    prefetch: PrefetchFn | None,
    token_for: Callable[[str], str | None] | None = None,
) -> LiveWiring:
    """Build the desk, the confirm flow, the execution service, the index, the coordinator.

    The desk's token accessor and the service's `on_confirmed` are the two seams: the service reads
    the raw APPROVE token from the desk's memory, and the confirm flow calls the service's sync
    hook. The coordinator is both the manager's protection registry (through the inputs source's
    live context) and the router's fill sink. `token_for` replaces the desk accessor only where a
    test models a restart (the raw token is memory only, so none is available after one).
    """
    index = ClientIdIndex()
    desk = ApprovalDesk(
        stores,
        profile=profile,
        clock=clock,
        intent_reader=lambda approval_id: intent_store.get_entry(approval_id=approval_id),
    )
    closer = MarketEmergencyCloser(
        adapter=adapter,  # type: ignore[arg-type]
        journal=journal,
        safe_mode_controller=safe_mode_controller,
        alert_sink=alert_sink,
        clock=clock,
        limits=limits,
    )
    coordinator = ProtectionCoordinator(
        adapter=adapter,  # type: ignore[arg-type]
        intent_store=intent_store,
        journal=journal,
        safe_mode_controller=safe_mode_controller,
        alert_sink=alert_sink,
        emergency_closer=closer,
        limits=limits,
        clock=clock,
    )
    service = ExecutionService(
        loop=loop,
        token_for=desk.approve_token_for if token_for is None else token_for,
        inputs=inputs,
        adapter=adapter,
        safe_mode_controller=safe_mode_controller,
        journal=journal,
        enablement=enablement,
        intent_store=intent_store,
        index=index,
        clock=clock,
        authorized_chat_id=authorized_chat_id,
    )
    confirm_flow = make_confirm_flow(
        desk=desk,
        profile=profile,
        stores=stores,
        clock=clock,
        bot=bot,
        sleep=sleep,
        mark_price=mark_price,
        validity_rule=validity_rule,
        recheck=recheck,
        on_confirmed=service.on_confirmed,
        prefetch=prefetch,
    )
    return LiveWiring(
        service=service,
        index=index,
        coordinator=coordinator,
        closer=closer,
        desk=desk,
        confirm_flow=confirm_flow,
    )


# --------------------------------------------------------------------------- #
# The complete process: stores.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class LiveStoreSet:
    """Every store of the live process over one `OperationalDatabase` (all synchronous).

    `entities` carries a journal (plan 24-19 hand-off 3): without it an UNKNOWN exit has no
    evidence row and the whole stream write rolls back. `shadow` is the DEMO-scoped store of the
    approval chain (`confirm_mode="DEMO"`).
    """

    db: OperationalDatabase
    shadow: PgShadowStores
    approvals: PgApprovalStore
    entities: PgTradingEntityStore
    execution_state: PgExecutionStateStore
    journal: PgJournalStore
    pending_actions: PgPendingActionStore
    reservations: PgRiskReservationStore
    system_state: PgSystemStateStore
    safe_mode_state: PgSafeModeStateStore
    snapshots: PgPlanConstraintSnapshotStore
    lot_filters: PgLotFilterStore
    day_risk: PgDayRiskStore


def build_pg_stores(db: OperationalDatabase) -> LiveStoreSet:
    """The PostgreSQL stores; no connection is opened by construction."""
    journal = PgJournalStore(db)
    system_state = PgSystemStateStore(db, journal=journal)
    return LiveStoreSet(
        db=db,
        shadow=PgShadowStores(db, confirm_mode="DEMO"),
        approvals=PgApprovalStore(db),
        entities=PgTradingEntityStore(db, journal=journal),
        execution_state=PgExecutionStateStore(db),
        journal=journal,
        pending_actions=PgPendingActionStore(db),
        reservations=PgRiskReservationStore(db),
        system_state=system_state,
        safe_mode_state=PgSafeModeStateStore(system_state),
        snapshots=PgPlanConstraintSnapshotStore(db),
        lot_filters=PgLotFilterStore(db),
        day_risk=PgDayRiskStore(db),
    )


class _EvidenceSink:
    """A router sink with no consumer in the live process: it counts what it was given.

    The status hint and algo route are evidence only (REST stays the truth, Phase 21 D-01) and no
    module reads them; the order and position writes and the divergence queue carry the rest.
    """

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, _item: object) -> None:
        self.count += 1


# --------------------------------------------------------------------------- #
# The complete process: the value.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class CompleteLiveWiring:
    """Every object of the live process (every field required)."""

    mode: Any
    clock: Callable[[], datetime]
    executor: StoreExecutor
    stores: LiveStoreSet
    spill: LocalSpill
    alerts: AlertBundle
    exchange: ExchangeBundle
    marks: MarkBook
    commission: CommissionCache
    equity: LiveEquitySource
    day_risk: LiveDayRiskService
    brackets: BracketCache
    lot_filters: Any
    index: ClientIdIndex
    signal_book: SignalContextBook
    signal_source: SignalSource
    safe_mode: SafeModeController
    enablement: Any
    closer: MarketEmergencyCloser
    coordinator: ProtectionCoordinator
    desk: ApprovalDesk
    producer: LiveRiskInputProducer
    service: ExecutionService
    stream: StreamBundle
    persistence: StreamPersistence
    divergences: StreamDivergenceQueue
    reconcile: ReconcileBundle
    runner: LiveTelegramRunner
    operator: OperatorCommands
    demo_signal: DemoSignalCommand | None
    sender: ApprovalRequestSender
    health: LiveHealthProducer
    rest_errors: RestErrorCounter
    db_writes: DbWriteTracker
    reconcile_observer: ReconcileObserver
    telegram_observer: TelegramDeliveryObserver
    kill_gate: KillGateSources
    releaser: ReservationReleaser
    scheduler: Scheduler
    specs: tuple[TaskSpec, ...]


class WiringIncomplete(RuntimeError):  # noqa: N818 - a composition error, not an exception family
    """The wiring was used before the start sequence loaded the SAFE_MODE controller."""


class WiringBroken(RuntimeError):  # noqa: N818 - a composition error, not an exception family
    """`check_wiring` named at least one broken link; the start does not proceed (D-05)."""


# --------------------------------------------------------------------------- #
# The assembly.
# --------------------------------------------------------------------------- #


class LiveAssembly:
    """The live objects before and after the SAFE_MODE controller exists (see the module doc)."""

    def __init__(
        self,
        *,
        config: LiveConfig,
        execution_limits: ExecutionLimits,
        binance_limits: BinanceLimits,
        parameter_set: ParameterSet,
        clock: Callable[[], datetime],
        sleep: SleepFn,
        sdk_factory: Callable[..., Any] | None,
        application_factory: Callable[[], Any],
        bot: Any,
        stores: LiveStoreSet,
        repo_root: Path,
        symbols: tuple[str, ...],
        session_id: str,
        engine: Any,
        signal_source: SignalSource,
        exchange_edge: Callable[[ExchangeBundle], ExchangeBundle] | None = None,
    ) -> None:
        if not symbols:
            raise ValueError("a live process needs at least one symbol")
        self.config = config
        self.limits = execution_limits
        self.binance_limits = binance_limits
        self.parameter_set = parameter_set
        self.params: dict[str, Any] = dict(parameter_set.params)
        self.clock = clock
        self.sleep = sleep
        self.application_factory = application_factory
        self.bot = bot
        self.stores = stores
        self.repo_root = repo_root
        self.symbols = symbols
        self.session_id = session_id
        self.engine = engine
        self.signal_source = signal_source
        self.cadences = LiveCadences.from_limits(execution_limits, binance_limits)
        self.executor = StoreExecutor()
        self.spill = LocalSpill(config.spill_dir)
        self.index = ClientIdIndex()
        self.marks = MarkBook()
        self.signal_book = SignalContextBook()
        self.rest_errors = RestErrorCounter()
        self.reconcile_observer = ReconcileObserver()
        self.telegram_observer = TelegramDeliveryObserver()
        self.db_writes = DbWriteTracker(clock=clock)
        self.divergences = StreamDivergenceQueue(max_items=binance_limits.stream.event_queue_max)
        self.initialize_gate_state = False
        self.operator_id: str | None = None
        self.scheduler_task: asyncio.Task[None] | None = None
        self.broken_links: list[str] = []
        self._safe_mode: SafeModeController | None = None
        self._enablement: Any = None
        self._wiring: CompleteLiveWiring | None = None

        journal = stores.journal

        async def write_journal(event: JournalEvent) -> None:
            await self.executor.write(journal.record, event)

        self.record: Callable[[JournalEvent], Awaitable[None]] = self.db_writes.track(write_journal)
        self.alerts = build_alerts(
            journal=journal,
            spill=self.spill,
            limits=execution_limits,
            bot=bot,
            chat_id=config.authorized_chat_id,
            sleep=sleep,
            clock=clock,
        )
        self.exchange = build_exchange(
            mode=config.mode,
            credentials=config.credentials,
            binance_limits=binance_limits,
            execution_limits=execution_limits,
            clock=clock,
            sleep=sleep,
            gate_state_path=config.gate_state_path,
            on_gate_alert=self.alerts.gate_alert,
            sdk_factory=sdk_factory,
        )
        if exchange_edge is not None:
            # The one test seam of the exchange edge (D-04 "fakes only at the edges"): production
            # passes None. It may replace the signed adapter and the public reader, never the gate.
            self.exchange = exchange_edge(self.exchange)
        adapter = self.exchange.adapter
        ttl = timedelta(seconds=int(self.params["commission_rate_ttl_seconds"]))
        self.commission = CommissionCache(
            adapter=adapter,
            clock=clock,
            symbols=symbols,
            ttl=ttl,
            refresh_margin=self.cadences.reconcile_tick,
        )
        self.equity = LiveEquitySource(
            adapter=adapter, clock=clock, limits=execution_limits, quote_asset=QUOTE_ASSET
        )
        self.brackets = BracketCache(adapter=adapter, clock=clock, limits=execution_limits)
        self.config_guard = SymbolConfigGuard(adapter=adapter, target_leverage=TARGET_LEVERAGE)
        self.day_risk = LiveDayRiskService(
            reader=adapter,
            store=stores.day_risk,  # type: ignore[arg-type]
            equity=self.equity,
            clock=clock,
            symbols=symbols,
            quote_asset=QUOTE_ASSET,
            funding_policy=FundingPolicy.TRADES_WITH_UNVERIFIED_FUNDING,  # Phase 21 O-2
            parameter_set=self.params,
            limits=execution_limits,
        )
        self.lot_filters = build_lot_filters(
            adapter=adapter,
            store=stores.lot_filters,
            snapshot_store=stores.snapshots,
            limits=execution_limits,
            clock=clock,
        )
        self.kill_gate = make_kill_gate_sources(
            mode=config.mode,
            system_state=stores.system_state,
            executor=self.executor,
            record=self.record,
            clock=clock,
        )
        self.holder = PrefetchedConfirmInputs()
        self.gtd_clock_margin = timedelta(
            milliseconds=max(
                binance_limits.drift.ahead_limit_ms, binance_limits.drift.behind_limit_ms
            )
        )
        # The desk: DEMO-scoped stores, the reserving D028 save and the intent reader (24-14).
        save_atomic = make_demo_save_atomic(
            approvals=stores.approvals,
            reservations=stores.reservations,
            entities=stores.entities,
            parameter_set=self.params,
            daily_loss_quote=self.day_risk.current_daily_loss_quote,
        )
        self.desk_stores = DemoDeskStores(stores.shadow, save_atomic)
        self.desk = ApprovalDesk(
            self.desk_stores,
            profile=DEMO_CONFIRM_PROFILE,
            clock=clock,
            intent_reader=lambda approval_id: stores.execution_state.get_entry(
                approval_id=approval_id
            ),
        )
        self.reservations = ExecutorReservations(stores.reservations, self.executor)
        # Plan 24-37 (F4, D095): the release of reservations that will never be placed.
        self.releaser = ReservationReleaser(
            reservations=stores.reservations,
            entities=stores.entities,
            intents=stores.execution_state,
            events_for_correlation=stores.journal.list_by_correlation,
            executor=self.executor,
            record=self.record,
        )

    # ---- the lazy view -------------------------------------------------------------------- #

    @property
    def wiring(self) -> CompleteLiveWiring:
        if self._wiring is None:
            raise WiringIncomplete("the SAFE_MODE controller has not been loaded yet")
        return self._wiring

    @property
    def is_complete(self) -> bool:
        return self._wiring is not None

    # ---- step 4: the controllers ------------------------------------------------------------ #

    async def _load_safe_mode(self) -> SafeModeController:
        controller = await self.executor.read(
            functools.partial(
                SafeModeController.load,
                adapter=self.exchange.adapter,
                journal=self.stores.journal,
                state_store=self.stores.safe_mode_state,
                now_utc=self.clock(),
                on_enter=self.alerts.safe_mode_observer,
                spill=self.spill,
            )
        )
        self._safe_mode = controller
        return controller

    async def _start_enablement(self) -> StartEnablement:
        started = await start_disabled(
            journal=self.stores.journal,
            state_store=self.stores.system_state,
            read=self.executor.read,
            write=self.executor.write,
            record=self.record,
            now_utc=self.clock(),
            spill=self.spill,
        )
        self._enablement = started.controller
        if self._safe_mode is not None:
            wiring = self.complete(safe_mode=self._safe_mode, enablement=started.controller)
            # D-05: a wiring with a broken link never starts (this step holds the start).
            self.broken_links = check_wiring(wiring)
            if self.broken_links:
                raise WiringBroken(", ".join(self.broken_links))
        return started

    def complete(self, *, safe_mode: SafeModeController, enablement: Any) -> CompleteLiveWiring:
        """Build every object that needs the controllers and return the immutable wiring."""
        if self._wiring is not None:
            return self._wiring
        self._wiring = self._build_complete(safe_mode, enablement)
        return self._wiring

    # ---- the controller-dependent objects --------------------------------------------------- #

    def _build_complete(self, safe_mode: SafeModeController, enablement: Any) -> CompleteLiveWiring:
        loop = asyncio.get_running_loop()
        clock, limits, stores = self.clock, self.limits, self.stores
        adapter = self.exchange.adapter
        sink = self.alerts.sink
        journal = stores.journal
        pending = stores.pending_actions

        closer = MarketEmergencyCloser(
            adapter=adapter,
            journal=journal,
            safe_mode_controller=safe_mode,
            alert_sink=sink,
            clock=clock,
            limits=limits,
            pending_actions=pending,
            spill=self.spill,
            lot_filters=self.lot_filters,
        )
        watch = build_liquidation_watch(
            brackets=self.brackets,
            fee_rates=self.commission,
            limits=limits,
        )
        coordinator = ProtectionCoordinator(
            adapter=adapter,  # type: ignore[arg-type]
            intent_store=stores.execution_state,
            journal=journal,
            safe_mode_controller=safe_mode,
            alert_sink=sink,
            emergency_closer=closer,
            limits=limits,
            clock=clock,
            pending_actions=pending,
            spill=self.spill,
            restore_required=True,
            liquidation_watch=watch,
        )
        producer = LiveRiskInputProducer(
            adapter=adapter,  # type: ignore[arg-type]
            equity=self.equity,
            day_risk=self.day_risk,
            config_guard=self.config_guard,
            brackets=self.brackets,
            reservations=self.reservations,
            protections=coordinator,
            cost_rates_for=make_cost_rates_for(
                commission_for=self.commission.account_commission_for,
                parameter_set=self.params,
            ),
            parameter_set=self.params,
            execution_limits=limits,
            drift_limits=self.binance_limits.drift,
            alert_sink=sink,
            clock=clock,
            signal_context_for=self.signal_book.lookup,
            # Plan 24-37 (F3, D095): the verified snapshot is made durable in the write-ahead
            # path, so `restored_plans_builder` finds it after a restart.
            snapshot_recorder=stores.snapshots.record,
        )
        service = ExecutionService(
            loop=loop,
            token_for=self.desk.approve_token_for,
            inputs=producer,
            adapter=adapter,  # type: ignore[arg-type]
            safe_mode_controller=safe_mode,
            journal=journal,
            enablement=enablement,
            intent_store=stores.execution_state,
            index=self.index,
            clock=clock,
            authorized_chat_id=self.config.authorized_chat_id,
            run_sync=self.executor.write,
            on_refused=self.releaser.release_refused,
        )

        persistence = StreamPersistence(
            executor=self.executor,
            store=stores.entities,
            database=stores.db,
            intents=stores.execution_state,
            journal=journal.record,
            clock=clock,
            correlation_id=f"live-stream-{self.session_id}",
        )

        async def snapshot() -> object:
            return {
                "positions": await adapter.snapshot_positions(),
                "orders": await adapter.snapshot_open_normal_orders(),
                "algo_orders": await adapter.snapshot_open_algo_orders(),
            }

        divergences = self.divergences
        stream = build_stream(
            exchange=self.exchange,
            stream_limits=self.binance_limits.stream,
            clock=clock,
            sleep=self.sleep,
            journal=journal,
            index=self.index,
            coordinator=coordinator,
            equity=self.equity,
            day_risk=self.day_risk,
            executor=self.executor,
            snapshot_provider=snapshot,
            sinks=StreamSinks(
                status_hint_sink=_EvidenceSink(),
                exchange_state_sink=persistence.exchange_state_sink,  # type: ignore[arg-type]
                algo_sink=_EvidenceSink(),
                account_sink=persistence.account_sink,
                divergence_sink=divergences.sink,
            ),
            session_id=self.session_id,
            # fills_reader stays None (plan 24-27B, documented): no production REST read of the
            # fills of one order exists. `user_trades_in_window` (the only trade-list read)
            # returns UserTradeRow, which carries neither price, quantity, side nor position side,
            # so it cannot build the FillEvent the coordinator needs; a reader needs a NEW adapter
            # method mapping the account_trade_list fields, verified against the current Binance
            # docs first. Until then the router's own FILL_TOTAL_MISMATCH divergence (journaled,
            # reconcile compares REST positions) is the only trace of a fill the stream missed.
            fills_reader=None,
            on_state_change=divergences.note_state,
            on_failure=divergences.note_failure,
        )
        # A fill that beats the plan's registration is adopted when the plan registers; the wake
        # runs the protection step at once instead of at the next tick.
        coordinator.set_wake(stream.wake.set)
        supervisor = stream.supervisor

        feeds = LiveFeedSource(
            supervisor=supervisor, marks=self.marks, clock=clock, symbols=self.symbols
        )
        plan_store = stores.entities
        reconcile = build_reconcile(
            adapter=adapter,
            gate=self.exchange.gate,
            safe_mode=safe_mode,
            intent_store=stores.execution_state,
            coordinator=coordinator,
            closer=closer,
            alerts=sink,
            journal=journal,
            limits=limits,
            binance_limits=self.binance_limits,
            feeds=feeds,
            stream=divergences,
            lot_filters=self.lot_filters,
            pending_actions=pending,
            plan_store=plan_store,
            on_entry_resolved=coordinator.note_entry_resolved,  # type: ignore[arg-type]
        )

        bot = self.bot

        async def reply(chat_id: int, text: str) -> None:
            await bot.send_message(chat_id=chat_id, text=text)

        operator = OperatorCommands(
            authorized_chat_id=self.config.authorized_chat_id,
            authorized_user_ids=self.config.authorized_user_ids,
            controller=safe_mode,
            enablement=enablement,
            coordinator=coordinator,
            intent_store=stores.execution_state,
            pending_actions=pending,
            gate=self.exchange.gate,
            stream_state=lambda: supervisor.state,
            journal=journal,
            clock=clock,
            reply=reply,
        )

        # Plan 24-27B: the owner-triggered Demo smoke injection (DEMO only; None elsewhere).
        demo_signal = build_demo_signal_command(
            mode=self.config.mode,
            source=self.signal_source,
            authorized_chat_id=self.config.authorized_chat_id,
            authorized_user_ids=self.config.authorized_user_ids,
            adapter=adapter,
            equity=self.equity,
            risk_rate=self.params["risk_rate"],
            symbol=self.symbols[0],
            record=self.record,
            clock=clock,
            reply=reply,
        )
        command_handlers: dict[str, Callable[..., Awaitable[Any]]] = dict(operator.handlers())
        if demo_signal is not None:
            command_handlers[COMMAND_DEMO_SIGNAL] = demo_signal.handle

        async def prefetch(signal: Any, plan: Any) -> None:
            context = self.signal_book.lookup(plan)
            readings = await read_pre_placement_inputs(adapter, signal.symbol, clock)  # type: ignore[arg-type]
            try:
                inputs = confirm_inputs_from_readings(
                    readings,
                    signal=signal,
                    plan=plan,
                    execution_limits=limits,
                    latest_closed_bar_close=None
                    if context is None
                    else context.latest_closed_bar_close,
                    gtd_clock_margin=self.gtd_clock_margin,
                    protections=coordinator,
                )
            except PositionModeUnavailable:
                return  # nothing is put; the re-check then refuses CONFIRM_INPUTS_UNAVAILABLE
            self.holder.put(plan.trade_plan_id, inputs)

        marks = self.marks

        def mark_price(symbol: str) -> Decimal | None:
            reading = marks.reading(symbol)
            return None if reading is None else reading.mark_price

        runner = LiveTelegramRunner(
            application_factory=self.application_factory,
            desk=self.desk,
            stores=stores.shadow,
            profile=DEMO_CONFIRM_PROFILE,
            clock=clock,
            bot=bot,
            sleep=self.sleep,
            service=service,
            executor=self.executor,
            authorized_chat_id=self.config.authorized_chat_id,
            authorized_user_ids=self.config.authorized_user_ids,
            error_journal=stores.shadow.record_journal,
            mark_price=mark_price,
            validity_rule=functools.partial(
                check_remaining_validity,
                min_remaining_validity_seconds=limits.min_remaining_validity_seconds,
                gtd_clock_margin=self.gtd_clock_margin,
            ),
            recheck=make_confirm_recheck(prefetched_provider(self.holder)),
            prefetch=prefetch,
            command_handlers=command_handlers,
        )

        sender = ApprovalRequestSender(
            desk=self.desk,
            bot=bot,
            chat_id=self.config.authorized_chat_id,
            entities=stores.entities,
            intents=stores.execution_state,
            protections=coordinator.protections,
            positions_reader=AdapterPositionsReader(adapter),
            approvals_reader=make_open_demo_approvals_reader(stores.shadow),
            money_for=build_request_money,
            clock=clock,
            sleep=self.sleep,
            journal=journal.record,
            register_reservation=make_reservation_registrar(stores.reservations),
            run_sync=self.executor.write,
            run_read=self.executor.read,
        )

        thresholds = LiveHealthThresholds.from_limits(
            limits,
            self.binance_limits,
            rest_max_error_rate=REST_MAX_ERROR_RATE,
            db_write_max_age=DB_WRITE_MAX_AGE,
        )
        health = LiveHealthProducer(
            mode=self.config.mode,
            # D056 (2): DEMO is the explicit Demo mode in which DEGRADED may run; the candle check
            # is DEGRADED by design here (no candle feed), so without the flag no DEMO enables.
            # LIVE can never carry the flag (the producer refuses it).
            demo_degraded_allowed=self.config.mode is Environment.DEMO,
            symbols=self.symbols,
            marks=marks,
            stream=supervisor,
            rest_errors=self.rest_errors,
            reconcile=self.reconcile_observer,
            db_writes=self.db_writes,
            telegram=self.telegram_observer,
            thresholds=thresholds,
            stream_halted_reason=divergences.halted_reason,
        )

        partial_wiring = _Parts(
            coordinator=coordinator,
            runner=runner,
            sender=sender,
            health=health,
            reconcile=reconcile,
            stream=stream,
            enablement=enablement,
            safe_mode=safe_mode,
            producer=producer,
            service=service,
        )
        specs = self._specs(partial_wiring)
        scheduler = Scheduler(
            clock=clock,
            sleep=self.sleep,
            record=self._record_task,
            specs=specs,
            record_duration=self._record_task_duration,
            duration_summary_interval=self.cadences.duration_summary_interval,
        )
        return CompleteLiveWiring(
            mode=self.config.mode,
            clock=clock,
            executor=self.executor,
            stores=stores,
            spill=self.spill,
            alerts=self.alerts,
            exchange=self.exchange,
            marks=marks,
            commission=self.commission,
            equity=self.equity,
            day_risk=self.day_risk,
            brackets=self.brackets,
            lot_filters=self.lot_filters,
            index=self.index,
            signal_book=self.signal_book,
            signal_source=self.signal_source,
            safe_mode=safe_mode,
            enablement=enablement,
            closer=closer,
            coordinator=coordinator,
            desk=self.desk,
            producer=producer,
            service=service,
            stream=stream,
            persistence=persistence,
            divergences=divergences,
            reconcile=reconcile,
            runner=runner,
            operator=operator,
            demo_signal=demo_signal,
            sender=sender,
            health=health,
            rest_errors=self.rest_errors,
            db_writes=self.db_writes,
            reconcile_observer=self.reconcile_observer,
            telegram_observer=self.telegram_observer,
            kill_gate=self.kill_gate,
            releaser=self.releaser,
            scheduler=scheduler,
            specs=specs,
        )

    async def _record_task(self, event: Any) -> None:
        # The journal row first; a `stall` event then also raises TASK_STALLED (D111). The alert
        # runs in a `finally` so a failing journal write does not lose it.
        try:
            await self.record(task_event_journal(event))
        finally:
            alert_task_stall(event, self.alerts.sink)

    async def _record_task_duration(self, summary: Any) -> None:
        # D112: observe only and never an alert (no sink call). A write failure propagates to
        # the scheduler, which logs it by class name and goes on.
        await self.record(task_duration_journal(summary))

    # ---- the scheduler specs ---------------------------------------------------------------- #

    def _specs(self, parts: _Parts) -> tuple[TaskSpec, ...]:
        clock, cadences = self.clock, self.cadences
        adapter = self.exchange.adapter
        errors = self.rest_errors
        coordinator = parts.coordinator

        def clock_ms() -> int:
            return int(clock().timestamp() * 1000)

        protection = errors.wrap(make_protection_step(coordinator, parts.stream.fanout))

        async def reconcile() -> None:
            service = parts.service
            if service.outstanding or service.take_settling():
                return  # a placement is in flight or has just ended: its rows are catching up
            await self._reconcile_tick(clock())

        async def drift() -> None:
            await remeasure_drift(self.exchange, clock_ms=clock_ms, now_utc=clock)

        async def marks() -> None:
            await refresh_marks(reader=self.exchange.public, marks=self.marks, symbols=self.symbols)

        async def commission() -> None:
            await self.commission.refresh_due()

        async def day_risk() -> None:
            await backfill_day_risk(self.day_risk, clock())
            # The day opens here, not at placement: the reservation at APPROVE needs its row.
            await parts.producer.open_day()

        async def confirm_sweep() -> None:
            await parts.runner.finalize_expired_once(clock())

        async def reservation_sweep() -> None:
            await self.releaser.sweep_once(clock())

        async def alert_drain() -> None:
            report = await drain_once(self.alerts)
            self.telegram_observer.note_send_report(report)

        async def health_tick() -> None:
            await health_tick_once(parts.health, now_utc=clock(), record=self.record)
            await kill_gate_tick_once(
                controller=parts.enablement,
                source=self.kill_gate.for_task,
                now_utc=clock(),
                persist=self._persist_enablement,
            )

        async def liveness() -> None:
            self._write_liveness()

        plan_store = ExecutorPlanStore(self.stores.entities, self.executor)

        async def scheduled_cancel() -> None:
            await cancel_expired_entries_once(
                coordinator=coordinator,
                plan_store=plan_store,
                adapter=adapter,  # type: ignore[arg-type]
                journal=self.stores.journal,
                spill=self.spill,
                now_utc=clock(),
            )

        async def pump() -> None:
            while True:
                request = await self.signal_source.next_request()
                if request is None:
                    return
                self.signal_book.put(request)
                await parts.sender.send_request(request)

        return (
            TaskSpec(
                TASK_PROTECTION,
                protection,
                cadences.protection_step,
                wake=parts.stream.wake,
                stall_after_seconds=cadences.protection_stall_after_seconds,
            ),
            TaskSpec(TASK_RECONCILE, errors.wrap(reconcile), cadences.reconcile_tick),
            TaskSpec(TASK_DRIFT, drift, cadences.drift_remeasure),
            TaskSpec(TASK_MARKS, marks, cadences.reconcile_tick),
            TaskSpec(TASK_COMMISSION, errors.wrap(commission), cadences.reconcile_tick),
            TaskSpec(TASK_DAY_RISK, day_risk, cadences.day_risk_backfill),
            TaskSpec(TASK_CONFIRM_SWEEP, confirm_sweep, cadences.confirm_ttl_sweep),
            # The expiry sweep of unplaced reservations runs at the confirm-TTL cadence: the same
            # kind of "something expired" check, no new number (plan 24-37).
            TaskSpec(TASK_RESERVATION_SWEEP, reservation_sweep, cadences.confirm_ttl_sweep),
            TaskSpec(TASK_ALERT_DRAIN, alert_drain, cadences.alert_drain),
            TaskSpec(TASK_HEALTH, health_tick, cadences.health),
            TaskSpec(TASK_LIVENESS, liveness, cadences.liveness_stamp),
            TaskSpec(
                TASK_SCHEDULED_CANCEL,
                errors.wrap(scheduled_cancel),
                cadences.scheduled_cancel_check,
            ),
            TaskSpec(TASK_SIGNAL_PUMP, pump, cadences.reconcile_tick),
        )

    async def _persist_enablement(self) -> None:
        await persist_enablement_snapshot(
            self._enablement,
            state_store=self.stores.system_state,
            write=self.executor.write,
            now_utc=self.clock(),
        )

    def _write_liveness(self) -> None:
        results = self.wiring.scheduler.results()
        tasks = {name: "PASS" if result.healthy else "FAIL" for name, result in results.items()}
        write_live_liveness(
            self.config.liveness_dir,
            mode=self.config.mode.value,
            loop_alive_utc=self.clock(),
            tasks=tasks,
        )

    async def _reconcile_tick(self, now_utc: datetime) -> Any:
        wiring = self.wiring
        report = await reconcile_tick_once(wiring.reconcile, now_utc)
        self.reconcile_observer.note(report)
        return report

    async def _startup_reconcile_tick(self, now_utc: datetime) -> Any:
        """The first tick of a start (D-08 step 8, D094): marks first, then the full tick.

        The scheduler's mark-refresh task has not run yet, so after a restart with a tracked plan
        the tick would judge the mark price of its symbol absent and enter SAFE_MODE STALE_FEED
        although the feed is fine. `refresh_marks` never raises: a failed read leaves the mark
        stale and the tick still enters SAFE_MODE (fail closed).
        """
        await refresh_marks(reader=self.exchange.public, marks=self.marks, symbols=self.symbols)
        return await self._reconcile_tick(now_utc)

    # ---- the start sequence ports ------------------------------------------------------------ #

    def startup_ports(
        self, *, initialize_gate_state: bool = False, operator_id: str | None = None
    ) -> StartupPorts:
        """The ports of `run_start_sequence`, bound to the composed objects (lazily)."""
        stores, clock = self.stores, self.clock
        late_coordinator = LateBound(lambda: self.wiring.coordinator)
        late_closer = LateBound(lambda: self.wiring.closer)
        plans = restored_plans_builder(
            intents=stores.execution_state,
            plan_for=stores.entities.get_trade_plan,
            snapshot_for=stores.snapshots.get,
            transition_events_for=lambda plan_hash: stores.journal.list_by_correlation(
                protection_correlation(plan_hash)
            ),
            index=self.index,
            tp1_quantity_fraction=TP1_QUANTITY_FRACTION,
            snapshot_ttl=timedelta(seconds=int(self.params["constraint_snapshot_ttl_seconds"])),
        )
        attempts = close_attempts_reader(
            plan_hashes=lambda: [e.plan_hash for e in stores.execution_state.restorable_entries()],
            events_for_correlation=stores.journal.list_by_correlation,
        )

        async def unrestored_entries(
            entries: Sequence[UnrestorableEntry], now_utc: datetime
        ) -> None:
            await cancel_unrestored_entries(
                entries=entries,
                adapter=self.exchange.adapter,  # type: ignore[arg-type]
                journal=stores.journal,
                spill=self.spill,
                alerts=self.alerts.sink,
                now_utc=now_utc,
            )

        recovery = RecoveryPorts(
            pending_store=stores.pending_actions,
            coordinator=late_coordinator,
            closer=late_closer,
            restored_plans_builder=plans,
            close_attempts_reader=attempts,
            intent_store=stores.execution_state,
            probe_adapter=self.exchange.adapter,
            journal=stores.journal,
            spill=self.spill,
            unrestored_entries=unrestored_entries,
        )
        return StartupPorts(
            mode=self.config.mode,
            clock=clock,
            record=self.record,
            admitted_config=lambda: {"mode": self.config.mode.value},
            gate_store=self.exchange.gate_store,
            gate=self.exchange.gate,
            initialize_gate_state=initialize_gate_state,
            operator_id=operator_id,
            alembic_revisions=alembic_revisions_reader(
                engine=self.engine, executor=self.executor, repo_root=self.repo_root
            ),
            load_safe_mode=self._load_safe_mode,
            start_enablement=self._start_enablement,
            load_constraint_snapshots=self._probe_snapshots,
            spill_directory=self.config.spill_dir,
            measure_clock_drift=self._measure_drift,
            refresh_exchange_info=self._refresh_exchange_info,
            recovery=recovery,
            reconcile_tick=self._startup_reconcile_tick,
            expire_confirms=lambda now: self.wiring.runner.expire_on_restart(now),
            requeue_alerts=self._requeue_alerts,
            start_stream=lambda: self.wiring.stream.supervisor.start(),
            start_bot=lambda: self.wiring.runner.start(),
            start_scheduler=self._start_scheduler,
            health_verdict=self._health_verdict,
            kill_gate_state=self._kill_gate_for_enable,
            persist_enablement=self._persist_enablement,
        )

    async def _kill_gate_for_enable(self) -> KillGateState | None:
        return await self.kill_gate.for_enable()

    async def _probe_snapshots(self) -> None:
        """Readability probe of the constraint snapshot store (the rebuild reads it per plan)."""
        await self.executor.read(self.stores.snapshots.get, "startup-probe")

    async def _measure_drift(self) -> None:
        guard = self.exchange.drift_guard
        await guard.refresh(
            server_time=self.exchange.adapter.server_time,
            clock_ms=lambda: int(self.clock().timestamp() * 1000),
            now_utc=self.clock,
        )

    async def _refresh_exchange_info(self) -> None:
        await self.exchange.adapter.exchange_info(list(self.symbols))
        for symbol in self.symbols:
            await self.lot_filters.refresh_if_due(symbol, now_utc=self.clock())

    async def _requeue_alerts(self) -> None:
        rows = await self.executor.read(
            self.stores.journal.list_by_correlation, "operational_alerts"
        )
        requeue_at_start(self.alerts, rows)

    async def _start_scheduler(self) -> None:
        wiring = self.wiring
        self.scheduler_task = asyncio.create_task(wiring.scheduler.run())

    async def _health_verdict(self) -> Any:
        wiring = self.wiring
        await refresh_marks(reader=self.exchange.public, marks=self.marks, symbols=self.symbols)
        await wiring.telegram_observer.probe(
            notifier=self.bot,
            chat_id=self.config.authorized_chat_id,
            probe_text=STARTUP_PROBE_TEMPLATE.format(mode=self.config.mode.value),
            now_utc=self.clock(),
            journal=self.stores.journal,
        )
        return await health_tick_once(wiring.health, now_utc=self.clock(), record=self.record)


@dataclass(frozen=True)
class _Parts:
    """The objects `_specs` needs before the `CompleteLiveWiring` exists."""

    coordinator: ProtectionCoordinator
    runner: LiveTelegramRunner
    sender: ApprovalRequestSender
    health: LiveHealthProducer
    reconcile: ReconcileBundle
    stream: StreamBundle
    enablement: Any
    safe_mode: SafeModeController
    producer: LiveRiskInputProducer
    service: ExecutionService


def build_wiring(
    *,
    config: LiveConfig,
    execution_limits: ExecutionLimits,
    binance_limits: BinanceLimits,
    parameter_set: ParameterSet,
    clock: Callable[[], datetime],
    sleep: SleepFn,
    sdk_factory: Callable[..., Any] | None,
    application_factory: Callable[[], Any],
    bot: Any,
    engine: Any,
    repo_root: Path,
    symbols: tuple[str, ...],
    session_id: str,
    stores: LiveStoreSet | None = None,
    signal_source: SignalSource | None = None,
    exchange_edge: Callable[[ExchangeBundle], ExchangeBundle] | None = None,
) -> LiveAssembly:
    """Construct the live process from explicit arguments (D-04).

    `stores` defaults to the PostgreSQL stores over `engine` (nothing connects at construction);
    `signal_source` defaults to the Demo smoke source (plan 24-14). Fakes belong at the edges only
    (SDK factory, application factory, bot, clock, sleep).
    """
    store_set = stores if stores is not None else build_pg_stores(OperationalDatabase(engine))
    source: SignalSource = (
        signal_source
        if signal_source is not None
        else DemoSmokeSignalSource(
            run_id=session_id,
            parameter_set=parameter_set,
            min_remaining_validity_seconds=execution_limits.min_remaining_validity_seconds,
        )
    )
    return LiveAssembly(
        config=config,
        execution_limits=execution_limits,
        binance_limits=binance_limits,
        parameter_set=parameter_set,
        clock=clock,
        sleep=sleep,
        sdk_factory=sdk_factory,
        application_factory=application_factory,
        bot=bot,
        stores=store_set,
        repo_root=repo_root,
        symbols=symbols,
        session_id=session_id,
        engine=engine,
        signal_source=source,
        exchange_edge=exchange_edge,
    )


# --------------------------------------------------------------------------- #
# D-05: the wiring gate.
# --------------------------------------------------------------------------- #


def _same(a: object, b: object) -> bool:
    return a is b


def check_wiring(wiring: CompleteLiveWiring) -> list[str]:
    """The names of the broken links of `wiring` (empty when every link has a production caller).

    ROADMAP criterion 1: the approval request sender fed by the signal-source task, the Telegram
    bot runner whose one handler is `on_callback`, the execution service that is the confirm flow's
    `on_confirmed`, the reconcile loop with the orphan sweeper, the health scheduler task, the
    live risk-input producer feeding the service, and the kill-gate event task toward `disable()`;
    plus D-15 (one REST gate and the drift guard), D-06 (durable SAFE_MODE, the market closer,
    restore required, the liquidation watch) and D-07 (the journal-first alert sink everywhere).
    """
    broken: list[str] = []
    names = {spec.name for spec in wiring.specs}
    scheduler_names = set(getattr(wiring.scheduler, "_state", {}))

    def need(ok: bool, link: str) -> None:
        if not ok:
            broken.append(link)

    need(
        type(wiring.sender) is ApprovalRequestSender
        and getattr(wiring.sender, "_desk", None) is wiring.desk,
        LINK_APPROVAL_SENDER,
    )
    need(TASK_SIGNAL_PUMP in names, LINK_SIGNAL_PUMP)
    need(type(wiring.runner) is LiveTelegramRunner, LINK_BOT_RUNNER)
    handler = getattr(wiring.runner, "handler", None)
    need(
        isinstance(handler, functools.partial) and handler.func is on_callback,
        LINK_CALLBACK_HANDLER,
    )
    need(
        type(wiring.service) is ExecutionService
        and _same(getattr(wiring.runner, "service", None), wiring.service),
        LINK_EXECUTION_SERVICE,
    )
    need(
        type(wiring.producer) is LiveRiskInputProducer
        and _same(getattr(wiring.service, "_inputs", None), wiring.producer),
        LINK_RISK_PRODUCER,
    )
    need(
        type(wiring.reconcile.loop).__name__ == "ReconcileLoop"
        and TASK_RECONCILE in names
        and _same(getattr(wiring.reconcile.loop, "_protection", None), wiring.coordinator)
        and _same(getattr(wiring.reconcile.loop, "_safe_mode", None), wiring.safe_mode),
        LINK_RECONCILE,
    )
    need(
        type(wiring.reconcile.sweeper).__name__ == "OrphanSweeper"
        and _same(getattr(wiring.reconcile.loop, "_sweeper", None), wiring.reconcile.sweeper),
        LINK_SWEEPER,
    )
    resolver = wiring.reconcile.resolver
    need(
        getattr(resolver, "_on_resolved", None) is not None
        and getattr(getattr(resolver, "_on_resolved", None), "__self__", None)
        is wiring.coordinator,
        LINK_RESOLVER,
    )
    need(TASK_HEALTH in names, LINK_HEALTH_TASK)
    need(TASK_HEALTH in names and wiring.kill_gate is not None, LINK_KILL_GATE_TASK)

    gate = wiring.exchange.gate
    adapter = wiring.exchange.adapter
    holders = (
        getattr(adapter, "_rest_gate", None),
        getattr(wiring.exchange.public, "_rest_gate", None),
        getattr(wiring.exchange.listen_keys, "_rest_gate", None),
        getattr(wiring.exchange.probe, "_rest_gate", None),
        getattr(wiring.stream.supervisor, "_gate", None),
        getattr(wiring.operator, "_gate", None),
        getattr(wiring.reconcile.loop, "_gate", None),
    )
    need(all(holder is gate for holder in holders), LINK_ONE_GATE)
    need(
        getattr(adapter, "_drift_guard", None) is wiring.exchange.drift_guard,
        LINK_DRIFT_GUARD,
    )

    sink = wiring.alerts.sink
    sinks = (
        getattr(wiring.coordinator, "_alerts", None),
        getattr(wiring.closer, "_alerts", None),
        getattr(wiring.reconcile.loop, "_alerts", None),
        getattr(wiring.producer, "_alert_sink", None),
    )
    need(
        type(sink) is JournalFirstAlertSink and all(held is sink for held in sinks),
        LINK_ALERT_SINK,
    )
    need(
        type(wiring.closer) is MarketEmergencyCloser
        and _same(getattr(wiring.coordinator, "_closer", None), wiring.closer),
        LINK_CLOSER,
    )
    need(getattr(wiring.coordinator, "_restore_required", None) is True, LINK_RESTORE_REQUIRED)
    watch = getattr(wiring.coordinator, "_liquidation_watch", None)
    need(
        watch is not None and "CLOSE_POSITION" in repr(getattr(watch, "_policy", None)),
        LINK_LIQUIDATION_WATCH,
    )
    need(
        getattr(wiring.safe_mode, "_state_store", None) is not None
        and _same(getattr(wiring.coordinator, "_safe_mode", None), wiring.safe_mode),
        LINK_SAFE_MODE,
    )
    need(names == TASK_NAMES and scheduler_names == TASK_NAMES, LINK_SCHEDULER_SPECS)
    registered = set(getattr(wiring.runner, "_command_handlers", {}))
    expected = set(wiring.operator.handlers())
    if wiring.demo_signal is not None:
        expected.add(COMMAND_DEMO_SIGNAL)
    need(registered == expected and bool(registered), LINK_COMMANDS)
    # The Demo smoke injection exists in DEMO only and feeds the very queue the pump reads.
    demo_ok = (
        wiring.demo_signal is not None
        and wiring.mode is Environment.DEMO
        and _same(wiring.demo_signal.source, wiring.signal_source)
        if wiring.mode is Environment.DEMO
        else wiring.demo_signal is None and COMMAND_DEMO_SIGNAL not in registered
    )
    need(demo_ok, LINK_DEMO_SIGNAL)
    # F4 (plan 24-37): the service hands a refused CONFIRM to the releaser that the sweep task
    # also runs, over the very same stores.
    need(
        getattr(wiring.service, "_on_refused", None) == wiring.releaser.release_refused
        and TASK_RESERVATION_SWEEP in names,
        LINK_RESERVATION_RELEASE,
    )
    # F3 (plan 24-37): the producer hands the manager the write-once snapshot store's `record`.
    need(
        getattr(wiring.producer, "_snapshot_recorder", None) == wiring.stores.snapshots.record,
        LINK_SNAPSHOT_RECORDER,
    )
    return broken


__all__ = [
    "DB_WRITE_MAX_AGE",
    "LINK_ALERT_SINK",
    "LINK_APPROVAL_SENDER",
    "LINK_BOT_RUNNER",
    "LINK_CALLBACK_HANDLER",
    "LINK_CLOSER",
    "LINK_COMMANDS",
    "LINK_DEMO_SIGNAL",
    "LINK_DRIFT_GUARD",
    "LINK_EXECUTION_SERVICE",
    "LINK_HEALTH_TASK",
    "LINK_KILL_GATE_TASK",
    "LINK_LIQUIDATION_WATCH",
    "LINK_ONE_GATE",
    "LINK_RECONCILE",
    "LINK_RESOLVER",
    "LINK_RESERVATION_RELEASE",
    "LINK_RESTORE_REQUIRED",
    "LINK_RISK_PRODUCER",
    "LINK_SAFE_MODE",
    "LINK_SCHEDULER_SPECS",
    "LINK_SIGNAL_PUMP",
    "LINK_SNAPSHOT_RECORDER",
    "LINK_SWEEPER",
    "REST_MAX_ERROR_RATE",
    "TASK_NAMES",
    "CompleteLiveWiring",
    "LiveAssembly",
    "LiveStoreSet",
    "LiveStores",
    "LiveWiring",
    "WiringBroken",
    "WiringIncomplete",
    "build_execution_path",
    "build_pg_stores",
    "build_wiring",
    "check_wiring",
]
