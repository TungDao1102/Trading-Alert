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

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from src.core.types import Candle
from src.domain.registry import ParameterSet
from src.paper.bars import CONTEXT_INTERVAL, SETUP_INTERVAL, BarBuffers
from src.paper.coverage import (
    RESTART_RULE,
    SLOT_INTERVAL_SECONDS,
    CoverageReport,
    FreezeEvidenceReport,
    HealthInterval,
    HealthThresholds,
    HostTickVerdict,
    coverage_report,
    derive_health_intervals,
    freeze_evidence_report,
    tick_timing_summary,
)
from src.paper.evidence_bundle import MANIFEST_NAME, DiffRecord, EvidenceBundle
from src.paper.loop import BAR_STAGES, BarContext, check_feed_freshness
from src.paper.pipeline import REASON_HISTORY_DISCONTINUITY, REASON_SIBLING_4H_MISSING
from src.paper.replay_inputs import (
    HistoryEntry,
    ReplayInputsError,
    context_from_inputs,
    parse_history_payload,
    window_accept_seq_of,
    window_digest,
)
from src.paper.runtime_state import RuntimeRecord
from src.paper.surface import (
    REASON_DUPLICATE_BAR,
    context_record,
    decision_surface,
    gate_record,
    observe_closed_bar,
)
from src.paper.vocabulary import INTERVAL_MS, GapReason, HealthState, RuntimeEventType

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
# Inputs only the runtime checks need: the Q-D rule and the parity replay context.
# --------------------------------------------------------------------------- #


class BackfillRule(StrEnum):
    """The user's Q-D decision on REST_BACKFILL bars (decisions/16-DEC-Q-D.md)."""

    HISTORY_ONLY = "history-only"
    FRESH_WITHIN_BOUND = "fresh-within-bound"


def read_backfill_rule(path: Path) -> BackfillRule:
    """Read the `option:` line of the Q-D decision file. There is no default.

    Raises:
        FileNotFoundError: the decision file does not exist.
        ValueError: the file has no `option:` line, or names an option this code does not know.
    """
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "option":
            try:
                return BackfillRule(value.strip())
            except ValueError:
                raise ValueError(f"{path.name}: unknown Q-D option {value.strip()!r}") from None
    raise ValueError(f"{path.name} has no 'option:' line")


@dataclass(frozen=True)
class ReplayRun:
    """One process run of the trial: its acceptance log, in acceptance order (plan 16-51).

    The run starts at a RUNTIME_START record and ends before the next one (None for the last run).
    Every pipeline numbers the bars it accepts from zero, so a log is only meaningful per run.
    """

    started_at_utc: datetime
    ended_before_utc: datetime | None
    log: tuple[HistoryEntry, ...]


@dataclass(frozen=True)
class ParityUnavailable:
    """The parity replay cannot be built from the bundle (plan 16-51); `reason` says why.

    Parity is then NOT EVALUATED and the criterion FAILS: a missing comparison is never a PASS.
    """

    reason: str


NO_REPLAY_INPUTS_REASON = (
    "the bundle carries no recorded replay inputs; it was written by a runtime before plan 16-51"
)


@dataclass(frozen=True)
class ParityReplay:
    """What the parity replay needs besides the recorded bars (D061 item D, L-04).

    Two forms. The bundle form (plan 16-51, `build_parity_replay`) carries `runs` (the acceptance
    log of each process run) and the registry `parameter_set`: the context of each evaluated bar is
    rebuilt from its recorded replay inputs and nothing else is supplied. The seam form (plan
    16-25) carries `context`, the `BarContext` (or a callable returning it per 1h bar) the live
    runtime decided with, and `history_bars`, the REST warm-up bars the runtime loaded before its
    first live bar (history, never recorded as processed); it is kept for the fixture tests.
    `build_problems` are inconsistencies found while the replay was built; each fails parity.
    """

    context: BarContext | Callable[[Candle], BarContext] | None = None
    history_bars: tuple[Candle, ...] = ()
    runs: tuple[ReplayRun, ...] = ()
    parameter_set: ParameterSet | None = None
    build_problems: tuple[str, ...] = ()


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
    if report.host_results:
        counts = Counter(result.verdict for result in report.host_results)
        shown = ", ".join(f"{v.value} {counts[v]}" for v in HostTickVerdict if counts[v])
        evidence.append(f"host witness ticks judged {len(report.host_results)}: {shown}")
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
    """Freeze lines of this trial: after the pin, up to one slot after the window end.

    The line of the last slot is written after the window end, so the bound is one slot interval
    later; anything beyond belongs to a later epoch and is auxiliary (REV-18).
    """
    last = inputs.window_end_utc + timedelta(seconds=SLOT_INTERVAL_SECONDS)
    return [
        r
        for r in inputs.diff_records
        if r.checked_at_utc is not None and inputs.pin_utc < r.checked_at_utc <= last
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
    symbols: tuple[str, ...]
    records: tuple[RuntimeRecord, ...]
    coverage: CoverageReport
    backfill_rule: BackfillRule
    parity: ParityReplay | ParityUnavailable | None
    other_epoch_records_in_window: tuple[tuple[str, int], ...]


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


_PROBLEM_LIMIT = 20


def _with_problems(name: str, summary: Sequence[str], problems: Sequence[str]) -> CriterionResult:
    """A criterion that passes exactly when it found no problem; problems are listed capped."""
    evidence = [*summary, *problems[:_PROBLEM_LIMIT]]
    if len(problems) > _PROBLEM_LIMIT:
        evidence.append(f"... and {len(problems) - _PROBLEM_LIMIT} more")
    return CriterionResult(name, not problems, tuple(evidence))


def _read_time(payload: Mapping[str, object], key: str) -> datetime | None:
    """A UTC-aware time from a payload value, or None when absent or unreadable."""
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _pair(record: RuntimeRecord) -> str:
    return f"{record.symbol} {record.interval}"


def _processed(records: Sequence[RuntimeRecord]) -> list[RuntimeRecord]:
    chosen = [r for r in records if r.event_type is RuntimeEventType.PAPER_BAR_PROCESSED]
    return sorted(chosen, key=lambda r: (r.occurred_at_utc, r.symbol or "", r.interval or ""))


def _gap_records(records: Sequence[RuntimeRecord]) -> list[RuntimeRecord]:
    chosen = [r for r in records if r.event_type is RuntimeEventType.PAPER_GAP]
    return sorted(chosen, key=lambda r: (r.occurred_at_utc, r.symbol or "", r.interval or ""))


def _gaps_explained(inputs: _RuntimeInputs) -> CriterionResult:
    """Every gap carries a known reason that is not UNKNOWN; no bar is late or fabricated."""
    problems: list[str] = []
    gaps = _gap_records(inputs.records)
    bars = _processed(inputs.records)
    reasons: Counter[str] = Counter()
    for gap in gaps:
        close = _read_time(gap.payload, "expected_close_utc")
        label = f"{_pair(gap)} close {close.isoformat() if close else 'unknown'}"
        raw = gap.payload.get("reason")
        if raw is None:
            problems.append(f"PAPER_GAP {label} has no reason code")
            continue
        try:
            reason = GapReason(str(raw))
        except ValueError:
            problems.append(f"PAPER_GAP {label} has an unknown reason code {raw!r}")
            continue
        reasons[reason.value] += 1
        if reason is GapReason.UNKNOWN:
            problems.append(f"unexplained gap: PAPER_GAP {label} has reason UNKNOWN")
    sources: Counter[str] = Counter()
    for bar in bars:
        close = bar.occurred_at_utc
        label = f"{_pair(bar)} close {close.isoformat()}"
        source = str(bar.payload.get("source"))
        sources[source] += 1
        if source == "REST_BACKFILL":
            if inputs.backfill_rule is BackfillRule.HISTORY_ONLY:
                problems.append(
                    f"late or fabricated bar: {label} was recorded from REST_BACKFILL, which the "
                    f"Q-D rule ({inputs.backfill_rule.value}) never evaluates"
                )
            else:
                problems.append(
                    f"late or fabricated bar: {label} was recorded from REST_BACKFILL and there "
                    f"is no ratified bound to check its age against "
                    f"({inputs.backfill_rule.value})"
                )
        elif source == "REST_WARMUP":
            problems.append(
                f"late or fabricated bar: {label} was recorded from REST_WARMUP (history only)"
            )
        elif source != "LIVE_WS":
            problems.append(f"late or fabricated bar: {label} has an unknown source {source!r}")
        tick = _read_time(bar.payload, "tick_time_utc")
        if tick is None:
            problems.append(f"late or fabricated bar: {label} has no readable tick time")
        elif tick < close:
            problems.append(f"late or fabricated bar: {label} was processed before it closed")
    by_source = ", ".join(f"{k}={v}" for k, v in sorted(sources.items())) or "none"
    by_reason = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())) or "none"
    summary = (
        f"{len(bars)} processed bar record(s) by source: {by_source}; "
        f"{len(gaps)} PAPER_GAP record(s) by reason: {by_reason}",
        f"Q-D rule in force: {inputs.backfill_rule.value}",
    )
    return _with_problems("gaps explained, no fabricated bar", summary, problems)


