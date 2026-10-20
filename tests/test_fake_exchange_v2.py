"""BinanceSemanticsFakeAdapter v2 (plan 19-10): positions, partial fills, closePosition rules.

The fake models documented or Demo-observed exchange rules and labels each assumption in its
module docstring ([DOC], [DEMO], [ASSUMED]). These tests prove the fake behaves as the labels
say; they are not evidence of mainnet behavior.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures import BadRequestError
from src.adapters.binance_errors import error_facts_from_exception
from src.adapters.binance_public import MarkPriceReading
from src.adapters.binance_usdm import (
    MarketCloseResult,
    OpenAlgoOrderSnapshot,
    OpenOrderSnapshot,
)
from src.domain.lot_filters import LotFilters

from tests.support.fake_binance_exchange import (
    FLAT_CLOSE_POSITION_CODE,
    STATUS_CANCELED,
    STATUS_FILLED,
    STATUS_FINISHED,
    STATUS_NEW,
    STATUS_PARTIALLY_FILLED,
    BinanceSemanticsFakeAdapter,
)
from tests.support.virtual_time import yield_to_loop

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


# --------------------------------------------------------------------------- #
# Task 2: exchange reads, stop trigger, MARKET close, lot filters.
# --------------------------------------------------------------------------- #

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _lot_filters(symbol: str = SYMBOL) -> LotFilters:
    # TEST_ONLY numbers; not exchange values.
    return LotFilters(
        symbol=symbol,
        price_tick_size=Decimal("0.10"),
        lot_min_quantity=Decimal("0.001"),
        lot_max_quantity=Decimal("1000"),
        lot_step_size=Decimal("0.001"),
        market_lot_min_quantity=Decimal("0.001"),
        market_lot_max_quantity=Decimal("120"),
        market_lot_step_size=Decimal("0.001"),
        min_notional=Decimal("100"),
    )


async def _open_long(fake: BinanceSemanticsFakeAdapter, quantity: str = "0.010") -> None:
    await fake.place_entry(**_entry_kwargs(quantity=quantity))
    fake.fill(ENTRY_ID)


async def test_mark_price_is_served_and_an_unset_symbol_raises() -> None:
    fake = _strict()
    fake.set_mark_price(SYMBOL, Decimal("100.50"), NOW)
    reading = await fake.get_mark_price(symbol=SYMBOL)
    assert isinstance(reading, MarkPriceReading)
    assert (reading.symbol, reading.mark_price, reading.exchange_time_utc) == (
        SYMBOL,
        Decimal("100.50"),
        NOW,
    )
    with pytest.raises(RuntimeError, match="ETHUSDT"):
        await fake.get_mark_price(symbol="ETHUSDT")
    configured = TimeoutError("configured")
    fake.set_mark_price_error(configured)
    with pytest.raises(TimeoutError) as caught:
        await fake.get_mark_price(symbol="ETHUSDT")
    assert caught.value is configured
    # A symbol that has a price is still served.
    assert (await fake.get_mark_price(symbol=SYMBOL)).mark_price == Decimal("100.50")


async def test_last_price_is_served_separately_and_an_unset_symbol_raises() -> None:
    """Quick task 261020-l4p: the last price is its own state, never the mark price."""
    from src.adapters.binance_public import LastPriceReading

    fake = _strict()
    fake.set_mark_price(SYMBOL, Decimal("100.50"), NOW)
    with pytest.raises(RuntimeError, match="no last price set for BTCUSDT"):
        await fake.get_last_price(symbol=SYMBOL)
    fake.set_last_price(SYMBOL, Decimal("100.40"), NOW)
    reading = await fake.get_last_price(symbol=SYMBOL)
    assert isinstance(reading, LastPriceReading)
    assert (reading.symbol, reading.last_price, reading.exchange_time_utc) == (
        SYMBOL,
        Decimal("100.40"),
        NOW,
    )
    configured = TimeoutError("configured")
    fake.set_last_price_error(configured)
    with pytest.raises(TimeoutError) as caught:
        await fake.get_last_price(symbol="ETHUSDT")
    assert caught.value is configured
    with pytest.raises(TypeError):
        await fake.get_last_price(symbol=SYMBOL, unexpected=True)


async def test_open_order_and_algo_snapshots_are_scoped_by_symbol() -> None:
    fake = _strict()
    await fake.place_entry(**_entry_kwargs())
    await fake.place_entry(**_entry_kwargs(client_id="test-only-entry-0002", symbol="ETHUSDT"))
    fake.fill(ENTRY_ID, quantity=Decimal("0.004"), price=Decimal("101.00"))
    await fake.place_algo_protective(**_stop_kwargs())

    btc = await fake.snapshot_open_normal_orders(symbol=SYMBOL)
    assert [(o.client_order_id, o.status, o.quantity) for o in btc] == [
        (ENTRY_ID, STATUS_PARTIALLY_FILLED, Decimal("0.010"))
    ]
    assert isinstance(btc[0], OpenOrderSnapshot)
    assert len(await fake.snapshot_open_normal_orders()) == 2
    assert len(await fake.snapshot_open_normal_orders(symbol="XRPUSDT")) == 0

    algos = await fake.snapshot_open_algo_orders(symbol=SYMBOL)
    assert isinstance(algos[0], OpenAlgoOrderSnapshot)
    assert [(a.client_algo_id, a.close_position, a.trigger_price) for a in algos] == [
        (STOP_ID, True, Decimal("95.00"))
    ]
    assert await fake.snapshot_open_algo_orders(symbol="ETHUSDT") == []


async def test_trigger_stop_consumes_the_position_and_finishes_the_algo() -> None:
    fake = _strict()
    await _open_long(fake)
    await fake.place_algo_protective(**_stop_kwargs())

    fake.trigger_stop(STOP_ID)

    assert await fake.snapshot_positions(symbol=SYMBOL) == []
    assert STOP_ID not in fake.open_algos
    probe = await fake.query_algo_order_by_client(client_algo_id=STOP_ID)
    assert probe.algo_status == STATUS_FINISHED
    assert await fake.snapshot_open_algo_orders() == []
    assert fake.algo_history[STOP_ID].status == STATUS_FINISHED


async def test_fill_after_the_stop_triggered_opens_a_new_position() -> None:
    # The B4 race: the entry remainder is still open when the stop closes the position.
    fake = _strict()
    await fake.place_entry(**_entry_kwargs())
    fake.fill(ENTRY_ID, quantity=Decimal("0.004"), price=Decimal("101.00"))
    await fake.place_algo_protective(**_stop_kwargs())
    fake.trigger_stop(STOP_ID)
    assert await fake.snapshot_positions() == []

    fake.fill(ENTRY_ID, quantity=Decimal("0.006"), price=Decimal("99.00"))

    positions = await fake.snapshot_positions(symbol=SYMBOL)
    assert [(p.position_amt, p.entry_price) for p in positions] == [
        (Decimal("0.006"), Decimal("99.00"))
    ]


async def test_market_close_reduces_the_position() -> None:
    fake = _strict()
    await _open_long(fake)
    fake.set_mark_price(SYMBOL, Decimal("102.00"), NOW)

    result = await fake.place_market_close(
        symbol=SYMBOL,
        side="SELL",
        position_side="BOTH",
        quantity=Decimal("0.004"),
        new_client_order_id=CLOSE_ID,
    )

    assert isinstance(result, MarketCloseResult)
    assert result.status == STATUS_FILLED
    assert result.executed_quantity == Decimal("0.004")
    assert result.average_price == Decimal("102.00")
    assert [p.position_amt for p in await fake.snapshot_positions()] == [Decimal("0.006")]
    probe = await fake.query_order_by_client(symbol=SYMBOL, orig_client_order_id=CLOSE_ID)
    assert (probe.status, probe.executed_quantity) == (STATUS_FILLED, Decimal("0.004"))


async def test_market_close_on_a_short_position_buys() -> None:
    fake = _strict()
    await fake.place_entry(**_entry_kwargs(side="SELL"))
    fake.fill(ENTRY_ID)
    await fake.place_market_close(
        symbol=SYMBOL,
        side="BUY",
        position_side="BOTH",
        quantity=Decimal("0.010"),
        new_client_order_id=CLOSE_ID,
    )
    assert await fake.snapshot_positions() == []


@pytest.mark.parametrize(
    ("setup", "quantity", "code"),
    [
        ("flat", "0.010", -2022),  # TEST CONVENTION for a flat position (research A4/A8)
        ("long", "0.011", -2024),  # above the position
        ("long_wrong_side", "0.010", -2022),  # a reduce-only order that would add exposure
    ],
)
async def test_market_close_rejections_use_sdk_errors_with_int_codes(
    setup: str, quantity: str, code: int
) -> None:
    fake = _strict()
    if setup != "flat":
        await _open_long(fake)
    side = "BUY" if setup == "long_wrong_side" else "SELL"
    with pytest.raises(BadRequestError) as caught:
        await fake.place_market_close(
            symbol=SYMBOL,
            side=side,
            position_side="BOTH",
            quantity=Decimal(quantity),
            new_client_order_id=CLOSE_ID,
        )
    assert caught.value.status_code == code
    assert isinstance(caught.value.status_code, int)
    # The call is recorded and the position is untouched.
    assert fake.calls_to("place_market_close")
    expected = [] if setup == "flat" else [Decimal("0.010")]
    assert [p.position_amt for p in await fake.snapshot_positions()] == expected


def test_the_flat_close_code_is_a_labelled_test_convention() -> None:
    source = (Path(__file__).parent / "support" / "fake_binance_exchange.py").read_text(
        encoding="utf-8"
    )
    assert "TEST CONVENTION" in source
    assert "UNPROVEN" in source


async def test_market_close_ack_only_reports_no_execution_but_moves_the_position() -> None:
    fake = _strict()
    fake.market_close_ack_only = True
    await _open_long(fake)
    result = await fake.place_market_close(
        symbol=SYMBOL,
        side="SELL",
        position_side="BOTH",
        quantity=Decimal("0.010"),
        new_client_order_id=CLOSE_ID,
    )
    assert result.status == STATUS_NEW
    assert result.executed_quantity is None
    assert await fake.snapshot_positions() == []


async def test_lot_filters_are_served_and_unset_raises() -> None:
    fake = _strict()
    filters = _lot_filters()
    fake.set_lot_filters(SYMBOL, filters)
    assert await fake.symbol_lot_filters(symbol=SYMBOL) == filters
    with pytest.raises(ValueError, match="ETHUSDT"):
        await fake.symbol_lot_filters(symbol="ETHUSDT")


def test_error_facts_match_the_real_adapter() -> None:
    fake = _strict()
    exc = BadRequestError(error_message="x", status_code=-4509)
    assert fake.error_facts(exc) == error_facts_from_exception(exc)
    assert fake.error_facts(exc).code == -4509


async def test_new_methods_bind_against_the_real_adapter_signature() -> None:
    fake = _strict()
    with pytest.raises(TypeError):
        await fake.get_mark_price(symbol=SYMBOL, unexpected=True)
    with pytest.raises(TypeError):
        await fake.place_market_close(symbol=SYMBOL, side="SELL")
    with pytest.raises(TypeError):
        await fake.symbol_lot_filters(sym=SYMBOL)
    with pytest.raises(TypeError):
        await fake.snapshot_open_algo_orders(symbols=[SYMBOL])


# --------------------------------------------------------------------------- #
# Task 3: scripted completion gates for deterministic stop/cancel races (D-12).
# --------------------------------------------------------------------------- #

RACE_ROUNDS = 20


async def _position_with_open_remainder() -> BinanceSemanticsFakeAdapter:
    fake = _strict()
    await fake.place_entry(**_entry_kwargs())
    fake.fill(ENTRY_ID, quantity=Decimal("0.004"), price=Decimal("101.00"))
    fake.completed.clear()
    return fake


def _start_stop(fake: BinanceSemanticsFakeAdapter) -> asyncio.Task[Any]:
    return asyncio.create_task(fake.place_algo_protective(**_stop_kwargs()))


def _start_cancel(fake: BinanceSemanticsFakeAdapter) -> asyncio.Task[Any]:
    return asyncio.create_task(
        fake.cancel_normal_order(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    )


async def test_stop_completes_first_while_the_cancel_is_held() -> None:
    for _ in range(RACE_ROUNDS):
        fake = await _position_with_open_remainder()
        fake.hold("cancel_normal_order")

        cancel = _start_cancel(fake)
        stop = _start_stop(fake)
        await yield_to_loop()
        await yield_to_loop()

        # The stop is on the exchange; the held cancel has recorded its call but not acted.
        assert fake.held() == ["cancel_normal_order"]
        assert STOP_ID in fake.open_algos
        assert fake.open_orders[ENTRY_ID].status == STATUS_PARTIALLY_FILLED
        assert fake.completed == ["place_algo_protective"]
        assert not cancel.done()
        assert stop.done()

        fake.release("cancel_normal_order")
        await asyncio.gather(cancel, stop)

        assert fake.held() == []
        assert fake.completed == ["place_algo_protective", "cancel_normal_order"]
        assert ENTRY_ID not in fake.open_orders
        assert fake.history[ENTRY_ID].status == STATUS_CANCELED


async def test_cancel_completes_first_while_the_stop_is_held() -> None:
    for _ in range(RACE_ROUNDS):
        fake = await _position_with_open_remainder()
        fake.hold("place_algo_protective")

        stop = _start_stop(fake)
        cancel = _start_cancel(fake)
        await yield_to_loop()
        await yield_to_loop()

        assert fake.held() == ["place_algo_protective"]
        assert fake.open_algos == {}
        assert fake.history[ENTRY_ID].status == STATUS_CANCELED
        assert fake.completed == ["cancel_normal_order"]
        assert not stop.done()
        assert cancel.done()
        # The held call was recorded the moment it was made.
        assert fake.calls_to("place_algo_protective")

        fake.release("place_algo_protective")
        await asyncio.gather(cancel, stop)

        assert fake.completed == ["cancel_normal_order", "place_algo_protective"]
        assert STOP_ID in fake.open_algos


async def test_release_before_the_call_lets_it_pass_and_a_hold_applies_once() -> None:
    fake = await _position_with_open_remainder()
    fake.hold("cancel_normal_order")
    fake.release("cancel_normal_order")
    await _start_cancel(fake)  # no wait: released in advance
    assert fake.held() == []
    # The hold was consumed by that call; a second cancel is not held.
    await fake.cancel_normal_order(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    assert fake.held() == []


async def test_release_without_a_hold_is_a_test_error() -> None:
    fake = _strict()
    with pytest.raises(ValueError, match="cancel_normal_order"):
        fake.release("cancel_normal_order")


async def test_fail_next_raises_once_after_recording_the_call() -> None:
    fake = _strict()
    boom = TimeoutError("scripted")
    fake.fail_next("query_order_by_client", boom)

    with pytest.raises(TimeoutError) as caught:
        await fake.query_order_by_client(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    assert caught.value is boom
    assert len(fake.calls_to("query_order_by_client")) == 1
    assert fake.completed == []  # a failed call does not complete

    probe = await fake.query_order_by_client(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    assert probe.found is False
    assert len(fake.calls_to("query_order_by_client")) == 2
    assert fake.completed == ["query_order_by_client"]


async def test_fail_next_leaves_the_exchange_state_untouched() -> None:
    fake = await _position_with_open_remainder()
    fake.fail_next("cancel_normal_order", TimeoutError("ambiguous"))
    with pytest.raises(TimeoutError):
        await fake.cancel_normal_order(symbol=SYMBOL, orig_client_order_id=ENTRY_ID)
    assert ENTRY_ID in fake.open_orders


async def test_reject_next_algo_answers_minus_2021_once() -> None:
    fake = await _position_with_open_remainder()
    fake.reject_next_algo(-2021)

    with pytest.raises(BadRequestError) as caught:
        await fake.place_algo_protective(**_stop_kwargs())
    assert caught.value.status_code == -2021
    assert fake.open_algos == {}
    assert len(fake.calls_to("place_algo_protective")) == 1

    placed = await fake.place_algo_protective(**_stop_kwargs())
    assert placed.algo_status == STATUS_NEW


async def test_hold_then_fail_next_fails_after_the_release() -> None:
    fake = await _position_with_open_remainder()
    fake.hold("place_algo_protective")
    fake.reject_next_algo(-2021)
    stop = _start_stop(fake)
    await yield_to_loop()
    assert fake.held() == ["place_algo_protective"]
    fake.release("place_algo_protective")
    with pytest.raises(BadRequestError):
        await stop
    assert fake.open_algos == {}


async def test_gates_never_sleep_for_real(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("asyncio.sleep must not be used by the fake")

    monkeypatch.setattr(asyncio, "sleep", forbidden)
    fake = await _position_with_open_remainder()
    fake.hold("cancel_normal_order")
    cancel = _start_cancel(fake)
    await yield_to_loop()
    fake.release("cancel_normal_order")
    await cancel
