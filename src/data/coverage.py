"""Coverage CLI — print effective per-symbol range from the Parquet store.

Per D-11 (DATA_PIPELINE §10) + 02-PATTERNS §13. This is the tracer
slice's user-visible proof: one entry point reads the canonical DuckDB
view (`src/sql/coverage_v1.sql`) and prints the effective range for one
symbol × interval pair.

HCMC display edge only (D-06): the storage stays UTC; conversion to
`Asia/Ho_Chi_Minh` happens at the print edge.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from src.data.store import DEFAULT_RAW_ROOT

DEFAULT_SQL_PATH = Path(__file__).resolve().parent.parent / "sql" / "coverage_v1.sql"
DISPLAY_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


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
    """
    sql_text = sql_path.read_text(encoding="utf-8")
    alt = str(raw_root).replace("\\", "/")
    sql_text = sql_text.replace("data/raw/", f"{alt}/")
    # Drop SQL line comments so the splitter only sees DDL statements.
    cleaned_lines = []
    for line in sql_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("--"):
            continue
        cleaned_lines.append(line)
    sql_text = "\n".join(cleaned_lines)
    for stmt in sql_text.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)


def _format_utc(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    # The SQL view casts to a naive TIMESTAMP (UTC) so DuckDB doesn't need
    # pytz; we re-attach UTC here so the display edge can convert to
    # `Asia/Ho_Chi_Minh` (D-06).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    hcmc = dt.astimezone(DISPLAY_TZ)
    return f"{dt.isoformat()}  ({hcmc.strftime('%Y-%m-%d %H:%M %Z')})"


def _attach_utc(dt: datetime | None) -> datetime | None:
    """Mark a DuckDB-emitted naive timestamp as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


def report_symbol(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
) -> list[dict[str, object]]:
    """Return one row per interval for `symbol` from the `coverage_v1` view."""
    _load_views(con, raw_root)
    rows = con.execute(
        "SELECT tf, historical_data_start_utc, historical_data_end_utc, rows "
        "FROM coverage_v1 WHERE symbol = ? ORDER BY tf",
        [symbol],
    ).fetchall()
    return [
        {
            "tf": tf,
            "start_utc": _attach_utc(start),
            "end_utc": _attach_utc(end),
            "rows": int(rows_count),
        }
        for tf, start, end, rows_count in rows
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.data.coverage",
        description="Print the effective per-symbol range from the Parquet store.",
    )
    parser.add_argument("--symbol", required=True, help="e.g. BTCUSDT")
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
                "tf": r["tf"],
                "historical_data_start_utc": (
                    r["start_utc"].isoformat() if r["start_utc"] else None
                ),
                "historical_data_end_utc": (
                    r["end_utc"].isoformat() if r["end_utc"] else None
                ),
                "rows": r["rows"],
            }
            for r in rows
        ]
        print(json.dumps(payload, indent=2))
        return 0

    print(f"coverage for symbol={args.symbol} (rows sourced from {args.raw_root}):")
    for r in rows:
        print(
            f"  {r['tf']:<4} rows={r['rows']:<6}  "
            f"start={_format_utc(r['start_utc'])}  "
            f"end={_format_utc(r['end_utc'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
