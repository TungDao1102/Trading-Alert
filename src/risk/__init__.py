"""Pure risk package — sizing, quantization, portfolio, gating (Phase 5, plans 05-01 + 05-02).

Phase 12 (plan 12-03) adds `cost_rates`: the `CostRates` value object and the
price-aware `per_unit_round_trip_cost` producer.

Per D-05: this package imports NOTHING from Polars/pandas/NumPy/Binance
SDK/SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 purity precedent. The package is
dependency-free by construction; any future plan that wants to add a
third-party dependency here must first lift D-05.

This barrel re-exports the public symbols. No logic lives here.
"""

from __future__ import annotations

from .cost_rates import CostRates, per_unit_round_trip_cost
from .gating import evaluate_risk, size_and_quantize
from .portfolio import check_portfolio, resolve_absolute_thresholds
from .quantization import quantize
from .sizing import size_position
from .types import ConstraintSnapshot, OpenPosition, PortfolioVerdict, SizedResult

__all__ = [
    # Types
    "ConstraintSnapshot",
    "CostRates",
    "OpenPosition",
    "PortfolioVerdict",
    "SizedResult",
    # Services
    "size_position",
    "quantize",
    "check_portfolio",
    "resolve_absolute_thresholds",
    "evaluate_risk",
    "size_and_quantize",
    "per_unit_round_trip_cost",
]
