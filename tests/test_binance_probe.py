"""Behavior of the Demo-probe adapter (plan 18-12).

`BinanceProbeAdapter` turns every exchange answer into a frozen `ProbeObservation`: an error
is recorded as data (HTTP class, int code, category, scrubbed message), never raised. These
tests drive it with the SDK-shaped fakes of `tests/probe_fakes.py`; nothing opens a
connection, and every limit value is a TEST_ONLY constant.
"""

from __future__ import annotations

import ast
import dataclasses
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_common.errors import (
    BadRequestError,
    NetworkError,
    RateLimitBanError,
    ServerError,
    TooManyRequestsError,
)
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    CancelAlgoOrderResponse,
    CancelAllAlgoOpenOrdersResponse,
    CancelAllOpenOrdersResponse,
    CancelOrderResponse,
    NewAlgoOrderResponse,
    NewOrderResponse,
    QueryAlgoOrderResponse,
    QueryOrderResponse,
)
from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
    NewAlgoOrderAlgoTypeEnum,
    NewAlgoOrderClosePositionEnum,
    NewAlgoOrderReduceOnlyEnum,
    NewAlgoOrderSideEnum,
    NewAlgoOrderTimeInForceEnum,
    NewAlgoOrderTypeEnum,
    NewAlgoOrderWorkingTypeEnum,
    NewOrderReduceOnlyEnum,
    NewOrderSideEnum,
    NewOrderTimeInForceEnum,
    NewOrderTypeEnum,
)
from src.adapters import binance_probe
from src.adapters.binance_limits import RateLimitPolicy, SignedCallPolicy
from src.adapters.binance_probe import (
    ERROR_MESSAGE_MAX_CHARS,
    BinanceProbeAdapter,
    ErrorObservation,
    ProbeBanned,
    ProbeObservation,
)
from src.adapters.binance_ratelimit_gate import (
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    RestRateLimitGate,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from src.ops.redaction import REDACTED, clear_runtime_secrets, register_runtime_secret

from tests.probe_fakes import FakeProbeRest, FakeProbeSdk, VirtualClock, make_gate
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS,
    TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS,
    TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS,
    TEST_ONLY_RECV_WINDOW_MS,
    test_only_signed_call_policy,
)

TEST_ONLY_SYMBOL = "BTCUSDT"
TEST_ONLY_CLIENT_ORDER_ID = "probe-test-order-0001"
TEST_ONLY_CLIENT_ALGO_ID = "probe-test-algo-0001"
TEST_ONLY_SECRET = "TESTONLYsecretValue123456"
MODULE_PATH = Path(binance_probe.__file__)


def _adapter(
    rest: FakeProbeRest | None = None,
    *,
    gate: RestRateLimitGate | None = None,
) -> tuple[BinanceProbeAdapter, FakeProbeRest, RestRateLimitGate]:
    rest = rest if rest is not None else FakeProbeRest()
    gate = gate if gate is not None else make_gate()
    adapter = BinanceProbeAdapter(
        FakeProbeSdk(rest),
        policy=test_only_signed_call_policy(),
        rest_gate=gate,
    )
    return adapter, rest, gate


@pytest.fixture(autouse=True)
def _no_runtime_secrets() -> Any:
    clear_runtime_secrets()
    yield
    clear_runtime_secrets()


# --------------------------------------------------------------------------- #
# Task 1: the exact not-found answer as data.
# --------------------------------------------------------------------------- #


async def test_query_order_missing_returns_the_exact_code_as_data() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "query_order",
        BadRequestError(status_code=-2013, error_message="Order does not exist."),
    )

    observation = await adapter.query_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )

    assert observation == ProbeObservation(
        operation="query_order",
        ok=False,
        summary={},
        error=ErrorObservation(
            http_class="BAD_REQUEST",
            code=-2013,
            retry_after_seconds=None,
            category="ORDER_ABSENT",
            message="Order does not exist.",
        ),
    )
    assert rest.calls == [
        (
            "query_order",
            {
                "symbol": TEST_ONLY_SYMBOL,
                "orig_client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
                "recv_window": TEST_ONLY_RECV_WINDOW_MS,
            },
        )
    ]


