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
     already on disk raises `FileExistsError`; the write itself is atomic,
     D-14).
  8. Publishes ONLY whole, closed UTC days (D-13, F-402): the effective end
     of every run is `min(end_ms, start of the current UTC day)`, rows at or
     after it are dropped before buffering, and a day is published only when
     the fetch window covered all of it (or the caller marks the end as
     `terminal_end`, a delivered contract's last day). A partially fetched
     day is held back, counted in `BackfillResult.partial_days_held`, and the
     cursor never advances past it — published Parquet is immutable, so a
     partial day could never be repaired.

Production use: called by `02-03`/`02-04` plans; this file is the
tracer's wiring skeleton (PLAN 02-02 Task 1).
"""

from __future__ import annotations

import asyncio
import calendar
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from pathlib import Path
from typing import Any, Protocol, overload

import structlog
import tenacity
from src.adapters.binance_usdm import Kline, MarkKline, is_rate_limit_error
from src.data.quality import QualityVerdict, check_batch, check_mark_batch
from src.data.store import (
    DEFAULT_RAW_ROOT,
    MARK_DATASET_DIR,
    publish_batch,
    publish_mark_batch,
)

log = structlog.get_logger()

DAY_MS = 86_400_000
_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)


def utc_ms(value: datetime) -> int:
    """Convert a tz-aware datetime to integer millisecond epoch.

    Exact integer timedelta arithmetic (same as `src.paper.resync`); the
    float `timestamp() * 1000` round-trip can skew a boundary by 1 ms, which
    would misplace a bar against the closed-day cut. Naive datetimes are
    rejected: their epoch is host-timezone dependent (determinism).
    """
    if value.tzinfo is None:
        raise ValueError("utc_ms requires a timezone-aware datetime")
    delta = value.astimezone(UTC) - _EPOCH_UTC
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


class KlineSource(Protocol):
    """Anything that can serve one kline page (REST adapter, archive source).

    The paginator depends on this shape only, so every source feeds the same
    quality gate and immutable store. Keyword-only so both the real
    `BinanceUsdmAdapter` and a plain test fake satisfy it structurally.
    """

    async def klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]: ...


class MarkKlineSource(Protocol):
    """Anything that can serve one mark-price kline page (D-11).

    Same keyword-only page contract as `KlineSource`, returning `MarkKline`.
    """

    async def mark_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]: ...


class _TimedRow(Protocol):
    """The two attributes the paginator reads from any dataset row."""

    @property
    def open_time_utc(self) -> datetime: ...

    @property
    def close_time_utc(self) -> datetime: ...


@dataclass(frozen=True)
class DatasetSpec[S, R: _TimedRow]:
    """How the paginator fetches, validates and publishes one dataset.

    The pagination, closed-day rule, dedup, cursor and structural-reject logic
    is dataset-independent; only these three callables differ between trade
    klines and mark klines (D-11). `name` keys the cursor file namespace, so a
    trade run and a mark run can never share a cursor.
    """

    name: str
    fetch: Callable[[S, str, str, int, int], Awaitable[list[R]]]
    validate: Callable[[list[R], str], QualityVerdict]
    publish: Callable[[list[R], str, str, Path], list[Path]]
    # Directory under the raw root that holds this dataset's day partitions
    # ("" for trade klines, `dataset=mark_klines` for mark klines). The resume
    # floor (`latest_published_day`) scans it.
    root_subdir: str = ""


async def _fetch_trade(
    source: KlineSource, symbol: str, interval: str, start_ms: int, limit: int
) -> list[Kline]:
    return await source.klines(
        symbol=symbol, interval=interval, start_ms=start_ms, limit=limit
    )


def _publish_trade(
    rows: list[Kline], interval: str, symbol: str, raw_root: Path
) -> list[Path]:
    return publish_batch(rows, interval=interval, symbol=symbol, raw_root=raw_root)


async def _fetch_mark(
    source: MarkKlineSource, symbol: str, interval: str, start_ms: int, limit: int
) -> list[MarkKline]:
    return await source.mark_klines(
        symbol=symbol, interval=interval, start_ms=start_ms, limit=limit
    )


def _publish_mark(
    rows: list[MarkKline], interval: str, symbol: str, raw_root: Path
) -> list[Path]:
    return publish_mark_batch(rows, interval=interval, symbol=symbol, raw_root=raw_root)


TRADE_DATASET: DatasetSpec[KlineSource, Kline] = DatasetSpec(
    name="trade",
    fetch=_fetch_trade,
    validate=check_batch,
    publish=_publish_trade,
)

MARK_DATASET: DatasetSpec[MarkKlineSource, MarkKline] = DatasetSpec(
    name="mark",
    fetch=_fetch_mark,
    validate=check_mark_batch,
    publish=_publish_mark,
    root_subdir=MARK_DATASET_DIR,
)


# Rate-limited failures are retried with jitter; on exhaustion the paginator
# raises and lets the caller decide (D-09 fail-closed posture).

# An empty page advances only one interval per round-trip — a long hole
# (e.g. a 30-day `1m` gap ≈ 43k serial fetches) must break fast instead
# of crawling one interval at a time.
MAX_CONSECUTIVE_EMPTY_PAGES = 100

# Fail closed AND terminate: a deterministically corrupt window never
# becomes a rate-limit, so consecutive structural rejections without a
# single successful publish raise instead of re-fetching forever.
MAX_CONSECUTIVE_REJECTIONS = 5


class StructuralRejectionError(RuntimeError):
    """Raised when consecutive corrupt pages exceed the in-run budget."""

    def __init__(
        self, symbol: str, interval: str, cursor_ms: int, consecutive: int
    ) -> None:
        super().__init__(
            f"structural rejection budget exhausted for {symbol}/{interval} "
            f"at cursor_ms={cursor_ms} "
            f"({consecutive} consecutive rejections, no successful publish)"
        )
        self.symbol = symbol
        self.interval = interval
        self.cursor_ms = cursor_ms
        self.consecutive = consecutive


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

    Integer math only: the float round-trip through `timestamp() * 1000`
    can skew the snap by up to 1 ms.
    """
    return ms - (ms % DAY_MS)


@dataclass(frozen=True)
class BackfillResult:
    """Outcome of one `backfill_symbol_interval` call."""

    pages: int
    rows_published: int
    structural_rejections: int
    durations_ms: tuple[int, ...]  # length == pages; one per page fetch
    # Past days the window only partly covered (held back, not published).
    partial_days_held: int = 0


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
        {root}/{symbol}_{interval}.cursor             (trade, plain text, integer ms)
        {root}/{dataset}__{symbol}_{interval}.cursor  (any other dataset, e.g. mark)

    `dataset` namespaces the file so a trade run and a mark run sharing one
    root can never overwrite each other's cursor; the trade name is unchanged.

    `None` from `read()` means "nothing persisted yet" — the caller
    decides the bootstrap start (the live-5 bounded-depth runner uses
    a per-interval default window).
    """

    root: Path
    dataset: str = "trade"

    def _path(self, *, symbol: str, interval: str) -> Path:
        if self.dataset == "trade":
            return self.root / f"{symbol}_{interval}.cursor"
        return self.root / f"{self.dataset}__{symbol}_{interval}.cursor"

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
        # Atomic persist: a kill mid-write must never leave a torn cursor
        # file behind (tmp + os.replace is atomic on POSIX and Windows).
        path = self._path(symbol=symbol, interval=interval)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(str(cursor_ms), encoding="utf-8")
        os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Page-fetch helper with bounded retry.
# --------------------------------------------------------------------------- #


def _is_rate_limit(exc: BaseException) -> bool:
    """Best-effort detection of a 429/418 response inside an SDK error.

    Delegates to the adapter (`is_rate_limit_error`), the only module
    allowed to import the SDK — the paginator never touches SDK types
    directly (`test_adapter_returned_type_is_domain_kline`).
    """
    return is_rate_limit_error(exc)


@overload
async def fetch_page_with_retry(
    adapter: KlineSource,
    *,
    symbol: str,
    interval: str,
    start_ms: int,
    limit: int,
    max_retries: int,
    jitter_max_seconds: float,
) -> list[Kline]: ...


@overload
async def fetch_page_with_retry[S, R: _TimedRow](
    adapter: S,
    *,
    symbol: str,
    interval: str,
    start_ms: int,
    limit: int,
    max_retries: int,
    jitter_max_seconds: float,
    dataset: DatasetSpec[S, R],
) -> list[R]: ...


async def fetch_page_with_retry(
    adapter: Any,
    *,
    symbol: str,
    interval: str,
    start_ms: int,
    limit: int,
    max_retries: int,
    jitter_max_seconds: float,
    dataset: DatasetSpec[Any, Any] = TRADE_DATASET,
) -> list[Any]:
    """Fetch one page of `dataset` with tenacity-bounded retry on rate-limit hits."""
    retry = tenacity.retry_if_exception(lambda e: _is_rate_limit(e))
    stop = tenacity.stop_after_attempt(max_retries)
    wait = tenacity.wait_exponential_jitter(initial=0.5, max=jitter_max_seconds * 4)
    decorator = tenacity.AsyncRetrying(retry=retry, stop=stop, wait=wait, reraise=True)

    async def _fetch() -> list[Any]:
        return await dataset.fetch(adapter, symbol, interval, start_ms, limit)

    async for attempt in decorator:
        with attempt:
            return await _fetch()
    # tenacity with reraise=True will raise on exhaustion; the explicit
    # return here satisfies the type checker for the non-raising path.
    raise RuntimeError("unreachable: tenacity.AsyncRetrying exhausted without reraise")


# --------------------------------------------------------------------------- #
# Paginator.
# --------------------------------------------------------------------------- #


@overload
async def backfill_symbol_interval(
    adapter: KlineSource,
    *,
    symbol: str,
    interval: str,
    start_ms: int | None = None,
    end_ms: int,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config: BackfillConfig | None = None,
    clock: Callable[[], datetime] = ...,
    on_publish: Callable[[int], Awaitable[None] | None] | None = None,
    cursor_store: CursorStore | None = None,
    terminal_end: bool = False,
) -> BackfillResult: ...


@overload
async def backfill_symbol_interval[S, R: _TimedRow](
    adapter: S,
    *,
    symbol: str,
    interval: str,
    start_ms: int | None = None,
    end_ms: int,
    dataset: DatasetSpec[S, R],
    raw_root: Path = DEFAULT_RAW_ROOT,
    config: BackfillConfig | None = None,
    clock: Callable[[], datetime] = ...,
    on_publish: Callable[[int], Awaitable[None] | None] | None = None,
    cursor_store: CursorStore | None = None,
    terminal_end: bool = False,
) -> BackfillResult: ...


async def backfill_symbol_interval(
    adapter: Any,
    *,
    symbol: str,
    interval: str,
    start_ms: int | None = None,
    end_ms: int,
    dataset: DatasetSpec[Any, Any] = TRADE_DATASET,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config: BackfillConfig | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_publish: Callable[[int], Awaitable[None] | None] | None = None,
    cursor_store: CursorStore | None = None,
    terminal_end: bool = False,
) -> BackfillResult:
    """Paginate `[start_ms, end_ms)` for one (symbol, interval) and publish.

    Closed-day rule (D-13, F-402): the run never publishes the current UTC
    day. `effective_end = min(end_ms, start of the current UTC day)`; rows
    whose open_time is at or after it are dropped before buffering. A day is
    published only when the window covered all of it (the day ends at or
    before `effective_end`). `terminal_end=True` additionally publishes the
    day containing `effective_end - 1` even though it is only partly covered
    -- for a delivered contract's last day, when `end_ms` is itself in the
    past. Any other partly covered day is held back (logged, counted in
    `BackfillResult.partial_days_held`) and the cursor is not advanced past
    it, so a later run can fetch it whole. Callers should pass a day-aligned
    `start_ms` (see `align_to_day_start_ms`).

    `dataset` selects what is fetched, validated and published (trade klines
    by default; `MARK_DATASET` for mark-price klines). A `cursor_store` of a
    different dataset is refused before any fetch: the two datasets must never
    share a cursor (D-11).

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
    # The cadence is load-bearing for resume math + cursor advance — a
    # config built for another interval must fail loudly, never drift.
    expected_interval_ms = interval_ms(interval)
    if cfg.interval_ms != expected_interval_ms:
        raise ValueError(
            f"BackfillConfig.interval_ms={cfg.interval_ms} does not match "
            f"interval {interval!r} ({expected_interval_ms} ms)"
        )
    if cursor_store is not None and cursor_store.dataset != dataset.name:
        raise ValueError(
            f"cursor_store dataset {cursor_store.dataset!r} does not match "
            f"backfill dataset {dataset.name!r}; refusing to share a cursor"
        )
    pages = 0
    rows_published = 0
    structural_rejections = 0
    consecutive_rejections = 0
    consecutive_empty_pages = 0
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
    now_ms = utc_ms(clock())
    day_start_now = align_to_day_start_ms(now_ms)
    effective_end = min(end_ms, day_start_now)
    if end_ms > day_start_now:
        log.info(
            "backfill.clamped_to_closed_days",
            symbol=symbol,
            interval=interval,
            end_ms=end_ms,
            effective_end_ms=effective_end,
        )
    # The terminal flag only means something when the caller's own end is a
    # closed past instant; a clamped end is never terminal (the day is open).
    terminal = terminal_end and end_ms <= day_start_now
    partial_days_held = 0
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
    date_buffers: dict[_date, list[Any]] = {}

    while cursor < effective_end:
        page_start = cursor
        pages += 1
        # Monotonic clock for durations: wall-clock `datetime.now(UTC)`
        # would leak host time into `BackfillResult`, breaking the
        # byte-reproducibility contract (durations are telemetry only and
        # excluded from equality assertions).
        t0 = time.monotonic()
        raw_page = await fetch_page_with_retry(
            adapter,
            symbol=symbol,
            interval=interval,
            start_ms=cursor,
            limit=cfg.page_size,
            max_retries=cfg.max_retries,
            jitter_max_seconds=cfg.jitter_max_seconds,
            dataset=dataset,
        )
        durations.append(int((time.monotonic() - t0) * 1000))

        # Drop the forming candle: anything whose close_time is in the future
        # relative to the injected clock (Pitfall 1), and anything at or after
        # the effective end (closed-day rule, D-13). This must run BEFORE the
        # quality gate so it never inspects an unclosed or out-of-window bar.
        closed: list[Any] = [
            k
            for k in raw_page
            if utc_ms(k.close_time_utc) <= now_ms
            and utc_ms(k.open_time_utc) < effective_end
        ]

        # Cross-page dedup: skip rows whose open_time we already buffered
        # on a previous page. Open_times are marked "seen" ONLY after the
        # batch passes the quality gate (in the structural_ok branch
        # below) so a rejected batch never poisons the set: on a
        # structural rejection the cursor rolls back and the next fetch
        # re-encounters the same rows, which must NOT be dropped as
        # "duplicates" (fail-closed — corrupt data is surfaced, never
        # silently skipped).
        if closed:
            deduped: list[Any] = []
            for k in closed:
                k_open_ms = utc_ms(k.open_time_utc)
                if k_open_ms in seen_open_times:
                    duplicates_skipped += 1
                    continue
                deduped.append(k)
            closed = deduped

        corrupt_rejection = False
        if closed:
            verdict = dataset.validate(closed, interval)
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
                # The batch passed the gate: only NOW mark its rows seen
                # (see the dedup comment above) and buffer them by date.
                for k in closed:
                    seen_open_times.add(utc_ms(k.open_time_utc))
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
                            key=lambda c: utc_ms(c.open_time_utc),
                        )
                        written = dataset.publish(candles, interval, symbol, raw_root)
                        rows_published += len(candles)
                        last_published_open_ms = utc_ms(candles[-1].open_time_utc)
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
            # there — but only up to MAX_CONSECUTIVE_REJECTIONS times: a
            # deterministically corrupt window never heals, so we raise
            # instead of re-fetching the identical page forever.
            consecutive_rejections += 1
            if consecutive_rejections > MAX_CONSECUTIVE_REJECTIONS:
                raise StructuralRejectionError(
                    symbol, interval, cursor, consecutive_rejections
                )
            cursor = last_published_open_ms + cfg.interval_ms
        elif raw_page:
            consecutive_rejections = 0
            consecutive_empty_pages = 0
            # Normal advance past the page we just fetched.
            last_open = utc_ms(raw_page[-1].open_time_utc)
            cursor = max(last_open + cfg.interval_ms, page_start + cfg.interval_ms)
        else:
            consecutive_rejections = 0
            consecutive_empty_pages += 1
            if consecutive_empty_pages > MAX_CONSECUTIVE_EMPTY_PAGES:
                log.warning(
                    "backfill.empty_hole",
                    symbol=symbol,
                    interval=interval,
                    cursor_ms=cursor,
                    consecutive_empty_pages=consecutive_empty_pages,
                )
                break
            cursor = page_start + cfg.interval_ms

        if cursor < effective_end and cfg.pace_seconds > 0:
            await asyncio.sleep(cfg.pace_seconds)

    # End-of-loop flush: a buffered date is published only when this run's
    # window covered the whole day (it ends at or before `effective_end`), or
    # when `terminal` marks the day containing `effective_end - 1` as the
    # last day of a delivered contract. Every other buffered date is a
    # partially fetched day: immutable Parquet could never repair it, so it
    # is held back (dropped from the buffer, logged, counted) and the cursor
    # is never written for its rows (D-13, F-402).
    if date_buffers:
        terminal_day = (
            _EPOCH_UTC + timedelta(milliseconds=effective_end - 1)
        ).date()
        for d in sorted(date_buffers.keys()):
            day_start_ms = utc_ms(datetime(d.year, d.month, d.day, tzinfo=UTC))
            whole_day = day_start_ms + DAY_MS <= effective_end
            if not whole_day and not (terminal and d == terminal_day):
                partial_days_held += 1
                log.warning(
                    "backfill.partial_day_held",
                    symbol=symbol,
                    interval=interval,
                    date=d.isoformat(),
                    rows=len(date_buffers[d]),
                )
                del date_buffers[d]
                continue
            candles = sorted(
                date_buffers[d],
                key=lambda c: utc_ms(c.open_time_utc),
            )
            written = dataset.publish(candles, interval, symbol, raw_root)
            rows_published += len(candles)
            last_published_open_ms = utc_ms(candles[-1].open_time_utc)
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
            # Progress consumers must see flushed rows too — the buffered
            # publish path fires on_publish, so the final flush does as well.
            if on_publish is not None:
                result = on_publish(len(candles))
                if asyncio.iscoroutine(result):
                    await result

    return BackfillResult(
        pages=pages,
        rows_published=rows_published,
        structural_rejections=structural_rejections,
        durations_ms=tuple(durations),
        partial_days_held=partial_days_held,
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


# D-04: decided history depth for the research backfill (F-122, F-906): 12
# months of 1m and 24 months of 1h/4h before the run date. The CLI prints the
# depth it used and lets flags override it.
DEPTH_MONTHS_DEFAULT: dict[str, int] = {"1m": 12, "1h": 24, "4h": 24}


def months_before(day: _date, months: int) -> _date:
    """Calendar-month subtraction, day clamped to the target month's length.

    `months_before(2026-03-31, 1)` is 2026-02-28 (never an invalid date).
    Integer month arithmetic only, so the result is deterministic.
    """
    if months < 0:
        raise ValueError(f"months must be non-negative, got {months}")
    total = day.year * 12 + (day.month - 1) - months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    return _date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def latest_published_day(
    raw_root: Path,
    *,
    dataset: DatasetSpec[Any, Any],
    symbol: str,
    interval: str,
) -> _date | None:
    """Latest UTC day with a published `part.parquet` for one key, else None.

    Scans `raw_root/<dataset.root_subdir>/interval=<I>/symbol=<S>/date=*/`.
    Published Parquet is immutable (D-04), so a resumed run must start after
    this day even when its cursor file is lost. Directory names that do not
    parse as an ISO date are ignored.
    """
    base = raw_root / dataset.root_subdir / f"interval={interval}" / f"symbol={symbol}"
    if not base.is_dir():
        return None
    latest: _date | None = None
    for part in base.glob("date=*/part.parquet"):
        try:
            day = _date.fromisoformat(part.parent.name.removeprefix("date="))
        except ValueError:
            continue
        if latest is None or day > latest:
            latest = day
    return latest


@overload
async def backfill_universe(
    adapter: KlineSource,
    *,
    symbols: tuple[str, ...] = ...,
    intervals: tuple[str, ...] = ...,
    end_ms: int | None = None,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config: BackfillConfig | None = None,
    clock: Callable[[], datetime] = ...,
    cursor_store: CursorStore | None = None,
    interval_start_ms: Mapping[str, int] | None = None,
    start_floor_ms: Mapping[str, int] | None = None,
    end_cap_ms: Mapping[str, int] | None = None,
    resume_from_store: bool = False,
) -> UniverseBootstrapResult: ...


@overload
async def backfill_universe[S, R: _TimedRow](
    adapter: S,
    *,
    symbols: tuple[str, ...] = ...,
    intervals: tuple[str, ...] = ...,
    end_ms: int | None = None,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config: BackfillConfig | None = None,
    clock: Callable[[], datetime] = ...,
    cursor_store: CursorStore | None = None,
    interval_start_ms: Mapping[str, int] | None = None,
    start_floor_ms: Mapping[str, int] | None = None,
    end_cap_ms: Mapping[str, int] | None = None,
    dataset: DatasetSpec[S, R],
    resume_from_store: bool = False,
) -> UniverseBootstrapResult: ...


async def backfill_universe(
    adapter: Any,
    *,
    symbols: tuple[str, ...] = LIVE_5,
    intervals: tuple[str, ...] = ("1m", "1h", "4h"),
    end_ms: int | None = None,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config: BackfillConfig | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    cursor_store: CursorStore | None = None,
    interval_start_ms: Mapping[str, int] | None = None,
    start_floor_ms: Mapping[str, int] | None = None,
    end_cap_ms: Mapping[str, int] | None = None,
    dataset: DatasetSpec[Any, Any] = TRADE_DATASET,
    resume_from_store: bool = False,
) -> UniverseBootstrapResult:
    """Backfill `symbols` across `intervals` (D-01 + D-02, extended by D-04).

    Per (symbol, interval), with every new keyword omitted (the default):
      - If `cursor_store` has an entry, resume from `cursor + 1 interval`.
      - Otherwise start at `end_ms - DEFAULT_BACKFILL_WINDOWS_MS[interval]`
        (bounded bootstrap; expand via a follow-up run with a deeper
        explicit window).

    History-depth keywords (all optional, all default to the behavior above):
      - `interval_start_ms`: explicit start per interval, used instead of the
        bounded default window; a persisted cursor still moves it forward.
      - `start_floor_ms`: per-symbol lower bound (e.g. the onboard time).
      - `end_cap_ms`: per-symbol upper bound. A cap below the resolved end is
        a contract's delivery: the run ends there and `terminal_end` lets the
        paginator publish the partly covered last day.
      - `dataset`: what is fetched/validated/published (trade by default).
      - `resume_from_store`: also floor the start at the day after the latest
        published partition, so a lost cursor can never re-publish a stored
        day (D-04 immutability).
    A key whose start is at or beyond its end is logged and returns an empty
    result without touching the adapter.

    Symbols × intervals run sequentially inside one async loop so the
    weight budget stays bounded (Pitfall 5 — pacing). A future plan may
    parallelize across symbols with a bounded semaphore; for V1 the
    sequential runner is enough to cover the live-5 bounded bootstrap.
    """
    # Resolve end_ms once so every per-(symbol, interval) call uses the
    # same "now" anchor (deterministic — same input → same output).
    resolved_end_ms = end_ms if end_ms is not None else utc_ms(clock())
    per_key: dict[tuple[str, str], BackfillResult] = {}
    total_rows = 0
    total_pages = 0
    total_rejections = 0

    for interval in intervals:
        window_ms = DEFAULT_BACKFILL_WINDOWS_MS.get(interval)
        explicit_start_ms = (
            interval_start_ms.get(interval) if interval_start_ms is not None else None
        )
        if window_ms is None and explicit_start_ms is None:
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
            if explicit_start_ms is not None:
                key_start_ms = explicit_start_ms
                if persisted is not None:
                    key_start_ms = max(key_start_ms, persisted + interval_ms(interval))
            elif persisted is not None:
                key_start_ms = persisted + interval_ms(interval)
            else:
                # Snap to the UTC day boundary so each page fits in one
                # per-day partition (see `align_to_day_start_ms` docstring
                # for the D-04 / multi-date-per-page rationale).
                assert window_ms is not None  # narrowed by the skip above
                key_start_ms = align_to_day_start_ms(resolved_end_ms - window_ms)
            floor_ms = start_floor_ms.get(symbol) if start_floor_ms is not None else None
            if floor_ms is not None:
                key_start_ms = max(key_start_ms, floor_ms)
            if resume_from_store:
                latest_day = latest_published_day(
                    raw_root, dataset=dataset, symbol=symbol, interval=interval
                )
                if latest_day is not None:
                    day_start = utc_ms(
                        datetime(
                            latest_day.year, latest_day.month, latest_day.day, tzinfo=UTC
                        )
                    )
                    key_start_ms = max(key_start_ms, day_start + DAY_MS)
            # Per-symbol end: a cap below the resolved end is a delivery, and
            # the run must end there as a terminal window (research Pitfall 1).
            key_end_ms = resolved_end_ms
            terminal = False
            cap_ms = end_cap_ms.get(symbol) if end_cap_ms is not None else None
            if cap_ms is not None and cap_ms < resolved_end_ms:
                key_end_ms = cap_ms
                terminal = True
            if key_start_ms >= key_end_ms:
                log.info(
                    "backfill.universe.empty_window",
                    symbol=symbol,
                    interval=interval,
                    start_ms=key_start_ms,
                    end_ms=key_end_ms,
                )
                per_key[(symbol, interval)] = BackfillResult(
                    pages=0,
                    rows_published=0,
                    structural_rejections=0,
                    durations_ms=(),
                )
                continue
            log.info(
                "backfill.universe.begin",
                symbol=symbol,
                interval=interval,
                start_ms=key_start_ms,
                end_ms=key_end_ms,
                from_persisted=persisted,
                terminal=terminal,
            )
            # Per-interval config: never share one interval_ms across
            # timeframes (a shared interval_ms=0 froze the cursor and the
            # `while cursor < end_ms` loop could never terminate). The
            # caller's other knobs (page_size, pacing, retries) are
            # preserved; only the cadence is derived per interval.
            per_cfg = (
                replace(config, interval_ms=interval_ms(interval))
                if config is not None
                else BackfillConfig(interval_ms=interval_ms(interval))
            )
            result = await backfill_symbol_interval(
                adapter,
                symbol=symbol,
                interval=interval,
                start_ms=key_start_ms,
                end_ms=key_end_ms,
                dataset=dataset,
                raw_root=raw_root,
                config=per_cfg,
                clock=clock,
                cursor_store=cursor_store,
                terminal_end=terminal,
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
