"""Unit tests pinning the single R-denominator function (Phase 14, plan 14-01, D-20).

`realized_risk_for_fill = sized_realized_risk x filled / planned`, built with the pinned
Decimal helpers; floats are refused and the quantity bounds fail closed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from src.risk.realized_risk import realized_risk_for_fill


def D(text: str) -> Decimal:  # noqa: N802 - terse fixture helper
    return Decimal(text)


def test_full_fill_returns_the_sized_figure() -> None:
    assert realized_risk_for_fill(
        sized_realized_risk=D("1.50"), planned_quantity=D("0.5"), filled_quantity=D("0.5")
    ) == D("1.50")


def test_half_fill_scales_the_sized_figure_by_the_fill_fraction() -> None:
    # 1.50 x 0.25 / 0.5 = 0.75
    assert realized_risk_for_fill(
        sized_realized_risk=D("1.50"), planned_quantity=D("0.5"), filled_quantity=D("0.25")
    ) == D("0.75")


def test_zero_fill_has_zero_risk() -> None:
    assert realized_risk_for_fill(
        sized_realized_risk=D("1.50"), planned_quantity=D("0.5"), filled_quantity=D("0")
    ) == D("0")


def test_filled_above_planned_raises() -> None:
    with pytest.raises(ValueError, match="filled_quantity"):
        realized_risk_for_fill(
            sized_realized_risk=D("1.50"), planned_quantity=D("0.5"), filled_quantity=D("0.6")
        )


def test_negative_fill_raises() -> None:
    with pytest.raises(ValueError, match="filled_quantity"):
        realized_risk_for_fill(
            sized_realized_risk=D("1.50"), planned_quantity=D("0.5"), filled_quantity=D("-0.1")
        )


def test_non_positive_planned_quantity_raises() -> None:
    for planned in (D("0"), D("-0.5")):
        with pytest.raises(ValueError, match="planned_quantity"):
            realized_risk_for_fill(
                sized_realized_risk=D("1.50"), planned_quantity=planned, filled_quantity=D("0")
            )


def test_float_input_raises_type_error() -> None:
    with pytest.raises(TypeError, match="sized_realized_risk"):
        realized_risk_for_fill(
            sized_realized_risk=1.5,  # type: ignore[arg-type]
            planned_quantity=D("0.5"),
            filled_quantity=D("0.5"),
        )
    with pytest.raises(TypeError, match="filled_quantity"):
        realized_risk_for_fill(
            sized_realized_risk=D("1.50"),
            planned_quantity=D("0.5"),
            filled_quantity=0.5,  # type: ignore[arg-type]
        )
