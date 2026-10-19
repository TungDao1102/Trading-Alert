"""The SDK-backed user-data stream adapter (Phase 18, plan 18-11, D-01, D-02, EXEC-05, OPS-02).

Every SDK object here is either an SDK-shaped fake from `tests/userdata_fakes.py` (bound to the
installed SDK by `tests/test_userdata_contract.py`) or a real SDK pydantic model built from a
SYNTHETIC frame. No network is touched, no real SDK client is constructed, and the SDK's
module-global stream map is isolated per test (research P6, P18). The facts the fakes mirror
come from reading the installed SDK source; the SDK's live behaviour is established by plan
18-18, not here.
"""

from __future__ import annotations

import ast
import dataclasses
import io
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_common import websocket as sdk_websocket
from binance_common.configuration import ConfigurationWebSocketStreams
from binance_common.errors import (
    BadRequestError,
    NetworkError,
    RateLimitBanError,
    ServerError,
    TooManyRequestsError,
    UnauthorizedError,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.user_data_stream_events_response import (  # noqa: E501
    UserDataStreamEventsResponse,
)
from src.adapters import binance_userdata as bud
from src.adapters.binance_ratelimit_gate import (
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    RateLimitBanActive,
    RateLimitPauseActive,
    RestRateLimitGate,
)
from src.adapters.binance_userdata import (
    ConnectionEvent,
    ListenKeyFailure,
    ListenKeyInvalid,
    ListenKeyTransient,
    QueuedStreamItem,
    SdkListenKeyPort,
    SdkNoiseGuard,
    SdkUserDataTransport,
    UserDataAdapter,
    capture_raw_user_events,
    install_sdk_log_bridge,
    install_sdk_noise_guard,
)
from src.adapters.binance_userdata_events import (
    OrderUpdateEvent,
    StreamAnomaly,
    StreamAnomalyKind,
    to_fill_event,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from src.execution.fill_monitor import FillEvent
from src.ops import redaction
from src.ops.redaction import RedactingFilter, configure_logging, scrub
from structlog.testing import capture_logs

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS,
    TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS,
    test_only_rate_limit_policy,
    test_only_stream_limits,
)
from tests.support.userdata_frames import order_trade_update_frame
from tests.userdata_fakes import (
    TEST_ONLY_LISTEN_KEY,
    TEST_ONLY_SECOND_LISTEN_KEY,
    FakeRestUserDataApi,
    FakeUserDataWsClient,
    fresh_sdk_stream_map,
    make_order_trade_update_message,
    make_raw_dict_message,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "src" / "adapters" / "binance_userdata.py"

TEST_ONLY_NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
TEST_ONLY_STREAM_URL = "wss://example.invalid"
TEST_ONLY_RETRY_AFTER_SECONDS = 7
TEST_ONLY_SMALL_QUEUE_MAX = 2
TEST_ONLY_SDK_PATHNAME = "C:/x/site-packages/binance_common/websocket.py"
TEST_ONLY_FOREIGN_PATHNAME = "C:/x/site-packages/other/lib.py"
# The SDK error message text planted in every SDK error; it must never reach a project exception.
TEST_ONLY_SDK_MESSAGE = "sdk-detail-text-that-must-not-leak"


def _clock() -> datetime:
    return TEST_ONLY_NOW


def _rest_gate() -> RestRateLimitGate:
    """A fresh process-wide REST gate (plan 18-10) with the TEST_ONLY policy (plan 18-14)."""
    return RestRateLimitGate(policy=test_only_rate_limit_policy(), clock=_clock)


@pytest.fixture(autouse=True)
def sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the SDK module-global stream map per test (research P6, P18)."""
    return fresh_sdk_stream_map(monkeypatch)


@pytest.fixture(autouse=True)
def _isolated_redactor() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


class _StubListenKeys:
    """A minimal ListenKeyPort for the Task 1 slice (the SDK port is tested further down)."""

    def __init__(self, key: str = TEST_ONLY_LISTEN_KEY) -> None:
        self.key = key
        self.starts = 0
        self.keepalives = 0
        self.closes = 0

    async def start(self) -> str:
        self.starts += 1
        return self.key

    async def keepalive(self) -> None:
        self.keepalives += 1

    async def close(self) -> None:
        self.closes += 1


def _configuration() -> ConfigurationWebSocketStreams:
    return ConfigurationWebSocketStreams(stream_url=TEST_ONLY_STREAM_URL)


class _Factory:
    """Client factory that records the fresh fake clients it builds."""

    def __init__(self) -> None:
        self.built: list[FakeUserDataWsClient] = []

    def __call__(self, configuration: ConfigurationWebSocketStreams) -> FakeUserDataWsClient:
        client = FakeUserDataWsClient()
        self.built.append(client)
        return client


def _rig(
    *,
    ws: FakeUserDataWsClient | None = None,
    port: Any = None,
    queue_max: int | None = None,
) -> tuple[UserDataAdapter, SdkUserDataTransport, FakeUserDataWsClient, _Factory, Any]:
    ws = ws if ws is not None else FakeUserDataWsClient()
    factory = _Factory()
    transport = SdkUserDataTransport(_configuration(), client_factory=factory, ws_client=ws)
    limits = test_only_stream_limits()
    if queue_max is not None:
        limits = dataclasses.replace(limits, event_queue_max=queue_max)
    port = port if port is not None else _StubListenKeys()
    adapter = UserDataAdapter(transport=transport, listen_keys=port, limits=limits, clock=_clock)
    return adapter, transport, ws, factory, port


def _sdk_free(value: object, path: str = "item") -> None:
    """Fail when any attribute reachable from `value` has an SDK type."""
    module = type(value).__module__
    assert not module.startswith("binance_"), f"{path} has SDK type {type(value).__name__}"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            _sdk_free(getattr(value, item.name), f"{path}.{item.name}")
    elif isinstance(value, tuple | list):
        for index, element in enumerate(value):
            _sdk_free(element, f"{path}[{index}]")


# --------------------------------------------------------------------------- #
# Task 1: tracer.
# --------------------------------------------------------------------------- #


async def test_tracer_sdk_order_trade_update_becomes_queued_event_and_fill() -> None:
    adapter, _transport, ws, _factory, port = _rig()

    await adapter.start()

    assert port.starts == 1
    assert adapter.epoch == 1
    # The bare listenKey goes on the wire as the SUBSCRIBE params, on the private connection.
    assert [frame["params"] for frame in ws.subscribe_frames] == [[TEST_ONLY_LISTEN_KEY]]
    private = ws.connection_for("private")
    assert private is not None
    assert len(private.stream_callback_map[TEST_ONLY_LISTEN_KEY]) == 1

    delivered = ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_order_trade_update_message())

    assert delivered == 1
    assert adapter.queue.qsize() == 1
    item = adapter.queue.get_nowait()
    assert isinstance(item, QueuedStreamItem)
    assert item.received_at_utc == TEST_ONLY_NOW
    assert item.connection_epoch == 1
    assert isinstance(item.outcome, OrderUpdateEvent)
    fill = to_fill_event(item.outcome)
    assert isinstance(fill, FillEvent)
    assert (fill.order_id, fill.exchange_trade_id) == ("8000000001", "900000001")
    assert fill.symbol == "BTCUSDT"
    assert fill.side == "BUY"
    assert fill.position_side == "BOTH"
    assert fill.fill_quantity == Decimal("0.004")
    assert fill.fill_price == Decimal("60000.00")
    assert fill.commission == Decimal("0.09600000")
    assert fill.commission_asset == "USDT"
    _sdk_free(item)
    _sdk_free(fill)


async def test_raw_dict_fallback_takes_the_same_path_and_gives_the_same_event() -> None:
    adapter, _transport, ws, _factory, _port = _rig()
    await adapter.start()

    ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_order_trade_update_message())
    ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_raw_dict_message(order_trade_update_frame()))

    from_model = adapter.queue.get_nowait()
    from_dict = adapter.queue.get_nowait()
    assert isinstance(from_dict.outcome, OrderUpdateEvent)
    assert from_dict.outcome == from_model.outcome
    _sdk_free(from_dict)


async def test_unrecognized_message_becomes_an_anomaly_item_and_never_raises() -> None:
    adapter, _transport, ws, _factory, _port = _rig()
    await adapter.start()

    ws.emit_user_event(TEST_ONLY_LISTEN_KEY, object())

    item = adapter.queue.get_nowait()
    assert isinstance(item.outcome, StreamAnomaly)
    assert item.outcome.kind is StreamAnomalyKind.UNRECOGNIZED_ENVELOPE
    assert item.connection_epoch == 1
    _sdk_free(item)


async def test_parser_exception_becomes_a_malformed_payload_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _transport, ws, _factory, _port = _rig()
    await adapter.start()

    def broken_parser(message: object, *, observed_at_utc: datetime) -> Any:
        raise RuntimeError("parser bug")

    monkeypatch.setattr(bud, "parse_stream_message", broken_parser)
    ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_order_trade_update_message())

    item = adapter.queue.get_nowait()
    assert isinstance(item.outcome, StreamAnomaly)
    assert item.outcome.kind is StreamAnomalyKind.MALFORMED_PAYLOAD
    assert "parser bug" not in item.outcome.detail
    assert item.outcome.observed_at_utc == TEST_ONLY_NOW


async def test_connect_raises_connection_error_when_the_sdk_produced_no_connection() -> None:
    ws = FakeUserDataWsClient(produce_connection=False)
    adapter, _transport, _ws, _factory, _port = _rig(ws=ws)

    with pytest.raises(ConnectionError) as excinfo:
        await adapter.start()

    assert "wss" not in str(excinfo.value)
    assert TEST_ONLY_LISTEN_KEY not in str(excinfo.value)
    assert adapter.epoch == 0
    assert ws.subscribe_frames == []


async def test_connect_raises_connection_error_when_no_private_connection_exists() -> None:
    class _NoPrivate(FakeUserDataWsClient):
        URL_PATHS = ("market", "public")

    ws = _NoPrivate()
    adapter, _transport, _ws, _factory, _port = _rig(ws=ws)

    with pytest.raises(ConnectionError):
        await adapter.start()
    assert ws.subscribe_frames == []
    assert adapter.epoch == 0


# --------------------------------------------------------------------------- #
# Task 2: shared helpers.
# --------------------------------------------------------------------------- #

_C = ExchangeErrorCategory
_ALL_CONNECTION_EVENTS = ("open", "reconnect", "close", "error", "ping", "pong")
_PORT_METHODS = {
    "start_user_data_stream": "start",
    "keepalive_user_data_stream": "keepalive",
    "close_user_data_stream": "close",
}


def _path_url(key: str) -> str:
    """The documented path form `/private/ws/<listenKey>` (WebFetch summary, not verified live)."""
    return f"wss://example.invalid/private/ws/{key}"


def _record(level: int, message: str, pathname: str = TEST_ONLY_SDK_PATHNAME) -> logging.LogRecord:
    return logging.LogRecord(
        name="root",
        level=level,
        pathname=pathname,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


class _CapturedRootLogs:
    """A root handler carrying `RedactingFilter` that writes into memory (stdlib output)."""

    def __init__(self) -> None:
        self.stream = io.StringIO()
        self._handler = logging.StreamHandler(self.stream)
        self._handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self._handler.addFilter(RedactingFilter())
        self._old_level = logging.NOTSET

    def __enter__(self) -> io.StringIO:
        root = logging.getLogger()
        self._old_level = root.level
        root.addHandler(self._handler)
        root.setLevel(logging.DEBUG)
        return self.stream

    def __exit__(self, *exc: object) -> None:
        root = logging.getLogger()
        root.removeHandler(self._handler)
        root.setLevel(self._old_level)


def _assert_no_key(key: str, *outputs: str) -> None:
    for output in outputs:
        if key in output:
            pytest.fail(f"a listenKey of length {len(key)} leaked into {len(output)} chars")


class _KeySequence:
    """A ListenKeyPort stub returning keys in order WITHOUT registering them (never the port)."""

    def __init__(self, *keys: str) -> None:
        self._keys = list(keys)
        self.closes = 0

    async def start(self) -> str:
        return self._keys.pop(0)

    async def keepalive(self) -> None:
        return None

    async def close(self) -> None:
        self.closes += 1


# --------------------------------------------------------------------------- #
# Task 2: the listenKey REST port.
# --------------------------------------------------------------------------- #


async def test_listen_key_port_start_returns_the_key_and_registers_it() -> None:
    port = SdkListenKeyPort(FakeRestUserDataApi(), rest_gate=_rest_gate())

    key = await port.start()

    assert key == TEST_ONLY_LISTEN_KEY
    assert type(key) is str
    _assert_no_key(key, scrub(f"subscribed {key}"), repr(port))


async def test_listen_key_port_runs_the_sdk_call_in_a_worker_thread() -> None:
    import threading

    seen: list[int] = []

    class _ThreadRecordingApi(FakeRestUserDataApi):
        def start_user_data_stream(self) -> Any:
            seen.append(threading.get_ident())
            return super().start_user_data_stream()

    await SdkListenKeyPort(_ThreadRecordingApi(), rest_gate=_rest_gate()).start()

    assert seen and seen[0] != threading.get_ident()


async def test_listen_key_port_start_without_a_key_raises_failure() -> None:
    rest = FakeRestUserDataApi(start_returns_no_key=True)

    with pytest.raises(ListenKeyFailure) as excinfo:
        await SdkListenKeyPort(rest, rest_gate=_rest_gate()).start()

    assert excinfo.value.category is _C.UNKNOWN_EXCHANGE_ERROR
    assert excinfo.value.retry_after_seconds is None
    assert rest.calls["start_user_data_stream"] == 1


async def test_keepalive_registers_a_key_carried_by_its_response() -> None:
    port = SdkListenKeyPort(
        FakeRestUserDataApi(keepalive_listen_key=TEST_ONLY_SECOND_LISTEN_KEY),
        rest_gate=_rest_gate(),
    )

    await port.keepalive()

    _assert_no_key(TEST_ONLY_SECOND_LISTEN_KEY, scrub(f"kept {TEST_ONLY_SECOND_LISTEN_KEY}"))
    # A response without a key is accepted and registers nothing.
    await SdkListenKeyPort(FakeRestUserDataApi(), rest_gate=_rest_gate()).keepalive()


_TRANSLATION_MATRIX: list[tuple[str, Any, type[Exception], ExchangeErrorCategory, int | None]] = [
    (
        "invalid_listen_key_400",
        lambda: BadRequestError(TEST_ONLY_SDK_MESSAGE, -1125),
        ListenKeyInvalid,
        _C.INVALID_LISTEN_KEY,
        None,
    ),
    (
        "rate_limited_429",
        lambda: TooManyRequestsError(TEST_ONLY_SDK_MESSAGE, -1003, TEST_ONLY_RETRY_AFTER_SECONDS),
        ListenKeyTransient,
        _C.RATE_LIMITED,
        TEST_ONLY_RETRY_AFTER_SECONDS,
    ),
    (
        "rate_limited_429_no_retry_after",
        lambda: TooManyRequestsError(TEST_ONLY_SDK_MESSAGE, -1003, None),
        ListenKeyTransient,
        _C.RATE_LIMITED,
        None,
    ),
    (
        "server_5xx",
        lambda: ServerError(TEST_ONLY_SDK_MESSAGE, 503),
        ListenKeyTransient,
        _C.STATUS_UNKNOWN,
        None,
    ),
    (
        "network",
        lambda: NetworkError(TEST_ONLY_SDK_MESSAGE),
        ListenKeyTransient,
        _C.STATUS_UNKNOWN,
        None,
    ),
    (
        "ip_banned_418",
        lambda: RateLimitBanError(TEST_ONLY_SDK_MESSAGE, -1003, None),
        ListenKeyFailure,
        _C.IP_BANNED,
        None,
    ),
    (
        "ip_banned_418_retry_after",
        lambda: RateLimitBanError(TEST_ONLY_SDK_MESSAGE, None, TEST_ONLY_RETRY_AFTER_SECONDS),
        ListenKeyFailure,
        _C.IP_BANNED,
        TEST_ONLY_RETRY_AFTER_SECONDS,
    ),
    (
        "auth_401",
        lambda: UnauthorizedError(TEST_ONLY_SDK_MESSAGE, -2015),
        ListenKeyFailure,
        _C.AUTH_OR_SIGNATURE,
        None,
    ),
    (
        "unknown_code_400",
        lambda: BadRequestError(TEST_ONLY_SDK_MESSAGE, -9999),
        ListenKeyFailure,
        _C.UNKNOWN_EXCHANGE_ERROR,
        None,
    ),
    (
        "non_sdk_exception",
        lambda: RuntimeError(TEST_ONLY_SDK_MESSAGE),
        ListenKeyFailure,
        _C.UNKNOWN_EXCHANGE_ERROR,
        None,
    ),
]


@pytest.mark.parametrize("method", sorted(_PORT_METHODS))
@pytest.mark.parametrize(
    ("label", "make_error", "expected", "category", "retry_after"),
    _TRANSLATION_MATRIX,
    ids=[row[0] for row in _TRANSLATION_MATRIX],
)
async def test_listen_key_translation_matrix(
    method: str,
    label: str,
    make_error: Any,
    expected: type[Exception],
    category: ExchangeErrorCategory,
    retry_after: int | None,
) -> None:
    rest = FakeRestUserDataApi()
    rest.fail_next(method, make_error())
    port = SdkListenKeyPort(rest, rest_gate=_rest_gate())

    with pytest.raises(expected) as excinfo:
        await getattr(port, _PORT_METHODS[method])()

    exc = excinfo.value
    assert type(exc) is expected
    assert isinstance(exc, Exception)
    assert exc.category is category  # type: ignore[attr-defined]
    assert exc.retry_after_seconds == retry_after  # type: ignore[attr-defined]
    text = f"{exc} {exc!r} {exc.args!r}"
    assert TEST_ONLY_SDK_MESSAGE not in text
    assert "://" not in text
    _assert_no_key(TEST_ONLY_LISTEN_KEY, text)
    # The SDK exception (and its message) is neither the cause nor the context.
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert rest.calls[method] == 1


def _class_def(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


async def test_listen_key_port_single_call_site_and_no_retry() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    port_class = _class_def(tree, "SdkListenKeyPort")
    to_thread_sites: list[str] = []
    sdk_method_sites: list[str] = []
    for method in port_class.body:
        if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(method):
            assert not isinstance(node, ast.For | ast.While | ast.AsyncFor), (
                f"{method.name} loops: the port never retries"
            )
            if isinstance(node, ast.Call):
                name = _call_name(node)
                assert name != "sleep", f"{method.name} sleeps: the port never waits"
                if name == "to_thread":
                    to_thread_sites.append(method.name)
                if name == "_rest_call":
                    sdk_method_sites.append(method.name)
    assert to_thread_sites == ["_rest_call"]
    assert sorted(sdk_method_sites) == ["close", "keepalive", "start"]

    # Behaviour: a 429 or a 418 on each call makes exactly one SDK call and is reported.
    for method, public in _PORT_METHODS.items():
        for error, expected in (
            (TooManyRequestsError(TEST_ONLY_SDK_MESSAGE, -1003, None), ListenKeyTransient),
            (RateLimitBanError(TEST_ONLY_SDK_MESSAGE, -1003, None), ListenKeyFailure),
        ):
            rest = FakeRestUserDataApi()
            rest.fail_next(method, error)
            with pytest.raises(expected):
                await getattr(SdkListenKeyPort(rest, rest_gate=_rest_gate()), public)()
            assert rest.calls[method] == 1
            assert sum(rest.calls.values()) == 1


async def test_listen_key_port_records_and_respects_shared_gate() -> None:
    # The gate is a required keyword: no port exists without the process-wide gate.
    with pytest.raises(TypeError):
        SdkListenKeyPort(FakeRestUserDataApi())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        SdkListenKeyPort(FakeRestUserDataApi(), rest_gate=object())  # type: ignore[arg-type]

    for method, public in _PORT_METHODS.items():
        # A pause or a ban set by another holder refuses before sending; the refusal is the
        # gate's own exception, unchanged, and the SDK fake's counter does not move.
        for category, refusal in (
            (_C.RATE_LIMITED, RateLimitPauseActive),
            (_C.IP_BANNED, RateLimitBanActive),
        ):
            gate = _rest_gate()
            gate.record(category, None)
            rest = FakeRestUserDataApi()
            with pytest.raises(refusal) as refused:
                await getattr(SdkListenKeyPort(rest, rest_gate=gate), public)()
            assert type(refused.value) is refusal
            assert sum(rest.calls.values()) == 0

        # A 429 on the call pauses every REST call of the process (here: the next call of
        # the same port is refused without sending); nothing is retried.
        gate = _rest_gate()
        rest = FakeRestUserDataApi()
        rest.fail_next(method, TooManyRequestsError(TEST_ONLY_SDK_MESSAGE, -1003, None))
        port = SdkListenKeyPort(rest, rest_gate=gate)
        with pytest.raises(ListenKeyTransient):
            await getattr(port, public)()
        restriction = gate.restriction()
        assert restriction is not None
        assert restriction.reason == RATE_LIMIT_PAUSE_429
        assert restriction.remaining_seconds == TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS
        with pytest.raises(RateLimitPauseActive):
            await getattr(port, public)()
        assert rest.calls[method] == 1
        assert sum(rest.calls.values()) == 1

        # A 429 with a Retry-After pauses for that many seconds.
        gate = _rest_gate()
        rest = FakeRestUserDataApi()
        rest.fail_next(
            method,
            TooManyRequestsError(TEST_ONLY_SDK_MESSAGE, -1003, TEST_ONLY_RETRY_AFTER_SECONDS),
        )
        with pytest.raises(ListenKeyTransient):
            await getattr(SdkListenKeyPort(rest, rest_gate=gate), public)()
        assert gate.remaining_seconds() == TEST_ONLY_RETRY_AFTER_SECONDS

        # A 418 bans REST for the 418 fallback.
        gate = _rest_gate()
        rest = FakeRestUserDataApi()
        rest.fail_next(method, RateLimitBanError(TEST_ONLY_SDK_MESSAGE, -1003, None))
        port = SdkListenKeyPort(rest, rest_gate=gate)
        with pytest.raises(ListenKeyFailure):
            await getattr(port, public)()
        restriction = gate.restriction()
        assert restriction is not None
        assert restriction.reason == IP_BAN_418
        assert restriction.remaining_seconds == TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS
        with pytest.raises(RateLimitBanActive):
            await getattr(port, public)()
        assert sum(rest.calls.values()) == 1

        # Every other failure leaves the gate open.
        for error in (
            ServerError(TEST_ONLY_SDK_MESSAGE, 503),
            BadRequestError(TEST_ONLY_SDK_MESSAGE, -1125),
            UnauthorizedError(TEST_ONLY_SDK_MESSAGE, -2015),
        ):
            gate = _rest_gate()
            rest = FakeRestUserDataApi()
            rest.fail_next(method, error)
            with pytest.raises(bud.ListenKeyError):
                await getattr(SdkListenKeyPort(rest, rest_gate=gate), public)()
            assert gate.restriction() is None


# --------------------------------------------------------------------------- #
# Task 2: connection fan-in with an epoch.
# --------------------------------------------------------------------------- #


async def test_connection_callbacks_are_registered_on_the_private_connection_only() -> None:
    adapter, _transport, ws, _factory, _port = _rig()
    events: list[ConnectionEvent] = []
    adapter.set_connection_listener(events.append)

    await adapter.start()

    assert ws.registered_events("private") == dict.fromkeys(_ALL_CONNECTION_EVENTS, 1)
    assert ws.registered_events("market") == {}
    assert ws.registered_events("public") == {}

    # SDK argument shapes: ping and pong pass the payload, error passes the error.
    ws.emit_connection_event("private", "ping", b"ping-payload")
    ws.emit_connection_event("private", "pong", b"pong-payload")
    ws.emit_connection_event("private", "error", RuntimeError(TEST_ONLY_SDK_MESSAGE))
    ws.emit_connection_event("private", "reconnect")
    ws.emit_connection_event("private", "open")
    ws.emit_connection_event("market", "close")  # not observed: not the private connection

    assert [event.name for event in events] == ["ping", "pong", "error", "reconnect", "open"]
    assert all(event.at_utc == TEST_ONLY_NOW and event.epoch == 1 for event in events)
    assert TEST_ONLY_SDK_MESSAGE not in repr(events)
    _sdk_free(events)


async def test_connection_listener_failure_never_reaches_the_sdk() -> None:
    adapter, _transport, ws, _factory, _port = _rig()

    def broken(event: ConnectionEvent) -> None:
        raise RuntimeError("listener bug")

    adapter.set_connection_listener(broken)
    await adapter.start()

    ws.emit_connection_event("private", "close")  # must not raise


async def test_connect_twice_does_not_duplicate_callbacks() -> None:
    _adapter, transport, ws, _factory, _port = _rig()

    await transport.connect(TEST_ONLY_LISTEN_KEY)
    await transport.connect(TEST_ONLY_LISTEN_KEY)

    for count in ws.registered_events("private").values():
        assert count == 1


# --------------------------------------------------------------------------- #
# Task 2: rebuild with stale-name forgetting.
# --------------------------------------------------------------------------- #


async def test_rebuild_forgets_only_its_own_name_and_resubscribes_on_a_fresh_client(
    sdk_stream_map: Any,
) -> None:
    adapter, transport, ws, factory, _port = _rig()
    events: list[ConnectionEvent] = []
    adapter.set_connection_listener(events.append)
    await adapter.start()
    foreign = object()
    stream_map = sdk_stream_map.stream_connections_map
    stream_map["btcusdt@kline_1h"] = foreign

    ws.simulate_unsolicited_close()

    assert TEST_ONLY_LISTEN_KEY in stream_map  # the SDK keeps the dead name (research P6)
    assert adapter.private_connection_open() is False
    assert [event.name for event in events] == ["close"]

    await adapter.rebuild()

    assert ws.close_calls == 1
    assert len(factory.built) == 1
    fresh = factory.built[0]
    assert [frame["params"] for frame in fresh.subscribe_frames] == [[TEST_ONLY_LISTEN_KEY]]
    assert stream_map[TEST_ONLY_LISTEN_KEY] is fresh.connection_for("private")
    assert stream_map["btcusdt@kline_1h"] is foreign
    assert adapter.epoch == 2
    assert adapter.private_connection_open() is True
    assert fresh.registered_events("private") == dict.fromkeys(_ALL_CONNECTION_EVENTS, 1)
    diagnostics = transport.diagnostics()
    assert diagnostics.stale_listen_key_names_found == 1
    assert diagnostics.rebuild_count == 1
    assert diagnostics.private_connection_open is True
    _assert_no_key(TEST_ONLY_LISTEN_KEY, repr(diagnostics), repr(transport), repr(adapter))

    fresh.emit_user_event(TEST_ONLY_LISTEN_KEY, make_order_trade_update_message())
    assert adapter.queue.get_nowait().connection_epoch == 2


async def test_rebuild_after_a_user_close_finds_no_stale_name() -> None:
    _adapter, transport, ws, factory, _port = _rig()
    await transport.connect(TEST_ONLY_LISTEN_KEY)
    await ws.close_connection()

    await transport.rebuild(TEST_ONLY_LISTEN_KEY)

    assert transport.diagnostics().stale_listen_key_names_found == 0
    assert [frame["params"] for frame in factory.built[0].subscribe_frames] == [
        [TEST_ONLY_LISTEN_KEY]
    ]


async def test_rebuild_logs_an_old_close_failure_by_type_name_only() -> None:
    adapter, _transport, ws, factory, _port = _rig()
    await adapter.start()
    ws.simulate_unsolicited_close()
    ws.close_should_raise = RuntimeError(TEST_ONLY_SDK_MESSAGE)

    with capture_logs() as logs:
        await adapter.rebuild()

    failures = [entry for entry in logs if entry["event"] == "userdata.rebuild_old_close_failed"]
    assert len(failures) == 1
    assert failures[0]["error_type"] == "RuntimeError"
    assert TEST_ONLY_SDK_MESSAGE not in repr(logs)
    _assert_no_key(TEST_ONLY_LISTEN_KEY, repr(logs))
    assert len(factory.built) == 1
    assert adapter.epoch == 2


async def test_rebuild_before_start_is_refused() -> None:
    adapter, _transport, _ws, _factory, _port = _rig()

    with pytest.raises(RuntimeError):
        await adapter.rebuild()


# --------------------------------------------------------------------------- #
# Task 2: adapter primitives (keepalive, rekey, stop).
# --------------------------------------------------------------------------- #


async def test_keepalive_delegates_and_propagates_listen_key_errors_unchanged() -> None:
    rest = FakeRestUserDataApi()
    now = [TEST_ONLY_NOW]
    gate = RestRateLimitGate(policy=test_only_rate_limit_policy(), clock=lambda: now[0])
    adapter, _transport, _ws, _factory, _port = _rig(port=SdkListenKeyPort(rest, rest_gate=gate))
    await adapter.start()

    rest.fail_next("keepalive_user_data_stream", BadRequestError(TEST_ONLY_SDK_MESSAGE, -1125))
    with pytest.raises(ListenKeyInvalid):
        await adapter.keepalive()
    rest.fail_next("keepalive_user_data_stream", TooManyRequestsError(None, -1003, None))
    with pytest.raises(ListenKeyTransient):
        await adapter.keepalive()
    # The 429 paused every REST call of the process (plan 18-14): refused unsent, unchanged.
    with pytest.raises(RateLimitPauseActive):
        await adapter.keepalive()
    now[0] += timedelta(seconds=TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS)
    rest.fail_next("keepalive_user_data_stream", RateLimitBanError(None, -1003, None))
    with pytest.raises(ListenKeyFailure):
        await adapter.keepalive()
    with pytest.raises(RateLimitBanActive):
        await adapter.keepalive()
    now[0] += timedelta(seconds=TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS)
    await adapter.keepalive()

    assert rest.calls["keepalive_user_data_stream"] == 4
    assert rest.calls["start_user_data_stream"] == 1
    assert adapter.epoch == 1


async def test_rekey_on_an_open_connection_subscribes_the_new_key_and_forgets_the_old(
    sdk_stream_map: Any,
) -> None:
    rest = FakeRestUserDataApi(listen_keys=(TEST_ONLY_LISTEN_KEY, TEST_ONLY_SECOND_LISTEN_KEY))
    adapter, _transport, ws, factory, _port = _rig(
        port=SdkListenKeyPort(rest, rest_gate=_rest_gate())
    )
    await adapter.start()

    await adapter.rekey()

    stream_map = sdk_stream_map.stream_connections_map
    assert TEST_ONLY_LISTEN_KEY not in stream_map
    assert stream_map[TEST_ONLY_SECOND_LISTEN_KEY] is ws.connection_for("private")
    assert [frame["params"] for frame in ws.subscribe_frames] == [
        [TEST_ONLY_LISTEN_KEY],
        [TEST_ONLY_SECOND_LISTEN_KEY],
    ]
    assert factory.built == []
    assert rest.calls["start_user_data_stream"] == 2
    assert adapter.epoch == 2

    ws.emit_user_event(TEST_ONLY_SECOND_LISTEN_KEY, make_order_trade_update_message())
    assert adapter.queue.get_nowait().connection_epoch == 2


async def test_rekey_rebuilds_when_the_private_connection_is_gone(sdk_stream_map: Any) -> None:
    rest = FakeRestUserDataApi(listen_keys=(TEST_ONLY_LISTEN_KEY, TEST_ONLY_SECOND_LISTEN_KEY))
    adapter, _transport, ws, factory, _port = _rig(
        port=SdkListenKeyPort(rest, rest_gate=_rest_gate())
    )
    await adapter.start()
    ws.simulate_unsolicited_close()

    await adapter.rekey()

    stream_map = sdk_stream_map.stream_connections_map
    assert TEST_ONLY_LISTEN_KEY not in stream_map
    assert len(factory.built) == 1
    assert stream_map[TEST_ONLY_SECOND_LISTEN_KEY] is factory.built[0].connection_for("private")
    assert ws.close_calls == 1
    assert adapter.epoch == 2


async def test_stop_requires_the_flag_and_is_idempotent(sdk_stream_map: Any) -> None:
    adapter, _transport, ws, _factory, port = _rig()
    await adapter.start()

    with pytest.raises(TypeError):
        await adapter.stop()  # type: ignore[call-arg]

    await adapter.stop(close_listen_key=True)
    await adapter.stop(close_listen_key=True)

    assert ws.close_calls == 1
    assert port.closes == 1
    assert TEST_ONLY_LISTEN_KEY not in sdk_stream_map.stream_connections_map


async def test_stop_without_closing_the_listen_key() -> None:
    adapter, _transport, ws, _factory, port = _rig()
    await adapter.start()

    await adapter.stop(close_listen_key=False)

    assert ws.close_calls == 1
    assert port.closes == 0


# --------------------------------------------------------------------------- #
# Task 2: queue overflow.
# --------------------------------------------------------------------------- #


async def test_full_queue_counts_losses_and_sets_the_flag_without_raising() -> None:
    adapter, _transport, ws, _factory, _port = _rig(queue_max=TEST_ONLY_SMALL_QUEUE_MAX)
    await adapter.start()

    for _ in range(TEST_ONLY_SMALL_QUEUE_MAX + 1):
        ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_order_trade_update_message())

    assert adapter.queue.qsize() == TEST_ONLY_SMALL_QUEUE_MAX
    assert adapter.overflowed is True
    assert adapter.overflow_count == 1

    adapter.clear_overflow()

    assert adapter.overflowed is False
    assert adapter.overflow_count == 1


# --------------------------------------------------------------------------- #
# Task 2: raw-frame tap.
# --------------------------------------------------------------------------- #


def test_raw_tap_receives_a_deep_copy_and_the_original_still_runs() -> None:
    original = sdk_websocket.parse_user_event
    captured: list[object] = []
    frame = order_trade_update_frame()

    with capture_raw_user_events(captured.append):
        assert sdk_websocket.parse_user_event is not original
        parsed = sdk_websocket.parse_user_event(frame, UserDataStreamEventsResponse)

    assert sdk_websocket.parse_user_event is original
    assert captured == [frame]
    assert captured[0] is not frame
    assert captured[0]["o"] is not frame["o"]  # type: ignore[index]
    assert type(parsed.actual_instance).__name__ == "OrderTradeUpdate"


def test_raw_tap_is_removed_after_an_exception() -> None:
    original = sdk_websocket.parse_user_event

    with pytest.raises(RuntimeError), capture_raw_user_events(lambda payload: None):
        raise RuntimeError("inside the tap")

    assert sdk_websocket.parse_user_event is original


def test_raw_tap_sink_failure_does_not_stop_the_sdk_parse() -> None:
    def broken(payload: object) -> None:
        raise RuntimeError("sink bug")

    with capture_raw_user_events(broken):
        parsed = sdk_websocket.parse_user_event(
            order_trade_update_frame(), UserDataStreamEventsResponse
        )

    assert type(parsed.actual_instance).__name__ == "OrderTradeUpdate"


# --------------------------------------------------------------------------- #
# Task 2: SDK log noise guard and log bridge.
# --------------------------------------------------------------------------- #


def test_noise_guard_is_idempotent_and_counts_suppressed_sdk_info_lines() -> None:
    first = install_sdk_noise_guard()
    second = install_sdk_noise_guard()
    root = logging.getLogger()

    assert first is second
    assert sum(isinstance(item, SdkNoiseGuard) for item in root.filters) == 1

    account_line = "Received message: {'e': 'ACCOUNT_UPDATE', 'a': {'B': [{'wb': '123.4'}]}}"
    subscribe_line = f"Subscribing to streams on WebSocket 3: ['{TEST_ONLY_LISTEN_KEY}']"
    send_line = (
        "Sending message to WebSocket 3: "
        f"{{'method': 'SUBSCRIBE', 'params': ['{TEST_ONLY_LISTEN_KEY}']}}"
    )
    with _CapturedRootLogs() as capture:
        root.handle(_record(logging.INFO, account_line))
        root.handle(_record(logging.INFO, subscribe_line))
        root.handle(_record(logging.INFO, send_line))
        root.handle(_record(logging.WARNING, "Received message: kept-because-warning"))
        root.handle(
            _record(logging.INFO, "Received message: kept-foreign", TEST_ONLY_FOREIGN_PATHNAME)
        )
        root.handle(_record(logging.INFO, "Connecting to wss://example.invalid/stream kept-info"))

    output = capture.getvalue()
    assert first.suppressed_count == 3
    assert "ACCOUNT_UPDATE" not in output
    _assert_no_key(TEST_ONLY_LISTEN_KEY, output)
    assert "kept-because-warning" in output
    assert "kept-foreign" in output
    assert "kept-info" in output


def test_sdk_log_bridge_forwards_sdk_warnings_once_and_ignores_the_rest() -> None:
    install_sdk_log_bridge()
    install_sdk_log_bridge()  # idempotent
    root = logging.getLogger()
    assert sum(isinstance(item, bud._UserDataSdkLogBridge) for item in root.handlers) == 1

    with capture_logs() as logs:
        root.handle(_record(logging.ERROR, "WebSocket failed to connect: boom"))
        root.handle(_record(logging.WARNING, "Failed to parse X"))
        root.handle(_record(logging.INFO, "info is not forwarded"))
        root.handle(_record(logging.ERROR, "unrelated", TEST_ONLY_FOREIGN_PATHNAME))

    forwarded = [entry for entry in logs if entry["event"] == "userdata.sdk_log"]
    assert [(entry["sdk_level"], entry["message"]) for entry in forwarded] == [
        ("ERROR", "WebSocket failed to connect: boom"),
        ("WARNING", "Failed to parse X"),
    ]


# --------------------------------------------------------------------------- #
# Task 2: redaction end to end.
# --------------------------------------------------------------------------- #


async def test_sdk_subscribe_line_and_every_repr_carry_no_listen_key() -> None:
    rest = FakeRestUserDataApi()
    port = SdkListenKeyPort(rest, rest_gate=_rest_gate())
    adapter, transport, ws, _factory, _port = _rig(port=port)
    await adapter.start()

    with _CapturedRootLogs() as capture:
        # The SDK's subscribe text, emitted outside the SDK path so the noise guard keeps it:
        # only the registration can protect it.
        logging.info(f"Subscribing to streams on WebSocket 3: ['{TEST_ONLY_LISTEN_KEY}']")

    output = capture.getvalue()
    assert "Subscribing to streams on WebSocket 3" in output
    assert "[REDACTED]" in output
    ws.emit_user_event(TEST_ONLY_LISTEN_KEY, make_order_trade_update_message())
    item = adapter.queue.get_nowait()
    _assert_no_key(
        TEST_ONLY_LISTEN_KEY,
        output,
        repr(adapter),
        repr(transport),
        repr(port),
        repr(transport.diagnostics()),
        repr(item),
    )


def test_path_form_url_not_caught_by_shape_rule_alone() -> None:
    redaction.clear_runtime_secrets()
    try:
        # Negative control: with nothing registered, the listenKey= shape rule does not
        # match the path form, so the key survives scrubbing.
        assert TEST_ONLY_LISTEN_KEY in scrub(_path_url(TEST_ONLY_LISTEN_KEY))
        redaction.register_runtime_secret(TEST_ONLY_LISTEN_KEY)
        _assert_no_key(TEST_ONLY_LISTEN_KEY, scrub(_path_url(TEST_ONLY_LISTEN_KEY)))
    finally:
        redaction.clear_runtime_secrets()


async def test_listen_key_registered_on_start_before_return() -> None:
    redaction.clear_runtime_secrets()
    try:
        buffer = io.StringIO()
        configure_logging(environ={}, stream=buffer)
        install_sdk_log_bridge()
        key = await SdkListenKeyPort(FakeRestUserDataApi(), rest_gate=_rest_gate()).start()

        with _CapturedRootLogs() as capture:
            logging.getLogger().error(f"Connecting to {_path_url(key)}")
            logging.getLogger().handle(_record(logging.ERROR, f"Connecting to {_path_url(key)}"))

        stdlib_output = capture.getvalue()
        structlog_output = buffer.getvalue()
        assert "Connecting to wss://example.invalid/private/ws/" in stdlib_output
        assert "userdata.sdk_log" in structlog_output
        for output in (stdlib_output, structlog_output):
            _assert_no_key(key, output)
            assert "[REDACTED]" in output
    finally:
        redaction.clear_runtime_secrets()


def _leak_like_the_sdk(key: str) -> None:
    """Log the path-form URL the way the SDK reports a swallowed connect failure (root logging)."""
    url = _path_url(key)
    logging.error(f"WebSocket failed to connect: {url}")
    logging.getLogger().handle(_record(logging.ERROR, f"WebSocket failed to connect: {url}"))


def _assert_outputs_clean(key: str, stdlib_output: str, structlog_output: str) -> None:
    assert "WebSocket failed to connect" in stdlib_output
    assert "userdata.sdk_log" in structlog_output
    _assert_no_key(key, stdlib_output, structlog_output)


async def test_transport_registers_key_before_connect_logs() -> None:
    redaction.clear_runtime_secrets()
    try:
        buffer = io.StringIO()
        configure_logging(environ={}, stream=buffer)
        ws = FakeUserDataWsClient(
            on_create_connection=lambda: _leak_like_the_sdk(TEST_ONLY_LISTEN_KEY)
        )
        transport = SdkUserDataTransport(_configuration(), client_factory=_Factory(), ws_client=ws)

        with _CapturedRootLogs() as capture:
            await transport.connect(TEST_ONLY_LISTEN_KEY)  # never seen by a listenKey port

        _assert_outputs_clean(TEST_ONLY_LISTEN_KEY, capture.getvalue(), buffer.getvalue())
    finally:
        redaction.clear_runtime_secrets()


async def test_transport_registers_key_before_rebuild_logs() -> None:
    redaction.clear_runtime_secrets()
    try:
        buffer = io.StringIO()
        configure_logging(environ={}, stream=buffer)

        def factory(configuration: ConfigurationWebSocketStreams) -> FakeUserDataWsClient:
            return FakeUserDataWsClient(
                on_create_connection=lambda: _leak_like_the_sdk(TEST_ONLY_SECOND_LISTEN_KEY)
            )

        transport = SdkUserDataTransport(
            _configuration(), client_factory=factory, ws_client=FakeUserDataWsClient()
        )
        await transport.connect(TEST_ONLY_LISTEN_KEY)

        with _CapturedRootLogs() as capture:
            await transport.rebuild(TEST_ONLY_SECOND_LISTEN_KEY)

        _assert_outputs_clean(TEST_ONLY_SECOND_LISTEN_KEY, capture.getvalue(), buffer.getvalue())
    finally:
        redaction.clear_runtime_secrets()


async def test_rekey_registers_the_new_key_before_subscribe_logs() -> None:
    redaction.clear_runtime_secrets()
    try:
        buffer = io.StringIO()
        configure_logging(environ={}, stream=buffer)

        def subscribe_line(key: str) -> None:
            # The SDK logs the SUBSCRIBE params (the bare key) before sending the frame.
            logging.error(f"Subscribing to streams on WebSocket 3: ['{key}']")

        ws = FakeUserDataWsClient(on_user_data=subscribe_line)
        port = _KeySequence(TEST_ONLY_LISTEN_KEY, TEST_ONLY_SECOND_LISTEN_KEY)
        adapter, _transport, _ws, _factory, _port = _rig(ws=ws, port=port)
        await adapter.start()

        with _CapturedRootLogs() as capture:
            await adapter.rekey()

        output = capture.getvalue()
        assert "Subscribing to streams on WebSocket 3" in output
        _assert_no_key(TEST_ONLY_SECOND_LISTEN_KEY, output, buffer.getvalue())
    finally:
        redaction.clear_runtime_secrets()


def test_register_runtime_secret_is_the_first_statement_of_every_key_entry_point() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    transport_class = _class_def(tree, "SdkUserDataTransport")
    methods = {
        node.name: node
        for node in transport_class.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    for name in ("connect", "rebuild", "resubscribe"):
        body = list(methods[name].body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]  # the docstring
        first = body[0]
        assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call), name
        assert _call_name(first.value) == "register_runtime_secret", name
        argument = first.value.args[0]
        assert isinstance(argument, ast.Name) and argument.id == "listen_key", name


def test_module_has_no_wall_clock_no_float_no_print_and_no_forbidden_import() -> None:
    assert wall_clock_calls(MODULE_PATH) == []
    assert float_constructor_calls(MODULE_PATH) == []
    assert forbidden_imports(MODULE_PATH, ("src.paper",)) == []
    # Plan 18-14 wired the process-wide REST gate into the listenKey port; it is the only
    # gate the module may hold (no second rate-limit state).
    assert "src.adapters.binance_ratelimit_gate" in module_imports(MODULE_PATH)
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert _call_name(node) != "print"
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    for inner in ast.walk(part.value):
                        named = inner.id if isinstance(inner, ast.Name) else None
                        attr = inner.attr if isinstance(inner, ast.Attribute) else None
                        for text in (named, attr):
                            assert text is None or "listen_key" not in text.lower(), (
                                "an f-string interpolates a listenKey"
                            )


def test_noise_guard_scrubs_a_key_bearing_sdk_error_line_for_every_handler() -> None:
    """Review WR-11: the SDK's ERROR line carries the stream name (the listenKey)."""
    redaction.register_runtime_secret(TEST_ONLY_LISTEN_KEY)
    install_sdk_noise_guard()
    root = logging.getLogger()
    stream = io.StringIO()
    plain = logging.StreamHandler(stream)  # deliberately NO RedactingFilter
    plain.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    record = logging.LogRecord(
        name="root",
        level=logging.ERROR,
        pathname=TEST_ONLY_SDK_PATHNAME,
        lineno=1,
        msg="Error in callback for key %s: %s",
        args=(TEST_ONLY_LISTEN_KEY, "boom"),
        exc_info=None,
    )
    old_level = root.level
    root.addHandler(plain)
    root.setLevel(logging.DEBUG)
    try:
        root.handle(record)
    finally:
        root.removeHandler(plain)
        root.setLevel(old_level)

    output = stream.getvalue()
    assert "Error in callback for key" in output
    assert "[REDACTED]" in output
    _assert_no_key(TEST_ONLY_LISTEN_KEY, output)


# --------------------------------------------------------------------------- #
# Review WR-06: a partial failure leaks no key and leaves no dirty client.
# --------------------------------------------------------------------------- #


async def test_a_failed_connect_still_lets_stop_delete_the_listen_key() -> None:
    adapter, _transport, ws, _factory, port = _rig()

    def _fail(_key: str) -> None:
        raise RuntimeError("subscribe failed")

    ws.on_user_data = _fail
    with pytest.raises(RuntimeError):
        await adapter.start()
    assert port.starts == 1

    await adapter.stop(close_listen_key=True)

    assert port.closes == 1


async def test_a_retried_start_uses_a_fresh_client_instead_of_stacking_connections() -> None:
    adapter, transport, ws, factory, port = _rig()
    calls = {"n": 0}

    def _fail_once(_key: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("subscribe failed")

    ws.on_user_data = _fail_once
    with pytest.raises(RuntimeError):
        await adapter.start()
    assert len(ws.connections) == 3  # the failed attempt left its connections behind

    await adapter.start()

    assert len(factory.built) == 1  # a fresh client replaced the dirty one
    assert ws.close_calls == 1  # the dirty client was released
    assert transport.diagnostics().connection_count == 3
    assert adapter.epoch == 1
    assert port.starts == 2


async def test_a_stop_whose_transport_close_fails_still_deletes_the_key_and_can_be_rerun() -> None:
    adapter, _transport, ws, _factory, port = _rig()
    await adapter.start()
    ws.close_should_raise = RuntimeError("close failed")

    with pytest.raises(RuntimeError):
        await adapter.stop(close_listen_key=True)
    assert port.closes == 1  # the DELETE was attempted in spite of the failed close

    ws.close_should_raise = None
    await adapter.stop(close_listen_key=False)  # not locked out by the first attempt
    assert ws.close_calls == 2
