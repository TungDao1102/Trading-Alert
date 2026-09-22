"""Tests for the parameter registry loader (Phase 3, plan 03-01).

Per D-04/D-05/D-06: file-based TOML registry is the source of truth;
identity = parameterSetId + parameterSetHash (SHA256 over canonical
JSON); loader is fail-closed (raises on unregistered/mutated/unknown
keys, never silent fallback).

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/domain/registry.py` is implemented.
"""

from __future__ import annotations

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
