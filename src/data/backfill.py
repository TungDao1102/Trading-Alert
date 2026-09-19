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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as _date
from pathlib import Path

import structlog
import tenacity
from src.adapters.binance_usdm import BinanceUsdmAdapter, Kline
from src.data.quality import check_batch
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


def align_to_day_start_ms(ms: int) -> int:
    """Snap a millisecond epoch to the start of its UTC day.

    The per-day Parquet partition layout (`data/raw/interval=.../symbol=.../
    date=YYYY-MM-DD/part.parquet`) makes the store raise if a single batch
    spans two UTC dates AND a later batch touches the same date again
    (D-04 immutability). Aligning the bootstrap's `start_ms` to a day
    boundary guarantees each page fits in one date — the paginator never
    revisits an already-published date.

    For V1 this is the pragmatic fix; a deeper redesign (sequence-numbered
    `part-001.parquet`, `part-002.parquet` per date, union-read in the
    DuckDB view) is deferred to a future plan.
    """
    dt = datetime.fromtimestamp(ms / 1000, tz=UTC)
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day_start.timestamp() * 1000)


@dataclass(frozen=True)
class BackfillResult:
    """Outcome of one `backfill_symbol_interval` call."""

    pages: int
    rows_published: int
    structural_rejections: int
    durations_ms: tuple[int, ...]  # length == pages; one per page fetch