async def test_query_algo_order_missing_returns_the_exact_code_as_data() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "query_algo_order",
        BadRequestError(status_code=-2013, error_message="Order does not exist."),
    )

    observation = await adapter.query_algo_order(client_algo_id=TEST_ONLY_CLIENT_ALGO_ID)

    assert observation == ProbeObservation(
        operation="query_algo_order",
        ok=False,
        summary={},
        error=ErrorObservation(
            http_class="BAD_REQUEST",
            code=-2013,
            retry_after_seconds=None,
            category="ORDER_ABSENT",
            message="Order does not exist.",
        ),
    )
    assert rest.calls == [
        (
            "query_algo_order",
            {"client_algo_id": TEST_ONLY_CLIENT_ALGO_ID, "recv_window": TEST_ONLY_RECV_WINDOW_MS},
        )
    ]


async def test_query_order_success_gives_a_string_summary_of_present_fields() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "query_order",
        QueryOrderResponse(
            order_id=8389765492,
            client_order_id=TEST_ONLY_CLIENT_ORDER_ID,
            status="NEW",
            side="BUY",
            type="LIMIT",
            orig_qty="0.010",
            executed_qty="0",
            price="50000.10",
            reduce_only=False,
        ),
    )

    observation = await adapter.query_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )

    assert observation.ok is True
    assert observation.error is None
    assert observation.operation == "query_order"
    assert dict(observation.summary) == {
        "order_id": "8389765492",
        "client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
        "status": "NEW",
        "side": "BUY",
        "type": "LIMIT",
        "orig_qty": "0.010",
        "executed_qty": "0",
        "price": "50000.10",
        "reduce_only": "false",
    }
    assert all(isinstance(value, str) for value in observation.summary.values())


async def test_query_order_summary_omits_absent_fields() -> None:
    adapter, rest, _ = _adapter()
    rest.script("query_order", QueryOrderResponse(order_id=1, status="CANCELED"))

    observation = await adapter.query_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )

    assert dict(observation.summary) == {"order_id": "1", "status": "CANCELED"}


async def test_query_algo_order_success_gives_a_string_summary() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "query_algo_order",
        QueryAlgoOrderResponse(
            algo_id=3000000123,
            client_algo_id=TEST_ONLY_CLIENT_ALGO_ID,
            algo_status="NEW",
            algo_type="CONDITIONAL",
            order_type="STOP_MARKET",
            side="SELL",
            quantity="0.010",
            trigger_price="48000.00",
            close_position=True,
        ),
    )

    observation = await adapter.query_algo_order(client_algo_id=TEST_ONLY_CLIENT_ALGO_ID)

    assert observation.ok is True
    assert dict(observation.summary) == {
        "algo_id": "3000000123",
        "client_algo_id": TEST_ONLY_CLIENT_ALGO_ID,
        "algo_status": "NEW",
        "algo_type": "CONDITIONAL",
        "order_type": "STOP_MARKET",
        "side": "SELL",
        "quantity": "0.010",
        "trigger_price": "48000.00",
        "close_position": "true",
    }


async def test_non_sdk_exception_records_the_type_name_only() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "query_order",
        RuntimeError(f"boom https://demo.invalid/fapi/v1/order?signature={'a' * 64}"),
    )

    observation = await adapter.query_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )

    assert observation.ok is False
    assert observation.error == ErrorObservation(
        http_class="NON_SDK",
        code=None,
        retry_after_seconds=None,
        category="UNKNOWN_EXCHANGE_ERROR",
        message="RuntimeError",
    )


async def test_exchange_message_is_scrubbed_and_capped() -> None:
    register_runtime_secret(TEST_ONLY_SECRET)
    adapter, rest, _ = _adapter()
    long_text = f"key {TEST_ONLY_SECRET} rejected; " + "x" * (3 * ERROR_MESSAGE_MAX_CHARS)
    rest.script("query_order", BadRequestError(status_code=-2013, error_message=long_text))

    observation = await adapter.query_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )

    assert observation.error is not None
    message = observation.error.message
    assert len(message) == ERROR_MESSAGE_MAX_CHARS
    assert TEST_ONLY_SECRET not in message
    assert message.startswith(f"key {REDACTED} rejected; ")


async def test_sdk_call_runs_in_a_worker_thread() -> None:
    adapter, rest, _ = _adapter()
    rest.script("query_order", QueryOrderResponse(order_id=1))

    await adapter.query_order(symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID)

    assert rest.thread_ids and rest.thread_ids[0] != threading.get_ident()


