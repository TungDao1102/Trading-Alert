"""Execution-intent store Protocol (Phase 17, D-13/D-14/D-15, EXEC-03).

The execution manager depends on this Protocol, never on a database driver:
this module is stdlib + `src.domain` only (no SQLAlchemy import), so the
manager stays free of persistence imports (09-REVIEW CR-07, research C12).

The write-ahead contract the manager follows around the entry order:

  1. `consume_and_record_entry_intent` — ONE transaction that inserts the ENTRY
     intent (INTENDED) and stamps the approval consumed. `True` = this caller
     won; `False` = the approval was already consumed (replay or lost race).
  2. `mark_sent` — committed BEFORE `place_entry` is awaited.
  3. `record_result` — ACKED / REJECTED / UNKNOWN from the exchange response.
  4. `record_protective_intent` + `mark_sent` + `record_result` for the STOP_LOSS leg,
     committed BEFORE `place_algo_protective` runs (D-14, F-703).
  5. `finalize_entry_outcome` — the exact `ExecutionOutcome` fields, so a replay
     returns the stored result with zero adapter calls (D-15).

Restart recovery (plan 17-12, D-14) reads the rows no step above finished through
`list_unresolved_intents` and resolves them by querying the exchange; it never re-sends.

Status changes are legal only along `src.domain.transitions` (EXECUTION_INTENT, D-20);
an unchanged status is an idempotent no-op.

The exchange's own client-id dedup is explicitly NOT relied on: Binance only
rejects a duplicate while the earlier order is still open (F-126).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from src.domain.enums import ExecutionIntentStatus


@dataclass(frozen=True)
class RecordedOutcome:
    """The persisted `ExecutionOutcome` fields (kept separate from the manager's class)."""

    is_no_trade: bool
    reason_code: str


@dataclass(frozen=True)
class IntentRecord:
    """One `execution_intents` row as the manager sees it (no ORM types)."""

    approval_id: str
    role: str
    trade_plan_id: str
    plan_hash: str
    client_order_id: str | None
    algo_client_id: str | None
    symbol: str
    side: str
    intended_quantity: Decimal | None
    intended_price: Decimal | None
    intent_status: ExecutionIntentStatus
    exchange_order_id: str | None
    exchange_status: str | None
    outcome: RecordedOutcome | None
    intended_at_utc: datetime
    sent_at_utc: datetime | None
    resolved_at_utc: datetime | None
    updated_at_utc: datetime
    # The sizing-time realized risk (SizedResult.realized_risk), stored once on the ENTRY row at
    # approval consumption (Phase 19, D-22, migration 0005). None = unknown or not an ENTRY row.
    sized_realized_risk: Decimal | None = None


@runtime_checkable
class ExecutionIntentStore(Protocol):
    """Durable approval consumption and write-ahead intents (synchronous, D-01)."""

    def get_entry(self, *, approval_id: str) -> IntentRecord | None: ...

    def list_unresolved_intents(self) -> Sequence[IntentRecord]:
        """Every INTENDED, SENT and UNKNOWN intent (any role), never ACKED or REJECTED.

        Ordered by `intended_at_utc`, then `approval_id`, then `role`, so recovery and
        Phase 20 reconciliation walk the rows in one deterministic order (D-14).
        """
        ...

    def consume_and_record_entry_intent(
        self,
        *,
        approval_id: str,
        trade_plan_id: str,
        plan_hash: str,
        client_order_id: str,
        symbol: str,
        side: str,
        intended_quantity: Decimal,
        intended_price: Decimal,
        now_utc: datetime,
        sized_realized_risk: Decimal | None = None,
    ) -> bool:
        """Insert the ENTRY intent and consume the approval in one transaction.

        `sized_realized_risk` (D-22) is written on the ENTRY row by this same INSERT and never
        updated later; None means "unknown" (the nullable evidence column stays NULL).
        """
        ...

    def record_protective_intent(
        self,
        *,
        approval_id: str,
        role: str,
        trade_plan_id: str,
        plan_hash: str,
        algo_client_id: str,
        symbol: str,
        side: str,
        intended_price: Decimal,
        now_utc: datetime,
    ) -> bool:
        """Insert a protective-leg intent (INTENDED, no quantity: close-position leg).

        `True` = this caller created the row; `False` = the (approval_id, role) row
        already existed.
        """
        ...

    def mark_sent(self, *, approval_id: str, role: str, now_utc: datetime) -> None: ...

    def record_result(
        self,
        *,
        approval_id: str,
        role: str,
        status: ExecutionIntentStatus,
        exchange_order_id: str | None,
        exchange_status: str | None,
        now_utc: datetime,
    ) -> None: ...

    def finalize_entry_outcome(
        self,
        *,
        approval_id: str,
        is_no_trade: bool,
        reason_code: str,
        now_utc: datetime,
    ) -> None: ...
