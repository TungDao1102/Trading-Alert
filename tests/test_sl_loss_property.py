"""Stop-loss-within-budget property test (Phase 12, plan 12-10; D-17, F-601).

Central invariant of the phase: for every plan `evaluate_risk` accepts, the
loss when the stop is hit, INCLUDING entry and exit fees and slippage, is at
most `allowed_risk`, for a fill anywhere inside the entry zone.

The loss arithmetic below is plain Decimal with literal rates. It never calls
`per_unit_round_trip_cost`, `modeled_costs_per_unit` or `_apply_costs`, so a
defect in the code under test cannot make this test agree with itself (F-601:
the previous test recomputed the buggy formula and could not fail).

Rates: fee_in 0.0005, slip_in 0.0001, fee_out 0.0005, slip_out 0.0003. Guards
0.003 and 0.15. risk_rate 0.005. The grid is explicit and byte-reproducible
(D-17): no hypothesis, no random draws.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.core.types import AccountState
from src.risk import ConstraintSnapshot, CostRates, PortfolioVerdict, evaluate_risk

from tests.test_risk_cost_guards import FROZEN_NOW, TTL, _plan

# --------------------------------------------------------------------------- #
# Literal inputs (never read back from the code under test)
# --------------------------------------------------------------------------- #

FEE_IN = Decimal("0.0005")
SLIP_IN = Decimal("0.0001")
FEE_OUT = Decimal("0.0005")
SLIP_OUT = Decimal("0.0003")
MIN_STOP = Decimal("0.003")
MAX_RATIO = Decimal("0.15")
MIN_UTIL = Decimal("0.6")
RISK_RATE = Decimal("0.005")

# Quantity is floored to the step and every product below is exact at the
# default Decimal precision (28) for these magnitudes, so the tolerance is
# zero. Do not widen it without stating the reason here and in the SUMMARY.
LOSS_TOLERANCE = Decimal("0")

# Permissive portfolio thresholds: the property concerns sizing, not caps.
PORTFOLIO: dict[str, Any] = {
    "max_open_positions": 5,
    "max_aggregate_open_risk": Decimal("100000"),
    "cluster_cap": Decimal("100000"),
    "daily_loss_warning_threshold": Decimal("100000"),
    "daily_loss_stop_threshold": Decimal("200000"),
}

ZONE_HALF_WIDTH = Decimal("0.001")  # zone is the price plus and minus 0.1 percent


def _rates() -> CostRates:
    return CostRates(
        fee_rate_entry=FEE_IN,
        entry_slippage_rate=SLIP_IN,
        fee_rate_exit=FEE_OUT,
        exit_slippage_rate=SLIP_OUT,
        fee_source="PARAMETER",
    )


def _constraints(symbol: str) -> ConstraintSnapshot:
    tick, step, min_qty = {
        "BTCUSDT": ("0.1", "0.001", "0.001"),
        "ETHUSDT": ("0.01", "0.001", "0.001"),
        "XRPUSDT": ("0.0001", "0.1", "0.1"),
    }[symbol]
    return ConstraintSnapshot(
        symbol=symbol,
        price_tick_size=Decimal(tick),
        quantity_step_size=Decimal(step),
        min_quantity=Decimal(min_qty),
        min_notional=Decimal("5"),
        metadata_observed_at_utc=FROZEN_NOW,
    )


def _zone(price: Decimal) -> tuple[Decimal, Decimal]:
    return price * (1 - ZONE_HALF_WIDTH), price * (1 + ZONE_HALF_WIDTH)


def _stop(side: str, zone: tuple[Decimal, Decimal], width: Decimal) -> Decimal:
    """LONG stop is below the adverse edge (entry_max); SHORT above entry_min."""
    if side == "LONG":
        return zone[1] * (1 - width)
    return zone[0] * (1 + width)


def _adverse_edge(side: str, zone: tuple[Decimal, Decimal]) -> Decimal:
    return zone[1] if side == "LONG" else zone[0]


def stop_loss_exit_loss(
    *, side: str, fill: Decimal, stop: Decimal, quantity: Decimal
) -> Decimal:
    """Loss when the stop is hit, entry and exit fees and slippage included.

    LONG:  (fill - stop) q + fill q (fee_in + slip_in) + stop q (fee_out + slip_out)
    SHORT: (stop - fill) q + fill q (fee_in + slip_in) + stop q (fee_out + slip_out)
    """
    entry_costs = fill * quantity * (FEE_IN + SLIP_IN)
    exit_costs = stop * quantity * (FEE_OUT + SLIP_OUT)
    if side == "LONG":
        return (fill - stop) * quantity + entry_costs + exit_costs
    return (stop - fill) * quantity + entry_costs + exit_costs


def _plan_for(symbol: str, zone: tuple[Decimal, Decimal], stop: Decimal) -> Any:
    return _plan(entry_min=str(zone[0]), entry_max=str(zone[1]), stop=str(stop), symbol=symbol)


def _run(
    *, symbol: str, side: str, zone: tuple[Decimal, Decimal], stop: Decimal, equity: str
) -> PortfolioVerdict:
    return evaluate_risk(
        trade_plan=_plan_for(symbol, zone, stop),
        candidate_position_side=side,
        account_state=AccountState(equity=Decimal(equity), risk_rate=RISK_RATE),
        constraint_snapshot=_constraints(symbol),
        open_positions=[],
        daily_loss_quote=Decimal("0"),
        now_utc=FROZEN_NOW,
        ttl=TTL,
        cost_rates=_rates(),
        min_stop_distance_rate=MIN_STOP,
        max_cost_to_risk=MAX_RATIO,
        minimum_risk_utilization_after_rounding=MIN_UTIL,
        parameter_set=PORTFOLIO,
    )


# --------------------------------------------------------------------------- #
# Loss-function oracle (hand-derived literal, independent of project code)
# --------------------------------------------------------------------------- #


def test_loss_function_matches_the_earlier_btc_long_edge_oracle() -> None:
    """Zone 59900-60100, stop 58780, quantity 0.035, fill at the edge 60100.

    0.035 x (60100 x 1.0006 - 58780 x 0.9992) = 0.035 x 1403.084 = 49.10794.
    """
    loss = stop_loss_exit_loss(
        side="LONG", fill=Decimal("60100"), stop=Decimal("58780"), quantity=Decimal("0.035")
    )
    assert loss == Decimal("49.10794")


# --------------------------------------------------------------------------- #
# Tracer: one grid point end to end (BTC LONG, width 2.2 percent)
# --------------------------------------------------------------------------- #

FRACTIONS = (Decimal("0"), Decimal("0.25"), Decimal("0.5"), Decimal("0.75"), Decimal("1"))


def test_tracer_btc_long_width_2_2_percent_within_budget_at_every_fill() -> None:
    price = Decimal("60000")
    zone = _zone(price)
    assert zone == (Decimal("59940.000"), Decimal("60060.000"))
    stop = _stop("LONG", zone, Decimal("0.022"))
    assert stop == Decimal("58738.680000")

    verdict = _run(symbol="BTCUSDT", side="LONG", zone=zone, stop=stop, equity="10000")
    assert verdict.is_no_trade is False
    assert verdict.sized is not None
    quantity = verdict.sized.quantity
    assert quantity is not None

    allowed_risk = Decimal("10000") * RISK_RATE
    assert allowed_risk == Decimal("50.000")

    for fraction in FRACTIONS:
        fill = zone[0] + (zone[1] - zone[0]) * fraction
        loss = stop_loss_exit_loss(side="LONG", fill=fill, stop=stop, quantity=quantity)
        assert loss <= allowed_risk + LOSS_TOLERANCE, (fraction, loss)

    # At the adverse edge the loss equals quantity x risk_per_unit exactly,
    # with risk_per_unit written out from the literal rates.
    edge = _adverse_edge("LONG", zone)
    risk_per_unit = (edge - stop) + edge * (FEE_IN + SLIP_IN) + stop * (FEE_OUT + SLIP_OUT)
    edge_loss = stop_loss_exit_loss(side="LONG", fill=edge, stop=stop, quantity=quantity)
    assert edge_loss == quantity * risk_per_unit
    assert verdict.sized.realized_risk == quantity * risk_per_unit
