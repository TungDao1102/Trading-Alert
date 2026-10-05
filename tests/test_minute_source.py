"""Tests for the lazy Parquet-backed MinuteSource (Phase 14, plan 14-10, D-13, D-31).

Every test publishes whole UTC days through the REAL immutable publishers
(`publish_batch`, `publish_mark_batch`) into `tmp_path`, so the source reads exactly
the layout production writes. The tracer at the bottom runs `engine.simulate` on the
lazy source and proves the dataset identity covers every file it opened.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from src.adapters.binance_usdm import Kline, MarkKline
from src.backtest.engine import simulate
from src.backtest.series import MinuteSeriesError
from src.data.case_input import dataset_identity
from src.data.minute_source import ParquetMinuteSource
from src.data.store import MARK_DATASET_DIR, partition_file, publish_batch, publish_mark_batch
from src.risk.gating import evaluate_risk

from tests.backtest_case_helpers import (
    constraint_row,
    funding_row,
    make_case,
    scripted_plan,
)

SYMBOL = "BTCUSDT"
DAY1 = datetime(2026, 7, 1, tzinfo=UTC)
DAY2 = datetime(2026, 7, 2, tzinfo=UTC)
DAY3 = datetime(2026, 7, 3, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
CLOSE_OFFSET = timedelta(seconds=59, milliseconds=999)

PriceFn = Callable[[datetime], tuple[Decimal, Decimal, Decimal, Decimal]]


def flat(open_time: datetime) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """open, high, low, close of a quiet minute: the price never nears the 100.00 limit."""
    base = Decimal(101) + Decimal((open_time.hour * 60 + open_time.minute) % 7) / Decimal(100)
    return base, base + Decimal("0.05"), base - Decimal("0.05"), base


def _minutes(start: datetime, end: datetime) -> list[datetime]:
    count = (end - start) // MINUTE
    return [start + MINUTE * i for i in range(count)]


def _trade(open_time: datetime, prices: PriceFn) -> Kline:
    o, h, lo, c = prices(open_time)
    return Kline(
        symbol=SYMBOL,
        interval="1m",
        open_time_utc=open_time,
        close_time_utc=open_time + CLOSE_OFFSET,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=Decimal("1.5"),
        quote_volume=c * Decimal("1.5"),
        trade_count=3,
    )


def _mark(open_time: datetime, prices: PriceFn) -> MarkKline:
    o, h, lo, c = prices(open_time)
    return MarkKline(
        symbol=SYMBOL,
        interval="1m",
        open_time_utc=open_time,
        close_time_utc=open_time + CLOSE_OFFSET,
        open=o,
        high=h,
        low=lo,
        close=c,
        price_tick_count=5,
    )


def publish_days(
    raw_root: Path,
    start: datetime,
    end: datetime,
    *,
    trade_prices: PriceFn = flat,
    mark_prices: PriceFn = flat,
    skip: frozenset[datetime] = frozenset(),
) -> None:
    opens = [m for m in _minutes(start, end) if m not in skip]
    publish_batch(
        [_trade(m, trade_prices) for m in opens], interval="1m", symbol=SYMBOL, raw_root=raw_root
    )
    publish_mark_batch(
        [_mark(m, mark_prices) for m in opens], interval="1m", symbol=SYMBOL, raw_root=raw_root
    )


def make_source(raw_root: Path, **overrides: object) -> ParquetMinuteSource:
    kwargs: dict[str, object] = {
        "symbols": [SYMBOL],
        "start_utc": DAY1,
        "end_utc": DAY3,
        "cache_days": 4,
    }
    kwargs.update(overrides)
    return ParquetMinuteSource(raw_root, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def two_days(tmp_path: Path) -> Path:
    root = tmp_path / "raw"
    publish_days(root, DAY1, DAY3)
    return root


# --------------------------------------------------------------------------- #
# Values, windows and the lazy day selection.
# --------------------------------------------------------------------------- #


def test_trade_minutes_match_the_published_source_values(two_days: Path) -> None:
    source = make_source(two_days)
    start = DAY1 + timedelta(hours=10)
    end = DAY1 + timedelta(hours=10, minutes=5)
    candles = source.trade_minutes(SYMBOL, start, end)
    # Close in (start, end]: the minute opened 10:00 closes 10:00:59.999 > start; the
    # minute opened 10:04 closes 10:04:59.999 <= 10:05:00; the 10:05 minute closes later.
    assert [c.open_time_utc for c in candles] == [start + MINUTE * i for i in range(5)]
    for candle in candles:
        o, h, lo, c = flat(candle.open_time_utc)
        assert (candle.open, candle.high, candle.low, candle.close) == (o, h, lo, c)
        assert candle.volume == Decimal("1.5")
        assert candle.symbol == SYMBOL and candle.interval == "1m"
        assert candle.close_time_utc == candle.open_time_utc + CLOSE_OFFSET
    closes = [c.close_time_utc for c in candles]
    assert closes == sorted(closes)
    assert all(start < t <= end for t in closes)


def test_mark_minutes_carry_zero_volume_and_mark_prices(tmp_path: Path) -> None:
    def mark_prices(open_time: datetime) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return Decimal("50"), Decimal("51"), Decimal("49"), Decimal("50.5")

    root = tmp_path / "raw"
    publish_days(root, DAY1, DAY2, mark_prices=mark_prices)
    source = make_source(root, end_utc=DAY2)
    candles = source.mark_minutes(SYMBOL, DAY1, DAY1 + timedelta(minutes=2))
    assert len(candles) == 2
    assert all(c.close == Decimal("50.5") and c.volume == Decimal("0") for c in candles)
    # Mark partitions live under the mark dataset directory, never the trade root.
    assert (root / MARK_DATASET_DIR).is_dir()
    trade = source.trade_minutes(SYMBOL, DAY1, DAY1 + timedelta(minutes=2))
    assert trade[0].close != Decimal("50.5")


def test_a_window_inside_day_one_opens_only_day_one_files(two_days: Path) -> None:
    source = make_source(two_days)
    assert source.files_read() == ()
    source.trade_minutes(SYMBOL, DAY1 + timedelta(hours=3), DAY1 + timedelta(hours=4))
    assert source.files_read() == (partition_file(two_days, "1m", SYMBOL, DAY1.date()),)

    source.mark_minutes(SYMBOL, DAY1 + timedelta(hours=3), DAY1 + timedelta(hours=4))
    mark_root = two_days / MARK_DATASET_DIR
    assert source.files_read() == (
        partition_file(two_days, "1m", SYMBOL, DAY1.date()),
        partition_file(mark_root, "1m", SYMBOL, DAY1.date()),
    )

    # A later window that spans midnight adds day two, in first-opened order.
    source.trade_minutes(SYMBOL, DAY2 - timedelta(hours=1), DAY2 + timedelta(hours=1))
    assert partition_file(two_days, "1m", SYMBOL, DAY2.date()) in source.files_read()
    assert len(source.files_read()) == 3


def test_a_window_spanning_midnight_is_continuous_and_ascending(two_days: Path) -> None:
    source = make_source(two_days)
    start = DAY2 - timedelta(minutes=2)
    candles = source.trade_minutes(SYMBOL, start, DAY2 + timedelta(minutes=2))
    opens = [c.open_time_utc for c in candles]
    assert opens == [start + MINUTE * i for i in range(4)]


def test_days_outside_the_configured_range_are_never_opened(two_days: Path) -> None:
    source = make_source(two_days, start_utc=DAY2, end_utc=DAY3)
    assert source.trade_minutes(SYMBOL, DAY1, DAY1 + timedelta(hours=1)) == ()
    assert source.files_read() == ()


# --------------------------------------------------------------------------- #
# Validation on first touch, holes and the LRU.
# --------------------------------------------------------------------------- #


def test_a_missing_minute_stays_a_hole_and_is_never_padded(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    hole = DAY1 + timedelta(hours=10, minutes=30)
    publish_days(root, DAY1, DAY2, skip=frozenset({hole}))
    source = make_source(root, end_utc=DAY2)
    candles = source.trade_minutes(
        SYMBOL, DAY1 + timedelta(hours=10), DAY1 + timedelta(hours=11)
    )
    opens = {c.open_time_utc for c in candles}
    assert len(candles) == 59
    assert hole not in opens


def test_a_duplicated_minute_raises_on_first_touch(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    publish_days(root, DAY1, DAY3)
    path = partition_file(root, "1m", SYMBOL, DAY2.date())
    frame = pl.read_parquet(path)
    duplicated = pl.concat([frame, frame.head(1)], how="vertical")
    path.unlink()
    duplicated.write_parquet(path)

    source = make_source(root)
    # Day one is clean and readable.
    assert source.trade_minutes(SYMBOL, DAY1, DAY1 + timedelta(hours=1))
    with pytest.raises(MinuteSeriesError, match="duplicate|decreases|overlaps"):
        source.trade_minutes(SYMBOL, DAY2, DAY2 + timedelta(hours=1))


def test_an_out_of_order_day_file_is_refused_not_sorted(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    publish_days(root, DAY1, DAY2)
    path = partition_file(root, "1m", SYMBOL, DAY1.date())
    frame = pl.read_parquet(path).reverse()
    path.unlink()
    frame.write_parquet(path)
    source = make_source(root, end_utc=DAY2)
    with pytest.raises(MinuteSeriesError):
        source.trade_minutes(SYMBOL, DAY1, DAY1 + timedelta(hours=1))


def test_a_row_dated_outside_its_partition_day_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    publish_days(root, DAY1, DAY3)
    # Day two's file holds day one's rows: wrong partition content.
    day1 = partition_file(root, "1m", SYMBOL, DAY1.date())
    day2 = partition_file(root, "1m", SYMBOL, DAY2.date())
    content = pl.read_parquet(day1)
    day2.unlink()
    content.write_parquet(day2)
    source = make_source(root)
    with pytest.raises(MinuteSeriesError, match="partition"):
        source.trade_minutes(SYMBOL, DAY2, DAY2 + timedelta(hours=1))


def test_cache_of_one_day_rereads_files_but_returns_identical_results(two_days: Path) -> None:
    big = make_source(two_days, cache_days=4)
    small = make_source(two_days, cache_days=1)
    windows = [
        (DAY1 + timedelta(hours=2), DAY1 + timedelta(hours=3)),
        (DAY2 + timedelta(hours=2), DAY2 + timedelta(hours=3)),
        (DAY1 + timedelta(hours=5), DAY1 + timedelta(hours=6)),
        (DAY2 + timedelta(hours=5), DAY2 + timedelta(hours=6)),
    ]
    for start, end in windows:
        assert small.trade_minutes(SYMBOL, start, end) == big.trade_minutes(SYMBOL, start, end)
    assert big.loads == 2
    assert small.loads == 4
    # Re-reads open the same two files; the identity input does not grow.
    assert len(small.files_read()) == 2
    assert small.files_read() == big.files_read()


def test_cache_days_must_be_positive(two_days: Path) -> None:
    with pytest.raises(ValueError, match="cache_days"):
        make_source(two_days, cache_days=0)


# --------------------------------------------------------------------------- #
# Path safety (T-14-19).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", ["../BTCUSDT", "btcusdt", "BTCUSDT/..", "BTC", ""])
def test_unsafe_symbols_are_refused_before_any_path_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    from src.data import minute_source as module

    def no_paths(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("a path was built for an unsafe symbol")

    monkeypatch.setattr(module, "partition_file", no_paths)
    with pytest.raises(MinuteSeriesError):
        ParquetMinuteSource(tmp_path, symbols=[bad], start_utc=DAY1, end_utc=DAY2)


def test_a_symbol_outside_the_constructor_list_is_refused(two_days: Path) -> None:
    source = make_source(two_days)
    with pytest.raises(MinuteSeriesError):
        source.trade_minutes("ETHUSDT", DAY1, DAY1 + timedelta(hours=1))
    with pytest.raises(MinuteSeriesError):
        source.mark_minutes("../BTCUSDT", DAY1, DAY1 + timedelta(hours=1))
    assert source.files_read() == ()


def test_a_day_with_no_partition_is_an_empty_hole(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    publish_days(root, DAY1, DAY2)
    source = make_source(root)  # range covers day two, which was never published
    assert source.trade_minutes(SYMBOL, DAY2, DAY2 + timedelta(hours=1)) == ()
    assert source.files_read() == ()


# --------------------------------------------------------------------------- #
# Tracer: the engine runs on published partitions through the lazy source.
# --------------------------------------------------------------------------- #

SIGNAL_CLOSE = datetime(2026, 7, 1, 9, 59, 59, 999000, tzinfo=UTC)
FILL_MINUTE = datetime(2026, 7, 1, 10, 1, tzinfo=UTC)
STOP_MINUTE = datetime(2026, 7, 1, 10, 40, tzinfo=UTC)


def tracer_trade_prices(open_time: datetime) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Quiet, except the 10:01 minute trades through the 100.00 limit."""
    if open_time == FILL_MINUTE:
        return Decimal("100.20"), Decimal("100.30"), Decimal("99.80"), Decimal("100.00")
    return Decimal("100.60"), Decimal("100.70"), Decimal("100.40"), Decimal("100.60")


