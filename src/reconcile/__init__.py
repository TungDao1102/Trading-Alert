"""Reconcile package — three-source compare + cancel-only sweeper + SAFE_MODE.

Per D-03 (reconciliation is the exchange-truth safety net): the
reconciler compares local intent against three exchange-truth sources
(normal orders, algo orders, positions), classifies divergences, and
either leaves them alone or sweeps orphan protectives via the
adapter's cancel surface. The reconciler NEVER places a new order
under any input (D-03 + EXEC-02 acceptance proof).

Public surface (the only symbols downstream code uses):

  - `compare.compare(...)` — three-source set-difference compare.
  - `sweeper.OrphanSweeper` — cancel-only orphan-protective sweep.
  - `safe_mode.SafeModeController` — SAFE_MODE enter/guard/exit.

The package is dependency-free: stdlib + `src/domain/*` + sibling
modules only. No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
The adapter is consumed via Protocol-typed surfaces; only
`src/adapters/binance_usdm.py` imports the SDK.
"""

from __future__ import annotations

from .compare import (
    DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
    DIVERGENCE_KIND_ORPHAN_PROTECTIVE,
    DIVERGENCE_KIND_UNSYNCED_ALGO,
    DIVERGENCE_KIND_UNSYNCED_NORMAL,
    DIVERGENCE_KIND_UNSYNCED_POSITION,
    CompareDiff,
    Divergence,
    compare,
)
from .safe_mode import (
    SafeModeController,
    SafeModeVerdict,
)
from .sweeper import OrphanSweeper, SweepOutcome, SweepSkip

__all__ = [
    # compare
    "compare",
    "CompareDiff",
    "Divergence",
    "DIVERGENCE_KIND_ORPHAN_PROTECTIVE",
    "DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE",
    "DIVERGENCE_KIND_UNSYNCED_ALGO",
    "DIVERGENCE_KIND_UNSYNCED_POSITION",
    "DIVERGENCE_KIND_UNSYNCED_NORMAL",
    # sweeper
    "OrphanSweeper",
    "SweepOutcome",
    "SweepSkip",
    # safe_mode
    "SafeModeController",
    "SafeModeVerdict",
]
