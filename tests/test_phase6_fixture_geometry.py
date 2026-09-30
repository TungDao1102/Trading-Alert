"""Pre-flight geometry guard for the Phase 6 simulator fixtures (Phase 12-04).

The old generator built 1H bars with a 0.05 half-range, which gives ATR-derived
stops 0.06 to 0.26 percent away from entry. The Phase 12 cost guards (minimum
stop distance 0.3 percent, cost-to-risk ceiling 0.15) would reject such a plan
before sizing, so the fixtures would silently stop producing trades.

This module recomputes each fixture's plan geometry with the EXISTING strategy
and planner, then checks the guard thresholds with independent literal
arithmetic. It deliberately does NOT import ``src.risk.cost_rates`` or
``src.backtest.costs`` to compute expectations: a producer bug must not be able
to bless its own fixtures (threat T-12-09).
"""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from src.backtest.simulator import _parse_account_state, _parse_candle
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import MarketSnapshot
from src.domain.registry import load_parameter_set

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE6_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase6"

SIMULATOR_FIXTURES = (
    "intrabar_both_touched",
    "intrabar_both_touched_short",
    "intrabar_missing_fallback",
    "limit_touch_no_fill",
    "limit_partial_fill",
    "limit_expiry",
    "invalidation_cancels_entry",
)

# Independent literals (deliberately not read from the project producer).
FEE_ENTRY = Decimal("0.0005")
SLIP_ENTRY = Decimal("0.0001")
FEE_EXIT = Decimal("0.0005")
SLIP_EXIT = Decimal("0.0003")
ENTRY_RATE = FEE_ENTRY + SLIP_ENTRY  # 0.0006
EXIT_RATE = FEE_EXIT + SLIP_EXIT  # 0.0008
MIN_STOP_RATE = Decimal("0.003")
MAX_COST_TO_RISK = Decimal("0.15")
# Stop distance (fraction of price) at which the 0.15 ceiling binds:
# c*(0.0006 + 0.0008*(1-s)) = 0.15*(s + cost) -> s >= about 0.0079.
CEILING_BINDING_STOP_RATE = Decimal("0.0079")

EXPECTED_COST_KEYS = {
    "fee_rate_entry",
    "fee_rate_exit",
    "expected_slippage",
    "exit_slippage_rate",
    "funding_treatment",
    "slippage_model",
    "spread_fill_assumptions",
    "partial_fill_fraction",
}
EXPECTED_PARTIAL_FILL = {
    "limit_touch_no_fill": "0",
    "limit_partial_fill": "0.5",
}


def _load_case(*parts: str) -> dict[str, Any]:
    path = PHASE6_FIXTURES_DIR.joinpath(*parts, "input.json")
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _plan_for(case: dict[str, Any]) -> tuple[str, Any]:
    """Return (direction, plan_result) for the LAST strategy bar.

    Mirrors ``simulator.run``: closed setup candles up to the last bar, closed
    context candles at or before it, registry set named by the fixture.
    """
    strategy_bars = sorted(
        (_parse_candle(r) for r in case["strategy_bars"]),
        key=lambda b: (b.close_time_utc, b.symbol),
    )
    context_bars = sorted(
        (_parse_candle(r) for r in case["context_bars"]),
        key=lambda c: (c.close_time_utc, c.symbol),
    )
    last = strategy_bars[-1]
    closed_context = [c for c in context_bars if c.close_time_utc <= last.close_time_utc]
    snapshot = MarketSnapshot(
        symbol=last.symbol,
        setup_candles=strategy_bars,
        context_candles=closed_context,
        source_timeframe="1h",
    )
    account_state = _parse_account_state(case["account_state"])
    parameter_set = load_parameter_set(case["strategy_id"], case["parameter_set_id"])
    setup = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=case["strategy_version"],
        parameter_set=parameter_set,
    )
    assert not setup.is_no_trade, f"strategy produced no signal ({setup.reason_code})"
    signal = setup.signal
    assert signal is not None
    result = plan(
        signal=signal,
        setup_candles=strategy_bars,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=last.close_time_utc,
    )
    return signal.direction, result


