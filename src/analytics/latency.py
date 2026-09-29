"""Execution-quality latency engine (Phase 10, plan 10-03, D-02, METRICS section 4).

Six latency legs are computed from journal timestamps in a FIXED order (the
UI-SPEC E-1 row order). Each leg reports how many records were measured, an
INCOMPLETE count per reason, and mean/median/p90 in exact Decimal seconds. A
missing timestamp is never imputed or defaulted to zero (D-02):

- `SIGNAL_TO_SEEN` is always INCOMPLETE(NO_SEEN_TIMESTAMP): no code journals a
  seen timestamp (RESEARCH P1).
- `Approval.requested_at_utc` is a delivery-request PROXY, never a read receipt.
- Paper approval timing is the fixed APPROVAL_DELAY_LAG_SECONDS constant, so a
  PAPER section carries `synthetic_lag_seconds` and is never presented as
  measured latency (RESEARCH P2, D-05).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from src.analytics.lifecycle import LifecycleRecord
from src.analytics.stats import dist_stat, seconds_between, seed_for
from src.analytics.types import (
    DEFAULT_BASE_SEED,
    DEFAULT_RESAMPLES,
    AnalyticsInputError,
    Estimate,
    EvidenceKind,
    IncompleteReason,
)
from src.domain.canonical import sha256_hex
from src.domain.enums import ApprovalResult
from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS

_ZERO = Decimal(0)
_UNIT_SECONDS = "s"


class Leg(str, Enum):
    """Latency legs in the fixed UI-SPEC E-1 row order."""

    SIGNAL_TO_SEEN = "SIGNAL_TO_SEEN"
    SIGNAL_TO_DELIVERY = "SIGNAL_TO_DELIVERY"
    DELIVERY_TO_APPROVED = "DELIVERY_TO_APPROVED"
    SIGNAL_TO_APPROVED = "SIGNAL_TO_APPROVED"
    APPROVED_TO_ORDER = "APPROVED_TO_ORDER"
    ORDER_TO_FILL = "ORDER_TO_FILL"


_LEG_ORDER: tuple[Leg, ...] = tuple(Leg)


@dataclass(frozen=True)
class LegStat:
    """Aggregate for one latency leg (n measured, INCOMPLETE by reason, seconds)."""

    leg: Leg
    n_measured: int
    incomplete: tuple[tuple[str, int], ...]
    mean: Estimate
    median: Decimal | None
    p90: Decimal | None
    unit: str

    def digest(self) -> str:
        return sha256_hex(
            {
                "leg": self.leg,
                "n_measured": self.n_measured,
                "incomplete": [[reason, count] for reason, count in self.incomplete],
                "mean": self.mean.digest(),
                "median": self.median,
                "p90": self.p90,
                "unit": self.unit,
            }
        )


@dataclass(frozen=True)
class ExecutionQualitySection:
    """Digest-stamped execution-quality section for exactly one EvidenceKind."""

    evidence: EvidenceKind
    n_records: int
    legs: tuple[LegStat, ...]  # Leg order
    synthetic_lag_seconds: int | None
    base_seed: int
    resamples: int

    def leg(self, leg: Leg) -> LegStat:
        """The LegStat for one named leg."""
        return self.legs[_LEG_ORDER.index(leg)]

    def digest(self) -> str:
        return sha256_hex(
            {
                "evidence": self.evidence,
                "n_records": self.n_records,
                "legs": [stat.digest() for stat in self.legs],
                "synthetic_lag_seconds": self.synthetic_lag_seconds,
                "base_seed": self.base_seed,
                "resamples": self.resamples,
            }
        )


@dataclass(frozen=True)
class _Interval:
    """One record's outcome on one leg: a measured value or an INCOMPLETE reason."""

    value: Decimal | None
    reason: IncompleteReason | None


def _measure(start: datetime, end: datetime) -> _Interval:
    seconds = seconds_between(start, end)
    if seconds < _ZERO:
        return _Interval(None, IncompleteReason.NEGATIVE_INTERVAL)
    return _Interval(seconds, None)


def _not_measured() -> _Interval:
    return _Interval(None, IncompleteReason.NOT_MEASURED_FOR_EVIDENCE)


