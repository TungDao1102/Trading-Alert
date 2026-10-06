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

import copy
import functools
import importlib.util
import json
import tomllib
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
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


def _lf(data: bytes) -> bytes:
    """Line endings normalized to LF (F12): a Windows checkout may hold CRLF working files.

    The generator writes explicit LF bytes, and git stores LF, but `core.autocrlf` rewrites the
    working tree to CRLF on Windows. The comparison is about content, not about the checkout's
    line-ending convention, so both sides are normalized before they are compared.
    """
    return data.replace(b"\r\n", b"\n")


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
        committed = _lf((PHASE6_FIXTURES_DIR / rel).read_bytes())
        assert committed == _lf(data), f"committed fixture {rel} differs from generator output"
    first_phase7 = _snapshot_tree(tmp_path / "first_phase7")
    assert first_phase7 == _snapshot_tree(tmp_path / "second_phase7")
    assert set(first_phase7) == {"parity_overlapping_history/input.json"}
    assert _lf(PHASE7_PARITY_INPUT.read_bytes()) == _lf(
        first_phase7["parity_overlapping_history/input.json"]
    )


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


# --------------------------------------------------------------------------- #
# Phase 15 (plan 15-10, D-19, D-26, F12): the v6 payloads of `build_v6_payloads()`.
#
# Nothing below reads a committed fixture: the payloads exist only in memory until plan 15-12
# writes them. Every expectation is recomputed here with this module's own loops and literal
# arithmetic (pivot search, Wilder ATR, zone, entry range, stop, TP1, RR, guard figures); the
# parameter values come from the registry TOML files through `tomllib`, never through the
# registry loader, so a producer bug cannot bless its own payloads (threat T-15-27).
# --------------------------------------------------------------------------- #

PARAMS_DIR = REPO_ROOT / "params" / "trend-pullback"

V6_LONG = "phase6/intrabar_both_touched/input.json"
V6_SHORT = "phase6/intrabar_both_touched_short/input.json"
V6_MISSING_FALLBACK = "phase6/intrabar_missing_fallback/input.json"
V6_TOUCH_NO_FILL = "phase6/limit_touch_no_fill/input.json"
V6_PARTIAL_FILL = "phase6/limit_partial_fill/input.json"
V6_EXPIRY = "phase6/limit_expiry/input.json"
V6_INVALIDATION = "phase6/invalidation_cancels_entry/input.json"
V6_NO_TRADE = "phase6/baselines/no_trade/input.json"
V6_SIMPLE_TREND = "phase6/baselines/simple_trend/input.json"
V6_PARITY = "phase7/parity_overlapping_history/input.json"

V6_CANDIDATE_KEYS = (
    V6_LONG,
    V6_SHORT,
    V6_MISSING_FALLBACK,
    V6_TOUCH_NO_FILL,
    V6_PARTIAL_FILL,
    V6_EXPIRY,
    V6_INVALIDATION,
    V6_PARITY,
)
V6_BASELINE_KEYS = {
    V6_NO_TRADE: "baseline-no-trade-v4",
    V6_SIMPLE_TREND: "baseline-simple-trend-v4",
}
V6_KEYS = (V6_LONG,)
V6_PARTIAL_FILL_FRACTIONS = {V6_PARTIAL_FILL: "0.5"}
# The trigger payloads whose planner geometry is recomputed, with the registry set each uses.
V6_GEOMETRY_CASES = {
    "long": (V6_LONG, "baseline-v6", False),
}
TRIGGER_INDEX = 249  # bar 249 of the 1h series closes at TRIGGER_CLOSE


@functools.cache
def _v6_cache() -> dict[str, dict[str, Any]]:
    return _load_generator().build_v6_payloads()


def _v6(key: str) -> dict[str, Any]:
    """A private copy of one v6 payload (the cache is never handed out)."""
    return copy.deepcopy(_v6_cache()[key])


def _d(value: object) -> Decimal:
    return Decimal(str(value))


def _toml_params(set_id: str) -> dict[str, Any]:
    text = (PARAMS_DIR / f"{set_id}.toml").read_text(encoding="utf-8")
    parameters: dict[str, Any] = tomllib.loads(text)["parameters"]
    return parameters


def _stored(value: Decimal) -> Decimal:
    """The NUMERIC(38,18) spelling the planner stores (ROUND_HALF_EVEN at 18 places)."""
    with localcontext() as ctx:
        ctx.prec = 60
        return value.quantize(Decimal("1e-18"), rounding=ROUND_HALF_EVEN)


