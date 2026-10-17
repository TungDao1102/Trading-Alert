"""End-to-end tests for the public backtest entry point `simulator.run` (v2 engine).

Phase 14, plan 14-12 (D-01, D-25): `run` delegates to the event-loop engine
(`src.backtest.engine.simulate`) with the module-global `evaluate_risk`. Every test loads a
regenerated phase 6 case-input v2 (`tests/fixtures/phase6/<case>/input.json`, 1m trade and
mark minutes start at 10:00, after the 09:59:59 signal bar close) and asserts the scenario
outcome. The phase 6 cases are REGRESSION SNAPSHOTS (D-25, F-608): their outputs are pinned
from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14
(see tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md). The cost arithmetic in the end-to-end
tests below is nevertheless recomputed from literal rates, so a producer bug cannot bless
itself.

Tests of the deleted v1 helpers are gone; each deleted test names its replacement here:

* `resolve_intrabar` empty and None intrabar (CR-01) -> tests/test_backtest_exits.py
  (test_hole_resolves_the_rest_of_the_hour_at_the_bar_close_with_stop_first,
  test_fallback_in_the_fill_bar_resolves_only_the_stop) and the fixture
  `intrabar_missing_fallback` below.
* `_make_record` trade_id binding (CR-02) -> tests/test_backtest_engine.py (a second plan
  gets another trade_id) and tests/test_backtest_lifecycle.py
  (test_tracer_state_becomes_a_validated_v2_trade_record); the full-versus-partial fill
  anchor is kept below (test_full_and_partial_fill_of_the_same_plan_have_different_trade_ids).
* `_apply_costs` per-leg oracles, TP1 rate, legacy refusal, unknown exit kind, unfilled
  pass-through -> tests/test_backtest_records.py
  (test_bookings_sum_to_realized_pnl_for_every_exit_kind,
  test_end_of_data_leg_uses_exit_slippage_rate_and_tp2_uses_expected_slippage,
  test_a_legacy_cost_model_without_exit_slippage_rate_is_refused,
  test_build_trade_record_refuses_an_exit_kind_outside_sl_tp2_end_of_data) and the
  hand-recomputed end-to-end tests below.
* the per-bar `intrabar_1m_map` no-lookahead test -> tests/test_backtest_lifecycle.py
  (test_minutes_at_or_before_the_signal_close_are_never_examined) and the two no-lookahead
  tests below.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.binding import CostModelBindingMismatch
from src.backtest.case import parse_case_input
from src.backtest.series import ListMinuteSource
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import MarketSnapshot
from src.domain.canonical import sha256_hex
from src.domain.registry import load_parameter_set

from tests.test_phase6_fixture_scenarios import V6_SCENARIOS

PHASE6_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase6"
TRIGGER_CLOSE = datetime(2026, 9, 11, 9, 59, 59, tzinfo=UTC)
REGRESSION_DOC = PHASE6_FIXTURES_DIR / "REGRESSION_SNAPSHOTS.md"

CASES = (
    "intrabar_both_touched",
    "intrabar_both_touched_short",
    "intrabar_missing_fallback",
    "limit_touch_no_fill",
    "limit_partial_fill",
    "limit_expiry",
    "invalidation_cancels_entry",
)
BASELINES = ("no_trade", "simple_trend")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((case_dir / "input.json").read_text(encoding="utf-8"))
    return loaded


def _case(name: str) -> dict[str, Any]:
    return _load_input(PHASE6_FIXTURES_DIR / name)


def _digest(output: dict[str, Any]) -> str:
    """sha256 of the whole run output (trades, run_summary and the identity fields)."""
    return sha256_hex(output)


def _replan(case_input: dict[str, Any]) -> tuple[Any, str]:
    """Re-run strategy + planner over the trigger bar (independent of the engine and costs).

    Returns the TradePlan and the direction of the plan the fixture produces at the trigger
    bar, so expected values come from plan prices and literal rates.
    """
    parsed = parse_case_input(case_input)
    bars = [b for b in parsed.strategy_bars if b.close_time_utc <= TRIGGER_CLOSE]
    context = [c for c in parsed.context_bars if c.close_time_utc <= TRIGGER_CLOSE]
    pset = load_parameter_set(case_input["strategy_id"], case_input["parameter_set_id"])
    snapshot = MarketSnapshot(
        symbol=bars[-1].symbol,
        setup_candles=bars,
        context_candles=context,
        source_timeframe="1h",
    )
    setup = evaluate(
        snapshot=snapshot,
        account_state=parsed.account_state,
        strategy_version=case_input["strategy_version"],
        parameter_set=pset,
    )
    assert not setup.is_no_trade
    signal = setup.signal
    assert signal is not None
    result = plan(
        signal=signal,
        setup_candles=bars,
        parameter_set=pset,
        account_state=parsed.account_state,
        created_at_utc=bars[-1].close_time_utc,
    )
    assert not result.is_no_trade
    assert result.trade_plan is not None
    return result.trade_plan, signal.direction


def _sized_modeled_costs(case_input: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Decimal:
    """Run the case and return the modeled cost per unit the FIRST risk call sized with.

    v2 filled records do not carry `modeled_costs_per_unit` (it is None on them), so the
    sizing figure is read from the verdict `evaluate_risk` returned to the engine: the spy
    wraps the module-global the engine resolves at call time.
    """
    import src.backtest.simulator as simulator

    verdicts: list[Any] = []
    real = simulator.evaluate_risk

    def spy(**kwargs: Any) -> Any:
        verdict = real(**kwargs)
        verdicts.append(verdict)
        return verdict

    monkeypatch.setattr(simulator, "evaluate_risk", spy)
    simulator.run(case_input)
    assert verdicts and verdicts[0].sized is not None
    value = verdicts[0].sized.modeled_costs_per_unit
    assert isinstance(value, Decimal)
    return value


# --------------------------------------------------------------------------- #
# Scenario outcomes of the seven phase 6 cases (regression snapshots, D-25).
# --------------------------------------------------------------------------- #


def test_intrabar_both_touched_long_resolves_sl_first() -> None:
    """The plan fills at 10:05 (a one-tick trade-through of the 117.80 limit), then one mark
    minute touches both the stop (116.50) and TP1 (123.20): the stop wins (D-12)."""
    from src.backtest.simulator import run

    trades = run(_case("intrabar_both_touched"))["trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_kind"] == "ENTRY_FILLED"
    assert trade["entry_price"] == "117.80"
    assert trade["entry_time_utc"] == "2026-09-11T10:05:59+00:00"
    assert trade["exit_kind"] == "SL"
    assert trade["exit_price"] == "116.50"
    assert trade["exit_time_utc"] == "2026-09-11T10:06:59+00:00"
    assert trade["tp1_quantity"] is None
    assert trade["fallback_applied"] is False
    assert trade["coverage_note"] is None
    # D-01: the fill happens after the signal bar closed.
    assert trade["signal_close_utc"] == TRIGGER_CLOSE.isoformat()
    assert trade["entry_time_utc"] > trade["signal_close_utc"]


def test_intrabar_both_touched_short_resolves_sl_first() -> None:
    """Mirror: SHORT limit 132.20 fills on a trade high of 132.30; stop 133.50 beats TP1."""
    from src.backtest.simulator import run

    trades = run(_case("intrabar_both_touched_short"))["trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert trade["direction"] == "SHORT"
    assert trade["entry_kind"] == "ENTRY_FILLED"
    assert trade["entry_price"] == "132.20"
    assert trade["exit_kind"] == "SL"
    assert trade["exit_price"] == "133.50"
    assert trade["fallback_applied"] is False
    assert trade["coverage_note"] is None


def test_intrabar_missing_mark_series_resolves_at_the_bar_close_with_a_flag() -> None:
    """The mark series has a hole from 10:06: the rest of bar 250 resolves once at its close
    from the bar range, stop first, flagged (never synthesized minute prices, D-12).

    On the corrected geometry the stop lies beyond the zone edge, so a bar range that reaches
    the stop is outside the zone and bar 250 raises no follow-up setup: one record (15-10
    facts, "What changed against the baseline-v5 fixtures").
    """
    from src.backtest.simulator import run

    output = run(_case("intrabar_missing_fallback"))
    trades = output["trades"]
    assert [t["entry_kind"] for t in trades] == ["ENTRY_FILLED"]
    trade = trades[0]
    assert trade["exit_kind"] == "SL"
    assert trade["exit_price"] == "116.50"
    assert trade["exit_time_utc"] == "2026-09-11T10:59:59+00:00"
    assert trade["fallback_applied"] is True
    assert trade["coverage_note"] is not None
    assert trade["coverage_note"].startswith("mark_price_1m_missing_from_2026-09-11T10:06:00")
    assert output["run_summary"]["fallback_count"] == 1


def test_costs_apply_from_run_1_and_realized_pnl_is_the_booked_sum() -> None:
    """realized_pnl = gross - entry_fee - exit_fee - slippage + funding, from run #1 (D-02)."""
    from src.backtest.simulator import run

    trades = run(_case("intrabar_both_touched"))["trades"]
    assert len(trades) == 1
    trade = trades[0]
    gross = Decimal(trade["gross_pnl"])
    entry_fee = Decimal(trade["entry_fee"])
    exit_fee = Decimal(trade["exit_fee"])
    slippage = Decimal(trade["slippage_amount"])
    funding = Decimal(trade["funding_amount"])
    assert Decimal(trade["realized_pnl"]) == gross - entry_fee - exit_fee - slippage + funding
    assert entry_fee > 0 and exit_fee > 0 and slippage > 0


