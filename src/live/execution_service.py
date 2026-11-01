"""The execution service: the one bridge from a CONFIRM to `execute_approved_plan` (D-17, C-1).

`on_confirmed(approval, plan, confirmed_at)` is the SYNC hook the confirm core calls after its
lock is released (src/approval/confirm_core.py). It cannot await and it carries no raw token, so it
does exactly one thing: it schedules `_place` on the event loop (directly when called on the loop
thread, through `call_soon_threadsafe` from any other thread) and returns None at once. A strong
reference to every task is kept until it finishes, and a task that raises is journaled by the
exception CLASS NAME only (an exception text could carry an order detail or a token).

`_place` is the single placement path of the live process:

  1. the raw APPROVE token comes from the desk's memory (`token_for`); none (an unknown id, or a
     restart: the token is never persisted) journals a refusal and calls nothing;
  2. the per-plan risk and gate inputs come from a `PlacementInputsSource` (a port: the live
     producer is a later plan, the tracer test fills it with TEST_ONLY values);
  3. the deterministic ENTRY client id is put in the client-id index BEFORE the manager is awaited
     (research P-4: a fill can arrive before any store row is visible);
  4. ONE awaited `execute_approved_plan` call, with no loop, no retry and no second call around it
     (D080, owner rule Q5: a placement is never re-sent; the manager probes an ambiguous result
     once and fails closed). tests/test_live_ast_guards.py enforces this on the source.

No wall clock is read here: every instant comes from the injected `clock` or the inputs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import structlog

from src.approval.binding import Callback
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, OrderRole
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.trade_plan import TradePlan
from src.execution.intent_store import ExecutionIntentStore
from src.execution.live_context import LivePlacementContext
from src.execution.manager import ExecutionAdapter, ExecutionOutcome, execute_approved_plan
from src.execution.order_ids import derive_client_order_id
from src.live.order_index import ClientIdIndex

log = structlog.get_logger(__name__)

EVENT_PLACEMENT_REFUSED = "LIVE_PLACEMENT_REFUSED"
EVENT_PLACEMENT_OUTCOME = "LIVE_PLACEMENT_OUTCOME"
EVENT_PLACEMENT_TASK_FAILED = "LIVE_PLACEMENT_TASK_FAILED"

REFUSAL_TOKEN_UNAVAILABLE = "APPROVE_TOKEN_UNAVAILABLE"

_JOURNAL_PREFIX = "live-placement"
_TASK_NAME_PREFIX = "live-placement:"
_ENTITY_TYPE = "LivePlacement"


@dataclass(frozen=True, kw_only=True)
class PlacementInputs:
    """Everything `execute_approved_plan` needs for one plan besides the approval and the token.

    `risk_kwargs["now_utc"]` must equal `now_utc` (the manager's single clock). The three
    approval binding fields are those the approval was issued under (the Signal's strategy
    version and parameter set). `live_context` carries the Signal, the constraint snapshot, the
    limits, the protection registry and the margin guard.
    """

    now_utc: datetime
    expiry_utc: datetime
    approval_strategy_version: str
    approval_parameter_set_id: str
    approval_parameter_set_hash: str
    risk_kwargs: dict[str, Any]
    gate_kwargs: dict[str, Any]
    live_context: LivePlacementContext


@dataclass(frozen=True, kw_only=True)
class PlacementRefusal:
    """The inputs source cannot build the inputs of this plan; nothing is placed."""

    reason: str


class PlacementInputsSource(Protocol):
    """Builds the per-plan placement inputs after a CONFIRM (the live producer: plan 24-16)."""

    async def for_plan(
        self, approval: Approval, plan: TradePlan, confirmed_at_utc: datetime
    ) -> PlacementInputs | PlacementRefusal: ...


class JournalWriter(Protocol):
    """The append-only journal surface (`record`)."""

    def record(self, event: JournalEvent) -> None: ...


#: Called as `(approval_id, trade_plan_id, reason_code, now_utc)` after a CONFIRM was refused
#: before anything was consumed (plan 24-37, F4). The live composition binds the reservation
#: releaser; it decides itself which refusals are final. A failing hook is logged and ignored.
type RefusalHook = Callable[[str, str, str, datetime], Awaitable[Any]]


class ExecutionService:
    """Bridges `on_confirmed` to one `execute_approved_plan` call (see the module docstring)."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        token_for: Callable[[str], str | None],
        inputs: PlacementInputsSource,
        adapter: ExecutionAdapter,
        safe_mode_controller: Any,
        journal: JournalWriter,
        enablement: Any,
        intent_store: ExecutionIntentStore,
        index: ClientIdIndex,
        clock: Callable[[], datetime],
        authorized_chat_id: int,
        run_sync: Callable[..., Awaitable[Any]] | None = None,
        on_refused: RefusalHook | None = None,
    ) -> None:
        self._on_refused = on_refused
        self._run_sync = run_sync
        self._loop = loop
        self._token_for = token_for
        self._inputs = inputs
        self._adapter = adapter
        self._safe_mode_controller = safe_mode_controller
        self._journal = journal
        self._enablement = enablement
        self._intent_store = intent_store
        self._index = index
        self._clock = clock
        self._authorized_chat_id = authorized_chat_id
        self._tasks: set[asyncio.Task[None]] = set()

    # ---- the sync hook ------------------------------------------------------------------- #

    def on_confirmed(self, approval: Approval, plan: TradePlan, confirmed_at: datetime) -> None:
        """Schedule placement and return None at once. Never awaits, never places by itself."""
        try:
            running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._schedule(approval, plan, confirmed_at)
        else:
            # A worker thread (or no loop at all): hand the call to the loop thread. A closed loop
            # raises here, which the confirm core records as a failed hand-off (fail closed).
            self._loop.call_soon_threadsafe(self._schedule, approval, plan, confirmed_at)

    def _schedule(self, approval: Approval, plan: TradePlan, confirmed_at: datetime) -> None:
        task = self._loop.create_task(
            self._place(approval, plan, confirmed_at),
            name=f"{_TASK_NAME_PREFIX}{approval.approval_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        approval_id = task.get_name().removeprefix(_TASK_NAME_PREFIX)
        fields: dict[str, Any] = {
            "event_type": EVENT_PLACEMENT_TASK_FAILED,
            "step": "task_failed",
            "entity_id": approval_id,
            "correlation": f"{_JOURNAL_PREFIX}:{approval_id}",
            "payload": {"error_class": type(error).__name__},
        }
        if self._run_sync is None:
            self._record(**fields)
            return
        # A done-callback cannot await: the row is written by a tracked task off the loop.
        row = self._loop.create_task(self._arecord(**fields))
        self._tasks.add(row)
        row.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for every outstanding placement task (shutdown and tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    @property
    def outstanding(self) -> int:
        return len(self._tasks)

    # ---- the placement ------------------------------------------------------------------- #

    async def _place(self, approval: Approval, plan: TradePlan, confirmed_at: datetime) -> None:
        raw_token = self._token_for(approval.approval_id)
        if raw_token is None:
            await self._journal_refusal(approval, plan, REFUSAL_TOKEN_UNAVAILABLE)
            return
        resolved = await self._inputs.for_plan(approval, plan, confirmed_at)
        if isinstance(resolved, PlacementRefusal):
            await self._journal_refusal(approval, plan, resolved.reason)
            await self._after_refusal(approval, plan, resolved.reason, confirmed_at)
            return
        callback = Callback(
            raw_token=raw_token,
            chat_id=self._authorized_chat_id,
            plan_hash=plan.plan_hash,
            strategy_version=resolved.approval_strategy_version,
            parameter_set_id=resolved.approval_parameter_set_id,
            parameter_set_hash=resolved.approval_parameter_set_hash,
            callback_at_utc=resolved.now_utc,
            action=ApprovalAction.APPROVE,
        )
        entry_id = derive_client_order_id(plan_hash=plan.plan_hash, role=OrderRole.ENTRY.value)
        self._index.register_entry(
            plan_hash=plan.plan_hash,
            client_order_id=entry_id,
            symbol=resolved.live_context.signal.symbol,
        )
        outcome: ExecutionOutcome = await execute_approved_plan(
            callback=callback,
            approval=approval,
            authorized_chat_id=self._authorized_chat_id,
            expiry_utc=resolved.expiry_utc,
            approval_strategy_version=resolved.approval_strategy_version,
            approval_parameter_set_id=resolved.approval_parameter_set_id,
            approval_parameter_set_hash=resolved.approval_parameter_set_hash,
            now_utc=resolved.now_utc,
            adapter=self._adapter,
            risk_kwargs=resolved.risk_kwargs,
            safe_mode_controller=self._safe_mode_controller,
            journal=self._journal,
            enablement=self._enablement,
            gate_kwargs=resolved.gate_kwargs,
            intent_store=self._intent_store,
            live_context=resolved.live_context,
        )
        await self._arecord(
            event_type=EVENT_PLACEMENT_OUTCOME,
            step="outcome",
            entity_id=approval.approval_id,
            correlation=f"{_JOURNAL_PREFIX}:{approval.approval_id}",
            payload={"is_no_trade": outcome.is_no_trade, "reason_code": outcome.reason_code},
            approval=approval,
            plan=plan,
        )
        if outcome.is_no_trade:
            await self._after_refusal(approval, plan, outcome.reason_code, resolved.now_utc)

    async def _after_refusal(
        self, approval: Approval, plan: TradePlan, reason_code: str, now_utc: datetime
    ) -> None:
        """Hand a refused CONFIRM to the release hook (F4). Never raises, never places."""
        hook = self._on_refused
        if hook is None:
            return
        try:
            await hook(approval.approval_id, plan.trade_plan_id, reason_code, now_utc)
        except Exception as exc:  # noqa: BLE001 - the refusal is already journaled; class name only
            log.warning("live.execution_service.release_failed", error_class=type(exc).__name__)

    # ---- journal ------------------------------------------------------------------------- #

    async def _journal_refusal(self, approval: Approval, plan: TradePlan, reason: str) -> None:
        await self._arecord(
            event_type=EVENT_PLACEMENT_REFUSED,
            step="refused",
            entity_id=approval.approval_id,
            correlation=f"{_JOURNAL_PREFIX}:{approval.approval_id}",
            payload={"reason": reason},
            approval=approval,
            plan=plan,
        )

    def _event(
        self,
        *,
        event_type: str,
        step: str,
        entity_id: str,
        correlation: str,
        payload: dict[str, Any],
        approval: Approval | None = None,
        plan: TradePlan | None = None,
    ) -> JournalEvent:
        return JournalEvent(
            journal_event_id=correlated_event_id(
                prefix=_JOURNAL_PREFIX,
                correlation_id=correlation,
                event_type=event_type,
                entity_id=entity_id,
                step=step,
            ),
            occurred_at_utc=self._clock(),
            event_type=event_type,
            entity_type=_ENTITY_TYPE,
            entity_id=entity_id,
            correlation_id=correlation,
            signal_id=None if approval is None else approval.signal_id,
            trade_plan_id=None if plan is None else plan.trade_plan_id,
            approval_id=None if approval is None else approval.approval_id,
            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )

    def _record(self, **fields: Any) -> None:
        """Append one journal row inline; a journal that fails is logged, never raised."""
        try:
            self._journal.record(self._event(**fields))
        except Exception as exc:  # noqa: BLE001 - an audit row must not break the loop
            log.warning("live.execution_service.journal_failed", error_class=type(exc).__name__)

    async def _arecord(self, **fields: Any) -> None:
        """Append one journal row; off the loop when the store seam is set (plan 24-27B, D-25)."""
        if self._run_sync is None:
            self._record(**fields)
            return
        try:
            await self._run_sync(self._journal.record, self._event(**fields))
        except Exception as exc:  # noqa: BLE001 - an audit row must not break the loop
            log.warning("live.execution_service.journal_failed", error_class=type(exc).__name__)


__all__ = [
    "EVENT_PLACEMENT_OUTCOME",
    "EVENT_PLACEMENT_REFUSED",
    "EVENT_PLACEMENT_TASK_FAILED",
    "REFUSAL_TOKEN_UNAVAILABLE",
    "ExecutionService",
    "JournalWriter",
    "PlacementInputs",
    "PlacementInputsSource",
    "PlacementRefusal",
]
