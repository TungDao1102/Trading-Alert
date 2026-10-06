"""Tests for the parameter registry loader (Phase 3, plans 03-01 + 03-03).

Per D-04/D-05/D-06: file-based TOML registry is the source of truth;
identity = parameterSetId + parameterSetHash (SHA256 over canonical
JSON); loader is fail-closed (raises on unregistered/mutated/unknown
keys, never silent fallback).

Plan 03-03 additions (registry hardening):
  - Whole-number TOML values normalize to int; fractional values become
    Decimal from string form (so identical logical sets hash identically
    regardless of source spelling).
  - Parameter names are restricted to 7-bit ASCII so code-point sorting
    matches the documented canonical profile; non-ASCII names raise at
    load.
  - Volatile sidecar fields (author, timestamp) never enter the hashed
    body; editing them does not change the hash.
  - Decimal values differing only in trailing precision produce distinct
    hashes by documented design.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/domain/registry.py` is implemented.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from src.domain.registry import (
    ParameterSet,
    ParameterSetMutated,
    RegistrySchemaMismatch,
    StrategyKeyOutsideRegistry,
    UnregisteredParameterSet,
    load_parameter_set,
    verify_parameter_set,
)

# --------------------------------------------------------------------------- #
# Test 1 — registered set loads with a 64-hex hash.
# --------------------------------------------------------------------------- #


def test_load_parameter_set_returns_parameter_set_with_64_hex_hash() -> None:
    """Beh. 1: load_parameter_set returns a ParameterSet with a 64-hex hash.

    The seed TOML `params/trend-pullback/baseline-v1.toml` is
    hand-authored and immutable. Its hash is the SHA256 over the
    canonical JSON of the normalized TOML body.
    """
    ps = load_parameter_set("trend-pullback", "baseline-v1")
    assert isinstance(ps, ParameterSet)
    assert ps.strategy_id == "trend-pullback"
    assert ps.parameter_set_id == "baseline-v1"
    assert isinstance(ps.parameter_set_hash, str)
    assert len(ps.parameter_set_hash) == 64
    assert all(c in "0123456789abcdef" for c in ps.parameter_set_hash)


# --------------------------------------------------------------------------- #
# Test 2 — hash is stable across key orderings.
# --------------------------------------------------------------------------- #


def test_load_parameter_set_hash_is_stable_across_runs() -> None:
    """Beh. 2: loading the same TOML twice yields the same hash.

    The canonicalizer sorts dict keys before hashing, so the order in
    which TOML keys appear in the file does not affect the digest.
    """
    ps_a = load_parameter_set("trend-pullback", "baseline-v1")
    ps_b = load_parameter_set("trend-pullback", "baseline-v1")
    assert ps_a.parameter_set_hash == ps_b.parameter_set_hash


# --------------------------------------------------------------------------- #
# Test 3 — unregistered set raises UnregisteredParameterSet.
# --------------------------------------------------------------------------- #


def test_load_parameter_set_unregistered_raises() -> None:
    """Beh. 3: load_parameter_set on a missing file raises UnregisteredParameterSet.

    D-04: never a silent fallback. Unknown parameter set is a
    load-time error.
    """
    with pytest.raises(UnregisteredParameterSet):
        load_parameter_set("trend-pullback", "does-not-exist")


# --------------------------------------------------------------------------- #
# Test 4 — schema version mismatch raises RegistrySchemaMismatch.
# --------------------------------------------------------------------------- #


def test_load_parameter_set_schema_mismatch_raises(tmp_path: Path) -> None:
    """Beh. 4: TOML with wrong schema_version raises RegistrySchemaMismatch.

    D-04: schema_version is validated against the loader's supported
    constant. Mismatch is a load-time error.
    """
    # Build a TOML with schema_version = 99 in a temp directory.
    strategy_dir = tmp_path / "test-strategy"
    strategy_dir.mkdir()
    toml_path = strategy_dir / "test-set.toml"
    toml_path.write_text(
        "schema_version = 99\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "swing_lookback = 20\n",
        encoding="utf-8",
    )

    # Monkey-patch REGISTRY_ROOT to point at tmp_path.
    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        with pytest.raises(RegistrySchemaMismatch):
            load_parameter_set("test-strategy", "test-set")
    finally:
        registry.REGISTRY_ROOT = original_root


# --------------------------------------------------------------------------- #
# Test 5 — unknown strategy key raises StrategyKeyOutsideRegistry.
# --------------------------------------------------------------------------- #


def test_load_parameter_set_unknown_strategy_key_raises(tmp_path: Path) -> None:
    """Beh. 5: TOML with an unknown strategy-semantic key raises.

    D-06: the loader owns the closed whitelist of strategy-semantic
    keys. Anything strategy-semantic found outside the whitelist
    raises at load.
    """
    strategy_dir = tmp_path / "test-strategy"
    strategy_dir.mkdir()
    toml_path = strategy_dir / "test-set.toml"
    toml_path.write_text(
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "swing_lookback = 20\n"
        "unknown_strategy_key = 42\n",  # not in STRATEGY_KEYS
        encoding="utf-8",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        with pytest.raises(StrategyKeyOutsideRegistry):
            load_parameter_set("test-strategy", "test-set")
    finally:
        registry.REGISTRY_ROOT = original_root


# --------------------------------------------------------------------------- #
# Test 6 — verify_parameter_set raises on hash mismatch.
# --------------------------------------------------------------------------- #


def test_verify_parameter_set_raises_on_mutation(tmp_path: Path) -> None:
    """Beh. 6: verify_parameter_set raises ParameterSetMutated on hash mismatch.

    D-04/D-05: once a parameter set is referenced, its hash is
    permanent. Any mutation raises ParameterSetMutated.
    """
    # Copy the seed TOML to a temp directory, load it, then mutate it.
    seed_path = Path("params/trend-pullback/baseline-v1.toml")
    assert seed_path.is_file(), f"missing seed TOML: {seed_path}"

    strategy_dir = tmp_path / "trend-pullback"
    strategy_dir.mkdir()
    copy_path = strategy_dir / "baseline-v1.toml"
    copy_path.write_text(seed_path.read_text(encoding="utf-8"), encoding="utf-8")

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps = load_parameter_set("trend-pullback", "baseline-v1")
        original_hash = ps.parameter_set_hash

        # Mutate the file: flip one digit.
        mutated = copy_path.read_text(encoding="utf-8").replace(
            "swing_lookback = 20", "swing_lookback = 21"
        )
        copy_path.write_text(mutated, encoding="utf-8")

        with pytest.raises(ParameterSetMutated):
            verify_parameter_set(copy_path, expected_hash=original_hash)
    finally:
        registry.REGISTRY_ROOT = original_root


# --------------------------------------------------------------------------- #
# Test 7 — verify_parameter_set passes when hash matches.
# --------------------------------------------------------------------------- #


def test_verify_parameter_set_passes_when_hash_matches(tmp_path: Path) -> None:
    """Beh. 7: verify_parameter_set returns None when hash matches.

    The verify function is the runtime tripwire for D-04/D-05.
    """
    seed_path = Path("params/trend-pullback/baseline-v1.toml")
    assert seed_path.is_file(), f"missing seed TOML: {seed_path}"

    strategy_dir = tmp_path / "trend-pullback"
    strategy_dir.mkdir()
    copy_path = strategy_dir / "baseline-v1.toml"
    copy_path.write_text(seed_path.read_text(encoding="utf-8"), encoding="utf-8")

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps = load_parameter_set("trend-pullback", "baseline-v1")
        # Same file, same hash → verify returns None (no exception).
        result = verify_parameter_set(copy_path, expected_hash=ps.parameter_set_hash)
        assert result is None
    finally:
        registry.REGISTRY_ROOT = original_root


# =========================================================================== #
# Plan 03-03 — Registry normalization and hash stability (TDD RED).
# =========================================================================== #


# --------------------------------------------------------------------------- #
# Test 8 — whole-number TOML values normalize to int.
# --------------------------------------------------------------------------- #


def test_whole_number_toml_value_normalizes_to_int(tmp_path: Path) -> None:
    """Beh. 8: a TOML integer like `swing_lookback = 20` stays int after load.

    Per RESEARCH_PROTOCOL §5: numeric type coercion (string-vs-int for
    whole numbers, exact decimal representation for fractional values).
    Whole-number values must be int, not float, so the canonical hash
    is stable across TOML spellings (`20` vs `20.0`).
    """
    strategy_dir = tmp_path / "test-strategy"
    strategy_dir.mkdir()
    toml_path = strategy_dir / "test-set.toml"
    toml_path.write_text(
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "swing_lookback = 20\n",
        encoding="utf-8",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps = load_parameter_set("test-strategy", "test-set")
        assert ps.params["swing_lookback"] == 20
        assert isinstance(ps.params["swing_lookback"], int)
        assert not isinstance(ps.params["swing_lookback"], float)
    finally:
        registry.REGISTRY_ROOT = original_root


# --------------------------------------------------------------------------- #
# Test 9 — fractional TOML values become Decimal from string form.
# --------------------------------------------------------------------------- #


def test_fractional_toml_value_normalizes_to_decimal_from_string(tmp_path: Path) -> None:
    """Beh. 9: a TOML float like `zone_tolerance_atr = 0.5` becomes Decimal.

    Per RESEARCH_PROTOCOL §5: exact decimal representation for
    fractional values. The Decimal is built from the string form so
    `0.5` → `Decimal("0.5")` (not `Decimal(0.5)` which would be
    `Decimal("0.5")` but with float-binary noise on other values).
    """
    strategy_dir = tmp_path / "test-strategy"
    strategy_dir.mkdir()
    toml_path = strategy_dir / "test-set.toml"
    toml_path.write_text(
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "zone_tolerance_atr = 0.5\n",
        encoding="utf-8",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps = load_parameter_set("test-strategy", "test-set")
        assert ps.params["zone_tolerance_atr"] == Decimal("0.5")
        assert isinstance(ps.params["zone_tolerance_atr"], Decimal)
    finally:
        registry.REGISTRY_ROOT = original_root


# --------------------------------------------------------------------------- #
# Test 10 — same TOML parsed twice yields identical hash.
# --------------------------------------------------------------------------- #


def test_same_toml_parsed_twice_yields_identical_hash(tmp_path: Path) -> None:
    """Beh. 10: same TOML parsed twice yields identical parameter_set_hash.

    Per D-04: parameterSetHash is stable across runs. The canonicalizer
    sorts dict keys before hashing, so the order in which TOML keys
    appear in the file does not affect the digest.
    """
    strategy_dir = tmp_path / "test-strategy"
    strategy_dir.mkdir()
    toml_path = strategy_dir / "test-set.toml"
    toml_path.write_text(
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "swing_lookback = 20\n"
        "zone_tolerance_atr = 0.5\n",
        encoding="utf-8",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps_a = load_parameter_set("test-strategy", "test-set")
        ps_b = load_parameter_set("test-strategy", "test-set")
        assert ps_a.parameter_set_hash == ps_b.parameter_set_hash
    finally:
        registry.REGISTRY_ROOT = original_root


# --------------------------------------------------------------------------- #
# Test 11 — non-ASCII parameter name raises at load.
# --------------------------------------------------------------------------- #


def test_non_ascii_parameter_name_raises_at_load(tmp_path: Path) -> None:
    """Beh. 11: a parameter name with non-ASCII characters raises at load.

    Per CONFIGURATION §9 + RESEARCH_PROTOCOL §5: parameter names are
    restricted to 7-bit ASCII so code-point sorting matches the
    documented canonical profile. Non-ASCII names raise a typed
    exception (StrategyKeyOutsideRegistry) at load.
    """
    strategy_dir = tmp_path / "test-strategy"
    strategy_dir.mkdir()
    toml_path = strategy_dir / "test-set.toml"
    # Use a quoted TOML key with a non-ASCII character (ñ = \xc3\xb1 in UTF-8).
    toml_path.write_text(
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "swing_lookback = 20\n"
        '"lookback_\xc3\xb1" = 10\n',
        encoding="utf-8",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        with pytest.raises(StrategyKeyOutsideRegistry):
            load_parameter_set("test-strategy", "test-set")
    finally:
        registry.REGISTRY_ROOT = original_root


# --------------------------------------------------------------------------- #
# Test 12 — volatile sidecar fields (author, timestamp) do not affect hash.
# --------------------------------------------------------------------------- #


def test_volatile_sidecar_fields_do_not_affect_hash(tmp_path: Path) -> None:
    """Beh. 12: editing author/timestamp sidecar fields does not change hash.

    Per D-04: parameterSetHash is computed over the canonical JSON of
    the normalized params body. Volatile sidecar fields (author,
    timestamp) are metadata about the file, not the parameter set
    itself, and must never enter the hashed body.
    """
    strategy_dir = tmp_path / "test-strategy"
    strategy_dir.mkdir()
    toml_path = strategy_dir / "test-set.toml"
    toml_path.write_text(
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        'author = "alice"\n'
        'created_at_utc = "2026-09-19T00:00:00Z"\n'
        "[parameters]\n"
        "swing_lookback = 20\n",
        encoding="utf-8",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps_original = load_parameter_set("test-strategy", "test-set")
        original_hash = ps_original.parameter_set_hash

        # Mutate the volatile sidecar fields.
        mutated = (
            toml_path.read_text(encoding="utf-8")
            .replace('author = "alice"', 'author = "bob"')
            .replace(
                'created_at_utc = "2026-09-19T00:00:00Z"',
                'created_at_utc = "2026-12-31T23:59:59Z"',
            )
        )
        toml_path.write_text(mutated, encoding="utf-8")

        ps_mutated = load_parameter_set("test-strategy", "test-set")
        assert ps_mutated.parameter_set_hash == original_hash
    finally:
        registry.REGISTRY_ROOT = original_root


# --------------------------------------------------------------------------- #
# Test 13 — Decimal values with different trailing precision yield different hashes.
# --------------------------------------------------------------------------- #


def test_decimal_values_with_different_precision_yield_different_hashes(
    tmp_path: Path,
) -> None:
    """Beh. 13: Decimal("1.50") vs Decimal("1.5") produce distinct hashes.

    Per D-12: Decimal → str() preserving full precision. Decimal("1.50")
    stays "1.50", never "1.5". This is documented design — trailing
    precision is semantically meaningful for exchange-sensitive values.
    """
    strategy_dir_a = tmp_path / "test-strategy-a"
    strategy_dir_a.mkdir()
    toml_path_a = strategy_dir_a / "test-set.toml"
    toml_path_a.write_text(
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy-a"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "zone_tolerance_atr = 1.50\n",
        encoding="utf-8",
    )

    strategy_dir_b = tmp_path / "test-strategy-b"
    strategy_dir_b.mkdir()
    toml_path_b = strategy_dir_b / "test-set.toml"
    toml_path_b.write_text(
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy-b"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "zone_tolerance_atr = 1.5\n",
        encoding="utf-8",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps_a = load_parameter_set("test-strategy-a", "test-set")
        ps_b = load_parameter_set("test-strategy-b", "test-set")
        # The params dict should preserve the trailing precision as a string.
        assert str(ps_a.params["zone_tolerance_atr"]) == "1.50"
        assert str(ps_b.params["zone_tolerance_atr"]) == "1.5"
        # And the hashes must differ because the canonical form preserves
        # the trailing precision (D-12).
        assert ps_a.parameter_set_hash != ps_b.parameter_set_hash
    finally:
        registry.REGISTRY_ROOT = original_root


def test_path_traversal_segments_raise_unregistered() -> None:
    """Beh. 14: `../`-style ids raise UnregisteredParameterSet (WR-05)."""
    with pytest.raises(UnregisteredParameterSet):
        load_parameter_set("../../etc", "x")
    with pytest.raises(UnregisteredParameterSet):
        load_parameter_set("trend-pullback", "../baseline-v1")
    with pytest.raises(UnregisteredParameterSet):
        load_parameter_set("", "baseline-v1")


def _write_toml(tmp_path: Path, body: str) -> None:
    """Write body as tmp test-strategy/test-set TOML."""
    strategy_dir = tmp_path / "test-strategy"
    strategy_dir.mkdir(exist_ok=True)
    (strategy_dir / "test-set.toml").write_text(body, encoding="utf-8")


def test_missing_strategy_version_raises(tmp_path: Path) -> None:
    """Beh. 15: TOML without strategy_version raises (CR-06)."""
    _write_toml(
        tmp_path,
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        "[parameters]\n"
        "swing_lookback = 20\n",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        with pytest.raises(RegistrySchemaMismatch):
            load_parameter_set("test-strategy", "test-set")
    finally:
        registry.REGISTRY_ROOT = original_root


def test_missing_parameters_table_raises(tmp_path: Path) -> None:
    """Beh. 16: TOML without [parameters] raises (CR-06)."""
    _write_toml(
        tmp_path,
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n',
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        with pytest.raises(RegistrySchemaMismatch):
            load_parameter_set("test-strategy", "test-set")
    finally:
        registry.REGISTRY_ROOT = original_root


def test_wrong_typed_values_raise_at_load(tmp_path: Path) -> None:
    """Beh. 17: str/bool/list values raise at the boundary (WR-06)."""
    from src.domain import registry

    cases = [
        'swing_lookback = "20"\n',  # string instead of int
        "risk_rate = true\n",  # bool instead of Decimal
        "signal_expiry_hours = [4]\n",  # list instead of int
    ]
    for extra in cases:
        _write_toml(
            tmp_path,
            "schema_version = 1\n"
            "[strategy]\n"
            'strategy_id = "test-strategy"\n'
            'strategy_version = "v1.0.0"\n'
            "[parameters]\n" + extra,
        )
        original_root = registry.REGISTRY_ROOT
        registry.REGISTRY_ROOT = tmp_path
        try:
            with pytest.raises(StrategyKeyOutsideRegistry):
                load_parameter_set("test-strategy", "test-set")
        finally:
            registry.REGISTRY_ROOT = original_root


def test_inline_comment_and_quoted_key_load(tmp_path: Path) -> None:
    """Beh. 18: trailing comments stripped, quoted keys read (WR-04)."""
    from decimal import Decimal

    from src.domain import registry

    _write_toml(
        tmp_path,
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "swing_lookback = 20\n"
        '"zone_tolerance_atr" = 0.5  # tuned\n',
    )
    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps = load_parameter_set("test-strategy", "test-set")
        assert ps.params["zone_tolerance_atr"] == Decimal("0.5")
    finally:
        registry.REGISTRY_ROOT = original_root


def test_normalize_params_recurses_into_nested_floats() -> None:
    """Beh. 19: floats nested in lists/dicts convert, not TypeError (WR-13)."""
    from decimal import Decimal

    from src.domain.registry import _normalize_params

    out = _normalize_params({"k": [0.5, 2.0, "x", {"n": 1.5}]})
    assert out["k"][0] == Decimal("0.5")
    assert out["k"][1] == 2
    assert out["k"][2] == "x"
    assert out["k"][3]["n"] == Decimal("1.5")


def test_verify_rejects_unknown_key_like_load(tmp_path: Path) -> None:
    """Beh. 20: copied TOML plus unknown key raises under verify (CR-05)."""
    seed_path = Path("params/trend-pullback/baseline-v1.toml")
    assert seed_path.is_file(), f"missing seed TOML: {seed_path}"

    strategy_dir = tmp_path / "trend-pullback"
    strategy_dir.mkdir()
    copy_path = strategy_dir / "baseline-v1.toml"
    copy_path.write_text(
        seed_path.read_text(encoding="utf-8") + "unknown_strategy_key = 42\n",
        encoding="utf-8",
    )

    ps = load_parameter_set("trend-pullback", "baseline-v1")
    with pytest.raises(StrategyKeyOutsideRegistry):
        verify_parameter_set(copy_path, expected_hash=ps.parameter_set_hash)


def test_verify_rejects_renamed_identity(tmp_path: Path) -> None:
    """Beh. 21: copied TOML under a mismatched path raises (CR-05)."""
    seed_path = Path("params/trend-pullback/baseline-v1.toml")
    assert seed_path.is_file(), f"missing seed TOML: {seed_path}"

    other_dir = tmp_path / "other-strategy"
    other_dir.mkdir()
    copy_path = other_dir / "baseline-v1.toml"
    copy_path.write_text(seed_path.read_text(encoding="utf-8"), encoding="utf-8")

    ps = load_parameter_set("trend-pullback", "baseline-v1")
    with pytest.raises(StrategyKeyOutsideRegistry):
        verify_parameter_set(copy_path, expected_hash=ps.parameter_set_hash)


# =========================================================================== #
# Plan 05-01 — Phase 5 D-05 registry type classification (Pitfall 5).
# =========================================================================== #


def test_max_open_positions_int_key_rejects_decimal(tmp_path: Path) -> None:
    """Beh. 22: max_open_positions (INT_KEY) rejects non-int like 2.5."""
    from src.domain.registry import _check_param_types

    params = {"max_open_positions": Decimal("2.5")}
    with pytest.raises(StrategyKeyOutsideRegistry, match="must be int"):
        _check_param_types(params, tmp_path / "test.toml")


def test_constraint_snapshot_ttl_seconds_int_key_rejects_decimal(tmp_path: Path) -> None:
    """Beh. 23: constraint_snapshot_ttl_seconds (INT_KEY) rejects non-int."""
    from src.domain.registry import _check_param_types

    params = {"constraint_snapshot_ttl_seconds": Decimal("3600.5")}
    with pytest.raises(StrategyKeyOutsideRegistry, match="must be int"):
        _check_param_types(params, tmp_path / "test.toml")


def test_risk_rate_decimal_key_loads_as_decimal(tmp_path: Path) -> None:
    """Beh. 24: risk_rate (DECIMAL_KEY) loads as Decimal."""
    _write_toml(
        tmp_path,
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "risk_rate = 0.005\n",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps = load_parameter_set("test-strategy", "test-set")
        assert isinstance(ps.params["risk_rate"], Decimal)
        assert ps.params["risk_rate"] == Decimal("0.005")
    finally:
        registry.REGISTRY_ROOT = original_root


def test_max_aggregate_open_risk_decimal_key_loads_as_decimal(tmp_path: Path) -> None:
    """Beh. 25: max_aggregate_open_risk (DECIMAL_KEY) loads as Decimal."""
    _write_toml(
        tmp_path,
        "schema_version = 1\n"
        "[strategy]\n"
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "max_aggregate_open_risk = 0.01\n",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps = load_parameter_set("test-strategy", "test-set")
        assert isinstance(ps.params["max_aggregate_open_risk"], Decimal)
        assert ps.params["max_aggregate_open_risk"] == Decimal("0.01")
    finally:
        registry.REGISTRY_ROOT = original_root


def test_baseline_v2_sets_load_with_all_d05_keys() -> None:
    """Beh. 26: all three baseline-v2 sets load cleanly with D-05 keys."""
    for family in ("trend-pullback", "breakout-retest", "range-mr"):
        ps = load_parameter_set(family, "baseline-v2")
        assert ps.strategy_version == "v2.0.0"
        # INT_KEYS present as int
        assert isinstance(ps.params["max_open_positions"], int)
        assert isinstance(ps.params["constraint_snapshot_ttl_seconds"], int)
        # DECIMAL_KEYS present as Decimal
        for key in (
            "risk_rate",
            "minimum_risk_utilization_after_rounding",
            "max_aggregate_open_risk",
            "cluster_cap",
            "daily_loss_warning_threshold",
            "daily_loss_stop_threshold",
            "fee_rate_entry",
            "fee_rate_exit",
            "expected_slippage",
        ):
            assert key in ps.params, f"{family}/baseline-v2 missing {key}"
            assert isinstance(ps.params[key], Decimal), (
                f"{family}/baseline-v2[{key}] must be Decimal, got {type(ps.params[key]).__name__}"
            )


# --------------------------------------------------------------------------- #
# Phase 11 plan 02 - pin coverage, working_type key, D036-D038 candidate sets.
# --------------------------------------------------------------------------- #

_REPO_PARAMS = Path(__file__).resolve().parent.parent / "params"
_PIN_FILE = Path(__file__).resolve().parent / "fixtures" / "phase4" / "parameters.json"

# Hashes of the ten pre-phase-11 sets (loader output at commit 679825c). They must
# never move: old sets are immutable (D-06, F-810).
PRE_PHASE_11_HASHES: dict[tuple[str, str], tuple[str, str]] = {
    ("breakout-retest", "baseline-v1"): (
        "v1.0.0",
        "4a8ee77ee99d390c1a4ccd86ee7259f86f319451de67d76732ee4cadc0cc1969",
    ),
    ("breakout-retest", "baseline-v2"): (
        "v2.0.0",
        "5be12f1b36b7c3e5595a93c62aec74e52ac877848bd8658ff60be2e69584ed0b",
    ),
    ("breakout-retest", "baseline-v3"): (
        "v2.0.0",
        "b36f095b49bc4342a212fa2a8607602b8f98f92e26d540b56c54897a8461a03e",
    ),
    ("range-mr", "baseline-v1"): (
        "v1.0.0",
        "060fc4470a075b97253b4cd0e787819031d019dd2b0b857aaec02e08e6066404",
    ),
    ("range-mr", "baseline-v2"): (
        "v2.0.0",
        "4249bf9934e1477736b3fb3008a0d962aaa1163047fed55227b37c973de3ed0f",
    ),
    ("trend-pullback", "baseline-no-trade-v1"): (
        "v2.0.0",
        "8f28ddc98876326b762c7ae05a749d0b0fbb4ca9d578cc817f5663bcb4f3ad0e",
    ),
    ("trend-pullback", "baseline-simple-trend-v1"): (
        "v2.0.0",
        "b99f1eaa6d3b8e15f210c7ed2db4eb5dd5823e59f0de3eb25afddf9bb1426a01",
    ),
    ("trend-pullback", "baseline-v1"): (
        "v1.0.0",
        "e1579900b1be20b8a6db76c554255cbec8125d5d317f6df7dadd5de78d2afae5",
    ),
    ("trend-pullback", "baseline-v2"): (
        "v2.0.0",
        "e3176f73eecf65cbcedce218f5316fef1ce9511efc38151c4e67e2ec00e45726",
    ),
    ("trend-pullback", "baseline-v3"): (
        "v2.0.0",
        "5205ec6a87f4665d4ae0b0ebd5f1e5fb49bbd0ea30b20842ceb4d780b4452e57",
    ),
}


def test_every_params_toml_has_a_pin_that_verifies() -> None:
    """Mirror of the registry-gate re-hash step: every TOML is pinned and verifies."""
    doc = json.loads(_PIN_FILE.read_text(encoding="utf-8"))
    pins = {
        (e["strategy_id"], e["parameter_set_id"]): e["parameter_set_hash"]
        for e in doc["parameter_sets"]
    }
    tomls = sorted(_REPO_PARAMS.rglob("*.toml"))
    assert tomls, "no params TOML files found"
    seen: set[tuple[str, str]] = set()
    for toml_path in tomls:
        key = (toml_path.parent.name, toml_path.stem)
        seen.add(key)
        assert key in pins, f"{toml_path}: no pinned hash - register it"
        verify_parameter_set(toml_path, pins[key])
    assert set(pins) == seen, f"pins without a file: {sorted(set(pins) - seen)}"
    assert len(pins) == len(doc["parameter_sets"]), "duplicate pin entries"


def test_pre_phase_11_hashes_and_versions_are_unchanged() -> None:
    for (strategy_id, set_id), (version, digest) in PRE_PHASE_11_HASHES.items():
        loaded = load_parameter_set(strategy_id, set_id)
        assert loaded.strategy_version == version, (strategy_id, set_id)
        assert loaded.parameter_set_hash == digest, (strategy_id, set_id)


_WORKING_TYPE_HEADER = (
    "schema_version = 1\n"
    "[strategy]\n"
    'strategy_id = "test-strategy"\n'
    'strategy_version = "v1.0.0"\n'
    "[parameters]\n"
)


def _load_tmp(tmp_path: Path, parameters: str) -> ParameterSet:
    from src.domain import registry

    _write_toml(tmp_path, _WORKING_TYPE_HEADER + parameters)
    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        return load_parameter_set("test-strategy", "test-set")
    finally:
        registry.REGISTRY_ROOT = original_root


def test_working_type_accepts_mark_price(tmp_path: Path) -> None:
    loaded = _load_tmp(tmp_path, 'working_type = "MARK_PRICE"\n')
    assert loaded.params["working_type"] == "MARK_PRICE"


def test_working_type_rejects_contract_price_until_consumers_exist(tmp_path: Path) -> None:
    # Live placement hard-codes MARK_PRICE and no backtest/paper code reads the key, so a
    # CONTRACT_PRICE declaration would be hashed into the set identity but ignored (WR-08).
    with pytest.raises(StrategyKeyOutsideRegistry):
        _load_tmp(tmp_path, 'working_type = "CONTRACT_PRICE"\n')


@pytest.mark.parametrize(
    "literal",
    ['"LAST"', '""', "1", "true", '"mark_price"', '"MARK_PRICE "'],
)
def test_working_type_rejects_other_values(tmp_path: Path, literal: str) -> None:
    with pytest.raises(StrategyKeyOutsideRegistry):
        _load_tmp(tmp_path, f"working_type = {literal}\n")


def test_set_without_working_type_still_loads(tmp_path: Path) -> None:
    loaded = _load_tmp(tmp_path, "swing_lookback = 20\n")
    assert "working_type" not in loaded.params


def test_working_type_is_not_a_cost_key() -> None:
    from src.backtest.costs import COST_KEYS
    from src.domain.registry import STRATEGY_KEYS

    assert "working_type" in STRATEGY_KEYS
    assert "working_type" not in COST_KEYS


_V4_SETS = (
    ("trend-pullback", "baseline-v4"),
    ("breakout-retest", "baseline-v4"),
    ("range-mr", "baseline-v4"),
)


@pytest.mark.parametrize(("strategy_id", "set_id"), _V4_SETS)
def test_v4_sets_match_d036_d038(strategy_id: str, set_id: str) -> None:
    from src.backtest.costs import COST_KEYS, build_cost_model

    loaded = load_parameter_set(strategy_id, set_id)
    params = loaded.params
    assert loaded.strategy_version == "v3.0.0"
    assert params["fee_rate_entry"] == Decimal("0.0005")
    assert params["fee_rate_exit"] == Decimal("0.0005")
    assert params["partial_fill_fraction"] == 1
    assert isinstance(params["partial_fill_fraction"], int)
    assert not isinstance(params["partial_fill_fraction"], bool)
    assert params["working_type"] == "MARK_PRICE"
    build_cost_model({k: params[k] for k in COST_KEYS})


def test_trend_pullback_v4_differs_from_v3_only_in_d036_d038_keys() -> None:
    v3 = load_parameter_set("trend-pullback", "baseline-v3").params
    v4 = load_parameter_set("trend-pullback", "baseline-v4").params
    changed = {"fee_rate_entry", "partial_fill_fraction", "working_type"}
    assert set(v4) - set(v3) == {"working_type"}
    assert set(v3) <= set(v4)
    for key in set(v3) - changed:
        assert v3[key] == v4[key], key


def test_breakout_retest_v4_differs_from_v3_only_in_d036_d038_keys() -> None:
    v3 = load_parameter_set("breakout-retest", "baseline-v3").params
    v4 = load_parameter_set("breakout-retest", "baseline-v4").params
    changed = {"fee_rate_entry", "partial_fill_fraction", "working_type"}
    assert set(v4) - set(v3) == {"working_type"}
    for key in set(v3) - changed:
        assert v3[key] == v4[key], key


def test_range_mr_v4_is_v2_plus_extended_cost_keys() -> None:
    v2 = load_parameter_set("range-mr", "baseline-v2").params
    v4 = load_parameter_set("range-mr", "baseline-v4").params
    added = {
        "funding_treatment",
        "slippage_model",
        "spread_fill_assumptions",
        "partial_fill_fraction",
        "working_type",
    }
    assert set(v4) - set(v2) == added
    for key in set(v2) - {"fee_rate_entry"}:
        assert v2[key] == v4[key], key
    assert v4["funding_treatment"] == "ADDITIVE"
    assert v4["slippage_model"] == "FIXED_BPS"
    assert v4["spread_fill_assumptions"] == "FULL_FILL"


# --------------------------------------------------------------------------- #
# Phase 12 (plan 12-02) - exit slippage, cost guards, commission TTL; unit guard.
# --------------------------------------------------------------------------- #

_PHASE12_KEYS = (
    "exit_slippage_rate",
    "min_stop_distance_rate",
    "max_cost_to_risk",
    "commission_rate_ttl_seconds",
)
_RATE_KEYS = ("fee_rate_entry", "fee_rate_exit", "expected_slippage", "exit_slippage_rate")


def test_phase12_keys_are_whitelisted_with_expected_types() -> None:
    from src.backtest.costs import COST_KEYS
    from src.domain.registry import DECIMAL_KEYS, INT_KEYS, STRATEGY_KEYS

    for key in _PHASE12_KEYS:
        assert key in STRATEGY_KEYS, key
        assert key not in COST_KEYS, key
    assert "commission_rate_ttl_seconds" in INT_KEYS
    for key in ("exit_slippage_rate", "min_stop_distance_rate", "max_cost_to_risk"):
        assert key in DECIMAL_KEYS, key
        assert key not in INT_KEYS, key
    assert "commission_rate_ttl_seconds" not in DECIMAL_KEYS


def test_set_with_phase12_keys_loads(tmp_path: Path) -> None:
    loaded = _load_tmp(
        tmp_path,
        "exit_slippage_rate = 0.0003\n"
        "min_stop_distance_rate = 0.003\n"
        "max_cost_to_risk = 0.15\n"
        "commission_rate_ttl_seconds = 3600\n",
    )
    assert loaded.params["exit_slippage_rate"] == Decimal("0.0003")
    assert loaded.params["min_stop_distance_rate"] == Decimal("0.003")
    assert loaded.params["max_cost_to_risk"] == Decimal("0.15")
    assert loaded.params["commission_rate_ttl_seconds"] == 3600


def test_set_without_phase12_keys_still_loads(tmp_path: Path) -> None:
    loaded = _load_tmp(tmp_path, "swing_lookback = 20\nfee_rate_entry = 0.0005\n")
    for key in _PHASE12_KEYS:
        assert key not in loaded.params


@pytest.mark.parametrize("key", _RATE_KEYS)
def test_rate_key_at_ceiling_loads(tmp_path: Path, key: str) -> None:
    loaded = _load_tmp(tmp_path, f"{key} = 0.01\n")
    assert loaded.params[key] == Decimal("0.01")


@pytest.mark.parametrize("key", _RATE_KEYS)
@pytest.mark.parametrize("literal", ["0.0100001", "2", "2.0", "-0.0001", "-1"])
def test_rate_key_unit_error_raises_naming_key(tmp_path: Path, key: str, literal: str) -> None:
    with pytest.raises(StrategyKeyOutsideRegistry) as excinfo:
        _load_tmp(tmp_path, f"{key} = {literal}\n")
    message = str(excinfo.value)
    assert key in message
    assert "unit error" in message


@pytest.mark.parametrize("key", _RATE_KEYS)
def test_rate_key_bool_raises(tmp_path: Path, key: str) -> None:
    with pytest.raises(StrategyKeyOutsideRegistry, match=key):
        _load_tmp(tmp_path, f"{key} = true\n")


@pytest.mark.parametrize(
    ("key", "literal", "loads"),
    [
        ("min_stop_distance_rate", "0", False),
        ("min_stop_distance_rate", "1", False),
        ("min_stop_distance_rate", "-0.1", False),
        ("min_stop_distance_rate", "0.003", True),
        ("max_cost_to_risk", "0", False),
        ("max_cost_to_risk", "1.5", False),
        ("max_cost_to_risk", "-0.1", False),
        ("max_cost_to_risk", "1", True),
        ("max_cost_to_risk", "0.15", True),
        ("commission_rate_ttl_seconds", "0", False),
        ("commission_rate_ttl_seconds", "-5", False),
        ("commission_rate_ttl_seconds", "3600.5", False),
        ("commission_rate_ttl_seconds", "3600", True),
    ],
)
def test_guard_keys_range_checked(tmp_path: Path, key: str, literal: str, loads: bool) -> None:
    if loads:
        assert key in _load_tmp(tmp_path, f"{key} = {literal}\n").params
        return
    with pytest.raises(StrategyKeyOutsideRegistry, match=key):
        _load_tmp(tmp_path, f"{key} = {literal}\n")


@pytest.mark.parametrize("key", _PHASE12_KEYS)
def test_ambient_config_named_after_phase12_key_is_rejected(key: str) -> None:
    from src.domain.registry import check_strategy_key_outside_registry

    with pytest.raises(StrategyKeyOutsideRegistry):
        check_strategy_key_outside_registry({key: "1"})
    with pytest.raises(StrategyKeyOutsideRegistry):
        check_strategy_key_outside_registry({"nested": {key.upper(): "1"}})


_PHASE12_FROZEN = {
    "exit_slippage_rate": Decimal("0.0003"),
    "min_stop_distance_rate": Decimal("0.003"),
    "max_cost_to_risk": Decimal("0.15"),
    "commission_rate_ttl_seconds": 3600,
}

_V5_SETS = (
    ("trend-pullback", "baseline-v4", "baseline-v5"),
    ("breakout-retest", "baseline-v4", "baseline-v5"),
    ("range-mr", "baseline-v4", "baseline-v5"),
)


@pytest.mark.parametrize(("strategy_id", "predecessor", "set_id"), _V5_SETS)
def test_baseline_v5_matches_phase12(strategy_id: str, predecessor: str, set_id: str) -> None:
    old = load_parameter_set(strategy_id, predecessor).params
    loaded = load_parameter_set(strategy_id, set_id)
    params = loaded.params
    assert loaded.strategy_version == "v4.0.0"
    assert params["fee_rate_entry"] == Decimal("0.0005")
    assert params["fee_rate_exit"] == Decimal("0.0005")
    assert params["expected_slippage"] == Decimal("0.0001")
    for key, value in _PHASE12_FROZEN.items():
        assert params[key] == value, key
        assert type(params[key]) is type(value), key
    assert params["working_type"] == "MARK_PRICE"
    assert set(params) - set(old) == set(_PHASE12_FROZEN)
    for key in old:
        assert params[key] == old[key], key


@pytest.mark.parametrize(
    "key",
    ["risk_rate", "minimum_rr", "max_cost_to_risk", "exit_slippage_rate", "min_stop_distance_rate"],
)
@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_non_finite_numeric_keys_raise_registry_exception(
    tmp_path: Path, key: str, bad: Decimal
) -> None:
    """12-REVIEW WR-04: NaN/Infinity raise StrategyKeyOutsideRegistry, never InvalidOperation."""
    from src.domain.registry import _check_param_types

    with pytest.raises(StrategyKeyOutsideRegistry, match="must be finite"):
        _check_param_types({key: bad}, tmp_path / "test.toml")


# --------------------------------------------------------------------------- #
# Phase 15 (plan 15-03) - pivot widths, geometry_version, tp_mode, min_stop_atr.
# --------------------------------------------------------------------------- #

_PHASE15_KEYS = (
    "pivot_left_bars",
    "pivot_right_bars",
    "geometry_version",
    "tp_mode",
    "min_stop_atr",
)
_PIVOT_BLOCK = "pivot_left_bars = 3\npivot_right_bars = 3\ngeometry_version = 1\n"


def _load_family(tmp_path: Path, family: str, parameters: str) -> ParameterSet:
    """Load a tmp set whose strategy_id is a real family name (cross-key rules key on it)."""
    from src.domain import registry

    strategy_dir = tmp_path / family
    strategy_dir.mkdir(exist_ok=True)
    (strategy_dir / "test-set.toml").write_text(
        "schema_version = 1\n"
        "[strategy]\n"
        f'strategy_id = "{family}"\n'
        'strategy_version = "v1.0.0"\n'
        "[parameters]\n"
        "swing_lookback = 20\n" + parameters,
        encoding="utf-8",
    )
    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        return load_parameter_set(family, "test-set")
    finally:
        registry.REGISTRY_ROOT = original_root


def test_phase15_keys_are_whitelisted_with_expected_types() -> None:
    from src.backtest.costs import COST_KEYS
    from src.domain.registry import (
        DECIMAL_KEYS,
        GEOMETRY_VERSION_VALUES,
        INT_KEYS,
        STRATEGY_KEYS,
        STRING_KEYS,
        TP_MODE_VALUES,
    )

    for key in _PHASE15_KEYS:
        assert key in STRATEGY_KEYS, key
        assert key not in COST_KEYS, key
    for key in ("pivot_left_bars", "pivot_right_bars", "geometry_version"):
        assert key in INT_KEYS, key
    assert "tp_mode" in STRING_KEYS
    assert "min_stop_atr" in DECIMAL_KEYS
    assert GEOMETRY_VERSION_VALUES == frozenset({1})
    assert TP_MODE_VALUES == frozenset({"T_MID", "T_OPPOSITE"})


def test_trend_pullback_set_with_phase15_keys_loads(tmp_path: Path) -> None:
    loaded = _load_family(tmp_path, "trend-pullback", _PIVOT_BLOCK + "min_stop_atr = 0.5\n")
    assert loaded.params["pivot_left_bars"] == 3
    assert loaded.params["pivot_right_bars"] == 3
    assert loaded.params["geometry_version"] == 1
    assert loaded.params["min_stop_atr"] == Decimal("0.5")


@pytest.mark.parametrize("tp_mode", ["T_MID", "T_OPPOSITE"])
def test_range_mr_set_with_phase15_keys_loads(tmp_path: Path, tp_mode: str) -> None:
    loaded = _load_family(tmp_path, "range-mr", _PIVOT_BLOCK + f'tp_mode = "{tp_mode}"\n')
    assert loaded.params["tp_mode"] == tp_mode


def test_breakout_retest_set_with_geometry_version_only_loads(tmp_path: Path) -> None:
    loaded = _load_family(tmp_path, "breakout-retest", "geometry_version = 1\n")
    assert loaded.params["geometry_version"] == 1


def test_set_without_phase15_keys_still_loads(tmp_path: Path) -> None:
    loaded = _load_family(tmp_path, "trend-pullback", "zone_tolerance_atr = 0.5\n")
    for key in _PHASE15_KEYS:
        assert key not in loaded.params


@pytest.mark.parametrize(
    ("key", "literal"),
    [
        ("pivot_left_bars", "0"),
        ("pivot_left_bars", "51"),
        ("pivot_left_bars", "true"),
        ("pivot_left_bars", "3.5"),
        ("pivot_right_bars", "0"),
        ("pivot_right_bars", "51"),
        ("pivot_right_bars", "false"),
        ("pivot_right_bars", "2.5"),
        ("geometry_version", "0"),
        ("geometry_version", "2"),
        ("geometry_version", "true"),
        ("geometry_version", "1.5"),
        ("tp_mode", '"MID"'),
        ("tp_mode", '""'),
        ("tp_mode", "1"),
        ("min_stop_atr", "0"),
        ("min_stop_atr", "-1"),
        ("min_stop_atr", "10.5"),
        ("min_stop_atr", "true"),
    ],
)
def test_phase15_key_values_rejected(tmp_path: Path, key: str, literal: str) -> None:
    with pytest.raises(StrategyKeyOutsideRegistry, match=key):
        _load_family(tmp_path, "range-mr", f"{key} = {literal}\n")


@pytest.mark.parametrize(("literal", "loads"), [("1", True), ("50", True), ("51", False)])
def test_pivot_width_bounds_are_inclusive(tmp_path: Path, literal: str, loads: bool) -> None:
    body = f"pivot_left_bars = {literal}\npivot_right_bars = 3\ngeometry_version = 1\n"
    if loads:
        loaded = _load_family(tmp_path, "trend-pullback", body)
        assert loaded.params["pivot_left_bars"] == int(literal)
        return
    with pytest.raises(StrategyKeyOutsideRegistry, match="pivot_left_bars"):
        _load_family(tmp_path, "trend-pullback", body)


@pytest.mark.parametrize(("literal", "loads"), [("10", True), ("0.0001", True), ("10.0001", False)])
def test_min_stop_atr_upper_bound_is_inclusive(tmp_path: Path, literal: str, loads: bool) -> None:
    body = f"min_stop_atr = {literal}\n"
    if loads:
        assert "min_stop_atr" in _load_family(tmp_path, "trend-pullback", body).params
        return
    with pytest.raises(StrategyKeyOutsideRegistry, match="min_stop_atr"):
        _load_family(tmp_path, "trend-pullback", body)


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_min_stop_atr_non_finite_raises_registry_exception(tmp_path: Path, bad: Decimal) -> None:
    from src.domain.registry import _check_param_types

    with pytest.raises(StrategyKeyOutsideRegistry, match="must be finite"):
        _check_param_types({"min_stop_atr": bad}, tmp_path / "test.toml")


@pytest.mark.parametrize("literal", ["nan", "inf", "-inf"])
def test_min_stop_atr_non_finite_toml_literals_are_rejected(tmp_path: Path, literal: str) -> None:
    with pytest.raises(StrategyKeyOutsideRegistry):
        _load_family(tmp_path, "trend-pullback", f"min_stop_atr = {literal}\n")


@pytest.mark.parametrize(
    ("family", "body"),
    [
        # only one pivot key
        ("trend-pullback", "pivot_left_bars = 3\ngeometry_version = 1\n"),
        ("trend-pullback", "pivot_right_bars = 3\ngeometry_version = 1\n"),
        # pivot_right_bars + 1 > swing_lookback (swing_lookback is 20)
        ("trend-pullback", "pivot_left_bars = 3\npivot_right_bars = 20\ngeometry_version = 1\n"),
        # pivot keys without geometry_version
        ("trend-pullback", "pivot_left_bars = 3\npivot_right_bars = 3\n"),
        # tp_mode without geometry_version
        ("range-mr", 'tp_mode = "T_MID"\n'),
        # tp_mode in a non-range-mr set
        ("trend-pullback", _PIVOT_BLOCK + 'tp_mode = "T_MID"\n'),
        ("breakout-retest", 'geometry_version = 1\ntp_mode = "T_MID"\n'),
        # pivot keys in a breakout-retest set
        ("breakout-retest", _PIVOT_BLOCK),
        # geometry_version without both pivot keys in trend-pullback / range-mr
        ("trend-pullback", "geometry_version = 1\n"),
        ("range-mr", 'geometry_version = 1\ntp_mode = "T_MID"\n'),
        # geometry_version in a range-mr set without tp_mode
        ("range-mr", _PIVOT_BLOCK),
    ],
)
def test_phase15_cross_key_rules_reject(tmp_path: Path, family: str, body: str) -> None:
    with pytest.raises(StrategyKeyOutsideRegistry):
        _load_family(tmp_path, family, body)


def test_pivot_right_bars_equal_to_swing_lookback_minus_one_loads(tmp_path: Path) -> None:
    body = "pivot_left_bars = 3\npivot_right_bars = 19\ngeometry_version = 1\n"
    assert _load_family(tmp_path, "trend-pullback", body).params["pivot_right_bars"] == 19


def test_range_mr_regime_filter_lookback_below_pivot_right_plus_one_is_rejected(
    tmp_path: Path,
) -> None:
    """15-REVIEW WR-01: the Family C regime reads pivots over `regime_filter_lookback` bars.

    A lookback below `pivot_right_bars + 1` makes `evaluate()` raise ValueError in the pure
    core, so the registry must refuse the set at load (fail closed) rather than let a
    backtest abort mid-run.
    """
    body = _PIVOT_BLOCK + 'tp_mode = "T_MID"\nregime_filter_lookback = 3\n'
    with pytest.raises(StrategyKeyOutsideRegistry, match="regime_filter_lookback"):
        _load_family(tmp_path, "range-mr", body)


def test_range_mr_regime_filter_lookback_equal_to_pivot_right_plus_one_loads(
    tmp_path: Path,
) -> None:
    body = _PIVOT_BLOCK + 'tp_mode = "T_MID"\nregime_filter_lookback = 4\n'
    loaded = _load_family(tmp_path, "range-mr", body)
    assert loaded.params["regime_filter_lookback"] == 4


@pytest.mark.parametrize("key", _PHASE15_KEYS)
def test_ambient_config_named_after_phase15_key_is_rejected(key: str) -> None:
    from src.domain.registry import check_strategy_key_outside_registry

    with pytest.raises(StrategyKeyOutsideRegistry):
        check_strategy_key_outside_registry({key: "1"})
    with pytest.raises(StrategyKeyOutsideRegistry):
        check_strategy_key_outside_registry({"nested": {key.upper(): "1"}})


# Sets written in Phase 15 (plan 15-08 baseline-v6; plan 15-09 re-issues the two comparison
# baselines as -v4). Every other committed set predates the Phase 15 keys and must stay free of
# them, which is what keeps its parameter_set_hash and byte lock valid (D-15).
_PHASE15_SET_IDS = frozenset(
    {
        ("trend-pullback", "baseline-v6"),
        ("breakout-retest", "baseline-v6"),
        ("range-mr", "baseline-v6"),
        ("trend-pullback", "baseline-no-trade-v4"),
        ("trend-pullback", "baseline-simple-trend-v4"),
    }
)


def test_committed_sets_carry_no_phase15_key_outside_the_phase15_sets() -> None:
    from src.domain import registry

    committed = sorted(Path(registry.REGISTRY_ROOT).glob("*/*.toml"))
    assert committed
    for path in committed:
        loaded = load_parameter_set(path.parent.name, path.stem)
        if (path.parent.name, path.stem) in _PHASE15_SET_IDS:
            assert loaded.params.get("geometry_version") == 1, f"{path}: Phase 15 set lacks the key"
            continue
        for key in _PHASE15_KEYS:
            assert key not in loaded.params, f"{path}: unexpected Phase 15 key {key}"
