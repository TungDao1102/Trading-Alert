"""Live take-profit sizing from a reconciled position (Phase 19, plan 19-07, D-18, D-19).

Every filter is a fake: sizing is proven offline, the mainnet filters are not verified
(research A7, B8).
"""

from __future__ import annotations

import ast
import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.semantics import TP1_QUANTITY_FRACTION
from src.domain.lot_filters import LotFilters
from src.execution.placement import ProtectiveTemplate, size_protectives_to_filled_qty
from src.execution.tp_sizing import TakeProfitSizing, size_take_profits
from src.risk.types import ConstraintSnapshot

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)

TP_SIZING_PATH = Path(__file__).resolve().parents[1] / "src" / "execution" / "tp_sizing.py"

D = Decimal


def make_filters(
    *,
    tick: str = "0.01",
    lot_min: str = "0.001",
    lot_max: str = "1000",
    lot_step: str = "0.001",
    mkt_min: str | None = None,
    mkt_max: str | None = None,
    mkt_step: str | None = None,
    min_notional: str = "0.1",
) -> LotFilters:
    return LotFilters(
        symbol="BTCUSDT",
        price_tick_size=D(tick),
        lot_min_quantity=D(lot_min),
        lot_max_quantity=D(lot_max),
        lot_step_size=D(lot_step),
        market_lot_min_quantity=D(mkt_min if mkt_min is not None else lot_min),
        market_lot_max_quantity=D(mkt_max if mkt_max is not None else lot_max),
        market_lot_step_size=D(mkt_step if mkt_step is not None else lot_step),
        min_notional=D(min_notional),
    )


def _size(
    *,
    position: str = "0.010",
    tp1: str = "106.004",
    tp2: str = "110.006",
    fraction: str = "0.5",
    filters: LotFilters | None = None,
    side: str = "LONG",
    mode: str = "ONE_WAY",
    working_type: str = "MARK_PRICE",
) -> TakeProfitSizing:
    return size_take_profits(
        position_quantity=D(position),
        tp1_trigger_price=D(tp1),
        tp2_trigger_price=D(tp2),
        tp1_quantity_fraction=D(fraction),
        filters=filters if filters is not None else make_filters(),
        side=side,
        position_mode=mode,
        working_type=working_type,
    )


def test_tracer_one_way_long_tp1_and_tp2_legs() -> None:
    result = size_take_profits(
        position_quantity=D("0.010"),
        tp1_trigger_price=D("106.004"),
        tp2_trigger_price=D("110.006"),
        tp1_quantity_fraction=D("0.5"),
        filters=make_filters(),
        side="LONG",
        position_mode="ONE_WAY",
        working_type="MARK_PRICE",
    )
    assert isinstance(result, TakeProfitSizing)
    assert result.is_no_trade is False
    assert result.reason_code == "OK"
    assert result.tp1_quantity == D("0.005")
    assert result.tp1_leg == {
        "side": "SELL",
        "position_side": "BOTH",
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": D("106.00"),
        "close_position": False,
        "quantity": D("0.005"),
        "reduce_only": True,
        "working_type": "MARK_PRICE",
    }
    assert result.tp2_leg == {
        "side": "SELL",
        "position_side": "BOTH",
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": D("110.00"),
        "close_position": True,
        "quantity": None,
        "reduce_only": None,
        "working_type": "MARK_PRICE",
    }


# --------------------------------------------------------------------------- #
# Quantization grid and closable cap
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("position", "fraction", "expected"),
    [
        ("0.010", "0.5", "0.005"),
        ("0.011", "0.5", "0.005"),  # 0.0055 floors, never rounds up
        ("0.0199", "0.5", "0.009"),
        ("0.003", "1", "0.003"),  # fraction 1 is the whole position, never more
        ("1.234", "0.3333", "0.411"),
    ],
)
def test_tp1_floors_onto_the_lot_grid(position: str, fraction: str, expected: str) -> None:
    result = _size(position=position, fraction=fraction)
    assert result.is_no_trade is False
    assert result.tp1_quantity == D(expected)
    assert result.tp1_quantity is not None and result.tp1_quantity <= D(position)


def test_coarser_market_lot_step_wins() -> None:
    filters = make_filters(lot_step="0.001", mkt_step="0.01", mkt_min="0.01", lot_min="0.001")
    result = _size(position="0.139", fraction="0.5", filters=filters)  # raw 0.0695
    assert result.is_no_trade is False
    assert result.tp1_quantity == D("0.06")


