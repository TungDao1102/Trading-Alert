"""Immutable dataset manifest and parameter grid with canonical hashes (D-25, REV-04, REV-05).

The manifest fixes everything a research run reads: universe, dataset identity, the exact
development / validation / holdout boundaries, candle intervals, data source and version,
excluded periods, known terminal declarations, the research account inputs and the
constraint source, and optionally one bounded terminal settlement per declared symbol (quick
261014-nnl, `terminal_settlements`; left out of the canonical form when empty, so a manifest
without one hashes exactly as before). The
grid fixes the strategy and the ordered, registered parameter sets of one experiment. Both
hash through `src.domain.canonical.sha256_hex` over a canonical dict (Decimal and datetimes
as strings, UTC only, no float), so the same content always has the same hash and any edit
changes it. The values inside a manifest (window, split dates) are the user's (O-03); this
module defines the shape and the hash, never a value.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit

from src.backtest.semantics import (
    TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
    TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
)
from src.data.case_input import (
    TERMINAL_REASON_DELISTED_CAPPED,
    TERMINAL_REASONS,
    CaseInputError,
    TerminalDeclaration,
)
from src.domain.canonical import canonical_decimal_text, sha256_hex

from .settlement_evidence import (
    SettlementEvidenceError,
    parse_fraction_text,
    tick_widened_bounds,
    union_bounds,
)

DEVELOPMENT = "DEVELOPMENT"
VALIDATION = "VALIDATION"
VALIDATION_FOLD_COUNT = 4
_ONE_DAY = timedelta(days=1)

# KG-1 (plan 16-54): the closed vocabulary of a known-gap reason is exactly one value, the
# sufficiency-report word DELISTED_CAPPED; the reason is required on every declaration.
KNOWN_GAP_REASON_DELISTED_CAPPED = TERMINAL_REASON_DELISTED_CAPPED
KNOWN_GAP_REASONS: frozenset[str] = TERMINAL_REASONS
# KG-4 (plan 16-54): the only host a declaration source URL may carry; nothing is fetched.
KNOWN_GAP_SOURCE_HOSTS: frozenset[str] = frozenset({"www.binance.com"})
# Quick 261014-nnl plan 02 (design section 2): a bounded terminal settlement samples the index
# price 60 times per minute (an unverified assumption, stated in the entry's condition text).
SAMPLES_PER_MINUTE = 60


class ManifestError(ValueError):
    """A manifest, grid or its inputs are malformed or do not match their preregistration."""


def _require_day_boundary(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ManifestError(f"{name} must be a UTC-aware datetime")
    if (value.hour, value.minute, value.second, value.microsecond) != (0, 0, 0, 0):
        raise ManifestError(f"{name} must be at 00:00:00 UTC (whole UTC days only)")
    return value


def _check_source_url(value: object) -> None:
    """KG-4 shape rule plus the host list; offline, and never echoes the value."""
    if not isinstance(value, str) or not value:
        raise ManifestError("known gap source_url must be a non-empty string")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ManifestError(
            "known gap source_url must not contain whitespace or control characters"
        )
    try:
        parts = urlsplit(value)
    except ValueError:
        raise ManifestError("known gap source_url is not a valid URL") from None
    if parts.scheme != "https":
        raise ManifestError("known gap source_url must use the https scheme")
    if not parts.netloc:
        raise ManifestError("known gap source_url must have a host")
    if "@" in parts.netloc:
        raise ManifestError("known gap source_url must not carry user information")
    if parts.netloc not in KNOWN_GAP_SOURCE_HOSTS:
        raise ManifestError("known gap source_url host is not in the allowed host list")


def _require_hex64(value: object, name: str) -> str:
    text = value if isinstance(value, str) else ""
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ManifestError(f"{name} must be 64 lowercase hex characters")
    return text


@dataclass(frozen=True)
class Period:
    """A preregistered excluded period."""

    start_utc: datetime
    end_utc: datetime
    reason: str

    def canonical(self) -> dict[str, Any]:
        return {"start_utc": self.start_utc, "end_utc": self.end_utc, "reason": self.reason}


def _is_minute_aligned_utc(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == timedelta(0)
        and (value.second, value.microsecond) == (0, 0)
    )


@dataclass(frozen=True)
class EvidenceFile:
    """A committed evidence file: a posix repo-relative path and the sha256 of its bytes."""

    path: str
    sha256: str

    def __post_init__(self) -> None:
        path = self.path
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or PurePosixPath(path).as_posix() != path
            or PurePosixPath(path).is_absolute()
            or PureWindowsPath(path).is_absolute()
            or PureWindowsPath(path).drive != ""
            or ".." in PurePosixPath(path).parts
        ):
            raise ManifestError(
                "evidence path must be a clean posix path relative to the repository root "
                "(no backslash, drive, '..', '.', empty segment or trailing slash)"
            )
        _require_hex64(self.sha256, "evidence sha256")

    def canonical(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256}


def _canonical_positive_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise ManifestError(f"{name} must be a Decimal")
    if not value.is_finite() or value <= 0:
        raise ManifestError(f"{name} must be a finite positive Decimal")
    # The hash writes str(value); that text is unique per number only when the Decimal carries
    # no trailing zeros and no positive exponent, which is exactly its canonical spelling.
    if value.as_tuple() != Decimal(canonical_decimal_text(value)).as_tuple():
        raise ManifestError(f"{name} must be in canonical decimal text (no trailing zeros)")
    return value


def _fraction_field(value: object, name: str) -> Fraction:
    if not isinstance(value, str):
        raise ManifestError(f'{name} must be a string "p/q"')
    try:
        return parse_fraction_text(value)
    except SettlementEvidenceError as exc:
        raise ManifestError(f"{name}: {exc}") from None


@dataclass(frozen=True)
class TerminalSettlement:
    """A bounded terminal settlement of one declared symbol (quick 261014-nnl, design section 2).

    The entry has no terminal instant of its own: T is the `terminal_at_utc` of the symbol's
    `known_gaps` declaration, and the bound window is [`bound_window_start_utc`, T). The nominal
    bounds are kept as the reduced text "p/q" (never a Fraction or float in the hash). Every
    stored bound is checked against the tick-widening and union rule at construction, and the
    runner recomputes them from the committed evidence bytes before any simulation. The entry
    records an interval, never a settlement price (16-DEC-S-B-interval item 1).
    """

    symbol: str
    kind: str
    recorded_evaluation: str
    bound_window_start_utc: datetime
    samples_per_minute: int
    nominal_lower: str
    nominal_upper: str
    price_tick_size: Decimal
    index_lower: Decimal
    index_upper: Decimal
    trade_candle_low: Decimal
    trade_candle_high: Decimal
    price_lower: Decimal
    price_upper: Decimal
    index_klines: EvidenceFile
    trade_kline: EvidenceFile
    supporting_evidence: tuple[EvidenceFile, ...]
    condition: str
    official_confirmation: None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ManifestError("terminal settlement symbol must be a non-empty string")
        if self.kind != TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES:
            raise ManifestError(
                f"terminal settlement kind must be {TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES!r}"
            )
        if self.recorded_evaluation != TERMINAL_EVALUATION_UNION_ADVERSE_BOUND:
            raise ManifestError(
                "terminal settlement recorded_evaluation must be "
                f"{TERMINAL_EVALUATION_UNION_ADVERSE_BOUND!r}"
            )
        if not _is_minute_aligned_utc(self.bound_window_start_utc):
            raise ManifestError("bound_window_start_utc must be a minute-aligned UTC datetime")
        if isinstance(self.samples_per_minute, bool) or not isinstance(
            self.samples_per_minute, int
        ):
            raise ManifestError("samples_per_minute must be the integer 60")
        if self.samples_per_minute != SAMPLES_PER_MINUTE:
            raise ManifestError(f"samples_per_minute must be {SAMPLES_PER_MINUTE}")
        tick = _canonical_positive_decimal(self.price_tick_size, "price_tick_size")
        stored: dict[str, Decimal] = {}
        for name in (
            "index_lower",
            "index_upper",
            "trade_candle_low",
            "trade_candle_high",
            "price_lower",
            "price_upper",
        ):
            value = _canonical_positive_decimal(getattr(self, name), name)
            if value % tick != 0:
                raise ManifestError(f"{name} is not a multiple of price_tick_size (tick-aligned)")
            stored[name] = value
        nominal_lower = _fraction_field(self.nominal_lower, "nominal_lower")
        nominal_upper = _fraction_field(self.nominal_upper, "nominal_upper")
        try:
            index_lower, index_upper = tick_widened_bounds(nominal_lower, nominal_upper, tick=tick)
            price_lower, price_upper = union_bounds(
                stored["index_lower"],
                stored["index_upper"],
                stored["trade_candle_low"],
                stored["trade_candle_high"],
            )
        except SettlementEvidenceError as exc:
            raise ManifestError(f"terminal settlement bounds are inconsistent: {exc}") from None
        for name, expected in (
            ("index_lower", index_lower),
            ("index_upper", index_upper),
            ("price_lower", price_lower),
            ("price_upper", price_upper),
        ):
            if stored[name] != expected:
                rule = "tick-widened nominal bound" if name.startswith("index") else "union"
                raise ManifestError(f"{name} does not equal the {rule} it must follow")
        if not stored["price_lower"] < stored["price_upper"]:
            raise ManifestError("price_lower must be below price_upper")
        for name in ("index_klines", "trade_kline"):
            if not isinstance(getattr(self, name), EvidenceFile):
                raise ManifestError(f"{name} must be an EvidenceFile")
        support = self.supporting_evidence
        if not isinstance(support, tuple) or not all(isinstance(f, EvidenceFile) for f in support):
            raise ManifestError("supporting_evidence must be a tuple of EvidenceFile")
        paths = [f.path for f in support]
        if len(set(paths)) != len(paths):
            raise ManifestError("supporting_evidence paths must be unique")
        if paths != sorted(paths):
            raise ManifestError("supporting_evidence must be sorted by path")
        if not isinstance(self.condition, str) or not self.condition.strip():
            raise ManifestError("condition must be a non-empty string")
        if self.official_confirmation is not None:
            raise ManifestError("official_confirmation must be null (no official source exists)")

    def nominal_bounds(self) -> tuple[Fraction, Fraction]:
        """The stored nominal bounds as exact Fractions (parsed from their reduced text)."""
        return (
            parse_fraction_text(self.nominal_lower),
            parse_fraction_text(self.nominal_upper),
        )

    def canonical(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "recorded_evaluation": self.recorded_evaluation,
            "bound_window_start_utc": self.bound_window_start_utc,
            "samples_per_minute": self.samples_per_minute,
            "nominal_lower": self.nominal_lower,
            "nominal_upper": self.nominal_upper,
            "price_tick_size": self.price_tick_size,
            "index_lower": self.index_lower,
            "index_upper": self.index_upper,
            "trade_candle_low": self.trade_candle_low,
            "trade_candle_high": self.trade_candle_high,
            "price_lower": self.price_lower,
            "price_upper": self.price_upper,
            "index_klines": self.index_klines.canonical(),
            "trade_kline": self.trade_kline.canonical(),
            "supporting_evidence": [f.canonical() for f in self.supporting_evidence],
            "condition": self.condition,
            "official_confirmation": self.official_confirmation,
        }


@dataclass(frozen=True)
class SplitWindow:
    """One window the runner simulates: its role and half-open UTC boundaries."""

    role: str
    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True)
class DatasetManifest:
    """The immutable preregistered description of the data one research run reads.

    `dataset_id` is the `dataset_identity` of the published files the runner reads: the
    research window, development start through validation end (the holdout is never read
    here). `constraint_source` is a JSON file of point-in-time exchange constraints and
    `constraint_sha256` the hash of its bytes. `known_gaps` are the terminal declarations
    (plan 16-54, KG-2 wrapper): one per symbol, each with a required reason, the terminal
    instant and the official source, all inside the hash. A hole that no declaration explains
    is not acknowledged by the manifest.

    `terminal_settlements` (quick 261014-nnl) is optional and last: one bounded settlement
    per declared symbol, keyed by symbol, whose terminal instant is the declaration's and
    must lie strictly inside the Development window. It is left out of `canonical()` when
    empty, so a manifest without one keeps its hash.
    """

    universe_id: str
    symbols: tuple[str, ...]
    dataset_id: str
    development_start_utc: datetime
    development_end_utc: datetime
    validation_start_utc: datetime
    validation_end_utc: datetime
    holdout_start_utc: datetime
    holdout_end_utc: datetime
    strategy_interval: str
    context_interval: str
    data_source: str
    data_source_version: str
    excluded_periods: tuple[Period, ...]
    known_gaps: tuple[TerminalDeclaration, ...]
    equity: Decimal
    risk_rate: Decimal
    constraint_source: str
    constraint_sha256: str
    terminal_settlements: tuple[TerminalSettlement, ...] = ()

    def __post_init__(self) -> None:
        if not self.universe_id or not self.symbols:
            raise ManifestError("universe_id and symbols must be non-empty")
        if len(set(self.symbols)) != len(self.symbols):
            raise ManifestError("symbols must be unique")
        _require_hex64(self.dataset_id, "dataset_id")
        _require_hex64(self.constraint_sha256, "constraint_sha256")
        bounds = (
            self.development_start_utc,
            self.development_end_utc,
            self.validation_start_utc,
            self.validation_end_utc,
            self.holdout_start_utc,
            self.holdout_end_utc,
        )
        names = (
            "development_start_utc",
            "development_end_utc",
            "validation_start_utc",
            "validation_end_utc",
            "holdout_start_utc",
            "holdout_end_utc",
        )
        for value, name in zip(bounds, names, strict=True):
            _require_day_boundary(value, name)
        if not (
            self.development_start_utc < self.development_end_utc
            and self.development_end_utc == self.validation_start_utc
            and self.validation_start_utc < self.validation_end_utc
            and self.validation_end_utc == self.holdout_start_utc
            and self.holdout_start_utc < self.holdout_end_utc
        ):
            raise ManifestError(
                "development, validation and holdout must be consecutive, non-empty and "
                "contiguous (each end equals the next start)"
            )
        if not (
            isinstance(self.equity, Decimal)
            and isinstance(self.risk_rate, Decimal)
            and self.equity.is_finite()
            and self.risk_rate.is_finite()
            and self.equity > 0
            and self.risk_rate > 0
        ):
            raise ManifestError("equity and risk_rate must be positive finite Decimals")
        seen: set[str] = set()
        for declaration in self.known_gaps:
            if not isinstance(declaration, TerminalDeclaration):
                raise ManifestError("known_gaps must hold terminal declarations")
            if declaration.symbol not in self.symbols:
                raise ManifestError("a known gap declaration names a symbol outside the universe")
            if declaration.symbol in seen:
                raise ManifestError("more than one known gap declaration for a symbol")
            seen.add(declaration.symbol)
            _check_source_url(declaration.source_url)
        self._check_terminal_settlements()

    def _check_terminal_settlements(self) -> None:
        """Design sections 2 and 4: cross-validation and the Validation / Holdout guard."""
        declared = {g.symbol: g for g in self.known_gaps}
        settled: set[str] = set()
        for entry in self.terminal_settlements:
            if not isinstance(entry, TerminalSettlement):
                raise ManifestError("terminal_settlements must hold TerminalSettlement entries")
            if entry.symbol in settled:
                raise ManifestError("more than one terminal settlement for a symbol")
            settled.add(entry.symbol)
            declaration = declared.get(entry.symbol)
            if declaration is None:
                raise ManifestError(
                    f"a terminal settlement for {entry.symbol} needs a known_gaps declaration "
                    "for that symbol"
                )
            terminal = declaration.terminal_at_utc
            if terminal >= self.validation_start_utc:
                raise ManifestError(
                    f"the declared terminal of {entry.symbol} is at or after validation_start_utc: "
                    "its settlement would reach Validation or Holdout"
                )
            if terminal <= self.development_start_utc:
                raise ManifestError(
                    f"the declared terminal of {entry.symbol} is at or before "
                    "development_start_utc: a settlement must lie inside the Development window"
                )
            if (terminal.second, terminal.microsecond) != (0, 0):
                raise ManifestError(
                    f"the declared terminal of {entry.symbol} must be minute-aligned "
                    "for a terminal settlement"
                )
            if entry.bound_window_start_utc >= terminal:
                raise ManifestError(
                    f"bound_window_start_utc of {entry.symbol} must be before the declared terminal"
                )

    def validation_folds(self) -> tuple[tuple[datetime, datetime], ...]:
        """The four consecutive equal-length walk-forward test folds of the validation block."""
        days = (self.validation_end_utc - self.validation_start_utc) // _ONE_DAY
        if days % VALIDATION_FOLD_COUNT != 0:
            raise ManifestError(
                f"the validation block has {days} whole days, which is not divisible into "
                f"{VALIDATION_FOLD_COUNT} equal folds"
            )
        step = _ONE_DAY * (days // VALIDATION_FOLD_COUNT)
        return tuple(
            (self.validation_start_utc + step * i, self.validation_start_utc + step * (i + 1))
            for i in range(VALIDATION_FOLD_COUNT)
        )

    def canonical(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "universe_id": self.universe_id,
            "symbols": list(self.symbols),
            "dataset_id": self.dataset_id,
            "development_start_utc": self.development_start_utc,
            "development_end_utc": self.development_end_utc,
            "validation_start_utc": self.validation_start_utc,
            "validation_end_utc": self.validation_end_utc,
            "holdout_start_utc": self.holdout_start_utc,
            "holdout_end_utc": self.holdout_end_utc,
            "strategy_interval": self.strategy_interval,
            "context_interval": self.context_interval,
            "data_source": self.data_source,
            "data_source_version": self.data_source_version,
            "excluded_periods": [p.canonical() for p in self.excluded_periods],
            "known_gaps": [
                {
                    "symbol": g.symbol,
                    "reason": g.reason,
                    "terminal_at_utc": g.terminal_at_utc,
                    "source_url": g.source_url,
                }
                for g in self.known_gaps
            ],
            "equity": self.equity,
            "risk_rate": self.risk_rate,
            "constraint_source": self.constraint_source,
            "constraint_sha256": self.constraint_sha256,
        }
        if self.terminal_settlements:
            out["terminal_settlements"] = [t.canonical() for t in self.terminal_settlements]
        return out


@dataclass(frozen=True)
class GridPoint:
    """One registered parameter set of the grid and the keys it varies."""

    parameter_set_id: str
    parameter_set_hash: str
    varied: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.parameter_set_id:
            raise ManifestError("parameter_set_id must be non-empty")
        _require_hex64(self.parameter_set_hash, "parameter_set_hash")

    def canonical(self) -> dict[str, Any]:
        return {
            "parameter_set_id": self.parameter_set_id,
            "parameter_set_hash": self.parameter_set_hash,
            "varied": [[key, value] for key, value in self.varied],
        }


@dataclass(frozen=True)
class ParameterGrid:
    """The strategy and the ordered grid points of one experiment."""

    strategy_id: str
    points: tuple[GridPoint, ...]

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.points:
            raise ManifestError("a grid needs a strategy_id and at least one point")

    def canonical(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "points": [p.canonical() for p in self.points],
        }


def manifest_hash(manifest: DatasetManifest) -> str:
    """The canonical 64-hex hash of the manifest (REV-04, REV-05)."""
    return sha256_hex(manifest.canonical())


def grid_hash(grid: ParameterGrid) -> str:
    """The canonical 64-hex hash of the parameter grid (REV-04)."""
    return sha256_hex(grid.canonical())


def research_splits(manifest: DatasetManifest) -> tuple[SplitWindow, ...]:
    """The windows the runner simulates: development, then the four validation folds.

    The holdout is never part of this list (protocol G5 evaluates it once, after G1 to G4).
    """
    windows = [
        SplitWindow(DEVELOPMENT, manifest.development_start_utc, manifest.development_end_utc)
    ]
    windows.extend(
        SplitWindow(VALIDATION, start, end) for start, end in manifest.validation_folds()
    )
    return tuple(windows)


def _reject_float(text: str) -> Any:
    raise ManifestError(
        "a JSON number with a fraction or exponent is refused: write it as a string"
    )


def read_json_object(path: Path, what: str) -> dict[str, Any]:
    """Read a UTF-8 JSON object from `path`; floats are refused (Decimal-only values)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"{what} file unreadable ({type(exc).__name__})") from None
    try:
        loaded = json.loads(text, parse_float=_reject_float, parse_constant=_reject_float)
    except ManifestError:
        raise
    except ValueError:
        raise ManifestError(f"{what} file is not valid JSON") from None
    if not isinstance(loaded, dict):
        raise ManifestError(f"{what} file must hold a JSON object")
    return loaded


