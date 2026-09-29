"""Tick-grid price quantization tests (09-REVIEW WR-01).

Binance rejects prices that are not a multiple of the symbol's tick
size. Every price the execution layer sends (LIMIT entry, SL/TP
triggers) is snapped onto the grid in an explicit, conservative
direction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from src.execution.placement import (
    PRICE_ROUND_DOWN,
    PRICE_ROUND_UP,
    ProtectiveTemplate,
    entry_limit_rounding,
    quantize_price,
    size_protectives_to_filled_qty,
    sl_trigger_rounding,
    tp_trigger_rounding,
)
from src.risk.types import ConstraintSnapshot

TICK = Decimal("0.01")


@pytest.mark.parametrize(
    ("price", "direction", "expected"),
    [
        (Decimal("100.015"), PRICE_ROUND_DOWN, Decimal("100.01")),
        (Decimal("100.015"), PRICE_ROUND_UP, Decimal("100.02")),
        (Decimal("101.00"), PRICE_ROUND_DOWN, Decimal("101.00")),
        (Decimal("101.00"), PRICE_ROUND_UP, Decimal("101.00")),
        (Decimal("0.0001"), PRICE_ROUND_UP, Decimal("0.01")),
    ],
)
def test_quantize_price_snaps_to_tick_grid(
    price: Decimal, direction: str, expected: Decimal
) -> None:
    result = quantize_price(price=price, price_tick_size=TICK, direction=direction)
    assert result == expected
    assert (result / TICK) == (result / TICK).to_integral_value()


def test_quantize_price_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        quantize_price(price=Decimal("0"), price_tick_size=TICK, direction=PRICE_ROUND_DOWN)
    with pytest.raises(ValueError):
        quantize_price(price=Decimal("1"), price_tick_size=TICK, direction="NEAREST")
    with pytest.raises(TypeError):
        quantize_price(price=1.0, price_tick_size=TICK, direction=PRICE_ROUND_DOWN)  # type: ignore[arg-type]


def test_rounding_directions_are_conservative() -> None:
    # LONG: BUY limit floors, SELL-side SL rounds up (toward entry),
    # TP rounds down (toward entry). SHORT mirrors every one.
    assert entry_limit_rounding(candidate_position_side="LONG") == PRICE_ROUND_DOWN
    assert entry_limit_rounding(candidate_position_side="SHORT") == PRICE_ROUND_UP
    assert sl_trigger_rounding(candidate_position_side="LONG") == PRICE_ROUND_UP
    assert sl_trigger_rounding(candidate_position_side="SHORT") == PRICE_ROUND_DOWN
    assert tp_trigger_rounding(candidate_position_side="LONG") == PRICE_ROUND_DOWN
    assert tp_trigger_rounding(candidate_position_side="SHORT") == PRICE_ROUND_UP


def test_protective_triggers_are_snapped_toward_entry() -> None:
    snapshot = ConstraintSnapshot(
        symbol="BTCUSDT",
        price_tick_size=TICK,
        quantity_step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("5.00"),
        metadata_observed_at_utc=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
    )
    template = ProtectiveTemplate(
        stop_loss_trigger_price=Decimal("98.005"),
        tp1_trigger_price=Decimal("106.005"),
        tp2_trigger_price=Decimal("110.005"),
        tp1_quantity_fraction=Decimal("0.5"),
    )
    sizing = size_protectives_to_filled_qty(
        filled_quantity=Decimal("0.300"),
        protective_template=template,
        constraint_snapshot=snapshot,
        position_mode="ONE_WAY",
        candidate_position_side="LONG",
    )
    assert sizing.sl_leg is not None and sizing.tp1_leg is not None
    assert sizing.tp2_leg is not None
    assert sizing.sl_leg["trigger_price"] == Decimal("98.01")
    assert sizing.tp1_leg["trigger_price"] == Decimal("106.00")
    assert sizing.tp2_leg["trigger_price"] == Decimal("110.00")
