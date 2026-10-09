"""Runtime coverage and freeze-tick evidence (Phase 16, plan 16-15; D-07, D-21, D-22).

Pure evidence functions for the two SEPARATE evidence sets of the exit criteria (D-22, REV-02):

- runtime health and coverage (this module: `HealthInterval`, `derive_health_intervals`,
  `coverage_report`): the denominator is the whole fixed trial window, only HEALTHY time is
  covered, DEGRADED, DISCONNECTED, PLANNED_RESTART, CRASH, PROCESS_DOWN, MAINTENANCE and UNKNOWN
  time is uncovered, and a gap that has a reason is still uncovered (REV-01). The 95 percent
  figure is L-04 (D061 item D); 14 days x 24 h x 0.95 = 319.2 covered hours is DERIVED from it,
  not a second threshold (REV-17).
- freeze-tick continuity (`expected_slots`, `freeze_evidence_report`): every expected scheduled
  freeze slot from the epoch pin to the window end must be satisfied by a CLEAN line of a
  schedule-event run; otherwise an `EvidenceGap` is produced, never CLEAN, never interpolated,
  and the qualifying trial restarts with a new epoch pin (REV-02, REV-18).

These functions REPORT. They never change a threshold, never fill a missing tick, never edit
`registry_diff.jsonl`. Numbers the user owns (healthy-feed silence limit, closed-bar lateness,
the continuous-uncovered ceiling, the freeze-tick grace) are required inputs with no default
(L-09, O-07). The module is pure: stdlib, `Decimal` and project types only, injected times, no
clock reads, no float (the package is float-scanned by `tests/test_domain_no_float.py`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal

from src.paper.vocabulary import GapReason, HealthState

# --------------------------------------------------------------------------- #
# Constants that come from a ratified decision (labels per AGENTS.md conventions).
# --------------------------------------------------------------------------- #

# DECISION D061 item D, 2026-10-07: runtime coverage of at least 95 percent of the trial window.
CRITERION_MIN_FRACTION = Decimal("0.95")

# Fixed decimal context so a quotient never depends on the caller's global context.
_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)

_US_PER_HOUR = 3_600_000_000
_US_PER_SECOND = 1_000_000

DERIVED_MINIMUM_LABEL = (
    "DERIVED (window hours x 0.95, REV-17); a derived value, not a threshold: "
    "the criterion is coverage >= 0.95 of the window"
)

# When intervals overlap, a segment takes the most specific cause. Process-level causes beat
# connection-level causes, which beat "not observed". The order only labels uncovered time (all
# of it is uncovered whatever the label), and it makes the result independent of input order.
_REASON_PRIORITY: tuple[GapReason, ...] = (
    GapReason.CRASH,
    GapReason.PLANNED_RESTART,
    GapReason.PROCESS_DOWN,
    GapReason.MAINTENANCE,
    GapReason.WS_DISCONNECTED,
    GapReason.WS_RECONNECT_WINDOW,
    GapReason.EXCHANGE_NO_CANDLE,
    GapReason.UNKNOWN,
)
_REASON_RANK: Mapping[GapReason, int] = {
    reason: len(_REASON_PRIORITY) - index for index, reason in enumerate(_REASON_PRIORITY)
}
_STATE_RANK: Mapping[HealthState, int] = {
    HealthState.HEALTHY: 0,
    HealthState.DEGRADED: 1,
    HealthState.DISCONNECTED: 2,
}


# --------------------------------------------------------------------------- #
# Small helpers.
# --------------------------------------------------------------------------- #


def _require_utc(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a UTC-aware datetime")


def _micros(delta: timedelta) -> int:
    """Whole microseconds of a timedelta, exactly (no float)."""
    return delta // timedelta(microseconds=1)


def _positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer (seconds), got {value!r}")
    return value


# --------------------------------------------------------------------------- #
# HealthInterval and the segment tiling shared by coverage and health derivation.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HealthInterval:
    """A span of time with one feed-health state and, when not HEALTHY, a reason code."""

    start_utc: datetime
    end_utc: datetime
    state: HealthState
    reason: GapReason | None

    def __post_init__(self) -> None:
        _require_utc("start_utc", self.start_utc)
        _require_utc("end_utc", self.end_utc)
        if self.end_utc <= self.start_utc:
            raise ValueError("a HealthInterval must have end_utc after start_utc")
        if self.state is HealthState.HEALTHY and self.reason is not None:
            raise ValueError("a HEALTHY interval carries no gap reason")


@dataclass(frozen=True)
class _Segment:
    """One elementary stretch of the window after normalisation."""

    start_utc: datetime
    end_utc: datetime
    state: HealthState
    reason: GapReason | None  # None only for a HEALTHY segment

    @property
    def healthy(self) -> bool:
        return self.state is HealthState.HEALTHY


def _effective_reason(interval: HealthInterval) -> GapReason:
    """The reason of a non-HEALTHY interval; a missing one is UNKNOWN (never None)."""
    return interval.reason if interval.reason is not None else GapReason.UNKNOWN


def _tile(
    window_start_utc: datetime,
    window_end_utc: datetime,
    intervals: Iterable[HealthInterval],
) -> list[_Segment]:
    """Normalise intervals into a gap-free, overlap-free tiling of exactly the window.

    Rules (deterministic, independent of input order):
    - intervals are clipped to the window; time outside it earns nothing;
    - where intervals overlap, any non-HEALTHY interval wins over HEALTHY (fail closed), and
      among non-HEALTHY ones the most specific reason wins (`_REASON_PRIORITY`), then the
      more severe state;
    - time with no interval at all is not covered: DISCONNECTED with reason UNKNOWN.
    Adjacent segments that are equal in state and reason are merged.
    """
    clipped: list[HealthInterval] = []
    for interval in intervals:
        start = max(interval.start_utc, window_start_utc)
        end = min(interval.end_utc, window_end_utc)
        if end > start:
            clipped.append(
                HealthInterval(
                    start_utc=start,
                    end_utc=end,
                    state=interval.state,
                    reason=interval.reason,
                )
            )

    boundaries = {window_start_utc, window_end_utc}
    for interval in clipped:
        boundaries.add(interval.start_utc)
        boundaries.add(interval.end_utc)
    points = sorted(boundaries)

    segments: list[_Segment] = []
    for left, right in zip(points, points[1:], strict=False):
        active = [i for i in clipped if i.start_utc <= left and i.end_utc >= right]
        if not active:
            segment = _Segment(left, right, HealthState.DISCONNECTED, GapReason.UNKNOWN)
        else:
            unhealthy = [i for i in active if i.state is not HealthState.HEALTHY]
            if not unhealthy:
                segment = _Segment(left, right, HealthState.HEALTHY, None)
            else:
                chosen = max(
                    unhealthy,
                    key=lambda i: (_REASON_RANK[_effective_reason(i)], _STATE_RANK[i.state]),
                )
                segment = _Segment(left, right, chosen.state, _effective_reason(chosen))
        if (
            segments
            and segments[-1].state is segment.state
            and segments[-1].reason is segment.reason
        ):
            previous = segments.pop()
            segment = _Segment(previous.start_utc, segment.end_utc, segment.state, segment.reason)
        segments.append(segment)
    return segments


# --------------------------------------------------------------------------- #
# Coverage report (REV-01, REV-17).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UncoveredInterval:
    """One uncovered stretch of the window with its reason code."""

    start_utc: datetime
    end_utc: datetime
    reason: GapReason


@dataclass(frozen=True)
class UncoveredBlock:
    """A maximal continuous non-HEALTHY block (every reason merged) and the reasons inside it."""

    start_utc: datetime
    end_utc: datetime
    length_seconds: Decimal
    reasons: tuple[GapReason, ...]


@dataclass(frozen=True)
class CoverageReport:
    """Runtime coverage of one fixed trial window (REV-01, REV-17).

    Reported, not decided: `coverage_pass` and `ceiling_pass` state whether the ratified
    criterion and the user-ratified ceiling were met; nothing here changes either.
    """

    window_start_utc: datetime
    window_end_utc: datetime
    window_hours: Decimal
    covered_hours: Decimal
    covered_fraction: Decimal
    criterion_min_fraction: Decimal
    coverage_pass: bool
    derived_minimum_covered_hours: Decimal
    derived_minimum_label: str
    uncovered: tuple[UncoveredInterval, ...]
    longest_uncovered_block: UncoveredBlock | None
    ceiling_seconds: int
    ceiling_pass: bool


def _uncovered_from(segments: Sequence[_Segment]) -> tuple[UncoveredInterval, ...]:
    return tuple(
        UncoveredInterval(s.start_utc, s.end_utc, s.reason)
        for s in segments
        if not s.healthy and s.reason is not None
    )


def _longest_block(segments: Sequence[_Segment]) -> UncoveredBlock | None:
    blocks: list[tuple[datetime, datetime, list[GapReason]]] = []
    for segment in segments:
        if segment.healthy or segment.reason is None:
            continue
        if blocks and blocks[-1][1] == segment.start_utc:
            start, _, reasons = blocks[-1]
            if segment.reason not in reasons:
                reasons.append(segment.reason)
            blocks[-1] = (start, segment.end_utc, reasons)
        else:
            blocks.append((segment.start_utc, segment.end_utc, [segment.reason]))
    if not blocks:
        return None
    # The earliest block wins a tie (strict comparison over blocks in time order).
    start, end, reasons = blocks[0]
    for candidate in blocks[1:]:
        if _micros(candidate[1] - candidate[0]) > _micros(end - start):
            start, end, reasons = candidate
    return UncoveredBlock(
        start_utc=start,
        end_utc=end,
        length_seconds=_CTX.divide(Decimal(_micros(end - start)), Decimal(_US_PER_SECOND)),
        reasons=tuple(reasons),
    )


def coverage_report(
    *,
    window_start_utc: datetime,
    window_end_utc: datetime,
    intervals: Sequence[HealthInterval],
    continuous_uncovered_ceiling_seconds: int,
) -> CoverageReport:
    """Compute REV-01 coverage over the whole window.

    `continuous_uncovered_ceiling_seconds` is the user-ratified maximum continuous non-HEALTHY
    block (O-07); it is a required keyword with no default. The report states whether the
    longest block exceeds it (strictly longer than the ceiling fails).
    """
    _require_utc("window_start_utc", window_start_utc)
    _require_utc("window_end_utc", window_end_utc)
    if window_end_utc <= window_start_utc:
        raise ValueError("the coverage window must end after it starts")
    ceiling = _positive_int(
        "continuous_uncovered_ceiling_seconds", continuous_uncovered_ceiling_seconds
    )

    segments = _tile(window_start_utc, window_end_utc, intervals)
    window_us = _micros(window_end_utc - window_start_utc)
    covered_us = sum(_micros(s.end_utc - s.start_utc) for s in segments if s.healthy)

    window_hours = _CTX.divide(Decimal(window_us), Decimal(_US_PER_HOUR))
    covered_hours = _CTX.divide(Decimal(covered_us), Decimal(_US_PER_HOUR))
    covered_fraction = _CTX.divide(Decimal(covered_us), Decimal(window_us))
    # Exact comparison on integers of microseconds: no rounding can flip the verdict.
    coverage_pass = Decimal(covered_us) >= _CTX.multiply(CRITERION_MIN_FRACTION, Decimal(window_us))

    block = _longest_block(segments)
    ceiling_pass = block is None or block.length_seconds <= Decimal(ceiling)

    return CoverageReport(
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        window_hours=window_hours,
        covered_hours=covered_hours,
        covered_fraction=covered_fraction,
        criterion_min_fraction=CRITERION_MIN_FRACTION,
        coverage_pass=coverage_pass,
        derived_minimum_covered_hours=_CTX.multiply(window_hours, CRITERION_MIN_FRACTION),
        derived_minimum_label=DERIVED_MINIMUM_LABEL,
        uncovered=_uncovered_from(segments),
        longest_uncovered_block=block,
        ceiling_seconds=ceiling,
        ceiling_pass=ceiling_pass,
    )
