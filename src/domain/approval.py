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
from decimal import Decimal

from .enums import ApprovalAction, ApprovalConsumptionStatus, ApprovalResult


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

    `acted_at_utc`, `consumed_at_utc` and `telegram_message_id` are nullable: NULL
    means "transition never happened" / "no Telegram message yet".

    Phase 17 (D-16, D-21, research C8/C13): `consumption_status` is the explicit
    durable consumption state (UNCONSUMED by default, never inferred from
    `consumed_at_utc`). CONSUMED requires `status` APPROVED and a UTC
    `consumed_at_utc`; only the execution-state consume transaction sets them.

    Phase 19 review-fix batch 4 (19-REVIEW WR-01, D078): `approved_quantity` is the quantity
    of the plan the approval request was issued for. It is written once with the PENDING row
    and never changed by a decision. None means "not recorded" (a row written before
    migration 0006); such an approval is never placeable (`APPROVED_QUANTITY_MISSING`).

    Phase 23 (plan 23-04, D-13): `money_json` is the canonical JSON text of the money block the
    messages show. It is written once with the PENDING row (the APPROVE and the SKIP row carry
    the same text), is part of the insert identity and is never changed by a decision. The
    domain keeps a plain string (it does not import the risk layer); `src/risk/money_at_stake.py`
    parses it strictly at render time. None means "not recorded" (a row written before
    migration 0013); every renderer refuses such an approval.
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
    consumption_status: ApprovalConsumptionStatus = ApprovalConsumptionStatus.UNCONSUMED
    consumed_at_utc: datetime | None = None  # None = "never consumed" (D-21)
    approved_quantity: Decimal | None = None  # None = "not recorded" (pre-0006 row, D078)
    money_json: str | None = None  # None = "not recorded" (pre-0013 row, D-13)

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
        # Phase 17 (D-16, D-21): explicit consumption state coherence.
        if self.consumed_at_utc is not None:
            _require_utc_aware(self.consumed_at_utc, "consumed_at_utc")
        if self.consumption_status == ApprovalConsumptionStatus.CONSUMED:
            if self.consumed_at_utc is None:
                raise ValueError("CONSUMED approval must set consumed_at_utc")
            if self.status != ApprovalResult.APPROVED:
                raise ValueError("CONSUMED approval must have status APPROVED")
        elif self.consumed_at_utc is not None:
            raise ValueError("UNCONSUMED approval must have consumed_at_utc=None")
        # D078: the approved quantity is None or a finite positive Decimal.
        if self.approved_quantity is not None:
            if not isinstance(self.approved_quantity, Decimal):
                raise ValueError("approved_quantity must be a Decimal or None")
            if not self.approved_quantity.is_finite() or self.approved_quantity <= Decimal("0"):
                raise ValueError("approved_quantity must be finite and greater than zero")
        # D-13: the money block is None or text shaped like a JSON object.
        if self.money_json is not None:
            if not isinstance(self.money_json, str):
                raise ValueError("money_json must be a str or None")
            if (
                len(self.money_json) < 2
                or not self.money_json.startswith("{")
                or not self.money_json.endswith("}")
            ):
                raise ValueError("money_json must be a JSON object text or None")
