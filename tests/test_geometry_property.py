"""D-06 invariant property test over an ATR, tolerance and buffer grid (Phase 15, 15-07, 15-13).

Every plan the corrected geometry (`geometry_version` 1) produces, for Families A, B and C and
both directions, must have its stop strictly outside the whole entry zone on the loss side, TP1
strictly on the profit side of the zone midpoint, and, when `min_stop_atr` is set,
`|entry_ref - stop| >= min_stop_atr x ATR` (D-18, D-06, D-08).

Plan 15-13 adds the legacy dimension: the same grid over the legacy parameter shapes (no
`geometry_version`, no pivot keys, no `min_stop_atr`; the sidecar `*_legacy_contrast` sets,
which are baseline-v5 plus the case's own keys), since the structural validator applies to every
parameter set. Legacy Family A may legitimately produce zero plans (its stop sits one stop
buffer beyond the swing low while the entry zone is widened by the tolerance and the entry
buffer); the legacy tests state that explicitly instead of requiring plans from it.

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
    legacy: bool = False


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


# Legacy shape (plan 15-13): sidecar legacy case and window builders per family and direction.
# Family C needs the flat 4h window for the legacy NEUTRAL regime (EMA50 equality, D-25).
LEGACY_FAMILIES: dict[str, dict[str, tuple[str, Any]]] = {
    "trend-pullback": {
        "LONG": ("a_long_legacy_contrast", geometry_builders.family_a_long_window),
        "SHORT": ("a_long_legacy_contrast", geometry_builders.family_a_short_window),
    },
    "breakout-retest": {
        "LONG": ("b_long_legacy_contrast", geometry_builders.family_b_long_window),
        "SHORT": ("b_long_legacy_contrast", geometry_builders.family_b_short_window),
    },
    "range-mr": {
        "LONG": ("c_long_legacy_contrast", geometry_builders.range_mr_long_flat_context_window),
        "SHORT": (
            "c_long_legacy_contrast",
            lambda: geometry_builders.range_mr_window(mirror=True, regime=None),
        ),
    },
}


@cache
def _window(
    family: str, direction: str, atr: str, legacy: bool = False
) -> tuple[list[Candle], list[Candle]]:
    """The family window rescaled so its constant bar range (ATR) is `atr`."""
    _case, builder = (LEGACY_FAMILIES if legacy else FAMILIES)[family][direction]
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
    legacy: bool = False,
) -> Cell:
    case, _builder = (LEGACY_FAMILIES if legacy else FAMILIES)[family][direction]
    overrides = {
        "zone_tolerance_atr": zone_tolerance_atr,
        "entry_buffer_atr": entry_buffer_atr,
        "sl_buffer_atr": sl_buffer_atr,
    }
    if min_stop_atr is not None:
        overrides["min_stop_atr"] = min_stop_atr
    parameter_set = _case_set(case, **overrides)
    if legacy:
        assert "geometry_version" not in parameter_set.params
        assert "min_stop_atr" not in parameter_set.params
    setup, context = _window(family, direction, atr, legacy)
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
        return Cell(*key, "strategy", result.reason_code, None, legacy)
    planned = plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=account,
        created_at_utc=setup[-1].close_time_utc,
    )
    if planned.is_no_trade or planned.trade_plan is None:
        return Cell(*key, "planner", planned.reason_code, None, legacy)
    return Cell(*key, "plan", planned.reason_code, planned.trade_plan, legacy)


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


@cache
def _legacy_grid() -> tuple[Cell, ...]:
    """The same grid over the legacy parameter shapes (no `min_stop_atr`: a legacy set has none)."""
    cells: list[Cell] = []
    for family in sorted(LEGACY_FAMILIES):
        for direction in ("LONG", "SHORT"):
            for tol, buf, slb, atr in product(ZONE_TOLERANCES, ENTRY_BUFFERS, SL_BUFFERS, ATRS):
                cells.append(_run_cell(family, direction, tol, buf, slb, atr, None, legacy=True))
    return tuple(cells)


def _label(cell: Cell) -> str:
    return (
        f"{'legacy ' if cell.legacy else ''}{cell.family} {cell.direction} "
        f"tol={cell.zone_tolerance_atr} "
        f"buf={cell.entry_buffer_atr} sl={cell.sl_buffer_atr} atr={cell.atr} "
        f"min_stop={cell.min_stop_atr}"
    )


def _plans(family: str, direction: str) -> list[Cell]:
    return [c for c in _grid() if c.family == family and c.direction == direction and c.trade_plan]


def _legacy_plans(family: str, direction: str) -> list[Cell]:
    return [
        c
        for c in _legacy_grid()
        if c.family == family and c.direction == direction and c.trade_plan
    ]


def _assert_invariants(cell: Cell) -> None:
    """Literal Decimal comparisons on the stored fields (never the planner's own validator)."""
    trade_plan = cell.trade_plan
    assert trade_plan is not None
    lowest, highest = trade_plan.entry_min_price, trade_plan.entry_max_price
    stop = trade_plan.stop_loss_price
    entry_ref = (lowest + highest) / 2
    tp1 = Decimal(json.loads(trade_plan.take_profit_json)["tp1"])
    assert lowest <= highest, _label(cell)
    if cell.direction == "LONG":
        assert stop < lowest, f"stop not below the zone: {_label(cell)}"
        assert tp1 > entry_ref, f"TP1 not above the zone midpoint: {_label(cell)}"
    else:
        assert stop > highest, f"stop not above the zone: {_label(cell)}"
        assert tp1 < entry_ref, f"TP1 not below the zone midpoint: {_label(cell)}"
    if cell.min_stop_atr is not None:
        floor = Decimal(cell.min_stop_atr) * Decimal(cell.atr)
        assert abs(entry_ref - stop) >= floor, f"stop closer than min_stop_atr: {_label(cell)}"


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_every_plan_has_its_stop_outside_the_whole_zone_and_tp1_on_the_profit_side(
    family: str, direction: str
) -> None:
    checked = 0
    for cell in _plans(family, direction):
        _assert_invariants(cell)
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


# --------------------------------------------------------------------------- #
# Plan 15-13: the legacy dimension (no geometry_version, no pivot keys, no min_stop_atr).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("family", sorted(LEGACY_FAMILIES))
def test_legacy_every_plan_has_its_stop_outside_the_whole_zone_and_tp1_on_the_profit_side(
    family: str, direction: str
) -> None:
    for cell in _legacy_plans(family, direction):
        assert cell.legacy
        _assert_invariants(cell)


def test_legacy_every_no_trade_reason_is_in_the_closed_set() -> None:
    for cell in _legacy_grid():
        if cell.trade_plan is None:
            assert cell.reason in ALLOWED_REASONS, f"{cell.reason} at {_label(cell)}"


def test_legacy_grid_size_is_the_documented_full_product() -> None:
    expected = (
        len(LEGACY_FAMILIES)
        * 2
        * len(ZONE_TOLERANCES)
        * len(ENTRY_BUFFERS)
        * len(SL_BUFFERS)
        * len(ATRS)
    )
    assert len(_legacy_grid()) == expected == 486
    assert all(c.legacy and c.min_stop_atr is None for c in _legacy_grid())


def test_legacy_vacuity_the_validator_refuses_signals_that_reach_plan() -> None:
    """Not vacuous on the rejecting side: every legacy family has cells that produced a signal
    and were refused by the validator. Without the universal call those cells would carry plans
    that fail the invariant assertions above."""
    for family in sorted(LEGACY_FAMILIES):
        refused = [
            c
            for c in _legacy_grid()
            if c.family == family and c.stage == "planner" and c.trade_plan is None
        ]
        assert refused, f"no legacy {family} cell reached plan() and was refused"
        assert {c.reason for c in refused} <= {"STOP_TOO_TIGHT", "INVALIDATED", "RR_TOO_LOW"}
    reasons = {c.reason for c in _legacy_grid() if c.stage == "planner"}
    assert {"STOP_TOO_TIGHT", "INVALIDATED"} <= reasons


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("family", ["breakout-retest", "range-mr"])
def test_legacy_vacuity_families_b_and_c_still_produce_plans(family: str, direction: str) -> None:
    assert _legacy_plans(family, direction), f"no legacy plan for {family} {direction}"


def test_legacy_family_a_plans_exist_only_where_the_stop_buffer_exceeds_the_zone_widening() -> None:
    """Legacy Family A stop = swing_low - sl_buffer, entry_min = swing_low - (tol + buffer) x ATR.

    A legacy A plan can therefore exist only in cells with `sl_buffer_atr > zone_tolerance_atr +
    entry_buffer_atr`. The grid is allowed to hold zero such plans (the counts are not pinned);
    it must never hold one anywhere else.
    """
    for cell in _legacy_grid():
        if cell.family != "trend-pullback" or cell.trade_plan is None:
            continue
        widening = Decimal(cell.zone_tolerance_atr) + Decimal(cell.entry_buffer_atr)
        assert Decimal(cell.sl_buffer_atr) > widening, _label(cell)
