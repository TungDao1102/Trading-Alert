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

from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import Any

import pytest
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


def stop_loss_exit_loss(*, side: str, fill: Decimal, stop: Decimal, quantity: Decimal) -> Decimal:
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


# --------------------------------------------------------------------------- #
# Task 2: the full grid (3 prices x 5 widths x 2 sides x 2 equities = 60 plans)
# --------------------------------------------------------------------------- #

PRICES: dict[str, Decimal] = {
    "BTCUSDT": Decimal("60000"),
    "ETHUSDT": Decimal("3000"),
    "XRPUSDT": Decimal("0.5"),
}
STEPS: dict[str, Decimal] = {
    "BTCUSDT": Decimal("0.001"),
    "ETHUSDT": Decimal("0.001"),
    "XRPUSDT": Decimal("0.1"),
}
WIDTHS = tuple(Decimal(w) for w in ("0.008", "0.01", "0.015", "0.02", "0.03"))
SIDES = ("LONG", "SHORT")
EQUITIES = ("10000", "800")

# Plans may be rejected here only for quantity reasons; a guard rejection
# inside the grid would mean the widths no longer sit past both guards.
QUANTITY_REJECTS = frozenset({"MIN_QTY_REJECT", "NOTIONAL_REJECT", "UTILIZATION_REJECT"})

# The previous behaviour: rate sum fee_in + fee_out + expected_slippage added
# to a price distance measured from the zone MID.
OLD_RATE_SUM = FEE_IN + FEE_OUT + SLIP_IN


@dataclass(frozen=True)
class GridPoint:
    symbol: str
    side: str
    width: Decimal
    equity: str
    zone: tuple[Decimal, Decimal]
    stop: Decimal

    @property
    def allowed_risk(self) -> Decimal:
        return Decimal(self.equity) * RISK_RATE

    @property
    def edge(self) -> Decimal:
        return _adverse_edge(self.side, self.zone)

    @property
    def risk_per_unit(self) -> Decimal:
        """Loss per unit at the adverse-edge fill, from the literal rates."""
        return (
            abs(self.edge - self.stop)
            + self.edge * (FEE_IN + SLIP_IN)
            + self.stop * (FEE_OUT + SLIP_OUT)
        )


def _grid() -> list[GridPoint]:
    points: list[GridPoint] = []
    for symbol, price in PRICES.items():
        zone = _zone(price)
        for width in WIDTHS:
            for side in SIDES:
                stop = _stop(side, zone, width)
                for equity in EQUITIES:
                    points.append(GridPoint(symbol, side, width, equity, zone, stop))
    return points


def _find(symbol: str, side: str, width: str, equity: str) -> GridPoint:
    matches = [
        p
        for p in _grid()
        if (p.symbol, p.side, p.width, p.equity) == (symbol, side, Decimal(width), equity)
    ]
    assert len(matches) == 1
    return matches[0]


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _fill_at(point: GridPoint, fraction: Decimal) -> Decimal:
    return point.zone[0] + (point.zone[1] - point.zone[0]) * fraction


def _adverse_fraction(side: str) -> Decimal:
    return Decimal("1") if side == "LONG" else Decimal("0")


@pytest.fixture(scope="module")
def evaluated() -> dict[GridPoint, PortfolioVerdict]:
    return {
        p: _run(symbol=p.symbol, side=p.side, zone=p.zone, stop=p.stop, equity=p.equity)
        for p in _grid()
    }


def _accepted_quantity(verdict: PortfolioVerdict) -> Decimal:
    assert verdict.is_no_trade is False
    assert verdict.sized is not None
    assert verdict.sized.quantity is not None
    return verdict.sized.quantity


def test_grid_has_sixty_points() -> None:
    assert len(_grid()) == 3 * 5 * 2 * 2


