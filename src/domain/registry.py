"""Parameter registry loader (Phase 3, plans 03-01 + 03-03).

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
  - Parameter names are restricted to 7-bit ASCII so code-point
    sorting matches the documented canonical profile; non-ASCII
    names raise `StrategyKeyOutsideRegistry`.
  - Whole-number TOML values normalize to int; fractional values
    become Decimal built from the original string form so trailing
    precision is preserved (D-12).
  - Volatile sidecar fields (author, timestamp) never enter the
    hashed body; editing them does not change the hash.
  - Canonicalizes + hashes — `parameter_set_hash` is SHA256 over the
    canonical JSON of the normalized params doc.
  - `verify_parameter_set(path, expected_hash)` re-hashes a TOML file
    and raises `ParameterSetMutated` on mismatch.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .canonical import sha256_hex

REGISTRY_ROOT = Path("params")
SCHEMA_VERSION = 1

# Registry path segments are restricted to this charset so
# `REGISTRY_ROOT / strategy_id / f"{parameter_set_id}.toml"` cannot
# escape `params/` (WR-05: fail closed on `../../etc`-style inputs).
_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _check_registry_segment(value: str, field_name: str) -> None:
    """Raise UnregisteredParameterSet if a path segment is unsafe."""
    if not _SEGMENT_RE.fullmatch(value):
        raise UnregisteredParameterSet(
            f"invalid registry path segment {field_name}={value!r}"
        )

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


def _extract_raw_param_strings(text: str) -> dict[str, str]:
    """Extract the original string form of each parameter value from TOML text.

    The stdlib `tomllib` parses `1.50` as Python float `1.5`, losing
    the trailing precision. To preserve trailing precision (D-12),
    we read the raw TOML text and extract the original string form
    of each value in the `[parameters]` section.

    Returns a dict mapping parameter name → original string form.
    Only includes keys that appear in the `[parameters]` section.
    """
    raw: dict[str, str] = {}
    in_params = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_params = stripped == "[parameters]"
            continue
        if not in_params or not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_\-]+)\s*=\s*(.+)$", stripped)
        if match:
            key = match.group(1)
            value = match.group(2).strip()
            raw[key] = value
    return raw


def _normalize_params(
    params: dict[str, Any],
    raw_strings: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Normalize a TOML params dict for canonical hashing.

    TOML parses integers as int and floats as float. We coerce
    whole-number floats to int (preserving the integer type) and
    convert non-integral floats to Decimal (D-12: float is banned
    for exchange-sensitive values; the canonicalizer rejects float
    loudly, so we must convert before hashing).

    If `raw_strings` is provided, fractional values are built from
    the original TOML string form to preserve trailing precision
    (e.g. `1.50` stays `Decimal("1.50")`, not `Decimal("1.5")`).
    """
    normalized: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, float):
            if value.is_integer():
                normalized[key] = int(value)
            else:
                if raw_strings is not None and key in raw_strings:
                    normalized[key] = Decimal(raw_strings[key])
                else:
                    normalized[key] = Decimal(str(value))
        else:
            normalized[key] = value
    return normalized


def _check_ascii_keys(params: dict[str, Any], path: Path) -> None:
    """Raise StrategyKeyOutsideRegistry if any parameter name is non-ASCII.

    Per CONFIGURATION §9 + RESEARCH_PROTOCOL §5: parameter names are
    restricted to 7-bit ASCII so code-point sorting matches the
    documented canonical profile.
    """
    for key in params:
        if not key.isascii():
            raise StrategyKeyOutsideRegistry(
                f"{path}: non-ASCII parameter name {key!r} "
                f"(parameter names must be 7-bit ASCII)"
            )


def load_parameter_set(strategy_id: str, parameter_set_id: str) -> ParameterSet:
    """Load and validate a parameter set from the registry.

    Raises:
        UnregisteredParameterSet: file does not exist (or either id
            contains path-unsafe characters — fail closed, WR-05).
        RegistrySchemaMismatch: schema_version does not match.
        StrategyKeyOutsideRegistry: unknown or non-ASCII strategy-semantic key.
    """
    _check_registry_segment(strategy_id, "strategy_id")
    _check_registry_segment(parameter_set_id, "parameter_set_id")
    path = REGISTRY_ROOT / strategy_id / f"{parameter_set_id}.toml"
    if not path.is_file():
        raise UnregisteredParameterSet(f"{strategy_id}/{parameter_set_id}")

    text = path.read_bytes().decode("utf-8")
    doc = tomllib.loads(text)

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

    # CR-06: fail closed on absent identity/semantic sections — a
    # truncated file must never load as a valid empty parameter set.
    if "strategy_version" not in strategy or not strategy["strategy_version"]:
        raise RegistrySchemaMismatch(f"{path}: missing strategy.strategy_version")
    if "parameters" not in doc or not isinstance(doc["parameters"], dict):
        raise RegistrySchemaMismatch(f"{path}: missing [parameters] table")
    params = doc["parameters"]

    _check_ascii_keys(params, path)
    unknown_keys = set(params.keys()) - STRATEGY_KEYS
    if unknown_keys:
        raise StrategyKeyOutsideRegistry(
            f"{path}: unknown strategy-semantic keys: {sorted(unknown_keys)}"
        )

    raw_strings = _extract_raw_param_strings(text)
    normalized_params = _normalize_params(params, raw_strings)
    strategy_version = strategy["strategy_version"]

    # Hash the normalized params + strategy identity (excluding
    # schema_version and volatile sidecar fields like author/timestamp,
    # which are metadata about the file, not the parameter set itself).
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
    text = path.read_bytes().decode("utf-8")
    doc = tomllib.loads(text)
    strategy = doc.get("strategy", {})
    params = doc.get("parameters", {})
    raw_strings = _extract_raw_param_strings(text)
    normalized_params = _normalize_params(params, raw_strings)

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


def check_strategy_key_outside_registry(ambient: dict[str, Any]) -> None:
    """Raise StrategyKeyOutsideRegistry if any whitelisted strategy key appears.

    D-06: strategy-semantic keys live ONLY in the registry. If a
    whitelisted key appears in ambient configuration (env vars, CLI
    flags, etc.), the loader raises StrategyKeyOutsideRegistry
    instead of silently altering semantics.

    Runtime config (endpoints, tokens, log levels, poll intervals)
    is allowed in ambient configuration — only strategy-semantic
    keys are rejected.
    """
    smuggled = set(ambient.keys()) & STRATEGY_KEYS
    if smuggled:
        raise StrategyKeyOutsideRegistry(
            f"strategy-semantic keys found outside registry: {sorted(smuggled)}"
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
    "check_strategy_key_outside_registry",
]
