"""Mark-price kline dataset: adapter mapping, schema, validation, publish (D-11, D-29).

Mark klines (`GET /fapi/v1/markPriceKlines`) are a SEPARATE immutable dataset
under `data/raw/dataset=mark_klines/...`. Their field 8 is a price-update
count, not a trade count, and their volume fields are always "0", so the
Parquet schema carries `price_tick_count` and no volume/trade_count column.

No network: a fake SDK exposes the one REST method the adapter calls and
returns rows shaped like the recorded fixture.
"""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    Kline,
    MarkKline,
    _row_to_mark_kline,
)
from src.data.backfill import (
    MARK_DATASET,
    TRADE_DATASET,
    BackfillConfig,
    CursorStore,
    backfill_symbol_interval,
)
from src.data.quality import check_mark_batch, mark_klines_to_frame
from src.data.store import MARK_DATASET_DIR, publish_mark_batch

FIXTURE = (
    Path(__file__).parent / "fixtures" / "phase13" / "mark_klines" / "mark_price_klines_sample.json"
)
MINUTE_MS = 60_000
DAY_MS = 86_400_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

MARK_COLUMNS = [
    "open_time_utc",
    "close_time_utc",
    "open",
    "high",
    "low",
    "close",
    "price_tick_count",
    "interval",
    "symbol",
]


