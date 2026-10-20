"""Binding of an approved plan to what is placed (Phase 19, plan 19-02).

What the human approved is exactly what the exchange receives. This module is pure:
stdlib, Decimal, `src.domain`, `src.core.planner` and `src.execution.placement` only;
no clock, no float, no SDK. Every refusal is a NO_TRADE with a reason code, decided
before any adapter call.

- D-01 / research F2: `TradePlan` has no symbol or side field, so the binding rests on the
  persisted `Signal` reached by `plan.signal_id`. The plan hash is re-derived with the
  planner's unchanged algorithm (`plan_hash_from_fields`); symbol and direction are NOT
  added to the hash (D051 item c, a one-way door already walked). The Signal's symbol and
  direction are cross-checked against the hash-bound geometry (stop below the zone means
  LONG, above means SHORT), the plan constraint snapshot and the caller; a caller value
  that disagrees is a refusal, never an override.
- D-02 (RISK-04): a placement quantity above the approved quantity is refused with
  `QUANTITY_ABOVE_APPROVED` and is never clipped; no clipping helper exists.
- D078 (19-REVIEW WR-01): the plan hash does not cover `quantity_after_rounding` (D051 c), so
  the approved quantity is the one stored on the approval row. `bind_plan` requires the plan's
  quantity to equal it (`PLAN_QUANTITY_MISMATCH`), refuses a row that stores none
  (`APPROVED_QUANTITY_MISSING`), and the bound plan carries the approval's value, never the
  caller's plan object, so the placement check compares with what was stored at approval time.
- D-03 / G4-020: the planner has no tick size (D054 accepted limitation), so
  `check_snapped_geometry` is the post-snap guard: after the entry limit and the SL trigger
  are snapped to the tick grid the stop must still sit strictly outside the entry zone.
- D-04 (D037): protective orders trigger on MARK_PRICE; the plan constraint snapshot's
  working type must equal `PROTECTIVE_WORKING_TYPE`.
- Research F3 / P13: the new reason codes are plain strings, deliberately NOT
  `RejectionReason` values and not routed through `PlacementGateVerdict`. A plan or
  approval hash mismatch reuses `RejectionReason.STALE_SETUP.value`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from src.core.planner import plan_hash_from_fields
from src.domain.enums import RejectionReason
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

# D037: protective stop/take-profit triggers use the mark price.
PROTECTIVE_WORKING_TYPE = "MARK_PRICE"

# Reason codes (GLOSSARY 9.3 in plan 19-17). A hash mismatch is STALE_SETUP.
STALE_SETUP = RejectionReason.STALE_SETUP.value
PLAN_SIGNAL_MISMATCH = "PLAN_SIGNAL_MISMATCH"
PLAN_SYMBOL_MISMATCH = "PLAN_SYMBOL_MISMATCH"
PLAN_SIDE_MISMATCH = "PLAN_SIDE_MISMATCH"
PLAN_QUANTITY_MISMATCH = "PLAN_QUANTITY_MISMATCH"
APPROVED_QUANTITY_MISSING = "APPROVED_QUANTITY_MISSING"
QUANTITY_ABOVE_APPROVED = "QUANTITY_ABOVE_APPROVED"
GEOMETRY_INVALID_AFTER_SNAP = "GEOMETRY_INVALID_AFTER_SNAP"
WORKING_TYPE_NOT_MARK_PRICE = "WORKING_TYPE_NOT_MARK_PRICE"

_OK = "OK"
_LONG = "LONG"
_SHORT = "SHORT"
_BUY = "BUY"
_SELL = "SELL"


@dataclass(frozen=True, kw_only=True)
class BoundPlan:
    """The order identity that is allowed to reach the exchange for one approved plan."""

    trade_plan_id: str
    plan_hash: str
    signal_id: str
    symbol: str
    side: str  # LONG | SHORT (the position side)
    entry_side: str  # BUY for LONG, SELL for SHORT
    exit_side: str  # the opposite of entry_side (protective legs)
    approved_quantity: Decimal


@dataclass(frozen=True)
class BindingVerdict:
    """Outcome of `bind_plan`: bound on success, a named reason code on refusal."""

    ok: bool
    reason_code: str
    bound: BoundPlan | None

    def __post_init__(self) -> None:
        if self.ok:
            if self.reason_code != _OK or self.bound is None:
                raise ValueError("BindingVerdict: ok=True requires reason_code='OK' and bound set")
        elif self.reason_code == _OK or self.bound is not None:
            raise ValueError(
                "BindingVerdict: ok=False requires a non-OK reason_code and bound=None"
            )


def _refuse(reason_code: str) -> BindingVerdict:
    return BindingVerdict(ok=False, reason_code=reason_code, bound=None)


def recompute_plan_hash(trade_plan: TradePlan) -> str:
    """Re-derive the plan hash from the TradePlan's own fields (the planner's algorithm)."""
    return plan_hash_from_fields(
        signal_id=trade_plan.signal_id,
        entry_min_price=trade_plan.entry_min_price,
        entry_max_price=trade_plan.entry_max_price,
        stop_loss_price=trade_plan.stop_loss_price,
        take_profit_json=trade_plan.take_profit_json,
        invalidation_rule_json=trade_plan.invalidation_rule_json,
        expiry_utc=trade_plan.expiry_utc,
    )


def _geometry_side(trade_plan: TradePlan) -> str | None:
    """LONG when the stop is below the zone, SHORT when above, None when inside it."""
    if trade_plan.stop_loss_price < trade_plan.entry_min_price:
        return _LONG
    if trade_plan.stop_loss_price > trade_plan.entry_max_price:
        return _SHORT
    return None


def bind_plan(
    *,
    trade_plan: TradePlan,
    signal: Signal,
    callback_plan_hash: str,
    approval_request_hash: str,
    approval_strategy_version: str,
    approval_parameter_set_id: str,
    approval_parameter_set_hash: str,
    plan_snapshot_symbol: str,
    plan_snapshot_trade_plan_id: str,
    caller_symbol: str,
    caller_side: str,
    approval_quantity: Decimal | None,
) -> BindingVerdict:
    """Bind an approved plan to its Signal, or refuse with the first failing reason code.

    Order (first failure wins): hash, signal, symbol, side, quantity. Symbol and side are
    taken from `signal`; the caller's values are only compared against them, never used.
    The quantity is not in the plan hash (D051 c), so step 5 compares the plan's
    `quantity_after_rounding` with `approval_quantity`, the value stored on the approval row
    (D078): None is `APPROVED_QUANTITY_MISSING`, a different value is `PLAN_QUANTITY_MISMATCH`.
    A non-Decimal `approval_quantity` is a programming error and raises `TypeError`.
    """
    # 1. Hash: recomputed == stored == callback == approval request (APRV-02).
    recomputed = recompute_plan_hash(trade_plan)
    if (
        recomputed != trade_plan.plan_hash
        or callback_plan_hash != trade_plan.plan_hash
        or approval_request_hash != trade_plan.plan_hash
    ):
        return _refuse(STALE_SETUP)

    # 2. Signal: the persisted Signal is the one the plan was built from, and the approval
    #    was issued under the same strategy version and parameter set (APRV-01).
    if (
        signal.signal_id != trade_plan.signal_id
        or signal.strategy_version != approval_strategy_version
        or signal.parameter_set_id != approval_parameter_set_id
        or signal.parameter_set_hash != approval_parameter_set_hash
    ):
        return _refuse(PLAN_SIGNAL_MISMATCH)

    # 3. Symbol: snapshot plan id, snapshot symbol and caller symbol all agree with the Signal.
    if (
        plan_snapshot_trade_plan_id != trade_plan.trade_plan_id
        or plan_snapshot_symbol != signal.symbol
        or caller_symbol != signal.symbol
    ):
        return _refuse(PLAN_SYMBOL_MISMATCH)

    # 4. Side: the Signal direction is a position side, agrees with the geometry and the caller.
    if signal.direction not in (_LONG, _SHORT):
        return _refuse(PLAN_SIDE_MISMATCH)
    if _geometry_side(trade_plan) != signal.direction or caller_side != signal.direction:
        return _refuse(PLAN_SIDE_MISMATCH)

    # 5. Quantity (D078): the plan's quantity must equal the one stored on the approval row.
    if approval_quantity is None:
        return _refuse(APPROVED_QUANTITY_MISSING)
    if not isinstance(approval_quantity, Decimal):
        raise TypeError("bind_plan: approval_quantity must be Decimal or None")
    if trade_plan.quantity_after_rounding != approval_quantity:
        return _refuse(PLAN_QUANTITY_MISMATCH)

    long = signal.direction == _LONG
    return BindingVerdict(
        ok=True,
        reason_code=_OK,
        bound=BoundPlan(
            trade_plan_id=trade_plan.trade_plan_id,
            plan_hash=trade_plan.plan_hash,
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            side=signal.direction,
            entry_side=_BUY if long else _SELL,
            exit_side=_SELL if long else _BUY,
            approved_quantity=approval_quantity,
        ),
    )


def check_quantity_bound(*, placement_quantity: Decimal, approved_quantity: Decimal) -> str | None:
    """Refuse a placement quantity above the approved quantity (D-02, RISK-04).

    Returns None when `placement_quantity <= approved_quantity`, else
    `QUANTITY_ABOVE_APPROVED`. The quantity is never clipped to the approved value: a
    placement above it is a caller bug and the whole placement is refused. Non-Decimal,
    non-finite or non-positive input is a programming error and raises.
    """
    for name, value in (
        ("placement_quantity", placement_quantity),
        ("approved_quantity", approved_quantity),
    ):
        if not isinstance(value, Decimal):
            raise TypeError(f"check_quantity_bound: {name} must be Decimal")
        if not value.is_finite() or value <= Decimal("0"):
            raise ValueError(f"check_quantity_bound: {name} must be finite and positive")
    if placement_quantity > approved_quantity:
        return QUANTITY_ABOVE_APPROVED
    return None


def check_working_type(working_type: str) -> str | None:
    """The plan constraint snapshot's working type must be MARK_PRICE (D-04, D037)."""
    if working_type != PROTECTIVE_WORKING_TYPE:
        return WORKING_TYPE_NOT_MARK_PRICE
    return None


