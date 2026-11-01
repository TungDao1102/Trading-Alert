"""The start sequence of the live process (plan 24-26; D-08, D-09, OPS-03, G4-029, row 43).

The order of a start is what makes a restart safe: no stream event and no button press is handled
before the intents, the protections and SAFE_MODE are rebuilt, and nothing can be placed before a
reconcile tick has compared the local state with Binance. The sequence is DATA: `START_STEPS` is
the ordered tuple of step names and `run_start_sequence` runs them in that order, journaling one
`LIVE_STARTUP_STEP` row per step (name, outcome, a reason code; never a message, a path or a value).

Groups, as numbered in D-08 (`START_STEP_GROUP`):

1. CONFIG: the admitted configuration and mode (already admitted by `parse_live_environment`).
2. GATE: the REST gate. `FileGateStateStore.initialize` runs ONLY with `--initialize-gate-state`
   and an operator id, and only when no state file exists (a corrupt one counts as existing: it is
   never re-initialized silently); a missing file without the flag is "unknown", not a fresh
   install, and holds. `gate.restore()` runs before any REST call and must report
   RESTORED_DURABLE.
3. ALEMBIC: the database is at the code's single head (read-only; `create_all` is never used).
4. SAFE_MODE, ENABLEMENT, SNAPSHOTS, SPILL_SENTINEL: the durable SAFE_MODE controller (a store
   failure starts it IN SAFE_MODE), a DISABLED enablement controller (a persisted "enabled" is
   never trusted), the constraint snapshots, and the spill sentinel check (20-DEFERRED row 43).
5. CLOCK_DRIFT. 6. EXCHANGE_INFO (exchange info and the lot filters). 7. RECOVERY
   (`run_startup_recovery`, the restored-plans and close-attempts glue below). 8. RECONCILE (one
   full tick).
9. CONFIRM_EXPIRY, ALERT_REQUEUE, STREAM, BOT, SCHEDULER, then HEALTH and ENABLE (DEMO only).

Failure classes (fail closed):

* A failure in groups 1 to 3, or in SAFE_MODE or ENABLEMENT (no controller to run on), HOLDS: the
  outcome is `admitted=False` with the step and a reason code and nothing is started.
* Any other failure continues in SAFE_MODE: entries are blocked, monitoring (reconcile, stream,
  scheduler) keeps running, and `enable_demo` is never called. SAFE_MODE exit stays manual. A
  failing step enters SAFE_MODE with reason `STARTUP_<STEP>_FAILED` (or the step's own reason) only
  when the controller is not in SAFE_MODE yet, so a more informative persisted reason is kept.
* The first journal rows (groups 1 to 3) are buffered until the Alembic check passes, because the
  journal table may not exist before it; on a hold they go to the log only.

The restart rehydrate glue (`restored_plans_builder`, `close_attempts_reader`,
`rebuild_client_id_index`) rebuilds the coordinator's `RestingEntry` records and the client-id
index from the intent store, the persisted plans and constraint snapshots, and the journal. An
entry whose send result is unknown is restored with `entry_state_unknown=True`; it stays UNKNOWN
with SAFE_MODE (D080), never closed as REJECTED by this module.

The module reads no clock: every time is injected. It places, cancels and closes nothing.
"""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Protocol

import structlog

from src.adapters.binance_client import Environment
from src.adapters.binance_ratelimit_gate import GateRecoveryStatus
from src.domain.enums import ExecutionIntentStatus, KillGateState, OrderRole
from src.domain.journal import JournalEvent, content_hash_event_id
from src.domain.trade_plan import TradePlan
from src.execution.binding import take_profit_levels
from src.execution.constraint_snapshot import PlanConstraintSnapshot
from src.execution.emergency_close import plan_hash_of_close_event
from src.execution.intent_recovery import IntentProbeAdapter
from src.execution.intent_store import ExecutionIntentStore, IntentRecord
from src.execution.order_ids import derive_client_order_id
from src.execution.pending_actions import PendingActionStore
from src.execution.placement import (
    derive_sl_trigger_price,
    quantize_price,
    sl_trigger_rounding,
)
from src.execution.pre_placement import good_till_date_ms
from src.execution.protection import (
    POSITION_MODE_ONE_WAY,
    SAFE_MODE_DB_FAILURE,
    SAFE_MODE_RESTORE_INCONSISTENT,
    RestingEntry,
)
from src.execution.protection_rebuild import RestoredPlan, rebuild_plan
from src.live.enablement import EnableOutcome, Persist, StartEnablement, enable_demo
from src.live.order_index import ClientIdIndex
from src.ops.health import HealthVerdict
from src.reconcile.loop import TICK_COMPARED, TickReport
from src.reconcile.startup import (
    CloseAttemptsReader,
    PlansBuilder,
    RestorableCloser,
    RestorableCoordinator,
    SafeModeLike,
    SpillReader,
    SpillReplay,
    SpillRowsFor,
    StartupReport,
    run_startup_recovery,
)

log = structlog.get_logger(__name__)

EVENT_STARTUP_STEP: Final = "LIVE_STARTUP_STEP"

# --------------------------------------------------------------------------- #
# The steps.
# --------------------------------------------------------------------------- #

