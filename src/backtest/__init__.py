"""Pure backtest package — simulator, costs, experiment, report (Phase 6, plan 06-01).

Per D-05: this package imports NOTHING from Polars/pandas/NumPy/Binance
SDK/SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent. The package
is dependency-free by construction; any future plan that wants to add a
third-party dependency here must first lift D-05.

This barrel re-exports the public symbols. No logic lives here.
"""
from __future__ import annotations

from .costs import CostModel, build_cost_model, modeled_costs_per_unit
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
    "IntrabarOutcome",
    "SimulatorResult",
    "TradeRecord",
    # Services
    "build_cost_model",
    "modeled_costs_per_unit",
    "resolve_intrabar",
    "run",
]
