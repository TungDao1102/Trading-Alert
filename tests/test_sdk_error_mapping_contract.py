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

import json
from collections.abc import Mapping
from typing import Any

import pytest
from binance_common.configuration import ConfigurationRestAPI
from binance_common.errors import BadRequestError
from binance_common.utils import send_request
from src.adapters.binance_errors import error_facts_from_exception
from src.domain.exchange_errors import (
    CallKind,
    ErrorFacts,
    ExchangeErrorCategory,
    HttpClass,
    classify,
)


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
