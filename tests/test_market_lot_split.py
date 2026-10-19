"""Pure lot arithmetic for the emergency close and the TP legs (Phase 19, plan 19-04, D-16, D-19).

Every filter here is a fake: the splitting is proven offline, the mainnet filters are not
verified (research A7, B8, B9).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from src.domain.lot_filters import LotFilters
from src.execution.lot_split import is_valid_market_part, next_close_part

D = Decimal


def make_filters(
    *,
    lot_min: str = "0.001",
    lot_max: str = "1000",
    lot_step: str = "0.001",
    market_min: str = "0.001",
    market_max: str = "120",
    market_step: str = "0.001",
) -> LotFilters:
    return LotFilters(
        symbol="BTCUSDT",
        price_tick_size=D("0.1"),
        lot_min_quantity=D(lot_min),
        lot_max_quantity=D(lot_max),
        lot_step_size=D(lot_step),
        market_lot_min_quantity=D(market_min),
        market_lot_max_quantity=D(market_max),
        market_lot_step_size=D(market_step),
        min_notional=D("100"),
    )


# --------------------------------------------------------------------------- #
# LotFilters validation
# --------------------------------------------------------------------------- #

_DECIMAL_FIELDS = (
    "price_tick_size",
    "lot_min_quantity",
    "lot_max_quantity",
    "lot_step_size",
    "market_lot_min_quantity",
    "market_lot_max_quantity",
    "market_lot_step_size",
    "min_notional",
)


def test_lot_filters_accepts_a_consistent_set() -> None:
    filters = make_filters()
    assert filters.lot_step_size == D("0.001")


@pytest.mark.parametrize("field", _DECIMAL_FIELDS)
@pytest.mark.parametrize("bad", [D("0"), D("-1"), D("NaN"), D("Infinity")])
def test_lot_filters_rejects_non_positive_or_non_finite(field: str, bad: Decimal) -> None:
    with pytest.raises(ValueError, match=field):
        replace(make_filters(), **{field: bad})


@pytest.mark.parametrize("field", _DECIMAL_FIELDS)
def test_lot_filters_rejects_a_non_decimal(field: str) -> None:
    with pytest.raises((TypeError, ValueError), match=field):
        replace(make_filters(), **{field: 1.5})


def test_lot_filters_rejects_lot_min_above_max() -> None:
    with pytest.raises(ValueError, match="lot_min_quantity"):
        make_filters(lot_min="5", lot_max="1")


def test_lot_filters_rejects_market_min_above_max() -> None:
    with pytest.raises(ValueError, match="market_lot_min_quantity"):
        make_filters(market_min="5", market_max="1")


def test_lot_filters_rejects_an_empty_symbol() -> None:
    with pytest.raises(ValueError, match="symbol"):
        replace(make_filters(), symbol="")


# --------------------------------------------------------------------------- #
# Tracer: one part within the market maximum
# --------------------------------------------------------------------------- #


def test_position_within_the_market_maximum_closes_in_one_part() -> None:
    assert next_close_part(remaining=D("0.5"), filters=make_filters()) == D("0.5")


def test_is_valid_market_part_needs_both_filters() -> None:
    filters = make_filters(lot_step="0.001", market_step="0.01", market_min="0.01")
    assert is_valid_market_part(D("0.5"), filters)
    assert not is_valid_market_part(D("0.505"), filters)  # off the market grid
    assert not is_valid_market_part(D("0.0005"), filters)  # below both minimums
    assert not is_valid_market_part(D("121"), filters)  # above the market maximum
    assert not is_valid_market_part(D("0"), filters)
