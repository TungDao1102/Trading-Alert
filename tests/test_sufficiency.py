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


def _kline(symbol: str, interval: str, open_ms: int, *, flat: bool = False) -> Kline:
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


# --------------------------------------------------------------------------- #
# Task 2 - per-split 1m coverage, flat-tail warning and the validate subcommand.
# --------------------------------------------------------------------------- #


def test_split_boundaries_follow_protocol_40_40_20() -> None:
    from src.data.sufficiency import SPLIT_NAMES, split_boundaries

    start, end = _ms(2024, 9, 30), _ms(2026, 9, 30)

    blocks = split_boundaries(start, end)

    assert [name for name, _, _ in blocks] == list(SPLIT_NAMES)
    assert SPLIT_NAMES == (
        "development",
        "validation_fold_1",
        "validation_fold_2",
        "validation_fold_3",
        "validation_fold_4",
        "holdout",
    )
    # 730 days: 40% = 292 d, then four folds of 73 d, then a 146 d holdout.
    edges = [blocks[0][1], *(b[2] for b in blocks)]
    assert edges == [
        _ms(2024, 9, 30),
        _ms(2025, 7, 19),
        _ms(2025, 9, 30),
        _ms(2025, 12, 12),
        _ms(2026, 2, 23),
        _ms(2026, 5, 7),
        _ms(2026, 9, 30),
    ]
    # Contiguous and covering the span exactly.
    for (_, _, prev_end), (_, next_start, _) in zip(blocks, blocks[1:], strict=False):
        assert prev_end == next_start
    assert blocks[0][1] == start and blocks[-1][2] == end


def test_split_boundaries_use_integer_arithmetic_on_odd_spans() -> None:
    from src.data.sufficiency import split_boundaries

    blocks = split_boundaries(0, 1_003)

    assert [b[2] for b in blocks] == [401, 501, 601, 702, 802, 1_003]
    assert all(isinstance(b[1], int) and isinstance(b[2], int) for b in blocks)
    with pytest.raises(ValueError):
        split_boundaries(5, 5)


def _split_report(tmp_path: Path, *, data_start: int, data_end: int) -> Any:
    raw = tmp_path / "raw"
    _publish_trade(raw, "BTCUSDT", "1m", data_start, data_end)
    window = _window(interval="1m", start_ms=data_start, end_ms=data_end, cause="FULL_DEPTH")
    return _report(
        raw,
        [window],
        depth_months={"1m": 12},
        dataset_start=date(2026, 8, 1),
        dataset_end=date(2026, 9, 30),
    )


def test_split_coverage_shows_missing_1m_in_development(tmp_path: Path) -> None:
    from src.data.sufficiency import DEPTH_EXTENSION_NOTE, render_report_table

    # 60 days: blocks end Aug 25, Aug 31, Sep 6, Sep 12, Sep 18, Sep 30.
    report = _split_report(tmp_path, data_start=_ms(2026, 9, 3), data_end=_ms(2026, 9, 8))

    by_block = {c.block: c for c in report.split_coverage}
    assert len(report.split_coverage) == 6
    assert by_block["development"].have_1m == 0
    assert by_block["development"].expected_1m == 24 * 1440
    assert by_block["validation_fold_1"].have_1m == 0
    assert by_block["validation_fold_2"].have_1m == 3 * 1440  # Sep 3 - Sep 6
    assert by_block["validation_fold_2"].expected_1m == 6 * 1440
    assert by_block["validation_fold_3"].have_1m == 2 * 1440  # Sep 6 - Sep 8
    assert by_block["holdout"].have_1m == 0
    assert report.depth_extension_note == DEPTH_EXTENSION_NOTE

    text = render_report_table(report)
    assert "50.00%" in text and "33.33%" in text and "0.00%" in text
    assert "development" in text and "holdout" in text
    assert DEPTH_EXTENSION_NOTE in text


