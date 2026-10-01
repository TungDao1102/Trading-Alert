"""Approval frozen dataclass (Phase 3, plan 03-02).

Per D-01/D-02/D-11/D-12: frozen pure-Python dataclass with timezone-aware
UTC datetime fields and Enum action/result fields. No `Optional` status;
`Optional` is reserved for "transition never happened" timestamps only.

The Approval entity carries the DATA_MODEL §2.5 field list. Repeated
callback delivery must resolve to the existing approval/result rather
than create a new approval or order (idempotent replay).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .enums import ApprovalAction, ApprovalResult


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


@dataclass(frozen=True)
class Approval:
    """Human interaction with a trade plan (DATA_MODEL §2.5).

    `action` is the GLOSSARY ApprovalAction (SIMULATE, APPROVE,
    SKIP_USER, SKIP_BUSY, CANCEL). `result` and `status` are the
    ApprovalResult lifecycle (PENDING, APPROVED, SKIPPED, EXPIRED) —
    `status` alone answers state (D-11); NULL `acted_at_utc` means
    "transition never happened".

    `acted_at_utc` and `telegram_message_id` are nullable: NULL means
    "transition never happened" / "no Telegram message yet".
    """

    approval_id: str
    trade_plan_id: str  # FK to TradePlan
    signal_id: str  # FK to Signal
    action: ApprovalAction
    result: ApprovalResult
    status: ApprovalResult  # explicit — never inferred (D-11)
    approval_token_hash: str
    requested_at_utc: datetime  # aware UTC
    acted_at_utc: datetime | None = None  # None = "never happened" (D-11)
    actor_id: str = ""
    telegram_message_id: str | None = None  # None = "no message yet"
    request_hash: str = ""

    def __post_init__(self) -> None:
        # D-12: UTC-aware datetimes only.
        _require_utc_aware(self.requested_at_utc, "requested_at_utc")
        if self.acted_at_utc is not None:
            _require_utc_aware(self.acted_at_utc, "acted_at_utc")
        # WR-07: state coherence — PENDING ⟺ acted_at_utc is None.
        # A pending approval has no transition yet; a decided approval
        # (APPROVED/SKIPPED/EXPIRED) must carry its transition time so
        # idempotent-replay logic can trust the entity.
        if self.status == ApprovalResult.PENDING and self.acted_at_utc is not None:
            raise ValueError("PENDING approval must have acted_at_utc=None")
        if self.status != ApprovalResult.PENDING and self.acted_at_utc is None:
            status_name = getattr(self.status, "value", self.status)
            raise ValueError(f"{status_name} approval must set acted_at_utc")
