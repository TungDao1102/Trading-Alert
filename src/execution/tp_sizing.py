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

_WORKING_TYPES = ("MARK_PRICE", "CONTRACT_PRICE")


def _require_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {value}")
    return value


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


def _refusal(reason_code: str) -> TakeProfitSizing:
    return TakeProfitSizing(
        is_no_trade=True, reason_code=reason_code, tp1_leg=None, tp2_leg=None, tp1_quantity=None
    )


def _match_step_exponent(quantity: Decimal, step: Decimal) -> Decimal:
    """Express `quantity` with the exponent of `step` when that loses nothing.

    The lot arithmetic works on a common power of ten, so `0.005` can come back as
    `0.0050`; the exchange payload and the frozen sizing carry the step's exponent.
    """
    exponent = step.as_tuple().exponent
    assert isinstance(exponent, int)
    candidate = quantity.quantize(Decimal(1).scaleb(exponent))
    return candidate if candidate == quantity else quantity


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
    """Size TP1 and TP2 from the reconciled position (D-18, D-19).

    Args:
        position_quantity: The real, reconciled position quantity (> 0).
        tp1_trigger_price: Raw TP1 trigger; snapped onto the tick toward the entry.
        tp2_trigger_price: Raw TP2 trigger; snapped the same way.
        tp1_quantity_fraction: Fraction of the position TP1 takes, in (0, 1]. Passed by the
            caller (EXEC-07 / O-02: the constant lives in the backtest semantics, not here).
        filters: LOT_SIZE, MARKET_LOT_SIZE, tick and MIN_NOTIONAL for the symbol.
        side: "LONG" or "SHORT" (the position side).
        position_mode: "ONE_WAY" (reduceOnly on TP1, positionSide BOTH) or "HEDGE" (explicit
            positionSide, no reduceOnly).
        working_type: The trigger price type from the plan constraint snapshot (D-04).

    Returns:
        Both legs, or a refusal (MIN_QTY_REJECT, NOTIONAL_REJECT) with no legs.
    """
    position = _require_decimal(position_quantity, "position_quantity")
    tp1_raw = _require_decimal(tp1_trigger_price, "tp1_trigger_price")
    tp2_raw = _require_decimal(tp2_trigger_price, "tp2_trigger_price")
    fraction = _require_decimal(tp1_quantity_fraction, "tp1_quantity_fraction")
    if position <= 0:
        raise ValueError(f"position_quantity must be > 0, got {position}")
    if fraction <= 0 or fraction > 1:
        raise ValueError(f"tp1_quantity_fraction must be in (0, 1], got {fraction}")
    if side not in (_LONG, _SHORT):
        raise ValueError(f"side must be {_LONG!r} or {_SHORT!r}, got {side!r}")
    if position_mode not in (_ONE_WAY, _HEDGE):
        raise ValueError(f"position_mode must be {_ONE_WAY!r} or {_HEDGE!r}, got {position_mode!r}")
    if working_type not in _WORKING_TYPES:
        raise ValueError(f"working_type must be one of {_WORKING_TYPES}, got {working_type!r}")

    protective_side = "SELL" if side == _LONG else "BUY"
    leg_position_side = _BOTH if position_mode == _ONE_WAY else side
    tp_rounding = tp_trigger_rounding(candidate_position_side=side)
    tp1_trigger = quantize_price(
        price=tp1_raw, price_tick_size=filters.price_tick_size, direction=tp_rounding
    )
    tp2_trigger = quantize_price(
        price=tp2_raw, price_tick_size=filters.price_tick_size, direction=tp_rounding
    )
    # Gate order of the frozen sizing: minimum quantity first, then notional at the TP1 trigger.
    raw_tp1 = _mul(position, fraction)
    tp1_qty = quantize_to_lot(quantity=raw_tp1, filters=filters, market_exit=True)
    tp1_qty = min(tp1_qty, position)  # never above the closable position (T-19-17)
    if tp1_qty <= 0:
        return _refusal(_MIN_QTY_REJECT)
    if _mul(tp1_qty, tp1_trigger) < filters.min_notional:
        return _refusal(_NOTIONAL_REJECT)
    tp1_qty = _match_step_exponent(tp1_qty, filters.lot_step_size)
    tp1_leg: dict[str, Any] = {
        "side": protective_side,
        "position_side": leg_position_side,
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": tp1_trigger,
        "close_position": False,
        "quantity": tp1_qty,
        "reduce_only": True if position_mode == _ONE_WAY else None,
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
