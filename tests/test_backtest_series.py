"""Minute-series validation and the lazy `MinuteSource` contract (Phase 14, plan 14-01, D-13).

Series are validated on load: strictly increasing, minute-aligned, no duplicate or
overlapping minutes. Holes stay explicit and are never padded; minutes are selected
by close time in the half-open window `(start_exclusive, end_inclusive]`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.backtest.series import (
    ListMinuteSource,
    MinuteSeriesError,
    parse_minute_row,
    validate_minute_series,
)
from src.core.types import Candle

from tests.backtest_plan_helpers import make_minute

SYMBOL = "BTCUSDT"


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 1, 5, hour, minute, second, tzinfo=UTC)


def _m(hour: int, minute: int, *, kind: str = "trade") -> Candle:
    return make_minute(SYMBOL, _at(hour, minute), "100.00", "100.50", "99.50", "100.20", kind)


def test_duplicate_open_time_raises() -> None:
    with pytest.raises(MinuteSeriesError, match="duplicate"):
        validate_minute_series([_m(10, 0), _m(10, 0)], symbol=SYMBOL, kind="trade")


def test_decreasing_open_time_raises() -> None:
    with pytest.raises(MinuteSeriesError, match="decreas"):
        validate_minute_series([_m(10, 1), _m(10, 0)], symbol=SYMBOL, kind="trade")


def test_open_time_not_aligned_to_a_whole_minute_raises() -> None:
    off_grid = Candle(
        symbol=SYMBOL,
        interval="1m",
        open_time_utc=_at(10, 0, 30),
        close_time_utc=_at(10, 0, 59),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    with pytest.raises(MinuteSeriesError, match="aligned"):
        validate_minute_series([off_grid], symbol=SYMBOL, kind="trade")


def test_close_time_not_strictly_inside_the_minute_raises() -> None:
    full_minute = Candle(
        symbol=SYMBOL,
        interval="1m",
        open_time_utc=_at(10, 0),
        close_time_utc=_at(10, 1),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    with pytest.raises(MinuteSeriesError, match="close"):
        validate_minute_series([full_minute], symbol=SYMBOL, kind="trade")


def test_overlapping_minute_raises() -> None:
    half_step = Candle(
        symbol=SYMBOL,
        interval="1m",
        open_time_utc=_at(10, 0, 30),
        close_time_utc=_at(10, 0, 59),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    with pytest.raises(MinuteSeriesError, match="overlap"):
        validate_minute_series([_m(10, 0), half_step], symbol=SYMBOL, kind="trade")


def test_symbol_and_interval_mismatch_raise() -> None:
    other = make_minute("ETHUSDT", _at(10, 0), "1", "2", "1", "1", "trade")
    with pytest.raises(MinuteSeriesError, match="symbol"):
        validate_minute_series([other], symbol=SYMBOL, kind="trade")
    five_minute = Candle(
        symbol=SYMBOL,
        interval="5m",
        open_time_utc=_at(10, 0),
        close_time_utc=_at(10, 0, 59),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    with pytest.raises(MinuteSeriesError, match="interval"):
        validate_minute_series([five_minute], symbol=SYMBOL, kind="trade")


def test_list_source_validates_at_construction() -> None:
    with pytest.raises(MinuteSeriesError):
        ListMinuteSource(trade={SYMBOL: [_m(10, 1), _m(10, 0)]}, mark={SYMBOL: [_m(10, 0)]})


def test_a_hole_validates_and_stays_absent_from_both_windows() -> None:
    trade = [_m(10, 0), _m(10, 1), _m(10, 3)]
    mark = [_m(10, 0, kind="mark"), _m(10, 2, kind="mark"), _m(10, 3, kind="mark")]
    source = ListMinuteSource(trade={SYMBOL: trade}, mark={SYMBOL: mark})
    start = _at(9, 59, 59)
    end = _at(10, 5)
    assert [c.open_time_utc for c in source.trade_minutes(SYMBOL, start, end)] == [
        _at(10, 0),
        _at(10, 1),
        _at(10, 3),
    ]
    assert [c.open_time_utc for c in source.mark_minutes(SYMBOL, start, end)] == [
        _at(10, 0),
        _at(10, 2),
        _at(10, 3),
    ]


def test_window_is_half_open_on_the_close_time() -> None:
    minutes = [_m(10, 0), _m(10, 1), _m(10, 2)]
    source = ListMinuteSource(trade={SYMBOL: minutes}, mark={SYMBOL: minutes})
    first_close = minutes[0].close_time_utc
    second_close = minutes[1].close_time_utc
    got = source.trade_minutes(SYMBOL, first_close, second_close)
    assert [c.open_time_utc for c in got] == [_at(10, 1)]  # start excluded, end included
    assert list(source.trade_minutes(SYMBOL, second_close, second_close)) == []


def test_unknown_symbol_is_a_data_error_not_an_empty_window() -> None:
    source = ListMinuteSource(trade={SYMBOL: [_m(10, 0)]}, mark={SYMBOL: [_m(10, 0, kind="mark")]})
    with pytest.raises(MinuteSeriesError, match="ETHUSDT"):
        source.trade_minutes("ETHUSDT", _at(9, 0), _at(11, 0))
    with pytest.raises(MinuteSeriesError, match="ETHUSDT"):
        source.mark_minutes("ETHUSDT", _at(9, 0), _at(11, 0))


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": SYMBOL,
        "interval": "1m",
        "open_time_utc": "2026-01-05T10:00:00+00:00",
        "close_time_utc": "2026-01-05T10:00:59.999000+00:00",
        "open": "100.00",
        "high": "100.50",
        "low": "99.50",
        "close": "100.20",
        "volume": "12.5",
    }
    row.update(overrides)
    return row


def test_parse_minute_row_rejects_float_values() -> None:
    with pytest.raises(TypeError, match="float"):
        parse_minute_row(_row(low=99.5), kind="trade")
    with pytest.raises(TypeError, match="float"):
        parse_minute_row(_row(volume=12.5), kind="trade")


def test_parse_minute_row_rejects_naive_datetimes() -> None:
    with pytest.raises(MinuteSeriesError, match="open_time_utc"):
        parse_minute_row(_row(open_time_utc="2026-01-05T10:00:00"), kind="trade")
    with pytest.raises(MinuteSeriesError, match="close_time_utc"):
        parse_minute_row(_row(close_time_utc=datetime(2026, 1, 5, 10, 0, 59)), kind="trade")


def test_mark_row_without_volume_parses_with_zero_volume() -> None:
    row = _row()
    del row["volume"]
    candle = parse_minute_row(row, kind="mark")
    assert candle.volume == Decimal("0")
    assert candle.low == Decimal("99.50")
    assert candle.close_time_utc - candle.open_time_utc == timedelta(seconds=59, milliseconds=999)


def test_trade_row_without_volume_raises() -> None:
    row = _row()
    del row["volume"]
    with pytest.raises(MinuteSeriesError, match="volume"):
        parse_minute_row(row, kind="trade")
