"""Coverage CLI + DuckDB view loaders — full D-11 contract.

Per D-11 (DATA_PIPELINE §10) + 02-PATTERNS §13. This module owns the
user-visible proof of "what data do we actually have?":

  1. Per-symbol effective range from the immutable Parquet candle store.
  2. Per-(symbol, data_class) coverage for the OI / funding tick stores.
  3. Per-(symbol, interval) continuity gap counts (so callers can spot
     a stuck or throttled backfill).
  4. A live-5 × {1m, 1h, 4h} matrix report for the all-symbol sweep.
  5. A read-only join with the PG-side `coverage_windows` rows
     (onboard time + status history), supplied by the caller as plain
     dicts so this module never needs a live database connection.

One entry point reads the canonical DuckDB view (`src/sql/coverage_v1.sql`)
and emits human-readable output. UTC stays UTC; conversion to
`Asia/Ho_Chi_Minh` happens ONLY at the print edge (D-06).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

import duckdb
from src.data.backfill import LIVE_5
from src.data.store import DEFAULT_RAW_ROOT

DEFAULT_SQL_PATH = Path(__file__).resolve().parent.parent / "sql" / "coverage_v1.sql"
DISPLAY_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Canonical V1 intervals (D-01). The coverage CLI reports a row for every
# (live-5 symbol, canonical interval) even when the cell is empty, so the
# operator sees missing partitions at a glance.
CANONICAL_INTERVALS: tuple[str, ...] = ("1m", "1h", "4h")
DEFAULT_OI_INTERVAL_MS = 300_000  # 5-minute canonical cadence (D-07)
DEFAULT_FUNDING_INTERVAL_MS = 28_800_000  # 8-hour funding cadence
# Unresolved-gap tolerances for tick series (D-19). OI ticks may be up to
# `TICK_GAP_FACTOR` cadences apart (the collector healthcheck bound) before a
# hole counts; funding ticks land within seconds of the 8h boundary, so a
# minute of jitter is tolerated and a missing tick (16h spacing) is a gap.
TICK_GAP_FACTOR = 2
FUNDING_JITTER_MS = 60_000

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _load_views(
    con: duckdb.DuckDBPyConnection,
    raw_root: Path,
    sql_path: Path = DEFAULT_SQL_PATH,
) -> None:
    """Load the checked-in view file, then re-point its glob at `raw_root`.

    The view file ships with the canonical `data/raw/...` glob (so it
    stays a stable contract across environments); the CLI rewrites the
    path to honor an alternate `raw_root` (e.g. a test tmpdir).

    Comments (`-- ...`) are stripped before splitting on `;` because
    DuckDB's SQL parser would otherwise try to interpret `-- ...` blocks
    that contain non-SQL punctuation (backticks, hyphens, etc.).

    Each `read_parquet(...)` glob is replaced at parse time with a
    `glob()` pre-check so a partition with zero files short-circuits to
    a `(SELECT ... WHERE 1 = 0)` frame with the exact column shape the
    outer view expects. The DuckDB session is pinned to `TimeZone =
    'UTC'` so a tz-aware Polars datetime column reads back as the same
    UTC wall-clock value regardless of host zone (D-06 / D-11 invariant).
    """
    # Pin DuckDB to UTC. The view file's CAST(... AS TIMESTAMP) strips
    # the tz info at the boundary; the comparison contract requires the
    # resulting naive timestamp to be the UTC wall-clock value.
    con.execute("SET TimeZone = 'UTC'")

    sql_text = sql_path.read_text(encoding="utf-8")
    alt = str(raw_root).replace("\\", "/")
    sql_text = sql_text.replace("data/raw/", f"{alt}/")
    cleaned_lines: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("--"):
            continue
        cleaned_lines.append(line)
    sql_text = "\n".join(cleaned_lines)

    import re

    pattern = re.compile(
        r"read_parquet\(\s*'([^']+)'\s*,\s*hive_partitioning\s*=\s*true\s*\)",
        flags=re.IGNORECASE,
    )

    # Map each read_parquet glob to the SELECT column list of its
    # enclosing view. We track which "CREATE OR REPLACE VIEW <name>"
    # we're inside by walking statements in order. For an empty glob,
    # we replace the read_parquet with a zero-row SELECT that carries
    # the same projected columns so the view creation succeeds.
    view_block_pattern = re.compile(
        r"(CREATE OR REPLACE VIEW\s+(\w+)\s+AS)(.*?)(?=CREATE OR REPLACE VIEW|\Z)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    new_blocks: list[str] = []
    cursor = 0
    for m in view_block_pattern.finditer(sql_text):
        prefix = sql_text[cursor : m.start()]
        new_blocks.append(prefix)
        view_name = m.group(2)
        body = m.group(3)
        cols = _columns_for_view(view_name)

        def _maybe_replace(read_match: re.Match[str], _cols: str = cols) -> str:
            glob_pat = read_match.group(1)
            # Escape single quotes: an operator path containing `'` must
            # not break the statement (or worse, inject SQL).
            glob_lit = glob_pat.replace("'", "''")
            try:
                hits = con.execute(
                    f"SELECT count(*) FROM glob('{glob_lit}')"
                ).fetchone()
                n = int(hits[0]) if hits else 0
            except duckdb.Error:
                n = 0
            if n > 0:
                return read_match.group(0)
            return f"(SELECT {_cols} WHERE 1 = 0)"

        body = pattern.sub(_maybe_replace, body)
        new_blocks.append(m.group(1) + body)
        cursor = m.end()
    new_blocks.append(sql_text[cursor:])
    sql_text = "".join(new_blocks)

    for stmt in sql_text.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        # Every view in the checked-in file is required: a creation
        # failure (wrong column, bad glob, schema drift) must fail loudly
        # at the cause, never downgrade to a warning that crashes a later
        # SELECT far from the defect.
        try:
            con.execute(stmt)
        except duckdb.Error as exc:
            raise RuntimeError(
                "coverage view failed to build: "
                f"{stmt.splitlines()[0][:120]}: {exc}"
            ) from exc


def _columns_for_view(view_name: str) -> str:
    """Return the projected column list for a view when the source glob is empty.

    The shape mirrors what the SQL view expects — we cast each column
    from NULL so the outer SELECT list compiles against the empty
    relation. Names match the real `read_parquet` schema column names
    (including Hive-partition virtual columns).
    """
    if view_name == "candles_v1":
        return (
            "CAST(NULL AS VARCHAR) AS symbol, "
            "CAST(NULL AS VARCHAR) AS interval, "
            "CAST(NULL AS TIMESTAMP) AS open_time_utc, "
            "CAST(NULL AS TIMESTAMP) AS close_time_utc, "
            "CAST(NULL AS DOUBLE) AS open, "
            "CAST(NULL AS DOUBLE) AS high, "
            "CAST(NULL AS DOUBLE) AS low, "
            "CAST(NULL AS DOUBLE) AS close, "
            "CAST(NULL AS DOUBLE) AS volume, "
            "CAST(NULL AS DOUBLE) AS quote_volume, "
            "CAST(NULL AS BIGINT) AS trade_count, "
            "CAST(NULL AS VARCHAR) AS tf, "
            "CAST(NULL AS DATE) AS date"
        )
    if view_name in ("oi_coverage_v1", "oi_research_coverage_v1"):
        return (
            "CAST(NULL AS VARCHAR) AS symbol, "
            "CAST(NULL AS VARCHAR) AS data_class, "
            "CAST(NULL AS TIMESTAMP) AS observed_at_utc"
        )
    if view_name == "funding_coverage_v1":
        # Funding ticks carry funding_time_utc (not observed_at_utc) — the
        # stub must project the real column or the view fails to compile.
        return (
            "CAST(NULL AS VARCHAR) AS symbol, "
            "CAST(NULL AS VARCHAR) AS data_class, "
            "CAST(NULL AS TIMESTAMP) AS funding_time_utc"
        )
    return "CAST(NULL AS TIMESTAMP) AS __empty"

def _format_utc(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    # The SQL view casts to a naive TIMESTAMP (UTC) so DuckDB doesn't need
    # pytz; we re-attach UTC here so the display edge can convert to
    # `Asia/Ho_Chi_Minh` (D-06).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    hcmc = dt.astimezone(DISPLAY_TZ)
    return f"{dt.isoformat()}  ({hcmc.strftime('%Y-%m-%d %H:%M %Z')})"


def _attach_utc(dt: datetime | None) -> datetime | None:
    """Mark a DuckDB-emitted naive timestamp as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@dataclass(frozen=True)
