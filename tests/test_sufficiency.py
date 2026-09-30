"""Data-sufficiency report (Phase 13, plan 13-08; D-05, D-21).

Pure tests over tmp stores built with the real publishers: the report compares
the bars a window expects with the bars actually stored, names a cause per
(dataset, symbol, interval) and never estimates a trade count. No network.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_usdm import Kline, MarkKline
from src.data.store import publish_batch, publish_mark_batch

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
RUN_DATE = date(2026, 9, 30)
_STEP_MS = {"1m": 60_000, "1h": HOUR_MS, "4h": 4 * HOUR_MS}


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    delta = datetime(year, month, day, hour, minute, tzinfo=UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000


def _dt(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


def _kline(
    symbol: str, interval: str, open_ms: int, *, flat: bool = False
) -> Kline:
    step = _STEP_MS[interval]
    price = Decimal("100.00")
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_dt(open_ms),
        close_time_utc=_dt(open_ms + step - 1),
        open=price,
        high=price if flat else Decimal("101.00"),
        low=price if flat else Decimal("99.00"),
        close=price,
        volume=Decimal("0") if flat else Decimal("1.0"),
        quote_volume=Decimal("0") if flat else Decimal("100.00"),
        trade_count=0 if flat else 10,
    )


def _publish_trade(
    raw: Path,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    *,
    skip_days: Sequence[int] = (),
    flat_from_ms: int | None = None,
) -> None:
    step = _STEP_MS[interval]
    rows = [
        _kline(symbol, interval, open_ms, flat=flat_from_ms is not None and open_ms >= flat_from_ms)
        for open_ms in range(start_ms, end_ms, step)
        if open_ms - open_ms % DAY_MS not in skip_days
    ]
    publish_batch(rows, interval=interval, symbol=symbol, raw_root=raw)


def _publish_mark(raw: Path, symbol: str, interval: str, start_ms: int, end_ms: int) -> None:
    step = _STEP_MS[interval]
    price = Decimal("100.00000000")
    rows = [
        MarkKline(
            symbol=symbol,
            interval=interval,
            open_time_utc=_dt(open_ms),
            close_time_utc=_dt(open_ms + step - 1),
            open=price,
            high=price,
            low=price,
            close=price,
            price_tick_count=60,
        )
        for open_ms in range(start_ms, end_ms, step)
    ]
    publish_mark_batch(rows, interval=interval, symbol=symbol, raw_root=raw)


def _window(
    symbol: str = "BTCUSDT",
    *,
    dataset: str = "trade",
    interval: str = "1h",
    start_ms: int | None = _ms(2026, 9, 27),
    end_ms: int | None = _ms(2026, 9, 30),
    terminal: bool = False,
    cause: str = "FULL_DEPTH",
) -> Any:
    from src.data.backfill_cli import SymbolWindow

    return SymbolWindow(
        dataset=dataset,
        symbol=symbol,
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
        terminal=terminal,
        cause=cause,
    )


def _report(raw: Path, windows: Sequence[Any], **overrides: Any) -> Any:
    from src.data.sufficiency import build_sufficiency_report

    params: dict[str, Any] = {
        "run_date": RUN_DATE,
        "depth_months": {"1h": 24},
        "dataset_start": date(2024, 9, 30),
        "dataset_end": RUN_DATE,
        "sources": {},
    }
    params.update(overrides)
    return build_sufficiency_report(raw, list(windows), **params)


# --------------------------------------------------------------------------- #
# Task 1 - expected bars, causes and the report file.
# --------------------------------------------------------------------------- #


def test_expected_bar_count_is_step_aligned() -> None:
    from src.data.sufficiency import expected_bar_count

    four_h = 4 * HOUR_MS
    # 07:00Z to the next midnight: bars open 08:00, 12:00, 16:00, 20:00.
    assert expected_bar_count(_ms(2026, 9, 1, 7), _ms(2026, 9, 2), four_h) == 4
    assert expected_bar_count(_ms(2026, 9, 1), _ms(2026, 9, 2), HOUR_MS) == 24
    assert expected_bar_count(_ms(2026, 9, 2), _ms(2026, 9, 2), HOUR_MS) == 0
    assert expected_bar_count(_ms(2026, 9, 3), _ms(2026, 9, 2), HOUR_MS) == 0


def test_complete_store_reports_ok(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _publish_trade(raw, "BTCUSDT", "1h", _ms(2026, 9, 27), _ms(2026, 9, 30))

    report = _report(raw, [_window()])

    (row,) = report.rows
    assert row.cause == "OK"
    assert (row.expected_bars, row.have_bars, row.missing_bars) == (72, 72, 0)
    assert row.gaps == ()
    assert row.source == "REST"
    assert report.missing_data is False


def test_missing_day_is_a_gap_with_the_builders_gap_definition(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    skipped = _ms(2026, 9, 28)
    _publish_trade(raw, "BTCUSDT", "1h", _ms(2026, 9, 27), _ms(2026, 9, 30), skip_days=[skipped])

    report = _report(raw, [_window()])

    (row,) = report.rows
    assert row.cause == "GAP"
    assert row.missing_bars == 24
    (gap,) = row.gaps
    assert gap.start_utc == _dt(skipped)
    assert gap.end_utc == _dt(_ms(2026, 9, 29))
    assert gap.missing == 24
    assert report.missing_data is True


@pytest.mark.parametrize(
    ("window_cause", "terminal", "expected_cause"),
    [
        ("ONBOARD_LIMITED", False, "ONBOARD_LIMITED"),
        ("DELISTED_CAPPED", True, "DELISTED_CAPPED"),
    ],
)
def test_informational_causes_with_complete_data_are_not_missing(
    tmp_path: Path, window_cause: str, terminal: bool, expected_cause: str
) -> None:
    raw = tmp_path / "raw"
    _publish_trade(raw, "BTCUSDT", "1h", _ms(2026, 9, 27), _ms(2026, 9, 30))

    report = _report(raw, [_window(cause=window_cause, terminal=terminal)])

    (row,) = report.rows
    assert row.cause == expected_cause
    assert row.missing_bars == 0
    assert report.missing_data is False


def test_unbounded_causes_map_to_no_window_and_unavailable(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    windows = [
        _window("SOONUSDT", start_ms=None, end_ms=None, cause="NOT_LISTED_IN_RANGE"),
        _window("OLDUSDT", start_ms=None, end_ms=None, cause="DELIVERY_UNKNOWN"),
        _window("GONEUSDT", start_ms=None, end_ms=None, cause="DELISTED_CAPPED", terminal=True),
    ]

    report = _report(raw, windows)

    causes = {r.symbol: r.cause for r in report.rows}
    assert causes == {
        "SOONUSDT": "NO_WINDOW",
        "OLDUSDT": "UNAVAILABLE",
        "GONEUSDT": "DELISTED_CAPPED",
    }
    assert all(r.expected_bars == 0 for r in report.rows)
    assert report.missing_data is True  # OLDUSDT only


def test_window_with_no_stored_bars_is_not_backfilled(tmp_path: Path) -> None:
    report = _report(tmp_path / "raw", [_window()])

    (row,) = report.rows
    assert row.cause == "NOT_BACKFILLED"
    assert (row.expected_bars, row.have_bars, row.missing_bars) == (72, 0, 72)
    assert report.missing_data is True


def test_unavailable_source_wins_over_a_window(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _publish_mark(raw, "BTCUSDT", "1h", _ms(2026, 9, 27), _ms(2026, 9, 30))

    report = _report(
        raw,
        [_window(dataset="mark")],
        sources={("mark", "BTCUSDT"): "UNAVAILABLE"},
    )

    (row,) = report.rows
    assert row.cause == "UNAVAILABLE"
    assert row.source == "UNAVAILABLE"
    assert report.missing_data is True


def test_mark_rows_are_read_from_the_mark_root(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _publish_mark(raw, "BTCUSDT", "1h", _ms(2026, 9, 27), _ms(2026, 9, 30))

    report = _report(raw, [_window(dataset="mark"), _window(dataset="trade")])

    by_dataset = {r.dataset: r for r in report.rows}
    assert by_dataset["mark"].cause == "OK"
    assert by_dataset["trade"].cause == "NOT_BACKFILLED"


def test_mid_day_onboard_start_is_not_a_leading_gap(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    onboard = _ms(2026, 9, 28, 7, 30)
    _publish_trade(raw, "NEWUSDT", "1h", _ms(2026, 9, 28, 8), _ms(2026, 9, 30))

    report = _report(
        raw,
        [_window("NEWUSDT", start_ms=onboard, cause="ONBOARD_LIMITED")],
    )

    (row,) = report.rows
    assert row.cause == "ONBOARD_LIMITED"
    assert row.expected_bars == 40  # 08:00 on the 28th to 23:00 on the 29th
    assert row.missing_bars == 0


def test_report_json_is_canonical_and_validates(tmp_path: Path) -> None:
    from src.data.sufficiency import (
        REPORT_SCHEMA,
        validate_report_file,
        write_report_json,
    )

    raw = tmp_path / "raw"
    _publish_trade(raw, "BTCUSDT", "1h", _ms(2026, 9, 27), _ms(2026, 9, 30))
    report = _report(raw, [_window()])

    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    write_report_json(report, first)
    write_report_json(_report(raw, [_window()]), second)

    assert first.read_bytes() == second.read_bytes()
    doc = json.loads(first.read_text(encoding="utf-8"))
    assert doc["schema"] == REPORT_SCHEMA == "data-sufficiency-report/1"
    assert list(doc) == sorted(doc)
    assert validate_report_file(first) == []
    assert not list(tmp_path.glob("*.tmp"))


def test_render_table_carries_rows_and_the_trade_floor_note(tmp_path: Path) -> None:
    from src.data.sufficiency import TRADE_FLOOR_NOTE, render_report_table

    raw = tmp_path / "raw"
    _publish_trade(raw, "BTCUSDT", "1h", _ms(2026, 9, 27), _ms(2026, 9, 30))
    report = _report(raw, [_window()])

    text = render_report_table(report)

    assert "DATASET" in text and "EXPECTED" in text and "CAUSE" in text
    assert "BTCUSDT" in text and "OK" in text
    assert TRADE_FLOOR_NOTE in text
    assert report.trade_floor_note == TRADE_FLOOR_NOTE
    assert "Phase 14" in TRADE_FLOOR_NOTE
    assert "100" in TRADE_FLOOR_NOTE and "30" in TRADE_FLOOR_NOTE


def test_missing_data_causes_are_exactly_the_three() -> None:
    from src.data.sufficiency import MISSING_DATA_CAUSES

    assert MISSING_DATA_CAUSES == frozenset({"NOT_BACKFILLED", "GAP", "UNAVAILABLE"})


def test_validate_rejects_tampered_reports(tmp_path: Path) -> None:
    from src.data.sufficiency import validate_report_file, write_report_json

    raw = tmp_path / "raw"
    _publish_trade(raw, "BTCUSDT", "1h", _ms(2026, 9, 27), _ms(2026, 9, 30))
    good = tmp_path / "good.json"
    write_report_json(_report(raw, [_window()]), good)
    doc = json.loads(good.read_text(encoding="utf-8"))

    bad_schema = tmp_path / "bad_schema.json"
    bad_schema.write_text(json.dumps({**doc, "schema": "other/9"}), encoding="utf-8")
    no_rows = tmp_path / "no_rows.json"
    no_rows.write_text(json.dumps({**doc, "rows": []}), encoding="utf-8")

    assert any("schema" in p for p in validate_report_file(bad_schema))
    assert any("rows" in p for p in validate_report_file(no_rows))
    assert validate_report_file(tmp_path / "absent.json") != []
