"""Engine tests for the v2 event loop (Phase 14, plan 14-08).

Tracer (Task 1): one scripted LONG plan at the 09:59:59.999 close is sized by the real
`evaluate_risk` on ledger equity, rests from 10:00, fills at 10:01, is stopped out by the
mark minute 10:40 and leaves one validated record.

Hand oracle (zone 99.00-101.00 -> limit 100.00, stop 98.00, tick 0.10, step 0.001,
min qty 0.001, min notional 5, equity 10000, risk_rate 0.005, baseline-v5 costs):

    sizing entry       = 101.00 (adverse zone edge)
    costs per unit     = 101 x 0.0006 + 98 x 0.0008 = 0.1390
    risk per unit      = |101 - 98| + 0.1390 = 3.1390, allowed risk = 10000 x 0.005 = 50
    quantity           = floor(50 / 3.1390 = 15.9286..., step 0.001) = 15.928
    realized risk      = 15.928 x 3.1390 = 49.997992
    gross_pnl          = (98.00 - 100.00) x 15.928 = -31.856
    entry fee          = 100 x 15.928 x 0.0005 = 0.7964
    entry slippage     = 100 x 15.928 x 0.0001 = 0.15928
    exit fee           = 98 x 15.928 x 0.0005 = 0.780472
    exit slippage      = 98 x 15.928 x 0.0003 = 0.4682832
    realized_pnl       = -31.856 - 0.7964 - 0.780472 - (0.15928 + 0.4682832) = -34.0604352
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.case import CASE_INPUT_SCHEMA, REMOVED_V1_KEYS
from src.backtest.engine import simulate, simulate_detailed
from src.backtest.records import build_reject_record
from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION
from src.domain.enums import RejectionReason
from src.risk.gating import evaluate_risk
from src.risk.types import PortfolioVerdict

from tests.backtest_case_helpers import (
    SIGNAL_CLOSE,
    SYMBOL,
    at,
    constraint_row,
    default_funding,
    fixed_risk_fn,
    flat_minutes,
    make_case,
    minute_close,
    minute_row,
    scripted_plan,
)

ENGINE_PATH = Path(__file__).resolve().parent.parent / "src" / "backtest" / "engine.py"


def tracer_case(**overrides: Any) -> dict[str, Any]:
    """The Task 1 case: a scripted LONG at 09:59:59.999, fill at 10:01, stop at 10:40."""
    trade = [
        # 10:00 stays above the limit - one tick; 10:01 trades through it.
        minute_row(SYMBOL, at(10, 0), "100.60", "100.70", "100.40", "100.60", kind="trade"),
        minute_row(SYMBOL, at(10, 1), "100.20", "100.30", "99.80", "100.00", kind="trade"),
    ]
    mark = [
        *flat_minutes(SYMBOL, at(10, 0), 40, "100.00", kind="mark"),
        minute_row(SYMBOL, at(10, 40), "98.50", "98.60", "97.90", "98.20", kind="mark"),
    ]
    arguments: dict[str, Any] = {
        "scripted": [scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-1")],
        "trade_minutes": trade,
        "mark_minutes": mark,
    }
    arguments.update(overrides)
    return make_case(**arguments)


def spying_risk_fn(calls: list[dict[str, Any]], verdicts: list[PortfolioVerdict]) -> Any:
    """`evaluate_risk` wrapped so a test sees every call and every verdict."""

    def risk_fn(**kwargs: Any) -> PortfolioVerdict:
        calls.append(kwargs)
        verdict = evaluate_risk(**kwargs)
        verdicts.append(verdict)
        return verdict

    return risk_fn


def test_tracer_plan_rests_fills_and_stops_out_with_real_sizing() -> None:
    calls: list[dict[str, Any]] = []
    verdicts: list[PortfolioVerdict] = []
    output = simulate(tracer_case(), risk_fn=spying_risk_fn(calls, verdicts))

    assert len(output["trades"]) == 1
    trade = output["trades"][0]
    assert trade["entry_kind"] == "ENTRY_FILLED"
    assert trade["outcome_kind"] == "OK"
    assert trade["exit_kind"] == "SL"
    assert trade["direction"] == "LONG"
    assert trade["signal_id"] == "sig-1"
    assert trade["signal_close_utc"] == SIGNAL_CLOSE.isoformat()
    # The plan is active from the first minute AFTER the signal close, and the fill is the
    # close of the deciding trade minute (10:01), never the signal bar itself.
    assert trade["entry_time_utc"] == minute_close(at(10, 1)).isoformat()
    assert datetime.fromisoformat(trade["entry_time_utc"]) > SIGNAL_CLOSE
    assert trade["exit_time_utc"] == minute_close(at(10, 40)).isoformat()
    assert Decimal(trade["entry_price"]) == Decimal("100.00")
    assert Decimal(trade["exit_price"]) == Decimal("98.00")
    assert trade["gap_through_stop"] is False
    assert Decimal(trade["quantity"]) == Decimal("15.928")
    assert Decimal(trade["planned_quantity"]) == Decimal("15.928")


def test_tracer_record_costs_follow_the_hand_oracle() -> None:
    verdicts: list[PortfolioVerdict] = []
    output = simulate(tracer_case(), risk_fn=spying_risk_fn([], verdicts))
    trade = output["trades"][0]

    assert Decimal(trade["gross_pnl"]) == Decimal("-31.856")
    assert Decimal(trade["entry_fee"]) == Decimal("0.7964")
    assert Decimal(trade["exit_fee"]) == Decimal("0.780472")
    assert Decimal(trade["slippage_amount"]) == Decimal("0.6275632")
    assert Decimal(trade["funding_amount"]) == Decimal("0")
    assert Decimal(trade["realized_pnl"]) == Decimal("-34.0604352")
    # A full fill: the R denominator is the sized realized risk itself (D-20).
    sized = verdicts[0].sized
    assert sized is not None
    assert Decimal(trade["realized_risk"]) == sized.realized_risk == Decimal("49.997992")


def test_risk_fn_receives_ledger_state_a_point_in_time_constraint_and_zero_ttl() -> None:
    calls: list[dict[str, Any]] = []
    simulate(tracer_case(), risk_fn=spying_risk_fn(calls, []))

    assert len(calls) == 1
    call = calls[0]
    assert call["now_utc"] == SIGNAL_CLOSE
    assert call["ttl"] == timedelta(0)
    assert call["open_positions"] == []
    assert call["daily_loss_quote"] == Decimal("0")
    assert call["account_state"].equity == Decimal("10000")
    assert call["account_state"].risk_rate == Decimal("0.005")
    assert call["candidate_position_side"] == "LONG"
    snapshot = call["constraint_snapshot"]
    assert snapshot.symbol == SYMBOL
    assert snapshot.price_tick_size == Decimal("0.10")
    # The freshness stamp is clamped to the bar close so the zero ttl gate sees age 0.
    assert snapshot.metadata_observed_at_utc == SIGNAL_CLOSE
    # Registry thresholds arrive as absolute quote amounts of the ledger equity (D-18).
    assert call["parameter_set"]["cluster_cap"] == Decimal("50.000")


def test_output_carries_summary_hashes_and_symbols() -> None:
    output = simulate(tracer_case(), risk_fn=evaluate_risk)

    assert output["symbols"] == [SYMBOL]
    assert output["strategy_version"] == "v4.0.0"
    assert len(output["parameter_set_hash"]) == 64
    assert len(output["cost_model_hash"]) == 64
    summary = output["run_summary"]
    assert summary["plan_source"] == "SCRIPTED"
    assert summary["simulator_semantics_version"] == SIMULATOR_SEMANTICS_VERSION == "2.0.0"
    assert summary["no_trade_counts"] == {}
    assert summary["allowed_gaps_used"] == []
    # The whole output is canonical-JSON safe.
    assert json.loads(json.dumps(output, sort_keys=True)) == output


@pytest.mark.parametrize("key", REMOVED_V1_KEYS)
def test_a_case_carrying_a_v1_key_is_refused_naming_the_key(key: str) -> None:
    case = tracer_case()
    case[key] = {} if key.endswith("_map") else "x"
    with pytest.raises(ValueError, match=key):
        simulate(case, risk_fn=evaluate_risk)


def test_removed_keys_include_the_documented_v1_set() -> None:
    assert set(REMOVED_V1_KEYS) == {
        "intrabar_1m_map",
        "constraint_snapshot",
        "open_positions",
        "daily_loss_quote",
        "now_utc",
        "ttl_seconds",
        "mark_price_bars",
    }


def test_a_case_without_the_schema_literal_is_refused() -> None:
    case = tracer_case()
    del case["case_input_schema"]
    with pytest.raises(ValueError, match="case_input_schema"):
        simulate(case, risk_fn=evaluate_risk)


def test_a_case_with_another_schema_literal_is_refused() -> None:
    case = tracer_case()
    case["case_input_schema"] = "backtest-case/1"
    with pytest.raises(ValueError, match=CASE_INPUT_SCHEMA):
        simulate(case, risk_fn=evaluate_risk)


def test_a_cost_model_without_funding_convention_is_refused() -> None:
    case = tracer_case()
    del case["cost_model"]["funding_convention"]
    with pytest.raises(ValueError, match="funding_convention"):
        simulate(case, risk_fn=evaluate_risk)


def test_a_float_anywhere_in_the_case_is_refused() -> None:
    case = tracer_case()
    case["account_state"]["equity"] = 10000.5
    with pytest.raises(TypeError, match="equity"):
        simulate(case, risk_fn=evaluate_risk)


def test_a_naive_datetime_in_the_case_is_refused() -> None:
    case = tracer_case()
    case["data_window"]["end_utc"] = "2026-01-05T12:00:00"
    with pytest.raises(ValueError, match="end_utc"):
        simulate(case, risk_fn=evaluate_risk)


def test_the_engine_never_imports_evaluate_risk() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == "evaluate_risk"
    ]
    assert imported == []


# --------------------------------------------------------------------------- #
# Task 2: portfolio semantics
# --------------------------------------------------------------------------- #

NEXT_CLOSE = SIGNAL_CLOSE + timedelta(hours=1)  # 10:59:59.999


def go_through(symbol: str, open_time: datetime) -> dict[str, str]:
    """A trade minute that trades through a 100.00 LONG limit (low 99.80 <= 99.90)."""
    return minute_row(symbol, open_time, "100.20", "100.30", "99.80", "100.00", kind="trade")


def stop_out(symbol: str, open_time: datetime) -> dict[str, str]:
    """A mark minute that reaches the 98.00 LONG stop and opens above it (no gap)."""
    return minute_row(symbol, open_time, "98.50", "98.60", "97.90", "98.20", kind="mark")


def resting_series(symbol: str, price: str, minutes: int = 30) -> dict[str, list[dict[str, str]]]:
    """Flat trade and mark minutes from 10:00 that never reach a limit or a stop."""
    return {
        "trade": flat_minutes(symbol, at(10, 0), minutes, price, kind="trade"),
        "mark": flat_minutes(symbol, at(10, 0), minutes, "100.00", kind="mark"),
    }


def test_a_second_setup_on_a_symbol_with_an_active_plan_is_skipped_and_counted() -> None:
    series = resting_series(SYMBOL, "105.00")
    case = make_case(
        scripted=[
            scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-1"),
            scripted_plan(SYMBOL, NEXT_CLOSE, "sig-2"),
        ],
        trade_minutes=series["trade"],
        mark_minutes=series["mark"],
    )
    calls: list[dict[str, Any]] = []
    output = simulate(case, risk_fn=fixed_risk_fn("0.5", "1.50", calls=calls))

    # Only the first plan produced a record; the second never reached the risk function.
    assert [t["signal_id"] for t in output["trades"]] == ["sig-1"]
    assert output["trades"][0]["entry_kind"] == "PENDING_AT_DATA_END"
    assert output["run_summary"]["no_trade_counts"] == {"CONFLICT_WITH_OPEN_POSITION": 1}
    assert len(calls) == 1


def test_a_resting_entry_counts_in_the_cluster_gate_of_a_same_side_symbol() -> None:
    btc = resting_series("BTCUSDT", "105.00")
    case = make_case(
        symbols=("BTCUSDT", "ETHUSDT"),
        scripted=[
            scripted_plan("BTCUSDT", SIGNAL_CLOSE, "sig-btc"),
            scripted_plan("ETHUSDT", NEXT_CLOSE, "sig-eth"),
        ],
        trade_minutes=btc["trade"],
        mark_minutes=btc["mark"],
    )
    calls: list[dict[str, Any]] = []
    output = simulate(case, risk_fn=spying_risk_fn(calls, []))

    by_symbol = {t["symbol"]: t for t in output["trades"]}
    assert by_symbol["BTCUSDT"]["entry_kind"] == "PENDING_AT_DATA_END"
    reject = by_symbol["ETHUSDT"]
    assert reject["outcome_kind"] == "REJECT"
    assert reject["entry_kind"] == "REJECT"
    assert reject["reason_code"] in {"CLUSTER_CAP_REJECT", "AGGREGATE_CAP_REJECT"}
    # The gate saw the BTC resting entry with its sized realized risk (D035).
    resting = calls[1]["open_positions"]
    assert [(p.symbol, p.position_side, p.open_risk) for p in resting] == [
        ("BTCUSDT", "LONG", Decimal("49.997992"))
    ]


def two_symbol_case(*, reverse: bool) -> dict[str, Any]:
    """BTC LONG and ETH SHORT scripted at one close; `reverse` flips every input order."""
    btc = resting_series("BTCUSDT", "105.00")
    eth = resting_series("ETHUSDT", "95.00")
    plans = [
        scripted_plan("BTCUSDT", SIGNAL_CLOSE, "sig-btc"),
        scripted_plan(
            "ETHUSDT", SIGNAL_CLOSE, "sig-eth", "SHORT", stop="103.00", tp1="96.00", tp2="92.00"
        ),
    ]
    symbols = ["BTCUSDT", "ETHUSDT"]
    constraints = [constraint_row("BTCUSDT"), constraint_row("ETHUSDT")]
    trade = [*btc["trade"], *eth["trade"]]
    mark = [*btc["mark"], *eth["mark"]]
    funding = default_funding(symbols)
    if reverse:
        plans.reverse()
        symbols.reverse()
        constraints.reverse()
        trade = [*eth["trade"], *btc["trade"]]  # whole symbol blocks swap, each stays in time order
        mark = [*eth["mark"], *btc["mark"]]
        funding.reverse()
    return make_case(
        symbols=symbols,
        scripted=plans,
        trade_minutes=trade,
        mark_minutes=mark,
        constraints=constraints,
        funding=funding,
    )


def test_symbols_closing_together_are_processed_in_sorted_order_whatever_the_input_order() -> None:
    forward_calls: list[dict[str, Any]] = []
    forward = simulate(
        two_symbol_case(reverse=False), risk_fn=fixed_risk_fn("0.5", "1.50", calls=forward_calls)
    )
    reverse_calls: list[dict[str, Any]] = []
    backward = simulate(
        two_symbol_case(reverse=True), risk_fn=fixed_risk_fn("0.5", "1.50", calls=reverse_calls)
    )

    for calls in (forward_calls, reverse_calls):
        assert [c["constraint_snapshot"].symbol for c in calls] == ["BTCUSDT", "ETHUSDT"]
        # BTCUSDT is sized first, so ETHUSDT already sees its resting entry.
        assert [p.symbol for p in calls[1]["open_positions"]] == ["BTCUSDT"]
    assert [t["symbol"] for t in forward["trades"]] == ["BTCUSDT", "ETHUSDT"]
    assert forward == backward


def daily_stop_case() -> dict[str, Any]:
    """BTC rests (would fill 10:30), ETH is open (fills 10:05, stops 10:45), SOL stops at 10:15."""
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    btc_trade = [
        *flat_minutes("BTCUSDT", at(10, 0), 30, "105.00", kind="trade"),
        go_through("BTCUSDT", at(10, 30)),
    ]
    eth_trade = [
        *flat_minutes("ETHUSDT", at(10, 0), 5, "105.00", kind="trade"),
        go_through("ETHUSDT", at(10, 5)),
    ]
    sol_trade = [
        *flat_minutes("SOLUSDT", at(10, 0), 1, "105.00", kind="trade"),
        go_through("SOLUSDT", at(10, 1)),
    ]
    btc_mark = flat_minutes("BTCUSDT", at(10, 0), 40, "100.00", kind="mark")
    eth_mark = [
        *flat_minutes("ETHUSDT", at(10, 0), 45, "100.00", kind="mark"),
        stop_out("ETHUSDT", at(10, 45)),
    ]
    sol_mark = [
        *flat_minutes("SOLUSDT", at(10, 0), 15, "100.00", kind="mark"),
        stop_out("SOLUSDT", at(10, 15)),
    ]
    return make_case(
        symbols=symbols,
        scripted=[scripted_plan(s, SIGNAL_CLOSE, f"sig-{s[:3].lower()}") for s in symbols],
        trade_minutes=[*btc_trade, *eth_trade, *sol_trade],
        mark_minutes=[*btc_mark, *eth_mark, *sol_mark],
    )


def test_a_daily_stop_cancels_resting_entries_at_the_booking_instant_and_keeps_open_stops() -> None:
    run = simulate_detailed(daily_stop_case(), risk_fn=fixed_risk_fn("50", "100"))
    by_symbol = {t["symbol"]: t for t in run.output["trades"]}

    # SOL: filled 10:01, stopped 10:15. Day PnL = -3.00 (entry) - 103.92 (stop leg) = -106.92,
    # past the 1.0 percent daily stop (100.00 of 10000.00): DAILY_STOP at 10:15:59.999.
    sol = by_symbol["SOLUSDT"]
    assert sol["exit_kind"] == "SL"
    assert sol["exit_time_utc"] == minute_close(at(10, 15)).isoformat()
    assert Decimal(sol["realized_pnl"]) == Decimal("-106.92")

    # BTC rested and would have traded through at 10:30: cancelled at the 10:15:59.999 booking.
    btc = by_symbol["BTCUSDT"]
    assert btc["entry_kind"] == "DAILY_STOP_CANCEL"
    assert btc["resolved_at_utc"] == minute_close(at(10, 15)).isoformat()
    assert btc["entry_time_utc"] is None
    assert btc["exit_kind"] is None

    # ETH was filled at 10:05 (before the stop instant), so its stop stays active until 10:45.
    eth = by_symbol["ETHUSDT"]
    assert eth["entry_kind"] == "ENTRY_FILLED"
    assert eth["entry_time_utc"] == minute_close(at(10, 5)).isoformat()
    assert eth["exit_kind"] == "SL"
    assert eth["exit_time_utc"] == minute_close(at(10, 45)).isoformat()

    cancel = [b for b in run.bookings if b.kind == "CANCEL"]
    assert [(b.symbol, b.time_utc, b.amount) for b in cancel] == [
        ("BTCUSDT", minute_close(at(10, 15)), Decimal("0"))
    ]
    assert not any(b.symbol == "BTCUSDT" and b.kind == "FILL" for b in run.bookings)
    assert run.ledger.equity == Decimal("10000") - Decimal("106.92") * 2


@pytest.mark.parametrize(
    ("quantity", "reason"),
    [("0.001", "MIN_QTY_REJECT"), ("0.002", "NOTIONAL_REJECT")],
)
def test_an_unsizeable_tp1_leg_rejects_the_plan_and_it_never_rests(
    quantity: str, reason: str
) -> None:
    # 0.001: half floors to 0 (below min qty 0.001). 0.002: half is 0.001, and
    # 0.001 x 104.00 = 0.104 is below min notional 5.
    series = resting_series(SYMBOL, "105.00")
    case = make_case(
        scripted=[
            scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-1"),
            scripted_plan(SYMBOL, NEXT_CLOSE, "sig-2"),
        ],
        trade_minutes=series["trade"],
        mark_minutes=series["mark"],
    )
    output = simulate(case, risk_fn=fixed_risk_fn(quantity, "1.50"))

    assert [(t["signal_id"], t["entry_kind"], t["reason_code"]) for t in output["trades"]] == [
        ("sig-1", "REJECT", reason),
        ("sig-2", "REJECT", reason),
    ]
    # Nothing rested, so the second setup was a fresh evaluation and not a conflict.
    assert output["run_summary"]["no_trade_counts"] == {}


def test_a_partial_fill_floors_the_quantity_and_scales_the_realized_risk() -> None:
    case = tracer_case(cost_overrides={"partial_fill_fraction": "0.5"})
    output = simulate(case, risk_fn=fixed_risk_fn("0.5", "1.50"))

    trade = output["trades"][0]
    assert trade["entry_kind"] == "PARTIAL_FILL"
    assert Decimal(trade["planned_quantity"]) == Decimal("0.5")
    assert Decimal(trade["quantity"]) == Decimal("0.250")  # floor(0.5 x 0.5 to step 0.001)
    assert Decimal(trade["realized_risk"]) == Decimal("0.75")  # 1.50 x 0.250 / 0.5
    assert Decimal(trade["gross_pnl"]) == Decimal("-0.500")  # (98.00 - 100.00) x 0.250


def test_exhausted_equity_stops_evaluating_new_setups() -> None:
    # Equity 100, quantity 60: the stop-out loses 120.00 + 3.60 + 4.704 = 128.304.
    mark = [
        *flat_minutes(SYMBOL, at(10, 0), 40, "100.00", kind="mark"),
        stop_out(SYMBOL, at(10, 40)),
    ]
    case = make_case(
        equity="100",
        scripted=[
            scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-1"),
            scripted_plan(SYMBOL, SIGNAL_CLOSE + timedelta(hours=1, minutes=30), "sig-2"),
        ],
        trade_minutes=[go_through(SYMBOL, at(10, 1))],
        mark_minutes=mark,
    )
    calls: list[dict[str, Any]] = []
    run = simulate_detailed(case, risk_fn=fixed_risk_fn("60", "50", calls=calls))

    assert run.ledger.equity == Decimal("100") - Decimal("128.304")
    assert len(calls) == 1  # the second setup was never sized
    assert [t["signal_id"] for t in run.output["trades"]] == ["sig-1"]
    assert run.output["run_summary"]["no_trade_counts"] == {"UNCERTAIN_ACCOUNT_STATE": 1}


def test_build_reject_record_refuses_a_reason_outside_the_rejection_vocabulary() -> None:
    with pytest.raises(ValueError, match="RejectionReason"):
        build_reject_record(
            signal_id="sig-1",
            trade_plan_id=None,
            symbol=SYMBOL,
            direction="LONG",
            reason_code="CONFLICT_WITH_OPEN_POSITION",
            bar_close_utc=SIGNAL_CLOSE,
            strategy_version="v4.0.0",
            parameter_set_hash="a" * 64,
        )


def test_build_reject_record_is_deterministic_and_has_no_trade_fields() -> None:
    arguments: dict[str, Any] = {
        "signal_id": "sig-1",
        "trade_plan_id": "tp-1",
        "symbol": SYMBOL,
        "direction": "LONG",
        "reason_code": "MIN_QTY_REJECT",
        "bar_close_utc": SIGNAL_CLOSE,
        "strategy_version": "v4.0.0",
        "parameter_set_hash": "a" * 64,
    }
    first = build_reject_record(**arguments)
    assert first == build_reject_record(**arguments)
    assert (first.outcome_kind, first.entry_kind, first.reason_code) == (
        "REJECT",
        "REJECT",
        "MIN_QTY_REJECT",
    )
    assert first.signal_close_utc == SIGNAL_CLOSE
    assert first.entry_time_utc is first.quantity is first.realized_pnl is None
    other = build_reject_record(**{**arguments, "reason_code": "NOTIONAL_REJECT"})
    assert other.trade_id != first.trade_id


def test_the_rejection_vocabulary_is_unchanged_and_excludes_the_conflict_label() -> None:
    assert len(list(RejectionReason)) == 20
    assert "CONFLICT_WITH_OPEN_POSITION" not in {r.value for r in RejectionReason}