class _NotAnException(BaseException):
    """A BaseException that is not an Exception: it must propagate, not become data."""


async def test_base_exception_is_not_turned_into_an_observation() -> None:
    adapter, rest, _ = _adapter()
    rest.script("query_order", _NotAnException())

    with pytest.raises(_NotAnException):
        await adapter.query_order(
            symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
        )


async def test_a_restricted_gate_refuses_a_query_without_an_sdk_call() -> None:
    clock = VirtualClock()
    gate = make_gate(clock)
    gate.record(ExchangeErrorCategory.IP_BANNED, None)
    adapter, rest, _ = _adapter(gate=gate)

    with pytest.raises(ProbeBanned) as caught:
        await adapter.query_order(
            symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
        )

    assert rest.calls == []
    assert caught.value.reason == IP_BAN_418
    assert caught.value.retry_after_seconds == TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS


# --------------------------------------------------------------------------- #
# The value types.
# --------------------------------------------------------------------------- #


def _error() -> ErrorObservation:
    return ErrorObservation(
        http_class="BAD_REQUEST",
        code=-2013,
        retry_after_seconds=None,
        category="ORDER_ABSENT",
        message="Order does not exist.",
    )


def test_observations_are_frozen() -> None:
    error = _error()
    observation = ProbeObservation(operation="query_order", ok=False, summary={}, error=error)
    with pytest.raises(dataclasses.FrozenInstanceError):
        error.code = -2011  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.ok = True  # type: ignore[misc]


def test_summary_cannot_be_mutated_through_the_observation() -> None:
    source = {"status": "NEW"}
    observation = ProbeObservation(operation="query_order", ok=True, summary=source, error=None)
    source["status"] = "FILLED"
    assert observation.summary["status"] == "NEW"
    with pytest.raises(TypeError):
        observation.summary["status"] = "FILLED"  # type: ignore[index]


@pytest.mark.parametrize("bad", [1, None, b"x", 1.5])
def test_observation_rejects_a_non_string_summary_value(bad: Any) -> None:
    with pytest.raises(TypeError):
        ProbeObservation(operation="query_order", ok=True, summary={"status": bad}, error=None)


def test_observation_rejects_a_non_string_summary_key() -> None:
    with pytest.raises(TypeError):
        ProbeObservation(operation="query_order", ok=True, summary={1: "x"}, error=None)  # type: ignore[dict-item]


def test_observation_ok_and_error_must_agree() -> None:
    with pytest.raises(ValueError):
        ProbeObservation(operation="query_order", ok=True, summary={}, error=_error())
    with pytest.raises(ValueError):
        ProbeObservation(operation="query_order", ok=False, summary={}, error=None)


def test_error_observation_validates_its_fields() -> None:
    base = dataclasses.asdict(_error())
    for field, bad in (
        ("http_class", "TEAPOT"),
        ("category", "MAYBE_ABSENT"),
        ("message", "x" * (ERROR_MESSAGE_MAX_CHARS + 1)),
        ("retry_after_seconds", -1),
    ):
        with pytest.raises(ValueError):
            ErrorObservation(**{**base, field: bad})
    for field, bad in (("code", True), ("code", "-2013"), ("message", None)):
        with pytest.raises(TypeError):
            ErrorObservation(**{**base, field: bad})


# --------------------------------------------------------------------------- #
# The constructor.
# --------------------------------------------------------------------------- #


def test_constructor_requires_the_policy_and_the_gate_as_keywords() -> None:
    gate = make_gate()
    policy = test_only_signed_call_policy()
    with pytest.raises(TypeError):
        BinanceProbeAdapter(FakeProbeSdk(), policy, gate)  # type: ignore[misc]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(FakeProbeSdk(), rest_gate=gate)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(FakeProbeSdk(), policy=policy)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(FakeProbeSdk(), policy=object(), rest_gate=gate)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(FakeProbeSdk(), policy=policy, rest_gate=object())  # type: ignore[arg-type]


