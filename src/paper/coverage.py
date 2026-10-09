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

import bisect
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal
from enum import StrEnum
from typing import Protocol

from src.paper.freeze import DiffLogEntry, FreezeSkippedEntry
from src.paper.vocabulary import INTERVAL_MS, GapReason, HealthState, RuntimeEventType

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


# --------------------------------------------------------------------------- #
# User-owned thresholds (O-07): required inputs, no default.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HealthThresholds:
    """The numbers the user owns for health and freeze evidence (L-09, O-07).

    Every field is required and positive; there is no default anywhere. The values come only
    from the user-ratified configuration file (plan 16-34); this module only consumes them.
    """

    max_ws_message_silence_seconds: int
    max_closed_bar_lateness_seconds: int
    continuous_uncovered_ceiling_seconds: int
    freeze_tick_grace_seconds: int

    def __post_init__(self) -> None:
        for name in (
            "max_ws_message_silence_seconds",
            "max_closed_bar_lateness_seconds",
            "continuous_uncovered_ceiling_seconds",
            "freeze_tick_grace_seconds",
        ):
            _positive_int(name, getattr(self, name))


# --------------------------------------------------------------------------- #
# Health derivation from the recorded runtime events (REV-01, REV-18).
# --------------------------------------------------------------------------- #


class RuntimeRecordLike(Protocol):
    """The part of a runtime journal record this module reads (plan 16-16 RuntimeRecord).

    Payload keys read (the evidence contract the runtime plans 16-24, 16-26 and 16-29 write):
    - PAPER_BAR_PROCESSED: `occurred_at_utc` is the bar close (open + interval - 1 ms),
      `payload["source"]` is the source tag (only "LIVE_WS" proves a live feed) and
      `payload["tick_time_utc"]` is the time the bar was processed (ISO string or datetime).
    - PAPER_GAP: `payload["expected_close_utc"]` and `payload["reason"]` (a GapReason value).
    - HEALTH_STATE_CHANGED: `payload["state"]` (a HealthState value), optional `"reason"`.
    - RUNTIME_START, RUNTIME_STOP, WS_DISCONNECT, WS_RECONNECT, PAPER_TICK_STATS: the record
      time alone (plus the tick-stats numbers, read by `tick_timing_summary`).
    """

    @property
    def event_type(self) -> RuntimeEventType: ...

    @property
    def epoch_id(self) -> str: ...

    @property
    def symbol(self) -> str | None: ...

    @property
    def interval(self) -> str | None: ...

    @property
    def occurred_at_utc(self) -> datetime: ...

    @property
    def payload(self) -> Mapping[str, object]: ...


# A STOP at the same instant as a START closes the old run before the new one opens.
_EVENT_ORDER: Mapping[RuntimeEventType, int] = {
    RuntimeEventType.RUNTIME_STOP: 0,
    RuntimeEventType.RUNTIME_START: 1,
}

# Reasons that mean the feed was not connected at all; every other reason is a degraded feed.
_DISCONNECTED_REASONS = frozenset(
    {
        GapReason.PROCESS_DOWN,
        GapReason.PLANNED_RESTART,
        GapReason.CRASH,
        GapReason.WS_DISCONNECTED,
        GapReason.WS_RECONNECT_WINDOW,
    }
)


def _state_for(reason: GapReason) -> HealthState:
    return HealthState.DISCONNECTED if reason in _DISCONNECTED_REASONS else HealthState.DEGRADED