def tracer_mark_prices(open_time: datetime) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Mark sits at 100.00; the 10:40 minute breaks the 98.00 stop."""
    if open_time == STOP_MINUTE:
        return Decimal("98.50"), Decimal("98.60"), Decimal("97.90"), Decimal("98.20")
    return Decimal("100.00"), Decimal("100.05"), Decimal("99.95"), Decimal("100.00")


def tracer_case() -> dict[str, object]:
    instants = [DAY1 + timedelta(hours=h) for h in (0, 8, 16, 24, 32)]
    case = make_case(
        symbols=[SYMBOL],
        scripted=[scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-1")],
        funding=[funding_row(SYMBOL, when) for when in instants],
        constraints=[constraint_row(SYMBOL, datetime(2026, 6, 1, tzinfo=UTC))],
        data_start=DAY1,
        data_end=DAY3,
    )
    del case["trade_bars_1m"]
    del case["mark_bars_1m"]
    return case


def test_tracer_engine_runs_on_published_partitions_and_identity_is_stable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw"
    publish_days(root, DAY1, DAY3, trade_prices=tracer_trade_prices, mark_prices=tracer_mark_prices)

    identities: list[str] = []
    outputs: list[dict[str, object]] = []
    for _ in range(2):
        source = make_source(root)
        output = simulate(tracer_case(), risk_fn=evaluate_risk, minute_source=source)
        outputs.append(output)
        files = source.files_read()
        assert files, "the engine must have opened at least one partition"
        assert all(root in path.parents for path in files)
        identities.append(dataset_identity(root, files))

    assert identities[0] == identities[1]
    assert len(identities[0]) == 64
    assert outputs[0] == outputs[1]

    trades = outputs[0]["trades"]
    assert isinstance(trades, list) and len(trades) == 1
    trade = trades[0]
    assert trade["entry_kind"] == "ENTRY_FILLED"
    assert trade["exit_kind"] == "SL"
    assert Decimal(trade["entry_price"]) == Decimal("100.00")
    assert Decimal(trade["exit_price"]) == Decimal("98.00")
    assert Decimal(trade["quantity"]) == Decimal("15.928")
    # The day the trade lives on is the only trade partition the engine needed to fill it.
    day1_trade = partition_file(root, "1m", SYMBOL, DAY1.date())
    assert day1_trade in source.files_read()


def test_dataset_identity_changes_when_an_opened_minute_partition_changes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw"
    publish_days(root, DAY1, DAY3, trade_prices=tracer_trade_prices, mark_prices=tracer_mark_prices)
    source = make_source(root)
    simulate(tracer_case(), risk_fn=evaluate_risk, minute_source=source)
    before = dataset_identity(root, source.files_read())

    day1_mark = partition_file(root / MARK_DATASET_DIR, "1m", SYMBOL, DAY1.date())
    assert day1_mark in source.files_read()
    frame = pl.read_parquet(day1_mark)
    day1_mark.unlink()
    frame.with_columns(pl.col("price_tick_count") + 1).write_parquet(day1_mark)
    assert dataset_identity(root, source.files_read()) != before
