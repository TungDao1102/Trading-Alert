"""Pre-flight geometry guard for the Phase 6 simulator fixtures (Phase 12-04, Phase 14-12).

The old generator built 1H bars with a 0.05 half-range, which gives ATR-derived
stops 0.06 to 0.26 percent away from entry. The Phase 12 cost guards (minimum
stop distance 0.3 percent, cost-to-risk ceiling 0.15) would reject such a plan
before sizing, so the fixtures would silently stop producing trades.

This module recomputes each fixture's plan geometry with the EXISTING strategy
and planner, then checks the guard thresholds with independent literal
arithmetic. It deliberately does NOT import ``src.risk.cost_rates`` or
``src.backtest.costs`` to compute expectations: a producer bug must not be able
to bless its own fixtures (threat T-12-09).

Phase 14 (plan 14-12, D-24, D-25): every generated input is a case-input v2 dict.
The 1m data of a case starts at bar N+1 (never inside the signal bar), the funding
rows cover the data window, and the v1 per-bar simulator code is gone.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from src.backtest.case import CASE_INPUT_SCHEMA, REMOVED_V1_KEYS, parse_case_input
from src.backtest.semantics import FUNDING_CONVENTION
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import MarketSnapshot
from src.domain.registry import load_parameter_set

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE6_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase6"
PHASE7_PARITY_INPUT = (
    Path(__file__).parent / "fixtures" / "phase7" / "parity_overlapping_history" / "input.json"
)

SIMULATOR_FIXTURES = (
    "intrabar_both_touched",
    "intrabar_both_touched_short",
    "intrabar_missing_fallback",
    "limit_touch_no_fill",
    "limit_partial_fill",
    "limit_expiry",
    "invalidation_cancels_entry",
)

# Close of the trigger (signal) bar of every phase 6 case: bar 249 of the 1h series that
# starts 2026-09-01 00:00 UTC. A 1m row of a v2 fixture may never open before this instant
# (D-24, F-602).
TRIGGER_CLOSE = datetime(2026, 9, 11, 9, 59, 59, tzinfo=UTC)

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
    "funding_convention",
    "funding_treatment",
    "slippage_model",
    "spread_fill_assumptions",
    "partial_fill_fraction",
}
EXPECTED_PARTIAL_FILL = {
    "limit_partial_fill": "0.5",
}

BASELINE_SETS = {
    "no_trade": "baseline-no-trade-v3",
    "simple_trend": "baseline-simple-trend-v3",
}


def _load_case(*parts: str) -> dict[str, Any]:
    path = PHASE6_FIXTURES_DIR.joinpath(*parts, "input.json")
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _plan_for(case: dict[str, Any]) -> tuple[str, Any]:
    """Return (direction, plan_result) for the trigger bar (the bar closing at TRIGGER_CLOSE).

    Mirrors the engine's strategy front-end: closed setup candles up to the trigger bar,
    closed context candles at or before it, the registry set named by the fixture. The case
    is read through the v2 parser, so a v1-shaped fixture fails here.
    """
    parsed = parse_case_input(case)
    strategy_bars = [b for b in parsed.strategy_bars if b.close_time_utc <= TRIGGER_CLOSE]
    context_bars = [c for c in parsed.context_bars if c.close_time_utc <= TRIGGER_CLOSE]
    last = strategy_bars[-1]
    assert last.close_time_utc == TRIGGER_CLOSE
    snapshot = MarketSnapshot(
        symbol=last.symbol,
        setup_candles=strategy_bars,
        context_candles=context_bars,
        source_timeframe="1h",
    )
    account_state = parsed.account_state
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
    # Phase 14 (D-16): the sign convention joins cost identity; the fixture value
    # must equal the code constant the registry slice appends.
    assert cost["funding_convention"] == FUNDING_CONVENTION
    assert cost["funding_treatment"] == "ADDITIVE"
    assert cost["slippage_model"] == "FIXED_BPS"
    assert cost["spread_fill_assumptions"] == "FULL_FILL"
    assert cost["partial_fill_fraction"] == EXPECTED_PARTIAL_FILL.get(name, "1.0")


@pytest.mark.parametrize("name", SIMULATOR_FIXTURES)
def test_fixture_clears_both_cost_guards(name: str) -> None:
    _assert_guard_clearance(_load_case(name))


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
    # The partial-fill fixture deliberately differs from the registry
    # (partial_fill_fraction 0.5) and is excluded from this parametrization.
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
        str(p.relative_to(root)).replace("\\", "/"): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_generator_is_deterministic_and_matches_committed_fixtures(
    tmp_path: Path,
) -> None:
    generator = _load_generator()
    generator.FIXTURE_ROOT = tmp_path / "first"
    generator.PHASE7_FIXTURE_ROOT = tmp_path / "first_phase7"
    generator.main()
    generator.FIXTURE_ROOT = tmp_path / "second"
    generator.PHASE7_FIXTURE_ROOT = tmp_path / "second_phase7"
    generator.main()
    first = _snapshot_tree(tmp_path / "first")
    second = _snapshot_tree(tmp_path / "second")
    assert first == second
    assert first, "generator wrote nothing"
    for rel, data in first.items():
        committed = (PHASE6_FIXTURES_DIR / rel).read_bytes()
        assert committed == data, f"committed fixture {rel} differs from generator output"
    first_phase7 = _snapshot_tree(tmp_path / "first_phase7")
    assert first_phase7 == _snapshot_tree(tmp_path / "second_phase7")
    assert set(first_phase7) == {"parity_overlapping_history/input.json"}
    assert PHASE7_PARITY_INPUT.read_bytes() == first_phase7["parity_overlapping_history/input.json"]


# --------------------------------------------------------------------------- #
# Phase 14 (plan 14-12): every generated case is a v2 case with no 1m data inside the
# signal bar (D-24, F-602), and the v1 per-bar simulator code is gone (D-01).
# --------------------------------------------------------------------------- #

ALL_V2_CASES: list[tuple[str, ...]] = [(n,) for n in SIMULATOR_FIXTURES] + [
    ("baselines", n) for n in sorted(BASELINE_SETS)
]


def _all_generated_inputs() -> list[Any]:
    params = [pytest.param(parts, id="/".join(parts)) for parts in ALL_V2_CASES]
    params.append(pytest.param(("phase7", "parity_overlapping_history"), id="phase7/parity"))
    return params


def _load_generated(parts: tuple[str, ...]) -> dict[str, Any]:
    if parts[0] == "phase7":
        loaded: dict[str, Any] = json.loads(PHASE7_PARITY_INPUT.read_text(encoding="utf-8"))
        return loaded
    return _load_case(*parts)


@pytest.mark.parametrize("parts", _all_generated_inputs())
def test_generated_case_is_a_v2_case_the_parser_accepts(parts: tuple[str, ...]) -> None:
    case = _load_generated(parts)
    assert case["case_input_schema"] == CASE_INPUT_SCHEMA == "backtest-case/2"
    assert not set(REMOVED_V1_KEYS) & set(case)
    parsed = parse_case_input(case)
    assert parsed.minute_source is not None
    assert parsed.allowed_gaps == ()


@pytest.mark.parametrize("parts", _all_generated_inputs())
def test_no_minute_row_opens_inside_the_signal_bar(parts: tuple[str, ...]) -> None:
    """1m data covers bar N+1 onward: every row opens at or after the trigger bar close (D-24)."""
    case = _load_generated(parts)
    for series in ("trade_bars_1m", "mark_bars_1m"):
        rows = case[series]
        assert rows, f"{series} is empty"
        for row in rows:
            opened = datetime.fromisoformat(row["open_time_utc"])
            closed = datetime.fromisoformat(row["close_time_utc"])
            assert opened >= TRIGGER_CLOSE, f"{series} row {opened} opens inside the signal bar"
            assert closed > TRIGGER_CLOSE, f"{series} row {closed} closes inside the signal bar"


@pytest.mark.parametrize("parts", _all_generated_inputs())
def test_funding_rows_cover_the_data_window(parts: tuple[str, ...]) -> None:
    case = _load_generated(parts)
    window_start = datetime.fromisoformat(case["data_window"]["start_utc"])
    window_end = datetime.fromisoformat(case["data_window"]["end_utc"])
    times = sorted(datetime.fromisoformat(r["funding_time_utc"]) for r in case["funding"])
    assert times[0] <= window_start and times[-1] >= window_end
    gaps = [later - earlier for earlier, later in zip(times, times[1:], strict=False)]
    assert max(gaps).total_seconds() <= 8 * 3600


def test_simulator_module_has_no_v1_per_bar_code() -> None:
    import src.backtest as backtest_package
    import src.backtest.simulator as simulator

    for name in (
        "resolve_intrabar",
        "IntrabarOutcome",
        "SimulatorResult",
        "_resolve_entry",
        "_make_record",
        "_make_filled_record",
        "_patch_record_metadata",
        "_apply_costs",
        "_parse_intrabar_map",
        "_parse_candle",
        "_entry_now_utc",
    ):
        assert not hasattr(simulator, name), name
        assert not hasattr(backtest_package, name), name
    assert simulator.run.__module__ == "src.backtest.simulator"
