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
    _observed_times_ms,
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
# The series the engine reads: open interest stays inert (no case-input v2 key).
ENGINE_SERIES: tuple[str, ...] = ("trade", "intrabar_1m", "mark_1m", "funding")

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
    inspected back as `allow_gaps` to proceed with a recorded hole. `refusals` maps a gap
    to the failed condition of a terminal declaration that was offered for its symbol and
    refused (plan 16-54, KG-3); the message names that condition.
    """

    def __init__(
        self, gaps: Sequence[GapRange], refusals: Mapping[GapRange, str] | None = None
    ) -> None:
        self.gaps: tuple[GapRange, ...] = tuple(gaps)
        self.refusals: dict[GapRange, str] = dict(refusals or {})
        detail = "; ".join(
            f"{g.series}/{g.interval} {g.start_utc.isoformat()}..{g.end_utc.isoformat()}"
            f" missing={g.missing}"
            + (f" (terminal declaration refused: {self.refusals[g]})" if g in self.refusals else "")
            for g in self.gaps
        )
        super().__init__(f"unresolved gaps in the published store: {detail}")


# KG-1 (plan 16-54): the one reason a terminal declaration can carry, the sufficiency-report word.
TERMINAL_REASON_DELISTED_CAPPED = "DELISTED_CAPPED"
TERMINAL_REASONS: frozenset[str] = frozenset({TERMINAL_REASON_DELISTED_CAPPED})


@dataclass(frozen=True)
class TerminalDeclaration:
    """A per-symbol declaration that a symbol's data ends (plan 16-54, KG-2 wrapper, KG-3).

    It names no six-field range and is not a `GapRange`: it is evidence that the series of
    `symbol` end, not a licence to skip missing data. The builder accepts a detected gap of
    that symbol under it only when the gap follows the data geometry (`_terminal_refusal`).
    `source_url` is carried for the manifest hash; the builder never reads or fetches it.
    """

    symbol: str
    reason: str
    terminal_at_utc: datetime
    source_url: str

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not _SYMBOL_RE.fullmatch(self.symbol):
            raise CaseInputError("terminal declaration symbol does not match ^[A-Z0-9]+USDT$")
        if self.reason not in TERMINAL_REASONS:
            raise CaseInputError(
                f"terminal declaration reason must be one of {sorted(TERMINAL_REASONS)}"
            )
        stamp = self.terminal_at_utc
        if (
            not isinstance(stamp, datetime)
            or stamp.tzinfo is None
            or stamp.utcoffset() != timedelta(0)
        ):
            raise CaseInputError(
                "terminal declaration terminal_at_utc must be a UTC-aware datetime"
            )
        if not isinstance(self.source_url, str) or not self.source_url:
            raise CaseInputError("terminal declaration source_url must be a non-empty string")


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

    def to_case_input(
        self, *, data_window_start_utc: datetime | None = None, **scenario: Any
    ) -> dict[str, Any]:
        """Return the case-input v2 dict: builder keys plus `scenario`.

        `data_window_start_utc` (plan 16-60, B3-CR-01) moves only the `data_window.start_utc` of
        the case: the bars the case holds start at the range the data was built with (the
        warm-up history), while the window the engine simulates, records and reports starts
        later. It must be UTC-aware and lie in `[start_utc, end_utc)`; left out, the window is
        the built range, exactly as before.

        A scenario key that collides with a builder key is refused: the store owns the
        market data, the caller owns the strategy identity and the account, cost and
        constraint scenario. Open interest has no v2 key and is not emitted.

        The engine reads the bars, the 1m trade and mark minutes and funding, and
        `dataset_id` is what binds a run to its data, so a case is only produced for data
        whose identity covers every one of those series: a subset such as `("trade",
        "funding")` could be paired with a lazily supplied `ParquetMinuteSource` over 1m
        files that are not in the identity (WR-10).
        """
        missing = sorted(set(ENGINE_SERIES) - set(self.series))
        if missing:
            raise CaseInputError(
                f"the dataset was built without the series {missing} the engine reads, so its "
                "dataset_id does not cover them; rebuild with every engine series"
            )
        window_start = self.start_utc
        if data_window_start_utc is not None:
            if (
                not isinstance(data_window_start_utc, datetime)
                or data_window_start_utc.tzinfo is None
                or data_window_start_utc.utcoffset() != timedelta(0)
            ):
                raise CaseInputError("data_window_start_utc must be a UTC-aware datetime")
            if not self.start_utc <= data_window_start_utc < self.end_utc:
                raise CaseInputError(
                    "data_window_start_utc must lie in [start_utc, end_utc) of the built range"
                )
            window_start = data_window_start_utc
        built: dict[str, Any] = {
            "case_input_schema": CASE_INPUT_SCHEMA,
            "symbols": list(self.symbols),
            "strategy_bars": [dict(b) for b in self.strategy_bars],
            "context_bars": [dict(b) for b in self.context_bars],
            "funding": [dict(r) for r in self.funding],
            "data_window": {
                "start_utc": window_start.isoformat(),
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


def _series_spec(series: str, interval: str, funding_step_ms: int) -> tuple[int, int | None, str]:
    """The cadence, the hole tolerance and the time column of one series at one interval.

    `funding_step_ms` is the symbol inferred funding cadence; the funding tolerance is
    always `FUNDING_TOLERANCE_MS` (the engine cadence plus jitter, D-36).
    """
    if series == "funding":
        return funding_step_ms, FUNDING_TOLERANCE_MS, "funding_time_utc"
    if series == "open_interest":
        return DEFAULT_OI_INTERVAL_MS, TICK_GAP_FACTOR * DEFAULT_OI_INTERVAL_MS, "observed_at_utc"
    return INTERVAL_MS[interval], None, "open_time_utc"


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
            step_ms, max_step_ms, time_column = _series_spec(series, interval, funding_step_ms)
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


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _epoch_ms_of(value: datetime) -> int:
    return (value - _EPOCH) // _MS


def _terminal_refusal(
    gap: GapRange,
    terminal_at_utc: datetime,
    observed_ms: Sequence[int],
    step_ms: int,
    start_utc: datetime,
    end_utc: datetime,
) -> str | None:
    """Why a terminal declaration does not explain `gap`, or None when it does (KG-3).

    `observed_ms` are the series' own observed instants inside [start_utc, end_utc), read from
    the files by the builder and never taken from the declaration. The gap is accepted only when
    it is a trailing hole that runs to exactly the window end, no observation lies at or after
    the terminal timestamp, its start is the first slot after the last observation (or the
    window start when the series has no observation in the window), on the series cadence, with
    a `missing` count equal to the one computed here from that geometry, and that start is at or
    after the terminal timestamp. A check of only `terminal_at_utc <= gap.start_utc` is not enough.
    """
    if gap.end_utc != end_utc:
        return (
            "the gap is not trailing: it does not run to the window end, so the series has "
            "data after the gap start"
        )
    end_ms = _epoch_ms_of(end_utc)
    if observed_ms:
        last_ms = observed_ms[-1]
        if _EPOCH + last_ms * _MS >= terminal_at_utc:
            return "the series has an observation at or after the terminal timestamp"
        expected_start_ms = last_ms + step_ms
        expected_missing = (end_ms - last_ms) // step_ms - 1
    else:
        expected_start_ms = _epoch_ms_of(start_utc)
        expected_missing = (end_ms - expected_start_ms) // step_ms
    if _epoch_ms_of(gap.start_utc) != expected_start_ms:
        return (
            "the gap start is not the first slot after the last observation "
            "(or the window start for a series with no observation)"
        )
    if gap.series != "funding" and expected_start_ms % step_ms != 0:
        return "the gap start is not on the series cadence"
    if gap.missing != max(1, expected_missing):
        return "the missing count differs from the count computed from the data geometry"
    if gap.start_utc < terminal_at_utc:
        return (
            "the terminal timestamp is after the gap start: the slots between the last "
            "observation and the terminal timestamp would be an unexplained loss"
        )
    return None


def _apply_terminal(
    gaps: Sequence[GapRange],
    declarations: Sequence[TerminalDeclaration],
    context: Mapping[str, tuple[Mapping[str, Sequence[tuple[str, Sequence[Path]]]], int]],
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[frozenset[GapRange], dict[GapRange, str]]:
    """Split `gaps` by the terminal declarations: (accepted, refused with the failed condition).

    One declaration per symbol. A gap of a symbol without a declaration is neither accepted
    nor refused here: it stays unresolved for the exact-match path. `context` gives, per
    symbol, the files of every series and interval and the inferred funding cadence.
    """
    by_symbol: dict[str, TerminalDeclaration] = {}
    for declaration in declarations:
        if not isinstance(declaration, TerminalDeclaration):
            raise CaseInputError("terminal_declarations entries must be TerminalDeclaration values")
        if declaration.symbol in by_symbol:
            raise CaseInputError(
                f"more than one terminal declaration for {declaration.symbol}; one per symbol"
            )
        by_symbol[declaration.symbol] = declaration
    accepted: set[GapRange] = set()
    refused: dict[GapRange, str] = {}
    for gap in gaps:
        declared_for = by_symbol.get(gap.symbol)
        if declared_for is None:
            continue
        files_by_series, cadence_ms = context[gap.symbol]
        files = dict(files_by_series[gap.series])[gap.interval]
        step_ms, _, time_column = _series_spec(gap.series, gap.interval, cadence_ms)
        observed = (
            _observed_times_ms(files, time_column, _epoch_ms_of(start_utc), _epoch_ms_of(end_utc))
            if files
            else []
        )
        reason = _terminal_refusal(
            gap, declared_for.terminal_at_utc, observed, step_ms, start_utc, end_utc
        )
        if reason is None:
            accepted.add(gap)
        else:
            refused[gap] = reason
    return frozenset(accepted), refused


def _apply_allowed(
    gaps: Sequence[GapRange],
    allow_gaps: Sequence[GapRange],
    *,
    declared: frozenset[GapRange] = frozenset(),
    refusals: Mapping[GapRange, str] | None = None,
) -> tuple[GapRange, ...]:
    """Split `gaps` by the acknowledgement list; raise for the unacknowledged rest.

    Only an entry equal to an actual gap counts; an entry that matches nothing is
    ignored and never recorded. `declared` are the gaps a terminal declaration explained
    (`_apply_terminal`, plan 16-54); every other gap still needs the exact six-field match.
    Returns the acknowledged gaps in gap order.
    """
    for entry in allow_gaps:
        if not isinstance(entry, GapRange):
            raise CaseInputError("allow_gaps entries must be GapRange values")
    acknowledged = set(allow_gaps) | declared
    unresolved = [g for g in gaps if g not in acknowledged]
    if unresolved:
        raise CaseInputGapError(unresolved, refusals)
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
    terminal_declarations: Sequence[TerminalDeclaration] = (),
    with_minute_rows: bool = False,
) -> CaseInputData:
    """Build the case-input v2 data for one or more symbols and a whole-UTC-day range.

    Pass `symbols` (any order; emitted sorted) or the single-symbol keyword `symbol`.
    `with_minute_rows=True` embeds the 1m trade and mark rows; the default leaves them
    out for a lazy `ParquetMinuteSource`. Gap detection and the dataset identity cover the
    1m partitions either way.

    `allow_gaps` acknowledges a hole only by an exact six-field match. `terminal_declarations`
    (plan 16-54, one per symbol) acknowledges the trailing holes of a symbol whose data ends,
    but only those that follow the data geometry (`_terminal_refusal`); an interior hole is
    never explained by a declaration.
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
    terminal_context: dict[str, tuple[Mapping[str, Sequence[tuple[str, Sequence[Path]]]], int]] = {}
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
        terminal_context[name] = (files_by_series, cadence_ms)
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
    declared, refusals = _apply_terminal(
        gaps, terminal_declarations, terminal_context, start_utc, end_utc
    )
    allowed_gaps = _apply_allowed(gaps, allow_gaps, declared=declared, refusals=refusals)

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
    "ENGINE_SERIES",
    "SERIES_ALL",
    "CaseInputData",
    "CaseInputError",
    "CaseInputGapError",
    "CaseInputRangeError",
    "FUNDING_TOLERANCE_MS",
    "TERMINAL_REASONS",
    "TERMINAL_REASON_DELISTED_CAPPED",
    "TerminalDeclaration",
    "build_case_input_data",
    "dataset_identity",
    "infer_funding_cadence_ms",
]