def test_constructor_refuses_a_gate_with_another_rate_limit_policy() -> None:
    other = RateLimitPolicy(
        no_retry_after_wait_418_seconds=TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS,
        no_retry_after_wait_429_seconds=TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS + 1,
        retry_after_cap_seconds=TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS,
    )
    gate = RestRateLimitGate(policy=other, clock=VirtualClock())
    with pytest.raises(ValueError):
        BinanceProbeAdapter(
            FakeProbeSdk(),
            policy=SignedCallPolicy(
                recv_window_ms=TEST_ONLY_RECV_WINDOW_MS,
                rate_limit=test_only_signed_call_policy().rate_limit,
            ),
            rest_gate=gate,
        )


# --------------------------------------------------------------------------- #
# Task 2: mutating operations, cancels, the ban flag and the shared gate.
# --------------------------------------------------------------------------- #

TEST_ONLY_QTY = Decimal("0.010")
TEST_ONLY_PRICE = Decimal("50000.10")
TEST_ONLY_TRIGGER = Decimal("48000.00")


def _limit(adapter: BinanceProbeAdapter, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "symbol": TEST_ONLY_SYMBOL,
        "side": "BUY",
        "quantity": TEST_ONLY_QTY,
        "price": TEST_ONLY_PRICE,
        "client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
        "position_side": "BOTH",
        "time_in_force": "GTC",
        "reduce_only": None,
    }
    return adapter.new_limit_order(**{**arguments, **overrides})


def _market(adapter: BinanceProbeAdapter, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "symbol": TEST_ONLY_SYMBOL,
        "side": "SELL",
        "quantity": TEST_ONLY_QTY,
        "client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
        "position_side": "BOTH",
        "reduce_only": True,
    }
    return adapter.new_market_order(**{**arguments, **overrides})


def _conditional(adapter: BinanceProbeAdapter, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "symbol": TEST_ONLY_SYMBOL,
        "side": "SELL",
        "order_type": "STOP_MARKET",
        "client_algo_id": TEST_ONLY_CLIENT_ALGO_ID,
        "position_side": "BOTH",
        "trigger_price": TEST_ONLY_TRIGGER,
        "working_type": "MARK_PRICE",
    }
    return adapter.new_conditional_order(**{**arguments, **overrides})


async def test_new_limit_order_sends_exact_strings_and_enum_members() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "new_order",
        NewOrderResponse(
            order_id=77, client_order_id=TEST_ONLY_CLIENT_ORDER_ID, status="NEW", type="LIMIT"
        ),
    )

    observation = await _limit(adapter, reduce_only=True, time_in_force="GTX")

    assert observation.ok is True
    assert observation.operation == "new_limit_order"
    assert dict(observation.summary) == {
        "order_id": "77",
        "client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
        "status": "NEW",
        "type": "LIMIT",
    }
    ((name, kwargs),) = rest.calls
    assert name == "new_order"
    assert kwargs == {
        "symbol": TEST_ONLY_SYMBOL,
        "side": NewOrderSideEnum.BUY,
        "type": NewOrderTypeEnum.LIMIT,
        "position_side": "BOTH",
        "time_in_force": NewOrderTimeInForceEnum.GTX,
        "quantity": "0.010",
        "price": "50000.10",
        "new_client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
        "reduce_only": NewOrderReduceOnlyEnum.TRUE,
        "recv_window": TEST_ONLY_RECV_WINDOW_MS,
    }


async def test_new_limit_order_omits_reduce_only_when_none_and_sends_false_when_false() -> None:
    adapter, rest, _ = _adapter()
    rest.script("new_order", NewOrderResponse(order_id=1), NewOrderResponse(order_id=2))

    await _limit(adapter, reduce_only=None)
    await _limit(adapter, reduce_only=False)

    assert "reduce_only" not in rest.calls[0][1]
    assert rest.calls[1][1]["reduce_only"] is NewOrderReduceOnlyEnum.FALSE


async def test_new_market_order_sends_a_market_type_without_price() -> None:
    adapter, rest, _ = _adapter()
    rest.script("new_order", NewOrderResponse(order_id=5, status="FILLED", executed_qty="0.010"))

    observation = await _market(adapter, position_side="SHORT", reduce_only=None)

    assert observation.ok is True
    assert observation.operation == "new_market_order"
    ((name, kwargs),) = rest.calls
    assert name == "new_order"
    assert kwargs == {
        "symbol": TEST_ONLY_SYMBOL,
        "side": NewOrderSideEnum.SELL,
        "type": NewOrderTypeEnum.MARKET,
        "position_side": "SHORT",
        "quantity": "0.010",
        "new_client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
        "recv_window": TEST_ONLY_RECV_WINDOW_MS,
    }


