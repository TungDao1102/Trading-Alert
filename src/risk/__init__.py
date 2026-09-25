"""Pure risk package — sizing, quantization, gating (Phase 5, plan 05-01).

Per D-05: this package imports NOTHING from Polars/pandas/NumPy/Binance
SDK/SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 purity precedent. The package is
dependency-free by construction; any future plan that wants to add a
third-party dependency here must first lift D-05.

This barrel re-exports the public symbols. No logic lives here.
"""

from __future__ import annotations

from .gating import evaluate_risk
from .quantization import quantize
from .sizing import size_position
from .types import ConstraintSnapshot, SizedResult

__all__ = [
    # Types
    "ConstraintSnapshot",
    "SizedResult",
    # Services
    "size_position",
    "quantize",
    "evaluate_risk",
]
