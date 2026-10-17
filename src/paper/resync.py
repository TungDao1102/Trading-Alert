"""Paper-loop REST resync module (Phase 7 plan 07-02, corrected in Phase 16 plan 16-08).

Per D-01 (flag-never-fabricate): the resync module REST-backfills missed closes after a
disconnect or SDK rotation, and reports any hole the exchange cannot fill as an explicit
`GapRecord` with a reason code. The module NEVER synthesizes a candle for a window the
exchange did not return: holes stay holes, and the runtime journals the records.

Phase 16 (research Pitfall P1): real Binance bars close at open + interval - 1 ms, so the
expected slots are anchored on open times of the exchange grid, not on `last_close_utc`
itself. Returned bars are `TaggedBar` values tagged `SourceTag.REST_BACKFILL`; a REST bar
can never be evaluated as a live signal (L-11).

The module is the owner of REST backfill: the public-data `Kline` type comes from
`src/adapters/binance_public.py`, interval arithmetic from the shared vocabulary, and the
WS surface stays behind `src/adapters/paper_ws.py`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol

import structlog
import tenacity

from src.adapters.binance_public import Kline

from .vocabulary import INTERVAL_MS, GapReason, GapRecord, SourceTag, TaggedBar

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

# REST backfill page size and page cap (16-DEC-O-07, "ratify current"; unchanged values). The
# page size is the exchange maximum rows of `GET /fapi/v1/klines` (docs/SOURCES.md rows of
# 2026-09-30 and 2026-10-08, MEDIUM): it stays the largest single request. The page cap bounds
# the walk against a misbehaving adapter. How many closes one backfill requests in total is the
# ratified `timing.rest_backfill_depth_bars` (plan 16-62, B1-WR-09), handed in by the caller.
REST_BACKFILL_PAGE_SIZE: int = 1500
REST_BACKFILL_PAGE_CAP: int = 200


# --------------------------------------------------------------------------- #
# Adapter protocol — the minimum surface resync needs.
# --------------------------------------------------------------------------- #


class AdapterLike(Protocol):
    """Anything that quacks like the project adapter for kline REST.

    The real `BinancePublicMarketData` satisfies this; tests inject a
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

_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)


def _datetime_to_ms(value: datetime) -> int:
    """Convert a tz-aware datetime to integer millisecond epoch (WR-01).

    Uses exact integer timedelta arithmetic — never `timestamp() * 1000`,
    whose binary-float round-trip loses sub-millisecond precision on
    large epoch values and escapes the no-float AST guard.
    """
    delta = value.astimezone(UTC) - _EPOCH_UTC
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _ms_to_utc(ms: int) -> datetime:
    """Convert integer epoch milliseconds to a UTC datetime (exact, no float)."""
    return _EPOCH_UTC + timedelta(milliseconds=ms)


def _step_ms(interval: str) -> int:
    """Interval length in milliseconds; an unknown interval fails loudly."""
    try:
        return INTERVAL_MS[interval]
    except KeyError:
        raise ValueError(f"unknown interval {interval!r}") from None


