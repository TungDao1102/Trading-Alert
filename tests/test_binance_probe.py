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
    AccountInformationV3Response,
    AccountTradeListResponseInner,
    CancelAlgoOrderResponse,
    CancelAllAlgoOpenOrdersResponse,
    CancelAllOpenOrdersResponse,
    CancelOrderResponse,
    ChangeInitialLeverageResponse,
    ChangeMarginTypeResponse,
    CheckServerTimeResponse,
    CurrentAllAlgoOpenOrdersResponseInner,
    CurrentAllOpenOrdersResponseInner,
    ExchangeInformationResponse,
    ExchangeInformationResponseSymbolsInner,
    ExchangeInformationResponseSymbolsInnerFiltersInner,
    FuturesAccountBalanceV3Response,
    FuturesAccountConfigurationResponse,
    GetIncomeHistoryResponse,
    MarkPriceResponse,
    MarkPriceResponse1,
    NewAlgoOrderResponse,
    NewOrderResponse,
    NotionalAndLeverageBracketsResponse,
    OrderBookResponse,
    PositionInformationV3ResponseInner,
    QueryAlgoOrderResponse,
    QueryOrderResponse,
    SymbolConfigurationResponse,
)
from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
    ChangeMarginTypeMarginTypeEnum,
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
    MARK_PRICE_INTERVAL,
    BinanceProbeAdapter,
    ErrorObservation,
    ProbeBanned,
    ProbeObservation,
)
from src.adapters.binance_public import BinancePublicMarketData
from src.adapters.binance_ratelimit_gate import (
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    RestRateLimitGate,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from src.ops.redaction import REDACTED, clear_runtime_secrets, register_runtime_secret

from tests.probe_fakes import (
    FakeProbeRest,
    FakeProbeSdk,
    VirtualClock,
    make_gate,
    make_public,
)
from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    wall_clock_calls,
)
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
        public=make_public(rest, gate),
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


def test_constructor_requires_the_policy_the_gate_and_the_public_reader_as_keywords() -> None:
    gate = make_gate()
    policy = test_only_signed_call_policy()
    public = make_public(FakeProbeRest(), gate)
    sdk = FakeProbeSdk()
    with pytest.raises(TypeError):
        BinanceProbeAdapter(sdk, policy, gate, public)  # type: ignore[misc]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(sdk, rest_gate=gate, public=public)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(sdk, policy=policy, public=public)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(sdk, policy=policy, rest_gate=gate)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(sdk, policy=object(), rest_gate=gate, public=public)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(sdk, policy=policy, rest_gate=object(), public=public)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BinanceProbeAdapter(sdk, policy=policy, rest_gate=gate, public=object())  # type: ignore[arg-type]


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
            public=make_public(FakeProbeRest(), gate),
        )


def test_constructor_refuses_a_public_reader_without_the_same_gate() -> None:
    """The mark price and filter reads must be refused during a ban or a pause too."""
    gate = make_gate()
    policy = test_only_signed_call_policy()
    ungated = BinancePublicMarketData(sdk_client=FakeProbeSdk(), rest_gate=None)  # type: ignore[arg-type]
    other_gate = make_public(FakeProbeRest(), make_gate())
    for public in (ungated, other_gate):
        with pytest.raises(ValueError):
            BinanceProbeAdapter(FakeProbeSdk(), policy=policy, rest_gate=gate, public=public)


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
    lambda a: _gtd(a),  # quick task 261021-sj0
    lambda a: a.stale_timestamp_read(  # quick task 261023-sj2
        symbol=TEST_ONLY_SYMBOL, recv_window_ms=5000, timestamp_behind_ms=10_000
    ),
    # Phase 22 plan 22-05: the two symbol-configuration changes are refused after a ban too
    lambda a: a.change_margin_type(symbol=TEST_ONLY_SYMBOL, margin_type="ISOLATED"),
    lambda a: a.change_initial_leverage(symbol=TEST_ONLY_SYMBOL, leverage=5),
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
    # `_call` (every ordinary request) and the one stale-clock call of quick task 261023-sj2.
    assert attributes == ["to_thread", "to_thread"]


# --------------------------------------------------------------------------- #
# Task 3: state capture - open orders, open algo orders, positions, trades, balance,
# mark price and filters; purity guards.
# --------------------------------------------------------------------------- #

TEST_ONLY_UPDATE_MS = 1791360000000


def _open_order_row(**overrides: Any) -> CurrentAllOpenOrdersResponseInner:
    fields: dict[str, Any] = {
        "symbol": TEST_ONLY_SYMBOL,
        "client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
        "order_id": 8389765492,
        "side": "BUY",
        "position_side": "BOTH",
        "type": "LIMIT",
        "time_in_force": "GTC",
        "status": "NEW",
        "orig_qty": "0.010",
        "price": "50000.10",
        "stop_price": "0",
        "reduce_only": False,
        "close_position": False,
        "update_time": TEST_ONLY_UPDATE_MS,
    }
    return CurrentAllOpenOrdersResponseInner(**{**fields, **overrides})


def _open_algo_row(**overrides: Any) -> CurrentAllAlgoOpenOrdersResponseInner:
    fields: dict[str, Any] = {
        "symbol": TEST_ONLY_SYMBOL,
        "client_algo_id": TEST_ONLY_CLIENT_ALGO_ID,
        "algo_id": 3000000123,
        "algo_type": "CONDITIONAL",
        "order_type": "STOP_MARKET",
        "side": "SELL",
        "position_side": "BOTH",
        "time_in_force": "GTE_GTC",
        "algo_status": "NEW",
        "quantity": "0",
        "trigger_price": "48000.00",
        "working_type": "MARK_PRICE",
        "close_position": True,
        "reduce_only": True,
        "update_time": TEST_ONLY_UPDATE_MS,
    }
    return CurrentAllAlgoOpenOrdersResponseInner(**{**fields, **overrides})


def _position_row(amount: str, **overrides: Any) -> PositionInformationV3ResponseInner:
    fields: dict[str, Any] = {
        "symbol": TEST_ONLY_SYMBOL,
        "position_side": "BOTH",
        "position_amt": amount,
        "entry_price": "50000.1",
        "break_even_price": "50020.1",
        "mark_price": "50010.00000000",
        "un_realized_profit": "0.09990000",
        "liquidation_price": "0",
        "notional": "500.10000000",
        "margin_asset": "USDT",
        "update_time": TEST_ONLY_UPDATE_MS,
    }
    return PositionInformationV3ResponseInner(**{**fields, **overrides})


