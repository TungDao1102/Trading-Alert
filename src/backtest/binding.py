"""Registry↔cost binding gate (Phase 7.1, D-01/D-02/D-03).

Per D-01: `assemble()` is the single choke point where registry identity
and cost identity meet. The gate compares the loaded ParameterSet's
cost-key slice against the caller-supplied CostModel and raises a
dedicated exception on hash inequality — before any record exists.

Per D-02: comparison is canonical-hash-to-hash (`build_cost_model(
registry_slice).cost_model_hash == passed.cost_model_hash`), so the
comparison logic exists exactly once. The gate reuses `COST_KEYS` and
`build_cost_model` from `.costs` — never re-implements hashing.

Per D-03: the gate raises `CostModelBindingMismatch` (distinct from
`ExperimentReproducibilityBroken`, which means *replay drift* on an
existing record; this means *assembly refusal* before any record
exists). Absent slice keys propagate as bare `KeyError` from
`build_cost_model` (fail closed, never silent defaults).

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 / Phase-6 D-05 purity
precedent.
"""

from __future__ import annotations

from src.domain.registry import ParameterSet

from .costs import COST_KEYS, CostModel, build_cost_model


class CostModelBindingMismatch(Exception):
    """Raised when a CostModel does not bind the registry ParameterSet.

    Distinct from `ExperimentReproducibilityBroken` (that exception
    means *replay drift* on an existing record; this means *assembly
    refusal* before any record exists — D-03). A mismatched binding
    is a programming/identity error, not a market outcome, and the
    project fail-closed posture demands a loud raise.
    """


def assert_cost_model_binds_registry(parameter_set: ParameterSet, cost_model: CostModel) -> None:
    """Return None iff `cost_model` equals the registry cost-key slice.

    Builds `registry_slice = {k: parameter_set.params[k] for k in
    COST_KEYS}`, derives the expected `CostModel` via
    `build_cost_model(registry_slice)`, and compares
    `cost_model_hash` strings. Inequality raises
    `CostModelBindingMismatch` naming both hashes plus the set
    identity. Absent slice keys propagate as bare `KeyError` from
    `build_cost_model` (fail closed, never silent defaults — D-02).
    """
    registry_slice = {k: parameter_set.params[k] for k in COST_KEYS}
    expected = build_cost_model(registry_slice)
    if expected.cost_model_hash != cost_model.cost_model_hash:
        raise CostModelBindingMismatch(
            f"cost_model_hash {cost_model.cost_model_hash!r} != registry-derived "
            f"{expected.cost_model_hash!r} for "
            f"{parameter_set.strategy_id}/{parameter_set.parameter_set_id}"
        )


__all__ = ["CostModelBindingMismatch", "assert_cost_model_binds_registry"]
