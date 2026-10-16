"""Offline pin of the installed SDK's HTTP-status to exception mapping (plan 18-05).

The taxonomy in `src/domain/exchange_errors.py` is keyed on the triple
(SDK exception class, int Binance code, call kind) because the SDK reports the
Binance body code in `status_code`, not the HTTP status (research F4, P10).
These tests drive the installed `binance_common.utils.send_request` with a
stub session, so a change of SDK behavior fails here instead of silently
changing a classification. No socket is opened and no real host is called:
the base path is `https://example.invalid` and the session is a stub.
"""

from __future__ import annotations

import inspect
import json
import socket
from collections.abc import Mapping
from typing import Any

import binance_common.errors as sdk_errors
import binance_common.utils as sdk_utils
import pytest
import requests
from binance_common.configuration import ConfigurationRestAPI
from binance_common.errors import (
    BadRequestError,
    ClientError,
    ForbiddenError,
    NetworkError,
    NotFoundError,
    RateLimitBanError,
    RequiredError,
    ServerError,
    TooManyRequestsError,
    UnauthorizedError,
)
from binance_common.utils import send_request
from src.adapters.binance_errors import error_facts_from_exception
from src.domain.exchange_errors import (
    CallKind,
    ErrorFacts,
    ExchangeErrorCategory,
    HttpClass,
    RateLimitDecision,
    classify,
    rate_limit_decision,
)

from tests.test_exchange_errors import (
    TEST_ONLY_418_FALLBACK_SECONDS,
    TEST_ONLY_429_FALLBACK_SECONDS,
    TEST_ONLY_CAP_SECONDS,
)


