"""Full planner contract tests for Phase 4 plan 04-03.

Per D-08/D-09: every SETUP produces exactly one TradePlan filling the
frozen trade_plan shape with entry zone, SL, TP1 at minimum_rr, TP2
extension, invalidation, expiry, expected RR, and plan_hash. RR below
minimum_rr yields NO_TRADE with RR_TOO_LOW, never a downgraded plan.

plan_hash equals sha256_hex over the canonical JSON of signal_id plus
entry plus SL plus TPs plus invalidation plus expiry, recomputable by
hand. Quantization fields carry Decimal planner-side estimates with
quantization_decision DEFERRED_TO_RISK; planner never floors or rounds
against stepSize.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/core/planner.py` is updated to the full contract.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.core.features import compute_features
from src.core.pivots import pivot_at
from src.core.planner import plan
from src.core.types import AccountState, Candle, PlanResult
from src.domain.canonical import canonical_decimal_text, quantize_for_storage, sha256_hex
from src.domain.enums import RejectionReason, TradePlanStatus
from src.domain.ids import derive_child_id
from src.domain.registry import ParameterSet, load_parameter_set

from tests import geometry_builders

# --------------------------------------------------------------------------- #
# Fixtures — the registered baseline-v6 set on a hand-derived Family A window.
#
# Phase 15 (D-19): the first-generation set and the "patched to touch support"
# phase4 CSV window are gone. Family A now plans from a confirmed fractal pivot
# (D-02/D-05): tests/geometry_builders.py `family_a_long_window` is the
# a_long_worked case of tests/fixtures/phase15/DERIVATIONS.md (pivot low 99.00,
# ATR 2.00, zone 98.00-100.00, entry 97.80-100.20, stop 97.40, TP1 106.00).
# --------------------------------------------------------------------------- #

PARAMETER_SET_ID = "baseline-v6"


@pytest.fixture
def window() -> tuple[list[Candle], list[Candle]]:
    """(setup_candles, context_candles) of the a_long_worked window."""
    return geometry_builders.family_a_long_window()


@pytest.fixture
def setup_candles(window: tuple[list[Candle], list[Candle]]) -> list[Candle]:
    """1H setup candles; the last bar touches the pivot zone of the confirmed pivot low."""
    return window[0]


@pytest.fixture
def context_candles(window: tuple[list[Candle], list[Candle]]) -> list[Candle]:
    """4H context candles (BULLISH regime)."""
    return window[1]


@pytest.fixture
def parameter_set() -> ParameterSet:
    """Load trend-pullback/baseline-v6."""
    return load_parameter_set("trend-pullback", PARAMETER_SET_ID)


def _with_override(parameter_set: ParameterSet, key: str, value: Decimal) -> ParameterSet:
    """In-memory copy of `parameter_set` with exactly one parameter replaced (nothing on disk)."""
    return dataclasses.replace(parameter_set, params={**parameter_set.params, key: value})


@pytest.fixture
def account_state() -> AccountState:
    """Standard account state for tests."""
    return AccountState(
        equity=Decimal("10000.00"),
        risk_rate=Decimal("0.005"),
    )


def _get_signal_and_plan(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> PlanResult:
    """Run strategy → plan, return PlanResult."""
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade, f"expected SETUP, got NO_TRADE: {result.reason_code}"
    assert result.signal is not None

    # CR-08: created_at must fall inside the signal's expiry window
    # (source_close + signal_expiry_hours), never after it.
    return plan(
        signal=result.signal,
        setup_candles=setup_candles,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )


# --------------------------------------------------------------------------- #
# Test 1 — entry zone math (D-05): zone = P +/- zone_tolerance_atr x ATR, entry range
# widened by entry_buffer_atr x ATR, stop sl_buffer_atr x ATR beyond entry_min.
# --------------------------------------------------------------------------- #


def test_entry_zone_math_long(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 1: LONG entry zone is built off the confirmed pivot low (D-05, D-06).

    Rewritten for the corrected geometry (the legacy test priced the zone off the trailing
    swing low and put the stop at `swing_low - sl_buffer_atr x ATR`, inside the zone): the
    stop is now `entry_min - sl_buffer_atr x ATR`, strictly below the whole entry zone.
    """
    plan_result = _get_signal_and_plan(setup_candles, context_candles, parameter_set, account_state)
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None
    assert plan_result.trade_plan.signal_id  # signal exists

    frame = compute_features(
        symbol="BTCUSDT",
        interval="1h",
        candles=setup_candles,
        parameter_set=parameter_set,
    )
    assert frame.features_valid
    assert frame.atr_14.value is not None
    pivot_low = pivot_at(
        setup_candles,
        len(setup_candles) - 1,
        lookback=int(parameter_set.params["swing_lookback"]),
        left=int(parameter_set.params["pivot_left_bars"]),
        right=int(parameter_set.params["pivot_right_bars"]),
        high=False,
    )
    assert pivot_low is not None

    entry_buffer_atr = Decimal(str(parameter_set.params["entry_buffer_atr"]))
    sl_buffer_atr = Decimal(str(parameter_set.params["sl_buffer_atr"]))
    zone_tolerance_atr = Decimal(str(parameter_set.params["zone_tolerance_atr"]))
    atr = frame.atr_14.value

    # D-05: zone = P +/- zone_tolerance_atr x ATR.
    half_width = zone_tolerance_atr * atr
    zone_upper = pivot_low + half_width
    zone_lower = pivot_low - half_width
    expected_entry_max = zone_upper + entry_buffer_atr * atr
    expected_entry_min = zone_lower - entry_buffer_atr * atr
    expected_stop = expected_entry_min - sl_buffer_atr * atr

    # D-12: the persisted prices are the geometry rounded to the NUMERIC(38,18)
    # scale (ROUND_HALF_EVEN), so they equal the quantized expected values.
    tp = plan_result.trade_plan
    assert tp.entry_max_price == quantize_for_storage(expected_entry_max)
    assert tp.entry_min_price == quantize_for_storage(expected_entry_min)
    assert tp.stop_loss_price == quantize_for_storage(expected_stop)
    # D-06: the stop lies strictly below the whole entry zone.
    assert tp.stop_loss_price < tp.entry_min_price
    # Cross-check with the hand derivation (DERIVATIONS.md a_long_worked).
    assert (pivot_low, atr) == (Decimal("99.00"), Decimal("2"))
    assert tp.entry_min_price == Decimal("97.80")
    assert tp.entry_max_price == Decimal("100.20")
    assert tp.stop_loss_price == Decimal("97.40")


