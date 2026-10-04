"""Funding schedule, sign convention and window tests (Phase 14, plan 14-03, D-14).

Every expected number is hand arithmetic (the RESEARCH "Funding oracle"), never read
back from the code under test:

    funding_pnl = -sign(position) x quantity x markPrice(fundingTime) x fundingRate
    LONG qty 0.5; t1 rate +0.0001 mark 100 -> -(+1) x 0.5 x 100 x 0.0001  = -0.005  (pays)
                  t2 rate -0.0002 mark 102 -> -(+1) x 0.5 x 102 x (-0.0002) = +0.0102 (receives)
    LONG total +0.0052 ; the same window for a SHORT gives +0.005, -0.0102, total -0.0052.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.backtest.funding import (
    FundingCoverageError,
    FundingGap,
    FundingResult,
    FundingRow,
    OpenSegment,
    check_funding_coverage,
    funding_events,
    funding_pnl,
    parse_funding_row,
)
from src.backtest.semantics import FUNDING_JITTER, FUNDING_MAX_CADENCE
from src.backtest.series import ListMinuteSource

from tests.backtest_plan_helpers import make_minute

SYMBOL = "BTCUSDT"

T1 = datetime(2026, 1, 5, 8, 0, 0, 3000, tzinfo=UTC)
T2 = datetime(2026, 1, 5, 16, 0, 0, 1000, tzinfo=UTC)
LOADED_START = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
LOADED_END = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
ENTRY = datetime(2026, 1, 5, 7, 30, 59, 999000, tzinfo=UTC)
EXIT = datetime(2026, 1, 5, 17, 10, 59, 999000, tzinfo=UTC)

NO_MARK_SOURCE = ListMinuteSource({}, {})


def _row(when: datetime, rate: str, mark: str | None, symbol: str = SYMBOL) -> FundingRow:
    return FundingRow(
        symbol=symbol,
        funding_time_utc=when,
        funding_rate=Decimal(rate),
        mark_price=None if mark is None else Decimal(mark),
    )


def _oracle_rows() -> list[FundingRow]:
    return [_row(T1, "0.0001", "100"), _row(T2, "-0.0002", "102")]


def _events(
    direction: str,
    start: datetime,
    end: datetime,
    quantity: str = "0.5",
    rows: list[FundingRow] | None = None,
) -> FundingResult:
    return funding_events(
        symbol=SYMBOL,
        direction=direction,
        segments=[OpenSegment(start_utc=start, end_utc=end, quantity=Decimal(quantity))],
        rows=_oracle_rows() if rows is None else rows,
        mark_source=NO_MARK_SOURCE,
        allowed_gaps=[],
        loaded_start_utc=LOADED_START,
        loaded_end_utc=LOADED_END,
    )


# --------------------------------------------------------------------------- #
# funding_pnl: sign convention (D-14)
# --------------------------------------------------------------------------- #


def test_long_with_a_positive_rate_pays() -> None:
    amount = funding_pnl(
        direction="LONG",
        quantity=Decimal("0.5"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.0001"),
    )
    assert amount == Decimal("-0.005")


def test_long_with_a_negative_rate_receives() -> None:
    amount = funding_pnl(
        direction="LONG",
        quantity=Decimal("0.5"),
        mark_price=Decimal("102"),
        funding_rate=Decimal("-0.0002"),
    )
    assert amount == Decimal("0.0102")


def test_short_is_the_mirror_of_long() -> None:
    paid_by_long = funding_pnl(
        direction="LONG",
        quantity=Decimal("0.5"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.0001"),
    )
    short = funding_pnl(
        direction="SHORT",
        quantity=Decimal("0.5"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.0001"),
    )
    assert short == Decimal("0.005")
    assert short == -paid_by_long


def test_funding_pnl_rejects_floats_bad_direction_and_non_positive_quantity() -> None:
    good = {
        "direction": "LONG",
        "quantity": Decimal("0.5"),
        "mark_price": Decimal("100"),
        "funding_rate": Decimal("0.0001"),
    }
    with pytest.raises(TypeError):
        funding_pnl(**{**good, "funding_rate": 0.0001})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        funding_pnl(**{**good, "quantity": 0.5})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        funding_pnl(**{**good, "mark_price": 100.0})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="direction"):
        funding_pnl(**{**good, "direction": "FLAT"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="quantity"):
        funding_pnl(**{**good, "quantity": Decimal("0")})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="quantity"):
        funding_pnl(**{**good, "quantity": Decimal("-0.5")})  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# funding_events: the actual-fundingTime schedule and the half-open window
# --------------------------------------------------------------------------- #


def test_long_held_across_two_instants_books_the_hand_oracle() -> None:
    result = _events("LONG", ENTRY, EXIT)
    assert [e.funding_time_utc for e in result.events] == [T1, T2]
    assert [e.amount for e in result.events] == [Decimal("-0.005"), Decimal("0.0102")]
    assert result.total == Decimal("0.0052")
    assert all(e.quantity == Decimal("0.5") and not e.mark_from_kline for e in result.events)
    assert result.used_allowed_gaps == ()


def test_short_held_across_the_same_window_books_the_mirror() -> None:
    result = _events("SHORT", ENTRY, EXIT)
    assert [e.amount for e in result.events] == [Decimal("0.005"), Decimal("-0.0102")]
    assert result.total == Decimal("-0.0052")


def test_a_position_opened_between_two_instants_is_not_charged_at_the_first() -> None:
    opened_after_t1 = datetime(2026, 1, 5, 8, 10, 59, 999000, tzinfo=UTC)
    result = _events("LONG", opened_after_t1, EXIT)
    assert [e.funding_time_utc for e in result.events] == [T2]
    assert result.total == Decimal("0.0102")


def test_a_position_closed_exactly_at_an_instant_is_not_charged_there() -> None:
    result = _events("LONG", ENTRY, T1)
    assert result.events == ()
    assert result.total == Decimal("0")


def test_a_position_opened_exactly_at_an_instant_is_charged_there() -> None:
    result = _events("LONG", T1, EXIT)
    assert [e.funding_time_utc for e in result.events] == [T1, T2]


def test_events_come_back_sorted_even_when_rows_are_not() -> None:
    result = _events("LONG", ENTRY, EXIT, rows=list(reversed(_oracle_rows())))
    assert [e.funding_time_utc for e in result.events] == [T1, T2]


def test_event_carries_symbol_rate_and_mark() -> None:
    first = _events("LONG", ENTRY, EXIT).events[0]
    assert first.symbol == SYMBOL
    assert first.funding_rate == Decimal("0.0001")
    assert first.mark_price == Decimal("100")


# --------------------------------------------------------------------------- #
# parse_funding_row
# --------------------------------------------------------------------------- #


def test_parse_funding_row_builds_decimals_from_strings() -> None:
    row = parse_funding_row(
        {
            "symbol": SYMBOL,
            "funding_time_utc": "2026-01-05T08:00:00.003+00:00",
            "funding_rate": "0.0001",
            "mark_price": "100.00",
        }
    )
    assert row == _row(T1, "0.0001", "100.00")


def test_parse_funding_row_maps_none_and_empty_string_mark_to_none() -> None:
    base = {"symbol": SYMBOL, "funding_time_utc": T1, "funding_rate": "0.0001"}
    assert parse_funding_row({**base, "mark_price": None}).mark_price is None
    assert parse_funding_row({**base, "mark_price": ""}).mark_price is None


def test_parse_funding_row_rejects_floats_and_naive_times() -> None:
    base = {
        "symbol": SYMBOL,
        "funding_time_utc": T1,
        "funding_rate": "0.0001",
        "mark_price": "100",
    }
    with pytest.raises(TypeError):
        parse_funding_row({**base, "funding_rate": 0.0001})
    with pytest.raises(TypeError):
        parse_funding_row({**base, "mark_price": 100.0})
    with pytest.raises(ValueError, match="UTC"):
        parse_funding_row({**base, "funding_time_utc": datetime(2026, 1, 5, 8, 0)})


# --------------------------------------------------------------------------- #
# Open-quantity segments across a TP1 partial (D-36)
# --------------------------------------------------------------------------- #

TP1_TIME = datetime(2026, 1, 5, 12, 0, 0, 2000, tzinfo=UTC)


def test_instant_after_tp1_uses_the_remainder_quantity() -> None:
    tp1_before_t2 = datetime(2026, 1, 5, 12, 0, 59, 999000, tzinfo=UTC)
    result = funding_events(
        symbol=SYMBOL,
        direction="LONG",
        segments=[
            OpenSegment(ENTRY, tp1_before_t2, Decimal("0.5")),
            OpenSegment(tp1_before_t2, EXIT, Decimal("0.25")),
        ],
        rows=_oracle_rows(),
        mark_source=NO_MARK_SOURCE,
        allowed_gaps=[],
        loaded_start_utc=LOADED_START,
        loaded_end_utc=LOADED_END,
    )
    # t1: -(+1) x 0.5 x 100 x 0.0001 = -0.005 ; t2: -(+1) x 0.25 x 102 x (-0.0002) = +0.0051
    assert [e.quantity for e in result.events] == [Decimal("0.5"), Decimal("0.25")]
    assert [e.amount for e in result.events] == [Decimal("-0.005"), Decimal("0.0051")]
    assert result.total == Decimal("0.0001")


def test_an_instant_exactly_at_the_tp1_time_belongs_to_the_remainder() -> None:
    rows = [
        _row(T1, "0.0001", "100"),
        _row(TP1_TIME, "0.0003", "101"),
        _row(T2, "-0.0002", "102"),
    ]
    result = funding_events(
        symbol=SYMBOL,
        direction="LONG",
        segments=[
            OpenSegment(ENTRY, TP1_TIME, Decimal("0.5")),
            OpenSegment(TP1_TIME, EXIT, Decimal("0.25")),
        ],
        rows=rows,
        mark_source=NO_MARK_SOURCE,
        allowed_gaps=[],
        loaded_start_utc=LOADED_START,
        loaded_end_utc=LOADED_END,
    )
    # at TP1: -(+1) x 0.25 x 101 x 0.0003 = -0.007575 ; total -0.005 - 0.007575 + 0.0051
    assert [e.quantity for e in result.events] == [Decimal("0.5"), Decimal("0.25"), Decimal("0.25")]
    assert result.events[1].amount == Decimal("-0.007575")
    assert result.total == Decimal("-0.007475")


def test_overlapping_segments_are_refused() -> None:
    with pytest.raises(ValueError, match="overlap"):
        funding_events(
            symbol=SYMBOL,
            direction="LONG",
            segments=[
                OpenSegment(ENTRY, EXIT, Decimal("0.5")),
                OpenSegment(TP1_TIME, EXIT, Decimal("0.25")),
            ],
            rows=_oracle_rows(),
            mark_source=NO_MARK_SOURCE,
            allowed_gaps=[],
            loaded_start_utc=LOADED_START,
            loaded_end_utc=LOADED_END,
        )


# --------------------------------------------------------------------------- #
# markPrice(fundingTime): the row first, the mark kline minute second (D-15)
# --------------------------------------------------------------------------- #


def _mark_source(*opens_and_prices: tuple[datetime, str]) -> ListMinuteSource:
    minutes = [
        make_minute(SYMBOL, opened, price, price, price, price, "mark")
        for opened, price in opens_and_prices
    ]
    return ListMinuteSource({}, {SYMBOL: minutes})


def _with_mark_source(source: ListMinuteSource, rows: list[FundingRow]) -> FundingResult:
    return funding_events(
        symbol=SYMBOL,
        direction="LONG",
        segments=[OpenSegment(ENTRY, EXIT, Decimal("0.5"))],
        rows=rows,
        mark_source=source,
        allowed_gaps=[],
        loaded_start_utc=LOADED_START,
        loaded_end_utc=LOADED_END,
    )


def test_an_empty_row_mark_falls_back_to_the_open_of_the_containing_mark_minute() -> None:
    source = _mark_source((datetime(2026, 1, 5, 8, 0, tzinfo=UTC), "99.80"))
    result = _with_mark_source(source, [_row(T1, "0.0001", None), _row(T2, "-0.0002", "102")])
    first, second = result.events
    # -(+1) x 0.5 x 99.80 x 0.0001 = -0.00499
    assert first.mark_price == Decimal("99.80")
    assert first.mark_from_kline is True
    assert first.amount == Decimal("-0.00499")
    assert second.mark_from_kline is False


def test_a_row_mark_wins_over_the_kline() -> None:
    source = _mark_source((datetime(2026, 1, 5, 8, 0, tzinfo=UTC), "99.80"))
    result = _with_mark_source(source, [_row(T1, "0.0001", "100"), _row(T2, "-0.0002", "102")])
    assert result.events[0].mark_price == Decimal("100")
    assert result.events[0].mark_from_kline is False


def test_the_minute_containing_the_instant_is_used_even_in_its_last_millisecond() -> None:
    late_in_minute = datetime(2026, 1, 5, 8, 0, 59, 999500, tzinfo=UTC)
    source = _mark_source(
        (datetime(2026, 1, 5, 7, 59, tzinfo=UTC), "98.00"),
        (datetime(2026, 1, 5, 8, 0, tzinfo=UTC), "99.80"),
        (datetime(2026, 1, 5, 8, 1, tzinfo=UTC), "97.00"),
    )
    result = _with_mark_source(
        source, [_row(late_in_minute, "0.0001", None), _row(T2, "-0.0002", "102")]
    )
    assert result.events[0].mark_price == Decimal("99.80")


def test_a_hole_at_the_mark_minute_fails_closed_and_never_uses_a_neighbour() -> None:
    source = _mark_source(
        (datetime(2026, 1, 5, 7, 59, tzinfo=UTC), "98.00"),
        (datetime(2026, 1, 5, 8, 1, tzinfo=UTC), "97.00"),
    )
    with pytest.raises(FundingCoverageError, match="mark"):
        _with_mark_source(source, [_row(T1, "0.0001", None), _row(T2, "-0.0002", "102")])


def test_no_mark_series_for_the_symbol_fails_closed() -> None:
    with pytest.raises(FundingCoverageError, match="mark"):
        _with_mark_source(NO_MARK_SOURCE, [_row(T1, "0.0001", None), _row(T2, "-0.0002", "102")])


# --------------------------------------------------------------------------- #
# Coverage rule (D-15, D-36): cadence plus jitter, loaded range, allow-gaps
# --------------------------------------------------------------------------- #

DAY = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
EARLY = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)


def _grid(step_hours: int, count: int, *, start: datetime = DAY) -> list[FundingRow]:
    return [
        _row(start + timedelta(hours=step_hours * i, milliseconds=2), "0.0001", "100")
        for i in range(count)
    ]


def _cover(
    rows: list[FundingRow],
    window_start: datetime,
    window_end: datetime,
    *,
    loaded_start: datetime = LOADED_START,
    loaded_end: datetime = LOADED_END,
    allowed: list[FundingGap] | None = None,
    symbol: str = SYMBOL,
) -> tuple[FundingGap, ...]:
    return check_funding_coverage(
        symbol=symbol,
        rows=rows,
        window_start_utc=window_start,
        window_end_utc=window_end,
        loaded_start_utc=loaded_start,
        loaded_end_utc=loaded_end,
        allowed_gaps=[] if allowed is None else allowed,
    )


def test_a_four_hour_cadence_covers_a_window() -> None:
    used = _cover(_grid(4, 6), EARLY, datetime(2026, 1, 5, 13, 0, tzinfo=UTC))
    assert used == ()


def test_an_eight_hour_cadence_covers_a_window() -> None:
    used = _cover(_grid(8, 3), EARLY, datetime(2026, 1, 5, 20, 0, tzinfo=UTC))
    assert used == ()


def test_the_tolerance_is_the_max_cadence_plus_the_jitter() -> None:
    assert FUNDING_MAX_CADENCE == timedelta(hours=8)
    assert FUNDING_JITTER == timedelta(seconds=60)


def test_millisecond_jitter_around_the_grid_is_covered() -> None:
    first = DAY
    second = first + timedelta(hours=7, minutes=59, seconds=59, milliseconds=990)
    third = second + timedelta(hours=8, milliseconds=40)
    rows = [_row(t, "0.0001", "100") for t in (first, second, third)]
    used = _cover(rows, EARLY, datetime(2026, 1, 5, 17, 0, tzinfo=UTC))
    assert used == ()


def test_a_spacing_just_beyond_the_tolerance_is_a_hole() -> None:
    too_far = DAY + timedelta(hours=8, seconds=61)
    rows = [_row(DAY, "0.0001", "100"), _row(too_far, "0.0001", "100")]
    with pytest.raises(FundingCoverageError) as caught:
        # window ends before the last row so only the 8 h 1 m 1 s spacing is a hole
        _cover(rows, EARLY, datetime(2026, 1, 5, 8, 0, tzinfo=UTC))
    assert caught.value.holes == (FundingGap(SYMBOL, DAY, too_far),)


HOLE_START = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
HOLE_END = HOLE_START + timedelta(hours=503)
HOLE_LOADED_END = datetime(2026, 2, 2, 0, 0, tzinfo=UTC)
HOLE_WINDOW = (
    datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
    datetime(2026, 1, 20, 12, 0, tzinfo=UTC),
)


def _rows_with_the_503_hour_hole() -> list[FundingRow]:
    return [
        _row(DAY, "0.0001", "100"),
        _row(HOLE_START, "0.0001", "100"),
        _row(HOLE_END, "0.0001", "100"),
        _row(HOLE_END + timedelta(hours=8), "0.0001", "100"),
    ]


def test_a_503_hour_hole_inside_the_window_raises_naming_symbol_and_bounds() -> None:
    with pytest.raises(FundingCoverageError) as caught:
        _cover(_rows_with_the_503_hour_hole(), *HOLE_WINDOW, loaded_end=HOLE_LOADED_END)
    assert caught.value.holes == (FundingGap(SYMBOL, HOLE_START, HOLE_END),)
    assert SYMBOL in str(caught.value)
    assert HOLE_START.isoformat() in str(caught.value)
    assert HOLE_END.isoformat() in str(caught.value)


def test_a_window_starting_before_the_loaded_range_raises() -> None:
    with pytest.raises(FundingCoverageError, match="loaded"):
        _cover(
            _grid(8, 3),
            datetime(2026, 1, 4, 23, 0, tzinfo=UTC),
            datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
        )


def test_a_window_ending_after_the_loaded_range_raises() -> None:
    with pytest.raises(FundingCoverageError, match="loaded"):
        _cover(
            _grid(8, 3),
            datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
            datetime(2026, 1, 6, 0, 0, 1, tzinfo=UTC),
        )


def test_a_window_with_no_funding_row_near_it_raises() -> None:
    with pytest.raises(FundingCoverageError):
        _cover([], EARLY, datetime(2026, 1, 5, 2, 0, tzinfo=UTC))


def test_an_allowed_gap_covering_the_hole_succeeds_and_is_recorded() -> None:
    allowed = FundingGap(SYMBOL, HOLE_START, HOLE_END)
    result = funding_events(
        symbol=SYMBOL,
        direction="LONG",
        segments=[OpenSegment(HOLE_WINDOW[0], HOLE_WINDOW[1], Decimal("0.5"))],
        rows=_rows_with_the_503_hour_hole(),
        mark_source=NO_MARK_SOURCE,
        allowed_gaps=[allowed],
        loaded_start_utc=LOADED_START,
        loaded_end_utc=HOLE_LOADED_END,
    )
    assert result.used_allowed_gaps == (allowed,)
    # only the 08:00 instant lies inside the window: -(+1) x 0.5 x 100 x 0.0001
    assert [e.funding_time_utc for e in result.events] == [HOLE_START]
    assert result.total == Decimal("-0.005")


def test_a_wider_allowed_gap_covers_and_an_unneeded_one_is_not_recorded() -> None:
    wide = FundingGap(SYMBOL, HOLE_START - timedelta(hours=1), HOLE_END + timedelta(hours=1))
    unrelated = FundingGap(
        SYMBOL, datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC)
    )
    used = _cover(
        _rows_with_the_503_hour_hole(),
        *HOLE_WINDOW,
        loaded_end=HOLE_LOADED_END,
        allowed=[wide, unrelated],
    )
    assert used == (wide,)


def test_an_allowed_gap_for_another_symbol_does_not_cover_the_hole() -> None:
    other = FundingGap("ETHUSDT", HOLE_START, HOLE_END)
    with pytest.raises(FundingCoverageError):
        _cover(
            _rows_with_the_503_hour_hole(),
            *HOLE_WINDOW,
            loaded_end=HOLE_LOADED_END,
            allowed=[other],
        )


def test_a_partially_covering_allowed_gap_does_not_cover_the_hole() -> None:
    partial = FundingGap(SYMBOL, HOLE_START, HOLE_END - timedelta(hours=1))
    with pytest.raises(FundingCoverageError):
        _cover(
            _rows_with_the_503_hour_hole(),
            *HOLE_WINDOW,
            loaded_end=HOLE_LOADED_END,
            allowed=[partial],
        )


def test_rows_of_other_symbols_are_ignored_and_never_fill_a_hole() -> None:
    foreign = [
        _row(HOLE_START + timedelta(hours=8 * i), "0.0001", "100", symbol="ETHUSDT")
        for i in range(1, 60)
    ]
    with pytest.raises(FundingCoverageError):
        _cover(
            _rows_with_the_503_hour_hole() + foreign,
            *HOLE_WINDOW,
            loaded_end=HOLE_LOADED_END,
        )


def test_a_duplicate_funding_time_for_one_symbol_raises() -> None:
    rows = [_row(T1, "0.0001", "100"), _row(T1, "0.0002", "101"), _row(T2, "-0.0002", "102")]
    with pytest.raises(ValueError, match="duplicate"):
        _events("LONG", ENTRY, EXIT, rows=rows)


def test_the_same_instant_for_two_different_symbols_is_not_a_duplicate() -> None:
    rows = [*_oracle_rows(), _row(T1, "0.0009", "500", symbol="ETHUSDT")]
    assert _events("LONG", ENTRY, EXIT, rows=rows).total == Decimal("0.0052")


def test_a_zero_length_window_books_nothing_and_needs_no_coverage() -> None:
    result = funding_events(
        symbol=SYMBOL,
        direction="LONG",
        segments=[OpenSegment(ENTRY, ENTRY, Decimal("0.5"))],
        rows=[],
        mark_source=NO_MARK_SOURCE,
        allowed_gaps=[],
        loaded_start_utc=LOADED_START,
        loaded_end_utc=LOADED_END,
    )
    assert result.events == ()
    assert result.total == Decimal("0")
