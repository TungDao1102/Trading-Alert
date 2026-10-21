"""Test doubles for the pending protective action store (Phase 20, plan 20-14, D-19).

`InMemoryPendingActionStore` mirrors the semantics of `PgPendingActionStore` (one open row per
(plan_hash, kind), a re-block bumps the same row, resolve and supersede touch only the open row)
so every coordinator and closer test runs without a database. `FailingPendingActionStore`
raises `StoreUnavailable` from every method, to prove the protective flow carries on and
SAFE_MODE DB_FAILURE is entered once.

No production code imports this module.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from src.execution.pending_actions import (
    PendingAction,
    PendingKind,
    PendingState,
    pending_id_for,
)
from src.persistence.errors import StoreUnavailable


class InMemoryPendingActionStore:
    """Dict-backed `PendingActionStore` with the Postgres store's semantics."""

    def __init__(self) -> None:
        self._rows: list[PendingAction] = []
        self.calls: list[str] = []

    def record_blocked(
        self,
        *,
        plan_hash: str,
        trade_plan_id: str,
        approval_id: str,
        symbol: str,
        kind: PendingKind,
        gate_reason: str,
        retry_after_until_utc: datetime | None,
        now_utc: datetime,
    ) -> PendingAction:
        self.calls.append("record_blocked")
        index = self._open_index(plan_hash, kind)
        if index is not None:
            current = self._rows[index]
            updated = replace(
                current,
                gate_reason=gate_reason,
                last_blocked_at_utc=max(now_utc, current.last_blocked_at_utc),
                block_count=current.block_count + 1,
                retry_after_until_utc=retry_after_until_utc,
            )
            self._rows[index] = updated
            return updated
        row = PendingAction(
            pending_id=pending_id_for(plan_hash, kind, opened_at_utc=now_utc),
            plan_hash=plan_hash,
            trade_plan_id=trade_plan_id,
            approval_id=approval_id,
            symbol=symbol,
            kind=kind,
            state=PendingState.PENDING,
            gate_reason=gate_reason,
            first_blocked_at_utc=now_utc,
            last_blocked_at_utc=now_utc,
            block_count=1,
            retry_after_until_utc=retry_after_until_utc,
            resolved_at_utc=None,
            resolution_note=None,
        )
        self._rows.append(row)
        return row

    def resolve(
        self, *, plan_hash: str, kind: PendingKind, note: str, now_utc: datetime
    ) -> PendingAction | None:
        self.calls.append("resolve")
        return self._close(plan_hash, kind, PendingState.RESOLVED, note, now_utc)

    def supersede(
        self, *, plan_hash: str, kind: PendingKind, note: str, now_utc: datetime
    ) -> PendingAction | None:
        self.calls.append("supersede")
        return self._close(plan_hash, kind, PendingState.SUPERSEDED, note, now_utc)

    def list_open(self) -> tuple[PendingAction, ...]:
        self.calls.append("list_open")
        open_rows = [r for r in self._rows if r.state is PendingState.PENDING]
        return tuple(sorted(open_rows, key=lambda r: (r.first_blocked_at_utc, r.pending_id)))

    # -- test-side reads (not part of the production Protocol) ------------------------------

    def all_rows(self) -> tuple[PendingAction, ...]:
        return tuple(self._rows)

    def rows_of(self, kind: PendingKind) -> tuple[PendingAction, ...]:
        return tuple(r for r in self._rows if r.kind is kind)

    def _open_index(self, plan_hash: str, kind: PendingKind) -> int | None:
        for index, row in enumerate(self._rows):
            if (
                row.plan_hash == plan_hash
                and row.kind is kind
                and row.state is PendingState.PENDING
            ):
                return index
        return None

    def _close(
        self,
        plan_hash: str,
        kind: PendingKind,
        state: PendingState,
        note: str,
        now_utc: datetime,
    ) -> PendingAction | None:
        index = self._open_index(plan_hash, kind)
        if index is None:
            return None
        closed = replace(
            self._rows[index],
            state=state,
            resolved_at_utc=max(now_utc, self._rows[index].last_blocked_at_utc),
            resolution_note=note,
        )
        self._rows[index] = closed
        return closed


class FailingPendingActionStore:
    """A store that is down: every method raises `StoreUnavailable`."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def record_blocked(self, **_: object) -> PendingAction:
        self.calls.append("record_blocked")
        raise StoreUnavailable("pending store is down (test)")

    def resolve(self, **_: object) -> PendingAction | None:
        self.calls.append("resolve")
        raise StoreUnavailable("pending store is down (test)")

    def supersede(self, **_: object) -> PendingAction | None:
        self.calls.append("supersede")
        raise StoreUnavailable("pending store is down (test)")

    def list_open(self) -> tuple[PendingAction, ...]:
        self.calls.append("list_open")
        raise StoreUnavailable("pending store is down (test)")


__all__ = [
    "FailingPendingActionStore",
    "InMemoryPendingActionStore",
]
