"""Pure placement math helpers (Phase 9, plans 09-01 + 09-02).

Per D-05: the execution core is dependency-free (stdlib + Decimal +
`src/core/_decimal.py` only). All placement math — limit-price
derivation, SL-trigger derivation, protective sizing to filled quantity
— runs in Decimal with pinned precision. The adapter converts to the
SDK's native numeric type at the SDK boundary via string-mediated
Decimal-to-edge conversion (RESEARCH Pattern 1).

The module is dependency-free: stdlib + `src/core/_decimal.py` only.
No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.core._decimal import _add, _div, _mul
from src.risk.types import ConstraintSnapshot

# --------------------------------------------------------------------------- #
# Reason code constants — use enum values for byte-identity with GLOSSARY §9.
# --------------------------------------------------------------------------- #

_OK = "OK"
_MIN_QTY_REJECT = "MIN_QTY_REJECT"
_NOTIONAL_REJECT = "NOTIONAL_REJECT"
_EXCHANGE_CONSTRAINT = "EXCHANGE_CONSTRAINT"

# Position mode constants.
_ONE_WAY = "ONE_WAY"
_HEDGE = "HEDGE"

# Position side constants.
_LONG = "LONG"
_SHORT = "SHORT"
_BOTH = "BOTH"


# --------------------------------------------------------------------------- #
# Frozen dataclasses — the public protective-sizing contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProtectiveTemplate:
    """The protective levels and TP1 split fraction from the plan.

    `tp1_quantity_fraction` is the fraction of filled quantity that TP1
    takes (e.g., 0.5 for half). The remainder is closed by TP2's
    close-all leg.
    """

    stop_loss_trigger_price: Decimal
    tp1_trigger_price: Decimal
    tp2_trigger_price: Decimal
    tp1_quantity_fraction: Decimal

    def __post_init__(self) -> None:
        for fname in (
            "stop_loss_trigger_price",
            "tp1_trigger_price",
            "tp2_trigger_price",
            "tp1_quantity_fraction",
        ):
            value = getattr(self, fname)
            if not isinstance(value, Decimal):
                raise TypeError(
                    f"{fname} must be Decimal, got {type(value).__name__}"
                )
        if self.tp1_quantity_fraction < Decimal("0") or self.tp1_quantity_fraction > Decimal("1"):
            raise ValueError(
                f"tp1_quantity_fraction must be in [0, 1], got {self.tp1_quantity_fraction}"
            )


@dataclass(frozen=True)
class ProtectiveSizing:
    """The result of `size_protectives_to_filled_qty`.

    `is_no_trade=True` carries a canonical RejectionReason value in
    `reason_code` (MIN_QTY_REJECT, NOTIONAL_REJECT, EXCHANGE_CONSTRAINT).
    On reject, all three legs are None.

    `is_no_trade=False` carries reason_code="OK" and three populated
    leg dicts (sl_leg, tp1_leg, tp2_leg) with mode-correct parameters.
    """

    is_no_trade: bool
    reason_code: str
    sl_leg: dict[str, Any] | None
    tp1_leg: dict[str, Any] | None
    tp2_leg: dict[str, Any] | None

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        if self.is_no_trade:
            if self.reason_code == _OK:
                raise ValueError(
                    "ProtectiveSizing: is_no_trade=True requires reason_code != 'OK'"
                )
            if self.sl_leg is not None or self.tp1_leg is not None or self.tp2_leg is not None:
                raise ValueError(
                    "ProtectiveSizing: is_no_trade=True requires all legs to be None"
                )
        else:
            if self.reason_code != _OK:
                raise ValueError(
                    f"ProtectiveSizing: is_no_trade=False requires reason_code='OK', "
                    f"got {self.reason_code!r}"
                )
            if self.sl_leg is None or self.tp1_leg is None or self.tp2_leg is None:
                raise ValueError(
                    "ProtectiveSizing: is_no_trade=False requires all legs populated"
                )


# --------------------------------------------------------------------------- #
# Public entry points.
# --------------------------------------------------------------------------- #


def derive_limit_price(
    *,
    entry_min_price: Decimal,
    entry_max_price: Decimal,
) -> Decimal:
    """Return the zone-mid limit price for a LIMIT_ZONE entry.

    Per D-02 (Phase 5): zone-mid entry_ref = (entry_min + entry_max) / 2.
    Pinned prec-28 so ambient context mutations cannot change the value.

    Args:
        entry_min_price: The lower bound of the entry zone.
        entry_max_price: The upper bound of the entry zone.

    Returns:
        The zone-mid Decimal limit price.
    """
    return _div(_add(entry_min_price, entry_max_price), Decimal("2"))


def derive_sl_trigger_price(*, stop_loss_price: Decimal) -> Decimal:
    """Return the SL trigger price for a CONDITIONAL STOP_MARKET leg.

    For a one-way LONG entry, the SL trigger equals the plan's
    stop_loss_price directly. For a one-way SHORT entry, the SL
    trigger also equals the plan's stop_loss_price (the exchange
    interprets the side to determine trigger direction).

    Args:
        stop_loss_price: The plan's stop_loss_price.

    Returns:
        The SL trigger Decimal price.
    """
    return stop_loss_price


def quantize_protective_qty(
    *,
    raw_quantity: Decimal,
    constraint_snapshot: ConstraintSnapshot,
    reference_price: Decimal,
) -> tuple[Decimal, str | None]:
    """Floor raw quantity to stepSize and apply min-qty/notional gates.

    Mirrors `src/risk/quantization.py:quantize` gate order (first
    failure wins):
      1. `rounded < min_quantity` → `MIN_QTY_REJECT`
      2. `rounded × reference_price < min_notional` → `NOTIONAL_REJECT`

    Defensive fail-closed: zero/negative `quantity_step_size` or
    `reference_price` returns `EXCHANGE_CONSTRAINT`.

    Args:
        raw_quantity: The unfloored quantity (e.g., filled_qty * tp1_fraction).
        constraint_snapshot: The exchangeInfo-derived constraints.
        reference_price: The price used for the notional check (TP1 trigger).

    Returns:
        A tuple of (rounded_quantity, reason_code). On accept,
        reason_code is None. On reject, rounded_quantity is the
        floored value and reason_code is the canonical rejection.
    """
    if not isinstance(raw_quantity, Decimal):
        raise TypeError(
            f"raw_quantity must be Decimal, got {type(raw_quantity).__name__}"
        )
    if not isinstance(reference_price, Decimal):
        raise TypeError(
            f"reference_price must be Decimal, got {type(reference_price).__name__}"
        )

    # Defensive: zero/negative step_size or reference_price → fail closed.
    if constraint_snapshot.quantity_step_size <= Decimal("0"):
        return (raw_quantity, _EXCHANGE_CONSTRAINT)
    if reference_price <= Decimal("0"):
        return (raw_quantity, _EXCHANGE_CONSTRAINT)

    # Exact Decimal floor-division (Pitfall 2 mitigation: never round up).
    steps = raw_quantity // constraint_snapshot.quantity_step_size
    rounded = _mul(steps, constraint_snapshot.quantity_step_size)

    # Gate 1: min-quantity reject.
    if rounded < constraint_snapshot.min_quantity:
        return (rounded, _MIN_QTY_REJECT)

    # Gate 2: notional reject.
    notional = _mul(rounded, reference_price)
    if notional < constraint_snapshot.min_notional:
        return (rounded, _NOTIONAL_REJECT)

    return (rounded, None)


def size_protectives_to_filled_qty(
    *,
    filled_quantity: Decimal,
    protective_template: ProtectiveTemplate,
    constraint_snapshot: ConstraintSnapshot,
    position_mode: str,
    candidate_position_side: str,
) -> ProtectiveSizing:
    """Size protective legs to the actual filled quantity (D-02).

    Per D-02: protective exits are sized against the actual filled
    quantity (never the planned quantity). Partial fills are first-class.

    Mode-correct parameter matrix (per EXECUTION_SPEC §5):
      - One-way: SL close_position=True with quantity=None; TP1 explicit
        quantity with reduce_only=True; TP2 close_position=True.
      - Hedge: same legs + explicit positionSide (LONG/SHORT), with
        reduce_only OMITTED everywhere. closePosition forbidden on
        BUY-in-LONG / SELL-in-SHORT sides (enforced by side derivation).

    Args:
        filled_quantity: The actual filled quantity from the entry.
        protective_template: The protective levels and TP1 split fraction.
        constraint_snapshot: The exchangeInfo-derived constraints.
        position_mode: "ONE_WAY" or "HEDGE".
        candidate_position_side: "LONG" or "SHORT".

    Returns:
        A `ProtectiveSizing` with mode-correct leg parameters, or a
        fail-closed rejection if the filled quantity is sub-minimum.
    """
    if not isinstance(filled_quantity, Decimal):
        raise TypeError(
            f"filled_quantity must be Decimal, got {type(filled_quantity).__name__}"
        )
    if position_mode not in (_ONE_WAY, _HEDGE):
        raise ValueError(
            f"position_mode must be {_ONE_WAY!r} or {_HEDGE!r}, got {position_mode!r}"
        )
    if candidate_position_side not in (_LONG, _SHORT):
        raise ValueError(
            f"candidate_position_side must be {_LONG!r} or {_SHORT!r}, "
            f"got {candidate_position_side!r}"
        )

    # Derive the protective side (opposite of entry side).
    protective_side = "SELL" if candidate_position_side == _LONG else "BUY"

    # Derive the position_side for hedge mode.
    if position_mode == _ONE_WAY:
        leg_position_side = _BOTH
    else:
        leg_position_side = candidate_position_side

    # Compute TP1 quantity: filled_qty * tp1_fraction, floored to stepSize.
    raw_tp1_qty = _mul(filled_quantity, protective_template.tp1_quantity_fraction)
    tp1_qty, tp1_reject = quantize_protective_qty(
        raw_quantity=raw_tp1_qty,
        constraint_snapshot=constraint_snapshot,
        reference_price=protective_template.tp1_trigger_price,
    )
    if tp1_reject is not None:
        return ProtectiveSizing(
            is_no_trade=True,
            reason_code=tp1_reject,
            sl_leg=None,
            tp1_leg=None,
            tp2_leg=None,
        )

    # Build the SL leg (close-all, no quantity).
    sl_leg: dict[str, Any] = {
        "side": protective_side,
        "position_side": leg_position_side,
        "algo_type": "CONDITIONAL",
        "type": "STOP_MARKET",
        "trigger_price": protective_template.stop_loss_trigger_price,
        "close_position": True,
        "quantity": None,
        "reduce_only": None,
        "working_type": "MARK_PRICE",
    }

    # Build the TP1 leg (explicit qty, reduce_only per mode).
    if position_mode == _ONE_WAY:
        tp1_reduce_only: bool | None = True
    else:
        # Hedge mode: reduceOnly OMITTED everywhere (Pitfall 1).
        tp1_reduce_only = None

    tp1_leg: dict[str, Any] = {
        "side": protective_side,
        "position_side": leg_position_side,
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": protective_template.tp1_trigger_price,
        "close_position": False,
        "quantity": tp1_qty,
        "reduce_only": tp1_reduce_only,
        "working_type": "MARK_PRICE",
    }

    # Build the TP2 leg (close-all, no quantity).
    tp2_leg: dict[str, Any] = {
        "side": protective_side,
        "position_side": leg_position_side,
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": protective_template.tp2_trigger_price,
        "close_position": True,
        "quantity": None,
        "reduce_only": None,
        "working_type": "MARK_PRICE",
    }

    return ProtectiveSizing(
        is_no_trade=False,
        reason_code=_OK,
        sl_leg=sl_leg,
        tp1_leg=tp1_leg,
        tp2_leg=tp2_leg,
    )


__all__ = [
    "derive_limit_price",
    "derive_sl_trigger_price",
    "quantize_protective_qty",
    "size_protectives_to_filled_qty",
    "ProtectiveTemplate",
    "ProtectiveSizing",
]