async def test_open_orders_reuse_the_production_converter_and_give_text_rows() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "current_all_open_orders",
        [_open_order_row(), _open_order_row(client_order_id="probe-test-order-0002", order_id=2)],
    )

    observation = await adapter.open_orders(symbol=TEST_ONLY_SYMBOL)

    assert rest.calls == [
        (
            "current_all_open_orders",
            {"symbol": TEST_ONLY_SYMBOL, "recv_window": TEST_ONLY_RECV_WINDOW_MS},
        )
    ]
    assert observation.ok is True
    assert observation.operation == "open_orders"
    summary = dict(observation.summary)
    assert summary["count"] == "2"
    assert summary["row_0_client_order_id"] == TEST_ONLY_CLIENT_ORDER_ID
    assert summary["row_0_exchange_order_id"] == "8389765492"
    assert summary["row_0_status"] == "NEW"
    assert summary["row_0_side"] == "BUY"
    assert summary["row_0_quantity"] == "0.010"
    assert summary["row_0_price"] == "50000.10"
    assert summary["row_0_stop_price"] == "0"
    assert summary["row_0_reduce_only"] == "false"
    assert summary["row_1_client_order_id"] == "probe-test-order-0002"
    assert summary["row_1_exchange_order_id"] == "2"
    assert all(isinstance(value, str) for value in summary.values())


async def test_open_orders_with_no_rows_gives_a_zero_count() -> None:
    adapter, rest, _ = _adapter()
    rest.script("current_all_open_orders", [])

    observation = await adapter.open_orders(symbol=TEST_ONLY_SYMBOL)

    assert dict(observation.summary) == {"count": "0"}


async def test_open_algo_orders_give_text_rows_with_the_trigger_price() -> None:
    adapter, rest, _ = _adapter()
    rest.script("current_all_algo_open_orders", [_open_algo_row()])

    observation = await adapter.open_algo_orders(symbol=TEST_ONLY_SYMBOL)

    assert rest.calls == [
        (
            "current_all_algo_open_orders",
            {"symbol": TEST_ONLY_SYMBOL, "recv_window": TEST_ONLY_RECV_WINDOW_MS},
        )
    ]
    summary = dict(observation.summary)
    assert summary["count"] == "1"
    assert summary["row_0_client_algo_id"] == TEST_ONLY_CLIENT_ALGO_ID
    assert summary["row_0_algo_id"] == "3000000123"
    assert summary["row_0_algo_status"] == "NEW"
    assert summary["row_0_side"] == "SELL"
    assert summary["row_0_quantity"] == "0"
    assert summary["row_0_trigger_price"] == "48000.00"
    assert summary["row_0_close_position"] == "true"
    assert "row_0_price" not in summary


async def test_positions_drop_zero_amount_rows_like_the_production_snapshot() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "position_information_v3",
        [
            _position_row("0.000", position_side="LONG"),
            _position_row("-0.010", position_side="SHORT"),
            _position_row("0"),
        ],
    )

    observation = await adapter.positions(symbol=TEST_ONLY_SYMBOL)

    assert rest.calls == [
        (
            "position_information_v3",
            {"symbol": TEST_ONLY_SYMBOL, "recv_window": TEST_ONLY_RECV_WINDOW_MS},
        )
    ]
    summary = dict(observation.summary)
    assert summary["count"] == "1"
    assert summary["row_0_position_side"] == "SHORT"
    assert summary["row_0_position_amt"] == "-0.010"
    assert summary["row_0_entry_price"] == "50000.1"
    assert summary["row_0_mark_price"] == "50010.00000000"
    assert not any(key.startswith("row_1_") for key in summary)


async def test_user_trades_give_the_trade_id_key_space_as_text() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "account_trade_list",
        [
            AccountTradeListResponseInner(
                id=698759,
                order_id=8389765492,
                symbol=TEST_ONLY_SYMBOL,
                side="BUY",
                price="50000.10",
                qty="0.010",
                commission="0.20000040",
                commission_asset="USDT",
                maker=False,
                time=TEST_ONLY_UPDATE_MS,
            )
        ],
    )

    observation = await adapter.user_trades(symbol=TEST_ONLY_SYMBOL, order_id=8389765492)

    assert rest.calls == [
        (
            "account_trade_list",
            {
                "symbol": TEST_ONLY_SYMBOL,
                "order_id": 8389765492,
                "recv_window": TEST_ONLY_RECV_WINDOW_MS,
            },
        )
    ]
    assert dict(observation.summary) == {
        "count": "1",
        "row_0_trade_id": "698759",
        "row_0_order_id": "8389765492",
        "row_0_price": "50000.10",
        "row_0_qty": "0.010",
        "row_0_commission": "0.20000040",
        "row_0_commission_asset": "USDT",
        "row_0_maker": "false",
        "row_0_time_ms": str(TEST_ONLY_UPDATE_MS),
        "row_0_side": "BUY",  # quick task 261021-sj0: the trade summary gained its side
    }


async def test_user_trades_without_an_order_id_omit_it() -> None:
    adapter, rest, _ = _adapter()
    rest.script("account_trade_list", [])

    observation = await adapter.user_trades(symbol=TEST_ONLY_SYMBOL)

    assert rest.calls[0][1] == {"symbol": TEST_ONLY_SYMBOL, "recv_window": TEST_ONLY_RECV_WINDOW_MS}
    assert dict(observation.summary) == {"count": "0"}


@pytest.mark.parametrize("bad", ["8389765492", True, 1.0])
async def test_user_trades_order_id_must_be_an_int(bad: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(TypeError):
        await adapter.user_trades(symbol=TEST_ONLY_SYMBOL, order_id=bad)
    assert rest.calls == []


async def test_account_balance_keeps_non_zero_assets_only() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "futures_account_balance_v3",
        [
            FuturesAccountBalanceV3Response(
                asset="USDT", balance="5000.12345678", available_balance="4800.00000000"
            ),
            FuturesAccountBalanceV3Response(
                asset="BNB", balance="0.00000000", available_balance="0.00000000"
            ),
            FuturesAccountBalanceV3Response(
                asset="USDC", balance="-0.50000000", available_balance="0"
            ),
        ],
    )

    observation = await adapter.account_balance()

    assert rest.calls == [("futures_account_balance_v3", {"recv_window": TEST_ONLY_RECV_WINDOW_MS})]
    assert dict(observation.summary) == {
        "count": "2",
        "row_0_asset": "USDT",
        "row_0_balance": "5000.12345678",
        "row_0_available_balance": "4800.00000000",
        "row_1_asset": "USDC",
        "row_1_balance": "-0.50000000",
        "row_1_available_balance": "0",
    }


