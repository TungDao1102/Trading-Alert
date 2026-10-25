"""SHADOW approval front half (Phase 16, plan 16-04, D-12, D-16, D-35, L-12, REV-12).

SHADOW means a signal becomes a labelled Telegram alert with functional APPROVE and SKIP
buttons, and the human decision is journaled with measured timestamps. SHADOW NEVER places an
order (D040): this module imports nothing from `src.execution` and nothing from `telegram`
(python-telegram-bot stays behind `src/adapters/telegram_notify.py`).

What lives here:
  - `Mode` and `SHADOW_LABEL`: only `Mode.SHADOW` is constructible (`require_shadow`); DEMO and
    LIVE exist as names only.
  - `render_shadow_message`: the ONE composer of SHADOW text. Every text this layer sends is
    built by it, so the alert, the decision replies and the send-failure notice cannot leave
    without the exact label, the mode and every time in UTC and Asia/Ho_Chi_Minh.
  - `ShadowApprovalBook`: issues the one-time tokens, holds the RAW tokens in memory only (PG
    holds hashes), resolves the `binding_context` for `on_callback` / `dispatch_callback`, and
    wraps `dispatch_callback` so a decision is stamped and journaled.
  - `send_shadow_alert`: parents first, journal first, then the send.
  - Restart handling: raw tokens do not survive a restart, so pending approvals are expired.
  - Plan 16-11 (D041): the confirm card, the confirm result and the card-delivery-failure notice
    are composed here too (`ShadowMessageKind.CONFIRM_*`); the confirm state machine itself
    lives in `src/paper/shadow_confirm.py`.

Button contract (F-961): SHADOW alerts use the live `APR:` and `SKP:` buttons only
(`build_shadow_decision_keyboard`). The SIMULATE-only keyboard (inert `SIM:`/`SKIP:` data) is
never sent by SHADOW code.

Approval rows: a SHADOW alert has TWO PENDING approvals for one plan, one with action APPROVE
and one with action SKIP_USER, each with its own one-time token, because the replay layer
rejects a button whose action differs from the stored row (CR-01). PostgreSQL allows only one
decided approval per plan, so the first press wins and the other row can never be decided.

Authorization: callbacks pass the existing `authorized_chat_gate` (chat id). User-id
authorization is Phase 23 and is NOT implemented here; the actor recorded on a decision is the
callback chat id.

Expiry (REV-12): the approval expiry is the TradePlan expiry (`plan.expiry_utc`), enforced by the
binding gate (`now_utc >= expiry_utc` is expired). There is no new TTL parameter; an APPROVE after
expiry is journaled as APPROVAL_EXPIRED and never revives the signal.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

import structlog
from tenacity import AsyncRetrying, RetryCallState, RetryError, wait_random_exponential

from src.adapters.telegram_callbacks import (
    CallbackKind,
    DispatchResult,
    ParsedCallback,
    current_press_correlation,
)
from src.adapters.telegram_callbacks import dispatch_callback as _dispatch_callback
from src.adapters.telegram_notify import (
    TelegramFailure,
    TelegramFailureKind,
    TelegramSendError,
    TelegramTextBot,
    build_shadow_decision_keyboard,
    format_approve,
    send_text,
)
from src.approval.confirm_core import ConfirmOutcome, ConfirmRecord
from src.approval.mapping import ShortIdMapping, make_short_id_mapping
from src.approval.replay import ApprovalAlreadyDecided
from src.approval.tokens import issue_one_time_token, token_hash_of
from src.backtest.semantics import TP1_QUANTITY_FRACTION
from src.domain.approval import Approval
from src.domain.canonical import sha256_hex
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper.notify import (
    NOTIFY_MAX_ATTEMPTS,
    NOTIFY_MAX_DELAY_SECONDS,
    NOTIFY_WAIT_MAX_SECONDS,
    NOTIFY_WAIT_MULTIPLIER_SECONDS,
)

log = structlog.get_logger()

SHADOW_LABEL: Final = "SHADOW — no real order"
DISPLAY_ZONE: Final = "Asia/Ho_Chi_Minh"
_TIME_FORMAT: Final = "%Y-%m-%d %H:%M:%S"

EVENT_SHADOW_ALERT_PENDING: Final = "SHADOW_ALERT_PENDING"
EVENT_SHADOW_ALERT_SENT: Final = "SHADOW_ALERT_SENT"
EVENT_SHADOW_ALERT_FAILED: Final = "SHADOW_ALERT_FAILED"
EVENT_APPROVAL_EXPIRED: Final = "APPROVAL_EXPIRED"
EVENT_PENDING_INVALIDATED: Final = "SHADOW_PENDING_INVALIDATED"
# The correlation of an alert's journal rows (`shadow-alert:<signal_id>`); plan 16-57 reads it at
# restart to tell an alert that persisted from a risk-passed bar whose alert never did.
ALERT_CORRELATION_PREFIX: Final = "shadow-alert:"
REASON_RUNTIME_RESTART: Final = "RUNTIME_RESTART"

_CONTEXT_SKIP_TOKEN: Final = "skip_raw_token"


# --------------------------------------------------------------------------- #
# Mode.
# --------------------------------------------------------------------------- #


class Mode(str, Enum):
    """Runtime mode carried in every message. DEMO and LIVE are names only (D-12)."""

    SHADOW = "SHADOW"
    DEMO = "DEMO"
    LIVE = "LIVE"


class ModeNotConstructible(ValueError):
    """A mode other than SHADOW was requested from Phase 16 code."""


def require_shadow(mode: Mode) -> None:
    """Raise unless `mode` is `Mode.SHADOW` (D-12, L-12: SHADOW is the only constructible mode)."""
    if mode is not Mode.SHADOW:
        raise ModeNotConstructible(
            f"only Mode.SHADOW is constructible by Phase 16 code, got {mode!r}"
        )


# --------------------------------------------------------------------------- #
# The single composer of SHADOW text (D-12, D-35).
# --------------------------------------------------------------------------- #


class ShadowMessageKind(str, Enum):
    """Every kind of text the SHADOW layer sends (plan 16-11 added the three confirm kinds)."""

    ALERT = "ALERT"
    DECISION_RESULT = "DECISION_RESULT"
    SEND_FAILURE_NOTICE = "SEND_FAILURE_NOTICE"
    CONFIRM_CARD = "CONFIRM_CARD"
    CONFIRM_RESULT = "CONFIRM_RESULT"
    CARD_DELIVERY_FAILED = "CARD_DELIVERY_FAILED"


class ShadowDecisionOutcome(str, Enum):
    """What a button press amounted to, as shown to the operator."""

    APPROVED = "APPROVED"
    SKIPPED = "SKIPPED"
    REPLAYED = "REPLAYED"
    REJECTED_APPROVAL_EXPIRED = "REJECTED_APPROVAL_EXPIRED"
    REJECTED_OTHER = "REJECTED_OTHER"


@dataclass(frozen=True)
class ConfirmCardFields:
    """The values of the SHADOW confirmation card (D041), already computed by the caller.

    `entry_ref` is the adverse edge of the entry zone (the sizing basis of RISK_MANAGEMENT:
    LONG entry_max, SHORT entry_min), so `notional` and `estimated_loss` are the conservative
    figures. `mark_price` is None when the injected provider had none; the card then says so.
    """

    symbol: str
    side: str
    quantity: Decimal
    entry_ref: Decimal
    stop_loss: Decimal
    notional: Decimal
    estimated_loss: Decimal
    mark_price: Decimal | None
    plan_expiry_utc: datetime
    plan_remaining_seconds: int
    confirm_ttl_seconds: int
    confirm_until_utc: datetime


def _plain(value: Decimal) -> str:
    """A Decimal without exponent or trailing zeros (`48.00` -> `48`, `0.080` -> `0.08`)."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_time_pair(instant_utc: datetime) -> str:
    """The instant in UTC and in Asia/Ho_Chi_Minh, e.g. `2026-10-09 03:00:00 UTC (... +7h ...)`."""
    if instant_utc.tzinfo is None:
        raise ValueError("instant must be UTC-aware, got naive datetime")
    utc = instant_utc.astimezone(UTC)
    local = utc.astimezone(ZoneInfo(DISPLAY_ZONE))
    return f"{utc.strftime(_TIME_FORMAT)} UTC ({local.strftime(_TIME_FORMAT)} {DISPLAY_ZONE})"


