"""Public backtest entry point - delegates to the v2 event-loop engine (Phase 14, plan 14-12).

`run(case_input, *, minute_source=None)` is the one function the experiment layer, the
paper parity gate and the analytics adapters call. Since plan 14-12 it contains no
simulation logic of its own: it hands the case-input v2 dict to
`src.backtest.engine.simulate` together with the shared risk function.

The risk function is `evaluate_risk` looked up in THIS module's globals at call time, never
captured earlier (D-01). A test that monkeypatches `src.backtest.simulator.evaluate_risk`
therefore intercepts every risk call the engine makes, and the engine itself never imports
`evaluate_risk`. The simulator never re-implements risk math: it delegates to
`src/risk/gating.evaluate_risk` identically.

The v1 per-bar simulator is gone: the fixture-clock expiry shortcut, the per-signal-bar
intrabar map, the single-exit TP1 path and the bar-direction invalidation heuristic no
longer exist anywhere in `src/backtest` (D-01, D-04, D-35). `TradeRecord` stays importable
from here so every analytics and adapter import keeps working.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic - stdlib + Decimal + the pure `src` core only, mirroring the Phase-4
D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from typing import Any

from src.risk.gating import evaluate_risk

from .engine import simulate
from .records import TradeRecord
from .series import MinuteSource


def run(
    case_input: dict[str, Any],
    *,
    minute_source: MinuteSource | None = None,
) -> dict[str, Any]:
    """Run the v2 engine on a case-input v2 dict and return its output dict.

    The output carries `trades` (`TradeRecord.to_dict()` projections in deterministic
    order), `run_summary`, `strategy_version`, `parameter_set_hash`, `cost_model_hash` and
    `symbols`; see `src.backtest.engine.simulate`. A `minute_source` (for example the
    Polars-backed one of `src/data`) wins over the `trade_bars_1m` / `mark_bars_1m` rows of
    the case.

    Raises:
        ValueError: a v1-shaped case (removed keys), a malformed case, a strategy version
            that differs from the registry, or no minute data at all.
        TypeError: a float anywhere in the case.
        CostModelBindingMismatch: the case cost model disagrees with the registry set.
    """
    # `evaluate_risk` is resolved from the module globals here, at call time: a monkeypatch
    # of src.backtest.simulator.evaluate_risk reaches every engine risk call (D-01).
    return simulate(case_input, risk_fn=evaluate_risk, minute_source=minute_source)


__all__ = ["TradeRecord", "run", "simulate"]
