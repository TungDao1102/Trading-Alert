"""Approval-delay impact reports (Phase 10, plan 10-06, D-02, METRICS section 3).

Three reports are computed over the same metric block and rendered side by side
so selection bias and time-availability effects stay visible:

- SYSTEM: every valid signal. Per-signal R is the realized R when supplied, else
  the hypothetical R when supplied.
- USER_EXECUTION: approved (user-executed) signals only, realized R only.
- OPPORTUNITY: skipped / expired signals only, hypothetical R only.

Differences between the reports are DESCRIPTIVE ONLY (D-02): no block ranks,
subtracts from or recommends over another, and nothing here gives timing advice.

Nothing is imputed: an opportunity signal without an explicitly supplied
hypothetical outcome is INCOMPLETE(NO_HYPOTHETICAL_OUTCOME), never a default R.

Paper approval time is the fixed `APPROVAL_DELAY_LAG_SECONDS` constant (imported,
never redefined or modified here), so a PAPER section carries the SYNTHETIC LAG
label and is never presented as measured latency (RESEARCH P2, D-05).

The signal->approve delay-bucket table (<1m, 1-5m, 5-30m, >=30m; bin edges are a
documented display default, RESEARCH A2) is computed from approved (USER_EXECUTED)
LIVE rows ONLY; skipped / expired signals have no approval time and are never bucketed.
PAPER and BACKTEST evidence never produce buckets. The measured live signal->approve
distribution is reported as calibration evidence while the paper constant stays
unchanged (RESEARCH Open Question 4).

Evidence stays unpooled: every section takes exactly one `EvidenceKind`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.analytics.lifecycle import LifecyclePath, LifecycleRecord
from src.analytics.stats import (
    dist_stat,
    estimate_mean,
    is_low_n,
    micros_since_epoch,
    seconds_between,
    seed_for,
)
from src.analytics.types import (
    DEFAULT_BASE_SEED,
    DEFAULT_RESAMPLES,
    AnalyticsInputError,
    DistStat,
    Estimate,
    EvidenceKind,
    IncompleteReason,
)
from src.core._decimal import _div
from src.domain.canonical import sha256_hex
from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS

_ZERO = Decimal(0)
SYNTHETIC_LAG_LABEL = f"SYNTHETIC LAG (APPROVAL_DELAY_LAG_SECONDS={APPROVAL_DELAY_LAG_SECONDS})"


class ReportLabel(str, Enum):
    """The three METRICS section 3 reports, in fixed side-by-side order."""

    SYSTEM = "SYSTEM"
    USER_EXECUTION = "USER_EXECUTION"
    OPPORTUNITY = "OPPORTUNITY"


class DelayBucket(str, Enum):
    """Signal->approve delay buckets in the fixed UI-SPEC D-1 row order."""

    LT_1M = "<1m"
    M1_TO_5 = "1-5m"
    M5_TO_30 = "5-30m"
    GE_30M = ">=30m"


_BUCKET_ORDER: tuple[DelayBucket, ...] = tuple(DelayBucket)
# Bin edges in exact Decimal seconds: [0, 60) [60, 300) [300, 1800) [1800, inf).
_EDGE_1M = Decimal(60)
_EDGE_5M = Decimal(300)
_EDGE_30M = Decimal(1800)
# Seed ordinals: report blocks use 0-2, delay buckets 3-6, measured delay 7.
_BLOCK_ORDINALS: dict[ReportLabel, int] = {label: index for index, label in enumerate(ReportLabel)}
_BUCKET_ORDINAL_BASE = len(ReportLabel)
_MEASURED_DELAY_ORDINAL = _BUCKET_ORDINAL_BASE + len(_BUCKET_ORDER)


def delay_bucket_for(delay_seconds: Decimal) -> DelayBucket | None:
    """The bucket for an exact Decimal delay in seconds; None for a negative delay."""
    if not isinstance(delay_seconds, Decimal) or not delay_seconds.is_finite():
        raise AnalyticsInputError("delay_seconds must be a finite Decimal")
    if delay_seconds < _ZERO:
        return None
    if delay_seconds < _EDGE_1M:
        return DelayBucket.LT_1M
    if delay_seconds < _EDGE_5M:
        return DelayBucket.M1_TO_5
    if delay_seconds < _EDGE_30M:
        return DelayBucket.M5_TO_30
    return DelayBucket.GE_30M


@dataclass(frozen=True)
class ApprovalDelayBlock:
    """One report's metric block (n, R statistics, INCOMPLETE reasons)."""

    label: ReportLabel
    n_signals: int
    n_r_valued: int
    mean_r: Estimate
    win_rate: Decimal | None
    expectancy_r: Decimal | None
    incomplete: tuple[tuple[str, int], ...]
    hypothetical_used: bool

    def digest(self) -> str:
        return sha256_hex(
            {
                "label": self.label,
                "n_signals": self.n_signals,
                "n_r_valued": self.n_r_valued,
                "mean_r": self.mean_r.digest(),
                "win_rate": self.win_rate,
                "expectancy_r": self.expectancy_r,
                "incomplete": [[reason, count] for reason, count in self.incomplete],
                "hypothetical_used": self.hypothetical_used,
            }
        )