def render_shadow_message(
    kind: ShadowMessageKind,
    *,
    mode: Mode,
    now_utc: datetime,
    body: str = "",
    detected_at_utc: datetime | None = None,
    expiry_utc: datetime | None = None,
    outcome: ShadowDecisionOutcome | None = None,
    detail: str = "",
    failure_kind: str = "",
    retry_after_seconds: int | None = None,
    signal_id: str = "",
    card: ConfirmCardFields | None = None,
    confirm_outcome: ConfirmOutcome | None = None,
    confirm_requested_at_utc: datetime | None = None,
) -> str:
    """Compose a SHADOW text: label, mode, the kind's lines, every time as a UTC + local pair.

    This is the only function that builds SHADOW text. Anything it renders carries the exact
    label, `Mode: SHADOW` and the time of rendering plus every plan time given, each in UTC and
    Asia/Ho_Chi_Minh. A mode other than SHADOW raises.
    """
    require_shadow(mode)
    lines = [SHADOW_LABEL, f"Mode: {mode.value}"]
    if kind is ShadowMessageKind.ALERT:
        if body == "":
            raise ValueError("an ALERT needs a body")
        lines.append(body)
        if detected_at_utc is not None:
            lines.append(f"Detected: {format_time_pair(detected_at_utc)}")
        if expiry_utc is not None:
            lines.append(f"Expiry: {format_time_pair(expiry_utc)}")
    elif kind is ShadowMessageKind.DECISION_RESULT:
        if outcome is None:
            raise ValueError("a DECISION_RESULT needs an outcome")
        lines.append(f"Decision: {outcome.value}")
        if detail != "":
            lines.append(f"Detail: {detail}")
        if expiry_utc is not None:
            lines.append(f"Plan expiry: {format_time_pair(expiry_utc)}")
    elif kind is ShadowMessageKind.SEND_FAILURE_NOTICE:
        if failure_kind == "":
            raise ValueError("a SEND_FAILURE_NOTICE needs a failure kind")
        retry = "" if retry_after_seconds is None else f" (retry_after {retry_after_seconds}s)"
        lines.append(f"Alert not delivered: {failure_kind}{retry}")
        if signal_id != "":
            lines.append(f"Signal: {signal_id}")
        lines.append("Nothing was approved.")
    elif kind is ShadowMessageKind.CONFIRM_CARD:
        if card is None:
            raise ValueError("a CONFIRM_CARD needs its card fields")
        mark = "mark price unavailable" if card.mark_price is None else _plain(card.mark_price)
        lines.extend(
            [
                "Confirm this SHADOW plan? No real order will be placed.",
                f"Symbol: {card.symbol}",
                f"Side: {card.side}",
                f"Quantity: {_plain(card.quantity)}",
                f"Entry (adverse edge): {_plain(card.entry_ref)}",
                f"Stop loss: {_plain(card.stop_loss)}",
                f"Notional: {_plain(card.notional)} quote",
                f"Estimated loss at SL: {_plain(card.estimated_loss)} quote",
                f"Mark price: {mark}",
                f"Plan expiry: {format_time_pair(card.plan_expiry_utc)} "
                f"(remaining {card.plan_remaining_seconds} s)",
                f"Confirm within {card.confirm_ttl_seconds} s "
                f"(until {format_time_pair(card.confirm_until_utc)})",
            ]
        )
    elif kind is ShadowMessageKind.CONFIRM_RESULT:
        if confirm_outcome is None:
            raise ValueError("a CONFIRM_RESULT needs an outcome")
        lines.append(f"Confirm: {confirm_outcome.value}")
        if detail != "":
            lines.append(f"Detail: {detail}")
        if confirm_requested_at_utc is not None:
            lines.append(f"Confirm requested: {format_time_pair(confirm_requested_at_utc)}")
        if expiry_utc is not None:
            lines.append(f"Plan expiry: {format_time_pair(expiry_utc)}")
        lines.append(
            "Nothing was simulated."
            if confirm_outcome is not ConfirmOutcome.CONFIRMED
            else "SHADOW only: no order was placed."
        )
    elif kind is ShadowMessageKind.CARD_DELIVERY_FAILED:
        if failure_kind == "":
            raise ValueError("a CARD_DELIVERY_FAILED notice needs a failure kind")
        lines.append(f"Confirmation card not delivered: {failure_kind}")
        if signal_id != "":
            lines.append(f"Signal: {signal_id}")
        if expiry_utc is not None:
            lines.append(f"Plan expiry: {format_time_pair(expiry_utc)}")
        lines.append("The plan was approved but cannot be confirmed. Nothing was simulated.")
    else:  # pragma: no cover - the enum is closed
        raise ValueError(f"unknown SHADOW message kind {kind!r}")
    lines.append(f"Time: {format_time_pair(now_utc)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The alert text.
# --------------------------------------------------------------------------- #


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


def format_shadow_alert(
    *,
    signal: Signal,
    plan: TradePlan,
    mode: Mode,
    now_utc: datetime,
    exposure_quote: Decimal,
    reason_codes: Sequence[str],
) -> str:
    """The SHADOW alert: the 12 APRV-01 fields (via `format_approve`) in the SHADOW envelope.

    `format_approve` still validates and renders the fields fail-closed; its two UTC time lines
    (`Detected:`, `Expiry:`) are replaced by `render_shadow_message` lines that show the detected
    and expiry times in UTC and Asia/Ho_Chi_Minh (format_approve has no display note since
    Phase 23, D-14; the SHADOW text keeps both zones). The alert also shows the plan's
    `quantity_after_rounding` on a `Quantity:` line (D078 item (6)): the value
    `ShadowApprovalBook.issue` stores as `approved_quantity` on both rows. A plan whose
    quantity is not above zero is refused here (ValueError), before anything is stored
    or sent.
    """
    require_shadow(mode)
    take_profit = _json_object(plan.take_profit_json, "take_profit_json")
    tp1 = _json_decimal(take_profit, "tp1", "take_profit_json")
    tp2 = _json_decimal(take_profit, "tp2", "take_profit_json")
    rr = _json_decimal(_json_object(plan.expected_rr_json, "expected_rr_json"), "tp1_rr", "rr")
    rule = _json_object(plan.invalidation_rule_json, "invalidation_rule_json")
    invalidation = f"{rule.get('basis')} at {rule.get('level')}"
    approve_text = format_approve(
        symbol=signal.symbol,
        direction=signal.direction,
        setup=signal.setup_type,
        entry_min=plan.entry_min_price,
        entry_max=plan.entry_max_price,
        stop_loss=plan.stop_loss_price,
        take_profits=[(tp1, TP1_QUANTITY_FRACTION), (tp2, Decimal(1) - TP1_QUANTITY_FRACTION)],
        rr=rr,
        risk_pct=plan.risk_rate,
        expiry_utc=plan.expiry_utc,
        invalidation=invalidation,
        exposure_quote=exposure_quote,
        reason_codes=list(reason_codes),
        signal_id=signal.signal_id,
        detected_at_utc=signal.detected_at_utc,
        approved_quantity=plan.quantity_after_rounding,
    )
    all_lines = approve_text.split("\n")
    body_lines = [line for line in all_lines if not line.startswith(("Detected: ", "Expiry: "))]
    if len(all_lines) - len(body_lines) != 2:
        raise RuntimeError("format_approve no longer has the Detected/Expiry lines")
    return render_shadow_message(
        ShadowMessageKind.ALERT,
        mode=mode,
        now_utc=now_utc,
        body="\n".join(body_lines),
        detected_at_utc=signal.detected_at_utc,
        expiry_utc=plan.expiry_utc,
    )


# --------------------------------------------------------------------------- #
# Stores port.
# --------------------------------------------------------------------------- #


class ShadowStores(Protocol):
    """What the SHADOW layer needs from persistence (the Phase 17 PG stores, composed in 16-31).

    Parent rows go first: the signal, then the plan, then approvals, mapping and journal rows.
    `list_pending_approvals` is the one reader the PG approval store does not have yet; the
    runtime composition adds it.
    """

    def insert_signal(self, signal: Signal) -> None: ...
    def insert_trade_plan(self, plan: TradePlan) -> None: ...
    def insert_pending(self, approval: Approval) -> None: ...
    def record_short_id_mapping(self, mapping: ShortIdMapping) -> None: ...
    def save_atomic(self, approval: Approval, mapping: ShortIdMapping | None) -> None: ...
    def lookup_by_token_hash(self, token_hash: str) -> Approval | None: ...
    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None: ...
    def list_pending_approvals(self) -> list[Approval]: ...
    def record_journal(self, event: JournalEvent) -> None: ...


def _journal_payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# The approval book.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IssuedApprovals:
    """The rows `ShadowApprovalBook.issue` made. The raw tokens are NOT here (memory only)."""

    approve: Approval
    skip: Approval
    mapping: ShortIdMapping


@dataclass(frozen=True)
class DecisionRecord:
    """What the last `ShadowApprovalBook.dispatch` amounted to (consumed by the reply function)."""

    outcome: ShadowDecisionOutcome
    expiry_utc: datetime | None


def _approval_id(plan: TradePlan, action: ApprovalAction) -> str:
    return "apv-" + sha256_hex({"trade_plan_id": plan.trade_plan_id, "action": action.value})[:32]


def approval_id_for(plan: TradePlan, action: ApprovalAction) -> str:
    """The deterministic id of a plan's APPROVE or SKIP_USER approval row (read by plan 16-31)."""
    return _approval_id(plan, action)


class ShadowApprovalBook:
    """Issues approvals, holds the raw tokens (memory only) and wraps `dispatch_callback`.

    `resolve` is the `binding_context_resolver` for `on_callback`; `dispatch` is its `dispatch`
    argument. Raw tokens never reach PostgreSQL, the journal or any message (T-16-10).
    """

    def __init__(self, stores: ShadowStores, *, clock: Callable[[], datetime]) -> None:
        self._stores = stores
        self._clock = clock
        self._contexts: dict[str, dict[str, Any]] = {}
        self._plans: dict[str, tuple[Signal, TradePlan]] = {}
        self._last: DecisionRecord | None = None

    def issue(self, *, signal: Signal, plan: TradePlan, now_utc: datetime) -> IssuedApprovals:
        """Build the PENDING APPROVE and SKIP approvals and the short-id mapping.

        Both rows carry `approved_quantity` = the plan's `quantity_after_rounding` (D078,
        19-REVIEW WR-01), the figure the SHADOW alert and
        `render_confirm_card` show. The SKIP row's value is never read; the two rows of one
        request stay identical.
        """
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
            )

        mapping = make_short_id_mapping(
            signal_id=signal.signal_id,
            trade_plan_id=plan.trade_plan_id,
            created_at_utc=now_utc,
        )
        self._plans[mapping.short_id] = (signal, plan)
        self._contexts[mapping.short_id] = {
            "plan_hash": plan.plan_hash,
            "strategy_version": signal.strategy_version,
            "parameter_set_id": signal.parameter_set_id,
            "parameter_set_hash": signal.parameter_set_hash,
            # REV-12: the approval expiry IS the TradePlan expiry. No new TTL.
            "expiry_utc": plan.expiry_utc,
            "raw_token": approve_token,
            _CONTEXT_SKIP_TOKEN: skip_token,
        }
        return IssuedApprovals(
            approve=_pending(ApprovalAction.APPROVE, approve_token),
            skip=_pending(ApprovalAction.SKIP_USER, skip_token),
            mapping=mapping,
        )

    def resolve(self, short_id: str) -> dict[str, Any] | None:
        """The `binding_context_resolver`: the binding context for a short id, or None."""
        context = self._contexts.get(short_id)
        return None if context is None else dict(context)

    def plan_context(self, short_id: str) -> tuple[Signal, TradePlan] | None:
        """The signal and plan behind a short id (memory only, like the raw tokens), or None.

        The confirm layer (plan 16-11) renders the confirmation card from it. After a restart
        the context is gone, which is consistent with the raw tokens being gone.
        """
        return self._plans.get(short_id)

    def take_last_decision(self) -> DecisionRecord | None:
        """Return and clear the record of the last `dispatch` (read by the reply function)."""
        record, self._last = self._last, None
        return record

    def dispatch(self, parsed: ParsedCallback, **kwargs: Any) -> DispatchResult:
        """`dispatch_callback` with the right token per button, an actor stamp and journaling."""
        now = self._clock()
        context: dict[str, Any] | None = kwargs.get("binding_context")
        raw_token: str = kwargs.get("raw_token", "")
        if context is not None and parsed.kind in (CallbackKind.APPROVE, CallbackKind.SKIP):
            key = "raw_token" if parsed.kind is CallbackKind.APPROVE else _CONTEXT_SKIP_TOKEN
            raw_token = str(context.get(key, ""))
            binding = {k: v for k, v in context.items() if k != _CONTEXT_SKIP_TOKEN}
            binding["raw_token"] = raw_token
            kwargs["binding_context"] = binding
            kwargs["raw_token"] = raw_token
        prior = self._stores.lookup_by_token_hash(token_hash_of(raw_token)) if raw_token else None
        actor_id = str(kwargs["callback_chat_id"])

        def _save(approval: Approval, mapping: ShortIdMapping | None) -> None:
            stamped = approval if approval.actor_id else replace(approval, actor_id=actor_id)
            self._stores.save_atomic(stamped, mapping)

        result = _dispatch_callback(
            parsed,
            journal_receipt=self._stores.record_journal,
            lookup_by_short_id=self._stores.lookup_by_short_id,
            lookup_by_token_hash=self._stores.lookup_by_token_hash,
            save_atomic=_save,
            now_utc=now,
            **kwargs,
        )
        if result.ok and result.approval is not None:
            stored = self._stores.lookup_by_token_hash(result.approval.approval_token_hash)
            if stored is not None:
                result = replace(result, approval=stored)
        if result.reason_code is RejectionReason.APPROVAL_EXPIRED and prior is not None:
            self._journal_expired(prior, parsed, now, kwargs)
        expiry = None if context is None else context.get("expiry_utc")
        self._last = DecisionRecord(_classify(result, prior), expiry)
        return result

    def _journal_expired(
        self, prior: Approval, parsed: ParsedCallback, now: datetime, kwargs: Mapping[str, Any]
    ) -> None:
        correlation = str(kwargs.get("correlation_id", ""))
        context = kwargs.get("binding_context") or {}
        self._stores.record_journal(
            JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix="shadow",
                    correlation_id=f"approval:{prior.approval_id}",
                    event_type=EVENT_APPROVAL_EXPIRED,
                    entity_id=prior.approval_id,
                    step=f"press:{correlation}",
                ),
                occurred_at_utc=now,
                event_type=EVENT_APPROVAL_EXPIRED,
                entity_type="Approval",
                entity_id=prior.approval_id,
                correlation_id=f"approval:{prior.approval_id}",
                signal_id=prior.signal_id,
                trade_plan_id=prior.trade_plan_id,
                approval_id=prior.approval_id,
                payload_json=_journal_payload(
                    {
                        "reason_code": RejectionReason.APPROVAL_EXPIRED.value,
                        "kind": parsed.kind.value,
                        "expiry_utc": _iso(context.get("expiry_utc")),
                        "mode": Mode.SHADOW.value,
                    }
                ),
            )
        )


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _classify(result: DispatchResult, prior: Approval | None) -> ShadowDecisionOutcome:
    if not result.ok:
        if result.reason_code is RejectionReason.APPROVAL_EXPIRED:
            return ShadowDecisionOutcome.REJECTED_APPROVAL_EXPIRED
        return ShadowDecisionOutcome.REJECTED_OTHER
    approval = result.approval
    if approval is None or approval.status is ApprovalResult.EXPIRED:
        return ShadowDecisionOutcome.REJECTED_OTHER
    if prior is not None and prior.status is not ApprovalResult.PENDING:
        return ShadowDecisionOutcome.REPLAYED
    if approval.status is ApprovalResult.APPROVED:
        return ShadowDecisionOutcome.APPROVED
    if approval.status is ApprovalResult.SKIPPED:
        return ShadowDecisionOutcome.SKIPPED
    return ShadowDecisionOutcome.REJECTED_OTHER


