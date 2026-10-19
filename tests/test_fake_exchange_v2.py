"""BinanceSemanticsFakeAdapter v2 (plan 19-10): positions, partial fills, closePosition rules.

The fake models documented or Demo-observed exchange rules and labels each assumption in its
module docstring ([DOC], [DEMO], [ASSUMED]). These tests prove the fake behaves as the labels
say; they are not evidence of mainnet behavior.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures import BadRequestError

from tests.support.fake_binance_exchange import (
    FLAT_CLOSE_POSITION_CODE,
    STATUS_CANCELED,
    STATUS_FILLED,
    STATUS_NEW,
    STATUS_PARTIALLY_FILLED,
    BinanceSemanticsFakeAdapter,
)

SYMBOL = "BTCUSDT"
ENTRY_ID = "test-only-entry-0001"
STOP_ID = "test-only-stop-0001"
CLOSE_ID = "test-only-close-0001"


def _entry_kwargs(
    *, client_id: str = ENTRY_ID, side: str = "BUY", quantity: str = "0.010", symbol: str = SYMBOL
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "side": side,
        "position_side": "BOTH",
        "time_in_force": "GTD",
        "quantity": Decimal(quantity),
        "price": Decimal("100.00"),
        "new_client_order_id": client_id,
        "good_till_date": 1_900_000_000_000,
    }


def _stop_kwargs(
    *,
    client_id: str = STOP_ID,
    side: str = "SELL",
    close_position: bool = True,
    quantity: Decimal | None = None,
    symbol: str = SYMBOL,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "side": side,
        "algo_type": "CONDITIONAL",
        "type": "STOP_MARKET",
        "position_side": "BOTH",
        "trigger_price": Decimal("95.00"),
        "close_position": close_position,
        "quantity": quantity,
        "working_type": "MARK_PRICE",
        "client_algo_id": client_id,
    }


def _strict() -> BinanceSemanticsFakeAdapter:
    return BinanceSemanticsFakeAdapter(enforce_flat_stop_rejection=True)


# --------------------------------------------------------------------------- #
# Task 1 (tracer): partial fill, REST view, closePosition stop with a position.
# --------------------------------------------------------------------------- #


async def test_tracer_partial_fill_probe_position_and_close_position_stop() -> None:
    fake = _strict()
    await fake.place_entry(**_entry_kwargs())

    fake.fill(ENTRY_ID, quantity=Decimal("0.004"), price=Decimal("101.00"))

    # The entry stays open as PARTIALLY_FILLED and its client id is still taken.
    assert fake.open_orders[ENTRY_ID].status == STATUS_PARTIALLY_FILLED
    probe = await fake.query_order_by_client(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    assert probe.found is True
    assert probe.status == STATUS_PARTIALLY_FILLED
    assert probe.executed_quantity == Decimal("0.004")
    assert probe.average_price == Decimal("101.00")

    positions = await fake.snapshot_positions(symbol=SYMBOL)
    assert [p.position_amt for p in positions] == [Decimal("0.004")]

    # One fill event with a trade id of its own.
    assert len(fake.fill_events) == 1
    event = fake.fill_events[0]
    assert event.fill_quantity == Decimal("0.004")
    assert event.fill_price == Decimal("101.00")
    assert event.order_id == fake.open_orders[ENTRY_ID].exchange_id

    # With a position the closePosition stop is accepted as NEW and queries as NEW.
    placed = await fake.place_algo_protective(**_stop_kwargs())
    assert placed.algo_status == STATUS_NEW
    algo_probe = await fake.query_algo_order_by_client(client_algo_id=STOP_ID)
    assert algo_probe.found is True
    assert algo_probe.algo_status == STATUS_NEW


async def test_close_position_stop_while_flat_raises_4509_and_is_recorded() -> None:
    fake = _strict()
    with pytest.raises(BadRequestError) as caught:
        await fake.place_algo_protective(**_stop_kwargs())
    assert caught.value.status_code == FLAT_CLOSE_POSITION_CODE == -4509
    # The attempt is in the call record; nothing rests on the exchange.
    assert [c["method"] for c in fake.calls] == ["place_algo_protective"]
    assert fake.open_algos == {}


async def test_explicit_quantity_stop_while_flat_is_accepted() -> None:
    # [DEMO] 18-probe-check.txt line 37: an explicit-quantity reduce-only STOP_MARKET placed
    # while flat was accepted (NEW); only the closePosition variant answered -4509.
    fake = _strict()
    placed = await fake.place_algo_protective(
        **_stop_kwargs(close_position=False, quantity=Decimal("0.010"))
    )
    assert placed.algo_status == STATUS_NEW


async def test_full_fill_keeps_old_behavior_and_moves_the_position() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await fake.place_entry(**_entry_kwargs())
    fake.fill(ENTRY_ID)  # no quantity: the old full fill
    assert ENTRY_ID not in fake.open_orders
    assert fake.history[ENTRY_ID].status == STATUS_FILLED
    positions = await fake.snapshot_positions(symbol=SYMBOL)
    assert [p.position_amt for p in positions] == [Decimal("0.010")]
    assert fake.fill_events[0].fill_quantity == Decimal("0.010")


async def test_second_partial_completes_the_order_and_averages_the_price() -> None:
    fake = _strict()
    await fake.place_entry(**_entry_kwargs())
    fake.fill(ENTRY_ID, quantity=Decimal("0.004"), price=Decimal("101.00"))
    fake.fill(ENTRY_ID, quantity=Decimal("0.006"), price=Decimal("102.00"))
    assert fake.history[ENTRY_ID].status == STATUS_FILLED
    probe = await fake.query_order_by_client(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    assert probe.executed_quantity == Decimal("0.010")
    assert probe.average_price == Decimal("101.60")
    assert len({e.exchange_trade_id for e in fake.fill_events}) == 2


async def test_fill_above_the_remaining_quantity_is_a_test_error() -> None:
    fake = _strict()
    await fake.place_entry(**_entry_kwargs())
    with pytest.raises(ValueError, match="remaining"):
        fake.fill(ENTRY_ID, quantity=Decimal("0.011"))


async def test_short_entry_fill_gives_a_negative_position() -> None:
    fake = _strict()
    await fake.place_entry(**_entry_kwargs(side="SELL"))
    fake.fill(ENTRY_ID)
    positions = await fake.snapshot_positions(symbol=SYMBOL)
    assert [p.position_amt for p in positions] == [Decimal("-0.010")]


async def test_cancel_of_a_partially_filled_entry_keeps_its_executed_quantity() -> None:
    fake = _strict()
    await fake.place_entry(**_entry_kwargs())
    fake.fill(ENTRY_ID, quantity=Decimal("0.004"), price=Decimal("101.00"))
    await fake.cancel_normal_order(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    assert ENTRY_ID not in fake.open_orders
    assert fake.history[ENTRY_ID].status == STATUS_CANCELED
    probe = await fake.query_order_by_client(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    assert probe.status == STATUS_CANCELED
    assert probe.executed_quantity == Decimal("0.004")
    # The position the fill opened stays.
    assert [p.position_amt for p in await fake.snapshot_positions()] == [Decimal("0.004")]


async def test_cancel_of_a_filled_entry_is_a_no_op() -> None:
    fake = _strict()
    await fake.place_entry(**_entry_kwargs())
    fake.fill(ENTRY_ID)
    await fake.cancel_normal_order(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    assert fake.history[ENTRY_ID].status == STATUS_FILLED


def test_default_fake_does_not_enforce_the_flat_stop_rule() -> None:
    # The pre-Phase-19 manager places its closePosition stop right after the entry ack, so
    # the legacy tests need the lenient default; the Phase 19 flow tests opt in.
    assert BinanceSemanticsFakeAdapter().enforce_flat_stop_rejection is False