async def test_new_market_order_reduce_only_is_sent_as_the_enum_member() -> None:
    adapter, rest, _ = _adapter()
    rest.script("new_order", NewOrderResponse(order_id=5))

    await _market(adapter, reduce_only=True)

    assert rest.calls[0][1]["reduce_only"] is NewOrderReduceOnlyEnum.TRUE


async def test_conditional_order_sends_only_the_given_optional_parameters() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "new_algo_order",
        NewAlgoOrderResponse(algo_id=9, client_algo_id=TEST_ONLY_CLIENT_ALGO_ID, algo_status="NEW"),
    )

    observation = await _conditional(adapter, close_position=True)

    assert observation.ok is True
    assert observation.operation == "new_conditional_order"
    assert dict(observation.summary) == {
        "algo_id": "9",
        "client_algo_id": TEST_ONLY_CLIENT_ALGO_ID,
        "algo_status": "NEW",
    }
    ((name, kwargs),) = rest.calls
    assert name == "new_algo_order"
    assert kwargs == {
        "algo_type": NewAlgoOrderAlgoTypeEnum.CONDITIONAL,
        "symbol": TEST_ONLY_SYMBOL,
        "side": NewAlgoOrderSideEnum.SELL,
        "type": NewAlgoOrderTypeEnum.STOP_MARKET,
        "position_side": "BOTH",
        "trigger_price": "48000.00",
        "working_type": NewAlgoOrderWorkingTypeEnum.MARK_PRICE,
        "close_position": NewAlgoOrderClosePositionEnum.TRUE,
        "client_algo_id": TEST_ONLY_CLIENT_ALGO_ID,
        "recv_window": TEST_ONLY_RECV_WINDOW_MS,
    }


async def test_conditional_order_explicit_quantity_reduce_only_leg() -> None:
    adapter, rest, _ = _adapter()
    rest.script("new_algo_order", NewAlgoOrderResponse(algo_id=10))

    await _conditional(
        adapter,
        order_type="TAKE_PROFIT_MARKET",
        quantity=TEST_ONLY_QTY,
        reduce_only=True,
        working_type="CONTRACT_PRICE",
    )

    kwargs = rest.calls[0][1]
    assert kwargs["type"] is NewAlgoOrderTypeEnum.TAKE_PROFIT_MARKET
    assert kwargs["quantity"] == "0.010"
    assert kwargs["reduce_only"] is NewAlgoOrderReduceOnlyEnum.TRUE
    assert kwargs["working_type"] is NewAlgoOrderWorkingTypeEnum.CONTRACT_PRICE
    assert "close_position" not in kwargs
    assert "price" not in kwargs
    assert "time_in_force" not in kwargs


async def test_conditional_stop_limit_with_time_in_force() -> None:
    adapter, rest, _ = _adapter()
    rest.script("new_algo_order", NewAlgoOrderResponse(algo_id=11))

    await _conditional(
        adapter,
        order_type="STOP",
        quantity=TEST_ONLY_QTY,
        price=TEST_ONLY_PRICE,
        time_in_force="GTC",
        reduce_only=False,
        close_position=False,
    )

    kwargs = rest.calls[0][1]
    assert kwargs["type"] is NewAlgoOrderTypeEnum.STOP
    assert kwargs["price"] == "50000.10"
    assert kwargs["time_in_force"] is NewAlgoOrderTimeInForceEnum.GTC
    assert kwargs["reduce_only"] is NewAlgoOrderReduceOnlyEnum.FALSE
    assert kwargs["close_position"] is NewAlgoOrderClosePositionEnum.FALSE


async def test_documented_invalid_combination_is_passed_through_for_the_exchange() -> None:
    """closePosition with quantity and reduceOnly reaches Binance unchanged; its answer is data."""
    adapter, rest, _ = _adapter()
    rest.script(
        "new_algo_order",
        BadRequestError(status_code=-4137, error_message="Quantity exists with closePosition."),
    )

    observation = await _conditional(
        adapter, close_position=True, quantity=TEST_ONLY_QTY, reduce_only=True
    )

    kwargs = rest.calls[0][1]
    assert kwargs["close_position"] is NewAlgoOrderClosePositionEnum.TRUE
    assert kwargs["quantity"] == "0.010"
    assert kwargs["reduce_only"] is NewAlgoOrderReduceOnlyEnum.TRUE
    assert observation.error is not None
    assert (observation.error.code, observation.error.category) == (-4137, "REJECTED_DEFINITIVE")


