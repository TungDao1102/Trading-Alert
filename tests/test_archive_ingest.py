"""Archive (data.binance.vision) ingestion as a `KlineSource` (D-08, DATA-01).

Delisted symbols that REST no longer serves are read from Binance's public
archive. Every zip is checksum-verified before parsing and its klines flow
through the same paginator, quality gate, closed-day rule and atomic
publisher as REST data. No test touches the network: every request is served
by respx, and every zip is built in-test with `zipfile`.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import polars as pl
import respx
from polars.testing import assert_frame_equal
from src.adapters.binance_usdm import Kline, _row_to_kline
from src.data.backfill import BackfillConfig, backfill_symbol_interval

SYMBOL = "FTTUSDT"
INTERVAL = "1h"
HOUR_MS = 3_600_000
BASE = "https://data.binance.vision/data/futures/um"
HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _arc() -> ModuleType:
    """The module under test, imported lazily so RED fails per test."""
    return importlib.import_module("src.data.archive")


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    delta = datetime(year, month, day, hour, tzinfo=UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000


def _clock(ms: int):  # type: ignore[no-untyped-def]
    fixed = _EPOCH + timedelta(milliseconds=ms)
    return lambda: fixed


def _csv_row(open_ms: int, step_ms: int = HOUR_MS, *, ts_width: int | None = None) -> str:
    """One archive CSV data row in the real 12-column layout."""
    open_txt = str(open_ms)
    close_txt = str(open_ms + step_ms - 1)
    if ts_width is not None:
        open_txt = open_txt.ljust(ts_width, "0")[:ts_width]
    return (
        f"{open_txt},24.2350,24.3440,24.1750,24.2350,16620.0,{close_txt},"
        "403353.45570,2487,10387.1,252109.82740,0"
    )


def _csv(start_ms: int, count: int, *, header: bool = True, step_ms: int = HOUR_MS) -> str:
    lines = [HEADER] if header else []
    lines += [_csv_row(start_ms + i * step_ms, step_ms) for i in range(count)]
    return "\n".join(lines) + "\n"


def _zip_bytes(csv_text: str, member: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, csv_text)
    return buf.getvalue()


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _url(period: str, stamp: str, *, symbol: str = SYMBOL, interval: str = INTERVAL) -> str:
    return f"{BASE}/{period}/klines/{symbol}/{interval}/{symbol}-{interval}-{stamp}.zip"


def _serve(
    router: respx.MockRouter,
    period: str,
    stamp: str,
    csv_text: str,
    *,
    symbol: str = SYMBOL,
    interval: str = INTERVAL,
    digest: str | None = None,
    member: str | None = None,
) -> tuple[respx.Route, respx.Route]:
    """Mock one zip and its `.CHECKSUM`; returns (zip_route, checksum_route)."""
    name = f"{symbol}-{interval}-{stamp}"
    blob = _zip_bytes(csv_text, member if member is not None else f"{name}.csv")
    url = _url(period, stamp, symbol=symbol, interval=interval)
    checksum_route = router.get(f"{url}.CHECKSUM").respond(
        200, text=f"{digest or _sha(blob)}  {name}.zip\n"
    )
    zip_route = router.get(url).respond(200, content=blob)
    return zip_route, checksum_route


def _missing(router: respx.MockRouter, period: str, stamp: str) -> None:
    url = _url(period, stamp)
    router.get(f"{url}.CHECKSUM").respond(404)
    router.get(url).respond(404)


def _expected_klines(start_ms: int, count: int) -> list[Kline]:
    return [
        _row_to_kline(SYMBOL, INTERVAL, _csv_row(start_ms + i * HOUR_MS).split(","))
        for i in range(count)
    ]


class _RestFake:
    """REST-shaped source over pre-built klines (same rows as the archive)."""

    def __init__(self, bars: list[Kline]) -> None:
        self._bars = sorted(bars, key=lambda k: k.open_time_utc)

    async def klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        floor = start_ms if start_ms is not None else 0
        out = [
            k
            for k in self._bars
            if int((k.open_time_utc - _EPOCH) / timedelta(milliseconds=1)) >= floor
        ]
        return out[:limit]


def _published(root: Path, symbol: str = SYMBOL) -> dict[str, pl.DataFrame]:
    base = root / f"interval={INTERVAL}" / f"symbol={symbol}"
    if not base.exists():
        return {}
    return {f.parent.name: pl.read_parquet(f) for f in sorted(base.rglob("part.parquet"))}


OCT_2022 = _ms(2022, 10, 1)
NOV_2022 = _ms(2022, 11, 1)
OCT_ROWS = 744


# ---------------------------------------------------------------------------
# Task 1: tracer - monthly zip -> ArchiveKlineSource -> paginator -> Parquet
# ---------------------------------------------------------------------------


async def test_fetch_archive_klines_parses_month_and_skips_header() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        _serve(router, "monthly", "2022-10", _csv(OCT_2022, OCT_ROWS))
        async with arc.make_archive_client() as client:
            rows = await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")

    assert len(rows) == OCT_ROWS
    assert rows == _expected_klines(OCT_2022, OCT_ROWS)


async def test_archive_source_pages_through_a_month() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        zip_route, _ = _serve(router, "monthly", "2022-10", _csv(OCT_2022, OCT_ROWS))
        async with arc.make_archive_client() as client:
            source = arc.ArchiveKlineSource(client, search_end_ms=NOV_2022)
            first = await source.klines(SYMBOL, INTERVAL, start_ms=OCT_2022, limit=500)
            next_open = int((first[-1].open_time_utc - _EPOCH) / timedelta(milliseconds=1))
            second = await source.klines(
                SYMBOL, INTERVAL, start_ms=next_open + HOUR_MS, limit=500
            )
            past_end = await source.klines(SYMBOL, INTERVAL, start_ms=NOV_2022, limit=500)

        assert len(first) == 500
        assert len(second) == OCT_ROWS - 500
        assert past_end == []
        assert first + second == _expected_klines(OCT_2022, OCT_ROWS)
        # The zip is downloaded once per stamp per source instance.
        assert zip_route.call_count == 1


async def test_archive_month_publishes_same_frames_as_rest(tmp_path: Path) -> None:
    arc = _arc()
    archive_root = tmp_path / "archive"
    rest_root = tmp_path / "rest"
    cfg = BackfillConfig(interval_ms=HOUR_MS, pace_seconds=0)

    with respx.mock(assert_all_called=False) as router:
        _serve(router, "monthly", "2022-10", _csv(OCT_2022, OCT_ROWS))
        async with arc.make_archive_client() as client:
            source = arc.ArchiveKlineSource(client, search_end_ms=NOV_2022)
            archive_result = await backfill_symbol_interval(
                source,
                symbol=SYMBOL,
                interval=INTERVAL,
                start_ms=OCT_2022,
                end_ms=NOV_2022,
                raw_root=archive_root,
                config=cfg,
                clock=_clock(_ms(2026, 9, 30)),
            )

    rest_result = await backfill_symbol_interval(
        _RestFake(_expected_klines(OCT_2022, OCT_ROWS)),
        symbol=SYMBOL,
        interval=INTERVAL,
        start_ms=OCT_2022,
        end_ms=NOV_2022,
        raw_root=rest_root,
        config=cfg,
        clock=_clock(_ms(2026, 9, 30)),
    )

    archive_days = _published(archive_root)
    rest_days = _published(rest_root)
    assert len(archive_days) == 31
    assert archive_days.keys() == rest_days.keys()
    for day, frame in archive_days.items():
        assert_frame_equal(frame, rest_days[day])
    assert archive_result.rows_published == rest_result.rows_published == OCT_ROWS
    assert archive_result.structural_rejections == 0


def test_archive_module_reuses_the_adapter_row_mapping() -> None:
    """The 12-column mapping lives in the adapter only (no second mapping)."""
    source = (Path(__file__).parent.parent / "src" / "data" / "archive.py").read_text(
        encoding="utf-8"
    )
    assert "_row_to_kline" in source
    assert "Decimal(" not in source
