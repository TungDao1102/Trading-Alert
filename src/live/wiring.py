"""The live composition root, execution path first (D-04): the one place live objects are built.

`LiveWiring` is a frozen value holding the objects of the live process; every field is required
(no `None` default), so the Phase 24 gate (plan 24-27) can assert that nothing is missing.
`build_execution_path` builds the execution path, CONFIRM to a protected position:

  desk -> confirm flow -> `ExecutionService.on_confirmed` -> `execute_approved_plan`
  user-data frame -> router -> `ProtectionCoordinator.fill_sink` (the router's lookup is `index`)

Plans 24-12 to 24-23 add their sub-builders in their own modules and plan 24-27 assembles the
complete wiring here. Nothing outside `src/live/` constructs an `ExecutionService`, and this
module never reads the wall clock: the clock, the adapter and every other collaborator are
injected by the caller (the process entry point, or a test).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from src.adapters.telegram_notify import TelegramTextBot
from src.approval.confirm_core import (
    ConfirmProfile,
    ConfirmStores,
    MarkPriceFn,
    RecheckFn,
)
from src.execution.approval_desk import ApprovalDesk, DeskStores
from src.execution.confirm_flow import ConfirmFlow, PrefetchFn, ValidityRule, make_confirm_flow
from src.execution.emergency_close import MarketEmergencyCloser
from src.execution.execution_limits import ExecutionLimits
from src.execution.intent_store import ExecutionIntentStore
from src.execution.manager import ExecutionAdapter
from src.execution.protection import CriticalAlertSink, ProtectionCoordinator
from src.live.execution_service import ExecutionService, JournalWriter, PlacementInputsSource
from src.live.order_index import ClientIdIndex

SleepFn = Callable[[float], Awaitable[None]]


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


__all__ = ["LiveStores", "LiveWiring", "build_execution_path"]