class _Bars:
    """Highs, lows and closes of a payload's strategy bars up to the trigger bar."""

    def __init__(self, payload: dict[str, Any]) -> None:
        rows = [
            r
            for r in payload["strategy_bars"]
            if datetime.fromisoformat(r["close_time_utc"]) <= TRIGGER_CLOSE
        ]
        assert len(rows) == TRIGGER_INDEX + 1
        self.high = [_d(r["high"]) for r in rows]
        self.low = [_d(r["low"]) for r in rows]
        self.close = [_d(r["close"]) for r in rows]


def _own_atr_series(bars: _Bars, period: int = 14) -> list[Decimal | None]:
    """Wilder ATR: SMA seed of the first `period` true ranges, then (n-1)/n smoothing."""
    with localcontext() as ctx:
        ctx.prec = 28
        true_ranges = [bars.high[0] - bars.low[0]]
        for i in range(1, len(bars.close)):
            prev_close = bars.close[i - 1]
            true_ranges.append(
                max(
                    bars.high[i] - bars.low[i],
                    abs(bars.high[i] - prev_close),
                    abs(bars.low[i] - prev_close),
                )
            )
        seed = sum(true_ranges[:period], Decimal(0)) / period
        series: list[Decimal | None] = [None] * (period - 1) + [seed]
        atr = seed
        for tr in true_ranges[period:]:
            atr = ((period - 1) * atr + tr) / period
            series.append(atr)
        return series


def _own_pivot(
    values: list[Decimal], i: int, *, high: bool, left: int, right: int, lookback: int
) -> tuple[int, Decimal] | None:
    """Newest confirmed fractal pivot at bar `i` (reads values[0..i] only).

    Tie rule: non-strict on the left, strict on the right (low: `<=` and `<`; high: `>=` and
    `>`). A candidate `t` needs `t + right <= i` and lies in `[max(left, i - lookback + 1),
    i - right]`, newest first.
    """
    for t in range(i - right, max(left, i - lookback + 1) - 1, -1):
        left_ok = all(
            values[t] >= values[j] if high else values[t] <= values[j] for j in range(t - left, t)
        )
        right_ok = all(
            values[t] > values[j] if high else values[t] < values[j]
            for j in range(t + 1, t + right + 1)
        )
        if left_ok and right_ok:
            return t, values[t]
    return None


def _own_geometry(
    payload: dict[str, Any], params: dict[str, Any], *, short: bool
) -> dict[str, Any]:
    """Every trigger-bar figure of the corrected Family A geometry, by literal arithmetic."""
    bars = _Bars(payload)
    left, right = int(params["pivot_left_bars"]), int(params["pivot_right_bars"])
    lookback = int(params["swing_lookback"])
    tol, buffer_atr = _d(params["zone_tolerance_atr"]), _d(params["entry_buffer_atr"])
    sl_atr = _d(params["sl_buffer_atr"])
    atr = _own_atr_series(bars)[TRIGGER_INDEX]
    assert atr is not None
    pivot = _own_pivot(
        bars.high if short else bars.low,
        TRIGGER_INDEX,
        high=short,
        left=left,
        right=right,
        lookback=lookback,
    )
    target = _own_pivot(
        bars.low if short else bars.high,
        TRIGGER_INDEX,
        high=not short,
        left=left,
        right=right,
        lookback=lookback,
    )
    assert pivot is not None and target is not None
    with localcontext() as ctx:
        ctx.prec = 28
        half, entry_buffer, sl_buffer = tol * atr, buffer_atr * atr, sl_atr * atr
        level = pivot[1]
        zone_lower, zone_upper = level - half, level + half
        entry_min = _stored(zone_lower - entry_buffer)
        entry_max = _stored(zone_upper + entry_buffer)
        stop = _stored(
            zone_upper + entry_buffer + sl_buffer
            if short
            else zone_lower - entry_buffer - sl_buffer
        )
        tp1 = _stored(target[1])
        entry_ref = (entry_min + entry_max) / 2
        risk = abs(entry_ref - stop)
        leg = entry_ref - tp1 if short else tp1 - entry_ref
        tp2 = _stored(entry_ref - 2 * leg if short else entry_ref + 2 * leg)
        edge = entry_min if short else entry_max
        distance = abs(edge - stop)
        cost = edge * ENTRY_RATE + stop * EXIT_RATE
    return {
        "atr": atr,
        "pivot_index": pivot[0],
        "pivot": level,
        "target_index": target[0],
        "zone": (zone_lower, zone_upper),
        "entry_min": entry_min,
        "entry_max": entry_max,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "entry_ref": entry_ref,
        "risk": risk,
        "rr": leg / risk,
        "leg": leg,
        "stop_rate": distance / edge,
        "cost_to_risk": cost / (distance + cost),
        "trigger_extreme": bars.high[-1] if short else bars.low[-1],
        "min_stop": _d(params["min_stop_atr"]) * atr,
        "left": left,
        "right": right,
        "lookback": lookback,
        "outer_edge": zone_upper + entry_buffer if short else zone_lower - entry_buffer,
        "sl_buffer": sl_buffer,
    }