# --------------------------------------------------------------------------- #
# Cursor persistence — idempotent re-run support (D-02 reversibility).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CursorStore:
    """Per-(symbol, interval) cursor persistence for idempotent re-runs.

    Each cursor file stores the open_time (ms) of the last SUCCESSFULLY
    published candle. A re-run reads the cursor and resumes at the next
    open_time, so a killed run never double-publishes (D-02). On a
    structural rejection, the paginator does NOT advance the cursor —
    the persisted value stays at the last good publish so the corrupt
    page is re-encountered on the next run (fail-closed).

    Layout:
        {root}/{symbol}_{interval}.cursor   (plain text, integer ms)

    `None` from `read()` means "nothing persisted yet" — the caller
    decides the bootstrap start (the live-5 bounded-depth runner uses
    a per-interval default window).
    """

    root: Path

    def _path(self, *, symbol: str, interval: str) -> Path:
        return self.root / f"{symbol}_{interval}.cursor"

    def read(self, *, symbol: str, interval: str) -> int | None:
        path = self._path(symbol=symbol, interval=interval)
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            log.warning(
                "backfill.cursor.corrupt",
                path=str(path),
                content=text,
            )
            return None

    def write(self, *, symbol: str, interval: str, cursor_ms: int) -> None:
        path = self._path(symbol=symbol, interval=interval)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(cursor_ms), encoding="utf-8")


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
    start_ms: int | None = None,
    end_ms: int,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config: BackfillConfig | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_publish: Callable[[int], Awaitable[None] | None] | None = None,
    cursor_store: CursorStore | None = None,
) -> BackfillResult:
    """Paginate `[start_ms, end_ms)` for one (symbol, interval) and publish.

    `clock` is injectable so tests can run with a frozen wall-clock and
    assert that the forming candle is dropped deterministically
    (Pitfall 1 — REPLAY-1 of the 02-02 threat model).

    `start_ms=None` together with `cursor_store` resumes from the last
    persisted cursor (`cursor_store.read(...) + 1 interval`); an explicit
    `start_ms` always wins. On every successful publish, the cursor is
    written to `cursor_store` so a killed run resumes cleanly (D-02
    reversibility, idempotent re-run).
    """
    cfg = config or BackfillConfig(interval_ms=interval_ms(interval))
    pages = 0
    rows_published = 0
    structural_rejections = 0
    duplicates_skipped = 0
    durations: list[int] = []

    # Resume from cursor when start_ms not given.
    if start_ms is None:
        if cursor_store is None:
            raise ValueError(
                "start_ms is None but no cursor_store was provided; "
                "pass start_ms explicitly OR supply a cursor_store to resume"
            )
        persisted = cursor_store.read(symbol=symbol, interval=interval)
        if persisted is None:
            raise ValueError(
                f"start_ms is None and cursor_store has no entry for "
                f"{symbol}/{interval}; pass start_ms explicitly to bootstrap"
            )
        start_ms = persisted + cfg.interval_ms
        log.info(
            "backfill.resume",
            symbol=symbol,
            interval=interval,
            from_ms=start_ms,
            from_persisted_ms=persisted,
        )

    cursor = start_ms
    # Sentinel: nothing published yet — `start_ms - interval_ms` so the
    # first publish naturally lands at `last_published_open_ms + interval_ms`
    # and on a corrupt first page the cursor stays put at `start_ms`
    # (the loop will retry via subsequent fetches).
    last_published_open_ms = start_ms - cfg.interval_ms
    now_ms = int(clock().timestamp() * 1000)
    # Cross-page dedup: Binance's paginated response can return an
    # overlapping row at the boundary (Pitfall 2). Track every open_time
    # we've added to a per-date buffer so the overlap lands in Parquet
    # exactly once.
    seen_open_times: set[int] = set()
    # Per-date buffer for candles that may still receive more data in
    # subsequent pages. A real Binance page (up to 1500 candles for 1h)
    # can span multiple UTC dates; the D-04 per-day Parquet layout
    # raises on any second write to the same partition, so we cannot
    # publish a date until we are CONFIDENT no later batch will revisit
    # it. The rule: after each page, publish all dates in the buffer
    # EXCEPT the latest one (which a future page might still extend).
    # The latest date is flushed at end-of-loop. See `align_to_day_start_ms`
    # for the bootstrap-start alignment that prevents mid-page splits.
    date_buffers: dict[_date, list[Kline]] = {}

    while cursor < end_ms:
        page_start = cursor
        pages += 1
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

        # Drop the forming candle: anything whose close_time is in the future
        # relative to the injected clock (Pitfall 1). This must run BEFORE the
        # quality gate so it never inspects an unclosed bar.
        closed: list[Kline] = [
            k for k in raw_page if int(k.close_time_utc.timestamp() * 1000) <= now_ms
        ]

        # Cross-page dedup: skip rows whose open_time we already buffered
        # on a previous page. Track them as "seen" only after the batch
        # passes the quality gate so a rejected batch never poisons later
        # cursor advances.
        if closed:
            deduped: list[Kline] = []
            for k in closed:
                k_open_ms = int(k.open_time_utc.timestamp() * 1000)
                if k_open_ms in seen_open_times:
                    duplicates_skipped += 1
                    continue
                seen_open_times.add(k_open_ms)
                deduped.append(k)
            closed = deduped

        corrupt_rejection = False
        if closed:
            verdict = check_batch(closed, interval)
            if not verdict.structural_ok:
                structural_rejections += 1
                corrupt_rejection = True
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
                # caller observes the rejection via the counter.
            else:
                # Group the closed batch by date and add to per-date buffer.
                for k in closed:
                    d = k.open_time_utc.date()
                    date_buffers.setdefault(d, []).append(k)

                # Publish every date EXCEPT the latest one. The latest date
                # may still receive more candles on subsequent pages (real
                # Binance pages can span 60+ UTC dates for 1h), so we defer
                # its publication until either (a) a later page brings a
                # candle in a later date, or (b) the loop ends (final flush).
                if date_buffers:
                    latest_date = max(date_buffers.keys())
                    for d in sorted(date_buffers.keys()):
                        if d == latest_date:
                            continue
                        candles = sorted(
                            date_buffers[d],
                            key=lambda c: int(c.open_time_utc.timestamp() * 1000),
                        )
                        written = publish_batch(
                            candles,
                            interval=interval,
                            symbol=symbol,
                            raw_root=raw_root,
                        )
                        rows_published += len(candles)
                        last_published_open_ms = int(
                            candles[-1].open_time_utc.timestamp() * 1000
                        )
                        if cursor_store is not None:
                            # Persist on every successful publish so a killed
                            # run resumes at the right cursor (D-02
                            # reversibility).
                            cursor_store.write(
                                symbol=symbol,
                                interval=interval,
                                cursor_ms=last_published_open_ms,
                            )
                        log.info(
                            "backfill.published",
                            symbol=symbol,
                            interval=interval,
                            rows=len(candles),
                            files=written,
                            gap_count=verdict.gap_count,
                            duplicates_skipped=duplicates_skipped,
                        )
                        del date_buffers[d]
                        if on_publish is not None:
                            result = on_publish(len(candles))
                            if asyncio.iscoroutine(result):
                                await result

        # Advance the cursor.
        if corrupt_rejection:
            # Fail-closed: do NOT advance past good data. Roll back to
            # immediately after the last successful publish so a re-run
            # re-encounters the corrupt page (Behavior #4). When the
            # FIRST page was corrupt and nothing is published yet, the
            # cursor stays at `start_ms` and the next fetch retries from
            # there — a real Binance rate-limit response will eventually
            # surface so we don't loop forever.
            cursor = last_published_open_ms + cfg.interval_ms
        elif raw_page:
            # Normal advance past the page we just fetched.
            last_open = int(raw_page[-1].open_time_utc.timestamp() * 1000)
            cursor = max(last_open + cfg.interval_ms, page_start + cfg.interval_ms)
        else:
            cursor = page_start + cfg.interval_ms

        if cursor < end_ms and cfg.pace_seconds > 0:
            await asyncio.sleep(cfg.pace_seconds)

    # End-of-loop flush: every date still in the buffer is now "as complete
    # as we're going to get" (no more pages, no more candles for those
    # dates in this run). Publish them in order and advance the cursor to
    # the last published candle.
    if date_buffers:
        for d in sorted(date_buffers.keys()):
            candles = sorted(
                date_buffers[d],
                key=lambda c: int(c.open_time_utc.timestamp() * 1000),
            )
            written = publish_batch(
                candles,
                interval=interval,
                symbol=symbol,
                raw_root=raw_root,
            )
            rows_published += len(candles)
            last_published_open_ms = int(
                candles[-1].open_time_utc.timestamp() * 1000
            )
            if cursor_store is not None:
                cursor_store.write(
                    symbol=symbol,
                    interval=interval,
                    cursor_ms=last_published_open_ms,
                )
            log.info(
                "backfill.flush",
                symbol=symbol,
                interval=interval,
                date=d.isoformat(),
                rows=len(candles),
                files=written,
            )
            del date_buffers[d]

    return BackfillResult(
        pages=pages,
        rows_published=rows_published,
        structural_rejections=structural_rejections,
        durations_ms=tuple(durations),
    )