class CoverageCell:
    """One row in the coverage matrix — typed access for the CLI / tests."""

    symbol: str
    tf: str
    start_utc: datetime | None
    end_utc: datetime | None
    rows: int
    gap_count: int = 0


@dataclass(frozen=True)
class CoverageReport:
    """Aggregate coverage matrix for a set of (symbol, interval) cells.

    `cells` always includes every requested cell — an empty cell stays in
    the matrix with `rows=0` and `start_utc=None` so the CLI surfaces
    missing partitions without re-running the query.
    """

    cells: list[CoverageCell] = field(default_factory=list)

    @property
    def rows(self) -> list[CoverageCell]:
        """Backwards-compat alias used by earlier tests / CLI code paths."""
        return self.cells


class OICoverageRow(TypedDict):
    """One per-(symbol, data_class) tick-coverage row (OI + funding views).

    Typed (instead of `dict[str, object]`) so gap-math call sites type
    check: `start_utc`/`end_utc` are datetimes-or-None, `rows` an int.
    A plain dict at runtime — callers iterating keys are unaffected.
    """

    symbol: str
    data_class: str
    start_utc: datetime | None
    end_utc: datetime | None
    rows: int
    gap_count: int


def _gap_count_for_range(
    *,
    start_utc: datetime | None,
    end_utc: datetime | None,
    rows: int,
    expected_interval_ms: int | None,
) -> int:
    """Estimate continuity gaps given the range + expected cadence.

    For a dense series at `expected_interval_ms`, the expected row count
    is `(span // cadence) + 1`; the gap count is `expected - rows` (≥0).
    Returns 0 when the cadence is unknown (caller didn't supply one).
    """
    if expected_interval_ms is None or expected_interval_ms <= 0:
        return 0
    if start_utc is None or end_utc is None or rows == 0:
        return 0
    span_ms = (end_utc - start_utc).total_seconds() * 1000
    if span_ms <= 0:
        return 0
    expected = int(span_ms // expected_interval_ms) + 1
    return max(0, expected - rows)


@dataclass(frozen=True)
class GapRange:
    """One unresolved hole in a published series (D-19).

    `start_utc` is the first missing expected point (or the range start for a
    leading hole), `end_utc` the next observed point (or the range end for a
    trailing hole); `missing` is the number of expected slots inside the hole.
    Frozen and value-comparable, so a caller can pass exactly the gaps it has
    inspected back as an `allow_gaps` acknowledgement.
    """

    series: str
    symbol: str
    interval: str
    start_utc: datetime
    end_utc: datetime
    missing: int


def _utc_epoch_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("gap range bounds must be UTC-aware datetimes")
    return (value - _EPOCH) // timedelta(milliseconds=1)


def _from_epoch_ms(value: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=value)


def _observed_times_ms(
    files: Sequence[Path], time_column: str, start_ms: int, end_ms: int
) -> list[int]:
    """Epoch-ms of every row of `time_column` inside [start_ms, end_ms), ascending.

    Reads the explicit file list (never a glob). Polars writes tz-aware
    columns, so the value is CAST to a naive TIMESTAMP under `TimeZone=UTC`
    before `epoch_ms`, exactly like the coverage views.
    """
    if not _IDENT_RE.fullmatch(time_column):
        raise ValueError(f"unsafe time column name {time_column!r}")
    con = duckdb.connect(":memory:")
    try:
        con.execute("SET TimeZone = 'UTC'")
        expr = f'epoch_ms(CAST("{time_column}" AS TIMESTAMP))'
        rows = con.execute(
            f"SELECT {expr} AS t FROM read_parquet(?, hive_partitioning = false) "
            f"WHERE {expr} >= ? AND {expr} < ? ORDER BY t",
            [[str(p) for p in files], start_ms, end_ms],
        ).fetchall()
    finally:
        con.close()
    return [int(r[0]) for r in rows]


def gap_ranges_for_files(
    files: Sequence[Path],
    *,
    series: str,
    symbol: str,
    interval: str,
    time_column: str,
    step_ms: int,
    start_utc: datetime,
    end_utc: datetime,
    max_step_ms: int | None = None,
) -> list[GapRange]:
    """Return every unresolved hole of one series inside [start_utc, end_utc).

    The single definition of a gap (D-19): consecutive observations further
    apart than `max_step_ms` (default `step_ms`) form an interior hole; the
    range start counts as a virtual observation one `step_ms` earlier, so a
    leading hole exists when the first row is later than
    `start + (max_step_ms - step_ms)`; a trailing hole exists when the range
    end is more than `max_step_ms` after the last row. For a dense kline
    series this means "any missing bar"; for ticks the tolerance is the
    caller's `max_step_ms`. No file at all is one hole covering the range.
    All arithmetic is integer epoch milliseconds.
    """
    if step_ms <= 0:
        raise ValueError("step_ms must be positive")
    limit = step_ms if max_step_ms is None else max_step_ms
    if limit < step_ms:
        raise ValueError("max_step_ms must not be below step_ms")
    start_ms = _utc_epoch_ms(start_utc)
    end_ms = _utc_epoch_ms(end_utc)
    if end_ms <= start_ms:
        raise ValueError("end_utc must be after start_utc")

    def hole(from_ms: int, to_ms: int, missing: int) -> GapRange:
        return GapRange(
            series=series,
            symbol=symbol,
            interval=interval,
            start_utc=_from_epoch_ms(from_ms),
            end_utc=_from_epoch_ms(to_ms),
            missing=max(1, missing),
        )

    times = _observed_times_ms(files, time_column, start_ms, end_ms) if files else []
    if not times:
        return [hole(start_ms, end_ms, (end_ms - start_ms) // step_ms)]

    gaps: list[GapRange] = []
    first = times[0]
    if first - start_ms > limit - step_ms:
        gaps.append(hole(start_ms, first, (first - start_ms) // step_ms))
    for prev, nxt in zip(times, times[1:], strict=False):
        if nxt - prev > limit:
            gaps.append(hole(prev + step_ms, nxt, (nxt - prev) // step_ms - 1))
    last = times[-1]
    if end_ms - last > limit:
        gaps.append(hole(last + step_ms, end_ms, (end_ms - last) // step_ms - 1))
    return gaps


def report_symbol(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
) -> list[CoverageCell]:
    """Return one row per interval for `symbol` from the `coverage_v1` view.

    Each row carries `tf`, `start_utc`, `end_utc`, `rows`, and a
    `gap_count` estimated against the canonical interval cadence
    (D-04 + DATA_PIPELINE §6 continuity check).
    """
    _load_views(con, raw_root)
    rows = con.execute(
        "SELECT tf, historical_data_start_utc, historical_data_end_utc, rows "
        "FROM coverage_v1 WHERE symbol = ? ORDER BY tf",
        [symbol],
    ).fetchall()
    from src.data.quality import INTERVAL_MS

    out: list[CoverageCell] = []
    for tf, start, end, rows_count in rows:
        start_utc = _attach_utc(start)
        end_utc = _attach_utc(end)
        cadence_ms = INTERVAL_MS.get(str(tf))
        gap_count = _gap_count_for_range(
            start_utc=start_utc,
            end_utc=end_utc,
            rows=int(rows_count),
            expected_interval_ms=cadence_ms,
        )
        out.append(
            CoverageCell(
                symbol=str(symbol),
                tf=str(tf),
                start_utc=start_utc,
                end_utc=end_utc,
                rows=int(rows_count),
                gap_count=gap_count,
            )
        )
    return out


def report_all_live5(
    con: duckdb.DuckDBPyConnection,
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
) -> CoverageReport:
    """Build the live-5 × canonical-intervals coverage matrix.

    Every cell is materialized — empty cells show up as `rows=0` with
    `None` start/end so the operator can spot a missing backfill at a
    glance.
    """
    _load_views(con, raw_root)
    actual = con.execute(
        "SELECT symbol, tf, "
        "historical_data_start_utc, historical_data_end_utc, rows "
        "FROM coverage_v1"
    ).fetchall()
    by_key: dict[tuple[str, str], tuple[datetime | None, datetime | None, int]] = {}
    for sym, tf, start, end, n in actual:
        by_key[(str(sym), str(tf))] = (
            _attach_utc(start),
            _attach_utc(end),
            int(n),
        )

    from src.data.quality import INTERVAL_MS

    cells: list[CoverageCell] = []
    for sym in LIVE_5:
        for tf in CANONICAL_INTERVALS:
            start_utc, end_utc, n = by_key.get((sym, tf), (None, None, 0))
            cadence_ms = INTERVAL_MS.get(tf)
            gap_count = _gap_count_for_range(
                start_utc=start_utc,
                end_utc=end_utc,
                rows=n,
                expected_interval_ms=cadence_ms,
            )
            cells.append(
                CoverageCell(
                    symbol=sym,
                    tf=tf,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    rows=n,
                    gap_count=gap_count,
                )
            )
    return CoverageReport(cells=cells)


def oi_coverage_rows(
    con: duckdb.DuckDBPyConnection,
    raw_root: Path = DEFAULT_RAW_ROOT,
) -> list[OICoverageRow]:
    """Return per-(symbol, data_class) tick coverage rows from the OI + funding views.

    Combines `oi_coverage_v1` and `funding_coverage_v1` into one list so
    the CLI / Phase-7 journal can iterate once. Empty views return an
    empty list — never raise.
    """
    _load_views(con, raw_root)
    out: list[OICoverageRow] = []
    for view in ("oi_coverage_v1", "funding_coverage_v1"):
        try:
            rows = con.execute(
                f"SELECT symbol, data_class, historical_data_start_utc, "
                f"historical_data_end_utc, rows FROM {view} ORDER BY symbol, data_class"
            ).fetchall()
        except duckdb.Error:
            continue
        for sym, dc, start, end, n in rows:
            out.append(
                {
                    "symbol": str(sym),
                    "data_class": str(dc),
                    "start_utc": _attach_utc(start),
                    "end_utc": _attach_utc(end),
                    "rows": int(n),
                    "gap_count": 0,
                }
            )
    return out


def build_oi_coverage(
    con: duckdb.DuckDBPyConnection,
    raw_root: Path = DEFAULT_RAW_ROOT,
    *,
    expected_interval_ms: int = DEFAULT_OI_INTERVAL_MS,
    funding_interval_ms: int = DEFAULT_FUNDING_INTERVAL_MS,
) -> list[OICoverageRow]:
    """Tick coverage with explicit gap_count against each class cadence.

    OI rows use the 5-minute canonical cadence; funding rows use the
    8-hour funding cadence (funding is not exempt from D-11 continuity).
    """
    rows = oi_coverage_rows(con, raw_root)
    for r in rows:
        if r["data_class"] == "oi" and r["start_utc"] and r["end_utc"]:
            r["gap_count"] = _gap_count_for_range(
                start_utc=r["start_utc"],
                end_utc=r["end_utc"],
                rows=int(r["rows"]),
                expected_interval_ms=expected_interval_ms,
            )
        elif r["data_class"] == "funding" and r["start_utc"] and r["end_utc"]:
            r["gap_count"] = _gap_count_for_range(
                start_utc=r["start_utc"],
                end_utc=r["end_utc"],
                rows=int(r["rows"]),
                expected_interval_ms=funding_interval_ms,
            )
    return rows


def build_oimeta_view(
    con: duckdb.DuckDBPyConnection,
    raw_root: Path = DEFAULT_RAW_ROOT,
    *,
    pg_rows: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, object]]:
    """Join the candle coverage view with PG-side metadata (onboard + status)."""
    candle_report = report_all_live5(con, raw_root=raw_root)
    pg_index: dict[str, dict[str, Any]] = {}
    if pg_rows:
        for r in pg_rows:
            pg_index[str(r["symbol"])] = r

    out: list[dict[str, object]] = []
    for cell in candle_report.rows:
        sym = cell.symbol
        pg_meta = pg_index.get(sym, {})
        onboard_ms = pg_meta.get("onboard_ms")
        onboard_utc: datetime | None = None
        if onboard_ms is not None:
            onboard_utc = datetime.fromtimestamp(int(onboard_ms) / 1000, tz=UTC)
        out.append(
            {
                "symbol": sym,
                "tf": cell.tf,
                "start_utc": cell.start_utc,
                "end_utc": cell.end_utc,
                "rows": cell.rows,
                "gap_count": cell.gap_count,
                "onboard_utc": onboard_utc,
                "status_history_json": pg_meta.get("status_history_json", "[]"),
            }
        )
    return out


def _print_live5_table(report: CoverageReport) -> None:
    """Pretty-print the live-5 matrix to stdout."""
    by_sym: dict[str, list[CoverageCell]] = {s: [] for s in LIVE_5}
    for r in report.rows:
        by_sym.setdefault(r.symbol, []).append(r)
    header = f"{'symbol':<10} {'tf':<5} {'rows':>6}  {'gap_count':>9}  range (UTC -> HCMC)"
    print(header)
    print("-" * len(header))
    for sym in LIVE_5:
        for r in by_sym.get(sym, []):
            print(
                f"{sym:<10} {r.tf:<5} {r.rows:>6}  {r.gap_count:>9}  "
                f"start={_format_utc(r.start_utc)}  end={_format_utc(r.end_utc)}"
            )


def _live5_to_json(report: CoverageReport) -> str:
    payload: list[dict[str, Any]] = []
    for r in report.rows:
        payload.append(
            {
                "symbol": r.symbol,
                "tf": r.tf,
                "historical_data_start_utc": (
                    r.start_utc.isoformat() if r.start_utc else None
                ),
                "historical_data_end_utc": (
                    r.end_utc.isoformat() if r.end_utc else None
                ),
                "rows": r.rows,
                "gap_count": r.gap_count,
            }
        )
    return json.dumps(payload, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.data.coverage",
        description=(
            "Print effective per-symbol range from the Parquet store. "
            "Supports --symbol (single) and --all (live-5 matrix)."
        ),
    )
    parser.add_argument("--symbol", help="e.g. BTCUSDT (mutually exclusive with --all)")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print the live-5 × {1m,1h,4h} coverage matrix (D-01).",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=DEFAULT_RAW_ROOT,
        help="Override the data/raw root (default: ./data/raw).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable table.",
    )
    args = parser.parse_args(argv)

    if not args.raw_root.exists():
        print(
            f"error: raw-root {args.raw_root} does not exist; "
            "run the backfill first (or pass --raw-root <path>)",
            file=sys.stderr,
        )
        return 2

    if args.all and args.symbol:
        print("error: --symbol and --all are mutually exclusive", file=sys.stderr)
        return 2
    if not args.all and not args.symbol:
        args.all = True

    if args.all:
        report = report_all_live5_load(args.raw_root)
        if args.json:
            print(_live5_to_json(report))
            return 0
        print(f"coverage matrix for live-5 (rows sourced from {args.raw_root}):")
        _print_live5_table(report)
        return 0

    con = duckdb.connect(":memory:")
    try:
        rows = report_symbol(con, args.symbol, raw_root=args.raw_root)
    finally:
        con.close()

    if not rows:
        print(f"no coverage rows for symbol={args.symbol}", file=sys.stderr)
        return 1

    if args.json:
        payload = [
            {
                "symbol": args.symbol,
                "tf": r.tf,
                "historical_data_start_utc": (
                    r.start_utc.isoformat() if r.start_utc else None
                ),
                "historical_data_end_utc": (
                    r.end_utc.isoformat() if r.end_utc else None
                ),
                "rows": r.rows,
            }
            for r in rows
        ]
        print(json.dumps(payload, indent=2))
        return 0

    print(f"coverage for symbol={args.symbol} (rows sourced from {args.raw_root}):")
    for r in rows:
        print(
            f"  {r.tf:<4} rows={r.rows:<6}  "
            f"start={_format_utc(r.start_utc)}  "
            f"end={_format_utc(r.end_utc)}"
        )
    return 0


def report_all_live5_load(raw_root: Path) -> CoverageReport:
    """Re-load the live-5 matrix from disk (used by --json mode)."""
    con = duckdb.connect(":memory:")
    try:
        return report_all_live5(con, raw_root=raw_root)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
