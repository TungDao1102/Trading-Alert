"""Named-scenario and consumer-fact proof of every v6 payload (Phase 15, plan 15-10).

`scripts/gen_phase6_fixtures.py` builds, in memory, the nine Phase 6 cases and the Phase 7
parity input on the corrected Family A geometry (`build_v6_payloads()`, D-19, D-26). Nothing
here reads a committed fixture: plan 15-12 writes the files from the same function and moves
every consumer of them in one commit. This module proves what that move will rely on:

* each payload, run through the simulator entry point `REGRESSION_SNAPSHOTS` uses
  (`src.backtest.simulator.run`), ends in the scenario of its case name (`V6_SCENARIOS`; each
  tuple keeps the meaning of today's `REGRESSION_SNAPSHOTS` tuple for the same case);
* exactly one signal fires, at the trigger close, and every earlier bar is NO_TRADE;
* the facts a consumer asserts (prices, times, quantities, counts, per-leg bookings) equal the
  hand-derived values of `15-10-SUMMARY.md` "## v6 fixture facts". Those values were computed
  with standalone Decimal one-liners quoted in that file; the engine output is only compared
  to them here, never the source of them (threat T-15-27).

The two baseline cases behave as baselines on the new bars (D-26, F7): baseline-no-trade-v4
gives one REJECT RR_TOO_LOW reached after the structural invariants pass, and
baseline-simple-trend-v4 gives one filled LONG trade that exits at its stop.
"""

from __future__ import annotations

import copy
import functools
import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.case import parse_case_input
from src.backtest.simulator import run
from src.core.strategy import evaluate
from src.core.types import MarketSnapshot
from src.domain.registry import load_parameter_set

REPO_ROOT = Path(__file__).resolve().parents[1]
TRIGGER_CLOSE = datetime(2026, 9, 11, 9, 59, 59, tzinfo=UTC)
SIGNAL_CLOSE_TEXT = "2026-09-11T09:59:59+00:00"

# Scenario tuple per Phase 6 case, the shape of REGRESSION_SNAPSHOTS:
# (entry_kind, exit_kind, fallback_applied, touch_no_fill_count) of the FIRST record. Each tuple
# keeps the meaning today's snapshot tuple has for the same case name. The record COUNT may
# differ from the baseline-v5 fixtures: the stop now lies beyond the zone, so the follow-up
# setup that bar 250 used to produce in the fallback and invalidation cases can no longer exist
# (a bar that reaches the stop is outside the zone it would have to touch).
V6_SCENARIOS: dict[str, tuple[str, str | None, bool, int]] = {
    "intrabar_both_touched": ("ENTRY_FILLED", "SL", False, 0),
    "intrabar_both_touched_short": ("ENTRY_FILLED", "SL", False, 0),
    "intrabar_missing_fallback": ("ENTRY_FILLED", "SL", True, 0),
    "limit_touch_no_fill": ("EXPIRED", None, False, 3),
    "limit_partial_fill": ("PARTIAL_FILL", "TP2", False, 0),
    "limit_expiry": ("EXPIRED", None, False, 0),
    "invalidation_cancels_entry": ("INVALIDATION_CANCEL", None, False, 0),
    "baselines/no_trade": ("REJECT", None, False, 0),
    "baselines/simple_trend": ("ENTRY_FILLED", "SL", False, 0),
}
PARITY_KEY = "phase7/parity_overlapping_history/input.json"


def _key(name: str) -> str:
    return f"phase6/{name}/input.json"


# The nine Phase 6 cases plus the Phase 7 parity input (the both-touched payload, as today).
SCENARIO_CASES: dict[str, tuple[str, tuple[str, str | None, bool, int]]] = {
    **{name: (_key(name), tuple_) for name, tuple_ in V6_SCENARIOS.items()},
    "parity_overlapping_history": (PARITY_KEY, V6_SCENARIOS["intrabar_both_touched"]),
}


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "gen_phase6_fixtures", REPO_ROOT / "scripts" / "gen_phase6_fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _payloads() -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = _load_generator().build_v6_payloads()
    return payloads


