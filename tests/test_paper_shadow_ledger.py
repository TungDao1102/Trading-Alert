"""SHADOW paper ledger tests (Phase 16, plan 16-23, D-17, G4-010, D052 item i, REV-07).

Task 1 (tracer): a confirmed plan's exposure and its booked loss feed the next risk inputs
exactly as the Phase 14 `Ledger` returns them for the same sequence, the initial equity is a
required input with no default and no numeric equity literal, and a second plan for a symbol
that already holds one is refused with the engine's own conflict label.

Every equity value here is a TEST value chosen for hand arithmetic; none is a recommendation
(REV-07: the real value is set by the user at plan 16-34).

No network, no wall clock: every instant is an explicit argument.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.backtest.ledger import (
    Ledger,
    apply_booking,
    daily_loss_quote,
    open_positions_for_risk,
    register_exposure,
    remove_exposure,
    roll_to,
)
from src.backtest.lifecycle import (
    EVENT_EXIT,
    EVENT_FILL,
    EVENT_TP1,
    LifecycleEvent,
    PlanState,
    new_plan_state,
)
from src.backtest.records import BOOKING_EXIT, BOOKING_FILL, Booking
from src.backtest.semantics import NO_TRADE_CONFLICT
from src.domain.registry import load_parameter_set
from src.paper import shadow_ledger
from src.paper.shadow_ledger import RegisterResult, ShadowLedger

from tests.backtest_plan_helpers import SIGNAL_CLOSE, D, make_trade_plan

SHADOW_LEDGER_PATH = Path(__file__).resolve().parent.parent / "src" / "paper" / "shadow_ledger.py"
PARAMS = load_parameter_set("trend-pullback", "baseline-v5").params
# Test values only (hand arithmetic): 10000 equity, one stopped-out trade losing 100.50.
TEST_EQUITY = D("10000")
START = SIGNAL_CLOSE - timedelta(hours=1)
FILL_TIME = SIGNAL_CLOSE + timedelta(minutes=2)
EXIT_TIME = SIGNAL_CLOSE + timedelta(minutes=41)
NEXT_SIGNAL = SIGNAL_CLOSE + timedelta(hours=2)
TICK = D("0.10")


def _state(
    plan_id: str = "tp-1",
    symbol: str = "BTCUSDT",
    direction: str = "LONG",
    risk: str = "50",
    quantity: str = "0.5",
    fill_quantity: str | None = None,
) -> PlanState:
    plan = make_trade_plan(
        direction=direction,
        trade_plan_id=plan_id,
        signal_id=f"sig-{plan_id}",
        quantity=quantity,
    )
    return new_plan_state(
        plan=plan,
        symbol=symbol,
        direction=direction,
        signal_close_utc=SIGNAL_CLOSE,
        price_tick_size=TICK,
        planned_quantity=D(quantity),
        sized_realized_risk=D(risk),
        fill_quantity=None if fill_quantity is None else D(fill_quantity),
    )


def _booking(
    time_utc: datetime, amount: str, kind: str = BOOKING_FILL, plan_id: str = "tp-1"
) -> Booking:
    return Booking(
        time_utc=time_utc,
        symbol="BTCUSDT",
        trade_plan_id=plan_id,
        amount=D(amount),
        kind=kind,
    )


def _shadow() -> ShadowLedger:
    return ShadowLedger(
        initial_equity=TEST_EQUITY, parameter_set_params=PARAMS, started_at_utc=START
    )


def _event(kind: str, time_utc: datetime, quantity: str | None) -> LifecycleEvent:
    return LifecycleEvent(
        kind=kind,
        symbol="BTCUSDT",
        trade_plan_id="tp-1",
        time_utc=time_utc,
        price=D("100"),
        quantity=None if quantity is None else D(quantity),
    )


# ---------------------------------------------------------------- Test 1: parity


def test_registered_plan_and_stop_loss_give_the_backtest_risk_inputs() -> None:
    shadow = _shadow()
    result = shadow.register(_state())
    assert result == RegisterResult(registered=True, reason_code="OK")

    # Reference: the Phase 14 ledger driven by the same calls in the same order.
    reference = Ledger.start(equity=TEST_EQUITY, parameter_set_params=PARAMS, at_utc=START)
    reference = register_exposure(
        reference,
        trade_plan_id="tp-1",
        symbol="BTCUSDT",
        position_side="LONG",
        open_risk=D("50"),
    )
    # While the plan is registered and nothing is booked the inputs already agree.
    reference_resting = roll_to(reference, NEXT_SIGNAL)
    positions, loss = shadow.risk_inputs(NEXT_SIGNAL)
    assert positions == open_positions_for_risk(reference_resting)
    assert loss == daily_loss_quote(reference_resting)
    assert [p.open_risk for p in positions] == [D("50")]

    # A stop-loss: entry cost, then the SL leg; the exit event frees the exposure.
    for booking in (
        _booking(FILL_TIME, "-2.50"),
        _booking(EXIT_TIME, "-98.00", BOOKING_EXIT),
    ):
        shadow.apply(booking)
        reference = apply_booking(reference, booking)
    reference = remove_exposure(reference, trade_plan_id="tp-1")
    shadow.apply_event(_event(EVENT_EXIT, EXIT_TIME, "0.5"), start_state=_state())

    positions, loss = shadow.risk_inputs(EXIT_TIME)
    assert positions == open_positions_for_risk(reference) == []
    assert loss == daily_loss_quote(reference) == D("100.50")
    assert shadow.equity == reference.equity == D("9899.50")


def test_open_position_stays_in_the_risk_inputs_until_it_exits() -> None:
    shadow = _shadow()
    shadow.register(_state())
    shadow.apply(_booking(FILL_TIME, "-2.50"))
    positions, loss = shadow.risk_inputs(FILL_TIME)
    assert [(p.symbol, p.position_side, p.open_risk) for p in positions] == [
        ("BTCUSDT", "LONG", D("50"))
    ]
    assert loss == D("2.50")


def test_partial_fill_rescales_the_exposure_like_the_engine() -> None:
    shadow = _shadow()
    state = _state(quantity="1.0", fill_quantity="0.4", risk="50")
    shadow.register(state)
    shadow.apply_event(_event(EVENT_FILL, FILL_TIME, "0.4"), start_state=state)
    positions, _loss = shadow.risk_inputs(FILL_TIME)
    # realized_risk_for_fill: 50 x 0.4 / 1.0
    assert [p.open_risk for p in positions] == [D("20")]


def test_tp1_scales_the_exposure_to_the_remaining_quantity() -> None:
    shadow = _shadow()
    state = _state(quantity="1.0", risk="50")
    shadow.register(state)
    shadow.apply_event(_event(EVENT_FILL, FILL_TIME, "1.0"), start_state=state)
    shadow.apply_event(_event(EVENT_TP1, EXIT_TIME, "0.5"), start_state=state)
    positions, _loss = shadow.risk_inputs(EXIT_TIME)
    assert [p.open_risk for p in positions] == [D("25")]


def test_day_rolls_to_the_signal_close_like_the_engine() -> None:
    shadow = _shadow()
    shadow.apply(_booking(FILL_TIME, "-10"))
    next_day = datetime(2026, 1, 6, 0, 0, 0, tzinfo=UTC)
    _positions, loss = shadow.risk_inputs(next_day)
    assert loss == D("0")


# --------------------------------------------------- Test 2: required equity, no literal


def test_initial_equity_is_a_required_input() -> None:
    with pytest.raises(TypeError):
        ShadowLedger(parameter_set_params=PARAMS, started_at_utc=START)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ShadowLedger()  # type: ignore[call-arg]


def test_initial_equity_must_be_a_positive_decimal() -> None:
    with pytest.raises(TypeError):
        ShadowLedger(
            initial_equity=10000,  # type: ignore[arg-type]
            parameter_set_params=PARAMS,
            started_at_utc=START,
        )
    with pytest.raises(ValueError):
        ShadowLedger(initial_equity=D("0"), parameter_set_params=PARAMS, started_at_utc=START)


def test_the_module_contains_no_numeric_equity_literal() -> None:
    tree = ast.parse(SHADOW_LEDGER_PATH.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
            if isinstance(node.value, int | float) and node.value != 0:
                offenders.append(f"line {node.lineno}: {node.value!r}")
            if isinstance(node.value, str) and node.value.replace(".", "", 1).isdigit():
                if Decimal(node.value) != 0:
                    offenders.append(f"line {node.lineno}: {node.value!r}")
    assert offenders == []
    # No default on the constructor's equity parameter either.
    init = next(
        n
        for c in ast.walk(tree)
        if isinstance(c, ast.ClassDef) and c.name == "ShadowLedger"
        for n in c.body
        if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    assert init.args.kw_defaults == [None] * len(init.args.kwonlyargs)
    assert init.args.defaults == []


def test_the_ledger_is_called_not_copied() -> None:
    tree = ast.parse(SHADOW_LEDGER_PATH.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "src.backtest.ledger"
        for alias in node.names
    }
    assert {"Ledger", "apply_booking", "register_exposure", "open_positions_for_risk"} <= imported
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not {"apply_booking", "register_exposure", "daily_loss_quote"} & defined
    assert shadow_ledger.Ledger is Ledger


# ------------------------------------------------------ Test 3: one active plan per symbol


def test_second_plan_for_the_same_symbol_is_refused_with_the_engine_label() -> None:
    shadow = _shadow()
    assert shadow.register(_state("tp-1")).registered
    before = shadow.risk_inputs(NEXT_SIGNAL)
    refused = shadow.register(_state("tp-2", direction="SHORT"))
    assert refused == RegisterResult(registered=False, reason_code=NO_TRADE_CONFLICT)
    assert refused.reason_code == "CONFLICT_WITH_OPEN_POSITION"
    assert shadow.risk_inputs(NEXT_SIGNAL) == before  # a refused plan changes nothing


def test_a_plan_for_another_symbol_is_accepted() -> None:
    shadow = _shadow()
    shadow.register(_state("tp-1", symbol="BTCUSDT"))
    assert shadow.register(_state("tp-2", symbol="ETHUSDT")).registered
    positions, _loss = shadow.risk_inputs(NEXT_SIGNAL)
    assert [p.symbol for p in positions] == ["BTCUSDT", "ETHUSDT"]


def test_the_symbol_is_free_again_after_the_plan_exits() -> None:
    shadow = _shadow()
    state = _state("tp-1")
    shadow.register(state)
    shadow.apply_event(_event(EVENT_EXIT, EXIT_TIME, "0.5"), start_state=state)
    assert shadow.register(_state("tp-2")).registered