def _leg_interval(leg: Leg, record: LifecycleRecord) -> _Interval | None:
    """The record's outcome on `leg`, or None when the leg does not apply."""
    if record.evidence is EvidenceKind.BACKTEST:
        return _not_measured()
    signal_at = record.signal_detected_at_utc
    if leg is Leg.SIGNAL_TO_SEEN:
        if signal_at is None:
            return None
        return _Interval(None, IncompleteReason.NO_SEEN_TIMESTAMP)
    if leg is Leg.SIGNAL_TO_DELIVERY:
        if signal_at is None:
            return None
        if record.delivery_requested_at_utc is not None:
            return _measure(signal_at, record.delivery_requested_at_utc)
        if record.evidence is EvidenceKind.LIVE:
            return _Interval(None, IncompleteReason.NO_APPROVAL)
        return _not_measured()
    if leg is Leg.DELIVERY_TO_APPROVED:
        if record.approved_at_utc is None:
            return None
        if record.delivery_requested_at_utc is None:
            return _not_measured()
        return _measure(record.delivery_requested_at_utc, record.approved_at_utc)
    if leg is Leg.SIGNAL_TO_APPROVED:
        if record.approved_at_utc is None:
            return None
        if signal_at is None:
            return _Interval(None, IncompleteReason.UNMATCHED_JOIN)
        return _measure(signal_at, record.approved_at_utc)
    if leg is Leg.APPROVED_TO_ORDER:
        if record.approved_at_utc is None or record.approval_result is not ApprovalResult.APPROVED:
            return None
        if record.order_submitted_at_utc is None:
            return _Interval(None, IncompleteReason.NO_ORDER)
        return _measure(record.approved_at_utc, record.order_submitted_at_utc)
    # Leg.ORDER_TO_FILL
    if record.order_submitted_at_utc is None:
        return None
    if record.fill_time_utc is None:
        return _Interval(None, IncompleteReason.NO_FILL_EVENT)
    return _measure(record.order_submitted_at_utc, record.fill_time_utc)


def _build_leg(
    leg: Leg,
    records: Sequence[LifecycleRecord],
    *,
    base_seed: int,
    resamples: int,
) -> LegStat:
    values: list[Decimal] = []
    counts: dict[str, int] = {}
    applicable = 0
    for record in records:
        interval = _leg_interval(leg, record)
        if interval is None:
            continue
        applicable += 1
        if interval.value is not None:
            values.append(interval.value)
        elif interval.reason is not None:
            counts[interval.reason.value] = counts.get(interval.reason.value, 0) + 1
    stat = dist_stat(
        values,
        seed=seed_for(base_seed, _LEG_ORDER.index(leg)),
        resamples=resamples,
        n=applicable,
    )
    return LegStat(
        leg=leg,
        n_measured=len(values),
        incomplete=tuple(sorted(counts.items())),
        mean=stat.mean,
        median=stat.median,
        p90=stat.p90,
        unit=_UNIT_SECONDS,
    )


def build_execution_quality(
    records: Sequence[LifecycleRecord],
    *,
    evidence: EvidenceKind,
    base_seed: int = DEFAULT_BASE_SEED,
    resamples: int = DEFAULT_RESAMPLES,
) -> ExecutionQualitySection:
    """Build the digest-stamped execution-quality section for one evidence kind."""
    for record in records:
        if record.evidence is not evidence:
            raise AnalyticsInputError(
                f"mixed evidence: record {record.source_id!r} is {record.evidence.value}, "
                f"section is {evidence.value} (evidence kinds are never pooled)"
            )
    ordered = sorted(records, key=lambda record: record.source_id)
    legs = tuple(
        _build_leg(leg, ordered, base_seed=base_seed, resamples=resamples) for leg in _LEG_ORDER
    )
    return ExecutionQualitySection(
        evidence=evidence,
        n_records=len(ordered),
        legs=legs,
        synthetic_lag_seconds=(
            APPROVAL_DELAY_LAG_SECONDS if evidence is EvidenceKind.PAPER else None
        ),
        base_seed=base_seed,
        resamples=resamples,
    )