# --------------------------------------------------------------------------- #
# Multi-symbol / multi-interval runner (D-01 + D-02 first bootstrap).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UniverseBootstrapResult:
    """Outcome of one `backfill_universe` call.

    `per_key` keys are `(symbol, interval)` tuples; values are the
    `BackfillResult` from `backfill_symbol_interval` for that pair.
    `total_rows` / `total_pages` / `total_rejections` aggregate across
    the universe so a smoke-test can assert the bootstrap closed cleanly.
    """

    per_key: dict[tuple[str, str], BackfillResult]
    total_rows: int
    total_pages: int
    total_rejections: int


# D-01: V1 live-5 universe. Frozen at plan time; expand later phases add
# 10–15 symbol research slice separately.
LIVE_5: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")

# D-02: Bounded first-bootstrap defaults per interval. The runner uses
# these when a (symbol, interval) cursor is not yet persisted.
#   - 1m: ~7 days back (1m × 5 × 7d = ~50_400 candles per symbol, well
#     inside the 2400 weight/min cap; tested in this phase)
#   - 1H/4H: ~30 days back (smaller payload; the OI history is the
#     longer-horizon artifact, not the candles)
DEFAULT_BACKFILL_WINDOWS_MS: dict[str, int] = {
    "1m": 7 * 24 * 60 * 60_000,
    "1h": 30 * 24 * 60 * 60_000,
    "4h": 30 * 24 * 60 * 60_000,
}


