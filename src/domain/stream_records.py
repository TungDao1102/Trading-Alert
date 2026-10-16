"""Journal records for the first callers of the Binance user-data stream (Phase 18, plan 08).

Pure module: standard library plus ``src.domain.journal`` only (no adapter, no SDK, no database
import). Every builder takes its time as an argument (never a wall clock) and returns a
``JournalEvent`` whose id is ``correlated_event_id`` over stable inputs, so the same inputs give
the same event and a replay is an idempotent no-op in the append-only journal (D-10).

UNKNOWN exits (G4-034, D051 item i, D-08). An Order or a Position leaves ``UNKNOWN`` only with
Binance evidence: a REST reconcile query or a user-data stream event, never local inference such
as a timeout or an operator guess. ``ExitEvidence`` carries that evidence and
``exit_evidence_event`` turns it into the UNKNOWN_EXIT_EVIDENCE journal event the store appends
in the same transaction as the status change. The id is keyed on (correlation, entity, step
``"<from>-><to>"``), so the same exit recorded twice is one row, and a second record of the same
exit with a different source or reference is a journal conflict, never a silent second row.

Stream anomalies (D-05, D-08). ``stream_anomaly_event`` records a stream message that did not
become a typed event. Its id is keyed on (session, anomaly kind, payload hash): a duplicate frame
in one session is one record. ``kind`` is a plain string so this module imports nothing from
``src.adapters``.

Payloads are sorted-key compact ASCII JSON of text values only (no Decimal, no float). They never
carry a listenKey, a credential or raw account data: references are restricted to printable
non-space ASCII and refuse credential-shaped words, and anomaly details are the field-name-only
text the stream parser already produced.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from src.domain.journal import JournalEvent, correlated_event_id

UNKNOWN_EXIT_EVIDENCE = "UNKNOWN_EXIT_EVIDENCE"
STREAM_ANOMALY = "STREAM_ANOMALY"
USER_DATA_STREAM = "USER_DATA_STREAM"

EXIT_EVIDENCE_PREFIX = "ev"
STREAM_ANOMALY_PREFIX = "sa"

# The state machines whose UNKNOWN exit must be backed by Binance evidence.
EXIT_EVIDENCE_ENTITY_TYPES = frozenset({"ORDER", "POSITION"})
UNKNOWN_STATUS = "UNKNOWN"

DETAIL_MAX_CHARS = 200
EVENT_NAME_MAX_CHARS = 64
FIELD_PATH_MAX_CHARS = 64
# journal_events.correlation_id and entity_id are VARCHAR(128).
_ID_MAX_CHARS = 128
_STATUS_MAX_CHARS = 32

# Printable ASCII without whitespace: a reference is an identifier, never free text.
_REFERENCE = re.compile(r"[!-~]+")
# Credential-shaped words a reference must never contain (case-insensitive).
_FORBIDDEN_REFERENCE_WORDS = ("listenkey", "apikey", "api_key", "secret", "signature", "password")
_ANOMALY_KIND = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_STATUS = re.compile(r"[A-Z][A-Z_]*")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class EvidenceSource(str, Enum):
    """Where the Binance evidence for an UNKNOWN exit came from (G4-034)."""

    REST_RECONCILE = "REST_RECONCILE"
    USER_DATA_EVENT = "USER_DATA_EVENT"


def _require_text(value: object, field_name: str, max_chars: int) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > max_chars:
        raise ValueError(f"{field_name} must be at most {max_chars} characters")
    return value


def _optional_text(value: object, field_name: str, max_chars: int) -> None:
    if value is not None:
        _require_text(value, field_name, max_chars)


def _require_utc_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return value


def _require_status(value: object, field_name: str) -> str:
    text = _require_text(value, field_name, _STATUS_MAX_CHARS)
    if not _STATUS.fullmatch(text):
        raise ValueError(f"{field_name} must be an upper-case status name")
    return text


def _payload(values: dict[str, str | None]) -> str:
    return json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class ExitEvidence:
    """Binance evidence that moves an Order or a Position out of UNKNOWN.

    `reference` identifies the evidence (for example the event name, event time and order id of
    a user-data event, or the REST query that answered); it is printable ASCII without spaces and
    never a credential. `correlation_id` ties the record to the stream session or reconcile run
    that observed it. `detail` is an optional note of at most 200 characters for logs; it is not
    journaled.
    """

    source: EvidenceSource
    observed_at_utc: datetime
    reference: str
    correlation_id: str
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, EvidenceSource):
            raise TypeError(f"source must be EvidenceSource, got {type(self.source).__name__}")
        _require_utc_aware(self.observed_at_utc, "observed_at_utc")
        reference = _require_text(self.reference, "reference", _ID_MAX_CHARS)
        if not _REFERENCE.fullmatch(reference):
            raise ValueError("reference must be printable ASCII without whitespace")
        lowered = reference.lower()
        if any(word in lowered for word in _FORBIDDEN_REFERENCE_WORDS):
            raise ValueError("reference must not carry a credential-shaped value")
        _require_text(self.correlation_id, "correlation_id", _ID_MAX_CHARS)
        _optional_text(self.detail, "detail", DETAIL_MAX_CHARS)


def exit_evidence_event(
    *,
    entity_type: str,
    entity_id: str,
    from_status: str,
    to_status: str,
    evidence: ExitEvidence,
    now_utc: datetime,
    order_id: str | None = None,
    position_id: str | None = None,
) -> JournalEvent:
    """The UNKNOWN_EXIT_EVIDENCE journal event of one UNKNOWN exit (pure, deterministic).

    Raises:
        TypeError: `evidence` is not an `ExitEvidence`.
        ValueError: the entity type is not ORDER or POSITION, `from_status` is not UNKNOWN,
            `to_status` equals it, a field is empty or too long, or `now_utc` is not UTC.
    """
    if not isinstance(evidence, ExitEvidence):
        raise TypeError(f"evidence must be ExitEvidence, got {type(evidence).__name__}")
    if entity_type not in EXIT_EVIDENCE_ENTITY_TYPES:
        raise ValueError("entity_type must be ORDER or POSITION")
    _require_text(entity_id, "entity_id", _ID_MAX_CHARS)
    if _require_status(from_status, "from_status") != UNKNOWN_STATUS:
        raise ValueError("from_status must be UNKNOWN")
    if _require_status(to_status, "to_status") == UNKNOWN_STATUS:
        raise ValueError("to_status must differ from UNKNOWN")
    _require_utc_aware(now_utc, "now_utc")
    _optional_text(order_id, "order_id", _ID_MAX_CHARS)
    _optional_text(position_id, "position_id", _ID_MAX_CHARS)
    event_id = correlated_event_id(
        prefix=EXIT_EVIDENCE_PREFIX,
        correlation_id=evidence.correlation_id,
        event_type=UNKNOWN_EXIT_EVIDENCE,
        entity_id=entity_id,
        step=f"{from_status}->{to_status}",
    )
    payload = _payload(
        {
            "evidence_source": evidence.source.value,
            "from_status": from_status,
            "observed_at_utc": evidence.observed_at_utc.isoformat(),
            "reference": evidence.reference,
            "to_status": to_status,
        }
    )
    return JournalEvent(
        journal_event_id=event_id,
        occurred_at_utc=now_utc,
        event_type=UNKNOWN_EXIT_EVIDENCE,
        entity_type=entity_type,
        entity_id=entity_id,
        correlation_id=evidence.correlation_id,
        order_id=order_id,
        position_id=position_id,
        payload_json=payload,
        created_at_utc=now_utc,
    )


__all__ = [
    "DETAIL_MAX_CHARS",
    "EXIT_EVIDENCE_ENTITY_TYPES",
    "STREAM_ANOMALY",
    "UNKNOWN_EXIT_EVIDENCE",
    "USER_DATA_STREAM",
    "EvidenceSource",
    "ExitEvidence",
    "exit_evidence_event",
]
