"""Runtime coverage evidence (Phase 16, plan 16-15, D-07, REV-01, REV-17).

Task 1 pins the coverage arithmetic: the whole fixed trial window is the denominator, only
HEALTHY time is covered, every uncovered interval carries a reason code, and the longest
continuous non-HEALTHY block is reported against a ceiling that has no default.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.paper.coverage import (
    CoverageReport,
    HealthInterval,
    coverage_report,
)
from src.paper.vocabulary import GapReason, HealthState

WINDOW_START = datetime(2026, 11, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 11, 15, tzinfo=UTC)
CEILING = 4 * 3600


def _healthy(start: datetime, end: datetime) -> HealthInterval:
    return HealthInterval(start_utc=start, end_utc=end, state=HealthState.HEALTHY, reason=None)


def _down(
    start: datetime,
    end: datetime,
    reason: GapReason,
    state: HealthState = HealthState.DISCONNECTED,
) -> HealthInterval:
    return HealthInterval(start_utc=start, end_utc=end, state=state, reason=reason)


def _tracer_intervals() -> list[HealthInterval]:
    """HEALTHY all window long except a 30-minute planned restart and a 2-hour disconnect."""
    restart_start = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
    restart_end = restart_start + timedelta(minutes=30)
    drop_start = datetime(2026, 11, 8, 4, 0, tzinfo=UTC)
    drop_end = drop_start + timedelta(hours=2)
    return [
        _healthy(WINDOW_START, restart_start),
        _down(restart_start, restart_end, GapReason.PLANNED_RESTART),
        _healthy(restart_end, drop_start),
        _down(drop_start, drop_end, GapReason.WS_DISCONNECTED),
        _healthy(drop_end, WINDOW_END),
    ]


def _report(intervals: list[HealthInterval], ceiling: int = CEILING) -> CoverageReport:
    return coverage_report(
        window_start_utc=WINDOW_START,
        window_end_utc=WINDOW_END,
        intervals=intervals,
        continuous_uncovered_ceiling_seconds=ceiling,
    )


def test_tracer_14_day_window_with_one_restart_and_one_disconnect() -> None:
    """Test 1: 336 h window, 333.5 h covered, criterion PASS, derived minimum 319.2 h labelled."""
    report = _report(_tracer_intervals())

    assert report.window_hours == Decimal("336")
    assert report.covered_hours == Decimal("333.5")
    assert report.covered_fraction == Decimal("333.5") / Decimal("336")
    assert report.criterion_min_fraction == Decimal("0.95")
    assert report.coverage_pass is True
    assert report.derived_minimum_covered_hours == Decimal("319.2")
    assert "DERIVED" in report.derived_minimum_label
    assert "not a threshold" in report.derived_minimum_label
    assert all(isinstance(v, Decimal) for v in (report.covered_hours, report.covered_fraction))


def test_coverage_below_the_criterion_fails() -> None:
    """The 95 percent criterion is a real comparison: 10 uncovered hours of 336 passes, 20 fails."""
    start = datetime(2026, 11, 2, tzinfo=UTC)
    ok = _report(
        [
            _healthy(WINDOW_START, start),
            _down(start, start + timedelta(hours=10), GapReason.CRASH),
            _healthy(start + timedelta(hours=10), WINDOW_END),
        ],
        ceiling=24 * 3600,
    )
    bad = _report(
        [
            _healthy(WINDOW_START, start),
            _down(start, start + timedelta(hours=20), GapReason.CRASH),
            _healthy(start + timedelta(hours=20), WINDOW_END),
        ],
        ceiling=24 * 3600,
    )
    assert ok.coverage_pass is True
    assert bad.coverage_pass is False
    assert bad.covered_hours == Decimal("316")


def test_exactly_at_the_criterion_passes() -> None:
    """The boundary is inclusive and exact: 319.2 covered hours is 95 percent, no rounding."""
    start = datetime(2026, 11, 2, tzinfo=UTC)
    exact_gap = timedelta(hours=16, minutes=48)  # 336 - 319.2
    report = _report(
        [
            _healthy(WINDOW_START, start),
            _down(start, start + exact_gap, GapReason.MAINTENANCE),
            _healthy(start + exact_gap, WINDOW_END),
        ],
        ceiling=24 * 3600,
    )
    assert report.covered_hours == Decimal("319.2")
    assert report.coverage_pass is True


def test_an_explained_gap_is_still_uncovered_and_missing_time_is_unknown() -> None:
    """Test 2: a reason never earns coverage (REV-01); time with no interval is UNKNOWN."""
    # Only the first 100 hours are described; the rest has no interval at all.
    described_end = WINDOW_START + timedelta(hours=100)
    restart = _down(
        WINDOW_START + timedelta(hours=10),
        WINDOW_START + timedelta(hours=12),
        GapReason.PLANNED_RESTART,
    )
    report = _report(
        [
            _healthy(WINDOW_START, WINDOW_START + timedelta(hours=10)),
            restart,
            _healthy(WINDOW_START + timedelta(hours=12), described_end),
        ],
        ceiling=1000 * 3600,
    )

    assert report.covered_hours == Decimal("98")
    reasons = [u.reason for u in report.uncovered]
    assert reasons == [GapReason.PLANNED_RESTART, GapReason.UNKNOWN]
    assert report.uncovered[0].start_utc == restart.start_utc
    assert report.uncovered[0].end_utc == restart.end_utc
    assert report.uncovered[1].start_utc == described_end
    assert report.uncovered[1].end_utc == WINDOW_END
    assert report.coverage_pass is False


def test_every_uncovered_interval_carries_a_reason_code() -> None:
    """A non-HEALTHY interval without a reason is reported with reason UNKNOWN, never None."""
    gap_start = datetime(2026, 11, 5, tzinfo=UTC)
    degraded_no_reason = HealthInterval(
        start_utc=gap_start,
        end_utc=gap_start + timedelta(hours=1),
        state=HealthState.DEGRADED,
        reason=None,
    )
    report = _report(
        [
            _healthy(WINDOW_START, gap_start),
            degraded_no_reason,
            _healthy(gap_start + timedelta(hours=1), WINDOW_END),
        ]
    )
    assert [u.reason for u in report.uncovered] == [GapReason.UNKNOWN]
    assert all(isinstance(u.reason, GapReason) for u in report.uncovered)


def test_a_healthy_interval_may_not_carry_a_reason() -> None:
    with pytest.raises(ValueError, match="HEALTHY"):
        HealthInterval(
            start_utc=WINDOW_START,
            end_utc=WINDOW_START + timedelta(hours=1),
            state=HealthState.HEALTHY,
            reason=GapReason.UNKNOWN,
        )


def test_overlapping_and_unsorted_intervals_normalise_deterministically() -> None:
    """Test 3: the same set in any order gives the same report; non-HEALTHY wins an overlap."""
    a = _healthy(WINDOW_START, WINDOW_END)  # whole window healthy ...
    b = _down(
        datetime(2026, 11, 2, 0, 0, tzinfo=UTC),
        datetime(2026, 11, 2, 6, 0, tzinfo=UTC),
        GapReason.WS_DISCONNECTED,
    )  # ... but a disconnect overlaps it
    c = _down(
        datetime(2026, 11, 2, 4, 0, tzinfo=UTC),
        datetime(2026, 11, 2, 8, 0, tzinfo=UTC),
        GapReason.CRASH,
        HealthState.DEGRADED,
    )  # overlapping disconnect with a different reason
    first = _report([a, b, c])
    second = _report([c, a, b])
    third = _report(list(reversed([a, b, c])))

    assert first == second == third
    assert first.covered_hours == Decimal("328")
    # One continuous 8 h uncovered block, reasons in order of first appearance.
    assert first.longest_uncovered_block is not None
    assert first.longest_uncovered_block.length_seconds == Decimal(8 * 3600)
    # The overlap [04:00, 06:00) resolves to the more specific process-level reason (CRASH).
    by_reason = {u.reason: (u.start_utc, u.end_utc) for u in first.uncovered}
    assert by_reason[GapReason.WS_DISCONNECTED] == (
        datetime(2026, 11, 2, 0, 0, tzinfo=UTC),
        datetime(2026, 11, 2, 4, 0, tzinfo=UTC),
    )
    assert by_reason[GapReason.CRASH] == (
        datetime(2026, 11, 2, 4, 0, tzinfo=UTC),
        datetime(2026, 11, 2, 8, 0, tzinfo=UTC),
    )


def test_intervals_outside_the_window_are_clipped() -> None:
    """The denominator is the window; HEALTHY time outside it earns nothing."""
    report = _report([_healthy(WINDOW_START - timedelta(days=30), WINDOW_END + timedelta(days=30))])
    assert report.covered_hours == Decimal("336")
    assert report.covered_fraction == Decimal("1")


def test_naive_datetimes_raise() -> None:
    naive = datetime(2026, 11, 1)  # noqa: DTZ001 - the point of the test
    with pytest.raises(ValueError, match="UTC"):
        HealthInterval(
            start_utc=naive,
            end_utc=WINDOW_START + timedelta(hours=1),
            state=HealthState.HEALTHY,
            reason=None,
        )
    with pytest.raises(ValueError, match="UTC"):
        coverage_report(
            window_start_utc=naive,
            window_end_utc=WINDOW_END,
            intervals=[],
            continuous_uncovered_ceiling_seconds=CEILING,
        )
    with pytest.raises(ValueError, match="UTC"):
        coverage_report(
            window_start_utc=WINDOW_START,
            window_end_utc=datetime(2026, 11, 15),  # noqa: DTZ001
            intervals=[],
            continuous_uncovered_ceiling_seconds=CEILING,
        )


def test_an_empty_or_reversed_window_raises() -> None:
    with pytest.raises(ValueError, match="window"):
        coverage_report(
            window_start_utc=WINDOW_END,
            window_end_utc=WINDOW_START,
            intervals=[],
            continuous_uncovered_ceiling_seconds=CEILING,
        )


def test_longest_continuous_block_is_reported_against_the_ceiling() -> None:
    """Test 4: contiguous uncovered pieces with different reasons form one continuous block."""
    t0 = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)
    intervals = [
        _healthy(WINDOW_START, t0),
        _down(t0, t0 + timedelta(hours=1), GapReason.PLANNED_RESTART),
        _down(
            t0 + timedelta(hours=1),
            t0 + timedelta(hours=3),
            GapReason.WS_DISCONNECTED,
        ),
        _healthy(t0 + timedelta(hours=3), t0 + timedelta(hours=5)),
        _down(t0 + timedelta(hours=5), t0 + timedelta(hours=6), GapReason.CRASH),
        _healthy(t0 + timedelta(hours=6), WINDOW_END),
    ]
    over = _report(intervals, ceiling=2 * 3600)
    block = over.longest_uncovered_block
    assert block is not None
    assert block.start_utc == t0
    assert block.end_utc == t0 + timedelta(hours=3)
    assert block.length_seconds == Decimal(3 * 3600)
    assert block.reasons == (GapReason.PLANNED_RESTART, GapReason.WS_DISCONNECTED)
    assert over.ceiling_seconds == 2 * 3600
    assert over.ceiling_pass is False

    at_ceiling = _report(intervals, ceiling=3 * 3600)
    assert at_ceiling.ceiling_pass is True  # "exceeds" means strictly longer than the ceiling


def test_no_uncovered_time_has_no_block_and_passes_the_ceiling() -> None:
    report = _report([_healthy(WINDOW_START, WINDOW_END)])
    assert report.longest_uncovered_block is None
    assert report.ceiling_pass is True
    assert report.uncovered == ()


def test_the_ceiling_is_a_required_input_with_no_default() -> None:
    """Test 4 (negative): calling without the user-ratified ceiling raises TypeError (O-07)."""
    with pytest.raises(TypeError):
        coverage_report(  # type: ignore[call-arg]
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            intervals=[],
        )


@pytest.mark.parametrize("bad", [0, -1, True, "3600"])
def test_a_non_positive_or_non_integer_ceiling_is_refused(bad: object) -> None:
    with pytest.raises(ValueError, match="ceiling"):
        coverage_report(
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            intervals=[],
            continuous_uncovered_ceiling_seconds=bad,  # type: ignore[arg-type]
        )


def test_the_report_is_frozen_and_input_is_not_mutated() -> None:
    intervals = _tracer_intervals()
    snapshot = list(intervals)
    report = _report(intervals)
    assert intervals == snapshot
    with pytest.raises(AttributeError):
        report.covered_hours = Decimal("1")  # type: ignore[misc]
