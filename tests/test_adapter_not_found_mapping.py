"""Not-found mapping for the two by-client-id query probes (Phase 9 Demo finding, plan 18-10).

Observed on demo-fapi.binance.com (read-only GET /fapi/v1/algoOrder, 2026-10-05):
the SDK raises ``BadRequestError`` with ``status_code=-2013`` and
``error_message='Order does not exist.'``. Only the taxonomy category ORDER_ABSENT of a
QUERY call (``src/domain/exchange_errors.py``: -2013 or -2011 carried as the int code of a
400 or 404 SDK error) may become ``found=False`` (that enables a retry of the placement);
every other error must raise the same exception object (fail closed), and message text never
decides (D-10, 08-REVIEW IN-10).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from binance_common.errors import (
    ClientError,
    NetworkError,
    NotFoundError,
    RateLimitBanError,
    ServerError,
    TooManyRequestsError,
)
from binance_sdk_derivatives_trading_usds_futures import BadRequestError
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import (
    INVALID_SYMBOL_CODE,
    BinanceUsdmAdapter,
    is_invalid_symbol_error,
    is_rate_limit_ban_error,
    is_rate_limit_error,
    rate_limit_retry_after_seconds,
)

from tests.support.limits import test_only_signed_call_policy


def _adapter(exc: BaseException) -> BinanceUsdmAdapter:
    def _raise(**_: Any) -> Any:
        raise exc

    rest = SimpleNamespace(query_algo_order=_raise, query_order=_raise)
    # Plan 18-13: signed calls need the TEST_ONLY policy and the one shared gate.
    policy = test_only_signed_call_policy()
    return BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        signed_call_policy=policy,
        rest_gate=RestRateLimitGate(
            policy=policy.rate_limit, clock=lambda: datetime(2026, 10, 16, tzinfo=UTC)
        ),
    )


def _bad(code: int | None, msg: str) -> BadRequestError:
    return BadRequestError(error_message=msg, status_code=code)


def _query_algo(adapter: BinanceUsdmAdapter) -> Any:
    return asyncio.run(adapter.query_algo_order_by_client(client_algo_id="x-abc"))


def _query_order(adapter: BinanceUsdmAdapter) -> Any:
    return asyncio.run(
        adapter.query_order_by_client(symbol="BTCUSDT", orig_client_order_id="x-abc")
    )


# --------------------------------------------------------------------------- #
# ORDER_ABSENT of a QUERY: the only "absent" answer.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cls", [BadRequestError, NotFoundError])
@pytest.mark.parametrize("code", [-2013, -2011])
def test_algo_query_maps_not_found_codes_to_found_false(cls: type[Exception], code: int) -> None:
    adapter = _adapter(cls("Order does not exist.", code))  # type: ignore[call-arg]
    probe = _query_algo(adapter)
    assert probe.found is False
    assert probe.client_algo_id == "x-abc"


@pytest.mark.parametrize("cls", [BadRequestError, NotFoundError])
@pytest.mark.parametrize("code", [-2013, -2011])
def test_order_query_maps_not_found_codes_to_found_false(cls: type[Exception], code: int) -> None:
    adapter = _adapter(cls("Order does not exist.", code))  # type: ignore[call-arg]
    probe = _query_order(adapter)
    assert probe.found is False
    assert probe.client_order_id == "x-abc"


# --------------------------------------------------------------------------- #
# Everything else re-raises the exact exception object.
# --------------------------------------------------------------------------- #


def _reraise_cases() -> list[tuple[str, BaseException]]:
    cases: list[tuple[str, BaseException]] = [
        (f"bad_request_{code}", _bad(code, "something else"))
        for code in (-1021, -1003, -2014, -2015, -1121, -2019, -4164, -2022)
    ]
    cases += [
        ("bad_request_code_none", _bad(None, "Order does not exist.")),
        ("bad_request_unlisted_code", _bad(-999_999, "Order does not exist.")),
        ("server_error", ServerError("Order does not exist.", 503)),
        ("network_error", NetworkError("-2013 Order does not exist.")),
        ("too_many_requests", TooManyRequestsError("-2013", -1003, 7)),
        ("rate_limit_ban", RateLimitBanError("-2011", -1003, None)),
        ("client_error", ClientError("-2013", None)),
        ("runtime_legacy_text", RuntimeError("-2011 UNKNOWN_ORDER")),
        ("runtime_code_text", RuntimeError("code -2013")),
        ("value_error", ValueError("-2013")),
        ("code_in_text_only", _bad(-1000, "ref -2013 in text")),
    ]
    return cases


_RERAISE = _reraise_cases()


@pytest.mark.parametrize(("name", "exc"), _RERAISE, ids=[name for name, _ in _RERAISE])
def test_every_other_error_reraises_the_same_object(name: str, exc: BaseException) -> None:
    with pytest.raises(type(exc)) as algo_info:
        _query_algo(_adapter(exc))
    assert algo_info.value is exc, name
    with pytest.raises(type(exc)) as order_info:
        _query_order(_adapter(exc))
    assert order_info.value is exc, name


def test_a_code_number_inside_other_text_is_not_not_found() -> None:
    """-20130 or a message that merely contains '-2013' must not match."""
    for exc in (_bad(-1000, "ref -2013 in text"), RuntimeError("code -20130 unknown")):
        adapter = _adapter(exc)
        with pytest.raises(type(exc)):
            _query_algo(adapter)


def test_legacy_message_form_no_longer_maps_to_absent() -> None:
    """Reversed on purpose (D-10, 08-REVIEW IN-10).

    Until plan 18-10 a non-SDK exception whose text carried "-2011" or "UNKNOWN_ORDER" was
    read as "order absent". Message text never decides now: a non-SDK exception is
    UNKNOWN_EXCHANGE_ERROR, so the probe raises and the execution manager fails closed
    instead of treating a possibly live order as gone (a duplicate-order risk).
    """
    exc = RuntimeError("-2011 UNKNOWN_ORDER")
    with pytest.raises(RuntimeError) as algo_info:
        _query_algo(_adapter(exc))
    assert algo_info.value is exc
    with pytest.raises(RuntimeError) as order_info:
        _query_order(_adapter(exc))
    assert order_info.value is exc


# --------------------------------------------------------------------------- #
# The public helper names keep working (backfill, universe freeze, collector).
# --------------------------------------------------------------------------- #


def test_public_rate_limit_and_symbol_helpers_still_behave() -> None:
    assert is_rate_limit_error(TooManyRequestsError("429", 429, 3)) is True
    assert is_rate_limit_error(RateLimitBanError("418", 418, None)) is True
    assert is_rate_limit_error(RuntimeError("TooManyRequests")) is False
    assert is_rate_limit_ban_error(RateLimitBanError("418")) is True
    assert is_rate_limit_ban_error(TooManyRequestsError("429")) is False
    assert INVALID_SYMBOL_CODE == -1121
    assert is_invalid_symbol_error(_bad(-1121, "Invalid symbol.")) is True
    assert is_invalid_symbol_error(_bad(-2013, "x")) is False


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (TooManyRequestsError("429", 429, 45), 45),
        (TooManyRequestsError("429", 429, 0), 0),
        (TooManyRequestsError("429", 429, None), None),
        (TooManyRequestsError("429", 429, -1), None),
        (TooManyRequestsError("429", 429, True), None),  # type: ignore[arg-type]
        (TooManyRequestsError("429", 429, "45"), None),  # type: ignore[arg-type]
        (RateLimitBanError("418", 418, 120), 120),
        (RuntimeError("retry after 45"), None),
    ],
)
def test_rate_limit_retry_after_seconds_agrees_with_the_shared_normalizer(
    exc: BaseException, expected: int | None
) -> None:
    assert rate_limit_retry_after_seconds(exc) == expected
