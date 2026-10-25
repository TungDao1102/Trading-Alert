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
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

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
from src.approval.confirm_core import (
    CONFIRM_TTL_SECONDS_DEFAULT,
    REASON_CARD_DELIVERY_FAILED,
    REASON_CHAT_MISMATCH,
    REASON_CONFIRM_ALREADY_EXPIRED,
    REASON_CONFIRM_TTL_ELAPSED,
    REASON_NO_CONFIRM_CONTEXT,
    REASON_RECHECK_ERROR,
    REASON_RUNTIME_RESTART,
    REASON_USER_ID_UNAVAILABLE,
    REASON_USER_MISMATCH,
    SHADOW_CONFIRM_PROFILE,
    ConfirmEntry,
    ConfirmOutcome,
    ConfirmResult,
    ConfirmState,
    ConfirmStores,
    MarkPriceFn,
    OnConfirmedFn,
    RecheckFn,
    ReservationPort,
    ReserveOutcome,
    StrandedApprovals,
)
from src.approval.confirm_core import ConfirmBook as CoreConfirmBook
from src.approval.confirm_core import (
    assert_no_stranded_approvals as core_assert_no_stranded_approvals,
)
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper.notify import NOTIFY_MAX_ATTEMPTS
from src.paper.shadow import (
    ConfirmCardFields,
    Mode,
    ShadowApprovalBook,
    ShadowMessageKind,
    render_shadow_message,
    require_shadow,
)

log = structlog.get_logger()

# The SHADOW names of the profile's journal events (read by `src/paper/attribution.py` and the
# SHADOW tests); the literals live in `SHADOW_CONFIRM_PROFILE`.
EVENT_SHADOW_CONFIRM_ISSUED: Final = SHADOW_CONFIRM_PROFILE.event_issued
EVENT_SHADOW_CONFIRMED: Final = SHADOW_CONFIRM_PROFILE.event_confirmed
EVENT_SHADOW_CONFIRM_CANCELLED: Final = SHADOW_CONFIRM_PROFILE.event_cancelled
EVENT_SHADOW_CONFIRM_EXPIRED: Final = SHADOW_CONFIRM_PROFILE.event_expired
# Not terminal: a press that was refused (another user, another chat, no confirm context).
EVENT_SHADOW_CONFIRM_REJECTED: Final = SHADOW_CONFIRM_PROFILE.event_rejected
# Not terminal: the best-effort failure notice itself could not be sent.
EVENT_SHADOW_CONFIRM_NOTICE_FAILED: Final = SHADOW_CONFIRM_PROFILE.event_notice_failed

TERMINAL_CONFIRM_EVENTS: Final = SHADOW_CONFIRM_PROFILE.terminal_events

DELIVERY_EDIT: Final = "edit"
DELIVERY_FALLBACK_SEND: Final = "fallback_send"

_NOTICE_SENT: Final = "sent"
_NOTICE_SKIPPED_RATE_LIMITED: Final = "skipped_rate_limited"
_NOTICE_FAILED: Final = "failed"


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


def _correlation(approval_id: str) -> str:
    return SHADOW_CONFIRM_PROFILE.correlation(approval_id)


def _message_id_of(result: object) -> int | None:
    value = getattr(result, "message_id", None)
    return value if isinstance(value, int) else None


# --------------------------------------------------------------------------- #
# The confirm book: the SHADOW profile over the shared core.
# --------------------------------------------------------------------------- #


class ConfirmBook(CoreConfirmBook):
    """The SHADOW confirm book: the core state machine with the SHADOW profile and card."""

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
        super().__init__(
            stores,
            profile=SHADOW_CONFIRM_PROFILE,
            clock=clock,
            card_renderer=self._render_card,
            ttl_seconds=ttl_seconds,
            mark_price=mark_price,
            recheck=recheck,
            on_confirmed=on_confirmed,
            reservations=reservations,
        )
        require_shadow(mode)
        self._mode = mode

    def _render_card(
        self,
        signal: Signal,
        plan: TradePlan,
        mark: Decimal | None,
        now_utc: datetime,
        ttl_seconds: int,
    ) -> str:
        return render_confirm_card(
            signal, plan, mode=self._mode, mark_price=mark, now_utc=now_utc, ttl_seconds=ttl_seconds
        )

    def _new_entry(
        self, fields: Mapping[str, Any], *, mark: Decimal | None, now_utc: datetime
    ) -> ConfirmEntry:
        # The card is assigned only from the one composer (the guard in
        # tests/test_paper_shadow_runtime.py reads this construction site).
        return ConfirmEntry(
            **fields,
            card_text=render_confirm_card(
                fields["signal"],
                fields["plan"],
                mode=self._mode,
                mark_price=mark,
                now_utc=now_utc,
                ttl_seconds=self._ttl,
            ),
        )


def assert_no_stranded_approvals(
    stores: ConfirmStores,
    now_utc: datetime,
    *,
    ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT,
) -> None:
    """Raise `StrandedApprovals` unless every approved plan past the TTL has one terminal event.

    The SHADOW profile of `src.approval.confirm_core.assert_no_stranded_approvals` (T-16-112).
    """
    core_assert_no_stranded_approvals(
        stores, now_utc, profile=SHADOW_CONFIRM_PROFILE, ttl_seconds=ttl_seconds
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
    "REASON_CARD_DELIVERY_FAILED",
    "REASON_CHAT_MISMATCH",
    "REASON_CONFIRM_ALREADY_EXPIRED",
    "REASON_CONFIRM_TTL_ELAPSED",
    "REASON_NO_CONFIRM_CONTEXT",
    "REASON_RECHECK_ERROR",
    "REASON_RUNTIME_RESTART",
    "REASON_USER_ID_UNAVAILABLE",
    "REASON_USER_MISMATCH",
    "SHADOW_CONFIRM_PROFILE",
    "TERMINAL_CONFIRM_EVENTS",
    "CardDelivery",
    "ConfirmBook",
    "ConfirmCallbacks",
    "ConfirmEntry",
    "ConfirmOutcome",
    "ConfirmResult",
    "ConfirmState",
    "ConfirmStores",
    "MarkPriceFn",
    "OnConfirmedFn",
    "RecheckFn",
    "ReservationPort",
    "ReserveOutcome",
    "StrandedApprovals",
    "assert_no_stranded_approvals",
    "deliver_confirm_card",
    "make_confirm_callbacks",
    "render_confirm_card",
]
