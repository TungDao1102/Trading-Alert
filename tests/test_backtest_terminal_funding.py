"""Funding clip at a declared terminal instant (quick 261014-nnl, plan 03, design 3.1 and test 4).

For a symbol with a declared terminal instant T funding is checked and charged only up to T:
the loaded end is `min(data_end, T)`, a hole longer than cadence plus jitter before T still
raises, and any funding row of the symbol at or after T is refused. The clip is an optional
keyword (`terminal_at_utc`, default None) on `funding_events` and `check_funding_coverage`, so
`shadow_fill.py` and `shadow_runtime.py` are unchanged and an undeclared case is byte-identical.

Geometry (the REEF shape of tests/test_backtest_terminal_settlement.py): last funding row 08:00,
T = 09:00, data end the next day. Without the declaration a position held to 08:30 would need
funding coverage up to 08:30 + 8h01m = 16:31, which the 08:00 row cannot give.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from src.backtest.engine import EngineRun
from src.backtest.funding import (
    FundingCoverageError,
    FundingRow,
    OpenSegment,
    check_funding_coverage,
    funding_events,
)
from src.backtest.records import BOOKING_FUNDING
from src.backtest.series import ListMinuteSource

from tests.backtest_case_helpers import at, flat_minutes, funding_row, minute_close, minute_row
from tests.test_backtest_terminal_settlement import REEF, TERMINAL, run_settled, settled_case

NEXT_DAY = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)


def far_end(case: dict[str, Any]) -> dict[str, Any]:
    """The same case with the data window ending the next day (T is far from the data end)."""
    case["data_window"]["end_utc"] = NEXT_DAY.isoformat()
    return case


def stopped_at_0830_case(*, declare: bool) -> dict[str, Any]:
    marks = [
        *flat_minutes(REEF, at(2, 0), 390, "100.00", kind="mark"),
        minute_row(REEF, at(8, 30), "98.50", "98.60", "97.90", "98.20", kind="mark"),
    ]
    return far_end(settled_case(declare=declare, mark_minutes=marks, with_last_bar=False))


def open_at_terminal_case(*, declare: bool) -> dict[str, Any]:
    return far_end(settled_case(declare=declare))


def hole_before_terminal_case() -> dict[str, Any]:
    """Last funding row 00:00: nothing for 9h before T, longer than cadence plus jitter."""
    rows = [
        funding_row(REEF, datetime(2026, 1, 4, 16, 0, tzinfo=UTC), "0", "100"),
        funding_row(REEF, at(0, 0), "0", "100"),
    ]
    return far_end(settled_case(funding=rows))


def test_last_row_0800_terminal_0900_position_stopped_at_0830_is_covered() -> None:
    run = run_settled(stopped_at_0830_case(declare=True))

    trade = run.output["trades"][0]
    assert trade["exit_kind"] == "SL"
    assert trade["exit_time_utc"] == minute_close(at(8, 30)).isoformat()
    assert trade["funding_event_count"] == 1  # the 08:00 row only


def test_last_row_0800_terminal_0900_position_open_at_terminal_is_covered_funding_stops() -> None:
    run: EngineRun = run_settled(open_at_terminal_case(declare=True))

    trade = run.output["trades"][0]
    assert trade["exit_kind"] == "SETTLEMENT"
    assert trade["exit_time_utc"] == TERMINAL.isoformat()
    assert trade["funding_event_count"] == 1  # rows before T only
    assert Decimal(trade["funding_amount"]) == Decimal("-0.1")
    funding_times = [b.time_utc for b in run.bookings if b.kind == BOOKING_FUNDING]
    assert funding_times == [at(8, 0)]
    assert all(t < TERMINAL for t in funding_times)


def test_a_hole_longer_than_cadence_plus_jitter_before_the_terminal_still_raises() -> None:
    with pytest.raises(FundingCoverageError, match="uncovered holes"):
        run_settled(hole_before_terminal_case())


@pytest.mark.parametrize(
    "builder",
    [stopped_at_0830_case, open_at_terminal_case],
    ids=["stopped-at-0830", "open-at-terminal"],
)
def test_without_a_declaration_the_same_case_still_raises_funding_coverage_error(
    builder: Any,
) -> None:
    case = builder(declare=False)
    assert "terminal_settlements" not in case

    with pytest.raises(FundingCoverageError, match="uncovered holes"):
        run_settled(case)


# --------------------------------------------------------------------------- #
# The optional keyword on the pure funding functions.
# --------------------------------------------------------------------------- #


def _rows(*times: datetime) -> list[FundingRow]:
    return [
        FundingRow(
            symbol=REEF,
            funding_time_utc=when,
            funding_rate=Decimal("0.0001"),
            mark_price=Decimal("100"),
        )
        for when in times
    ]


def _call(
    rows: list[FundingRow], **extra: Any
) -> Any:  # FundingResult; Any keeps the kwarg optional
    return funding_events(
        symbol=REEF,
        direction="LONG",
        segments=[OpenSegment(at(2, 0), at(8, 30), Decimal("10"))],
        rows=rows,
        mark_source=ListMinuteSource(trade={}, mark={}),
        allowed_gaps=(),
        loaded_start_utc=at(0, 0),
        loaded_end_utc=NEXT_DAY,
        **extra,
    )


def test_funding_events_with_terminal_none_equals_the_call_without_the_kwarg() -> None:
    rows = _rows(at(0, 0), at(8, 0), at(16, 0))

    assert _call(rows, terminal_at_utc=None) == _call(rows)
    assert repr(_call(rows, terminal_at_utc=None)) == repr(_call(rows))


@pytest.mark.parametrize("late", [at(9, 0), at(16, 0)], ids=["at-terminal", "after-terminal"])
def test_a_funding_row_at_or_after_the_terminal_is_refused_by_funding_events(
    late: datetime,
) -> None:
    rows = _rows(at(0, 0), at(8, 0), late)

    with pytest.raises(FundingCoverageError, match="at or after its terminal instant"):
        _call(rows, terminal_at_utc=TERMINAL)


def test_funding_events_with_a_terminal_charges_only_rows_before_it() -> None:
    result = _call(_rows(at(0, 0), at(8, 0)), terminal_at_utc=TERMINAL)

    assert [e.funding_time_utc for e in result.events] == [at(8, 0)]


def test_check_funding_coverage_clips_the_loaded_end_to_the_terminal() -> None:
    rows = _rows(at(0, 0), at(8, 0))
    common: dict[str, Any] = {
        "symbol": REEF,
        "rows": rows,
        "window_start_utc": at(8, 15),
        "window_end_utc": at(8, 30),
        "loaded_start_utc": at(0, 0),
        "loaded_end_utc": NEXT_DAY,
        "allowed_gaps": (),
    }

    with pytest.raises(FundingCoverageError):
        check_funding_coverage(**common)
    assert check_funding_coverage(**common, terminal_at_utc=TERMINAL) == ()


def test_check_funding_coverage_still_raises_for_a_hole_before_the_terminal() -> None:
    with pytest.raises(FundingCoverageError):
        check_funding_coverage(
            symbol=REEF,
            rows=_rows(at(0, 0)),
            window_start_utc=at(8, 15),
            window_end_utc=at(8, 30),
            loaded_start_utc=at(0, 0),
            loaded_end_utc=NEXT_DAY,
            allowed_gaps=(),
            terminal_at_utc=TERMINAL,
        )
