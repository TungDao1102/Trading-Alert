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
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures.rest_api import (
    DerivativesTradingUsdsFuturesRestAPI as SdkRestApi,
)
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
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
}

_OPERATIONS: dict[str, _Op] = {
    "query_order": lambda a: a.query_order(symbol="BTCUSDT", client_order_id="c1"),
    "query_algo_order": lambda a: a.query_algo_order(client_algo_id="a1"),
}


def _bind(name: str, kwargs: dict[str, Any]) -> None:
    """Bind `kwargs` to the installed SDK method `name` (raises TypeError on a wrong keyword)."""
    signature = inspect.signature(getattr(SdkRestApi, name))
    signature.bind(None, **kwargs)


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