# --------------------------------------------------------------------------- #
# The alert sender: parents first, journal first, then the send.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ShadowSendOutcome:
    """What `send_shadow_alert` did. It never raises on a send failure and never approves.

    On failure `failure` is the classified failure and `notice_text` the SHADOW-labelled failure
    notice (journaled; no further Telegram text is sent after a failure).
    """

    sent: bool
    attempts: int
    short_id: str
    failure: TelegramFailure | None = None
    notice_text: str = ""


def _alert_event(
    *,
    event_type: str,
    step: str,
    signal: Signal,
    plan: TradePlan,
    approval: Approval,
    short_id: str,
    now_utc: datetime,
    payload: Mapping[str, Any],
) -> JournalEvent:
    correlation = f"{ALERT_CORRELATION_PREFIX}{signal.signal_id}"
    return JournalEvent(
        journal_event_id=correlated_event_id(
            prefix="shadow",
            correlation_id=correlation,
            event_type=event_type,
            entity_id=short_id,
            step=step,
        ),
        occurred_at_utc=now_utc,
        event_type=event_type,
        entity_type="ShadowAlert",
        entity_id=short_id,
        correlation_id=correlation,
        signal_id=signal.signal_id,
        trade_plan_id=plan.trade_plan_id,
        approval_id=approval.approval_id,
        payload_json=_journal_payload({**payload, "mode": Mode.SHADOW.value}),
    )


