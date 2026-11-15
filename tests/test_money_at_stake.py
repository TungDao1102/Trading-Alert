"""Money block built once from the risk pipeline output (Phase 23, plan 23-02, D-13, F-015).

Every expected value is recomputed here with plain Decimal arithmetic written in the test, not
with the module's helpers, so a wrong formula in the module cannot hide behind itself.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates
from src.risk.money_at_stake import (
    EQUITY_SOURCE_ACCOUNT_LIVE,
    LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT,
    MONEY_AT_STAKE_MISSING,
    MONEY_SCHEMA_TAG,
    MoneyAtStake,
    MoneyAtStakeUnavailable,
    build_money_at_stake,
    money_canonical_json,
    parse_money_json,
)
from src.risk.types import SizedResult

from tests.support.ast_guards import float_constructor_calls, forbidden_imports, wall_clock_calls

D = Decimal
OBSERVED = datetime(2026, 10, 9, 3, 0, 0, tzinfo=UTC)

# Rates of the fixtures: fee 0.0005 each way, slippage 0.0002 each way -> 0.0007 per leg.
RATES = CostRates(
    fee_rate_entry=D("0.0005"),
    entry_slippage_rate=D("0.0002"),
    fee_rate_exit=D("0.0005"),
    exit_slippage_rate=D("0.0002"),
    fee_source=FEE_SOURCE_PARAMETER,
)
LEG_RATE = D("0.0007")


def _sized_long() -> SizedResult:
    # entry 50100 (adverse edge), SL 49500: risk per unit = 600 + (50100 + 49500) x 0.0007
    return SizedResult(
        is_no_trade=False,
        quantity=D("0.08"),
        quantity_before_rounding=D("0.0803"),
        quantity_after_rounding=D("0.08"),
        quantization_decision="ACCEPTED",
        realized_risk=D("53.5776"),
        modeled_costs_per_unit=D("69.72"),
        sizing_entry_price=D("50100"),
    )


def _build_long() -> MoneyAtStake:
    return build_money_at_stake(
        side="LONG",
        sized=_sized_long(),
        stop_loss_price=D("49500"),
        take_profits=[(D("51000"), D("0.5")), (D("52000"), D("0.5"))],
        cost_rates=RATES,
        leverage=5,
        leverage_source=LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT,
        equity=D("800"),
        equity_source=EQUITY_SOURCE_ACCOUNT_LIVE,
        equity_observed_at_utc=OBSERVED,
    )


def test_long_plan_money_is_recomputed_independently() -> None:
    money = _build_long()
    sized = _sized_long()

    assert money.schema == "money-at-stake/1" == MONEY_SCHEMA_TAG
    assert money.quote_asset == "USDT"
    assert money.side == "LONG"
    assert money.quantity == D("0.08")
    assert money.entry_price == D("50100")
    assert money.stop_loss_price == D("49500")

    # 0.08 x 50100 = 4008.00 ; 4008 / 5 = 801.6
    assert money.notional == D("4008.00")
    assert money.leverage == 5
    assert money.initial_margin == D("801.6")

    # gross 0.08 x |50100 - 49500| = 48.00 ; net is the pipeline's own realized_risk
    assert money.loss_at_stop_gross == D("48.00")
    assert money.loss_at_stop_net == D("53.5776")
    assert money.loss_at_stop_net == sized.realized_risk

    tp1, tp2 = money.take_profits
    assert (tp1.label, tp1.price, tp1.fraction, tp1.leg_quantity) == (
        "TP1",
        D("51000"),
        D("0.5"),
        D("0.04"),
    )
    assert tp1.profit_gross == D("36.00")
    assert tp1.profit_net == D("36.00") - D("0.04") * (
        D("50100") * LEG_RATE + D("51000") * LEG_RATE
    )
    assert (tp2.label, tp2.price, tp2.fraction, tp2.leg_quantity) == (
        "TP2",
        D("52000"),
        D("0.5"),
        D("0.04"),
    )
    assert tp2.profit_gross == D("76.00")
    assert tp2.profit_net == D("76.00") - D("0.04") * (
        D("50100") * LEG_RATE + D("52000") * LEG_RATE
    )

    assert money.equity == D("800")
    assert money.equity_source == EQUITY_SOURCE_ACCOUNT_LIVE
    assert money.equity_observed_at_utc == OBSERVED
    assert money.leverage_source == LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT


def test_the_block_refuses_a_notional_that_the_quantity_and_entry_do_not_produce() -> None:
    money = _build_long()
    with pytest.raises(ValueError, match="notional"):
        replace(money, notional=money.notional + D("1"))


def test_the_block_refuses_leg_quantities_that_do_not_sum_to_the_quantity() -> None:
    money = _build_long()
    first, second = money.take_profits
    with pytest.raises(ValueError, match="leg quantities"):
        replace(money, take_profits=(first, replace(second, leg_quantity=first.leg_quantity / 2)))


def test_canonical_json_shape_and_round_trip_byte_for_byte() -> None:
    money = _build_long()
    text = money_canonical_json(money)

    assert " " not in text
    doc = json.loads(text)
    assert list(doc) == sorted(doc)
    assert doc["schema"] == "money-at-stake/1"
    assert doc["leverage"] == 5 and isinstance(doc["leverage"], int)
    assert doc["notional"] == "4008.00"
    assert doc["initial_margin"] == "801.60"
    assert doc["equity_observed_at_utc"] == "2026-10-09T03:00:00+00:00"
    assert doc["take_profits"][0]["leg_quantity"] == "0.040"
    assert list(doc["take_profits"][0]) == sorted(doc["take_profits"][0])
    for value in doc.values():
        assert not isinstance(value, float)

    parsed = parse_money_json(text)
    assert parsed == money
    assert money_canonical_json(parsed) == text


# --------------------------------------------------------------------------- #
# Task 2: SHORT, refusals, rounding direction, TP side checks, strict parsing
# --------------------------------------------------------------------------- #


def _sized_short() -> SizedResult:
    # entry_min 50000 (adverse edge), SL 50600: risk per unit = 600 + (50000 + 50600) x 0.0007
    return SizedResult(
        is_no_trade=False,
        quantity=D("0.08"),
        quantity_before_rounding=D("0.0801"),
        quantity_after_rounding=D("0.08"),
        quantization_decision="ACCEPTED",
        realized_risk=D("53.6336"),
        modeled_costs_per_unit=D("70.42"),
        sizing_entry_price=D("50000"),
    )


def _kwargs(**override: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "side": "LONG",
        "sized": _sized_long(),
        "stop_loss_price": D("49500"),
        "take_profits": [(D("51000"), D("0.5")), (D("52000"), D("0.5"))],
        "cost_rates": RATES,
        "leverage": 5,
        "leverage_source": LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT,
        "equity": D("800"),
        "equity_source": EQUITY_SOURCE_ACCOUNT_LIVE,
        "equity_observed_at_utc": OBSERVED,
    }
    base.update(override)
    return base


def test_short_plan_money_is_recomputed_independently() -> None:
    money = build_money_at_stake(
        **_kwargs(
            side="SHORT",
            sized=_sized_short(),
            stop_loss_price=D("50600"),
            take_profits=[(D("49000"), D("0.5")), (D("48000"), D("0.5"))],
            leverage=4,
        )
    )

    assert money.side == "SHORT"
    assert money.entry_price == D("50000")
    assert money.notional == D("4000.00")  # 0.08 x 50000
    assert money.initial_margin == D("1000")  # 4000 / 4
    assert money.loss_at_stop_gross == D("48.00")  # 0.08 x |50000 - 50600|
    assert money.loss_at_stop_net == D("53.6336")
    assert money.loss_at_stop_net == _sized_short().realized_risk
    tp1, tp2 = money.take_profits
    assert (tp1.label, tp1.leg_quantity, tp1.profit_gross) == ("TP1", D("0.04"), D("40.00"))
    assert tp1.profit_net == D("40.00") - D("0.04") * (
        D("50000") * LEG_RATE + D("49000") * LEG_RATE
    )
    assert (tp2.label, tp2.leg_quantity, tp2.profit_gross) == ("TP2", D("0.04"), D("80.00"))
    assert tp2.profit_net == D("80.00") - D("0.04") * (
        D("50000") * LEG_RATE + D("48000") * LEG_RATE
    )
    assert parse_money_json(money_canonical_json(money)) == money


def _assert_refused(field: str, **override: Any) -> None:
    with pytest.raises(MoneyAtStakeUnavailable) as caught:
        build_money_at_stake(**_kwargs(**override))
    assert caught.value.reason_code == MONEY_AT_STAKE_MISSING
    assert caught.value.field == field
    assert field in str(caught.value)


def test_refuses_a_no_trade_result() -> None:
    no_trade = SizedResult(
        is_no_trade=True,
        quantity=None,
        quantity_before_rounding=D("0.001"),
        quantity_after_rounding=D("0"),
        quantization_decision="REJECTED",
        realized_risk=D("0"),
        reason_code="MIN_QTY_REJECT",
    )
    _assert_refused("sized", sized=no_trade)


def test_refuses_without_sizing_entry_price() -> None:
    _assert_refused("sizing_entry_price", sized=replace(_sized_long(), sizing_entry_price=None))


def test_refuses_without_modeled_costs() -> None:
    _assert_refused(
        "modeled_costs_per_unit", sized=replace(_sized_long(), modeled_costs_per_unit=None)
    )


def test_refuses_without_leverage() -> None:
    _assert_refused("leverage", leverage=None)


def test_refuses_without_equity() -> None:
    _assert_refused("equity", equity=None)


def test_refuses_without_equity_time() -> None:
    _assert_refused("equity_observed_at_utc", equity_observed_at_utc=None)


def test_refuses_without_stop_loss() -> None:
    _assert_refused("stop_loss_price", stop_loss_price=None)


@pytest.mark.parametrize("empty", [[], None])
def test_refuses_without_take_profits(empty: Any) -> None:
    _assert_refused("take_profits", take_profits=empty)


@pytest.mark.parametrize("second", [D("0.4"), D("0.6")])
def test_refuses_fractions_that_do_not_sum_to_one(second: Decimal) -> None:
    _assert_refused("take_profits", take_profits=[(D("51000"), D("0.5")), (D("52000"), second)])


@pytest.mark.parametrize("bad_price", [D("50100"), D("50000")])
def test_refuses_a_long_take_profit_at_or_below_entry(bad_price: Decimal) -> None:
    _assert_refused("take_profits", take_profits=[(bad_price, D("0.5")), (D("52000"), D("0.5"))])


@pytest.mark.parametrize("bad_price", [D("50000"), D("50500")])
def test_refuses_a_short_take_profit_at_or_above_entry(bad_price: Decimal) -> None:
    _assert_refused(
        "take_profits",
        side="SHORT",
        sized=_sized_short(),
        stop_loss_price=D("50600"),
        take_profits=[(bad_price, D("0.5")), (D("48000"), D("0.5"))],
    )


def test_refuses_a_stop_on_the_wrong_side() -> None:
    _assert_refused("stop_loss_price", stop_loss_price=D("50200"))


def test_refuses_realized_risk_below_the_gross_loss() -> None:
    _assert_refused("realized_risk", sized=replace(_sized_long(), realized_risk=D("47.99")))


def test_margin_is_truncated_never_rounded_up() -> None:
    # 0.07 x 50101 = 3507.07 ; / 3 = 1169.02333... (non-terminating)
    sized = SizedResult(
        is_no_trade=False,
        quantity=D("0.07"),
        quantity_before_rounding=D("0.0705"),
        quantity_after_rounding=D("0.07"),
        quantization_decision="ACCEPTED",
        realized_risk=D("46.5"),
        modeled_costs_per_unit=D("70.1"),
        sizing_entry_price=D("50101"),
    )
    money = build_money_at_stake(**_kwargs(sized=sized, leverage=3))

    exact = Fraction(7, 100) * 50101 / 3
    margin = Fraction(money.initial_margin)
    exponent = money.initial_margin.as_tuple().exponent
    assert isinstance(exponent, int) and exponent >= -18
    assert margin <= exact
    assert exact - margin < Fraction(1, 10**18)
    assert margin != exact


def _doc() -> dict[str, Any]:
    return json.loads(money_canonical_json(_build_long()))  # type: ignore[no-any-return]


def _dump(doc: dict[str, Any]) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"))


def test_parser_rejects_a_float_literal_anywhere() -> None:
    top = _doc()
    top["equity"] = 800.5
    with pytest.raises(ValueError, match="float"):
        parse_money_json(_dump(top))
    nested = _doc()
    nested["take_profits"][0]["fraction"] = 0.5
    with pytest.raises(ValueError, match="float"):
        parse_money_json(_dump(nested))
    leverage = _doc()
    leverage["leverage"] = 5.0
    with pytest.raises(ValueError, match="float"):
        parse_money_json(_dump(leverage))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_parser_rejects_non_finite_constants(constant: str) -> None:
    text = money_canonical_json(_build_long()).replace('"leverage":5', f'"leverage":{constant}')
    with pytest.raises(ValueError, match="non-finite"):
        parse_money_json(text)


def test_parser_rejects_unknown_and_missing_keys() -> None:
    extra = _doc()
    extra["note"] = "x"
    with pytest.raises(ValueError, match="unknown"):
        parse_money_json(_dump(extra))
    missing = _doc()
    del missing["equity"]
    with pytest.raises(ValueError, match="missing"):
        parse_money_json(_dump(missing))
    leg_extra = _doc()
    leg_extra["take_profits"][1]["note"] = "x"
    with pytest.raises(ValueError, match="unknown"):
        parse_money_json(_dump(leg_extra))
    leg_missing = _doc()
    del leg_missing["take_profits"][0]["profit_net"]
    with pytest.raises(ValueError, match="missing"):
        parse_money_json(_dump(leg_missing))


def test_parser_rejects_a_foreign_schema_tag() -> None:
    doc = _doc()
    doc["schema"] = "money-at-stake/2"
    with pytest.raises(ValueError, match="schema"):
        parse_money_json(_dump(doc))


def test_parser_rejects_a_naive_time_and_a_bool_leverage() -> None:
    naive = _doc()
    naive["equity_observed_at_utc"] = "2026-10-09T03:00:00"
    with pytest.raises(ValueError, match="UTC"):
        parse_money_json(_dump(naive))
    boolean = _doc()
    boolean["leverage"] = True
    with pytest.raises(ValueError, match="integer"):
        parse_money_json(_dump(boolean))


def test_parser_rejects_non_canonical_decimal_text_and_duplicate_keys() -> None:
    doc = _doc()
    doc["equity"] = "8E+2"
    with pytest.raises(ValueError, match="canonical"):
        parse_money_json(_dump(doc))
    text = money_canonical_json(_build_long()).replace('"leverage":5', '"leverage":5,"leverage":6')
    with pytest.raises(ValueError, match="duplicate"):
        parse_money_json(text)
    with pytest.raises(ValueError, match="valid JSON"):
        parse_money_json("{")


def test_module_is_pure_no_clock_no_float_no_execution_import() -> None:
    path = Path(__file__).resolve().parent.parent / "src" / "risk" / "money_at_stake.py"
    assert wall_clock_calls(path) == []
    assert float_constructor_calls(path) == []
    assert forbidden_imports(path, ("src.execution", "src.paper", "src.adapters", "telegram")) == []
