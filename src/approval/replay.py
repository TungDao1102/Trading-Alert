"""Approval replay — replay-to-existing resolution (Phase 8, plan 08-01).

Per D-01: a human pressing APPROVE once transitions exactly one PENDING
approval to APPROVED with acted_at_utc set. Replaying the same callback
4 more times returns the existing Approval unchanged with zero new
transitions (5x = 1 transition). The replay layer is the at-least-once
handler for Telegram callbacks — the Telegram intake (08-02) calls
resolve_callback for every callback, and the same callback may arrive
multiple times due to network retries.

The module is dependency-free: stdlib + `src/domain/*` + sibling
modules (`tokens`, `binding`) only. No Telegram, no Binance SDK, no
SQLAlchemy, no Pydantic.

The replay layer looks up the approval by token hash (the idempotency
key), runs the fixed-order binding gate, and either:
  - returns the existing Approval untouched (replay of a decided
    approval), or
  - performs exactly one transition (PENDING -> APPROVED/SKIPPED),
    saves it, and returns the new Approval.
"""

from __future__ import annotations

import threading as _threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

from src.approval.binding import (
    ApprovalRejected,
    Callback,
    action_to_result,
    check_binding_full,
)
from src.approval.tokens import token_hash_of
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason

if TYPE_CHECKING:
    from src.domain.approval import Approval


# Type aliases for the lookup and save callbacks (D-01 dependency
# injection — the replay layer never touches the DB directly).
LookupByTokenHash = Callable[[str], "Approval | None"]
SaveApproval = Callable[["Approval"], None]


class ApprovalAlreadyDecided(Exception):
    """A conditional decision lost a race: the approval was decided by someone else.

    Raised by any store whose conditional write (UPDATE ... WHERE status = 'PENDING',
    or a one-decision-per-plan uniqueness arbiter) found the approval already decided
    (Phase 17 D-17, research C15). `existing` is the STORED approval, so the replay
    layer resolves to the persisted decision and never returns a locally computed one.
    """

    def __init__(self, existing: Approval) -> None:
        super().__init__("approval already decided")
        self.existing = existing


# Per-token in-process locks: two concurrent `resolve_callback` calls
# for the same token hash serialize on the token's lock so only one
# performs the PENDING->decided transition. This is a latency optimization
# only: correctness comes from the store's conditional write
# (UPDATE ... WHERE status='PENDING'), whose lost race surfaces as
# `ApprovalAlreadyDecided` and resolves to the stored approval (D-17).
_TOKEN_LOCKS: dict[str, _threading.Lock] = {}
_TOKEN_LOCKS_GUARD = _threading.Lock()


def _lock_for_token(token_hash: str) -> _threading.Lock:
    with _TOKEN_LOCKS_GUARD:
        lock = _TOKEN_LOCKS.get(token_hash)
        if lock is None:
            lock = _threading.Lock()
            _TOKEN_LOCKS[token_hash] = lock
        return lock


# The approvals.actor_id column width (src/persistence).
_ACTOR_ID_MAX_LENGTH = 64


def resolve_callback(
    callback: Callback,
    lookup_by_token_hash: LookupByTokenHash,
    save: SaveApproval,
    *,
    authorized_chat_id: int,
    expiry_utc: datetime,
    approval_strategy_version: str,
    approval_parameter_set_id: str,
    approval_parameter_set_hash: str,
    now_utc: datetime | None = None,
    actor_id: str = "",
) -> Approval:
    """Resolve a Telegram callback to an existing or transitioned approval.

    Per D-01: the token hash is the idempotency key. A callback is
    first hashed, then looked up. A wrong token (lookup returns None)
    is rejected. A found approval is run through the fixed-order
    binding gate. If the gate passes and the approval is PENDING,
    exactly one transition is performed and saved. If the approval is
    already decided (APPROVED/SKIPPED/EXPIRED), the existing approval
    is returned untouched — this is the replay-to-existing semantics.

    Args:
        callback: The Telegram callback payload.
        lookup_by_token_hash: Caller-supplied function that looks up
            an Approval by its token hash. Returns None if not found.
        save: Caller-supplied function that persists the Approval.
            Called exactly once per PENDING->decided transition.
        authorized_chat_id: The chat id authorized for this account.
        expiry_utc: The approval's expiry (from the parent TradePlan).
        approval_strategy_version: The strategy version on the parent.
        approval_parameter_set_id: The parameter set id on the parent.
        approval_parameter_set_hash: The parameter set hash on the parent.
        now_utc: The current UTC-aware datetime. If None, uses
            callback.callback_at_utc.
        actor_id: The Telegram user id (as text) of the press that decides the
            approval (Phase 23, D-03). Set only in the PENDING -> decided
            transition; a replay returns the stored row and keeps the first
            actor. At most 64 characters (the approvals.actor_id column width).

    Returns:
        The Approval after resolution — either the existing decided
        approval (replay) or the newly transitioned approval.

    Raises:
        ApprovalRejected: The binding gate failed. The exception's
            `reason_code` carries the canonical RejectionReason.
    """
    if len(actor_id) > _ACTOR_ID_MAX_LENGTH:
        raise ValueError(f"actor_id must be at most {_ACTOR_ID_MAX_LENGTH} characters")

    # Derive now_utc from the callback if not provided.
    effective_now = now_utc if now_utc is not None else callback.callback_at_utc

    # Gate 1 (chat) runs BEFORE any state lookup (D-01). A wrong chat
    # must never touch the approval row. We check the chat gate here
    # before hashing the token or looking up the approval.
    if callback.chat_id != authorized_chat_id:
        raise ApprovalRejected(
            reason_code=RejectionReason.INVALIDATED,
            message="wrong chat id",
        )

    # Hash the raw token to get the idempotency key.
    token_hash = token_hash_of(callback.raw_token)

    with _lock_for_token(token_hash):
        return _resolve_locked(
            callback=callback,
            token_hash=token_hash,
            lookup_by_token_hash=lookup_by_token_hash,
            save=save,
            authorized_chat_id=authorized_chat_id,
            expiry_utc=expiry_utc,
            approval_strategy_version=approval_strategy_version,
            approval_parameter_set_id=approval_parameter_set_id,
            approval_parameter_set_hash=approval_parameter_set_hash,
            effective_now=effective_now,
            actor_id=actor_id,
        )


