"""PostgreSQL append-only system state: SAFE_MODE, enablement, kill gate (Phase 17-13, D-22, D-03).

`PgSystemStateStore` persists the durable system state the controllers must restore after a
restart (F-606, research C14). Each state change is a new row of `system_state_events` with a
per-key `state_version`, linked to the journal event that recorded it.

  - `append` writes the journal event (`SYSTEM_STATE_CHANGED`) and the state row in ONE
    transaction, so the audit trail and the current state cannot diverge (D-03). The next version
    is `max(state_version) + 1` for the key, read inside the transaction with no row lock;
    `uq_system_state_events_key_version` is the arbiter, and a concurrent append that loses the
    race raises `RowConflict` (the transaction, including its journal row, rolls back; the caller
    re-reads and retries).
  - `latest(key)` returns the highest version, or None when the key was never written.
    `latest_kill_gate_state()` is the typed reader for the KILL_GATE key.
  - State dict formats are owned by the controllers (SAFE_MODE, LIVE_ENABLEMENT) and by the
    kill-gate evaluator (`{"kill_gate_state": <KillGateState value>}`). Values are JSON-safe
    scalars only (`str`, `bool`, `None`); floats and integers are refused so a state document has
    exactly one canonical form.

There is deliberately no update or delete method: the table is append-only
(`trg_system_state_events_append_only`), so a writer that bypasses this class is refused by the
database. An unreachable database raises `StoreUnavailable` from the unit of work; there is no
retry loop here (F-406). Nothing here wires SAFE_MODE or enablement to the store: that is
Phase 20 / 24 (the controllers take a plain mapping and import nothing from persistence).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import SystemStateEventRow
from src.domain.canonical import canonical_bytes
from src.domain.enums import KillGateState, SystemStateKey
from src.domain.journal import JournalEvent, content_hash_event_id
from src.persistence.errors import ParentRowMissing, RowConflict
from src.persistence.uow import OperationalDatabase

_SQLSTATE_UNIQUE_VIOLATION = "23505"
_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"

#: The journal event written with every state change.
EVENT_TYPE = "SYSTEM_STATE_CHANGED"
ENTITY_TYPE = "SystemState"

_STATE_ID_PREFIX = "system_state"
_JOURNAL_ID_PREFIX = "system_state_event"
_KILL_GATE_FIELD = "kill_gate_state"

type StateValue = str | bool | None


class JournalAppender(Protocol):
    """The journal surface this store needs: write one event inside the caller's transaction."""

    def append(self, tx: Session, event: JournalEvent) -> None: ...


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else "unknown constraint"


def _require_utc_aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC, got offset {value.utcoffset()}")
    return value


def _validated_state(state: object) -> dict[str, StateValue]:
    """A copy of `state` with str keys and `str | bool | None` values, or ValueError."""
    if not isinstance(state, Mapping):
        raise ValueError(f"state must be a mapping, got {type(state).__name__}")
    checked: dict[str, StateValue] = {}
    for name, value in state.items():
        if not isinstance(name, str) or name == "":
            raise ValueError("state keys must be non-empty strings")
        if value is not None and not isinstance(value, (str, bool)):
            raise ValueError(
                f"state[{name!r}] must be str, bool or None, got {type(value).__name__}"
            )
        checked[name] = value
    return checked


def _reject_number(literal: str) -> Any:
    raise ValueError(f"number literal {literal!r} in stored system state")


def _parse_state_json(text: str) -> dict[str, StateValue]:
    try:
        doc = json.loads(
            text,
            parse_float=_reject_number,
            parse_int=_reject_number,
            parse_constant=_reject_number,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"stored system state is not valid JSON: {exc}") from exc
    return _validated_state(doc)


@dataclass(frozen=True)
class SystemStateRecord:
    """One persisted state version of a `SystemStateKey`."""

    key: SystemStateKey
    version: int
    state: Mapping[str, StateValue]
    recorded_at_utc: datetime
    journal_event_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, SystemStateKey):
            raise ValueError(f"key must be a SystemStateKey, got {type(self.key).__name__}")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError(f"version must be an int >= 1, got {self.version!r}")
        object.__setattr__(self, "state", MappingProxyType(_validated_state(self.state)))
        _require_utc_aware(self.recorded_at_utc, "recorded_at_utc")


