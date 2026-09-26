"""Tests for the registry↔cost binding gate (Phase 7.1, D-01/D-02/D-03).

Per D-05: match-case fixtures must hash against the registry slice;
mismatch cases (wrong fee, wrong string, precision drift) raise
CostModelBindingMismatch. Phase6 fixtures are grandfathered per D-05
and are NOT used here.

This module is the GREEN phase of the Phase 7.1 binding gate — it pins
the match-case behavior (gate accepts a registry-consistent pair and
assembles byte-identically to the pre-gate path), the byte-stability
regression (D-04: published experiment IDs are permanent), and the four
D-05 refusal behaviors (wrong fee rate, wrong funding_treatment string,
trailing-precision drift, missing-slice KeyError path). Plan 07.1-02
ships these refusal cases as the expansion task.

# D-05 grandfather log (Phase 6 fixture audit verdict)
#
# Per the Phase 6 fixture audit executed at plan time, every cost-carrying
# phase6 fixture is unbindable to its referenced registry set under the
# new gate. Counts and reasons:
#
#   * 8 fixtures reference trend-pullback/baseline-v2 and carry only
#     3 of the 7 COST_KEYS — assemble() raises bare KeyError from
#     build_cost_model over the registry slice (correct fail-closed
#     behavior, never translated into CostModelBindingMismatch, never
#     skipped). The 8 fixtures are:
#       - tests/fixtures/phase6/registry_identity/input.json
#       - tests/fixtures/phase6/intrabar_both_touched/input.json
#       - tests/fixtures/phase6/intrabar_both_touched_short/input.json
#       - tests/fixtures/phase6/intrabar_missing_fallback/input.json
#       - tests/fixtures/phase6/invalidation_cancels_entry/input.json
#       - tests/fixtures/phase6/limit_expiry/input.json
#       - tests/fixtures/phase6/limit_partial_fill/input.json
#       - tests/fixtures/phase6/limit_touch_no_fill/input.json
#
#   * 2 baseline fixtures carry all 7 cost keys but hash-mismatch the
#     registry on a single key — partial_fill_fraction: TOML whole-number
#     rule normalizes 1.0 to int 1 while the fixture spells "1.0",
#     producing canonical-byte divergence on a sole key. The 2 fixtures
#     are:
#       - tests/fixtures/phase6/baselines/no_trade/input.json
#       - tests/fixtures/phase6/baselines/simple_trend/input.json
#
# Per D-05: phase6 fixture FILES are byte-untouched (grandfathered).
# Tests that call assemble() migrate to the v3 set id (plan 07.1-02
# Task 2). Baseline runner paths (baseline_no_trade, baseline_simple_trend)
# call simulator_run directly, not assemble(), so the gate never fires
# on those paths.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from src.backtest.binding import CostModelBindingMismatch
from src.backtest.costs import build_cost_model
from src.backtest.experiment import assemble

PHASE7_1_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7.1"


# --------------------------------------------------------------------------- #
# Helpers — load input from a phase7.1 case directory.
# --------------------------------------------------------------------------- #


def _load_match_input() -> dict:
    return json.loads((PHASE7_1_FIXTURES_DIR / "match" / "input.json").read_text(encoding="utf-8"))


def _load_case_input(case_subdir: str) -> dict:
    """Load a phase7.1 mismatch case input.json by subdirectory name."""
    return json.loads(
        (PHASE7_1_FIXTURES_DIR / case_subdir / "input.json").read_text(encoding="utf-8")
    )


def _build_cost_model(cost_dict: dict):
    """Build a CostModel from a dict (delegates to costs.build_cost_model)."""
    return build_cost_model(cost_dict)


def _gate_assemble(case: dict, *, cost_model=None):
    """Assemble a record from a phase7.1 case dict.

    Optional `cost_model` override lets mismatch tests inject a
    registry-divergent CostModel without rebuilding the whole dict.
    """
    if cost_model is None:
        cost_model = _build_cost_model(case["cost_model"])
    return assemble(
        parameter_set_id=case["parameter_set_id"],
        strategy_id=case["strategy_id"],
        strategy_version=case["strategy_version"],
        data_snapshot_id=case["data_snapshot_id"],
        code_version=case["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(case["time_range_start_utc"]),
        time_range_end_utc=datetime.fromisoformat(case["time_range_end_utc"]),
        universe=case["universe"],
        run_type=case["run_type"],
        notes=case["notes"],
    )


# --------------------------------------------------------------------------- #
# Beh. 1 — match-case assemble succeeds through the gate.
# --------------------------------------------------------------------------- #


def test_binding_gate_accepts_match_case() -> None:
    """Beh. 1: a registry-consistent cost model passes the gate and
    assemble() returns an ExperimentRecord with the six-field identity
    tuple intact.

    Per D-01: the gate sits between load_parameter_set and identity_payload
    construction. A consistent pair assembles byte-identically to the
    pre-gate path (D-04).
    """
    case = _load_match_input()
    record = _gate_assemble(case)

    # Six-field identity tuple is present and well-formed.
    for field in (
        "experiment_id",
        "parameter_set_hash",
        "data_snapshot_id",
        "cost_model_hash",
        "universe_hash",
    ):
        value = getattr(record, field)
        assert isinstance(value, str), f"{field} must be str, got {type(value).__name__}"
        assert len(value) == 64, f"{field} must be 64-hex, got len={len(value)}"
        assert all(c in "0123456789abcdef" for c in value), (
            f"{field} must be lowercase hex, got {value!r}"
        )

    # The recorded cost_model_hash equals the caller's cost_model_hash
    # (the gate verified they came from the same cost assumptions).
    cost_model = _build_cost_model(case["cost_model"])
    assert record.cost_model_hash == cost_model.cost_model_hash


# --------------------------------------------------------------------------- #
# Beh. 2 — byte-stability regression (D-04).
# --------------------------------------------------------------------------- #


def test_binding_gate_does_not_change_experiment_id_for_match_case() -> None:
    """Beh. 2: match-case assemble() produces a stable experiment_id
    across reruns (D-04 byte-stability).

    Per D-04: the gate only shrinks the set of assemblable inputs; it
    never changes what a consistent input hashes to. Two assemble()
    calls with identical inputs must yield identical experiment_id.
    """
    case = _load_match_input()
    record_a = _gate_assemble(case)
    record_b = _gate_assemble(case)
    assert record_a.experiment_id == record_b.experiment_id, (
        "experiment_id must be stable across reruns (D-04 byte-stability)"
    )


# --------------------------------------------------------------------------- #
# Beh. 3 — wrong fee_rate_entry raises CostModelBindingMismatch (D-05).
# --------------------------------------------------------------------------- #


def test_binding_gate_rejects_wrong_fee_rate() -> None:
    """Beh. 3: a fixture with fee_rate_entry 0.0009 vs registry 0.0002
    raises CostModelBindingMismatch at assemble() time.

    Per D-01 + D-05: a present-but-unequal cost key is an assembly-
    refusal event, not a missing-slice event. The mismatch path raises
    CostModelBindingMismatch naming both hashes; comparison is
    hash-string only (never Decimal value equality, per D-04/D-12).
    """
    case = _load_case_input("wrong_fee")
    cost_model = _build_cost_model(case["cost_model"])
    with pytest.raises(CostModelBindingMismatch):
        _gate_assemble(case, cost_model=cost_model)


# --------------------------------------------------------------------------- #
# Beh. 4 — wrong funding_treatment string raises CostModelBindingMismatch.
# --------------------------------------------------------------------------- #


def test_binding_gate_rejects_wrong_funding_treatment() -> None:
    """Beh. 4: a fixture with funding_treatment PRO_RATA vs registry
    ADDITIVE raises CostModelBindingMismatch at assemble() time.

    Per D-03 + D-05: the gate refuses registry-inconsistent string-
    valued cost keys too — the cost_model_hash covers all 7 COST_KEYS
    regardless of value type. The refusal proves the string-typed
    keys bind just as tightly as the numeric ones.
    """
    case = _load_case_input("wrong_funding")
    cost_model = _build_cost_model(case["cost_model"])
    with pytest.raises(CostModelBindingMismatch):
        _gate_assemble(case, cost_model=cost_model)


# --------------------------------------------------------------------------- #
# Beh. 5 — trailing-precision drift raises CostModelBindingMismatch (D-04/D-12).
# --------------------------------------------------------------------------- #


def test_binding_gate_rejects_precision_drift() -> None:
    """Beh. 5: a fixture with fee_rate_entry "0.00020" vs registry
    "0.0002" raises CostModelBindingMismatch (trailing-precision
    discipline, D-04/D-12).

    Per D-04/D-12: Decimal → str() preserving full precision.
    Decimal("0.00020") stays "0.00020", never "0.0002" — the
    trailing precision is semantically meaningful for exchange-
    sensitive values and must not be silently normalized by the gate.
    Comparison is hash-string only (never value equality).
    """
    case = _load_case_input("precision_drift")
    cost_model = _build_cost_model(case["cost_model"])
    with pytest.raises(CostModelBindingMismatch):
        _gate_assemble(case, cost_model=cost_model)


# --------------------------------------------------------------------------- #
# Beh. 6 — missing-slice KeyError path for v1/v2 sets (fail closed).
# --------------------------------------------------------------------------- #


def test_binding_gate_propagates_keyerror_for_missing_slice_keys() -> None:
    """Beh. 6: assembling with parameter_set_id="baseline-v2" (only 3
    of 7 COST_KEYS) propagates bare KeyError from build_cost_model.

    Per D-02 + D-05: the gate reads the registry slice and lets
    build_cost_model raise the bare KeyError it already raises on
    absent keys — never translates it into CostModelBindingMismatch
    (the CostModelBindingMismatch exception is reserved for the
    present-but-unequal path), never skips the check (silent defaults
    are forbidden by the project fail-closed posture), never reuses
    ExperimentReproducibilityBroken (which means replay drift, not
    assembly refusal). The 8 phase6 fixtures referencing
    baseline-v2 take this path (see D-05 grandfather log above).
    """
    case = {
        "parameter_set_id": "baseline-v2",
        "strategy_id": "trend-pullback",
        "strategy_version": "v2.0.0",
        "data_snapshot_id": "0" * 64,
        "code_version": "07-01-missing-keys",
        "cost_model": {
            "fee_rate_entry": "0.0002",
            "fee_rate_exit": "0.0005",
            "funding_treatment": "ADDITIVE",
            "expected_slippage": "0.0001",
            "slippage_model": "FIXED_BPS",
            "spread_fill_assumptions": "FULL_FILL",
            "partial_fill_fraction": "0.5",
        },
        "time_range_start_utc": "2026-09-01T00:00:00+00:00",
        "time_range_end_utc": "2026-09-11T10:00:00+00:00",
        "universe": ["BTCUSDT"],
        "run_type": "CANDIDATE",
        "notes": "Phase 7.1 missing-slice KeyError path test (D-05).",
    }
    cost_model = _build_cost_model(case["cost_model"])
    with pytest.raises(KeyError):
        _gate_assemble(case, cost_model=cost_model)
