"""Pure pre-placement refusals (Phase 19, plan 19-03; D-05..D-09, D-14, RISK-04).

Hand oracles (tick 0.10, LONG zone 99.50-100.60, stop 98.00; SHORT zone 99.50-100.60, stop 102.00):

    LONG : mark 98.00 is AT the stop (crossed); mark 99.40 is one tick below the zone (outside);
           99.50 and 100.60 are the inclusive zone edges (pass); 100.70 is above the zone.
    SHORT: mark 102.00 is AT the stop (crossed); 100.70 is one tick above the zone (outside);
           99.50 and 100.60 pass; 99.40 is below the zone.
    Mark age is measured against `max_mark_price_age_ms`; an equal age passes, a future reading
    (negative age) and an unset bound refuse as MARK_PRICE_UNAVAILABLE.
    19-REVIEW CR-01: the age is taken at `mark_checked_at_utc` (a clock read AFTER the mark read),
    not at `now_utc`; a reading stamped up to `gtd_clock_margin` ahead of it is age zero.
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import src.execution.pre_placement as pp
from src.domain.enums import TradePlanStatus
from src.execution.pre_placement import PrePlacementInputs, check_mark_price, evaluate_pre_placement

from tests.backtest_plan_helpers import make_trade_plan
from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)

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
        "max_clock_skew": timedelta(0),
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
        "mark_checked_at_utc": NOW,
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
@pytest.mark.parametrize(
    "missing", ["mark_price", "mark_time_utc", "now_utc", "max_mark_price_age_ms"]
)
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
    with pytest.raises(ValueError, match="max_clock_skew"):
        check_mark_price(**_mark_kwargs("LONG", max_clock_skew=timedelta(milliseconds=-1)))


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_check_mark_price_tolerates_only_the_bounded_clock_skew(side: str) -> None:
    """19-REVIEW CR-01: Binance may stamp the reading up to `max_clock_skew` ahead of the check."""
    skew = timedelta(milliseconds=876)
    ahead_within = _mark_kwargs(side, mark_time_utc=NOW + skew, max_clock_skew=skew)
    assert check_mark_price(**ahead_within) is None
    ahead_beyond = _mark_kwargs(
        side, mark_time_utc=NOW + skew + timedelta(milliseconds=1), max_clock_skew=skew
    )
    assert check_mark_price(**ahead_beyond) == pp.MARK_PRICE_UNAVAILABLE
    # The tolerance never relaxes the staleness bound.
    too_old = _mark_kwargs(
        side, mark_time_utc=NOW - timedelta(milliseconds=MAX_AGE_MS + 1), max_clock_skew=skew
    )
    assert check_mark_price(**too_old) == pp.MARK_PRICE_UNAVAILABLE


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


def test_evaluate_mark_age_a_reading_taken_after_now_utc_is_fresh() -> None:
    """19-REVIEW CR-01: the read happens after `now_utc`, so its exchange time is later.

    Old code measured `now_utc - mark_time_utc` (negative here) and refused a fresh reading.
    The age is now measured at the post-read clock instant, with no clock skew involved
    (the reading is stamped BEFORE the check instant).
    """
    for side in ("LONG", "SHORT"):
        fresh_after_now = _inputs(
            side,
            gtd_clock_margin=timedelta(0),
            mark_time_utc=NOW + timedelta(milliseconds=300),
            mark_checked_at_utc=NOW + timedelta(milliseconds=500),
        )
        assert evaluate_pre_placement(fresh_after_now) is None


def test_evaluate_mark_age_staleness_is_measured_at_the_check_instant() -> None:
    """A reading fresh relative to the pre-read `now_utc` but stale at the check refuses."""
    stale_at_check = _inputs(
        mark_time_utc=NOW,
        mark_checked_at_utc=NOW + timedelta(milliseconds=MAX_AGE_MS + 1),
    )
    assert evaluate_pre_placement(stale_at_check) == pp.MARK_PRICE_UNAVAILABLE
    # An unreadable check instant is "not available" (fail closed).
    assert evaluate_pre_placement(_inputs(mark_checked_at_utc=None)) == pp.MARK_PRICE_UNAVAILABLE
    # A reading clearly ahead of the check instant (beyond the drift margin) refuses.
    future = _inputs(
        gtd_clock_margin=timedelta(seconds=5),
        mark_time_utc=NOW + timedelta(seconds=5, milliseconds=1),
        mark_checked_at_utc=NOW,
    )
    assert evaluate_pre_placement(future) == pp.MARK_PRICE_UNAVAILABLE
    with pytest.raises(ValueError, match="UTC"):
        _inputs(mark_checked_at_utc=datetime(2026, 1, 5, 10, 0, 0))


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


# --------------------------------------------------------------------------- #
# check_symbol_free (D-05, D-11)
# --------------------------------------------------------------------------- #


def _free(**over: Any) -> str | None:
    kwargs: dict[str, Any] = {
        "symbol": SYMBOL,
        "position_symbols": frozenset({"ETHUSDT"}),
        "open_order_symbols": frozenset({"ETHUSDT"}),
        "any_unprotected": False,
    }
    kwargs.update(over)
    return pp.check_symbol_free(**kwargs)


def test_check_symbol_free_verdicts() -> None:
    assert _free() is None
    assert _free(position_symbols=frozenset(), open_order_symbols=frozenset()) is None
    assert _free(position_symbols=frozenset({SYMBOL})) == pp.SYMBOL_HAS_POSITION
    assert _free(open_order_symbols=frozenset({SYMBOL, "ETHUSDT"})) == pp.SYMBOL_HAS_OPEN_ORDER
    assert _free(open_order_symbols=None) == pp.SYMBOL_STATE_UNAVAILABLE
    assert _free(any_unprotected=True) == pp.UNPROTECTED_POSITION_EXISTS


def test_check_symbol_free_precedence() -> None:
    # Unprotected (account-wide) first, then a position, then unreadable orders, then an order.
    both = {"position_symbols": frozenset({SYMBOL}), "open_order_symbols": frozenset({SYMBOL})}
    assert _free(any_unprotected=True, **both) == pp.UNPROTECTED_POSITION_EXISTS
    assert _free(**both) == pp.SYMBOL_HAS_POSITION
    assert _free(position_symbols=frozenset({SYMBOL}), open_order_symbols=None) == (
        pp.SYMBOL_HAS_POSITION
    )
    assert _free(open_order_symbols=frozenset({SYMBOL})) == pp.SYMBOL_HAS_OPEN_ORDER


def test_check_symbol_free_other_symbols_do_not_block() -> None:
    others = frozenset({"ETHUSDT", "SOLUSDT"})
    assert _free(position_symbols=others, open_order_symbols=others) is None


# --------------------------------------------------------------------------- #
# check_position_mode (D-14)
# --------------------------------------------------------------------------- #


def test_check_position_mode() -> None:
    assert pp.check_position_mode("HEDGE") == pp.HEDGE_MODE_UNSUPPORTED
    assert pp.check_position_mode("ONE_WAY") is None
    for bad in ("hedge", "", "BOTH", "UNKNOWN"):
        with pytest.raises(ValueError, match="position mode"):
            pp.check_position_mode(bad)


def test_position_mode_constants_match_the_manager() -> None:
    from src.execution.manager import POSITION_MODE_HEDGE, POSITION_MODE_ONE_WAY

    assert pp.check_position_mode(POSITION_MODE_HEDGE) == pp.HEDGE_MODE_UNSUPPORTED
    assert pp.check_position_mode(POSITION_MODE_ONE_WAY) is None


# --------------------------------------------------------------------------- #
# Composite: each of the five checks fails in turn, and the order is pinned
# --------------------------------------------------------------------------- #

_FAILING_CASES: list[tuple[str, dict[str, Any]]] = [
    (pp.PLAN_STATUS_INVALID, {"plan_status": TradePlanStatus.SUPERSEDED}),
    (pp.PLAN_INVALIDATED_BEFORE_PLACEMENT, {"latest_closed_bar_close": D("97.00")}),
    (pp.VALIDITY_TOO_SHORT, {"expiry_utc": NOW + timedelta(seconds=30)}),
    (pp.SYMBOL_HAS_POSITION, {"position_symbols": frozenset({SYMBOL})}),
    (pp.MARK_PRICE_CROSSED_STOP, {"mark_price": D("98.00")}),
]


@pytest.mark.parametrize(("expected", "override"), _FAILING_CASES)
def test_evaluate_each_check_fails_in_turn(expected: str, override: dict[str, Any]) -> None:
    assert evaluate_pre_placement(_inputs(**override)) == expected


def test_evaluate_first_failure_wins_over_every_later_check() -> None:
    for index, (expected, _) in enumerate(_FAILING_CASES):
        merged: dict[str, Any] = {}
        for _, override in _FAILING_CASES[index:]:
            merged.update(override)
        assert evaluate_pre_placement(_inputs(**merged)) == expected


def test_evaluate_symbol_free_reasons_flow_through() -> None:
    assert evaluate_pre_placement(_inputs(open_order_symbols=None)) == pp.SYMBOL_STATE_UNAVAILABLE
    assert evaluate_pre_placement(_inputs(open_order_symbols=frozenset({SYMBOL}))) == (
        pp.SYMBOL_HAS_OPEN_ORDER
    )
    assert evaluate_pre_placement(_inputs(any_unprotected=True)) == pp.UNPROTECTED_POSITION_EXISTS


# --------------------------------------------------------------------------- #
# RISK-04 and purity guards
# --------------------------------------------------------------------------- #

_FORBIDDEN_NAME_PARTS = ("loss", "pnl", "target", "drawdown", "streak")
_SOURCE = Path(pp.__file__)


def _public_functions() -> list[Any]:
    return [
        obj
        for name, obj in vars(pp).items()
        if inspect.isfunction(obj) and not name.startswith("_") and obj.__module__ == pp.__name__
    ]


def test_risk04_no_input_describes_prior_results() -> None:
    names: list[str] = [f.name for f in dataclasses.fields(PrePlacementInputs)]
    functions = _public_functions()
    assert len(functions) >= 10
    for function in functions:
        names.extend(inspect.signature(function).parameters)
    for name in names:
        assert not any(part in name.lower() for part in _FORBIDDEN_NAME_PARTS), name


def test_purity_imports_float_and_clock() -> None:
    allowed = {
        "__future__",
        "json",
        "dataclasses",
        "datetime",
        "decimal",
        "src.domain.enums",
        "src.domain.trade_plan",
    }
    assert set(module_imports(_SOURCE)) <= allowed
    assert forbidden_imports(_SOURCE, ["src.backtest", "src.adapters", "src.persistence"]) == []
    assert float_constructor_calls(_SOURCE) == []
    assert wall_clock_calls(_SOURCE) == []
