"""Thin total mappers between domain entities and ORM rows (Phase 3, plan 03-01).

Per D-02: PostgreSQL tables mirror the domain 1:1 via a separate ORM
layer. Thin mapper functions translate domain ↔ row; no ORM class IS
the domain model.

Mappers are total (every field mapped) and round-trip tested:
`from_row(to_row(x)) == x`.
"""

from __future__ import annotations

from src.db.models import SignalRow
from src.domain.enums import SignalStatus
from src.domain.signal import Signal


def signal_to_row(s: Signal) -> SignalRow:
    """Convert a domain Signal to its ORM row representation.

    `status` is stored as `SignalStatus.value` (the string) for ORM
    portability. The `from_row` path reconstructs the Enum via
    `SignalStatus(value)` — unknown values raise ValueError (D-10).
    """
    return SignalRow(
        signal_id=s.signal_id,
        strategy_id=s.strategy_id,
        strategy_version=s.strategy_version,
        parameter_set_id=s.parameter_set_id,
        parameter_set_hash=s.parameter_set_hash,
        symbol=s.symbol,
        direction=s.direction,
        setup_type=s.setup_type,
        source_timeframe=s.source_timeframe,
        source_candle_close_utc=s.source_candle_close_utc,
        detected_at_utc=s.detected_at_utc,
        status=s.status.value,
        expires_at_utc=s.expires_at_utc,
        invalidated_at_utc=s.invalidated_at_utc,
    )


def signal_from_row(r: SignalRow) -> Signal:
    """Convert an ORM SignalRow back to a domain Signal.

    `status` is reconstructed via `SignalStatus(value)` — unknown
    values raise ValueError (D-10 boundary contract).
    """
    return Signal(
        signal_id=r.signal_id,
        strategy_id=r.strategy_id,
        strategy_version=r.strategy_version,
        parameter_set_id=r.parameter_set_id,
        parameter_set_hash=r.parameter_set_hash,
        symbol=r.symbol,
        direction=r.direction,
        setup_type=r.setup_type,
        source_timeframe=r.source_timeframe,
        source_candle_close_utc=r.source_candle_close_utc,
        detected_at_utc=r.detected_at_utc,
        status=SignalStatus(r.status),
        expires_at_utc=r.expires_at_utc,
        invalidated_at_utc=r.invalidated_at_utc,
    )


__all__ = ["signal_to_row", "signal_from_row"]
