"""The DEMO approval request sender: the one place that creates a DEMO approval card (D-18).

Phase 24, plan 24-14 (APRV-01, APRV-02; research C-4; 20-DEFERRED "second plan per symbol" and
"transition_signal / transition_trade_plan are never called"). It takes a `SignalRequest` from a
`SignalSource` (`src/live/signal_source.py`) and, in this order:

  1. refuses a request that is not a fresh DETECTED signal with an APPROVAL_PENDING plan;
  2. refuses a second plan on a symbol that already has one (T-24-37): an active tracked plan
     (any protection state but FLAT or ENTRY_ENDED_NO_FILL), an unresolved ENTRY intent, a
     resting entry order or a non-zero position on the exchange, or an unexpired PENDING or
     APPROVED DEMO approval. The label is `CONFLICT_WITH_OPEN_POSITION` (the engine's
     `NO_TRADE_CONFLICT`); a source that cannot be read refuses with `UNCERTAIN_ACCOUNT_STATE`
     (fail closed) and the read failure is journaled by its class name only. Nothing is written
     before this check passes. In One-way mode a second entry would merge into the open position
     and plan 1's closePosition stop would close both;
  3. builds the money block with the injected `money_for` and issues the card through
     `ApprovalDesk.issue` (the money block is stored on both approval rows, Phase 23 D-13); no
     money is recomputed here (F-015);
  4. registers the risk reservation request, when the composition injects one (Phase 21: the
     approval transaction can only reserve a REQUESTED row);
  5. sends the card with `ApprovalDesk.send` (one message with APPROVE and SKIP). A send failure
     approves nothing: both approvals stay PENDING and the failure is journaled by the desk
     (APRV-02, T-24-38). Only after a successful send the Signal moves DETECTED -> NOTIFIED.

The sender never calls `execute_approved_plan` and holds no placement port: placement is reached
only from a CONFIRM press (plan 24-13 and the execution service).

The decision side, `make_demo_save_atomic`, is the Phase 21 `make_reserving_save_atomic`
extended so that the SAME transaction applies the D028 chain (GLOSSARY 2.1, section 11.1 and
11.2; DATA_MODEL section 3): on APPROVED the Signal and then the TradePlan move to APPROVED
(`transition_signal`, `transition_trade_plan`); on SKIPPED the Signal moves to SKIPPED_USER (or
SKIPPED_BUSY for a SKIP_BUSY action); on EXPIRED the Signal and the TradePlan move to EXPIRED. The
documents name no TradePlan state for a skip (a plan is SUPERSEDED only when replaced before the
decision), so a skipped plan keeps APPROVAL_PENDING: it can never be placed (placement needs an
APPROVED approval) and its expiry sweep ends it. A failure of any step rolls the decision, the
reservation and the transitions back together: the press is answered as a failure and nothing is
approved.

No wall clock is read here: the instant of a request comes from the injected `clock`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Final, Protocol, cast

import structlog
from sqlalchemy.orm import Session

from src.adapters.telegram_notify import TelegramTextBot
from src.approval.mapping import ShortIdMapping
from src.backtest.semantics import NO_TRADE_CONFLICT
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    OrderRole,
    RejectionReason,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.approval_desk import ApprovalDesk, DeskStores, IssuedRequest, SleepFn
from src.execution.intent_store import IntentRecord
from src.execution.protection import PlanProtection, ProtectionState
from src.live.signal_source import SignalRequest
from src.persistence.approvals import PgApprovalStore
from src.persistence.risk_reservations import PgRiskReservationStore, make_reserving_save_atomic
from src.persistence.shadow_stores import approval_mode_correlation, mode_from_marker_payload
from src.risk.money_at_stake import MoneyAtStake

log = structlog.get_logger(__name__)

# --------------------------------------------------------------------------- #
# Journal events and labels.
# --------------------------------------------------------------------------- #

EVENT_REQUEST_REFUSED: Final = "DEMO_APPROVAL_REQUEST_REFUSED"
EVENT_REQUEST_NOT_ISSUED: Final = "DEMO_APPROVAL_REQUEST_NOT_ISSUED"
EVENT_SIGNAL_NOTIFY_FAILED: Final = "DEMO_SIGNAL_NOTIFY_FAILED"

REASON_CONFLICT: Final = NO_TRADE_CONFLICT  # "CONFLICT_WITH_OPEN_POSITION"
REASON_UNCERTAIN: Final = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
REASON_EXPIRED: Final = RejectionReason.APPROVAL_EXPIRED.value
REASON_INVALID_REQUEST: Final = "INVALID_REQUEST"
REASON_MONEY_MISSING: Final = "MONEY_AT_STAKE_MISSING"
REASON_ISSUE_FAILED: Final = "ISSUE_FAILED"
REASON_RESERVATION_FAILED: Final = "RESERVATION_REQUEST_FAILED"

SOURCE_ACTIVE_PLAN: Final = "ACTIVE_PLAN"
SOURCE_ENTRY_INTENT: Final = "UNRESOLVED_ENTRY_INTENT"
SOURCE_RESTING_ENTRY: Final = "RESTING_ENTRY_ORDER"
SOURCE_OPEN_POSITION: Final = "OPEN_POSITION"
SOURCE_OPEN_APPROVAL: Final = "PENDING_OR_APPROVED_APPROVAL"
CONFLICT_SOURCES: Final[tuple[str, ...]] = (
    SOURCE_ACTIVE_PLAN,
    SOURCE_ENTRY_INTENT,
    SOURCE_RESTING_ENTRY,
    SOURCE_OPEN_POSITION,
    SOURCE_OPEN_APPROVAL,
)

# A tracked plan in one of these protection states holds nothing and does not block the symbol.
_INACTIVE_PROTECTION_STATES: Final = frozenset(
    {ProtectionState.FLAT, ProtectionState.ENTRY_ENDED_NO_FILL}
)
_JOURNAL_PREFIX: Final = "demo-send"
_ENTITY_TYPE: Final = "ApprovalRequestSender"
_DEMO_MODE: Final = "DEMO"


class SendStatus(str, Enum):
    """What `send_request` did with one request."""

    SENT = "SENT"
    REFUSED = "REFUSED"
    NOT_ISSUED = "NOT_ISSUED"
    SEND_FAILED = "SEND_FAILED"


@dataclass(frozen=True)
class SendOutcome:
    """The result of one request. It never carries a token and nothing in it approves anything."""

    status: SendStatus
    reason: str | None = None
    # The conflict sources that refused the request (or the read failures, by class name).
    sources: tuple[str, ...] = ()
    short_id: str | None = None
    message_id: int | None = None
    # True once the Signal moved DETECTED -> NOTIFIED after a successful send.
    notified: bool = False


# --------------------------------------------------------------------------- #
# Ports (everything injected).
# --------------------------------------------------------------------------- #


class PositionsReader(Protocol):
    """The exchange side of the conflict check (REST truth, read fresh per request)."""

    async def open_position_quantity(self, symbol: str) -> Decimal:
        """The absolute size of the symbol's position, zero when flat. Raises when unreadable."""
        ...

    async def open_entry_order_count(self, symbol: str) -> int:
        """The number of resting entry orders on the symbol. Raises when unreadable."""
        ...


