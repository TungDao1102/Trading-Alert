"""Intent-store test doubles (Phase 17, D-25).

`InMemoryExecutionIntentStore` mirrors `PgExecutionStateStore` semantics
(same `src.domain.transitions` rules, same won/lost return of consume) so every
existing manager unit test keeps its one-call behavior without a database.

`AlwaysWinsIntentStore` is the NEGATIVE CONTROL: it never remembers, so a
replayed approval always looks like a first call. Running the SC4 scenario
against it must produce two `place_entry` calls, proving the Binance-
semantics fake can actually observe the F-126 double entry.

`CrashAfter` wraps a store and raises `SimulatedCrash` (a `BaseException`, so the
manager can never swallow it) right after a named write-ahead step has been
COMMITTED (plan 11, D-14, D-26): the row stays readable and a restarted manager
must not re-send.

`FailingIntentStore` raises a chosen exception from one method (optionally only
for one role) to prove the manager fails closed on store errors on both sides of
placement.

All of these live under `tests/support` on purpose: production code has no in-memory
fallback (D-04, T-17-04 fail closed).
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.domain.transitions import IllegalTransition, TransitionKind, assert_transition
from src.execution.intent_store import ExecutionIntentStore, IntentRecord, RecordedOutcome
from src.persistence.errors import IntentStateConflict

_UNRESOLVED: frozenset[ExecutionIntentStatus] = frozenset(
    {
        ExecutionIntentStatus.INTENDED,
        ExecutionIntentStatus.SENT,
        ExecutionIntentStatus.UNKNOWN,
    }
)


class InMemoryExecutionIntentStore:
    """Dict-backed `ExecutionIntentStore` with the Postgres store's semantics."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], IntentRecord] = {}
        self._lock = threading.Lock()

    def get_entry(self, *, approval_id: str) -> IntentRecord | None:
        with self._lock:
            return self._rows.get((approval_id, OrderRole.ENTRY.value))

    def get_intent(self, *, approval_id: str, role: str) -> IntentRecord | None:
        """Test-side read of any role's row (not part of the production Protocol)."""
        with self._lock:
            return self._rows.get((approval_id, role))

    def list_unresolved_intents(self) -> tuple[IntentRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (r for r in self._rows.values() if r.intent_status in _UNRESOLVED),
                    key=lambda r: (r.intended_at_utc, r.approval_id, r.role),
                )
            )

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
        key = (approval_id, role)
        with self._lock:
            if key in self._rows:
                return False
            self._rows[key] = IntentRecord(
                approval_id=approval_id,
                role=role,
                trade_plan_id=trade_plan_id,
                plan_hash=plan_hash,
                client_order_id=None,
                algo_client_id=algo_client_id,
                symbol=symbol,
                side=side,
                intended_quantity=None,
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
            if row.intent_status == ExecutionIntentStatus.SENT:
                return  # unchanged status is an idempotent no-op
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
            if row.intent_status == status:
                return  # unchanged status is an idempotent no-op
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
        try:
            assert_transition(TransitionKind.EXECUTION_INTENT, row.intent_status, target)
        except IllegalTransition as exc:
            raise IntentStateConflict(
                f"illegal intent transition {row.intent_status.value} -> {target.value}"
            ) from exc


class AlwaysWinsIntentStore:
    """Never remembers: `get_entry` is always None and consume always wins."""

    def get_entry(self, *, approval_id: str) -> IntentRecord | None:
        return None

    def list_unresolved_intents(self) -> tuple[IntentRecord, ...]:
        return ()

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


# --------------------------------------------------------------------------- #
# Crash and failure injection (plan 17-11, D-14, D-26).
# --------------------------------------------------------------------------- #


class SimulatedCrash(BaseException):
    """A process crash: a `BaseException`, so no `except Exception` catches it."""


CRASH_STEPS: tuple[str, ...] = (
    "consume",
    "entry_sent",
    "entry_result",
    "sl_intent",
    "sl_sent",
    "sl_result",
    "finalize",
)


class CrashAfter:
    """Delegates to `inner` and raises `SimulatedCrash` right AFTER the named step committed."""

    def __init__(self, inner: ExecutionIntentStore, *, step: str) -> None:
        if step not in CRASH_STEPS:
            raise ValueError(f"unknown crash step {step!r}; known: {CRASH_STEPS}")
        self._inner = inner
        self._step = step

    def _maybe_crash(self, step: str) -> None:
        if step == self._step:
            raise SimulatedCrash(f"simulated crash after {step}")

    def get_entry(self, *, approval_id: str) -> IntentRecord | None:
        return self._inner.get_entry(approval_id=approval_id)

    def list_unresolved_intents(self) -> Sequence[IntentRecord]:
        return self._inner.list_unresolved_intents()

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
        won = self._inner.consume_and_record_entry_intent(
            approval_id=approval_id,
            trade_plan_id=trade_plan_id,
            plan_hash=plan_hash,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            intended_quantity=intended_quantity,
            intended_price=intended_price,
            now_utc=now_utc,
        )
        self._maybe_crash("consume")
        return won

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
        created = self._inner.record_protective_intent(
            approval_id=approval_id,
            role=role,
            trade_plan_id=trade_plan_id,
            plan_hash=plan_hash,
            algo_client_id=algo_client_id,
            symbol=symbol,
            side=side,
            intended_price=intended_price,
            now_utc=now_utc,
        )
        self._maybe_crash("sl_intent")
        return created

    def mark_sent(self, *, approval_id: str, role: str, now_utc: datetime) -> None:
        self._inner.mark_sent(approval_id=approval_id, role=role, now_utc=now_utc)
        self._maybe_crash("entry_sent" if role == OrderRole.ENTRY.value else "sl_sent")

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
        self._inner.record_result(
            approval_id=approval_id,
            role=role,
            status=status,
            exchange_order_id=exchange_order_id,
            exchange_status=exchange_status,
            now_utc=now_utc,
        )
        self._maybe_crash("entry_result" if role == OrderRole.ENTRY.value else "sl_result")

    def finalize_entry_outcome(
        self,
        *,
        approval_id: str,
        is_no_trade: bool,
        reason_code: str,
        now_utc: datetime,
    ) -> None:
        self._inner.finalize_entry_outcome(
            approval_id=approval_id,
            is_no_trade=is_no_trade,
            reason_code=reason_code,
            now_utc=now_utc,
        )
        self._maybe_crash("finalize")


_FAILABLE_METHODS: frozenset[str] = frozenset(
    {
        "get_entry",
        "list_unresolved_intents",
        "consume_and_record_entry_intent",
        "record_protective_intent",
        "mark_sent",
        "record_result",
        "finalize_entry_outcome",
    }
)


class FailingIntentStore:
    """Delegates to `inner`; raises `exc` from `method_name` (optionally for one role only)."""

    def __init__(
        self,
        method_name: str,
        exc: BaseException,
        *,
        inner: ExecutionIntentStore | None = None,
        role: str | None = None,
    ) -> None:
        if method_name not in _FAILABLE_METHODS:
            raise ValueError(f"unknown store method {method_name!r}")
        self._inner: ExecutionIntentStore = inner or InMemoryExecutionIntentStore()
        self._method_name = method_name
        self._exc = exc
        self._role = role
        self.failures_raised = 0

    def _maybe_fail(self, method_name: str, role: str | None = None) -> None:
        if method_name != self._method_name:
            return
        if self._role is not None and role != self._role:
            return
        self.failures_raised += 1
        raise self._exc

    def get_entry(self, *, approval_id: str) -> IntentRecord | None:
        self._maybe_fail("get_entry")
        return self._inner.get_entry(approval_id=approval_id)

    def list_unresolved_intents(self) -> Sequence[IntentRecord]:
        self._maybe_fail("list_unresolved_intents")
        return self._inner.list_unresolved_intents()

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
        self._maybe_fail("consume_and_record_entry_intent")
        return self._inner.consume_and_record_entry_intent(
            approval_id=approval_id,
            trade_plan_id=trade_plan_id,
            plan_hash=plan_hash,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            intended_quantity=intended_quantity,
            intended_price=intended_price,
            now_utc=now_utc,
        )

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
        self._maybe_fail("record_protective_intent", role)
        return self._inner.record_protective_intent(
            approval_id=approval_id,
            role=role,
            trade_plan_id=trade_plan_id,
            plan_hash=plan_hash,
            algo_client_id=algo_client_id,
            symbol=symbol,
            side=side,
            intended_price=intended_price,
            now_utc=now_utc,
        )

    def mark_sent(self, *, approval_id: str, role: str, now_utc: datetime) -> None:
        self._maybe_fail("mark_sent", role)
        self._inner.mark_sent(approval_id=approval_id, role=role, now_utc=now_utc)

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
        self._maybe_fail("record_result", role)
        self._inner.record_result(
            approval_id=approval_id,
            role=role,
            status=status,
            exchange_order_id=exchange_order_id,
            exchange_status=exchange_status,
            now_utc=now_utc,
        )

    def finalize_entry_outcome(
        self,
        *,
        approval_id: str,
        is_no_trade: bool,
        reason_code: str,
        now_utc: datetime,
    ) -> None:
        self._maybe_fail("finalize_entry_outcome")
        self._inner.finalize_entry_outcome(
            approval_id=approval_id,
            is_no_trade=is_no_trade,
            reason_code=reason_code,
            now_utc=now_utc,
        )