class PgSystemStateStore:
    """Append-only system state, each change written together with its journal event."""

    def __init__(self, db: OperationalDatabase, journal: JournalAppender) -> None:
        self._db = db
        self._journal = journal

    @contextmanager
    def _unit(self, tx: Session | None) -> Iterator[Session]:
        """Join the caller's unit of work, or open (and commit) one."""
        if tx is not None:
            yield tx
            return
        with self._db.transaction() as session:
            yield session

    def append(
        self,
        key: SystemStateKey,
        state: Mapping[str, StateValue],
        *,
        now_utc: datetime,
        tx: Session | None = None,
    ) -> SystemStateRecord:
        """Record a new state version and its journal event in one transaction.

        Raises:
            ValueError: `key` is not a `SystemStateKey`, `now_utc` is not UTC-aware, or `state`
                holds anything other than `str`, `bool` or `None` values. Nothing is written.
            RowConflict: a concurrent append took the same version (re-read and retry). When a
                caller-owned `tx` is passed it is aborted and must be rolled back.
            ParentRowMissing: the journal row the state row links to does not exist.
        """
        if not isinstance(key, SystemStateKey):
            raise ValueError(f"key must be a SystemStateKey, got {type(key).__name__}")
        _require_utc_aware(now_utc, "now_utc")
        checked = _validated_state(state)
        state_json = canonical_bytes(dict(checked)).decode("ascii")

        with self._unit(tx) as session:
            current = session.execute(
                select(func.max(SystemStateEventRow.state_version)).where(
                    SystemStateEventRow.state_key == key.value
                )
            ).scalar_one()
            version = 1 if current is None else int(current) + 1
            event = self._journal_event(key, version, checked, now_utc)
            self._journal.append(session, event)
            row = SystemStateEventRow(
                state_event_id=content_hash_event_id(
                    prefix=_STATE_ID_PREFIX,
                    event_type=f"v{version}",
                    entity_id=key.value,
                    occurred_at_utc=now_utc,
                    payload_json=state_json,
                ),
                state_key=key.value,
                state_version=version,
                state_json=state_json,
                journal_event_id=event.journal_event_id,
                recorded_at_utc=now_utc,
            )
            try:
                session.add(row)
                session.flush()
            except IntegrityError as exc:
                sqlstate = getattr(exc.orig, "sqlstate", None)
                name = _constraint_name(exc)
                if sqlstate == _SQLSTATE_UNIQUE_VIOLATION:
                    raise RowConflict(
                        f"system state {key.value} version {version}: already taken ({name})"
                    ) from exc
                if sqlstate == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                    raise ParentRowMissing(
                        f"system state {key.value} version {version}: journal event missing "
                        f"({name})"
                    ) from exc
                raise
            return SystemStateRecord(
                key=key,
                version=version,
                state=checked,
                recorded_at_utc=now_utc,
                journal_event_id=event.journal_event_id,
            )

    def latest(self, key: SystemStateKey, *, tx: Session | None = None) -> SystemStateRecord | None:
        """The highest version of `key`, or None when it was never written.

        Raises:
            ValueError: the stored row is malformed (fail closed, never a default).
        """
        if not isinstance(key, SystemStateKey):
            raise ValueError(f"key must be a SystemStateKey, got {type(key).__name__}")
        with self._unit(tx) as session:
            row = session.execute(
                select(SystemStateEventRow)
                .where(SystemStateEventRow.state_key == key.value)
                .order_by(SystemStateEventRow.state_version.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            return SystemStateRecord(
                key=SystemStateKey(row.state_key),
                version=row.state_version,
                state=_parse_state_json(row.state_json),
                recorded_at_utc=row.recorded_at_utc,
                journal_event_id=row.journal_event_id,
            )

    def latest_kill_gate_state(self, *, tx: Session | None = None) -> KillGateState | None:
        """The latest stored kill-gate state, or None when never recorded.

        Raises:
            ValueError: the stored value is missing, not text, or outside `KillGateState`.
        """
        record = self.latest(SystemStateKey.KILL_GATE, tx=tx)
        if record is None:
            return None
        raw = record.state.get(_KILL_GATE_FIELD)
        if not isinstance(raw, str):
            raise ValueError(f"stored KILL_GATE state has no text {_KILL_GATE_FIELD!r}")
        try:
            return KillGateState(raw)
        except ValueError:
            raise ValueError(f"stored KILL_GATE state {raw!r} is not a KillGateState") from None

    @staticmethod
    def _journal_event(
        key: SystemStateKey,
        version: int,
        state: Mapping[str, StateValue],
        now_utc: datetime,
    ) -> JournalEvent:
        payload_json = canonical_bytes(
            {"state": dict(state), "state_key": key.value, "state_version": version}
        ).decode("ascii")
        return JournalEvent(
            journal_event_id=content_hash_event_id(
                prefix=_JOURNAL_ID_PREFIX,
                event_type=EVENT_TYPE,
                entity_id=key.value,
                occurred_at_utc=now_utc,
                payload_json=payload_json,
            ),
            occurred_at_utc=now_utc,
            event_type=EVENT_TYPE,
            entity_type=ENTITY_TYPE,
            entity_id=key.value,
            correlation_id=f"system_state:{key.value}",
            payload_json=payload_json,
        )


if TYPE_CHECKING:
    from src.persistence.journal import PgJournalStore

    def _conforms(journal: PgJournalStore) -> JournalAppender:
        # mypy-only: fails the type check if the journal's `append` surface drifts.
        return journal


__all__ = ["EVENT_TYPE", "ENTITY_TYPE", "PgSystemStateStore", "SystemStateRecord"]
