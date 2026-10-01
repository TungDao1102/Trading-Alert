"""Intent-store test doubles (Phase 17, D-25).

`InMemoryExecutionIntentStore` mirrors `PgExecutionStateStore` semantics
(same allowed-predecessor rules, same won/lost return of consume) so every
existing manager unit test keeps its one-call behavior without a database.

`AlwaysWinsIntentStore` is the NEGATIVE CONTROL: it never remembers, so a
replayed approval always looks like a first call. Running the SC4 scenario
against it must produce two `place_entry` calls, proving the Binance-
semantics fake can actually observe the F-126 double entry.

Both live under `tests/support` on purpose: production code has no in-memory
fallback (D-04, T-17-04 fail closed).
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.execution.intent_store import ALLOWED_PREDECESSORS, IntentRecord, RecordedOutcome
from src.persistence.errors import IntentStateConflict


class InMemoryExecutionIntentStore:
    """Dict-backed `ExecutionIntentStore` with the Postgres store's semantics."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], IntentRecord] = {}
        self._lock = threading.Lock()

    def get_entry(self, *, approval_id: str) -> IntentRecord | None:
        with self._lock:
            return self._rows.get((approval_id, OrderRole.ENTRY.value))

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
    ) -> bool:
        key = (approval_id, OrderRole.ENTRY.value)
        with self._lock:
            if key in self._rows:
                return False
            self._rows[key] = IntentRecord(
                approval_id=approval_id,
                role=OrderRole.ENTRY.value,
                trade_plan_id=trade_plan_id,
                plan_hash=plan_hash,
                client_order_id=client_order_id,
                algo_client_id=None,
                symbol=symbol,
                side=side,
                intended_quantity=intended_quantity,
                intended_price=intended_price,
                intent_status=ExecutionIntentStatus.INTENDED,
                exchange_order_id=None,
                exchange_status=None,
                outcome=None,
                intended_at_utc=now_utc,
                sent_at_utc=None,
                resolved_at_utc=None,
                updated_at_utc=now_utc,
            )
            return True

    def mark_sent(self, *, approval_id: str, role: str, now_utc: datetime) -> None:
        with self._lock:
            row = self._require(approval_id, role)
            self._check(row, ExecutionIntentStatus.SENT)
            self._rows[(approval_id, role)] = replace(
                row,
                intent_status=ExecutionIntentStatus.SENT,
                sent_at_utc=now_utc,
                updated_at_utc=now_utc,
            )

    def record_result(
        self,
        *,
        approval_id: str,
        role: str,
        status: ExecutionIntentStatus,
        exchange_order_id: str | None,
        exchange_status: str | None,
        now_utc: datetime,
    ) -> None:
        with self._lock:
            row = self._require(approval_id, role)
            self._check(row, status)
            resolved = now_utc if status != ExecutionIntentStatus.UNKNOWN else None
            self._rows[(approval_id, role)] = replace(
                row,
                intent_status=status,
                exchange_order_id=exchange_order_id,
                exchange_status=exchange_status,
                resolved_at_utc=resolved,
                updated_at_utc=now_utc,
            )

    def finalize_entry_outcome(
        self,
        *,
        approval_id: str,
        is_no_trade: bool,
        reason_code: str,
        now_utc: datetime,
    ) -> None:
        with self._lock:
            row = self._require(approval_id, OrderRole.ENTRY.value)
            if row.outcome is not None:
                raise IntentStateConflict("entry outcome already recorded")
            self._rows[(approval_id, OrderRole.ENTRY.value)] = replace(
                row,
                outcome=RecordedOutcome(is_no_trade=is_no_trade, reason_code=reason_code),
                updated_at_utc=now_utc,
            )

    # ------------------------------------------------------------------ #

    def _require(self, approval_id: str, role: str) -> IntentRecord:
        row = self._rows.get((approval_id, role))
        if row is None:
            raise IntentStateConflict(f"no intent row for role {role}")
        return row

    @staticmethod
    def _check(row: IntentRecord, target: ExecutionIntentStatus) -> None:
        if row.intent_status not in ALLOWED_PREDECESSORS[target]:
            raise IntentStateConflict(
                f"illegal intent transition {row.intent_status.value} -> {target.value}"
            )


class AlwaysWinsIntentStore:
    """Never remembers: `get_entry` is always None and consume always wins."""

    def get_entry(self, *, approval_id: str) -> IntentRecord | None:
        return None

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
    ) -> bool:
        return True

    def mark_sent(self, *, approval_id: str, role: str, now_utc: datetime) -> None:
        return None

    def record_result(
        self,
        *,
        approval_id: str,
        role: str,
        status: ExecutionIntentStatus,
        exchange_order_id: str | None,
        exchange_status: str | None,
        now_utc: datetime,
    ) -> None:
        return None

    def finalize_entry_outcome(
        self,
        *,
        approval_id: str,
        is_no_trade: bool,
        reason_code: str,
        now_utc: datetime,
    ) -> None:
        return None
