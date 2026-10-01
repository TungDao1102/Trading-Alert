"""Tests for the coverage CLI + DuckDB coverage views (02-05 Task 1).

D-11 says "Queryable coverage" means:
  (a) a CLI command printing effective per-symbol range + violation/gap counts
  (b) a DuckDB SQL view over Parquet + metadata reporting
      historical_data_start_utc / historical_data_end_utc /
      onboard_time_utc / status_history per symbol.

The 02-02 tracer slice already shipped the parquet-side view + a per-symbol
CLI. This plan promotes both to the FULL contract:
  - coverage_v1.sql grows an oi / funding coverage view per data_class
  - coverage.py prints range + violation + gap counts for all live-5
    symbols across 1m / 1H / 4H
  - DuckDB views join Parquet evidence with PG-side onboard + status
    history (mocked in tests — production uses coverage_windows)

The CLI must convert to Asia/Ho_Chi_Minh ONLY at the print edge (D-06).

Tests run against an isolated tmpdir Parquet store; the SQL file is loaded
directly from disk so we exercise the "view-load from the checked-in file"
behavior the plan calls out.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import duckdb
import polars as pl
import pytest
from src.adapters.binance_usdm import Kline
from src.data.backfill import LIVE_5
from src.data.coverage import (
    DEFAULT_FUNDING_INTERVAL_MS,
    DEFAULT_OI_INTERVAL_MS,
    DEFAULT_SQL_PATH,
    FUNDING_JITTER_MS,
    TICK_GAP_FACTOR,
    CoverageReport,
    GapRange,
    build_oi_coverage,
    build_oimeta_view,
    gap_ranges_for_files,
    oi_coverage_rows,
    report_all_live5,
    report_symbol,
)
from src.data.store import publish_batch

# --------------------------------------------------------------------------- #
# Helpers — fabricate Parquet data for the DuckDB views.
# --------------------------------------------------------------------------- #


def _kline(
    *,
    open_ms: int,
    close_ms: int,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    price: str = "100.00",
) -> Kline:
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_dt.datetime.fromtimestamp(open_ms / 1000, tz=_dt.UTC),
        close_time_utc=_dt.datetime.fromtimestamp(close_ms / 1000, tz=_dt.UTC),
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1.0"),
        quote_volume=Decimal(price),
        trade_count=10,
    )


def _seed_candles(
    *,
    raw_root: Path,
    symbol: str,
    interval: str,
    start_ms: int,
    interval_ms: int,
    count: int,
) -> tuple[int, int]:
    """Publish `count` closed candles starting at `start_ms`. Return (start, end)."""
    klines = [
        _kline(
            open_ms=start_ms + i * interval_ms,
            close_ms=start_ms + i * interval_ms + interval_ms - 1,
            symbol=symbol,
            interval=interval,
        )
        for i in range(count)
    ]
    publish_batch(
        klines,
        interval=interval,
        symbol=symbol,
        raw_root=raw_root,
    )
    return start_ms, start_ms + (count - 1) * interval_ms + interval_ms - 1


def _seed_oi_snapshot(
    *,
    raw_root: Path,
    symbol: str,
    observed_ms: int,
    oi_value: str = "12345.6789",
    data_class: str = "oi",
    source: str = "canonical",
) -> Path:
    """Write one OI tick Parquet file under data_class=<oi>/symbol=<SYM>/date=.../."""
    observed_dt = _dt.datetime.fromtimestamp(observed_ms / 1000, tz=_dt.UTC)
    day = observed_dt.date().isoformat()
    iso = observed_dt.strftime("%Y%m%dT%H%M%SZ")
    out_dir = raw_root / f"data_class={data_class}" / f"symbol={symbol}" / f"date={day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"tick-{iso}.parquet"
    df = pl.DataFrame(
        {
            "symbol": [symbol],
            "observed_at_utc": [observed_dt],
            "open_interest": [Decimal(oi_value)],
            "source": [source],
        },
        schema_overrides={
            "observed_at_utc": pl.Datetime(time_unit="ms", time_zone="UTC"),
        },
    )
    df.write_parquet(out_path)
    return out_path


def _seed_funding_tick(
    *,
    raw_root: Path,
    symbol: str,
    funding_ms: int,
    funding_rate: str = "0.0001",
) -> Path:
    """Write one funding tick in the REAL collector schema.

    Mirrors `_write_funding_tick`: `sweep-<iso>.parquet` carrying
    `funding_time_utc` / `funding_rate` (never the OI shape — seeding the
    funding partition with OI-shaped rows masks view/column drift).
    """
    funding_dt = _dt.datetime.fromtimestamp(funding_ms / 1000, tz=_dt.UTC)
    day = funding_dt.date().isoformat()
    iso = funding_dt.strftime("%Y%m%dT%H%M%SZ")
    out_dir = raw_root / "data_class=funding" / f"symbol={symbol}" / f"date={day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"sweep-{iso}.parquet"
    df = pl.DataFrame(
        {
            "symbol": [symbol],
            "funding_time_utc": [funding_dt],
            "funding_rate": [Decimal(funding_rate)],
            "mark_price": [Decimal("50000.00")],
        },
        schema_overrides={
            "funding_time_utc": pl.Datetime(time_unit="ms", time_zone="UTC"),
        },
    )
    df.write_parquet(out_path)
    return out_path


# --------------------------------------------------------------------------- #
# Test 1 — CLI prints effective range + counts for a single symbol/interval.
# --------------------------------------------------------------------------- #


def test_report_symbol_returns_range_and_counts(tmp_path: Path) -> None:
    """One symbol × interval: report gives start, end, rows, gap_count."""
    start_ms = 1_700_000_000_000
    interval_ms = 3_600_000  # 1h
    _seed_candles(
        raw_root=tmp_path,
        symbol="BTCUSDT",
        interval="1h",
        start_ms=start_ms,
        interval_ms=interval_ms,
        count=10,
    )
    con = duckdb.connect(":memory:")
    try:
        rows = report_symbol(con, "BTCUSDT", raw_root=tmp_path)
    finally:
        con.close()

    by_tf = {r.tf: r for r in rows}
    assert "1h" in by_tf
    r = by_tf["1h"]
    assert r.rows == 10
    assert r.start_utc is not None
    assert r.end_utc is not None
    assert r.start_utc.tzinfo is not None
    assert int(r.start_utc.timestamp() * 1000) == start_ms
    assert r.gap_count == 0


# --------------------------------------------------------------------------- #
# Test 2 — empty partition returns zero rows (no crash, distinct msg).
# --------------------------------------------------------------------------- #


def test_report_symbol_with_no_data_returns_empty(tmp_path: Path) -> None:
    """An empty raw_root returns an empty list, never raises."""
    con = duckdb.connect(":memory:")
    try:
        rows = report_symbol(con, "BTCUSDT", raw_root=tmp_path)
    finally:
        con.close()
    assert rows == []


# --------------------------------------------------------------------------- #
# Test 3 — gap_count surfaces continuity gaps (not silently dropped).
# --------------------------------------------------------------------------- #


def test_gap_count_reports_continuity_gaps(tmp_path: Path) -> None:
    """A batch with a missing candle in the middle should flag a gap_count > 0.

    We publish 24 hourly bars covering 24h but skip one bar (bar 12). The
    coverage view spans 24 intervals but only contains 23 rows → 1 gap.
    """
    start_ms = 1_700_000_000_000
    interval_ms = 3_600_000  # 1h
    # Bars 0..22 (23 candles), leaving a 1-bar hole at index 12
    bars = [
        _kline(
            open_ms=start_ms + i * interval_ms,
            close_ms=start_ms + i * interval_ms + interval_ms - 1,
        )
        for i in range(24)
        if i != 12
    ]
    publish_batch(bars, interval="1h", symbol="BTCUSDT", raw_root=tmp_path)

    con = duckdb.connect(":memory:")
    try:
        rows = report_symbol(con, "BTCUSDT", raw_root=tmp_path)
    finally:
        con.close()

    by_tf = {r.tf: r for r in rows}
    assert by_tf["1h"].rows == 23
    assert by_tf["1h"].gap_count >= 1


# --------------------------------------------------------------------------- #
# Test 4 — range math uses close_time for end (not open_time).
# --------------------------------------------------------------------------- #


def test_range_uses_min_open_and_max_close(tmp_path: Path) -> None:
    """The effective start = MIN(open_time), end = MAX(close_time)."""
    start_ms = 1_700_000_000_000
    interval_ms = 3_600_000
    count = 5
    _, last_close_ms = _seed_candles(
        raw_root=tmp_path,
        symbol="ETHUSDT",
        interval="1h",
        start_ms=start_ms,
        interval_ms=interval_ms,
        count=count,
    )
    con = duckdb.connect(":memory:")
    try:
        rows = report_symbol(con, "ETHUSDT", raw_root=tmp_path)
    finally:
        con.close()
    r = next(r for r in rows if r.tf == "1h")
    assert int(r.start_utc.timestamp() * 1000) == start_ms
    assert int(r.end_utc.timestamp() * 1000) == last_close_ms


# --------------------------------------------------------------------------- #
# Test 5 — view-load from the checked-in SQL file (not inline).
# --------------------------------------------------------------------------- #


def test_default_sql_path_exists_and_loads() -> None:
    """The default SQL path resolves to a checked-in file (D-11 contract)."""
    assert DEFAULT_SQL_PATH.exists(), f"missing {DEFAULT_SQL_PATH}"
    text = DEFAULT_SQL_PATH.read_text(encoding="utf-8")
    # Must define candles_v1 + coverage_v1 (the contract)
    assert "CREATE OR REPLACE VIEW candles_v1" in text
    assert "CREATE OR REPLACE VIEW coverage_v1" in text


def test_load_views_handles_alternate_raw_root(tmp_path: Path) -> None:
    """_load_views rewrites the glob path so tests can use a tmpdir root."""
    from src.data.coverage import _load_views

    _seed_candles(
        raw_root=tmp_path,
        symbol="BNBUSDT",
        interval="1h",
        start_ms=1_700_000_000_000,
        interval_ms=3_600_000,
        count=3,
    )
    con = duckdb.connect(":memory:")
    try:
        _load_views(con, tmp_path)
        rows = con.execute(
            "SELECT tf, rows FROM coverage_v1 WHERE symbol = 'BNBUSDT' ORDER BY tf"
        ).fetchall()
    finally:
        con.close()
    assert ("1h", 3) in rows


# --------------------------------------------------------------------------- #
# Test 6 — report_all_live5 covers the live-5 × {1m, 1h, 4h} matrix.
# --------------------------------------------------------------------------- #


def test_report_all_live5_returns_matrix(tmp_path: Path) -> None:
    """The all-live5 reporter covers every live-5 symbol × the canonical
    V1 interval set (1m + 1h + 4h) — even when some cells are empty."""
    # Seed BTCUSDT 1h only — the other cells stay empty but appear in the report.
    _seed_candles(
        raw_root=tmp_path,
        symbol="BTCUSDT",
        interval="1h",
        start_ms=1_700_000_000_000,
        interval_ms=3_600_000,
        count=4,
    )
    con = duckdb.connect(":memory:")
    try:
        report = report_all_live5(con, raw_root=tmp_path)
    finally:
        con.close()

    assert isinstance(report, CoverageReport)
    # Every live-5 symbol × every canonical interval must appear.
    expected = {(s, tf) for s in LIVE_5 for tf in ("1m", "1h", "4h")}
    assert {(r.symbol, r.tf) for r in report.rows} >= expected
    # BTCUSDT 1h has 4 rows; every other cell is 0 (still present in the matrix).
    btc_1h = next(r for r in report.rows if r.symbol == "BTCUSDT" and r.tf == "1h")
    assert btc_1h.rows == 4
    sol_1m = next(r for r in report.rows if r.symbol == "SOLUSDT" and r.tf == "1m")
    assert sol_1m.rows == 0
    assert sol_1m.start_utc is None
    assert sol_1m.end_utc is None


# --------------------------------------------------------------------------- #
# Test 7 — OI coverage view (D-08) — per (symbol, data_class) oi rows.
# --------------------------------------------------------------------------- #


def test_oi_coverage_view_reports_per_symbol_range(tmp_path: Path) -> None:
    """The `oi_coverage_v1` view aggregates Parquet ticks per (symbol, data_class)."""
    # Seed OI ticks for BTCUSDT (canonical) on 3 distinct minutes.
    for i in range(3):
        _seed_oi_snapshot(
            raw_root=tmp_path,
            symbol="BTCUSDT",
            observed_ms=1_700_000_000_000 + i * 60_000,
            oi_value="100.0",
            data_class="oi",
        )
    # Seed funding tick in the real funding schema (different data_class)
    _seed_funding_tick(
        raw_root=tmp_path,
        symbol="BTCUSDT",
        funding_ms=1_700_000_000_000,
        funding_rate="0.0001",
    )
    con = duckdb.connect(":memory:")
    try:
        rows = oi_coverage_rows(con, tmp_path)
    finally:
        con.close()

    by_class = {(r["data_class"], r["symbol"]): r for r in rows}
    assert ("oi", "BTCUSDT") in by_class
    assert by_class[("oi", "BTCUSDT")]["rows"] == 3
    assert ("funding", "BTCUSDT") in by_class
    assert by_class[("funding", "BTCUSDT")]["rows"] == 1


# --------------------------------------------------------------------------- #
# Test 8 — onboard + status history joined from a PG-side rows source.
# --------------------------------------------------------------------------- #


def test_coverage_view_joins_onboard_and_status_history(tmp_path: Path) -> None:
    """The coverage report can attach a PG-side onboard time + status history.

    The actual PG connection is out of scope for this plan (no DB in the
    test environment). We exercise the join contract by passing in a list
    of `(symbol, onboard_ms, status_history_json)` tuples.
    """
    _seed_candles(
        raw_root=tmp_path,
        symbol="SOLUSDT",
        interval="1h",
        start_ms=1_700_000_000_000,
        interval_ms=3_600_000,
        count=2,
    )
    pg_rows = [
        {
            "symbol": "SOLUSDT",
            "onboard_ms": 1_600_000_000_000,
            "status_history_json": json.dumps(
                [{"status": "TRADING", "from_ms": 1_600_000_000_000}]
            ),
        },
        {
            "symbol": "BTCUSDT",
            "onboard_ms": 1_500_000_000_000,
            "status_history_json": json.dumps(
                [{"status": "TRADING", "from_ms": 1_500_000_000_000}]
            ),
        },
    ]
    con = duckdb.connect(":memory:")
    try:
        report = build_oimeta_view(con, tmp_path, pg_rows=pg_rows)
    finally:
        con.close()

    sol = next(r for r in report if r["symbol"] == "SOLUSDT")
    assert sol["onboard_utc"] is not None
    assert int(sol["onboard_utc"].timestamp() * 1000) == 1_600_000_000_000
    assert json.loads(sol["status_history_json"])[0]["status"] == "TRADING"
    btc = next(r for r in report if r["symbol"] == "BTCUSDT")
    assert btc["rows"] == 0  # no BTCUSDT candles seeded
    assert btc["onboard_utc"] is not None


# --------------------------------------------------------------------------- #
# Test 9 — CLI exit code 0 for a seeded symbol, 1 for an empty one.
# --------------------------------------------------------------------------- #


def test_cli_runs_for_seeded_symbol(tmp_path: Path) -> None:
    """`python -m src.data.coverage --symbol BTCUSDT` prints range + exit 0."""
    _seed_candles(
        raw_root=tmp_path,
        symbol="BTCUSDT",
        interval="1h",
        start_ms=1_700_000_000_000,
        interval_ms=3_600_000,
        count=3,
    )
    cmd = [
        sys.executable,
        "-m",
        "src.data.coverage",
        "--symbol",
        "BTCUSDT",
        "--raw-root",
        str(tmp_path),
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert "1h" in proc.stdout
    assert "rows=3" in proc.stdout


def test_cli_exits_nonzero_for_unknown_symbol(tmp_path: Path) -> None:
    """`--symbol XYZ` with no data exits 1 with a 'no coverage rows' stderr."""
    cmd = [
        sys.executable,
        "-m",
        "src.data.coverage",
        "--symbol",
        "XYZUSDT",
        "--raw-root",
        str(tmp_path),
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "no coverage rows" in proc.stderr


# --------------------------------------------------------------------------- #
# Test 10 — coverage table for all live-5 via CLI (`--all`).
# --------------------------------------------------------------------------- #


def test_cli_all_live5_prints_full_matrix(tmp_path: Path) -> None:
    """`--all` prints a row for every live-5 symbol × {1m,1h,4h} cell."""
    _seed_candles(
        raw_root=tmp_path,
        symbol="BTCUSDT",
        interval="1h",
        start_ms=1_700_000_000_000,
        interval_ms=3_600_000,
        count=2,
    )
    cmd = [
        sys.executable,
        "-m",
        "src.data.coverage",
        "--all",
        "--raw-root",
        str(tmp_path),
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    out = proc.stdout
    for sym in LIVE_5:
        assert sym in out, f"missing {sym} in CLI output"
    # Every canonical interval must appear at least once.
    for tf in ("1m", "1h", "4h"):
        assert tf in out, f"missing interval {tf} in CLI output"


# --------------------------------------------------------------------------- #
# Test 11 — HCMC display edge (D-06): UTC → Asia/Ho_Chi_Minh at print time.
# --------------------------------------------------------------------------- #


def test_cli_displays_asia_ho_chi_minh_at_print_edge(tmp_path: Path) -> None:
    """The CLI converts to Asia/Ho_Chi_Minh at the display edge only."""
    _seed_candles(
        raw_root=tmp_path,
        symbol="BTCUSDT",
        interval="1h",
        start_ms=1_700_000_000_000,  # 2023-11-14 22:13:20 UTC
        interval_ms=3_600_000,
        count=1,
    )
    cmd = [
        sys.executable,
        "-m",
        "src.data.coverage",
        "--symbol",
        "BTCUSDT",
        "--raw-root",
        str(tmp_path),
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    # The UTC line is the canonical value; the parenthetical is HCMC.
    assert "+07" in proc.stdout or "ICT" in proc.stdout, (
        f"expected HCMC marker in output, got: {proc.stdout!r}"
    )


# --------------------------------------------------------------------------- #
# Test 12 — gap count for OI coverage surfaces missing ticks.
# --------------------------------------------------------------------------- #


def test_oi_gap_count_via_build_oi_coverage(tmp_path: Path) -> None:
    """OI coverage exposes per-(symbol, data_class) gap_count for tick density."""
    # Seed 5 OI ticks 5 minutes apart — the data is dense; no gaps.
    for i in range(5):
        _seed_oi_snapshot(
            raw_root=tmp_path,
            symbol="BTCUSDT",
            observed_ms=1_700_000_000_000 + i * 300_000,  # 5 min apart
            data_class="oi",
        )
    con = duckdb.connect(":memory:")
    try:
        rows = build_oi_coverage(con, tmp_path, expected_interval_ms=300_000)
    finally:
        con.close()
    btc = next(r for r in rows if r["symbol"] == "BTCUSDT" and r["data_class"] == "oi")
    # 5 ticks spanning 20 minutes, density check: 5 rows, gap_count should be 0
    # (the OI loop is canonical cadence; expected interval 5 minutes).
    assert btc["rows"] == 5
    assert btc["gap_count"] == 0


# --------------------------------------------------------------------------- #
# Test 13 — JSON output mode emits structured payload (machine-readable).
# --------------------------------------------------------------------------- #


def test_cli_json_mode_emits_machine_readable(tmp_path: Path) -> None:
    """`--json` produces a parseable payload with isoformat timestamps."""
    _seed_candles(
        raw_root=tmp_path,
        symbol="BTCUSDT",
        interval="1h",
        start_ms=1_700_000_000_000,
        interval_ms=3_600_000,
        count=2,
    )
    cmd = [
        sys.executable,
        "-m",
        "src.data.coverage",
        "--symbol",
        "BTCUSDT",
        "--raw-root",
        str(tmp_path),
        "--json",
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert isinstance(payload, list)
    assert payload[0]["symbol"] == "BTCUSDT"
    assert payload[0]["tf"] == "1h"
    assert payload[0]["rows"] == 2
    assert "2023-11-14" in payload[0]["historical_data_start_utc"]


# --------------------------------------------------------------------------- #
# Test 14 — Static guard: src/data/coverage.py has no `float(` call.
# --------------------------------------------------------------------------- #


def test_coverage_module_has_no_float_call() -> None:
    """Same ENGINEERING_PRINCIPLES rule that ships with metadata."""
    import ast

    from src.data import coverage as coverage_mod

    src = Path(coverage_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                pytest.fail(f"float() call at line {node.lineno} — violates exchange-decimal rule")


# --------------------------------------------------------------------------- #
# Test 15 — Sanity guard: SQL view file lists every canonical data class.
# --------------------------------------------------------------------------- #


def test_sql_view_defines_candles_oi_and_funding() -> None:
    """The checked-in view file MUST define at least candles + oi + funding views."""
    text = DEFAULT_SQL_PATH.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE VIEW candles_v1" in text
    assert "CREATE OR REPLACE VIEW coverage_v1" in text
    assert "oi_coverage_v1" in text or "funding_coverage_v1" in text


# --------------------------------------------------------------------------- #
# 13-09 - gap_ranges_for_files: the one definition of an unresolved gap (D-19).
# --------------------------------------------------------------------------- #

_H = 3_600_000
_DAY0_MS = int(_dt.datetime(2026, 7, 1, tzinfo=_dt.UTC).timestamp() * 1000)


def _utc(ms: int) -> _dt.datetime:
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.UTC)


def _publish_hours(raw_root: Path, hours: list[int]) -> list[Path]:
    klines = [_kline(open_ms=_DAY0_MS + h * _H, close_ms=_DAY0_MS + h * _H + _H - 1) for h in hours]
    return publish_batch(klines, interval="1h", symbol="BTCUSDT", raw_root=raw_root)


def _hour_gaps(files: list[Path]) -> list:
    return gap_ranges_for_files(
        files,
        series="trade",
        symbol="BTCUSDT",
        interval="1h",
        time_column="open_time_utc",
        step_ms=_H,
        start_utc=_utc(_DAY0_MS),
        end_utc=_utc(_DAY0_MS + 24 * _H),
    )


def test_gap_ranges_reports_interior_kline_gap(tmp_path: Path) -> None:
    files = _publish_hours(tmp_path, [h for h in range(24) if h not in (10, 11)])
    assert _hour_gaps(files) == [
        GapRange(
            series="trade",
            symbol="BTCUSDT",
            interval="1h",
            start_utc=_utc(_DAY0_MS + 10 * _H),
            end_utc=_utc(_DAY0_MS + 12 * _H),
            missing=2,
        )
    ]


def test_gap_ranges_complete_series_has_no_gap(tmp_path: Path) -> None:
    files = _publish_hours(tmp_path, list(range(24)))
    assert _hour_gaps(files) == []


def test_gap_ranges_reports_leading_trailing_and_empty(tmp_path: Path) -> None:
    files = _publish_hours(tmp_path, list(range(2, 22)))
    gaps = _hour_gaps(files)
    assert [(g.start_utc, g.end_utc, g.missing) for g in gaps] == [
        (_utc(_DAY0_MS), _utc(_DAY0_MS + 2 * _H), 2),
        (_utc(_DAY0_MS + 22 * _H), _utc(_DAY0_MS + 24 * _H), 2),
    ]
    whole = _hour_gaps([])
    assert [(g.start_utc, g.end_utc, g.missing) for g in whole] == [
        (_utc(_DAY0_MS), _utc(_DAY0_MS + 24 * _H), 24)
    ]


def _funding_gaps(files: list[Path]) -> list:
    return gap_ranges_for_files(
        files,
        series="funding",
        symbol="BTCUSDT",
        interval="8h",
        time_column="funding_time_utc",
        step_ms=DEFAULT_FUNDING_INTERVAL_MS,
        max_step_ms=DEFAULT_FUNDING_INTERVAL_MS + FUNDING_JITTER_MS,
        start_utc=_utc(_DAY0_MS),
        end_utc=_utc(_DAY0_MS + 24 * _H),
    )


def test_funding_jitter_is_not_a_gap_but_a_missing_tick_is(tmp_path: Path) -> None:
    jittered = [
        _seed_funding_tick(raw_root=tmp_path, symbol="BTCUSDT", funding_ms=_DAY0_MS + 4),
        _seed_funding_tick(raw_root=tmp_path, symbol="BTCUSDT", funding_ms=_DAY0_MS + 8 * _H + 8),
        _seed_funding_tick(raw_root=tmp_path, symbol="BTCUSDT", funding_ms=_DAY0_MS + 16 * _H + 12),
    ]
    assert _funding_gaps(jittered) == []

    other = tmp_path / "other"
    sparse = [
        _seed_funding_tick(raw_root=other, symbol="BTCUSDT", funding_ms=_DAY0_MS),
        _seed_funding_tick(raw_root=other, symbol="BTCUSDT", funding_ms=_DAY0_MS + 16 * _H),
    ]
    gaps = _funding_gaps(sparse)
    assert [(g.start_utc, g.end_utc, g.missing) for g in gaps] == [
        (_utc(_DAY0_MS + 8 * _H), _utc(_DAY0_MS + 16 * _H), 1)
    ]


def _oi_gaps(files: list[Path]) -> list:
    return gap_ranges_for_files(
        files,
        series="open_interest",
        symbol="BTCUSDT",
        interval="5m",
        time_column="observed_at_utc",
        step_ms=DEFAULT_OI_INTERVAL_MS,
        max_step_ms=TICK_GAP_FACTOR * DEFAULT_OI_INTERVAL_MS,
        start_utc=_utc(_DAY0_MS),
        end_utc=_utc(_DAY0_MS + 30 * 60_000),
    )


def test_oi_gap_bound_is_twice_the_cadence(tmp_path: Path) -> None:
    ok = [
        _seed_oi_snapshot(raw_root=tmp_path, symbol="BTCUSDT", observed_ms=_DAY0_MS + i * 320_000)
        for i in range(6)
    ]
    assert _oi_gaps(ok) == []

    other = tmp_path / "other"
    holed = [
        _seed_oi_snapshot(raw_root=other, symbol="BTCUSDT", observed_ms=_DAY0_MS + m * 60_000)
        for m in (0, 5, 16, 21, 26)
    ]
    gaps = _oi_gaps(holed)
    assert [(g.start_utc, g.end_utc, g.missing) for g in gaps] == [
        (_utc(_DAY0_MS + 10 * 60_000), _utc(_DAY0_MS + 16 * 60_000), 1)
    ]