def check_snapped_geometry(
    *,
    side: str,
    limit_price: Decimal,
    sl_trigger_price: Decimal,
    entry_min_price: Decimal,
    entry_max_price: Decimal,
) -> str | None:
    """Post-snap geometry guard (D-03, G4-020).

    Called with the entry limit and the SL trigger AFTER the tick snap. LONG needs
    `entry_min <= limit <= entry_max`, `sl_trigger < entry_min` and `sl_trigger < limit`;
    SHORT is the mirror (`sl_trigger > entry_max` and `sl_trigger > limit`). A stop within
    one tick of the zone edge that snaps onto or past the zone gives
    `GEOMETRY_INVALID_AFTER_SNAP`. An unknown side is a programming error and raises.
    """
    if side not in (_LONG, _SHORT):
        raise ValueError(f"check_snapped_geometry: unknown side {side!r}")
    if not (entry_min_price <= limit_price <= entry_max_price):
        return GEOMETRY_INVALID_AFTER_SNAP
    if side == _LONG:
        stop_outside = sl_trigger_price < entry_min_price and sl_trigger_price < limit_price
    else:
        stop_outside = sl_trigger_price > entry_max_price and sl_trigger_price > limit_price
    return None if stop_outside else GEOMETRY_INVALID_AFTER_SNAP


