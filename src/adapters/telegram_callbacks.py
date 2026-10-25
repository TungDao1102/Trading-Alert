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

import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.adapters.telegram_notify import (
    APR_PREFIX,
    CNF_PREFIX,
    CXL_PREFIX,
    SIM_PREFIX,
    SKIP_PREFIX,
    SKP_PREFIX,
    TELEGRAM_CALLBACK_DATA_MAX_BYTES,
    TelegramBot,
    format_approve,
)
from src.approval.binding import ApprovalRejected, Callback
from src.approval.mapping import ShortIdMapping, make_short_id_mapping
from src.approval.reason_codes import (
    APPROVAL_STORE_FAILURE,
    CALLBACK_HANDLER_ERROR,
    CHAT_NOT_PRIVATE,
    USER_ID_UNAVAILABLE,
    USER_NOT_AUTHORIZED,
)
from src.approval.replay import ApprovalDecidedDifferently, resolve_callback
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason
from src.domain.journal import JournalEvent, correlated_event_id

if TYPE_CHECKING:
    from telegram import InlineKeyboardMarkup, Update
    from telegram.ext import Application, ContextTypes

log = logging.getLogger(__name__)

# The correlation id (`cbq:<callback query id>`) of the press `on_callback` is answering right
# now. The reply function reads it to pick up the record of THAT press (plan 16-58, B2-WR-03); it
# is set for the duration of one `on_callback` call and reset afterwards.
_PRESS_CORRELATION: ContextVar[str | None] = ContextVar("press_correlation_id", default=None)


def current_press_correlation() -> str | None:
    """The correlation id of the press being answered, or None outside `on_callback`."""
    return _PRESS_CORRELATION.get()


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

# Phase 23 (D-08): an exception raised inside the callback handler AFTER the gates. Journaled with
# the correlation id and the exception CLASS name only, never the message text.
EVENT_TYPE_CALLBACK_HANDLER_FAILED: str = "CALLBACK_HANDLER_FAILED"


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
    # SHADOW confirm step (Phase 16, plan 16-11, D041). These two never move an approval:
    # they are routed to the injected `confirm_handler`, not to `dispatch_callback`.
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"


def _callback_kind_to_action(kind: CallbackKind) -> ApprovalAction:
    if kind in (CallbackKind.CONFIRM, CallbackKind.CANCEL):
        # A confirm press must never be mistaken for an approval decision.
        raise ValueError(f"{kind.value} is not an approval action")
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

    Accepts the six prefixes — `APR:`, `SKP:`, `SIM:`, `SKIP:` and, for the SHADOW confirm
    step (plan 16-11), `CNF:` and `CXL:` — followed by exactly 32 lowercase hex chars. Any
    other shape raises `ValueError` so the receiver can journal the malformed receipt and skip
    the chat gate.

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
    elif raw.startswith(CNF_PREFIX):
        prefix = CNF_PREFIX
        kind = CallbackKind.CONFIRM
    elif raw.startswith(CXL_PREFIX):
        prefix = CXL_PREFIX
        kind = CallbackKind.CANCEL
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


@dataclass(frozen=True)
class CallbackPress:
    """What the SHADOW confirm layer is told about one button press (plan 16-11).

    Built by `on_callback` AFTER the authorized-chat gate and the Phase 23 user gate
    (`authorized_user_gate`: listed user, private chat). `from_user_id` is the Telegram user who
    pressed (`query.from_user.id`, None when Telegram gave none) and `message_id` the id of the
    message carrying the button. The confirm layer BINDS the confirm to the user that pressed
    APPROVE.
    """

    parsed: ParsedCallback
    chat_id: int
    authorized_chat_id: int
    from_user_id: int | None
    message_id: int | None
    callback_at_utc: datetime
    correlation_id: str


@dataclass(frozen=True)
class ConfirmReply:
    """The confirm handler's verdict on a CNF:/CXL: press: `ok` and the detail for the reply."""

    ok: bool
    text: str = ""


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


