"""Paper-loop WS supervisor (Phase 7, plan 07-02, task 2).

Per D-01 / D-05: the supervisor owns the WS lifecycle (subscribe,
keepalive, 24h rotation, reconnect trigger). On disconnect it
distinguishes:

  - Scheduled 24h rotation: close the old handles, REST backfill from
    the last-seen close per pair, record the backfilled closes, and only
    then resubscribe (D-16, F-413). NO reconnect attempt (the WS is
    still connected, just rotating). NO outage-class gap journaled.

  - Unsolicited drop: tenacity-bounded reconnect (same attempt and
    delay ceilings as resync), then the same close -> backfill ->
    record -> resubscribe sequence. Per-symbol try-except isolation:
    one failing pair journals its gap while healthy pairs still
    dispatch.

The last-close state per (symbol, interval) only moves forward
(`_advance_last_close`), so a bar is never delivered twice across the
reconnect seam (D-28).

The module owns the WS lifecycle behind `src/adapters/paper_ws.py`
and the REST backfill surface behind `src/adapters/binance_usdm.py`
(SDK response types enter only as `Kline` values; the supervisor
never imports the SDK directly).
"""

from __future__ import annotations

import threading
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
        # Guards the check-and-set in _advance_last_close: WS callbacks run
        # on the adapter thread while the backfill runs on the event loop.
        self._last_close_lock = threading.Lock()
        self._handles: list[tuple[str, str, Any]] = []
        self._close_failures: int = 0

    def record_close(
        self, symbol: str, interval: str, close_time_utc: datetime
    ) -> None:
        """Record the last-seen close for a pair.

        Called by the dispatch path when a closed kline arrives. The
        supervisor uses this to know where to resume backfill after
        a rotation or disconnect. Monotonic (D-28): an earlier or equal
        close never moves the stored value backwards.
        """
        self._advance_last_close(symbol, interval, close_time_utc)

    def _advance_last_close(
        self, symbol: str, interval: str, close_time_utc: datetime
    ) -> bool:
        """Atomically move the pair's last close forward.

        Returns True only when there is no stored close or the new close
        is strictly later (the bar is new); False when the close is at or
        before the stored one (a duplicate or stale bar). The check and
        the store happen under one lock so concurrent callers cannot both
        claim the same bar (T-13-10).
        """
        key = (symbol, interval)
        with self._last_close_lock:
            stored = self._last_close.get(key)
            if stored is not None and close_time_utc <= stored:
                return False
            self._last_close[key] = close_time_utc
            return True

    def start(self) -> None:
        """Subscribe to all symbol-interval pairs + register dispatch.

        Idempotent guard (WR-08): a second start() without stop()
        would double-subscribe every pair (two callbacks per close).
        Restart flows go through _resubscribe_and_backfill (which
        closes first); an explicit double-start raises loudly.
        """
        if self._handles:
            raise RuntimeError(
                "PaperSupervisor.start() called twice without stop(); "
                "restart via _resubscribe_and_backfill only"
            )
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
            if not kline.is_closed:
                return
            # Monotonic guard (D-28): a closed kline at or before the
            # pair's last close was already delivered (via backfill or an
            # earlier WS message) and is dropped, never dispatched twice.
            if not self._advance_last_close(symbol, interval, kline.close_time_utc):
                log.warning(
                    "paper.supervisor.duplicate_close_dropped",
                    symbol=symbol,
                    interval=interval,
                    close_time=kline.close_time_utc.isoformat(),
                )
                return
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
            try:
                await self._reconnect_with_retry()
            except Exception as exc:
                # Reconnect exhaustion must not skip backfill (CR-02):
                # the unrecoverable-WS case is exactly when REST
                # backfill matters most. Record and fall through.
                log.error(
                    "paper.supervisor.reconnect_exhausted",
                    error=f"{type(exc).__name__}: {exc}",
                )
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

    async def _resubscribe_and_backfill(
        self, *, journal_outage_gaps: bool
    ) -> tuple[dict[tuple[str, str], list[RestKline]], list[dict[str, Any]]]:
        """Close handles, backfill missed closes, then resubscribe.

        Order (D-16, F-413): close the old handles, REST-backfill every
        pair from its last close and record those closes (advancing the
        last-close state), and only then re-attach the WS stream. A
        second verification backfill after the resubscribe picks up any
        bar that closed in the seam between the first backfill's `now`
        and the WS attach (D-28). The last-close state is monotonic, so
        a bar reaching both the backfill and the WS stream is delivered
        once, never twice.

        Returns the backfilled closes per (symbol, interval) pair
        (CR-03: log-only backfill dropped closes on the floor — the
        caller feeds these into the loop's feed_events path), plus
        the outage gaps for pairs whose backfill raised (WR-09: the
        failing pair journals its gap instead of leaving an invisible
        hole). Pairs with no prior close contribute no entry.
        """
        self._close_all_handles()
        backfilled, outage_gaps = await self._backfill_pairs(
            self._clock(),
            reason_prefix="backfill_exception",
            journal_outage_gaps=journal_outage_gaps,
        )
        self.start()

        # Verification pass (D-28): a bar can close in the seam between
        # the first backfill's `now` and the WS attach. Backfill again
        # from the updated last close; only closes that advance the
        # last-close state are kept, so no bar appears twice and none is
        # skipped. Failures here add an outage gap and never discard the
        # first-pass closes.
        verified, verify_gaps = await self._backfill_pairs(
            self._clock(),
            reason_prefix="verify_backfill_exception",
            journal_outage_gaps=journal_outage_gaps,
            log_missing_last_close=False,
            skip_pairs=frozenset(
                (str(g["symbol"]), str(g["data_class"]).removeprefix("paper-"))
                for g in outage_gaps
            ),
        )
        for pair, extra in verified.items():
            backfilled.setdefault(pair, []).extend(extra)
            log.info(
                "paper.supervisor.verify_backfilled",
                symbol=pair[0],
                interval=pair[1],
                closes=len(extra),
            )
        outage_gaps.extend(verify_gaps)
        return backfilled, outage_gaps

    async def _backfill_pairs(
        self,
        now: datetime,
        *,
        reason_prefix: str,
        journal_outage_gaps: bool,
        log_missing_last_close: bool = True,
        skip_pairs: frozenset[tuple[str, str]] = frozenset(),
    ) -> tuple[dict[tuple[str, str], list[RestKline]], list[dict[str, Any]]]:
        """Backfill every pair from its last close, keeping only new closes.

        A close is kept only when `_advance_last_close` accepts it, in
        close_time order, so the returned closes are strictly newer than
        anything already delivered and the last-close state ends at the
        latest kept bar (D-28). Per-pair try/except isolation: a raising
        pair contributes one outage gap (`{reason_prefix}:{ExcType}`) and
        the remaining pairs still run.
        """
        backfilled: dict[tuple[str, str], list[RestKline]] = {}
        outage_gaps: list[dict[str, Any]] = []
        for symbol in self._symbols:
            for interval in self._intervals:
                if (symbol, interval) in skip_pairs:
                    # The first pass already journaled this pair's outage
                    # gap; re-running would double-count the same hole.
                    continue
                last = self._last_close.get((symbol, interval))
                if last is None:
                    # No prior close recorded for this pair — nothing
                    # to backfill. Loud (not silent): a missing last
                    # means the dispatch path never recorded a close
                    # for this pair. (The verification pass skips the
                    # log: the first pass already reported it.)
                    if log_missing_last_close:
                        log.error(
                            "paper.supervisor.no_last_close",
                            symbol=symbol,
                            interval=interval,
                        )
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
                    # Build the gap dict in the CollectorGap shape so
                    # the hole is visible to the journal (WR-09), not
                    # just a log line.
                    outage_gap = {
                        "symbol": symbol,
                        "data_class": f"paper-{interval}",
                        "expected_utc": last,
                        "observed_utc": now,
                        "reason": f"{reason_prefix}:{type(exc).__name__}",
                    }
                    outage_gaps.append(outage_gap)
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
                # its feed_events path, not the WS callback. Keep only
                # closes that advance the last-close state (monotonic,
                # D-28) and return them per pair so the caller can
                # persist and dispatch them (CR-03).
                kept = [
                    k
                    for k in sorted(closes, key=lambda c: c.close_time_utc)
                    if self._advance_last_close(symbol, interval, k.close_time_utc)
                ]
                if kept:
                    log.info(
                        "paper.supervisor.backfilled",
                        symbol=symbol,
                        interval=interval,
                        closes=len(kept),
                    )
                    backfilled[(symbol, interval)] = kept
        return backfilled, outage_gaps

    def _close_all_handles(self) -> None:
        """Close every WS handle we own."""
        for symbol, interval, handle in self._handles:
            try:
                self._ws.close(handle)
            except Exception:
                # A failed close is logged but does not propagate —
                # the supervisor must survive a wedged handle. The
                # symbol/interval pair plus a consecutive-failure
                # count make repeated rotation failures
                # distinguishable from one-offs (WR-08).
                self._close_failures += 1
                log.warning(
                    "paper.supervisor.close_failed",
                    symbol=symbol,
                    interval=interval,
                    handle_id=id(handle),
                    consecutive_close_failures=self._close_failures,
                )
                continue
        self._close_failures = 0
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
