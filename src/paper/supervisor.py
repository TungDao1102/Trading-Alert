"""Paper-loop WS supervisor (Phase 7, plan 07-02, task 2).

Per D-01 / D-05: the supervisor owns the WS lifecycle (subscribe,
keepalive, 24h rotation, reconnect trigger). On disconnect it
distinguishes:

  - Scheduled 24h rotation: proactive resubscribe + REST backfill
    from the last-seen close per pair. NO reconnect attempt (the WS
    is still connected, just rotating). NO outage-class gap journaled.

  - Unsolicited drop: tenacity-bounded reconnect (same attempt and
    delay ceilings as resync) + resubscribe + backfill. Per-symbol
    try-except isolation: one failing pair journals its gap while
    healthy pairs still dispatch.

The module imports only stdlib + tenacity + structlog + sibling
modules (per the plan's purity contract for this slice). The WS
surface stays behind `src/adapters/paper_ws.py`; the REST adapter
surface stays behind `src/adapters/binance_usdm.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
import tenacity

from src.adapters.binance_usdm import Kline as RestKline
from src.adapters.paper_ws import Kline as WsKline
from src.data.backfill import LIVE_5

from .resync import backfill_missed_closes

log = structlog.get_logger()


# --------------------------------------------------------------------------- #
# Bounded-retry ceilings — mirror resync.py so the supervisor and the
# resync module share the same fail-closed posture.
# --------------------------------------------------------------------------- #

SUPERVISOR_MAX_ATTEMPTS: int = 7
SUPERVISOR_MAX_DELAY_SECONDS: int = 120
SUPERVISOR_WAIT_MULTIPLIER_SECONDS: int = 1
SUPERVISOR_WAIT_MAX_SECONDS: int = 60


# --------------------------------------------------------------------------- #
# Adapter protocols — the minimum surface the supervisor needs.
# --------------------------------------------------------------------------- #


class WsAdapterLike(Protocol):
    """Anything that quacks like `PaperWsAdapter`."""

    def subscribe(
        self,
        *,
        symbol: str,
        interval: str,
        on_kline: Callable[[WsKline], None],
        stream_id: str | None = None,
    ) -> Any: ...

    def reconnect(self, handle: Any) -> None: ...

    def close(self, handle: Any) -> None: ...


class RestAdapterLike(Protocol):
    """Anything that quacks like `BinanceUsdmAdapter` for klines."""

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
    """Owns the WS lifecycle for the paper loop.

    Holds one WS adapter + one REST adapter + the Live-5 symbol list
    + 1H/4H interval subscriptions. `start()` subscribes all
    symbol-interval pairs and registers the loop's `on_closed_candle`
    dispatch. `on_disconnect(scheduled=...)` handles both the scheduled
    24h rotation and unsolicited drops. `stop()` closes the adapter
    cleanly.
    """

    def __init__(
        self,
        *,
        ws_adapter: WsAdapterLike,
        rest_adapter: RestAdapterLike,
        on_closed_candle: Callable[[WsKline], None],
        symbols: tuple[str, ...] = LIVE_5,
        intervals: tuple[str, ...] = ("1h", "4h"),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ws = ws_adapter
        self._rest = rest_adapter
        self._on_closed_candle = on_closed_candle
        self._symbols = symbols
        self._intervals = intervals
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))
        self._last_close: dict[tuple[str, str], datetime] = {}
        self._handles: list[tuple[str, str, Any]] = []

    def record_close(
        self, symbol: str, interval: str, close_time_utc: datetime
    ) -> None:
        """Record the last-seen close for a pair.

        Called by the dispatch path when a closed kline arrives. The
        supervisor uses this to know where to resume backfill after
        a rotation or disconnect.
        """
        self._last_close[(symbol, interval)] = close_time_utc

    def start(self) -> None:
        """Subscribe to all symbol-interval pairs + register dispatch."""
        for symbol in self._symbols:
            for interval in self._intervals:
                handle = self._ws.subscribe(
                    symbol=symbol.lower(),
                    interval=interval,
                    on_kline=self._make_kline_handler(symbol, interval),
                )
                self._handles.append((symbol, interval, handle))

    def _make_kline_handler(
        self, symbol: str, interval: str
    ) -> Callable[[WsKline], None]:
        def _on_kline(kline: WsKline) -> None:
            # Only closed klines advance the dispatch + last-close state.
            # Forming updates (x=False) are ignored by design — the
            # paper loop's double closed-candle gate rejects them before
            # they reach evaluate (loop.py).
            if kline.is_closed:
                self._last_close[(symbol, interval)] = kline.close_time_utc
                self._on_closed_candle(kline)

        return _on_kline

    async def on_disconnect(self, *, scheduled: bool = False) -> None:
        """Handle a disconnect event.

        `scheduled=True`: the 24h server-initiated rotation. Resubscribe
        all pairs and backfill from the last-seen close per pair. No
        reconnect attempt (the WS is still connected, just rotating).
        No outage-class gap journaled.

        `scheduled=False`: an unsolicited drop. Tenacity-bounded
        reconnect attempt, then resubscribe all pairs and backfill
        from the last-seen close per pair. Per-symbol try-except
        isolation: one failing pair journals its gap while healthy
        pairs still dispatch.
        """
        if not scheduled:
            await self._reconnect_with_retry()
        await self._resubscribe_and_backfill(journal_outage_gaps=not scheduled)

    def stop(self) -> None:
        """Close all WS handles and stop the supervisor."""
        self._close_all_handles()

    # ------------------------------------------------------------------ #
    # Internal: reconnect with bounded retry.
    # ------------------------------------------------------------------ #

    async def _reconnect_with_retry(self) -> None:
        """Tenacity-bounded reconnect attempt for every existing handle."""
        retry = tenacity.retry_if_exception(lambda _e: True)
        stop = tenacity.stop_after_attempt(
            SUPERVISOR_MAX_ATTEMPTS
        ) | tenacity.stop_after_delay(SUPERVISOR_MAX_DELAY_SECONDS)
        wait = tenacity.wait_random_exponential(
            multiplier=SUPERVISOR_WAIT_MULTIPLIER_SECONDS,
            max=SUPERVISOR_WAIT_MAX_SECONDS,
        )
        decorator = tenacity.AsyncRetrying(
            retry=retry, stop=stop, wait=wait, reraise=True
        )

        async def _reconnect() -> None:
            for _symbol, _interval, handle in list(self._handles):
                self._ws.reconnect(handle)

        async for attempt in decorator:
            with attempt:
                await _reconnect()

    # ------------------------------------------------------------------ #
    # Internal: resubscribe + backfill with per-symbol isolation.
    # ------------------------------------------------------------------ #

    async def _resubscribe_and_backfill(self, *, journal_outage_gaps: bool) -> None:
        """Close existing handles, resubscribe, and backfill each pair."""
        self._close_all_handles()
        self.start()

        now = self._clock()
        for symbol in self._symbols:
            for interval in self._intervals:
                last = self._last_close.get((symbol, interval))
                if last is None:
                    # No prior close recorded for this pair — nothing
                    # to backfill. Skip silently.
                    continue
                try:
                    closes, gaps = await backfill_missed_closes(
                        self._rest,
                        symbol=symbol,
                        interval=interval,
                        last_close_utc=last,
                        now_utc=now,
                    )
                except Exception as exc:
                    # Per-symbol isolation: one failing pair journals
                    # its gap and the remaining pairs still dispatch.
                    if journal_outage_gaps:
                        log.warning(
                            "paper.supervisor.backfill_failed",
                            symbol=symbol,
                            interval=interval,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    continue
                # Log any holes the exchange could not fill.
                for gap in gaps:
                    log.warning(
                        "paper.supervisor.gap",
                        symbol=gap["symbol"],
                        data_class=gap["data_class"],
                        expected_utc=gap["expected_utc"].isoformat(),
                        observed_utc=gap["observed_utc"].isoformat(),
                        reason=gap["reason"],
                    )
                # Backfilled closes are REST klines (not WS klines);
                # the paper loop's run_paper_tick consumes them via
                # its feed_events path, not the WS callback. The
                # supervisor's job is to surface them in the log so
                # the journal layer can persist them.
                if closes:
                    log.info(
                        "paper.supervisor.backfilled",
                        symbol=symbol,
                        interval=interval,
                        closes=len(closes),
                    )

    def _close_all_handles(self) -> None:
        """Close every WS handle we own."""
        for _symbol, _interval, handle in self._handles:
            try:
                self._ws.close(handle)
            except Exception:
                # A failed close is logged but does not propagate —
                # the supervisor must survive a wedged handle.
                log.warning(
                    "paper.supervisor.close_failed",
                    handle_id=id(handle),
                )
        self._handles.clear()


__all__ = [
    "PaperSupervisor",
    "RestAdapterLike",
    "SUPERVISOR_MAX_ATTEMPTS",
    "SUPERVISOR_MAX_DELAY_SECONDS",
    "SUPERVISOR_WAIT_MULTIPLIER_SECONDS",
    "SUPERVISOR_WAIT_MAX_SECONDS",
    "WsAdapterLike",
]
