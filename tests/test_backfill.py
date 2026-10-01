"""Tests for the full live-5 bounded-depth backfill runner (02-03 §Task 2).

The 02-03 plan calls out four behaviors that the full bootstrap must
demonstrate (02-03-PLAN §tasks[2].behavior):

  1. Windowed cursor covering a multi-page range emits every expected
     candle with no silent truncation.
  2. Forming candle at the frozen-now boundary is excluded from publish
     (Pitfall 1 — no future-bar leakage / repaint).
  3. Killed run resumes from the persisted cursor and publishes only
     the remainder (idempotent re-run per D-02 reversibility).
  4. Structurally corrupt page is rejected while its cursor is NOT
     advanced past good data (fail-closed — no silent overwrite).

The adapter is a fake (no network), the clock is injectable, and the
publish path writes into a `tmp_path` so the tests are isolated. The
tracer slice's three behaviors (forming candle, cross-page dedup,
pacing+retry) live in `tests/test_tracer_slice.py` — we duplicate only
the forming-candle test here because the plan explicitly enumerates it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_usdm import Kline
from src.data.backfill import (
    BackfillConfig,
    BackfillResult,
    CursorStore,
    backfill_symbol_interval,
)

# --------------------------------------------------------------------------- #
# Test scaffold.
# --------------------------------------------------------------------------- #


INTERVAL = "1h"
INTERVAL_MS = 60 * 60_000
# Midnight UTC of 2023-11-14. The D-04 per-day partition layout raises
# when a single page spans two UTC dates and a later batch touches the
# same date again, so test bases must be day-aligned (see
# `src.data.backfill.align_to_day_start_ms`).
BASE_OPEN_MS = 1_699_920_000_000


class _FakeRateLimitError(Exception):
    """Stand-in for Binance's `TooManyRequestsError`."""


class FakeAdapter:
    """Programmable kline source.

    Each `klines()` call pops the next entry from `responses` and exposes
    the call in `self.calls` for assertions. Set `raise_after` to N to
    raise `RuntimeError("simulated kill")` on the (N+1)th call, simulating
    a process kill mid-backfill.
    """

    def __init__(
        self,
        responses: list[list[Kline] | BaseException],
        *,
        raise_after: int | None = None,
    ) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self._raise_after = raise_after

    async def klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        self.calls.append(
            {
                "symbol": symbol,
                "interval": interval,
                "start_ms": start_ms,
                "limit": limit,
            }
        )
        if self._raise_after is not None and len(self.calls) > self._raise_after:
            raise RuntimeError("simulated process kill mid-backfill")
        if not self._responses:
            return []
        nxt = self._responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _mk_kline(
    *,
    open_ms: int,
    close_ms: int,
    symbol: str = "BTCUSDT",
    interval: str = INTERVAL,
    open: str = "100.00",
    high: str = "101.00",
    low: str = "99.00",
    close: str = "100.50",
) -> Kline:
    """Build a valid Kline (high ≥ all, low ≤ all) by default.

    Pass `high` < `open` (or `low` > `close`) to produce an OHLC violation
    for the corruption test.
    """
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
        close_time_utc=datetime.fromtimestamp(close_ms / 1000, tz=UTC),
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1.0"),
        quote_volume=Decimal("100.50"),
        trade_count=10,
    )


def _frozen_clock(ms: int) -> callable:
    """Return a callable that always returns the same UTC instant."""
    fixed = datetime.fromtimestamp(ms / 1000, tz=UTC)

    def _now() -> datetime:
        return fixed

    return _now


def _read_published_symbol(raw_root: Path, *, symbol: str, interval: str) -> list[int]:
    """Read back every published open_time (ms) for one symbol × interval."""
    import polars as pl

    pattern = raw_root / f"interval={interval}" / f"symbol={symbol}"
    if not pattern.exists():
        return []
    files = sorted(pattern.rglob("part.parquet"))
    if not files:
        return []
    df = pl.concat([pl.read_parquet(f) for f in files])
    return [int(t.timestamp() * 1000) for t in df["open_time_utc"].to_list()]


# --------------------------------------------------------------------------- #
# Test 1 — multi-page windowed cursor emits every expected candle.
# --------------------------------------------------------------------------- #