async def test_decimal_exponent_values_cross_as_fixed_point_text() -> None:
    adapter, rest, _ = _adapter()
    rest.script("new_order", NewOrderResponse(order_id=1))

    await _limit(adapter, quantity=Decimal("1E+1"), price=Decimal("1E-8"))

    assert rest.calls[0][1]["quantity"] == "10"
    assert rest.calls[0][1]["price"] == "0.00000001"


@pytest.mark.parametrize("bad", [0.01, 1, True, "0.01"])
@pytest.mark.parametrize("field", ["quantity", "price"])
async def test_limit_order_money_must_be_decimal(field: str, bad: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(TypeError):
        await _limit(adapter, **{field: bad})
    assert rest.calls == []


@pytest.mark.parametrize("bad", [0.01, 1])
async def test_market_and_conditional_money_must_be_decimal(bad: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(TypeError):
        await _market(adapter, quantity=bad)
    for field in ("trigger_price", "quantity", "price"):
        with pytest.raises(TypeError):
            await _conditional(adapter, **{field: bad})
    assert rest.calls == []


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-0.001"), Decimal("NaN"), Decimal("Inf")])
async def test_non_positive_or_non_finite_money_is_refused(bad: Decimal) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(ValueError):
        await _limit(adapter, quantity=bad)
    with pytest.raises(ValueError):
        await _limit(adapter, price=bad)
    with pytest.raises(ValueError):
        await _market(adapter, quantity=bad)
    with pytest.raises(ValueError):
        await _conditional(adapter, trigger_price=bad)
    with pytest.raises(ValueError):
        await _conditional(adapter, quantity=bad)
    assert rest.calls == []


@pytest.mark.parametrize(
    "call",
    [
        lambda a: _limit(a, side="HOLD"),
        lambda a: _limit(a, time_in_force="FOREVER"),
        lambda a: _market(a, side="buy"),
        lambda a: _conditional(a, side="HOLD"),
        lambda a: _conditional(a, order_type="STOP_LOSS"),
        lambda a: _conditional(a, order_type="LIMIT"),
        lambda a: _conditional(a, order_type="TRAILING_STOP_MARKET"),
        lambda a: _conditional(a, working_type="LAST_PRICE"),
        lambda a: _conditional(a, time_in_force="FOREVER"),
    ],
)
async def test_unknown_enum_text_is_refused_before_the_sdk_call(call: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(ValueError):
        await call(adapter)
    assert rest.calls == []


@pytest.mark.parametrize(
    "call",
    [
        lambda a: _limit(a, reduce_only="true"),
        lambda a: _market(a, reduce_only=1),
        lambda a: _conditional(a, close_position="true"),
        lambda a: _conditional(a, reduce_only=0),
        lambda a: _limit(a, side=1),
    ],
)
async def test_flags_and_enum_text_must_have_their_types(call: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(TypeError):
        await call(adapter)
    assert rest.calls == []


async def test_cancel_operations_send_the_documented_keywords() -> None:
    adapter, rest, _ = _adapter()
    rest.script("cancel_order", CancelOrderResponse(order_id=3, status="CANCELED"))
    rest.script(
        "cancel_algo_order",
        CancelAlgoOrderResponse(algo_id=4, client_algo_id=TEST_ONLY_CLIENT_ALGO_ID, code="200"),
    )
    rest.script("cancel_all_open_orders", CancelAllOpenOrdersResponse(code=200, msg="done"))
    rest.script("cancel_all_algo_open_orders", CancelAllAlgoOpenOrdersResponse(code=200))

    first = await adapter.cancel_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )
    second = await adapter.cancel_algo_order(client_algo_id=TEST_ONLY_CLIENT_ALGO_ID)
    third = await adapter.cancel_all_open_orders(symbol=TEST_ONLY_SYMBOL)
    fourth = await adapter.cancel_all_algo_open_orders(symbol=TEST_ONLY_SYMBOL)

    window = TEST_ONLY_RECV_WINDOW_MS
    assert rest.calls == [
        (
            "cancel_order",
            {
                "symbol": TEST_ONLY_SYMBOL,
                "orig_client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
                "recv_window": window,
            },
        ),
        ("cancel_algo_order", {"client_algo_id": TEST_ONLY_CLIENT_ALGO_ID, "recv_window": window}),
        ("cancel_all_open_orders", {"symbol": TEST_ONLY_SYMBOL, "recv_window": window}),
        ("cancel_all_algo_open_orders", {"symbol": TEST_ONLY_SYMBOL, "recv_window": window}),
    ]
    assert [o.operation for o in (first, second, third, fourth)] == [
        "cancel_order",
        "cancel_algo_order",
        "cancel_all_open_orders",
        "cancel_all_algo_open_orders",
    ]
    assert dict(first.summary) == {"order_id": "3", "status": "CANCELED"}
    assert dict(second.summary) == {
        "algo_id": "4",
        "client_algo_id": TEST_ONLY_CLIENT_ALGO_ID,
        "code": "200",
    }
    assert dict(third.summary) == {"code": "200", "msg": "done"}
    assert dict(fourth.summary) == {"code": "200"}


async def test_cancel_message_field_is_scrubbed() -> None:
    register_runtime_secret(TEST_ONLY_SECRET)
    adapter, rest, _ = _adapter()
    rest.script(
        "cancel_all_open_orders",
        CancelAllOpenOrdersResponse(code=200, msg=f"done for {TEST_ONLY_SECRET}"),
    )

    observation = await adapter.cancel_all_open_orders(symbol=TEST_ONLY_SYMBOL)

    assert observation.summary["msg"] == f"done for {REDACTED}"


@pytest.mark.parametrize("code", [-2011, -2013])
async def test_single_cancels_record_not_found_as_order_absent(code: int) -> None:
    adapter, rest, _ = _adapter()
    rest.script("cancel_order", BadRequestError(status_code=code, error_message="Unknown order"))
    rest.script(
        "cancel_algo_order", BadRequestError(status_code=code, error_message="Unknown order")
    )

    plain = await adapter.cancel_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )
    algo = await adapter.cancel_algo_order(client_algo_id=TEST_ONLY_CLIENT_ALGO_ID)

    for observation in (plain, algo):
        assert observation.ok is False
        assert observation.error is not None
        assert observation.error.code == code
        assert observation.error.category == "ORDER_ABSENT"


async def test_a_status_unknown_cancel_is_recorded_once_and_never_retried() -> None:
    adapter, rest, _ = _adapter()
    rest.script("cancel_order", ServerError(status_code=503, error_message="busy"))

    observation = await adapter.cancel_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )

    assert len(rest.calls) == 1
    assert observation.error is not None
    assert (observation.error.http_class, observation.error.category) == (
        "SERVER_5XX",
        "STATUS_UNKNOWN",
    )
    assert adapter.banned is False


async def test_a_placement_timeout_is_recorded_once_and_never_retried() -> None:
    adapter, rest, _ = _adapter()
    rest.script("new_order", NetworkError("read timed out"))

    observation = await _market(adapter)

    assert len(rest.calls) == 1
    assert observation.error is not None
    assert observation.error.category == "STATUS_UNKNOWN"


_READ_AND_MUTATING_CALLS = [
    lambda a: a.query_order(symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID),
    lambda a: a.query_algo_order(client_algo_id=TEST_ONLY_CLIENT_ALGO_ID),
    lambda a: _limit(a),
    lambda a: _market(a),
    lambda a: _conditional(a, close_position=True),
    lambda a: a.cancel_order(symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID),
    lambda a: a.cancel_algo_order(client_algo_id=TEST_ONLY_CLIENT_ALGO_ID),
    lambda a: a.cancel_all_open_orders(symbol=TEST_ONLY_SYMBOL),
    lambda a: a.cancel_all_algo_open_orders(symbol=TEST_ONLY_SYMBOL),
]


@pytest.mark.parametrize(
    ("answer", "category", "reason"),
    [
        (RateLimitBanError(status_code=-1003, error_message="banned"), "IP_BANNED", IP_BAN_418),
        (
            TooManyRequestsError(status_code=-1003, error_message="too many"),
            "RATE_LIMITED",
            RATE_LIMIT_PAUSE_429,
        ),
    ],
)
async def test_a_rate_limit_answer_sets_the_ban_flag_and_refuses_every_later_call(
    answer: Exception, category: str, reason: str
) -> None:
    clock = VirtualClock()
    adapter, rest, gate = _adapter(gate=make_gate(clock))
    rest.script("new_order", answer)

    first = await _limit(adapter)

    assert first.error is not None
    assert first.error.category == category
    assert adapter.banned is True
    # Let the shared gate open again: the adapter's own flag still refuses (no retry, ever).
    clock.advance(TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS + 1)
    assert gate.restriction() is None
    for call in _READ_AND_MUTATING_CALLS:
        with pytest.raises(ProbeBanned) as caught:
            await call(adapter)
        assert caught.value.reason == reason
        assert caught.value.retry_after_seconds is None
    assert len(rest.calls) == 1


async def test_a_pause_then_an_open_gate_still_refuses_with_the_pause_reason() -> None:
    clock = VirtualClock()
    adapter, rest, gate = _adapter(gate=make_gate(clock))
    rest.script("query_order", TooManyRequestsError(status_code=-1003))

    await adapter.query_order(symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID)
    clock.advance(TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS + 1)

    assert gate.restriction() is None
    with pytest.raises(ProbeBanned) as caught:
        await adapter.query_algo_order(client_algo_id=TEST_ONLY_CLIENT_ALGO_ID)
    assert caught.value.reason == RATE_LIMIT_PAUSE_429
    assert rest.names() == ["query_order"]


async def test_probe_records_rate_limit_in_shared_gate() -> None:
    ban_adapter, ban_rest, ban_gate = _adapter()
    ban_rest.script("new_order", RateLimitBanError(status_code=-1003, error_message="banned"))
    await _market(ban_adapter)
    ban = ban_gate.restriction()
    assert ban is not None
    assert ban.reason == IP_BAN_418
    assert ban.remaining_seconds == TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS

    pause_adapter, pause_rest, pause_gate = _adapter()
    pause_rest.script(
        "cancel_order", TooManyRequestsError(status_code=-1003, error_message="too many")
    )
    await pause_adapter.cancel_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )
    pause = pause_gate.restriction()
    assert pause is not None
    assert pause.reason == RATE_LIMIT_PAUSE_429
    assert pause.remaining_seconds == TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS

    capped_adapter, capped_rest, capped_gate = _adapter()
    over_cap = TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS + 500
    capped_rest.script("query_order", RateLimitBanError(status_code=-1003, retry_after=over_cap))
    observation = await capped_adapter.query_order(
        symbol=TEST_ONLY_SYMBOL, client_order_id=TEST_ONLY_CLIENT_ORDER_ID
    )
    capped = capped_gate.restriction()
    assert capped is not None
    assert capped.remaining_seconds == TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS
    assert observation.error is not None
    assert observation.error.retry_after_seconds == over_cap