# --------------------------------------------------------------------------- #
# Bounded send retry: the notify_simulate pattern, with retry_after honoured.
# --------------------------------------------------------------------------- #


def _failure_of(exc: BaseException | None) -> TelegramFailure:
    if isinstance(exc, TelegramSendError):
        return exc.failure
    name = "UnknownError" if exc is None else type(exc).__name__
    return TelegramFailure(TelegramFailureKind.UNKNOWN, None, name)


def _failure_of_state(retry_state: RetryCallState) -> TelegramFailure:
    outcome = retry_state.outcome
    return _failure_of(None if outcome is None else outcome.exception())


def _is_retryable(exc: BaseException) -> bool:
    """Transient faults only: programming errors and refusals fail at once (WR-02, fail closed)."""
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return False
    if isinstance(exc, TelegramSendError):
        return exc.failure.kind in (
            TelegramFailureKind.RATE_LIMITED,
            TelegramFailureKind.TRANSIENT,
            TelegramFailureKind.UNKNOWN,
        )
    return True


def _retryable_state(retry_state: RetryCallState) -> bool:
    outcome = retry_state.outcome
    if outcome is None or not outcome.failed:
        return False
    exc = outcome.exception()
    return exc is not None and _is_retryable(exc)


def _remaining_budget(retry_state: RetryCallState) -> float:
    return NOTIFY_MAX_DELAY_SECONDS - (retry_state.seconds_since_start or 0.0)


