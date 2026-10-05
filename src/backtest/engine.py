"""v2 event-loop engine (Phase 14, plan 14-08, RED skeleton)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.risk.types import PortfolioVerdict

from .semantics import PLAN_SOURCE_SCRIPTED, SIMULATOR_SEMANTICS_VERSION

RiskFn = Callable[..., PortfolioVerdict]


def simulate(
    case_input: dict[str, Any], *, risk_fn: RiskFn, minute_source: Any = None
) -> dict[str, Any]:
    return {
        "trades": [],
        "run_summary": {
            "no_trade_counts": {},
            "plan_source": PLAN_SOURCE_SCRIPTED,
            "allowed_gaps_used": [],
            "simulator_semantics_version": SIMULATOR_SEMANTICS_VERSION,
        },
        "strategy_version": "",
        "parameter_set_hash": "",
        "cost_model_hash": "",
        "symbols": [],
    }
