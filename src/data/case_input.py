"""Published Parquet -> backtest case-input builder (M4, D-17, D-18, D-22).

`build_case_input_data` reads ONLY the immutable published partitions for one
symbol and a whole-UTC-day range and returns the simulator's case-input
keys, so a backtest runs straight from the store without hand-built fixtures.

Design rules (13-CONTEXT D-17..D-22):

- Whole UTC days only. The caller passes `as_of_day_utc`; a range ending after
  the start of that day is refused, so the current (still forming) UTC day and
  live tick files are never read. The module takes no wall clock.
- Decimal-safe: every price/volume/rate leaves this module as a plain-notation
  string (`format(Decimal, "f")`), every timestamp as an ISO-8601 UTC string.
  There is no float anywhere in the path.
- Dataset identity (D-18): `dataset_id` is sha256 over the sorted list of
  `{repo-relative posix path, sha256 of file bytes}` for exactly the files read.
  The same partitions give the same id; a changed, added or removed partition
  changes it. A dataset that is re-written (for example after a Polars upgrade
  changes the Parquet bytes) is a NEW dataset by design (13-RESEARCH A4).
- Package purity (D-12): Polars and DuckDB live here in `src/data`; nothing under
  `src/backtest` imports this module. The mark-price, funding and open-interest
  keys are inert to the current simulator, which ignores unknown keys, until
  Phase 14 consumes them.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import polars as pl
from src.data.coverage import (
    DEFAULT_FUNDING_INTERVAL_MS,
    DEFAULT_OI_INTERVAL_MS,
    FUNDING_JITTER_MS,
    TICK_GAP_FACTOR,
    GapRange,
    gap_ranges_for_files,
)
from src.data.quality import INTERVAL_MS
from src.data.store import MARK_DATASET_DIR, partition_file
from src.domain.canonical import sha256_hex

SERIES_ALL: tuple[str, ...] = (
    "trade",
    "intrabar_1m",
    "mark_1m",
    "funding",
    "open_interest",
)

_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
_ONE_MINUTE_MS = 60_000
_HASH_CHUNK = 1 << 20

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
    """Everything the simulator (and the experiment record) needs from the store."""

    symbol: str
    strategy_interval: str
    context_interval: str
    start_utc: datetime
    end_utc: datetime
    series: tuple[str, ...]
    strategy_bars: tuple[Row, ...]
    context_bars: tuple[Row, ...]
    intrabar_1m_map: Mapping[str, tuple[Row, ...] | None]
    mark_bars_1m: tuple[Row, ...]
    funding: tuple[Row, ...]
    open_interest: tuple[Row, ...]
    files: tuple[str, ...]
    dataset_id: str
    allowed_gaps: tuple[GapRange, ...]

    def to_case_input(self, **scenario: Any) -> dict[str, Any]:
        """Return the simulator case-input dict: builder keys plus `scenario`.

        A scenario key that collides with a builder key is refused: the store
        owns the bars, the caller owns the account/constraint/cost scenario.
        """
        built: dict[str, Any] = {
            "strategy_bars": [dict(b) for b in self.strategy_bars],
            "context_bars": [dict(b) for b in self.context_bars],
            "intrabar_1m_map": {
                key: None if minutes is None else [dict(m) for m in minutes]
                for key, minutes in self.intrabar_1m_map.items()
            },
            "mark_price_bars": [dict(b) for b in self.mark_bars_1m],
            "funding": [dict(r) for r in self.funding],
            "open_interest": [dict(r) for r in self.open_interest],
            "dataset_id": self.dataset_id,
            "allowed_gaps": [
                {
                    "series": g.series,
                    "symbol": g.symbol,
                    "interval": g.interval,
                    "start_utc": g.start_utc.isoformat(),
                    "end_utc": g.end_utc.isoformat(),
                    "missing": g.missing,
                }
                for g in self.allowed_gaps
            ],
        }
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


def _validate(
    *,
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
    as_of_day_utc: date,
    strategy_interval: str,
    context_interval: str,
    series: Sequence[str],
) -> tuple[str, ...]:
    if not isinstance(symbol, str) or not _SYMBOL_RE.fullmatch(symbol):
        raise CaseInputError(f"symbol {symbol!r} does not match ^[A-Z0-9]+USDT$")
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
) -> list[GapRange]:
    """Every gap of every requested series, in a deterministic order."""
    gaps: list[GapRange] = []
    for series in SERIES_ALL:
        if series not in wanted:
            continue
        for interval, files in files_by_series[series]:
            if series == "funding":
                step_ms = DEFAULT_FUNDING_INTERVAL_MS
                max_step_ms: int | None = DEFAULT_FUNDING_INTERVAL_MS + FUNDING_JITTER_MS
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
) -> list[Row]:
    """Read `files` into rows sorted by `time_column` with a fixed column order."""
    if not files:
        return []
    frame = pl.read_parquet(
        [str(p) for p in files], columns=list(columns), hive_partitioning=False
    ).sort(time_column)
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


def _group_intrabar(
    strategy_bars: Sequence[Row],
    minutes: Sequence[Row],
    *,
    symbol: str,
    strategy_step_ms: int,
) -> dict[str, tuple[Row, ...] | None]:
    """Map `SYMBOL|ISO_CLOSE` to the bar's 60 one-minute rows, else None."""
    expected = strategy_step_ms // _ONE_MINUTE_MS
    buckets: dict[int, list[Row]] = {}
    for minute in minutes:
        open_ms = _epoch_ms(minute["open_time_utc"])
        buckets.setdefault(open_ms - open_ms % strategy_step_ms, []).append(minute)
    out: dict[str, tuple[Row, ...] | None] = {}
    for bar in strategy_bars:
        bar_open = _epoch_ms(bar["open_time_utc"])
        group = buckets.get(bar_open, [])
        offsets = {(_epoch_ms(m["open_time_utc"]) - bar_open) // _ONE_MINUTE_MS for m in group}
        complete = len(group) == expected and offsets == set(range(expected))
        out[f"{symbol}|{bar['close_time_utc']}"] = tuple(group) if complete else None
    return out


# --------------------------------------------------------------------------- #
# Builder.
# --------------------------------------------------------------------------- #


def build_case_input_data(
    raw_root: Path,
    *,
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
    as_of_day_utc: date,
    strategy_interval: str = "1h",
    context_interval: str = "4h",
    series: Sequence[str] = SERIES_ALL,
    allow_gaps: Sequence[GapRange] = (),
) -> CaseInputData:
    """Build the case-input data for one symbol and a whole-UTC-day range."""
    wanted = _validate(
        symbol=symbol,
        start_utc=start_utc,
        end_utc=end_utc,
        as_of_day_utc=as_of_day_utc,
        strategy_interval=strategy_interval,
        context_interval=context_interval,
        series=series,
    )
    days = _utc_days(start_utc, end_utc)
    mark_root = raw_root / MARK_DATASET_DIR

    strategy_files = _kline_files(raw_root, strategy_interval, symbol, days)
    context_files = _kline_files(raw_root, context_interval, symbol, days)
    minute_files = _kline_files(raw_root, "1m", symbol, days)
    mark_files = _kline_files(mark_root, "1m", symbol, days)
    funding_files = _tick_files(raw_root, "funding", "sweep", symbol, days)
    oi_files = _tick_files(raw_root, "oi", "tick", symbol, days)

    trade_intervals = list(dict.fromkeys((strategy_interval, context_interval)))
    files_by_series: dict[str, list[tuple[str, Sequence[Path]]]] = {
        "trade": [
            (iv, strategy_files if iv == strategy_interval else context_files)
            for iv in trade_intervals
        ],
        "intrabar_1m": [("1m", minute_files)],
        "mark_1m": [("1m", mark_files)],
        "funding": [("8h", funding_files)],
        "open_interest": [("5m", oi_files)],
    }
    # Fail closed BEFORE any row is emitted: a hole is never padded (D-19).
    allowed_gaps = _apply_allowed(
        _collect_gaps(
            wanted=wanted,
            symbol=symbol,
            start_utc=start_utc,
            end_utc=end_utc,
            files_by_series=files_by_series,
        ),
        allow_gaps,
    )

    used: list[Path] = []
    strategy_bars: list[Row] = []
    context_bars: list[Row] = []
    minutes: list[Row] = []
    mark_bars: list[Row] = []
    funding: list[Row] = []
    open_interest: list[Row] = []

    if "trade" in wanted:
        used += strategy_files + context_files
        strategy_bars = _read_rows(
            strategy_files,
            _BAR_COLUMNS,
            "open_time_utc",
            symbol=symbol,
            interval=strategy_interval,
        )
        context_bars = _read_rows(
            context_files,
            _BAR_COLUMNS,
            "open_time_utc",
            symbol=symbol,
            interval=context_interval,
        )
    if "intrabar_1m" in wanted:
        used += minute_files
        minutes = _read_rows(
            minute_files, _BAR_COLUMNS, "open_time_utc", symbol=symbol, interval="1m"
        )
    if "mark_1m" in wanted:
        used += mark_files
        mark_bars = _read_rows(
            mark_files, _MARK_COLUMNS, "open_time_utc", symbol=symbol, interval="1m"
        )
    if "funding" in wanted:
        used += funding_files
        funding = _read_rows(funding_files, _FUNDING_COLUMNS, "funding_time_utc", symbol=symbol)
    if "open_interest" in wanted:
        used += oi_files
        open_interest = _read_rows(oi_files, _OI_COLUMNS, "observed_at_utc", symbol=symbol)

    step_ms = INTERVAL_MS[strategy_interval]
    if "intrabar_1m" in wanted:
        intrabar = _group_intrabar(strategy_bars, minutes, symbol=symbol, strategy_step_ms=step_ms)
    else:
        intrabar = {f"{symbol}|{bar['close_time_utc']}": None for bar in strategy_bars}

    files = tuple(sorted({_relative_posix(raw_root, p) for p in used}))
    return CaseInputData(
        symbol=symbol,
        strategy_interval=strategy_interval,
        context_interval=context_interval,
        start_utc=start_utc,
        end_utc=end_utc,
        series=wanted,
        strategy_bars=tuple(strategy_bars),
        context_bars=tuple(context_bars),
        intrabar_1m_map=MappingProxyType(intrabar),
        mark_bars_1m=tuple(mark_bars),
        funding=tuple(funding),
        open_interest=tuple(open_interest),
        files=files,
        dataset_id=dataset_identity(raw_root, used),
        allowed_gaps=allowed_gaps,
    )


__all__ = [
    "SERIES_ALL",
    "CaseInputData",
    "CaseInputError",
    "CaseInputGapError",
    "CaseInputRangeError",
    "build_case_input_data",
    "dataset_identity",
]