def _stop(retry_state: RetryCallState) -> bool:
    """The `notify_simulate` stop (attempts or delay), plus: never wait past the budget."""
    if retry_state.attempt_number >= NOTIFY_MAX_ATTEMPTS:
        return True
    remaining = _remaining_budget(retry_state)
    if remaining <= 0:
        return True
    retry_after = _failure_of_state(retry_state).retry_after_seconds
    return retry_after is not None and retry_after > remaining


_BACKOFF = wait_random_exponential(
    multiplier=NOTIFY_WAIT_MULTIPLIER_SECONDS, max=NOTIFY_WAIT_MAX_SECONDS
)


def _wait(retry_state: RetryCallState) -> float:
    """The larger of the jittered backoff and retry_after, never past the remaining budget."""
    retry_after = _failure_of_state(retry_state).retry_after_seconds or 0
    wanted = max(float(_BACKOFF(retry_state)), float(retry_after))
    return max(0.0, min(wanted, _remaining_budget(retry_state)))


async def _send_bounded(
    bot: TelegramTextBot,
    chat_id: int | str,
    text: str,
    keyboard: Any,
    sleep: Callable[[float], Awaitable[None]],
) -> tuple[int, TelegramFailure | None]:
    """Send with the existing retry budget. Returns `(attempts, failure or None)`; never raises."""
    attempts = 0
    try:
        async for attempt in AsyncRetrying(
            stop=_stop,
            wait=_wait,
            retry=_retryable_state,
            reraise=True,
            sleep=sleep,
        ):
            with attempt:
                attempts += 1
                await send_text(bot, chat_id, text, keyboard)
    except RetryError as exc:  # pragma: no cover - reraise=True re-raises the cause instead
        attempt_exc = exc.last_attempt.exception() if exc.last_attempt else None
        return attempts, _failure_of(attempt_exc)
    except Exception as exc:  # noqa: BLE001 - classified and journaled, never raised
        return attempts, _failure_of(exc)
    return attempts, None


