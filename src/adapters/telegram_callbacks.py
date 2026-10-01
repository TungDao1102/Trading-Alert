"""Telegram callback receiver — APPROVE/SKIP intake (Phase 8, plan 08-02).

Per D-02: the Telegram intake is the bound APPROVE/SKIP loop. Real
PTB polling receiver behind the adapter boundary, short-id mapping,
authorized-chat-first gate, journal-first receipt, 12-field message.
This module is the ONLY importer of `python-telegram-bot` for the
callback side (the send-side lives in `telegram_notify.py`).

Threat model (08-02 plan §threat_model):
  - T-8-10 (Elevation of privilege): authorized-chat check runs
    BEFORE any state lookup. Unknown chats rejected + journaled.
  - T-8-11 (Tampering): strict `APR:` / `SKP:` / `SIM:` / `SKIP:`
    plus 32-hex shape; 64-byte ceiling enforced at parse time.
  - T-8-12 (Repudiation): journal-first receipt — every callback
    receipt lands as a JournalEvent BEFORE resolve_callback runs.
  - T-8-13 (Information disclosure): raw token never crosses the
    adapter boundary into the journal payload; only short_id + chat
    context is recorded.

Purity contract:
  - `parse_callback_data`, `authorized_chat_gate`, and
    `dispatch_callback` are pure functions over stdlib + domain
    types. They take injected dependencies (`journal_event`,
    `lookup_by_short_id`, `save_atomic`) so the receiver never
    imports the Binance SDK, Pydantic, or SQLAlchemy.
  - `on_callback` and `build_application` are the only PTB-bound
    surfaces; they are not exercised by unit tests (the tests
    inject fake bot surfaces via the TelegramBot Protocol).

Atomic write contract (key-link from the plan):
  - The receiver persists the ShortIdMappingRow in the SAME
    database transaction as the Approval row transition. The
    injected `save_atomic` callable owns the transaction; the
    receiver never opens its own session. This keeps mapping +
    approval writes from drifting into two commits.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.adapters.telegram_notify import (
    APR_PREFIX,
    SIM_PREFIX,
    SKIP_PREFIX,
    SKP_PREFIX,
    TELEGRAM_CALLBACK_DATA_MAX_BYTES,
    TelegramBot,
    format_approve,
)
from src.approval.binding import ApprovalRejected, Callback
from src.approval.mapping import ShortIdMapping, make_short_id_mapping
from src.approval.replay import resolve_callback
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, RejectionReason
from src.domain.journal import JournalEvent, correlated_event_id

if TYPE_CHECKING:
    from telegram import InlineKeyboardMarkup, Update
    from telegram.ext import Application, ContextTypes

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants.
# --------------------------------------------------------------------------- #


# Length of the hex short id parsed from callback_data. Must match
# src/approval/mapping.py:SHORT_ID_LENGTH (32).
SHORT_ID_HEX_LEN: int = 32


# Callback-receipt journal event_type. The receipt is recorded BEFORE
# resolve_callback runs (D-02 journal-first ordering).
EVENT_TYPE_CALLBACK_RECEIVED: str = "CALLBACK_RECEIVED"

# Outcome-rendering journal event_type. Recorded AFTER the resolve
# succeeds or fails (success path: APPROVED / SKIPPED; failure path:
# rejected by the binding gate).
EVENT_TYPE_CALLBACK_RESOLVED: str = "CALLBACK_RESOLVED"
EVENT_TYPE_CALLBACK_REJECTED: str = "CALLBACK_REJECTED"


# --------------------------------------------------------------------------- #
# Parse surface — pure, no PTB imports.
# --------------------------------------------------------------------------- #


class CallbackKind(str, Enum):
    """What kind of callback the user pressed.

    APR / SKP are the live Phase-8 prefixes. SIM / SKIP remain the
    inert Phase-7 labels (D-02 wire-format stability) and resolve to
    SIMULATE_RECORDED so the receiver never advances approval state
    in response to a SIMULATE-only button.
    """

    APPROVE = "APPROVE"
    SKIP = "SKIP"
    SIMULATE_RECORDED = "SIMULATE_RECORDED"


def _callback_kind_to_action(kind: CallbackKind) -> ApprovalAction:
    if kind == CallbackKind.APPROVE:
        return ApprovalAction.APPROVE
    return ApprovalAction.SKIP_USER


@dataclass(frozen=True)
class ParsedCallback:
    """The strict parse result of a raw callback_data payload.

    `raw` is the original payload (untouched, for the journal
    receipt). `kind` is the canonical CallbackKind. `short_id` is
    the 32-hex-char sha256 prefix bound to the alert sender.

    The receiver rejects any callback_data that does not parse
    strictly (wrong prefix, wrong short_id shape, wrong byte
    length) BEFORE touching any approval state.
    """

    raw: str
    kind: CallbackKind
    short_id: str


def parse_callback_data(raw: str) -> ParsedCallback:
    """Strictly parse a Telegram `callback_data` payload (D-02).

    Accepts the four prefixes — `APR:`, `SKP:`, `SIM:`, `SKIP:` —
    followed by exactly 32 lowercase hex chars. Any other shape
    raises `ValueError` so the receiver can journal the malformed
    receipt and skip the chat gate.

    The 64-byte Telegram ceiling is enforced at parse time too: a
    payload longer than `TELEGRAM_CALLBACK_DATA_MAX_BYTES` raises
    `ValueError` even if its prefix is valid.
    """
    if not isinstance(raw, str) or raw == "":
        raise ValueError("callback_data must be a non-empty string")
    encoded_len = len(raw.encode("utf-8"))
    if encoded_len > TELEGRAM_CALLBACK_DATA_MAX_BYTES:
        raise ValueError(
            f"callback_data exceeds {TELEGRAM_CALLBACK_DATA_MAX_BYTES} bytes: {encoded_len} bytes"
        )
    if raw.startswith(APR_PREFIX):
        prefix = APR_PREFIX
        kind = CallbackKind.APPROVE
    elif raw.startswith(SKP_PREFIX):
        prefix = SKP_PREFIX
        kind = CallbackKind.SKIP
    elif raw.startswith(SIM_PREFIX):
        prefix = SIM_PREFIX
        kind = CallbackKind.SIMULATE_RECORDED
    elif raw.startswith(SKIP_PREFIX):
        prefix = SKIP_PREFIX
        kind = CallbackKind.SIMULATE_RECORDED
    else:
        raise ValueError(f"callback_data has no recognized prefix: {raw[:8]!r}...")
    short_id = raw[len(prefix) :]
    if len(short_id) != SHORT_ID_HEX_LEN:
        raise ValueError(
            f"short_id must be {SHORT_ID_HEX_LEN} hex chars, got {len(short_id)}: {short_id!r}"
        )
    if any(c not in "0123456789abcdef" for c in short_id):
        raise ValueError(f"short_id must be lowercase hex, got {short_id!r}")
    return ParsedCallback(raw=raw, kind=kind, short_id=short_id)


# --------------------------------------------------------------------------- #
# Authorized-chat gate — pure, runs BEFORE any state lookup.
# --------------------------------------------------------------------------- #


def authorized_chat_gate(*, callback_chat_id: int, authorized_chat_id: int) -> bool:
    """Return True iff the callback's chat id matches the authorized
    chat.

    Per D-02 + 08-01 D-01: the chat gate runs BEFORE any state
    lookup. An unknown chat must never touch the approval row. The
    receiver journals the rejection and returns; the approval state
    is left untouched.
    """
    if not isinstance(callback_chat_id, int):
        raise TypeError(f"callback_chat_id must be int, got {type(callback_chat_id).__name__}")
    if not isinstance(authorized_chat_id, int):
        raise TypeError(f"authorized_chat_id must be int, got {type(authorized_chat_id).__name__}")
    return callback_chat_id == authorized_chat_id


# --------------------------------------------------------------------------- #
# Dependency-injection callables (receiver never touches DB directly).
# --------------------------------------------------------------------------- #


# Look up the full (signal_id, trade_plan_id) pair by short id.
LookupByShortId = Callable[[str], tuple[str, str] | None]

# Look up the approval row by token hash (delegated to replay layer).
LookupByTokenHash = Callable[[str], Approval | None]

# Atomic write of approval + mapping in one transaction. The
# receiver calls this exactly once per PENDING->decided transition
# (replay-to-existing semantics from 08-01 D-01). The mapping row
# is optional for replay paths (already persisted on the first
# transition); the callable decides whether to insert.
SaveAtomic = Callable[[Approval, ShortIdMapping | None], None]

# Journal receipt + outcome journalers.
JournalReceipt = Callable[[JournalEvent], None]


# --------------------------------------------------------------------------- #
# Dispatch surface — pure orchestrator over the injected dependencies.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DispatchResult:
    """The outcome of dispatching a parsed callback.

    `ok` is True iff the approval transitioned (PENDING -> decided)
    AND the mapping row was persisted atomically. `kind` carries
    the callback kind for the renderer. `approval` is the resulting
    Approval (the existing row on replay, the newly-transitioned
    row on a fresh approval). `reason_code` carries the rejection
    reason on failure (None on success).
    """

    ok: bool
    kind: CallbackKind
    approval: Approval | None = None
    reason_code: RejectionReason | None = None


def dispatch_callback(
    parsed: ParsedCallback,
    *,
    callback_chat_id: int,
    authorized_chat_id: int,
    callback_at_utc: datetime,
    raw_token: str,
    correlation_id: str,
    journal_receipt: JournalReceipt,
    lookup_by_short_id: LookupByShortId,
    lookup_by_token_hash: LookupByTokenHash,
    save_atomic: SaveAtomic,
    now_utc: datetime | None = None,
    binding_context: dict[str, Any] | None = None,
) -> DispatchResult:
    """Dispatch a parsed callback to the approval core.

    Per D-02: the order is fixed and never reordered.
      1. Strict parse (already done by the caller — we receive a
         ParsedCallback).
      2. Authorized-chat gate — runs BEFORE any state lookup. A
         wrong chat is journaled and the function returns with
         `ok=False, reason_code=INVALIDATED`. No mapping lookup,
         no token hash, no replay.
      3. Journal the receipt (CALLBACK_RECEIVED) BEFORE the mapping
         lookup — at-least-once audit trail.
      4. Short-id mapping lookup. A missing short id is rejected
         with INVALIDATED (no replay against an unknown plan).
      5. Build the Callback payload and delegate to
         `src.approval.replay.resolve_callback`. The replay layer
         runs the binding gate and either returns the existing
         Approval (replay-to-existing) or transitions PENDING ->
         decided and calls `save_atomic` exactly once.
      6. The atomic write owns BOTH the ShortIdMappingRow (if a
         fresh transition) AND the Approval row transition in the
         same transaction. Replay paths pass `mapping=None` because
         the mapping row already exists from the first transition.
    """
    # Gate 2: authorized chat — runs first, before any state lookup.
    if not authorized_chat_gate(
        callback_chat_id=callback_chat_id,
        authorized_chat_id=authorized_chat_id,
    ):
        receipt = _build_chat_reject_receipt(
            parsed=parsed,
            callback_chat_id=callback_chat_id,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        journal_receipt(receipt)
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=False,
            reason_code=RejectionReason.INVALIDATED,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=RejectionReason.INVALIDATED,
        )

    # Gate 3: journal-first receipt (raw, BEFORE any state lookup).
    receipt = _build_callback_receipt(
        parsed=parsed,
        callback_chat_id=callback_chat_id,
        callback_at_utc=callback_at_utc,
        correlation_id=correlation_id,
    )
    journal_receipt(receipt)

    # SIMULATE-only buttons do NOT advance approval state (D-02 +
    # 08-01 D-11). Record the receipt, return early.
    if parsed.kind == CallbackKind.SIMULATE_RECORDED:
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=True,
            reason_code=None,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(ok=True, kind=parsed.kind)

    # Gate 4: short-id mapping lookup.
    mapping = lookup_by_short_id(parsed.short_id)
    if mapping is None:
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=False,
            reason_code=RejectionReason.INVALIDATED,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=RejectionReason.INVALIDATED,
        )
    signal_id, trade_plan_id = mapping

    # Gate 5: build the Callback payload and delegate to replay.
    if binding_context is None:
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=False,
            reason_code=RejectionReason.INVALIDATED,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=RejectionReason.INVALIDATED,
        )

    try:
        callback = Callback(
            raw_token=raw_token,
            chat_id=callback_chat_id,
            plan_hash=binding_context["plan_hash"],
            strategy_version=binding_context["strategy_version"],
            parameter_set_id=binding_context["parameter_set_id"],
            parameter_set_hash=binding_context["parameter_set_hash"],
            callback_at_utc=callback_at_utc,
            action=_callback_kind_to_action(parsed.kind),
        )
    except (ValueError, KeyError, TypeError):
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=False,
            reason_code=RejectionReason.INVALIDATED,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=RejectionReason.INVALIDATED,
        )

    # Build a wrapper save_atomic that includes the mapping row on
    # the first transition. The replay layer calls save(new_approval)
    # exactly once per PENDING -> decided transition; we wrap it so
    # the mapping insert happens in the SAME transaction.
    new_mapping = make_short_id_mapping(
        signal_id=signal_id,
        trade_plan_id=trade_plan_id,
        created_at_utc=callback_at_utc,
    )
    if new_mapping.short_id != parsed.short_id:
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=False,
            reason_code=RejectionReason.INVALIDATED,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=RejectionReason.INVALIDATED,
        )

    def _atomic_save(approval: Approval) -> None:
        # The mapping is persisted alongside the approval row
        # transition in the SAME database transaction. Replay paths
        # call save_atomic too — we pass mapping=None there so the
        # atomic-write callable can decide whether to insert (it
        # must not insert duplicates of an existing short_id).
        # We always pass the freshly-built mapping here because this
        # callable is only invoked from the PENDING->decided path,
        # not the replay path.
        save_atomic(approval, new_mapping)

    try:
        approval = resolve_callback(
            callback=callback,
            lookup_by_token_hash=lookup_by_token_hash,
            save=_atomic_save,
            authorized_chat_id=authorized_chat_id,
            expiry_utc=binding_context["expiry_utc"],
            approval_strategy_version=binding_context["strategy_version"],
            approval_parameter_set_id=binding_context["parameter_set_id"],
            approval_parameter_set_hash=binding_context["parameter_set_hash"],
            now_utc=now_utc if now_utc is not None else datetime.now(UTC),
        )
    except ApprovalRejected as exc:
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=False,
            reason_code=exc.reason_code,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=exc.reason_code,
        )
    except (ValueError, KeyError, TypeError):
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=False,
            reason_code=RejectionReason.INVALIDATED,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=RejectionReason.INVALIDATED,
        )
    except Exception:
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=False,
            reason_code=RejectionReason.INVALIDATED,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=RejectionReason.INVALIDATED,
        )

    _journal_outcome(
        journal_receipt,
        parsed=parsed,
        ok=True,
        reason_code=None,
        callback_at_utc=callback_at_utc,
        correlation_id=correlation_id,
    )
    return DispatchResult(ok=True, kind=parsed.kind, approval=approval)


# --------------------------------------------------------------------------- #
# Journal receipt builders — pure, no DB.
# --------------------------------------------------------------------------- #


def _build_callback_receipt(
    *,
    parsed: ParsedCallback,
    callback_chat_id: int,
    callback_at_utc: datetime,
    correlation_id: str,
) -> JournalEvent:
    """Build the journal receipt for a callback (D-02 journal-first)."""
    if callback_at_utc.tzinfo is None:
        raise ValueError("callback_at_utc must be UTC-aware")
    payload = {
        "chat_id": callback_chat_id,
        "callback_data": parsed.raw,
        "kind": parsed.kind.value,
        "short_id": parsed.short_id,
    }
    entity_id = f"short:{parsed.short_id}"
    return JournalEvent(
        # Pure function of the correlation (callback_query.id) and a fixed
        # step label: a Telegram redelivery writes the same id (D-10, C7).
        journal_event_id=correlated_event_id(
            prefix="cb",
            correlation_id=correlation_id,
            event_type=EVENT_TYPE_CALLBACK_RECEIVED,
            entity_id=entity_id,
            step="receipt",
        ),
        occurred_at_utc=callback_at_utc,
        event_type=EVENT_TYPE_CALLBACK_RECEIVED,
        entity_type="Approval",
        entity_id=entity_id,
        correlation_id=correlation_id,
        signal_id=None,
        trade_plan_id=None,
        approval_id=None,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


def _build_chat_reject_receipt(
    *,
    parsed: ParsedCallback,
    callback_chat_id: int,
    callback_at_utc: datetime,
    correlation_id: str,
) -> JournalEvent:
    """Build the journal receipt for an unknown-chat rejection.

    The chat gate rejects the callback BEFORE any state lookup, but
    the rejection is journaled as a CALLBACK_RECEIVED event with the
    `chat_gate_rejected=True` payload flag so the audit trail still
    captures the attempt (T-8-12 — repudiation mitigation).
    """
    if callback_at_utc.tzinfo is None:
        raise ValueError("callback_at_utc must be UTC-aware")
    payload = {
        "chat_id": callback_chat_id,
        "callback_data": parsed.raw,
        "kind": parsed.kind.value,
        "short_id": parsed.short_id,
        "chat_gate_rejected": True,
    }
    entity_id = f"short:{parsed.short_id}"
    return JournalEvent(
        journal_event_id=correlated_event_id(
            prefix="cb",
            correlation_id=correlation_id,
            event_type=EVENT_TYPE_CALLBACK_RECEIVED,
            entity_id=entity_id,
            step="chat_reject",
        ),
        occurred_at_utc=callback_at_utc,
        event_type=EVENT_TYPE_CALLBACK_RECEIVED,
        entity_type="Approval",
        entity_id=entity_id,
        correlation_id=correlation_id,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


def _journal_outcome(
    journal_receipt: JournalReceipt,
    *,
    parsed: ParsedCallback,
    ok: bool,
    reason_code: RejectionReason | None,
    callback_at_utc: datetime,
    correlation_id: str,
) -> None:
    event_type = EVENT_TYPE_CALLBACK_RESOLVED if ok else EVENT_TYPE_CALLBACK_REJECTED
    reason_label = reason_code.value if reason_code is not None else "NONE"
    entity_id = f"short:{parsed.short_id}"
    payload = {
        "short_id": parsed.short_id,
        "kind": parsed.kind.value,
        "ok": ok,
        "reason_code": reason_code.value if reason_code is not None else None,
        "correlation_id": correlation_id,
    }
    journal_receipt(
        JournalEvent(
            # The step encodes ok and reason_code, so a rejected first delivery
            # and a resolved redelivery are two different events (D-10).
            journal_event_id=correlated_event_id(
                prefix="cb",
                correlation_id=correlation_id,
                event_type=event_type,
                entity_id=entity_id,
                step=f"outcome:{ok}:{reason_label}",
            ),
            occurred_at_utc=callback_at_utc,
            event_type=event_type,
            entity_type="Approval",
            entity_id=entity_id,
            correlation_id=correlation_id,
            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
    )


# --------------------------------------------------------------------------- #
# PTB-bound surfaces — only used by the live polling loop.
# --------------------------------------------------------------------------- #


# Type alias for the dispatch call signature injected into the PTB
# handler. Tests can build a fake dispatcher that returns a known
# DispatchResult without going through the resolve_callback path.
DispatchCallable = Callable[..., DispatchResult]


async def on_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    authorized_chat_id: int,
    binding_context_resolver: Callable[[str], dict[str, Any] | None],
    dispatch: DispatchCallable,
    reply_text_fn: Callable[[int, str], Awaitable[None]] | None = None,
) -> DispatchResult:
    """PTB `CallbackQueryHandler` entry point.

    The handler:
      1. Calls `query.answer()` first to clear the Telegram client
         spinner — independent of any state lookup so the operator
         always sees feedback even on rejection.
      2. Strict-parses `query.data`.
      3. Calls `dispatch_callback` with all injected dependencies.
      4. Edits the original message via `reply_text_fn` (or, if
         None, falls back to a no-op) to render the outcome.

    The handler NEVER touches approval state directly. All state
    mutation goes through `dispatch_callback` -> `resolve_callback`.
    """
    query = update.callback_query
    if query is None:
        raise ValueError("update.callback_query must not be None")
    # Step 1: spinner clear (always — even on malformed input).
    await query.answer()
    if query.data is None or query.data == "":
        raise ValueError("callback query carries no data")
    if query.message is None:
        raise ValueError("callback query has no associated message")
    parsed = parse_callback_data(query.data)

    chat = update.effective_chat
    if chat is None:
        raise ValueError("update.effective_chat must not be None")
    callback_chat_id = int(chat.id)

    # Correlation comes from Telegram's callback_query.id, which is stable
    # across redelivery of the same callback (D-10, research C7, A10). A
    # missing id fails closed: without it a redelivery could not be told
    # apart from a fresh press. The wall clock is event time only.
    query_id = getattr(query, "id", None)
    if not isinstance(query_id, str) or query_id == "":
        raise ValueError("callback query carries no id")
    callback_at_utc = datetime.now(UTC)
    correlation_id = f"cbq:{query_id}"

    if not authorized_chat_gate(
        callback_chat_id=callback_chat_id,
        authorized_chat_id=authorized_chat_id,
    ):
        result = dispatch(
            parsed,
            callback_chat_id=callback_chat_id,
            authorized_chat_id=authorized_chat_id,
            callback_at_utc=callback_at_utc,
            raw_token="",
            correlation_id=correlation_id,
            binding_context=None,
        )

        if reply_text_fn is not None:
            chat_id = getattr(query.message, "chat_id", None)
            if chat_id is not None:
                await reply_text_fn(int(chat_id), "Rejected")

        return result

    binding = binding_context_resolver(parsed.short_id)
    raw_token = ""
    if binding is not None:
        raw_token = binding.get("raw_token", "")

    result = dispatch(
        parsed,
        callback_chat_id=callback_chat_id,
        authorized_chat_id=authorized_chat_id,
        callback_at_utc=callback_at_utc,
        raw_token=raw_token,
        correlation_id=correlation_id,
        binding_context=binding,
    )

    if reply_text_fn is not None:
        text = _render_outcome_text(result, parsed)
        # query.message is typed as Message | MaybeInaccessibleMessage;
        # the chat_id attribute is only on Message. Guard with getattr
        # so an inaccessible message (e.g. deleted) does not crash the
        # handler — the operator still sees the spinner clear.
        chat_id = getattr(query.message, "chat_id", None)
        if chat_id is not None:
            await reply_text_fn(int(chat_id), text)

    return result


def _render_outcome_text(result: DispatchResult, parsed: ParsedCallback) -> str:
    """Render the outcome text for a callback (best-effort, human-readable)."""
    if not result.ok:
        reason = result.reason_code.value if result.reason_code else "UNKNOWN"
        return f"Rejected ({reason}): {parsed.kind.value}"
    if result.approval is None:
        return f"Recorded: {parsed.kind.value}"
    return f"OK: {result.approval.status.value}"


def build_application(
    *,
    token: str,
    authorized_chat_id: int,
    binding_context_resolver: Callable[[str], dict[str, Any] | None],
    dispatch: DispatchCallable,
    reply_text_fn: Callable[[int, str], Awaitable[None]] | None = None,
) -> Application[Any, Any, Any, Any, Any, Any]:
    """Build a PTB `Application` wired with the approval-callback handler.

    This is the only function in the codebase that imports
    `telegram.ext.Application`. It MUST NOT be called from any
    unit test — tests exercise the pure `parse_callback_data`,
    `authorized_chat_gate`, and `dispatch_callback` surfaces
    instead, with injected fake dependencies.
    """
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN must be a non-empty string")

    from telegram.ext import ApplicationBuilder, CallbackQueryHandler

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> DispatchResult:
        return await on_callback(
            update,
            context,
            authorized_chat_id=authorized_chat_id,
            binding_context_resolver=binding_context_resolver,
            dispatch=dispatch,
            reply_text_fn=reply_text_fn,
        )

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CallbackQueryHandler(_handler))
    return app


# Re-export the renderer so the send-side paper-core can reuse it.
# format_approve is the canonical 12-field renderer; it lives in
# telegram_notify.py (PTB-free) and is exposed here for the
# approval-messaging path that needs to render the alert message.
__all__ = [
    "CallbackKind",
    "DispatchCallable",
    "DispatchResult",
    "EVENT_TYPE_CALLBACK_RECEIVED",
    "EVENT_TYPE_CALLBACK_REJECTED",
    "EVENT_TYPE_CALLBACK_RESOLVED",
    "JournalReceipt",
    "LookupByShortId",
    "LookupByTokenHash",
    "ParsedCallback",
    "SaveAtomic",
    "SHORT_ID_HEX_LEN",
    "TelegramBot",
    "authorized_chat_gate",
    "build_application",
    "dispatch_callback",
    "format_approve",
    "on_callback",
    "parse_callback_data",
]


# Re-export the InlineKeyboardMarkup type for the test surface
# via a lazy lookup so importing this module never requires
# `python-telegram-bot` (pure surfaces stay independently usable).
__all__ += ["InlineKeyboardMarkup"]


def __getattr__(name: str) -> Any:
    if name == "InlineKeyboardMarkup":
        from telegram import InlineKeyboardMarkup as _Markup

        return _Markup
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
