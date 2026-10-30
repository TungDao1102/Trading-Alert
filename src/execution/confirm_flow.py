"""The DEMO/LIVE two-step confirm flow: APPROVE shows a card, only CONFIRM reaches placement.

Phase 23, plan 23-12 (D041, D-06, D-09 to D-13; ROADMAP criteria 3 and 4; F-016). The shared core
(`src/approval/confirm_core.py`) holds the state machine; this module is its DEMO/LIVE mode, the
analog of `src/paper/shadow_confirm.py` (read, not imported). It is a library piece that Phase 24
composes into the running process (D-17); it is proven with fakes.

What it does:
  - `approved_handler`: after an APPROVE that reached APPROVED, the request message is edited into
    the confirmation card (one `call_bounded` edit inside the remaining confirm window, one
    fallback send, else the confirm is journaled EXPIRED with CARD_DELIVERY_FAILED). The card shows
    the mode, the size, the STORED money, the current mark price against entry and SL, and the
    remaining validity with the verdict of the placement gate's own rule (`validity_rule`).
  - `confirm_handler`: a CONFIRM first awaits the composition's `prefetch(signal, plan)` (fresh
    exchange readings), then calls the core's synchronous `handle_confirm`, which runs the injected
    `recheck` (plan 23-05) and, for the approving user only and once, the injected `on_confirmed`.
    CANCEL goes to `handle_cancel`. Every refusal is journaled by the core.
  - `reply_fn` / `finalize_message`: truthful answers, and the card made final (CONFIRMED,
    CANCELLED, EXPIRED or REFUSED, keyboard removed in the same edit). A CONFIRMED card shows what
    the stored entry intent says (`needs reconciliation` for UNKNOWN, SENT and INTENDED, never
    `rejected` for an ambiguous result). A decision still open keeps its keyboard. The desk's own
    hooks are the fallback for presses that have no confirm entry.
  - `finalize_expired` / `expire_on_restart`: the TTL sweep edits an expired card once; a restart
    journals RUNTIME_RESTART and edits nothing (the raw tokens are gone).

What it does NOT do: place an order. It imports nothing from `src.execution.manager` or a Binance
adapter, and `on_confirmed` is a required injected callable, the single seam that Phase 24 connects
to the placement step. `LIVE_ORDERS_DISABLED` is not touched. A placement is never re-sent
(Q5, D080): nothing here retries anything but Telegram messages.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from src.adapters.telegram_callbacks import (
    CallbackKind,
    CallbackPress,
    ConfirmReply,
    DispatchResult,
    JournalReceipt,
    current_press_correlation,
)
from src.adapters.telegram_notify import (
    TelegramFailure,
    TelegramFailureKind,
    TelegramTextBot,
    build_confirm_keyboard,
    call_bounded,
    edit_text,
    finalize_decided_message,
    format_live_confirm_card,
    format_live_confirm_final,
    format_presentation_time,
    send_text_bounded,
)
from src.approval.confirm_core import (
    CONFIRM_TTL_SECONDS_DEFAULT,
    DEMO_CONFIRM_PROFILE,
    LIVE_CONFIRM_PROFILE,
    REASON_CARD_DELIVERY_FAILED,
    REASON_CONFIRM_TTL_ELAPSED,
    REASON_RUNTIME_RESTART,
    REASON_USER_ID_UNAVAILABLE,
    ConfirmEntry,
    ConfirmOutcome,
    ConfirmProfile,
    ConfirmResult,
    ConfirmState,
    ConfirmStores,
    MarkPriceFn,
    OnConfirmedFn,
    RecheckFn,
)
from src.approval.confirm_core import ConfirmBook as CoreConfirmBook
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.approval_desk import ApprovalDesk
from src.execution.prior_outcome import PRIOR_OUTCOME_LABEL, PriorOutcome, describe_prior_outcome
from src.ops.alert_wording import reconciliation_required_text
from src.risk.money_at_stake import MoneyAtStake, MoneyAtStakeUnavailable

log = structlog.get_logger()

DELIVERY_EDIT: Final = "edit"
DELIVERY_FALLBACK_SEND: Final = "fallback_send"

# The validity rule itself raised: the card shows the check as refused with this code (fail closed).
VALIDITY_RULE_ERROR: Final = "VALIDITY_RULE_ERROR"

_NOTICE_SENT: Final = "sent"
_NOTICE_SKIPPED_RATE_LIMITED: Final = "skipped_rate_limited"

# Reasons under which an entry ended without any refusal of the operator's press: a final text
# says EXPIRED. Every other terminal reason (a recheck code, APPROVAL_EXPIRED, ...) says REFUSED.
_EXPIRY_REASONS: Final = frozenset(
    {
        REASON_CONFIRM_TTL_ELAPSED,
        REASON_RUNTIME_RESTART,
        REASON_CARD_DELIVERY_FAILED,
        REASON_USER_ID_UNAVAILABLE,
    }
)

# How many reply texts wait for the reply function of their press (a bound, not a tuning knob).
_REPLIES_CAP: Final = 64
# `reply_fn` passes the adapter's own text through for a press whose handler raised.
_PASS_THROUGH: Final = object()

PLACEMENT_NOT_RECORDED: Final = "Placement: handed to the execution step; no entry recorded yet"
# Review WR-08: the hook raised, so "handed over" is not known. Said plainly, with the
# reconciliation words, instead of PLACEMENT_NOT_RECORDED.
PLACEMENT_HAND_OFF_FAILED: Final = (
    "Placement: HAND-OFF FAILED; it is not known that anything was sent. Check the journal."
)


class ValidityRule(Protocol):
    """The placement gate's remaining-validity rule with the owner's limits already bound.

    Phase 24 binds it with `functools.partial(check_remaining_validity,
    min_remaining_validity_seconds=..., gtd_clock_margin=...)`; it returns a refusal code or None.
    """

    def __call__(self, *, expiry_utc: datetime, now_utc: datetime) -> str | None: ...


PrefetchFn = Callable[[Signal, TradePlan], Awaitable[None]]
SleepFn = Callable[[float], Awaitable[None]]


def _message_id_of(result: object) -> int | None:
    value = getattr(result, "message_id", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class ConfirmFlow:
    """One DEMO or LIVE confirm flow over a desk. Build it with `make_confirm_flow`."""

    def __init__(
        self,
        *,
        desk: ApprovalDesk,
        profile: ConfirmProfile,
        stores: ConfirmStores,
        clock: Callable[[], datetime],
        bot: TelegramTextBot,
        sleep: SleepFn,
        mark_price: MarkPriceFn | None,
        validity_rule: ValidityRule,
        recheck: RecheckFn,
        on_confirmed: OnConfirmedFn,
        prefetch: PrefetchFn | None,
        ttl_seconds: int,
    ) -> None:
        if profile is not DEMO_CONFIRM_PROFILE and profile is not LIVE_CONFIRM_PROFILE:
            raise ValueError("the confirm flow serves DEMO_CONFIRM_PROFILE or LIVE_CONFIRM_PROFILE")
        if profile is not desk.profile:
            raise ValueError("the confirm flow and its approval desk must share one profile")
        if on_confirmed is None:  # a required seam: no default, no silent no-op
            raise ValueError("on_confirmed is required")
        self._desk = desk
        self._profile = profile
        self._mode = profile.mode_label
        self._stores = stores
        self._clock = clock
        self._bot = bot
        self._sleep = sleep
        self._validity_rule = validity_rule
        self._prefetch = prefetch
        self._book = CoreConfirmBook(
            stores,
            profile=profile,
            clock=clock,
            card_renderer=self._render_card,
            ttl_seconds=ttl_seconds,
            mark_price=mark_price,
            recheck=recheck,
            on_confirmed=on_confirmed,
        )
        self._desk_reply = desk.reply_fn(bot, sleep=sleep)
        self._desk_finalize = desk.finalize_hook(bot, sleep=sleep)
        self._replies: dict[str, object] = {}
        self._finalized: dict[str, tuple[int, str]] = {}
        self._notified: dict[str, str] = {}
        self._short_by_approval: dict[str, str] = {}
        self._chat_by_short: dict[str, int | str] = {}
        # From now on a fresh APPROVE is answered "Nothing was placed." (wording only).
        desk.confirmation_attached = True

    # ---- read side --------------------------------------------------------------------- #

    @property
    def book(self) -> CoreConfirmBook:
        """The core confirm book (read it; the flow drives it)."""
        return self._book

    # ---- the card ---------------------------------------------------------------------- #

    def _validity_verdict(self, plan: TradePlan, now_utc: datetime) -> str | None:
        try:
            return self._validity_rule(expiry_utc=plan.expiry_utc, now_utc=now_utc)
        except Exception as exc:  # noqa: BLE001 - fail closed: a broken rule shows as refused
            log.warning(
                f"{self._profile.log_namespace}.validity_rule_failed",
                error_class=type(exc).__name__,
            )
            return VALIDITY_RULE_ERROR

    def _render_card(
        self,
        signal: Signal,
        plan: TradePlan,
        mark: Decimal | None,
        now_utc: datetime,
        ttl_seconds: int,
    ) -> str:
        money = self._desk.checked_money_for(signal, plan)
        if money is None:
            raise MoneyAtStakeUnavailable("money", "no stored money for the card")
        return format_live_confirm_card(
            mode_label=self._mode,
            symbol=signal.symbol,
            side=signal.direction,
            money=money,
            mark_price=mark,
            plan_expiry_utc=plan.expiry_utc,
            validity_verdict=self._validity_verdict(plan, now_utc),
            now_utc=now_utc,
            ttl_seconds=ttl_seconds,
        )

    # ---- APPROVE -> card --------------------------------------------------------------- #

    async def approved_handler(self, press: CallbackPress, result: DispatchResult) -> bool:
        """After an APPROVE that reached APPROVED: edit the request into the card. True if handled.

        False leaves the answer to the desk (no confirm context, no stored money, or a repeated
        APPROVE of a confirm that is no longer open): the approval stays recorded and nothing can
        be placed without a CONFIRM.
        """
        try:
            return await self._approved(press, result)
        except Exception:
            self._mark_pass_through(press.correlation_id)
            raise

    async def _approved(self, press: CallbackPress, result: DispatchResult) -> bool:
        short_id = press.parsed.short_id
        now = press.callback_at_utc
        existing = self._book.get(short_id)
        if existing is not None:
            # A repeated APPROVE: replay to the existing confirm, never a second token.
            self._book.expire_if_due(short_id, now)
            if existing.state is not ConfirmState.PENDING or not existing.delivered:
                return False
            if press.message_id is not None and press.message_id == existing.message_id:
                await self._deliver_card(existing, press, replay=True)
            return True
        context = self._desk.plan_context(short_id)
        if context is None or result.approval is None:
            return False
        if self._desk.money_for(short_id) is None:
            log.error(f"{self._profile.log_namespace}.no_stored_money")
            return False
        signal, plan = context
        # Review WR-02: the confirm is bound to the user that pressed APPROVE, i.e. the stored
        # `actor_id`. A replayed APPROVE by another allow-listed user (after a failed first
        # handler) never becomes the approving user, so it creates no confirm.
        if press.from_user_id is None or result.approval.actor_id != str(press.from_user_id):
            log.warning(f"{self._profile.log_namespace}.confirm_not_bound_to_stored_actor")
            return False
        # The approval is stamped by the desk's own, later clock read, so its `acted_at_utc` can sit
        # a few microseconds after the press time. A card is never stamped before the approval it
        # follows, and the TTL, the expiry and the journaled request instant follow this one stamp.
        acted_at = result.approval.acted_at_utc
        entry = self._book.issue(
            short_id=short_id,
            approval=result.approval,
            signal=signal,
            plan=plan,
            approving_user_id=press.from_user_id,
            now_utc=now if acted_at is None else max(now, acted_at),
        )
        self._short_by_approval[entry.approval.approval_id] = short_id
        self._chat_by_short[short_id] = press.chat_id
        if entry.state is not ConfirmState.PENDING:
            return False
        await self._deliver_card(entry, press, replay=False)
        return True

    async def _deliver_card(
        self, entry: ConfirmEntry, press: CallbackPress, *, replay: bool
    ) -> None:
        """Edit the request into the card; on failure one fallback send; else expire the confirm."""
        keyboard = build_confirm_keyboard(entry.signal.signal_id)
        chat_id = press.chat_id
        message_id = press.message_id

        def window() -> float:
            left = timedelta(seconds=entry.ttl_seconds) - (self._clock() - entry.issued_at_utc)
            return max(0.0, left.total_seconds())

        attempts = 0
        edit_failure: TelegramFailure | None = None
        if message_id is not None:
            edited = await call_bounded(
                lambda: edit_text(self._bot, chat_id, message_id, entry.card_text, keyboard),
                sleep=self._sleep,
                window_seconds=window(),
            )
            attempts += edited.attempts
            edit_failure = edited.failure
            if edit_failure is None:
                if not replay:
                    self._book.record_issued(
                        entry,
                        delivery=DELIVERY_EDIT,
                        message_id=message_id,
                        attempts=attempts,
                        edit_failure=None,
                        now_utc=self._clock(),
                    )
                return
        if replay:
            log.warning(
                f"{self._profile.log_namespace}.replay_edit_failed",
                kind=None if edit_failure is None else edit_failure.kind.value,
            )
            return
        throttled = (
            edit_failure is not None and edit_failure.kind is TelegramFailureKind.RATE_LIMITED
        )
        last_failure = edit_failure
        if not throttled:
            sent = await send_text_bounded(
                self._bot,
                chat_id,
                entry.card_text,
                keyboard,
                sleep=self._sleep,
                window_seconds=window(),
            )
            attempts += sent.attempts
            if sent.failure is None:
                self._book.record_issued(
                    entry,
                    delivery=DELIVERY_FALLBACK_SEND,
                    message_id=_message_id_of(sent.result),
                    attempts=attempts,
                    edit_failure=edit_failure,
                    now_utc=self._clock(),
                )
                return
            last_failure = sent.failure
        failure = last_failure or TelegramFailure(TelegramFailureKind.UNKNOWN, None, "NoMessageId")
        notice = _NOTICE_SKIPPED_RATE_LIMITED if throttled else _NOTICE_SENT
        self._book.abort_delivery(
            entry, failure=failure, notice=notice, attempts=attempts, now_utc=self._clock()
        )
        if throttled:
            return
        notice_text = (
            f"Mode: {self._mode}\n"
            f"The confirmation card for {entry.signal.symbol} {entry.signal.direction} could not "
            f"be delivered ({failure.kind.value}). Nothing was placed. The plan expires at "
            f"{format_presentation_time(entry.plan.expiry_utc)}."
        )
        outcome = await send_text_bounded(self._bot, chat_id, notice_text, sleep=self._sleep)
        if outcome.failure is not None:
            self._book.record_notice_failed(entry, outcome.failure, self._clock())

    # ---- CONFIRM / CANCEL -------------------------------------------------------------- #

    async def confirm_handler(self, press: CallbackPress) -> ConfirmReply:
        """A CNF: or CXL: press, after the chat and user gates. Journals; places nothing itself."""
        try:
            return await self._confirm(press)
        except Exception:
            self._mark_pass_through(press.correlation_id)
            raise

    async def _confirm(self, press: CallbackPress) -> ConfirmReply:
        kind = press.parsed.kind
        short_id = press.parsed.short_id
        if kind is CallbackKind.CONFIRM:
            await self._prefetch_for(press)
            # Review WR-11: the TTL, the plan expiry and the re-check are judged at the instant
            # the decision is taken, i.e. after the awaited exchange round trip, never earlier
            # than the press itself.
            decided_at = max(press.callback_at_utc, self._clock())
            result = self._book.handle_confirm(
                short_id=short_id,
                chat_id=press.chat_id,
                authorized_chat_id=press.authorized_chat_id,
                from_user_id=press.from_user_id,
                now_utc=decided_at,
                correlation_id=press.correlation_id,
            )
            ok = result.outcome is ConfirmOutcome.CONFIRMED
        elif kind is CallbackKind.CANCEL:
            result = self._book.handle_cancel(
                short_id=short_id,
                chat_id=press.chat_id,
                authorized_chat_id=press.authorized_chat_id,
                from_user_id=press.from_user_id,
                now_utc=press.callback_at_utc,
                correlation_id=press.correlation_id,
            )
            ok = result.outcome is ConfirmOutcome.CANCELLED
        else:
            raise ValueError(f"not a confirm press: {kind!r}")
        text = self._reply_text(result)
        self._store_reply(press.correlation_id, text)
        return ConfirmReply(ok=ok, text=text)

    async def _prefetch_for(self, press: CallbackPress) -> None:
        """Await the composition's fresh readings, only for a CONFIRM that could still succeed.

        Not for a press of another user or chat, after the confirm window or after the plan
        expiry: those are refused before the recheck and need no exchange data.

        A prefetch error is logged by class name; the CONFIRM then refuses through the recheck
        (CONFIRM_INPUTS_UNAVAILABLE), it is never waved through.
        """
        if self._prefetch is None:
            return
        entry = self._book.get(press.parsed.short_id)
        if (
            entry is None
            or entry.state is not ConfirmState.PENDING
            or press.chat_id != press.authorized_chat_id
            or press.from_user_id != entry.approving_user_id
            or press.callback_at_utc >= entry.expires_at_utc
            or press.callback_at_utc >= entry.plan.expiry_utc
        ):
            return
        try:
            await self._prefetch(entry.signal, entry.plan)
        except Exception as exc:  # noqa: BLE001 - the recheck refuses without inputs
            log.warning(
                f"{self._profile.log_namespace}.prefetch_failed", error_class=type(exc).__name__
            )

    def _reply_text(self, result: ConfirmResult) -> str:
        """The answer to a CONFIRM or CANCEL press; empty when the final card says it all."""
        outcome = result.outcome
        if outcome is ConfirmOutcome.CONFIRMED:
            body = "Already confirmed. Nothing changed." if result.replayed else ""
        elif outcome is ConfirmOutcome.CANCELLED:
            body = "Already cancelled. Nothing changed." if result.replayed else ""
        elif outcome is ConfirmOutcome.REJECTED_USER_MISMATCH:
            body = (
                f"Refused: {result.reason}. Only the user who pressed APPROVE can confirm. "
                "Nothing changed."
            )
        elif outcome is ConfirmOutcome.EXPIRED_TTL:
            body = f"Refused: {result.reason}. The confirm window ran out. Nothing was placed."
        elif outcome is ConfirmOutcome.REJECTED_PLAN_EXPIRED:
            body = f"Refused: {result.reason}. The plan has expired. Nothing was placed."
        else:
            body = f"Refused: {result.reason}. Nothing was placed."
        return f"Mode: {self._mode}\n{body}" if body else ""

    def _store_reply(self, correlation_id: str, value: object) -> None:
        self._replies[correlation_id] = value
        while len(self._replies) > _REPLIES_CAP:
            del self._replies[next(iter(self._replies))]

    def _mark_pass_through(self, correlation_id: str) -> None:
        self._store_reply(correlation_id, _PASS_THROUGH)

    # ---- reply ------------------------------------------------------------------------- #

    async def reply_fn(self, chat_id: int, text: str) -> None:
        """The `reply_text_fn` for `on_callback`.

        A confirm press is answered from its own stored text (empty: nothing is sent, the final
        card says it). A press whose handler raised passes the adapter's neutral text through. Any
        other press is answered by the desk from its record.
        """
        correlation = current_press_correlation() or ""
        if correlation in self._replies:
            stored = self._replies.pop(correlation)
            if stored is _PASS_THROUGH:
                message = f"Mode: {self._mode}\n{text}"
            else:
                message = str(stored)
            if message == "":
                return
            outcome = await send_text_bounded(self._bot, chat_id, message, sleep=self._sleep)
            if outcome.failure is not None:
                log.warning(
                    f"{self._profile.log_namespace}.reply_failed",
                    kind=outcome.failure.kind.value,
                    detail=outcome.failure.detail,
                )
            return
        await self._desk_reply(chat_id, text)

    # ---- final text -------------------------------------------------------------------- #

    def _placement_lines(
        self, approval_id: str, *, hand_off_failed: bool = False
    ) -> tuple[str, ...]:
        """What the stored entry intent says; ambiguous or unreadable reads as reconciliation.

        Without a stored intent the text depends on the hand-off: "handed to the execution step"
        only when the hook did not raise (review WR-08), else the failure and the reconciliation
        words.
        """
        try:
            prior = describe_prior_outcome(self._desk.intent_reader(approval_id))
        except Exception as exc:  # noqa: BLE001 - an unreadable intent is never "rejected"
            log.error(
                f"{self._profile.log_namespace}.intent_read_failed", error_class=type(exc).__name__
            )
            prior = PriorOutcome.NEEDS_RECONCILIATION
        if prior is None:
            if hand_off_failed:
                return (PLACEMENT_HAND_OFF_FAILED, reconciliation_required_text())
            return (PLACEMENT_NOT_RECORDED,)
        lines = (f"Placement: {PRIOR_OUTCOME_LABEL[prior]}",)
        if prior is PriorOutcome.NEEDS_RECONCILIATION:
            return (*lines, reconciliation_required_text())
        return lines

    def _final_text(self, entry: ConfirmEntry) -> str | None:
        """The final text of a decided card from the STORED state, or None without stored money."""
        if entry.state is ConfirmState.PENDING:
            return None
        try:
            money: MoneyAtStake | None = self._desk.checked_money_for(entry.signal, entry.plan)
        except ValueError as exc:
            # A stored block that disagrees with the plan is never shown (review WR-04).
            log.error(
                f"{self._profile.log_namespace}.stored_money_inconsistent",
                error_class=type(exc).__name__,
            )
            return None
        if money is None:
            return None
        common: dict[str, Any] = {
            "mode_label": self._mode,
            "symbol": entry.signal.symbol,
            "side": entry.signal.direction,
            "money": money,
            "at_utc": entry.decided_at_utc or self._clock(),
        }
        if entry.state is ConfirmState.CONFIRMED:
            return format_live_confirm_final(
                **common,
                outcome="CONFIRMED",
                user_id=entry.approving_user_id,
                placement_lines=self._placement_lines(
                    entry.approval.approval_id, hand_off_failed=entry.hand_off_failed
                ),
            )
        if entry.state is ConfirmState.CANCELLED:
            return format_live_confirm_final(
                **common, outcome="CANCELLED", user_id=entry.approving_user_id
            )
        expired = entry.outcome is ConfirmOutcome.EXPIRED_TTL or entry.reason in _EXPIRY_REASONS
        return format_live_confirm_final(
            **common, outcome="EXPIRED" if expired else "REFUSED", reason=entry.reason
        )

    # ---- finalize ---------------------------------------------------------------------- #

    async def finalize_message(self, press: CallbackPress, result: DispatchResult) -> None:
        """After the reply of a press that passed both gates: make the card final when it is.

        CONFIRM and CANCEL: a decided confirm becomes its final text with the keyboard removed in
        the same edit; a confirm still PENDING (another user's CONFIRM, which refuses without
        ending it) keeps its keyboard. APPROVE and SKIP: when a confirm exists the desk's record is
        consumed here and the card is the open decision (or already final); otherwise the desk's
        own hook answers. The same final text is not edited twice.
        """
        kind = press.parsed.kind
        short_id = press.parsed.short_id
        entry = self._book.get(short_id)
        is_confirm_press = kind in (CallbackKind.CONFIRM, CallbackKind.CANCEL)
        if not is_confirm_press:
            if entry is None:
                await self._desk_finalize(press, result)
                return
            self._desk.take_decision(press.correlation_id)
        if press.message_id is None:
            return  # an inaccessible message: nothing to edit
        if entry is None:
            # No confirm context (a restart lost the token): the buttons are dead, drop them.
            await self._remove_keyboard(None, short_id, press, trigger=kind.value)
            return
        if entry.state is ConfirmState.PENDING:
            if (
                not is_confirm_press
                and entry.message_id is not None
                and press.message_id != entry.message_id
            ):
                # The card was sent as a new message: the old request message loses its buttons.
                await self._remove_keyboard(entry, short_id, press, trigger=kind.value)
            return  # a decision is still open on the card: it keeps its keyboard
        final_done = await self._edit_final(
            entry, press.chat_id, press.message_id, trigger=kind.value
        )
        if not final_done and is_confirm_press:
            await self._send_final_message(entry)

    async def _remove_keyboard(
        self, entry: ConfirmEntry | None, short_id: str, press: CallbackPress, *, trigger: str
    ) -> None:
        """A keyboard-only edit of the pressed message; a failure is journaled, never raised."""
        message_id = press.message_id
        if message_id is None:
            return
        outcome = await finalize_decided_message(
            self._bot, chat_id=press.chat_id, message_id=message_id, text=None, sleep=self._sleep
        )
        if outcome.done:
            return
        log.warning(
            f"{self._profile.log_namespace}.keyboard_removal_failed",
            trigger=trigger,
            kind=None if outcome.failure is None else outcome.failure.kind.value,
        )
        self._journal_edit_failed(
            entry,
            short_id=short_id,
            message_id=message_id,
            trigger=trigger,
            failure=outcome.failure,
            attempts=outcome.attempts,
            correlation_id=press.correlation_id,
        )

    async def _send_final_message(self, entry: ConfirmEntry) -> None:
        """The final edit failed after a CONFIRM or CANCEL: say the outcome once as a message."""
        text = self._final_text(entry)
        chat_id = self._chat_by_short.get(entry.short_id)
        if text is None or chat_id is None or self._notified.get(entry.short_id) == text:
            return
        outcome = await send_text_bounded(self._bot, chat_id, text, sleep=self._sleep)
        if outcome.failure is None:
            self._notified[entry.short_id] = text
        else:
            log.warning(
                f"{self._profile.log_namespace}.final_message_failed",
                kind=outcome.failure.kind.value,
                detail=outcome.failure.detail,
            )

    async def _edit_final(
        self, entry: ConfirmEntry, chat_id: int | str, message_id: int | None, *, trigger: str
    ) -> bool:
        """Edit `message_id` to the final text of a decided entry, once. True when it is final."""
        if message_id is None:
            return False
        text = self._final_text(entry)
        if text is not None and self._finalized.get(entry.short_id) == (message_id, text):
            return True
        outcome = await finalize_decided_message(
            self._bot, chat_id=chat_id, message_id=message_id, text=text, sleep=self._sleep
        )
        if outcome.done:
            if text is not None:
                self._finalized[entry.short_id] = (message_id, text)
            return True
        log.warning(
            f"{self._profile.log_namespace}.final_edit_failed",
            trigger=trigger,
            kind=None if outcome.failure is None else outcome.failure.kind.value,
        )
        self._journal_edit_failed(
            entry,
            short_id=entry.short_id,
            message_id=message_id,
            trigger=trigger,
            failure=outcome.failure,
            attempts=outcome.attempts,
            correlation_id=None,
        )
        return False

    def _journal_edit_failed(
        self,
        entry: ConfirmEntry | None,
        *,
        short_id: str,
        message_id: int,
        trigger: str,
        failure: TelegramFailure | None,
        attempts: int,
        correlation_id: str | None,
    ) -> None:
        """Journal one failed final edit (classified kind only); it never changes the decision.

        Without a confirm entry (a restart lost it) the row hangs on the short id, like the core's
        NO_CONFIRM_CONTEXT row.
        """
        event_type = f"{self._mode}_CONFIRM_MESSAGE_EDIT_FAILED"
        step_key = correlation_id or self._clock().isoformat()
        if entry is not None:
            entity_type = self._profile.entity_type
            entity_id = entry.approval.approval_id
            correlation = self._profile.correlation(entity_id)
        else:
            entity_type = "Approval"
            entity_id = f"short:{short_id}"
            correlation = f"{self._profile.correlation_prefix}short:{short_id}"
        payload: Mapping[str, Any] = {
            "short_id": short_id,
            "message_id": message_id,
            "trigger": trigger,
            "attempts": attempts,
            "kind": None if failure is None else failure.kind.value,
            "error_class": None if failure is None else failure.detail,
            "mode": self._mode,
        }
        try:
            self._stores.record_journal(
                JournalEvent(
                    journal_event_id=correlated_event_id(
                        prefix=f"{self._mode.lower()}-cnf-edit",
                        correlation_id=correlation,
                        event_type=event_type,
                        entity_id=entity_id,
                        step=f"{trigger}:{message_id}:{step_key}",
                    ),
                    occurred_at_utc=self._clock(),
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    correlation_id=correlation,
                    signal_id=None if entry is None else entry.signal.signal_id,
                    trade_plan_id=None if entry is None else entry.plan.trade_plan_id,
                    approval_id=None if entry is None else entry.approval.approval_id,
                    payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                )
            )
        except Exception as exc:  # noqa: BLE001 - the decision stands; the journal gap is logged
            log.error(
                f"{self._profile.log_namespace}.edit_failure_journal_failed",
                error_class=type(exc).__name__,
            )

    # ---- sweeps ------------------------------------------------------------------------ #

    async def finalize_expired(self, now_utc: datetime) -> list[str]:
        """Expire every confirm past its TTL and edit each delivered card to its final text, once.

        The core journals EXPIRED (CONFIRM_TTL_ELAPSED) and repairs stranded approvals; a card
        that was delivered and is now EXPIRED becomes its final text with the keyboard removed. A
        second call expires and edits nothing. Returns the short ids whose card was edited.
        """
        finalized: list[str] = []
        for approval_id in self._book.expire_due(now_utc):
            short_id = self._short_by_approval.get(approval_id)
            entry = None if short_id is None else self._book.get(short_id)
            if (
                entry is None
                or entry.state is not ConfirmState.EXPIRED
                or not entry.delivered
                or entry.message_id is None
            ):
                continue
            chat_id = self._chat_by_short.get(entry.short_id)
            if chat_id is None:
                continue
            if await self._edit_final(entry, chat_id, entry.message_id, trigger="ttl_sweep"):
                finalized.append(entry.short_id)
        return finalized

    def expire_on_restart(self, now_utc: datetime) -> list[str]:
        """Journal RUNTIME_RESTART for every outstanding confirm of the previous process.

        Call once at startup with a fresh flow. Nothing is edited: the old process' message ids are
        gone, and a later tap on an old card is refused (NO_CONFIRM_CONTEXT) and loses its buttons.
        Returns the approval ids that were expired; a second call returns none.
        """
        return self._book.expire_on_restart(now_utc)

    # ---- callbacks --------------------------------------------------------------------- #

    def callback_kwargs(
        self,
        *,
        authorized_chat_id: int,
        authorized_user_ids: frozenset[int],
        error_journal: JournalReceipt | None = None,
    ) -> dict[str, Any]:
        """The full keyword set of `on_callback` / `build_application` for this flow."""
        return {
            "authorized_chat_id": authorized_chat_id,
            "authorized_user_ids": authorized_user_ids,
            "binding_context_resolver": self._desk.resolve,
            "dispatch": self._desk.dispatch,
            "reply_text_fn": self.reply_fn,
            "confirm_handler": self.confirm_handler,
            "approved_handler": self.approved_handler,
            "finalize_message": self.finalize_message,
            "error_journal": error_journal,
            "clock": self._clock,
        }


def make_confirm_flow(
    *,
    desk: ApprovalDesk,
    profile: ConfirmProfile,
    stores: ConfirmStores,
    clock: Callable[[], datetime],
    bot: TelegramTextBot,
    sleep: SleepFn = asyncio.sleep,
    mark_price: MarkPriceFn | None,
    validity_rule: ValidityRule,
    recheck: RecheckFn,
    on_confirmed: OnConfirmedFn,
    prefetch: PrefetchFn | None = None,
    ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT,
) -> ConfirmFlow:
    """Build the DEMO or LIVE confirm flow over `desk` (which must share `profile`).

    `on_confirmed(approval, plan, confirmed_at_utc)` is the only seam to placement: required, no
    default. `recheck` is the synchronous callable of `make_confirm_recheck`; `prefetch(signal,
    plan)` is awaited before every CONFIRM that could succeed and must put fresh readings where the
    recheck reads them. `validity_rule` gives the card's placement-check verdict.
    """
    return ConfirmFlow(
        desk=desk,
        profile=profile,
        stores=stores,
        clock=clock,
        bot=bot,
        sleep=sleep,
        mark_price=mark_price,
        validity_rule=validity_rule,
        recheck=recheck,
        on_confirmed=on_confirmed,
        prefetch=prefetch,
        ttl_seconds=ttl_seconds,
    )


__all__ = [
    "DELIVERY_EDIT",
    "DELIVERY_FALLBACK_SEND",
    "PLACEMENT_HAND_OFF_FAILED",
    "PLACEMENT_NOT_RECORDED",
    "VALIDITY_RULE_ERROR",
    "ConfirmFlow",
    "PrefetchFn",
    "ValidityRule",
    "make_confirm_flow",
]
