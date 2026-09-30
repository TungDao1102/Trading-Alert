"""History-depth backfill CLI (Phase 13, plan 13-07; D-04, D-10, D-26, F-122, F-906).

`python -m src.data.backfill_cli` bootstraps the research history:

  1. Reads `exchangeInfo` and writes versioned `symbol_metadata` rows for the
     resolved universe FIRST (always with a universe filter, D-29), so the tick,
     step and notional rules of every research symbol are stored point in time.
  2. Plans one explicit window per (dataset, symbol, interval): the start is
     `max(depth start, onboard time)` and, for a delivered non-TRADING
     contract, the end is its `deliveryDate` as a TERMINAL end, so the flat
     zero-volume bars the exchange keeps serving after delivery are never
     published (D-26, research Pitfall 1).
  3. Backfills trade and mark klines through the closed-day paginator with a
     separate cursor per dataset. The start is also floored at the day after
     the latest published partition, so an interrupted run resumes and never
     re-publishes a stored day (D-04).

Depth defaults (D-04): 1m for 12 months, 1h/4h for 24 months before the run
date; overridable by flags and printed in the run header. When the
research-universe manifest is FROZEN its `selection_date` is the 1h/4h start
for every symbol (D-07) and its symbols join the backfill universe.

Fail-closed posture: a symbol whose delivery cannot be established, or that
is missing from `exchangeInfo`, gets NO window and is listed in the run
output; the archive fallback and the data-sufficiency report arrive in plan
13-08. Nothing here prints a database URL or credential: failures print the
exception type name only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import structlog
from sqlalchemy.orm import Session, sessionmaker
from src.adapters.binance_usdm import BinanceUsdmAdapter, SymbolFilters
from src.data.backfill import (
    DEPTH_MONTHS_DEFAULT,
    MARK_DATASET,
    TRADE_DATASET,
    BackfillConfig,
    CursorStore,
    DatasetSpec,
    KlineSource,
    MarkKlineSource,
    UniverseBootstrapResult,
    align_to_day_start_ms,
    backfill_universe,
    interval_ms,
    months_before,
    utc_ms,
)
from src.data.collect_list import (
    DEFAULT_COLLECT_LIST_PATH,
    SYMBOL_RE,
    CollectListError,
    load_collect_list,
)
from src.data.collector import _make_sync_engine
from src.data.metadata import MetadataWidthError, refresh_symbol_metadata
from src.data.store import DEFAULT_RAW_ROOT
from src.data.sufficiency import (
    SufficiencyReport,
    build_sufficiency_report,
    render_report_table,
    write_report_json,
)

log = structlog.get_logger()

_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)

# Dataset names accepted by --datasets, mapped to the paginator's dataset spec.
DATASET_SPECS: dict[str, DatasetSpec[Any, Any]] = {
    "trade": TRADE_DATASET,
    "mark": MARK_DATASET,
}
DATASET_CHOICES = tuple(DATASET_SPECS)
INTERVAL_CHOICES = tuple(DEPTH_MONTHS_DEFAULT)

# The manifest is read with tomllib here (src/ must not import scripts/). The
# path is relative to the working directory, like the collect list default.
DEFAULT_MANIFEST_PATH = Path("docs") / "research" / "universe" / "research-universe-v1.toml"

# Resume state lives next to the raw store so the Compose rawdata volume keeps
# it across container restarts. The name starts with "_" and holds no
# `interval=*` directory, so the candles_v1 glob and the builder never read it.
CURSOR_DIR_NAME = "_cursors"

# limit-1000 pages cost weight 5: 0.25 s per page keeps a zero-latency run at
# or below about 1,200 weight per minute, half of the 2,400/min IP budget.
DEFAULT_PACE_SECONDS = 0.25
PAGE_SIZE = 1000

# Window causes (13-RESEARCH Pattern 4).
ONBOARD_LIMITED = "ONBOARD_LIMITED"
DELISTED_CAPPED = "DELISTED_CAPPED"
NOT_LISTED_IN_RANGE = "NOT_LISTED_IN_RANGE"
DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"
FULL_DEPTH = "FULL_DEPTH"


class BackfillConfigError(ValueError):
    """A usage or configuration defect (exit code 2); the message is safe to print."""


class BackfillAdapter(KlineSource, MarkKlineSource, Protocol):
    """The adapter surface the CLI needs: exchangeInfo plus both kline datasets."""

    async def exchange_info(self) -> list[SymbolFilters]: ...


def _utc_now() -> datetime:
    """Wall-clock seam for the CLI (tests patch this)."""
    return datetime.now(UTC)


def _iso_ms(ms: int) -> str:
    return (_EPOCH_UTC + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%MZ")


def _day_start_ms(day: date) -> int:
    return utc_ms(datetime(day.year, day.month, day.day, tzinfo=UTC))


# --------------------------------------------------------------------------- #
# Value objects.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BackfillRunConfig:
    """Everything one run needs; built by `main` from the flags."""

    symbols: Sequence[str]
    intervals: Sequence[str]
    datasets: Sequence[str]
    depth_months: Mapping[str, int]
    htf_start_date: date | None
    raw_root: Path
    cursor_root: Path
    pace_seconds: float
    dry_run: bool
    report_out: Path | None = None


@dataclass(frozen=True)
class SymbolWindow:
    """The planned fetch window of one (dataset, symbol, interval).

    `start_ms` / `end_ms` are None when the symbol gets NO window (cause
    `DELIVERY_UNKNOWN` or `NOT_LISTED_IN_RANGE`, or an empty capped window):
    nothing is fetched or published for it.
    """

    dataset: str
    symbol: str
    interval: str
    start_ms: int | None
    end_ms: int | None
    terminal: bool
    cause: str

    @property
    def has_window(self) -> bool:
        return (
            self.start_ms is not None
            and self.end_ms is not None
            and self.start_ms < self.end_ms
        )


@dataclass(frozen=True)
class BackfillRunReport:
    """What one run planned and did (dry runs have empty `results`)."""

    run_date: date
    depth_months: dict[str, int]
    windows: tuple[SymbolWindow, ...]
    metadata_rows: int
    missing_from_exchange_info: tuple[str, ...]
    results: dict[tuple[str, str], UniverseBootstrapResult]
    sufficiency: SufficiencyReport | None = None


# --------------------------------------------------------------------------- #
# Universe resolution.
# --------------------------------------------------------------------------- #


def _read_manifest(path: Path) -> tuple[list[str], date | None]:
    """Symbols and 1h/4h start of a FROZEN manifest; a DRAFT contributes nothing."""
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BackfillConfigError(
            f"{path}: cannot read research-universe manifest ({type(exc).__name__})"
        ) from exc
    status = doc.get("status")
    if status == "DRAFT":
        return [], None
    if status != "FROZEN":
        raise BackfillConfigError(
            f"{path}: manifest status must be DRAFT or FROZEN, got {status!r}"
        )
    raw_symbols = doc.get("symbols")
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raise BackfillConfigError(f"{path}: FROZEN manifest has no symbols")
    symbols: list[str] = []
    for sym in raw_symbols:
        if not isinstance(sym, str) or not SYMBOL_RE.match(sym):
            raise BackfillConfigError(
                f"{path}: invalid manifest symbol {sym!r} (must match {SYMBOL_RE.pattern})"
            )
        symbols.append(sym)
    selection = doc.get("selection_date")
    if not isinstance(selection, str):
        raise BackfillConfigError(f"{path}: FROZEN manifest has no selection_date")
    try:
        selection_date = date.fromisoformat(selection)
    except ValueError as exc:
        raise BackfillConfigError(
            f"{path}: selection_date {selection!r} is not an ISO date"
        ) from exc
    return symbols, selection_date


def resolve_universe(
    collect_list_path: Path,
    manifest_path: Path | None,
    explicit: Sequence[str] | None,
) -> tuple[list[str], date | None]:
    """Resolve the backfill symbols and the 1h/4h start date.

    Default: the collect list union the symbols of a FROZEN manifest (D-07);
    a DRAFT manifest contributes no symbols and no start. An explicit list
    (`--symbols`) replaces that union, but the 1h/4h start still comes from a
    FROZEN manifest when one is given. Every symbol must match `SYMBOL_RE`
    because it reaches paths and URLs.
    """
    frozen_symbols: list[str] = []
    htf_start: date | None = None
    if manifest_path is not None:
        frozen_symbols, htf_start = _read_manifest(manifest_path)
    if explicit is not None:
        if not explicit:
            raise BackfillConfigError("--symbols is empty; refusing to backfill nothing")
        for sym in explicit:
            if not SYMBOL_RE.match(sym):
                raise BackfillConfigError(
                    f"--symbols symbol {sym!r} must match {SYMBOL_RE.pattern}"
                )
        return sorted(set(explicit)), htf_start
    collect = load_collect_list(collect_list_path).symbols
    return sorted(set(collect) | set(frozen_symbols)), htf_start


# --------------------------------------------------------------------------- #
# Window planning.
# --------------------------------------------------------------------------- #


def _validate_choices(name: str, values: Sequence[str], allowed: Sequence[str]) -> None:
    if not values:
        raise BackfillConfigError(f"{name} is empty")
    for value in values:
        if value not in allowed:
            raise BackfillConfigError(
                f"unknown {name} value {value!r}; expected one of {sorted(allowed)}"
            )


def depth_start_ms(
    interval: str,
    *,
    run_date: date,
    depth_months: Mapping[str, int],
    htf_start_date: date | None,
) -> int:
    """UTC-midnight start of the depth window for one interval.

    1m always counts `depth_months` back from the run date; 1h/4h start at the
    FROZEN manifest's selection date when there is one (D-07), else count back.
    """
    if interval != "1m" and htf_start_date is not None:
        return _day_start_ms(htf_start_date)
    months = depth_months.get(interval, DEPTH_MONTHS_DEFAULT[interval])
    return _day_start_ms(months_before(run_date, months))


def _plan_key(
    filters: SymbolFilters | None, *, depth_start: int, run_end_ms: int
) -> tuple[int | None, int | None, bool, str]:
    """(start_ms, end_ms, terminal, cause) for one symbol and interval."""
    if filters is None:
        # Not in exchangeInfo: the REST endpoint cannot bound the window
        # (13-08 adds the archive fallback), so nothing is published.
        return None, None, False, DELIVERY_UNKNOWN
    onboard_ms = (
        utc_ms(filters.onboard_time_utc) if filters.onboard_time_utc is not None else None
    )
    if onboard_ms is not None and onboard_ms >= run_end_ms:
        return None, None, False, NOT_LISTED_IN_RANGE
    start = depth_start if onboard_ms is None else max(depth_start, onboard_ms)
    end = run_end_ms
    terminal = False
    if filters.status != "TRADING":
        if filters.delivery_date_ms is None:
            return None, None, False, DELIVERY_UNKNOWN
        if filters.delivery_date_ms < run_end_ms:
            end = filters.delivery_date_ms
            terminal = True
    if start >= end:
        return None, None, False, DELISTED_CAPPED if terminal else NOT_LISTED_IN_RANGE
    if terminal:
        cause = DELISTED_CAPPED
    elif onboard_ms is not None and onboard_ms > depth_start:
        cause = ONBOARD_LIMITED
    else:
        cause = FULL_DEPTH
    return start, end, terminal, cause


def plan_windows(
    filters_by_symbol: Mapping[str, SymbolFilters],
    *,
    symbols: Sequence[str],
    intervals: Sequence[str],
    datasets: Sequence[str],
    run_date: date,
    now_ms: int,
    depth_months: Mapping[str, int],
    htf_start_date: date | None,
) -> list[SymbolWindow]:
    """One `SymbolWindow` per (dataset, interval, symbol), in that order.

    The end of every window is at most the start of the run's UTC day (only
    closed days are published). Mark windows equal the trade windows for the
    same symbol and interval, so mark rows before onboard or after delivery
    are never requested. Symbols with no window keep their cause in the list.
    """
    _validate_choices("--intervals", intervals, INTERVAL_CHOICES)
    _validate_choices("--datasets", datasets, DATASET_CHOICES)
    run_end_ms = align_to_day_start_ms(now_ms)
    planned: dict[tuple[str, str], tuple[int | None, int | None, bool, str]] = {}
    for interval in intervals:
        start = depth_start_ms(
            interval,
            run_date=run_date,
            depth_months=depth_months,
            htf_start_date=htf_start_date,
        )
        for symbol in symbols:
            planned[(symbol, interval)] = _plan_key(
                filters_by_symbol.get(symbol), depth_start=start, run_end_ms=run_end_ms
            )
    windows: list[SymbolWindow] = []
    for dataset in datasets:
        for interval in intervals:
            for symbol in symbols:
                start_ms, end_ms, terminal, cause = planned[(symbol, interval)]
                windows.append(
                    SymbolWindow(
                        dataset=dataset,
                        symbol=symbol,
                        interval=interval,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        terminal=terminal,
                        cause=cause,
                    )
                )
    return windows


# --------------------------------------------------------------------------- #
# Run.
# --------------------------------------------------------------------------- #


def _window_line(w: SymbolWindow) -> str:
    if w.has_window and w.start_ms is not None and w.end_ms is not None:
        span = f"{_iso_ms(w.start_ms)}..{_iso_ms(w.end_ms)}"
        tail = " terminal" if w.terminal else ""
        return f"backfill: window {w.dataset} {w.symbol} {w.interval} {span} {w.cause}{tail}"
    return f"backfill: window {w.dataset} {w.symbol} {w.interval} none {w.cause}"


async def run_backfill(
    config: BackfillRunConfig,
    *,
    adapter: BackfillAdapter,
    session: Session | None,
    clock: Callable[[], datetime],
    emit: Callable[[str], None] = print,
) -> BackfillRunReport:
    """Metadata first, then windows, then the trade and mark backfill.

    `--dry-run` (config.dry_run) still reads exchangeInfo but writes nothing:
    no metadata row, no cursor, no Parquet file, no klines request.
    """
    symbols = tuple(config.symbols)
    intervals = tuple(config.intervals)
    datasets = tuple(config.datasets)
    _validate_choices("--intervals", intervals, INTERVAL_CHOICES)
    _validate_choices("--datasets", datasets, DATASET_CHOICES)
    if not symbols:
        raise BackfillConfigError("no symbols to backfill")
    if session is None and not config.dry_run:
        raise BackfillConfigError("a database session is required unless --dry-run")

    now = clock()
    now_ms = utc_ms(now)
    run_date = now.astimezone(UTC).date()
    run_end_ms = align_to_day_start_ms(now_ms)
    depth = {i: config.depth_months.get(i, DEPTH_MONTHS_DEFAULT[i]) for i in intervals}

    depth_text = ", ".join(f"{i}={m} months" for i, m in depth.items())
    header = (
        f"backfill: run_date {run_date.isoformat()} depth {depth_text} "
        f"datasets={','.join(datasets)} universe={len(symbols)} symbols "
        f"pace={config.pace_seconds}s"
    )
    if config.htf_start_date is not None:
        header += (
            f" 1h/4h start {config.htf_start_date.isoformat()} "
            "(frozen manifest selection_date)"
        )
    if config.dry_run:
        header += " DRY-RUN"
    emit(header)

    # 1. exchangeInfo, then versioned metadata rows for the universe (D-10, D-29).
    filters = await adapter.exchange_info()
    by_symbol = {f.symbol: f for f in filters}
    missing = tuple(sorted(s for s in symbols if s not in by_symbol))
    metadata_rows = 0
    if not config.dry_run:
        assert session is not None  # guarded above: only dry runs may omit it
        metadata_rows = refresh_symbol_metadata(
            session, filters, observed_at=now, universe=set(symbols)
        )
        emit(f"backfill: metadata rows inserted {metadata_rows}")
    if missing:
        emit(
            f"backfill: missing from exchangeInfo ({len(missing)}): {', '.join(missing)} "
            "- no window planned"
        )

    # 2. One explicit window per (dataset, symbol, interval).
    windows = plan_windows(
        by_symbol,
        symbols=symbols,
        intervals=intervals,
        datasets=datasets,
        run_date=run_date,
        now_ms=now_ms,
        depth_months=depth,
        htf_start_date=config.htf_start_date,
    )
    for window in windows:
        emit(_window_line(window))

    results: dict[tuple[str, str], UniverseBootstrapResult] = {}
    report = BackfillRunReport(
        run_date=run_date,
        depth_months=depth,
        windows=tuple(windows),
        metadata_rows=metadata_rows,
        missing_from_exchange_info=missing,
        results=results,
    )
    if config.dry_run:
        return report

    # 3. Backfill each dataset and interval with its own cursor namespace.
    for dataset_name in datasets:
        spec = DATASET_SPECS[dataset_name]
        cursor_store = CursorStore(config.cursor_root, dataset=spec.name)
        for interval in intervals:
            active = [
                w
                for w in windows
                if w.dataset == dataset_name and w.interval == interval and w.has_window
            ]
            if not active:
                continue
            start_floor = {w.symbol: w.start_ms for w in active if w.start_ms is not None}
            end_cap = {w.symbol: w.end_ms for w in active if w.end_ms is not None}
            interval_start = depth_start_ms(
                interval,
                run_date=run_date,
                depth_months=depth,
                htf_start_date=config.htf_start_date,
            )
            emit(f"backfill: {dataset_name} {interval} symbols={len(active)}")
            result = await backfill_universe(
                adapter,
                symbols=tuple(w.symbol for w in active),
                intervals=(interval,),
                end_ms=run_end_ms,
                raw_root=config.raw_root,
                config=BackfillConfig(
                    interval_ms=interval_ms(interval),
                    page_size=PAGE_SIZE,
                    pace_seconds=config.pace_seconds,
                ),
                clock=clock,
                cursor_store=cursor_store,
                interval_start_ms={interval: interval_start},
                start_floor_ms=start_floor,
                end_cap_ms=end_cap,
                dataset=spec,
                resume_from_store=True,
            )
            results[(dataset_name, interval)] = result
            emit(
                f"backfill: done {dataset_name} {interval} rows={result.total_rows} "
                f"pages={result.total_pages} rejections={result.total_rejections}"
            )

    # 4. The data-sufficiency report (D-05): what depth exists, and why any is short.
    htf_start_ms = depth_start_ms(
        "1h", run_date=run_date, depth_months=depth, htf_start_date=config.htf_start_date
    )
    sufficiency = build_sufficiency_report(
        config.raw_root,
        windows,
        run_date=run_date,
        depth_months=depth,
        dataset_start=datetime.fromtimestamp(htf_start_ms / 1000, tz=UTC).date(),
        dataset_end=run_date,
        sources={},
    )
    for line in render_report_table(sufficiency).splitlines():
        emit(line)
    if config.report_out is not None:
        write_report_json(sufficiency, config.report_out)
        emit(f"sufficiency: report written to {config.report_out.as_posix()}")
    return replace(report, sufficiency=sufficiency)


# --------------------------------------------------------------------------- #
# Entrypoint.
# --------------------------------------------------------------------------- #


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.data.backfill_cli",
        description=(
            "History-depth backfill (D-04): versioned symbol metadata first, then "
            "trade and mark klines over each symbol's real trading life. "
            "Defaults: 1m for 12 months, 1h/4h for 24 months before the run date."
        ),
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Explicit symbols (default: the collect list union a FROZEN manifest).",
    )
    parser.add_argument(
        "--collect-list",
        type=Path,
        default=DEFAULT_COLLECT_LIST_PATH,
        help=f"Collect list TOML (default: {DEFAULT_COLLECT_LIST_PATH.as_posix()}).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help=(
            "Research-universe manifest; when FROZEN its symbols join the universe "
            "and its selection_date is the 1h/4h start "
            f"(default: {DEFAULT_MANIFEST_PATH.as_posix()})."
        ),
    )
    parser.add_argument(
        "--intervals",
        nargs="+",
        default=list(INTERVAL_CHOICES),
        help=f"Intervals to backfill (default: {' '.join(INTERVAL_CHOICES)}).",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=list(DATASET_CHOICES),
        help=f"Datasets to backfill (default: {' '.join(DATASET_CHOICES)}).",
    )
    parser.add_argument(
        "--depth-1m-months",
        type=int,
        default=DEPTH_MONTHS_DEFAULT["1m"],
        help="1m history depth in months before the run date (default: 12).",
    )
    parser.add_argument(
        "--depth-htf-months",
        type=int,
        default=DEPTH_MONTHS_DEFAULT["1h"],
        help="1h/4h history depth in months before the run date (default: 24).",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=DEFAULT_RAW_ROOT,
        help="Parquet raw-store root (default: data/raw).",
    )
    parser.add_argument(
        "--cursor-root",
        type=Path,
        default=None,
        help="Cursor directory for resume state (default: <raw-root>/_cursors).",
    )
    parser.add_argument(
        "--pace-seconds",
        type=float,
        default=DEFAULT_PACE_SECONDS,
        help=(
            "Sleep between pages (default: 0.25 s, about 1,200 weight per minute "
            "at page size 1000, half the IP budget)."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Sync DB URL (default: DATABASE_URL_SYNC / DATABASE_URL env).",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=None,
        help=(
            "Write the data-sufficiency report as canonical JSON to this path "
            "(the table is always printed after a backfill)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read exchangeInfo and print every window; write and fetch nothing.",
    )
    return parser.parse_args(argv)


def _build_config(args: argparse.Namespace) -> BackfillRunConfig:
    _validate_choices("--intervals", args.intervals, INTERVAL_CHOICES)
    _validate_choices("--datasets", args.datasets, DATASET_CHOICES)
    if args.depth_1m_months < 1 or args.depth_htf_months < 1:
        raise BackfillConfigError("--depth-1m-months and --depth-htf-months must be >= 1")
    if args.pace_seconds < 0:
        raise BackfillConfigError("--pace-seconds must be >= 0")
    symbols, htf_start = resolve_universe(args.collect_list, args.manifest, args.symbols)
    raw_root = Path(args.raw_root)
    cursor_root = (
        Path(args.cursor_root) if args.cursor_root is not None else raw_root / CURSOR_DIR_NAME
    )
    return BackfillRunConfig(
        symbols=symbols,
        intervals=list(dict.fromkeys(args.intervals)),
        datasets=list(dict.fromkeys(args.datasets)),
        depth_months={
            "1m": args.depth_1m_months,
            "1h": args.depth_htf_months,
            "4h": args.depth_htf_months,
        },
        htf_start_date=htf_start,
        raw_root=raw_root,
        cursor_root=cursor_root,
        pace_seconds=float(args.pace_seconds),
        dry_run=bool(args.dry_run),
        report_out=Path(args.report_out) if args.report_out is not None else None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the backfill.

    Exit 0 on success, 1 on failure, 2 on usage/config errors and 3 when the
    data-sufficiency report shows missing data (NOT_BACKFILLED, GAP or
    UNAVAILABLE). The trade count never sets an exit code (D-05).
    """
    args = _parse_args(argv)
    try:
        config = _build_config(args)
    except (BackfillConfigError, CollectListError) as exc:
        print(f"backfill: {exc}", file=sys.stderr)
        return 2

    session: Session | None = None
    engine = None
    if not config.dry_run:
        try:
            engine = _make_sync_engine(args.database_url)
        except RuntimeError:
            # The message names env vars, never a value; print our own anyway.
            print(
                "backfill: no database URL (pass --database-url or set "
                "DATABASE_URL_SYNC / DATABASE_URL)",
                file=sys.stderr,
            )
            return 2
        except Exception as exc:
            print(
                f"backfill: cannot create database engine ({type(exc).__name__})",
                file=sys.stderr,
            )
            return 2
        session = sessionmaker(bind=engine)()

    adapter = BinanceUsdmAdapter()
    try:
        report = asyncio.run(
            run_backfill(config, adapter=adapter, session=session, clock=_utc_now)
        )
    except BackfillConfigError as exc:
        print(f"backfill: {exc}", file=sys.stderr)
        return 2
    except MetadataWidthError as exc:
        # Names the symbol and field only; safe to print.
        print(f"backfill: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Type name only: a database error message can embed the connection URL.
        print(f"backfill: failed ({type(exc).__name__})", file=sys.stderr)
        log.error("backfill.failed", error_type=type(exc).__name__)
        return 1
    finally:
        if session is not None:
            session.close()
        if engine is not None:
            engine.dispose()

    total_rows = sum(r.total_rows for r in report.results.values())
    print(
        f"backfill: complete rows={total_rows} windows={len(report.windows)} "
        f"missing_from_exchange_info={len(report.missing_from_exchange_info)}"
    )
    if report.sufficiency is not None and report.sufficiency.missing_data:
        print(
            "backfill: data is missing (NOT_BACKFILLED, GAP or UNAVAILABLE rows); exit 3",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
