"""A SIMULATE payload with a consistent money block (Phase 23, plan 23-09).

`notify_simulate` and `format_simulate` require `approved_quantity` and `money` (D-14). The money
is built by the real `build_money_at_stake` from a sizing result written here, so the payload
agrees with itself: the same quantity, stop, take-profit prices and fractions, side LONG.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates
from src.risk.money_at_stake import (
    EQUITY_SOURCE_PAPER_CONFIG,
    LEVERAGE_SOURCE_PAPER_CONFIG,
    MoneyAtStake,
    build_money_at_stake,
)
from src.risk.types import SizedResult

D = Decimal
QUANTITY = D("2.415")
STOP_LOSS = D("99.50")
TAKE_PROFITS: list[tuple[Decimal, Decimal]] = [(D("101.50"), D("0.5")), (D("103.00"), D("0.5"))]
OBSERVED_AT_UTC = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)


def make_money(**overrides: Any) -> MoneyAtStake:
    """The money block of the payload below: entry 100.30, stop 99.50, quantity 2.415."""
    sized = SizedResult(
        is_no_trade=False,
        quantity=QUANTITY,
        quantity_before_rounding=D("2.4151"),
        quantity_after_rounding=QUANTITY,
        quantization_decision="ACCEPTED",
        realized_risk=D("2.10"),
        modeled_costs_per_unit=D("0.20"),
        sizing_entry_price=D("100.30"),
    )
    values: dict[str, Any] = {
        "side": "LONG",
        "sized": sized,
        "stop_loss_price": STOP_LOSS,
        "take_profits": TAKE_PROFITS,
        "cost_rates": CostRates(
            fee_rate_entry=D("0.0005"),
            entry_slippage_rate=D("0.0002"),
            fee_rate_exit=D("0.0005"),
            exit_slippage_rate=D("0.0002"),
            fee_source=FEE_SOURCE_PARAMETER,
        ),
        "leverage": 5,
        "leverage_source": LEVERAGE_SOURCE_PAPER_CONFIG,
        "equity": D("1000"),
        "equity_source": EQUITY_SOURCE_PAPER_CONFIG,
        "equity_observed_at_utc": OBSERVED_AT_UTC,
    }
    values.update(overrides)
    return build_money_at_stake(**values)


def make_simulate_payload(**overrides: Any) -> dict[str, Any]:
    """The 12 APRV-01 fields plus `approved_quantity` and `money` of one LONG paper plan."""
    payload: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "setup": "TREND_PULLBACK_LONG",
        "entry_min": D("100.10"),
        "entry_max": D("100.30"),
        "stop_loss": STOP_LOSS,
        "take_profits": list(TAKE_PROFITS),
        "rr": D("2.0"),
        "risk_pct": D("0.005"),
        "expiry_utc": datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
        "invalidation": "CANDLE_CLOSE < 99.50",
        "exposure_quote": D("50.00"),
        "reason_codes": ["SETUP_DETECTED"],
        "signal_id": "sig_test_0000000000000000000000000000000000000000000000000000",
        "detected_at_utc": datetime(2026, 9, 19, 9, 0, tzinfo=UTC),
        "approved_quantity": QUANTITY,
        "money": make_money(),
    }
    payload.update(overrides)
    return payload
