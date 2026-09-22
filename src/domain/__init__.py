"""Domain package — pure, dependency-free value objects (Phase 3, plan 03-01).

Per D-01: the strategy core imports NOTHING from SQLAlchemy, Pydantic,
Polars, or the Binance SDK. Dependency-free domain keeps Phase 4 pure
functions testable without a DB.

This barrel re-exports the public symbols. No logic lives here.
"""

from __future__ import annotations

from .enums import (
    ApprovalAction,
    OrderStatus,
    PositionStatus,
    RejectionReason,
    SignalStatus,
    SystemMode,
    TradePlanStatus,
    TradeStatus,
)
from .ids import derive_child_id, make_signal_id
from .registry import (
    ParameterSet,
    RegistrySchemaMismatch,
    StrategyKeyOutsideRegistry,
    UnregisteredParameterSet,
    load_parameter_set,
    verify_parameter_set,
)
from .signal import Signal

__all__ = [
    # Enums
    "SignalStatus",
    "TradePlanStatus",
    "ApprovalAction",
    "OrderStatus",
    "TradeStatus",
    "PositionStatus",
    "SystemMode",
    "RejectionReason",
    # Entities
    "Signal",
    # IDs
    "make_signal_id",
    "derive_child_id",
    # Registry
    "ParameterSet",
    "load_parameter_set",
    "verify_parameter_set",
    "UnregisteredParameterSet",
    "RegistrySchemaMismatch",
    "StrategyKeyOutsideRegistry",
]
