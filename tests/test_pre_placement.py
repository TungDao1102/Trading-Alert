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


# --------------------------------------------------------------------------- #
# check_plan_status (D-09 deny-list)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (TradePlanStatus.READY, None),
        (TradePlanStatus.APPROVAL_PENDING, None),
        (TradePlanStatus.APPROVED, None),
        (TradePlanStatus.EXPIRED, pp.PLAN_STATUS_INVALID),
        (TradePlanStatus.INVALIDATED, pp.PLAN_STATUS_INVALID),
        (TradePlanStatus.SUPERSEDED, pp.PLAN_STATUS_INVALID),
    ],
)
def test_check_plan_status_is_a_deny_list(status: TradePlanStatus, expected: str | None) -> None:
    assert pp.check_plan_status(status) == expected


def test_check_plan_status_covers_every_status() -> None:
    # A future status must be classified on purpose: every member has a defined verdict here.
    verdicts = {status: pp.check_plan_status(status) for status in TradePlanStatus}
    assert len(verdicts) == 6


# --------------------------------------------------------------------------- #
# Invalidation: parity with the backtest, distinct code
# --------------------------------------------------------------------------- #

_LEVEL = D("98.00")
_TICK = D("0.10")
_GRID_CLOSES = [
    _LEVEL - D("1.00"),
    _LEVEL - _TICK,
    _LEVEL,
    _LEVEL + _TICK,
    _LEVEL + D("1.00"),
    D("102.00") - _TICK,
    D("102.00"),
    D("102.00") + _TICK,
]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("level_text", ["98.00", "102.00", "100.05"])
def test_invalidation_parity_with_backtest_grid(side: str, level_text: str) -> None:
    import src.backtest.entry as backtest_entry

    plan = make_trade_plan(side, invalidation_level=level_text)
    level = pp.plan_invalidation_level(plan)
    assert level == backtest_entry.invalidation_level(plan) == D(level_text)
    for close in [*_GRID_CLOSES, level - _TICK, level, level + _TICK]:
        assert pp.bar_close_invalidates(bar_close_price=close, level=level, side=side) == (
            backtest_entry.is_invalidated(bar_close_price=close, level=level, direction=side)
        )


def test_invalidation_parity_grid_has_enough_triples() -> None:
    assert len(_GRID_CLOSES) * 2 * 3 >= 12


def test_bar_close_invalidates_boundaries() -> None:
    assert not pp.bar_close_invalidates(bar_close_price=_LEVEL, level=_LEVEL, side="LONG")
    assert pp.bar_close_invalidates(bar_close_price=_LEVEL - _TICK, level=_LEVEL, side="LONG")
    assert not pp.bar_close_invalidates(bar_close_price=_LEVEL, level=_LEVEL, side="SHORT")
    assert pp.bar_close_invalidates(bar_close_price=_LEVEL + _TICK, level=_LEVEL, side="SHORT")
    with pytest.raises(ValueError, match="side"):
        pp.bar_close_invalidates(bar_close_price=_LEVEL, level=_LEVEL, side="BUY")


def test_check_invalidation_verdicts() -> None:
    plan = make_trade_plan("LONG", invalidation_level="98.00")

    def run(**over: Any) -> str | None:
        kwargs: dict[str, Any] = {
            "trade_plan": plan,
            "side": "LONG",
            "signal_invalidated": False,
            "latest_closed_bar_close": D("100.00"),
        }
        kwargs.update(over)
        return pp.check_invalidation(**kwargs)

    assert run() is None
    assert run(latest_closed_bar_close=D("98.00")) is None  # at the level is not beyond it
    assert run(latest_closed_bar_close=D("97.90")) == pp.PLAN_INVALIDATED_BEFORE_PLACEMENT
    assert run(signal_invalidated=True) == pp.PLAN_INVALIDATED_BEFORE_PLACEMENT
    assert run(signal_invalidated=True, latest_closed_bar_close=None) == (
        pp.PLAN_INVALIDATED_BEFORE_PLACEMENT
    )
    assert run(latest_closed_bar_close=None) == pp.INVALIDATION_INPUT_UNAVAILABLE
    bad_rules = (
        "not json",
        "[]",
        '{"basis":"WICK","level":"98.00"}',
        '{"basis":"CANDLE_CLOSE"}',
    )
    for bad_rule in bad_rules:
        bad = dataclasses.replace(plan, invalidation_rule_json=bad_rule)
        assert run(trade_plan=bad) == pp.INVALIDATION_INPUT_UNAVAILABLE


def test_invalidation_code_is_distinct_from_the_enum_and_the_enum_is_unchanged() -> None:
    from src.domain.enums import RejectionReason

    assert pp.PLAN_INVALIDATED_BEFORE_PLACEMENT != RejectionReason.INVALIDATED.value
    assert len(RejectionReason) == 20


# --------------------------------------------------------------------------- #
# Remaining validity and the goodTillDate floor
# --------------------------------------------------------------------------- #

_MARGIN = timedelta(seconds=5)


def _validity(
    *, ahead: timedelta, owner_min: int | None, margin: timedelta = _MARGIN
) -> str | None:
    return pp.check_remaining_validity(
        expiry_utc=NOW + ahead,
        now_utc=NOW,
        min_remaining_validity_seconds=owner_min,
        gtd_clock_margin=margin,
    )


