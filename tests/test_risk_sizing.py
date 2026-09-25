"""Tests for the pure position-sizing function (Phase 5, plan 05-01).

Per D-01: `size_position` consumes a Phase-4 TradePlan DEFERRED_TO_RISK
estimate fields as inputs (never re-derived) plus equity, risk_rate, and
modeled_costs_per_unit, and returns raw quantity equal to
allowed_risk / risk_per_unit, all in Decimal under pinned prec-28.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/risk/sizing.py` is implemented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.core.types import AccountState
from src.domain.enums import TradePlanStatus
from src.domain.trade_plan import TradePlan
from src.risk.sizing import size_position
from src.risk.types import SizedResult

# --------------------------------------------------------------------------- #
# Helpers — build a frozen TradePlan with DEFERRED_TO_RISK estimate fields.
# --------------------------------------------------------------------------- #


def _mk_trade_plan(
    *,
    side: str = "LONG",
    entry_min: str = "49900.00",
    entry_max: str = "50100.00",
    stop_loss: str = "49000.00",
    risk_rate: str = "0.005",
    risk_budget: str = "50.00000",
    suggested_quantity: str = "0.04995004995004995004995004995",
) -> TradePlan:
    """Build a frozen TradePlan with DEFERRED_TO_RISK estimate fields.

    The plan_hash / trade_plan_id / signal_id are 64-hex placeholders so
    the TradePlan post_init guards pass; sizing never reads them.
    """
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
    """Build a frozen AccountState for tests."""
    return AccountState(equity=Decimal(equity), risk_rate=Decimal(risk_rate))


# --------------------------------------------------------------------------- #
# Test 1 — happy-path LONG sizing matches allowed_risk / risk_per_unit.
# --------------------------------------------------------------------------- #


def test_size_position_happy_path_long_byte_exact() -> None:
    """Beh. 1: size_position returns raw quantity = allowed_risk / risk_per_unit.

    Per D-01: allowed_risk = equity × risk_rate = 10000 × 0.005 = 50.00.
    sl_distance = |50000 - 49000| = 1000. risk_per_unit = 1000 + 1 = 1001.
    raw_quantity = 50 / 1001 = 0.04995004995004995004995004995... (Decimal prec-28).
    """
    plan = _mk_trade_plan()
    account = _mk_account_state()
    result = size_position(
        trade_plan=plan,
        account_state=account,
        entry_ref=Decimal("50000.00"),
        modeled_costs_per_unit=Decimal("1.0"),
    )
    assert isinstance(result, SizedResult)
    # raw_quantity = 50 / 1001, computed under pinned prec-28.
    expected_raw = Decimal("50") / Decimal("1001")
    assert result.quantity_before_rounding == expected_raw
    # Passthrough — quantization owns the floor.
    assert result.quantity_after_rounding == expected_raw
    assert result.quantization_decision == "DEFERRED_TO_RISK"
    assert result.reason_code == "OK"
    assert result.is_no_trade is False


# --------------------------------------------------------------------------- #
# Test 2 — zero SL distance returns is_no_trade=True with EXCHANGE_CONSTRAINT.
# --------------------------------------------------------------------------- #


def test_size_position_zero_sl_distance_fails_closed() -> None:
    """Beh. 2: zero SL distance → is_no_trade=True, EXCHANGE_CONSTRAINT, no division.

    Per D-01 + Pitfall 1: degenerate zone (entry_ref == stop_loss) must
    fail closed before dividing by zero.
    """
    plan = _mk_trade_plan(stop_loss="50000.00")
    account = _mk_account_state()
    result = size_position(
        trade_plan=plan,
        account_state=account,
        entry_ref=Decimal("50000.00"),
        modeled_costs_per_unit=Decimal("1.0"),
    )
    assert isinstance(result, SizedResult)
    assert result.is_no_trade is True
    assert result.reason_code == "EXCHANGE_CONSTRAINT"
    assert result.quantity is None


# --------------------------------------------------------------------------- #
# Test 3 — SHORT is symmetric to LONG.
# --------------------------------------------------------------------------- #


def test_size_position_short_symmetric() -> None:
    """Beh. 3: SHORT sizing uses |entry_ref - stop_loss| (symmetric to LONG)."""
    plan = _mk_trade_plan(stop_loss="51000.00")
    account = _mk_account_state()
    result = size_position(
        trade_plan=plan,
        account_state=account,
        entry_ref=Decimal("50000.00"),
        modeled_costs_per_unit=Decimal("1.0"),
    )
    assert isinstance(result, SizedResult)
    # sl_distance = |50000 - 51000| = 1000 (same as LONG).
    expected_raw = Decimal("50") / Decimal("1001")
    assert result.quantity_before_rounding == expected_raw
    assert result.is_no_trade is False


# --------------------------------------------------------------------------- #
# Test 4 — Decimal arithmetic byte-identical across two runs (parity subset).
# --------------------------------------------------------------------------- #


def test_size_position_byte_identical_across_runs() -> None:
    """Beh. 4: identical inputs run twice produce byte-identical SizedResult.

    Per D-01: pinned prec-28 + Decimal-only math → byte-identical outputs.
    """
    plan = _mk_trade_plan()
    account = _mk_account_state()
    a = size_position(
        trade_plan=plan,
        account_state=account,
        entry_ref=Decimal("50000.00"),
        modeled_costs_per_unit=Decimal("1.0"),
    )
    b = size_position(
        trade_plan=plan,
        account_state=account,
        entry_ref=Decimal("50000.00"),
        modeled_costs_per_unit=Decimal("1.0"),
    )
    assert a.quantity_before_rounding == b.quantity_before_rounding
    assert a.quantity_after_rounding == b.quantity_after_rounding
    assert a.realized_risk == b.realized_risk
    assert a.reason_code == b.reason_code
    assert a.quantization_decision == b.quantization_decision