async def test_windowed_cursor_emits_every_expected_candle(
    tmp_path: Path,
) -> None:
    """A window covering 3 pages of 8 candles each publishes the whole day.

    No silent truncation: every open_time in the window appears in
    Parquet exactly once. Page size is forced to 8 via `BackfillConfig.page_size`
    so the paginator needs three fetches to walk the full window. The window
    is one whole closed UTC day (D-13: a partial day would be held back), so
    the 24 bars publish as a single `date=` file.
    """
    base_ms = BASE_OPEN_MS
    total_bars = 24

    pages: list[list[Kline]] = []
    for page_idx in range(3):
        bars: list[Kline] = []
        for i in range(8):
            open_ms = base_ms + (page_idx * 8 + i) * INTERVAL_MS
            bars.append(_mk_kline(open_ms=open_ms, close_ms=open_ms + INTERVAL_MS - 1))
        pages.append(bars)

    adapter = FakeAdapter(responses=pages)

    cfg = BackfillConfig(interval_ms=INTERVAL_MS, pace_seconds=0, page_size=8)
    result = await backfill_symbol_interval(
        adapter,  # type: ignore[arg-type]
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=base_ms,
        end_ms=base_ms + total_bars * INTERVAL_MS,
        raw_root=tmp_path,
        config=cfg,
    )

    assert result.rows_published == total_bars, (
        f"expected {total_bars} rows, got {result.rows_published}"
    )
    assert result.pages == 3
    assert result.structural_rejections == 0
    assert len(adapter.calls) == 3

    published = _read_published_symbol(tmp_path, symbol="BTCUSDT", interval=INTERVAL)
    expected = [base_ms + i * INTERVAL_MS for i in range(total_bars)]
    assert published == expected


# --------------------------------------------------------------------------- #
# Test 2 — forming candle at frozen-now is excluded.
# --------------------------------------------------------------------------- #


async def test_forming_candle_at_frozen_now_is_excluded(
    tmp_path: Path,
) -> None:
    """At a frozen clock, the still-forming bar must NOT be published.

    Duplicated here from test_tracer_slice.py because the 02-03 plan
    enumerates it as one of the four behaviors the full runner must
    demonstrate. Since D-13 the frozen clock sits inside the CURRENT UTC day,
    so the closed-day rule also excludes the closed bar of that day: nothing
    is published, nothing is fetched, and the cursor is untouched.
    """
    closed_open = BASE_OPEN_MS
    forming_open = closed_open + INTERVAL_MS
    frozen_at = forming_open + 60_000

    closed_bar = _mk_kline(open_ms=closed_open, close_ms=closed_open + INTERVAL_MS - 1)
    forming_bar = _mk_kline(open_ms=forming_open, close_ms=forming_open + INTERVAL_MS - 1)

    adapter = FakeAdapter(responses=[[closed_bar, forming_bar]])
    cfg = BackfillConfig(interval_ms=INTERVAL_MS, pace_seconds=0)
    cursor_store = CursorStore(root=tmp_path / "cursors")

    result = await backfill_symbol_interval(
        adapter,  # type: ignore[arg-type]
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=closed_open,
        end_ms=forming_open + INTERVAL_MS,
        raw_root=tmp_path,
        config=cfg,
        clock=_frozen_clock(frozen_at),
        cursor_store=cursor_store,
    )

    assert result.rows_published == 0
    assert result.pages == 0
    assert adapter.calls == []
    published = _read_published_symbol(tmp_path, symbol="BTCUSDT", interval=INTERVAL)
    assert published == []
    assert cursor_store.read(symbol="BTCUSDT", interval=INTERVAL) is None


# --------------------------------------------------------------------------- #
# Test 3 — killed run resumes from persisted cursor (idempotent re-run).
# --------------------------------------------------------------------------- #