@pytest.mark.parametrize("fraction", ["0", "-0.1", "1.0001", "2"])
def test_fraction_outside_zero_one_raises(fraction: str) -> None:
    with pytest.raises(ValueError, match="tp1_quantity_fraction"):
        _size(fraction=fraction)


# --------------------------------------------------------------------------- #
# Refusals (O-03: no single-TP fallback, D-19: no reduce-only notional exemption)
# --------------------------------------------------------------------------- #


def _assert_refused(result: TakeProfitSizing, reason: str) -> None:
    assert result.is_no_trade is True
    assert result.reason_code == reason
    assert result.tp1_leg is None
    assert result.tp2_leg is None
    assert result.tp1_quantity is None


def test_tp1_below_lot_minimum_is_min_qty_reject() -> None:
    _assert_refused(_size(position="0.001", fraction="0.5"), "MIN_QTY_REJECT")


def test_tp1_below_market_lot_minimum_is_min_qty_reject() -> None:
    filters = make_filters(mkt_min="0.01", mkt_step="0.01")
    _assert_refused(_size(position="0.015", fraction="0.5", filters=filters), "MIN_QTY_REJECT")


def test_tp1_below_min_notional_is_notional_reject() -> None:
    # 0.005 * 106.00 = 0.53 < 5: no reduce-only exemption is assumed.
    filters = make_filters(min_notional="5")
    _assert_refused(_size(position="0.010", filters=filters), "NOTIONAL_REJECT")


def test_notional_is_measured_at_the_snapped_tp1_trigger() -> None:
    # 0.05 * 100.00 = 5.00 is exactly the minimum (accepted); a trigger snapped down to
    # 99.99 gives 4.9995 and is refused.
    filters = make_filters(min_notional="5")
    assert _size(position="0.1", tp1="100.004", filters=filters).is_no_trade is False
    _assert_refused(_size(position="0.1", tp1="99.996", filters=filters), "NOTIONAL_REJECT")


def test_min_quantity_is_checked_before_notional() -> None:
    _assert_refused(_size(position="0.001", fraction="0.5", tp1="1000"), "MIN_QTY_REJECT")


def test_no_single_tp_fallback_exists() -> None:
    result = _size(position="0.001")
    assert result.is_no_trade is True
    assert result.tp2_leg is None  # no lone close-all TP2 is offered instead


# --------------------------------------------------------------------------- #
# One-way payloads
# --------------------------------------------------------------------------- #


def test_one_way_short_payloads() -> None:
    result = _size(side="SHORT", mode="ONE_WAY", tp1="93.996", tp2="90.004")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["side"] == "BUY"
    assert result.tp1_leg["position_side"] == "BOTH"
    assert result.tp1_leg["reduce_only"] is True
    assert result.tp1_leg["close_position"] is False
    assert result.tp1_leg["trigger_price"] == D("94.00")  # snapped up, toward the entry
    assert result.tp2_leg["side"] == "BUY"
    assert result.tp2_leg["position_side"] == "BOTH"
    assert result.tp2_leg["close_position"] is True
    assert result.tp2_leg["quantity"] is None
    assert result.tp2_leg["reduce_only"] is None
    assert result.tp2_leg["trigger_price"] == D("90.01")


def test_one_way_long_tp1_reduce_only_and_tp2_close_position() -> None:
    result = _size(side="LONG", mode="ONE_WAY")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["reduce_only"] is True
    assert result.tp1_leg["position_side"] == "BOTH"
    assert result.tp2_leg["close_position"] is True
    assert result.tp2_leg["reduce_only"] is None


def test_working_type_is_copied_into_both_legs() -> None:
    result = _size(working_type="CONTRACT_PRICE")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["working_type"] == "CONTRACT_PRICE"
    assert result.tp2_leg["working_type"] == "CONTRACT_PRICE"


# --------------------------------------------------------------------------- #
# Hedge payloads
# --------------------------------------------------------------------------- #


def test_hedge_long_payloads() -> None:
    result = _size(side="LONG", mode="HEDGE")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["side"] == "SELL"
    assert result.tp1_leg["position_side"] == "LONG"
    assert result.tp1_leg["reduce_only"] is None
    assert result.tp1_leg["close_position"] is False
    assert result.tp1_leg["quantity"] == D("0.005")
    assert result.tp2_leg["side"] == "SELL"
    assert result.tp2_leg["position_side"] == "LONG"
    assert result.tp2_leg["close_position"] is True
    assert result.tp2_leg["quantity"] is None
    assert result.tp2_leg["reduce_only"] is None