def test_accepted_plans_never_lose_more_than_allowed_risk_at_the_stop(
    evaluated: dict[GridPoint, PortfolioVerdict],
) -> None:
    for point, verdict in evaluated.items():
        if verdict.is_no_trade:
            continue
        quantity = _accepted_quantity(verdict)
        assert verdict.sized is not None

        for fraction in FRACTIONS:
            loss = stop_loss_exit_loss(
                side=point.side, fill=_fill_at(point, fraction), stop=point.stop, quantity=quantity
            )
            assert loss <= point.allowed_risk + LOSS_TOLERANCE, (point, fraction, loss)

        # Independent quantity: allowed_risk / risk_per_unit floored to the step.
        assert quantity == _floor_to_step(
            point.allowed_risk / point.risk_per_unit, STEPS[point.symbol]
        ), point

        # Loss at the adverse edge is exactly quantity x risk_per_unit, and the
        # recorded realized risk is that same number.
        edge_loss = stop_loss_exit_loss(
            side=point.side,
            fill=_fill_at(point, _adverse_fraction(point.side)),
            stop=point.stop,
            quantity=quantity,
        )
        assert edge_loss == quantity * point.risk_per_unit, point
        assert verdict.sized.realized_risk == quantity * point.risk_per_unit, point
        assert verdict.sized.realized_risk <= point.allowed_risk + LOSS_TOLERANCE, point


def test_grid_acceptance_counts_and_rejection_reasons(
    evaluated: dict[GridPoint, PortfolioVerdict],
) -> None:
    accepted = [p for p, v in evaluated.items() if not v.is_no_trade]
    assert len(accepted) >= 24
    for symbol in PRICES:
        for side in SIDES:
            assert any(p.symbol == symbol and p.side == side for p in accepted), (symbol, side)
    for point, verdict in evaluated.items():
        if verdict.is_no_trade:
            assert verdict.reason_code in QUANTITY_REJECTS, (point, verdict.reason_code)


def test_flooring_to_the_step_is_material(
    evaluated: dict[GridPoint, PortfolioVerdict],
) -> None:
    """At least one accepted BTC/ETH plan is sized strictly below the raw ratio."""
    floored = [
        p
        for p, v in evaluated.items()
        if not v.is_no_trade
        and p.symbol in ("BTCUSDT", "ETHUSDT")
        and _accepted_quantity(v) < p.allowed_risk / p.risk_per_unit
    ]
    assert floored


def test_corrected_xrp_long_quantity_at_the_narrowest_width(
    evaluated: dict[GridPoint, PortfolioVerdict],
) -> None:
    point = _find("XRPUSDT", "LONG", "0.008", "10000")
    quantity = _accepted_quantity(evaluated[point])
    assert quantity == Decimal("10634.9")  # planning-time independent value
    edge_loss = stop_loss_exit_loss(
        side="LONG", fill=point.edge, stop=point.stop, quantity=quantity
    )
    assert edge_loss <= Decimal("50")


# --------------------------------------------------------------------------- #
# Guard regions (RESEARCH Pitfall 2: the cost ceiling binds before the floor)
# --------------------------------------------------------------------------- #


def _guard_verdict(symbol: str, side: str, width: str) -> PortfolioVerdict:
    zone = _zone(PRICES[symbol])
    return _run(
        symbol=symbol, side=side, zone=zone, stop=_stop(side, zone, Decimal(width)), equity="10000"
    )


@pytest.mark.parametrize("symbol", ["BTCUSDT", "XRPUSDT"])
@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("width", ["0.001", "0.002", "0.0029"])
def test_widths_below_the_stop_floor_are_stop_too_tight(symbol: str, side: str, width: str) -> None:
    verdict = _guard_verdict(symbol, side, width)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "STOP_TOO_TIGHT"


@pytest.mark.parametrize("symbol", ["BTCUSDT", "XRPUSDT"])
@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("width", ["0.004", "0.006", "0.007"])
def test_widths_past_the_floor_but_costly_are_cost_to_risk_exceeded(
    symbol: str, side: str, width: str
) -> None:
    verdict = _guard_verdict(symbol, side, width)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "COST_TO_RISK_EXCEEDED"


@pytest.mark.parametrize("symbol", ["BTCUSDT", "XRPUSDT"])
@pytest.mark.parametrize("side", SIDES)
def test_width_0_8_percent_passes_both_guards(symbol: str, side: str) -> None:
    verdict = _guard_verdict(symbol, side, "0.008")
    assert verdict.is_no_trade is False, verdict.reason_code


# --------------------------------------------------------------------------- #
# Mutation check: the same harness fed the OLD formula must find violations
# --------------------------------------------------------------------------- #


def old_formula_quantity(
    *,
    side: str,
    zone: tuple[Decimal, Decimal],
    stop: Decimal,
    equity: Decimal,
    risk_rate: Decimal,
    step: Decimal,
) -> Decimal:
    """Previous behaviour: |zone mid - stop| + rate sum, floored to the step."""
    del side  # the old formula was side-symmetric
    mid = (zone[0] + zone[1]) / 2
    risk_per_unit = abs(mid - stop) + OLD_RATE_SUM
    return _floor_to_step(equity * risk_rate / risk_per_unit, step)


