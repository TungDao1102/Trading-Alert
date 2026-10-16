"""Offline SDK contract of the probe adapter (plan 18-12, threat T-18-35).

The probe adapter is first run against Binance by the user at the plan 18-20 checkpoint, so a
mistyped SDK keyword or enum would otherwise surface only then, possibly with an order left
open. Every SDK call the adapter makes is recorded by the fake of `tests/probe_fakes.py` and
bound here with `inspect.signature` against the installed
`DerivativesTradingUsdsFuturesRestAPI` method of the same name: an unknown keyword fails.
Negative controls prove that the binding check bites. Only classes are introspected; no SDK
client is constructed and nothing opens a connection.
"""

from __future__ import annotations

import ast
import inspect
import typing
from collections.abc import Awaitable, Callable
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures.rest_api import (
    DerivativesTradingUsdsFuturesRestAPI as SdkRestApi,
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
from src.adapters import binance_probe
from src.adapters.binance_probe import SDK_REST_METHODS, BinanceProbeAdapter

from tests.probe_fakes import FakeProbeRest, FakeProbeSdk, make_gate
from tests.support.limits import TEST_ONLY_RECV_WINDOW_MS, test_only_signed_call_policy

MODULE_PATH = Path(binance_probe.__file__)

_Op = Callable[[BinanceProbeAdapter], Awaitable[Any]]

# One driver per adapter operation, with the scripted success payload of each SDK method.
_SUCCESS_PAYLOADS: dict[str, Any] = {
    "query_order": QueryOrderResponse(order_id=1, status="NEW"),
    "query_algo_order": QueryAlgoOrderResponse(algo_id=1, algo_status="NEW"),
    "new_order": NewOrderResponse(order_id=1, status="NEW"),
    "new_algo_order": NewAlgoOrderResponse(algo_id=1, algo_status="NEW"),
    "cancel_order": CancelOrderResponse(order_id=1, status="CANCELED"),
    "cancel_algo_order": CancelAlgoOrderResponse(algo_id=1, code="200", msg="success"),
    "cancel_all_open_orders": CancelAllOpenOrdersResponse(code=200, msg="done"),
    "cancel_all_algo_open_orders": CancelAllAlgoOpenOrdersResponse(code=200, msg="done"),
}

_Q = Decimal("0.010")
_P = Decimal("50000.10")
_T = Decimal("48000.00")

_OPERATIONS: dict[str, _Op] = {
    "query_order": lambda a: a.query_order(symbol="BTCUSDT", client_order_id="c1"),
    "query_algo_order": lambda a: a.query_algo_order(client_algo_id="a1"),
    "new_limit_order": lambda a: a.new_limit_order(
        symbol="BTCUSDT",
        side="BUY",
        quantity=_Q,
        price=_P,
        client_order_id="c1",
        position_side="BOTH",
        time_in_force="GTC",
        reduce_only=None,
    ),
    "new_limit_order_reduce_only": lambda a: a.new_limit_order(
        symbol="BTCUSDT",
        side="SELL",
        quantity=_Q,
        price=_P,
        client_order_id="c2",
        position_side="BOTH",
        time_in_force="GTX",
        reduce_only=True,
    ),
    "new_market_order": lambda a: a.new_market_order(
        symbol="BTCUSDT",
        side="SELL",
        quantity=_Q,
        client_order_id="c3",
        position_side="BOTH",
        reduce_only=True,
    ),
    "conditional_explicit_quantity_reduce_only": lambda a: a.new_conditional_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="TAKE_PROFIT_MARKET",
        client_algo_id="a2",
        position_side="BOTH",
        trigger_price=_T,
        working_type="MARK_PRICE",
        quantity=_Q,
        reduce_only=True,
    ),
    "conditional_close_position": lambda a: a.new_conditional_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="STOP_MARKET",
        client_algo_id="a3",
        position_side="BOTH",
        trigger_price=_T,
        working_type="MARK_PRICE",
        close_position=True,
    ),
    "conditional_stop_limit_with_time_in_force": lambda a: a.new_conditional_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="STOP",
        client_algo_id="a4",
        position_side="LONG",
        trigger_price=_T,
        working_type="MARK_PRICE",
        quantity=_Q,
        price=_T,
        time_in_force="GTC",
        reduce_only=False,
        close_position=False,
    ),
    "cancel_order": lambda a: a.cancel_order(symbol="BTCUSDT", client_order_id="c1"),
    "cancel_algo_order": lambda a: a.cancel_algo_order(client_algo_id="a1"),
    "cancel_all_open_orders": lambda a: a.cancel_all_open_orders(symbol="BTCUSDT"),
    "cancel_all_algo_open_orders": lambda a: a.cancel_all_algo_open_orders(symbol="BTCUSDT"),
}


def _bind(name: str, kwargs: dict[str, Any]) -> None:
    """Bind `kwargs` to the installed SDK method `name` (raises TypeError on a wrong keyword)."""
    signature = inspect.signature(getattr(SdkRestApi, name))
    signature.bind(None, **kwargs)