def _payload(key: str) -> dict[str, Any]:
    return copy.deepcopy(_payloads()[key])


@functools.cache
def _run_cached(key: str) -> dict[str, Any]:
    output: dict[str, Any] = run(_payload(key))
    return output


def test_v6_scenarios_has_one_entry_per_phase_6_case() -> None:
    assert len(V6_SCENARIOS) == 9
    assert set(_payloads()) == {_key(name) for name in V6_SCENARIOS} | {PARITY_KEY}


@pytest.mark.parametrize("case", sorted(SCENARIO_CASES))
def test_v6_payload_matches_its_named_scenario(case: str) -> None:
    """The first record's scenario tuple, extracted exactly as REGRESSION_SNAPSHOTS does."""
    key, scenario = SCENARIO_CASES[case]
    first = _run_cached(key)["trades"][0]
    assert (
        first["entry_kind"],
        first["exit_kind"],
        first["fallback_applied"],
        first["touch_no_fill_count"],
    ) == scenario


def test_the_parity_input_is_the_both_touched_payload() -> None:
    assert _payloads()[PARITY_KEY] == _payloads()[_key("intrabar_both_touched")]
    assert _run_cached(PARITY_KEY) == _run_cached(_key("intrabar_both_touched"))


# --------------------------------------------------------------------------- #
# Exactly one signal, at the trigger close; NO_TRADE on every earlier bar.
# --------------------------------------------------------------------------- #


def _evaluated_closes(case: dict[str, Any]) -> int:
    """Strategy bars the engine evaluates: those closing inside the data window."""
    start = datetime.fromisoformat(case["data_window"]["start_utc"])
    end = datetime.fromisoformat(case["data_window"]["end_utc"])
    return sum(
        1
        for row in case["strategy_bars"]
        if start <= datetime.fromisoformat(row["close_time_utc"]) <= end
    )


@pytest.mark.parametrize("key", sorted(_payloads()))
def test_v6_exactly_one_signal_at_the_trigger_close(key: str) -> None:
    case = _payload(key)
    output = _run_cached(key)
    trades = output["trades"]
    assert len(trades) == 1, [t["entry_kind"] for t in trades]
    assert trades[0]["signal_close_utc"] == SIGNAL_CLOSE_TEXT
    counts = output["run_summary"]["no_trade_counts"]
    rejects = sum(1 for t in trades if t["entry_kind"] == "REJECT")
    # Every evaluated close but the trigger is NO_TRADE; a rejected plan adds its own count.
    assert sum(counts.values()) == _evaluated_closes(case) - 1 + rejects
    assert "CONFLICT_WITH_OPEN_POSITION" not in counts


@pytest.mark.parametrize("key", sorted(_payloads()))
def test_v6_every_earlier_bar_is_no_trade_under_the_real_strategy(key: str) -> None:
    """The strategy on each prefix of bars 230..248 gives NO_TRADE; bar 249 gives a signal."""
    case = _payload(key)
    parsed = parse_case_input(case)
    bars = list(parsed.strategy_bars)[:250]
    parameter_set = load_parameter_set(case["strategy_id"], case["parameter_set_id"])

    def verdict(index: int) -> Any:
        prefix = bars[: index + 1]
        context = [c for c in parsed.context_bars if c.close_time_utc <= prefix[-1].close_time_utc]
        return evaluate(
            snapshot=MarketSnapshot(
                symbol=prefix[-1].symbol,
                setup_candles=prefix,
                context_candles=context,
                source_timeframe="1h",
            ),
            account_state=parsed.account_state,
            strategy_version=case["strategy_version"],
            parameter_set=parameter_set,
        )

    for index in range(230, 249):
        assert verdict(index).is_no_trade, f"bar {index} produced a signal"
    assert bars[249].close_time_utc == TRIGGER_CLOSE
    assert not verdict(249).is_no_trade


