"""JournalEvent frozen dataclass (Phase 3, plan 03-02).

Per D-01/D-02/D-12: frozen pure-Python dataclass with timezone-aware
UTC datetime fields. JournalEvent is append-only and never substitutes
for current-state tables (DATA_MODEL §2.10).

`event_type` and `entity_type` are validated non-empty strings with
empty values rejected at construction (T-03-04). Enum promotion is
deferred to Phase 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


def _require_non_empty(value: str, field_name: str) -> None:
    """Reject empty strings for validated non-empty fields (T-03-04)."""
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(
            f"{field_name} must be UTC, got offset {value.utcoffset()}"
        )


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
        # D-12: UTC-aware datetimes only.
        _require_utc_aware(self.occurred_at_utc, "occurred_at_utc")
        if self.created_at_utc is not None:
            _require_utc_aware(self.created_at_utc, "created_at_utc")