async def send_shadow_alert(
    *,
    stores: ShadowStores,
    book: ShadowApprovalBook,
    bot: TelegramTextBot,
    chat_id: int | str,
    mode: Mode,
    signal: Signal,
    plan: TradePlan,
    exposure_quote: Decimal,
    reason_codes: Sequence[str],
    now_utc: datetime,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ShadowSendOutcome:
    """Persist the parents and PENDING approvals, journal, then send the labelled alert.

    Order: parents first (signal, plan, both approvals, the short-id mapping), the journal row
    next, the send last. A send failure is journaled with its classified kind and approves
    nothing; the approvals stay PENDING. The sleep is injectable so tests never wait.
    """
    require_shadow(mode)
    text = format_shadow_alert(
        signal=signal,
        plan=plan,
        mode=mode,
        now_utc=now_utc,
        exposure_quote=exposure_quote,
        reason_codes=reason_codes,
    )
    keyboard = build_shadow_decision_keyboard(signal.signal_id)
    issued = book.issue(signal=signal, plan=plan, now_utc=now_utc)
    short_id = issued.mapping.short_id

    stores.insert_signal(signal)
    stores.insert_trade_plan(plan)
    stores.insert_pending(issued.approve)
    stores.insert_pending(issued.skip)
    stores.record_short_id_mapping(issued.mapping)

    def _event(event_type: str, step: str, payload: Mapping[str, Any]) -> JournalEvent:
        return _alert_event(
            event_type=event_type,
            step=step,
            signal=signal,
            plan=plan,
            approval=issued.approve,
            short_id=short_id,
            now_utc=now_utc,
            payload=payload,
        )

    # Journal first (RESEARCH Pitfall 5): the row is committed before the send.
    stores.record_journal(
        _event(
            EVENT_SHADOW_ALERT_PENDING,
            "pending",
            {
                "approve_approval_id": issued.approve.approval_id,
                "skip_approval_id": issued.skip.approval_id,
                "short_id": short_id,
            },
        )
    )
    attempts, failure = await _send_bounded(bot, chat_id, text, keyboard, sleep)
    if failure is None:
        stores.record_journal(_event(EVENT_SHADOW_ALERT_SENT, "sent", {"attempts": attempts}))
        return ShadowSendOutcome(sent=True, attempts=attempts, short_id=short_id)
    notice = render_shadow_message(
        ShadowMessageKind.SEND_FAILURE_NOTICE,
        mode=mode,
        now_utc=now_utc,
        failure_kind=failure.kind.value,
        retry_after_seconds=failure.retry_after_seconds,
        signal_id=signal.signal_id,
    )
    stores.record_journal(
        _event(
            EVENT_SHADOW_ALERT_FAILED,
            "failed",
            {
                "attempts": attempts,
                "kind": failure.kind.value,
                "retry_after_seconds": failure.retry_after_seconds,
                "error_class": failure.detail,
                "notice_text": notice,
            },
        )
    )
    return ShadowSendOutcome(
        sent=False, attempts=attempts, short_id=short_id, failure=failure, notice_text=notice
    )


# --------------------------------------------------------------------------- #
# Decision replies: the only other sender in this module.
# --------------------------------------------------------------------------- #


class ConfirmResultSource(Protocol):
    """The confirm book as the reply function sees it: it hands over the record of one press."""

    def take_result(self, correlation_id: str | None) -> ConfirmRecord | None: ...


def _outcome_from_text(text: str) -> ShadowDecisionOutcome:
    """Fail-closed fallback when no dispatch record exists: only an explicit OK counts."""
    if text.startswith("OK: APPROVED"):
        return ShadowDecisionOutcome.APPROVED
    if text.startswith("OK: SKIPPED"):
        return ShadowDecisionOutcome.SKIPPED
    if RejectionReason.APPROVAL_EXPIRED.value in text:
        return ShadowDecisionOutcome.REJECTED_APPROVAL_EXPIRED
    return ShadowDecisionOutcome.REJECTED_OTHER


def make_shadow_reply_fn(
    bot: TelegramTextBot,
    *,
    mode: Mode,
    clock: Callable[[], datetime],
    book: ShadowApprovalBook | None = None,
    confirm_book: ConfirmResultSource | None = None,
) -> Callable[[int, str], Awaitable[None]]:
    """The `reply_text_fn` for `on_callback`: every outcome text goes through the composer.

    The adapter's own outcome string becomes only the `detail` of a DECISION_RESULT message.
    With the approval `book`, the outcome (APPROVED, SKIPPED, REPLAYED, expired, rejected) comes
    from the book's record of the last dispatch; without it, from the text, failing closed. The
    decision is already made when the reply goes out, so a failed reply is logged and never
    raised into the handler. With the `confirm_book` (plan 16-11), the reply to a CONFIRM or
    CANCEL press is a CONFIRM_RESULT message built from the book's record of that press, found by
    the press correlation id.
    """
    require_shadow(mode)

    async def reply(chat_id: int, text: str) -> None:
        # The record of the press this reply answers (its correlation id, set by `on_callback`),
        # never the last one written: a background sweep or an earlier press that raised cannot
        # become the reply to an unrelated press (plan 16-58, B2-WR-03).
        confirm_record = (
            None if confirm_book is None else confirm_book.take_result(current_press_correlation())
        )
        if confirm_record is not None:
            message = render_shadow_message(
                ShadowMessageKind.CONFIRM_RESULT,
                mode=mode,
                now_utc=clock(),
                confirm_outcome=confirm_record.outcome,
                detail=confirm_record.detail,
                confirm_requested_at_utc=confirm_record.confirm_requested_at_utc,
                expiry_utc=confirm_record.plan_expiry_utc,
            )
        else:
            record = None if book is None else book.take_last_decision()
            outcome = _outcome_from_text(text) if record is None else record.outcome
            message = render_shadow_message(
                ShadowMessageKind.DECISION_RESULT,
                mode=mode,
                now_utc=clock(),
                outcome=outcome,
                detail=text,
                expiry_utc=None if record is None else record.expiry_utc,
            )
        try:
            await send_text(bot, chat_id, message)
        except TelegramSendError as exc:
            log.warning(
                "paper.shadow.reply_failed",
                kind=exc.failure.kind.value,
                detail=exc.failure.detail,
            )

    return reply


# --------------------------------------------------------------------------- #
# Restart: raw tokens do not survive, so pending approvals are expired (Pitfall P13).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RestartReport:
    """Approvals decided EXPIRED by the sweep, and those left PENDING.

    PostgreSQL allows ONE decided approval per plan, so the sibling of an expired approval
    cannot be decided; it stays PENDING with a token nobody holds any more, which makes it
    undecidable.
    """

    expired: list[Approval]
    left_pending: list[Approval]


def invalidate_pending_on_restart(stores: ShadowStores, now_utc: datetime) -> RestartReport:
    """Decide every PENDING approval EXPIRED (reason RUNTIME_RESTART) and journal it.

    The alternative, deterministic tokens that survive a restart, would be a design change that
    needs its own decision and is not taken: expiring fails closed with no new token design.
    """
    expired: list[Approval] = []
    left_pending: list[Approval] = []
    for pending in sorted(stores.list_pending_approvals(), key=lambda a: a.approval_id):
        decided = replace(
            pending,
            result=ApprovalResult.EXPIRED,
            status=ApprovalResult.EXPIRED,
            acted_at_utc=now_utc,
            actor_id=pending.actor_id or REASON_RUNTIME_RESTART,
        )
        try:
            stores.save_atomic(decided, None)
        except ApprovalAlreadyDecided:
            left_pending.append(pending)
            outcome = "LEFT_PENDING_SIBLING_DECIDED"
        else:
            expired.append(decided)
            outcome = ApprovalResult.EXPIRED.value
        stores.record_journal(
            JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix="shadow",
                    correlation_id=f"approval:{pending.approval_id}",
                    event_type=EVENT_PENDING_INVALIDATED,
                    entity_id=pending.approval_id,
                    step="restart",
                ),
                occurred_at_utc=now_utc,
                event_type=EVENT_PENDING_INVALIDATED,
                entity_type="Approval",
                entity_id=pending.approval_id,
                correlation_id=f"approval:{pending.approval_id}",
                signal_id=pending.signal_id,
                trade_plan_id=pending.trade_plan_id,
                approval_id=pending.approval_id,
                payload_json=_journal_payload(
                    {
                        "reason_code": REASON_RUNTIME_RESTART,
                        "outcome": outcome,
                        "previous_status": ApprovalResult.PENDING.value,
                        "mode": Mode.SHADOW.value,
                    }
                ),
            )
        )
    return RestartReport(expired=expired, left_pending=left_pending)


__all__ = [
    "DISPLAY_ZONE",
    "SHADOW_LABEL",
    "ConfirmCardFields",
    "ConfirmOutcome",
    "ConfirmRecord",
    "ConfirmResultSource",
    "DecisionRecord",
    "IssuedApprovals",
    "Mode",
    "ModeNotConstructible",
    "RestartReport",
    "EVENT_APPROVAL_EXPIRED",
    "EVENT_PENDING_INVALIDATED",
    "REASON_RUNTIME_RESTART",
    "ShadowApprovalBook",
    "ShadowDecisionOutcome",
    "ShadowMessageKind",
    "ShadowSendOutcome",
    "ShadowStores",
    "format_shadow_alert",
    "approval_id_for",
    "format_time_pair",
    "invalidate_pending_on_restart",
    "make_shadow_reply_fn",
    "render_shadow_message",
    "require_shadow",
    "send_shadow_alert",
]