def _validate_authorized_user_ids(authorized_user_ids: object) -> None:
    """Raise `ValueError` unless the allow-list is a non-empty frozenset of real ints.

    Never allow-all (D-02): an empty set, a plain set or a bool/str member is a programming error
    and is refused at the entry point, before any decision. The members are never put in the
    message.
    """
    if not isinstance(authorized_user_ids, frozenset) or not authorized_user_ids:
        raise ValueError("authorized_user_ids must be a non-empty frozenset of int")
    for member in authorized_user_ids:
        if isinstance(member, bool) or not isinstance(member, int):
            raise ValueError("authorized_user_ids must contain only int user ids")


def authorized_user_gate(
    *,
    from_user_id: object,
    chat_type: object,
    authorized_user_ids: frozenset[int],
) -> str | None:
    """Return the plain refusal code of a press, or None when the press may go on (Phase 23).

    The second, independent gate after the chat gate (D-01: the two fail independently). The
    order is fixed: user id present, then chat type exactly "private", then membership in the
    required allow-list. A refusal happens BEFORE any short-id or token lookup. The chat type is
    compared with the plain string (`telegram.constants.ChatType.PRIVATE == "private"`), so this
    function stays free of any PTB import.
    """
    _validate_authorized_user_ids(authorized_user_ids)
    if isinstance(from_user_id, bool) or not isinstance(from_user_id, int):
        return USER_ID_UNAVAILABLE
    if not isinstance(chat_type, str) or chat_type != "private":
        return CHAT_NOT_PRIVATE
    if from_user_id not in authorized_user_ids:
        return USER_NOT_AUTHORIZED
    return None


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
    reason on failure (None on success): a `RejectionReason` member, or since Phase 23 a plain
    string from `src.approval.reason_codes` (orchestrator resolution 7: the enum stays at 21).

    `already_decided` (Phase 23, D-06, D-09) is True when the press changed nothing because the
    plan was already decided in the store: a replay to an existing decision, a lost race that
    resolved to the same decision, or a tap on the sibling button of a decided plan. It is derived
    from stored state (the save callable was not the one that wrote), never from a local guess,
    and it changes no journal row. A composer may answer "already decided" from it.
    """

    ok: bool
    kind: CallbackKind
    approval: Approval | None = None
    reason_code: RejectionReason | str | None = None
    already_decided: bool = False


def _reason_label(reason_code: RejectionReason | str | None) -> str | None:
    """The journal/render text of a reason code (enum -> value, plain string -> itself)."""
    if reason_code is None:
        return None
    if isinstance(reason_code, RejectionReason):
        return reason_code.value
    return reason_code


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
    from_user_id: int | None = None,
    chat_type: str | None = None,
    authorized_user_ids: frozenset[int] | None = None,
) -> DispatchResult:
    """Dispatch a parsed callback to the approval core.

    Phase 23 (D-01, D-02, D-03): right after the chat gate and before the receipt, a press is
    checked by `authorized_user_gate` when `authorized_user_ids` is given. `on_callback` always
    passes it (and refuses by itself first); only direct library callers omit it, which skips
    this step. `from_user_id` also becomes the `actor_id` of a decided approval.

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

    # Gate 2b (Phase 23): the user and chat-type gate, still BEFORE any state lookup.
    if authorized_user_ids is not None:
        user_refusal = authorized_user_gate(
            from_user_id=from_user_id,
            chat_type=chat_type,
            authorized_user_ids=authorized_user_ids,
        )
        if user_refusal is not None:
            journal_receipt(
                _build_user_reject_receipt(
                    parsed=parsed,
                    callback_chat_id=callback_chat_id,
                    from_user_id=from_user_id,
                    chat_type=chat_type,
                    reason=user_refusal,
                    callback_at_utc=callback_at_utc,
                    correlation_id=correlation_id,
                )
            )
            _journal_outcome(
                journal_receipt,
                parsed=parsed,
                ok=False,
                reason_code=user_refusal,
                callback_at_utc=callback_at_utc,
                correlation_id=correlation_id,
            )
            return DispatchResult(ok=False, kind=parsed.kind, reason_code=user_refusal)

    # Gate 3: journal-first receipt (raw, BEFORE any state lookup).
    receipt = _build_callback_receipt(
        parsed=parsed,
        callback_chat_id=callback_chat_id,
        callback_at_utc=callback_at_utc,
        correlation_id=correlation_id,
    )
    journal_receipt(receipt)

    # CONFIRM / CANCEL never enter the approval transitions (plan 16-11): fail closed if one
    # ever reaches this function, instead of reading it as a SKIP.
    if parsed.kind in (CallbackKind.CONFIRM, CallbackKind.CANCEL):
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
        # Set only after the write returned: a replay, or a lost race, never reaches this line.
        transitioned.append(True)

    transitioned: list[bool] = []
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
            actor_id=(
                str(from_user_id)
                if isinstance(from_user_id, int) and not isinstance(from_user_id, bool)
                else ""
            ),
        )
    except ApprovalDecidedDifferently as exc:
        # The plan was decided with the other outcome (the sibling button): journaled exactly
        # like any ApprovalRejected, and flagged from the STORED row (research Pitfall 7).
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
            approval=exc.existing,
            reason_code=exc.reason_code,
            already_decided=True,
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
    except Exception as exc:  # noqa: BLE001 - fail closed: nothing was approved
        # An infrastructure failure (a store or connection error) is not a domain rejection. Since
        # Phase 23 it has its own plain code, APPROVAL_STORE_FAILURE (it used to be INVALIDATED);
        # the class and the correlation id are logged so the cause is diagnosable; never the
        # message text, the token or the callback data (B2-WR-08).
        log.error(
            "telegram.callback.dispatch_failed: %s correlation_id=%s",
            type(exc).__name__,
            correlation_id,
        )
        _journal_outcome(
            journal_receipt,
            parsed=parsed,
            ok=False,
            reason_code=APPROVAL_STORE_FAILURE,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=APPROVAL_STORE_FAILURE,
        )

    _journal_outcome(
        journal_receipt,
        parsed=parsed,
        ok=True,
        reason_code=None,
        callback_at_utc=callback_at_utc,
        correlation_id=correlation_id,
    )
    return DispatchResult(
        ok=True, kind=parsed.kind, approval=approval, already_decided=not transitioned
    )


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


