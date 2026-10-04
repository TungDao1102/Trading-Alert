"""Shared temporal trade-record validator (Phase 14, plan 14-01, D-23).

`validate_trade_record` asserts the temporal invariants of one trade record and
RAISES `TradeRecordInvariantError` on a violation — it never warns and never logs.
It runs inside the record builder and, from plan 14-11, again at every normalizer
boundary.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .records import TradeRecord


class TradeRecordInvariantError(Exception):
    """A trade record violates a causal or temporal invariant (D-23, F-804)."""


def validate_trade_record(
    record: TradeRecord,
    *,
    data_start_utc: datetime | None = None,
    data_end_utc: datetime | None = None,
) -> None:
    """Raise `TradeRecordInvariantError` unless `record` satisfies the invariants.

    Minimal contract of the tracer slice: a filled record carries its signal close and
    its `entry_time` is strictly later than it; `exit_time` is not earlier than
    `entry_time`. The full D-23 contract is completed in Task 2 of plan 14-01.
    """
    if record.entry_time_utc is None:
        return
    if record.signal_close_utc is None:
        raise TradeRecordInvariantError(
            f"signal_close_utc is required on a filled record (entry_time {record.entry_time_utc})"
        )
    if not record.entry_time_utc > record.signal_close_utc:
        raise TradeRecordInvariantError(
            f"entry_time {record.entry_time_utc.isoformat()} must be > "
            f"signal_close {record.signal_close_utc.isoformat()}"
        )
    if record.exit_time_utc is not None and record.exit_time_utc < record.entry_time_utc:
        raise TradeRecordInvariantError(
            f"exit_time {record.exit_time_utc.isoformat()} must be >= "
            f"entry_time {record.entry_time_utc.isoformat()}"
        )
    del data_start_utc, data_end_utc  # window check lands in Task 2
