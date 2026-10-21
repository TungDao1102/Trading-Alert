"""Pure feed-freshness predicates (Phase 20, plan 20-16; EXEC-02, OPS-05, D-25, D058).

`assess_feeds` answers two questions from an injected `FeedReading` and an injected `now_utc`:

  * which symbols have a missing or stale mark price (older than
    `stale_feed.max_mark_price_age_ms`), and
  * has the user-data stream been silent for longer than `stale_feed.max_user_data_silence_ms`.

Fail closed: a missing timestamp is stale, a symbol absent from the reading is stale, and a
threshold that is `NOT_CONFIGURED` (None) is refused with a ValueError, never defaulted. The two
thresholds are read from the `stale_feed_*` fields of the execution limits only; the paper
runtime's `max_ws_message_silence_seconds` belongs to another process and is not used (D-25).

A timestamp ahead of `now_utc` is clock skew between two machines, not staleness: it counts as
fresh here (staleness means "older than"). The ratified drift bound that judges a future mark
time lives in the pre-placement check; this module has none of its own and invents none.

Pure: stdlib and `src.domain` only, no clock read, no float, no I/O. The loop (plan 20-16) turns
a stale verdict into SAFE_MODE STALE_FEED plus a STALE_DATA alert; a feed that recovers never
leaves SAFE_MODE (only the operator does, D-15) and Phase 24 owns the LIVE enablement gate.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


class StaleFeedLimits(Protocol):
    """The two stale-feed fields of `ExecutionLimits` (None means NOT_CONFIGURED)."""

    @property
    def stale_feed_max_mark_price_age_ms(self) -> int | None: ...

    @property
    def stale_feed_max_user_data_silence_ms(self) -> int | None: ...


@dataclass(frozen=True)
class FeedReading:
    """What the two feeds last delivered.

    `mark_price_at_utc` maps a symbol to the time of its latest mark price (None = none yet);
    `user_data_last_event_at_utc` is the time of the latest user-data liveness signal.
    """

    mark_price_at_utc: Mapping[str, datetime | None]
    user_data_last_event_at_utc: datetime | None


@dataclass(frozen=True)
class FeedVerdict:
    """The symbols with a stale mark price (sorted, unique) and whether user data is silent."""

    stale_symbols: tuple[str, ...]
    user_data_silent: bool

    @property
    def any_stale(self) -> bool:
        return bool(self.stale_symbols) or self.user_data_silent


def assess_feeds(
    reading: FeedReading,
    *,
    symbols: Iterable[str],
    now_utc: datetime,
    limits: StaleFeedLimits,
) -> FeedVerdict:
    """Judge the mark price of each of `symbols` and the user-data feed.

    Args:
        reading: the latest feed times.
        symbols: the symbols with a tracked plan; only these mark prices are judged.
        now_utc: the injected current time (timezone-aware).
        limits: the execution limits (only the two `stale_feed_*` fields are read).

    Raises:
        ValueError: a datetime is naive, or a threshold is NOT_CONFIGURED.
    """
    _require_aware(now_utc, "now_utc")
    mark_limit = _limit(limits.stale_feed_max_mark_price_age_ms, "stale_feed.max_mark_price_age_ms")
    silence_limit = _limit(
        limits.stale_feed_max_user_data_silence_ms, "stale_feed.max_user_data_silence_ms"
    )
    stale = sorted(
        {s for s in symbols if _is_stale(reading.mark_price_at_utc.get(s), now_utc, mark_limit)}
    )
    silent = _is_stale(reading.user_data_last_event_at_utc, now_utc, silence_limit)
    return FeedVerdict(stale_symbols=tuple(stale), user_data_silent=silent)


def _limit(value: int | None, key: str) -> timedelta:
    if value is None or isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} is NOT_CONFIGURED (or not a non-negative int); no default exists")
    return timedelta(milliseconds=value)


def _is_stale(seen_at_utc: datetime | None, now_utc: datetime, limit: timedelta) -> bool:
    """Missing is stale; otherwise stale means strictly older than `limit`."""
    if seen_at_utc is None:
        return True
    _require_aware(seen_at_utc, "feed time")
    return now_utc - seen_at_utc > limit


def _require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


__all__ = ["FeedReading", "FeedVerdict", "StaleFeedLimits", "assess_feeds"]