STEP_CONFIG: Final = "CONFIG"
STEP_GATE: Final = "GATE"
STEP_ALEMBIC: Final = "ALEMBIC"
STEP_SAFE_MODE: Final = "SAFE_MODE"
STEP_ENABLEMENT: Final = "ENABLEMENT"
STEP_SNAPSHOTS: Final = "SNAPSHOTS"
STEP_SPILL_SENTINEL: Final = "SPILL_SENTINEL"
STEP_CLOCK_DRIFT: Final = "CLOCK_DRIFT"
STEP_EXCHANGE_INFO: Final = "EXCHANGE_INFO"
STEP_RECOVERY: Final = "RECOVERY"
STEP_RECONCILE: Final = "RECONCILE"
STEP_CONFIRM_EXPIRY: Final = "CONFIRM_EXPIRY"
STEP_ALERT_REQUEUE: Final = "ALERT_REQUEUE"
STEP_STREAM: Final = "STREAM"
STEP_BOT: Final = "BOT"
STEP_SCHEDULER: Final = "SCHEDULER"
STEP_HEALTH: Final = "HEALTH"
STEP_ENABLE: Final = "ENABLE"

#: The fixed order of a start (D-08). Nothing is placed before the last step completes.
START_STEPS: Final[tuple[str, ...]] = (
    STEP_CONFIG,
    STEP_GATE,
    STEP_ALEMBIC,
    STEP_SAFE_MODE,
    STEP_ENABLEMENT,
    STEP_SNAPSHOTS,
    STEP_SPILL_SENTINEL,
    STEP_CLOCK_DRIFT,
    STEP_EXCHANGE_INFO,
    STEP_RECOVERY,
    STEP_RECONCILE,
    STEP_CONFIRM_EXPIRY,
    STEP_ALERT_REQUEUE,
    STEP_STREAM,
    STEP_BOT,
    STEP_SCHEDULER,
    STEP_HEALTH,
    STEP_ENABLE,
)

#: The D-08 group number (1 to 9) of every step, journaled with the row.
START_STEP_GROUP: Final[Mapping[str, int]] = {
    STEP_CONFIG: 1,
    STEP_GATE: 2,
    STEP_ALEMBIC: 3,
    STEP_SAFE_MODE: 4,
    STEP_ENABLEMENT: 4,
    STEP_SNAPSHOTS: 4,
    STEP_SPILL_SENTINEL: 4,
    STEP_CLOCK_DRIFT: 5,
    STEP_EXCHANGE_INFO: 6,
    STEP_RECOVERY: 7,
    STEP_RECONCILE: 8,
    STEP_CONFIRM_EXPIRY: 9,
    STEP_ALERT_REQUEUE: 9,
    STEP_STREAM: 9,
    STEP_BOT: 9,
    STEP_SCHEDULER: 9,
    STEP_HEALTH: 9,
    STEP_ENABLE: 9,
}

#: Failure here HOLDS the process (nothing is started): there is no safe state to continue in.
HOLD_STEPS: Final[frozenset[str]] = frozenset(
    {STEP_CONFIG, STEP_GATE, STEP_ALEMBIC, STEP_SAFE_MODE, STEP_ENABLEMENT}
)
#: Steps whose journal rows wait for the Alembic check (the journal table may not exist before it).
_BUFFERED_STEPS: Final[frozenset[str]] = frozenset({STEP_CONFIG, STEP_GATE, STEP_ALEMBIC})

OUTCOME_OK: Final = "OK"
OUTCOME_FAILED: Final = "FAILED"
OUTCOME_HELD: Final = "HELD"
OUTCOME_SKIPPED: Final = "SKIPPED"
OUTCOME_REFUSED: Final = "REFUSED"

# Reason codes (fixed vocabulary; the journal row carries a code, never a message).
CODE_GATE_STATE_EXISTS: Final = "GATE_STATE_EXISTS"
CODE_GATE_STATE_MISSING: Final = "GATE_STATE_MISSING"
CODE_OPERATOR_ID_MISSING: Final = "OPERATOR_ID_MISSING"
CODE_GATE_NOT_RESTORED: Final = "GATE_NOT_RESTORED"
CODE_ALEMBIC_MISMATCH: Final = "ALEMBIC_HEAD_MISMATCH"
CODE_ALEMBIC_UNREADABLE: Final = "ALEMBIC_UNREADABLE"
CODE_ENABLEMENT_NOT_DISABLED: Final = "ENABLEMENT_NOT_DISABLED"
CODE_SPILL_SENTINEL_MISSING: Final = "SPILL_SENTINEL_MISSING"
CODE_RECOVERY_INCOMPLETE: Final = "RECOVERY_INCOMPLETE"
CODE_RECONCILE_NOT_CLEAN: Final = "RECONCILE_NOT_CLEAN"
CODE_STEP_FAILED: Final = "STEP_FAILED"
CODE_JOURNAL_FAILED: Final = "JOURNAL_WRITE_FAILED"
CODE_LIVE_HUMAN_ENABLE: Final = "LIVE_KEEPS_HUMAN_ENABLE"
CODE_BLOCKED_SAFE_MODE: Final = "BLOCKED_SAFE_MODE"
CODE_BLOCKED_STEP_FAILED: Final = "BLOCKED_STEP_FAILED"
CODE_HEALTH_UNAVAILABLE: Final = "HEALTH_UNAVAILABLE"

SPILL_SENTINEL_NAME: Final = ".spill-initialized"
_SPILL_SENTINEL_SCHEMA: Final = 1

PROTECTION_CORRELATION_PREFIX: Final = "protection_"
CLOSE_CORRELATION_PREFIX: Final = "emergency_close_"

