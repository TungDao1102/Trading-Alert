"""Closed-day publishing rule for the backfill paginator (D-13, F-402).

Published Parquet is immutable, so a partial or still-open UTC day must never
become a file: the effective end of every run is
`min(end_ms, start of the current UTC day)`, and a day file is published only
when the fetch window covered the whole day (or the caller marked the end as
terminal, i.e. a delivered contract's last day).

The source is a plain class exposing the kline fetch signature (the
`KlineSource` contract) — no `BinanceUsdmAdapter`, no network. Clocks are
frozen, and every published file is written into `tmp_path`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
from src.adapters.binance_usdm import Kline
from src.data.backfill import (
    BackfillConfig,
    CursorStore,
    backfill_symbol_interval,
)

INTERVAL = "1h"
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Integer epoch milliseconds for a UTC wall-clock instant."""
    delta = datetime(year, month, day, hour, minute, tzinfo=UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000


def _clock(ms: int):  # type: ignore[no-untyped-def]
    fixed = _EPOCH + timedelta(milliseconds=ms)
    return lambda: fixed


def _bar(open_ms: int, *, trade_count: int = 10) -> Kline:
    zero = trade_count == 0
    price = Decimal("100.00")
    return Kline(
        symbol="BTCUSDT",
        interval=INTERVAL,
        open_time_utc=_EPOCH + timedelta(milliseconds=open_ms),
        close_time_utc=_EPOCH + timedelta(milliseconds=open_ms + HOUR_MS - 1),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("0") if zero else Decimal("1.0"),
        quote_volume=Decimal("0") if zero else Decimal("100.00"),
        trade_count=trade_count,
    )


def _bars(start_ms: int, count: int) -> list[Kline]:
    return [_bar(start_ms + i * HOUR_MS) for i in range(count)]


class _Source:
    """Kline source that mimics the exchange: bars at or after `start_ms`."""

    def __init__(self, bars: list[Kline]) -> None:
        self._bars = sorted(bars, key=lambda k: k.open_time_utc)
        self.calls: list[int | None] = []

    async def klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        self.calls.append(start_ms)
        floor = start_ms if start_ms is not None else 0
        out = [
            k
            for k in self._bars
            if int((k.open_time_utc - _EPOCH) / timedelta(milliseconds=1)) >= floor
        ]
        return out[:limit]


def _cfg() -> BackfillConfig:
    return BackfillConfig(interval_ms=HOUR_MS, pace_seconds=0)


def _published(raw_root: Path) -> dict[str, int]:
    """Map `date=YYYY-MM-DD` directory name to its published row count."""
    base = raw_root / f"interval={INTERVAL}" / "symbol=BTCUSDT"
    if not base.exists():
        return {}
    return {
        f.parent.name: pl.read_parquet(f).height
        for f in sorted(base.rglob("part.parquet"))
    }


async def test_current_utc_day_is_never_published(tmp_path: Path) -> None:
    """Closed bars of the current UTC day stay out; only the closed day publishes."""
    day = _ms(2023, 11, 14)
    today = _ms(2023, 11, 15)
    bars = _bars(day, 24) + [_bar(today), _bar(today + HOUR_MS)]
    cursors = CursorStore(root=tmp_path / "cursors")

    result = await backfill_symbol_interval(
        _Source(bars),
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=day,
        end_ms=_ms(2023, 11, 15, 2),
        raw_root=tmp_path,
        config=_cfg(),
        clock=_clock(_ms(2023, 11, 15, 1, 1)),
        cursor_store=cursors,
    )

    assert _published(tmp_path) == {"date=2023-11-14": 24}
    assert not (
        tmp_path / f"interval={INTERVAL}" / "symbol=BTCUSDT" / "date=2023-11-15"
    ).exists()
    assert result.rows_published == 24
    assert cursors.read(symbol="BTCUSDT", interval=INTERVAL) == day + 23 * HOUR_MS


async def test_partial_past_day_is_held_back_unless_terminal(
    tmp_path: Path,
) -> None:
    """A past day only partly covered by the window is held, never published."""
    day = _ms(2023, 11, 14)
    end = _ms(2023, 11, 14, 15)
    cursors = CursorStore(root=tmp_path / "cursors")

    held = await backfill_symbol_interval(
        _Source(_bars(day, 15)),
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=day,
        end_ms=end,
        raw_root=tmp_path / "held",
        config=_cfg(),
        cursor_store=cursors,
    )

    assert _published(tmp_path / "held") == {}
    assert held.rows_published == 0
    assert held.partial_days_held == 1
    assert cursors.read(symbol="BTCUSDT", interval=INTERVAL) is None

    terminal = await backfill_symbol_interval(
        _Source(_bars(day, 15)),
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=day,
        end_ms=end,
        raw_root=tmp_path / "terminal",
        config=_cfg(),
        terminal_end=True,
    )

    assert _published(tmp_path / "terminal") == {"date=2023-11-14": 15}
    assert terminal.rows_published == 15
    assert terminal.partial_days_held == 0


async def test_rows_at_or_after_the_effective_end_are_never_buffered(
    tmp_path: Path,
) -> None:
    """A page that overshoots end_ms publishes only rows before it."""
    day = _ms(2023, 11, 14)
    bars = _bars(day, 24) + _bars(_ms(2023, 11, 15), 3)

    result = await backfill_symbol_interval(
        _Source(bars),
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=day,
        end_ms=_ms(2023, 11, 14, 20),
        raw_root=tmp_path,
        config=_cfg(),
        terminal_end=True,
    )

    assert _published(tmp_path) == {"date=2023-11-14": 20}
    assert result.rows_published == 20


async def test_resume_publishes_only_the_next_closed_day(tmp_path: Path) -> None:
    """A second run over the same cursor store publishes only the new day."""
    day1 = _ms(2023, 11, 14)
    day2 = _ms(2023, 11, 15)
    bars = _bars(day1, 24) + _bars(day2, 24) + [_bar(_ms(2023, 11, 16))]
    cursors = CursorStore(root=tmp_path / "cursors")

    first = await backfill_symbol_interval(
        _Source(bars),
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=day1,
        end_ms=_ms(2023, 11, 16, 2),
        raw_root=tmp_path,
        config=_cfg(),
        clock=_clock(_ms(2023, 11, 15, 1, 1)),
        cursor_store=cursors,
    )
    assert _published(tmp_path) == {"date=2023-11-14": 24}
    assert first.rows_published == 24

    second = await backfill_symbol_interval(
        _Source(bars),
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=None,
        end_ms=_ms(2023, 11, 16, 2),
        raw_root=tmp_path,
        config=_cfg(),
        clock=_clock(_ms(2023, 11, 16, 1, 1)),
        cursor_store=cursors,
    )

    assert _published(tmp_path) == {"date=2023-11-14": 24, "date=2023-11-15": 24}
    assert second.rows_published == 24
    assert cursors.read(symbol="BTCUSDT", interval=INTERVAL) == day2 + 23 * HOUR_MS


async def test_listing_day_with_late_first_bar_is_published(tmp_path: Path) -> None:
    """A symbol listed mid-day still publishes its (shorter) first closed day."""
    day = _ms(2023, 11, 14)

    result = await backfill_symbol_interval(
        _Source(_bars(_ms(2023, 11, 14, 7), 17)),
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=day,
        end_ms=_ms(2023, 11, 15, 2),
        raw_root=tmp_path,
        config=_cfg(),
        clock=_clock(_ms(2023, 11, 15, 1, 1)),
    )

    assert _published(tmp_path) == {"date=2023-11-14": 17}
    assert result.rows_published == 17
    assert result.partial_days_held == 0


async def test_empty_effective_window_makes_no_adapter_call(tmp_path: Path) -> None:
    """When the clamp leaves nothing to fetch, the source is never called."""
    source = _Source(_bars(_ms(2023, 11, 15), 2))

    result = await backfill_symbol_interval(
        source,
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=_ms(2023, 11, 15),
        end_ms=_ms(2023, 11, 15, 2),
        raw_root=tmp_path,
        config=_cfg(),
        clock=_clock(_ms(2023, 11, 15, 1, 1)),
    )

    assert result.pages == 0
    assert source.calls == []
    assert _published(tmp_path) == {}


async def test_any_object_with_the_kline_signature_is_a_source(
    tmp_path: Path,
) -> None:
    """The paginator is typed on the KlineSource Protocol, not the adapter."""
    from src.data.backfill import KlineSource

    day = _ms(2023, 11, 14)
    source: KlineSource = _Source(_bars(day, 24))

    result = await backfill_symbol_interval(
        source,
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=day,
        end_ms=_ms(2023, 11, 15),
        raw_root=tmp_path,
        config=_cfg(),
        clock=_clock(_ms(2023, 11, 15, 1)),
    )

    assert result.rows_published == 24


async def test_zero_trade_bars_are_published_with_the_rest_of_the_day(
    tmp_path: Path,
) -> None:
    """Illiquid zero-trade bars are real data: the whole day publishes (D-15)."""
    day = _ms(2023, 11, 14)
    bars = _bars(day, 24)
    for index in (3, 4, 17):
        bars[index] = _bar(day + index * HOUR_MS, trade_count=0)

    result = await backfill_symbol_interval(
        _Source(bars),
        symbol="BTCUSDT",
        interval=INTERVAL,
        start_ms=day,
        end_ms=_ms(2023, 11, 15),
        raw_root=tmp_path,
        config=_cfg(),
        clock=_clock(_ms(2023, 11, 15, 1)),
    )

    assert result.structural_rejections == 0
    assert result.rows_published == 24
    assert _published(tmp_path) == {"date=2023-11-14": 24}
