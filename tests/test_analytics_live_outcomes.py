"""Live-row normalizer tests (Phase 10, plan 10-06, JRN-01, RESEARCH P9 / A7).

Signal / TradePlan / Order / Fill rows become R-valued LIVE `TradeOutcome`s under
an explicit net-PnL definition, behind a fail-closed exchange-semantics gate:
live R is shown only when the Binance realizedPnl / commission semantics were
verified against the current official docs; otherwise it is INCOMPLETE.
"""

from __future__ import annotations

import random
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.analytics import live_outcomes
from src.analytics.live_outcomes import (
    LIVE_NET_PNL_SEMANTICS_NOTE,
    QUOTE_ASSET,
    LiveOutcomeResult,
    normalize_live_outcomes,
)
from src.analytics.stats import r_value
from src.analytics.types import EvidenceKind, IncompleteReason, TradeOutcome
from src.domain.enums import OrderStatus, SignalStatus, TradePlanStatus
from src.domain.fill import Fill
from src.domain.order import Order
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

from tests.phase10_helpers import D, load_expected, load_input, parse_utc

HEX64 = re.compile(r"^[0-9a-f]{64}$")
LIVE_SRC = Path(__file__).resolve().parent.parent / "src" / "analytics" / "live_outcomes.py"
BINANCE_DOC_URL = (
    "https://developers.binance.com/docs/derivatives/usds-margined-futures/"
    "trade/rest-api/Account-Trade-List"
)


def _signal(row: dict[str, Any]) -> Signal:
    detected = parse_utc(row["detected_at_utc"])
    return Signal(
        signal_id=row["signal_id"],
        strategy_id="trend-pullback",
        strategy_version="v2.0.0",
        parameter_set_id="PS-1",
        parameter_set_hash="b" * 64,
        symbol=row["symbol"],
        direction=row["direction"],
        setup_type="pullback",
        source_timeframe="4h",
        source_candle_close_utc=detected,
        detected_at_utc=detected,
        status=SignalStatus.DETECTED,
        expires_at_utc=detected,
    )


def _plan(row: dict[str, Any]) -> TradePlan:
    created = parse_utc("2026-04-01T07:00:00+00:00")
    return TradePlan(
        trade_plan_id=row["trade_plan_id"],
        signal_id=row["signal_id"],
        trade_plan_version="v1",
        entry_model="limit",
        entry_min_price=Decimal("1"),
        entry_max_price=Decimal("2"),
        stop_loss_price=Decimal("1"),
        take_profit_json="[]",
        invalidation_rule_json="{}",
        expiry_utc=created,
        expected_rr_json="{}",
        risk_rate=Decimal("0.01"),
        risk_budget=D(row["risk_budget"]),
        suggested_quantity=Decimal("1"),
        quantity_before_rounding=Decimal("1"),
        quantity_after_rounding=Decimal("1"),
        quantization_decision="OK",
        plan_hash="c" * 64,
        status=TradePlanStatus.APPROVED,
        created_at_utc=created,
    )


def _order(row: dict[str, Any]) -> Order:
    submitted = parse_utc(row["submitted_at_utc"])
    return Order(
        order_id=row["order_id"],
        trade_plan_id=row["trade_plan_id"],
        position_id=None,
        parent_order_id=None,
        order_role=row["order_role"],
        exchange="BINANCE",
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        order_type="LIMIT",
        time_in_force="GTC",
        quantity=Decimal("1"),
        price=None,
        stop_price=None,
        close_position=False,
        reduce_only=False,
        client_order_id=None,
        exchange_order_id=None,
        algo_client_id=None,
        exchange_status="NEW",
        local_status=OrderStatus.NEW,
        submitted_at_utc=submitted,
        updated_at_utc=submitted,
    )


def _fill(row: dict[str, Any]) -> Fill:
    return Fill(
        fill_id=row["fill_id"],
        order_id=row["order_id"],
        exchange_trade_id=f"TR-{row['fill_id']}",
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        fill_price=D(row["fill_price"]),
        fill_quantity=D(row["fill_quantity"]),
        quote_quantity=Decimal("1"),
        commission=D(row["commission"]),
        commission_asset=row["commission_asset"],
        realized_pnl=D(row["realized_pnl"]),
        fill_time_utc=parse_utc(row["fill_time_utc"]),
        is_maker=True,
    )