def test_risk_reject_is_first_class_outcome() -> None:
    """A realized-risk or quantization reject is a first-class record with the canonical code."""
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    # Force a NOTIONAL_REJECT by setting min_notional very high.
    case_input["constraint_history"][0]["min_notional"] = "999999"
    trades = run(case_input)["trades"]
    assert len(trades) == 1
    reject = trades[0]
    assert reject["outcome_kind"] == "REJECT"
    assert reject["entry_kind"] == "REJECT"
    assert reject["reason_code"] in {
        "NOTIONAL_REJECT",
        "MIN_QTY_REJECT",
        "UTILIZATION_REJECT",
        "STOP_TOO_TIGHT",
        "COST_TO_RISK_EXCEEDED",
    }


def test_limit_touch_no_fill_counts_touches_and_the_plan_expires() -> None:
    """Three minutes reach the limit exactly but never trade through it: EXPIRED, 3 touches."""
    from src.backtest.simulator import run

    output = run(_case("limit_touch_no_fill"))
    (trade,) = output["trades"]
    assert trade["entry_kind"] == "EXPIRED"
    assert trade["touch_no_fill_count"] == 3
    assert trade["quantity"] is None
    assert trade["planned_quantity"] == "19.303"
    assert trade["resolved_at_utc"] == "2026-09-11T13:59:59+00:00"
    assert output["run_summary"]["touch_no_fill_total"] == 3