@dataclass(frozen=True)
class DelayBucketRow:
    """One signal->approve delay bucket (LIVE rows only)."""

    bucket: DelayBucket
    n: int
    n_r_valued: int
    mean_r: Estimate
    low_n: bool
    incomplete: tuple[tuple[str, int], ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "bucket": self.bucket,
                "n": self.n,
                "n_r_valued": self.n_r_valued,
                "mean_r": self.mean_r.digest(),
                "low_n": self.low_n,
                "incomplete": [[reason, count] for reason, count in self.incomplete],
            }
        )


@dataclass(frozen=True)
class ApprovalDelaySection:
    """Digest-stamped approval-delay section for exactly one EvidenceKind."""

    evidence: EvidenceKind
    system: ApprovalDelayBlock
    user_execution: ApprovalDelayBlock
    opportunity: ApprovalDelayBlock
    buckets: tuple[DelayBucketRow, ...]
    measured_delay: DistStat | None
    delay_incomplete: tuple[tuple[str, int], ...]
    synthetic_lag_seconds: int | None
    synthetic_lag_label: str | None
    base_seed: int
    resamples: int

    def digest(self) -> str:
        return sha256_hex(
            {
                "evidence": self.evidence,
                "system": self.system.digest(),
                "user_execution": self.user_execution.digest(),
                "opportunity": self.opportunity.digest(),
                "buckets": [row.digest() for row in self.buckets],
                "measured_delay": (
                    None if self.measured_delay is None else self.measured_delay.digest()
                ),
                "delay_incomplete": [[reason, count] for reason, count in self.delay_incomplete],
                "synthetic_lag_seconds": self.synthetic_lag_seconds,
                "synthetic_lag_label": self.synthetic_lag_label,
                "base_seed": self.base_seed,
                "resamples": self.resamples,
            }
        )


def _record_key(record: LifecycleRecord) -> str:
    """The signal key: signal_id when present, else source_id."""
    return record.signal_id if record.signal_id is not None else record.source_id


def _time_order_key(record: LifecycleRecord) -> tuple[bool, int, str]:
    """Total order: detection time (undated last), then the signal key."""
    detected = record.signal_detected_at_utc
    return (
        detected is None,
        0 if detected is None else micros_since_epoch(detected),
        _record_key(record),
    )


def _default_reason(record: LifecycleRecord) -> IncompleteReason:
    """Why a record without any supplied R is INCOMPLETE (per evidence kind)."""
    if record.evidence is EvidenceKind.PAPER:
        return IncompleteReason.NO_PAPER_OUTCOME
    if record.evidence is EvidenceKind.LIVE:
        if record.fill_time_utc is not None:
            return IncompleteReason.OPEN_POSITION
        return IncompleteReason.NO_FILL_EVENT
    if record.entry_filled is False:
        return IncompleteReason.NO_FILL_EVENT
    return IncompleteReason.NOT_MEASURED_FOR_EVIDENCE


@dataclass(frozen=True)
class _Resolved:
    """One record's R for one block: a value (and its source) or an INCOMPLETE reason."""

    r: Decimal | None
    hypothetical: bool
    reason: IncompleteReason | None


