"""Live take-profit sizing from a reconciled position (Phase 19, plan 19-07, D-18, D-19).

Every filter is a fake: sizing is proven offline, the mainnet filters are not verified
(research A7, B8).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from src.domain.lot_filters import LotFilters
from src.execution.tp_sizing import TakeProfitSizing, size_take_profits

D = Decimal


def make_filters(
    *,
    tick: str = "0.01",
    lot_min: str = "0.001",
    lot_max: str = "1000",
    lot_step: str = "0.001",
    mkt_min: str | None = None,
    mkt_max: str | None = None,
    mkt_step: str | None = None,
    min_notional: str = "5",
) -> LotFilters:
    return LotFilters(
        symbol="BTCUSDT",
        price_tick_size=D(tick),
        lot_min_quantity=D(lot_min),
        lot_max_quantity=D(lot_max),
        lot_step_size=D(lot_step),
        market_lot_min_quantity=D(mkt_min if mkt_min is not None else lot_min),
        market_lot_max_quantity=D(mkt_max if mkt_max is not None else lot_max),
        market_lot_step_size=D(mkt_step if mkt_step is not None else lot_step),
        min_notional=D(min_notional),
    )


def _size(
    *,
    position: str = "0.010",
    tp1: str = "106.004",
    tp2: str = "110.006",
    fraction: str = "0.5",
    filters: LotFilters | None = None,
    side: str = "LONG",
    mode: str = "ONE_WAY",
    working_type: str = "MARK_PRICE",
) -> TakeProfitSizing:
    return size_take_profits(
        position_quantity=D(position),
        tp1_trigger_price=D(tp1),
        tp2_trigger_price=D(tp2),
        tp1_quantity_fraction=D(fraction),
        filters=filters if filters is not None else make_filters(),
        side=side,
        position_mode=mode,
        working_type=working_type,
    )


def test_tracer_one_way_long_tp1_and_tp2_legs() -> None:
    result = size_take_profits(
        position_quantity=D("0.010"),
        tp1_trigger_price=D("106.004"),
        tp2_trigger_price=D("110.006"),
        tp1_quantity_fraction=D("0.5"),
        filters=make_filters(),
        side="LONG",
        position_mode="ONE_WAY",
        working_type="MARK_PRICE",
    )
    assert isinstance(result, TakeProfitSizing)
    assert result.is_no_trade is False
    assert result.reason_code == "OK"
    assert result.tp1_quantity == D("0.005")
    assert result.tp1_leg == {
        "side": "SELL",
        "position_side": "BOTH",
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": D("106.00"),
        "close_position": False,
        "quantity": D("0.005"),
        "reduce_only": True,
        "working_type": "MARK_PRICE",
    }
    assert result.tp2_leg == {
        "side": "SELL",
        "position_side": "BOTH",
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": D("110.00"),
        "close_position": True,
        "quantity": None,
        "reduce_only": None,
        "working_type": "MARK_PRICE",
    }


# --------------------------------------------------------------------------- #
# Quantization grid and closable cap
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("position", "fraction", "expected"),
    [
        ("0.010", "0.5", "0.005"),
        ("0.011", "0.5", "0.005"),  # 0.0055 floors, never rounds up
        ("0.0199", "0.5", "0.009"),
        ("0.003", "1", "0.003"),  # fraction 1 is the whole position, never more
        ("1.234", "0.3333", "0.411"),
    ],
)
def test_tp1_floors_onto_the_lot_grid(position: str, fraction: str, expected: str) -> None:
    result = _size(position=position, fraction=fraction)
    assert result.is_no_trade is False
    assert result.tp1_quantity == D(expected)
    assert result.tp1_quantity is not None and result.tp1_quantity <= D(position)


def test_coarser_market_lot_step_wins() -> None:
    filters = make_filters(lot_step="0.001", mkt_step="0.01", mkt_min="0.01", lot_min="0.001")
    result = _size(position="0.139", fraction="0.5", filters=filters)  # raw 0.0695
    assert result.is_no_trade is False
    assert result.tp1_quantity == D("0.06")


@pytest.mark.parametrize("fraction", ["0", "-0.1", "1.0001", "2"])
def test_fraction_outside_zero_one_raises(fraction: str) -> None:
    with pytest.raises(ValueError, match="tp1_quantity_fraction"):
        _size(fraction=fraction)


# --------------------------------------------------------------------------- #
# Refusals (O-03: no single-TP fallback, D-19: no reduce-only notional exemption)
# --------------------------------------------------------------------------- #


def _assert_refused(result: TakeProfitSizing, reason: str) -> None:
    assert result.is_no_trade is True
    assert result.reason_code == reason
    assert result.tp1_leg is None
    assert result.tp2_leg is None
    assert result.tp1_quantity is None


def test_tp1_below_lot_minimum_is_min_qty_reject() -> None:
    _assert_refused(_size(position="0.001", fraction="0.5"), "MIN_QTY_REJECT")


def test_tp1_below_market_lot_minimum_is_min_qty_reject() -> None:
    filters = make_filters(mkt_min="0.01", mkt_step="0.01")
    _assert_refused(_size(position="0.015", fraction="0.5", filters=filters), "MIN_QTY_REJECT")


def test_tp1_below_min_notional_is_notional_reject() -> None:
    # 0.005 * 106.00 = 0.53 < 5: no reduce-only exemption is assumed.
    filters = make_filters(min_notional="5")
    _assert_refused(_size(position="0.010", filters=filters), "NOTIONAL_REJECT")


def test_notional_is_measured_at_the_snapped_tp1_trigger() -> None:
    # 0.05 * 100.00 = 5.00 is exactly the minimum (accepted); a trigger snapped down to
    # 99.99 gives 4.9995 and is refused.
    filters = make_filters(min_notional="5")
    assert _size(position="0.1", tp1="100.004", filters=filters).is_no_trade is False
    _assert_refused(_size(position="0.1", tp1="99.996", filters=filters), "NOTIONAL_REJECT")


def test_min_quantity_is_checked_before_notional() -> None:
    _assert_refused(_size(position="0.001", fraction="0.5", tp1="1000"), "MIN_QTY_REJECT")


def test_no_single_tp_fallback_exists() -> None:
    result = _size(position="0.001")
    assert result.is_no_trade is True
    assert result.tp2_leg is None  # no lone close-all TP2 is offered instead


# --------------------------------------------------------------------------- #
# One-way payloads
# --------------------------------------------------------------------------- #


def test_one_way_short_payloads() -> None:
    result = _size(side="SHORT", mode="ONE_WAY", tp1="93.996", tp2="90.004")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["side"] == "BUY"
    assert result.tp1_leg["position_side"] == "BOTH"
    assert result.tp1_leg["reduce_only"] is True
    assert result.tp1_leg["close_position"] is False
    assert result.tp1_leg["trigger_price"] == D("94.00")  # snapped up, toward the entry
    assert result.tp2_leg["side"] == "BUY"
    assert result.tp2_leg["position_side"] == "BOTH"
    assert result.tp2_leg["close_position"] is True
    assert result.tp2_leg["quantity"] is None
    assert result.tp2_leg["reduce_only"] is None
    assert result.tp2_leg["trigger_price"] == D("90.01")


def test_one_way_long_tp1_reduce_only_and_tp2_close_position() -> None:
    result = _size(side="LONG", mode="ONE_WAY")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["reduce_only"] is True
    assert result.tp1_leg["position_side"] == "BOTH"
    assert result.tp2_leg["close_position"] is True
    assert result.tp2_leg["reduce_only"] is None


def test_working_type_is_copied_into_both_legs() -> None:
    result = _size(working_type="CONTRACT_PRICE")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["working_type"] == "CONTRACT_PRICE"
    assert result.tp2_leg["working_type"] == "CONTRACT_PRICE"


# --------------------------------------------------------------------------- #
# Hedge payloads
# --------------------------------------------------------------------------- #


def test_hedge_long_payloads() -> None:
    result = _size(side="LONG", mode="HEDGE")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["side"] == "SELL"
    assert result.tp1_leg["position_side"] == "LONG"
    assert result.tp1_leg["reduce_only"] is None
    assert result.tp1_leg["close_position"] is False
    assert result.tp1_leg["quantity"] == D("0.005")
    assert result.tp2_leg["side"] == "SELL"
    assert result.tp2_leg["position_side"] == "LONG"
    assert result.tp2_leg["close_position"] is True
    assert result.tp2_leg["quantity"] is None
    assert result.tp2_leg["reduce_only"] is None


def test_hedge_short_payloads() -> None:
    result = _size(side="SHORT", mode="HEDGE", tp1="93.996", tp2="90.004")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["side"] == "BUY"
    assert result.tp1_leg["position_side"] == "SHORT"
    assert result.tp1_leg["reduce_only"] is None
    assert result.tp2_leg["side"] == "BUY"
    assert result.tp2_leg["position_side"] == "SHORT"
    assert result.tp2_leg["close_position"] is True
    assert result.tp2_leg["reduce_only"] is None


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "field",
    ["position_quantity", "tp1_trigger_price", "tp2_trigger_price", "tp1_quantity_fraction"],
)
def test_non_decimal_input_raises_type_error(field: str) -> None:
    kwargs: dict[str, Any] = {
        "position_quantity": D("0.010"),
        "tp1_trigger_price": D("106"),
        "tp2_trigger_price": D("110"),
        "tp1_quantity_fraction": D("0.5"),
        "filters": make_filters(),
        "side": "LONG",
        "position_mode": "ONE_WAY",
        "working_type": "MARK_PRICE",
    }
    kwargs[field] = 0.5
    with pytest.raises(TypeError, match=field):
        size_take_profits(**kwargs)


@pytest.mark.parametrize("position", ["0", "-0.01", "NaN"])
def test_non_positive_or_non_finite_position_raises(position: str) -> None:
    with pytest.raises(ValueError, match="position_quantity"):
        _size(position=position)


def test_unknown_side_or_mode_raises() -> None:
    with pytest.raises(ValueError, match="side"):
        _size(side="BOTH")
    with pytest.raises(ValueError, match="position_mode"):
        _size(mode="NETTED")


def test_unknown_working_type_raises() -> None:
    with pytest.raises(ValueError, match="working_type"):
        _size(working_type="LAST_PRICE")


def test_result_invariants() -> None:
    with pytest.raises(ValueError):
        TakeProfitSizing(
            is_no_trade=True, reason_code="OK", tp1_leg=None, tp2_leg=None, tp1_quantity=None
        )
    with pytest.raises(ValueError):
        TakeProfitSizing(
            is_no_trade=False, reason_code="OK", tp1_leg=None, tp2_leg=None, tp1_quantity=None
        )
    with pytest.raises(ValueError):
        TakeProfitSizing(
            is_no_trade=True,
            reason_code="MIN_QTY_REJECT",
            tp1_leg={"x": 1},
            tp2_leg=None,
            tp1_quantity=None,
        )
