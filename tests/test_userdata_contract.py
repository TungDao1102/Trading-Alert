"""Offline contract tests pinning every SDK internal the user-data adapter relies on (plan 18-11).

`src/adapters/binance_userdata.py` and `tests/userdata_fakes.py` were written from reading the
installed `binance-sdk-derivatives-trading-usds-futures` 17.4.0 and `binance-common` 4.4.0
source (research F1, Pattern 4). An SDK upgrade that moves any of these internals fails a test
here before it can fail in production; a fake that departs from the SDK surface fails the
mirror checks (with negative controls proving the checks bite).

Only classes, functions and module attributes are introspected (`inspect.signature`,
`inspect.getsource`, `inspect.iscoroutinefunction`, pydantic `model_fields`). Nothing here
constructs an SDK client, opens a socket or performs I/O (research P18: the SDK stream maps
in `binance_common.websocket` are module-global and would leak between tests).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest
from binance_common import constants as sdk_constants
from binance_common import utils as sdk_utils
from binance_common import websocket as sdk_websocket
from binance_common.configuration import ConfigurationRestAPI, ConfigurationWebSocketStreams
from binance_common.websocket import (
    RequestStreamHandle,
    WebSocketCommon,
    WebSocketConnection,
    WebSocketStreamBase,
)
from binance_sdk_derivatives_trading_usds_futures.rest_api import (
    DerivativesTradingUsdsFuturesRestAPI as SdkRestApi,
)
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    KeepaliveUserDataStreamResponse,
    StartUserDataStreamResponse,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (
    DerivativesTradingUsdsFuturesWebSocketStreams as SdkStreamsClient,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models import (
    AccountUpdateA,
    AccountUpdateABInner,
    AccountUpdateAPInner,
    AlgoUpdateO,
    OrderTradeUpdateO,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.user_data_stream_events_response import (  # noqa: E501
    UserDataStreamEventsResponse,
)
from src.adapters.binance_userdata import CONNECTION_EVENTS, PRIVATE_URL_PATH
from src.adapters.binance_userdata_events import (
    ACCOUNT_BALANCE_WIRE_FIELDS,
    ACCOUNT_POSITION_WIRE_FIELDS,
    ACCOUNT_UPDATE_WIRE_FIELDS,
    ALGO_UPDATE_WIRE_FIELDS,
    ORDER_UPDATE_WIRE_FIELDS,
)

from tests.userdata_fakes import (
    SUPPORTED_CONNECTION_EVENTS,
    FakeRestUserDataApi,
    FakeUserDataWsClient,
    FakeUserStreamHandle,
)

_CLIENT_COROUTINES = ("create_connection", "user_data", "close_connection")
_CLIENT_SIGNATURES = ("user_data", "close_connection", "on_connection", "on")
_REST_METHODS = ("start_user_data_stream", "keepalive_user_data_stream", "close_user_data_stream")

# The event model names the parser routes on (`binance_userdata_events._TYPED_ROUTES`,
# `_IGNORED_ROUTES`, `_ANOMALY_ROUTES`, compared after normalisation).
_ROUTED_MODEL_NAMES = frozenset(
    {
        "OrderTradeUpdate",
        "AlgoUpdate",
        "AccountUpdate",
        "ListenKeyExpired",
        "AccountConfigUpdate",
        "TradeLite",
        "MarginCall",
        "StrategyUpdate",
        "GridUpdate",
        "ConditionalOrderTriggerReject",
    }
)


def _params(fn: Any) -> list[str]:
    """Parameter names without `self`."""
    return [name for name in inspect.signature(fn).parameters if name != "self"]


def _public_members(cls: type) -> set[str]:
    return {name for name in dir(cls) if not name.startswith("_")}


def _wire_names(model: Any) -> set[str]:
    """The wire keys of a pydantic SDK model: each field's alias, else its name."""
    return {field.alias or name for name, field in model.model_fields.items()}


def assert_mirrors_sdk_user_data_surface(client_cls: type, handle_cls: type) -> None:
    """Raise AssertionError naming the first member where a fake departs from the SDK."""
    for name in _CLIENT_COROUTINES:
        assert inspect.iscoroutinefunction(getattr(SdkStreamsClient, name)), f"SDK {name} not async"
        assert inspect.iscoroutinefunction(getattr(client_cls, name, None)), (
            f"fake client method {name} must be a coroutine function like the SDK"
        )
    for name in _CLIENT_SIGNATURES:
        assert _params(getattr(client_cls, name)) == _params(getattr(SdkStreamsClient, name)), (
            f"fake client method {name} parameter names differ from the SDK"
        )
    for name in ("on_connection", "on"):
        assert not inspect.iscoroutinefunction(getattr(SdkStreamsClient, name))
        assert not inspect.iscoroutinefunction(getattr(client_cls, name, None)), (
            f"fake client method {name} must be synchronous like the SDK"
        )
    assert not inspect.iscoroutinefunction(RequestStreamHandle.on)
    assert not inspect.iscoroutinefunction(getattr(handle_cls, "on", None)), (
        "fake handle method on must be synchronous like the SDK"
    )
    assert inspect.iscoroutinefunction(RequestStreamHandle.unsubscribe)
    assert inspect.iscoroutinefunction(getattr(handle_cls, "unsubscribe", None)), (
        "fake handle method unsubscribe must be a coroutine function like the SDK"
    )
    assert _params(handle_cls.on) == _params(RequestStreamHandle.on), (  # type: ignore[attr-defined]
        "fake handle method on parameter names differ from the SDK"
    )
    assert _public_members(handle_cls) == _public_members(RequestStreamHandle), (
        "fake handle public members must equal the SDK handle's public members"
    )


