"""Trial exit-criteria evaluator (Phase 16, plan 16-25; D-23, L-04, REV-01, REV-02, REV-17, REV-18).

One deterministic judge for the paper trial soak. It reads ONE verified evidence bundle
(`src/paper/evidence_bundle.py`) and prints PASS or FAIL per ratified criterion together with the
evidence it read. It evaluates; it never changes a threshold, never fills a missing tick, never
edits or drops an input, and reads no clock (every time comes from the bundle).

Ratified values (DECISION labels, chosen for operational reasons and never derived from backtest or
research results): 14 calendar days, runtime coverage of at least 95 percent of the fixed window,
parity tolerance zero (D061 item D, 2026-10-07). 336 h x 0.95 = 319.2 h is DERIVED, not a
threshold (D065 item 3, REV-17). Numbers the user owns (health silence and lateness, the
continuous-uncovered ceiling, the freeze-tick grace) are required inputs with no default: they come
from the ratified runtime configuration (O-07, L-09).

Two evidence sets stay separate (REV-02): freeze integrity (registry, epoch, parameter hash, the
scheduled tick continuity) and runtime health (feed, coverage). A criterion of one group never reads
the other group's inputs. Evidence of an earlier epoch (REV-18) is auxiliary: it is listed with its
counts, never satisfies a slot or an interval of the judged epoch, and is never edited.

The proof class of a bundle follows from its manifest source only (fixture is FAKE, pg is
REAL_SOAK): there is no parameter that sets it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from src.paper.bars import CONTEXT_INTERVAL, SETUP_INTERVAL
from src.paper.coverage import (
    RESTART_RULE,
    CoverageReport,
    FreezeEvidenceReport,
    HealthInterval,
    HealthThresholds,
    coverage_report,
    derive_health_intervals,
    freeze_evidence_report,
    tick_timing_summary,
)
from src.paper.evidence_bundle import DiffRecord, EvidenceBundle
from src.paper.runtime_state import RuntimeRecord
from src.paper.vocabulary import HealthState

# DECISION D061 item D, 2026-10-07: trial soak length, in calendar days.
TRIAL_CALENDAR_DAYS = 14
# DECISION D061 item D, 2026-10-07: runtime coverage of at least this fraction of the fixed window.
MIN_COVERAGE_FRACTION = Decimal("0.95")
# DECISION D061 item D, 2026-10-07: parity tolerance for the decision logic is zero.
PARITY_TOLERANCE = 0

# The decision text the constants above are witnessed against (a test reads docs/DECISIONS.md).
DECISION_LABEL = "DECISION D061 item D, 2026-10-07"

# Intervals whose closed bars the runtime processes: 1h evaluated, 4h context.
EVALUATED_INTERVALS: tuple[str, ...] = (SETUP_INTERVAL, CONTEXT_INTERVAL)

TIME_OF_DAY_LABEL = "time of day: reported, not a pass condition (D061 item D)"
AUXILIARY_HEADING = "auxiliary evidence (not qualifying)"
OBSERVATIONS_HEADING = "observations (not criteria)"

_US = timedelta(microseconds=1)
_US_PER_HOUR = 3_600_000_000
_QUANT = Decimal("0.001")


class ProofClass(StrEnum):
    """Where a piece of evidence came from; only the REAL_* classes can close a requirement."""

    FAKE = "FAKE"
    CODE = "CODE"
    REAL_SMOKE = "REAL_SMOKE"
    REAL_REHEARSAL = "REAL_REHEARSAL"
    REAL_SOAK = "REAL_SOAK"


# A bundle's proof class follows from its manifest source and from nothing else.
_SOURCE_PROOF_CLASS: Mapping[str, ProofClass] = {
    "fixture": ProofClass.FAKE,
    "pg": ProofClass.REAL_SOAK,
}


def bundle_proof_class(source: str) -> ProofClass:
    """The proof class of a bundle manifest source ("fixture" is FAKE, "pg" is REAL_SOAK)."""
    try:
        return _SOURCE_PROOF_CLASS[source]
    except KeyError:
        raise ValueError(f"unknown bundle source {source!r}") from None


# --------------------------------------------------------------------------- #
# Result types.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CriterionResult:
    """One criterion: its verdict and the evidence lines it read."""

    name: str
    passed: bool
    evidence: tuple[str, ...]

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class CriterionGroup:
    """A set of criteria drawn from one evidence set."""

    name: str
    results: tuple[CriterionResult, ...]


@dataclass(frozen=True)
class TimeOfDayDistribution:
    """Covered and uncovered time per UTC hour of day. Reported only; no pass condition."""

    label: str
    covered_microseconds_by_hour_of_day: Mapping[int, int]
    covered_hours_by_hour_of_day: Mapping[int, Decimal]
    uncovered_hours_by_hour_of_day: Mapping[int, Decimal]


@dataclass(frozen=True)
class TrialEvaluation:
    """The judged epoch, the criteria per group and the report-only blocks."""

    epoch_id: str
    window_start_utc: datetime
    window_end_utc: datetime
    bundle_source: str
    proof_class: ProofClass
    groups: tuple[CriterionGroup, ...]
    coverage: CoverageReport
    freeze: FreezeEvidenceReport
    time_of_day: TimeOfDayDistribution
    auxiliary: tuple[str, ...]
    observations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(r.passed for g in self.groups for r in g.results)

    def render(self) -> str:
        """The text the command line prints: PASS or FAIL per criterion with its evidence."""
        lines = [
            f"Trial evaluation of epoch {self.epoch_id}",
            f"window: {self.window_start_utc.isoformat()} to {self.window_end_utc.isoformat()}",
            f"bundle source: {self.bundle_source}",
            f"proof class: {self.proof_class.value}",
        ]
        if self.proof_class is not ProofClass.REAL_SOAK:
            lines.append(
                "note: this evidence is not REAL_SOAK; it can never close a requirement (SC9)."
            )
        for group in self.groups:
            lines.append("")
            lines.append(f"== {group.name} ==")
            for result in group.results:
                lines.append(f"{result.status}  {result.name}")
                lines.extend(f"    {text}" for text in result.evidence)
        lines.append("")
        lines.append(f"REPORTED  {self.time_of_day.label}")
        for hour in range(24):
            covered = self.time_of_day.covered_hours_by_hour_of_day[hour]
            uncovered = self.time_of_day.uncovered_hours_by_hour_of_day[hour]
            lines.append(f"    {hour:02d}:00 UTC  covered {covered} h  uncovered {uncovered} h")
        lines.append("")
        lines.append(f"{OBSERVATIONS_HEADING}:")
        lines.extend(f"    {text}" for text in self.observations)
        lines.append("")
        lines.append(f"{AUXILIARY_HEADING}:")
        lines.extend(f"    {text}" for text in self.auxiliary)
        lines.append("")
        lines.append(f"RESULT: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Small helpers.
# --------------------------------------------------------------------------- #


def _require_utc(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a UTC-aware datetime")


def _hours(microseconds: int) -> Decimal:
    return (Decimal(microseconds) / Decimal(_US_PER_HOUR)).quantize(_QUANT)


def _q(value: Decimal) -> str:
    return str(value.quantize(_QUANT))


def _hour_of_day_split(
    intervals: Sequence[HealthInterval],
) -> tuple[dict[int, int], dict[int, int]]:
    """Microseconds of HEALTHY and non-HEALTHY time per UTC hour of day."""
    covered = dict.fromkeys(range(24), 0)
    uncovered = dict.fromkeys(range(24), 0)
    for interval in intervals:
        bucket = covered if interval.state is HealthState.HEALTHY else uncovered
        cursor = interval.start_utc.astimezone(UTC)
        end = interval.end_utc.astimezone(UTC)
        while cursor < end:
            next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            stop = min(next_hour, end)
            bucket[cursor.hour] += (stop - cursor) // _US
            cursor = stop
    return covered, uncovered


def _time_of_day(intervals: Sequence[HealthInterval]) -> TimeOfDayDistribution:
    covered, uncovered = _hour_of_day_split(intervals)
    return TimeOfDayDistribution(
        label=TIME_OF_DAY_LABEL,
        covered_microseconds_by_hour_of_day=covered,
        covered_hours_by_hour_of_day={h: _hours(us) for h, us in covered.items()},
        uncovered_hours_by_hour_of_day={h: _hours(us) for h, us in uncovered.items()},
    )


def _span(moments: Sequence[datetime]) -> str:
    if not moments:
        return "none"
    return f"{min(moments).isoformat()} to {max(moments).isoformat()}"


# --------------------------------------------------------------------------- #
# Trial definition (not an evidence set): the fixed window.
# --------------------------------------------------------------------------- #


def _trial_window(
    pin_utc: datetime, window_start_utc: datetime, window_end_utc: datetime
) -> CriterionResult:
    expected = timedelta(days=TRIAL_CALENDAR_DAYS)
    length = window_end_utc - window_start_utc
    problems: list[str] = []
    if window_start_utc != pin_utc:
        problems.append(
            f"window starts {window_start_utc.isoformat()} but the epoch is pinned at "
            f"{pin_utc.isoformat()}"
        )
    if length != expected:
        problems.append(f"window length is {length}, not {expected}")
    evidence = [
        f"required: {TRIAL_CALENDAR_DAYS} calendar days from the epoch pin ({DECISION_LABEL})",
        f"window {window_start_utc.isoformat()} to {window_end_utc.isoformat()} = {length}",
        f"epoch pinned at {pin_utc.isoformat()}",
        *problems,
    ]
    return CriterionResult("trial window", not problems, tuple(evidence))


# --------------------------------------------------------------------------- #
# Freeze integrity group (reads only the freeze inputs).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FreezeInputs:
    """Everything the freeze integrity criteria read. No runtime record is in here."""

    manifest_epoch_id: str
    pin_utc: datetime
    window_end_utc: datetime
    pinned_hash: str
    pinned_epoch_id: str
    diff_records: tuple[DiffRecord, ...]
    report: FreezeEvidenceReport
    in_window_gap_records: int


def _freeze_continuity(inputs: _FreezeInputs) -> CriterionResult:
    report = inputs.report
    passed = report.qualifying_from_pin and inputs.in_window_gap_records == 0
    evidence = [
        f"expected scheduled slots {len(report.slots)}, satisfied {len(report.satisfied_slots)}, "
        f"EVIDENCE_GAP {len(report.gaps)}, non-CLEAN lines after the pin {len(report.breaks)}",
        report.statement,
    ]
    if inputs.in_window_gap_records:
        evidence.append(
            f"{inputs.in_window_gap_records} EVIDENCE_GAP record(s) in the bundle fall inside "
            f"the window: the {RESTART_RULE}."
        )
    for gap in report.gaps[:10]:
        evidence.append(
            f"EVIDENCE_GAP slot {gap.slot_utc.isoformat()} reason {gap.reason.value}"
            + ("" if gap.run_id is None else f" run {gap.run_id}")
        )
    if len(report.gaps) > 10:
        evidence.append(f"... and {len(report.gaps) - 10} more EVIDENCE_GAP slot(s)")
    return CriterionResult("freeze continuity", passed, tuple(evidence))


def _lines_after_pin(inputs: _FreezeInputs) -> list[DiffRecord]:
    return [
        r
        for r in inputs.diff_records
        if r.checked_at_utc is not None and r.checked_at_utc > inputs.pin_utc
    ]


def _single_epoch(inputs: _FreezeInputs) -> CriterionResult:
    after = _lines_after_pin(inputs)
    stamped = [r for r in after if r.epoch_id is not None]
    foreign = sorted(
        {
            r.epoch_id
            for r in stamped
            if r.epoch_id is not None and r.epoch_id != inputs.pinned_epoch_id
        }
    )
    problems: list[str] = []
    if inputs.manifest_epoch_id != inputs.pinned_epoch_id:
        problems.append(
            f"manifest epoch_id {inputs.manifest_epoch_id} != pinned epoch_id "
            f"{inputs.pinned_epoch_id}"
        )
    if foreign:
        problems.append(f"freeze lines after the pin carry other epoch_id value(s): {foreign}")
    if not stamped:
        problems.append("no freeze line after the pin carries an epoch_id (cannot be shown)")
    evidence = [
        f"epoch_id {inputs.pinned_epoch_id}; {len(stamped)} freeze line(s) after the pin read",
        *problems,
    ]
    return CriterionResult("single epoch", not problems, tuple(evidence))


def _hash_unchanged(inputs: _FreezeInputs) -> CriterionResult:
    after = [r for r in _lines_after_pin(inputs) if r.outcome == "clean"]
    changed = [
        r
        for r in after
        if r.pinned_hash != inputs.pinned_hash or r.current_hash != inputs.pinned_hash
    ]
    problems: list[str] = []
    if changed:
        first = changed[0].checked_at_utc
        problems.append(
            f"{len(changed)} CLEAN line(s) after the pin do not carry the pinned hash "
            f"(first at {first.isoformat() if first else 'an unknown time'})"
        )
    if not after:
        problems.append("no CLEAN freeze line after the pin carries a hash (cannot be shown)")
    evidence = [
        f"pinned parameter_set_hash {inputs.pinned_hash}; {len(after)} CLEAN line(s) read",
        *problems,
    ]
    return CriterionResult("pinned hash unchanged", not problems, tuple(evidence))


def _freeze_group(inputs: _FreezeInputs) -> CriterionGroup:
    return CriterionGroup(
        "freeze integrity",
        (_freeze_continuity(inputs), _single_epoch(inputs), _hash_unchanged(inputs)),
    )


# --------------------------------------------------------------------------- #
# Runtime health group (reads only the runtime records).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _RuntimeInputs:
    """Everything the runtime health criteria read. No freeze line or run is in here."""

    epoch_id: str
    window_start_utc: datetime
    window_end_utc: datetime
    records: tuple[RuntimeRecord, ...]
    coverage: CoverageReport


def _coverage_criterion(inputs: _RuntimeInputs) -> CriterionResult:
    report = inputs.coverage
    evidence = [
        f"window {_q(report.window_hours)} h; covered {_q(report.covered_hours)} h "
        f"(fraction {report.covered_fraction.quantize(Decimal('0.0001'))}); criterion: at least "
        f"{MIN_COVERAGE_FRACTION} of the whole window with a HEALTHY feed ({DECISION_LABEL})",
        f"minimum covered time {_q(report.derived_minimum_covered_hours)} h - "
        f"{report.derived_minimum_label}",
    ]
    if not report.coverage_pass:
        evidence.append("coverage is below the criterion")
    evidence.extend(
        f"uncovered {u.start_utc.isoformat()} to {u.end_utc.isoformat()} reason {u.reason.value}"
        for u in report.uncovered[:20]
    )
    if len(report.uncovered) > 20:
        evidence.append(f"... and {len(report.uncovered) - 20} more uncovered interval(s)")
    return CriterionResult("runtime coverage", report.coverage_pass, tuple(evidence))


def _ceiling_criterion(inputs: _RuntimeInputs) -> CriterionResult:
    report = inputs.coverage
    block = report.longest_uncovered_block
    evidence: tuple[str, ...]
    if block is None:
        evidence = (
            f"no uncovered time; ceiling {report.ceiling_seconds} s (the user's number, O-07)",
        )
    else:
        reasons = ", ".join(reason.value for reason in block.reasons)
        evidence = (
            f"longest continuous uncovered block {block.length_seconds} s from "
            f"{block.start_utc.isoformat()} to {block.end_utc.isoformat()} ({reasons})",
            f"ceiling {report.ceiling_seconds} s (the user's number, O-07, from the ratified "
            "configuration)",
        )
    return CriterionResult("continuous uncovered time", report.ceiling_pass, evidence)


def _runtime_group(inputs: _RuntimeInputs) -> CriterionGroup:
    return CriterionGroup(
        "runtime health", (_coverage_criterion(inputs), _ceiling_criterion(inputs))
    )


# --------------------------------------------------------------------------- #
# Auxiliary evidence and observations (report-only).
# --------------------------------------------------------------------------- #


def _auxiliary_lines(
    bundle: EvidenceBundle, report: FreezeEvidenceReport, pin_utc: datetime
) -> tuple[str, ...]:
    aux = report.auxiliary
    span = "none"
    if aux.first_utc is not None and aux.last_utc is not None:
        span = f"{aux.first_utc.isoformat()} to {aux.last_utc.isoformat()}"
    lines = [
        f"freeze lines at or before the pin: {aux.line_count}; runs: {aux.run_count}; span {span}",
    ]
    others: dict[str, list[datetime]] = {}
    for record in bundle.records:
        if record.epoch_id != bundle.epoch_id:
            others.setdefault(record.epoch_id, []).append(record.occurred_at_utc)
    if others:
        for epoch_id in sorted(others):
            moments = others[epoch_id]
            lines.append(
                f"runtime records of earlier epoch {epoch_id}: {len(moments)}; "
                f"span {_span(moments)}"
            )
    else:
        lines.append("runtime records of other epochs: 0")
    earlier_gaps = [g for g in bundle.evidence_gaps if g.slot_utc <= pin_utc]
    lines.append(f"EVIDENCE_GAP records of earlier epochs: {len(earlier_gaps)}")
    lines.append(
        "all of the above is retained untouched and cannot satisfy a slot or an interval of the "
        "judged epoch: earlier-epoch evidence cannot complete the freeze criterion of the new "
        "trial (REV-18)."
    )
    return tuple(lines)


def _observation_lines(records: Sequence[RuntimeRecord]) -> tuple[str, ...]:
    summary = tick_timing_summary(records)
    dropped = ", ".join(f"{reason}={count}" for reason, count in summary.dropped_by_reason)
    return (
        "report-only: no observation turns a criterion into PASS or FAIL.",
        f"tick timing: {summary.tick_count} tick(s); duration ms min {summary.duration_ms_min} "
        f"median {summary.duration_ms_median} max {summary.duration_ms_max}; "
        f"queue depth max {summary.queue_depth_max}",
        f"dropped events: {summary.dropped_total}" + (f" ({dropped})" if dropped else ""),
    )


# --------------------------------------------------------------------------- #
# The evaluator.
# --------------------------------------------------------------------------- #


def evaluate_trial(
    bundle: EvidenceBundle,
    *,
    thresholds: HealthThresholds,
    cron: str,
    symbols: Sequence[str],
) -> TrialEvaluation:
    """Judge the manifest's epoch from one verified bundle.

    `thresholds` are the user-ratified numbers (O-07) and `cron` is the recorded schedule of the
    freeze workflow; neither has a default. `symbols` are the scope of the ratified configuration:
    every closed 1h and 4h bar of each must be accounted for. The grace is passed only to
    `freeze_evidence_report`, where it can never turn a gap into CLEAN.
    """
    if not isinstance(thresholds, HealthThresholds):
        raise TypeError("thresholds must be the HealthThresholds of the ratified configuration")
    if (
        isinstance(symbols, str)
        or len(symbols) == 0
        or not all(isinstance(s, str) for s in symbols)
    ):
        raise ValueError("symbols must be a non-empty sequence of symbol names")
    _require_utc("window_start_utc", bundle.window_start_utc)
    _require_utc("window_end_utc", bundle.window_end_utc)
    _require_utc("pin_utc", bundle.pinned.opened_at_utc)

    pin = bundle.pinned.opened_at_utc
    start, end = bundle.window_start_utc, bundle.window_end_utc
    mine = tuple(r for r in bundle.records if r.epoch_id == bundle.epoch_id)

    freeze = freeze_evidence_report(
        pin_utc=pin,
        window_end_utc=end,
        cron=cron,
        lines=bundle.freeze_lines,
        runs=bundle.runs,
        grace_seconds=thresholds.freeze_tick_grace_seconds,
        detected_at_utc=end,
    )
    in_window_gaps = sum(1 for g in bundle.evidence_gaps if pin < g.slot_utc <= end)

    health = derive_health_intervals(
        mine,
        epoch_id=bundle.epoch_id,
        window_start_utc=start,
        window_end_utc=end,
        intervals_expected=[(s, i) for s in symbols for i in EVALUATED_INTERVALS],
        thresholds=thresholds,
    )
    coverage = coverage_report(
        window_start_utc=start,
        window_end_utc=end,
        intervals=health,
        continuous_uncovered_ceiling_seconds=thresholds.continuous_uncovered_ceiling_seconds,
    )

    freeze_inputs = _FreezeInputs(
        manifest_epoch_id=bundle.epoch_id,
        pin_utc=pin,
        window_end_utc=end,
        pinned_hash=bundle.pinned.parameter_set_hash,
        pinned_epoch_id=bundle.pinned.epoch_id,
        diff_records=bundle.diff_records,
        report=freeze,
        in_window_gap_records=in_window_gaps,
    )
    runtime_inputs = _RuntimeInputs(
        epoch_id=bundle.epoch_id,
        window_start_utc=start,
        window_end_utc=end,
        records=mine,
        coverage=coverage,
    )
    groups = (
        CriterionGroup("trial definition", (_trial_window(pin, start, end),)),
        _freeze_group(freeze_inputs),
        _runtime_group(runtime_inputs),
    )
    return TrialEvaluation(
        epoch_id=bundle.epoch_id,
        window_start_utc=start,
        window_end_utc=end,
        bundle_source=bundle.source,
        proof_class=bundle_proof_class(bundle.source),
        groups=groups,
        coverage=coverage,
        freeze=freeze,
        time_of_day=_time_of_day(health),
        auxiliary=_auxiliary_lines(bundle, freeze, pin),
        observations=_observation_lines(mine),
    )


__all__ = [
    "AUXILIARY_HEADING",
    "DECISION_LABEL",
    "EVALUATED_INTERVALS",
    "MIN_COVERAGE_FRACTION",
    "OBSERVATIONS_HEADING",
    "PARITY_TOLERANCE",
    "RESTART_RULE",
    "TIME_OF_DAY_LABEL",
    "TRIAL_CALENDAR_DAYS",
    "CriterionGroup",
    "CriterionResult",
    "ProofClass",
    "TimeOfDayDistribution",
    "TrialEvaluation",
    "bundle_proof_class",
    "evaluate_trial",
]