async def test_read_errors_are_data_too() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "position_information_v3",
        BadRequestError(
            status_code=-1022, error_message="Signature for this request is not valid."
        ),
    )

    observation = await adapter.positions(symbol=TEST_ONLY_SYMBOL)

    assert observation.error == ErrorObservation(
        http_class="BAD_REQUEST",
        code=-1022,
        retry_after_seconds=None,
        category="AUTH_OR_SIGNATURE",
        message="Signature for this request is not valid.",
    )


_MARK_ROW = [
    1791360000000,
    "84090.10",
    "84130.00",
    "83900.00",
    "83905.50",
    "0",
    1791360059999,
    "0",
    60,
    "0",
    "0",
    "0",
]


async def test_mark_price_is_the_latest_one_minute_mark_close_as_text() -> None:
    adapter, rest, _ = _adapter()
    rest.script("mark_price_kline_candlestick_data", [_MARK_ROW])

    observation = await adapter.mark_price(symbol=TEST_ONLY_SYMBOL)

    ((name, kwargs),) = rest.calls
    assert name == "mark_price_kline_candlestick_data"
    assert kwargs["symbol"] == TEST_ONLY_SYMBOL
    assert kwargs["interval"] == MARK_PRICE_INTERVAL
    assert kwargs["limit"] == 1
    assert observation.ok is True
    assert observation.operation == "mark_price"
    assert dict(observation.summary) == {
        "symbol": TEST_ONLY_SYMBOL,
        "interval": MARK_PRICE_INTERVAL,
        "count": "1",
        "close": "83905.50",
        "open_time_utc": "2026-10-07T08:00:00+00:00",
        "close_time_utc": "2026-10-07T08:00:59.999000+00:00",
    }


async def test_mark_price_with_no_row_records_a_zero_count() -> None:
    adapter, rest, _ = _adapter()
    rest.script("mark_price_kline_candlestick_data", [])

    observation = await adapter.mark_price(symbol=TEST_ONLY_SYMBOL)

    assert dict(observation.summary) == {
        "symbol": TEST_ONLY_SYMBOL,
        "interval": MARK_PRICE_INTERVAL,
        "count": "0",
    }


def _filter_symbol(symbol: str) -> ExchangeInformationResponseSymbolsInner:
    return ExchangeInformationResponseSymbolsInner(
        symbol=symbol,
        contract_type="PERPETUAL",
        status="TRADING",
        base_asset="BTC",
        quote_asset="USDT",
        margin_asset="USDT",
        filters=[
            ExchangeInformationResponseSymbolsInnerFiltersInner(
                filter_type="PRICE_FILTER", tick_size="0.10"
            ),
            ExchangeInformationResponseSymbolsInnerFiltersInner(
                filter_type="LOT_SIZE", step_size="0.001", min_qty="0.001", max_qty="1000"
            ),
            ExchangeInformationResponseSymbolsInnerFiltersInner(
                filter_type="MIN_NOTIONAL", notional="100"
            ),
            ExchangeInformationResponseSymbolsInnerFiltersInner(
                filter_type="PERCENT_PRICE",
                multiplier_up="1.0500",
                multiplier_down="0.9500",
                multiplier_decimal="4",
            ),
        ],
    )


async def test_symbol_filters_come_from_exchange_info_as_text() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "exchange_information",
        ExchangeInformationResponse(symbols=[_filter_symbol("ETHUSDT"), _filter_symbol("BTCUSDT")]),
    )

    observation = await adapter.symbol_filters(symbol=TEST_ONLY_SYMBOL)

    assert rest.names() == ["exchange_information"]
    assert observation.ok is True
    assert observation.operation == "symbol_filters"
    assert dict(observation.summary) == {
        "symbol": TEST_ONLY_SYMBOL,
        "found": "true",
        "status": "TRADING",
        "tick_size": "0.10",
        "step_size": "0.001",
        "min_quantity": "0.001",
        "max_quantity": "1000",
        "min_notional": "100",
        "percent_price_multiplier_up": "1.0500",
        "percent_price_multiplier_down": "0.9500",
        "percent_price_multiplier_decimals": "4",
    }


async def test_symbol_filters_for_an_unlisted_symbol_record_not_found() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "exchange_information", ExchangeInformationResponse(symbols=[_filter_symbol("ETHUSDT")])
    )

    observation = await adapter.symbol_filters(symbol=TEST_ONLY_SYMBOL)

    assert dict(observation.summary) == {"symbol": TEST_ONLY_SYMBOL, "found": "false"}


async def test_public_reads_record_errors_as_data_and_rate_limits_in_the_gate() -> None:
    adapter, rest, gate = _adapter()
    rest.script(
        "mark_price_kline_candlestick_data",
        TooManyRequestsError(status_code=-1003, error_message="too many"),
    )

    observation = await adapter.mark_price(symbol=TEST_ONLY_SYMBOL)

    assert observation.error is not None
    assert observation.error.category == "RATE_LIMITED"
    assert adapter.banned is True
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.reason == RATE_LIMIT_PAUSE_429
    # The pause the public reader (holding the same gate) recorded.
    assert restriction.remaining_seconds == TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS
    with pytest.raises(ProbeBanned):
        await adapter.symbol_filters(symbol=TEST_ONLY_SYMBOL)
    assert rest.names() == ["mark_price_kline_candlestick_data"]


_READ_CALLS = [
    lambda a: a.open_orders(symbol=TEST_ONLY_SYMBOL),
    lambda a: a.open_algo_orders(symbol=TEST_ONLY_SYMBOL),
    lambda a: a.positions(symbol=TEST_ONLY_SYMBOL),
    lambda a: a.user_trades(symbol=TEST_ONLY_SYMBOL),
    lambda a: a.account_balance(),
    lambda a: a.mark_price(symbol=TEST_ONLY_SYMBOL),
    lambda a: a.symbol_filters(symbol=TEST_ONLY_SYMBOL),
    # quick task 261021-sj0: the capture reads
    lambda a: a.account_information(),
    lambda a: a.account_balance_all(),
    lambda a: a.account_config(),
    lambda a: a.symbol_config(symbol=TEST_ONLY_SYMBOL),
    lambda a: a.leverage_brackets(symbol=TEST_ONLY_SYMBOL),
    lambda a: a.income_history(symbol=TEST_ONLY_SYMBOL, start_time_ms=TEST_ONLY_UPDATE_MS),
    lambda a: a.query_algo_order_by_algo_id(algo_id=1000000001),
    lambda a: a.live_mark_price(symbol=TEST_ONLY_SYMBOL),
    # quick task 261022-sj1
    lambda a: a.server_time(),
    lambda a: a.order_book(symbol=TEST_ONLY_SYMBOL),
    # quick task 261023-sj2
    lambda a: a.stale_timestamp_read(
        symbol=TEST_ONLY_SYMBOL, recv_window_ms=5000, timestamp_behind_ms=10_000
    ),
]


