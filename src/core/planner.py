"""Pure trade planner — SETUP → TradePlan (Phase 4, plan 04-03).

Per D-08/D-09: every SETUP produces exactly one TradePlan filling the
existing `src/domain/trade_plan.py` shape. Entry/SL geometry is built
from the levels that triggered the setup (CR-05): Family A prices off
its per-side support/resistance zone, Families B/C re-derive the
detector's zone edge from the same candles (the signal carries no
zone). TP1 is structure-derived (opposing extreme / measured move),
never constructed from `minimum_rr` (CR-03) — `minimum_rr` stays purely
an acceptance threshold, so the RR gate can actually fire. Invalidation
JSON carries basis=CANDLE_CLOSE + level + break_distance, expiry =
source_close + signal_expiry_hours, plan_hash = SHA256 over canonical
JSON. RR below `minimum_rr` returns NO_TRADE with `RR_TOO_LOW` (never
a downgraded plan); stale/foreign signals return NO_TRADE, never raise
(CR-02/CR-08/WR-14).

Quantization fields are populated with Decimal planner-side estimates
for shape completeness, but exchange rounding/minimums enforcement stays
Phase 5. Planner NEVER floor/round-up against stepSize — it records
pre-risk quantities and marks `quantization_decision = "DEFERRED_TO_RISK"`
so Phase 5 owns identical-everywhere math.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from src.domain.canonical import sha256_hex
from src.domain.enums import RejectionReason, TradePlanStatus
from src.domain.ids import derive_child_id
from src.domain.registry import ParameterSet
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

# --------------------------------------------------------------------------- #
# Decimal helpers — pinned local context (D-10).
# --------------------------------------------------------------------------- #
# Decimal arithmetic lives in `._decimal` (single pinned-prec source,
# review WR-16); re-exported here for `from .planner import ...` users.
from ._decimal import _add, _div, _mul, _q, _sub  # noqa: F401 (re-export for compat)
from .features import compute_features
from .strategy import _detect_breakout_retest_setup, _detect_range_mr_setup
from .types import AccountState, Candle, PlanResult

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
# Setup-level geometry — entry/SL/TP1 from the trigger levels (CR-05).
# --------------------------------------------------------------------------- #

_Geometry = tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]


def _long_geometry(
    strategy_id: str,
    setup_candles: list[Candle],
    parameter_set: ParameterSet,
    atr: Decimal,
    swing_high: Decimal,
    swing_low: Decimal,
    zone_tolerance_atr: Decimal,
    sl_buffer: Decimal,
) -> _Geometry:
    """Return (zone_upper, zone_lower, stop_loss, tp1) for a LONG signal.

    Family A prices off the support zone; Families B/C re-derive the
    detector's zone edge from the same candles (CR-05) and price the
    entry around that edge with a measured-move TP1 (CR-03). A
    vanished, direction-mismatched, or unknown-family setup returns
    all-None so the caller emits STALE_SETUP.
    """
    if strategy_id == "trend-pullback":
        half = _mul(zone_tolerance_atr, atr)
        support_upper = _add(swing_low, half)
        support_lower = _sub(swing_low, half)
        return (
            support_upper,
            support_lower,
            _sub(swing_low, sl_buffer),
            swing_high,
        )
    if strategy_id == "breakout-retest":
        setup = _detect_breakout_retest_setup(
            setup_candles=setup_candles, parameter_set=parameter_set
        )
        if setup is None or setup[0] != "LONG":
            return (None, None, None, None)
        _direction, _setup_type, zone_upper, zone_lower = setup
        height = _sub(zone_upper, zone_lower)
        return (
            zone_upper,
            zone_upper,
            _sub(zone_lower, sl_buffer),
            _add(zone_upper, height),
        )
    if strategy_id == "range-mr":
        setup = _detect_range_mr_setup(
            setup_candles=setup_candles, parameter_set=parameter_set
        )
        if setup is None or setup[0] != "LONG":
            return (None, None, None, None)
        _direction, _setup_type, zone_upper, zone_lower = setup
        return (
            zone_lower,
            zone_lower,
            _sub(zone_lower, sl_buffer),
            zone_upper,
        )
    return (None, None, None, None)


def _short_geometry(
    strategy_id: str,
    setup_candles: list[Candle],
    parameter_set: ParameterSet,
    atr: Decimal,
    swing_high: Decimal,
    swing_low: Decimal,
    zone_tolerance_atr: Decimal,
    sl_buffer: Decimal,
) -> _Geometry:
    """Return (zone_upper, zone_lower, stop_loss, tp1) for a SHORT signal."""
    if strategy_id == "trend-pullback":
        half = _mul(zone_tolerance_atr, atr)
        resistance_upper = _add(swing_high, half)
        resistance_lower = _sub(swing_high, half)
        return (
            resistance_upper,
            resistance_lower,
            _add(swing_high, sl_buffer),
            swing_low,
        )
    if strategy_id == "breakout-retest":
        setup = _detect_breakout_retest_setup(
            setup_candles=setup_candles, parameter_set=parameter_set
        )
        if setup is None or setup[0] != "SHORT":
            return (None, None, None, None)
        _direction, _setup_type, zone_upper, zone_lower = setup
        height = _sub(zone_upper, zone_lower)
        return (
            zone_lower,
            zone_lower,
            _add(zone_upper, sl_buffer),
            _sub(zone_lower, height),
        )
    if strategy_id == "range-mr":
        setup = _detect_range_mr_setup(
            setup_candles=setup_candles, parameter_set=parameter_set
        )
        if setup is None or setup[0] != "SHORT":
            return (None, None, None, None)
        _direction, _setup_type, zone_upper, zone_lower = setup
        return (
            zone_upper,
            zone_upper,
            _add(zone_upper, sl_buffer),
            zone_lower,
        )
    return (None, None, None, None)


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
) -> PlanResult:
    """Build a TradePlan from a SETUP signal + the 1H candle stream.

    Fail-closed (CR-02/CR-08/WR-14): empty streams, invalid features,
    non-positive risk, expired signals, and any signal-vs-candles (or
    signal-vs-parameter-set) mismatch return NO_TRADE — never raise.
    Geometry comes from the levels that triggered the setup (CR-05):
    the Family-A side zone, or the re-derived Family-B/C detector zone;
    `compute_features` is the validity gate, not the geometry source.
    TP1 is structure-derived and `minimum_rr` is purely an acceptance
    threshold (CR-03), so the RR gate below can actually fire.
    """
    # Signal-vs-candles correspondence (CR-08/WR-14) — before touching
    # setup_candles[0], so an empty stream returns NO_TRADE (CR-02).
    if not setup_candles:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.DATA_STALE.value,
        )
    if signal.symbol != setup_candles[0].symbol:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.DATA_STALE.value,
        )
    if signal.source_timeframe != setup_candles[0].interval:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.DATA_STALE.value,
        )
    if signal.strategy_id != parameter_set.strategy_id:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.DATA_STALE.value,
        )
    if signal.parameter_set_id != parameter_set.parameter_set_id:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.DATA_STALE.value,
        )
    if signal.source_candle_close_utc != setup_candles[-1].close_time_utc:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.STALE_SETUP.value,
        )

    # Pull parameters.
    entry_buffer_atr = parameter_set.params["entry_buffer_atr"]
    sl_buffer_atr = parameter_set.params["sl_buffer_atr"]
    minimum_rr = parameter_set.params["minimum_rr"]
    zone_tolerance_atr = parameter_set.params["zone_tolerance_atr"]
    signal_expiry_hours = int(parameter_set.params["signal_expiry_hours"])
    # WR-03: the account's risk_rate is the single sizing source of
    # truth — the registry copy is not read for sizing.
    risk_rate = account_state.risk_rate
    if not isinstance(entry_buffer_atr, Decimal):
        entry_buffer_atr = Decimal(str(entry_buffer_atr))
    if not isinstance(sl_buffer_atr, Decimal):
        sl_buffer_atr = Decimal(str(sl_buffer_atr))
    if not isinstance(minimum_rr, Decimal):
        minimum_rr = Decimal(str(minimum_rr))
    if not isinstance(zone_tolerance_atr, Decimal):
        zone_tolerance_atr = Decimal(str(zone_tolerance_atr))

    # Expiry = source_close + signal_expiry_hours; an already-expired
    # signal at creation time is NO_TRADE, never a READY plan (CR-08).
    expiry_utc = signal.source_candle_close_utc + timedelta(hours=signal_expiry_hours)
    if expiry_utc <= created_at_utc:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.APPROVAL_EXPIRED.value,
        )

    # Features are the validity gate only (CR-05), never the geometry
    # source. Mixed-symbol/interval streams raise inside — map to
    # NO_TRADE rather than crashing the caller (CR-02).
    try:
        setup_frame = compute_features(
            symbol=signal.symbol,
            interval=signal.source_timeframe,
            candles=setup_candles,
            parameter_set=parameter_set,
        )
    except ValueError:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.DATA_STALE.value,
        )
    if not setup_frame.features_valid:
        reason = RejectionReason.DATA_STALE.value
        for feat in (
            setup_frame.ema_20,
            setup_frame.ema_50,
            setup_frame.ema_200,
            setup_frame.atr_14,
            setup_frame.swing_high,
            setup_frame.swing_low,
            setup_frame.zone_upper,
            setup_frame.zone_lower,
        ):
            if not feat.valid:
                reason = feat.reason_code
                if reason == "GAP_IN_SOURCE":
                    reason = RejectionReason.DATA_STALE.value
                break
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=reason,
        )
    assert setup_frame.atr_14.value is not None
    assert setup_frame.swing_high.value is not None
    assert setup_frame.swing_low.value is not None

    atr = setup_frame.atr_14.value
    swing_high = setup_frame.swing_high.value
    swing_low = setup_frame.swing_low.value

    # Geometry from the trigger levels (CR-05/WR-01): per-side zones —
    # LONG off support, SHORT off resistance. Families B/C re-derive
    # the detector's zone edge; a vanished/mismatched setup at plan
    # time is STALE_SETUP, never a repriced plan.
    entry_buffer = _mul(entry_buffer_atr, atr)
    sl_buffer = _mul(sl_buffer_atr, atr)
    if signal.direction == "LONG":
        zone_upper, zone_lower, stop_loss, take_profit_1 = _long_geometry(
            signal.strategy_id,
            setup_candles,
            parameter_set,
            atr,
            swing_high,
            swing_low,
            zone_tolerance_atr,
            sl_buffer,
        )
    elif signal.direction == "SHORT":
        zone_upper, zone_lower, stop_loss, take_profit_1 = _short_geometry(
            signal.strategy_id,
            setup_candles,
            parameter_set,
            atr,
            swing_high,
            swing_low,
            zone_tolerance_atr,
            sl_buffer,
        )
    else:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.DATA_STALE.value,
        )
    if zone_upper is None or zone_lower is None or stop_loss is None:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.STALE_SETUP.value,
        )
    assert take_profit_1 is not None
    entry_min = _sub(zone_lower, entry_buffer)
    entry_max = _add(zone_upper, entry_buffer)

    # Reference entry = midpoint of the zone (deterministic, no fill model).
    # Per 04-03 checkpoint:decision option A: entry_ref = zone mid for LIMIT_ZONE.
    entry_ref = _div(_add(entry_min, entry_max), _q("2"))

    # Risk = |entry_ref - stop_loss|; non-positive risk is NO_TRADE (CR-02).
    risk = abs(_sub(entry_ref, stop_loss))
    if risk <= Decimal("0"):
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.RR_TOO_LOW.value,
        )

    # TP2 extends the structure move: entry ± 2 * (TP1 − entry).
    tp1 = take_profit_1
    tp1_leg = _sub(tp1, entry_ref) if signal.direction == "LONG" else _sub(entry_ref, tp1)
    if signal.direction == "LONG":
        tp2 = _add(entry_ref, _mul(_q("2"), tp1_leg))
    else:
        tp2 = _sub(entry_ref, _mul(_q("2"), tp1_leg))

    # RR gate — TP1 is structure-derived, so this gate can fire (CR-03).
    realized_rr = _div(abs(_sub(tp1, entry_ref)), risk)
    if realized_rr < minimum_rr:
        return PlanResult(
            is_no_trade=True,
            trade_plan=None,
            reason_code=RejectionReason.RR_TOO_LOW.value,
        )

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
    # Invalidation schema (D-08): basis=CANDLE_CLOSE, level=stop_loss_price,
    # break_distance_atr = sl_buffer_atr * ATR (family-specific break distance).
    break_distance = _mul(sl_buffer_atr, atr)
    invalidation_rule_json = json.dumps(
        {
            "basis": "CANDLE_CLOSE",
            "level": str(stop_loss),
            "break_distance_atr": str(break_distance),
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

    trade_plan = TradePlan(
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

    return PlanResult(
        is_no_trade=False,
        trade_plan=trade_plan,
        reason_code="OK",
    )


__all__ = ["plan"]
