"""Pinned Parquet Decimal schema and mixed-scale tolerant readers (CR-03).

Polars infers a Decimal column's scale from the batch's own values, so before
the writer pinned `Decimal(38, 8)` two partitions of one key could carry
different types and a multi-file read raised `SchemaError`. Synthetic data only
(`tmp_path`); nothing here touches the real raw store.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from src.adapters.binance_usdm import Kline, MarkKline
from src.data.case_input import _read_rows
from src.data.quality import PRICE_DECIMAL, klines_to_frame, mark_klines_to_frame
from src.data.store import publish_batch, publish_mark_batch, read_partitions

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY0 = datetime(2023, 11, 14, tzinfo=UTC)
_PRICE_COLUMNS = ("open", "high", "low", "close", "volume", "quote_volume")


def _kline(open_time: datetime, *, price: str, volume: str, quote_volume: str) -> Kline:
    p = Decimal(price)
    return Kline(
        symbol="BTCUSDT",
        interval="1h",
        open_time_utc=open_time,
        close_time_utc=open_time + HOUR - timedelta(milliseconds=1),
        open=p,
        high=p,
        low=p,
        close=p,
        volume=Decimal(volume),
        quote_volume=Decimal(quote_volume),
        trade_count=3,
    )


def _day(day_offset: int, *, price: str, volume: str, quote_volume: str) -> list[Kline]:
    start = DAY0 + timedelta(days=day_offset)
    return [
        _kline(start + i * HOUR, price=price, volume=volume, quote_volume=quote_volume)
        for i in range(24)
    ]


def test_trade_frame_pins_every_price_and_volume_column_to_decimal_38_8() -> None:
    # Scale-0, scale-1 and scale-2 inputs: inference would give three schemas.
    frames = [
        klines_to_frame(_day(0, price="100", volume="5", quote_volume="500")),
        klines_to_frame(_day(1, price="100.5", volume="5.5", quote_volume="502.5")),
        klines_to_frame(_day(2, price="100.25", volume="5.25", quote_volume="505.25")),
        klines_to_frame([]),
    ]

    for frame in frames:
        for column in _PRICE_COLUMNS:
            assert frame.schema[column] == PRICE_DECIMAL, column
    assert len({tuple(f.schema.items()) for f in frames}) == 1
    assert frames[1]["volume"][0] == Decimal("5.50000000")


def test_mark_frame_pins_price_columns_to_decimal_38_8() -> None:
    def _mark(price: str) -> MarkKline:
        p = Decimal(price)
        return MarkKline(
            symbol="BTCUSDT",
            interval="1m",
            open_time_utc=DAY0,
            close_time_utc=DAY0 + timedelta(minutes=1) - timedelta(milliseconds=1),
            open=p,
            high=p,
            low=p,
            close=p,
            price_tick_count=4,
        )

    frames = [mark_klines_to_frame([_mark("100")]), mark_klines_to_frame([_mark("100.1234567")])]

    for frame in frames:
        for column in ("open", "high", "low", "close"):
            assert frame.schema[column] == PRICE_DECIMAL, column
    assert frames[0].schema == frames[1].schema


def test_every_published_file_has_an_identical_schema(tmp_path: Path) -> None:
    publish_batch(
        _day(0, price="100", volume="5", quote_volume="500"),
        interval="1h",
        symbol="BTCUSDT",
        raw_root=tmp_path,
    )
    publish_batch(
        _day(1, price="100.5", volume="5.5", quote_volume="502.5"),
        interval="1h",
        symbol="BTCUSDT",
        raw_root=tmp_path,
    )

    files = sorted(tmp_path.rglob("part.parquet"))
    assert len(files) == 2
    schemas = {tuple(pl.read_parquet_schema(f).items()) for f in files}
    assert len(schemas) == 1
    # The plain multi-file read that used to raise SchemaError now works.
    assert pl.read_parquet([str(f) for f in files], hive_partitioning=False).height == 48


def test_published_mark_files_share_one_schema(tmp_path: Path) -> None:
    def _mark_day(day_offset: int, price: str) -> list[MarkKline]:
        start = DAY0 + timedelta(days=day_offset)
        p = Decimal(price)
        return [
            MarkKline(
                symbol="BTCUSDT",
                interval="1m",
                open_time_utc=start + timedelta(minutes=i),
                close_time_utc=start + timedelta(minutes=i + 1) - timedelta(milliseconds=1),
                open=p,
                high=p,
                low=p,
                close=p,
                price_tick_count=1,
            )
            for i in range(60)
        ]

    publish_mark_batch(_mark_day(0, "100"), interval="1m", symbol="BTCUSDT", raw_root=tmp_path)
    publish_mark_batch(
        _mark_day(1, "100.12345678"), interval="1m", symbol="BTCUSDT", raw_root=tmp_path
    )

    files = sorted(tmp_path.rglob("part.parquet"))
    assert len({tuple(pl.read_parquet_schema(f).items()) for f in files}) == 1


def _legacy_partition(path: Path, *, scale: int, volume_scale: int, day_offset: int) -> None:
    """Write a partition the way the old (inferred-scale) writer did."""
    start = DAY0 + timedelta(days=day_offset)
    price = Decimal(1).scaleb(-scale) * 15
    frame = pl.DataFrame(
        {
            "open_time_utc": [start, start + HOUR],
            "close_time_utc": [start + HOUR, start + 2 * HOUR],
            "open": [price, price],
            "volume": [Decimal(1).scaleb(-volume_scale) * 7] * 2,
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "interval": ["1h", "1h"],
        }
    )
    path.parent.mkdir(parents=True)
    frame.write_parquet(path)


def test_read_partitions_widens_mixed_legacy_scales_without_losing_value(
    tmp_path: Path,
) -> None:
    a = tmp_path / "date=2023-11-14" / "part.parquet"
    b = tmp_path / "date=2023-11-15" / "part.parquet"
    _legacy_partition(a, scale=7, volume_scale=0, day_offset=0)
    _legacy_partition(b, scale=8, volume_scale=2, day_offset=1)

    with pytest.raises(pl.exceptions.SchemaError):
        pl.read_parquet([str(a), str(b)], hive_partitioning=False)

    columns = ["open_time_utc", "open", "volume", "symbol"]
    widened = read_partitions([a, b], columns)
    assert widened.height == 4
    assert widened.schema["open"] == pl.Decimal(38, 8)
    assert widened.schema["volume"] == pl.Decimal(38, 2)
    assert widened["open"].to_list() == [
        Decimal("0.0000015"),
        Decimal("0.0000015"),
        Decimal("0.00000015"),
        Decimal("0.00000015"),
    ]

    pinned = read_partitions([a, b], columns, pin_price_scale=True)
    assert pinned.schema["open"] == pl.Decimal(38, 8)
    assert pinned.schema["volume"] == pl.Decimal(38, 8)
    assert pinned["volume"].to_list() == [Decimal(7)] * 2 + [Decimal("0.07")] * 2


def test_read_partitions_never_narrows_a_wider_scale(tmp_path: Path) -> None:
    """A funding-style scale-10 column keeps all ten digits (no pin)."""
    path = tmp_path / "part.parquet"
    pl.DataFrame({"funding_rate": [Decimal("0.0001234567")]}).write_parquet(path)

    frame = read_partitions([path], ["funding_rate"])

    assert frame.schema["funding_rate"] == pl.Decimal(38, 10)
    assert frame["funding_rate"][0] == Decimal("0.0001234567")


def test_case_input_reader_survives_mixed_scale_partitions(tmp_path: Path) -> None:
    a = tmp_path / "date=2023-11-14" / "part.parquet"
    b = tmp_path / "date=2023-11-15" / "part.parquet"
    _legacy_partition(a, scale=7, volume_scale=1, day_offset=0)
    _legacy_partition(b, scale=8, volume_scale=2, day_offset=1)

    rows = _read_rows(
        [b, a],
        ["open_time_utc", "open", "volume", "symbol", "interval"],
        "open_time_utc",
        symbol="BTCUSDT",
        interval="1h",
        pin_price_scale=True,
    )

    assert [r["open"] for r in rows] == [
        "0.00000150",
        "0.00000150",
        "0.00000015",
        "0.00000015",
    ]
    assert rows[0]["volume"] == "0.70000000"


def test_repair_script_is_dry_run_by_default_and_writes_pinned_copies(
    tmp_path: Path,
) -> None:
    from scripts.repair_parquet_scale import find_deviations, main, repair_copies

    raw = tmp_path / "raw"
    legacy = raw / "interval=1h" / "symbol=BTCUSDT" / "date=2023-11-14" / "part.parquet"
    _legacy_partition(legacy, scale=7, volume_scale=0, day_offset=0)
    before = legacy.read_bytes()

    assert [d.path for d in find_deviations(raw)] == [legacy]
    assert main(["--raw-root", str(raw)]) == 0  # dry run
    assert legacy.read_bytes() == before

    out = tmp_path / "repaired"
    with pytest.raises(ValueError):
        repair_copies(raw, raw / "inside")
    written, skipped = repair_copies(raw, out)

    assert (written, skipped) == (1, [])
    assert legacy.read_bytes() == before  # the input is never touched
    copy = out / legacy.relative_to(raw)
    assert pl.read_parquet_schema(copy)["open"] == PRICE_DECIMAL
    assert pl.read_parquet(copy, hive_partitioning=False)["open"][0] == Decimal("0.0000015")
    assert find_deviations(out) == []