def _resolve_system(
    record: LifecycleRecord,
    realized: Mapping[str, Decimal],
    hypothetical: Mapping[str, Decimal],
) -> _Resolved:
    key = _record_key(record)
    if key in realized:
        return _Resolved(realized[key], False, None)
    if key in hypothetical:
        return _Resolved(hypothetical[key], True, None)
    if record.path is LifecyclePath.OPPORTUNITY:
        return _Resolved(None, False, IncompleteReason.NO_HYPOTHETICAL_OUTCOME)
    return _Resolved(None, False, _default_reason(record))


def _resolve_user(record: LifecycleRecord, realized: Mapping[str, Decimal]) -> _Resolved:
    key = _record_key(record)
    if key in realized:
        return _Resolved(realized[key], False, None)
    return _Resolved(None, False, _default_reason(record))


def _resolve_opportunity(record: LifecycleRecord, hypothetical: Mapping[str, Decimal]) -> _Resolved:
    key = _record_key(record)
    if key in hypothetical:
        return _Resolved(hypothetical[key], True, None)
    return _Resolved(None, False, IncompleteReason.NO_HYPOTHETICAL_OUTCOME)


def _build_block(
    label: ReportLabel,
    resolved: Sequence[_Resolved],
    *,
    base_seed: int,
    resamples: int,
) -> ApprovalDelayBlock:
    """Aggregate resolved per-record R values (already in stable time order)."""
    values = [item.r for item in resolved if item.r is not None]
    counts: dict[str, int] = {}
    for item in resolved:
        if item.reason is not None:
            counts[item.reason.value] = counts.get(item.reason.value, 0) + 1
    n_signals = len(resolved)
    mean_r = estimate_mean(
        values,
        seed=seed_for(base_seed, _BLOCK_ORDINALS[label]),
        resamples=resamples,
        n=n_signals,
    )
    wins = sum(1 for value in values if value > _ZERO)
    return ApprovalDelayBlock(
        label=label,
        n_signals=n_signals,
        n_r_valued=len(values),
        mean_r=mean_r,
        win_rate=None if not values else _div(Decimal(wins), Decimal(len(values))),
        expectancy_r=mean_r.value,
        incomplete=tuple(sorted(counts.items())),
        hypothetical_used=any(item.hypothetical for item in resolved),
    )


def _build_delay(
    ordered: Sequence[LifecycleRecord],
    realized: Mapping[str, Decimal],
    *,
    base_seed: int,
    resamples: int,
) -> tuple[tuple[DelayBucketRow, ...], DistStat, tuple[tuple[str, int], ...]]:
    """LIVE delay buckets + measured signal->approve distribution + excluded counts.

    Only USER_EXECUTED records with an approval action time enter: the table measures
    signal->approve, and a skipped or expired (OPPORTUNITY) signal is never "approved"
    (the live normalizer sets `approved_at_utc` for APPROVED decisions only). OPPORTUNITY
    signals are reported in the OPPORTUNITY block, not here. A missing signal time is
    UNMATCHED_JOIN and a negative delay is NEGATIVE_INTERVAL; both are counted and
    excluded, never bucketed or imputed.
    """
    per_bucket: dict[DelayBucket, list[_Resolved]] = {bucket: [] for bucket in _BUCKET_ORDER}
    delays: list[Decimal] = []
    excluded: dict[str, int] = {}
    for record in ordered:
        if record.path is not LifecyclePath.USER_EXECUTED or record.approved_at_utc is None:
            continue
        if record.signal_detected_at_utc is None:
            reason = IncompleteReason.UNMATCHED_JOIN.value
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        delay = seconds_between(record.signal_detected_at_utc, record.approved_at_utc)
        bucket = delay_bucket_for(delay)
        if bucket is None:
            reason = IncompleteReason.NEGATIVE_INTERVAL.value
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        delays.append(delay)
        per_bucket[bucket].append(_resolve_user(record, realized))
    rows: list[DelayBucketRow] = []
    for index, bucket in enumerate(_BUCKET_ORDER):
        resolved = per_bucket[bucket]
        values = [item.r for item in resolved if item.r is not None]
        counts: dict[str, int] = {}
        for item in resolved:
            if item.reason is not None:
                counts[item.reason.value] = counts.get(item.reason.value, 0) + 1
        rows.append(
            DelayBucketRow(
                bucket=bucket,
                n=len(resolved),
                n_r_valued=len(values),
                mean_r=estimate_mean(
                    values,
                    seed=seed_for(base_seed, _BUCKET_ORDINAL_BASE + index),
                    resamples=resamples,
                    n=len(resolved),
                ),
                low_n=is_low_n(len(values)),
                incomplete=tuple(sorted(counts.items())),
            )
        )
    measured = dist_stat(
        delays,
        seed=seed_for(base_seed, _MEASURED_DELAY_ORDINAL),
        resamples=resamples,
        n=len(delays),
    )
    return tuple(rows), measured, tuple(sorted(excluded.items()))


