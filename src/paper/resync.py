"""Paper-loop REST resync module (Phase 7, plan 07-02, task 1).

Per D-01 (flag-never-fabricate): the paper loop's resync module
REST-backfills missed closes after a disconnect or 24h rotation, and
journals any holes the exchange cannot fill as explicit gap records.
The module NEVER synthesizes a candle for a window the exchange did
not return — holes stay holes, and the journal layer persists them
without a parallel table (gap dicts reuse the `CollectorGap` field
shape: symbol, data_class, expected_utc, observed_utc, reason).

The module imports only stdlib + tenacity + structlog + sibling
modules (per the plan's purity contract for this slice). The WS
surface stays behind `src/adapters/paper_ws.py`; the REST adapter
surface stays behind `src/adapters/binance_usdm.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog
import tenacity

from src.adapters.binance_usdm import Kline
from src.data.backfill import interval_ms

log = structlog.get_logger()


# --------------------------------------------------------------------------- #
# Bounded-retry ceilings (FLAGGED ASSUMPTION, PAPER-01 unclassified).
# --------------------------------------------------------------------------- #
#
# The operator tunes these only before a soak epoch starts, never
# mid-epoch. The values are documented constants — not env vars — so a
# mid-soak change is a code change, not a config drift.
#
# - RESYNC_MAX_ATTEMPTS: cap on retry attempts before fail-closed.
# - RESYNC_MAX_DELAY_SECONDS: wall-clock cap on the retry window.
# - RESYNC_WAIT_MULTIPLIER_SECONDS: exponential-jitter base.
# - RESYNC_WAIT_MAX_SECONDS: exponential-jitter ceiling per sleep.

RESYNC_MAX_ATTEMPTS: int = 7
RESYNC_MAX_DELAY_SECONDS: int = 120
RESYNC_WAIT_MULTIPLIER_SECONDS: int = 1
RESYNC_WAIT_MAX_SECONDS: int = 60


# --------------------------------------------------------------------------- #
# Adapter protocol — the minimum surface resync needs.
# --------------------------------------------------------------------------- #


class AdapterLike(Protocol):
    """Anything that quacks like the project adapter for kline REST.

    The real `BinanceUsdmAdapter` satisfies this; tests inject a
    `FakeAdapter` that records its `start_ms` argument for audit.
    """

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]: ...


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _data_class_for(interval: str) -> str:
    """Map a canonical interval string to the paper-journal data_class.

    Per D-01: the journal layer persists gap rows on the existing
    `CollectorGap` table with a `data_class` discriminator. Paper
    streams use `paper-<interval>` so downstream consumers can
    distinguish paper gaps from OI/funding gaps.
    """
    return f"paper-{interval}"


def _expected_open_times(
    last_close_utc: datetime,
    now_utc: datetime,
    step_ms: int,
) -> list[datetime]:
    """Build the contiguous list of expected candle open_times.

    The first expected open_time is `last_close_utc` (the next candle
    starts when the previous one closes); the last is the largest
    `last_close_utc + k*step_ms` whose close_time `<= now_utc`.
    Returns an empty list when `last_close_utc + step_ms > now_utc`
    (no missed closes to backfill).

    The diff uses open_time (not close_time) so each expected slot maps
    to exactly one exchange row; the caller diffs against CLOSED rows
    only, so a slot whose row is still forming is reported as a
    forming_at_observed_time gap, never as silent coverage.
    """
    step = timedelta(milliseconds=step_ms)
    out: list[datetime] = []
    t = last_close_utc
    while t + step <= now_utc:
        out.append(t)
        t += step
    return out


# --------------------------------------------------------------------------- #
# Public entry point — backfill_missed_closes.
# --------------------------------------------------------------------------- #


async def backfill_missed_closes(
    adapter: AdapterLike,
    *,
    symbol: str,
    interval: str,
    last_close_utc: datetime,
    now_utc: datetime,
) -> tuple[list[Kline], list[dict[str, Any]]]:
    """Backfill missed closes via REST klines, journaling holes as gaps.

    Per D-01: the function pages `adapter.klines` from
    `ms(last_close_utc)` with `limit=1500` under a tenacity-bounded
    retry, drops any candle whose `close_time_utc > now_utc` (forming
    candle), diffs the returned closes against the contiguous
    expectation to find holes, and returns the available closes in
    `close_time_utc` order plus one gap dict per hole.

    The gap dicts reuse the `CollectorGap` field shape (symbol,
    data_class, expected_utc, observed_utc, reason) so the journal
    layer persists them without a parallel table.

    Returns `(closes, gaps)`:
      - `closes`: list of `Kline` instances in `close_time_utc` order
      - `gaps`: list of gap dicts, one per hole the exchange did not fill
    """
    # Normalize to UTC for arithmetic (callers may pass any tz-aware
    # datetime; the adapter's ms math is UTC-anchored).
    if last_close_utc.tzinfo is None:
        raise ValueError("last_close_utc must be UTC-aware")
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be UTC-aware")
    last_close_utc = last_close_utc.astimezone(UTC)
    now_utc = now_utc.astimezone(UTC)

    step_ms = interval_ms(interval)
    start_ms = int(last_close_utc.timestamp() * 1000)
    now_ms = int(now_utc.timestamp() * 1000)

    # Bounded retry: cap attempts AND wall-clock, then fail closed.
    # Retry transient faults only — programming errors (ValueError,
    # KeyError, TypeError) fail immediately instead of burning the
    # 120 s budget and masking deterministic faults as transient
    # (WR-02; mirrors src/data/backfill.py fetch_page_with_retry).
    def _is_transient(exc: BaseException) -> bool:
        return not isinstance(exc, (ValueError, KeyError, TypeError))

    retry = tenacity.retry_if_exception(_is_transient)
    stop = tenacity.stop_after_attempt(RESYNC_MAX_ATTEMPTS) | tenacity.stop_after_delay(
        RESYNC_MAX_DELAY_SECONDS
    )
    wait = tenacity.wait_random_exponential(
        multiplier=RESYNC_WAIT_MULTIPLIER_SECONDS,
        max=RESYNC_WAIT_MAX_SECONDS,
    )
    decorator = tenacity.AsyncRetrying(retry=retry, stop=stop, wait=wait, reraise=True)

    async def _fetch_page(cursor_ms: int) -> list[Kline]:
        return await adapter.klines(
            symbol=symbol,
            interval=interval,
            start_ms=cursor_ms,
            limit=1500,
        )

    async def _fetch_page_with_retry(cursor_ms: int) -> list[Kline]:
        async for attempt in decorator:
            with attempt:
                return await _fetch_page(cursor_ms)
        raise RuntimeError("unreachable: tenacity.AsyncRetrying exhausted without reraise")

    # Page until the returned page no longer advances toward now_utc
    # (CR-01): a single 1500-row page silently truncates any outage
    # longer than 1500 intervals. Each full page advances the cursor
    # past the last returned open_time; a short page (or an empty
    # page, or a cursor past now) ends the walk. A page-count cap
    # keeps a misbehaving adapter from spinning forever — hitting it
    # is journaled as a truncated backfill, never silent coverage.
    raw_page: list[Kline] = []
    cursor_ms = start_ms
    truncated = False
    for _ in range(200):
        page = await _fetch_page_with_retry(cursor_ms)
        if not page:
            break
        raw_page.extend(page)
        if len(page) < 1500:
            break
        last_open_ms = int(page[-1].open_time_utc.timestamp() * 1000)
        cursor_ms = last_open_ms + step_ms
        if cursor_ms > now_ms:
            break
    else:
        truncated = True
        log.warning(
            "paper.resync.truncated",
            symbol=symbol,
            interval=interval,
            pages=200,
            closes=len(raw_page),
        )

    # Drop forming candles: anything whose close_time is in the future
    # relative to now_utc (Pitfall 1 — no future-bar leakage / repaint).
    closed: list[Kline] = [k for k in raw_page if k.close_time_utc <= now_utc]

    # Sort by close_time_utc for deterministic downstream consumption.
    closed.sort(key=lambda k: k.close_time_utc)

    # Build the contiguous expectation and diff against CLOSED rows
    # only (CR-09): a slot whose only exchange row is still forming
    # contributes no close, so diffing against raw_page would mark it
    # "covered" while downstream sees a missing bar. Slots present in
    # the raw page but absent from closed get an explicit
    # forming_at_observed_time gap (retryable) rather than silence.
    expected_open_times = _expected_open_times(last_close_utc, now_utc, step_ms)
    closed_open_times = {k.open_time_utc for k in closed}
    raw_open_times = {k.open_time_utc for k in raw_page}
    gaps: list[dict[str, Any]] = []
    for expected_open in expected_open_times:
        if expected_open not in closed_open_times:
            expected_close = expected_open + timedelta(milliseconds=step_ms)
            if expected_open in raw_open_times:
                reason = "forming_at_observed_time"
            else:
                reason = "exchange_returned_no_candle_for_expected_close"
            gaps.append(
                {
                    "symbol": symbol,
                    "data_class": _data_class_for(interval),
                    "expected_utc": expected_close,
                    "observed_utc": now_utc,
                    "reason": reason,
                }
            )

    log.info(
        "paper.resync.complete",
        symbol=symbol,
        interval=interval,
        last_close_utc=last_close_utc.isoformat(),
        now_utc=now_utc.isoformat(),
        closes=len(closed),
        gaps=len(gaps),
    )

    return closed, gaps


__all__ = [
    "AdapterLike",
    "RESYNC_MAX_ATTEMPTS",
    "RESYNC_MAX_DELAY_SECONDS",
    "RESYNC_WAIT_MULTIPLIER_SECONDS",
    "RESYNC_WAIT_MAX_SECONDS",
    "backfill_missed_closes",
]
