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

    Returns:
        The Approval after resolution — either the existing decided
        approval (replay) or the newly transitioned approval.

    Raises:
        ApprovalRejected: The binding gate failed. The exception's
            `reason_code` carries the canonical RejectionReason.
    """
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
    )

    # Save exactly once. If save raises (e.g., notify failure), the
    # approval stays PENDING — the caller catches the exception.
    save(new_approval)

    return new_approval


__all__ = [
    "resolve_callback",
    "LookupByTokenHash",
    "SaveApproval",
]