def _payload_time(payload: Mapping[str, object], key: str) -> datetime | None:
    """A UTC-aware datetime from a payload value (datetime or ISO string), None if absent."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"payload[{key!r}] is not an ISO-8601 time: {value!r}") from exc
    else:
        raise ValueError(f"payload[{key!r}] must be a datetime or an ISO string")
    _require_utc(f"payload[{key!r}]", parsed)
    return parsed


def _payload_reason(payload: Mapping[str, object]) -> GapReason | None:
    value = payload.get("reason")
    if value is None:
        return None
    try:
        return GapReason(str(value))
    except ValueError:
        return GapReason.UNKNOWN


def _record_sort_key(record: RuntimeRecordLike) -> tuple[datetime, int, str, str, str, str]:
    return (
        record.occurred_at_utc,
        _EVENT_ORDER.get(record.event_type, 2),
        record.event_type.value,
        record.symbol or "",
        record.interval or "",
        json.dumps(dict(record.payload), sort_keys=True, default=str),
    )


@dataclass(frozen=True)
class _Run:
    """One uninterrupted stretch of the runtime process."""

    start: datetime
    end: datetime | None  # None: still running at the end of the evidence
    ended_by: str | None  # "STOP", "CRASH" or None


def _last_evidence(
    ordered: Sequence[RuntimeRecordLike], start: datetime, until: datetime
) -> datetime:
    last = start
    for record in ordered:
        if start <= record.occurred_at_utc < until:
            last = max(last, record.occurred_at_utc)
        tick = _payload_time(record.payload, "tick_time_utc")
        if tick is not None and start <= tick < until:
            last = max(last, tick)
    return last


def _build_runs(ordered: Sequence[RuntimeRecordLike]) -> list[_Run]:
    """Runs from RUNTIME_START and RUNTIME_STOP records; a START with no STOP is a crash.

    A crashed run ends at the last evidence it left (the latest record or processing time
    before the next START), never later: the time after it is unobserved.
    """
    runs: list[_Run] = []
    current: datetime | None = None
    for record in ordered:
        if record.event_type is RuntimeEventType.RUNTIME_START:
            if current is not None:
                last = _last_evidence(ordered, current, record.occurred_at_utc)
                runs.append(_Run(current, last, "CRASH"))
            current = record.occurred_at_utc
        elif record.event_type is RuntimeEventType.RUNTIME_STOP and current is not None:
            runs.append(_Run(current, record.occurred_at_utc, "STOP"))
            current = None
    if current is not None:
        runs.append(_Run(current, None, None))
    return runs


def _expected_closes(interval: str, start_utc: datetime, end_utc: datetime) -> list[datetime]:
    """Close times (open + interval - 1 ms, on the epoch grid) in [start_utc, end_utc)."""
    step = INTERVAL_MS[interval]
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    start_ms = _micros(start_utc - epoch) // 1000
    k = -((-(start_ms + 1)) // step)  # ceil((start_ms + 1) / step)
    closes: list[datetime] = []
    while True:
        close = epoch + timedelta(milliseconds=k * step - 1)
        if close >= end_utc:
            return closes
        closes.append(close)
        k += 1


def derive_health_intervals(
    records: Sequence[RuntimeRecordLike],
    *,
    epoch_id: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    intervals_expected: Sequence[tuple[str, str]],
    thresholds: HealthThresholds,
) -> tuple[HealthInterval, ...]:
    """Turn the judged epoch's recorded events into health intervals tiling the window.

    `intervals_expected` lists the (symbol, interval) pairs whose closed bars are expected.

    HEALTHY only while all of these hold: the runtime process is up; the feed is connected (no
    WS_DISCONNECT without a later WS_RECONNECT); a feed message was seen since the process
    started and the latest one is no older than `max_ws_message_silence_seconds`; every
    expected closed bar of every expected pair arrived live within
    `max_closed_bar_lateness_seconds` of its close; and the runtime did not itself declare a
    non-HEALTHY state (HEALTH_STATE_CHANGED). Anything else is DEGRADED or DISCONNECTED with a
    reason code. Time the records say nothing about is never HEALTHY.

    Feed-message evidence is what the runtime journals: a live closed bar (its processing
    time), a PAPER_TICK_STATS record or a WS_RECONNECT record. A silence limit shorter than the
    closed-bar cadence therefore leaves time DEGRADED (visible in the report, never hidden).

    Records whose `epoch_id` differs from `epoch_id` are ignored (REV-18: an earlier epoch is
    auxiliary evidence). The input is not mutated; the result does not depend on input order.
    """
    _require_utc("window_start_utc", window_start_utc)
    _require_utc("window_end_utc", window_end_utc)
    if window_end_utc <= window_start_utc:
        raise ValueError("the health window must end after it starts")
    for symbol, interval in intervals_expected:
        if interval not in INTERVAL_MS:
            raise ValueError(f"unknown interval {interval!r} for {symbol!r}")

    mine = [r for r in records if r.epoch_id == epoch_id]
    for record in mine:
        _require_utc("occurred_at_utc", record.occurred_at_utc)
    ordered = sorted(mine, key=_record_sort_key)

    silence = timedelta(seconds=thresholds.max_ws_message_silence_seconds)
    lateness = timedelta(seconds=thresholds.max_closed_bar_lateness_seconds)

    bad: list[HealthInterval] = []

    def add(start: datetime, end: datetime, state: HealthState, reason: GapReason) -> None:
        if end > start:
            bad.append(HealthInterval(start_utc=start, end_utc=end, state=state, reason=reason))

    # 1. Process lifecycle.
    runs = _build_runs(ordered)
    if not runs:
        add(window_start_utc, window_end_utc, HealthState.DISCONNECTED, GapReason.PROCESS_DOWN)
    else:
        add(window_start_utc, runs[0].start, HealthState.DISCONNECTED, GapReason.PROCESS_DOWN)
        for earlier, later in zip(runs, runs[1:], strict=False):
            if earlier.end is None:  # only the last run can be open
                raise ValueError("internal error: an open run is followed by another run")
            restart = GapReason.PLANNED_RESTART if earlier.ended_by == "STOP" else GapReason.CRASH
            add(earlier.end, later.start, HealthState.DISCONNECTED, restart)
        last_run = runs[-1]
        if last_run.end is not None:
            add(last_run.end, window_end_utc, HealthState.DISCONNECTED, GapReason.PROCESS_DOWN)

    # 2. Connection: WS_DISCONNECT until WS_RECONNECT (or until the process boundary).
    dropped_since: datetime | None = None
    for record in ordered:
        kind = record.event_type
        if kind is RuntimeEventType.WS_DISCONNECT:
            if dropped_since is None:
                dropped_since = record.occurred_at_utc
        elif kind in (
            RuntimeEventType.WS_RECONNECT,
            RuntimeEventType.RUNTIME_START,
            RuntimeEventType.RUNTIME_STOP,
        ):
            if dropped_since is not None:
                add(
                    dropped_since,
                    record.occurred_at_utc,
                    HealthState.DISCONNECTED,
                    GapReason.WS_DISCONNECTED,
                )
                dropped_since = None
    if dropped_since is not None:
        add(dropped_since, window_end_utc, HealthState.DISCONNECTED, GapReason.WS_DISCONNECTED)

    # 3. Live arrivals per bar, gap records, feed-message evidence, process boundaries.
    arrival: dict[tuple[str, str, datetime], datetime] = {}
    gap_reason: dict[tuple[str, str, datetime], GapReason] = {}
    messages: list[datetime] = []
    boundaries: list[datetime] = []
    for record in ordered:
        kind = record.event_type
        if kind is RuntimeEventType.PAPER_BAR_PROCESSED:
            tick = _payload_time(record.payload, "tick_time_utc")
            if record.payload.get("source") == "LIVE_WS" and tick is not None:
                if record.symbol is None or record.interval is None:
                    raise ValueError("PAPER_BAR_PROCESSED needs a symbol and an interval")
                key = (record.symbol, record.interval, record.occurred_at_utc)
                arrival[key] = min(tick, arrival.get(key, tick))
                messages.append(tick)
        elif kind is RuntimeEventType.PAPER_TICK_STATS:
            messages.append(record.occurred_at_utc)
        elif kind is RuntimeEventType.WS_RECONNECT:
            messages.append(record.occurred_at_utc)
            boundaries.append(record.occurred_at_utc)
        elif kind in (RuntimeEventType.RUNTIME_START, RuntimeEventType.RUNTIME_STOP):
            boundaries.append(record.occurred_at_utc)
        elif kind is RuntimeEventType.PAPER_GAP:
            expected_close = _payload_time(record.payload, "expected_close_utc")
            if expected_close is None or record.symbol is None or record.interval is None:
                raise ValueError("PAPER_GAP needs symbol, interval and payload expected_close_utc")
            gap_reason[(record.symbol, record.interval, expected_close)] = (
                _payload_reason(record.payload) or GapReason.UNKNOWN
            )
    messages.sort()
    boundaries.sort()

    # 4. Silence: per run, the wait for the first message and every gap above the limit.
    for run in runs:
        run_end = run.end if run.end is not None else window_end_utc
        run_messages = [m for m in messages if m >= run.start and (run.end is None or m <= run.end)]
        if not run_messages:
            add(run.start, run_end, HealthState.DISCONNECTED, GapReason.WS_RECONNECT_WINDOW)
            continue
        add(run.start, run_messages[0], HealthState.DISCONNECTED, GapReason.WS_RECONNECT_WINDOW)
        for earlier_msg, later_msg in zip(run_messages, run_messages[1:], strict=False):
            add(earlier_msg + silence, later_msg, HealthState.DEGRADED, GapReason.UNKNOWN)
        add(run_messages[-1] + silence, run_end, HealthState.DEGRADED, GapReason.UNKNOWN)

    # 5. Expected closed bars: on time, late, or never arrived (a recorded gap never arrived).
    arrivals_by_pair: dict[tuple[str, str], list[tuple[datetime, datetime]]] = {}
    for (symbol, interval, close), tick in arrival.items():
        arrivals_by_pair.setdefault((symbol, interval), []).append((close, tick))
    slots: set[tuple[str, str, datetime]] = set(gap_reason)
    for symbol, interval in intervals_expected:
        for close in _expected_closes(interval, window_start_utc, window_end_utc):
            slots.add((symbol, interval, close))
    for symbol, interval, close in sorted(slots):
        recorded_gap = gap_reason.get((symbol, interval, close))
        arrived = arrival.get((symbol, interval, close))
        if recorded_gap is None and arrived is not None:
            if arrived - close > lateness:
                add(close + lateness, arrived, HealthState.DEGRADED, GapReason.UNKNOWN)
            continue
        # Never arrived live (or a gap was recorded): not healthy from the close until the
        # feed is seen again - a later bar of the pair, a reconnect, a process boundary, or the
        # end of the window - and for at least the lateness limit.
        resolved = [window_end_utc]
        resolved.extend(
            tick for other, tick in arrivals_by_pair.get((symbol, interval), []) if other > close
        )
        if arrived is not None:
            resolved.append(arrived)
        index = bisect.bisect_left(boundaries, close)
        if index < len(boundaries):
            resolved.append(boundaries[index])
        reason = recorded_gap or GapReason.UNKNOWN
        add(close, max(min(resolved), close + lateness), _state_for(reason), reason)

    # 6. States the runtime declared itself (HEALTH_STATE_CHANGED).
    declared = [r for r in ordered if r.event_type is RuntimeEventType.HEALTH_STATE_CHANGED]
    lifecycle_times = [
        r.occurred_at_utc
        for r in ordered
        if r.event_type in (RuntimeEventType.RUNTIME_START, RuntimeEventType.RUNTIME_STOP)
    ]
    for position, record in enumerate(declared):
        raw_state = record.payload.get("state")
        try:
            state = HealthState(str(raw_state))
        except ValueError as exc:
            raise ValueError(f"HEALTH_STATE_CHANGED has an unknown state {raw_state!r}") from exc
        if state is HealthState.HEALTHY:
            continue
        end = window_end_utc
        if position + 1 < len(declared):
            end = min(end, declared[position + 1].occurred_at_utc)
        index = bisect.bisect_right(lifecycle_times, record.occurred_at_utc)
        if index < len(lifecycle_times):
            end = min(end, lifecycle_times[index])
        default = (
            GapReason.WS_RECONNECT_WINDOW
            if state is HealthState.DISCONNECTED
            else GapReason.UNKNOWN
        )
        add(record.occurred_at_utc, end, state, _payload_reason(record.payload) or default)

    base = HealthInterval(window_start_utc, window_end_utc, HealthState.HEALTHY, None)
    segments = _tile(window_start_utc, window_end_utc, [base, *bad])
    return tuple(HealthInterval(s.start_utc, s.end_utc, s.state, s.reason) for s in segments)


# --------------------------------------------------------------------------- #
# Freeze-tick continuity (REV-02, REV-18): expected slots, EVIDENCE_GAP, segments.
# --------------------------------------------------------------------------- #

SLOT_INTERVAL_SECONDS = 3600  # the freeze workflow is hourly; one slot per cron minute per hour
RESTART_RULE = "qualifying trial restarts with a new epoch pin (D065 item 4)"
_HOURLY_CRON = re.compile(r"([0-9]|[1-5][0-9]) \* \* \* \*")
_SLOT_STEP = timedelta(seconds=SLOT_INTERVAL_SECONDS)


class EvidenceGapReason(StrEnum):
    """Why an expected scheduled freeze slot has no valid CLEAN evidence."""

    NO_RUN_FOUND = "NO_RUN_FOUND"
    RUN_WITHOUT_LINE = "RUN_WITHOUT_LINE"
    RUN_LATE_BEYOND_GRACE = "RUN_LATE_BEYOND_GRACE"
    INVALID_LINE = "INVALID_LINE"
    SCHEDULE_MISMATCH = "SCHEDULE_MISMATCH"


# Which reason is reported when several runs are assigned to one unsatisfied slot.
_GAP_PRECEDENCE: tuple[EvidenceGapReason, ...] = (
    EvidenceGapReason.INVALID_LINE,
    EvidenceGapReason.SCHEDULE_MISMATCH,
    EvidenceGapReason.RUN_WITHOUT_LINE,
    EvidenceGapReason.RUN_LATE_BEYOND_GRACE,
)


@dataclass(frozen=True)
class EvidenceGap:
    """An expected scheduled freeze slot without valid CLEAN evidence (never CLEAN)."""

    slot_utc: datetime
    schedule: str
    reason: EvidenceGapReason
    detected_at_utc: datetime
    run_id: str | None

    def __post_init__(self) -> None:
        _require_utc("slot_utc", self.slot_utc)
        _require_utc("detected_at_utc", self.detected_at_utc)


@dataclass(frozen=True)
class GithubRun:
    """One workflow run from the exported GitHub run list (REST workflow runs, research S1)."""

    run_id: str
    event: str
    status: str
    conclusion: str | None
    created_at_utc: datetime
    run_started_at_utc: datetime | None
    run_attempt: int
    head_sha: str

    def __post_init__(self) -> None:
        _require_utc("created_at_utc", self.created_at_utc)
        if self.run_started_at_utc is not None:
            _require_utc("run_started_at_utc", self.run_started_at_utc)


_LINE_OUTCOMES = frozenset({"clean", "REGISTRY_DIFF", "SKIPPED"})


@dataclass(frozen=True)
class FreezeLine:
    """A freeze-check log line reduced to what the reconciler reads.

    `outcome` is "clean", "REGISTRY_DIFF" or "SKIPPED" for a valid line and "INVALID" for one
    that could not be read; `checked_at_utc` is None when not even the time could be read.
    """

    checked_at_utc: datetime | None
    outcome: str
    run_metadata: Mapping[str, str] | None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.checked_at_utc is not None:
            _require_utc("checked_at_utc", self.checked_at_utc)

    @property
    def run_id(self) -> str | None:
        return None if self.run_metadata is None else self.run_metadata.get("run_id")


def _normalise_line(line: DiffLogEntry | FreezeSkippedEntry | FreezeLine) -> FreezeLine:
    if isinstance(line, FreezeLine):
        return line
    if isinstance(line, DiffLogEntry):
        return FreezeLine(line.checked_at_utc, line.outcome, line.run_metadata)
    if isinstance(line, FreezeSkippedEntry):
        return FreezeLine(line.checked_at_utc, "SKIPPED", line.run_metadata, line.reason)
    raise TypeError(f"unsupported freeze log line type {type(line).__name__}")


def parse_freeze_log(text: str) -> tuple[FreezeLine, ...]:
    """Parse the JSONL text of `registry_diff.jsonl`; a bad line becomes an INVALID FreezeLine.

    Nothing is dropped silently: an unreadable line is returned (with whatever time and run
    metadata could still be read) so the reconciler can count it or tie it to its run.
    """
    parsed: list[FreezeLine] = []
    for raw in text.splitlines():
        if raw.strip() == "":
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            parsed.append(FreezeLine(None, "INVALID", None, "not valid JSON"))
            continue
        if not isinstance(data, dict):
            parsed.append(FreezeLine(None, "INVALID", None, "not a JSON object"))
            continue
        try:
            checked = _payload_time(data, "checked_at_utc")
        except ValueError:
            checked = None
        metadata = data.get("run_metadata")
        run_metadata: dict[str, str] | None = None
        if isinstance(metadata, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in metadata.items()
        ):
            run_metadata = dict(metadata)
        outcome = data.get("outcome")
        if isinstance(outcome, str) and outcome in _LINE_OUTCOMES and checked is not None:
            parsed.append(FreezeLine(checked, outcome, run_metadata))
        else:
            parsed.append(FreezeLine(checked, "INVALID", run_metadata, "unreadable line"))
    return tuple(parsed)


def parse_github_runs(text: str) -> tuple[GithubRun, ...]:
    """Parse the exported run list: a JSON array of runs or an object with `workflow_runs`."""
    data = json.loads(text)
    items = data.get("workflow_runs") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("expected a JSON array of runs or an object with a workflow_runs array")
    runs: list[GithubRun] = []
    for item in items:
        created = _payload_time(item, "created_at")
        if created is None:
            raise ValueError("a workflow run has no created_at")
        conclusion = item.get("conclusion")
        runs.append(
            GithubRun(
                run_id=str(item["id"]),
                event=str(item["event"]),
                status=str(item.get("status", "")),
                conclusion=None if conclusion is None else str(conclusion),
                created_at_utc=created,
                run_started_at_utc=_payload_time(item, "run_started_at"),
                run_attempt=int(item.get("run_attempt", 1)),
                head_sha=str(item.get("head_sha", "")),
            )
        )
    return tuple(runs)


def _cron_minute(cron: str) -> int:
    match = _HOURLY_CRON.fullmatch(cron) if isinstance(cron, str) else None
    if match is None:
        raise ValueError(f"cron must be the hourly form 'M * * * *' with M from 0 to 59: {cron!r}")
    return int(match.group(1))


def expected_slots(pin_utc: datetime, window_end_utc: datetime, cron: str) -> tuple[datetime, ...]:
    """Every hourly slot of `cron` strictly after the pin and not after the window end.

    Only the hourly form `M * * * *` is understood; anything else raises (fail closed rather
    than misread a schedule). The grid follows the cron minute and nothing else (checkpoint
    Q-Q of plan 16-30 may move the minute; every slot is treated identically).
    """
    minute = _cron_minute(cron)
    _require_utc("pin_utc", pin_utc)
    _require_utc("window_end_utc", window_end_utc)
    pin = pin_utc.astimezone(UTC)
    slot = pin.replace(minute=minute, second=0, microsecond=0)
    if slot <= pin:
        slot += _SLOT_STEP
    slots: list[datetime] = []
    while slot <= window_end_utc:
        slots.append(slot)
        slot += _SLOT_STEP
    return tuple(slots)


def _latest_slot_not_after(moment: datetime, minute: int) -> datetime:
    slot = moment.astimezone(UTC).replace(minute=minute, second=0, microsecond=0)
    if slot > moment:
        slot -= _SLOT_STEP
    return slot


@dataclass(frozen=True)
class FreezeBreak:
    """A non-CLEAN line after the pin (REGISTRY_DIFF, SKIPPED or unreadable): ends continuity."""

    at_utc: datetime
    outcome: str
    run_id: str | None


@dataclass(frozen=True)
class FreezeSegment:
    """A maximal run of consecutive satisfied slots; the first one starts at the pin."""

    start_utc: datetime
    end_utc: datetime
    slot_count: int


@dataclass(frozen=True)
class FreezeSlotResult:
    """The verdict for one expected slot."""

    slot_utc: datetime
    status: str  # "SATISFIED", "EVIDENCE_GAP" or "BROKEN_BY_LINE"
    run_id: str | None


@dataclass(frozen=True)
class AuxiliaryEvidence:
    """Lines and runs at or before the epoch pin: kept untouched, never counted (REV-18).

    Evidence of an earlier epoch (one ended by an EVIDENCE_GAP or replaced by a new pin) stays
    readable and reproducible with its own pin, but it cannot satisfy a slot of the new trial.
    The tuples hold the caller's own objects, in input order.
    """

    lines: tuple[DiffLogEntry | FreezeSkippedEntry | FreezeLine, ...]
    runs: tuple[GithubRun, ...]
    line_count: int
    run_count: int
    first_utc: datetime | None
    last_utc: datetime | None


@dataclass(frozen=True)
class FreezeEvidenceReport:
    """Freeze-tick continuity from the pin to the window end (REV-02, REV-18).

    Freeze integrity only: it says nothing about whether the host ran or the feed was healthy
    (that is `CoverageReport`, a separate evidence set).
    """

    pin_utc: datetime
    window_end_utc: datetime
    cron: str
    grace_seconds: int
    slots: tuple[datetime, ...]
    satisfied_slots: tuple[datetime, ...]
    slot_results: tuple[FreezeSlotResult, ...]
    gaps: tuple[EvidenceGap, ...]
    breaks: tuple[FreezeBreak, ...]
    segments: tuple[FreezeSegment, ...]
    unplaced_line_count: int
    auxiliary: AuxiliaryEvidence
    qualifying_from_pin: bool
    statement: str


_SATISFIED = "SATISFIED"
_GAP = "EVIDENCE_GAP"
_BROKEN = "BROKEN_BY_LINE"


def _line_verdict(line: FreezeLine, cron: str) -> str:
    """SATISFIED, BROKEN or the gap reason name for one line of the slot's run."""
    if line.outcome in ("REGISTRY_DIFF", "SKIPPED"):
        return _BROKEN
    if line.outcome != "clean":
        return EvidenceGapReason.INVALID_LINE.value
    meta = line.run_metadata or {}
    if meta.get("event_name") != "schedule":
        return EvidenceGapReason.INVALID_LINE.value
    if meta.get("schedule") != cron:
        return EvidenceGapReason.SCHEDULE_MISMATCH.value
    if meta.get("run_attempt", "1") != "1":
        # A re-run happens later than the slot; its line is not the tick evidence of the slot.
        return EvidenceGapReason.INVALID_LINE.value
    return _SATISFIED