def _resolve_locked(
    *,
    callback: Callback,
    token_hash: str,
    lookup_by_token_hash: LookupByTokenHash,
    save: SaveApproval,
    authorized_chat_id: int,
    expiry_utc: datetime,
    approval_strategy_version: str,
    approval_parameter_set_id: str,
    approval_parameter_set_hash: str,
    effective_now: datetime,
    actor_id: str,
) -> Approval:
    # Look up the approval by token hash. A wrong token (lookup returns
    # None) is rejected — the binding gate's token gate would also
    # catch this, but we reject early to avoid running the rest of the
    # gate on a non-existent approval.
    approval = lookup_by_token_hash(token_hash)
    if approval is None:
        raise ApprovalRejected(
            reason_code=RejectionReason.INVALIDATED,
            message="approval not found for token hash",
        )

    # Run the remaining binding gates (expiry, plan-hash, version,
    # token). The chat gate already passed above. The gate raises no
    # exception; it returns a BindingCheck with ok=False and a
    # reason_code on failure. We translate that to ApprovalRejected.
    check = check_binding_full(
        callback=callback,
        approval=approval,
        authorized_chat_id=authorized_chat_id,
        now_utc=effective_now,
        expiry_utc=expiry_utc,
        approval_strategy_version=approval_strategy_version,
        approval_parameter_set_id=approval_parameter_set_id,
        approval_parameter_set_hash=approval_parameter_set_hash,
    )
    if not check.ok:
        assert check.reason_code is not None
        raise ApprovalRejected(
            reason_code=check.reason_code,
            message=f"binding gate failed: {check.reason_code.value}",
        )

    # Replay-to-existing: if the approval is already decided, return
    # it untouched. WR-07: PENDING iff acted_at_utc is None — we
    # re-check at transition time to guard against a corrupt row.
    if approval.status != ApprovalResult.PENDING:
        return approval
    if approval.acted_at_utc is not None:
        # Defensive: a non-PENDING approval must have acted_at_utc set
        # (WR-07). If it doesn't, the row is corrupt — treat as PENDING
        # and transition. But this should never happen because the
        # Approval __post_init__ rejects it.
        pass  # fall through to transition

    # PENDING -> decided transition. CR-01: the pressed button
    # (callback.action) determines the outcome — never the stored row.
    # A stored-action/callback-action mismatch is an explicit reject
    # (fail closed). WR-31: SIMULATE never transitions approval state.
    if approval.action == ApprovalAction.SIMULATE:
        raise ApprovalRejected(
            reason_code=RejectionReason.INVALIDATED,
            message="SIMULATE never transitions approval state",
        )
    deciding_action = callback.action if callback.action is not None else approval.action
    if deciding_action == ApprovalAction.SIMULATE:
        raise ApprovalRejected(
            reason_code=RejectionReason.INVALIDATED,
            message="SIMULATE never transitions approval state",
        )
    if callback.action is not None and callback.action != approval.action:
        raise ApprovalRejected(
            reason_code=RejectionReason.INVALIDATED,
            message="callback action != approval action",
        )
    new_result = action_to_result(deciding_action)
    if new_result == ApprovalResult.PENDING:
        raise ApprovalRejected(
            reason_code=RejectionReason.INVALIDATED,
            message=f"callback action {deciding_action.value} maps to PENDING — no transition",
        )
    new_approval = replace(
        approval,
        result=new_result,
        status=new_result,
        acted_at_utc=effective_now,
        actor_id=actor_id or approval.actor_id,
    )

    # Save exactly once. If save raises (e.g., notify failure), the
    # approval stays PENDING — the caller catches the exception.
    try:
        save(new_approval)
    except ApprovalAlreadyDecided as lost:
        # Lost a (cross-process) race: the stored decision is the truth (D-17, C15).
        existing = lost.existing
        if existing.action == deciding_action and existing.status == new_result:
            return existing
        raise ApprovalRejected(
            reason_code=RejectionReason.INVALIDATED,
            message="approval already decided with a different outcome",
        ) from None

    return new_approval


__all__ = [
    "ApprovalAlreadyDecided",
    "resolve_callback",
    "LookupByTokenHash",
    "SaveApproval",
]
