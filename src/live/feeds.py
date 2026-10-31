"""Feed sources of the live reconcile loop (plan 24-19, D-14, 20-DEFERRED feed-liveness row).

Three pieces bind the reconcile loop's optional protocols to the live process:

* `LiveFeedSource` implements `FeedSource.read_feed()` over two inputs and judges nothing itself
  (`assess_feeds` does, in the loop, with `stale_feed.max_user_data_silence_ms` and
  `stale_feed.max_mark_price_age_ms`):

  - The user-data time is the NEWEST of the supervisor's last event, last ping and last pong
    (`supervisor.liveness()`), plus the entry into LIVE while the stream is LIVE (the same
    signals `stream_is_stale` uses, research P12). Binance sends user-data events only on account
    activity, so the last event alone would put a quiet account into SAFE_MODE; a pong proves the
    connection. CLOCK: the supervisor stamps events, pings, pongs and the LIVE entry with ITS
    injected clock, which the composition binds to the process wall clock (WR-B6). `assess_feeds`
    compares them with the tick time of the loop (the same process clock) and tolerates the
    ratified drift skew ahead; no stream-side Binance time is mixed in.
  - The mark time of a symbol is the `exchange_time_utc` of the latest `MarkPriceReading`
    (REST `GET /fapi/v1/premiumIndex`, Binance's clock) that `refresh_marks` stored. A failed
    refresh keeps the older reading, so its mark ages and goes stale. A time ahead of now by more
    than the ratified drift is stale in `assess_feeds` (WR-B6, unchanged).

* `refresh_marks` is the body of the once-per-tick mark task: one `premiumIndex` call per tracked
  symbol through the reader (the shared REST gate sits inside `BinancePublicMarketData`). It never
  raises (cancellation excepted): a failure is logged by class name only and the old reading stays.

* `StreamDivergenceQueue` implements `StreamDivergenceSource`. The router's divergence sink calls
  `sink`; `drain()` hands the items over once in arrival order. The supervisor's `on_failure` and
  `on_state_change` callbacks feed `halted_reason()`: a halt reason until the stream is LIVE again.
  The queue is bounded by `max_items` (bind the stream's own `event_queue_max`); an item that does
  not fit is NOT dropped silently: the queue reports the overflow once through `on_overflow` and
  `halted_reason()` returns `DIVERGENCE_QUEUE_OVERFLOW` for good (the loop turns a halt into
  SAFE_MODE `USER_DATA_STREAM_HALTED`; only the operator leaves SAFE_MODE).

  Escalation (research C-5): the loop acts on a drained item only when its `kind` is
  `SINK_FAILURE` (SAFE_MODE `STREAM_SINK_FAILURE`); every other kind just triggers a REST query.
  The router surfaces a `CONDITIONAL_ORDER_TRIGGER_REJECT` frame (a rejected triggered stop) as a
  `STREAM_ANOMALY` divergence with anomaly kind `DEPRECATED_EVENT`, which would never reach
  SAFE_MODE. The queue therefore re-labels such an item as `SINK_FAILURE` (all other fields kept,
  fixed project reason) before it is queued. This is a stop-gap: Phase 25 should give the rejected
  triggered stop its own router kind and loop mapping (24-DEFERRED).

All methods run on the event loop thread; none blocks. No wall clock is read here (a clock is
injected), and no message text is read.
"""

from __future__ import annotations

import dataclasses
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from typing import Any, Protocol

import structlog

from src.adapters.binance_public import MarkPriceReading
from src.adapters.binance_userdata_router import StreamDivergence, StreamDivergenceKind
from src.adapters.binance_userdata_supervisor import LivenessSnapshot, StreamState
from src.reconcile.feed_freshness import FeedReading

log = structlog.get_logger(__name__)

#: `halted_reason()` once the queue lost an item (sticky).
REASON_DIVERGENCE_QUEUE_OVERFLOW = "DIVERGENCE_QUEUE_OVERFLOW"
#: The anomaly kind the router gives a CONDITIONAL_ORDER_TRIGGER_REJECT frame.
ESCALATED_ANOMALY_KIND = "DEPRECATED_EVENT"
#: Fixed project text of an escalated item (never exchange text).
ESCALATED_REASON = "a triggered conditional order was rejected (CONDITIONAL_ORDER_TRIGGER_REJECT)"


class LivenessSource(Protocol):
    """`UserDataSupervisor.liveness()`."""

    def liveness(self) -> LivenessSnapshot: ...


class MarkReader(Protocol):
    """`BinancePublicMarketData.mark_price` (REST premiumIndex through the shared gate)."""

    async def mark_price(self, symbol: str) -> MarkPriceReading: ...


class MarkBook:
    """The latest mark reading per symbol, written by `refresh_marks`, read by the feed source."""

    def __init__(self) -> None:
        self._readings: dict[str, MarkPriceReading] = {}
        self._failures: dict[str, str] = {}

    def store(self, reading: MarkPriceReading) -> None:
        self._readings[reading.symbol] = reading
        self._failures.pop(reading.symbol, None)

    def note_failure(self, symbol: str, error_class: str) -> None:
        self._failures[symbol] = error_class

    def reading(self, symbol: str) -> MarkPriceReading | None:
        return self._readings.get(symbol)

    def last_failure(self, symbol: str) -> str | None:
        """The class name of the latest failed refresh of `symbol`, None after a good one."""
        return self._failures.get(symbol)