def _run_verdict(
    run: GithubRun, slot: datetime, cron: str, grace: timedelta, lines: Sequence[FreezeLine]
) -> str:
    if run.created_at_utc - slot > grace:
        return EvidenceGapReason.RUN_LATE_BEYOND_GRACE.value
    if not lines:
        return EvidenceGapReason.RUN_WITHOUT_LINE.value
    verdicts = {_line_verdict(line, cron) for line in lines}
    for verdict in (
        _SATISFIED,
        _BROKEN,
        EvidenceGapReason.SCHEDULE_MISMATCH.value,
        EvidenceGapReason.INVALID_LINE.value,
    ):
        if verdict in verdicts:
            return verdict
    return EvidenceGapReason.INVALID_LINE.value


def freeze_evidence_report(
    *,
    pin_utc: datetime,
    window_end_utc: datetime,
    cron: str,
    lines: Sequence[DiffLogEntry | FreezeSkippedEntry | FreezeLine],
    runs: Sequence[GithubRun],
    grace_seconds: int,
    detected_at_utc: datetime,
) -> FreezeEvidenceReport:
    """Reconcile the expected slot grid with the freeze-check lines and the exported run list.

    A slot is satisfied only by a CLEAN line of a schedule-event run assigned to it (the run is
    assigned to the latest slot not after its `created_at`, so a run serves exactly one slot),
    created no later than `grace_seconds` after the slot, whose recorded cron string equals
    `cron`. Anything else is an `EvidenceGap` (never CLEAN, never interpolated, never filled
    from a neighbouring tick); the qualifying trial then restarts with a new epoch pin (REV-02,
    REV-18). A non-CLEAN line after the pin (REGISTRY_DIFF, SKIPPED, unreadable) also ends the
    continuity window. Lines and runs at or before the pin are not evaluated.

    `grace_seconds` is the user's number (no default); it bounds only how late a valid scheduled
    run may start. The function returns records; it never writes `registry_diff.jsonl`.
    """
    slots = expected_slots(pin_utc, window_end_utc, cron)
    _require_utc("detected_at_utc", detected_at_utc)
    if isinstance(grace_seconds, bool) or not isinstance(grace_seconds, int) or grace_seconds < 0:
        raise ValueError(f"grace_seconds must be a non-negative integer, got {grace_seconds!r}")
    if grace_seconds >= SLOT_INTERVAL_SECONDS:
        raise ValueError(
            f"grace_seconds {grace_seconds} is not below the slot interval "
            f"({SLOT_INTERVAL_SECONDS} s): one run could stand for two slots (REV-02, REV-18)"
        )
    grace = timedelta(seconds=grace_seconds)
    minute = _cron_minute(cron)
    slot_set = set(slots)

    normalised = [_normalise_line(line) for line in lines]
    dated = [n for n in normalised if n.checked_at_utc is not None]
    unplaced = len(normalised) - len(dated)
    auxiliary = _auxiliary(pin_utc, lines, normalised, runs)
    lines_by_run: dict[str, list[FreezeLine]] = {}
    for line in normalised:
        if line.run_id is not None:
            lines_by_run.setdefault(line.run_id, []).append(line)

    assigned: dict[datetime, list[GithubRun]] = {}
    for run in sorted(runs, key=lambda r: (r.created_at_utc, r.run_id)):
        if run.event != "schedule" or run.created_at_utc <= pin_utc:
            continue
        slot = _latest_slot_not_after(run.created_at_utc, minute)
        if slot in slot_set:
            assigned.setdefault(slot, []).append(run)

    results: list[FreezeSlotResult] = []
    gaps: list[EvidenceGap] = []
    for slot in slots:
        slot_runs = assigned.get(slot, [])
        verdicts = [
            (run, _run_verdict(run, slot, cron, grace, lines_by_run.get(run.run_id, [])))
            for run in slot_runs
        ]
        satisfied = next((run for run, verdict in verdicts if verdict == _SATISFIED), None)
        if satisfied is not None:
            results.append(FreezeSlotResult(slot, _SATISFIED, satisfied.run_id))
        elif any(verdict == _BROKEN for _, verdict in verdicts):
            broken = next(run for run, verdict in verdicts if verdict == _BROKEN)
            results.append(FreezeSlotResult(slot, _BROKEN, broken.run_id))
        else:
            reason = EvidenceGapReason.NO_RUN_FOUND
            run_id: str | None = None
            for candidate in _GAP_PRECEDENCE:
                match = next((run for run, verdict in verdicts if verdict == candidate.value), None)
                if match is not None:
                    reason, run_id = candidate, match.run_id
                    break
            gaps.append(EvidenceGap(slot, cron, reason, detected_at_utc, run_id))
            results.append(FreezeSlotResult(slot, _GAP, run_id))

    breaks = sorted(
        (
            FreezeBreak(n.checked_at_utc, n.outcome, n.run_id)
            for n in dated
            if n.checked_at_utc is not None
            and n.outcome != "clean"
            and pin_utc < n.checked_at_utc <= window_end_utc
        ),
        key=lambda b: (b.at_utc, b.outcome, b.run_id or ""),
    )

    segments = _segments(pin_utc, slots, {r.slot_utc: r.status for r in results}, breaks)
    satisfied_slots = tuple(r.slot_utc for r in results if r.status == _SATISFIED)
    qualifying = bool(slots) and len(satisfied_slots) == len(slots) and not breaks and unplaced == 0
    return FreezeEvidenceReport(
        pin_utc=pin_utc,
        window_end_utc=window_end_utc,
        cron=cron,
        grace_seconds=grace_seconds,
        slots=slots,
        satisfied_slots=satisfied_slots,
        slot_results=tuple(results),
        gaps=tuple(gaps),
        breaks=tuple(breaks),
        segments=segments,
        unplaced_line_count=unplaced,
        auxiliary=auxiliary,
        qualifying_from_pin=qualifying,
        statement=_freeze_statement(slots, gaps, breaks, unplaced, auxiliary),
    )


