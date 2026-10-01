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

Phase 17 (D-12, F-410) adds two Decimal helpers that sit beside, never inside,
the scalar policy above: `canonical_decimal_text` (the D047 spelling-invariant
text, moved here from `src/backtest/costs.py`) and `quantize_for_storage`
(NUMERIC(38,18) scale, ROUND_HALF_EVEN). `canonical_scalars`/`canonical_bytes`
are unchanged: registry hashes, signal ids and cost hashes depend on them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
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


# --------------------------------------------------------------------------- #
# Decimal helpers (Phase 17, D-12) — spelling-invariant text and storage scale.
# --------------------------------------------------------------------------- #

#: Fractional digits of the PostgreSQL NUMERIC(38,18) plan columns (D-12).
STORAGE_DECIMAL_PLACES = 18

# Working precision for `quantize_for_storage`: far above NUMERIC(38,18)'s 38
# digits so a legitimate value never trips InvalidOperation, yet finite so a
# runaway magnitude still fails closed instead of quantizing silently.
_STORAGE_WORKING_PREC = 60
_STORAGE_QUANTUM = Decimal(1).scaleb(-STORAGE_DECIMAL_PLACES)


def canonical_decimal_text(value: Decimal) -> str:
    """Render a Decimal as one plain (non-exponent) text form (D047, D-15).

    Zero, in any spelling including negative zero, renders as "0". Every
    other value renders as its plain positional text with trailing zeros
    removed, so 1, 1.0 and Decimal("1.00") all render "1", 0.00020 renders
    "0.0002", and 100 stays "100" (never "1E+2"). Built from the digit tuple
    so it does not depend on the ambient Decimal context precision.
    """
    if not value.is_finite():
        raise ValueError(f"decimal value must be finite, got {value}")
    if value == 0:
        return "0"
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)  # finite Decimal
    mantissa = list(digits)
    while len(mantissa) > 1 and mantissa[-1] == 0:
        mantissa.pop()
        exponent += 1
    return format(Decimal((sign, tuple(mantissa), exponent)), "f")


def quantize_for_storage(value: Decimal) -> Decimal:
    """Round a Decimal to the NUMERIC(38,18) scale with ROUND_HALF_EVEN (D-12).

    The result always carries exactly 18 fractional digits, the spelling a
    PostgreSQL NUMERIC(38,18) read-back returns, so a persisted plan value
    is identical before and after storage. Runs in a local context with
    precision 60 (ambient precision is ignored); non-finite input, or a
    result too large for that precision, raises ValueError (fail closed).
    """
    if not value.is_finite():
        raise ValueError(f"decimal value must be finite, got {value}")
    with localcontext() as ctx:
        ctx.prec = _STORAGE_WORKING_PREC
        try:
            return value.quantize(_STORAGE_QUANTUM, rounding=ROUND_HALF_EVEN)
        except InvalidOperation as exc:
            raise ValueError(
                f"decimal value {value} cannot be quantized to {STORAGE_DECIMAL_PLACES} places"
            ) from exc
