"""Immutable dataset manifest and parameter grid with canonical hashes (D-25, REV-04, REV-05).

The manifest fixes everything a research run reads: universe, dataset identity, the exact
development / validation / holdout boundaries, candle intervals, data source and version,
excluded periods, known gaps, the research account inputs and the constraint source. The
grid fixes the strategy and the ordered, registered parameter sets of one experiment. Both
hash through `src.domain.canonical.sha256_hex` over a canonical dict (Decimal and datetimes
as strings, UTC only, no float), so the same content always has the same hash and any edit
changes it. The values inside a manifest (window, split dates) are the user's (O-03); this
module defines the shape and the hash, never a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.data.coverage import GapRange
from src.domain.canonical import sha256_hex

DEVELOPMENT = "DEVELOPMENT"
VALIDATION = "VALIDATION"
VALIDATION_FOLD_COUNT = 4
_ONE_DAY = timedelta(days=1)


class ManifestError(ValueError):
    """A manifest, grid or its inputs are malformed or do not match their preregistration."""


def _require_day_boundary(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ManifestError(f"{name} must be a UTC-aware datetime")
    if (value.hour, value.minute, value.second, value.microsecond) != (0, 0, 0, 0):
        raise ManifestError(f"{name} must be at 00:00:00 UTC (whole UTC days only)")
    return value


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
    `constraint_sha256` the hash of its bytes.
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
    known_gaps: tuple[GapRange, ...]
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
                    "series": g.series,
                    "symbol": g.symbol,
                    "interval": g.interval,
                    "start_utc": g.start_utc,
                    "end_utc": g.end_utc,
                    "missing": g.missing,
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


__all__ = [
    "DEVELOPMENT",
    "VALIDATION",
    "DatasetManifest",
    "GridPoint",
    "ManifestError",
    "ParameterGrid",
    "Period",
    "SplitWindow",
    "grid_hash",
    "manifest_hash",
    "research_splits",
]