class EntityTransitions(Protocol):
    """`PgTradingEntityStore`'s two transition methods (the unit of work is optional)."""

    def transition_signal(
        self,
        signal_id: str,
        new_status: SignalStatus,
        *,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> Signal: ...

    def transition_trade_plan(
        self,
        trade_plan_id: str,
        new_status: TradePlanStatus,
        *,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> TradePlan: ...


class UnresolvedIntents(Protocol):
    """The slice of `ExecutionIntentStore` the check reads."""

    def list_unresolved_intents(self) -> Sequence[IntentRecord]: ...


@dataclass(frozen=True)
class OpenApproval:
    """A PENDING or APPROVED DEMO approval, with the symbol and expiry of its plan."""

    approval_id: str
    symbol: str
    expiry_utc: datetime


ProtectionsReader = Callable[[], Sequence[PlanProtection]]
ApprovalsReader = Callable[[], Iterable[OpenApproval]]
MoneyFor = Callable[[SignalRequest], MoneyAtStake | None]
ReservationRegistrar = Callable[[SignalRequest, MoneyAtStake, datetime], None]
JournalSink = Callable[[JournalEvent], None]
Clock = Callable[[], datetime]
# Plan 24-27B (D-25): the store seam. `run(fn, *args, **kwargs)` awaits a synchronous store call
# off the event loop (`StoreExecutor.write` for writes, `StoreExecutor.read` for reads).
RunSync = Callable[..., Awaitable[Any]]


class ApprovalRequestSender:
    """Issues and sends DEMO approval cards, one request at a time (see the module docstring).

    `run_sync` / `run_read` (plan 24-27B) are the optional store seam of the live process
    (`StoreExecutor.write` / `.read`): every synchronous store call of the flow (the desk's issue,
    the reservation, the signal transition, the journal rows and the conflict reads) is awaited off
    the event loop. Without them the calls stay inline (the unit tests).

    `register_reservation(request, money, now_utc)` is optional: the composition binds it to the
    Phase 21 reservation store's `register_request` (REQUESTED row) so the approval transaction
    has a row to reserve; it is injected so this module does not call the store directly. If it
    raises, the card is NOT sent (an unreservable card could never be approved).
    """

    def __init__(
        self,
        *,
        desk: ApprovalDesk,
        bot: TelegramTextBot,
        chat_id: int | str,
        entities: EntityTransitions,
        intents: UnresolvedIntents,
        protections: ProtectionsReader,
        positions_reader: PositionsReader,
        approvals_reader: ApprovalsReader,
        money_for: MoneyFor,
        clock: Clock,
        sleep: SleepFn,
        journal: JournalSink,
        register_reservation: ReservationRegistrar | None = None,
        run_sync: RunSync | None = None,
        run_read: RunSync | None = None,
    ) -> None:
        self._desk = desk
        self._run_sync = run_sync
        self._run_read = run_read if run_read is not None else run_sync
        self._bot = bot
        self._chat_id = chat_id
        self._entities = entities
        self._intents = intents
        self._protections = protections
        self._positions = positions_reader
        self._approvals = approvals_reader
        self._money_for = money_for
        self._clock = clock
        self._sleep = sleep
        self._journal = journal
        self._register_reservation = register_reservation
        # Two concurrent requests for one symbol must not both pass the check before either has
        # written its rows.
        self._lock = asyncio.Lock()

    async def _write(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self._run_sync is None:
            return fn(*args, **kwargs)
        return await self._run_sync(fn, *args, **kwargs)

    async def _read(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self._run_read is None:
            return fn(*args, **kwargs)
        return await self._run_read(fn, *args, **kwargs)

    async def send_request(self, request: SignalRequest) -> SendOutcome:
        """Refuse, or issue and send one approval card. Never approves, never places."""
        async with self._lock:
            return await self._send_locked(request)

    # ---- the flow ------------------------------------------------------------- #

    async def _send_locked(self, request: SignalRequest) -> SendOutcome:
        now = self._clock()
        signal, plan = request.signal, request.plan
        invalid = _invalid_reason(request, now)
        if invalid is not None:
            return await self._refuse(request, now, invalid, ())

        conflicts, failures = await self._conflict_sources(signal.symbol, now)
        if conflicts:
            return await self._refuse(request, now, REASON_CONFLICT, (*conflicts, *failures))
        if failures:
            return await self._refuse(request, now, REASON_UNCERTAIN, failures)

        try:
            money = self._money_for(request)
        except Exception as exc:  # noqa: BLE001 - journaled by class name only
            return await self._not_issued(request, now, type(exc).__name__)
        if money is None:
            return await self._not_issued(request, now, REASON_MONEY_MISSING)
        try:
            issued = await self._write(
                self._desk.issue,
                signal=signal,
                plan=plan,
                money=money,
                exposure_quote=request.exposure_quote,
                reason_codes=list(request.reason_codes),
                now_utc=now,
            )
        except Exception as exc:  # noqa: BLE001 - journaled by class name only
            return await self._not_issued(
                request, now, f"{REASON_ISSUE_FAILED}:{type(exc).__name__}"
            )
        if self._register_reservation is not None:
            try:
                await self._write(self._register_reservation, request, money, now)
            except Exception as exc:  # noqa: BLE001 - journaled by class name only
                return await self._not_issued(
                    request,
                    now,
                    f"{REASON_RESERVATION_FAILED}:{type(exc).__name__}",
                    short_id=issued.mapping.short_id,
                )
        return await self._send(request, issued)

    async def _send(self, request: SignalRequest, issued: IssuedRequest) -> SendOutcome:
        short_id = issued.mapping.short_id
        try:
            sent = await self._desk.send(
                self._bot, chat_id=self._chat_id, issued=issued, sleep=self._sleep
            )
        except Exception as exc:  # noqa: BLE001 - the card was not delivered; nothing approved
            await self._record(
                request,
                EVENT_REQUEST_NOT_ISSUED,
                "send_raised",
                self._clock(),
                {"error_class": type(exc).__name__, "short_id": short_id},
            )
            return SendOutcome(SendStatus.SEND_FAILED, type(exc).__name__, short_id=short_id)
        if not sent.sent:
            # The desk journaled the classified failure; both approvals stay PENDING (APRV-02).
            kind = sent.failure.kind.value if sent.failure is not None else "UNKNOWN"
            return SendOutcome(SendStatus.SEND_FAILED, kind, short_id=short_id)
        notified = await self._mark_notified(request)
        return SendOutcome(
            SendStatus.SENT, short_id=short_id, message_id=sent.message_id, notified=notified
        )

    async def _mark_notified(self, request: SignalRequest) -> bool:
        """DETECTED -> NOTIFIED once the card is out. A failure leaves the card unapprovable."""
        now = self._clock()
        try:
            await self._write(
                self._entities.transition_signal,
                request.signal.signal_id,
                SignalStatus.NOTIFIED,
                now_utc=now,
            )
        except Exception as exc:  # noqa: BLE001 - journaled by class name only
            await self._record(
                request,
                EVENT_SIGNAL_NOTIFY_FAILED,
                "notify_failed",
                now,
                {"error_class": type(exc).__name__},
            )
            return False
        return True

    # ---- the second-plan refusal ------------------------------------------------ #

    async def _conflict_sources(
        self, symbol: str, now: datetime
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """`(conflicting sources, read failures)`. Every source is read; none is skipped."""
        conflicts: list[str] = []
        failures: list[str] = []

        def failed(source: str, exc: BaseException) -> None:
            failures.append(f"{source}:READ_FAILED:{type(exc).__name__}")

        try:
            if any(
                p.symbol == symbol and p.state not in _INACTIVE_PROTECTION_STATES
                for p in self._protections()
            ):
                conflicts.append(SOURCE_ACTIVE_PLAN)
        except Exception as exc:  # noqa: BLE001 - fail closed, journaled by class name
            failed(SOURCE_ACTIVE_PLAN, exc)
        try:
            if any(
                record.symbol == symbol and record.role == OrderRole.ENTRY.value
                for record in await self._read(self._intents.list_unresolved_intents)
            ):
                conflicts.append(SOURCE_ENTRY_INTENT)
        except Exception as exc:  # noqa: BLE001
            failed(SOURCE_ENTRY_INTENT, exc)
        try:
            if await self._positions.open_entry_order_count(symbol) > 0:
                conflicts.append(SOURCE_RESTING_ENTRY)
        except Exception as exc:  # noqa: BLE001
            failed(SOURCE_RESTING_ENTRY, exc)
        try:
            if await self._positions.open_position_quantity(symbol) != Decimal("0"):
                conflicts.append(SOURCE_OPEN_POSITION)
        except Exception as exc:  # noqa: BLE001
            failed(SOURCE_OPEN_POSITION, exc)
        try:
            # An approval counts while its plan can still be confirmed; a plan past its expiry is
            # either unfilled (the entry is gone) or filled (the position source covers it).
            open_approvals = await self._read(lambda: list(self._approvals()))
            if any(item.symbol == symbol and item.expiry_utc > now for item in open_approvals):
                conflicts.append(SOURCE_OPEN_APPROVAL)
        except Exception as exc:  # noqa: BLE001
            failed(SOURCE_OPEN_APPROVAL, exc)
        return tuple(conflicts), tuple(failures)

    # ---- outcomes and journal ----------------------------------------------------- #

    async def _refuse(
        self, request: SignalRequest, now: datetime, reason: str, sources: tuple[str, ...]
    ) -> SendOutcome:
        await self._record(
            request,
            EVENT_REQUEST_REFUSED,
            "refused",
            now,
            {"reason": reason, "sources": list(sources), "symbol": request.signal.symbol},
            link_rows=False,
        )
        return SendOutcome(SendStatus.REFUSED, reason, sources)

    async def _not_issued(
        self, request: SignalRequest, now: datetime, reason: str, *, short_id: str | None = None
    ) -> SendOutcome:
        await self._record(
            request,
            EVENT_REQUEST_NOT_ISSUED,
            "not_issued",
            now,
            {"reason": reason, "short_id": short_id},
            link_rows=short_id is not None,
        )
        return SendOutcome(SendStatus.NOT_ISSUED, reason, short_id=short_id)

    async def _record(
        self,
        request: SignalRequest,
        event_type: str,
        step: str,
        now: datetime,
        payload: Mapping[str, Any],
        *,
        link_rows: bool = True,
    ) -> None:
        """Journal one event. `link_rows=False` leaves the FK columns empty: no row was written."""
        signal_id, plan_id = request.signal.signal_id, request.plan.trade_plan_id
        correlation = f"demo-request:{signal_id}"
        body = {**payload, "mode": _DEMO_MODE, "signal_id": signal_id, "trade_plan_id": plan_id}
        try:
            await self._write(
                self._journal,
                JournalEvent(
                    journal_event_id=correlated_event_id(
                        prefix=_JOURNAL_PREFIX,
                        correlation_id=correlation,
                        event_type=event_type,
                        entity_id=signal_id,
                        step=step,
                    ),
                    occurred_at_utc=now,
                    event_type=event_type,
                    entity_type=_ENTITY_TYPE,
                    entity_id=signal_id,
                    correlation_id=correlation,
                    signal_id=signal_id if link_rows else None,
                    trade_plan_id=plan_id if link_rows else None,
                    payload_json=json.dumps(body, sort_keys=True, separators=(",", ":")),
                ),
            )
        except Exception as exc:  # noqa: BLE001 - a journal failure never turns a refusal into a send
            log.warning("demo_request_journal_failed", error_class=type(exc).__name__)


def _invalid_reason(request: SignalRequest, now: datetime) -> str | None:
    signal, plan = request.signal, request.plan
    if signal.status is not SignalStatus.DETECTED:
        return REASON_INVALID_REQUEST
    if plan.status is not TradePlanStatus.APPROVAL_PENDING:
        return REASON_INVALID_REQUEST
    if plan.signal_id != signal.signal_id:
        return REASON_INVALID_REQUEST
    if plan.expiry_utc <= now:
        return REASON_EXPIRED
    return None


# --------------------------------------------------------------------------- #
# The open-approvals reader over the DEMO-scoped stores (plan 24-08).
# --------------------------------------------------------------------------- #


class ApprovalLookupStores(Protocol):
    """The slice of `PgShadowStores(confirm_mode="DEMO")` the open-approvals reader needs."""

    @property
    def confirm_mode(self) -> str | None: ...
    def list_pending_approvals(self) -> list[Approval]: ...
    def list_approved_approvals(self) -> list[Approval]: ...
    def get_signal(self, signal_id: str) -> Signal | None: ...
    def get_trade_plan(self, trade_plan_id: str) -> TradePlan | None: ...
    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]: ...


def make_open_demo_approvals_reader(stores: ApprovalLookupStores) -> ApprovalsReader:
    """The PENDING and APPROVED DEMO approvals with their symbol and plan expiry.

    `list_pending_approvals` is not mode-scoped (SHADOW and DEMO share one database), so a
    PENDING approval counts only when it carries the DEMO marker of plan 24-08
    (`APPROVAL_MODE_RECORDED`); `list_approved_approvals` is scoped by the store itself, so the
    store MUST be `confirm_mode="DEMO"`. A plan or signal row that cannot be found raises: the
    sender then refuses (fail closed).
    """
    if stores.confirm_mode != _DEMO_MODE:
        raise ValueError('the open-approvals reader needs stores with confirm_mode="DEMO"')

    def is_demo(approval: Approval) -> bool:
        for event in stores.journal_for_correlation(
            approval_mode_correlation(approval.approval_id)
        ):
            if mode_from_marker_payload(event.payload_json) == _DEMO_MODE:
                return True
        return False

    def read() -> list[OpenApproval]:
        found: dict[str, OpenApproval] = {}
        candidates = [a for a in stores.list_pending_approvals() if is_demo(a)]
        candidates.extend(stores.list_approved_approvals())
        for approval in candidates:
            if approval.trade_plan_id in found:
                continue
            plan = stores.get_trade_plan(approval.trade_plan_id)
            signal = stores.get_signal(approval.signal_id)
            if plan is None or signal is None:
                raise LookupError(f"plan or signal of approval {approval.approval_id} not found")
            found[approval.trade_plan_id] = OpenApproval(
                approval_id=approval.approval_id,
                symbol=signal.symbol,
                expiry_utc=plan.expiry_utc,
            )
        return list(found.values())

    return read


# --------------------------------------------------------------------------- #
# The decision side: reservation + the D028 chain in ONE transaction.
# --------------------------------------------------------------------------- #

AfterDecide = Callable[[Session, Approval], None]
SaveAtomicFn = Callable[[Approval, ShortIdMapping | None], None]


def apply_d028_chain(entities: EntityTransitions, session: Session, approval: Approval) -> None:
    """Move the Signal and the TradePlan along with a decided approval, on `session`.

    APPROVED: Signal APPROVED, then TradePlan APPROVED (GLOSSARY 2.1: "Signal APPROVED ->
    TradePlan APPROVED -> Order PLANNED"). SKIPPED: Signal SKIPPED_USER (SKIPPED_BUSY for a
    SKIP_BUSY action), GLOSSARY 11.1; the plan is left as it is (no plan state is named for a
    skip). EXPIRED: Signal EXPIRED and TradePlan EXPIRED, GLOSSARY 11.1 and 11.2. An illegal
    move raises `IllegalTransition`, which rolls the whole approval transaction back.
    """
    acted_at = approval.acted_at_utc
    if acted_at is None:
        raise ValueError("a decided approval carries acted_at_utc")
    signal_id, plan_id = approval.signal_id, approval.trade_plan_id
    if approval.status is ApprovalResult.APPROVED:
        if approval.action is not ApprovalAction.APPROVE:
            raise ValueError("only an APPROVE action can approve a signal")
        entities.transition_signal(signal_id, SignalStatus.APPROVED, now_utc=acted_at, tx=session)
        entities.transition_trade_plan(
            plan_id, TradePlanStatus.APPROVED, now_utc=acted_at, tx=session
        )
    elif approval.status is ApprovalResult.SKIPPED:
        target = (
            SignalStatus.SKIPPED_BUSY
            if approval.action is ApprovalAction.SKIP_BUSY
            else SignalStatus.SKIPPED_USER
        )
        entities.transition_signal(signal_id, target, now_utc=acted_at, tx=session)
    elif approval.status is ApprovalResult.EXPIRED:
        entities.transition_signal(signal_id, SignalStatus.EXPIRED, now_utc=acted_at, tx=session)
        entities.transition_trade_plan(
            plan_id, TradePlanStatus.EXPIRED, now_utc=acted_at, tx=session
        )
    else:
        raise ValueError("the D028 chain needs a decided approval")


class _ChainedApprovals:
    """Wraps the approval store so the D028 chain runs after the reservation hook.

    `make_reserving_save_atomic` calls `approvals.save_atomic(approval, mapping,
    after_decide=hook)`. This wrapper hands the store a combined hook: the reservation hook first
    (so a refused reservation never reaches the chain), then the transitions, on the same session.
    """

    def __init__(self, inner: PgApprovalStore, entities: EntityTransitions) -> None:
        self._inner = inner
        self._entities = entities

    def save_atomic(
        self,
        approval: Approval,
        mapping: ShortIdMapping | None,
        *,
        after_decide: AfterDecide | None = None,
    ) -> None:
        def combined(session: Session, decided: Approval) -> None:
            if after_decide is not None:
                after_decide(session, decided)
            apply_d028_chain(self._entities, session, decided)

        self._inner.save_atomic(approval, mapping, after_decide=combined)


def make_demo_save_atomic(
    *,
    approvals: PgApprovalStore,
    reservations: PgRiskReservationStore,
    entities: EntityTransitions,
    parameter_set: dict[str, Any],
    daily_loss_quote: Callable[[Any], Decimal | None],
) -> SaveAtomicFn:
    """The DEMO desk's `save_atomic`: decision, reservation and D028 chain in one transaction.

    The result has the unchanged `SaveAtomic` signature. Order inside the transaction: the
    approval is decided, the reservation is made (APPROVED) or released (SKIPPED, EXPIRED), then
    the Signal and TradePlan move. Any failure rolls all of it back; the approval stays PENDING.
    """
    chained = cast(PgApprovalStore, _ChainedApprovals(approvals, entities))
    return make_reserving_save_atomic(
        approvals=chained,
        reservations=reservations,
        parameter_set=parameter_set,
        daily_loss_quote=daily_loss_quote,
    )


class DemoDeskStores:
    """`DeskStores` whose `save_atomic` is the composed DEMO one; everything else is delegated.

    Hand this to `ApprovalDesk` so a press runs through `make_demo_save_atomic`. The inner stores
    are the DEMO-scoped `PgShadowStores(db, confirm_mode="DEMO")` of plan 24-08.
    """

    def __init__(self, inner: DeskStores, save_atomic: SaveAtomicFn) -> None:
        self._inner = inner
        self._save_atomic = save_atomic

    def insert_signal(self, signal: Signal) -> None:
        self._inner.insert_signal(signal)

    def insert_trade_plan(self, plan: TradePlan) -> None:
        self._inner.insert_trade_plan(plan)

    def insert_pending(self, approval: Approval) -> None:
        self._inner.insert_pending(approval)

    def record_short_id_mapping(self, mapping: ShortIdMapping) -> None:
        self._inner.record_short_id_mapping(mapping)

    def save_atomic(self, approval: Approval, mapping: ShortIdMapping | None) -> None:
        self._save_atomic(approval, mapping)

    def lookup_by_token_hash(self, token_hash: str) -> Approval | None:
        return self._inner.lookup_by_token_hash(token_hash)

    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None:
        return self._inner.lookup_by_short_id(short_id)

    def record_journal(self, event: JournalEvent) -> None:
        self._inner.record_journal(event)


__all__ = [
    "CONFLICT_SOURCES",
    "EVENT_REQUEST_NOT_ISSUED",
    "EVENT_REQUEST_REFUSED",
    "EVENT_SIGNAL_NOTIFY_FAILED",
    "REASON_CONFLICT",
    "REASON_UNCERTAIN",
    "ApprovalLookupStores",
    "ApprovalRequestSender",
    "ApprovalsReader",
    "DemoDeskStores",
    "EntityTransitions",
    "OpenApproval",
    "PositionsReader",
    "SendOutcome",
    "SendStatus",
    "UnresolvedIntents",
    "apply_d028_chain",
    "make_demo_save_atomic",
    "make_open_demo_approvals_reader",
]
