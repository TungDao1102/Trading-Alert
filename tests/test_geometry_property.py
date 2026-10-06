"""D-06 invariant property test over an ATR, tolerance and buffer grid (Phase 15, plan 15-07).

Every plan the corrected geometry (`geometry_version` 1) produces, for Families A, B and C and
both directions, must have its stop strictly outside the whole entry zone on the loss side, TP1
strictly on the profit side of the zone midpoint, and, when `min_stop_atr` is set,
`|entry_ref - stop| >= min_stop_atr x ATR` (D-18, D-06, D-08).

The grid is explicit and sorted: no random draws, no hypothesis, byte-reproducible. The
assertions are literal Decimal comparisons on the stored TradePlan fields; they never call the
planner's own validator, so a defect in it cannot make this test agree with itself.

The windows are the hand-derived constant-range windows of plans 15-03..15-06 (ATR 2.00),
rescaled by a positive factor so the bar range, and therefore the ATR, takes each grid value
exactly. A positive factor keeps every ratio of the derivation in ATR units, so the same
setup is detected at every scale. The grid is never reduced by dropping a family or a
direction; the vacuity test proves it still produces plans for each.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from itertools import product
from typing import Any

import pytest
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot
from src.domain.trade_plan import TradePlan

from tests import geometry_builders
from tests.test_planner_geometry import _case_set

BASE_ATR = Decimal("2")
EQUITY = Decimal("10000")
RISK_RATE = Decimal("0.005")

ZONE_TOLERANCES = ("0.25", "0.5", "1.0")
ENTRY_BUFFERS = ("0", "0.1", "0.3")
SL_BUFFERS = ("0.05", "0.2", "0.5")
ATRS = ("0.5", "2", "8")
MIN_STOP_ATRS: tuple[str | None, ...] = (None, "0.5")

# family id -> (sidecar case names LONG and SHORT, window builders LONG and SHORT)
FAMILIES: dict[str, dict[str, tuple[str, Any]]] = {
    "trend-pullback": {
        "LONG": ("a_long_worked", geometry_builders.family_a_long_window),
        "SHORT": ("a_short_worked", geometry_builders.family_a_short_window),
    },
    "breakout-retest": {
        "LONG": ("b_long_worked", geometry_builders.family_b_long_window),
        "SHORT": ("b_short_worked", geometry_builders.family_b_short_window),
    },
    "range-mr": {
        "LONG": ("c_long_worked", geometry_builders.range_mr_long_window),
        "SHORT": ("c_short_worked", geometry_builders.range_mr_short_window),
    },
}

ALLOWED_REASONS = frozenset(
    {"STOP_TOO_TIGHT", "INVALIDATED", "RR_TOO_LOW", "STALE_SETUP", "NO_TRADE_REGIME"}
)


@dataclass(frozen=True)
class Cell:
    """One grid cell and what the real pipeline did with it."""

    family: str
    direction: str
    zone_tolerance_atr: str
    entry_buffer_atr: str
    sl_buffer_atr: str
    atr: str
    min_stop_atr: str | None
    stage: str  # "strategy" | "planner" | "plan"
    reason: str
    trade_plan: TradePlan | None


def _scaled(candle: Candle, factor: Decimal) -> Candle:
    return Candle(
        symbol=candle.symbol,
        interval=candle.interval,
        open_time_utc=candle.open_time_utc,
        close_time_utc=candle.close_time_utc,
        open=candle.open * factor,
        high=candle.high * factor,
        low=candle.low * factor,
        close=candle.close * factor,
        volume=candle.volume,
    )


@cache
def _window(family: str, direction: str, atr: str) -> tuple[list[Candle], list[Candle]]:
    """The family window rescaled so its constant bar range (ATR) is `atr`."""
    _case, builder = FAMILIES[family][direction]
    setup, context = builder()
    factor = Decimal(atr) / BASE_ATR
    return [_scaled(c, factor) for c in setup], [_scaled(c, factor) for c in context]


def _run_cell(
    family: str,
    direction: str,
    zone_tolerance_atr: str,
    entry_buffer_atr: str,
    sl_buffer_atr: str,
    atr: str,
    min_stop_atr: str | None,
) -> Cell:
    case, _builder = FAMILIES[family][direction]
    overrides = {
        "zone_tolerance_atr": zone_tolerance_atr,
        "entry_buffer_atr": entry_buffer_atr,
        "sl_buffer_atr": sl_buffer_atr,
    }
    if min_stop_atr is not None:
        overrides["min_stop_atr"] = min_stop_atr
    parameter_set = _case_set(case, **overrides)
    setup, context = _window(family, direction, atr)
    account = AccountState(equity=EQUITY, risk_rate=RISK_RATE)
    result = evaluate(
        snapshot=MarketSnapshot(
            symbol="BTCUSDT", setup_candles=setup, context_candles=context, source_timeframe="1h"
        ),
        account_state=account,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    key = (
        family,
        direction,
        zone_tolerance_atr,
        entry_buffer_atr,
        sl_buffer_atr,
        atr,
        min_stop_atr,
    )
    if result.is_no_trade or result.signal is None:
        return Cell(*key, "strategy", result.reason_code, None)
    planned = plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=account,
        created_at_utc=setup[-1].close_time_utc,
    )
    if planned.is_no_trade or planned.trade_plan is None:
        return Cell(*key, "planner", planned.reason_code, None)
    return Cell(*key, "plan", planned.reason_code, planned.trade_plan)


@cache
def _grid() -> tuple[Cell, ...]:
    """Every cell of the sorted grid, evaluated once for the whole module."""
    cells: list[Cell] = []
    for family in sorted(FAMILIES):
        for direction in ("LONG", "SHORT"):
            for tol, buf, slb, atr, min_stop in product(
                ZONE_TOLERANCES, ENTRY_BUFFERS, SL_BUFFERS, ATRS, MIN_STOP_ATRS
            ):
                cells.append(_run_cell(family, direction, tol, buf, slb, atr, min_stop))
    return tuple(cells)


def _label(cell: Cell) -> str:
    return (
        f"{cell.family} {cell.direction} tol={cell.zone_tolerance_atr} "
        f"buf={cell.entry_buffer_atr} sl={cell.sl_buffer_atr} atr={cell.atr} "
        f"min_stop={cell.min_stop_atr}"
    )


def _plans(family: str, direction: str) -> list[Cell]:
    return [c for c in _grid() if c.family == family and c.direction == direction and c.trade_plan]


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_every_plan_has_its_stop_outside_the_whole_zone_and_tp1_on_the_profit_side(
    family: str, direction: str
) -> None:
    checked = 0
    for cell in _plans(family, direction):
        trade_plan = cell.trade_plan
        assert trade_plan is not None
        lowest, highest = trade_plan.entry_min_price, trade_plan.entry_max_price
        stop = trade_plan.stop_loss_price
        entry_ref = (lowest + highest) / 2
        tp1 = Decimal(json.loads(trade_plan.take_profit_json)["tp1"])
        assert lowest <= highest, _label(cell)
        if direction == "LONG":
            assert stop < lowest, f"stop not below the zone: {_label(cell)}"
            assert tp1 > entry_ref, f"TP1 not above the zone midpoint: {_label(cell)}"
        else:
            assert stop > highest, f"stop not above the zone: {_label(cell)}"
            assert tp1 < entry_ref, f"TP1 not below the zone midpoint: {_label(cell)}"
        if cell.min_stop_atr is not None:
            floor = Decimal(cell.min_stop_atr) * Decimal(cell.atr)
            assert abs(entry_ref - stop) >= floor, f"stop closer than min_stop_atr: {_label(cell)}"
        checked += 1
    assert checked > 0


def test_every_no_trade_reason_is_in_the_closed_set() -> None:
    for cell in _grid():
        if cell.trade_plan is None:
            assert cell.reason in ALLOWED_REASONS, f"{cell.reason} at {_label(cell)}"


def test_vacuity_every_family_and_direction_produces_a_plan() -> None:
    """Vacuity proof (permanent): at least one plan per family and direction, at every ATR."""
    for family in sorted(FAMILIES):
        for direction in ("LONG", "SHORT"):
            assert _plans(family, direction), f"no plan produced for {family} {direction}"
            for atr in ATRS:
                assert any(c.atr == atr for c in _plans(family, direction)), (
                    f"no plan produced for {family} {direction} at ATR {atr}"
                )


def test_vacuity_the_min_stop_atr_branch_is_exercised() -> None:
    """Some plan passes with `min_stop_atr` set, so the distance assertion is not skipped."""
    assert any(c.trade_plan is not None and c.min_stop_atr is not None for c in _grid())


def test_vacuity_plans_exist_at_every_tolerance_buffer_and_min_stop_setting() -> None:
    plans = [c for c in _grid() if c.trade_plan is not None]
    for tolerance in ZONE_TOLERANCES:
        assert any(c.zone_tolerance_atr == tolerance for c in plans), tolerance
    for buffer in ENTRY_BUFFERS:
        assert any(c.entry_buffer_atr == buffer for c in plans), buffer
    for sl_buffer in SL_BUFFERS:
        assert any(c.sl_buffer_atr == sl_buffer for c in plans), sl_buffer
    assert any(c.min_stop_atr is None for c in plans)


def test_the_grid_size_is_the_documented_full_product() -> None:
    expected = (
        len(FAMILIES)
        * 2
        * len(ZONE_TOLERANCES)
        * len(ENTRY_BUFFERS)
        * len(SL_BUFFERS)
        * len(ATRS)
        * len(MIN_STOP_ATRS)
    )
    assert len(_grid()) == expected == 972