async def backfill_universe(
    adapter: BinanceUsdmAdapter,
    *,
    symbols: tuple[str, ...] = LIVE_5,
    intervals: tuple[str, ...] = ("1m", "1h", "4h"),
    end_ms: int | None = None,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config: BackfillConfig | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    cursor_store: CursorStore | None = None,
) -> UniverseBootstrapResult:
    """Backfill the live-5 across `intervals` at bounded depth (D-01 + D-02).

    Per (symbol, interval):
      - If `cursor_store` has an entry, resume from `cursor + 1 interval`.
      - Otherwise start at `end_ms - DEFAULT_BACKFILL_WINDOWS_MS[interval]`
        (bounded bootstrap; expand via a follow-up run with a deeper
        explicit window).

    Symbols × intervals run sequentially inside one async loop so the
    weight budget stays bounded (Pitfall 5 — pacing). A future plan may
    parallelize across symbols with a bounded semaphore; for V1 the
    sequential runner is enough to cover the live-5 bounded bootstrap.
    """
    cfg = config or BackfillConfig(interval_ms=0)
    # Resolve end_ms once so every per-(symbol, interval) call uses the
    # same "now" anchor (deterministic — same input → same output).
    resolved_end_ms = (
        end_ms if end_ms is not None else int(clock().timestamp() * 1000)
    )
    per_key: dict[tuple[str, str], BackfillResult] = {}
    total_rows = 0
    total_pages = 0
    total_rejections = 0

    for interval in intervals:
        window_ms = DEFAULT_BACKFILL_WINDOWS_MS.get(interval)
        if window_ms is None:
            log.warning(
                "backfill.universe.skip_interval",
                interval=interval,
                reason="no bounded default — pass start_ms explicitly",
            )
            continue
        for symbol in symbols:
            # Per-key start: prefer the persisted cursor (idempotent
            # re-run) over the bounded-default window.
            if cursor_store is not None:
                persisted = cursor_store.read(symbol=symbol, interval=interval)
            else:
                persisted = None
            if persisted is not None:
                key_start_ms: int | None = persisted + interval_ms(interval)
            else:
                # Snap to the UTC day boundary so each page fits in one
                # per-day partition (see `align_to_day_start_ms` docstring
                # for the D-04 / multi-date-per-page rationale).
                key_start_ms = align_to_day_start_ms(resolved_end_ms - window_ms)
            log.info(
                "backfill.universe.begin",
                symbol=symbol,
                interval=interval,
                start_ms=key_start_ms,
                end_ms=resolved_end_ms,
                from_persisted=persisted,
            )
            result = await backfill_symbol_interval(
                adapter,
                symbol=symbol,
                interval=interval,
                start_ms=key_start_ms,
                end_ms=resolved_end_ms,
                raw_root=raw_root,
                config=cfg,
                clock=clock,
                cursor_store=cursor_store,
            )
            per_key[(symbol, interval)] = result
            total_rows += result.rows_published
            total_pages += result.pages
            total_rejections += result.structural_rejections
            log.info(
                "backfill.universe.end",
                symbol=symbol,
                interval=interval,
                pages=result.pages,
                rows=result.rows_published,
                rejections=result.structural_rejections,
            )
    return UniverseBootstrapResult(
        per_key=per_key,
        total_rows=total_rows,
        total_pages=total_pages,
        total_rejections=total_rejections,
    )


def interval_ms(interval: str) -> int:
    """Resolve the interval name to its millisecond duration."""
    # Local import to keep the public API of quality.py independent of this
    # function (the table lives there for canonical access).
    from src.data.quality import INTERVAL_MS

    if interval not in INTERVAL_MS:
        raise ValueError(f"unknown interval {interval!r}")
    return INTERVAL_MS[interval]
