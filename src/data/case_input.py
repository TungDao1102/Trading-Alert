"""Published Parquet -> backtest case-input v2 builder (M4, D-17, D-18, D-22; Phase 14 D-13).

`build_case_input_data` reads ONLY the immutable published partitions for one or
more symbols and a whole-UTC-day range and returns the case-input v2 keys
(`backtest-case/2`: schema, sorted symbols, strategy and context bars, funding per
symbol, `data_window`, `dataset_id`, `allowed_gaps`), so a backtest runs straight from
the store without hand-built fixtures. The caller adds the scenario keys (strategy
identity, `account_state`, `cost_model`, `constraint_history`, `scripted_plans`).

1m minutes (D-13, D-31): by default the case carries NO minute rows; the caller passes a
lazy `ParquetMinuteSource` (src/data/minute_source.py) to `engine.simulate`.
`with_minute_rows=True` adds `trade_bars_1m` and `mark_bars_1m` rows for small ranges.
The per-signal-bar intrabar map of the v1 case is gone.

Design rules (13-CONTEXT D-17..D-22):

- Whole UTC days only. The caller passes `as_of_day_utc`; a range ending after
  the start of that day is refused, so the current (still forming) UTC day and
  live tick files are never read. The module takes no wall clock.
- Decimal-safe: every price/volume/rate leaves this module as a plain-notation
  string (`format(Decimal, "f")`), every timestamp as an ISO-8601 UTC string.
  There is no float anywhere in the path.
- Dataset identity (D-18): `dataset_id` is sha256 over the sorted list of
  `{repo-relative posix path, sha256 of file bytes}` for every file of the requested
  series, symbols and day range: the bars, every funding file, and (when the 1m series
  are requested) every 1m trade and mark partition, whether the rows are embedded or
  served lazily. A lazy `ParquetMinuteSource` can only open files of that set, so the id
  covers every file a run reads. The same partitions give the same id; a changed, added
  or removed partition changes it. A dataset that is re-written (for example after a
  Polars upgrade changes the Parquet bytes) is a NEW dataset by design (13-RESEARCH A4).
- Funding cadence (D-36, D-15): each symbol funding cadence (8 h or 4 h) is inferred
  from the observed spacing; a hole is two observations further apart than
  `FUNDING_MAX_CADENCE + FUNDING_JITTER` (the engine tolerance, equal by test to the
  `src/data/coverage` constants). Holes fail closed unless passed as `allow_gaps`.
- Package purity (D-12): Polars and DuckDB live here in `src/data`; nothing under
  `src/backtest` imports this module (this module may import the pure backtest
  constants). Phase 14 consumes bars, mark, funding and minutes; open interest stays
  inert (it is read and hashed but has no case-input v2 key).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
from src.backtest.case import CASE_INPUT_SCHEMA
from src.backtest.semantics import FUNDING_JITTER, FUNDING_MAX_CADENCE
from src.data.coverage import (
    DEFAULT_FUNDING_INTERVAL_MS,
    DEFAULT_OI_INTERVAL_MS,
    TICK_GAP_FACTOR,
    GapRange,
    gap_ranges_for_files,
)
from src.data.minute_source import SYMBOL_RE as _SYMBOL_RE
from src.data.quality import INTERVAL_MS
from src.data.store import MARK_DATASET_DIR, partition_file, read_partitions
from src.domain.canonical import sha256_hex

SERIES_ALL: tuple[str, ...] = (
    "trade",
    "intrabar_1m",
    "mark_1m",
    "funding",
    "open_interest",
)

_HASH_CHUNK = 1 << 20
_MS = timedelta(milliseconds=1)

# D-36: two funding observations further apart than the max cadence plus jitter are a hole.
# The engine coverage check uses the same sum (src/backtest/funding.py).
FUNDING_TOLERANCE_MS: int = (FUNDING_MAX_CADENCE + FUNDING_JITTER) // _MS
_FOUR_HOUR_MS = 4 * 3_600_000

Row = dict[str, str | int | None]

_BAR_COLUMNS: tuple[str, ...] = (
    "symbol",
    "interval",
    "open_time_utc",
    "close_time_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
_MARK_COLUMNS: tuple[str, ...] = (
    "symbol",
    "interval",
    "open_time_utc",
    "close_time_utc",
    "open",
    "high",
    "low",
    "close",
    "price_tick_count",
)
_FUNDING_COLUMNS: tuple[str, ...] = (
    "symbol",
    "funding_time_utc",
    "funding_rate",
    "mark_price",
)
_OI_COLUMNS: tuple[str, ...] = (
    "symbol",
    "observed_at_utc",
    "open_interest",
    "source",
)


class CaseInputError(ValueError):
    """The case input cannot be built from the requested arguments or store."""


class CaseInputRangeError(CaseInputError):
    """The requested range is not a closed whole-UTC-day range (D-17)."""


class CaseInputGapError(CaseInputError):
    """A requested series has an unresolved gap; nothing is padded (D-19).

    `gaps` lists every unacknowledged `GapRange`; pass the ones you have
    inspected back as `allow_gaps` to proceed with a recorded hole.
    """

    def __init__(self, gaps: Sequence[GapRange]) -> None:
        self.gaps: tuple[GapRange, ...] = tuple(gaps)
        detail = "; ".join(
            f"{g.series}/{g.interval} {g.start_utc.isoformat()}..{g.end_utc.isoformat()}"
            f" missing={g.missing}"
            for g in self.gaps
        )
        super().__init__(f"unresolved gaps in the published store: {detail}")


# --------------------------------------------------------------------------- #
# Output value object.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CaseInputData:
    """Everything the engine (and the experiment record) needs from the store.

    `trade_bars_1m` and `mark_bars_1m` are empty unless the builder ran with
    `with_minute_rows=True`; the lazy path serves minutes from a `ParquetMinuteSource`.
    """

    symbols: tuple[str, ...]
    strategy_interval: str
    context_interval: str
    start_utc: datetime
    end_utc: datetime
    series: tuple[str, ...]
    strategy_bars: tuple[Row, ...]
    context_bars: tuple[Row, ...]
    trade_bars_1m: tuple[Row, ...]
    mark_bars_1m: tuple[Row, ...]
    funding: tuple[Row, ...]
    open_interest: tuple[Row, ...]
    files: tuple[str, ...]
    dataset_id: str
    allowed_gaps: tuple[GapRange, ...]
    with_minute_rows: bool = False

    def to_case_input(self, **scenario: Any) -> dict[str, Any]:
        """Return the case-input v2 dict: builder keys plus `scenario`.

        A scenario key that collides with a builder key is refused: the store owns the
        market data, the caller owns the strategy identity and the account, cost and
        constraint scenario. Open interest has no v2 key and is not emitted.
        """
        built: dict[str, Any] = {
            "case_input_schema": CASE_INPUT_SCHEMA,
            "symbols": list(self.symbols),
            "strategy_bars": [dict(b) for b in self.strategy_bars],
            "context_bars": [dict(b) for b in self.context_bars],
            "funding": [dict(r) for r in self.funding],
            "data_window": {
                "start_utc": self.start_utc.isoformat(),
                "end_utc": self.end_utc.isoformat(),
            },
            "dataset_id": self.dataset_id,
            "allowed_gaps": [
                {
                    "series": g.series,
                    "symbol": g.symbol,
                    "start_utc": g.start_utc.isoformat(),
                    "end_utc": g.end_utc.isoformat(),
                    "missing": g.missing,
                }
                for g in self.allowed_gaps
            ],
        }
        if self.with_minute_rows:
            built["trade_bars_1m"] = [dict(m) for m in self.trade_bars_1m]
            built["mark_bars_1m"] = [
                {k: v for k, v in dict(m).items() if k != "price_tick_count"}
                for m in self.mark_bars_1m
            ]
        clash = sorted(set(scenario) & set(built))
        if clash:
            raise CaseInputError(
                f"scenario keys collide with builder keys {clash}; the store owns them"
            )
        return {**built, **scenario}


# --------------------------------------------------------------------------- #
# Dataset identity (D-18).
# --------------------------------------------------------------------------- #


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_posix(raw_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(raw_root.resolve()).as_posix()
    except ValueError as exc:
        raise CaseInputError(f"{path} is not under raw root {raw_root}") from exc


def dataset_identity(raw_root: Path, files: Iterable[Path]) -> str:
    """sha256 over the sorted `{posix path relative to raw_root, file sha256}` list.

    Order of `files` never matters; separators are normalised to forward
    slashes so Windows and POSIX hash identically (no drive letter, no
    backslash in the hashed payload).
    """
    entries: dict[str, str] = {}
    for path in files:
        entries[_relative_posix(raw_root, path)] = _file_sha256(path)
    payload = {"files": [{"path": rel, "sha256": entries[rel]} for rel in sorted(entries)]}
    return sha256_hex(payload)


# --------------------------------------------------------------------------- #
# Argument validation (before any filesystem access, T-13-37).
# --------------------------------------------------------------------------- #


def _require_midnight_utc(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise CaseInputRangeError(f"{name} must be a UTC-aware datetime")
    if (value.hour, value.minute, value.second, value.microsecond) != (0, 0, 0, 0):
        raise CaseInputRangeError(f"{name} must be at 00:00:00 UTC (whole UTC days only)")


def _resolve_symbols(symbols: Sequence[str] | None, symbol: str | None) -> list[str]:
    """The requested symbols as a list: `symbols`, or the single-symbol `symbol` keyword."""
    if symbols is not None and symbol is not None:
        raise CaseInputError("pass either symbols or symbol, not both")
    if symbol is not None:
        return [symbol]
    if symbols is None or isinstance(symbols, str):
        raise CaseInputError("symbols must be a non-empty sequence of symbols")
    return list(symbols)


def _validate(
    *,
    symbols: Sequence[str],
    start_utc: datetime,
    end_utc: datetime,
    as_of_day_utc: date,
    strategy_interval: str,
    context_interval: str,
    series: Sequence[str],
) -> tuple[str, ...]:
    if not symbols:
        raise CaseInputError("symbols must not be empty")
    for symbol in symbols:
        if not isinstance(symbol, str) or not _SYMBOL_RE.fullmatch(symbol):
            raise CaseInputError(f"symbol {symbol!r} does not match ^[A-Z0-9]+USDT$")
    if len(set(symbols)) != len(symbols):
        raise CaseInputError(f"symbols must be unique, got {list(symbols)}")
    for label, interval in (
        ("strategy_interval", strategy_interval),
        ("context_interval", context_interval),
    ):
        if interval not in INTERVAL_MS:
            raise CaseInputError(f"{label} {interval!r} is not one of {sorted(INTERVAL_MS)}")
    wanted = tuple(series)
    unknown = sorted(set(wanted) - set(SERIES_ALL))
    if unknown or not wanted:
        raise CaseInputError(f"series must be a non-empty subset of {SERIES_ALL}, got {wanted!r}")
    _require_midnight_utc(start_utc, "start_utc")
    _require_midnight_utc(end_utc, "end_utc")
    if start_utc >= end_utc:
        raise CaseInputRangeError("start_utc must be before end_utc")
    if type(as_of_day_utc) is not date:
        raise CaseInputRangeError("as_of_day_utc must be a date (UTC day)")
    cutoff = datetime(as_of_day_utc.year, as_of_day_utc.month, as_of_day_utc.day, tzinfo=UTC)
    if end_utc > cutoff:
        raise CaseInputRangeError(
            f"end_utc {end_utc.isoformat()} is after the start of as_of_day_utc "
            f"{cutoff.isoformat()}; the current UTC day is never read"
        )
    return tuple(s for s in SERIES_ALL if s in wanted)


# --------------------------------------------------------------------------- #
# File listing (explicit list, never a glob over the whole store).
# --------------------------------------------------------------------------- #


def _utc_days(start_utc: datetime, end_utc: datetime) -> list[date]:
    count = (end_utc - start_utc) // timedelta(days=1)
    return [(start_utc + timedelta(days=i)).date() for i in range(count)]


def _kline_files(root: Path, interval: str, symbol: str, days: Sequence[date]) -> list[Path]:
    paths = (partition_file(root, interval, symbol, day) for day in days)
    return [p for p in paths if p.is_file()]


def _tick_files(
    raw_root: Path, data_class: str, prefix: str, symbol: str, days: Sequence[date]
) -> list[Path]:
    out: list[Path] = []
    for day in days:
        day_dir = (
            raw_root / f"data_class={data_class}" / f"symbol={symbol}" / f"date={day.isoformat()}"
        )
        if day_dir.is_dir():
            out.extend(sorted(day_dir.glob(f"{prefix}-*.parquet")))
    return out


# --------------------------------------------------------------------------- #
# Gap policy (D-19): the single gap definition lives in coverage.py.
# --------------------------------------------------------------------------- #


def _collect_gaps(
    *,
    wanted: Sequence[str],
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
    files_by_series: Mapping[str, Sequence[tuple[str, Sequence[Path]]]],
    funding_step_ms: int = DEFAULT_FUNDING_INTERVAL_MS,
) -> list[GapRange]:
    """Every gap of every requested series, in a deterministic order.

    `funding_step_ms` is the symbol inferred funding cadence; the funding tolerance is
    always `FUNDING_TOLERANCE_MS` (the engine cadence plus jitter, D-36).
    """
    gaps: list[GapRange] = []
    for series in SERIES_ALL:
        if series not in wanted:
            continue
        for interval, files in files_by_series[series]:
            if series == "funding":
                step_ms = funding_step_ms
                max_step_ms: int | None = FUNDING_TOLERANCE_MS
                time_column = "funding_time_utc"
            elif series == "open_interest":
                step_ms = DEFAULT_OI_INTERVAL_MS
                max_step_ms = TICK_GAP_FACTOR * DEFAULT_OI_INTERVAL_MS
                time_column = "observed_at_utc"
            else:
                step_ms = INTERVAL_MS[interval]
                max_step_ms = None
                time_column = "open_time_utc"
            gaps.extend(
                gap_ranges_for_files(
                    files,
                    series=series,
                    symbol=symbol,
                    interval=interval,
                    time_column=time_column,
                    step_ms=step_ms,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    max_step_ms=max_step_ms,
                )
            )
    return gaps


def _apply_allowed(
    gaps: Sequence[GapRange], allow_gaps: Sequence[GapRange]
) -> tuple[GapRange, ...]:
    """Split `gaps` by the acknowledgement list; raise for the unacknowledged rest.

    Only an entry equal to an actual gap counts; an entry that matches nothing is
    ignored and never recorded. Returns the acknowledged gaps in gap order.
    """
    for entry in allow_gaps:
        if not isinstance(entry, GapRange):
            raise CaseInputError("allow_gaps entries must be GapRange values")
    acknowledged = set(allow_gaps)
    unresolved = [g for g in gaps if g not in acknowledged]
    if unresolved:
        raise CaseInputGapError(unresolved)
    return tuple(g for g in gaps if g in acknowledged)


# --------------------------------------------------------------------------- #
# Row conversion (Decimal -> plain string, datetime -> ISO, no float).
# --------------------------------------------------------------------------- #


def _plain(value: object) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise CaseInputError("stored timestamp is not UTC-aware")
        return value.isoformat()
    if isinstance(value, bool):
        raise CaseInputError("unexpected bool cell in a published partition")
    if isinstance(value, (int, str)):
        return value
    raise CaseInputError(f"unsupported cell type {type(value).__name__}")


def _read_rows(
    files: Sequence[Path],
    columns: Sequence[str],
    time_column: str,
    *,
    symbol: str,
    interval: str | None = None,
    pin_price_scale: bool = False,
) -> list[Row]:
    """Read `files` into rows sorted by `time_column` with a fixed column order.

    `pin_price_scale` floors every Decimal column at scale 8 (kline and mark
    partitions); funding and open-interest keep their own declared scales.
    """
    if not files:
        return []
    frame = read_partitions(files, columns, pin_price_scale=pin_price_scale).sort(time_column)
    if frame.filter(pl.col("symbol") != symbol).height:
        raise CaseInputError(f"a published partition carries a symbol other than {symbol}")
    if interval is not None and frame.filter(pl.col("interval") != interval).height:
        raise CaseInputError(f"a published partition carries an interval other than {interval}")
    return [{col: _plain(row[col]) for col in columns} for row in frame.iter_rows(named=True)]


def _epoch_ms(iso: str | int | None) -> int:
    if not isinstance(iso, str):
        raise CaseInputError("bar time is not an ISO string")
    delta = datetime.fromisoformat(iso) - datetime(1970, 1, 1, tzinfo=UTC)
    return delta // timedelta(milliseconds=1)


def infer_funding_cadence_ms(times_ms: Sequence[int]) -> int:
    """Infer a funding series cadence (8 h or 4 h) from its observed instants (D-36).

    Each spacing votes for the nearer cadence (under 6 h counts as 4 h, anything longer,
    including a long hole, as 8 h); the majority wins and a tie, an empty or a
    single-observation series defaults to 8 h. A missed instant in a 4 h series (one 8 h
    spacing) therefore does not change the cadence, and jitter of seconds is irrelevant.
    """
    midpoint = (_FOUR_HOUR_MS + DEFAULT_FUNDING_INTERVAL_MS) // 2
    four = eight = 0
    for earlier, later in zip(times_ms, times_ms[1:], strict=False):
        spacing = later - earlier
        if spacing <= 0:
            continue
        if spacing < midpoint:
            four += 1
        else:
            eight += 1
    return _FOUR_HOUR_MS if four > eight else DEFAULT_FUNDING_INTERVAL_MS


# --------------------------------------------------------------------------- #
# Builder.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _SymbolFiles:
    """The explicit partition files of one symbol over the requested days."""

    symbol: str
    strategy: list[Path]
    context: list[Path]
    minute: list[Path]
    mark: list[Path]
    funding: list[Path]
    open_interest: list[Path]


def _symbol_files(
    raw_root: Path,
    symbol: str,
    days: Sequence[date],
    *,
    strategy_interval: str,
    context_interval: str,
) -> _SymbolFiles:
    mark_root = raw_root / MARK_DATASET_DIR
    return _SymbolFiles(
        symbol=symbol,
        strategy=_kline_files(raw_root, strategy_interval, symbol, days),
        context=_kline_files(raw_root, context_interval, symbol, days),
        minute=_kline_files(raw_root, "1m", symbol, days),
        mark=_kline_files(mark_root, "1m", symbol, days),
        funding=_tick_files(raw_root, "funding", "sweep", symbol, days),
        open_interest=_tick_files(raw_root, "oi", "tick", symbol, days),
    )


def build_case_input_data(
    raw_root: Path,
    *,
    symbols: Sequence[str] | None = None,
    symbol: str | None = None,
    start_utc: datetime,
    end_utc: datetime,
    as_of_day_utc: date,
    strategy_interval: str = "1h",
    context_interval: str = "4h",
    series: Sequence[str] = SERIES_ALL,
    allow_gaps: Sequence[GapRange] = (),
    with_minute_rows: bool = False,
) -> CaseInputData:
    """Build the case-input v2 data for one or more symbols and a whole-UTC-day range.

    Pass `symbols` (any order; emitted sorted) or the single-symbol keyword `symbol`.
    `with_minute_rows=True` embeds the 1m trade and mark rows; the default leaves them
    out for a lazy `ParquetMinuteSource`. Gap detection and the dataset identity cover the
    1m partitions either way.
    """
    names = _resolve_symbols(symbols, symbol)
    wanted = _validate(
        symbols=names,
        start_utc=start_utc,
        end_utc=end_utc,
        as_of_day_utc=as_of_day_utc,
        strategy_interval=strategy_interval,
        context_interval=context_interval,
        series=series,
    )
    ordered = sorted(names)
    days = _utc_days(start_utc, end_utc)
    trade_intervals = list(dict.fromkeys((strategy_interval, context_interval)))

    # Phase 1: files and funding rows per symbol, then every gap, BEFORE any other row is
    # read: a hole is never padded (D-19). Funding rows come first because the cadence
    # (8 h or 4 h) is inferred from the observed spacing (D-36).
    files_of: dict[str, _SymbolFiles] = {}
    funding_of: dict[str, list[Row]] = {}
    gaps: list[GapRange] = []
    for name in ordered:
        files = _symbol_files(
            raw_root,
            name,
            days,
            strategy_interval=strategy_interval,
            context_interval=context_interval,
        )
        files_of[name] = files
        funding_rows: list[Row] = []
        if "funding" in wanted:
            funding_rows = _read_rows(
                files.funding, _FUNDING_COLUMNS, "funding_time_utc", symbol=name
            )
        funding_of[name] = funding_rows
        cadence_ms = infer_funding_cadence_ms(
            [_epoch_ms(r["funding_time_utc"]) for r in funding_rows]
        )
        files_by_series: dict[str, list[tuple[str, Sequence[Path]]]] = {
            "trade": [
                (iv, files.strategy if iv == strategy_interval else files.context)
                for iv in trade_intervals
            ],
            "intrabar_1m": [("1m", files.minute)],
            "mark_1m": [("1m", files.mark)],
            "funding": [(f"{cadence_ms // 3_600_000}h", files.funding)],
            "open_interest": [("5m", files.open_interest)],
        }
        gaps.extend(
            _collect_gaps(
                wanted=wanted,
                symbol=name,
                start_utc=start_utc,
                end_utc=end_utc,
                files_by_series=files_by_series,
                funding_step_ms=cadence_ms,
            )
        )
    allowed_gaps = _apply_allowed(gaps, allow_gaps)

    # Phase 2: rows. Rows are grouped by sorted symbol, ascending in time within a symbol.
    used: list[Path] = []
    strategy_bars: list[Row] = []
    context_bars: list[Row] = []
    trade_minutes: list[Row] = []
    mark_bars: list[Row] = []
    funding: list[Row] = []
    open_interest: list[Row] = []
    for name in ordered:
        files = files_of[name]
        if "trade" in wanted:
            used += files.strategy + files.context
            strategy_bars += _read_rows(
                files.strategy,
                _BAR_COLUMNS,
                "open_time_utc",
                symbol=name,
                interval=strategy_interval,
                pin_price_scale=True,
            )
            context_bars += _read_rows(
                files.context,
                _BAR_COLUMNS,
                "open_time_utc",
                symbol=name,
                interval=context_interval,
                pin_price_scale=True,
            )
        if "intrabar_1m" in wanted:
            used += files.minute
            if with_minute_rows:
                trade_minutes += _read_rows(
                    files.minute,
                    _BAR_COLUMNS,
                    "open_time_utc",
                    symbol=name,
                    interval="1m",
                    pin_price_scale=True,
                )
        if "mark_1m" in wanted:
            used += files.mark
            if with_minute_rows:
                mark_bars += _read_rows(
                    files.mark,
                    _MARK_COLUMNS,
                    "open_time_utc",
                    symbol=name,
                    interval="1m",
                    pin_price_scale=True,
                )
        if "funding" in wanted:
            used += files.funding
            funding += funding_of[name]
        if "open_interest" in wanted:
            used += files.open_interest
            open_interest += _read_rows(
                files.open_interest, _OI_COLUMNS, "observed_at_utc", symbol=name
            )

    relative = tuple(sorted({_relative_posix(raw_root, p) for p in used}))
    return CaseInputData(
        symbols=tuple(ordered),
        strategy_interval=strategy_interval,
        context_interval=context_interval,
        start_utc=start_utc,
        end_utc=end_utc,
        series=wanted,
        strategy_bars=tuple(strategy_bars),
        context_bars=tuple(context_bars),
        trade_bars_1m=tuple(trade_minutes),
        mark_bars_1m=tuple(mark_bars),
        funding=tuple(funding),
        open_interest=tuple(open_interest),
        files=relative,
        dataset_id=dataset_identity(raw_root, used),
        allowed_gaps=allowed_gaps,
        with_minute_rows=with_minute_rows,
    )


__all__ = [
    "SERIES_ALL",
    "CaseInputData",
    "CaseInputError",
    "CaseInputGapError",
    "CaseInputRangeError",
    "FUNDING_TOLERANCE_MS",
    "build_case_input_data",
    "dataset_identity",
    "infer_funding_cadence_ms",
]
