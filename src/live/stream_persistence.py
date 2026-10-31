"""Production writers of what the user-data stream says about our orders and positions (24-19).

D-10 / G4-043: migration 0015 gave `orders` and `positions` an exchange event-time column and the
store monotonic updates (`update_order_exchange_state(..., exchange_event_time_utc=)`,
`update_position_snapshot`). This module is their first production caller. The router's
`exchange_state_sink` and `account_sink` are plain SYNCHRONOUS callables on the event loop thread;
they must neither block nor touch the store. Each sink therefore only builds a small immutable job
from the event (memory only) and enqueues it on the `StoreExecutor` writer thread
(`loop.create_task(executor.write(...))`): tasks start in creation order and the writer is one
thread, so the writes of one stream keep their arrival order. All database work, the intent
lookup and the failure journal run on the writer thread.

Order sink (`make_exchange_state_writer`)
  * A client order id that is not one of ours (no `x-` / `xa-` / `xc-` prefix of
    `src.execution.order_ids`) is not persisted as ours (counted `foreign`).
  * No `orders` row for the id yet: the row is inserted from the intent record
    (`IntentSource.intent_for_client_id`), `local_status` NEW, or UNKNOWN when the intent is
    UNKNOWN. No intent, or an intent without a quantity: nothing is invented, the failure is
    journaled (`NO_INTENT`, `NO_QUANTITY`).
  * `update_order_exchange_state` with the event's exchange time `E`. An older `E` is a recorded
    no-op (`stats.stale`); `local_status` is never touched by that call.
  * G4-034 (D051 item i): an Order whose `local_status` is UNKNOWN and that a not-stale stream
    event reports in a known exchange state leaves UNKNOWN in the SAME transaction through
    `transition_order(evidence=ExitEvidence(USER_DATA_EVENT, observed_at=E))`, which journals the
    evidence source and the event time. A status the table does not know changes no local state.

Account sink (`make_account_position_writer`)
  * One transaction per `ACCOUNT_UPDATE` position row, keyed by a deterministic position id of
    (symbol, position side). A first sight inserts an OPEN row (quantity zero is not inserted: a
    flat row of a position never seen carries nothing), then `update_position_snapshot` with `E`.
    Missing break-even or accumulated-realized values are never invented: an existing row keeps
    its stored value, a first sight without them is journaled `MISSING_FIELD` and not inserted.
  * `status` and `closed_at_utc` are untouched, except that a row in UNKNOWN leaves it with
    USER_DATA_EVENT evidence (OPEN, or CLOSED for quantity zero). A reopened position after a
    CLOSED row is a lifecycle matter this snapshot writer does not solve (24-DEFERRED).

Failures are journaled by exception CLASS NAME and the event time only
(`STREAM_PERSISTENCE_FAILURE`),
never by message text; a failing journal is logged and swallowed. The sink call itself cannot fail
on the store: only a missing running loop or a closed executor surfaces, to the router's own sink
failure path. No wall clock is read here: `now_utc` comes from the router update or the injected
clock. The order sink needs `ExchangeStateLike.exchange_event_time_utc`; see the SUMMARY of 24-19
for the router field that carries it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

import structlog

from src.adapters.binance_userdata_events import AccountUpdateEvent, PositionDelta
from src.domain.enums import ExecutionIntentStatus, OrderStatus, PositionStatus
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.order import Order
from src.domain.position import Position
from src.domain.stream_records import EvidenceSource, ExitEvidence
from src.execution.intent_store import IntentRecord
from src.execution.order_ids import SYSTEM_ID_PREFIXES
from src.ops.store_executor import StoreExecutor
from src.persistence.entities import PgTradingEntityStore
from src.persistence.uow import OperationalDatabase

log = structlog.get_logger(__name__)

EXCHANGE = "BINANCE_USDM"
STREAM_PERSISTENCE_FAILURE = "STREAM_PERSISTENCE_FAILURE"
_JOURNAL_PREFIX = "spf"

FAIL_NO_INTENT = "NO_INTENT"
FAIL_NO_QUANTITY = "NO_QUANTITY"
FAIL_MISSING_FIELD = "MISSING_FIELD"

#: The exchange order statuses that map onto the local table (EXPIRED_IN_MATCH is an expiry).
_LOCAL_FOR_EXCHANGE: dict[str, OrderStatus] = {
    "NEW": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "EXPIRED": OrderStatus.EXPIRED,
    "EXPIRED_IN_MATCH": OrderStatus.EXPIRED,
}


class ExchangeStateLike(Protocol):
    """What the order sink reads of the router's `ExchangeStateUpdate`, plus the event time `E`."""

    @property
    def local_order_id(self) -> str: ...

    @property
    def exchange_status(self) -> str: ...

    @property
    def exchange_order_id(self) -> str: ...

    @property
    def now_utc(self) -> datetime: ...

    @property
    def exchange_event_time_utc(self) -> datetime: ...