def _check_mapping(mapping: Mapping[str, Decimal], name: str) -> None:
    for key, value in mapping.items():
        if not isinstance(key, str) or key == "":
            raise AnalyticsInputError(f"{name} keys must be non-empty str, got {key!r}")
        if not isinstance(value, Decimal) or not value.is_finite():
            raise AnalyticsInputError(f"{name}[{key!r}] must be a finite Decimal")


def build_approval_delay(
    records: Sequence[LifecycleRecord],
    *,
    evidence: EvidenceKind,
    realized_r_by_signal: Mapping[str, Decimal],
    hypothetical_r_by_signal: Mapping[str, Decimal],
    base_seed: int = DEFAULT_BASE_SEED,
    resamples: int = DEFAULT_RESAMPLES,
) -> ApprovalDelaySection:
    """Build the three side-by-side reports for one evidence kind.

    Hypothetical outcomes come only from `hypothetical_r_by_signal`; a missing
    entry is INCOMPLETE(NO_HYPOTHETICAL_OUTCOME), never imputed. Mixed evidence
    kinds and duplicate signal keys fail closed with `AnalyticsInputError`.
    """
    if not isinstance(evidence, EvidenceKind):
        raise AnalyticsInputError("evidence must be an EvidenceKind")
    _check_mapping(realized_r_by_signal, "realized_r_by_signal")
    _check_mapping(hypothetical_r_by_signal, "hypothetical_r_by_signal")
    for record in records:
        if record.evidence is not evidence:
            raise AnalyticsInputError(
                f"mixed evidence: record {record.source_id!r} is {record.evidence.value}, "
                f"section is {evidence.value} (evidence kinds are never pooled)"
            )
    ordered = sorted(records, key=_time_order_key)
    keys = [_record_key(record) for record in ordered]
    if len(set(keys)) != len(keys):
        raise AnalyticsInputError("duplicate signal key in approval-delay records")
    system = [_resolve_system(r, realized_r_by_signal, hypothetical_r_by_signal) for r in ordered]
    user = [
        _resolve_user(r, realized_r_by_signal)
        for r in ordered
        if r.path is LifecyclePath.USER_EXECUTED
    ]
    opportunity = [
        _resolve_opportunity(r, hypothetical_r_by_signal)
        for r in ordered
        if r.path is LifecyclePath.OPPORTUNITY
    ]
    is_paper = evidence is EvidenceKind.PAPER
    buckets: tuple[DelayBucketRow, ...] = ()
    measured_delay: DistStat | None = None
    delay_incomplete: tuple[tuple[str, int], ...] = ()
    if evidence is EvidenceKind.LIVE:
        buckets, measured_delay, delay_incomplete = _build_delay(
            ordered,
            realized_r_by_signal,
            base_seed=base_seed,
            resamples=resamples,
        )
    return ApprovalDelaySection(
        evidence=evidence,
        system=_build_block(ReportLabel.SYSTEM, system, base_seed=base_seed, resamples=resamples),
        user_execution=_build_block(
            ReportLabel.USER_EXECUTION, user, base_seed=base_seed, resamples=resamples
        ),
        opportunity=_build_block(
            ReportLabel.OPPORTUNITY, opportunity, base_seed=base_seed, resamples=resamples
        ),
        buckets=buckets,
        measured_delay=measured_delay,
        delay_incomplete=delay_incomplete,
        synthetic_lag_seconds=APPROVAL_DELAY_LAG_SECONDS if is_paper else None,
        synthetic_lag_label=SYNTHETIC_LAG_LABEL if is_paper else None,
        base_seed=base_seed,
        resamples=resamples,
    )
