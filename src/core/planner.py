"""Pure trade planner — SETUP → TradePlan (Phase 4, plan 04-01).

Per D-08/D-09: every SETUP produces exactly one TradePlan filling the
existing `src/domain/trade_plan.py` shape. Entry zone from
`entry_buffer_atr`, SL from `sl_buffer_atr`, TP1 at `minimum_rr`, TP2
extension, invalidation JSON, expiry = source_close + signal_expiry_hours,
plan_hash = SHA256 over canonical JSON. RR below `minimum_rr` → NO_TRADE
with `RR_TOO_LOW` (never a downgraded plan).

Quantization fields are populated with Decimal planner-side estimates
for shape completeness, but exchange rounding/minimums enforcement stays
Phase 5. Planner NEVER floor/round-up against stepSize — it records
pre-risk quantities and marks `quantization_decision = "DEFERRED_TO_RISK"`
so Phase 5 owns identical-everywhere math.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from src.domain.canonical import sha256_hex
from src.domain.enums import RejectionReason, TradePlanStatus
from src.domain.ids import derive_child_id
from src.domain.registry import ParameterSet
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

from .features import compute_features
from .types import AccountState, Candle, MarketSnapshot


# --------------------------------------------------------------------------- #
# Decimal helpers — pinned local context (D-10).
# --------------------------------------------------------------------------- #


def _q(x: Decimal | int | str) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, str):
        return Decimal(x)
    raise TypeError(f"_q: unsupported type {type(x).__name__}")


def _div(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        return a / b


def _mul(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        return a * b


def _add(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        return a + b


def _sub(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        return a - b


# --------------------------------------------------------------------------- #
# Plan hash — D-08 canonical-hash discipline.
# --------------------------------------------------------------------------- #


def _plan_hash(
    *,
    signal_id: str,
    entry_min_price: Decimal,
    entry_max_price: Decimal,
    stop_loss_price: Decimal,
    take_profit_json: str,
    invalidation_rule_json: str,
    expiry_utc: datetime,
) -> str:
    """SHA256 over canonical JSON of the plan's identity-bearing fields.

    Per D-08: mirrors the D-04 canonical-hash discipline. Sorted keys,
    compact separators, Decimal-as-str, datetime → UTC isoformat.
    """
    return sha256_hex(
        {
            "signal_id": signal_id,
            "entry_min_price": entry_min_price,
            "entry_max_price": entry_max_price,
            "stop_loss_price": stop_loss_price,
            "take_profit_json": take_profit_json,
            "invalidation_rule_json": invalidation_rule_json,
            "expiry_utc": expiry_utc,
        }
    )


# --------------------------------------------------------------------------- #
# Public entry point — plan.
# --------------------------------------------------------------------------- #


def plan(
    *,
    signal: Signal,
    setup_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
    created_at_utc: datetime,
) -> TradePlan:
    """Build a TradePlan from a SETUP signal + the 1H candle stream.

    The planner recomputes features on the 1H setup stream — the same
    features the strategy already validated — to keep a single
    deterministic computation path (no double-source-of-truth). Entry
    zone from `entry_buffer_atr`, SL from `sl_buffer_atr`, TP1 at
    `minimum_rr`, TP2 extension, invalidation JSON, expiry =
    source_close + signal_expiry_hours, plan_hash via canonical SHA256.

    RR below `minimum_rr` raises `ValueError` (the strategy gate should
    have caught this earlier; the planner is the second line of defense).
    """
    # Pull parameters.
    entry_buffer_atr = parameter_set.params["entry_buffer_atr"]
    sl_buffer_atr = parameter_set.params["sl_buffer_atr"]
    minimum_rr = parameter_set.params["minimum_rr"]
    signal_expiry_hours = int(parameter_set.params["signal_expiry_hours"])
    risk_rate = parameter_set.params["risk_rate"]
    if not isinstance(entry_buffer_atr, Decimal):
        entry_buffer_atr = Decimal(str(entry_buffer_atr))
    if not isinstance(sl_buffer_atr, Decimal):
        sl_buffer_atr = Decimal(str(sl_buffer_atr))
    if not isinstance(minimum_rr, Decimal):
        minimum_rr = Decimal(str(minimum_rr))
    if not isinstance(risk_rate, Decimal):
        risk_rate = Decimal(str(risk_rate))

    # Compute features on the setup stream (deterministic; same path as strategy).
    setup_frame = compute_features(
        symbol=signal.symbol,
        interval=setup_candles[0].interval,
        candles=setup_candles,
        parameter_set=parameter_set,
    )
    if not setup_frame.features_valid:
        raise ValueError(
            f"plan: features invalid at bar {setup_frame.bar_index} "
            f"(rejection={setup_frame.atr_14.reason_code})"
        )
    assert setup_frame.atr_14.value is not None
    assert setup_frame.swing_high.value is not None
    assert setup_frame.swing_low.value is not None
    assert setup_frame.zone_upper.value is not None
    assert setup_frame.zone_lower.value is not None

    atr = setup_frame.atr_14.value
    swing_high = setup_frame.swing_high.value
    swing_low = setup_frame.swing_low.value
    zone_upper = setup_frame.zone_upper.value
    zone_lower = setup_frame.zone_lower.value

    # Entry zone: zone ± entry_buffer_atr * ATR.
    entry_buffer = _mul(entry_buffer_atr, atr)
    if signal.direction == "LONG":
        entry_min = _sub(zone_lower, entry_buffer)
        entry_max = _add(zone_upper, entry_buffer)
        stop_loss = _sub(swing_low, _mul(sl_buffer_atr, atr))
    else:
        entry_min = _sub(zone_lower, entry_buffer)
        entry_max = _add(zone_upper, entry_buffer)
        stop_loss = _add(swing_high, _mul(sl_buffer_atr, atr))

    # Reference entry = midpoint of the zone (deterministic, no fill model).
    entry_ref = _div(_add(entry_min, entry_max), _q("2"))

    # Risk = |entry_ref - stop_loss|.
    risk = abs(_sub(entry_ref, stop_loss))
    if risk <= Decimal("0"):
        raise ValueError(
            f"plan: risk {risk} must be > 0 (entry_ref={entry_ref}, stop={stop_loss})"
        )

    # TP1 at minimum_rr; TP2 extension = 2 * minimum_rr (simple documented rule).
    if signal.direction == "LONG":
        tp1 = _add(entry_ref, _mul(minimum_rr, risk))
        tp2 = _add(entry_ref, _mul(_mul(_q("2"), minimum_rr), risk))
    else:
        tp1 = _sub(entry_ref, _mul(minimum_rr, risk))
        tp2 = _sub(entry_ref, _mul(_mul(_q("2"), minimum_rr), risk))

    # RR gate — RR < minimum_rr → NO_TRADE (D-08: never a downgraded plan).
    realized_rr = _div(abs(_sub(tp1, entry_ref)), risk)
    if realized_rr < minimum_rr:
        raise ValueError(
            f"plan: realized RR {realized_rr} < minimum_rr {minimum_rr} "
            f"(rejection={RejectionReason.RR_TOO_LOW.value})"
        )

    # Expiry = source_close + signal_expiry_hours.
    expiry_utc = signal.source_candle_close_utc + timedelta(hours=signal_expiry_hours)

    # JSON-as-TEXT fields (DATA_MODEL §5).
    take_profit_json = json.dumps(
        {
            "tp1": str(tp1),
            "tp2": str(tp2),
            "tp1_role": "TAKE_PROFIT_1",
            "tp2_role": "TAKE_PROFIT_2",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    invalidation_rule_json = json.dumps(
        {
            "basis": "structure_break_candle_close",
            "direction": signal.direction,
            "stop_loss_price": str(stop_loss),
            "expiry_utc": expiry_utc.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_rr_json = json.dumps(
        {
            "tp1_rr": str(realized_rr),
            "tp2_rr": str(_div(abs(_sub(tp2, entry_ref)), risk)),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    # Quantization estimates (D-09: DEFERRED_TO_RISK; Phase 5 owns stepSize math).
    risk_budget = _mul(account_state.equity, risk_rate)
    # suggested_quantity = risk_budget / risk (pre-rounding; Phase 5 floors).
    suggested_quantity = _div(risk_budget, risk)
    quantity_before_rounding = suggested_quantity
    quantity_after_rounding = suggested_quantity  # Phase 5 floors; planner passes through

    # Plan hash.
    plan_hash_value = _plan_hash(
        signal_id=signal.signal_id,
        entry_min_price=entry_min,
        entry_max_price=entry_max,
        stop_loss_price=stop_loss,
        take_profit_json=take_profit_json,
        invalidation_rule_json=invalidation_rule_json,
        expiry_utc=expiry_utc,
    )

    # TradePlan ID via derive_child_id with discriminator "trade_plan:v1".
    trade_plan_id = derive_child_id(signal.signal_id, "trade_plan:v1")

    return TradePlan(
        trade_plan_id=trade_plan_id,
        signal_id=signal.signal_id,
        trade_plan_version="v1",
        entry_model="LIMIT_ZONE",
        entry_min_price=entry_min,
        entry_max_price=entry_max,
        stop_loss_price=stop_loss,
        take_profit_json=take_profit_json,
        invalidation_rule_json=invalidation_rule_json,
        expiry_utc=expiry_utc,
        expected_rr_json=expected_rr_json,
        risk_rate=risk_rate,
        risk_budget=risk_budget,
        suggested_quantity=suggested_quantity,
        quantity_before_rounding=quantity_before_rounding,
        quantity_after_rounding=quantity_after_rounding,
        quantization_decision="DEFERRED_TO_RISK",
        plan_hash=plan_hash_value,
        status=TradePlanStatus.READY,
        created_at_utc=created_at_utc,
    )


__all__ = ["plan"]