def test_limit_partial_fill_fills_half_then_takes_tp1_and_tp2() -> None:
    """partial_fill_fraction 0.5 fills floor(19.303 x 0.5) = 9.651; TP1 takes half of it."""
    from src.backtest.simulator import run

    (trade,) = run(_case("limit_partial_fill"))["trades"]
    assert trade["entry_kind"] == "PARTIAL_FILL"
    assert trade["planned_quantity"] == "19.303"
    assert trade["quantity"] == "9.651"
    assert Decimal(trade["quantity"]) < Decimal(trade["planned_quantity"])
    assert trade["tp1_quantity"] == "4.825"
    assert trade["tp1_price"] == "123.20"
    assert trade["exit_kind"] == "TP2"
    assert trade["exit_price"] == "128.60"


def test_limit_expiry_without_a_touch() -> None:
    """The limit is never reached: EXPIRED at the plan expiry, no touches, no quantity."""
    from src.backtest.simulator import run

    (trade,) = run(_case("limit_expiry"))["trades"]
    assert trade["entry_kind"] == "EXPIRED"
    assert trade["touch_no_fill_count"] == 0
    assert trade["quantity"] is None
    assert trade["resolved_at_utc"] == "2026-09-11T13:59:59+00:00"


def test_invalidation_cancels_the_resting_entry_at_the_next_bar_close() -> None:
    """Bar 250 closes at 116.00, below the invalidation level, while the plan rests.

    Bar 250 raises no follow-up setup on the corrected geometry (15-10 facts): one record.
    """
    from src.backtest.simulator import run

    trades = run(_case("invalidation_cancels_entry"))["trades"]
    assert [t["entry_kind"] for t in trades] == ["INVALIDATION_CANCEL"]
    cancelled = trades[0]
    assert cancelled["quantity"] is None
    assert cancelled["resolved_at_utc"] == "2026-09-11T10:59:59+00:00"