@pytest.fixture(autouse=True)
def _no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to open a connection fails the test."""

    def _refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("this contract test must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


class _StubResponse:
    """The attributes `send_request` reads from a `requests` response."""

    def __init__(self, status_code: int, headers: Mapping[str, str], body: str) -> None:
        self.status_code = status_code
        self.headers = dict(headers)
        self.text = body

    def json(self) -> Any:
        return json.loads(self.text)


class _StubSession:
    """A `requests.Session` stand-in: records each call, never opens a socket."""

    def __init__(
        self,
        response: _StubResponse | None = None,
        raises: BaseException | None = None,
    ) -> None:
        self._response = response
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> _StubResponse:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        assert self._response is not None
        return self._response

    def mount(self, *_: Any) -> None:  # pragma: no cover - https_agent is never set here
        raise AssertionError("no transport adapter may be mounted in this test")


def _config(retries: int = 0) -> ConfigurationRestAPI:
    return ConfigurationRestAPI(
        api_key="TEST_ONLY_KEY",
        api_secret="TEST_ONLY_SECRET",
        base_path="https://example.invalid",
        retries=retries,
        timeout=1000,
    )


def _json_response(status: int, code: int, msg: str, **headers: str) -> _StubResponse:
    all_headers = {"Content-Type": "application/json", **headers}
    return _StubResponse(status, all_headers, json.dumps({"code": code, "msg": msg}))


def _send(session: _StubSession, *, method: str = "GET", retries: int = 0) -> BaseException:
    """Run the installed `send_request` and return the exception it raised."""
    with pytest.raises(Exception) as info:
        send_request(
            session,  # type: ignore[arg-type]
            _config(retries),
            method=method,
            path="/fapi/v1/order",
            payload={"symbol": "BTCUSDT", "origClientOrderId": "x-test"},
            is_signed=False,
        )
    return info.value


def test_tracer_sdk_bad_request_2013_is_order_absent_for_query_only() -> None:
    """Task 1 tracer: a real SDK error from a stubbed 400 reaches a category."""
    session = _StubSession(_json_response(400, -2013, "Order does not exist."))
    exc = _send(session)

    assert type(exc) is BadRequestError
    assert exc.status_code == -2013
    assert len(session.calls) == 1

    facts = error_facts_from_exception(exc)
    assert facts == ErrorFacts(HttpClass.BAD_REQUEST, -2013, None)
    assert classify(facts, CallKind.QUERY) is ExchangeErrorCategory.ORDER_ABSENT
    assert classify(facts, CallKind.PLACEMENT) is ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR


# --------------------------------------------------------------------------- #
# Task 3: the HTTP-status to exception mapping of the installed SDK
# (18-RESEARCH.md F4 "How the SDK surfaces them").
# --------------------------------------------------------------------------- #

# (HTTP status, body code, SDK class, expected `status_code`, HttpClass, ErrorFacts.code)
_STATUS_ROWS: list[tuple[int, int, type[BaseException], int | None, HttpClass, int | None]] = [
    (400, -2013, BadRequestError, -2013, HttpClass.BAD_REQUEST, -2013),
    (401, -2015, UnauthorizedError, -2015, HttpClass.UNAUTHORIZED, -2015),
    (403, -2015, ForbiddenError, -2015, HttpClass.FORBIDDEN, -2015),
    (404, -2013, NotFoundError, -2013, HttpClass.NOT_FOUND, -2013),
    # Any other 4xx goes to the else branch: ClientError built with no code.
    (408, -1007, ClientError, None, HttpClass.CLIENT_OTHER, None),
    # 418 and 429: the body code, not the HTTP status.
    (418, -1003, RateLimitBanError, -1003, HttpClass.BANNED_418, -1003),
    (429, -1003, TooManyRequestsError, -1003, HttpClass.TOO_MANY_429, -1003),
    # 5xx: the body is discarded; `status_code` is the HTTP status.
    (500, -1007, ServerError, 500, HttpClass.SERVER_5XX, None),
    (502, -1007, ServerError, 502, HttpClass.SERVER_5XX, None),
    (503, -1007, ServerError, 503, HttpClass.SERVER_5XX, None),
]

_EXPECTED_CATEGORY_BY_CLASS: dict[HttpClass, ExchangeErrorCategory] = {
    HttpClass.UNAUTHORIZED: ExchangeErrorCategory.AUTH_OR_SIGNATURE,
    HttpClass.FORBIDDEN: ExchangeErrorCategory.AUTH_OR_SIGNATURE,
    HttpClass.CLIENT_OTHER: ExchangeErrorCategory.STATUS_UNKNOWN,
    HttpClass.BANNED_418: ExchangeErrorCategory.IP_BANNED,
    HttpClass.TOO_MANY_429: ExchangeErrorCategory.RATE_LIMITED,
    HttpClass.SERVER_5XX: ExchangeErrorCategory.STATUS_UNKNOWN,
}


@pytest.mark.parametrize(
    ("status", "body_code", "sdk_class", "status_code", "http_class", "facts_code"),
    _STATUS_ROWS,
    ids=[f"http{row[0]}" for row in _STATUS_ROWS],
)
def test_status_row_maps_to_sdk_class_and_facts(
    status: int,
    body_code: int,
    sdk_class: type[BaseException],
    status_code: int | None,
    http_class: HttpClass,
    facts_code: int | None,
) -> None:
    exc = _send(_StubSession(_json_response(status, body_code, "stub message")))
    assert type(exc) is sdk_class
    assert getattr(exc, "status_code", "missing") == status_code
    facts = error_facts_from_exception(exc)
    assert facts.http_class is http_class
    assert facts.code == facts_code
    if sdk_class in (RateLimitBanError, TooManyRequestsError):
        assert getattr(exc, "retry_after", "missing") is None
        assert facts.retry_after_seconds is None
        with_header = _send(
            _StubSession(_json_response(status, body_code, "stub", **{"Retry-After": "7"}))
        )
        assert type(with_header) is sdk_class
        assert getattr(with_header, "retry_after", None) == 7
        assert error_facts_from_exception(with_header) == ErrorFacts(http_class, facts_code, 7)
    else:
        assert not hasattr(exc, "retry_after")
        assert facts.retry_after_seconds is None
    if http_class in _EXPECTED_CATEGORY_BY_CLASS:
        for kind in CallKind:
            assert classify(facts, kind) is _EXPECTED_CATEGORY_BY_CLASS[http_class]


def test_5xx_with_a_non_json_body_is_the_same_server_error() -> None:
    """The SDK discards the 5xx body, so the 503 variants cannot be told apart."""
    for body, content_type in (("Service Unavailable.", "text/plain"), ("", "text/html")):
        exc = _send(_StubSession(_StubResponse(503, {"Content-Type": content_type}, body)))
        assert type(exc) is ServerError
        assert exc.status_code == 503
        assert error_facts_from_exception(exc) == ErrorFacts(HttpClass.SERVER_5XX, None, None)


def test_400_with_a_non_json_body_has_no_code_and_is_unknown() -> None:
    response = _StubResponse(400, {"Content-Type": "text/html"}, "<html>Bad Request</html>")
    exc = _send(_StubSession(response))
    assert type(exc) is BadRequestError
    assert exc.status_code is None
    facts = error_facts_from_exception(exc)
    assert facts == ErrorFacts(HttpClass.BAD_REQUEST, None, None)
    for kind in CallKind:
        assert classify(facts, kind) is ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR


_FALLBACK_BY_STATUS = {
    418: (ExchangeErrorCategory.IP_BANNED, TEST_ONLY_418_FALLBACK_SECONDS),
    429: (ExchangeErrorCategory.RATE_LIMITED, TEST_ONLY_429_FALLBACK_SECONDS),
}


def _decide(category: ExchangeErrorCategory, retry_after: int | None) -> RateLimitDecision:
    return rate_limit_decision(
        category,
        retry_after,
        no_retry_after_wait_418_seconds=TEST_ONLY_418_FALLBACK_SECONDS,
        no_retry_after_wait_429_seconds=TEST_ONLY_429_FALLBACK_SECONDS,
        retry_after_cap_seconds=TEST_ONLY_CAP_SECONDS,
    )


@pytest.mark.parametrize("status", [418, 429])
def test_unparseable_retry_after_reaches_the_decision_as_none(status: int) -> None:
    exc = _send(_StubSession(_json_response(status, -1003, "stub", **{"Retry-After": "soon"})))
    assert getattr(exc, "retry_after", "missing") is None
    facts = error_facts_from_exception(exc)
    assert facts.retry_after_seconds is None
    category, fallback = _FALLBACK_BY_STATUS[status]
    assert classify(facts, CallKind.CANCEL) is category
    assert _decide(category, facts.retry_after_seconds) == RateLimitDecision(False, fallback)


@pytest.mark.parametrize("status", [418, 429])
def test_negative_retry_after_is_dropped_by_the_normalizer(status: int) -> None:
    exc = _send(_StubSession(_json_response(status, -1003, "stub", **{"Retry-After": "-5"})))
    assert getattr(exc, "retry_after", "missing") == -5  # the SDK passes it through
    facts = error_facts_from_exception(exc)
    assert facts.retry_after_seconds is None
    category, fallback = _FALLBACK_BY_STATUS[status]
    assert _decide(category, facts.retry_after_seconds) == RateLimitDecision(False, fallback)


@pytest.mark.parametrize("status", [418, 429])
def test_missing_retry_after_uses_the_status_fallback(status: int) -> None:
    exc = _send(_StubSession(_json_response(status, -1003, "stub")))
    facts = error_facts_from_exception(exc)
    category, fallback = _FALLBACK_BY_STATUS[status]
    assert _decide(category, facts.retry_after_seconds) == RateLimitDecision(False, fallback)


def test_connect_timeout_is_network_error_and_status_unknown() -> None:
    session = _StubSession(
        raises=requests.exceptions.ConnectTimeout("signature=deadbeef host unreachable")
    )
    exc = _send(session, method="GET", retries=0)
    assert type(exc) is NetworkError
    assert len(session.calls) == 1
    facts = error_facts_from_exception(exc)
    assert facts == ErrorFacts(HttpClass.NETWORK, None, None)
    for kind in CallKind:
        assert classify(facts, kind) is ExchangeErrorCategory.STATUS_UNKNOWN

    other = _send(
        _StubSession(raises=requests.exceptions.ConnectTimeout("-2013 Order does not exist.")),
        retries=0,
    )
    assert type(other) is NetworkError
    assert error_facts_from_exception(other) == facts
    assert error_facts_from_exception(NetworkError("-2013 UNKNOWN_ORDER")) == facts


class _SleepRecorder:
    """Stands in for the `time` module inside `binance_common.utils` (sleep only)."""

    def __init__(self) -> None:
        self.sleeps: list[Any] = []

    def sleep(self, seconds: Any) -> None:
        self.sleeps.append(seconds)


def test_sdk_retry_pin_get_retries_on_network_error_post_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin of the SDK's own retry loop (research P9: SDK and project retries stack).

    Installed behavior (`send_request`, `should_retry_request`): only a
    `requests.RequestException` is retried, only for GET and DELETE, with
    `time.sleep(backoff * attempt)`. With `retries=2` the loop sends 2 requests,
    not 3: after the second failure `retries - attempt` is 0 and the error is
    raised (SDK delta against the research reading "retries=N gives N+1 tries").
    """
    recorder = _SleepRecorder()
    monkeypatch.setattr(sdk_utils, "time", recorder)

    get_session = _StubSession(raises=requests.exceptions.ConnectTimeout("stub"))
    assert type(_send(get_session, method="GET", retries=2)) is NetworkError
    assert len(get_session.calls) == 2
    assert recorder.sleeps == [1.0]  # backoff 1000 ms (default) times attempt 1

    recorder.sleeps.clear()
    delete_session = _StubSession(raises=requests.exceptions.ConnectTimeout("stub"))
    assert type(_send(delete_session, method="DELETE", retries=2)) is NetworkError
    assert len(delete_session.calls) == 2
    assert recorder.sleeps == [1.0]

    recorder.sleeps.clear()
    post_session = _StubSession(raises=requests.exceptions.ConnectTimeout("stub"))
    assert type(_send(post_session, method="POST", retries=2)) is NetworkError
    assert len(post_session.calls) == 1
    assert recorder.sleeps == []

    recorder.sleeps.clear()
    retries_three = _StubSession(raises=requests.exceptions.ConnectTimeout("stub"))
    assert type(_send(retries_three, method="GET", retries=3)) is NetworkError
    assert len(retries_three.calls) == 3
    assert recorder.sleeps == [1.0, 2.0]


