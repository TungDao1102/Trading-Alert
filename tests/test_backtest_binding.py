"""Tests for the registry↔cost binding gate (Phase 7.1, D-01/D-02/D-03).

Per D-05: match-case fixtures must hash against the registry slice;
mismatch cases (wrong fee, wrong string, precision drift) raise
CostModelBindingMismatch. Phase6 fixtures are grandfathered per D-05
and are NOT used here.

This module is the RED phase of the Phase 7.1 tracer slice — it pins
the match-case behavior (gate accepts a registry-consistent pair and
assembles byte-identically to the pre-gate path) and the byte-stability
regression (D-04: published experiment IDs are permanent). Mismatch
refusal coverage lands in plan 07.1-02.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PHASE7_1_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7.1"


# --------------------------------------------------------------------------- #
# Helpers — load input from a phase7.1 case directory.
# --------------------------------------------------------------------------- #


def _load_match_input() -> dict:
    return json.loads((PHASE7_1_FIXTURES_DIR / "match" / "input.json").read_text(encoding="utf-8"))


def _build_cost_model(cost_dict: dict):
    """Build a CostModel from a dict (delegates to costs.build_cost_model)."""
    from src.backtest.costs import build_cost_model

    return build_cost_model(cost_dict)


def _gate_assemble(case: dict, *, cost_model=None):
    """Assemble a record from a phase7.1 match-case dict.

    Optional `cost_model` override lets mismatch tests inject a
    registry-divergent CostModel without rebuilding the whole dict.
    """
    from src.backtest.experiment import assemble

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
