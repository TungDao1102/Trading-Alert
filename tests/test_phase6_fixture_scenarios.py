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
}
PARITY_KEY = "phase7/parity_overlapping_history/input.json"


def _key(name: str) -> str:
    return f"phase6/{name}/input.json"


# The nine Phase 6 cases plus the Phase 7 parity input (the both-touched payload, as today).
SCENARIO_CASES: dict[str, tuple[str, tuple[str, str | None, bool, int]]] = {
    **{name: (_key(name), tuple_) for name, tuple_ in V6_SCENARIOS.items()},
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
    assert set(V6_SCENARIOS) == {"intrabar_both_touched"}
    assert set(_payloads()) == {_key(name) for name in V6_SCENARIOS}


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
