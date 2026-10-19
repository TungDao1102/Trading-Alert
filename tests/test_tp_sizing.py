"""Live take-profit sizing from a reconciled position (Phase 19, plan 19-07, D-18, D-19).

Every filter is a fake: sizing is proven offline, the mainnet filters are not verified
(research A7, B8).
"""

from __future__ import annotations

from decimal import Decimal

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