def _exact_keys(payload: Mapping[str, Any], expected: frozenset[str], what: str) -> None:
    keys = set(payload)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ManifestError(f"{what} has missing keys {missing} and unknown keys {extra}")


def _text(payload: Mapping[str, Any], key: str, what: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ManifestError(f"{what} {key} must be a string")
    return value


def _utc(payload: Mapping[str, Any], key: str, what: str) -> datetime:
    try:
        value = datetime.fromisoformat(_text(payload, key, what))
    except ValueError:
        raise ManifestError(f"{what} {key} must be an ISO-8601 UTC timestamp") from None
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ManifestError(f"{what} {key} must carry a UTC offset (Z or +00:00)")
    return value


def _decimal(payload: Mapping[str, Any], key: str, what: str) -> Decimal:
    try:
        return Decimal(_text(payload, key, what))
    except InvalidOperation:
        raise ManifestError(f"{what} {key} must be a decimal string") from None


def _list(payload: Mapping[str, Any], key: str, what: str) -> list[Any]:
    value = payload[key]
    if not isinstance(value, list):
        raise ManifestError(f"{what} {key} must be a list")
    return value


def _object(value: object, what: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{what} must be an object")
    return value


_MANIFEST_KEYS = frozenset(
    {
        "universe_id",
        "symbols",
        "dataset_id",
        "development_start_utc",
        "development_end_utc",
        "validation_start_utc",
        "validation_end_utc",
        "holdout_start_utc",
        "holdout_end_utc",
        "strategy_interval",
        "context_interval",
        "data_source",
        "data_source_version",
        "excluded_periods",
        "known_gaps",
        "equity",
        "risk_rate",
        "constraint_source",
        "constraint_sha256",
    }
)
_SETTLEMENTS_KEY = "terminal_settlements"
_SETTLEMENT_KEYS = frozenset(
    {
        "symbol",
        "kind",
        "recorded_evaluation",
        "bound_window_start_utc",
        "samples_per_minute",
        "nominal_lower",
        "nominal_upper",
        "price_tick_size",
        "index_lower",
        "index_upper",
        "trade_candle_low",
        "trade_candle_high",
        "price_lower",
        "price_upper",
        "index_klines",
        "trade_kline",
        "supporting_evidence",
        "condition",
        "official_confirmation",
    }
)
_EVIDENCE_KEYS = frozenset({"path", "sha256"})
_PERIOD_KEYS = frozenset({"start_utc", "end_utc", "reason"})
_GAP_KEYS = frozenset({"symbol", "reason", "terminal_at_utc", "source_url"})
_POINT_KEYS = frozenset({"parameter_set_id", "parameter_set_hash", "varied"})


def _canonical_decimal(payload: Mapping[str, Any], key: str, what: str) -> Decimal:
    """A Decimal whose JSON text is already its canonical spelling (one file form per value)."""
    text = _text(payload, key, what)
    try:
        value = Decimal(text)
        canonical = canonical_decimal_text(value)
    except (InvalidOperation, ValueError):
        raise ManifestError(f"{what} {key} must be a finite decimal string") from None
    if canonical != text:
        raise ManifestError(f"{what} {key} must be in canonical decimal text, e.g. {canonical!r}")
    return value


def _evidence_file(value: object, what: str) -> EvidenceFile:
    row = _object(value, what)
    _exact_keys(row, _EVIDENCE_KEYS, what)
    return EvidenceFile(path=_text(row, "path", what), sha256=_text(row, "sha256", what))


def _terminal_settlement(value: object) -> TerminalSettlement:
    what = "terminal settlement"
    row = _object(value, what)
    _exact_keys(row, _SETTLEMENT_KEYS, what)
    samples = row["samples_per_minute"]
    if isinstance(samples, bool) or not isinstance(samples, int):
        raise ManifestError(f"{what} samples_per_minute must be a JSON integer")
    return TerminalSettlement(
        symbol=_text(row, "symbol", what),
        kind=_text(row, "kind", what),
        recorded_evaluation=_text(row, "recorded_evaluation", what),
        bound_window_start_utc=_utc(row, "bound_window_start_utc", what),
        samples_per_minute=samples,
        nominal_lower=_text(row, "nominal_lower", what),
        nominal_upper=_text(row, "nominal_upper", what),
        price_tick_size=_canonical_decimal(row, "price_tick_size", what),
        index_lower=_canonical_decimal(row, "index_lower", what),
        index_upper=_canonical_decimal(row, "index_upper", what),
        trade_candle_low=_canonical_decimal(row, "trade_candle_low", what),
        trade_candle_high=_canonical_decimal(row, "trade_candle_high", what),
        price_lower=_canonical_decimal(row, "price_lower", what),
        price_upper=_canonical_decimal(row, "price_upper", what),
        index_klines=_evidence_file(row["index_klines"], "terminal settlement index_klines"),
        trade_kline=_evidence_file(row["trade_kline"], "terminal settlement trade_kline"),
        supporting_evidence=tuple(
            _evidence_file(item, "terminal settlement supporting_evidence entry")
            for item in _list(row, "supporting_evidence", what)
        ),
        condition=_text(row, "condition", what),
        official_confirmation=row["official_confirmation"],
    )


def load_manifest(path: Path) -> DatasetManifest:
    """Parse a manifest JSON file into a `DatasetManifest` (strict keys, UTC, Decimal strings).

    The top-level key set is exactly the registered set, plus the optional `terminal_settlements`
    (a non-empty list; an empty list is refused so one manifest has one file form).
    """
    payload = read_json_object(path, "manifest")
    what = "manifest"
    with_settlements = _SETTLEMENTS_KEY in payload
    _exact_keys(
        payload, _MANIFEST_KEYS | {_SETTLEMENTS_KEY} if with_settlements else _MANIFEST_KEYS, what
    )
    settlements: list[TerminalSettlement] = []
    if with_settlements:
        items = _list(payload, _SETTLEMENTS_KEY, what)
        if not items:
            raise ManifestError("manifest terminal_settlements must not be empty (omit the key)")
        settlements = [_terminal_settlement(item) for item in items]
    symbols = _list(payload, "symbols", what)
    if any(not isinstance(sym, str) for sym in symbols):
        raise ManifestError("manifest symbols must be strings")
    periods: list[Period] = []
    for item in _list(payload, "excluded_periods", what):
        row = _object(item, "excluded period")
        _exact_keys(row, _PERIOD_KEYS, "excluded period")
        periods.append(
            Period(
                _utc(row, "start_utc", "excluded period"),
                _utc(row, "end_utc", "excluded period"),
                _text(row, "reason", "excluded period"),
            )
        )
    gaps: list[TerminalDeclaration] = []
    for item in _list(payload, "known_gaps", what):
        row = _object(item, "known gap")
        _exact_keys(row, _GAP_KEYS, "known gap")
        reason = _text(row, "reason", "known gap")
        if reason not in KNOWN_GAP_REASONS:
            raise ManifestError(f"known gap reason must be one of {sorted(KNOWN_GAP_REASONS)}")
        source_url = _text(row, "source_url", "known gap")
        _check_source_url(source_url)
        try:
            gaps.append(
                TerminalDeclaration(
                    symbol=_text(row, "symbol", "known gap"),
                    reason=reason,
                    terminal_at_utc=_utc(row, "terminal_at_utc", "known gap"),
                    source_url=source_url,
                )
            )
        except CaseInputError as exc:
            raise ManifestError(str(exc)) from None
    return DatasetManifest(
        universe_id=_text(payload, "universe_id", what),
        symbols=tuple(symbols),
        dataset_id=_text(payload, "dataset_id", what),
        development_start_utc=_utc(payload, "development_start_utc", what),
        development_end_utc=_utc(payload, "development_end_utc", what),
        validation_start_utc=_utc(payload, "validation_start_utc", what),
        validation_end_utc=_utc(payload, "validation_end_utc", what),
        holdout_start_utc=_utc(payload, "holdout_start_utc", what),
        holdout_end_utc=_utc(payload, "holdout_end_utc", what),
        strategy_interval=_text(payload, "strategy_interval", what),
        context_interval=_text(payload, "context_interval", what),
        data_source=_text(payload, "data_source", what),
        data_source_version=_text(payload, "data_source_version", what),
        excluded_periods=tuple(periods),
        known_gaps=tuple(gaps),
        equity=_decimal(payload, "equity", what),
        risk_rate=_decimal(payload, "risk_rate", what),
        constraint_source=_text(payload, "constraint_source", what),
        constraint_sha256=_text(payload, "constraint_sha256", what),
        terminal_settlements=tuple(settlements),
    )


def load_grid(path: Path) -> ParameterGrid:
    """Parse a parameter-grid JSON file into a `ParameterGrid` (strict keys)."""
    payload = read_json_object(path, "grid")
    _exact_keys(payload, frozenset({"strategy_id", "points"}), "grid")
    points: list[GridPoint] = []
    for item in _list(payload, "points", "grid"):
        row = _object(item, "grid point")
        _exact_keys(row, _POINT_KEYS, "grid point")
        varied: list[tuple[str, str]] = []
        for pair in _list(row, "varied", "grid point"):
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(part, str) for part in pair)
            ):
                raise ManifestError("grid point varied must be a list of [key, value] strings")
            varied.append((pair[0], pair[1]))
        points.append(
            GridPoint(
                parameter_set_id=_text(row, "parameter_set_id", "grid point"),
                parameter_set_hash=_text(row, "parameter_set_hash", "grid point"),
                varied=tuple(varied),
            )
        )
    return ParameterGrid(strategy_id=_text(payload, "strategy_id", "grid"), points=tuple(points))


__all__ = [
    "DEVELOPMENT",
    "KNOWN_GAP_REASONS",
    "KNOWN_GAP_REASON_DELISTED_CAPPED",
    "KNOWN_GAP_SOURCE_HOSTS",
    "VALIDATION",
    "SAMPLES_PER_MINUTE",
    "DatasetManifest",
    "EvidenceFile",
    "GridPoint",
    "ManifestError",
    "ParameterGrid",
    "Period",
    "SplitWindow",
    "TerminalSettlement",
    "grid_hash",
    "load_grid",
    "load_manifest",
    "manifest_hash",
    "read_json_object",
    "research_splits",
]


if __name__ == "__main__":  # pragma: no cover - thin entry point, tested through manifest_build
    from src.research.manifest_build import main as _build_main

    raise SystemExit(_build_main())
