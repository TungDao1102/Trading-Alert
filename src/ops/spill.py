"""Local durable spill for audit records written while the journal is down (Phase 20, D-16, D-30).

A risk-reducing control acts first and journals afterwards (`src.ops.risk_first`). When the
journal or its database cannot take the record, the record is written to this local spill,
one file per record, and `replay_spill` moves it into the journal once the journal is back.

Rules this module keeps:

- One file per record, named `<journal_event_id>.json`. The name is the validated journal
  event id and nothing else: it is never built from exchange or user text, and a name that
  does not match the id pattern is refused on write and reported as corrupt on read.
- A write is atomic: the bytes go to `.<id>.<pid>.tmp` in the same directory, are fsynced, and
  are moved into place with `src.data.store.replace_with_retry` (bounded Windows retry).
- The spill is supplementary evidence of what this process did. It is never a substitute for
  Binance truth, and a missing or empty spill proves nothing (D-30). What a restart does with
  it is plan 20-19.
- `replay_spill` is idempotent. An id the journal already holds with the same identity
  fields is "already present" and its file is removed. An id the journal holds with different
  fields is a conflict: the file is kept and the journal row is never changed. An unreadable
  or malformed file is reported as corrupt and kept.
- Reports carry event ids, reason codes and exception class names only, never message text.

No wall clock is read here: every timestamp in a record comes from the event itself.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.data.store import replace_with_retry
from src.domain.journal import JournalEvent
from src.persistence.errors import JournalConflict

# A journal event id: first character alphanumeric, then letters, digits, underscore or hyphen.
# No dot, separator or whitespace can appear, so a file name built from it cannot leave the
# spill directory. 128 is the journal_event_id column width.
_EVENT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")

_SUFFIX = ".json"

# Reason codes of a corrupt spill entry.
CORRUPT_INVALID_NAME = "INVALID_NAME"
CORRUPT_UNREADABLE = "UNREADABLE"
CORRUPT_INVALID_JSON = "INVALID_JSON"
CORRUPT_INVALID_RECORD = "INVALID_RECORD"
CORRUPT_ID_MISMATCH = "ID_MISMATCH"

# Label used in a report for a file whose name is not a valid journal event id.
INVALID_NAME_LABEL = "<invalid-name>"

_REQUIRED_TEXT_FIELDS = ("journal_event_id", "event_type", "entity_type", "entity_id")
_OPTIONAL_TEXT_FIELDS = (
    "signal_id",
    "trade_plan_id",
    "approval_id",
    "order_id",
    "position_id",
)
_DATETIME_FIELDS = ("occurred_at_utc", "created_at_utc")
_RECORD_KEYS = frozenset(
    {
        *_REQUIRED_TEXT_FIELDS,
        *_OPTIONAL_TEXT_FIELDS,
        *_DATETIME_FIELDS,
        "correlation_id",
        "payload_json",
    }
)

# Fields the journal compares on a replay (same set as src/persistence/journal.py).
_IDENTITY_FIELDS: tuple[str, ...] = (
    "event_type",
    "entity_type",
    "entity_id",
    "correlation_id",
    "signal_id",
    "trade_plan_id",
    "approval_id",
    "order_id",
    "position_id",
    "payload_json",
)


def is_valid_event_id(value: object) -> bool:
    """True when `value` is a journal event id that is safe to use as a file name."""
    return isinstance(value, str) and _EVENT_ID_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class SpillToken:
    """Handle to one spilled record (its journal event id)."""

    journal_event_id: str


@dataclass(frozen=True)
class SpillRecord:
    """One parsed spill file."""

    event: JournalEvent
    token: SpillToken


@dataclass(frozen=True)
class SpillScan:
    """What a directory scan found: parsed records and entries that could not be proven."""

    records: tuple[SpillRecord, ...]
    corrupt: tuple[tuple[str, str], ...]  # (event id or INVALID_NAME_LABEL, reason code)


@dataclass(frozen=True)
class SpillReplayReport:
    """Outcome of one `replay_spill` call. Ids, reason codes and class names only."""

    replayed: tuple[str, ...] = ()
    already_present: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()  # ids whose journal row differs; file kept
    corrupt: tuple[tuple[str, str], ...] = ()  # (id or label, reason); file kept
    failed: tuple[tuple[str, str], ...] = ()  # (id, exception class name); file kept

    @property
    def is_clean(self) -> bool:
        """True when nothing was left in the spill for a reason other than success."""
        return not (self.conflicts or self.corrupt or self.failed)


def _event_to_json(event: JournalEvent) -> str:
    created = event.created_at_utc
    body: dict[str, Any] = {
        "journal_event_id": event.journal_event_id,
        "occurred_at_utc": event.occurred_at_utc.isoformat(),
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "correlation_id": event.correlation_id,
        "signal_id": event.signal_id,
        "trade_plan_id": event.trade_plan_id,
        "approval_id": event.approval_id,
        "order_id": event.order_id,
        "position_id": event.position_id,
        "payload_json": event.payload_json,
        "created_at_utc": None if created is None else created.isoformat(),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _event_from_mapping(body: Mapping[str, Any]) -> JournalEvent:
    """Rebuild an event from a parsed spill mapping; any shape error raises `ValueError`."""
    if set(body) != _RECORD_KEYS:
        raise ValueError("spill record keys differ from the journal event fields")
    values: dict[str, Any] = {}
    for name in (*_REQUIRED_TEXT_FIELDS, "correlation_id", "payload_json"):
        value = body[name]
        if not isinstance(value, str):
            raise ValueError(f"spill field {name} must be text")
        values[name] = value
    for name in _OPTIONAL_TEXT_FIELDS:
        value = body[name]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"spill field {name} must be text or null")
        values[name] = value
    occurred = body["occurred_at_utc"]
    if not isinstance(occurred, str):
        raise ValueError("spill field occurred_at_utc must be ISO-8601 text")
    values["occurred_at_utc"] = datetime.fromisoformat(occurred)
    created = body["created_at_utc"]
    if created is None:
        values["created_at_utc"] = None
    elif isinstance(created, str):
        values["created_at_utc"] = datetime.fromisoformat(created)
    else:
        raise ValueError("spill field created_at_utc must be ISO-8601 text or null")
    return JournalEvent(**values)


def _same_identity(left: JournalEvent, right: JournalEvent) -> bool:
    return all(getattr(left, name) == getattr(right, name) for name in _IDENTITY_FIELDS)


class LocalSpill:
    """A directory of spilled journal events, one atomic file per event."""

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        # 0o700 where the OS honours it. Windows ACLs are not POSIX modes (see
        # .planning/WINDOWS.md), so the mode is a no-op there.
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return self._directory

    def _path_for(self, journal_event_id: str) -> Path:
        if not is_valid_event_id(journal_event_id):
            raise ValueError("spill refuses an id that is not a valid journal event id")
        return self._directory / f"{journal_event_id}{_SUFFIX}"

    def write(self, event: JournalEvent) -> SpillToken:
        """Write `event` durably (tmp + fsync + replace) and return its token.

        Raises:
            ValueError: the event id is not a valid journal event id (nothing is written).
            FileExistsError: a spill file with this id holds different content (kept as is).
            OSError: the directory or file cannot be written.
        """
        final = self._path_for(event.journal_event_id)
        payload = (_event_to_json(event) + "\n").encode("utf-8")
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if final.exists() and final.read_bytes() != payload:
            raise FileExistsError(
                f"spill record {event.journal_event_id} exists with different content"
            )
        tmp = final.with_name(f".{final.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            replace_with_retry(tmp, final)
        finally:
            tmp.unlink(missing_ok=True)
        self._fsync_directory()
        return SpillToken(journal_event_id=event.journal_event_id)

    def discard(self, token: SpillToken) -> None:
        """Delete one spilled record (a missing file is not an error)."""
        self._path_for(token.journal_event_id).unlink(missing_ok=True)

    def scan(self) -> SpillScan:
        """Parse every spill file; a missing directory is an empty scan (proves nothing)."""
        try:
            names = sorted(os.listdir(self._directory))
        except OSError:
            return SpillScan(records=(), corrupt=())
        records: list[SpillRecord] = []
        corrupt: list[tuple[str, str]] = []
        for name in names:
            if not name.endswith(_SUFFIX) or name.startswith("."):
                continue  # temp files and foreign files are not spill records
            path = self._directory / name
            if not path.is_file():
                continue
            stem = name[: -len(_SUFFIX)]
            if not is_valid_event_id(stem):
                corrupt.append((INVALID_NAME_LABEL, CORRUPT_INVALID_NAME))
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                corrupt.append((stem, CORRUPT_UNREADABLE))
                continue
            try:
                body = json.loads(text)
            except ValueError:
                corrupt.append((stem, CORRUPT_INVALID_JSON))
                continue
            try:
                if not isinstance(body, dict):
                    raise ValueError("spill record is not an object")
                event = _event_from_mapping(body)
            except (ValueError, TypeError):
                corrupt.append((stem, CORRUPT_INVALID_RECORD))
                continue
            if event.journal_event_id != stem:
                corrupt.append((stem, CORRUPT_ID_MISMATCH))
                continue
            records.append(SpillRecord(event=event, token=SpillToken(journal_event_id=stem)))
        records.sort(key=lambda r: (r.event.occurred_at_utc, r.event.journal_event_id))
        return SpillScan(records=tuple(records), corrupt=tuple(corrupt))

    def pending(self) -> tuple[SpillRecord, ...]:
        """Parsed records, sorted by (occurred_at_utc, journal_event_id)."""
        return self.scan().records

    def corrupt(self) -> tuple[tuple[str, str], ...]:
        """Entries that could not be proven: (id or label, reason code)."""
        return self.scan().corrupt

    def _fsync_directory(self) -> None:
        """Best-effort directory fsync where the OS supports it (a no-op on Windows)."""
        if os.name == "nt":
            return
        try:
            fd = os.open(self._directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)


def replay_spill(spill: LocalSpill, journal: Any) -> SpillReplayReport:
    """Move spilled records into `journal`. Idempotent; never overwrites a journal row.

    `journal` needs `record(event)`; when it also has `get(id)` (the real
    `PgJournalStore` does) an event that is already stored is reported as
    `already_present` without a second write.
    """
    scan = spill.scan()
    getter = getattr(journal, "get", None)
    replayed: list[str] = []
    already: list[str] = []
    conflicts: list[str] = []
    failed: list[tuple[str, str]] = []
    for record in scan.records:
        event = record.event
        event_id = event.journal_event_id
        stored: JournalEvent | None = None
        if callable(getter):
            try:
                stored = getter(event_id)
            except Exception:
                stored = None  # fall through to record(), which verifies a replay itself
        if stored is not None:
            if _same_identity(stored, event):
                bucket = already
            else:
                conflicts.append(event_id)
                continue
        else:
            try:
                journal.record(event)
            except JournalConflict:
                conflicts.append(event_id)
                continue
            except Exception as exc:
                failed.append((event_id, type(exc).__name__))
                continue
            bucket = replayed
        try:
            spill.discard(record.token)
        except OSError as exc:
            failed.append((event_id, type(exc).__name__))
            continue
        bucket.append(event_id)
    return SpillReplayReport(
        replayed=tuple(replayed),
        already_present=tuple(already),
        conflicts=tuple(conflicts),
        corrupt=scan.corrupt,
        failed=tuple(failed),
    )


__all__ = [
    "LocalSpill",
    "SpillToken",
    "SpillRecord",
    "SpillScan",
    "SpillReplayReport",
    "replay_spill",
    "is_valid_event_id",
    "INVALID_NAME_LABEL",
]
