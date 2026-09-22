"""Parameter registry loader (Phase 3, plan 03-01).

Per D-04/D-05/D-06: file-based TOML registry is the source of truth;
identity = parameterSetId + parameterSetHash (SHA256 over canonical
JSON); loader is fail-closed (raises on unregistered/mutated/unknown
keys, never silent fallback).

Contract:
  - `load_parameter_set(strategy_id, parameter_set_id)` resolves
    `params/<strategy_id>/<parameter_set_id>.toml` — missing file
    raises `UnregisteredParameterSet`.
  - Parses with stdlib `tomllib`; validates `schema_version` against
    `SCHEMA_VERSION` — mismatch raises `RegistrySchemaMismatch`.
  - Validates strategy identity fields; rejects unknown
    strategy-semantic keys — raises `StrategyKeyOutsideRegistry`.
  - Canonicalizes + hashes — `parameter_set_hash` is SHA256 over the
    canonical JSON of the normalized params doc.
  - `verify_parameter_set(path, expected_hash)` re-hashes a TOML file
    and raises `ParameterSetMutated` on mismatch.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .canonical import sha256_hex

REGISTRY_ROOT = Path("params")
SCHEMA_VERSION = 1

# Closed whitelist of strategy-semantic keys (D-06). Anything
# strategy-semantic found OUTSIDE the registry raises; anything
# unknown INSIDE raises.
STRATEGY_KEYS = frozenset(
    {
        "swing_lookback",
        "zone_tolerance_atr",
        "breakout_confirmation_bars",
        "entry_buffer_atr",
        "sl_buffer_atr",
        "minimum_rr",
        "signal_expiry_hours",
        "risk_rate",
        "minimum_risk_utilization_after_rounding",
    }
)


class UnregisteredParameterSet(Exception):
    """Raised when a parameter set file does not exist in the registry."""


class ParameterSetMutated(Exception):
    """Raised when a parameter set's hash does not match the expected value."""


class RegistrySchemaMismatch(Exception):
    """Raised when a TOML file's schema_version does not match SCHEMA_VERSION."""


class StrategyKeyOutsideRegistry(Exception):
    """Raised when a TOML file contains an unknown strategy-semantic key."""


@dataclass(frozen=True)
class ParameterSet:
    """A loaded, validated, hashed parameter set.

    `parameter_set_hash` is SHA256 over the canonical JSON of the
    normalized params doc. Once referenced by a backtest/alert/order
    plan, the hash is permanent (D-04).
    """

    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    params: dict[str, Any]  # normalized values (Decimals preserved, not floats)


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize a TOML params dict for canonical hashing.

    TOML parses integers as int and floats as float. We coerce
    whole-number floats to int (preserving the integer type) and
    convert non-integral floats to Decimal (D-12: float is banned
    for exchange-sensitive values; the canonicalizer rejects float
    loudly, so we must convert before hashing).
    """
    normalized: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, float):
            if value.is_integer():
                normalized[key] = int(value)
            else:
                normalized[key] = Decimal(str(value))
        else:
            normalized[key] = value
    return normalized


def load_parameter_set(strategy_id: str, parameter_set_id: str) -> ParameterSet:
    """Load and validate a parameter set from the registry.

    Raises:
        UnregisteredParameterSet: file does not exist.
        RegistrySchemaMismatch: schema_version does not match.
        StrategyKeyOutsideRegistry: unknown strategy-semantic key.
    """
    path = REGISTRY_ROOT / strategy_id / f"{parameter_set_id}.toml"
    if not path.is_file():
        raise UnregisteredParameterSet(f"{strategy_id}/{parameter_set_id}")

    doc = tomllib.loads(path.read_bytes().decode("utf-8"))

    if doc.get("schema_version") != SCHEMA_VERSION:
        raise RegistrySchemaMismatch(
            f"{path}: schema_version={doc.get('schema_version')!r}, "
            f"expected {SCHEMA_VERSION}"
        )

    strategy = doc.get("strategy", {})
    if strategy.get("strategy_id") != strategy_id:
        raise StrategyKeyOutsideRegistry(
            f"{path}: strategy.strategy_id={strategy.get('strategy_id')!r} "
            f"does not match path strategy_id={strategy_id!r}"
        )

    params = doc.get("parameters", {})
    unknown_keys = set(params.keys()) - STRATEGY_KEYS
    if unknown_keys:
        raise StrategyKeyOutsideRegistry(
            f"{path}: unknown strategy-semantic keys: {sorted(unknown_keys)}"
        )

    normalized_params = _normalize_params(params)
    strategy_version = strategy.get("strategy_version", "")

    # Hash the normalized params + strategy identity (excluding
    # schema_version, which is metadata about the file format, not
    # the parameter set itself).
    hash_payload = {
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "parameter_set_id": parameter_set_id,
        "parameters": normalized_params,
    }
    parameter_set_hash = sha256_hex(hash_payload)

    return ParameterSet(
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set_hash,
        params=normalized_params,
    )


def verify_parameter_set(path: Path, expected_hash: str) -> None:
    """Re-hash a TOML file and raise ParameterSetMutated on mismatch.

    D-04/D-05: once a parameter set is referenced, its hash is
    permanent. Any mutation raises ParameterSetMutated.
    """
    doc = tomllib.loads(path.read_bytes().decode("utf-8"))
    strategy = doc.get("strategy", {})
    params = doc.get("parameters", {})
    normalized_params = _normalize_params(params)

    hash_payload = {
        "strategy_id": strategy.get("strategy_id", ""),
        "strategy_version": strategy.get("strategy_version", ""),
        "parameter_set_id": path.stem,
        "parameters": normalized_params,
    }
    actual_hash = sha256_hex(hash_payload)
    if actual_hash != expected_hash:
        raise ParameterSetMutated(
            f"{path}: expected {expected_hash}, got {actual_hash}"
        )


__all__ = [
    "REGISTRY_ROOT",
    "SCHEMA_VERSION",
    "STRATEGY_KEYS",
    "ParameterSet",
    "UnregisteredParameterSet",
    "ParameterSetMutated",
    "RegistrySchemaMismatch",
    "StrategyKeyOutsideRegistry",
    "load_parameter_set",
    "verify_parameter_set",
]
