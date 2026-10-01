"""End-to-end tests for the 02-02 tracer slice.

These tests cover the three behaviors the plan explicitly calls out as
the tracer's acceptance criteria (02-02-PLAN §Test 1-3):

  1. The paginator drops the still-forming candle at a frozen clock
     boundary (Pitfall 1 — no future-bar leakage / repaint).
  2. Duplicate `open_time_utc` rows across paginated requests collapse
     to one published row (Pitfall 2 — overlap-with-previous-page).
  3. The paginator paces between pages and retries a rate-limit
     response before resuming from the original cursor (Pitfall 5).

The adapter is a fake (no network), the clock is injectable, and the
publish path writes into a `tmp_path` so the tests are isolated.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from src.adapters.binance_usdm import Kline
from src.data.backfill import BackfillConfig, backfill_symbol_interval

# --------------------------------------------------------------------------- #
# Test scaffold.
# --------------------------------------------------------------------------- #


class _FakeRateLimitError(Exception):
    """Stand-in for Binance's `TooManyRequestsError`.

    The paginator sniffs the class name (`_is_rate_limit`) so the fake
    needs a name that contains the canonical substring.
    """


class FakeAdapter:
    """Programmable kline source for the paginator tests.

    `responses` is a queue of either `Kline` lists (return value) or
    exceptions (raise on call). Each `klines()` invocation pops one
    entry and exposes the call via `self.calls` for assertions.
    """

    def __init__(self, responses: list[list[Kline] | BaseException]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

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
    interval: str = "1h",
    price: str = "100.00",
) -> Kline:
    """Build a minimal valid Kline for unit tests."""
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
        close_time_utc=datetime.fromtimestamp(close_ms / 1000, tz=UTC),
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1.0"),
        quote_volume=Decimal(price),
        trade_count=10,
    )


def _frozen_clock(ms: int) -> callable:
    """Return a zero-arg callable that always returns the same UTC instant."""

    fixed = datetime.fromtimestamp(ms / 1000, tz=UTC)

    def _now() -> datetime:
        return fixed

    return _now


def _read_published_symbol(raw_root: Path, *, symbol: str, interval: str) -> pl.DataFrame:
    """Read back everything we published for one symbol/interval."""
    pattern = raw_root / f"interval={interval}" / f"symbol={symbol}"
    if not pattern.exists():
        return pl.DataFrame()
    files = sorted(pattern.rglob("part.parquet"))
    if not files:
        return pl.DataFrame()
    return pl.concat([pl.read_parquet(f) for f in files])


# --------------------------------------------------------------------------- #
# Test 1 — forming candle is dropped at the frozen clock boundary.
# --------------------------------------------------------------------------- #


async def test_paginator_drops_forming_candle_at_frozen_clock(tmp_path: Path) -> None:
    # Two klines in the API response: one CLOSED bar + one still-forming bar.
    # The frozen clock sits inside the forming bar so the closed bar's
    # close_time is in the past (kept) and the forming bar's close_time is
    # in the future (dropped).
    #
    # D-13: the closed-day rule clamps the run to the start of the current
    # UTC day. The reference instant is 22:13:20 UTC on 2023-11-14 and the
    # forming bar straddles midnight, so the frozen clock is 00:10 UTC on
    # 2023-11-15: both bars open inside the closed day 2023-11-14 (the
    # close_time filter, not the day cut, is what drops the forming bar).
    closed_open = 1_700_000_000_000  # fixed reference instant
    forming_open = closed_open + 3_600_000  # +1h (next bar starts here)
    frozen_at = 1_700_007_000_000  # 2023-11-15T00:10Z, in the forming bar

    closed_bar = _mk_kline(
        open_ms=closed_open,
        close_ms=closed_open + 3_599_999,
    )
    forming_bar = _mk_kline(
        open_ms=forming_open,
        close_ms=forming_open + 3_599_999,
    )

    adapter = FakeAdapter(responses=[[closed_bar, forming_bar]])

    cfg = BackfillConfig(
        interval_ms=3_600_000,
        pace_seconds=0,  # no pacing noise in this test
    )

    result = await backfill_symbol_interval(
        adapter,  # type: ignore[arg-type]
        symbol="BTCUSDT",
        interval="1h",
        start_ms=closed_open,
        end_ms=forming_open + 3_600_000,
        raw_root=tmp_path,
        config=cfg,
        clock=_frozen_clock(frozen_at),
    )

    # Only the closed bar is published.
    assert result.rows_published == 1, (
        f"expected 1 closed row, got {result.rows_published} "
        f"(forming candle leaked across the frozen clock)"
    )
    assert result.structural_rejections == 0
    assert result.pages == 1

    published = _read_published_symbol(tmp_path, symbol="BTCUSDT", interval="1h")
    assert published.height == 1
    assert published["open_time_utc"][0].timestamp() * 1000 == closed_open


# --------------------------------------------------------------------------- #
# Test 2 — duplicate open_time rows across pages collapse to one publish.
# --------------------------------------------------------------------------- #


async def test_duplicate_open_time_across_pages_collapse_to_one_row(
    tmp_path: Path,
) -> None:
    # Two pages with an overlapping row at the boundary. The paginator
    # must dedup so the overlap row only lands in Parquet once.
    #
    # Mid-day mechanics (D-13): the window is the first three hours of a past
    # UTC day, so it passes `terminal_end=True` (a delivered contract's last
    # day) — otherwise the partly covered day would be held back.
    base = 1_699_920_000_000  # 2023-11-14T00:00Z
    bar0 = _mk_kline(open_ms=base, close_ms=base + 3_599_999)
    bar1 = _mk_kline(open_ms=base + 3_600_000, close_ms=base + 7_199_999)
    # `bar1` repeats on the next page (overlap).
    bar2 = _mk_kline(open_ms=base + 7_200_000, close_ms=base + 10_799_999)

    adapter = FakeAdapter(responses=[[bar0, bar1], [bar1, bar2]])

    cfg = BackfillConfig(
        interval_ms=3_600_000,
        pace_seconds=0,
        page_size=2,  # forces the cursor advance after two rows
    )

    result = await backfill_symbol_interval(
        adapter,  # type: ignore[arg-type]
        symbol="BTCUSDT",
        interval="1h",
        start_ms=base,
        end_ms=base + 3 * 3_600_000,
        raw_root=tmp_path,
        config=cfg,
        terminal_end=True,
    )

    # Three distinct bars total; bar1 must not have been published twice.
    assert result.rows_published == 3, (
        f"expected 3 unique rows published, got {result.rows_published} "
        f"(duplicate open_time was not collapsed)"
    )
    assert result.pages == 2
    assert result.structural_rejections == 0

    published = _read_published_symbol(tmp_path, symbol="BTCUSDT", interval="1h")
    assert published.height == 3
    open_times_ms = [int(t.timestamp() * 1000) for t in published["open_time_utc"].to_list()]
    assert open_times_ms == [
        base,
        base + 3_600_000,
        base + 7_200_000,
    ]


# --------------------------------------------------------------------------- #
# Test 3 — pacing + 429 retry from the original cursor.
# --------------------------------------------------------------------------- #


async def test_paced_fetch_sleeps_and_retries_429_then_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # First call raises a rate-limit; second call returns one valid page.
    # Mid-day mechanics (D-13): a one-hour window on a past UTC day passes
    # `terminal_end=True`, otherwise the partly covered day would be held back.
    base = 1_699_920_000_000  # 2023-11-14T00:00Z
    bar0 = _mk_kline(open_ms=base, close_ms=base + 3_599_999)
    adapter = FakeAdapter(
        responses=[
            _FakeRateLimitError("simulated 429 from Binance"),
            [bar0],
        ]
    )

    cfg = BackfillConfig(
        interval_ms=3_600_000,
        pace_seconds=0.05,
        max_retries=3,
        jitter_max_seconds=0.01,  # keep the test fast
    )

    # Patch asyncio.sleep to count invocations without actually waiting.
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    result = await backfill_symbol_interval(
        adapter,  # type: ignore[arg-type]
        symbol="BTCUSDT",
        interval="1h",
        start_ms=base,
        end_ms=base + 3_600_000,
        raw_root=tmp_path,
        config=cfg,
        terminal_end=True,
    )

    # The retry happened (two adapter calls — verified via the fake),
    # the page after the retry resumed from the original cursor, and
    # pacing sleeps were observed.
    assert len(adapter.calls) == 2, (
        f"expected retry to issue a 2nd adapter call, got {len(adapter.calls)}"
    )
    assert adapter.calls[0]["start_ms"] == base
    assert adapter.calls[1]["start_ms"] == base, (
        "paginator must resume from the original cursor after a 429 retry"
    )
    assert result.rows_published == 1
    # Tenacity handles the 429 retry *inside* fetch_page_with_retry, so
    # the paginator counts one paginator-level page (the retry is
    # transparent at this layer). The two adapter calls above prove the
    # retry actually happened.
    assert result.pages == 1
    assert any(s > 0 for s in sleep_calls), f"expected pacing sleep, got {sleep_calls}"


# --------------------------------------------------------------------------- #
# Sanity — BinanceUsdmAdapter does NOT leak the SDK type to the paginator.
# --------------------------------------------------------------------------- #


def test_adapter_returned_type_is_domain_kline() -> None:
    """Static guard: the paginator's contract is `list[Kline]`.

    The SDK's own response models are NOT permitted to enter the
    paginator — see `src/adapters/binance_usdm.py` module docstring.
    """
    import inspect

    from src.data import backfill as backfill_mod

    src = inspect.getsource(backfill_mod)
    assert "from binance_sdk_derivatives_trading_usds_futures" not in src, (
        "paginator must not import the SDK directly — adapter is the only owner"
    )