@pytest.mark.parametrize("call", _READ_CALLS)
async def test_state_reads_are_refused_during_a_ban_or_pause(call: Any) -> None:
    adapter, rest, gate = _adapter()
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)

    with pytest.raises(ProbeBanned) as caught:
        await call(adapter)

    assert rest.calls == []
    assert caught.value.reason == RATE_LIMIT_PAUSE_429


async def test_a_public_refusal_raced_by_another_holder_becomes_probe_banned() -> None:
    """The gate restricts between the probe's own check and the public reader's check."""
    rest = FakeProbeRest()
    gate = make_gate()

    class _RacingPublic(BinancePublicMarketData):
        async def exchange_info(self) -> Any:
            gate.record(ExchangeErrorCategory.IP_BANNED, None)
            return await super().exchange_info()

    racing = _RacingPublic(sdk_client=FakeProbeSdk(rest), rest_gate=gate)  # type: ignore[arg-type]
    adapter = BinanceProbeAdapter(
        FakeProbeSdk(rest),
        policy=test_only_signed_call_policy(),
        rest_gate=gate,
        public=racing,
    )

    with pytest.raises(ProbeBanned) as caught:
        await adapter.symbol_filters(symbol=TEST_ONLY_SYMBOL)

    assert caught.value.reason == IP_BAN_418
    assert rest.calls == []


# --------------------------------------------------------------------------- #
# Quick task 261021-sj0: the capture operations (flattened account reads, income history,
# the algo query by id, the GTD limit and the live mark price).
# --------------------------------------------------------------------------- #

_RECV = TEST_ONLY_RECV_WINDOW_MS


async def test_account_information_flattens_every_present_field() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "account_information_v3",
        AccountInformationV3Response.from_dict(
            {
                "totalWalletBalance": "5000.12345678",
                "availableBalance": "4800.00000000",
                "totalCrossUnPnl": None,
                "assets": [
                    {"asset": "USDT", "walletBalance": "5000.12345678", "marginBalance": "5001"},
                    {"asset": "BNB", "walletBalance": "0.00000000"},
                ],
                "positions": [{"symbol": "BTCUSDT", "positionSide": "BOTH", "leverage": "20"}],
                "unlisted": "kept-as-additional-property",
            }
        ),
    )

    observation = await adapter.account_information()

    assert rest.calls == [("account_information_v3", {"recv_window": _RECV})]
    assert observation.ok is True and observation.operation == "account_information"
    assert dict(observation.summary) == {
        "totalWalletBalance": "5000.12345678",
        "availableBalance": "4800.00000000",
        "assets.0.asset": "USDT",
        "assets.0.walletBalance": "5000.12345678",
        "assets.0.marginBalance": "5001",
        "assets.1.asset": "BNB",
        "assets.1.walletBalance": "0.00000000",
        "positions.0.symbol": "BTCUSDT",
        "positions.0.positionSide": "BOTH",
        "positions.0.leverage": "20",
        "unlisted": "kept-as-additional-property",
    }  # None dropped, zero balance kept, no truncated key


async def test_account_balance_all_keeps_every_asset_and_every_field() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "futures_account_balance_v3",
        FuturesAccountBalanceV3Response.from_dict(
            [
                {"asset": "USDT", "balance": "5000", "availableBalance": "4800", "updateTime": 7},
                {"asset": "BNB", "balance": "0.00000000", "crossUnPnl": "0"},
            ]
        ),
    )

    observation = await adapter.account_balance_all()

    assert rest.calls == [("futures_account_balance_v3", {"recv_window": _RECV})]
    assert observation.operation == "account_balance_all"
    assert dict(observation.summary) == {
        "0.asset": "USDT",
        "0.balance": "5000",
        "0.availableBalance": "4800",
        "0.updateTime": "7",
        "1.asset": "BNB",
        "1.balance": "0.00000000",
        "1.crossUnPnl": "0",
    }


async def test_account_config_gives_the_wire_names_with_booleans_as_text() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "futures_account_configuration",
        FuturesAccountConfigurationResponse.from_dict(
            {"feeTier": 0, "canTrade": True, "dualSidePosition": False, "multiAssetsMargin": False}
        ),
    )

    observation = await adapter.account_config()

    assert rest.calls == [("futures_account_configuration", {"recv_window": _RECV})]
    assert observation.operation == "account_config"
    assert dict(observation.summary) == {
        "feeTier": "0",
        "canTrade": "true",
        "dualSidePosition": "false",
        "multiAssetsMargin": "false",
    }


async def test_symbol_config_sends_the_symbol_and_flattens_the_rows() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "symbol_configuration",
        SymbolConfigurationResponse.from_dict(
            [
                {
                    "symbol": "BTCUSDT",
                    "marginType": "CROSSED",
                    "isAutoAddMargin": False,
                    "leverage": 20,
                }
            ]
        ),
    )

    observation = await adapter.symbol_config(symbol=TEST_ONLY_SYMBOL)

    assert rest.calls == [
        ("symbol_configuration", {"symbol": TEST_ONLY_SYMBOL, "recv_window": _RECV})
    ]
    assert observation.operation == "symbol_config"
    assert dict(observation.summary) == {
        "0.symbol": "BTCUSDT",
        "0.marginType": "CROSSED",
        "0.isAutoAddMargin": "false",
        "0.leverage": "20",
    }


async def test_leverage_brackets_unwrap_the_one_of_wrapper() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "notional_and_leverage_brackets",
        NotionalAndLeverageBracketsResponse.from_dict(
            [
                {
                    "symbol": "BTCUSDT",
                    "brackets": [
                        {"bracket": 1, "initialLeverage": 125, "notionalCap": 50000},
                        {"bracket": 2, "initialLeverage": 100},
                    ],
                }
            ]
        ),
    )

    observation = await adapter.leverage_brackets(symbol=TEST_ONLY_SYMBOL)

    assert rest.calls == [
        ("notional_and_leverage_brackets", {"symbol": TEST_ONLY_SYMBOL, "recv_window": _RECV})
    ]
    assert observation.operation == "leverage_brackets"
    assert dict(observation.summary) == {
        "0.symbol": "BTCUSDT",
        "0.brackets.0.bracket": "1",
        "0.brackets.0.initialLeverage": "125",
        "0.brackets.0.notionalCap": "50000",
        "0.brackets.1.bracket": "2",
        "0.brackets.1.initialLeverage": "100",
    }


