"""Canonical-hash identity (Phase 3, plan 03-01).

Per D-04/D-12: a single canonicalizer owns scalar normalization →
`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True,
allow_nan=False)` → UTF-8 → `hashlib.sha256().hexdigest()`. Both
`registry.py` (parameterSetHash) and `ids.py` (SignalId/plan/order IDs)
call it.

Policy:
  - Decimal → str() preserving full precision (Decimal("1.50") stays
    "1.50", never "1.5")
  - datetime → normalized to UTC then isoformat() (any aware tz is
    accepted here; `astimezone(UTC)` collapses the same
    instant to one rendering — callers must already enforce UTC-aware
    at the domain boundary; naive raises). Canonical rendering uses
    the `+00:00` suffix (never `Z`): `fromisoformat` round-trips both
    on 3.11+, but the hash input is always the `+00:00` spelling.
  - Enum → .value
  - dict → recursive, sorted keys
  - list/tuple → order-preserving
  - set/frozenset → REJECTED (unordered — fail closed, never silently
    sort)
  - float → REJECTED (no canonical JSON form for NaN/inf; use
    Decimal/str/int)
  - any other type → no `default=str` fallback; json.dumps raises
    TypeError loudly
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def canonical_scalars(value: Any) -> Any:
    """Recursively normalize a value into a canonical-JSON-safe form.

    See module docstring for the full policy.
    """
    if isinstance(value, dict):
        return {k: canonical_scalars(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonical_scalars(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)  # full precision: "1.50" ≠ "1.5" by design
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime in canonical hash input")
        # WR-01: normalize to UTC so the same instant hashes identically
        # regardless of caller timezone representation (e.g. +00:00 vs
        # +07:00). Canonical rendering keeps the `+00:00` suffix.
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        raise TypeError("unordered set in canonical hash input — use a sorted list")
    if isinstance(value, float):
        raise TypeError("float in canonical hash input — use Decimal/str/int")
    # str/int/bool/None pass through; anything else → json TypeError
    return value


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize a payload to canonical JSON bytes (UTF-8).

    Uses sorted keys, compact separators, ensure_ascii=True, and
    allow_nan=False to guarantee byte-equivalent output across
    processes and Python versions.
    """
    return json.dumps(
        canonical_scalars(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(payload: dict[str, Any]) -> str:
    """Return the SHA256 hex digest of the canonical JSON bytes."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