def test_sdk_does_not_retry_an_http_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 5xx, 418 or 429 answer raises at once even for a GET with retries left."""
    recorder = _SleepRecorder()
    monkeypatch.setattr(sdk_utils, "time", recorder)
    for status in (503, 418, 429):
        session = _StubSession(_json_response(status, -1003, "stub"))
        _send(session, method="GET", retries=2)
        assert len(session.calls) == 1
    assert recorder.sleeps == []


def test_installed_sdk_error_class_set_is_the_one_mapped() -> None:
    """A new or renamed SDK error class fails here before it can bypass the normalizer."""
    classes = {
        name
        for name, value in inspect.getmembers(sdk_errors, inspect.isclass)
        if issubclass(value, sdk_errors.Error) and value is not sdk_errors.Error
    }
    assert classes == {
        "BadRequestError",
        "ClientError",
        "ForbiddenError",
        "NetworkError",
        "NotFoundError",
        "RateLimitBanError",
        "RequiredError",
        "ServerError",
        "TooManyRequestsError",
        "UnauthorizedError",
    }
    # RequiredError is raised before any request is sent (a missing parameter):
    # a programming error, so it is NON_SDK and UNKNOWN_EXCHANGE_ERROR.
    assert error_facts_from_exception(RequiredError("symbol")) == ErrorFacts(
        HttpClass.NON_SDK, None, None
    )


def test_normalizer_rejects_bool_and_non_int_codes_and_retry_after() -> None:
    assert error_facts_from_exception(BadRequestError(status_code=True)).code is None  # type: ignore[arg-type]
    assert error_facts_from_exception(BadRequestError(status_code="-2013")).code is None  # type: ignore[arg-type]
    ban = RateLimitBanError(status_code=-1003, retry_after=True)  # type: ignore[arg-type]
    assert error_facts_from_exception(ban).retry_after_seconds is None
    throttle = TooManyRequestsError(status_code=-1003, retry_after="7")  # type: ignore[arg-type]
    assert error_facts_from_exception(throttle).retry_after_seconds is None
    server = ServerError(status_code=503)
    assert error_facts_from_exception(server) == ErrorFacts(HttpClass.SERVER_5XX, None, None)
