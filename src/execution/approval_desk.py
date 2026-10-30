"""The DEMO/LIVE approval desk: one request message, SKIP recorded, decided messages final.

Phase 23, plan 23-11 (D-03, D-05, D-06, D-07, D-12, D-13; G4-032). The desk is the library piece
that Phase 24 composes into the running process ("approval request sender", "Telegram bot
runner"). It is proven with fakes (D-17) and sits in `src/execution/` so it never enters the
SHADOW import closure. It is the DEMO/LIVE analog of `ShadowApprovalBook` plus `send_shadow_alert`
(read, not imported).

What it does:
  - `issue`: builds the request text from the plan and the STORED money block
    (`format_approval_request`), refuses before any write when the money is missing or disagrees,
    then writes the parents first (signal, plan), the two PENDING approvals (APPROVE and
    SKIP_USER, both with `approved_quantity` and the same `money_json`), the short-id mapping and
    the ISSUED journal row.
  - `send`: ONE message with APPROVE and SKIP (`build_decision_keyboard`) through
    `send_text_bounded`. A send failure is journaled with its classified kind and approves
    nothing: both approvals stay PENDING (APRV-02, T-23-32).
  - `resolve` / `dispatch`: the `binding_context_resolver` and `dispatch` of `on_callback`. A
    press is dispatched with the token of the button, and the desk keeps a record of what the
    press amounted to (`DeskDecisionRecord`) for the reply and the final edit.
  - `reply_fn` / `finalize_hook`: truthful answers for every tap, and the request message made
    final (decision, actor and time, keyboard removed in the same edit). A redelivered APPROVE
    after the plan expired is answered from the stored entry intent (G4-032).
  - `finalize_expired_requests`: an untapped request whose plan expired becomes a final EXPIRED
    message. It writes no approval row (the expiry policy of the rows is Phase 24's, O-2).

What it does NOT do: place or cancel an order. It imports nothing from `src.execution.manager`
or the Binance adapter, and it has no `on_confirmed` seam: the two-step confirm for DEMO/LIVE is
plan 23-12. Until a confirmation handler is attached, a fresh APPROVE is recorded and the answer
says that nothing can be confirmed or placed (fail closed).

Raw one-time tokens, the request text and the message id live in memory only (D-04): a restart
loses them, which makes the old buttons dead (the stored state refuses them).
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Final, Protocol

import structlog

from src.adapters.telegram_callbacks import (
    CallbackKind,
    CallbackPress,
    DispatchResult,
    FinalizeHook,
    ParsedCallback,
    current_press_correlation,
)
from src.adapters.telegram_callbacks import dispatch_callback as _dispatch_callback
from src.adapters.telegram_notify import (
    TelegramFailure,
    TelegramTextBot,
    build_decision_keyboard,
    finalize_decided_message,
    format_approval_request,
    format_presentation_time,
    send_text_bounded,
)
from src.approval.confirm_core import (
    DEMO_CONFIRM_PROFILE,
    LIVE_CONFIRM_PROFILE,
    ConfirmProfile,
)
from src.approval.mapping import ShortIdMapping, make_short_id_mapping
from src.approval.reason_codes import (
    ALREADY_DECIDED,
    APPROVAL_STORE_FAILURE,
    CALLBACK_HANDLER_ERROR,
    CHAT_NOT_PRIVATE,
    USER_ID_UNAVAILABLE,
    USER_NOT_AUTHORIZED,
)
from src.approval.tokens import issue_one_time_token, token_hash_of
from src.domain.approval import Approval
from src.domain.canonical import sha256_hex
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.intent_store import IntentRecord
from src.execution.prior_outcome import (
    PRIOR_OUTCOME_LABEL,
    PriorOutcome,
    prior_outcome_for_expired_redelivery,
)
from src.ops.alert_wording import reconciliation_required_text
from src.risk.money_at_stake import (
    MoneyAtStake,
    MoneyAtStakeUnavailable,
    money_canonical_json,
    parse_money_json,
)

log = structlog.get_logger()

# --------------------------------------------------------------------------- #
# Journal event names: <MODE>_APPROVAL_REQUEST_* (MODE = DEMO or LIVE).
# --------------------------------------------------------------------------- #

EVENT_DEMO_APPROVAL_REQUEST_ISSUED: Final = "DEMO_APPROVAL_REQUEST_ISSUED"
EVENT_DEMO_APPROVAL_REQUEST_SENT: Final = "DEMO_APPROVAL_REQUEST_SENT"
EVENT_DEMO_APPROVAL_REQUEST_SEND_FAILED: Final = "DEMO_APPROVAL_REQUEST_SEND_FAILED"
EVENT_DEMO_DECIDED_MESSAGE_EDIT_FAILED: Final = "DEMO_DECIDED_MESSAGE_EDIT_FAILED"
EVENT_LIVE_APPROVAL_REQUEST_ISSUED: Final = "LIVE_APPROVAL_REQUEST_ISSUED"
EVENT_LIVE_APPROVAL_REQUEST_SENT: Final = "LIVE_APPROVAL_REQUEST_SENT"
EVENT_LIVE_APPROVAL_REQUEST_SEND_FAILED: Final = "LIVE_APPROVAL_REQUEST_SEND_FAILED"
EVENT_LIVE_DECIDED_MESSAGE_EDIT_FAILED: Final = "LIVE_DECIDED_MESSAGE_EDIT_FAILED"

_SUFFIX_ISSUED: Final = "APPROVAL_REQUEST_ISSUED"
_SUFFIX_SENT: Final = "APPROVAL_REQUEST_SENT"
_SUFFIX_SEND_FAILED: Final = "APPROVAL_REQUEST_SEND_FAILED"
_SUFFIX_EDIT_FAILED: Final = "DECIDED_MESSAGE_EDIT_FAILED"

_SKIP_TOKEN_KEY: Final = "skip_raw_token"
_RECORDS_CAP: Final = 256

# Refusals a second tap can still cure: the keyboard stays (the decision may yet be taken).
_TRANSIENT_REASONS: Final = frozenset({APPROVAL_STORE_FAILURE, CALLBACK_HANDLER_ERROR})
# The user/chat gate codes of plan 23-01: nothing of the operator's message is touched.
_GATE_REASONS: Final = frozenset({CHAT_NOT_PRIVATE, USER_ID_UNAVAILABLE, USER_NOT_AUTHORIZED})

NO_HANDLER_REPLY: Final = (
    "APPROVED is recorded; no confirmation card handler is attached, so nothing can be "
    "confirmed or placed."
)
_ATTACHED_REPLY: Final = "APPROVED is recorded. Nothing was placed."
_NO_HANDLER_NOTE: Final = (
    "No confirmation card handler is attached, so nothing can be confirmed or placed."
)
_ATTACHED_NOTE: Final = "Nothing was placed."


class DeskStores(Protocol):
    """What the desk needs from persistence (`InMemoryShadowStores` and the PG stores satisfy it).

    Parent rows go first: the signal, then the plan, then the approvals, the mapping and the
    journal rows.
    """

    def insert_signal(self, signal: Signal) -> None: ...
    def insert_trade_plan(self, plan: TradePlan) -> None: ...
    def insert_pending(self, approval: Approval) -> None: ...
    def record_short_id_mapping(self, mapping: ShortIdMapping) -> None: ...
    def save_atomic(self, approval: Approval, mapping: ShortIdMapping | None) -> None: ...
    def lookup_by_token_hash(self, token_hash: str) -> Approval | None: ...
    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None: ...
    def record_journal(self, event: JournalEvent) -> None: ...


SleepFn = Callable[[float], Awaitable[None]]
IntentReader = Callable[[str], IntentRecord | None]


@dataclass(frozen=True)
class IssuedRequest:
    """The rows `ApprovalDesk.issue` wrote and the text to send. Raw tokens are NOT here."""

    approve: Approval
    skip: Approval
    mapping: ShortIdMapping
    text: str


@dataclass(frozen=True)
class RequestSendOutcome:
    """What `ApprovalDesk.send` did. It never raises on a send failure and never approves."""

    sent: bool
    message_id: int | None
    attempts: int
    failure: TelegramFailure | None = None


class DeskOutcome(str, Enum):
    """What one press amounted to, from the stored state."""

    APPROVED = "APPROVED"
    SKIPPED = "SKIPPED"
    ALREADY_DECIDED = "ALREADY_DECIDED"
    PRIOR_OUTCOME = "PRIOR_OUTCOME"
    EXPIRED = "EXPIRED"
    REFUSED = "REFUSED"
    GATE_REFUSED = "GATE_REFUSED"


@dataclass(frozen=True)
class DeskDecisionRecord:
    """The record of one dispatched press (read by the reply function and the final edit).

    `reason` is the refusal code (an enum value or a plain string), None for a decision.
    `approval` is the STORED row the answer talks about; `prior_outcome` is set only for an
    APPROVAL_EXPIRED redelivery on an APPROVED approval (G4-032).
    """

    outcome: DeskOutcome
    reason: str | None
    approval: Approval | None
    prior_outcome: PriorOutcome | None = None


@dataclass
class _Request:
    """The in-memory side of one request (restart loses it, D-04)."""

    signal: Signal
    plan: TradePlan
    money: MoneyAtStake
    text: str
    approve_id: str
    skip_id: str
    approve_hash: str
    skip_hash: str
    approve_token: str
    skip_token: str
    message_id: int | None = None
    chat_id: int | str | None = None
    finalized_text: str | None = None


def _journal_payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _approval_id(plan: TradePlan, action: ApprovalAction) -> str:
    return "apv-" + sha256_hex({"trade_plan_id": plan.trade_plan_id, "action": action.value})[:32]


def _json_object(raw: str, field: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{field} must be a JSON object")
    return payload


def _json_decimal(payload: Mapping[str, Any], key: str, field: str) -> Decimal:
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise ValueError(f"{field} {key} must be a decimal string, got {raw!r}")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{field} {key} is not a decimal: {raw!r}") from exc
    if not value.is_finite():
        raise ValueError(f"{field} {key} must be finite, got {raw!r}")
    return value


def _reason_label(reason: RejectionReason | str | None) -> str | None:
    if reason is None:
        return None
    return reason.value if isinstance(reason, RejectionReason) else reason


class ApprovalDesk:
    """Issues DEMO/LIVE approval requests, sends them, records the taps, finalizes messages.

    `profile` is `DEMO_CONFIRM_PROFILE` or `LIVE_CONFIRM_PROFILE` (SHADOW keeps its own book).
    `clock` is injected (no wall clock here). `intent_reader` takes an approval id and returns
    its stored ENTRY intent or None (Phase 24 binds `store.get_entry(approval_id=...)`).
    """

    def __init__(
        self,
        stores: DeskStores,
        *,
        profile: ConfirmProfile,
        clock: Callable[[], datetime],
        intent_reader: IntentReader,
    ) -> None:
        if profile is not DEMO_CONFIRM_PROFILE and profile is not LIVE_CONFIRM_PROFILE:
            raise ValueError(
                "the approval desk serves DEMO_CONFIRM_PROFILE or LIVE_CONFIRM_PROFILE"
            )
        self._stores = stores
        self._profile = profile
        self._clock = clock
        self._intent_reader = intent_reader
        self._mode = profile.mode_label
        self._lock = threading.Lock()
        self._requests: dict[str, _Request] = {}
        self._decisions: dict[str, DeskDecisionRecord] = {}
        # Plan 23-12 sets this when a confirmation flow is attached; it only changes wording.
        self.confirmation_attached = False

    # ---- properties ------------------------------------------------------- #

    @property
    def profile(self) -> ConfirmProfile:
        return self._profile

    @property
    def intent_reader(self) -> IntentReader:
        return self._intent_reader

    # ---- journal ----------------------------------------------------------- #

    def _event_name(self, suffix: str) -> str:
        return f"{self._mode}_{suffix}"

    def _request_correlation(self, signal_id: str) -> str:
        return f"{self._mode.lower()}-request:{signal_id}"

    def _event(
        self,
        request: _Request,
        *,
        short_id: str,
        suffix: str,
        step: str,
        now_utc: datetime,
        payload: Mapping[str, Any],
    ) -> JournalEvent:
        event_type = self._event_name(suffix)
        correlation = self._request_correlation(request.signal.signal_id)
        return JournalEvent(
            journal_event_id=correlated_event_id(
                prefix=f"{self._mode.lower()}-req",
                correlation_id=correlation,
                event_type=event_type,
                entity_id=short_id,
                step=step,
            ),
            occurred_at_utc=now_utc,
            event_type=event_type,
            entity_type="ApprovalRequest",
            entity_id=short_id,
            correlation_id=correlation,
            signal_id=request.signal.signal_id,
            trade_plan_id=request.plan.trade_plan_id,
            approval_id=request.approve_id,
            payload_json=_journal_payload({**payload, "mode": self._mode}),
        )

    # ---- issue -------------------------------------------------------------- #

    def issue(
        self,
        *,
        signal: Signal,
        plan: TradePlan,
        money: MoneyAtStake | None,
        exposure_quote: Decimal,
        reason_codes: Sequence[str],
        now_utc: datetime,
    ) -> IssuedRequest:
        """Build and store the APPROVE and SKIP rows and the request text (nothing is sent).

        Refused BEFORE any write (ValueError, `MoneyAtStakeUnavailable` for a missing money) when
        the money is missing, or disagrees with the plan, or the plan fields cannot be shown.
        Both rows carry `approved_quantity` = the plan's `quantity_after_rounding` and the same
        `money_json`. Order: signal, plan, approve, skip, mapping, then the ISSUED journal row.
        """
        if money is None:
            raise MoneyAtStakeUnavailable("money")
        text = self._request_text_for(
            signal=signal,
            plan=plan,
            money=money,
            exposure_quote=exposure_quote,
            reason_codes=reason_codes,
        )
        mapping = make_short_id_mapping(
            signal_id=signal.signal_id,
            trade_plan_id=plan.trade_plan_id,
            created_at_utc=now_utc,
        )
        with self._lock:
            if mapping.short_id in self._requests:
                raise ValueError("a request for this signal was already issued")
        money_json = money_canonical_json(money)
        approve_token = issue_one_time_token()
        skip_token = issue_one_time_token()

        def _pending(action: ApprovalAction, raw_token: str) -> Approval:
            return Approval(
                approval_id=_approval_id(plan, action),
                trade_plan_id=plan.trade_plan_id,
                signal_id=signal.signal_id,
                action=action,
                result=ApprovalResult.PENDING,
                status=ApprovalResult.PENDING,
                approval_token_hash=token_hash_of(raw_token),
                requested_at_utc=now_utc,
                request_hash=plan.plan_hash,
                approved_quantity=plan.quantity_after_rounding,
                money_json=money_json,
            )

        approve = _pending(ApprovalAction.APPROVE, approve_token)
        skip = _pending(ApprovalAction.SKIP_USER, skip_token)
        request = _Request(
            signal=signal,
            plan=plan,
            money=money,
            text=text,
            approve_id=approve.approval_id,
            skip_id=skip.approval_id,
            approve_hash=approve.approval_token_hash,
            skip_hash=skip.approval_token_hash,
            approve_token=approve_token,
            skip_token=skip_token,
        )
        self._stores.insert_signal(signal)
        self._stores.insert_trade_plan(plan)
        self._stores.insert_pending(approve)
        self._stores.insert_pending(skip)
        self._stores.record_short_id_mapping(mapping)
        self._stores.record_journal(
            self._event(
                request,
                short_id=mapping.short_id,
                suffix=_SUFFIX_ISSUED,
                step="issued",
                now_utc=now_utc,
                payload={
                    "short_id": mapping.short_id,
                    "approve_approval_id": approve.approval_id,
                    "skip_approval_id": skip.approval_id,
                    "plan_hash": plan.plan_hash,
                    "approved_quantity": format(plan.quantity_after_rounding, "f"),
                },
            )
        )
        with self._lock:
            self._requests[mapping.short_id] = request
        return IssuedRequest(approve=approve, skip=skip, mapping=mapping, text=text)

    def _request_text_for(
        self,
        *,
        signal: Signal,
        plan: TradePlan,
        money: MoneyAtStake,
        exposure_quote: Decimal,
        reason_codes: Sequence[str],
    ) -> str:
        take_profit = _json_object(plan.take_profit_json, "take_profit_json")
        tp1 = _json_decimal(take_profit, "tp1", "take_profit_json")
        tp2 = _json_decimal(take_profit, "tp2", "take_profit_json")
        rr = _json_decimal(_json_object(plan.expected_rr_json, "expected_rr_json"), "tp1_rr", "rr")
        rule = _json_object(plan.invalidation_rule_json, "invalidation_rule_json")
        # The quantity share of each take-profit comes from the STORED money block that was built
        # for these legs, never from a constant: no execution module imports the backtest
        # (Phase 19 invariant 7). `require_money_consistent` still compares prices and the number
        # of legs with the plan.
        if len(money.take_profits) != 2:
            raise MoneyAtStakeUnavailable("take_profits", "the money block needs the two TP legs")
        fractions = [leg.fraction for leg in money.take_profits]
        return format_approval_request(
            mode_label=self._mode,
            symbol=signal.symbol,
            direction=signal.direction,
            setup=signal.setup_type,
            entry_min=plan.entry_min_price,
            entry_max=plan.entry_max_price,
            stop_loss=plan.stop_loss_price,
            take_profits=list(zip((tp1, tp2), fractions, strict=True)),
            rr=rr,
            risk_pct=plan.risk_rate,
            expiry_utc=plan.expiry_utc,
            invalidation=f"{rule.get('basis')} at {rule.get('level')}",
            exposure_quote=exposure_quote,
            reason_codes=list(reason_codes),
            signal_id=signal.signal_id,
            detected_at_utc=signal.detected_at_utc,
            approved_quantity=plan.quantity_after_rounding,
            money=money,
        )

    # ---- send --------------------------------------------------------------- #

    async def send(
        self,
        bot: TelegramTextBot,
        *,
        chat_id: int | str,
        issued: IssuedRequest,
        sleep: SleepFn = asyncio.sleep,
    ) -> RequestSendOutcome:
        """Send the request as ONE message with APPROVE and SKIP; the send comes last.

        RetryAfter is honoured inside the message bound (`send_text_bounded`). A failure is
        journaled with its classified kind and approves nothing: both approvals stay PENDING.
        """
        short_id = issued.mapping.short_id
        with self._lock:
            request = self._requests.get(short_id)
        if request is None:
            raise ValueError("unknown request: issue it with this desk first")
        outcome = await send_text_bounded(
            bot,
            chat_id,
            issued.text,
            build_decision_keyboard(issued.mapping.signal_id),
            sleep=sleep,
        )
        now = self._clock()
        if outcome.failure is None:
            raw_id = getattr(outcome.result, "message_id", None)
            message_id = (
                raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
            )
            with self._lock:
                request.message_id = message_id
                request.chat_id = chat_id
            self._stores.record_journal(
                self._event(
                    request,
                    short_id=short_id,
                    suffix=_SUFFIX_SENT,
                    step="sent",
                    now_utc=now,
                    payload={
                        "short_id": short_id,
                        "message_id": message_id,
                        "attempts": outcome.attempts,
                    },
                )
            )
            return RequestSendOutcome(True, message_id, outcome.attempts)
        failure = outcome.failure
        self._stores.record_journal(
            self._event(
                request,
                short_id=short_id,
                suffix=_SUFFIX_SEND_FAILED,
                step="send_failed",
                now_utc=now,
                payload={
                    "short_id": short_id,
                    "attempts": outcome.attempts,
                    "kind": failure.kind.value,
                    "retry_after_seconds": failure.retry_after_seconds,
                    "error_class": failure.detail,
                },
            )
        )
        return RequestSendOutcome(False, None, outcome.attempts, failure)

    # ---- memory readers ------------------------------------------------------ #

    def resolve(self, short_id: str) -> dict[str, Any] | None:
        """The `binding_context_resolver`: the binding context for a short id, or None."""
        with self._lock:
            request = self._requests.get(short_id)
        if request is None:
            return None
        return {
            "plan_hash": request.plan.plan_hash,
            "strategy_version": request.signal.strategy_version,
            "parameter_set_id": request.signal.parameter_set_id,
            "parameter_set_hash": request.signal.parameter_set_hash,
            # REV-12: the approval expiry IS the TradePlan expiry. No new TTL.
            "expiry_utc": request.plan.expiry_utc,
            "raw_token": request.approve_token,
            _SKIP_TOKEN_KEY: request.skip_token,
        }

    def plan_context(self, short_id: str) -> tuple[Signal, TradePlan] | None:
        """The signal and plan behind a short id (memory only), or None."""
        with self._lock:
            request = self._requests.get(short_id)
        return None if request is None else (request.signal, request.plan)

    def money_for(self, key: str) -> MoneyAtStake | None:
        """The money block of a request, by short id or by trade plan id, or None.

        Read from the STORED `money_json` of the APPROVE row (parsed strictly), so the card of
        plan 23-12 shows what was stored, never a recomputation. None when unknown or not stored.
        """
        with self._lock:
            request = self._requests.get(key)
            if request is None:
                request = next(
                    (r for r in self._requests.values() if r.plan.trade_plan_id == key), None
                )
        if request is None:
            return None
        stored = self._stores.lookup_by_token_hash(request.approve_hash)
        if stored is None or stored.money_json is None:
            return None
        return parse_money_json(stored.money_json)

    def request_text(self, short_id: str) -> str | None:
        """The text of the request message as sent (memory only), or None."""
        with self._lock:
            request = self._requests.get(short_id)
        return None if request is None else request.text

    def message_id(self, short_id: str) -> int | None:
        """The Telegram message id of the sent request (memory only), or None."""
        with self._lock:
            request = self._requests.get(short_id)
        return None if request is None else request.message_id

    # ---- dispatch -------------------------------------------------------------- #

    def dispatch(self, parsed: ParsedCallback, **kwargs: Any) -> DispatchResult:
        """`dispatch_callback` with the token of the pressed button, plus a record of the press.

        The user gate keywords are mandatory (review WR-01): a call without `authorized_user_ids`
        is refused before any lookup or write.
        """
        if kwargs.get("authorized_user_ids") is None:
            raise ValueError("authorized_user_ids is required")
        now = self._clock()
        context: dict[str, Any] | None = kwargs.get("binding_context")
        raw_token: str = kwargs.get("raw_token", "")
        if context is not None and parsed.kind in (CallbackKind.APPROVE, CallbackKind.SKIP):
            key = "raw_token" if parsed.kind is CallbackKind.APPROVE else _SKIP_TOKEN_KEY
            raw_token = str(context.get(key, ""))
            binding = {k: v for k, v in context.items() if k != _SKIP_TOKEN_KEY}
            binding["raw_token"] = raw_token
            kwargs["binding_context"] = binding
            kwargs["raw_token"] = raw_token
        # The stored row BEFORE the press: what G4-032 and the expiry answers need.
        prior = self._stores.lookup_by_token_hash(token_hash_of(raw_token)) if raw_token else None
        result = _dispatch_callback(
            parsed,
            journal_receipt=self._stores.record_journal,
            lookup_by_short_id=self._stores.lookup_by_short_id,
            lookup_by_token_hash=self._stores.lookup_by_token_hash,
            save_atomic=self._stores.save_atomic,
            now_utc=now,
            **kwargs,
        )
        if result.ok and result.approval is not None:
            stored = self._stores.lookup_by_token_hash(result.approval.approval_token_hash)
            if stored is not None:
                result = replace(result, approval=stored)
        chat_mismatch = kwargs.get("callback_chat_id") != kwargs.get("authorized_chat_id")
        record = self._classify(result, prior, chat_mismatch=chat_mismatch)
        key_id = current_press_correlation() or ""
        with self._lock:
            self._decisions[key_id] = record
            while len(self._decisions) > _RECORDS_CAP:
                self._decisions.pop(next(iter(self._decisions)))
        return result

    def _classify(
        self, result: DispatchResult, prior: Approval | None, *, chat_mismatch: bool
    ) -> DeskDecisionRecord:
        reason = _reason_label(result.reason_code)
        if chat_mismatch or (reason is not None and reason in _GATE_REASONS):
            return DeskDecisionRecord(DeskOutcome.GATE_REFUSED, reason, None)
        if result.ok:
            approval = result.approval
            if approval is None:
                return DeskDecisionRecord(
                    DeskOutcome.REFUSED, RejectionReason.INVALIDATED.value, None
                )
            if result.already_decided:
                return DeskDecisionRecord(DeskOutcome.ALREADY_DECIDED, ALREADY_DECIDED, approval)
            if approval.status is ApprovalResult.APPROVED:
                return DeskDecisionRecord(DeskOutcome.APPROVED, None, approval)
            if approval.status is ApprovalResult.SKIPPED:
                return DeskDecisionRecord(DeskOutcome.SKIPPED, None, approval)
            return DeskDecisionRecord(DeskOutcome.ALREADY_DECIDED, ALREADY_DECIDED, approval)
        if result.already_decided:
            return DeskDecisionRecord(DeskOutcome.ALREADY_DECIDED, ALREADY_DECIDED, result.approval)
        if reason == RejectionReason.APPROVAL_EXPIRED.value:
            prior_outcome = self._prior_outcome(prior)
            if prior_outcome is not None:
                return DeskDecisionRecord(DeskOutcome.PRIOR_OUTCOME, reason, prior, prior_outcome)
            if prior is not None and prior.status is ApprovalResult.PENDING:
                return DeskDecisionRecord(DeskOutcome.EXPIRED, reason, prior)
            return DeskDecisionRecord(DeskOutcome.REFUSED, reason, prior)
        return DeskDecisionRecord(DeskOutcome.REFUSED, reason or "UNKNOWN", result.approval)

    def _prior_outcome(self, prior: Approval | None) -> PriorOutcome | None:
        try:
            return prior_outcome_for_expired_redelivery(
                reason_code=RejectionReason.APPROVAL_EXPIRED,
                stored=prior,
                intent_reader=self._intent_reader,
            )
        except Exception as exc:  # noqa: BLE001 - an unreadable intent is never "expired"
            log.error("execution.approval_desk.intent_read_failed", error_class=type(exc).__name__)
            if prior is not None and prior.status is ApprovalResult.APPROVED:
                return PriorOutcome.NEEDS_RECONCILIATION
            return None

    def take_decision(self, correlation_id: str | None) -> DeskDecisionRecord | None:
        """Return and clear the record of the press with this correlation id."""
        with self._lock:
            return self._decisions.pop(correlation_id or "", None)

    # ---- reply ------------------------------------------------------------------ #

    def _reply_text(self, record: DeskDecisionRecord) -> str | None:
        """The answer to one press, or None when the final edit already says everything."""
        mode = f"Mode: {self._mode}"
        outcome = record.outcome
        if outcome is DeskOutcome.SKIPPED:
            return None
        if outcome is DeskOutcome.APPROVED:
            body = _ATTACHED_REPLY if self.confirmation_attached else NO_HANDLER_REPLY
        elif outcome is DeskOutcome.ALREADY_DECIDED:
            status = "UNKNOWN" if record.approval is None else record.approval.status.value
            body = f"Already decided: {status}. Nothing changed. [{ALREADY_DECIDED}]"
        elif outcome is DeskOutcome.PRIOR_OUTCOME and record.prior_outcome is not None:
            label = PRIOR_OUTCOME_LABEL[record.prior_outcome]
            body = (
                f"The plan has expired, but it was approved before: the entry is {label}. "
                "Nothing changed."
            )
            if record.prior_outcome is PriorOutcome.NEEDS_RECONCILIATION:
                body = f"{body}\n{reconciliation_required_text()}"
        elif outcome is DeskOutcome.GATE_REFUSED or record.reason is None:
            body = "Refused. Nothing changed."
        else:
            body = f"Refused: {record.reason}. Nothing changed."
        return f"{mode}\n{body}"

    def reply_fn(
        self, bot: TelegramTextBot, *, sleep: SleepFn = asyncio.sleep
    ) -> Callable[[int, str], Awaitable[None]]:
        """The `reply_text_fn` for `on_callback`: the answer comes from the desk's record.

        The adapter's own text is only the fallback: with no record (a press the desk did not
        dispatch) the answer is the fail-closed "Refused. Nothing changed.". A fresh SKIP sends
        nothing (the final edit carries the decision). A failed reply is logged and never raised:
        the decision is already made.
        """

        async def reply(chat_id: int, text: str) -> None:
            del text
            correlation = current_press_correlation() or ""
            with self._lock:
                record = self._decisions.get(correlation)
                if record is not None and record.outcome is DeskOutcome.GATE_REFUSED:
                    # No final edit follows a gate refusal, so the record is consumed here.
                    self._decisions.pop(correlation, None)
            message = (
                f"Mode: {self._mode}\nRefused. Nothing changed."
                if record is None
                else self._reply_text(record)
            )
            if message is None:
                return
            outcome = await send_text_bounded(bot, chat_id, message, sleep=sleep)
            if outcome.failure is not None:
                log.warning(
                    "execution.approval_desk.reply_failed",
                    kind=outcome.failure.kind.value,
                    detail=outcome.failure.detail,
                )

        return reply

    # ---- final text ----------------------------------------------------------------- #

    def _decision_line(self, approval: Approval) -> str:
        actor = approval.actor_id
        who = f"user {actor}" if actor else "an unrecorded user"
        when = (
            ""
            if approval.acted_at_utc is None
            else f" at {format_presentation_time(approval.acted_at_utc)}"
        )
        return f"Decision: {approval.status.value} by {who}{when}"

    def _state_text(
        self, request: _Request, *, now_utc: datetime, refused_code: str | None = None
    ) -> str | None:
        """The final text of a request from the STORED state, or None while it can still change."""
        rows = [
            self._stores.lookup_by_token_hash(request.approve_hash),
            self._stores.lookup_by_token_hash(request.skip_hash),
        ]
        for row in rows:
            if row is not None and row.status in (ApprovalResult.APPROVED, ApprovalResult.SKIPPED):
                note = ""
                if row.status is ApprovalResult.APPROVED:
                    note = f"\n{_ATTACHED_NOTE if self.confirmation_attached else _NO_HANDLER_NOTE}"
                return f"{request.text}\n{self._decision_line(row)}{note}"
        expiry = request.plan.expiry_utc
        if now_utc >= expiry or any(
            row is not None and row.status is ApprovalResult.EXPIRED for row in rows
        ):
            return (
                f"{request.text}\nEXPIRED: the plan expired at {format_presentation_time(expiry)}; "
                "no decision was taken."
            )
        if refused_code is not None:
            return f"{request.text}\nRefused: {refused_code}; no decision was taken."
        return None

    # ---- finalize ----------------------------------------------------------------------- #

    def _journal_edit_failure(
        self,
        request: _Request,
        *,
        short_id: str,
        message_id: int,
        trigger: str,
        step: str,
        failure: TelegramFailure | None,
        attempts: int,
        now_utc: datetime,
    ) -> None:
        payload: dict[str, Any] = {
            "short_id": short_id,
            "message_id": message_id,
            "trigger": trigger,
            "attempts": attempts,
            "kind": None if failure is None else failure.kind.value,
            "error_class": None if failure is None else failure.detail,
        }
        try:
            self._stores.record_journal(
                self._event(
                    request,
                    short_id=short_id,
                    suffix=_SUFFIX_EDIT_FAILED,
                    step=step,
                    now_utc=now_utc,
                    payload=payload,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a failed removal never changes a decision
            log.error(
                "execution.approval_desk.edit_failure_journal_failed",
                error_class=type(exc).__name__,
            )

    def finalize_hook(
        self, bot: TelegramTextBot, *, sleep: SleepFn = asyncio.sleep
    ) -> FinalizeHook:
        """The `finalize_message` hook: the request message becomes final once nothing can follow.

        The final text is the request text plus one `Decision:` line (status, actor, the local +07
        time with UTC in brackets of the STORED row), or the EXPIRED line, with the keyboard
        removed in the same edit. A transient refusal (store failure, handler error) keeps the
        keyboard. A short id the desk does not know (a restart lost it) loses its keyboard only.
        The same final text is not edited twice. A failed edit is journaled and logged; it never
        changes a decision.
        """

        async def hook(press: CallbackPress, result: DispatchResult) -> None:
            del result
            record = self.take_decision(press.correlation_id)
            if record is None or record.outcome is DeskOutcome.GATE_REFUSED:
                return
            if record.reason in _TRANSIENT_REASONS:
                return
            if press.message_id is None:
                return
            short_id = press.parsed.short_id
            now = self._clock()
            with self._lock:
                request = self._requests.get(short_id)
            text: str | None = None
            if request is not None:
                refused = record.reason if record.outcome is DeskOutcome.REFUSED else None
                text = self._state_text(request, now_utc=now, refused_code=refused)
                if text is None:
                    return
                if request.finalized_text == text:
                    return
            outcome = await finalize_decided_message(
                bot,
                chat_id=press.chat_id,
                message_id=press.message_id,
                text=text,
                sleep=sleep,
            )
            if outcome.done:
                if request is not None:
                    with self._lock:
                        request.finalized_text = text
                return
            log.warning(
                "execution.approval_desk.decided_edit_failed",
                kind=None if outcome.failure is None else outcome.failure.kind.value,
                detail=None if outcome.failure is None else outcome.failure.detail,
            )
            if request is not None:
                self._journal_edit_failure(
                    request,
                    short_id=short_id,
                    message_id=press.message_id,
                    trigger=press.parsed.kind.value,
                    step=f"press:{press.correlation_id}",
                    failure=outcome.failure,
                    attempts=outcome.attempts,
                    now_utc=now,
                )

        return hook

    async def finalize_expired_requests(
        self, bot: TelegramTextBot, *, now_utc: datetime, sleep: SleepFn = asyncio.sleep
    ) -> list[str]:
        """Edit every sent, untapped request whose plan expired to its final EXPIRED text, once.

        Untapped means both approvals are still PENDING. No approval row is written (the expiry
        policy of the rows is Phase 24's, O-2). Returns the short ids that were finalized.
        """
        with self._lock:
            candidates = [
                (short_id, request)
                for short_id, request in self._requests.items()
                if request.message_id is not None and request.finalized_text is None
            ]
        finalized: list[str] = []
        for short_id, request in candidates:
            message_id = request.message_id
            chat_id = request.chat_id
            if message_id is None or chat_id is None or now_utc < request.plan.expiry_utc:
                continue
            rows = [
                self._stores.lookup_by_token_hash(request.approve_hash),
                self._stores.lookup_by_token_hash(request.skip_hash),
            ]
            if any(row is None or row.status is not ApprovalResult.PENDING for row in rows):
                continue
            text = self._state_text(request, now_utc=now_utc)
            if text is None:
                continue
            outcome = await finalize_decided_message(
                bot,
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                sleep=sleep,
            )
            if outcome.done:
                with self._lock:
                    request.finalized_text = text
                finalized.append(short_id)
                continue
            self._journal_edit_failure(
                request,
                short_id=short_id,
                message_id=message_id,
                trigger="expiry_sweep",
                step="expiry_sweep",
                failure=outcome.failure,
                attempts=outcome.attempts,
                now_utc=now_utc,
            )
        return finalized


__all__ = [
    "EVENT_DEMO_APPROVAL_REQUEST_ISSUED",
    "EVENT_DEMO_APPROVAL_REQUEST_SENT",
    "EVENT_DEMO_APPROVAL_REQUEST_SEND_FAILED",
    "EVENT_DEMO_DECIDED_MESSAGE_EDIT_FAILED",
    "EVENT_LIVE_APPROVAL_REQUEST_ISSUED",
    "EVENT_LIVE_APPROVAL_REQUEST_SENT",
    "EVENT_LIVE_APPROVAL_REQUEST_SEND_FAILED",
    "EVENT_LIVE_DECIDED_MESSAGE_EDIT_FAILED",
    "NO_HANDLER_REPLY",
    "ApprovalDesk",
    "DeskDecisionRecord",
    "DeskOutcome",
    "DeskStores",
    "IssuedRequest",
    "RequestSendOutcome",
]