async def test_killed_run_resumes_from_persisted_cursor(
    tmp_path: Path,
) -> None:
    """A process that dies mid-bootstrap resumes from the cursor on restart.

    Page 1 must trigger a partial publish so the cursor is written before
    the kill. The paginator's date-buffer holds the LATEST date in the
    batch back until either a later page brings a later date OR the loop
    ends — so the first page's earliest date is published immediately
    only when the page spans at least 2 dates. With 1h bars at a day-
    aligned `base_ms`, that means `bars_per_page >= 25` (the first 24
    candles land on date D, the 25th crosses into D+1).

    The fixture builds 4 pages of 25 candles with a 1-candle overlap at
    every boundary (Binance-style paginated response overlap, Pitfall 2).
    Run 1 publishes D's 24 candles, persists cursor=23h, then the
    adapter raises on call #2. Run 2 reads the cursor, starts at 24h,
    and walks pages 2-4 — every date is published exactly once across
    both runs (no double-publish), and the published set is exactly the
    96 unique candles inside the window. The run ends at the day boundary
    `base + 96h` (D-13), so the fixture's trailing 97th candle (open ==
    end) is never published: only whole closed days D..D+3 exist.
    """
    base_ms = BASE_OPEN_MS
    bars_per_page = 25
    total_pages = 4

    # Fixture: 4 pages, each starting where the previous started (so
    # the boundary candle is the first candle of pages 2-4 and the LAST
    # candle of pages 1-3 — standard Binance paginator overlap shape).
    pages: list[list[Kline]] = []
    for page_idx in range(total_pages):
        bars: list[Kline] = []
        for i in range(bars_per_page):
            open_ms = base_ms + (page_idx * (bars_per_page - 1) + i) * INTERVAL_MS
            bars.append(_mk_kline(open_ms=open_ms, close_ms=open_ms + INTERVAL_MS - 1))
        pages.append(bars)

    # Expected unique candles: 100 in the fixture, 3 boundary overlaps
    # (24h, 48h, 72h each appear twice) → 97 unique, of which the 97th
    # (open == end_ms, 96h) is outside the window. The open_times come back
    # as datetimes from the fixture; we compare as ints below.
    end_ms = base_ms + total_pages * (bars_per_page - 1) * INTERVAL_MS
    all_unique_ms = sorted(
        {int(b.open_time_utc.timestamp() * 1000) for page in pages for b in page}
    )
    assert len(all_unique_ms) == 97
    assert all_unique_ms[-1] == end_ms  # last candle = 96h, outside the window
    expected_unique_open_times_ms = [t for t in all_unique_ms if t < end_ms]
    assert len(expected_unique_open_times_ms) == 96

    cursor_store = CursorStore(root=tmp_path / "cursors")
    cfg = BackfillConfig(interval_ms=INTERVAL_MS, pace_seconds=0, page_size=bars_per_page)

    # First run — kills itself after one page's fetch.
    adapter_killed = FakeAdapter(
        responses=list(pages),
        raise_after=1,  # let page 1 fetch + buffer/publish, then raise on call #2
    )
    with pytest.raises(RuntimeError, match="simulated process kill"):
        await backfill_symbol_interval(
            adapter_killed,  # type: ignore[arg-type]
            symbol="BTCUSDT",
            interval=INTERVAL,
            start_ms=base_ms,
            end_ms=base_ms + total_pages * (bars_per_page - 1) * INTERVAL_MS,
            raw_root=tmp_path,
            config=cfg,
            cursor_store=cursor_store,
        )

    # Cursor must now reflect D's last published candle (23h, midnight+23h).
    persisted = cursor_store.read(symbol="BTCUSDT", interval=INTERVAL)
    assert persisted is not None
    assert persisted == base_ms + 23 * INTERVAL_MS, (
        f"cursor must point at the last D candle (23h) which was the only "
        f"date fully published by run 1; got {persisted}"
    )

    # Second run — resumes from the cursor and finishes the remainder.
    remaining_pages = pages[1:]
    adapter_resumed = FakeAdapter(responses=list(remaining_pages))
    result = await backfill_symbol_interval(
        adapter_resumed,  # type: ignore[arg-type]
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=None,  # signal: read from cursor_store
        end_ms=base_ms + total_pages * (bars_per_page - 1) * INTERVAL_MS,
        raw_root=tmp_path,
        config=cfg,
        cursor_store=cursor_store,
    )

    # Resume must NOT republish D — and must publish exactly the remaining
    # 72 unique candles across D+1 (24), D+2 (24) and D+3 (24); D+4's
    # boundary candle is outside the window.
    assert result.rows_published == 72, (
        f"expected 72 rows on resume (24 + 24 + 24), got {result.rows_published}"
    )
    assert result.structural_rejections == 0

    # The full Parquet set contains exactly the 96 unique candles — no
    # double-publish of D, no missing D+1 boundary.
    published = _read_published_symbol(tmp_path, symbol="BTCUSDT", interval=INTERVAL)
    assert published == expected_unique_open_times_ms, (
        "resume must produce the full 96 unique candles with no duplicates"
    )


# --------------------------------------------------------------------------- #
# Test 4 — structurally corrupt page rejected, cursor NOT advanced past good.
# --------------------------------------------------------------------------- #


