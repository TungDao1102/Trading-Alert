"""Mark-hole coverage notes in windows with no strategy bar (Phase 14, plan 14-17).

Closes UAT test 6 (gap G-14-06) and the remaining half of review finding WR-09: a hole in
the 1m mark series inside the life of an open position, in a window that ends where the
symbol has no strategy bar, used to leave no trace. The design is ANNOTATE-ONLY (D-12, D-13,
D-33): the hole is recorded in the trade's `coverage_note` and nothing else changes: no event,
price, time, cost, `fallback_applied` flag or count of any trade. What a hole should do to a
trade (count, skip, invalidate) is open question OQ-1 and is NOT decided here.

Hand oracles (engine tracer, scripted LONG at 09:59:59.999, tick 0.10, stop 98.00):

    the symbol has only the scripted close and the data end as window ends, so it has no
    strategy bar in any window; the fill is the close of trade minute 10:01 (low 99.80 trades
    through the 100.00 limit); the fill-minute mark 10:01 is present, minutes 10:02-10:09 are
    walked, 10:10-10:19 are absent, 10:20 is the next walked minute, so the missing span is
    first 10:10 and last 10:19; the stop minute 10:40 has low 97.90 <= 98.00, so the exit is
    SL at 98.00 at 10:40:59.999 exactly as in the hole-free tracer
    (realized_pnl -34.0604352, see tests/test_backtest_engine.py).

Lifecycle oracle (UAT scenario): LONG filled at 10:01, mark minutes 11:20-11:29 missing, strategy
bars at hours 10 and 12 only, so the second window spans hours 11 and 12 and hour 11 has no
strategy bar; the missing span is first 11:20 and last 11:29, the position stays OPEN.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.backtest.engine import simulate
from src.backtest.lifecycle import PlanState, advance, finalize_at_data_end
from src.backtest.report import build
from src.backtest.validator import validate_trade_record
from src.risk.gating import evaluate_risk

from tests.backtest_case_helpers import (
    SYMBOL,
    flat_minutes,
    make_experiment_record,
    minute_row,
)
from tests.test_backtest_engine import tracer_case
from tests.test_backtest_exits import (
    BAR_12_CLOSE,
    SIGNAL_CLOSE,
    SL_THROUGH,
    at,
    close_of,
    flat_bar,
    long_fill_source,
    long_state,
    record_of,
    strategy_bar,
    walk_hours,
)

NOTE_PREFIX = "mark_price_1m_missing_from_"


def prefix(first: datetime, last: datetime) -> str:
    """Expected start of one continuity note (built from datetimes, never from arithmetic)."""
    return f"{NOTE_PREFIX}{first.isoformat()}_to_{last.isoformat()}"


HOLE_11_20 = {at(11, m) for m in range(20, 30)}
BARS_10_AND_12 = [flat_bar(10), flat_bar(12)]


def holed_tracer_case() -> dict[str, Any]:
    """The engine tracer with mark minutes 10:10-10:19 left out of the series."""
    mark = [
        *flat_minutes(SYMBOL, at(10, 0), 10, "100.00", kind="mark"),
        *flat_minutes(SYMBOL, at(10, 20), 20, "100.00", kind="mark"),
        minute_row(SYMBOL, at(10, 40), "98.50", "98.60", "97.90", "98.20", kind="mark"),
    ]
    return tracer_case(mark_minutes=mark)


def build_report(trades: list[dict[str, Any]]) -> Any:
    return build(
        experiment_record=make_experiment_record(experiment_id="0" * 64, notes="14-17 tracer"),
        trade_records=trades,
        bootstrap_seed=1,
        resamples=100,
        probable=Decimal("0.1"),
        universe_tags=None,
        baseline_summaries=None,
        built_at_utc=datetime(2026, 9, 26, 12, 0, tzinfo=UTC),
    )


def without_note(trade: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in trade.items() if key != "coverage_note"}


# --------------------------------------------------------------------------- #
# Task 1 (tracer): engine -> trade note -> report.
# --------------------------------------------------------------------------- #


def test_tracer_mark_hole_in_a_bar_less_window_is_noted_and_reaches_the_report() -> None:
    clean = simulate(tracer_case(), risk_fn=evaluate_risk)
    holed = simulate(holed_tracer_case(), risk_fn=evaluate_risk)

    assert len(holed["trades"]) == 1
    trade = holed["trades"][0]
    note = trade["coverage_note"]
    assert note is not None
    assert note.startswith(prefix(at(10, 10), at(10, 19)))
    assert "not evaluated minute by minute" in note
    # Annotate-only: every other field of the trade and the whole run summary are unchanged.
    clean_trade = clean["trades"][0]
    assert clean_trade["coverage_note"] is None
    assert without_note(trade) == without_note(clean_trade)
    assert trade["fallback_applied"] is False
    assert Decimal(trade["realized_pnl"]) == Decimal("-34.0604352")
    assert holed["run_summary"] == clean["run_summary"]
    assert holed["run_summary"]["fallback_count"] == 0
    # The note reaches the report; coverage percent and counts do not move (OQ-1).
    coverage = build_report(holed["trades"]).intrabar_coverage
    assert coverage.coverage_notes == (note,)
    assert coverage.percent == Decimal("100")
    assert coverage.fallback_count == 0
    assert coverage.total_trades == 1
    assert build_report(clean["trades"]).intrabar_coverage.coverage_notes == ()


def test_a_hole_free_run_carries_no_note_and_keeps_the_oracle_pnl() -> None:
    trade = simulate(tracer_case(), risk_fn=evaluate_risk)["trades"][0]
    assert trade["coverage_note"] is None
    assert Decimal(trade["realized_pnl"]) == Decimal("-34.0604352")


def test_a_hole_in_an_hour_with_no_strategy_bar_is_noted_and_changes_nothing() -> None:
    holed = long_fill_source(mark_holes=HOLE_11_20)
    final, events = walk_hours(long_state(), holed, BARS_10_AND_12)
    control, control_events = walk_hours(long_state(), long_fill_source(), BARS_10_AND_12)

    assert final.phase == "OPEN"
    assert final.fallback_applied is False
    assert [e.kind for e in events] == ["FILL"]
    assert final.coverage_note is not None
    assert final.coverage_note.startswith(prefix(at(11, 20), at(11, 29)))
    assert final.mark_settled_through_utc == at(12, 59)
    assert events == control_events
    assert dataclasses.replace(final, coverage_note=None) == control


def test_a_stop_after_the_hole_is_not_changed_and_the_closed_trade_keeps_the_note() -> None:
    marks = {at(11, 40): SL_THROUGH}
    final, events = walk_hours(
        long_state(), long_fill_source(mark_specials=marks, mark_holes=HOLE_11_20), BARS_10_AND_12
    )
    control, control_events = walk_hours(
        long_state(), long_fill_source(mark_specials=marks), BARS_10_AND_12
    )

    assert final.phase == "CLOSED"
    assert final.exit_kind == "SL"
    assert final.exit_price == Decimal("98.00")
    assert final.exit_time_utc == close_of(at(11, 40))
    assert [e.kind for e in events] == ["FILL", "EXIT"]
    assert events == control_events
    assert final.coverage_note is not None
    assert final.coverage_note.startswith(prefix(at(11, 20), at(11, 29)))
    assert dataclasses.replace(
        final, coverage_note=None, mark_settled_through_utc=None
    ) == dataclasses.replace(control, mark_settled_through_utc=None)
    record = record_of(final)
    assert record.coverage_note == final.coverage_note
    assert record.fallback_applied is False


# --------------------------------------------------------------------------- #
# Task 2 (expansion): no double note, fill minute, END_OF_DATA, path independence.
# --------------------------------------------------------------------------- #

QUIET_BAR_11 = strategy_bar(11, o="101.00", h="101.50", low="100.50", c="101.00")
QUIET_BAR_12 = strategy_bar(12, o="101.00", h="101.50", low="100.50", c="101.00")


def test_a_hole_that_straddles_the_bar_open_gets_one_note_before_the_bar_and_the_fallback() -> None:
    # Holes 11:50-11:59 (before bar 12) and 12:00-12:05 (inside bar 12). The closing-bar scan
    # covers the bar region from 12:00 and resolves it by fallback; 11:50-11:59 lies before the
    # bar region, which that scan never covers, so it gets its own continuity note.
    holes = {at(11, m) for m in range(50, 60)} | {at(12, m) for m in range(0, 6)}
    final, events = walk_hours(
        long_state(), long_fill_source(mark_holes=holes), [flat_bar(10), QUIET_BAR_12]
    )
    assert final.phase == "OPEN"
    assert final.fallback_applied is True
    assert [e.kind for e in events] == ["FILL"]
    assert final.coverage_note is not None
    first, second = final.coverage_note.split(" | ")
    assert first.startswith(prefix(at(11, 50), at(11, 59)))
    assert second.startswith(f"{NOTE_PREFIX}{at(12, 0).isoformat()}; ")
    assert f"resolved_at_strategy_bar_close_{BAR_12_CLOSE.isoformat()}" in second
    assert final.mark_settled_through_utc == at(12, 59)


def test_no_second_note_after_a_fallback_resolved_hole() -> None:
    holes = {at(11, m) for m in range(20, 30)}
    final, _ = walk_hours(
        long_state(),
        long_fill_source(mark_holes=holes),
        [flat_bar(10), QUIET_BAR_11, flat_bar(12)],
    )
    assert final.fallback_applied is True
    assert final.coverage_note is not None
    assert final.coverage_note.count(NOTE_PREFIX) == 1
    assert at(11, 20).isoformat() in final.coverage_note
    assert f"resolved_at_strategy_bar_close_{close_of(at(11, 59)).isoformat()}" in (
        final.coverage_note
    )
    assert final.mark_settled_through_utc == at(12, 59)


def test_a_hole_on_the_fill_minute_without_a_bar_is_noted_at_the_next_walked_minute() -> None:
    source = long_fill_source(mark_holes={at(10, 1)})
    state, events = advance(
        long_state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=close_of(at(10, 30)),
        bar=None,
    )
    assert state.phase == "OPEN"
    assert [e.kind for e in events] == ["FILL"]
    assert state.fallback_applied is False
    assert state.coverage_note is not None
    assert state.coverage_note.startswith(prefix(at(10, 1), at(10, 1)))


def _closed_at_data_end(*, marks_end: datetime, data_end: datetime) -> PlanState:
    """The END_OF_DATA closed state with mark minutes only up to `marks_end` (exclusive)."""
    source = long_fill_source(end_exclusive=marks_end)
    state, _ = advance(
        long_state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=data_end,
        bar=None,
    )
    assert state.phase == "OPEN"
    closed, _ = finalize_at_data_end(state, data_end_utc=data_end, source=source)
    return closed


def test_end_of_data_notes_the_minutes_missing_before_the_data_end() -> None:
    closed = _closed_at_data_end(marks_end=at(10, 30), data_end=at(11, 0))
    assert closed.exit_kind == "END_OF_DATA"
    assert closed.exit_price == Decimal("101.00")
    assert closed.exit_time_utc == close_of(at(10, 29))
    assert closed.coverage_note is not None
    assert closed.coverage_note.startswith(prefix(at(10, 30), at(10, 59)))
    # Complete data up to the data end adds no note.
    complete = _closed_at_data_end(marks_end=at(10, 30), data_end=at(10, 30))
    assert complete.exit_kind == "END_OF_DATA"
    assert complete.coverage_note is None
    # A partial last minute is never reported as missing.
    partial = _closed_at_data_end(
        marks_end=at(10, 45), data_end=datetime(2026, 1, 5, 10, 45, 20, tzinfo=UTC)
    )
    assert partial.exit_kind == "END_OF_DATA"
    assert partial.coverage_note is None


def test_hour_by_hour_and_one_window_give_the_same_state_and_notes() -> None:
    holes = {at(11, m) for m in range(20, 30)} | {at(12, m) for m in range(40, 45)}
    source = long_fill_source(mark_holes=holes)
    one, _ = advance(
        long_state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=close_of(at(13, 59)),
        bar=None,
    )
    stepped = long_state()
    previous = SIGNAL_CLOSE
    for end in (
        close_of(at(10, 59)),
        close_of(at(11, 59)),
        close_of(at(12, 59)),
        close_of(at(13, 59)),
    ):
        stepped, _ = advance(
            stepped, source=source, start_exclusive=previous, end_inclusive=end, bar=None
        )
        previous = end
    assert stepped == one
    assert one.coverage_note is not None
    first, second = one.coverage_note.split(" | ")
    assert first.startswith(prefix(at(11, 20), at(11, 29)))
    assert second.startswith(prefix(at(12, 40), at(12, 44)))
    assert one.mark_settled_through_utc == at(13, 59)


def test_re_advancing_a_walked_window_adds_nothing_and_never_moves_the_marker_back() -> None:
    source = long_fill_source()
    walked, _ = walk_hours(long_state(), source, [flat_bar(10), flat_bar(11)])
    assert walked.mark_settled_through_utc == at(11, 59)
    again, events = advance(
        walked,
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=close_of(at(10, 59)),
        bar=None,
    )
    assert events == ()
    assert again == walked


def test_a_noted_closed_trade_passes_the_record_validator() -> None:
    final, _ = walk_hours(
        long_state(),
        long_fill_source(mark_specials={at(11, 40): SL_THROUGH}, mark_holes=HOLE_11_20),
        BARS_10_AND_12,
    )
    assert final.phase == "CLOSED"
    assert final.coverage_note is not None
    validate_trade_record(record_of(final), data_start_utc=SIGNAL_CLOSE, data_end_utc=at(14))


def test_a_hole_seen_mid_bar_and_resolved_at_the_bar_close_carries_both_notes() -> None:
    # Documents the accepted double note: a mid-bar window sees the hole (continuity note) and
    # the later closing-bar window resolves the same hole by fallback (fallback note).
    holes = {at(12, m) for m in range(15, 30)}
    source = long_fill_source(mark_holes=holes)
    open_state, _ = walk_hours(long_state(), source, [flat_bar(10), flat_bar(11)])
    mid, _ = advance(
        open_state,
        source=source,
        start_exclusive=flat_bar(11).close_time_utc,
        end_inclusive=close_of(at(12, 30)),
        bar=None,
    )
    bar12 = strategy_bar(12, o="101.00", h="101.50", low="97.90", c="99.00")
    resolved, _ = advance(
        mid,
        source=source,
        start_exclusive=close_of(at(12, 30)),
        end_inclusive=bar12.close_time_utc,
        bar=bar12,
    )
    assert resolved.exit_kind == "SL"
    assert resolved.exit_price == Decimal("98.00")
    assert resolved.exit_time_utc == BAR_12_CLOSE
    assert resolved.coverage_note is not None
    first, second = resolved.coverage_note.split(" | ")
    assert first.startswith(prefix(at(12, 15), at(12, 29)))
    assert second.startswith(f"{NOTE_PREFIX}{at(12, 15).isoformat()}; ")


# --------------------------------------------------------------------------- #
# Review WR-01: the note stays bounded however many holes a long position crosses.
# --------------------------------------------------------------------------- #

# Annotation-text cap (an implementation constant, not a strategy parameter): the first
# LISTED_CAP hole spans are written out, every further span is only counted.
LISTED_CAP = 20


def _single_minute_holes(hour: int, count: int) -> set[datetime]:
    """`count` single-minute holes at minutes 1, 3, 5 ... of `hour` (each its own span)."""
    return {at(hour, 1 + 2 * index) for index in range(count)}


def _advance_bar_less(source: Any, end: datetime) -> PlanState:
    state, _ = advance(
        long_state(), source=source, start_exclusive=SIGNAL_CLOSE, end_inclusive=end, bar=None
    )
    return state


def test_a_long_position_over_many_holes_lists_a_bounded_number_of_spans_and_counts_the_rest() -> (
    None
):
    holes = _single_minute_holes(11, 30) | _single_minute_holes(12, 30)  # 60 spans
    source = long_fill_source(mark_holes=holes)
    end = close_of(at(13, 59))
    one = _advance_bar_less(source, end)
    control = _advance_bar_less(long_fill_source(), end)

    note = one.coverage_note
    assert note is not None
    assert note.count(NOTE_PREFIX) == LISTED_CAP
    assert "mark_price_1m_missing_40_further_spans_not_listed" in note
    # Bounded: a 60-hole run is no longer than 21 single-hole notes.
    single = _advance_bar_less(long_fill_source(mark_holes={at(11, 1)}), end).coverage_note
    assert single is not None
    assert len(note) < 22 * len(single)
    # Annotate-only: nothing but the note moves.
    assert dataclasses.replace(one, coverage_note=None) == control
    assert one.fallback_applied is False


def test_the_capped_note_is_path_independent_and_prefix_invariant() -> None:
    holes = _single_minute_holes(11, 30) | _single_minute_holes(12, 30)
    source = long_fill_source(mark_holes=holes)
    one = _advance_bar_less(source, close_of(at(13, 59)))
    stepped = long_state()
    previous = SIGNAL_CLOSE
    for end in (
        close_of(at(10, 59)),
        close_of(at(11, 59)),
        close_of(at(12, 59)),
        close_of(at(13, 59)),
    ):
        stepped, _ = advance(
            stepped, source=source, start_exclusive=previous, end_inclusive=end, bar=None
        )
        previous = end
    assert stepped.coverage_note == one.coverage_note
    # Prefix-invariant: after hour 11 alone 29 spans are known (the 11:59 hole is only noted once
    # a later minute is walked), and the 20 listed are the first 20 listed later.
    after_11 = _advance_bar_less(source, close_of(at(11, 59))).coverage_note
    assert after_11 is not None
    assert "mark_price_1m_missing_9_further_spans_not_listed" in after_11
    assert one.coverage_note is not None
    assert after_11.split(" | ")[:LISTED_CAP] == one.coverage_note.split(" | ")[:LISTED_CAP]


def test_exactly_the_cap_is_listed_in_full_and_one_more_span_is_counted() -> None:
    at_cap = _advance_bar_less(
        long_fill_source(mark_holes=_single_minute_holes(11, LISTED_CAP)), close_of(at(11, 59))
    ).coverage_note
    assert at_cap is not None
    assert at_cap.count(NOTE_PREFIX) == LISTED_CAP
    assert "further_spans_not_listed" not in at_cap
    over = _advance_bar_less(
        long_fill_source(mark_holes=_single_minute_holes(11, LISTED_CAP + 1)),
        close_of(at(11, 59)),
    ).coverage_note
    assert over is not None
    assert over.count(NOTE_PREFIX) == LISTED_CAP
    assert "mark_price_1m_missing_1_further_spans_not_listed" in over