async def test_a_single_symbol_bracket_answer_flattens_too() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "notional_and_leverage_brackets",
        NotionalAndLeverageBracketsResponse.from_dict(
            {"symbol": "BTCUSDT", "brackets": [{"bracket": 1, "initialLeverage": 125}]}
        ),
    )

    observation = await adapter.leverage_brackets(symbol=TEST_ONLY_SYMBOL)

    assert dict(observation.summary) == {
        "symbol": "BTCUSDT",
        "brackets.0.bracket": "1",
        "brackets.0.initialLeverage": "125",
    }


async def test_the_flat_summary_scrubs_caps_and_truncates() -> None:
    register_runtime_secret(TEST_ONLY_SECRET)
    adapter, rest, _ = _adapter()
    long_text = "x" * (ERROR_MESSAGE_MAX_CHARS + 50)
    rest.script(
        "futures_account_configuration",
        FuturesAccountConfigurationResponse.from_dict(
            {"feeTier": 0, "note": f"has {TEST_ONLY_SECRET} inside", "long": long_text}
        ),
    )
    observation = await adapter.account_config()
    assert TEST_ONLY_SECRET not in observation.summary["note"]
    assert REDACTED in observation.summary["note"]
    assert observation.summary["long"] == "x" * ERROR_MESSAGE_MAX_CHARS

    many = [{"asset": f"A{index}"} for index in range(binance_probe.FLAT_SUMMARY_MAX_KEYS + 25)]
    rest.script("futures_account_balance_v3", FuturesAccountBalanceV3Response.from_dict(many))
    big = await adapter.account_balance_all()
    assert big.summary["truncated"] == "true"
    assert len(big.summary) == binance_probe.FLAT_SUMMARY_MAX_KEYS + 1
    assert "0.asset" in big.summary and f"{len(many) - 1}.asset" not in big.summary


async def test_the_flat_summary_of_an_empty_answer_is_empty() -> None:
    adapter, rest, _ = _adapter()
    rest.script("futures_account_balance_v3", [])
    observation = await adapter.account_balance_all()
    assert observation.ok is True and dict(observation.summary) == {}


@pytest.mark.parametrize(
    ("name", "sdk", "call"),
    [
        ("account_information", "account_information_v3", lambda a: a.account_information()),
        ("account_balance_all", "futures_account_balance_v3", lambda a: a.account_balance_all()),
        ("account_config", "futures_account_configuration", lambda a: a.account_config()),
        (
            "symbol_config",
            "symbol_configuration",
            lambda a: a.symbol_config(symbol=TEST_ONLY_SYMBOL),
        ),
        (
            "leverage_brackets",
            "notional_and_leverage_brackets",
            lambda a: a.leverage_brackets(symbol=TEST_ONLY_SYMBOL),
        ),
    ],
)
async def test_the_flat_reads_record_an_exchange_error_as_data(
    name: str, sdk: str, call: Any
) -> None:
    adapter, rest, _ = _adapter()
    rest.script(sdk, BadRequestError(status_code=-2015, error_message="Invalid API-key."))
    observation = await call(adapter)
    assert observation.ok is False and observation.operation == name
    assert observation.error is not None and observation.error.code == -2015


async def test_income_history_sends_symbol_and_start_time_only() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "get_income_history",
        [
            GetIncomeHistoryResponse(
                symbol="BTCUSDT",
                income_type="COMMISSION",
                income="-0.02400000",
                asset="USDT",
                info=f"8389765492 {TEST_ONLY_SECRET}",
                time=TEST_ONLY_UPDATE_MS,
                tran_id=9001,
                trade_id="4411",
            ),
            GetIncomeHistoryResponse(
                symbol="BTCUSDT",
                income_type="REALIZED_PNL",
                income="0.50000000",
                asset="USDT",
                time=TEST_ONLY_UPDATE_MS + 1,
                tran_id=9002,
                trade_id="4411",
            ),
        ],
    )
    register_runtime_secret(TEST_ONLY_SECRET)

    observation = await adapter.income_history(
        symbol=TEST_ONLY_SYMBOL, start_time_ms=TEST_ONLY_UPDATE_MS
    )

    assert rest.calls == [
        (
            "get_income_history",
            {"symbol": TEST_ONLY_SYMBOL, "start_time": TEST_ONLY_UPDATE_MS, "recv_window": _RECV},
        )
    ]
    assert observation.operation == "income_history"
    summary = dict(observation.summary)
    assert TEST_ONLY_SECRET not in summary["row_0_info"]
    summary.pop("row_0_info")
    assert summary == {
        "count": "2",
        "row_0_symbol": "BTCUSDT",
        "row_0_income_type": "COMMISSION",
        "row_0_income": "-0.02400000",
        "row_0_asset": "USDT",
        "row_0_time_ms": str(TEST_ONLY_UPDATE_MS),
        "row_0_tran_id": "9001",
        "row_0_trade_id": "4411",
        "row_1_symbol": "BTCUSDT",
        "row_1_income_type": "REALIZED_PNL",
        "row_1_income": "0.50000000",
        "row_1_asset": "USDT",
        "row_1_time_ms": str(TEST_ONLY_UPDATE_MS + 1),
        "row_1_tran_id": "9002",
        "row_1_trade_id": "4411",
    }


@pytest.mark.parametrize("bad", [True, 0, -5])
async def test_income_history_refuses_a_bad_start_time(bad: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises((TypeError, ValueError)):
        await adapter.income_history(symbol=TEST_ONLY_SYMBOL, start_time_ms=bad)
    with pytest.raises(TypeError):
        await adapter.income_history(symbol=TEST_ONLY_SYMBOL, start_time_ms=1.5)  # type: ignore[arg-type]
    assert rest.calls == []


async def test_query_algo_order_by_algo_id_sends_the_int_id() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "query_algo_order",
        QueryAlgoOrderResponse(
            algo_id=1000000001, client_algo_id=TEST_ONLY_CLIENT_ALGO_ID, algo_status="NEW"
        ),
    )

    observation = await adapter.query_algo_order_by_algo_id(algo_id=1000000001)

    assert rest.calls == [("query_algo_order", {"algo_id": 1000000001, "recv_window": _RECV})]
    assert observation.operation == "query_algo_order_by_algo_id"
    assert dict(observation.summary) == {
        "algo_id": "1000000001",
        "client_algo_id": TEST_ONLY_CLIENT_ALGO_ID,
        "algo_status": "NEW",
    }


