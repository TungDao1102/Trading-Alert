"""JournalEvent frozen dataclass (Phase 3, plan 03-02).

Per D-01/D-02/D-12: frozen pure-Python dataclass with timezone-aware
UTC datetime fields. JournalEvent is append-only and never substitutes
for current-state tables (DATA_MODEL §2.10).

`event_type` and `entity_type` are validated non-empty strings with
empty values rejected at construction (T-03-04). Enum promotion is
deferred to Phase 4.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

_MAX_EVENT_ID_LENGTH = 128


def content_hash_event_id(
    *,
    prefix: str,
    event_type: str,
    entity_id: str,
    occurred_at_utc: datetime,
    payload_json: str,
) -> str:
    """Deterministic content-hash `journal_event_id` (DATA_MODEL PK contract).

    `journal_events.journal_event_id` is documented as a content hash.
    Ids built from `(name, millisecond)` alone collide whenever two
    DIFFERENT events share an injected timestamp (e.g. a PASS and a FAIL
    run of the same probe) — an integrity error, or a silently dropped
    event under upsert semantics (09-REVIEW WR-09). Hashing the full
    content keeps ids deterministic (same inputs → same id, replay-safe)
    while distinct events always get distinct ids. Byte-identical events
    intentionally map to the same id (they carry no new information).

    Returns `"{prefix}_{sha256-hex}"` (prefix + 65 chars, within the
    128-char column).
    """
    _require_non_empty(prefix, "prefix")
    _require_utc_aware(occurred_at_utc, "occurred_at_utc")
    material = json.dumps(
        [event_type, entity_id, occurred_at_utc.isoformat(), payload_json],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"{prefix}_{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def correlated_event_id(
    *,
    prefix: str,
    correlation_id: str,
    event_type: str,
    entity_id: str,
    step: str,
) -> str:
    """Deterministic `journal_event_id` for correlated, replayable events.

    A pure function of `(prefix, correlation_id, event_type, entity_id, step)`:
    no clock, no randomness, no database-derived sequence (D-10, research C7).
    A redelivered Telegram callback carries the same correlation id and so
    writes the same ids; the journal primary key then makes the replay an
    idempotent no-op. Distinct steps of one correlation (receipt, chat
    reject, each distinct outcome) get distinct ids.

    The hashed material is a compact JSON array of the four non-prefix
    values, so field boundaries cannot be shifted to forge a collision.

    Returns `"{prefix}_{sha256-hex}"`; with a short prefix this stays
    within the 128-char column.
    """
    _require_non_empty(prefix, "prefix")
    _require_non_empty(correlation_id, "correlation_id")
    _require_non_empty(event_type, "event_type")
    _require_non_empty(entity_id, "entity_id")
    _require_non_empty(step, "step")
    material = json.dumps(
        [correlation_id, event_type, entity_id, step],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    event_id = f"{prefix}_{hashlib.sha256(material.encode('utf-8')).hexdigest()}"
    if len(event_id) > _MAX_EVENT_ID_LENGTH:
        raise ValueError(f"journal_event_id exceeds {_MAX_EVENT_ID_LENGTH} characters")
    return event_id


def _require_non_empty(value: str, field_name: str) -> None:
    """Reject empty strings for validated non-empty fields (T-03-04)."""
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


@dataclass(frozen=True)
class JournalEvent:
    """Append-only operational/audit event (DATA_MODEL §2.10).

    All linkage ids are nullable except `correlation_id` (every event
    must be correlatable). `payload_json` is JSON-as-TEXT (DATA_MODEL §5).

    Do not use the event table as a substitute for current-state tables.
    """

    journal_event_id: str
    occurred_at_utc: datetime  # aware UTC
    event_type: str  # validated non-empty string (Phase 4 may promote to Enum)
    entity_type: str  # validated non-empty string (Phase 4 may promote to Enum)
    entity_id: str
    correlation_id: str
    signal_id: str | None = None
    trade_plan_id: str | None = None
    approval_id: str | None = None
    order_id: str | None = None
    position_id: str | None = None
    payload_json: str = ""
    created_at_utc: datetime | None = None  # aware UTC; defaults to None

    def __post_init__(self) -> None:
        # T-03-04: validated non-empty strings with empty rejected at construction.
        _require_non_empty(self.event_type, "event_type")
        _require_non_empty(self.entity_type, "entity_type")
        # WR-08: every event must be correlatable — empty correlation or
        # entity ids silently break the audit-trail join.
        _require_non_empty(self.correlation_id, "correlation_id")
        _require_non_empty(self.entity_id, "entity_id")
        # payload_json is JSON-as-TEXT; "" means "no payload" (default),
        # any other value must parse.
        if self.payload_json != "":
            try:
                json.loads(self.payload_json)
            except ValueError as exc:
                raise ValueError(f"payload_json must be valid JSON: {exc}") from exc
        # D-12: UTC-aware datetimes only.
        _require_utc_aware(self.occurred_at_utc, "occurred_at_utc")
        if self.created_at_utc is not None:
            _require_utc_aware(self.created_at_utc, "created_at_utc")
