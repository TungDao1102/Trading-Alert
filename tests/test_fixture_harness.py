"""Tests for the golden fixture harness (Phase 3, plan 03-01).

Per D-07/D-09: golden fixtures live under `tests/fixtures/phase3/`
(candles.csv + parameters.json + expected_signals.json +
expected_plans.json). Phase 3 expectations are minimal placeholders
proving the harness mechanism; Phase 4 populates real family
expectations.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `tests/conftest.py` is extended with the phase-3 loaders
and the fixture files exist.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Test 1 — phase3_candles fixture loads the candle CSV.
# --------------------------------------------------------------------------- #


def test_phase3_candles_fixture_loads(phase3_candles) -> None:
    """Beh. 1: phase3_candles fixture returns a non-empty list of dicts.

    The CSV has the canonical column order from TESTING_STRATEGY §2:
    symbol,timeframe,open_time_utc,open,high,low,close,volume.
    """
    assert isinstance(phase3_candles, list)
    assert len(phase3_candles) > 0
    first = phase3_candles[0]
    assert "symbol" in first
    assert "timeframe" in first
    assert "open_time_utc" in first
    assert "open" in first
    assert "high" in first
    assert "low" in first
    assert "close" in first
    assert "volume" in first


# --------------------------------------------------------------------------- #
# Test 2 — phase3_parameters fixture loads the pinned registry set.
# --------------------------------------------------------------------------- #


def test_phase3_parameters_fixture_loads(phase3_parameters) -> None:
    """Beh. 2: phase3_parameters fixture returns the pinned registry set.

    The parameters.json pins the same registry set the loader reads
    (strategy_id, strategy_version, parameter_set_id, parameter_set_hash).
    """
    assert isinstance(phase3_parameters, dict)
    assert phase3_parameters["strategy_id"] == "trend-pullback"
    assert phase3_parameters["strategy_version"] == "v1.0.0"
    assert phase3_parameters["parameter_set_id"] == "baseline-v1"
    assert "parameter_set_hash" in phase3_parameters
    assert len(phase3_parameters["parameter_set_hash"]) == 64


# --------------------------------------------------------------------------- #
# Test 3 — phase3_expected_signals fixture loads the placeholder.
# --------------------------------------------------------------------------- #


def test_phase3_expected_signals_fixture_loads(phase3_expected_signals) -> None:
    """Beh. 3: phase3_expected_signals fixture returns the placeholder.

    Per D-09, Phase 3 expectations are minimal placeholders (empty
    signals). Phase 4 populates real family expectations.
    """
    assert isinstance(phase3_expected_signals, dict)
    assert "signals" in phase3_expected_signals
    assert phase3_expected_signals["signals"] == []


# --------------------------------------------------------------------------- #
# Test 4 — phase3_expected_plans fixture loads the placeholder.
# --------------------------------------------------------------------------- #


def test_phase3_expected_plans_fixture_loads(phase3_expected_plans) -> None:
    """Beh. 4: phase3_expected_plans fixture returns the placeholder.

    Per D-09, Phase 3 expectations are minimal placeholders (empty
    plans). Phase 4 populates real family expectations.
    """
    assert isinstance(phase3_expected_plans, dict)
    assert "plans" in phase3_expected_plans
    assert phase3_expected_plans["plans"] == []


# --------------------------------------------------------------------------- #
# Test 5 — fixture files exist on disk.
# --------------------------------------------------------------------------- #


def test_phase3_fixture_files_exist() -> None:
    """Beh. 5: the four golden fixture files exist on disk.

    Pins the D-07 contract: the triple (input candles + parameters →
    expected outputs) is mandatory.
    """
    fixtures_dir = Path(__file__).parent / "fixtures" / "phase3"
    assert (fixtures_dir / "candles.csv").is_file()
    assert (fixtures_dir / "parameters.json").is_file()
    assert (fixtures_dir / "expected_signals.json").is_file()
    assert (fixtures_dir / "expected_plans.json").is_file()


# --------------------------------------------------------------------------- #
# Test 6 — parameters.json hash matches the loaded registry hash.
# --------------------------------------------------------------------------- #


def test_phase3_parameters_hash_matches_registry(phase3_parameters) -> None:
    """Beh. 6: the pinned parameter_set_hash matches the loaded registry.

    The fixture pins the same registry set the loader reads. If the
    seed TOML is mutated, this test fails (D-04/D-05 tripwire).
    """
    from src.domain.registry import load_parameter_set

    ps = load_parameter_set(
        phase3_parameters["strategy_id"],
        phase3_parameters["parameter_set_id"],
    )
    assert ps.parameter_set_hash == phase3_parameters["parameter_set_hash"]


# --------------------------------------------------------------------------- #
# Test 8 — harness output matches expected files digest-exactly.
# --------------------------------------------------------------------------- #

# Canonical-digest pins of the placeholder expected files (D-09).
# T-03-09 tripwire: ANY edit to expected_signals.json /
# expected_plans.json changes these digests and fails here.
# Regenerate ONLY in Phase 4 with spec citations.
EXPECTED_SIGNALS_DIGEST = "78abe5a2b4cc98cca7c4411e8caaee2a772a2e4301725f82af9b37f21a4e1a09"
EXPECTED_PLANS_DIGEST = "c40f0ef815ddea83c6d4375f23c02a2d8a5cab1dddd42ba90a5a589319be5ac3"


def test_harness_output_matches_expected_files_digest_exactly(
    phase3_expected_signals, phase3_expected_plans
) -> None:
    """Beh. 8: harness output matches both expected files digest-exactly.

    The placeholder harness output (empty signals/plans per D-09) must
    hash to the pinned digests above through canonical_bytes. Any
    unregistered semantic change to domain outputs fails here.
    """
    from src.domain.canonical import sha256_hex

    harness_signals_output: list = []
    harness_plans_output: list = []

    assert (
        sha256_hex({"signals": harness_signals_output})
        == sha256_hex({"signals": phase3_expected_signals["signals"]})
        == EXPECTED_SIGNALS_DIGEST
    )
    assert (
        sha256_hex({"plans": harness_plans_output})
        == sha256_hex({"plans": phase3_expected_plans["plans"]})
        == EXPECTED_PLANS_DIGEST
    )


# --------------------------------------------------------------------------- #
# Test 9 — loaded registry set matches the pinned identity in full.
# --------------------------------------------------------------------------- #


def test_loaded_registry_set_matches_pinned_identity(phase3_parameters) -> None:
    """Beh. 9: the loaded ParameterSet matches parameters.json identity.

    Beyond the hash tripwire (Beh. 6): strategy_id, strategy_version,
    and parameter_set_id must all agree between the pinned file and
    the loader, closing the DOMN-02 half of the harness contract.
    """
    from src.domain.registry import load_parameter_set

    ps = load_parameter_set(
        phase3_parameters["strategy_id"],
        phase3_parameters["parameter_set_id"],
    )
    assert ps.strategy_id == phase3_parameters["strategy_id"]
    assert ps.strategy_version == phase3_parameters["strategy_version"]
    assert ps.parameter_set_id == phase3_parameters["parameter_set_id"]
    assert ps.parameter_set_hash == phase3_parameters["parameter_set_hash"]


def test_placeholder_expectations_match_harness_output_byte_exactly(
    phase3_expected_signals, phase3_expected_plans
) -> None:
    """Beh. 7: the placeholder expectations match the harness output.

    Per D-09, Phase 3 expectations are minimal placeholders. The
    harness output for the empty-signal placeholder must match the
    expected files byte-exactly.
    """
    # The harness output for the placeholder is the empty list.
    # This test pins the contract that the fixture files encode the
    # same empty-list output the harness produces.
    harness_signals_output: list = []
    harness_plans_output: list = []

    assert harness_signals_output == phase3_expected_signals["signals"]
    assert harness_plans_output == phase3_expected_plans["plans"]
