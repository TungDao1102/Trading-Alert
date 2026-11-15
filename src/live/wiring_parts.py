"""Small adapters the live composition root binds (plan 24-27; D-04).

Each class or function here closes one gap named in a hand-off of an earlier Phase 24 plan:

- `SignalContextBook`: the in-process lookup behind `LiveRiskInputProducer.signal_context_for`
  (24-16), filled by the signal-source pump from each `SignalRequest`;
- `AdapterPositionsReader`: the exchange side of the approval sender's conflict check (24-14);
- `ExecutorReservations`, `ExecutorPlanStore`: synchronous PostgreSQL reads behind the
  `StoreExecutor` (24-16, 24-21);
- `make_reservation_registrar`: the sender's `register_reservation` over the Phase 21 store (the
  Phase 22 gate invariant 13 pin names `src/live/wiring.py` as its one caller);
- `LateBound`: a forwarding proxy for an object that exists only after the start sequence loaded
  the SAFE_MODE controller (the startup ports are built before step 4);
- `make_kill_gate_sources`: the D092 rule. In DEMO the kill-gate state for `enable_demo` is treated
  as evaluated WITHIN_BUDGET and the rule is journaled on every enable; in every other mode the
  only source is the persisted evaluated state, and its absence keeps the enable refused.
- `alembic_revisions_reader`: the read-only Alembic head check of start step 3.
- `alert_task_stall`: the TASK_STALLED alert of a scheduler `stall` event (D111).
- `task_duration_journal`: the journal row of one bounded duration summary of a scheduler task
  (D112); observe only, never an alert.

No wall clock is read here: every clock is injected.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

import structlog

from src.adapters.binance_client import Environment
from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent, content_hash_event_id
from src.domain.trade_plan import TradePlan
from src.live.approval_sender import ReservationRegistrar
from src.live.risk_inputs import PlanSignalContext
from src.live.scheduler import TaskDurationSummary, TaskEvent
from src.live.signal_source import SignalRequest
from src.live.startup import AlembicRevisions
from src.ops.store_executor import StoreExecutor
from src.persistence.entities import PgTradingEntityStore
from src.persistence.risk_reservations import PgRiskReservationStore
from src.persistence.system_state import PgSystemStateStore
from src.risk.money_at_stake import MoneyAtStake
from src.risk.reservations import ReservationRequest, margin_for_reservation

log = structlog.get_logger(__name__)

EVENT_DEMO_KILL_GATE_RULE = "DEMO_KILL_GATE_RULE_APPLIED"
EVENT_TASK = "LIVE_TASK_EVENT"
# D112: the bounded duration summary row of a scheduler task (never an alert).
EVENT_TASK_DURATION = "LIVE_TASK_DURATION"
# D111: the alert event and its fixed reason for a scheduler `stall` event.
TASK_STALLED_EVENT = "TASK_STALLED"
TASK_STALL_REASON = "STALL_BOUND_EXCEEDED"
DEMO_KILL_GATE_RULE_CODE = "D092_DEMO_ONLY_TREATED_AS_WITHIN_BUDGET"

Record = Callable[[JournalEvent], Awaitable[None]]
KillGateSource = Callable[[], Awaitable[KillGateState | None]]


class SignalContextBook:
    """Plan id -> the persisted Signal and the bar-close price of the request that made it."""

    def __init__(self) -> None:
        self._by_plan: dict[str, PlanSignalContext] = {}

    def put(self, request: SignalRequest) -> None:
        self._by_plan[request.plan.trade_plan_id] = PlanSignalContext(
            signal=request.signal, latest_closed_bar_close=request.bar_close_price
        )

    def lookup(self, plan: TradePlan) -> PlanSignalContext | None:
        return self._by_plan.get(plan.trade_plan_id)

    def __len__(self) -> int:
        return len(self._by_plan)


def _field(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


class AdapterPositionsReader:
    """`PositionsReader` over the signed adapter's REST snapshots (fresh per request)."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    async def open_position_quantity(self, symbol: str) -> Decimal:
        rows = await self._adapter.snapshot_positions()
        if not isinstance(rows, list | tuple):
            raise ValueError("positions snapshot is not a list")
        total = Decimal(0)
        for row in rows:
            if _field(row, "symbol") != symbol:
                continue
            amount = _field(row, "position_amt")
            if not isinstance(amount, Decimal) or not amount.is_finite():
                raise ValueError("position amount is not a finite Decimal")
            total += abs(amount)
        return total

    async def open_entry_order_count(self, symbol: str) -> int:
        rows = await self._adapter.snapshot_open_normal_orders()
        if not isinstance(rows, list | tuple):
            raise ValueError("open orders snapshot is not a list")
        return sum(1 for row in rows if _field(row, "symbol") == symbol)


