"""Tests for the corrected cost pipeline in the shared risk step (Phase 12, plan 12-06).

`evaluate_risk` / `size_and_quantize` compute the modeled cost per unit
themselves from a `CostRates` object (D-02), size at the ADVERSE edge of the
entry zone (D-03), and apply two cost guards before quantization (D-07):
STOP_TOO_TIGHT then COST_TO_RISK_EXCEEDED.

Every expected number below is a hand-derived literal (standalone Decimal
script, independent of project code). Rates: fee_in 0.0005, slip_in 0.0001,
fee_out 0.0005, slip_out 0.0003; equity 10000, risk_rate 0.005 so
allowed_risk = 50; guards 0.003 and 0.15.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import structlog
from src.core.types import AccountState
from src.domain.enums import TradePlanStatus
from src.domain.trade_plan import TradePlan
from src.risk import (
    ConstraintSnapshot,
    CostRates,
    PortfolioVerdict,
    SizedResult,
    check_portfolio,
    evaluate_risk,
    size_and_quantize,
)
from src.risk.cost_guards import check_cost_guards, validate_guard_rates

FROZEN_NOW = datetime(2026, 9, 19, tzinfo=UTC)
TTL = timedelta(seconds=3600)

PARAMETERS: dict[str, Any] = {
    "max_open_positions": 2,
    "max_aggregate_open_risk": Decimal("100"),
    "cluster_cap": Decimal("50"),
    "daily_loss_warning_threshold": Decimal("50"),
    "daily_loss_stop_threshold": Decimal("100"),
}

MIN_STOP = Decimal("0.003")
MAX_RATIO = Decimal("0.15")
MIN_UTIL = Decimal("0.6")
ALLOWED_RISK = Decimal("50")

FEE_IN = Decimal("0.0005")
SLIP_IN = Decimal("0.0001")
FEE_OUT = Decimal("0.0005")
SLIP_OUT = Decimal("0.0003")


def _rates() -> CostRates:
    return CostRates(
        fee_rate_entry=FEE_IN,
        entry_slippage_rate=SLIP_IN,
        fee_rate_exit=FEE_OUT,
        exit_slippage_rate=SLIP_OUT,
        fee_source="PARAMETER",
    )


def _plan(*, entry_min: str, entry_max: str, stop: str, symbol: str = "BTCUSDT") -> TradePlan:
    return TradePlan(
        trade_plan_id="1" * 64,
        signal_id="2" * 64,
        trade_plan_version="v1",
        entry_model="LIMIT_ZONE",
        entry_min_price=Decimal(entry_min),
        entry_max_price=Decimal(entry_max),
        stop_loss_price=Decimal(stop),
        take_profit_json='{"tp1":"52000.00","tp1_role":"TAKE_PROFIT_1"}',
        invalidation_rule_json='{"basis":"CANDLE_CLOSE","level":"1","break_distance_atr":"1"}',
        expiry_utc=datetime(2026, 9, 19, 4, tzinfo=UTC),
        expected_rr_json='{"tp1_rr":"2.0"}',
        risk_rate=Decimal("0.005"),
        risk_budget=Decimal("50.00000"),
        suggested_quantity=Decimal("0.04"),
        quantity_before_rounding=Decimal("0.04"),
        quantity_after_rounding=Decimal("0.04"),
        quantization_decision="DEFERRED_TO_RISK",
        plan_hash="3" * 64,
        status=TradePlanStatus.READY,
        created_at_utc=datetime(2026, 9, 19, tzinfo=UTC),
    )


def _account(equity: str = "10000") -> AccountState:
    return AccountState(equity=Decimal(equity), risk_rate=Decimal("0.005"))


def _btc_constraints(*, min_notional: str = "50") -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol="BTCUSDT",
        price_tick_size=Decimal("0.10"),
        quantity_step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal(min_notional),
        metadata_observed_at_utc=FROZEN_NOW,
    )


def _xrp_constraints() -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol="XRPUSDT",
        price_tick_size=Decimal("0.0001"),
        quantity_step_size=Decimal("0.1"),
        min_quantity=Decimal("0.1"),
        min_notional=Decimal("5"),
        metadata_observed_at_utc=FROZEN_NOW,
    )


def _btc_long(
    *, stop: str = "58780", entry_min: str = "59900", entry_max: str = "60100"
) -> TradePlan:
    return _plan(entry_min=entry_min, entry_max=entry_max, stop=stop)


def _btc_short(*, stop: str = "61300") -> TradePlan:
    return _plan(entry_min="59900", entry_max="60100", stop=stop)


def _xrp_long() -> TradePlan:
    return _plan(entry_min="0.4990", entry_max="0.5010", stop="0.4930", symbol="XRPUSDT")


def _size(
    plan: TradePlan,
    side: str,
    constraints: ConstraintSnapshot,
    *,
    account: AccountState | None = None,
    min_stop: Decimal = MIN_STOP,
    max_ratio: Decimal = MAX_RATIO,
    cost_rates: Any = None,
) -> SizedResult:
    return size_and_quantize(
        trade_plan=plan,
        candidate_position_side=side,
        account_state=account or _account(),
        constraint_snapshot=constraints,
        cost_rates=cost_rates if cost_rates is not None else _rates(),
        min_stop_distance_rate=min_stop,
        max_cost_to_risk=max_ratio,
        minimum_risk_utilization_after_rounding=MIN_UTIL,
    )


def _evaluate(
    plan: TradePlan,
    side: str,
    constraints: ConstraintSnapshot,
    *,
    account: AccountState | None = None,
    min_stop: Decimal = MIN_STOP,
    max_ratio: Decimal = MAX_RATIO,
) -> PortfolioVerdict:
    return evaluate_risk(
        trade_plan=plan,
        candidate_position_side=side,
        account_state=account or _account(),
        constraint_snapshot=constraints,
        open_positions=[],
        daily_loss_quote=Decimal("0"),
        now_utc=FROZEN_NOW,
        ttl=TTL,
        cost_rates=_rates(),
        min_stop_distance_rate=min_stop,
        max_cost_to_risk=max_ratio,
        minimum_risk_utilization_after_rounding=MIN_UTIL,
        parameter_set=PARAMETERS,
    )


# --------------------------------------------------------------------------- #
# Oracle: adverse-edge sizing with the price-aware cost (D-02, D-03)
# --------------------------------------------------------------------------- #


def test_btc_long_oracle() -> None:
    sized = _size(_btc_long(), "LONG", _btc_constraints())
    assert sized.is_no_trade is False
    assert sized.quantity == Decimal("0.035")
    assert sized.quantity_before_rounding == Decimal("0.03563578517038181605662953893")
    assert sized.realized_risk == Decimal("49.1079400")
    assert sized.modeled_costs_per_unit == Decimal("83.0840")
    assert sized.sizing_entry_price == Decimal("60100")
    assert sized.stop_distance_rate == Decimal("0.02196339434276206322795341098")
    assert sized.cost_to_risk_ratio == Decimal("0.05921527150192005610498017225")
    assert sized.fee_rate_entry == Decimal("0.0005")
    assert sized.fee_rate_exit == Decimal("0.0005")
    assert sized.fee_source == "PARAMETER"


def test_btc_short_oracle() -> None:
    sized = _size(_btc_short(), "SHORT", _btc_constraints())
    assert sized.is_no_trade is False
    assert sized.quantity == Decimal("0.033")
    assert sized.realized_risk == Decimal("49.0043400")
    assert sized.modeled_costs_per_unit == Decimal("84.9800")
    assert sized.sizing_entry_price == Decimal("59900")
    assert sized.stop_distance_rate == Decimal("0.02337228714524207011686143573")
    assert sized.cost_to_risk_ratio == Decimal("0.05722635995097577071745074008")
    assert sized.fee_source == "PARAMETER"


def test_xrp_long_oracle() -> None:
    sized = _size(_xrp_long(), "LONG", _xrp_constraints())
    assert sized.is_no_trade is False
    assert sized.quantity == Decimal("5750.4")
    assert sized.realized_risk == Decimal("49.999728000")
    assert sized.modeled_costs_per_unit == Decimal("0.00069500")
    assert sized.sizing_entry_price == Decimal("0.5010")
    assert sized.stop_distance_rate == Decimal("0.01596806387225548902195608782")
    assert sized.cost_to_risk_ratio == Decimal("0.07993099482461184588844163312")


def test_evaluate_risk_equals_check_portfolio_of_size_and_quantize() -> None:
    plan = _btc_long()
    constraints = _btc_constraints()
    sized = _size(plan, "LONG", constraints)
    expected = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=[],
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=TTL,
        positions_reconciled=True,
        constraint_observed_at_utc=constraints.metadata_observed_at_utc,
    )
    verdict = _evaluate(plan, "LONG", constraints)
    assert verdict == expected
    assert verdict.is_no_trade is False
    assert verdict.sized is not None
    assert verdict.sized.quantity == Decimal("0.035")


# --------------------------------------------------------------------------- #
# Worst case: loss at the stop is at most allowed_risk for a fill anywhere in
# the zone (D-03). The loss is plain Decimal arithmetic with literal rates.
# --------------------------------------------------------------------------- #

_C_ENTRY = FEE_IN + SLIP_IN  # 0.0006
_C_EXIT = FEE_OUT + SLIP_OUT  # 0.0008


def _long_loss(quantity: Decimal, fill: Decimal, stop: Decimal) -> Decimal:
    return quantity * (fill * (1 + _C_ENTRY) - stop * (1 - _C_EXIT))


def _short_loss(quantity: Decimal, fill: Decimal, stop: Decimal) -> Decimal:
    return quantity * (stop * (1 + _C_EXIT) - fill * (1 - _C_ENTRY))


@pytest.mark.parametrize("fraction", [Decimal("0"), Decimal("0.5"), Decimal("1")])
def test_worst_case_loss_at_stop_within_budget(fraction: Decimal) -> None:
    lo, hi = Decimal("59900"), Decimal("60100")
    fill = lo + (hi - lo) * fraction

    long_sized = _size(_btc_long(), "LONG", _btc_constraints())
    assert long_sized.quantity is not None
    assert _long_loss(long_sized.quantity, fill, Decimal("58780")) <= ALLOWED_RISK

    short_sized = _size(_btc_short(), "SHORT", _btc_constraints())
    assert short_sized.quantity is not None
    assert _short_loss(short_sized.quantity, fill, Decimal("61300")) <= ALLOWED_RISK

    xlo, xhi = Decimal("0.4990"), Decimal("0.5010")
    xfill = xlo + (xhi - xlo) * fraction
    xrp = _size(_xrp_long(), "LONG", _xrp_constraints())
    assert xrp.quantity is not None
    assert _long_loss(xrp.quantity, xfill, Decimal("0.4930")) <= ALLOWED_RISK


def test_edge_fill_loss_equals_quantity_times_risk_per_unit() -> None:
    sized = _size(_btc_long(), "LONG", _btc_constraints())
    assert sized.quantity is not None
    loss = _long_loss(sized.quantity, Decimal("60100"), Decimal("58780"))
    assert loss == Decimal("49.1079400")
    assert loss == sized.realized_risk


def test_zone_mid_sizing_counterfactual_exceeds_budget() -> None:
    """Why D-03 exists: mid sizing gives 0.038, which loses more than 50 at the edge."""
    mid_quantity = Decimal("0.038")
    loss = _long_loss(mid_quantity, Decimal("60100"), Decimal("58780"))
    assert loss == Decimal("53.3171920")
    assert loss > ALLOWED_RISK


# --------------------------------------------------------------------------- #
# Notional reference stays the zone mid (the price the order is placed at)
# --------------------------------------------------------------------------- #


def test_notional_reference_is_zone_mid_long_rejects() -> None:
    # quantity 0.035: mid notional 2100 < 2102 (reject); an edge reference 2103.5 would pass.
    sized = _size(_btc_long(), "LONG", _btc_constraints(min_notional="2102"))
    assert sized.is_no_trade is True
    assert sized.reason_code == "NOTIONAL_REJECT"


def test_notional_reference_is_zone_mid_short_passes() -> None:
    # quantity 0.033: mid notional 1980 >= 1978 (pass); the edge 1976.7 would have rejected.
    sized = _size(_btc_short(), "SHORT", _btc_constraints(min_notional="1978"))
    assert sized.is_no_trade is False
    assert sized.quantity == Decimal("0.033")


# --------------------------------------------------------------------------- #
# Fail-closed typing of the new contract (T-12-14, T-12-15)
# --------------------------------------------------------------------------- #


def _base_kwargs() -> dict[str, Any]:
    return {
        "trade_plan": _btc_long(),
        "candidate_position_side": "LONG",
        "account_state": _account(),
        "constraint_snapshot": _btc_constraints(),
        "cost_rates": _rates(),
        "min_stop_distance_rate": MIN_STOP,
        "max_cost_to_risk": MAX_RATIO,
        "minimum_risk_utilization_after_rounding": MIN_UTIL,
    }


def test_removed_modeled_costs_keyword_raises_type_error() -> None:
    kwargs = _base_kwargs()
    with pytest.raises(TypeError):
        size_and_quantize(**kwargs, modeled_costs_per_unit=Decimal("1"))
    with pytest.raises(TypeError):
        evaluate_risk(
            **kwargs,
            open_positions=[],
            daily_loss_quote=Decimal("0"),
            now_utc=FROZEN_NOW,
            ttl=TTL,
            parameter_set=PARAMETERS,
            modeled_costs_per_unit=Decimal("1"),
        )


@pytest.mark.parametrize("missing", ["cost_rates", "min_stop_distance_rate", "max_cost_to_risk"])
def test_omitted_required_keyword_raises_type_error(missing: str) -> None:
    kwargs = _base_kwargs()
    del kwargs[missing]
    with pytest.raises(TypeError):
        size_and_quantize(**kwargs)


def test_signature_has_no_defaults_for_new_keywords() -> None:
    for fn in (size_and_quantize, evaluate_risk):
        params = inspect.signature(fn).parameters
        assert "modeled_costs_per_unit" not in params
        for name in ("cost_rates", "min_stop_distance_rate", "max_cost_to_risk"):
            assert params[name].default is inspect.Parameter.empty


@pytest.mark.parametrize("bad", [{"a": 1}, "x", None, 0.0005, Decimal("0.0005")])
def test_cost_rates_must_be_cost_rates(bad: Any) -> None:
    kwargs = _base_kwargs()
    kwargs["cost_rates"] = bad
    with pytest.raises(TypeError):
        size_and_quantize(**kwargs)


@pytest.mark.parametrize("bad", [0.003, "0.003", 1, True, None])
@pytest.mark.parametrize("field", ["min_stop_distance_rate", "max_cost_to_risk"])
def test_guard_rate_must_be_decimal(field: str, bad: Any) -> None:
    kwargs = _base_kwargs()
    kwargs[field] = bad
    with pytest.raises(TypeError):
        size_and_quantize(**kwargs)
    other = "max_cost_to_risk" if field == "min_stop_distance_rate" else "min_stop_distance_rate"
    args = {field: bad, other: Decimal("0.5")}
    with pytest.raises(TypeError):
        validate_guard_rates(**args)


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-0.1"), Decimal("1"), Decimal("1.5")])
def test_min_stop_distance_rate_range(bad: Decimal) -> None:
    kwargs = _base_kwargs()
    kwargs["min_stop_distance_rate"] = bad
    with pytest.raises(ValueError):
        size_and_quantize(**kwargs)


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-0.1"), Decimal("1.0001")])
def test_max_cost_to_risk_range(bad: Decimal) -> None:
    kwargs = _base_kwargs()
    kwargs["max_cost_to_risk"] = bad
    with pytest.raises(ValueError):
        size_and_quantize(**kwargs)


def test_max_cost_to_risk_of_exactly_one_is_valid() -> None:
    validate_guard_rates(min_stop_distance_rate=Decimal("0.003"), max_cost_to_risk=Decimal("1"))


@pytest.mark.parametrize("bad_side", ["BOTH", "long", "", "BUY"])
def test_invalid_side_raises_value_error(bad_side: str) -> None:
    with pytest.raises(ValueError):
        _size(_btc_long(), bad_side, _btc_constraints())


def test_zero_stop_distance_is_exchange_constraint() -> None:
    plan = _btc_long(stop="60100")
    sized = _size(plan, "LONG", _btc_constraints())
    assert sized.is_no_trade is True
    assert sized.reason_code == "EXCHANGE_CONSTRAINT"


# --------------------------------------------------------------------------- #
# Lineage (D-12)
# --------------------------------------------------------------------------- #


def test_cost_rates_lineage_event_emitted_once_with_string_values() -> None:
    with structlog.testing.capture_logs() as logs:
        _size(_btc_long(), "LONG", _btc_constraints())
    events = [e for e in logs if e.get("event") == "risk.cost_rates"]
    assert len(events) == 1
    ev = events[0]
    assert ev["fee_rate_entry"] == "0.0005"
    assert ev["fee_rate_exit"] == "0.0005"
    assert ev["fee_source"] == "PARAMETER"
    assert ev["modeled_costs_per_unit"] == "83.0840"
    assert ev["sizing_entry_price"] == "60100"
    assert ev["stop_distance_rate"] == "0.02196339434276206322795341098"
    assert ev["cost_to_risk_ratio"] == "0.05921527150192005610498017225"
    for key in (
        "fee_rate_entry",
        "fee_rate_exit",
        "fee_source",
        "modeled_costs_per_unit",
        "sizing_entry_price",
        "stop_distance_rate",
        "cost_to_risk_ratio",
    ):
        assert isinstance(ev[key], str)


def test_quantize_reject_carries_cost_trail() -> None:
    sized = _size(_btc_long(), "LONG", _btc_constraints(min_notional="2102"))
    assert sized.reason_code == "NOTIONAL_REJECT"
    assert sized.modeled_costs_per_unit == Decimal("83.0840")
    assert sized.fee_source == "PARAMETER"


# --------------------------------------------------------------------------- #
# Cost guards (D-07): STOP_TOO_TIGHT then COST_TO_RISK_EXCEEDED, before quantize
# --------------------------------------------------------------------------- #

TIGHT = Decimal("0.0000001")


def test_check_cost_guards_pure_function() -> None:
    assert (
        check_cost_guards(
            stop_distance_rate=Decimal("0.01"),
            cost_to_risk_ratio=Decimal("0.1"),
            min_stop_distance_rate=Decimal("0.003"),
            max_cost_to_risk=Decimal("0.15"),
        )
        is None
    )
    assert (
        check_cost_guards(
            stop_distance_rate=Decimal("0.002"),
            cost_to_risk_ratio=Decimal("0.1"),
            min_stop_distance_rate=Decimal("0.003"),
            max_cost_to_risk=Decimal("0.15"),
        )
        == "STOP_TOO_TIGHT"
    )
    assert (
        check_cost_guards(
            stop_distance_rate=Decimal("0.01"),
            cost_to_risk_ratio=Decimal("0.2"),
            min_stop_distance_rate=Decimal("0.003"),
            max_cost_to_risk=Decimal("0.15"),
        )
        == "COST_TO_RISK_EXCEEDED"
    )
    # Stop check is first when both fail.
    assert (
        check_cost_guards(
            stop_distance_rate=Decimal("0.001"),
            cost_to_risk_ratio=Decimal("0.9"),
            min_stop_distance_rate=Decimal("0.003"),
            max_cost_to_risk=Decimal("0.15"),
        )
        == "STOP_TOO_TIGHT"
    )


def test_stop_distance_boundary_equality_passes() -> None:
    # LONG zone 49900-50000, stop 49850 -> 150 / 50000 = 0.003 exactly.
    plan = _plan(entry_min="49900", entry_max="50000", stop="49850")
    sized = _size(
        plan, "LONG", _btc_constraints(), min_stop=Decimal("0.003"), max_ratio=Decimal("1")
    )
    assert sized.stop_distance_rate == Decimal("0.003")
    assert sized.reason_code != "STOP_TOO_TIGHT"


def test_stop_distance_boundary_just_below_rejects() -> None:
    plan = _plan(entry_min="49900", entry_max="50000", stop="49850")
    sized = _size(
        plan, "LONG", _btc_constraints(), min_stop=Decimal("0.0031"), max_ratio=Decimal("1")
    )
    assert sized.is_no_trade is True
    assert sized.reason_code == "STOP_TOO_TIGHT"


def test_cost_to_risk_boundary_equality_passes() -> None:
    sized = _size(
        _btc_long(),
        "LONG",
        _btc_constraints(),
        min_stop=TIGHT,
        max_ratio=Decimal("0.05921527150192005610498017225"),
    )
    assert sized.is_no_trade is False
    assert sized.quantity == Decimal("0.035")


def test_cost_to_risk_boundary_one_ulp_below_rejects() -> None:
    sized = _size(
        _btc_long(),
        "LONG",
        _btc_constraints(),
        min_stop=TIGHT,
        max_ratio=Decimal("0.05921527150192005610498017224"),
    )
    assert sized.is_no_trade is True
    assert sized.reason_code == "COST_TO_RISK_EXCEEDED"


def test_half_percent_stop_passes_stop_guard_but_fails_cost_ratio() -> None:
    plan = _btc_long(stop="59800")
    sized = _size(plan, "LONG", _btc_constraints())
    assert sized.is_no_trade is True
    assert sized.reason_code == "COST_TO_RISK_EXCEEDED"
    assert sized.modeled_costs_per_unit == Decimal("83.9000")
    assert sized.stop_distance_rate == Decimal("0.004991680532445923460898502496")
    assert sized.cost_to_risk_ratio == Decimal("0.2185464964834592341755665538")


def test_both_guards_violated_reports_stop_too_tight() -> None:
    plan = _btc_long(stop="59980")
    sized = _size(plan, "LONG", _btc_constraints())
    assert sized.is_no_trade is True
    assert sized.reason_code == "STOP_TOO_TIGHT"
    assert sized.stop_distance_rate is not None and sized.stop_distance_rate < Decimal("0.003")
    assert sized.cost_to_risk_ratio is not None and sized.cost_to_risk_ratio > Decimal("0.15")


def test_guards_run_before_quantize() -> None:
    # Tiny equity would be MIN_QTY_REJECT after rounding; the guard reason wins.
    plan = _btc_long(stop="59980")
    sized = _size(plan, "LONG", _btc_constraints(), account=_account(equity="1"))
    assert sized.reason_code == "STOP_TOO_TIGHT"
    # A plan that passes the guards with tiny equity does reach quantize.
    ok_plan = _btc_long()
    quantized = _size(ok_plan, "LONG", _btc_constraints(), account=_account(equity="1"))
    assert quantized.reason_code == "MIN_QTY_REJECT"


def test_guard_reject_shape() -> None:
    plan = _btc_long(stop="59800")
    sized = _size(plan, "LONG", _btc_constraints())
    assert sized.is_no_trade is True
    assert sized.quantity is None
    assert sized.quantization_decision == "REJECTED"
    assert sized.quantity_after_rounding == Decimal("0")
    assert sized.realized_risk == Decimal("0")
    assert sized.quantity_before_rounding > Decimal("0")
    assert sized.fee_source == "PARAMETER"
    assert sized.sizing_entry_price == Decimal("60100")


def test_guard_reject_verdict_shape() -> None:
    verdict = _evaluate(_btc_long(stop="59800"), "LONG", _btc_constraints())
    assert verdict.is_no_trade is True
    assert verdict.sized is None
    assert verdict.reason_code == "COST_TO_RISK_EXCEEDED"
    stop_verdict = _evaluate(_btc_long(stop="59980"), "LONG", _btc_constraints())
    assert stop_verdict.reason_code == "STOP_TOO_TIGHT"


def test_guard_reject_lineage_event() -> None:
    with structlog.testing.capture_logs() as logs:
        _size(_btc_long(stop="59800"), "LONG", _btc_constraints())
    events = [e for e in logs if e.get("event") == "risk.cost_guard"]
    assert len(events) == 1
    ev = events[0]
    assert ev["reason_code"] == "COST_TO_RISK_EXCEEDED"
    assert ev["stop_distance_rate"] == "0.004991680532445923460898502496"
    assert ev["cost_to_risk_ratio"] == "0.2185464964834592341755665538"
    for key in ("reason_code", "stop_distance_rate", "cost_to_risk_ratio"):
        assert isinstance(ev[key], str)
    # No guard event on an accepted plan.
    with structlog.testing.capture_logs() as ok_logs:
        _size(_btc_long(), "LONG", _btc_constraints())
    assert not [e for e in ok_logs if e.get("event") == "risk.cost_guard"]