# Regression snapshots (D-25): scenario tuple and a digest of the whole output, both pinned
# from the v2 engine. They are NOT hand-derived. Regenerating the fixtures or changing the
# engine semantics moves them; re-pin by printing `_digest(run(case))` and say why in the
# plan's regeneration inventory. Phase 15 (plan 15-12, D-19, D054): re-pinned on the v6
# fixtures; every scenario tuple equals `V6_SCENARIOS` of tests/test_phase6_fixture_scenarios.py
# (asserted below) and the digests were re-pinned only while that module passed.
REGRESSION_SNAPSHOTS: dict[str, tuple[tuple[str, str | None, bool, int], str]] = {
    # name: ((entry_kind, exit_kind, fallback_applied, touch_no_fill_count), digest)
    "intrabar_both_touched": (
        ("ENTRY_FILLED", "SL", False, 0),
        "d680ad5c27b7fdb9282fed770d248a1afd4fd1d80d80d969cd53318363edf7c6",
    ),
    "intrabar_both_touched_short": (
        ("ENTRY_FILLED", "SL", False, 0),
        "9d3b70d6b873b5b2b50726ddf08f7552200c8276c736d897e3c727211ca64426",
    ),
    "intrabar_missing_fallback": (
        ("ENTRY_FILLED", "SL", True, 0),
        "f15cf66d1a9d44183135973206de38a54bf112fcc6d11f6d208576cd9066c92a",
    ),
    "limit_touch_no_fill": (
        ("EXPIRED", None, False, 3),
        "895714437aee40eda63f1c31be3eadbb32f15e553e87cced900a2826c27e1117",
    ),
    "limit_partial_fill": (
        ("PARTIAL_FILL", "TP2", False, 0),
        "b9e0894ee38f0f10478f3b4779f1a6ffa24c9baedbeb9ca11e5affe4445b5816",
    ),
    "limit_expiry": (
        ("EXPIRED", None, False, 0),
        "8659ac4b3eb923796be57243009f5852834e0c822ceb90fcb8c9370a3a8974f2",
    ),
    "invalidation_cancels_entry": (
        ("INVALIDATION_CANCEL", None, False, 0),
        "1bd01918f0ce151205b2225fb58381c2704f4f690ea2f4115c8665d9b4bf914a",
    ),
    "baselines/no_trade": (
        ("REJECT", None, False, 0),
        "9196d272105b43c7215cb66e9a1d76f66e997e2151ff71f32a288708632caaae",
    ),
    "baselines/simple_trend": (
        ("ENTRY_FILLED", "SL", False, 0),
        "8eafebff30096d51d8657ae6f98aaa1806209dddd8966bdfe1a339fbd5bb5995",
    ),
}


@pytest.mark.parametrize("name", sorted(REGRESSION_SNAPSHOTS))
def test_phase6_case_matches_its_regression_snapshot(name: str) -> None:
    """Regression snapshot: the first record's scenario tuple and the output digest.

    These values were pinned from the v2 engine output (D-25); they guard against silent
    drift of the engine, not against a wrong engine. Hand-derived goldens are in
    tests/fixtures/phase14.
    """
    from src.backtest.simulator import run

    scenario, digest = REGRESSION_SNAPSHOTS[name]
    assert scenario == V6_SCENARIOS[name]
    output = run(_case(name))
    first = output["trades"][0]
    assert (
        first["entry_kind"],
        first["exit_kind"],
        first["fallback_applied"],
        first["touch_no_fill_count"],
    ) == scenario
    assert _digest(output) == digest


# --------------------------------------------------------------------------- #
# Determinism and no-lookahead.
# --------------------------------------------------------------------------- #


def test_run_twice_byte_identical() -> None:
    """Two runs over the same case yield byte-identical outputs."""
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    a = run(case_input)
    b = run(copy.deepcopy(case_input))
    assert _digest(a) == _digest(b)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_minutes_inside_the_signal_bar_are_never_examined() -> None:
    """A junk minute that trades through the limit BEFORE the signal close changes nothing (D-01).

    Added at 09:30, inside the signal bar (09:00 to 09:59:59): a trade low of 1.00 would fill
    the plan at once if the engine read it, and a mark low of 1.00 would stop it.
    """
    from src.backtest.simulator import run

    case_input = _case("limit_expiry")
    baseline = run(case_input)
    poisoned = copy.deepcopy(case_input)
    junk_open = "2026-09-11T09:30:00+00:00"
    junk_close = "2026-09-11T09:30:59+00:00"
    for series, volume in (("trade_bars_1m", "1.0"), ("mark_bars_1m", None)):
        row = {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "open_time_utc": junk_open,
            "close_time_utc": junk_close,
            "open": "100.00",
            "high": "100.00",
            "low": "1.00",
            "close": "100.00",
        }
        if volume is not None:
            row["volume"] = volume
        poisoned[series].insert(0, row)
    assert _digest(run(poisoned)) == _digest(baseline)


def test_minutes_after_the_data_end_change_nothing() -> None:
    """Appending a post-horizon minute (after the data window end) does not change the output."""
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    baseline = run(case_input)
    extended = copy.deepcopy(case_input)
    for series, volume in (("trade_bars_1m", "1.0"), ("mark_bars_1m", None)):
        row = {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "open_time_utc": "2026-09-11T11:30:00+00:00",
            "close_time_utc": "2026-09-11T11:30:59+00:00",
            "open": "99999.00",
            "high": "99999.00",
            "low": "99999.00",
            "close": "99999.00",
        }
        if volume is not None:
            row["volume"] = volume
        extended[series].append(row)
    assert _digest(run(extended)) == _digest(baseline)


# --------------------------------------------------------------------------- #
# Phase 6 fixtures, relabelled as regression snapshots (D-25, F-608).
# --------------------------------------------------------------------------- #


