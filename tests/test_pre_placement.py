"""Pure pre-placement refusals (Phase 19, plan 19-03; D-05..D-09, D-14, RISK-04).

Hand oracles (tick 0.10, LONG zone 99.50-100.60, stop 98.00; SHORT zone 99.50-100.60, stop 102.00):

    LONG : mark 98.00 is AT the stop (crossed); mark 99.40 is one tick below the zone (outside);
           99.50 and 100.60 are the inclusive zone edges (pass); 100.70 is above the zone.
    SHORT: mark 102.00 is AT the stop (crossed); 100.70 is one tick above the zone (outside);
           99.50 and 100.60 pass; 99.40 is below the zone.
    Mark age is measured against `max_mark_price_age_ms`; an equal age passes, a future reading
    (negative age) and an unset bound refuse as MARK_PRICE_UNAVAILABLE.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import src.execution.pre_placement as pp
from src.domain.enums import TradePlanStatus
from src.execution.pre_placement import PrePlacementInputs, check_mark_price, evaluate_pre_placement

from tests.backtest_plan_helpers import make_trade_plan

NOW = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)
EXPIRY = NOW + timedelta(hours=2)
SYMBOL = "BTCUSDT"
MAX_AGE_MS = 5000


def D(text: str) -> Decimal:  # noqa: N802 - terse fixture helper
    return Decimal(text)


def _mark_kwargs(side: str, **over: Any) -> dict[str, Any]:
    stop = "98.00" if side == "LONG" else "102.00"
    base: dict[str, Any] = {
        "side": side,
        "mark_price": D("100.00"),
        "mark_time_utc": NOW - timedelta(milliseconds=1000),
        "now_utc": NOW,
        "max_mark_price_age_ms": MAX_AGE_MS,
        "sl_trigger_price": D(stop),
        "entry_min_price": D("99.50"),
        "entry_max_price": D("100.60"),
    }
    base.update(over)
    return base


def _inputs(side: str = "LONG", **over: Any) -> PrePlacementInputs:
    stop = "98.00" if side == "LONG" else "102.00"
    plan = make_trade_plan(
        side,
        entry_min="99.50",
        entry_max="100.60",
        stop_loss=stop,
        signal_close_utc=NOW - timedelta(hours=1),
        expiry_hours=3,
    )
    base: dict[str, Any] = {
        "side": side,
        "plan_status": TradePlanStatus.APPROVED,
        "signal_invalidated": False,
        "trade_plan": plan,
        "latest_closed_bar_close": D("100.00"),
        "expiry_utc": EXPIRY,
        "now_utc": NOW,
        "min_remaining_validity_seconds": 900,
        "gtd_clock_margin": timedelta(seconds=5),
        "position_symbols": frozenset({"ETHUSDT"}),
        "open_order_symbols": frozenset({"ETHUSDT"}),
        "any_unprotected": False,
        "symbol": SYMBOL,
        "mark_price": D("100.00"),
        "mark_time_utc": NOW - timedelta(milliseconds=1000),
        "max_mark_price_age_ms": MAX_AGE_MS,
        "sl_trigger_price": D(stop),
        "entry_min_price": D("99.50"),
        "entry_max_price": D("100.60"),
    }
    base.update(over)
    return PrePlacementInputs(**base)


# --------------------------------------------------------------------------- #
# check_mark_price
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("side", "mark", "expected"),
    [
        ("LONG", "100.00", None),
        ("LONG", "99.50", None),  # inclusive lower edge
        ("LONG", "100.60", None),  # inclusive upper edge
        ("LONG", "98.00", pp.MARK_PRICE_CROSSED_STOP),  # AT the stop
        ("LONG", "97.50", pp.MARK_PRICE_CROSSED_STOP),
        ("LONG", "98.10", pp.MARK_PRICE_OUTSIDE_ZONE),  # above stop, below zone
        ("LONG", "99.40", pp.MARK_PRICE_OUTSIDE_ZONE),  # one tick below entry_min
        ("LONG", "100.70", pp.MARK_PRICE_OUTSIDE_ZONE),  # one tick above entry_max
        ("SHORT", "100.00", None),
        ("SHORT", "99.50", None),
        ("SHORT", "100.60", None),
        ("SHORT", "102.00", pp.MARK_PRICE_CROSSED_STOP),
        ("SHORT", "103.00", pp.MARK_PRICE_CROSSED_STOP),
        ("SHORT", "101.90", pp.MARK_PRICE_OUTSIDE_ZONE),
        ("SHORT", "100.70", pp.MARK_PRICE_OUTSIDE_ZONE),  # one tick above entry_max
        ("SHORT", "99.40", pp.MARK_PRICE_OUTSIDE_ZONE),  # one tick below entry_min
    ],
)
def test_check_mark_price_position(side: str, mark: str, expected: str | None) -> None:
    assert check_mark_price(**_mark_kwargs(side, mark_price=D(mark))) == expected


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_check_mark_price_age_bounds(side: str) -> None:
    at_bound = NOW - timedelta(milliseconds=MAX_AGE_MS)
    assert check_mark_price(**_mark_kwargs(side, mark_time_utc=at_bound)) is None
    too_old = NOW - timedelta(milliseconds=MAX_AGE_MS + 1)
    assert check_mark_price(**_mark_kwargs(side, mark_time_utc=too_old)) == (
        pp.MARK_PRICE_UNAVAILABLE
    )
    future = NOW + timedelta(milliseconds=1)
    assert check_mark_price(**_mark_kwargs(side, mark_time_utc=future)) == pp.MARK_PRICE_UNAVAILABLE
    same_instant = NOW
    assert check_mark_price(**_mark_kwargs(side, mark_time_utc=same_instant)) is None


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("missing", ["mark_price", "mark_time_utc", "max_mark_price_age_ms"])
def test_check_mark_price_missing_input_is_unavailable(side: str, missing: str) -> None:
    assert check_mark_price(**_mark_kwargs(side, **{missing: None})) == pp.MARK_PRICE_UNAVAILABLE


def test_check_mark_price_unavailable_beats_crossed_and_crossed_beats_outside() -> None:
    stale_and_crossed = _mark_kwargs(
        "LONG", mark_price=D("97.00"), mark_time_utc=NOW - timedelta(seconds=60)
    )
    assert check_mark_price(**stale_and_crossed) == pp.MARK_PRICE_UNAVAILABLE
    # 97.00 is both crossed the stop and outside the zone: crossed is reported.
    assert check_mark_price(**_mark_kwargs("LONG", mark_price=D("97.00"))) == (
        pp.MARK_PRICE_CROSSED_STOP
    )


def test_check_mark_price_rejects_bad_side_and_naive_time() -> None:
    with pytest.raises(ValueError, match="side"):
        check_mark_price(**_mark_kwargs("BUY"))
    with pytest.raises(ValueError, match="UTC"):
        check_mark_price(**_mark_kwargs("LONG", mark_time_utc=datetime(2026, 1, 5, 9, 59, 59)))


# --------------------------------------------------------------------------- #
# PrePlacementInputs + evaluate_pre_placement (tracer)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_evaluate_valid_case_passes(side: str) -> None:
    assert evaluate_pre_placement(_inputs(side)) is None


def test_inputs_are_frozen_and_keyword_only() -> None:
    inputs = _inputs()
    with pytest.raises(AttributeError):
        inputs.symbol = "X"  # type: ignore[misc]
    with pytest.raises(TypeError):
        PrePlacementInputs("LONG")  # type: ignore[misc]


def test_inputs_validation() -> None:
    with pytest.raises(ValueError, match="side"):
        dataclasses.replace(_inputs(), side="BUY")
    with pytest.raises(ValueError, match="UTC"):
        _inputs(now_utc=datetime(2026, 1, 5, 10, 0, 0))
    with pytest.raises(TypeError, match="mark_price"):
        _inputs(mark_price=100.0)


def test_evaluate_refuses_a_crossed_mark_price() -> None:
    assert evaluate_pre_placement(_inputs("LONG", mark_price=D("98.00"))) == (
        pp.MARK_PRICE_CROSSED_STOP
    )
    assert evaluate_pre_placement(_inputs("SHORT", mark_price=D("102.00"))) == (
        pp.MARK_PRICE_CROSSED_STOP
    )
    assert evaluate_pre_placement(_inputs("LONG", mark_price=D("99.40"))) == (
        pp.MARK_PRICE_OUTSIDE_ZONE
    )
    assert evaluate_pre_placement(_inputs("LONG", max_mark_price_age_ms=None)) == (
        pp.MARK_PRICE_UNAVAILABLE
    )