def _enum_class(annotation: Any) -> type[Enum] | None:
    """The Enum class inside an `Optional[...]` SDK annotation, if any."""
    for candidate in (annotation, *typing.get_args(annotation)):
        if isinstance(candidate, type) and issubclass(candidate, Enum):
            return candidate
    return None


def _check_argument_types(name: str, kwargs: dict[str, Any]) -> None:
    """An enum-annotated SDK parameter gets a member of that enum; nothing is a float."""
    hints = typing.get_type_hints(getattr(SdkRestApi, name))
    for key, value in kwargs.items():
        assert not isinstance(value, float), (name, key)
        enum_cls = _enum_class(hints.get(key))
        if enum_cls is not None:
            assert isinstance(value, enum_cls), (name, key, value)
        else:
            assert not isinstance(value, Enum), (name, key, value)


async def _record_all() -> list[tuple[str, dict[str, Any]]]:
    recorded: list[tuple[str, dict[str, Any]]] = []
    for operation in _OPERATIONS.values():
        rest = FakeProbeRest()
        for name, payload in _SUCCESS_PAYLOADS.items():
            rest.script(name, payload)
        adapter = BinanceProbeAdapter(
            FakeProbeSdk(rest), policy=test_only_signed_call_policy(), rest_gate=make_gate()
        )
        observation = await operation(adapter)
        assert observation.ok is True
        recorded.extend(rest.calls)
    return recorded


async def test_every_recorded_sdk_call_binds_to_the_installed_signature() -> None:
    recorded = await _record_all()
    assert recorded
    for name, kwargs in recorded:
        _bind(name, kwargs)


async def test_every_recorded_sdk_call_passes_enum_members_and_no_float() -> None:
    for name, kwargs in await _record_all():
        _check_argument_types(name, kwargs)


async def test_every_recorded_sdk_call_carries_the_policy_recv_window() -> None:
    for name, kwargs in await _record_all():
        assert kwargs.get("recv_window") == TEST_ONLY_RECV_WINDOW_MS, name


async def test_the_recorded_methods_are_exactly_the_declared_sdk_methods() -> None:
    recorded = {name for name, _ in await _record_all()}
    assert recorded == set(SDK_REST_METHODS)


def test_every_declared_sdk_method_exists_on_the_installed_rest_api() -> None:
    for name in SDK_REST_METHODS:
        assert callable(getattr(SdkRestApi, name, None)), name
        assert "recv_window" in inspect.signature(getattr(SdkRestApi, name)).parameters, name


def test_every_fake_method_exists_on_the_installed_rest_api() -> None:
    fake_methods = {
        name
        for name, value in vars(FakeProbeRest).items()
        if callable(value) and not name.startswith("_") and name not in {"script", "names"}
    }
    assert fake_methods >= set(SDK_REST_METHODS)
    for name in fake_methods:
        assert hasattr(SdkRestApi, name), name


def test_every_call_site_names_a_declared_sdk_method() -> None:
    """Each `self._call(...)` passes a string literal SDK name that is declared."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_call"
        ):
            sdk_name = next((kw.value for kw in node.keywords if kw.arg == "sdk_method_name"), None)
            assert isinstance(sdk_name, ast.Constant), ast.dump(node)
            names.append(sdk_name.value)
    assert names
    assert set(names) == set(SDK_REST_METHODS)


# --------------------------------------------------------------------------- #
# Negative controls: the binding check rejects a renamed or invented keyword.
# --------------------------------------------------------------------------- #


async def test_binding_rejects_a_renamed_keyword() -> None:
    recorded = await _record_all()
    name, kwargs = next(item for item in recorded if item[0] == "query_order")
    renamed = dict(kwargs)
    renamed["client_order_id"] = renamed.pop("orig_client_order_id")
    with pytest.raises(TypeError):
        _bind(name, renamed)


async def test_binding_rejects_an_invented_keyword() -> None:
    recorded = await _record_all()
    name, kwargs = recorded[0]
    with pytest.raises(TypeError):
        _bind(name, {**kwargs, "recvWindow": TEST_ONLY_RECV_WINDOW_MS})


async def test_binding_rejects_a_renamed_conditional_order_keyword() -> None:
    recorded = await _record_all()
    name, kwargs = next(item for item in recorded if item[0] == "new_algo_order")
    renamed = dict(kwargs)
    renamed["triggerPrice"] = renamed.pop("trigger_price")
    with pytest.raises(TypeError):
        _bind(name, renamed)


async def test_type_check_rejects_a_plain_string_for_an_enum_parameter() -> None:
    recorded = await _record_all()
    name, kwargs = next(item for item in recorded if item[0] == "new_order")
    with pytest.raises(AssertionError):
        _check_argument_types(name, {**kwargs, "side": "BUY"})
    with pytest.raises(AssertionError):
        _check_argument_types(name, {**kwargs, "quantity": 0.01})
