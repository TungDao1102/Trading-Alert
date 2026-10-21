"""PostgreSQL adapter for the durable SAFE_MODE state (Phase 20, plan 20-06, D-14, F-127).

`PgSafeModeStateStore` satisfies `src.reconcile.safe_mode.SafeModeStateStore` on top of the
append-only `PgSystemStateStore`: every `save` is a new `system_state_events` row of key
`SAFE_MODE` plus its `SYSTEM_STATE_CHANGED` journal event in one transaction, and `load` is the
latest version. The `system_state_events` CHECK already lists SAFE_MODE, so there is no DDL change.

There is no retry here. A concurrent version (`RowConflict`) and typed persistence errors
(`StoreUnavailable`, `StoreFailure`, ...) propagate unchanged: the controller stays in SAFE_MODE
on a failed save and retries on its next `enter_safe_mode` call, and on a failed load it starts in
SAFE_MODE (`SAFE_MODE_STATE_UNREADABLE`).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from src.domain.enums import SystemStateKey
from src.persistence.system_state import PgSystemStateStore


class PgSafeModeStateStore:
    """The SAFE_MODE key of the system-state log, as a `SafeModeStateStore`."""

    def __init__(self, system_state: PgSystemStateStore) -> None:
        self._system_state = system_state

    def save(self, state: Mapping[str, str | bool | None], *, now_utc: datetime) -> None:
        """Append one SAFE_MODE state version with its journal event (one transaction).

        Raises:
            ValueError: `state` holds a value other than `str`, `bool` or `None`, or `now_utc` is
                not UTC-aware. Nothing is written.
            RowConflict: a concurrent append took the same version; propagates unchanged.
            PersistenceError: any typed store failure propagates unchanged.
        """
        self._system_state.append(SystemStateKey.SAFE_MODE, state, now_utc=now_utc)

    def load(self) -> Mapping[str, str | bool | None] | None:
        """The latest persisted SAFE_MODE state, or None when it was never written.

        Raises:
            ValueError: the stored row is malformed (the caller fails closed).
            PersistenceError: any typed store failure propagates unchanged.
        """
        record = self._system_state.latest(SystemStateKey.SAFE_MODE)
        if record is None:
            return None
        return dict(record.state)


__all__ = ["PgSafeModeStateStore"]