_PROTECTIVE_ROLES: Final[tuple[OrderRole, ...]] = (
    OrderRole.STOP_LOSS,
    OrderRole.TAKE_PROFIT_1,
    OrderRole.TAKE_PROFIT_2,
)
_UNKNOWN_SEND_STATES: Final[frozenset[ExecutionIntentStatus]] = frozenset(
    {ExecutionIntentStatus.SENT, ExecutionIntentStatus.UNKNOWN}
)
_RESTORABLE_STATES: Final[frozenset[ExecutionIntentStatus]] = frozenset(
    {ExecutionIntentStatus.SENT, ExecutionIntentStatus.UNKNOWN, ExecutionIntentStatus.ACKED}
)
_MILLISECOND: Final = timedelta(milliseconds=1)
_UNIX_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def protection_correlation(plan_hash: str) -> str:
    """The journal correlation id of a plan's `PROTECTION_TRANSITION` rows."""
    return f"{PROTECTION_CORRELATION_PREFIX}{plan_hash}"


def close_correlation(plan_hash: str) -> str:
    """The journal correlation id of a plan's `EMERGENCY_CLOSE` rows."""
    return f"{CLOSE_CORRELATION_PREFIX}{plan_hash}"


# --------------------------------------------------------------------------- #
# Ports.
# --------------------------------------------------------------------------- #

type Port = Callable[[], object]
type JournalRecord = Callable[[JournalEvent], Awaitable[None]]


class StartupRefused(Exception):  # noqa: N818 - a refusal of the start, not an error family
    """A step refuses with a fixed `code`; `message` is fixed text built by this module only."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


class StartupStepFailed(Exception):  # noqa: N818 - a step outcome, not an error family
    """A degrade-class step failed: `code` is journaled, `safe_mode_reason` is the SAFE_MODE one."""

    def __init__(self, code: str, safe_mode_reason: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.safe_mode_reason = safe_mode_reason


class GateStateStoreLike(Protocol):
    """`FileGateStateStore` as the sequence uses it."""

    def inspect(self) -> Any: ...

    def initialize(self, *, now_utc: datetime, operator_id: str) -> object: ...


class RestorableGate(Protocol):
    """`RestRateLimitGate.restore` (the status of its restart recovery)."""

    def restore(self) -> GateRecoveryStatus: ...


class SafeModeControllerLike(SafeModeLike, Protocol):
    """The SAFE_MODE controller as the sequence uses it (`enter_safe_mode`, `in_safe_mode`)."""


@dataclass(frozen=True, kw_only=True)
class AlembicRevisions:
    """What the Alembic check compares: the database's revision (None = unstamped) and the head."""

    current: str | None
    head: str


@dataclass(frozen=True, kw_only=True)
class RecoveryPorts:
    """The arguments of `run_startup_recovery` that are objects (SAFE_MODE comes from step 4)."""

    pending_store: PendingActionStore
    coordinator: RestorableCoordinator
    closer: RestorableCloser
    restored_plans_builder: PlansBuilder
    close_attempts_reader: CloseAttemptsReader
    intent_store: ExecutionIntentStore
    probe_adapter: IntentProbeAdapter
    journal: Any
    spill: SpillReader | None
    spill_replay: SpillReplay | None = None


@dataclass(frozen=True, kw_only=True)
class StartupPorts:
    """Every step's callable or object. Plan 24-27 binds them to the composed live objects.

    A step port is a callable that may be sync or async; it raises to fail. The sequence reads no
    clock: `clock` is the injected reading.
    """

    mode: Environment
    clock: Callable[[], datetime]
    record: JournalRecord
    # 1
    admitted_config: Callable[[], Mapping[str, str]]
    # 2
    gate_store: GateStateStoreLike
    gate: RestorableGate
    initialize_gate_state: bool
    operator_id: str | None
    # 3
    alembic_revisions: Callable[[], AlembicRevisions | Awaitable[AlembicRevisions]]
    # 4
    load_safe_mode: Callable[[], SafeModeControllerLike | Awaitable[SafeModeControllerLike]]
    start_enablement: Callable[[], StartEnablement | Awaitable[StartEnablement]]
    load_constraint_snapshots: Port
    spill_directory: Path
    # 5, 6
    measure_clock_drift: Port
    refresh_exchange_info: Port
    # 7
    recovery: RecoveryPorts
    # 8
    reconcile_tick: Callable[[datetime], Awaitable[TickReport]]
    # 9
    expire_confirms: Callable[[datetime], Sequence[str]]
    requeue_alerts: Port
    start_stream: Port
    start_bot: Port
    start_scheduler: Port
    health_verdict: Callable[[], HealthVerdict | Awaitable[HealthVerdict]]
    kill_gate_state: Callable[[], KillGateState | None | Awaitable[KillGateState | None]]
    persist_enablement: Persist | None = None


@dataclass(frozen=True)
class StepRecord:
    """One step's result: the name, `OUTCOME_*` and a reason code (None for a plain OK)."""

    name: str
    outcome: str
    code: str | None = None


@dataclass(frozen=True)
class StartupOutcome:
    """What a start did. Names, counts and codes only; never a message with a value in it."""

    admitted: bool
    held_step: str | None
    held_code: str | None
    held_message: str | None
    safe_mode_reasons: tuple[str, ...]
    safe_mode_errors: tuple[str, ...]
    in_safe_mode: bool
    started_tasks: tuple[str, ...]
    enabled: bool
    enable_reason: str | None
    first_install: bool
    steps: tuple[StepRecord, ...]
    degraded_steps: tuple[str, ...]
    recovery: StartupReport | None
    reconcile: TickReport | None


# --------------------------------------------------------------------------- #
# Spill sentinel, Alembic head (20-DEFERRED row 43; D-08 step 3).
# --------------------------------------------------------------------------- #


