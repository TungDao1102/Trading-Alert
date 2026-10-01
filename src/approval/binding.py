"""Approval binding — callback payload + fixed-order gate (Phase 8, plan 08-01).

Per D-01: the gate order is fixed and never reordered. A callback is
checked in this order:

  1. chat-id — the authorized chat gate runs first, before any state
     lookup. A wrong chat must never touch the approval row.
  2. expiry — now_utc >= expiry_utc is expired (boundary inclusive).
     One second before expiry is still approvable.
  3. plan-hash — the plan must match the hash bound to the approval.
     A mismatch means the plan was rebuilt or replaced (STALE_SETUP).
  4. version/parameter-set — strategy_version + parameter_set_id +
     parameter_set_hash must all match. A mismatch means the strategy
     was rebuilt (INVALIDATED).
  5. token-hash — the raw token must hash to the approval's stored
     hash. A wrong token is rejected (INVALIDATED).

The module is dependency-free: stdlib + `src/domain/enums.py` only.
No Telegram, no Binance SDK, no SQLAlchemy, no Pydantic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason

if TYPE_CHECKING:
    from src.domain.approval import Approval


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive datetimes loudly (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


@dataclass(frozen=True)
class Callback:
    """The untrusted callback payload from Telegram.

    `raw_token` is the one-time secret bound to the approval. It is
    NEVER persisted or logged — only the SHA-256 hash form lives on
    the Approval row. The remaining fields carry the plan identity
    tuple and the chat authorization.

    `action` carries the human's decision from the pressed button
    (APPROVE vs SKIP_*). CR-01: the pressed button must determine the
    outcome — the resolver maps the callback's action, not the stored
    row's action, and rejects a stored/callback mismatch explicitly.
    `None` preserves backward compatibility for callers that have not
    yet threaded the button kind through (they fall back to the stored
    row's action).

    All fields are validated non-empty strings / ints / UTC-aware
    datetimes. The chat gate runs before any state lookup (D-01).
    """

    raw_token: str
    chat_id: int
    plan_hash: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    callback_at_utc: datetime
    action: ApprovalAction | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.raw_token, str) or self.raw_token == "":
            raise ValueError("raw_token must be a non-empty string")
        if not isinstance(self.chat_id, int):
            raise TypeError(f"chat_id must be int, got {type(self.chat_id).__name__}")
        for fname in (
            "plan_hash",
            "strategy_version",
            "parameter_set_id",
            "parameter_set_hash",
        ):
            value = getattr(self, fname)
            if not isinstance(value, str) or value == "":
                raise ValueError(f"{fname} must be a non-empty string")
        if not isinstance(self.plan_hash, str) or len(self.plan_hash) != 64:
            raise ValueError("plan_hash must be a 64-char string")
        if not isinstance(self.parameter_set_hash, str) or len(self.parameter_set_hash) != 64:
            raise ValueError("parameter_set_hash must be a 64-char string")
        _require_utc_aware(self.callback_at_utc, "callback_at_utc")
        if self.action is not None and not isinstance(self.action, ApprovalAction):
            raise TypeError(f"action must be ApprovalAction, got {type(self.action).__name__}")


@dataclass(frozen=True)
class BindingCheck:
    """The result of running `check_binding_full`.

    `ok` is True iff every gate passed. `reason_code` carries the
    canonical RejectionReason on failure (APPROVAL_EXPIRED,
    STALE_SETUP, or INVALIDATED).
    """

    ok: bool
    reason_code: RejectionReason | None = None


class ApprovalRejected(Exception):
    """Raised when a callback fails the binding gate.

    Carries the canonical RejectionReason. The caller (replay.py)
    catches this and surfaces the reason code to the journal / log.
    """

    def __init__(self, reason_code: RejectionReason, message: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code.value)


def action_to_result(action: ApprovalAction) -> ApprovalResult:
    """Map an ApprovalAction to the resulting ApprovalResult.

    Per D-11: APPROVE -> APPROVED, SKIP_USER/SKIP_BUSY/CANCEL -> SKIPPED.
    SIMULATE does not advance the approval state (07-04: SIMULATE is a
    notify-only path) and is treated as PENDING here — the replay
    layer never sees SIMULATE callbacks because the Telegram intake
    (08-02) routes them to the notify path, not the replay path.
    """
    if action == ApprovalAction.APPROVE:
        return ApprovalResult.APPROVED
    if action in (
        ApprovalAction.SKIP_USER,
        ApprovalAction.SKIP_BUSY,
        ApprovalAction.CANCEL,
    ):
        return ApprovalResult.SKIPPED
    return ApprovalResult.PENDING


def check_binding_identity(
    *,
    callback: Callback,
    approval: Approval,
    authorized_chat_id: int,
    approval_strategy_version: str,
    approval_parameter_set_id: str,
    approval_parameter_set_hash: str,
) -> BindingCheck:
    """Run the identity gates of `check_binding_full` WITHOUT the expiry gate (D-16).

    Order is fixed: chat-id -> plan-hash -> version/parameter-set -> token-hash. The
    execution manager runs this first so a stored outcome is only ever revealed to a
    caller that proves it is the approved caller, and only then looks the outcome up
    BEFORE the expiry gate (a replay of an already-executed plan after its expiry must
    return the stored outcome, not APPROVAL_EXPIRED).

    It never looks at an expiry: an expired approval passes here and is rejected by
    `check_binding_full`, which stays unchanged.
    """
    from src.approval.tokens import verify_token_hash

    # Gate 1: chat-id (runs first, before any state lookup).
    if callback.chat_id != authorized_chat_id:
        return BindingCheck(ok=False, reason_code=RejectionReason.INVALIDATED)

    # Gate 2: plan-hash.
    if callback.plan_hash != approval.request_hash:
        return BindingCheck(ok=False, reason_code=RejectionReason.STALE_SETUP)

    # Gate 3: version/parameter-set.
    if (
        callback.strategy_version != approval_strategy_version
        or callback.parameter_set_id != approval_parameter_set_id
        or callback.parameter_set_hash != approval_parameter_set_hash
    ):
        return BindingCheck(ok=False, reason_code=RejectionReason.INVALIDATED)

    # Gate 4: token-hash.
    if not verify_token_hash(callback.raw_token, approval.approval_token_hash):
        return BindingCheck(ok=False, reason_code=RejectionReason.INVALIDATED)

    return BindingCheck(ok=True, reason_code=None)


def check_binding_full(
    *,
    callback: Callback,
    approval: Approval,
    authorized_chat_id: int,
    now_utc: datetime,
    expiry_utc: datetime,
    approval_strategy_version: str,
    approval_parameter_set_id: str,
    approval_parameter_set_hash: str,
) -> BindingCheck:
    """Run the fixed-order gate with full identity tuple (D-01).

    Gate order is fixed and never reordered:
      1. chat-id — wrong chat rejected before any state lookup.
      2. expiry — now_utc >= expiry_utc is expired (boundary inclusive).
      3. plan-hash — mismatch is STALE_SETUP.
      4. version/parameter-set — mismatch is INVALIDATED.
      5. token-hash — mismatch is INVALIDATED (wrong token).

    Args:
        callback: The Telegram callback payload.
        approval: The approval row being acted on.
        authorized_chat_id: The chat id authorized for this account.
            (Tests may inject a different value to test the chat gate.)
        now_utc: The current UTC-aware datetime.
        expiry_utc: The approval's expiry (from the parent TradePlan).
        approval_strategy_version: The strategy version on the parent.
        approval_parameter_set_id: The parameter set id on the parent.
        approval_parameter_set_hash: The parameter set hash on the parent.
    """
    from src.approval.tokens import verify_token_hash

    _require_utc_aware(now_utc, "now_utc")
    _require_utc_aware(expiry_utc, "expiry_utc")

    # Gate 1: chat-id (runs first, before any state lookup).
    if callback.chat_id != authorized_chat_id:
        return BindingCheck(ok=False, reason_code=RejectionReason.INVALIDATED)

    # Gate 2: expiry (boundary inclusive — now_utc >= expiry_utc is expired).
    if now_utc >= expiry_utc:
        return BindingCheck(ok=False, reason_code=RejectionReason.APPROVAL_EXPIRED)

    # Gate 3: plan-hash.
    if callback.plan_hash != approval.request_hash:
        return BindingCheck(ok=False, reason_code=RejectionReason.STALE_SETUP)

    # Gate 4: version/parameter-set.
    if (
        callback.strategy_version != approval_strategy_version
        or callback.parameter_set_id != approval_parameter_set_id
        or callback.parameter_set_hash != approval_parameter_set_hash
    ):
        return BindingCheck(ok=False, reason_code=RejectionReason.INVALIDATED)

    # Gate 5: token-hash.
    expected_hash = approval.approval_token_hash
    if not verify_token_hash(callback.raw_token, expected_hash):
        return BindingCheck(ok=False, reason_code=RejectionReason.INVALIDATED)

    return BindingCheck(ok=True, reason_code=None)


__all__ = [
    "Callback",
    "BindingCheck",
    "ApprovalRejected",
    "check_binding_full",
    "check_binding_identity",
    "action_to_result",
]
