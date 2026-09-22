"""Signal frozen dataclass (Phase 3, plan 03-01).

Per D-01/D-02/D-11/D-12: frozen pure-Python dataclass with Decimal
money/qty/price fields, timezone-aware UTC datetime fields, and Enum
status fields. No `Optional` status; `Optional` is reserved for
"transition never happened" timestamps only.

The Signal entity carries the DATA_MODEL §2.3 field list. Phase 3
implements the minimum slice needed for the tracer; remaining fields
land in plan 03-02.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .enums import SignalStatus


@dataclass(frozen=True)
class Signal:
    """A deterministic statement that the strategy detected a setup.

    `signal_id` is the content hash from `ids.make_signal_id` — never
    passed in by callers. `status` is explicit (D-11); NULL timestamps
    mean "transition never happened".
    """

    signal_id: str
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    symbol: str
    direction: str  # LONG/SHORT — Phase 4 may promote to Enum
    setup_type: str
    source_timeframe: str
    source_candle_close_utc: datetime  # aware UTC
    detected_at_utc: datetime
    status: SignalStatus  # explicit — never inferred (D-11)
    expires_at_utc: datetime
    invalidated_at_utc: datetime | None = None  # None = "never happened"
