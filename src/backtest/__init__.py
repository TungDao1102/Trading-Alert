"""Pure backtest package — simulator, costs, experiment, report (Phase 6, plan 06-01).

Per D-05: this package imports NOTHING from Polars/pandas/NumPy/Binance
SDK/SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent. The package
is dependency-free by construction; any future plan that wants to add a
third-party dependency here must first lift D-05.

This barrel re-exports the public symbols. No logic lives here.
"""

from __future__ import annotations

from .binding import CostModelBindingMismatch, assert_cost_model_binds_registry
from .costs import CostModel, build_cost_model, cost_rates_from_model, modeled_costs_per_unit
from .experiment import (
    ExperimentRecord,
    ExperimentReproducibilityBroken,
    IncompleteExperimentRecord,
    assemble,
    baseline_no_trade,
    baseline_simple_trend,
    reproduce,
    verify_experiment,
)
from .simulator import (
    IntrabarOutcome,
    SimulatorResult,
    TradeRecord,
    resolve_intrabar,
    run,
)

__all__ = [
    # Types
    "CostModel",
    "ExperimentRecord",
    "IntrabarOutcome",
    "SimulatorResult",
    "TradeRecord",
    # Exceptions
    "CostModelBindingMismatch",
    "ExperimentReproducibilityBroken",
    "IncompleteExperimentRecord",
    # Services
    "assert_cost_model_binds_registry",
    "assemble",
    "baseline_no_trade",
    "baseline_simple_trend",
    "build_cost_model",
    "cost_rates_from_model",
    "modeled_costs_per_unit",
    "reproduce",
    "resolve_intrabar",
    "run",
    "verify_experiment",
]
