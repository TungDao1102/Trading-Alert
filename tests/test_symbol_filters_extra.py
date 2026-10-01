"""MARKET_LOT_SIZE and PERCENT_PRICE parsing into optional SymbolFilters fields.

Phase 17 plan 06 (EXEC-04, D-18, research C10): the adapter exposes the two
filters EXEC-04 names as trailing optional fields (no symbol_metadata column,
no migration). An absent filter is None; a present-but-malformed filter fails
closed with ValueError, never a silent None.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    ExchangeInformationResponse,
    ExchangeInformationResponseSymbolsInner,
    ExchangeInformationResponseSymbolsInnerFiltersInner,
)
from src.adapters.binance_usdm import BinanceUsdmAdapter, SymbolFilters

_FIXTURE = Path(__file__).parent / "fixtures" / "exchange_info_sample.json"
_EXTRA_FIELDS = (
    "market_lot_min_quantity",
    "market_lot_max_quantity",
    "market_lot_step_size",
    "percent_price_multiplier_up",
    "percent_price_multiplier_down",
    "percent_price_multiplier_decimals",
)


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _FakeRest:
    def __init__(self, info: Any) -> None:
        self._info = info

    def exchange_information(self) -> _FakeResponse:
        return _FakeResponse(self._info)


class _FakeSdk:
    def __init__(self, rest: _FakeRest) -> None:
        self.rest_api = rest


def _adapter(info: ExchangeInformationResponse) -> BinanceUsdmAdapter:
    return BinanceUsdmAdapter(sdk_client=_FakeSdk(_FakeRest(info)))  # type: ignore[arg-type]


def _parse(info: ExchangeInformationResponse) -> list[SymbolFilters]:
    return asyncio.run(_adapter(info).exchange_info())


def _raw_sample() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return loaded


def _info_from_raw(raw: dict[str, Any]) -> ExchangeInformationResponse:
    return ExchangeInformationResponse.from_dict(raw)


def _raw_filter(raw_symbol: dict[str, Any], filter_type: str) -> dict[str, Any]:
    for f in raw_symbol["filters"]:
        if f["filterType"] == filter_type:
            found: dict[str, Any] = f
            return found
    raise AssertionError(f"{filter_type} not in fixture symbol {raw_symbol['symbol']}")


def _drop_filters(raw: dict[str, Any], *filter_types: str) -> None:
    for sym in raw["symbols"]:
        sym["filters"] = [f for f in sym["filters"] if f["filterType"] not in filter_types]


def test_five_symbols_carry_market_lot_and_percent_price_decimals() -> None:
    raw = _raw_sample()
    parsed = {f.symbol: f for f in _parse(_info_from_raw(raw))}
    assert set(parsed) == {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
    for raw_symbol in raw["symbols"]:
        got = parsed[raw_symbol["symbol"]]
        lot = _raw_filter(raw_symbol, "MARKET_LOT_SIZE")
        pct = _raw_filter(raw_symbol, "PERCENT_PRICE")
        assert got.market_lot_min_quantity == Decimal(str(lot["minQty"]))
        assert got.market_lot_max_quantity == Decimal(str(lot["maxQty"]))
        assert got.market_lot_step_size == Decimal(str(lot["stepSize"]))
        assert got.percent_price_multiplier_up == Decimal(str(pct["multiplierUp"]))
        assert got.percent_price_multiplier_down == Decimal(str(pct["multiplierDown"]))
        assert got.percent_price_multiplier_decimals == int(pct["multiplierDecimal"])
        assert isinstance(got.market_lot_step_size, Decimal)
        assert isinstance(got.percent_price_multiplier_decimals, int)
        assert not isinstance(got.percent_price_multiplier_decimals, bool)


def test_btc_values_match_the_recorded_sample() -> None:
    btc = {f.symbol: f for f in _parse(_info_from_raw(_raw_sample()))}["BTCUSDT"]
    assert btc.market_lot_max_quantity == Decimal("120")
    assert btc.market_lot_step_size == Decimal("0.001")
    assert btc.percent_price_multiplier_up == Decimal("1.0500")
    assert btc.percent_price_multiplier_down == Decimal("0.9500")
    assert btc.percent_price_multiplier_decimals == 4


def test_absent_filters_leave_all_six_fields_none() -> None:
    raw = _raw_sample()
    _drop_filters(raw, "MARKET_LOT_SIZE", "PERCENT_PRICE")
    parsed = _parse(_info_from_raw(raw))
    assert len(parsed) == 5
    for filters in parsed:
        for name in _EXTRA_FIELDS:
            assert getattr(filters, name) is None, f"{filters.symbol}.{name}"
        # The required filters still parse: absence of the extras is not drift.
        assert filters.price_tick_size > Decimal("0")


def test_only_market_lot_absent_keeps_percent_price() -> None:
    raw = _raw_sample()
    _drop_filters(raw, "MARKET_LOT_SIZE")
    btc = {f.symbol: f for f in _parse(_info_from_raw(raw))}["BTCUSDT"]
    assert btc.market_lot_step_size is None
    assert btc.market_lot_min_quantity is None
    assert btc.market_lot_max_quantity is None
    assert btc.percent_price_multiplier_up == Decimal("1.0500")
    assert btc.percent_price_multiplier_decimals == 4


def _filter(filter_type: str, **fields: Any) -> ExchangeInformationResponseSymbolsInnerFiltersInner:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(filter_type=filter_type, **fields)


def _single_symbol_info(extra: list[Any]) -> ExchangeInformationResponse:
    base = [
        _filter("PRICE_FILTER", tick_size="0.10"),
        _filter("LOT_SIZE", step_size="0.001", min_qty="0.001", max_qty="1000"),
        _filter("MIN_NOTIONAL", notional="50"),
    ]
    symbol = ExchangeInformationResponseSymbolsInner(
        symbol="BTCUSDT",
        contract_type="PERPETUAL",
        status="TRADING",
        base_asset="BTC",
        quote_asset="USDT",
        margin_asset="USDT",
        filters=[*base, *extra],
    )
    return ExchangeInformationResponse(symbols=[symbol])


@pytest.mark.parametrize(
    "bad_filter",
    [
        # malformed numeric text
        _filter("MARKET_LOT_SIZE", min_qty="abc", max_qty="120", step_size="0.001"),
        _filter("MARKET_LOT_SIZE", min_qty="0.001", max_qty="1.2.3", step_size="0.001"),
        _filter("MARKET_LOT_SIZE", min_qty="0.001", max_qty="120", step_size=""),
        _filter("PERCENT_PRICE", multiplier_up="x", multiplier_down="0.95", multiplier_decimal="4"),
        _filter(
            "PERCENT_PRICE", multiplier_up="1.05", multiplier_down="nan", multiplier_decimal="4"
        ),
        _filter(
            "PERCENT_PRICE", multiplier_up="1.05", multiplier_down="0.95", multiplier_decimal="4.5"
        ),
        _filter(
            "PERCENT_PRICE", multiplier_up="1.05", multiplier_down="0.95", multiplier_decimal="-1"
        ),
        # a present filter missing a field
        _filter("MARKET_LOT_SIZE", min_qty="0.001", step_size="0.001"),
        _filter("MARKET_LOT_SIZE", max_qty="120", step_size="0.001"),
        _filter("MARKET_LOT_SIZE", min_qty="0.001", max_qty="120"),
        _filter("PERCENT_PRICE", multiplier_down="0.95", multiplier_decimal="4"),
        _filter("PERCENT_PRICE", multiplier_up="1.05", multiplier_decimal="4"),
        _filter("PERCENT_PRICE", multiplier_up="1.05", multiplier_down="0.95"),
    ],
)
def test_malformed_or_incomplete_filter_raises_value_error(bad_filter: Any) -> None:
    with pytest.raises(ValueError):
        _parse(_single_symbol_info([bad_filter]))


def test_wellformed_single_symbol_parses_through_the_same_path() -> None:
    info = _single_symbol_info(
        [
            _filter("MARKET_LOT_SIZE", min_qty="0.001", max_qty="120", step_size="0.001"),
            _filter(
                "PERCENT_PRICE",
                multiplier_up="1.05",
                multiplier_down="0.95",
                multiplier_decimal="4",
            ),
        ]
    )
    (parsed,) = _parse(info)
    assert parsed.market_lot_max_quantity == Decimal("120")
    assert parsed.percent_price_multiplier_decimals == 4


def test_new_fields_are_trailing_optional_with_none_defaults() -> None:
    """Existing positional/keyword construction of SymbolFilters keeps working."""
    import dataclasses

    fields = dataclasses.fields(SymbolFilters)
    names = [f.name for f in fields]
    tail = names[-len(_EXTRA_FIELDS) :]
    assert tuple(tail) == _EXTRA_FIELDS
    by_name = {f.name: f for f in fields}
    for name in _EXTRA_FIELDS:
        assert by_name[name].default is None
    assert names.index("delivery_date_ms") < names.index(_EXTRA_FIELDS[0])