def test_full_1m_coverage_prints_no_extension_note(tmp_path: Path) -> None:
    from src.data.sufficiency import DEPTH_EXTENSION_NOTE, render_report_table

    raw = tmp_path / "raw"
    start, end = _ms(2026, 9, 1), _ms(2026, 9, 11)
    _publish_trade(raw, "BTCUSDT", "1m", start, end)

    report = _report(
        raw,
        [_window(interval="1m", start_ms=start, end_ms=end)],
        depth_months={"1m": 12},
        dataset_start=date(2026, 9, 1),
        dataset_end=date(2026, 9, 11),
    )

    assert all(c.have_1m == c.expected_1m for c in report.split_coverage)
    assert report.depth_extension_note is None
    assert DEPTH_EXTENSION_NOTE not in render_report_table(report)


def test_flat_tail_is_warned_not_failed(tmp_path: Path) -> None:
    from src.data.sufficiency import render_report_table

    raw = tmp_path / "raw"
    # Sep 27, 28 and 29 hold only zero-trade flat bars (the last three stored days).
    _publish_trade(
        raw, "FLATUSDT", "1h", _ms(2026, 9, 20), _ms(2026, 9, 30), flat_from_ms=_ms(2026, 9, 27)
    )
    # Only two flat days: not flagged.
    _publish_trade(
        raw, "LIVEUSDT", "1h", _ms(2026, 9, 20), _ms(2026, 9, 30), flat_from_ms=_ms(2026, 9, 28)
    )
    windows = [
        _window("FLATUSDT", start_ms=_ms(2026, 9, 20)),
        _window("LIVEUSDT", start_ms=_ms(2026, 9, 20)),
    ]

    report = _report(raw, windows)

    flags = {r.symbol: r.flat_tail for r in report.rows}
    assert flags == {"FLATUSDT": True, "LIVEUSDT": False}
    assert {r.symbol: r.cause for r in report.rows} == {"FLATUSDT": "OK", "LIVEUSDT": "OK"}
    assert report.missing_data is False  # a warning, never a failure
    text = render_report_table(report)
    assert any(line.startswith("WARNING") and "FLATUSDT" in line for line in text.splitlines())
    assert not any("LIVEUSDT" in line for line in text.splitlines() if "WARNING" in line)


