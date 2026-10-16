"""SHADOW CONFIRM step of D041 (Phase 16, plan 16-11, D-16, L-13, REV-12, D-12, D-35).

D041 is a two-step flow: APPROVE does not confirm anything, it turns the alert into a
confirmation card with CONFIRM and CANCEL buttons, and only CONFIRM within a short TTL counts.
In SHADOW the same flow runs so the human delay is measured realistically, and it NEVER places
anything: this module imports nothing from `src.execution`, nothing from a Binance adapter and
nothing from `telegram` (python-telegram-bot stays behind `src/adapters/telegram_notify.py`).
The only side effect of a successful CONFIRM is the injected `on_confirmed` callback (plan 16-31
wires it to the SHADOW fill driver).

What lives here:
  - `ConfirmBook`: the confirm state machine. A confirm token is issued per APPROVED approval,
    is separate from the approval token (a fresh one-time token, memory only; PostgreSQL and the
    journal never see it), is single use, is bound to the Telegram user id that pressed APPROVE
    and to the plan hash, and expires `ttl_seconds` (60 s by default, D041) after the card was
    issued. CANCEL, expiry and every rejection are journaled and simulate nothing; a replayed
    CONFIRM replays to the existing outcome and never reaches `on_confirmed` a second time.
  - `render_confirm_card`: a thin call of the one composer (`render_shadow_message`).
  - `deliver_confirm_card`: edits the alert into the card; a failed edit is followed by exactly
    one fallback send of the same card; if that fails too the confirm is journaled EXPIRED with
    reason `CARD_DELIVERY_FAILED`. An approved plan is never left without a card AND without a
    journaled outcome (T-16-112, `assert_no_stranded_approvals`).
  - `make_confirm_callbacks`: the `approved_handler` and `confirm_handler` hooks of `on_callback`.

Authorization: the confirm is BOUND to the user id that pressed APPROVE (taken from the
callback). Authorizing user ids against an allow-list, money amounts on the card and keyboard
removal are Phase 23.

Expiry (REV-12): the approval expiry stays the plan expiry; at CONFIRM the plan expiry is checked
again (inclusive boundary, as `src/approval/binding.py`). The confirm TTL is D041's 60 s and is
not a new strategy or risk parameter.

Restart: raw confirm tokens do not survive a process restart, so outstanding confirms are
expired and journaled with reason `RUNTIME_RESTART` (fail closed, as plan 16-04).
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Final, Protocol, TypeVar

import structlog

from src.adapters.telegram_callbacks import (
    CallbackKind,
    CallbackPress,
    ConfirmReply,
    DispatchResult,
)
from src.adapters.telegram_notify import (
    TelegramFailure,
    TelegramFailureKind,
    TelegramSendError,
    TelegramTextBot,
    build_confirm_keyboard,
    edit_to_confirm_card,
    send_text,
)
from src.approval.tokens import issue_one_time_token, token_hash_of
from src.domain.approval import Approval
from src.domain.enums import ApprovalResult, RejectionReason
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper.notify import NOTIFY_MAX_ATTEMPTS
from src.paper.shadow import (
    ConfirmCardFields,
    ConfirmOutcome,
    ConfirmRecord,
    Mode,
    ShadowApprovalBook,
    ShadowMessageKind,
    render_shadow_message,
    require_shadow,
)

log = structlog.get_logger()

_T = TypeVar("_T")

# D041: the SHADOW confirm TTL. It is the human-confirmation window of the two-step flow, not a
# strategy or risk parameter; REV-12 keeps the approval expiry equal to the plan expiry.
CONFIRM_TTL_SECONDS_DEFAULT: Final = 60

EVENT_SHADOW_CONFIRM_ISSUED: Final = "SHADOW_CONFIRM_ISSUED"
EVENT_SHADOW_CONFIRMED: Final = "SHADOW_CONFIRMED"
EVENT_SHADOW_CONFIRM_CANCELLED: Final = "SHADOW_CONFIRM_CANCELLED"
EVENT_SHADOW_CONFIRM_EXPIRED: Final = "SHADOW_CONFIRM_EXPIRED"
# Not terminal: a press that was refused (another user, another chat, no confirm context).
EVENT_SHADOW_CONFIRM_REJECTED: Final = "SHADOW_CONFIRM_REJECTED"
# Not terminal: the best-effort failure notice itself could not be sent.
EVENT_SHADOW_CONFIRM_NOTICE_FAILED: Final = "SHADOW_CONFIRM_NOTICE_FAILED"

TERMINAL_CONFIRM_EVENTS: Final = (
    EVENT_SHADOW_CONFIRMED,
    EVENT_SHADOW_CONFIRM_CANCELLED,
    EVENT_SHADOW_CONFIRM_EXPIRED,
)

REASON_CONFIRM_TTL_ELAPSED: Final = "CONFIRM_TTL_ELAPSED"
REASON_CARD_DELIVERY_FAILED: Final = "CARD_DELIVERY_FAILED"
REASON_RUNTIME_RESTART: Final = "RUNTIME_RESTART"
REASON_USER_ID_UNAVAILABLE: Final = "USER_ID_UNAVAILABLE"
REASON_USER_MISMATCH: Final = "USER_MISMATCH"
REASON_CHAT_MISMATCH: Final = "CHAT_MISMATCH"
REASON_NO_CONFIRM_CONTEXT: Final = "NO_CONFIRM_CONTEXT"
REASON_RECHECK_ERROR: Final = "RECHECK_ERROR"
REASON_CONFIRM_ALREADY_EXPIRED: Final = "CONFIRM_ALREADY_EXPIRED"

DELIVERY_EDIT: Final = "edit"
DELIVERY_FALLBACK_SEND: Final = "fallback_send"

_NOTICE_SENT: Final = "sent"
_NOTICE_SKIPPED_RATE_LIMITED: Final = "skipped_rate_limited"
_NOTICE_FAILED: Final = "failed"

# A re-check returns None to pass or the reason: a `RejectionReason`, or a plain code text for the
# labels that are not enum members (the engine's CONFLICT_WITH_OPEN_POSITION).
RecheckFn = Callable[[Signal, TradePlan, datetime], RejectionReason | str | None]
OnConfirmedFn = Callable[[Approval, TradePlan, datetime], None]
MarkPriceFn = Callable[[str], Decimal | None]


class ConfirmStores(Protocol):
    """What the confirm layer needs from persistence: the journal and the approval readers.

    The Phase 17 PostgreSQL stores provide the writers; plan 16-31 adds the two list readers
    the sweep uses (`list_approved_approvals`, `journal_for_correlation`).
    """

    def record_journal(self, event: JournalEvent) -> None: ...
    def lookup_by_token_hash(self, token_hash: str) -> Approval | None: ...
    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None: ...
    def list_approved_approvals(self) -> list[Approval]: ...
    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]: ...


class ReserveOutcome(Protocol):
    """What a reservation attempt amounted to (`src/paper/shadow_ledger.py:ReserveResult`)."""

    @property
    def reserved(self) -> bool: ...
    @property
    def reason_code(self) -> str: ...


class ReservationPort(Protocol):
    """The exposure reservation of the Q-C decision `reserve-at-confirm` (plan 16-23).

    `section()` is the serialized section the CONFIRM runs in: recheck, the SHADOW_CONFIRMED
    journal write and `reserve` happen inside it, so no other CONFIRM can interleave. `check` is
    the full capacity check on the current ledger and runs BEFORE the journal write; a failure
    rejects the CONFIRM. `confirm_payload` returns the reservation facts merged into the
    SHADOW_CONFIRMED payload (the journal is the source of truth for recovery). `reserve` runs only
    after that write succeeded.
    """

    def section(self) -> AbstractContextManager[Any]: ...
    def check(self, signal: Signal, plan: TradePlan, now_utc: datetime) -> str | None: ...
    def confirm_payload(
        self,
        *,
        approval: Approval,
        signal: Signal,
        plan: TradePlan,
        short_id: str,
        confirmed_at_utc: datetime,
    ) -> Mapping[str, Any]: ...
    def reserve(
        self,
        *,
        approval: Approval,
        signal: Signal,
        plan: TradePlan,
        short_id: str,
        confirmed_at_utc: datetime,
    ) -> ReserveOutcome: ...


class StrandedApprovals(AssertionError):
    """An approved plan is past the confirm TTL with no terminal confirm event (T-16-112)."""


# --------------------------------------------------------------------------- #
# The card.
# --------------------------------------------------------------------------- #


def render_confirm_card(
    signal: Signal,
    plan: TradePlan,
    *,
    mode: Mode,
    mark_price: Decimal | None,
    now_utc: datetime,
    ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT,
) -> str:
    """The SHADOW confirmation card, built by the one composer (`render_shadow_message`).

    Shows mode SHADOW, symbol, side, quantity, notional, estimated loss at SL, the current mark
    price against entry and SL, and the remaining validity (the plan expiry as a UTC and an
    Asia/Ho_Chi_Minh time next to the remaining seconds, plus the confirm window).
    Notional and loss use the adverse edge of the entry zone (LONG entry_max, SHORT entry_min).
    """
    require_shadow(mode)
    if signal.direction == "LONG":
        entry_ref = plan.entry_max_price
    elif signal.direction == "SHORT":
        entry_ref = plan.entry_min_price
    else:
        raise ValueError(f"unknown signal direction {signal.direction!r}")
    quantity = plan.quantity_after_rounding
    remaining = max(0, int((plan.expiry_utc - now_utc).total_seconds()))
    card = ConfirmCardFields(
        symbol=signal.symbol,
        side=signal.direction,
        quantity=quantity,
        entry_ref=entry_ref,
        stop_loss=plan.stop_loss_price,
        notional=quantity * entry_ref,
        estimated_loss=quantity * abs(entry_ref - plan.stop_loss_price),
        mark_price=mark_price,
        plan_expiry_utc=plan.expiry_utc,
        plan_remaining_seconds=remaining,
        confirm_ttl_seconds=ttl_seconds,
        confirm_until_utc=now_utc + timedelta(seconds=ttl_seconds),
    )
    return render_shadow_message(
        ShadowMessageKind.CONFIRM_CARD, mode=mode, now_utc=now_utc, card=card
    )


# --------------------------------------------------------------------------- #
# State.
# --------------------------------------------------------------------------- #


class ConfirmState(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass
class ConfirmEntry:
    """One issued confirm token and where it stands. Internal state: read it, do not edit it."""

    short_id: str
    approval: Approval
    signal: Signal
    plan: TradePlan
    approving_user_id: int
    issued_at_utc: datetime
    ttl_seconds: int
    token_hash: str
    raw_token: str
    card_text: str
    state: ConfirmState = ConfirmState.PENDING
    outcome: ConfirmOutcome | None = None
    reason: str = ""
    decided_at_utc: datetime | None = None
    delivered: bool = False
    message_id: int | None = None
    # The SHADOW_CONFIRMED append raised, so whether it committed is unknown: the next press
    # reconciles against the journal before doing anything else (plan 16-23).
    confirm_append_unknown: bool = False
    # The CONFIRM is journaled but the reservation step has not completed: a repeated press
    # retries it (idempotent) so the ledger never lacks a journaled reservation.
    reservation_pending: bool = False

    @property
    def expires_at_utc(self) -> datetime:
        return self.issued_at_utc + timedelta(seconds=self.ttl_seconds)


@dataclass(frozen=True)
class ConfirmResult:
    """What a CONFIRM or CANCEL press amounted to."""

    outcome: ConfirmOutcome
    replayed: bool
    reason: str
    detail: str


def _correlation(approval_id: str) -> str:
    return f"shadow-confirm:{approval_id}"


def _payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _require_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be UTC-aware, got naive datetime")


def _message_id_of(result: object) -> int | None:
    value = getattr(result, "message_id", None)
    return value if isinstance(value, int) else None


# --------------------------------------------------------------------------- #
# The confirm book.
# --------------------------------------------------------------------------- #


class ConfirmBook:
    """Issues confirm tokens, holds them in memory, and journals every outcome.

    Pure of Telegram: it returns results, the callbacks of `make_confirm_callbacks` do the I/O.
    Everything is keyed by the short id of the alert (`CNF:<short>` / `CXL:<short>`).
    """

    def __init__(
        self,
        stores: ConfirmStores,
        *,
        clock: Callable[[], datetime],
        ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT,
        mode: Mode = Mode.SHADOW,
        mark_price: MarkPriceFn | None = None,
        recheck: RecheckFn | None = None,
        on_confirmed: OnConfirmedFn | None = None,
        reservations: ReservationPort | None = None,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be a positive integer, got {ttl_seconds!r}")
        require_shadow(mode)
        self._stores = stores
        self._clock = clock
        self._ttl = ttl_seconds
        self._mode = mode
        self._mark_price = mark_price
        self._recheck = recheck
        self._on_confirmed = on_confirmed
        self._reservations = reservations
        self._lock = threading.RLock()
        self._entries: dict[str, ConfirmEntry] = {}
        self._last: ConfirmRecord | None = None
        # Set by `_finish_confirm` inside the book lock, taken and called by `handle_confirm`
        # after the locks are released.
        self._deferred_confirmed: tuple[Approval, TradePlan, datetime] | None = None

    # ---- read side ------------------------------------------------------ #

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def now(self) -> datetime:
        """The book's clock: the anchor of every TTL decision."""
        return self._clock()

    def get(self, short_id: str) -> ConfirmEntry | None:
        return self._entries.get(short_id)

    def take_last_result(self) -> ConfirmRecord | None:
        """Return and clear the record of the last CONFIRM or CANCEL press (for the reply)."""
        record, self._last = self._last, None
        return record

    # ---- journal -------------------------------------------------------- #

    def _event(
        self,
        *,
        event_type: str,
        step: str,
        approval: Approval,
        signal_id: str,
        trade_plan_id: str,
        now_utc: datetime,
        payload: Mapping[str, Any],
    ) -> JournalEvent:
        correlation = _correlation(approval.approval_id)
        return JournalEvent(
            journal_event_id=correlated_event_id(
                prefix="shadow-cnf",
                correlation_id=correlation,
                event_type=event_type,
                entity_id=approval.approval_id,
                step=step,
            ),
            occurred_at_utc=now_utc,
            event_type=event_type,
            entity_type="ShadowConfirm",
            entity_id=approval.approval_id,
            correlation_id=correlation,
            signal_id=signal_id,
            trade_plan_id=trade_plan_id,
            approval_id=approval.approval_id,
            payload_json=_payload({**payload, "mode": self._mode.value}),
        )

    def _journal(
        self,
        entry: ConfirmEntry,
        event_type: str,
        step: str,
        now_utc: datetime,
        payload: Mapping[str, Any],
    ) -> None:
        self._stores.record_journal(
            self._event(
                event_type=event_type,
                step=step,
                approval=entry.approval,
                signal_id=entry.signal.signal_id,
                trade_plan_id=entry.plan.trade_plan_id,
                now_utc=now_utc,
                payload={
                    "approval_id": entry.approval.approval_id,
                    "short_id": entry.short_id,
                    "confirm_requested_at_utc": entry.issued_at_utc.isoformat(),
                    "approving_user_id": str(entry.approving_user_id),
                    **payload,
                },
            )
        )

    def _journal_rejection(
        self,
        entry: ConfirmEntry,
        *,
        reason: str,
        presented_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
        kind: str,
    ) -> None:
        self._journal(
            entry,
            EVENT_SHADOW_CONFIRM_REJECTED,
            f"press:{correlation_id}:{reason}",
            now_utc,
            {
                "reason": reason,
                "kind": kind,
                "rejected_at_utc": now_utc.isoformat(),
                "presented_user_id": None if presented_user_id is None else str(presented_user_id),
            },
        )

    # ---- issue ---------------------------------------------------------- #

    def issue(
        self,
        *,
        short_id: str,
        approval: Approval,
        signal: Signal,
        plan: TradePlan,
        approving_user_id: int | None,
        now_utc: datetime,
    ) -> ConfirmEntry:
        """Issue the confirm token for an APPROVED approval and render the card (idempotent).

        A second call for the same short id returns the existing entry: one token per approval.
        Without a user id to bind to, no card can be confirmed by anyone, so the confirm is
        journaled EXPIRED at once (reason USER_ID_UNAVAILABLE) instead of issuing a token.
        """
        _require_utc(now_utc, "now_utc")
        existing = self._entries.get(short_id)
        if existing is not None:
            return existing
        mark = self._current_mark(signal.symbol)
        raw_token = issue_one_time_token()
        entry = ConfirmEntry(
            short_id=short_id,
            approval=approval,
            signal=signal,
            plan=plan,
            approving_user_id=approving_user_id if approving_user_id is not None else -1,
            issued_at_utc=now_utc,
            ttl_seconds=self._ttl,
            token_hash=token_hash_of(raw_token),
            raw_token=raw_token,
            card_text=render_confirm_card(
                signal,
                plan,
                mode=self._mode,
                mark_price=mark,
                now_utc=now_utc,
                ttl_seconds=self._ttl,
            ),
        )
        self._entries[short_id] = entry
        if approving_user_id is None:
            self._terminate(
                entry,
                state=ConfirmState.EXPIRED,
                outcome=ConfirmOutcome.REJECTED_OTHER,
                reason=REASON_USER_ID_UNAVAILABLE,
                now_utc=now_utc,
                event_type=EVENT_SHADOW_CONFIRM_EXPIRED,
            )
        return entry

    def _current_mark(self, symbol: str) -> Decimal | None:
        if self._mark_price is None:
            return None
        try:
            return self._mark_price(symbol)
        except Exception as exc:  # noqa: BLE001 - a missing mark price is shown, not fatal
            log.warning("paper.shadow_confirm.mark_price_failed", error_class=type(exc).__name__)
            return None

    # ---- delivery outcomes ---------------------------------------------- #

    def record_issued(
        self,
        entry: ConfirmEntry,
        *,
        delivery: str,
        message_id: int | None,
        attempts: int,
        edit_failure: TelegramFailure | None,
        now_utc: datetime,
    ) -> None:
        """The card reached the chat: journal SHADOW_CONFIRM_ISSUED (unless already decided)."""
        if entry.state is not ConfirmState.PENDING:
            return
        if now_utc >= entry.expires_at_utc:
            # Fail safe: a card delivered after its TTL ran out is expired at once.
            self._terminate(
                entry,
                state=ConfirmState.EXPIRED,
                outcome=ConfirmOutcome.EXPIRED_TTL,
                reason=REASON_CONFIRM_TTL_ELAPSED,
                now_utc=now_utc,
                event_type=EVENT_SHADOW_CONFIRM_EXPIRED,
                extra={"delivered_late": True, "delivery": delivery},
            )
            return
        self._journal(
            entry,
            EVENT_SHADOW_CONFIRM_ISSUED,
            "issued",
            now_utc,
            {
                "issued_at_utc": entry.issued_at_utc.isoformat(),
                "expires_at_utc": entry.expires_at_utc.isoformat(),
                "ttl_seconds": entry.ttl_seconds,
                "delivery": delivery,
                "message_id": None if message_id is None else str(message_id),
                "attempts": attempts,
                "edit_failure_kind": None if edit_failure is None else edit_failure.kind.value,
                "confirm_token_hash_prefix": entry.token_hash[:16],
            },
        )
        entry.delivered = True
        entry.message_id = message_id

    def abort_delivery(
        self,
        entry: ConfirmEntry,
        *,
        failure: TelegramFailure,
        notice: str,
        attempts: int,
        now_utc: datetime,
    ) -> None:
        """No card could be delivered: EXPIRED with reason CARD_DELIVERY_FAILED, token invalid."""
        if entry.state is not ConfirmState.PENDING:
            return
        self._terminate(
            entry,
            state=ConfirmState.EXPIRED,
            outcome=ConfirmOutcome.REJECTED_OTHER,
            reason=REASON_CARD_DELIVERY_FAILED,
            now_utc=now_utc,
            event_type=EVENT_SHADOW_CONFIRM_EXPIRED,
            extra={
                "failure_kind": failure.kind.value,
                "retry_after_seconds": failure.retry_after_seconds,
                "error_class": failure.detail,
                "attempts": attempts,
                "failure_notice": notice,
            },
        )

    def record_notice_failed(
        self, entry: ConfirmEntry, failure: TelegramFailure, now_utc: datetime
    ) -> None:
        """The best-effort failure notice failed too: journal it, change nothing else."""
        self._journal(
            entry,
            EVENT_SHADOW_CONFIRM_NOTICE_FAILED,
            "notice_failed",
            now_utc,
            {
                "failure_kind": failure.kind.value,
                "retry_after_seconds": failure.retry_after_seconds,
                "error_class": failure.detail,
            },
        )

    # ---- terminal transitions ------------------------------------------- #

    def _terminate(
        self,
        entry: ConfirmEntry,
        *,
        state: ConfirmState,
        outcome: ConfirmOutcome,
        reason: str,
        now_utc: datetime,
        event_type: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """Journal the single terminal event, THEN move the state (a failed write moves nothing)."""
        body: dict[str, Any] = {"reason": reason, "decided_at_utc": now_utc.isoformat()}
        if state is ConfirmState.CONFIRMED:
            body["confirmed_at_utc"] = now_utc.isoformat()
        if state is ConfirmState.CANCELLED:
            body["cancelled_at_utc"] = now_utc.isoformat()
        if state is ConfirmState.EXPIRED:
            body["expired_at_utc"] = now_utc.isoformat()
        # Integer milliseconds: no float anywhere in this module (Decimal-only guard).
        body["elapsed_ms"] = max(0, (now_utc - entry.issued_at_utc) // timedelta(milliseconds=1))
        if extra:
            body.update(extra)
        self._journal(entry, event_type, "terminal", now_utc, body)
        entry.state = state
        entry.outcome = outcome
        entry.reason = reason
        entry.decided_at_utc = now_utc

    def _result(
        self, entry: ConfirmEntry, outcome: ConfirmOutcome, reason: str, *, replayed: bool
    ) -> ConfirmResult:
        detail = reason if not replayed else f"REPLAYED existing outcome ({reason})"
        result = ConfirmResult(outcome=outcome, replayed=replayed, reason=reason, detail=detail)
        self._last = ConfirmRecord(
            outcome=outcome,
            detail=detail,
            confirm_requested_at_utc=entry.issued_at_utc,
            plan_expiry_utc=entry.plan.expiry_utc,
        )
        return result

    def _replay(
        self,
        entry: ConfirmEntry,
        *,
        kind: str,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        """A press on a decided confirm replays the existing outcome.

        CONFIRMED and CANCELLED replays write nothing. A press on an EXPIRED confirm hit a dead
        token (a TTL that ran out, a failed card delivery, a restart): the attempt itself is
        journaled (idempotent per callback query) and simulates nothing.
        """
        if entry.state is ConfirmState.EXPIRED:
            self._journal_rejection(
                entry,
                reason=REASON_CONFIRM_ALREADY_EXPIRED,
                presented_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
                kind=kind,
            )
        if entry.state is ConfirmState.CONFIRMED:
            return self._result(entry, ConfirmOutcome.CONFIRMED, "CONFIRMED", replayed=True)
        if entry.state is ConfirmState.CANCELLED:
            return self._result(entry, ConfirmOutcome.CANCELLED, "CANCELLED", replayed=True)
        outcome = entry.outcome or ConfirmOutcome.REJECTED_OTHER
        return self._result(entry, outcome, entry.reason, replayed=True)

    def _expire_ttl(self, entry: ConfirmEntry, now_utc: datetime) -> ConfirmResult:
        self._terminate(
            entry,
            state=ConfirmState.EXPIRED,
            outcome=ConfirmOutcome.EXPIRED_TTL,
            reason=REASON_CONFIRM_TTL_ELAPSED,
            now_utc=now_utc,
            event_type=EVENT_SHADOW_CONFIRM_EXPIRED,
        )
        return self._result(
            entry, ConfirmOutcome.EXPIRED_TTL, REASON_CONFIRM_TTL_ELAPSED, replayed=False
        )

    def _press_gate(
        self,
        entry: ConfirmEntry,
        *,
        kind: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult | None:
        """Chat, then user: a refusal is journaled and leaves the token usable by its owner."""
        if chat_id != authorized_chat_id:
            self._journal_rejection(
                entry,
                reason=REASON_CHAT_MISMATCH,
                presented_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
                kind=kind,
            )
            return self._result(
                entry, ConfirmOutcome.REJECTED_OTHER, REASON_CHAT_MISMATCH, replayed=False
            )
        if from_user_id is None or from_user_id != entry.approving_user_id:
            self._journal_rejection(
                entry,
                reason=REASON_USER_MISMATCH,
                presented_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
                kind=kind,
            )
            return self._result(
                entry, ConfirmOutcome.REJECTED_USER_MISMATCH, REASON_USER_MISMATCH, replayed=False
            )
        return None

    def _reject_unknown(
        self,
        short_id: str,
        *,
        kind: str,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        """No confirm context for this short id (never issued, or lost to a restart)."""
        mapping = self._stores.lookup_by_short_id(short_id)
        signal_id, plan_id = (None, None) if mapping is None else mapping
        correlation = f"shadow-confirm:short:{short_id}"
        self._stores.record_journal(
            JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix="shadow-cnf",
                    correlation_id=correlation,
                    event_type=EVENT_SHADOW_CONFIRM_REJECTED,
                    entity_id=f"short:{short_id}",
                    step=f"press:{correlation_id}",
                ),
                occurred_at_utc=now_utc,
                event_type=EVENT_SHADOW_CONFIRM_REJECTED,
                entity_type="ShadowConfirm",
                entity_id=f"short:{short_id}",
                correlation_id=correlation,
                signal_id=signal_id,
                trade_plan_id=plan_id,
                payload_json=_payload(
                    {
                        "reason": REASON_NO_CONFIRM_CONTEXT,
                        "kind": kind,
                        "short_id": short_id,
                        "rejected_at_utc": now_utc.isoformat(),
                        "presented_user_id": None if from_user_id is None else str(from_user_id),
                        "mode": self._mode.value,
                    }
                ),
            )
        )
        detail = REASON_NO_CONFIRM_CONTEXT
        self._last = ConfirmRecord(
            outcome=ConfirmOutcome.REJECTED_OTHER,
            detail=detail,
            confirm_requested_at_utc=None,
            plan_expiry_utc=None,
        )
        return ConfirmResult(ConfirmOutcome.REJECTED_OTHER, False, detail, detail)

    # ---- the binding gate ------------------------------------------------ #

    def _binding_gate(
        self, entry: ConfirmEntry, now_utc: datetime
    ) -> tuple[RejectionReason, ConfirmOutcome] | None:
        """Re-run the approval binding gate at CONFIRM, in the order of `src/approval/binding.py`.

        Chat was gated first (`_press_gate`). Then: plan expiry (inclusive, REV-12), plan hash,
        version and parameter set and the identity of the approved row. The confirm token itself
        is the in-memory capability looked up by short id, so there is no token-hash gate here.
        """
        plan, signal, approval = entry.plan, entry.signal, entry.approval
        if now_utc >= plan.expiry_utc:
            return RejectionReason.APPROVAL_EXPIRED, ConfirmOutcome.REJECTED_PLAN_EXPIRED
        stored = self._stores.lookup_by_token_hash(approval.approval_token_hash)
        if stored is None or stored.status != ApprovalResult.APPROVED:
            return RejectionReason.INVALIDATED, ConfirmOutcome.REJECTED_OTHER
        if stored.request_hash != plan.plan_hash or entry.approval.request_hash != plan.plan_hash:
            return RejectionReason.STALE_SETUP, ConfirmOutcome.REJECTED_OTHER
        if (
            plan.signal_id != signal.signal_id
            or stored.trade_plan_id != plan.trade_plan_id
            or stored.signal_id != signal.signal_id
        ):
            return RejectionReason.INVALIDATED, ConfirmOutcome.REJECTED_OTHER
        return None

    def _run_recheck(self, entry: ConfirmEntry, now_utc: datetime) -> str | None:
        """The injected re-check, then the reservation capacity check; fail closed on any error."""
        try:
            if self._recheck is not None:
                reason = self._recheck(entry.signal, entry.plan, now_utc)
                if reason is not None:
                    return reason.value if isinstance(reason, RejectionReason) else reason
            if self._reservations is not None:
                return self._reservations.check(entry.signal, entry.plan, now_utc)
        except Exception as exc:  # noqa: BLE001 - fail closed: a broken re-check rejects
            log.warning("paper.shadow_confirm.recheck_failed", error_class=type(exc).__name__)
            return REASON_RECHECK_ERROR
        return None

    # ---- CONFIRM / CANCEL ------------------------------------------------ #

    def handle_confirm(
        self,
        *,
        short_id: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        """A CNF: press. CONFIRMED only for the approving user, once, inside the TTL, after the
        binding gate and the injected re-check; every other outcome is journaled and simulates
        nothing. A repeat press replays the existing outcome.

        With a `ReservationPort` (plan 16-23, Q-C `reserve-at-confirm`) the whole press runs in
        its serialized section: re-check and capacity check (before the journal write), the
        SHADOW_CONFIRMED write, then the reservation. A failed check or write reserves nothing.
        """
        _require_utc(now_utc, "now_utc")
        return self._in_section(
            lambda: self._handle_confirm_locked(
                short_id=short_id,
                chat_id=chat_id,
                authorized_chat_id=authorized_chat_id,
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        )

    def _in_section(self, body: Callable[[], _T]) -> _T:
        """Run `body` under the book lock and, with a reservation port, its serialized section.

        Every path that can finish a CONFIRM (a press, an adopted stored CONFIRM) runs here, so
        `on_confirmed` is called once for it AFTER the section and the book lock are released
        (B2-CR-01): the hook may take the coordinator lock without waiting on the ledger lock.
        """
        with self._lock:
            self._deferred_confirmed = None
            if self._reservations is None:
                result = body()
            else:
                with self._reservations.section():
                    result = body()
            deferred, self._deferred_confirmed = self._deferred_confirmed, None
        if deferred is not None and self._on_confirmed is not None:
            self._on_confirmed(*deferred)
        return result

    def _reconcile_unknown(self, entry: ConfirmEntry) -> ConfirmResult | None:
        """Settle an earlier SHADOW_CONFIRMED append of unknown outcome against the journal.

        None when the entry has no unknown append, or the journal shows none committed (the flag
        is cleared and the caller goes on). A committed one is adopted as the CONFIRM and its
        result returned: the caller must not write a second terminal event (plan 16-58, B2-WR-02).
        A journal that cannot be read raises (fail closed: nothing is written).
        """
        if not entry.confirm_append_unknown:
            return None
        stored = self._stored_confirmed(entry)
        if stored is not None:
            return self._adopt_stored_confirm(entry, stored)
        entry.confirm_append_unknown = False
        return None

    def _handle_confirm_locked(
        self,
        *,
        short_id: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        entry = self._entries.get(short_id)
        if entry is None:
            return self._reject_unknown(
                short_id,
                kind="CONFIRM",
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        refused = self._press_gate(
            entry,
            kind="CONFIRM",
            chat_id=chat_id,
            authorized_chat_id=authorized_chat_id,
            from_user_id=from_user_id,
            now_utc=now_utc,
            correlation_id=correlation_id,
        )
        if refused is not None:
            return refused
        if entry.state is ConfirmState.CONFIRMED and entry.reservation_pending:
            # Journaled CONFIRMED but the reservation step did not complete: finish it (idempotent).
            return self._finish_confirm(entry, entry.decided_at_utc or now_utc)
        if entry.state is not ConfirmState.PENDING:
            return self._replay(
                entry,
                kind="CONFIRM",
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        # An earlier SHADOW_CONFIRMED append has an unknown outcome: the journal decides. A
        # journal that cannot be read raises here (fail closed: nothing reserved).
        adopted = self._reconcile_unknown(entry)
        if adopted is not None:
            return adopted
        if now_utc >= entry.expires_at_utc:  # boundary inclusive, as binding.py
            return self._expire_ttl(entry, now_utc)
        rejection = self._binding_gate(entry, now_utc)
        if rejection is not None:
            reason, outcome = rejection
            return self._reject_terminal(entry, reason.value, outcome, now_utc)
        recheck_reason = self._run_recheck(entry, now_utc)
        if recheck_reason is not None:
            return self._reject_terminal(
                entry, recheck_reason, ConfirmOutcome.REJECTED_OTHER, now_utc
            )
        extra: dict[str, Any] = {
            "plan_hash": entry.plan.plan_hash,
            "ttl_seconds": entry.ttl_seconds,
        }
        if self._reservations is not None:
            try:
                extra.update(
                    self._reservations.confirm_payload(
                        approval=entry.approval,
                        signal=entry.signal,
                        plan=entry.plan,
                        short_id=entry.short_id,
                        confirmed_at_utc=now_utc,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - fail closed: no reservation facts, no confirm
                log.warning(
                    "paper.shadow_confirm.reservation_payload_failed",
                    error_class=type(exc).__name__,
                )
                return self._reject_terminal(
                    entry, REASON_RECHECK_ERROR, ConfirmOutcome.REJECTED_OTHER, now_utc
                )
        try:
            self._terminate(
                entry,
                state=ConfirmState.CONFIRMED,
                outcome=ConfirmOutcome.CONFIRMED,
                reason="CONFIRMED",
                now_utc=now_utc,
                event_type=EVENT_SHADOW_CONFIRMED,
                extra=extra,
            )
        except Exception:
            # The append raised: it may or may not have committed. Reconcile against the journal
            # before anything else; an event that did commit is the authoritative CONFIRM.
            entry.confirm_append_unknown = True
            stored = self._stored_confirmed(entry)  # raises when unreadable: fail closed
            if stored is None:
                entry.confirm_append_unknown = False
                raise
            return self._adopt_stored_confirm(entry, stored)
        return self._finish_confirm(entry, now_utc)

    def _stored_confirmed(self, entry: ConfirmEntry) -> JournalEvent | None:
        """The SHADOW_CONFIRMED event of this approval in the journal, or None when absent."""
        for event in self._stores.journal_for_correlation(_correlation(entry.approval.approval_id)):
            if event.event_type == EVENT_SHADOW_CONFIRMED:
                return event
        return None

    def _adopt_stored_confirm(self, entry: ConfirmEntry, stored: JournalEvent) -> ConfirmResult:
        """Treat a committed SHADOW_CONFIRMED as the CONFIRM; reuse its stored confirm instant."""
        loaded = json.loads(stored.payload_json) if stored.payload_json else {}
        raw = loaded.get("confirmed_at_utc") if isinstance(loaded, dict) else None
        if not isinstance(raw, str):
            raise ValueError("the stored SHADOW_CONFIRMED has no confirmed_at_utc")
        confirmed_at = datetime.fromisoformat(raw)
        entry.state = ConfirmState.CONFIRMED
        entry.outcome = ConfirmOutcome.CONFIRMED
        entry.reason = "CONFIRMED"
        entry.decided_at_utc = confirmed_at
        entry.confirm_append_unknown = False
        return self._finish_confirm(entry, confirmed_at)

    def _finish_confirm(self, entry: ConfirmEntry, confirmed_at_utc: datetime) -> ConfirmResult:
        """After SHADOW_CONFIRMED is journaled: reserve the exposure, then notify `on_confirmed`.

        A reservation that cannot be made (never expected inside the serialized section) is
        journaled by the reservation layer as refused and the press is reported as NOT confirmed,
        so a refused plan never reaches `on_confirmed`. A reserve that raises leaves
        `reservation_pending` set; a repeated press retries it.
        """
        result = self._result(entry, ConfirmOutcome.CONFIRMED, "CONFIRMED", replayed=False)
        if self._reservations is not None:
            entry.reservation_pending = True
            outcome = self._reservations.reserve(
                approval=entry.approval,
                signal=entry.signal,
                plan=entry.plan,
                short_id=entry.short_id,
                confirmed_at_utc=confirmed_at_utc,
            )
            entry.reservation_pending = False
            if not outcome.reserved:
                return self._result(
                    entry, ConfirmOutcome.REJECTED_OTHER, outcome.reason_code, replayed=False
                )
        # State is already CONFIRMED, so a replay can never set this a second time. The hook runs
        # in `handle_confirm` once the section is released (B2-CR-01).
        self._deferred_confirmed = (entry.approval, entry.plan, confirmed_at_utc)
        return result

    def _reject_terminal(
        self, entry: ConfirmEntry, reason: str, outcome: ConfirmOutcome, now_utc: datetime
    ) -> ConfirmResult:
        self._terminate(
            entry,
            state=ConfirmState.EXPIRED,
            outcome=outcome,
            reason=reason,
            now_utc=now_utc,
            event_type=EVENT_SHADOW_CONFIRM_EXPIRED,
            extra={"rejected_at_confirm": True},
        )
        return self._result(entry, outcome, reason, replayed=False)

    def handle_cancel(
        self,
        *,
        short_id: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        """A CXL: press. Journals SHADOW_CONFIRM_CANCELLED; nothing is simulated. A cancel after
        a decision cannot flip it: it replays the existing outcome. A CONFIRM append of unknown
        outcome is reconciled against the journal first, so a committed CONFIRM is never followed
        by a second terminal event (B2-WR-02).
        """
        _require_utc(now_utc, "now_utc")
        return self._in_section(
            lambda: self._handle_cancel_locked(
                short_id=short_id,
                chat_id=chat_id,
                authorized_chat_id=authorized_chat_id,
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        )

    def _handle_cancel_locked(
        self,
        *,
        short_id: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        entry = self._entries.get(short_id)
        if entry is None:
            return self._reject_unknown(
                short_id,
                kind="CANCEL",
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        refused = self._press_gate(
            entry,
            kind="CANCEL",
            chat_id=chat_id,
            authorized_chat_id=authorized_chat_id,
            from_user_id=from_user_id,
            now_utc=now_utc,
            correlation_id=correlation_id,
        )
        if refused is not None:
            return refused
        if entry.state is ConfirmState.PENDING:
            self._reconcile_unknown(entry)  # adopting a committed CONFIRM makes it non-PENDING
        if entry.state is not ConfirmState.PENDING:
            return self._replay(
                entry,
                kind="CANCEL",
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        if now_utc >= entry.expires_at_utc:
            return self._expire_ttl(entry, now_utc)
        self._terminate(
            entry,
            state=ConfirmState.CANCELLED,
            outcome=ConfirmOutcome.CANCELLED,
            reason="CANCELLED",
            now_utc=now_utc,
            event_type=EVENT_SHADOW_CONFIRM_CANCELLED,
        )
        return self._result(entry, ConfirmOutcome.CANCELLED, "CANCELLED", replayed=False)

    # ---- sweeps ---------------------------------------------------------- #

    def expire_if_due(self, short_id: str, now_utc: datetime) -> bool:
        """Expire one outstanding confirm whose TTL has run out. True when it was expired.

        An unknown CONFIRM append is reconciled against the journal first (B2-WR-02): a committed
        CONFIRM is adopted and nothing is expired; an unreadable journal raises.
        """
        return self._in_section(lambda: self._expire_if_due_locked(short_id, now_utc))

    def _expire_if_due_locked(self, short_id: str, now_utc: datetime) -> bool:
        entry = self._entries.get(short_id)
        if (
            entry is None
            or entry.state is not ConfirmState.PENDING
            or now_utc < entry.expires_at_utc
        ):
            return False
        if self._reconcile_unknown(entry) is not None:
            return False
        self._expire_ttl(entry, now_utc)
        return True

    def expire_due(self, now_utc: datetime) -> list[str]:
        """Journal EXPIRED for every confirm past its TTL, and repair stranded approvals.

        Returns the approval ids expired by this call, sorted. A second call writes nothing.
        Two sources: tokens held in memory (reason CONFIRM_TTL_ELAPSED), and APPROVED approvals
        older than the TTL that have no terminal confirm event and no token here: with no
        SHADOW_CONFIRM_* event at all the card was never delivered (CARD_DELIVERY_FAILED), with
        an ISSUED event only the token is gone (RUNTIME_RESTART).
        """
        _require_utc(now_utc, "now_utc")
        expired = self._in_section(lambda: self._expire_held_locked(now_utc))
        expired.extend(self._sweep_orphans(now_utc, require_age=True))
        return sorted(expired)

    def _expire_held_locked(self, now_utc: datetime) -> list[str]:
        expired: list[str] = []
        for entry in sorted(self._entries.values(), key=lambda e: e.approval.approval_id):
            if entry.state is ConfirmState.PENDING and now_utc >= entry.expires_at_utc:
                if self._reconcile_unknown(entry) is not None:
                    continue  # the unknown append had committed: the CONFIRM stands (B2-WR-02)
                self._expire_ttl(entry, now_utc)
                expired.append(entry.approval.approval_id)
        return expired

    def expire_on_restart(self, now_utc: datetime) -> list[str]:
        """Expire every outstanding confirm of the previous process (raw tokens are gone).

        Call once at startup with a fresh book. APPROVED approvals without a terminal confirm
        event are expired at once: ISSUED ones with reason RUNTIME_RESTART, those that never
        got a card with CARD_DELIVERY_FAILED. Idempotent.
        """
        _require_utc(now_utc, "now_utc")
        return sorted(self._sweep_orphans(now_utc, require_age=False))

    def _sweep_orphans(self, now_utc: datetime, *, require_age: bool) -> list[str]:
        swept: list[str] = []
        held = {e.approval.approval_id for e in self._entries.values()}
        for approval in sorted(self._stores.list_approved_approvals(), key=lambda a: a.approval_id):
            if approval.approval_id in held:
                continue  # its token is in memory: the TTL path owns it
            events = self._stores.journal_for_correlation(_correlation(approval.approval_id))
            types = {e.event_type for e in events}
            if types & set(TERMINAL_CONFIRM_EVENTS):
                continue
            issued = [e for e in events if e.event_type == EVENT_SHADOW_CONFIRM_ISSUED]
            if issued:
                reason = REASON_RUNTIME_RESTART
                base = issued[0].occurred_at_utc
            else:
                reason = REASON_CARD_DELIVERY_FAILED
                base = approval.acted_at_utc or approval.requested_at_utc
            if require_age and now_utc < base + timedelta(seconds=self._ttl):
                continue
            self._stores.record_journal(
                self._event(
                    event_type=EVENT_SHADOW_CONFIRM_EXPIRED,
                    step="terminal",
                    approval=approval,
                    signal_id=approval.signal_id,
                    trade_plan_id=approval.trade_plan_id,
                    now_utc=now_utc,
                    payload={
                        "approval_id": approval.approval_id,
                        "reason": reason,
                        "expired_at_utc": now_utc.isoformat(),
                        "swept": True,
                    },
                )
            )
            swept.append(approval.approval_id)
        return swept


def assert_no_stranded_approvals(
    stores: ConfirmStores,
    now_utc: datetime,
    *,
    ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT,
) -> None:
    """Raise `StrandedApprovals` unless every approved plan past the TTL has one terminal event.

    The invariant of T-16-112: after APPROVE a plan can never sit with no confirm card and no
    journaled outcome. Each APPROVED approval older than `ttl_seconds` must have exactly one
    SHADOW_CONFIRMED, SHADOW_CONFIRM_CANCELLED or SHADOW_CONFIRM_EXPIRED event (any reason).
    """
    _require_utc(now_utc, "now_utc")
    stranded: list[str] = []
    for approval in sorted(stores.list_approved_approvals(), key=lambda a: a.approval_id):
        acted = approval.acted_at_utc or approval.requested_at_utc
        if now_utc < acted + timedelta(seconds=ttl_seconds):
            continue
        events = stores.journal_for_correlation(_correlation(approval.approval_id))
        terminal = [e for e in events if e.event_type in TERMINAL_CONFIRM_EVENTS]
        if len(terminal) != 1:
            stranded.append(f"{approval.approval_id} ({len(terminal)} terminal events)")
    if stranded:
        raise StrandedApprovals(
            "approved plans without exactly one confirm outcome: " + ", ".join(stranded)
        )


# --------------------------------------------------------------------------- #
# Card delivery: edit, one fallback send, fail closed.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CardDelivery:
    """What `deliver_confirm_card` did. It never raises on a Telegram failure."""

    delivered: bool
    delivery: str
    message_id: int | None
    attempts: int
    failure: TelegramFailure | None


def _failure_of(exc: BaseException) -> TelegramFailure:
    if isinstance(exc, TelegramSendError):
        return exc.failure
    return TelegramFailure(TelegramFailureKind.UNKNOWN, None, type(exc).__name__)


async def _try_edit(
    bot: TelegramTextBot, chat_id: int, message_id: int, text: str, keyboard: Any
) -> TelegramFailure | None:
    try:
        await edit_to_confirm_card(bot, chat_id, message_id, text, keyboard)
    except Exception as exc:  # noqa: BLE001 - every failure is classified, never raised
        return _failure_of(exc)
    return None


async def deliver_confirm_card(
    *,
    book: ConfirmBook,
    entry: ConfirmEntry,
    bot: TelegramTextBot,
    chat_id: int,
    message_id: int | None,
    mode: Mode,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    replay: bool = False,
) -> CardDelivery:
    """Edit the alert into the card; on failure one fallback send; else expire the confirm.

    Edit: a 429 is honoured inside the REMAINING confirm TTL (the anchor stays the issue time):
    the wait is the server's retry_after, and a retry_after longer than the remaining window
    stops the edit at once with no sleep. `MESSAGE_NOT_MODIFIED` counts as success. Any other
    failure goes straight to the fallback: exactly one `send_text` of the same card (same token,
    same issue time, same keyboard). When that fails too, or the edit was throttled beyond the
    window, the confirm is journaled EXPIRED with reason CARD_DELIVERY_FAILED and its token is
    invalid; one best-effort notice is attempted (not while Telegram is throttling us) and its
    own failure is journaled. A decided approval is never reverted.

    With `replay=True` (a repeated APPROVE press) the stored card is edited back in once; a
    failure is logged and nothing is journaled, the confirm keeps its state.
    """
    require_shadow(mode)
    keyboard = build_confirm_keyboard(entry.signal.signal_id)
    clock = book.now

    def remaining() -> timedelta:
        return timedelta(seconds=entry.ttl_seconds) - (clock() - entry.issued_at_utc)

    attempts = 0
    edit_failure: TelegramFailure | None = None
    if message_id is not None:
        while True:
            attempts += 1
            edit_failure = await _try_edit(bot, chat_id, message_id, entry.card_text, keyboard)
            if (
                edit_failure is None
                or edit_failure.kind is TelegramFailureKind.MESSAGE_NOT_MODIFIED
            ):
                edit_failure = None
                break
            if (
                edit_failure.kind is not TelegramFailureKind.RATE_LIMITED
                or attempts >= NOTIFY_MAX_ATTEMPTS
            ):
                break
            retry_after = edit_failure.retry_after_seconds or 0
            window = remaining()
            if timedelta(seconds=retry_after) > window or window <= timedelta(0):
                break
            await sleep(retry_after)
        if edit_failure is None:
            return await _delivered(
                book, entry, DELIVERY_EDIT, message_id, attempts, None, replay=replay
            )
    if replay:
        log.warning(
            "paper.shadow_confirm.replay_edit_failed",
            kind=None if edit_failure is None else edit_failure.kind.value,
        )
        return CardDelivery(False, DELIVERY_EDIT, message_id, attempts, edit_failure)

    throttled = (
        edit_failure is not None
        and edit_failure.kind is TelegramFailureKind.RATE_LIMITED
        and timedelta(seconds=edit_failure.retry_after_seconds or 0) > remaining()
    )
    last_failure = edit_failure
    if not throttled:
        attempts += 1
        try:
            sent = await send_text(bot, chat_id, entry.card_text, keyboard)
        except Exception as exc:  # noqa: BLE001 - every failure is classified, never raised
            last_failure = _failure_of(exc)
        else:
            return await _delivered(
                book,
                entry,
                DELIVERY_FALLBACK_SEND,
                _message_id_of(sent),
                attempts,
                edit_failure,
                replay=False,
            )
    failure = last_failure or TelegramFailure(TelegramFailureKind.UNKNOWN, None, "NoMessageId")
    notice = _NOTICE_SKIPPED_RATE_LIMITED if throttled else _NOTICE_SENT
    book.abort_delivery(entry, failure=failure, notice=notice, attempts=attempts, now_utc=clock())
    if not throttled:
        notice_text = render_shadow_message(
            ShadowMessageKind.CARD_DELIVERY_FAILED,
            mode=mode,
            now_utc=clock(),
            failure_kind=failure.kind.value,
            signal_id=entry.signal.signal_id,
            expiry_utc=entry.plan.expiry_utc,
        )
        try:
            await send_text(bot, chat_id, notice_text)
        except Exception as exc:  # noqa: BLE001 - best effort; journaled, changes nothing
            book.record_notice_failed(entry, _failure_of(exc), clock())
    return CardDelivery(False, "", None, attempts, failure)


async def _delivered(
    book: ConfirmBook,
    entry: ConfirmEntry,
    delivery: str,
    message_id: int | None,
    attempts: int,
    edit_failure: TelegramFailure | None,
    *,
    replay: bool,
) -> CardDelivery:
    if not replay:
        book.record_issued(
            entry,
            delivery=delivery,
            message_id=message_id,
            attempts=attempts,
            edit_failure=edit_failure,
            now_utc=book.now(),
        )
    return CardDelivery(True, delivery, message_id, attempts, None)


# --------------------------------------------------------------------------- #
# The hooks of on_callback.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConfirmCallbacks:
    """The two hooks to pass to `on_callback` (`approved_handler`, `confirm_handler`)."""

    approved_handler: Callable[[CallbackPress, DispatchResult], Awaitable[bool]]
    confirm_handler: Callable[[CallbackPress], Awaitable[ConfirmReply]]


def make_confirm_callbacks(
    *,
    approvals: ShadowApprovalBook,
    confirm: ConfirmBook,
    bot: TelegramTextBot,
    mode: Mode,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ConfirmCallbacks:
    """Wire the confirm flow into `on_callback`. No exchange object is passed or reachable."""
    require_shadow(mode)

    async def approved_handler(press: CallbackPress, result: DispatchResult) -> bool:
        """After APPROVE: edit the alert into the confirmation card. True when it was handled."""
        short_id = press.parsed.short_id
        now = press.callback_at_utc
        existing = confirm.get(short_id)
        if existing is not None:
            # A repeated APPROVE press: replay to the existing confirm, never a second token.
            confirm.expire_if_due(short_id, now)
            if existing.state is not ConfirmState.PENDING or not existing.delivered:
                return False
            await deliver_confirm_card(
                book=confirm,
                entry=existing,
                bot=bot,
                chat_id=press.chat_id,
                message_id=press.message_id,
                mode=mode,
                sleep=sleep,
                replay=True,
            )
            return True
        context = approvals.plan_context(short_id)
        if context is None or result.approval is None:
            return False
        signal, plan = context
        # The approval is stamped by its own, later clock read (`ShadowApprovalBook.dispatch`
        # runs in a worker thread), so its `acted_at_utc` can sit a few microseconds after the
        # press time. A card is never stamped before the approval it follows (the journal check
        # `confirm_requested_at_utc >= acted_at_utc` is strict), and the TTL, the expiry and the
        # journaled `confirm_requested_at_utc` all follow this one stamp.
        acted_at = result.approval.acted_at_utc
        entry = confirm.issue(
            short_id=short_id,
            approval=result.approval,
            signal=signal,
            plan=plan,
            approving_user_id=press.from_user_id,
            now_utc=now if acted_at is None else max(now, acted_at),
        )
        if entry.state is not ConfirmState.PENDING:
            return False
        await deliver_confirm_card(
            book=confirm,
            entry=entry,
            bot=bot,
            chat_id=press.chat_id,
            message_id=press.message_id,
            mode=mode,
            sleep=sleep,
        )
        approvals.take_last_decision()
        return True

    async def confirm_handler(press: CallbackPress) -> ConfirmReply:
        """A CNF: or CXL: press, after the chat gate. Journals; simulates nothing itself."""
        if press.parsed.kind is CallbackKind.CONFIRM:
            outcome = confirm.handle_confirm(
                short_id=press.parsed.short_id,
                chat_id=press.chat_id,
                authorized_chat_id=press.authorized_chat_id,
                from_user_id=press.from_user_id,
                now_utc=press.callback_at_utc,
                correlation_id=press.correlation_id,
            ).outcome
            return ConfirmReply(ok=outcome is ConfirmOutcome.CONFIRMED, text=outcome.value)
        if press.parsed.kind is CallbackKind.CANCEL:
            outcome = confirm.handle_cancel(
                short_id=press.parsed.short_id,
                chat_id=press.chat_id,
                authorized_chat_id=press.authorized_chat_id,
                from_user_id=press.from_user_id,
                now_utc=press.callback_at_utc,
                correlation_id=press.correlation_id,
            ).outcome
            return ConfirmReply(ok=outcome is ConfirmOutcome.CANCELLED, text=outcome.value)
        raise ValueError(f"not a confirm press: {press.parsed.kind!r}")

    return ConfirmCallbacks(approved_handler=approved_handler, confirm_handler=confirm_handler)


__all__ = [
    "CONFIRM_TTL_SECONDS_DEFAULT",
    "EVENT_SHADOW_CONFIRMED",
    "EVENT_SHADOW_CONFIRM_CANCELLED",
    "EVENT_SHADOW_CONFIRM_EXPIRED",
    "EVENT_SHADOW_CONFIRM_ISSUED",
    "EVENT_SHADOW_CONFIRM_NOTICE_FAILED",
    "EVENT_SHADOW_CONFIRM_REJECTED",
    "TERMINAL_CONFIRM_EVENTS",
    "CardDelivery",
    "ConfirmBook",
    "ConfirmCallbacks",
    "ConfirmEntry",
    "ConfirmResult",
    "ConfirmState",
    "ConfirmStores",
    "ReservationPort",
    "ReserveOutcome",
    "StrandedApprovals",
    "assert_no_stranded_approvals",
    "deliver_confirm_card",
    "make_confirm_callbacks",
    "render_confirm_card",
]
