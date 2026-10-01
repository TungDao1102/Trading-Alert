"""Tests for the fail-closed negative gates (Phase 3, plan 03-03).

Per D-04/D-05/D-06: the registry loader is fail-closed. Every
negative path raises a typed exception with no silent fallback:

  - Loading a nonexistent strategy/set pair raises
    `UnregisteredParameterSet`.
  - Copying the seed TOML, flipping one digit, and verifying against
    the original hash raises `ParameterSetMutated`.
  - A TOML with a `schema_version` other than 1 raises
    `RegistrySchemaMismatch`.
  - A strategy-semantic key presented outside the registry raises
    `StrategyKeyOutsideRegistry` instead of silently altering
    semantics.

TDD discipline: RED → GREEN. These tests are the RED phase — they
MUST fail until `src/domain/registry.py` is implemented.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.domain.registry import (
    ParameterSetMutated,
    RegistrySchemaMismatch,
    StrategyKeyOutsideRegistry,
    UnregisteredParameterSet,
    check_strategy_key_outside_registry,
    load_parameter_set,
    verify_parameter_set,
)

# --------------------------------------------------------------------------- #
# Test 1 — loading a nonexistent strategy/set pair raises UnregisteredParameterSet.
# --------------------------------------------------------------------------- #


def test_load_nonexistent_strategy_set_raises_unregistered() -> None:
    """Beh. 1: load_parameter_set on a missing file raises UnregisteredParameterSet.

    D-04: never a silent fallback. Unknown parameter set is a
    load-time error.
    """
    with pytest.raises(UnregisteredParameterSet):
        load_parameter_set("trend-pullback", "does-not-exist")


# --------------------------------------------------------------------------- #
# Test 2 — copying seed TOML, flipping one digit, verifying raises ParameterSetMutated.
# --------------------------------------------------------------------------- #


def test_verify_on_mutated_copy_raises_parameter_set_mutated(tmp_path: Path) -> None:
    """Beh. 2: verify_parameter_set on a one-digit-mutated copy raises ParameterSetMutated.

    D-04/D-05: once a parameter set is referenced, its hash is
    permanent. Any mutation raises ParameterSetMutated.
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
# Test 3 — a TOML with schema_version other than 1 raises RegistrySchemaMismatch.
# --------------------------------------------------------------------------- #


def test_load_schema_version_2_raises_registry_schema_mismatch(tmp_path: Path) -> None:
    """Beh. 3: a TOML with schema_version = 2 raises RegistrySchemaMismatch.

    D-04: schema_version is validated against the loader's supported
    constant. Mismatch is a load-time error.
    """
    strategy_dir = tmp_path / "test-strategy"
    strategy_dir.mkdir()
    toml_path = strategy_dir / "test-set.toml"
    toml_path.write_text(
        "schema_version = 2\n"
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
        with pytest.raises(RegistrySchemaMismatch):
            load_parameter_set("test-strategy", "test-set")
    finally:
        registry.REGISTRY_ROOT = original_root


# --------------------------------------------------------------------------- #
# Test 4 — a strategy-semantic key outside the registry raises StrategyKeyOutsideRegistry.
# --------------------------------------------------------------------------- #


def test_check_strategy_key_outside_registry_raises_on_whitelisted_key() -> None:
    """Beh. 4: an ambient mapping containing a whitelisted strategy key raises.

    D-06: strategy-semantic keys live ONLY in the registry. If a
    whitelisted key appears in ambient configuration (env vars, CLI
    flags, etc.), the loader raises StrategyKeyOutsideRegistry
    instead of silently altering semantics.
    """
    ambient = {"swing_lookback": 50, "log_level": "INFO"}
    with pytest.raises(StrategyKeyOutsideRegistry):
        check_strategy_key_outside_registry(ambient)


def test_check_strategy_key_outside_registry_passes_on_clean_ambient() -> None:
    """Beh. 4b: an ambient mapping with no whitelisted keys passes.

    Runtime config (endpoints, tokens, log levels, poll intervals)
    is allowed in ambient configuration — only strategy-semantic
    keys are rejected.
    """
    ambient = {"log_level": "INFO", "poll_interval_seconds": 30}
    result = check_strategy_key_outside_registry(ambient)
    assert result is None


def test_check_strategy_key_outside_registry_raises_on_nested_key() -> None:
    """Beh. 5: a whitelisted key nested in ambient config raises (WR-12)."""
    ambient = {"strategy": {"swing_lookback": 50}, "log_level": "INFO"}
    with pytest.raises(StrategyKeyOutsideRegistry):
        check_strategy_key_outside_registry(ambient)


def test_check_strategy_key_outside_registry_raises_on_env_var_spelling() -> None:
    """Beh. 6: prefixed UPPER_SNAKE ambient spelling raises (WR-12)."""
    ambient = {"TREND_SWING_LOOKBACK": "50", "log_level": "INFO"}
    with pytest.raises(StrategyKeyOutsideRegistry):
        check_strategy_key_outside_registry(ambient)
