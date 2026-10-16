"""Behavior of the Demo-probe adapter (plan 18-12).

`BinanceProbeAdapter` turns every exchange answer into a frozen `ProbeObservation`: an error
is recorded as data (HTTP class, int code, category, scrubbed message), never raised. These
tests drive it with the SDK-shaped fakes of `tests/probe_fakes.py`; nothing opens a
connection, and every limit value is a TEST_ONLY constant.
"""

from __future__ import annotations

import dataclasses
import threading
from typing import Any

import pytest
from binance_common.errors import BadRequestError
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    QueryAlgoOrderResponse,
    QueryOrderResponse,
)
from src.adapters.binance_limits import RateLimitPolicy, SignedCallPolicy
from src.adapters.binance_probe import (
    ERROR_MESSAGE_MAX_CHARS,
    BinanceProbeAdapter,
    ErrorObservation,
    ProbeBanned,
    ProbeObservation,
)
from src.adapters.binance_ratelimit_gate import IP_BAN_418, RestRateLimitGate
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