# --------------------------------------------------------------------------- #
# Consumer facts: hand-derived values (15-10-SUMMARY.md "## v6 fixture facts").
# --------------------------------------------------------------------------- #

# Money, price and quantity facts are Decimals; times, kinds and flags are plain values.
D = Decimal
LONG_STOP_OUT: dict[str, Any] = {
    "direction": "LONG",
    "signal_close_utc": SIGNAL_CLOSE_TEXT,
    "entry_kind": "ENTRY_FILLED",
    "entry_price": D("117.80"),
    "entry_time_utc": "2026-09-11T10:05:59+00:00",
    "exit_kind": "SL",
    "exit_price": D("116.50"),
    "exit_time_utc": "2026-09-11T10:06:59+00:00",
    "planned_quantity": D("19.303"),
    "quantity": D("19.303"),
    "tp1_quantity": None,
    "fallback_applied": False,
    "coverage_note": None,
    "touch_no_fill_count": 0,
    "gross_pnl": D("-25.09390"),
    "entry_fee": D("1.136946700"),
    "exit_fee": D("1.124399750"),
    "slippage_amount": D("0.902029190"),
    "realized_pnl": D("-28.257275640"),
}
V6_FACTS: dict[str, dict[str, Any]] = {
    "intrabar_both_touched": LONG_STOP_OUT,
    "parity_overlapping_history": LONG_STOP_OUT,
    "intrabar_both_touched_short": {
        "direction": "SHORT",
        "signal_close_utc": SIGNAL_CLOSE_TEXT,
        "entry_kind": "ENTRY_FILLED",
        "entry_price": D("132.20"),
        "entry_time_utc": "2026-09-11T10:05:59+00:00",
        "exit_kind": "SL",
        "exit_price": D("133.50"),
        "exit_time_utc": "2026-09-11T10:06:59+00:00",
        "planned_quantity": D("19.147"),
        "quantity": D("19.147"),
        "tp1_quantity": None,
        "fallback_applied": False,
        "coverage_note": None,
        "touch_no_fill_count": 0,
        "gross_pnl": D("-24.89110"),
        "entry_fee": D("1.265616700"),
        "exit_fee": D("1.278062250"),
        "slippage_amount": D("1.019960690"),
        "realized_pnl": D("-28.454739640"),
    },
    "intrabar_missing_fallback": {
        **LONG_STOP_OUT,
        "exit_time_utc": "2026-09-11T10:59:59+00:00",
        "resolved_at_utc": "2026-09-11T10:59:59+00:00",
        "fallback_applied": True,
        # The first missing mark minute opens at 10:06:00 (minute 6 of the hour); the rest of
        # bar 250 resolves once at its close 10:59:59, stop first (D-12).
        "coverage_note": (
            "mark_price_1m_missing_from_2026-09-11T10:06:00+00:00; "
            "resolved_at_strategy_bar_close_2026-09-11T10:59:59+00:00 "
            "from the trade-price bar range, stop first"
        ),
    },
    "limit_touch_no_fill": {
        "direction": "LONG",
        "entry_kind": "EXPIRED",
        "quantity": None,
        "planned_quantity": D("19.303"),
        "touch_no_fill_count": 3,
        "resolved_at_utc": "2026-09-11T13:59:59+00:00",
    },
    "limit_partial_fill": {
        "direction": "LONG",
        "entry_kind": "PARTIAL_FILL",
        "entry_price": D("117.80"),
        "entry_time_utc": "2026-09-11T10:05:59+00:00",
        "planned_quantity": D("19.303"),
        "quantity": D("9.651"),
        "tp1_quantity": D("4.825"),
        "tp1_price": D("123.20"),
        "exit_kind": "TP2",
        "exit_price": D("128.60"),
        "exit_time_utc": "2026-09-11T10:07:59+00:00",
        "resolved_at_utc": "2026-09-11T10:07:59+00:00",
        "touch_no_fill_count": 0,
        "gross_pnl": D("78.17580"),
        "entry_fee": D("0.568443900"),
        "exit_fee": D("0.607531800"),
        "slippage_amount": D("0.235195140"),
        "realized_pnl": D("76.764629160"),
    },
    "limit_expiry": {
        "direction": "LONG",
        "entry_kind": "EXPIRED",
        "quantity": None,
        "planned_quantity": D("19.303"),
        "touch_no_fill_count": 0,
        "resolved_at_utc": "2026-09-11T13:59:59+00:00",
    },
    "invalidation_cancels_entry": {
        "direction": "LONG",
        "entry_kind": "INVALIDATION_CANCEL",
        "quantity": None,
        "planned_quantity": D("19.303"),
        "touch_no_fill_count": 0,
        "resolved_at_utc": "2026-09-11T10:59:59+00:00",
    },
    "baselines/no_trade": {
        "direction": "LONG",
        "entry_kind": "REJECT",
        "reason_code": "RR_TOO_LOW",
        "signal_close_utc": SIGNAL_CLOSE_TEXT,
        "quantity": None,
    },
    "baselines/simple_trend": {
        "direction": "LONG",
        "signal_close_utc": SIGNAL_CLOSE_TEXT,
        "entry_kind": "ENTRY_FILLED",
        "entry_price": D("117.80"),
        "entry_time_utc": "2026-09-11T10:05:59+00:00",
        "exit_kind": "SL",
        "exit_price": D("115.60"),
        "exit_time_utc": "2026-09-11T10:06:59+00:00",
        "planned_quantity": D("11.566"),
        "quantity": D("11.566"),
        "gross_pnl": D("-25.44520"),
        "entry_fee": D("0.681237400"),
        "exit_fee": D("0.668514800"),
        "slippage_amount": D("0.537356360"),
        "realized_pnl": D("-27.332308560"),
    },
}