def test_hedge_short_payloads() -> None:
    result = _size(side="SHORT", mode="HEDGE", tp1="93.996", tp2="90.004")
    assert result.tp1_leg is not None and result.tp2_leg is not None
    assert result.tp1_leg["side"] == "BUY"
    assert result.tp1_leg["position_side"] == "SHORT"
    assert result.tp1_leg["reduce_only"] is None
    assert result.tp2_leg["side"] == "BUY"
    assert result.tp2_leg["position_side"] == "SHORT"
    assert result.tp2_leg["close_position"] is True
    assert result.tp2_leg["reduce_only"] is None


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "field",
    ["position_quantity", "tp1_trigger_price", "tp2_trigger_price", "tp1_quantity_fraction"],
)
def test_non_decimal_input_raises_type_error(field: str) -> None:
    kwargs: dict[str, Any] = {
        "position_quantity": D("0.010"),
        "tp1_trigger_price": D("106"),
        "tp2_trigger_price": D("110"),
        "tp1_quantity_fraction": D("0.5"),
        "filters": make_filters(),
        "side": "LONG",
        "position_mode": "ONE_WAY",
        "working_type": "MARK_PRICE",
    }
    kwargs[field] = 0.5
    with pytest.raises(TypeError, match=field):
        size_take_profits(**kwargs)


@pytest.mark.parametrize("position", ["0", "-0.01", "NaN"])
def test_non_positive_or_non_finite_position_raises(position: str) -> None:
    with pytest.raises(ValueError, match="position_quantity"):
        _size(position=position)


def test_unknown_side_or_mode_raises() -> None:
    with pytest.raises(ValueError, match="side"):
        _size(side="BOTH")
    with pytest.raises(ValueError, match="position_mode"):
        _size(mode="NETTED")


def test_unknown_working_type_raises() -> None:
    with pytest.raises(ValueError, match="working_type"):
        _size(working_type="LAST_PRICE")


def test_result_invariants() -> None:
    with pytest.raises(ValueError):
        TakeProfitSizing(
            is_no_trade=True, reason_code="OK", tp1_leg=None, tp2_leg=None, tp1_quantity=None
        )
    with pytest.raises(ValueError):
        TakeProfitSizing(
            is_no_trade=False, reason_code="OK", tp1_leg=None, tp2_leg=None, tp1_quantity=None
        )
    with pytest.raises(ValueError):
        TakeProfitSizing(
            is_no_trade=True,
            reason_code="MIN_QTY_REJECT",
            tp1_leg={"x": 1},
            tp2_leg=None,
            tp1_quantity=None,
        )


# --------------------------------------------------------------------------- #
# Byte-identical regression against the frozen sizing (research F12)
# --------------------------------------------------------------------------- #

# (tick, step) pairs; min quantity equals the step and MARKET_LOT_SIZE equals LOT_SIZE, the
# input class where both functions apply.
_GRID_PAIRS = [("0.01", "0.001"), ("0.1", "0.01"), ("0.5", "1")]
_GRID_QUANTITIES = {
    "0.001": ["0.001", "0.002", "0.010", "0.0373", "1.2345"],
    "0.01": ["0.01", "0.03", "0.10", "0.377", "12.345"],
    "1": ["1", "2", "3", "10", "37.9"],
}
_FIXED_AT = datetime(2026, 10, 1, tzinfo=UTC)


def _frozen_and_live(
    *, quantity: str, tick: str, step: str, side: str, mode: str
) -> tuple[Any, TakeProfitSizing]:
    entry = D("100")
    sign = 1 if side == "LONG" else -1
    tp1 = entry + sign * D("6.004")
    tp2 = entry + sign * D("10.006")
    snapshot = ConstraintSnapshot(
        symbol="BTCUSDT",
        price_tick_size=D(tick),
        quantity_step_size=D(step),
        min_quantity=D(step),
        min_notional=D("5"),
        metadata_observed_at_utc=_FIXED_AT,
    )
    template = ProtectiveTemplate(
        stop_loss_trigger_price=entry - sign * D("5"),
        tp1_trigger_price=tp1,
        tp2_trigger_price=tp2,
        tp1_quantity_fraction=TP1_QUANTITY_FRACTION,
    )
    frozen = size_protectives_to_filled_qty(
        filled_quantity=D(quantity),
        protective_template=template,
        constraint_snapshot=snapshot,
        position_mode=mode,
        candidate_position_side=side,
    )
    filters = LotFilters(
        symbol="BTCUSDT",
        price_tick_size=D(tick),
        lot_min_quantity=D(step),
        lot_max_quantity=D("100000"),
        lot_step_size=D(step),
        market_lot_min_quantity=D(step),
        market_lot_max_quantity=D("100000"),
        market_lot_step_size=D(step),
        min_notional=D("5"),
    )
    live = size_take_profits(
        position_quantity=D(quantity),
        tp1_trigger_price=tp1,
        tp2_trigger_price=tp2,
        tp1_quantity_fraction=TP1_QUANTITY_FRACTION,
        filters=filters,
        side=side,
        position_mode=mode,
        working_type="MARK_PRICE",
    )
    return frozen, live