def _newest(times: Iterable[datetime | None]) -> datetime | None:
    present = [t for t in times if t is not None]
    return max(present) if present else None


class LiveFeedSource:
    """`FeedSource` over the supervisor's liveness and the stored REST mark readings."""

    def __init__(
        self,
        *,
        supervisor: LivenessSource,
        marks: MarkBook,
        clock: Callable[[], datetime],
        symbols: Iterable[str],
    ) -> None:
        self._supervisor = supervisor
        self._marks = marks
        self._clock = clock
        self._symbols = tuple(dict.fromkeys(symbols))

    @property
    def symbols(self) -> tuple[str, ...]:
        return self._symbols

    def user_data_liveness(self) -> datetime | None:
        """Newest of last event, ping, pong (and the LIVE entry while LIVE); None = none yet."""
        snap = self._supervisor.liveness()
        entered_live = snap.state_since_utc if snap.state is StreamState.LIVE else None
        return _newest(
            (snap.last_event_at_utc, snap.last_ping_at_utc, snap.last_pong_at_utc, entered_live)
        )

    def read_feed(self) -> FeedReading:
        marks: dict[str, datetime | None] = {}
        for symbol in self._symbols:
            reading = self._marks.reading(symbol)
            marks[symbol] = None if reading is None else reading.exchange_time_utc
        return FeedReading(
            mark_price_at_utc=marks, user_data_last_event_at_utc=self.user_data_liveness()
        )


async def refresh_marks(*, reader: MarkReader, marks: MarkBook, symbols: Iterable[str]) -> int:
    """One `premiumIndex` call per tracked symbol; returns how many readings were stored.

    Never raises except for cancellation: a failed call keeps the older reading (which then ages)
    and records the exception class name only.
    """
    stored = 0
    for symbol in dict.fromkeys(symbols):
        try:
            reading = await reader.mark_price(symbol)
        except Exception as exc:  # noqa: BLE001 - logged by class name, the old reading ages
            marks.note_failure(symbol, type(exc).__name__)
            log.warning("live.feeds.mark_refresh_failed", symbol=symbol, error=type(exc).__name__)
            continue
        marks.store(reading)
        stored += 1
    return stored


class StreamDivergenceQueue:
    """`StreamDivergenceSource` fed by the router's divergence sink (see the module docstring)."""

    def __init__(
        self,
        *,
        max_items: int,
        on_overflow: Callable[[], None] | None = None,
    ) -> None:
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
            raise ValueError("max_items must be a positive int")
        self._max = max_items
        self._items: deque[StreamDivergence] = deque()
        self._halt: str | None = None
        self._overflowed = False
        self._on_overflow = on_overflow
        self.escalated = 0

    # -- router side ---------------------------------------------------------------------- #

    def sink(self, divergence: StreamDivergence) -> None:
        """The router's `divergence_sink`: queue one item, escalating a rejected triggered stop."""
        if divergence.anomaly_kind == ESCALATED_ANOMALY_KIND:
            divergence = dataclasses.replace(
                divergence, kind=StreamDivergenceKind.SINK_FAILURE, reason=ESCALATED_REASON
            )
            self.escalated += 1
        if len(self._items) >= self._max:
            self._report_overflow()
            return
        self._items.append(divergence)

    def _report_overflow(self) -> None:
        if self._overflowed:
            return
        self._overflowed = True
        log.error("live.feeds.divergence_queue_overflow", max_items=self._max)
        if self._on_overflow is not None:
            try:
                self._on_overflow()
            except Exception as exc:  # noqa: BLE001 - the halt reason is the durable signal
                log.warning("live.feeds.overflow_callback_failed", error=type(exc).__name__)

    # -- supervisor side ------------------------------------------------------------------ #

    def note_failure(self, reason: str) -> None:
        """Bind to the supervisor's `on_failure`: a halt waits for a resync."""
        self._halt = reason

    def note_state(self, state: StreamState, reason: str) -> None:
        """Bind to the supervisor's `on_state_change`: LIVE again clears the halt."""
        del reason
        if state is StreamState.LIVE:
            self._halt = None

    # -- loop side ------------------------------------------------------------------------ #

    def drain(self) -> Sequence[Any]:
        taken = tuple(self._items)
        self._items.clear()
        return taken

    def halted_reason(self) -> str | None:
        if self._overflowed:
            return REASON_DIVERGENCE_QUEUE_OVERFLOW
        return self._halt

    def __len__(self) -> int:
        return len(self._items)


__all__ = [
    "ESCALATED_ANOMALY_KIND",
    "ESCALATED_REASON",
    "REASON_DIVERGENCE_QUEUE_OVERFLOW",
    "LiveFeedSource",
    "LivenessSource",
    "MarkBook",
    "MarkReader",
    "StreamDivergenceQueue",
    "refresh_marks",
]