@pytest.mark.parametrize(
    ("category", "reason", "remaining"),
    [
        (
            ExchangeErrorCategory.IP_BANNED,
            IP_BAN_418,
            TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS,
        ),
        (
            ExchangeErrorCategory.RATE_LIMITED,
            RATE_LIMIT_PAUSE_429,
            TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS,
        ),
    ],
)
@pytest.mark.parametrize("call", _READ_AND_MUTATING_CALLS)
async def test_probe_refuses_when_another_holder_restricted_the_gate(
    category: ExchangeErrorCategory, reason: str, remaining: int, call: Any
) -> None:
    adapter, rest, gate = _adapter()
    gate.record(category, None)  # another holder of the same gate met a 418 or a 429

    with pytest.raises(ProbeBanned) as caught:
        await call(adapter)

    assert rest.calls == []
    assert caught.value.reason == reason
    assert caught.value.retry_after_seconds == remaining
    assert adapter.banned is False


def test_module_has_no_retry_construct() -> None:
    """One SDK send site, no loop, no tenacity, no sleep: nothing can retry."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any(name.startswith("tenacity") for name in imported)
    assert not any(isinstance(node, ast.While | ast.AsyncFor) for node in ast.walk(tree))
    attributes = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"to_thread", "sleep"}
    ]
    assert attributes == ["to_thread"]