@dataclass(frozen=True)
class _Run:
    start: datetime
    end: datetime | None


def _runs(records: Sequence[RuntimeRecord]) -> list[_Run]:
    """Runs from RUNTIME_START and RUNTIME_STOP; a START with no STOP before the next START ends
    at that next START."""
    markers = sorted(
        (
            r
            for r in records
            if r.event_type in (RuntimeEventType.RUNTIME_START, RuntimeEventType.RUNTIME_STOP)
        ),
        key=lambda r: (r.occurred_at_utc, r.event_type is RuntimeEventType.RUNTIME_START),
    )
    runs: list[_Run] = []
    opened: datetime | None = None
    for marker in markers:
        if marker.event_type is RuntimeEventType.RUNTIME_START:
            if opened is not None:
                runs.append(_Run(opened, marker.occurred_at_utc))
            opened = marker.occurred_at_utc
        elif opened is not None:
            runs.append(_Run(opened, marker.occurred_at_utc))
            opened = None
    if opened is not None:
        runs.append(_Run(opened, None))
    return runs


def _restart_warmup(inputs: _RuntimeInputs) -> CriterionResult:
    """A bar that closed while the process was down never produces a signal (D061 item 1)."""
    runs = _runs(inputs.records)
    problems: list[str] = []
    checked = 0
    for bar in _processed(inputs.records):
        if bar.payload.get("stage") not in BAR_STAGES:
            continue  # a feed-gate reject or a context bar decides nothing
        checked += 1
        tick = _read_time(bar.payload, "tick_time_utc")
        if tick is None:
            continue  # reported by the gap check
        label = f"{_pair(bar)} close {bar.occurred_at_utc.isoformat()}"
        run = next((r for r in runs if r.start <= tick and (r.end is None or tick <= r.end)), None)
        if run is None:
            problems.append(f"evaluated bar {label} has no recorded run around its tick time")
        elif bar.occurred_at_utc <= run.start:
            problems.append(
                f"evaluated bar {label} closed while the process was down (before the start at "
                f"{run.start.isoformat()}): no late signal may exist"
            )
    summary = (
        f"{len(runs)} run(s) from RUNTIME_START and RUNTIME_STOP records; "
        f"{checked} evaluated bar(s) checked against the start of their run",
    )
    return _with_problems("restart warm-up before the first evaluated bar", summary, problems)


def _no_duplicate_signal(inputs: _RuntimeInputs) -> CriterionResult:
    bars = _processed(inputs.records)
    keys = Counter((r.symbol, r.interval, r.occurred_at_utc) for r in bars)
    problems = [
        f"duplicate signal: {count} PAPER_BAR_PROCESSED records for {symbol} {interval} close "
        f"{close.isoformat()}"
        for (symbol, interval, close), count in sorted(
            keys.items(), key=lambda item: (item[0][2], item[0][0] or "", item[0][1] or "")
        )
        if count > 1
    ]
    signal_bars: dict[str, set[tuple[str | None, str | None, datetime]]] = {}
    for bar in bars:
        surface = bar.payload.get("surface")
        signal_id = surface.get("signal_id") if isinstance(surface, Mapping) else None
        if isinstance(signal_id, str) and signal_id:
            signal_bars.setdefault(signal_id, set()).add(
                (bar.symbol, bar.interval, bar.occurred_at_utc)
            )
    problems.extend(
        f"duplicate signal: signal id {signal_id} appears on {len(places)} bars"
        for signal_id, places in sorted(signal_bars.items())
        if len(places) > 1
    )
    summary = (
        f"{len(bars)} PAPER_BAR_PROCESSED record(s) read; {len(signal_bars)} distinct signal id(s)",
    )
    return _with_problems("no duplicate signal", summary, problems)


