"""The recorded Demo SL-triggered close reaches the day loss through the stream path.

Phase 21, plan 21-16 (D-09, Pitfall 4). Every Demo value is demo-observed, not mainnet, one
sample: the frames are the verbatim ``triggered_close_position_bracket`` frames of plan 21-08 and
their REST ``userTrades`` row. The frame goes through the REAL parser (``parse_stream_message``
and ``to_fill_event``); the service takes the resulting ``FillEvent``. Expected values are literal
Decimals, never computed by the code under test.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.adapters.binance_usdm import UserTradeRow
from src.adapters.binance_userdata_events import (
    AccountUpdateEvent,
    OrderUpdateEvent,
    parse_stream_message,
    to_fill_event,
)
from src.domain.enums import DailyState
from src.execution.day_risk_service import components_from_fill, components_from_user_trade
from src.execution.fill_monitor import FillEvent
from src.risk.daily_loss import ComponentKind, ComponentSource

from tests.support.day_risk_fakes import build_day_risk_rig

RECORDED = Path(__file__).parent / "fixtures" / "phase21" / "recorded_demo"
FRAMES = RECORDED / "frames"
SL_CLOSE = "triggered_close_position_bracket-010-ORDER_TRADE_UPDATE.json"
ACCOUNT_BEFORE = "triggered_close_position_bracket-003-ACCOUNT_UPDATE.json"
ACCOUNT_AFTER = "triggered_close_position_bracket-009-ACCOUNT_UPDATE.json"
OBSERVED = datetime(2026, 10, 22, 12, 10, 0, tzinfo=UTC)  # TEST_ONLY observation stamp
FILL_TIME = datetime(2026, 10, 22, 12, 9, 23, 58000, tzinfo=UTC)  # frame T 1792670963058 ms
FILL_DAY = date(2026, 10, 22)
KEY = "BTCUSDT:28645789207:549733079"


def _frame(name: str) -> dict[str, Any]:
    loaded = json.loads((FRAMES / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def recorded_fill() -> FillEvent:
    outcome = parse_stream_message(_frame(SL_CLOSE), observed_at_utc=OBSERVED)
    assert isinstance(outcome, OrderUpdateEvent)
    fill = to_fill_event(outcome)
    assert fill is not None
    return fill


def recorded_rest_row() -> UserTradeRow:
    """The REST row of the same trade, mapped field by field from the recorded JSON."""
    rows = json.loads((RECORDED / "user_trades_triggered_bracket.json").read_text(encoding="utf-8"))
    assert len(rows) == 1
    row = rows[0]
    return UserTradeRow(
        symbol=row["symbol"],
        order_id=row["orderId"],
        trade_id=row["id"],
        realized_pnl=Decimal(row["realizedPnl"]),
        commission=Decimal(row["commission"]),
        commission_asset=row["commissionAsset"],
        margin_asset=row["marginAsset"],
        time_utc=datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=row["time"]),
    )


def wallet_balance(name: str) -> Decimal:
    outcome = parse_stream_message(_frame(name), observed_at_utc=OBSERVED)
    assert isinstance(outcome, AccountUpdateEvent)
    usdt = [row for row in outcome.balances if row.asset == "USDT"]
    assert len(usdt) == 1
    return usdt[0].wallet_balance


def test_the_recorded_sl_close_becomes_the_two_stream_components() -> None:
    fill = recorded_fill()
    assert fill.fill_time_utc == FILL_TIME
    components = components_from_fill(fill, quote_asset="USDT")
    assert components is not None
    pnl, commission = components
    # demo-observed, not mainnet: rp -0.00327999, n 0.02616201 USDT
    assert (pnl.kind, pnl.amount, pnl.asset) == (
        ComponentKind.FILL_PNL,
        Decimal("-0.00327999"),
        "USDT",
    )
    assert (commission.kind, commission.amount, commission.asset) == (
        ComponentKind.FILL_COMMISSION,
        Decimal("-0.02616201"),
        "USDT",
    )
    for component in components:
        assert component.source is ComponentSource.USER_DATA_EVENT
        assert component.source_key == KEY
        assert component.event_time_utc == FILL_TIME
        assert component.utc_day == FILL_DAY


def test_the_rest_row_of_the_same_trade_has_the_same_key_and_the_same_amounts() -> None:
    stream = components_from_fill(recorded_fill(), quote_asset="USDT")
    assert stream is not None
    rest = components_from_user_trade(recorded_rest_row())
    assert [c.source_key for c in rest] == [KEY, KEY]
    assert all(c.source is ComponentSource.REST_USER_TRADES for c in rest)
    # No divergence in this sample: stream and REST carry identical amounts, asset and time.
    for from_stream, from_rest in zip(stream, rest, strict=True):
        assert from_stream.kind is from_rest.kind
        assert from_stream.amount == from_rest.amount
        assert from_stream.asset == from_rest.asset
        assert from_stream.event_time_utc == from_rest.event_time_utc


async def test_the_sl_close_reaches_the_day_loss_through_the_stream_path() -> None:
    rig = await build_day_risk_rig(start=FILL_TIME + timedelta(seconds=5))
    now = rig.clock()
    await rig.service.backfill(now_utc=now)  # complete backfill with no trade rows
    rig.service.ingest_fill(recorded_fill())
    verdict = await rig.service.evaluate(now_utc=now, exposure=False)
    assert verdict.state is DailyState.NORMAL  # against the Demo base, demo-observed
    assert verdict.loss_quote == Decimal("0.02944200")  # 0.00327999 + 0.02616201
    stored = rig.store.list_components(FILL_DAY)
    assert [c.source for c in stored] == [ComponentSource.USER_DATA_EVENT] * 2
    assert {c.kind for c in stored} == {ComponentKind.FILL_PNL, ComponentKind.FILL_COMMISSION}
    assert rig.service.current_daily_loss_quote(FILL_DAY) == Decimal("0.02944200")


async def test_the_stream_fill_and_the_rest_row_count_once() -> None:
    rig = await build_day_risk_rig(start=FILL_TIME + timedelta(seconds=5))
    rig.reader.trades["BTCUSDT"] = (recorded_rest_row(),)
    now = rig.clock()
    rig.service.ingest_fill(recorded_fill())
    await rig.service.backfill(now_utc=now)
    verdict = await rig.service.evaluate(now_utc=now, exposure=False)
    assert verdict.loss_quote == Decimal("0.02944200")  # the same trade is not counted twice


def test_wallet_delta_around_the_sl_close_equals_realized_pnl_minus_commission() -> None:
    # demo-observed, not mainnet, one sample, reason ORDER on both frames.
    before = wallet_balance(ACCOUNT_BEFORE)
    after = wallet_balance(ACCOUNT_AFTER)
    assert before == Decimal("4998.74798621")
    assert after == Decimal("4998.71854421")
    assert after - before == Decimal("-0.029442")
    pnl, commission = components_from_fill(recorded_fill(), quote_asset="USDT") or ()
    assert pnl.amount + commission.amount == Decimal("-0.02944200")
    assert after - before == pnl.amount + commission.amount