class IntentSource(Protocol):
    """The intent record behind a client order id (read on the writer thread, never on the loop)."""

    def intent_for_client_id(self, client_order_id: str) -> IntentRecord | None: ...


@dataclass
class WriterStats:
    """Counters of what the writers did (mutated on the writer thread; read for tests and ops)."""

    orders_applied: int = 0
    orders_stale: int = 0
    orders_inserted: int = 0
    unknown_exits: int = 0
    foreign: int = 0
    positions_applied: int = 0
    positions_stale: int = 0
    positions_inserted: int = 0
    positions_flat_skipped: int = 0
    failures: int = 0
    enqueue_failures: int = 0


def is_system_client_id(client_id: str) -> bool:
    return client_id.startswith(SYSTEM_ID_PREFIXES)


def order_id_for(client_order_id: str) -> str:
    """Deterministic `orders.order_id` of a system client order id (64 hex characters)."""
    material = json.dumps(["order", EXCHANGE, client_order_id], separators=(",", ":"))
    return hashlib.sha256(material.encode("ascii")).hexdigest()


def position_id_for(symbol: str, position_side: str) -> str:
    """Deterministic `positions.position_id` of (symbol, position side)."""
    material = json.dumps(["position", EXCHANGE, symbol, position_side], separators=(",", ":"))
    return hashlib.sha256(material.encode("ascii")).hexdigest()