def _auxiliary(
    pin_utc: datetime,
    lines: Sequence[DiffLogEntry | FreezeSkippedEntry | FreezeLine],
    normalised: Sequence[FreezeLine],
    runs: Sequence[GithubRun],
) -> AuxiliaryEvidence:
    """Everything at or before the pin, as the caller's own objects (never copied or edited)."""
    kept_lines: list[DiffLogEntry | FreezeSkippedEntry | FreezeLine] = []
    moments: list[datetime] = []
    for original, line in zip(lines, normalised, strict=True):
        if line.checked_at_utc is not None and line.checked_at_utc <= pin_utc:
            kept_lines.append(original)
            moments.append(line.checked_at_utc)
    kept_runs = [run for run in runs if run.created_at_utc <= pin_utc]
    moments.extend(run.created_at_utc for run in kept_runs)
    return AuxiliaryEvidence(
        lines=tuple(kept_lines),
        runs=tuple(kept_runs),
        line_count=len(kept_lines),
        run_count=len(kept_runs),
        first_utc=min(moments) if moments else None,
        last_utc=max(moments) if moments else None,
    )


def _segments(
    pin_utc: datetime,
    slots: Sequence[datetime],
    status: Mapping[datetime, str],
    breaks: Sequence[FreezeBreak],
) -> tuple[FreezeSegment, ...]:
    """Maximal runs of consecutive satisfied slots, split by any gap or non-CLEAN line."""
    events = [(b.at_utc, 0) for b in breaks] + [(slot, 1) for slot in slots]
    events.sort()
    segments: list[FreezeSegment] = []
    current: list[datetime] = []

    def flush() -> None:
        if current:
            start = pin_utc if current[0] == slots[0] else current[0]
            segments.append(FreezeSegment(start, current[-1], len(current)))
            current.clear()

    for moment, kind in events:
        if kind == 1 and status[moment] == _SATISFIED:
            current.append(moment)
        else:
            flush()
    flush()
    return tuple(segments)


