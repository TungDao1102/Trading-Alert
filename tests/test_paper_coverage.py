"""Runtime coverage evidence (Phase 16, plan 16-15, D-07, REV-01, REV-17).

Task 1 pins the coverage arithmetic: the whole fixed trial window is the denominator, only
HEALTHY time is covered, every uncovered interval carries a reason code, and the longest
continuous non-HEALTHY block is reported against a ceiling that has no default.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import random
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.paper import coverage as coverage_module
from src.paper.coverage import (
    CoverageReport,
    HealthInterval,
    HealthThresholds,
    coverage_report,
    derive_health_intervals,
)
from src.paper.vocabulary import GapReason, HealthState, RuntimeEventType

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


# --------------------------------------------------------------------------- #
# Task 2: derive_health_intervals from recorded runtime events.
# --------------------------------------------------------------------------- #

EPOCH = "e" * 64
OTHER_EPOCH = "f" * 64
PAIR = ("BTCUSDT", "1h")


def _ts(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, 1, hour, minute, second, tzinfo=UTC)


@dataclasses.dataclass(frozen=True)
class _Rec:
    event_type: RuntimeEventType
    epoch_id: str
    symbol: str | None
    interval: str | None
    occurred_at_utc: datetime
    payload: Mapping[str, object]


def _start(at: datetime, epoch: str = EPOCH) -> _Rec:
    return _Rec(RuntimeEventType.RUNTIME_START, epoch, None, None, at, {})


def _stop(at: datetime, epoch: str = EPOCH) -> _Rec:
    return _Rec(RuntimeEventType.RUNTIME_STOP, epoch, None, None, at, {})


def _drop(at: datetime, epoch: str = EPOCH) -> _Rec:
    return _Rec(RuntimeEventType.WS_DISCONNECT, epoch, None, None, at, {})


def _reconnect(at: datetime, epoch: str = EPOCH) -> _Rec:
    return _Rec(RuntimeEventType.WS_RECONNECT, epoch, None, None, at, {})


def _close_of(hour: int) -> datetime:
    """Close time (exchange convention: open + interval - 1 ms) of the 1h bar ending at `hour`."""
    return _ts(hour) - timedelta(milliseconds=1)


def _bar(hour: int, *, delay_seconds: int = 2, epoch: str = EPOCH, source: str = "LIVE_WS") -> _Rec:
    tick = _ts(hour) + timedelta(seconds=delay_seconds)
    return _Rec(
        RuntimeEventType.PAPER_BAR_PROCESSED,
        epoch,
        PAIR[0],
        PAIR[1],
        _close_of(hour),
        {"source": source, "tick_time_utc": tick.isoformat()},
    )


def _gap(hour: int, reason: GapReason) -> _Rec:
    return _Rec(
        RuntimeEventType.PAPER_GAP,
        EPOCH,
        PAIR[0],
        PAIR[1],
        _ts(hour, 0, 30),
        {"expected_close_utc": _close_of(hour).isoformat(), "reason": reason.value},
    )


def _tick_stats(at: datetime, *, duration_ms: int = 5) -> _Rec:
    return _Rec(
        RuntimeEventType.PAPER_TICK_STATS,
        EPOCH,
        None,
        None,
        at,
        {"duration_ms": duration_ms},
    )


def _declared(at: datetime, state: HealthState, reason: GapReason | None = None) -> _Rec:
    payload: dict[str, object] = {"state": state.value}
    if reason is not None:
        payload["reason"] = reason.value
    return _Rec(RuntimeEventType.HEALTH_STATE_CHANGED, EPOCH, None, None, at, payload)


THRESHOLDS = HealthThresholds(
    max_ws_message_silence_seconds=7200,
    max_closed_bar_lateness_seconds=600,
    continuous_uncovered_ceiling_seconds=4 * 3600,
    freeze_tick_grace_seconds=300,
)
DERIVE_START = _ts(0)
DERIVE_END = _ts(6)


def _derive(
    records: list[_Rec],
    *,
    expected: tuple[tuple[str, str], ...] = (PAIR,),
    thresholds: HealthThresholds = THRESHOLDS,
    epoch: str = EPOCH,
) -> list[tuple[datetime, datetime, HealthState, GapReason | None]]:
    out = derive_health_intervals(
        records,
        epoch_id=epoch,
        window_start_utc=DERIVE_START,
        window_end_utc=DERIVE_END,
        intervals_expected=expected,
        thresholds=thresholds,
    )
    return [(i.start_utc, i.end_utc, i.state, i.reason) for i in out]


def _healthy_day(extra: list[_Rec] | None = None) -> list[_Rec]:
    base = [_start(_ts(0))] + [_bar(h) for h in range(1, 7)]
    return base + (extra or [])


STARTUP_WAIT = (_ts(0), _ts(1, 0, 2), HealthState.DISCONNECTED, GapReason.WS_RECONNECT_WINDOW)


def test_healthy_only_while_up_connected_fresh_and_every_bar_on_time() -> None:
    """Test 1: the start-up wait before the first live message is not HEALTHY; then HEALTHY."""
    assert _derive(_healthy_day()) == [
        STARTUP_WAIT,
        (_ts(1, 0, 2), _ts(6), HealthState.HEALTHY, None),
    ]


def test_a_ws_disconnect_until_reconnect_is_disconnected_with_its_reason() -> None:
    records = _healthy_day([_drop(_ts(3, 30)), _reconnect(_ts(3, 30, 40))])
    assert _derive(records) == [
        STARTUP_WAIT,
        (_ts(1, 0, 2), _ts(3, 30), HealthState.HEALTHY, None),
        (_ts(3, 30), _ts(3, 30, 40), HealthState.DISCONNECTED, GapReason.WS_DISCONNECTED),
        (_ts(3, 30, 40), _ts(6), HealthState.HEALTHY, None),
    ]


def test_an_unrecovered_disconnect_lasts_to_the_window_end() -> None:
    records = [_start(_ts(0)), _bar(1), _bar(2), _drop(_ts(2, 30))]
    result = _derive(records, expected=())
    assert result[-1] == (_ts(2, 30), _ts(6), HealthState.DISCONNECTED, GapReason.WS_DISCONNECTED)


def test_silence_longer_than_the_limit_is_degraded_from_the_limit_on() -> None:
    """Message evidence is the live closed bar, the tick stats record or a reconnect."""
    records = [_start(_ts(0)), _tick_stats(_ts(0, 5)), _tick_stats(_ts(1, 0))]
    result = _derive(records, expected=())
    assert result == [
        (_ts(0), _ts(0, 5), HealthState.DISCONNECTED, GapReason.WS_RECONNECT_WINDOW),
        (_ts(0, 5), _ts(3, 0), HealthState.HEALTHY, None),
        (_ts(3, 0), _ts(6), HealthState.DEGRADED, GapReason.UNKNOWN),
    ]


def test_a_late_bar_makes_the_wait_beyond_the_lateness_limit_degraded() -> None:
    """Bar 3 arrives 20 min after its close; the limit is 10 min: [close + 600 s, arrival)."""
    records = [_start(_ts(0))] + [_bar(h) for h in (1, 2, 4, 5, 6)] + [_bar(3, delay_seconds=1200)]
    expected_start = _close_of(3) + timedelta(seconds=600)
    assert _derive(records) == [
        STARTUP_WAIT,
        (_ts(1, 0, 2), expected_start, HealthState.HEALTHY, None),
        (expected_start, _ts(3, 20), HealthState.DEGRADED, GapReason.UNKNOWN),
        (_ts(3, 20), _ts(6), HealthState.HEALTHY, None),
    ]


def test_a_missing_bar_is_unhealthy_from_its_close_until_the_feed_is_seen_again() -> None:
    """A bar that never arrived: not healthy from its close to the next live arrival."""
    records = [_start(_ts(0))] + [_bar(h) for h in (1, 2, 4, 5, 6)]
    assert _derive(records) == [
        STARTUP_WAIT,
        (_ts(1, 0, 2), _close_of(3), HealthState.HEALTHY, None),
        (_close_of(3), _ts(4, 0, 2), HealthState.DEGRADED, GapReason.UNKNOWN),
        (_ts(4, 0, 2), _ts(6), HealthState.HEALTHY, None),
    ]


def test_a_recorded_gap_gives_the_missing_bar_its_reason() -> None:
    records = [_start(_ts(0))] + [_bar(h) for h in (1, 2, 4, 5, 6)]
    records.append(_gap(3, GapReason.EXCHANGE_NO_CANDLE))
    result = _derive(records)
    assert (
        _close_of(3),
        _ts(4, 0, 2),
        HealthState.DEGRADED,
        GapReason.EXCHANGE_NO_CANDLE,
    ) in result


def test_a_bar_that_did_not_come_from_the_live_stream_is_not_proof_of_a_live_feed() -> None:
    """A REST backfill row recovers history but does not show the live feed delivered it."""
    records = [_start(_ts(0))] + [_bar(h) for h in (1, 2, 4, 5, 6)]
    records.append(_bar(3, source="REST_BACKFILL", delay_seconds=30))
    result = _derive(records)
    assert (_close_of(3), _ts(4, 0, 2), HealthState.DEGRADED, GapReason.UNKNOWN) in result


def test_a_declared_non_healthy_state_is_kept_until_the_next_declaration() -> None:
    records = _healthy_day(
        [
            _declared(_ts(2, 30), HealthState.DEGRADED, GapReason.MAINTENANCE),
            _declared(_ts(3, 0), HealthState.HEALTHY),
        ]
    )
    assert _derive(records) == [
        STARTUP_WAIT,
        (_ts(1, 0, 2), _ts(2, 30), HealthState.HEALTHY, None),
        (_ts(2, 30), _ts(3, 0), HealthState.DEGRADED, GapReason.MAINTENANCE),
        (_ts(3, 0), _ts(6), HealthState.HEALTHY, None),
    ]


def test_a_stop_then_start_is_a_planned_restart_and_both_are_uncovered() -> None:
    """Test 2: STOP followed by START labels the gap PLANNED_RESTART."""
    records = [
        _start(_ts(0)),
        _bar(1),
        _bar(2),
        _stop(_ts(2, 20)),
        _start(_ts(3, 5)),
        _bar(4),
        _bar(5),
        _bar(6),
    ]
    assert _derive(records) == [
        STARTUP_WAIT,
        (_ts(1, 0, 2), _ts(2, 20), HealthState.HEALTHY, None),
        (_ts(2, 20), _ts(3, 5), HealthState.DISCONNECTED, GapReason.PLANNED_RESTART),
        (_ts(3, 5), _ts(4, 0, 2), HealthState.DISCONNECTED, GapReason.WS_RECONNECT_WINDOW),
        (_ts(4, 0, 2), _ts(6), HealthState.HEALTHY, None),
    ]


def test_a_start_with_no_preceding_stop_is_a_crash_after_the_last_evidence() -> None:
    """Test 2: START without a STOP is a CRASH from the last evidence of the previous run."""
    records = [
        _start(_ts(0)),
        _bar(1),
        _bar(2),
        _start(_ts(3, 10)),
        _bar(4),
        _bar(5),
        _bar(6),
    ]
    result = _derive(records)
    assert (_ts(2, 0, 2), _ts(3, 10), HealthState.DISCONNECTED, GapReason.CRASH) in result
    assert result[-1] == (_ts(4, 0, 2), _ts(6), HealthState.HEALTHY, None)


def test_time_before_the_first_start_is_process_down() -> None:
    records = [_start(_ts(2)), _bar(3), _bar(4), _bar(5), _bar(6)]
    result = _derive(records)
    assert result[0] == (_ts(0), _ts(2), HealthState.DISCONNECTED, GapReason.PROCESS_DOWN)


def test_a_stop_that_is_never_followed_by_a_start_is_process_down() -> None:
    records = [_start(_ts(0)), _bar(1), _bar(2), _stop(_ts(2, 30))]
    result = _derive(records, expected=())
    assert result[-1] == (_ts(2, 30), _ts(6), HealthState.DISCONNECTED, GapReason.PROCESS_DOWN)


def test_no_records_at_all_is_not_covered() -> None:
    assert _derive([]) == [(_ts(0), _ts(6), HealthState.DISCONNECTED, GapReason.PROCESS_DOWN)]


def test_health_thresholds_have_no_default_and_reject_non_positive_values() -> None:
    """Test 3: every field is required; zero, negative, bool and non-int are refused."""
    with pytest.raises(TypeError):
        HealthThresholds()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        HealthThresholds(  # type: ignore[call-arg]
            max_ws_message_silence_seconds=1,
            max_closed_bar_lateness_seconds=1,
            continuous_uncovered_ceiling_seconds=1,
        )
    for field in dataclasses.fields(HealthThresholds):
        assert field.default is dataclasses.MISSING, field.name
        assert field.default_factory is dataclasses.MISSING, field.name
    good = {
        "max_ws_message_silence_seconds": 1,
        "max_closed_bar_lateness_seconds": 1,
        "continuous_uncovered_ceiling_seconds": 1,
        "freeze_tick_grace_seconds": 1,
    }
    for name in good:
        for bad in (0, -5, True, 1.5, "10"):
            with pytest.raises(ValueError, match=name):
                HealthThresholds(**{**good, name: bad})  # type: ignore[arg-type]


def test_the_module_source_has_no_numeric_default_for_the_user_owned_names() -> None:
    """Test 3 (AST): no class field, parameter default or constant carries a numeric value."""
    source = Path(inspect.getsourcefile(coverage_module) or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "max_ws_message_silence_seconds",
        "max_closed_bar_lateness_seconds",
        "continuous_uncovered_ceiling_seconds",
        "freeze_tick_grace_seconds",
        "grace_seconds",
    }
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in names and node.value is not None:
                offenders.append(f"field {node.target.id}")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    offenders.append(f"assignment {target.id}")
        if isinstance(node, ast.FunctionDef):
            args = node.args
            positional = [*args.posonlyargs, *args.args]
            defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
            pairs = list(zip(positional, defaults, strict=True)) + list(
                zip(args.kwonlyargs, args.kw_defaults, strict=True)
            )
            for arg, default in pairs:
                if arg.arg in names and default is not None:
                    offenders.append(f"default {node.name}({arg.arg})")
    assert offenders == []


def test_derivation_is_deterministic_and_independent_of_input_order() -> None:
    """Test 4: the same records always give the same intervals, in whatever order they arrive."""
    records = _healthy_day(
        [_drop(_ts(3, 30)), _reconnect(_ts(3, 30, 40)), _gap(5, GapReason.CRASH)]
    )
    first = _derive(records)
    assert first == _derive(list(records))
    shuffled = list(records)
    random.Random(7).shuffle(shuffled)
    assert first == _derive(shuffled)
    assert first == _derive(list(reversed(records)))


def test_records_of_an_earlier_epoch_are_ignored_and_not_mutated() -> None:
    """Test 5 (REV-18): earlier-epoch runtime records never change the judged epoch's intervals."""
    mine = _healthy_day([_drop(_ts(3, 30)), _reconnect(_ts(3, 30, 40))])
    earlier = [
        _start(_ts(0), OTHER_EPOCH),
        _bar(1, epoch=OTHER_EPOCH),
        _drop(_ts(1, 30), OTHER_EPOCH),
        _stop(_ts(2), OTHER_EPOCH),
        _reconnect(_ts(5), OTHER_EPOCH),
        _bar(3, epoch=OTHER_EPOCH),
    ]
    combined = mine + earlier
    snapshot = list(combined)
    assert _derive(combined) == _derive(mine)
    assert combined == snapshot


