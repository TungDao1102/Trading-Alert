"""Immutable dataset manifest and parameter grid with canonical hashes (D-25, REV-04, REV-05).

The manifest fixes everything a research run reads: universe, dataset identity, the exact
development / validation / holdout boundaries, candle intervals, data source and version,
excluded periods, known terminal declarations, the research account inputs and the
constraint source. The
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
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.data.case_input import (
    TERMINAL_REASON_DELISTED_CAPPED,
    TERMINAL_REASONS,
    CaseInputError,
    TerminalDeclaration,
)
from src.domain.canonical import sha256_hex

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
        return {
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
_PERIOD_KEYS = frozenset({"start_utc", "end_utc", "reason"})
_GAP_KEYS = frozenset({"symbol", "reason", "terminal_at_utc", "source_url"})
_POINT_KEYS = frozenset({"parameter_set_id", "parameter_set_hash", "varied"})


def load_manifest(path: Path) -> DatasetManifest:
    """Parse a manifest JSON file into a `DatasetManifest` (strict keys, UTC, Decimal strings)."""
    payload = read_json_object(path, "manifest")
    what = "manifest"
    _exact_keys(payload, _MANIFEST_KEYS, what)
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
    "DatasetManifest",
    "GridPoint",
    "ManifestError",
    "ParameterGrid",
    "Period",
    "SplitWindow",
    "grid_hash",
    "load_grid",
    "load_manifest",
    "manifest_hash",
    "read_json_object",
    "research_splits",
]
