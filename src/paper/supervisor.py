"""Paper-loop WS supervisor (Phase 7 plan 07-02, rewritten in Phase 16 plan 16-08).

The supervisor owns the subscription lifecycle of the paper loop behind the project's
`PaperWsAdapter` (`src/adapters/paper_ws.py`): an awaited `start()` connects and subscribes
every (symbol, interval) pair, and only CLOSED klines reach the `on_closed_bar` sink, as
`TaggedBar` values tagged `SourceTag.LIVE_WS`. Forming updates are ignored by design.

The last-close state per (symbol, interval) only moves forward (`_advance_last_close`), so a
bar is never delivered twice across a reconnect seam (D-28).

The module imports no order adapter and no data-layer module: the public-data `Kline` type
comes from `src/adapters/binance_public.py`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from src.adapters.binance_public import Kline as RestKline
from src.adapters.paper_ws import Kline as WsKline

from .vocabulary import (
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
    """Owns the subscriptions of the paper loop and hands closed bars to explicit sinks.

    The composition root names the symbols and intervals; there is no default universe.
    Sinks (all synchronous, all must only record or enqueue, never block):

    - `on_closed_bar(TaggedBar)`: a closed live kline, tagged `LIVE_WS`.
    - `on_backfill(TaggedBar)`: a REST-recovered close, tagged `REST_BACKFILL`.
    - `on_gap(GapRecord)`: an expected close that no bar covers, with a reason code.
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

    async def start(self) -> None:
        """Connect, then subscribe every symbol-interval pair.

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
        try:
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
        """Unsubscribe every stream and close the connection."""
        await self._rollback()
        self._started = False

    def _make_kline_handler(self, symbol: str, interval: str) -> Callable[[WsKline], None]:
        def _on_kline(kline: WsKline) -> None:
            # Only closed klines advance the dispatch and last-close state. Forming updates
            # (x=False) are ignored by design.
            if not kline.is_closed:
                return
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
            self._on_closed_bar(
                TaggedBar(
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
            )

        return _on_kline

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