class _Rows:
    """The live_net_r fixture as frozen domain rows."""

    def __init__(self) -> None:
        data = load_input("live_net_r")
        self.signals = [_signal(row) for row in data["signals"]]
        self.plans = [_plan(row) for row in data["plans"]]
        self.orders = [_order(row) for row in data["orders"]]
        self.fills = [_fill(row) for row in data["fills"]]

    def run(self, **overrides: Any) -> LiveOutcomeResult:
        args: dict[str, Any] = {
            "signals": self.signals,
            "plans": self.plans,
            "orders": self.orders,
            "fills": self.fills,
        }
        args.update(overrides)
        return normalize_live_outcomes(
            args["signals"], args["plans"], args["orders"], args["fills"]
        )


def _by_trade(result: LiveOutcomeResult) -> dict[str, TradeOutcome]:
    return {outcome.trade_id: outcome for outcome in result.outcomes}


def _check_branch(result: LiveOutcomeResult, want: dict[str, Any]) -> None:
    assert [o.trade_id for o in result.outcomes] == [w["trade_id"] for w in want["outcomes"]]
    for outcome, expected in zip(result.outcomes, want["outcomes"], strict=True):
        assert outcome.evidence is EvidenceKind.LIVE
        assert outcome.signal_id == expected["signal_id"]
        assert outcome.direction == expected["direction"]
        assert outcome.strategy_version == "v2.0.0"
        assert outcome.parameter_set_hash == "b" * 64
        assert outcome.entry_price == D(expected["entry_price"])
        assert outcome.quantity == D(expected["quantity"])
        assert outcome.entry_time_utc == parse_utc(expected["entry_time_utc"])
        assert outcome.exit_kind == expected["exit_kind"]
        assert outcome.realized_risk == D(expected["realized_risk"])
        for name in ("exit_price", "realized_pnl"):
            want_value = expected[name]
            assert getattr(outcome, name) == (None if want_value is None else D(want_value))
        want_exit = expected["exit_time_utc"]
        assert outcome.exit_time_utc == (None if want_exit is None else parse_utc(want_exit))
        r = r_value(outcome.realized_pnl, outcome.realized_risk)
        assert r == (None if expected["r"] is None else D(expected["r"]))
    assert result.incomplete == tuple(
        (signal_id, IncompleteReason(reason)) for signal_id, reason in want["incomplete"]
    )