# --------------------------------------------------------------------------- #
# The streams client: user_data, SUBSCRIBE and the handle.
# --------------------------------------------------------------------------- #


def test_user_data_is_a_coroutine_taking_only_listen_key_on_the_private_url() -> None:
    assert inspect.iscoroutinefunction(SdkStreamsClient.user_data)
    assert _params(SdkStreamsClient.user_data) == ["listenKey"]
    source = inspect.getsource(SdkStreamsClient.user_data)
    assert f'stream_url="{PRIVATE_URL_PATH}"' in source
    assert "response_model=UserDataStreamEventsResponse" in source
    # The client opens market, public and private connections (research F1 item 5).
    init_source = inspect.getsource(SdkStreamsClient.__init__)
    assert 'url_paths=["market", "public", "private"]' in init_source


def test_subscribe_sends_the_bare_name_as_params_and_skips_mapped_names() -> None:
    source = inspect.getsource(WebSocketStreamBase.subscribe)
    assert '"method": "SUBSCRIBE"' in source
    assert '"params": connection_streams' in source
    # Names already in the module-global map are filtered out: the pinned reason the adapter
    # forgets its own listenKey name before re-subscribing (research P6).
    assert "if stream not in global_stream_connections.stream_connections_map" in source
    # RequestStream subscribes the stream (the bare listenKey) as a one-element list.
    request_stream_source = inspect.getsource(sdk_websocket.RequestStream)
    assert "streams=[stream]" in request_stream_source
    assert "stream_url=stream_url" in request_stream_source


def test_request_stream_handle_exposes_only_on_and_unsubscribe() -> None:
    assert _public_members(RequestStreamHandle) == {"on", "unsubscribe"}
    assert not inspect.iscoroutinefunction(RequestStreamHandle.on)
    assert inspect.iscoroutinefunction(RequestStreamHandle.unsubscribe)
    assert _params(RequestStreamHandle.on) == ["event", "callback"]
    assert '{"message"}' in inspect.getsource(RequestStreamHandle.on)


def test_fakes_mirror_the_installed_sdk_surface() -> None:
    assert_mirrors_sdk_user_data_surface(FakeUserDataWsClient, FakeUserStreamHandle)


def test_negative_control_synchronous_fake_user_data_is_rejected() -> None:
    """The mirror helper must reject a fake whose `user_data` is synchronous."""

    class _SyncUserData(FakeUserDataWsClient):
        def user_data(self, listenKey: str) -> FakeUserStreamHandle:  # type: ignore[override]  # noqa: N803
            return FakeUserStreamHandle(self, listenKey)

    with pytest.raises(AssertionError, match="user_data"):
        assert_mirrors_sdk_user_data_surface(_SyncUserData, FakeUserStreamHandle)


def test_negative_control_handle_with_a_fictional_method_is_rejected() -> None:
    """A handle exposing more than `on` and `unsubscribe` (the old fictional API) is rejected."""

    class _FictionalHandle(FakeUserStreamHandle):
        def reconnect(self) -> None:  # not on the real handle
            return None

    with pytest.raises(AssertionError, match="public members"):
        assert_mirrors_sdk_user_data_surface(FakeUserDataWsClient, _FictionalHandle)


# --------------------------------------------------------------------------- #
# The callback envelope and the parser's wire fields.
# --------------------------------------------------------------------------- #


def test_user_data_response_one_of_schemas_cover_every_routed_model() -> None:
    one_of = UserDataStreamEventsResponse.model_fields["one_of_schemas"].default
    assert _ROUTED_MODEL_NAMES <= set(one_of)
    assert "actual_instance" in UserDataStreamEventsResponse.model_fields


@pytest.mark.parametrize(
    ("constant_name", "wire_fields", "model"),
    [
        ("ORDER_UPDATE_WIRE_FIELDS", ORDER_UPDATE_WIRE_FIELDS, OrderTradeUpdateO),
        ("ALGO_UPDATE_WIRE_FIELDS", ALGO_UPDATE_WIRE_FIELDS, AlgoUpdateO),
        ("ACCOUNT_UPDATE_WIRE_FIELDS", ACCOUNT_UPDATE_WIRE_FIELDS, AccountUpdateA),
        ("ACCOUNT_BALANCE_WIRE_FIELDS", ACCOUNT_BALANCE_WIRE_FIELDS, AccountUpdateABInner),
        ("ACCOUNT_POSITION_WIRE_FIELDS", ACCOUNT_POSITION_WIRE_FIELDS, AccountUpdateAPInner),
    ],
)
def test_parser_wire_fields_are_aliases_of_the_sdk_models(
    constant_name: str, wire_fields: frozenset[str], model: Any
) -> None:
    missing = sorted(wire_fields - _wire_names(model))
    assert missing == [], f"{constant_name} keys not on {model.__name__}: {missing}"