def _expected_closes(interval: str, start_utc: datetime, end_utc: datetime) -> list[datetime]:
    """Close times (open + interval - 1 ms, on the epoch grid) in [start_utc, end_utc)."""
    step = INTERVAL_MS[interval]
    origin = datetime(1970, 1, 1, tzinfo=UTC)
    start_ms = (start_utc - origin) // timedelta(milliseconds=1)
    k = -((-(start_ms + 1)) // step)  # ceil((start_ms + 1) / step)
    closes: list[datetime] = []
    while True:
        close = origin + timedelta(milliseconds=k * step - 1)
        if close >= end_utc:
            return closes
        closes.append(close)
        k += 1


def _no_missing_row(inputs: _RuntimeInputs) -> CriterionResult:
    have: set[tuple[str | None, str | None, datetime]] = {
        (r.symbol, r.interval, r.occurred_at_utc) for r in _processed(inputs.records)
    }
    for gap in _gap_records(inputs.records):
        expected = _read_time(gap.payload, "expected_close_utc")
        if expected is not None:
            have.add((gap.symbol, gap.interval, expected))
    expected_total = 0
    problems: list[str] = []
    for symbol in inputs.symbols:
        for interval in EVALUATED_INTERVALS:
            for close in _expected_closes(interval, inputs.window_start_utc, inputs.window_end_utc):
                expected_total += 1
                if (symbol, interval, close) not in have:
                    problems.append(
                        f"missing journal row: {symbol} {interval} close {close.isoformat()} has "
                        "neither a processed record nor a gap record"
                    )
    summary = (
        f"{expected_total} expected closed bar(s) ({', '.join(inputs.symbols)} x "
        f"{', '.join(EVALUATED_INTERVALS)}) from the pin to the window end; "
        f"{len(problems)} without a record",
    )
    return _with_problems("no missing journal row", summary, problems)


def _no_test_signal(inputs: _RuntimeInputs) -> CriterionResult:
    """REV-03: the test signal runs only in a rehearsal before the soak (every record test_only)."""
    problems = [
        f"test signal inside the soak window: {r.event_type.value} at "
        f"{r.occurred_at_utc.isoformat()} is marked test_only"
        for r in sorted(inputs.records, key=lambda r: (r.occurred_at_utc, r.event_type.value))
        if r.payload.get("test_only") not in (None, False)
    ]
    summary = (f"{len(inputs.records)} runtime record(s) of the judged epoch read",)
    return _with_problems("no test signal inside the soak window", summary, problems)


def _one_epoch(inputs: _RuntimeInputs) -> CriterionResult:
    problems = [
        f"{count} runtime record(s) of epoch {epoch_id} lie inside the trial window: more than "
        "one epoch_id"
        for epoch_id, count in inputs.other_epoch_records_in_window
    ]
    summary = (
        f"judged epoch {inputs.epoch_id}; runtime records of earlier epochs before the pin are "
        "auxiliary and are not read here",
    )
    return _with_problems("runtime records of one epoch", summary, problems)


# --------------------------------------------------------------------------- #
# Parity (tolerance zero) over the recorded bars and the live surface records.
# --------------------------------------------------------------------------- #

_PIPELINE_ONLY_GATES = frozenset({REASON_HISTORY_DISCONTINUITY, REASON_SIBLING_4H_MISSING})
_PARITY_NAME = "parity (tolerance zero)"


def _candle_from(bar: Mapping[str, object]) -> Candle:
    def moment(key: str) -> datetime:
        value = _read_time(bar, key)
        if value is None:
            raise ValueError(f"bar {key} is not a UTC time")
        return value

    try:
        return Candle(
            symbol=str(bar["symbol"]),
            interval=str(bar["interval"]),
            open_time_utc=moment("open_time_utc"),
            close_time_utc=moment("close_time_utc"),
            open=Decimal(str(bar["open"])),
            high=Decimal(str(bar["high"])),
            low=Decimal(str(bar["low"])),
            close=Decimal(str(bar["close"])),
            volume=Decimal(str(bar["volume"])),
        )
    except (KeyError, InvalidOperation) as exc:
        raise ValueError(f"bar field unreadable: {exc!r}") from None


def _close_ms(moment: datetime) -> int:
    return (moment - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1)


def parity_criterion(
    records: Sequence[RuntimeRecord], replay: ParityReplay | ParityUnavailable | None
) -> CriterionResult:
    """Replay the recorded bars through the shared chain and compare every live surface record.

    The replay uses `decision_surface` (the function the live pipeline's mapping is shared with)
    over the history bars and the bars recorded in the PAPER_BAR_PROCESSED payloads. The recorded
    tick time decides the freshness gate (`check_feed_freshness`), so a DATA_STALE gate record is
    reproduced from the record, not assumed. HISTORY_DISCONTINUITY and SIBLING_4H_MISSING gate
    records depend on the pipeline's own buffers and are counted, not compared. The tolerance is
    `PARITY_TOLERANCE` (zero): any differing record fails.
    """
    if isinstance(replay, ParityUnavailable):
        return CriterionResult(_PARITY_NAME, False, (f"NOT EVALUATED: {replay.reason}",))
    if replay is None or (replay.parameter_set is None and replay.context is None):
        return CriterionResult(
            _PARITY_NAME,
            False,
            (
                "NOT EVALUATED: no replay context was supplied, so the recorded decisions were "
                "not compared with a replay (a missing comparison is never a PASS)",
            ),
        )
    if replay.parameter_set is not None:
        return _parity_from_bundle(records, replay, replay.parameter_set)
    seam_context = replay.context
    if seam_context is None:  # unreachable: guarded above; narrows the type for the replay
        raise AssertionError("a seam replay needs a context")
    bars = _processed(records)
    if not bars:
        return CriterionResult(
            _PARITY_NAME, False, ("no processed bar record to replay (nothing was compared)",)
        )
    problems: list[str] = []
    recorded: list[tuple[RuntimeRecord, Candle, dict[str, object]]] = []
    for record in bars:
        bar, surface = record.payload.get("bar"), record.payload.get("surface")
        label = f"{_pair(record)} close {record.occurred_at_utc.isoformat()}"
        if not isinstance(bar, Mapping) or not isinstance(surface, Mapping):
            problems.append(f"{label}: the record carries no bar or no surface to compare")
            continue
        try:
            candle = _candle_from(bar)
        except ValueError as exc:
            problems.append(f"{label}: {exc}")
            continue
        recorded.append((record, candle, dict(surface)))

    replayed: dict[tuple[str, str, datetime], dict[str, object]] = {}
    refused = False
    if recorded:
        try:
            produced = decision_surface(
                [*replay.history_bars, *(candle for _, candle, _ in recorded)],
                context=seam_context,
            )
        except ValueError as exc:
            problems.append(f"the replay refused the recorded bars: {exc}")
            refused = True
            produced = ()
        for item in produced:
            if item.reason_code != REASON_DUPLICATE_BAR:
                replayed.setdefault(
                    (item.symbol, item.interval, item.bar_close_utc), item.to_dict()
                )

    compared = 0
    skipped = 0
    stages: Counter[str] = Counter()
    mismatches: list[str] = []
    for record, candle, live in recorded:
        stages[str(live.get("stage"))] += 1
        if live.get("stage") == "feed_gate" and live.get("reason_code") in _PIPELINE_ONLY_GATES:
            skipped += 1
            continue
        tick = _read_time(record.payload, "tick_time_utc")
        stale = None
        if candle.interval == SETUP_INTERVAL and tick is not None:
            stale = check_feed_freshness({"T": _close_ms(candle.close_time_utc)}, tick)
        key = (candle.symbol, candle.interval, candle.close_time_utc)
        expected: dict[str, object] | None
        if stale is not None:
            expected = dict(gate_record(candle, stale).to_dict())
        else:
            expected = replayed.get(key)
        label = f"{_pair(record)} close {candle.close_time_utc.isoformat()}"
        if expected is None:
            if not refused:
                problems.append(f"{label}: the replay produced no record for this bar")
            continue
        compared += 1
        differing = [k for k in sorted({*live, *expected}) if live.get(k) != expected.get(k)]
        if differing:
            mismatches.append(
                f"{label}: differs in {', '.join(differing)} (recorded stage "
                f"{live.get('stage')} {live.get('reason_code')}, replay stage "
                f"{expected.get('stage')} {expected.get('reason_code')})"
            )
    by_stage = ", ".join(f"{k}={v}" for k, v in sorted(stages.items()))
    summary = [
        f"{compared} recorded surface record(s) compared with the replay of "
        f"{len(replay.history_bars)} history bar(s) and {len(recorded)} recorded bar(s); "
        f"tolerance {PARITY_TOLERANCE}, {len(mismatches)} difference(s)",
        f"recorded stages: {by_stage or 'none'}; pipeline-only gate records not compared: "
        f"{skipped}",
    ]
    failed = len(mismatches) > PARITY_TOLERANCE or bool(problems)
    evidence = [*summary, *problems, *mismatches[:_PROBLEM_LIMIT]]
    if len(mismatches) > _PROBLEM_LIMIT:
        evidence.append(f"... and {len(mismatches) - _PROBLEM_LIMIT} more difference(s)")
    return CriterionResult(_PARITY_NAME, not failed, tuple(evidence))


def _run_index(starts: Sequence[datetime], moment: datetime) -> int | None:
    """The index of the run holding `moment`: the last start at or before it (None before all)."""
    found: int | None = None
    for index, start in enumerate(starts):
        if start <= moment:
            found = index
    return found


def build_parity_replay(
    records: Sequence[RuntimeRecord],
    *,
    parameter_set: ParameterSet,
    pinned_parameter_set_hash: str,
) -> ParityReplay | ParityUnavailable:
    """Build the parity replay from the runtime records of ONE epoch and the registry set.

    Run k starts at its RUNTIME_START and ends before the next one; every PAPER_HISTORY_BARS record
    joins the run holding its time, and each run's log is ordered by acceptance sequence. A history
    record outside every run or an unreadable one is kept as a build problem (parity fails on it).
    `pinned_parameter_set_hash` is the epoch's pinned hash; the registry set must carry it.

    Returns `ParityUnavailable` (parity NOT EVALUATED, the criterion fails) when the registry set
    carries another hash than the pinned one, or when the records hold no replay inputs and no
    history record (a bundle written by a runtime before plan 16-51).
    """
    if parameter_set.parameter_set_hash != pinned_parameter_set_hash:
        return ParityUnavailable(
            f"the registry parameter set hash {parameter_set.parameter_set_hash} differs from the "
            f"parameter set hash {pinned_parameter_set_hash} pinned by the epoch"
        )
    if not has_recorded_replay_inputs(records):
        return ParityUnavailable(NO_REPLAY_INPUTS_REASON)
    starts = sorted(
        {r.occurred_at_utc for r in records if r.event_type is RuntimeEventType.RUNTIME_START}
    )
    logs: list[list[HistoryEntry]] = [[] for _ in starts]
    problems: list[str] = []
    history = sorted(
        (r for r in records if r.event_type is RuntimeEventType.PAPER_HISTORY_BARS),
        key=lambda r: (r.occurred_at_utc, r.payload_json),
    )
    for record in history:
        when = record.occurred_at_utc.isoformat()
        try:
            entries = parse_history_payload(json.loads(record.payload_json))
        except ReplayInputsError as exc:
            problems.append(f"history record at {when}: {exc}")
            continue
        index = _run_index(starts, record.occurred_at_utc)
        if index is None:
            problems.append(f"history record at {when} lies outside every recorded run")
            continue
        logs[index].extend(entries)
    runs = tuple(
        ReplayRun(
            started_at_utc=start,
            ended_before_utc=starts[index + 1] if index + 1 < len(starts) else None,
            log=tuple(sorted(logs[index], key=lambda e: e.accept_seq)),
        )
        for index, start in enumerate(starts)
    )
    return ParityReplay(runs=runs, parameter_set=parameter_set, build_problems=tuple(problems))


def has_recorded_replay_inputs(records: Sequence[RuntimeRecord]) -> bool:
    """True when the records hold at least one replay-inputs or history record (plan 16-51)."""
    return any(
        r.event_type in (RuntimeEventType.PAPER_REPLAY_INPUTS, RuntimeEventType.PAPER_HISTORY_BARS)
        for r in records
    )


@dataclass
class _RunFeed:
    """A fresh buffer set fed from one run's log, in acceptance order."""

    log: tuple[HistoryEntry, ...]
    buffers: BarBuffers
    fed: int = 0
    next_seq: int = 0
    error: str | None = None


class _NoRecordedInputs(Exception):
    """The replay reached the risk stage of a bar that has no replay-inputs record."""


def _advance(feed: _RunFeed, cut: int) -> str | None:
    """Feed every log entry up to the cut point; the error text when the log cannot reach it."""
    while feed.error is None and feed.fed < len(feed.log) and feed.log[feed.fed].accept_seq <= cut:
        entry = feed.log[feed.fed]
        if entry.accept_seq != feed.next_seq:
            feed.error = (
                f"the acceptance log is not contiguous: expected accept_seq {feed.next_seq}, "
                f"found {entry.accept_seq}"
            )
        elif not feed.buffers.add(entry.candle):
            feed.error = f"the buffers refused logged bar accept_seq {entry.accept_seq}"
        else:
            feed.fed += 1
            feed.next_seq += 1
    if feed.error is None and feed.next_seq != cut + 1:
        feed.error = (
            f"window_accept_seq {cut} is not in the acceptance log (it ends at {feed.next_seq - 1})"
        )
    return feed.error


@dataclass
class _Windowed:
    """A recorded 1h bar waiting for its windows: the cut point and its recorded inputs."""

    slot: int
    record: RuntimeRecord
    candle: Candle
    live: dict[str, object]
    label: str
    run: int
    cut: int
    inputs: RuntimeRecord | None


def _parity_from_bundle(
    records: Sequence[RuntimeRecord], replay: ParityReplay, parameter_set: ParameterSet
) -> CriterionResult:
    """Parity from the bundle alone (plan 16-51): run by run, in acceptance order.

    Each run's log is fed into a fresh `BarBuffers`; every evaluated 1h bar is observed when the
    feed reaches its cut point (`window_accept_seq` of its replay-inputs record), over windows whose
    digests must equal the recorded ones, with the context rebuilt from the recorded inputs and
    verified. A missing record, a gap in the log or a differing window fails and names the bar
    close.
    """
    bars = _processed(records)
    if not bars:
        return CriterionResult(
            _PARITY_NAME, False, ("no processed bar record to replay (nothing was compared)",)
        )
    problems: list[str] = list(replay.build_problems)
    inputs_by_key = {
        (r.symbol, r.interval, r.occurred_at_utc): r
        for r in records
        if r.event_type is RuntimeEventType.PAPER_REPLAY_INPUTS
    }
    feeds = [_RunFeed(run.log, BarBuffers()) for run in replay.runs]
    indexes = [
        {(e.candle.symbol, e.candle.interval, e.candle.open_time_utc): e for e in r.log}
        for r in replay.runs
    ]
    expected: dict[int, dict[str, object]] = {}
    waiting: list[_Windowed] = []
    recorded: list[tuple[RuntimeRecord, Candle, dict[str, object], str]] = []
    stages: Counter[str] = Counter()
    skipped = 0
    for record in bars:
        bar, surface = record.payload.get("bar"), record.payload.get("surface")
        label = f"{_pair(record)} close {record.occurred_at_utc.isoformat()}"
        if not isinstance(bar, Mapping) or not isinstance(surface, Mapping):
            problems.append(f"{label}: the record carries no bar or no surface to compare")
            continue
        try:
            candle = _candle_from(bar)
        except ValueError as exc:
            problems.append(f"{label}: {exc}")
            continue
        live = dict(surface)
        slot = len(recorded)
        recorded.append((record, candle, live, label))
        stages[str(live.get("stage"))] += 1
        if live.get("stage") == "feed_gate" and live.get("reason_code") in _PIPELINE_ONLY_GATES:
            skipped += 1
            continue
        tick = _read_time(record.payload, "tick_time_utc")
        if tick is None:
            problems.append(f"{label}: the record carries no tick time")
            continue
        run = _run_index([r.started_at_utc for r in replay.runs], tick)
        if run is None:
            problems.append(f"{label}: no recorded run holds its tick time {tick.isoformat()}")
            continue
        entry = indexes[run].get((candle.symbol, candle.interval, candle.open_time_utc))
        if entry is None or entry.candle != candle or entry.source != "LIVE_WS":
            problems.append(f"{label}: the bar is not a LIVE_WS entry of its run's acceptance log")
            continue
        if candle.interval == CONTEXT_INTERVAL:
            expected[slot] = dict(context_record(candle).to_dict())
            continue
        if candle.interval != SETUP_INTERVAL:
            problems.append(f"{label}: unsupported interval {candle.interval!r}")
            continue
        stale = check_feed_freshness({"T": _close_ms(candle.close_time_utc)}, tick)
        if stale is not None:
            expected[slot] = dict(gate_record(candle, stale).to_dict())
            continue
        key = (candle.symbol, candle.interval, candle.close_time_utc)
        inputs = inputs_by_key.get(key)
        cut = entry.accept_seq
        if inputs is not None:
            try:
                cut = window_accept_seq_of(json.loads(inputs.payload_json))
            except ReplayInputsError as exc:
                problems.append(f"{label}: replay inputs unreadable: {exc}")
                continue
        else:
            for other in replay.runs[run].log:
                if (
                    other.fetched_for_close_utc == candle.close_time_utc
                    and other.candle.symbol == candle.symbol
                ):
                    cut = max(cut, other.accept_seq)
        waiting.append(_Windowed(slot, record, candle, live, label, run, cut, inputs))

    for item in sorted(waiting, key=lambda w: (w.run, w.cut, w.candle.close_time_utc)):
        feed = feeds[item.run]
        error = _advance(feed, item.cut)
        if error is not None:
            problems.append(f"{item.label}: {error}")
            continue
        setup_window = feed.buffers.setup_window(item.candle.symbol, item.candle.close_time_utc)
        context_window = feed.buffers.context_window(item.candle.symbol, item.candle.close_time_utc)
        context = None
        if item.inputs is not None:
            payload = json.loads(item.inputs.payload_json)
            try:
                context = context_from_inputs(
                    payload, symbol=item.candle.symbol, parameter_set=parameter_set
                )
            except ReplayInputsError as exc:
                problems.append(f"{item.label}: replay inputs refused: {exc}")
                continue
            for name, window in (
                ("setup_window_digest", setup_window),
                ("context_window_digest", context_window),
            ):
                if payload.get(name) != window_digest(window):
                    problems.append(
                        f"{item.label}: {name} differs: the window rebuilt from the acceptance "
                        "log is not the window the runtime evaluated"
                    )
                    context = None
                    break
            if context is None:
                continue

        def resolve(found: BarContext | None = context) -> BarContext:
            if found is None:
                raise _NoRecordedInputs
            return found

        try:
            observed = observe_closed_bar(item.candle, setup_window, context_window, resolve)
        except _NoRecordedInputs:
            if item.live.get("stage") in BAR_STAGES:
                problems.append(f"{item.label}: an evaluated bar has no recorded replay inputs")
            else:
                problems.append(
                    f"{item.label}: the replay reaches the risk stage but no replay inputs were "
                    f"recorded (recorded stage {item.live.get('stage')} "
                    f"{item.live.get('reason_code')})"
                )
            continue
        except ValueError as exc:
            problems.append(f"{item.label}: the replay refused the bar: {exc}")
            continue
        expected[item.slot] = dict(observed.to_dict())

    compared = 0
    mismatches: list[str] = []
    for slot, (_record, _candle, live, label) in enumerate(recorded):
        want = expected.get(slot)
        if want is None:
            continue
        compared += 1
        differing = [k for k in sorted({*live, *want}) if live.get(k) != want.get(k)]
        if differing:
            mismatches.append(
                f"{label}: differs in {', '.join(differing)} (recorded stage "
                f"{live.get('stage')} {live.get('reason_code')}, replay stage "
                f"{want.get('stage')} {want.get('reason_code')})"
            )
    heartbeat_keys = {(r.symbol, r.interval, r.occurred_at_utc) for r in bars}
    orphans = [
        f"orphan replay-inputs record for {key[0]} {key[1]} close {key[2].isoformat()}: no "
        "heartbeat follows (a crash between the two writes; the close is a CRASH gap); not compared"
        for key in sorted(inputs_by_key, key=lambda k: (str(k[0]), str(k[1]), k[2]))
        if key not in heartbeat_keys
    ]
    by_stage = ", ".join(f"{k}={v}" for k, v in sorted(stages.items()))
    logged = sum(len(run.log) for run in replay.runs)
    summary = [
        f"{compared} recorded surface record(s) compared with the replay of {logged} logged "
        f"bar(s) in {len(replay.runs)} run(s) and {len(recorded)} recorded bar(s); "
        f"tolerance {PARITY_TOLERANCE}, {len(mismatches)} difference(s)",
        f"recorded stages: {by_stage or 'none'}; pipeline-only gate records not compared: "
        f"{skipped}",
    ]
    failed = len(mismatches) > PARITY_TOLERANCE or bool(problems)
    evidence = [
        *summary,
        *problems[:_PROBLEM_LIMIT],
        *mismatches[:_PROBLEM_LIMIT],
        *orphans[:_PROBLEM_LIMIT],
    ]
    if len(problems) > _PROBLEM_LIMIT:
        evidence.append(f"... and {len(problems) - _PROBLEM_LIMIT} more problem(s)")
    if len(mismatches) > _PROBLEM_LIMIT:
        evidence.append(f"... and {len(mismatches) - _PROBLEM_LIMIT} more difference(s)")
    return CriterionResult(_PARITY_NAME, not failed, tuple(evidence))


def _runtime_group(inputs: _RuntimeInputs) -> CriterionGroup:
    return CriterionGroup(
        "runtime health",
        (
            _coverage_criterion(inputs),
            _ceiling_criterion(inputs),
            _gaps_explained(inputs),
            _restart_warmup(inputs),
            _no_duplicate_signal(inputs),
            _no_missing_row(inputs),
            _no_test_signal(inputs),
            _one_epoch(inputs),
            parity_criterion(inputs.records, inputs.parity),
        ),
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
    backfill_rule: BackfillRule,
    parity: ParityReplay | ParityUnavailable | None,
) -> TrialEvaluation:
    """Judge the manifest's epoch from one verified bundle.

    `thresholds` are the user-ratified numbers (O-07) and `cron` is the recorded schedule of the
    freeze workflow; neither has a default. `symbols` are the scope of the ratified configuration:
    every closed 1h and 4h bar of each must be accounted for. `backfill_rule` is the user's Q-D
    option read from its decision file (`read_backfill_rule`). `parity` is the replay built from
    the bundle (`build_parity_replay`) or the test seam; None or `ParityUnavailable` means parity
    is NOT EVALUATED and the criterion fails (a missing comparison is never a PASS).
    The grace is passed only to `freeze_evidence_report`, where it can never turn a gap into CLEAN.
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
        host_ticks=bundle.host_ticks,
        pinned_epoch_id=bundle.pinned.epoch_id,
        pinned_hash=bundle.pinned.parameter_set_hash,
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
        diff_records=bundle.diff_records + bundle.host_diff_records,
        report=freeze,
        in_window_gap_records=in_window_gaps,
    )
    foreign = Counter(
        r.epoch_id
        for r in bundle.records
        if r.epoch_id != bundle.epoch_id and pin < r.occurred_at_utc <= end
    )
    runtime_inputs = _RuntimeInputs(
        epoch_id=bundle.epoch_id,
        window_start_utc=start,
        window_end_utc=end,
        symbols=tuple(symbols),
        records=mine,
        coverage=coverage,
        backfill_rule=backfill_rule,
        parity=parity,
        other_epoch_records_in_window=tuple(sorted(foreign.items())),
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


# --------------------------------------------------------------------------- #
# Requirement closure rule (ROADMAP SC9, D061 item J).
# --------------------------------------------------------------------------- #

# ROADMAP SC9 and D061 item J: PAPER-01 completes when criteria SC1, SC2 and SC7 hold, PAPER-02
# when SC3 and SC5 hold. PAPER-03 asks for a 3 to 6 month wall-clock observation with no tuning and
# stays Pending until Phase 26. Nothing here closes on fake-level evidence (phase 7 was closed with
# these requirements unmet, so Phase 16 must not repeat that).
REQUIREMENT_CRITERIA: Mapping[str, tuple[str, ...]] = {
    "PAPER-01": ("SC1", "SC2", "SC7"),
    "PAPER-02": ("SC3", "SC5"),
}
PAPER_03 = "PAPER-03"
PAPER_03_STATUS = "Pending, Phase 26"
STATUS_CLOSABLE = "CLOSABLE"
STATUS_NOT_CLOSABLE = "NOT CLOSABLE"

# What each criterion needs: a list of slots, each slot the proof classes that can fill it. A
# criterion holds only when every slot has at least one item. CODE can fill a slot only where the
# plan names the code-level contract test as a companion (SC2); it never replaces a REAL slot.
CRITERION_SLOTS: Mapping[str, tuple[tuple[ProofClass, ...], ...]] = {
    "SC1": ((ProofClass.REAL_SOAK,),),
    "SC2": ((ProofClass.CODE,), (ProofClass.REAL_SMOKE,)),
    "SC3": ((ProofClass.REAL_REHEARSAL, ProofClass.REAL_SOAK),),
    "SC5": ((ProofClass.REAL_REHEARSAL, ProofClass.REAL_SOAK),),
    "SC7": ((ProofClass.REAL_SMOKE,),),
}
_SLOT_NOTE: Mapping[ProofClass, str] = {ProofClass.CODE: " (the code-level contract test)"}
_REAL_CLASSES = frozenset({ProofClass.REAL_SMOKE, ProofClass.REAL_REHEARSAL, ProofClass.REAL_SOAK})

# Sub-claims of SC5 that one rehearsal cannot exercise: they stay CODE and PostgreSQL proof only,
# and are printed so the user's O-11 (v) declaration sees them. They never turn a FAIL into a PASS.
SC5_CODE_ONLY_SUBCLAIMS: tuple[str, ...] = (
    "SKIP journaling",
    "CANCEL journaling",
    "expiry journaling",
)

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_SMOKE_CLASSES = (ProofClass.FAKE, ProofClass.REAL_SMOKE)
_REHEARSAL_CLASSES = (ProofClass.FAKE, ProofClass.REAL_REHEARSAL)


@dataclass(frozen=True)
class EvidenceItem:
    """One piece of evidence for a criterion: where it came from and the hash of its file.

    Build items with `bundle_evidence_item`, `smoke_evidence_item`, `rehearsal_evidence_item` and
    `code_evidence_item`: each takes the proof class from the source of the evidence and none has a
    parameter that sets it.
    """

    criterion: str
    proof_class: ProofClass
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if self.criterion not in CRITERION_SLOTS:
            raise ValueError(
                f"unknown criterion {self.criterion!r}; expected one of {list(CRITERION_SLOTS)}"
            )
        if not isinstance(self.proof_class, ProofClass):
            raise ValueError("proof_class must be a ProofClass")
        if not isinstance(self.path, str) or self.path == "":
            raise ValueError("path must be a non-empty string")
        if not isinstance(self.sha256, str) or _SHA256_HEX.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must be 64 lowercase hex characters")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_proof_class(path: Path, allowed: Sequence[ProofClass]) -> ProofClass:
    """The `proof_class` field of an evidence file written by its own script."""
    try:
        data = json.loads(path.read_bytes())
    except ValueError:
        raise ValueError(f"{path.name} is not valid JSON") from None
    claimed = data.get("proof_class") if isinstance(data, dict) else None
    for proof_class in allowed:
        if claimed == proof_class.value:
            return proof_class
    raise ValueError(
        f"{path.name}: proof_class must be one of {[p.value for p in allowed]}, got {claimed!r}"
    )


def _require_criterion(criterion: str, allowed: Sequence[str], what: str) -> None:
    if criterion not in allowed:
        raise ValueError(
            f"{what} evidence cannot support criterion {criterion!r}; use one of {list(allowed)}"
        )


def bundle_evidence_item(bundle: EvidenceBundle, evaluation: TrialEvaluation) -> EvidenceItem:
    """SC1 evidence from a trial bundle: its proof class follows the manifest source only.

    A trial evaluation that failed is not evidence of anything; the item is refused.
    """
    if evaluation.epoch_id != bundle.epoch_id or evaluation.bundle_source != bundle.source:
        raise ValueError("the evaluation does not belong to this bundle")
    if not evaluation.passed:
        raise ValueError("a failed trial evaluation is not evidence for SC1")
    manifest = bundle.path / MANIFEST_NAME
    return EvidenceItem(
        criterion="SC1",
        proof_class=bundle_proof_class(bundle.source),
        path=str(manifest),
        sha256=_file_sha256(manifest),
    )


def smoke_evidence_item(criterion: str, path: Path) -> EvidenceItem:
    """Live-smoke evidence (SC2, SC7): the file's own `proof_class` (FAKE or REAL_SMOKE)."""
    _require_criterion(criterion, ("SC2", "SC7"), "smoke")
    return EvidenceItem(
        criterion=criterion,
        proof_class=_json_proof_class(path, _SMOKE_CLASSES),
        path=str(path),
        sha256=_file_sha256(path),
    )


def rehearsal_evidence_item(criterion: str, path: Path) -> EvidenceItem:
    """Rehearsal evidence (SC3, SC5): the file's own `proof_class` (REAL_REHEARSAL only in live)."""
    _require_criterion(criterion, ("SC3", "SC5"), "rehearsal")
    return EvidenceItem(
        criterion=criterion,
        proof_class=_json_proof_class(path, _REHEARSAL_CLASSES),
        path=str(path),
        sha256=_file_sha256(path),
    )


def code_evidence_item(criterion: str, path: Path) -> EvidenceItem:
    """A code-level proof: a test file. Supporting evidence, never sufficient on its own."""
    if not (path.name.startswith("test_") and path.suffix == ".py"):
        raise ValueError(f"{path.name} is not a test file (test_*.py): CODE proof comes from tests")
    return EvidenceItem(
        criterion=criterion,
        proof_class=ProofClass.CODE,
        path=str(path),
        sha256=_file_sha256(path),
    )


@dataclass(frozen=True)
class CriterionClosure:
    """One criterion: whether every slot it needs is filled, and the items behind it."""

    criterion: str
    satisfied: bool
    real_items: tuple[EvidenceItem, ...]
    supporting_items: tuple[EvidenceItem, ...]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class RequirementClosure:
    """One requirement: CLOSABLE, NOT CLOSABLE, or (PAPER-03) Pending, Phase 26."""

    requirement: str
    closable: bool
    status: str
    criteria: tuple[CriterionClosure, ...]


@dataclass(frozen=True)
class ClosureVerdict:
    """The closure state of PAPER-01, PAPER-02 and PAPER-03, with the disclosures to print."""

    requirements: tuple[RequirementClosure, ...]
    disclosures: tuple[str, ...]

    def render(self) -> str:
        lines = ["Requirement closure (ROADMAP SC9, D061 item J)"]
        for requirement in self.requirements:
            lines.append(f"{requirement.requirement}: {requirement.status}")
            for criterion in requirement.criteria:
                state = "satisfied" if criterion.satisfied else "NOT satisfied"
                lines.append(f"    {criterion.criterion}: {state}")
                for item in (*criterion.real_items, *criterion.supporting_items):
                    role = "real" if item.proof_class in _REAL_CLASSES else "supporting only"
                    lines.append(
                        f"        {item.proof_class.value} ({role}) {item.path} "
                        f"sha256 {item.sha256}"
                    )
                lines.extend(f"        missing: {text}" for text in criterion.missing)
        lines.extend(self.disclosures)
        return "\n".join(lines)


def _class_names(classes: Sequence[ProofClass]) -> str:
    return " or ".join(c.value for c in classes)


def _criterion_closure(criterion: str, items: Sequence[EvidenceItem]) -> CriterionClosure:
    mine = sorted(
        (i for i in items if i.criterion == criterion),
        key=lambda i: (i.proof_class.value, i.path, i.sha256),
    )
    missing: list[str] = []
    for slot in CRITERION_SLOTS[criterion]:
        if not any(i.proof_class in slot for i in mine):
            note = _SLOT_NOTE.get(slot[0], "") if len(slot) == 1 else ""
            missing.append(f"a {_class_names(slot)} item for {criterion}{note}")
    return CriterionClosure(
        criterion=criterion,
        satisfied=not missing,
        real_items=tuple(i for i in mine if i.proof_class in _REAL_CLASSES),
        supporting_items=tuple(i for i in mine if i.proof_class not in _REAL_CLASSES),
        missing=tuple(missing),
    )


def closure_verdict(items: Iterable[EvidenceItem]) -> ClosureVerdict:
    """Which requirements are closable on the evidence given (pure, order independent).

    PAPER-01 and PAPER-02 are CLOSABLE only when every criterion they depend on has its REAL
    evidence (see `CRITERION_SLOTS`); FAKE and CODE items are listed as supporting and never
    sufficient. PAPER-03 is never closable here.
    """
    given = tuple(items)
    for item in given:
        if not isinstance(item, EvidenceItem):
            raise TypeError("closure_verdict takes EvidenceItem values built from their sources")
    requirements: list[RequirementClosure] = []
    for requirement, criteria in REQUIREMENT_CRITERIA.items():
        closures = tuple(_criterion_closure(c, given) for c in criteria)
        closable = all(c.satisfied for c in closures)
        requirements.append(
            RequirementClosure(
                requirement=requirement,
                closable=closable,
                status=STATUS_CLOSABLE if closable else STATUS_NOT_CLOSABLE,
                criteria=closures,
            )
        )
    requirements.append(RequirementClosure(PAPER_03, False, PAPER_03_STATUS, ()))
    disclosures = tuple(
        f"SC5 sub-claim {subclaim}: CODE and PG proof only, disclosed (a rehearsal cannot "
        "exercise it; for the user's O-11 (v) declaration; it never turns a FAIL into a PASS)"
        for subclaim in SC5_CODE_ONLY_SUBCLAIMS
    )
    return ClosureVerdict(requirements=tuple(requirements), disclosures=disclosures)


__all__ = [
    "AUXILIARY_HEADING",
    "DECISION_LABEL",
    "EVALUATED_INTERVALS",
    "MIN_COVERAGE_FRACTION",
    "OBSERVATIONS_HEADING",
    "PAPER_03_STATUS",
    "PARITY_TOLERANCE",
    "REQUIREMENT_CRITERIA",
    "RESTART_RULE",
    "SC5_CODE_ONLY_SUBCLAIMS",
    "TIME_OF_DAY_LABEL",
    "TRIAL_CALENDAR_DAYS",
    "BackfillRule",
    "ClosureVerdict",
    "CriterionClosure",
    "CriterionGroup",
    "CriterionResult",
    "EvidenceItem",
    "NO_REPLAY_INPUTS_REASON",
    "ParityReplay",
    "ParityUnavailable",
    "ReplayRun",
    "ProofClass",
    "RequirementClosure",
    "TimeOfDayDistribution",
    "TrialEvaluation",
    "bundle_proof_class",
    "bundle_evidence_item",
    "closure_verdict",
    "code_evidence_item",
    "evaluate_trial",
    "build_parity_replay",
    "has_recorded_replay_inputs",
    "parity_criterion",
    "read_backfill_rule",
    "rehearsal_evidence_item",
    "smoke_evidence_item",
]
