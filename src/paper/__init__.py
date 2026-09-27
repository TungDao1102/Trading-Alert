"""Pure paper-loop package — realtime forward-observation engine (Phase 7, plan 07-01).

Per D-01/D-02/D-05: this package imports NOTHING from
Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic — stdlib + Decimal +
`src/core/_decimal.py` only, mirroring the Phase-4 D-10 / Phase-5 D-05 /
Phase-6 D-05 purity precedent. The WS surface lives behind
`src/adapters/paper_ws.py` (adapter-boundary isolation, RESEARCH §Pattern 1).

This barrel re-exports the public symbols. No logic lives here.
"""

from __future__ import annotations

from .attribution import APPROVAL_DELAY_LAG_SECONDS, AttributionKind
from .freeze import (
    DiffLogEntry,
    FreezeCheckOutcome,
    StreamEpoch,
    check_registry_unchanged,
    pin_stream_epoch,
)
from .journal import (
    PaperRecord,
    assemble_no_trade_record,
    assemble_paper_record,
    paper_records_digest,
)
from .loop import run_paper_tick

__all__ = [
    "APPROVAL_DELAY_LAG_SECONDS",
    "AttributionKind",
    "DiffLogEntry",
    "FreezeCheckOutcome",
    "PaperRecord",
    "StreamEpoch",
    "assemble_no_trade_record",
    "assemble_paper_record",
    "check_registry_unchanged",
    "paper_records_digest",
    "pin_stream_epoch",
    "run_paper_tick",
]
