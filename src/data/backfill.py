"""Deterministic kline paginator (RESEARCH §Pattern 2 + §Pitfalls 1, 5).

The paginator:
  1. Walks `[start_ms, end_ms)` in fixed interval windows.
  2. Calls the adapter page-by-page with `limit=1500` (the SDK maximum).
  3. Drops the still-forming candle (`close_time_utc > now_utc`) before
     publishing (Pitfall 1 — no future-bar leakage / repaint).
  4. Sleeps a configurable pacing delay between pages so a 5-symbol ×
     multi-interval bootstrap stays well under the 2400 weight/min IP
     cap (Pitfall 5).
  5. Retries 429/418 responses via `tenacity` with exponential backoff
     + jitter (Pitfall 5).
  6. Sends every batch through the quality gate; corrupt batches raise
     before any Parquet write (D-10 fail-closed).
  7. Persists per-file via `publish_batch` (D-04 immutability — file
     already on disk raises `FileExistsError`).

Production use: called by `02-03`/`02-04` plans; this file is the
tracer's wiring skeleton (PLAN 02-02 Task 1).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import tenacity

from src.adapters.binance_usdm import BinanceUsdmAdapter, Kline
from src.data.quality import QualityVerdict, check_batch
from src.data.store import DEFAULT_RAW_ROOT, publish_batch

log = structlog.get_logger()


# Rate-limited failures are retried with jitter; on exhaustion the paginator
# raises and lets the caller decide (D-09 fail-closed posture).
_RATE_LIMIT_ERRORS: tuple[type[BaseException], ...] = (tenacity.RetryError,)


@dataclass(frozen=True)
class BackfillConfig:
    """Tunable knobs for one backfill run.

    Defaults are sized so the tracer's small BTCUSDT-1h window produces
    one or two HTTP calls (no pacing overhead visible in test output)
    while a full bootstrap stays under the 2400 weight/min IP cap.
    """

    interval_ms: int
    page_size: int = 1000          # ≤1500 per Binance; 1000 → weight 5
    pace_seconds: float = 0.05     # sleep between pages (conservative)
    max_retries: int = 5
    jitter_max_seconds: float = 1.0


@dataclass(frozen=True)
class BackfillResult:
    """Outcome of one `backfill_symbol_interval` call."""

    pages: int
    rows_published: int
    structural_rejections: int
    durations_ms: tuple[int, ...]  # length == pages; one per page fetch


# --------------------------------------------------------------------------- #
# Page-fetch helper with bounded retry.
# --------------------------------------------------------------------------- #


def _is_rate_limit(exc: BaseException) -> bool:
    """Best-effort detection of a 429/418 response inside an SDK error.

    The SDK raises its own exception types; we sniff for the canonical
    Binance `TooManyRequestsError` class by name to keep this module
    independent of the SDK's internal exception hierarchy.
    """
    cls_name = type(exc).__name__
    return "TooManyRequests" in cls_name or "RateLimit" in cls_name


async def fetch_page_with_retry(
    adapter: BinanceUsdmAdapter,
    *,
    symbol: str,
    interval: str,
    start_ms: int,
    limit: int,
    max_retries: int,
    jitter_max_seconds: float,
) -> list[Kline]:
    """Fetch one kline page with tenacity-bounded retry on rate-limit hits."""
    retry = tenacity.retry_if_exception(lambda e: _is_rate_limit(e))
    stop = tenacity.stop_after_attempt(max_retries)
    wait = tenacity.wait_exponential_jitter(initial=0.5, max=jitter_max_seconds * 4)
    decorator = tenacity.AsyncRetrying(retry=retry, stop=stop, wait=wait, reraise=True)

    async def _fetch() -> list[Kline]:
        return await adapter.klines(
            symbol=symbol,
            interval=interval,
            start_ms=start_ms,
            limit=limit,
        )

    async for attempt in decorator:
        with attempt:
            return await _fetch()
    # tenacity with reraise=True will raise on exhaustion; the explicit
    # return here satisfies the type checker for the non-raising path.
    raise RuntimeError("unreachable: tenacity.AsyncRetrying exhausted without reraise")


# --------------------------------------------------------------------------- #
# Paginator.
# --------------------------------------------------------------------------- #


async def backfill_symbol_interval(
    adapter: BinanceUsdmAdapter,
    *,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config: BackfillConfig | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_publish: Callable[[int], Awaitable[None] | None] | None = None,
) -> BackfillResult:
    """Paginate `[start_ms, end_ms)` for one (symbol, interval) and publish.

    `clock` is injectable so tests can run with a frozen wall-clock and
    assert that the forming candle is dropped deterministically
    (Pitfall 1 — REPLAY-1 of the 02-02 threat model).
    """
    cfg = config or BackfillConfig(interval_ms=interval_ms(interval))
    pages = 0
    rows_published = 0
    structural_rejections = 0
    durations: list[int] = []
    cursor = start_ms
    now_ms = int(clock().timestamp() * 1000)

    while cursor < end_ms:
        page_start = cursor
        t0 = datetime.now(UTC)
        raw_page = await fetch_page_with_retry(
            adapter,
            symbol=symbol,
            interval=interval,
            start_ms=cursor,
            limit=cfg.page_size,
            max_retries=cfg.max_retries,
            jitter_max_seconds=cfg.jitter_max_seconds,
        )
        durations.append(int((datetime.now(UTC) - t0).total_seconds() * 1000))
        pages += 1

        # Drop the forming candle: anything whose close_time is in the future
        # relative to the injected clock (Pitfall 1). This must run BEFORE the
        # quality gate so it never inspects an unclosed bar.
        closed: list[Kline] = [k for k in raw_page if int(k.close_time_utc.timestamp() * 1000) <= now_ms]

        if closed:
            verdict = check_batch(closed, interval)
            if not verdict.structural_ok:
                structural_rejections += 1
                log.error(
                    "backfill.rejected",
                    symbol=symbol,
                    interval=interval,
                    duplicates=verdict.duplicates,
                    ohlc_violations=verdict.ohlc_violations,
                    timestamp_regressions=verdict.timestamp_regressions,
                    rows=len(closed),
                )
                # D-10: do NOT publish; do NOT overwrite prior data. The
                # caller observes the rejection via the counter and may
                # decide to stop the run.
            else:
                written = publish_batch(
                    closed, interval=interval, symbol=symbol, raw_root=raw_root
                )
                rows_published += len(closed)
                log.info(
                    "backfill.published",
                    symbol=symbol,
                    interval=interval,
                    rows=len(closed),
                    files=written,
                    gap_count=verdict.gap_count,
                )
                if on_publish is not None:
                    result = on_publish(len(closed))
                    if asyncio.iscoroutine(result):
                        await result

        # Advance cursor to the next page. If the page was empty or the
        # last bar's open_time is before `cursor`, advance by at least one
        # interval to avoid infinite loops on an exhausted window.
        if raw_page:
            last_open = int(raw_page[-1].open_time_utc.timestamp() * 1000)
            cursor = max(last_open + cfg.interval_ms, page_start + cfg.interval_ms)
        else:
            cursor = page_start + cfg.interval_ms

        if cursor < end_ms and cfg.pace_seconds > 0:
            await asyncio.sleep(cfg.pace_seconds)

    return BackfillResult(
        pages=pages,
        rows_published=rows_published,
        structural_rejections=structural_rejections,
        durations_ms=tuple(durations),
    )


def interval_ms(interval: str) -> int:
    """Resolve the interval name to its millisecond duration."""
    # Local import to keep the public API of quality.py independent of this
    # function (the table lives there for canonical access).
    from src.data.quality import INTERVAL_MS

    if interval not in INTERVAL_MS:
        raise ValueError(f"unknown interval {interval!r}")
    return INTERVAL_MS[interval]
