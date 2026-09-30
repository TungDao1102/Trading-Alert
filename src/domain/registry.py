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

REGISTRY_ROOT = Path(__file__).resolve().parents[2] / "params"
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
        # Family B (breakout-retest) — added in plan 04-03 (D-05).
        "retest_window_bars",
        "retest_depth_atr",
        "breakout_volume_threshold",
        # Family C (range-mr) — added in plan 04-03 (D-05).
        "zone_min_touches",
        "zone_aging_bars",
        "range_break_buffer_atr",
        "regime_filter_lookback",
        # Detector volatility knobs — promoted to the registry in the
        # Phase 04 review fix (CR-01). Previously silent `.get()`
        # code defaults in the Family B/C detectors; now versioned
        # parameters that fail closed (KeyError) when absent.
        "atr_period",
        "touch_tolerance_atr",
        # Phase 5 D-05 additions (D-03 portfolio + cost model).
        # Portfolio gates (research baselines per RISK_MANAGEMENT §§4-5).
        "max_open_positions",
        "max_aggregate_open_risk",
        "cluster_cap",
        # Daily PnL state machine (RISK_MANAGEMENT §8).
        "daily_loss_warning_threshold",
        "daily_loss_stop_threshold",
        # Cost model keys (RISK_MANAGEMENT §3) — Phase-6-compatible.
        "fee_rate_entry",
        "fee_rate_exit",
        "expected_slippage",
        # Phase 6 plan 06-02 — extended cost-model keys (D-02 + Pitfall 7).
        # These keys were previously absent from the whitelist; cost
        # assumptions lived in code constants and two experiments with
        # different constants shared a costModelHash. Adding them to
        # STRATEGY_KEYS makes unknown cost keys fail closed exactly like
        # unknown strategy keys.
        "funding_treatment",
        "slippage_model",
        "spread_fill_assumptions",
        "partial_fill_fraction",
        # Constraint-snapshot freshness (RISK_MANAGEMENT §12).
        "constraint_snapshot_ttl_seconds",
        # Phase 11 (D037): protective-trigger price source. Optional; absent in
        # sets that predate it. Deliberately NOT a cost key (COST_KEYS in
        # src/backtest/costs.py), so cost_model_hash is unaffected.
        # NOTE: check_strategy_key_outside_registry now also rejects ambient
        # config named working_type; runtime configuration must use another name.
        "working_type",
        # Phase 12 (D-06, D-07, D-11). Optional: absent in sets that predate
        # Phase 12, like working_type, so every older set keeps loading and
        # keeps its parameter_set_hash.
        #   exit_slippage_rate          stop-market exit slippage, separate from the
        #                               entry-side expected_slippage (D-06). Deliberately
        #                               NOT a member of the 7-key COST_KEYS tuple;
        #                               plan 12-03 adds it to the cost model presence-driven.
        #   min_stop_distance_rate      minimum stop distance as a fraction of price (D-07)
        #   max_cost_to_risk            ceiling on round-trip cost over risk amount (D-07)
        #   commission_rate_ttl_seconds freshness window of the account commission rate (D-11)
        "exit_slippage_rate",
        "min_stop_distance_rate",
        "max_cost_to_risk",
        "commission_rate_ttl_seconds",
    }
)

# Fee and slippage rates are decimal fractions of notional (0.0005 is 5 bps). A value
# above this ceiling is a unit error (a fee of 2 typed for 0.0002, a percent or bps
# figure) and is refused at load (D-04, F-028). 0.01 is 100 bps, far above any real
# Binance fee tier or modeled slippage.
RATE_UNIT_KEYS = frozenset(
    {"fee_rate_entry", "fee_rate_exit", "expected_slippage", "exit_slippage_rate"}
)
MAX_RATE = Decimal("0.01")

# Closed set of admissible working_type values (D037). Anything else, e.g. LAST or
# CONTRACT_PRICE, fails closed at load. Only MARK_PRICE is admitted because live
# placement hard-codes it and no backtest/paper code reads the key yet; accepting
# CONTRACT_PRICE would hash a claim the engine ignores. Widen only together with the
# consumers (roadmap phases 14 and 19).
WORKING_TYPE_VALUES = frozenset({"MARK_PRICE"})


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


def _strip_inline_comment(s: str) -> str:
    """Cut a TOML line at the first `#` outside string literals."""
    in_single = False
    in_double = False
    escaped = False
    for i, ch in enumerate(s):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return s[:i]
    return s


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
        match = re.match(r'^(?:"([^"]+)"|([A-Za-z0-9_\-]+))\s*=\s*(.+)$', stripped)
        if match:
            key = match.group(1) if match.group(1) is not None else match.group(2)
            value = _strip_inline_comment(match.group(3)).strip()
            raw[key] = value
    return raw


