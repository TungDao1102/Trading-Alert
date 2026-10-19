"""Plan binding tests (Phase 19, plan 19-02; D-01..D-04, research F2/F3).

What the human approved is exactly what is placed: the plan hash is re-derived
with the planner's frozen algorithm, symbol and side come from the persisted
Signal reached by plan.signal_id, and every disagreement is a named refusal.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from decimal import Decimal

import pytest
from src.core.planner import plan, plan_hash_from_fields
from src.core.strategy import evaluate
from src.core.types import AccountState, MarketSnapshot
from src.domain.registry import ParameterSet, load_parameter_set
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.binding import (
    PLAN_SIDE_MISMATCH,
    PLAN_SIGNAL_MISMATCH,
    PLAN_SYMBOL_MISMATCH,
    QUANTITY_ABOVE_APPROVED,
    STALE_SETUP,
    WORKING_TYPE_NOT_MARK_PRICE,
    BindingVerdict,
    BoundPlan,
    bind_plan,
    check_quantity_bound,
    check_working_type,
    recompute_plan_hash,
)

from tests import geometry_builders

_PARAMETER_SET_ID = "baseline-v6"


def _parameter_set() -> ParameterSet:
    return load_parameter_set("trend-pullback", _PARAMETER_SET_ID)


def _real_plan(side: str) -> tuple[Signal, TradePlan]:
    """A real evaluate() Signal and plan() TradePlan on the hand-derived Family A window."""
    window = (
        geometry_builders.family_a_long_window()
        if side == "LONG"
        else geometry_builders.family_a_short_window()
    )
    parameter_set = _parameter_set()
    account_state = AccountState(equity=Decimal("10000.00"), risk_rate=Decimal("0.005"))
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=window[0],
        context_candles=window[1],
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade, result.reason_code
    assert result.signal is not None
    planned = plan(
        signal=result.signal,
        setup_candles=window[0],
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert planned.trade_plan is not None, planned.reason_code
    assert result.signal.direction == side
    return result.signal, planned.trade_plan


def _bind(signal: Signal, trade_plan: TradePlan, **overrides: str) -> BindingVerdict:
    """bind_plan with every argument consistent, then the named overrides applied."""
    kwargs: dict[str, str] = {
        "callback_plan_hash": trade_plan.plan_hash,
        "approval_request_hash": trade_plan.plan_hash,
        "approval_strategy_version": signal.strategy_version,
        "approval_parameter_set_id": signal.parameter_set_id,
        "approval_parameter_set_hash": signal.parameter_set_hash,
        "plan_snapshot_symbol": signal.symbol,
        "plan_snapshot_trade_plan_id": trade_plan.trade_plan_id,
        "caller_symbol": signal.symbol,
        "caller_side": signal.direction,
    }
    kwargs.update(overrides)
    return bind_plan(trade_plan=trade_plan, signal=signal, **kwargs)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_tracer_real_plan_binds_to_its_signal(side: str) -> None:
    signal, trade_plan = _real_plan(side)
    assert recompute_plan_hash(trade_plan) == trade_plan.plan_hash

    verdict = _bind(signal, trade_plan)

    assert verdict.ok is True
    assert verdict.reason_code == "OK"
    assert verdict.bound == BoundPlan(
        trade_plan_id=trade_plan.trade_plan_id,
        plan_hash=trade_plan.plan_hash,
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        side=side,
        entry_side="BUY" if side == "LONG" else "SELL",
        exit_side="SELL" if side == "LONG" else "BUY",
        approved_quantity=trade_plan.quantity_after_rounding,
    )


# --------------------------------------------------------------------------- #
# Task 2 - mismatch grid.
# --------------------------------------------------------------------------- #


def _refused(verdict: BindingVerdict, reason: str) -> None:
    assert verdict.ok is False
    assert verdict.reason_code == reason
    assert verdict.bound is None


def _rehashed(trade_plan: TradePlan, **changes: object) -> TradePlan:
    """A TradePlan with changed fields and a plan_hash that matches them (a consistent row)."""
    changed = dataclasses.replace(trade_plan, **changes)
    return dataclasses.replace(changed, plan_hash=recompute_plan_hash(changed))


def test_stale_setup_constant_is_the_rejection_reason() -> None:
    assert STALE_SETUP == "STALE_SETUP"


@pytest.mark.parametrize(
    "field",
    [
        "entry_min_price",
        "entry_max_price",
        "stop_loss_price",
        "take_profit_json",
        "invalidation_rule_json",
        "expiry_utc",
        "signal_id",
    ],
)
def test_mutated_hashed_field_without_new_hash_is_stale_setup(field: str) -> None:
    signal, trade_plan = _real_plan("LONG")
    mutations: dict[str, object] = {
        "entry_min_price": Decimal("1"),
        "entry_max_price": Decimal("1000000"),
        "stop_loss_price": Decimal("1"),
        "take_profit_json": '{"tp1":"1","tp2":"2"}',
        "invalidation_rule_json": '{"basis":"OTHER"}',
        "expiry_utc": trade_plan.expiry_utc + timedelta(hours=1),
        "signal_id": "other-signal",
    }
    mutated = dataclasses.replace(trade_plan, **{field: mutations[field]})

    _refused(_bind(signal, mutated), STALE_SETUP)


def test_callback_or_approval_hash_that_differs_is_stale_setup() -> None:
    signal, trade_plan = _real_plan("LONG")
    _refused(_bind(signal, trade_plan, callback_plan_hash="0" * 64), STALE_SETUP)
    _refused(_bind(signal, trade_plan, approval_request_hash="0" * 64), STALE_SETUP)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("signal_id", "another-signal"),
        ("strategy_version", "other-version"),
        ("parameter_set_id", "other-set"),
        ("parameter_set_hash", "f" * 64),
    ],
)
def test_signal_or_approval_identity_mismatch(field: str, value: str) -> None:
    signal, trade_plan = _real_plan("LONG")
    other = dataclasses.replace(signal, **{field: value})
    # The approval was issued under the original identity; the loaded Signal differs.
    verdict = bind_plan(
        trade_plan=trade_plan,
        signal=other,
        callback_plan_hash=trade_plan.plan_hash,
        approval_request_hash=trade_plan.plan_hash,
        approval_strategy_version=signal.strategy_version,
        approval_parameter_set_id=signal.parameter_set_id,
        approval_parameter_set_hash=signal.parameter_set_hash,
        plan_snapshot_symbol=signal.symbol,
        plan_snapshot_trade_plan_id=trade_plan.trade_plan_id,
        caller_symbol=signal.symbol,
        caller_side=signal.direction,
    )
    _refused(verdict, PLAN_SIGNAL_MISMATCH)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("plan_snapshot_trade_plan_id", "another-plan"),
        ("plan_snapshot_symbol", "ETHUSDT"),
        ("caller_symbol", "ETHUSDT"),
    ],
)
def test_symbol_mismatch(key: str, value: str) -> None:
    signal, trade_plan = _real_plan("LONG")
    _refused(_bind(signal, trade_plan, **{key: value}), PLAN_SYMBOL_MISMATCH)


def test_caller_side_disagreeing_with_the_plan_is_a_refusal() -> None:
    signal, trade_plan = _real_plan("LONG")
    _refused(_bind(signal, trade_plan, caller_side="SHORT"), PLAN_SIDE_MISMATCH)
    short_signal, short_plan = _real_plan("SHORT")
    _refused(_bind(short_signal, short_plan, caller_side="LONG"), PLAN_SIDE_MISMATCH)


def test_signal_direction_that_is_not_a_position_side_is_a_refusal() -> None:
    signal, trade_plan = _real_plan("LONG")
    odd = dataclasses.replace(signal, direction="BOTH")
    _refused(_bind(odd, trade_plan, caller_side="BOTH"), PLAN_SIDE_MISMATCH)


def test_signal_direction_contradicting_the_geometry_is_a_refusal() -> None:
    signal, trade_plan = _real_plan("SHORT")  # stop above the zone
    liar = dataclasses.replace(signal, direction="LONG")
    _refused(_bind(liar, trade_plan, caller_side="LONG"), PLAN_SIDE_MISMATCH)


def test_stop_inside_the_zone_has_no_geometry_side() -> None:
    signal, trade_plan = _real_plan("LONG")
    inside = _rehashed(trade_plan, stop_loss_price=trade_plan.entry_min_price)
    verdict = _bind(
        signal,
        inside,
        callback_plan_hash=inside.plan_hash,
        approval_request_hash=inside.plan_hash,
    )
    _refused(verdict, PLAN_SIDE_MISMATCH)


def test_first_failure_order_hash_beats_caller_side() -> None:
    signal, trade_plan = _real_plan("LONG")
    mutated = dataclasses.replace(trade_plan, stop_loss_price=Decimal("1"))
    _refused(_bind(signal, mutated, caller_side="SHORT"), STALE_SETUP)


def test_first_failure_order_signal_beats_symbol_and_side() -> None:
    signal, trade_plan = _real_plan("LONG")
    verdict = _bind(
        signal,
        trade_plan,
        approval_strategy_version="other-version",
        caller_symbol="ETHUSDT",
        caller_side="SHORT",
    )
    _refused(verdict, PLAN_SIGNAL_MISMATCH)


def test_first_failure_order_symbol_beats_side() -> None:
    signal, trade_plan = _real_plan("LONG")
    verdict = _bind(signal, trade_plan, caller_symbol="ETHUSDT", caller_side="SHORT")
    _refused(verdict, PLAN_SYMBOL_MISMATCH)


def test_binding_verdict_validates_its_shape() -> None:
    with pytest.raises(ValueError):
        BindingVerdict(ok=True, reason_code="OK", bound=None)
    with pytest.raises(ValueError):
        BindingVerdict(ok=False, reason_code="OK", bound=None)
    signal, trade_plan = _real_plan("LONG")
    bound = _bind(signal, trade_plan).bound
    assert bound is not None
    with pytest.raises(ValueError):
        BindingVerdict(ok=False, reason_code=STALE_SETUP, bound=bound)


def test_rehashed_row_binds_when_all_hashes_agree() -> None:
    """Control for the grid: a consistent changed row (new hash everywhere) still binds."""
    signal, trade_plan = _real_plan("LONG")
    changed = _rehashed(trade_plan, expiry_utc=trade_plan.expiry_utc + timedelta(hours=1))
    verdict = _bind(
        signal,
        changed,
        callback_plan_hash=changed.plan_hash,
        approval_request_hash=changed.plan_hash,
    )
    assert verdict.ok is True
    assert changed.plan_hash != trade_plan.plan_hash
    assert (
        plan_hash_from_fields(
            signal_id=changed.signal_id,
            entry_min_price=changed.entry_min_price,
            entry_max_price=changed.entry_max_price,
            stop_loss_price=changed.stop_loss_price,
            take_profit_json=changed.take_profit_json,
            invalidation_rule_json=changed.invalidation_rule_json,
            expiry_utc=changed.expiry_utc,
        )
        == changed.plan_hash
    )


@pytest.mark.parametrize(
    ("placement", "approved", "refused"),
    [
        (Decimal("0.5"), Decimal("0.5"), False),
        (Decimal("0.4"), Decimal("0.5"), False),
        (Decimal("0.500000000000000001"), Decimal("0.5"), True),
        (Decimal("2"), Decimal("0.5"), True),
    ],
)
def test_check_quantity_bound(placement: Decimal, approved: Decimal, refused: bool) -> None:
    result = check_quantity_bound(placement_quantity=placement, approved_quantity=approved)
    assert result == (QUANTITY_ABOVE_APPROVED if refused else None)


@pytest.mark.parametrize(
    ("placement", "approved", "error"),
    [
        (0.5, Decimal("0.5"), TypeError),
        (Decimal("0.5"), 0.5, TypeError),
        (Decimal("0.5"), "0.5", TypeError),
        (Decimal("0"), Decimal("0.5"), ValueError),
        (Decimal("0.5"), Decimal("0"), ValueError),
        (Decimal("-1"), Decimal("0.5"), ValueError),
        (Decimal("NaN"), Decimal("0.5"), ValueError),
        (Decimal("0.5"), Decimal("Infinity"), ValueError),
    ],
)
def test_check_quantity_bound_programming_errors_fail_loud(
    placement: object, approved: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        check_quantity_bound(
            placement_quantity=placement,  # type: ignore[arg-type]
            approved_quantity=approved,  # type: ignore[arg-type]
        )


def test_check_working_type() -> None:
    assert check_working_type("MARK_PRICE") is None
    for other in ("CONTRACT_PRICE", "mark_price", "", "UNKNOWN"):
        assert check_working_type(other) == WORKING_TYPE_NOT_MARK_PRICE
