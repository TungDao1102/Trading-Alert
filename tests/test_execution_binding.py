"""Plan binding tests (Phase 19, plan 19-02; D-01..D-04, research F2/F3).

What the human approved is exactly what is placed: the plan hash is re-derived
with the planner's frozen algorithm, symbol and side come from the persisted
Signal reached by plan.signal_id, and every disagreement is a named refusal.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.core.planner import plan, plan_hash_from_fields
from src.core.strategy import evaluate
from src.core.types import AccountState, MarketSnapshot
from src.domain.registry import ParameterSet, load_parameter_set
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.binding import (
    APPROVED_QUANTITY_MISSING,
    GEOMETRY_INVALID_AFTER_SNAP,
    PLAN_QUANTITY_MISMATCH,
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
    check_snapped_geometry,
    check_working_type,
    recompute_plan_hash,
    take_profit_levels,
)
from src.execution.placement import (
    derive_limit_price,
    derive_sl_trigger_price,
    entry_limit_rounding,
    quantize_price,
    sl_trigger_rounding,
)

from tests import geometry_builders
from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)

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


def _bind(signal: Signal, trade_plan: TradePlan, **overrides: object) -> BindingVerdict:
    """bind_plan with every argument consistent, then the named overrides applied."""
    kwargs: dict[str, object] = {
        "callback_plan_hash": trade_plan.plan_hash,
        "approval_request_hash": trade_plan.plan_hash,
        "approval_strategy_version": signal.strategy_version,
        "approval_parameter_set_id": signal.parameter_set_id,
        "approval_parameter_set_hash": signal.parameter_set_hash,
        "plan_snapshot_symbol": signal.symbol,
        "plan_snapshot_trade_plan_id": trade_plan.trade_plan_id,
        "caller_symbol": signal.symbol,
        "caller_side": signal.direction,
        # D078 (19-REVIEW WR-01): the quantity stored on the approval row.
        "approval_quantity": trade_plan.quantity_after_rounding,
    }
    kwargs.update(overrides)
    return bind_plan(trade_plan=trade_plan, signal=signal, **kwargs)  # type: ignore[arg-type]


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
        approval_quantity=trade_plan.quantity_after_rounding,
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


# --------------------------------------------------------------------------- #
# Review-fix batch 4 (19-REVIEW WR-01, D078) - the approved quantity bound.
# --------------------------------------------------------------------------- #


def test_wr01_an_equal_quantity_binds_and_the_bound_carries_the_approval_value() -> None:
    signal, trade_plan = _real_plan("LONG")
    stored = trade_plan.quantity_after_rounding.quantize(Decimal("1.000000000000000000"))
    assert stored == trade_plan.quantity_after_rounding

    verdict = _bind(signal, trade_plan, approval_quantity=stored)

    assert verdict.ok is True
    assert verdict.bound is not None
    # The bound holds the approval's value (same object, same scale), not the plan's own field.
    assert verdict.bound.approved_quantity is stored
    assert str(verdict.bound.approved_quantity) == str(stored)


@pytest.mark.parametrize(
    "delta", [Decimal("0.000000000000000001"), Decimal("-0.000000000000000001")]
)
def test_wr01_a_plan_quantity_that_differs_from_the_approval_is_refused(delta: Decimal) -> None:
    signal, trade_plan = _real_plan("LONG")
    stored = trade_plan.quantity_after_rounding + delta
    _refused(_bind(signal, trade_plan, approval_quantity=stored), PLAN_QUANTITY_MISMATCH)


def test_wr01_an_inflated_plan_object_is_refused_although_its_hash_still_verifies() -> None:
    signal, trade_plan = _real_plan("LONG")
    inflated = dataclasses.replace(
        trade_plan, quantity_after_rounding=trade_plan.quantity_after_rounding * 2
    )
    # D051 (c): the quantity is not a hashed field, so the plan hash is unchanged.
    assert recompute_plan_hash(inflated) == trade_plan.plan_hash == inflated.plan_hash
    _refused(
        _bind(signal, inflated, approval_quantity=trade_plan.quantity_after_rounding),
        PLAN_QUANTITY_MISMATCH,
    )


def test_wr01_a_missing_approval_quantity_is_refused_as_missing() -> None:
    signal, trade_plan = _real_plan("LONG")
    _refused(_bind(signal, trade_plan, approval_quantity=None), APPROVED_QUANTITY_MISSING)


def test_wr01_numeric_equality_ignores_the_scale() -> None:
    signal, trade_plan = _real_plan("LONG")
    scaled = dataclasses.replace(trade_plan, quantity_after_rounding=Decimal("0.0800"))
    verdict = _bind(signal, scaled, approval_quantity=Decimal("0.08"))
    assert verdict.ok is True
    assert verdict.bound is not None
    assert verdict.bound.approved_quantity == Decimal("0.08")


def test_wr01_a_hash_mismatch_beats_a_quantity_mismatch() -> None:
    signal, trade_plan = _real_plan("LONG")
    mutated = dataclasses.replace(trade_plan, stop_loss_price=Decimal("1"))
    _refused(
        _bind(signal, mutated, approval_quantity=trade_plan.quantity_after_rounding * 2),
        STALE_SETUP,
    )


def test_wr01_a_side_mismatch_beats_a_quantity_mismatch() -> None:
    signal, trade_plan = _real_plan("LONG")
    _refused(
        _bind(signal, trade_plan, caller_side="SHORT", approval_quantity=Decimal("1")),
        PLAN_SIDE_MISMATCH,
    )


@pytest.mark.parametrize("bad", [0.5, 1, "0.5", True])
def test_wr01_a_non_decimal_approval_quantity_is_a_programming_error(bad: object) -> None:
    signal, trade_plan = _real_plan("LONG")
    with pytest.raises(TypeError):
        _bind(signal, trade_plan, approval_quantity=bad)


def test_wr01_the_plan_hash_field_set_ignores_the_quantity() -> None:
    _, trade_plan = _real_plan("LONG")
    other = dataclasses.replace(
        trade_plan, quantity_after_rounding=trade_plan.quantity_after_rounding + Decimal("1")
    )
    assert recompute_plan_hash(other) == recompute_plan_hash(trade_plan)


def test_wr01_approval_quantity_is_a_required_keyword() -> None:
    signal, trade_plan = _real_plan("LONG")
    with pytest.raises(TypeError):
        bind_plan(  # type: ignore[call-arg]
            trade_plan=trade_plan,
            signal=signal,
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


# --------------------------------------------------------------------------- #
# Task 3 - snapped geometry (G4-020), take-profit levels and purity.
# --------------------------------------------------------------------------- #

_TICKS = [Decimal("0.01"), Decimal("0.1"), Decimal("0.5")]


def _snap(
    side: str,
    *,
    entry_min: Decimal,
    entry_max: Decimal,
    stop: Decimal,
    tick: Decimal,
) -> tuple[Decimal, Decimal]:
    """The limit and SL trigger exactly as the manager snaps them today."""
    limit = quantize_price(
        price=derive_limit_price(entry_min_price=entry_min, entry_max_price=entry_max),
        price_tick_size=tick,
        direction=entry_limit_rounding(candidate_position_side=side),
    )
    sl_trigger = quantize_price(
        price=derive_sl_trigger_price(stop_loss_price=stop),
        price_tick_size=tick,
        direction=sl_trigger_rounding(candidate_position_side=side),
    )
    return limit, sl_trigger


def _expected_refusal(
    side: str,
    *,
    limit: Decimal,
    sl_trigger: Decimal,
    entry_min: Decimal,
    entry_max: Decimal,
) -> bool:
    """Independent statement of D-03: the stop is strictly outside the zone and the limit."""
    if side == "LONG":
        return (
            not (entry_min <= limit <= entry_max) or sl_trigger >= entry_min or sl_trigger >= limit
        )
    return not (entry_min <= limit <= entry_max) or sl_trigger <= entry_max or sl_trigger <= limit


def test_snapped_geometry_grid_refuses_exactly_the_stop_that_reaches_the_zone() -> None:
    refused_cases = 0
    accepted_cases = 0
    for side in ("LONG", "SHORT"):
        for tick in _TICKS:
            for entry_min, entry_max in (
                (Decimal("100.03"), Decimal("100.37")),
                (Decimal("100.20"), Decimal("101.20")),
                (Decimal("100.03"), Decimal("100.04")),  # a zone narrower than most ticks
            ):
                for offset in (Decimal("0"), tick / 4, tick / 2, tick, 2 * tick, 5 * tick):
                    stop = entry_min - offset if side == "LONG" else entry_max + offset
                    limit, sl_trigger = _snap(
                        side, entry_min=entry_min, entry_max=entry_max, stop=stop, tick=tick
                    )
                    refused = check_snapped_geometry(
                        side=side,
                        limit_price=limit,
                        sl_trigger_price=sl_trigger,
                        entry_min_price=entry_min,
                        entry_max_price=entry_max,
                    )
                    expected = _expected_refusal(
                        side,
                        limit=limit,
                        sl_trigger=sl_trigger,
                        entry_min=entry_min,
                        entry_max=entry_max,
                    )
                    assert refused == (GEOMETRY_INVALID_AFTER_SNAP if expected else None), (
                        side,
                        tick,
                        entry_min,
                        entry_max,
                        stop,
                        limit,
                        sl_trigger,
                    )
                    refused_cases += expected
                    accepted_cases += not expected
    assert refused_cases > 0
    assert accepted_cases > 0


def test_snapped_geometry_stop_one_tick_below_the_zone_edge_snaps_onto_it() -> None:
    """LONG, tick 0.5, zone 100.20-101.20, stop 100.10: the stop snaps UP to 100.50 (inside)."""
    entry_min, entry_max, tick = Decimal("100.20"), Decimal("101.20"), Decimal("0.5")
    limit, sl_trigger = _snap(
        "LONG", entry_min=entry_min, entry_max=entry_max, stop=Decimal("100.10"), tick=tick
    )
    assert sl_trigger == Decimal("100.5")
    assert (
        check_snapped_geometry(
            side="LONG",
            limit_price=limit,
            sl_trigger_price=sl_trigger,
            entry_min_price=entry_min,
            entry_max_price=entry_max,
        )
        == GEOMETRY_INVALID_AFTER_SNAP
    )


def test_snapped_geometry_accepts_a_stop_clear_of_the_zone() -> None:
    for side, stop in (("LONG", Decimal("97.40")), ("SHORT", Decimal("102.60"))):
        entry_min, entry_max, tick = Decimal("97.80"), Decimal("100.20"), Decimal("0.01")
        limit, sl_trigger = _snap(
            side, entry_min=entry_min, entry_max=entry_max, stop=stop, tick=tick
        )
        assert (
            check_snapped_geometry(
                side=side,
                limit_price=limit,
                sl_trigger_price=sl_trigger,
                entry_min_price=entry_min,
                entry_max_price=entry_max,
            )
            is None
        )


def test_snapped_geometry_limit_outside_the_zone_is_refused() -> None:
    assert (
        check_snapped_geometry(
            side="LONG",
            limit_price=Decimal("101"),
            sl_trigger_price=Decimal("90"),
            entry_min_price=Decimal("98"),
            entry_max_price=Decimal("100"),
        )
        == GEOMETRY_INVALID_AFTER_SNAP
    )


def test_snapped_geometry_unknown_side_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        check_snapped_geometry(
            side="BOTH",
            limit_price=Decimal("99"),
            sl_trigger_price=Decimal("90"),
            entry_min_price=Decimal("98"),
            entry_max_price=Decimal("100"),
        )


def test_take_profit_levels_parse_tp1_and_tp2() -> None:
    _signal, trade_plan = _real_plan("LONG")
    tp1, tp2 = take_profit_levels(trade_plan)
    prices = json.loads(trade_plan.take_profit_json)
    assert (tp1, tp2) == (Decimal(prices["tp1"]), Decimal(prices["tp2"]))
    assert isinstance(tp1, Decimal) and isinstance(tp2, Decimal)


@pytest.mark.parametrize(
    "take_profit_json",
    [
        "{}",
        '{"tp1": "106.0"}',
        '{"tp2": "112.0"}',
        '{"tp1": 106.0, "tp2": "112.0"}',
        '{"tp1": "106.0", "tp2": 112}',
        '{"tp1": "NaN", "tp2": "112.0"}',
        '{"tp1": "106.0", "tp2": "Infinity"}',
        '{"tp1": "abc", "tp2": "112.0"}',
        '{"tp1": "0", "tp2": "112.0"}',
        '{"tp1": "-1", "tp2": "112.0"}',
        "[]",
        '"text"',
        "not json",
    ],
)
def test_take_profit_levels_fail_closed(take_profit_json: str) -> None:
    _signal, trade_plan = _real_plan("LONG")
    broken = dataclasses.replace(trade_plan, take_profit_json=take_profit_json)
    with pytest.raises(ValueError):
        take_profit_levels(broken)


_BINDING_PATH = Path(__file__).resolve().parents[1] / "src" / "execution" / "binding.py"
_ALLOWED_PREFIXES = (
    "__future__",
    "dataclasses",
    "decimal",
    "json",
    "src.core.planner",
    "src.domain",
    "src.execution.placement",
)


def test_binding_module_is_pure() -> None:
    forbidden = forbidden_imports(
        _BINDING_PATH,
        [
            "binance*",
            "sqlalchemy",
            "pydantic",
            "polars",
            "src.adapters",
            "src.persistence",
            "src.backtest",
        ],
    )
    assert forbidden == []
    unexpected = [
        name
        for name in module_imports(_BINDING_PATH)
        if not any(name == p or name.startswith(p + ".") for p in _ALLOWED_PREFIXES)
    ]
    assert unexpected == []
    assert float_constructor_calls(_BINDING_PATH) == []
    assert wall_clock_calls(_BINDING_PATH) == []


def test_purity_guard_reports_a_planted_float_call(tmp_path: Path) -> None:
    """Negative control: the helper does see a float() call and a clock read."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import time\n\n\ndef f(x):\n    time.time()\n    return float(x)\n", encoding="utf-8"
    )
    assert float_constructor_calls(planted) == [6]
    assert [name for _line, name in wall_clock_calls(planted)] == ["time.time"]
