"""Approval short-id to full-id mapping (Phase 8, plan 08-02).

Per D-02: Telegram `callback_data` is capped at 64 bytes, but real
`signal_id` values (content-hash strings, 128+ hex chars) and the full
identity tuple (plan_hash + version + parameter_set_id +
parameter_set_hash) cannot fit. The Phase-7 sender hashes
`signal_id` to a 32-hex prefix (`sha256(signal_id)[:32]`) and embeds
that short id in the callback payload. Phase 8 binds real handlers,
so the receiver must reverse the mapping deterministically — without
holding the raw `signal_id` or `trade_plan_id` in memory across a
process restart.

This module defines the canonical short→full mapping record type.
The record carries the deterministic short id, the full `signal_id`
and `trade_plan_id`, and a UTC-aware `created_at_utc` timestamp.

Persistence responsibility (D-02):
  - The receiver writes the row in the SAME database transaction as
    the Approval row transition (atomic write; mapping insert plus
    approval transition commit together, never in separate commits).
  - The mapping module itself is dependency-free: stdlib +
    `src/domain/*` only. No Telegram, no Binance SDK, no SQLAlchemy,
    no Pydantic. The ORM row lives in `src/db/models.py`; the
    `to_row` / `from_row` translation lives in `src/db/mappers.py`.

Charset (D-02):
  - `short_id` is exactly 32 lowercase hex chars (sha256 prefix).
  - `signal_id` and `trade_plan_id` are content-hash strings
    (String(128) on the ORM side).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

# Length of the SHA-256 hex prefix used as the Telegram short id.
# 32 hex chars × 1 byte = 32 bytes — fits any prefix under the 64-byte
# Telegram ceiling (e.g. "APR:" + 32 hex = 36 bytes).
SHORT_ID_LENGTH: int = 32


def derive_short_id(signal_id: str) -> str:
    """Return the canonical short id for a `signal_id`.

    Per D-02: the short id is `sha256(signal_id)[:32]` — a 32-hex-char
    prefix that fits inside Telegram's 64-byte `callback_data` ceiling
    with room for a 4-byte prefix (`APR:` / `SKP:` / `SIM:` / `SKIP:`).
    Deterministic across processes and Python versions.
    """
    if not isinstance(signal_id, str) or signal_id == "":
        raise ValueError("signal_id must be a non-empty string")
    return hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:SHORT_ID_LENGTH]


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive datetimes loudly (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field_name} must be UTC, got offset {offset}")


@dataclass(frozen=True)
class ShortIdMapping:
    """The canonical short→full id mapping record.

    `short_id` is the deterministic 32-hex prefix of
    `sha256(signal_id)`. `signal_id` and `trade_plan_id` are the full
    content-hash ids used everywhere else in the project. The
    `created_at_utc` field is UTC-aware.

    The receiver (08-02 telegram_callbacks) constructs a
    `ShortIdMapping` for every alert it sends and persists it in the
    same transaction as the Approval row. The replay resolution path
    (`src/approval/replay.py`) accepts a `lookup_by_short_id`
    callable that returns the full `(signal_id, trade_plan_id)` pair
    given a short id — see the receiver for the wiring.
    """

    short_id: str
    signal_id: str
    trade_plan_id: str
    created_at_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.short_id, str):
            raise TypeError(f"short_id must be str, got {type(self.short_id).__name__}")
        if len(self.short_id) != SHORT_ID_LENGTH:
            raise ValueError(
                f"short_id must be {SHORT_ID_LENGTH} hex chars, got "
                f"{len(self.short_id)}: {self.short_id!r}"
            )
        if any(c not in "0123456789abcdef" for c in self.short_id):
            raise ValueError(f"short_id must be lowercase hex, got {self.short_id!r}")
        if not isinstance(self.signal_id, str) or self.signal_id == "":
            raise ValueError("signal_id must be a non-empty string")
        if not isinstance(self.trade_plan_id, str) or self.trade_plan_id == "":
            raise ValueError("trade_plan_id must be a non-empty string")
        _require_utc_aware(self.created_at_utc, "created_at_utc")


def make_short_id_mapping(
    *,
    signal_id: str,
    trade_plan_id: str,
    created_at_utc: datetime | None = None,
) -> ShortIdMapping:
    """Build a `ShortIdMapping` from the canonical inputs.

    Convenience constructor: derives the short id, defaults
    `created_at_utc` to `datetime.now(UTC)` when not supplied. Use
    the dataclass directly when the caller has already computed the
    short id (e.g. the keyboard builder path that emits
    `APR:<short>`).
    """
    if created_at_utc is None:
        created_at_utc = datetime.now(UTC)
    _require_utc_aware(created_at_utc, "created_at_utc")
    return ShortIdMapping(
        short_id=derive_short_id(signal_id),
        signal_id=signal_id,
        trade_plan_id=trade_plan_id,
        created_at_utc=created_at_utc,
    )


__all__ = [
    "SHORT_ID_LENGTH",
    "ShortIdMapping",
    "derive_short_id",
    "make_short_id_mapping",
]