@pytest.mark.parametrize("bad", [True, False, 0, -1, "1000000001", 1.0])
async def test_query_algo_order_by_algo_id_refuses_a_bool_or_a_non_positive_id(bad: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises((TypeError, ValueError)):
        await adapter.query_algo_order_by_algo_id(algo_id=bad)
    assert rest.calls == []


async def test_new_gtd_limit_order_sends_gtd_and_the_int_good_till_date() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "new_order",
        NewOrderResponse(
            order_id=1,
            client_order_id=TEST_ONLY_CLIENT_ORDER_ID,
            status="NEW",
            time_in_force="GTD",
            good_till_date=TEST_ONLY_UPDATE_MS + 660_000,
        ),
    )

    observation = await adapter.new_gtd_limit_order(
        symbol=TEST_ONLY_SYMBOL,
        side="BUY",
        quantity=Decimal("0.0008"),
        price=Decimal("50000.10"),
        client_order_id=TEST_ONLY_CLIENT_ORDER_ID,
        position_side="BOTH",
        good_till_date_ms=TEST_ONLY_UPDATE_MS + 660_000,
    )

    assert rest.calls == [
        (
            "new_order",
            {
                "symbol": TEST_ONLY_SYMBOL,
                "side": NewOrderSideEnum.BUY,
                "type": NewOrderTypeEnum.LIMIT,
                "position_side": "BOTH",
                "time_in_force": NewOrderTimeInForceEnum.GTD,
                "quantity": "0.0008",
                "price": "50000.10",
                "new_client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
                "good_till_date": TEST_ONLY_UPDATE_MS + 660_000,
                "recv_window": _RECV,
            },
        )
    ]
    assert "reduce_only" not in rest.calls[0][1]
    assert isinstance(rest.calls[0][1]["good_till_date"], int)
    assert observation.operation == "new_gtd_limit_order"
    assert observation.summary["good_till_date"] == str(TEST_ONLY_UPDATE_MS + 660_000)
    assert observation.summary["time_in_force"] == "GTD"


@pytest.mark.parametrize("bad", [True, 1.5, "1791360660000", None])
async def test_new_gtd_limit_order_refuses_a_non_int_good_till_date(bad: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(TypeError):
        await _gtd(adapter, good_till_date_ms=bad)
    assert rest.calls == []


@pytest.mark.parametrize("bad", [0, -1])
async def test_new_gtd_limit_order_refuses_a_non_positive_good_till_date(bad: int) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(ValueError):
        await _gtd(adapter, good_till_date_ms=bad)
    assert rest.calls == []


async def test_new_gtd_limit_order_keeps_the_money_and_enum_rules() -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises(TypeError):
        await _gtd(adapter, quantity=0.0008)
    with pytest.raises(ValueError):
        await _gtd(adapter, price=Decimal(0))
    with pytest.raises(ValueError):
        await _gtd(adapter, side="HOLD")
    assert rest.calls == []


async def _gtd(adapter: BinanceProbeAdapter, **overrides: Any) -> ProbeObservation:
    arguments: dict[str, Any] = {
        "symbol": TEST_ONLY_SYMBOL,
        "side": "BUY",
        "quantity": Decimal("0.0008"),
        "price": Decimal("50000.10"),
        "client_order_id": TEST_ONLY_CLIENT_ORDER_ID,
        "position_side": "BOTH",
        "good_till_date_ms": TEST_ONLY_UPDATE_MS + 660_000,
    }
    arguments.update(overrides)
    return await adapter.new_gtd_limit_order(**arguments)


async def test_a_gtd_placement_timeout_is_recorded_once_and_never_retried() -> None:
    adapter, rest, _ = _adapter()
    rest.script("new_order", NetworkError("FAKE: connection reset"))
    observation = await _gtd(adapter)
    assert observation.ok is False
    assert rest.names() == ["new_order"]


async def test_live_mark_price_is_the_premium_index_mark_as_text() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "mark_price",
        MarkPriceResponse(
            actual_instance=MarkPriceResponse1(
                symbol=TEST_ONLY_SYMBOL, mark_price="83748.12345678", time=TEST_ONLY_UPDATE_MS
            )
        ),
    )

    observation = await adapter.live_mark_price(symbol=TEST_ONLY_SYMBOL)

    assert rest.calls == [("mark_price", {"symbol": TEST_ONLY_SYMBOL})]  # public: no recvWindow
    assert observation.ok is True and observation.operation == "live_mark_price"
    assert dict(observation.summary) == {
        "symbol": TEST_ONLY_SYMBOL,
        "mark_price": "83748.12345678",
        "exchange_time_utc": "2026-10-07T08:00:00+00:00",
    }


async def test_live_mark_price_records_an_unreadable_answer_as_data() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "mark_price",
        MarkPriceResponse(
            actual_instance=MarkPriceResponse1(symbol="ETHUSDT", mark_price="1", time=1)
        ),
    )
    observation = await adapter.live_mark_price(symbol=TEST_ONLY_SYMBOL)
    assert observation.ok is False
    assert observation.error is not None and observation.error.message == "ValueError"


# --------------------------------------------------------------------------- #
# Purity guards.
# --------------------------------------------------------------------------- #


def test_module_has_no_float_call_no_wall_clock_and_no_paper_import() -> None:
    assert float_constructor_calls(MODULE_PATH) == []
    assert wall_clock_calls(MODULE_PATH) == []
    assert forbidden_imports(MODULE_PATH, ["src.paper"]) == []


def test_purity_guards_catch_a_seeded_violation(tmp_path: Path) -> None:
    seeded = tmp_path / "seeded.py"
    seeded.write_text(
        "import datetime\nfrom src.paper import freeze\n"
        "x = float('1.0')\ny = datetime.datetime.now()\n",
        encoding="utf-8",
    )
    assert float_constructor_calls(seeded) == [3]
    assert [name for _, name in wall_clock_calls(seeded)] == ["datetime.datetime.now"]
    assert forbidden_imports(seeded, ["src.paper"]) == ["src.paper"]


_ALLOWED_RETURNS = frozenset({"ProbeObservation", "list[ProbeObservation]"})