class ExecutorReservations:
    """The reservation reads of the producer and the margin guard, run behind the executor."""

    def __init__(self, store: PgRiskReservationStore, executor: StoreExecutor) -> None:
        self._store = store
        self._executor = executor

    async def list_counted(self) -> Any:
        return await self._executor.read(self._store.list_counted)

    async def list_margin_claims(self) -> Any:
        return await self._executor.read(self._store.list_margin_claims)


class ExecutorPlanStore:
    """`scheduled_cancel.PlanStore`: the stored plan expiry by plan hash, read via the executor."""

    def __init__(self, entities: PgTradingEntityStore, executor: StoreExecutor) -> None:
        self._entities = entities
        self._executor = executor

    async def expiry_utc_for(self, plan_hash: str) -> datetime | None:
        plan = await self._executor.read(self._entities.get_trade_plan_by_hash, plan_hash)
        return None if plan is None else plan.expiry_utc


def make_reservation_registrar(reservations: PgRiskReservationStore) -> ReservationRegistrar:
    """The sender's `register_reservation`: the REQUESTED row the approval transaction reserves.

    The margin trio follows `margin_for_reservation` (quantity x entry price / leverage), the one
    definition the claims reader re-derives (22-REVIEW WR-07).
    """

    def register(request: SignalRequest, money: MoneyAtStake, now_utc: datetime) -> None:
        reservations.register_request(
            ReservationRequest(
                trade_plan_id=request.plan.trade_plan_id,
                plan_hash=request.plan.plan_hash,
                symbol=request.signal.symbol,
                position_side=money.side,
                quantity=money.quantity,
                realized_risk=request.money_inputs.sized.realized_risk,
                required_margin=margin_for_reservation(
                    quantity=money.quantity, price=money.entry_price, leverage=money.leverage
                ),
                margin_entry_price=money.entry_price,
                margin_leverage=money.leverage,
            ),
            now_utc=now_utc,
        )

    return register


class LateBound:
    """Forwards every attribute to `resolve()`; for objects built after the SAFE_MODE load."""

    def __init__(self, resolve: Callable[[], Any]) -> None:
        object.__setattr__(self, "_resolve", resolve)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_resolve")(), name)


class BotNotBound(RuntimeError):  # noqa: N818 - a composition error, not an exception family
    """A send was attempted before the Telegram application (and its bot) exists."""


class LiveBotProxy:
    """A forwarding `TelegramTextBot`: the real bot exists only once the application does.

    The runner binds it to the application's bot at `start()` (duck-typed `is_bound`, `bind`).
    A send before that raises `BotNotBound` (a send failure, never a silent drop).
    """

    def __init__(self, bot: Any | None = None) -> None:
        self._bot = bot

    def bind(self, bot: Any) -> None:
        self._bot = bot

    @property
    def is_bound(self) -> bool:
        return self._bot is not None

    def _require(self) -> Any:
        if self._bot is None:
            raise BotNotBound("the Telegram bot is not bound yet")
        return self._bot

    async def send_message(
        self, *, chat_id: str | int, text: str, reply_markup: Any = None
    ) -> object:
        return await self._require().send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup
        )

    async def edit_message_text(
        self, *, chat_id: str | int, message_id: int, text: str, reply_markup: Any = None
    ) -> object:
        return await self._require().edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
        )

    async def edit_message_reply_markup(
        self, *, chat_id: str | int, message_id: int, reply_markup: Any = None
    ) -> object:
        return await self._require().edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
        )


def task_event_journal(event: TaskEvent) -> JournalEvent:
    """The journal row of one scheduler outcome change (task name, kind and class name only)."""
    payload = json.dumps(
        {"task": event.task, "kind": event.kind, "error_class": event.error_class},
        sort_keys=True,
        separators=(",", ":"),
    )
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="live_task",
            event_type=EVENT_TASK,
            entity_id=event.task,
            occurred_at_utc=event.at_utc,
            payload_json=payload,
        ),
        occurred_at_utc=event.at_utc,
        event_type=EVENT_TASK,
        entity_type="LiveScheduler",
        entity_id=event.task,
        correlation_id="live_scheduler",
        payload_json=payload,
    )


def task_duration_journal(summary: TaskDurationSummary) -> JournalEvent:
    """The journal row of one scheduler duration summary (D112): a task name and integers only."""
    payload = json.dumps(
        {
            "task": summary.task,
            "runs": summary.runs,
            "total_ms": summary.total_ms,
            "max_ms": summary.max_ms,
            "window_max_ms": summary.window_max_ms,
            "new_max": summary.new_max,
            "window_end": summary.window_end,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="live_task_duration",
            event_type=EVENT_TASK_DURATION,
            entity_id=summary.task,
            occurred_at_utc=summary.at_utc,
            payload_json=payload,
        ),
        occurred_at_utc=summary.at_utc,
        event_type=EVENT_TASK_DURATION,
        entity_type="LiveScheduler",
        entity_id=summary.task,
        correlation_id="live_scheduler",
        payload_json=payload,
    )