def test_validate_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from src.data.sufficiency import main, write_report_json

    good = tmp_path / "good.json"
    report = _split_report(tmp_path, data_start=_ms(2026, 9, 3), data_end=_ms(2026, 9, 8))
    write_report_json(report, good)
    doc = json.loads(good.read_text(encoding="utf-8"))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**doc, "schema": "other/9", "rows": []}), encoding="utf-8")

    assert main(["validate", str(good)]) == 0
    capsys.readouterr()
    assert main(["validate", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "schema" in err and "rows" in err
    assert main(["validate", str(tmp_path / "absent.json")]) == 1
    assert main([]) == 2


# --------------------------------------------------------------------------- #
# Funding coverage rows (D-23): per-symbol intervals, no constant step assumed.
# --------------------------------------------------------------------------- #

H8 = 8 * HOUR_MS
H4 = 4 * HOUR_MS


def _write_funding(raw: Path, symbol: str, times_ms: Sequence[int]) -> None:
    """One sweep-*.parquet per tick, exactly like the collector writes them."""
    import polars as pl

    for t in times_ms:
        when = _dt(t)
        folder = raw / "data_class=funding" / f"symbol={symbol}" / f"date={when.date()}"
        folder.mkdir(parents=True, exist_ok=True)
        frame = pl.DataFrame(
            {
                "symbol": [symbol],
                "funding_time_utc": [when],
                "funding_rate": [Decimal("0.0001")],
                "mark_price": [Decimal("100")],
            },
            schema={
                "symbol": pl.String(),
                "funding_time_utc": pl.Datetime(time_unit="ms", time_zone="UTC"),
                "funding_rate": pl.Decimal(scale=10),
                "mark_price": pl.Decimal(scale=8),
            },
        )
        frame.write_parquet(folder / f"sweep-{when:%Y%m%dT%H%M%SZ}-{t}.parquet")


def _series(start_ms: int, end_ms: int, step_ms: int) -> list[int]:
    return list(range(start_ms, end_ms, step_ms))


def _funding_window(
    symbol: str = "BTCUSDT",
    *,
    start_ms: int | None = _ms(2026, 9, 1),
    end_ms: int | None = _ms(2026, 9, 10),
    terminal: bool = False,
    cause: str = "FULL_DEPTH",
) -> Any:
    return _window(
        symbol,
        dataset="funding",
        interval="funding",
        start_ms=start_ms,
        end_ms=end_ms,
        terminal=terminal,
        cause=cause,
    )


def _funding_report(raw: Path, windows: Sequence[Any], **overrides: Any) -> Any:
    return _report(raw, [], funding_windows=list(windows), **overrides)


def test_full_8h_funding_series_is_ok(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_funding(raw, "BTCUSDT", _series(_ms(2026, 9, 1), _ms(2026, 9, 10), H8))

    report = _funding_report(raw, [_funding_window()])

    (row,) = report.rows
    assert (row.dataset, row.interval, row.cause) == ("funding", "funding", "OK")
    assert (row.expected_bars, row.have_bars, row.missing_bars) == (27, 27, 0)
    assert report.missing_data is False


def test_mixed_8h_then_4h_funding_series_is_ok(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    switch = _ms(2026, 9, 5)
    ticks = _series(_ms(2026, 9, 1), switch, H8) + _series(switch, _ms(2026, 9, 10), H4)
    _write_funding(raw, "BTCUSDT", ticks)

    report = _funding_report(raw, [_funding_window()])

    (row,) = report.rows
    assert row.cause == "OK"
    assert (row.expected_bars, row.have_bars) == (len(ticks), len(ticks))


def test_hole_in_the_middle_of_funding_is_a_gap_with_a_range(tmp_path: Path) -> None:
    from src.data.sufficiency import render_report_table

    raw = tmp_path / "raw"
    hole = (_ms(2026, 9, 4), _ms(2026, 9, 5))
    ticks = [
        t for t in _series(_ms(2026, 9, 1), _ms(2026, 9, 10), H8) if not hole[0] <= t < hole[1]
    ]
    _write_funding(raw, "BTCUSDT", ticks)

    report = _funding_report(raw, [_funding_window()])

    (row,) = report.rows
    assert row.cause == "GAP"
    assert report.missing_data is True
    (gap,) = row.gaps
    assert gap.missing == 3
    assert (gap.start_utc, gap.end_utc) == (_dt(hole[0]), _dt(hole[1]))
    assert (row.expected_bars, row.have_bars, row.missing_bars) == (27, 24, 3)
    line = "GAP funding BTCUSDT funding 2026-09-04T00:00:00Z..2026-09-05T00:00:00Z missing 3"
    assert line in render_report_table(report)


def test_funding_hole_inside_a_4h_stretch_counts_4h_ticks(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    hole = (_ms(2026, 9, 4), _ms(2026, 9, 4, 12))
    ticks = [
        t for t in _series(_ms(2026, 9, 1), _ms(2026, 9, 10), H4) if not hole[0] <= t < hole[1]
    ]
    _write_funding(raw, "BTCUSDT", ticks)

    (row,) = _funding_report(raw, [_funding_window()]).rows

    assert row.cause == "GAP"
    assert [g.missing for g in row.gaps] == [3]


def test_funding_late_first_tick_and_early_last_tick_are_gaps(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_funding(raw, "LATEUSDT", _series(_ms(2026, 9, 3), _ms(2026, 9, 10), H8))
    _write_funding(raw, "EARLYUSDT", _series(_ms(2026, 9, 1), _ms(2026, 9, 8), H8))

    report = _funding_report(raw, [_funding_window("LATEUSDT"), _funding_window("EARLYUSDT")])

    late, early = report.rows
    assert (late.cause, early.cause) == ("GAP", "GAP")
    assert late.gaps[0].start_utc == _dt(_ms(2026, 9, 1))
    assert late.gaps[0].missing == 6
    assert early.gaps[0].end_utc == _dt(_ms(2026, 9, 10))


def test_funding_jitter_within_tolerance_is_not_a_gap(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    base = _series(_ms(2026, 9, 1), _ms(2026, 9, 10), H8)
    _write_funding(raw, "BTCUSDT", [t + (3 if i % 2 else 0) for i, t in enumerate(base)])

    (row,) = _funding_report(raw, [_funding_window()]).rows

    assert row.cause == "OK"


def test_onboard_limited_funding_starts_at_the_late_window(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_funding(raw, "NEWUSDT", _series(_ms(2026, 9, 6, 8), _ms(2026, 9, 10), H8))

    report = _funding_report(
        raw,
        [_funding_window("NEWUSDT", start_ms=_ms(2026, 9, 6, 3), cause="ONBOARD_LIMITED")],
    )

    (row,) = report.rows
    assert row.cause == "ONBOARD_LIMITED"
    assert row.missing_bars == 0
    assert report.missing_data is False


def test_delisted_funding_is_capped_at_the_delivery(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    delivery = _ms(2026, 9, 6, 8)
    _write_funding(raw, "OLDUSDT", _series(_ms(2026, 9, 1), delivery, H8))

    report = _funding_report(
        raw,
        [_funding_window("OLDUSDT", end_ms=delivery, terminal=True, cause="DELISTED_CAPPED")],
    )

    (row,) = report.rows
    assert row.cause == "DELISTED_CAPPED"
    assert report.missing_data is False
    assert row.expected_end_utc == "2026-09-06T08:00:00Z"

    # Stopping a day before the delivery is a gap, not a cap.
    _write_funding(raw, "CUTUSDT", _series(_ms(2026, 9, 1), _ms(2026, 9, 5, 8), H8))
    cut_window = _funding_window("CUTUSDT", end_ms=delivery, terminal=True, cause="DELISTED_CAPPED")
    (cut,) = _funding_report(raw, [cut_window]).rows
    assert cut.cause == "GAP"


def test_empty_funding_is_not_backfilled_and_missing(tmp_path: Path) -> None:
    raw = tmp_path / "raw"

    report = _funding_report(raw, [_funding_window()])

    (row,) = report.rows
    assert row.cause == "NOT_BACKFILLED"
    assert (row.expected_bars, row.have_bars) == (27, 0)
    assert report.missing_data is True


def test_funding_without_window_is_no_window_or_unavailable(tmp_path: Path) -> None:
    raw = tmp_path / "raw"

    report = _funding_report(
        raw,
        [
            _funding_window("NOWUSDT", start_ms=None, end_ms=None, cause="NOT_LISTED_IN_RANGE"),
            _funding_window("UNKUSDT", start_ms=None, end_ms=None, cause="DELIVERY_UNKNOWN"),
        ],
    )

    assert [r.cause for r in report.rows] == ["NO_WINDOW", "UNAVAILABLE"]


def test_report_with_funding_rows_still_validates(tmp_path: Path) -> None:
    from src.data.sufficiency import validate_report_file, write_report_json

    raw = tmp_path / "raw"
    _publish_trade(raw, "BTCUSDT", "1h", _ms(2026, 9, 27), _ms(2026, 9, 30))
    _write_funding(raw, "BTCUSDT", _series(_ms(2026, 9, 1), _ms(2026, 9, 10), H8))
    report = _report(raw, [_window()], funding_windows=[_funding_window()])
    path = tmp_path / "report.json"

    write_report_json(report, path)

    assert report.schema == "data-sufficiency-report/1"
    assert validate_report_file(path) == []
    assert [r.dataset for r in report.rows] == ["trade", "funding"]
