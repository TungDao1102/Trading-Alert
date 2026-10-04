"""Tests for the registry↔cost binding gate (Phase 7.1, D-01/D-02/D-03).

Per D-05: match-case fixtures must hash against the registry slice;
mismatch cases (wrong fee, wrong string) raise CostModelBindingMismatch;
an equivalent numeric spelling (the former "precision drift" case) now
binds because cost identity is canonical numeric text (Phase 12, D-15).
Phase6 fixtures are grandfathered per D-05 and are NOT used here.

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
#
# Phase 12 update (D048): the list above is the Phase 7.1 audit verdict and
# stays as history. Phase 12 (plan 12-04) regenerated the seven simulator
# fixtures (intrabar_both_touched, intrabar_both_touched_short,
# intrabar_missing_fallback, invalidation_cancels_entry, limit_expiry,
# limit_partial_fill, limit_touch_no_fill) and the two baselines from
# scripts/gen_phase6_fixtures.py onto the Phase 12 identity: baseline-v5 and
# baseline-no-trade-v3 / baseline-simple-trend-v3, strategy v4.0.0, the 8-key
# cost dict, and a realistic candle geometry (the two stale baseline
# expected.json files had no consumer and were removed). They now bind their
# registry sets directly, except limit_touch_no_fill and limit_partial_fill,
# whose partial_fill_fraction is deliberately 0 / 0.5. The
# registry_identity fixture is unchanged and stays grandfathered, and the
# phase-7.1 binding fixtures are unaffected. No test in this file changed.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from src.backtest.binding import CostModelBindingMismatch
from src.backtest.costs import CostModel, build_cost_model
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
# Beh. 5 — equivalent numeric spelling binds (D-15); genuine change refused.
# --------------------------------------------------------------------------- #


def test_binding_gate_accepts_equivalent_spelling() -> None:
    """Beh. 5: a fixture with fee_rate_entry "0.00020" vs registry
    "0.0002" now binds (D-15 canonical numeric text).

    Supersedes the Phase 7.1 D-04/D-12 trailing-precision refusal: cost
    identity is the value, so an equivalent spelling must not fail a
    correct binding (F-608). A genuine value change is still refused by
    test_binding_gate_rejects_wrong_fee_rate (the wrong_fee case).
    Comparison stays hash-string only.
    """
    case = _load_case_input("precision_drift")
    cost_model = _build_cost_model(case["cost_model"])
    record = _gate_assemble(case, cost_model=cost_model)
    match_model = _build_cost_model(_load_match_input()["cost_model"])
    assert record.cost_model_hash == match_model.cost_model_hash


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


# --------------------------------------------------------------------------- #
# Beh. 7 — build_cost_model rejects non-string/empty string cost values (WR-02).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", ["funding_treatment", "slippage_model", "spread_fill_assumptions"])
@pytest.mark.parametrize("bad_value", [None, 123, ""])
def test_build_cost_model_rejects_non_string_cost_values(key: str, bad_value: object) -> None:
    """Beh. 7: build_cost_model raises TypeError for non-string or empty
    string-valued cost keys instead of silently coercing via str().

    Per WR-02: a mistyped caller/fixture value such as
    funding_treatment=None or 123 must fail loud at the boundary
    (TypeError naming the field), never coerce to "None"/"123" and
    surface downstream as a hash mismatch (CostModelBindingMismatch).
    The base dict is the all-valid-string match-fixture spelling with
    exactly one key mutated per case.
    """
    cost_dict = dict(_load_match_input()["cost_model"])
    cost_dict[key] = bad_value
    with pytest.raises(TypeError, match=key):
        _build_cost_model(cost_dict)


# --------------------------------------------------------------------------- #
# Beh. 8 — direct-int vs builder-int cost_model_hash convergence (WR-03).
# --------------------------------------------------------------------------- #


def test_direct_int_cost_model_converges_with_builder_hash() -> None:
    """Beh. 8: a directly-constructed CostModel with int numerics produces
    the SAME cost_model_hash as build_cost_model with the same logical
    values.

    Per WR-03: CostModel.__post_init__ normalizes numeric fields via
    object.__setattr__ so both construction paths converge on Decimal
    before hashing. Covers all four numeric fields as int (including
    whole-number rates (0; rates above 0.01 are refused, D-04) and the
    partial_fill_fraction upper bound 1), and asserts the stored fields are Decimal.
    """
    base = _load_match_input()["cost_model"]
    int_cost = {
        **base,
        "fee_rate_entry": 0,
        "fee_rate_exit": 0,
        "expected_slippage": 0,
        "partial_fill_fraction": 1,
    }
    via_builder = _build_cost_model(int_cost)
    direct = CostModel(
        fee_rate_entry=0,  # type: ignore[arg-type]
        fee_rate_exit=0,  # type: ignore[arg-type]
        funding_treatment=int_cost["funding_treatment"],
        expected_slippage=0,  # type: ignore[arg-type]
        slippage_model=int_cost["slippage_model"],
        spread_fill_assumptions=int_cost["spread_fill_assumptions"],
        partial_fill_fraction=1,  # type: ignore[arg-type]
        cost_model_hash="",
    )
    assert direct.cost_model_hash == via_builder.cost_model_hash, (
        "direct-int and builder-int construction must converge on one hash (WR-03)"
    )
    for fname in (
        "fee_rate_entry",
        "fee_rate_exit",
        "expected_slippage",
        "partial_fill_fraction",
    ):
        assert isinstance(getattr(direct, fname), Decimal), (
            f"{fname} must be normalized to Decimal, got {type(getattr(direct, fname)).__name__}"
        )


# --------------------------------------------------------------------------- #
# Beh. 9 — Decimal inputs pass through un-respelled (WR-03 byte-stability).
# --------------------------------------------------------------------------- #


def test_decimal_cost_inputs_hash_equal_to_string_baseline() -> None:
    """Beh. 9: directly-constructed Decimal cost inputs hash identically to
    the all-string build_cost_model baseline, and equivalent spellings
    converge.

    Per WR-03 + D-15: Decimal inputs are coerced without a str() round
    trip, and the hash uses canonical numeric text, so Decimal("0.0002"),
    "0.0002" and Decimal("0.00020") all converge on one hash.
    """
    baseline = _build_cost_model(_load_match_input()["cost_model"])
    direct = CostModel(
        fee_rate_entry=Decimal("0.0002"),
        fee_rate_exit=Decimal("0.0005"),
        funding_treatment="ADDITIVE",
        expected_slippage=Decimal("0.0001"),
        slippage_model="FIXED_BPS",
        spread_fill_assumptions="FULL_FILL",
        partial_fill_fraction=Decimal("0.5"),
        cost_model_hash="",
    )
    assert direct.cost_model_hash == baseline.cost_model_hash, (
        "Decimal inputs must pass through un-respelled to the baseline hash (WR-03)"
    )
    drift = CostModel(
        fee_rate_entry=Decimal("0.00020"),
        fee_rate_exit=Decimal("0.0005"),
        funding_treatment="ADDITIVE",
        expected_slippage=Decimal("0.0001"),
        slippage_model="FIXED_BPS",
        spread_fill_assumptions="FULL_FILL",
        partial_fill_fraction=Decimal("0.5"),
        cost_model_hash="",
    )
    assert drift.cost_model_hash == baseline.cost_model_hash, (
        "equivalent spellings must converge on one cost hash (D-15)"
    )


# --------------------------------------------------------------------------- #
# Plan 14-04 — funding_convention binds both gates hash-to-hash (D-16, D-36).
# --------------------------------------------------------------------------- #


def _v5_registry_pair():
    from src.backtest.costs import cost_slice
    from src.domain.registry import load_parameter_set

    parameter_set = load_parameter_set("trend-pullback", "baseline-v5")
    return parameter_set, dict(cost_slice(parameter_set.params))


def test_gates_accept_v5_model_carrying_funding_convention() -> None:
    from src.backtest.binding import (
        assert_cost_model_binds_registry,
        assert_sizing_costs_bind_registry,
    )
    from src.backtest.semantics import FUNDING_CONVENTION

    parameter_set, registry_slice = _v5_registry_pair()
    assert registry_slice["funding_convention"] == FUNDING_CONVENTION
    model = build_cost_model(registry_slice)
    assert_cost_model_binds_registry(parameter_set, model)
    assert_sizing_costs_bind_registry(parameter_set, model)


def test_gates_refuse_v5_model_lacking_funding_convention() -> None:
    from src.backtest.binding import (
        assert_cost_model_binds_registry,
        assert_sizing_costs_bind_registry,
    )

    parameter_set, registry_slice = _v5_registry_pair()
    del registry_slice["funding_convention"]
    model = build_cost_model(registry_slice)
    assert model.funding_convention is None
    with pytest.raises(CostModelBindingMismatch):
        assert_cost_model_binds_registry(parameter_set, model)
    with pytest.raises(CostModelBindingMismatch):
        assert_sizing_costs_bind_registry(parameter_set, model)


def test_legacy_set_slice_never_carries_funding_convention() -> None:
    from src.backtest.costs import cost_slice
    from src.domain.registry import load_parameter_set

    legacy = cost_slice(load_parameter_set("trend-pullback", "baseline-v4").params)
    assert "funding_convention" not in legacy
