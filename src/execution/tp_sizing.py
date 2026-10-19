"""Live take-profit sizing from the reconciled position (Phase 19, plan 19-07, D-18, D-19).

`size_protectives_to_filled_qty` (src/execution/placement.py) is called by the frozen
backtest and must not change, so the live path has its own function. It differs in what
it is given and what it checks:

- the quantity is the real, reconciled position after the entry is terminal (D-18), not
  the entry's filled quantity;
- TP1 is floored onto the intersection of LOT_SIZE and MARKET_LOT_SIZE (a triggered
  TAKE_PROFIT_MARKET is a market exit, research A7), never up and never above the position;
- the fraction of the position that TP1 takes is an argument. It stays the code constant of
  D052 item (c) in the caller's domain (EXEC-07 stays Pending, O-02): no constant lives here.

Refusals. A TP1 below the lot or market minimum is MIN_QTY_REJECT, and a TP1 whose notional
at the snapped trigger is below MIN_NOTIONAL is NOTIONAL_REJECT. No MIN_NOTIONAL exemption
is assumed for reduce-only legs (criterion 4: the Demo evidence was for a stop, not a TP).
There is no single-TP fallback (O-03 auto default): the backtest rule D-27 and the live
rule must move together (G4-007), so only the refusal is implemented. The caller keeps the
confirmed stop and goes to SAFE_MODE (CR-03 branch).

TP2 is `closePosition=true` with no quantity and no reduceOnly.

Purity: stdlib, Decimal, `src.domain`, `src.core._decimal` and the pure placement and lot
helpers. No clock, no float, no SDK, no `src.backtest`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.core._decimal import _mul
from src.domain.lot_filters import LotFilters
from src.execution.lot_split import quantize_to_lot
from src.execution.placement import quantize_price, tp_trigger_rounding

_OK = "OK"
_MIN_QTY_REJECT = "MIN_QTY_REJECT"
_NOTIONAL_REJECT = "NOTIONAL_REJECT"

_ONE_WAY = "ONE_WAY"
_HEDGE = "HEDGE"
_LONG = "LONG"
_SHORT = "SHORT"
_BOTH = "BOTH"


@dataclass(frozen=True)
class TakeProfitSizing:
    """The result of `size_take_profits`.

    `is_no_trade=True` carries a canonical rejection in `reason_code` (MIN_QTY_REJECT or
    NOTIONAL_REJECT) and no legs. `is_no_trade=False` carries "OK" and both legs.
    """

    is_no_trade: bool
    reason_code: str
    tp1_leg: dict[str, Any] | None
    tp2_leg: dict[str, Any] | None
    tp1_quantity: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        legs = (self.tp1_leg, self.tp2_leg, self.tp1_quantity)
        if self.is_no_trade:
            if self.reason_code == _OK:
                raise ValueError("TakeProfitSizing: is_no_trade=True requires reason_code != 'OK'")
            if any(leg is not None for leg in legs):
                raise ValueError("TakeProfitSizing: is_no_trade=True requires no legs")
        else:
            if self.reason_code != _OK:
                raise ValueError(
                    f"TakeProfitSizing: is_no_trade=False requires reason_code='OK', "
                    f"got {self.reason_code!r}"
                )
            if any(leg is None for leg in legs):
                raise ValueError("TakeProfitSizing: is_no_trade=False requires both legs")


def size_take_profits(
    *,
    position_quantity: Decimal,
    tp1_trigger_price: Decimal,
    tp2_trigger_price: Decimal,
    tp1_quantity_fraction: Decimal,
    filters: LotFilters,
    side: str,
    position_mode: str,
    working_type: str,
) -> TakeProfitSizing:
    """Size TP1 and TP2 from the reconciled position (D-18, D-19)."""
    protective_side = "SELL" if side == _LONG else "BUY"
    leg_position_side = _BOTH if position_mode == _ONE_WAY else side
    tp_rounding = tp_trigger_rounding(candidate_position_side=side)
    tp1_trigger = quantize_price(
        price=tp1_trigger_price, price_tick_size=filters.price_tick_size, direction=tp_rounding
    )
    tp2_trigger = quantize_price(
        price=tp2_trigger_price, price_tick_size=filters.price_tick_size, direction=tp_rounding
    )
    raw_tp1 = _mul(position_quantity, tp1_quantity_fraction)
    tp1_qty = quantize_to_lot(quantity=raw_tp1, filters=filters, market_exit=True)
    tp1_leg: dict[str, Any] = {
        "side": protective_side,
        "position_side": leg_position_side,
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": tp1_trigger,
        "close_position": False,
        "quantity": tp1_qty,
        "reduce_only": True,
        "working_type": working_type,
    }
    tp2_leg: dict[str, Any] = {
        "side": protective_side,
        "position_side": leg_position_side,
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": tp2_trigger,
        "close_position": True,
        "quantity": None,
        "reduce_only": None,
        "working_type": working_type,
    }
    return TakeProfitSizing(
        is_no_trade=False,
        reason_code=_OK,
        tp1_leg=tp1_leg,
        tp2_leg=tp2_leg,
        tp1_quantity=tp1_qty,
    )


__all__ = ["TakeProfitSizing", "size_take_profits"]
