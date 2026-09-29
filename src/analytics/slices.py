"""Robustness slice tables (Phase 10, plan 10-04, D-02 / METRICS section 5, JRN-01).

Every table leads with the unsliced ALL row (the full report is never hidden),
then slice rows in a documented stable key order - NEVER by any favorability
measure. Low-n slices carry a `low_n` display flag but stay in place; UNKNOWN and
INCOMPLETE buckets are pinned last (UNKNOWN before INCOMPLETE). Each slice row is
a `CoreMetrics` projection, so its estimate keeps the Phase-6 uncertainty
presentation (n plus a bootstrap interval or an explicit interval-absent marker).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.analytics.core_metrics import CoreMetrics, compute_core_metrics
from src.analytics.types import (
    AnalyticsInputError,
    Estimate,
    EvidenceKind,
    TradeOutcome,
)
from src.domain.canonical import sha256_hex

SLICE_VOCABULARY_VERSION = "slices/1"
ALL_KEY = "ALL"
UNKNOWN_KEY = "UNKNOWN"
INCOMPLETE_KEY = "INCOMPLETE"


class SliceDimension(str, Enum):
    """The METRICS section 5 slice dimensions, in fixed display order."""

    SYMBOL = "symbol"
    MONTH = "month"
    QUARTER = "quarter"
    SESSION = "session"
    DIRECTION = "direction"
    VOLATILITY_REGIME = "volatility_regime"
    TREND_RANGE_REGIME = "trend_range_regime"
    STRATEGY_VERSION = "strategy_version"


@dataclass(frozen=True)
class SliceRow:
    """One slice row (or the ALL row): a CoreMetrics projection keyed by slice key."""

    key: str
    n: int
    n_r_valued: int
    zero_risk_excluded: int
    incomplete: int
    mean_r: Estimate
    win_rate: Decimal | None
    expectancy_r: Decimal | None
    low_n: bool

    def digest(self) -> str:
        return sha256_hex(
            {
                "key": self.key,
                "n": self.n,
                "n_r_valued": self.n_r_valued,
                "zero_risk_excluded": self.zero_risk_excluded,
                "incomplete": self.incomplete,
                "mean_r": self.mean_r.digest(),
                "win_rate": self.win_rate,
                "expectancy_r": self.expectancy_r,
                "low_n": self.low_n,
            }
        )


@dataclass(frozen=True)
class SliceTable:
    """One dimension: the ALL row first, then slice rows in stable key order."""

    dimension: SliceDimension
    all_row: SliceRow
    rows: tuple[SliceRow, ...]
    slice_count: int
    total_n: int

    def digest(self) -> str:
        return sha256_hex(
            {
                "dimension": self.dimension.value,
                "all_row": self.all_row.digest(),
                "rows": [row.digest() for row in self.rows],
                "slice_count": self.slice_count,
                "total_n": self.total_n,
            }
        )


@dataclass(frozen=True)
class SlicesSection:
    """All slice tables for one evidence kind (evidence kinds are never pooled)."""

    evidence: EvidenceKind
    tables: tuple[SliceTable, ...]
    session_bands: tuple[tuple[str, int, int], ...]
    vocabulary_version: str
    base_seed: int
    resamples: int

    def digest(self) -> str:
        return sha256_hex(
            {
                "evidence": self.evidence.value,
                "tables": [table.digest() for table in self.tables],
                "session_bands": [list(band) for band in self.session_bands],
                "vocabulary_version": self.vocabulary_version,
                "base_seed": self.base_seed,
                "resamples": self.resamples,
            }
        )


# (label, start_hour_inclusive, end_hour_exclusive) over the UTC hour of ENTRY time.
SESSION_BANDS: tuple[tuple[str, int, int], ...] = (
    ("ASIA", 0, 8),
    ("EUROPE", 8, 16),
    ("US", 16, 24),
)

# A key function returns the slice label, or one of the reserved bucket labels.
KeyFn = Callable[[TradeOutcome], str]


def _row(key: str, metrics: CoreMetrics) -> SliceRow:
    return SliceRow(
        key=key,
        n=metrics.n,
        n_r_valued=metrics.n_r_valued,
        zero_risk_excluded=metrics.zero_risk_excluded,
        incomplete=metrics.incomplete,
        mean_r=metrics.mean_r,
        win_rate=metrics.win_rate,
        expectancy_r=metrics.expectancy_r,
        low_n=metrics.low_n,
    )


def _build_table(
    dimension: SliceDimension,
    outcomes: Sequence[TradeOutcome],
    key_fn: KeyFn,
    *,
    base_seed: int,
    resamples: int,
) -> SliceTable:
    """Generic builder: ALL row (ordinal 0), then keyed rows, UNKNOWN, INCOMPLETE.

    Ordering is by the label's plain ascending string order - a documented stable
    key, never a metric value. Rows take bootstrap ordinals 1..k in display order.
    """
    groups: dict[str, list[TradeOutcome]] = {}
    for outcome in outcomes:
        groups.setdefault(key_fn(outcome), []).append(outcome)
    ordered = sorted(key for key in groups if key not in (UNKNOWN_KEY, INCOMPLETE_KEY))
    for bucket in (UNKNOWN_KEY, INCOMPLETE_KEY):
        if bucket in groups:
            ordered.append(bucket)
    all_row = _row(
        ALL_KEY,
        compute_core_metrics(outcomes, base_seed=base_seed, resamples=resamples, ordinal=0),
    )
    rows = tuple(
        _row(
            key,
            compute_core_metrics(
                groups[key], base_seed=base_seed, resamples=resamples, ordinal=ordinal
            ),
        )
        for ordinal, key in enumerate(ordered, start=1)
    )
    return SliceTable(
        dimension=dimension,
        all_row=all_row,
        rows=rows,
        slice_count=len(rows),
        total_n=len(outcomes),
    )


def _symbol_key(outcome: TradeOutcome) -> str:
    return outcome.symbol


_KEY_FUNCTIONS: tuple[tuple[SliceDimension, KeyFn], ...] = ((SliceDimension.SYMBOL, _symbol_key),)


def build_slices(
    outcomes: Sequence[TradeOutcome],
    *,
    evidence: EvidenceKind,
    base_seed: int,
    resamples: int,
) -> SlicesSection:
    """Build the slice tables for one evidence kind (mixed evidence fails closed)."""
    for outcome in outcomes:
        if outcome.evidence is not evidence:
            raise AnalyticsInputError(
                f"outcome {outcome.trade_id!r} has evidence {outcome.evidence.value}, "
                f"expected {evidence.value} (evidence kinds are never pooled)"
            )
    tables = tuple(
        _build_table(dimension, outcomes, key_fn, base_seed=base_seed, resamples=resamples)
        for dimension, key_fn in _KEY_FUNCTIONS
    )
    return SlicesSection(
        evidence=evidence,
        tables=tables,
        session_bands=SESSION_BANDS,
        vocabulary_version=SLICE_VOCABULARY_VERSION,
        base_seed=base_seed,
        resamples=resamples,
    )
