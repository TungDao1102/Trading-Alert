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
from src.backtest.report import build
from src.risk.gating import evaluate_risk

from tests.backtest_case_helpers import (
    SYMBOL,
    flat_minutes,
    make_experiment_record,
    minute_row,
)
from tests.test_backtest_engine import tracer_case
from tests.test_backtest_exits import (
    SL_THROUGH,
    at,
    close_of,
    flat_bar,
    long_fill_source,
    long_state,
    record_of,
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