def _sample_rows() -> list[list[Any]]:
    rows: list[list[Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return rows


def _dt(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


def _mark(
    open_ms: int,
    *,
    price: str = "100.00000000",
    ticks: int = 60,
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    duration_ms: int = MINUTE_MS,
) -> MarkKline:
    p = Decimal(price)
    return MarkKline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_dt(open_ms),
        close_time_utc=_dt(open_ms + duration_ms - 1),
        open=p,
        high=p,
        low=p,
        close=p,
        price_tick_count=ticks,
    )


# --------------------------------------------------------------------------- #
# Fake SDK (only what the adapter calls).
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _FakeRest:
    def __init__(self, rows: list[list[Any]]) -> None:
        self._rows = rows
        self.calls: list[dict[str, Any]] = []

    def mark_price_kline_candlestick_data(
        self,
        symbol: str,
        interval: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "symbol": symbol,
                "interval": interval,
                "start_time": start_time,
                "end_time": end_time,
                "limit": limit,
            }
        )
        floor = start_time if start_time is not None else 0
        page = [r for r in self._rows if int(r[0]) >= floor]
        return _FakeResponse(page[: limit or 500])


class _FakeSdk:
    def __init__(self, rows: list[list[Any]]) -> None:
        self.rest_api = _FakeRest(rows)


def _adapter(rows: list[list[Any]]) -> tuple[BinanceUsdmAdapter, _FakeRest]:
    sdk = _FakeSdk(rows)
    return BinanceUsdmAdapter(sdk_client=sdk), sdk.rest_api  # type: ignore[arg-type]


def _day_rows(day_start_ms: int, count: int = 1440) -> list[list[Any]]:
    """A dense day of well-formed mark rows shaped like the recorded sample."""
    rows: list[list[Any]] = []
    for i in range(count):
        o = day_start_ms + i * MINUTE_MS
        rows.append(
            [o, "100.5", "101.0", "100.0", "100.7", "0", o + MINUTE_MS - 1, "0", 30 + i % 3, "0", "0", "0"]
        )
    return rows


# --------------------------------------------------------------------------- #
# Row mapping.
# --------------------------------------------------------------------------- #


def test_row_maps_ohlc_times_and_price_tick_count() -> None:
    row = _sample_rows()[0]
    mk = _row_to_mark_kline("BTCUSDT", "1m", row)
    assert mk.open == Decimal("83751.55144203")
    assert mk.high == Decimal("83760.1")
    assert mk.low == Decimal("83740.0")
    assert mk.close == Decimal("83755.2")
    assert mk.price_tick_count == 60
    assert mk.open_time_utc == datetime(2026, 9, 30, 12, 7, tzinfo=UTC)
    assert mk.close_time_utc == mk.open_time_utc + timedelta(seconds=59, milliseconds=999)
    assert (mk.symbol, mk.interval) == ("BTCUSDT", "1m")


def test_mark_kline_has_no_volume_or_trade_count_field() -> None:
    names = {f.name for f in fields(MarkKline)}
    assert names == {
        "symbol",
        "interval",
        "open_time_utc",
        "close_time_utc",
        "open",
        "high",
        "low",
        "close",
        "price_tick_count",
    }


def test_short_row_raises_value_error() -> None:
    with pytest.raises(ValueError, match="too short"):
        _row_to_mark_kline("BTCUSDT", "1m", [1, "1", "1", "1", "1", "0", 2, "0"])


async def test_adapter_mark_klines_calls_sdk_once_and_returns_domain_types() -> None:
    adapter, rest = _adapter(_sample_rows())
    start = int(_sample_rows()[0][0])
    out = await adapter.mark_klines("BTCUSDT", "1m", start_ms=start, limit=1000)
    assert rest.calls == [
        {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "start_time": start,
            "end_time": None,
            "limit": 1000,
        }
    ]
    assert len(out) == 4
    assert all(type(m) is MarkKline for m in out)
    assert out[2].price_tick_count == 0


# --------------------------------------------------------------------------- #
# Frame schema and validator.
# --------------------------------------------------------------------------- #


def test_mark_frame_columns_are_exact() -> None:
    frame = mark_klines_to_frame([_mark(0)])
    assert frame.columns == MARK_COLUMNS
    assert frame.schema["price_tick_count"] == pl.Int64
    assert frame.schema["open"] == pl.Decimal(scale=8)
    empty = mark_klines_to_frame([])
    assert empty.columns == MARK_COLUMNS


def test_check_mark_batch_accepts_zero_price_tick_count_and_warns_on_gap() -> None:
    rows = [_mark(0, ticks=0), _mark(MINUTE_MS, ticks=0), _mark(3 * MINUTE_MS, ticks=5)]
    verdict = check_mark_batch(rows, "1m")
    assert verdict.structural_ok is True
    assert verdict.gap_count == 1


def test_check_mark_batch_rejects_structural_faults() -> None:
    good = [_mark(0), _mark(MINUTE_MS)]
    assert check_mark_batch(good, "1m").structural_ok is True

    dup = check_mark_batch([_mark(0), _mark(0)], "1m")
    assert not dup.structural_ok and dup.duplicates == 2

    ohlc = _mark(MINUTE_MS)
    bad = MarkKline(
        symbol=ohlc.symbol,
        interval=ohlc.interval,
        open_time_utc=ohlc.open_time_utc,
        close_time_utc=ohlc.close_time_utc,
        open=Decimal("100"),
        high=Decimal("99"),
        low=Decimal("98"),
        close=Decimal("100"),
        price_tick_count=1,
    )
    v = check_mark_batch([_mark(0), bad], "1m")
    assert not v.structural_ok and v.ohlc_violations == 1

    v = check_mark_batch([_mark(MINUTE_MS), _mark(0)], "1m")
    assert not v.structural_ok and v.timestamp_regressions == 1

    v = check_mark_batch([_mark(0, price="-1.00000000")], "1m")
    assert not v.structural_ok and v.negative_values == 1

    v = check_mark_batch([_mark(0, ticks=-1)], "1m")
    assert not v.structural_ok and v.negative_values == 1

    v = check_mark_batch([_mark(0, duration_ms=0)], "1m")
    assert not v.structural_ok and v.bad_durations == 1

    v = check_mark_batch([_mark(0), _mark(MINUTE_MS, symbol="ETHUSDT")], "1m")
    assert not v.structural_ok and v.mixed_keys == 1

    v = check_mark_batch([_mark(0, price="1.123456789")], "1m")
    assert not v.structural_ok and v.bad_decimals == 1


def test_check_mark_batch_rejects_unsupported_interval() -> None:
    with pytest.raises(ValueError, match="unsupported interval"):
        check_mark_batch([_mark(0)], "2m")


# --------------------------------------------------------------------------- #
# Publish + paginator.
# --------------------------------------------------------------------------- #


def test_publish_mark_batch_rejects_heterogeneous_batch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="heterogeneous"):
        publish_mark_batch(
            [_mark(0), _mark(MINUTE_MS, symbol="ETHUSDT")],
            interval="1m",
            symbol="BTCUSDT",
            raw_root=tmp_path,
        )


