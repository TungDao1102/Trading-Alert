"""The MARKET reduce-only close, the pre-send marker, error facts and live lot filters.

Plan 19-08 (EXEC-01, D-15, D-16, D-19, D-21). Every test drives the REAL
`BinanceUsdmAdapter` over a recording fake SDK; no network call, no sleep.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
    NewOrderReduceOnlyEnum,
    NewOrderSideEnum,
    NewOrderTypeEnum,
)
from src.adapters.binance_clock import ClockDriftGuard
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    EntriesBlocked,
    MarketCloseResult,
)
from src.domain.exchange_errors import ExchangeErrorCategory

from tests.support.limits import test_only_drift_limits, test_only_signed_call_policy

START = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
UPDATE_MS = 1_791_360_000_000
CLOSE_ID = "c" * 36


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class RecordingRest:
    """Fake SDK REST surface: records `new_order` kwargs and answers a MARKET ack."""

    def __init__(self) -> None:
        self.new_order_calls: list[dict[str, Any]] = []
        self.new_order_error: BaseException | None = None
        self.new_order_payload: Any = None
        self.exchange_information_calls = 0
        self.exchange_information_payload: Any = SimpleNamespace(symbols=[])

    def new_order(self, **kwargs: Any) -> _Response:
        self.new_order_calls.append(dict(kwargs))
        if self.new_order_error is not None:
            raise self.new_order_error
        if self.new_order_payload is not None:
            return _Response(self.new_order_payload)
        return _Response(
            SimpleNamespace(
                symbol=kwargs["symbol"],
                client_order_id=kwargs["new_client_order_id"],
                order_id=777,
                side=kwargs["side"].value,
                position_side=kwargs["position_side"],
                type="MARKET",
                status="NEW",
                executed_qty="0.000",
                avg_price="0.00000",
                update_time=UPDATE_MS,
            )
        )

    def exchange_information(self, **_: Any) -> _Response:
        self.exchange_information_calls += 1
        return _Response(self.exchange_information_payload)


def _clock() -> datetime:
    return START


def _adapter(
    *, drift_guard: ClockDriftGuard | None = None
) -> tuple[BinanceUsdmAdapter, RecordingRest, RestRateLimitGate]:
    rest = RecordingRest()
    policy = test_only_signed_call_policy()
    gate = RestRateLimitGate(policy=policy.rate_limit, clock=_clock)
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        signed_call_policy=policy,
        rest_gate=gate,
        drift_guard=drift_guard,
        clock=_clock if drift_guard is not None else None,
    )
    return adapter, rest, gate


def _close(
    adapter: BinanceUsdmAdapter,
    *,
    side: str = "SELL",
    position_side: str = "BOTH",
    quantity: Any = Decimal("0.004"),
    client_id: str = CLOSE_ID,
) -> Any:
    return asyncio.run(
        adapter.place_market_close(
            symbol="BTCUSDT",
            side=side,
            position_side=position_side,
            quantity=quantity,
            new_client_order_id=client_id,
        )
    )


# --------------------------------------------------------------------------- #
# Task 1: the MARKET reduce-only close.
# --------------------------------------------------------------------------- #


def test_one_way_close_sends_one_market_reduce_only_order() -> None:
    adapter, rest, _ = _adapter()
    result = _close(adapter, side="SELL", position_side="BOTH")
    assert len(rest.new_order_calls) == 1
    wire = rest.new_order_calls[0]
    assert wire["type"] is NewOrderTypeEnum.MARKET
    assert wire["side"] is NewOrderSideEnum.SELL
    assert wire["position_side"] == "BOTH"
    assert wire["reduce_only"] is NewOrderReduceOnlyEnum.TRUE
    assert wire["quantity"] == "0.004"
    assert wire["new_client_order_id"] == CLOSE_ID
    assert wire["symbol"] == "BTCUSDT"
    assert wire["recv_window"] == test_only_signed_call_policy().recv_window_ms
    assert "price" not in wire
    assert "time_in_force" not in wire
    assert isinstance(result, MarketCloseResult)
    assert result.client_order_id == CLOSE_ID
    assert result.exchange_order_id == "777"
    assert result.symbol == "BTCUSDT"
    assert result.side == "SELL"
    assert result.position_side == "BOTH"
    assert result.status == "NEW"
    assert result.update_time_utc == datetime.fromtimestamp(UPDATE_MS / 1000, tz=UTC)


def test_one_way_buy_close_of_a_short_is_reduce_only_too() -> None:
    adapter, rest, _ = _adapter()
    _close(adapter, side="BUY", position_side="BOTH")
    wire = rest.new_order_calls[0]
    assert wire["side"] is NewOrderSideEnum.BUY
    assert wire["reduce_only"] is NewOrderReduceOnlyEnum.TRUE


@pytest.mark.parametrize(("side", "position_side"), [("SELL", "LONG"), ("BUY", "SHORT")])
def test_hedge_close_has_explicit_position_side_and_no_reduce_only(
    side: str, position_side: str
) -> None:
    adapter, rest, _ = _adapter()
    result = _close(adapter, side=side, position_side=position_side)
    wire = rest.new_order_calls[0]
    assert wire["position_side"] == position_side
    assert wire["type"] is NewOrderTypeEnum.MARKET
    assert "reduce_only" not in wire
    assert result.position_side == position_side


@pytest.mark.parametrize(("side", "position_side"), [("BUY", "LONG"), ("SELL", "SHORT")])
def test_hedge_close_that_would_add_exposure_raises_before_any_sdk_call(
    side: str, position_side: str
) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(ValueError, match="add exposure"):
        _close(adapter, side=side, position_side=position_side)
    assert rest.new_order_calls == []


@pytest.mark.parametrize(
    "quantity",
    [Decimal("0"), Decimal("-0.001"), Decimal("NaN"), Decimal("Infinity"), 0.004, "0.004", 1],
)
def test_a_non_positive_or_non_decimal_quantity_raises_before_any_sdk_call(
    quantity: Any,
) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises((ValueError, TypeError)):
        _close(adapter, quantity=quantity)
    assert rest.new_order_calls == []


@pytest.mark.parametrize(
    ("side", "position_side", "client_id"),
    [
        ("HOLD", "BOTH", CLOSE_ID),
        ("SELL", "SIDEWAYS", CLOSE_ID),
        ("SELL", "BOTH", ""),
        ("SELL", "BOTH", "x" * 37),
    ],
)
def test_an_invalid_side_position_side_or_client_id_raises_before_any_sdk_call(
    side: str, position_side: str, client_id: str
) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(ValueError):
        _close(adapter, side=side, position_side=position_side, client_id=client_id)
    assert rest.new_order_calls == []


def test_the_close_is_never_retried_after_an_ambiguous_failure() -> None:
    adapter, rest, _ = _adapter()
    rest.new_order_error = RuntimeError("socket closed")
    with pytest.raises(RuntimeError):
        _close(adapter)
    assert len(rest.new_order_calls) == 1


def test_a_drift_guard_that_blocks_entries_does_not_block_the_close() -> None:
    guard = ClockDriftGuard(limits=test_only_drift_limits())  # never measured: blocks entries
    adapter, rest, _ = _adapter(drift_guard=guard)
    with pytest.raises(EntriesBlocked):
        asyncio.run(
            adapter.place_entry(
                symbol="BTCUSDT",
                side="BUY",
                position_side="BOTH",
                time_in_force="GTC",
                quantity=Decimal("0.010"),
                price=Decimal("100.0"),
                new_client_order_id="e" * 36,
            )
        )
    assert rest.new_order_calls == []
    _close(adapter)
    assert len(rest.new_order_calls) == 1


def test_a_gate_pause_refuses_the_close_with_nothing_sent() -> None:
    from src.adapters.binance_ratelimit_gate import RestGateRefusal

    adapter, rest, gate = _adapter()
    gate.record(ExchangeErrorCategory.RATE_LIMITED, 30)
    with pytest.raises(RestGateRefusal):
        _close(adapter)
    assert rest.new_order_calls == []


def test_no_signed_policy_refuses_the_close_with_nothing_sent() -> None:
    from src.adapters.binance_usdm import SignedCallPolicyMissing

    rest = RecordingRest()
    adapter = BinanceUsdmAdapter(sdk_client=SimpleNamespace(rest_api=rest))  # type: ignore[arg-type]
    with pytest.raises(SignedCallPolicyMissing):
        _close(adapter)
    assert rest.new_order_calls == []


def test_absent_executed_quantity_and_average_price_are_none_never_zero() -> None:
    adapter, rest, _ = _adapter()
    rest.new_order_payload = SimpleNamespace(
        symbol="BTCUSDT",
        client_order_id=CLOSE_ID,
        order_id=5,
        side="SELL",
        position_side="BOTH",
        status="NEW",
        update_time=UPDATE_MS,
    )
    result = _close(adapter)
    assert result.executed_quantity is None
    assert result.average_price is None


def test_filled_executed_quantity_and_average_price_are_decimals() -> None:
    adapter, rest, _ = _adapter()
    rest.new_order_payload = SimpleNamespace(
        symbol="BTCUSDT",
        client_order_id=CLOSE_ID,
        order_id=5,
        side="SELL",
        position_side="BOTH",
        status="FILLED",
        executed_qty="0.004",
        avg_price="64000.10",
        update_time=UPDATE_MS,
    )
    result = _close(adapter)
    assert result.executed_quantity == Decimal("0.004")
    assert result.average_price == Decimal("64000.10")
    assert result.status == "FILLED"


@pytest.mark.parametrize("missing", ["order_id", "client_order_id", "symbol"])
def test_a_response_without_identity_raises(missing: str) -> None:
    adapter, rest, _ = _adapter()
    fields: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "client_order_id": CLOSE_ID,
        "order_id": 5,
        "side": "SELL",
        "position_side": "BOTH",
        "status": "NEW",
        "update_time": UPDATE_MS,
    }
    fields[missing] = None
    rest.new_order_payload = SimpleNamespace(**fields)
    with pytest.raises(ValueError, match="missing identity"):
        _close(adapter)


def test_a_response_without_update_time_raises() -> None:
    adapter, rest, _ = _adapter()
    rest.new_order_payload = SimpleNamespace(
        symbol="BTCUSDT",
        client_order_id=CLOSE_ID,
        order_id=5,
        side="SELL",
        position_side="BOTH",
        status="NEW",
        update_time=None,
    )
    with pytest.raises(ValueError, match="update_time"):
        _close(adapter)