def test_a_naive_record_time_is_refused() -> None:
    bad = _Rec(
        RuntimeEventType.RUNTIME_START,
        EPOCH,
        None,
        None,
        datetime(2026, 11, 1),  # noqa: DTZ001
        {},
    )
    with pytest.raises(ValueError, match="UTC"):
        _derive([bad])


def test_an_unknown_expected_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="interval"):
        _derive(_healthy_day(), expected=(("BTCUSDT", "7m"),))


def test_derived_intervals_feed_the_coverage_report() -> None:
    """The two functions compose: the start-up wait is the only uncovered stretch."""
    derived = derive_health_intervals(
        _healthy_day(),
        epoch_id=EPOCH,
        window_start_utc=DERIVE_START,
        window_end_utc=DERIVE_END,
        intervals_expected=(PAIR,),
        thresholds=THRESHOLDS,
    )
    report = coverage_report(
        window_start_utc=DERIVE_START,
        window_end_utc=DERIVE_END,
        intervals=derived,
        continuous_uncovered_ceiling_seconds=THRESHOLDS.continuous_uncovered_ceiling_seconds,
    )
    assert [u.reason for u in report.uncovered] == [GapReason.WS_RECONNECT_WINDOW]
    assert report.covered_hours == Decimal(5 * 3600 - 2) / Decimal(3600)