def test_phase6_fixtures_exist_and_are_v2_cases() -> None:
    """Each case directory contains a v2 input.json; none keeps a stale expected file."""
    assert PHASE6_FIXTURES_DIR.is_dir()
    actual_cases = {p.name for p in PHASE6_FIXTURES_DIR.iterdir() if p.is_dir()}
    assert set(CASES).issubset(actual_cases), f"missing phase6 cases: {set(CASES) - actual_cases}"
    for name in CASES:
        assert _case(name)["case_input_schema"] == "backtest-case/2"
        assert not (PHASE6_FIXTURES_DIR / name / "expected.json").exists(), name
    for name in BASELINES:
        assert _load_input(PHASE6_FIXTURES_DIR / "baselines" / name)["case_input_schema"] == (
            "backtest-case/2"
        )
        assert not (PHASE6_FIXTURES_DIR / "baselines" / name / "expected.json").exists()


def test_regression_snapshot_note_names_every_case_and_baseline() -> None:
    text = REGRESSION_DOC.read_text(encoding="utf-8")
    for name in (*CASES, *(f"baselines/{b}" for b in BASELINES)):
        assert name in text, name
    assert text.count("regression snapshot") >= len(CASES) + len(BASELINES)
    assert "tests/fixtures/phase14" in text
    assert "registry_identity" in text and "report_slices" in text