def _millis(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


@dataclass(frozen=True)
class _OrderJob:
    client_order_id: str
    exchange_status: str
    exchange_order_id: str
    now_utc: datetime
    event_time_utc: datetime


@dataclass(frozen=True)
class _PositionJob:
    rows: tuple[PositionDelta, ...]
    now_utc: datetime
    event_time_utc: datetime


class StreamPersistence:
    """The two sinks, the shared task tracker and the counters (see the module docstring)."""

    def __init__(
        self,
        *,
        executor: StoreExecutor,
        store: PgTradingEntityStore,
        database: OperationalDatabase,
        intents: IntentSource,
        journal: Callable[[JournalEvent], None],
        clock: Callable[[], datetime],
        correlation_id: str,
    ) -> None:
        if not isinstance(correlation_id, str) or correlation_id == "":
            raise ValueError("correlation_id must be a non-empty string")
        self._executor = executor
        self._store = store
        self._db = database
        self._intents = intents
        self._journal = journal
        self._clock = clock
        self._correlation_id = correlation_id
        self._tasks: set[asyncio.Task[None]] = set()
        self.stats = WriterStats()

    # -- loop side: memory only ------------------------------------------------------------- #

    def exchange_state_sink(self, update: ExchangeStateLike) -> None:
        """Router `exchange_state_sink`: enqueue one order write (returns before it runs)."""
        client_id = update.local_order_id
        if not is_system_client_id(client_id):
            self.stats.foreign += 1
            return
        job = _OrderJob(
            client_order_id=client_id,
            exchange_status=update.exchange_status,
            exchange_order_id=update.exchange_order_id,
            now_utc=update.now_utc,
            event_time_utc=update.exchange_event_time_utc,
        )
        self._spawn(self._write_order, job)

    def account_sink(self, event: AccountUpdateEvent) -> None:
        """Router `account_sink`: enqueue the position rows of one ACCOUNT_UPDATE."""
        if not event.positions:
            return
        job = _PositionJob(
            rows=event.positions, now_utc=self._clock(), event_time_utc=event.event_time_utc
        )
        self._spawn(self._write_positions, job)

    def _spawn(self, fn: Callable[[Any], None], job: Any) -> None:
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._executor.write(fn, job))
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:  # the job catches its own errors: this is a closed executor
            self.stats.enqueue_failures += 1
            log.error("live.stream_persistence.enqueue_failed", error=type(exc).__name__)

    @property
    def pending(self) -> int:
        return len(self._tasks)

    async def drain(self) -> None:
        """Wait until every enqueued write has finished (shutdown and tests)."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    # -- writer thread ---------------------------------------------------------------------- #

    def _write_order(self, job: _OrderJob) -> None:
        try:
            self._write_order_inner(job)
        except Exception as exc:  # noqa: BLE001 - journaled by class name, the stream goes on
            self._fail("ORDER", job.client_order_id, job.event_time_utc, type(exc).__name__)

    def _write_order_inner(self, job: _OrderJob) -> None:
        store = self._store
        cid = job.client_order_id
        with self._db.transaction() as tx:
            order = store.get_order_by_client_order_id(cid, tx=tx)
            if order is None:
                intent = self._intents.intent_for_client_id(cid)
                if intent is None:
                    self._fail("ORDER", cid, job.event_time_utc, FAIL_NO_INTENT)
                    return
                if intent.intended_quantity is None:
                    self._fail("ORDER", cid, job.event_time_utc, FAIL_NO_QUANTITY)
                    return
                order = _order_from_intent(intent, cid, job)
                store.insert_order(order, tx=tx)
                self.stats.orders_inserted += 1
            result = store.update_order_exchange_state(
                order.order_id,
                exchange_status=job.exchange_status,
                exchange_order_id=job.exchange_order_id,
                now_utc=job.now_utc,
                exchange_event_time_utc=job.event_time_utc,
                tx=tx,
            )
            if result.stale:
                self.stats.orders_stale += 1
                log.info("live.stream_persistence.order_event_stale", order_id=order.order_id)
                return
            target = _LOCAL_FOR_EXCHANGE.get(job.exchange_status)
            if result.entity.local_status is OrderStatus.UNKNOWN and target is not None:
                store.transition_order(
                    order.order_id,
                    target,
                    now_utc=job.now_utc,
                    tx=tx,
                    evidence=self._evidence(
                        f"ORDER_TRADE_UPDATE:{job.exchange_order_id}:{_millis(job.event_time_utc)}",
                        job.event_time_utc,
                    ),
                )
                self.stats.unknown_exits += 1
            self.stats.orders_applied += 1

    def _write_positions(self, job: _PositionJob) -> None:
        for row in job.rows:
            try:
                self._write_position(row, job)
            except Exception as exc:  # noqa: BLE001 - journaled by class name, next row goes on
                self._fail(
                    "POSITION",
                    position_id_for(row.symbol, row.position_side),
                    job.event_time_utc,
                    type(exc).__name__,
                )

    def _write_position(self, row: PositionDelta, job: _PositionJob) -> None:
        store = self._store
        pid = position_id_for(row.symbol, row.position_side)
        with self._db.transaction() as tx:
            stored = store.get_position(pid, tx=tx)
            if stored is None:
                if row.position_amount == 0:
                    self.stats.positions_flat_skipped += 1
                    return
                if row.breakeven_price is None or row.accumulated_realized is None:
                    self._fail("POSITION", pid, job.event_time_utc, FAIL_MISSING_FIELD)
                    return
                stored = _position_from_row(pid, row, job, row.breakeven_price)
                store.insert_position(stored, tx=tx)
                self.stats.positions_inserted += 1
            result = store.update_position_snapshot(
                pid,
                quantity=row.position_amount,
                entry_price=row.entry_price,
                break_even_price=(
                    stored.break_even_price if row.breakeven_price is None else row.breakeven_price
                ),
                unrealized_pnl=row.unrealized_pnl,
                realized_pnl=(
                    stored.realized_pnl
                    if row.accumulated_realized is None
                    else row.accumulated_realized
                ),
                event_time_utc=job.event_time_utc,
                now_utc=job.now_utc,
                tx=tx,
            )
            if result.stale:
                self.stats.positions_stale += 1
                log.info("live.stream_persistence.position_event_stale", position_id=pid)
                return
            if result.entity.status is PositionStatus.UNKNOWN:
                target = PositionStatus.OPEN if row.position_amount != 0 else PositionStatus.CLOSED
                store.transition_position(
                    pid,
                    target,
                    now_utc=job.now_utc,
                    tx=tx,
                    evidence=self._evidence(
                        f"ACCOUNT_UPDATE:{row.symbol}:{_millis(job.event_time_utc)}",
                        job.event_time_utc,
                    ),
                )
                self.stats.unknown_exits += 1
            self.stats.positions_applied += 1

    def _evidence(self, reference: str, observed_at_utc: datetime) -> ExitEvidence:
        return ExitEvidence(
            source=EvidenceSource.USER_DATA_EVENT,
            observed_at_utc=observed_at_utc,
            reference=reference,
            correlation_id=self._correlation_id,
        )

    def _fail(self, entity_type: str, entity_id: str, event_time: datetime, reason: str) -> None:
        """Journal a failure by reason token or exception class name (never message text)."""
        self.stats.failures += 1
        log.warning(
            "live.stream_persistence.failed", entity_type=entity_type, reason=reason, id=entity_id
        )
        try:
            now = self._clock()
            payload = {
                "entity_type": entity_type,
                "event_time_utc": event_time.isoformat(),
                "reason": reason,
            }
            self._journal(
                JournalEvent(
                    journal_event_id=correlated_event_id(
                        prefix=_JOURNAL_PREFIX,
                        correlation_id=self._correlation_id,
                        event_type=STREAM_PERSISTENCE_FAILURE,
                        entity_id=entity_id,
                        step=f"{_millis(event_time)}:{reason}",
                    ),
                    occurred_at_utc=now,
                    event_type=STREAM_PERSISTENCE_FAILURE,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    correlation_id=self._correlation_id,
                    payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    created_at_utc=now,
                )
            )
        except Exception as exc:  # noqa: BLE001 - the log line above is the fallback record
            log.error("live.stream_persistence.journal_failed", error=type(exc).__name__)


def _order_from_intent(intent: IntentRecord, client_order_id: str, job: _OrderJob) -> Order:
    quantity = intent.intended_quantity
    assert quantity is not None  # checked by the caller
    unknown = intent.intent_status is ExecutionIntentStatus.UNKNOWN
    return Order(
        order_id=order_id_for(client_order_id),
        trade_plan_id=intent.trade_plan_id,
        position_id=None,
        parent_order_id=None,
        order_role=intent.role,
        exchange=EXCHANGE,
        symbol=intent.symbol,
        side=intent.side,
        position_side="BOTH",
        order_type="LIMIT",
        time_in_force="GTD",
        quantity=quantity,
        price=intent.intended_price,
        stop_price=None,
        close_position=False,
        reduce_only=False,
        client_order_id=client_order_id,
        exchange_order_id=None,
        algo_client_id=None,
        exchange_status=job.exchange_status,
        local_status=OrderStatus.UNKNOWN if unknown else OrderStatus.NEW,
        submitted_at_utc=intent.sent_at_utc or intent.intended_at_utc,
        updated_at_utc=job.now_utc,
    )


def _position_from_row(
    position_id: str, row: PositionDelta, job: _PositionJob, break_even: Decimal
) -> Position:
    realized = row.accumulated_realized
    assert realized is not None  # checked by the caller
    return Position(
        position_id=position_id,
        symbol=row.symbol,
        position_side=row.position_side,
        mode="ONE_WAY" if row.position_side == "BOTH" else "HEDGE",
        quantity=row.position_amount,
        entry_price=row.entry_price,
        break_even_price=break_even,
        unrealized_pnl=row.unrealized_pnl,
        realized_pnl=realized,
        opened_at_utc=job.event_time_utc,
        updated_at_utc=job.now_utc,
        status=PositionStatus.OPEN,
    )


def make_exchange_state_writer(
    persistence: StreamPersistence,
) -> Callable[[ExchangeStateLike], None]:
    """The router's `exchange_state_sink` over `persistence` (enqueues, never blocks)."""
    return persistence.exchange_state_sink


def make_account_position_writer(
    persistence: StreamPersistence,
) -> Callable[[AccountUpdateEvent], None]:
    """The router's `account_sink` over `persistence` (enqueues, never blocks)."""
    return persistence.account_sink


__all__ = [
    "EXCHANGE",
    "FAIL_MISSING_FIELD",
    "FAIL_NO_INTENT",
    "FAIL_NO_QUANTITY",
    "STREAM_PERSISTENCE_FAILURE",
    "ExchangeStateLike",
    "IntentSource",
    "StreamPersistence",
    "WriterStats",
    "is_system_client_id",
    "make_account_position_writer",
    "make_exchange_state_writer",
    "order_id_for",
    "position_id_for",
]
