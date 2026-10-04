"""Backtest/live R-denominator parity (Phase 14, plan 14-06, D-20, D-29, BKTS-04, F-204).

One trade is pushed through two independent paths and must come out with the same
`realized_risk` and the same R multiple:

* backtest: ``advance`` -> ``build_trade_record`` -> ``normalize_backtest``
* live: Signal / TradePlan / Order / Fill rows -> ``normalize_live_outcomes`` with the
  sized figure supplied through ``sized_risks`` (D-29: it is not persisted for live)

Both paths divide by ``realized_risk_for_fill(sized, planned, filled)``;
``TradePlan.risk_budget`` (equity x rate) is deliberately set to a different number so
it cannot be the denominator. Funding is zero on both sides because live R excludes
funding (D-29, ``LIVE_R_EXCLUDES``). Modeled slippage is zero because a live fill price
already embeds slippage, so the backtest cost model books fees only here.

Hand oracle (LONG, limit 100.00, stop 98.00, tick 0.10, sized risk 50, planned 0.5):

    filled 0.5   gross -1.00  entry fee 0.0200  exit fee 0.0196  pnl -1.0396
                 realized_risk 50      R = -1.0396 / 50 = -0.020792
    filled 0.25  gross -0.50  entry fee 0.0100  exit fee 0.0098  pnl -0.5198
                 realized_risk 25      R = -0.5198 / 25 = -0.020792
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from src.analytics import live_outcomes
from src.analytics.inputs import normalize_backtest
from src.analytics.live_outcomes import normalize_live_outcomes
from src.analytics.stats import r_value
from src.analytics.types import EvidenceKind, IncompleteReason, TradeOutcome
from src.backtest.costs import CostModel
from src.backtest.lifecycle import advance, new_plan_state
from src.backtest.records import TradeRecord, build_trade_record
from src.backtest.series import ListMinuteSource
from src.core.types import Candle
from src.domain.enums import OrderStatus, SignalStatus
from src.domain.fill import Fill
from src.domain.order import Order
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

from tests.backtest_plan_helpers import make_minute, make_trade_plan

SYMBOL = "BTCUSDT"
SIGNAL_CLOSE = datetime(2026, 1, 5, 9, 59, 59, 999000, tzinfo=UTC)
WINDOW_END = datetime(2026, 1, 5, 10, 5, 59, 999000, tzinfo=UTC)
TICK = Decimal("0.10")
SIZED_RISK = Decimal("50")
PLANNED_QUANTITY = Decimal("0.5")
TRADE_PLAN_ID = "tp-parity"
SIGNAL_ID = "sig-parity"
PARAMETER_SET_HASH = "b" * 64


def _minute(hour_minute: tuple[int, int], o: str, h: str, low: str, c: str, kind: str) -> Candle:
    return make_minute(
        SYMBOL,
        datetime(2026, 1, 5, hour_minute[0], hour_minute[1], tzinfo=UTC),
        o,
        h,
        low,
        c,
        kind,
    )


def _source() -> ListMinuteSource:
    """Touch at 10:00, trade-through fill at 10:01 and a mark-price stop on the fill minute."""
    return ListMinuteSource(
        trade={
            SYMBOL: [
                _minute((10, 0), "100.50", "100.80", "100.00", "100.40", "trade"),
                _minute((10, 1), "100.40", "100.50", "99.90", "100.20", "trade"),
                _minute((10, 2), "101.00", "101.50", "100.90", "101.20", "trade"),
            ]
        },
        mark={
            SYMBOL: [
                _minute((10, 0), "100.50", "100.80", "99.00", "100.40", "mark"),
                _minute((10, 1), "100.10", "100.30", "97.90", "98.50", "mark"),
                _minute((10, 2), "98.50", "99.00", "97.00", "97.50", "mark"),
            ]
        },
    )


def _fee_only_cost_model() -> CostModel:
    return CostModel(
        fee_rate_entry=Decimal("0.0004"),
        fee_rate_exit=Decimal("0.0004"),
        funding_treatment="ADDITIVE",
        expected_slippage=Decimal("0"),
        slippage_model="FIXED_RATE",
        spread_fill_assumptions="TAKER",
        partial_fill_fraction=Decimal("1"),
        cost_model_hash="",
        exit_slippage_rate=Decimal("0"),
    )


def _plan() -> TradePlan:
    # risk_budget (equity x rate) is intentionally NOT the sized figure.
    return make_trade_plan(
        "LONG",
        entry_min="99.00",
        entry_max="101.00",
        stop_loss="98.00",
        signal_close_utc=SIGNAL_CLOSE,
        trade_plan_id=TRADE_PLAN_ID,
        signal_id=SIGNAL_ID,
        risk_budget="1.50",
    )


def _backtest(filled_quantity: Decimal) -> tuple[TradeRecord, TradeOutcome]:
    state = new_plan_state(
        plan=_plan(),
        symbol=SYMBOL,
        direction="LONG",
        signal_close_utc=SIGNAL_CLOSE,
        price_tick_size=TICK,
        planned_quantity=PLANNED_QUANTITY,
        sized_realized_risk=SIZED_RISK,
        fill_quantity=filled_quantity,
    )
    final, _ = advance(
        state,
        source=_source(),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    record = build_trade_record(
        state=final,
        strategy_version="v2.0.0",
        parameter_set_hash=PARAMETER_SET_HASH,
        cost_model=_fee_only_cost_model(),
        funding_amount=Decimal("0"),
        funding_event_count=0,
        regime=None,
        constraints_extrapolated=False,
    )
    outcomes = normalize_backtest([record]).outcomes
    assert len(outcomes) == 1
    return record, outcomes[0]


def _signal() -> Signal:
    return Signal(
        signal_id=SIGNAL_ID,
        strategy_id="trend-pullback",
        strategy_version="v2.0.0",
        parameter_set_id="PS-1",
        parameter_set_hash=PARAMETER_SET_HASH,
        symbol=SYMBOL,
        direction="LONG",
        setup_type="pullback",
        source_timeframe="4h",
        source_candle_close_utc=SIGNAL_CLOSE,
        detected_at_utc=SIGNAL_CLOSE,
        status=SignalStatus.DETECTED,
        expires_at_utc=SIGNAL_CLOSE,
    )


def _order(order_id: str, role: str, side: str, submitted: datetime) -> Order:
    return Order(
        order_id=order_id,
        trade_plan_id=TRADE_PLAN_ID,
        position_id=None,
        parent_order_id=None,
        order_role=role,
        exchange="BINANCE",
        symbol=SYMBOL,
        side=side,
        position_side="BOTH",
        order_type="LIMIT",
        time_in_force="GTC",
        quantity=PLANNED_QUANTITY,
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


def _fill(
    fill_id: str,
    order_id: str,
    side: str,
    price: Decimal,
    quantity: Decimal,
    commission: Decimal,
    realized_pnl: Decimal,
    when: datetime,
) -> Fill:
    return Fill(
        fill_id=fill_id,
        order_id=order_id,
        exchange_trade_id=f"TR-{fill_id}",
        symbol=SYMBOL,
        side=side,
        position_side="BOTH",
        fill_price=price,
        fill_quantity=quantity,
        quote_quantity=Decimal("1"),
        commission=commission,
        commission_asset="USDT",
        realized_pnl=realized_pnl,
        fill_time_utc=when,
        is_maker=True,
    )


def _live(record: TradeRecord, **kwargs: object) -> live_outcomes.LiveOutcomeResult:
    """The same trade as live rows: identical prices, quantities, fees and times."""
    assert record.entry_price is not None and record.exit_price is not None
    assert record.entry_time_utc is not None and record.exit_time_utc is not None
    assert record.quantity is not None
    assert record.entry_fee is not None and record.exit_fee is not None
    assert record.gross_pnl is not None
    orders = [
        _order("ORD-ENTRY", "ENTRY", "BUY", record.signal_close_utc or SIGNAL_CLOSE),
        _order("ORD-SL", "STOP_LOSS", "SELL", record.signal_close_utc or SIGNAL_CLOSE),
    ]
    fills = [
        _fill(
            "F-ENTRY",
            "ORD-ENTRY",
            "BUY",
            record.entry_price,
            record.quantity,
            record.entry_fee,
            Decimal("0"),
            record.entry_time_utc,
        ),
        _fill(
            "F-EXIT",
            "ORD-SL",
            "SELL",
            record.exit_price,
            record.quantity,
            record.exit_fee,
            record.gross_pnl,
            record.exit_time_utc,
        ),
    ]
    return normalize_live_outcomes([_signal()], [_plan()], orders, fills, **kwargs)  # type: ignore[arg-type]


def _sized_risks() -> dict[str, object]:
    return {
        TRADE_PLAN_ID: live_outcomes.SizedRisk(
            realized_risk=SIZED_RISK, planned_quantity=PLANNED_QUANTITY
        )
    }


@pytest.mark.parametrize(
    ("filled", "expected_risk", "expected_r"),
    [
        (Decimal("0.5"), Decimal("50"), Decimal("-0.020792")),
        (Decimal("0.25"), Decimal("25"), Decimal("-0.020792")),
    ],
)
def test_backtest_and_live_share_one_denominator_and_one_r(
    monkeypatch: pytest.MonkeyPatch,
    filled: Decimal,
    expected_risk: Decimal,
    expected_r: Decimal,
) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", True)
    record, backtest = _backtest(filled)
    live_result = _live(record, sized_risks=_sized_risks())

    assert len(live_result.outcomes) == 1
    live = live_result.outcomes[0]
    assert backtest.evidence is EvidenceKind.BACKTEST
    assert live.evidence is EvidenceKind.LIVE
    assert backtest.realized_risk == expected_risk
    assert live.realized_risk == expected_risk
    assert live.realized_risk == backtest.realized_risk
    # Same trade, same fees, zero funding and zero modeled slippage: same net PnL.
    assert backtest.realized_pnl == live.realized_pnl
    backtest_r = r_value(backtest.realized_pnl, backtest.realized_risk)
    live_r = r_value(live.realized_pnl, live.realized_risk)
    assert backtest_r == live_r
    assert backtest_r == expected_r
    # No INCOMPLETE listing: the live path had everything it needs.
    assert live_result.incomplete == ()


def test_live_without_sized_risk_is_incomplete_even_with_a_positive_risk_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", True)
    record, _ = _backtest(PLANNED_QUANTITY)
    plan = _plan()
    assert plan.risk_budget > 0  # the old denominator is available and must NOT be used
    live_result = _live(record)

    assert len(live_result.outcomes) == 1
    live = live_result.outcomes[0]
    assert live.realized_risk is None
    assert (SIGNAL_ID, IncompleteReason.NO_RISK_VALUE) in live_result.incomplete
    assert r_value(live.realized_pnl, live.realized_risk) is None


def test_sized_risk_for_an_unrelated_plan_does_not_supply_a_denominator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_outcomes, "LIVE_NET_PNL_SEMANTICS_VERIFIED", True)
    record, _ = _backtest(PLANNED_QUANTITY)
    other = {
        "some-other-plan": live_outcomes.SizedRisk(
            realized_risk=SIZED_RISK, planned_quantity=PLANNED_QUANTITY
        )
    }
    live_result = _live(record, sized_risks=other)
    assert live_result.outcomes[0].realized_risk is None
    assert (SIGNAL_ID, IncompleteReason.NO_RISK_VALUE) in live_result.incomplete