def test_gtd_floor_constant_is_the_binance_structural_value() -> None:
    assert pp.GTD_MIN_AHEAD_SECONDS == 600


def test_good_till_date_ms_floors_to_the_second() -> None:
    whole = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC)
    assert pp.good_till_date_ms(whole) == int(whole.timestamp()) * 1000
    assert pp.good_till_date_ms(whole + timedelta(milliseconds=999)) == pp.good_till_date_ms(whole)
    assert pp.good_till_date_ms(whole + timedelta(seconds=1)) == pp.good_till_date_ms(whole) + 1000
    assert pp.good_till_date_ms(whole) % 1000 == 0


def test_validity_unset_owner_minimum_is_not_configured() -> None:
    assert _validity(ahead=timedelta(hours=2), owner_min=None) == pp.LIMITS_NOT_CONFIGURED


def test_validity_floor_is_exclusive_with_a_small_owner_minimum() -> None:
    floor = timedelta(seconds=pp.GTD_MIN_AHEAD_SECONDS) + _MARGIN
    assert _validity(ahead=floor, owner_min=60) == pp.VALIDITY_TOO_SHORT  # exactly at the floor
    assert _validity(ahead=floor - timedelta(seconds=1), owner_min=60) == pp.VALIDITY_TOO_SHORT
    assert _validity(ahead=floor + timedelta(seconds=1), owner_min=60) is None


def test_validity_owner_minimum_binds_when_above_the_floor() -> None:
    assert _validity(ahead=timedelta(seconds=900), owner_min=900) == pp.VALIDITY_TOO_SHORT
    assert _validity(ahead=timedelta(seconds=901), owner_min=900) is None
    assert _validity(ahead=timedelta(seconds=899), owner_min=900) == pp.VALIDITY_TOO_SHORT


def test_validity_uses_the_second_precision_floor_of_a_sub_second_expiry() -> None:
    # 605.9 s ahead floors to 605 s: refused. 606.9 s floors to 606 s: passes.
    assert _validity(ahead=timedelta(seconds=605, milliseconds=900), owner_min=60) == (
        pp.VALIDITY_TOO_SHORT
    )
    assert _validity(ahead=timedelta(seconds=606, milliseconds=900), owner_min=60) is None


def test_validity_zero_margin_and_expired_expiry() -> None:
    assert _validity(ahead=timedelta(seconds=600), owner_min=0, margin=timedelta(0)) == (
        pp.VALIDITY_TOO_SHORT
    )
    assert _validity(ahead=timedelta(seconds=601), owner_min=0, margin=timedelta(0)) is None
    assert _validity(ahead=timedelta(seconds=-5), owner_min=0) == pp.VALIDITY_TOO_SHORT


def test_validity_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="UTC"):
        pp.check_remaining_validity(
            expiry_utc=datetime(2026, 1, 5, 12, 0, 0),
            now_utc=NOW,
            min_remaining_validity_seconds=60,
            gtd_clock_margin=_MARGIN,
        )


# --------------------------------------------------------------------------- #
# Composite order with the Task 2 checks
# --------------------------------------------------------------------------- #


def test_evaluate_status_invalidation_validity_in_order() -> None:
    crossed = {"mark_price": D("98.00")}
    short_expiry = {"expiry_utc": NOW + timedelta(seconds=30)}
    beyond = {"latest_closed_bar_close": D("97.00")}
    expired = {"plan_status": TradePlanStatus.EXPIRED}

    assert evaluate_pre_placement(_inputs(**crossed)) == pp.MARK_PRICE_CROSSED_STOP
    assert evaluate_pre_placement(_inputs(**crossed, **short_expiry)) == pp.VALIDITY_TOO_SHORT
    assert evaluate_pre_placement(_inputs(**crossed, **short_expiry, **beyond)) == (
        pp.PLAN_INVALIDATED_BEFORE_PLACEMENT
    )
    assert evaluate_pre_placement(_inputs(**crossed, **short_expiry, **beyond, **expired)) == (
        pp.PLAN_STATUS_INVALID
    )


def test_evaluate_refuses_unset_owner_minimum_and_missing_bar_close() -> None:
    assert evaluate_pre_placement(_inputs(min_remaining_validity_seconds=None)) == (
        pp.LIMITS_NOT_CONFIGURED
    )
    assert evaluate_pre_placement(_inputs(latest_closed_bar_close=None)) == (
        pp.INVALIDATION_INPUT_UNAVAILABLE
    )
    assert evaluate_pre_placement(_inputs(signal_invalidated=True)) == (
        pp.PLAN_INVALIDATED_BEFORE_PLACEMENT
    )


def test_evaluate_an_executed_approved_plan_is_not_contradicted() -> None:
    assert evaluate_pre_placement(_inputs(plan_status=TradePlanStatus.APPROVED)) is None
    assert evaluate_pre_placement(_inputs(plan_status=TradePlanStatus.READY)) is None
    assert evaluate_pre_placement(_inputs(plan_status=TradePlanStatus.APPROVAL_PENDING)) is None