# --------------------------------------------------------------------------- #
# Cost parity: the record's modeled cost is quote per unit at the sizing edge (D-18).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case_name", ["intrabar_missing_fallback", "intrabar_both_touched_short"])
def test_cost_parity_simulator_matches_costs_module(
    case_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The modeled cost the engine sized with equals the public helper and literal arithmetic.

    The plan edge and stop come from re-running the planner in the test; the expected value
    is also written out as literal arithmetic, edge x (0.0005 + 0.0001) + stop x
    (0.0005 + 0.0003), so the test cannot agree with a re-derived buggy formula.
    """
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit

    case_input = _case(case_name)
    cost_model = build_cost_model(case_input["cost_model"])
    sim_costs = _sized_modeled_costs(case_input, monkeypatch)

    trade_plan, direction = _replan(case_input)
    edge = trade_plan.entry_max_price if direction == "LONG" else trade_plan.entry_min_price
    via_helper = modeled_costs_per_unit(
        cost_model=cost_model,
        side=direction,
        entry_price=edge,
        stop_price=trade_plan.stop_loss_price,
    )
    literal = edge * Decimal("0.0006") + trade_plan.stop_loss_price * Decimal("0.0008")
    assert sim_costs == via_helper
    assert sim_costs == literal
    assert sim_costs > Decimal("0.0011"), "must not collapse to the dimensionless rate sum"


_COST8 = {
    "fee_rate_entry": "0.0005",
    "fee_rate_exit": "0.0005",
    "funding_treatment": "ADDITIVE",
    "expected_slippage": "0.0001",
    "slippage_model": "FIXED_BPS",
    "spread_fill_assumptions": "FULL_FILL",
    "partial_fill_fraction": "1.0",
    "exit_slippage_rate": "0.0003",
}

_MODELED_COSTS_ORACLES = [
    ("btc_long", "LONG", "60100", "58780", "83.0840"),
    ("btc_short", "SHORT", "59900", "61300", "84.9800"),
    ("xrp_long", "LONG", "0.5010", "0.4930", "0.000695"),
]


@pytest.mark.parametrize(
    "label,side,entry,stop,expected",
    _MODELED_COSTS_ORACLES,
    ids=[row[0] for row in _MODELED_COSTS_ORACLES],
)
def test_modeled_costs_per_unit_price_aware_oracles(
    label: str, side: str, entry: str, stop: str, expected: str
) -> None:
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit

    got = modeled_costs_per_unit(
        cost_model=build_cost_model(_COST8),
        side=side,
        entry_price=Decimal(entry),
        stop_price=Decimal(stop),
    )
    assert got == Decimal(expected)


def test_modeled_costs_per_unit_is_linear_in_price() -> None:
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit

    model = build_cost_model(_COST8)
    base = modeled_costs_per_unit(
        cost_model=model, side="LONG", entry_price=Decimal("60100"), stop_price=Decimal("58780")
    )
    doubled = modeled_costs_per_unit(
        cost_model=model, side="LONG", entry_price=Decimal("120200"), stop_price=Decimal("117560")
    )
    assert base == Decimal("83.0840")
    assert doubled == Decimal("166.1680")


def test_modeled_costs_per_unit_rejects_bad_side_legacy_model_and_old_call_form() -> None:
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit

    model = build_cost_model(_COST8)
    prices = {"entry_price": Decimal("60100"), "stop_price": Decimal("58780")}
    with pytest.raises(ValueError, match="side"):
        modeled_costs_per_unit(cost_model=model, side="FLAT", **prices)

    legacy = build_cost_model({k: v for k, v in _COST8.items() if k != "exit_slippage_rate"})
    with pytest.raises(ValueError, match="exit_slippage_rate"):
        modeled_costs_per_unit(cost_model=legacy, side="LONG", **prices)

    with pytest.raises(TypeError):
        modeled_costs_per_unit(cost_model=model, side="LONG")  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# Run-level contracts: identity, parse refusals, entry point wiring.
# --------------------------------------------------------------------------- #


def test_full_and_partial_fill_of_the_same_plan_have_different_trade_ids() -> None:
    """The trade_id binds the filled quantity: fraction 1.0 and 0.5 never collide (CR-02)."""
    from src.backtest.simulator import run

    partial_input = _case("limit_partial_fill")
    full_input = copy.deepcopy(partial_input)
    full_input["cost_model"] = dict(full_input["cost_model"], partial_fill_fraction="1.0")
    full_id = run(full_input)["trades"][0]["trade_id"]
    partial_id = run(partial_input)["trades"][0]["trade_id"]
    assert full_id != partial_id


def test_cr10_fixture_strategy_version_bound_to_registry() -> None:
    """CR-10: a case claiming a strategy_version the registry set does not carry fails closed."""
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    case_input["strategy_version"] = "v9.9.9"
    with pytest.raises(ValueError, match="strategy_version"):
        run(case_input)


def test_wr14_float_json_numbers_and_naive_datetimes_rejected() -> None:
    """WR-14: float-typed JSON numbers and naive datetimes fail closed at parse."""
    from src.backtest.simulator import run

    base = _case("intrabar_both_touched")

    float_price = copy.deepcopy(base)
    float_price["strategy_bars"][0]["open"] = 1.1
    with pytest.raises(TypeError):
        run(float_price)

    naive_dt = copy.deepcopy(base)
    naive_dt["strategy_bars"][0]["close_time_utc"] = "2026-09-11T10:00:00"
    with pytest.raises(ValueError):
        run(naive_dt)

    float_account = copy.deepcopy(base)
    float_account["account_state"]["equity"] = 10000.00
    with pytest.raises(TypeError):
        run(float_account)


def test_a_v1_shaped_case_is_refused_naming_the_removed_keys() -> None:
    """The v1 keys (fixture clock, single constraint snapshot, intrabar map) are refused (D-01)."""
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    case_input["intrabar_1m_map"] = {}
    case_input["now_utc"] = "2026-09-11T10:00:00+00:00"
    with pytest.raises(ValueError, match="intrabar_1m_map"):
        run(case_input)


def test_run_resolves_evaluate_risk_from_the_module_globals_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monkeypatching src.backtest.simulator.evaluate_risk intercepts every engine risk call."""
    import src.backtest.simulator as simulator

    real = simulator.evaluate_risk
    seen: list[dict[str, Any]] = []

    def spy(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(simulator, "evaluate_risk", spy)
    output = simulator.run(_case("intrabar_both_touched"))
    assert len(seen) == 1, "the engine must call the patched evaluate_risk exactly once"
    assert seen[0]["ttl"].total_seconds() == 0
    assert seen[0]["now_utc"] == TRIGGER_CLOSE
    assert output["trades"][0]["entry_kind"] == "ENTRY_FILLED"


def test_a_patched_risk_function_can_veto_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """The seam is live: a stand-in that rejects turns the plan into a REJECT record."""
    import src.backtest.simulator as simulator
    from src.domain.enums import DailyState
    from src.risk.types import PortfolioVerdict

    def veto(**_: Any) -> PortfolioVerdict:
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code="STOP_TOO_TIGHT",
            daily_state=DailyState.NORMAL,
        )

    monkeypatch.setattr(simulator, "evaluate_risk", veto)
    (trade,) = simulator.run(_case("intrabar_both_touched"))["trades"]
    assert trade["entry_kind"] == "REJECT"
    assert trade["reason_code"] == "STOP_TOO_TIGHT"


def test_a_passed_minute_source_wins_over_the_rows_and_missing_data_fails_closed() -> None:
    """`minute_source` replaces the case rows; with neither, run raises."""
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    with_rows = run(case_input)

    parsed = parse_case_input(case_input)
    source = parsed.minute_source
    assert isinstance(source, ListMinuteSource)
    without_rows = {
        k: v for k, v in case_input.items() if k not in ("trade_bars_1m", "mark_bars_1m")
    }
    assert _digest(run(without_rows, minute_source=source)) == _digest(with_rows)
    with pytest.raises(ValueError, match="minute"):
        run(without_rows)


# --------------------------------------------------------------------------- #
# guard_rates_from_params (shared by the engine and the paper loop, D-19).
# --------------------------------------------------------------------------- #


def test_guard_rates_from_params_reads_both_keys_as_decimals() -> None:
    from src.backtest.costs import guard_rates_from_params

    result = guard_rates_from_params(
        {"min_stop_distance_rate": Decimal("0.003"), "max_cost_to_risk": Decimal("0.15")}
    )
    assert result == (Decimal("0.003"), Decimal("0.15"))
    assert all(isinstance(v, Decimal) for v in result)


@pytest.mark.parametrize("missing", ["min_stop_distance_rate", "max_cost_to_risk"])
def test_guard_rates_from_params_names_the_missing_key(missing: str) -> None:
    from src.backtest.costs import guard_rates_from_params

    params = {"min_stop_distance_rate": Decimal("0.003"), "max_cost_to_risk": Decimal("0.15")}
    del params[missing]
    with pytest.raises(ValueError, match=missing):
        guard_rates_from_params(params)


def test_guard_rates_from_params_matches_pinned_registry_set() -> None:
    from src.backtest.costs import guard_rates_from_params

    v5 = load_parameter_set("trend-pullback", "baseline-v5")
    assert guard_rates_from_params(v5.params) == (Decimal("0.003"), Decimal("0.15"))
    v4 = load_parameter_set("trend-pullback", "baseline-v4")
    with pytest.raises(ValueError, match="min_stop_distance_rate"):
        guard_rates_from_params(v4.params)


@pytest.mark.parametrize("bad", [0.003, "0.003", True, None])
def test_guard_rates_from_params_rejects_non_decimal_types(bad: object) -> None:
    """12-REVIEW WR-05: float, str, bool and None are refused (Decimal or int only)."""
    from src.backtest.costs import guard_rates_from_params

    params = {"min_stop_distance_rate": bad, "max_cost_to_risk": Decimal("0.15")}
    with pytest.raises(TypeError, match="min_stop_distance_rate"):
        guard_rates_from_params(params)


@pytest.mark.parametrize(
    ("min_stop", "max_ratio"),
    [
        (Decimal("NaN"), Decimal("0.15")),
        (Decimal("0.003"), Decimal("NaN")),
        (Decimal("Infinity"), Decimal("0.15")),
        (Decimal("0.003"), Decimal("0")),
        (Decimal("0.003"), Decimal("2")),
    ],
)
def test_guard_rates_from_params_validates_range_and_finiteness(
    min_stop: Decimal, max_ratio: Decimal
) -> None:
    from src.backtest.costs import guard_rates_from_params

    params = {"min_stop_distance_rate": min_stop, "max_cost_to_risk": max_ratio}
    with pytest.raises(ValueError):
        guard_rates_from_params(params)


# --------------------------------------------------------------------------- #
# End to end: costs recomputed from literal rates (D-05, F-306).
# --------------------------------------------------------------------------- #

_E2E_CASES = [
    "intrabar_both_touched",
    "intrabar_both_touched_short",
    "intrabar_missing_fallback",
]


@pytest.mark.parametrize("case_name", _E2E_CASES)
def test_end_to_end_sl_loss_including_costs_is_within_allowed_risk(case_name: str) -> None:
    """The full run: loss at the SL, fees and slippage included, <= 50.

    allowed_risk = 10000 x 0.005 = 50. Rates are literals (0.0005 fees, 0.0001 entry
    slippage, 0.0003 stop-exit slippage), the loss is recomputed here from the record's own
    prices and quantity. No funding instant lies inside the holding period, so funding is 0.
    """
    from src.backtest.simulator import run

    trade = run(_case(case_name))["trades"][0]
    assert trade["exit_kind"] == "SL"

    entry = Decimal(trade["entry_price"])
    exit_ = Decimal(trade["exit_price"])
    qty = Decimal(trade["quantity"])
    if trade["direction"] == "LONG":
        gross = (exit_ - entry) * qty
    else:
        gross = (entry - exit_) * qty
    entry_fee = entry * qty * Decimal("0.0005")
    exit_fee = exit_ * qty * Decimal("0.0005")
    slippage = entry * qty * Decimal("0.0001") + exit_ * qty * Decimal("0.0003")

    assert Decimal(trade["entry_fee"]) == entry_fee
    assert Decimal(trade["exit_fee"]) == exit_fee
    assert Decimal(trade["slippage_amount"]) == slippage
    assert Decimal(trade["gross_pnl"]) == gross
    assert Decimal(trade["funding_amount"]) == 0
    assert trade["funding_event_count"] == 0

    loss = -(gross - entry_fee - exit_fee - slippage)
    assert Decimal(trade["realized_pnl"]) == -loss
    assert loss > 0
    assert loss <= Decimal("50")
    assert qty % Decimal("0.001") == 0


def test_end_to_end_tp_ladder_costs_are_booked_per_leg() -> None:
    """TP1 half then TP2 (both resting limits at expected_slippage 0.0001), hand arithmetic.

    Entry 117.80 x 9.651; TP1 123.20 x 4.825; TP2 128.60 x 4.826 (the remainder).
    """
    from src.backtest.simulator import run

    (trade,) = run(_case("limit_partial_fill"))["trades"]
    entry, qty = Decimal("117.80"), Decimal("9.651")
    tp1_price, tp1_qty = Decimal("123.20"), Decimal("4.825")
    tp2_price, tp2_qty = Decimal("128.60"), qty - tp1_qty
    assert tp2_qty == Decimal("4.826")

    gross = tp1_qty * (tp1_price - entry) + tp2_qty * (tp2_price - entry)
    assert gross == Decimal("78.1758")
    fees = (entry * qty + tp1_price * tp1_qty + tp2_price * tp2_qty) * Decimal("0.0005")
    slippage = (entry * qty + tp1_price * tp1_qty + tp2_price * tp2_qty) * Decimal("0.0001")

    assert Decimal(trade["gross_pnl"]) == gross
    assert Decimal(trade["entry_fee"]) + Decimal(trade["exit_fee"]) == fees
    assert Decimal(trade["slippage_amount"]) == slippage
    assert Decimal(trade["realized_pnl"]) == gross - fees - slippage


@pytest.mark.parametrize("case_name", _E2E_CASES)
def test_end_to_end_modeled_costs_are_quote_per_unit_at_the_sizing_edge(
    case_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """modeled cost per unit = sizing_edge x 0.0006 + stop x 0.0008 (quote per unit)."""
    case_input = _case(case_name)
    sized = _sized_modeled_costs(case_input, monkeypatch)
    trade_plan, direction = _replan(case_input)
    edge = trade_plan.entry_max_price if direction == "LONG" else trade_plan.entry_min_price
    expected = edge * Decimal("0.0006") + trade_plan.stop_loss_price * Decimal("0.0008")
    assert sized == expected


# --------------------------------------------------------------------------- #
# Legacy refusals and guard flow-through (T-12-19).
# --------------------------------------------------------------------------- #


def test_run_refuses_legacy_registry_set_without_guard_rates() -> None:
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    case_input["parameter_set_id"] = "baseline-v4"
    case_input["strategy_version"] = "v3.0.0"
    # The v5 fixture cost model carries exit_slippage_rate, the legacy v4 set
    # does not pin it: the registry binding refuses before any sizing (WR-03).
    with pytest.raises(CostModelBindingMismatch):
        run(case_input)


def test_run_refuses_cost_dict_without_exit_slippage_rate() -> None:
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    del case_input["cost_model"]["exit_slippage_rate"]
    # A dict without exit_slippage_rate disagrees with the v5 registry set that
    # pins it; the binding refuses it before any sizing (WR-03).
    with pytest.raises(CostModelBindingMismatch):
        run(case_input)


def test_run_refuses_cost_dict_without_funding_convention() -> None:
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    del case_input["cost_model"]["funding_convention"]
    # The v2 parser refuses a cost model without the funding sign convention: it is part
    # of cost identity (Phase 14, D-16, D-36), so no engine work starts.
    with pytest.raises(ValueError, match="funding_convention"):
        run(case_input)


def test_run_refuses_fixture_cost_model_that_disagrees_with_registry() -> None:
    """WR-03: a fixture fee rate the registry set does not pin is refused."""
    from src.backtest.simulator import run

    case_input = _case("intrabar_both_touched")
    case_input["cost_model"]["fee_rate_entry"] = "0.0001"
    with pytest.raises(CostModelBindingMismatch):
        run(case_input)


def test_run_accepts_partial_fill_fraction_that_differs_from_registry() -> None:
    """WR-03: partial_fill_fraction is applied after sizing and is not bound."""
    from src.backtest.simulator import run

    assert run(_case("limit_partial_fill"))["trades"][0]["entry_kind"] == "PARTIAL_FILL"


def test_guard_reason_flows_from_the_shared_helper_into_a_reject_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A min_stop_distance_rate of 3 percent (the fixture stop is about 2.04 percent)."""
    import src.backtest.engine as engine
    import src.backtest.simulator as simulator

    real = engine.guard_rates_from_params

    def _tight(params):  # type: ignore[no-untyped-def]
        _, max_cost_to_risk = real(params)
        return Decimal("0.03"), max_cost_to_risk

    monkeypatch.setattr(engine, "guard_rates_from_params", _tight)
    trades = simulator.run(_case("intrabar_both_touched"))["trades"]
    assert len(trades) == 1
    assert trades[0]["outcome_kind"] == "REJECT"
    assert trades[0]["reason_code"] == "STOP_TOO_TIGHT"