class TaskAlertSink(Protocol):
    """The `alert` call of the journal-first alert sink (`JournalFirstAlertSink.alert`)."""

    def alert(self, *, event: str, subject: str, reason: str, now_utc: datetime) -> None: ...


def alert_task_stall(event: TaskEvent, sink: TaskAlertSink) -> bool:
    """Raise the HIGH TASK_STALLED alert for a scheduler `stall` event; True when it was raised.

    Only `kind == "stall"` alerts (the other kinds are journaled and stay quiet). The subject is
    the task name and the reason is fixed, so nothing from the run (no exception text) reaches the
    message. A failing sink is logged by class name and never raised: the watchdog only observes.
    """
    if event.kind != "stall":
        return False
    try:
        sink.alert(
            event=TASK_STALLED_EVENT,
            subject=event.task,
            reason=TASK_STALL_REASON,
            now_utc=event.at_utc,
        )
    except Exception as exc:  # noqa: BLE001 - observe only; class name, never text
        log.error("live.task_stall_alert_failed", error_class=type(exc).__name__)
        return False
    return True


@dataclass(frozen=True, kw_only=True)
class KillGateSources:
    """The two kill-gate readers of the composition (D092).

    `for_enable` is the start sequence's `kill_gate_state` port: in DEMO it journals the rule on
    every call. `for_task` is the periodic check toward `disable()`: it never journals (the task
    can only move toward disabled, so a DEMO WITHIN_BUDGET changes nothing).
    """

    for_enable: KillGateSource
    for_task: KillGateSource


def make_kill_gate_sources(
    *,
    mode: Environment,
    system_state: PgSystemStateStore,
    executor: StoreExecutor,
    record: Record,
    clock: Callable[[], datetime],
) -> KillGateSources:
    """D092: an explicit DEMO-only rule now, the persisted evaluated state in every other mode."""

    async def persisted() -> KillGateState | None:
        return await executor.read(system_state.latest_kill_gate_state)

    if mode is not Environment.DEMO:
        return KillGateSources(for_enable=persisted, for_task=persisted)

    async def demo_enable() -> KillGateState | None:
        now = clock()
        payload = json.dumps(
            {"mode": mode.value, "rule": DEMO_KILL_GATE_RULE_CODE, "state": "WITHIN_BUDGET"},
            sort_keys=True,
            separators=(",", ":"),
        )
        await record(
            JournalEvent(
                journal_event_id=content_hash_event_id(
                    prefix="demo_kill_gate",
                    event_type=EVENT_DEMO_KILL_GATE_RULE,
                    entity_id="kill_gate",
                    occurred_at_utc=now,
                    payload_json=payload,
                ),
                occurred_at_utc=now,
                event_type=EVENT_DEMO_KILL_GATE_RULE,
                entity_type="KillGate",
                entity_id="kill_gate",
                correlation_id="execution_health",
                payload_json=payload,
            )
        )
        return KillGateState.WITHIN_BUDGET

    async def demo_task() -> KillGateState | None:
        return KillGateState.WITHIN_BUDGET

    return KillGateSources(for_enable=demo_enable, for_task=demo_task)


def alembic_revisions_reader(
    *, engine: Any, executor: StoreExecutor, repo_root: Any
) -> Callable[[], Awaitable[AlembicRevisions]]:
    """The read-only Alembic check of start step 3: the database revision and the code head."""

    def read() -> AlembicRevisions:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        config = Config(str(repo_root / "alembic.ini"))
        config.set_main_option("script_location", str(repo_root / "src" / "db" / "alembic"))
        config.set_main_option("path_separator", "os")
        heads = ScriptDirectory.from_config(config).get_heads()
        if len(heads) != 1:
            raise RuntimeError("the Alembic chain does not have exactly one head")
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        return AlembicRevisions(current=current, head=heads[0])

    async def run() -> AlembicRevisions:
        return await executor.read(read)

    return run


__all__ = [
    "DEMO_KILL_GATE_RULE_CODE",
    "EVENT_DEMO_KILL_GATE_RULE",
    "EVENT_TASK",
    "EVENT_TASK_DURATION",
    "AdapterPositionsReader",
    "BotNotBound",
    "ExecutorPlanStore",
    "ExecutorReservations",
    "KillGateSources",
    "LateBound",
    "LiveBotProxy",
    "TASK_STALLED_EVENT",
    "TASK_STALL_REASON",
    "SignalContextBook",
    "TaskAlertSink",
    "alembic_revisions_reader",
    "alert_task_stall",
    "make_kill_gate_sources",
    "make_reservation_registrar",
    "task_duration_journal",
    "task_event_journal",
]
