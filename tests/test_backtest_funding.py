"""Funding schedule, sign convention and window tests (Phase 14, plan 14-03, D-14).

Every expected number is hand arithmetic (the RESEARCH "Funding oracle"), never read
back from the code under test:

    funding_pnl = -sign(position) x quantity x markPrice(fundingTime) x fundingRate
    LONG qty 0.5; t1 rate +0.0001 mark 100 -> -(+1) x 0.5 x 100 x 0.0001  = -0.005  (pays)
                  t2 rate -0.0002 mark 102 -> -(+1) x 0.5 x 102 x (-0.0002) = +0.0102 (receives)
    LONG total +0.0052 ; the same window for a SHORT gives +0.005, -0.0102, total -0.0052.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from src.backtest.funding import (
    FundingRow,
    OpenSegment,
    funding_events,
    funding_pnl,
    parse_funding_row,
)
from src.backtest.series import ListMinuteSource

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
):
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