def _build_user_reject_receipt(
    *,
    parsed: ParsedCallback,
    callback_chat_id: int,
    from_user_id: int | None,
    chat_type: str | None,
    reason: str,
    callback_at_utc: datetime,
    correlation_id: str,
) -> JournalEvent:
    """Build the journal receipt for a refused user or chat type (Phase 23, D-01, D-02).

    Journaled as CALLBACK_RECEIVED with `user_gate_rejected=True` and the plain reason code, like
    the chat-gate receipt. Only the pressing actor's id is recorded, never the allow-list (T-23-03).
    """
    if callback_at_utc.tzinfo is None:
        raise ValueError("callback_at_utc must be UTC-aware")
    safe_user_id = (
        from_user_id
        if isinstance(from_user_id, int) and not isinstance(from_user_id, bool)
        else None
    )
    safe_chat_type = chat_type[:32] if isinstance(chat_type, str) else None
    payload = {
        "chat_id": callback_chat_id,
        "from_user_id": safe_user_id,
        "chat_type": safe_chat_type,
        "callback_data": parsed.raw,
        "kind": parsed.kind.value,
        "short_id": parsed.short_id,
        "user_gate_rejected": True,
        "reason": reason,
    }
    entity_id = f"short:{parsed.short_id}"
    return JournalEvent(
        journal_event_id=correlated_event_id(
            prefix="cb",
            correlation_id=correlation_id,
            event_type=EVENT_TYPE_CALLBACK_RECEIVED,
            entity_id=entity_id,
            step="user_reject",
        ),
        occurred_at_utc=callback_at_utc,
        event_type=EVENT_TYPE_CALLBACK_RECEIVED,
        entity_type="Approval",
        entity_id=entity_id,
        correlation_id=correlation_id,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


def _build_handler_failed_receipt(
    *,
    parsed: ParsedCallback,
    error_class: str,
    callback_at_utc: datetime,
    correlation_id: str,
) -> JournalEvent:
    """Build the journal event of an exception raised after the gates (Phase 23, D-08).

    The payload is the short id, the callback kind, the exception class name and the correlation
    id: no message text, no token and no callback data (B2-WR-08, T-23-22).
    """
    if callback_at_utc.tzinfo is None:
        raise ValueError("callback_at_utc must be UTC-aware")
    payload = {
        "short_id": parsed.short_id,
        "kind": parsed.kind.value,
        "error_class": error_class,
        "correlation_id": correlation_id,
    }
    entity_id = f"short:{parsed.short_id}"
    return JournalEvent(
        journal_event_id=correlated_event_id(
            prefix="cb",
            correlation_id=correlation_id,
            event_type=EVENT_TYPE_CALLBACK_HANDLER_FAILED,
            entity_id=entity_id,
            step="handler_error",
        ),
        occurred_at_utc=callback_at_utc,
        event_type=EVENT_TYPE_CALLBACK_HANDLER_FAILED,
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
    reason_code: RejectionReason | str | None,
    callback_at_utc: datetime,
    correlation_id: str,
) -> None:
    event_type = EVENT_TYPE_CALLBACK_RESOLVED if ok else EVENT_TYPE_CALLBACK_REJECTED
    reason_text = _reason_label(reason_code)
    reason_label = reason_text if reason_text is not None else "NONE"
    entity_id = f"short:{parsed.short_id}"
    payload = {
        "short_id": parsed.short_id,
        "kind": parsed.kind.value,
        "ok": ok,
        "reason_code": reason_text,
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
DispatchCallable = Callable[..., DispatchResult | Awaitable[DispatchResult]]


async def _dispatched(
    dispatch: DispatchCallable, parsed: ParsedCallback, **kwargs: Any
) -> DispatchResult:
    """Run `dispatch` and await its result when it is awaitable.

    A synchronous dispatcher (the default, pure `dispatch_callback`) is called inline. The SHADOW
    runtime (plan 16-31) passes an async wrapper that runs the synchronous dispatcher in a worker
    thread, so the blocking database writes of a press never run on the event loop.
    """
    result = dispatch(parsed, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


# SHADOW confirm hooks (plan 16-11). `ConfirmHandler` serves CNF:/CXL: presses; `ApprovedHandler`
# runs after a press reached APPROVED and returns True when it delivered its own reply (the
# confirmation card), so the generic outcome reply is skipped.
ConfirmHandler = Callable[[CallbackPress], Awaitable[ConfirmReply]]
ApprovedHandler = Callable[[CallbackPress, DispatchResult], Awaitable[bool]]

# Phase 23 (D-06): runs after the reply of every press that passed both gates (APR, SKP, CNF,
# CXL). A composer builds it on `finalize_decided_message` to make the decided message final and
# remove its keyboard. A failure in it is logged by class name and changes nothing.
FinalizeHook = Callable[[CallbackPress, DispatchResult], Awaitable[None]]


async def _run_finalize_hook(
    finalize_message: FinalizeHook | None,
    press: CallbackPress,
    result: DispatchResult,
) -> None:
    """Await the finalize hook of a press; never let it raise (the decision is already made)."""
    if finalize_message is None:
        return
    try:
        await finalize_message(press, result)
    except Exception as exc:  # noqa: BLE001 - the press is decided; a hook failure changes nothing
        log.error(
            "telegram.callback.finalize_failed: %s correlation_id=%s",
            type(exc).__name__,
            press.correlation_id,
        )


async def answer_callback_safely(query: Any) -> None:
    """Clear the Telegram spinner once, without text, and never let a failure escape.

    `answerCallbackQuery` is cosmetic: the callback is processed through the gates whether or
    not it succeeds. A failure (an expired query, a network fault, a rate limit) is logged by
    exception class only, never retried, and never raised.

    Phase 23 (D-08): a callback that waited out a downtime raises `BadRequest: Query is too old
    ...`. That is expected after a restart, so it is logged at debug level; everything else keeps
    the warning. The class is matched by name, so this module still imports no PTB type, and the
    exception text is only compared, never logged.
    """
    try:
        await query.answer()
    except Exception as exc:  # noqa: BLE001 - cosmetic call; the press is still processed
        if type(exc).__name__ == "BadRequest" and "query is too old" in str(exc).lower():
            log.debug("telegram.callback.answer_expired: %s", type(exc).__name__)
        else:
            log.warning("telegram.callback.answer_failed: %s", type(exc).__name__)


def make_application_error_handler() -> Callable[[object, Any], Coroutine[Any, Any, None]]:
    """The PTB application error handler (Phase 23, D-08): log the class and the press only.

    Before this the application had none: PTB logged the traceback of every exception that
    escaped a callback, message text included. The handler logs ONE line with the exception class
    name and, when the update is a callback query, its correlation id (`cbq:<id>`). It never logs
    the exception text, the callback data or the token, never raises and changes no approval state.
    """

    async def _on_application_error(update: object, context: Any) -> None:
        try:
            error = getattr(context, "error", None)
            query = getattr(update, "callback_query", None)
            query_id = getattr(query, "id", None)
            correlation = f"cbq:{query_id}" if isinstance(query_id, str) and query_id else None
            log.error(
                "telegram.application.error: %s correlation_id=%s",
                type(error).__name__,
                correlation,
            )
        except Exception:  # noqa: BLE001 - an error handler must never raise
            return

    return _on_application_error


async def on_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    authorized_chat_id: int,
    authorized_user_ids: frozenset[int],
    binding_context_resolver: Callable[[str], dict[str, Any] | None],
    dispatch: DispatchCallable,
    reply_text_fn: Callable[[int, str], Awaitable[None]] | None = None,
    confirm_handler: ConfirmHandler | None = None,
    approved_handler: ApprovedHandler | None = None,
    finalize_message: FinalizeHook | None = None,
    error_journal: JournalReceipt | None = None,
    clock: Callable[[], datetime] | None = None,
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

    SHADOW confirm step (plan 16-11, all optional, default None keeps the behaviour above):
    `confirm_handler` serves `CNF:` / `CXL:` presses after the chat gate (they never enter
    `dispatch_callback`; without a handler they are refused); `approved_handler` runs after a
    press reached APPROVED; `clock` replaces the wall clock for the press time (tests).

    Phase 23 (D-01, D-02): `authorized_user_ids` is REQUIRED (no default, never allow-all; an
    empty set or a non-int member is a `ValueError` here). After the chat gate and before any
    lookup the press must come from a listed user in a chat of type "private"; otherwise it is
    refused, journaled with only the presser's id, and answered with the generic "Rejected".

    Phase 23 (D-06): `finalize_message`, when given, is awaited after the reply of every press
    that passed both gates (never for a refused press); an error in it is logged by class name
    and changes nothing.

    Phase 23 (D-08): an exception raised after the gates is caught here. It is logged by class
    name and correlation id, journaled as `CALLBACK_HANDLER_FAILED` when `error_journal` is given
    (a failing journal is logged and swallowed), and the authorized chat gets one neutral text.
    The result is `ok=False` with `CALLBACK_HANDLER_ERROR`. `CancelledError` still propagates, and
    a malformed update still raises `ValueError` before any correlation exists.
    """
    _validate_authorized_user_ids(authorized_user_ids)
    query = update.callback_query
    if query is None:
        raise ValueError("update.callback_query must not be None")
    # Step 1: spinner clear (always — even on malformed input). A failure of this purely
    # cosmetic call never stops the press from being parsed and dispatched through the gates.
    await answer_callback_safely(query)
    if query.data is None or query.data == "":
        raise ValueError("callback query carries no data")
    if query.message is None:
        raise ValueError("callback query has no associated message")
    parsed = parse_callback_data(query.data)

    chat = update.effective_chat
    if chat is None:
        raise ValueError("update.effective_chat must not be None")
    callback_chat_id = int(chat.id)
    chat_type = getattr(chat, "type", None)

    # Correlation comes from Telegram's callback_query.id, which is stable
    # across redelivery of the same callback (D-10, research C7, A10). A
    # missing id fails closed: without it a redelivery could not be told
    # apart from a fresh press. The wall clock is event time only.
    query_id = getattr(query, "id", None)
    if not isinstance(query_id, str) or query_id == "":
        raise ValueError("callback query carries no id")
    callback_at_utc = datetime.now(UTC) if clock is None else clock()
    correlation_id = f"cbq:{query_id}"

    token = _PRESS_CORRELATION.set(correlation_id)
    try:
        return await _answer_press(
            query,
            parsed,
            callback_chat_id=callback_chat_id,
            authorized_chat_id=authorized_chat_id,
            authorized_user_ids=authorized_user_ids,
            chat_type=chat_type if isinstance(chat_type, str) else None,
            binding_context_resolver=binding_context_resolver,
            dispatch=dispatch,
            reply_text_fn=reply_text_fn,
            confirm_handler=confirm_handler,
            approved_handler=approved_handler,
            finalize_message=finalize_message,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
    except Exception as exc:  # noqa: BLE001 - D-08: journaled, answered neutrally, never raised
        return await _handle_press_failure(
            exc,
            parsed=parsed,
            callback_chat_id=callback_chat_id,
            authorized_chat_id=authorized_chat_id,
            reply_text_fn=reply_text_fn,
            error_journal=error_journal,
            callback_at_utc=callback_at_utc,
            correlation_id=correlation_id,
        )
    finally:
        _PRESS_CORRELATION.reset(token)


async def _handle_press_failure(
    exc: Exception,
    *,
    parsed: ParsedCallback,
    callback_chat_id: int,
    authorized_chat_id: int,
    reply_text_fn: Callable[[int, str], Awaitable[None]] | None,
    error_journal: JournalReceipt | None,
    callback_at_utc: datetime,
    correlation_id: str,
) -> DispatchResult:
    """Log, journal and answer an exception raised after the gates (Phase 23, D-08).

    Only the exception class name and the correlation id leave this function (log, journal and
    reply): never the exception text, a token or callback data (B2-WR-08, T-23-22).
    """
    error_class = type(exc).__name__
    log.error("telegram.callback.handler_failed: %s correlation_id=%s", error_class, correlation_id)
    if error_journal is not None:
        try:
            error_journal(
                _build_handler_failed_receipt(
                    parsed=parsed,
                    error_class=error_class,
                    callback_at_utc=callback_at_utc,
                    correlation_id=correlation_id,
                )
            )
        except Exception as journal_exc:  # noqa: BLE001 - the neutral answer still goes out
            log.error(
                "telegram.callback.handler_failed_journal_failed: %s correlation_id=%s",
                type(journal_exc).__name__,
                correlation_id,
            )
    if reply_text_fn is not None and callback_chat_id == authorized_chat_id:
        try:
            await reply_text_fn(
                callback_chat_id,
                f"An internal error stopped this tap (reference {correlation_id}). "
                "Do not tap again; check the journal.",
            )
        except Exception as reply_exc:  # noqa: BLE001 - nothing more can be done for this press
            log.error(
                "telegram.callback.handler_failed_reply_failed: %s correlation_id=%s",
                type(reply_exc).__name__,
                correlation_id,
            )
    return DispatchResult(ok=False, kind=parsed.kind, reason_code=CALLBACK_HANDLER_ERROR)


async def _answer_press(
    query: Any,
    parsed: ParsedCallback,
    *,
    callback_chat_id: int,
    authorized_chat_id: int,
    authorized_user_ids: frozenset[int],
    chat_type: str | None,
    binding_context_resolver: Callable[[str], dict[str, Any] | None],
    dispatch: DispatchCallable,
    reply_text_fn: Callable[[int, str], Awaitable[None]] | None,
    confirm_handler: ConfirmHandler | None,
    approved_handler: ApprovedHandler | None,
    finalize_message: FinalizeHook | None,
    callback_at_utc: datetime,
    correlation_id: str,
) -> DispatchResult:
    """The gates, the dispatch and the reply of one press (run by `on_callback`)."""
    if not authorized_chat_gate(
        callback_chat_id=callback_chat_id,
        authorized_chat_id=authorized_chat_id,
    ):
        result = await _dispatched(
            dispatch,
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

    from_user = getattr(query, "from_user", None)
    from_user_id = getattr(from_user, "id", None)
    typed_user_id = (
        from_user_id
        if isinstance(from_user_id, int) and not isinstance(from_user_id, bool)
        else None
    )

    # Phase 23 (D-01, D-02): the user and chat-type gate. It runs before CallbackPress, the
    # confirm handler and any lookup. `on_callback` builds its own refusal, so the gate holds even
    # if an injected dispatcher ignores the new keywords (T-23-05).
    user_refusal = authorized_user_gate(
        from_user_id=from_user_id,
        chat_type=chat_type,
        authorized_user_ids=authorized_user_ids,
    )
    if user_refusal is not None:
        await _dispatched(
            dispatch,
            parsed,
            callback_chat_id=callback_chat_id,
            authorized_chat_id=authorized_chat_id,
            callback_at_utc=callback_at_utc,
            raw_token="",
            correlation_id=correlation_id,
            binding_context=None,
            from_user_id=typed_user_id,
            chat_type=chat_type,
            authorized_user_ids=authorized_user_ids,
        )

        if reply_text_fn is not None:
            refused_chat_id = getattr(query.message, "chat_id", None)
            if refused_chat_id is not None:
                await reply_text_fn(int(refused_chat_id), "Rejected")

        return DispatchResult(ok=False, kind=parsed.kind, reason_code=user_refusal)

    message_id = getattr(query.message, "message_id", None)
    press = CallbackPress(
        parsed=parsed,
        chat_id=callback_chat_id,
        authorized_chat_id=authorized_chat_id,
        from_user_id=typed_user_id,
        message_id=message_id if isinstance(message_id, int) else None,
        callback_at_utc=callback_at_utc,
        correlation_id=correlation_id,
    )

    if parsed.kind in (CallbackKind.CONFIRM, CallbackKind.CANCEL):
        if confirm_handler is None:
            raise ValueError("a confirm callback needs a confirm_handler")
        reply = await confirm_handler(press)
        if reply_text_fn is not None:
            confirm_chat_id = getattr(query.message, "chat_id", None)
            if confirm_chat_id is not None:
                await reply_text_fn(int(confirm_chat_id), reply.text)
        confirm_result = DispatchResult(ok=reply.ok, kind=parsed.kind)
        await _run_finalize_hook(finalize_message, press, confirm_result)
        return confirm_result

    binding = binding_context_resolver(parsed.short_id)
    raw_token = ""
    if binding is not None:
        raw_token = binding.get("raw_token", "")

    result = await _dispatched(
        dispatch,
        parsed,
        callback_chat_id=callback_chat_id,
        authorized_chat_id=authorized_chat_id,
        callback_at_utc=callback_at_utc,
        raw_token=raw_token,
        correlation_id=correlation_id,
        binding_context=binding,
        from_user_id=typed_user_id,
        chat_type=chat_type,
        authorized_user_ids=authorized_user_ids,
    )

    handled = False
    if (
        approved_handler is not None
        and parsed.kind is CallbackKind.APPROVE
        and result.ok
        and result.approval is not None
        and result.approval.status == ApprovalResult.APPROVED
    ):
        handled = await approved_handler(press, result)

    if reply_text_fn is not None and not handled:
        text = _render_outcome_text(result, parsed)
        # query.message is typed as Message | MaybeInaccessibleMessage;
        # the chat_id attribute is only on Message. Guard with getattr
        # so an inaccessible message (e.g. deleted) does not crash the
        # handler — the operator still sees the spinner clear.
        chat_id = getattr(query.message, "chat_id", None)
        if chat_id is not None:
            await reply_text_fn(int(chat_id), text)

    await _run_finalize_hook(finalize_message, press, result)
    return result


def _render_outcome_text(result: DispatchResult, parsed: ParsedCallback) -> str:
    """Render the outcome text for a callback (best-effort, human-readable)."""
    if not result.ok:
        reason = _reason_label(result.reason_code) or "UNKNOWN"
        return f"Rejected ({reason}): {parsed.kind.value}"
    if result.approval is None:
        return f"Recorded: {parsed.kind.value}"
    return f"OK: {result.approval.status.value}"


def build_application(
    *,
    token: str,
    authorized_chat_id: int,
    authorized_user_ids: frozenset[int],
    binding_context_resolver: Callable[[str], dict[str, Any] | None],
    dispatch: DispatchCallable,
    reply_text_fn: Callable[[int, str], Awaitable[None]] | None = None,
    confirm_handler: ConfirmHandler | None = None,
    approved_handler: ApprovedHandler | None = None,
    finalize_message: FinalizeHook | None = None,
    error_journal: JournalReceipt | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Application[Any, Any, Any, Any, Any, Any]:
    """Build a PTB `Application` wired with the approval-callback handler.

    The three optional hooks are the SHADOW confirm step of plan 16-11 (passed through to
    `on_callback` unchanged); left at None the behaviour is exactly the earlier one.

    This is the only function in the codebase that imports
    `telegram.ext.Application`. It MUST NOT be called from any
    unit test — tests exercise the pure `parse_callback_data`,
    `authorized_chat_gate`, and `dispatch_callback` surfaces
    instead, with injected fake dependencies.
    """
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN must be a non-empty string")
    _validate_authorized_user_ids(authorized_user_ids)

    from telegram.ext import ApplicationBuilder, CallbackQueryHandler

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> DispatchResult:
        return await on_callback(
            update,
            context,
            authorized_chat_id=authorized_chat_id,
            authorized_user_ids=authorized_user_ids,
            binding_context_resolver=binding_context_resolver,
            dispatch=dispatch,
            reply_text_fn=reply_text_fn,
            confirm_handler=confirm_handler,
            approved_handler=approved_handler,
            finalize_message=finalize_message,
            error_journal=error_journal,
            clock=clock,
        )

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CallbackQueryHandler(_handler))
    app.add_error_handler(make_application_error_handler())
    return app


# Re-export the renderer so the send-side paper-core can reuse it.
# format_approve is the canonical 12-field renderer; it lives in
# telegram_notify.py (PTB-free) and is exposed here for the
# approval-messaging path that needs to render the alert message.
__all__ = [
    "ApprovedHandler",
    "CallbackKind",
    "CallbackPress",
    "ConfirmHandler",
    "ConfirmReply",
    "DispatchCallable",
    "DispatchResult",
    "EVENT_TYPE_CALLBACK_HANDLER_FAILED",
    "EVENT_TYPE_CALLBACK_RECEIVED",
    "EVENT_TYPE_CALLBACK_REJECTED",
    "EVENT_TYPE_CALLBACK_RESOLVED",
    "FinalizeHook",
    "JournalReceipt",
    "LookupByShortId",
    "LookupByTokenHash",
    "ParsedCallback",
    "SaveAtomic",
    "SHORT_ID_HEX_LEN",
    "TelegramBot",
    "answer_callback_safely",
    "authorized_chat_gate",
    "authorized_user_gate",
    "build_application",
    "current_press_correlation",
    "dispatch_callback",
    "format_approve",
    "make_application_error_handler",
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