def _freeze_statement(
    slots: Sequence[datetime],
    gaps: Sequence[EvidenceGap],
    breaks: Sequence[FreezeBreak],
    unplaced: int,
    auxiliary: AuxiliaryEvidence,
) -> str:
    base = (
        "Freeze integrity evidence only (registry immutability from the epoch pin); "
        "runtime health is a separate report."
    )
    problems: list[str] = []
    if gaps:
        problems.append(
            f"{len(gaps)} EVIDENCE_GAP slot(s), first at {gaps[0].slot_utc.isoformat()}: "
            "a missing, late, failed, manual or mismatched tick is never CLEAN and is never "
            "interpolated or filled from neighbouring ticks."
        )
    if breaks:
        problems.append(
            f"{len(breaks)} non-CLEAN line(s) after the pin (REGISTRY_DIFF, SKIPPED or "
            "unreadable) end the continuity window."
        )
    if unplaced:
        problems.append(f"{unplaced} unreadable line(s) cannot be placed in time.")
    note = ""
    if auxiliary.line_count or auxiliary.run_count:
        note = (
            " Note: earlier epoch evidence is auxiliary and cannot complete the freeze "
            f"criterion of the new trial ({auxiliary.line_count} line(s) and "
            f"{auxiliary.run_count} run(s) at or before the pin, kept untouched)."
        )
    if problems:
        return f"{base} {' '.join(problems)} The {RESTART_RULE}.{note}"
    if not slots:
        empty = "No scheduled slot lies between the pin and the window end: not qualifying."
        return f"{base} {empty}{note}"
    return (
        f"{base} Every expected scheduled slot from the pin to the window end is satisfied by a "
        f"CLEAN line of a schedule run.{note}"
    )


