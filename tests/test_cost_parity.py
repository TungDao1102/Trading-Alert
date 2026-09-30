"""Cost parity across every call site of the one cost producer (Phase 12, plan 12-10; D-19).

Three consumers must agree on the modeled round-trip cost for identical
inputs: `per_unit_round_trip_cost` itself, `backtest.costs.modeled_costs_per_unit`
and `evaluate_risk`. The simulator and the paper loop must hand `evaluate_risk`
identical cost arguments on the same trigger bar, and both wrappers must
delegate to the single producer object (patching it changes both).

Every expected number is a hand-derived literal:

* BTC LONG zone 59900-60100, stop 58780: 60100 x 0.0006 + 58780 x 0.0008
  = 36.06 + 47.024 = 83.084
* XRP LONG zone 0.4990-0.5010, stop 0.4930: 0.5010 x 0.0006 + 0.4930 x 0.0008
  = 0.0003006 + 0.0003944 = 0.000695
* BTC LONG with account taker 0.0007: 60100 x 0.0008 + 58780 x 0.0010
  = 48.08 + 58.78 = 106.86
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
import src.backtest.costs as costs_module
import src.backtest.simulator as simulator_module
import src.paper.loop as paper_module
import src.risk.cost_rates as cost_rates_module
import src.risk.gating as gating_module
from src.backtest.costs import build_cost_model, modeled_costs_per_unit
from src.backtest.simulator import run as simulator_run
from src.risk import CostRates, PortfolioVerdict, evaluate_risk
from src.risk.cost_rates import (
    FEE_SOURCE_ACCOUNT_MAX,
    FEE_SOURCE_PARAMETER,
    per_unit_round_trip_cost,
)
from src.risk.live_commission import AccountCommission, resolve_live_cost_rates

from tests.test_paper_parity import PARITY_FIXTURE_DIR, _replay_paper_through_bars
from tests.test_risk_cost_guards import (
    FROZEN_NOW,
    MAX_RATIO,
    MIN_STOP,
    MIN_UTIL,
    PARAMETERS,
    TTL,
    _account,
    _btc_constraints,
    _btc_long,
    _rates,
    _xrp_constraints,
    _xrp_long,
)

COST_MODEL_DICT: dict[str, str] = {
    "fee_rate_entry": "0.0005",
    "fee_rate_exit": "0.0005",
    "funding_treatment": "ADDITIVE",
    "expected_slippage": "0.0001",
    "slippage_model": "FIXED_BPS",
    "spread_fill_assumptions": "FULL_FILL",
    "partial_fill_fraction": "1.0",
    "exit_slippage_rate": "0.0003",
}


def _evaluate_with(plan: Any, constraints: Any, rates: CostRates) -> PortfolioVerdict:
    return evaluate_risk(
        trade_plan=plan,
        candidate_position_side="LONG",
        account_state=_account(),
        constraint_snapshot=constraints,
        open_positions=[],
        daily_loss_quote=Decimal("0"),
        now_utc=FROZEN_NOW,
        ttl=TTL,
        cost_rates=rates,
        min_stop_distance_rate=MIN_STOP,
        max_cost_to_risk=MAX_RATIO,
        minimum_risk_utilization_after_rounding=MIN_UTIL,
        parameter_set=PARAMETERS,
    )


def _sized_cost(verdict: PortfolioVerdict) -> Decimal:
    assert verdict.is_no_trade is False, verdict.reason_code
    assert verdict.sized is not None
    assert verdict.sized.modeled_costs_per_unit is not None
    return verdict.sized.modeled_costs_per_unit


# --------------------------------------------------------------------------- #
# Four-way equality: producer, backtest helper, evaluate_risk, literal
# --------------------------------------------------------------------------- #


def test_four_way_equality_btc_long() -> None:
    entry, stop = Decimal("60100"), Decimal("58780")
    producer = per_unit_round_trip_cost(
        side="LONG", entry_price=entry, stop_price=stop, rates=_rates()
    )
    helper = modeled_costs_per_unit(
        cost_model=build_cost_model(dict(COST_MODEL_DICT)),
        side="LONG",
        entry_price=entry,
        stop_price=stop,
    )
    pipeline = _sized_cost(_evaluate_with(_btc_long(), _btc_constraints(), _rates()))
    assert producer == helper == pipeline == Decimal("83.0840")


def test_four_way_equality_xrp_long() -> None:
    entry, stop = Decimal("0.5010"), Decimal("0.4930")
    producer = per_unit_round_trip_cost(
        side="LONG", entry_price=entry, stop_price=stop, rates=_rates()
    )
    helper = modeled_costs_per_unit(
        cost_model=build_cost_model(dict(COST_MODEL_DICT)),
        side="LONG",
        entry_price=entry,
        stop_price=stop,
    )
    pipeline = _sized_cost(_evaluate_with(_xrp_long(), _xrp_constraints(), _rates()))
    assert producer == helper == pipeline == Decimal("0.000695")


# --------------------------------------------------------------------------- #
# Delegation: one producer object behind every wrapper
# --------------------------------------------------------------------------- #


def test_every_wrapper_holds_the_same_producer_object() -> None:
    producer = cost_rates_module.per_unit_round_trip_cost
    assert costs_module.per_unit_round_trip_cost is producer
    assert gating_module.per_unit_round_trip_cost is producer


def test_patching_the_producer_changes_both_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def constant_one(**_: Any) -> Decimal:
        return Decimal("1")

    model = build_cost_model(dict(COST_MODEL_DICT))
    kwargs: dict[str, Any] = {
        "cost_model": model,
        "side": "LONG",
        "entry_price": Decimal("60100"),
        "stop_price": Decimal("58780"),
    }

    # Control: unpatched, both equal the oracle (they derive nothing themselves).
    assert modeled_costs_per_unit(**kwargs) == Decimal("83.0840")
    assert _sized_cost(_evaluate_with(_btc_long(), _btc_constraints(), _rates())) == Decimal(
        "83.0840"
    )

    monkeypatch.setattr(costs_module, "per_unit_round_trip_cost", constant_one)
    assert modeled_costs_per_unit(**kwargs) == Decimal("1")
    # The pipeline is untouched by the backtest-side patch.
    assert _sized_cost(_evaluate_with(_btc_long(), _btc_constraints(), _rates())) == Decimal(
        "83.0840"
    )

    monkeypatch.setattr(gating_module, "per_unit_round_trip_cost", constant_one)
    assert _sized_cost(_evaluate_with(_btc_long(), _btc_constraints(), _rates())) == Decimal("1")


# --------------------------------------------------------------------------- #
# Call-site parity: simulator and paper loop hand evaluate_risk the same inputs
# --------------------------------------------------------------------------- #


def _spy_on_evaluate_risk(
    monkeypatch: pytest.MonkeyPatch, module: Any
) -> list[tuple[dict[str, Any], PortfolioVerdict]]:
    sink: list[tuple[dict[str, Any], PortfolioVerdict]] = []
    real = module.evaluate_risk

    def wrapper(**kwargs: Any) -> PortfolioVerdict:
        verdict: PortfolioVerdict = real(**kwargs)
        sink.append((dict(kwargs), verdict))
        return verdict

    monkeypatch.setattr(module, "evaluate_risk", wrapper)
    return sink


def test_simulator_and_paper_call_evaluate_risk_with_identical_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim_calls = _spy_on_evaluate_risk(monkeypatch, simulator_module)
    paper_calls = _spy_on_evaluate_risk(monkeypatch, paper_module)

    case_input = json.loads((PARITY_FIXTURE_DIR / "input.json").read_text())
    sim_result = simulator_run(case_input)
    # The paper loop replays bar by bar; only the trigger bar reaches the risk stage.
    _replay_paper_through_bars(case_input)

    assert len(sim_calls) == 1, "the simulator must reach the risk stage exactly once"
    assert len(paper_calls) == 1, "the paper loop must reach the risk stage exactly once"
    (sim_kwargs, sim_verdict), (paper_kwargs, paper_verdict) = sim_calls[0], paper_calls[0]

    for name in (
        "cost_rates",
        "min_stop_distance_rate",
        "max_cost_to_risk",
        "trade_plan",
        "candidate_position_side",
        "account_state",
        "constraint_snapshot",
    ):
        assert sim_kwargs[name] == paper_kwargs[name], name
    assert sim_kwargs == paper_kwargs

    # The literal parameter rates reach both call sites (baseline-v5 fixture).
    rates = sim_kwargs["cost_rates"]
    assert (
        rates.fee_rate_entry,
        rates.entry_slippage_rate,
        rates.fee_rate_exit,
        rates.exit_slippage_rate,
        rates.fee_source,
    ) == (
        Decimal("0.0005"),
        Decimal("0.0001"),
        Decimal("0.0005"),
        Decimal("0.0003"),
        FEE_SOURCE_PARAMETER,
    )
    assert (sim_kwargs["min_stop_distance_rate"], sim_kwargs["max_cost_to_risk"]) == (
        Decimal("0.003"),
        Decimal("0.15"),
    )

    assert sim_verdict.is_no_trade is False and paper_verdict.is_no_trade is False
    assert sim_verdict.sized is not None and paper_verdict.sized is not None
    assert sim_verdict.sized.quantity == paper_verdict.sized.quantity
    assert sim_verdict.sized.modeled_costs_per_unit == paper_verdict.sized.modeled_costs_per_unit

    # The simulator record shows what sizing used.
    (trade,) = sim_result["trades"]
    assert Decimal(str(trade["modeled_costs_per_unit"])) == sim_verdict.sized.modeled_costs_per_unit


# --------------------------------------------------------------------------- #
# Live commission versus the versioned parameter rates (D-10, D-12)
# --------------------------------------------------------------------------- #


def _commission(taker: str) -> AccountCommission:
    return AccountCommission(
        symbol="BTCUSDT",
        maker_rate=Decimal("0.0002"),
        taker_rate=Decimal(taker),
        observed_at_utc=FROZEN_NOW - timedelta(seconds=10),
    )


def _live_rates(taker: str) -> CostRates:
    result = resolve_live_cost_rates(
        parameter_rates=_rates(),
        account_commission=_commission(taker),
        candidate_symbol="BTCUSDT",
        now_utc=FROZEN_NOW,
        ttl=TTL,
    )
    assert result.rates is not None
    return result.rates


def test_account_taker_below_parameter_gives_the_parameter_quantity_and_cost() -> None:
    live = _live_rates("0.0004")
    assert live.fee_source == FEE_SOURCE_ACCOUNT_MAX
    assert (
        live.fee_rate_entry,
        live.entry_slippage_rate,
        live.fee_rate_exit,
        live.exit_slippage_rate,
    ) == (Decimal("0.0005"), Decimal("0.0001"), Decimal("0.0005"), Decimal("0.0003"))

    parameter = _evaluate_with(_btc_long(), _btc_constraints(), _rates())
    live_verdict = _evaluate_with(_btc_long(), _btc_constraints(), live)
    assert parameter.sized is not None and live_verdict.sized is not None
    assert live_verdict.sized.quantity == parameter.sized.quantity == Decimal("0.035")
    assert _sized_cost(live_verdict) == _sized_cost(parameter) == Decimal("83.0840")
    assert live_verdict.sized.fee_source == FEE_SOURCE_ACCOUNT_MAX
    assert parameter.sized.fee_source == FEE_SOURCE_PARAMETER


def test_account_taker_above_parameter_raises_the_recorded_fee_and_never_grows_the_size() -> None:
    live = _live_rates("0.0007")
    parameter = _evaluate_with(_btc_long(), _btc_constraints(), _rates())
    live_verdict = _evaluate_with(_btc_long(), _btc_constraints(), live)
    assert parameter.sized is not None and live_verdict.sized is not None
    assert parameter.sized.quantity is not None and live_verdict.sized.quantity is not None

    assert live_verdict.sized.quantity <= parameter.sized.quantity
    assert live_verdict.sized.fee_rate_entry == Decimal("0.0007")
    assert live_verdict.sized.fee_rate_exit == Decimal("0.0007")
    assert live_verdict.sized.fee_source == FEE_SOURCE_ACCOUNT_MAX
    assert _sized_cost(live_verdict) == Decimal("106.860")
    assert _sized_cost(live_verdict) > _sized_cost(parameter)
