"""Tests for the pure quantization function (Phase 5, plan 05-01).

Per D-02 + RISK_MANAGEMENT §11: `quantize` floors raw quantity via exact
Decimal floor-division, then applies min-quantity reject, notional
reject, and the 60% realized-risk / allowed-risk utilization gate in
fixed order — first failure wins.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/risk/quantization.py` is implemented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from src.core.types import AccountState
from src.domain.enums import TradePlanStatus
from src.domain.trade_plan import TradePlan
from src.risk.quantization import quantize
from src.risk.sizing import size_position
from src.risk.types import ConstraintSnapshot, SizedResult

# --------------------------------------------------------------------------- #
# Helpers — sized result + constraint snapshot factories.
# --------------------------------------------------------------------------- #


def _mk_trade_plan(
    *,
    entry_min: str = "49900.00",
    entry_max: str = "50100.00",
    stop_loss: str = "49000.00",
    risk_rate: str = "0.005",
    risk_budget: str = "50.00000",
    suggested_quantity: str = "0.04995004995004995004995004995",
) -> TradePlan:
    """Build a frozen TradePlan with DEFERRED_TO_RISK estimate fields."""
    return TradePlan(
        trade_plan_id="1" * 64,
        signal_id="2" * 64,
        trade_plan_version="v1",
        entry_model="LIMIT_ZONE",
        entry_min_price=Decimal(entry_min),
        entry_max_price=Decimal(entry_max),
        stop_loss_price=Decimal(stop_loss),
        take_profit_json='{"tp1":"52000.00","tp1_role":"TAKE_PROFIT_1"}',
        invalidation_rule_json='{"basis":"CANDLE_CLOSE","level":"49000.00","break_distance_atr":"20.00"}',
        expiry_utc=datetime(2026, 9, 19, 4, tzinfo=UTC),
        expected_rr_json='{"tp1_rr":"2.0"}',
        risk_rate=Decimal(risk_rate),
        risk_budget=Decimal(risk_budget),
        suggested_quantity=Decimal(suggested_quantity),
        quantity_before_rounding=Decimal(suggested_quantity),
        quantity_after_rounding=Decimal(suggested_quantity),
        quantization_decision="DEFERRED_TO_RISK",
        plan_hash="3" * 64,
        status=TradePlanStatus.READY,
        created_at_utc=datetime(2026, 9, 19, tzinfo=UTC),
    )


def _mk_account_state(equity: str = "10000.00", risk_rate: str = "0.005") -> AccountState:
    return AccountState(equity=Decimal(equity), risk_rate=Decimal(risk_rate))


def _mk_constraints(
    *,
    symbol: str = "BTCUSDT",
    step: str = "0.001",
    min_qty: str = "0.001",
    min_notional: str = "50",
    metadata_observed_at_utc: datetime | None = None,
) -> ConstraintSnapshot:
    """Build a ConstraintSnapshot for tests."""
    return ConstraintSnapshot(
        symbol=symbol,
        price_tick_size=Decimal("0.10"),
        quantity_step_size=Decimal(step),
        min_quantity=Decimal(min_qty),
        min_notional=Decimal(min_notional),
        metadata_observed_at_utc=metadata_observed_at_utc or datetime(2026, 9, 19, tzinfo=UTC),
    )


def _size(
    *,
    equity: str = "10000.00",
    risk_rate: str = "0.005",
    stop_loss: str = "49000.00",
    entry_ref: str = "50000.00",
    costs: str = "1.0",
) -> tuple[SizedResult, Decimal, Decimal]:
    """Run size_position and return (result, allowed_risk, risk_per_unit)."""
    plan = _mk_trade_plan(
        stop_loss=stop_loss,
        risk_rate=risk_rate,
        risk_budget=str(Decimal(equity) * Decimal(risk_rate)),
    )
    account = _mk_account_state(equity=equity, risk_rate=risk_rate)
    allowed_risk = Decimal(equity) * Decimal(risk_rate)
    sl_distance = abs(Decimal(entry_ref) - Decimal(stop_loss))
    risk_per_unit = sl_distance + Decimal(costs)
    result = size_position(
        trade_plan=plan,
        account_state=account,
        entry_ref=Decimal(entry_ref),
        modeled_costs_per_unit=Decimal(costs),
    )
    return result, allowed_risk, risk_per_unit


# --------------------------------------------------------------------------- #
# Test 1 — floor exact step → ACCEPTED, raw == rounded.
# --------------------------------------------------------------------------- #


def test_quantize_floor_exact_step_accepted() -> None:
    """Beh. 1a: raw_quantity is an exact multiple of step_size → ACCEPTED.

    raw_qty / step_size is an exact integer → floor() leaves it
    unchanged; min_qty / notional / utilization all pass.
    """
    sized, allowed_risk, risk_per_unit = _size()
    constraints = _mk_constraints()
    result = quantize(
        sized=sized,
        constraint_snapshot=constraints,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        reference_price=Decimal("50000.00"),
    )
    assert isinstance(result, SizedResult)
    assert result.is_no_trade is False
    assert result.quantization_decision == "ACCEPTED"
    assert result.quantity == result.quantity_after_rounding
    assert result.reason_code == "OK"


# --------------------------------------------------------------------------- #
# Test 2 — one ULP above step rounds DOWN and stays ACCEPTED.
# --------------------------------------------------------------------------- #


def test_quantize_one_ulp_above_step_rounds_down_accepted() -> None:
    """Beh. 1b: raw = step + 1 ULP → floors to step → ACCEPTED.

    Per D-02 + Pitfall 2: the floor never rounds UP. A quantity that is
    just above a step boundary still gets floored (never silently
    increased to the next step).
    """
    # raw_quantity = 0.0024 (just above 2 * step=0.001); floor → 0.002.
    # utilization = 0.002/0.0024 = 0.833 → ACCEPTED.
    sized, allowed_risk, risk_per_unit = _size(
        equity="0.024",
        risk_rate="1.0",  # allowed_risk = 0.024
        stop_loss="49990.00",
        entry_ref="50000.00",
        costs="0.0",
    )
    constraints = _mk_constraints(step="0.001", min_qty="0.001")
    result = quantize(
        sized=sized,
        constraint_snapshot=constraints,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        reference_price=Decimal("50000.00"),
    )
    assert result.quantization_decision == "ACCEPTED"
    assert result.quantity == Decimal("0.002")


# --------------------------------------------------------------------------- #
# Test 3 — rounded < min_quantity → MIN_QTY_REJECT.
# --------------------------------------------------------------------------- #


def test_quantize_below_min_quantity_rejects() -> None:
    """Beh. 1c: rounded_quantity < min_quantity → MIN_QTY_REJECT (first failure)."""
    # raw = 0.005, step = 0.001, rounded = 0.005, min_qty = 0.01 → REJECT.
    sized, allowed_risk, risk_per_unit = _size(
        equity="5.00",
        risk_rate="1.0",  # allowed_risk = 5
        stop_loss="0",  # to make risk_per_unit = 1000 (sl_distance=1000 + costs=0)
        entry_ref="1000",
        costs="0.0",
    )
    constraints = _mk_constraints(step="0.001", min_qty="0.01")
    result = quantize(
        sized=sized,
        constraint_snapshot=constraints,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        reference_price=Decimal("1000.00"),
    )
    assert result.is_no_trade is True
    assert result.quantization_decision == "REJECTED"
    assert result.reason_code == "MIN_QTY_REJECT"


# --------------------------------------------------------------------------- #
# Test 4 — rounded × reference_price < min_notional → NOTIONAL_REJECT.
# --------------------------------------------------------------------------- #


def test_quantize_below_min_notional_rejects() -> None:
    """Beh. 1d: rounded × reference_price < min_notional → NOTIONAL_REJECT.

    Gate order is fixed: min_qty → notional → utilization. First failure wins.
    """
    # raw = 0.1, step = 0.001, rounded = 0.1, min_qty = 0.001 OK.
    # reference_price = 100, notional = 0.1 * 100 = 10 < 50 → REJECT.
    sized, allowed_risk, risk_per_unit = _size(
        equity="1.0",
        risk_rate="1.0",  # allowed_risk = 1
        stop_loss="0",
        entry_ref="10",
        costs="0.0",
    )
    constraints = _mk_constraints(step="0.001", min_qty="0.001", min_notional="50")
    result = quantize(
        sized=sized,
        constraint_snapshot=constraints,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        reference_price=Decimal("100.00"),
    )
    assert result.is_no_trade is True
    assert result.quantization_decision == "REJECTED"
    assert result.reason_code == "NOTIONAL_REJECT"


# --------------------------------------------------------------------------- #
# Test 5 — nonzero-cost UTILIZATION_REJECT distinguishing case (Pitfall 2).
# --------------------------------------------------------------------------- #


def test_quantize_utilization_reject_with_nonzero_costs() -> None:
    """Beh. 1e: realized_risk / allowed_risk < 0.6 → UTILIZATION_REJECT.

    Per D-02 + Pitfall 2: the gate uses realized_risk / allowed_risk,
    NOT rounded / raw_quantity. With nonzero costs, the two metrics
    diverge. Parity fixture pins this exact case.
    """
    # allowed_risk = 1.7; risk_per_unit = 1000 (sl_distance=100, costs=900).
    # raw = 1.7/1000 = 0.0017; step = 0.001; rounded = 0.001.
    # realized_risk = 0.001 * 1000 = 1.0.
    # utilization = 1.0 / 1.7 = 0.5882... < 0.6 → UTILIZATION_REJECT.
    sized, allowed_risk, risk_per_unit = _size(
        equity="100.00",
        risk_rate="0.017",
        stop_loss="49900.00",
        entry_ref="50000.00",
        costs="900.0",
    )
    constraints = _mk_constraints(step="0.001", min_qty="0.001")
    result = quantize(
        sized=sized,
        constraint_snapshot=constraints,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        reference_price=Decimal("50000.00"),
    )
    assert result.is_no_trade is True
    assert result.quantization_decision == "REJECTED"
    assert result.reason_code == "UTILIZATION_REJECT"
    # Realized risk is rounded * risk_per_unit = 0.001 * 1000 = 1.0.
    assert result.realized_risk == Decimal("1.0")


# --------------------------------------------------------------------------- #
# Test 6 — exact 0.6 utilization equality is ACCEPTED (boundary).
# --------------------------------------------------------------------------- #


def test_quantize_exact_0_6_utilization_accepted() -> None:
    """Beh. 1f: realized_risk / allowed_risk == 0.6 exactly → ACCEPTED.

    Per D-02: 0.6 is the baseline; equality is the inclusive boundary
    (>=, not >). Construct inputs so utilization hits exactly 0.6:
    - risk_per_unit = 600, raw = 1/600 ≈ 0.001667 (under prec-28).
    - step = 0.001, rounded = floor(1.667) * 0.001 = 0.001.
    - realized_risk = 0.001 * 600 = 0.6.
    - allowed_risk = 1, utilization = 0.6 / 1 = 0.6 exactly → ACCEPTED.
    """
    # Build directly with raw = 1/600 so the math is exact under prec-28.
    plan = _mk_trade_plan(
        stop_loss="0",  # sl_distance = 600 (entry_ref=600, stop_loss=0)
        risk_rate="1.0",
        risk_budget="1.0",
        suggested_quantity=str(Decimal("1") / Decimal("600")),
    )
    from src.risk.sizing import size_position

    sized = size_position(
        trade_plan=plan,
        account_state=_mk_account_state(equity="1.0", risk_rate="1.0"),
        entry_ref=Decimal("600"),
        modeled_costs_per_unit=Decimal("0"),
    )
    allowed_risk = Decimal("1")
    risk_per_unit = Decimal("600")
    constraints = _mk_constraints(step="0.001", min_qty="0.001")
    result = quantize(
        sized=sized,
        constraint_snapshot=constraints,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        reference_price=Decimal("100000.00"),
    )
    assert result.quantization_decision == "ACCEPTED"
    assert result.reason_code == "OK"
    assert result.realized_risk == Decimal("0.6")


# --------------------------------------------------------------------------- #
# Test 7 — quantity_step_size == 0 fails closed at type construction (D-04).
# --------------------------------------------------------------------------- #


def test_constraint_snapshot_zero_step_size_rejected() -> None:
    """Beh. 1g: zero quantity_step_size rejected at ConstraintSnapshot construction.

    Per D-04: invalid exchange metadata fails closed. The type guard
    rejects zero/negative step_size before quantize ever runs — the
    adapter edge must never produce zero step_size, and the loader
    raises if it tries.
    """
    with pytest.raises(ValueError, match="quantity_step_size must be > 0"):
        _mk_constraints(step="0")


# --------------------------------------------------------------------------- #
# Test 8 — reference price zero/negative fails closed.
# --------------------------------------------------------------------------- #


def test_quantize_zero_reference_price_fails_closed() -> None:
    """Beh. 1h: zero reference_price → EXCHANGE_CONSTRAINT fail closed."""
    sized, allowed_risk, risk_per_unit = _size()
    constraints = _mk_constraints()
    result = quantize(
        sized=sized,
        constraint_snapshot=constraints,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        reference_price=Decimal("0"),
    )
    assert result.is_no_trade is True
    assert result.reason_code == "EXCHANGE_CONSTRAINT"
