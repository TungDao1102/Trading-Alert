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

  4. Falls back to the checksum-verified Binance archive, per symbol, for a
     symbol REST no longer serves (`-1121`) or that `exchangeInfo` no longer
     lists, capped at its delivery date or its last archive day (D-08). The
     source of every (dataset, symbol) is recorded and printed. Mark klines
     are only ever taken from REST: an archive-only symbol whose mark REST
     rejects is UNAVAILABLE, never filled from trade data.
  5. Backfills funding history over the 1h/4h dataset range for every universe
     symbol with data (D-23); a funding failure is a gap row, not a crash.
  6. Prints the data-sufficiency report (D-05) and, with `--report-out`, writes
     it as canonical JSON. Exit codes: 0 ok, 1 failure, 2 usage, 3 missing data
     (NOT_BACKFILLED, GAP, UNAVAILABLE). The trade count never sets an exit code.

Fail-closed posture: a symbol whose delivery cannot be established gets NO
window and is reported UNAVAILABLE. Nothing here prints a database URL or
credential: failures print the exception type name only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast

import httpx
import polars as pl
import structlog
from sqlalchemy.orm import Session, sessionmaker
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    FundingTick,
    SymbolFilters,
    is_invalid_symbol_error,
)
from src.data.archive import (
    ArchiveError,
    ArchiveKlineSource,
    archive_last_day,
    make_archive_client,
)
from src.data.backfill import (
    DAY_MS,
    DEPTH_MONTHS_DEFAULT,
    MARK_DATASET,
    TRADE_DATASET,
    BackfillConfig,
    BackfillResult,
    CursorStore,
    DatasetSpec,
    KlineSource,
    MarkKlineSource,
    UniverseBootstrapResult,
    align_to_day_start_ms,
    backfill_universe,
    interval_ms,
    latest_published_day,
    months_before,
    utc_ms,
)
from src.data.collect_list import (
    DEFAULT_COLLECT_LIST_PATH,
    SYMBOL_RE,
    CollectListError,
    load_collect_list,
)
from src.data.collector import (
    AdapterLike,
    FundingHistoryResult,
    _make_sync_engine,
    backfill_funding_history,
)
from src.data.metadata import MetadataWidthError, refresh_symbol_metadata
from src.data.store import DEFAULT_RAW_ROOT, partition_file
from src.data.sufficiency import (
    SOURCE_ARCHIVE,
    SOURCE_REST,
    SOURCE_UNAVAILABLE,
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

# Provenance sidecar next to the cursors: symbols whose trade history came from
# the archive. A complete re-run never asks REST again (nothing left to fetch),
# so without this the report would lose which origin filled a symbol (T-13-45).
SOURCES_FILE_NAME = "_sources.json"

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

    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[FundingTick]: ...


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
    funding: bool = True


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
        return self.start_ms is not None and self.end_ms is not None and self.start_ms < self.end_ms


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
    sources: dict[tuple[str, str], str] = field(default_factory=dict)
    funding: FundingHistoryResult | None = None


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
        # Not in exchangeInfo: REST cannot bound the window. `run_backfill`
        # re-plans such a symbol from the archive (D-08) or reports it UNAVAILABLE.
        return None, None, False, DELIVERY_UNKNOWN
    onboard_ms = utc_ms(filters.onboard_time_utc) if filters.onboard_time_utc is not None else None
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


class _ArchiveAccess:
    """Lazy archive client, cached last-day lookups and one shared kline source."""

    def __init__(self, injected: httpx.AsyncClient | None) -> None:
        self._client = injected
        self._owned = False
        self._last_days: dict[str, date | None] = {}
        self._source: ArchiveKlineSource | None = None

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_archive_client()
            self._owned = True
        return self._client

    async def last_day(self, symbol: str) -> date | None:
        """Latest archived day of `symbol`, or None (also when the archive errors)."""
        if symbol not in self._last_days:
            try:
                self._last_days[symbol] = await archive_last_day(self.client(), symbol)
            except ArchiveError as exc:
                # Type name only; the symbol is reported UNAVAILABLE (fail closed).
                log.error("backfill.archive_lookup_failed", error_type=type(exc).__name__)
                self._last_days[symbol] = None
        return self._last_days[symbol]

    def kline_source(self, search_end_ms: int) -> ArchiveKlineSource:
        if self._source is None:
            self._source = ArchiveKlineSource(self.client(), search_end_ms=search_end_ms)
        return self._source

    async def aclose(self) -> None:
        if self._owned and self._client is not None:
            await self._client.aclose()


def _load_archive_presets(cursor_root: Path) -> set[str]:
    """Symbols an earlier run had to fill from the archive (unreadable file: none)."""
    try:
        doc = json.loads((cursor_root / SOURCES_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(doc, dict):
        return set()
    symbols: set[str] = set()
    for key, value in doc.items():
        dataset, _, symbol = str(key).partition("|")
        if dataset == "trade" and value == SOURCE_ARCHIVE and SYMBOL_RE.match(symbol):
            symbols.add(symbol)
    return symbols


def _save_archive_presets(cursor_root: Path, symbols: set[str]) -> None:
    if not symbols:
        return
    doc = {f"trade|{sym}": SOURCE_ARCHIVE for sym in sorted(symbols)}
    text = json.dumps(doc, sort_keys=True, indent=2) + "\n"
    cursor_root.mkdir(parents=True, exist_ok=True)
    path = cursor_root / SOURCES_FILE_NAME
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _archive_window(
    w: SymbolWindow, *, archive_end_ms: int, run_end_ms: int, depth_start_ms_: int
) -> SymbolWindow:
    """Re-plan `w` for an archive-sourced symbol: capped at the last archive day.

    A window that already ends earlier (a delivery date) keeps its end; one
    without a window starts at the depth start. Any end before the run end is
    terminal, so the partly covered last day is published.
    """
    has = w.has_window and w.start_ms is not None and w.end_ms is not None
    start = w.start_ms if has and w.start_ms is not None else depth_start_ms_
    planned_end = w.end_ms if has and w.end_ms is not None else run_end_ms
    end = min(planned_end, archive_end_ms)
    terminal = end < run_end_ms
    if start >= end:
        return replace(w, start_ms=None, end_ms=None, terminal=True, cause=DELISTED_CAPPED)
    cause = DELISTED_CAPPED if terminal else (w.cause if has else FULL_DEPTH)
    return replace(w, start_ms=start, end_ms=end, terminal=terminal, cause=cause)


def _last_stored_open_ms(raw_root: Path, symbol: str, interval: str) -> int | None:
    """Open time (epoch ms) of the last stored trade bar of one key, or None."""
    day = latest_published_day(raw_root, dataset=TRADE_DATASET, symbol=symbol, interval=interval)
    if day is None:
        return None
    frame = pl.read_parquet(
        partition_file(raw_root, interval, symbol, day), columns=["open_time_utc"]
    )
    latest = frame["open_time_utc"].dt.epoch("ms").max()
    return int(latest) if isinstance(latest, int) else None


async def run_backfill(
    config: BackfillRunConfig,
    *,
    adapter: BackfillAdapter,
    session: Session | None,
    clock: Callable[[], datetime],
    emit: Callable[[str], None] = print,
    archive_client: httpx.AsyncClient | None = None,
) -> BackfillRunReport:
    """Metadata first, then windows, the trade and mark backfill, funding and the report.

    `--dry-run` (config.dry_run) still reads exchangeInfo but writes nothing:
    no metadata row, no cursor, no Parquet file, no klines request, no archive
    request. `archive_client` is injected by tests; otherwise one is created
    lazily (only when a symbol needs the archive) and closed at the end.
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
    depth = {i: config.depth_months.get(i, DEPTH_MONTHS_DEFAULT[i]) for i in intervals}

    depth_text = ", ".join(f"{i}={m} months" for i, m in depth.items())
    header = (
        f"backfill: run_date {run_date.isoformat()} depth {depth_text} "
        f"datasets={','.join(datasets)} universe={len(symbols)} symbols "
        f"pace={config.pace_seconds}s"
    )
    if config.htf_start_date is not None:
        header += (
            f" 1h/4h start {config.htf_start_date.isoformat()} (frozen manifest selection_date)"
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
        outcome = (
            "no window planned" if config.dry_run else "no REST window; the archive is consulted"
        )
        emit(
            f"backfill: missing from exchangeInfo ({len(missing)}): "
            f"{', '.join(missing)} - {outcome}"
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
    assert session is not None

    access = _ArchiveAccess(archive_client)
    try:
        return await _backfill_and_report(
            config,
            adapter=adapter,
            session=session,
            clock=clock,
            emit=emit,
            access=access,
            report=report,
            missing=missing,
            now=now,
        )
    finally:
        await access.aclose()


async def _backfill_and_report(
    config: BackfillRunConfig,
    *,
    adapter: BackfillAdapter,
    session: Session,
    clock: Callable[[], datetime],
    emit: Callable[[str], None],
    access: _ArchiveAccess,
    report: BackfillRunReport,
    missing: tuple[str, ...],
    now: datetime,
) -> BackfillRunReport:
    """Steps 3 to 6 of `run_backfill`: sources, klines, funding, sufficiency report."""
    symbols = tuple(config.symbols)
    intervals = tuple(config.intervals)
    datasets = tuple(config.datasets)
    depth = report.depth_months
    run_date = report.run_date
    run_end_ms = align_to_day_start_ms(utc_ms(now))
    windows = report.windows
    results = report.results

    def depth_of(interval: str) -> int:
        return depth_start_ms(
            interval,
            run_date=run_date,
            depth_months=depth,
            htf_start_date=config.htf_start_date,
        )

    win_by_key: dict[tuple[str, str, str], SymbolWindow] = {
        (w.dataset, w.symbol, w.interval): w for w in windows
    }
    sources: dict[tuple[str, str], str] = {}
    archive_capped: set[tuple[str, str]] = set()  # (symbol, interval) ended by the archive
    archived = _load_archive_presets(config.cursor_root) & set(symbols)

    def adopt_archive(symbol: str, last_day: date) -> None:
        """Route `symbol`'s trade history to the archive, capped at its last day."""
        archive_end_ms = utc_ms(datetime(last_day.year, last_day.month, last_day.day, tzinfo=UTC))
        archive_end_ms += DAY_MS
        sources[("trade", symbol)] = SOURCE_ARCHIVE
        archived.add(symbol)
        for key, w in list(win_by_key.items()):
            if w.symbol != symbol:
                continue
            planned_end = w.end_ms if w.has_window and w.end_ms is not None else run_end_ms
            win_by_key[key] = _archive_window(
                w,
                archive_end_ms=archive_end_ms,
                run_end_ms=run_end_ms,
                depth_start_ms_=depth_of(w.interval),
            )
            if archive_end_ms < planned_end:
                archive_capped.add((symbol, w.interval))
        emit(
            f"backfill: source trade {symbol} {SOURCE_ARCHIVE} "
            f"(last archive day {last_day.isoformat()})"
        )

    # 3. Symbols exchangeInfo no longer lists, or an earlier run took from the archive.
    if "trade" in datasets:
        for symbol in sorted(set(missing) | archived):
            last_day = await access.last_day(symbol)
            if last_day is None:
                archived.discard(symbol)
                for dataset_name in datasets:
                    sources[(dataset_name, symbol)] = SOURCE_UNAVAILABLE
                emit(f"backfill: source {symbol} {SOURCE_UNAVAILABLE} (no REST window, no archive)")
            else:
                adopt_archive(symbol, last_day)

    async def bootstrap(
        source: Any,
        w: SymbolWindow,
        spec: DatasetSpec[Any, Any],
        cursor_store: CursorStore,
    ) -> UniverseBootstrapResult:
        assert w.start_ms is not None and w.end_ms is not None
        return await backfill_universe(
            source,
            symbols=(w.symbol,),
            intervals=(w.interval,),
            end_ms=run_end_ms,
            raw_root=config.raw_root,
            config=BackfillConfig(
                interval_ms=interval_ms(w.interval),
                page_size=PAGE_SIZE,
                pace_seconds=config.pace_seconds,
            ),
            clock=clock,
            cursor_store=cursor_store,
            interval_start_ms={w.interval: depth_of(w.interval)},
            start_floor_ms={w.symbol: w.start_ms},
            end_cap_ms={w.symbol: w.end_ms},
            dataset=spec,
            resume_from_store=True,
        )

    # 4. Backfill each dataset and interval with its own cursor namespace, one
    #    symbol at a time so a REST `-1121` reroutes only that symbol.
    for dataset_name in datasets:
        spec = DATASET_SPECS[dataset_name]
        cursor_store = CursorStore(config.cursor_root, dataset=spec.name)
        for interval in intervals:
            active = [
                current
                for w in windows
                if w.dataset == dataset_name and w.interval == interval
                for current in (win_by_key[(w.dataset, w.symbol, w.interval)],)
                if current.has_window
            ]
            if not active:
                continue
            emit(f"backfill: {dataset_name} {interval} symbols={len(active)}")
            parts: list[UniverseBootstrapResult] = []

            for w in active:
                source_name = sources.get((dataset_name, w.symbol), SOURCE_REST)
                if source_name == SOURCE_UNAVAILABLE:
                    continue
                current = w
                if source_name == SOURCE_REST:
                    try:
                        parts.append(await bootstrap(adapter, current, spec, cursor_store))
                        sources.setdefault((dataset_name, w.symbol), SOURCE_REST)
                        continue
                    except Exception as exc:
                        if not is_invalid_symbol_error(exc):
                            raise
                    # REST no longer serves the symbol (-1121, D-08).
                    if dataset_name == "mark":
                        sources[("mark", w.symbol)] = SOURCE_UNAVAILABLE
                        emit(f"backfill: source mark {w.symbol} {SOURCE_UNAVAILABLE} (REST -1121)")
                        continue
                    last_day = await access.last_day(w.symbol)
                    if last_day is None:
                        sources[("trade", w.symbol)] = SOURCE_UNAVAILABLE
                        emit(
                            f"backfill: source trade {w.symbol} {SOURCE_UNAVAILABLE} "
                            "(REST -1121, no archive)"
                        )
                        continue
                    adopt_archive(w.symbol, last_day)
                    current = win_by_key[(dataset_name, w.symbol, interval)]
                    if not current.has_window:
                        continue
                parts.append(
                    await bootstrap(access.kline_source(run_end_ms), current, spec, cursor_store)
                )
            merged_keys: dict[tuple[str, str], BackfillResult] = {}
            for part in parts:
                merged_keys.update(part.per_key)
            result = UniverseBootstrapResult(
                per_key=merged_keys,
                total_rows=sum(part.total_rows for part in parts),
                total_pages=sum(part.total_pages for part in parts),
                total_rejections=sum(part.total_rejections for part in parts),
            )
            results[(dataset_name, interval)] = result
            emit(
                f"backfill: done {dataset_name} {interval} rows={result.total_rows} "
                f"pages={result.total_pages} rejections={result.total_rejections}"
            )

    # An archive-capped end is the last archive DAY; the last bar inside it is the
    # real end of the history, so the report expects up to that bar only.
    for symbol, interval in sorted(archive_capped):
        last_open = _last_stored_open_ms(config.raw_root, symbol, interval)
        if last_open is None:
            continue
        trimmed_end = last_open + interval_ms(interval)
        for dataset_name in datasets:
            key = (dataset_name, symbol, interval)
            planned = win_by_key.get(key)
            if (
                planned is not None
                and planned.has_window
                and planned.end_ms is not None
                and trimmed_end < planned.end_ms
            ):
                win_by_key[key] = replace(planned, end_ms=trimmed_end)

    final_windows = tuple(win_by_key[(w.dataset, w.symbol, w.interval)] for w in windows)
    for w in final_windows:
        if w.has_window:
            sources.setdefault((w.dataset, w.symbol), SOURCE_REST)
    _save_archive_presets(
        config.cursor_root, {s for s in archived if sources.get(("trade", s)) == SOURCE_ARCHIVE}
    )
    for dataset_name in datasets:
        listed = " ".join(
            f"{sym}={src}" for (ds, sym), src in sorted(sources.items()) if ds == dataset_name
        )
        emit(f"backfill: sources {dataset_name} {listed}".rstrip())

    # 5. Funding history over the 1h/4h dataset range (D-23).
    htf_start_ms = depth_of("1h")
    funding_result: FundingHistoryResult | None = None
    if config.funding:
        rows_per_symbol: dict[str, int] = {}
        pages = gaps = 0
        truncated: list[str] = []
        for symbol in symbols:
            own = [w for w in final_windows if w.symbol == symbol and w.has_window]
            if not own or sources.get(("trade", symbol)) == SOURCE_UNAVAILABLE:
                continue
            caps = [w.end_ms for w in own if w.terminal and w.end_ms is not None]
            funding_end_ms = min([run_end_ms, *caps])
            if funding_end_ms <= htf_start_ms:
                continue
            # The walk only calls `funding_rate`; the real adapter has the full surface.
            outcome = await backfill_funding_history(
                cast(AdapterLike, adapter),
                session,
                symbols=[symbol],
                start_ms=htf_start_ms,
                end_ms=funding_end_ms,
                raw_root=config.raw_root,
                observed_utc=now,
            )
            rows_per_symbol.update(outcome.rows_per_symbol)
            pages += outcome.pages
            gaps += outcome.gaps_recorded
            truncated.extend(outcome.truncated_symbols)
            emit(
                f"backfill: funding {symbol} ticks={outcome.rows_per_symbol.get(symbol, 0)} "
                f"pages={outcome.pages} gaps={outcome.gaps_recorded}"
            )
        funding_result = FundingHistoryResult(
            rows_per_symbol=rows_per_symbol,
            pages=pages,
            gaps_recorded=gaps,
            truncated_symbols=tuple(truncated),
        )

    # 6. The data-sufficiency report (D-05): what depth exists, and why any is short.
    sufficiency = build_sufficiency_report(
        config.raw_root,
        final_windows,
        run_date=run_date,
        depth_months=depth,
        dataset_start=datetime.fromtimestamp(htf_start_ms / 1000, tz=UTC).date(),
        dataset_end=run_date,
        sources=sources,
    )
    for line in render_report_table(sufficiency).splitlines():
        emit(line)
    if config.report_out is not None:
        write_report_json(sufficiency, config.report_out)
        emit(f"sufficiency: report written to {config.report_out.as_posix()}")
    return replace(
        report,
        windows=final_windows,
        sufficiency=sufficiency,
        sources=sources,
        funding=funding_result,
    )


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
        "--funding",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Backfill funding history over the 1h/4h dataset range for every universe "
            "symbol (default: on; --no-funding skips it)."
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
        funding=bool(args.funding),
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
        report = asyncio.run(run_backfill(config, adapter=adapter, session=session, clock=_utc_now))
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