def _earlier_bars_that_touch(
    payload: dict[str, Any], params: dict[str, Any], *, short: bool
) -> list[int]:
    """Bars 0..248 whose extreme lies inside the zone of the pivot known at that bar's close."""
    bars = _Bars(payload)
    atr_series = _own_atr_series(bars)
    tol = _d(params["zone_tolerance_atr"])
    touching: list[int] = []
    for i in range(TRIGGER_INDEX):
        atr = atr_series[i]
        if atr is None:
            continue
        pivot = _own_pivot(
            bars.high if short else bars.low,
            i,
            high=short,
            left=int(params["pivot_left_bars"]),
            right=int(params["pivot_right_bars"]),
            lookback=int(params["swing_lookback"]),
        )
        if pivot is None:
            continue
        half = tol * atr
        extreme = bars.high[i] if short else bars.low[i]
        if pivot[1] - half <= extreme <= pivot[1] + half:
            touching.append(i)
    return touching


def test_build_v6_payloads_is_pure_and_returns_every_case() -> None:
    """Two calls return equal dicts keyed by the output path relative to tests/fixtures."""
    first = _load_generator().build_v6_payloads()
    second = _load_generator().build_v6_payloads()
    assert first == second
    assert set(first) == set(V6_KEYS)


def _walk_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for child in value.values():
            found |= _walk_keys(child)
        return found
    if isinstance(value, list):
        found = set()
        for child in value:
            found |= _walk_keys(child)
        return found
    return set()


@pytest.mark.parametrize("key", V6_KEYS)
def test_v6_payload_carries_its_identity_and_never_a_parameters_key(key: str) -> None:
    case = _v6(key)
    expected_set = V6_BASELINE_KEYS.get(key, "baseline-v6")
    assert case["parameter_set_id"] == expected_set
    assert case["strategy_id"] == "trend-pullback"
    assert case["strategy_version"] == "v5.0.0"
    assert not {"parameters", "parameters_json"} & _walk_keys(case)
    assert set(case["cost_model"]) == EXPECTED_COST_KEYS
    assert case["cost_model"]["partial_fill_fraction"] == V6_PARTIAL_FILL_FRACTIONS.get(key, "1.0")
    assert case["cost_model"]["funding_convention"] == FUNDING_CONVENTION


@pytest.mark.parametrize(
    "set_id", ["baseline-v6", "baseline-no-trade-v4", "baseline-simple-trend-v4"]
)
def test_v6_cost_dict_equals_the_ratified_cost_values(set_id: str) -> None:
    """The one canonical cost literal COST_MODEL equals every ratified cost value (15-08)."""
    params = _toml_params(set_id)
    cost = _v6(V6_LONG)["cost_model"]
    for key in (
        "fee_rate_entry",
        "fee_rate_exit",
        "expected_slippage",
        "exit_slippage_rate",
        "partial_fill_fraction",
    ):
        assert _d(cost[key]) == _d(params[key]), key
    for key in ("funding_treatment", "slippage_model", "spread_fill_assumptions"):
        assert cost[key] == params[key], key


@pytest.mark.parametrize("key", [k for k in V6_KEYS if k not in V6_PARTIAL_FILL_FRACTIONS])
def test_v6_cost_dict_binds_its_registry_set(key: str) -> None:
    """The payload's own cost dict binds the registry set it names (no rebinding)."""
    from src.backtest.binding import assert_cost_model_binds_registry
    from src.backtest.costs import build_cost_model

    case = _v6(key)
    parameter_set = load_parameter_set(case["strategy_id"], case["parameter_set_id"])
    assert_cost_model_binds_registry(parameter_set, build_cost_model(dict(case["cost_model"])))


