"""Pure risk package — sizing, quantization, portfolio, gating (Phase 5, plans 05-01 + 05-02).

Per D-05: this package imports NOTHING from Polars/pandas/NumPy/Binance
SDK/SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 purity precedent. The package is
dependency-free by construction; any future plan that wants to add a
third-party dependency here must first lift D-05.

This barrel re-exports the public symbols. No logic lives here.
"""

from __future__ import annotations

from .gating import evaluate_risk
from .portfolio import check_portfolio
from .quantization import quantize
from .sizing import size_position
from .types import ConstraintSnapshot, OpenPosition, PortfolioVerdict, SizedResult

__all__ = [
    # Types
    "ConstraintSnapshot",
    "OpenPosition",
    "PortfolioVerdict",
    "SizedResult",
    # Services
    "size_position",
    "quantize",
    "check_portfolio",
    "evaluate_risk",
]