def test_publish_mark_batch_refuses_overwrite(tmp_path: Path) -> None:
    publish_mark_batch([_mark(0)], interval="1m", symbol="BTCUSDT", raw_root=tmp_path)
    with pytest.raises(FileExistsError):
        publish_mark_batch([_mark(MINUTE_MS)], interval="1m", symbol="BTCUSDT", raw_root=tmp_path)


def test_mark_dataset_dir_constant() -> None:
    assert MARK_DATASET_DIR == "dataset=mark_klines"


async def test_mark_backfill_publishes_to_mark_root_only(tmp_path: Path) -> None:
    day_start = 1790640000000 - (1790640000000 % DAY_MS)  # some closed UTC day
    adapter, rest = _adapter(_day_rows(day_start))
    clock_dt = _dt(day_start + DAY_MS + 3_600_000)

    result = await backfill_symbol_interval(
        adapter,
        symbol="BTCUSDT",
        interval="1m",
        start_ms=day_start,
        end_ms=day_start + DAY_MS,
        dataset=MARK_DATASET,
        raw_root=tmp_path,
        config=BackfillConfig(interval_ms=MINUTE_MS, pace_seconds=0),
        clock=lambda: clock_dt,
    )
    assert result.rows_published == 1440
    assert len(rest.calls) >= 2

    day = _dt(day_start).date().isoformat()
    part = (
        tmp_path
        / "dataset=mark_klines"
        / "interval=1m"
        / "symbol=BTCUSDT"
        / f"date={day}"
        / "part.parquet"
    )
    assert part.exists()
    frame = pl.read_parquet(part)
    assert frame.columns == MARK_COLUMNS
    assert frame.height == 1440
    # No mark file leaks into the trade partition root.
    assert not (tmp_path / "interval=1m").exists()


def test_mark_kline_parquet_has_no_volume_or_trade_count_column(tmp_path: Path) -> None:
    """D-20 / D-29: price-update count is never stored as volume or trade_count."""
    paths = publish_mark_batch(
        [_mark(0, ticks=7), _mark(MINUTE_MS, ticks=0)],
        interval="1m",
        symbol="BTCUSDT",
        raw_root=tmp_path,
    )
    assert len(paths) == 1
    assert "dataset=mark_klines" in paths[0].as_posix()
    frame = pl.read_parquet(paths[0])
    assert frame.columns == MARK_COLUMNS
    for forbidden in ("volume", "quote_volume", "trade_count"):
        assert forbidden not in frame.columns
    assert frame["price_tick_count"].to_list() == [7, 0]


async def test_trade_dataset_default_is_unchanged(tmp_path: Path) -> None:
    """Without a dataset argument the paginator still publishes trade klines."""
    day_start = 1790640000000 - (1790640000000 % DAY_MS)

    class _TradeSource:
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
            out: list[Kline] = []
            for i in range(24):
                o = day_start + i * 3_600_000
                if o < floor:
                    continue
                p = Decimal("100.00")
                out.append(
                    Kline(
                        symbol=symbol,
                        interval=interval,
                        open_time_utc=_dt(o),
                        close_time_utc=_dt(o + 3_600_000 - 1),
                        open=p,
                        high=p,
                        low=p,
                        close=p,
                        volume=Decimal("1"),
                        quote_volume=Decimal("100"),
                        trade_count=3,
                    )
                )
            return out[:limit]

    result = await backfill_symbol_interval(
        _TradeSource(),
        symbol="BTCUSDT",
        interval="1h",
        start_ms=day_start,
        end_ms=day_start + DAY_MS,
        raw_root=tmp_path,
        config=BackfillConfig(interval_ms=3_600_000, pace_seconds=0),
        clock=lambda: _dt(day_start + DAY_MS + 3_600_000),
    )
    assert result.rows_published == 24
    assert TRADE_DATASET.name == "trade"
    assert (tmp_path / "interval=1h" / "symbol=BTCUSDT").exists()
    assert not (tmp_path / "dataset=mark_klines").exists()


def test_cursor_store_default_dataset_is_trade(tmp_path: Path) -> None:
    assert CursorStore(root=tmp_path).dataset == "trade"