def _normalize_value(value: Any, raw: str | None) -> Any:
    """Normalize one value, recursing into lists/tuples/dicts (WR-13).

    `raw` is the original TOML spelling, meaningful only for a
    top-level scalar float; nested floats fall back to `Decimal(str)`.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        if raw is not None:
            return Decimal(raw)
        return Decimal(str(value))
    if isinstance(value, list):
        return [_normalize_value(v, None) for v in value]
    if isinstance(value, tuple):
        return [_normalize_value(v, None) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_value(v, None) for k, v in value.items()}
    return value


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
        raw: str | None = None
        if raw_strings is not None and isinstance(value, float):
            raw = raw_strings.get(key)
        normalized[key] = _normalize_value(value, raw)
    return normalized


# Expected value types per key (WR-06: fail closed at the registry
# boundary instead of surfacing type errors in Phase 4 arithmetic).
# Integer-count keys must be int; ratio/threshold keys accept int or
# Decimal (whole-number TOML spellings like `minimum_rr = 2.0`
# normalize to int 2, which stays valid). bool is rejected everywhere
# even though bool subclasses int.
INT_KEYS = frozenset(
    {
        "swing_lookback",
        "breakout_confirmation_bars",
        "signal_expiry_hours",
        # Family B (breakout-retest) — added in plan 04-03 (D-05).
        "retest_window_bars",
        # Family C (range-mr) — added in plan 04-03 (D-05).
        "zone_min_touches",
        "zone_aging_bars",
        "regime_filter_lookback",
        # Detector volatility knob — Phase 04 review fix (CR-01).
        "atr_period",
        # Phase 5 D-05 additions — count-like keys (Pitfall 5).
        "max_open_positions",
        "constraint_snapshot_ttl_seconds",
        # Phase 12 (D-11): commission-rate freshness window, seconds.
        "commission_rate_ttl_seconds",
    }
)
# Phase 6 plan 06-02 — string-valued cost-model keys (D-02 + Pitfall 7).
# These keys carry model-assumption identifiers (funding mode, slippage
# model, spread assumptions) rather than numeric values. They are
# validated as non-empty strings at load time.
STRING_KEYS = frozenset(
    {
        "funding_treatment",
        "slippage_model",
        "spread_fill_assumptions",
        "working_type",
    }
)
DECIMAL_KEYS = STRATEGY_KEYS - INT_KEYS - STRING_KEYS


def _check_value_range(key: str, value: Any, path: Path) -> None:
    """Raise StrategyKeyOutsideRegistry on unit errors and out-of-range guard values.

    Only int / Decimal values reach this point (bool and wrong types were rejected
    by the per-type branches of `_check_param_types`).
    """
    number = Decimal(value)
    # 12-REVIEW WR-04: NaN and Infinity must never load, for any numeric key.
    # Without this, NaN compares raise decimal.InvalidOperation (wrong
    # exception) and unranged keys (risk_rate, minimum_rr) accept them.
    if not number.is_finite():
        raise StrategyKeyOutsideRegistry(
            f"{path}: parameter {key!r} must be finite, got {value}"
        )
    if key in RATE_UNIT_KEYS:
        if number < 0 or number > MAX_RATE:
            raise StrategyKeyOutsideRegistry(
                f"{path}: parameter {key!r} = {value} is a unit error: rates are "
                f"decimal fractions within 0 and {MAX_RATE} (0.0005 is 5 bps), "
                f"not percentages or whole numbers (F-028, D-04)"
            )
    elif key == "min_stop_distance_rate":
        if not (Decimal(0) < number < Decimal(1)):
            raise StrategyKeyOutsideRegistry(
                f"{path}: parameter {key!r} = {value} must be within the open "
                f"interval (0, 1) as a fraction of price (D-07)"
            )
    elif key == "max_cost_to_risk":
        if not (Decimal(0) < number <= Decimal(1)):
            raise StrategyKeyOutsideRegistry(
                f"{path}: parameter {key!r} = {value} must be within (0, 1] as a "
                f"fraction of the risk amount (D-07)"
            )
    elif key == "commission_rate_ttl_seconds" and number <= 0:
        raise StrategyKeyOutsideRegistry(
            f"{path}: parameter {key!r} = {value} must be greater than 0 seconds (D-11)"
        )


def _check_param_types(params: dict[str, Any], path: Path) -> None:
    """Raise StrategyKeyOutsideRegistry on wrong-typed parameter values."""
    for key, value in params.items():
        if isinstance(value, bool):
            raise StrategyKeyOutsideRegistry(
                f"{path}: parameter {key!r} must not be bool"
            )
        if key in INT_KEYS:
            if not isinstance(value, int):
                raise StrategyKeyOutsideRegistry(
                    f"{path}: parameter {key!r} must be int, "
                    f"got {type(value).__name__}"
                )
        elif key in STRING_KEYS:
            if not isinstance(value, str) or value == "":
                raise StrategyKeyOutsideRegistry(
                    f"{path}: parameter {key!r} must be a non-empty string, "
                    f"got {type(value).__name__}"
                )
            if key == "working_type" and value not in WORKING_TYPE_VALUES:
                raise StrategyKeyOutsideRegistry(
                    f"{path}: parameter 'working_type' must be one of "
                    f"{sorted(WORKING_TYPE_VALUES)}, got {value!r}"
                )
        elif key in DECIMAL_KEYS:
            if not isinstance(value, (int, Decimal)):
                raise StrategyKeyOutsideRegistry(
                    f"{path}: parameter {key!r} must be Decimal or int, "
                    f"got {type(value).__name__}"
                )
        if key in INT_KEYS or key in DECIMAL_KEYS:
            _check_value_range(key, value, path)


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


def _parse_and_validate(
    text: str,
    path: Path,
    strategy_id: str,
    parameter_set_id: str,
) -> tuple[str, dict[str, Any]]:
    """Parse TOML text and run every load-time validation (CR-05).

    Single shared path for `load_parameter_set` and
    `verify_parameter_set`: schema version, path-vs-content identity,
    required sections (CR-06), ASCII names, unknown-key whitelist, and
    per-key types (WR-06). Returns `(strategy_version, normalized_params)`.
    """
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
    _check_param_types(normalized_params, path)
    return strategy["strategy_version"], normalized_params


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
    strategy_version, normalized_params = _parse_and_validate(
        text, path, strategy_id, parameter_set_id
    )

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

    Identity (`strategy_id`/`parameter_set_id`) is derived from the
    file path — the same binding `load_parameter_set` uses — so a
    renamed or copied file verifies under its path identity, not the
    content's (CR-05). Every load-time validation runs first: schema,
    identity, required sections, whitelist, and types all raise here
    exactly as they do at load.
    """
    strategy_id = path.parent.name
    parameter_set_id = path.stem
    _check_registry_segment(strategy_id, "strategy_id")
    _check_registry_segment(parameter_set_id, "parameter_set_id")
    text = path.read_bytes().decode("utf-8")
    strategy_version, normalized_params = _parse_and_validate(
        text, path, strategy_id, parameter_set_id
    )

    hash_payload = {
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "parameter_set_id": parameter_set_id,
        "parameters": normalized_params,
    }
    actual_hash = sha256_hex(hash_payload)
    if actual_hash != expected_hash:
        raise ParameterSetMutated(
            f"{path}: expected {expected_hash}, got {actual_hash}"
        )