async def test_corrupt_page_rejected_cursor_not_advanced_past_good_data(
    tmp_path: Path,
) -> None:
    """A corrupt batch must not be published and the cursor must roll back
    so the corrupt page's open_times are NOT skipped silently.

    Page 1: 5 good candles at open_times [t, t+1h, t+2h, t+3h, t+4h]
    Page 2: 5 OHLC-corrupt candles at open_times [t+5h, ..., t+9h]
    Expected outcome:
      - rows_published == 5 (only page 1)
      - structural_rejections == 1 (page 2)
      - published Parquet contains exactly page 1's candles — NO corrupt
        rows, no silent overwrite, no skip
      - cursor is rolled back to immediately after page 1's last candle,
        so a re-run would re-encounter the corrupt page (fail-closed)
    """
    base_ms = BASE_OPEN_MS
    bars_per_page = 5

    good_bars: list[Kline] = []
    for i in range(bars_per_page):
        open_ms = base_ms + i * INTERVAL_MS
        good_bars.append(_mk_kline(open_ms=open_ms, close_ms=open_ms + INTERVAL_MS - 1))

    # Corrupt: `high < open` violates the OHLC relationship on every bar.
    corrupt_bars: list[Kline] = []
    for i in range(bars_per_page):
        open_ms = base_ms + (bars_per_page + i) * INTERVAL_MS
        corrupt_bars.append(
            _mk_kline(
                open_ms=open_ms,
                close_ms=open_ms + INTERVAL_MS - 1,
                open="110.00",
                high="100.00",  # high < open ⇒ OHLC violation
                low="100.00",
                close="105.00",
            )
        )

    adapter = FakeAdapter(responses=[good_bars, corrupt_bars])

    cursor_store = CursorStore(root=tmp_path / "cursors")
    cfg = BackfillConfig(interval_ms=INTERVAL_MS, pace_seconds=0, page_size=bars_per_page)

    result = await backfill_symbol_interval(
        adapter,  # type: ignore[arg-type]
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=base_ms,
        # Day boundary (D-13): the window covers the whole closed day, so the
        # buffered good rows publish at the end-of-loop flush.
        end_ms=base_ms + 24 * INTERVAL_MS,
        raw_root=tmp_path,
        config=cfg,
        cursor_store=cursor_store,
    )

    assert result.rows_published == bars_per_page, (
        f"only the good page should publish; got {result.rows_published} rows"
    )
    assert result.structural_rejections == 1

    # Persisted cursor must point at the last GOOD candle (page 1's last),
    # not at the corrupt page's last candle.
    persisted = cursor_store.read(symbol="BTCUSDT", interval=INTERVAL)
    assert persisted == base_ms + (bars_per_page - 1) * INTERVAL_MS, (
        f"cursor must roll back to last good publish; got {persisted}"
    )

    # Parquet contains exactly the 5 good candles — no overwrite, no skip.
    published = _read_published_symbol(tmp_path, symbol="BTCUSDT", interval=INTERVAL)
    assert published == [base_ms + i * INTERVAL_MS for i in range(bars_per_page)]


# --------------------------------------------------------------------------- #
# Helpers — exposed so the runner / smoke test can re-use them.
# --------------------------------------------------------------------------- #


def test_rate_limit_predicate_pins_canonical_sdk_error_names() -> None:
    """Pin the retry predicate to the SDK's real error classes.

    `fetch_page_with_retry` matches `isinstance` against the installed
    SDK's errors. If Binance renames the exception, the import (or this
    test) fails loudly instead of silently disabling all retry.
    """
    from binance_sdk_derivatives_trading_usds_futures import (
        RateLimitBanError,
        TooManyRequestsError,
    )
    from src.data.backfill import _is_rate_limit

    assert _is_rate_limit(TooManyRequestsError("429")) is True
    assert _is_rate_limit(RateLimitBanError("418")) is True
    assert _is_rate_limit(RuntimeError("boom")) is False
    assert _is_rate_limit(ValueError("TooManyRequests-like value")) is False


def _result_summary(result: BackfillResult) -> str:
    """Tiny formatter for ad-hoc verification scripts."""
    return (
        f"pages={result.pages} rows={result.rows_published} rejects={result.structural_rejections}"
    )


__all__ = [
    "FakeAdapter",
    "INTERVAL",
    "INTERVAL_MS",
    "_mk_kline",
    "_frozen_clock",
    "_read_published_symbol",
    "_result_summary",
]