@pytest.mark.parametrize("name", sorted(V6_GEOMETRY_CASES))
def test_v6_trigger_geometry_matches_independent_arithmetic(name: str) -> None:
    """Pivot, ATR, zone, entry range, stop, TP1, RR and both guard figures, recomputed here."""
    key, set_id, short = V6_GEOMETRY_CASES[name]
    params = _toml_params(set_id)
    case = _v6(key)
    geo = _own_geometry(case, params, short=short)

    # The pivot sits inside the search window and was confirmed no later than bar 248.
    assert geo["pivot_index"] + geo["right"] <= 248
    assert geo["pivot_index"] >= TRIGGER_INDEX - geo["lookback"] + 1
    assert geo["target_index"] + geo["right"] <= 248
    # The trigger bar touches the pivot zone without trading through the stop.
    zone_lower, zone_upper = geo["zone"]
    assert zone_lower <= geo["trigger_extreme"] <= zone_upper
    if short:
        assert geo["stop"] > geo["entry_max"]
        assert geo["trigger_extreme"] < geo["stop"]
        assert geo["tp1"] < geo["entry_ref"]
    else:
        assert geo["stop"] < geo["entry_min"]
        assert geo["trigger_extreme"] > geo["stop"]
        assert geo["tp1"] > geo["entry_ref"]
    # The stop lies one sl_buffer beyond the outer edge of the whole entry zone.
    beyond = geo["outer_edge"] + geo["sl_buffer"] if short else geo["outer_edge"] - geo["sl_buffer"]
    assert abs(geo["stop"] - beyond) <= Decimal("1e-17")
    # min_stop_atr distance and the Phase 12 guards.
    assert geo["risk"] >= geo["min_stop"]
    assert geo["stop_rate"] >= MIN_STOP_RATE
    assert geo["stop_rate"] >= CEILING_BINDING_STOP_RATE
    assert geo["cost_to_risk"] <= MAX_COST_TO_RISK
    # The RR gate: a candidate clears minimum_rr, the no-trade baseline cannot.
    minimum_rr = _d(params["minimum_rr"])
    if name == "no_trade":
        assert geo["rr"] < minimum_rr
        assert geo["rr"] > 0, "TP1 is on the profit side, so only the RR gate rejects"
    else:
        assert geo["rr"] >= minimum_rr
    # No earlier bar touches the zone of the pivot known at its close.
    assert _earlier_bars_that_touch(case, params, short=short) == []

    # The real strategy and planner give the same figures.
    direction, result = _plan_for(case)
    assert direction == ("SHORT" if short else "LONG")
    if name == "no_trade":
        assert result.is_no_trade and result.reason_code == "RR_TOO_LOW"
        return
    assert not result.is_no_trade, result.reason_code
    trade_plan = result.trade_plan
    assert trade_plan is not None
    assert trade_plan.entry_min_price == geo["entry_min"]
    assert trade_plan.entry_max_price == geo["entry_max"]
    assert trade_plan.stop_loss_price == geo["stop"]
    take_profit = json.loads(trade_plan.take_profit_json)
    assert Decimal(take_profit["tp1"]) == geo["tp1"]
    assert Decimal(take_profit["tp2"]) == geo["tp2"]
    rr = json.loads(trade_plan.expected_rr_json)
    assert Decimal(rr["tp1_rr"]) == geo["rr"]
    stop_rate, cost_to_risk = _assert_guard_clearance(case)
    assert stop_rate == geo["stop_rate"]
    assert cost_to_risk == geo["cost_to_risk"]


@pytest.mark.parametrize("key", V6_KEYS)
def test_v6_payload_is_a_v2_case_the_parser_accepts(key: str) -> None:
    case = _v6(key)
    assert case["case_input_schema"] == CASE_INPUT_SCHEMA == "backtest-case/2"
    assert not set(REMOVED_V1_KEYS) & set(case)
    parsed = parse_case_input(case)
    assert parsed.minute_source is not None
    assert parsed.allowed_gaps == ()


@pytest.mark.parametrize("key", V6_KEYS)
def test_v6_no_minute_row_opens_inside_the_signal_bar(key: str) -> None:
    """1m data covers bar N+1 onward: every row opens at or after the trigger bar close (D-24)."""
    case = _v6(key)
    for series in ("trade_bars_1m", "mark_bars_1m"):
        rows = case[series]
        assert rows, f"{series} is empty"
        for row in rows:
            opened = datetime.fromisoformat(row["open_time_utc"])
            closed = datetime.fromisoformat(row["close_time_utc"])
            assert opened >= TRIGGER_CLOSE, f"{series} row {opened} opens inside the signal bar"
            assert closed > TRIGGER_CLOSE, f"{series} row {closed} closes inside the signal bar"


@pytest.mark.parametrize("key", V6_KEYS)
def test_v6_funding_rows_cover_the_data_window(key: str) -> None:
    case = _v6(key)
    window_start = datetime.fromisoformat(case["data_window"]["start_utc"])
    window_end = datetime.fromisoformat(case["data_window"]["end_utc"])
    times = sorted(datetime.fromisoformat(r["funding_time_utc"]) for r in case["funding"])
    assert times[0] <= window_start and times[-1] >= window_end
    gaps = [later - earlier for earlier, later in zip(times, times[1:], strict=False)]
    assert max(gaps).total_seconds() <= 8 * 3600
