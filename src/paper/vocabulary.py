"""Shared paper-runtime vocabulary (Phase 16, plan 16-08, D-05 / D-06).

Pure module: stdlib and `Decimal` only. It names the things the supervisor, the resync
module, the bar pipeline and the runtime journal exchange, so none of them has to import the
others (and none has to import an exchange adapter):

- `SourceTag`: where a bar came from. Only `LIVE_WS` bars that pass the closed gate may reach
  `evaluate` (structural rule of L-11, not a freshness constant).
- `HealthState`, `GapReason`, `DropReason`, `RuntimeEventType`: closed vocabularies used as
  reason codes and event types (REV-01 reason codes: every gap carries one).
- `TaggedBar` and `GapRecord`: the frozen values the supervisor hands to its sinks.
- `INTERVAL_MS`: interval length in milliseconds for the intervals the runtime subscribes to.

Timestamps are tz-aware UTC datetimes (D-06); prices and volumes are `Decimal`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

# --------------------------------------------------------------------------- #
# Closed vocabularies.
# --------------------------------------------------------------------------- #


class SourceTag(StrEnum):
    """Where a bar entered the runtime."""

    LIVE_WS = "LIVE_WS"
    REST_WARMUP = "REST_WARMUP"
    REST_BACKFILL = "REST_BACKFILL"


class HealthState(StrEnum):
    """Feed health as the runtime reports it."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"


class GapReason(StrEnum):
    """Why an expected close is missing (REV-01: every gap carries a reason code)."""

    PROCESS_DOWN = "PROCESS_DOWN"
    WS_DISCONNECTED = "WS_DISCONNECTED"
    WS_RECONNECT_WINDOW = "WS_RECONNECT_WINDOW"
    PLANNED_RESTART = "PLANNED_RESTART"
    CRASH = "CRASH"
    MAINTENANCE = "MAINTENANCE"
    EXCHANGE_NO_CANDLE = "EXCHANGE_NO_CANDLE"
    UNKNOWN = "UNKNOWN"


class DropReason(StrEnum):
    """Why a feed event was dropped before it could become a bar.

    Vocabulary only: the bar pipeline (plan 16-24) reports the reason and the runtime
    (plan 16-26) journals it.
    """

    # A closed event whose close time is later than the tick time (clock skew, research P20).
    FUTURE_CLOSE = "FUTURE_CLOSE"


class RuntimeEventType(StrEnum):
    """Event types the runtime journals."""

    RUNTIME_START = "RUNTIME_START"
    RUNTIME_STOP = "RUNTIME_STOP"
    EPOCH_PINNED = "EPOCH_PINNED"
    PAPER_BAR_PROCESSED = "PAPER_BAR_PROCESSED"
    PAPER_GAP = "PAPER_GAP"
    # One record per consumer iteration (plan 16-26): tick time, dropped-event counts and the
    # measured tick duration (research P20 and A10).
    PAPER_TICK_STATS = "PAPER_TICK_STATS"
    WS_DISCONNECT = "WS_DISCONNECT"
    WS_RECONNECT = "WS_RECONNECT"
    HEALTH_STATE_CHANGED = "HEALTH_STATE_CHANGED"


# --------------------------------------------------------------------------- #
# Intervals.
# --------------------------------------------------------------------------- #

INTERVAL_MS: Mapping[str, int] = MappingProxyType(
    {
        "1m": 60_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
    }
)


# --------------------------------------------------------------------------- #
# Frozen values.
# --------------------------------------------------------------------------- #


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be UTC-aware")


@dataclass(frozen=True)
class TaggedBar:
    """One closed bar with the source it came from.

    `close_time_utc` follows the exchange convention: open + interval - 1 ms.
    """

    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: SourceTag

    def __post_init__(self) -> None:
        _require_utc("open_time_utc", self.open_time_utc)
        _require_utc("close_time_utc", self.close_time_utc)


@dataclass(frozen=True)
class GapRecord:
    """One expected close that no bar covers, with the reason it is missing."""

    symbol: str
    interval: str
    expected_close_utc: datetime
    reason: GapReason
    detected_at_utc: datetime

    def __post_init__(self) -> None:
        _require_utc("expected_close_utc", self.expected_close_utc)
        _require_utc("detected_at_utc", self.detected_at_utc)


__all__ = [
    "INTERVAL_MS",
    "DropReason",
    "GapReason",
    "GapRecord",
    "HealthState",
    "RuntimeEventType",
    "SourceTag",
    "TaggedBar",
]