@pytest.mark.parametrize("case", sorted(V6_FACTS))
def test_v6_consumer_facts_equal_the_hand_derived_values(case: str) -> None:
    key, _ = SCENARIO_CASES[case]
    (trade,) = _run_cached(key)["trades"]
    for field, expected in V6_FACTS[case].items():
        actual = trade[field]
        if isinstance(expected, Decimal):
            assert actual is not None and Decimal(actual) == expected, field
        else:
            assert actual == expected, field


def test_v6_missing_fallback_coverage_note_names_the_first_missing_minute() -> None:
    output = _run_cached(_key("intrabar_missing_fallback"))
    (trade,) = output["trades"]
    assert trade["coverage_note"].startswith("mark_price_1m_missing_from_2026-09-11T10:06:00")
    assert output["run_summary"]["fallback_count"] == 1


def test_v6_touch_no_fill_total_counts_the_three_touches() -> None:
    assert _run_cached(_key("limit_touch_no_fill"))["run_summary"]["touch_no_fill_total"] == 3


# --------------------------------------------------------------------------- #
# Per-leg bookings of the stop-out and the TP ladder, by literal arithmetic.
# --------------------------------------------------------------------------- #

FEE = Decimal("0.0005")
ENTRY_SLIPPAGE = Decimal("0.0001")  # entry leg and every resting-limit exit (TP1, TP2)
STOP_SLIPPAGE = Decimal("0.0003")  # stop-market exit leg


def _bookings(key: str) -> dict[str, Decimal]:
    from src.backtest.engine import simulate_detailed
    from src.risk.gating import evaluate_risk as real_evaluate_risk

    result = simulate_detailed(_payload(key), risk_fn=real_evaluate_risk)
    kinds = [b.kind for b in result.bookings]
    assert len(kinds) == len(set(kinds)), f"one booking per kind expected: {kinds}"
    return {b.kind: b.amount for b in result.bookings}


