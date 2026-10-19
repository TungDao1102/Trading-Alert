"""Pure lot arithmetic for the emergency close and the TP legs (Phase 19, plan 19-04, D-16, D-19).

Every filter here is a fake: the splitting is proven offline, the mainnet filters are not
verified (research A7, B8, B9).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from src.domain.lot_filters import LotFilters
from src.execution.lot_split import (
    CloseSplit,
    is_valid_market_part,
    next_close_part,
    plan_close_parts,
)

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


# --------------------------------------------------------------------------- #
# Splitting above the market maximum
# --------------------------------------------------------------------------- #


def _unit_filters(
    *, step: str, market_min_steps: int, market_max_steps: int, lot_max_steps: int = 100_000
) -> LotFilters:
    unit = D(step)
    return make_filters(
        lot_min=str(unit),
        lot_max=str(unit * lot_max_steps),
        lot_step=str(unit),
        market_min=str(unit * market_min_steps),
        market_max=str(unit * market_max_steps),
        market_step=str(unit),
    )


def test_position_above_the_market_maximum_splits_into_valid_parts() -> None:
    filters = make_filters(
        lot_min="1", lot_step="1", market_min="1", market_max="5", market_step="1"
    )
    split = plan_close_parts(position=D("12"), filters=filters)
    assert split == CloseSplit(parts=(D("5"), D("5"), D("2")), complete=True)


def test_split_avoids_leaving_a_tail_below_the_minimum() -> None:
    filters = make_filters(
        lot_min="0.5", lot_step="0.5", market_min="1", market_max="5", market_step="0.5"
    )
    split = plan_close_parts(position=D("10.5"), filters=filters)
    assert split.parts == (D("5"), D("4.5"), D("1"))
    assert split.complete
    assert sum(split.parts, D("0")) == D("10.5")


def test_tail_avoidance_when_the_naive_max_part_strands_a_sub_minimum_tail() -> None:
    filters = make_filters(
        lot_min="1", lot_step="1", market_min="3", market_max="4", market_step="1"
    )
    # 9 = 3 + 3 + 3 (the greedy 4 + 4 would strand 1, 4 + 5 is above the maximum)
    split = plan_close_parts(position=D("9"), filters=filters)
    assert split.complete
    assert sum(split.parts, D("0")) == D("9")
    assert all(is_valid_market_part(part, filters) for part in split.parts)


def test_unrepresentable_position_reports_incomplete_and_never_rounds_up() -> None:
    filters = make_filters()
    split = plan_close_parts(position=D("0.0015"), filters=filters)
    assert not split.complete
    assert sum(split.parts, D("0")) < D("0.0015")
    assert next_close_part(remaining=D("0.0005"), filters=filters) is None


def test_next_close_part_is_none_when_the_remainder_is_below_the_minimum() -> None:
    filters = make_filters(market_min="0.01", market_step="0.01")
    assert next_close_part(remaining=D("0.009"), filters=filters) is None


@pytest.mark.parametrize("remaining", [D("0"), D("-1"), D("NaN")])
def test_next_close_part_is_none_for_a_non_positive_or_non_finite_remainder(
    remaining: Decimal,
) -> None:
    assert next_close_part(remaining=remaining, filters=make_filters()) is None


def test_zero_position_needs_no_part() -> None:
    assert plan_close_parts(position=D("0"), filters=make_filters()) == CloseSplit(
        parts=(), complete=True
    )


def test_lot_and_market_grids_with_different_steps_use_the_intersection() -> None:
    filters = make_filters(
        lot_min="0.001", lot_step="0.001", market_min="0.01", market_max="1", market_step="0.01"
    )
    part = next_close_part(remaining=D("0.555"), filters=filters)
    assert part == D("0.55")
    assert part is not None and is_valid_market_part(part, filters)


def test_disjoint_progressions_have_no_valid_part() -> None:
    # LOT_SIZE accepts 0.002 + k*0.004; MARKET_LOT_SIZE accepts 0.005 + k*0.004: never equal
    filters = make_filters(
        lot_min="0.002", lot_step="0.004", market_min="0.005", market_max="1", market_step="0.004"
    )
    assert next_close_part(remaining=D("0.5"), filters=filters) is None
    assert plan_close_parts(position=D("0.5"), filters=filters) == CloseSplit(
        parts=(), complete=False
    )


def test_splitting_is_deterministic() -> None:
    filters = _unit_filters(step="0.01", market_min_steps=3, market_max_steps=7)
    first = plan_close_parts(position=D("0.43"), filters=filters)
    second = plan_close_parts(position=D("0.43"), filters=filters)
    assert first == second


def _valid_units(filters: LotFilters, unit: Decimal, ceiling: int) -> set[int]:
    """Valid MARKET parts by brute force over whole units, with the independent check."""
    return {k for k in range(1, ceiling + 1) if is_valid_market_part(unit * k, filters)}


def _representable_units(valid: set[int], limit: int) -> set[int]:
    reachable = {0}
    for total in range(1, limit + 1):
        if any((total - part) in reachable for part in valid if part <= total):
            reachable.add(total)
    return reachable


_STEPS = ("0.001", "0.01", "0.5")
_MARKET_MIN_STEPS = (1, 3)
_MARKET_MAX_STEPS = (4, 7, 50)
_POSITION_STEPS = range(1, 61)


def test_exhaustive_grid_of_fake_filters() -> None:
    cases = 0
    for step in _STEPS:
        unit = D(step)
        for min_steps in _MARKET_MIN_STEPS:
            for max_steps in _MARKET_MAX_STEPS:
                filters = _unit_filters(
                    step=step, market_min_steps=min_steps, market_max_steps=max_steps
                )
                valid = _valid_units(filters, unit, 60)
                reachable = _representable_units(valid, 60)
                positions = [unit * k for k in _POSITION_STEPS]
                positions += [unit * k + unit / 2 for k in (0, 1, 5, 20)]  # off the grid
                for position in positions:
                    cases += 1
                    split = plan_close_parts(position=position, filters=filters)
                    remaining = position
                    for part in split.parts:
                        assert is_valid_market_part(part, filters)
                        assert part <= remaining
                        remaining -= part
                    on_grid = position % unit == 0
                    expected = on_grid and int(position / unit) in reachable
                    assert split.complete is expected, (step, min_steps, max_steps, position)
                    if split.complete:
                        assert remaining == 0
                        assert sum(split.parts, D("0")) == position
                    else:
                        assert remaining > 0
    assert cases == (
        len(_STEPS) * len(_MARKET_MIN_STEPS) * len(_MARKET_MAX_STEPS) * (len(_POSITION_STEPS) + 4)
    )
