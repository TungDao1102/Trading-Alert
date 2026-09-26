"""Pure paper-loop package — realtime forward-observation engine (Phase 7, plan 07-01).

Per D-01/D-02/D-05: this package imports NOTHING from
Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic — stdlib + Decimal +
`src/core/_decimal.py` only, mirroring the Phase-4 D-10 / Phase-5 D-05 /
Phase-6 D-05 purity precedent. The WS surface lives behind
`src/adapters/paper_ws.py` (adapter-boundary isolation, RESEARCH §Pattern 1).

This barrel re-exports the public symbols. No logic lives here.
"""

from __future__ import annotations

from .loop import run_paper_tick

__all__ = ["run_paper_tick"]