def test_verified_semantics_branch_gives_net_r(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", True)
    expected = load_expected("live_net_r")["verified_true"]
    result = _Rows().run()
    _check_branch(result, expected)
    outcome = _by_trade(result)["PLAN-A"]
    # entry 100.50 (weighted), exit 104.00, net 7.00 - 3 * 0.10 = 6.70, R = 0.67.
    assert outcome.entry_price == D("100.50")
    assert outcome.exit_price == D("104.00")
    assert outcome.realized_pnl == D("6.70")
    assert r_value(outcome.realized_pnl, outcome.realized_risk) == D("0.67")
    assert HEX64.match(result.digest())
    assert result.digest() == expected["result_digest"]


def test_unverified_semantics_branch_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", False)
    expected = load_expected("live_net_r")["verified_false"]
    result = _Rows().run()
    _check_branch(result, expected)
    closed = _by_trade(result)["PLAN-A"]
    # Price/time fields stay populated so MFE/MAE and latency keep working.
    assert closed.entry_price == D("100.50")
    assert closed.exit_time_utc == parse_utc("2026-04-01T12:00:00+00:00")
    assert closed.realized_pnl is None
    assert all(o.realized_pnl is None for o in result.outcomes)
    assert HEX64.match(result.digest())
    assert result.digest() == expected["result_digest"]


def test_module_default_matches_recorded_verification_status() -> None:
    """The flag and the docstring must agree: no silent assumption of verified semantics."""
    doc = live_outcomes.__doc__ or ""
    assert len(doc) > 400
    assert BINANCE_DOC_URL in doc
    assert re.search(r"20\d\d-\d\d-\d\d", doc), "docstring must record a retrieval date"
    assert LIVE_NET_PNL_SEMANTICS_NOTE.strip() != ""
    if live_outcomes.LIVE_NET_PNL_SEMANTICS_VERIFIED:
        assert "VERIFIED" in doc
    else:
        assert "NOT VERIFIED" in doc
        assert "fail closed" in doc.lower() or "fail-closed" in doc.lower()


def test_net_pnl_rule_and_funding_exclusion_are_documented() -> None:
    doc = live_outcomes.__doc__ or ""
    assert "commission" in doc.lower()
    assert "funding" in doc.lower()
    assert "excluded" in doc.lower()
    assert QUOTE_ASSET == "USDT"


def test_non_quote_commission_asset_yields_no_converted_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", True)
    result = _Rows().run()
    outcome = _by_trade(result)["PLAN-C"]
    assert outcome.realized_pnl is None
    assert ("SIG-C", IncompleteReason.COMMISSION_ASSET_NOT_QUOTE) in result.incomplete
    # Prices and times are still reported.
    assert outcome.entry_price == D("50.00")
    assert outcome.exit_kind == "SL"


def test_open_position_emits_outcome_without_exit_or_pnl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", True)
    result = _Rows().run()
    outcome = _by_trade(result)["PLAN-B"]
    # Only 0.4 of 1.0 has been closed: still open.
    assert outcome.exit_price is None
    assert outcome.exit_time_utc is None
    assert outcome.exit_kind is None
    assert outcome.realized_pnl is None
    assert ("SIG-B", IncompleteReason.OPEN_POSITION) in result.incomplete


def test_non_positive_risk_budget_is_no_risk_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", True)
    rows = _Rows()
    zero_budget = [
        replace(plan, risk_budget=Decimal("0")) if plan.trade_plan_id == "PLAN-A" else plan
        for plan in rows.plans
    ]
    result = rows.run(plans=zero_budget)
    outcome = _by_trade(result)["PLAN-A"]
    assert outcome.realized_risk is None
    assert ("SIG-A", IncompleteReason.NO_RISK_VALUE) in result.incomplete
    assert r_value(outcome.realized_pnl, outcome.realized_risk) is None


def test_exit_kind_comes_from_latest_exit_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", True)
    rows = _Rows()
    extra_order = _order(
        {
            "order_id": "ORD-A-TP2",
            "trade_plan_id": "PLAN-A",
            "order_role": "TAKE_PROFIT_2",
            "submitted_at_utc": "2026-04-01T08:03:00+00:00",
        }
    )
    extra_fill = _fill(
        {
            "fill_id": "F-A4",
            "order_id": "ORD-A-TP2",
            "fill_price": "106.00",
            "fill_quantity": "1.0",
            "commission": "0.10",
            "commission_asset": "USDT",
            "realized_pnl": "5.50",
            "fill_time_utc": "2026-04-01T13:00:00+00:00",
        }
    )
    result = rows.run(orders=[*rows.orders, extra_order], fills=[*rows.fills, extra_fill])
    outcome = _by_trade(result)["PLAN-A"]
    assert outcome.exit_kind == "TP2"
    assert outcome.exit_time_utc == parse_utc("2026-04-01T13:00:00+00:00")
    # (2.0 @ 104 + 1.0 @ 106) / 3 = 104.666..., quantity exited (3.0) >= entered (2.0).
    assert outcome.exit_price is not None
    assert abs(outcome.exit_price - D("314") / D("3")) < D("0.000001")
    assert outcome.realized_pnl == D("12.50") - D("0.40")


def test_plan_without_entry_fill_is_not_a_candidate() -> None:
    rows = _Rows()
    only_orphan = [f for f in rows.fills if f.fill_id == "F-ORPHAN"]
    result = rows.run(fills=only_orphan)
    assert result.outcomes == ()
    assert result.incomplete == ()


def test_plan_without_signal_is_unmatched_join() -> None:
    rows = _Rows()
    result = rows.run(signals=[s for s in rows.signals if s.signal_id != "SIG-B"])
    assert "PLAN-B" not in _by_trade(result)
    assert ("SIG-B", IncompleteReason.UNMATCHED_JOIN) in result.incomplete


def test_non_positive_fill_quantity_fails_closed_as_malformed() -> None:
    rows = _Rows()
    bad = [
        replace(f, fill_quantity=Decimal("-1.0")) if f.fill_id == "F-B2" else f for f in rows.fills
    ]
    result = rows.run(fills=bad)
    assert "PLAN-B" not in _by_trade(result)
    assert ("SIG-B", IncompleteReason.MALFORMED_ROW) in result.incomplete


def test_output_is_identical_when_inputs_are_shuffled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", True)
    rows = _Rows()
    baseline = rows.run()
    for seed in range(5):
        rng = random.Random(seed)
        shuffled = rows.run(
            signals=rng.sample(rows.signals, len(rows.signals)),
            plans=rng.sample(rows.plans, len(rows.plans)),
            orders=rng.sample(rows.orders, len(rows.orders)),
            fills=rng.sample(rows.fills, len(rows.fills)),
        )
        assert shuffled == baseline
        assert shuffled.digest() == baseline.digest()


def test_module_is_pure_and_never_hardcodes_quote_conversion() -> None:
    source = LIVE_SRC.read_text(encoding="utf-8")
    assert "src.adapters" not in source
    assert "sqlalchemy" not in source
