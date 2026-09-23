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
        'schema_version = 99\n'
        '[strategy]\n'
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        '[parameters]\n'
        'swing_lookback = 20\n',
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
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        '[parameters]\n'
        'swing_lookback = 20\n'
        'unknown_strategy_key = 42\n',  # not in STRATEGY_KEYS
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
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        '[parameters]\n'
        'swing_lookback = 20\n',
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
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        '[parameters]\n'
        'zone_tolerance_atr = 0.5\n',
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
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        '[parameters]\n'
        'swing_lookback = 20\n'
        'zone_tolerance_atr = 0.5\n',
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
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        '[parameters]\n'
        'swing_lookback = 20\n'
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
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        'author = "alice"\n'
        'created_at_utc = "2026-09-19T00:00:00Z"\n'
        '[parameters]\n'
        'swing_lookback = 20\n',
        encoding="utf-8",
    )

    from src.domain import registry

    original_root = registry.REGISTRY_ROOT
    registry.REGISTRY_ROOT = tmp_path
    try:
        ps_original = load_parameter_set("test-strategy", "test-set")
        original_hash = ps_original.parameter_set_hash

        # Mutate the volatile sidecar fields.
        mutated = toml_path.read_text(encoding="utf-8").replace(
            'author = "alice"', 'author = "bob"'
        ).replace(
            'created_at_utc = "2026-09-19T00:00:00Z"',
            'created_at_utc = "2026-12-31T23:59:59Z"',
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
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy-a"\n'
        'strategy_version = "v1.0.0"\n'
        '[parameters]\n'
        'zone_tolerance_atr = 1.50\n',
        encoding="utf-8",
    )

    strategy_dir_b = tmp_path / "test-strategy-b"
    strategy_dir_b.mkdir()
    toml_path_b = strategy_dir_b / "test-set.toml"
    toml_path_b.write_text(
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy-b"\n'
        'strategy_version = "v1.0.0"\n'
        '[parameters]\n'
        'zone_tolerance_atr = 1.5\n',
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
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy"\n'
        '[parameters]\n'
        'swing_lookback = 20\n',
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
        'schema_version = 1\n'
        '[strategy]\n'
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
        'risk_rate = true\n',  # bool instead of Decimal
        'signal_expiry_hours = [4]\n',  # list instead of int
    ]
    for extra in cases:
        _write_toml(
            tmp_path,
            'schema_version = 1\n'
            '[strategy]\n'
            'strategy_id = "test-strategy"\n'
            'strategy_version = "v1.0.0"\n'
            '[parameters]\n' + extra,
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
        'schema_version = 1\n'
        '[strategy]\n'
        'strategy_id = "test-strategy"\n'
        'strategy_version = "v1.0.0"\n'
        '[parameters]\n'
        'swing_lookback = 20\n'
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
