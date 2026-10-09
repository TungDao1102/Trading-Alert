"""Paper-loop WS supervisor (Phase 7 plan 07-02, rewritten in Phase 16 plan 16-08).

The supervisor owns the subscription lifecycle of the paper loop behind the project's
`PaperWsAdapter` (`src/adapters/paper_ws.py`): an awaited `start()` connects and subscribes
every (symbol, interval) pair, and only CLOSED klines reach the `on_closed_bar` sink, as
`TaggedBar` values tagged `SourceTag.LIVE_WS`. Forming updates are ignored by design.

One rotation owner (research P3). The SDK owns reconnection and the 23 h connection
replacement; the supervisor adds no rotation timer. It reacts to the SDK connection events
(callbacks run on the event-loop thread, research D6, so a callback only schedules a task):

- `open` / `reconnect`: a REST verification backfill from the last close per pair.
- `close` / `error`: records `WS_DISCONNECT`, rebuilds the adapter under a bounded retry,
  records `WS_RECONNECT`, then runs the same backfill. When the rebuild is exhausted the
  backfill still runs (CR-02) and every close it cannot recover becomes a `GapRecord`
  with `GapReason.WS_DISCONNECTED`.

Nothing is only logged (P9): backfilled bars go to `on_backfill` (tagged `REST_BACKFILL`),
gaps go to `on_gap` with a reason code, connection events go to `on_connection_event`.

The last-close state per (symbol, interval) only moves forward (`_advance_last_close`), so a
bar is never delivered twice across a reconnect seam (D-28). While a recovery is pending,
live closed bars are held and delivered after the backfilled bars, so a live bar can never
move the cursor past a bar the backfill is still about to recover.

The module imports no order adapter and no data-layer module: the public-data `Kline` type
comes from `src/adapters/binance_public.py`.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
import tenacity

from src.adapters.binance_public import Kline as RestKline
from src.adapters.paper_ws import LIFECYCLE_EVENTS
from src.adapters.paper_ws import Kline as WsKline

from .resync import backfill_missed_closes, expected_close_times
from .vocabulary import (
    GapReason,
    GapRecord,
    RuntimeEventType,
    SourceTag,
    TaggedBar,
)

log = structlog.get_logger()


# --------------------------------------------------------------------------- #
# Bounded-retry ceilings. Implementation values, not ratified thresholds (O-07): they stay
# unchanged from Phase 7 and are tabulated for the user's decision in plan 16-27.
# --------------------------------------------------------------------------- #

SUPERVISOR_MAX_ATTEMPTS: int = 7
SUPERVISOR_MAX_DELAY_SECONDS: int = 120
SUPERVISOR_WAIT_MULTIPLIER_SECONDS: int = 1
SUPERVISOR_WAIT_MAX_SECONDS: int = 60

# SDK connection events after which the connection is considered lost and must be rebuilt.
_DROP_EVENTS = frozenset({"close", "error"})


# --------------------------------------------------------------------------- #
# Adapter protocols — the minimum surface the supervisor needs.
# --------------------------------------------------------------------------- #


class WsAdapterLike(Protocol):
    """Anything that quacks like `PaperWsAdapter` (every SDK-facing call is a coroutine)."""

    async def connect(self) -> None: ...

    def on_connection(self, event: str, callback: Callable[..., None]) -> None: ...

    async def subscribe(
        self,
        *,
        symbol: str,
        interval: str,
        on_kline: Callable[[WsKline], None],
        stream_id: str | None = None,
    ) -> Any: ...

    async def unsubscribe(self, handle: Any) -> None: ...

    async def close(self) -> None: ...

    async def rebuild(self) -> None: ...


class RestAdapterLike(Protocol):
    """Anything that quacks like `BinancePublicMarketData` for klines."""

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[RestKline]: ...


# --------------------------------------------------------------------------- #
# PaperSupervisor.
# --------------------------------------------------------------------------- #


class PaperSupervisor:
    """Owns the subscriptions of the paper loop and hands bars, gaps and events to sinks.

    The composition root names the symbols and intervals; there is no default universe.
    Sinks (all synchronous, all must only record or enqueue, never block):

    - `on_closed_bar(TaggedBar)`: a closed live kline, tagged `LIVE_WS`.
    - `on_backfill(TaggedBar)`: a REST-recovered close, tagged `REST_BACKFILL`.
    - `on_gap(GapRecord)`: an expected close that no bar covers, with a reason code. The same
      (symbol, interval, expected close) is reported at most once.
    - `on_connection_event(RuntimeEventType, datetime)`: `WS_DISCONNECT` / `WS_RECONNECT`.
    """

    def __init__(
        self,
        *,
        ws_adapter: WsAdapterLike,
        rest_adapter: RestAdapterLike,
        symbols: tuple[str, ...],
        intervals: tuple[str, ...],
        on_closed_bar: Callable[[TaggedBar], None],
        on_backfill: Callable[[TaggedBar], None],
        on_gap: Callable[[GapRecord], None],
        on_connection_event: Callable[[RuntimeEventType, datetime], None],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ws = ws_adapter
        self._rest = rest_adapter
        self._symbols = symbols
        self._intervals = intervals
        self._on_closed_bar = on_closed_bar
        self._on_backfill = on_backfill
        self._on_gap = on_gap
        self._on_connection_event = on_connection_event
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))
        self._last_close: dict[tuple[str, str], datetime] = {}
        # Guards the check-and-set in _advance_last_close. SDK callbacks run on the event-loop
        # thread (research D6), so the lock only protects the race between the live path and
        # the backfill path.
        self._last_close_lock = threading.Lock()
        self._handles: list[tuple[str, str, Any]] = []
        self._close_failures: int = 0
        self._started = False
        self._stopping = False
        self._rebuilding = False
        self._disconnected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._recovery_lock = asyncio.Lock()
        # Events accepted from the SDK whose recovery has not finished; live bars are held
        # while it is positive.
        self._pending_events = 0
        self._held: list[tuple[str, str, WsKline]] = []
        self._emitted_gaps: set[tuple[str, str, datetime]] = set()
        # Built once so the adapter's duplicate check keeps a retried start() from registering
        # the same callback twice.
        self._connection_handlers: dict[str, Callable[..., None]] = {
            event: self._make_connection_handler(event) for event in LIFECYCLE_EVENTS
        }

    def record_close(self, symbol: str, interval: str, close_time_utc: datetime) -> None:
        """Record the last-seen close for a pair.

        Called by the dispatch path when a closed kline arrives, and by the runtime before
        `start()` to seed the cursor from restored state (P8). The supervisor uses it to know
        where to resume a backfill. Monotonic (D-28): an earlier or equal close never moves
        the stored value backwards.
        """
        self._advance_last_close(symbol, interval, close_time_utc)

    def _advance_last_close(self, symbol: str, interval: str, close_time_utc: datetime) -> bool:
        """Atomically move the pair's last close forward.

        Returns True only when there is no stored close or the new close is strictly later
        (the bar is new); False when the close is at or before the stored one (a duplicate or
        stale bar). The check and the store happen under one lock so concurrent callers cannot
        both claim the same bar (T-13-10).
        """
        key = (symbol, interval)
        with self._last_close_lock:
            stored = self._last_close.get(key)
            if stored is not None and close_time_utc <= stored:
                return False
            self._last_close[key] = close_time_utc
            return True

    # ------------------------------------------------------------------ #
    # Lifecycle.
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Register for connection events, connect, then subscribe every symbol-interval pair.

        Idempotent guard (WR-08): a second start() without stop() would double-subscribe every
        pair (two callbacks per close), so it raises loudly. A failure part-way rolls back
        (IN-03): the handles already created are unsubscribed and the connection closed, so a
        retry of start() is possible.
        """
        if self._started or self._handles:
            raise RuntimeError(
                "PaperSupervisor.start() called twice without stop(); "
                "the SDK owns reconnection, so there is nothing to restart"
            )
        self._loop = asyncio.get_running_loop()
        self._stopping = False
        try:
            # The adapter records the callbacks and applies them to the connections it opens.
            for event, handler in self._connection_handlers.items():
                self._ws.on_connection(event, handler)
            await self._ws.connect()
            for symbol in self._symbols:
                for interval in self._intervals:
                    handle = await self._ws.subscribe(
                        symbol=symbol.lower(),
                        interval=interval,
                        on_kline=self._make_kline_handler(symbol, interval),
                    )
                    self._handles.append((symbol, interval, handle))
        except Exception:
            await self._rollback()
            raise
        self._started = True

    async def stop(self) -> None:
        """Cancel any running recovery, unsubscribe every stream and close the connection."""
        self._stopping = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._held.clear()
        await self._rollback()
        self._started = False

    async def wait_idle(self) -> None:
        """Wait until every scheduled connection-event recovery has finished.

        Connection callbacks only schedule a task; the composition root and the tests use this
        to wait for the recovery they triggered.
        """
        await asyncio.sleep(0)  # let a just-scheduled recovery task be created
        while True:
            pending = [task for task in self._tasks if not task.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    # ------------------------------------------------------------------ #
    # Live path.
    # ------------------------------------------------------------------ #

    def _make_kline_handler(self, symbol: str, interval: str) -> Callable[[WsKline], None]:
        def _on_kline(kline: WsKline) -> None:
            # Only closed klines advance the dispatch and last-close state. Forming updates
            # (x=False) are ignored by design.
            if not kline.is_closed:
                return
            if self._pending_events > 0:
                # A recovery is pending: deliver after the backfilled bars so this bar cannot
                # move the cursor past a bar the backfill is about to recover.
                self._held.append((symbol, interval, kline))
                return
            self._deliver_live(symbol, interval, kline)

        return _on_kline

    def _deliver_live(self, symbol: str, interval: str, kline: WsKline) -> None:
        # Monotonic guard (D-28): a closed kline at or before the pair's last close was
        # already delivered (via backfill or an earlier WS message) and is dropped.
        if not self._advance_last_close(symbol, interval, kline.close_time_utc):
            log.warning(
                "paper.supervisor.duplicate_close_dropped",
                symbol=symbol,
                interval=interval,
                close_time=kline.close_time_utc.isoformat(),
            )
            return
        bar = TaggedBar(
            symbol=symbol,
            interval=interval,
            open_time_utc=kline.open_time_utc,
            close_time_utc=kline.close_time_utc,
            open=kline.open,
            high=kline.high,
            low=kline.low,
            close=kline.close,
            volume=kline.volume,
            source=SourceTag.LIVE_WS,
        )
        if not self._call_sink("on_closed_bar", self._on_closed_bar, bar):
            self._emit_sink_failure_gap(bar)

    def _flush_held(self) -> None:
        held, self._held = self._held, []
        if self._stopping:
            if held:
                log.info("paper.supervisor.held_bars_discarded", count=len(held))
            return
        for symbol, interval, kline in sorted(held, key=lambda item: item[2].close_time_utc):
            self._deliver_live(symbol, interval, kline)

    # ------------------------------------------------------------------ #
    # SDK connection events.
    # ------------------------------------------------------------------ #

    def _make_connection_handler(self, event: str) -> Callable[..., None]:
        def _handler(*_args: Any, **_kwargs: Any) -> None:
            self._on_sdk_event(event)

        return _handler

    def _on_sdk_event(self, event: str) -> None:
        """React to one SDK connection event; only counts and schedules, never does I/O."""
        if not self._started or self._stopping or self._rebuilding or self._loop is None:
            # Before start, after stop, or the echo of our own rebuild closing the old client.
            log.debug("paper.supervisor.event_ignored", sdk_event=event)
            return
        self._pending_events += 1
        self._loop.call_soon_threadsafe(self._spawn, event)

    def _spawn(self, event: str) -> None:
        assert self._loop is not None  # set by start(); events are ignored before it
        task = self._loop.create_task(self._run_event(event))
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("paper.supervisor.event_failed", error=f"{type(exc).__name__}: {exc}")

    async def _run_event(self, event: str) -> None:
        try:
            async with self._recovery_lock:
                if self._stopping:
                    return
                if event in _DROP_EVENTS:
                    await self._recover_from_drop()
                else:
                    await self._verify_after_reconnect(event)
        finally:
            self._pending_events -= 1
            if self._pending_events == 0:
                self._flush_held()

    async def _verify_after_reconnect(self, event: str) -> None:
        """The SDK replaced or reopened the connection: verify the seam against REST."""
        if event == "reconnect" or self._disconnected:
            self._disconnected = False
            self._emit_connection_event(RuntimeEventType.WS_RECONNECT, self._clock())
        await self._backfill_and_emit(GapReason.WS_RECONNECT_WINDOW)

    async def _recover_from_drop(self) -> None:
        """An unsolicited close or error: rebuild, then backfill whatever the drop cost."""
        self._disconnected = True
        self._emit_connection_event(RuntimeEventType.WS_DISCONNECT, self._clock())
        if await self._rebuild_with_retry():
            self._disconnected = False
            self._emit_connection_event(RuntimeEventType.WS_RECONNECT, self._clock())
            reason = GapReason.WS_RECONNECT_WINDOW
        else:
            # Reconnect exhaustion must not skip the backfill (CR-02): the unrecoverable-WS
            # case is exactly when the REST backfill matters most.
            reason = GapReason.WS_DISCONNECTED
        await self._backfill_and_emit(reason)

    async def _rebuild_with_retry(self) -> bool:
        """Tenacity-bounded `ws.rebuild()`; True when it succeeded, False when exhausted."""
        # Cancellation (stop()) is never retried: tenacity records any BaseException as a
        # failed attempt.
        retry = tenacity.retry_if_exception(lambda e: not isinstance(e, asyncio.CancelledError))
        stop = tenacity.stop_after_attempt(SUPERVISOR_MAX_ATTEMPTS) | tenacity.stop_after_delay(
            SUPERVISOR_MAX_DELAY_SECONDS
        )
        wait = tenacity.wait_random_exponential(
            multiplier=SUPERVISOR_WAIT_MULTIPLIER_SECONDS,
            max=SUPERVISOR_WAIT_MAX_SECONDS,
        )
        decorator = tenacity.AsyncRetrying(retry=retry, stop=stop, wait=wait, reraise=True)
        self._rebuilding = True
        try:
            async for attempt in decorator:
                with attempt:
                    await self._ws.rebuild()
            return True
        except Exception as exc:
            log.error(
                "paper.supervisor.reconnect_exhausted",
                error=f"{type(exc).__name__}: {exc}",
            )
            return False
        finally:
            self._rebuilding = False

    # ------------------------------------------------------------------ #
    # Backfill with per-pair isolation.
    # ------------------------------------------------------------------ #

    async def _backfill_and_emit(self, reason: GapReason) -> None:
        """Backfill every pair from its last close and hand the result to the sinks (P9)."""
        now = self._clock()
        bars, gaps = await self._backfill_pairs(now, reason)
        for bar in bars:
            if not self._call_sink("on_backfill", self._on_backfill, bar):
                self._emit_sink_failure_gap(bar)
        # A live bar held during the recovery covers its own slot: not a gap.
        held_closes = {(symbol, interval, k.close_time_utc) for symbol, interval, k in self._held}
        for gap in gaps:
            if (gap.symbol, gap.interval, gap.expected_close_utc) not in held_closes:
                self._emit_gap(gap)

    async def _backfill_pairs(
        self, now: datetime, reason: GapReason
    ) -> tuple[list[TaggedBar], list[GapRecord]]:
        """Backfill every pair from its last close, keeping only new closes.

        A close is kept only when `_advance_last_close` accepts it, in close_time order, so the
        returned closes are strictly newer than anything already delivered and the last-close
        state ends at the latest kept bar (D-28). Per-pair try/except isolation: a raising pair
        contributes one `GapRecord` per expected close it could not recover (WR-09) and the
        remaining pairs still run. A hole the exchange reported (`EXCHANGE_NO_CANDLE`) is
        re-labelled with the reason of the window that was being verified.
        """
        bars: list[TaggedBar] = []
        gaps: list[GapRecord] = []
        for symbol in self._symbols:
            for interval in self._intervals:
                last = self._last_close.get((symbol, interval))
                if last is None:
                    # No prior close recorded for this pair: nothing to backfill from. Loud
                    # (not silent): the runtime seeds the cursor through record_close (P8).
                    log.error(
                        "paper.supervisor.no_last_close",
                        symbol=symbol,
                        interval=interval,
                    )
                    continue
                try:
                    closes, found = await backfill_missed_closes(
                        self._rest,
                        symbol=symbol,
                        interval=interval,
                        last_close_utc=last,
                        now_utc=now,
                    )
                except Exception as exc:
                    log.warning(
                        "paper.supervisor.backfill_failed",
                        symbol=symbol,
                        interval=interval,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    gaps.extend(
                        GapRecord(
                            symbol=symbol,
                            interval=interval,
                            expected_close_utc=expected_close,
                            reason=reason,
                            detected_at_utc=now,
                        )
                        for expected_close in expected_close_times(last, now, interval)
                    )
                    continue
                kept = [
                    bar
                    for bar in closes
                    if self._advance_last_close(symbol, interval, bar.close_time_utc)
                ]
                if kept:
                    log.info(
                        "paper.supervisor.backfilled",
                        symbol=symbol,
                        interval=interval,
                        closes=len(kept),
                    )
                bars.extend(kept)
                gaps.extend(
                    replace(gap, reason=reason)
                    if gap.reason is GapReason.EXCHANGE_NO_CANDLE
                    else gap
                    for gap in found
                )
        return bars, gaps

    # ------------------------------------------------------------------ #
    # Sinks.
    # ------------------------------------------------------------------ #

    def _call_sink(self, name: str, sink: Callable[..., None], *args: Any) -> bool:
        """Call a sink; a failing sink is logged and reported, never propagated into the SDK."""
        try:
            sink(*args)
        except Exception as exc:
            log.error(
                "paper.supervisor.sink_failed", sink=name, error=f"{type(exc).__name__}: {exc}"
            )
            return False
        return True

    def _emit_gap(self, gap: GapRecord) -> None:
        key = (gap.symbol, gap.interval, gap.expected_close_utc)
        if key in self._emitted_gaps:
            return
        self._emitted_gaps.add(key)
        log.warning(
            "paper.supervisor.gap",
            symbol=gap.symbol,
            interval=gap.interval,
            expected_close=gap.expected_close_utc.isoformat(),
            reason=str(gap.reason),
        )
        self._call_sink("on_gap", self._on_gap, gap)

    def _emit_sink_failure_gap(self, bar: TaggedBar) -> None:
        """A bar the sink refused is a hole: record it instead of losing it silently."""
        self._emit_gap(
            GapRecord(
                symbol=bar.symbol,
                interval=bar.interval,
                expected_close_utc=bar.close_time_utc,
                reason=GapReason.UNKNOWN,
                detected_at_utc=self._clock(),
            )
        )

    def _emit_connection_event(self, event: RuntimeEventType, at: datetime) -> None:
        self._call_sink("on_connection_event", self._on_connection_event, event, at)

    # ------------------------------------------------------------------ #
    # Teardown.
    # ------------------------------------------------------------------ #

    async def _rollback(self) -> None:
        """Unsubscribe every handle we own, then close the connection (best effort).

        ``_close_failures`` persists across calls and is reset only when a full pass succeeds,
        so the logged count is truly consecutive.
        """
        pass_clean = True
        for symbol, interval, handle in self._handles:
            try:
                await self._ws.unsubscribe(handle)
            except Exception:
                # A failed unsubscribe is logged but does not propagate: the supervisor must
                # survive a wedged handle (WR-08).
                pass_clean = False
                self._close_failures += 1
                log.warning(
                    "paper.supervisor.close_failed",
                    symbol=symbol,
                    interval=interval,
                    handle_id=id(handle),
                    consecutive_close_failures=self._close_failures,
                )
        self._handles.clear()
        try:
            await self._ws.close()
        except Exception as exc:
            pass_clean = False
            self._close_failures += 1
            log.warning(
                "paper.supervisor.close_failed",
                error=f"{type(exc).__name__}: {exc}",
                consecutive_close_failures=self._close_failures,
            )
        if pass_clean:
            self._close_failures = 0


__all__ = [
    "SUPERVISOR_MAX_ATTEMPTS",
    "SUPERVISOR_MAX_DELAY_SECONDS",
    "SUPERVISOR_WAIT_MAX_SECONDS",
    "SUPERVISOR_WAIT_MULTIPLIER_SECONDS",
    "PaperSupervisor",
    "RestAdapterLike",
    "WsAdapterLike",
]