def _expected_open_times(
    last_close_utc: datetime,
    now_utc: datetime,
    step_ms: int,
) -> list[datetime]:
    """Build the contiguous list of expected candle open times on the exchange grid.

    Exchange bars close at open + interval - 1 ms (research Pitfall P1), so the first
    expected open is the first grid point at or after `last_close_utc + 1 ms`, which is
    `last_open + interval` when `last_close_utc` is a real close. Anchoring on the grid (not
    on `last_close_utc` itself) is what keeps real bars from being reported as phantom gaps.
    The last expected open is the largest grid point whose close (open + interval - 1 ms) is
    `<= now_utc`. Returns an empty list when no close is due yet.

    The diff uses open time (not close time) so each expected slot maps to exactly one
    exchange row; the caller diffs against CLOSED rows only, so a slot whose row is not closed
    yet is reported as a gap, never as silent coverage.
    """
    next_open_ms = -(-(_datetime_to_ms(last_close_utc) + 1) // step_ms) * step_ms
    now_ms = _datetime_to_ms(now_utc)
    out: list[datetime] = []
    while next_open_ms + step_ms - 1 <= now_ms:
        out.append(_ms_to_utc(next_open_ms))
        next_open_ms += step_ms
    return out


def expected_close_times(
    last_close_utc: datetime, now_utc: datetime, interval: str
) -> list[datetime]:
    """The closes due after `last_close_utc` up to and including `now_utc`.

    Used by the supervisor to name every close it could not recover when a whole backfill
    fails (each becomes a `GapRecord`).
    """
    if last_close_utc.tzinfo is None:
        raise ValueError("last_close_utc must be UTC-aware")
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be UTC-aware")
    step_ms = _step_ms(interval)
    return [
        open_utc + timedelta(milliseconds=step_ms - 1)
        for open_utc in _expected_open_times(
            last_close_utc.astimezone(UTC), now_utc.astimezone(UTC), step_ms
        )
    ]


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
    depth_bars: int,
    beyond_depth_reason: GapReason,
) -> tuple[list[TaggedBar], list[GapRecord]]:
    """Backfill missed closes via REST klines, reporting holes as gap records.

    Per D-01: the function pages `adapter.klines` from `ms(last_close_utc)` under a
    tenacity-bounded retry, drops any candle whose `close_time_utc > now_utc` (forming
    candle), diffs the returned closes against the contiguous expectation on the exchange
    grid to find holes, and returns the available closes in `close_time_utc` order plus one
    `GapRecord` per hole.

    The request is bounded by `depth_bars` (the ratified `timing.rest_backfill_depth_bars`,
    plan 16-62, B1-WR-09), newest closes first: at most `depth_bars` closes are requested, each
    request asks for `min(REST_BACKFILL_PAGE_SIZE, remaining depth)` rows, and the walk is
    further bounded by `REST_BACKFILL_PAGE_CAP` pages. When more closes are missing than the
    depth, the walk starts at the oldest of the newest `depth_bars` expected closes and every
    older expected close becomes a `GapRecord` with `beyond_depth_reason` (the reason of the
    window being verified); it is never labelled `EXCHANGE_NO_CANDLE` and never dropped, and
    no bar is fabricated for it. One log line names the count of such closes.

    Returns `(closes, gaps)`:
      - `closes`: `TaggedBar` values tagged `SourceTag.REST_BACKFILL`, carrying the interval
        of the request, in `close_time_utc` order
      - `gaps`: one `GapRecord` per expected close the exchange did not fill
        (`GapReason.EXCHANGE_NO_CANDLE`), per close beyond the depth
        (`beyond_depth_reason`); a due slot whose only row is not closed yet is
        reported as `GapReason.UNKNOWN` (CR-09: never silent coverage)
    """
    if depth_bars < 1:
        raise ValueError(f"depth_bars must be at least 1, got {depth_bars}")
    # Normalize to UTC for arithmetic (callers may pass any tz-aware
    # datetime; the adapter's ms math is UTC-anchored).
    if last_close_utc.tzinfo is None:
        raise ValueError("last_close_utc must be UTC-aware")
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be UTC-aware")
    last_close_utc = last_close_utc.astimezone(UTC)
    now_utc = now_utc.astimezone(UTC)

    step_ms = _step_ms(interval)
    now_ms = _datetime_to_ms(now_utc)

    # The newest `depth_bars` expected closes are requested; every older one is a gap (B1-WR-09).
    expected_open_times = _expected_open_times(last_close_utc, now_utc, step_ms)
    beyond_count = max(0, len(expected_open_times) - depth_bars)
    beyond_open_times = expected_open_times[:beyond_count]
    if beyond_count:
        start_ms = _datetime_to_ms(expected_open_times[beyond_count])
        log.warning(
            "paper.resync.beyond_depth",
            symbol=symbol,
            interval=interval,
            closes=beyond_count,
            depth_bars=depth_bars,
        )
    else:
        start_ms = _datetime_to_ms(last_close_utc)

    # Bounded retry: cap attempts AND wall-clock, then fail closed.
    # Retry transient faults only — programming errors (ValueError,
    # KeyError, TypeError) fail immediately instead of burning the
    # 120 s budget and masking deterministic faults as transient
    # (WR-02).
    def _is_transient(exc: BaseException) -> bool:
        # Cancellation is never transient: tenacity records any BaseException as a failed
        # attempt, so without this a cancelled backfill (supervisor stop) would be retried.
        return not isinstance(exc, (ValueError, KeyError, TypeError, asyncio.CancelledError))

    retry = tenacity.retry_if_exception(_is_transient)
    stop = tenacity.stop_after_attempt(RESYNC_MAX_ATTEMPTS) | tenacity.stop_after_delay(
        RESYNC_MAX_DELAY_SECONDS
    )
    wait = tenacity.wait_random_exponential(
        multiplier=RESYNC_WAIT_MULTIPLIER_SECONDS,
        max=RESYNC_WAIT_MAX_SECONDS,
    )
    decorator = tenacity.AsyncRetrying(retry=retry, stop=stop, wait=wait, reraise=True)

    async def _fetch_page(cursor_ms: int, limit: int) -> list[Kline]:
        return await adapter.klines(
            symbol=symbol,
            interval=interval,
            start_ms=cursor_ms,
            limit=limit,
        )

    async def _fetch_page_with_retry(cursor_ms: int, limit: int) -> list[Kline]:
        async for attempt in decorator:
            with attempt:
                return await _fetch_page(cursor_ms, limit)
        raise RuntimeError("unreachable: tenacity.AsyncRetrying exhausted without reraise")

    # Page until the returned page no longer advances toward now_utc
    # (CR-01): a single page silently truncates any outage longer than one page. Each full
    # page advances the cursor past the last returned open_time; a short page (or an empty
    # page, a cursor past now, or an exhausted depth) ends the walk. Every request asks for
    # min(page size, remaining depth) rows (B1-WR-09). A page-count cap keeps a misbehaving
    # adapter from spinning forever — hitting it is journaled as a truncated backfill,
    # never silent coverage.
    raw_page: list[Kline] = []
    cursor_ms = start_ms
    remaining = depth_bars
    for _ in range(REST_BACKFILL_PAGE_CAP):
        limit = min(REST_BACKFILL_PAGE_SIZE, remaining)
        page = await _fetch_page_with_retry(cursor_ms, limit)
        if not page:
            break
        raw_page.extend(page)
        remaining -= len(page)
        if len(page) < limit or remaining <= 0:
            break
        last_open_ms = _datetime_to_ms(page[-1].open_time_utc)
        cursor_ms = last_open_ms + step_ms
        if cursor_ms > now_ms:
            break
    else:
        log.warning(
            "paper.resync.truncated",
            symbol=symbol,
            interval=interval,
            pages=REST_BACKFILL_PAGE_CAP,
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
    # "covered" while downstream sees a missing bar. A slot present in
    # the raw page but absent from closed gets its own reason (UNKNOWN)
    # rather than silence.
    closed_open_times = {k.open_time_utc for k in closed}
    raw_open_times = {k.open_time_utc for k in raw_page}
    gaps: list[GapRecord] = [
        GapRecord(
            symbol=symbol,
            interval=interval,
            expected_close_utc=expected_open + timedelta(milliseconds=step_ms - 1),
            reason=beyond_depth_reason,
            detected_at_utc=now_utc,
        )
        for expected_open in beyond_open_times
    ]
    for expected_open in expected_open_times[beyond_count:]:
        if expected_open in closed_open_times:
            continue
        if expected_open in raw_open_times:
            reason = GapReason.UNKNOWN
            log.warning(
                "paper.resync.slot_not_closed",
                symbol=symbol,
                interval=interval,
                open_time=expected_open.isoformat(),
            )
        else:
            reason = GapReason.EXCHANGE_NO_CANDLE
        gaps.append(
            GapRecord(
                symbol=symbol,
                interval=interval,
                expected_close_utc=expected_open + timedelta(milliseconds=step_ms - 1),
                reason=reason,
                detected_at_utc=now_utc,
            )
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

    bars = [
        TaggedBar(
            symbol=symbol,
            interval=interval,
            open_time_utc=k.open_time_utc,
            close_time_utc=k.close_time_utc,
            open=k.open,
            high=k.high,
            low=k.low,
            close=k.close,
            volume=k.volume,
            source=SourceTag.REST_BACKFILL,
        )
        for k in closed
    ]
    return bars, gaps


__all__ = [
    "REST_BACKFILL_PAGE_CAP",
    "REST_BACKFILL_PAGE_SIZE",
    "RESYNC_MAX_ATTEMPTS",
    "RESYNC_MAX_DELAY_SECONDS",
    "RESYNC_WAIT_MAX_SECONDS",
    "RESYNC_WAIT_MULTIPLIER_SECONDS",
    "AdapterLike",
    "backfill_missed_closes",
    "expected_close_times",
]