def write_spill_sentinel(directory: Path, *, now_utc: datetime) -> None:
    """Write the first-install sentinel into the spill directory (atomic, idempotent).

    The sentinel proves the spill volume existed at the first install: a later start that finds an
    initialized gate state but no sentinel is looking at a volume that was re-created empty.
    """
    target = directory / SPILL_SENTINEL_NAME
    if target.exists():
        return
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    body = json.dumps(
        {"schema": _SPILL_SENTINEL_SCHEMA, "created_at_utc": now_utc.isoformat()},
        sort_keys=True,
    )
    tmp = directory / f".{SPILL_SENTINEL_NAME}.{os.getpid()}.tmp"
    try:
        with open(tmp, "wb") as handle:
            handle.write(body.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def check_spill_sentinel(directory: Path) -> bool:
    """True only when the sentinel exists and parses; a missing or unreadable one is False."""
    try:
        body = json.loads((directory / SPILL_SENTINEL_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(body, dict) and body.get("schema") == _SPILL_SENTINEL_SCHEMA


def alembic_head_matches(*, current: str | None, head: str) -> bool:
    """True when the database is stamped at exactly the code's single head (read-only compare)."""
    return current is not None and current == head


# --------------------------------------------------------------------------- #
# Restart rehydrate glue (G4-029, D-09).
# --------------------------------------------------------------------------- #


class RestoreSourceMissing(RuntimeError):  # noqa: N818 - a fail-closed refusal of the rebuild
    """A restorable entry has no persisted plan or snapshot: the plans cannot be rebuilt."""


class RestoreIntentReader(Protocol):
    """The intent reads the rebuild needs beyond `ExecutionIntentStore` (synchronous).

    `restorable_entries` is every ENTRY row that may still have a live order or a live position:
    SENT, UNKNOWN and ACKED rows (`list_unresolved_intents` returns neither the ACKED rows nor
    the protective rows that were acknowledged). `get_intent` reads one role's row.
    """

    def restorable_entries(self) -> Sequence[IntentRecord]: ...

    def get_intent(self, *, approval_id: str, role: str) -> IntentRecord | None: ...


def resting_entry_from_intent(
    *,
    entry: IntentRecord,
    plan: TradePlan,
    snapshot: PlanConstraintSnapshot,
    tp1_quantity_fraction: Decimal,
    snapshot_ttl: timedelta,
) -> RestingEntry:
    """Rebuild the `RestingEntry` of an ENTRY intent row exactly as the manager built it.

    Prices are derived from the persisted plan and snapshot the way `execute_approved_plan` did
    (snapped SL trigger, raw TP levels); the quantity is the one the intent recorded. A row sent
    with an unknown result (SENT, UNKNOWN) is restored with `entry_state_unknown=True` and the
    `goodTillDate` its plan implies. `registered_at_utc` is the intent's durable time (no clock).

    Raises:
        ValueError: the row is not a restorable ENTRY row of this plan, or lacks a quantity.
    """
    if entry.role != OrderRole.ENTRY.value:
        raise ValueError("only an ENTRY row can be rebuilt as a resting entry")
    if entry.intent_status not in _RESTORABLE_STATES:
        raise ValueError("an entry that was never sent is not restored")
    if entry.plan_hash != plan.plan_hash or entry.trade_plan_id != plan.trade_plan_id:
        raise ValueError("the persisted plan does not belong to this entry row")
    if entry.intended_quantity is None:
        raise ValueError("an entry row without a quantity cannot be restored")
    expected_id = derive_client_order_id(plan_hash=plan.plan_hash, role=OrderRole.ENTRY.value)
    if entry.client_order_id != expected_id:
        raise ValueError("the entry row does not carry the deterministic client id of its plan")
    if entry.side not in ("BUY", "SELL"):
        raise ValueError("the entry row side must be BUY or SELL")
    position_side = "LONG" if entry.side == "BUY" else "SHORT"
    exit_side = "SELL" if entry.side == "BUY" else "BUY"
    sl_trigger = quantize_price(
        price=derive_sl_trigger_price(stop_loss_price=plan.stop_loss_price),
        price_tick_size=snapshot.price_tick_size,
        direction=sl_trigger_rounding(candidate_position_side=position_side),
    )
    tp1_trigger, tp2_trigger = take_profit_levels(plan)
    unknown = entry.intent_status in _UNKNOWN_SEND_STATES
    return RestingEntry(
        approval_id=entry.approval_id,
        trade_plan_id=plan.trade_plan_id,
        plan_hash=plan.plan_hash,
        symbol=entry.symbol,
        side=position_side,
        entry_side=entry.side,
        exit_side=exit_side,
        entry_client_order_id=expected_id,
        entry_quantity=entry.intended_quantity,
        sl_trigger_price=sl_trigger,
        tp1_trigger_price=tp1_trigger,
        tp2_trigger_price=tp2_trigger,
        tp1_quantity_fraction=tp1_quantity_fraction,
        working_type=snapshot.working_type,
        position_mode=POSITION_MODE_ONE_WAY,
        plan_constraint_snapshot=snapshot,
        snapshot_ttl=snapshot_ttl,
        registered_at_utc=entry.intended_at_utc,
        entry_state_unknown=unknown,
        entry_good_till_utc=(_gtd_datetime(plan.expiry_utc) if unknown else None),
    )


def _gtd_datetime(expiry_utc: datetime) -> datetime:
    """The `goodTillDate` the entry was sent with, as a datetime (whole seconds, floored)."""
    return _UNIX_EPOCH + good_till_date_ms(expiry_utc) * _MILLISECOND


def rebuild_client_id_index(
    index: ClientIdIndex, plans: Sequence[RestoredPlan], intents: RestoreIntentReader
) -> int:
    """Register the ids of the restored plans so the first stream frame finds a known order.

    The ENTRY id of every restored plan, and the algo id of every protective row the intent store
    holds. Returns the number of ids registered. Idempotent (the index keeps the first record).
    """
    registered = 0
    for plan in plans:
        entry = plan.entry
        index.register_entry(
            plan_hash=entry.plan_hash,
            client_order_id=entry.entry_client_order_id,
            symbol=entry.symbol,
        )
        registered += 1
        for role in _PROTECTIVE_ROLES:
            row = intents.get_intent(approval_id=entry.approval_id, role=role.value)
            if row is None or row.algo_client_id is None:
                continue
            index.register_algo(
                plan_hash=entry.plan_hash,
                client_algo_id=row.algo_client_id,
                symbol=entry.symbol,
                role=role,
            )
            registered += 1
    return registered


def restored_plans_builder(
    *,
    intents: RestoreIntentReader,
    plan_for: Callable[[str], TradePlan | None],
    snapshot_for: Callable[[str], PlanConstraintSnapshot | None],
    transition_events_for: Callable[[str], Sequence[JournalEvent]],
    index: ClientIdIndex,
    tp1_quantity_fraction: Decimal,
    snapshot_ttl: timedelta,
) -> PlansBuilder:
    """The `restored_plans_builder` of `run_startup_recovery` (Phase 24 wiring, G4-029).

    For every restorable ENTRY row it reads the persisted plan and constraint snapshot, rebuilds
    the `RestingEntry`, and runs `protection_rebuild.rebuild_plan` over the plan's journal rows
    (`transition_events_for`, correlation `protection_<plan_hash>`), its ENTRY and STOP_LOSS rows,
    and the spill rows the recovery hands in. The client-id index is filled before the builder
    returns, so it is complete before the stream starts.

    A missing plan or snapshot raises `RestoreSourceMissing` (recovery then enters SAFE_MODE
    DB_FAILURE and the coordinator stays unrestored, so no entry opens).
    """

    def build(spill_rows_for: SpillRowsFor) -> Sequence[RestoredPlan]:
        plans: list[RestoredPlan] = []
        for entry in intents.restorable_entries():
            if entry.role != OrderRole.ENTRY.value or entry.intent_status not in _RESTORABLE_STATES:
                continue
            plan = plan_for(entry.trade_plan_id)
            snapshot = snapshot_for(entry.trade_plan_id)
            if plan is None or snapshot is None:
                raise RestoreSourceMissing("a restorable entry has no persisted plan or snapshot")
            resting = resting_entry_from_intent(
                entry=entry,
                plan=plan,
                snapshot=snapshot,
                tp1_quantity_fraction=tp1_quantity_fraction,
                snapshot_ttl=snapshot_ttl,
            )
            plans.append(
                rebuild_plan(
                    entry=resting,
                    transition_events=transition_events_for(resting.plan_hash),
                    entry_intent=entry,
                    stop_intent=intents.get_intent(
                        approval_id=entry.approval_id, role=OrderRole.STOP_LOSS.value
                    ),
                    spill_rows=spill_rows_for(resting.plan_hash),
                )
            )
        rebuild_client_id_index(index, plans, intents)
        return plans

    return build


def close_attempts_reader(
    *,
    plan_hashes: Callable[[], Iterable[str]],
    events_for_correlation: Callable[[str], Sequence[JournalEvent]],
) -> CloseAttemptsReader:
    """The `close_attempts_reader` of `run_startup_recovery`: EMERGENCY_CLOSE rows by plan hash.

    `plan_hashes` names the plans to read (the restorable entries' plans);
    `events_for_correlation` is `PgJournalStore.list_by_correlation`. Only events whose own
    correlation names the plan are kept.
    """

    def read() -> Mapping[str, Sequence[JournalEvent]]:
        out: dict[str, list[JournalEvent]] = {}
        for plan_hash in plan_hashes():
            kept = [
                event
                for event in events_for_correlation(close_correlation(plan_hash))
                if plan_hash_of_close_event(event) == plan_hash
            ]
            if kept:
                out[plan_hash] = kept
        return out

    return read


# --------------------------------------------------------------------------- #
# The runner.
# --------------------------------------------------------------------------- #


async def _call(port: Callable[..., Any], *args: Any) -> Any:
    """Call a port that may be sync or async."""
    result = port(*args)
    if inspect.isawaitable(result):
        return await result
    return result


def _step_event(
    step: str, outcome: str, code: str | None, now_utc: datetime, *, sequence: int
) -> JournalEvent:
    document = {
        "code": code,
        "group": START_STEP_GROUP[step],
        "outcome": outcome,
        "sequence": sequence,
        "step": step,
    }
    payload_json = json.dumps(document, separators=(",", ":"), sort_keys=True)
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="live_startup",
            event_type=EVENT_STARTUP_STEP,
            entity_id=step,
            occurred_at_utc=now_utc,
            payload_json=payload_json,
        ),
        occurred_at_utc=now_utc,
        event_type=EVENT_STARTUP_STEP,
        entity_type="LiveStartup",
        entity_id=step,
        correlation_id="live_startup",
        payload_json=payload_json,
    )


@dataclass
class _Run:
    """Mutable bookkeeping of one start (kept out of the public outcome)."""

    ports: StartupPorts
    now_utc: datetime
    steps: list[StepRecord] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    buffered: list[JournalEvent] = field(default_factory=list)
    controller: SafeModeControllerLike | None = None
    enablement: StartEnablement | None = None
    first_install: bool = False
    journal_ready: bool = False
    journal_failed: bool = False
    held: tuple[str, str, str] | None = None
    recovery: StartupReport | None = None
    reconcile: TickReport | None = None
    enable_outcome: EnableOutcome | None = None

    # ---- journal ------------------------------------------------------------------------- #

    async def _write(self, event: JournalEvent) -> None:
        try:
            await self.ports.record(event)
        except Exception as exc:  # noqa: BLE001 - the class name only; the sequence continues
            self.journal_failed = True
            log.error("live.startup.journal_failed", error=type(exc).__name__)

    async def note(self, step: str, outcome: str, code: str | None = None) -> None:
        """Record the step result; rows of the first steps wait for the Alembic check."""
        self.steps.append(StepRecord(name=step, outcome=outcome, code=code))
        log.info("live.startup.step", step=step, outcome=outcome, code=code)
        event = _step_event(step, outcome, code, self.ports.clock(), sequence=len(self.steps))
        if not self.journal_ready and step in _BUFFERED_STEPS:
            self.buffered.append(event)
            return
        await self._flush()
        await self._write(event)

    async def _flush(self) -> None:
        pending, self.buffered = self.buffered, []
        for event in pending:
            await self._write(event)

    async def open_journal(self) -> None:
        """The Alembic check passed: the buffered rows can be written now."""
        self.journal_ready = True
        await self._flush()

    # ---- SAFE_MODE ----------------------------------------------------------------------- #

    def enter_safe_mode(self, reason: str) -> None:
        """Enter SAFE_MODE unless it is already on (a persisted reason is kept); never raises."""
        controller = self.controller
        if controller is None:
            return
        try:
            if controller.in_safe_mode:
                return
            if reason not in self.reasons:
                self.reasons.append(reason)
            controller.enter_safe_mode(reason=reason, now_utc=self.ports.clock())
        except Exception as exc:  # noqa: BLE001 - the flag flips before the save; name the class
            self.errors.append(type(exc).__name__)

    async def degrade(self, step: str, code: str, reason: str | None = None) -> None:
        """A non-hold step failed: SAFE_MODE (entries blocked), monitoring continues."""
        self.degraded.append(step)
        self.enter_safe_mode(reason or f"STARTUP_{step}_FAILED")
        await self.note(step, OUTCOME_FAILED, code)

    async def hold(self, step: str, code: str, message: str) -> None:
        self.held = (step, code, message)
        await self.note(step, OUTCOME_HELD, code)
        log.error("live.startup.held", step=step, code=code)

    # ---- one step ------------------------------------------------------------------------ #

    async def run(
        self,
        step: str,
        body: Callable[[], Awaitable[str | None]],
    ) -> bool:
        """Run a step body; True when it completed. A hold-class failure sets `held`."""
        try:
            code = await body()
        except StartupRefused as refusal:
            if step in HOLD_STEPS:
                await self.hold(step, refusal.code, refusal.message)
            else:
                await self.degrade(step, refusal.code)
            return False
        except StartupStepFailed as failed:
            if step in HOLD_STEPS:
                await self.hold(step, failed.code, "the step failed")
            else:
                await self.degrade(step, failed.code, failed.safe_mode_reason)
            return False
        except Exception as exc:  # noqa: BLE001 - the class name only, never the text
            name = type(exc).__name__
            if step in HOLD_STEPS:
                await self.hold(step, CODE_STEP_FAILED, f"{step} failed ({name})")
            else:
                await self.degrade(step, f"{CODE_STEP_FAILED}:{name}")
            return False
        await self.note(step, OUTCOME_OK, code)
        return True


async def run_start_sequence(ports: StartupPorts, *, now_utc: datetime) -> StartupOutcome:
    """Run the D-08 start sequence once; see the module docstring.

    Args:
        ports: every step's callable or object (plan 24-27 binds them).
        now_utc: the start time, a timezone-aware UTC reading (used for the gate bootstrap, the
            sentinel and the startup recovery; later steps read `ports.clock()`).

    Returns:
        A `StartupOutcome`. `admitted=False` means a hold: nothing was started.

    Raises:
        ValueError: `now_utc` is not timezone-aware.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be a timezone-aware datetime")
    run = _Run(ports=ports, now_utc=now_utc)
    await _drive(run)
    return _outcome(run)


async def _drive(run: _Run) -> None:
    ports = run.ports

    # ---- 1. config ---------------------------------------------------------------------- #
    async def config() -> str | None:
        document = ports.admitted_config()
        if "mode" in document and document["mode"] != ports.mode.value:
            raise StartupRefused("MODE_MISMATCH", "the admitted mode differs from the start mode")
        return None

    if not await run.run(STEP_CONFIG, config):
        return

    # ---- 2. REST gate ------------------------------------------------------------------- #
    async def gate() -> str | None:
        inspection = ports.gate_store.inspect()
        if ports.initialize_gate_state:
            if inspection.exists:
                raise StartupRefused(
                    CODE_GATE_STATE_EXISTS,
                    "--initialize-gate-state refused: a gate state file already exists; "
                    "a gate state is never re-initialized silently",
                )
            operator = ports.operator_id
            if operator is None or operator.strip() == "":
                raise StartupRefused(
                    CODE_OPERATOR_ID_MISSING,
                    "--initialize-gate-state needs --operator-id <id>",
                )
            ports.gate_store.initialize(now_utc=run.now_utc, operator_id=operator)
            run.first_install = True
        elif not inspection.exists:
            raise StartupRefused(
                CODE_GATE_STATE_MISSING,
                "no REST gate state file: this is not treated as a fresh install; run the one-shot "
                "bootstrap once: python -m src.live.runtime --initialize-gate-state "
                "--operator-id <id>",
            )
        status = ports.gate.restore()
        if status is not GateRecoveryStatus.RESTORED_DURABLE:
            raise StartupRefused(
                CODE_GATE_NOT_RESTORED,
                f"the REST gate did not restore a durable state ({status.name})",
            )
        return "INITIALIZED" if run.first_install else "RESTORED"

    if not await run.run(STEP_GATE, gate):
        return

    # ---- 3. Alembic head, read-only ------------------------------------------------------ #
    async def alembic() -> str | None:
        try:
            revisions: AlembicRevisions = await _call(ports.alembic_revisions)
        except Exception as exc:  # noqa: BLE001 - the database could not be read
            raise StartupRefused(
                CODE_ALEMBIC_UNREADABLE,
                f"the database revision could not be read ({type(exc).__name__})",
            ) from None
        if not alembic_head_matches(current=revisions.current, head=revisions.head):
            raise StartupRefused(
                CODE_ALEMBIC_MISMATCH,
                f"database revision {revisions.current} is not the code head {revisions.head}; "
                "run alembic upgrade head",
            )
        return None

    if not await run.run(STEP_ALEMBIC, alembic):
        return
    await run.open_journal()

    # ---- 4. SAFE_MODE, enablement, snapshots, spill sentinel ----------------------------- #
    async def safe_mode() -> str | None:
        run.controller = await _call(ports.load_safe_mode)
        return (
            "IN_SAFE_MODE" if run.controller is not None and run.controller.in_safe_mode else None
        )

    if not await run.run(STEP_SAFE_MODE, safe_mode):
        return

    async def enablement() -> str | None:
        run.enablement = await _call(ports.start_enablement)
        if run.enablement is None or not run.enablement.controller.is_disabled:
            raise StartupRefused(
                CODE_ENABLEMENT_NOT_DISABLED, "the enablement controller must start DISABLED"
            )
        return None

    if not await run.run(STEP_ENABLEMENT, enablement):
        return

    async def snapshots() -> str | None:
        await _call(ports.load_constraint_snapshots)
        return None

    await run.run(STEP_SNAPSHOTS, snapshots)

    async def sentinel() -> str | None:
        if run.first_install:
            write_spill_sentinel(ports.spill_directory, now_utc=run.now_utc)
            return "WRITTEN"
        if not check_spill_sentinel(ports.spill_directory):
            raise StartupStepFailed(CODE_SPILL_SENTINEL_MISSING, SAFE_MODE_RESTORE_INCONSISTENT)
        return None

    await run.run(STEP_SPILL_SENTINEL, sentinel)

    # ---- 5, 6. drift and exchange info ---------------------------------------------------- #
    async def drift() -> str | None:
        await _call(ports.measure_clock_drift)
        return None

    await run.run(STEP_CLOCK_DRIFT, drift)

    async def exchange_info() -> str | None:
        await _call(ports.refresh_exchange_info)
        return None

    await run.run(STEP_EXCHANGE_INFO, exchange_info)

    # ---- 7. startup recovery -------------------------------------------------------------- #
    async def recovery() -> str | None:
        controller = run.controller
        if controller is None:  # unreachable: the SAFE_MODE step holds without a controller
            raise StartupStepFailed(CODE_STEP_FAILED)
        parts = ports.recovery
        report = await run_startup_recovery(
            safe_mode_load=lambda: controller,
            pending_store=parts.pending_store,
            coordinator=parts.coordinator,
            closer=parts.closer,
            restored_plans_builder=parts.restored_plans_builder,
            close_attempts_reader=parts.close_attempts_reader,
            intent_store=parts.intent_store,
            probe_adapter=parts.probe_adapter,
            journal=parts.journal,
            spill=parts.spill,
            now_utc=run.now_utc,
            spill_replay=parts.spill_replay,
        )
        run.recovery = report
        if report.failed_steps or not report.restore_complete:
            raise StartupStepFailed(CODE_RECOVERY_INCOMPLETE, SAFE_MODE_RESTORE_INCONSISTENT)
        return None

    await run.run(STEP_RECOVERY, recovery)

    # ---- 8. one full reconcile tick ------------------------------------------------------- #
    async def reconcile() -> str | None:
        report = await ports.reconcile_tick(ports.clock())
        run.reconcile = report
        clean = (
            report.outcome == TICK_COMPARED
            and report.agreement is True
            and not report.divergences
            and report.failed_source is None
            and not report.action_failures
        )
        if not clean:
            raise StartupStepFailed(CODE_RECONCILE_NOT_CLEAN)
        return None

    await run.run(STEP_RECONCILE, reconcile)

    # ---- 9. expiry, requeue, then the tasks that handle events ---------------------------- #
    async def expiry() -> str | None:
        expired = ports.expire_confirms(ports.clock())
        return f"EXPIRED_{len(expired)}"

    await run.run(STEP_CONFIRM_EXPIRY, expiry)

    async def requeue() -> str | None:
        await _call(ports.requeue_alerts)
        return None

    await run.run(STEP_ALERT_REQUEUE, requeue)

    for name, port in (
        (STEP_STREAM, ports.start_stream),
        (STEP_BOT, ports.start_bot),
        (STEP_SCHEDULER, ports.start_scheduler),
    ):
        if await run.run(name, _starter(port)):
            run.started.append(name)

    await _enable(run)


def _starter(port: Port) -> Callable[[], Awaitable[str | None]]:
    async def start() -> str | None:
        await _call(port)
        return None

    return start


async def _enable(run: _Run) -> None:
    """HEALTH and ENABLE: DEMO only, and only when nothing failed (entries stay blocked else)."""
    ports = run.ports
    if ports.mode is not Environment.DEMO:
        await run.note(STEP_HEALTH, OUTCOME_SKIPPED, CODE_LIVE_HUMAN_ENABLE)
        await run.note(STEP_ENABLE, OUTCOME_SKIPPED, CODE_LIVE_HUMAN_ENABLE)
        return
    controller = run.controller
    in_safe_mode = controller is None or controller.in_safe_mode
    if in_safe_mode or run.degraded or run.journal_failed:
        code = CODE_BLOCKED_SAFE_MODE if in_safe_mode else CODE_BLOCKED_STEP_FAILED
        if run.journal_failed:
            run.enter_safe_mode(SAFE_MODE_DB_FAILURE)
            code = CODE_JOURNAL_FAILED
        await run.note(STEP_HEALTH, OUTCOME_SKIPPED, code)
        await run.note(STEP_ENABLE, OUTCOME_SKIPPED, code)
        return
    if run.enablement is None:  # unreachable: the ENABLEMENT step holds without a controller
        await run.note(STEP_ENABLE, OUTCOME_SKIPPED, CODE_BLOCKED_STEP_FAILED)
        return

    verdict: HealthVerdict | None = None
    try:
        verdict = await _call(ports.health_verdict)
    except Exception as exc:  # noqa: BLE001 - no verdict, no enable; the process stays DISABLED
        log.error("live.startup.health_failed", error=type(exc).__name__)
    if verdict is None:
        await run.note(STEP_HEALTH, OUTCOME_FAILED, CODE_HEALTH_UNAVAILABLE)
        await run.note(STEP_ENABLE, OUTCOME_SKIPPED, CODE_HEALTH_UNAVAILABLE)
        return
    await run.note(STEP_HEALTH, OUTCOME_OK, "NO_TRADE" if verdict.is_no_trade else "OK")

    kill_state: KillGateState | None = None
    try:
        kill_state = await _call(ports.kill_gate_state)
    except Exception as exc:  # noqa: BLE001 - unevaluated: enable_demo refuses and journals it
        log.error("live.startup.kill_gate_unreadable", error=type(exc).__name__)
    outcome = await enable_demo(
        mode=ports.mode,
        controller=run.enablement.controller,
        health_verdict=verdict,
        kill_gate_state=kill_state,
        now_utc=ports.clock(),
        record=ports.record,
        persist=ports.persist_enablement,
    )
    run.enable_outcome = outcome
    await run.note(STEP_ENABLE, OUTCOME_OK if outcome.enabled else OUTCOME_REFUSED, outcome.reason)


def _outcome(run: _Run) -> StartupOutcome:
    held = run.held
    controller = run.controller
    enabled = run.enable_outcome is not None and run.enable_outcome.enabled
    return StartupOutcome(
        admitted=held is None,
        held_step=None if held is None else held[0],
        held_code=None if held is None else held[1],
        held_message=None if held is None else held[2],
        safe_mode_reasons=tuple(run.reasons),
        safe_mode_errors=tuple(run.errors),
        in_safe_mode=controller is not None and controller.in_safe_mode,
        started_tasks=tuple(run.started),
        enabled=enabled,
        enable_reason=None if run.enable_outcome is None else run.enable_outcome.reason,
        first_install=run.first_install,
        steps=tuple(run.steps),
        degraded_steps=tuple(run.degraded),
        recovery=run.recovery,
        reconcile=run.reconcile,
    )


__all__ = [
    "CLOSE_CORRELATION_PREFIX",
    "CODE_ALEMBIC_MISMATCH",
    "CODE_ALEMBIC_UNREADABLE",
    "CODE_BLOCKED_SAFE_MODE",
    "CODE_BLOCKED_STEP_FAILED",
    "CODE_ENABLEMENT_NOT_DISABLED",
    "CODE_GATE_NOT_RESTORED",
    "CODE_GATE_STATE_EXISTS",
    "CODE_GATE_STATE_MISSING",
    "CODE_HEALTH_UNAVAILABLE",
    "CODE_JOURNAL_FAILED",
    "CODE_LIVE_HUMAN_ENABLE",
    "CODE_OPERATOR_ID_MISSING",
    "CODE_RECONCILE_NOT_CLEAN",
    "CODE_RECOVERY_INCOMPLETE",
    "CODE_SPILL_SENTINEL_MISSING",
    "CODE_STEP_FAILED",
    "EVENT_STARTUP_STEP",
    "HOLD_STEPS",
    "OUTCOME_FAILED",
    "OUTCOME_HELD",
    "OUTCOME_OK",
    "OUTCOME_REFUSED",
    "OUTCOME_SKIPPED",
    "PROTECTION_CORRELATION_PREFIX",
    "SPILL_SENTINEL_NAME",
    "START_STEPS",
    "START_STEP_GROUP",
    "AlembicRevisions",
    "GateStateStoreLike",
    "RecoveryPorts",
    "RestorableGate",
    "RestoreIntentReader",
    "RestoreSourceMissing",
    "SafeModeControllerLike",
    "StartupOutcome",
    "StartupPorts",
    "StartupRefused",
    "StartupStepFailed",
    "StepRecord",
    "alembic_head_matches",
    "check_spill_sentinel",
    "close_attempts_reader",
    "close_correlation",
    "protection_correlation",
    "rebuild_client_id_index",
    "restored_plans_builder",
    "resting_entry_from_intent",
    "run_start_sequence",
    "write_spill_sentinel",
]
