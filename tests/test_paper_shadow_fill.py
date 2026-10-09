"""SHADOW fill driver over the Phase 14 lifecycle (Phase 16, plan 16-19, D-14, L-02).

Task 1 (tracer): one confirmed plan is filled over recorded minutes through the public Phase 14
functions (`new_plan_state`, `advance`, `booking_for_event`, `build_trade_record`) and the trade
record equals the `simulate` trade for the same minutes byte for byte when the eligibility start
equals the signal close. An AST check proves the driver neither uses the private `_Engine` nor
re-defines a lifecycle step of its own.

Task 3 (below the tracer tests): the Q-B eligibility start (`confirm-plus-one`, decided by the
user), its audit fields, and the replay/restart properties of the threshold.

No network, no wall clock: every instant is an explicit argument.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.case import ParsedCase, parse_case_input
from src.backtest.constraints import select_constraints
from src.backtest.engine import simulate
from src.backtest.funding import FundingCoverageError
from src.backtest.series import ListMinuteSource, parse_minute_row
from src.core.types import Candle
from src.domain.signal import Signal
from src.domain.enums import SignalStatus
from src.paper import shadow_fill
from src.paper.loop import BarOutcome
from src.paper.shadow_fill import FundingHistory, ShadowFillDriver

from tests.backtest_case_helpers import (
    DATA_END,
    SIGNAL_CLOSE,
    SYMBOL,
    fixed_risk_fn,
)
from tests.test_backtest_engine import tracer_case

SHADOW_FILL_PATH = Path(__file__).resolve().parent.parent / "src" / "paper" / "shadow_fill.py"
QUANTITY = "15.928"
REALIZED_RISK = "49.997992"


def _source(case: dict[str, Any]) -> ListMinuteSource:
    """The recorded minutes of a case as the `MinuteSource` the lifecycle reads."""
    trade = [parse_minute_row(r, kind="trade") for r in case["trade_bars_1m"]]
    mark = [parse_minute_row(r, kind="mark") for r in case["mark_bars_1m"]]
    return ListMinuteSource({SYMBOL: trade}, {SYMBOL: mark})


def _outcome(parsed: ParsedCase) -> BarOutcome:
    """The risk-passed bar outcome of the scripted plan, sized by the same stand-in as simulate."""
    scripted = parsed.scripted_plans[0] if parsed.scripted_plans else None
    assert scripted is not None
    verdict = fixed_risk_fn(QUANTITY, REALIZED_RISK)(trade_plan=scripted.plan)
    closed = Candle(
        symbol=SYMBOL,
        interval="1h",
        open_time_utc=SIGNAL_CLOSE - timedelta(hours=1) + timedelta(milliseconds=1),
        close_time_utc=SIGNAL_CLOSE,
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    signal = Signal(
        signal_id=scripted.plan.signal_id,
        strategy_id=parsed.strategy_id,
        strategy_version=parsed.strategy_version,
        parameter_set_id=parsed.parameter_set_id,
        parameter_set_hash="hash",
        symbol=SYMBOL,
        direction=scripted.direction,
        setup_type="SCRIPTED",
        source_timeframe="1h",
        source_candle_close_utc=SIGNAL_CLOSE,
        detected_at_utc=SIGNAL_CLOSE,
        status=SignalStatus.DETECTED,
        expires_at_utc=scripted.plan.expiry_utc,
    )
    return BarOutcome(
        closed_candle=closed,
        stage="risk_passed",
        reason_code="OK",
        signal=signal,
        trade_plan=scripted.plan,
        verdict=verdict,
        regime=scripted.regime,
    )


def _driver(parsed: ParsedCase, expected: dict[str, Any]) -> ShadowFillDriver:
    pit = select_constraints(parsed.constraints, symbol=SYMBOL, bar_close_utc=SIGNAL_CLOSE)
    return ShadowFillDriver(
        cost_model=parsed.cost_model,
        constraint_snapshot=pit.snapshot,
        strategy_version=expected["strategy_version"],
        parameter_set_hash=expected["parameter_set_hash"],
        constraints_extrapolated=pit.extrapolated,
    )


def _funding(parsed: ParsedCase) -> FundingHistory:
    return FundingHistory(
        rows=parsed.funding_rows,
        loaded_start_utc=parsed.data_start_utc,
        loaded_end_utc=parsed.data_end_utc,
    )


def _tracer() -> tuple[dict[str, Any], ParsedCase, dict[str, Any]]:
    case = tracer_case()
    expected = simulate(case, risk_fn=fixed_risk_fn(QUANTITY, REALIZED_RISK))
    return case, parse_case_input(case), expected


# --------------------------------------------------------------------------- #
# Task 1 - tracer
# --------------------------------------------------------------------------- #


def test_shadow_trade_record_equals_the_simulate_trade_when_start_is_the_signal_close() -> None:
    case, parsed, expected = _tracer()
    assert len(expected["trades"]) == 1
    driver = _driver(parsed, expected)

    opened = driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    assert opened.opened
    driver.advance_to(DATA_END, _source(case), funding=_funding(parsed))

    assert driver.is_closed
    assert driver.trade_record().to_dict() == expected["trades"][0]


def test_advancing_in_several_windows_gives_the_same_record_as_one_window() -> None:
    case, parsed, expected = _tracer()
    source = _source(case)
    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    for hour, minute in ((10, 0), (10, 1), (10, 30), (10, 40), (11, 0)):
        driver.advance_to(
            datetime(2026, 1, 5, hour, minute, tzinfo=UTC), source, funding=_funding(parsed)
        )
    driver.advance_to(DATA_END, source, funding=_funding(parsed))

    assert driver.trade_record().to_dict() == expected["trades"][0]


def test_bookings_follow_the_lifecycle_events_in_time_order() -> None:
    case, parsed, expected = _tracer()
    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    driver.advance_to(DATA_END, _source(case), funding=_funding(parsed))

    assert [b.kind for b in driver.bookings] == ["FILL", "EXIT"]
    times = [b.time_utc for b in driver.bookings]
    assert times == sorted(times)
    record = driver.trade_record()
    assert record.realized_pnl is not None
    assert sum((b.amount for b in driver.bookings), Decimal("0")) == record.realized_pnl


def test_a_position_open_without_funding_history_fails_closed() -> None:
    case, parsed, expected = _tracer()
    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    with pytest.raises(FundingCoverageError):
        driver.advance_to(DATA_END, _source(case), funding=None)
    # Nothing moved: the failed window left the state at the signal close.
    assert driver.bookings == ()
    assert driver.advanced_to_utc == SIGNAL_CLOSE


def test_the_driver_calls_the_public_lifecycle_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    case, parsed, expected = _tracer()
    calls: dict[str, int] = {"new_plan_state": 0, "advance": 0, "booking_for_event": 0}

    def spy(name: str) -> Callable[..., Any]:
        original = getattr(shadow_fill, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls[name] += 1
            return original(*args, **kwargs)

        return wrapper

    for name in calls:
        monkeypatch.setattr(shadow_fill, name, spy(name))
    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    driver.advance_to(DATA_END, _source(case), funding=_funding(parsed))
    driver.trade_record()

    assert calls["new_plan_state"] == 1
    assert calls["advance"] >= 1
    assert calls["booking_for_event"] == 2  # FILL and EXIT


def test_the_driver_neither_uses_the_private_engine_nor_defines_a_lifecycle_step() -> None:
    tree = ast.parse(SHADOW_FILL_PATH.read_text(encoding="utf-8"))
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    referenced |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            referenced |= {alias.name for alias in node.names}
    assert "_Engine" not in referenced
    assert "simulate" not in referenced and "simulate_detailed" not in referenced
    defined = {
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    forbidden = {
        "advance",
        "new_plan_state",
        "booking_for_event",
        "build_trade_record",
        "protective_levels_for_fill",
        "funding_events",
        "cancel_plan",
        "finalize_at_data_end",
    }
    assert defined.isdisjoint(forbidden), defined & forbidden


def test_an_outcome_that_did_not_pass_risk_is_refused() -> None:
    _case, parsed, expected = _tracer()
    passed = _outcome(parsed)
    rejected = BarOutcome(
        closed_candle=passed.closed_candle,
        stage="risk",
        reason_code="UTILIZATION_REJECT",
        signal=passed.signal,
        trade_plan=passed.trade_plan,
        verdict=passed.verdict,
    )
    driver = _driver(parsed, expected)
    with pytest.raises(ValueError, match="risk_passed"):
        driver.open(rejected, eligibility_start_utc=SIGNAL_CLOSE)