def test_v6_stop_out_legs_match_hand_arithmetic() -> None:
    """Entry leg and the SL final leg (stop-market, exit_slippage_rate): 19.303 at 117.80."""
    qty, entry, stop = Decimal("19.303"), Decimal("117.80"), Decimal("116.50")
    entry_leg = -(entry * qty * (FEE + ENTRY_SLIPPAGE))
    final_leg = (stop - entry) * qty - stop * qty * (FEE + STOP_SLIPPAGE)
    assert _bookings(_key("intrabar_both_touched")) == {"FILL": entry_leg, "EXIT": final_leg}
    assert entry_leg == Decimal("-1.364336040")
    assert final_leg == Decimal("-26.892939600")


def test_v6_tp_ladder_legs_match_hand_arithmetic() -> None:
    """Entry, TP1 and TP2 legs: 9.651 filled, 4.825 at TP1 123.20, 4.826 at TP2 128.60."""
    entry = Decimal("117.80")
    qty, tp1_qty, tp2_qty = Decimal("9.651"), Decimal("4.825"), Decimal("4.826")
    tp1, tp2 = Decimal("123.20"), Decimal("128.60")
    entry_leg = -(entry * qty * (FEE + ENTRY_SLIPPAGE))
    tp1_leg = (tp1 - entry) * tp1_qty - tp1 * tp1_qty * (FEE + ENTRY_SLIPPAGE)
    final_leg = (tp2 - entry) * tp2_qty - tp2 * tp2_qty * (FEE + ENTRY_SLIPPAGE)
    assert tp1_qty + tp2_qty == qty
    assert _bookings(_key("limit_partial_fill")) == {
        "FILL": entry_leg,
        "TP1": tp1_leg,
        "EXIT": final_leg,
    }
    assert entry_leg == Decimal("-0.682132680")
    assert tp1_leg == Decimal("25.698336000")
    assert final_leg == Decimal("51.748425840")


# --------------------------------------------------------------------------- #
# The two baselines behave as baselines on the new bars (D-26, F7).
# --------------------------------------------------------------------------- #


def test_baseline_no_trade_is_one_rr_reject_after_the_invariants_pass() -> None:
    """One REJECT RR_TOO_LOW record; the same bars on baseline-v6 produce a plan (D-26)."""
    key = _key("baselines/no_trade")
    output = _run_cached(key)
    assert [(t["entry_kind"], t["reason_code"]) for t in output["trades"]] == [
        ("REJECT", "RR_TOO_LOW")
    ]
    assert output["run_summary"]["no_trade_counts"]["RR_TOO_LOW"] == 1
    case = _payload(key)
    assert case["parameter_set_id"] == "baseline-no-trade-v4"
    assert case["strategy_version"] == "v5.0.0"
    # The rejection is the RR gate and nothing before it: the identical bars on the candidate
    # set (same geometry, minimum_rr 2.0) become a filled-able plan, so the structural
    # invariants (stop outside the zone, signal bar not through the stop, min_stop_atr, TP1 on
    # the profit side) all passed before the RR gate fired.
    candidate = dict(case, parameter_set_id="baseline-v6")
    candidate_trade = run(candidate)["trades"][0]
    assert candidate_trade["entry_kind"] == "ENTRY_FILLED"


def test_baseline_simple_trend_is_one_filled_long_trade_exiting_at_its_stop() -> None:
    key = _key("baselines/simple_trend")
    case = _payload(key)
    assert case["parameter_set_id"] == "baseline-simple-trend-v4"
    assert case["strategy_version"] == "v5.0.0"
    (trade,) = _run_cached(key)["trades"]
    assert trade["direction"] == "LONG"
    assert trade["entry_kind"] == "ENTRY_FILLED"
    assert trade["exit_kind"] == "SL"
    assert trade["entry_time_utc"] > trade["signal_close_utc"]
    # The wider zone gives a wider stop than the candidate: the exit minute must reach 115.60.
    candidate = _run_cached(_key("intrabar_both_touched"))["trades"][0]
    assert Decimal(trade["exit_price"]) < Decimal(candidate["exit_price"])