def _old_quantity(point: GridPoint) -> Decimal:
    return old_formula_quantity(
        side=point.side,
        zone=point.zone,
        stop=point.stop,
        equity=Decimal(point.equity),
        risk_rate=RISK_RATE,
        step=STEPS[point.symbol],
    )


def _edge_violations(
    quantity_of: Callable[[GridPoint], Decimal | None],
) -> list[tuple[GridPoint, Decimal]]:
    """Grid points whose loss at the adverse-edge fill exceeds allowed_risk."""
    found: list[tuple[GridPoint, Decimal]] = []
    for point in _grid():
        quantity = quantity_of(point)
        if quantity is None:
            continue
        loss = stop_loss_exit_loss(
            side=point.side, fill=point.edge, stop=point.stop, quantity=quantity
        )
        if loss > point.allowed_risk + LOSS_TOLERANCE:
            found.append((point, loss))
    return found


def _assert_harness_bites(
    quantity_of: Callable[[GridPoint], Decimal | None],
) -> list[tuple[GridPoint, Decimal]]:
    violations = _edge_violations(quantity_of)
    if not any(p.symbol == "BTCUSDT" for p, _ in violations):
        raise AssertionError(
            "the property test is vacuous: the mutated formula found no BTC violation"
        )
    return violations


def _pipeline_quantity_of(
    evaluated: dict[GridPoint, PortfolioVerdict],
) -> Callable[[GridPoint], Decimal | None]:
    def quantity_of(point: GridPoint) -> Decimal | None:
        verdict = evaluated[point]
        return None if verdict.is_no_trade else _accepted_quantity(verdict)

    return quantity_of


def test_pipeline_quantities_have_no_edge_violation(
    evaluated: dict[GridPoint, PortfolioVerdict],
) -> None:
    assert _edge_violations(_pipeline_quantity_of(evaluated)) == []


def test_old_formula_violates_the_budget_on_btc_and_xrp() -> None:
    violations = dict(_assert_harness_bites(_old_quantity))
    assert any(p.symbol == "BTCUSDT" for p in violations)
    assert any(p.symbol == "XRPUSDT" for p in violations)

    btc_long_2 = _find("BTCUSDT", "LONG", "0.02", "10000")
    assert _old_quantity(btc_long_2) == Decimal("0.043")
    assert Decimal("55.22") < violations[btc_long_2] < Decimal("55.23")

    btc_long_narrow = _find("BTCUSDT", "LONG", "0.008", "10000")
    assert _old_quantity(btc_long_narrow) == Decimal("0.118")
    assert Decimal("66.57") < violations[btc_long_narrow] < Decimal("66.58")

    btc_short_2 = _find("BTCUSDT", "SHORT", "0.02", "10000")
    assert Decimal("55.19") < violations[btc_short_2] < Decimal("55.20")

    xrp_long = _find("XRPUSDT", "LONG", "0.008", "10000")
    assert _old_quantity(xrp_long) == Decimal("10860.1")
    assert Decimal("51.05") < violations[xrp_long] < Decimal("51.06")


def test_harness_reports_vacuity_when_fed_a_correct_quantity(
    evaluated: dict[GridPoint, PortfolioVerdict],
) -> None:
    """Fed the corrected pipeline quantity, the mutation check must fail loudly."""
    with pytest.raises(AssertionError, match="vacuous"):
        _assert_harness_bites(_pipeline_quantity_of(evaluated))


def test_old_cost_term_ran_in_both_directions() -> None:
    """0.0011 overstates the XRP round-trip cost and understates the BTC one."""
    xrp_true = Decimal("0.5010") * (FEE_IN + SLIP_IN) + Decimal("0.4930") * (FEE_OUT + SLIP_OUT)
    assert xrp_true == Decimal("0.000695")
    assert OLD_RATE_SUM == Decimal("0.0011")
    assert OLD_RATE_SUM > xrp_true

    btc_true = Decimal("60100") * (FEE_IN + SLIP_IN) + Decimal("58780") * (FEE_OUT + SLIP_OUT)
    assert btc_true == Decimal("83.0840")
    assert OLD_RATE_SUM < btc_true