def test_parse_user_event_is_a_module_global_used_by_the_receive_loop() -> None:
    # The raw-frame tap wraps the name in the websocket module namespace: it must be the
    # utils function imported there and called by name from the receive path.
    assert getattr(sdk_websocket, "parse_user_event") is sdk_utils.parse_user_event  # noqa: B009
    receive_source = inspect.getsource(WebSocketCommon.receive_loop)
    assert "parse_user_event(" in receive_source
    assert "utils.parse_user_event" not in receive_source
    assert _params(sdk_utils.parse_user_event) == ["payload", "response_model_cls"]
    # The raw-dict fallback the adapter's single parser path handles (research P4).
    assert "model_construct(actual_instance=payload)" in inspect.getsource(
        sdk_utils._wrap_raw_payload
    )


def test_stream_maps_and_rotation_constant_in_the_websocket_namespace() -> None:
    assert isinstance(sdk_websocket.global_stream_connections.stream_connections_map, dict)
    assert isinstance(sdk_websocket.global_user_stream_connections.stream_connections_map, dict)
    # Read through the websocket module namespace, where `schedule_reconnect` uses it.
    assert sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS == 23 * 3600
    assert sdk_constants.AUTO_RECONNECT_INTERVAL_SECONDS == 23 * 3600


def test_unsolicited_close_keeps_names_and_user_close_forgets_them() -> None:
    """The asymmetry the adapter's rebuild relies on (research P6)."""
    discard_source = inspect.getsource(WebSocketCommon._discard_connection)
    assert "_forget_connection_streams" not in discard_source
    close_one_source = inspect.getsource(WebSocketCommon._close_one)
    assert "_forget_connection_streams(connection)" in close_one_source


# --------------------------------------------------------------------------- #
# Connections and connection events.
# --------------------------------------------------------------------------- #


def test_websocket_connection_carries_url_path_and_is_open() -> None:
    assert "url_path" in _params(WebSocketConnection.__init__)
    source = inspect.getsource(WebSocketConnection.__init__)
    assert "self.url_path = url_path" in source
    # `SdkUserDataTransport.private_connection_open` reads this flag.
    assert "self.is_open = True" in source


def test_on_connection_signature_and_supported_events() -> None:
    assert _params(WebSocketCommon.on_connection) == ["event", "callback", "connection"]
    assert _params(SdkStreamsClient.on_connection) == ["event", "callback", "connection"]
    supported = set(sdk_constants.SUPPORTED_CONNECTION_EVENTS)
    assert supported == {"open", "reconnect", "close", "error", "ping", "pong"}
    assert set(CONNECTION_EVENTS) == supported
    assert set(SUPPORTED_CONNECTION_EVENTS) == supported
    # The SDK trims the callback arguments to the callback's signature, so a callback that
    # takes no argument receives no payload (the adapter keeps no ping, pong or error payload).
    assert "VAR_POSITIONAL" in inspect.getsource(WebSocketCommon._invoke_connection_callback)


# --------------------------------------------------------------------------- #
# Configuration and the REST listenKey methods.
# --------------------------------------------------------------------------- #


def test_configuration_classes_accept_the_keywords_the_caller_sets() -> None:
    rest_params = set(_params(ConfigurationRestAPI.__init__))
    assert {"base_path", "timeout", "retries", "backoff"} <= rest_params
    stream_params = set(_params(ConfigurationWebSocketStreams.__init__))
    assert {"stream_url", "reconnect_delay", "reconnect_attempts"} <= stream_params


@pytest.mark.parametrize("name", _REST_METHODS)
def test_rest_listen_key_methods_are_synchronous_without_parameters(name: str) -> None:
    method = getattr(SdkRestApi, name)
    assert callable(method)
    assert not inspect.iscoroutinefunction(method)
    assert _params(method) == []
    fake = getattr(FakeRestUserDataApi, name)
    assert not inspect.iscoroutinefunction(fake)
    assert _params(fake) == []


@pytest.mark.parametrize("model", [StartUserDataStreamResponse, KeepaliveUserDataStreamResponse])
def test_rest_listen_key_responses_expose_listen_key_alias(model: Any) -> None:
    assert model.model_fields["listen_key"].alias == "listenKey"


# --------------------------------------------------------------------------- #
# This file stays offline.
# --------------------------------------------------------------------------- #


def test_this_file_constructs_no_sdk_client_and_opens_no_socket() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    forbidden = {
        "SdkStreamsClient",
        "SdkRestApi",
        "DerivativesTradingUsdsFutures",
        "create_connection",
        "connect",
        "ClientSession",
        "ws_connect",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            assert name not in forbidden, f"{name} is called in the contract test"
