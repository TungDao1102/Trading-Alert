"""Data-sufficiency report for the history backfill (Phase 13, plan 13-08; D-05, D-21).

`build_sufficiency_report` compares, per (dataset, symbol, interval), the bars a
planned window EXPECTS with the bars actually stored, and names the cause of any
shortfall:

  OK               the window is fully covered.
  ONBOARD_LIMITED  the contract listed after the depth start; covered from onboard.
  DELISTED_CAPPED  the contract was delivered; covered up to its delivery.
  NO_WINDOW        nothing is expected (the contract lists after the run).
  NOT_BACKFILLED   bars are expected and none are stored.          (missing data)
  GAP              stored bars leave an unresolved hole.            (missing data)
  UNAVAILABLE      no source serves the symbol or dataset.          (missing data)

The gap definition is `coverage.gap_ranges_for_files`, the same one the case
input builder refuses on (D-19), so a GAP row here is exactly a range the
builder would fail closed on.

The report checks data DEPTH only. It never estimates a trade count and never
edits or lowers the D043 trade floor: the floor cannot be measured until the
Phase 14 causal simulator exists (`TRADE_FLOOR_NOTE`, D-05). Extending 1m to 24
months through the archive is a user decision taken from this report
(`DEPTH_EXTENSION_NOTE`, D-21). All arithmetic is integer epoch milliseconds;
no wall clock is read.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Protocol

import polars as pl
from src.data.coverage import GapRange, gap_ranges_for_files
from src.data.quality import INTERVAL_MS
from src.data.store import MARK_DATASET_DIR, partition_file

REPORT_SCHEMA: Final = "data-sufficiency-report/1"

# Causes that mean data is missing (exit code 3). Everything else is either
# fully covered or an explained, expected shortfall.
MISSING_DATA_CAUSES: Final = frozenset({"NOT_BACKFILLED", "GAP", "UNAVAILABLE"})
ALL_CAUSES: Final = frozenset(
    {"OK", "ONBOARD_LIMITED", "DELISTED_CAPPED", "NO_WINDOW", *MISSING_DATA_CAUSES}
)

SOURCE_REST: Final = "REST"
SOURCE_ARCHIVE: Final = "ARCHIVE"
SOURCE_UNAVAILABLE: Final = "UNAVAILABLE"
SOURCE_NONE: Final = "NONE"

TRADE_FLOOR_NOTE: Final = (
    "The D043 trade floor (at least 100 closed trades pooled across the four "
    "Validation folds and at least 30 per fold) cannot be measured until the "
    "Phase 14 causal simulator exists; this report checks data depth only and "
    "never changes the floor."
)
DEPTH_EXTENSION_NOTE: Final = (
    "Extending 1m history to 24 months through the Binance archive is a user "
    "decision to take after reading this report (D-21); the default stays 12 months."
)

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_DAY_MS: Final = 86_400_000
_MAX_GAPS_PRINTED: Final = 5


class WindowLike(Protocol):
    """The planned window fields the report reads (`backfill_cli.SymbolWindow`)."""

    @property
    def dataset(self) -> str: ...
    @property
    def symbol(self) -> str: ...
    @property
    def interval(self) -> str: ...
    @property
    def start_ms(self) -> int | None: ...
    @property
    def end_ms(self) -> int | None: ...
    @property
    def cause(self) -> str: ...


@dataclass(frozen=True)
class SufficiencyRow:
    """One (dataset, symbol, interval): expected versus stored bars and why."""

    dataset: str
    symbol: str
    interval: str
    source: str
    expected_start_utc: str | None
    expected_end_utc: str | None
    expected_bars: int
    have_bars: int
    missing_bars: int
    cause: str
    gaps: tuple[GapRange, ...]
    flat_tail: bool


@dataclass(frozen=True)
class SplitCoverage:
    """1m coverage of one protocol split block for one symbol (D-21)."""

    symbol: str
    block: str
    start_utc: str
    end_utc: str
    expected_1m: int
    have_1m: int


@dataclass(frozen=True)
class SufficiencyReport:
    """The whole report; `missing_data` drives the CLI exit code."""

    schema: str
    run_date: date
    depth_months: dict[str, int]
    dataset_start: date
    dataset_end: date
    rows: tuple[SufficiencyRow, ...]
    split_coverage: tuple[SplitCoverage, ...]
    trade_floor_note: str
    depth_extension_note: str | None
    missing_data: bool


# --------------------------------------------------------------------------- #
# Arithmetic and store access.
# --------------------------------------------------------------------------- #


def expected_bar_count(start_ms: int, end_ms: int, step_ms: int) -> int:
    """Bars whose open time is a multiple of `step_ms` inside [start_ms, end_ms)."""
    if step_ms <= 0:
        raise ValueError("step_ms must be positive")
    if start_ms >= end_ms:
        return 0
    first = -(-start_ms // step_ms) * step_ms
    if first >= end_ms:
        return 0
    return (end_ms - 1 - first) // step_ms + 1


def _ceil_to_step(ms: int, step_ms: int) -> int:
    return -(-ms // step_ms) * step_ms


def _from_ms(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


def _iso(ms: int) -> str:
    return _from_ms(ms).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day_start_ms(day: date) -> int:
    return (datetime(day.year, day.month, day.day, tzinfo=UTC) - _EPOCH) // timedelta(
        milliseconds=1
    )


def _store_root(raw_root: Path, dataset: str) -> Path:
    return raw_root / MARK_DATASET_DIR if dataset == "mark" else raw_root


def _day_files(
    raw_root: Path, dataset: str, interval: str, symbol: str, lo_ms: int, hi_ms: int
) -> list[Path]:
    """Existing per-day files whose UTC day intersects [lo_ms, hi_ms), oldest first."""
    if lo_ms >= hi_ms:
        return []
    root = _store_root(raw_root, dataset)
    files: list[Path] = []
    day = _from_ms(lo_ms).date()
    last = _from_ms(hi_ms - 1).date()
    while day <= last:
        path = partition_file(root, interval, symbol, day)
        if path.is_file():
            files.append(path)
        day += timedelta(days=1)
    return files


def _open_times_ms(files: Sequence[Path]) -> pl.Series:
    """Every stored open time of `files` as epoch milliseconds."""
    if not files:
        return pl.Series("open_ms", [], dtype=pl.Int64)
    frame = pl.read_parquet(
        [str(p) for p in files], columns=["open_time_utc"], hive_partitioning=False
    )
    return frame["open_time_utc"].dt.epoch("ms").alias("open_ms")


def _count_in(open_ms: pl.Series, lo_ms: int, hi_ms: int) -> int:
    return int(((open_ms >= lo_ms) & (open_ms < hi_ms)).sum())


# --------------------------------------------------------------------------- #
# Rows.
# --------------------------------------------------------------------------- #


def _informational(window_cause: str) -> str:
    return window_cause if window_cause in ("ONBOARD_LIMITED", "DELISTED_CAPPED") else "OK"


def _build_row(raw_root: Path, window: WindowLike, source: str | None) -> SufficiencyRow:
    start, end = window.start_ms, window.end_ms
    has_window = start is not None and end is not None and start < end
    resolved_source = source or (SOURCE_REST if has_window else SOURCE_NONE)

    def row(
        cause: str,
        *,
        expected: int = 0,
        have: int = 0,
        gaps: tuple[GapRange, ...] = (),
    ) -> SufficiencyRow:
        return SufficiencyRow(
            dataset=window.dataset,
            symbol=window.symbol,
            interval=window.interval,
            source=resolved_source,
            expected_start_utc=_iso(start) if has_window and start is not None else None,
            expected_end_utc=_iso(end) if has_window and end is not None else None,
            expected_bars=expected,
            have_bars=have,
            missing_bars=max(expected - have, 0),
            cause=cause,
            gaps=gaps,
            flat_tail=False,
        )

    if window.cause == "NOT_LISTED_IN_RANGE":
        return row("NO_WINDOW")
    if window.cause == "DELIVERY_UNKNOWN" or resolved_source == SOURCE_UNAVAILABLE:
        return row("UNAVAILABLE")
    if not has_window or start is None or end is None:
        # A capped window that ended before the depth start expects nothing.
        return row("DELISTED_CAPPED" if window.cause == "DELISTED_CAPPED" else "NO_WINDOW")

    step = INTERVAL_MS[window.interval]
    expected = expected_bar_count(start, end, step)
    if expected == 0:
        return row(_informational(window.cause))
    # The first bar of a mid-day start (onboard time) opens on the next step
    # boundary; anchoring the gap check there keeps the range start from
    # counting as a missing bar.
    aligned_start = _ceil_to_step(start, step)
    files = _day_files(
        raw_root, window.dataset, window.interval, window.symbol, aligned_start, end
    )
    have = _count_in(_open_times_ms(files), aligned_start, end)
    if have == 0:
        return row("NOT_BACKFILLED", expected=expected)
    gaps = tuple(
        gap_ranges_for_files(
            files,
            series=f"{window.dataset}_klines",
            symbol=window.symbol,
            interval=window.interval,
            time_column="open_time_utc",
            step_ms=step,
            start_utc=_from_ms(aligned_start),
            end_utc=_from_ms(end),
        )
    )
    if gaps:
        return row("GAP", expected=expected, have=have, gaps=gaps)
    return row(_informational(window.cause), expected=expected, have=have)


def build_sufficiency_report(
    raw_root: Path,
    windows: Sequence[WindowLike],
    *,
    run_date: date,
    depth_months: Mapping[str, int],
    dataset_start: date,
    dataset_end: date,
    sources: Mapping[tuple[str, str], str],
) -> SufficiencyReport:
    """One row per planned window, in window order; `sources` maps (dataset, symbol)."""
    rows = tuple(
        _build_row(raw_root, w, sources.get((w.dataset, w.symbol))) for w in windows
    )
    return SufficiencyReport(
        schema=REPORT_SCHEMA,
        run_date=run_date,
        depth_months=dict(depth_months),
        dataset_start=dataset_start,
        dataset_end=dataset_end,
        rows=rows,
        split_coverage=(),
        trade_floor_note=TRADE_FLOOR_NOTE,
        depth_extension_note=None,
        missing_data=any(r.cause in MISSING_DATA_CAUSES for r in rows),
    )


# --------------------------------------------------------------------------- #
# Rendering, writing, validating.
# --------------------------------------------------------------------------- #


def _gap_dict(gap: GapRange) -> dict[str, Any]:
    return {
        "series": gap.series,
        "symbol": gap.symbol,
        "interval": gap.interval,
        "start_utc": gap.start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_utc": gap.end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "missing": gap.missing,
    }


def report_to_dict(report: SufficiencyReport) -> dict[str, Any]:
    """The JSON-ready form of a report (keys sorted on write)."""
    return {
        "schema": report.schema,
        "run_date": report.run_date.isoformat(),
        "depth_months": dict(report.depth_months),
        "dataset_start": report.dataset_start.isoformat(),
        "dataset_end": report.dataset_end.isoformat(),
        "rows": [
            {
                "dataset": r.dataset,
                "symbol": r.symbol,
                "interval": r.interval,
                "source": r.source,
                "expected_start_utc": r.expected_start_utc,
                "expected_end_utc": r.expected_end_utc,
                "expected_bars": r.expected_bars,
                "have_bars": r.have_bars,
                "missing_bars": r.missing_bars,
                "cause": r.cause,
                "gaps": [_gap_dict(g) for g in r.gaps],
                "flat_tail": r.flat_tail,
            }
            for r in report.rows
        ],
        "split_coverage": [
            {
                "symbol": c.symbol,
                "block": c.block,
                "start_utc": c.start_utc,
                "end_utc": c.end_utc,
                "expected_1m": c.expected_1m,
                "have_1m": c.have_1m,
            }
            for c in report.split_coverage
        ],
        "trade_floor_note": report.trade_floor_note,
        "depth_extension_note": report.depth_extension_note,
        "missing_data": report.missing_data,
    }


def render_report_table(report: SufficiencyReport) -> str:
    """Human-readable report: one line per row, gap lines, then the notes."""
    depth = ", ".join(f"{k}={v} months" for k, v in sorted(report.depth_months.items()))
    lines = [
        f"sufficiency: run_date {report.run_date.isoformat()} depth {depth}; "
        f"1h/4h dataset {report.dataset_start.isoformat()}..{report.dataset_end.isoformat()}"
    ]
    headers = ("DATASET", "SYMBOL", "INTERVAL", "SOURCE", "EXPECTED", "HAVE", "MISSING", "CAUSE")
    body = [
        (
            r.dataset,
            r.symbol,
            r.interval,
            r.source,
            str(r.expected_bars),
            str(r.have_bars),
            str(r.missing_bars),
            r.cause,
        )
        for r in report.rows
    ]
    widths = [max([len(h), *(len(b[i]) for b in body)]) for i, h in enumerate(headers)]
    numeric = {4, 5, 6}

    def fmt(cells: Sequence[str]) -> str:
        return "  ".join(
            c.rjust(widths[i]) if i in numeric else c.ljust(widths[i])
            for i, c in enumerate(cells)
        ).rstrip()

    lines.append(fmt(headers))
    lines.extend(fmt(b) for b in body)
    for r in report.rows:
        for gap in r.gaps[:_MAX_GAPS_PRINTED]:
            lines.append(
                f"  GAP {r.dataset} {r.symbol} {r.interval} "
                f"{_gap_dict(gap)['start_utc']}..{_gap_dict(gap)['end_utc']} missing {gap.missing}"
            )
        if len(r.gaps) > _MAX_GAPS_PRINTED:
            lines.append(
                f"  GAP {r.dataset} {r.symbol} {r.interval} "
                f"... {len(r.gaps) - _MAX_GAPS_PRINTED} more"
            )
    lines.append(f"NOTE: {report.trade_floor_note}")
    return "\n".join(lines)


def write_report_json(report: SufficiencyReport, path: Path) -> None:
    """Canonical JSON (sorted keys, LF, UTF-8) written through tmp + os.replace."""
    text = json.dumps(report_to_dict(report), sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


_REQUIRED_TOP: Final = (
    "schema",
    "run_date",
    "depth_months",
    "dataset_start",
    "dataset_end",
    "rows",
    "split_coverage",
    "trade_floor_note",
    "depth_extension_note",
    "missing_data",
)
_REQUIRED_ROW: Final = (
    "dataset",
    "symbol",
    "interval",
    "source",
    "expected_start_utc",
    "expected_end_utc",
    "expected_bars",
    "have_bars",
    "missing_bars",
    "cause",
    "gaps",
    "flat_tail",
)


def validate_report_file(path: Path) -> list[str]:
    """Problems found in a written report; an empty list means it is valid."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"{path}: cannot read report ({type(exc).__name__})"]
    if not isinstance(doc, dict):
        return [f"{path}: report is not a JSON object"]
    problems: list[str] = []
    if doc.get("schema") != REPORT_SCHEMA:
        problems.append(f"schema must be {REPORT_SCHEMA!r}, got {doc.get('schema')!r}")
    for key in _REQUIRED_TOP:
        if key not in doc:
            problems.append(f"missing top-level key {key!r}")
    rows = doc.get("rows")
    if not isinstance(rows, list) or not rows:
        problems.append("rows must be a non-empty list")
        rows = []
    any_missing = False
    for index, entry in enumerate(rows):
        if not isinstance(entry, dict):
            problems.append(f"rows[{index}] is not an object")
            continue
        absent = [k for k in _REQUIRED_ROW if k not in entry]
        if absent:
            problems.append(f"rows[{index}] lacks keys {absent}")
            continue
        cause = entry["cause"]
        if cause not in ALL_CAUSES:
            problems.append(f"rows[{index}] has unknown cause {cause!r}")
        any_missing = any_missing or cause in MISSING_DATA_CAUSES
        expected, have, missing = entry["expected_bars"], entry["have_bars"], entry["missing_bars"]
        if not all(isinstance(v, int) for v in (expected, have, missing)):
            problems.append(f"rows[{index}] bar counts must be integers")
        elif missing != max(expected - have, 0):
            problems.append(f"rows[{index}] missing_bars is not expected_bars - have_bars")
    if rows and doc.get("missing_data") is not any_missing:
        problems.append("missing_data does not match the row causes")
    if doc.get("trade_floor_note") != TRADE_FLOOR_NOTE:
        problems.append("trade_floor_note is not the D043 unmeasurable-floor statement")
    note = doc.get("depth_extension_note")
    if note is not None and note != DEPTH_EXTENSION_NOTE:
        problems.append("depth_extension_note is not the D-21 statement")
    return problems