# --------------------------------------------------------------------------- #
# Report-only tick timing summary (research A10 and P20).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TickTimingSummary:
    """What the runtime measured about its own ticks. An observation, never a criterion.

    It makes two assumptions visible: that a tick finishes well inside a bar interval (A10) and
    that a host clock running behind drops closed bars (P20, `dropped_by_reason`). It is compared
    with no limit anywhere and feeds no decision.
    """

    tick_count: int
    duration_ms_min: int | None
    duration_ms_median: int | None
    duration_ms_max: int | None
    queue_depth_max: int | None
    dropped_total: int
    dropped_by_reason: tuple[tuple[str, int], ...]
    first_tick_utc: datetime | None
    last_tick_utc: datetime | None


def _tick_counter(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"PAPER_TICK_STATS payload[{key!r}] must be a non-negative integer, got {value!r}"
        )
    return value


def _tick_dropped_by_reason(payload: Mapping[str, object]) -> Mapping[str, int]:
    raw = payload.get("dropped_by_reason")
    if not isinstance(raw, Mapping):
        raise ValueError("PAPER_TICK_STATS payload['dropped_by_reason'] must be a mapping")
    return {str(reason): _tick_counter(raw, str(reason)) for reason in raw}


def tick_timing_summary(records: Iterable[RuntimeRecordLike]) -> TickTimingSummary:
    """Summarise the PAPER_TICK_STATS records: durations, queue depth, drops by reason.

    Integers only. The median is the lower middle value. Records of other event types are
    ignored; with no tick record `tick_count` is 0 and the optional fields are None.
    """
    ticks = [r for r in records if r.event_type is RuntimeEventType.PAPER_TICK_STATS]
    for tick in ticks:
        _require_utc("occurred_at_utc", tick.occurred_at_utc)
    durations = sorted(_tick_counter(t.payload, "duration_ms") for t in ticks)
    depths = [_tick_counter(t.payload, "queue_depth_before") for t in ticks]
    dropped_total = sum(_tick_counter(t.payload, "dropped_total") for t in ticks)
    by_reason: dict[str, int] = {}
    for tick in ticks:
        for reason, count in _tick_dropped_by_reason(tick.payload).items():
            by_reason[reason] = by_reason.get(reason, 0) + count
    times = [t.occurred_at_utc for t in ticks]
    return TickTimingSummary(
        tick_count=len(ticks),
        duration_ms_min=durations[0] if durations else None,
        duration_ms_median=durations[(len(durations) - 1) // 2] if durations else None,
        duration_ms_max=durations[-1] if durations else None,
        queue_depth_max=max(depths) if depths else None,
        dropped_total=dropped_total,
        dropped_by_reason=tuple(sorted(by_reason.items())),
        first_tick_utc=min(times) if times else None,
        last_tick_utc=max(times) if times else None,
    )
