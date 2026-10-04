"""Contiguity-aware resume floor for `backfill_universe` (CR-02, phase 13 review).

The published store (not the newest partition, not the cursor file) decides
what a resumed run fetches: only UTC days with no partition inside the
requested window, and never a day that already has a partition (D-04
immutability). A stray newer partition or an over-eager cursor must not hide
older missing days. Synthetic bars only; a fake source stands in for Binance.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
from src.adapters.binance_usdm import Kline
from src.data.backfill import (
    BackfillConfig,
    CursorStore,
    backfill_symbol_interval,
    backfill_universe,
    missing_day_runs,
)
from structlog.testing import capture_logs

INTERVAL = "1h"
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
SYMBOL = "BTCUSDT"


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    delta = datetime(year, month, day, hour, minute, tzinfo=UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000


def _clock(ms: int):  # type: ignore[no-untyped-def]
    fixed = _EPOCH + timedelta(milliseconds=ms)
    return lambda: fixed


def _bar(open_ms: int) -> Kline:
    price = Decimal("100.00")
    return Kline(
        symbol=SYMBOL,
        interval=INTERVAL,
        open_time_utc=_EPOCH + timedelta(milliseconds=open_ms),
        close_time_utc=_EPOCH + timedelta(milliseconds=open_ms + HOUR_MS - 1),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1.0"),
        quote_volume=Decimal("100.00"),
        trade_count=10,
    )


def _days(first_day: int, count: int) -> list[Kline]:
    """Full-day bars for `count` days of Nov 2023 starting at `first_day`."""
    start = _ms(2023, 11, first_day)
    return [_bar(start + i * HOUR_MS) for i in range(count * 24)]


class _Source:
    """Mimics the exchange: every bar at or after `start_ms`, capped by `limit`."""

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
    base = raw_root / f"interval={INTERVAL}" / f"symbol={SYMBOL}"
    if not base.exists():
        return {}
    return {f.parent.name: pl.read_parquet(f).height for f in sorted(base.rglob("part.parquet"))}


async def _seed_day(raw_root: Path, day: int) -> None:
    """Publish one full day (Nov `day`) the way an earlier run would have."""
    await backfill_symbol_interval(
        _Source(_days(day, 1)),
        symbol=SYMBOL,
        interval=INTERVAL,
        start_ms=_ms(2023, 11, day),
        end_ms=_ms(2023, 11, day + 1),
        raw_root=raw_root,
        config=_cfg(),
        clock=_clock(_ms(2023, 12, 1)),
    )


def test_missing_day_runs_finds_every_hole_and_never_touches_published_days() -> None:
    published = frozenset({date(2023, 11, 3), date(2023, 11, 4), date(2023, 11, 7)})

    runs = missing_day_runs(_ms(2023, 11, 1), _ms(2023, 11, 9), published)

    assert runs == [
        (_ms(2023, 11, 1), _ms(2023, 11, 3)),
        (_ms(2023, 11, 5), _ms(2023, 11, 7)),
        (_ms(2023, 11, 8), _ms(2023, 11, 9)),
    ]


def test_missing_day_runs_keeps_a_mid_day_start_and_an_unaligned_end() -> None:
    start = _ms(2023, 11, 1, 7)
    end = _ms(2023, 11, 3, 5)

    assert missing_day_runs(start, end, frozenset()) == [(start, end)]
    assert missing_day_runs(start, end, frozenset({date(2023, 11, 2)})) == [
        (start, _ms(2023, 11, 2)),
        (_ms(2023, 11, 3), end),
    ]
    assert missing_day_runs(end, start, frozenset()) == []


async def test_stray_newer_partition_does_not_hide_older_missing_days(tmp_path: Path) -> None:
    """Days 1-4 and 6 are fetched around the stray day-5 partition, which is untouched."""
    await _seed_day(tmp_path, 5)
    source = _Source(_days(1, 6))
    cursors = CursorStore(root=tmp_path / "cursors")

    with capture_logs() as logs:
        result = await backfill_universe(
            source,
            symbols=(SYMBOL,),
            intervals=(INTERVAL,),
            raw_root=tmp_path,
            config=_cfg(),
            clock=_clock(_ms(2023, 11, 7, 1)),
            cursor_store=cursors,
            interval_start_ms={INTERVAL: _ms(2023, 11, 1)},
            resume_from_store=True,
        )

    assert _published(tmp_path) == {f"date=2023-11-0{d}": 24 for d in range(1, 7)}
    assert result.per_key[(SYMBOL, INTERVAL)].rows_published == 5 * 24
    assert result.total_rejections == 0
    assert any(e["event"] == "backfill.universe.interior_hole" for e in logs)


async def test_cursor_ahead_of_store_never_skips_missing_days(tmp_path: Path) -> None:
    """A cursor past unpublished days is overridden by the store, with a warning."""
    cursors = CursorStore(root=tmp_path / "cursors")
    cursors.write(symbol=SYMBOL, interval=INTERVAL, cursor_ms=_ms(2023, 11, 5, 23))
    source = _Source(_days(1, 5))

    with capture_logs() as logs:
        result = await backfill_universe(
            source,
            symbols=(SYMBOL,),
            intervals=(INTERVAL,),
            raw_root=tmp_path,
            config=_cfg(),
            clock=_clock(_ms(2023, 11, 6, 1)),
            cursor_store=cursors,
            interval_start_ms={INTERVAL: _ms(2023, 11, 1)},
            resume_from_store=True,
        )

    assert sorted(_published(tmp_path)) == [f"date=2023-11-0{d}" for d in range(1, 6)]
    assert result.per_key[(SYMBOL, INTERVAL)].rows_published == 5 * 24
    warned = [e for e in logs if e["event"] == "backfill.universe.cursor_ahead_of_store"]
    assert warned and warned[0]["log_level"] == "warning"


async def test_contiguous_store_is_complete_and_makes_no_adapter_call(tmp_path: Path) -> None:
    for day in (1, 2, 3):
        await _seed_day(tmp_path, day)
    source = _Source(_days(1, 4))

    with capture_logs() as logs:
        result = await backfill_universe(
            source,
            symbols=(SYMBOL,),
            intervals=(INTERVAL,),
            raw_root=tmp_path,
            config=_cfg(),
            clock=_clock(_ms(2023, 11, 4, 1)),
            interval_start_ms={INTERVAL: _ms(2023, 11, 1)},
            resume_from_store=True,
        )

    assert source.calls == []
    assert result.total_rows == 0
    assert any(e["event"] == "backfill.universe.complete_from_store" for e in logs)
    assert not [e for e in logs if e["log_level"] == "warning"]


async def test_deeper_window_extends_history_backwards(tmp_path: Path) -> None:
    """A deeper explicit window fetches the older days in front of the stored run."""
    for day in (4, 5):
        await _seed_day(tmp_path, day)
    source = _Source(_days(1, 5))

    result = await backfill_universe(
        source,
        symbols=(SYMBOL,),
        intervals=(INTERVAL,),
        raw_root=tmp_path,
        config=_cfg(),
        clock=_clock(_ms(2023, 11, 6, 1)),
        interval_start_ms={INTERVAL: _ms(2023, 11, 1)},
        resume_from_store=True,
    )

    assert sorted(_published(tmp_path)) == [f"date=2023-11-0{d}" for d in range(1, 6)]
    assert result.total_rows == 3 * 24


async def test_cursor_floored_empty_window_logs_a_warning_with_both_starts(
    tmp_path: Path,
) -> None:
    """Legacy (cursor-only) mode: a floor that empties the window is not silent."""
    cursors = CursorStore(root=tmp_path / "cursors")
    cursors.write(symbol=SYMBOL, interval=INTERVAL, cursor_ms=_ms(2023, 11, 5, 23))
    source = _Source(_days(1, 5))
    requested = _ms(2023, 11, 1)

    with capture_logs() as logs:
        result = await backfill_universe(
            source,
            symbols=(SYMBOL,),
            intervals=(INTERVAL,),
            raw_root=tmp_path,
            config=_cfg(),
            clock=_clock(_ms(2023, 11, 6, 1)),
            end_ms=_ms(2023, 11, 3),
            cursor_store=cursors,
            interval_start_ms={INTERVAL: requested},
        )

    assert source.calls == []
    assert result.total_rows == 0
    empty = [e for e in logs if e["event"] == "backfill.universe.empty_window"]
    assert empty and empty[0]["log_level"] == "warning"
    assert empty[0]["requested_start_ms"] == requested
    assert empty[0]["floored_start_ms"] == _ms(2023, 11, 6)
    assert empty[0]["floor_reason"] == "cursor"