def _public_coroutine_returns(path: Path) -> dict[str, str]:
    """Return annotation text of every public coroutine of BinanceProbeAdapter."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    (cls,) = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "BinanceProbeAdapter"
    ]
    return {
        node.name: ast.unparse(node.returns) if node.returns is not None else ""
        for node in cls.body
        if isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_")
    }


def test_every_public_coroutine_returns_observations_only() -> None:
    returns = _public_coroutine_returns(MODULE_PATH)
    assert set(returns) == {
        "query_order",
        "query_algo_order",
        "new_limit_order",
        "new_market_order",
        "new_conditional_order",
        "cancel_order",
        "cancel_algo_order",
        "cancel_all_open_orders",
        "cancel_all_algo_open_orders",
        "open_orders",
        "open_algo_orders",
        "positions",
        "user_trades",
        "account_balance",
        "mark_price",
        "symbol_filters",
        # quick task 261021-sj0
        "account_information",
        "account_balance_all",
        "account_config",
        "symbol_config",
        "leverage_brackets",
        "income_history",
        "query_algo_order_by_algo_id",
        "new_gtd_limit_order",
        "live_mark_price",
        # quick task 261022-sj1
        "server_time",
        "order_book",
        # quick task 261023-sj2
        "stale_timestamp_read",
        # Phase 22 plan 22-05
        "change_margin_type",
        "change_initial_leverage",
    }
    assert {name: text for name, text in returns.items() if text not in _ALLOWED_RETURNS} == {}


def test_the_return_walk_catches_a_raw_sdk_return(tmp_path: Path) -> None:
    seeded = tmp_path / "seeded.py"
    seeded.write_text(
        "class BinanceProbeAdapter:\n"
        "    async def query_order(self) -> ProbeObservation: ...\n"
        "    async def leak(self) -> QueryOrderResponse: ...\n",
        encoding="utf-8",
    )
    returns = _public_coroutine_returns(seeded)
    assert {name for name, text in returns.items() if text not in _ALLOWED_RETURNS} == {"leak"}


# --------------------------------------------------------------------------- #
# Quick task 261022-sj1: the server time and the depth read.
# --------------------------------------------------------------------------- #


async def test_server_time_is_the_exchange_clock_as_milliseconds_and_utc_text() -> None:
    adapter, rest, _ = _adapter()
    rest.script("check_server_time", CheckServerTimeResponse(server_time=1791360123456))

    observation = await adapter.server_time()

    assert rest.calls == [("check_server_time", {})]  # public: no recvWindow
    assert observation.ok is True and observation.operation == "server_time"
    assert dict(observation.summary) == {
        "server_time_ms": "1791360123456",
        "server_time_utc": "2026-10-07T08:02:03.456000+00:00",
    }


async def test_server_time_keeps_every_millisecond_digit() -> None:
    adapter, rest, _ = _adapter()
    for ms in (1791360123001, 1791360123999, 1791360123123):
        rest.script("check_server_time", CheckServerTimeResponse(server_time=ms))
        observation = await adapter.server_time()
        assert observation.summary["server_time_ms"] == str(ms)


async def test_server_time_records_an_unreadable_answer_as_data() -> None:
    adapter, rest, _ = _adapter()
    rest.script("check_server_time", CheckServerTimeResponse(server_time=None))
    observation = await adapter.server_time()
    assert observation.ok is False
    assert observation.error is not None and observation.error.message == "ValueError"


async def test_order_book_summarises_the_levels_as_text() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "order_book",
        OrderBookResponse(
            last_update_id=7,
            E=1791360123456,
            T=1791360123450,
            bids=[["83900.10", "1.500"], ["83900.00", "2"]],
            asks=[["83900.20", "0.250"], ["83900.30", "2"], ["83900.40", "10"]],
        ),
    )

    observation = await adapter.order_book(symbol=TEST_ONLY_SYMBOL)

    assert rest.calls == [("order_book", {"symbol": TEST_ONLY_SYMBOL, "limit": 20})]
    assert observation.ok is True and observation.operation == "order_book"
    assert dict(observation.summary) == {
        "symbol": TEST_ONLY_SYMBOL,
        "last_update_id": "7",
        "bid_count": "2",
        "ask_count": "3",
        "bid_0_price": "83900.10",
        "bid_0_quantity": "1.500",
        "bid_1_price": "83900.00",
        "bid_1_quantity": "2",
        "ask_0_price": "83900.20",
        "ask_0_quantity": "0.250",
        "ask_1_price": "83900.30",
        "ask_1_quantity": "2",
        "ask_2_price": "83900.40",
        "ask_2_quantity": "10",
    }


async def test_order_book_records_a_malformed_answer_as_data() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "order_book",
        OrderBookResponse(last_update_id=7, E=1, T=1, bids=[["1", "1"]], asks=[["x", "1"]]),
    )
    observation = await adapter.order_book(symbol=TEST_ONLY_SYMBOL)
    assert observation.ok is False
    assert observation.error is not None and observation.error.message == "ValueError"


# --------------------------------------------------------------------------- #
# Quick task 261023-sj2: the stale-timestamp read (the -1021 answer).
# --------------------------------------------------------------------------- #


class _ClockAskingRest(FakeProbeRest):
    """A fake whose `current_all_open_orders` asks the SDK clock like `send_request` does."""

    def __init__(self) -> None:
        super().__init__()
        self.clock_values: list[int] = []

    def current_all_open_orders(self, **kwargs: Any) -> Any:
        import binance_common.utils as sdk_utils

        self.clock_values.append(sdk_utils.get_timestamp())
        return super().current_all_open_orders(**kwargs)


async def test_the_stale_read_sends_the_clock_minus_the_given_milliseconds() -> None:
    import binance_common.utils as sdk_utils

    original = sdk_utils.get_timestamp
    rest = _ClockAskingRest()
    adapter, _, _ = _adapter(rest)
    rest.script("current_all_open_orders", [])
    before = original()
    observation = await adapter.stale_timestamp_read(
        symbol=TEST_ONLY_SYMBOL, recv_window_ms=5000, timestamp_behind_ms=10_000
    )
    after = original()
    assert observation.ok is True and observation.operation == "stale_timestamp_read"
    (sent,) = rest.clock_values
    assert before - 10_000 <= sent <= after - 10_000
    assert observation.summary["timestamp_sent_ms"] == str(sent)
    assert observation.summary["timestamp_behind_ms"] == "10000"
    assert observation.summary["recv_window_ms"] == "5000"
    assert observation.summary["clock_calls"] == "1"
    assert observation.summary["count"] == "0"
    assert rest.calls == [
        ("current_all_open_orders", {"symbol": TEST_ONLY_SYMBOL, "recv_window": 5000})
    ]
    assert sdk_utils.get_timestamp is original  # the SDK clock is back


async def test_the_stale_read_records_the_exchange_error_with_the_clock_facts() -> None:
    rest = _ClockAskingRest()
    adapter, _, _ = _adapter(rest)
    rest.script(
        "current_all_open_orders",
        BadRequestError(
            status_code=-1021,
            error_message="Timestamp for this request is outside of the recvWindow.",
        ),
    )
    observation = await adapter.stale_timestamp_read(
        symbol=TEST_ONLY_SYMBOL, recv_window_ms=5000, timestamp_behind_ms=10_000
    )
    assert observation.ok is False
    assert observation.error is not None
    assert observation.error.code == -1021
    assert observation.error.http_class == "BAD_REQUEST"
    assert "recvWindow" in observation.error.message
    assert observation.summary["clock_calls"] == "1"
    assert observation.summary["timestamp_behind_ms"] == "10000"


async def test_a_read_that_never_asks_the_sdk_clock_says_so() -> None:
    adapter, rest, _ = _adapter()  # the plain fake never asks the clock
    rest.script("current_all_open_orders", [])
    observation = await adapter.stale_timestamp_read(
        symbol=TEST_ONLY_SYMBOL, recv_window_ms=5000, timestamp_behind_ms=10_000
    )
    assert observation.summary["clock_calls"] == "0"
    assert "timestamp_sent_ms" not in observation.summary


async def test_the_sdk_clock_is_restored_after_an_exception_and_other_threads_see_real_time() -> (
    None
):
    import binance_common.utils as sdk_utils

    original = sdk_utils.get_timestamp
    seen_in_other_thread: list[int] = []

    class _Rest(_ClockAskingRest):
        def current_all_open_orders(self, **kwargs: Any) -> Any:
            worker = threading.Thread(
                target=lambda: seen_in_other_thread.append(sdk_utils.get_timestamp())
            )
            worker.start()
            worker.join()
            raise NetworkError(error_message="boom")

    rest = _Rest()
    adapter, _, _ = _adapter(rest)
    start = original()
    observation = await adapter.stale_timestamp_read(
        symbol=TEST_ONLY_SYMBOL, recv_window_ms=5000, timestamp_behind_ms=60_000
    )
    assert observation.ok is False
    assert sdk_utils.get_timestamp is original
    (other,) = seen_in_other_thread
    assert other >= start  # another thread is never made stale


@pytest.mark.parametrize(
    ("window", "behind"),
    [(0, 10), (-1, 10), (5000, 0), (5000, -3), (True, 10), (5000, True), (5000.0, 10), (5000, 1.5)],
)
async def test_the_stale_read_refuses_a_window_or_offset_that_is_not_a_positive_int(
    window: Any, behind: Any
) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises((TypeError, ValueError)):
        await adapter.stale_timestamp_read(
            symbol=TEST_ONLY_SYMBOL, recv_window_ms=window, timestamp_behind_ms=behind
        )
    assert rest.calls == []


async def test_the_stale_read_is_refused_after_a_ban_without_an_sdk_call() -> None:
    adapter, rest, gate = _adapter()
    rest.script(
        "current_all_open_orders", TooManyRequestsError(error_message="slow", retry_after=3)
    )
    await adapter.open_orders(symbol=TEST_ONLY_SYMBOL)
    assert gate.restriction() is not None
    with pytest.raises(ProbeBanned):
        await adapter.stale_timestamp_read(
            symbol=TEST_ONLY_SYMBOL, recv_window_ms=5000, timestamp_behind_ms=10_000
        )
    assert len(rest.calls) == 1


# --------------------------------------------------------------------------- #
# Phase 22 plan 22-05: change_margin_type and change_initial_leverage (mutating, sent once).
# --------------------------------------------------------------------------- #


async def test_change_margin_type_sends_the_enum_member_once_and_records_code_and_msg() -> None:
    adapter, rest, _ = _adapter()
    rest.script("change_margin_type", ChangeMarginTypeResponse(code=200, msg="success"))

    observation = await adapter.change_margin_type(symbol=TEST_ONLY_SYMBOL, margin_type="ISOLATED")

    assert rest.calls == [
        (
            "change_margin_type",
            {
                "symbol": TEST_ONLY_SYMBOL,
                "margin_type": ChangeMarginTypeMarginTypeEnum.ISOLATED,
                "recv_window": _RECV,
            },
        )
    ]
    assert observation.operation == "change_margin_type"
    assert observation.ok is True and observation.error is None
    assert dict(observation.summary) == {"code": "200", "msg": "success"}


@pytest.mark.parametrize("bad", ["isolated", "CROSS", "", "ISOLATED ", 1, None, True])
async def test_change_margin_type_refuses_any_other_value_before_an_sdk_call(bad: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises((TypeError, ValueError)):
        await adapter.change_margin_type(symbol=TEST_ONLY_SYMBOL, margin_type=bad)
    assert rest.calls == []


async def test_change_margin_type_records_an_exchange_error_as_data_and_never_retries() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "change_margin_type",
        BadRequestError(status_code=-4046, error_message="No need to change margin type."),
    )

    observation = await adapter.change_margin_type(symbol=TEST_ONLY_SYMBOL, margin_type="ISOLATED")

    assert len(rest.calls) == 1  # sent once
    assert observation.ok is False and observation.error is not None
    assert observation.error.code == -4046
    assert observation.error.http_class == "BAD_REQUEST"
    assert adapter.banned is False


async def test_change_initial_leverage_sends_an_int_once_and_records_the_answer() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "change_initial_leverage",
        ChangeInitialLeverageResponse(symbol="BTCUSDT", leverage=5, max_notional_value="5000000"),
    )

    observation = await adapter.change_initial_leverage(symbol=TEST_ONLY_SYMBOL, leverage=5)

    assert rest.calls == [
        (
            "change_initial_leverage",
            {"symbol": TEST_ONLY_SYMBOL, "leverage": 5, "recv_window": _RECV},
        )
    ]
    assert type(rest.calls[0][1]["leverage"]) is int
    assert observation.operation == "change_initial_leverage"
    assert dict(observation.summary) == {
        "symbol": "BTCUSDT",
        "leverage": "5",
        "maxNotionalValue": "5000000",
    }


@pytest.mark.parametrize("bad", [0, -1, -20, True, False, 5.0, "5", None])
async def test_change_initial_leverage_refuses_a_non_positive_or_non_int_leverage(bad: Any) -> None:
    adapter, rest, _ = _adapter()
    with pytest.raises((TypeError, ValueError)):
        await adapter.change_initial_leverage(symbol=TEST_ONLY_SYMBOL, leverage=bad)
    assert rest.calls == []


async def test_change_initial_leverage_records_an_exchange_error_and_never_retries() -> None:
    adapter, rest, _ = _adapter()
    rest.script(
        "change_initial_leverage",
        ServerError(status_code=503, error_message="busy"),
    )

    observation = await adapter.change_initial_leverage(symbol=TEST_ONLY_SYMBOL, leverage=5)

    assert len(rest.calls) == 1
    assert observation.ok is False and observation.error is not None
    assert observation.error.category == "STATUS_UNKNOWN"  # a change is never re-sent
