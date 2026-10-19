"""GTD with goodTillDate on the LIMIT entry and the executed quantity on the order probe.

Plan 19-05 (D-05 exchange-side expiry backstop, D-10 REST fill source). Fake SDK REST surface,
no network, no real sleep.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures import BadRequestError
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import BinanceUsdmAdapter, OrderProbe

from tests.support.limits import test_only_signed_call_policy

_GTD_MS = 1_789_903_200_000
_UPDATE_MS = 1_789_900_000_000
_CID = "xa-194547b9a1659419ecfa4a736a3decee"


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _FakeRest:
    def __init__(self, query_payload: Any = None) -> None:
        self.new_order_calls: list[dict[str, Any]] = []
        self.query_order_calls: list[dict[str, Any]] = []
        self.query_payload = query_payload

    def new_order(self, **kwargs: Any) -> _FakeResponse:
        self.new_order_calls.append(kwargs)
        return _FakeResponse(
            SimpleNamespace(
                symbol=kwargs["symbol"],
                client_order_id=kwargs["new_client_order_id"],
                order_id=987654,
                side=kwargs["side"].value,
                position_side=kwargs["position_side"],
                type=kwargs["type"].value,
                time_in_force=kwargs["time_in_force"].value,
                status="NEW",
                orig_qty=kwargs["quantity"],
                price=kwargs["price"],
                update_time=_UPDATE_MS,
            )
        )

    def query_order(self, **kwargs: Any) -> _FakeResponse:
        self.query_order_calls.append(kwargs)
        if isinstance(self.query_payload, Exception):
            raise self.query_payload
        return _FakeResponse(self.query_payload)


def _adapter(query_payload: Any = None) -> tuple[BinanceUsdmAdapter, _FakeRest]:
    rest = _FakeRest(query_payload)
    policy = test_only_signed_call_policy()
    gate = RestRateLimitGate(
        policy=policy.rate_limit, clock=lambda: datetime(2026, 10, 16, tzinfo=UTC)
    )
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        signed_call_policy=policy,
        rest_gate=gate,
    )
    return adapter, rest


def _entry_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "time_in_force": "GTC",
        "quantity": Decimal("0.004"),
        "price": Decimal("101.20"),
        "new_client_order_id": _CID,
    }
    kwargs.update(overrides)
    return kwargs


# --------------------------------------------------------------------------- #
# Task 2: GTD with goodTillDate.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_gtd_forwards_good_till_date_in_one_sdk_call() -> None:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
        NewOrderTimeInForceEnum,
    )

    adapter, rest = _adapter()
    await adapter.place_entry(**_entry_kwargs(time_in_force="GTD", good_till_date=_GTD_MS))
    assert len(rest.new_order_calls) == 1
    sent = rest.new_order_calls[0]
    assert sent["time_in_force"] is NewOrderTimeInForceEnum.GTD
    assert sent["good_till_date"] == _GTD_MS
    assert type(sent["good_till_date"]) is int


@pytest.mark.asyncio
async def test_gtd_without_good_till_date_raises_before_anything_is_sent() -> None:
    adapter, rest = _adapter()
    with pytest.raises(ValueError, match="good_till_date"):
        await adapter.place_entry(**_entry_kwargs(time_in_force="GTD"))
    assert rest.new_order_calls == []


@pytest.mark.asyncio
async def test_good_till_date_with_gtc_raises_before_anything_is_sent() -> None:
    adapter, rest = _adapter()
    with pytest.raises(ValueError, match="good_till_date"):
        await adapter.place_entry(**_entry_kwargs(time_in_force="GTC", good_till_date=_GTD_MS))
    assert rest.new_order_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [True, 1.5, "1789903200000", Decimal("1789903200000")])
async def test_non_int_good_till_date_raises_type_error(bad: Any) -> None:
    adapter, rest = _adapter()
    with pytest.raises(TypeError, match="good_till_date"):
        await adapter.place_entry(**_entry_kwargs(time_in_force="GTD", good_till_date=bad))
    assert rest.new_order_calls == []


@pytest.mark.asyncio
async def test_gtc_wire_is_unchanged_and_sends_no_good_till_date() -> None:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
        NewOrderSideEnum,
        NewOrderTimeInForceEnum,
        NewOrderTypeEnum,
    )

    adapter, rest = _adapter()
    await adapter.place_entry(**_entry_kwargs())
    policy = test_only_signed_call_policy()
    assert rest.new_order_calls == [
        {
            "recv_window": policy.recv_window_ms,
            "symbol": "BTCUSDT",
            "side": NewOrderSideEnum.BUY,
            "type": NewOrderTypeEnum.LIMIT,
            "position_side": "BOTH",
            "time_in_force": NewOrderTimeInForceEnum.GTC,
            "quantity": "0.004",
            "price": "101.20",
            "new_client_order_id": _CID,
        }
    ]


# --------------------------------------------------------------------------- #
# Task 3: executed quantity and average price on the order probe.
# --------------------------------------------------------------------------- #


def _query_payload(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "order_id": 987654,
        "status": "PARTIALLY_FILLED",
        "update_time": _UPDATE_MS,
        "executed_qty": "0.004",
        "avg_price": "101.20",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def _probe(payload: Any) -> OrderProbe:
    adapter, _ = _adapter(payload)
    return await adapter.query_order_by_client(symbol="BTCUSDT", orig_client_order_id=_CID)


@pytest.mark.asyncio
async def test_probe_carries_executed_quantity_and_average_price() -> None:
    probe = await _probe(_query_payload())
    assert probe.executed_quantity == Decimal("0.004")
    assert probe.average_price == Decimal("101.20")
    assert probe.status == "PARTIALLY_FILLED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "attribute"),
    [("executed_qty", "executed_quantity"), ("avg_price", "average_price")],
)
async def test_missing_field_is_none_never_zero(field: str, attribute: str) -> None:
    probe = await _probe(_query_payload(**{field: None}))
    assert getattr(probe, attribute) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["executed_qty", "avg_price"])
@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity", ""])
async def test_malformed_field_raises(field: str, bad: str) -> None:
    with pytest.raises(ValueError, match=field):
        await _probe(_query_payload(**{field: bad}))


@pytest.mark.asyncio
async def test_not_found_probe_keeps_both_fields_none() -> None:
    probe = await _probe(BadRequestError("Order does not exist.", -2013))
    assert probe.found is False
    assert probe.executed_quantity is None
    assert probe.average_price is None


def test_existing_constructions_of_order_probe_still_work() -> None:
    positional = OrderProbe("cid", True, "1", "NEW", None)
    keyword = OrderProbe(
        client_order_id="cid", found=True, order_id="1", status="NEW", update_time_utc=None
    )
    assert positional == keyword
    assert positional.executed_quantity is None and positional.average_price is None
