"""Money block built once from the risk pipeline output (Phase 23, plan 23-02, D-13, F-015).

Every expected value is recomputed here with plain Decimal arithmetic written in the test, not
with the module's helpers, so a wrong formula in the module cannot hide behind itself.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates
from src.risk.money_at_stake import (
    EQUITY_SOURCE_ACCOUNT_LIVE,
    LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT,
    MONEY_SCHEMA_TAG,
    MoneyAtStake,
    build_money_at_stake,
    money_canonical_json,
    parse_money_json,
)
from src.risk.types import SizedResult

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
    assert tp1.profit_net == D("36.00") - D("0.04") * (D("50100") * LEG_RATE + D("51000") * LEG_RATE)
    assert (tp2.label, tp2.price, tp2.fraction, tp2.leg_quantity) == (
        "TP2",
        D("52000"),
        D("0.5"),
        D("0.04"),
    )
    assert tp2.profit_gross == D("76.00")
    assert tp2.profit_net == D("76.00") - D("0.04") * (D("50100") * LEG_RATE + D("52000") * LEG_RATE)

    assert money.equity == D("800")
    assert money.equity_source == EQUITY_SOURCE_ACCOUNT_LIVE
    assert money.equity_observed_at_utc == OBSERVED
    assert money.leverage_source == LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT


def test_canonical_json_shape_and_round_trip_byte_for_byte() -> None:
    money = _build_long()
    text = money_canonical_json(money)

    assert " " not in text
    doc = json.loads(text)
    assert list(doc) == sorted(doc)
    assert doc["schema"] == "money-at-stake/1"
    assert doc["leverage"] == 5 and isinstance(doc["leverage"], int)
    assert doc["notional"] == "4008.00"
    assert doc["initial_margin"] == "801.6"
    assert doc["equity_observed_at_utc"] == "2026-10-09T03:00:00+00:00"
    assert doc["take_profits"][0]["leg_quantity"] == "0.04"
    assert list(doc["take_profits"][0]) == sorted(doc["take_profits"][0])
    for value in doc.values():
        assert not isinstance(value, float)

    parsed = parse_money_json(text)
    assert parsed == money
    assert money_canonical_json(parsed) == text
