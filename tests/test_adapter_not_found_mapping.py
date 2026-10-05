"""Not-found mapping for the two by-client-id query probes (Phase 9 Demo finding).

Observed on demo-fapi.binance.com (read-only GET /fapi/v1/algoOrder, 2026-10-05):
the SDK raises ``BadRequestError`` with ``status_code=-2013`` and
``error_message='Order does not exist.'``; ``str(exc)`` is
``"(-2013, 'Order does not exist.')"``. Only a definitive not-found code may become
``found=False`` (that enables a retry); every other error must still raise (fail closed).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures import BadRequestError
from src.adapters.binance_usdm import BinanceUsdmAdapter


def _adapter(exc: BaseException) -> BinanceUsdmAdapter:
    def _raise(**_: Any) -> Any:
        raise exc

    rest = SimpleNamespace(query_algo_order=_raise, query_order=_raise)
    return BinanceUsdmAdapter(sdk_client=SimpleNamespace(rest_api=rest))  # type: ignore[arg-type]


def _bad(code: int, msg: str) -> BadRequestError:
    return BadRequestError(error_message=msg, status_code=code)


@pytest.mark.parametrize("code", [-2013, -2011])
def test_algo_query_maps_not_found_codes_to_found_false(code: int) -> None:
    adapter = _adapter(_bad(code, "Order does not exist."))
    probe = asyncio.run(adapter.query_algo_order_by_client(client_algo_id="x-abc"))
    assert probe.found is False
    assert probe.client_algo_id == "x-abc"


@pytest.mark.parametrize("code", [-2013, -2011])
def test_order_query_maps_not_found_codes_to_found_false(code: int) -> None:
    adapter = _adapter(_bad(code, "Order does not exist."))
    probe = asyncio.run(
        adapter.query_order_by_client(symbol="BTCUSDT", orig_client_order_id="x-abc")
    )
    assert probe.found is False


@pytest.mark.parametrize("code", [-1021, -1003, -2014, -2015, -1121, -2019, -4164, -2022])
def test_other_codes_still_raise(code: int) -> None:
    adapter = _adapter(_bad(code, "something else"))
    with pytest.raises(BadRequestError):
        asyncio.run(adapter.query_algo_order_by_client(client_algo_id="x-abc"))
    with pytest.raises(BadRequestError):
        asyncio.run(adapter.query_order_by_client(symbol="BTCUSDT", orig_client_order_id="x-abc"))


def test_a_code_number_inside_other_text_is_not_not_found() -> None:
    """-20130 or a message that merely contains '-2013' must not match."""
    for exc in (_bad(-1000, "ref -2013 in text"), RuntimeError("code -20130 unknown")):
        adapter = _adapter(exc)
        with pytest.raises(type(exc)):
            asyncio.run(adapter.query_algo_order_by_client(client_algo_id="x-abc"))


def test_legacy_message_form_still_maps() -> None:
    """Fakes and older wrappers carry the code only in the message text."""
    adapter = _adapter(RuntimeError("-2011 UNKNOWN_ORDER"))
    probe = asyncio.run(adapter.query_algo_order_by_client(client_algo_id="x-abc"))
    assert probe.found is False