# --------------------------------------------------------------------------- #
# Test 2 — RR gate: exact-equality pass, one-tick-above pass.
#
# The a_long_worked plan has entry_ref 99.00, stop 97.40, TP1 106.00 (hand-derived), so
# its RR to TP1 is 7.00 / 1.60 = 4.375 exactly (expected_rr_json tp1_rr).
# --------------------------------------------------------------------------- #

_RR_TP1 = Decimal("4.375")


def _plan_with_minimum_rr(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
    minimum_rr: Decimal,
) -> PlanResult:
    """Plan with `minimum_rr` replaced in an in-memory copy of baseline-v6 (one override)."""
    signal, created = _valid_signal_and_params(
        setup_candles, context_candles, parameter_set, account_state
    )
    return plan(
        signal=signal,
        setup_candles=setup_candles,
        parameter_set=_with_override(parameter_set, "minimum_rr", minimum_rr),
        account_state=account_state,
        created_at_utc=created,
    )


def test_rr_gate_exact_equality_passes(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2a: TP1 RR exactly equal to minimum_rr is admitted.

    The default plan on baseline-v6 is admitted and carries tp1_rr 4.375. Override:
    minimum_rr = 4.375 (the plan's TP1 RR) on an in-memory copy of baseline-v6.
    """
    plan_result = _get_signal_and_plan(setup_candles, context_candles, parameter_set, account_state)
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None
    assert plan_result.trade_plan.status == TradePlanStatus.READY
    assert json.loads(plan_result.trade_plan.expected_rr_json)["tp1_rr"] == str(_RR_TP1)

    at_equality = _plan_with_minimum_rr(
        setup_candles, context_candles, parameter_set, account_state, _RR_TP1
    )
    assert not at_equality.is_no_trade
    assert at_equality.trade_plan is not None
    assert at_equality.trade_plan.status == TradePlanStatus.READY


def test_rr_gate_one_tick_above_passes(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2b: RR one tick above minimum_rr is admitted.

    Override: minimum_rr = 4.374 (one 0.001 tick below the plan's RR 4.375).
    """
    plan_result = _plan_with_minimum_rr(
        setup_candles, context_candles, parameter_set, account_state, Decimal("4.374")
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None


def test_rr_gate_below_returns_no_trade_with_rr_too_low(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2c: RR below minimum_rr returns NO_TRADE with RR_TOO_LOW.

    The legacy test deepened the last bar's low by 500 and asserted only `if plan_result
    .is_no_trade`. Under the corrected geometry a low below the stop is INVALIDATED (D-07),
    so the zone is widened the other way: the last bar's high rises by 500, ATR jumps, the
    stop moves far below entry_ref and the RR to the fixed TP1 collapses. The assertion is
    now unconditional (stronger than before). The perturbation uses no parameter override;
    the boundary check after it overrides minimum_rr = 4.376 (one tick above the plan RR).
    """
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade
    signal = result.signal
    assert signal is not None

    # Perturb the last candle to widen the zone (tall wick; ATR rises, geometry follows).
    perturbed = list(setup_candles)
    last = perturbed[-1]
    perturbed[-1] = Candle(
        symbol=last.symbol,
        interval=last.interval,
        open_time_utc=last.open_time_utc,
        close_time_utc=last.close_time_utc,
        open=last.open,
        high=last.high + Decimal("500.00"),
        low=last.low,
        close=last.close,
        volume=last.volume,
    )

    plan_result = plan(
        signal=signal,
        setup_candles=perturbed,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert isinstance(plan_result, PlanResult)
    assert plan_result.is_no_trade
    assert plan_result.reason_code == RejectionReason.RR_TOO_LOW.value
    assert plan_result.trade_plan is None

    # And the exact boundary: minimum_rr one tick above the plan RR rejects, never downgrades.
    just_above = _plan_with_minimum_rr(
        setup_candles, context_candles, parameter_set, account_state, Decimal("4.376")
    )
    assert just_above.is_no_trade
    assert just_above.reason_code == RejectionReason.RR_TOO_LOW.value
    assert just_above.trade_plan is None


def test_rr_gate_fires_on_structure_tp_below_minimum(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2d (CR-03): TP1 is structure-derived, so the RR gate can fire.

    With minimum_rr raised above the structure-implied RR (override minimum_rr = 1000 on an
    in-memory copy of baseline-v6), the planner must return NO_TRADE with RR_TOO_LOW — the
    gate is a real acceptance threshold, not a tautology.
    """
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade
    signal = result.signal
    assert signal is not None

    strict_params = _with_override(parameter_set, "minimum_rr", Decimal("1000"))
    plan_result = plan(
        signal=signal,
        setup_candles=setup_candles,
        parameter_set=strict_params,
        account_state=account_state,
        created_at_utc=signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert isinstance(plan_result, PlanResult)
    assert plan_result.is_no_trade
    assert plan_result.reason_code == RejectionReason.RR_TOO_LOW.value
    assert plan_result.trade_plan is None


# --------------------------------------------------------------------------- #
# Test 2e — fail-closed envelope (CR-02/CR-08/WR-14): never raise, mismatch
# or stale input returns NO_TRADE with the mapped reason.
# --------------------------------------------------------------------------- #


def _valid_signal_and_params(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
):
    """Run evaluate and return (signal, created_at_inside_expiry)."""
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade
    assert result.signal is not None
    created = result.signal.source_candle_close_utc + timedelta(hours=1)
    return result.signal, created


def test_plan_empty_candles_returns_no_trade(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2e-i (CR-02): empty setup stream returns DATA_STALE, never raises."""
    signal, created = _valid_signal_and_params(
        setup_candles, context_candles, parameter_set, account_state
    )
    plan_result = plan(
        signal=signal,
        setup_candles=[],
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=created,
    )
    assert plan_result.is_no_trade
    assert plan_result.reason_code == RejectionReason.DATA_STALE.value
    assert plan_result.trade_plan is None


def test_plan_expired_signal_returns_no_trade(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2e-ii (CR-08): created_at past expiry returns APPROVAL_EXPIRED."""
    signal, _ = _valid_signal_and_params(
        setup_candles, context_candles, parameter_set, account_state
    )
    plan_result = plan(
        signal=signal,
        setup_candles=setup_candles,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=signal.source_candle_close_utc + timedelta(hours=99),
    )
    assert plan_result.is_no_trade
    assert plan_result.reason_code == RejectionReason.APPROVAL_EXPIRED.value
    assert plan_result.trade_plan is None


def test_plan_symbol_mismatch_returns_no_trade(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2e-iii (WR-14): foreign-symbol candles return DATA_STALE."""
    from dataclasses import replace

    signal, created = _valid_signal_and_params(
        setup_candles, context_candles, parameter_set, account_state
    )
    other = [replace(c, symbol="ETHUSDT") for c in setup_candles]
    plan_result = plan(
        signal=signal,
        setup_candles=other,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=created,
    )
    assert plan_result.is_no_trade
    assert plan_result.reason_code == RejectionReason.DATA_STALE.value
    assert plan_result.trade_plan is None


# --------------------------------------------------------------------------- #
# Test 3 — plan_hash recomputation + trade_plan_id.
# --------------------------------------------------------------------------- #


def test_plan_hash_recomputable_from_payload(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 3a: plan_hash equals sha256_hex over the stored-form payload (D-12)."""
    plan_result = _get_signal_and_plan(setup_candles, context_candles, parameter_set, account_state)
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    tp = plan_result.trade_plan
    expected_hash = sha256_hex(
        {
            "signal_id": tp.signal_id,
            "entry_min_price": canonical_decimal_text(tp.entry_min_price),
            "entry_max_price": canonical_decimal_text(tp.entry_max_price),
            "stop_loss_price": canonical_decimal_text(tp.stop_loss_price),
            "take_profit_json": tp.take_profit_json,
            "invalidation_rule_json": tp.invalidation_rule_json,
            "expiry_utc": tp.expiry_utc,
        }
    )
    assert tp.plan_hash == expected_hash


def test_persisted_decimals_fit_numeric_38_18(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """D-12: every persisted Decimal and every TP price has at most 18 fractional digits."""
    plan_result = _get_signal_and_plan(setup_candles, context_candles, parameter_set, account_state)
    assert plan_result.trade_plan is not None
    tp = plan_result.trade_plan
    persisted = {
        "entry_min_price": tp.entry_min_price,
        "entry_max_price": tp.entry_max_price,
        "stop_loss_price": tp.stop_loss_price,
        "risk_rate": tp.risk_rate,
        "risk_budget": tp.risk_budget,
        "suggested_quantity": tp.suggested_quantity,
        "quantity_before_rounding": tp.quantity_before_rounding,
        "quantity_after_rounding": tp.quantity_after_rounding,
    }
    tp_prices = json.loads(tp.take_profit_json)
    persisted["tp1"] = Decimal(tp_prices["tp1"])
    persisted["tp2"] = Decimal(tp_prices["tp2"])
    for name, value in persisted.items():
        quantized = quantize_for_storage(value)
        assert value == quantized, name
        exponent = value.as_tuple().exponent
        assert isinstance(exponent, int)
        assert exponent >= -18, f"{name} has more than 18 fractional digits: {value}"


def test_plan_hash_is_spelling_invariant() -> None:
    """D-12: 50000, 50000.0 and the scale-18 read-back spelling hash identically."""
    from src.core.planner import _plan_hash

    base = dict(
        signal_id="sig",
        take_profit_json='{"tp1":"1"}',
        invalidation_rule_json='{"basis":"CANDLE_CLOSE"}',
        expiry_utc=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
    )
    hashes = {
        _plan_hash(
            entry_min_price=Decimal(a),
            entry_max_price=Decimal(b),
            stop_loss_price=Decimal(c),
            **base,
        )
        for a, b, c in [
            ("50000", "51000", "49000"),
            ("50000.0", "51000.0", "49000.0"),
            ("50000.000000000000000000", "51000.000000000000000000", "49000.000000000000000000"),
        ]
    }
    assert len(hashes) == 1


def test_trade_plan_id_derives_from_signal_id(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 3b: trade_plan_id = derive_child_id(signal_id, "trade_plan:v1")."""
    plan_result = _get_signal_and_plan(setup_candles, context_candles, parameter_set, account_state)
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    expected_id = derive_child_id(plan_result.trade_plan.signal_id, "trade_plan:v1")
    assert plan_result.trade_plan.trade_plan_id == expected_id


# --------------------------------------------------------------------------- #
# Test 4 — expiry, invalidation schema, deferred quantization.
# --------------------------------------------------------------------------- #


def test_expiry_equals_source_close_plus_signal_expiry_hours(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 4a: expiry_utc = source_candle_close_utc + signal_expiry_hours."""
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade
    signal = result.signal
    assert signal is not None

    plan_result = plan(
        signal=signal,
        setup_candles=setup_candles,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    signal_expiry_hours = int(parameter_set.params["signal_expiry_hours"])
    expected_expiry = signal.source_candle_close_utc + timedelta(hours=signal_expiry_hours)
    assert plan_result.trade_plan.expiry_utc == expected_expiry


def test_invalidation_json_schema(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 4b: invalidation JSON carries basis=CANDLE_CLOSE, level, break_distance."""
    plan_result = _get_signal_and_plan(setup_candles, context_candles, parameter_set, account_state)
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    invalidation = json.loads(plan_result.trade_plan.invalidation_rule_json)
    assert invalidation["basis"] == "CANDLE_CLOSE"
    assert "level" in invalidation
    assert invalidation["level"] == str(plan_result.trade_plan.stop_loss_price)
    assert "break_distance_atr" in invalidation


def test_deferred_quantization_equality(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 4c: quantity_after_rounding == quantity_before_rounding, DEFERRED_TO_RISK."""
    plan_result = _get_signal_and_plan(setup_candles, context_candles, parameter_set, account_state)
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    tp = plan_result.trade_plan
    assert tp.quantization_decision == "DEFERRED_TO_RISK"
    assert tp.quantity_after_rounding == tp.quantity_before_rounding
    assert tp.suggested_quantity == tp.quantity_before_rounding
    assert isinstance(tp.suggested_quantity, Decimal)
    assert isinstance(tp.quantity_before_rounding, Decimal)
    assert isinstance(tp.quantity_after_rounding, Decimal)


# --------------------------------------------------------------------------- #
# Test 5 — no-float guard: src/core/planner.py has no float literals.
# --------------------------------------------------------------------------- #


def test_planner_has_no_float_literals() -> None:
    """Beh. 5: src/core/planner.py contains no float literals or float() calls.

    Per D-10: the pure core is Decimal-only. Float injection would fork
    plan_hash across processes.
    """
    import ast

    path = Path("src/core/planner.py")
    assert path.is_file(), f"missing: {path}"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"planner.py contains float literal at line {node.lineno}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                pytest.fail(f"planner.py contains float() call at line {node.lineno}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "Decimal":
                if node.args and isinstance(node.args[0], ast.Call):
                    inner = node.args[0]
                    if isinstance(inner.func, ast.Name) and inner.func.id == "float":
                        pytest.fail(f"planner.py contains Decimal(float) at line {node.lineno}")


# --------------------------------------------------------------------------- #
# Test 6 — PlanResult envelope: is_no_trade=True requires trade_plan=None.
# --------------------------------------------------------------------------- #


def test_plan_result_envelope_validation() -> None:
    """Beh. 6: PlanResult enforces is_no_trade/trade_plan consistency."""
    result = PlanResult(is_no_trade=True, trade_plan=None, reason_code="RR_TOO_LOW")
    assert result.is_no_trade
    assert result.trade_plan is None

    with pytest.raises(ValueError, match="is_no_trade=True requires trade_plan=None"):
        PlanResult(
            is_no_trade=True,
            trade_plan="not-none",  # type: ignore[arg-type]
            reason_code="RR_TOO_LOW",
        )

    with pytest.raises(ValueError, match="is_no_trade=False requires a TradePlan"):
        PlanResult(is_no_trade=False, trade_plan=None, reason_code="OK")


def test_plan_hash_from_fields_is_the_planner_algorithm(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """The public wrapper equals the private hash on three spellings and the stored plan hash."""
    from src.core.planner import _plan_hash, plan_hash_from_fields

    base = dict(
        signal_id="sig",
        take_profit_json='{"tp1":"1"}',
        invalidation_rule_json='{"basis":"CANDLE_CLOSE"}',
        expiry_utc=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
    )
    for a, b, c in [
        ("50000", "51000", "49000"),
        ("50000.0", "51000.0", "49000.0"),
        ("50000.000000000000000000", "51000.000000000000000000", "49000.000000000000000000"),
    ]:
        fields = dict(
            entry_min_price=Decimal(a),
            entry_max_price=Decimal(b),
            stop_loss_price=Decimal(c),
            **base,
        )
        assert plan_hash_from_fields(**fields) == _plan_hash(**fields)

    plan_result = _get_signal_and_plan(setup_candles, context_candles, parameter_set, account_state)
    assert plan_result.trade_plan is not None
    tp = plan_result.trade_plan
    assert (
        plan_hash_from_fields(
            signal_id=tp.signal_id,
            entry_min_price=tp.entry_min_price,
            entry_max_price=tp.entry_max_price,
            stop_loss_price=tp.stop_loss_price,
            take_profit_json=tp.take_profit_json,
            invalidation_rule_json=tp.invalidation_rule_json,
            expiry_utc=tp.expiry_utc,
        )
        == tp.plan_hash
    )