def _canonical(leg: dict[str, Any] | None) -> dict[str, str] | None:
    """Every value as its str() so Decimal exponents are part of the comparison."""
    return None if leg is None else {key: str(value) for key, value in leg.items()}


_REGRESSION_CASES = [
    (tick, step, quantity, side, mode)
    for tick, step in _GRID_PAIRS
    for quantity in _GRID_QUANTITIES[step]
    for side in ("LONG", "SHORT")
    for mode in ("ONE_WAY", "HEDGE")
]


@pytest.mark.parametrize(("tick", "step", "quantity", "side", "mode"), _REGRESSION_CASES)
def test_overlap_is_byte_identical_to_the_frozen_sizing(
    tick: str, step: str, quantity: str, side: str, mode: str
) -> None:
    frozen, live = _frozen_and_live(quantity=quantity, tick=tick, step=step, side=side, mode=mode)
    assert live.is_no_trade == frozen.is_no_trade
    assert live.reason_code == frozen.reason_code
    assert live.tp1_leg == frozen.tp1_leg
    assert live.tp2_leg == frozen.tp2_leg
    assert _canonical(live.tp1_leg) == _canonical(frozen.tp1_leg)
    assert _canonical(live.tp2_leg) == _canonical(frozen.tp2_leg)


def test_regression_grid_covers_accepts_and_refusals() -> None:
    assert len(_REGRESSION_CASES) >= 2 * 2 * 3 * 5
    outcomes = {
        _frozen_and_live(quantity=q, tick=t, step=st, side=sd, mode=m)[0].reason_code
        for t, st, q, sd, m in _REGRESSION_CASES
    }
    assert "OK" in outcomes
    assert outcomes - {"OK"}  # at least one refusal path is compared too


# --------------------------------------------------------------------------- #
# EXEC-07 guard: the TP1 fraction stays a code constant outside src/execution
# --------------------------------------------------------------------------- #


def test_tp1_fraction_constant_and_template_shape_are_unchanged() -> None:
    assert D("0.5") == TP1_QUANTITY_FRACTION
    assert str(TP1_QUANTITY_FRACTION) == "0.5"
    assert [f.name for f in dataclasses.fields(ProtectiveTemplate)] == [
        "stop_loss_trigger_price",
        "tp1_trigger_price",
        "tp2_trigger_price",
        "tp1_quantity_fraction",
    ]


def test_tp_sizing_defines_no_fraction_constant() -> None:
    tree = ast.parse(TP_SIZING_PATH.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offenders.append(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Decimal"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.strip() in {"0.5", ".5", "0.50"}
        ):
            offenders.append(node.lineno)
    assert offenders == []
    referenced = [
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id == "TP1_QUANTITY_FRACTION")
        or (isinstance(node, ast.alias) and node.name == "TP1_QUANTITY_FRACTION")
    ]
    assert referenced == []


# --------------------------------------------------------------------------- #
# Purity
# --------------------------------------------------------------------------- #


def test_tp_sizing_is_pure() -> None:
    assert (
        forbidden_imports(
            TP_SIZING_PATH,
            [
                "src.backtest",
                "binance*",
                "sqlalchemy",
                "pydantic",
                "polars",
                "pandas",
                "numpy",
                "httpx",
                "asyncio",
                "datetime",
                "time",
            ],
        )
        == []
    )
    assert float_constructor_calls(TP_SIZING_PATH) == []
    assert wall_clock_calls(TP_SIZING_PATH) == []
    assert "src.backtest.semantics" not in module_imports(TP_SIZING_PATH)