def _assert_guard_clearance(case: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """Independent-arithmetic guard check; returns (stop_rate, cost_to_risk)."""
    direction, result = _plan_for(case)
    assert not result.is_no_trade, f"planner rejected: {result.reason_code}"
    trade_plan = result.trade_plan
    assert trade_plan is not None
    stop = trade_plan.stop_loss_price
    # Adverse edge: highest entry for LONG, lowest entry for SHORT.
    edge = trade_plan.entry_max_price if direction == "LONG" else trade_plan.entry_min_price
    distance = abs(edge - stop)
    stop_rate = distance / edge
    cost = edge * ENTRY_RATE + stop * EXIT_RATE
    risk_per_unit = distance + cost
    cost_to_risk = cost / risk_per_unit
    assert stop_rate >= MIN_STOP_RATE, f"stop {stop_rate} below 0.3 percent floor"
    assert stop_rate >= CEILING_BINDING_STOP_RATE, (
        f"stop {stop_rate} below the 0.79 percent level where the 0.15 ceiling binds"
    )
    assert cost_to_risk <= MAX_COST_TO_RISK, f"cost-to-risk {cost_to_risk} above 0.15"
    return stop_rate, cost_to_risk


@pytest.mark.parametrize("name", SIMULATOR_FIXTURES)
def test_fixture_carries_phase12_identity(name: str) -> None:
    case = _load_case(name)
    assert case["parameter_set_id"] == "baseline-v5"
    assert case["strategy_version"] == "v4.0.0"
    cost = case["cost_model"]
    assert set(cost) == EXPECTED_COST_KEYS
    assert cost["fee_rate_entry"] == "0.0005"
    assert cost["fee_rate_exit"] == "0.0005"
    assert cost["expected_slippage"] == "0.0001"
    assert cost["exit_slippage_rate"] == "0.0003"
    assert cost["funding_treatment"] == "ADDITIVE"
    assert cost["slippage_model"] == "FIXED_BPS"
    assert cost["spread_fill_assumptions"] == "FULL_FILL"
    assert cost["partial_fill_fraction"] == EXPECTED_PARTIAL_FILL.get(name, "1.0")


@pytest.mark.parametrize("name", SIMULATOR_FIXTURES)
def test_fixture_clears_both_cost_guards(name: str) -> None:
    _assert_guard_clearance(_load_case(name))


BASELINE_SETS = {
    "no_trade": "baseline-no-trade-v3",
    "simple_trend": "baseline-simple-trend-v3",
}


@pytest.mark.parametrize("name", sorted(BASELINE_SETS))
def test_baseline_fixture_carries_phase12_identity(name: str) -> None:
    case = _load_case("baselines", name)
    assert case["parameter_set_id"] == BASELINE_SETS[name]
    assert case["strategy_version"] == "v4.0.0"
    assert case["cost_model"] == _load_case("intrabar_both_touched")["cost_model"]
    assert set(case["cost_model"]) == EXPECTED_COST_KEYS


def test_simple_trend_baseline_clears_both_cost_guards() -> None:
    stop_rate, _ = _assert_guard_clearance(_load_case("baselines", "simple_trend"))
    # Planning-time prototype: about 1.83 percent.
    assert stop_rate >= Decimal("0.01")


def test_no_trade_baseline_is_rejected_by_the_planner_rr_gate() -> None:
    _, result = _plan_for(_load_case("baselines", "no_trade"))
    assert result.is_no_trade
    assert result.reason_code == "RR_TOO_LOW"


@pytest.mark.parametrize(
    "parts",
    [(n,) for n in SIMULATOR_FIXTURES if n not in EXPECTED_PARTIAL_FILL]
    + [("baselines", n) for n in sorted(BASELINE_SETS)],
    ids=lambda p: "/".join(p),
)
def test_fixture_cost_dict_binds_its_registry_set(parts: tuple[str, ...]) -> None:
    """The fixture's own cost dict binds the registry set it names (no rebinding)."""
    from src.backtest.binding import assert_cost_model_binds_registry
    from src.backtest.costs import build_cost_model

    case = _load_case(*parts)
    parameter_set = load_parameter_set(case["strategy_id"], case["parameter_set_id"])
    # The two partial-fill fixtures deliberately differ from the registry
    # (partial_fill_fraction 0 / 0.5) and are excluded from this parametrization.
    assert_cost_model_binds_registry(parameter_set, build_cost_model(dict(case["cost_model"])))


def test_geometry_guard_would_reject_old_tight_stops() -> None:
    """The arithmetic must fail for the pre-Phase-12 geometry (0.06 percent stop)."""
    price = Decimal("121.5")
    stop = price * (Decimal("1") - Decimal("0.0006"))
    stop_rate = (price - stop) / price
    assert stop_rate < MIN_STOP_RATE
    cost = price * ENTRY_RATE + stop * EXIT_RATE
    assert cost / ((price - stop) + cost) > MAX_COST_TO_RISK


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gen_phase6_fixtures", REPO_ROOT / "scripts" / "gen_phase6_fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_generator_is_deterministic_and_matches_committed_fixtures(
    tmp_path: Path,
) -> None:
    generator = _load_generator()
    generator.FIXTURE_ROOT = tmp_path / "first"
    generator.main()
    generator.FIXTURE_ROOT = tmp_path / "second"
    generator.main()
    first = _snapshot_tree(tmp_path / "first")
    second = _snapshot_tree(tmp_path / "second")
    assert first == second
    assert first, "generator wrote nothing"
    for rel, data in first.items():
        committed = (PHASE6_FIXTURES_DIR / rel).read_bytes()
        assert committed == data, f"committed fixture {rel} differs from generator output"