def _take_profit_level(levels: object, key: str) -> Decimal:
    if not isinstance(levels, dict) or key not in levels:
        raise ValueError(f"take_profit_json has no {key!r} level")
    raw = levels[key]
    if not isinstance(raw, str):
        raise ValueError(f"take_profit_json {key!r} must be a decimal string")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"take_profit_json {key!r} is not a decimal: {raw!r}") from exc
    if not value.is_finite() or value <= Decimal("0"):
        raise ValueError(f"take_profit_json {key!r} must be a finite positive price")
    return value


def take_profit_levels(trade_plan: TradePlan) -> tuple[Decimal, Decimal]:
    """Parse (tp1, tp2) from `take_profit_json`; anything else raises ValueError (fail closed)."""
    levels = json.loads(trade_plan.take_profit_json)
    return _take_profit_level(levels, "tp1"), _take_profit_level(levels, "tp2")


__all__ = [
    "APPROVED_QUANTITY_MISSING",
    "GEOMETRY_INVALID_AFTER_SNAP",
    "PLAN_QUANTITY_MISMATCH",
    "PLAN_SIDE_MISMATCH",
    "PLAN_SIGNAL_MISMATCH",
    "PLAN_SYMBOL_MISMATCH",
    "PROTECTIVE_WORKING_TYPE",
    "QUANTITY_ABOVE_APPROVED",
    "STALE_SETUP",
    "WORKING_TYPE_NOT_MARK_PRICE",
    "BindingVerdict",
    "BoundPlan",
    "bind_plan",
    "check_quantity_bound",
    "check_snapped_geometry",
    "check_working_type",
    "recompute_plan_hash",
    "take_profit_levels",
]
