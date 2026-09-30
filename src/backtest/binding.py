"""Registry↔cost binding gate (Phase 7.1, D-01/D-02/D-03).

Per D-01: `assemble()` is the single choke point where registry identity
and cost identity meet. The gate compares the loaded ParameterSet's
cost-key slice against the caller-supplied CostModel and raises a
dedicated exception on hash inequality — before any record exists.

Per D-02: comparison is canonical-hash-to-hash (`build_cost_model(
registry_slice).cost_model_hash == passed.cost_model_hash`), so the
comparison logic exists exactly once. The gate reuses `cost_slice` and
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

from .costs import CostModel, build_cost_model, cost_slice


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

    Builds `registry_slice = cost_slice(parameter_set.params)` (the seven
    required cost keys, plus `exit_slippage_rate` when the registry set
    carries it, so a Phase 12 set binds its stop-exit slippage rate and a
    model missing or disagreeing on it is refused), derives the expected
    `CostModel` via
    `build_cost_model(registry_slice)`, and compares
    `cost_model_hash` strings. Inequality raises
    `CostModelBindingMismatch` naming both hashes plus the set
    identity. Absent slice keys propagate as bare `KeyError` from
    `build_cost_model` (fail closed, never silent defaults — D-02).
    """
    registry_slice = cost_slice(parameter_set.params)
    expected = build_cost_model(registry_slice)
    if expected.cost_model_hash != cost_model.cost_model_hash:
        raise CostModelBindingMismatch(
            f"cost_model_hash {cost_model.cost_model_hash!r} != registry-derived "
            f"{expected.cost_model_hash!r} for "
            f"{parameter_set.strategy_id}/{parameter_set.parameter_set_id}"
        )


def assert_sizing_costs_bind_registry(parameter_set: ParameterSet, cost_model: CostModel) -> None:
    """Return None iff every sizing-relevant cost of `cost_model` matches the registry.

    Used by the single-case entry points (`simulator.run`, `run_paper_tick`),
    which size with a fixture-supplied cost dict while the guard thresholds
    come from the registry set (12-REVIEW WR-03). The comparison is the
    `assert_cost_model_binds_registry` hash-to-hash test with one field
    excluded: `partial_fill_fraction` is an execution-scenario knob applied to
    the filled quantity AFTER sizing (the partial-fill fixtures set it to a
    value the registry does not pin), so it never influences the fee, slippage
    or guard inputs of the risk gate. Every other cost key, including a
    missing or divergent `exit_slippage_rate`, is refused. Raises
    `CostModelBindingMismatch`; absent registry keys propagate as `KeyError`.
    """
    registry_slice = cost_slice(parameter_set.params)
    registry_slice["partial_fill_fraction"] = cost_model.partial_fill_fraction
    expected = build_cost_model(registry_slice)
    if expected.cost_model_hash != cost_model.cost_model_hash:
        raise CostModelBindingMismatch(
            f"sizing cost model (hash {cost_model.cost_model_hash!r}, excluding "
            f"partial_fill_fraction) does not match the registry set "
            f"{parameter_set.strategy_id}/{parameter_set.parameter_set_id} "
            f"(expected hash {expected.cost_model_hash!r})"
        )


__all__ = [
    "CostModelBindingMismatch",
    "assert_cost_model_binds_registry",
    "assert_sizing_costs_bind_registry",
]
