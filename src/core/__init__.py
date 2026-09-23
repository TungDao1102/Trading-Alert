"""Pure-core package — feature engine, strategy function, planner (Phase 4, plan 04-01).

Per D-01/D-10: the pure core imports NOTHING from Polars/pandas/NumPy/Binance
SDK/SQLAlchemy/Pydantic — stdlib + Decimal only, mirroring the Phase-3 D-01
domain purity precedent. This barrel re-exports the public symbols.

The package is dependency-free by construction. Any future plan that wants
to add a third-party dependency here must first lift D-10.
"""

from __future__ import annotations

from .features import compute_features, ema_update, true_range
from .planner import plan
from .strategy import evaluate
from .types import (
    AccountState,
    Candle,
    FeatureFrame,
    FeatureOutput,
    MarketSnapshot,
    SetupResult,
)

__all__ = [
    # Types
    "Candle",
    "FeatureOutput",
    "FeatureFrame",
    "SetupResult",
    "MarketSnapshot",
    "AccountState",
    # Features
    "compute_features",
    "ema_update",
    "true_range",
    # Strategy
    "evaluate",
    # Planner
    "plan",
]