def _iter_ambient_keys(ambient: dict[str, Any]) -> Any:
    """Yield every key in a possibly nested ambient mapping."""
    for key, value in ambient.items():
        yield key
        if isinstance(value, dict):
            yield from _iter_ambient_keys(value)


def _is_strategy_key_name(name: object) -> bool:
    """Match a key against STRATEGY_KEYS, tolerating env-var spelling.

    Env-var rule: upper-case with an optional strategy prefix
    (`SWING_LOOKBACK`, `TREND_SWING_LOOKBACK`). Matching is
    case-insensitive on the full name or on the trailing `_`-separated
    suffix, so prefixed and unprefixed smuggling both raise.
    """
    if not isinstance(name, str):
        return False
    lowered = name.lower()
    if lowered in STRATEGY_KEYS:
        return True
    return any(lowered == sk or lowered.endswith("_" + sk) for sk in STRATEGY_KEYS)


def check_strategy_key_outside_registry(ambient: dict[str, Any]) -> None:
    """Raise StrategyKeyOutsideRegistry if any whitelisted strategy key appears.

    D-06: strategy-semantic keys live ONLY in the registry. If a
    whitelisted key appears in ambient configuration (env vars, CLI
    flags, etc.) — at any nesting level, in any env-var spelling — the
    loader raises StrategyKeyOutsideRegistry instead of silently
    altering semantics.

    Runtime config (endpoints, tokens, log levels, poll intervals)
    is allowed in ambient configuration — only strategy-semantic
    keys are rejected.
    """
    smuggled = sorted(
        {str(key) for key in _iter_ambient_keys(ambient) if _is_strategy_key_name(key)}
    )
    if smuggled:
        raise StrategyKeyOutsideRegistry(
            f"strategy-semantic keys found outside registry: {smuggled}"
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
